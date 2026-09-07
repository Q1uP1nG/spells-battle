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

Remote Duel architecture, local runbook, and Alibaba Cloud deployment:

```text
docs/remote_duel_refactor_architecture.md
docs/remote_duel_runbook.md
deploy/README.md
```

Start a local authoritative server with `python -m server.app`, then choose menu
option `5` in two clients. For different-network play, `client_config.json` contains
the default deployed endpoint. `SPELLS_SERVER_URL` can override it for local testing
or another server; a domain and `wss://` are an optional later security upgrade. See
`docs/remote_duel_direct_ip_route.md`.

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
