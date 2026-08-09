from __future__ import annotations

import os


ROOM_CODE_LENGTH = 6
BACKSPACE_KEYS = {8, 127}
ENTER_KEYS = {10, 13}
ESCAPE_KEY = 27


def room_code_character(key):
    """Return one server-compatible ASCII room-code character for a key."""
    if ord("0") <= key <= ord("9"):
        return chr(key)
    if ord("A") <= key <= ord("Z"):
        return chr(key)
    if ord("a") <= key <= ord("z"):
        return chr(key).upper()
    return ""


def apply_room_code_key(value, key, max_length=ROOM_CODE_LENGTH):
    """Apply one key and return ``(new_value, action)``.

    Actions are changed, submit, incomplete, cancel, or ignored.  In
    particular, OpenCV/Windows IME key 229 is ignored instead of becoming a
    non-ASCII glyph.
    """
    value = str(value)
    if key in BACKSPACE_KEYS:
        return value[:-1], "changed"
    if key in ENTER_KEYS:
        action = "submit" if len(value) == max_length else "incomplete"
        return value, action
    if key == ESCAPE_KEY:
        return "", "cancel"

    character = room_code_character(key)
    if character and len(value) < max_length:
        return value + character, "changed"
    return value, "ignored"


class PhysicalRoomCodeKeyboard:
    """Poll physical room-code keys on Windows, independently of the IME.

    OpenCV's ``waitKey`` reports ``VK_PROCESSKEY`` (229) while a Chinese IME is
    active and does not expose the underlying letter.  GetAsyncKeyState keeps
    room-code entry usable without asking the player to switch input methods.
    """

    _VK_TO_KEY = {
        **{value: value for value in range(ord("0"), ord("9") + 1)},
        **{value: value for value in range(ord("A"), ord("Z") + 1)},
        **{0x60 + value: ord("0") + value for value in range(10)},
        0x08: 8,
        0x0D: 13,
        0x1B: 27,
    }

    def __init__(self, get_key_state=None):
        if get_key_state is None and os.name == "nt":
            try:
                import ctypes

                get_key_state = ctypes.windll.user32.GetAsyncKeyState
            except (AttributeError, OSError):
                get_key_state = None
        self._get_key_state = get_key_state
        self._down = set()

    @property
    def available(self):
        return self._get_key_state is not None

    def _snapshot(self):
        down = set()
        pressed_since_poll = set()
        if not self.available:
            return down, pressed_since_poll
        for virtual_key in self._VK_TO_KEY:
            state = int(self._get_key_state(virtual_key)) & 0xFFFF
            if state & 0x8000:
                down.add(virtual_key)
            if state & 0x0001:
                pressed_since_poll.add(virtual_key)
        return down, pressed_since_poll

    def begin(self):
        """Capture held keys so the J used to open the field is not inserted."""
        self._down, _ = self._snapshot()

    def poll(self):
        if not self.available:
            return []
        down, pressed_since_poll = self._snapshot()
        # The low bit records a press since the previous query. Keep it even
        # when the key was down in the previous snapshot: the player may have
        # released and pressed it again between two rendered frames.
        newly_pressed = (down - self._down) | pressed_since_poll
        self._down = down
        return [self._VK_TO_KEY[key] for key in self._VK_TO_KEY if key in newly_pressed]
