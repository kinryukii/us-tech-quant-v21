from __future__ import annotations

import csv
import importlib.util
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_210_post_cleanup_size_and_integrity_reconciliation.py"
WRAPPER = ROOT / "scripts/v21/run_v21_210_post_cleanup_size_and_integrity_reconciliation.ps1"
DELETED = [
    "V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST",
    "V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST",
    "V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY",
]


def load_module():
    spec = importlib.util.spec_from_file_location("v21_210", SCRIPT)
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


def source_digest(files: dict[str, str]) -> tuple[str, int, int]:
    import hashlib

    digest = hashlib.sha256()
    total = 0
    for rel_path, text in sorted(files.items()):
        data = text.encode("utf-8")
        file_hash = hashlib.sha256(data).hexdigest()
        total += len(data)
        digest.update(f"{rel_path}\t{len(data)}\t{file_hash}\n".encode("utf-8"))
    return digest.hexdigest(), len(files), total


def make_zip(root: Path, stage: str, files: dict[str, str]) -> tuple[Path, str, int, int]:
    zpath = root / f"archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION/{stage}__V21.207_COMPRESS_ONLY_COPY.zip"
    zpath.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel_path, text in sorted(files.items()):
            zf.writestr(f"{stage}/{rel_path}", text)
    digest, count, total = source_digest(files)
    return zpath, digest, count, total


def add_protected_paths(root: Path, alias_201: bool = False) -> None:
    touch(root / ".venv/Scripts/python.exe", "python")
    touch(root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv", "date,close")
    touch(root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/summary.json", "{}")
    touch(root / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/summary.json", "{}")
    if alias_201:
        touch(root / "outputs/v21/V21.201_DAILY_DRAM_PLAN_ALIAS/summary.json", "{}")
    else:
        touch(root / "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/summary.json", "{}")
    touch(root / "outputs/v21/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION/v21_207_summary.json", "{}")
    touch(root / "outputs/v21/V21.208_ORIGINAL_REMOVAL_DRY_RUN_APPROVAL_GATE/v21_208_summary.json", "{}")
    touch(root / "outputs/v21/V21.209_DELETE_ORIGINALS_AFTER_ZIP_VERIFICATION/v21_209_summary.json", "{}")


def make_repo(tmp_path: Path, protected: bool = True, alias_201: bool = False, v209_pass: bool = True, leave_original: bool = False):
    module = load_module()
    root = tmp_path / "repo"
    if protected:
        add_protected_paths(root, alias_201=alias_201)
    result_rows = []
    deleted_size = 0
    for stage in DELETED:
        files = {"data.csv": f"{stage},data", "nested/info.txt": "info"}
        zpath, digest, count, total = make_zip(root, stage, files)
        deleted_size += total
        if leave_original:
            for rel_path, text in files.items():
                touch(root / f"outputs/v21/{stage}/{rel_path}", text)
        result_rows.append({
            "stage_dir": f"outputs/v21/{stage}",
            "zip_file_path": str(zpath),
            "pre_delete_source_manifest_sha256": digest,
            "pre_delete_source_size_bytes": total,
            "deletion_status": "DELETED_ORIGINAL",
            "deleted_size_bytes": total,
            "post_delete_source_exists": "False",
            "post_delete_zip_exists": "True",
            "post_delete_zip_test_passed": "True",
        })
    summary = {
        "final_status": module.V209_PASS if v209_pass else "WARN_OTHER",
        "deleted_size_bytes": deleted_size,
        "deleted_count": 3,
    }
    summary_path = root / "v209_summary.json"
    result_path = root / "v209_result.csv"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    fields = ["stage_dir", "zip_file_path", "pre_delete_source_manifest_sha256", "pre_delete_source_size_bytes", "deletion_status", "deleted_size_bytes", "post_delete_source_exists", "post_delete_zip_exists", "post_delete_zip_test_passed"]
    write_csv(result_path, result_rows, fields)
    return module, root, summary_path, result_path


def test_v21_209_pass_status_detected(tmp_path):
    module, root, summary_path, result_path = make_repo(tmp_path)
    summary = module.run(root, v209_summary_path=summary_path, v209_result_path=result_path)
    chain = rows(root / module.OUT_REL / "cleanup_chain_reconciliation.csv")
    assert summary["final_status"] == "PASS_V21_210_POST_CLEANUP_RECONCILIATION_READY"
    assert [row for row in chain if row["check_name"] == "v21_209_final_status"][0]["check_passed"] == "True"


def test_all_three_deleted_originals_absent(tmp_path):
    module, root, summary_path, result_path = make_repo(tmp_path)
    summary = module.run(root, v209_summary_path=summary_path, v209_result_path=result_path)
    assert summary["deleted_original_missing_count"] == 3
    assert summary["deleted_original_still_present_count"] == 0


def test_any_deleted_original_still_present_produces_warn(tmp_path):
    module, root, summary_path, result_path = make_repo(tmp_path, leave_original=True)
    summary = module.run(root, v209_summary_path=summary_path, v209_result_path=result_path)
    assert summary["final_status"] == "WARN_V21_210_RECONCILIATION_MISMATCH"
    assert summary["deleted_original_still_present_count"] == 3


def test_all_three_zip_archives_exist_and_pass_integrity(tmp_path):
    module, root, summary_path, result_path = make_repo(tmp_path)
    summary = module.run(root, v209_summary_path=summary_path, v209_result_path=result_path)
    assert summary["zip_archive_present_count"] == 3
    assert summary["zip_integrity_pass_count"] == 3


def test_missing_zip_produces_fail(tmp_path):
    module, root, summary_path, result_path = make_repo(tmp_path)
    next((root / "archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION").glob("*.zip")).unlink()
    summary = module.run(root, v209_summary_path=summary_path, v209_result_path=result_path)
    assert summary["final_status"] == "FAIL_V21_210_PROTECTED_PATH_OR_ZIP_MISSING"


def test_zip_integrity_failure_produces_fail(tmp_path):
    module, root, summary_path, result_path = make_repo(tmp_path)
    next((root / "archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION").glob("*.zip")).write_text("bad", encoding="utf-8")
    summary = module.run(root, v209_summary_path=summary_path, v209_result_path=result_path)
    assert summary["final_status"] == "FAIL_V21_210_PROTECTED_PATH_OR_ZIP_MISSING"


def test_protected_path_alias_support_for_v21_201(tmp_path):
    module, root, summary_path, result_path = make_repo(tmp_path, alias_201=True)
    summary = module.run(root, v209_summary_path=summary_path, v209_result_path=result_path)
    presence = rows(root / module.OUT_REL / "protected_path_presence_check.csv")
    row201 = [row for row in presence if row["protected_key"].startswith("V21.201")][0]
    assert summary["final_status"] == "PASS_V21_210_POST_CLEANUP_RECONCILIATION_READY"
    assert row201["resolution_method"] == "ALIAS_DISCOVERY_NEWEST_MODIFIED"


def test_missing_protected_path_produces_fail(tmp_path):
    module, root, summary_path, result_path = make_repo(tmp_path, protected=False)
    summary = module.run(root, v209_summary_path=summary_path, v209_result_path=result_path)
    assert summary["final_status"] == "FAIL_V21_210_PROTECTED_PATH_OR_ZIP_MISSING"
    assert summary["protected_path_missing_count"] > 0


def test_repo_size_summary_written(tmp_path):
    module, root, summary_path, result_path = make_repo(tmp_path)
    module.run(root, v209_summary_path=summary_path, v209_result_path=result_path)
    assert (root / module.OUT_REL / "post_cleanup_repo_size_summary.csv").is_file()


def test_cleanup_chain_reconciliation_written(tmp_path):
    module, root, summary_path, result_path = make_repo(tmp_path)
    module.run(root, v209_summary_path=summary_path, v209_result_path=result_path)
    assert (root / module.OUT_REL / "cleanup_chain_reconciliation.csv").is_file()


def test_no_mutation_behavior(tmp_path):
    module, root, summary_path, result_path = make_repo(tmp_path)
    zip_paths = sorted((root / "archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION").glob("*.zip"))
    before = {path.name: path.stat().st_size for path in zip_paths}
    module.run(root, v209_summary_path=summary_path, v209_result_path=result_path)
    after = {path.name: path.stat().st_size for path in zip_paths}
    assert before == after


def test_summary_report_artifacts_written(tmp_path):
    module, root, summary_path, result_path = make_repo(tmp_path)
    summary = module.run(root, v209_summary_path=summary_path, v209_result_path=result_path)
    out = root / module.OUT_REL
    for name in [
        "v21_210_summary.json",
        "V21.210_post_cleanup_reconciliation_report.txt",
        "post_cleanup_repo_size_summary.csv",
        "deleted_original_presence_check.csv",
        "zip_archive_integrity_recheck.csv",
        "protected_path_presence_check.csv",
        "cleanup_chain_reconciliation.csv",
    ]:
        assert (out / name).is_file()
    payload = json.loads((out / "v21_210_summary.json").read_text(encoding="utf-8"))
    assert payload["final_status"] == summary["final_status"]
    assert payload["deletion_performed"] is False


def test_unhandled_exception_produces_fail(tmp_path):
    module, root, summary_path, result_path = make_repo(tmp_path)
    summary = module.run(root, v209_summary_path=summary_path, v209_result_path=result_path, simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_210_RECONCILIATION_EXCEPTION"
    assert summary["final_decision"] == "POST_CLEANUP_RECONCILIATION_FAILED"


def test_wrapper_exists_and_references_venv_python():
    assert WRAPPER.is_file()
    text = WRAPPER.read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in text
    assert "v21_210_post_cleanup_size_and_integrity_reconciliation.py" in text
