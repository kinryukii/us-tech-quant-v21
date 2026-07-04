#!/usr/bin/env python
"""V21.229 Moomoo-only data source policy gate.

Policy/audit only. Bounded text scanning; no market data fetch, broker action,
or source mutation.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STAGE = "V21.229_MOOMOO_ONLY_DATA_SOURCE_POLICY_GATE"
OUT_REL = Path("outputs/v21") / STAGE
V228_REL = Path("outputs/v21/V21.228_EXTERNAL_CACHE_AND_ARCHIVE_MIGRATION_COPY_ONLY")
PASS_STATUS = "PASS_V21_229_MOOMOO_ONLY_POLICY_GATE_READY"
WARN_STATUS = "WARN_V21_229_MOOMOO_ONLY_POLICY_GATE_READY_WITH_ACTIVE_BLOCKERS"
FAIL_STATUS = "FAIL_V21_229_MOOMOO_ONLY_POLICY_GATE_FAILED"
PASS_DECISION = "MOOMOO_ONLY_POLICY_READY_FOR_HISTORICAL_REFETCH_DRY_RUN"
WARN_DECISION = "MOOMOO_ONLY_POLICY_READY_FIX_ACTIVE_BLOCKERS_BEFORE_CANONICAL_REBUILD"
DEFAULT_MAX_SCAN = 2_000_000

TEXT_EXTS = {".py", ".ps1", ".json", ".csv", ".txt", ".md", ".yaml", ".yml", ".toml", ".ini", ".cfg"}
SKIP_DIRS = {".git", ".venv", ".venv_moomoo_py312", "__pycache__", ".pytest_cache"}
YF_IMPORT = "import " + "yfinance"
YF_FROM = "from " + "yfinance"
YFINANCE_TERMS = ["yfinance", "yf.download", YF_IMPORT, YF_FROM, "ALLOW_YFINANCE", "YFINANCE_ENABLED"]
YAHOO_TERMS = ["Yahoo", "yahoo", "query1.finance.yahoo", "fallback_to_yahoo"]
EXTERNAL_TERMS = ["pandas_datareader", "stooq", "alphavantage", "alpha_vantage", "polygon", "iex", "tiingo", "quandl", "external_fallback", "fallback_to_yahoo", "V21_112_R1_ALLOW_CANONICAL_PRICE_REFRESH"]
MOOMOO_TERMS = ["moomoo", "futu", "OpenD", "Futu OpenD", "Moomoo OpenD", "local Moomoo cache", "MOOMOO_ONLY", "FUTU_MOOMOO", "moomoo canonical"]

SCAN_FIELDS = ["path","relative_path","path_type","size_bytes","mtime_utc","scanned_content","inferred_module","active_candidate","data_source_terms_found","forbidden_terms_found","allowed_moomoo_terms_found","classification","severity","recommended_action","future_active_chain_allowed","diagnostic_only_required","user_review_required","notes"]
FORBIDDEN_FIELDS = ["path","forbidden_source","matched_term","line_number","context_snippet","active_candidate","severity","future_active_chain_allowed","recommended_action"]
YF_FIELDS = ["path","matched_term","line_number","usage_type","active_candidate","is_import_or_call","is_env_toggle","is_historical_metadata","is_diagnostic_only","future_active_chain_allowed","recommended_action"]
YAHOO_FIELDS = ["path","matched_term","line_number","usage_type","active_candidate","severity","recommended_action"]
MOOMOO_FIELDS = ["path","matched_term","line_number","usage_type","active_candidate","allowed_usage_type","notes"]
EXTERNAL_FIELDS = ["path","matched_term","line_number","fallback_type","active_candidate","allowed_in_future","diagnostic_only_required","recommended_action"]
ACTIVE_FIELDS = ["module_or_file","chain_role","active_candidate","yfinance_related","yahoo_related","moomoo_related","external_fallback_related","future_active_chain_allowed","block_reason","required_fix_before_active"]
SCRIPT_FIELDS = ["script_path","imports_yfinance","calls_yfinance","imports_moomoo_or_futu","calls_moomoo_or_futu","external_fallback_terms","policy_status","required_action"]
WRAPPER_FIELDS = ["wrapper_path","yfinance_env_toggle_found","yahoo_env_toggle_found","external_fallback_toggle_found","moomoo_policy_flag_found","policy_status","required_action"]
CONFIG_FIELDS = ["config_path","yfinance_enabled_default","yahoo_enabled_default","external_fallback_enabled_default","moomoo_only_policy_found","policy_status","required_action"]
OUTPUT_FIELDS = ["output_path","data_source_policy","canonical_source","yfinance_used","external_fallback_used","moomoo_used","policy_status","notes"]
CANON_FIELDS = ["artifact_or_module","canonical_source","yfinance_used","moomoo_used","external_fallback_used","allowed_for_future_canonical","required_rebuild","notes"]
DRAM_FIELDS = ["artifact_or_module","dram_related","data_source_policy","yfinance_related","moomoo_related","local_cache_related","allowed_for_future_dram_chain","required_rebuild_or_patch","notes"]
ABCDE_FIELDS = ["artifact_or_module","abcde_related","data_source_policy","yfinance_related","moomoo_related","local_cache_related","allowed_for_future_abcde_chain","required_rebuild_or_patch","notes"]
BLOCKER_FIELDS = ["path","violation_type","severity","blocks_future_active_chain","blocks_v21_230_refetch","blocks_v21_231_canonical_rebuild","required_action","notes"]
ALLOW_FIELDS = ["path_or_module","reason","allowed_only_if_explicit","must_set_diagnostic_only","not_allowed_for_canonical","not_allowed_for_dram","not_allowed_for_abcde","notes"]
ENFORCE_FIELDS = ["enforcement_item","target_file_or_policy","required_behavior","future_script","priority","notes"]
CROSS_FIELDS = ["check_name","expected","actual","pass","severity","notes"]


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def mtime_utc(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def candidate_files(root: Path, include_v20: bool) -> list[Path]:
    bases = [root / "scripts/v21", root / "config", root / "docs", root / "outputs/v21"]
    if include_v20:
        bases.extend([root / "scripts/v20", root / "outputs/v20"])
    bases.extend(root.glob("*.ps1"))
    files: list[Path] = []
    for base in bases:
        if base.is_file():
            files.append(base)
        elif base.exists():
            for p in base.rglob("*"):
                if p.is_file() and p.suffix.lower() in TEXT_EXTS and not any(part in SKIP_DIRS for part in p.parts):
                    files.append(p)
    return sorted(set(files), key=lambda p: rel(p, root).lower())


def read_sample(path: Path, max_bytes: int) -> tuple[str, bool]:
    try:
        if path.stat().st_size > max_bytes and path.suffix.lower() == ".csv":
            data = path.read_bytes()[:max_bytes]
        else:
            data = path.read_bytes()[:max_bytes]
        return data.decode("utf-8", errors="ignore"), True
    except OSError:
        return "", False


def is_active_candidate(path: Path, root: Path) -> bool:
    r = rel(path, root).lower()
    return r.startswith("scripts/") or r.startswith("config/") or ("/run_" in r and r.endswith(".ps1")) or (path.parent == root and path.suffix.lower() in {".ps1", ".py"})


def line_matches(text: str, terms: list[str]) -> list[tuple[str, int, str]]:
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        low = line.lower()
        for term in terms:
            if term.lower() in low:
                out.append((term, i, line.strip()[:220]))
    return out


def infer_module(path: Path, root: Path) -> str:
    parts = rel(path, root).split("/")
    if "outputs" in parts and len(parts) > parts.index("outputs") + 2:
        return parts[parts.index("outputs") + 2]
    return path.stem


def usage_type(path: Path, active: bool) -> str:
    r = path.as_posix().lower()
    if "outputs/" in r:
        return "historical_output_metadata"
    if path.suffix.lower() == ".ps1":
        return "wrapper_or_env"
    if active:
        return "active_executable"
    return "diagnostic_or_doc"


def classify(path: Path, root: Path, text: str) -> tuple[str, str, str, bool, bool, bool]:
    active = is_active_candidate(path, root)
    yfin = bool(line_matches(text, YFINANCE_TERMS))
    yahoo = bool(line_matches(text, YAHOO_TERMS))
    ext = bool(line_matches(text, EXTERNAL_TERMS))
    moo = bool(line_matches(text, MOOMOO_TERMS))
    utype = usage_type(path, active)
    if active and yfin:
        return "YFINANCE_FORBIDDEN", "ERROR", "REMOVE_OR_DISABLE_YFINANCE_BEFORE_ACTIVE_CHAIN", False, False, True
    if active and yahoo:
        return "YAHOO_FORBIDDEN", "ERROR", "REMOVE_OR_DISABLE_YAHOO_BEFORE_ACTIVE_CHAIN", False, False, True
    if active and ext:
        return "EXTERNAL_FALLBACK_DIAGNOSTIC_ONLY", "WARN", "REQUIRE_DIAGNOSTIC_ONLY_EXPLICIT_APPROVAL", False, True, True
    if yfin:
        return "YFINANCE_FORBIDDEN", "INFO", "KEEP_HISTORICAL_OR_DIAGNOSTIC_ONLY", False, True, False
    if yahoo:
        return "YAHOO_FORBIDDEN", "INFO", "KEEP_HISTORICAL_OR_DIAGNOSTIC_ONLY", False, True, False
    if ext:
        return "EXTERNAL_FALLBACK_DIAGNOSTIC_ONLY", "INFO", "DIAGNOSTIC_ONLY_NOT_ACTIVE_CHAIN", False, True, False
    if moo:
        return "MOOMOO_ALLOWED_ACTIVE" if active else "LOCAL_MOOMOO_CACHE_ALLOWED", "OK", "ALLOW_UNDER_MOOMOO_ONLY_POLICY", True, False, False
    if "archive" in utype or "historical" in utype:
        return "LEGACY_DEPRECATED", "INFO", "NO_ACTIVE_CHAIN_USE", False, True, False
    return "DATA_SOURCE_NEUTRAL", "OK", "NO_DATA_SOURCE_POLICY_ACTION", True, False, False


def scan(root: Path, include_v20: bool, max_bytes: int) -> dict[str, list[dict[str, Any]]]:
    rows = {k: [] for k in ["scan","forbidden","yfinance","yahoo","moomoo","external","active","script","wrapper","config","output","canonical","dram","abcde","blockers","allow"]}
    for path in candidate_files(root, include_v20):
        text, scanned = read_sample(path, max_bytes)
        active = is_active_candidate(path, root)
        yfm = line_matches(text, YFINANCE_TERMS)
        ym = line_matches(text, YAHOO_TERMS)
        em = line_matches(text, EXTERNAL_TERMS)
        mm = line_matches(text, MOOMOO_TERMS)
        classification, severity, action, allowed, diag, review = classify(path, root, text)
        r = rel(path, root)
        terms = sorted({m[0] for m in yfm + ym + em + mm})
        forbidden = sorted({m[0] for m in yfm + ym})
        rows["scan"].append({"path": str(path), "relative_path": r, "path_type": "file", "size_bytes": path.stat().st_size, "mtime_utc": mtime_utc(path), "scanned_content": scanned, "inferred_module": infer_module(path, root), "active_candidate": active, "data_source_terms_found": "|".join(terms), "forbidden_terms_found": "|".join(forbidden), "allowed_moomoo_terms_found": "|".join(sorted({m[0] for m in mm})), "classification": classification, "severity": severity, "recommended_action": action, "future_active_chain_allowed": allowed, "diagnostic_only_required": diag, "user_review_required": review, "notes": "bounded_text_scan_only"})
        for term, line, ctx in yfm + ym:
            source = "YFINANCE" if term.lower() in {t.lower() for t in YFINANCE_TERMS} else "YAHOO"
            rows["forbidden"].append({"path": str(path), "forbidden_source": source, "matched_term": term, "line_number": line, "context_snippet": ctx, "active_candidate": active, "severity": "ERROR" if active else "INFO", "future_active_chain_allowed": False, "recommended_action": action})
        for term, line, ctx in yfm:
            is_import = term.lower() in {YF_IMPORT.lower(), YF_FROM.lower(), "yf.download"}
            is_env = "ALLOW_" in term.upper() or "ENABLED" in term.upper()
            hist = not active and "outputs/" in r.lower()
            rows["yfinance"].append({"path": str(path), "matched_term": term, "line_number": line, "usage_type": usage_type(path, active), "active_candidate": active, "is_import_or_call": is_import, "is_env_toggle": is_env, "is_historical_metadata": hist, "is_diagnostic_only": not active, "future_active_chain_allowed": False, "recommended_action": action})
        for term, line, ctx in ym:
            rows["yahoo"].append({"path": str(path), "matched_term": term, "line_number": line, "usage_type": usage_type(path, active), "active_candidate": active, "severity": "ERROR" if active else "INFO", "recommended_action": action})
        for term, line, ctx in mm:
            rows["moomoo"].append({"path": str(path), "matched_term": term, "line_number": line, "usage_type": usage_type(path, active), "active_candidate": active, "allowed_usage_type": "MOOMOO_ONLY_ALLOWED_REFERENCE", "notes": "string reference only; this script does not import/call provider"})
        for term, line, ctx in em:
            rows["external"].append({"path": str(path), "matched_term": term, "line_number": line, "fallback_type": term, "active_candidate": active, "allowed_in_future": False, "diagnostic_only_required": True, "recommended_action": "DIAGNOSTIC_ONLY_EXPLICIT_APPROVAL_REQUIRED"})
        lower_r = r.lower()
        if active or any(token in lower_r for token in ["canonical", "dram", "abcde", "daily_moomoo"]):
            role = "CANONICAL" if "canonical" in lower_r else "DRAM" if "dram" in lower_r else "ABCDE" if "abcde" in lower_r else "ACTIVE_SCRIPT"
            blocked = (active and (yfm or ym or em)) or (role in {"CANONICAL", "DRAM", "ABCDE"} and (yfm or ym or em))
            rows["active"].append({"module_or_file": str(path), "chain_role": role, "active_candidate": active, "yfinance_related": bool(yfm), "yahoo_related": bool(ym), "moomoo_related": bool(mm), "external_fallback_related": bool(em), "future_active_chain_allowed": not blocked, "block_reason": "FORBIDDEN_OR_EXTERNAL_SOURCE_REFERENCE" if blocked else "", "required_fix_before_active": "REMOVE_OR_DOWNGRADE_TO_DIAGNOSTIC" if blocked else ""})
        if path.suffix.lower() == ".py" and active:
            rows["script"].append({"script_path": str(path), "imports_yfinance": any(t.lower() in {YF_IMPORT.lower(), YF_FROM.lower()} for t, _, _ in yfm), "calls_yfinance": any(t.lower() == "yf.download" for t, _, _ in yfm), "imports_moomoo_or_futu": False, "calls_moomoo_or_futu": False, "external_fallback_terms": "|".join(sorted({m[0] for m in em})), "policy_status": "BLOCK" if yfm or em else "ALLOW", "required_action": "PATCH_BEFORE_ACTIVE_USE" if yfm or em else ""})
        if path.suffix.lower() == ".ps1":
            rows["wrapper"].append({"wrapper_path": str(path), "yfinance_env_toggle_found": any("YFINANCE" in m[0].upper() for m in yfm), "yahoo_env_toggle_found": bool(ym), "external_fallback_toggle_found": bool(em), "moomoo_policy_flag_found": bool(mm), "policy_status": "BLOCK" if active and (yfm or ym or em) else "ALLOW_OR_DIAGNOSTIC", "required_action": "REMOVE_FORBIDDEN_DEFAULT" if active and (yfm or ym or em) else ""})
        if "config/" in lower_r:
            rows["config"].append({"config_path": str(path), "yfinance_enabled_default": bool(yfm), "yahoo_enabled_default": bool(ym), "external_fallback_enabled_default": bool(em), "moomoo_only_policy_found": bool(mm), "policy_status": "BLOCK" if yfm or ym or em else "ALLOW", "required_action": "SET_MOOMOO_ONLY_DEFAULTS" if yfm or ym or em else ""})
        if "outputs/" in lower_r and path.suffix.lower() in {".json", ".csv", ".txt"}:
            rows["output"].append({"output_path": str(path), "data_source_policy": "MOOMOO_ONLY" if mm and not (yfm or ym or em) else "HISTORICAL_OR_DIAGNOSTIC", "canonical_source": "MOOMOO" if mm else "UNKNOWN_OR_LEGACY", "yfinance_used": bool(yfm), "external_fallback_used": bool(em or ym), "moomoo_used": bool(mm), "policy_status": "DIAGNOSTIC_ONLY" if yfm or ym or em else "ALLOW", "notes": "historical output metadata scan"})
        if "canonical" in lower_r or yfm or ym or em or mm:
            rows["canonical"].append({"artifact_or_module": str(path), "canonical_source": "MOOMOO" if mm else "UNKNOWN_OR_LEGACY", "yfinance_used": bool(yfm), "moomoo_used": bool(mm), "external_fallback_used": bool(em or ym), "allowed_for_future_canonical": bool(mm) and not (yfm or ym or em), "required_rebuild": bool(yfm or ym or em), "notes": "future canonical must be Moomoo-only"})
        if "dram" in lower_r:
            rows["dram"].append({"artifact_or_module": str(path), "dram_related": True, "data_source_policy": "MOOMOO_ONLY" if mm and not (yfm or ym or em) else "REBUILD_OR_PATCH_REQUIRED" if yfm or ym or em else "UNKNOWN_REVIEW", "yfinance_related": bool(yfm), "moomoo_related": bool(mm), "local_cache_related": "cache" in lower_r, "allowed_for_future_dram_chain": not (yfm or ym or em), "required_rebuild_or_patch": bool(yfm or ym or em), "notes": "DRAM active chain must not use forbidden sources"})
        if "abcde" in lower_r or "a1" in lower_r:
            rows["abcde"].append({"artifact_or_module": str(path), "abcde_related": True, "data_source_policy": "MOOMOO_ONLY" if mm and not (yfm or ym or em) else "REBUILD_OR_PATCH_REQUIRED" if yfm or ym or em else "UNKNOWN_REVIEW", "yfinance_related": bool(yfm), "moomoo_related": bool(mm), "local_cache_related": "cache" in lower_r, "allowed_for_future_abcde_chain": not (yfm or ym or em), "required_rebuild_or_patch": bool(yfm or ym or em), "notes": "ABCDE active chain must not use forbidden sources"})
        if active and (yfm or ym or em):
            rows["blockers"].append({"path": str(path), "violation_type": "YFINANCE_OR_YAHOO" if yfm or ym else "EXTERNAL_FALLBACK", "severity": "ERROR" if yfm or ym else "WARN", "blocks_future_active_chain": True, "blocks_v21_230_refetch": bool(yfm or ym), "blocks_v21_231_canonical_rebuild": bool(yfm or ym or em), "required_action": action, "notes": "active executable/config/wrapper policy blocker"})
        if (yfm or ym or em) and not active:
            rows["allow"].append({"path_or_module": str(path), "reason": "historical/deprecated/diagnostic reference", "allowed_only_if_explicit": True, "must_set_diagnostic_only": True, "not_allowed_for_canonical": True, "not_allowed_for_dram": True, "not_allowed_for_abcde": True, "notes": "not a future active data source"})
    return rows


def policy_json() -> dict[str, Any]:
    return {
        "policy_version": "V21.229",
        "default_data_source_policy": "MOOMOO_ONLY",
        "allowed_active_sources": ["MOOMOO_OPEND", "LOCAL_MOOMOO_CACHE", "MANUAL_MOOMOO_IMPORT_WITH_TAG"],
        "forbidden_default_sources": ["YFINANCE", "YAHOO"],
        "external_fallback_policy": "DIAGNOSTIC_ONLY_EXPLICIT_APPROVAL_REQUIRED",
        "yfinance_allowed_by_default": False,
        "yahoo_allowed_by_default": False,
        "yfinance_allowed_for_canonical": False,
        "yfinance_allowed_for_dram": False,
        "yfinance_allowed_for_abcde": False,
        "external_fallback_allowed_for_canonical": False,
        "external_fallback_allowed_for_dram": False,
        "external_fallback_allowed_for_abcde": False,
        "moomoo_import_called_in_this_script": False,
        "data_fetch_called_in_this_script": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
        "next_allowed_stage": "V21.230_MOOMOO_ONLY_HISTORICAL_REFETCH_DRY_RUN",
    }


def enforcement_plan() -> list[dict[str, Any]]:
    return [
        {"enforcement_item": "block_yfinance_defaults", "target_file_or_policy": "data_source_policy.json", "required_behavior": "YFINANCE_AND_YAHOO_FALSE_BY_DEFAULT", "future_script": "V21.230", "priority": "HIGH", "notes": "required before refetch dry-run"},
        {"enforcement_item": "moomoo_only_canonical", "target_file_or_policy": "canonical rebuild scripts", "required_behavior": "MOOMOO_ONLY_OR_LOCAL_MOOMOO_CACHE", "future_script": "V21.231", "priority": "HIGH", "notes": "canonical rebuild must not use fallback"},
        {"enforcement_item": "diagnostic_allowlist", "target_file_or_policy": "legacy artifacts", "required_behavior": "FORBIDDEN_REFERENCES_DIAGNOSTIC_ONLY", "future_script": "V21.230", "priority": "MEDIUM", "notes": "legacy references do not block if not active"},
    ]


def v228_crosscheck(v228_dir: Path) -> tuple[list[dict[str, Any]], str]:
    summary = read_json(v228_dir / "v21_228_summary.json")
    policy = read_json(v228_dir / "copy_only_policy_gate.json")
    rows = [
        {"check_name": "v21_228_summary", "expected": "present", "actual": "present" if summary else "missing", "pass": bool(summary), "severity": "ERROR", "notes": "V21.228 context"},
        {"check_name": "copy_verified", "expected": "failed_copy_count=0", "actual": summary.get("failed_copy_count", ""), "pass": summary.get("failed_copy_count") == 0, "severity": "ERROR", "notes": "copy-only verification must have passed"},
        {"check_name": "policy_next_stage", "expected": STAGE, "actual": policy.get("next_allowed_stage", ""), "pass": policy.get("next_allowed_stage") == STAGE, "severity": "WARN", "notes": "V21.228 points to V21.229"},
    ]
    return rows, "FOUND" if summary else "MISSING"


def run(repo_root: Path | None = None, output_dir: Path | None = None, v21_228_output_dir: Path | None = None, max_content_scan_bytes: int = DEFAULT_MAX_SCAN, include_v20: bool = False) -> dict[str, Any]:
    root = (repo_root or default_repo_root()).resolve()
    out = (output_dir or root / OUT_REL).resolve()
    v228 = (v21_228_output_dir or root / V228_REL).resolve()
    out.mkdir(parents=True, exist_ok=True)
    try:
        rows = scan(root, include_v20, max_content_scan_bytes)
        cross, cross_status = v228_crosscheck(v228)
        active_yf = sum(1 for r in rows["yfinance"] if r["active_candidate"])
        active_yahoo = sum(1 for r in rows["yahoo"] if r["active_candidate"])
        external_blockers = sum(1 for r in rows["external"] if r["active_candidate"])
        active_blocked = sum(1 for r in rows["active"] if not r["future_active_chain_allowed"])
        status = WARN_STATUS if active_yf or active_yahoo or external_blockers or active_blocked else PASS_STATUS
        summary = {
            "final_status": status,
            "final_decision": WARN_DECISION if status == WARN_STATUS else PASS_DECISION,
            "repo_root": str(root),
            "output_dir": str(out),
            "scanned_file_count": len(rows["scan"]),
            "forbidden_usage_count": len(rows["forbidden"]),
            "yfinance_usage_count": len(rows["yfinance"]),
            "yahoo_usage_count": len(rows["yahoo"]),
            "active_yfinance_blocker_count": active_yf,
            "active_yahoo_blocker_count": active_yahoo,
            "external_fallback_blocker_count": external_blockers,
            "moomoo_allowed_usage_count": len(rows["moomoo"]),
            "diagnostic_only_allowlist_count": len(rows["allow"]),
            "active_chain_allowed_count": sum(1 for r in rows["active"] if r["future_active_chain_allowed"]),
            "active_chain_blocked_count": active_blocked,
            "canonical_rebuild_required": any(r["required_rebuild"] for r in rows["canonical"]),
            "dram_rebuild_required": any(r["required_rebuild_or_patch"] for r in rows["dram"]),
            "abcde_rebuild_required": any(r["required_rebuild_or_patch"] for r in rows["abcde"]),
            "v21_228_crosscheck_status": cross_status,
            "yfinance_used": False,
            "yahoo_used": False,
            "data_fetch_used": False,
            "moomoo_import_used": False,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "research_only": True,
            "warning_count": 1 if status == WARN_STATUS else 0,
            "error_count": 0,
        }
        write_json(out / "data_source_policy.json", policy_json())
        write_csv(out / "repository_data_source_scan.csv", rows["scan"], SCAN_FIELDS)
        write_csv(out / "forbidden_source_usage_inventory.csv", rows["forbidden"], FORBIDDEN_FIELDS)
        write_csv(out / "yfinance_usage_inventory.csv", rows["yfinance"], YF_FIELDS)
        write_csv(out / "yahoo_string_inventory.csv", rows["yahoo"], YAHOO_FIELDS)
        write_csv(out / "moomoo_allowed_usage_inventory.csv", rows["moomoo"], MOOMOO_FIELDS)
        write_csv(out / "external_fallback_inventory.csv", rows["external"], EXTERNAL_FIELDS)
        write_csv(out / "active_chain_policy_audit.csv", rows["active"], ACTIVE_FIELDS)
        write_csv(out / "script_import_policy_audit.csv", rows["script"], SCRIPT_FIELDS)
        write_csv(out / "wrapper_env_policy_audit.csv", rows["wrapper"], WRAPPER_FIELDS)
        write_csv(out / "config_policy_audit.csv", rows["config"], CONFIG_FIELDS)
        write_csv(out / "output_manifest_policy_audit.csv", rows["output"], OUTPUT_FIELDS)
        write_csv(out / "canonical_source_policy_audit.csv", rows["canonical"], CANON_FIELDS)
        write_csv(out / "dram_policy_readiness_audit.csv", rows["dram"], DRAM_FIELDS)
        write_csv(out / "abcde_policy_readiness_audit.csv", rows["abcde"], ABCDE_FIELDS)
        write_csv(out / "policy_violation_blockers.csv", rows["blockers"], BLOCKER_FIELDS)
        write_csv(out / "diagnostic_only_allowlist_plan.csv", rows["allow"], ALLOW_FIELDS)
        write_csv(out / "moomoo_only_enforcement_plan.csv", enforcement_plan(), ENFORCE_FIELDS)
        write_csv(out / "v21_228_copy_policy_crosscheck.csv", cross, CROSS_FIELDS)
        write_json(out / "v21_229_summary.json", summary)
        write_report(out / "V21.229_moomoo_only_data_source_policy_gate_report.txt", summary)
    except Exception as exc:
        summary = {"final_status": FAIL_STATUS, "final_decision": "MOOMOO_ONLY_POLICY_GATE_FAILED", "repo_root": str(root), "output_dir": str(out), "scanned_file_count": 0, "forbidden_usage_count": 0, "yfinance_usage_count": 0, "yahoo_usage_count": 0, "active_yfinance_blocker_count": 0, "active_yahoo_blocker_count": 0, "external_fallback_blocker_count": 0, "moomoo_allowed_usage_count": 0, "diagnostic_only_allowlist_count": 0, "active_chain_allowed_count": 0, "active_chain_blocked_count": 0, "canonical_rebuild_required": False, "dram_rebuild_required": False, "abcde_rebuild_required": False, "v21_228_crosscheck_status": "NOT_RUN", "yfinance_used": False, "yahoo_used": False, "data_fetch_used": False, "moomoo_import_used": False, "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True, "warning_count": 0, "error_count": 1, "error_message": f"{type(exc).__name__}: {exc}"}
        write_json(out / "v21_229_summary.json", summary)
    for key in ["final_status","final_decision","scanned_file_count","forbidden_usage_count","yfinance_usage_count","yahoo_usage_count","active_yfinance_blocker_count","active_yahoo_blocker_count","external_fallback_blocker_count","moomoo_allowed_usage_count","diagnostic_only_allowlist_count","active_chain_blocked_count","canonical_rebuild_required","dram_rebuild_required","abcde_rebuild_required","warning_count","error_count"]:
        print(f"{key}={summary[key]}")
    print(f"summary_path={out / 'v21_229_summary.json'}")
    return summary


def write_report(path: Path, summary: dict[str, Any]) -> None:
    keys = ["final_status","final_decision","scanned_file_count","forbidden_usage_count","yfinance_usage_count","yahoo_usage_count","active_yfinance_blocker_count","active_yahoo_blocker_count","external_fallback_blocker_count","moomoo_allowed_usage_count","diagnostic_only_allowlist_count","active_chain_blocked_count","canonical_rebuild_required","dram_rebuild_required","abcde_rebuild_required","warning_count","error_count"]
    path.write_text("\n".join([STAGE, *[f"{k}={summary[k]}" for k in keys], "policy_audit_only=True", "data_fetch_used=False", "moomoo_import_used=False", "broker_action_allowed=False", "official_adoption_allowed=False"]) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=STAGE)
    p.add_argument("--repo-root")
    p.add_argument("--output-dir")
    p.add_argument("--v21-228-output-dir")
    p.add_argument("--max-content-scan-bytes", type=int, default=DEFAULT_MAX_SCAN)
    p.add_argument("--include-v20", action="store_true")
    p.add_argument("--fail-on-active-blockers", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(
        repo_root=Path(args.repo_root) if args.repo_root else None,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        v21_228_output_dir=Path(args.v21_228_output_dir) if args.v21_228_output_dir else None,
        max_content_scan_bytes=args.max_content_scan_bytes,
        include_v20=args.include_v20,
    )
    if summary["final_status"] == FAIL_STATUS:
        return 1
    if args.fail_on_active_blockers and summary["final_status"] == WARN_STATUS:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
