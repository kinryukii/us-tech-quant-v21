from __future__ import annotations

import csv
import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_221_minimal_current_chain_keepset_and_repo_body_prune_plan.py")
spec = importlib.util.spec_from_file_location("v21_221", MODULE_PATH)
v221 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v221)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def touch(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_repo(tmp_path: Path, *, protected: bool = True) -> Path:
    root = tmp_path / "repo"
    touch(root / ".venv/Scripts/python.exe")
    touch(root / ".venv_moomoo_py312/Scripts/python.exe")
    touch(root / "scripts/v21/current.py")
    if protected:
        touch(root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
        for name in [
            "V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
            "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
            "V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
            "V21.221_MINIMAL_CURRENT_CHAIN_KEEPSET_AND_REPO_BODY_PRUNE_PLAN",
        ]:
            touch(root / "outputs/v21" / name / "summary.json")
    return root


def test_minimal_hard_keep_paths_are_retained(tmp_path):
    root = make_repo(tmp_path)
    v221.run(root, out_dir=root / "out")
    keeps = read_csv(root / "out/minimal_current_chain_keepset_manifest.csv")
    keep_paths = {r["keep_path"] for r in keeps}
    assert ".venv" in keep_paths
    assert "scripts" in keep_paths
    assert "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv" in keep_paths


def test_v21_197_v21_199_v21_201_retained(tmp_path):
    root = make_repo(tmp_path)
    v221.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/outputs_v21_keep_delete_decision.csv")
    retained = [r for r in rows if r["keep_or_delete_decision"] == "KEEP_MINIMAL_CURRENT_CHAIN"]
    text = "\n".join(r["candidate_path"] for r in retained)
    assert "V21.197" in text
    assert "V21.199" in text
    assert "V21.201" in text


def test_canonical_ohlcv_retained(tmp_path):
    root = make_repo(tmp_path)
    v221.run(root, out_dir=root / "out")
    assert (root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv").exists()


def test_scripts_and_venv_retained(tmp_path):
    root = make_repo(tmp_path)
    v221.run(root, out_dir=root / "out")
    assert (root / "scripts/v21/current.py").exists()
    assert (root / ".venv/Scripts/python.exe").exists()


def test_old_cleanup_proof_chain_delete_candidate(tmp_path):
    root = make_repo(tmp_path)
    touch(root / "outputs/v21/V21.216_AGGRESSIVE_COMPACT_AND_DELETE_EXPANDED_OUTPUTS_AFTER_APPROVAL/summary.json")
    v221.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/cleanup_proof_chain_prune_plan.csv")
    assert any("V21.216" in r["candidate_path"] and r["keep_or_delete_decision"] == "DELETE_OLD_CLEANUP_PROOF" for r in rows)


def test_historical_outputs_v21_not_in_keepset_delete_candidate(tmp_path):
    root = make_repo(tmp_path)
    touch(root / "outputs/v21/V21.123_OLD_HISTORY/summary.json")
    v221.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/repo_body_prune_candidate_plan.csv")
    assert any("V21.123_OLD_HISTORY" in r["candidate_path"] and r["keep_or_delete_decision"] == "DELETE_HISTORICAL_OUTPUT" for r in rows)


def test_non_current_state_cache_delete_candidate(tmp_path):
    root = make_repo(tmp_path)
    touch(root / "state/cache/old.tmp")
    v221.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/state_keep_delete_decision.csv")
    assert any(r["keep_or_delete_decision"] == "DELETE_NON_CURRENT_STATE_CACHE" for r in rows)


def test_alt_venv_kept_for_separate_review(tmp_path):
    root = make_repo(tmp_path)
    v221.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/repo_body_prune_candidate_plan.csv")
    alt = next(r for r in rows if r["candidate_path"] == ".venv_moomoo_py312")
    assert alt["keep_or_delete_decision"] == "RETAIN_FOR_SEPARATE_ALT_VENV_REVIEW"
    assert "CURRENT_MOOMOO_PERMISSION_READINESS_ISSUE" in alt["blocker_reasons"]


def test_deletion_allowed_always_false_and_projection_calculated(tmp_path):
    root = make_repo(tmp_path)
    touch(root / "outputs/v21/V21.123_OLD_HISTORY/summary.json")
    summary = v221.run(root, out_dir=root / "out")
    rows = read_csv(root / "out/repo_body_prune_candidate_plan.csv")
    assert all(r["deletion_allowed_in_this_run"] == "False" for r in rows)
    assert summary["projected_repo_size_after_minimal_keepset_prune"] >= 0
    assert summary["required_manual_approval_phrase"] == v221.APPROVAL_PHRASE


def test_hard_keep_missing_produces_fail(tmp_path):
    root = make_repo(tmp_path, protected=False)
    summary = v221.run(root, out_dir=root / "out")
    assert summary["final_status"] == "FAIL_V21_221_HARD_KEEP_PATH_MISSING"


def test_summary_report_artifacts_written_and_no_mutation(tmp_path):
    root = make_repo(tmp_path)
    out = root / "out"
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    summary = v221.run(root, out_dir=out)
    after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if not p.is_relative_to(out))
    for name in [
        "v21_221_summary.json",
        "V21.221_minimal_current_chain_keepset_and_repo_body_prune_plan_report.txt",
        "minimal_current_chain_keepset_manifest.csv",
        "repo_body_prune_candidate_plan.csv",
        "outputs_v21_keep_delete_decision.csv",
        "state_keep_delete_decision.csv",
        "cleanup_proof_chain_prune_plan.csv",
        "projected_repo_size_after_minimal_keepset_prune.csv",
        "protected_path_presence_check.csv",
        "manual_approval_checklist.csv",
    ]:
        assert (out / name).exists()
    assert [p for p in before if not p.startswith("out/")] == after
    assert summary["deletion_performed"] is False
    assert summary["moomoo_broker_connection_performed"] is False


def test_unhandled_exception_produces_fail(tmp_path):
    root = make_repo(tmp_path)
    summary = v221.run(root, out_dir=root / "out", simulate_exception=True)
    assert summary["final_status"] == "FAIL_V21_221_MINIMAL_KEEPSET_PLAN_EXCEPTION"
    assert summary["deletion_performed"] is False
