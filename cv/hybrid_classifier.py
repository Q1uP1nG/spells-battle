from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cv.gesture_classifier import (
    MIN_PATH_LENGTH_FOR_SHAPE_RULES,
    MIN_RAW_POINTS_FOR_SHAPE_RULES,
    collect_gesture_matches,
    extract_gesture_features,
    score_gesture_match,
)
from cv.gesture_pipeline import ClassificationResult, HeuristicGestureClassifier
from cv.template_classifier import _dtw_distance, _normalize_trajectory, template_label_to_spell

RUNTIME_TEMPLATE_SCORE_DISTANCE = 0.35
RUNTIME_TEMPLATE_ACCEPT_MIN = 0.78
DEFAULT_HEURISTIC_WEIGHT = 1.0
DEFAULT_TEMPLATE_WEIGHT = 0.2
TRAJECTORY_SPELLS = {"incendio", "circle", "glacius", "lumos", "overload"}


@dataclass
class RuntimeGestureTemplate:
    spell: str
    normalized: object
    source: str


def load_runtime_templates(log_dir: str | Path = "logs/cv_sessions") -> list[RuntimeGestureTemplate]:
    """Load templates from the labeled training session with the most samples."""
    root = Path(log_dir)
    if not root.exists():
        return []

    best_templates: list[RuntimeGestureTemplate] = []
    best_count = 0
    for path in sorted(root.glob("*.jsonl")):
        templates = _load_templates_from_file(path)
        if len(templates) > best_count:
            best_templates = templates
            best_count = len(templates)
    return best_templates


def _load_templates_from_file(path: Path) -> list[RuntimeGestureTemplate]:
    templates = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return templates

    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not _is_accepted_training_event(event):
            continue
        normalized = _normalize_trajectory(event.get("points") or [])
        if normalized is None:
            continue
        templates.append(RuntimeGestureTemplate(
            spell=template_label_to_spell(event["intended_spell"]),
            normalized=normalized,
            source=str(path),
        ))
    return templates


def _is_accepted_training_event(event: dict) -> bool:
    spell = event.get("intended_spell")
    if spell not in TRAJECTORY_SPELLS:
        return False
    if not event.get("training_mode", False):
        return False
    status = event.get("training_status")
    return status in (None, "accepted")


class HybridTemplateGestureClassifier:
    """Runtime classifier: structure-first heuristic with small DTW template support."""

    def __init__(
        self,
        templates: Optional[list[RuntimeGestureTemplate]] = None,
        log_dir: str | Path = "logs/cv_sessions",
        heuristic_weight: float = DEFAULT_HEURISTIC_WEIGHT,
        template_weight: float = DEFAULT_TEMPLATE_WEIGHT,
    ):
        self._templates = templates
        self._log_dir = log_dir
        self._heuristic_weight = heuristic_weight
        self._template_weight = template_weight
        self._heuristic = HeuristicGestureClassifier()

    def classify(self, points, side) -> ClassificationResult:
        templates = self._get_templates()
        heuristic = self._heuristic.classify(points, side)
        if not templates:
            return ClassificationResult(
                spell=heuristic.spell,
                confidence=heuristic.confidence,
                method="heuristic",
                reason=f"{heuristic.reason}; no runtime templates",
            )

        features = extract_gesture_features(points, side)
        normalized = _normalize_trajectory(points)
        if features is None or normalized is None:
            return heuristic

        heuristic_scores = {
            match.spell: score_gesture_match(match, features)
            for match in collect_gesture_matches(features)
        }
        template_scores = self._template_scores(normalized, templates)
        labels = sorted({template.spell for template in templates} | set(heuristic_scores.keys()))
        if not labels:
            return heuristic

        combined = {}
        for label in labels:
            combined[label] = (
                self._heuristic_weight * heuristic_scores.get(label, 0.0)
                + self._template_weight * template_scores.get(label, 0.0)
            )
        best_spell, best_score = max(combined.items(), key=lambda item: item[1])
        if best_score <= 0:
            return heuristic

        h_score = heuristic_scores.get(best_spell, 0.0)
        t_score = template_scores.get(best_spell, 0.0)
        if h_score <= 0 and not self._allow_template_only(features, t_score):
            return heuristic

        confidence = min(1.0, max(h_score, t_score, heuristic.confidence))
        reason = (
            f"hybrid H={h_score:.2f} T={t_score:.2f} "
            f"w={self._heuristic_weight:.1f}/{self._template_weight:.1f}"
        )
        return ClassificationResult(
            spell=best_spell,
            confidence=confidence,
            method="hybrid",
            reason=reason,
            features={
                "heuristic_scores": heuristic_scores,
                "template_scores": template_scores,
                "combined_scores": combined,
            },
        )

    def _get_templates(self) -> list[RuntimeGestureTemplate]:
        if self._templates is None:
            self._templates = load_runtime_templates(self._log_dir)
        return self._templates

    def _template_scores(self, normalized, templates: list[RuntimeGestureTemplate]) -> dict[str, float]:
        best_distance_by_spell = {}
        for template in templates:
            distance = _dtw_distance(normalized, template.normalized)
            current = best_distance_by_spell.get(template.spell)
            if current is None or distance < current:
                best_distance_by_spell[template.spell] = distance
        return {
            spell: max(0.0, 1.0 - distance / RUNTIME_TEMPLATE_SCORE_DISTANCE)
            for spell, distance in best_distance_by_spell.items()
        }

    def _allow_template_only(self, features, template_score: float) -> bool:
        return (
            features.raw_count >= MIN_RAW_POINTS_FOR_SHAPE_RULES
            and features.path_len >= MIN_PATH_LENGTH_FOR_SHAPE_RULES
            and template_score >= 0.78
        )


class RuntimeTemplateClassifier:
    """Adapter that wraps raw logged templates behind the DataTemplateClassifier interface.

    Lets ``FusedGestureClassifier`` use runtime (raw log) templates as a
    fallback when no trained ``gesture_templates.json`` is available, so the
    decision-tree fusion path is always used instead of the 0.2-weighted sum.
    """

    def __init__(self, templates=None, log_dir: str | Path = "logs/cv_sessions"):
        self._templates = templates
        self._log_dir = log_dir
        self.loaded = False
        self.load_error = ""
        self._ensure_loaded()

    def _ensure_loaded(self):
        if self._templates is None:
            self._templates = load_runtime_templates(self._log_dir)
        self.loaded = bool(self._templates)
        if not self.loaded and not self.load_error:
            self.load_error = "no runtime templates found"

    def classify(self, points, side) -> ClassificationResult:
        if not self.loaded:
            return ClassificationResult(
                spell=None,
                confidence=0.0,
                method="runtime_template",
                reason=self.load_error or "no runtime templates",
            )

        normalized = _normalize_trajectory(points)
        if normalized is None:
            return ClassificationResult(
                spell=None,
                confidence=0.0,
                method="runtime_template",
                reason="too few points to normalize",
            )

        best_distance_by_spell: dict[str, float] = {}
        for template in self._templates:
            distance = _dtw_distance(normalized, template.normalized)
            current = best_distance_by_spell.get(template.spell)
            if current is None or distance < current:
                best_distance_by_spell[template.spell] = distance

        if not best_distance_by_spell:
            return ClassificationResult(
                spell=None,
                confidence=0.0,
                method="runtime_template",
                reason="no template distances",
            )

        best_spell, best_distance = min(best_distance_by_spell.items(), key=lambda item: item[1])
        confidence = max(0.0, 1.0 - best_distance / RUNTIME_TEMPLATE_SCORE_DISTANCE)
        if confidence < RUNTIME_TEMPLATE_ACCEPT_MIN:
            return ClassificationResult(
                spell=None,
                confidence=confidence,
                method="runtime_template",
                reason=f"{best_spell} distance {best_distance:.3f} conf {confidence:.3f}<{RUNTIME_TEMPLATE_ACCEPT_MIN}",
            )

        return ClassificationResult(
            spell=best_spell,
            confidence=confidence,
            method="runtime_template",
            reason=f"{best_spell} distance {best_distance:.3f} conf {confidence:.3f}",
        )
