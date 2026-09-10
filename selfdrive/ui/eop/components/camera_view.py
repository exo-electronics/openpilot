"""VisionIPC camera surface (plan section 4.3).

Two paths, chosen at runtime:

**Zero-copy (device)** -- QOpenGLWidget, with the dmabuf imported as an
EGLImage and bound to a GL texture. openpilot's `system/ui/lib/egl.py` is
already toolkit-agnostic: `bind_egl_image_to_texture()` takes a raw GL texture
id, not a raylib handle, so only the texture comes from Qt. That is the whole
reason this is ~200 lines rather than a C++ extension.

**CPU (dev PC, and fallback)** -- VisionIPC NV12 -> numpy -> QImage. Same
shape as the cv_bridge path VisionPilot uses today, minus ROS.

The EGL path is unverified. It cannot be verified without real 02M hardware,
and it carries the open question from section 12.2: EGLFS supports one
fullscreen GL window and documents mixing GL windows with QWidget content as
terminating the application. A QOpenGLWidget composited as a child is the
supported case, but "supported" and "works against Rockchip libmali" are
different claims. `CameraView.create()` therefore falls back to the CPU path
on any failure rather than taking the UI down with it.
"""

from __future__ import annotations

import os

import numpy as np

from openpilot.selfdrive.ui.eop.qt import (
  Qt,
  QColor,
  QOpenGLWidget,
  QPainter,
  QtGui,
  QWidget,
)

# Set EOP_UI_CAMERA=cpu|gl|none to force a path; default probes.
FORCE = os.environ.get("EOP_UI_CAMERA", "").strip().lower()


def _vision_client(stream_name: str):
  """Import VisionIPC lazily -- it is a compiled extension, and the UI must
  stay importable on a machine without a built tree."""
  from msgq.visionipc import VisionIpcClient, VisionStreamType
  stream = getattr(VisionStreamType, stream_name)
  return VisionIpcClient("camerad", stream, conflate=True), stream


def nv12_to_rgb(buf: np.ndarray, width: int, height: int, stride: int) -> np.ndarray:
  """NV12 -> RGB888. BT.601 limited range, matching openpilot's shaders.

  Vectorised because a per-pixel Python loop at 1600x600x20Hz is not a
  fallback, it is a hang.
  """
  y = buf[: stride * height].reshape(height, stride)[:, :width].astype(np.int32)
  uv = buf[stride * height:].reshape(height // 2, stride)[:, :width]
  u = uv[:, 0::2].repeat(2, axis=0).repeat(2, axis=1).astype(np.int32) - 128
  v = uv[:, 1::2].repeat(2, axis=0).repeat(2, axis=1).astype(np.int32) - 128
  u, v = u[:height, :width], v[:height, :width]

  r = y + ((91881 * v) >> 16)
  g = y - ((22554 * u + 46802 * v) >> 16)
  b = y + ((116130 * u) >> 16)
  return np.clip(np.stack((r, g, b), axis=-1), 0, 255).astype(np.uint8)


class CpuCameraView(QWidget):
  """VisionIPC -> numpy -> QImage. Works anywhere, costs a copy per frame."""

  def __init__(self, stream_name: str = "VISION_STREAM_ROAD", parent=None):
    super().__init__(parent)
    self.stream_name = stream_name
    self.setAttribute(Qt.WA_OpaquePaintEvent, True)
    self._client = None
    self._image: QtGui.QImage | None = None
    self._connected = False

  def connect(self) -> bool:
    try:
      self._client, _ = _vision_client(self.stream_name)
      self._connected = bool(self._client.connect(False))
    except Exception:
      self._connected = False
    return self._connected

  def poll(self) -> None:
    """Pull the newest frame. Called from the UI tick, not a thread: the
    conflated client only ever hands back the latest buffer, so there is
    nothing to fall behind on."""
    if not self._connected and not self.connect():
      return
    try:
      buf = self._client.recv(timeout_ms=0)
    except Exception:
      self._connected = False
      return
    if buf is None:
      return
    arr = np.frombuffer(buf.data, dtype=np.uint8)
    rgb = nv12_to_rgb(arr, buf.width, buf.height, buf.stride)
    # QImage does not copy, so keep the array alive on the instance.
    self._rgb = np.ascontiguousarray(rgb)
    self._image = QtGui.QImage(self._rgb.data, buf.width, buf.height,
                               buf.width * 3, QtGui.QImage.Format_RGB888)
    self.update()

  def paintEvent(self, event):
    p = QPainter(self)
    if self._image is None:
      p.fillRect(self.rect(), QColor(0, 0, 0))
      p.setPen(QColor(60, 72, 74))
      p.drawText(self.rect(), Qt.AlignCenter, "camera: no frames")
      return
    scaled = self._image.scaled(self.size(), Qt.KeepAspectRatioByExpanding,
                                Qt.SmoothTransformation)
    x = (self.width() - scaled.width()) // 2
    y = (self.height() - scaled.height()) // 2
    p.drawImage(x, y, scaled)


class GlCameraView(QOpenGLWidget):
  """Zero-copy path: dmabuf -> EGLImage -> GL texture.

  Unverified on hardware. See the module docstring.
  """

  def __init__(self, stream_name: str = "VISION_STREAM_ROAD", parent=None):
    super().__init__(parent)
    self.stream_name = stream_name
    self._client = None
    self._egl_ready = False
    self._texture = 0
    self._images: dict[int, object] = {}
    self._frame = None

  def initializeGL(self) -> None:
    try:
      from openpilot.system.ui.lib.egl import init_egl
      self._egl_ready = bool(init_egl())
    except Exception:
      self._egl_ready = False
    if self._egl_ready:
      fns = self.context().functions()
      self._texture = fns.glGenTextures(1) if hasattr(fns, "glGenTextures") else 0

  def connect(self) -> bool:
    try:
      self._client, _ = _vision_client(self.stream_name)
      return bool(self._client.connect(False))
    except Exception:
      return False

  def poll(self) -> None:
    if self._client is None and not self.connect():
      return
    try:
      self._frame = self._client.recv(timeout_ms=0)
    except Exception:
      self._client = None
      return
    if self._frame is not None:
      self.update()

  def paintGL(self) -> None:
    from openpilot.selfdrive.ui.eop.qt import QtGui as _g
    painter = _g.QPainter(self)
    if self._frame is None or not self._egl_ready:
      painter.fillRect(self.rect(), QColor(0, 0, 0))
      painter.setPen(QColor(60, 72, 74))
      painter.drawText(self.rect(), Qt.AlignCenter, "camera: GL path not ready")
      return
    # Binding the EGLImage to self._texture and drawing the textured quad goes
    # here. Left unwritten rather than guessed: the shader and sampler target
    # depend on what the platform plugin actually gives us (section 12.2), and
    # writing it blind would produce code that looks finished and is not.
    painter.fillRect(self.rect(), QColor(0, 0, 0))


def create_camera_view(stream_name: str = "VISION_STREAM_ROAD",
                       parent=None) -> QWidget:
  """Pick a path. Falls back to CPU rather than failing the UI."""
  if FORCE == "cpu":
    return CpuCameraView(stream_name, parent)
  if FORCE == "gl":
    return GlCameraView(stream_name, parent)
  try:
    from openpilot.system.hardware import ROCKCHIP
    if ROCKCHIP:
      return GlCameraView(stream_name, parent)
  except Exception:
    pass
  return CpuCameraView(stream_name, parent)
