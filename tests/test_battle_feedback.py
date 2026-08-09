import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class BattleFeedbackTests(unittest.TestCase):
    def _make_game(self):
        from game.battle import BattleGame

        return BattleGame(character_ids=("harry", "ron"))

    def _make_projectile(self, spell="incendio", owner=1):
        from config import SPELLS
        from models.projectile import Projectile

        s = SPELLS[spell]
        return Projectile(
            owner=owner,
            spell=spell,
            pos=np.array([400.0, 360.0], dtype=np.float32),
            vel=np.array([-s.get("speed", 500.0), 0.0], dtype=np.float32),
            radius=s.get("radius", 24),
            damage=s.get("damage", 10),
            color=s["color"],
        )

    def test_shield_hit_keeps_character_out_of_hit_pose(self):
        game = self._make_game()
        target = game.players[0]
        target.shield_value = 35
        target.shield_until = 20.0
        target.visual_state = "normal"
        target.visual_state_until = 0.0

        game.apply_shield_hit(target, self._make_projectile(), now=10.0)

        self.assertEqual(target.visual_state, "normal")
        self.assertEqual(target.pose_key(10.2), "normal")
        self.assertEqual(target.last_message, "SHIELD HIT")

    def test_player_hit_sets_hit_pose_and_screen_feedback(self):
        game = self._make_game()
        target = game.players[0]

        game.apply_player_hit(target, self._make_projectile(), now=10.0)

        self.assertEqual(target.visual_state, "hit")
        self.assertGreater(game.screen_shake_until, 10.0)
        self.assertGreater(game.hit_flash_until, 10.0)

    def test_overload_hit_disables_target_buff_for_twenty_seconds(self):
        game = self._make_game()
        target = game.players[0]

        game.apply_player_hit(target, self._make_projectile("overload"), now=10.0)

        self.assertAlmostEqual(target.buff_disabled_until, 30.0)
        self.assertEqual(target.last_message, "BUFF DISABLED")

    def test_shield_blocks_overload_buff_disable(self):
        game = self._make_game()
        target = game.players[0]
        target.shield_value = 35
        target.shield_until = 20.0

        game.apply_shield_hit(target, self._make_projectile("overload"), now=10.0)

        self.assertEqual(target.buff_disabled_until, 0.0)


if __name__ == "__main__":
    unittest.main()
