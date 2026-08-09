import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class PVEAITests(unittest.TestCase):
    def test_ai_does_not_cast_when_p2_dead(self):
        from game.battle import BattleGame
        from game.pve_ai import SimplePVEAI

        game = BattleGame()
        game.players[1].hp = 0.0
        ai = SimplePVEAI()
        result = ai.update(game, 100.0)
        self.assertIsNone(result)

    def test_ai_respects_spell_cooldown(self):
        from game.battle import BattleGame
        from game.pve_ai import SimplePVEAI

        game = BattleGame()
        game.players[1].mana = 100.0
        game.cast_spell(1, "incendio", 10.0)
        ai = SimplePVEAI()
        ai.next_decision_time = 0.0
        result = ai.update(game, 10.1)
        if result == "incendio":
            self.fail("AI cast incendio while it was on cooldown")

    def test_ai_does_not_cast_with_insufficient_mana(self):
        from game.battle import BattleGame
        from game.pve_ai import SimplePVEAI

        game = BattleGame()
        game.players[1].mana = 1.0
        ai = SimplePVEAI()
        result = ai.update(game, 100.0)
        self.assertIsNone(result)

    def test_ai_casts_attack_spell_when_available(self):
        from game.battle import BattleGame
        from game.pve_ai import SimplePVEAI

        game = BattleGame()
        ai = SimplePVEAI()
        result = ai.update(game, 100.0)
        self.assertIsNone(result)
        self.assertIn(ai.pending_spell, ["incendio", "stupefy", "glacius"])
        self.assertAlmostEqual(ai.pending_cast_at, 101.6)
        self.assertEqual(len(game.projectiles), 0)
        self.assertEqual(game.players[1].mana, 100.0)
        self.assertIn("AI CASTING", game.players[1].last_message)

    def test_ai_casts_pending_spell_after_windup(self):
        from game.battle import BattleGame
        from game.pve_ai import SimplePVEAI

        game = BattleGame()
        ai = SimplePVEAI()

        self.assertIsNone(ai.update(game, 100.0))
        pending_spell = ai.pending_spell
        self.assertIsNone(ai.update(game, 101.59))
        self.assertEqual(len(game.projectiles), 0)

        result = ai.update(game, 101.61)

        self.assertEqual(result, pending_spell)
        self.assertIsNone(ai.pending_spell)
        self.assertEqual(len(game.projectiles), 1)
        self.assertLess(game.players[1].mana, 100.0)
        self.assertAlmostEqual(ai.next_decision_time, 101.61 + ai.attack_interval)

    def test_ai_cancels_pending_spell_if_silenced_before_release(self):
        from game.battle import BattleGame
        from game.pve_ai import SimplePVEAI

        game = BattleGame()
        ai = SimplePVEAI()

        self.assertIsNone(ai.update(game, 100.0))
        game.players[1].silenced_until = 102.0

        result = ai.update(game, 101.61)

        self.assertIsNone(result)
        self.assertIsNone(ai.pending_spell)
        self.assertEqual(len(game.projectiles), 0)
        self.assertAlmostEqual(ai.next_decision_time, 102.11)

    def test_ai_cancels_pending_spell_immediately_when_silenced_during_windup(self):
        from game.battle import BattleGame
        from game.pve_ai import SimplePVEAI

        game = BattleGame()
        ai = SimplePVEAI()

        self.assertIsNone(ai.update(game, 100.0))
        game.players[1].silenced_until = 102.0

        result = ai.update(game, 100.20)

        self.assertIsNone(result)
        self.assertIsNone(ai.pending_spell)
        self.assertEqual(len(game.projectiles), 0)
        self.assertAlmostEqual(ai.next_decision_time, 100.70)

    def test_ai_prefers_lumos_at_low_hp(self):
        from game.battle import BattleGame
        from game.pve_ai import SimplePVEAI

        game = BattleGame()
        game.players[1].hp = 20.0
        ai = SimplePVEAI()
        result = ai.update(game, 100.0)
        self.assertIsNone(result)
        self.assertEqual(ai.pending_spell, "lumos")

        result = ai.update(game, 101.61)
        self.assertEqual(result, "lumos")

    def test_ai_low_hp_check_uses_character_max_hp(self):
        from game.battle import BattleGame
        from game.pve_ai import SimplePVEAI

        game = BattleGame(character_ids=("harry", "ron"))
        game.players[1].hp = 40.0
        ai = SimplePVEAI()

        result = ai.update(game, 100.0)

        self.assertIsNone(result)
        self.assertEqual(ai.pending_spell, "lumos")

    def test_ai_considers_protego_with_incoming(self):
        from game.battle import BattleGame
        from game.pve_ai import SimplePVEAI
        from models.projectile import Projectile
        import numpy as np

        game = BattleGame()
        proj = Projectile(
            owner=0,
            spell="incendio",
            pos=np.array([500.0, 400.0]),
            vel=np.array([760.0, 0.0]),
            radius=28,
            damage=22,
            color=(40, 130, 255),
        )
        game.projectiles.append(proj)
        ai = SimplePVEAI()
        result = ai.update(game, 100.0)
        self.assertIsNone(result)
        self.assertEqual(ai.pending_spell, "protego")

        result = ai.update(game, 101.61)
        self.assertEqual(result, "protego")

    def test_ai_reset_clears_state(self):
        from game.pve_ai import SimplePVEAI

        ai = SimplePVEAI()
        ai.next_decision_time = 999.0
        ai._rotation_index = 5
        ai.pending_spell = "incendio"
        ai.pending_cast_at = 101.0
        ai.pending_started_at = 100.2
        ai.reset()
        self.assertEqual(ai.next_decision_time, 0.0)
        self.assertEqual(ai._rotation_index, 0)
        self.assertIsNone(ai.pending_spell)
        self.assertEqual(ai.pending_cast_at, 0.0)
        self.assertEqual(ai.pending_started_at, 0.0)

    def test_pve_rules_do_not_refill_mana(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame()
        game.players[1].mana = 30.0
        ModeRunner(GameMode.PVE)._apply_rules(game)
        self.assertEqual(game.players[1].mana, 30.0)

    def test_pve_rules_clear_winner_and_set_defeated(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame()
        game.players[1].hp = 0.0
        game.winner = 0
        ModeRunner(GameMode.PVE)._apply_rules(game)
        self.assertIsNone(game.winner)
        self.assertTrue(game.solo_dummy_defeated)

    def test_pve_rules_keep_winner_when_player_is_defeated(self):
        from game.battle import BattleGame
        from game.mode import GameMode, ModeRunner

        game = BattleGame()
        game.players[0].hp = 0.0
        game.update(0.016, 100.0)

        ModeRunner(GameMode.PVE)._apply_rules(game)

        self.assertEqual(game.winner, 1)
        self.assertFalse(game.solo_dummy_defeated)


if __name__ == "__main__":
    unittest.main()
