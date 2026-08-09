"""Promote reviewed samples into the bank, then rebuild the DTW template pack.

Usage:
    python tools/retrain_gesture_templates.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.cv_training import (  # noqa: E402
    DEFAULT_BANK_SLOT_COUNT,
    DEFAULT_REVIEWED_SAMPLES_PATH,
    DEFAULT_TEMPLATE_BANK_PATH,
    promote_reviewed_samples_to_bank,
)
from tools.train_gesture_templates import DEFAULT_OUTPUT, main as build_pack_main  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", default=str(DEFAULT_TEMPLATE_BANK_PATH))
    parser.add_argument("--reviewed", default=str(DEFAULT_REVIEWED_SAMPLES_PATH))
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--slot-count", type=int, default=DEFAULT_BANK_SLOT_COUNT)
    parser.add_argument("--k", type=int, default=7)
    parser.add_argument("--min-samples", type=int, default=8)
    args = parser.parse_args(argv)

    summary = promote_reviewed_samples_to_bank(
        bank_path=args.bank,
        reviewed_path=args.reviewed,
        slot_count=args.slot_count,
    )
    print(
        "Promoted reviewed samples to bank: "
        f"added={summary['promoted']} distilled={summary['distilled']} "
        f"duplicates={summary['skipped_duplicates']}"
    )

    return build_pack_main([
        "--bank", str(args.bank),
        "--reviewed", "",
        "--output", str(args.output),
        "--k", str(args.k),
        "--min-samples", str(args.min_samples),
    ])


if __name__ == "__main__":
    raise SystemExit(main())
