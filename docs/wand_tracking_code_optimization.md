# Bright-Marker Wand Tracking Optimization Notes

## Current Direction

Plain/unmarked wand detection has been removed from the active project. The wand path now means bright-marker wand only: the user puts a saturated colored marker on the tip, enters `wand` mode with `V`, and locks the marker color with `C`.

The tracking stack should stay conservative:

```text
HSV calibrated detector
-> contour scoring
-> LK short-term flow fallback
-> alpha-beta smoothing / short coasting
-> confidence gate
-> explicit LOST state
```

Do not replace this with KCF/CSRT/MOSSE or a deep model unless there is strong evidence that the current lightweight route cannot be stabilized.

## Main Known Weaknesses

- Bright white lamps can attract the marker detector if calibration captured low-saturation or over-bright pixels.
- Fast motion can still cause short gaps.
- Coasting must remain short; stale predicted points should not become gesture input for long.
- Debug output must clearly say whether the point came from detector, LK flow, prediction, or no source.

## Recommended Next Work

1. Tighten calibration:
   - During `C` calibration, ignore low-saturation pixels.
   - Reject calibration if the patch has too few high-confidence marker pixels.
   - Report a clear message such as `CALIBRATION LOW SAT` or `MOVE MARKER TO CENTER`.

2. Reject white-light attraction:
   - Require hue confidence plus minimum saturation.
   - Penalize candidates with very high value but weak saturation.
   - Add tests with a white lamp blob near a colored marker.

3. Improve reacquire behavior:
   - Prefer the previous predicted position when multiple candidates are close.
   - Search around the predicted point first, then expand to hand ROI.
   - Keep `COASTING` under a short timeout.

4. Keep logs human-readable:
   - `WAND LOCKED detector 0.82`
   - `WAND FLOW lk 0.51`
   - `WAND COASTING 0.32`
   - `WAND LOST low_sat` / `low_score` / `no_candidate`

## Boundaries

- Do not reintroduce plain wand / unmarked pen-tip detection.
- Do not alter battle rules.
- Do not alter gesture classification while tuning point tracking.
- Keep finger mode and open-palm Protego intact.
