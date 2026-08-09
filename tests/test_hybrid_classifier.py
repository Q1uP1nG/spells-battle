import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class HybridTemplateGestureClassifierTests(unittest.TestCase):
    def test_falls_back_to_heuristic_when_no_templates_are_available(self):
        from cv.gesture_classifier import classify_cv_gesture
        from cv.hybrid_classifier import HybridTemplateGestureClassifier

        points = [[640, 400 - i * 8] for i in range(20)]
        expected_spell, expected_confidence = classify_cv_gesture(points, "left")

        classifier = HybridTemplateGestureClassifier(templates=[])
        result = classifier.classify(points, "left")

        self.assertEqual(result.spell, expected_spell)
        self.assertEqual(result.confidence, expected_confidence)
        self.assertEqual(result.method, "heuristic")
        self.assertIn("no runtime templates", result.reason)

    def test_template_can_rescue_shape_rule_near_miss(self):
        from cv.hybrid_classifier import HybridTemplateGestureClassifier, RuntimeGestureTemplate
        from cv.template_classifier import _normalize_trajectory

        template_points = [[0, 0], [80, 0], [160, 0], [240, 0]]
        near_miss = [[i * 16, 20 if i % 2 == 0 else -5] for i in range(16)]
        templates = [
            RuntimeGestureTemplate("incendio", _normalize_trajectory(template_points), "unit"),
            RuntimeGestureTemplate("glacius", _normalize_trajectory([[0, 0], [0, 80], [0, 160], [0, 240]]), "unit"),
        ]

        classifier = HybridTemplateGestureClassifier(templates=templates)
        result = classifier.classify(near_miss, "left")

        self.assertEqual(result.spell, "incendio")
        self.assertEqual(result.method, "hybrid")
        self.assertGreaterEqual(result.confidence, 0.78)

    def test_runtime_template_loader_chooses_largest_labeled_session(self):
        import json
        import tempfile
        from cv.hybrid_classifier import load_runtime_templates

        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            small = log_dir / "session_small.jsonl"
            large = log_dir / "session_large.jsonl"
            small.write_text(json.dumps({
                "training_mode": True,
                "training_status": "accepted",
                "intended_spell": "lumos",
                "points": [[0, 100], [0, 0]],
            }), encoding="utf-8")
            large.write_text("\n".join([
                json.dumps({
                    "training_mode": True,
                    "training_status": "accepted",
                    "intended_spell": "incendio",
                    "points": [[0, 0], [100, 0]],
                }),
                json.dumps({
                    "training_mode": True,
                    "training_status": "accepted",
                    "intended_spell": "glacius",
                    "points": [[0, 0], [0, 100]],
                }),
            ]), encoding="utf-8")

            templates = load_runtime_templates(log_dir)

        self.assertEqual({t.spell for t in templates}, {"incendio", "glacius"})
        self.assertTrue(all(t.source.endswith("session_large.jsonl") for t in templates))


if __name__ == "__main__":
    unittest.main()
