#!/usr/bin/env python
"""Tests for V20.211 weight repair objective contract and shadow rejection."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v20" / "v20_211_weight_repair_objective_contract_and_shadow_rejection.py"
WRAPPER = ROOT / "scripts" / "v20" / "run_v20_211_weight_repair_objective_contract_and_shadow_rejection.ps1"
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
IN_EFFECTIVENESS = CONSOLIDATION / "V20_109_FORWARD_WINDOW_TOPN_EFFECTIVENESS_MATRIX.csv"

OUTPUTS = [
    CONSOLIDATION / "V20_211_SHADOW_WEIGHT_REJECTION_DECISION.csv",
    CONSOLIDATION / "V20_211_WEIGHT_REPAIR_OBJECTIVE_CONTRACT.csv",
    CONSOLIDATION / "V20_211_FORWARD_WINDOW_GUARDRAIL_MATRIX.csv",
    CONSOLIDATION / "V20_211_DATA_TRUST_AND_RISK_ROLE_SEPARATION_CONTRACT.csv",
    CONSOLIDATION / "V20_211_ETF_ROTATION_LANE_SEPARATION_CONTRACT.csv",
    CONSOLIDATION / "V20_211_NEXT_STAGE_GATE.csv",
    READ_CENTER / "V20_211_WEIGHT_REPAIR_OBJECTIVE_CONTRACT_AND_SHADOW_REJECTION_REPORT.md",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_weight_files() -> list[Path]:
    roots = [ROOT / "outputs", ROOT / "configs", ROOT / "data"]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(
                path for path in root.rglob("*.csv")
                if "weight" in path.name.lower() and not path.name.startswith("V20_211_")
            )
    return sorted(files)


def top20_underperforms(window: str) -> bool:
    rows = read_csv(IN_EFFECTIVENESS)
    for row in rows:
        if row.get("forward_window") == window and row.get("top_n") == "20":
            return float(row["shadow_mean_forward_return"]) < float(row["baseline_mean_forward_return"])
    raise AssertionError(f"missing {window} Top20 row")


def test_v20_211_weight_repair_objective_contract_and_shadow_rejection() -> None:
    assert IN_EFFECTIVENESS.exists() and IN_EFFECTIVENESS.stat().st_size > 0
    input_hash = sha(IN_EFFECTIVENESS)
    weight_before = {path: sha(path) for path in protected_weight_files()}

    result = subprocess.run(["python", str(SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert "FINAL_STATUS=PASS_V20_211_WEIGHT_REPAIR_OBJECTIVE_CONTRACT_CREATED_CURRENT_SHADOW_REJECTED_BASELINE_RETAINED" in result.stdout
    assert "CURRENT_SHADOW_OFFICIAL_ELIGIBLE=FALSE" in result.stdout
    assert "BASELINE_RETAINED=TRUE" in result.stdout
    assert "OFFICIAL_PROMOTION_ALLOWED=FALSE" in result.stdout
    assert "OFFICIAL_RECOMMENDATION_CREATED=FALSE" in result.stdout
    assert "WEIGHT_MUTATED=FALSE" in result.stdout
    assert "TRADE_ACTION_CREATED=FALSE" in result.stdout
    assert "BROKER_EXECUTION_SUPPORTED=FALSE" in result.stdout

    assert input_hash == sha(IN_EFFECTIVENESS)
    assert weight_before == {path: sha(path) for path in protected_weight_files()}

    for path in OUTPUTS:
        assert path.exists() and path.stat().st_size > 0, f"missing output {path}"
        if path.suffix.lower() == ".csv":
            assert read_csv(path), f"output has no rows {path}"

    gate = read_csv(CONSOLIDATION / "V20_211_NEXT_STAGE_GATE.csv")[0]
    assert gate["current_shadow_official_eligible"] == "FALSE"
    assert gate["baseline_retained"] == "TRUE"
    assert gate["future_weight_repair_contract_created"] == "TRUE"
    assert gate["data_trust_role_separated"] == "TRUE"
    assert gate["risk_role_separated"] == "TRUE"
    assert gate["etf_rotation_lane_separated"] == "TRUE"
    assert gate["official_promotion_allowed"] == "FALSE"
    assert gate["official_recommendation_created"] == "FALSE"
    assert gate["weight_mutated"] == "FALSE"
    assert gate["trade_action_created"] == "FALSE"
    assert gate["broker_execution_supported"] == "FALSE"
    assert gate["recommended_next_stage"] == "V20.212_PORTFOLIO_EQUITY_CURVE_AND_DRAWDOWN_BACKTEST_CONTRACT"

    if top20_underperforms("60D") or top20_underperforms("120D"):
        assert gate["current_shadow_official_eligible"] == "FALSE"

    decision = read_csv(CONSOLIDATION / "V20_211_SHADOW_WEIGHT_REJECTION_DECISION.csv")[0]
    assert decision["decision"] == "REJECT_CURRENT_SHADOW_WEIGHT_FOR_OFFICIAL_USE_RETAIN_BASELINE"
    assert decision["baseline_retained"] == "TRUE"
    assert decision["official_weight_file_mutated"] == "FALSE"
    assert decision["official_recommendation_created"] == "FALSE"
    assert decision["trade_action_created"] == "FALSE"
    assert decision["broker_execution_supported"] == "FALSE"

    guardrails = read_csv(CONSOLIDATION / "V20_211_FORWARD_WINDOW_GUARDRAIL_MATRIX.csv")
    by_window = {row["forward_window"]: row for row in guardrails}
    assert set(["5D", "10D", "20D", "60D", "120D"]).issubset(by_window)
    assert by_window["20D"]["guardrail_pass"] == "FALSE"
    assert by_window["60D"]["guardrail_pass"] == "FALSE"
    assert by_window["120D"]["guardrail_pass"] == "FALSE"

    contract = read_csv(CONSOLIDATION / "V20_211_WEIGHT_REPAIR_OBJECTIVE_CONTRACT.csv")
    contract_text = "\n".join(row["rule_id"] + " " + row["rule_value"] for row in contract)
    assert "20D_TOP20_NON_UNDERPERFORMANCE 20D Top20 shadow_minus_baseline_mean_return >= 0" in contract_text
    assert "60D_TOP20_NON_UNDERPERFORMANCE 60D Top20 shadow_minus_baseline_mean_return >= 0" in contract_text
    assert "120D_TOP20_NON_UNDERPERFORMANCE 120D Top20 shadow_minus_baseline_mean_return >= 0" in contract_text
    assert "AUTO_REJECT_IF_60D_OR_120D_TOP20_UNDERPERFORMS_BASELINE TRUE" in contract_text

    role = read_csv(CONSOLIDATION / "V20_211_DATA_TRUST_AND_RISK_ROLE_SEPARATION_CONTRACT.csv")
    role_map = {row["role_key"]: row["role_value"] for row in role}
    assert role_map["DATA_TRUST_ALPHA_WEIGHT_RECOMMENDATION"] == "0"
    assert role_map["DATA_TRUST_ROLE"] == "GATE_WARNING_ELIGIBILITY_ONLY"
    assert role_map["RISK_ALPHA_WEIGHT_RECOMMENDATION"] == "DO_NOT_INCREASE_FOR_ALPHA_UNLESS_VALIDATED"
    assert role_map["RISK_ROLE"] == "GATE_CAP_WARNING_DOWNSIDE_CONTROL"

    etf = read_csv(CONSOLIDATION / "V20_211_ETF_ROTATION_LANE_SEPARATION_CONTRACT.csv")
    etf_status = next(row for row in etf if row["contract_key"] == "ETF_ROTATION_LANE_STATUS")
    assert etf_status["contract_value"] == "SEPARATE_REQUIRED"

    report_text = (READ_CENTER / "V20_211_WEIGHT_REPAIR_OBJECTIVE_CONTRACT_AND_SHADOW_REJECTION_REPORT.md").read_text(encoding="utf-8")
    assert "current shadow dynamic weight is rejected for official use" in report_text
    assert "Max drawdown is not available from the forward-window tables" in report_text
    assert "V20.212_PORTFOLIO_EQUITY_CURVE_AND_DRAWDOWN_BACKTEST_CONTRACT" in report_text


def test_wrapper_parseable() -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "FINAL_STATUS=PASS_V20_211_WEIGHT_REPAIR_OBJECTIVE_CONTRACT_CREATED_CURRENT_SHADOW_REJECTED_BASELINE_RETAINED" in result.stdout
    assert "CURRENT_SHADOW_OFFICIAL_ELIGIBLE=FALSE" in result.stdout
    assert "WEIGHT_MUTATED=FALSE" in result.stdout


if __name__ == "__main__":
    test_v20_211_weight_repair_objective_contract_and_shadow_rejection()
    test_wrapper_parseable()
    print("PASS test_v20_211_weight_repair_objective_contract_and_shadow_rejection")
