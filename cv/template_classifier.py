from __future__ import annotations

import math
import json
from pathlib import Path
from typing import Optional

import numpy as np
from cv.trajectory import advances_toward_opponent, validated_points

TARGET_POINT_COUNT = 32
DTW_ACCEPT_THRESHOLD = 1.5
DEFAULT_MARGIN_THRESHOLD = 0.05
DEFAULT_DATA_TEMPLATE_PATH = Path("models/gesture_templates.json")
DEFAULT_CYCLIC_SHADOW_TEMPLATE_PATH = Path("models/gesture_templates_shadow_v2.json")
DATA_TEMPLATE_ALGORITHM_VERSION = "data-template-dtw-v2-structured"
CYCLIC_TEMPLATE_ALGORITHM_VERSION = "data-template-dtw-v2-cyclic-stupefy"


def _normalize_trajectory(points) -> Optional[np.ndarray]:
    pts = validated_points(points)
    if pts is None:
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


def _reanchor_normalized_trajectory(points: np.ndarray) -> np.ndarray:
    """Re-anchor an already normalized trajectory after a cyclic roll."""
    anchored = np.asarray(points, dtype=np.float32) - np.asarray(points[0], dtype=np.float32)
    max_span = float(np.max(np.abs(anchored))) if anchored.size else 0.0
    if max_span > 1e-6:
        anchored = anchored / max_span
    return anchored.astype(np.float32)


def _cyclic_dtw_best(
    query: np.ndarray,
    prototypes: np.ndarray,
    *,
    allow_reverse: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Best distance, shift, and reverse flag for each closed prototype."""
    prototypes = np.asarray(prototypes, dtype=np.float32)
    if prototypes.ndim != 3 or len(prototypes) == 0:
        return (
            np.asarray([], dtype=np.float64),
            np.asarray([], dtype=np.int32),
            np.asarray([], dtype=bool),
        )

    variants = []
    owners = []
    shifts = []
    reversals = []
    for prototype_index, prototype in enumerate(prototypes):
        orientations = [(prototype, False)]
        if allow_reverse:
            orientations.append((prototype[::-1], True))
        for oriented, reversed_sequence in orientations:
            for shift in range(len(oriented)):
                rolled = np.roll(oriented, -shift, axis=0)
                variants.append(_reanchor_normalized_trajectory(rolled))
                owners.append(prototype_index)
                shifts.append(shift)
                reversals.append(reversed_sequence)

    variant_batch = np.stack(variants).astype(np.float32)
    direct = _batch_dtw_distances(query, variant_batch)
    mirrored = _batch_dtw_distances(_flip_x(query), variant_batch)
    distances = np.minimum(direct, mirrored)
    best_distance = np.full((len(prototypes),), float("inf"), dtype=np.float64)
    best_shift = np.zeros((len(prototypes),), dtype=np.int32)
    best_reversed = np.zeros((len(prototypes),), dtype=bool)
    for index, distance in enumerate(distances):
        owner = owners[index]
        if distance < best_distance[owner]:
            best_distance[owner] = float(distance)
            best_shift[owner] = shifts[index]
            best_reversed[owner] = reversals[index]
    return best_distance, best_shift, best_reversed


def closed_trajectory_gate(points) -> dict:
    """Use the existing development thresholds as the cyclic-DTW safety gate."""
    from cv.gesture_classifier import (
        MIN_PATH_LENGTH_FOR_SHAPE_RULES,
        MIN_RAW_POINTS_FOR_SHAPE_RULES,
        STUPEFY_CIRCLE_AREA_MIN,
        STUPEFY_CIRCLE_CIRCULARITY_MIN,
        STUPEFY_CIRCLE_CLOSURE_RATIO_MAX,
        STUPEFY_CIRCLE_PATH_MIN,
        STUPEFY_CIRCLE_SPAN_MIN,
        extract_gesture_features,
    )

    features = extract_gesture_features(points, "left")
    if features is None:
        return {"passed": False, "reasons": ["too_few_points"]}
    closure = float(np.linalg.norm(features.points[-1] - features.points[0]))
    closure_ratio = closure / max(features.path_len, 1.0)
    circularity = float(4.0 * math.pi * features.area / max(features.path_len ** 2, 1.0))
    checks = {
        "raw_points": features.raw_count >= MIN_RAW_POINTS_FOR_SHAPE_RULES,
        "path_length": (
            features.path_len >= MIN_PATH_LENGTH_FOR_SHAPE_RULES
            and features.path_len > STUPEFY_CIRCLE_PATH_MIN
        ),
        "closure_ratio": closure_ratio < STUPEFY_CIRCLE_CLOSURE_RATIO_MAX,
        "x_span": features.x_span > STUPEFY_CIRCLE_SPAN_MIN,
        "y_span": features.y_span > STUPEFY_CIRCLE_SPAN_MIN,
        "area": features.area > STUPEFY_CIRCLE_AREA_MIN,
        "circularity": circularity > STUPEFY_CIRCLE_CIRCULARITY_MIN,
    }
    return {
        "passed": all(checks.values()),
        "reasons": [name for name, passed in checks.items() if not passed],
        "raw_points": features.raw_count,
        "path_length": features.path_len,
        "closure_ratio": closure_ratio,
        "x_span": features.x_span,
        "y_span": features.y_span,
        "area": features.area,
        "circularity": circularity,
    }


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

    def __init__(
        self,
        template_path=None,
        *,
        template_payload: Optional[dict] = None,
        enable_cyclic_stupefy: bool = False,
        reject_ambiguous: bool = False,
        allow_cyclic_reverse: Optional[bool] = None,
        cyclic_stupefy_only: bool = False,
    ):
        self.template_path = Path(template_path) if template_path is not None else DEFAULT_DATA_TEMPLATE_PATH
        self._prototypes: dict[str, list[np.ndarray]] = {}
        self._prototype_ids: dict[str, list[str]] = {}
        self._thresholds: dict[str, float] = {}
        self._margin_thresholds: dict[str, float] = {}
        self.enable_cyclic_stupefy = bool(enable_cyclic_stupefy)
        self.reject_ambiguous = bool(reject_ambiguous)
        self.cyclic_stupefy_only = bool(cyclic_stupefy_only)
        self.allow_cyclic_reverse = allow_cyclic_reverse
        self.template_payload = template_payload
        self.template_pack_version = None
        self.loaded = False
        self.load_error = ""
        try:
            self._load()
        except (TypeError, ValueError, OverflowError, AttributeError) as exc:
            self._prototypes.clear()
            self._prototype_ids.clear()
            self._thresholds.clear()
            self._margin_thresholds.clear()
            self.loaded = False
            self.load_error = f"template pack invalid: {exc}"

    @property
    def spells(self):
        return tuple(self._prototypes.keys())

    def _load(self):
        payload = self.template_payload
        if payload is None:
            try:
                with open(self.template_path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except FileNotFoundError:
                self.load_error = "template pack missing"
                return
            except (OSError, ValueError, TypeError) as exc:
                self.load_error = f"template pack invalid: {exc}"
                return
        if not isinstance(payload, dict):
            self.load_error = "template pack invalid: root must be an object"
            return

        target_count = payload.get("target_point_count", TARGET_POINT_COUNT)
        if type(target_count) is not int or target_count != TARGET_POINT_COUNT:
            raise ValueError(f"target_point_count must be {TARGET_POINT_COUNT}")
        self.template_pack_version = payload.get("version")
        prototypes = payload.get("prototypes") or {}
        thresholds = payload.get("thresholds") or {}
        margin_thresholds = payload.get("margin_thresholds") or {}
        cyclic_config = payload.get("cyclic_dtw") or {}
        if not all(isinstance(value, dict) for value in
                   (prototypes, thresholds, margin_thresholds, cyclic_config)):
            raise ValueError("prototype and threshold sections must be objects")
        if self.allow_cyclic_reverse is None:
            self.allow_cyclic_reverse = bool(cyclic_config.get("allow_reverse", False))
        for spell, arrays in prototypes.items():
            if spell not in ("incendio", "stupefy", "circle", "glacius", "lumos", "overload"):
                raise ValueError(f"unsupported template label: {spell}")
            if not isinstance(arrays, list):
                raise ValueError("prototypes must be lists")
            mats = []
            prototype_ids = []
            for index, item in enumerate(arrays or []):
                if isinstance(item, dict):
                    array = item.get("points") or item.get("trajectory")
                    prototype_id = str(item.get("prototype_id") or item.get("id") or f"{spell}:v2:{index}")
                else:
                    array = item
                    prototype_id = f"{spell}:legacy:{index}"
                mat = validated_points(array)
                if mat is None or mat.shape != (target_count, 2):
                    raise ValueError(f"invalid prototype for {spell}")
                mats.append(mat)
                prototype_ids.append(prototype_id)
            if mats:
                self._prototypes[spell] = mats
                self._prototype_ids[spell] = prototype_ids
                self._thresholds[spell] = float(thresholds.get(spell, DTW_ACCEPT_THRESHOLD))
                self._margin_thresholds[spell] = float(
                    margin_thresholds.get(spell, DEFAULT_MARGIN_THRESHOLD)
                )
                if not math.isfinite(self._thresholds[spell]) or self._thresholds[spell] <= 0:
                    raise ValueError("distance thresholds must be finite and positive")
                if not math.isfinite(self._margin_thresholds[spell]) or self._margin_thresholds[spell] < 0:
                    raise ValueError("margin thresholds must be finite and non-negative")

        self.loaded = bool(self._prototypes)
        if not self.loaded and not self.load_error:
            self.load_error = "template pack has no prototypes"

    def _best_for_spell(self, normalized: np.ndarray, spell: str) -> float:
        prototypes = np.stack(self._prototypes[spell]).astype(np.float32)
        direct = _batch_dtw_distances(normalized, prototypes)
        flipped = _batch_dtw_distances(_flip_x(normalized), prototypes)
        return float(np.minimum(direct, flipped).min())

    def _prototype_matches(self, normalized: np.ndarray, points) -> dict[str, list[dict]]:
        labels = []
        prototypes = []
        prototype_ids = []
        for spell, spell_prototypes in self._prototypes.items():
            for index, prototype in enumerate(spell_prototypes):
                labels.append(spell)
                prototypes.append(prototype)
                prototype_ids.append(self._prototype_ids[spell][index])
        if not prototypes:
            return {}
        prototype_batch = np.stack(prototypes).astype(np.float32)
        direct = _batch_dtw_distances(normalized, prototype_batch)
        flipped = _batch_dtw_distances(_flip_x(normalized), prototype_batch)
        distances = np.minimum(direct, flipped)
        shifts = np.zeros((len(prototypes),), dtype=np.int32)
        reversed_flags = np.zeros((len(prototypes),), dtype=bool)
        cyclic_used = False
        gate = closed_trajectory_gate(points)
        if self.enable_cyclic_stupefy and gate.get("passed") and "stupefy" in self._prototypes:
            stupefy_indices = [index for index, spell in enumerate(labels) if spell == "stupefy"]
            stupefy_batch = prototype_batch[stupefy_indices]
            cyclic_distances, cyclic_shifts, cyclic_reversed = _cyclic_dtw_best(
                normalized,
                stupefy_batch,
                allow_reverse=bool(self.allow_cyclic_reverse),
            )
            for local_index, prototype_index in enumerate(stupefy_indices):
                distances[prototype_index] = cyclic_distances[local_index]
                shifts[prototype_index] = cyclic_shifts[local_index]
                reversed_flags[prototype_index] = cyclic_reversed[local_index]
            cyclic_used = True

        matches = {spell: [] for spell in self._prototypes}
        for index, spell in enumerate(labels):
            matches[spell].append({
                "distance": float(distances[index]),
                "prototype_id": prototype_ids[index],
                "shift": int(shifts[index]),
                "reversed": bool(reversed_flags[index]),
                "cyclic": bool(cyclic_used and spell == "stupefy"),
            })
        matches["__gate__"] = gate
        return matches

    def _rank_spells(self, normalized: np.ndarray, points) -> tuple[list[dict], dict]:
        prototype_matches = self._prototype_matches(normalized, points)
        gate = prototype_matches.pop("__gate__", {})
        ranked = []
        for spell, matches in prototype_matches.items():
            best = min(matches, key=lambda item: item["distance"])
            threshold = max(self._thresholds.get(spell, DTW_ACCEPT_THRESHOLD), 1e-6)
            ranked.append({
                "spell": spell,
                **best,
                "threshold": threshold,
                "distance_ratio": best["distance"] / threshold,
            })
        ranked.sort(key=lambda item: (item["distance_ratio"], item["distance"], item["spell"]))
        return ranked, gate

    def classify(self, points, side) -> ClassificationResult:
        from cv.gesture_pipeline import ClassificationResult

        if not self.loaded:
            return ClassificationResult(
                spell=None,
                confidence=0.0,
                method="data_template",
                reason=self.load_error or "template pack missing",
                algorithm_version=(
                    CYCLIC_TEMPLATE_ALGORITHM_VERSION
                    if self.enable_cyclic_stupefy else DATA_TEMPLATE_ALGORITHM_VERSION
                ),
            )

        normalized = _normalize_trajectory(points)
        if normalized is None:
            return ClassificationResult(
                spell=None,
                confidence=0.0,
                method="data_template",
                reason="invalid or insufficient trajectory",
                algorithm_version=(
                    CYCLIC_TEMPLATE_ALGORITHM_VERSION
                    if self.enable_cyclic_stupefy else DATA_TEMPLATE_ALGORITHM_VERSION
                ),
            )

        if self.enable_cyclic_stupefy and self.cyclic_stupefy_only:
            gate = closed_trajectory_gate(points)
            if not gate.get("passed"):
                return ClassificationResult(
                    spell=None,
                    confidence=0.0,
                    method="cyclic_template_shadow",
                    reason=f"closure gate rejected: {','.join(gate.get('reasons') or [])}",
                    features={"closure_gate": gate},
                    algorithm_version=CYCLIC_TEMPLATE_ALGORITHM_VERSION,
                )

        ranked, gate = self._rank_spells(normalized, points)
        ranked = [match for match in ranked if math.isfinite(match["distance"])]
        if not ranked:
            return ClassificationResult(
                spell=None,
                confidence=0.0,
                method="data_template",
                reason="no prototypes",
                algorithm_version=DATA_TEMPLATE_ALGORITHM_VERSION,
            )

        best = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None
        best_spell = best["spell"]
        best_distance = best["distance"]
        best_threshold = best["threshold"]
        margin = (
            second["distance_ratio"] - best["distance_ratio"]
            if second is not None else float("inf")
        )
        margin_threshold = self._margin_thresholds.get(best_spell, DEFAULT_MARGIN_THRESHOLD)
        ambiguous = bool(second is not None and margin < margin_threshold)
        algorithm_version = (
            CYCLIC_TEMPLATE_ALGORITHM_VERSION
            if self.enable_cyclic_stupefy else DATA_TEMPLATE_ALGORITHM_VERSION
        )
        structured = {
            "best_distance": best_distance,
            "second_spell": template_label_to_spell(second["spell"]) if second else None,
            "second_distance": second["distance"] if second else None,
            "margin": margin,
            "ambiguous": ambiguous,
            "matched_prototype_id": best["prototype_id"],
            "algorithm_version": algorithm_version,
            "best_shift": best["shift"],
            "cyclic_used": bool(best.get("cyclic")),
            "features": {
                "closure_gate": gate,
                "best_reversed": best["reversed"],
                "distance_margin_kind": "normalized_threshold_ratio",
            },
        }

        confidence = float(max(0.0, min(1.0, 1.0 - best_distance / best_threshold)))
        if best_distance > best_threshold:
            return ClassificationResult(
                spell=None,
                confidence=confidence,
                method="cyclic_template_shadow" if self.enable_cyclic_stupefy else "data_template",
                reason=f"best {best_spell} distance {best_distance:.3f}>{best_threshold:.3f}",
                **structured,
            )

        if ambiguous and self.reject_ambiguous:
            return ClassificationResult(
                spell=None,
                confidence=confidence,
                method="cyclic_template_shadow" if self.enable_cyclic_stupefy else "data_template",
                reason=(
                    f"ambiguous {best_spell}/{second['spell']} margin "
                    f"{margin:.3f}<{margin_threshold:.3f}"
                ),
                **structured,
            )

        cast_spell = template_label_to_spell(best_spell)
        if cast_spell == "incendio" and not advances_toward_opponent(points, side):
            return ClassificationResult(
                spell=None, confidence=0.0, method="data_template",
                reason="incendio must advance toward opponent", **structured,
            )
        return ClassificationResult(
            spell=cast_spell,
            confidence=confidence,
            method="cyclic_template_shadow" if self.enable_cyclic_stupefy else "data_template",
            reason=f"{best_spell} distance {best_distance:.3f}<{best_threshold:.3f}",
            **structured,
        )
