#!/usr/bin/env python
"""V21.222 minimal keepset deep attribution and size reduction plan.

Audit-only. Attributes remaining footprint inside the minimal current-chain
keepset, environments, state, scripts, and residual outputs. No deletion,
compression, movement, price refresh, canonical mutation, OpenD connection,
adoption change, or broker action is performed.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path(r"D:\us-tech-quant")
STAGE = "V21.222_MINIMAL_KEEPSET_DEEP_ATTRIBUTION_AND_SIZE_REDUCTION_PLAN"
OUT_REL = Path("outputs/v21/V21.222_MINIMAL_KEEPSET_DEEP_ATTRIBUTION_AND_SIZE_REDUCTION_PLAN")
TARGET_REPO_SIZE_BYTES = 1_000_000_000
V221_SUMMARY_REL = Path("outputs/v21/V21.221_MINIMAL_CURRENT_CHAIN_KEEPSET_AND_REPO_BODY_PRUNE_PLAN/v21_221_summary.json")
PROTECTED_REQUIRED = [
    "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT",
    "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME",
    "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH",
    "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv",
    ".venv",
    "scripts",
]
COMPONENT_FIELDS = [
    "component_name", "component_path", "recursive_size_bytes", "file_count", "directory_count",
    "largest_file_path", "largest_file_size_bytes", "csv_size_bytes", "json_size_bytes",
    "txt_size_bytes", "parquet_size_bytes", "py_size_bytes", "cache_tmp_size_bytes",
    "current_chain_required", "protected_flag", "can_reduce_without_breaking_current_chain",
    "proposed_reduction_method", "estimated_savings_bytes", "risk_level", "rationale",
]
FILE_FIELDS = ["component_name", "file_path", "file_size_bytes", "file_extension", "modified_time"]
PRESENCE_FIELDS = ["protected_key", "expected_path", "exact_exists", "alias_discovery_attempted", "alias_candidate_count", "resolved_exists", "resolved_protected_path", "resolution_method", "warning_reason"]
ALT_FIELDS = ["current_venv_python", "import_ok", "moomoo_version", "exception_type", "exception_message", "permission_log_blocker_flag", "alt_venv_exists", "alt_venv_size_bytes", "recommended_action"]
GAP_FIELDS = ["metric", "value"]
ACTION_FIELDS = ["action_name", "risk_level", "estimated_savings_bytes", "requires_future_approval", "rationale"]
STATE_FIELDS = ["path", "size_bytes", "file_count", "directory_count", "state_class", "rationale"]
VENV_FIELDS = ["package_path", "size_bytes", "file_count", "directory_count", "package_name"]


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def str_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def iter_files(path: Path) -> list[Path]:
    try:
        if path.is_file():
            return [path]
        return sorted([p for p in path.rglob("*") if p.is_file()], key=lambda p: p.as_posix())
    except OSError:
        return []


def iter_dirs(path: Path) -> list[Path]:
    try:
        if path.is_dir():
            return sorted([p for p in path.rglob("*") if p.is_dir()], key=lambda p: p.as_posix())
    except OSError:
        pass
    return []


def metrics(path: Path, root: Path) -> dict[str, Any]:
    files = iter_files(path) if path.exists() else []
    dirs = iter_dirs(path) if path.exists() else []
    totals = defaultdict(int)
    size = 0
    largest = ("", 0)
    for f in files:
        try:
            stat = f.stat()
        except OSError:
            continue
        size += stat.st_size
        ext = f.suffix.lower()
        name = f.name.lower()
        if ext == ".csv":
            totals["csv"] += stat.st_size
        elif ext == ".json":
            totals["json"] += stat.st_size
        elif ext in {".txt", ".md", ".log"}:
            totals["txt"] += stat.st_size
        elif ext == ".parquet":
            totals["parquet"] += stat.st_size
        elif ext == ".py":
            totals["py"] += stat.st_size
        if any(t in rel(f, root).lower() for t in ["cache", "tmp", "__pycache__", "pytest_tmp"]):
            totals["cache_tmp"] += stat.st_size
        if stat.st_size > largest[1]:
            largest = (rel(f, root), stat.st_size)
    return {
        "recursive_size_bytes": size, "file_count": len(files), "directory_count": len(dirs),
        "largest_file_path": largest[0], "largest_file_size_bytes": largest[1],
        "csv_size_bytes": totals["csv"], "json_size_bytes": totals["json"],
        "txt_size_bytes": totals["txt"], "parquet_size_bytes": totals["parquet"],
        "py_size_bytes": totals["py"], "cache_tmp_size_bytes": totals["cache_tmp"],
    }


def v21_201_alias_ok(path: Path) -> bool:
    tokens = {"dram", "moomoo", "plan", "r4", "daily"}
    return any(t in path.name.lower() for t in tokens)


def protected_presence(root: Path) -> list[dict[str, Any]]:
    rows = []
    out21 = root / "outputs/v21"
    for item in PROTECTED_REQUIRED:
        expected = root / item
        exact = expected.exists()
        attempted = False
        candidates: list[Path] = []
        resolved = expected if exact else None
        method = "EXACT_PATH" if exact else "UNRESOLVED"
        warning = "" if exact else "EXPECTED_PATH_MISSING"
        if not exact and item.startswith("outputs/v21/V21.") and out21.exists():
            attempted = True
            sid = Path(item).name.split("_", 1)[0]
            candidates = [p for p in out21.iterdir() if p.is_dir() and p.name.startswith(sid) and (sid != "V21.201" or v21_201_alias_ok(p))]
            if candidates:
                resolved = max(candidates, key=lambda p: p.stat().st_mtime)
                method = "ALIAS_DISCOVERY_NEWEST_MODIFIED"
                warning = ""
        rows.append({"protected_key": Path(item).name, "expected_path": item, "exact_exists": exact, "alias_discovery_attempted": attempted, "alias_candidate_count": len(candidates), "resolved_exists": bool(resolved and resolved.exists()), "resolved_protected_path": rel(resolved, root) if resolved else "", "resolution_method": method, "warning_reason": warning})
    return rows


def component(root: Path, name: str, relpath: str, current: bool, protected: bool, method: str, savings: int, risk: str, rationale: str) -> dict[str, Any]:
    path = root / relpath
    m = metrics(path, root)
    return {"component_name": name, "component_path": relpath, **m, "current_chain_required": current, "protected_flag": protected, "can_reduce_without_breaking_current_chain": risk == "LOW", "proposed_reduction_method": method, "estimated_savings_bytes": savings, "risk_level": risk, "rationale": rationale}


def components(root: Path) -> list[dict[str, Any]]:
    rows = [
        component(root, "V21.197", "outputs/v21/V21.197_FINAL_BROAD_DATE_ABCDE_RERUN_AFTER_MANUAL_IMPORT", True, True, "KEEP_AS_IS", 0, "LOW", "Current ABCDE rerun output hard kept."),
        component(root, "V21.199_R4", "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME", True, True, "COMPRESS_CURRENT_CHAIN_RAW_KLINE_WITH_INDEX", int(metrics(root / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME", root)["recursive_size_bytes"] * 0.4), "MEDIUM", "Large current Moomoo/kline stage; future indexed compaction may reduce size."),
        component(root, "V21.201", "outputs/v21/V21.201_DRAM_MOOMOO_R4_DATE_ALIGNMENT_AND_PLAN_REFRESH", True, True, "COMPACT_CURRENT_CHAIN_OUTPUTS_KEEP_LATEST_ONLY", 0, "MEDIUM", "Current DRAM plan output hard kept, only future compaction after contract review."),
        component(root, "canonical_price", "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv", True, True, "MOVE_CANONICAL_TO_EXTERNAL_DATA_STORE_WITH_POINTER", int(metrics(root / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv", root)["recursive_size_bytes"] * 0.9), "HIGH", "Canonical source can only be externalized with explicit pointer contract."),
        component(root, "state", "state", True, False, "STATE_PRUNE_NONCURRENT_CACHE", int(metrics(root / "state", root)["cache_tmp_size_bytes"]), "LOW", "Only explicit cache/tmp state is low risk."),
        component(root, "current_venv", ".venv", True, True, "REBUILD_SLIM_CURRENT_VENV", int(metrics(root / ".venv", root)["recursive_size_bytes"] * 0.35), "MEDIUM", "Slim rebuild may save package/test cache size but affects runtime environment."),
        component(root, "alt_venv", ".venv_moomoo_py312", False, False, "RETIRE_ALT_VENV_AFTER_LOG_PERMISSION_FIX", metrics(root / ".venv_moomoo_py312", root)["recursive_size_bytes"], "MEDIUM", "Blocked until current Moomoo import is clean."),
        component(root, "scripts", "scripts", True, True, "KEEP_AS_IS", 0, "LOW", "Source code and tests hard kept."),
        component(root, "remaining_outputs_v21", "outputs/v21", False, False, "DELETE_DUPLICATE_NONCURRENT_FILES_INSIDE_PROTECTED_STAGE", 0, "MANUAL", "Residual outputs need per-stage keep/delete contract."),
    ]
    return rows


def largest_files(root: Path, comps: list[dict[str, Any]], limit: int = 200) -> list[dict[str, Any]]:
    roots = [root / r["component_path"] for r in comps]
    out = []
    for c, p in zip(comps, roots):
        for f in iter_files(p):
            try:
                st = f.stat()
            except OSError:
                continue
            out.append({"component_name": c["component_name"], "file_path": rel(f, root), "file_size_bytes": st.st_size, "file_extension": f.suffix.lower(), "modified_time": datetime.fromtimestamp(st.st_mtime, timezone.utc).replace(microsecond=0).isoformat()})
    return sorted(out, key=lambda r: int(r["file_size_bytes"]), reverse=True)[:limit]


def state_breakdown(root: Path) -> list[dict[str, Any]]:
    state = root / "state"
    rows = []
    if state.exists():
        for child in sorted(state.iterdir(), key=lambda p: p.name):
            m = metrics(child, root)
            cls = "NONCURRENT_CACHE" if any(t in child.name.lower() for t in ["cache", "tmp", "temp", "checkpoint"]) else "CURRENT_OR_UNKNOWN_STATE"
            rows.append({"path": rel(child, root), "size_bytes": m["recursive_size_bytes"], "file_count": m["file_count"], "directory_count": m["directory_count"], "state_class": cls, "rationale": "Name-based cache/state split; no mutation."})
    return rows


def venv_packages(root: Path) -> list[dict[str, Any]]:
    site_roots = list((root / ".venv").glob("Lib/site-packages"))
    rows = []
    for site in site_roots:
        for child in sorted(site.iterdir(), key=lambda p: p.name.lower()) if site.exists() else []:
            if child.name.startswith("__"):
                continue
            m = metrics(child, root)
            rows.append({"package_path": rel(child, root), "size_bytes": m["recursive_size_bytes"], "file_count": m["file_count"], "directory_count": m["directory_count"], "package_name": child.name})
    return sorted(rows, key=lambda r: int(r["size_bytes"]), reverse=True)


def moomoo_import_check(root: Path) -> dict[str, Any]:
    py = root / ".venv/Scripts/python.exe"
    out = {"current_venv_python": str(py), "import_ok": False, "moomoo_version": "", "exception_type": "", "exception_message": "", "permission_log_blocker_flag": False, "alt_venv_exists": (root / ".venv_moomoo_py312").exists(), "alt_venv_size_bytes": metrics(root / ".venv_moomoo_py312", root)["recursive_size_bytes"], "recommended_action": ""}
    if not py.exists():
        out["exception_type"] = "PythonMissing"
        out["recommended_action"] = "KEEP_ALT_VENV"
        return out
    code = "import json\ntry:\n import os; import moomoo\n print(json.dumps({'ok': True, 'version': getattr(moomoo, '__version__', 'NO_VERSION_ATTR')}))\nexcept Exception as e:\n print(json.dumps({'ok': False, 'etype': type(e).__name__, 'msg': str(e)}))\n"
    try:
        p = subprocess.run([str(py), "-c", code], capture_output=True, text=True, timeout=30, check=False)
        payload = json.loads((p.stdout or "{}").splitlines()[-1])
        out["import_ok"] = bool(payload.get("ok"))
        out["moomoo_version"] = str(payload.get("version", ""))
        out["exception_type"] = str(payload.get("etype", ""))
        out["exception_message"] = str(payload.get("msg", ""))
    except Exception as exc:
        out["exception_type"] = type(exc).__name__
        out["exception_message"] = str(exc)
    out["permission_log_blocker_flag"] = "Permission" in out["exception_type"] and "com.moomoo.OpenD" in out["exception_message"]
    out["recommended_action"] = "FIX_MOOMOO_LOG_PERMISSION_OR_REDIRECT_LOG_DIR_BEFORE_ALT_VENV_RETIREMENT" if out["permission_log_blocker_flag"] or not out["import_ok"] else "ALT_VENV_RETIREMENT_REVIEW_CAN_CONTINUE"
    return out


def gap_analysis(root: Path, comps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    repo = metrics(root, root)["recursive_size_bytes"]
    v221 = read_json(root / V221_SUMMARY_REL)
    savings_v221 = int(v221.get("prune_candidate_size_bytes", 0) or 0)
    alt = next((r for r in comps if r["component_name"] == "alt_venv"), {})
    state = next((r for r in comps if r["component_name"] == "state"), {})
    venv = next((r for r in comps if r["component_name"] == "current_venv"), {})
    current_chain = sum(int(r["estimated_savings_bytes"]) for r in comps if r["proposed_reduction_method"].startswith("COMPACT") or r["proposed_reduction_method"].startswith("COMPRESS"))
    external = next((r for r in comps if r["component_name"] == "canonical_price"), {})
    best = repo - savings_v221 - int(alt.get("recursive_size_bytes", 0)) - int(state.get("estimated_savings_bytes", 0)) - int(venv.get("estimated_savings_bytes", 0)) - current_chain - int(external.get("estimated_savings_bytes", 0))
    pairs = {
        "current_repo_size": repo,
        "target_size": TARGET_REPO_SIZE_BYTES,
        "gap_to_target": max(0, repo - TARGET_REPO_SIZE_BYTES),
        "savings_from_v21_221_if_executed": savings_v221,
        "savings_from_alt_venv_if_retired": int(alt.get("recursive_size_bytes", 0)),
        "savings_from_state_prune": int(state.get("estimated_savings_bytes", 0)),
        "savings_from_slim_venv_rebuild": int(venv.get("estimated_savings_bytes", 0)),
        "savings_from_current_chain_output_compaction": current_chain,
        "savings_from_externalizing_canonical_or_kline": int(external.get("estimated_savings_bytes", 0)),
        "projected_best_case_repo_size": max(0, best),
    }
    return [{"metric": k, "value": v} for k, v in pairs.items()]


def next_actions(comps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"action_name": r["proposed_reduction_method"], "risk_level": r["risk_level"], "estimated_savings_bytes": r["estimated_savings_bytes"], "requires_future_approval": True, "rationale": r["rationale"]} for r in comps if r["proposed_reduction_method"] != "KEEP_AS_IS"]


def policy_flags() -> dict[str, Any]:
    return {"research_only": True, "audit_only": True, "dry_run": True, "aggressive_storage_cleanup": True, "deletion_performed": False, "compression_performed": False, "archive_movement_performed": False, "price_refresh_performed": False, "canonical_mutation_performed": False, "moomoo_broker_connection_performed": False, "broker_action_allowed": False, "official_adoption_allowed": False, "protected_outputs_modified": False}


def summarize(root: Path, comps: list[dict[str, Any]], presence_missing: int, gap: list[dict[str, Any]]) -> dict[str, Any]:
    repo = metrics(root, root)["recursive_size_bytes"]
    by_name = {r["component_name"]: r for r in comps}
    largest = max(comps, key=lambda r: int(r["recursive_size_bytes"])) if comps else {}
    low = sum(int(r["estimated_savings_bytes"]) for r in comps if r["risk_level"] == "LOW")
    med = sum(int(r["estimated_savings_bytes"]) for r in comps if r["risk_level"] == "MEDIUM")
    high = sum(int(r["estimated_savings_bytes"]) for r in comps if r["risk_level"] == "HIGH")
    best = int(next((r["value"] for r in gap if r["metric"] == "projected_best_case_repo_size"), repo))
    if presence_missing:
        status = "FAIL_V21_222_PROTECTED_PATH_MISSING"
        decision = "MINIMAL_KEEPSET_ATTRIBUTION_FAILED_PROTECTED_PATH_MISSING"
    elif repo - low > TARGET_REPO_SIZE_BYTES:
        status = "WARN_V21_222_1GB_REQUIRES_MEDIUM_OR_HIGH_RISK_ACTIONS"
        decision = "MINIMAL_KEEPSET_ATTRIBUTION_READY_1GB_REQUIRES_RISK_ACCEPTANCE"
    else:
        status = "PASS_V21_222_MINIMAL_KEEPSET_ATTRIBUTION_READY"
        decision = "MINIMAL_KEEPSET_ATTRIBUTION_READY_NEXT_ACTIONS_IDENTIFIED"
    return {"stage": STAGE, "repo_total_size_bytes_now": repo, "target_repo_size_bytes": TARGET_REPO_SIZE_BYTES, "gap_to_1gb_bytes": max(0, repo - TARGET_REPO_SIZE_BYTES), "minimal_keepset_size_bytes": sum(int(r["recursive_size_bytes"]) for r in comps if r["protected_flag"] or r["current_chain_required"]), "largest_minimal_keepset_component": largest.get("component_name", ""), "largest_minimal_keepset_component_size_bytes": int(largest.get("recursive_size_bytes", 0) or 0), "v21_197_size_bytes": int(by_name.get("V21.197", {}).get("recursive_size_bytes", 0) or 0), "v21_199_r4_size_bytes": int(by_name.get("V21.199_R4", {}).get("recursive_size_bytes", 0) or 0), "v21_201_size_bytes": int(by_name.get("V21.201", {}).get("recursive_size_bytes", 0) or 0), "canonical_price_size_bytes": int(by_name.get("canonical_price", {}).get("recursive_size_bytes", 0) or 0), "state_size_bytes": int(by_name.get("state", {}).get("recursive_size_bytes", 0) or 0), "venv_size_bytes": int(by_name.get("current_venv", {}).get("recursive_size_bytes", 0) or 0), "alt_venv_size_bytes": int(by_name.get("alt_venv", {}).get("recursive_size_bytes", 0) or 0), "scripts_size_bytes": int(by_name.get("scripts", {}).get("recursive_size_bytes", 0) or 0), "estimated_safe_savings_without_current_chain_risk": low, "estimated_medium_risk_savings": med, "estimated_high_risk_savings": high, "projected_best_case_repo_size": best, "target_1gb_reachable_without_externalization": repo - low - med <= TARGET_REPO_SIZE_BYTES, "target_1gb_reachable_with_externalization": best <= TARGET_REPO_SIZE_BYTES, "protected_path_missing_count": presence_missing, "deletion_allowed_in_this_run": False, "compression_allowed_in_this_run": False, "final_status": status, "final_decision": decision, **policy_flags()}


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [STAGE, f"final_status={summary['final_status']}", f"final_decision={summary['final_decision']}", f"repo_total_size_bytes_now={summary['repo_total_size_bytes_now']}", f"gap_to_1gb_bytes={summary['gap_to_1gb_bytes']}", f"projected_best_case_repo_size={summary['projected_best_case_repo_size']}", "deletion_allowed_in_this_run=false", "compression_allowed_in_this_run=false"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(repo_root: Path = DEFAULT_ROOT, out_dir: Path | None = None, simulate_exception: bool = False) -> dict[str, Any]:
    root = repo_root.resolve()
    output = out_dir or (root / OUT_REL)
    output.mkdir(parents=True, exist_ok=True)
    try:
        if simulate_exception:
            raise RuntimeError("simulated V21.222 failure")
        presence = protected_presence(root)
        missing = [r for r in presence if not str_bool(r["resolved_exists"])]
        comps = components(root)
        gap = gap_analysis(root, comps)
        summary = summarize(root, comps, len(missing), gap)
        write_csv(output / "minimal_keepset_component_size_breakdown.csv", comps, COMPONENT_FIELDS)
        write_csv(output / "minimal_keepset_largest_files.csv", largest_files(root, comps), FILE_FIELDS)
        for name, fname in [("V21.197", "v21_197_deep_size_breakdown.csv"), ("V21.199_R4", "v21_199_r4_deep_size_breakdown.csv"), ("V21.201", "v21_201_deep_size_breakdown.csv"), ("canonical_price", "canonical_price_size_breakdown.csv")]:
            write_csv(output / fname, [r for r in comps if r["component_name"] == name], COMPONENT_FIELDS)
        write_csv(output / "state_current_vs_noncurrent_breakdown.csv", state_breakdown(root), STATE_FIELDS)
        write_csv(output / "venv_package_size_breakdown.csv", venv_packages(root), VENV_FIELDS)
        write_csv(output / "alt_venv_retirement_blocker_recheck.csv", [moomoo_import_check(root)], ALT_FIELDS)
        write_csv(output / "repo_1gb_gap_analysis.csv", gap, GAP_FIELDS)
        write_csv(output / "next_reduction_action_plan.csv", next_actions(comps), ACTION_FIELDS)
        write_csv(output / "protected_path_presence_check.csv", presence, PRESENCE_FIELDS)
        write_json(output / "v21_222_summary.json", summary)
        write_report(output / "V21.222_minimal_keepset_deep_attribution_report.txt", summary)
    except Exception as exc:
        summary = {"stage": STAGE, "final_status": "FAIL_V21_222_ATTRIBUTION_EXCEPTION", "final_decision": "MINIMAL_KEEPSET_ATTRIBUTION_FAILED", "error_type": type(exc).__name__, "error_message": str(exc), **policy_flags()}
        write_json(output / "v21_222_summary.json", summary)
        (output / "V21.222_minimal_keepset_deep_attribution_report.txt").write_text(f"{STAGE}\nfinal_status={summary['final_status']}\nfinal_decision={summary['final_decision']}\nerror={summary['error_type']}: {summary['error_message']}\n", encoding="utf-8")
    for key in ["final_status", "final_decision", "repo_total_size_bytes_now", "gap_to_1gb_bytes", "projected_best_case_repo_size"]:
        if key in summary:
            print(f"{key}={summary[key]}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", default=str(DEFAULT_ROOT))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(Path(args.repo_root))
    return 0 if str(summary["final_status"]).startswith(("PASS", "WARN")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
