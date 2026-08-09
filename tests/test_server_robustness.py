import asyncio
import json
import logging
import unittest

from server.connection import ClientConnection, SlowClientError
from server.logging import JsonFormatter


class FakeWebSocket:
    def __init__(self):
        self.closed = None

    async def send(self, raw):
        await asyncio.Future()

    async def close(self, code, reason):
        self.closed = (code, reason)


class ServerRobustnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_client_queue_is_bounded_and_rejected(self):
        websocket = FakeWebSocket()
        connection = ClientConnection(websocket, queue_limit=2)

        await connection.send("ping", {})
        await connection.send("ping", {})
        with self.assertRaises(SlowClientError):
            await connection.send("ping", {})
        await asyncio.sleep(0)

        self.assertEqual(websocket.closed, (1013, "client too slow"))

    async def test_writer_can_be_cancelled_without_leaking_task(self):
        connection = ClientConnection(FakeWebSocket())
        connection.start_writer()
        await connection.stop_writer()

        self.assertIsNone(connection._writer_task)


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


if __name__ == "__main__":
    unittest.main()
