"""Mobilerun Macro Module - Record and replay UI automation sequences."""

__all__ = [
    "MacroPlayer",
    "RecoveryOutcome",
    "RunResult",
    "replay_macro_file",
    "replay_macro_file_result",
    "replay_macro_folder",
]


def __getattr__(name):
    if name in {
        "MacroPlayer",
        "replay_macro_file",
        "replay_macro_file_result",
        "replay_macro_folder",
    }:
        from mobilerun.macro import replay

        return getattr(replay, name)
    if name in {"RecoveryOutcome", "RunResult"}:
        from mobilerun.macro import contracts

        return getattr(contracts, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
