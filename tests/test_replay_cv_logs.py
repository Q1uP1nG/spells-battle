import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ReplayCVLogsTests(unittest.TestCase):
    def test_summarize_entries_counts_intended_spell_accuracy(self):
        from tools.replay_cv_logs import summarize_entries

        entries = [
            {
                "intended_spell": "glacius",
                "primary": {"spell": "glacius"},
                "shadow": {"spell": "lumos"},
                "agreement": False,
                "mode": "finger",
            },
            {
                "intended_spell": "lumos",
                "primary": {"spell": "glacius"},
                "shadow": {"spell": "lumos"},
                "agreement": False,
                "mode": "finger",
            },
            {
                "intended_spell": None,
                "primary": {"spell": "incendio"},
                "shadow": {"spell": "incendio"},
                "agreement": True,
                "mode": "wand",
            },
        ]

        summary = summarize_entries(entries)

        self.assertEqual(summary["labeled_total"], 2)
        self.assertEqual(summary["primary_correct"], 1)
        self.assertEqual(summary["shadow_correct"], 1)


if __name__ == "__main__":
    unittest.main()
