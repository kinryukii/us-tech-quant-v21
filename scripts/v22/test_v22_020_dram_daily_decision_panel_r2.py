from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_020_dram_daily_decision_panel_r2.py")
SPEC = importlib.util.spec_from_file_location("v22_020", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "v22_dram_daily_decision_panel.csv",
    "v22_dram_signal_to_action_panel.csv",
    "v22_dram_forward_maturity_panel.csv",
    "v22_dram_source_audit.csv",
    "v22_dram_risk_state.json",
    "v22_dram_daily_decision_panel_summary.json",
    "v22_dram_daily_decision_panel_risk_gate.json",
    "V22.020_dram_daily_decision_panel_r2_report.txt",
]

FORBIDDEN_LABELS = {
    "BUY_NOW",
    "SELL_NOW",
    "TRADE_ALLOWED",
    "BROKER_ACTION_ALLOWED",
    "AUTO_TRADE",
    "EXECUTE_ORDER",
}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def seed_inputs(repo: Path) -> None:
    dashboard_fields = [
        "item_id",
        "item_name",
        "item_type",
        "family",
        "forward_confirmation_status",
        "forward_5d_status",
        "forward_10d_status",
        "forward_20d_status",
        "matured_forward_observation_count_estimate",
        "supportive_forward_observation_count_estimate",
        "source_summary_only_flag",
        "placeholder_only_flag",
        "primary_blocker",
        "official_adoption_allowed",
        "broker_action_allowed",
        "trade_allowed",
        "next_required_validation",
        "reason",
    ]
    write_csv(
        repo / module.FORWARD_DASHBOARD_INPUT,
        dashboard_fields,
        [
            {
                "item_id": "DRAM_DAILY_PLAN",
                "item_name": "DRAM Daily Plan",
                "item_type": "DRAM_SYSTEM",
                "family": "DRAM",
                "forward_confirmation_status": "FORWARD_PENDING_MATURITY",
                "forward_5d_status": "FORWARD_PENDING_MATURITY",
                "forward_10d_status": "FORWARD_PENDING_MATURITY",
                "forward_20d_status": "FORWARD_PENDING_MATURITY",
                "matured_forward_observation_count_estimate": 3,
                "supportive_forward_observation_count_estimate": 0,
                "source_summary_only_flag": False,
                "placeholder_only_flag": False,
                "primary_blocker": "FALSE_DISCOVERY_HIGH",
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
                "trade_allowed": False,
                "next_required_validation": "TEST",
                "reason": "seed",
            },
            {
                "item_id": "DRAM_FORWARD_OUTCOME_TRACKING",
                "item_name": "DRAM Forward Outcome Tracking",
                "item_type": "DRAM_SYSTEM",
                "family": "DRAM",
                "forward_confirmation_status": "FORWARD_PENDING_MATURITY",
                "forward_5d_status": "FORWARD_PENDING_MATURITY",
                "forward_10d_status": "FORWARD_PENDING_MATURITY",
                "forward_20d_status": "FORWARD_PENDING_MATURITY",
                "matured_forward_observation_count_estimate": 3,
                "supportive_forward_observation_count_estimate": 0,
                "source_summary_only_flag": False,
                "placeholder_only_flag": False,
                "primary_blocker": "",
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
                "trade_allowed": False,
                "next_required_validation": "TEST",
                "reason": "seed",
            },
            {
                "item_id": "DRAM_INTRADAY_TRIGGER",
                "item_name": "DRAM Intraday Trigger",
                "item_type": "DRAM_SYSTEM",
                "family": "DRAM",
                "forward_confirmation_status": "FORWARD_PENDING_MATURITY",
                "forward_5d_status": "FORWARD_PENDING_MATURITY",
                "forward_10d_status": "FORWARD_PENDING_MATURITY",
                "forward_20d_status": "FORWARD_PENDING_MATURITY",
                "matured_forward_observation_count_estimate": 3,
                "supportive_forward_observation_count_estimate": 0,
                "source_summary_only_flag": False,
                "placeholder_only_flag": False,
                "primary_blocker": "",
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
                "trade_allowed": False,
                "next_required_validation": "TEST",
                "reason": "seed",
            },
            {
                "item_id": "DRAM_NO_TRADE_GATE",
                "item_name": "DRAM No Trade Gate",
                "item_type": "DRAM_SYSTEM",
                "family": "DRAM",
                "forward_confirmation_status": "FORWARD_PENDING_MATURITY",
                "forward_5d_status": "FORWARD_PENDING_MATURITY",
                "forward_10d_status": "FORWARD_PENDING_MATURITY",
                "forward_20d_status": "FORWARD_PENDING_MATURITY",
                "matured_forward_observation_count_estimate": 3,
                "supportive_forward_observation_count_estimate": 0,
                "source_summary_only_flag": False,
                "placeholder_only_flag": False,
                "primary_blocker": "",
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
                "trade_allowed": False,
                "next_required_validation": "TEST",
                "reason": "seed",
            },
        ],
    )
    (repo / module.FORWARD_SUMMARY_INPUT).parent.mkdir(parents=True, exist_ok=True)
    (repo / module.FORWARD_SUMMARY_INPUT).write_text(json.dumps({"final_decision": "FORWARD_ONLY_FACTOR_CONFIRMATION_DASHBOARD_READY_RESEARCH_ONLY"}), encoding="utf-8")
    write_csv(
        repo / "outputs" / "v21" / "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH" / "dram_daily_plan_moomoo_r4.csv",
        ["plan_date", "latest_price_date", "ticker", "planned_entry", "no_chase_above", "stop_loss", "take_profit_1"],
        [{"plan_date": "2026-07-05", "latest_price_date": "2026-07-05", "ticker": "DRAM", "planned_entry": 70.0, "no_chase_above": 75.0, "stop_loss": 65.0, "take_profit_1": 80.0}],
    )


def run_stage(tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "repo"
    seed_inputs(repo)
    payload = module.run(repo)
    return repo, payload


def test_required_output_files_are_created(tmp_path):
    repo, _ = run_stage(tmp_path)
    for filename in REQUIRED_FILES:
        assert (repo / module.OUT_REL / filename).exists()


def test_summary_decision_and_counts(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_dram_daily_decision_panel_summary.json").read_text(encoding="utf-8"))
    assert summary["final_decision"] == "DRAM_DAILY_DECISION_PANEL_READY_RESEARCH_ONLY"
    assert summary["forward_confirmation_input_exists"] is True
    assert summary["dram_panel_row_count"] >= 1


def test_panel_symbol_labels_and_closed_permissions(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_dram_daily_decision_panel.csv")
    assert rows
    for row in rows:
        assert row["primary_symbol"] == "DRAM"
        assert row["final_research_action_label"] not in FORBIDDEN_LABELS
        assert row["official_adoption_allowed"] == "False"
        assert row["broker_action_allowed"] == "False"
        assert row["trade_allowed"] == "False"


def test_signal_groups_and_forward_maturity(tmp_path):
    repo, _ = run_stage(tmp_path)
    signal_rows = read_rows(repo / module.OUT_REL / "v22_dram_signal_to_action_panel.csv")
    groups = {row["signal_group"] for row in signal_rows}
    assert {"DAILY_PLAN", "FORWARD_CONFIRMATION", "NO_TRADE_GATE", "OPTION_EXTENSION_PLACEHOLDER", "PERSONAL_RISK_RULE"}.issubset(groups)
    forward_rows = read_rows(repo / module.OUT_REL / "v22_dram_forward_maturity_panel.csv")
    assert "DRAM_DAILY_PLAN" in {row["item_id"] for row in forward_rows}


def test_summary_gates_are_false(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_dram_daily_decision_panel_summary.json").read_text(encoding="utf-8"))
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
    assert summary["protected_outputs_modified"] is False


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


def test_module_writes_only_under_v22_020_output_dir(tmp_path):
    repo, payload = run_stage(tmp_path)
    expected = (repo / module.OUT_REL).resolve()
    allowed_seed_files = {
        (repo / module.FORWARD_DASHBOARD_INPUT).resolve(),
        (repo / module.FORWARD_SUMMARY_INPUT).resolve(),
        (repo / "outputs" / "v21" / "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH" / "dram_daily_plan_moomoo_r4.csv").resolve(),
    }
    assert expected.name == "V22.020_DRAM_DAILY_DECISION_PANEL_R2"
    assert payload["module_id"] == "V22.020"
    for path in repo.rglob("*"):
        if path.is_file() and path.resolve() not in allowed_seed_files:
            assert expected in path.resolve().parents
