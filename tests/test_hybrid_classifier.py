import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class RuntimeTemplateLoaderTests(unittest.TestCase):
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
