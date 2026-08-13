# Spells Current Project Brief

Updated: 2026-06-24

This is the active source of truth for the refactored project.

Plain/unmarked wand detection has been removed from the active project. Do not reintroduce it unless there is a new approved plan and evidence that it is worth rebuilding.

---

## Quick Start

```powershell
cd "D:\magic spale\magic spale\magic_spale_refactor"
python main.py
```

Main menu:

- `1`: Solo Spell Showcase
- `2`: Duel Battle Mode
- `3`: PVE Battle
- `4`: CV Training
- `Z` / `X`: cycle P1 character on menu
- `K` / `L`: cycle P2 character on menu
- `M`: return to menu
- `SPACE`: reset current round
- `B`: toggle BGM
- `N`: mute/unmute audio
- `ESC`: quit

In-game CV keys:

- `V`: cycle input mode (`finger` -> `wand` -> `finger`)
- `C`: lock bright wand marker color, only in `wand` mode
- `D`: toggle compact / verbose CV debug overlay

CV Training keys:

- `Enter`: save frozen sample
- `Backspace` or `Space`: discard sample
- `4` / `5` / `6` / `7` / `8`: relabel pending sample as Incendio / Stupefy circle / Glacius / Overload / Lumos

Optional evaluation labels can be set before launch. Use anonymous labels chosen by the user;
do not use a real name or hardware serial number:

```powershell
$env:SPELLS_CV_USER_ID="player-a"
$env:SPELLS_CV_DEVICE_ID="laptop-camera-a"
python main.py
```

New gesture logs use Schema v2 and include stable sample/session IDs, input mode,
frame size, FPS estimate, palm scale when available, review state, classifier version,
and the optional anonymous labels. Existing Schema v1 logs remain readable.

Mode 4 resumes saved progress from `logs/cv_training/progress.json`. Leaving to the menu and entering Mode 4 again keeps the accepted sample counts. Pressing `SPACE` while not reviewing a pending sample resets the current training progress.

Character selection is available on the menu and is saved with user settings:

| Character | Current Buff | Presentation States |
| --- | --- | --- |
| Harry | +15% projectile damage | normal / casting / hit / win / lose |
| Hermione | shorter spell cooldown and global cooldown | normal / casting / hit / win / lose |
| Ron | +20% max HP | normal / casting / hit / win / lose |
| Snape | projectiles resist normal counter removal | normal / casting / hit / win / lose |

The character visuals are still code-drawn placeholders. The system is ready for future portrait/sprite assets, but no external character art is required to run the current build.

---

## Current Modes

### Solo Spell Showcase

Training-dummy mode. The dummy does not actively fight. When dummy HP reaches 0, the screen shows `DUMMY DEFEATED`; press `SPACE` to reset.

### Duel Battle

Two players fight on the same camera screen. P1 is left, P2 is right.

### PVE Battle

P1 fights a simple rule-based opponent. The opponent can attack, shield, and heal. This should be described as PVE Battle, not as advanced AI.

### CV Training

Separate gesture-data mode. Normal gameplay does not ask for labels. CV Training freezes the completed trail for review so future classifier changes can be judged from real logs.

---

## Input Paths

### Finger

Uses the index fingertip. This is the simplest CV input path and remains useful for testing gesture rules.

### Bright Wand

Uses `cv/wand_detector.py` to track a saturated colored marker on the wand tip.

Setup:

1. Put a small bright marker on the tip.
2. Press `V` until the status shows wand mode.
3. Put the marker inside the center calibration target.
4. Press `C`.
5. After `CV WAND LOCKED`, draw spells with the marked tip.

### Removed Route

Unmarked pen/chopstick detection was removed because the labeled experiment showed only limited improvement. The current priority is bright-marker stability and trajectory training.

---

## Spell Actions

| Spell | CV Action | Keyboard P1/P2 | Effect |
| --- | --- | --- | --- |
| Incendio | Horizontal push toward opponent | `Q` / `U` | Fire projectile |
| Stupefy | Closed loop / circle | `W` / `I` | Projectile plus silence |
| Glacius | Downward slash | `E` / `O` | Ice projectile plus slow |
| Protego | Open palm hold | `R` / `P` | Shield |
| Lumos | Upward flick | `T` / `L` | Heal after channel |
| Overload | Multi-zigzag lightning | CV only | Projectile, consumes all mana, disables target buffs |

Protego is open palm, not a drawn U. Stupefy now uses a circle gesture; zigzag gestures belong to Overload. Overload currently has no default keyboard binding.

---

## Current Implementation State

- `python main.py` is the main entrypoint.
- `game/battle.py` owns casting, mana, cooldowns, shields, projectiles, interactions, damage, and winner state.
- Global cooldown and per-spell cooldowns are active.
- Audio dispatch works through `game/audio.py`; external files are loaded first, synthesized fallback sounds remain.
- Character profiles are implemented in `game/characters.py`; battle buffs are applied through `models/player.py` and `game/battle.py`.
- Menu character selection persists through `game/settings.py`.
- Transparent character art from `pictures_transparent/` is used by the character-select screen and battle player renderer. Missing art falls back to the old code-drawn player.
- CV state has explicit cast states and clearer debug text than the original monolithic file.
- CV Training logs `intended_spell`, primary fused/heuristic prediction, and shadow template/DTW prediction.
- CV Training persists accepted sample counts in `logs/cv_training/progress.json`, so a partially recorded set can be resumed after returning to the menu.
- When `models/gesture_templates.json` is available, `DataTemplateClassifier` is used inside the primary `FusedGestureClassifier`; it can boost confidence when it agrees with the heuristic and can rescue a no-match heuristic result at high confidence.
- `ShadowTemplateClassifier` is still a separate fixed-template comparison path and does not control gameplay.
- The active CV input modes are only `finger` and bright-marker `wand`.
- Settings from older builds that contain `plain_wand` fall back to `finger`.
- Remote Duel uses an authoritative server. Each connection has a bounded reliable FIFO,
  one latest-snapshot slot, an independent sender task, send timeout/backpressure cleanup,
  and lifetime health metrics. The battle Tick never waits for a real WebSocket send.
- Normalized gesture features and cyclic Stupefy DTW are diagnostic Shadow paths. The cyclic
  candidate is not promoted because grouped data is insufficient and its measured latency is
  above the real-time gate; `CV_CYCLIC_STUPEFY_PRIMARY` remains disabled.

---

## Current Weaknesses

### Bright Wand Stability

The bright marker path is the most valuable wand route but still needs tuning. Known issues:

- bright white lamps can attract detection if saturation gating is too loose
- fast motion can cause short gaps
- coasting must remain short so stale predictions do not become real gesture input
- debug text needs to make detector / LK / coasting / lost states obvious

### Gesture Classification

The default primary classifier is conservative fusion when the representative trajectory template pack is present, and falls back to the runtime hybrid/heuristic path when it is not. This is non-parametric DTW matching, not a trained supervised model. DTW/template influence is intentionally limited: agreement adds confidence, high-confidence template rescue can recover a heuristic no-match, and conflicts keep the heuristic result. The fixed-template shadow classifier remains diagnostic only.

### Frontend Presentation

The game is functional, but presentation can still improve:

- reduce clutter during gameplay
- keep instructions on intro/menu/training screens instead of overloading HUD
- make mode copy concise and player-facing
- tune character art placement, scale, and cropping after manual playtesting
- preserve the current spell effect UI where it already feels good

---

## Next Priority Order

1. Collect Stupefy samples across more independent sessions before reconsidering cyclic DTW.
2. Stabilize bright-marker wand tracking and collect both finger and wand Schema v2 samples.
3. Run user/device-grouped evaluation only after genuine anonymous user/device groups exist.
4. Improve frontend polish and reduce on-screen clutter.
5. Deploy and run two-device public acceptance only when the deployment work is resumed.

Do not spend more time on unmarked pen/chopstick detection unless the project goal changes.

---

## Verification Commands

```powershell
python -m compileall -q .
python -m unittest discover -s tests -v
python main.py
```
