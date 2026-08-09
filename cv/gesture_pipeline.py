from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Mapping, Optional

import numpy as np


GESTURE_PIPELINE_VERSION = "gesture-pipeline-v2-normalized-shadow"
NORMALIZED_FEATURE_VERSION = "normalized-heuristic-shadow-v1"
REFERENCE_PALM_SCALE = 100.0
REFERENCE_FRAME_DIAGONAL = math.hypot(1280.0, 720.0)
REFERENCE_TRAJECTORY_SPAN = 180.0


@dataclass(frozen=True)
class GestureClassificationContext:
    """Capture metadata shared by preview, final classification, and replay."""

    palm_scale: Optional[float] = None
    frame_width: Optional[int] = None
    frame_height: Optional[int] = None
    fps_estimate: Optional[float] = None
    input_mode: str = "unknown"
    purpose: str = "final"


@dataclass(frozen=True)
class NormalizedFeatureMetadata:
    feature_version: str
    scale_source: str
    source_scale: float
    coordinate_scale: float
    duration_seconds: Optional[float]
    normalized_speed: Optional[float]


@dataclass
class ClassificationResult:
    spell: Optional[str]
    confidence: float
    method: str
    reason: str
    features: Optional[object] = None
    best_distance: Optional[float] = None
    second_spell: Optional[str] = None
    second_distance: Optional[float] = None
    margin: Optional[float] = None
    ambiguous: bool = False
    matched_prototype_id: Optional[str] = None
    algorithm_version: Optional[str] = None
    best_shift: Optional[int] = None
    cyclic_used: bool = False


@dataclass(frozen=True)
class PipelineClassification:
    """Primary gameplay result plus diagnostic results from the same pipeline run."""

    primary: ClassificationResult
    shadows: Mapping[str, ClassificationResult] = field(default_factory=dict)
    pipeline_version: str = GESTURE_PIPELINE_VERSION
    purpose: str = "final"

    @property
    def normalized_shadow(self) -> Optional[ClassificationResult]:
        return self.shadows.get("normalized_heuristic")

    @property
    def cyclic_shadow(self) -> Optional[ClassificationResult]:
        return self.shadows.get("cyclic_template")


def _positive_float(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0.0:
        return None
    return number


def normalize_points_for_context(points, context: Optional[GestureClassificationContext] = None):
    """Scale coordinates without translating or rotating them.

    Palm scale is preferred. Frame diagonal is the deterministic fallback for
    captures that know their resolution; legacy trajectories fall back to their
    own largest span. The returned metadata makes that fallback visible in
    evaluation reports instead of silently mixing coordinate systems.
    """

    context = context or GestureClassificationContext()
    pts = np.asarray(points, dtype=np.float32)
    if pts.ndim != 2 or pts.shape[1] < 2 or len(pts) == 0:
        return pts, NormalizedFeatureMetadata(
            feature_version=NORMALIZED_FEATURE_VERSION,
            scale_source="unavailable",
            source_scale=1.0,
            coordinate_scale=1.0,
            duration_seconds=None,
            normalized_speed=None,
        )
    pts = pts[:, :2]

    palm_scale = _positive_float(context.palm_scale)
    width = _positive_float(context.frame_width)
    height = _positive_float(context.frame_height)
    if palm_scale is not None:
        scale_source = "palm_scale"
        source_scale = palm_scale
        coordinate_scale = REFERENCE_PALM_SCALE / palm_scale
    elif width is not None and height is not None:
        scale_source = "frame_diagonal_fallback"
        source_scale = math.hypot(width, height)
        coordinate_scale = REFERENCE_FRAME_DIAGONAL / source_scale
    else:
        spans = np.ptp(pts, axis=0)
        trajectory_span = float(max(float(spans[0]), float(spans[1])))
        if trajectory_span > 1e-6:
            scale_source = "trajectory_span_fallback"
            source_scale = trajectory_span
            coordinate_scale = REFERENCE_TRAJECTORY_SPAN / trajectory_span
        else:
            scale_source = "unit_fallback"
            source_scale = 1.0
            coordinate_scale = 1.0

    normalized = (pts * coordinate_scale).astype(np.float32)
    fps = _positive_float(context.fps_estimate)
    duration = (len(pts) - 1) / fps if fps is not None and len(pts) > 1 else None
    if len(normalized) > 1:
        path_length = float(np.linalg.norm(np.diff(normalized, axis=0), axis=1).sum())
    else:
        path_length = 0.0
    normalized_speed = path_length / duration if duration and duration > 0.0 else None
    metadata = NormalizedFeatureMetadata(
        feature_version=NORMALIZED_FEATURE_VERSION,
        scale_source=scale_source,
        source_scale=source_scale,
        coordinate_scale=coordinate_scale,
        duration_seconds=duration,
        normalized_speed=normalized_speed,
    )
    return normalized, metadata


def _invoke_classifier(classifier, points, side, context):
    if getattr(classifier, "supports_context", False):
        return classifier.classify(points, side, context)
    return classifier.classify(points, side)


class HeuristicGestureClassifier:
    supports_context = True

    def classify(self, points, side, context=None) -> ClassificationResult:
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


class NormalizedHeuristicGestureClassifier:
    """Versioned scale-normalized heuristic candidate; never authoritative."""

    supports_context = True

    def classify(self, points, side, context=None) -> ClassificationResult:
        from cv.gesture_classifier import classify_cv_gesture, explain_cv_gesture

        normalized, metadata = normalize_points_for_context(points, context)
        spell, confidence = classify_cv_gesture(normalized, side)
        match = explain_cv_gesture(normalized, side)
        reason = match.reason if match is not None else "no match"
        reason = f"{reason}; scale={metadata.scale_source}:{metadata.coordinate_scale:.4f}"
        return ClassificationResult(
            spell=spell,
            confidence=confidence,
            method="normalized_heuristic_shadow",
            reason=reason,
            features=metadata,
        )


class FusedGestureClassifier:
    """Confidence-weighted fusion of heuristics and non-parametric DTW templates."""

    supports_context = True
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

    def classify(self, points, side, context=None) -> ClassificationResult:
        heuristic = _invoke_classifier(self.heuristic, points, side, context)
        template = _invoke_classifier(self.template, points, side, context)

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


class StupefyCyclicOverlayClassifier:
    """Per-spell promotion switch: overlay only a closed-loop Stupefy decision."""

    def __init__(self, baseline, cyclic_candidate):
        self.baseline = baseline
        self.cyclic_candidate = cyclic_candidate
        self.loaded = bool(getattr(baseline, "loaded", False))

    def classify(self, points, side) -> ClassificationResult:
        baseline = self.baseline.classify(points, side)
        cyclic = self.cyclic_candidate.classify(points, side)
        if cyclic.cyclic_used:
            return cyclic
        return baseline


class GesturePipeline:
    def __init__(self, primary=None, shadows=None, version=GESTURE_PIPELINE_VERSION):
        self.primary = primary if primary is not None else HeuristicGestureClassifier()
        self.shadows = dict(
            shadows if shadows is not None else {
                "normalized_heuristic": NormalizedHeuristicGestureClassifier(),
            }
        )
        self.version = str(version)

    def classify_both(
        self,
        points,
        side,
        context: Optional[GestureClassificationContext] = None,
    ) -> PipelineClassification:
        context = context or GestureClassificationContext()
        primary = _invoke_classifier(self.primary, points, side, context)
        shadows = {
            name: _invoke_classifier(classifier, points, side, context)
            for name, classifier in self.shadows.items()
        }
        return PipelineClassification(
            primary=primary,
            shadows=shadows,
            pipeline_version=self.version,
            purpose=context.purpose,
        )

    def classify(
        self,
        points,
        side,
        context: Optional[GestureClassificationContext] = None,
    ) -> ClassificationResult:
        return self.classify_both(points, side, context).primary
