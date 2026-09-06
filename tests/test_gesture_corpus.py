from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class GestureCorpusTests(unittest.TestCase):
    def _write_jsonl(self, path, entries):
        path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")

    def test_bank_and_accepted_review_are_one_canonical_sample(self):
        from tools.gesture_corpus import load_canonical_corpus

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            points = [[0, 0], [60, 0], [120, 0]]
            bank_path = root / "bank.json"
            reviewed_path = root / "reviewed.jsonl"
            bank_path.write_text(json.dumps({
                "slots": {"incendio": [{
                    "sample_id": "session.jsonl:7",
                    "label": "incendio",
                    "points": points,
                    "source_file": "logs/session.jsonl",
                    "source_attempt_id": 7,
                }]},
            }), encoding="utf-8")
            self._write_jsonl(reviewed_path, [{
                "sample_id": "session.jsonl:7",
                "review_status": "accepted",
                "label": "incendio",
                "points": points,
                "source_file": "logs/session.jsonl",
                "source_attempt_id": 7,
            }])

            corpus = load_canonical_corpus(bank_path=bank_path, reviewed_path=reviewed_path)
            repeated = load_canonical_corpus(bank_path=bank_path, reviewed_path=reviewed_path)

        self.assertEqual(len(corpus.samples), 1)
        self.assertEqual(corpus.audit["duplicates_merged"], 1)
        self.assertEqual(set(corpus.samples[0].sources), {"bank", "reviewed"})
        self.assertTrue(corpus.audit["corpus_version"].startswith("sha256:"))
        self.assertEqual(corpus.audit["corpus_version"], repeated.audit["corpus_version"])

    def test_conflicting_strong_reviews_apply_latest_in_file_order(self):
        from tools.gesture_corpus import load_canonical_corpus

        # One candidate can match two different review records through two
        # different strong aliases (its sample_id and its source key).  The
        # applied decision must be the latest review in file order and must
        # not depend on set iteration order inside the process.
        points = [[0.0, 0.0], [80.0, 0.0], [160.0, 0.0]]
        accept_older = {
            "sample_id": "log-a.jsonl:1",
            "review_status": "accepted",
            "label": "incendio",
            "points": points,
        }
        discard_newer = {
            "source_file": "log-b.jsonl",
            "source_attempt_id": 2,
            "review_status": "discarded",
            "points": points,
        }
        bank_entry = {
            "sample_id": "log-a.jsonl:1",
            "label": "incendio",
            "points": points,
            "source_file": "log-b.jsonl",
            "source_attempt_id": 2,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bank_path = root / "bank.json"
            bank_path.write_text(json.dumps({"slots": {"incendio": [bank_entry]}}), encoding="utf-8")

            discard_last = root / "discard_last.jsonl"
            self._write_jsonl(discard_last, [accept_older, discard_newer])
            discarded = load_canonical_corpus(bank_path=bank_path, reviewed_path=discard_last)
            discarded_again = load_canonical_corpus(bank_path=bank_path, reviewed_path=discard_last)

            accept_last = root / "accept_last.jsonl"
            self._write_jsonl(accept_last, [discard_newer, accept_older])
            accepted = load_canonical_corpus(bank_path=bank_path, reviewed_path=accept_last)
            accepted_again = load_canonical_corpus(bank_path=bank_path, reviewed_path=accept_last)

        # The bank candidate is discarded by the newest review, but the accepted
        # review itself still contributes one canonical sample.
        self.assertEqual(discarded.audit, discarded_again.audit)
        self.assertEqual(len(discarded.samples), 1)
        self.assertEqual(discarded.samples[0].label, "incendio")
        self.assertEqual(discarded.audit["discarded_by_review"], 1)
        self.assertEqual(discarded.audit["duplicates_merged"], 0)

        # The same candidate is kept when the accept review is the newest one,
        # and the accepted-review view of the same trajectory merges into it.
        self.assertEqual(accepted.audit, accepted_again.audit)
        self.assertEqual(len(accepted.samples), 1)
        self.assertEqual(accepted.samples[0].label, "incendio")
        self.assertEqual(accepted.audit["discarded_by_review"], 0)
        self.assertEqual(accepted.audit["duplicates_merged"], 1)

    def test_latest_discard_review_excludes_bank_sample(self):
        from tools.gesture_corpus import load_canonical_corpus

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            points = [[0, 0], [0, 60], [0, 120]]
            bank_path = root / "bank.json"
            reviewed_path = root / "reviewed.jsonl"
            bank_path.write_text(json.dumps({
                "slots": {"glacius": [{
                    "sample_id": "gesture-1", "label": "glacius", "points": points,
                }]},
            }), encoding="utf-8")
            self._write_jsonl(reviewed_path, [
                {"sample_id": "gesture-1", "review_status": "accepted", "label": "glacius", "points": points},
                {"sample_id": "gesture-1", "review_status": "discarded", "label": None, "points": points},
            ])

            corpus = load_canonical_corpus(bank_path=bank_path, reviewed_path=reviewed_path)

        self.assertEqual(corpus.samples, [])
        self.assertEqual(corpus.audit["latest_reviews"], 1)
        self.assertEqual(corpus.audit["discarded_by_review"], 1)

    def test_review_label_overrides_legacy_bank_label(self):
        from tools.gesture_corpus import load_canonical_corpus

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            points = [[0, 0], [30, 50], [60, 0], [90, 50]]
            bank_path = root / "bank.json"
            reviewed_path = root / "reviewed.jsonl"
            bank_path.write_text(json.dumps({
                "slots": {"incendio": [{
                    "sample_id": "gesture-2", "label": "incendio", "points": points,
                }]},
            }), encoding="utf-8")
            self._write_jsonl(reviewed_path, [{
                "sample_id": "gesture-2", "review_status": "accepted",
                "label": "overload", "points": points,
            }])

            corpus = load_canonical_corpus(bank_path=bank_path, reviewed_path=reviewed_path)

        self.assertEqual(len(corpus.samples), 1)
        self.assertEqual(corpus.samples[0].label, "overload")
        self.assertTrue(corpus.audit["label_conflicts"])

    def test_locked_review_partition_overrides_development_bank_view(self):
        from tools.gesture_corpus import load_canonical_corpus

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bank_path = root / "bank.json"
            reviewed_path = root / "reviewed.jsonl"
            points = [[0, 0], [60, 0], [120, 0]]
            bank_path.write_text(json.dumps({
                "slots": {"incendio": [{
                    "sample_id": "locked-sample",
                    "points": points,
                    "dataset_partition": "development",
                }]},
            }), encoding="utf-8")
            self._write_jsonl(reviewed_path, [{
                "sample_id": "locked-sample",
                "review_status": "accepted",
                "label": "incendio",
                "points": points,
                "dataset_partition": "locked",
            }])

            corpus = load_canonical_corpus(bank_path=bank_path, reviewed_path=reviewed_path)

        self.assertEqual(corpus.samples[0].dataset_partition, "locked")

    def test_exact_trajectory_deduplicates_legacy_views_without_sample_id(self):
        from tools.gesture_corpus import load_canonical_corpus

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            points = [[5.0, 100.0], [5.0, 50.0], [5.0, 0.0]]
            bank_path = root / "bank.json"
            reviewed_path = root / "reviewed.jsonl"
            bank_path.write_text(json.dumps({
                "slots": {"lumos": [{"label": "lumos", "points": points}]},
            }), encoding="utf-8")
            self._write_jsonl(reviewed_path, [{
                "review_status": "accepted", "label": "lumos", "points": points,
            }])

            corpus = load_canonical_corpus(bank_path=bank_path, reviewed_path=reviewed_path)

        self.assertEqual(len(corpus.samples), 1)
        self.assertTrue(corpus.samples[0].sample_id.startswith("legacy:lumos:"))

    def test_identical_trajectories_in_same_source_remain_distinct_recordings(self):
        from tools.gesture_corpus import load_canonical_corpus

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bank_path = root / "bank.json"
            points = [[0, 0], [60, 0], [120, 0]]
            bank_path.write_text(json.dumps({
                "slots": {
                    "incendio": [
                        {"sample_id": "recording-1", "points": points},
                        {"sample_id": "recording-2", "points": points},
                    ],
                },
            }), encoding="utf-8")

            corpus = load_canonical_corpus(bank_path=bank_path)

        self.assertEqual(len(corpus.samples), 2)
        self.assertEqual(
            {sample.sample_id for sample in corpus.samples},
            {"recording-1", "recording-2"},
        )

    def test_raw_reviewed_label_is_accepted_when_intended_spell_is_missing(self):
        from tools.gesture_corpus import load_canonical_corpus

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reviewed_path = root / "reviewed.jsonl"
            self._write_jsonl(reviewed_path, [{
                "sample_id": "review-only", "review_status": "accepted",
                "label": "circle", "intended_spell": None,
                "points": [[0, 0], [30, 30], [0, 60], [-30, 30], [0, 0]],
            }])

            corpus = load_canonical_corpus(reviewed_path=reviewed_path)

        self.assertEqual(len(corpus.samples), 1)
        self.assertEqual(corpus.samples[0].label, "circle")


if __name__ == "__main__":
    unittest.main()
