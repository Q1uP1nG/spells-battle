from __future__ import annotations

from dataclasses import dataclass


PROTOCOL_VERSION = 1


def _remaining(until, now):
    return max(0.0, float(until) - float(now))


@dataclass(frozen=True)
class PlayerSnapshot:
    player_index: int
    character_id: str
    hp: float
    max_hp: float
    mana: float
    global_cooldown_remaining: float
    spell_cooldown_remaining: tuple[tuple[str, float], ...]
    shield_value: float
    shield_remaining: float
    silence_remaining: float
    frozen_remaining: float
    healing_remaining: float
    pending_heal: float
    mana_regen_boost_remaining: float
    buff_disabled_remaining: float


@dataclass(frozen=True)
class ProjectileSnapshot:
    projectile_id: int
    owner: int
    spell: str
    x: float
    y: float
    vx: float
    vy: float
    radius: float
    damage: float
    color: tuple[int, int, int]
    life_remaining: float


@dataclass(frozen=True)
class BattleSnapshot:
    protocol_version: int
    match_id: str
    server_tick: int
    match_time: float
    players: tuple[PlayerSnapshot, PlayerSnapshot]
    projectiles: tuple[ProjectileSnapshot, ...]
    winner: int | None


def snapshot_from_engine(engine, match_id, server_tick, match_time):
    players = []
    for player in engine.players:
        cooldowns = tuple(
            (name, _remaining(until, match_time))
            for name, until in sorted(player.spell_cooldown_until.items())
        )
        players.append(
            PlayerSnapshot(
                player_index=int(player.pid),
                character_id=str(player.character_id),
                hp=float(player.hp),
                max_hp=float(player.max_hp),
                mana=float(player.mana),
                global_cooldown_remaining=_remaining(player.global_cooldown_until, match_time),
                spell_cooldown_remaining=cooldowns,
                shield_value=float(player.shield_value),
                shield_remaining=_remaining(player.shield_until, match_time),
                silence_remaining=_remaining(player.silenced_until, match_time),
                frozen_remaining=_remaining(player.frozen_until, match_time),
                healing_remaining=_remaining(player.healing_until, match_time),
                pending_heal=float(player.pending_heal),
                mana_regen_boost_remaining=_remaining(player.mana_regen_boost_until, match_time),
                buff_disabled_remaining=_remaining(player.buff_disabled_until, match_time),
            )
        )

    projectiles = tuple(
        ProjectileSnapshot(
            projectile_id=int(projectile.projectile_id),
            owner=int(projectile.owner),
            spell=str(projectile.spell),
            x=float(projectile.pos[0]),
            y=float(projectile.pos[1]),
            vx=float(projectile.vel[0]),
            vy=float(projectile.vel[1]),
            radius=float(projectile.radius),
            damage=float(projectile.damage),
            color=tuple(int(value) for value in projectile.color),
            life_remaining=float(projectile.life),
        )
        for projectile in engine.projectiles
        if projectile.active
    )
    return BattleSnapshot(
        protocol_version=PROTOCOL_VERSION,
        match_id=str(match_id),
        server_tick=int(server_tick),
        match_time=float(match_time),
        players=tuple(players),
        projectiles=projectiles,
        winner=None if engine.winner is None else int(engine.winner),
    )
