# Shadow DTW v2 Algorithm Upgrade Plan

## Background

The project has CV Training Mode. It freezes a completed gesture trail, then lets the user save, discard, or relabel the intended spell. Logs include trajectory points, `intended_spell`, primary heuristic output, and shadow template/DTW output.

There is not enough real labeled gesture data yet, so DTW/template must not control gameplay. The stable route is to keep the current heuristic classifier as primary, and use DTW/template only as a shadow/advice pipeline until replay results prove it is better.

## Principles

- Do not change official cast results yet.
- Do not change battle values, cooldowns, or PVE difficulty.
- Do not let DTW directly cast spells.
- Evaluate with CV Training logs before changing classifier behavior.
- Do not tune thresholds aggressively without real labeled data.
- Do not include plain wand / unmarked pen-tip detection in this plan.

## Next Algorithm Work

1. Upgrade the shadow template classifier:
   - Use multiple variants per spell instead of one synthetic template.
   - Add straight, curved, different-size, and different-speed variants.
   - Keep Protego as open-palm logic, outside DTW.

2. Improve DTW output:
   - Return top-1, top-2, distance, and margin.
   - Return `ambiguous` when the margin is small.
   - Preserve directional meaning; do not rotate-normalize.

3. Strengthen replay:
   - Compare primary and shadow against `intended_spell`.
   - Output per-spell accuracy.
   - Output a confusion matrix.
   - Count ambiguous cases and common mistake pairs.

## Future Handoff Condition

Only if real CV Training logs show shadow is consistently better than the heuristic on a specific spell should that spell be considered for partial handoff. Handoff should be per-spell, not an all-at-once classifier replacement.

## Recommended Sequence

1. Collect finger and bright-wand samples in CV Training.
2. Replay logs and compare primary vs shadow predictions.
3. Upgrade templates based on real mistake clusters.
4. Replay again.
5. Consider partial handoff only for spells where shadow clearly wins.
