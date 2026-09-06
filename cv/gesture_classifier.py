from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np


# ---------------------------------------------------------------------------
# Classifier thresholds
# ---------------------------------------------------------------------------

MAX_FEATURE_POINTS = 80
MIN_POINTS_FOR_FEATURES = 6
MIN_PATH_LENGTH_TO_CLASSIFY = 55
MIN_RAW_POINTS_FOR_SHAPE_RULES = 14
MIN_PATH_LENGTH_FOR_SHAPE_RULES = 125
MAX_CONFIDENCE = 1.0

LUMOS_FAST_DY_MAX = -72
LUMOS_FAST_ABS_DX_MAX = 175
LUMOS_FAST_Y_SPAN_MIN = 58
LUMOS_FAST_PATH_MIN = 78
LUMOS_FAST_CONFIDENCE_BASE = 0.79
LUMOS_FAST_CONFIDENCE_OFFSET = 72
LUMOS_FAST_CONFIDENCE_SCALE = 210

LUMOS_SHAPE_DY_MAX = -125
LUMOS_SHAPE_ABS_DX_MAX = 160
LUMOS_SHAPE_Y_SPAN_MIN = 105
LUMOS_SHAPE_PATH_MIN = 145
LUMOS_SHAPE_CONFIDENCE_BASE = 0.78
LUMOS_SHAPE_CONFIDENCE_OFFSET = 125
LUMOS_SHAPE_CONFIDENCE_SCALE = 260

INCENDIO_FAST_OPPONENT_DX_MIN = 92
INCENDIO_FAST_Y_SPAN_MAX = 115
INCENDIO_FAST_STRAIGHTNESS_MIN = 0.68
INCENDIO_FAST_PATH_MIN = 88
INCENDIO_FAST_CONFIDENCE_BASE = 0.79
INCENDIO_FAST_CONFIDENCE_OFFSET = 92
INCENDIO_FAST_CONFIDENCE_SCALE = 260

INCENDIO_SHAPE_OPPONENT_DX_MIN = 150
INCENDIO_SHAPE_Y_SPAN_MAX = 105
INCENDIO_SHAPE_STRAIGHTNESS_MIN = 0.82
INCENDIO_SHAPE_PATH_MIN = 155
INCENDIO_SHAPE_CONFIDENCE_BASE = 0.80
INCENDIO_SHAPE_CONFIDENCE_OFFSET = 150
INCENDIO_SHAPE_CONFIDENCE_SCALE = 300

GLACIUS_FAST_DY_MIN = 92
GLACIUS_FAST_ABS_DX_MAX = 175
GLACIUS_FAST_Y_SPAN_MIN = 72
GLACIUS_FAST_PATH_MIN = 90
GLACIUS_FAST_STRAIGHTNESS_MIN = 0.48
GLACIUS_FAST_CONFIDENCE_BASE = 0.79
GLACIUS_FAST_CONFIDENCE_OFFSET = 92
GLACIUS_FAST_CONFIDENCE_SCALE = 230

GLACIUS_SHAPE_DY_MIN = 135
GLACIUS_SHAPE_ABS_DX_MAX = 165
GLACIUS_SHAPE_Y_SPAN_MIN = 120
GLACIUS_SHAPE_X_SPAN_MAX = 190
GLACIUS_SHAPE_PATH_MIN = 150
GLACIUS_SHAPE_STRAIGHTNESS_MIN = 0.55
GLACIUS_SHAPE_CONFIDENCE_BASE = 0.80
GLACIUS_SHAPE_CONFIDENCE_OFFSET = 125
GLACIUS_SHAPE_CONFIDENCE_SCALE = 260

STUPEFY_MIN_TURN_COUNT = 3
STUPEFY_PATH_MIN = 230
STUPEFY_X_SPAN_MIN = 100
STUPEFY_Y_SPAN_MIN = 70
STUPEFY_CONFIDENCE_BASE = 0.78
STUPEFY_TURN_CONFIDENCE_WEIGHT = 0.045
STUPEFY_SELECTION_BONUS = 0.12
NON_STUPEFY_ZIGZAG_PENALTY = 0.14

STUPEFY_CIRCLE_PATH_MIN = 220
STUPEFY_CIRCLE_SPAN_MIN = 80
STUPEFY_CIRCLE_CLOSURE_RATIO_MAX = 0.24
STUPEFY_CIRCLE_AREA_MIN = 4800
STUPEFY_CIRCLE_CIRCULARITY_MIN = 0.24
STUPEFY_CIRCLE_STRAIGHTNESS_MAX = 0.32
STUPEFY_CIRCLE_CONFIDENCE_BASE = 0.80

OVERLOAD_MIN_TURN_COUNT = 3
OVERLOAD_PATH_MIN = 230
OVERLOAD_X_SPAN_MIN = 100
OVERLOAD_Y_SPAN_MIN = 70
OVERLOAD_NET_ADVANCE_MIN = 70
OVERLOAD_ADVANCE_RATIO_MIN = 0.10
OVERLOAD_CONFIDENCE_BASE = 0.78
OVERLOAD_TURN_CONFIDENCE_WEIGHT = 0.045
OVERLOAD_SELECTION_BONUS = 0.16
NON_OVERLOAD_ZIGZAG_PENALTY = 0.14

TURN_DELTA_MIN = 7
MIN_USEFUL_DELTAS_FOR_TURNS = 4


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class GestureFeatures:
    """All computed features for a single gesture track."""

    points: np.ndarray          # last MAX_FEATURE_POINTS points, float32
    dx: float                   # end[0] - start[0]
    dy: float                   # end[1] - start[1]
    x_span: float               # max(x) - min(x)
    y_span: float               # max(y) - min(y)
    path_len: float             # total polyline length
    straightness: float         # |end-start| / path_len
    opponent_dx: float          # dx or -dx depending on side
    turn_count: int             # direction reversals
    area: float                 # |signed_polyline_area|
    raw_count: int              # len(original points list) before truncation


@dataclass
class GestureMatch:
    """Result of a single rule matcher."""

    spell: Optional[str]
    confidence: float
    reason: str


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------


def select_feature_points(points) -> np.ndarray:
    """Uniformly sample at most MAX_FEATURE_POINTS points across the whole gesture.

    Keeping only the trailing points made slow gestures lose their start: a
    deliberately drawn circle longer than MAX_FEATURE_POINTS frames was turned
    into an arc, which broke closure/area features and the cyclic gate, and
    zigzags lost early turns.  Downsampling keeps the full time span, and the
    first and last points are always preserved so end-point features stay honest.
    """
    raw = np.asarray(points, dtype=np.float32)
    if len(raw) <= MAX_FEATURE_POINTS:
        return raw
    positions = np.linspace(0, len(raw) - 1, MAX_FEATURE_POINTS)
    indices = np.unique(np.rint(positions).astype(np.int64))
    return raw[indices]


def extract_gesture_features(points, side) -> Optional[GestureFeatures]:
    """Compute all features from a point list. Returns None if too few points."""
    if len(points) < MIN_POINTS_FOR_FEATURES:
        return None

    pts = select_feature_points(points)
    deltas = np.diff(pts, axis=0)
    path_len = float(np.linalg.norm(deltas, axis=1).sum())
    start = pts[0]
    end = pts[-1]
    dx = float(end[0] - start[0])
    dy = float(end[1] - start[1])
    x_span = float(pts[:, 0].max() - pts[:, 0].min())
    y_span = float(pts[:, 1].max() - pts[:, 1].min())
    straightness = float(np.linalg.norm(end - start) / max(path_len, 1.0))
    opponent_dx = dx if side == "left" else -dx
    turn_count = count_direction_turns(pts)
    area = abs(signed_polyline_area(pts))

    return GestureFeatures(
        points=pts,
        dx=dx,
        dy=dy,
        x_span=x_span,
        y_span=y_span,
        path_len=path_len,
        straightness=straightness,
        opponent_dx=opponent_dx,
        turn_count=turn_count,
        area=area,
        raw_count=len(points),
    )


# ---------------------------------------------------------------------------
# Individual rule matchers
# ---------------------------------------------------------------------------


def match_lumos(f: GestureFeatures) -> Optional[GestureMatch]:
    """Upward flick -> Lumos."""
    if (
        f.dy < LUMOS_FAST_DY_MAX
        and abs(f.dx) < LUMOS_FAST_ABS_DX_MAX
        and f.y_span > LUMOS_FAST_Y_SPAN_MIN
        and f.path_len > LUMOS_FAST_PATH_MIN
    ):
        confidence = min(
            MAX_CONFIDENCE,
            LUMOS_FAST_CONFIDENCE_BASE
            + (-f.dy - LUMOS_FAST_CONFIDENCE_OFFSET) / LUMOS_FAST_CONFIDENCE_SCALE,
        )
        return GestureMatch("lumos", confidence, "fast upward")

    if f.raw_count >= MIN_RAW_POINTS_FOR_SHAPE_RULES and f.path_len >= MIN_PATH_LENGTH_FOR_SHAPE_RULES:
        if (
            f.dy < LUMOS_SHAPE_DY_MAX
            and abs(f.dx) < LUMOS_SHAPE_ABS_DX_MAX
            and f.y_span > LUMOS_SHAPE_Y_SPAN_MIN
            and f.path_len > LUMOS_SHAPE_PATH_MIN
        ):
            confidence = min(
                MAX_CONFIDENCE,
                LUMOS_SHAPE_CONFIDENCE_BASE
                + (-f.dy - LUMOS_SHAPE_CONFIDENCE_OFFSET) / LUMOS_SHAPE_CONFIDENCE_SCALE,
            )
            return GestureMatch("lumos", confidence, "shape upward")

    return None


def match_incendio(f: GestureFeatures) -> Optional[GestureMatch]:
    """Horizontal push toward opponent -> Incendio."""
    if (
        f.opponent_dx > INCENDIO_FAST_OPPONENT_DX_MIN
        and f.y_span < INCENDIO_FAST_Y_SPAN_MAX
        and f.straightness > INCENDIO_FAST_STRAIGHTNESS_MIN
        and f.path_len > INCENDIO_FAST_PATH_MIN
    ):
        confidence = min(
            MAX_CONFIDENCE,
            INCENDIO_FAST_CONFIDENCE_BASE
            + (f.opponent_dx - INCENDIO_FAST_CONFIDENCE_OFFSET) / INCENDIO_FAST_CONFIDENCE_SCALE,
        )
        return GestureMatch("incendio", confidence, "fast horizontal")

    if f.raw_count >= MIN_RAW_POINTS_FOR_SHAPE_RULES and f.path_len >= MIN_PATH_LENGTH_FOR_SHAPE_RULES:
        if (
            f.opponent_dx > INCENDIO_SHAPE_OPPONENT_DX_MIN
            and f.y_span < INCENDIO_SHAPE_Y_SPAN_MAX
            and f.straightness > INCENDIO_SHAPE_STRAIGHTNESS_MIN
            and f.path_len > INCENDIO_SHAPE_PATH_MIN
        ):
            confidence = min(
                MAX_CONFIDENCE,
                INCENDIO_SHAPE_CONFIDENCE_BASE
                + (f.opponent_dx - INCENDIO_SHAPE_CONFIDENCE_OFFSET) / INCENDIO_SHAPE_CONFIDENCE_SCALE,
            )
            return GestureMatch("incendio", confidence, "shape horizontal")

    return None


def match_glacius(f: GestureFeatures) -> Optional[GestureMatch]:
    """Downward slash -> Glacius."""
    if (
        f.dy > GLACIUS_FAST_DY_MIN
        and abs(f.dx) < GLACIUS_FAST_ABS_DX_MAX
        and f.y_span > GLACIUS_FAST_Y_SPAN_MIN
        and f.path_len > GLACIUS_FAST_PATH_MIN
        and f.straightness > GLACIUS_FAST_STRAIGHTNESS_MIN
    ):
        confidence = min(
            MAX_CONFIDENCE,
            GLACIUS_FAST_CONFIDENCE_BASE
            + (f.dy - GLACIUS_FAST_CONFIDENCE_OFFSET) / GLACIUS_FAST_CONFIDENCE_SCALE,
        )
        return GestureMatch("glacius", confidence, "fast downward")

    if f.raw_count >= MIN_RAW_POINTS_FOR_SHAPE_RULES and f.path_len >= MIN_PATH_LENGTH_FOR_SHAPE_RULES:
        if (
            f.dy > GLACIUS_SHAPE_DY_MIN
            and abs(f.dx) < GLACIUS_SHAPE_ABS_DX_MAX
            and f.y_span > GLACIUS_SHAPE_Y_SPAN_MIN
            and f.x_span < GLACIUS_SHAPE_X_SPAN_MAX
            and f.path_len > GLACIUS_SHAPE_PATH_MIN
            and f.straightness > GLACIUS_SHAPE_STRAIGHTNESS_MIN
        ):
            confidence = min(
                MAX_CONFIDENCE,
                GLACIUS_SHAPE_CONFIDENCE_BASE
                + (f.dy - GLACIUS_SHAPE_CONFIDENCE_OFFSET) / GLACIUS_SHAPE_CONFIDENCE_SCALE,
            )
            return GestureMatch("glacius", confidence, "shape downward")

    return None


def match_stupefy(f: GestureFeatures) -> Optional[GestureMatch]:
    """Closed loop -> Stupefy."""
    if f.raw_count < MIN_RAW_POINTS_FOR_SHAPE_RULES or f.path_len < MIN_PATH_LENGTH_FOR_SHAPE_RULES:
        return None

    closure = float(np.linalg.norm(f.points[-1] - f.points[0]))
    closure_ratio = closure / max(f.path_len, 1.0)
    circularity = float(4.0 * np.pi * f.area / max(f.path_len * f.path_len, 1.0))
    if (
        f.path_len > STUPEFY_CIRCLE_PATH_MIN
        and f.x_span > STUPEFY_CIRCLE_SPAN_MIN
        and f.y_span > STUPEFY_CIRCLE_SPAN_MIN
        and closure_ratio < STUPEFY_CIRCLE_CLOSURE_RATIO_MAX
        and f.area > STUPEFY_CIRCLE_AREA_MIN
        and circularity > STUPEFY_CIRCLE_CIRCULARITY_MIN
        and f.straightness < STUPEFY_CIRCLE_STRAIGHTNESS_MAX
    ):
        confidence = min(
            MAX_CONFIDENCE,
            STUPEFY_CIRCLE_CONFIDENCE_BASE
            + (STUPEFY_CIRCLE_CLOSURE_RATIO_MAX - closure_ratio) * 0.45
            + min(0.12, circularity * 0.08),
        )
        return GestureMatch("stupefy", confidence, "circle")
    return None


def match_overload(f: GestureFeatures) -> Optional[GestureMatch]:
    """Multi-zigzag lightning -> Overload."""
    if f.raw_count < MIN_RAW_POINTS_FOR_SHAPE_RULES or f.path_len < MIN_PATH_LENGTH_FOR_SHAPE_RULES:
        return None
    net_advance = float(np.hypot(f.dx, f.dy))
    advance_ratio = net_advance / max(f.path_len, 1.0)
    if (
        f.turn_count >= OVERLOAD_MIN_TURN_COUNT
        and f.path_len > OVERLOAD_PATH_MIN
        and f.x_span > OVERLOAD_X_SPAN_MIN
        and f.y_span > OVERLOAD_Y_SPAN_MIN
        and net_advance > OVERLOAD_NET_ADVANCE_MIN
        and advance_ratio > OVERLOAD_ADVANCE_RATIO_MIN
    ):
        confidence = min(
            MAX_CONFIDENCE,
            OVERLOAD_CONFIDENCE_BASE + f.turn_count * OVERLOAD_TURN_CONFIDENCE_WEIGHT,
        )
        return GestureMatch("overload", confidence, "zigzag")
    return None


# ---------------------------------------------------------------------------
# Debug / diagnosis
# ---------------------------------------------------------------------------


@dataclass
class GestureDebug:
    """Structured explanation for why a gesture was or wasn't recognised."""

    features: Optional[GestureFeatures]
    prediction: Optional[str]
    confidence: float
    best_match: Optional[GestureMatch]
    rejected_reasons: List[str]
    message: str


def _rejection_reasons(f: GestureFeatures) -> List[str]:
    """Build human-readable rejection reasons for every matcher that did NOT fire.

    Each spell reports ALL failing conditions, not just the first one.
    """
    reasons = []

    # --- Lumos ---------------------------------------------------------------
    lumos_fails = []
    if not (f.dy < LUMOS_FAST_DY_MAX):
        lumos_fails.append(f"dy={f.dy:.0f} need<{LUMOS_FAST_DY_MAX}")
    if not (abs(f.dx) < LUMOS_FAST_ABS_DX_MAX):
        lumos_fails.append(f"|dx|={abs(f.dx):.0f} need<{LUMOS_FAST_ABS_DX_MAX}")
    if not (f.y_span > LUMOS_FAST_Y_SPAN_MIN):
        lumos_fails.append(f"y_span={f.y_span:.0f} need>{LUMOS_FAST_Y_SPAN_MIN}")
    if not (f.path_len > LUMOS_FAST_PATH_MIN):
        lumos_fails.append(f"path_len={f.path_len:.0f} need>{LUMOS_FAST_PATH_MIN}")
    if lumos_fails:
        reasons.append("Lumos: " + "; ".join(lumos_fails))

    # --- Incendio ------------------------------------------------------------
    inc_fails = []
    if not (f.opponent_dx > INCENDIO_FAST_OPPONENT_DX_MIN):
        inc_fails.append(f"opponent_dx={f.opponent_dx:.0f} need>{INCENDIO_FAST_OPPONENT_DX_MIN}")
    if not (f.y_span < INCENDIO_FAST_Y_SPAN_MAX):
        inc_fails.append(f"y_span={f.y_span:.0f} need<{INCENDIO_FAST_Y_SPAN_MAX}")
    if not (f.straightness > INCENDIO_FAST_STRAIGHTNESS_MIN):
        inc_fails.append(f"straightness={f.straightness:.2f} need>{INCENDIO_FAST_STRAIGHTNESS_MIN}")
    if not (f.path_len > INCENDIO_FAST_PATH_MIN):
        inc_fails.append(f"path_len={f.path_len:.0f} need>{INCENDIO_FAST_PATH_MIN}")
    if inc_fails:
        reasons.append("Incendio: " + "; ".join(inc_fails))

    # --- Glacius -------------------------------------------------------------
    gla_fails = []
    if not (f.dy > GLACIUS_FAST_DY_MIN):
        gla_fails.append(f"dy={f.dy:.0f} need>{GLACIUS_FAST_DY_MIN}")
    if not (abs(f.dx) < GLACIUS_FAST_ABS_DX_MAX):
        gla_fails.append(f"|dx|={abs(f.dx):.0f} need<{GLACIUS_FAST_ABS_DX_MAX}")
    if not (f.y_span > GLACIUS_FAST_Y_SPAN_MIN):
        gla_fails.append(f"y_span={f.y_span:.0f} need>{GLACIUS_FAST_Y_SPAN_MIN}")
    if not (f.path_len > GLACIUS_FAST_PATH_MIN):
        gla_fails.append(f"path_len={f.path_len:.0f} need>{GLACIUS_FAST_PATH_MIN}")
    if not (f.straightness > GLACIUS_FAST_STRAIGHTNESS_MIN):
        gla_fails.append(f"straightness={f.straightness:.2f} need>{GLACIUS_FAST_STRAIGHTNESS_MIN}")
    if gla_fails:
        reasons.append("Glacius: " + "; ".join(gla_fails))

    # --- Stupefy circle ------------------------------------------------------
    stu_fails = []
    if f.raw_count < MIN_RAW_POINTS_FOR_SHAPE_RULES:
        stu_fails.append(f"raw_count={f.raw_count} need>={MIN_RAW_POINTS_FOR_SHAPE_RULES}")
    if f.path_len < MIN_PATH_LENGTH_FOR_SHAPE_RULES:
        stu_fails.append(f"path_len={f.path_len:.0f} need>={MIN_PATH_LENGTH_FOR_SHAPE_RULES}")
    closure = float(np.linalg.norm(f.points[-1] - f.points[0]))
    closure_ratio = closure / max(f.path_len, 1.0)
    circularity = float(4.0 * np.pi * f.area / max(f.path_len * f.path_len, 1.0))
    if not (f.path_len > STUPEFY_CIRCLE_PATH_MIN):
        stu_fails.append(f"path_len={f.path_len:.0f} need>{STUPEFY_CIRCLE_PATH_MIN}")
    if not (f.x_span > STUPEFY_CIRCLE_SPAN_MIN):
        stu_fails.append(f"x_span={f.x_span:.0f} need>{STUPEFY_CIRCLE_SPAN_MIN}")
    if not (f.y_span > STUPEFY_CIRCLE_SPAN_MIN):
        stu_fails.append(f"y_span={f.y_span:.0f} need>{STUPEFY_CIRCLE_SPAN_MIN}")
    if not (closure_ratio < STUPEFY_CIRCLE_CLOSURE_RATIO_MAX):
        stu_fails.append(f"closure={closure_ratio:.2f} need<{STUPEFY_CIRCLE_CLOSURE_RATIO_MAX}")
    if not (f.area > STUPEFY_CIRCLE_AREA_MIN):
        stu_fails.append(f"area={f.area:.0f} need>{STUPEFY_CIRCLE_AREA_MIN}")
    if not (circularity > STUPEFY_CIRCLE_CIRCULARITY_MIN):
        stu_fails.append(f"round={circularity:.2f} need>{STUPEFY_CIRCLE_CIRCULARITY_MIN}")
    if stu_fails:
        reasons.append("Stupefy: " + "; ".join(stu_fails))

    # --- Overload zigzag -----------------------------------------------------
    ovr_fails = []
    if f.raw_count < MIN_RAW_POINTS_FOR_SHAPE_RULES:
        ovr_fails.append(f"raw_count={f.raw_count} need>={MIN_RAW_POINTS_FOR_SHAPE_RULES}")
    if f.path_len < MIN_PATH_LENGTH_FOR_SHAPE_RULES:
        ovr_fails.append(f"path_len={f.path_len:.0f} need>={MIN_PATH_LENGTH_FOR_SHAPE_RULES}")
    if f.turn_count < OVERLOAD_MIN_TURN_COUNT:
        ovr_fails.append(f"turns={f.turn_count} need>={OVERLOAD_MIN_TURN_COUNT}")
    if not (f.path_len > OVERLOAD_PATH_MIN):
        ovr_fails.append(f"path_len={f.path_len:.0f} need>{OVERLOAD_PATH_MIN}")
    if not (f.x_span > OVERLOAD_X_SPAN_MIN):
        ovr_fails.append(f"x_span={f.x_span:.0f} need>{OVERLOAD_X_SPAN_MIN}")
    if not (f.y_span > OVERLOAD_Y_SPAN_MIN):
        ovr_fails.append(f"y_span={f.y_span:.0f} need>{OVERLOAD_Y_SPAN_MIN}")
    overload_advance = float(np.hypot(f.dx, f.dy))
    overload_advance_ratio = overload_advance / max(f.path_len, 1.0)
    if not (overload_advance > OVERLOAD_NET_ADVANCE_MIN):
        ovr_fails.append(f"advance={overload_advance:.0f} need>{OVERLOAD_NET_ADVANCE_MIN}")
    if not (overload_advance_ratio > OVERLOAD_ADVANCE_RATIO_MIN):
        ovr_fails.append(f"advance_ratio={overload_advance_ratio:.2f} need>{OVERLOAD_ADVANCE_RATIO_MIN}")
    if ovr_fails:
        reasons.append("Overload: " + "; ".join(ovr_fails))

    return reasons


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_cv_gesture(points, side):
    """Classify a gesture track into (spell_name_or_None, confidence_float)."""
    features = extract_gesture_features(points, side)
    if features is None:
        return None, 0.0
    if features.path_len < MIN_PATH_LENGTH_TO_CLASSIFY:
        return None, 0.0

    match = select_best_match(features)
    if match is not None:
        return match.spell, match.confidence
    return None, 0.0


def explain_cv_gesture(points, side) -> Optional[GestureMatch]:
    """Like classify_cv_gesture, but includes the matcher reason."""
    features = extract_gesture_features(points, side)
    if features is None:
        return None
    if features.path_len < MIN_PATH_LENGTH_TO_CLASSIFY:
        return GestureMatch(None, 0.0, "path too short")

    match = select_best_match(features)
    if match is not None:
        return match
    return GestureMatch(None, 0.0, "no match")


def diagnose_cv_gesture(points, side) -> Optional[GestureDebug]:
    """Return a structured explanation of why a gesture was or wasn't recognised.

    Includes feature values, rejection reasons for every matcher that failed,
    and a compact UI-friendly message.
    """
    features = extract_gesture_features(points, side)
    if features is None:
        return GestureDebug(
            features=None,
            prediction=None,
            confidence=0.0,
            best_match=None,
            rejected_reasons=["too few points"],
            message="too few points",
        )

    if features.path_len < MIN_PATH_LENGTH_TO_CLASSIFY:
        return GestureDebug(
            features=features,
            prediction=None,
            confidence=0.0,
            best_match=None,
            rejected_reasons=[f"path too short {features.path_len:.0f}<{MIN_PATH_LENGTH_TO_CLASSIFY}"],
            message=f"short {features.path_len:.0f}/{MIN_PATH_LENGTH_TO_CLASSIFY}",
        )

    match = select_best_match(features)
    if match is not None:
        return GestureDebug(
            features=features,
            prediction=match.spell,
            confidence=match.confidence,
            best_match=match,
            rejected_reasons=[],
            message=f"{match.spell} {match.confidence:.2f}",
        )

    rejects = _rejection_reasons(features)
    return GestureDebug(
        features=features,
        prediction=None,
        confidence=0.0,
        best_match=None,
        rejected_reasons=rejects,
        message=f"no match ({features.path_len:.0f}px, {features.turn_count}t)",
    )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def cv_path_length(points):
    if len(points) < 2:
        return 0.0
    pts = np.array(points, dtype=np.float32)
    return float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())


def collect_gesture_matches(features: GestureFeatures) -> List[GestureMatch]:
    """Return every spell matcher that accepts the trajectory."""
    matches = []
    for matcher in [match_lumos, match_incendio, match_glacius, match_stupefy, match_overload]:
        match = matcher(features)
        if match is not None:
            matches.append(match)
    return matches


def select_best_match(features: GestureFeatures) -> Optional[GestureMatch]:
    """Pick the strongest candidate after every spell has had a chance to match."""
    matches = collect_gesture_matches(features)
    if not matches:
        return None
    return max(
        matches,
        key=lambda match: (
            score_gesture_match(match, features),
            match.confidence,
            match.spell in ("overload", "stupefy"),
        ),
    )


def score_gesture_match(match: GestureMatch, features: GestureFeatures) -> float:
    """Selection score used to keep zigzags from being stolen by line gestures."""
    score = match.confidence
    overload_advance = float(np.hypot(features.dx, features.dy))
    has_overload_structure = (
        features.turn_count >= OVERLOAD_MIN_TURN_COUNT
        and features.path_len > OVERLOAD_PATH_MIN
        and features.x_span > OVERLOAD_X_SPAN_MIN
        and features.y_span > OVERLOAD_Y_SPAN_MIN
        and overload_advance > OVERLOAD_NET_ADVANCE_MIN
        and overload_advance / max(features.path_len, 1.0) > OVERLOAD_ADVANCE_RATIO_MIN
    )
    if match.spell == "overload":
        extra_turns = max(0, features.turn_count - OVERLOAD_MIN_TURN_COUNT)
        return score + OVERLOAD_SELECTION_BONUS + extra_turns * OVERLOAD_TURN_CONFIDENCE_WEIGHT
    if match.spell == "stupefy":
        return score + STUPEFY_SELECTION_BONUS
    if has_overload_structure:
        return score - NON_OVERLOAD_ZIGZAG_PENALTY
    return score


def count_direction_turns(points):
    if len(points) < 5:
        return 0
    deltas = np.diff(points, axis=0)
    useful = deltas[np.linalg.norm(deltas, axis=1) > TURN_DELTA_MIN]
    if len(useful) < MIN_USEFUL_DELTAS_FOR_TURNS:
        return 0
    return max(count_axis_turns(useful[:, 0]), count_axis_turns(useful[:, 1]))


def count_axis_turns(values):
    signs = np.sign(values)
    signs = signs[signs != 0]
    if len(signs) < 2:
        return 0
    return int(np.sum(signs[1:] * signs[:-1] < 0))


def signed_polyline_area(points):
    if len(points) < 3:
        return 0.0
    x = points[:, 0]
    y = points[:, 1]
    return float(0.5 * np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))
