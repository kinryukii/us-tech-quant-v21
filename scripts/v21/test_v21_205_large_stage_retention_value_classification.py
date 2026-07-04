from __future__ import annotations

import csv
import importlib.util
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_205_large_stage_retention_value_classification.py"
WRAPPER = ROOT / "scripts/v21/run_v21_205_large_stage_retention_value_classification.ps1"
NOW = datetime(2026, 7, 2, tzinfo=timezone.utc)
OLD_TS = datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp()


def load_module():
    spec = importlib.util.spec_from_file_location("v21_205", SCRIPT)
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
    touch(out / "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/ranking.csv", size=2048)
    touch(out / "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/summary.json", text='{"final_status":"PASS"}')
    touch(out / "V21.202_REPO_SAFE_CLEANUP_AUDIT_AND_CACHE_PURGE/v21_202_summary.json", text='{"final_status":"PASS"}')
    touch(out / "V21.203_REPO_SIZE_ATTRIBUTION_AND_SAFE_PURGE_CANDIDATE_AUDIT/v21_203_summary.json", text='{"final_status":"PASS"}')
    if include_all_protected:
        touch(out / "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/plan.json", size=2048)
    return root


def row_for(root: Path, module, stage: str) -> dict[str, str]:
    table = rows(root / module.OUT_REL / "large_stage_retention_classification.csv")
    return next(row for row in table if row["stage_name"] == stage)


def run_small_threshold(module, root: Path):
    return module.run(root, threshold_bytes=1, now=NOW)


def test_protected_stages_classified_must_keep_protected(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    run_small_threshold(module, root)
    row = row_for(root, module, "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME")
    assert row["retention_value_class"] == "MUST_KEEP_PROTECTED_STAGE"
    assert row["future_action_recommendation"] == "KEEP_AS_IS_PROTECTED"


def test_current_chain_keyword_stage_classified_must_keep_current(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    stage = "V21.120_LATEST_SIGNAL_OUTPUT"
    touch(root / f"outputs/v21/{stage}/latest_signal.csv", size=2048)
    run_small_threshold(module, root)
    row = row_for(root, module, stage)
    assert row["retention_value_class"] == "MUST_KEEP_CURRENT_CHAIN"
    assert row["future_action_recommendation"] == "KEEP_AS_IS"


def test_v21_154_invalid_trial_replay_classified_conservatively(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    stage = "V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT"
    touch(root / f"outputs/v21/{stage}/invalid_trial_replay_summary.json", text='{"final_status":"PASS"}')
    touch(root / f"outputs/v21/{stage}/payload.csv", size=4096)
    run_small_threshold(module, root)
    row = row_for(root, module, stage)
    assert row["retention_value_class"] in {"KEEP_AUDIT_CRITICAL_HISTORY", "KEEP_REPRODUCIBILITY_SUPPORT"}
    assert row["future_action_recommendation"] in {"KEEP_AS_IS", "REVIEW_BEFORE_ANY_ACTION"}


def test_large_report_only_historical_stage_can_be_compress_only(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    stage = "V21.050_OLD_REPORT_ONLY"
    touch(root / f"outputs/v21/{stage}/v21_050_summary.json", text='{"final_status":"PASS"}')
    touch(root / f"outputs/v21/{stage}/V21.050_report.txt", text="report")
    touch(root / f"outputs/v21/{stage}/intermediate.csv", size=4096)
    run_small_threshold(module, root)
    row = row_for(root, module, stage)
    assert row["retention_value_class"] == "COMPRESS_ONLY_CANDIDATE"
    assert row["future_action_recommendation"] in {"CONSIDER_ZIP_ARCHIVE_COPY_ONLY", "CONSIDER_COMPRESS_INTERMEDIATE_CSV_ONLY"}


def test_low_value_old_temp_heavy_large_stage_can_be_manual_review_low_value(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    stage = "V21.051_OLD_TEMP_HEAVY"
    touch(root / f"outputs/v21/{stage}/payload.tmp", size=4096)
    touch(root / f"outputs/v21/{stage}/small.txt", text="x")
    run_small_threshold(module, root)
    row = row_for(root, module, stage)
    assert row["retention_value_class"] == "MANUAL_REVIEW_LOW_VALUE_CANDIDATE"
    assert row["future_action_recommendation"] == "CONSIDER_MOVE_TO_ARCHIVE_AFTER_MANUAL_APPROVAL"


def test_sensitive_files_prevent_delete_recommendation(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    for token in ["canonical.csv", "price_history.csv", "daily.kline", "moomoo.csv", "dram.csv", "abcde.csv", "trade_plan.csv", "ranking.csv", "ledger.csv"]:
        stage = f"V21.060_{token.replace('.', '_').upper()}"
        touch(root / f"outputs/v21/{stage}/{token}", size=2048)
    run_small_threshold(module, root)
    for token in ["CANONICAL_CSV", "PRICE_HISTORY_CSV", "DAILY_KLINE", "MOOMOO_CSV", "DRAM_CSV", "ABCDE_CSV", "TRADE_PLAN_CSV", "RANKING_CSV", "LEDGER_CSV"]:
        row = row_for(root, module, f"V21.060_{token}")
        assert row["future_action_recommendation"] in {"KEEP_AS_IS", "REVIEW_BEFORE_ANY_ACTION"}
        assert "DELETE" not in row["future_action_recommendation"]


def test_largest_file_and_file_type_breakdown_generated(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    stage = "V21.070_FILES"
    touch(root / f"outputs/v21/{stage}/big.csv", size=4096)
    touch(root / f"outputs/v21/{stage}/small.json", text="{}")
    run_small_threshold(module, root)
    largest = rows(root / module.OUT_REL / "large_stage_largest_files.csv")
    breakdown = rows(root / module.OUT_REL / "large_stage_file_type_breakdown.csv")
    assert any(row["stage_name"] == stage and row["file_path"].endswith("big.csv") for row in largest)
    assert any(row["stage_name"] == stage and row["file_type"] == "csv" for row in breakdown)


def test_summary_and_report_artifacts_written(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    summary = run_small_threshold(module, root)
    out = root / module.OUT_REL
    for name in [
        "v21_205_summary.json",
        "V21.205_large_stage_retention_value_report.txt",
        "large_stage_retention_classification.csv",
        "large_stage_largest_files.csv",
        "large_stage_file_type_breakdown.csv",
        "large_stage_recommended_manual_actions.csv",
        "protected_stage_resolution_check.csv",
    ]:
        assert (out / name).is_file()
    assert summary["research_only"] is True
    assert summary["audit_only"] is True
    assert summary["mutation_allowed"] is False
    assert summary["deletion_performed"] is False
    assert summary["compression_performed"] is False


def test_no_mutation_behavior(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    protected = root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/ranking.csv"
    before = protected.read_text(encoding="utf-8")
    run_small_threshold(module, root)
    assert protected.read_text(encoding="utf-8") == before


def test_missing_protected_stage_produces_warn(tmp_path):
    module = load_module()
    root = make_repo(tmp_path, include_all_protected=False)
    summary = run_small_threshold(module, root)
    assert summary["final_status"] == "WARN_V21_205_PROTECTED_STAGE_RESOLUTION_INCOMPLETE"
    assert summary["final_decision"] == "LARGE_STAGE_RETENTION_CLASSIFICATION_WARN_PROTECTED_RESOLUTION"


def test_audit_exception_produces_fail(tmp_path):
    module = load_module()
    root = make_repo(tmp_path)
    summary = module.run(root, simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_205_RETENTION_CLASSIFICATION_EXCEPTION"
    assert summary["final_decision"] == "LARGE_STAGE_RETENTION_CLASSIFICATION_FAILED"
    assert summary["deletion_performed"] is False


def test_wrapper_exists_and_uses_venv_python():
    assert WRAPPER.is_file()
    text = WRAPPER.read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in text
    assert "v21_205_large_stage_retention_value_classification.py" in text
