from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
from pathlib import Path

P = Path(__file__).with_name("v21_250_technical_diagnostic_freeze_and_manual_checklist_archive_r1.py")
S = importlib.util.spec_from_file_location("m250", P)
m = importlib.util.module_from_spec(S)
S.loader.exec_module(m)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else ["x"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def rows(path: Path):
    return list(csv.DictReader(path.open(encoding="utf-8")))


def seed(tmp_path: Path, passed: int = 0, missing_noncritical: bool = False):
    repo = tmp_path / "repo"
    summaries = {
        m.V246_REL / "v21_246_summary.json": {"final_status": "P", "technical_indicator_count": 27, "research_only": True, "official_adoption_allowed": False, "broker_action_allowed": False},
        m.V247_REL / "v21_247_summary.json": {"final_status": "P", "research_only": True, "official_adoption_allowed": False, "broker_action_allowed": False},
        m.V248_REL / "v21_248_summary.json": {"final_status": "P", "repair_candidate_count": 6, "research_only": True, "official_adoption_allowed": False, "broker_action_allowed": False},
        m.V249_REL / "v21_249_summary.json": {"final_status": "WARN", "repair_candidate_count": 6, "tested_repair_candidate_count": 6, "passed_repair_candidate_count": passed, "incremental_edge_confirmed_count": 0 if passed == 0 else 1, "timing_overlay_candidate_count": 0 if passed == 0 else 1, "context_filter_candidate_count": 0, "research_only": True, "official_adoption_allowed": False, "broker_action_allowed": False},
    }
    for rel, data in summaries.items():
        write_json(repo / rel, data)
    if not missing_noncritical:
        for rel in [
            m.V246_REL / "technical_panel_quality_audit.csv",
            m.V246_REL / "forward_return_quality_audit.csv",
            m.V247_REL / "technical_subfactor_effectiveness_master.csv",
            m.V247_REL / "technical_subfactor_candidate_for_v21_248.csv",
            m.V248_REL / "technical_repair_candidate_spec.csv",
            m.V248_REL / "technical_signal_final_disposition.csv",
            m.V249_REL / "technical_repair_role_recommendation.csv",
            m.V249_REL / "technical_repair_keep_drop_review.csv",
        ]:
            write_csv(repo / rel, [{"x": 1}])
    protected = repo / "protected.txt"
    protected.write_text("protected", encoding="utf-8")
    return repo, protected, hashlib.sha256(protected.read_bytes()).hexdigest()


def test_missing_v21_249_summary(tmp_path):
    repo, _, _ = seed(tmp_path)
    (repo / m.V249_REL / "v21_249_summary.json").unlink()
    assert m.run(repo)["final_status"] == "FAIL_V21_250_TECHNICAL_FREEZE_INPUT_MISSING"


def test_missing_noncritical_csv_warns(tmp_path):
    repo, _, _ = seed(tmp_path, missing_noncritical=True)
    s = m.run(repo)
    assert s["final_status"] == "WARN_V21_250_TECHNICAL_ARCHIVE_INCOMPLETE"


def test_zero_passed_candidates_produces_freeze(tmp_path):
    repo, _, _ = seed(tmp_path, passed=0)
    s = m.run(repo)
    assert s["final_status"] == "PASS_V21_250_TECHNICAL_DIAGNOSTIC_FREEZE_ARCHIVED"
    assert s["model_entry_allowed"] is False


def test_nonzero_passed_candidates_warns(tmp_path):
    repo, _, _ = seed(tmp_path, passed=1)
    s = m.run(repo)
    assert s["final_status"] == "WARN_V21_250_TECHNICAL_ARCHIVE_INCOMPLETE"


def test_manual_checklist_observation_only(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    data = rows(repo / m.OUT_REL / "technical_manual_checklist_archive.csv")
    assert data
    assert {r["automated_signal"] for r in data} == {"False"}
    assert {r["ranking_input"] for r in data} == {"False"}
    assert {r["weight_input"] for r in data} == {"False"}
    assert {r["broker_action_input"] for r in data} == {"False"}


def test_all_blocking_gates(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    assert s["model_entry_allowed"] is False
    assert s["weight_update_allowed"] is False
    assert s["automatic_timing_overlay_allowed"] is False
    assert s["context_filter_integration_allowed"] is False
    assert s["broker_action_allowed"] is False


def test_summary_json_schema(tmp_path):
    repo, _, _ = seed(tmp_path)
    m.run(repo)
    payload = json.loads((repo / m.OUT_REL / "v21_250_summary.json").read_text(encoding="utf-8"))
    for k in ["final_status", "final_decision", "chain_stage_count", "manual_checklist_item_count", "reopen_condition_count", "research_only", "official_adoption_allowed", "broker_action_allowed"]:
        assert k in payload


def test_no_market_data_provider_call_static(tmp_path):
    repo, _, _ = seed(tmp_path)
    s = m.run(repo)
    assert s["market_data_fetch_allowed"] is False
    text = P.read_text(encoding="utf-8").lower()
    banned = [r"\bimport\s+yfinance\b", r"\bfrom\s+yfinance\b", r"\bimport\s+moomoo\b", r"\bfrom\s+moomoo\b", r"\bimport\s+futu\b", r"\bfrom\s+futu\b"]
    assert not any(re.search(p, text) for p in banned)


def test_no_protected_output_mutation(tmp_path):
    repo, protected, before = seed(tmp_path)
    m.run(repo)
    assert hashlib.sha256(protected.read_bytes()).hexdigest() == before
