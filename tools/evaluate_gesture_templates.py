"""Offline evaluation for labeled CV gesture logs.

Usage:
    python tools/evaluate_gesture_templates.py logs/cv_sessions/session_20260619_095544.jsonl
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from time import perf_counter
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cv.gesture_classifier import (
    classify_cv_gesture,
    collect_gesture_matches,
    extract_gesture_features,
    score_gesture_match,
)
from cv.gesture_pipeline import (
    FusedGestureClassifier,
    GestureClassificationContext,
    NORMALIZED_FEATURE_VERSION,
    NormalizedHeuristicGestureClassifier,
)
from cv.template_classifier import (
    CYCLIC_TEMPLATE_ALGORITHM_VERSION,
    DataTemplateClassifier,
    DEFAULT_CYCLIC_SHADOW_TEMPLATE_PATH,
)
from cv.template_classifier import _dtw_distance, _normalize_trajectory, template_label_to_spell
from tools.gesture_corpus import CanonicalCorpus, load_canonical_corpus


TEMPLATE_SCORE_DISTANCE = 0.35
FOCUS_LABELS = ("circle", "overload")
SPLIT_MODES = ("session_grouped_cv", "user_grouped_cv", "device_grouped_cv")


class EvaluationDataError(ValueError):
    pass


@dataclass
class GestureSample:
    index: int
    label: str
    points: list
    normalized: Any
    attempt: Optional[int]
    logged_primary: Optional[str]
    logged_shadow: Optional[str]
    sample_id: str = ""
    session_id: str = "legacy"
    input_mode: str = "unknown"
    logged_primary_available: bool = False
    logged_shadow_available: bool = False
    user_id: str = ""
    device_id: str = ""
    derived_from_sample_id: str = ""
    dataset_partition: str = "development"
    frame_width: Optional[int] = None
    frame_height: Optional[int] = None
    fps_estimate: Optional[float] = None
    palm_scale: Optional[float] = None


def load_entries(path: str | Path) -> list[dict]:
    log_path = Path(path)
    entries = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def build_samples(entries: list[dict]) -> list[GestureSample]:
    samples = []
    for entry in entries:
        if entry.get("review_status") in ("discarded", "skipped"):
            continue
        label = entry.get("label") or entry.get("intended_spell")
        points = entry.get("points") or []
        normalized = _normalize_trajectory(points)
        if not label or normalized is None:
            continue
        primary = entry.get("primary")
        shadow = entry.get("shadow")
        samples.append(
            GestureSample(
                index=len(samples),
                label=label,
                points=points,
                normalized=normalized,
                attempt=entry.get("training_attempt"),
                logged_primary=(primary or {}).get("spell"),
                logged_shadow=(shadow or {}).get("spell"),
                sample_id=str(entry.get("sample_id") or ""),
                session_id=str(
                    entry.get("session_id")
                    or Path(str(entry.get("source_file") or "legacy")).stem
                    or "legacy"
                ),
                input_mode=str(entry.get("input_mode") or entry.get("mode") or "unknown"),
                logged_primary_available=isinstance(primary, dict) and "spell" in primary,
                logged_shadow_available=isinstance(shadow, dict) and "spell" in shadow,
                user_id=str(entry.get("user_id") or ""),
                device_id=str(entry.get("device_id") or ""),
                derived_from_sample_id=str(entry.get("derived_from_sample_id") or ""),
                dataset_partition=str(entry.get("dataset_partition") or "development"),
                frame_width=entry.get("frame_width"),
                frame_height=entry.get("frame_height"),
                fps_estimate=entry.get("fps_estimate"),
                palm_scale=entry.get("palm_scale"),
            )
        )
    return samples


def build_samples_from_corpus(
    corpus: CanonicalCorpus,
    dataset_partition: str = "all",
) -> list[GestureSample]:
    return build_samples([
        {
            "label": sample.label,
            "points": sample.points,
            "sample_id": sample.sample_id,
            "session_id": sample.session_id,
            "input_mode": sample.input_mode,
            "source_file": sample.source_file,
            "training_attempt": sample.source_attempt_id,
            "primary": sample.metadata.get("primary"),
            "shadow": sample.metadata.get("shadow"),
            "user_id": sample.metadata.get("user_id"),
            "device_id": sample.metadata.get("device_id"),
            "derived_from_sample_id": sample.metadata.get("derived_from_sample_id"),
            "dataset_partition": sample.dataset_partition,
            "frame_width": sample.metadata.get("frame_width"),
            "frame_height": sample.metadata.get("frame_height"),
            "fps_estimate": sample.metadata.get("fps_estimate"),
            "palm_scale": sample.metadata.get("palm_scale"),
        }
        for sample in corpus.samples
        if dataset_partition == "all" or sample.dataset_partition == dataset_partition
    ])


def _sample_distance(
    samples: list[GestureSample],
    first_index: int,
    second_index: int,
    distance_cache: Optional[dict[tuple[int, int], float]] = None,
) -> float:
    key = tuple(sorted((first_index, second_index)))
    if distance_cache is not None and key in distance_cache:
        return distance_cache[key]
    distance = _dtw_distance(
        samples[first_index].normalized,
        samples[second_index].normalized,
    )
    if distance_cache is not None:
        distance_cache[key] = distance
    return distance


def classify_real_template(
    samples: list[GestureSample],
    sample_index: int,
    distance_cache: Optional[dict[tuple[int, int], float]] = None,
    candidate_indices: Optional[list[int]] = None,
) -> dict:
    target = samples[sample_index]
    matches = []
    indices = candidate_indices if candidate_indices is not None else range(len(samples))
    for other_index in indices:
        sample = samples[other_index]
        if other_index == sample_index:
            continue
        distance = _sample_distance(samples, sample_index, other_index, distance_cache)
        matches.append({
            "spell": sample.label,
            "distance": distance,
            "sample_index": other_index,
            "attempt": sample.attempt,
        })

    if not matches:
        return {
            "spell": None,
            "distance": float("inf"),
            "margin": 0.0,
            "nearest_sample_index": None,
            "top": [],
        }

    best_by_spell = {}
    for match in matches:
        current = best_by_spell.get(match["spell"])
        if current is None or match["distance"] < current["distance"]:
            best_by_spell[match["spell"]] = match

    top = sorted(best_by_spell.values(), key=lambda item: item["distance"])
    best = top[0]
    second_distance = top[1]["distance"] if len(top) > 1 else best["distance"]
    return {
        "spell": best["spell"],
        "distance": best["distance"],
        "margin": second_distance - best["distance"],
        "nearest_sample_index": best["sample_index"],
        "top": top,
    }


def template_scores_by_spell(
    samples: list[GestureSample],
    sample_index: int,
    distance_cache: Optional[dict[tuple[int, int], float]] = None,
) -> dict[str, float]:
    result = classify_real_template(samples, sample_index, distance_cache)
    scores = {}
    for item in result["top"]:
        scores[item["spell"]] = max(0.0, 1.0 - item["distance"] / TEMPLATE_SCORE_DISTANCE)
    return scores


def heuristic_scores_by_spell(sample: GestureSample) -> dict[str, float]:
    features = extract_gesture_features(sample.points, "left")
    if features is None:
        return {}
    scores = {}
    for match in collect_gesture_matches(features):
        scores[match.spell] = score_gesture_match(match, features)
    return scores


def classify_hybrid(
    samples: list[GestureSample],
    sample_index: int,
    heuristic_weight: float,
    template_weight: float,
    distance_cache: Optional[dict[tuple[int, int], float]] = None,
) -> dict:
    sample = samples[sample_index]
    heuristic_scores = heuristic_scores_by_spell(sample)
    template_scores = template_scores_by_spell(samples, sample_index, distance_cache)
    spells = sorted({template_label_to_spell(label) for label in {sample.label for sample in samples}})
    scores = {}
    for spell in spells:
        label = spell
        for s in samples:
            if template_label_to_spell(s.label) == spell:
                label = s.label
                break
        scores[spell] = (
            heuristic_weight * heuristic_scores.get(spell, 0.0)
            + template_weight * template_scores.get(label, 0.0)
        )
    best_spell, best_score = max(scores.items(), key=lambda item: item[1])
    return {
        "spell": best_spell if best_score > 0 else None,
        "score": best_score,
        "scores": scores,
        "heuristic_scores": heuristic_scores,
        "template_scores": template_scores,
    }


def classify_hybrid_from_scores(
    spells: list[str],
    heuristic_scores: dict[str, float],
    template_scores: dict[str, float],
    heuristic_weight: float,
    template_weight: float,
) -> Optional[str]:
    scores = {}
    for spell in spells:
        label = "circle" if spell == "stupefy" else spell
        scores[spell] = (
            heuristic_weight * heuristic_scores.get(spell, 0.0)
            + template_weight * template_scores.get(label, 0.0)
        )
    best_spell, best_score = max(scores.items(), key=lambda item: item[1])
    return best_spell if best_score > 0 else None


def search_hybrid_weights(
    samples: list[GestureSample],
    heuristic_weights=(0.0, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0),
    template_weights=(0.0, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0),
) -> list[dict]:
    results = []
    spells = sorted({template_label_to_spell(sample.label) for sample in samples})
    distance_cache = {}
    cached_scores = [
        (
            heuristic_scores_by_spell(sample),
            template_scores_by_spell(samples, i, distance_cache),
        )
        for i, sample in enumerate(samples)
    ]
    for h_weight in heuristic_weights:
        for t_weight in template_weights:
            predictions = []
            for i, sample in enumerate(samples):
                h_scores, t_scores = cached_scores[i]
                prediction = classify_hybrid_from_scores(
                    spells, h_scores, t_scores, h_weight, t_weight,
                )
                predictions.append((sample.label, prediction))
            summary = summarize_predictions(predictions)
            results.append({
                "heuristic_weight": h_weight,
                "template_weight": t_weight,
                "correct": summary["correct"],
                "total": summary["total"],
                "summary": summary,
            })
    return sorted(
        results,
        key=lambda item: (
            item["correct"],
            -item["template_weight"],
            item["heuristic_weight"],
        ),
        reverse=True,
    )


def evaluate_samples(
    samples: list[GestureSample],
    data_template_classifier=None,
    cyclic_template_classifier=None,
    distance_cache=None,
) -> dict:
    data_template_classifier = data_template_classifier or DataTemplateClassifier()
    if cyclic_template_classifier is None:
        if isinstance(data_template_classifier, DataTemplateClassifier):
            cyclic_path = (
                DEFAULT_CYCLIC_SHADOW_TEMPLATE_PATH
                if DEFAULT_CYCLIC_SHADOW_TEMPLATE_PATH.exists()
                else data_template_classifier.template_path
            )
            cyclic_template_classifier = DataTemplateClassifier(
                template_path=cyclic_path,
                enable_cyclic_stupefy=True,
                reject_ambiguous=True,
                cyclic_stupefy_only=True,
            )
        else:
            cyclic_template_classifier = data_template_classifier
    fused_classifier = FusedGestureClassifier(template=data_template_classifier)
    normalized_classifier = NormalizedHeuristicGestureClassifier()
    methods = {
        "logged_primary": [],
        "current_heuristic": [],
        "normalized_heuristic_shadow": [],
        "logged_shadow": [],
        "real_template": [],
        "data_template": [],
        "cyclic_template_shadow": [],
        "fused": [],
        "hybrid_1_0_0_2": [],
    }
    method_records = defaultdict(list)
    misses = []
    distance_cache = distance_cache if distance_cache is not None else {}
    timings = defaultdict(list)
    template_margins = []
    normalization_sources = Counter()
    cyclic_diagnostics = Counter()

    for i, sample in enumerate(samples):
        started = perf_counter()
        current_spell, current_conf = classify_cv_gesture(sample.points, "left")
        timings["current_heuristic"].append((perf_counter() - started) * 1000.0)
        context = GestureClassificationContext(
            palm_scale=sample.palm_scale,
            frame_width=sample.frame_width,
            frame_height=sample.frame_height,
            fps_estimate=sample.fps_estimate,
            input_mode=sample.input_mode,
            purpose="evaluation",
        )
        started = perf_counter()
        normalized_shadow = normalized_classifier.classify(sample.points, "left", context)
        timings["normalized_heuristic_shadow"].append((perf_counter() - started) * 1000.0)
        normalization_sources[normalized_shadow.features.scale_source] += 1
        template = classify_real_template(samples, i, distance_cache)
        template_margins.append(template["margin"])
        started = perf_counter()
        data_template = data_template_classifier.classify(sample.points, "left")
        timings["data_template"].append((perf_counter() - started) * 1000.0)
        started = perf_counter()
        cyclic_template = cyclic_template_classifier.classify(sample.points, "left")
        timings["cyclic_template_shadow"].append((perf_counter() - started) * 1000.0)
        if getattr(cyclic_template, "cyclic_used", False):
            cyclic_diagnostics["cyclic_top1"] += 1
        if getattr(cyclic_template, "ambiguous", False):
            cyclic_diagnostics["ambiguous"] += 1
        closure_gate = getattr(cyclic_template, "features", None)
        cyclic_gate_passed = bool(
            isinstance(closure_gate, dict)
            and (closure_gate.get("closure_gate") or {}).get("passed")
        )
        if cyclic_gate_passed:
            cyclic_diagnostics["closure_gate_passed"] += 1
        started = perf_counter()
        fused = fused_classifier.classify(sample.points, "left")
        timings["fused"].append((perf_counter() - started) * 1000.0)
        hybrid = classify_hybrid(
            samples,
            i,
            heuristic_weight=1.0,
            template_weight=0.2,
            distance_cache=distance_cache,
        )
        predictions = {
            "current_heuristic": current_spell,
            "normalized_heuristic_shadow": normalized_shadow.spell,
            "real_template": template_label_to_spell(template["spell"]),
            "data_template": data_template.spell,
            "cyclic_template_shadow": (
                cyclic_template.spell
                if cyclic_gate_passed
                else data_template.spell
            ),
            "fused": fused.spell,
            "hybrid_1_0_0_2": template_label_to_spell(hybrid["spell"]),
        }
        if sample.logged_primary_available:
            predictions["logged_primary"] = sample.logged_primary
        if sample.logged_shadow_available:
            predictions["logged_shadow"] = sample.logged_shadow
        for method, prediction in predictions.items():
            methods[method].append((sample.label, prediction))
            method_records[method].append((sample, prediction))
        for method, prediction in predictions.items():
            if prediction != template_label_to_spell(sample.label):
                misses.append({
                    "sample_index": sample.index,
                    "attempt": sample.attempt,
                    "label": sample.label,
                    "method": method,
                    "prediction": prediction,
                    "template_top": template["top"][:3],
                    "data_template_reason": data_template.reason,
                    "cyclic_template_reason": cyclic_template.reason,
                    "fused_reason": fused.reason,
                    "current_confidence": current_conf,
                    "normalized_shadow_reason": normalized_shadow.reason,
                    "points": len(sample.points),
                })

    method_summaries = {
        method: summarize_predictions(pairs)
        for method, pairs in methods.items()
    }
    for method, values in timings.items():
        method_summaries[method]["latency_ms"] = _distribution(values)
    for method, records in method_records.items():
        method_summaries[method]["breakdowns"] = _metric_breakdowns(records)
    method_summaries["real_template"]["margin"] = _distribution(template_margins)
    method_summaries["normalized_heuristic_shadow"]["normalization_sources"] = dict(
        sorted(normalization_sources.items())
    )
    method_summaries["cyclic_template_shadow"]["diagnostics"] = dict(
        sorted(cyclic_diagnostics.items())
    )
    return {
        "total": len(samples),
        "methods": method_summaries,
        "misses": misses,
        **method_summaries,
    }


def summarize_predictions(pairs: list[tuple[str, Optional[str]]]) -> dict:
    correct = sum(1 for label, prediction in pairs if template_label_to_spell(label) == prediction)
    by_label = defaultdict(lambda: {"correct": 0, "total": 0})
    confusion = defaultdict(Counter)
    for label, prediction in pairs:
        by_label[label]["total"] += 1
        if template_label_to_spell(label) == prediction:
            by_label[label]["correct"] += 1
        confusion[label][prediction] += 1
    labels = sorted({template_label_to_spell(label) for label, _prediction in pairs})
    per_spell = {}
    for spell in labels:
        true_positive = sum(
            1 for label, prediction in pairs
            if template_label_to_spell(label) == spell and prediction == spell
        )
        false_positive = sum(
            1 for label, prediction in pairs
            if template_label_to_spell(label) != spell and prediction == spell
        )
        false_negative = sum(
            1 for label, prediction in pairs
            if template_label_to_spell(label) == spell and prediction != spell
        )
        precision = true_positive / max(true_positive + false_positive, 1)
        recall = true_positive / max(true_positive + false_negative, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-12)
        per_spell[spell] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": true_positive + false_negative,
        }
    macro = {
        metric: sum(values[metric] for values in per_spell.values()) / max(len(per_spell), 1)
        for metric in ("precision", "recall", "f1")
    }
    return {
        "correct": correct,
        "total": len(pairs),
        "accuracy": correct / max(len(pairs), 1),
        "macro": macro,
        "per_spell": per_spell,
        "rejection_rate": sum(1 for _label, prediction in pairs if prediction is None) / max(len(pairs), 1),
        "error_acceptance_rate": sum(
            1
            for label, prediction in pairs
            if prediction is not None and prediction != template_label_to_spell(label)
        ) / max(len(pairs), 1),
        "by_label": dict(by_label),
        "confusion": {label: dict(counter) for label, counter in confusion.items()},
    }


def _distribution(values) -> dict:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return {"count": 0, "p50": None, "p95": None, "min": None, "max": None}
    return {
        "count": len(ordered),
        "p50": _percentile(ordered, 0.50),
        "p95": _percentile(ordered, 0.95),
        "min": ordered[0],
        "max": ordered[-1],
    }


def _percentile(ordered, quantile):
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _metric_breakdowns(records):
    result = {}
    for field in ("input_mode", "session_id", "user_id", "device_id"):
        grouped = defaultdict(list)
        for sample, prediction in records:
            value = str(getattr(sample, field, "") or "")
            if not value or (field in ("user_id", "device_id") and value == "legacy"):
                continue
            grouped[value].append((sample.label, prediction))
        if grouped:
            result[field] = {
                group: summarize_predictions(pairs)
                for group, pairs in sorted(grouped.items())
            }
    return result


def compare_to_baseline(summary, baseline_metrics):
    comparisons = {}
    baseline_methods = baseline_metrics.get("methods") or {}
    for method, current in summary.get("methods", {}).items():
        baseline = baseline_methods.get(method)
        if not baseline:
            continue
        comparisons[method] = {
            "accuracy_delta": current.get("accuracy", 0.0) - baseline.get("accuracy", 0.0),
            "macro_f1_delta": (
                (current.get("macro") or {}).get("f1", 0.0)
                - (baseline.get("macro") or {}).get("f1", 0.0)
            ),
            "rejection_rate_delta": (
                current.get("rejection_rate", 0.0) - baseline.get("rejection_rate", 0.0)
            ),
            "error_acceptance_rate_delta": (
                _error_acceptance_rate(current) - _error_acceptance_rate(baseline)
            ),
        }
    return comparisons


def _error_acceptance_rate(metric):
    if "error_acceptance_rate" in metric:
        return float(metric["error_acceptance_rate"])
    total = max(int(metric.get("total") or 0), 1)
    incorrect_rate = (total - int(metric.get("correct") or 0)) / total
    return max(0.0, incorrect_rate - float(metric.get("rejection_rate") or 0.0))


def build_grouped_folds(samples, split_mode="session_grouped_cv", fold_count=5):
    if split_mode not in SPLIT_MODES:
        raise EvaluationDataError(f"unknown split mode: {split_mode}")
    if fold_count < 2:
        raise EvaluationDataError("grouped evaluation requires at least two folds")

    seen_sample_ids = set()
    groups = defaultdict(list)
    field = {
        "session_grouped_cv": "session_id",
        "user_grouped_cv": "user_id",
        "device_grouped_cv": "device_id",
    }[split_mode]
    samples_by_id = {sample.sample_id: sample for sample in samples if sample.sample_id}

    def effective_group_id(sample):
        current = sample
        visited = set()
        while current.derived_from_sample_id and current.derived_from_sample_id not in visited:
            visited.add(current.derived_from_sample_id)
            parent = samples_by_id.get(current.derived_from_sample_id)
            if parent is None:
                break
            current = parent
        return str(getattr(current, field, "") or getattr(sample, field, "") or "")

    for index, sample in enumerate(samples):
        if sample.sample_id:
            if sample.sample_id in seen_sample_ids:
                raise EvaluationDataError(f"duplicate sample_id: {sample.sample_id}")
            seen_sample_ids.add(sample.sample_id)
        group_id = effective_group_id(sample)
        if not group_id or (field != "session_id" and group_id == "legacy"):
            raise EvaluationDataError(
                f"{split_mode} unavailable: sample {sample.sample_id or index} lacks {field}"
            )
        group_key = f"{field}:{group_id}"
        groups[group_key].append(index)

    if len(groups) < 2:
        raise EvaluationDataError(
            f"{split_mode} requires at least two independent groups; found {len(groups)}"
        )
    actual_fold_count = min(int(fold_count), len(groups))
    fold_groups = [[] for _ in range(actual_fold_count)]
    fold_sizes = [0] * actual_fold_count
    ordered_groups = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    for group_key, indices in ordered_groups:
        target = min(range(actual_fold_count), key=lambda idx: (fold_sizes[idx], idx))
        fold_groups[target].append(group_key)
        fold_sizes[target] += len(indices)

    all_indices = set(range(len(samples)))
    folds = []
    for index, group_keys in enumerate(fold_groups):
        test_indices = sorted(item for key in group_keys for item in groups[key])
        train_indices = sorted(all_indices.difference(test_indices))
        folds.append({
            "fold": index,
            "groups": sorted(group_keys),
            "train_indices": train_indices,
            "test_indices": test_indices,
        })
    _validate_folds(samples, folds)
    return folds


def _validate_folds(samples, folds):
    test_membership = {}
    for fold in folds:
        train = set(fold["train_indices"])
        test = set(fold["test_indices"])
        if train.intersection(test):
            raise EvaluationDataError(f"fold {fold['fold']} has train/test leakage")
        for sample_index in test:
            if sample_index in test_membership:
                raise EvaluationDataError(f"sample index {sample_index} appears in multiple test folds")
            test_membership[sample_index] = fold["fold"]
    if set(test_membership) != set(range(len(samples))):
        raise EvaluationDataError("not every sample appears in exactly one test fold")
    sample_index_by_id = {
        sample.sample_id: index for index, sample in enumerate(samples) if sample.sample_id
    }
    for index, sample in enumerate(samples):
        parent_index = sample_index_by_id.get(sample.derived_from_sample_id)
        if parent_index is not None and test_membership[index] != test_membership[parent_index]:
            raise EvaluationDataError(
                f"derived sample {sample.sample_id} is separated from {sample.derived_from_sample_id}"
            )


def evaluate_grouped_template(samples, folds, distance_cache=None):
    distance_cache = distance_cache if distance_cache is not None else {}
    pairs = []
    margins = []
    misses = []
    for fold in folds:
        for sample_index in fold["test_indices"]:
            result = classify_real_template(
                samples,
                sample_index,
                distance_cache,
                candidate_indices=fold["train_indices"],
            )
            sample = samples[sample_index]
            prediction = template_label_to_spell(result["spell"])
            pairs.append((sample.label, prediction))
            margins.append(result["margin"])
            if prediction != template_label_to_spell(sample.label):
                misses.append({
                    "sample_index": sample.index,
                    "sample_id": sample.sample_id,
                    "label": sample.label,
                    "method": "grouped_template",
                    "prediction": prediction,
                    "fold": fold["fold"],
                    "template_top": result["top"][:3],
                    "points": len(sample.points),
                })
    result = summarize_predictions(pairs)
    result["margin"] = _distribution(margins)
    return result, misses


def format_summary(summary: dict) -> str:
    lines = [f"Total labeled samples: {summary['total']}", ""]
    method_order = [
        "logged_primary",
        "current_heuristic",
        "normalized_heuristic_shadow",
        "logged_shadow",
        "real_template",
        "grouped_template",
        "data_template",
        "cyclic_template_shadow",
        "fused",
        "hybrid_1_0_0_2",
    ]
    for method in [name for name in method_order if name in summary]:
        result = summary[method]
        total = max(result["total"], 1)
        lines.append(f"{method}: {result['correct']}/{result['total']} ({result['correct'] / total:.1%})")
        lines.append(
            f"  macro_f1={result['macro']['f1']:.3f} "
            f"rejection={result['rejection_rate']:.1%} "
            f"error_acceptance={result['error_acceptance_rate']:.1%}"
        )
        latency = result.get("latency_ms") or {}
        if latency.get("p50") is not None:
            lines.append(
                f"  latency_ms p50={latency['p50']:.3f} p95={latency['p95']:.3f}"
            )
        margin = result.get("margin") or {}
        if margin.get("p50") is not None:
            lines.append(
                f"  margin p50={margin['p50']:.3f} p95={margin['p95']:.3f}"
            )
        normalization_sources = result.get("normalization_sources") or {}
        if normalization_sources:
            lines.append(f"  normalization_sources={normalization_sources}")
        diagnostics = result.get("diagnostics") or {}
        if diagnostics:
            lines.append(f"  diagnostics={diagnostics}")
        for label, data in sorted(result["by_label"].items()):
            label_total = max(data["total"], 1)
            lines.append(f"  {label}: {data['correct']}/{data['total']} ({data['correct'] / label_total:.1%})")
        lines.append("")

    lines.append("Real-template confusion:")
    for label, counter in sorted(summary["real_template"]["confusion"].items()):
        lines.append(f"  {label}: {counter}")

    focus_labels = [label for label in FOCUS_LABELS if label in summary["fused"]["by_label"]]
    if focus_labels:
        lines.append("")
        lines.append("Circle/Overload focus:")
        for label in focus_labels:
            lines.append(f"  {label} -> {template_label_to_spell(label)}:")
            for method in [
                "current_heuristic",
                "normalized_heuristic_shadow",
                "data_template",
                "cyclic_template_shadow",
                "fused",
                "real_template",
            ]:
                if method not in summary:
                    continue
                data = summary[method]["by_label"].get(label, {"correct": 0, "total": 0})
                total = max(data["total"], 1)
                lines.append(
                    f"    {method}: {data['correct']}/{data['total']} "
                    f"({data['correct'] / total:.1%})"
                )

    important_misses = [
        miss for miss in summary["misses"]
        if miss["method"] in (
            "current_heuristic",
            "real_template",
            "data_template",
            "cyclic_template_shadow",
            "fused",
        )
    ]
    if important_misses:
        lines.append("")
        lines.append("Current/template misses:")
        for miss in important_misses:
            top = [
                f"{item['spell']}:{item['distance']:.3f}"
                for item in miss["template_top"]
            ]
            lines.append(
                f"  #{miss['sample_index']} attempt={miss['attempt']} "
                f"label={miss['label']} method={miss['method']} pred={miss['prediction']} "
                f"points={miss['points']} top={top}"
            )
    if summary.get("comparison"):
        lines.append("")
        lines.append("Change from baseline:")
        for method, deltas in sorted(summary["comparison"].items()):
            lines.append(
                f"  {method}: accuracy {deltas['accuracy_delta']:+.3f}, "
                f"macro_f1 {deltas['macro_f1_delta']:+.3f}, "
                f"rejection {deltas['rejection_rate_delta']:+.3f}, "
                f"error_acceptance {deltas['error_acceptance_rate_delta']:+.3f}"
            )
    return "\n".join(lines)


def main(path: str) -> None:
    entries = load_entries(path)
    samples = build_samples(entries)
    if not samples:
        print("No labeled samples found.")
        return
    summary = evaluate_samples(samples)
    print(format_summary(summary))
    print()
    print("Hybrid weight search:")
    for result in search_hybrid_weights(samples)[:10]:
        total = max(result["total"], 1)
        print(
            f"  H={result['heuristic_weight']:.2f} T={result['template_weight']:.2f} "
            f"{result['correct']}/{result['total']} ({result['correct'] / total:.1%})"
        )


def evaluate_canonical_corpus(
    corpus,
    data_template_classifier=None,
    cyclic_template_classifier=None,
    split_mode=None,
    fold_count=5,
    dataset_partition="all",
):
    samples = build_samples_from_corpus(corpus, dataset_partition=dataset_partition)
    distance_cache = {}
    summary = evaluate_samples(
        samples,
        data_template_classifier=data_template_classifier,
        cyclic_template_classifier=cyclic_template_classifier,
        distance_cache=distance_cache,
    )
    summary["dataset_partition"] = dataset_partition
    if split_mode:
        folds = build_grouped_folds(samples, split_mode=split_mode, fold_count=fold_count)
        grouped, misses = evaluate_grouped_template(samples, folds, distance_cache=distance_cache)
        summary["grouped_template"] = grouped
        summary["methods"]["grouped_template"] = grouped
        summary["misses"].extend(misses)
        summary["split"] = {
            "mode": split_mode,
            "fold_count": len(folds),
            "folds": [
                {
                    "fold": fold["fold"],
                    "groups": fold["groups"],
                    "train_samples": len(fold["train_indices"]),
                    "test_samples": len(fold["test_indices"]),
                    "train_labels": dict(sorted(Counter(
                        samples[index].label for index in fold["train_indices"]
                    ).items())),
                    "test_labels": dict(sorted(Counter(
                        samples[index].label for index in fold["test_indices"]
                    ).items())),
                    "missing_train_labels": sorted(
                        {sample.label for sample in samples}
                        - {samples[index].label for index in fold["train_indices"]}
                    ),
                }
                for fold in folds
            ],
        }
    return samples, summary


def _template_pack_manifest(path=Path("models/gesture_templates.json")):
    template_path = ROOT / path
    result = {"path": str(path).replace("\\", "/"), "available": False}
    try:
        raw = template_path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return result
    result.update({
        "available": True,
        "schema_version": payload.get("version"),
        "created": payload.get("created"),
        "sha256": hashlib.sha256(raw).hexdigest(),
    })
    return result


def _deterministic_metrics_version(summary):
    payload = {
        "total": summary["total"],
        "dataset_partition": summary.get("dataset_partition"),
        "split": summary.get("split"),
        "methods": json.loads(json.dumps(summary["methods"])),
    }
    for method in payload["methods"].values():
        method.pop("latency_ms", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"sha256:{hashlib.sha256(encoded.encode('ascii')).hexdigest()}"


def write_evaluation_artifacts(output_dir, summary, corpus, command):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    manifest = {
        "schema": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": commit,
        "classifier_versions": {
            "heuristic": f"source@{commit}",
            "fused": f"source@{commit}",
            "normalized_heuristic_shadow": NORMALIZED_FEATURE_VERSION,
            "cyclic_template_shadow": CYCLIC_TEMPLATE_ALGORITHM_VERSION,
            "real_template": "leave-one-out-dtw-v1",
        },
        "template_pack": _template_pack_manifest(),
        "cyclic_template_pack": _template_pack_manifest(
            Path(summary.get("cyclic_template_pack") or DEFAULT_CYCLIC_SHADOW_TEMPLATE_PATH)
        ),
        "corpus_version": corpus.audit.get("corpus_version"),
        "deterministic_metrics_version": _deterministic_metrics_version(summary),
        "split": summary.get("split"),
        "dataset_partition": summary.get("dataset_partition"),
        "command": list(command),
        "corpus_audit": corpus.audit,
        "source_files": corpus.source_files,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    metrics = {
        "total": summary["total"],
        "split": summary.get("split"),
        "dataset_partition": summary.get("dataset_partition"),
        "comparison": summary.get("comparison"),
        "methods": summary["methods"],
    }
    (output / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    audit = corpus.audit
    limitations = (
        "This is a regression baseline on the current legacy corpus, not evidence of "
        "cross-user or cross-device generalization. `data_template` uses a template pack "
        "built from this bank and is therefore a resubstitution result. `real_template` "
        "uses sample-level leave-one-out DTW but is not yet session-grouped."
    )
    split = summary.get("split")
    split_text = "No grouped split was requested."
    if split:
        split_text = (
            f"`{split['mode']}` with {split['fold_count']} folds; group IDs are kept "
            "entirely within one test fold."
        )
    report_header = (
        "# Gesture Evaluation\n\n"
        "## Scope and limitations\n\n"
        f"{limitations}\n\n"
        f"Dataset partition: `{summary.get('dataset_partition', 'all')}`. {split_text}\n\n"
        "## Corpus audit\n\n"
        f"- Canonical samples: {audit.get('canonical_samples', 0)}\n"
        f"- Duplicate views merged: {audit.get('duplicates_merged', 0)}\n"
        f"- Latest reviews: {audit.get('latest_reviews', 0)} "
        f"({audit.get('accepted_reviews', 0)} accepted, "
        f"{audit.get('discarded_reviews', 0)} discarded)\n"
        f"- Corpus version: `{audit.get('corpus_version', 'unknown')}`\n\n"
        "## Results\n\n```text\n"
    )
    (output / "report.md").write_text(
        report_header + format_summary(summary) + "\n```\n",
        encoding="utf-8",
    )
    with open(output / "confusion_matrix.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        labels = sorted({
            label
            for method in summary["methods"].values()
            for label in method["confusion"]
        })
        predictions = sorted({
            str(prediction)
            for method in summary["methods"].values()
            for values in method["confusion"].values()
            for prediction in values
        })
        writer.writerow(["method", "actual", *predictions])
        for method_name, method in sorted(summary["methods"].items()):
            for label in labels:
                row = method["confusion"].get(label, {})
                writer.writerow([
                    method_name,
                    label,
                    *[row.get(None if value == "None" else value, 0) for value in predictions],
                ])
    with open(output / "misses.jsonl", "w", encoding="utf-8") as handle:
        for miss in summary["misses"]:
            handle.write(json.dumps(miss, ensure_ascii=False) + "\n")
    return manifest


def cli(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", help="legacy single JSONL input")
    parser.add_argument("--logs", default=None)
    parser.add_argument("--bank", default=None)
    parser.add_argument("--reviewed", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--split-mode", choices=SPLIT_MODES, default="session_grouped_cv")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--baseline-metrics", default=None)
    parser.add_argument(
        "--cyclic-template-pack",
        default=str(DEFAULT_CYCLIC_SHADOW_TEMPLATE_PATH),
    )
    parser.add_argument(
        "--partition",
        choices=("development", "locked", "all"),
        default="development",
    )
    args = parser.parse_args(argv)
    if args.path and not any((args.logs, args.bank, args.reviewed, args.output_dir)):
        main(args.path)
        return 0
    corpus = load_canonical_corpus(
        log_glob=args.logs,
        bank_path=args.bank,
        reviewed_path=args.reviewed,
    )
    try:
        cyclic_template_classifier = DataTemplateClassifier(
            template_path=args.cyclic_template_pack,
            enable_cyclic_stupefy=True,
            reject_ambiguous=True,
            cyclic_stupefy_only=True,
        )
        samples, summary = evaluate_canonical_corpus(
            corpus,
            cyclic_template_classifier=cyclic_template_classifier,
            split_mode=args.split_mode,
            fold_count=args.folds,
            dataset_partition=args.partition,
        )
        summary["cyclic_template_pack"] = args.cyclic_template_pack
    except EvaluationDataError as exc:
        print(f"Evaluation data error: {exc}", file=sys.stderr)
        return 2
    if args.baseline_metrics:
        try:
            baseline_metrics = json.loads(
                Path(args.baseline_metrics).read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Baseline metrics error: {exc}", file=sys.stderr)
            return 2
        summary["comparison"] = compare_to_baseline(summary, baseline_metrics)
    if not samples:
        print("No labeled samples found.")
        return 1
    print(format_summary(summary))
    if args.output_dir:
        write_evaluation_artifacts(args.output_dir, summary, corpus, sys.argv if argv is None else argv)
        print(f"\nWrote evaluation artifacts to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
