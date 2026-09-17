"""A2 Attribution Framework R1 public API."""

from .drawdown import detect_drawdown_episodes, drawdown_window_diagnostics
from .engine import AttributionEngine
from .incremental import IncrementalAttributionEngine
from .io import ImmutableInputError, verify_immutable_manifest
from .schemas import AttributionConfig, AttributionRow

__all__ = [
    "AttributionConfig",
    "AttributionEngine",
    "AttributionRow",
    "ImmutableInputError",
    "IncrementalAttributionEngine",
    "detect_drawdown_episodes",
    "drawdown_window_diagnostics",
    "verify_immutable_manifest",
]
