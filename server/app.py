from __future__ import annotations

import argparse
import asyncio
import logging
import json

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

    @property
    def port(self):
        if self._server is None or not self._server.sockets:
            return self.config.port
        return self._server.sockets[0].getsockname()[1]

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
        connection = ClientConnection(websocket, queue_limit=self.config.client_send_queue)
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
            message = decode_message(raw)
            request_id = message["request_id"]
            message_type = message["type"]
            payload = message["payload"]
            now = asyncio.get_running_loop().time()

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
                room.select_character(
                    player_index, self._required_text(payload, "character_id"), now
                )
                await self._broadcast_room_state(room)
            elif message_type == "ready":
                if "ready" not in payload or not isinstance(payload["ready"], bool):
                    raise ProtocolError("invalid_field", "ready must be a boolean")
                room.set_ready(player_index, payload["ready"], now)
                await self._broadcast_room_state(room)
                if room.snapshot() is not None:
                    await self._broadcast(
                        room.room_code, "battle_snapshot", snapshot_to_payload(room.snapshot())
                    )
            elif message_type == "cast":
                intent = cast_intent_from_payload(payload)
                _, events = room.submit_cast(player_index, intent, now)
                for event in events:
                    await self._broadcast(room.room_code, "battle_event", event_to_payload(event))
            elif message_type == "rematch":
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
            for room in tuple(self.rooms.rooms.values()):
                events = room.step(interval)
                for event in events:
                    await self._broadcast(room.room_code, "battle_event", event_to_payload(event))
                if (
                    room.session is not None
                    and room.session.server_tick % snapshot_interval == 0
                    and not room.paused
                ):
                    await self._broadcast(
                        room.room_code, "battle_snapshot", snapshot_to_payload(room.snapshot())
                    )
                if events and room.state.value == "ROUND_OVER":
                    await self._broadcast(
                        room.room_code, "battle_snapshot", snapshot_to_payload(room.snapshot())
                    )
                    await self._broadcast_room_state(room)
            self.rooms.cleanup(now)

    async def _broadcast_room_state(self, room):
        await self._broadcast(room.room_code, "room_state", room.public_state())

    async def _broadcast(self, room_code, message_type, payload):
        targets = [
            connection
            for connection in self._connections.values()
            if connection.room_code == room_code
        ]
        if targets:
            await asyncio.gather(
                *(connection.send(message_type, payload) for connection in targets),
                return_exceptions=True,
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
