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

## Phase 4 - Complete

Date: 2026-08-09

### Implementation summary

- Added a headless asyncio WebSocket server using the current `websockets` API.
- Added validated environment-backed server configuration for host, port, tick rate,
  snapshot rate, reconnect/idle timeouts, message size, and cast rate limit.
- Added six-character room codes, server-generated match IDs, two server-owned
  seats, and unguessable reconnect tokens.
- Added an in-memory room state machine with ready checks, authoritative running,
  round-over, pause-on-disconnect, reconnect, expiry, and idle cleanup.
- Added a 30 Hz configurable authoritative battle loop and configurable snapshot
  broadcasting, with immediate event broadcast and guaranteed final snapshot.
- Added monotonic per-seat cast sequence validation and per-seat request rate limits.
- Ensured client-supplied `player_index` is ignored; identity always comes from the
  WebSocket connection's bound seat.
- Added application heartbeat request/response alongside WebSocket-level pings.
- Added `websockets>=16.1,<17` as the only new runtime dependency.

### Verification

```text
Room state-machine tests
  Ran 5 tests
  OK

Real WebSocket two-client integration tests
  Ran 4 tests
  OK
  Covered: room create/join, ready, identical snapshots, identity binding,
  duplicate sequence rejection, completed round, heartbeat, pause and reconnect.

python -m compileall -q .
  PASS

python -m unittest discover -s tests
  Ran 411 tests in 13.868s
  OK

Real log snapshot before/after the full test suite
  REAL_LOGS_UNCHANGED=True
```

### Remaining risks

- The current server is intentionally single-process and stores rooms in memory;
  restart loses active rooms, which is acceptable for the first release.
- Remote UI and its background network worker do not yet exist. Phase 5 connects the
  real client without converting the existing OpenCV/UI loop to asyncio.
- Rematch is present in the protocol vocabulary but is not wired into the room state
  machine yet; Phase 5/7 will cover the user-facing rematch lifecycle.

### Next phase

Phase 5: add a queue-isolated background client, `RemoteBattleSession`, snapshot
interpolation/presentation, and Remote Duel menu/create/join flow while retaining all
offline modes.

## Phase 5 - Complete

Date: 2026-08-09

### Implementation summary

- Added a daemon-thread WebSocket client with thread-safe incoming/outgoing queues;
  the network worker never imports or mutates OpenCV/UI objects.
- Added explicit transport and remote-session states for connecting, waiting, ready,
  running, reconnecting, round-over, disconnected, and closed behavior.
- Added `RemoteBattleSession` with the same cast request boundary used by keyboard
  and CV. Remote casts return pending and never pre-apply authoritative results.
- Applied snapshots to a render-only `BattleGame` view and consumed server events
  through the existing local particle/audio/flash presentation adapter.
- Added stable-ID projectile interpolation between the latest two snapshots and
  stale-snapshot rejection.
- Added Remote Duel to the menu (`5`), an in-window create/join room-code lobby,
  local-seat character selection, ready flow, and server status/error display.
- Bound both keyboard and CV input to the seat assigned by the server; P2 local keys
  cannot control a remote opponent.
- Kept `SPELLS_SERVER_URL` configurable with a local development default.
- Added two-party rematch readiness and verified a second round starts with a new
  match ID and reset authoritative state.

### Verification

```text
Remote session unit and real two-client tests
  Ran 7 tests
  OK

Snapshot interpolation tests
  Ran 2 tests
  OK

Main mode and menu tests
  Ran 35 tests
  OK

python -m compileall -q .
  PASS

python -m unittest discover -s tests
  Ran 422 tests in 15.557s
  OK

Real log snapshot before/after the full test suite
  REAL_LOGS_UNCHANGED=True
```

### Remaining risks

- Automated tests exercise real sockets and queue isolation, but physical two-device
  camera/audio acceptance still requires the deployment endpoint from Phase 6.
- Reconnect credentials currently live only in process memory, so a full client
  process restart cannot reclaim a seat. Short network interruptions are supported.
- The remote lobby intentionally uses keyboard room-code entry; richer mouse/text UI
  can be added later without changing the protocol.

### Next phase

Phase 6: package the server for Alibaba Cloud with a health endpoint, Docker,
Caddy/TLS reverse proxy, environment templates, restart/logging policy, and an
operator deployment guide.

## Phase 6 - Complete

Date: 2026-08-09

### Implementation summary

- Added a JSON `/health` response on the same HTTP/WebSocket listener.
- Added validated `SPELLS_SERVER_LOG_LEVEL` configuration.
- Added a minimal server-only dependency set without OpenCV, MediaPipe, Pygame,
  Pillow, camera, audio, or client rendering packages.
- Added a Python 3.13 slim, non-root server image with an internal health check.
- Added Docker Compose with automatic restart, service health dependency, and
  bounded JSON log rotation.
- Added Caddy automatic TLS/WSS termination, security headers, compression, and
  JSON access logs. Only 443 is published; the application port remains private.
- Added `.env.example`, `.dockerignore`, and a Chinese Alibaba Cloud deployment,
  client configuration, operations, rollback, and troubleshooting guide.

### Verification

```text
Live HTTP health endpoint plus WebSocket integration tests
  Ran 5 tests
  OK

Deployment/configuration static tests
  Ran 4 tests
  OK

python -m unittest discover -s tests
  Ran 427 tests in 15.538s
  OK

Real log snapshot before/after the full test suite
  REAL_LOGS_UNCHANGED=True
```

### Verification limitation

Docker is not installed in the current Windows workspace, so `docker build` and
`docker compose config` could not be executed here. The deployment files are covered
by YAML/static contract tests and must be built once on a Docker-capable staging/ECS
host before public release.

### Remaining risks

- A real domain, DNS record, ECS instance, and TLS certificate are external state and
  were not provisioned from this repository task.
- Public two-network acceptance requires deploying these files and setting
  `SPELLS_SERVER_URL=wss://<domain>` on both clients.

### Next phase

Phase 7: harden malformed/slow-client behavior, add structured redacted server logs,
perform dependency and architecture audits, consolidate runbooks, and execute the
final regression gate.

## Phase 7 - Complete (code and local verification)

Date: 2026-08-09

### Implementation summary

- Added application RTT measurement and a visible remote latency/state indicator.
- Added reconnect counters for diagnostics while retaining pause-on-disconnect.
- Isolated every server connection behind a bounded asynchronous send queue; a slow
  client is closed with retry-later status instead of blocking the fixed battle tick.
- Added configurable room-count and per-client send-queue capacity limits on top of
  existing message-size and cast-rate limits.
- Added structured JSON logging with recursive redaction of reconnect tokens,
  camera/frame/image fields, and related sensitive context.
- Verified malformed JSON and protocol-version mismatch over real WebSockets.
- Added a headless server dependency/import audit and confirmed the server doesn't
  load OpenCV, MediaPipe, Pygame, renderer, camera, or audio components.
- Added the complete local/two-client/public acceptance runbook and linked it from
  the project README.
- Deliberately left Protego network grace at zero and retained JSON rather than
  MessagePack because no measured public-network evidence justifies fairness or
  protocol changes yet.

### Final local verification

```text
python -m compileall -q .
  PASS

python -m unittest discover -s tests
  Ran 434 tests in 17.373s (final post-hardening run)
  OK

Repeated real-WebSocket integration suite (two additional consecutive runs)
  6 tests OK
  6 tests OK

Real log snapshot before/after all tests
  REAL_LOGS_UNCHANGED=True

python -m pip install --dry-run -r requirements-server.txt
  PASS (numpy and websockets 16.1.1 satisfied)

git diff --check
  PASS
```

## Public-deployment preflight hardening

Date: 2026-08-09

- Added configurable total connection and general per-connection message-rate
  limits, complementing room, cast, message-size, and send-queue limits.
- Added a deployable headless probe at `tools/remote_duel_probe.py`.
- The probe validates health, two real WebSocket connections, create/join, ready,
  heartbeat, authoritative cast acknowledgement, full-round winner calculation, and
  identical final snapshots.
- Verified the probe's default full-round path against a random local port: protocol
  2, winner P1, complete in 9.908 seconds.

Final local gate after these changes:

```text
python -m unittest discover -s tests
  Ran 439 tests in 17.914s
  OK

Real log snapshot before/after the full suite
  REAL_LOGS_UNCHANGED=True

git diff --check
  PASS
```

Once a public endpoint exists, the remaining external acceptance starts with:

```powershell
python tools/remote_duel_probe.py --url ws://<ECS_PUBLIC_IP>:8765
```

The shared Conda environment's global `pip check` reports unrelated pre-existing
missing optional dependencies for Azure Identity, EasyOCR, MCP, MSAL, and PDFMiner.
No project dependency is named by those errors, and the server-specific dependency
resolution succeeds; the shared environment was intentionally not mutated to repair
unrelated tools.

### Architecture audit

- Human keyboard and CV casts enter through session adapters; no direct calls remain
  in `main.py` or `cv/`.
- Direct rule calls remain only at intended authority boundaries: local session, PVE
  authority, and server battle session.
- Server identity comes only from the connection-bound seat.
- Protocol payloads contain commands/events/snapshots and never camera data.
- Offline modes import and run without a server.

### External acceptance still required

All repository phases are implemented and locally verified. The revised architecture's
final definition also requires two physical devices on different networks to connect
through a real Alibaba Cloud ECS public IPv4 endpoint. A domain and DNS are no longer
required; completing this external acceptance still needs an ECS public IP and
authorization to deploy. Follow `docs/remote_duel_direct_ip_route.md`,
`deploy/README.md`, and `docs/remote_duel_runbook.md`; record the public acceptance
results here after deployment.

## Post-Phase 7 completion audit hardening

Date: 2026-08-09

The requirement-by-requirement audit found that battle commands and events needed
stronger cross-round correlation before public deployment. The following protocol
hardening was completed:

- Bumped the wire protocol from version 1 to version 2.
- Required `match_id` on cast, character selection, ready, and rematch commands.
- Added `match_id` to every battle event.
- Added the originating cast `sequence` to `cast_accepted` and `cast_rejected` event
  payloads so clients can correlate authoritative acknowledgement with pending input.
- Reject stale commands from an earlier rematch before they reach battle rules.
- Ignore stale events and snapshots from earlier matches on the client.
- Reset interpolation history when a new rematch ID becomes authoritative.

Verification:

```text
python -m compileall -q .
  PASS

python -m unittest discover -s tests
  Ran 436 tests in 16.856s
  OK

Real log snapshot before/after the full suite
  REAL_LOGS_UNCHANGED=True

git diff --check
  PASS
```

## Deployment route revision: public IP first

Date: 2026-08-09

The user explicitly chose to avoid the domain registration and waiting period. The
first-release deployment route is therefore `ws://ECS_PUBLIC_IP:8765`, with no DNS,
certificate, or reverse proxy dependency. This decision does not change the
authoritative battle architecture or wire protocol.

Repository changes:

- Default `compose.yaml` publishes the authoritative service on 8765/TCP.
- Added `compose.tls.yaml` to preserve Caddy/WSS as an optional later upgrade.
- Added a domainless deployment route document and rewrote deployment instructions.
- Updated the architecture, reusable Goal, runbook, environment example, README, and
  deployment regression tests to use the direct-IP route.
- Documented the accepted plaintext boundary: suitable for controlled private tests,
  not a public service carrying accounts, chat, payment, or other sensitive data.

External completion now requires only an ECS public IPv4 address, deployment access,
and two physical clients on different networks. It no longer requires a domain.

Verification after the route revision:

```text
python -m unittest tests.test_server_deployment tests.test_remote_duel_probe -v
  Ran 9 tests in 0.965s
  OK

python -m compileall -q .
  PASS

python -m unittest discover -s tests
  Ran 441 tests in 20.188s
  OK

git diff --check
  PASS
```

Docker is not installed on the current Windows workstation, so a local
`docker compose config`/container start could not be performed. Compose structure is
covered by YAML regression tests; the actual container build, health check, and public
port check remain part of the ECS deployment gate.

## Pre-deployment audit against the project report

Date: 2026-08-09

The complete 21-page `Spells_Battle_Report.pdf` was reviewed against the current
repository. The original finger/wand input paths, six spells, characters, PVE, local
Duel, CV Training, rendering/audio feedback, fallback behavior, and offline tooling
remain covered. Remote Duel extends those boundaries through session adapters and an
authoritative headless server; it does not move camera frames, MediaPipe, rendering, or
audio to the server.

The audit found one release-entry defect: running the documented command
`python tools/remote_duel_probe.py` directly placed `tools/` instead of the repository
root on Python's import path. The probe now adds its repository root only for direct
script execution, and a subprocess regression test protects the documented command.

Verification after the fix:

```text
python -m unittest tests.test_remote_duel_probe -v
  Ran 3 tests
  OK

python tools/remote_duel_probe.py --url ws://127.0.0.1:18765
  health.status=ok
  duel.ok=true
  protocol_version=2
  full_round=true
  winner=0
  elapsed_seconds=9.895

python -m compileall -q .
  PASS

python -m unittest discover -s tests
  Ran 442 tests in 15.725s
  OK
```

The code and deployment artifacts are ready for execution. Remaining gates are
external: build the container on the purchased ECS, open TCP/8765, run the probe
against `ws://101.132.63.248:8765`, and complete the report's required manual camera/CV
and two-physical-device checks.

## Alibaba Cloud public endpoint acceptance

Date: 2026-08-09

The authoritative server was deployed to Ubuntu on Alibaba Cloud ECS at
`ws://101.132.63.248:8765`. Because the mainland instance could not reach Docker Hub,
the same server entry point is running from an isolated Python virtual environment
under a dedicated `spells` user and systemd service instead of Docker. TCP/8765 is
published through the ECS security group.

Public full-round probe result:

```text
python tools/remote_duel_probe.py --url ws://101.132.63.248:8765
  health.status=ok
  health.rooms=0
  health.connections=0
  duel.ok=true
  protocol_version=2
  initial_server_tick=1
  full_round=true
  winner=0
  elapsed_seconds=10.107
```

This verifies the public health endpoint, two real WebSocket connections, room create
and join, ready flow, authoritative casts, a complete round, winner calculation, and
matching final snapshots over the deployed internet endpoint. The remaining final gate
is manual play on two physical Windows devices on different networks, including
keyboard first and then finger/bright-wand CV, reconnect, and repeated rematches.
