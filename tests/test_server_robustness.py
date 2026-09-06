import asyncio
import json
import logging
import unittest

from network.protocol import decode_message
from game.snapshots import BattleSnapshot, PROTOCOL_VERSION
from server.app import BattleServer
from server.config import ServerConfig
from server.connection import ClientConnection, SlowClientError
from server.logging import JsonFormatter


class FakeWebSocket:
    def __init__(self):
        self.closed = None

    async def send(self, raw):
        await asyncio.Future()

    async def close(self, code, reason):
        self.closed = (code, reason)


class CapturingWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = None

    async def send(self, raw):
        self.sent.append(decode_message(raw))

    async def close(self, code, reason):
        self.closed = (code, reason)


class FailingWebSocket(CapturingWebSocket):
    async def send(self, raw):
        raise ConnectionError("simulated websocket failure")


class TickRoom:
    room_code = "TICK01"
    paused = False

    def __init__(self):
        self.steps = 0
        self.session = self
        self.server_tick = 0
        self.state = type("State", (), {"value": "RUNNING"})()

    def step(self, interval):
        self.steps += 1
        self.server_tick += 1
        return []

    def snapshot(self):
        return BattleSnapshot(
            protocol_version=PROTOCOL_VERSION,
            match_id="tick-test",
            server_tick=self.server_tick,
            match_time=0.0,
            players=(),
            projectiles=(),
            winner=None,
        )


class TickRooms:
    def __init__(self, room):
        self.rooms = {room.room_code: room}

    def cleanup(self, now):
        return []


class ServerRobustnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_client_queue_is_bounded_and_rejected(self):
        websocket = FakeWebSocket()
        connection = ClientConnection(websocket, queue_limit=2)

        await connection.send("ping", {})
        await connection.send("ping", {})
        with self.assertRaises(SlowClientError):
            await connection.send("ping", {})
        with self.assertRaises(SlowClientError):
            await connection.send("ping", {})
        await asyncio.sleep(0)

        self.assertEqual(websocket.closed, (1013, "client too slow"))
        self.assertEqual(connection.send_stats.backpressure_disconnect_count, 1)

    async def test_writer_can_be_cancelled_without_leaking_task(self):
        connection = ClientConnection(FakeWebSocket())
        connection.start_writer()
        await connection.stop_writer()

        self.assertIsNone(connection._writer_task)

    async def test_snapshots_use_one_latest_value_slot(self):
        connection = ClientConnection(CapturingWebSocket())

        connection.enqueue("battle_snapshot", {"server_tick": 1})
        connection.enqueue("battle_snapshot", {"server_tick": 2})
        connection.enqueue("battle_snapshot", {"server_tick": 3})

        self.assertTrue(connection.snapshot_pending)
        self.assertEqual(connection.send_stats.coalesced_snapshot_count, 2)
        self.assertEqual(connection.reliable_queue_depth, 0)

    async def test_sender_preserves_reliable_order_then_sends_latest_snapshot(self):
        websocket = CapturingWebSocket()
        connection = ClientConnection(websocket)
        connection.enqueue("battle_event", {"sequence": 1})
        connection.enqueue("battle_event", {"sequence": 2})
        connection.enqueue("battle_snapshot", {"server_tick": 4})
        connection.enqueue("battle_snapshot", {"server_tick": 5})
        connection.start_writer()

        for _ in range(20):
            if len(websocket.sent) == 3:
                break
            await asyncio.sleep(0)
        await connection.stop_writer()

        self.assertEqual([item["type"] for item in websocket.sent], [
            "battle_event", "battle_event", "battle_snapshot",
        ])
        self.assertEqual(websocket.sent[0]["payload"]["sequence"], 1)
        self.assertEqual(websocket.sent[1]["payload"]["sequence"], 2)
        self.assertEqual(websocket.sent[2]["payload"]["server_tick"], 5)

    async def test_broadcast_enqueue_does_not_wait_for_blocked_websocket_send(self):
        server = BattleServer()
        slow = ClientConnection(FakeWebSocket(), room_code="SLOW", player_index=0)
        fast_socket = CapturingWebSocket()
        fast = ClientConnection(fast_socket, room_code="FAST", player_index=0)
        slow.start_writer()
        fast.start_writer()
        server._connections = {slow.websocket: slow, fast.websocket: fast}

        server._broadcast_nowait("SLOW", "battle_snapshot", {"server_tick": 1})
        server._broadcast_nowait("FAST", "battle_event", {"sequence": 1})
        for _ in range(20):
            if fast_socket.sent:
                break
            await asyncio.sleep(0)

        self.assertEqual(fast_socket.sent[0]["type"], "battle_event")
        self.assertEqual(slow.reliable_queue_depth, 0)
        self.assertLessEqual(int(slow.snapshot_pending), 1)
        await slow.stop_writer()
        await fast.stop_writer()

    async def test_send_timeout_closes_only_that_connection(self):
        websocket = FakeWebSocket()
        connection = ClientConnection(websocket, send_timeout=0.001)
        connection.start_writer()
        connection.enqueue("battle_event", {"sequence": 1})

        await asyncio.sleep(0.02)
        await connection.stop_writer()

        self.assertEqual(websocket.closed, (1013, "client send timeout"))
        self.assertEqual(connection.send_stats.send_timeout_count, 1)
        self.assertEqual(connection.send_stats.messages_sent, 0)
        self.assertEqual(connection.reliable_queue_depth, 0)

    async def test_completed_connection_failures_remain_in_server_metrics(self):
        server = BattleServer()
        connection = ClientConnection(CapturingWebSocket())
        connection.send_stats.send_timeout_count = 2
        connection.send_stats.send_failure_count = 1
        connection.send_stats.backpressure_disconnect_count = 1
        connection.send_stats.coalesced_snapshot_count = 3
        connection.send_stats.send_durations_ms.extend([1.0, 3.0])

        server._record_completed_connection(connection)

        metrics = server.metrics_snapshot
        self.assertEqual(metrics["send_timeout_count"], 2)
        self.assertEqual(metrics["send_failure_count"], 1)
        self.assertEqual(metrics["backpressure_disconnect_count"], 1)
        self.assertEqual(metrics["coalesced_snapshot_count"], 3)
        self.assertEqual(metrics["send_duration_p50_ms"], 2.0)
        self.assertAlmostEqual(metrics["send_duration_p95_ms"], 2.9)

    async def test_websocket_send_failure_closes_sender_and_is_counted(self):
        websocket = FailingWebSocket()
        connection = ClientConnection(websocket)
        connection.start_writer()
        connection.enqueue("battle_event", {"sequence": 1})

        for _ in range(20):
            if websocket.closed is not None:
                break
            await asyncio.sleep(0)
        await connection.stop_writer()

        self.assertEqual(websocket.closed, (1011, "client send failed"))
        self.assertEqual(connection.send_stats.send_failure_count, 1)
        self.assertEqual(connection.send_stats.messages_sent, 0)

    async def test_blocked_sender_does_not_reduce_authoritative_tick_frequency(self):
        config = ServerConfig(port=0, tick_rate=100, snapshot_rate=100)
        server = BattleServer(config)
        room = TickRoom()
        server.rooms = TickRooms(room)
        connection = ClientConnection(
            FakeWebSocket(),
            room_code=room.room_code,
            player_index=0,
            send_timeout=5.0,
        )
        connection.start_writer()
        server._connections = {connection.websocket: connection}

        tick_task = asyncio.create_task(server._tick_loop())
        await asyncio.sleep(0.07)
        server._closing = True
        await asyncio.wait_for(tick_task, timeout=0.1)
        await connection.stop_writer()

        self.assertGreaterEqual(room.steps, 5)
        self.assertGreater(connection.send_stats.coalesced_snapshot_count, 0)
        self.assertEqual(len(server._tick_durations_ms), room.steps)

    async def test_unexpected_handler_error_responds_without_dropping_connection(self):
        server = BattleServer()
        websocket = CapturingWebSocket()

        class ExplodingConnection(ClientConnection):
            def allow_request(self, now, limit):
                raise TypeError("simulated handler bug")

        connection = ExplodingConnection(websocket)
        connection.start_writer()
        raw = json.dumps({"protocol_version": PROTOCOL_VERSION, "type": "ping", "payload": {}})

        await server._handle_message(connection, raw)

        for _ in range(20):
            if websocket.sent:
                break
            await asyncio.sleep(0)
        await connection.stop_writer()

        self.assertEqual(websocket.closed, None)
        self.assertEqual(len(websocket.sent), 1)
        self.assertEqual(websocket.sent[0]["type"], "error")
        self.assertEqual(websocket.sent[0]["payload"]["code"], "internal_error")

    async def test_general_message_rate_is_bounded_per_connection(self):
        connection = ClientConnection(FakeWebSocket())

        self.assertTrue(connection.allow_request(1.0, limit=2))
        self.assertTrue(connection.allow_request(1.1, limit=2))
        self.assertFalse(connection.allow_request(1.2, limit=2))
        self.assertTrue(connection.allow_request(2.1, limit=2))


class StructuredLoggingTests(unittest.TestCase):
    def test_sensitive_context_is_redacted(self):
        record = logging.LogRecord("spells_server", logging.INFO, __file__, 1, "joined", (), None)
        record.context = {
            "room_code": "ABC123",
            "reconnect_token": "do-not-log",
            "nested": {"frame": "pixels"},
        }

        payload = json.loads(JsonFormatter().format(record))

        self.assertEqual(payload["context"]["room_code"], "ABC123")
        self.assertEqual(payload["context"]["reconnect_token"], "[REDACTED]")
        self.assertEqual(payload["context"]["nested"]["frame"], "[REDACTED]")
        self.assertNotIn("do-not-log", json.dumps(payload))

    def test_exception_records_include_traceback(self):
        import sys

        try:
            raise ValueError("handler failed")
        except ValueError:
            record = logging.LogRecord(
                "spells_server", logging.ERROR, __file__, 1, "request handler failed", (), sys.exc_info(),
            )

        payload = json.loads(JsonFormatter().format(record))

        self.assertIn("exception", payload)
        self.assertIn("ValueError: handler failed", payload["exception"])


if __name__ == "__main__":
    unittest.main()
