import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class CharacterProfileTests(unittest.TestCase):
    def test_character_roster_has_expected_roles_and_poses(self):
        from game.characters import CHARACTERS, CHARACTER_ORDER

        self.assertEqual(CHARACTER_ORDER, ("harry", "hermione", "ron", "snape"))
        self.assertEqual(CHARACTERS["ron"].max_hp_mult, 1.2)
        self.assertLess(CHARACTERS["hermione"].spell_cooldown_mult, 1.0)
        self.assertGreater(CHARACTERS["harry"].damage_mult, 1.0)
        self.assertTrue(CHARACTERS["snape"].uncounterable_spells)

        for profile in CHARACTERS.values():
            self.assertEqual(set(profile.poses), {"normal", "casting", "hit", "win", "lose"})

    def test_player_applies_character_profile_and_pose_state(self):
        from models.player import Player

        ron = Player(0, "P1", "left", character_id="ron")
        self.assertEqual(ron.character_id, "ron")
        self.assertEqual(ron.name, "P1")
        self.assertEqual(ron.display_name, "Ron")
        self.assertEqual(ron.max_hp, 120.0)
        self.assertEqual(ron.hp, 120.0)

        ron.set_visual_state("casting", now=10.0, duration=0.5)
        self.assertEqual(ron.pose_key(now=10.2), "casting")
        self.assertEqual(ron.pose_key(now=10.6), "normal")
        self.assertEqual(ron.pose_key(now=10.6, winner=0), "win")
        self.assertEqual(ron.pose_key(now=10.6, winner=1), "lose")


class CharacterBattleBuffTests(unittest.TestCase):
    def test_harry_projectile_damage_is_boosted(self):
        from game.battle import BattleGame

        game = BattleGame(character_ids=("harry", "ron"))
        game.cast_spell(0, "incendio", now=10.0)

        self.assertAlmostEqual(game.projectiles[-1].damage, 22 * 1.15)

    def test_buff_disable_suppresses_harry_damage_boost_temporarily(self):
        from game.battle import BattleGame

        game = BattleGame(character_ids=("harry", "ron"))
        game.players[0].buff_disabled_until = 30.0

        game.cast_spell(0, "incendio", now=10.0)
        self.assertAlmostEqual(game.projectiles[-1].damage, 22.0)

        game.players[0].mana = 100.0
        game.cast_spell(0, "glacius", now=31.0)
        self.assertAlmostEqual(game.projectiles[-1].damage, 10 * 1.15)

    def test_hermione_has_shorter_spell_and_global_cooldowns(self):
        from config import GLOBAL_CAST_COOLDOWN, SPELLS
        from game.battle import BattleGame

        game = BattleGame(character_ids=("hermione", "ron"))
        game.cast_spell(0, "glacius", now=10.0)
        player = game.players[0]

        self.assertAlmostEqual(player.global_cooldown_until, 10.0 + GLOBAL_CAST_COOLDOWN * 0.9)
        self.assertAlmostEqual(player.spell_cooldown_until["glacius"], 10.0 + SPELLS["glacius"]["cooldown"] * 0.85)

    def test_buff_disable_suppresses_hermione_cooldown_boost_temporarily(self):
        from config import SPELLS
        from game.battle import BattleGame

        game = BattleGame(character_ids=("hermione", "ron"))
        player = game.players[0]
        player.buff_disabled_until = 30.0

        game.cast_spell(0, "glacius", now=10.0)

        self.assertAlmostEqual(player.spell_cooldown_until["glacius"], 10.0 + SPELLS["glacius"]["cooldown"])

    def test_snape_projectile_cannot_be_countered_when_it_would_normally_lose(self):
        import numpy as np

        from game.battle import BattleGame
        from models.projectile import Projectile

        game = BattleGame(character_ids=("snape", "harry"))
        snape_incendio = Projectile(
            owner=0,
            spell="incendio",
            pos=np.array([500.0, 360.0], dtype=np.float32),
            vel=np.array([1.0, 0.0], dtype=np.float32),
            radius=30,
            damage=22,
            color=(40, 130, 255),
        )
        harry_glacius = Projectile(
            owner=1,
            spell="glacius",
            pos=np.array([505.0, 360.0], dtype=np.float32),
            vel=np.array([-1.0, 0.0], dtype=np.float32),
            radius=30,
            damage=10,
            color=(255, 210, 70),
        )

        game._apply_interaction(snape_incendio, harry_glacius)

        self.assertTrue(snape_incendio.active)
        self.assertFalse(harry_glacius.active)

    def test_buff_disable_suppresses_snape_counter_resistance(self):
        import numpy as np

        from game.battle import BattleGame
        from models.projectile import Projectile

        game = BattleGame(character_ids=("snape", "harry"))
        game.players[0].buff_disabled_until = 30.0
        snape_incendio = Projectile(
            owner=0,
            spell="incendio",
            pos=np.array([500.0, 360.0], dtype=np.float32),
            vel=np.array([1.0, 0.0], dtype=np.float32),
            radius=30,
            damage=22,
            color=(40, 130, 255),
        )
        harry_glacius = Projectile(
            owner=1,
            spell="glacius",
            pos=np.array([505.0, 360.0], dtype=np.float32),
            vel=np.array([-1.0, 0.0], dtype=np.float32),
            radius=30,
            damage=10,
            color=(255, 210, 70),
        )

        game._apply_interaction(snape_incendio, harry_glacius, now=10.0)

        self.assertFalse(snape_incendio.active)
        self.assertTrue(harry_glacius.active)

    def test_reset_preserves_selected_characters(self):
        from game.battle import BattleGame

        game = BattleGame(character_ids=("ron", "snape"))
        game.players[0].hp = 5

        game.reset()

        self.assertEqual([player.character_id for player in game.players], ["ron", "snape"])
        self.assertEqual(game.players[0].hp, 120.0)


class CharacterHelperTests(unittest.TestCase):
    def test_cycle_character_avoiding_skips_taken_role(self):
        from game.characters import CHARACTER_ORDER, cycle_character_avoiding

        # Forward from harry while avoiding hermione -> ron.
        self.assertEqual(cycle_character_avoiding("harry", "hermione", 1), "ron")
        # Backward from harry while avoiding snape -> ron.
        self.assertEqual(cycle_character_avoiding("harry", "snape", -1), "ron")

    def test_cycle_character_avoiding_wraps_around(self):
        from game.characters import cycle_character_avoiding

        # Forward from snape wraps to harry unless harry is avoided.
        self.assertEqual(cycle_character_avoiding("snape", "harry", 1), "hermione")
        # Backward from harry wraps to snape unless snape is avoided.
        self.assertEqual(cycle_character_avoiding("harry", "snape", -1), "ron")

    def test_random_character_excludes_given_id(self):
        from game.characters import CHARACTER_ORDER, random_character

        for _ in range(20):
            self.assertNotEqual(random_character(exclude_id="harry"), "harry")
            self.assertIn(random_character(), CHARACTER_ORDER)

    def test_battle_cycle_avoids_duplicate(self):
        from game.battle import BattleGame

        game = BattleGame(character_ids=("harry", "hermione"))
        game.set_player_character(1, "harry")
        game.cycle_player_character(1, 1)
        self.assertNotEqual(game.players[1].character_id, "harry")
        self.assertEqual(game.players[1].character_id, "hermione")

    def test_battle_randomize_respects_exclusion(self):
        from game.battle import BattleGame

        game = BattleGame(character_ids=("harry", "harry"))
        game.randomize_player_character(1)
        self.assertNotEqual(game.players[1].character_id, "harry")


if __name__ == "__main__":
    unittest.main()
