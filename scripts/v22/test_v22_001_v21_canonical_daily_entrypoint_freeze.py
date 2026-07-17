from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_001_v21_canonical_daily_entrypoint_freeze.py")
SPEC = importlib.util.spec_from_file_location("v22_001", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


REQUIRED_FILES = [
    "v21_canonical_daily_entrypoint.json",
    "v21_daily_chain_entrypoint_manifest.csv",
    "v21_entrypoint_dependency_presence_audit.csv",
    "v21_entrypoint_freeze_risk_gate.json",
    "V22.001_v21_canonical_daily_entrypoint_freeze_report.txt",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def seed_required_references(repo: Path) -> None:
    (repo / "scripts" / "v21").mkdir(parents=True, exist_ok=True)
    (repo / module.ACCEPTED_ENTRYPOINT_SCRIPT).write_text("# placeholder\n", encoding="utf-8")
    scope_path = repo / module.V22_000_SCOPE_FILE
    scope_path.parent.mkdir(parents=True, exist_ok=True)
    scope_path.write_text("{}\n", encoding="utf-8")


def run_stage(tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "repo"
    seed_required_references(repo)
    payload = module.run(repo)
    return repo, payload


def test_required_output_files_are_created(tmp_path):
    repo, _ = run_stage(tmp_path)
    out = repo / module.OUT_REL
    for filename in REQUIRED_FILES:
        assert (out / filename).exists()


def test_final_decision_and_entrypoint_fields(tmp_path):
    repo, payload = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v21_canonical_daily_entrypoint.json").read_text(encoding="utf-8"))
    assert payload["final_decision"] == "V21_CANONICAL_DAILY_ENTRYPOINT_FROZEN_FOR_V22_CONSOLIDATION_RESEARCH_ONLY"
    assert summary["final_decision"] == "V21_CANONICAL_DAILY_ENTRYPOINT_FROZEN_FOR_V22_CONSOLIDATION_RESEARCH_ONLY"
    assert summary["accepted_entrypoint_script"] == "scripts/v21/run_v21_256_daily_chain_master_wrapper_with_context_r1.ps1"
    assert summary["daily_chain_execution_allowed_in_v22_001"] is False


def test_all_broker_network_and_trade_gates_false(tmp_path):
    repo, _ = run_stage(tmp_path)
    summary = json.loads((repo / module.OUT_REL / "v21_canonical_daily_entrypoint.json").read_text(encoding="utf-8"))
    for key in [
        "broker_action_allowed",
        "official_adoption_allowed",
        "trade_allowed",
        "moomoo_connection_allowed",
        "market_data_fetch_allowed",
        "option_chain_fetch_allowed",
    ]:
        assert summary[key] is False
    assert summary["protected_outputs_modified"] is False


def test_manifest_includes_canonical_entrypoint(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v21_daily_chain_entrypoint_manifest.csv")
    by_name = {row["entrypoint_name"]: row for row in rows}
    canonical = by_name["V21.256_DAILY_CHAIN_MASTER_WRAPPER_WITH_CONTEXT_R1"]
    assert canonical["entrypoint_script"] == "scripts/v21/run_v21_256_daily_chain_master_wrapper_with_context_r1.ps1"
    assert canonical["role"] == "CANONICAL_V21_DAILY_RESEARCH_ENTRYPOINT"
    assert canonical["status"] == "ACCEPTED_IF_PRESENT"
    assert canonical["execute_allowed_in_this_module"] == "False"


def test_dependency_audit_includes_required_references(tmp_path):
    repo, _ = run_stage(tmp_path)
    rows = read_rows(repo / module.OUT_REL / "v21_entrypoint_dependency_presence_audit.csv")
    by_path = {row["dependency_path"]: row for row in rows}
    canonical = by_path["scripts/v21/run_v21_256_daily_chain_master_wrapper_with_context_r1.ps1"]
    scope = by_path["outputs/v22/V22.000_V22_CHARTER_SCOPE_AND_RISK_POLICY_FREEZE/v22_charter_scope_freeze.json"]
    assert canonical["required_for_freeze"] == "True"
    assert canonical["exists"] == "True"
    assert scope["required_for_freeze"] == "True"
    assert scope["exists"] == "True"


def test_module_has_no_broker_network_or_market_data_imports():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    banned_modules = {
        "moomoo",
        "futu",
        "yfinance",
        "requests",
        "urllib",
        "http",
        "socket",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(banned_modules)


def test_module_writes_only_under_v22_001_output_dir(tmp_path):
    repo, payload = run_stage(tmp_path)
    expected = (repo / module.OUT_REL).resolve()
    assert Path(payload["output_dir"]).resolve() == expected
    assert expected.name == "V22.001_V21_CANONICAL_DAILY_ENTRYPOINT_FREEZE"

    allowed_seed_files = {
        (repo / module.ACCEPTED_ENTRYPOINT_SCRIPT).resolve(),
        (repo / module.V22_000_SCOPE_FILE).resolve(),
    }
    for path in repo.rglob("*"):
        if path.is_file() and path.resolve() not in allowed_seed_files:
            assert expected in path.resolve().parents


def test_warn_status_when_required_references_missing(tmp_path):
    repo = tmp_path / "repo"
    payload = module.run(repo)
    assert payload["final_status"] == "WARN_V22_001_ENTRYPOINT_FREEZE_DONE_WITH_MISSING_REFERENCES"
    assert payload["final_decision"] == "V21_CANONICAL_DAILY_ENTRYPOINT_FROZEN_FOR_V22_CONSOLIDATION_RESEARCH_ONLY"
