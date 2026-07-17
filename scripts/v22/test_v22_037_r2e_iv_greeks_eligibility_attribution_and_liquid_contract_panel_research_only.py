from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).with_name(
    "v22_037_r2e_iv_greeks_eligibility_attribution_and_liquid_contract_panel_research_only.py"
)
spec = importlib.util.spec_from_file_location("r2e", MODULE_PATH)
r2e = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = r2e
spec.loader.exec_module(r2e)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def base_recalc(code: str = "US.QQQ260710C723000", **overrides):
    row = {
        "source_row_number": "2",
        "contract_code": code,
        "underlying": "QQQ",
        "option_type": "CALL",
        "expiry_timestamp_et": "2026-07-10T16:00:00-04:00",
        "days_to_expiry": "0.22",
        "strike": "723",
        "underlying_price": "722.66",
        "moneyness_spot_over_strike": "0.9995",
        "log_moneyness": "-0.0005",
        "bid": "1.75",
        "ask": "1.77",
        "option_market_price": "1.76",
        "spread_absolute": "0.02",
        "spread_ratio_mid": "0.01136",
        "quote_alignment_seconds": "2",
        "timestamp_alignment_pass": "True",
        "valuation_timestamp_trust_pass": "True",
        "no_arbitrage_pass": "True",
        "iv_solver_converged": "True",
        "greeks_invariant_pass": "True",
        "quote_quality_pass": "True",
        "synthetic_iv": "0.25",
        "delta": "0.48",
        "gamma": "0.02",
        "theta_per_day": "-0.15",
        "vega_per_1vol_point": "0.03",
        "rho_per_1pct": "0.01",
        "quality_tier": "B",
        "eligible_for_research_ranking": "True",
    }
    row.update(overrides)
    return row


def capture(code: str = "US.QQQ260710C723000", **overrides):
    row = {
        "contract_code": code,
        "option_code": code,
        "underlying": "QQQ",
        "volume": "1000",
        "open_interest": "5000",
    }
    row.update(overrides)
    return row


def validation(code: str, check: str, passed: str = "False", severity: str = "WARN"):
    return {
        "source_row_number": "2",
        "contract_code": code,
        "underlying": "QQQ",
        "option_type": "CALL",
        "check_name": check,
        "expected": "True",
        "actual": "False",
        "passed": passed,
        "severity": severity,
        "notes": "",
    }


def test_bool_value():
    assert r2e.bool_value(True)
    assert r2e.bool_value("True")
    assert r2e.bool_value("1")
    assert not r2e.bool_value("False")


def test_safe_float():
    assert r2e.safe_float("1.25") == 1.25
    assert r2e.safe_float("10%") == 10.0
    assert r2e.safe_float("nan") is None


@pytest.mark.parametrize(
    "value,expected",
    [(-1, "EXPIRED"), (0.2, "0DTE"), (1, "1_7DTE"), (7, "1_7DTE"), (8, "8_30DTE"),
     (30, "8_30DTE"), (31, "31_45DTE"), (45, "31_45DTE"), (46, "GT45DTE"), (None, "UNKNOWN")],
)
def test_dte_bucket(value, expected):
    assert r2e.dte_bucket(value) == expected


def test_activity_status():
    assert r2e.activity_status(None, None) == "MISSING"
    assert r2e.activity_status(1, None) == "PARTIAL"
    assert r2e.activity_status(1, 10) == "AVAILABLE"


def test_activity_pass_or_logic():
    cfg = r2e.Config(min_volume=5, min_open_interest=20)
    assert r2e.activity_pass(5, 0, cfg)
    assert r2e.activity_pass(0, 20, cfg)
    assert not r2e.activity_pass(1, 2, cfg)


def test_validation_index_groups_failures():
    code = "US.QQQ260710C723000"
    idx = r2e.build_validation_index([
        validation(code, "spread_ratio_within_limit", severity="WARN"),
        validation(code, "iv_solver_converged", severity="ERROR"),
        validation(code, "ignored", passed="True", severity="ERROR"),
    ])
    assert idx[code]["WARN"] == ["spread_ratio_within_limit"]
    assert idx[code]["ERROR"] == ["iv_solver_converged"]


def test_panel_policy_passes_good_row():
    assert r2e.panel_policy_reasons(base_recalc(), r2e.Config()) == []


def test_panel_policy_rejects_non_base_eligible_only_once():
    row = base_recalc(eligible_for_research_ranking="False")
    assert r2e.panel_policy_reasons(row, r2e.Config()) == ["BASE_NOT_RESEARCH_ELIGIBLE"]


def test_panel_policy_rejects_micro_premium_and_wide_spread():
    row = base_recalc(bid="0.02", ask="0.03", option_market_price="0.025", spread_absolute="0.01", spread_ratio_mid="0.4", delta="0.05")
    reasons = r2e.panel_policy_reasons(row, r2e.Config())
    assert "BID_BELOW_MINIMUM" in reasons
    assert "OPTION_PRICE_BELOW_MINIMUM" in reasons
    assert "SPREAD_RATIO_ABOVE_LIMIT" in reasons
    assert "ABS_DELTA_OUTSIDE_POLICY" in reasons


def test_panel_policy_require_activity():
    row = base_recalc(volume=None, open_interest=None)
    cfg = r2e.Config(require_activity=True)
    assert "VOLUME_OPEN_INTEREST_BELOW_POLICY" in r2e.panel_policy_reasons(row, cfg)


def test_score_higher_for_better_liquidity():
    cfg = r2e.Config()
    good = base_recalc(volume="1000", open_interest="5000", spread_ratio_mid="0.01", quote_alignment_seconds="1", delta="0.5")
    bad = base_recalc(volume="0", open_interest="0", spread_ratio_mid="0.14", quote_alignment_seconds="14", delta="0.2")
    assert r2e.score_row(good, cfg) > r2e.score_row(bad, cfg)


def test_enrich_rows_merges_capture_and_attribution(tmp_path):
    code = "US.QQQ260710C723000"
    rows = r2e.enrich_rows(
        [capture(code)],
        [base_recalc(code)],
        [validation(code, "risk_free_rate_source_available", severity="WARN")],
        tmp_path,
        r2e.Config(),
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["volume"] == 1000.0
    assert row["base_validation_warn_count"] == 1
    assert row["liquid_panel_eligible"] is True
    assert row["panel_rank_underlying"] == 1


def test_enrich_rows_ranking_by_score(tmp_path):
    rows = r2e.enrich_rows(
        [capture("A", volume="1", open_interest="1"), capture("B", volume="1000", open_interest="5000")],
        [base_recalc("A", spread_ratio_mid="0.10"), base_recalc("B", spread_ratio_mid="0.01")],
        [],
        tmp_path,
        r2e.Config(),
    )
    ranks = {row["contract_code"]: row["panel_rank_underlying"] for row in rows}
    assert ranks["B"] == 1
    assert ranks["A"] == 2


def test_summarize_groups_counts():
    rows = [
        {**base_recalc("A"), "dte_bucket": "0DTE", "liquid_panel_eligible": True, "base_failure_reasons": "", "panel_exclusion_reasons": ""},
        {**base_recalc("B", eligible_for_research_ranking="False", timestamp_alignment_pass="False"), "dte_bucket": "1_7DTE", "liquid_panel_eligible": False, "base_failure_reasons": "iv_solver_converged", "panel_exclusion_reasons": "BASE_NOT_RESEARCH_ELIGIBLE"},
    ]
    summary = r2e.summarize_groups(rows)
    qqq = next(row for row in summary if row["group_type"] == "UNDERLYING" and row["group_value"] == "QQQ")
    assert qqq["input_row_count"] == 2
    assert qqq["base_research_eligible_count"] == 1
    assert qqq["liquid_panel_count"] == 1
    assert qqq["zero_dte_base_eligible_count"] == 1


def test_failure_summary():
    rows = [{**base_recalc("A"), "panel_exclusion_reasons": "SPREAD_RATIO_ABOVE_LIMIT"}]
    output = r2e.failure_summary(rows, [validation("A", "spread_ratio_within_limit", severity="WARN")])
    reasons = {(row["stage"], row["reason"]): row["affected_row_count"] for row in output}
    assert reasons[("BASE_VALIDATION", "spread_ratio_within_limit")] == 1
    assert reasons[("LIQUID_PANEL_POLICY", "SPREAD_RATIO_ABOVE_LIMIT")] == 1


def test_topn_panel_limits_per_underlying():
    rows = []
    for i in range(3):
        rows.append({**base_recalc(str(i)), "underlying": "QQQ", "liquid_panel_eligible": True, "panel_rank_underlying": i + 1})
    top = r2e.topn_panel(rows, 2)
    assert len(top) == 2


def test_discover_explicit_run(tmp_path):
    assert r2e.discover_r2d_run(tmp_path, tmp_path) == tmp_path.resolve()


def test_discover_latest_pointer(tmp_path):
    root = tmp_path / "outputs" / "v22" / "V22.037_R2D_MULTI_UNDERLYING_RATE_LIMITED_SAME_SNAPSHOT_CAPTURE_AND_IV_GREEKS_VALIDATION_RESEARCH_ONLY"
    run = root / "runs" / "v22_037_r2d_x"
    run.mkdir(parents=True)
    (root / "latest_run.json").write_text(json.dumps({"output_dir": str(run)}), encoding="utf-8")
    assert r2e.discover_r2d_run(tmp_path) == run.resolve()


def test_required_paths():
    paths = r2e.required_paths(Path("X"))
    assert paths["capture"].name == "option_underlying_same_snapshot_capture_research_only.csv"
    assert paths["recalculated"].name == "option_iv_greeks_recalculated_research_only.csv"


def test_execute_end_to_end_pass(tmp_path):
    repo = tmp_path / "repo"
    run = tmp_path / "run"
    output = tmp_path / "out"
    paths = r2e.required_paths(run)
    write_csv(paths["capture"], [capture()])
    write_csv(paths["recalculated"], [base_recalc()])
    write_csv(paths["validation"], [validation("US.QQQ260710C723000", "risk_free_rate_source_available", severity="WARN")])
    summary = r2e.execute(repo, output, run, r2e.Config())
    assert summary["final_status"] == r2e.PASS_STATUS
    assert summary["base_research_eligible_count"] == 1
    assert summary["liquid_panel_count"] == 1
    assert (output / "option_iv_greeks_eligibility_attribution.csv").exists()
    assert (output / "option_iv_greeks_liquid_contract_panel_research_only.csv").exists()


def test_execute_warn_when_policy_empty(tmp_path):
    repo = tmp_path / "repo"
    run = tmp_path / "run"
    output = tmp_path / "out"
    paths = r2e.required_paths(run)
    write_csv(paths["capture"], [capture()])
    write_csv(paths["recalculated"], [base_recalc(option_market_price="0.02", bid="0.01", ask="0.03", spread_ratio_mid="1.0")])
    write_csv(paths["validation"], [])
    summary = r2e.execute(repo, output, run, r2e.Config())
    assert summary["final_status"] == r2e.WARN_STATUS
    assert summary["base_research_eligible_count"] == 1
    assert summary["liquid_panel_count"] == 0


def test_execute_fail_when_no_base_eligible(tmp_path):
    repo = tmp_path / "repo"
    run = tmp_path / "run"
    output = tmp_path / "out"
    paths = r2e.required_paths(run)
    write_csv(paths["capture"], [capture()])
    write_csv(paths["recalculated"], [base_recalc(eligible_for_research_ranking="False")])
    write_csv(paths["validation"], [])
    summary = r2e.execute(repo, output, run, r2e.Config())
    assert summary["final_status"] == r2e.FAIL_NO_BASE_ELIGIBLE


def test_execute_fail_missing_inputs(tmp_path):
    summary = r2e.execute(tmp_path, tmp_path / "out", tmp_path / "run", r2e.Config())
    assert summary["final_status"] == r2e.FAIL_INPUT


def test_policy_payload_governance():
    payload = r2e.policy_payload(r2e.Config())
    assert payload["official_adoption_allowed"] is False
    assert payload["broker_action_allowed"] is False


def test_report_contains_governance():
    text = r2e.report_text({"final_status": "X", "final_decision": "Y"})
    assert "Broker action allowed: False" in text
    assert "Research only: True" in text
