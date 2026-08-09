import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SettingsTests(unittest.TestCase):
    def setUp(self):
        import game.settings as S

        self._original_path = S.SETTINGS_PATH
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        S.SETTINGS_PATH = Path(self._tmp.name)

    def tearDown(self):
        import game.settings as S

        S.SETTINGS_PATH = self._original_path
        self._tmp.close()
        Path(self._tmp.name).unlink(missing_ok=True)

    # -- load ----------------------------------------------------------------

    def test_load_returns_defaults_when_file_missing(self):
        import game.settings as S

        S.SETTINGS_PATH = Path("/nonexistent_dir_xyz/spells/settings.json")
        result = S.load()
        self.assertEqual(result["input_mode"], "finger")
        self.assertIsNone(result["wand_hue"])

    def test_load_returns_defaults_for_corrupt_json(self):
        import game.settings as S

        S.SETTINGS_PATH.write_text("not valid json {{{")
        result = S.load()
        self.assertEqual(result["input_mode"], "finger")

    def test_save_and_load_roundtrip(self):
        import game.settings as S

        data = {
            "input_mode": "wand",
            "wand_hue": 42.5,
            "wand_sat_min": 80,
            "wand_val_min": 90,
            "wand_color_bgr": (0, 255, 255),
        }
        S.save(data)
        result = S.load()
        self.assertEqual(result["input_mode"], "wand")
        self.assertEqual(result["wand_hue"], 42.5)
        self.assertEqual(result["wand_sat_min"], 80)
        self.assertEqual(result["wand_val_min"], 90)
        self.assertEqual(result["wand_color_bgr"], (0, 255, 255))

    def test_save_filters_unknown_keys(self):
        import game.settings as S

        data = {"input_mode": "finger", "wand_hue": None, "extra_key": "evil"}
        S.save(data)
        raw = json.loads(S.SETTINGS_PATH.read_text())
        self.assertNotIn("extra_key", raw)
        self.assertIn("input_mode", raw)

    def test_save_and_load_player_characters(self):
        import game.settings as S

        S.save({"input_mode": "finger", "player_characters": ["ron", "snape"]})

        result = S.load()

        self.assertEqual(result["player_characters"], ["ron", "snape"])

    def test_load_filters_unknown_keys(self):
        import game.settings as S

        S.save({"input_mode": "finger"})
        raw = json.loads(S.SETTINGS_PATH.read_text())
        raw["bogus"] = 123
        S.SETTINGS_PATH.write_text(json.dumps(raw))
        result = S.load()
        self.assertNotIn("bogus", result)
        self.assertEqual(result["input_mode"], "finger")

    # -- collect --------------------------------------------------------------

    def test_collect_reads_cv_state(self):
        from game.settings import collect

        class FakeWand:
            wand_hue = 55.0
            wand_sat_min = 72
            wand_val_min = 85
            wand_color_bgr = (255, 0, 0)

        class FakeCV:
            input_mode = "wand"
            wand_detector = FakeWand()

        result = collect(FakeCV)
        self.assertEqual(result["input_mode"], "wand")
        self.assertEqual(result["wand_hue"], 55.0)
        self.assertEqual(result["wand_color_bgr"], (255, 0, 0))

    def test_collect_reads_player_characters_when_game_is_provided(self):
        from game.battle import BattleGame
        from game.settings import collect

        class FakeWand:
            wand_hue = None
            wand_sat_min = 70
            wand_val_min = 70
            wand_color_bgr = None

        class FakeCV:
            input_mode = "finger"
            wand_detector = FakeWand()

        game = BattleGame(character_ids=("ron", "snape"))

        result = collect(FakeCV, game)

        self.assertEqual(result["player_characters"], ["ron", "snape"])

    # -- restore --------------------------------------------------------------

    def test_restore_ignores_finger_mode(self):
        from game.settings import restore

        class FakeWand:
            wand_hue = None
            wand_sat_min = 70
            wand_val_min = 70
            wand_color_bgr = None

        class FakeCV:
            input_mode = "finger"
            wand_detector = FakeWand()

            def refresh_status(self):
                self._refreshed = True

        fake = FakeCV()
        fake._refreshed = False
        restore(fake, {"input_mode": "finger", "wand_hue": None})
        self.assertEqual(fake.input_mode, "finger")
        self.assertIsNone(fake.wand_detector.wand_hue)

    def test_restore_applies_wand_mode(self):
        from game.settings import restore

        class FakeWand:
            wand_hue = None
            wand_sat_min = 70
            wand_val_min = 70
            wand_color_bgr = None

        class FakeCV:
            input_mode = "finger"
            wand_detector = FakeWand()

            def refresh_status(self):
                self._refreshed = True

        fake = FakeCV()
        fake._refreshed = False
        settings = {
            "input_mode": "wand",
            "wand_hue": 30.0,
            "wand_sat_min": 65,
            "wand_val_min": 75,
            "wand_color_bgr": (100, 200, 50),
        }
        restore(fake, settings)
        self.assertEqual(fake.input_mode, "wand")
        self.assertEqual(fake.wand_detector.wand_hue, 30.0)
        self.assertEqual(fake.wand_detector.wand_sat_min, 65)
        self.assertEqual(fake.wand_detector.wand_val_min, 75)
        self.assertEqual(fake.wand_detector.wand_color_bgr, (100, 200, 50))

    def test_restore_ignores_wand_without_hue(self):
        from game.settings import restore

        class FakeCV:
            input_mode = "finger"

            def refresh_status(self):
                pass

        fake = FakeCV()
        restore(fake, {"input_mode": "wand", "wand_hue": None})
        self.assertEqual(fake.input_mode, "finger")

    def test_restore_applies_player_characters_when_game_is_provided(self):
        from game.battle import BattleGame
        from game.settings import restore

        class FakeCV:
            input_mode = "finger"

            def refresh_status(self):
                pass

        game = BattleGame(character_ids=("harry", "snape"))

        restore(FakeCV(), {"player_characters": ["ron", "hermione"]}, game)

        self.assertEqual([player.character_id for player in game.players], ["ron", "hermione"])
        self.assertEqual(game.players[0].max_hp, 120.0)

    # -- validation of malformed values -------------------------------------

    def test_invalid_input_mode_reverts_to_default(self):
        import game.settings as S

        S.SETTINGS_PATH.write_text(json.dumps({"input_mode": "banana"}))
        result = S.load()
        self.assertEqual(result["input_mode"], "finger")

    def test_invalid_wand_hue_reverts_to_default(self):
        import game.settings as S

        S.SETTINGS_PATH.write_text(json.dumps({"wand_hue": "not_a_number"}))
        result = S.load()
        self.assertIsNone(result["wand_hue"])

    def test_out_of_range_wand_hue_reverts_to_default(self):
        import game.settings as S

        S.SETTINGS_PATH.write_text(json.dumps({"wand_hue": 181.0}))
        result = S.load()
        self.assertIsNone(result["wand_hue"])

    def test_invalid_sat_reverts_to_default(self):
        import game.settings as S

        S.SETTINGS_PATH.write_text(json.dumps({"wand_sat_min": [1, 2, 3]}))
        result = S.load()
        self.assertEqual(result["wand_sat_min"], 70)

    def test_out_of_range_sat_and_val_revert_to_default(self):
        import game.settings as S

        S.SETTINGS_PATH.write_text(json.dumps({"wand_sat_min": -1, "wand_val_min": 300}))
        result = S.load()
        self.assertEqual(result["wand_sat_min"], 70)
        self.assertEqual(result["wand_val_min"], 70)

    def test_invalid_color_bgr_reverts_to_default(self):
        import game.settings as S

        S.SETTINGS_PATH.write_text(json.dumps({"wand_color_bgr": "red"}))
        result = S.load()
        self.assertIsNone(result["wand_color_bgr"])

    def test_color_bgr_wrong_length_reverts_to_default(self):
        import game.settings as S

        S.SETTINGS_PATH.write_text(json.dumps({"wand_color_bgr": [255, 0]}))
        result = S.load()
        self.assertIsNone(result["wand_color_bgr"])

    def test_color_bgr_out_of_range_reverts_to_default(self):
        import game.settings as S

        S.SETTINGS_PATH.write_text(json.dumps({"wand_color_bgr": [255, -1, 999]}))
        result = S.load()
        self.assertIsNone(result["wand_color_bgr"])

    def test_plain_wand_saved_from_old_versions_reverts_to_default(self):
        import game.settings as S

        data = {"input_mode": "plain_wand", "wand_hue": None}
        S.save(data)
        result = S.load()
        self.assertEqual(result["input_mode"], "finger")

    def test_plain_wand_loaded_from_old_versions_reverts_to_default(self):
        import game.settings as S

        S.SETTINGS_PATH.write_text(json.dumps({"input_mode": "plain_wand", "wand_hue": None}))
        result = S.load()
        self.assertEqual(result["input_mode"], "finger")

    def test_restore_ignores_plain_wand_from_old_versions(self):
        from game.settings import restore

        class FakeCV:
            input_mode = "finger"

            def refresh_status(self):
                self._refreshed = True

        fake = FakeCV()
        fake._refreshed = False
        restore(fake, {"input_mode": "plain_wand", "wand_hue": None})
        self.assertEqual(fake.input_mode, "finger")
        self.assertFalse(fake._refreshed)


if __name__ == "__main__":
    unittest.main()
