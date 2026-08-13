import asyncio
import json
import urllib.request
import unittest

from websockets.asyncio.client import connect

from game.commands import CastIntent
from network.protocol import (
    cast_intent_to_payload,
    decode_message,
    encode_message,
)
from server.app import BattleServer
from server.config import ServerConfig


class ServerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = BattleServer(
            ServerConfig(
                host="127.0.0.1",
                port=0,
                tick_rate=30,
                snapshot_rate=15,
                reconnect_timeout=2.0,
                room_idle_timeout=30.0,
            )
        )
        await self.server.start()
        uri = f"ws://127.0.0.1:{self.server.port}"
        self.first = await connect(uri)
        self.second = await connect(uri)

    async def asyncTearDown(self):
        await self.first.close()
        await self.second.close()
        await self.server.stop()

    async def send(self, websocket, message_type, payload, request_id=None):
        await websocket.send(encode_message(message_type, payload, request_id))

    async def receive_until(self, websocket, message_type, predicate=None, timeout=3.0):
        async def receive():
            while True:
                message = decode_message(await websocket.recv())
                if message["type"] == message_type and (
                    predicate is None or predicate(message["payload"])
                ):
                    return message

        return await asyncio.wait_for(receive(), timeout)

    async def create_join_and_ready(self):
        await self.send(self.first, "create_room", {}, "create")
        created = await self.receive_until(self.first, "room_created")
        room_code = created["payload"]["room_code"]
        self.match_id = created["payload"]["match_id"]
        await self.send(self.second, "join_room", {"room_code": room_code}, "join")
        joined = await self.receive_until(self.second, "room_joined")
        await self.send(self.first, "ready", {"ready": True, "match_id": self.match_id})
        await self.send(self.second, "ready", {"ready": True, "match_id": self.match_id})
        first_snapshot = await self.receive_until(self.first, "battle_snapshot")
        second_snapshot = await self.receive_until(self.second, "battle_snapshot")
        return created, joined, first_snapshot, second_snapshot

    async def test_health_endpoint_reports_ready_server(self):
        def fetch_health():
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.server.port}/health", timeout=2
            ) as response:
                return response.status, json.loads(response.read())

        status, payload = await asyncio.to_thread(fetch_health)

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["rooms"], 0)
        self.assertEqual(payload["connections"], 2)
        self.assertIn("tick_duration_p95_ms", payload["metrics"])
        self.assertIn("coalesced_snapshot_count", payload["metrics"])

    async def test_malformed_json_and_version_mismatch_return_explicit_errors(self):
        await self.first.send("not-json")
        invalid = await self.receive_until(self.first, "error")
        self.assertEqual(invalid["payload"]["code"], "invalid_json")

        await self.first.send(
            json.dumps({"protocol_version": 999, "type": "ping", "payload": {}})
        )
        mismatch = await self.receive_until(self.first, "error")
        self.assertEqual(mismatch["payload"]["code"], "version_mismatch")

    async def test_two_clients_share_authoritative_identity_and_initial_snapshot(self):
        created, joined, first_snapshot, second_snapshot = await self.create_join_and_ready()

        self.assertEqual(created["payload"]["player_index"], 0)
        self.assertEqual(joined["payload"]["player_index"], 1)
        self.assertEqual(first_snapshot["payload"], second_snapshot["payload"])

        intent = CastIntent("incendio", 1, 0, "keyboard")
        payload = cast_intent_to_payload(intent, self.match_id)
        payload["player_index"] = 1
        await self.send(self.first, "cast", payload)
        event = await self.receive_until(
            self.first,
            "battle_event",
            lambda value: value["kind"] == "cast_accepted",
        )

        self.assertEqual(event["payload"]["data"]["player_index"], 0)
        self.assertEqual(event["payload"]["data"]["sequence"], 1)
        self.assertEqual(event["payload"]["match_id"], self.match_id)

    async def test_duplicate_cast_is_idempotently_rejected(self):
        await self.create_join_and_ready()
        intent = CastIntent("incendio", 1, 0, "keyboard")
        payload = cast_intent_to_payload(intent, self.match_id)

        await self.send(self.first, "cast", payload)
        await self.receive_until(
            self.first, "battle_event", lambda value: value["kind"] == "cast_accepted"
        )
        await self.send(self.first, "cast", payload)
        error = await self.receive_until(self.first, "error")

        self.assertEqual(error["payload"]["code"], "duplicate_sequence")
        room = next(iter(self.server.rooms.rooms.values()))
        self.assertEqual(len(room.session.engine.projectiles), 1)

    async def test_two_clients_observe_the_same_completed_round(self):
        await self.create_join_and_ready()
        room = next(iter(self.server.rooms.rooms.values()))
        room.session.engine.players[1].hp = 1.0
        intent = CastIntent("incendio", 1, 0, "keyboard")

        await self.send(self.first, "cast", cast_intent_to_payload(intent, self.match_id))
        first_final = await self.receive_until(
            self.first,
            "battle_snapshot",
            lambda value: value["winner"] == 0,
        )
        second_final = await self.receive_until(
            self.second,
            "battle_snapshot",
            lambda value: value["winner"] == 0,
        )

        self.assertEqual(first_final["payload"], second_final["payload"])
        self.assertEqual(first_final["payload"]["players"][1]["hp"], 0.0)

    async def test_cast_from_stale_match_is_rejected_before_rule_execution(self):
        await self.create_join_and_ready()
        intent = CastIntent("incendio", 1, 0, "keyboard")

        await self.send(
            self.first,
            "cast",
            cast_intent_to_payload(intent, match_id="previous-match"),
        )
        error = await self.receive_until(self.first, "error")

        self.assertEqual(error["payload"]["code"], "stale_match")
        room = next(iter(self.server.rooms.rooms.values()))
        self.assertEqual(room.session.engine.projectiles, [])

    async def test_heartbeat_and_reconnect_restore_the_authoritative_snapshot(self):
        created, _, _, _ = await self.create_join_and_ready()
        room = next(iter(self.server.rooms.rooms.values()))
        await self.send(self.second, "ping", {"time": 123}, "heartbeat")
        pong = await self.receive_until(self.second, "pong")
        self.assertEqual(pong["payload"]["echo"], 123)

        token = created["payload"]["reconnect_token"]
        room_code = created["payload"]["room_code"]
        await self.first.close()
        for _ in range(50):
            if room.paused:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(room.paused)

        self.first = await connect(f"ws://127.0.0.1:{self.server.port}")
        await self.send(
            self.first,
            "reconnect",
            {"room_code": room_code, "reconnect_token": token},
        )
        joined = await self.receive_until(self.first, "room_joined")
        snapshot = await self.receive_until(self.first, "battle_snapshot")

        self.assertTrue(joined["payload"]["reconnected"])
        self.assertEqual(snapshot["payload"]["match_id"], room.match_id)
        self.assertFalse(room.paused)

    async def test_server_stop_cleans_all_live_connection_senders(self):
        connections = tuple(self.server._connections.values())
        self.assertEqual(len(connections), 2)
        self.assertTrue(all(connection._writer_task is not None for connection in connections))

        await self.server.stop()

        self.assertEqual(self.server._connections, {})
        self.assertTrue(all(connection._writer_task is None for connection in connections))
        self.assertTrue(all(connection._close_task is None for connection in connections))


if __name__ == "__main__":
    unittest.main()
