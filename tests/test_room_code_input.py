import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class RoomCodeInputTests(unittest.TestCase):
    def test_accepts_only_ascii_room_code_characters(self):
        from game.room_code_input import apply_room_code_key

        value = ""
        for key in map(ord, "aB3nmx"):
            value, action = apply_room_code_key(value, key)
            self.assertEqual(action, "changed")

        self.assertEqual(value, "AB3NMX")

    def test_windows_ime_process_key_is_ignored(self):
        from game.room_code_input import apply_room_code_key

        value, action = apply_room_code_key("AB", 229)

        self.assertEqual(value, "AB")
        self.assertEqual(action, "ignored")

    def test_backspace_does_not_create_a_replacement_character(self):
        from game.room_code_input import apply_room_code_key

        value, action = apply_room_code_key("ABC", 8)
        self.assertEqual((value, action), ("AB", "changed"))
        self.assertEqual(apply_room_code_key(value, 229), ("AB", "ignored"))

    def test_enter_requires_the_complete_six_character_code(self):
        from game.room_code_input import apply_room_code_key

        self.assertEqual(apply_room_code_key("ABC", 13), ("ABC", "incomplete"))
        self.assertEqual(apply_room_code_key("ABC123", 13), ("ABC123", "submit"))

    def test_escape_cancels_entry(self):
        from game.room_code_input import apply_room_code_key

        self.assertEqual(apply_room_code_key("ABC", 27), ("", "cancel"))

    def test_physical_keyboard_ignores_the_held_join_key_then_accepts_b(self):
        from game.room_code_input import PhysicalRoomCodeKeyboard

        states = {ord("J"): 0x8000}
        keyboard = PhysicalRoomCodeKeyboard(lambda key: states.get(key, 0))
        keyboard.begin()
        self.assertEqual(keyboard.poll(), [])

        states[ord("J")] = 0
        keyboard.poll()
        states[ord("B")] = 0x8000

        self.assertEqual(keyboard.poll(), [ord("B")])


if __name__ == "__main__":
    unittest.main()
