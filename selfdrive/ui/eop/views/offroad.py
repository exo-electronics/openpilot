"""Offroad settings.

Nagasware's navigation model, not openpilot's (plan section 5.5): a horizontal
tab bar across the top with grouped pages below, rather than a left sidebar
over a long scrolling list. The geometry decides it -- 1600x600 leaves 500px
of content height between the bars, and a sidebar spends the scarce axis while
tabs spend the abundant one.

Pages are built from `settings/descriptor.py`, so adding a control is a data
change and the coverage gate can prove nothing was dropped.
"""

from __future__ import annotations

from openpilot.selfdrive.ui.eop.components.controls import ControlRow, ParamStore
from openpilot.selfdrive.ui.eop.qt import Qt, QtWidgets, QWidget
from openpilot.selfdrive.ui.eop.settings.descriptor import PAGES, Page

# Human titles for the descriptor's page keys. Kept here rather than in the
# descriptor because the descriptor is generated, and regenerating it should
# never silently revert a wording change.
PAGE_TITLES = {
  "device": "Device",
  "lateral": "Steering",
  "cruise": "Cruise",
  "perception": "Perception",
  "map": "Map & GPS",
  "safety": "Safety",
  "vehicle": "Vehicle",
  "dvr": "Recording",
  "voice": "Voice",
}
PAGE_ORDER = ["device", "lateral", "cruise", "safety", "perception",
              "map", "vehicle", "dvr", "voice"]


class SettingsPage(QtWidgets.QScrollArea):
  """One tab: a scrolling column of ControlRows built from the descriptor."""

  def __init__(self, page: Page, store: ParamStore, parent=None):
    super().__init__(parent)
    self.page = page
    self.setWidgetResizable(True)
    self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    body = QWidget()
    lay = QtWidgets.QVBoxLayout(body)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)

    self.rows = []
    for control in page.controls:
      row = ControlRow(control, store)
      lay.addWidget(row)
      self.rows.append(row)
    lay.addStretch(1)
    self.setWidget(body)

  def showEvent(self, event):
    # Re-read on every entry rather than trusting construction-time values:
    # another page, a daemon, or adb may have moved the param since.
    super().showEvent(event)
    for row in self.rows:
      row.refresh()


class OffroadView(QWidget):
  """Top tab bar plus the page stack."""

  def __init__(self, store: ParamStore | None = None, parent=None):
    super().__init__(parent)
    self.setObjectName("offroadRoot")
    self._store = store if store is not None else ParamStore()

    lay = QtWidgets.QVBoxLayout(self)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)

    self.tabs = QtWidgets.QTabWidget()
    self.tabs.setObjectName("settingsTabs")
    self.tabs.setTabPosition(QtWidgets.QTabWidget.North)
    self.tabs.currentChanged.connect(self._refresh_current)
    lay.addWidget(self.tabs)

    by_name = {p.name: p for p in PAGES}
    ordered = [by_name[n] for n in PAGE_ORDER if n in by_name]
    ordered += [p for p in PAGES if p.name not in PAGE_ORDER]

    self.pages = {}
    for page in ordered:
      widget = SettingsPage(page, self._store)
      self.pages[page.name] = widget
      self.tabs.addTab(widget, PAGE_TITLES.get(page.name, page.name.title()))

  def _refresh_current(self, index: int) -> None:
    page = self.tabs.widget(index)
    if page is not None:
      for row in page.rows:
        row.refresh()

  def page_names(self) -> list[str]:
    return [self.tabs.tabText(i) for i in range(self.tabs.count())]
