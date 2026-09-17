"""Fail-closed A2 research governance primitives."""

from .judge import JudgeThresholds, evaluate_trial, render_scorecard
from .registry import RegistryError, build_leaderboard, load_registries, transition_model
from .schemas import FoldRecord, TrialInput

__all__ = [
    "FoldRecord",
    "JudgeThresholds",
    "RegistryError",
    "TrialInput",
    "build_leaderboard",
    "evaluate_trial",
    "load_registries",
    "render_scorecard",
    "transition_model",
]
