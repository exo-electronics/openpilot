"""Qt binding shim.

The target is **Ubuntu 22.04 on RK3576**, where the binding to use is
**PySide2** (`python3-pyside2`, 5.15.2, in jammy universe and built for
arm64). PySide6 is not in jammy at all and has no official aarch64 wheels, so
using it there means building Shiboken and PySide from source on the device or
in a cross-toolchain -- hours of build for no gain, since the device already
runs Qt 5.15 for the existing C++ UI. See docs/eop10/EOP10_PORT_PLAN.md
section 12.1.

Development machines are frequently newer than the target and carry PySide6
instead, so this module resolves whichever is present rather than pinning one.
It is deliberately about thirty lines and not a general abstraction layer --
QtPy exists for that. It normalises only the differences this UI actually
touches:

- `QOpenGLWidget` moved from `QtWidgets` (Qt5) to `QtOpenGLWidgets` (Qt6).
- `exec_()` is the only spelling in PySide2; PySide6 prefers `exec()`.

Everything else is written to the intersection on purpose. Unscoped enum
access (`Qt.WA_TranslucentBackground` rather than
`Qt.WidgetAttribute.WA_TranslucentBackground`) is native in PySide2 and
accepted by PySide6's forgiveness mode, so it works on both; `Signal` and
`Slot` are spelled the same in either. Keeping to that intersection is what
makes the shim small enough to be worth having.
"""

from __future__ import annotations

try:
  from PySide2 import QtCore, QtGui, QtWidgets  # type: ignore
  from PySide2.QtWidgets import QOpenGLWidget  # type: ignore
  BINDING = "PySide2"
except ImportError:  # pragma: no cover - exercised on dev machines only
  from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore
  from PySide6.QtOpenGLWidgets import QOpenGLWidget  # type: ignore
  BINDING = "PySide6"

Qt = QtCore.Qt
Signal = QtCore.Signal
Slot = QtCore.Slot
QTimer = QtCore.QTimer
QColor = QtGui.QColor
QPainter = QtGui.QPainter
QLinearGradient = QtGui.QLinearGradient
QWidget = QtWidgets.QWidget
QApplication = QtWidgets.QApplication

__all__ = [
  "BINDING", "QtCore", "QtGui", "QtWidgets", "Qt", "Signal", "Slot", "QTimer",
  "QColor", "QPainter", "QLinearGradient", "QWidget", "QApplication",
  "QOpenGLWidget", "run_app",
]


def run_app(app: QtWidgets.QApplication) -> int:
  """Enter the event loop under either binding."""
  return app.exec_() if hasattr(app, "exec_") else app.exec()
