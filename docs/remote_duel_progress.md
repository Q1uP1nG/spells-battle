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

## Phase 2 - Complete

Date: 2026-08-09

### Implementation summary

- Extracted `BattleEngine` as the authoritative battle rules component.
- Removed wall-clock, particle, audio, renderer, camera, OpenCV, and Pygame
  dependencies from the authoritative engine; callers inject `dt` and match time.
- Added immutable, structured `BattleEvent` values with monotonic event IDs.
- Added stable monotonic `projectile_id` allocation for authoritative projectiles.
- Converted cast feedback, healing completion, clashes, shield hits, player hits,
  and round completion into domain events.
- Rebuilt `BattleGame` as a backward-compatible local presentation adapter that
  consumes events immediately and preserves particles, audio cues, messages,
  shockwaves, screen shake, hit flash, and existing public methods.
- Exported `BattleEngine` and `BattleEvent` through the lazy `game` package API.

### Modified files

- `game/battle_engine.py`
- `game/events.py`
- `game/battle.py`
- `game/__init__.py`
- `models/projectile.py`
- `tests/test_battle_engine.py`
- `docs/remote_duel_progress.md`

### Architecture impact

The same battle rules can now run in a headless server process without importing
client presentation or device dependencies. The local application retains its old
`BattleGame` surface, while authoritative changes are emitted as deterministic
facts that can later be serialized and replayed by remote clients.

### Verification

```text
Phase 2 deterministic/headless tests
  Ran 6 tests
  OK

Targeted battle feedback, interaction, mode, and PVE tests
  Ran 62 tests
  OK

python -m compileall -q .
  PASS

python -m unittest discover -s tests
  Ran 388 tests in 13.032s
  OK

Real log snapshot before/after the full test suite
  REAL_LOGS_UNCHANGED=True
```

### Remaining risks

- Domain event payloads are Python values but do not yet have a versioned wire
  schema or validation. Phase 3 adds protocol codecs and round-trip coverage.
- Snapshots do not yet exist, so remote clients cannot reconstruct authoritative
  state after joining or reconnecting.
- Presentation randomness is intentionally local and nondeterministic; it has no
  effect on authoritative state.

### Next phase

Phase 3: define versioned command/event/snapshot DTOs and strict JSON codecs,
including required-field validation, forward-compatible optional fields, and
round-trip tests.

## Phase 3 - Complete

Date: 2026-08-09

### Implementation summary

- Added immutable `PlayerSnapshot`, `ProjectileSnapshot`, and `BattleSnapshot` DTOs.
- Converted all NumPy-backed positions, velocities, colors, and numeric state to
  JSON-safe Python values at the snapshot boundary.
- Represented timed effects as remaining durations relative to `match_time`, avoiding
  transfer of process-local monotonic clock values.
- Added protocol version 1 JSON envelopes for room commands, casts, battle events,
  snapshots, heartbeat messages, and errors.
- Added explicit protocol errors for invalid JSON, duplicate fields, missing fields,
  unknown message types, invalid payloads, and version mismatch.
- Established forward compatibility by ignoring unknown optional fields while
  validating all required fields.
- Added `server_tick` to domain events for ordering at the wire boundary.

### Verification

```text
Protocol tests
  Ran 11 tests
  OK

Snapshot tests
  Ran 3 tests
  OK

python -m unittest discover -s tests
  Ran 402 tests in 12.187s
  OK

Real log snapshot before/after the full test suite
  REAL_LOGS_UNCHANGED=True
```

### Remaining risks

- Duplicate cast sequence handling belongs to the connection/room authority and is
  implemented in Phase 4; the JSON parser already rejects duplicate object keys.
- Protocol version 1 is intentionally compact and has not yet been exercised over
  a real WebSocket connection.

### Next phase

Phase 4: implement the in-memory room state machine and local authoritative
WebSocket server, then verify one server and two headless clients over a random port.
