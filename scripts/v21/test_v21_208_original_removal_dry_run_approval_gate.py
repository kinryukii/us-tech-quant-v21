from __future__ import annotations

import csv
import importlib.util
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/v21/v21_208_original_removal_dry_run_approval_gate.py"
WRAPPER = ROOT / "scripts/v21/run_v21_208_original_removal_dry_run_approval_gate.ps1"
ELIGIBLE = [
    "V21.141_EXTENDED_2020_MULTI_STRATEGY_RANDOM_BACKTEST",
    "V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST",
    "V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY",
]


def load_module():
    spec = importlib.util.spec_from_file_location("v21_208", SCRIPT)
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


def add_protected_paths(root: Path, alias_201: bool = False) -> None:
    touch(root / ".venv/Scripts/python.exe", "python")
    touch(root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv", "date,close")
    touch(root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/summary.json", "{}")
    touch(root / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/summary.json", "{}")
    if alias_201:
        touch(root / "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/summary.json", "{}")
    else:
        touch(root / "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/summary.json", "{}")
    touch(root / "outputs/v21/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION/v21_207_summary.json", "{}")
    touch(root / "archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION/.keep", "")


def make_repo(tmp_path: Path, stages: list[str] | None = None, protected: bool = True):
    module = load_module()
    root = tmp_path / "repo"
    stages = stages or ELIGIBLE
    if protected:
        add_protected_paths(root)
    result_rows = []
    for stage in stages:
        make_stage(root, stage)
        zpath = make_zip(root, stage)
        result_rows.append({
            "stage_dir": f"outputs/v21/{stage}",
            "zip_file_path": str(zpath),
            "zip_test_passed": "True",
            "source_unchanged_after": "True",
            "deletion_allowed_now": "False",
            "source_still_exists_after": "True",
        })
    fields = ["stage_dir", "zip_file_path", "zip_test_passed", "source_unchanged_after", "deletion_allowed_now", "source_still_exists_after"]
    result_csv = root / "v207_result.csv"
    integrity_csv = root / "v207_integrity.csv"
    write_csv(result_csv, result_rows, fields)
    write_csv(integrity_csv, result_rows, fields)
    return module, root, result_csv, integrity_csv


def test_only_three_eligible_v207_zip_backed_originals_considered(tmp_path):
    module, root, result_csv, integrity_csv = make_repo(tmp_path, ELIGIBLE + ["V21.999_OTHER"])
    summary = module.run(root, result_csv=result_csv, integrity_csv=integrity_csv)
    assert summary["candidates_from_v21_207"] == 4
    assert summary["candidates_after_hard_exclusions"] == 3
    plan = rows(root / module.OUT_REL / "original_removal_dry_run_approval_plan.csv")
    assert {Path(row["stage_dir"]).name for row in plan} == set(ELIGIBLE)


def test_v21_140_excluded(tmp_path):
    module, root, result_csv, integrity_csv = make_repo(tmp_path, ["V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020"])
    summary = module.run(root, result_csv=result_csv, integrity_csv=integrity_csv)
    assert summary["candidates_after_hard_exclusions"] == 0


def test_v21_154_excluded(tmp_path):
    module, root, result_csv, integrity_csv = make_repo(tmp_path, ["V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT"])
    summary = module.run(root, result_csv=result_csv, integrity_csv=integrity_csv)
    assert summary["candidates_after_hard_exclusions"] == 0


def test_sensitive_keyword_candidate_blocked(tmp_path):
    module, root, result_csv, integrity_csv = make_repo(tmp_path, [ELIGIBLE[0]])
    touch(root / f"outputs/v21/{ELIGIBLE[0]}/canonical.csv", "blocked")
    summary = module.run(root, result_csv=result_csv, integrity_csv=integrity_csv)
    assert summary["final_status"] == "FAIL_V21_208_PROTECTED_OR_CURRENT_CHAIN_BLOCKER"
    plan = rows(root / module.OUT_REL / "original_removal_dry_run_approval_plan.csv")
    assert plan[0]["sensitive_keyword_blocker_count"] != "0"


def test_integrity_recheck_pass_produces_eligible_true(tmp_path):
    module, root, result_csv, integrity_csv = make_repo(tmp_path, [ELIGIBLE[0]])
    summary = module.run(root, result_csv=result_csv, integrity_csv=integrity_csv)
    assert summary["final_status"] == "PASS_V21_208_ORIGINAL_REMOVAL_DRY_RUN_READY"
    plan = rows(root / module.OUT_REL / "original_removal_dry_run_approval_plan.csv")
    assert plan[0]["eligible_for_future_deletion"] == "True"


def test_zip_missing_produces_fail_integrity(tmp_path):
    module, root, result_csv, integrity_csv = make_repo(tmp_path, [ELIGIBLE[0]])
    for zpath in (root / "archive/v21_compressed_stage_copies/V21.207_COMPRESS_ONLY_ZIP_COPY_CREATION").glob("*.zip"):
        zpath.unlink()
    summary = module.run(root, result_csv=result_csv, integrity_csv=integrity_csv)
    assert summary["final_status"] == "FAIL_V21_208_INTEGRITY_RECHECK_FAILED"


def test_source_missing_produces_fail_integrity(tmp_path):
    module, root, result_csv, integrity_csv = make_repo(tmp_path, [ELIGIBLE[0]])
    for file in (root / f"outputs/v21/{ELIGIBLE[0]}").rglob("*"):
        if file.is_file():
            file.unlink()
    for directory in sorted((root / f"outputs/v21/{ELIGIBLE[0]}").rglob("*"), reverse=True):
        if directory.is_dir():
            directory.rmdir()
    (root / f"outputs/v21/{ELIGIBLE[0]}").rmdir()
    summary = module.run(root, result_csv=result_csv, integrity_csv=integrity_csv)
    assert summary["final_status"] == "FAIL_V21_208_INTEGRITY_RECHECK_FAILED"


def test_source_zip_manifest_mismatch_produces_fail_integrity(tmp_path):
    module, root, result_csv, integrity_csv = make_repo(tmp_path, [ELIGIBLE[0]])
    touch(root / f"outputs/v21/{ELIGIBLE[0]}/extra.txt", "new")
    summary = module.run(root, result_csv=result_csv, integrity_csv=integrity_csv)
    assert summary["final_status"] == "FAIL_V21_208_INTEGRITY_RECHECK_FAILED"


def test_deletion_allowed_in_this_run_always_false(tmp_path):
    module, root, result_csv, integrity_csv = make_repo(tmp_path, [ELIGIBLE[0]])
    summary = module.run(root, result_csv=result_csv, integrity_csv=integrity_csv)
    plan = rows(root / module.OUT_REL / "original_removal_dry_run_approval_plan.csv")
    assert summary["deletion_allowed_in_this_run"] is False
    assert plan[0]["deletion_allowed_in_this_run"] == "False"


def test_required_manual_approval_phrase_present(tmp_path):
    module, root, result_csv, integrity_csv = make_repo(tmp_path, [ELIGIBLE[0]])
    summary = module.run(root, result_csv=result_csv, integrity_csv=integrity_csv)
    assert summary["required_manual_approval_phrase"] == module.APPROVAL_PHRASE
    checklist = rows(root / module.OUT_REL / "manual_approval_checklist.csv")
    assert any(row["required_value"] == module.APPROVAL_PHRASE for row in checklist)


def test_protected_path_alias_support_for_v21_201(tmp_path):
    module, root, result_csv, integrity_csv = make_repo(tmp_path, [ELIGIBLE[0]], protected=False)
    add_protected_paths(root, alias_201=True)
    exact = root / "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH"
    exact.rename(root / "outputs/v21/V21.201_DAILY_DRAM_PLAN_ALIAS")
    summary = module.run(root, result_csv=result_csv, integrity_csv=integrity_csv)
    presence = rows(root / module.OUT_REL / "protected_path_presence_check.csv")
    row201 = [row for row in presence if row["protected_key"].startswith("V21.201")][0]
    assert summary["final_status"] == "PASS_V21_208_ORIGINAL_REMOVAL_DRY_RUN_READY"
    assert row201["resolution_method"] == "ALIAS_DISCOVERY_NEWEST_MODIFIED"
    assert row201["resolved_exists"] == "True"


def test_protected_path_missing_produces_blocker(tmp_path):
    module, root, result_csv, integrity_csv = make_repo(tmp_path, [ELIGIBLE[0]], protected=False)
    summary = module.run(root, result_csv=result_csv, integrity_csv=integrity_csv)
    assert summary["final_status"] == "FAIL_V21_208_PROTECTED_OR_CURRENT_CHAIN_BLOCKER"
    blockers = rows(root / module.OUT_REL / "source_deletion_blocker_check.csv")
    assert any(row["blocker_type"] == "PROTECTED_PATH_MISSING" for row in blockers)


def test_summary_report_artifacts_written(tmp_path):
    module, root, result_csv, integrity_csv = make_repo(tmp_path, [ELIGIBLE[0]])
    summary = module.run(root, result_csv=result_csv, integrity_csv=integrity_csv)
    out = root / module.OUT_REL
    for name in [
        "v21_208_summary.json",
        "V21.208_original_removal_dry_run_approval_gate_report.txt",
        "original_removal_dry_run_approval_plan.csv",
        "zip_vs_source_integrity_recheck.csv",
        "source_deletion_blocker_check.csv",
        "protected_path_presence_check.csv",
        "manual_approval_checklist.csv",
    ]:
        assert (out / name).is_file()
    payload = json.loads((out / "v21_208_summary.json").read_text(encoding="utf-8"))
    assert payload["final_status"] == summary["final_status"]


def test_no_mutation_behavior(tmp_path):
    module, root, result_csv, integrity_csv = make_repo(tmp_path, [ELIGIBLE[0]])
    source_file = root / f"outputs/v21/{ELIGIBLE[0]}/data.csv"
    before = source_file.read_text(encoding="utf-8")
    module.run(root, result_csv=result_csv, integrity_csv=integrity_csv)
    assert source_file.read_text(encoding="utf-8") == before
    assert (root / f"outputs/v21/{ELIGIBLE[0]}").is_dir()


def test_unhandled_exception_produces_fail(tmp_path):
    module, root, result_csv, integrity_csv = make_repo(tmp_path, [ELIGIBLE[0]])
    summary = module.run(root, result_csv=result_csv, integrity_csv=integrity_csv, simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_208_DRY_RUN_EXCEPTION"
    assert summary["final_decision"] == "ORIGINAL_REMOVAL_DRY_RUN_FAILED"


def test_wrapper_exists_and_references_venv_python():
    assert WRAPPER.is_file()
    text = WRAPPER.read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in text
    assert "v21_208_original_removal_dry_run_approval_gate.py" in text
