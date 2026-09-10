"""DVR playback.

From Nagasware's `dvr_video_player.py`, which is the only source with one.
Retargeted: nagasware drives its own recorder thread, while here `recordd`
already owns recording and segment rotation, so this is a browser and player
over what recordd wrote -- not a second recorder.

Segments are read off disk rather than through a message: a UI that asks a
daemon to list files is a round trip for information the filesystem already
has, and it must keep working when recordd is not running, which is exactly
when someone wants to review footage.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from openpilot.selfdrive.ui.eop.qt import Qt, QtWidgets, QWidget, Signal

# Where recordd writes. Overridable for a dev machine.
SEGMENT_ROOT = Path(os.environ.get("EOP_DVR_ROOT", "/data/media/0/realdata"))
VIDEO_SUFFIXES = (".hevc", ".mp4", ".ts")


@dataclass(frozen=True)
class Segment:
  path: Path
  started: datetime
  size_mb: float
  camera: str

  @property
  def label(self) -> str:
    return f"{self.started:%Y-%m-%d  %H:%M:%S}   {self.camera}   {self.size_mb:.0f} MB"


def scan_segments(root: Path = SEGMENT_ROOT, limit: int = 200) -> list[Segment]:
  """Newest first. Tolerates a missing or unreadable root -- an empty list is
  a correct answer for a device that has not recorded anything yet."""
  if not root.exists():
    return []
  found: list[Segment] = []
  try:
    for path in root.rglob("*"):
      if path.suffix.lower() not in VIDEO_SUFFIXES or not path.is_file():
        continue
      try:
        stat = path.stat()
      except OSError:
        continue
      found.append(Segment(
        path=path,
        started=datetime.fromtimestamp(stat.st_mtime),
        size_mb=stat.st_size / (1024 * 1024),
        camera=path.stem.replace("_", " "),
      ))
      if len(found) >= limit * 4:
        break
  except OSError:
    return found
  found.sort(key=lambda s: s.started, reverse=True)
  return found[:limit]


class PlaybackSurface(QWidget):
  """Where decoded frames go.

  Decoding is not wired. On the device this should go through MPP (openpilot
  publishes `mppStatus`, so the hardware decoder is already a known quantity)
  rather than a software decoder that would compete with the driving model
  for CPU. Wiring it is the same shape of problem as the camera path in
  section 4.3, and belongs after it.
  """

  def __init__(self, parent=None):
    super().__init__(parent)
    self.setObjectName("dvrSurface")
    self.setAttribute(Qt.WA_OpaquePaintEvent, True)
    self._segment: Segment | None = None

  def set_segment(self, segment: Segment | None) -> None:
    self._segment = segment
    self.update()

  def paintEvent(self, event):
    from openpilot.selfdrive.ui.eop.qt import QColor, QPainter
    p = QPainter(self)
    p.fillRect(self.rect(), QColor(0, 0, 0))
    p.setPen(QColor(60, 72, 74))
    text = ("no segment selected" if self._segment is None
            else f"{self._segment.path.name}\ndecode not wired (MPP)")
    p.drawText(self.rect(), Qt.AlignCenter, text)


class DvrView(QWidget):
  """Segment list beside a playback surface."""

  segment_selected = Signal(object)

  def __init__(self, root: Path = SEGMENT_ROOT, parent=None):
    super().__init__(parent)
    self.setObjectName("dvrRoot")
    self._root = root
    self.segments: list[Segment] = []

    lay = QtWidgets.QHBoxLayout(self)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(16)

    left = QtWidgets.QVBoxLayout()
    self.list = QtWidgets.QListWidget()
    self.list.setObjectName("dvrList")
    self.list.currentRowChanged.connect(self._on_row)
    left.addWidget(self.list, 1)

    refresh = QtWidgets.QPushButton("Refresh")
    refresh.clicked.connect(self.refresh)
    self.status = QtWidgets.QLabel("")
    self.status.setObjectName("dvrStatus")
    left.addWidget(self.status)
    left.addWidget(refresh)
    lay.addLayout(left, 0)

    self.surface = PlaybackSurface(self)
    lay.addWidget(self.surface, 1)

    self.refresh()

  def refresh(self) -> None:
    self.segments = scan_segments(self._root)
    self.list.clear()
    for seg in self.segments:
      self.list.addItem(seg.label)
    total = sum(s.size_mb for s in self.segments)
    self.status.setText(
      f"{len(self.segments)} segments · {total / 1024:.1f} GB"
      if self.segments else f"no recordings under {self._root}")

  def _on_row(self, row: int) -> None:
    seg = self.segments[row] if 0 <= row < len(self.segments) else None
    self.surface.set_segment(seg)
    self.segment_selected.emit(seg)
