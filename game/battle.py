import math
import random
import time

import numpy as np

from config import (
    GLOBAL_CAST_COOLDOWN,
    HEIGHT,
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
from game.geometry import circle_hits_rect
from models.particle import Particle
from models.player import Player
from models.projectile import Projectile


class BattleGame:
    def __init__(self, character_ids=None):
        character_ids = tuple(character_ids or DEFAULT_CHARACTER_IDS)
        if len(character_ids) < 2:
            character_ids = DEFAULT_CHARACTER_IDS
        self.players = [
            Player(0, "P1", "left", character_id=character_ids[0]),
            Player(1, "P2", "right", character_id=character_ids[1]),
        ]
        self.projectiles = []
        self.particles = []
        self.flash_messages = []
        self.shockwaves = []
        self.sound_events = []
        self.screen_shake_until = 0.0
        self.screen_shake_intensity = 0.0
        self.hit_flash_until = 0.0
        self.hit_flash_intensity = 0.0
        self.winner = None
        self.solo_dummy_defeated = False
        self.round_start = time.monotonic()

    def reset(self):
        character_ids = [player.character_id for player in self.players]
        self.__init__(character_ids=character_ids)

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
        profile = get_character(random_character(exclude_id=exclude))
        return self.set_player_character(player_index, profile.id)

    def can_cast(self, player_index, spell_name, now):
        """Check if a player can cast a spell. Returns (allowed, reason)."""
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
            player.last_message = reason
            player.message_until = now + 0.6
            self.sound_events.append(("cast_fail",))
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
        player.last_spell = spell["full"]
        player.last_message = "CAST " + spell["label"]
        player.message_until = now + 0.9
        player.set_visual_state("casting", now, 0.5)

        if spell["kind"] == "projectile":
            start = player.wand_pos()
            direction = np.array([1.0, 0.0], dtype=np.float32)
            if player.side == "right":
                direction = np.array([-1.0, 0.0], dtype=np.float32)
            if now < player.frozen_until:
                speed = spell["speed"] * 0.6
            else:
                speed = spell["speed"]
            proj = Projectile(
                owner=player_index,
                spell=spell_name,
                pos=start.copy(),
                vel=direction * speed,
                radius=spell["radius"],
                damage=spell["damage"] * player.damage_mult_at(now),
                color=spell["color"],
            )
            self.projectiles.append(proj)
            self.spawn_burst(start, spell["color"], 18, 90)
            self.sound_events.append(("cast", spell_name))

        elif spell["kind"] == "shield":
            player.shield_value = spell["shield_value"]
            player.shield_until = now + spell["duration"]
            self.spawn_burst(player.center(), spell["color"], 26, 120)
            self.sound_events.append(("cast", "protego"))

        elif spell["kind"] == "heal":
            player.healing_until = now + spell["channel"]
            player.pending_heal = spell["heal"]
            self.spawn_burst(player.center(), spell["color"], 30, 80)
            self.sound_events.append(("cast", "lumos"))

        return True

    def update(self, dt, now):
        for player in self.players:
            if player.alive():
                regen_mult = 1.0
                if now < player.mana_regen_boost_until:
                    regen_mult = SPELLS["lumos"].get("mana_regen_mult", 1.0)
                player.mana = min(MAX_MANA, player.mana + MANA_REGEN_PER_SEC * regen_mult * dt)

            if player.pending_heal > 0 and now >= player.healing_until:
                player.hp = min(player.effective_max_hp(now), player.hp + player.pending_heal)
                player.pending_heal = 0
                mana_regen_duration = SPELLS["lumos"].get("mana_regen_duration", 0.0)
                if mana_regen_duration > 0:
                    player.mana_regen_boost_until = max(
                        player.mana_regen_boost_until,
                        now + mana_regen_duration,
                    )
                player.last_message = "HEALED + MANA"
                player.message_until = now + 0.8
                self.spawn_burst(player.center(), SPELLS["lumos"]["color"], 45, 150)
                self.sound_events.append(("heal_complete",))
            elif player.is_healing(now):
                self.spawn_lumos_channel(player, now)

            if now >= player.shield_until:
                player.shield_value = 0

        for proj in self.projectiles:
            if not proj.active:
                continue
            proj.pos += proj.vel * dt
            proj.life -= dt
            if proj.life <= 0 or proj.pos[0] < -80 or proj.pos[0] > WIDTH + 80:
                proj.active = False
                continue

            self.spawn_trail(proj)

        self.resolve_projectile_collisions(now)
        self.resolve_hits(now)
        self.projectiles = [p for p in self.projectiles if p.active]

        for particle in self.particles:
            particle.pos += particle.vel * dt
            particle.vel *= 0.96
            particle.life -= dt
        self.particles = [p for p in self.particles if p.life > 0]
        self.flash_messages = [m for m in self.flash_messages if now < m["until"]]
        self.shockwaves = [
            w for w in self.shockwaves
            if now < w["created_at"] + w.get("duration", 0.45)
        ]

        for player in self.players:
            if player.hp <= 0 and self.winner is None:
                self.winner = 1 - player.pid
                self.spawn_burst(player.center(), (255, 255, 255), 80, 260)
                self.sound_events.append(("round_over",))

    def resolve_projectile_collisions(self, now):
        for i, a in enumerate(self.projectiles):
            if not a.active:
                continue
            for b in self.projectiles[i + 1 :]:
                if not b.active or a.owner == b.owner:
                    continue
                dist = np.linalg.norm(a.pos - b.pos)
                if dist > a.radius + b.radius:
                    continue
                self._apply_interaction(a, b, now=now)

    def _apply_interaction(self, a, b, now=None):
        if now is None:
            now = time.monotonic()
        interaction = SPELL_INTERACTIONS.get((a.spell, b.spell)) \
                   or SPELL_INTERACTIONS.get((b.spell, a.spell))
        mid = (a.pos + b.pos) / 2

        if interaction is None:
            # Same spell or unlisted combination: both destroyed
            a.active = False
            b.active = False
            if a.spell == b.spell and a.spell in SPELLS:
                color = SPELLS[a.spell]["color"]
            else:
                color = (170, 210, 255)
            self.spawn_burst(mid, color, 55, 210)
            self.add_flash_message("CLASH", mid, color, now, duration=0.7)
            self.add_shockwave(mid, color, now, max_radius=120, thickness=6)
            self.register_screen_feedback(now, shake=4.5, flash=0.14, duration=0.12)
            self.sound_events.append(("clash", "clash_cancel"))
            return

        winner_spell, loser_dmg_mult, loser_vel_mult = interaction
        winner = a if a.spell == winner_spell else b
        loser = b if winner is a else a

        if self.players[loser.owner].uncounterable_spells_at(now):
            survivor = loser
            removed = winner
            removed.active = False
            survivor.radius *= 0.95
            self.spawn_burst(mid, SPELLS[survivor.spell]["color"], 42, 190)
            self.add_flash_message("RESISTED", mid, SPELLS[survivor.spell]["color"], now, duration=0.8)
            self.add_shockwave(mid, SPELLS[survivor.spell]["color"], now, max_radius=110, thickness=5)
            self.register_screen_feedback(now, shake=4.0, flash=0.13, duration=0.12)
            self.sound_events.append(("clash", "clash_cancel"))
            return

        loser.active = False
        winner.damage *= loser_dmg_mult
        winner.vel *= loser_vel_mult
        winner.radius *= 0.9
        self.spawn_burst(mid, SPELLS[winner_spell]["color"], 42, 190)
        self.add_flash_message("COUNTERED!", mid, SPELLS[winner_spell]["color"], now, duration=0.9)
        self.add_shockwave(mid, SPELLS[winner_spell]["color"], now, max_radius=145, thickness=7)
        self.register_screen_feedback(now, shake=6.0, flash=0.18, duration=0.14)
        clash_sound = (
            SPELL_CLASH_SOUNDS.get((a.spell, b.spell))
            or SPELL_CLASH_SOUNDS.get((b.spell, a.spell))
            or "clash_cancel"
        )
        self.sound_events.append(("clash", clash_sound))

    def resolve_hits(self, now):
        for proj in self.projectiles:
            if not proj.active:
                continue
            target = self.players[1 - proj.owner]
            if not target.alive():
                continue

            if target.has_shield(now) and self.projectile_touches_shield(proj, target):
                self.apply_shield_hit(target, proj, now)
                proj.active = False
                continue

            if circle_hits_rect(proj.pos, proj.radius, target.target_body_rect()):
                self.apply_player_hit(target, proj, now)
                proj.active = False

    def apply_shield_hit(self, target, proj, now):
        if proj.spell == "glacius":
            target.shield_value -= 20
            target.shield_until = max(now, target.shield_until - 1.5)
            self.spawn_burst(proj.pos, SPELLS["glacius"]["color"], 42, 190)
        elif proj.spell == "stupefy":
            target.shield_value -= 20
            self.spawn_burst(proj.pos, SPELLS["stupefy"]["color"], 36, 160)
        else:
            target.shield_value -= proj.damage
            self.spawn_burst(proj.pos, proj.color, 36, 170)

        target.last_message = "SHIELD HIT"
        target.message_until = now + 0.7
        self.register_screen_feedback(now, shake=3.5, flash=0.12, duration=0.12)
        self.sound_events.append(("shield_hit",))
        if target.shield_value <= 0:
            target.shield_value = 0
            target.shield_until = 0
            self.spawn_burst(target.center(), (255, 255, 255), 45, 220)

    def apply_player_hit(self, target, proj, now):
        target.set_visual_state("hit", now, 0.55)
        damage = proj.damage
        if target.is_healing(now) and proj.spell in ("incendio", "stupefy"):
            target.pending_heal = 0
            target.healing_until = 0
            if proj.spell == "incendio":
                damage += 6
            target.last_message = "HEAL INTERRUPTED"
        else:
            target.last_message = "HIT " + SPELLS[proj.spell]["label"]

        target.hp = max(0.0, target.hp - damage)
        target.message_until = now + 0.9

        if proj.spell == "stupefy":
            target.silenced_until = max(target.silenced_until, now + SPELLS["stupefy"]["silence"])
        elif proj.spell == "glacius":
            target.frozen_until = max(target.frozen_until, now + SPELLS["glacius"]["frozen"])
            target.last_message = "CHILLED"
        elif proj.spell == "overload":
            target.buff_disabled_until = max(
                target.buff_disabled_until,
                now + SPELLS["overload"]["buff_disable"],
            )
            target.last_message = "BUFF DISABLED"

        self.spawn_burst(proj.pos, proj.color, 55, 240)
        self.register_screen_feedback(now, shake=9.0, flash=0.28, duration=0.18)
        self.sound_events.append(("hit",))

    def projectile_touches_shield(self, proj, target):
        center = target.center()
        shield_x = center[0] + (105 if target.side == "left" else -105)
        shield_center = np.array([shield_x, center[1] - 15], dtype=np.float32)
        return np.linalg.norm(proj.pos - shield_center) < 115 + proj.radius

    def spawn_trail(self, proj):
        color = proj.color
        for _ in range(2):
            jitter = np.array(
                [random.uniform(-8, 8), random.uniform(-8, 8)], dtype=np.float32
            )
            vel = -proj.vel * 0.06 + np.array(
                [random.uniform(-35, 35), random.uniform(-35, 35)], dtype=np.float32
            )
            self.particles.append(
                Particle(
                    pos=proj.pos + jitter,
                    vel=vel,
                    color=color,
                    radius=random.uniform(2, 6),
                    life=random.uniform(0.25, 0.55),
                    max_life=0.55,
                )
            )

    def add_shockwave(self, pos, color, now, max_radius=130, duration=0.45, thickness=6):
        self.shockwaves.append(
            {
                "pos": np.array(pos, dtype=np.float32),
                "color": color,
                "created_at": now,
                "duration": duration,
                "max_radius": max_radius,
                "thickness": thickness,
            }
        )

    def add_flash_message(self, text, pos, color, now, duration=0.8):
        self.flash_messages.append(
            {
                "text": text,
                "pos": np.array(pos, dtype=np.float32),
                "color": color,
                "created_at": now,
                "until": now + duration,
                "duration": duration,
            }
        )

    def register_screen_feedback(self, now, shake=8.0, flash=0.30, duration=0.18):
        self.screen_shake_until = max(self.screen_shake_until, now + duration)
        self.screen_shake_intensity = max(self.screen_shake_intensity, shake)
        self.hit_flash_until = max(self.hit_flash_until, now + duration)
        self.hit_flash_intensity = max(self.hit_flash_intensity, flash)

    def spawn_lumos_channel(self, player, now):
        center = player.center()
        for _ in range(3):
            ang = random.uniform(0, math.tau)
            radius = random.uniform(50, 105)
            pos = center + np.array(
                [math.cos(ang) * radius, math.sin(ang) * radius],
                dtype=np.float32,
            )
            outward = pos - center
            norm = max(np.linalg.norm(outward), 1)
            vel = outward / norm * random.uniform(18, 55)
            self.particles.append(
                Particle(
                    pos=pos,
                    vel=vel,
                    color=SPELLS["lumos"]["color"],
                    radius=random.uniform(2, 7),
                    life=random.uniform(0.35, 0.75),
                    max_life=0.75,
                )
            )

    def spawn_burst(self, pos, color, count, speed):
        for _ in range(count):
            ang = random.uniform(0, math.tau)
            mag = random.uniform(speed * 0.25, speed)
            vel = np.array([math.cos(ang) * mag, math.sin(ang) * mag], dtype=np.float32)
            self.particles.append(
                Particle(
                    pos=np.array(pos, dtype=np.float32),
                    vel=vel,
                    color=color,
                    radius=random.uniform(2, 8),
                    life=random.uniform(0.35, 0.9),
                    max_life=0.9,
                )
            )
