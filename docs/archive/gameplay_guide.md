# Spells Gameplay Guide

This guide describes the current runnable behavior of the refactored project.

## Start

```powershell
cd "D:\magic spale\magic spale\magic_spale_refactor"
python main.py
```

Main menu:

- `1`: Solo Spell Showcase
- `2`: Duel Battle Mode
- `3`: PVE Battle
- `M`: return to menu
- `SPACE`: reset current round
- `B`: toggle BGM
- `N`: mute/unmute audio
- `ESC`: quit

## Goal

Reduce the opponent's HP to 0.

The HUD shows:

- `HP`: health
- `MANA`: casting resource, regenerates over time
- `SH`: Protego shield value
- `Silence`: remaining silence time
- `Last`: last spell or cast-block message
- spell boxes: each spell's local cooldown, global cooldown, mana block, or ready state

Successful casts trigger two cooldowns:

- a spell-specific cooldown, such as Incendio's own cooldown
- a 1.0 second global cooldown that briefly blocks other spells

If a spell box shows `G0.7` or the spell guide shows `GCD 0.7`, wait for the global cooldown to clear.

## Modes

### Solo Spell Showcase

Solo is a training-dummy mode. The dummy does not actively fight. When its HP reaches 0, the screen shows:

```text
DUMMY DEFEATED
Press SPACE to reset
```

### Duel Battle Mode

Two players fight on the same camera screen. P1 is on the left side and P2 is on the right side.

### PVE Battle

P1 fights a simple AI opponent. The AI can attack, shield, and heal. If the AI reaches 0 HP, the screen uses the dummy-defeated ending. If P1 reaches 0 HP, the normal winner overlay appears.

## Keyboard Controls

Keyboard casting is always available and is the most stable debug path.

| Spell | P1 | P2 |
| --- | --- | --- |
| Incendio | `Q` | `U` |
| Stupefy | `W` | `I` |
| Glacius | `E` | `O` |
| Protego | `R` | `P` |
| Lumos | `T` | `L` |

## CV Finger Mode

Finger mode is the default CV input mode. The system tracks the index fingertip as the spell trajectory.

- Left half of the screen maps to P1.
- Right half of the screen maps to P2.
- In Solo/PVE, CV input is treated as P1 input.

## CV Wand Mode

Press `V` to switch between finger mode and wand mode.

Current wand mode supports a bright colored marker on the tip of a pen/chopstick. It does not reliably support an unmarked ordinary object yet.

To use it:

1. Put a small bright marker on the tip, such as yellow, green, cyan, or pink tape.
2. Press `V` to enter wand mode.
3. Place the marker inside the center calibration circle.
4. Press `C` to lock the color.
5. After `CV WAND LOCKED`, draw spells with the marked tip.

Screen cues:

- Center circle/crosshair: wand color calibration target.
- `CENTER MARKER + C TO LOCK`: put the marker in the center and press `C`.
- Yellow circle near the hand: detected wand tip candidate.
- `YELLOW CIRCLE = TIP | C RELOCK`: the yellow circle is the current tip; press `C` again if lighting or marker color changes.

## Spell Actions

| Spell | CV action | Mana | Local cooldown | Effect |
| --- | --- | ---: | ---: | --- |
| Incendio | Fast horizontal push toward the opponent | 25 | 3.0s | Fire projectile, 22 damage on hit |
| Stupefy | Multi-turn zigzag / lightning path | 35 | 5.0s | Red projectile, 16 damage and 1.0s silence |
| Glacius | Clear downward slash | 30 | 4.6s | Ice projectile, 10 damage and 2.0s slow |
| Protego | Hold an open palm briefly | 30 | 6.0s | 35 shield for 3.0s |
| Lumos | Fast upward flick | 40 | 8.0s | Heals 18 HP after a 1.2s channel |

Protego is currently triggered by open palm, not by drawing a U shape.

## Spell Interactions

Projectile clashes use a simple interaction table:

- Glacius beats Incendio.
- Incendio beats Stupefy.
- Stupefy beats Glacius.
- Same-type projectiles usually cancel each other.

These clashes now have dedicated sound events, so the counter relationship should be audible as well as visible.

Protego can block projectiles, but the shield value is consumed. Lumos healing can be interrupted by Incendio or Stupefy.

## CV Tips

- Incendio: draw a clear horizontal push. P1 should push left-to-right; P2 should push right-to-left.
- Stupefy: use several direction changes, like a lightning stroke.
- Glacius: draw a decisive top-to-bottom slash.
- Lumos: make the upward flick larger than a normal hand lift.
- Protego: open the palm and hold still briefly.

If CV does not trigger, check the bottom debug text. Common causes are:

- trajectory too short
- motion too slow
- not enough mana
- spell local cooldown
- global cooldown
- silence
- no hand/tip detected
- wand marker not calibrated or not visible

During a stroke, CV may show a candidate prediction such as `INC`, but it now waits for the gesture to end before actually casting. This is intentional: it reduces half-drawn accidental casts.

## Current Limits

- Gesture classification is heuristic, not trained.
- Wand mode currently depends on a visible bright marker.
- Keyboard mode is the best fallback for confirming battle logic.
- CV mode is the main area that still needs measurement and tuning.
