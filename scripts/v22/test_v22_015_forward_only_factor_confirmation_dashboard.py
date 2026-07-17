from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_015_forward_only_factor_confirmation_dashboard.py")
SPEC = importlib.util.spec_from_file_location("v22_015", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "v22_forward_only_factor_confirmation_dashboard.csv",
    "v22_forward_confirmation_by_horizon.csv",
    "v22_forward_confirmation_blocker_audit.csv",
    "v22_forward_confirmation_group_summary.csv",
    "v22_forward_confirmation_source_audit.csv",
    "v22_forward_only_factor_confirmation_summary.json",
    "v22_forward_only_factor_confirmation_risk_gate.json",
    "V22.015_forward_only_factor_confirmation_dashboard_report.txt",
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
    registry_fields = [
        "item_id",
        "item_name",
        "item_type",
        "family",
        "evidence_level_label",
        "forward_maturity_status",
        "coverage_status",
        "redundancy_risk",
        "official_adoption_allowed",
        "broker_action_allowed",
        "trade_allowed",
        "research_only",
    ]
    write_csv(
        repo / module.REGISTRY_INPUT,
        registry_fields,
        [
            {
                "item_id": item_id,
                "item_name": item_id,
                "item_type": item_type,
                "family": family,
                "evidence_level_label": "LEVEL_1_HISTORICAL_CORRELATION" if item_id == "A1_CONTROL" else "LEVEL_2_PIT_LITE_BACKTEST",
                "forward_maturity_status": "PARTIAL_OR_PENDING",
                "coverage_status": "TEST",
                "redundancy_risk": "MEDIUM",
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
                "trade_allowed": False,
                "research_only": True,
            }
            for item_id, item_type, family in specs
        ],
    )
    write_csv(repo / module.COVERAGE_INPUT, ["item_id", "coverage_status"], [{"item_id": item_id, "coverage_status": "COVERAGE_READY"} for item_id in item_ids])
    write_csv(
        repo / module.PREDICTIVE_PANEL_INPUT,
        ["item_id", "item_name", "item_type", "predictive_validity_status", "computation_status"],
        [{"item_id": item_id, "item_name": item_id, "item_type": item_type, "predictive_validity_status": "MIXED_SIGNAL", "computation_status": "LOCAL_METRIC_COLUMNS_PRESENT"} for item_id, item_type, _family in specs],
    )
    write_csv(
        repo / module.PREDICTIVE_HORIZON_INPUT,
        ["item_id", "item_name", "horizon", "computation_status", "predictive_validity_status", "sample_count", "date_count", "source_path", "source_metric_name", "metric_quality"],
        [
            {
                "item_id": item_id,
                "item_name": item_id,
                "horizon": horizon,
                "computation_status": "LOCAL_METRIC_COLUMNS_PRESENT",
                "predictive_validity_status": "MIXED_SIGNAL",
                "sample_count": 5,
                "date_count": 1,
                "source_path": "test_forward_source.csv",
                "source_metric_name": "forward_proxy",
                "metric_quality": "LOCAL_SUMMARY_OR_HEADER_ONLY",
            }
            for item_id in item_ids
            for horizon in ["5D", "10D", "20D"]
        ],
    )
    write_csv(repo / module.REDUNDANCY_INPUT, ["item_id", "assigned_cluster", "redundancy_risk"], [{"item_id": item_id, "assigned_cluster": "TEST_CLUSTER", "redundancy_risk": "HIGH" if item_id in {"RSI", "KDJ"} else "MEDIUM"} for item_id in item_ids])
    write_csv(
        repo / module.FALSE_DISCOVERY_INPUT,
        ["item_id", "false_discovery_risk", "multiple_testing_adjustment_status", "source_summary_only_flag", "official_adoption_allowed", "broker_action_allowed", "trade_allowed"],
        [
            {
                "item_id": item_id,
                "false_discovery_risk": "PLACEHOLDER_ONLY" if item_type == "ETF_OPTION_PLACEHOLDER" else ("VERY_HIGH" if item_id in {"D_WEIGHT_OPTIMIZED_R1", "NEW_FACTOR_LITE", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"} else "MEDIUM"),
                "multiple_testing_adjustment_status": "PLACEHOLDER_ONLY" if item_type == "ETF_OPTION_PLACEHOLDER" else ("ADJUSTMENT_REQUIRED_HIGH_RISK" if item_id in {"D_WEIGHT_OPTIMIZED_R1", "NEW_FACTOR_LITE", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"} else "ADJUSTMENT_REQUIRED"),
                "source_summary_only_flag": False,
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
                "trade_allowed": False,
            }
            for item_id, item_type, _family in specs
        ],
    )
    optional = repo / "outputs" / "v21" / "V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1"
    write_csv(optional / "forward_panel.csv", ["item_id", "forward_window", "forward_return", "matured_observation_count"], [{"item_id": "RSI", "forward_window": "5D", "forward_return": 0.01, "matured_observation_count": 1}])
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
    summary = json.loads((repo / module.OUT_REL / "v22_forward_only_factor_confirmation_summary.json").read_text(encoding="utf-8"))
    assert summary["final_decision"] == "FORWARD_ONLY_FACTOR_CONFIRMATION_DASHBOARD_READY_RESEARCH_ONLY"
    assert summary["registry_input_exists"] is True
    assert summary["coverage_input_exists"] is True
    assert summary["predictive_panel_input_exists"] is True
    assert summary["predictive_horizon_input_exists"] is True
    assert summary["redundancy_input_exists"] is True
    assert summary["false_discovery_input_exists"] is True
    assert summary["evaluated_item_count"] == summary["registered_item_count"]


def test_required_items_and_statuses(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_forward_only_factor_confirmation_dashboard.csv")
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
    for item_id in ["ETF_OPTION_LONG_CALL", "ETF_OPTION_LONG_PUT"]:
        assert by_id[item_id]["forward_confirmation_status"] == "PLACEHOLDER_ONLY"
        assert by_id[item_id]["adoption_eligible_after_v22_015"] == "False"
    for item_id in ["D_WEIGHT_OPTIMIZED_R1", "NEW_FACTOR_LITE", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"]:
        assert by_id[item_id]["adoption_eligible_after_v22_015"] == "False"


def test_action_counts_and_gates_are_zero_or_false(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_forward_only_factor_confirmation_summary.json").read_text(encoding="utf-8"))
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


def test_module_writes_only_under_v22_015_output_dir(tmp_path):
    repo, payload = run_stage(tmp_path)
    expected = (repo / module.OUT_REL).resolve()
    allowed_seed_files = {
        (repo / module.REGISTRY_INPUT).resolve(),
        (repo / module.COVERAGE_INPUT).resolve(),
        (repo / module.PREDICTIVE_PANEL_INPUT).resolve(),
        (repo / module.PREDICTIVE_HORIZON_INPUT).resolve(),
        (repo / module.REDUNDANCY_INPUT).resolve(),
        (repo / module.FALSE_DISCOVERY_INPUT).resolve(),
        (repo / "outputs" / "v21" / "V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1" / "forward_panel.csv").resolve(),
    }
    assert Path(payload["output_dir"]).resolve() == expected
    assert expected.name == "V22.015_FORWARD_ONLY_FACTOR_CONFIRMATION_DASHBOARD"
    for path in repo.rglob("*"):
        if path.is_file() and path.resolve() not in allowed_seed_files:
            assert expected in path.resolve().parents


def test_no_factor_or_strategy_allows_official_adoption_broker_action_or_trade(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_forward_only_factor_confirmation_dashboard.csv")
    assert rows
    for row in rows:
        if row["item_type"] in {"FACTOR_FAMILY", "TECHNICAL_SUBFACTOR", "STRATEGY_RANKING_SYSTEM"}:
            assert row["official_adoption_allowed"] == "False"
            assert row["broker_action_allowed"] == "False"
            assert row["trade_allowed"] == "False"


def test_horizon_rows_and_false_discovery_blockers(tmp_path):
    repo, _ = run_stage(tmp_path)
    horizon_rows = read_rows(repo / module.OUT_REL / "v22_forward_confirmation_by_horizon.csv")
    horizons = {row["horizon"] for row in horizon_rows}
    assert {"5D", "10D", "20D"}.issubset(horizons)
    blocker_rows = read_rows(repo / module.OUT_REL / "v22_forward_confirmation_blocker_audit.csv")
    high_blockers = [row for row in blocker_rows if row["blocker_type"] == "FALSE_DISCOVERY_HIGH"]
    assert high_blockers
    assert {"D_WEIGHT_OPTIMIZED_R1", "NEW_FACTOR_LITE", "NEW_FACTOR_LITE_REPEATED_LOSER_LEFT_TAIL"} & {row["item_id"] for row in high_blockers}
