"""Build a representative DTW template pack from labeled CV trajectories.

Usage:
    python tools/train_gesture_templates.py
    python tools/train_gesture_templates.py --min-samples 6 --k 3
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cv.template_classifier import TARGET_POINT_COUNT, _dtw_distance, _normalize_trajectory, template_label_to_spell
from tools.gesture_corpus import load_canonical_corpus

TRAJECTORY_SPELLS = ("incendio", "circle", "glacius", "lumos", "overload")
DEFAULT_LOG_GLOB = "logs/cv_sessions/*.jsonl"
DEFAULT_OUTPUT = "models/gesture_templates.json"
DEFAULT_BANK = "models/gesture_template_bank.json"
DEFAULT_REVIEWED = "models/gesture_reviewed_samples.jsonl"

DEFAULT_K = 3
DEFAULT_MIN_SAMPLES = 8
DEFAULT_MIN_CONFIDENCE = 0.85
KMEDOIDS_MAX_ITERATIONS = 25


def load_labeled_trajectories(
    log_glob,
    min_confidence=DEFAULT_MIN_CONFIDENCE,
    include_weak_labels=False,
    bank_path=None,
    reviewed_path=None,
):
    buckets = {spell: [] for spell in TRAJECTORY_SPELLS}
    records = {spell: [] for spell in TRAJECTORY_SPELLS}
    corpus = load_canonical_corpus(
        log_glob=log_glob,
        bank_path=bank_path,
        reviewed_path=reviewed_path,
        include_weak_labels=include_weak_labels,
        min_confidence=min_confidence,
    )
    for sample in corpus.samples:
        if sample.dataset_partition == "locked":
            continue
        normalized = _normalize_trajectory(sample.points)
        if normalized is None or normalized.shape != (TARGET_POINT_COUNT, 2):
            continue
        normalized = normalized.astype(np.float32)
        buckets[sample.label].append(normalized)
        records[sample.label].append({
            "sample_id": sample.sample_id,
            "source_file": sample.source_file,
            "session_id": sample.session_id,
            "normalized": normalized,
        })
    load_labeled_trajectories.last_audit = corpus.audit
    load_labeled_trajectories.last_records = records
    return buckets, corpus.source_files


load_labeled_trajectories.last_audit = {}
load_labeled_trajectories.last_records = {}


def _pairwise_dtw(samples):
    count = len(samples)
    distances = np.zeros((count, count), dtype=np.float64)
    for i in range(count):
        for j in range(i + 1, count):
            distance = _dtw_distance(samples[i], samples[j])
            distances[i, j] = distances[j, i] = distance
    return distances


def kmedoids(samples, k):
    count = len(samples)
    k = max(1, min(int(k), count))
    distances = _pairwise_dtw(samples)
    medoids = [int(np.argmin(distances.sum(axis=1)))]
    while len(medoids) < k:
        nearest = distances[:, medoids].min(axis=1)
        medoids.append(int(np.argmax(nearest)))

    labels = np.zeros(count, dtype=int)
    for _ in range(KMEDOIDS_MAX_ITERATIONS):
        labels = np.argmin(distances[:, medoids], axis=1)
        next_medoids = []
        for cluster in range(len(medoids)):
            members = np.where(labels == cluster)[0]
            if len(members) == 0:
                next_medoids.append(medoids[cluster])
                continue
            sub = distances[np.ix_(members, members)]
            next_medoids.append(int(members[np.argmin(sub.sum(axis=1))]))
        if next_medoids == medoids:
            break
        medoids = next_medoids
    return medoids, labels, distances


def _trajectory_cache_key(sample):
    array = np.asarray(sample, dtype=np.float32)
    return hashlib.sha256(array.tobytes()).digest()


def _cached_dtw_distance(first, second, cache):
    first_key = _trajectory_cache_key(first)
    second_key = _trajectory_cache_key(second)
    key = tuple(sorted((first_key, second_key)))
    if key not in cache:
        cache[key] = _dtw_distance(first, second)
    return cache[key]


def _nearest_distance(sample, prototypes, cache=None):
    cache = cache if cache is not None else {}
    return min(_cached_dtw_distance(sample, prototype, cache) for prototype in prototypes)


def _optimize_global_threshold(prototype_arrays, buckets):
    """Bayes-optimal global threshold: midpoint between the farthest correct
    nearest-prototype match and the nearest incorrect nearest-prototype match."""
    correct_distances = []
    incorrect_distances = []
    distance_cache = {}

    for true_spell, samples in buckets.items():
        if true_spell not in prototype_arrays:
            continue
        for sample in samples:
            nearest_spell = None
            nearest_dist = float("inf")
            for proto_spell, proto_list in prototype_arrays.items():
                dist = _nearest_distance(sample, proto_list, distance_cache)
                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest_spell = proto_spell
            if nearest_spell == true_spell:
                correct_distances.append(nearest_dist)
            else:
                incorrect_distances.append(nearest_dist)

    if not correct_distances:
        return 0.0
    if not incorrect_distances:
        return float(max(correct_distances) * 1.2)

    accept_bound = max(correct_distances)
    reject_bound = min(incorrect_distances)
    return float((accept_bound + reject_bound) / 2.0)


def build_prototypes(buckets, k=DEFAULT_K, min_samples=DEFAULT_MIN_SAMPLES):
    prototype_arrays = {}
    source_counts = {spell: len(samples) for spell, samples in buckets.items()}

    for spell, samples in buckets.items():
        if len(samples) < min_samples:
            continue
        medoids, _labels, _distances = kmedoids(samples, k)
        prototype_arrays[spell] = [samples[index] for index in medoids]

    global_threshold = _optimize_global_threshold(prototype_arrays, buckets)

    prototypes = {}
    thresholds = {}
    for spell, spell_prototypes in prototype_arrays.items():
        output_key = template_label_to_spell(spell)
        prototypes[output_key] = [prototype.tolist() for prototype in spell_prototypes]
        thresholds[output_key] = float(global_threshold)

    return prototypes, thresholds, source_counts


def _percentile(values, percentile, default=0.0):
    if not values:
        return float(default)
    return float(np.percentile(np.asarray(values, dtype=np.float64), percentile))


def _calibrate_pack(prototype_arrays, buckets):
    """Calibrate per-spell acceptance and normalized-ratio margin on development data."""
    if not prototype_arrays:
        return {}, {}, []
    own_distances = {spell: [] for spell in prototype_arrays}
    other_distances = {spell: [] for spell in prototype_arrays}
    sample_rows = []
    distance_cache = {}
    for true_spell, samples in buckets.items():
        for sample_index, sample in enumerate(samples):
            distances = {
                spell: _nearest_distance(sample, prototypes, distance_cache)
                for spell, prototypes in prototype_arrays.items()
            }
            for spell, distance in distances.items():
                target = own_distances if spell == true_spell else other_distances
                target[spell].append(distance)
            sample_rows.append((true_spell, sample_index, distances))

    thresholds = {}
    for spell in prototype_arrays:
        positive = _percentile(own_distances[spell], 95, default=0.0)
        negative = _percentile(other_distances[spell], 5, default=positive * 1.2)
        thresholds[spell] = float((positive + negative) / 2.0 if negative > positive else positive)
        thresholds[spell] = max(thresholds[spell], 1e-6)

    correct_margins = {spell: [] for spell in prototype_arrays}
    evaluated_rows = []
    for true_spell, sample_index, distances in sample_rows:
        ranked = sorted(
            (
                {
                    "spell": spell,
                    "distance": distance,
                    "ratio": distance / thresholds[spell],
                }
                for spell, distance in distances.items()
            ),
            key=lambda item: (item["ratio"], item["distance"], item["spell"]),
        )
        best = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None
        margin = second["ratio"] - best["ratio"] if second else float("inf")
        if best["spell"] == true_spell and np.isfinite(margin):
            correct_margins[true_spell].append(float(margin))
        evaluated_rows.append({
            "true_spell": true_spell,
            "sample_index": sample_index,
            "prediction": best["spell"],
            "distance": best["distance"],
            "ratio": best["ratio"],
            "margin": margin,
        })

    margin_thresholds = {
        spell: max(0.0, _percentile(correct_margins[spell], 10, default=0.0))
        for spell in prototype_arrays
    }
    return thresholds, margin_thresholds, evaluated_rows


def build_template_pack(records, k=DEFAULT_K, min_samples=DEFAULT_MIN_SAMPLES):
    """Select traceable medoids and produce a candidate Schema v2 template pack."""
    prototype_arrays = {}
    medoid_indices = {}
    cluster_summary = {}
    source_counts = {spell: len(records.get(spell, [])) for spell in TRAJECTORY_SPELLS}
    buckets = {
        spell: [record["normalized"] for record in records.get(spell, [])]
        for spell in TRAJECTORY_SPELLS
    }
    for spell, samples in buckets.items():
        if len(samples) < min_samples:
            continue
        medoids, labels, _distances = kmedoids(samples, k)
        medoid_indices[spell] = medoids
        prototype_arrays[spell] = [samples[index] for index in medoids]
        cluster_summary[template_label_to_spell(spell)] = {
            "source_count": len(samples),
            "prototype_count": len(medoids),
            "cluster_sizes": [int(np.sum(labels == cluster)) for cluster in range(len(medoids))],
            "session_count": len({record.get("session_id") or "legacy" for record in records[spell]}),
        }

    thresholds, margin_thresholds, evaluated_rows = _calibrate_pack(prototype_arrays, buckets)
    prototypes = {}
    for spell, medoids in medoid_indices.items():
        output_spell = template_label_to_spell(spell)
        prototypes[output_spell] = []
        for medoid_index in medoids:
            record = records[spell][medoid_index]
            source_id = str(record.get("sample_id") or f"{spell}-{medoid_index}")
            prototypes[output_spell].append({
                "prototype_id": f"{output_spell}:medoid:{source_id}",
                "source_sample_id": source_id,
                "source_file": record.get("source_file") or "",
                "session_id": record.get("session_id") or "legacy",
                "points": record["normalized"].tolist(),
            })

    outliers = []
    for row in evaluated_rows:
        output_true = template_label_to_spell(row["true_spell"])
        output_prediction = template_label_to_spell(row["prediction"])
        margin_threshold = margin_thresholds.get(row["true_spell"], 0.0)
        if (
            output_prediction != output_true
            or row["ratio"] > 1.0
            or row["margin"] < margin_threshold
        ):
            record = records[row["true_spell"]][row["sample_index"]]
            outliers.append({
                "sample_id": record.get("sample_id") or "",
                "label": output_true,
                "prediction": output_prediction,
                "best_distance": row["distance"],
                "distance_ratio": row["ratio"],
                "margin": row["margin"],
            })

    return {
        "prototypes": prototypes,
        "thresholds": {
            template_label_to_spell(spell): float(value)
            for spell, value in thresholds.items()
        },
        "margin_thresholds": {
            template_label_to_spell(spell): float(value)
            for spell, value in margin_thresholds.items()
        },
        "source_samples": source_counts,
        "cluster_summary": cluster_summary,
        "outliers": outliers,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs", default=DEFAULT_LOG_GLOB)
    parser.add_argument("--bank", default=None)
    parser.add_argument("--reviewed", default=None)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--k", type=int, default=DEFAULT_K, help="prototype count per spell")
    parser.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONFIDENCE)
    parser.add_argument(
        "--allow-cyclic-reverse",
        action="store_true",
        help="allow reversed point order only for the Stupefy cyclic candidate",
    )
    parser.add_argument(
        "--include-weak-labels",
        action="store_true",
        help="also include successful high-confidence gameplay casts as weak labels",
    )
    args = parser.parse_args(argv)

    bank_path = args.bank
    if bank_path is None and args.logs == DEFAULT_LOG_GLOB and Path(DEFAULT_BANK).exists():
        bank_path = DEFAULT_BANK
    reviewed_path = args.reviewed
    if reviewed_path is None and args.logs == DEFAULT_LOG_GLOB and Path(DEFAULT_REVIEWED).exists():
        reviewed_path = DEFAULT_REVIEWED

    buckets, files = load_labeled_trajectories(
        args.logs,
        min_confidence=args.min_confidence,
        include_weak_labels=args.include_weak_labels,
        bank_path=bank_path,
        reviewed_path=reviewed_path,
    )
    print(f"Scanned {len(files)} corpus source files")
    audit = getattr(load_labeled_trajectories, "last_audit", {})
    if audit:
        print(
            "Canonical corpus: "
            f"{audit.get('canonical_samples', 0)} samples, "
            f"{audit.get('duplicates_merged', 0)} duplicates merged, "
            f"{audit.get('discarded_by_review', 0)} discarded by review"
        )
    for spell in TRAJECTORY_SPELLS:
        print(f"  {spell:10s}: {len(buckets[spell])} usable trajectories")

    records = getattr(load_labeled_trajectories, "last_records", {})
    pack = build_template_pack(
        records,
        k=args.k,
        min_samples=args.min_samples,
    )
    prototypes = pack["prototypes"]
    thresholds = pack["thresholds"]
    if not prototypes:
        print("No spell had enough samples; nothing written.")
        return 1

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        git_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        git_commit = "unknown"
    command = ["tools/train_gesture_templates.py"] + list(sys.argv[1:] if argv is None else argv)
    payload = {
        "version": 2,
        "schema_version": 2,
        "created": datetime.now(timezone.utc).isoformat(),
        "target_point_count": TARGET_POINT_COUNT,
        "k": args.k,
        "min_samples": args.min_samples,
        "include_weak_labels": bool(args.include_weak_labels),
        "dataset_partition": "development",
        "source_samples": pack["source_samples"],
        "prototypes": prototypes,
        "thresholds": thresholds,
        "margin_thresholds": pack["margin_thresholds"],
        "cyclic_dtw": {
            "spell": "stupefy",
            "shifts": TARGET_POINT_COUNT,
            "allow_reverse": bool(args.allow_cyclic_reverse),
            "shadow_only": True,
        },
        "cluster_summary": pack["cluster_summary"],
        "development_fold_summary": {
            "partition": "development",
            "canonical_samples": audit.get("canonical_samples", 0),
            "corpus_version": audit.get("corpus_version"),
            "locked_samples_used": 0,
        },
        "outliers": pack["outliers"],
        "build": {
            "command": command,
            "git_commit": git_commit,
        },
    }
    output_path.write_text(json.dumps(payload), encoding="utf-8")

    print(f"\nWrote {output_path}")
    for spell, prototypes_for_spell in sorted(prototypes.items()):
        print(
            f"  {spell:10s}: {len(prototypes_for_spell)} prototypes "
            f"accept<{thresholds[spell]:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
