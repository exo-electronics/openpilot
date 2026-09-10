"""UI state: one SubMaster, one timer, Qt signals out.

This is the *only* module in the UI that touches messaging. Widgets take plain
values and emit plain signals, which is what keeps them testable without capnp
and the integration surface small enough to reason about (plan section 5.2).

One SubMaster, shared -- not one per bridge. That bug has already been paid
for once in this codebase, in ncp_session.py, where multiple PubMaster
instances for the same service crashed msgq on boot; the subscribe side has
the same shape, and openpilot's own selfdrive/ui/ui_state.py has always used a
single shared SubMaster.

`cereal` is imported lazily inside _default_submaster() rather than at module
scope, so importing this module does not require a built capnp. Tests inject
their own source.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from openpilot.selfdrive.ui.eop.components.blind_spot import (
  BlindSpotSeverity,
  fuse_blind_spot,
)
from openpilot.selfdrive.ui.eop.qt import QObject, QTimer, Signal

UI_FREQ_HZ = 20

# Everything the UI reads. Deliberately explicit: a SubMaster subscribes to
# what it is told to, and an over-broad list costs wakeups at 20 Hz for the
# whole onroad session.
SERVICES = [
  "carState",
  "controlsState",
  "selfdriveState",
  "deviceState",
  "modelV2",
  "radarState",
  "longitudinalPlan",
  "liveCalibration",
  "managerState",
  "onroadEvents",
]


class UIStatus(Enum):
  DISENGAGED = "disengaged"
  ENGAGED = "engaged"
  OVERRIDE = "override"


@dataclass(frozen=True)
class Snapshot:
  """What the views actually read. A frozen value object rather than live
  capnp readers, so a widget can never accidentally hold a reference into a
  buffer that has since been recycled."""
  started: bool = False
  status: UIStatus = UIStatus.DISENGAGED
  v_ego: float = 0.0
  left_blinker: bool = False
  right_blinker: bool = False
  in_reverse: bool = False
  blind_spot: BlindSpotSeverity = BlindSpotSeverity()

  @property
  def hazards(self) -> bool:
    """Both blinkers. Not an intent to move sideways, so the camera overlays
    deliberately do nothing here -- see plan section 5.7."""
    return self.left_blinker and self.right_blinker


def _default_submaster():
  from cereal import messaging
  return messaging.SubMaster(SERVICES)


class UIState(QObject):
  """Polls the SubMaster on a timer and publishes an immutable Snapshot."""

  updated = Signal(object)            # Snapshot
  offroad_transition = Signal(bool)   # True when going offroad

  def __init__(self, sm=None, parent=None):
    super().__init__(parent)
    self._sm = sm if sm is not None else _default_submaster()
    self._snapshot = Snapshot()
    self._timer = QTimer(self)
    self._timer.setInterval(int(1000 / UI_FREQ_HZ))
    self._timer.timeout.connect(self.update)

  # ---- lifecycle --------------------------------------------------------

  def start(self) -> None:
    if not self._timer.isActive():
      self._timer.start()

  def stop(self) -> None:
    self._timer.stop()

  @property
  def snapshot(self) -> Snapshot:
    return self._snapshot

  # ---- polling ----------------------------------------------------------

  def update(self) -> None:
    self._sm.update(0)
    new = self._read()
    was_started = self._snapshot.started
    self._snapshot = new
    if new.started != was_started:
      self.offroad_transition.emit(not new.started)
    self.updated.emit(new)

  def _read(self) -> Snapshot:
    sm = self._sm

    started = False
    status = UIStatus.DISENGAGED
    if sm.valid("selfdriveState"):
      ss = sm["selfdriveState"]
      started = bool(ss.enabled) or bool(getattr(ss, "active", False))
      if ss.enabled:
        status = UIStatus.OVERRIDE if getattr(ss, "overrideLateral", False) else UIStatus.ENGAGED

    v_ego = 0.0
    left_blinker = right_blinker = in_reverse = False
    car_left = car_right = False
    if sm.valid("carState"):
      cs = sm["carState"]
      v_ego = float(cs.vEgo)
      left_blinker = bool(cs.leftBlinker)
      right_blinker = bool(cs.rightBlinker)
      in_reverse = str(cs.gearShifter) == "reverse"
      car_left = bool(cs.leftBlindspot)
      car_right = bool(cs.rightBlindspot)

    ctrl_left = ctrl_right = 0
    if sm.valid("controlsState"):
      ctrl = sm["controlsState"]
      ctrl_left = int(getattr(ctrl, "leftBlindSpot", 0))
      ctrl_right = int(getattr(ctrl, "rightBlindSpot", 0))

    # Note the 0/False defaults above: a source that is not currently valid
    # contributes nothing rather than being skipped, so a stale WARNING cannot
    # outlive the message that raised it. fuse_blind_spot()'s max() only ever
    # raises, which is exactly why that matters.
    return Snapshot(
      started=started,
      status=status,
      v_ego=v_ego,
      left_blinker=left_blinker,
      right_blinker=right_blinker,
      in_reverse=in_reverse,
      blind_spot=fuse_blind_spot(ctrl_left, ctrl_right, car_left, car_right),
    )
