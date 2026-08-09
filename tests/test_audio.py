import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class AudioRegistryTests(unittest.TestCase):
    def test_spell_clash_effects_have_registered_fallbacks(self):
        from game.audio import SOUND_GENERATORS

        for name in (
            "clash_fire_lightning",
            "clash_lightning_ice",
            "clash_ice_fire",
            "clash_cancel",
        ):
            self.assertIn(name, SOUND_GENERATORS)

    def test_main_sound_dispatch_handles_fail_and_clash_events(self):
        from main import play_sound_event

        class FakeAudio:
            def __init__(self):
                self.calls = []

            def play_cast(self, name):
                self.calls.append(("cast", name))

            def play_hit(self):
                self.calls.append(("hit",))

            def play_shield_hit(self):
                self.calls.append(("shield_hit",))

            def play_round_over(self):
                self.calls.append(("round_over",))

            def play_cast_fail(self):
                self.calls.append(("cast_fail",))

            def play_effect(self, name):
                self.calls.append(("effect", name))

        audio = FakeAudio()

        play_sound_event(audio, ("cast_fail",))
        play_sound_event(audio, ("clash", "clash_ice_fire"))

        self.assertEqual(
            audio.calls,
            [
                ("cast_fail",),
                ("effect", "clash_ice_fire"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
