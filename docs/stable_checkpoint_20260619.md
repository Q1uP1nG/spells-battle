# Stable Checkpoint - 2026-06-19

## Current State

- Public CV input modes are `finger` and bright-marker `wand`.
- `plain_wand` remains removed from public mode selection.
- PVE AI uses a visible windup before release, with default `cast_windup = 1.6s`.
- Bright-marker wand tracking uses HSV detection, candidate history, LK fallback, alpha-beta smoothing, short coasting, and structured wand debug logs.
- Gesture classification uses the hybrid pipeline, while gameplay still remains conservative around CV tracking quality.

## Latest Wand Stability Fixes

- `NO WAND` reset no longer clears `wand_candidate_history`.
  - This lets low-confidence but spatially stable marker candidates relock instead of being rejected forever as `unstable`.
- Stable LOST-state candidates can bypass stale prediction jump rejection.
  - This prevents an old predicted point from blocking a real marker that has reappeared consistently.
- Stable relock has a separate minimum confidence threshold:
  - single-frame lock remains stricter;
  - multi-frame stable relock can accept candidates down to `0.50`.

## Manual Test Focus

Run:

```powershell
python main.py
```

Then check:

- Wand mode calibrates with `C`.
- Yellow marker locks onto the bright wand tip within a few frames.
- If the marker briefly disappears, it relocks instead of staying `NO WAND unstable`.
- Fast turns may still show short `FLOW` or `COASTING`, but should not remain lost when the marker is visible.
- PVE AI should feel slower because release happens after the visible windup.

## Verification Commands

Last intended verification set:

```powershell
python -m compileall -q .
python -m unittest discover -s tests -v
```
