import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SpellInteractionTests(unittest.TestCase):
    # -- helpers ---------------------------------------------------------------

    def _make_game(self):
        from game.battle import BattleGame
        return BattleGame(character_ids=("harry", "ron"))

    def _make_proj(self, spell, owner=0, pos_x=500.0, pos_y=400.0):
        from models.projectile import Projectile
        from config import SPELLS

        s = SPELLS[spell]
        return Projectile(
            owner=owner,
            spell=spell,
            pos=np.array([pos_x, pos_y]),
            vel=np.array([s["speed"], 0.0]),
            radius=s["radius"],
            damage=s["damage"],
            color=s["color"],
        )

    # -- incendio vs stupefy ---------------------------------------------------

    def test_incendio_beats_stupefy(self):
        game = self._make_game()
        a = self._make_proj("incendio", owner=0)
        b = self._make_proj("stupefy", owner=1)
        a.vel = np.array([760.0, 0.0])
        b.vel = np.array([-620.0, 0.0])

        old_damage = a.damage
        game._apply_interaction(a, b)

        self.assertTrue(a.active)
        self.assertFalse(b.active)
        self.assertAlmostEqual(a.damage, old_damage * 0.75)
        self.assertEqual(a.vel[0], 760.0)  # vel unchanged for incendio winner
        self.assertIn(("clash", "clash_fire_lightning"), game.sound_events)

    def test_incendio_beats_stupefy_reverse_order(self):
        game = self._make_game()
        a = self._make_proj("stupefy", owner=0)
        b = self._make_proj("incendio", owner=1)

        old_damage = b.damage
        game._apply_interaction(a, b)

        self.assertFalse(a.active)
        self.assertTrue(b.active)
        self.assertAlmostEqual(b.damage, old_damage * 0.75)

    # -- stupefy vs glacius ----------------------------------------------------

    def test_stupefy_beats_glacius(self):
        game = self._make_game()
        a = self._make_proj("stupefy", owner=0)
        b = self._make_proj("glacius", owner=1)

        old_damage = a.damage
        old_vel_x = a.vel[0]
        game._apply_interaction(a, b)

        self.assertTrue(a.active)
        self.assertFalse(b.active)
        self.assertAlmostEqual(a.damage, old_damage * 0.75)
        self.assertAlmostEqual(a.vel[0], old_vel_x * 0.85)
        self.assertIn(("clash", "clash_lightning_ice"), game.sound_events)

    # -- incendio vs glacius ---------------------------------------------------

    def test_glacius_beats_incendio(self):
        game = self._make_game()
        a = self._make_proj("incendio", owner=0)
        b = self._make_proj("glacius", owner=1)

        old_damage = b.damage
        old_vel_x = b.vel[0]
        game._apply_interaction(a, b)

        self.assertFalse(a.active)
        self.assertTrue(b.active)
        self.assertAlmostEqual(b.damage, old_damage * 0.80)
        self.assertAlmostEqual(b.vel[0], old_vel_x * 0.90)
        self.assertIn(("clash", "clash_ice_fire"), game.sound_events)

    def test_counter_interaction_adds_player_facing_flash_message(self):
        game = self._make_game()
        a = self._make_proj("incendio", owner=0)
        b = self._make_proj("stupefy", owner=1)

        game._apply_interaction(a, b, now=12.0)

        self.assertTrue(any(msg["text"] == "COUNTERED!" for msg in game.flash_messages))

    # -- same spell: both destroyed --------------------------------------------

    def test_same_spell_both_destroyed(self):
        game = self._make_game()
        a = self._make_proj("incendio", owner=0)
        b = self._make_proj("incendio", owner=1)

        game._apply_interaction(a, b)

        self.assertFalse(a.active)
        self.assertFalse(b.active)
        self.assertIn(("clash", "clash_cancel"), game.sound_events)

    # -- unlisted combination: both destroyed ----------------------------------

    def test_unlisted_pair_both_destroyed(self):
        from models.projectile import Projectile

        game = self._make_game()
        # Two projectiles whose spells have no entry in SPELL_INTERACTIONS.
        a = Projectile(owner=0, spell="incendio",
                       pos=np.array([500.0, 400.0]),
                       vel=np.array([760.0, 0.0]),
                       radius=28, damage=22, color=(40, 130, 255))
        b = Projectile(owner=1, spell="unknown_xyz",
                       pos=np.array([520.0, 400.0]),
                       vel=np.array([-500.0, 0.0]),
                       radius=22, damage=10, color=(200, 200, 200))

        game._apply_interaction(a, b)

        self.assertFalse(a.active)
        self.assertFalse(b.active)

    # -- table is complete for all listed pairs -------------------------------

    def test_all_defined_pairs_covered(self):
        from config import SPELL_INTERACTIONS

        for (x, y), (winner, dmg, vel) in SPELL_INTERACTIONS.items():
            self.assertIn(x, ["incendio", "stupefy", "glacius", "protego", "lumos"])
            self.assertIn(y, ["incendio", "stupefy", "glacius", "protego", "lumos"])
            self.assertIn(winner, [x, y])
            self.assertGreater(dmg, 0.0)
            self.assertGreaterEqual(vel, 0.0)

    # -- resolve method integration (smoke) -----------------------------------

    def test_resolve_handles_empty_projectiles(self):
        game = self._make_game()
        game.resolve_projectile_collisions(0.0)  # should not crash
        self.assertEqual(len(game.projectiles), 0)


if __name__ == "__main__":
    unittest.main()
