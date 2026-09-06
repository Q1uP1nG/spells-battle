from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cv.gesture_pipeline import ClassificationResult
from cv.template_classifier import _dtw_distance, _normalize_trajectory, template_label_to_spell

RUNTIME_TEMPLATE_SCORE_DISTANCE = 0.35
RUNTIME_TEMPLATE_ACCEPT_MIN = 0.78
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
