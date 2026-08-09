from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


GESTURE_PIPELINE_VERSION = "gesture-pipeline-v1"


@dataclass
class ClassificationResult:
    spell: Optional[str]
    confidence: float
    method: str
    reason: str
    features: Optional[object] = None


class HeuristicGestureClassifier:

    def classify(self, points, side) -> ClassificationResult:
        from cv.gesture_classifier import classify_cv_gesture, explain_cv_gesture

        spell, confidence = classify_cv_gesture(points, side)
        match = explain_cv_gesture(points, side)
        reason = match.reason if match is not None else "no match"
        return ClassificationResult(
            spell=spell,
            confidence=confidence,
            method="heuristic",
            reason=reason,
        )


class FusedGestureClassifier:
    """Confidence-weighted fusion of heuristics and non-parametric DTW templates."""

    TEMPLATE_RESCUE_MIN = 0.75
    TEMPLATE_OVERRIDE_MIN = 0.70
    AGREE_BOOST = 0.08
    CONFLICT_MARGIN = 0.05

    def __init__(self, heuristic=None, template=None):
        self.heuristic = heuristic if heuristic is not None else HeuristicGestureClassifier()
        if template is None:
            from cv.template_classifier import DataTemplateClassifier
            template = DataTemplateClassifier()
        self.template = template

    def classify(self, points, side) -> ClassificationResult:
        heuristic = self.heuristic.classify(points, side)
        template = self.template.classify(points, side)

        if heuristic.spell and template.spell and heuristic.spell == template.spell:
            confidence = min(1.0, max(heuristic.confidence, template.confidence) + self.AGREE_BOOST)
            return ClassificationResult(
                spell=heuristic.spell,
                confidence=confidence,
                method="fused",
                reason=f"agree heuristic={heuristic.reason}; template={template.reason}",
            )

        if (
            heuristic.spell
            and template.spell
            and template.spell != heuristic.spell
            and template.confidence >= self.TEMPLATE_OVERRIDE_MIN
        ):
            if template.confidence >= heuristic.confidence - self.CONFLICT_MARGIN:
                return ClassificationResult(
                    spell=template.spell,
                    confidence=min(0.95, template.confidence),
                    method="fused",
                    reason=f"template wins (T={template.confidence:.2f} >= H={heuristic.confidence:.2f}-{self.CONFLICT_MARGIN}): {template.reason}",
                )

        if (
            heuristic.spell is None
            and template.spell
            and template.confidence >= self.TEMPLATE_RESCUE_MIN
        ):
            return ClassificationResult(
                spell=template.spell,
                confidence=min(0.95, template.confidence),
                method="fused",
                reason=f"template rescue: {template.reason}",
            )

        if heuristic.spell:
            return ClassificationResult(
                spell=heuristic.spell,
                confidence=heuristic.confidence,
                method="fused",
                reason=f"conflict keep heuristic: {heuristic.reason}; template={template.reason}",
            )

        return ClassificationResult(
            spell=None,
            confidence=0.0,
            method="fused",
            reason=f"no match: heuristic={heuristic.reason}; template={template.reason}",
        )


class GesturePipeline:

    def __init__(self, primary=None):
        self.primary = primary if primary is not None else HeuristicGestureClassifier()

    def classify(self, points, side) -> ClassificationResult:
        return self.primary.classify(points, side)
