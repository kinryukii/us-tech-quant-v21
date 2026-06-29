#!/usr/bin/env python
"""Validate V21.129 D continued tracking strict adoption gate outputs."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE"
OUT = ROOT / "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE"
V128 = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE"
MAIN_SCRIPT = ROOT / "scripts/v21/v21_129_d_continued_tracking_and_strict_adoption_gate.py"

SUMMARY = OUT / "V21.129_summary.json"
READABLE_REPORT = OUT / "V21.129_readable_report.txt"
COMPACT_REPORT = OUT / "V21.129_compact_report.txt"
STRICT_GATES = OUT / "V21.129_d_strict_gate_results.csv"
TOP20 = OUT / "V21.129_d_tracking_top20.csv"
TOP50 = OUT / "V21.129_d_tracking_top50.csv"
FORWARD_COMPARISON = OUT / "V21.129_d_vs_a1_forward_comparison.csv"
CONCENTRATION = OUT / "V21.129_d_concentration_diagnostic.csv"
REPEATED_LOSER = OUT / "V21.129_d_repeated_loser_diagnostic.csv"
REGIME = OUT / "V21.129_d_regime_gate_diagnostic.csv"

V128_SUMMARY = V128 / "V21.128_summary.json"
V128_PROTECTED = [
    V128 / "V21.128_summary.json",
    V128 / "V21.128_readable_report.txt",
    V128 / "V21.128_compact_report.txt",
    V128 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv",
    V128 / "A1_BASELINE_CONTROL_latest_ranking.csv",
]
EXPECTED_V128_SHA256 = {
    "V21.128_summary.json": "9769d42521e1aace56930c2e4d553de4472c77d176d64143cf1751211233a71c",
    "V21.128_readable_report.txt": "bd6e99582cf23f201aaf9d4b340a2cb7139c9d8bd6dd2d6dbac0cc929dba2af3",
    "V21.128_compact_report.txt": "8763446cf2d70e3712ec6a247819e334db0a9b63740151b40b91169be841835a",
    "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv": "014bc942860b969185090998730178177a740b52b1985d8c2134e8299b3c3f01",
    "A1_BASELINE_CONTROL_latest_ranking.csv": "60197c9c964b2666258a2d5154ff2b97d9ca667aed964a1585653afe570d59a9",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def finite_or_blank(value: Any) -> bool:
    if value in ("", None):
        return True
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return False
    return not math.isinf(parsed)


def validate_files() -> None:
    required = [
        MAIN_SCRIPT,
        OUT,
        SUMMARY,
        READABLE_REPORT,
        COMPACT_REPORT,
        STRICT_GATES,
        TOP20,
        TOP50,
        FORWARD_COMPARISON,
        CONCENTRATION,
        REPEATED_LOSER,
        REGIME,
    ]
    for path in required:
        require(path.exists(), f"missing required path: {path}")


def validate_outputs(summary: dict[str, Any]) -> None:
    require(len(pd.read_csv(TOP20)) == 20, "V21.129_d_tracking_top20.csv must contain 20 rows")
    require(len(pd.read_csv(TOP50)) == 50, "V21.129_d_tracking_top50.csv must contain 50 rows")

    gates = csv_rows(STRICT_GATES)
    require(gates, "strict gate results must not be empty")
    allowed_status = {"PASS", "BLOCK", "UNKNOWN"}
    for row in gates:
        require(row.get("status") in allowed_status, f"invalid gate status: {row}")
    gate_names = {row.get("gate") for row in gates}
    for gate in [
        "DATA_FRESHNESS",
        "DATA_QUALITY_WARNING",
        "MATURITY",
        "VS_A1_PERFORMANCE",
        "VS_QQQ_PERFORMANCE",
        "CONCENTRATION_RISK",
        "LEFT_TAIL_DRAWDOWN_RISK",
        "REPEATED_LOSER_RISK",
        "REGIME_COMPATIBILITY",
    ]:
        require(gate in gate_names, f"missing strict gate: {gate}")

    require(as_bool(summary.get("D_continued_tracking")) is True, "D_continued_tracking must be true")
    require(as_bool(summary.get("D_adoption_allowed")) is False, "D_adoption_allowed must be false")
    require(as_bool(summary.get("official_adoption_allowed")) is False, "official_adoption_allowed must be false")
    require(as_bool(summary.get("broker_action_allowed")) is False, "broker_action_allowed must be false")
    require(as_bool(summary.get("protected_outputs_modified")) is False, "protected_outputs_modified must be false")
    require(as_bool(summary.get("research_only")) is True, "research_only must be true")
    require(as_bool(summary.get("no_future_leakage")) is True, "summary no_future_leakage must be true")
    require(as_bool(summary.get("v21_128_baseline_preserved")) is True, "V21.128 baseline must be marked preserved")
    require("PROMOTED" not in str(summary.get("D_status", "")).upper(), "D must not be promoted automatically")
    require(summary.get("D_status") != "ADOPTED", "D must not be adopted")

    loser_rows = csv_rows(REPEATED_LOSER)
    require(loser_rows, "repeated loser diagnostic must not be empty")
    loser = loser_rows[0]
    for field in [
        "D_repeated_loser_ticker_count",
        "D_repeated_loser_tickers",
        "D_top20_repeated_loser_overlap_tickers",
        "D_top20_repeated_loser_weight",
        "D_repeated_loser_risk_level",
    ]:
        require(field in loser, f"repeated loser diagnostic missing {field}")
    loser_tickers = [ticker for ticker in loser["D_repeated_loser_tickers"].split("|") if ticker]
    require(int(float(loser["D_repeated_loser_ticker_count"])) == len(loser_tickers), "repeated loser count must match emitted ticker list")
    require(loser["D_repeated_loser_risk_level"] in {"LOW", "MEDIUM", "HIGH"}, "invalid repeated loser risk level")
    require(finite_or_blank(loser["D_top20_repeated_loser_weight"]), "invalid repeated loser weight")

    regime_rows = csv_rows(REGIME)
    require(regime_rows, "regime gate diagnostic must not be empty")
    require(regime_rows[0].get("current_regime"), "regime diagnostic missing current_regime")


def validate_v128_preserved() -> None:
    for path in V128_PROTECTED:
        require(path.is_file(), f"missing V21.128 protected baseline file: {path}")
        expected = EXPECTED_V128_SHA256.get(path.name)
        require(expected is not None, f"missing expected hash for {path.name}")
        require(sha256(path) == expected, f"V21.128 protected file changed: {path.name}")


def validate_no_future_leakage(summary: dict[str, Any]) -> None:
    v128_summary = load_json(V128_SUMMARY)
    latest_price_date = str(v128_summary.get("latest_price_date_used", ""))
    require(latest_price_date, "V21.128 latest_price_date_used missing")
    require(str(summary.get("latest_price_date_used", "")) == latest_price_date, "latest price date mismatch")
    for path in [TOP20, TOP50]:
        frame = pd.read_csv(path)
        if "latest_price_date" in frame:
            max_date = frame["latest_price_date"].dropna().astype(str).max()
            require(max_date <= latest_price_date, f"future leakage detected in {path.name}: {max_date}")
        for column in ["leakage_warning"]:
            if column in frame:
                warnings = frame[column].dropna().astype(str).str.upper()
                bad = warnings.str.contains("FUTURE_LEAKAGE_DETECTED").any() and not warnings.str.startswith("NO_FUTURE_LEAKAGE_DETECTED").all()
                require(not bad, f"future leakage warning detected in {path.name}")


def main() -> None:
    validate_files()
    summary = load_json(SUMMARY)
    require(summary.get("stage") == STAGE, "summary stage mismatch")
    validate_outputs(summary)
    validate_v128_preserved()
    validate_no_future_leakage(summary)
    print("V21.129 validation PASS")
    print(f"summary_path={SUMMARY.relative_to(ROOT).as_posix()}")
    print(f"D_gate_data_freshness={summary.get('D_gate_data_freshness')}")
    print(f"D_gate_data_quality_warning={summary.get('D_gate_data_quality_warning')}")
    print(f"D_gate_regime={summary.get('D_gate_regime')}")


if __name__ == "__main__":
    main()
