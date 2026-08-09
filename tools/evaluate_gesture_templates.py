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
from cv.gesture_pipeline import FusedGestureClassifier
from cv.template_classifier import DataTemplateClassifier
from cv.template_classifier import _dtw_distance, _normalize_trajectory, template_label_to_spell
from tools.gesture_corpus import CanonicalCorpus, load_canonical_corpus


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
    sample_id: str = ""
    session_id: str = "legacy"
    input_mode: str = "unknown"
    logged_primary_available: bool = False
    logged_shadow_available: bool = False


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
            )
        )
    return samples


def build_samples_from_corpus(corpus: CanonicalCorpus) -> list[GestureSample]:
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
        }
        for sample in corpus.samples
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
) -> dict:
    target = samples[sample_index]
    matches = []
    for other_index, sample in enumerate(samples):
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
    distance_cache = {}

    for i, sample in enumerate(samples):
        current_spell, current_conf = classify_cv_gesture(sample.points, "left")
        template = classify_real_template(samples, i, distance_cache)
        data_template = data_template_classifier.classify(sample.points, "left")
        fused = fused_classifier.classify(sample.points, "left")
        hybrid = classify_hybrid(
            samples,
            i,
            heuristic_weight=1.0,
            template_weight=0.2,
            distance_cache=distance_cache,
        )
        predictions = {
            "current_heuristic": current_spell,
            "real_template": template_label_to_spell(template["spell"]),
            "data_template": data_template.spell,
            "fused": fused.spell,
            "hybrid_1_0_0_2": template_label_to_spell(hybrid["spell"]),
        }
        if sample.logged_primary_available:
            predictions["logged_primary"] = sample.logged_primary
        if sample.logged_shadow_available:
            predictions["logged_shadow"] = sample.logged_shadow
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


def evaluate_canonical_corpus(corpus, data_template_classifier=None):
    samples = build_samples_from_corpus(corpus)
    return samples, evaluate_samples(samples, data_template_classifier=data_template_classifier)


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
            "real_template": "leave-one-out-dtw-v1",
        },
        "template_pack": _template_pack_manifest(),
        "corpus_version": corpus.audit.get("corpus_version"),
        "command": list(command),
        "corpus_audit": corpus.audit,
        "source_files": corpus.source_files,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    metrics = {"total": summary["total"], "methods": summary["methods"]}
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
    report_header = (
        "# Gesture Evaluation\n\n"
        "## Scope and limitations\n\n"
        f"{limitations}\n\n"
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
        labels = sorted(summary["fused"]["confusion"])
        predictions = sorted({
            str(prediction)
            for values in summary["fused"]["confusion"].values()
            for prediction in values
        })
        writer.writerow(["actual", *predictions])
        for label in labels:
            row = summary["fused"]["confusion"][label]
            writer.writerow([label, *[row.get(None if value == "None" else value, 0) for value in predictions]])
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
    args = parser.parse_args(argv)
    if args.path and not any((args.logs, args.bank, args.reviewed, args.output_dir)):
        main(args.path)
        return 0
    corpus = load_canonical_corpus(
        log_glob=args.logs,
        bank_path=args.bank,
        reviewed_path=args.reviewed,
    )
    samples, summary = evaluate_canonical_corpus(corpus)
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
