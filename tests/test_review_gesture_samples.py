from __future__ import annotations

import json
import sys
import tempfile
import unittest
import threading
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ReviewGestureSamplesTests(unittest.TestCase):
    def test_review_page_has_start_end_legend(self):
        from tools.review_gesture_samples import HTML

        self.assertIn('class="legend"', HTML)
        self.assertIn("Start", HTML)
        self.assertIn("End", HTML)
        self.assertIn("legend-dot start", HTML)
        self.assertIn("legend-dot end", HTML)

    def test_review_page_uses_single_viewport_layout(self):
        from tools.review_gesture_samples import HTML

        self.assertIn("height: 100vh;", HTML)
        self.assertIn("overflow: hidden;", HTML)
        self.assertIn("min-height: 0;", HTML)
        self.assertIn("min-height: 300px;", HTML)

    def test_review_page_has_retrain_button(self):
        from tools.review_gesture_samples import HTML

        self.assertIn('id="retrain"', HTML)
        self.assertIn('id="retrainStatus"', HTML)
        self.assertIn("/api/retrain", HTML)
        self.assertIn("Rebuild Template Pack", HTML)

    def test_review_page_does_not_show_shadow_prediction(self):
        from tools.review_gesture_samples import HTML

        self.assertNotIn('<strong>Shadow</strong>', HTML)
        self.assertNotIn('id="shadow"', HTML)

    def test_run_retrain_builds_template_model_from_reviewed_samples(self):
        from tools.review_gesture_samples import run_retrain

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bank_path = root / "gesture_template_bank.json"
            reviewed_path = root / "gesture_reviewed_samples.jsonl"
            output_path = root / "gesture_templates.json"
            entries = [
                {
                    "review_status": "accepted",
                    "label": "lumos",
                    "sample_id": "lumos-1",
                    "points": [[0, 200], [0, 130], [0, 60], [0, -10]],
                },
                {
                    "review_status": "accepted",
                    "label": "lumos",
                    "sample_id": "lumos-2",
                    "points": [[5, 200], [5, 130], [5, 60], [5, -10]],
                },
            ]
            reviewed_path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

            result = run_retrain([
                "--bank", str(bank_path),
                "--reviewed", str(reviewed_path),
                "--output", str(output_path),
                "--min-samples", "2",
                "--k", "2",
            ])

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            bank_payload = json.loads(bank_path.read_text(encoding="utf-8"))

        self.assertTrue(result["ok"], result["output"])
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("lumos", payload["prototypes"])
        self.assertEqual(bank_payload["slot_count"], 30)
        self.assertEqual(len([slot for slot in bank_payload["slots"]["lumos"] if slot]), 2)
        self.assertIn("Wrote", result["output"])

    def test_load_review_candidates_from_logs(self):
        from tools.review_gesture_samples import load_review_candidates

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "session.jsonl"
            entries = [
                {
                    "schema": 2,
                    "sample_id": "stable-sample-7",
                    "session_id": "stable-session",
                    "attempt_id": 7,
                    "timestamp": 123.4,
                    "mode": "wand",
                    "side": "left",
                    "points": [[0, 0], [40, 0], [80, 0], [120, 0]],
                    "path_length": 120.0,
                    "primary": {"spell": "incendio", "confidence": 0.88, "method": "fused"},
                    "shadow": {"spell": "incendio", "confidence": 0.70, "method": "template"},
                    "agreement": True,
                    "cast_success": True,
                    "user_id": "player-a",
                    "device_id": "camera-a",
                    "palm_scale": 110.0,
                },
                {
                    "attempt_id": 8,
                    "timestamp": 124.0,
                    "mode": "wand",
                    "side": "left",
                    "points": [[0, 0], [1, 1]],
                    "path_length": 1.4,
                    "primary": {"spell": None, "confidence": 0.0},
                    "shadow": {"spell": None, "confidence": 0.0},
                },
            ]
            log_path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")

            samples = load_review_candidates([log_path], min_path_length=55.0)

        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0]["sample_id"], "stable-sample-7")
        self.assertEqual(samples[0]["source_file"], str(log_path))
        self.assertEqual(samples[0]["suggested_label"], "incendio")
        self.assertEqual(samples[0]["session_id"], "stable-session")
        self.assertEqual(samples[0]["user_id"], "player-a")
        self.assertEqual(samples[0]["device_id"], "camera-a")
        self.assertEqual(samples[0]["palm_scale"], 110.0)
        self.assertNotIn("shadow", samples[0])
        self.assertNotIn("agreement", samples[0])

    def test_append_review_record_writes_accepted_sample(self):
        from tools.review_gesture_samples import append_review_record

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_path = root / "reviewed.jsonl"
            sample = {
                "sample_id": "session.jsonl:7",
                "source_file": "session.jsonl",
                "source_attempt_id": 7,
                "points": [[0, 0], [40, 0], [80, 0]],
                "primary": {"spell": "incendio"},
                "shadow": {"spell": "incendio"},
                "session_id": "session-a",
                "user_id": "player-a",
                "device_id": "camera-a",
                "dataset_partition": "locked",
            }

            record = append_review_record(output_path, sample, "incendio", "accepted")
            saved = json.loads(output_path.read_text(encoding="utf-8").strip())

        self.assertEqual(record["label"], "incendio")
        self.assertEqual(saved["schema"], 2)
        self.assertEqual(saved["review_status"], "accepted")
        self.assertEqual(saved["points"], [[0, 0], [40, 0], [80, 0]])
        self.assertNotIn("shadow", record)
        self.assertNotIn("shadow", saved)
        self.assertEqual(saved["session_id"], "session-a")
        self.assertEqual(saved["user_id"], "player-a")
        self.assertEqual(saved["device_id"], "camera-a")
        self.assertEqual(saved["dataset_partition"], "locked")

    def test_filter_unreviewed_candidates_skips_existing_reviews(self):
        from tools.review_gesture_samples import append_review_record, filter_unreviewed_candidates

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_path = root / "reviewed.jsonl"
            reviewed_sample = {
                "sample_id": "session.jsonl:7",
                "points": [[0, 0], [40, 0], [80, 0]],
            }
            fresh_sample = {
                "sample_id": "session.jsonl:8",
                "points": [[0, 0], [0, 40], [0, 80]],
            }
            append_review_record(output_path, reviewed_sample, "incendio", "accepted")

            samples = filter_unreviewed_candidates([reviewed_sample, fresh_sample], output_path)

        self.assertEqual([sample["sample_id"] for sample in samples], ["session.jsonl:8"])

    def test_api_samples_keeps_pending_reviews_visible_with_label(self):
        from tools.review_gesture_samples import make_handler

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_path = root / "reviewed.jsonl"
            samples = [
                {
                    "sample_id": "session.jsonl:1",
                    "points": [[0, 0], [80, 0]],
                    "path_length": 80.0,
                    "primary": {"spell": "incendio"},
                },
                {
                    "sample_id": "session.jsonl:2",
                    "points": [[0, 0], [0, 80]],
                    "path_length": 80.0,
                    "primary": {"spell": "lumos"},
                },
            ]
            handler = make_handler(samples, output_path)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}"
            try:
                first = json.loads(urllib.request.urlopen(f"{url}/api/samples", timeout=2).read().decode("utf-8"))
                request = urllib.request.Request(
                    f"{url}/api/review",
                    data=json.dumps({
                        "sample_id": "session.jsonl:1",
                        "label": "incendio",
                        "review_status": "accepted",
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(request, timeout=2).read()
                second = json.loads(urllib.request.urlopen(f"{url}/api/samples", timeout=2).read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertEqual([sample["sample_id"] for sample in first["samples"]], ["session.jsonl:1", "session.jsonl:2"])
        self.assertEqual([sample["sample_id"] for sample in second["samples"]], ["session.jsonl:1", "session.jsonl:2"])
        self.assertEqual(second["samples"][0]["pending_label"], "incendio")
        self.assertEqual(second["samples"][0]["pending_review_status"], "accepted")
        self.assertFalse(output_path.exists())

    def test_api_retrain_commits_pending_reviews_and_then_hides_them(self):
        from tools.review_gesture_samples import make_handler

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_path = root / "reviewed.jsonl"
            samples = [
                {
                    "sample_id": "session.jsonl:1",
                    "points": [[0, 0], [80, 0]],
                    "path_length": 80.0,
                    "primary": {"spell": "incendio"},
                },
            ]
            handler = make_handler(samples, output_path, retrain_func=lambda: {"ok": True, "exit_code": 0, "output": "trained"})
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}"
            try:
                review_request = urllib.request.Request(
                    f"{url}/api/review",
                    data=json.dumps({
                        "sample_id": "session.jsonl:1",
                        "label": "incendio",
                        "review_status": "accepted",
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(review_request, timeout=2).read()
                retrain_request = urllib.request.Request(f"{url}/api/retrain", data=b"", method="POST")
                retrain_response = json.loads(urllib.request.urlopen(retrain_request, timeout=2).read().decode("utf-8"))
                after = json.loads(urllib.request.urlopen(f"{url}/api/samples", timeout=2).read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

            saved = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(retrain_response["ok"])
            self.assertEqual(retrain_response["committed_reviews"], 1)
            self.assertEqual(saved[0]["sample_id"], "session.jsonl:1")
            self.assertEqual(saved[0]["label"], "incendio")
            self.assertEqual(after["samples"], [])

    def test_review_page_highlights_pending_label(self):
        from tools.review_gesture_samples import HTML

        self.assertIn("pending_label", HTML)
        self.assertIn("selected", HTML)
        self.assertNotIn("samples.splice(index, 1);", HTML)


if __name__ == "__main__":
    unittest.main()
