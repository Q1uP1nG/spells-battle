__all__ = ["BattleGame", "GameMode", "ModeRunner", "SimplePVEAI"]


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
    raise AttributeError(name)
