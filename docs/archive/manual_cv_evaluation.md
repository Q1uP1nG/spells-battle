# Manual CV Evaluation Protocol

Use this checklist whenever gesture classification or wand detection changes. Do not rely on "it felt okay" when judging CV accuracy.

## Setup

1. Start the app:

```powershell
cd "D:\magic spale\magic spale\magic_spale_refactor"
python main.py
```

2. Choose a mode:
   - `1` Solo is best for isolated CV testing.
   - `3` PVE is useful only after Solo works.
3. If verbose CV debug is available, press `D` to enable it.  When the shadow pipeline is active, the debug overlay shows both the primary heuristic prediction (`H=...`) and the shadow DTW/template prediction (`S=...`).
4. Test finger mode and wand mode separately.

## Test Procedure

For each spell, perform 10 attempts.

Before each attempt:

- wait for local spell cooldown to clear
- wait for global cooldown to clear
- make sure mana is available
- make sure the player is not silenced
- in wand mode, confirm the marker is calibrated and visible

After each attempt, record the result:

| Result | Meaning |
| --- | --- |
| `CAST <spell>` | correct spell triggered |
| `CAST <wrong>` | wrong spell triggered |
| no cast | gesture did not pass tracking/classification |
| blocked | mana, silence, local cooldown, global cooldown, or round end blocked the cast |

Candidate predictions shown while the hand/wand is still moving do not count as casts. Count only the final `CAST <spell>` result or the final blocked/no-trigger reason after the stroke ends.

## Tracking Sheet

Copy this table for each evaluation session:

```text
Date: ________  Mode: [finger / wand]  Lighting: ________  Debug: [on / off]

Spell     Attempts  Correct  WrongSpell  NoTrigger  Blocked  CommonReason  Notes
-------   --------  -------  ----------  ---------  -------  ------------  -----
Incendio     10       __        __          __         __       __________  ____
Glacius      10       __        __          __         __       __________  ____
Lumos        10       __        __          __         __       __________  ____
Stupefy      10       __        __          __         __       __________  ____
Protego      10       __        __          __         __       __________  ____
```

## Success Targets

| Input path | Target |
| --- | --- |
| Keyboard | 10/10, used as battle-logic baseline |
| Finger mode | at least 7/10 per spell before claiming demo-ready |
| Wand mode with bright marker | at least 7/10 for Incendio, Glacius, Lumos before claiming demo-ready |

Stupefy may be harder because it depends on turn counting and consistent tracking.

## Debug Values To Watch

Useful debug fields:

- point count
- path length
- `dx` / `dy`
- straightness
- turn count
- predicted spell and confidence
- shadow spell and confidence (if shadow pipeline is enabled)
- primary/shadow agreement or disagreement
- rejection reason
- cast-block reason such as `MP`, `SILENCE`, `CD`, or `GCD`

When a spell fails:

1. Check whether tracking produced enough points.
2. Check whether the path was long enough.
3. Check whether the expected direction was strong enough.
4. Check whether another matcher fired first.
5. Check whether the cast was blocked after classification.

## Wand-Specific Notes

Record these in the notes column:

- marker color
- lighting condition
- approximate camera distance
- whether the hand was detected
- whether calibration said locked
- whether the marker disappeared near the palm or frame edge

Common wand failure causes:

| Symptom | Likely cause |
| --- | --- |
| `uncalibrated` | press `C` in wand mode |
| no bright tip | marker hidden, too dim, or wrong hue |
| empty ROI | hand not detected or ROI too small |
| intermittent loss | lighting change, low saturation, motion blur, or marker leaving ROI |

## Post-Session Analysis

After a session, replay the JSONL gesture log to compare the heuristic primary and DTW shadow predictions:

```powershell
python tools/replay_cv_logs.py logs/cv_sessions/session_xxx.jsonl
```

Use this output to:

- count how often primary and shadow agree
- identify which spell pairs cause the most disagreement
- decide whether the shadow classifier is ready to vote on or replace any individual spell

Do not replace the heuristic primary with the shadow classifier until real logs show the shadow is consistently more stable for that spell.

## Frequency

Run this evaluation:

- after changing classifier thresholds
- after changing wand detector constants
- after changing CV state transitions
- before saying the CV path is demo-ready

Do not publish accuracy numbers without a filled evaluation sheet.
