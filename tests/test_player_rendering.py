import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class PlayerRenderingTests(unittest.TestCase):
    def test_draw_player_uses_current_pose_character_art(self):
        from config import HEIGHT, WIDTH
        from game.battle import BattleGame
        from renderer.player import draw_player

        game = BattleGame(character_ids=("harry", "ron"))
        player = game.players[0]
        player.set_visual_state("casting", now=10.0, duration=1.0)
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

        with patch("renderer.player.draw_character_sprite", return_value=True) as draw_sprite:
            draw_player(frame, player, now=10.2)

        self.assertEqual(draw_sprite.call_args.kwargs["character_id"], "harry")
        self.assertEqual(draw_sprite.call_args.kwargs["pose"], "casting")

    def test_draw_player_flips_right_side_character_art(self):
        from config import HEIGHT, WIDTH
        from game.battle import BattleGame
        from renderer.player import draw_player

        game = BattleGame(character_ids=("harry", "ron"))
        player = game.players[1]
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

        with patch("renderer.player.draw_character_sprite", return_value=True) as draw_sprite:
            draw_player(frame, player, now=10.0)

        self.assertTrue(draw_sprite.call_args.kwargs["flip"])

    def test_draw_player_falls_back_to_geometric_body_when_asset_missing(self):
        from config import HEIGHT, WIDTH
        from game.battle import BattleGame
        from renderer.player import draw_player

        game = BattleGame(character_ids=("harry", "ron"))
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

        with patch("renderer.player.draw_character_sprite", return_value=False):
            draw_player(frame, game.players[0], now=10.0)

        self.assertGreater(int(np.count_nonzero(frame)), 0)


if __name__ == "__main__":
    unittest.main()
