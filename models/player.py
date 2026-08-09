from dataclasses import dataclass, field

import numpy as np

from config import HEIGHT, MAX_HP, MAX_MANA, SPELLS, WIDTH
from game.characters import DEFAULT_CHARACTER_IDS, get_character


@dataclass
class Player:
    pid: int
    name: str
    side: str
    character_id: str = DEFAULT_CHARACTER_IDS[0]
    max_hp: float = MAX_HP
    hp: float = MAX_HP
    mana: float = MAX_MANA
    global_cooldown_until: float = 0.0
    spell_cooldown_until: dict = field(
        default_factory=lambda: {name: 0.0 for name in SPELLS}
    )
    shield_value: float = 0.0
    shield_until: float = 0.0
    silenced_until: float = 0.0
    frozen_until: float = 0.0
    healing_until: float = 0.0
    pending_heal: float = 0.0
    mana_regen_boost_until: float = 0.0
    buff_disabled_until: float = 0.0
    last_spell: str = "-"
    last_message: str = ""
    message_until: float = 0.0
    visual_state: str = "normal"
    visual_state_until: float = 0.0

    def __post_init__(self):
        self.apply_character(self.character_id, reset_hp=True)

    @property
    def profile(self):
        return get_character(self.character_id)

    @property
    def display_name(self):
        return self.profile.name

    @property
    def damage_mult(self):
        return self.profile.damage_mult

    def damage_mult_at(self, now):
        return 1.0 if self.buffs_disabled(now) else self.profile.damage_mult

    @property
    def spell_cooldown_mult(self):
        return self.profile.spell_cooldown_mult

    def spell_cooldown_mult_at(self, now):
        return 1.0 if self.buffs_disabled(now) else self.profile.spell_cooldown_mult

    @property
    def global_cooldown_mult(self):
        return self.profile.global_cooldown_mult

    def global_cooldown_mult_at(self, now):
        return 1.0 if self.buffs_disabled(now) else self.profile.global_cooldown_mult

    @property
    def uncounterable_spells(self):
        return self.profile.uncounterable_spells

    def uncounterable_spells_at(self, now):
        return False if self.buffs_disabled(now) else self.profile.uncounterable_spells

    def buffs_disabled(self, now):
        return now < self.buff_disabled_until

    def effective_max_hp(self, now):
        return MAX_HP if self.buffs_disabled(now) else self.max_hp

    def apply_character(self, character_id, reset_hp=False):
        profile = get_character(character_id)
        self.character_id = profile.id
        self.max_hp = round(MAX_HP * profile.max_hp_mult, 2)
        if reset_hp:
            self.hp = self.max_hp
        else:
            self.hp = min(self.hp, self.max_hp)

    def set_visual_state(self, state, now, duration=0.45):
        if state in self.profile.poses:
            self.visual_state = state
            self.visual_state_until = now + duration

    def pose_key(self, now, winner=None):
        if winner is not None:
            return "win" if winner == self.pid else "lose"
        if not self.alive():
            return "lose"
        if now < self.visual_state_until:
            return self.visual_state
        return "normal"

    def center(self):
        if self.side == "left":
            return np.array([WIDTH * 0.23, HEIGHT * 0.55], dtype=np.float32)
        return np.array([WIDTH * 0.77, HEIGHT * 0.55], dtype=np.float32)

    def wand_pos(self):
        base = self.center()
        return base + np.array([70 if self.side == "left" else -70, -40], dtype=np.float32)

    def target_body_rect(self):
        c = self.center()
        return (
            int(c[0] - 85),
            int(c[1] - 130),
            int(c[0] + 85),
            int(c[1] + 120),
        )

    def alive(self):
        return self.hp > 0

    def has_shield(self, now):
        return self.shield_value > 0 and now < self.shield_until

    def is_healing(self, now):
        return self.pending_heal > 0 and now < self.healing_until
