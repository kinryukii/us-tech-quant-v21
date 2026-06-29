import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.172_TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH"
REQ = [
    "approved_target_tickers.csv",
    "pre_refresh_price_panel_snapshot_hash.csv",
    "targeted_refresh_attempt_log.csv",
    "targeted_refresh_result_by_ticker.csv",
    "post_refresh_price_panel_freshness.csv",
    "price_panel_mutation_audit.csv",
    "protected_output_mutation_audit.csv",
    "refresh_data_quality_delta.csv",
    "refresh_non_active_impact_confirmation.csv",
    "V21.172_TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH_report.txt",
    "V21.172_TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH_summary.json",
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "V21.172_TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH_summary.json").read_text(encoding="utf-8"))


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


def test_approved_target_list_only_expected():
    df = read("approved_target_tickers.csv")
    assert set(df["ticker"]) == {"BITF", "PSTG", "SATS", "TQQQ"}


def test_no_non_approved_ticker_refreshed_unless_broad_allowed():
    attempts = read("targeted_refresh_attempt_log.csv")
    assert set(attempts["ticker"]).issubset({"BITF", "PSTG", "SATS", "TQQQ"})
    audit = read("price_panel_mutation_audit.csv")
    assert str(audit["broad_refresh_allowed"].iloc[0]).lower() == "false"


def test_protected_and_action_flags_clean():
    s = summary()
    assert s["protected_outputs_modified"] is False
    assert s["broker_action_allowed"] is False
    assert s["live_trading_allowed"] is False
    assert s["official_adoption_allowed"] is False
    audit = read("protected_output_mutation_audit.csv")
    assert str(audit["audit_clean"].iloc[0]).lower() == "true"
    assert int(audit["broker_action_file_mutation_count"].iloc[0]) == 0
    assert int(audit["official_output_mutation_count"].iloc[0]) == 0
    assert int(audit["historical_ledger_mutation_count"].iloc[0]) == 0


def test_if_canonical_mutated_hashes_exist():
    s = summary()
    snap = read("pre_refresh_price_panel_snapshot_hash.csv")
    mut = read("price_panel_mutation_audit.csv")
    if s["canonical_price_panel_mutated"] is True:
        assert str(snap["pre_refresh_sha256"].iloc[0])
        assert str(mut["post_refresh_sha256"].iloc[0])


def test_output_directory_is_isolated():
    assert OUT.as_posix().endswith("outputs/v21/V21.172_TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH")
    for path in OUT.iterdir():
        assert path.is_file()
        assert path.parent == OUT


def test_no_official_or_protected_outputs_modified():
    s = summary()
    audit = read("protected_output_mutation_audit.csv")
    assert s["protected_outputs_modified"] is False
    assert int(audit["changed_protected_file_count"].iloc[0]) == 0
