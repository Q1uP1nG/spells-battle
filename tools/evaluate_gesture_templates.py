"""Offline evaluation for labeled CV gesture logs.

Usage:
    python tools/evaluate_gesture_templates.py logs/cv_sessions/session_20260619_095544.jsonl
"""
from __future__ import annotations

import json
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
from cv.gesture_pipeline import FusedGestureClassifier
from cv.template_classifier import DataTemplateClassifier
from cv.template_classifier import _dtw_distance, _normalize_trajectory, template_label_to_spell


TEMPLATE_SCORE_DISTANCE = 0.35
FOCUS_LABELS = ("circle", "overload")


@dataclass
class GestureSample:
    index: int
    label: str
    points: list
    normalized: Any
    attempt: Optional[int]
    logged_primary: Optional[str]
    logged_shadow: Optional[str]


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
        label = entry.get("intended_spell")
        points = entry.get("points") or []
        normalized = _normalize_trajectory(points)
        if not label or normalized is None:
            continue
        samples.append(
            GestureSample(
                index=len(samples),
                label=label,
                points=points,
                normalized=normalized,
                attempt=entry.get("training_attempt"),
                logged_primary=(entry.get("primary") or {}).get("spell"),
                logged_shadow=(entry.get("shadow") or {}).get("spell"),
            )
        )
    return samples


def classify_real_template(samples: list[GestureSample], sample_index: int) -> dict:
    target = samples[sample_index]
    matches = []
    for other_index, sample in enumerate(samples):
        if other_index == sample_index:
            continue
        distance = _dtw_distance(target.normalized, sample.normalized)
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


def template_scores_by_spell(samples: list[GestureSample], sample_index: int) -> dict[str, float]:
    result = classify_real_template(samples, sample_index)
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
) -> dict:
    sample = samples[sample_index]
    heuristic_scores = heuristic_scores_by_spell(sample)
    template_scores = template_scores_by_spell(samples, sample_index)
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
    cached_scores = [
        (heuristic_scores_by_spell(sample), template_scores_by_spell(samples, i))
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


def evaluate_samples(samples: list[GestureSample], data_template_classifier=None) -> dict:
    data_template_classifier = data_template_classifier or DataTemplateClassifier()
    fused_classifier = FusedGestureClassifier(template=data_template_classifier)
    methods = {
        "logged_primary": [],
        "current_heuristic": [],
        "logged_shadow": [],
        "real_template": [],
        "data_template": [],
        "fused": [],
        "hybrid_1_0_0_2": [],
    }
    misses = []

    for i, sample in enumerate(samples):
        current_spell, current_conf = classify_cv_gesture(sample.points, "left")
        template = classify_real_template(samples, i)
        data_template = data_template_classifier.classify(sample.points, "left")
        fused = fused_classifier.classify(sample.points, "left")
        hybrid = classify_hybrid(samples, i, heuristic_weight=1.0, template_weight=0.2)
        predictions = {
            "logged_primary": sample.logged_primary,
            "current_heuristic": current_spell,
            "logged_shadow": sample.logged_shadow,
            "real_template": template_label_to_spell(template["spell"]),
            "data_template": data_template.spell,
            "fused": fused.spell,
            "hybrid_1_0_0_2": template_label_to_spell(hybrid["spell"]),
        }
        for method, prediction in predictions.items():
            methods[method].append((sample.label, prediction))
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
                    "fused_reason": fused.reason,
                    "current_confidence": current_conf,
                    "points": len(sample.points),
                })

    method_summaries = {
        method: summarize_predictions(pairs)
        for method, pairs in methods.items()
    }
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
    return {
        "correct": correct,
        "total": len(pairs),
        "by_label": dict(by_label),
        "confusion": {label: dict(counter) for label, counter in confusion.items()},
    }


def format_summary(summary: dict) -> str:
    lines = [f"Total labeled samples: {summary['total']}", ""]
    for method in [
        "logged_primary",
        "current_heuristic",
        "logged_shadow",
        "real_template",
        "data_template",
        "fused",
        "hybrid_1_0_0_2",
    ]:
        result = summary[method]
        total = max(result["total"], 1)
        lines.append(f"{method}: {result['correct']}/{result['total']} ({result['correct'] / total:.1%})")
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
            for method in ["current_heuristic", "data_template", "fused", "real_template"]:
                data = summary[method]["by_label"].get(label, {"correct": 0, "total": 0})
                total = max(data["total"], 1)
                lines.append(
                    f"    {method}: {data['correct']}/{data['total']} "
                    f"({data['correct'] / total:.1%})"
                )

    important_misses = [
        miss for miss in summary["misses"]
        if miss["method"] in ("current_heuristic", "real_template", "data_template", "fused")
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


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/evaluate_gesture_templates.py <path_to_session.jsonl>")
        sys.exit(1)
    main(sys.argv[1])
