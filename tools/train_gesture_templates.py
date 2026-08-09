"""Train learned DTW gesture templates from labeled CV session logs.

Usage:
    python tools/train_gesture_templates.py
    python tools/train_gesture_templates.py --min-samples 6 --k 3
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cv.template_classifier import TARGET_POINT_COUNT, _dtw_distance, _normalize_trajectory, template_label_to_spell

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
    bank_count = _load_bank_trajectories(bank_path, buckets)
    reviewed_count = _load_reviewed_trajectories(reviewed_path, buckets)
    if bank_count > 0:
        sources = [str(bank_path)]
        if reviewed_count > 0:
            sources.append(str(reviewed_path))
        return buckets, sources

    files = sorted(glob.glob(str(log_glob)))
    for path in files:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                spell = _record_label(record, min_confidence, include_weak_labels)
                if spell is None:
                    continue
                normalized = _normalize_trajectory(record.get("points") or [])
                if normalized is None or normalized.shape != (TARGET_POINT_COUNT, 2):
                    continue
                buckets[spell].append(normalized.astype(np.float32))
    if reviewed_count > 0:
        files.append(str(reviewed_path))
    return buckets, files


def _load_bank_trajectories(bank_path, buckets):
    if not bank_path:
        return 0
    path = Path(bank_path)
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    slots = data.get("slots")
    if not isinstance(slots, dict):
        return 0

    count = 0
    for spell in TRAJECTORY_SPELLS:
        for entry in slots.get(spell, []) or []:
            if not isinstance(entry, dict):
                continue
            normalized = _normalize_trajectory(entry.get("points") or [])
            if normalized is None or normalized.shape != (TARGET_POINT_COUNT, 2):
                continue
            buckets[spell].append(normalized.astype(np.float32))
            count += 1
    return count


def _load_reviewed_trajectories(reviewed_path, buckets):
    if not reviewed_path:
        return 0
    path = Path(reviewed_path)
    if not path.exists():
        return 0

    count = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    latest_by_sample = {}
    anonymous_index = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        sample_key = entry.get("sample_id")
        if sample_key is None:
            anonymous_index += 1
            sample_key = f"__anonymous_{anonymous_index}"
        latest_by_sample[str(sample_key)] = entry

    for entry in latest_by_sample.values():
        if entry.get("review_status") != "accepted":
            continue
        label = entry.get("label")
        if label not in TRAJECTORY_SPELLS:
            continue
        normalized = _normalize_trajectory(entry.get("points") or [])
        if normalized is None or normalized.shape != (TARGET_POINT_COUNT, 2):
            continue
        buckets[label].append(normalized.astype(np.float32))
        count += 1
    return count


def _record_label(record, min_confidence, include_weak_labels):
    intended = record.get("intended_spell")
    if intended in TRAJECTORY_SPELLS:
        return intended
    if not include_weak_labels:
        return None
    primary = record.get("primary") or {}
    spell = primary.get("spell")
    if (
        spell in TRAJECTORY_SPELLS
        and float(primary.get("confidence") or 0.0) >= min_confidence
        and record.get("cast_success")
        and len(record.get("points") or []) >= 8
    ):
        return spell
    return None


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
        help="also learn from successful high-confidence gameplay casts",
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
    print(f"Scanned {len(files)} log files")
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
