from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_014_multiple_testing_false_discovery_audit.py")
SPEC = importlib.util.spec_from_file_location("v22_014", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "v22_multiple_testing_false_discovery_audit.csv",
    "v22_false_discovery_group_summary.csv",
    "v22_research_variant_count_audit.csv",
    "v22_false_discovery_source_audit.csv",
    "v22_multiple_testing_false_discovery_summary.json",
    "v22_multiple_testing_false_discovery_risk_gate.json",
    "V22.014_multiple_testing_false_discovery_audit_report.txt",
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
        "current_status": "ACTIVE_RESEARCH",
        "forward_maturity_status": "PARTIAL_OR_PENDING",
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


def seed_inputs(repo: Path) -> list[str]:
    specs = [
        ("A1_CONTROL", "STRATEGY_RANKING_SYSTEM", "STRATEGY"),
        ("D_WEIGHT_OPTIMIZED_R1", "STRATEGY_RANKING_SYSTEM", "STRATEGY"),
        ("E_R3_QUALITY_RISK_REPAIR_BASE", "STRATEGY_RANKING_SYSTEM", "STRATEGY"),
        ("NEW_FACTOR_LITE", "STRATEGY_RANKING_SYSTEM", "STRATEGY"),
        ("NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL", "STRATEGY_RANKING_SYSTEM", "STRATEGY"),
        ("RSI", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        ("KDJ", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        ("MACD", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        ("MOMENTUM", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        ("RELATIVE_STRENGTH", "TECHNICAL_SUBFACTOR", "TECHNICAL"),
        ("DRAM_DAILY_PLAN", "DRAM_SYSTEM", "DRAM"),
        ("ETF_OPTION_LONG_CALL", "ETF_OPTION_PLACEHOLDER", "ETF_OPTIONS"),
        ("ETF_OPTION_LONG_PUT", "ETF_OPTION_PLACEHOLDER", "ETF_OPTIONS"),
    ]
    item_ids = [item_id for item_id, _item_type, _family in specs]
    write_csv(repo / module.REGISTRY_INPUT, REGISTRY_FIELDS, [registry_row(*spec) for spec in specs])
    write_csv(repo / module.COVERAGE_INPUT, ["item_id", "coverage_status"], [{"item_id": item_id, "coverage_status": "COVERAGE_READY"} for item_id in item_ids])
    write_csv(
        repo / module.PREDICTIVE_PANEL_INPUT,
        ["item_id", "item_name", "item_type", "predictive_validity_status", "computation_status", "official_adoption_allowed", "broker_action_allowed", "trade_allowed"],
        [
            {
                "item_id": item_id,
                "item_name": item_id,
                "item_type": item_type,
                "predictive_validity_status": "MIXED_SIGNAL",
                "computation_status": "LOCAL_METRIC_COLUMNS_PRESENT",
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
                "trade_allowed": False,
            }
            for item_id, item_type, _family in specs
        ],
    )
    write_csv(
        repo / module.PREDICTIVE_HORIZON_INPUT,
        ["item_id", "horizon", "computation_status"],
        [{"item_id": item_id, "horizon": horizon, "computation_status": "SOURCE_SUMMARY_ONLY"} for item_id in item_ids for horizon in ["1D", "5D", "20D"]],
    )
    write_csv(
        repo / module.REDUNDANCY_CLUSTER_INPUT,
        ["item_id", "assigned_cluster", "redundancy_risk"],
        [
            {
                "item_id": item_id,
                "assigned_cluster": "ETF_OPTION_PLACEHOLDER_CLUSTER" if item_type == "ETF_OPTION_PLACEHOLDER" else "STRATEGY_COMPOSITE_CLUSTER",
                "redundancy_risk": "PLACEHOLDER_ONLY" if item_type == "ETF_OPTION_PLACEHOLDER" else ("HIGH" if item_id in {"RSI", "KDJ", "MACD", "MOMENTUM", "RELATIVE_STRENGTH"} else "MEDIUM"),
            }
            for item_id, item_type, _family in specs
        ],
    )
    write_csv(repo / module.REDUNDANCY_PAIRWISE_INPUT, ["item_id_a", "item_id_b", "pairwise_overlap_risk"], [{"item_id_a": "RSI", "item_id_b": "KDJ", "pairwise_overlap_risk": "HIGH"}])
    optional = repo / "outputs" / "v21" / "V21.255_DETAILED_STRATEGY_BACKTEST_FACTOR_WEIGHT_COMPARISON"
    write_csv(
        optional / "strategy_factor_weight_effectiveness_matrix.csv",
        ["strategy", "factor_name", "factor_weight", "trial_count", "forward_window", "period", "topn_scope"],
        [{"strategy": "D_WEIGHT_OPTIMIZED_R1", "factor_name": "momentum", "factor_weight": 0.2, "trial_count": 12, "forward_window": "20D", "period": "post", "topn_scope": 20}],
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
    summary = json.loads((repo / module.OUT_REL / "v22_multiple_testing_false_discovery_summary.json").read_text(encoding="utf-8"))
    assert summary["final_decision"] == "MULTIPLE_TESTING_FALSE_DISCOVERY_AUDIT_READY_RESEARCH_ONLY"
    assert summary["registry_input_exists"] is True
    assert summary["coverage_input_exists"] is True
    assert summary["predictive_panel_input_exists"] is True
    assert summary["predictive_horizon_input_exists"] is True
    assert summary["redundancy_cluster_input_exists"] is True
    assert summary["redundancy_pairwise_input_exists"] is True
    assert summary["audited_item_count"] == summary["registered_item_count"]


def test_required_items_and_false_discovery_treatments(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_multiple_testing_false_discovery_audit.csv")
    by_id = {row["item_id"]: row for row in rows}
    for item_id in [
        "A1_CONTROL",
        "D_WEIGHT_OPTIMIZED_R1",
        "E_R3_QUALITY_RISK_REPAIR_BASE",
        "NEW_FACTOR_LITE",
        "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL",
        "RSI",
        "KDJ",
        "MACD",
        "MOMENTUM",
        "RELATIVE_STRENGTH",
        "DRAM_DAILY_PLAN",
        "ETF_OPTION_LONG_CALL",
        "ETF_OPTION_LONG_PUT",
    ]:
        assert item_id in by_id
    assert by_id["A1_CONTROL"]["false_discovery_risk"] == "LOW"
    assert by_id["A1_CONTROL"]["multiple_testing_adjustment_status"] == "ADJUSTMENT_NOT_NEEDED_CONTROL_OR_BASELINE"
    assert by_id["D_WEIGHT_OPTIMIZED_R1"]["false_discovery_risk"] in {"HIGH", "VERY_HIGH"} or by_id["D_WEIGHT_OPTIMIZED_R1"]["multiple_testing_adjustment_status"] == "ADJUSTMENT_REQUIRED_HIGH_RISK"
    for item_id in ["NEW_FACTOR_LITE", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"]:
        assert by_id[item_id]["false_discovery_risk"] in {"HIGH", "VERY_HIGH"}
    for item_id in ["ETF_OPTION_LONG_CALL", "ETF_OPTION_LONG_PUT"]:
        assert by_id[item_id]["false_discovery_risk"] == "PLACEHOLDER_ONLY"
        assert by_id[item_id]["adoption_eligible_after_v22_014"] == "False"


def test_action_counts_and_gates_are_zero_or_false(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_multiple_testing_false_discovery_summary.json").read_text(encoding="utf-8"))
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


def test_module_writes_only_under_v22_014_output_dir(tmp_path):
    repo, payload = run_stage(tmp_path)
    expected = (repo / module.OUT_REL).resolve()
    allowed_seed_files = {
        (repo / module.REGISTRY_INPUT).resolve(),
        (repo / module.COVERAGE_INPUT).resolve(),
        (repo / module.PREDICTIVE_PANEL_INPUT).resolve(),
        (repo / module.PREDICTIVE_HORIZON_INPUT).resolve(),
        (repo / module.REDUNDANCY_CLUSTER_INPUT).resolve(),
        (repo / module.REDUNDANCY_PAIRWISE_INPUT).resolve(),
        (repo / "outputs" / "v21" / "V21.255_DETAILED_STRATEGY_BACKTEST_FACTOR_WEIGHT_COMPARISON" / "strategy_factor_weight_effectiveness_matrix.csv").resolve(),
    }
    assert Path(payload["output_dir"]).resolve() == expected
    assert expected.name == "V22.014_MULTIPLE_TESTING_FALSE_DISCOVERY_AUDIT"
    for path in repo.rglob("*"):
        if path.is_file() and path.resolve() not in allowed_seed_files:
            assert expected in path.resolve().parents


def test_no_factor_or_strategy_allows_official_adoption_broker_action_or_trade(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_multiple_testing_false_discovery_audit.csv")
    assert rows
    for row in rows:
        if row["item_type"] in {"FACTOR_FAMILY", "TECHNICAL_SUBFACTOR", "STRATEGY_RANKING_SYSTEM"}:
            assert row["official_adoption_allowed"] == "False"
            assert row["broker_action_allowed"] == "False"
            assert row["trade_allowed"] == "False"
