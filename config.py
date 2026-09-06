WIDTH = 1280
HEIGHT = 720
FPS_FALLBACK = 60

# --- Duel mode hand -> player split ---------------------------------------
# In duel mode each player owns one half of the screen.  MediaPipe just returns
# up to two hands with no notion of *which* person they belong to, so two hands
# that land on the same half would otherwise both drive a single track and leave
# the other player dead.  These knobs control how strictly the two detected
# hands are separated onto opposite sides.
#
# DUEL_FORCE_SPLIT: when True and two hands are detected, force the leftmost hand
#   onto player 1 and the rightmost onto player 2 instead of trusting the raw
#   half-of-screen rule.
# DUEL_SPLIT_MIN_SEPARATION_FRAC: how far apart (as a fraction of frame width)
#   the two hands must be before they are forced onto opposite sides.  Lower =
#   stricter separation (split even hands that are close together); higher =
#   looser (only split clearly separated hands, otherwise treat them as one
#   person and keep the better-placed hand).
DUEL_FORCE_SPLIT = True
DUEL_SPLIT_MIN_SEPARATION_FRAC = 0.12
MAX_HP = 100.0
MAX_MANA = 100.0
MANA_REGEN_PER_SEC = 12.0
GLOBAL_CAST_COOLDOWN = 1.0
CV_TRACK_TIMEOUT = 0.65
CV_LOST_HOLD_TIME = 0.24
WAND_LOST_HOLD_TIME = 0.36
CV_PREDICT_HOLD_TIME = 0.14
CV_MAX_MISSED_FRAMES = 3
CV_PALM_CONFIDENCE = 0.78
CV_PALM_HOLD_TIME = 0.28
CV_PALM_MAX_CAST_SPEED = 360.0
WAND_MIN_SATURATION = 70
WAND_MIN_VALUE = 70
WAND_MIN_AREA = 8
WAND_MAX_AREA = 900
WAND_HUE_TOLERANCE = 12
WAND_CALIBRATION_RADIUS = 18
WAND_MIN_CALIBRATION_PIXELS = 18
HAND_MODEL_PATH = "hand_landmarker.task"
HAND_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"


THEME = {
    "bg": (16, 12, 20),
    "panel": (24, 18, 28),
    "panel_soft": (34, 26, 38),
    "panel_border": (78, 115, 156),
    "gold": (92, 157, 232),
    "gold_bright": (128, 196, 255),
    "text": (246, 239, 226),
    "muted": (194, 185, 178),
    "debug": (190, 220, 235),
    "hp": (66, 72, 218),
    "hp_trail": (44, 43, 126),
    "mana": (224, 170, 76),
    "shield": (245, 214, 128),
    "ready": (88, 150, 92),
    "blocked": (70, 64, 76),
    "no_mana": (72, 56, 104),
    "flash": (255, 255, 255),
    "danger": (70, 72, 238),
}


SPELLS = {
    "incendio": {
        "label": "INC",
        "full": "Incendio",
        "mana": 25,
        "cooldown": 3.0,
        "damage": 22,
        "speed": 760,
        "radius": 28,
        "color": (40, 130, 255),
        "kind": "projectile",
    },
    "stupefy": {
        "label": "STU",
        "full": "Stupefy",
        "mana": 35,
        "cooldown": 5.0,
        "damage": 16,
        "speed": 620,
        "radius": 22,
        "color": (70, 70, 255),
        "kind": "projectile",
        "silence": 1.0,
    },
    "glacius": {
        "label": "GLA",
        "full": "Glacius",
        "mana": 30,
        "cooldown": 4.6,
        "damage": 10,
        "speed": 500,
        "radius": 34,
        "color": (255, 210, 70),
        "kind": "projectile",
        "frozen": 2.0,
    },
    "protego": {
        "label": "PRO",
        "full": "Protego",
        "mana": 30,
        "cooldown": 6.0,
        "shield_value": 35,
        "duration": 3.0,
        "color": (255, 210, 120),
        "kind": "shield",
    },
    "lumos": {
        "label": "LUM",
        "full": "Lumos",
        "mana": 40,
        "cooldown": 8.0,
        "heal": 18,
        "channel": 1.2,
        "mana_regen_duration": 5.0,
        "mana_regen_mult": 4.0,
        "color": (230, 255, 255),
        "kind": "heal",
    },
    "overload": {
        "label": "OVR",
        "full": "Overload",
        "mana": 45,
        "cooldown": 0.0,
        "damage": 14,
        "speed": 560,
        "radius": 26,
        "color": (205, 120, 255),
        "kind": "projectile",
        "consume_all_mana": True,
        "self_recovery": 3.0,
        "buff_disable": 20.0,
    },
}


# (spell_a, spell_b): (winner_spell, loser_damage_mult, loser_vel_mult)
# Pairs not listed here cause both projectiles to be destroyed.
SPELL_INTERACTIONS = {
    ("incendio", "stupefy"): ("incendio", 0.75, 1.0),
    ("stupefy", "glacius"): ("stupefy", 0.75, 0.85),
    ("incendio", "glacius"): ("glacius", 0.80, 0.90),
}

SPELL_CLASH_SOUNDS = {
    ("incendio", "stupefy"): "clash_fire_lightning",
    ("stupefy", "glacius"): "clash_lightning_ice",
    ("incendio", "glacius"): "clash_ice_fire",
}

P1_KEYS = {
    ord("q"): "incendio",
    ord("w"): "stupefy",
    ord("e"): "glacius",
    ord("r"): "protego",
    ord("t"): "lumos",
}

P2_KEYS = {
    ord("u"): "incendio",
    ord("i"): "stupefy",
    ord("o"): "glacius",
    ord("p"): "protego",
    ord("l"): "lumos",
}
# Cyclic Stupefy remains diagnostic until the evaluation gate is satisfied.
CV_CYCLIC_STUPEFY_PRIMARY = False
