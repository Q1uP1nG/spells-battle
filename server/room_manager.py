from __future__ import annotations

import secrets
import string

from server.room import Room, RoomError, RoomState


ROOM_ALPHABET = string.ascii_uppercase + string.digits


class RoomManager:
    def __init__(
        self,
        reconnect_timeout=45.0,
        room_idle_timeout=900.0,
        max_casts_per_second=12,
        max_rooms=1000,
    ):
        self.reconnect_timeout = reconnect_timeout
        self.room_idle_timeout = room_idle_timeout
        self.max_casts_per_second = max_casts_per_second
        self.max_rooms = int(max_rooms)
        self.rooms = {}

    def create_room(self, now):
        if len(self.rooms) >= self.max_rooms:
            raise RoomError("server_capacity", "server room capacity reached")
        room_code = self._new_code()
        room = Room(
            room_code,
            now,
            reconnect_timeout=self.reconnect_timeout,
            max_casts_per_second=self.max_casts_per_second,
        )
        seat = room.add_player(now)
        self.rooms[room_code] = room
        return room, seat

    def join_room(self, room_code, now):
        room = self.get(room_code)
        return room, room.add_player(now)

    def get(self, room_code):
        room = self.rooms.get(str(room_code).upper())
        if room is None or room.state == RoomState.CLOSED:
            raise RoomError("room_not_found", "room code was not found")
        return room

    def cleanup(self, now):
        removed = []
        for code, room in tuple(self.rooms.items()):
            if room.reconnect_expired(now) or now - room.last_active_at > self.room_idle_timeout:
                room.state = RoomState.CLOSED
                removed.append(code)
                del self.rooms[code]
        return removed

    def _new_code(self):
        while True:
            code = "".join(secrets.choice(ROOM_ALPHABET) for _ in range(6))
            if code not in self.rooms:
                return code
