"""Frozen FAST3-002 contract loading and safety checks."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


class ContractViolation(ValueError):
    pass


def canonical_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def config_sha256(value: dict) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ExecutableContract:
    contract_id: str
    version: str
    entry_mode: str
    default_entry_mode: str
    max_holding_minutes: int
    target_net_return: float
    stop_gross_return: float
    round_trip_cost_bps: tuple[int, ...]
    max_concurrent_positions: int
    initial_nav: float
    confirmation_start_et: str
    config_hash: str

    @classmethod
    def from_file(cls, path: str | Path) -> "ExecutableContract":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        supplied = raw.pop("config_sha256", None)
        calculated = config_sha256(raw)
        if supplied != calculated:
            raise ContractViolation("CONFIG_HASH_MISMATCH")
        if raw["default_entry_mode"] != "MODE_A_NEXT_BAR_OPEN":
            raise ContractViolation("DEFAULT_ENTRY_MODE_MUST_BE_CONSERVATIVE")
        if raw["portfolio"]["max_concurrent_positions"] != 1:
            raise ContractViolation("PRIMARY_PORTFOLIO_MUST_BE_SINGLE_POSITION")
        if raw["safety"]["live_trading_allowed"] or raw["safety"]["broker_action_allowed"]:
            raise ContractViolation("LIVE_OR_BROKER_ACTION_FORBIDDEN")
        return cls(
            contract_id=raw["contract_id"], version=raw["version"],
            entry_mode=raw["entry_modes"][raw["default_entry_mode"]]["price_source"],
            default_entry_mode=raw["default_entry_mode"],
            max_holding_minutes=raw["exit"]["max_holding_minutes"],
            target_net_return=raw["exit"]["target_net_return"],
            stop_gross_return=raw["exit"]["stop_gross_return"],
            round_trip_cost_bps=tuple(raw["cost"]["round_trip_scenarios_bps"]),
            max_concurrent_positions=raw["portfolio"]["max_concurrent_positions"],
            initial_nav=raw["portfolio"]["initial_nav"],
            confirmation_start_et=raw["confirmation_guard"]["confirmation_start_et"],
            config_hash=supplied,
        )


def assert_confirmation_forbidden(timestamps, confirmation_start_et: str) -> None:
    """Fail closed before any rows at/after Confirmation are evaluated."""
    import pandas as pd
    ts = pd.to_datetime(timestamps, errors="raise")
    boundary = pd.Timestamp(confirmation_start_et)
    if getattr(ts.dt, "tz", None) is None:
        ts = ts.dt.tz_localize(boundary.tz)
    elif boundary.tz is not None:
        ts = ts.dt.tz_convert(boundary.tz)
    if (ts >= boundary).any():
        raise ContractViolation("CONFIRMATION_PATH_FORBIDDEN")
