from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

P = Path(__file__).with_name("v21_248_r1_active_event_dependency_replacement_plan.py")
S = importlib.util.spec_from_file_location("m248r1", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def wc(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def seed(repo: Path) -> None:
    (repo / "scripts/v21").mkdir(parents=True, exist_ok=True)
    (repo / "scripts/v21/v21_241_daily_chain_retention_guard_integration.py").write_text("# external policy reference, no event updater call\n", encoding="utf-8")
    (repo / "scripts/v21/v21_248_event_auto_update_retirement_and_moomoo_only_replacement_audit.py").write_text("# event retirement inventory scanner\n", encoding="utf-8")
    rows = [
        {"path": str(repo / "scripts/v21/v21_241_daily_chain_retention_guard_integration.py"), "relative_path": "scripts/v21/v21_241_daily_chain_retention_guard_integration.py", "module_type": ".py", "event_auto_update_related": "True", "active_chain_dependency": "True", "retirement_decision": "KEEP_REQUIRED", "notes": "inventory"},
        {"path": str(repo / "scripts/v21/v21_248_event_auto_update_retirement_and_moomoo_only_replacement_audit.py"), "relative_path": "scripts/v21/v21_248_event_auto_update_retirement_and_moomoo_only_replacement_audit.py", "module_type": ".py", "event_auto_update_related": "True", "active_chain_dependency": "True", "retirement_decision": "KEEP_REQUIRED", "notes": "inventory"},
    ]
    wc(repo / m.V248_REL / "event_auto_update_module_inventory.csv", rows, ["path", "relative_path", "module_type", "event_auto_update_related", "active_chain_dependency", "retirement_decision", "notes"])


def test_active_dependencies_classified_without_mutation_or_disable(tmp_path):
    repo = tmp_path / "repo"
    seed(repo)
    p = repo / "scripts/v21/v21_241_daily_chain_retention_guard_integration.py"
    before = p.read_text(encoding="utf-8")
    summary = m.run(repo)
    out = repo / m.OUT_REL
    assert p.read_text(encoding="utf-8") == before
    assert summary["active_dependency_count"] == 2
    assert summary["delete_allowed"] is False and summary["quarantine_allowed"] is False
    assert summary["broker_action_allowed"] is False and summary["official_adoption_allowed"] is False
    assert summary["hard_dependency_count"] == 0
    assert summary["unknown_blocker_count"] == 0
    detail = (out / "active_event_dependency_detail.csv").read_text(encoding="utf-8")
    assert "v21_241_daily_chain_retention_guard_integration.py" in detail
    assert "v21_248_event_auto_update_retirement_and_moomoo_only_replacement_audit.py" in detail
    assert "DISABLE_SAFE_AFTER_CHAIN_TEST" in (out / "active_event_dependency_replacement_plan.csv").read_text(encoding="utf-8")
    for name in [
        "active_event_dependency_call_graph.csv",
        "moomoo_only_equivalent_source_audit.csv",
        "disable_chain_test_plan.csv",
        "quarantine_delete_safety_plan.csv",
        "v21_248_r1_summary.json",
        "V21.248_R1_active_event_dependency_replacement_report.txt",
    ]:
        assert (out / name).exists()


def test_missing_v248_input_fails(tmp_path):
    summary = m.run(tmp_path / "repo")
    assert summary["final_status"] == "FAIL_V21_248_R1_REQUIRED_INPUT_MISSING"
    assert summary["error_count"] == 1
