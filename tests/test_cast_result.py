import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class CanCastTests(unittest.TestCase):
    def test_can_cast_returns_true_when_allowed(self):
        from game.battle import BattleGame

        game = BattleGame()
        allowed, reason = game.can_cast(0, "incendio", 100.0)
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_can_cast_returns_no_mana(self):
        from game.battle import BattleGame

        game = BattleGame()
        game.players[0].mana = 5.0
        allowed, reason = game.can_cast(0, "incendio", 100.0)
        self.assertFalse(allowed)
        self.assertEqual(reason, "NO MANA")

    def test_can_cast_returns_spell_cd(self):
        from game.battle import BattleGame

        game = BattleGame()
        game.cast_spell(0, "incendio", 100.0)
        allowed, reason = game.can_cast(0, "incendio", 100.5)
        self.assertFalse(allowed)
        self.assertEqual(reason, "SPELL CD")

    def test_can_cast_returns_global_cd_for_different_spell(self):
        from game.battle import BattleGame

        game = BattleGame()
        game.cast_spell(0, "incendio", 100.0)
        allowed, reason = game.can_cast(0, "stupefy", 100.5)
        self.assertFalse(allowed)
        self.assertEqual(reason, "GLOBAL CD")

    def test_global_cd_expires_before_different_spell_cast(self):
        from game.battle import BattleGame
        from config import GLOBAL_CAST_COOLDOWN

        game = BattleGame()
        game.cast_spell(0, "incendio", 100.0)
        allowed, reason = game.can_cast(0, "stupefy", 100.0 + GLOBAL_CAST_COOLDOWN)
        self.assertTrue(allowed, reason)
        self.assertEqual(reason, "")

    def test_successful_cast_sets_global_cooldown(self):
        from game.battle import BattleGame
        from config import GLOBAL_CAST_COOLDOWN

        game = BattleGame()
        game.cast_spell(0, "incendio", 100.0)
        self.assertEqual(game.players[0].global_cooldown_until, 100.0 + GLOBAL_CAST_COOLDOWN)

    def test_can_cast_returns_silenced(self):
        from game.battle import BattleGame

        game = BattleGame()
        game.players[0].silenced_until = 110.0
        allowed, reason = game.can_cast(0, "incendio", 105.0)
        self.assertFalse(allowed)
        self.assertEqual(reason, "SILENCED")

    def test_can_cast_returns_dead(self):
        from game.battle import BattleGame

        game = BattleGame()
        game.players[0].hp = 0.0
        allowed, reason = game.can_cast(0, "incendio", 100.0)
        self.assertFalse(allowed)
        self.assertEqual(reason, "DEAD")

    def test_can_cast_returns_round_over(self):
        from game.battle import BattleGame

        game = BattleGame()
        game.winner = 1
        allowed, reason = game.can_cast(0, "incendio", 100.0)
        self.assertFalse(allowed)
        self.assertEqual(reason, "ROUND OVER")

    def test_cast_spell_sets_reason_message(self):
        from game.battle import BattleGame

        game = BattleGame()
        game.players[0].mana = 5.0
        result = game.cast_spell(0, "incendio", 100.0)
        self.assertFalse(result)
        self.assertEqual(game.players[0].last_message, "NO MANA")

    def test_can_cast_all_spells(self):
        from game.battle import BattleGame

        game = BattleGame()
        for spell_name in ["incendio", "stupefy", "glacius", "protego", "lumos"]:
            allowed, reason = game.can_cast(0, spell_name, 100.0)
            self.assertTrue(allowed, f"{spell_name} should be allowed, got {reason}")
            self.assertEqual(reason, "")

    def test_lumos_heal_completion_starts_mana_regen_boost(self):
        from game.battle import BattleGame
        from config import SPELLS

        game = BattleGame()
        player = game.players[0]
        player.hp = 50.0

        self.assertTrue(game.cast_spell(0, "lumos", 10.0))
        game.update(0.0, 10.0 + SPELLS["lumos"]["channel"])

        self.assertEqual(player.hp, 68.0)
        self.assertEqual(player.pending_heal, 0)
        self.assertAlmostEqual(player.mana_regen_boost_until, 16.2)

    def test_mana_regen_boost_quadruples_regen_until_expired(self):
        from game.battle import BattleGame
        from config import MANA_REGEN_PER_SEC

        game = BattleGame()
        player = game.players[0]
        player.mana = 0.0
        player.mana_regen_boost_until = 20.0

        game.update(1.0, 11.0)
        self.assertEqual(player.mana, MANA_REGEN_PER_SEC * 4.0)

        game.update(1.0, 21.0)
        self.assertEqual(player.mana, MANA_REGEN_PER_SEC * 5.0)

    def test_overload_requires_minimum_mana_then_clears_all_mana_and_recovers(self):
        from game.battle import BattleGame

        game = BattleGame()
        player = game.players[0]
        player.mana = 60.0

        self.assertTrue(game.cast_spell(0, "overload", 10.0))

        self.assertEqual(player.mana, 0.0)
        self.assertGreaterEqual(player.global_cooldown_until, 13.0)

    def test_overload_rejects_below_minimum_mana(self):
        from game.battle import BattleGame

        game = BattleGame()
        game.players[0].mana = 44.0

        allowed, reason = game.can_cast(0, "overload", 10.0)

        self.assertFalse(allowed)
        self.assertEqual(reason, "NO MANA")


if __name__ == "__main__":
    unittest.main()
