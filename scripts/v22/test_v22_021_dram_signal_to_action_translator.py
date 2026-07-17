from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_021_dram_signal_to_action_translator.py")
SPEC = importlib.util.spec_from_file_location("v22_021", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "v22_dram_signal_to_action_translator.csv",
    "v22_dram_action_policy_table.csv",
    "v22_dram_action_blocker_audit.csv",
    "v22_dram_action_readiness_summary.csv",
    "v22_dram_signal_to_action_summary.json",
    "v22_dram_signal_to_action_risk_gate.json",
    "V22.021_dram_signal_to_action_translator_report.txt",
]

FORBIDDEN_STATES = {
    "BUY_NOW",
    "SELL_NOW",
    "TRADE_ALLOWED",
    "BROKER_ACTION_ALLOWED",
    "AUTO_TRADE",
    "EXECUTE_ORDER",
    "ORDER_READY",
    "ENTRY_APPROVED",
    "EXIT_APPROVED",
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
    write_csv(
        repo / module.DRAM_PANEL_INPUT,
        [
            "panel_date_utc",
            "primary_symbol",
            "source_status",
            "plan_currentness_status",
            "forward_confirmation_status_from_v22_015",
            "no_trade_gate_status",
            "option_extension_status",
            "primary_blocker",
            "secondary_blockers",
            "final_research_action_label",
        ],
        [
            {
                "panel_date_utc": "2026-07-06",
                "primary_symbol": "DRAM",
                "source_status": "LOCAL_DRAM_SOURCE_FOUND",
                "plan_currentness_status": "STALE_REVIEW_REQUIRED",
                "forward_confirmation_status_from_v22_015": "FORWARD_PENDING_MATURITY",
                "no_trade_gate_status": "LOCAL_GATE_REVIEW_REQUIRED",
                "option_extension_status": "NOT_YET_INGESTED",
                "primary_blocker": "FALSE_DISCOVERY_HIGH",
                "secondary_blockers": "",
                "final_research_action_label": "DRAM_FORWARD_PENDING_MATURITY",
            }
        ],
    )
    write_csv(
        repo / module.DRAM_SIGNAL_INPUT,
        ["signal_name", "signal_group", "signal_status", "source_path", "source_quality", "trade_allowed", "broker_action_allowed"],
        [
            {"signal_name": "Daily plan", "signal_group": "DAILY_PLAN", "signal_status": "LOCAL_DRAM_SOURCE_FOUND", "source_path": "local.csv", "source_quality": "LOCAL_SOURCE_SCAN", "trade_allowed": False, "broker_action_allowed": False},
            {"signal_name": "Forward confirmation", "signal_group": "FORWARD_CONFIRMATION", "signal_status": "FORWARD_PENDING_MATURITY", "source_path": "v22.csv", "source_quality": "V22_015_GOVERNANCE", "trade_allowed": False, "broker_action_allowed": False},
            {"signal_name": "No trade gate", "signal_group": "NO_TRADE_GATE", "signal_status": "LOCAL_GATE_REVIEW_REQUIRED", "source_path": "", "source_quality": "LOCAL_SOURCE_SUMMARY", "trade_allowed": False, "broker_action_allowed": False},
            {"signal_name": "Option placeholder", "signal_group": "OPTION_EXTENSION_PLACEHOLDER", "signal_status": "NOT_YET_INGESTED", "source_path": "", "source_quality": "PLACEHOLDER", "trade_allowed": False, "broker_action_allowed": False},
        ],
    )
    write_csv(
        repo / module.DRAM_FORWARD_INPUT,
        ["item_id", "forward_confirmation_status"],
        [{"item_id": "DRAM_DAILY_PLAN", "forward_confirmation_status": "FORWARD_PENDING_MATURITY"}],
    )
    (repo / module.DRAM_SUMMARY_INPUT).parent.mkdir(parents=True, exist_ok=True)
    (repo / module.DRAM_SUMMARY_INPUT).write_text(json.dumps({"final_decision": "DRAM_DAILY_DECISION_PANEL_READY_RESEARCH_ONLY"}), encoding="utf-8")
    (repo / module.DRAM_RISK_STATE_INPUT).parent.mkdir(parents=True, exist_ok=True)
    (repo / module.DRAM_RISK_STATE_INPUT).write_text(
        json.dumps(
            {
                "broker_action_allowed": False,
                "official_adoption_allowed": False,
                "trade_allowed": False,
                "market_data_fetch_allowed": False,
                "moomoo_connection_allowed": False,
                "option_chain_fetch_allowed": False,
                "daily_chain_execution_allowed": False,
            }
        ),
        encoding="utf-8",
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


def test_summary_decision_inputs_and_counts(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_dram_signal_to_action_summary.json").read_text(encoding="utf-8"))
    assert summary["final_decision"] == "DRAM_SIGNAL_TO_ACTION_TRANSLATOR_READY_RESEARCH_ONLY"
    assert summary["dram_panel_input_exists"] is True
    assert summary["dram_signal_input_exists"] is True
    assert summary["dram_forward_input_exists"] is True
    assert summary["dram_summary_input_exists"] is True
    assert summary["dram_risk_state_input_exists"] is True
    assert summary["translated_signal_count"] >= 1
    assert summary["policy_count"] >= 8


def test_no_forbidden_states_and_no_row_permissions(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_dram_signal_to_action_translator.csv")
    assert rows
    for row in rows:
        assert row["translated_action_state"] not in FORBIDDEN_STATES
        assert row["official_adoption_allowed"] == "False"
        assert row["broker_action_allowed"] == "False"
        assert row["trade_allowed"] == "False"


def test_policy_table_contains_required_policies(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v22_dram_action_policy_table.csv")
    policies = {row["policy_name"] for row in rows}
    assert {
        "FORWARD_PENDING_MATURITY_POLICY",
        "NO_TRADE_GATE_POLICY",
        "RISK_GATE_POLICY",
        "OPTION_EXTENSION_PLACEHOLDER_POLICY",
        "PAPER_REVIEW_POLICY",
    }.issubset(policies)


def test_summary_gates_are_false_and_final_state_safe(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v22_dram_signal_to_action_summary.json").read_text(encoding="utf-8"))
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
    assert summary["final_translated_action_state"] not in FORBIDDEN_STATES


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


def test_module_writes_only_under_v22_021_output_dir(tmp_path):
    repo, payload = run_stage(tmp_path)
    expected = (repo / module.OUT_REL).resolve()
    allowed_seed_files = {
        (repo / module.DRAM_PANEL_INPUT).resolve(),
        (repo / module.DRAM_SIGNAL_INPUT).resolve(),
        (repo / module.DRAM_FORWARD_INPUT).resolve(),
        (repo / module.DRAM_SUMMARY_INPUT).resolve(),
        (repo / module.DRAM_RISK_STATE_INPUT).resolve(),
    }
    assert expected.name == "V22.021_DRAM_SIGNAL_TO_ACTION_TRANSLATOR"
    assert payload["module_id"] == "V22.021"
    for path in repo.rglob("*"):
        if path.is_file() and path.resolve() not in allowed_seed_files:
            assert expected in path.resolve().parents
