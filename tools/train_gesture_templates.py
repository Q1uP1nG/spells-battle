"""Build a representative DTW template pack from labeled CV trajectories.

Usage:
    python tools/train_gesture_templates.py
    python tools/train_gesture_templates.py --min-samples 6 --k 3
"""
from __future__ import annotations

import argparse
import json
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
    corpus = load_canonical_corpus(
        log_glob=log_glob,
        bank_path=bank_path,
        reviewed_path=reviewed_path,
        include_weak_labels=include_weak_labels,
        min_confidence=min_confidence,
    )
    for sample in corpus.samples:
        normalized = _normalize_trajectory(sample.points)
        if normalized is None or normalized.shape != (TARGET_POINT_COUNT, 2):
            continue
        buckets[sample.label].append(normalized.astype(np.float32))
    load_labeled_trajectories.last_audit = corpus.audit
    return buckets, corpus.source_files


load_labeled_trajectories.last_audit = {}


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


def _nearest_distance(sample, prototypes):
    return min(_dtw_distance(sample, prototype) for prototype in prototypes)


def _optimize_global_threshold(prototype_arrays, buckets):
    """Bayes-optimal global threshold: midpoint between the farthest correct
    nearest-prototype match and the nearest incorrect nearest-prototype match."""
    correct_distances = []
    incorrect_distances = []

    for true_spell, samples in buckets.items():
        if true_spell not in prototype_arrays:
            continue
        for sample in samples:
            nearest_spell = None
            nearest_dist = float("inf")
            for proto_spell, proto_list in prototype_arrays.items():
                dist = _nearest_distance(sample, proto_list)
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

    prototypes, thresholds, source_counts = build_prototypes(
        buckets,
        k=args.k,
        min_samples=args.min_samples,
    )
    if not prototypes:
        print("No spell had enough samples; nothing written.")
        return 1

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "created": datetime.now(timezone.utc).isoformat(),
        "target_point_count": TARGET_POINT_COUNT,
        "k": args.k,
        "min_samples": args.min_samples,
        "include_weak_labels": bool(args.include_weak_labels),
        "source_samples": source_counts,
        "prototypes": prototypes,
        "thresholds": thresholds,
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
