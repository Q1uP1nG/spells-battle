import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class CastIntentTests(unittest.TestCase):
    def test_intent_is_immutable_and_has_no_player_identity(self):
        from game.commands import CastIntent

        intent = CastIntent("incendio", sequence=1, client_time_ms=1250, source="cv")

        self.assertNotIn("player_index", intent.__dataclass_fields__)
        with self.assertRaises(FrozenInstanceError):
            intent.spell = "lumos"

    def test_intent_rejects_invalid_transport_values(self):
        from game.commands import CastIntent

        with self.assertRaises(ValueError):
            CastIntent("", sequence=1, client_time_ms=0, source="cv")
        with self.assertRaises(ValueError):
            CastIntent("incendio", sequence=0, client_time_ms=0, source="cv")
        with self.assertRaises(ValueError):
            CastIntent("incendio", sequence=1, client_time_ms=-1, source="cv")
        with self.assertRaises(ValueError):
            CastIntent("incendio", sequence=1, client_time_ms=0, source="network")


class LocalBattleSessionTests(unittest.TestCase):
    def test_local_session_satisfies_battle_session_protocol(self):
        from game.session import BattleSession, LocalBattleSession

        game = SimpleNamespace(cast_spell=lambda *_args: True, players=[])
        self.assertIsInstance(LocalBattleSession(game), BattleSession)

    def test_request_builds_monotonic_intents_and_delegates_once(self):
        from game.session import LocalBattleSession

        calls = []

        class FakeGame:
            players = [SimpleNamespace(last_message=""), SimpleNamespace(last_message="")]

            def cast_spell(self, player_index, spell, now):
                calls.append((player_index, spell, now))
                return True

        session = LocalBattleSession(FakeGame())
        first = session.request_cast(0, "incendio", 1.25, "keyboard")
        second = session.request_cast(0, "lumos", 1.50, "cv")
        other_player = session.request_cast(1, "glacius", 1.75, "keyboard")

        self.assertEqual(calls, [(0, "incendio", 1.25), (0, "lumos", 1.5), (1, "glacius", 1.75)])
        self.assertEqual(first.intent.sequence, 1)
        self.assertEqual(second.intent.sequence, 2)
        self.assertEqual(other_player.intent.sequence, 1)
        self.assertEqual(first.intent.client_time_ms, 1250)
        self.assertTrue(first.accepted)
        self.assertFalse(first.pending)

    def test_rejected_cast_reports_game_reason(self):
        from game.session import LocalBattleSession

        player = SimpleNamespace(last_message="")

        class FakeGame:
            players = [player]

            def cast_spell(self, _player_index, _spell, _now):
                player.last_message = "NO MANA"
                return False

        result = LocalBattleSession(FakeGame()).request_cast(0, "incendio", 3.0, "cv")

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "NO MANA")


if __name__ == "__main__":
    unittest.main()
