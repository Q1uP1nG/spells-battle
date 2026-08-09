import math
import random

import numpy as np

from config import SPELLS
from game.battle_engine import BattleEngine
from models.particle import Particle


class BattleGame(BattleEngine):
    """Local presentation adapter around the authoritative battle engine."""

    def __init__(self, character_ids=None, start_time=0.0):
        self._reset_presentation()
        super().__init__(character_ids=character_ids, start_time=start_time, retain_events=False)

    def _reset_presentation(self):
        self.particles = []
        self.flash_messages = []
        self.shockwaves = []
        self.sound_events = []
        self.screen_shake_until = 0.0
        self.screen_shake_intensity = 0.0
        self.hit_flash_until = 0.0
        self.hit_flash_intensity = 0.0
        self.solo_dummy_defeated = False

    def reset(self, now=0.0):
        character_ids = [player.character_id for player in self.players]
        self._reset_presentation()
        BattleEngine.__init__(
            self,
            character_ids=character_ids,
            start_time=now,
            retain_events=False,
        )

    def update(self, dt, now):
        super().update(dt, now)

        for player in self.players:
            if player.is_healing(now):
                self.spawn_lumos_channel(player, now)
        for projectile in self.projectiles:
            if projectile.active:
                self.spawn_trail(projectile)

        for particle in self.particles:
            particle.pos += particle.vel * dt
            particle.vel *= 0.96
            particle.life -= dt
        self.particles = [particle for particle in self.particles if particle.life > 0]
        self.flash_messages = [message for message in self.flash_messages if now < message["until"]]
        self.shockwaves = [
            wave
            for wave in self.shockwaves
            if now < wave["created_at"] + wave.get("duration", 0.45)
        ]

    def _apply_interaction(self, first, second, now=None):
        return super()._apply_interaction(first, second, 0.0 if now is None else now)

    def _on_event(self, event):
        payload = event.payload
        now = event.match_time

        if event.kind == "cast_rejected":
            player = self.players[payload["player_index"]]
            player.last_message = payload["reason"]
            player.message_until = now + 0.6
            self.sound_events.append(("cast_fail",))
            return

        if event.kind == "cast_accepted":
            player = self.players[payload["player_index"]]
            spell_name = payload["spell"]
            spell = SPELLS[spell_name]
            player.last_spell = spell["full"]
            player.last_message = "CAST " + spell["label"]
            player.message_until = now + 0.9
            player.set_visual_state("casting", now, 0.5)
            if payload["spell_kind"] == "projectile":
                self.spawn_burst(payload["position"], payload["color"], 18, 90)
                self.sound_events.append(("cast", spell_name))
            elif payload["spell_kind"] == "shield":
                self.spawn_burst(payload["position"], payload["color"], 26, 120)
                self.sound_events.append(("cast", "protego"))
            elif payload["spell_kind"] == "heal":
                self.spawn_burst(payload["position"], payload["color"], 30, 80)
                self.sound_events.append(("cast", "lumos"))
            return

        if event.kind == "heal_completed":
            player = self.players[payload["player_index"]]
            player.last_message = "HEALED + MANA"
            player.message_until = now + 0.8
            self.spawn_burst(payload["position"], SPELLS["lumos"]["color"], 45, 150)
            self.sound_events.append(("heal_complete",))
            return

        if event.kind == "spell_clashed":
            outcome = payload["outcome"]
            effects = {
                "cancelled": ("CLASH", 55, 210, 120, 6, 4.5, 0.14, 0.12, 0.7),
                "resisted": ("RESISTED", 42, 190, 110, 5, 4.0, 0.13, 0.12, 0.8),
                "countered": ("COUNTERED!", 42, 190, 145, 7, 6.0, 0.18, 0.14, 0.9),
            }
            text, count, speed, radius, thickness, shake, flash, duration, text_duration = effects[
                outcome
            ]
            self.spawn_burst(payload["position"], payload["color"], count, speed)
            self.add_flash_message(
                text, payload["position"], payload["color"], now, duration=text_duration
            )
            self.add_shockwave(
                payload["position"], payload["color"], now, max_radius=radius, thickness=thickness
            )
            self.register_screen_feedback(now, shake=shake, flash=flash, duration=duration)
            self.sound_events.append(("clash", payload["sound"]))
            return

        if event.kind == "shield_hit":
            player = self.players[payload["player_index"]]
            self.spawn_burst(
                payload["position"],
                payload["color"],
                payload["burst_count"],
                payload["burst_speed"],
            )
            player.last_message = "SHIELD HIT"
            player.message_until = now + 0.7
            self.register_screen_feedback(now, shake=3.5, flash=0.12, duration=0.12)
            self.sound_events.append(("shield_hit",))
            if payload["shield_broken"]:
                self.spawn_burst(payload["player_position"], (255, 255, 255), 45, 220)
            return

        if event.kind == "player_hit":
            player = self.players[payload["player_index"]]
            player.set_visual_state("hit", now, 0.55)
            player.last_message = payload["message"]
            player.message_until = now + 0.9
            self.spawn_burst(payload["position"], payload["color"], 55, 240)
            self.register_screen_feedback(now, shake=9.0, flash=0.28, duration=0.18)
            self.sound_events.append(("hit",))
            return

        if event.kind == "round_ended":
            self.spawn_burst(payload["position"], (255, 255, 255), 80, 260)
            self.sound_events.append(("round_over",))

    def spawn_trail(self, projectile):
        for _ in range(2):
            jitter = np.array(
                [random.uniform(-8, 8), random.uniform(-8, 8)], dtype=np.float32
            )
            velocity = -projectile.vel * 0.06 + np.array(
                [random.uniform(-35, 35), random.uniform(-35, 35)], dtype=np.float32
            )
            self.particles.append(
                Particle(
                    pos=projectile.pos + jitter,
                    vel=velocity,
                    color=projectile.color,
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
            angle = random.uniform(0, math.tau)
            radius = random.uniform(50, 105)
            position = center + np.array(
                [math.cos(angle) * radius, math.sin(angle) * radius], dtype=np.float32
            )
            outward = position - center
            norm = max(np.linalg.norm(outward), 1)
            velocity = outward / norm * random.uniform(18, 55)
            self.particles.append(
                Particle(
                    pos=position,
                    vel=velocity,
                    color=SPELLS["lumos"]["color"],
                    radius=random.uniform(2, 7),
                    life=random.uniform(0.35, 0.75),
                    max_life=0.75,
                )
            )

    def spawn_burst(self, pos, color, count, speed):
        for _ in range(count):
            angle = random.uniform(0, math.tau)
            magnitude = random.uniform(speed * 0.25, speed)
            velocity = np.array(
                [math.cos(angle) * magnitude, math.sin(angle) * magnitude], dtype=np.float32
            )
            self.particles.append(
                Particle(
                    pos=np.array(pos, dtype=np.float32),
                    vel=velocity,
                    color=color,
                    radius=random.uniform(2, 8),
                    life=random.uniform(0.35, 0.9),
                    max_life=0.9,
                )
            )
