"""Runtime exports loaded lazily to avoid importing ADB during utility imports."""
from importlib import import_module

__all__ = ["BreakManager", "GameState", "GameStateMachine", "RuntimeTracker"]


def __getattr__(name):
    modules = {"BreakManager": "breaks", "GameState": "game_state",
               "GameStateMachine": "game_state", "RuntimeTracker": "tracker"}
    if name not in modules:
        raise AttributeError(name)
    value = getattr(import_module(f"coc_bot.runtime.{modules[name]}"), name)
    globals()[name] = value
    return value
