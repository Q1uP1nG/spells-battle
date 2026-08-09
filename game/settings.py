"""Persist user preferences (input mode, wand calibration) across restarts."""

import json
import os
from pathlib import Path

from game.characters import CHARACTERS, DEFAULT_CHARACTER_IDS

SETTINGS_DIR = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "spells"
SETTINGS_PATH = SETTINGS_DIR / "settings.json"

DEFAULTS = {
    "input_mode": "finger",
    "wand_hue": None,
    "wand_sat_min": 70,
    "wand_val_min": 70,
    "wand_color_bgr": None,
    "wand_hue_p1": None,
    "wand_sat_min_p1": 70,
    "wand_val_min_p1": 70,
    "wand_color_bgr_p1": None,
    "player_characters": list(DEFAULT_CHARACTER_IDS),
}

OPENCV_HUE_MIN = 0.0
OPENCV_HUE_MAX = 180.0
COLOR_CHANNEL_MIN = 0
COLOR_CHANNEL_MAX = 255


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate(settings):
    """Fix or drop malformed values in-place."""
    if settings.get("input_mode") not in ("finger", "wand"):
        settings["input_mode"] = DEFAULTS["input_mode"]

    characters = settings.get("player_characters")
    if not (
        isinstance(characters, list)
        and len(characters) == 2
        and all(character_id in CHARACTERS for character_id in characters)
    ):
        settings["player_characters"] = list(DEFAULTS["player_characters"])

    # wand_hue must be None or an OpenCV hue value [0, 180)
    hue = settings.get("wand_hue")
    if hue is not None and (
        not _is_number(hue)
        or not (OPENCV_HUE_MIN <= float(hue) < OPENCV_HUE_MAX)
    ):
        settings["wand_hue"] = DEFAULTS["wand_hue"]

    hue_p1 = settings.get("wand_hue_p1")
    if hue_p1 is not None and (
        not _is_number(hue_p1)
        or not (OPENCV_HUE_MIN <= float(hue_p1) < OPENCV_HUE_MAX)
    ):
        settings["wand_hue_p1"] = DEFAULTS["wand_hue_p1"]

    # sat / val must be numeric OpenCV channel values
    for k in ("wand_sat_min", "wand_val_min", "wand_sat_min_p1", "wand_val_min_p1"):
        value = settings.get(k)
        if (
            not _is_number(value)
            or not (COLOR_CHANNEL_MIN <= float(value) <= COLOR_CHANNEL_MAX)
        ):
            settings[k] = DEFAULTS[k]

    # color_bgr must be a 3-element list/tuple of ints or None
    bgr = settings.get("wand_color_bgr")
    if bgr is not None:
        if not (isinstance(bgr, (list, tuple)) and len(bgr) == 3):
            settings["wand_color_bgr"] = DEFAULTS["wand_color_bgr"]
        elif not all(
            isinstance(c, int)
            and not isinstance(c, bool)
            and COLOR_CHANNEL_MIN <= c <= COLOR_CHANNEL_MAX
            for c in bgr
        ):
            settings["wand_color_bgr"] = DEFAULTS["wand_color_bgr"]


def load():
    """Return a settings dict.  Falls back to DEFAULTS if the file is missing
    or unreadable."""
    try:
        with open(SETTINGS_PATH, "r") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULTS)

    merged = dict(DEFAULTS)
    for key in DEFAULTS:
        if key in data:
            merged[key] = data[key]
    # Convert wand_color_bgr from list back to tuple
    if isinstance(merged.get("wand_color_bgr"), list):
        merged["wand_color_bgr"] = tuple(merged["wand_color_bgr"])
    if isinstance(merged.get("wand_color_bgr_p1"), list):
        merged["wand_color_bgr_p1"] = tuple(merged["wand_color_bgr_p1"])
    _validate(merged)
    return merged


def save(settings_dict):
    """Write a settings dict to disk."""
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    # Convert tuple to list for JSON serialization
    safe = dict(settings_dict)
    if isinstance(safe.get("wand_color_bgr"), tuple):
        safe["wand_color_bgr"] = list(safe["wand_color_bgr"])
    if isinstance(safe.get("wand_color_bgr_p1"), tuple):
        safe["wand_color_bgr_p1"] = list(safe["wand_color_bgr_p1"])
    # Only persist keys that are in DEFAULTS
    clean = {k: safe[k] for k in DEFAULTS if k in safe}
    with open(SETTINGS_PATH, "w") as f:
        json.dump(clean, f, indent=2)


def collect(cv_controller, game=None):
    """Build a settings dict from the current CV controller state."""
    wd = cv_controller.wand_detector
    settings = {
        "input_mode": cv_controller.input_mode,
        "wand_hue": wd.wand_hue,
        "wand_sat_min": wd.wand_sat_min,
        "wand_val_min": wd.wand_val_min,
        "wand_color_bgr": wd.wand_color_bgr,
    }
    tracks = getattr(cv_controller, "tracks", [])
    if len(tracks) > 1 and tracks[1].wand_color_calibrated:
        settings["wand_hue_p1"] = tracks[1].wand_hue
        settings["wand_sat_min_p1"] = tracks[1].wand_sat_min
        settings["wand_val_min_p1"] = tracks[1].wand_val_min
        settings["wand_color_bgr_p1"] = tracks[1].wand_color_bgr
    else:
        settings["wand_hue_p1"] = None
        settings["wand_sat_min_p1"] = 70
        settings["wand_val_min_p1"] = 70
        settings["wand_color_bgr_p1"] = None
    if game is not None and hasattr(game, "players"):
        settings["player_characters"] = [player.character_id for player in game.players[:2]]
    return settings


def restore(cv_controller, settings, game=None):
    """Apply saved settings to a CV controller."""
    input_mode = settings.get("input_mode")
    if input_mode == "wand" and settings.get("wand_hue") is not None:
        cv_controller.input_mode = "wand"
        wd = cv_controller.wand_detector
        wd.wand_hue = settings["wand_hue"]
        wd.wand_sat_min = settings["wand_sat_min"]
        wd.wand_val_min = settings["wand_val_min"]
        wd.wand_color_bgr = settings["wand_color_bgr"]
        tracks = getattr(cv_controller, "tracks", [])
        if len(tracks) > 0:
            tracks[0].wand_hue = wd.wand_hue
            tracks[0].wand_sat_min = wd.wand_sat_min
            tracks[0].wand_val_min = wd.wand_val_min
            tracks[0].wand_color_bgr = wd.wand_color_bgr
        if len(tracks) > 1 and settings.get("wand_hue_p1") is not None:
            tracks[1].wand_hue = settings["wand_hue_p1"]
            tracks[1].wand_sat_min = settings["wand_sat_min_p1"]
            tracks[1].wand_val_min = settings["wand_val_min_p1"]
            tracks[1].wand_color_bgr = settings["wand_color_bgr_p1"]
        cv_controller.refresh_status()

    if game is not None and hasattr(game, "set_player_character"):
        characters = settings.get("player_characters")
        if isinstance(characters, list) and len(characters) == 2:
            for index, character_id in enumerate(characters):
                if character_id in CHARACTERS:
                    game.set_player_character(index, character_id)
