from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_225_system_review_deprecation_and_cleanup_audit.py")
spec = importlib.util.spec_from_file_location("v21_225", MODULE_PATH)
v225 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v225)


def write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    write(root / "outputs/v21/DAILY_DRAM_PLAN/summary.json", '{"final_status":"PASS"}')
    write(root / "outputs/v21/V21.183_DRAM_INTRADAY_FORWARD_OUTCOME_UPDATER/summary.json", "{}")
    write(root / "outputs/v21/V21.184_DRAM_INTRADAY_OUTCOME_DASHBOARD_AND_DECISION_SUMMARY/report.txt", "outcome_dashboard")
    write(root / "outputs/v21/V21.186_DRAM_NO_TRADE_GATE/report.txt", "no_trade_gate")
    write(root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/summary.json", "{}")
    write(root / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME/summary.json", "{}")
    write(root / "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH/summary.json", "{}")
    write(root / "outputs/v21/V21.223_LOCAL_CACHE_ARCHITECTURE_AND_IO_ROUTER/summary.json", "{}")
    write(root / "outputs/v21/V21.224_PRE_MIGRATION_RESULT_ARCHIVE_AND_MANIFEST_FREEZE/archive_pointer_manifest.json", "{}")
    write(root / "outputs/v21/E_R1_DEFENSIVE_OVERLAY/result.csv", "paused")
    write(root / "outputs/v21/D_R2C_VARIANT/result.csv", "paused")
    write(root / "outputs/v21/SOFT_CAP_OVERHEAT_OVERLAY/result.csv", "paused")
    write(root / "outputs/v21/SWITCH_GOVERNANCE_LEDGER/result.csv", "paused")
    write(root / "outputs/v21/AI_BOTTLENECK_THEME/result.csv", "paused")
    write(root / "outputs/v21/ETF_ROTATION_EXPERIMENT/result.csv", "paused")
    write(root / "scripts/v21/yahoo_default_chain.py", "import yfinance as yf\n")
    write(root / "tmp/scratch.tmp", "scratch")
    write(root / "outputs/v21/MYSTERY_MODULE/file.dat", "unknown")
    write(root / ".git/ignored.txt", "ignored")
    write(root / ".venv/ignored.py", "ignored")
    return root


def make_v224_manifest(root: Path) -> Path:
    v224 = root / "outputs/v21/V21.224_PRE_MIGRATION_RESULT_ARCHIVE_AND_MANIFEST_FREEZE"
    protected = root / "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT/summary.json"
    write(
        v224 / "archive_manifest.csv",
        "source_path,archive_path,relative_archive_path,size_bytes,sha256,copied,verified,classification,run_id\n"
        f"{protected},{root / 'archive/copy.json'},x,2,abc,True,True,PROTECTED_EVIDENCE,V21.197\n",
    )
    return v224


def run_audit(root: Path, out: Path, **kwargs) -> dict:
    return v225.run(repo_root=root, output_dir=out, v21_224_output_dir=kwargs.get("v224"), large_threshold_bytes=kwargs.get("large", 10), max_content_scan_bytes=2000)


def test_classifies_dram_daily_intraday_modules_active(tmp_path):
    root = make_repo(tmp_path)
    make_v224_manifest(root)
    out = tmp_path / "out"
    run_audit(root, out)
    rows = read_csv(out / "system_file_inventory.csv")
    dram = [r for r in rows if "DRAM" in r["relative_path"]]
    assert dram
    assert all(r["primary_status"] in {"ACTIVE_CORE", "PROTECTED_EVIDENCE", "ACTIVE_SUPPORT"} for r in dram)


def test_classifies_known_protected_versions(tmp_path):
    root = make_repo(tmp_path)
    make_v224_manifest(root)
    out = tmp_path / "out"
    run_audit(root, out)
    rows = read_csv(out / "module_status_registry.csv")
    protected_names = ["V21.197", "V21.199_R4", "V21.201", "V21.223", "V21.224"]
    for name in protected_names:
        row = next(r for r in rows if name in r["module_name"])
        assert row["primary_status"] in {"PROTECTED_EVIDENCE", "ACTIVE_CORE", "ACTIVE_SUPPORT"}


def test_paused_candidates_are_not_safe_delete(tmp_path):
    root = make_repo(tmp_path)
    make_v224_manifest(root)
    out = tmp_path / "out"
    run_audit(root, out)
    rows = read_csv(out / "system_file_inventory.csv")
    paused = [r for r in rows if any(token in r["relative_path"] for token in ["E_R1", "D_R2C", "SOFT_CAP", "SWITCH", "AI_BOTTLENECK", "ETF_ROTATION"])]
    assert paused
    assert all(r["primary_status"] in {"PAUSED_REVIEW_REQUIRED", "ARCHIVE_ONLY"} for r in paused)
    assert all(r["safe_to_delete_now"] == "False" for r in paused)


def test_yfinance_artifacts_deprecated_and_disallowed(tmp_path):
    root = make_repo(tmp_path)
    make_v224_manifest(root)
    out = tmp_path / "out"
    run_audit(root, out)
    yrows = read_csv(out / "yfinance_artifact_inventory.csv")
    assert yrows
    assert yrows[0]["primary_status"] == "DEPRECATED"
    assert yrows[0]["allowed_in_future_active_chain"] == "False"


def test_creates_paused_project_review_list(tmp_path):
    root = make_repo(tmp_path)
    make_v224_manifest(root)
    out = tmp_path / "out"
    run_audit(root, out)
    assert read_csv(out / "paused_project_review_list.csv")


def test_delete_candidates_safe_to_delete_now_always_false(tmp_path):
    root = make_repo(tmp_path)
    make_v224_manifest(root)
    out = tmp_path / "out"
    run_audit(root, out)
    inv = read_csv(out / "system_file_inventory.csv")
    assert all(r["safe_to_delete_now"] == "False" for r in inv)
    deletes = read_csv(out / "delete_candidates_review_only.csv")
    assert deletes


def test_creates_large_file_inventory(tmp_path):
    root = make_repo(tmp_path)
    make_v224_manifest(root)
    out = tmp_path / "out"
    run_audit(root, out, large=1)
    assert read_csv(out / "large_file_inventory.csv")


def test_creates_moomoo_only_readiness_audit(tmp_path):
    root = make_repo(tmp_path)
    make_v224_manifest(root)
    out = tmp_path / "out"
    run_audit(root, out)
    rows = read_csv(out / "moomoo_only_readiness_audit.csv")
    assert rows
    assert any(r["allowed_in_future_canonical_chain"] == "False" for r in rows)


def test_consumes_v21_224_manifest_and_marks_protected(tmp_path):
    root = make_repo(tmp_path)
    v224dir = make_v224_manifest(root)
    out = tmp_path / "out"
    summary = run_audit(root, out, v224=v224dir)
    assert summary["v21_224_archive_crosscheck_status"] == "FOUND"
    inv = read_csv(out / "system_file_inventory.csv")
    assert any(r["protected_by_v21_224"] == "True" for r in inv)


def test_dram_outcome_pattern_crosscheck_pattern_miss_only(tmp_path):
    root = make_repo(tmp_path)
    make_v224_manifest(root)
    out = tmp_path / "out"
    summary = run_audit(root, out)
    assert summary["dram_outcome_crosscheck_status"] == "PATTERN_MISS_ONLY"
    assert read_csv(out / "dram_outcome_pattern_crosscheck.csv")


def test_does_not_scan_venv_or_git_by_default(tmp_path):
    root = make_repo(tmp_path)
    make_v224_manifest(root)
    out = tmp_path / "out"
    run_audit(root, out)
    inv = read_csv(out / "system_file_inventory.csv")
    assert not any(".git" in r["relative_path"] or ".venv" in r["relative_path"] for r in inv)


def test_does_not_import_yfinance_moomoo_or_futu():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "import yfinance" not in text
    assert "from yfinance" not in text
    assert "import moomoo" not in text
    assert "from moomoo" not in text
    assert "import futu" not in text
    assert "from futu" not in text


def test_cleanup_policy_disallows_delete_and_is_audit_only(tmp_path):
    root = make_repo(tmp_path)
    make_v224_manifest(root)
    out = tmp_path / "out"
    run_audit(root, out)
    policy = json.loads((out / "cleanup_policy.json").read_text(encoding="utf-8"))
    assert policy["delete_allowed"] is False
    assert policy["audit_only"] is True


def test_warning_status_when_unknown_review_items_remain(tmp_path):
    root = make_repo(tmp_path)
    make_v224_manifest(root)
    out = tmp_path / "out"
    summary = run_audit(root, out)
    assert summary["final_status"] == v225.WARN_REVIEW_STATUS


def test_returns_non_zero_on_hard_output_write_failure(monkeypatch, tmp_path):
    root = make_repo(tmp_path)
    make_v224_manifest(root)

    def boom(*args, **kwargs):
        raise OSError("simulated write failure")

    monkeypatch.setattr(v225, "write_csv", boom)
    code = v225.main(["--repo-root", str(root), "--output-dir", str(tmp_path / "out")])
    assert code != 0
