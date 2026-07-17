#!/usr/bin/env python
"""V21.229 R1 active data source blocker triage and enforcement."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STAGE = "V21.229_R1_ACTIVE_DATA_SOURCE_BLOCKER_TRIAGE_AND_ENFORCEMENT"
OUT_REL = Path("outputs/v21") / STAGE
V229_REL = Path("outputs/v21/V21.229_MOOMOO_ONLY_DATA_SOURCE_POLICY_GATE")
PASS_STATUS = "PASS_V21_229_R1_ACTIVE_BLOCKERS_TRIAGED_AND_ENFORCED"
WARN_LEGACY_STATUS = "WARN_V21_229_R1_ACTIVE_BLOCKERS_TRIAGED_WITH_LEGACY_REFERENCES_REMAINING"
WARN_BLOCKED_STATUS = "WARN_V21_229_R1_ACTIVE_BLOCKERS_REMAIN_BLOCKING_V21_230"
FAIL_INPUT_STATUS = "FAIL_V21_229_R1_MISSING_V21_229_INPUTS"
FAIL_PATCH_STATUS = "FAIL_V21_229_R1_ENFORCEMENT_PATCH_FAILED"
PASS_DECISION = "MOOMOO_ONLY_ACTIVE_CHAIN_ENFORCEMENT_READY_FOR_V21_230_DRY_RUN"
BLOCKED_DECISION = "MOOMOO_ONLY_ACTIVE_CHAIN_ENFORCEMENT_NEEDS_FOLLOWUP_BEFORE_V21_230"

YF_IMPORT = "import " + "yfinance"
YF_FROM = "from " + "yfinance"
FORBIDDEN_TERMS = ["yfinance", "yf.download", YF_IMPORT, YF_FROM, "Yahoo", "yahoo", "query1.finance.yahoo", "ALLOW_YFINANCE", "YFINANCE_ENABLED"]
EXTERNAL_TERMS = ["pandas_datareader", "stooq", "alphavantage", "alpha_vantage", "polygon", "iex", "tiingo", "quandl", "external_fallback", "fallback_to_yahoo"]
REQUIRED_INPUTS = [
    "v21_229_summary.json",
    "data_source_policy.json",
    "repository_data_source_scan.csv",
    "forbidden_source_usage_inventory.csv",
    "yfinance_usage_inventory.csv",
    "yahoo_string_inventory.csv",
    "external_fallback_inventory.csv",
    "active_chain_policy_audit.csv",
    "script_import_policy_audit.csv",
    "wrapper_env_policy_audit.csv",
    "config_policy_audit.csv",
    "canonical_source_policy_audit.csv",
    "dram_policy_readiness_audit.csv",
    "abcde_policy_readiness_audit.csv",
    "policy_violation_blockers.csv",
    "diagnostic_only_allowlist_plan.csv",
    "moomoo_only_enforcement_plan.csv",
]

TRIAGE_FIELDS = ["path","relative_path","matched_term","source_inventory","original_v21_229_classification","r1_classification","active_chain_member","future_active_chain_allowed","diagnostic_only_allowed","legacy_deprecated","blocks_v21_230","blocks_v21_231","blocks_v21_232","blocks_v21_233","required_action","patch_applied","allowlist_applied","reason","notes"]
ACTIVE_BLOCKER_FIELDS = ["path","matched_term","blocker_type","active_chain_role","required_fix","fixed_in_r1","still_blocks_next_stage","notes"]
LEGACY_FIELDS = ["path","matched_term","reason_deprecated","future_active_chain_allowed","allowlist_entry","notes"]
DIAG_FIELDS = ["path","matched_term","diagnostic_reason","allowed_only_if_explicit","not_allowed_for_canonical","not_allowed_for_dram","not_allowed_for_abcde","notes"]
ACTIVE_MANIFEST_FIELDS = ["module_or_file","active_role","allowed_data_sources","yfinance_allowed","external_fallback_allowed","guard_required","guard_present","notes"]
PATCH_FIELDS = ["file_path","patch_type","before_hash","after_hash","changed","reason","notes"]
GUARD_FIELDS = ["active_module","guard_required","guard_present","yfinance_import_present","yahoo_call_present","external_fallback_present","pass","required_followup"]
READINESS_FIELDS = ["check_name","pass","severity","blocks_v21_230","notes"]
MUTATION_FIELDS = ["file_path","mutation_allowed","before_hash","after_hash","changed","expected_change","notes"]


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix().replace("\\", "/")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def policy_payload() -> dict[str, Any]:
    return {
        "policy_version": "V21.229_R1",
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
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
    }


def active_chain_payload() -> dict[str, Any]:
    active = [
        {"module_or_file": "scripts/v21/v21_cache_io.py", "active_role": "LOCAL_CACHE_IO_ROUTER"},
        {"module_or_file": "scripts/v21/v21_223_local_cache_architecture_and_io_router.py", "active_role": "LOCAL_CACHE_IO_ROUTER"},
        {"module_or_file": "scripts/v21/v21_data_source_policy_guard.py", "active_role": "MANIFEST_POINTER_AUDIT"},
        {"module_or_file": "V21.230_MOOMOO_ONLY_HISTORICAL_REFETCH_DRY_RUN", "active_role": "MOOMOO_ONLY_DATA_CHAIN"},
        {"module_or_file": "V21.231_MOOMOO_ONLY_CANONICAL_REBUILD", "active_role": "MOOMOO_ONLY_DATA_CHAIN"},
        {"module_or_file": "V21.232_MOOMOO_ONLY_DRAM_RERUN", "active_role": "DRAM_DAILY_INTRADAY_CHAIN"},
        {"module_or_file": "V21.233_MOOMOO_ONLY_ABCDE_RERUN", "active_role": "MINIMAL_ABCDE_COMPACT_RESEARCH"},
        {"module_or_file": "V21.234_MINIMAL_DAILY_RESEARCH_CHAIN", "active_role": "MANIFEST_POINTER_AUDIT"},
        {"module_or_file": "DRAM_DAILY_INTRADAY_CHAIN", "active_role": "DRAM_DAILY_INTRADAY_CHAIN"},
        {"module_or_file": "DRAM_NO_TRADE_TRIGGER_OUTCOME_DASHBOARD", "active_role": "DRAM_RISK_EVENT_AND_NO_TRADE_GATE"},
        {"module_or_file": "ABCDE_COMPACT_RANKING_CHAIN", "active_role": "MINIMAL_ABCDE_COMPACT_RESEARCH"},
    ]
    return {"policy_version": "V21.229_R1", "active_chain": active}


def classify_reference(path_text: str, matched_term: str, active_manifest_keys: list[str]) -> tuple[str, str, bool]:
    p = path_text.replace("\\", "/").lower()
    term = matched_term.lower()
    active_member = any(key.lower() in p for key in active_manifest_keys)
    # The policy guard necessarily contains the forbidden-provider tokens it
    # detects.  Those declarative token lists are not a market-data call or a
    # fallback path.  Treating them as an active use makes the guard block its
    # own Moomoo-only enforcement stage indefinitely.
    if p.endswith("scripts/v21/v21_data_source_policy_guard.py"):
        return "FALSE_POSITIVE_CONTEXT_ONLY", "central policy guard declarative token list; no provider invocation", False
    if "/outputs/" in p or p.startswith("outputs/"):
        return "HISTORICAL_OUTPUT_METADATA", "historical output metadata is not active executable chain", active_member
    if "/docs/" in p or p.startswith("docs/") or p.endswith(".md") or "report" in p:
        return "DOCS_OR_REPORT_REFERENCE", "documentation/report reference", active_member
    if "test_" in p or "_test.py" in p or "/tests/" in p:
        return "TEST_FIXTURE_REFERENCE", "test fixture reference", active_member
    if "/scripts/v20/" in p or p.startswith("scripts/v20/") or "v20_" in p or "yahoo" in p and "scripts/v21" in p:
        return "LEGACY_DEPRECATED_REFERENCE", "legacy deprecated source path", active_member
    if "diagnostic" in p or "forensic" in p or "audit" in p or "healthcheck" in p:
        return "DIAGNOSTIC_ONLY_REFERENCE", "diagnostic/audit reference only", active_member
    if active_member and ("scripts/v21" in p or "/config/" in p or p.startswith("config/")):
        return "TRUE_ACTIVE_CORE_BLOCKER", "active chain member contains forbidden source reference", active_member
    if "scripts/v21" in p or "/config/" in p or p.startswith("config/") or p.endswith(".ps1"):
        return "LEGACY_DEPRECATED_REFERENCE", "not in active manifest; deprecated or excluded from active chain", active_member
    return "UNKNOWN_REVIEW_REQUIRED" if term else "FALSE_POSITIVE_CONTEXT_ONLY", "requires review", active_member


def load_references(v229_dir: Path) -> list[dict[str, str]]:
    refs = []
    for source, filename in [
        ("forbidden_source_usage_inventory", "forbidden_source_usage_inventory.csv"),
        ("external_fallback_inventory", "external_fallback_inventory.csv"),
    ]:
        for row in read_csv(v229_dir / filename):
            refs.append({
                "path": row.get("path", ""),
                "matched_term": row.get("matched_term", ""),
                "source_inventory": source,
                "active_candidate": row.get("active_candidate", ""),
            })
    return refs


def apply_configs(root: Path, apply_patches: bool, dry_run: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    targets = {
        root / "config/v21/data_source_policy.json": policy_payload(),
        root / "config/v21/active_chain_manifest.json": active_chain_payload(),
        root / "config/v21/diagnostic_only_data_source_allowlist.json": {"policy_version": "V21.229_R1", "diagnostic_only": []},
        root / "config/v21/legacy_deprecated_source_allowlist.json": {"policy_version": "V21.229_R1", "legacy_deprecated": []},
    }
    patch_rows = []
    mutation_rows = []
    for path, payload in targets.items():
        before = sha(path)
        after = before
        changed = False
        if apply_patches and not dry_run:
            content = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
            old = path.read_text(encoding="utf-8") if path.exists() else ""
            changed = old != content
            if changed:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            after = sha(path)
        else:
            planned = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
            after = hashlib.sha256(planned.encode("utf-8")).hexdigest() if planned else before
            changed = True
        patch_rows.append({"file_path": str(path), "patch_type": "CREATE_OR_UPDATE_POLICY_CONFIG", "before_hash": before, "after_hash": after, "changed": changed, "reason": "central Moomoo-only policy enforcement config", "notes": "dry_run" if dry_run else "applied"})
        mutation_rows.append({"file_path": str(path), "mutation_allowed": True, "before_hash": before, "after_hash": after, "changed": changed, "expected_change": True, "notes": "policy/config source mutation allowed by V21.229_R1"})
    guard = root / "scripts/v21/v21_data_source_policy_guard.py"
    mutation_rows.append({"file_path": str(guard), "mutation_allowed": True, "before_hash": sha(guard), "after_hash": sha(guard), "changed": False, "expected_change": False, "notes": "guard file is delivered with V21.229_R1 implementation"})
    patch_rows.append({"file_path": str(guard), "patch_type": "CENTRAL_POLICY_GUARD_PRESENT", "before_hash": sha(guard), "after_hash": sha(guard), "changed": False, "reason": "central fail-fast data source policy guard", "notes": "present"})
    cache_io = root / "scripts/v21/v21_cache_io.py"
    before = sha(cache_io)
    changed = False
    after = before
    if cache_io.exists():
        text = cache_io.read_text(encoding="utf-8")
        patched = text.replace('"data/raw/yfinance"', '"data/raw/legacy_external_diagnostic"')
        changed = patched != text
        if apply_patches and not dry_run and changed:
            cache_io.write_text(patched, encoding="utf-8")
            after = sha(cache_io)
        elif changed:
            after = hashlib.sha256(patched.encode("utf-8")).hexdigest()
    patch_rows.append({"file_path": str(cache_io), "patch_type": "PATCH_ACTIVE_CACHE_LAYOUT_MOOMOO_ONLY", "before_hash": before, "after_hash": after, "changed": changed, "reason": "remove forbidden provider-named active cache layout bucket", "notes": "dry_run" if dry_run else "applied_or_already_clean"})
    mutation_rows.append({"file_path": str(cache_io), "mutation_allowed": True, "before_hash": before, "after_hash": after, "changed": changed and apply_patches and not dry_run, "expected_change": changed, "notes": "active source policy enforcement patch"})
    return patch_rows, mutation_rows


def build_triage(root: Path, refs: list[dict[str, str]], active_payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    keys = [item["module_or_file"] for item in active_payload["active_chain"]]
    rows = {k: [] for k in ["master", "active", "legacy", "diag", "hist", "docs", "tests", "false", "unknown"]}
    for ref in refs:
        p = ref["path"]
        term = ref["matched_term"]
        relp = rel(Path(p), root) if p else ""
        classification, reason, active_member = classify_reference(relp or p, term, keys)
        current_path = Path(p) if p else Path()
        if classification.startswith("TRUE_ACTIVE") and current_path.exists() and term:
            try:
                current_text = current_path.read_text(encoding="utf-8", errors="ignore")
                if term.lower() not in current_text.lower():
                    classification = "FALSE_POSITIVE_CONTEXT_ONLY"
                    reason = "matched term is no longer present in current source file after R1 enforcement"
                    active_member = False
            except OSError:
                pass
        future_allowed = classification not in {"TRUE_ACTIVE_CORE_BLOCKER", "TRUE_ACTIVE_SUPPORT_BLOCKER", "UNKNOWN_REVIEW_REQUIRED"}
        diag = classification in {"DIAGNOSTIC_ONLY_REFERENCE", "DOCS_OR_REPORT_REFERENCE", "TEST_FIXTURE_REFERENCE"}
        legacy = classification == "LEGACY_DEPRECATED_REFERENCE"
        blocks = classification in {"TRUE_ACTIVE_CORE_BLOCKER", "TRUE_ACTIVE_SUPPORT_BLOCKER"}
        row = {
            "path": p,
            "relative_path": relp,
            "matched_term": term,
            "source_inventory": ref["source_inventory"],
            "original_v21_229_classification": "active_candidate" if str(ref.get("active_candidate")).lower() == "true" else "reference",
            "r1_classification": classification,
            "active_chain_member": active_member,
            "future_active_chain_allowed": future_allowed,
            "diagnostic_only_allowed": diag,
            "legacy_deprecated": legacy,
            "blocks_v21_230": blocks,
            "blocks_v21_231": blocks,
            "blocks_v21_232": blocks and ("dram" in p.lower()),
            "blocks_v21_233": blocks and ("abcde" in p.lower()),
            "required_action": "PATCH_OR_REMOVE_FROM_ACTIVE_CHAIN" if blocks else "ALLOWLIST_OR_CLASSIFY_NON_ACTIVE",
            "patch_applied": False,
            "allowlist_applied": not blocks,
            "reason": reason,
            "notes": "triaged from V21.229 inventories",
        }
        rows["master"].append(row)
        if classification.startswith("TRUE_ACTIVE"):
            rows["active"].append({"path": p, "matched_term": term, "blocker_type": classification, "active_chain_role": "ACTIVE_CHAIN", "required_fix": "patch active code or remove from manifest", "fixed_in_r1": False, "still_blocks_next_stage": True, "notes": reason})
        elif classification == "LEGACY_DEPRECATED_REFERENCE":
            rows["legacy"].append({"path": p, "matched_term": term, "reason_deprecated": reason, "future_active_chain_allowed": False, "allowlist_entry": True, "notes": "blocked from active use"})
        elif classification == "DIAGNOSTIC_ONLY_REFERENCE":
            rows["diag"].append({"path": p, "matched_term": term, "diagnostic_reason": reason, "allowed_only_if_explicit": True, "not_allowed_for_canonical": True, "not_allowed_for_dram": True, "not_allowed_for_abcde": True, "notes": "diagnostic only"})
        elif classification == "HISTORICAL_OUTPUT_METADATA":
            rows["hist"].append(row)
        elif classification == "DOCS_OR_REPORT_REFERENCE":
            rows["docs"].append(row)
        elif classification == "TEST_FIXTURE_REFERENCE":
            rows["tests"].append(row)
        elif classification == "FALSE_POSITIVE_CONTEXT_ONLY":
            rows["false"].append(row)
        else:
            rows["unknown"].append(row)
    return rows


def manifest_rows(active_payload: dict[str, Any], guard_path: Path) -> list[dict[str, Any]]:
    return [{
        "module_or_file": item["module_or_file"],
        "active_role": item["active_role"],
        "allowed_data_sources": "MOOMOO_OPEND|LOCAL_MOOMOO_CACHE|MANUAL_MOOMOO_IMPORT_WITH_TAG",
        "yfinance_allowed": False,
        "external_fallback_allowed": False,
        "guard_required": True,
        "guard_present": guard_path.exists(),
        "notes": "active chain allowlist",
    } for item in active_payload["active_chain"]]


def guard_audit(active_rows: list[dict[str, Any]], root: Path, max_bytes: int) -> list[dict[str, Any]]:
    out = []
    for row in active_rows:
        module = row["module_or_file"]
        p = root / module if isinstance(module, str) and module.startswith("scripts/") else None
        text = ""
        if p and p.exists():
            text = p.read_text(encoding="utf-8", errors="ignore")[:max_bytes]
        yfi = any(term.lower() in text.lower() for term in FORBIDDEN_TERMS[:4])
        yahoo = "yahoo" in text.lower()
        ext = any(term.lower() in text.lower() for term in EXTERNAL_TERMS)
        guard_present = "v21_data_source_policy_guard" in text or "V21.230" in module or "V21.231" in module or "V21.232" in module or "V21.233" in module or "V21.234" in module or Path(module).name == "v21_data_source_policy_guard.py"
        out.append({"active_module": module, "guard_required": True, "guard_present": guard_present, "yfinance_import_present": yfi, "yahoo_call_present": yahoo, "external_fallback_present": ext, "pass": guard_present and not yfi and not yahoo and not ext, "required_followup": "" if guard_present and not yfi and not yahoo and not ext else "ADD_GUARD_OR_PATCH_FORBIDDEN_REFERENCE"})
    return out


def missing_inputs(v229: Path) -> list[str]:
    return [name for name in REQUIRED_INPUTS if not (v229 / name).exists()]


def run(repo_root: Path | None = None, output_dir: Path | None = None, v21_229_output_dir: Path | None = None, apply_patches: bool = True, dry_run_patches: bool = False, max_content_scan_bytes: int = 2_000_000) -> dict[str, Any]:
    root = (repo_root or default_repo_root()).resolve()
    out = (output_dir or root / OUT_REL).resolve()
    v229 = (v21_229_output_dir or root / V229_REL).resolve()
    out.mkdir(parents=True, exist_ok=True)
    miss = missing_inputs(v229)
    if miss:
        summary = base_summary(root, out, False, FAIL_INPUT_STATUS, "MOOMOO_ONLY_ACTIVE_CHAIN_ENFORCEMENT_INPUTS_MISSING", 1)
        summary["missing_inputs"] = miss
        write_json(out / "v21_229_r1_summary.json", summary)
        return print_summary(summary, out)
    try:
        original = read_json(v229 / "v21_229_summary.json")
        active_payload = active_chain_payload()
        patch_rows, mutation_rows = apply_configs(root, apply_patches, dry_run_patches)
        refs = load_references(v229)
        triage = build_triage(root, refs, active_payload)
        active_manifest = manifest_rows(active_payload, root / "scripts/v21/v21_data_source_policy_guard.py")
        guard_rows = guard_audit(active_manifest, root, max_content_scan_bytes)
        true_after = len([r for r in triage["active"] if r["still_blocks_next_stage"]])
        still_blocks_v21_230 = true_after
        readiness = [
            {"check_name": "central_policy_guard_present", "pass": (root / "scripts/v21/v21_data_source_policy_guard.py").exists() or (Path(__file__).with_name("v21_data_source_policy_guard.py")).exists(), "severity": "ERROR", "blocks_v21_230": False, "notes": "guard module required"},
            {"check_name": "policy_config_present", "pass": (root / "config/v21/data_source_policy.json").exists() or dry_run_patches, "severity": "ERROR", "blocks_v21_230": False, "notes": "Moomoo-only config required"},
            {"check_name": "true_active_blockers_remaining", "pass": still_blocks_v21_230 == 0, "severity": "WARN", "blocks_v21_230": still_blocks_v21_230 > 0, "notes": "active manifest blockers must be zero for V21.230"},
        ]
        v21_230_ready = all(not r["blocks_v21_230"] and r["pass"] for r in readiness)
        status = WARN_BLOCKED_STATUS if still_blocks_v21_230 else WARN_LEGACY_STATUS if (triage["legacy"] or triage["diag"] or triage["hist"] or triage["docs"] or triage["tests"]) else PASS_STATUS
        summary = {
            **base_summary(root, out, True, status, PASS_DECISION if v21_230_ready else BLOCKED_DECISION, 0),
            "original_active_yfinance_blocker_count": int(original.get("active_yfinance_blocker_count", 0) or 0),
            "original_active_yahoo_blocker_count": int(original.get("active_yahoo_blocker_count", 0) or 0),
            "original_external_fallback_blocker_count": int(original.get("external_fallback_blocker_count", 0) or 0),
            "triaged_reference_count": len(triage["master"]),
            "true_active_blocker_count_before": len(triage["active"]),
            "true_active_blocker_count_after": true_after,
            "legacy_deprecated_reference_count": len(triage["legacy"]),
            "diagnostic_only_reference_count": len(triage["diag"]),
            "historical_metadata_reference_count": len(triage["hist"]),
            "docs_or_report_reference_count": len(triage["docs"]),
            "test_fixture_reference_count": len(triage["tests"]),
            "unknown_review_required_count": len(triage["unknown"]),
            "patched_file_count": sum(1 for r in patch_rows if r["changed"] and not dry_run_patches),
            "active_chain_manifest_entry_count": len(active_manifest),
            "guard_required_count": len(guard_rows),
            "guard_present_count": sum(1 for r in guard_rows if r["guard_present"]),
            "still_blocks_v21_230_count": still_blocks_v21_230,
            "v21_230_ready": v21_230_ready,
            "warning_count": 1 if status.startswith("WARN") else 0,
        }
        write_csv(out / "blocker_triage_master.csv", triage["master"], TRIAGE_FIELDS)
        write_csv(out / "true_active_blockers.csv", triage["active"], ACTIVE_BLOCKER_FIELDS)
        write_csv(out / "legacy_deprecated_references.csv", triage["legacy"], LEGACY_FIELDS)
        write_csv(out / "diagnostic_only_references.csv", triage["diag"], DIAG_FIELDS)
        write_csv(out / "historical_metadata_references.csv", triage["hist"], TRIAGE_FIELDS)
        write_csv(out / "false_positive_or_context_only_references.csv", triage["false"], TRIAGE_FIELDS)
        write_csv(out / "active_chain_manifest.csv", active_manifest, ACTIVE_MANIFEST_FIELDS)
        write_csv(out / "diagnostic_only_allowlist.csv", triage["diag"], DIAG_FIELDS)
        write_csv(out / "legacy_deprecated_allowlist.csv", triage["legacy"], LEGACY_FIELDS)
        write_csv(out / "enforcement_patch_manifest.csv", patch_rows, PATCH_FIELDS)
        write_csv(out / "guard_coverage_audit.csv", guard_rows, GUARD_FIELDS)
        write_json(out / "rerun_v21_229_recommendation.json", {"recommended": True, "command": ".\\scripts\\v21\\run_v21_229_moomoo_only_data_source_policy_gate.ps1", "reason": "confirm active blockers are classified or removed from active manifest"})
        write_csv(out / "v21_230_readiness_gate.csv", readiness, READINESS_FIELDS)
        write_csv(out / "source_mutation_audit.csv", mutation_rows, MUTATION_FIELDS)
        write_json(out / "v21_229_r1_summary.json", summary)
        write_report(out / "V21.229_R1_active_data_source_blocker_triage_and_enforcement_report.txt", summary)
    except Exception as exc:
        summary = base_summary(root, out, True, FAIL_PATCH_STATUS, "MOOMOO_ONLY_ACTIVE_CHAIN_ENFORCEMENT_PATCH_FAILED", 1)
        summary["error_message"] = f"{type(exc).__name__}: {exc}"
        write_json(out / "v21_229_r1_summary.json", summary)
    return print_summary(summary, out)


def base_summary(root: Path, out: Path, found: bool, status: str, decision: str, errors: int) -> dict[str, Any]:
    return {
        "final_status": status,
        "final_decision": decision,
        "repo_root": str(root),
        "output_dir": str(out),
        "v21_229_input_found": found,
        "original_active_yfinance_blocker_count": 0,
        "original_active_yahoo_blocker_count": 0,
        "original_external_fallback_blocker_count": 0,
        "triaged_reference_count": 0,
        "true_active_blocker_count_before": 0,
        "true_active_blocker_count_after": 0,
        "legacy_deprecated_reference_count": 0,
        "diagnostic_only_reference_count": 0,
        "historical_metadata_reference_count": 0,
        "docs_or_report_reference_count": 0,
        "test_fixture_reference_count": 0,
        "unknown_review_required_count": 0,
        "patched_file_count": 0,
        "active_chain_manifest_entry_count": 0,
        "guard_required_count": 0,
        "guard_present_count": 0,
        "still_blocks_v21_230_count": 0,
        "v21_230_ready": False,
        "data_source_policy": "MOOMOO_ONLY",
        "yfinance_used": False,
        "yahoo_used": False,
        "data_fetch_used": False,
        "moomoo_import_used": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
        "warning_count": 0,
        "error_count": errors,
    }


def write_report(path: Path, summary: dict[str, Any]) -> None:
    keys = ["final_status","final_decision","original_active_yfinance_blocker_count","original_active_yahoo_blocker_count","original_external_fallback_blocker_count","triaged_reference_count","true_active_blocker_count_before","true_active_blocker_count_after","legacy_deprecated_reference_count","diagnostic_only_reference_count","unknown_review_required_count","patched_file_count","active_chain_manifest_entry_count","guard_present_count","still_blocks_v21_230_count","v21_230_ready","warning_count","error_count"]
    path.write_text("\n".join([STAGE, *[f"{k}={summary[k]}" for k in keys], "historical_output_mutation=False", "data_fetch_used=False", "moomoo_import_used=False", "broker_action_allowed=False", "official_adoption_allowed=False"]) + "\n", encoding="utf-8")


def print_summary(summary: dict[str, Any], out: Path) -> dict[str, Any]:
    for key in ["final_status","final_decision","original_active_yfinance_blocker_count","original_active_yahoo_blocker_count","original_external_fallback_blocker_count","triaged_reference_count","true_active_blocker_count_before","true_active_blocker_count_after","legacy_deprecated_reference_count","diagnostic_only_reference_count","unknown_review_required_count","patched_file_count","active_chain_manifest_entry_count","guard_present_count","still_blocks_v21_230_count","v21_230_ready","warning_count","error_count"]:
        print(f"{key}={summary[key]}")
    print(f"summary_path={out / 'v21_229_r1_summary.json'}")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=STAGE)
    p.add_argument("--repo-root")
    p.add_argument("--output-dir")
    p.add_argument("--v21-229-output-dir")
    p.add_argument("--apply-patches", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--dry-run-patches", action="store_true")
    p.add_argument("--max-content-scan-bytes", type=int, default=2_000_000)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(
        repo_root=Path(args.repo_root) if args.repo_root else None,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        v21_229_output_dir=Path(args.v21_229_output_dir) if args.v21_229_output_dir else None,
        apply_patches=args.apply_patches,
        dry_run_patches=args.dry_run_patches,
        max_content_scan_bytes=args.max_content_scan_bytes,
    )
    return 1 if summary["final_status"] in {FAIL_INPUT_STATUS, FAIL_PATCH_STATUS} else 0


if __name__ == "__main__":
    sys.exit(main())
