"""A2 Forward Shadow Unified Runner R1."""

from .components import ShadowComponent, SyntheticComponent
from .preflight import run_preflight
from .protocol import ProtocolStore
from .runner import UnifiedShadowRunner
from .schemas import ComponentIdentity, ComponentResult, RunnerConfig, RunIdentity

__all__ = [
    "ComponentIdentity", "ComponentResult", "ProtocolStore", "RunIdentity", "RunnerConfig",
    "ShadowComponent", "SyntheticComponent", "UnifiedShadowRunner", "run_preflight",
]
