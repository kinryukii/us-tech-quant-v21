from __future__ import annotations

import csv
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_206_compress_only_dry_run_plan.py"
WRAPPER = ROOT / "scripts/v21/run_v21_206_compress_only_dry_run_plan.ps1"


def load_module():
    spec = importlib.util.spec_from_file_location("v21_206", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_v205(root: Path, rows_in: list[dict[str, str]]) -> Path:
    path = root / "v205.csv"
    fields = [
        "stage_dir", "stage_name", "retention_value_class", "future_action_recommendation",
        "protected_stage_flag", "current_chain_flag",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows_in)
    return path


def candidate(stage: str, cls: str = "COMPRESS_ONLY_CANDIDATE", action: str = "CONSIDER_ZIP_ARCHIVE_COPY_ONLY", protected: str = "False", current: str = "False") -> dict[str, str]:
    return {
        "stage_dir": f"outputs/v21/{stage}",
        "stage_name": stage,
        "retention_value_class": cls,
        "future_action_recommendation": action,
        "protected_stage_flag": protected,
        "current_chain_flag": current,
    }


def make_stage(root: Path, stage: str) -> Path:
    touch(root / f"outputs/v21/{stage}/a.csv", "alpha")
    touch(root / f"outputs/v21/{stage}/b.json", '{"b":1}')
    return root / f"outputs/v21/{stage}"


def run_with_rows(tmp_path: Path, rows_in: list[dict[str, str]], **kwargs):
    module = load_module()
    root = tmp_path / "repo"
    for row in rows_in:
        make_stage(root, row["stage_name"])
    source = write_v205(root, rows_in)
    summary = module.run(root, source_csv=source, **kwargs)
    return module, root, summary


def test_only_v205_compress_only_candidates_considered(tmp_path):
    rows_in = [candidate("V21.010_KEEP"), candidate("V21.011_OTHER", cls="KEEP_AUDIT_CRITICAL_HISTORY", action="KEEP_AS_IS")]
    module, root, summary = run_with_rows(tmp_path, rows_in)
    plan = rows(root / module.OUT_REL / "compress_only_dry_run_plan.csv")
    assert summary["candidate_count_from_v21_205"] == 1
    assert [r["stage_dir"] for r in plan] == ["outputs/v21/V21.010_KEEP"]


def test_protected_stages_excluded(tmp_path):
    rows_in = [candidate("V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME", protected="True")]
    module, root, summary = run_with_rows(tmp_path, rows_in)
    assert summary["candidate_count_after_exclusions"] == 0
    exclusions = rows(root / module.OUT_REL / "compression_exclusion_check.csv")
    assert exclusions[0]["exclusion_reason"] == "PROTECTED_STAGE_FLAG"


def test_current_chain_sensitive_keyword_stages_excluded(tmp_path):
    rows_in = [candidate("V21.010_LATEST_KEEP"), candidate("V21.011_SAFE")]
    module, root, summary = run_with_rows(tmp_path, rows_in)
    plan = rows(root / module.OUT_REL / "compress_only_dry_run_plan.csv")
    assert summary["candidate_count_after_exclusions"] == 1
    assert plan[0]["stage_dir"] == "outputs/v21/V21.011_SAFE"


def test_v21_154_always_excluded(tmp_path):
    rows_in = [candidate("V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT")]
    module, root, summary = run_with_rows(tmp_path, rows_in)
    assert summary["candidate_count_after_exclusions"] == 0
    exclusions = rows(root / module.OUT_REL / "compression_exclusion_check.csv")
    assert exclusions[0]["exclusion_reason"] == "HARDCODED_PROTECTED_EXCLUSION"


def test_dry_run_does_not_create_zip_files(tmp_path):
    rows_in = [candidate("V21.010_SAFE")]
    module, root, summary = run_with_rows(tmp_path, rows_in)
    plan = rows(root / module.OUT_REL / "compress_only_dry_run_plan.csv")
    assert summary["compression_performed"] is False
    assert not Path(plan[0]["proposed_archive_zip_path"]).exists()


def test_original_directories_are_not_modified(tmp_path):
    rows_in = [candidate("V21.010_SAFE")]
    module = load_module()
    root = tmp_path / "repo"
    stage = make_stage(root, "V21.010_SAFE")
    before = (stage / "a.csv").read_text(encoding="utf-8")
    source = write_v205(root, rows_in)
    module.run(root, source_csv=source)
    assert (stage / "a.csv").read_text(encoding="utf-8") == before


def test_sha256_manifest_is_generated(tmp_path):
    rows_in = [candidate("V21.010_SAFE")]
    module, root, summary = run_with_rows(tmp_path, rows_in)
    manifest = rows(root / module.OUT_REL / "compress_only_file_manifest.csv")
    assert manifest
    assert all(len(row["sha256"]) == 64 for row in manifest)


def test_compression_and_deletion_allowed_always_false(tmp_path):
    rows_in = [candidate("V21.010_SAFE")]
    module, root, summary = run_with_rows(tmp_path, rows_in)
    plan = rows(root / module.OUT_REL / "compress_only_dry_run_plan.csv")
    assert plan[0]["compression_allowed_in_this_run"] == "False"
    assert plan[0]["deletion_allowed_after_compression"] == "False"


def test_no_eligible_candidates_produces_warn(tmp_path):
    rows_in = [candidate("V21.011_OTHER", cls="KEEP_AUDIT_CRITICAL_HISTORY", action="KEEP_AS_IS")]
    module, root, summary = run_with_rows(tmp_path, rows_in)
    assert summary["final_status"] == "WARN_V21_206_NO_ELIGIBLE_COMPRESS_ONLY_CANDIDATES"
    assert summary["final_decision"] == "COMPRESS_ONLY_DRY_RUN_NO_ELIGIBLE_CANDIDATES"


def test_protected_current_chain_candidate_inclusion_produces_fail(tmp_path):
    rows_in = [candidate("V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME", protected="True")]
    module, root, summary = run_with_rows(tmp_path, rows_in, force_include_protected=True)
    assert summary["final_status"] == "FAIL_V21_206_PROTECTED_OR_CURRENT_CHAIN_CANDIDATE_INCLUDED"
    assert summary["final_decision"] == "COMPRESS_ONLY_DRY_RUN_BLOCKED_PROTECTED_CANDIDATE"


def test_summary_and_report_artifacts_written(tmp_path):
    rows_in = [candidate("V21.010_SAFE")]
    module, root, summary = run_with_rows(tmp_path, rows_in)
    out = root / module.OUT_REL
    for name in [
        "v21_206_summary.json",
        "V21.206_compress_only_dry_run_plan_report.txt",
        "compress_only_dry_run_plan.csv",
        "compress_only_file_manifest.csv",
        "compress_only_candidate_integrity_manifest.csv",
        "compression_exclusion_check.csv",
    ]:
        assert (out / name).is_file()
    assert summary["research_only"] is True
    assert summary["dry_run"] is True
    assert summary["mutation_allowed"] is False
    assert summary["archive_movement_performed"] is False


def test_audit_exception_produces_fail(tmp_path):
    module = load_module()
    root = tmp_path / "repo"
    summary = module.run(root, simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_206_COMPRESS_DRY_RUN_EXCEPTION"
    assert summary["final_decision"] == "COMPRESS_ONLY_DRY_RUN_FAILED"


def test_wrapper_exists_and_uses_venv_python():
    assert WRAPPER.is_file()
    text = WRAPPER.read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in text
    assert "v21_206_compress_only_dry_run_plan.py" in text
