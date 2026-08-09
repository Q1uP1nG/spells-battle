import sys
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class CVTrainingSessionTests(unittest.TestCase):
    def _event(self, points=None, spell="incendio"):
        return {
            "intended_spell": spell,
            "points": points or [[0, 0], [20, 0], [40, 0]],
            "primary": {"spell": spell, "confidence": 0.9},
        }

    def test_template_bank_migrates_logs_to_circle_slots(self):
        from game.cv_training import GestureTemplateBank

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "logs"
            log_dir.mkdir()
            log_path = log_dir / "session.jsonl"
            entries = [
                self._event([[0, 0], [40, 0], [80, 0]], "incendio"),
                self._event([[0, 0], [30, 40], [60, 0], [90, 40]], "circle"),
            ]
            log_path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

            bank = GestureTemplateBank(
                path=root / "gesture_template_bank.json",
                log_glob=str(log_dir / "*.jsonl"),
            )

            self.assertTrue(bank.has_recorded_slot("incendio", 0))
            self.assertTrue(bank.has_recorded_slot("circle", 0))
            self.assertFalse(bank.has_recorded_slot("overload", 0))

    def test_default_template_bank_has_thirty_slots(self):
        from game.cv_training import CVTrainingSession, DEFAULT_BANK_SLOT_COUNT, GestureTemplateBank

        bank = GestureTemplateBank(path=None, migrate_from_logs=False)
        session = CVTrainingSession(progress_path=None)

        self.assertEqual(DEFAULT_BANK_SLOT_COUNT, 30)
        self.assertEqual(bank.slot_count, 30)
        self.assertEqual(len(bank.slots["incendio"]), 30)
        self.assertEqual(session.attempts_per_spell, 30)

    def test_template_bank_saves_and_reloads_fixed_slot(self):
        from game.cv_training import GestureTemplateBank

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gesture_template_bank.json"
            bank = GestureTemplateBank(path=path, migrate_from_logs=False)
            event = self._event([[1, 2], [3, 4], [5, 6]], "circle")

            bank.set_slot("circle", 4, event, source="manual")
            reloaded = GestureTemplateBank(path=path, migrate_from_logs=False)

            self.assertTrue(reloaded.has_recorded_slot("circle", 4))
            self.assertEqual(reloaded.slot("circle", 4)["points"], [[1, 2], [3, 4], [5, 6]])
            self.assertNotIn("shadow", reloaded.slot("circle", 4))
            self.assertEqual(reloaded.count("circle"), 1)

    def test_template_bank_preserves_schema_v2_evaluation_metadata(self):
        from game.cv_training import GestureTemplateBank

        bank = GestureTemplateBank(path=None, migrate_from_logs=False)
        event = self._event([[1, 2], [3, 4], [5, 6]], "circle")
        event.update({
            "schema": 2,
            "sample_id": "session-a:7",
            "session_id": "session-a",
            "user_id": "player-a",
            "device_id": "camera-a",
            "palm_scale": 123.0,
            "pipeline_version": "gesture-pipeline-v2-normalized-shadow",
            "dataset_partition": "locked",
        })

        bank.set_slot("circle", 0, event, source="manual")
        saved = bank.slot("circle", 0)

        self.assertEqual(saved["schema"], 2)
        self.assertEqual(saved["sample_id"], "session-a:7")
        self.assertEqual(saved["session_id"], "session-a")
        self.assertEqual(saved["user_id"], "player-a")
        self.assertEqual(saved["device_id"], "camera-a")
        self.assertEqual(saved["palm_scale"], 123.0)
        self.assertEqual(saved["pipeline_version"], "gesture-pipeline-v2-normalized-shadow")
        self.assertEqual(saved["dataset_partition"], "locked")

    def test_template_bank_saves_numpy_points_from_cv_tracks(self):
        from game.cv_training import GestureTemplateBank

        bank = GestureTemplateBank(path=None, migrate_from_logs=False)
        event = self._event([
            np.array([1.5, 2.5], dtype=np.float32),
            np.array([3.0, 4.0], dtype=np.float32),
            np.array([5.0, 6.0], dtype=np.float32),
        ], "circle")

        bank.set_slot("circle", 0, event, source="manual")

        self.assertTrue(bank.has_recorded_slot("circle", 0))
        self.assertEqual(bank.count("circle"), 1)
        self.assertEqual(bank.slot("circle", 0)["points"], [[1.5, 2.5], [3.0, 4.0], [5.0, 6.0]])

    def test_promote_reviewed_samples_fills_empty_bank_slots(self):
        from game.cv_training import GestureTemplateBank, promote_reviewed_samples_to_bank

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bank_path = root / "gesture_template_bank.json"
            reviewed_path = root / "gesture_reviewed_samples.jsonl"
            reviewed = [
                {
                    "review_status": "accepted",
                    "label": "lumos",
                    "sample_id": "session.jsonl:1",
                    "source_file": "session.jsonl",
                    "source_attempt_id": 1,
                    "points": [[0, 200], [0, 120], [0, 40]],
                    "shadow": {"spell": "lumos"},
                },
                {
                    "review_status": "discarded",
                    "label": "lumos",
                    "sample_id": "session.jsonl:2",
                    "points": [[0, 0], [10, 10]],
                },
            ]
            reviewed_path.write_text("\n".join(json.dumps(e) for e in reviewed), encoding="utf-8")

            summary = promote_reviewed_samples_to_bank(
                bank_path=bank_path,
                reviewed_path=reviewed_path,
                labels=("lumos",),
                slot_count=30,
            )
            reloaded = GestureTemplateBank(
                path=bank_path,
                labels=("lumos",),
                migrate_from_logs=False,
            )

        self.assertEqual(summary["promoted"], 1)
        self.assertEqual(reloaded.count("lumos"), 1)
        self.assertEqual(reloaded.slot("lumos", 0)["source"], "review_promoted")
        self.assertEqual(reloaded.slot("lumos", 0)["sample_id"], "session.jsonl:1")
        self.assertNotIn("shadow", reloaded.slot("lumos", 0))

    def test_promote_reviewed_samples_distills_full_bank_to_slot_count(self):
        from game.cv_training import GestureTemplateBank, promote_reviewed_samples_to_bank

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bank_path = root / "gesture_template_bank.json"
            reviewed_path = root / "gesture_reviewed_samples.jsonl"
            bank = GestureTemplateBank(
                path=bank_path,
                labels=("incendio",),
                slot_count=30,
                migrate_from_logs=False,
            )
            for index in range(30):
                bank.set_slot(
                    "incendio",
                    index,
                    self._event([[0, index], [60, index], [120, index]], "incendio"),
                    source="manual",
                )
            reviewed_path.write_text(json.dumps({
                "review_status": "accepted",
                "label": "incendio",
                "sample_id": "session.jsonl:31",
                "points": [[0, 100], [30, 150], [60, 100], [90, 150]],
            }), encoding="utf-8")

            summary = promote_reviewed_samples_to_bank(
                bank_path=bank_path,
                reviewed_path=reviewed_path,
                labels=("incendio",),
                slot_count=30,
            )
            reloaded = GestureTemplateBank(
                path=bank_path,
                labels=("incendio",),
                slot_count=30,
                migrate_from_logs=False,
            )

        self.assertEqual(summary["distilled"], 1)
        self.assertEqual(reloaded.slot_count, 30)
        self.assertEqual(reloaded.count("incendio"), 30)

    def test_template_bank_treats_empty_point_slot_as_unrecorded(self):
        from game.cv_training import GestureTemplateBank

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gesture_template_bank.json"
            path.write_text(json.dumps({
                "schema": 1,
                "slot_count": 10,
                "labels": ["circle"],
                "slots": {
                    "circle": [{
                        "label": "circle",
                        "points": [],
                        "source": "training_mode",
                    }] + [None] * 9,
                },
            }), encoding="utf-8")

            bank = GestureTemplateBank(
                path=path,
                labels=("circle",),
                migrate_from_logs=False,
            )

            self.assertFalse(bank.has_recorded_slot("circle", 0))
            self.assertEqual(bank.count("circle"), 0)

    def test_session_browses_template_slots_and_reports_default_status(self):
        from game.cv_training import CVTrainingSession, GestureTemplateBank

        bank = GestureTemplateBank(path=None, migrate_from_logs=False)
        session = CVTrainingSession(
            spell_order=["incendio", "circle"],
            attempts_per_spell=10,
            template_bank=bank,
            progress_path=None,
        )

        self.assertEqual(session.current_target_spell, "incendio")
        self.assertEqual(session.current_attempt_number, 1)
        self.assertEqual(session.current_slot_status, "DEFAULT")
        self.assertGreater(len(session.current_display_points()), 3)

        session.next_slot()
        self.assertEqual(session.current_attempt_number, 2)

        session.next_spell()
        self.assertEqual(session.current_target_spell, "circle")
        self.assertEqual(session.current_attempt_number, 1)

    def test_accept_pending_writes_current_template_slot(self):
        from game.cv_training import CVTrainingSession, GestureTemplateBank

        bank = GestureTemplateBank(path=None, migrate_from_logs=False)
        session = CVTrainingSession(
            spell_order=["incendio"],
            attempts_per_spell=10,
            template_bank=bank,
            progress_path=None,
        )
        session.next_slot()
        session.begin_review(self._event([[1, 1], [5, 1], [9, 1]], "incendio"), track_index=0)

        saved = session.accept_pending()

        self.assertEqual(saved["training_slot"], 1)
        self.assertTrue(bank.has_recorded_slot("incendio", 1))
        self.assertEqual(session.accepted_counts["incendio"], 1)
        self.assertEqual(session.current_attempt_number, 3)

    def test_accept_pending_rejects_empty_points_without_advancing_slot(self):
        from game.cv_training import CVTrainingSession, GestureTemplateBank

        bank = GestureTemplateBank(path=None, labels=("circle",), migrate_from_logs=False)
        session = CVTrainingSession(
            spell_order=["circle"],
            attempts_per_spell=10,
            template_bank=bank,
            progress_path=None,
        )
        session.begin_review({"primary": {"spell": "stupefy"}, "points": []}, [], track_index=0)

        saved = session.accept_pending()

        self.assertIsNone(saved)
        self.assertFalse(session.has_pending_review)
        self.assertEqual(session.accepted_counts["circle"], 0)
        self.assertFalse(bank.has_recorded_slot("circle", 0))
        self.assertEqual(session.current_attempt_number, 1)

    def test_default_training_spells_are_trajectory_spells_only(self):
        from game.cv_training import CVTrainingSession, DEFAULT_TRAINING_SPELLS

        self.assertEqual(DEFAULT_TRAINING_SPELLS, ("incendio", "circle", "glacius", "lumos", "overload"))

        session = CVTrainingSession(progress_path=None)

        self.assertEqual(session.spell_order, DEFAULT_TRAINING_SPELLS)
        self.assertNotIn("protego", session.accepted_counts)

    def test_relabel_accepts_training_labels_that_are_not_spells(self):
        from game.cv_training import CVTrainingSession

        session = CVTrainingSession(spell_order=["circle"], attempts_per_spell=1)
        session.begin_review({"primary": {"spell": "stupefy"}}, [[1.0, 2.0]], track_index=0)

        label = session.relabel_pending("overload")
        saved = session.accept_pending()

        self.assertEqual(label, "overload")
        self.assertEqual(saved["intended_spell"], "overload")
        self.assertEqual(session.accepted_counts["overload"], 1)

    def test_accepting_pending_sample_counts_current_target(self):
        from game.cv_training import CVTrainingSession

        session = CVTrainingSession(spell_order=["incendio", "glacius"], attempts_per_spell=2)
        session.begin_review({"primary": {"spell": "incendio"}}, [[1.0, 2.0]], track_index=0)

        saved = session.accept_pending()

        self.assertEqual(saved["intended_spell"], "incendio")
        self.assertEqual(saved["training_status"], "accepted")
        self.assertEqual(saved["training_target"], "incendio")
        self.assertEqual(session.accepted_counts["incendio"], 1)
        self.assertFalse(session.has_pending_review)
        self.assertEqual(session.current_target_spell, "incendio")
        self.assertEqual(session.current_attempt_number, 2)

    def test_relabel_counts_saved_label_and_keeps_unfinished_target(self):
        from game.cv_training import CVTrainingSession

        session = CVTrainingSession(spell_order=["incendio", "glacius"], attempts_per_spell=2)
        session.begin_review({"primary": {"spell": "incendio"}}, [[1.0, 2.0]], track_index=0)
        session.relabel_pending("glacius")

        saved = session.accept_pending()

        self.assertEqual(saved["intended_spell"], "glacius")
        self.assertEqual(saved["training_target"], "incendio")
        self.assertEqual(session.accepted_counts["glacius"], 1)
        self.assertEqual(session.accepted_counts["incendio"], 0)
        self.assertEqual(session.current_target_spell, "incendio")

    def test_discard_pending_sample_does_not_count_or_save(self):
        from game.cv_training import CVTrainingSession

        session = CVTrainingSession(spell_order=["incendio"], attempts_per_spell=2)
        session.begin_review({"primary": {"spell": None}}, [[1.0, 2.0]], track_index=0)

        discarded = session.discard_pending()

        self.assertIsNone(discarded)
        self.assertEqual(session.accepted_counts["incendio"], 0)
        self.assertFalse(session.has_pending_review)
        self.assertEqual(session.current_attempt_number, 1)

    def test_accept_pending_persists_training_progress(self):
        from game.cv_training import CVTrainingSession

        with tempfile.TemporaryDirectory() as tmp:
            progress_path = Path(tmp) / "progress.json"
            session = CVTrainingSession(
                spell_order=["incendio", "glacius"],
                attempts_per_spell=2,
                progress_path=progress_path,
            )
            session.begin_review({"primary": {"spell": "incendio"}}, [[1.0, 2.0]], track_index=0)

            session.accept_pending()

            saved = json.loads(progress_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["accepted_counts"], {"incendio": 1, "glacius": 0})
            self.assertEqual(saved["attempts_per_spell"], 2)

    def test_new_training_session_resumes_saved_progress(self):
        from game.cv_training import CVTrainingSession

        with tempfile.TemporaryDirectory() as tmp:
            progress_path = Path(tmp) / "progress.json"
            progress_path.write_text(json.dumps({
                "schema": 1,
                "spell_order": ["incendio", "glacius"],
                "attempts_per_spell": 2,
                "accepted_counts": {"incendio": 2, "glacius": 1},
            }), encoding="utf-8")

            session = CVTrainingSession(
                spell_order=["incendio", "glacius"],
                attempts_per_spell=2,
                progress_path=progress_path,
            )

            self.assertEqual(session.accepted_counts, {"incendio": 2, "glacius": 1})
            self.assertEqual(session.current_target_spell, "glacius")
            self.assertEqual(session.current_attempt_number, 2)

    def test_reset_clears_persisted_training_progress(self):
        from game.cv_training import CVTrainingSession

        with tempfile.TemporaryDirectory() as tmp:
            progress_path = Path(tmp) / "progress.json"
            session = CVTrainingSession(
                spell_order=["incendio"],
                attempts_per_spell=2,
                progress_path=progress_path,
            )
            session.begin_review({"primary": {"spell": "incendio"}}, [[1.0, 2.0]], track_index=0)
            session.accept_pending()

            session.reset()

            saved = json.loads(progress_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["accepted_counts"], {"incendio": 0})


if __name__ == "__main__":
    unittest.main()
