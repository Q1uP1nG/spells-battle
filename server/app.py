from __future__ import annotations

import argparse
import asyncio
from collections import deque
import logging
import json
from time import perf_counter

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed
from websockets.datastructures import Headers
from websockets.http11 import Response

from network.protocol import (
    ProtocolError,
    cast_intent_from_payload,
    decode_message,
    event_to_payload,
    snapshot_to_payload,
)
from server.connection import ClientConnection
from server.config import ServerConfig
from server.logging import configure_logging
from server.room import RoomError
from server.room_manager import RoomManager


LOGGER = logging.getLogger("spells_server")
LOGGER.addHandler(logging.NullHandler())
LOGGER.propagate = False


def _percentile(values, quantile):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


class BattleServer:
    def __init__(self, config=None):
        self.config = config or ServerConfig.from_env()
        self.rooms = RoomManager(
            reconnect_timeout=self.config.reconnect_timeout,
            room_idle_timeout=self.config.room_idle_timeout,
            max_casts_per_second=self.config.max_casts_per_second,
            max_rooms=self.config.max_rooms,
        )
        self._connections = {}
        self._server = None
        self._tick_task = None
        self._closing = False
        self._tick_durations_ms = deque(maxlen=1024)
        self._tick_lags_ms = deque(maxlen=1024)

    @property
    def port(self):
        if self._server is None or not self._server.sockets:
            return self.config.port
        return self._server.sockets[0].getsockname()[1]

    @property
    def metrics_snapshot(self):
        connections = tuple(self._connections.values())
        send_durations = [
            duration
            for connection in connections
            for duration in connection.send_stats.send_durations_ms
        ]
        depths = [connection.reliable_queue_depth for connection in connections]
        return {
            "tick_duration_p50_ms": _percentile(self._tick_durations_ms, 0.50),
            "tick_duration_p95_ms": _percentile(self._tick_durations_ms, 0.95),
            "tick_lag_p50_ms": _percentile(self._tick_lags_ms, 0.50),
            "tick_lag_p95_ms": _percentile(self._tick_lags_ms, 0.95),
            "reliable_queue_depth_total": sum(depths),
            "reliable_queue_depth_max": max(depths, default=0),
            "snapshot_pending_count": sum(connection.snapshot_pending for connection in connections),
            "coalesced_snapshot_count": sum(
                connection.send_stats.coalesced_snapshot_count for connection in connections
            ),
            "send_duration_p50_ms": _percentile(send_durations, 0.50),
            "send_duration_p95_ms": _percentile(send_durations, 0.95),
            "send_timeout_count": sum(
                connection.send_stats.send_timeout_count for connection in connections
            ),
            "send_failure_count": sum(
                connection.send_stats.send_failure_count for connection in connections
            ),
            "backpressure_disconnect_count": sum(
                connection.send_stats.backpressure_disconnect_count for connection in connections
            ),
        }

    async def start(self):
        self._closing = False
        self._server = await serve(
            self._handle_connection,
            self.config.host,
            self.config.port,
            max_size=self.config.max_message_size,
            ping_interval=20,
            ping_timeout=20,
            process_request=self._process_request,
        )
        self._tick_task = asyncio.create_task(self._tick_loop(), name="battle-server-tick")
        return self

    async def stop(self):
        self._closing = True
        if self._tick_task is not None:
            self._tick_task.cancel()
            await asyncio.gather(self._tick_task, return_exceptions=True)
            self._tick_task = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_connection(self, websocket):
        if len(self._connections) >= self.config.max_connections:
            await websocket.close(code=1013, reason="server connection capacity reached")
            return
        connection = ClientConnection(
            websocket,
            queue_limit=self.config.client_send_queue,
            send_timeout=self.config.client_send_timeout,
            reliable_burst=self.config.client_reliable_burst,
        )
        connection.start_writer()
        self._connections[websocket] = connection
        try:
            async for raw in websocket:
                await self._handle_message(connection, raw)
        except ConnectionClosed:
            pass
        finally:
            await connection.stop_writer()
            self._connections.pop(websocket, None)
            if connection.room_code is not None and connection.player_index is not None:
                try:
                    room = self.rooms.get(connection.room_code)
                    room.disconnect(connection.player_index, asyncio.get_running_loop().time())
                    LOGGER.info(
                        "player disconnected",
                        extra={
                            "context": {
                                "room_code": room.room_code,
                                "player_index": connection.player_index,
                            }
                        },
                    )
                    await self._broadcast_room_state(room)
                except RoomError:
                    pass

    def _process_request(self, connection, request):
        if request.path != "/health":
            return None
        body = json.dumps(
            {
                "status": "ok",
                "rooms": len(self.rooms.rooms),
                "connections": len(self._connections),
                "metrics": self.metrics_snapshot,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        return Response(
            200,
            "OK",
            Headers(
                {
                    "Content-Type": "application/json; charset=utf-8",
                    "Content-Length": str(len(body)),
                    "Cache-Control": "no-store",
                }
            ),
            body,
        )

    async def _handle_message(self, connection, raw):
        request_id = None
        try:
            request_time = asyncio.get_running_loop().time()
            if not connection.allow_request(
                request_time, self.config.max_messages_per_second
            ):
                raise ProtocolError("rate_limited", "too many messages")
            message = decode_message(raw)
            request_id = message["request_id"]
            message_type = message["type"]
            payload = message["payload"]
            now = request_time

            if message_type == "create_room":
                self._ensure_unbound(connection)
                room, seat = self.rooms.create_room(now)
                self._bind(connection, room.room_code, seat.player_index)
                LOGGER.info(
                    "room created",
                    extra={"context": {"room_code": room.room_code, "match_id": room.match_id}},
                )
                await connection.send(
                    "room_created",
                    {
                        "room_code": room.room_code,
                        "match_id": room.match_id,
                        "player_index": seat.player_index,
                        "reconnect_token": seat.reconnect_token,
                    },
                    request_id,
                )
                await self._broadcast_room_state(room)
                return

            if message_type == "join_room":
                self._ensure_unbound(connection)
                room_code = self._required_text(payload, "room_code").upper()
                room, seat = self.rooms.join_room(room_code, now)
                self._bind(connection, room.room_code, seat.player_index)
                LOGGER.info(
                    "room joined",
                    extra={
                        "context": {
                            "room_code": room.room_code,
                            "player_index": seat.player_index,
                        }
                    },
                )
                await connection.send(
                    "room_joined",
                    {
                        "room_code": room.room_code,
                        "match_id": room.match_id,
                        "player_index": seat.player_index,
                        "reconnect_token": seat.reconnect_token,
                    },
                    request_id,
                )
                await self._broadcast_room_state(room)
                return

            if message_type == "reconnect":
                self._ensure_unbound(connection)
                room = self.rooms.get(self._required_text(payload, "room_code").upper())
                seat = room.reconnect(self._required_text(payload, "reconnect_token"), now)
                self._drop_existing_connection(room.room_code, seat.player_index, connection)
                self._bind(connection, room.room_code, seat.player_index)
                LOGGER.info(
                    "player reconnected",
                    extra={
                        "context": {
                            "room_code": room.room_code,
                            "player_index": seat.player_index,
                        }
                    },
                )
                await connection.send(
                    "room_joined",
                    {
                        "room_code": room.room_code,
                        "match_id": room.match_id,
                        "player_index": seat.player_index,
                        "reconnected": True,
                    },
                    request_id,
                )
                await self._broadcast_room_state(room)
                if room.snapshot() is not None:
                    await connection.send("battle_snapshot", snapshot_to_payload(room.snapshot()))
                return

            if message_type == "ping":
                await connection.send("pong", {"echo": payload.get("time")}, request_id)
                return

            room, player_index = self._bound_room(connection)
            if message_type == "select_character":
                self._require_current_match(room, payload)
                room.select_character(
                    player_index, self._required_text(payload, "character_id"), now
                )
                await self._broadcast_room_state(room)
            elif message_type == "ready":
                self._require_current_match(room, payload)
                if "ready" not in payload or not isinstance(payload["ready"], bool):
                    raise ProtocolError("invalid_field", "ready must be a boolean")
                room.set_ready(player_index, payload["ready"], now)
                await self._broadcast_room_state(room)
                if room.snapshot() is not None:
                    await self._broadcast(
                        room.room_code, "battle_snapshot", snapshot_to_payload(room.snapshot())
                    )
            elif message_type == "cast":
                command_match_id = self._required_text(payload, "match_id")
                if command_match_id != room.match_id:
                    raise RoomError("stale_match", "cast belongs to a different match")
                intent = cast_intent_from_payload(payload)
                _, events = room.submit_cast(player_index, intent, now)
                for event in events:
                    await self._broadcast(room.room_code, "battle_event", event_to_payload(event))
            elif message_type == "rematch":
                self._require_current_match(room, payload)
                room.request_rematch(player_index, now)
                await self._broadcast_room_state(room)
                if room.state.value == "RUNNING":
                    await self._broadcast(
                        room.room_code, "battle_snapshot", snapshot_to_payload(room.snapshot())
                    )
            else:
                raise ProtocolError("invalid_command", f"message type is not a client command: {message_type}")
        except (ProtocolError, RoomError, KeyError, ValueError) as exc:
            code = getattr(exc, "code", "invalid_request")
            LOGGER.warning(
                "request rejected",
                extra={
                    "context": {
                        "room_code": connection.room_code,
                        "player_index": connection.player_index,
                        "error_code": code,
                    }
                },
            )
            await connection.send("error", {"code": code, "message": str(exc)}, request_id)

    async def _tick_loop(self):
        interval = 1.0 / self.config.tick_rate
        snapshot_interval = max(1, round(self.config.tick_rate / self.config.snapshot_rate))
        loop = asyncio.get_running_loop()
        deadline = loop.time()
        while not self._closing:
            deadline += interval
            await asyncio.sleep(max(0.0, deadline - loop.time()))
            now = loop.time()
            tick_started = perf_counter()
            tick_lag_ms = max(0.0, (now - deadline) * 1000.0)
            for room in tuple(self.rooms.rooms.values()):
                events = room.step(interval)
                for event in events:
                    self._broadcast_nowait(
                        room.room_code, "battle_event", event_to_payload(event)
                    )
                if (
                    room.session is not None
                    and room.session.server_tick % snapshot_interval == 0
                    and not room.paused
                ):
                    self._broadcast_nowait(
                        room.room_code, "battle_snapshot", snapshot_to_payload(room.snapshot())
                    )
                if events and room.state.value == "ROUND_OVER":
                    self._broadcast_nowait(
                        room.room_code, "battle_snapshot", snapshot_to_payload(room.snapshot())
                    )
                    self._broadcast_nowait(room.room_code, "room_state", room.public_state())
            self.rooms.cleanup(now)
            tick_duration_ms = (perf_counter() - tick_started) * 1000.0
            self._tick_durations_ms.append(tick_duration_ms)
            self._tick_lags_ms.append(tick_lag_ms)
            LOGGER.debug(
                "server tick",
                extra={
                    "context": {
                        "tick_duration_ms": tick_duration_ms,
                        "tick_lag_ms": tick_lag_ms,
                        "room_count": len(self.rooms.rooms),
                    }
                },
            )

    async def _broadcast_room_state(self, room):
        await self._broadcast(room.room_code, "room_state", room.public_state())

    async def _broadcast(self, room_code, message_type, payload):
        self._broadcast_nowait(room_code, message_type, payload)

    def _broadcast_nowait(self, room_code, message_type, payload):
        targets = [
            connection
            for connection in self._connections.values()
            if connection.room_code == room_code
        ]
        for connection in targets:
            try:
                connection.enqueue(message_type, payload)
            except Exception as exc:
                LOGGER.warning(
                    "connection enqueue rejected",
                    extra={
                        "context": {
                            "room_code": room_code,
                            "player_index": connection.player_index,
                            "message_type": message_type,
                            **connection.send_metrics,
                            "error": type(exc).__name__,
                        }
                    },
                )

    def _bind(self, connection, room_code, player_index):
        connection.room_code = room_code
        connection.player_index = player_index

    def _ensure_unbound(self, connection):
        if connection.room_code is not None:
            raise RoomError("already_in_room", "connection is already bound to a room")

    def _bound_room(self, connection):
        if connection.room_code is None or connection.player_index is None:
            raise RoomError("not_in_room", "connection is not bound to a room")
        return self.rooms.get(connection.room_code), connection.player_index

    def _drop_existing_connection(self, room_code, player_index, replacement):
        for connection in self._connections.values():
            if (
                connection is not replacement
                and connection.room_code == room_code
                and connection.player_index == player_index
            ):
                connection.room_code = None
                connection.player_index = None

    @staticmethod
    def _required_text(payload, name):
        value = payload.get(name)
        if not isinstance(value, str) or not value:
            raise ProtocolError("missing_field", f"{name} must be a non-empty string")
        return value

    def _require_current_match(self, room, payload):
        if self._required_text(payload, "match_id") != room.match_id:
            raise RoomError("stale_match", "command belongs to a different match")


async def run_server(config=None):
    server = BattleServer(config)
    await server.start()
    LOGGER.info("server listening on %s:%s", server.config.host, server.port)
    try:
        await asyncio.Future()
    finally:
        await server.stop()


def main():
    parser = argparse.ArgumentParser(description="Spells Battle authoritative server")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    config = ServerConfig.from_env()
    if args.host is not None or args.port is not None:
        config = ServerConfig(
            **{
                **config.__dict__,
                "host": args.host if args.host is not None else config.host,
                "port": args.port if args.port is not None else config.port,
            }
        )
    configure_logging(config.log_level)
    asyncio.run(run_server(config))


if __name__ == "__main__":
    main()
