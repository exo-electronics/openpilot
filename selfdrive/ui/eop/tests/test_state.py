"""UIState polling and snapshot derivation.

Uses a stub SubMaster rather than a mock framework: the real one is a dict-like
with valid()/update(), so a small hand-written double is both more honest about
the contract and readable when it fails.
"""

import dataclasses
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from openpilot.selfdrive.ui.eop.components.blind_spot import CAUTION, CLEAR, WARNING
from openpilot.selfdrive.ui.eop.qt import QApplication
from openpilot.selfdrive.ui.eop.state import Snapshot, UIState, UIStatus


class Msg:
  """Stand-in for a capnp reader: attribute access over a dict."""
  def __init__(self, **fields):
    self.__dict__.update(fields)


class StubSM:
  def __init__(self, **msgs):
    self._msgs = msgs
    self._valid = dict.fromkeys(msgs, True)
    self.update_calls = 0

  def update(self, _timeout=0):
    self.update_calls += 1

  def valid(self, name):
    return self._valid.get(name, False)

  def invalidate(self, name):
    self._valid[name] = False

  def __getitem__(self, name):
    return self._msgs[name]


def car(**kw):
  base = dict(vEgo=0.0, leftBlinker=False, rightBlinker=False,
              gearShifter="drive", leftBlindspot=False, rightBlindspot=False)
  base.update(kw)
  return Msg(**base)


def controls(left=0, right=0):
  return Msg(leftBlindSpot=left, rightBlindSpot=right)


def selfdrive(enabled=False, active=False, overrideLateral=False):
  return Msg(enabled=enabled, active=active, overrideLateral=overrideLateral)


@pytest.fixture(scope="module")
def app():
  return QApplication.instance() or QApplication([])


class TestSnapshot:
  def test_defaults_are_safe(self):
    s = Snapshot()
    assert not s.started and s.status is UIStatus.DISENGAGED
    assert s.blind_spot.left == CLEAR and not s.hazards

  def test_hazards_needs_both_blinkers(self):
    assert not Snapshot(left_blinker=True).hazards
    assert not Snapshot(right_blinker=True).hazards
    assert Snapshot(left_blinker=True, right_blinker=True).hazards


class TestUIState:
  def test_polls_the_submaster(self, app):
    sm = StubSM(carState=car())
    st = UIState(sm=sm)
    st.update()
    assert sm.update_calls == 1

  def test_reads_car_state(self, app):
    sm = StubSM(carState=car(vEgo=13.5, leftBlinker=True, gearShifter="reverse"))
    st = UIState(sm=sm)
    st.update()
    snap = st.snapshot
    assert snap.v_ego == pytest.approx(13.5)
    assert snap.left_blinker and not snap.right_blinker
    assert snap.in_reverse

  def test_engaged_status(self, app):
    sm = StubSM(selfdriveState=selfdrive(enabled=True))
    st = UIState(sm=sm)
    st.update()
    assert st.snapshot.status is UIStatus.ENGAGED
    assert st.snapshot.started

  def test_override_status(self, app):
    sm = StubSM(selfdriveState=selfdrive(enabled=True, overrideLateral=True))
    st = UIState(sm=sm)
    st.update()
    assert st.snapshot.status is UIStatus.OVERRIDE

  def test_blind_spot_is_fused_from_both_sources(self, app):
    sm = StubSM(carState=car(rightBlindspot=True), controlsState=controls(left=WARNING))
    st = UIState(sm=sm)
    st.update()
    bs = st.snapshot.blind_spot
    assert bs.left == WARNING   # from controlsState severity
    assert bs.right == CAUTION  # raised by carState's bool

  def test_invalid_controls_state_clears_rather_than_sticking(self, app):
    # The failure this guards: a severity-2 that outlives the message that
    # raised it, because fuse's max() can only raise.
    sm = StubSM(carState=car(), controlsState=controls(left=WARNING))
    st = UIState(sm=sm)
    st.update()
    assert st.snapshot.blind_spot.left == WARNING
    sm.invalidate("controlsState")
    st.update()
    assert st.snapshot.blind_spot.left == CLEAR

  def test_missing_services_do_not_raise(self, app):
    st = UIState(sm=StubSM())
    st.update()
    assert st.snapshot == Snapshot()

  def test_emits_updated_with_the_snapshot(self, app):
    sm = StubSM(carState=car(vEgo=7.0))
    st = UIState(sm=sm)
    seen = []
    st.updated.connect(seen.append)
    st.update()
    assert len(seen) == 1 and seen[0].v_ego == pytest.approx(7.0)

  def test_offroad_transition_fires_only_on_change(self, app):
    sm = StubSM(selfdriveState=selfdrive(enabled=False))
    st = UIState(sm=sm)
    seen = []
    st.offroad_transition.connect(seen.append)

    st.update()
    assert seen == []                      # already offroad, no edge

    sm._msgs["selfdriveState"] = selfdrive(enabled=True)
    st.update()
    assert seen == [False]                 # went onroad

    st.update()
    assert seen == [False]                 # no repeat while unchanged

    sm._msgs["selfdriveState"] = selfdrive(enabled=False)
    st.update()
    assert seen == [False, True]           # back offroad

  def test_timer_is_not_running_until_started(self, app):
    st = UIState(sm=StubSM())
    assert not st._timer.isActive()
    st.start()
    assert st._timer.isActive()
    st.stop()
    assert not st._timer.isActive()

  def test_snapshot_is_immutable(self, app):
    st = UIState(sm=StubSM(carState=car()))
    st.update()
    # frozen dataclass -> FrozenInstanceError, a subclass of AttributeError.
    # Naming it matters: a bare Exception here would also pass if the attribute
    # simply did not exist, which is the opposite of what this asserts.
    with pytest.raises(dataclasses.FrozenInstanceError):
      st.snapshot.v_ego = 99.0
