from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import secrets
import uuid

from game.characters import DEFAULT_CHARACTER_IDS, get_character
from server.battle_session import AuthoritativeBattleSession


class RoomError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class RoomState(str, Enum):
    WAITING_FOR_PLAYER = "WAITING_FOR_PLAYER"
    READY_CHECK = "READY_CHECK"
    RUNNING = "RUNNING"
    ROUND_OVER = "ROUND_OVER"
    CLOSED = "CLOSED"


@dataclass
class Seat:
    player_index: int
    reconnect_token: str
    character_id: str
    ready: bool = False
    connected: bool = True
    disconnected_at: float | None = None
    last_sequence: int = 0
    cast_times: deque = field(default_factory=deque)
    rematch_ready: bool = False


class Room:
    def __init__(self, room_code, now, reconnect_timeout=45.0, max_casts_per_second=12):
        self.room_code = room_code
        self.match_id = uuid.uuid4().hex
        self.created_at = float(now)
        self.last_active_at = float(now)
        self.reconnect_timeout = float(reconnect_timeout)
        self.max_casts_per_second = int(max_casts_per_second)
        self.state = RoomState.WAITING_FOR_PLAYER
        self.seats: list[Seat | None] = [None, None]
        self.session: AuthoritativeBattleSession | None = None
        self.paused = False

    def add_player(self, now):
        try:
            player_index = self.seats.index(None)
        except ValueError as exc:
            raise RoomError("room_full", "room already has two players") from exc
        seat = Seat(
            player_index=player_index,
            reconnect_token=secrets.token_urlsafe(24),
            character_id=DEFAULT_CHARACTER_IDS[player_index],
        )
        self.seats[player_index] = seat
        self.last_active_at = float(now)
        if all(self.seats):
            self.state = RoomState.READY_CHECK
        return seat

    def reconnect(self, token, now):
        for seat in self.seats:
            if seat and secrets.compare_digest(seat.reconnect_token, token):
                if seat.disconnected_at is not None and now - seat.disconnected_at > self.reconnect_timeout:
                    raise RoomError("reconnect_expired", "reconnect window expired")
                seat.connected = True
                seat.disconnected_at = None
                self.paused = any(value and not value.connected for value in self.seats)
                self.last_active_at = float(now)
                return seat
        raise RoomError("invalid_reconnect_token", "reconnect token is invalid")

    def disconnect(self, player_index, now):
        seat = self._seat(player_index)
        seat.connected = False
        seat.disconnected_at = float(now)
        if self.state in (RoomState.RUNNING, RoomState.ROUND_OVER):
            self.paused = True
        self.last_active_at = float(now)

    def select_character(self, player_index, character_id, now):
        if self.state not in (RoomState.WAITING_FOR_PLAYER, RoomState.READY_CHECK):
            raise RoomError("invalid_room_state", "characters cannot change after the round starts")
        get_character(character_id)
        seat = self._seat(player_index)
        seat.character_id = character_id
        seat.ready = False
        self.last_active_at = float(now)

    def set_ready(self, player_index, ready, now):
        if self.state not in (RoomState.READY_CHECK,):
            raise RoomError("invalid_room_state", "room is not accepting ready state")
        seat = self._seat(player_index)
        seat.ready = bool(ready)
        self.last_active_at = float(now)
        if all(value and value.ready and value.connected for value in self.seats):
            self.session = AuthoritativeBattleSession(
                self.match_id,
                tuple(value.character_id for value in self.seats),
            )
            self.state = RoomState.RUNNING
            self.paused = False

    def submit_cast(self, player_index, intent, now):
        if self.state != RoomState.RUNNING or self.paused or self.session is None:
            raise RoomError("battle_not_running", "battle is not currently running")
        seat = self._seat(player_index)
        if intent.sequence <= seat.last_sequence:
            raise RoomError("duplicate_sequence", "cast sequence was already processed")
        seat.last_sequence = intent.sequence
        while seat.cast_times and now - seat.cast_times[0] >= 1.0:
            seat.cast_times.popleft()
        if len(seat.cast_times) >= self.max_casts_per_second:
            raise RoomError("rate_limited", "too many cast requests")
        seat.cast_times.append(float(now))
        self.last_active_at = float(now)
        accepted = self.session.cast(player_index, intent)
        return accepted, self.session.drain_events()

    def request_rematch(self, player_index, now):
        if self.state != RoomState.ROUND_OVER:
            raise RoomError("invalid_room_state", "rematch is only available after a round")
        seat = self._seat(player_index)
        seat.rematch_ready = True
        self.last_active_at = float(now)
        if all(value and value.rematch_ready and value.connected for value in self.seats):
            self.match_id = uuid.uuid4().hex
            self.session = AuthoritativeBattleSession(
                self.match_id,
                tuple(value.character_id for value in self.seats),
            )
            for value in self.seats:
                value.rematch_ready = False
            self.state = RoomState.RUNNING
            self.paused = False

    def step(self, dt):
        if self.state != RoomState.RUNNING or self.paused or self.session is None:
            return []
        events = self.session.step(dt)
        if self.session.engine.winner is not None:
            self.state = RoomState.ROUND_OVER
        return events

    def snapshot(self):
        return None if self.session is None else self.session.snapshot()

    def public_state(self):
        return {
            "room_code": self.room_code,
            "match_id": self.match_id,
            "state": self.state.value,
            "paused": self.paused,
            "players": [
                None
                if seat is None
                else {
                    "player_index": seat.player_index,
                    "character_id": seat.character_id,
                    "ready": seat.ready,
                    "connected": seat.connected,
                    "rematch_ready": seat.rematch_ready,
                }
                for seat in self.seats
            ],
        }

    def reconnect_expired(self, now):
        return any(
            seat
            and not seat.connected
            and seat.disconnected_at is not None
            and now - seat.disconnected_at > self.reconnect_timeout
            for seat in self.seats
        )

    def _seat(self, player_index):
        if player_index not in (0, 1) or self.seats[player_index] is None:
            raise RoomError("invalid_seat", "player seat is not occupied")
        return self.seats[player_index]
