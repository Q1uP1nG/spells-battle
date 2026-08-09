"""Headless end-to-end probe for a deployed Remote Duel WebSocket endpoint."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import time
import urllib.request

# Direct script execution puts tools/ rather than the repository root on sys.path.
# Keep the documented ``python tools/remote_duel_probe.py`` command runnable.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from websockets.asyncio.client import connect

from game.commands import CastIntent
from network.protocol import cast_intent_to_payload, decode_message, encode_message


class ProbeError(RuntimeError):
    pass


async def _send(websocket, message_type, payload):
    await websocket.send(encode_message(message_type, payload))


async def _receive_until(websocket, message_type, predicate=None, timeout=8.0):
    async def receive():
        while True:
            message = decode_message(await websocket.recv())
            if message["type"] == "error":
                payload = message["payload"]
                raise ProbeError(f"{payload.get('code')}: {payload.get('message')}")
            if message["type"] == message_type and (
                predicate is None or predicate(message["payload"])
            ):
                return message["payload"]

    return await asyncio.wait_for(receive(), timeout=timeout)


def _cooldown_ready(snapshot, spell):
    cooldowns = dict(snapshot["players"][0]["spell_cooldown_remaining"])
    return cooldowns.get(spell, 0.0) <= 0.0 and snapshot["players"][0]["mana"] >= 25.0


async def probe(server_url, full_round=True, timeout=8.0):
    started = time.perf_counter()
    async with connect(server_url, max_size=16_384) as first, connect(
        server_url, max_size=16_384
    ) as second:
        await _send(first, "create_room", {})
        created = await _receive_until(first, "room_created", timeout=timeout)
        room_code = created["room_code"]
        match_id = created["match_id"]

        await _send(second, "join_room", {"room_code": room_code})
        joined = await _receive_until(second, "room_joined", timeout=timeout)
        if joined["match_id"] != match_id:
            raise ProbeError("clients received different match IDs")

        ready = {"ready": True, "match_id": match_id}
        await _send(first, "ready", ready)
        await _send(second, "ready", ready)
        first_snapshot = await _receive_until(first, "battle_snapshot", timeout=timeout)
        second_snapshot = await _receive_until(second, "battle_snapshot", timeout=timeout)
        if first_snapshot != second_snapshot:
            raise ProbeError("initial authoritative snapshots diverged")

        await _send(first, "ping", {"time": started})
        pong = await _receive_until(first, "pong", timeout=timeout)
        if pong.get("echo") != started:
            raise ProbeError("heartbeat echo mismatch")

        winner = None
        first_final = None
        casts = 6 if full_round else 1
        for sequence in range(1, casts + 1):
            intent = CastIntent("incendio", sequence, sequence, "keyboard")
            await _send(first, "cast", cast_intent_to_payload(intent, match_id))
            event = await _receive_until(
                first,
                "battle_event",
                lambda payload: payload["kind"] == "cast_accepted"
                and payload["data"].get("sequence") == sequence,
                timeout=timeout,
            )
            if event["match_id"] != match_id:
                raise ProbeError("cast acknowledgement has the wrong match ID")
            if not full_round:
                break

            outcome = await _receive_until(
                first,
                "battle_event",
                lambda payload: payload["kind"] in ("player_hit", "round_ended"),
                timeout=timeout,
            )
            if outcome["kind"] == "round_ended":
                winner = outcome["data"]["winner"]
                break
            snapshot = await _receive_until(
                first,
                "battle_snapshot",
                lambda payload: payload["winner"] is not None
                or (
                    payload["server_tick"] > event["server_tick"]
                    and _cooldown_ready(payload, "incendio")
                ),
                timeout=max(timeout, 6.0),
            )
            if snapshot["winner"] is not None:
                winner = snapshot["winner"]
                first_final = snapshot
                break

        report = {
            "ok": True,
            "server_url": server_url,
            "room_code": room_code,
            "match_id": match_id,
            "protocol_version": first_snapshot["protocol_version"],
            "initial_server_tick": first_snapshot["server_tick"],
            "full_round": bool(full_round),
            "winner": winner,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
        if full_round:
            if winner is None:
                raise ProbeError("full-round probe didn't reach a winner")
            if first_final is None:
                first_final = await _receive_until(
                    first,
                    "battle_snapshot",
                    lambda payload: payload["winner"] is not None,
                    timeout,
                )
            second_final = await _receive_until(
                second, "battle_snapshot", lambda payload: payload["winner"] is not None, timeout
            )
            if first_final != second_final:
                raise ProbeError("final authoritative snapshots diverged")
        return report


def health_url(server_url):
    if server_url.startswith("wss://"):
        return "https://" + server_url[6:].rstrip("/") + "/health"
    if server_url.startswith("ws://"):
        return "http://" + server_url[5:].rstrip("/") + "/health"
    raise ProbeError("server URL must start with ws:// or wss://")


def check_health(server_url, timeout=5.0):
    with urllib.request.urlopen(health_url(server_url), timeout=timeout) as response:
        payload = json.loads(response.read())
    if payload.get("status") != "ok":
        raise ProbeError(f"health check failed: {payload!r}")
    return payload


def main():
    parser = argparse.ArgumentParser(description="Probe a deployed Spells Remote Duel server")
    parser.add_argument("--url", required=True, help="ws:// or wss:// server URL")
    parser.add_argument("--quick", action="store_true", help="stop after one accepted cast")
    parser.add_argument("--skip-health", action="store_true")
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()

    result = {}
    if not args.skip_health:
        result["health"] = check_health(args.url, args.timeout)
    result["duel"] = asyncio.run(
        probe(args.url, full_round=not args.quick, timeout=args.timeout)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
