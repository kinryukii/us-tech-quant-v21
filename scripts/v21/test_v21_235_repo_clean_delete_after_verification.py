from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_235_repo_clean_delete_after_verification.py")
spec = importlib.util.spec_from_file_location("v21_235", MODULE_PATH)
v235 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(v235)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as h:
        return list(csv.DictReader(h))


def make_guard(root: Path) -> None:
    write(root / "config/v21/data_source_policy.json", json.dumps({"default_data_source_policy":"MOOMOO_ONLY","research_only":True,"yfinance_allowed_by_default":False}))
    write(root / "scripts/v21/v21_data_source_policy_guard.py", """
import json
from pathlib import Path
def load_data_source_policy(policy_path=None):
    return json.loads(Path(policy_path).read_text(encoding="utf-8"))
def assert_moomoo_only_policy(context, allow_diagnostic_external=False):
    if load_data_source_policy(Path(__file__).resolve().parents[2] / "config/v21/data_source_policy.json").get("default_data_source_policy") != "MOOMOO_ONLY":
        raise RuntimeError("bad")
""".lstrip())


def sha(path: Path) -> str:
    return v235.sha256(path)


def make_inputs(root: Path, *, active: Path | None=None, protected: Path | None=None, user: Path | None=None, candidate: Path | None=None, external: Path | None=None, mismatch: bool=False) -> tuple[Path, Path, Path, Path, Path]:
    make_guard(root)
    v225=root/"outputs/v21/V21.225_SYSTEM_REVIEW_DEPRECATION_AND_CLEANUP_AUDIT"
    v226=root/"outputs/v21/V21.226_REPO_CACHE_ARCHIVE_SEPARATION_PLAN"
    v227=root/"outputs/v21/V21.227_EXTERNAL_CACHE_AND_ARCHIVE_MIGRATION_DRY_RUN"
    v228=root/"outputs/v21/V21.228_EXTERNAL_CACHE_AND_ARCHIVE_MIGRATION_COPY_ONLY"
    v234=root/"outputs/v21/V21.234_MINIMAL_MOOMOO_ONLY_DAILY_RESEARCH_CHAIN"
    for name in ["system_file_inventory.csv","delete_candidates_review_only.csv"]:
        write(v225/name, "source_path\n")
    write(v225/"active_core_modules.csv", f"module_name\n{active.name if active else ''}\n")
    write(v225/"active_support_modules.csv", "module_name\n")
    write(v225/"protected_evidence_modules.csv", f"module_name\n{protected.name if protected else ''}\n")
    write(v225/"paused_project_review_list.csv", f"module_name\n{user.name if user else ''}\n")
    write(v226/"separation_plan_master.csv", "source_path\n")
    rows = "source_path,size_bytes,reason\n"
    if candidate:
        rows += f"{candidate},{candidate.stat().st_size},delete after verification\n"
    if active:
        rows += f"{active},{active.stat().st_size},delete after verification\n"
    if protected:
        rows += f"{protected},{protected.stat().st_size},delete after verification\n"
    if user:
        rows += f"{user},{user.stat().st_size},delete after verification\n"
    write(v226/"delete_after_verification_plan.csv", rows)
    write(v226/"protected_no_action_plan.csv", "source_path\n")
    write(v226/"user_review_required_plan.csv", f"source_path\n{user if user else ''}\n")
    write(v227/"dry_run_delete_after_verification_actions.csv", rows)
    write(v227/"dry_run_master_plan.csv", "source_path\n")
    write(v227/"dry_run_user_review_blockers.csv", "source_path\n")
    write(v227/"dry_run_protected_no_action.csv", "source_path\n")
    write(v228/"v21_228_summary.json", json.dumps({"copied_file_count":1,"verified_file_count":1,"failed_copy_count":0,"hash_mismatch_count":0}))
    copy_rows = "source_path,target_path,source_sha256,target_sha256,source_size,target_size,hash_match,size_match,verified,error\n"
    if candidate and external:
        target_hash = "bad" if mismatch else sha(external)
        copy_rows += f"{candidate},{external},{sha(candidate)},{target_hash},{candidate.stat().st_size},{external.stat().st_size},{'False' if mismatch else 'True'},True,True,\n"
    write(v228/"copy_hash_verification.csv", copy_rows)
    write(v228/"source_integrity_audit.csv", "source_path\n")
    write(v228/"repo_pointer_manifest_index.csv", "source_path\n")
    write(v234/"v21_234_summary.json", json.dumps({"daily_chain_passed":True}))
    write(v234/"daily_chain_stage_status.csv", "stage_name\n")
    write(v234/"daily_chain_pointer_manifest.json", json.dumps({"v21_231_output_dir":str(root/"outputs/v21/V21.231"),"canonical_snapshot_dir":str(root/"not_external")}))
    write(v234/"source_policy_gate.json", json.dumps({"data_source_policy":"MOOMOO_ONLY"}))
    return v225,v226,v227,v228,v234


def test_missing_inputs_fail(tmp_path):
    root=tmp_path/"repo"; make_guard(root)
    s=v235.run(root,tmp_path/"out")
    assert s["final_status"] == v235.FAIL_INPUT


def test_never_imports_yfinance_or_moomoo_futu():
    text=MODULE_PATH.read_text(encoding="utf-8")
    assert "import yfinance" not in text and "from yfinance" not in text
    assert "import moomoo" not in text and "from moomoo" not in text
    assert "import futu" not in text and "from futu" not in text


def test_blocks_active_protected_user_review(tmp_path):
    root=tmp_path/"repo"
    active=root/"active_core.txt"; protected=root/"protected.txt"; user=root/"user_review.txt"
    write(active,"a"); write(protected,"p"); write(user,"u")
    dirs=make_inputs(root,active=active,protected=protected,user=user)
    s=v235.run(root,tmp_path/"out",*dirs)
    assert active.exists() and protected.exists() and user.exists()
    assert s["active_chain_blocked_count"] >= 1
    assert s["protected_blocked_count"] >= 1
    assert s["user_review_blocked_count"] >= 1


def test_deletes_pycache_and_pytest_cache(tmp_path):
    root=tmp_path/"repo"; pyc=root/"pkg/__pycache__/a.pyc"; pc=root/".pytest_cache/v/cache/nodeids"
    write(pyc,"x"); write(pc,"x")
    dirs=make_inputs(root)
    s=v235.run(root,tmp_path/"out",*dirs)
    assert not pyc.exists()
    assert not pc.exists()
    assert s["transient_delete_count"] >= 2


def test_deletes_duplicate_only_when_hash_matches(tmp_path):
    root=tmp_path/"repo"; f=root/"dup.txt"; ext=tmp_path/"archive/dup.txt"
    write(f,"same"); write(ext,"same")
    dirs=make_inputs(root,candidate=f,external=ext)
    s=v235.run(root,tmp_path/"out",*dirs)
    assert not f.exists()
    assert ext.exists()
    assert s["external_copy_verified_delete_count"] >= 1


def test_refuses_duplicate_missing_or_mismatch(tmp_path):
    root=tmp_path/"repo"; f=root/"dup.txt"; ext=tmp_path/"archive/dup.txt"
    write(f,"same")
    dirs=make_inputs(root,candidate=f)
    s=v235.run(root,tmp_path/"out1",*dirs)
    assert f.exists()
    write(ext,"different")
    dirs=make_inputs(root,candidate=f,external=ext,mismatch=True)
    s=v235.run(root,tmp_path/"out2",*dirs)
    assert f.exists()


def test_does_not_delete_external_files(tmp_path):
    root=tmp_path/"repo"; f=root/"dup.txt"; ext=tmp_path/"us-tech-quant-cache/file.txt"
    write(f,"same"); write(ext,"same")
    dirs=make_inputs(root,candidate=ext,external=f)
    v235.run(root,tmp_path/"out",*dirs)
    assert ext.exists()


def test_writes_manifests_and_dry_run(tmp_path):
    root=tmp_path/"repo"; f=root/"dup.txt"; ext=tmp_path/"archive/dup.txt"
    write(f,"same"); write(ext,"same")
    dirs=make_inputs(root,candidate=f,external=ext)
    out=tmp_path/"out"; s=v235.run(root,out,*dirs,dry_run=True)
    assert f.exists()
    for n in ["deleted_file_ledger.csv","skipped_delete_blocked_manifest.csv","external_copy_verification_audit.csv","deletion_policy_gate.json"]:
        assert (out/n).exists()


def test_empty_dirs_flag_and_warn_blockers(tmp_path):
    root=tmp_path/"repo"; f=root/"a/b/dup.txt"; ext=tmp_path/"archive/dup.txt"; active=root/"active.txt"
    write(f,"same"); write(ext,"same"); write(active,"x")
    dirs=make_inputs(root,candidate=f,external=ext,active=active)
    s=v235.run(root,tmp_path/"out",*dirs,delete_empty_dirs_flag=True)
    assert not (root/"a/b").exists()
    assert s["final_status"] == v235.WARN_STATUS
    assert s["empty_dir_deleted_count"] >= 1


def test_policy_gate_flags(tmp_path):
    root=tmp_path/"repo"; dirs=make_inputs(root)
    out=tmp_path/"out"; v235.run(root,out,*dirs)
    gate=json.loads((out/"deletion_policy_gate.json").read_text())
    assert gate["broker_action_allowed"] is False
    assert gate["official_adoption_allowed"] is False
