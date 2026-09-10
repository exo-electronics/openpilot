#!/usr/bin/env python3
"""EOP UI entry point (ExoPilot 02M).

Standalone until P5, when it replaces the C++ `ui` process in
system/manager/process_config.py. Running it directly is the intended way to
work on it:

    PYTHONPATH=. python3 -m openpilot.selfdrive.ui.eop.main --demo

`--demo` drives the view from a scripted state source instead of msgq, so the
UI can be worked on without a running backend or a built capnp.
"""

from __future__ import annotations

import argparse
import sys

from openpilot.selfdrive.ui.eop.qt import QApplication, run_app
from openpilot.selfdrive.ui.eop.state import UIState
from openpilot.selfdrive.ui.eop.styles.style_manager import (
  Component,
  StyleManager,
  Theme,
)
from openpilot.selfdrive.ui.eop.views.onroad import PANEL_H, PANEL_W, OnroadView


def _demo_source():
  """Cycle blind-spot severities so the bands can be seen without a car."""
  from openpilot.selfdrive.ui.eop.components.blind_spot import (
    CAUTION,
    CLEAR,
    WARNING,
  )
  from openpilot.selfdrive.ui.eop.state import Snapshot
  from openpilot.selfdrive.ui.eop.components.blind_spot import BlindSpotSeverity

  script = [
    BlindSpotSeverity(CLEAR, CLEAR),
    BlindSpotSeverity(CAUTION, CLEAR),
    BlindSpotSeverity(CLEAR, WARNING),
    BlindSpotSeverity(WARNING, CAUTION),
  ]
  i = 0
  while True:
    yield Snapshot(blind_spot=script[i % len(script)])
    i += 1


def main(argv: list[str] | None = None) -> int:
  ap = argparse.ArgumentParser(description="ExoPilot 02M UI")
  ap.add_argument("--demo", action="store_true",
                  help="drive the view from a scripted source, no msgq needed")
  args = ap.parse_args(argv)

  app = QApplication(sys.argv[:1])

  styles = StyleManager(Theme.DARK)
  styles.apply(app, Component.ONROAD)

  view = OnroadView()
  view.resize(PANEL_W, PANEL_H)
  view.show()

  if args.demo:
    from openpilot.selfdrive.ui.eop.qt import QTimer
    source = _demo_source()
    timer = QTimer(view)
    timer.setInterval(1500)
    timer.timeout.connect(lambda: view.set_snapshot(next(source)))
    timer.start()
    view.set_snapshot(next(source))
  else:
    state = UIState(parent=view)
    state.updated.connect(view.set_snapshot)
    state.start()

  return run_app(app)


if __name__ == "__main__":
  raise SystemExit(main())
