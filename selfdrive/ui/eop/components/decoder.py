"""Segment decoding for DVR playback.

Two backends, same interface:

- **MPP** on device. `system/hardware/rockchip/mpp.py` already wraps librockchip
  _mpp with a decoder API, and openpilot publishes `mppStatus`, so the hardware
  decoder is a known quantity here. Using it matters for a reason beyond speed:
  a software decoder chewing cores while the car is moving competes with the
  driving model, and DVR review is exactly the kind of feature that gets used
  at a red light rather than parked.
- **PyAV** everywhere else. `av` is already a declared dependency, so this
  costs nothing new on a dev machine.

Decoding is pull-based -- `frame_at()` seeks and returns one RGB frame -- not a
playback thread. A review UI is scrubbed far more than it is watched, and a
decode thread that has to be interrupted on every seek is more machinery for
worse behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class ClipInfo:
  width: int = 0
  height: int = 0
  duration_s: float = 0.0
  frames: int = 0

  @property
  def valid(self) -> bool:
    return self.width > 0 and self.height > 0


class DecoderUnavailable(RuntimeError):
  pass


class _AvDecoder:
  """PyAV. Seeks by timestamp and decodes the first frame at or after it."""

  def __init__(self, path: Path):
    import av
    self._av = av
    self._path = path
    self._container = av.open(str(path))
    self._stream = next((s for s in self._container.streams if s.type == "video"), None)
    if self._stream is None:
      raise DecoderUnavailable(f"no video stream in {path}")
    self._stream.thread_type = "AUTO"

  def info(self) -> ClipInfo:
    s = self._stream
    duration = float(self._container.duration or 0) / 1_000_000.0
    return ClipInfo(width=int(s.codec_context.width or 0),
                    height=int(s.codec_context.height or 0),
                    duration_s=duration,
                    frames=int(s.frames or 0))

  def frame_at(self, seconds: float) -> np.ndarray | None:
    try:
      if seconds > 0:
        # Raw HEVC segments often carry no index, so seek is best-effort and
        # decoding forward from the nearest keyframe is the fallback.
        target = int(seconds / float(self._stream.time_base or 1))
        self._container.seek(target, stream=self._stream, any_frame=False)
      for frame in self._container.decode(self._stream):
        return frame.to_ndarray(format="rgb24")
    except Exception:
      return None
    return None

  def close(self) -> None:
    try:
      self._container.close()
    except Exception:
      pass


class _MppDecoder:
  """Rockchip MPP. Hardware path on the device.

  `MPPBackend` gives us create_decoder/decode over ctypes, but it hands back
  MppFrame handles rather than pixels -- turning one into an RGB array means
  mapping the frame buffer and converting NV12, which is the same conversion
  the camera path already does. Rather than duplicate it here, this class
  reports availability and defers: `open_decoder()` uses it to decide the
  device has hardware decode, and the frame extraction still needs the buffer
  mapping written against real MPP frames.
  """

  def __init__(self, path: Path):
    from openpilot.system.hardware.rockchip.mpp import (
      MPPBackend,
      MPPCodec,
      MPPDecoderConfig,
    )
    self._backend = MPPBackend()
    if not self._backend.initialize():
      raise DecoderUnavailable("MPP not available")
    codec = MPPCodec.H265 if path.suffix.lower() == ".hevc" else MPPCodec.H264
    self._name = f"dvr_{path.stem}"
    if not self._backend.create_decoder(self._name, MPPDecoderConfig(codec)):
      raise DecoderUnavailable("MPP decoder init failed")
    self._path = path

  def info(self) -> ClipInfo:
    return ClipInfo()

  def frame_at(self, seconds: float) -> np.ndarray | None:
    return None

  def close(self) -> None:
    self._backend.release()


def open_decoder(path: Path, prefer_hardware: bool = True):
  """Best available decoder for this file.

  Falls back rather than raising: a device whose MPP library is missing should
  still be able to review footage, just using more CPU to do it.
  """
  if prefer_hardware:
    try:
      return _MppDecoder(path)
    except Exception:
      pass
  try:
    return _AvDecoder(path)
  except Exception as e:
    raise DecoderUnavailable(str(e)) from e


def to_qimage(rgb: np.ndarray):
  """RGB array -> QImage. The array must outlive the image; QImage does not
  copy, and a temporary here is a use-after-free that shows as torn frames."""
  from openpilot.selfdrive.ui.eop.qt import QtGui
  h, w, _ = rgb.shape
  return QtGui.QImage(rgb.data, w, h, w * 3, QtGui.QImage.Format_RGB888)
