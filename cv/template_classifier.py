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
    distances = _batch_dtw_distances(a, np.asarray([b], dtype=np.float32))
    return float(distances[0]) if len(distances) else float("inf")


def _batch_dtw_distances(query: np.ndarray, templates: np.ndarray) -> np.ndarray:
    """Return exact DTW distances for one query against many templates.

    Cells on one anti-diagonal have no dependencies on each other, so they can
    be evaluated together across both the diagonal and the template batch. This
    preserves the original recurrence while removing tens of thousands of
    Python/NumPy scalar operations from every runtime classification.
    """

    query = np.asarray(query, dtype=np.float32)
    templates = np.asarray(templates, dtype=np.float32)
    if query.ndim != 2 or len(query) == 0:
        return np.full((len(templates) if templates.ndim > 0 else 0,), float("inf"))
    if templates.ndim != 3 or templates.shape[0] == 0 or templates.shape[2] != query.shape[1]:
        return np.full((templates.shape[0] if templates.ndim == 3 else 0,), float("inf"))

    batch, template_n, _dims = templates.shape
    query_n = len(query)
    if template_n == 0:
        return np.full((batch,), float("inf"))

    cost = np.linalg.norm(
        query[None, :, None, :] - templates[:, None, :, :],
        axis=3,
    ).astype(np.float32)
    dtw = np.full((batch, query_n + 1, template_n + 1), float("inf"), dtype=np.float32)
    dtw[:, 0, 0] = 0.0

    for diagonal in range(2, query_n + template_n + 1):
        i_start = max(1, diagonal - template_n)
        i_stop = min(query_n, diagonal - 1)
        if i_start > i_stop:
            continue
        i = np.arange(i_start, i_stop + 1)
        j = diagonal - i
        best_previous = np.minimum(
            np.minimum(dtw[:, i - 1, j], dtw[:, i, j - 1]),
            dtw[:, i - 1, j - 1],
        )
        dtw[:, i, j] = cost[:, i - 1, j - 1] + best_previous

    return dtw[:, query_n, template_n].astype(np.float64) / float(query_n + template_n)


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
    """Non-parametric DTW matcher backed by representative Mode 4 trajectories."""

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
            self.load_error = "template pack missing"
            return
        except (OSError, ValueError, TypeError) as exc:
            self.load_error = f"template pack invalid: {exc}"
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
            self.load_error = "template pack has no prototypes"

    def _best_for_spell(self, normalized: np.ndarray, spell: str) -> float:
        prototypes = np.stack(self._prototypes[spell]).astype(np.float32)
        direct = _batch_dtw_distances(normalized, prototypes)
        flipped = _batch_dtw_distances(_flip_x(normalized), prototypes)
        return float(np.minimum(direct, flipped).min())

    def _best_distances(self, normalized: np.ndarray) -> dict[str, float]:
        labels = []
        prototypes = []
        for spell, spell_prototypes in self._prototypes.items():
            for prototype in spell_prototypes:
                labels.append(spell)
                prototypes.append(prototype)
        if not prototypes:
            return {}
        prototype_batch = np.stack(prototypes).astype(np.float32)
        direct = _batch_dtw_distances(normalized, prototype_batch)
        flipped = _batch_dtw_distances(_flip_x(normalized), prototype_batch)
        distances = np.minimum(direct, flipped)
        best = {spell: float("inf") for spell in self._prototypes}
        for spell, distance in zip(labels, distances):
            best[spell] = min(best[spell], float(distance))
        return best

    def classify(self, points, side) -> ClassificationResult:
        from cv.gesture_pipeline import ClassificationResult

        if not self.loaded:
            return ClassificationResult(
                spell=None,
                confidence=0.0,
                method="data_template",
                reason=self.load_error or "template pack missing",
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
        distances = self._best_distances(normalized)
        for spell in self._prototypes:
            distance = distances[spell]
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
