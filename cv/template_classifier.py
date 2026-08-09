from __future__ import annotations

import math
import json
from pathlib import Path
from typing import Optional

import numpy as np

TARGET_POINT_COUNT = 32
DTW_ACCEPT_THRESHOLD = 1.5
DEFAULT_DATA_TEMPLATE_PATH = Path("models/gesture_templates.json")


def _normalize_trajectory(points) -> Optional[np.ndarray]:
    if not points or len(points) < 2:
        return None

    pts = np.array(points, dtype=np.float32)
    if pts.ndim != 2 or pts.shape[1] < 2:
        return None

    resampled = _resample_arc_length(pts, TARGET_POINT_COUNT)
    if resampled is None:
        return None

    start = resampled[0].copy()
    translated = resampled - start

    max_span = float(max(
        float(np.max(np.abs(translated[:, 0]))),
        float(np.max(np.abs(translated[:, 1]))),
    ))
    if max_span < 1e-6:
        return translated / 1.0
    return translated / max_span


def _resample_arc_length(pts: np.ndarray, target_n: int) -> Optional[np.ndarray]:
    if len(pts) < 2:
        return None

    deltas = np.diff(pts, axis=0)
    seg_lengths = np.linalg.norm(deltas, axis=1)
    cumulative = np.concatenate([[0.0], np.cumsum(seg_lengths)])
    total = float(cumulative[-1])

    if total < 1e-6:
        n = len(pts)
        indices = np.linspace(0, n - 1, target_n, dtype=np.float32)
        floor = np.floor(indices).astype(int)
        ceil = np.clip(floor + 1, 0, n - 1)
        frac = indices - floor.astype(np.float32)
        result = pts[floor] * (1 - frac[:, None]) + pts[ceil] * frac[:, None]
        return result.astype(np.float32)

    sample_positions = np.linspace(0, total, target_n, dtype=np.float32)
    indices = np.searchsorted(cumulative, sample_positions, side="right")
    indices = np.clip(indices, 1, len(pts) - 1)

    prev_cum = cumulative[indices - 1]
    next_cum = cumulative[indices]
    segment_length = next_cum - prev_cum
    safe_length = np.where(segment_length < 1e-6, 1.0, segment_length)
    frac = (sample_positions - prev_cum) / safe_length
    frac = np.clip(frac, 0.0, 1.0)

    prev_pts = pts[indices - 1]
    next_pts = pts[indices]
    result = prev_pts * (1 - frac[:, None]) + next_pts * frac[:, None]
    return result.astype(np.float32)


def _dtw_distance(a: np.ndarray, b: np.ndarray) -> float:
    n = len(a)
    m = len(b)
    if n == 0 or m == 0:
        return float("inf")

    cost = np.zeros((n, m), dtype=np.float32)
    for i in range(n):
        for j in range(m):
            cost[i, j] = float(np.linalg.norm(a[i] - b[j]))

    dtw = np.full((n + 1, m + 1), float("inf"), dtype=np.float32)
    dtw[0, 0] = 0.0

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best_prev = min(dtw[i - 1, j], dtw[i, j - 1], dtw[i - 1, j - 1])
            dtw[i, j] = cost[i - 1, j - 1] + best_prev

    return float(dtw[n, m]) / float(n + m)


def _flip_x(points: np.ndarray) -> np.ndarray:
    flipped = points.copy()
    flipped[:, 0] *= -1.0
    return flipped


def _gen_incendio_template() -> np.ndarray:
    x = np.linspace(0, 1, TARGET_POINT_COUNT, dtype=np.float32)
    y = np.zeros(TARGET_POINT_COUNT, dtype=np.float32)
    y += np.random.RandomState(42).uniform(-0.02, 0.02, TARGET_POINT_COUNT).astype(np.float32)
    return np.column_stack([x, y])


def _gen_incendio_flipped_template() -> np.ndarray:
    x = np.linspace(0, -1, TARGET_POINT_COUNT, dtype=np.float32)
    y = np.zeros(TARGET_POINT_COUNT, dtype=np.float32)
    y += np.random.RandomState(42).uniform(-0.02, 0.02, TARGET_POINT_COUNT).astype(np.float32)
    return np.column_stack([x, y])


def _gen_glacius_template() -> np.ndarray:
    x = np.zeros(TARGET_POINT_COUNT, dtype=np.float32)
    x += np.random.RandomState(42).uniform(-0.03, 0.03, TARGET_POINT_COUNT).astype(np.float32)
    y = np.linspace(0, 1, TARGET_POINT_COUNT, dtype=np.float32)
    return np.column_stack([x, y])


def _gen_lumos_template() -> np.ndarray:
    x = np.zeros(TARGET_POINT_COUNT, dtype=np.float32)
    x += np.random.RandomState(42).uniform(-0.03, 0.03, TARGET_POINT_COUNT).astype(np.float32)
    y = np.linspace(0, -1, TARGET_POINT_COUNT, dtype=np.float32)
    return np.column_stack([x, y])


def _gen_stupefy_template() -> np.ndarray:
    n = TARGET_POINT_COUNT
    t = np.linspace(0, 2 * math.pi, n, dtype=np.float32)
    # Match _normalize_trajectory(): first point is translated to (0, 0)
    # and the largest span is scaled to 1.  A circle starting at its rightmost
    # point therefore ranges roughly x=[-1, 0], y=[-0.5, 0.5].
    x = (np.cos(t) - 1.0) / 2.0
    y = np.sin(t) / 2.0
    return np.column_stack([x, y]).astype(np.float32)


def _gen_overload_template() -> np.ndarray:
    n = TARGET_POINT_COUNT
    t = np.linspace(0, 1, n, dtype=np.float32)
    # A zigzag that moves upward while sweeping left and right.  The sinusoid
    # produces 4 direction reversals in x, matching the overload turn-count rule.
    x = np.sin(t * 4 * math.pi) * 0.9
    y = t * 1.0
    # Add tiny deterministic jitter so the template is not perfectly smooth.
    rng = np.random.RandomState(42)
    x += rng.uniform(-0.02, 0.02, n).astype(np.float32)
    y += rng.uniform(-0.02, 0.02, n).astype(np.float32)
    return np.column_stack([x, y])


TEMPLATES = {
    "incendio": _gen_incendio_template(),
    "incendio_flipped": _gen_incendio_flipped_template(),
    "glacius": _gen_glacius_template(),
    "lumos": _gen_lumos_template(),
    "stupefy": _gen_stupefy_template(),
    "overload": _gen_overload_template(),
}


def template_label_to_spell(label: str) -> str:
    return "stupefy" if label == "circle" else label


class DataTemplateClassifier:
    """DTW classifier backed by prototypes learned from Mode4 logs."""

    def __init__(self, template_path=None):
        self.template_path = Path(template_path) if template_path is not None else DEFAULT_DATA_TEMPLATE_PATH
        self._prototypes: dict[str, list[np.ndarray]] = {}
        self._thresholds: dict[str, float] = {}
        self.loaded = False
        self.load_error = ""
        self._load()

    @property
    def spells(self):
        return tuple(self._prototypes.keys())

    def _load(self):
        try:
            with open(self.template_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            self.load_error = "template model missing"
            return
        except (OSError, ValueError, TypeError) as exc:
            self.load_error = f"template model invalid: {exc}"
            return

        target_count = int(payload.get("target_point_count") or TARGET_POINT_COUNT)
        prototypes = payload.get("prototypes") or {}
        thresholds = payload.get("thresholds") or {}
        for spell, arrays in prototypes.items():
            mats = []
            for array in arrays or []:
                mat = np.asarray(array, dtype=np.float32)
                if mat.ndim == 2 and mat.shape == (target_count, 2):
                    mats.append(mat)
            if mats:
                self._prototypes[spell] = mats
                self._thresholds[spell] = float(thresholds.get(spell, DTW_ACCEPT_THRESHOLD))

        self.loaded = bool(self._prototypes)
        if not self.loaded and not self.load_error:
            self.load_error = "template model has no prototypes"

    def _best_for_spell(self, normalized: np.ndarray, spell: str) -> float:
        flipped = _flip_x(normalized)
        best = float("inf")
        for prototype in self._prototypes[spell]:
            best = min(
                best,
                _dtw_distance(normalized, prototype),
                _dtw_distance(flipped, prototype),
            )
        return best

    def classify(self, points, side) -> ClassificationResult:
        from cv.gesture_pipeline import ClassificationResult

        if not self.loaded:
            return ClassificationResult(
                spell=None,
                confidence=0.0,
                method="data_template",
                reason=self.load_error or "template model missing",
            )

        normalized = _normalize_trajectory(points)
        if normalized is None:
            return ClassificationResult(
                spell=None,
                confidence=0.0,
                method="data_template",
                reason="too few points to normalize",
            )

        best_spell = None
        best_distance = float("inf")
        best_threshold = 1.0
        for spell in self._prototypes:
            distance = self._best_for_spell(normalized, spell)
            threshold = max(self._thresholds.get(spell, DTW_ACCEPT_THRESHOLD), 1e-6)
            if distance / threshold < best_distance / best_threshold:
                best_spell = spell
                best_distance = distance
                best_threshold = threshold

        if best_spell is None:
            return ClassificationResult(
                spell=None,
                confidence=0.0,
                method="data_template",
                reason="no prototypes",
            )

        confidence = float(max(0.0, min(1.0, 1.0 - best_distance / best_threshold)))
        if best_distance > best_threshold:
            return ClassificationResult(
                spell=None,
                confidence=confidence,
                method="data_template",
                reason=f"best {best_spell} distance {best_distance:.3f}>{best_threshold:.3f}",
            )

        cast_spell = template_label_to_spell(best_spell)
        return ClassificationResult(
            spell=cast_spell,
            confidence=confidence,
            method="data_template",
            reason=f"{best_spell} distance {best_distance:.3f}<{best_threshold:.3f}",
        )
