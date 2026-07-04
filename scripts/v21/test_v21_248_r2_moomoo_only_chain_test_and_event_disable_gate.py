from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

P = Path(__file__).with_name("v21_248_r2_moomoo_only_chain_test_and_event_disable_gate.py")
S = importlib.util.spec_from_file_location("m248r2", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def wc(path: Path, data: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, lineterminator="\n")
        w.writeheader()
        w.writerows(data)


def wj(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def seed(repo: Path) -> None:
    (repo / "scripts/v21").mkdir(parents=True, exist_ok=True)
    (repo / "scripts/v21/v21_241_daily_chain_retention_guard_integration.py").write_text("# stale external wording only\n", encoding="utf-8")
    (repo / "scripts/v21/v21_248_event_auto_update_retirement_and_moomoo_only_replacement_audit.py").write_text("# soft event audit scanner only\n", encoding="utf-8")
    wc(repo / m.R1_REL / "active_event_dependency_replacement_plan.csv", [
        {"dependency": "scripts/v21/v21_241_daily_chain_retention_guard_integration.py", "current_classification": "stale_reference", "proposed_action": "DISABLE_SAFE_AFTER_CHAIN_TEST", "replacement_source": "local", "disable_allowed_now": "False", "delete_allowed": "False", "quarantine_allowed": "False", "chain_test_required": "True", "notes": ""},
        {"dependency": "scripts/v21/v21_248_event_auto_update_retirement_and_moomoo_only_replacement_audit.py", "current_classification": "soft_dependency", "proposed_action": "REPLACE_WITH_MOOMOO_LOCAL_CACHE", "replacement_source": "local", "disable_allowed_now": "False", "delete_allowed": "False", "quarantine_allowed": "False", "chain_test_required": "True", "notes": ""},
    ], ["dependency", "current_classification", "proposed_action", "replacement_source", "disable_allowed_now", "delete_allowed", "quarantine_allowed", "chain_test_required", "notes"])
    wj(repo / m.V234_REL / "v21_234_summary.json", {"daily_chain_passed": True, "yfinance_used": False, "external_fallback_used": False, "broker_action_allowed": False, "official_adoption_allowed": False})
    wj(repo / m.V240_REL / "v21_240_summary.json", {"final_status": "PASS_V21_240_RETENTION_GUARD_OK", "repo_budget_status": "OK", "total_budget_status": "OK"})


def test_event_disable_gate_handles_exact_two_dependencies(tmp_path):
    repo = tmp_path / "repo"
    seed(repo)
    p = repo / "scripts/v21/v21_241_daily_chain_retention_guard_integration.py"
    before = p.read_text(encoding="utf-8")
    summary = m.run(repo)
    out = repo / m.OUT_REL
    assert p.read_text(encoding="utf-8") == before
    assert summary["active_dependencies_replaced_count"] == 2
    assert summary["active_dependencies_remaining_count"] == 0
    assert summary["delete_allowed"] is False and summary["quarantine_allowed"] is False
    assert summary["chain_test_executed"] is True
    assert summary["chain_test_passed"] is True
    assert summary["forbidden_external_fetch_found"] is False
    assert summary["broker_action_allowed"] is False and summary["official_adoption_allowed"] is False
    assert "forbidden_external_fetch_found" in (out / "forbidden_external_fetch_scan.csv").read_text(encoding="utf-8")
    assert "disable_confirmed" in (out / "event_disable_gate_decision.csv").read_text(encoding="utf-8")
    for name in ["event_dependency_disable_patch_audit.csv", "moomoo_only_chain_test_plan.csv", "moomoo_only_chain_test_result.csv", "retention_guard_after_disable_audit.csv", "v21_248_r2_summary.json", "V21.248_R2_moomoo_only_chain_test_event_disable_report.txt"]:
        assert (out / name).exists()


def test_forbidden_import_blocks_disable(tmp_path):
    repo = tmp_path / "repo"
    seed(repo)
    (repo / "scripts/v21/v21_241_daily_chain_retention_guard_integration.py").write_text("import yfinance\n", encoding="utf-8")
    summary = m.run(repo)
    assert summary["final_status"] == "DISABLE_BLOCKED_EXTERNAL_FETCH_FOUND"
    assert summary["disable_confirmed"] is False
