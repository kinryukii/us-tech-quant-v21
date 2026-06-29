import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "v21" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD"
REQ = [
    "data_freshness_summary.csv",
    "price_panel_freshness_by_ticker.csv",
    "proxy_coverage_summary.csv",
    "proxy_coverage_by_ticker.csv",
    "neutral_fallback_cells.csv",
    "stale_or_missing_tickers.csv",
    "strategy_input_coverage_by_module.csv",
    "data_quality_impact_classification.csv",
    "protected_output_mutation_audit.csv",
    "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD_report.txt",
    "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD_summary.json",
]


def read(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name)


def summary() -> dict:
    return json.loads((OUT / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD_summary.json").read_text(encoding="utf-8"))


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


def test_data_freshness_summary_has_rows():
    df = read("data_freshness_summary.csv")
    assert len(df) > 0
    assert {"metric", "value", "status"}.issubset(df.columns)


def test_proxy_coverage_summary_has_rows():
    df = read("proxy_coverage_summary.csv")
    assert len(df) > 0
    assert {"proxy_name", "coverage"}.issubset(df.columns)


def test_strategy_input_coverage_file_exists_and_has_modules():
    df = read("strategy_input_coverage_by_module.csv")
    assert len(df) > 0
    assert {"A1", "C-R2", "AI Bottleneck", "switch controller", "switch ledger"}.issubset(set(df["module"]))


def test_data_quality_impact_classification_exists():
    df = read("data_quality_impact_classification.csv")
    assert len(df) > 0
    assert "impact_level" in df.columns


def test_protected_output_mutation_audit_exists_and_clean():
    df = read("protected_output_mutation_audit.csv")
    assert len(df) > 0
    assert int(df["changed_protected_file_count"].iloc[0]) == 0
    assert str(df["protected_outputs_modified"].iloc[0]).lower() == "false"


def test_output_directory_is_isolated():
    assert OUT.as_posix().endswith("outputs/v21/V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD")
    for path in OUT.iterdir():
        assert path.is_file()
        assert path.parent == OUT


def test_no_official_or_protected_output_files_modified():
    s = summary()
    audit = read("protected_output_mutation_audit.csv")
    assert s["protected_outputs_modified"] is False
    assert int(audit["changed_protected_file_count"].iloc[0]) == 0
