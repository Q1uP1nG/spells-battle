from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class BattleEvent:
    """A deterministic fact emitted by the authoritative battle engine."""

    event_id: int
    kind: str
    match_time: float
    payload: Mapping[str, Any]
    server_tick: int = 0
    match_id: str = ""
