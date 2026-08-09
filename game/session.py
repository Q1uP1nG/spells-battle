from __future__ import annotations

from typing import Protocol, runtime_checkable

from game.commands import CastIntent, CastSubmission


@runtime_checkable
class BattleSession(Protocol):
    """Write boundary shared by local play and future remote play."""

    game: object

    def request_cast(
        self,
        player_index: int,
        spell: str,
        now: float,
        source: str,
    ) -> CastSubmission:
        ...

    def submit_cast(
        self,
        player_index: int,
        intent: CastIntent,
        now: float,
    ) -> CastSubmission:
        ...


class LocalBattleSession:
    """Adapter that executes commands against the existing local BattleGame."""

    def __init__(self, game):
        self.game = game
        self._next_sequence_by_player: dict[int, int] = {}

    def request_cast(
        self,
        player_index: int,
        spell: str,
        now: float,
        source: str,
    ) -> CastSubmission:
        intent = CastIntent(
            spell=spell,
            sequence=self._next_sequence(player_index),
            client_time_ms=max(0, int(round(float(now) * 1000.0))),
            source=source,
        )
        return self.submit_cast(player_index, intent, now)

    def submit_cast(
        self,
        player_index: int,
        intent: CastIntent,
        now: float,
    ) -> CastSubmission:
        accepted = bool(self.game.cast_spell(player_index, intent.spell, now))
        reason = ""
        if not accepted:
            players = getattr(self.game, "players", ())
            if 0 <= player_index < len(players):
                reason = str(getattr(players[player_index], "last_message", "") or "")
        return CastSubmission(intent=intent, accepted=accepted, reason=reason)

    def _next_sequence(self, player_index: int) -> int:
        if not isinstance(player_index, int) or isinstance(player_index, bool) or player_index < 0:
            raise ValueError("player_index must be a non-negative integer")
        sequence = self._next_sequence_by_player.get(player_index, 0) + 1
        self._next_sequence_by_player[player_index] = sequence
        return sequence
