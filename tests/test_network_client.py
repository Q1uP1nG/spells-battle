import asyncio
import unittest

from network.client import NetworkClient
from network.protocol import decode_message


class NetworkClientQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconnect_is_sent_while_room_commands_wait_for_confirmation(self):
        client = NetworkClient("ws://127.0.0.1:8765")
        client._resume_sending.clear()
        client.send("ready", {"ready": True, "match_id": "match"})
        client.send_priority("reconnect", {"room_code": "ABC123", "reconnect_token": "token"})
        sent = []
        reconnect_sent = asyncio.Event()
        ready_sent = asyncio.Event()

        class WebSocket:
            async def send(self, raw):
                message = decode_message(raw)
                sent.append(message["type"])
                if message["type"] == "reconnect":
                    reconnect_sent.set()
                else:
                    ready_sent.set()

            async def recv(self):
                await asyncio.Future()

        task = asyncio.create_task(client._connected_loop(WebSocket()))
        try:
            await asyncio.wait_for(reconnect_sent.wait(), timeout=1.0)
            self.assertEqual(sent, ["reconnect"])
            self.assertFalse(client._resume_sending.is_set())
            self.assertEqual(client.outgoing.qsize(), 1)
            client.resume_sending()
            await asyncio.wait_for(ready_sent.wait(), timeout=1.0)
            self.assertEqual(sent, ["reconnect", "ready"])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
