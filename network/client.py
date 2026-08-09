from __future__ import annotations

import asyncio
from enum import Enum
import queue
import threading

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from network.protocol import decode_message, encode_message


class ConnectionState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    CLOSED = "CLOSED"


class NetworkClient:
    """WebSocket worker isolated from the CV/UI main thread by queues."""

    def __init__(self, server_url, reconnect_delay=0.5, max_message_size=16_384):
        self.server_url = str(server_url)
        self.reconnect_delay = float(reconnect_delay)
        self.max_message_size = int(max_message_size)
        self.incoming = queue.Queue()
        self.outgoing = queue.Queue()
        self.state = ConnectionState.DISCONNECTED
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._thread_main, name="spells-network", daemon=True)
        self._thread.start()

    def send(self, message_type, payload, request_id=None):
        if self.state == ConnectionState.CLOSED:
            raise RuntimeError("network client is closed")
        self.outgoing.put((message_type, dict(payload), request_id))

    def drain(self, limit=256):
        messages = []
        for _ in range(limit):
            try:
                messages.append(self.incoming.get_nowait())
            except queue.Empty:
                break
        return messages

    def close(self, timeout=2.0):
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        self._set_state(ConnectionState.CLOSED)

    def _thread_main(self):
        try:
            asyncio.run(self._run())
        except Exception as exc:
            self.incoming.put(
                {"type": "transport_error", "payload": {"message": str(exc)}}
            )
            self._set_state(ConnectionState.DISCONNECTED)

    async def _run(self):
        first_attempt = True
        while not self._stop.is_set():
            self._set_state(
                ConnectionState.CONNECTING if first_attempt else ConnectionState.RECONNECTING
            )
            try:
                async with connect(
                    self.server_url,
                    max_size=self.max_message_size,
                    ping_interval=20,
                    ping_timeout=20,
                ) as websocket:
                    self._set_state(ConnectionState.CONNECTED)
                    await self._connected_loop(websocket)
            except (OSError, ConnectionClosed, asyncio.TimeoutError) as exc:
                self.incoming.put(
                    {"type": "transport_error", "payload": {"message": str(exc)}}
                )
            first_attempt = False
            if not self._stop.is_set():
                self._set_state(ConnectionState.RECONNECTING)
                await asyncio.sleep(self.reconnect_delay)
        self._set_state(ConnectionState.CLOSED)

    async def _connected_loop(self, websocket):
        while not self._stop.is_set():
            while True:
                try:
                    message_type, payload, request_id = self.outgoing.get_nowait()
                except queue.Empty:
                    break
                await websocket.send(encode_message(message_type, payload, request_id))
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=0.03)
            except asyncio.TimeoutError:
                continue
            self.incoming.put(decode_message(raw))

    def _set_state(self, state):
        if self.state == state:
            return
        self.state = state
        self.incoming.put({"type": "transport_state", "payload": {"state": state.value}})
