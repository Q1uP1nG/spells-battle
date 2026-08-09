import json
import unittest

from game.battle_engine import BattleEngine
from game.snapshots import snapshot_from_engine
from network.protocol import snapshot_from_payload, snapshot_to_payload


class BattleSnapshotTests(unittest.TestCase):
    def test_snapshot_contains_only_json_compatible_authority_values(self):
        engine = BattleEngine(("harry", "ron"))
        engine.cast_spell(0, "stupefy", 1.0)

        snapshot = snapshot_from_engine(engine, "match-1", 12, 1.25)
        payload = snapshot_to_payload(snapshot)

        encoded = json.dumps(payload, allow_nan=False)
        self.assertIsInstance(encoded, str)
        self.assertIsInstance(payload["projectiles"][0]["x"], float)
        self.assertIsInstance(payload["projectiles"][0]["projectile_id"], int)

    def test_snapshot_round_trip_preserves_value(self):
        engine = BattleEngine(("hermione", "snape"))
        engine.cast_spell(0, "protego", 2.0)
        engine.cast_spell(1, "glacius", 2.0)
        snapshot = snapshot_from_engine(engine, "match-roundtrip", 27, 2.5)

        restored = snapshot_from_payload(json.loads(json.dumps(snapshot_to_payload(snapshot))))

        self.assertEqual(restored, snapshot)

    def test_snapshot_transmits_remaining_durations_not_machine_clock_values(self):
        engine = BattleEngine()
        engine.cast_spell(0, "protego", 1000.0)

        snapshot = snapshot_from_engine(engine, "match-time", 1, 1001.0)
        player = snapshot.players[0]

        self.assertGreater(player.shield_remaining, 0.0)
        self.assertLess(player.shield_remaining, 20.0)
        self.assertGreaterEqual(player.global_cooldown_remaining, 0.0)


if __name__ == "__main__":
    unittest.main()
