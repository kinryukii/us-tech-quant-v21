from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_224_pre_migration_result_archive_and_manifest_freeze.py")
spec = importlib.util.spec_from_file_location("v21_224", MODULE_PATH)
v224 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v224)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_run(root: Path, name: str, *, summary: dict | None = None, body: str = "payload") -> Path:
    run_dir = root / "outputs" / "v21" / name
    write(run_dir / "result.txt", body)
    if summary is not None:
        write(run_dir / "summary.json", json.dumps(summary))
    return run_dir


def make_complete_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    make_run(root, "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT", summary={"final_status": "PASS_A", "final_decision": "DECISION_A"})
    make_run(root, "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME")
    make_run(root, "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH")
    make_run(root, "V21.223_LOCAL_CACHE_ARCHITECTURE_AND_IO_ROUTER")
    make_run(root, "FULL_SYSTEM_LATEST_RERUN_20260630_152719")
    make_run(root, "DAILY_MOOMOO_RESEARCH_CHAIN")
    make_run(root, "DAILY_DRAM_PLAN")
    make_run(root, "DRAM_INTRADAY_FORWARD")
    make_run(root, "DRAM_NO_TRADE_GATE")
    make_run(root, "DRAM_OUTCOME_DASHBOARD")
    make_run(root, "MOOMOO_CANONICAL_CACHE_IO")
    return root


def run_freeze(root: Path, archive: Path, out: Path, *, dry_run: bool = False, freeze_id: str = "freeze_20260703_010203") -> dict:
    return v224.run(repo_root=root, archive_root=archive, output_dir=out, freeze_id=freeze_id, dry_run=dry_run)


def test_discovers_protected_v21_output_directories_by_pattern(tmp_path):
    root = make_complete_repo(tmp_path)
    runs = v224.discover_runs(root)
    protected = {row["run_id"] for row in runs if row["classification"] == "PROTECTED_EVIDENCE"}
    assert "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT" in protected
    assert "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME" in protected


def test_parses_final_status_and_final_decision_from_summary_json(tmp_path):
    root = make_complete_repo(tmp_path)
    out = tmp_path / "out"
    summary = run_freeze(root, tmp_path / "archive", out)
    assert summary["final_status"] == v224.PASS_STATUS
    rows = read_csv(out / "protected_result_run_index.csv")
    row = next(r for r in rows if r["run_id"].startswith("V21.197"))
    assert row["final_status"] == "PASS_A"
    assert row["final_decision"] == "DECISION_A"


def test_creates_migration_inventory_csv(tmp_path):
    root = make_complete_repo(tmp_path)
    out = tmp_path / "out"
    run_freeze(root, tmp_path / "archive", out)
    rows = read_csv(out / "migration_inventory.csv")
    assert rows
    assert {"source_path", "sha256", "classification"}.issubset(rows[0].keys())


def test_creates_protected_result_run_index_csv(tmp_path):
    root = make_complete_repo(tmp_path)
    out = tmp_path / "out"
    run_freeze(root, tmp_path / "archive", out)
    rows = read_csv(out / "protected_result_run_index.csv")
    assert rows
    assert all(r["broker_action_allowed"] == "False" for r in rows)


def test_copies_protected_outputs_into_archive_directory_copy_only(tmp_path):
    root = make_complete_repo(tmp_path)
    archive = tmp_path / "archive"
    out = tmp_path / "out"
    run_freeze(root, archive, out)
    archived = archive / "v21" / f"{v224.STAGE}_freeze_20260703_010203" / "outputs_snapshot" / "outputs" / "v21" / "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT" / "result.txt"
    assert archived.exists()
    assert archived.read_text(encoding="utf-8") == "payload"


def test_preserves_original_source_files_unchanged(tmp_path):
    root = make_complete_repo(tmp_path)
    source = root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/result.txt"
    before = source.read_text(encoding="utf-8")
    before_hash = sha(source)
    run_freeze(root, tmp_path / "archive", tmp_path / "out")
    assert source.exists()
    assert source.read_text(encoding="utf-8") == before
    assert sha(source) == before_hash


def test_calculates_and_verifies_sha256(tmp_path):
    root = make_complete_repo(tmp_path)
    out = tmp_path / "out"
    run_freeze(root, tmp_path / "archive", out)
    rows = read_csv(out / "sha256_manifest.csv")
    row = next(r for r in rows if r["source_path"].endswith("result.txt"))
    assert row["sha256"] == sha(Path(row["source_path"]))
    assert row["sha256"] == sha(Path(row["archive_path"]))


def test_fails_if_archive_target_same_relative_path_has_different_sha256(tmp_path):
    root = make_complete_repo(tmp_path)
    archive = tmp_path / "archive"
    freeze_dir = archive / "v21" / f"{v224.STAGE}_freeze_20260703_010203"
    conflict = freeze_dir / "outputs_snapshot" / "outputs" / "v21" / "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT" / "result.txt"
    write(conflict, "different")
    summary = run_freeze(root, archive, tmp_path / "out")
    assert summary["final_status"] == v224.FAIL_STATUS


def test_supports_dry_run_without_copying_files(tmp_path):
    root = make_complete_repo(tmp_path)
    archive = tmp_path / "archive"
    out = tmp_path / "out"
    summary = run_freeze(root, archive, out, dry_run=True)
    archived = archive / "v21" / f"{v224.STAGE}_freeze_20260703_010203" / "outputs_snapshot" / "outputs" / "v21" / "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT" / "result.txt"
    assert summary["final_status"] == v224.PASS_STATUS
    assert not archived.exists()


def test_marks_missing_critical_patterns_as_warnings_not_silent_success(tmp_path):
    root = tmp_path / "repo"
    make_run(root, "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT")
    summary = run_freeze(root, tmp_path / "archive", tmp_path / "out")
    assert summary["final_status"] == v224.WARN_STATUS
    assert summary["missing_critical_patterns"]
    assert summary["warning_count"] > 0


def test_never_sets_broker_action_or_official_adoption_allowed_true(tmp_path):
    root = make_complete_repo(tmp_path)
    summary = run_freeze(root, tmp_path / "archive", tmp_path / "out")
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    pointer = json.loads((tmp_path / "out" / "archive_pointer_manifest.json").read_text(encoding="utf-8"))
    assert pointer["policy_flags"]["broker_action_allowed"] is False
    assert pointer["policy_flags"]["official_adoption_allowed"] is False


def test_does_not_import_or_call_yfinance():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "import yfinance" not in text
    assert "from yfinance" not in text


def test_writes_archive_pointer_manifest_json(tmp_path):
    root = make_complete_repo(tmp_path)
    out = tmp_path / "out"
    summary = run_freeze(root, tmp_path / "archive", out)
    pointer = json.loads((out / "archive_pointer_manifest.json").read_text(encoding="utf-8"))
    assert pointer["final_status"] == summary["final_status"]
    assert pointer["policy_flags"]["copy_only"] is True


def test_returns_non_zero_exit_code_on_hard_verification_failure(tmp_path):
    root = make_complete_repo(tmp_path)
    archive = tmp_path / "archive"
    freeze_dir = archive / "v21" / f"{v224.STAGE}_freeze_20260703_010203"
    conflict = freeze_dir / "outputs_snapshot" / "outputs" / "v21" / "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT" / "result.txt"
    write(conflict, "different")
    code = v224.main([
        "--repo-root",
        str(root),
        "--archive-root",
        str(archive),
        "--output-dir",
        str(tmp_path / "out"),
        "--freeze-id",
        "freeze_20260703_010203",
    ])
    assert code != 0
