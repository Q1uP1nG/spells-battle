from __future__ import annotations

from dataclasses import replace
from enum import Enum
import os

import numpy as np

from game.battle import BattleGame
from game.commands import CastIntent, CastSubmission
from models.projectile import Projectile
from network.client import NetworkClient
from network.clock import SnapshotInterpolator
from network.protocol import (
    cast_intent_to_payload,
    event_from_payload,
    snapshot_from_payload,
)


DEFAULT_SERVER_URL = os.getenv("SPELLS_SERVER_URL", "ws://127.0.0.1:8765")


class RemoteSessionState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    WAITING = "WAITING"
    READY = "READY"
    RUNNING = "RUNNING"
    RECONNECTING = "RECONNECTING"
    ROUND_OVER = "ROUND_OVER"


class RemoteBattleSession:
    def __init__(self, server_url=DEFAULT_SERVER_URL, network_client=None):
        self.game = BattleGame(start_time=0.0)
        self.client = network_client or NetworkClient(server_url)
        self.state = RemoteSessionState.DISCONNECTED
        self.player_index = None
        self.room_code = ""
        self.match_id = ""
        self.reconnect_token = ""
        self.status_message = "DISCONNECTED"
        self.last_error = ""
        self._next_sequence_value = 1
        self._requested_action = None
        self.interpolator = SnapshotInterpolator()

    def start(self):
        self.state = RemoteSessionState.CONNECTING
        self.client.start()

    def create_room(self):
        self._requested_action = ("create_room", {})
        self.client.send("create_room", {})

    def join_room(self, room_code):
        code = str(room_code).strip().upper()
        if not code:
            raise ValueError("room code must not be empty")
        self._requested_action = ("join_room", {"room_code": code})
        self.client.send("join_room", {"room_code": code})

    def select_character(self, character_id):
        self.client.send("select_character", {"character_id": character_id})

    def set_ready(self, ready=True):
        self.client.send("ready", {"ready": bool(ready)})

    def request_rematch(self):
        self.client.send("rematch", {})

    def request_cast(self, player_index, spell, now, source):
        intent = CastIntent(
            spell=spell,
            sequence=self._next_sequence_value,
            client_time_ms=max(0, int(round(float(now) * 1000.0))),
            source=source,
        )
        self._next_sequence_value += 1
        return self.submit_cast(player_index, intent, now)

    def submit_cast(self, player_index, intent, now):
        if self.state != RemoteSessionState.RUNNING or self.player_index is None:
            return CastSubmission(intent, False, "NOT CONNECTED")
        self.client.send("cast", cast_intent_to_payload(intent))
        self.game.players[self.player_index].last_message = "AWAITING SERVER"
        self.game.players[self.player_index].message_until = now + 0.8
        return CastSubmission(intent, None, "")

    def update(self, now, dt):
        for message in self.client.drain():
            self._handle_message(message, now)
        for projectile in self.game.projectiles:
            position = self.interpolator.projectile_positions(now).get(projectile.projectile_id)
            if position is not None:
                projectile.pos[:] = position
                self.game.spawn_trail(projectile)
        for player in self.game.players:
            if player.is_healing(now):
                self.game.spawn_lumos_channel(player, now)
        self.game.update_presentation(dt, now)

    def close(self):
        self.client.close()
        self.state = RemoteSessionState.DISCONNECTED

    def _handle_message(self, message, now):
        message_type = message["type"]
        payload = message["payload"]
        if message_type == "transport_state":
            transport_state = payload["state"]
            if transport_state == "CONNECTING":
                self.state = RemoteSessionState.CONNECTING
            elif transport_state == "RECONNECTING":
                self.state = RemoteSessionState.RECONNECTING
            elif transport_state == "CONNECTED" and self.reconnect_token and self.room_code:
                self.client.send(
                    "reconnect",
                    {
                        "room_code": self.room_code,
                        "reconnect_token": self.reconnect_token,
                    },
                )
            elif transport_state == "CONNECTED":
                self.status_message = "CONNECTED"
            return
        if message_type == "transport_error":
            self.last_error = payload.get("message", "network error")
            return
        if message_type in ("room_created", "room_joined"):
            self.room_code = payload["room_code"]
            self.match_id = payload["match_id"]
            self.player_index = payload["player_index"]
            if "reconnect_token" in payload:
                self.reconnect_token = payload["reconnect_token"]
            self.state = RemoteSessionState.WAITING
            self.status_message = f"ROOM {self.room_code} - P{self.player_index + 1}"
            return
        if message_type == "room_state":
            self._apply_room_state(payload)
            return
        if message_type == "battle_snapshot":
            snapshot = snapshot_from_payload(payload)
            if self.interpolator.push(snapshot, now):
                self._apply_snapshot(snapshot, now)
            return
        if message_type == "battle_event":
            event = replace(event_from_payload(payload), match_time=float(now))
            self.game._on_event(event)
            return
        if message_type == "error":
            self.last_error = payload.get("message", "server rejected request")
            self.status_message = payload.get("code", "ERROR").upper()

    def _apply_room_state(self, payload):
        state = payload["state"]
        self.room_code = payload["room_code"]
        incoming_match_id = payload["match_id"]
        if self.match_id and incoming_match_id != self.match_id:
            self.interpolator = SnapshotInterpolator()
        self.match_id = incoming_match_id
        for player_value in payload.get("players", []):
            if player_value is not None:
                index = player_value["player_index"]
                character_id = player_value["character_id"]
                if self.game.players[index].character_id != character_id:
                    self.game.set_player_character(index, character_id)
        if state == "RUNNING":
            self.state = RemoteSessionState.RECONNECTING if payload.get("paused") else RemoteSessionState.RUNNING
        elif state == "ROUND_OVER":
            self.state = RemoteSessionState.ROUND_OVER
        elif self.player_index is not None:
            own = payload.get("players", [None, None])[self.player_index]
            self.state = RemoteSessionState.READY if own and own.get("ready") else RemoteSessionState.WAITING
        self.status_message = f"{state}{' - PAUSED' if payload.get('paused') else ''}"

    def _apply_snapshot(self, snapshot, now):
        for value in snapshot.players:
            player = self.game.players[value.player_index]
            if player.character_id != value.character_id:
                self.game.set_player_character(value.player_index, value.character_id)
            player.hp = value.hp
            player.max_hp = value.max_hp
            player.mana = value.mana
            player.global_cooldown_until = now + value.global_cooldown_remaining
            player.spell_cooldown_until = {
                name: now + remaining for name, remaining in value.spell_cooldown_remaining
            }
            player.shield_value = value.shield_value
            player.shield_until = now + value.shield_remaining
            player.silenced_until = now + value.silence_remaining
            player.frozen_until = now + value.frozen_remaining
            player.healing_until = now + value.healing_remaining
            player.pending_heal = value.pending_heal
            player.mana_regen_boost_until = now + value.mana_regen_boost_remaining
            player.buff_disabled_until = now + value.buff_disabled_remaining
        existing = {projectile.projectile_id: projectile for projectile in self.game.projectiles}
        projectiles = []
        for value in snapshot.projectiles:
            projectile = existing.get(value.projectile_id)
            if projectile is None:
                projectile = Projectile(
                    owner=value.owner,
                    spell=value.spell,
                    pos=np.array([value.x, value.y], dtype=np.float32),
                    vel=np.array([value.vx, value.vy], dtype=np.float32),
                    radius=value.radius,
                    damage=value.damage,
                    color=value.color,
                    projectile_id=value.projectile_id,
                )
            projectile.life = value.life_remaining
            projectile.active = True
            projectiles.append(projectile)
        self.game.projectiles = projectiles
        self.game.winner = snapshot.winner
