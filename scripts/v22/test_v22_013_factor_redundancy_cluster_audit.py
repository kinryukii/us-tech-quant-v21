from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_013_factor_redundancy_cluster_audit.py")
SPEC = importlib.util.spec_from_file_location("v22_013", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "v22_factor_redundancy_cluster_audit.csv",
    "v22_factor_redundancy_pairwise_audit.csv",
    "v22_factor_cluster_summary.csv",
    "v22_factor_unique_signal_candidate_summary.csv",
    "v22_factor_redundancy_source_audit.csv",
    "v22_factor_redundancy_cluster_summary.json",
    "v22_factor_redundancy_cluster_risk_gate.json",
    "V22.013_factor_redundancy_cluster_audit_report.txt",
]

REGISTRY_FIELDS = [
    "item_id",
    "item_name",
    "item_type",
    "family",
    "current_evidence_level",
    "evidence_level_label",
    "evidence_source_modules",
    "current_status",
    "forward_maturity_status",
    "regime_robustness_status",
    "coverage_status",
    "multiple_testing_risk",
    "redundancy_risk",
    "adoption_eligible",
    "official_adoption_allowed",
    "broker_action_allowed",
    "trade_allowed",
    "research_only",
    "next_required_validation",
    "reason",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def registry_row(item_id: str, item_type: str, family: str) -> dict[str, object]:
    return {
        "item_id": item_id,
        "item_name": item_id,
        "item_type": item_type,
        "family": family,
        "current_evidence_level": 2,
        "evidence_level_label": "LEVEL_2_PIT_LITE_BACKTEST",
        "evidence_source_modules": "TEST",
        "current_status": "TEST",
        "forward_maturity_status": "PENDING",
        "regime_robustness_status": "NOT_CONFIRMED",
        "coverage_status": "TEST",
        "multiple_testing_risk": "MEDIUM",
        "redundancy_risk": "MEDIUM",
        "adoption_eligible": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "trade_allowed": False,
        "research_only": True,
        "next_required_validation": "TEST_NEXT",
        "reason": "seed row",
    }


def panel_row(item_id: str, item_type: str, status: str = "SOURCE_SUMMARY_ONLY") -> dict[str, object]:
    return {
        "item_id": item_id,
        "item_name": item_id,
        "item_type": item_type,
        "predictive_validity_status": status,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "trade_allowed": False,
    }


def seed_inputs(repo: Path) -> list[str]:
    specs = [
        ("RSI", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        ("KDJ", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        ("MACD", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        ("BOLLINGER_BAND_7_LINE", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        ("MOMENTUM", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        ("RELATIVE_STRENGTH", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        ("BREAKOUT", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        ("MA20", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        ("MA50", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        ("EMA", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        ("E_R3_QUALITY_RISK_REPAIR_BASE", "STRATEGY_RANKING_SYSTEM", "STRATEGY"),
        ("NEW_FACTOR_LITE", "STRATEGY_RANKING_SYSTEM", "STRATEGY"),
        ("DRAM_DAILY_PLAN", "DRAM_SYSTEM", "DRAM"),
        ("ETF_OPTION_LONG_CALL", "ETF_OPTION_PLACEHOLDER", "ETF_OPTIONS"),
        ("ETF_OPTION_LONG_PUT", "ETF_OPTION_PLACEHOLDER", "ETF_OPTIONS"),
    ]
    item_ids = [item_id for item_id, _item_type, _family in specs]
    write_csv(repo / module.REGISTRY_INPUT, REGISTRY_FIELDS, [registry_row(*spec) for spec in specs])
    write_csv(repo / module.COVERAGE_INPUT, ["item_id", "coverage_status"], [{"item_id": item_id, "coverage_status": "COVERAGE_READY"} for item_id in item_ids])
    write_csv(
        repo / module.PREDICTIVE_PANEL_INPUT,
        ["item_id", "item_name", "item_type", "predictive_validity_status", "official_adoption_allowed", "broker_action_allowed", "trade_allowed"],
        [panel_row(item_id, item_type) for item_id, item_type, _family in specs],
    )
    write_csv(
        repo / module.PREDICTIVE_HORIZON_INPUT,
        ["item_id", "horizon", "computation_status"],
        [{"item_id": item_id, "horizon": "1D", "computation_status": "SOURCE_SUMMARY_ONLY"} for item_id in item_ids],
    )
    return item_ids


def run_stage(tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "repo"
    seed_inputs(repo)
    payload = module.run(repo)
    return repo, payload


def test_required_output_files_are_created(tmp_path):
    repo, _ = run_stage(tmp_path)
    for filename in REQUIRED_FILES:
        assert (repo / module.OUT_REL / filename).exists()


def test_summary_decision_inputs_and_counts(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_factor_redundancy_cluster_summary.json").read_text(encoding="utf-8"))
    assert summary["final_decision"] == "FACTOR_REDUNDANCY_CLUSTER_AUDIT_READY_RESEARCH_ONLY"
    assert summary["registry_input_exists"] is True
    assert summary["coverage_input_exists"] is True
    assert summary["predictive_panel_input_exists"] is True
    assert summary["predictive_horizon_input_exists"] is True
    assert summary["clustered_item_count"] == summary["registered_item_count"]


def test_required_items_and_clusters(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_factor_redundancy_cluster_audit.csv")
    by_id = {row["item_id"]: row for row in rows}
    for item_id in [
        "RSI",
        "KDJ",
        "MACD",
        "BOLLINGER_BAND_7_LINE",
        "MOMENTUM",
        "RELATIVE_STRENGTH",
        "BREAKOUT",
        "E_R3_QUALITY_RISK_REPAIR_BASE",
        "NEW_FACTOR_LITE",
        "DRAM_DAILY_PLAN",
        "ETF_OPTION_LONG_CALL",
        "ETF_OPTION_LONG_PUT",
    ]:
        assert item_id in by_id
    for item_id in ["RSI", "KDJ", "BOLLINGER_BAND_7_LINE"]:
        assert by_id[item_id]["assigned_cluster"] == "OSCILLATOR_MEAN_REVERSION_CLUSTER"
    for item_id in ["MOMENTUM", "RELATIVE_STRENGTH", "BREAKOUT", "MA20", "MA50", "EMA", "MACD"]:
        assert by_id[item_id]["assigned_cluster"] == "TREND_MOMENTUM_CLUSTER"
    for item_id in ["ETF_OPTION_LONG_CALL", "ETF_OPTION_LONG_PUT"]:
        assert by_id[item_id]["assigned_cluster"] == "ETF_OPTION_PLACEHOLDER_CLUSTER"
        assert by_id[item_id]["adoption_eligible_after_v22_013"] == "False"


def test_pairwise_contains_expected_overlap_pairs(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_factor_redundancy_pairwise_audit.csv")
    pairs = {tuple(sorted([row["item_id_a"], row["item_id_b"]])) for row in rows}
    assert tuple(sorted(["MOMENTUM", "RELATIVE_STRENGTH"])) in pairs
    assert tuple(sorted(["RSI", "KDJ"])) in pairs


def test_action_counts_and_gates_are_zero_or_false(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_factor_redundancy_cluster_summary.json").read_text(encoding="utf-8"))
    assert summary["official_adoption_allowed_count"] == 0
    assert summary["broker_action_allowed_count"] == 0
    assert summary["trade_allowed_count"] == 0
    for key in [
        "broker_action_allowed",
        "official_adoption_allowed",
        "trade_allowed",
        "moomoo_connection_allowed",
        "market_data_fetch_allowed",
        "option_chain_fetch_allowed",
        "daily_chain_execution_allowed",
        "factor_promotion_allowed",
        "factor_weight_change_allowed",
    ]:
        assert summary[key] is False


def test_module_has_no_broker_network_process_or_mutation_imports():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    banned_modules = {"moomoo", "futu", "yfinance", "requests", "urllib", "http", "socket", "subprocess", "shutil", "os"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(banned_modules)


def test_module_writes_only_under_v22_013_output_dir(tmp_path):
    repo, payload = run_stage(tmp_path)
    expected = (repo / module.OUT_REL).resolve()
    allowed_seed_files = {
        (repo / module.REGISTRY_INPUT).resolve(),
        (repo / module.COVERAGE_INPUT).resolve(),
        (repo / module.PREDICTIVE_PANEL_INPUT).resolve(),
        (repo / module.PREDICTIVE_HORIZON_INPUT).resolve(),
    }
    assert Path(payload["output_dir"]).resolve() == expected
    assert expected.name == "V22.013_FACTOR_REDUNDANCY_CLUSTER_AUDIT"
    for path in repo.rglob("*"):
        if path.is_file() and path.resolve() not in allowed_seed_files:
            assert expected in path.resolve().parents


def test_no_cluster_row_allows_official_adoption_broker_action_or_trade(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_factor_redundancy_cluster_audit.csv")
    assert rows
    for row in rows:
        assert row["official_adoption_allowed"] == "False"
        assert row["broker_action_allowed"] == "False"
        assert row["trade_allowed"] == "False"
