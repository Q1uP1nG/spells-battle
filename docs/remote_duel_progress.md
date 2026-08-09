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

