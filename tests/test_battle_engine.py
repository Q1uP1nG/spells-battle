import ast
import inspect
import subprocess
import sys
import unittest

from game.battle_engine import BattleEngine


def authority_signature(engine):
    players = []
    for player in engine.players:
        players.append(
            (
                player.pid,
                player.character_id,
                player.hp,
                player.mana,
                player.global_cooldown_until,
                tuple(sorted(player.spell_cooldown_until.items())),
                player.shield_value,
                player.shield_until,
                player.silenced_until,
                player.frozen_until,
                player.healing_until,
                player.pending_heal,
                player.mana_regen_boost_until,
                player.buff_disabled_until,
            )
        )
    projectiles = []
    for projectile in engine.projectiles:
        projectiles.append(
            (
                projectile.projectile_id,
                projectile.owner,
                projectile.spell,
                tuple(float(value) for value in projectile.pos),
                tuple(float(value) for value in projectile.vel),
                projectile.radius,
                projectile.damage,
                projectile.life,
                projectile.active,
            )
        )
    return tuple(players), tuple(projectiles), engine.winner, engine.round_start


class BattleEngineTests(unittest.TestCase):
    def test_has_no_presentation_state(self):
        engine = BattleEngine(character_ids=("harry", "ron"))

        for attribute in ("particles", "sound_events", "flash_messages", "shockwaves"):
            self.assertFalse(hasattr(engine, attribute))

    def test_source_uses_injected_time_and_has_no_client_dependencies(self):
        source = inspect.getsource(sys.modules[BattleEngine.__module__])
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)

        self.assertNotIn("time.monotonic", source)
        self.assertFalse(any(name == "cv2" or name.startswith("cv2.") for name in imports))
        self.assertFalse(any(name == "pygame" or name.startswith("pygame.") for name in imports))
        self.assertFalse(any("renderer" in name for name in imports))
        self.assertNotIn("models.particle", imports)

    def test_headless_import_does_not_load_cv_or_pygame(self):
        command = (
            "import sys; from game.battle_engine import BattleEngine; "
            "BattleEngine(); "
            "assert 'cv2' not in sys.modules; assert 'pygame' not in sys.modules"
        )

        result = subprocess.run(
            [sys.executable, "-c", command],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_projectile_and_event_ids_are_stable_and_monotonic(self):
        engine = BattleEngine(character_ids=("harry", "ron"))

        self.assertTrue(engine.cast_spell(0, "stupefy", 1.0))
        self.assertTrue(engine.cast_spell(1, "glacius", 1.0))

        self.assertEqual([projectile.projectile_id for projectile in engine.projectiles], [1, 2])
        self.assertEqual([event.event_id for event in engine.events()], [1, 2])
        self.assertEqual([event.kind for event in engine.events()], ["cast_accepted", "cast_accepted"])

    def test_rejected_cast_is_a_structured_event(self):
        engine = BattleEngine()
        engine.players[0].mana = 0.0

        self.assertFalse(engine.cast_spell(0, "stupefy", 4.0))

        event = engine.events()[0]
        self.assertEqual(event.kind, "cast_rejected")
        self.assertEqual(event.match_time, 4.0)
        self.assertEqual(event.payload["reason"], "NO MANA")

    def test_same_inputs_produce_same_authoritative_state_and_events(self):
        engines = [BattleEngine(("harry", "ron")), BattleEngine(("harry", "ron"))]

        for engine in engines:
            engine.cast_spell(0, "stupefy", 1.0)
            engine.cast_spell(1, "glacius", 1.0)
            for step in range(1, 31):
                engine.update(1.0 / 60.0, 1.0 + step / 60.0)
            engine.cast_spell(0, "protego", 2.0)
            for step in range(1, 61):
                engine.update(1.0 / 60.0, 2.0 + step / 60.0)

        self.assertEqual(authority_signature(engines[0]), authority_signature(engines[1]))
        self.assertEqual(engines[0].events(), engines[1].events())


if __name__ == "__main__":
    unittest.main()
