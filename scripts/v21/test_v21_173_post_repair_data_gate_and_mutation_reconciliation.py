import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.173_POST_REPAIR_DATA_GATE_AND_MUTATION_RECONCILIATION"
REQ = [
    "post_repair_target_ticker_status.csv",
    "post_repair_data_gate_reclassification.csv",
    "v21_172_mutation_reconciliation.csv",
    "cumulative_stage_mutation_audit.csv",
    "unresolved_price_issue_register.csv",
    "non_blocking_unresolved_price_issues.csv",
    "active_holding_and_maturity_dependency_recheck.csv",
    "post_repair_protected_output_mutation_audit.csv",
    "post_repair_guardrail_status.csv",
    "V21.173_POST_REPAIR_DATA_GATE_AND_MUTATION_RECONCILIATION_report.txt",
    "V21.173_POST_REPAIR_DATA_GATE_AND_MUTATION_RECONCILIATION_summary.json",
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "V21.173_POST_REPAIR_DATA_GATE_AND_MUTATION_RECONCILIATION_summary.json").read_text(encoding="utf-8"))


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


def test_no_new_refresh_performed_and_targets_exist():
    s = summary()
    assert s["no_new_refresh_performed"] is True
    df = read("post_repair_target_ticker_status.csv")
    assert {"BITF", "PSTG", "SATS", "TQQQ"}.issubset(set(df["ticker"]))


def test_mutation_reconciliation_exists_and_distinguishes_final_vs_cumulative():
    df = read("v21_172_mutation_reconciliation.csv")
    assert len(df) == 1
    assert "final_wrapper_canonical_mutated" in df.columns
    assert "cumulative_v21_172_canonical_mutated" in df.columns
    s = summary()
    assert s["final_wrapper_canonical_price_panel_mutated"] in {True, False}
    assert s["cumulative_v21_172_canonical_price_panel_mutated"] in {True, False}


def test_if_sats_tqqq_improved_cumulative_mutation_true():
    status = read("post_repair_target_ticker_status.csv")
    improved = set(status[(status["ticker"].isin(["SATS", "TQQQ"])) & (status["pre_v21_172_status"].ne("FRESH")) & (status["post_v21_172_status"].eq("FRESH"))]["ticker"])
    if improved:
        assert summary()["cumulative_v21_172_canonical_price_panel_mutated"] is True


def test_protected_broker_official_ledger_clean():
    s = summary()
    assert s["protected_output_mutation_audit_clean"] is True
    assert s["broker_action_file_mutation_count"] == 0
    assert s["official_output_mutation_count"] == 0
    assert s["historical_ledger_mutation_count"] == 0


def test_unresolved_bitf_pstg_non_blocking_if_no_active_dependency():
    df = read("post_repair_target_ticker_status.csv")
    sub = df[df["ticker"].isin(["BITF", "PSTG"])]
    for row in sub.to_dict("records"):
        if row["unresolved_issue"] and not row["active_holding_impact"] and not row["maturity_dependency_impact"]:
            assert row["current_blocking_impact"] is False or str(row["current_blocking_impact"]).lower() == "false"
            assert row["post_repair_impact_class"] == "POST_REPAIR_UNRESOLVED_NON_BLOCKING_ISSUES_REMAIN"


def test_output_directory_is_isolated():
    assert OUT.as_posix().endswith("outputs/v21/V21.173_POST_REPAIR_DATA_GATE_AND_MUTATION_RECONCILIATION")
    for path in OUT.iterdir():
        assert path.is_file()
        assert path.parent == OUT


def test_no_official_or_protected_outputs_modified():
    s = summary()
    audit = read("post_repair_protected_output_mutation_audit.csv")
    assert s["protected_outputs_modified"] is False
    assert int(audit["changed_protected_file_count_during_v21_173"].iloc[0]) == 0
