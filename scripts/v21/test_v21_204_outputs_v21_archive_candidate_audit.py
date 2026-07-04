from __future__ import annotations

import csv
import importlib.util
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_204_outputs_v21_archive_candidate_audit.py"
WRAPPER = ROOT / "scripts/v21/run_v21_204_outputs_v21_archive_candidate_audit.ps1"
NOW = datetime(2026, 7, 2, tzinfo=timezone.utc)
OLD_TS = datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp()
NEW_TS = datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()


def load_module():
    spec = importlib.util.spec_from_file_location("v21_204", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def touch(path: Path, size: int = 1, text: str | None = None, ts: float = OLD_TS) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if text is not None:
        path.write_text(text, encoding="utf-8")
    else:
        with path.open("wb") as handle:
            handle.write(b"x" * size)
    os.utime(path, (ts, ts))
    os.utime(path.parent, (ts, ts))
    return path


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def make_repo(tmp_path: Path, include_all_protected: bool = True) -> Path:
    root = tmp_path / "repo"
    out = root / "outputs/v21"
    touch(out / "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/ranking.csv")
    touch(out / "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/summary.json")
    touch(out / "V21.202_REPO_SAFE_CLEANUP_AUDIT_AND_CACHE_PURGE/v21_202_summary.json")
    touch(out / "V21.203_REPO_SIZE_ATTRIBUTION_AND_SAFE_PURGE_CANDIDATE_AUDIT/v21_203_summary.json")
    if include_all_protected:
        touch(out / "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/plan.json")
    return root


def row_for(root: Path, module, stage: str) -> dict[str, str]:
    audit = rows(root / module.OUT_REL / "outputs_v21_stage_archive_candidate_audit.csv")
    return next(row for row in audit if row["stage_name"] == stage)


def test_protected_v21_197_excluded(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    module.run(root, now=NOW)
    row = row_for(root, module, "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT")
    assert row["protected_stage_flag"] == "True"
    assert row["archive_candidate_tier"] == "NOT_ARCHIVE_CANDIDATE"


def test_protected_v21_199_r4_excluded(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    module.run(root, now=NOW)
    row = row_for(root, module, "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME")
    assert row["protected_stage_flag"] == "True"
    assert row["archive_candidate_flag"] == "False"


def test_protected_v21_201_alias_excluded(tmp_path):
    module = load_module()
    root = make_repo(tmp_path, include_all_protected=False)
    touch(root / "outputs/v21/V21.201_DAILY_DRAM_MOOMOO_R4_PLAN_REFRESH/plan.json")
    module.run(root, now=NOW)
    row = row_for(root, module, "V21.201_DAILY_DRAM_MOOMOO_R4_PLAN_REFRESH")
    assert row["protected_stage_flag"] == "True"
    assert row["archive_candidate_tier"] == "NOT_ARCHIVE_CANDIDATE"


def test_v21_202_and_v21_203_excluded(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    module.run(root, now=NOW)
    for stage in ["V21.202_REPO_SAFE_CLEANUP_AUDIT_AND_CACHE_PURGE", "V21.203_REPO_SIZE_ATTRIBUTION_AND_SAFE_PURGE_CANDIDATE_AUDIT"]:
        row = row_for(root, module, stage)
        assert row["protected_stage_flag"] == "True"
        assert row["archive_candidate_flag"] == "False"


def test_current_chain_keyword_files_cause_exclusion(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    stage = "V21.120_OLD_BUT_LATEST_KEYWORD"
    touch(root / f"outputs/v21/{stage}/latest_signal.csv", size=2 * 1024 * 1024)
    module.run(root, now=NOW)
    row = row_for(root, module, stage)
    assert row["current_chain_flag"] == "True"
    assert row["archive_candidate_flag"] == "False"


def test_sensitive_artifact_files_cause_exclusion(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    for token in ["canonical.csv", "price_history.csv", "trade_plan.csv", "daily.kline", "ledger.csv", "ranking.csv"]:
        stage = f"V21.130_{token.replace('.', '_').upper()}"
        touch(root / f"outputs/v21/{stage}/{token}", size=2 * 1024 * 1024)
    module.run(root, now=NOW)
    for token in ["CANONICAL_CSV", "PRICE_HISTORY_CSV", "TRADE_PLAN_CSV", "DAILY_KLINE", "LEDGER_CSV", "RANKING_CSV"]:
        row = row_for(root, module, f"V21.130_{token}")
        assert row["archive_candidate_flag"] == "False"
        assert "SENSITIVE_CURRENT_ARTIFACT_NAME" in row["exclusion_reasons"] or row["current_chain_flag"] == "True"


def test_old_large_completed_report_only_directory_becomes_tier1(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    stage = "V21.050_OLD_RESEARCH_REPLAY"
    touch(root / f"outputs/v21/{stage}/v21_050_summary.json", text="{}")
    touch(root / f"outputs/v21/{stage}/V21.050_report.txt", text="report")
    touch(root / f"outputs/v21/{stage}/payload.bin", size=11 * 1024 * 1024)
    module.run(root, now=NOW)
    row = row_for(root, module, stage)
    assert row["archive_candidate_tier"] == "TIER_1_ARCHIVE_CANDIDATE"
    assert row["archive_candidate_flag"] == "True"


def test_old_medium_ambiguous_directory_becomes_tier2(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    stage = "V21.060_OLD_AMBIGUOUS"
    touch(root / f"outputs/v21/{stage}/payload.bin", size=2 * 1024 * 1024)
    module.run(root, now=NOW)
    row = row_for(root, module, stage)
    assert row["archive_candidate_tier"] == "TIER_2_REVIEW_CANDIDATE"


def test_tiny_directory_not_proposed(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    stage = "V21.061_TINY_OLD"
    touch(root / f"outputs/v21/{stage}/payload.bin", size=128)
    module.run(root, now=NOW)
    row = row_for(root, module, stage)
    assert row["archive_candidate_tier"] == "NOT_ARCHIVE_CANDIDATE"
    assert row["archive_candidate_flag"] == "False"


def test_summary_and_report_artifacts_written(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    summary = module.run(root, now=NOW)
    out = root / module.OUT_REL
    for name in [
        "v21_204_summary.json",
        "V21.204_outputs_v21_archive_candidate_report.txt",
        "outputs_v21_stage_archive_candidate_audit.csv",
        "outputs_v21_largest_stage_directories.csv",
        "protected_stage_resolution_check.csv",
        "archive_candidate_exclusion_reason_counts.csv",
    ]:
        assert (out / name).is_file()
    assert summary["research_only"] is True
    assert summary["audit_only"] is True
    assert summary["mutation_allowed"] is False
    assert summary["deletion_performed"] is False


def test_no_mutation_behavior(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    protected = root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/ranking.csv"
    before = protected.read_text(encoding="utf-8")
    module.run(root, now=NOW)
    assert protected.read_text(encoding="utf-8") == before


def test_missing_protected_stage_produces_warn(tmp_path):
    module = load_module()
    root = make_repo(tmp_path, include_all_protected=False)
    summary = module.run(root, now=NOW)
    assert summary["final_status"] == "WARN_V21_204_PROTECTED_STAGE_RESOLUTION_INCOMPLETE"
    assert summary["final_decision"] == "OUTPUTS_V21_ARCHIVE_AUDIT_WARN_PROTECTED_RESOLUTION"


def test_audit_exception_produces_fail(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    summary = module.run(root, simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_204_ARCHIVE_CANDIDATE_AUDIT_EXCEPTION"
    assert summary["final_decision"] == "OUTPUTS_V21_ARCHIVE_AUDIT_FAILED"
    assert summary["deletion_performed"] is False


def test_wrapper_exists_and_uses_venv_python():
    assert WRAPPER.is_file()
    text = WRAPPER.read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in text
    assert "v21_204_outputs_v21_archive_candidate_audit.py" in text
