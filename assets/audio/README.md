# Audio Assets

The game loads external audio first and falls back to generated synth sounds when a file is missing.

Supported formats:

- `.ogg`
- `.wav`

## Runtime Paths

```text
assets/audio/
  sfx/
    incendio.ogg
    stupefy.ogg
    glacius.wav
    protego.ogg
    lumos.ogg
    hit.ogg
    shield_hit.ogg
    cast_fail.ogg
    menu_select.ogg
    round_over.ogg
    clash_fire_lightning.ogg
    clash_lightning_ice.ogg
    clash_ice_fire.wav
    clash_cancel.ogg
  bgm/
    battle_loop.wav
```

## Event Mapping

| File | Used for |
| --- | --- |
| `incendio` | fire spell cast |
| `stupefy` | lightning/stun spell cast |
| `glacius` | ice spell cast |
| `protego` | shield activation |
| `lumos` | healing cast and heal completion |
| `hit` | projectile hits a player |
| `shield_hit` | projectile hits a shield |
| `cast_fail` | cast blocked by mana, cooldown, silence, or round state |
| `menu_select` | menu option selected |
| `round_over` | battle end |
| `clash_fire_lightning` | Incendio beats Stupefy |
| `clash_lightning_ice` | Stupefy beats Glacius |
| `clash_ice_fire` | Glacius beats Incendio |
| `clash_cancel` | same-spell or unlisted projectile clash |
| `battle_loop` | looping BGM |

## Controls

- `B`: toggle BGM.
- `N`: mute/unmute audio.

## Sources And License

The first bundled asset pass uses CC0 sources from OpenGameArt:

- 80 CC0 RPG SFX: https://opengameart.org/content/80-cc0-rpg-sfx
- Magic Spell SFX: https://opengameart.org/content/magic-spell-sfx
- Ice Spells: https://opengameart.org/content/ice-spells
- Fast fight / battle music looped: https://opengameart.org/content/fast-fight-battle-music-looped

Keep future replacements CC0 or otherwise clearly licensed for redistribution. Avoid franchise, film, or game rip audio.
