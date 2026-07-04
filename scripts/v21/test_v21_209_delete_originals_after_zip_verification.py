from __future__ import annotations

import csv
import importlib.util
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_209_delete_originals_after_zip_verification.py"
WRAPPER = ROOT / "scripts/v21/run_v21_209_delete_originals_after_zip_verification.ps1"
APPROVED = [
    "V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST",
    "V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST",
    "V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY",
]


def load_module():
    spec = importlib.util.spec_from_file_location("v21_209", SCRIPT)
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


def write_csv(path: Path, data: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(data)


def make_stage(root: Path, stage: str) -> Path:
    touch(root / f"outputs/v21/{stage}/data.csv", f"{stage},data")
    touch(root / f"outputs/v21/{stage}/nested/info.txt", "info")
    return root / f"outputs/v21/{stage}"


def make_zip(root: Path, stage: str) -> Path:
    source = root / f"outputs/v21/{stage}"
    zpath = root / f"archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION/{stage}__V21.207_COMPRESS_ONLY_COPY.zip"
    zpath.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in sorted([p for p in source.rglob("*") if p.is_file()], key=lambda p: p.relative_to(source).as_posix()):
            zf.write(file, f"{stage}/{file.relative_to(source).as_posix()}")
    return zpath


def add_protected_paths(root: Path) -> None:
    touch(root / ".venv/Scripts/python.exe", "python")
    touch(root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv", "date,close")
    touch(root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/summary.json", "{}")
    touch(root / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/summary.json", "{}")
    touch(root / "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/summary.json", "{}")
    touch(root / "outputs/v21/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION/v21_207_summary.json", "{}")
    touch(root / "outputs/v21/V21.208_ORIGINAL_REMOVAL_DRY_RUN_APPROVAL_GATE/v21_208_summary.json", "{}")
    touch(root / "archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION/.keep", "")


def make_repo(tmp_path: Path, stages: list[str] | None = None, protected: bool = True):
    module = load_module()
    root = tmp_path / "repo"
    stages = stages or APPROVED
    if protected:
        add_protected_paths(root)
    plan_rows = []
    v207_rows = []
    for stage in stages:
        make_stage(root, stage)
        zpath = make_zip(root, stage)
        sdir = f"outputs/v21/{stage}"
        plan_rows.append({
            "stage_dir": sdir,
            "source_path": str(root / sdir),
            "zip_file_path": str(zpath),
            "source_exists": "True",
            "zip_exists": "True",
            "zip_test_passed": "True",
            "integrity_recheck_passed": "True",
            "eligible_for_future_deletion": "True",
        })
        v207_rows.append({
            "stage_dir": sdir,
            "zip_file_path": str(zpath),
            "zip_exists": "True",
            "zip_test_passed": "True",
            "source_still_exists_after": "True",
            "source_unchanged_after": "True",
            "deletion_allowed_now": "False",
        })
    plan_fields = ["stage_dir", "source_path", "zip_file_path", "source_exists", "zip_exists", "zip_test_passed", "integrity_recheck_passed", "eligible_for_future_deletion"]
    v207_fields = ["stage_dir", "zip_file_path", "zip_exists", "zip_test_passed", "source_still_exists_after", "source_unchanged_after", "deletion_allowed_now"]
    plan_csv = root / "v208_plan.csv"
    integrity_csv = root / "v207_integrity.csv"
    write_csv(plan_csv, plan_rows, plan_fields)
    write_csv(integrity_csv, v207_rows, v207_fields)
    return module, root, plan_csv, integrity_csv


def run_approved(module, root, plan_csv, integrity_csv, **kwargs):
    return module.run(root, approval_phrase=module.APPROVAL_PHRASE, v208_plan=plan_csv, v207_integrity=integrity_csv, **kwargs)


def test_missing_approval_phrase_blocks_deletion(tmp_path):
    module, root, plan_csv, integrity_csv = make_repo(tmp_path, [APPROVED[0]])
    summary = module.run(root, v208_plan=plan_csv, v207_integrity=integrity_csv)
    assert summary["final_status"] == "FAIL_V21_209_MANUAL_APPROVAL_MISSING"
    assert (root / f"outputs/v21/{APPROVED[0]}").is_dir()


def test_wrong_approval_phrase_blocks_deletion(tmp_path):
    module, root, plan_csv, integrity_csv = make_repo(tmp_path, [APPROVED[0]])
    summary = module.run(root, approval_phrase="WRONG", v208_plan=plan_csv, v207_integrity=integrity_csv)
    assert summary["final_decision"] == "DELETE_ORIGINALS_BLOCKED_MANUAL_APPROVAL_MISSING"
    assert (root / f"outputs/v21/{APPROVED[0]}").is_dir()


def test_exact_approval_phrase_allows_only_eligible_candidates(tmp_path):
    module, root, plan_csv, integrity_csv = make_repo(tmp_path, APPROVED + ["V21.999_OTHER"])
    summary = run_approved(module, root, plan_csv, integrity_csv)
    assert summary["approved_candidate_count"] == 3
    assert not (root / f"outputs/v21/{APPROVED[0]}").exists()
    assert (root / "outputs/v21/V21.999_OTHER").is_dir()


def test_only_three_approved_originals_can_be_deleted(tmp_path):
    module, root, plan_csv, integrity_csv = make_repo(tmp_path, APPROVED)
    summary = run_approved(module, root, plan_csv, integrity_csv)
    assert summary["deleted_count"] == 3
    for stage in APPROVED:
        assert not (root / f"outputs/v21/{stage}").exists()


def test_v21_140_excluded(tmp_path):
    stage = "V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020"
    module, root, plan_csv, integrity_csv = make_repo(tmp_path, [stage])
    summary = run_approved(module, root, plan_csv, integrity_csv)
    assert summary["final_status"] == "FAIL_V21_209_PROTECTED_OR_CURRENT_CHAIN_BLOCKER"
    assert (root / f"outputs/v21/{stage}").is_dir()


def test_v21_154_excluded(tmp_path):
    stage = "V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT"
    module, root, plan_csv, integrity_csv = make_repo(tmp_path, [stage])
    summary = run_approved(module, root, plan_csv, integrity_csv)
    assert summary["final_status"] == "FAIL_V21_209_PROTECTED_OR_CURRENT_CHAIN_BLOCKER"
    assert (root / f"outputs/v21/{stage}").is_dir()


def test_sensitive_keyword_candidate_blocked(tmp_path):
    module, root, plan_csv, integrity_csv = make_repo(tmp_path, [APPROVED[0]])
    touch(root / f"outputs/v21/{APPROVED[0]}/canonical.csv", "blocked")
    summary = run_approved(module, root, plan_csv, integrity_csv)
    assert summary["final_status"] == "FAIL_V21_209_PROTECTED_OR_CURRENT_CHAIN_BLOCKER"
    assert (root / f"outputs/v21/{APPROVED[0]}").is_dir()


def test_zip_missing_blocks_deletion(tmp_path):
    module, root, plan_csv, integrity_csv = make_repo(tmp_path, [APPROVED[0]])
    for zpath in (root / "archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION").glob("*.zip"):
        zpath.unlink()
    summary = run_approved(module, root, plan_csv, integrity_csv)
    assert summary["final_status"] == "FAIL_V21_209_ZIP_INTEGRITY_FAILED"
    assert (root / f"outputs/v21/{APPROVED[0]}").is_dir()


def test_zip_integrity_failure_blocks_deletion(tmp_path):
    module, root, plan_csv, integrity_csv = make_repo(tmp_path, [APPROVED[0]])
    zpath = next((root / "archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION").glob("*.zip"))
    zpath.write_text("not a zip", encoding="utf-8")
    summary = run_approved(module, root, plan_csv, integrity_csv)
    assert summary["final_status"] == "FAIL_V21_209_ZIP_INTEGRITY_FAILED"
    assert (root / f"outputs/v21/{APPROVED[0]}").is_dir()


def test_protected_path_missing_blocks_or_fails(tmp_path):
    module, root, plan_csv, integrity_csv = make_repo(tmp_path, [APPROVED[0]], protected=False)
    summary = run_approved(module, root, plan_csv, integrity_csv)
    assert summary["final_status"] == "FAIL_V21_209_PROTECTED_PATH_MISSING_AFTER"
    assert (root / f"outputs/v21/{APPROVED[0]}").is_dir()


def test_successful_deletion_removes_originals_but_keeps_zip_files(tmp_path):
    module, root, plan_csv, integrity_csv = make_repo(tmp_path, APPROVED)
    summary = run_approved(module, root, plan_csv, integrity_csv)
    assert summary["final_status"] == "PASS_V21_209_ORIGINALS_DELETED_AFTER_ZIP_VERIFICATION"
    for stage in APPROVED:
        assert not (root / f"outputs/v21/{stage}").exists()
        assert (root / f"archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION/{stage}__V21.207_COMPRESS_ONLY_COPY.zip").is_file()


def test_zip_integrity_passes_after_deletion(tmp_path):
    module, root, plan_csv, integrity_csv = make_repo(tmp_path, [APPROVED[0]])
    summary = run_approved(module, root, plan_csv, integrity_csv)
    assert summary["all_zip_integrity_passed_after"] is True
    result = rows(root / module.OUT_REL / "deletion_execution_result.csv")
    assert result[0]["post_delete_zip_test_passed"] == "True"


def test_protected_paths_remain_present_after_deletion(tmp_path):
    module, root, plan_csv, integrity_csv = make_repo(tmp_path, [APPROVED[0]])
    summary = run_approved(module, root, plan_csv, integrity_csv)
    assert summary["all_protected_paths_present_after"] is True
    assert (root / ".venv").exists()
    assert (root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv").is_file()


def test_partial_access_denied_deletion_returns_warn(tmp_path):
    module, root, plan_csv, integrity_csv = make_repo(tmp_path, APPROVED)
    summary = run_approved(module, root, plan_csv, integrity_csv, simulate_delete_failure_stage=APPROVED[0])
    assert summary["final_status"] == "WARN_V21_209_PARTIAL_DELETE_WITH_ORIGINALS_RETAINED_OR_SKIPPED"
    assert (root / f"outputs/v21/{APPROVED[0]}").is_dir()


def test_summary_report_artifacts_written(tmp_path):
    module, root, plan_csv, integrity_csv = make_repo(tmp_path, [APPROVED[0]])
    summary = run_approved(module, root, plan_csv, integrity_csv)
    out = root / module.OUT_REL
    for name in [
        "v21_209_summary.json",
        "V21.209_delete_originals_after_zip_verification_report.txt",
        "deletion_execution_result.csv",
        "pre_delete_zip_integrity_recheck.csv",
        "pre_delete_source_manifest.csv",
        "post_delete_presence_check.csv",
        "protected_path_presence_check.csv",
        "deletion_blocker_check.csv",
    ]:
        assert (out / name).is_file()
    payload = json.loads((out / "v21_209_summary.json").read_text(encoding="utf-8"))
    assert payload["final_status"] == summary["final_status"]
    assert payload["zip_archives_deleted"] is False


def test_unhandled_exception_produces_fail(tmp_path):
    module, root, plan_csv, integrity_csv = make_repo(tmp_path, [APPROVED[0]])
    summary = module.run(root, approval_phrase=module.APPROVAL_PHRASE, v208_plan=plan_csv, v207_integrity=integrity_csv, simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_209_DELETE_EXCEPTION"
    assert summary["final_decision"] == "DELETE_ORIGINALS_FAILED"
    assert (root / f"outputs/v21/{APPROVED[0]}").is_dir()


def test_wrapper_exists_and_references_venv_python():
    assert WRAPPER.is_file()
    text = WRAPPER.read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in text
    assert "v21_209_delete_originals_after_zip_verification.py" in text
