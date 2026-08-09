# Remote Duel Refactor Progress

This file records phase gates for `remote_duel_refactor_architecture.md`.

## Phase 0 - Complete

Date: 2026-08-09  
Baseline commit: `89ba1fd chore: establish remote duel refactor baseline`

### Implementation summary

- Repaired the empty `.git` directory by initializing a valid `main` repository.
- Created a root baseline commit containing the current code, tests, report, models, audio assets, and remote-duel design documents.
- Added logger dependency injection to `CVGestureController` so tests can use isolated log destinations.
- Updated CV state-machine and clean-draw tests to use temporary gesture and wand-debug directories.
- Prevented controller construction in tests from pruning real wand-debug sessions.
- Prevented state-machine tests from writing synthetic gesture events into `logs/cv_sessions`.

### Modified files

- `cv/controller.py`
- `tests/test_cv_state_machine.py`
- `tests/test_cv_draw_clean_mode.py`
- `docs/remote_duel_refactor_architecture.md`
- `docs/remote_duel_goal.md`
- `docs/remote_duel_progress.md`

### Architecture impact

`CVGestureController` remains backward compatible: production callers can still use
`CVGestureController()` with the existing default loggers. Tests and future client
composition can inject logger instances without touching global paths. This is also
the first dependency-injection seam needed by the later client/session split.

### Verification

```text
python -m compileall -q .
  PASS

python -m unittest discover -s tests -v
  Ran 374 tests in 13.067s
  OK

Real log snapshot before/after the full test suite
  REAL_LOGS_UNCHANGED=True
```

### Remaining risks

- The existing `.gitignore` globally ignores PNG/JPG files, so the local character
  image folders are not part of the new Git baseline. They remain on disk and the
  renderer still has its geometric fallback. Asset packaging must be resolved before
  distributing remote clients.
- The baseline is local only and currently has no configured remote repository.
- Production loggers still intentionally catch write failures to avoid crashing live
  play; structured error reporting can be addressed in a later observability phase.

### Next phase

Phase 1: introduce `CastIntent`, a `BattleSession` interface, and
`LocalBattleSession`; route keyboard and CV casting through the same session command
path while preserving all offline behavior.

## Phase 1 - Complete

Date: 2026-08-09

### Implementation summary

- Added immutable, transport-neutral `CastIntent` commands. Player identity is not
  included in the payload, allowing a future server to derive it from the room seat
  bound to the connection.
- Added `CastSubmission`, including an explicit future `pending` state for remote
  acknowledgement.
- Added the runtime-checkable `BattleSession` protocol and `LocalBattleSession`.
- Added per-player monotonic command sequence allocation and client-time metadata.
- Created one `LocalBattleSession` in the main application and injected the same
  instance into `CVGestureController`.
- Routed both P1/P2 keyboard input and CV-recognized casts through the session.
- Preserved `BattleGame.cast_spell()` as the local compatibility and rules API.
- Left PVE AI inside the local authority boundary; it is not treated as a remote
  player-input source.

### Modified files

- `game/commands.py`
- `game/session.py`
- `game/__init__.py`
- `cv/controller.py`
- `main.py`
- `tests/test_battle_session.py`
- `tests/test_cv_controller.py`
- `tests/test_main_modes.py`
- `docs/remote_duel_progress.md`

### Architecture impact

All human cast writes now pass through a transport-neutral session seam. Offline
play resolves the command immediately through `LocalBattleSession`; a later
`RemoteBattleSession` can preserve the same command shape while sending it to the
authoritative server. The CV subsystem continues to read the local battle view for
gesture side and feedback, but no longer writes directly through
`BattleGame.cast_spell()`.

### Verification

```text
Targeted session/CV/main regression suite
  Ran 90 tests
  OK

python -m compileall -q .
  PASS

python -m unittest discover -s tests -v
  Ran 382 tests in 12.682s
  OK

Real log snapshot before/after the full test suite
  REAL_LOGS_UNCHANGED=True

Direct human-input cast call audit
  main.py: no direct cast_spell call
  cv/: no direct cast_spell call
  game/session.py: the only human-input adapter call
```

### Remaining risks

- `CastSubmission(accepted=None)` is modeled but not yet consumed asynchronously by
  the current CV/UI path. Remote pending/accepted/rejected handling belongs to the
  later remote-client phase.
- `BattleGame` still combines authoritative rules with particles, audio events,
  flash messages, and screen feedback. Phase 2 must separate those responsibilities.
- `BattleGame` still owns a few direct wall-clock fallbacks. Phase 2 must remove them
  from the authoritative engine.

### Next phase

Phase 2: extract a deterministic `BattleEngine`, introduce domain `BattleEvent`
outputs, and retain `BattleGame` as a compatibility facade that combines the engine
with local presentation behavior.
