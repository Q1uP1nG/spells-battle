"""Replay / statistics tool for CV gesture session logs.

Usage:  python tools/replay_cv_logs.py logs/cv_sessions/session_xxx.jsonl
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def parse_line(line: str) -> dict | None:
    try:
        return json.loads(line.strip())
    except json.JSONDecodeError:
        return None


def summarize_entries(entries):
    total = len(entries)
    primary_castable = sum(
        1 for e in entries
        if e.get("primary", {}).get("spell") is not None
        and e.get("primary", {}).get("confidence", 0) > 0
    )
    shadow_castable = sum(
        1 for e in entries
        if e.get("shadow", {}).get("spell") is not None
        and e.get("shadow", {}).get("confidence", 0) > 0
    )
    agreements = sum(1 for e in entries if e.get("agreement", False))
    attempts = sum(1 for e in entries if e.get("cast_attempted", False))
    successes = sum(1 for e in entries if e.get("cast_success", False))

    modes = Counter(e.get("mode", "?") for e in entries)
    primary_spells = Counter()
    shadow_spells = Counter()
    disagreement_pairs = Counter()
    block_reasons = Counter()
    intended_spells = Counter()
    labeled_total = 0
    primary_correct = 0
    shadow_correct = 0

    for e in entries:
        ps = e.get("primary", {}).get("spell")
        ss = e.get("shadow", {}).get("spell")
        intended = e.get("intended_spell")

        if ps:
            primary_spells[ps] += 1
        if ss:
            shadow_spells[ss] += 1
        if ps != ss:
            disagreement_pairs[f"P={ps} S={ss}"] += 1
        if e.get("cast_attempted") and not e.get("cast_success"):
            block_reasons[e.get("block_reason", "")] += 1
        if intended:
            labeled_total += 1
            intended_spells[intended] += 1
            if ps == intended:
                primary_correct += 1
            if ss == intended:
                shadow_correct += 1

    return {
        "total": total,
        "primary_castable": primary_castable,
        "shadow_castable": shadow_castable,
        "agreements": agreements,
        "attempts": attempts,
        "successes": successes,
        "modes": modes,
        "primary_spells": primary_spells,
        "shadow_spells": shadow_spells,
        "disagreement_pairs": disagreement_pairs,
        "block_reasons": block_reasons,
        "intended_spells": intended_spells,
        "labeled_total": labeled_total,
        "primary_correct": primary_correct,
        "shadow_correct": shadow_correct,
    }


def main(path: str):
    log_path = Path(path)
    if not log_path.exists():
        print(f"File not found: {log_path}")
        return

    entries = []
    malformed = 0
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = parse_line(line)
            if entry is None:
                malformed += 1
                continue
            entries.append(entry)

    total = len(entries)
    if total == 0:
        print(f"No valid entries found. Malformed lines: {malformed}")
        return

    summary = summarize_entries(entries)

    print(f"File: {log_path.name}")
    print(f"Total gestures: {summary['total']}")
    print(f"Malformed lines skipped: {malformed}")
    print()
    print(f"Primary castable predictions: {summary['primary_castable']}")
    print(f"Shadow  castable predictions:  {summary['shadow_castable']}")
    print(f"Shadow agreement:            {summary['agreements']}/{summary['total']}")
    print()
    print(f"Cast attempts:  {summary['attempts']}")
    print(f"Cast successes: {summary['successes']}")
    print()

    if summary["labeled_total"]:
        print(f"Labeled gestures: {summary['labeled_total']}")
        print(f"Primary matches intended: {summary['primary_correct']}/{summary['labeled_total']}")
        print(f"Shadow  matches intended: {summary['shadow_correct']}/{summary['labeled_total']}")
        print()
        print("Intended spell counts:")
        for spell, count in summary["intended_spells"].most_common():
            print(f"  {spell}: {count}")
        print()

    print("Per-mode counts:")
    for mode, count in summary["modes"].most_common():
        print(f"  {mode}: {count}")
    print()

    print("Primary spell counts:")
    for spell, count in summary["primary_spells"].most_common():
        print(f"  {spell}: {count}")
    print()

    print("Shadow spell counts:")
    for spell, count in summary["shadow_spells"].most_common():
        print(f"  {spell}: {count}")
    print()

    if summary["disagreement_pairs"]:
        print("Disagreements:")
        for pair, count in summary["disagreement_pairs"].most_common():
            print(f"  {pair}  count={count}")
        print()

    if summary["block_reasons"]:
        print("Block reasons (cast attempted but not cast):")
        for reason, count in summary["block_reasons"].most_common():
            print(f"  {reason}: {count}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/replay_cv_logs.py <path_to_session.jsonl>")
        sys.exit(1)
    main(sys.argv[1])
