from __future__ import annotations

from dataclasses import replace

from game.battle_engine import BattleEngine
from game.snapshots import snapshot_from_engine


class AuthoritativeBattleSession:
    def __init__(self, match_id, character_ids):
        self.match_id = str(match_id)
        self.engine = BattleEngine(character_ids=character_ids, start_time=0.0)
        self.server_tick = 0
        self.match_time = 0.0

    def cast(self, player_index, intent):
        accepted = self.engine.cast_spell(player_index, intent.spell, self.match_time)
        return accepted, self._drain_events(command_sequence=intent.sequence)

    def step(self, dt):
        self.server_tick += 1
        self.match_time += float(dt)
        self.engine.update(float(dt), self.match_time)
        return self._drain_events()

    def drain_events(self):
        return self._drain_events()

    def _drain_events(self, command_sequence=None):
        events = []
        for event in self.engine.drain_events():
            payload = dict(event.payload)
            if command_sequence is not None and event.kind in ("cast_accepted", "cast_rejected"):
                payload["sequence"] = int(command_sequence)
            events.append(
                replace(
                    event,
                    server_tick=self.server_tick,
                    match_id=self.match_id,
                    payload=payload,
                )
            )
        return events

    def snapshot(self):
        return snapshot_from_engine(
            self.engine,
            match_id=self.match_id,
            server_tick=self.server_tick,
            match_time=self.match_time,
        )
