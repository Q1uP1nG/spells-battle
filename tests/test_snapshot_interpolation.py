import unittest

from game.battle_engine import BattleEngine
from game.snapshots import snapshot_from_engine
from network.clock import SnapshotInterpolator


class SnapshotInterpolationTests(unittest.TestCase):
    def test_projectile_interpolates_by_stable_id(self):
        engine = BattleEngine()
        engine.cast_spell(0, "incendio", 0.0)
        first = snapshot_from_engine(engine, "match", 1, 0.0)
        engine.update(0.1, 0.1)
        second = snapshot_from_engine(engine, "match", 4, 0.1)
        interpolator = SnapshotInterpolator()
        interpolator.push(first, received_at=5.0)
        interpolator.push(second, received_at=5.1)

        positions = interpolator.projectile_positions(5.15)

        expected_x = (first.projectiles[0].x + second.projectiles[0].x) / 2
        self.assertAlmostEqual(positions[1][0], expected_x, places=4)

    def test_stale_snapshot_is_ignored(self):
        engine = BattleEngine()
        newest = snapshot_from_engine(engine, "match", 8, 1.0)
        stale = snapshot_from_engine(engine, "match", 7, 0.9)
        interpolator = SnapshotInterpolator()

        self.assertTrue(interpolator.push(newest, 2.0))
        self.assertFalse(interpolator.push(stale, 2.1))
        self.assertEqual(interpolator.current.server_tick, 8)


if __name__ == "__main__":
    unittest.main()
