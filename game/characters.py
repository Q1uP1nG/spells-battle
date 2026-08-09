from __future__ import annotations

import random
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class CharacterProfile:
    id: str
    name: str
    buff_label: str
    max_hp_mult: float = 1.0
    damage_mult: float = 1.0
    spell_cooldown_mult: float = 1.0
    global_cooldown_mult: float = 1.0
    uncounterable_spells: bool = False
    color: tuple = (210, 210, 220)
    poses: dict | None = None

    def __post_init__(self):
        poses = self.poses
        if poses is None:
            poses = {
                "normal": "READY",
                "casting": "CAST",
                "hit": "HIT",
                "win": "WIN",
                "lose": "LOSE",
            }
        object.__setattr__(self, "poses", MappingProxyType(dict(poses)))


CHARACTER_ORDER = ("harry", "hermione", "ron", "snape")
DEFAULT_CHARACTER_IDS = ("harry", "snape")

CHARACTERS = {
    "harry": CharacterProfile(
        id="harry",
        name="Harry",
        buff_label="+15% damage",
        damage_mult=1.15,
        color=(80, 115, 245),
        poses={
            "normal": "FOCUSED",
            "casting": "BOLD CAST",
            "hit": "STAGGER",
            "win": "VICTORY",
            "lose": "DOWN",
        },
    ),
    "hermione": CharacterProfile(
        id="hermione",
        name="Hermione",
        buff_label="faster cooldowns",
        spell_cooldown_mult=0.85,
        global_cooldown_mult=0.90,
        color=(190, 115, 230),
        poses={
            "normal": "PRECISE",
            "casting": "QUICK CAST",
            "hit": "BRACE",
            "win": "COMPOSED WIN",
            "lose": "FALL BACK",
        },
    ),
    "ron": CharacterProfile(
        id="ron",
        name="Ron",
        buff_label="+20% HP",
        max_hp_mult=1.20,
        color=(65, 135, 225),
        poses={
            "normal": "STEADY",
            "casting": "BRAVE CAST",
            "hit": "SHAKEN",
            "win": "CHEER",
            "lose": "SLUMP",
        },
    ),
    "snape": CharacterProfile(
        id="snape",
        name="Snape",
        buff_label="spells resist counters",
        uncounterable_spells=True,
        color=(155, 145, 130),
        poses={
            "normal": "SEVERE",
            "casting": "CUTTING CAST",
            "hit": "GLARE",
            "win": "COLD WIN",
            "lose": "WITHDRAW",
        },
    ),
}


def get_character(character_id):
    return CHARACTERS.get(character_id, CHARACTERS[DEFAULT_CHARACTER_IDS[0]])


def cycle_character(character_id, direction):
    current = character_id if character_id in CHARACTER_ORDER else DEFAULT_CHARACTER_IDS[0]
    index = CHARACTER_ORDER.index(current)
    return CHARACTER_ORDER[(index + direction) % len(CHARACTER_ORDER)]


def cycle_character_avoiding(current_id, avoid_id, direction):
    """Return the next character in the requested direction, skipping the avoided one.

    With two or more characters in the roster there is always a valid candidate.
    """
    current = current_id if current_id in CHARACTER_ORDER else DEFAULT_CHARACTER_IDS[0]
    index = CHARACTER_ORDER.index(current)
    for offset in range(1, len(CHARACTER_ORDER) + 1):
        candidate = CHARACTER_ORDER[(index + direction * offset) % len(CHARACTER_ORDER)]
        if candidate != avoid_id:
            return candidate
    # Fallback only possible when the roster has a single character.
    return current_id


def random_character(exclude_id=None):
    """Return a random character id, optionally excluding one."""
    choices = [cid for cid in CHARACTER_ORDER if cid != exclude_id]
    if not choices:
        return CHARACTER_ORDER[0]
    return random.choice(choices)
