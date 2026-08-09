from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import glob
import json
from pathlib import Path

from config import SPELLS


TRAINING_LABELS = {
    "incendio": {"label": SPELLS["incendio"]["label"], "spell": "incendio", "name": "Incendio"},
    "circle": {"label": "CIR", "spell": "stupefy", "name": "Stupefy circle"},
    "glacius": {"label": SPELLS["glacius"]["label"], "spell": "glacius", "name": "Glacius"},
    "lumos": {"label": SPELLS["lumos"]["label"], "spell": "lumos", "name": "Lumos"},
    "overload": {"label": SPELLS["overload"]["label"], "spell": "overload", "name": "Overload zigzag"},
}

DEFAULT_TRAINING_SPELLS = ("incendio", "circle", "glacius", "lumos", "overload")
DEFAULT_BANK_SLOT_COUNT = 30
DEFAULT_TRAINING_PROGRESS_PATH = Path("logs/cv_training/progress.json")
DEFAULT_TEMPLATE_BANK_PATH = Path("models/gesture_template_bank.json")
DEFAULT_TEMPLATE_LOG_GLOB = "logs/cv_sessions/*.jsonl"
DEFAULT_REVIEWED_SAMPLES_PATH = Path("models/gesture_reviewed_samples.jsonl")
EVALUATION_METADATA_FIELDS = (
    "schema",
    "sample_id",
    "session_id",
    "source_file",
    "source_attempt_id",
    "attempt_id",
    "input_mode",
    "mode",
    "user_id",
    "device_id",
    "frame_width",
    "frame_height",
    "fps_estimate",
    "palm_scale",
    "classifier_version",
    "pipeline_version",
    "review_status",
    "dataset_partition",
    "derived_from_sample_id",
)


def get_training_label(label):
    return TRAINING_LABELS.get(label, TRAINING_LABELS["incendio"])


def training_label_to_spell(label):
    return get_training_label(label)["spell"]


def _copy_points(points):
    copied = []
    for point in points or []:
        try:
            if len(point) < 2:
                continue
            x = float(point[0])
            y = float(point[1])
        except (TypeError, ValueError, IndexError):
            continue
        copied.append([x, y])
    return copied


def default_template_points(label):
    """Return a built-in normalized display template for an empty slot."""
    from cv.template_classifier import TEMPLATES

    template_key = "stupefy" if label == "circle" else label
    template = TEMPLATES.get(template_key)
    if template is None:
        return []
    return template.astype(float).tolist()


class GestureTemplateBank:
    """Persistent gesture template bank used by CV Bank mode."""

    def __init__(
        self,
        path=None,
        labels=None,
        slot_count=DEFAULT_BANK_SLOT_COUNT,
        log_glob=DEFAULT_TEMPLATE_LOG_GLOB,
        migrate_from_logs=True,
    ):
        self.path = Path(path) if path else None
        self.labels = tuple(labels or DEFAULT_TRAINING_SPELLS)
        self.slot_count = int(slot_count)
        self.slots = {
            label: [None for _ in range(self.slot_count)]
            for label in self.labels
        }
        loaded = self._load()
        if migrate_from_logs and (not loaded or self.is_empty):
            self._migrate_from_logs(log_glob)
            self.save()

    @property
    def is_empty(self):
        return all(self.count(label) == 0 for label in self.labels)

    def slot(self, label, index):
        if label not in self.slots or not 0 <= int(index) < self.slot_count:
            return None
        entry = self.slots[label][int(index)]
        if not isinstance(entry, dict) or not _copy_points(entry.get("points")):
            return None
        return entry

    def has_recorded_slot(self, label, index):
        return self.slot(label, index) is not None

    def count(self, label):
        return sum(1 for index in range(len(self.slots.get(label, []))) if self.has_recorded_slot(label, index))

    def first_empty_index(self, label):
        slots = self.slots.get(label, [])
        for index, slot in enumerate(slots):
            if slot is None:
                return index
        return max(0, len(slots) - 1)

    def display_points(self, label, index):
        slot = self.slot(label, index)
        if slot is not None:
            return _copy_points(slot.get("points"))
        return default_template_points(label)

    def set_slot(self, label, index, event, source="manual"):
        if label not in self.slots:
            self.slots[label] = [None for _ in range(self.slot_count)]
        index = max(0, min(int(index), self.slot_count - 1))
        points = _copy_points(event.get("points") or [])
        if not points:
            self.slots[label][index] = None
            self.save()
            return None
        entry = {
            "label": label,
            "points": points,
            "source": source,
            "source_label": event.get("intended_spell") or label,
            "primary": deepcopy(event.get("primary") or {}),
        }
        for name in EVALUATION_METADATA_FIELDS:
            if event.get(name) is not None:
                entry[name] = deepcopy(event[name])
        self.slots[label][index] = entry
        self.save()
        return entry

    def clear_slot(self, label, index):
        if label not in self.slots:
            return False
        index = max(0, min(int(index), self.slot_count - 1))
        changed = self.slots[label][index] is not None
        self.slots[label][index] = None
        if changed:
            self.save()
        return changed

    def save(self):
        if self.path is None:
            return
        payload = {
            "schema": 1,
            "slot_count": self.slot_count,
            "labels": list(self.labels),
            "slots": self.slots,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _load(self):
        if self.path is None or not self.path.exists():
            return False
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False

        raw_slots = data.get("slots")
        if not isinstance(raw_slots, dict):
            return False

        for label in self.labels:
            source_slots = raw_slots.get(label, [])
            if not isinstance(source_slots, list):
                continue
            for index, entry in enumerate(source_slots[: self.slot_count]):
                if isinstance(entry, dict) and _copy_points(entry.get("points")):
                    self.slots[label][index] = entry
        return True

    def _migrate_from_logs(self, log_glob):
        for log_path in sorted(glob.glob(str(log_glob))):
            try:
                lines = Path(log_path).read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                label = event.get("intended_spell")
                if label is None or label not in self.slots:
                    continue
                points = _copy_points(event.get("points") or [])
                if len(points) < 2:
                    continue
                index = self.first_empty_index(label)
                if self.has_recorded_slot(label, index):
                    continue
                migrated = deepcopy(event)
                migrated["points"] = points
                entry = self.set_slot(label, index, migrated, source="migrated_log")
                entry["source_file"] = str(log_path)
                entry["source_label"] = event.get("intended_spell")
                self.save()


def promote_reviewed_samples_to_bank(
    bank_path=DEFAULT_TEMPLATE_BANK_PATH,
    reviewed_path=DEFAULT_REVIEWED_SAMPLES_PATH,
    labels=DEFAULT_TRAINING_SPELLS,
    slot_count=DEFAULT_BANK_SLOT_COUNT,
):
    """Promote accepted review samples into the template bank.

    Empty slots are filled directly.  When a label is already full, the old bank
    entries seed a DTW k-medoids pass and the bank is distilled back to
    ``slot_count`` representative real samples.
    """
    labels = tuple(labels or DEFAULT_TRAINING_SPELLS)
    bank = GestureTemplateBank(
        path=bank_path,
        labels=labels,
        slot_count=slot_count,
        migrate_from_logs=False,
    )
    reviewed_by_label = _load_reviewed_bank_entries(reviewed_path, labels)
    summary = {
        "bank_path": str(bank_path),
        "reviewed_path": str(reviewed_path),
        "slot_count": int(slot_count),
        "promoted": 0,
        "distilled": 0,
        "skipped_duplicates": 0,
        "labels": {label: {"added": 0, "selected": 0, "distilled": False} for label in labels},
    }

    for label in labels:
        existing = [
            bank.slot(label, index)
            for index in range(bank.slot_count)
            if bank.slot(label, index) is not None
        ]
        existing_sample_ids = {
            str(entry.get("sample_id"))
            for entry in existing
            if entry.get("sample_id") is not None
        }
        incoming = []
        for entry in reviewed_by_label.get(label, []):
            sample_id = entry.get("sample_id")
            if sample_id is not None and str(sample_id) in existing_sample_ids:
                summary["skipped_duplicates"] += 1
                continue
            incoming.append(entry)

        if not incoming:
            summary["labels"][label]["selected"] = len(existing)
            continue

        pool = existing + incoming
        if len(pool) <= bank.slot_count:
            selected = pool
            summary["promoted"] += len(incoming)
            summary["labels"][label]["added"] = len(incoming)
        else:
            selected = _distill_bank_entries(pool, existing_count=len(existing), slot_count=bank.slot_count)
            selected_ids = {id(entry) for entry in selected}
            added = sum(1 for entry in incoming if id(entry) in selected_ids)
            summary["promoted"] += added
            summary["distilled"] += 1
            summary["labels"][label]["added"] = added
            summary["labels"][label]["distilled"] = True

        bank.slots[label] = selected[: bank.slot_count] + [None for _ in range(max(0, bank.slot_count - len(selected)))]
        summary["labels"][label]["selected"] = bank.count(label)

    bank.save()
    return summary


def _load_reviewed_bank_entries(reviewed_path, labels):
    labels = set(labels)
    path = Path(reviewed_path)
    by_label = {label: [] for label in labels}
    if not path.exists():
        return by_label

    latest_by_sample = {}
    anonymous_index = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return by_label
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

    promoted_at = datetime.now(timezone.utc).isoformat()
    for entry in latest_by_sample.values():
        if entry.get("review_status") != "accepted":
            continue
        label = entry.get("label")
        if label not in labels:
            continue
        points = _copy_points(entry.get("points") or [])
        if len(points) < 2:
            continue
        bank_entry = {
            "label": label,
            "points": points,
            "source": "review_promoted",
            "source_label": label,
            "sample_id": entry.get("sample_id"),
            "source_file": entry.get("source_file"),
            "source_attempt_id": entry.get("source_attempt_id"),
            "reviewed_at": entry.get("reviewed_at"),
            "promoted_at": promoted_at,
            "primary": deepcopy(entry.get("primary") or {}),
        }
        for name in EVALUATION_METADATA_FIELDS:
            if entry.get(name) is not None:
                bank_entry[name] = deepcopy(entry[name])
        by_label[label].append(bank_entry)
    return by_label


def _distill_bank_entries(entries, existing_count, slot_count):
    from cv.template_classifier import _dtw_distance, _normalize_trajectory
    import numpy as np

    valid = []
    for index, entry in enumerate(entries):
        normalized = _normalize_trajectory(entry.get("points") or [])
        if normalized is not None:
            valid.append((entry, index < existing_count, normalized))
    if len(valid) <= slot_count:
        return [entry for entry, _is_existing, _normalized in valid]

    count = len(valid)
    distances = np.zeros((count, count), dtype=np.float64)
    for i in range(count):
        for j in range(i + 1, count):
            distance = _dtw_distance(valid[i][2], valid[j][2])
            distances[i, j] = distances[j, i] = distance

    medoids = [idx for idx, (_entry, is_existing, _normalized) in enumerate(valid) if is_existing][:slot_count]
    if not medoids:
        medoids = [int(np.argmin(distances.sum(axis=1)))]
    while len(medoids) < slot_count:
        nearest = distances[:, medoids].min(axis=1)
        medoids.append(int(np.argmax(nearest)))

    for _ in range(25):
        assignments = np.argmin(distances[:, medoids], axis=1)
        next_medoids = []
        for cluster in range(len(medoids)):
            members = np.where(assignments == cluster)[0]
            if len(members) == 0:
                next_medoids.append(medoids[cluster])
                continue
            sub = distances[np.ix_(members, members)]
            costs = sub.sum(axis=1)
            best_cost = float(costs.min())
            tied = [int(members[i]) for i, cost in enumerate(costs) if abs(float(cost) - best_cost) <= 1e-9]
            existing_tied = [idx for idx in tied if valid[idx][1]]
            next_medoids.append(existing_tied[0] if existing_tied else tied[0])
        if next_medoids == medoids:
            break
        medoids = next_medoids

    return [valid[index][0] for index in medoids[:slot_count]]


class CVTrainingSession:
    """State for guided CV sample collection."""

    def __init__(
        self,
        spell_order=None,
        attempts_per_spell=DEFAULT_BANK_SLOT_COUNT,
        progress_path=None,
        template_bank=None,
        bank_path=None,
    ):
        self.spell_order = tuple(spell_order or DEFAULT_TRAINING_SPELLS)
        self.attempts_per_spell = int(attempts_per_spell)
        if template_bank is None:
            template_bank = GestureTemplateBank(
                path=bank_path,
                labels=self.spell_order,
                slot_count=self.attempts_per_spell,
                migrate_from_logs=bank_path is not None,
            )
        self.template_bank = template_bank
        self._refresh_counts()
        self.progress_path = Path(progress_path) if progress_path else None
        self.pending_event = None
        self.pending_points = []
        self.pending_track_index = 0
        self.pending_label = None
        self.pending_target = None
        self.current_spell_index = self._first_unfilled_spell_index()
        self.current_slot_index = self.template_bank.first_empty_index(self.current_target_spell)
        if self.template_bank.is_empty:
            self._load_progress()

    @property
    def has_pending_review(self):
        return self.pending_event is not None

    @property
    def is_complete(self):
        return all(self.accepted_counts[spell] >= self.attempts_per_spell for spell in self.spell_order)

    @property
    def current_target_spell(self):
        return self.spell_order[self.current_spell_index]

    @property
    def current_attempt_number(self):
        return min(self.current_slot_index + 1, self.attempts_per_spell)

    @property
    def current_slot_status(self):
        if self.template_bank.has_recorded_slot(self.current_target_spell, self.current_slot_index):
            return "RECORDED"
        return "DEFAULT"

    def current_display_points(self):
        return self.template_bank.display_points(self.current_target_spell, self.current_slot_index)

    def next_slot(self):
        self.current_slot_index = (self.current_slot_index + 1) % self.attempts_per_spell
        return self.current_slot_index

    def previous_slot(self):
        self.current_slot_index = (self.current_slot_index - 1) % self.attempts_per_spell
        return self.current_slot_index

    def next_spell(self):
        self.current_spell_index = (self.current_spell_index + 1) % len(self.spell_order)
        self.current_slot_index = self.template_bank.first_empty_index(self.current_target_spell)
        return self.current_target_spell

    def previous_spell(self):
        self.current_spell_index = (self.current_spell_index - 1) % len(self.spell_order)
        self.current_slot_index = self.template_bank.first_empty_index(self.current_target_spell)
        return self.current_target_spell

    def clear_current_slot(self):
        changed = self.template_bank.clear_slot(self.current_target_spell, self.current_slot_index)
        self._refresh_counts()
        self._save_progress()
        return changed

    def begin_review(self, event, points=None, track_index=0):
        target = self.current_target_spell
        pending = deepcopy(event)
        pending["training_mode"] = True
        pending["training_target"] = target
        pending["training_status"] = "review"
        if points is not None:
            pending["points"] = points
        self.pending_event = pending
        self.pending_points = list(points or pending.get("points", []))
        self.pending_track_index = track_index
        self.pending_target = target
        self.pending_label = target

    def relabel_pending(self, spell):
        if spell not in TRAINING_LABELS:
            raise ValueError(f"Unknown training label: {spell}")
        if self.pending_event is None:
            return ""
        self.pending_label = spell
        return spell

    def accept_pending(self):
        if self.pending_event is None:
            return None

        label = self.pending_label or self.pending_target or self.current_target_spell
        saved = deepcopy(self.pending_event)
        saved["training_status"] = "accepted"
        saved["training_target"] = self.pending_target
        if label == self.pending_target:
            slot_index = self.current_slot_index
        else:
            slot_index = self.template_bank.first_empty_index(label)
        saved["training_attempt"] = slot_index + 1
        saved["training_slot"] = slot_index
        saved["training_attempts_per_spell"] = self.attempts_per_spell
        saved["intended_spell"] = label
        entry = self.template_bank.set_slot(label, slot_index, saved, source="training_mode")
        self._refresh_counts()
        if entry is None:
            self._save_progress()
            self._clear_pending()
            return None
        if label == self.pending_target:
            self.current_slot_index = min(slot_index + 1, self.attempts_per_spell - 1)
        self._save_progress()
        self._clear_pending()
        return saved

    def discard_pending(self):
        if self.pending_event is None:
            return None
        self._clear_pending()
        return None

    def reset(self):
        for spell in self.spell_order:
            for index in range(self.attempts_per_spell):
                self.template_bank.clear_slot(spell, index)
        self._refresh_counts()
        self.current_spell_index = 0
        self.current_slot_index = 0
        self._clear_pending()
        self._save_progress()

    def _clear_pending(self):
        self.pending_event = None
        self.pending_points = []
        self.pending_track_index = 0
        self.pending_label = None
        self.pending_target = None

    def _load_progress(self):
        if self.progress_path is None or not self.progress_path.exists():
            return
        try:
            data = json.loads(self.progress_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        if int(data.get("attempts_per_spell", self.attempts_per_spell)) != self.attempts_per_spell:
            return

        counts = data.get("accepted_counts", {})
        if not isinstance(counts, dict):
            return

        for spell in self.spell_order:
            value = counts.get(spell, 0)
            if not isinstance(value, int) or isinstance(value, bool):
                value = 0
            self.accepted_counts[spell] = max(0, min(value, self.attempts_per_spell))
        self.current_spell_index = self._first_unfilled_spell_index()
        self.current_slot_index = min(self.accepted_counts[self.current_target_spell], self.attempts_per_spell - 1)

    def _save_progress(self):
        if self.progress_path is None:
            return
        data = {
            "schema": 1,
            "spell_order": list(self.spell_order),
            "attempts_per_spell": self.attempts_per_spell,
            "accepted_counts": {spell: int(self.accepted_counts.get(spell, 0)) for spell in self.spell_order},
        }
        try:
            self.progress_path.parent.mkdir(parents=True, exist_ok=True)
            self.progress_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _refresh_counts(self):
        self.accepted_counts = {
            spell: self.template_bank.count(spell)
            for spell in self.template_bank.slots
        }

    def _first_unfilled_spell_index(self):
        for index, spell in enumerate(self.spell_order):
            if self.accepted_counts.get(spell, 0) < self.attempts_per_spell:
                return index
        return max(0, len(self.spell_order) - 1)
