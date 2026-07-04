from __future__ import annotations

import csv
import importlib.util
import zipfile
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_215_cold_archive_zip_copy_creation_for_v21_154.py")
spec = importlib.util.spec_from_file_location("v21_215", MODULE_PATH)
v215 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v215)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def make_repo(tmp_path: Path, *, protected: bool = True, plan_stage: str = v215.APPROVED_STAGE) -> Path:
    root = tmp_path / "repo"
    (root / ".venv/Scripts").mkdir(parents=True)
    (root / ".venv/Scripts/python.exe").write_text("python", encoding="utf-8")
    if protected:
        (root / "outputs/v20/price_history").mkdir(parents=True)
        (root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv").write_text("x\n", encoding="utf-8")
        for name in [
            "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
            "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
            "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
            "V21.212_ARTIFACT_ROLE_REGISTRY_AND_RETENTION_POLICY",
            "V21.214_LARGE_OUTPUTS_COLD_ARCHIVE_CANDIDATE_PLAN",
            v215.APPROVED_STAGE,
        ]:
            (root / "outputs/v21" / name).mkdir(parents=True, exist_ok=True)
    source = root / "outputs/v21" / v215.APPROVED_STAGE
    source.mkdir(parents=True, exist_ok=True)
    (source / "a.csv").write_text("alpha\n", encoding="utf-8")
    (source / "nested").mkdir(exist_ok=True)
    (source / "nested/b.json").write_text('{"b": 2}\n', encoding="utf-8")
    write_plan(root, plan_stage)
    return root


def write_plan(root: Path, stage: str, *, tier: str = "TIER_A_COLD_ARCHIVE_RETAIN_EVIDENCE", action: str = "ZIP_COPY_ONLY_NEXT_STAGE") -> None:
    path = root / v215.PLAN_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["stage_dir", "cold_archive_candidate_tier", "future_action_plan", "compression_allowed_in_this_run", "deletion_allowed_in_this_run"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow({
            "stage_dir": stage,
            "cold_archive_candidate_tier": tier,
            "future_action_plan": action,
            "compression_allowed_in_this_run": "False",
            "deletion_allowed_in_this_run": "False",
        })


def test_only_v21_154_is_included(tmp_path):
    root = make_repo(tmp_path, plan_stage="V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020")
    summary = v215.run(root, out_dir=root / "out")
    assert summary["final_status"] == "WARN_V21_215_COLD_ARCHIVE_ZIP_COPY_FAILED_SOURCE_RETAINED"
    assert summary["approved_candidate_count"] == 0


def test_v21_140_excluded(tmp_path):
    assert v215.hard_exclusion_reason("V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020") == "HARDCODED_EXCLUSION"


def test_protected_current_chain_stages_excluded():
    assert v215.hard_exclusion_reason("V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT") == "HARDCODED_EXCLUSION"
    assert v215.hard_exclusion_reason("V21.214_LARGE_OUTPUTS_COLD_ARCHIVE_CANDIDATE_PLAN") == "CLEANUP_OR_CURRENT_CHAIN_EXCLUSION"


def test_one_zip_created_for_v21_154_and_preserves_stage_relative_paths(tmp_path):
    root = make_repo(tmp_path)
    summary = v215.run(root, out_dir=root / "out")
    assert summary["final_status"] == "PASS_V21_215_COLD_ARCHIVE_ZIP_COPY_READY"
    assert summary["zip_created_count"] == 1
    zpath = root / v215.ZIP_REL / v215.ZIP_NAME
    assert zpath.exists()
    with zipfile.ZipFile(zpath) as zf:
        names = sorted(zf.namelist())
    assert names == [
        f"{v215.APPROVED_STAGE}/a.csv",
        f"{v215.APPROVED_STAGE}/nested/b.json",
    ]


def test_zip_integrity_passes_and_source_remains_present(tmp_path):
    root = make_repo(tmp_path)
    summary = v215.run(root, out_dir=root / "out")
    assert summary["zip_integrity_passed"] is True
    assert summary["source_unchanged_after"] is True
    assert (root / "outputs/v21" / v215.APPROVED_STAGE).exists()


def test_source_manifest_before_after_unchanged(tmp_path):
    root = make_repo(tmp_path)
    v215.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/source_directory_postcheck.csv")
    assert rows[0]["source_unchanged_after"] == "True"
    assert rows[0]["source_file_count_after"] == "2"


def test_rerun_existing_valid_zip_skips_creation(tmp_path):
    root = make_repo(tmp_path)
    v215.run(root, out_dir=root / "out1")
    summary = v215.run(root, out_dir=root / "out2")
    assert summary["final_status"] == "PASS_V21_215_COLD_ARCHIVE_ZIP_COPY_READY"
    assert summary["zip_skipped_existing_valid_count"] == 1
    assert summary["compression_performed"] is False


def test_failed_existing_zip_can_be_overwritten_with_reason(tmp_path):
    root = make_repo(tmp_path)
    zpath = root / v215.ZIP_REL / v215.ZIP_NAME
    zpath.parent.mkdir(parents=True, exist_ok=True)
    zpath.write_text("not a zip", encoding="utf-8")
    summary = v215.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/cold_archive_zip_copy_result.csv")
    assert summary["final_status"] == "PASS_V21_215_COLD_ARCHIVE_ZIP_COPY_READY"
    assert rows[0]["overwrite_reason"] == "FAILED_PRIOR_INTEGRITY_CHECK"


def test_deletion_allowed_now_always_false(tmp_path):
    root = make_repo(tmp_path)
    summary = v215.run(root, out_dir=root / "out")
    assert summary["deletion_allowed_now"] is False
    rows = read_csv(root / "out/cold_archive_zip_integrity_check.csv")
    assert rows[0]["deletion_allowed_now"] == "False"


def test_source_mutation_produces_fail(tmp_path):
    root = make_repo(tmp_path)
    summary = v215.run(root, out_dir=root / "out", simulate_source_mutation=True)
    assert summary["final_status"] == "FAIL_V21_215_SOURCE_MUTATION_DETECTED"


def test_protected_path_missing_produces_fail(tmp_path):
    root = make_repo(tmp_path, protected=False)
    summary = v215.run(root, out_dir=root / "out")
    assert summary["final_status"] == "FAIL_V21_215_PROTECTED_PATH_MISSING"


def test_summary_report_artifacts_written(tmp_path):
    root = make_repo(tmp_path)
    out = root / "out"
    v215.run(root, out_dir=out)
    for name in [
        "v21_215_summary.json",
        "V21.215_cold_archive_zip_copy_creation_report.txt",
        "cold_archive_zip_copy_result.csv",
        "cold_archive_zip_integrity_check.csv",
        "source_directory_pre_manifest.csv",
        "source_directory_postcheck.csv",
        "zip_file_manifest.csv",
        "protected_path_presence_check.csv",
        "v21_154_audit_evidence_retention_note.txt",
    ]:
        assert (out / name).exists()


def test_unhandled_exception_produces_fail(tmp_path):
    root = make_repo(tmp_path)
    summary = v215.run(root, out_dir=root / "out", simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_215_COLD_ARCHIVE_ZIP_EXCEPTION"
    assert summary["deletion_performed"] is False
