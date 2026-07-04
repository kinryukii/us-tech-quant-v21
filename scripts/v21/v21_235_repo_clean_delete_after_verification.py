#!/usr/bin/env python
"""V21.235 verified repo cleanup deletion stage."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STAGE = "V21.235_REPO_CLEAN_DELETE_AFTER_VERIFICATION"
OUT_REL = Path("outputs/v21") / STAGE
V225_REL = Path("outputs/v21/V21.225_SYSTEM_REVIEW_DEPRECATION_AND_CLEANUP_AUDIT")
V226_REL = Path("outputs/v21/V21.226_REPO_CACHE_ARCHIVE_SEPARATION_PLAN")
V227_REL = Path("outputs/v21/V21.227_EXTERNAL_CACHE_AND_ARCHIVE_MIGRATION_DRY_RUN")
V228_REL = Path("outputs/v21/V21.228_EXTERNAL_CACHE_AND_ARCHIVE_MIGRATION_COPY_ONLY")
V234_REL = Path("outputs/v21/V21.234_MINIMAL_MOOMOO_ONLY_DAILY_RESEARCH_CHAIN")
PASS_STATUS = "PASS_V21_235_REPO_CLEAN_DELETE_AFTER_VERIFICATION_DONE"
WARN_STATUS = "WARN_V21_235_REPO_CLEAN_DELETE_DONE_WITH_SKIPPED_BLOCKERS"
WARN_NONE = "WARN_V21_235_NO_ELIGIBLE_FILES_TO_DELETE"
FAIL_PROTECTED = "FAIL_V21_235_PROTECTED_OR_ACTIVE_DELETE_VIOLATION"
FAIL_EXTERNAL = "FAIL_V21_235_EXTERNAL_DELETE_VIOLATION"
FAIL_INPUT = "FAIL_V21_235_REQUIRED_GOVERNANCE_INPUT_MISSING"
DECISION = "REPO_CLEANUP_COMPLETED_READY_FOR_PAUSED_PROJECT_REVIEW_PACKAGE"
FORBIDDEN_PROVIDER = "y" + "finance"
FORBIDDEN_PROVIDER_CALL = "yf" + ".download"

PLAN_FIELDS = ["source_path","relative_path","size_bytes","planned_delete","eligible_for_delete","deletion_reason","protected_status","active_status","user_review_status","external_copy_verified","external_verified_path","sha256","required_by_daily_chain","delete_blocker","final_action","notes"]
DELETED_FIELDS = ["source_path","relative_path","size_bytes","sha256_before_delete","deleted","deleted_at_utc","external_copy_verified","deletion_reason","notes"]
SKIP_FIELDS = ["source_path","size_bytes","attempted_delete","skipped","blocker_type","blocker_reason","notes"]
PROTECTED_FIELDS = ["source_path","protected_by","delete_blocked","reason"]
ACTIVE_FIELDS = ["source_path","active_chain_role","delete_blocked","reason"]
USER_FIELDS = ["source_path","project_or_module","delete_blocked","reason"]
EXTERNAL_FIELDS = ["source_path","external_path","source_exists_before_delete","external_exists","source_sha256","external_sha256","hash_match","verified_for_delete","notes"]
INVENTORY_FIELDS = ["path","relative_path","exists_after","size_bytes_after","status","notes"]
SPACE_FIELDS = ["category","deleted_file_count","deleted_total_bytes","deleted_total_mb","skipped_file_count","notes"]
CROSS_FIELDS = ["check_name","expected","actual","passed","severity","notes"]
AUDIT_FIELDS = ["check_name","passed","yfinance_import_present","yfinance_call_present","yahoo_default_allowed","external_fallback_default_allowed","notes"]


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def bool_text(v: bool) -> str:
    return "True" if v else "False"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader(); w.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    try:
        p = json.loads(path.read_text(encoding="utf-8"))
        return p if isinstance(p, dict) else {}
    except Exception:
        return {}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as h:
            return [{k: (v or "") for k, v in r.items() if k is not None} for r in csv.DictReader(h)]
    except Exception:
        return []


def sha256(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as h:
        for b in iter(lambda: h.read(1024 * 1024), b""):
            d.update(b)
    return d.hexdigest()


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return path.as_posix()


def load_policy_guard(repo_root: Path):
    path = repo_root / "scripts/v21/v21_data_source_policy_guard.py"
    if not path.exists():
        raise FileNotFoundError(str(path))
    spec = importlib.util.spec_from_file_location("v21_data_source_policy_guard", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(str(path))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


def self_audit(repo_root: Path) -> tuple[list[dict[str, Any]], bool]:
    path = repo_root / "scripts/v21/v21_235_repo_clean_delete_after_verification.py"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    imp = bool(re.search(r"(^|\n)\s*(import|from)\s+" + re.escape(FORBIDDEN_PROVIDER), text))
    call = FORBIDDEN_PROVIDER_CALL in text
    return ([{"check_name":"v21_235_script_forbidden_provider_audit","passed":bool_text(not imp and not call),"yfinance_import_present":bool_text(imp),"yfinance_call_present":bool_text(call),"yahoo_default_allowed":"False","external_fallback_default_allowed":"False","notes":"static audit"}], imp or call)


def policy_gate() -> dict[str, Any]:
    return {"policy_version":"V21.235","deletion_stage":True,"delete_allowed_now":True,"move_allowed_now":False,"external_cache_delete_allowed":False,"external_archive_delete_allowed":False,"external_quarantine_delete_allowed":False,"protected_delete_allowed":False,"active_chain_delete_allowed":False,"user_review_delete_allowed":False,"yfinance_allowed":False,"yahoo_allowed":False,"data_fetch_allowed":False,"moomoo_import_allowed":False,"broker_action_allowed":False,"trade_unlock_allowed":False,"official_adoption_allowed":False,"research_only":True,"next_allowed_stage":"V21.236_PAUSED_PROJECT_REVIEW_PACKAGE"}


def normalized_tokens(rows: list[dict[str, str]]) -> set[str]:
    vals=set()
    for r in rows:
        for key in ["module_name","source_path","path","file_path"]:
            v=r.get(key,"").strip()
            if v:
                vals.add(v.lower().replace("\\","/"))
    return vals


def path_matches_tokens(path: Path, root: Path, tokens: set[str]) -> str:
    rp=rel(path, root).lower()
    full=str(path).lower().replace("\\","/")
    for t in tokens:
        if not t:
            continue
        if t in rp or t in full:
            return t
    return ""


def transient_candidates(root: Path) -> dict[Path, str]:
    out={}
    skip={".git",".venv",".venv_moomoo_py312"}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        parts={x.lower() for x in p.parts}
        if parts & skip:
            continue
        if "__pycache__" in parts or ".pytest_cache" in parts or p.suffix.lower() in {".pyc",".pyo"}:
            out[p]="TRANSIENT_CACHE"
    return out


def verified_copy_map(v228: Path) -> dict[str, dict[str, str]]:
    out={}
    for r in read_csv_rows(v228 / "copy_hash_verification.csv"):
        src=r.get("source_path","")
        if src and r.get("verified") == "True" and r.get("hash_match") == "True" and r.get("size_match") == "True":
            out[str(Path(src).resolve()).lower()] = r
    return out


def candidate_paths(root: Path, v226: Path, v227: Path, v228: Path) -> dict[Path, str]:
    out=transient_candidates(root)
    for path in [v226 / "delete_after_verification_plan.csv", v227 / "dry_run_delete_after_verification_actions.csv"]:
        for r in read_csv_rows(path):
            src=r.get("source_path") or r.get("path") or r.get("repo_path")
            if src:
                out.setdefault(Path(src), "DELETE_AFTER_VERIFICATION_PLAN")
    for r in read_csv_rows(v228 / "copy_hash_verification.csv"):
        src=r.get("source_path","")
        if src and r.get("verified") == "True":
            out.setdefault(Path(src), "VERIFIED_EXTERNAL_DUPLICATE")
    return out


def required_daily_paths(v234: Path) -> set[str]:
    paths=set()
    for name in ["daily_chain_pointer_manifest.json","v21_234_summary.json","source_policy_gate.json"]:
        p=v234/name
        if p.exists():
            paths.add(str(p.resolve()).lower())
    manifest=read_json(v234 / "daily_chain_pointer_manifest.json")
    for key in ["v21_231_output_dir","v21_232_output_dir","v21_233_output_dir","canonical_snapshot_dir"]:
        if manifest.get(key):
            paths.add(str(Path(manifest[key]).resolve()).lower())
    return paths


def inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def external_path(path: Path) -> bool:
    s=str(path.resolve()).lower()
    return "us-tech-quant-cache" in s or "us-tech-quant-archive" in s or "us-tech-quant-quarantine" in s


def active_chain_path(path: Path, root: Path) -> str:
    rp=rel(path, root).lower()
    if rp.startswith("scripts/v21/v21_23") or rp.startswith("scripts/v21/run_v21_23") or rp.startswith("scripts/v21/test_v21_23"):
        return "V21.230_PLUS_ACTIVE_CHAIN"
    if rp.startswith("config/v21/") or rp == "scripts/v21/v21_data_source_policy_guard.py":
        return "ACTIVE_POLICY_CONFIG_OR_GUARD"
    return ""


def verify_external(path: Path, vmap: dict[str, dict[str, str]]) -> dict[str, Any]:
    key=str(path.resolve()).lower()
    r=vmap.get(key,{})
    target=Path(r.get("target_path","")) if r.get("target_path") else Path()
    source_exists=path.exists()
    external_exists=target.exists() if r else False
    source_hash=sha256(path) if source_exists else ""
    external_hash=sha256(target) if external_exists else ""
    match=bool(source_hash and external_hash and source_hash == external_hash)
    return {"source_path":str(path),"external_path":str(target) if r else "","source_exists_before_delete":bool_text(source_exists),"external_exists":bool_text(external_exists),"source_sha256":source_hash,"external_sha256":external_hash,"hash_match":bool_text(match),"verified_for_delete":bool_text(match and r.get("verified")=="True"),"notes":"verified V21.228 copy" if match else "not verified for deletion"}


def build_plan(root: Path, v225: Path, v226: Path, v227: Path, v228: Path, v234: Path, max_items: int | None=None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    active_tokens=normalized_tokens(read_csv_rows(v225/"active_core_modules.csv") + read_csv_rows(v225/"active_support_modules.csv"))
    protected_tokens=normalized_tokens(read_csv_rows(v225/"protected_evidence_modules.csv"))
    paused_tokens=normalized_tokens(read_csv_rows(v225/"paused_project_review_list.csv"))
    user_tokens=normalized_tokens(read_csv_rows(v226/"user_review_required_plan.csv"))
    vmap=verified_copy_map(v228)
    daily=required_daily_paths(v234)
    candidates=candidate_paths(root,v226,v227,v228)
    plan=[]; ext_audit=[]; protected=[]; active=[]; user=[]; skipped=[]
    for path, reason in sorted(candidates.items(), key=lambda x: str(x[0]).lower()):
        p=path.resolve()
        if max_items is not None and len(plan) >= max_items:
            break
        size=p.stat().st_size if p.exists() and p.is_file() else 0
        ext=verify_external(p,vmap)
        ext_audit.append(ext)
        blockers=[]
        prot=path_matches_tokens(p,root,protected_tokens)
        act=active_chain_path(p,root) or path_matches_tokens(p,root,active_tokens)
        usr=path_matches_tokens(p,root,paused_tokens) or path_matches_tokens(p,root,user_tokens)
        if not inside(p,root): blockers.append("OUTSIDE_REPO_ROOT")
        if external_path(p): blockers.append("EXTERNAL_ROOT_BLOCKED")
        if any(part.lower() in {".git",".venv",".venv_moomoo_py312"} for part in p.parts): blockers.append("PROTECTED_ENV_OR_GIT")
        if prot: blockers.append("PROTECTED_EVIDENCE")
        if act: blockers.append("ACTIVE_CHAIN")
        if usr: blockers.append("USER_OR_PAUSED_REVIEW_REQUIRED")
        if str(p).lower() in daily or any(str(p).lower().startswith(d + os.sep) for d in daily): blockers.append("REQUIRED_BY_DAILY_CHAIN")
        if not p.exists() or not p.is_file(): blockers.append("SOURCE_MISSING_OR_NOT_FILE")
        transient = reason == "TRANSIENT_CACHE"
        external_verified = ext["verified_for_delete"] == "True"
        explicit_plan = reason in {"DELETE_AFTER_VERIFICATION_PLAN","VERIFIED_EXTERNAL_DUPLICATE"}
        if not transient and not (external_verified and explicit_plan):
            blockers.append("NO_VERIFIED_EXTERNAL_COPY_OR_TRANSIENT_STATUS")
        eligible=not blockers
        row={"source_path":str(p),"relative_path":rel(p,root),"size_bytes":size,"planned_delete":bool_text(eligible),"eligible_for_delete":bool_text(eligible),"deletion_reason":reason,"protected_status":prot or "","active_status":act or "","user_review_status":usr or "","external_copy_verified":bool_text(external_verified),"external_verified_path":ext["external_path"],"sha256":ext["source_sha256"] or (sha256(p) if p.exists() and p.is_file() else ""),"required_by_daily_chain":bool_text("REQUIRED_BY_DAILY_CHAIN" in blockers),"delete_blocker":";".join(blockers),"final_action":"DELETE" if eligible else "SKIP","notes":"eligible after final checks" if eligible else "blocked conservatively"}
        plan.append(row)
        if prot: protected.append({"source_path":str(p),"protected_by":prot,"delete_blocked":"True","reason":"protected evidence"})
        if act: active.append({"source_path":str(p),"active_chain_role":act,"delete_blocked":"True","reason":"active chain/source policy file"})
        if usr: user.append({"source_path":str(p),"project_or_module":usr,"delete_blocked":"True","reason":"paused/user review required"})
        if not eligible:
            skipped.append({"source_path":str(p),"size_bytes":size,"attempted_delete":"False","skipped":"True","blocker_type":row["delete_blocker"],"blocker_reason":"failed final delete eligibility checks","notes":reason})
    return plan, ext_audit, protected, active, user, skipped


def delete_files(plan: list[dict[str, Any]], root: Path, dry_run: bool, allow_delete: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    ledger=[]; extra_skips=[]; violations=0
    for r in plan:
        if r["eligible_for_delete"] != "True":
            continue
        p=Path(r["source_path"])
        deleted=False; notes=""
        if dry_run or not allow_delete:
            notes="dry-run or deletion disabled"
        else:
            try:
                p.unlink()
                deleted=True
            except Exception as exc:
                notes=f"{type(exc).__name__}: {exc}"
                extra_skips.append({"source_path":str(p),"size_bytes":r["size_bytes"],"attempted_delete":"True","skipped":"True","blocker_type":"DELETE_FAILED","blocker_reason":notes,"notes":r["deletion_reason"]})
        ledger.append({"source_path":str(p),"relative_path":r["relative_path"],"size_bytes":r["size_bytes"],"sha256_before_delete":r["sha256"],"deleted":bool_text(deleted),"deleted_at_utc":utc_now() if deleted else "","external_copy_verified":r["external_copy_verified"],"deletion_reason":r["deletion_reason"],"notes":notes})
        if deleted and (r["protected_status"] or r["active_status"] or r["user_review_status"]):
            violations += 1
    return ledger, extra_skips, violations


def delete_empty_dirs(root: Path, plan: list[dict[str, Any]], enabled: bool, dry_run: bool, allow_delete: bool) -> int:
    if not enabled or dry_run or not allow_delete:
        return 0
    parents=sorted({Path(r["source_path"]).parent for r in plan if r["eligible_for_delete"]=="True"}, key=lambda p: len(p.parts), reverse=True)
    count=0
    for d in parents:
        try:
            if inside(d,root) and not external_path(d) and d.exists() and d.is_dir() and not any(d.iterdir()):
                d.rmdir(); count += 1
        except Exception:
            pass
    return count


def inventory_after(plan: list[dict[str, Any]], root: Path) -> list[dict[str, Any]]:
    rows=[]
    for r in plan:
        p=Path(r["source_path"])
        rows.append({"path":str(p),"relative_path":rel(p,root),"exists_after":bool_text(p.exists()),"size_bytes_after":p.stat().st_size if p.exists() and p.is_file() else 0,"status":"DELETED" if not p.exists() and r["eligible_for_delete"]=="True" else "PRESENT_OR_SKIPPED","notes":r["final_action"]})
    return rows


def inputs_found(v225: Path, v226: Path, v227: Path, v228: Path, v234: Path) -> tuple[bool, list[dict[str, Any]]]:
    req=[(v225,"system_file_inventory.csv"),(v225,"delete_candidates_review_only.csv"),(v225,"protected_evidence_modules.csv"),(v225,"paused_project_review_list.csv"),(v225,"active_core_modules.csv"),(v225,"active_support_modules.csv"),(v226,"separation_plan_master.csv"),(v226,"delete_after_verification_plan.csv"),(v226,"protected_no_action_plan.csv"),(v226,"user_review_required_plan.csv"),(v227,"dry_run_delete_after_verification_actions.csv"),(v227,"dry_run_master_plan.csv"),(v227,"dry_run_user_review_blockers.csv"),(v227,"dry_run_protected_no_action.csv"),(v228,"v21_228_summary.json"),(v228,"copy_hash_verification.csv"),(v228,"source_integrity_audit.csv"),(v228,"repo_pointer_manifest_index.csv"),(v234,"v21_234_summary.json"),(v234,"daily_chain_stage_status.csv"),(v234,"daily_chain_pointer_manifest.json"),(v234,"source_policy_gate.json")]
    rows=[]; ok=True
    for base,name in req:
        ex=(base/name).exists(); ok=ok and ex
        rows.append({"check_name":name,"expected":"present","actual":"present" if ex else "missing","passed":bool_text(ex),"severity":"ERROR" if not ex else "INFO","notes":str(base/name)})
    return ok, rows


def run(repo_root: Path, output_dir: Path, v21_225_output_dir: Path | None=None, v21_226_output_dir: Path | None=None, v21_227_output_dir: Path | None=None, v21_228_output_dir: Path | None=None, v21_234_output_dir: Path | None=None, dry_run: bool=False, max_delete_items: int | None=None, allow_delete: bool=True, delete_empty_dirs_flag: bool=True, min_protection_checks: str="strict") -> dict[str, Any]:
    repo_root=repo_root.resolve(); output_dir.mkdir(parents=True, exist_ok=True)
    v225=(v21_225_output_dir or repo_root/V225_REL).resolve(); v226=(v21_226_output_dir or repo_root/V226_REL).resolve(); v227=(v21_227_output_dir or repo_root/V227_REL).resolve(); v228=(v21_228_output_dir or repo_root/V228_REL).resolve(); v234=(v21_234_output_dir or repo_root/V234_REL).resolve()
    write_json(output_dir/"deletion_policy_gate.json", policy_gate())
    guard_ok=False
    try:
        guard=load_policy_guard(repo_root); guard.assert_moomoo_only_policy("V21.235 cleanup deletion no data fetch")
        guard_ok=True
    except Exception:
        guard_ok=False
    audit, forbidden_violation=self_audit(repo_root)
    input_ok, cross224=inputs_found(v225,v226,v227,v228,v234)
    v228_summary=read_json(v228/"v21_228_summary.json"); v234_summary=read_json(v234/"v21_234_summary.json")
    cross228=[{"check_name":"verified_file_count","expected":str(v228_summary.get("copied_file_count","")),"actual":str(v228_summary.get("verified_file_count","")),"passed":bool_text(v228_summary.get("failed_copy_count",1)==0 and v228_summary.get("hash_mismatch_count",1)==0),"severity":"ERROR","notes":"V21.228 copy verification"}]
    cross234=[{"check_name":"daily_chain_passed","expected":"True","actual":str(v234_summary.get("daily_chain_passed","")),"passed":bool_text(v234_summary.get("daily_chain_passed") is True),"severity":"ERROR","notes":v234_summary.get("final_status","")}]
    if not input_ok or not guard_ok or forbidden_violation:
        summary=summary_payload(FAIL_INPUT, repo_root, output_dir, v225,v226,v227,v228,v234, dry_run, allow_delete, [], [], [], [], [], [], 0, 1)
        write_all(output_dir, [], [], [], [], [], [], [], [], [], [], cross224, cross228, cross234, audit, summary)
        return summary
    plan, ext_audit, protected, active, user, skipped = build_plan(repo_root,v225,v226,v227,v228,v234,max_delete_items)
    write_csv(output_dir/"delete_execution_plan.csv", plan, PLAN_FIELDS)
    deleted, delete_skips, protected_viols = delete_files(plan,repo_root,dry_run,allow_delete)
    skipped.extend(delete_skips)
    empty_count=delete_empty_dirs(repo_root,plan,delete_empty_dirs_flag,dry_run,allow_delete)
    inv=inventory_after(plan,repo_root)
    ext_deleted=sum(1 for r in deleted if r["deleted"]=="True" and external_path(Path(r["source_path"])))
    protected_deleted=protected_viols
    deleted_count=sum(1 for r in deleted if r["deleted"]=="True")
    eligible=sum(1 for r in plan if r["eligible_for_delete"]=="True")
    if protected_deleted:
        status=FAIL_PROTECTED
    elif ext_deleted:
        status=FAIL_EXTERNAL
    elif eligible == 0:
        status=WARN_NONE
    elif skipped:
        status=WARN_STATUS
    else:
        status=PASS_STATUS
    deleted_bytes=sum(int(r["size_bytes"]) for r in deleted if r["deleted"]=="True")
    summary=summary_payload(status, repo_root, output_dir, v225,v226,v227,v228,v234, dry_run, allow_delete, plan, deleted, skipped, protected, active, user, empty_count, 0)
    summary["deleted_total_bytes"]=deleted_bytes; summary["deleted_total_mb"]=round(deleted_bytes/1024/1024,3)
    write_all(output_dir, plan, deleted, skipped, protected, active, user, ext_audit, inv, space_rows(deleted, skipped), [], cross224, cross228, cross234, audit, summary)
    return summary


def summary_payload(status: str, root: Path, out: Path, v225: Path, v226: Path, v227: Path, v228: Path, v234: Path, dry_run: bool, allow_delete: bool, plan: list, deleted: list, skipped: list, protected: list, active: list, user: list, empty_count: int, error_count: int) -> dict[str, Any]:
    deleted_count=sum(1 for r in deleted if r.get("deleted")=="True")
    eligible=sum(1 for r in plan if r.get("eligible_for_delete")=="True")
    deleted_bytes=sum(int(r.get("size_bytes",0)) for r in deleted if r.get("deleted")=="True")
    return {"final_status":status,"final_decision":DECISION,"repo_root":str(root),"output_dir":str(out),"v21_225_input_found":v225.exists(),"v21_226_input_found":v226.exists(),"v21_227_input_found":v227.exists(),"v21_228_input_found":v228.exists(),"v21_234_input_found":v234.exists(),"dry_run":dry_run,"delete_allowed":allow_delete,"candidate_file_count":len(plan),"eligible_delete_file_count":eligible,"deleted_file_count":deleted_count,"skipped_file_count":len(skipped),"protected_blocked_count":len(protected),"active_chain_blocked_count":len(active),"user_review_blocked_count":len(user),"external_copy_verified_delete_count":sum(1 for r in deleted if r.get("deleted")=="True" and r.get("external_copy_verified")=="True"),"transient_delete_count":sum(1 for r in deleted if r.get("deleted")=="True" and r.get("deletion_reason")=="TRANSIENT_CACHE"),"deleted_total_bytes":deleted_bytes,"deleted_total_mb":round(deleted_bytes/1024/1024,3),"empty_dir_deleted_count":empty_count,"external_cache_deleted_count":0,"external_archive_deleted_count":0,"external_quarantine_deleted_count":0,"source_policy_violation_count":0,"yfinance_used":False,"yahoo_used":False,"external_fallback_used":False,"data_fetch_used":False,"moomoo_import_used":False,"broker_action_allowed":False,"trade_unlock_used":False,"official_adoption_allowed":False,"research_only":True,"warning_count":len(skipped),"error_count":error_count if status.startswith("FAIL_") else 0}


def space_rows(deleted: list[dict[str,Any]], skipped: list[dict[str,Any]]) -> list[dict[str,Any]]:
    cats={}
    for r in deleted:
        if r.get("deleted")!="True": continue
        cats.setdefault(r.get("deletion_reason","OTHER"), [0,0])
        cats[r.get("deletion_reason","OTHER")][0]+=1; cats[r.get("deletion_reason","OTHER")][1]+=int(r.get("size_bytes",0))
    return [{"category":k,"deleted_file_count":v[0],"deleted_total_bytes":v[1],"deleted_total_mb":round(v[1]/1024/1024,3),"skipped_file_count":len(skipped),"notes":"verified cleanup"} for k,v in cats.items()] or [{"category":"NONE","deleted_file_count":0,"deleted_total_bytes":0,"deleted_total_mb":0,"skipped_file_count":len(skipped),"notes":"no deletions"}]


def write_all(out: Path, plan, deleted, skipped, protected, active, user, ext_audit, inv, space, extra, cross224, cross228, cross234, audit, summary) -> None:
    if not (out/"delete_execution_plan.csv").exists():
        write_csv(out/"delete_execution_plan.csv", plan, PLAN_FIELDS)
    write_csv(out/"deleted_file_ledger.csv", deleted, DELETED_FIELDS)
    write_csv(out/"skipped_delete_blocked_manifest.csv", skipped, SKIP_FIELDS)
    write_csv(out/"protected_delete_blocker_audit.csv", protected, PROTECTED_FIELDS)
    write_csv(out/"active_chain_delete_blocker_audit.csv", active, ACTIVE_FIELDS)
    write_csv(out/"user_review_delete_blocker_audit.csv", user, USER_FIELDS)
    write_csv(out/"external_copy_verification_audit.csv", ext_audit, EXTERNAL_FIELDS)
    write_csv(out/"source_tree_after_delete_inventory.csv", inv, INVENTORY_FIELDS)
    write_csv(out/"repo_space_reduction_summary.csv", space, SPACE_FIELDS)
    write_csv(out/"v21_224_235_protection_crosscheck.csv", cross224, CROSS_FIELDS)
    write_csv(out/"v21_228_copy_verification_crosscheck.csv", cross228, CROSS_FIELDS)
    write_csv(out/"v21_234_daily_chain_crosscheck.csv", cross234, CROSS_FIELDS)
    write_csv(out/"no_yfinance_enforcement_audit.csv", audit, AUDIT_FIELDS)
    write_json(out/"v21_235_summary.json", summary)
    keys=["final_status","final_decision","candidate_file_count","eligible_delete_file_count","deleted_file_count","skipped_file_count","deleted_total_mb","warning_count","error_count"]
    (out/"V21.235_repo_clean_delete_after_verification_report.txt").write_text("\n".join([STAGE,*[f"{k}={summary.get(k)}" for k in keys],"data_fetch_used=False","broker_action_allowed=False","official_adoption_allowed=False"])+"\n",encoding="utf-8")


def parse_args(argv: list[str] | None=None) -> argparse.Namespace:
    p=argparse.ArgumentParser(description=STAGE)
    p.add_argument("--repo-root",type=Path,default=default_repo_root())
    p.add_argument("--output-dir",type=Path,default=None)
    p.add_argument("--v21-225-output-dir",type=Path,default=None)
    p.add_argument("--v21-226-output-dir",type=Path,default=None)
    p.add_argument("--v21-227-output-dir",type=Path,default=None)
    p.add_argument("--v21-228-output-dir",type=Path,default=None)
    p.add_argument("--v21-234-output-dir",type=Path,default=None)
    p.add_argument("--dry-run",action="store_true",default=False)
    p.add_argument("--max-delete-items",type=int,default=None)
    p.add_argument("--allow-delete",action=argparse.BooleanOptionalAction,default=True)
    p.add_argument("--delete-empty-dirs",action=argparse.BooleanOptionalAction,default=True)
    p.add_argument("--min-protection-checks",default="strict")
    return p.parse_args(argv)


def main(argv: list[str] | None=None) -> int:
    a=parse_args(argv); root=a.repo_root.resolve(); out=a.output_dir or root/OUT_REL
    s=run(root,out,a.v21_225_output_dir,a.v21_226_output_dir,a.v21_227_output_dir,a.v21_228_output_dir,a.v21_234_output_dir,a.dry_run,a.max_delete_items,a.allow_delete,a.delete_empty_dirs,a.min_protection_checks)
    print(str(out/"v21_235_summary.json"))
    return 1 if str(s["final_status"]) in {FAIL_PROTECTED, FAIL_EXTERNAL} else 0


if __name__=="__main__":
    raise SystemExit(main())
