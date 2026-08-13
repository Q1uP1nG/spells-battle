from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
import logging
from time import perf_counter

from network.protocol import encode_message


LOGGER = logging.getLogger("spells_server.connection")


class SlowClientError(RuntimeError):
    pass


def _percentile(values, quantile):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


@dataclass
class ConnectionSendStats:
    reliable_enqueued: int = 0
    snapshots_enqueued: int = 0
    coalesced_snapshot_count: int = 0
    messages_sent: int = 0
    send_timeout_count: int = 0
    send_failure_count: int = 0
    backpressure_disconnect_count: int = 0
    send_durations_ms: deque = field(default_factory=lambda: deque(maxlen=1024))


@dataclass
class ClientConnection:
    websocket: object
    room_code: str | None = None
    player_index: int | None = None
    queue_limit: int = 64
    send_timeout: float = 5.0
    reliable_burst: int = 8
    _reliable_queue: asyncio.Queue = field(init=False)
    _latest_snapshot: str | None = field(default=None, init=False)
    _wakeup: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _writer_task: asyncio.Task | None = field(default=None, init=False)
    _close_task: asyncio.Task | None = field(default=None, init=False)
    _closing: bool = field(default=False, init=False)
    _request_times: deque = field(default_factory=deque, init=False)
    send_stats: ConnectionSendStats = field(default_factory=ConnectionSendStats, init=False)

    def __post_init__(self):
        self._reliable_queue = asyncio.Queue(maxsize=self.queue_limit)

    @property
    def reliable_queue_depth(self):
        return self._reliable_queue.qsize()

    @property
    def snapshot_pending(self):
        return self._latest_snapshot is not None

    @property
    def send_metrics(self):
        durations = list(self.send_stats.send_durations_ms)
        return {
            "reliable_queue_depth": self.reliable_queue_depth,
            "snapshot_pending": self.snapshot_pending,
            "coalesced_snapshot_count": self.send_stats.coalesced_snapshot_count,
            "send_duration_p50_ms": _percentile(durations, 0.50),
            "send_duration_p95_ms": _percentile(durations, 0.95),
            "send_timeout_count": self.send_stats.send_timeout_count,
            "send_failure_count": self.send_stats.send_failure_count,
            "backpressure_disconnect_count": self.send_stats.backpressure_disconnect_count,
        }

    def start_writer(self):
        if self._writer_task is None:
            self._closing = False
            self._writer_task = asyncio.create_task(self._writer(), name="websocket-sender")

    def enqueue(self, message_type, payload, request_id=None):
        """Synchronously queue a message; never waits for the network."""
        if self._closing:
            raise SlowClientError("connection sender is closing")
        raw = encode_message(message_type, payload, request_id=request_id)
        if message_type == "battle_snapshot":
            if self._latest_snapshot is not None:
                self.send_stats.coalesced_snapshot_count += 1
            self._latest_snapshot = raw
            self.send_stats.snapshots_enqueued += 1
            self._wakeup.set()
            return
        try:
            self._reliable_queue.put_nowait(raw)
        except asyncio.QueueFull as exc:
            self.send_stats.backpressure_disconnect_count += 1
            LOGGER.warning(
                "disconnecting client after reliable queue overflow",
                extra={"context": self.send_metrics},
            )
            self._schedule_close(1013, "client too slow")
            raise SlowClientError("client reliable send queue is full") from exc
        self.send_stats.reliable_enqueued += 1
        self._wakeup.set()

    async def send(self, message_type, payload, request_id=None):
        """Compatibility wrapper for request handlers and older callers."""
        self.enqueue(message_type, payload, request_id=request_id)

    async def stop_writer(self):
        self._closing = True
        self._wakeup.set()
        task = self._writer_task
        self._writer_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        close_task = self._close_task
        self._close_task = None
        if close_task is not None:
            await asyncio.gather(close_task, return_exceptions=True)

    def allow_request(self, now, limit):
        while self._request_times and now - self._request_times[0] >= 1.0:
            self._request_times.popleft()
        if len(self._request_times) >= limit:
            return False
        self._request_times.append(float(now))
        return True

    def _schedule_close(self, code, reason):
        self._closing = True
        self._wakeup.set()
        if self._close_task is None or self._close_task.done():
            self._close_task = asyncio.create_task(
                self.websocket.close(code=code, reason=reason),
                name="websocket-backpressure-close",
            )

    def _take_snapshot(self):
        raw = self._latest_snapshot
        self._latest_snapshot = None
        return raw

    async def _send_raw(self, raw):
        started = perf_counter()
        try:
            await asyncio.wait_for(self.websocket.send(raw), timeout=self.send_timeout)
        except asyncio.TimeoutError:
            self.send_stats.send_timeout_count += 1
            LOGGER.warning(
                "disconnecting client after send timeout",
                extra={"context": self.send_metrics},
            )
            # Retrying is unsafe: the peer may have received the frame before the
            # timeout fired. Close and recover from an authoritative snapshot instead.
            self._schedule_close(1013, "client send timeout")
            return False
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception:
            self.send_stats.send_failure_count += 1
            LOGGER.warning(
                "disconnecting client after send failure",
                extra={"context": self.send_metrics},
            )
            self._schedule_close(1011, "client send failed")
            return False
        finally:
            self.send_stats.send_durations_ms.append(
                (perf_counter() - started) * 1000.0
            )
        self.send_stats.messages_sent += 1
        return True

    async def _writer(self):
        while not self._closing:
            sent_any = False
            for _ in range(max(1, self.reliable_burst)):
                try:
                    raw = self._reliable_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                sent_any = True
                if not await self._send_raw(raw):
                    self._closing = True
                    return

            snapshot = self._take_snapshot()
            if snapshot is not None:
                sent_any = True
                if not await self._send_raw(snapshot):
                    self._closing = True
                    return

            if sent_any:
                continue
            self._wakeup.clear()
            if not self._reliable_queue.empty() or self._latest_snapshot is not None:
                self._wakeup.set()
                continue
            await self._wakeup.wait()
