from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from game.commands import CastIntent
from game.events import BattleEvent
from game.snapshots import (
    PROTOCOL_VERSION,
    BattleSnapshot,
    PlayerSnapshot,
    ProjectileSnapshot,
)


MESSAGE_TYPES = frozenset(
    {
        "create_room",
        "join_room",
        "reconnect",
        "select_character",
        "ready",
        "cast",
        "rematch",
        "ping",
        "pong",
        "room_created",
        "room_joined",
        "room_state",
        "battle_event",
        "battle_snapshot",
        "error",
    }
)


class ProtocolError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("duplicate_field", f"duplicate field: {key}")
        result[key] = value
    return result


def _require_mapping(value, name):
    if not isinstance(value, dict):
        raise ProtocolError("invalid_field", f"{name} must be an object")
    return value


def _required(mapping, *names):
    missing = [name for name in names if name not in mapping]
    if missing:
        raise ProtocolError("missing_field", "missing required field(s): " + ", ".join(missing))


def encode_message(message_type, payload, request_id=None):
    if message_type not in MESSAGE_TYPES:
        raise ProtocolError("unknown_type", f"unknown message type: {message_type}")
    if not isinstance(payload, dict):
        raise ProtocolError("invalid_field", "payload must be an object")
    envelope = {
        "protocol_version": PROTOCOL_VERSION,
        "type": message_type,
        "payload": payload,
    }
    if request_id is not None:
        envelope["request_id"] = str(request_id)
    return json.dumps(envelope, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def decode_message(raw):
    if not isinstance(raw, str):
        raise ProtocolError("invalid_json", "message must be JSON text")
    try:
        envelope = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except ProtocolError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ProtocolError("invalid_json", "invalid JSON message") from exc
    _require_mapping(envelope, "message")
    _required(envelope, "protocol_version", "type", "payload")
    if envelope["protocol_version"] != PROTOCOL_VERSION:
        raise ProtocolError(
            "version_mismatch",
            f"expected protocol {PROTOCOL_VERSION}, got {envelope['protocol_version']!r}",
        )
    if not isinstance(envelope["type"], str) or envelope["type"] not in MESSAGE_TYPES:
        raise ProtocolError("unknown_type", f"unknown message type: {envelope['type']!r}")
    _require_mapping(envelope["payload"], "payload")
    return {
        "protocol_version": PROTOCOL_VERSION,
        "type": envelope["type"],
        "payload": envelope["payload"],
        "request_id": envelope.get("request_id"),
    }


def cast_intent_to_payload(intent, match_id=None):
    payload = {
        "spell": intent.spell,
        "sequence": intent.sequence,
        "client_time_ms": intent.client_time_ms,
        "source": intent.source,
    }
    if match_id is not None:
        payload["match_id"] = str(match_id)
    return payload


def cast_intent_from_payload(payload):
    payload = _require_mapping(payload, "cast payload")
    _required(payload, "spell", "sequence", "client_time_ms", "source")
    try:
        return CastIntent(
            spell=payload["spell"],
            sequence=payload["sequence"],
            client_time_ms=payload["client_time_ms"],
            source=payload["source"],
        )
    except (TypeError, ValueError) as exc:
        raise ProtocolError("invalid_field", str(exc)) from exc


def event_to_payload(event):
    return {
        "event_id": int(event.event_id),
        "server_tick": int(event.server_tick),
        "match_id": str(event.match_id),
        "kind": str(event.kind),
        "match_time": float(event.match_time),
        "data": dict(event.payload),
    }


def event_from_payload(payload):
    payload = _require_mapping(payload, "event payload")
    _required(payload, "event_id", "server_tick", "match_id", "kind", "match_time", "data")
    data = _require_mapping(payload["data"], "event data")
    try:
        return BattleEvent(
            event_id=int(payload["event_id"]),
            kind=str(payload["kind"]),
            match_time=float(payload["match_time"]),
            payload=data,
            server_tick=int(payload["server_tick"]),
            match_id=str(payload["match_id"]),
        )
    except (TypeError, ValueError) as exc:
        raise ProtocolError("invalid_field", "invalid battle event") from exc


def snapshot_to_payload(snapshot):
    return asdict(snapshot)


def snapshot_from_payload(payload):
    payload = _require_mapping(payload, "snapshot payload")
    _required(
        payload,
        "protocol_version",
        "match_id",
        "server_tick",
        "match_time",
        "players",
        "projectiles",
        "winner",
    )
    if payload["protocol_version"] != PROTOCOL_VERSION:
        raise ProtocolError("version_mismatch", "snapshot protocol version mismatch")
    if not isinstance(payload["players"], (list, tuple)) or len(payload["players"]) != 2:
        raise ProtocolError("invalid_field", "snapshot players must contain exactly two players")
    if not isinstance(payload["projectiles"], (list, tuple)):
        raise ProtocolError("invalid_field", "snapshot projectiles must be an array")
    try:
        players = []
        for value in payload["players"]:
            value = _require_mapping(value, "player snapshot")
            _required(value, *PlayerSnapshot.__dataclass_fields__)
            player_data = {name: value[name] for name in PlayerSnapshot.__dataclass_fields__}
            player_data["spell_cooldown_remaining"] = tuple(
                (str(name), float(remaining))
                for name, remaining in player_data["spell_cooldown_remaining"]
            )
            players.append(PlayerSnapshot(**player_data))
        projectiles = []
        for value in payload["projectiles"]:
            value = _require_mapping(value, "projectile snapshot")
            _required(value, *ProjectileSnapshot.__dataclass_fields__)
            projectile_data = {name: value[name] for name in ProjectileSnapshot.__dataclass_fields__}
            projectile_data["color"] = tuple(int(component) for component in projectile_data["color"])
            projectiles.append(ProjectileSnapshot(**projectile_data))
        return BattleSnapshot(
            protocol_version=PROTOCOL_VERSION,
            match_id=str(payload["match_id"]),
            server_tick=int(payload["server_tick"]),
            match_time=float(payload["match_time"]),
            players=tuple(players),
            projectiles=tuple(projectiles),
            winner=None if payload["winner"] is None else int(payload["winner"]),
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise ProtocolError("invalid_field", "invalid battle snapshot") from exc
