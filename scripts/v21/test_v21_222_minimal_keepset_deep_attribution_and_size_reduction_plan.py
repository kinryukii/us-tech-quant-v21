from __future__ import annotations

import csv
import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_222_minimal_keepset_deep_attribution_and_size_reduction_plan.py")
spec = importlib.util.spec_from_file_location("v21_222", MODULE_PATH)
v222 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v222)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def touch(path: Path, data: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def make_repo(tmp_path: Path, *, protected: bool = True) -> Path:
    root = tmp_path / "repo"
    touch(root / ".venv/Scripts/python.exe")
    touch(root / ".venv/Lib/site-packages/pkg_a/__init__.py")
    touch(root / ".venv_moomoo_py312/Scripts/python.exe")
    touch(root / "scripts/v21/current.py")
    touch(root / "state/cache/old.tmp")
    if protected:
        touch(root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
        for name in [
            "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
            "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
            "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
        ]:
            touch(root / "outputs/v21" / name / "summary.json")
            touch(root / "outputs/v21" / name / "large.csv", "abc\n")
    touch(root / "outputs/v21/OTHER_STAGE/file.csv")
    return root


def test_current_chain_stages_attributed_not_deletion_candidates(tmp_path):
    root = make_repo(tmp_path)
    v222.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/minimal_keepset_component_size_breakdown.csv")
    for name in ["V21.197", "V21.199_R4", "V21.201"]:
        row = next(r for r in rows if r["component_name"] == name)
        assert row["current_chain_required"] == "True"
        assert row["proposed_reduction_method"] != "DELETE"


def test_canonical_attributed_not_delete_now(tmp_path):
    root = make_repo(tmp_path)
    v222.run(root, out_dir=root / "out")
    row = read_csv(root / "out/canonical_price_size_breakdown.csv")[0]
    assert row["component_name"] == "canonical_price"
    assert row["proposed_reduction_method"] == "MOVE_CANONICAL_TO_EXTERNAL_DATA_STORE_WITH_POINTER"
    assert row["risk_level"] == "HIGH"


def test_state_breakdown_generated(tmp_path):
    root = make_repo(tmp_path)
    v222.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/state_current_vs_noncurrent_breakdown.csv")
    assert any(r["state_class"] == "NONCURRENT_CACHE" for r in rows)


def test_venv_package_breakdown_generated(tmp_path):
    root = make_repo(tmp_path)
    v222.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/venv_package_size_breakdown.csv")
    assert any(r["package_name"] == "pkg_a" for r in rows)


def test_alt_venv_blocker_recheck_recorded(tmp_path):
    root = make_repo(tmp_path)
    v222.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/alt_venv_retirement_blocker_recheck.csv")
    assert rows
    assert rows[0]["alt_venv_exists"] == "True"


def test_largest_files_and_gap_analysis_emitted(tmp_path):
    root = make_repo(tmp_path)
    v222.run(root, out_dir=root / "out")
    assert read_csv(root / "out/minimal_keepset_largest_files.csv")
    gap = {r["metric"]: r["value"] for r in read_csv(root / "out/repo_1gb_gap_analysis.csv")}
    assert "gap_to_target" in gap
    assert "projected_best_case_repo_size" in gap


def test_risk_actions_separated(tmp_path):
    root = make_repo(tmp_path)
    v222.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/next_reduction_action_plan.csv")
    risks = {r["risk_level"] for r in rows}
    assert "MEDIUM" in risks
    assert "HIGH" in risks


def test_no_delete_or_compress_flags(tmp_path):
    root = make_repo(tmp_path)
    summary = v222.run(root, out_dir=root / "out")
    assert summary["deletion_allowed_in_this_run"] is False
    assert summary["compression_allowed_in_this_run"] is False
    assert summary["deletion_performed"] is False
    assert summary["compression_performed"] is False


def test_protected_path_missing_produces_fail(tmp_path):
    root = make_repo(tmp_path, protected=False)
    summary = v222.run(root, out_dir=root / "out")
    assert summary["final_status"] == "FAIL_V21_222_PROTECTED_PATH_MISSING"


def test_summary_report_artifacts_written_and_no_mutation(tmp_path):
    root = make_repo(tmp_path)
    out = root / "out"
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    summary = v222.run(root, out_dir=out)
    after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if not p.is_relative_to(out))
    for name in [
        "v21_222_summary.json",
        "V21.222_minimal_keepset_deep_attribution_report.txt",
        "minimal_keepset_component_size_breakdown.csv",
        "minimal_keepset_largest_files.csv",
        "v21_197_deep_size_breakdown.csv",
        "v21_199_r4_deep_size_breakdown.csv",
        "v21_201_deep_size_breakdown.csv",
        "canonical_price_size_breakdown.csv",
        "state_current_vs_noncurrent_breakdown.csv",
        "venv_package_size_breakdown.csv",
        "alt_venv_retirement_blocker_recheck.csv",
        "repo_1gb_gap_analysis.csv",
        "next_reduction_action_plan.csv",
        "protected_path_presence_check.csv",
    ]:
        assert (out / name).exists()
    assert [p for p in before if not p.startswith("out/")] == after
    assert summary["moomoo_broker_connection_performed"] is False


def test_unhandled_exception_produces_fail(tmp_path):
    root = make_repo(tmp_path)
    summary = v222.run(root, out_dir=root / "out", simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_222_ATTRIBUTION_EXCEPTION"
    assert summary["deletion_performed"] is False
