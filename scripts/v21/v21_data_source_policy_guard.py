#!/usr/bin/env python
"""Central V21 data source policy guard.

This module is intentionally provider-neutral. It does not import market-data
SDKs and does not make network calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_POLICY = {
    "policy_version": "V21.229_R1",
    "default_data_source_policy": "MOOMOO_ONLY",
    "allowed_active_sources": ["MOOMOO_OPEND", "LOCAL_MOOMOO_CACHE", "MANUAL_MOOMOO_IMPORT_WITH_TAG"],
    "forbidden_default_sources": ["YFINANCE", "YAHOO"],
    "external_fallback_policy": "DIAGNOSTIC_ONLY_EXPLICIT_APPROVAL_REQUIRED",
    "yfinance_allowed_by_default": False,
    "yahoo_allowed_by_default": False,
    "yfinance_allowed_for_canonical": False,
    "yfinance_allowed_for_dram": False,
    "yfinance_allowed_for_abcde": False,
    "external_fallback_allowed_for_canonical": False,
    "external_fallback_allowed_for_dram": False,
    "external_fallback_allowed_for_abcde": False,
    "broker_action_allowed": False,
    "official_adoption_allowed": False,
    "research_only": True,
}


def _default_policy_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "v21" / "data_source_policy.json"


def load_data_source_policy(policy_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(policy_path) if policy_path else _default_policy_path()
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                merged = dict(DEFAULT_POLICY)
                merged.update(payload)
                return merged
        except (OSError, json.JSONDecodeError):
            pass
    return dict(DEFAULT_POLICY)


def classify_data_source_usage(source_name: str, context: str) -> str:
    source = source_name.strip().upper()
    ctx = context.strip().lower()
    if source in {"MOOMOO", "MOOMOO_OPEND", "LOCAL_MOOMOO_CACHE", "MANUAL_MOOMOO_IMPORT_WITH_TAG"}:
        return "ALLOWED_ACTIVE"
    if source in {"YFINANCE", "YAHOO"}:
        return "FORBIDDEN_ACTIVE"
    if source in {"EXTERNAL_FALLBACK", "STOOQ", "PANDAS_DATAREADER", "POLYGON", "TIINGO", "QUANDL"}:
        return "DIAGNOSTIC_ONLY_ALLOWED" if "diagnostic" in ctx else "FORBIDDEN_ACTIVE"
    return "UNKNOWN_REVIEW_REQUIRED"


def assert_yfinance_disabled(context: str) -> None:
    policy = load_data_source_policy()
    if policy.get("yfinance_allowed_by_default") is not False:
        raise RuntimeError(f"Forbidden data source enabled in context={context}")


def assert_moomoo_only_policy(context: str, allow_diagnostic_external: bool = False) -> None:
    policy = load_data_source_policy()
    if policy.get("default_data_source_policy") != "MOOMOO_ONLY":
        raise RuntimeError(f"Moomoo-only data source policy is not active for context={context}")
    assert_yfinance_disabled(context)
    if not allow_diagnostic_external:
        lowered = context.lower()
        if any(role in lowered for role in ["canonical", "dram", "abcde"]):
            for key in [
                "external_fallback_allowed_for_canonical",
                "external_fallback_allowed_for_dram",
                "external_fallback_allowed_for_abcde",
            ]:
                if policy.get(key):
                    raise RuntimeError(f"External fallback is forbidden for active chain context={context}")


def policy_flags_for_summary() -> dict[str, Any]:
    policy = load_data_source_policy()
    return {
        "data_source_policy": policy.get("default_data_source_policy", "MOOMOO_ONLY"),
        "yfinance_allowed_by_default": False,
        "yahoo_allowed_by_default": False,
        "yfinance_allowed_for_canonical": False,
        "yfinance_allowed_for_dram": False,
        "yfinance_allowed_for_abcde": False,
        "external_fallback_allowed_for_canonical": False,
        "external_fallback_allowed_for_dram": False,
        "external_fallback_allowed_for_abcde": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
    }
