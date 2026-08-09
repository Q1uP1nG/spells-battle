"""Canonical ingestion for reviewed gesture trajectories.

The repository stores the same real trajectory through several views: raw CV
logs, the curated template bank, and the append-only review log.  This module
merges those views without treating them as independent samples.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import glob
import hashlib
import json
from pathlib import Path
from typing import Iterable, Optional


TRAJECTORY_LABELS = ("incendio", "circle", "glacius", "lumos", "overload")
LABEL_SET = frozenset(TRAJECTORY_LABELS)
SOURCE_PRIORITY = {"raw_log": 1, "bank": 2, "reviewed": 3}


def clean_points(points) -> list[list[float]]:
    cleaned = []
    for point in points or []:
        try:
            if len(point) < 2:
                continue
            cleaned.append([float(point[0]), float(point[1])])
        except (TypeError, ValueError, IndexError):
            continue
    return cleaned


def trajectory_fingerprint(points) -> str:
    """Stable exact-trajectory fingerprint used only for cross-view dedup."""
    cleaned = [[round(value, 4) for value in point] for point in clean_points(points)]
    payload = json.dumps(cleaned, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def normalized_source_file(value) -> str:
    if not value:
        return ""
    return Path(str(value).replace("\\", "/")).name.lower()


def source_attempt_key(source_file, source_attempt_id) -> str:
    filename = normalized_source_file(source_file)
    if not filename or source_attempt_id is None:
        return ""
    return f"{filename}:{source_attempt_id}"


@dataclass
class CanonicalGestureSample:
    sample_id: str
    label: str
    points: list[list[float]]
    source_file: str = ""
    source_attempt_id: object = None
    session_id: str = "legacy"
    input_mode: str = "unknown"
    side: str = "left"
    schema: int = 1
    review_status: str = "accepted"
    dataset_partition: str = "development"
    sources: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    _label_priority: int = field(default=0, repr=False)


@dataclass
class CanonicalCorpus:
    samples: list[CanonicalGestureSample]
    audit: dict
    source_files: list[str]


def load_canonical_corpus(
    *,
    log_glob: Optional[str] = None,
    bank_path: Optional[str | Path] = None,
    reviewed_path: Optional[str | Path] = None,
    include_raw_with_bank: bool = False,
    include_weak_labels: bool = False,
    min_confidence: float = 0.85,
) -> CanonicalCorpus:
    """Load one deduplicated corpus from raw, bank, and review views.

    A non-empty bank is the curated working view, so raw logs are candidates
    rather than automatically added ground truth.  Set ``include_raw_with_bank``
    only for audit tools that intentionally need both.
    """
    reviews, review_files, review_stats = _load_latest_reviews(reviewed_path)
    review_aliases = _review_aliases(reviews.values())
    candidates = []
    source_files = []

    bank_candidates, bank_files = _load_bank_candidates(bank_path)
    candidates.extend(bank_candidates)
    source_files.extend(bank_files)

    if log_glob and (include_raw_with_bank or not bank_candidates):
        raw_candidates, raw_files = _load_raw_candidates(
            log_glob,
            include_weak_labels=include_weak_labels,
            min_confidence=min_confidence,
        )
        candidates.extend(raw_candidates)
        source_files.extend(raw_files)

    # Accepted reviews not represented in the bank/raw source are still valid
    # candidates; aliases merge the common case back into the source record.
    for review in reviews.values():
        if review.get("review_status") == "accepted":
            candidate = _candidate_from_mapping(review, "reviewed", review.get("label"))
            if candidate is not None:
                candidates.append(candidate)
    source_files.extend(review_files)

    registry = _CanonicalRegistry(review_aliases)
    for candidate in candidates:
        registry.add(candidate)

    audit = {
        "schema": 2,
        "input_candidates": len(candidates),
        "canonical_samples": len(registry.samples),
        "duplicates_merged": registry.duplicates_merged,
        "discarded_by_review": registry.discarded_by_review,
        "label_conflicts": registry.label_conflicts,
        "missing_source": sum(1 for sample in registry.samples if not sample.source_file),
        "review_records": review_stats["records"],
        "latest_reviews": review_stats["latest"],
        "accepted_reviews": review_stats["accepted"],
        "discarded_reviews": review_stats["discarded"],
    }
    audit["corpus_version"] = _corpus_version(registry.samples)
    return CanonicalCorpus(
        samples=sorted(registry.samples, key=lambda sample: (sample.label, sample.sample_id)),
        audit=audit,
        source_files=sorted(set(source_files)),
    )


class _CanonicalRegistry:
    def __init__(self, review_aliases):
        self.samples: list[CanonicalGestureSample] = []
        self._lookup = {}
        self._review_aliases = review_aliases
        self.duplicates_merged = 0
        self.discarded_by_review = 0
        self.label_conflicts = []

    def add(self, candidate):
        aliases = _identity_aliases(candidate)
        decision = _lookup_review(self._review_aliases, aliases)
        if decision is not None:
            status = decision.get("review_status")
            if status in ("discarded", "skipped"):
                self.discarded_by_review += 1
                return
            if status == "accepted" and decision.get("label") in LABEL_SET:
                if candidate.get("label") and candidate["label"] != decision["label"]:
                    self.label_conflicts.append({
                        "sample_id": candidate.get("sample_id") or "legacy",
                        "kept": decision["label"],
                        "existing": candidate["label"],
                        "incoming": decision["label"],
                    })
                candidate["label"] = decision["label"]
                candidate["label_priority"] = SOURCE_PRIORITY["reviewed"]
                aliases.update(_identity_aliases(decision))

        strong_aliases = {alias for alias in aliases if not alias.startswith("trajectory:")}
        strong_matches = {self._lookup[alias] for alias in strong_aliases if alias in self._lookup}
        aliases_to_match = strong_aliases if strong_matches else aliases
        matching_indices = set()
        for alias in aliases_to_match:
            if alias not in self._lookup:
                continue
            index = self._lookup[alias]
            # An exact trajectory is a fallback cross-view identity, not proof
            # that two separately recorded slots in the same source are one
            # sample. Explicit sample/source IDs still deduplicate normally.
            if alias.startswith("trajectory:") and candidate.get("source") in self.samples[index].sources:
                continue
            matching_indices.add(index)
        matching = sorted(matching_indices)
        if not matching:
            sample = _sample_from_candidate(candidate)
            index = len(self.samples)
            self.samples.append(sample)
            for alias in aliases:
                self._lookup[alias] = index
            return

        target_index = matching[0]
        target = self.samples[target_index]
        self.duplicates_merged += 1
        self._merge(target, candidate)
        for alias in aliases:
            self._lookup[alias] = target_index

        # A candidate can bridge records that entered through different legacy
        # aliases. Consolidate them rather than leaving two canonical samples.
        for other_index in reversed(matching[1:]):
            other = self.samples[other_index]
            self._merge(target, {
                "label": other.label,
                "points": other.points,
                "source": other.sources[-1] if other.sources else "raw_log",
                "label_priority": other._label_priority,
                "sample_id": other.sample_id,
                "source_file": other.source_file,
                "source_attempt_id": other.source_attempt_id,
                "session_id": other.session_id,
                "input_mode": other.input_mode,
                "side": other.side,
                "schema": other.schema,
                "dataset_partition": other.dataset_partition,
                "metadata": other.metadata,
            })
            del self.samples[other_index]
            self._lookup = {
                alias: (index - 1 if index > other_index else index)
                for alias, index in self._lookup.items()
                if index != other_index
            }

    def _merge(self, target, candidate):
        source = candidate.get("source", "unknown")
        if source not in target.sources:
            target.sources.append(source)
        incoming_label = candidate.get("label")
        incoming_priority = int(candidate.get("label_priority", 0))
        if incoming_label and incoming_label != target.label:
            self.label_conflicts.append({
                "sample_id": target.sample_id,
                "kept": target.label if target._label_priority >= incoming_priority else incoming_label,
                "existing": target.label,
                "incoming": incoming_label,
            })
            if incoming_priority > target._label_priority:
                target.label = incoming_label
                target._label_priority = incoming_priority
        if target.sample_id.startswith("legacy:") and candidate.get("sample_id"):
            target.sample_id = str(candidate["sample_id"])
        if not target.source_file and candidate.get("source_file"):
            target.source_file = str(candidate["source_file"])
        if target.source_attempt_id is None and candidate.get("source_attempt_id") is not None:
            target.source_attempt_id = candidate["source_attempt_id"]
        if target.input_mode == "unknown" and candidate.get("input_mode"):
            target.input_mode = str(candidate["input_mode"])
        if candidate.get("dataset_partition") == "locked":
            target.dataset_partition = "locked"
        target.metadata.update(candidate.get("metadata") or {})


def _sample_from_candidate(candidate) -> CanonicalGestureSample:
    points = clean_points(candidate.get("points"))
    fingerprint = trajectory_fingerprint(points)
    label = candidate["label"]
    source_file = str(candidate.get("source_file") or "")
    attempt = candidate.get("source_attempt_id")
    sample_id = str(candidate.get("sample_id") or "")
    if not sample_id:
        source_key = source_attempt_key(source_file, attempt)
        sample_id = source_key or f"legacy:{label}:{fingerprint[:20]}"
    session_id = str(candidate.get("session_id") or Path(source_file).stem or "legacy")
    return CanonicalGestureSample(
        sample_id=sample_id,
        label=label,
        points=points,
        source_file=source_file,
        source_attempt_id=attempt,
        session_id=session_id,
        input_mode=str(candidate.get("input_mode") or "unknown"),
        side=str(candidate.get("side") or "left"),
        schema=int(candidate.get("schema") or 1),
        dataset_partition=str(candidate.get("dataset_partition") or "development"),
        sources=[str(candidate.get("source") or "unknown")],
        metadata=dict(candidate.get("metadata") or {}),
        _label_priority=int(candidate.get("label_priority") or 0),
    )


def _candidate_from_mapping(entry, source, label=None, source_file=None):
    points = clean_points(entry.get("points"))
    label = label or entry.get("label") or entry.get("intended_spell")
    if label not in LABEL_SET or len(points) < 2:
        return None
    actual_source_file = entry.get("source_file") or source_file or ""
    attempt = entry.get("source_attempt_id")
    if attempt is None:
        attempt = entry.get("attempt_id") or entry.get("training_attempt")
    return {
        "sample_id": entry.get("sample_id"),
        "label": label,
        "points": points,
        "source": source,
        "label_priority": SOURCE_PRIORITY[source],
        "source_file": str(actual_source_file),
        "source_attempt_id": attempt,
        "session_id": entry.get("session_id") or Path(str(actual_source_file)).stem,
        "input_mode": entry.get("input_mode") or entry.get("mode"),
        "side": entry.get("side"),
        "schema": entry.get("schema", 1),
        "dataset_partition": entry.get("dataset_partition") or "development",
        "metadata": {
            name: entry.get(name)
            for name in (
                "device_id",
                "user_id",
                "frame_width",
                "frame_height",
                "fps_estimate",
                "palm_scale",
                "primary",
                "shadow",
                "classifier_version",
                "derived_from_sample_id",
            )
            if entry.get(name) is not None
        },
    }


def _corpus_version(samples) -> str:
    payload = [
        {
            "sample_id": sample.sample_id,
            "label": sample.label,
            "dataset_partition": sample.dataset_partition,
            "trajectory": trajectory_fingerprint(sample.points),
        }
        for sample in sorted(samples, key=lambda item: (item.sample_id, item.label))
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"sha256:{hashlib.sha256(encoded.encode('ascii')).hexdigest()}"


def _identity_aliases(candidate) -> set[str]:
    aliases = {f"trajectory:{trajectory_fingerprint(candidate.get('points'))}"}
    if candidate.get("sample_id"):
        aliases.add(f"sample:{candidate['sample_id']}")
    source_key = source_attempt_key(candidate.get("source_file"), candidate.get("source_attempt_id"))
    if source_key:
        aliases.add(f"source:{source_key}")
    return aliases


def _lookup_review(review_aliases, aliases):
    strong = [
        review_aliases[alias]
        for alias in aliases
        if not alias.startswith("trajectory:")
        and alias in review_aliases
        and review_aliases[alias] is not None
    ]
    if strong:
        return strong[-1]
    trajectory = [
        review_aliases[alias]
        for alias in aliases
        if alias.startswith("trajectory:")
        and alias in review_aliases
        and review_aliases[alias] is not None
    ]
    return trajectory[-1] if trajectory else None


def _review_aliases(reviews: Iterable[dict]):
    aliases = {}
    for review in reviews:
        for alias in _identity_aliases(review):
            existing = aliases.get(alias)
            if existing is not None and existing.get("sample_id") != review.get("sample_id"):
                # An identical trajectory can be recorded more than once. It
                # is unsafe to apply either review through this weak alias.
                aliases[alias] = None
            elif alias not in aliases:
                aliases[alias] = review
    return aliases


def _load_latest_reviews(path_value):
    if not path_value:
        return {}, [], {"records": 0, "latest": 0, "accepted": 0, "discarded": 0}
    path = Path(path_value)
    if not path.exists():
        return {}, [], {"records": 0, "latest": 0, "accepted": 0, "discarded": 0}
    latest = {}
    records = 0
    for index, entry in enumerate(_read_jsonl(path)):
        records += 1
        key = entry.get("sample_id") or source_attempt_key(
            entry.get("source_file"), entry.get("source_attempt_id")
        ) or f"trajectory:{trajectory_fingerprint(entry.get('points'))}:{index}"
        latest[str(key)] = entry
    accepted = sum(1 for entry in latest.values() if entry.get("review_status") == "accepted")
    discarded = sum(1 for entry in latest.values() if entry.get("review_status") == "discarded")
    return latest, [str(path)], {
        "records": records,
        "latest": len(latest),
        "accepted": accepted,
        "discarded": discarded,
    }


def _load_bank_candidates(path_value):
    if not path_value:
        return [], []
    path = Path(path_value)
    if not path.exists():
        return [], []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], [str(path)]
    slots = payload.get("slots")
    if not isinstance(slots, dict):
        return [], [str(path)]
    candidates = []
    for slot_label, entries in slots.items():
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            candidate = _candidate_from_mapping(entry, "bank", slot_label)
            if candidate is not None:
                candidates.append(candidate)
    return candidates, [str(path)]


def _load_raw_candidates(log_glob, include_weak_labels=False, min_confidence=0.85):
    candidates = []
    files = sorted(glob.glob(str(log_glob)))
    for filename in files:
        path = Path(filename)
        for index, entry in enumerate(_read_jsonl(path)):
            mapping = dict(entry)
            label = mapping.get("intended_spell")
            if label not in LABEL_SET and include_weak_labels:
                primary = mapping.get("primary") or {}
                proposed = primary.get("spell")
                if (
                    proposed in LABEL_SET
                    and float(primary.get("confidence") or 0.0) >= float(min_confidence)
                    and mapping.get("cast_success")
                    and len(clean_points(mapping.get("points"))) >= 8
                ):
                    label = proposed
                    mapping["intended_spell"] = label
            if label not in LABEL_SET:
                continue
            attempt = mapping.get("attempt_id", index + 1)
            mapping.setdefault("sample_id", f"{path.name}:{attempt}")
            mapping.setdefault("source_attempt_id", attempt)
            candidate = _candidate_from_mapping(mapping, "raw_log", source_file=str(path))
            if candidate is not None:
                candidates.append(candidate)
    return candidates, files


def _read_jsonl(path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries = []
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries
