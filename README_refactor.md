# Spells Refactor

This folder is a side-by-side modular refactor of the original `magic_spale/spells_battle_mvp.py`.
The original project folder is intentionally untouched.

Project status and future work:

```text
docs/project_status_and_roadmap.md
docs/README.md
docs/archive/
```

Older planning documents have been archived under `docs/archive/`.

Run from this directory:

```bash
python main.py
```

Compatibility entrypoint:

```bash
python spells_battle_mvp.py
```

Smoke tests:

```bash
python -m unittest discover -s tests -v
```

Wand mode manual check:

```text
1. Run python main.py
2. Press V to switch to wand mode
3. Put a bright colored marker at the center calibration target
4. Press C and wait for CV WAND LOCKED
5. Move the marked pen/chopstick tip and watch the ROI, tip circle, and track line
```
