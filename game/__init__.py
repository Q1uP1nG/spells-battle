__all__ = [
    "BattleGame",
    "BattleSession",
    "CastIntent",
    "CastSubmission",
    "GameMode",
    "LocalBattleSession",
    "ModeRunner",
    "SimplePVEAI",
]


def __getattr__(name):
    if name == "BattleGame":
        from game.battle import BattleGame

        return BattleGame
    if name in ("GameMode", "ModeRunner"):
        from game.mode import GameMode, ModeRunner

        return {"GameMode": GameMode, "ModeRunner": ModeRunner}[name]
    if name == "SimplePVEAI":
        from game.pve_ai import SimplePVEAI

        return SimplePVEAI
    if name in ("CastIntent", "CastSubmission"):
        from game.commands import CastIntent, CastSubmission

        return {"CastIntent": CastIntent, "CastSubmission": CastSubmission}[name]
    if name in ("BattleSession", "LocalBattleSession"):
        from game.session import BattleSession, LocalBattleSession

        return {"BattleSession": BattleSession, "LocalBattleSession": LocalBattleSession}[name]
    raise AttributeError(name)
