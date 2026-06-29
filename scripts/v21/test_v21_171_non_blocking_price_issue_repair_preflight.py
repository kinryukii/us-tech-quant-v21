import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.171_NON_BLOCKING_PRICE_ISSUE_REPAIR_PREFLIGHT"
REQ = [
    "price_issue_repair_preflight_summary.csv",
    "target_ticker_price_issue_detail.csv",
    "target_ticker_active_holding_impact.csv",
    "target_ticker_universe_membership_check.csv",
    "target_ticker_refresh_safety_check.csv",
    "target_ticker_repair_recommendation.csv",
    "canonical_price_panel_mutation_risk.csv",
    "protected_output_mutation_audit.csv",
    "V21.171_NON_BLOCKING_PRICE_ISSUE_REPAIR_PREFLIGHT_report.txt",
    "V21.171_NON_BLOCKING_PRICE_ISSUE_REPAIR_PREFLIGHT_summary.json",
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "V21.171_NON_BLOCKING_PRICE_ISSUE_REPAIR_PREFLIGHT_summary.json").read_text(encoding="utf-8"))


def test_required_outputs_and_summary_exist():
    assert OUT.exists()
    for name in REQ:
        assert (OUT / name).exists(), name
    assert "final_status" in summary()


def test_policy_flags_remain_enforced():
    s = summary()
    assert s["research_only"] is True
    assert s["official_adoption_allowed"] is False
    assert s["broker_action_allowed"] is False
    assert s["live_trading_allowed"] is False
    assert s["protected_outputs_modified"] is False
    assert s["role_review_required"] is False


def test_target_ticker_detail_includes_all_targets():
    df = read("target_ticker_price_issue_detail.csv")
    assert {"BITF", "PSTG", "SATS", "TQQQ"}.issubset(set(df["ticker"]))


def test_no_canonical_price_refresh_performed():
    s = summary()
    risk = read("canonical_price_panel_mutation_risk.csv")
    assert s["preflight_performed_refresh"] is False
    assert str(risk["preflight_mutated_canonical_price_panel"].iloc[0]).lower() == "false"


def test_protected_audit_clean():
    audit = read("protected_output_mutation_audit.csv")
    assert len(audit) == 1
    assert int(audit["changed_protected_file_count"].iloc[0]) == 0
    assert str(audit["audit_clean"].iloc[0]).lower() == "true"


def test_no_broker_live_official_flags_true():
    s = summary()
    assert s["broker_action_allowed"] is False
    assert s["live_trading_allowed"] is False
    assert s["official_adoption_allowed"] is False
    rec = read("target_ticker_repair_recommendation.csv")
    for col in ["broker_action_allowed", "live_trading_allowed", "official_adoption_allowed"]:
        assert not rec[col].astype(str).str.lower().eq("true").any()


def test_output_directory_is_isolated():
    assert OUT.as_posix().endswith("outputs/v21/V21.171_NON_BLOCKING_PRICE_ISSUE_REPAIR_PREFLIGHT")
    for path in OUT.iterdir():
        assert path.is_file()
        assert path.parent == OUT


def test_no_official_or_protected_outputs_modified():
    s = summary()
    audit = read("protected_output_mutation_audit.csv")
    assert s["protected_outputs_modified"] is False
    assert int(audit["changed_protected_file_count"].iloc[0]) == 0
