from __future__ import annotations

import numpy as np

from config import (
    GLOBAL_CAST_COOLDOWN,
    MANA_REGEN_PER_SEC,
    MAX_MANA,
    SPELLS,
    SPELL_CLASH_SOUNDS,
    SPELL_INTERACTIONS,
    WIDTH,
)
from game.characters import (
    DEFAULT_CHARACTER_IDS,
    cycle_character_avoiding,
    get_character,
    random_character,
)
from game.events import BattleEvent
from game.geometry import circle_hits_rect
from models.player import Player
from models.projectile import Projectile


def _point_tuple(point) -> tuple[float, float]:
    return float(point[0]), float(point[1])


def _color_tuple(color) -> tuple[int, int, int]:
    return int(color[0]), int(color[1]), int(color[2])


class BattleEngine:
    """Authoritative battle rules with no camera, renderer, audio, or wall clock.

    Callers inject ``now`` and ``dt``. The engine mutates only authoritative
    player/projectile state and emits structured events for presentation/network
    consumers.
    """

    def __init__(self, character_ids=None, start_time: float = 0.0, retain_events: bool = True):
        self._retain_events = bool(retain_events)
        self._next_event_id = 1
        self._next_projectile_id = 1
        self._events: list[BattleEvent] = []
        self._reset_authority(character_ids, start_time)

    def _reset_authority(self, character_ids=None, start_time: float = 0.0):
        character_ids = tuple(character_ids or DEFAULT_CHARACTER_IDS)
        if len(character_ids) < 2:
            character_ids = DEFAULT_CHARACTER_IDS
        self.players = [
            Player(0, "P1", "left", character_id=character_ids[0]),
            Player(1, "P2", "right", character_id=character_ids[1]),
        ]
        self.projectiles: list[Projectile] = []
        self.winner = None
        self.round_start = float(start_time)

    def reset(self, now: float = 0.0):
        character_ids = [player.character_id for player in self.players]
        self._events.clear()
        self._next_event_id = 1
        self._next_projectile_id = 1
        self._reset_authority(character_ids, now)
        self._emit("round_reset", now)

    def set_player_character(self, player_index, character_id):
        profile = get_character(character_id)
        self.players[player_index].apply_character(profile.id, reset_hp=True)
        return profile

    def cycle_player_character(self, player_index, direction):
        current = self.players[player_index].character_id
        avoid = self.players[1 - player_index].character_id
        return self.set_player_character(
            player_index, cycle_character_avoiding(current, avoid, direction)
        )

    def randomize_player_character(self, player_index, exclude_other=True):
        exclude = self.players[1 - player_index].character_id if exclude_other else None
        return self.set_player_character(player_index, random_character(exclude_id=exclude))

    def can_cast(self, player_index, spell_name, now):
        player = self.players[player_index]
        spell = SPELLS[spell_name]

        if self.winner is not None:
            return False, "ROUND OVER"
        if not player.alive():
            return False, "DEAD"
        if now < player.silenced_until:
            return False, "SILENCED"
        if now < player.spell_cooldown_until[spell_name]:
            return False, "SPELL CD"
        if now < player.global_cooldown_until:
            return False, "GLOBAL CD"
        if player.mana < spell["mana"]:
            return False, "NO MANA"
        return True, ""

    def cast_spell(self, player_index, spell_name, now):
        player = self.players[player_index]
        spell = SPELLS[spell_name]
        allowed, reason = self.can_cast(player_index, spell_name, now)
        if not allowed:
            self._emit(
                "cast_rejected",
                now,
                player_index=player_index,
                spell=spell_name,
                reason=reason,
            )
            return False

        if spell.get("consume_all_mana"):
            player.mana = 0.0
        else:
            player.mana -= spell["mana"]
        player.global_cooldown_until = now + GLOBAL_CAST_COOLDOWN * player.global_cooldown_mult_at(now)
        self_recovery = float(spell.get("self_recovery", 0.0) or 0.0)
        if self_recovery > 0:
            player.global_cooldown_until = max(player.global_cooldown_until, now + self_recovery)
        player.spell_cooldown_until[spell_name] = now + spell["cooldown"] * player.spell_cooldown_mult_at(now)

        position = player.center()
        if spell["kind"] == "projectile":
            position = player.wand_pos()
            direction = np.array([1.0, 0.0], dtype=np.float32)
            if player.side == "right":
                direction = np.array([-1.0, 0.0], dtype=np.float32)
            speed = spell["speed"] * (0.6 if now < player.frozen_until else 1.0)
            projectile = Projectile(
                owner=player_index,
                spell=spell_name,
                pos=position.copy(),
                vel=direction * speed,
                radius=spell["radius"],
                damage=spell["damage"] * player.damage_mult_at(now),
                color=spell["color"],
                projectile_id=self._next_projectile_id,
            )
            self._next_projectile_id += 1
            self.projectiles.append(projectile)
        elif spell["kind"] == "shield":
            player.shield_value = spell["shield_value"]
            player.shield_until = now + spell["duration"]
        elif spell["kind"] == "heal":
            player.healing_until = now + spell["channel"]
            player.pending_heal = spell["heal"]

        self._emit(
            "cast_accepted",
            now,
            player_index=player_index,
            spell=spell_name,
            spell_kind=spell["kind"],
            position=_point_tuple(position),
            color=_color_tuple(spell["color"]),
        )
        return True

    def update(self, dt, now):
        for player in self.players:
            if player.alive():
                regen_mult = 1.0
                if now < player.mana_regen_boost_until:
                    regen_mult = SPELLS["lumos"].get("mana_regen_mult", 1.0)
                player.mana = min(MAX_MANA, player.mana + MANA_REGEN_PER_SEC * regen_mult * dt)

            if player.pending_heal > 0 and now >= player.healing_until:
                heal_amount = player.pending_heal
                player.pending_heal = 0
                if player.alive():
                    player.hp = min(player.effective_max_hp(now), player.hp + heal_amount)
                    mana_regen_duration = SPELLS["lumos"].get("mana_regen_duration", 0.0)
                    if mana_regen_duration > 0:
                        player.mana_regen_boost_until = max(
                            player.mana_regen_boost_until,
                            now + mana_regen_duration,
                        )
                    self._emit(
                        "heal_completed",
                        now,
                        player_index=player.pid,
                        position=_point_tuple(player.center()),
                    )

            if now >= player.shield_until:
                player.shield_value = 0

        for projectile in self.projectiles:
            if not projectile.active:
                continue
            projectile.pos += projectile.vel * dt
            projectile.life -= dt
            if projectile.life <= 0 or projectile.pos[0] < -80 or projectile.pos[0] > WIDTH + 80:
                projectile.active = False

        self.resolve_projectile_collisions(now)
        self.resolve_hits(now)
        self.projectiles = [projectile for projectile in self.projectiles if projectile.active]

        for player in self.players:
            if player.hp <= 0 and self.winner is None:
                self.winner = 1 - player.pid
                self._emit(
                    "round_ended",
                    now,
                    winner=self.winner,
                    defeated_player=player.pid,
                    position=_point_tuple(player.center()),
                )

    def resolve_projectile_collisions(self, now):
        for index, first in enumerate(self.projectiles):
            if not first.active:
                continue
            for second in self.projectiles[index + 1 :]:
                if not second.active or first.owner == second.owner:
                    continue
                distance = np.linalg.norm(first.pos - second.pos)
                if distance <= first.radius + second.radius:
                    self._apply_interaction(first, second, now)

    def _apply_interaction(self, first, second, now):
        interaction = (
            SPELL_INTERACTIONS.get((first.spell, second.spell))
            or SPELL_INTERACTIONS.get((second.spell, first.spell))
        )
        midpoint = (first.pos + second.pos) / 2

        if interaction is None:
            first.active = False
            second.active = False
            if first.spell == second.spell and first.spell in SPELLS:
                color = SPELLS[first.spell]["color"]
            else:
                color = (170, 210, 255)
            self._emit(
                "spell_clashed",
                now,
                outcome="cancelled",
                position=_point_tuple(midpoint),
                color=_color_tuple(color),
                sound="clash_cancel",
            )
            return

        winner_spell, loser_damage_mult, loser_velocity_mult = interaction
        winner = first if first.spell == winner_spell else second
        loser = second if winner is first else first

        if self.players[loser.owner].uncounterable_spells_at(now):
            winner.active = False
            loser.radius *= 0.95
            color = SPELLS[loser.spell]["color"]
            self._emit(
                "spell_clashed",
                now,
                outcome="resisted",
                position=_point_tuple(midpoint),
                color=_color_tuple(color),
                sound="clash_cancel",
            )
            return

        loser.active = False
        winner.damage *= loser_damage_mult
        winner.vel *= loser_velocity_mult
        winner.radius *= 0.9
        clash_sound = (
            SPELL_CLASH_SOUNDS.get((first.spell, second.spell))
            or SPELL_CLASH_SOUNDS.get((second.spell, first.spell))
            or "clash_cancel"
        )
        self._emit(
            "spell_clashed",
            now,
            outcome="countered",
            winner_spell=winner_spell,
            position=_point_tuple(midpoint),
            color=_color_tuple(SPELLS[winner_spell]["color"]),
            sound=clash_sound,
        )

    def resolve_hits(self, now):
        for projectile in self.projectiles:
            if not projectile.active:
                continue
            target = self.players[1 - projectile.owner]
            if not target.alive():
                continue
            if target.has_shield(now) and self.projectile_touches_shield(projectile, target):
                self.apply_shield_hit(target, projectile, now)
                projectile.active = False
            elif circle_hits_rect(projectile.pos, projectile.radius, target.target_body_rect()):
                self.apply_player_hit(target, projectile, now)
                projectile.active = False

    def apply_shield_hit(self, target, projectile, now):
        if projectile.spell == "glacius":
            target.shield_value -= 20
            target.shield_until = max(now, target.shield_until - 1.5)
            burst_color = SPELLS["glacius"]["color"]
            burst_count, burst_speed = 42, 190
        elif projectile.spell == "stupefy":
            target.shield_value -= 20
            burst_color = SPELLS["stupefy"]["color"]
            burst_count, burst_speed = 36, 160
        else:
            target.shield_value -= projectile.damage
            burst_color = projectile.color
            burst_count, burst_speed = 36, 170

        shield_broken = target.shield_value <= 0
        if shield_broken:
            target.shield_value = 0
            target.shield_until = 0
        self._emit(
            "shield_hit",
            now,
            player_index=target.pid,
            spell=projectile.spell,
            position=_point_tuple(projectile.pos),
            color=_color_tuple(burst_color),
            burst_count=burst_count,
            burst_speed=burst_speed,
            shield_broken=shield_broken,
            player_position=_point_tuple(target.center()),
        )

    def apply_player_hit(self, target, projectile, now):
        damage = projectile.damage
        message = "HIT " + SPELLS[projectile.spell]["label"]
        if target.is_healing(now) and projectile.spell in ("incendio", "stupefy"):
            target.pending_heal = 0
            target.healing_until = 0
            if projectile.spell == "incendio":
                damage += 6
            message = "HEAL INTERRUPTED"

        target.hp = max(0.0, target.hp - damage)
        if projectile.spell == "stupefy":
            target.silenced_until = max(target.silenced_until, now + SPELLS["stupefy"]["silence"])
        elif projectile.spell == "glacius":
            target.frozen_until = max(target.frozen_until, now + SPELLS["glacius"]["frozen"])
            message = "CHILLED"
        elif projectile.spell == "overload":
            target.buff_disabled_until = max(
                target.buff_disabled_until,
                now + SPELLS["overload"]["buff_disable"],
            )
            message = "BUFF DISABLED"

        self._emit(
            "player_hit",
            now,
            player_index=target.pid,
            spell=projectile.spell,
            damage=float(damage),
            message=message,
            position=_point_tuple(projectile.pos),
            color=_color_tuple(projectile.color),
        )

    def projectile_touches_shield(self, projectile, target):
        center = target.center()
        shield_x = center[0] + (105 if target.side == "left" else -105)
        shield_center = np.array([shield_x, center[1] - 15], dtype=np.float32)
        return np.linalg.norm(projectile.pos - shield_center) < 115 + projectile.radius

    def events(self) -> tuple[BattleEvent, ...]:
        return tuple(self._events)

    def drain_events(self) -> list[BattleEvent]:
        events = list(self._events)
        self._events.clear()
        return events

    def _emit(self, kind: str, now: float, **payload):
        event = BattleEvent(
            event_id=self._next_event_id,
            kind=kind,
            match_time=float(now),
            payload=payload,
        )
        self._next_event_id += 1
        if self._retain_events:
            self._events.append(event)
        self._on_event(event)

    def _on_event(self, event: BattleEvent):
        pass
