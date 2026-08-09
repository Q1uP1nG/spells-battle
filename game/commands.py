from __future__ import annotations

from dataclasses import dataclass


CAST_SOURCES = frozenset({"cv", "keyboard"})


@dataclass(frozen=True)
class CastIntent:
    """Transport-neutral request to cast one spell.

    Player identity is deliberately not part of the payload. A local session
    receives it out of band; a remote server will derive it from the room seat
    bound to the connection instead of trusting client input.
    """

    spell: str
    sequence: int
    client_time_ms: int
    source: str

    def __post_init__(self):
        if not isinstance(self.spell, str) or not self.spell:
            raise ValueError("spell must be a non-empty string")
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValueError("sequence must be a positive integer")
        if (
            not isinstance(self.client_time_ms, int)
            or isinstance(self.client_time_ms, bool)
            or self.client_time_ms < 0
        ):
            raise ValueError("client_time_ms must be a non-negative integer")
        if self.source not in CAST_SOURCES:
            raise ValueError(f"unsupported cast source: {self.source!r}")


@dataclass(frozen=True)
class CastSubmission:
    """Acknowledgement returned by a battle session.

    Local sessions resolve synchronously. A future remote session may return
    ``accepted=None`` until the authoritative server confirms the command.
    """

    intent: CastIntent
    accepted: bool | None
    reason: str = ""

    @property
    def pending(self) -> bool:
        return self.accepted is None
