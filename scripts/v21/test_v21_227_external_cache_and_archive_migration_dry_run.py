from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_227_external_cache_and_archive_migration_dry_run.py")
spec = importlib.util.spec_from_file_location("v21_227", MODULE_PATH)
v227 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v227)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def make_v226(tmp_path: Path, *, collision: bool = False, invalid: bool = False, missing: bool = False) -> tuple[Path, Path, Path, Path, Path]:
    root = tmp_path / "repo"
    v226 = root / "outputs/v21/V21.226_REPO_CACHE_ARCHIVE_SEPARATION_PLAN"
    cache = tmp_path / "cache"
    archive = tmp_path / "archive"
    quarantine = tmp_path / "quarantine"
    srcs = {
        "script": root / "scripts/a.py",
        "cache": root / "outputs/moomoo_raw.csv",
        "archive": root / "outputs/history.csv",
        "quarantine": root / "outputs/bad.csv",
        "delete": root / "tmp/x.tmp",
        "review": root / "outputs/E_R1.csv",
        "protected": root / "outputs/protected_summary.json",
        "large": root / "outputs/large.csv",
        "yfin": root / "outputs/yfinance_cache.csv",
    }
    for k, p in srcs.items():
        if not (missing and k == "archive"):
            write(p, "x" * (100 if k != "large" else 2000))
    target_archive = str(cache / "same.csv") if collision else str(archive / "history.csv")
    target_cache = str(Path("C:/outside/bad.csv")) if invalid else str(cache / "raw.csv")
    rows = [
        [srcs["script"],"scripts/a.py","100","ACTIVE_SUPPORT","KEEP_IN_REPO","","","", "python_code","a","True","False","False","False","False","False","False","False","False","False","False","False","False","False","False","False","keep",""],
        [srcs["cache"],"outputs/moomoo_raw.csv","100","ACTIVE_CORE","MOVE_TO_CACHE_PLAN",cache,"raw.csv",target_cache,"data","m","True","False","False","False","True","False","False","False","False","False","False","False","False","False","True","True","cache",""],
        [srcs["archive"],"outputs/history.csv","100","ARCHIVE_ONLY","MOVE_TO_ARCHIVE_PLAN",archive,"history.csv",target_archive,"data","h","False","False","False","False","False","False","False","False","False","False","False","False","False","False","True","True","archive",""],
        [srcs["quarantine"],"outputs/bad.csv","100","QUARANTINE_CANDIDATE","QUARANTINE_PLAN",quarantine,"bad.csv",quarantine/"bad.csv","data","q","False","False","False","False","False","False","False","False","False","True","False","False","False","False","True","True","quarantine",""],
        [srcs["delete"],"tmp/x.tmp","100","DELETE_CANDIDATE_REVIEW_ONLY","DELETE_AFTER_VERIFICATION_PLAN","","","","file","d","False","False","False","False","False","False","False","False","False","False","True","False","False","False","False","True","delete",""],
        [srcs["review"],"outputs/E_R1.csv","100","PAUSED_REVIEW_REQUIRED","USER_REVIEW_REQUIRED","","","","data","r","False","False","False","False","False","False","False","False","False","True","False","False","False","False","False","False","review",""],
        [srcs["protected"],"outputs/protected_summary.json","100","PROTECTED_EVIDENCE","PROTECTED_NO_ACTION","","","","json","p","True","True","True","False","False","False","False","False","False","False","False","False","False","False","False","False","protected",""],
        [srcs["large"],"outputs/large.csv","2000","ARCHIVE_ONLY","MOVE_TO_ARCHIVE_PLAN",archive,"large.csv",archive/"large.csv","data","l","False","False","False","False","False","False","False","False","False","False","False","False","False","False","True","True","large",""],
        [srcs["yfin"],"outputs/yfinance_cache.csv","100","DEPRECATED","DELETE_AFTER_VERIFICATION_PLAN","","","","data","y","False","False","False","True","False","False","False","False","False","False","True","False","False","False","False","True","yfinance",""],
    ]
    if collision:
        rows[1][7] = str(cache / "same.csv")
    header = ["source_path","relative_path","size_bytes","current_status","target_action","target_root","target_relative_path","proposed_target_path","artifact_type","inferred_module","active_dependency","protected_by_v21_224","protected_by_v21_225","yfinance_related","moomoo_related","dram_related","abcde_related","v20_related","v21_related","requires_user_review","delete_after_verification_only","immediate_delete_allowed","immediate_move_allowed","immediate_copy_allowed","pointer_required","sha256_required","reason","notes"]
    write(v226 / "separation_plan_master.csv", ",".join(header) + "\n" + "\n".join(",".join(map(str, r)) for r in rows) + "\n")
    write(v226 / "repo_keep_plan.csv", "source_path,reason,lightweight_policy,max_expected_size_bytes,pointer_required,active_dependency\n%s,keep,policy,1,False,True\n" % srcs["script"])
    write(v226 / "cache_migration_plan.csv", "source_path,proposed_cache_path,cache_category,data_source_policy,active_runtime_needed,sha256_required,pointer_required,reason\n%s,%s,raw,MOOMOO,True,True,True,cache\n" % (srcs["cache"], target_cache))
    write(v226 / "archive_migration_plan.csv", "source_path,proposed_archive_path,archive_category,protected_evidence,user_review_required,sha256_required,pointer_required,reason\n%s,%s,hist,False,False,True,True,archive\n%s,%s,hist,False,False,True,True,large\n" % (srcs["archive"], target_archive, srcs["large"], archive/"large.csv"))
    write(v226 / "quarantine_plan.csv", "source_path,proposed_quarantine_path,reason,conflict_type,user_review_required,verification_required\n%s,%s,q,q,True,True\n" % (srcs["quarantine"], quarantine/"bad.csv"))
    write(v226 / "delete_after_verification_plan.csv", "source_path,size_bytes,reason,required_pre_delete_checks,protected_blocker,user_review_blocker,archive_or_cache_copy_required,immediate_delete_allowed\n%s,100,delete,checks,False,False,True,False\n%s,100,yfinance,checks,False,False,True,False\n" % (srcs["delete"], srcs["yfin"]))
    write(v226 / "user_review_required_plan.csv", "source_path,project_name,reason,latest_status,continue_value_score,fit_with_dram_only_focus,recommended_review_action\n%s,E_R1,review,,1,LOW,review\n" % srcs["review"])
    write(v226 / "protected_no_action_plan.csv", "source_path,reason,protected_by,no_action_until\n%s,protected,V21.224,later\n" % srcs["protected"])
    write(v226 / "pointer_manifest_plan.csv", "source_path,future_repo_pointer_path,target_external_path,pointer_type,required_fields,reason\n%s,%s,%s,cache_pointer,a,cache\n" % (srcs["cache"], root/"outputs/_pointers/raw.pointer.json", target_cache))
    for name in ["directory_layout_plan.json","repo_lightweight_output_policy.json","v21_226_summary.json"]:
        write(v226 / name, json.dumps({"total_planned_items": len(rows), "immediate_delete_allowed": False, "immediate_move_allowed": False, "immediate_copy_allowed": False}))
    write(v226 / "migration_order_plan.csv", "step_number,phase_name,action,allowed_to_execute_now,prerequisite,expected_next_script,notes\n1,V21.227 migration dry-run,simulate,True,x,V21.228,y\n2,V21.228 copy-only externalization,copy,False,x,V21.229,y\n10,V21.235 clean delete after verification,delete,False,x,V21.236,y\n")
    for name in ["storage_impact_projection.csv","moomoo_only_cache_layout_plan.csv","archive_layout_plan.csv","v21_224_225_dependency_crosscheck.csv"]:
        write(v226 / name, "x\n")
    return root, v226, cache, archive, quarantine


def test_fails_if_required_v226_inputs_missing(tmp_path):
    summary = v227.run(repo_root=tmp_path/"repo", output_dir=tmp_path/"out", v21_226_output_dir=tmp_path/"missing")
    assert summary["final_status"] == v227.FAIL_INPUT_STATUS


def test_reads_master_and_creates_dry_run_master(tmp_path):
    root, v226dir, cache, archive, quarantine = make_v226(tmp_path)
    out = tmp_path/"out"; v227.run(root, out, v226dir, cache, archive, quarantine)
    assert read_csv(out/"dry_run_master_plan.csv")


def test_simulates_all_actions_without_mutation(tmp_path):
    root, v226dir, cache, archive, quarantine = make_v226(tmp_path)
    before = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    out = tmp_path/"out"; v227.run(root, out, v226dir, cache, archive, quarantine)
    after = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and not str(p).startswith(str(out)))
    assert all((out / name).exists() for name in ["dry_run_cache_actions.csv","dry_run_archive_actions.csv","dry_run_quarantine_actions.csv","dry_run_delete_after_verification_actions.csv","dry_run_repo_keep_actions.csv","dry_run_protected_no_action.csv","dry_run_user_review_blockers.csv"])
    assert before == after


def test_never_creates_external_roots(tmp_path):
    root, v226dir, cache, archive, quarantine = make_v226(tmp_path)
    v227.run(root, tmp_path/"out", v226dir, cache, archive, quarantine)
    assert not cache.exists() and not archive.exists() and not quarantine.exists()


def test_detects_duplicate_target_collisions(tmp_path):
    root, v226dir, cache, archive, quarantine = make_v226(tmp_path, collision=True)
    summary = v227.run(root, tmp_path/"out", v226dir, cache, archive, quarantine)
    assert summary["path_collision_count"] > 0


def test_detects_targets_outside_allowed_roots(tmp_path):
    root, v226dir, cache, archive, quarantine = make_v226(tmp_path, invalid=True)
    summary = v227.run(root, tmp_path/"out", v226dir, cache, archive, quarantine)
    assert summary["invalid_target_path_count"] > 0


def test_missing_required_sources_fail(tmp_path):
    root, v226dir, cache, archive, quarantine = make_v226(tmp_path, missing=True)
    summary = v227.run(root, tmp_path/"out", v226dir, cache, archive, quarantine)
    assert summary["missing_source_count"] > 0
    assert summary["final_status"] == v227.FAIL_PLAN_STATUS


def test_user_review_blockers_not_delete_allowed_now(tmp_path):
    root, v226dir, cache, archive, quarantine = make_v226(tmp_path)
    out = tmp_path/"out"; v227.run(root, out, v226dir, cache, archive, quarantine)
    assert read_csv(out/"dry_run_user_review_blockers.csv")
    assert all(r["dry_run_delete_allowed_now"] == "False" for r in read_csv(out/"dry_run_delete_after_verification_actions.csv"))


def test_protected_files_no_action_or_blocked(tmp_path):
    root, v226dir, cache, archive, quarantine = make_v226(tmp_path)
    out = tmp_path/"out"; v227.run(root, out, v226dir, cache, archive, quarantine)
    assert read_csv(out/"dry_run_protected_no_action.csv")[0]["dry_run_pass"] == "True"


def test_creates_pointer_manifest_actions(tmp_path):
    root, v226dir, cache, archive, quarantine = make_v226(tmp_path)
    out = tmp_path/"out"; v227.run(root, out, v226dir, cache, archive, quarantine)
    assert read_csv(out/"dry_run_pointer_manifest_actions.csv")


def test_hash_feasibility_defers_large_by_default(tmp_path):
    root, v226dir, cache, archive, quarantine = make_v226(tmp_path)
    out = tmp_path/"out"; v227.run(root, out, v226dir, cache, archive, quarantine, hash_threshold_bytes=100)
    rows = read_csv(out/"dry_run_hash_feasibility_audit.csv")
    assert any(r["sha256_status"] == "HASH_DEFERRED_TO_COPY_ONLY_STAGE" for r in rows)


def test_policy_gate_allows_no_mutation(tmp_path):
    root, v226dir, cache, archive, quarantine = make_v226(tmp_path)
    out = tmp_path/"out"; v227.run(root, out, v226dir, cache, archive, quarantine)
    policy = json.loads((out/"dry_run_policy_gate.json").read_text())
    assert policy["copy_allowed_now"] is False and policy["move_allowed_now"] is False and policy["delete_allowed_now"] is False
    assert policy["external_root_creation_allowed_now"] is False


def test_yfinance_disallowed_in_active_future_chain(tmp_path):
    root, v226dir, cache, archive, quarantine = make_v226(tmp_path)
    out = tmp_path/"out"; v227.run(root, out, v226dir, cache, archive, quarantine)
    row = next(r for r in read_csv(out/"dry_run_master_plan.csv") if "yfinance" in r["relative_path"])
    assert row["dry_run_future_action"] == "DELETE_AFTER_VERIFICATION_FUTURE"


def test_creates_storage_projection(tmp_path):
    root, v226dir, cache, archive, quarantine = make_v226(tmp_path)
    out = tmp_path/"out"; v227.run(root, out, v226dir, cache, archive, quarantine)
    assert read_csv(out/"dry_run_storage_projection.csv")


def test_creates_consistency_audit(tmp_path):
    root, v226dir, cache, archive, quarantine = make_v226(tmp_path)
    out = tmp_path/"out"; v227.run(root, out, v226dir, cache, archive, quarantine)
    assert read_csv(out/"v21_226_plan_consistency_audit.csv")


def test_warning_when_only_user_review_blockers_remain(tmp_path):
    root, v226dir, cache, archive, quarantine = make_v226(tmp_path)
    summary = v227.run(root, tmp_path/"out", v226dir, cache, archive, quarantine)
    assert summary["final_status"] == v227.WARN_STATUS


def test_fail_for_collisions_or_invalid_required_targets(tmp_path):
    root, v226dir, cache, archive, quarantine = make_v226(tmp_path, invalid=True)
    summary = v227.run(root, tmp_path/"out", v226dir, cache, archive, quarantine)
    assert summary["final_status"] == v227.FAIL_PLAN_STATUS


def test_no_banned_imports():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "import yfinance" not in text and "from yfinance" not in text
    assert "import moomoo" not in text and "from moomoo" not in text
    assert "import futu" not in text and "from futu" not in text
