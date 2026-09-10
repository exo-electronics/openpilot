"""Onroad view.

The camera fills the view; everything else floats over it. Layout is by
explicit geometry rather than a QLayout because the overlays deliberately do
not take space -- they cover. Plan sections 5.6 and 5.7.

The camera surface itself is a placeholder here. Wiring it to VisionIPC is P1
(plan section 4.3), and it is deliberately the *last* thing added rather than
the first: the spike has to establish which Qt platform plugin the device runs
and whether a QOpenGLWidget composites with QWidget chrome under EGLFS before
any of this is built on top of it.
"""

from __future__ import annotations

from openpilot.selfdrive.ui.eop.components.blind_spot import BlindSpotBands
from openpilot.selfdrive.ui.eop.components.camera_overlay import CameraOverlayStack
from openpilot.selfdrive.ui.eop.qt import Qt, QColor, QPainter, QWidget
from openpilot.selfdrive.ui.eop.state import Snapshot

# The 1600x600 panel, split 50 / 500 / 50 (plan section 5.4).
PANEL_W, PANEL_H = 1600, 600
BAR_H = 50


class CameraSurface(QWidget):
  """Placeholder for the road camera.

  Paints flat black with a centred label so the view is honest about what is
  and is not wired: an empty widget would look like a rendering bug, and a
  fake road image would look like it worked.
  """

  def __init__(self, parent=None):
    super().__init__(parent)
    self.setAttribute(Qt.WA_OpaquePaintEvent, True)

  def paintEvent(self, event):
    p = QPainter(self)
    p.fillRect(self.rect(), QColor(0, 0, 0))
    p.setPen(QColor(60, 72, 74))
    p.drawText(self.rect(), Qt.AlignCenter, "camera: not wired (P1)")


class OnroadView(QWidget):
  """Camera, with the blind-spot bands over it."""

  def __init__(self, parent=None):
    super().__init__(parent)
    self.setObjectName("onroadRoot")

    self.camera = CameraSurface(self)
    self.bands = BlindSpotBands(self)
    # A side or rear overlay covers the whole view, so it sits above the
    # bands -- which is exactly why the blind-spot warning has to move onto
    # the overlay's own border while one is up (plan section 5.7).
    self.overlays = CameraOverlayStack(self)
    self.bands.raise_()
    self.overlays.raise_()

  def set_snapshot(self, snap: Snapshot) -> None:
    self.bands.set_severity(snap.blind_spot)
    self.overlays.set_snapshot(snap)

  def _layout(self) -> None:
    self.camera.setGeometry(self.rect())
    self.bands.setGeometry(self.rect())
    self.overlays.setGeometry(self.rect())

  def resizeEvent(self, event):
    super().resizeEvent(event)
    self._layout()

  def showEvent(self, event):
    # A widget that has never been shown receives no resizeEvent at all -- not
    # queued, not delivered by processEvents(). Laying out again on show is
    # what stops children sitting at their default 100x30 forever.
    super().showEvent(event)
    self._layout()
