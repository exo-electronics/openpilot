"""Camera overlay rules, border overlay, and warnings."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from openpilot.selfdrive.ui.eop.components.blind_spot import (
  WARNING,
  BlindSpotSeverity,
)
from openpilot.selfdrive.ui.eop.components.border_overlay import (
  BorderOverlay,
  Mode,
  Side,
)
from openpilot.selfdrive.ui.eop.components.camera_overlay import (
  IDLE_BORDER_PX,
  WARN_BORDER_PX,
  Camera,
  CameraOverlayStack,
  active_camera,
  overlay_style,
)
from openpilot.selfdrive.ui.eop.components.warnings import (
  AdasWarning,
  WarningOverlay,
  blocks_engagement,
  highest,
)
from openpilot.selfdrive.ui.eop.qt import QApplication, QWidget
from openpilot.selfdrive.ui.eop.state import Snapshot


@pytest.fixture(scope="module")
def app():
  return QApplication.instance() or QApplication([])


class TestActiveCamera:
  def test_nothing_when_idle(self):
    assert active_camera(Snapshot()) is Camera.NONE

  def test_single_blinker_opens_that_side(self):
    assert active_camera(Snapshot(left_blinker=True)) is Camera.LEFT
    assert active_camera(Snapshot(right_blinker=True)) is Camera.RIGHT

  def test_hazards_open_nothing(self):
    # Both blinkers is hazards, not an intent to move sideways.
    snap = Snapshot(left_blinker=True, right_blinker=True)
    assert snap.hazards
    assert active_camera(snap) is Camera.NONE

  def test_reverse_shows_rear(self):
    assert active_camera(Snapshot(in_reverse=True)) is Camera.REAR

  def test_reverse_outranks_a_blinker(self):
    # Signalling while reversing must not steal the screen from the rear view.
    assert active_camera(Snapshot(in_reverse=True, left_blinker=True)) is Camera.REAR
    assert active_camera(Snapshot(in_reverse=True, right_blinker=True)) is Camera.REAR

  def test_reverse_beats_hazards_too(self):
    snap = Snapshot(in_reverse=True, left_blinker=True, right_blinker=True)
    assert active_camera(snap) is Camera.REAR


class TestOverlayStyle:
  def test_idle_border_when_clear(self):
    st = overlay_style(Camera.LEFT, BlindSpotSeverity())
    assert st.border_px == IDLE_BORDER_PX

  def test_border_widens_on_warning(self):
    st = overlay_style(Camera.LEFT, BlindSpotSeverity(left=WARNING))
    assert st.border_px == WARN_BORDER_PX

  def test_only_the_matching_side_escalates(self):
    bs = BlindSpotSeverity(left=WARNING)
    assert overlay_style(Camera.RIGHT, bs).border_px == IDLE_BORDER_PX
    assert overlay_style(Camera.LEFT, bs).border_px == WARN_BORDER_PX

  def test_rear_ignores_blind_spot(self):
    bs = BlindSpotSeverity(left=WARNING, right=WARNING)
    assert overlay_style(Camera.REAR, bs).border_px == IDLE_BORDER_PX


class TestOverlayStack:
  def _stack(self, app):
    host = QWidget()
    host.resize(1600, 600)
    st = CameraOverlayStack(host)
    st.resize(1600, 600)
    host.show()
    QApplication.processEvents()
    self._host = host
    return st

  def test_at_most_one_visible(self, app):
    st = self._stack(app)
    for snap in (Snapshot(left_blinker=True), Snapshot(in_reverse=True), Snapshot()):
      st.set_snapshot(snap)
      QApplication.processEvents()
      assert sum(1 for o in st._overlays.values() if o.isVisible()) <= 1

  def test_tracks_the_active_camera(self, app):
    st = self._stack(app)
    st.set_snapshot(Snapshot(right_blinker=True))
    assert st.active is Camera.RIGHT
    st.set_snapshot(Snapshot())
    assert st.active is Camera.NONE

  def test_overlays_fill_the_view(self, app):
    st = self._stack(app)
    assert all(o.size() == st.size() for o in st._overlays.values())


class TestBorderOverlay:
  @pytest.fixture(autouse=True)
  def isolate(self):
    """BorderOverlay's blink clock is deliberately shared across every
    instance, so instances left alive by earlier tests keep it running. Clear
    the registry around each test rather than asserting against whatever the
    rest of the suite happens to have created."""
    BorderOverlay._stop_timer()
    saved = BorderOverlay._instances
    BorderOverlay._instances = []
    yield
    BorderOverlay._stop_timer()
    BorderOverlay._instances = saved

  def test_disabled_by_default(self, app):
    host = QWidget()
    b = BorderOverlay(Side.LEFT, "caution", parent=host)
    assert not b.is_enabled()

  def test_blink_timer_only_runs_when_needed(self, app):
    BorderOverlay._stop_timer()
    host = QWidget()
    b = BorderOverlay(Side.LEFT, "warning", Mode.BLINK, parent=host)
    assert BorderOverlay._timer is None
    b.set_enabled(True)
    assert BorderOverlay._timer is not None
    b.set_enabled(False)
    BorderOverlay._tick()          # next tick notices nothing blinks
    assert BorderOverlay._timer is None

  def test_solid_mode_needs_no_timer(self, app):
    BorderOverlay._stop_timer()
    host = QWidget()
    b = BorderOverlay(Side.RIGHT, "caution", Mode.SOLID, parent=host)
    b.set_enabled(True)
    assert BorderOverlay._timer is None

  def test_dead_instances_are_swept(self, app):
    import gc
    host = QWidget()
    BorderOverlay(Side.LEFT, "caution", parent=host)
    assert len(BorderOverlay._live()) == 1

    del host
    gc.collect()
    # _live() is what prunes, and it must drop the dead entry rather than hand
    # the shared timer a reference to call update() on -- that was the leak in
    # nagasware's version, where the list was only pruned in closeEvent and
    # child widgets never get one.
    assert BorderOverlay._live() == []
    assert BorderOverlay._instances == []


class TestWarnings:
  def test_crash_outranks_everything(self):
    active = [AdasWarning.GPS_FAULT, AdasWarning.DOOR_OPEN, AdasWarning.CRASH_DETECTED]
    assert highest(active) is AdasWarning.CRASH_DETECTED

  def test_none_when_empty(self):
    assert highest([]) is None

  def test_blocking_is_not_the_same_as_undismissable(self):
    # CALIBRATION_REQUIRED blocks engagement but may be dismissed from the
    # screen; collapsing the two would make that state inexpressible.
    w = AdasWarning.CALIBRATION_REQUIRED
    assert w.blocking and w.dismissible

  def test_degraded_states_do_not_block(self):
    for w in (AdasWarning.GPS_FAULT, AdasWarning.TIRE_MONITOR,
              AdasWarning.CALIBRATION_DEGRADED):
      assert not w.blocking

  def test_blocks_engagement_any(self):
    assert not blocks_engagement([AdasWarning.GPS_FAULT])
    assert blocks_engagement([AdasWarning.GPS_FAULT, AdasWarning.DOOR_OPEN])

  def test_keys_are_unique(self):
    keys = [w.key for w in AdasWarning]
    assert len(keys) == len(set(keys))

  def test_from_key_roundtrip(self):
    for w in AdasWarning:
      assert AdasWarning.from_key(w.key) is w
    assert AdasWarning.from_key("nope") is None

  def test_dismiss_only_affects_dismissable(self, app):
    ov = WarningOverlay()
    ov.set_active([AdasWarning.DOOR_OPEN])
    ov.dismiss_current()
    assert ov.current() is AdasWarning.DOOR_OPEN     # not dismissable

    ov.set_active([AdasWarning.GPS_FAULT])
    ov.dismiss_current()
    assert ov.current() is None

  def test_dismissal_forgotten_when_warning_clears(self, app):
    ov = WarningOverlay()
    ov.set_active([AdasWarning.GPS_FAULT])
    ov.dismiss_current()
    assert ov.current() is None
    ov.set_active([])                 # goes away
    ov.set_active([AdasWarning.GPS_FAULT])   # and comes back
    assert ov.current() is AdasWarning.GPS_FAULT
