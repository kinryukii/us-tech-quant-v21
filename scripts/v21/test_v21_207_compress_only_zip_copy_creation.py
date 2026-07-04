from __future__ import annotations

import csv
import importlib.util
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_207_compress_only_zip_copy_creation.py"
WRAPPER = ROOT / "scripts/v21/run_v21_207_compress_only_zip_copy_creation.ps1"
APPROVED = [
    "V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST",
    "V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST",
    "V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY",
]


def load_module():
    spec = importlib.util.spec_from_file_location("v21_207", SCRIPT)
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


def write_plan(root: Path, stages: list[str]) -> Path:
    path = root / "v206_plan.csv"
    fields = [
        "stage_dir",
        "compression_allowed_in_this_run",
        "deletion_allowed_after_compression",
        "original_directory_retention_policy",
        "exclusion_reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for stage in stages:
            writer.writerow({
                "stage_dir": f"outputs/v21/{stage}",
                "compression_allowed_in_this_run": "False",
                "deletion_allowed_after_compression": "False",
                "original_directory_retention_policy": "KEEP_ORIGINAL_UNTIL_SEPARATE_MANUAL_APPROVAL",
                "exclusion_reason": "",
            })
    return path


def make_stage(root: Path, stage: str) -> Path:
    touch(root / f"outputs/v21/{stage}/data.csv", f"{stage},data")
    touch(root / f"outputs/v21/{stage}/nested/info.txt", "info")
    return root / f"outputs/v21/{stage}"


def make_repo(tmp_path: Path, stages: list[str] | None = None):
    module = load_module()
    root = tmp_path / "repo"
    stages = stages or APPROVED
    for stage in stages:
        make_stage(root, stage)
    plan = write_plan(root, stages)
    return module, root, plan


def test_only_three_approved_candidates_are_included(tmp_path):
    module, root, plan = make_repo(tmp_path, APPROVED + ["V21.999_NOT_APPROVED"])
    make_stage(root, "V21.999_NOT_APPROVED")
    summary = module.run(root, source_plan=plan)
    assert summary["approved_candidate_count"] == 3
    result = rows(root / module.OUT_REL / "zip_copy_creation_result.csv")
    assert {Path(r["stage_dir"]).name for r in result} == set(APPROVED)


def test_v21_140_excluded(tmp_path):
    stage = "V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020"
    module, root, plan = make_repo(tmp_path, [stage])
    summary = module.run(root, source_plan=plan)
    exclusions = rows(root / module.OUT_REL / "compression_exclusion_check.csv")
    assert summary["approved_candidate_count"] == 0
    assert exclusions[0]["exclusion_reason"] == "NOT_IN_APPROVED_STAGE_ALLOWLIST"


def test_v21_154_excluded(tmp_path):
    stage = "V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT"
    module, root, plan = make_repo(tmp_path, [stage])
    summary = module.run(root, source_plan=plan)
    assert summary["approved_candidate_count"] == 0


def test_sensitive_keyword_candidate_blocked(tmp_path):
    stage = "V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST"
    module, root, plan = make_repo(tmp_path, [stage])
    touch(root / f"outputs/v21/{stage}/canonical.csv", "blocked")
    summary = module.run(root, source_plan=plan)
    assert summary["approved_candidate_count"] == 0
    exclusions = rows(root / module.OUT_REL / "compression_exclusion_check.csv")
    assert exclusions[0]["exclusion_reason"] == "SENSITIVE_FILE_KEYWORD"


def test_one_zip_per_candidate_created(tmp_path):
    module, root, plan = make_repo(tmp_path)
    summary = module.run(root, source_plan=plan)
    assert summary["zip_created_count"] == 3
    for stage in APPROVED:
        assert (root / module.ZIP_REL / f"{stage}__V21.207_COMPRESS_ONLY_COPY.zip").is_file()


def test_zip_preserves_stage_dir_relative_paths(tmp_path):
    module, root, plan = make_repo(tmp_path, [APPROVED[0]])
    module.run(root, source_plan=plan)
    zpath = root / module.ZIP_REL / f"{APPROVED[0]}__V21.207_COMPRESS_ONLY_COPY.zip"
    with zipfile.ZipFile(zpath) as zf:
        names = set(zf.namelist())
    assert f"{APPROVED[0]}/data.csv" in names
    assert f"{APPROVED[0]}/nested/info.txt" in names


def test_zip_integrity_passes_and_source_unchanged(tmp_path):
    module, root, plan = make_repo(tmp_path, [APPROVED[0]])
    summary = module.run(root, source_plan=plan)
    assert summary["all_zip_integrity_passed"] is True
    assert summary["all_sources_unchanged_after"] is True
    integrity = rows(root / module.OUT_REL / "zip_copy_integrity_check.csv")
    assert integrity[0]["source_manifest_sha256_before"] == integrity[0]["source_manifest_sha256_after"]


def test_rerun_existing_valid_zip_skips_creation(tmp_path):
    module, root, plan = make_repo(tmp_path, [APPROVED[0]])
    module.run(root, source_plan=plan)
    summary = module.run(root, source_plan=plan)
    assert summary["zip_skipped_existing_valid_count"] == 1
    result = rows(root / module.OUT_REL / "zip_copy_creation_result.csv")
    assert result[0]["status"] == "SKIP_EXISTING_VALID_ZIP"


def test_existing_failed_zip_overwritten_with_reason(tmp_path):
    module, root, plan = make_repo(tmp_path, [APPROVED[0]])
    zpath = root / module.ZIP_REL / f"{APPROVED[0]}__V21.207_COMPRESS_ONLY_COPY.zip"
    touch(zpath, "not a zip")
    summary = module.run(root, source_plan=plan)
    result = rows(root / module.OUT_REL / "zip_copy_creation_result.csv")
    assert result[0]["overwrite_reason"] == "FAILED_PRIOR_INTEGRITY_CHECK"
    assert result[0]["zip_test_passed"] == "True"


def test_deletion_allowed_now_always_false(tmp_path):
    module, root, plan = make_repo(tmp_path, [APPROVED[0]])
    summary = module.run(root, source_plan=plan)
    assert summary["deletion_allowed_now"] is False
    result = rows(root / module.OUT_REL / "zip_copy_integrity_check.csv")
    assert result[0]["deletion_allowed_now"] == "False"


def test_no_source_mutation_behavior(tmp_path):
    module, root, plan = make_repo(tmp_path, [APPROVED[0]])
    source_file = root / f"outputs/v21/{APPROVED[0]}/data.csv"
    before = source_file.read_text(encoding="utf-8")
    module.run(root, source_plan=plan)
    assert source_file.read_text(encoding="utf-8") == before


def test_partial_zip_failure_produces_warn(tmp_path):
    module, root, plan = make_repo(tmp_path, [APPROVED[0]])
    summary = module.run(root, source_plan=plan, simulate_zip_failure_stage=APPROVED[0])
    assert summary["final_status"] == "WARN_V21_207_PARTIAL_ZIP_COPY_FAILURE"
    assert summary["final_decision"] == "ZIP_COPY_CREATION_PARTIAL_FAILURE_ORIGINALS_RETAINED"


def test_source_mutation_produces_fail(tmp_path):
    module, root, plan = make_repo(tmp_path, [APPROVED[0]])
    summary = module.run(root, source_plan=plan, simulate_source_mutation_stage=APPROVED[0])
    assert summary["final_status"] == "FAIL_V21_207_SOURCE_MUTATION_DETECTED"
    assert summary["final_decision"] == "ZIP_COPY_CREATION_FAILED_SOURCE_MUTATION"


def test_protected_candidate_inclusion_produces_fail(tmp_path):
    module, root, plan = make_repo(tmp_path, ["V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME"])
    summary = module.run(root, source_plan=plan, force_include_protected=True)
    assert summary["final_status"] == "FAIL_V21_207_PROTECTED_OR_CURRENT_CHAIN_CANDIDATE_INCLUDED"
    assert summary["final_decision"] == "ZIP_COPY_CREATION_BLOCKED_PROTECTED_CANDIDATE"


def test_summary_report_artifacts_written(tmp_path):
    module, root, plan = make_repo(tmp_path, [APPROVED[0]])
    summary = module.run(root, source_plan=plan)
    out = root / module.OUT_REL
    for name in [
        "v21_207_summary.json",
        "V21.207_compress_only_zip_copy_creation_report.txt",
        "zip_copy_creation_result.csv",
        "zip_copy_integrity_check.csv",
        "source_directory_postcheck.csv",
        "zip_file_manifest.csv",
        "compression_exclusion_check.csv",
    ]:
        assert (out / name).is_file()
    assert summary["deletion_performed"] is False
    assert summary["archive_movement_performed"] is False
    assert summary["broker_action_allowed"] is False


def test_unhandled_exception_produces_fail(tmp_path):
    module, root, plan = make_repo(tmp_path, [APPROVED[0]])
    summary = module.run(root, source_plan=plan, simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_207_ZIP_COPY_EXCEPTION"
    assert summary["final_decision"] == "ZIP_COPY_CREATION_FAILED"


def test_wrapper_exists_and_uses_venv_python():
    assert WRAPPER.is_file()
    text = WRAPPER.read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in text
    assert "v21_207_compress_only_zip_copy_creation.py" in text
