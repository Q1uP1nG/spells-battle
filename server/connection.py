from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from network.protocol import encode_message


class SlowClientError(RuntimeError):
    pass


@dataclass
class ClientConnection:
    websocket: object
    room_code: str | None = None
    player_index: int | None = None
    queue_limit: int = 64
    _send_queue: asyncio.Queue = field(init=False)
    _writer_task: asyncio.Task | None = field(default=None, init=False)

    def __post_init__(self):
        self._send_queue = asyncio.Queue(maxsize=self.queue_limit)

    def start_writer(self):
        if self._writer_task is None:
            self._writer_task = asyncio.create_task(self._writer(), name="websocket-writer")

    async def send(self, message_type, payload, request_id=None):
        raw = encode_message(message_type, payload, request_id=request_id)
        try:
            self._send_queue.put_nowait(raw)
        except asyncio.QueueFull as exc:
            asyncio.create_task(self.websocket.close(code=1013, reason="client too slow"))
            raise SlowClientError("client send queue is full") from exc

    async def stop_writer(self):
        task = self._writer_task
        self._writer_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _writer(self):
        while True:
            await self.websocket.send(await self._send_queue.get())
