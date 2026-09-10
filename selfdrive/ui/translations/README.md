# Translations

The `.ts` files here are real translation work and are kept, but the pipeline
that produced and consumed them is gone with the C++/Qt UI (dev/02M replaces
it with `selfdrive/ui/eop`, a Qt Widgets UI in Python).

What changed:

- `lupdate` scanned `.cc`/`.h` for `tr(...)`. The equivalent for a Python Qt
  UI is `pylupdate5` (or `pyside2-lupdate`) over `selfdrive/ui/eop/**/*.py`.
- `lrelease` compiled `.ts` to `.qm` at build time and `rcc` baked them into
  the binary. The Python UI has no binary to bake into: load `.qm` at runtime
  with `QTranslator.load()` from this directory.
- `update_translations.py` still drives the `.ts` files but needs its
  extraction step retargeted; it is not wired into any build today.

Nothing in the UI is translated at the moment. The strings in
`selfdrive/ui/eop` are English literals, and wiring `QTranslator` plus
retargeting extraction is outstanding work, deliberately not faked by leaving
a dead `lrelease` step in the build.
