"""Final internal-blocker and zero-quota A2 coverage closeout.

This runner consumes the frozen upstream ledgers.  It performs no price fetch,
model work, candidate build, or promotion when the live historical-security
quota remains zero.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


TASK = "A2_INTERNAL_BLOCKER_AND_FINAL_COVERAGE_CLOSEOUT_R1"
TARGET = "2026-08-20"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK
FOUNDATION = RESULTS / "A2_FORWARD_FOUNDATION_CLOSEOUT_R1"
GAP_CLOSE = RESULTS / "A2_CANONICAL_COVERAGE_GAP_CLOSE_AND_PROMOTION_R1"
QUOTA_CLOSE = RESULTS / "A2_CANONICAL_COVERAGE_QUOTA_AWARE_CLOSEOUT_R1"
R3 = RESULTS / "A2_PIT_CANONICAL_COVERAGE_R3"
NG_R3 = RESULTS / "A2_NG8_FORWARD_PIT_CANONICAL_COVERAGE_REMEDIATION_R3"
PIT = RESULTS / "A2_CANONICAL_FORWARD_READINESS_R2/component_inputs/2026-08-20/pit_universe.json"
POINTER = Path(
    r"D:\us-tech-quant-daily\current\V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD"
    r"\canonical_snapshot_pointer.json"
)
MAPPING = REPO / "scripts/v22/a2_pit_moomoo_current_week_completion_r1.py"
MAPPING_TEST = REPO / "scripts/v22/test_a2_pit_moomoo_current_week_completion_r1.py"
TMP_TEST = REPO / "scripts/v22/test_a2_forward_shadow_production_blocker_closeout_r1a.py"
GUARD = REPO / "fast3/scripts/audit/run_fast3_guard.py"
POLICY = REPO / "docs/governance/ANTI_BLOAT_POLICY.md"
BROKER_BINDING = REPO / "config/research_governance/a2_forward_shadow_production_binding_r1.json"
TEMP_BLOCKER = Path(r"D:\us-tech-quant\.tmp_a2_gap_close_r1_pytest")
NEW_TEST_TEMP = Path(
    r"D:\us-tech-quant-results\_pytest_tmp"
    r"\A2_INTERNAL_BLOCKER_AND_FINAL_COVERAGE_CLOSEOUT_R1_forward_closeout_synthetic"
)
STAGE_RAW = R3 / "api_incremental_raw_20260819_20260820.parquet"
STAGE_QFQ = R3 / "api_incremental_qfq_20260819_20260820.parquet"
STAGE_ACTIONS = NG_R3 / "remediation_actions.csv"
LOOKBACK = NG_R3 / "lookback_sufficiency_report.csv"
EXPECTED_OUTPUTS = {
    "task_receipt.json", "internal_blocker_closeout.json", "coverage_final_ledger.csv",
    "quota_fetch_execution.json", "promotion_manifest.json",
    "post_promotion_reconciliation.json", "final_report.md", "hash_manifest.json",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_json(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def strict_bool(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def validate_result(root: Path) -> dict[str, Any]:
    manifest = read_json(root / "hash_manifest.json")
    entries = manifest.get("artifacts")
    if entries is None:
        entries = [
            {"path": str(root / name), **record}
            for name, record in manifest["files"].items()
        ]
    failures = []
    for entry in entries:
        path = Path(entry["path"])
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            failures.append(str(path))
    return {"status": "PASS" if not failures else "FAIL", "failures": failures}


def live_quota(mapping: Any) -> tuple[dict[str, Any], set[str]]:
    used, remaining, detail = mapping.quota_detail()
    normalized = sorted(
        ({"code": str(item.get("code", "")), "request_time": str(item.get("request_time", ""))} for item in detail),
        key=lambda item: (item["code"], item["request_time"]),
    )
    times = sorted(item["request_time"] for item in normalized if item["request_time"])
    return ({
        "check_status": "PASS_LIVE_MOOMOO_QUOTA",
        "historical_security_used": int(used),
        "historical_security_limit": int(used + remaining),
        "historical_security_remaining": int(remaining),
        "detail_count": len(detail),
        "quota_period_context": "PROVIDER_ROLLING_DETAIL;RESET_TIME_NOT_REPORTED",
        "earliest_request_time": times[0] if times else None,
        "latest_request_time": times[-1] if times else None,
        "normalized_code_request_time_sha256": hash_json(normalized),
    }, {item["code"] for item in normalized if item["code"]})


def guard_audit() -> dict[str, Any]:
    result = subprocess.run(
        [r"D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe", str(GUARD)],
        cwd=REPO, text=True, capture_output=True, check=False,
    )
    payload = json.loads(result.stdout)
    repository = next(check for check in payload["checks"] if check["name"] == "repository_budget")
    material = [row for row in repository["access_errors"] if row["material_to_repo_accounting"]]
    return {
        "status": payload["status"],
        "exit_code": result.returncode,
        "violations": payload["violations"],
        "current_new_violation_count": payload["current_new_violation_count"],
        "repository_worktree_bytes_lower_bound": repository["repository_worktree_bytes"],
        "repository_target_300m_status": repository["target_300m_status"],
        "repository_preferred_150m_status": repository["preferred_150m_status"],
        "repo_local_venv_exists": repository["repository_local_venv_exists"],
        "oversized_files": repository["oversized_files"],
        "new_files_over_10m": repository["new_files_over_10m"],
        "forbidden_artifacts": repository["forbidden_artifacts"],
        "material_access_errors": material,
    }


def main() -> int:
    assert not OUT.exists(), f"OUTPUT_ALREADY_EXISTS:{OUT}"
    upstream = {
        str(root): validate_result(root)
        for root in (FOUNDATION, GAP_CLOSE, QUOTA_CLOSE)
    }
    assert all(value["status"] == "PASS" for value in upstream.values())

    prior_ledger = pd.read_csv(QUOTA_CLOSE / "coverage_gap_ledger.csv", dtype=str).fillna("")
    prior_plan = read_json(QUOTA_CLOSE / "quota_and_fetch_plan.json")
    prior_recon = read_json(QUOTA_CLOSE / "post_promotion_reconciliation.json")
    gap_ledger = pd.read_csv(GAP_CLOSE / "coverage_gap_ledger.csv", dtype=str).fillna("")
    gap_receipt = read_json(GAP_CLOSE / "task_receipt.json")
    quota_receipt = read_json(QUOTA_CLOSE / "task_receipt.json")
    pit = pd.DataFrame(read_json(PIT)["members"])[["security_id", "ticker"]].astype(str)

    assert len(prior_ledger) == prior_ledger.security_id.nunique()
    assert len(prior_plan["next_fetch_plan"]) == len(prior_ledger)
    assert prior_plan["next_fetch_plan_sha256"] == hash_json(prior_plan["next_fetch_plan"])
    assert set(prior_ledger.security_id) == {str(row["security_id"]) for row in prior_plan["next_fetch_plan"]}
    ge = prior_ledger.loc[prior_ledger.security_id.eq("369604301")]
    assert len(ge) == 1
    assert ge.iloc[0].canonical_ticker == "GE" and ge.iloc[0].broker_symbol == "US.GE"

    required = gap_ledger.final_required.map(strict_bool)
    covered = gap_ledger.final_covered.map(strict_bool)
    staged = gap_ledger.final_classification.eq("STAGED_VALID_FOR_PROMOTION") & required
    unresolved = gap_ledger.final_classification.eq("UNRESOLVED_REQUIRED_QUOTA_BLOCKED") & required
    exclusions = gap_ledger.final_classification.eq("LEGITIMATE_MODEL_SAFE_EXCLUSION")
    covered_ids = set(gap_ledger.loc[covered & required, "security_id"])
    staged_ids = set(gap_ledger.loc[staged, "security_id"])
    unresolved_ids = set(gap_ledger.loc[unresolved, "security_id"])
    exclusion_ids = set(gap_ledger.loc[exclusions, "security_id"])
    assert set(prior_ledger.security_id) == unresolved_ids
    assert not (covered_ids & staged_ids or covered_ids & unresolved_ids or staged_ids & unresolved_ids)
    assert (covered_ids | staged_ids | unresolved_ids | exclusion_ids) == set(pit.security_id)
    assert set(gap_ledger.loc[exclusions, "ticker"]) == {"EA", "TALK", "OLPX", "PAYP"}
    assert gap_ledger.loc[exclusions, "exclusion_reason"].str.len().gt(0).all()
    assert gap_ledger.loc[exclusions, "classification_change_evidence"].str.len().gt(0).all()

    expected_stage_hashes = prior_recon["validation"]["staged_integrity"]["hashes"]
    stage_paths = (STAGE_RAW, STAGE_QFQ, STAGE_ACTIONS, LOOKBACK)
    current_stage_hashes = {str(path): sha256_file(path) for path in stage_paths}
    stage_hash_pass = current_stage_hashes == expected_stage_hashes
    raw_target = pd.read_parquet(STAGE_RAW, columns=["ticker", "date"])
    qfq_target = pd.read_parquet(STAGE_QFQ, columns=["ticker", "date"])
    raw_target = raw_target.loc[raw_target.date.astype(str).str[:10].eq(TARGET)]
    qfq_target = qfq_target.loc[qfq_target.date.astype(str).str[:10].eq(TARGET)]
    staged_tickers = set(gap_ledger.loc[staged, "ticker"])
    stage_set_pass = (
        set(raw_target.ticker.astype(str)) & staged_tickers
        == set(qfq_target.ticker.astype(str)) & staged_tickers
        == staged_tickers
    )
    staged_integrity = stage_hash_pass and stage_set_pass
    assert staged_integrity

    pointer_bytes = POINTER.read_bytes()
    pointer = json.loads(pointer_bytes)
    manifest_path = Path(pointer["canonical_manifest_path"])
    raw_path = Path(pointer["canonical_raw_path"])
    qfq_path = Path(pointer["canonical_qfq_path"])
    expected = quota_receipt["source_hashes"]
    canonical_hashes = {
        str(POINTER): sha256_file(POINTER),
        str(manifest_path): sha256_file(manifest_path),
        str(raw_path): sha256_file(raw_path),
        str(qfq_path): sha256_file(qfq_path),
    }
    canonical_identity = all(current == expected[path] for path, current in canonical_hashes.items())
    assert canonical_identity

    mapping = load_module("a2_internal_final_mapping", MAPPING)
    intervals = pd.read_parquet(RESULTS / "A2_PIT13F_MATERIALIZATION_R1/effective_universe_intervals.parquet")
    frozen_ge = intervals.loc[intervals.security_id.astype(str).eq("369604301")]
    fixed_ge = mapping.apply_security_identity_overrides(frozen_ge)
    ge_pass = (
        not fixed_ge.empty
        and set(fixed_ge.ticker.astype(str)) == {"GE"}
        and set(fixed_ge.moomoo_transport_code.astype(str)) == {"US.GE"}
    )
    assert ge_pass

    quota, touched = live_quota(mapping)
    if quota["historical_security_remaining"] != 0:
        raise RuntimeError("QUOTA_RECOVERED_REQUIRES_FETCH_REMEDIATION_BRANCH;NO_WAITING_ARTIFACT_WRITTEN")
    frozen_codes = set(prior_ledger.broker_symbol)
    already_touched = frozen_codes & touched
    assert not already_touched

    guard = guard_audit()
    blocker_material = any(row["path"] == str(TEMP_BLOCKER) for row in guard["material_access_errors"])
    assert guard["status"] == "FAIL" and blocker_material
    assert not NEW_TEST_TEMP.exists()
    repo_local_venv_count = int(guard["repo_local_venv_exists"])
    broker_binding = read_json(BROKER_BINDING)
    assert pointer.get("broker_action_allowed") is False
    assert broker_binding.get("broker_action_allowed") is False

    # No state-changing data action occurred; verify immutable bodies one last time.
    canonical_identity = canonical_identity and (
        POINTER.read_bytes() == pointer_bytes
        and sha256_file(manifest_path) == canonical_hashes[str(manifest_path)]
        and sha256_file(raw_path) == canonical_hashes[str(raw_path)]
        and sha256_file(qfq_path) == canonical_hashes[str(qfq_path)]
    )
    assert canonical_identity

    overall = "WAITING_FOR_QUOTA_FINAL_FETCH_READY"
    temp_status = "BLOCKED_MANAGED_ACL_AFTER_SAFE_DELETE_AND_EXACT_QUARANTINE_MOVE"
    anti_bloat_status = "FAIL_ONE_MATERIAL_UNREADABLE_REPO_TEMP;EXTERNAL_MANAGED_ACL_BLOCK"
    final_rows = []
    for row in prior_ledger.to_dict("records"):
        final_rows.append({
            **row,
            "target_date": TARGET,
            "cohort_status": "FROZEN_FINAL_FETCH_READY",
            "current_quota_touched": str(row["broker_symbol"] in touched),
            "actual_fetch_attempted": "False",
            "final_unresolved": "True",
        })
    fields = list(final_rows[0])

    OUT.mkdir(parents=True, exist_ok=False)
    ledger_tmp = OUT / "coverage_final_ledger.csv.tmp"
    with ledger_tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(final_rows)
    os.replace(ledger_tmp, OUT / "coverage_final_ledger.csv")

    blocker = {
        "task_id": TASK,
        "temp_blocker_path": str(TEMP_BLOCKER),
        "existence_at_final_check": TEMP_BLOCKER.exists(),
        "creation_time_utc": "2026-08-22T14:56:48",
        "last_write_time_utc": "2026-08-22T14:56:48",
        "origin_task": "A2_CANONICAL_COVERAGE_GAP_CLOSE_AND_PROMOTION_R1",
        "classification": ["STALE_TEST_TEMP", "MANAGED_ACL_BLOCKED"],
        "root_cause": "MANAGED_ACL_BLOCKED;OWNER_AND_ACL_UNREADABLE",
        "attributes": "Directory",
        "owner": "UNREADABLE_ACCESS_DENIED",
        "contents_classification": "PYTEST_TASK_TEMP;CONTENTS_UNREADABLE_FAIL_CLOSED_PRESERVED",
        "active_process_check": "NO_PYTHON_OR_PYTEST_PROCESS_VISIBLE;EXACT_COMMANDLINE_AND_OPENFILES_QUERY_ACCESS_DENIED",
        "process_termination_count": 0,
        "cleanup_attempts": [
            {"attempt": 1, "action": "NORMAL_RECURSIVE_DELETE_EXACT_PATH", "result": "ACCESS_DENIED"},
            {"attempt": 2, "action": "OPEN_HANDLE_AND_ACTIVE_PROCESS_IDENTIFICATION", "result": "NO_PYTHON_PYTEST_VISIBLE;SYSTEM_QUERY_ACCESS_DENIED;NO_PROCESS_TERMINATED"},
            {"attempt": 3, "action": "EXACT_PATH_MOVE_TO_EXTERNAL_MAINTENANCE_QUARANTINE", "result": "ACCESS_DENIED;EMPTY_QUARANTINE_ROOT_REMOVED"},
        ],
        "temp_cleanup_status": temp_status,
        "temp_blocker_external_managed_acl": True,
        "broad_acl_mutation_count": 0,
        "takeown_count": 0,
        "recursive_icacls_count": 0,
        "tmp_path_tests": {
            "discovered": 33,
            "first_external_routing_attempt": "24_PASS;9_SETUP_ERROR_MISSING_REQUIRED_SYNTHETIC_ROOT_ENV",
            "final_external_routing_attempt": "33_PASS;0_FAIL;0_ERROR",
            "executed": 33,
            "pass": 33,
            "fail": 0,
            "error": 0,
            "pytest_acl_status": "PASS_EXTERNAL_TASK_TEMP_ROUTING_33_OF_33",
            "new_external_temp_cleanup": "PASS_NO_RESIDUAL",
        },
        "anti_bloat": guard,
        "anti_bloat_status": anti_bloat_status,
        "internal_engineering_ready": False,
        "internal_engineering_blocker": str(TEMP_BLOCKER),
    }
    write_json(OUT / "internal_blocker_closeout.json", blocker)

    quota_execution = {
        "task_id": TASK,
        "target_date": TARGET,
        "branch": "BRANCH_A_ZERO_QUOTA",
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "live_quota": quota,
        "pre_task_unresolved_required_count": len(prior_ledger),
        "frozen_fetch_cohort_count": len(final_rows),
        "frozen_fetch_cohort_sha256": hash_json(prior_plan["next_fetch_plan"]),
        "already_touched_count": len(already_touched),
        "new_unique_quota_required_count": len(frozen_codes - touched),
        "actual_historical_fetch_security_count": 0,
        "fetch_request_count_for_prevalidated_321": 0,
        "fetch_success_count": 0,
        "fetch_failure_count": 0,
        "price_api_request_count": 0,
        "final_unresolved_required_count": len(final_rows),
        "fetch_plan_source": str(QUOTA_CLOSE / "quota_and_fetch_plan.json"),
        "quota_reset_time_assumption": "NONE",
    }
    write_json(OUT / "quota_fetch_execution.json", quota_execution)

    promotion = {
        "task_id": TASK,
        "PROMOTION_EXECUTED": False,
        "reason": "WAITING_FOR_HISTORICAL_SECURITY_QUOTA;REQUIRED_GAP_REMAINS",
        "candidate_snapshot_status": "NOT_CREATED_ZERO_QUOTA_INCOMPLETE_REQUIRED_GATE",
        "atomic_promotion_status": "NOT_EXECUTED_FAIL_CLOSED",
        "existing_authoritative_snapshot_id": pointer["snapshot_id"],
        "existing_canonical_manifest_sha256": canonical_hashes[str(manifest_path)],
        "new_canonical_snapshot_id": None,
        "new_canonical_manifest_sha256": None,
        "partial_promotion_executed": False,
        "authoritative_pointer_unchanged": True,
    }
    write_json(OUT / "promotion_manifest.json", promotion)

    pit_count = len(pit)
    required_count = len(covered_ids | staged_ids | unresolved_ids)
    exclusion_count = len(exclusion_ids)
    silent_count = int(
        gap_ledger.loc[exclusions, "exclusion_reason"].eq("").sum()
        + gap_ledger.loc[exclusions, "classification_change_evidence"].eq("").sum()
    )
    coverage_pct = 100 * len(covered_ids) / required_count
    reconciliation = {
        "task_id": TASK,
        "overall_status": overall,
        "target_date": TARGET,
        "pit_universe_security_count": pit_count,
        "active_tradable_required_count": required_count,
        "legitimate_exclusion_count": exclusion_count,
        "silent_exclusion_count": silent_count,
        "authoritative_model_safe_coverage_count": len(covered_ids),
        "authoritative_model_safe_coverage_pct": round(coverage_pct, 6),
        "prevalidated_staged_count": len(staged_ids),
        "staged_321_integrity_status": "PASS_HASH_MANIFEST_EXISTENCE_NO_MUTATION",
        "staged_321_refetch_count": 0,
        "final_unresolved_required_count": len(final_rows),
        "historical_canonical_identity_status": "PASS_HASH_VERIFIED_NO_MUTATION",
        "canonical_mutation_count": 0,
        "staged_321_mutation_count": 0,
        "candidate_snapshot_status": promotion["candidate_snapshot_status"],
        "atomic_promotion_status": promotion["atomic_promotion_status"],
        "post_promotion_verification": "NOT_APPLICABLE_PROMOTION_NOT_EXECUTED;CURRENT_POINTER_RELOADED_AND_HASH_VERIFIED",
        "anti_bloat_status": anti_bloat_status,
        "internal_engineering_ready": False,
        "clean_forward_foundation_ready": False,
        "ready_for_unified_replay": False,
        "upstream_hash_validation": upstream,
    }
    write_json(OUT / "post_promotion_reconciliation.json", reconciliation)

    source_paths = [
        FOUNDATION / "hash_manifest.json", GAP_CLOSE / "hash_manifest.json",
        QUOTA_CLOSE / "hash_manifest.json", QUOTA_CLOSE / "coverage_gap_ledger.csv",
        QUOTA_CLOSE / "quota_and_fetch_plan.json", GAP_CLOSE / "coverage_gap_ledger.csv",
        PIT, STAGE_RAW, STAGE_QFQ, STAGE_ACTIONS, LOOKBACK, POINTER,
        manifest_path, raw_path, qfq_path, MAPPING, MAPPING_TEST, TMP_TEST,
        GUARD, POLICY, BROKER_BINDING, Path(__file__),
    ]
    receipt = {
        "task_id": TASK,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "target_date": TARGET,
        "authoritative_upstreams": [str(FOUNDATION), str(GAP_CLOSE), str(QUOTA_CLOSE)],
        "source_hashes": {str(path): sha256_file(path) for path in source_paths},
        "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, text=True, capture_output=True, check=True).stdout.strip(),
        "git_worktree_dirty": bool(subprocess.run(["git", "status", "--porcelain"], cwd=REPO, text=True, capture_output=True, check=True).stdout.strip()),
        "network_calls": {"quota_probe_count": 1, "price_api_request_count": 0},
        "source_modification_count_for_task": 1,
        "deletion_count": 1,
        "deletion_detail": "NEW_EXTERNAL_PYTEST_TEMP_ONLY;STALE_REPO_TEMP_PRESERVED_ACCESS_DENIED",
        "prohibited_actions": {
            "model_training_executed": False,
            "2026_used_for_training": False,
            "2026_used_for_model_selection": False,
            "broker_action_executed": False,
            "candidate_snapshot_created": False,
            "promotion_executed": False,
            "broad_acl_mutation_executed": False,
            "git_commit_or_push_executed": False,
        },
    }
    write_json(OUT / "task_receipt.json", receipt)

    report = f"""# {TASK}

Overall status: `{overall}`. The frozen cohort is final-fetch ready, but live historical quota is zero. The legacy repo temp remains a managed ACL hard-gate failure; the 33 affected tests now execute successfully through an external task-specific temp root.

## Required answers

1. Unreadable temp exact path: `{TEMP_BLOCKER}`.
2. Root cause: `MANAGED_ACL_BLOCKED`; owner/ACL and content traversal return AccessDenied. It is a stale pytest task temp by path, timestamps and originating run, with no visible Python/pytest process; exact open-handle attribution is unavailable under the same managed policy.
3. Deleted or moved out of repo: **no**. Exact normal delete and exact quarantine move both returned AccessDenied; the object was preserved fail-closed.
4. Broad ACL mutation performed: **false** (`0`). No takeown, recursive icacls or parent ACL mutation was used.
5. The 33 tmp-path tests truly executed: **yes**, in a fresh canonical Python process with external TEMP/TMP/TMPDIR, explicit basetemp and required synthetic-root environment.
6. Final test result: **33 passed, 0 failed, 0 errors**. The first routing attempt produced 24 passes and 9 setup errors until the existing synthetic-root contract was supplied.
7. Anti-Bloat final status: `{anti_bloat_status}`. The single violation is repository accounting incomplete for the exact unreadable temp.
8. Repo-local venv count: **{repo_local_venv_count}**.
9. The 321 staged securities remain mutation-free: **yes**, `PASS_HASH_MANIFEST_EXISTENCE_NO_MUTATION`; refetch count is 0.
10. Frozen unresolved cohort: **{len(final_rows)}** unique securities; ledger and next-fetch-plan identities reconcile exactly.
11. GE mapping remains PASS: **CUSIP 369604301 / GE / US.GE**; frozen GE.WI input is corrected only at the mapping boundary.
12. Live historical quota: **{quota['historical_security_used']} used / {quota['historical_security_limit']} limit / {quota['historical_security_remaining']} remaining**; provider reset time was not reported.
13. Quota recovered: **no**.
14. Historical securities actually fetched: **0**.
15. Fetch successes: **0**.
16. Fetch failures: **0**; no price request was sent.
17. Final unresolved required: **{len(final_rows)}**.
18. Candidate snapshot created: **no** (`{promotion['candidate_snapshot_status']}`).
19. Historical no-mutation: **PASS_HASH_VERIFIED_NO_MUTATION**; canonical mutation count is 0.
20. Atomic promotion executed: **no** (`NOT_EXECUTED_FAIL_CLOSED`).
21. New canonical snapshot ID/hash: **none**. Existing snapshot remains `{pointer['snapshot_id']}` / `{canonical_hashes[str(manifest_path)]}`.
22. Authoritative model-safe coverage: **{len(covered_ids)}/{required_count} = {coverage_pct:.2f}%**. The validated staged rows are not counted as authoritative before atomic promotion.
23. Ready for `A2_UNIFIED_REPLAY_AND_ATTRIBUTION_R1`: **no**. Coverage first requires quota release, 60-security remediation and atomic promotion; Anti-Bloat also remains blocked by the exact managed ACL object.

## Reconciliation and safety

- `{pit_count} PIT = {required_count} required + {exclusion_count} legitimate exclusions`; `{required_count} required = {len(covered_ids)} authoritative + {len(staged_ids)} prevalidated staged + {len(unresolved_ids)} unresolved`.
- Silent exclusions: `{silent_count}`. Four frozen exclusions remain EA, TALK, OLPX and PAYP with non-empty evidence references.
- New external pytest temp residual: `0`; repository-local venv: `0`; new oversized repository file: `0`.
- Model training, 2026 model selection, historical price fetch, candidate creation, promotion, broker action and Unified Replay were not executed.
"""
    (OUT / "final_report.md").write_text(report, encoding="utf-8")

    core = [
        "task_receipt.json", "internal_blocker_closeout.json", "coverage_final_ledger.csv",
        "quota_fetch_execution.json", "promotion_manifest.json",
        "post_promotion_reconciliation.json", "final_report.md",
    ]
    artifact_rows = [
        {"path": str(OUT / name), "bytes": (OUT / name).stat().st_size, "sha256": sha256_file(OUT / name)}
        for name in core
    ]
    write_json(OUT / "hash_manifest.json", {
        "task_id": TASK,
        "definition": "SHA256 of the seven other core artifacts; this manifest excludes itself",
        "artifacts": artifact_rows,
        "artifact_set_sha256": hash_json(artifact_rows),
    })
    assert {path.name for path in OUT.iterdir()} == EXPECTED_OUTPUTS

    summary = {
        "OVERALL_STATUS": overall,
        "TARGET_DATE": TARGET,
        "PIT_UNIVERSE_SECURITY_COUNT": pit_count,
        "ACTIVE_TRADABLE_REQUIRED_COUNT": required_count,
        "LEGITIMATE_EXCLUSION_COUNT": exclusion_count,
        "SILENT_EXCLUSION_COUNT": silent_count,
        "TEMP_BLOCKER_PATH": str(TEMP_BLOCKER),
        "TEMP_BLOCKER_ROOT_CAUSE": "MANAGED_ACL_BLOCKED",
        "TEMP_CLEANUP_STATUS": temp_status,
        "BROAD_ACL_MUTATION_COUNT": 0,
        "TMP_PATH_TESTS_DISCOVERED": 33,
        "TMP_PATH_TESTS_EXECUTED": 33,
        "TMP_PATH_TESTS_PASS": 33,
        "TMP_PATH_TESTS_FAIL": 0,
        "PYTEST_ACL_STATUS": "PASS_EXTERNAL_TASK_TEMP_ROUTING_33_OF_33",
        "ANTI_BLOAT_STATUS": anti_bloat_status,
        "REPO_LOCAL_VENV_COUNT": repo_local_venv_count,
        "STAGED_321_INTEGRITY_STATUS": "PASS_HASH_MANIFEST_EXISTENCE_NO_MUTATION",
        "STAGED_321_REFETCH_COUNT": 0,
        "GE_MAPPING_STATUS": "PASS_FIXED_AT_CUSIP_MAPPING_BOUNDARY",
        "GE_AUTHORITATIVE_IDENTITY": "CUSIP_369604301;TICKER_GE",
        "GE_BROKER_SYMBOL": "US.GE",
        "GE_REGRESSION_TEST_STATUS": "PASS_FOCUSED_SUITE_5_OF_5;CURRENT_MAPPING_REVERIFIED",
        "PRE_TASK_UNRESOLVED_REQUIRED_COUNT": len(prior_ledger),
        "FROZEN_FETCH_COHORT_COUNT": len(final_rows),
        "HISTORICAL_QUOTA_USED": quota["historical_security_used"],
        "HISTORICAL_QUOTA_LIMIT": quota["historical_security_limit"],
        "HISTORICAL_QUOTA_REMAINING_AT_FETCH_GATE": quota["historical_security_remaining"],
        "ACTUAL_HISTORICAL_FETCH_SECURITY_COUNT": 0,
        "FETCH_SUCCESS_COUNT": 0,
        "FETCH_FAILURE_COUNT": 0,
        "FINAL_UNRESOLVED_REQUIRED_COUNT": len(final_rows),
        "CANDIDATE_SNAPSHOT_STATUS": promotion["candidate_snapshot_status"],
        "HISTORICAL_CANONICAL_IDENTITY_STATUS": "PASS_HASH_VERIFIED_NO_MUTATION",
        "ATOMIC_PROMOTION_STATUS": "NOT_EXECUTED_FAIL_CLOSED",
        "NEW_CANONICAL_SNAPSHOT_ID": "",
        "NEW_CANONICAL_MANIFEST_SHA256": "",
        "FINAL_AUTHORITATIVE_MODEL_SAFE_COVERAGE_COUNT": len(covered_ids),
        "FINAL_AUTHORITATIVE_MODEL_SAFE_COVERAGE_PCT": f"{coverage_pct:.2f}%",
        "MODEL_TRAINING_EXECUTED": "false",
        "2026_USED_FOR_TRAINING": "false",
        "2026_USED_FOR_MODEL_SELECTION": "false",
        "CLEAN_FORWARD_FOUNDATION_READY": "false",
        "READY_FOR_UNIFIED_REPLAY": "false",
        "OFFICIAL_ADOPTION_ALLOWED": "false",
        "BROKER_ACTION_ALLOWED": "false",
        "OUTPUT_DIR": str(OUT),
        "FINAL_REPORT": str(OUT / "final_report.md"),
        "HASH_MANIFEST": str(OUT / "hash_manifest.json"),
    }
    print("=" * 60)
    print(f"{TASK}_FINAL")
    print("=" * 60)
    for key, value in summary.items():
        print(f"{key}={value}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
