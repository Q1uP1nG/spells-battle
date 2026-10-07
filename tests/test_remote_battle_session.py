import queue
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game.battle_engine import BattleEngine
from game.remote_session import RemoteBattleSession, RemoteSessionState
from game.snapshots import snapshot_from_engine
from network.client import NetworkClient
from network.protocol import event_to_payload, snapshot_to_payload
from server.app import BattleServer
from server.config import ServerConfig


class FakeNetworkClient:
    def __init__(self):
        self.messages = queue.Queue()
        self.sent = []
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def send(self, message_type, payload, request_id=None):
        self.sent.append((message_type, payload, request_id))

    def send_priority(self, message_type, payload, request_id=None):
        self.sent.append((message_type, payload, request_id))

    def resume_sending(self):
        pass

    def drain(self, limit=256):
        values = []
        while len(values) < limit:
            try:
                values.append(self.messages.get_nowait())
            except queue.Empty:
                break
        return values

    def close(self):
        self.closed = True


class RemoteBattleSessionTests(unittest.TestCase):
    def make_session(self):
        client = FakeNetworkClient()
        return RemoteBattleSession(network_client=client), client

    def test_create_and_join_commands_do_not_include_player_identity(self):
        session, client = self.make_session()

        session.start()
        session.create_room()
        session.join_room("ab12cd")

        self.assertTrue(client.started)
        self.assertEqual(client.sent[0][0:2], ("create_room", {}))
        self.assertEqual(client.sent[1][1], {"room_code": "AB12CD"})
        self.assertNotIn("player_index", client.sent[1][1])

    def test_pre_room_transport_retry_remains_a_lobby_connection(self):
        session, client = self.make_session()
        client.messages.put(
            {"type": "transport_state", "payload": {"state": "RECONNECTING"}}
        )

        session.update(now=1.0, dt=0.0)

        self.assertEqual(session.state, RemoteSessionState.CONNECTING)
        self.assertFalse(session.has_room_assignment)
        self.assertEqual(session.status_message, "SERVER UNREACHABLE - RETRYING")

    def test_assigned_room_transport_retry_is_a_real_reconnect(self):
        session, client = self.make_session()
        session.player_index = 1
        session.room_code = "ABC123"
        session.match_id = "match"
        session.reconnect_token = "token"
        client.messages.put(
            {"type": "transport_state", "payload": {"state": "RECONNECTING"}}
        )

        session.update(now=1.0, dt=0.0)

        self.assertEqual(session.state, RemoteSessionState.RECONNECTING)
        self.assertTrue(session.has_room_assignment)
        self.assertEqual(session.disconnect_count, 1)

    def test_server_url_uses_environment_before_client_config(self):
        from game.remote_session import resolve_server_url

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "client_config.json"
            config_path.write_text(
                '{"server_url": "ws://config.example:8765"}', encoding="utf-8"
            )
            with patch.dict(os.environ, {"SPELLS_SERVER_URL": "ws://env.example:9000"}):
                self.assertEqual(
                    resolve_server_url(config_path), "ws://env.example:9000"
                )

    def test_server_url_uses_persistent_client_config(self):
        from game.remote_session import resolve_server_url

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "client_config.json"
            config_path.write_text(
                '{"server_url": "ws://config.example:8765"}', encoding="utf-8"
            )
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(
                    resolve_server_url(config_path), "ws://config.example:8765"
                )

    def test_remote_cast_is_pending_and_uses_server_bound_identity(self):
        session, client = self.make_session()
        session.player_index = 1
        session.match_id = "match-cast"
        session.state = RemoteSessionState.RUNNING

        result = session.request_cast(0, "incendio", 4.0, "cv")

        self.assertTrue(result.pending)
        self.assertEqual(client.sent[0][0], "cast")
        self.assertNotIn("player_index", client.sent[0][1])
        self.assertEqual(client.sent[0][1]["sequence"], 1)
        self.assertEqual(client.sent[0][1]["match_id"], "match-cast")

    def test_snapshot_updates_render_view_without_advancing_authority(self):
        session, client = self.make_session()
        engine = BattleEngine(("hermione", "snape"))
        engine.cast_spell(0, "incendio", 1.0)
        snapshot = snapshot_from_engine(engine, "match-remote", 7, 1.1)
        client.messages.put(
            {"type": "battle_snapshot", "payload": snapshot_to_payload(snapshot)}
        )

        session.update(now=10.0, dt=1.0 / 60.0)

        self.assertEqual(session.game.players[0].character_id, "hermione")
        self.assertEqual(session.game.projectiles[0].projectile_id, 1)
        self.assertEqual(session.game.projectiles[0].life, snapshot.projectiles[0].life_remaining)

    def test_server_event_drives_existing_local_presentation(self):
        session, client = self.make_session()
        engine = BattleEngine()
        engine.cast_spell(0, "protego", 1.0)
        event = engine.drain_events()[0]
        client.messages.put({"type": "battle_event", "payload": event_to_payload(event)})

        session.update(now=20.0, dt=0.0)

        self.assertEqual(session.game.players[0].last_message, "CAST PRO")
        self.assertIn(("cast", "protego"), session.game.sound_events)
        self.assertGreater(len(session.game.particles), 0)

    def test_snapshot_from_previous_match_is_ignored(self):
        session, client = self.make_session()
        session.match_id = "current-match"
        initial_hp = session.game.players[0].hp
        engine = BattleEngine()
        engine.players[0].hp = 1.0
        stale = snapshot_from_engine(engine, "previous-match", 99, 5.0)
        client.messages.put(
            {"type": "battle_snapshot", "payload": snapshot_to_payload(stale)}
        )

        session.update(now=10.0, dt=0.0)

        self.assertEqual(session.game.players[0].hp, initial_hp)
        self.assertIsNone(session.interpolator.current)

    def test_room_states_are_explicit(self):
        session, client = self.make_session()
        client.messages.put(
            {
                "type": "room_created",
                "payload": {
                    "room_code": "ABC123",
                    "match_id": "match",
                    "player_index": 0,
                    "reconnect_token": "secret",
                },
            }
        )
        client.messages.put(
            {
                "type": "room_state",
                "payload": {
                    "room_code": "ABC123",
                    "match_id": "match",
                    "state": "RUNNING",
                    "paused": False,
                    "players": [
                        {"player_index": 0, "character_id": "harry", "ready": True},
                        {"player_index": 1, "character_id": "ron", "ready": True},
                    ],
                },
            }
        )

        session.update(now=1.0, dt=0.0)

        self.assertEqual(session.state, RemoteSessionState.RUNNING)
        self.assertEqual(session.player_index, 0)
        self.assertTrue(session.round_started)

    def test_reconnecting_before_round_keeps_round_unstarted(self):
        session, client = self.make_session()
        client.messages.put(
            {"type": "transport_state", "payload": {"state": "CONNECTING"}}
        )
        client.messages.put(
            {"type": "transport_state", "payload": {"state": "RECONNECTING"}}
        )

        session.update(now=1.0, dt=0.0)

        self.assertEqual(session.state, RemoteSessionState.CONNECTING)
        self.assertFalse(session.round_started)

    def test_reconnecting_during_round_keeps_round_started(self):
        session, client = self.make_session()
        session.player_index = 0
        session.reconnect_token = "token"
        client.messages.put(
            {
                "type": "room_state",
                "payload": {
                    "room_code": "ABC123",
                    "match_id": "active-match",
                    "state": "RUNNING",
                    "paused": False,
                    "players": [None, None],
                },
            }
        )
        client.messages.put(
            {"type": "transport_state", "payload": {"state": "RECONNECTING"}}
        )

        session.update(now=1.0, dt=0.0)

        self.assertEqual(session.state, RemoteSessionState.RECONNECTING)
        self.assertTrue(session.round_started)

    def test_new_match_resets_round_started_flag(self):
        session, client = self.make_session()
        session.match_id = "old-match"
        session.player_index = 0
        session.round_started = True
        client.messages.put(
            {
                "type": "room_state",
                "payload": {
                    "room_code": "ABC123",
                    "match_id": "new-match",
                    "state": "WAITING",
                    "paused": False,
                    "players": [None, None],
                },
            }
        )

        session.update(now=1.0, dt=0.0)

        self.assertEqual(session.match_id, "new-match")
        self.assertFalse(session.round_started)
        self.assertEqual(session.state, RemoteSessionState.WAITING)

    def test_rematch_request_is_a_session_command(self):
        session, client = self.make_session()
        session.match_id = "match-rematch"

        session.request_rematch()

        self.assertEqual(
            client.sent,
            [("rematch", {"match_id": "match-rematch"}, None)],
        )

    def test_ping_updates_rtt_metric(self):
        session, client = self.make_session()
        session.state = RemoteSessionState.WAITING

        session.update(now=5.0, dt=0.0)
        self.assertEqual(client.sent[-1][0], "ping")
        client.messages.put({"type": "pong", "payload": {"echo": 5.0}})
        session.update(now=5.125, dt=0.0)

        self.assertEqual(session.rtt_ms, 125.0)


class RemoteBattleSessionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = BattleServer(
            ServerConfig(host="127.0.0.1", port=0, tick_rate=30, snapshot_rate=15)
        )
        await self.server.start()
        url = f"ws://127.0.0.1:{self.server.port}"
        self.first = RemoteBattleSession(server_url=url)
        self.second = RemoteBattleSession(server_url=url)
        self.first.start()
        self.second.start()

    async def asyncTearDown(self):
        await asyncio.gather(
            asyncio.to_thread(self.first.close),
            asyncio.to_thread(self.second.close),
        )
        await self.server.stop()

    async def wait_for(self, predicate, timeout=3.0):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            now = loop.time()
            self.first.update(now, 0.01)
            self.second.update(now, 0.01)
            if predicate():
                return
            await asyncio.sleep(0.01)
        self.fail("remote sessions did not reach expected state")

    async def test_two_queue_isolated_sessions_complete_one_server_owned_round(self):
        self.first.create_room()
        await self.wait_for(lambda: bool(self.first.room_code))
        self.second.join_room(self.first.room_code)
        await self.wait_for(lambda: self.second.player_index == 1)
        self.first.set_ready()
        self.second.set_ready()
        await self.wait_for(
            lambda: self.first.state == self.second.state == RemoteSessionState.RUNNING
        )
        room = next(iter(self.server.rooms.rooms.values()))
        room.session.engine.players[1].hp = 1.0

        result = self.first.request_cast(0, "incendio", 1.0, "keyboard")
        self.assertTrue(result.pending)
        await self.wait_for(
            lambda: self.first.game.winner == self.second.game.winner == 0,
            timeout=3.0,
        )

        self.assertEqual(self.first.game.players[1].hp, 0.0)
        self.assertEqual(self.second.game.players[1].hp, 0.0)

        self.first.request_rematch()
        self.second.request_rematch()
        await self.wait_for(
            lambda: self.first.state == self.second.state == RemoteSessionState.RUNNING
            and self.first.game.winner is None
            and self.second.game.winner is None
        )

    async def test_lobby_command_queued_during_disconnect_runs_after_reconnect(self):
        await asyncio.to_thread(self.first.close)
        self.first = RemoteBattleSession(
            server_url=f"ws://127.0.0.1:{self.server.port}",
            network_client=NetworkClient(
                f"ws://127.0.0.1:{self.server.port}", reconnect_delay=1.0
            ),
        )
        self.first.start()
        await self.wait_for(lambda: self.first.client.state.value == "CONNECTED")
        self.first.create_room()
        await self.wait_for(lambda: bool(self.first.room_code))
        self.second.join_room(self.first.room_code)
        await self.wait_for(lambda: self.second.player_index == 1)

        room = next(iter(self.server.rooms.rooms.values()))
        connection = next(
            value
            for value in self.server._connections.values()
            if value.room_code == room.room_code and value.player_index == 0
        )
        await connection.websocket.close()
        await self.wait_for(lambda: self.first.state == RemoteSessionState.RECONNECTING)

        self.first.select_character("snape")
        await self.wait_for(
            lambda: room.seats[0].character_id == "snape"
            and self.first.game.players[0].character_id == "snape"
            and self.second.game.players[0].character_id == "snape",
            timeout=5.0,
        )
        self.assertEqual(self.first.game.players[0].character_id, "snape")

    async def test_running_round_resumes_after_disconnect(self):
        self.first.create_room()
        await self.wait_for(lambda: bool(self.first.room_code))
        self.second.join_room(self.first.room_code)
        await self.wait_for(lambda: self.second.player_index == 1)
        self.first.set_ready()
        self.second.set_ready()
        await self.wait_for(
            lambda: self.first.state == self.second.state == RemoteSessionState.RUNNING
        )
        match_id = self.first.match_id
        connection = next(
            value for value in self.server._connections.values()
            if value.room_code == self.first.room_code and value.player_index == 0
        )
        await connection.websocket.close()
        await self.wait_for(lambda: self.first.disconnect_count > 0)
        await self.wait_for(
            lambda: self.first.state == self.second.state == RemoteSessionState.RUNNING
            and not self.server.rooms.get(self.first.room_code).paused,
            timeout=5.0,
        )
        self.assertEqual(self.first.match_id, match_id)
        self.assertTrue(self.first.round_started)
        self.assertEqual(self.first.player_index, 0)


if __name__ == "__main__":
    unittest.main()
