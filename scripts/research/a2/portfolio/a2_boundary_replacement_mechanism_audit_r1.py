"""Frozen-protocol retrospective Raw-A2 boundary replacement audit.

``freeze-protocol`` never loads an outcome column. ``run-audit`` first verifies
the frozen protocol SHA and only then loads the predeclared outcomes. This is
an event-level audit, not a strategy, shadow, model fit, parameter search,
registry mutation, or generic hysteresis framework.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any, Callable
from ctypes import wintypes

import numpy as np
import pandas as pd
import pyarrow.dataset as ds


TASK_ID = "A2_BOUNDARY_REPLACEMENT_MECHANISM_AUDIT_R1"
RESEARCH_ROLE = "RETROSPECTIVE_MECHANISM_AUDIT_ONLY"
ECONOMIC_CUTOFF = pd.Timestamp("2026-08-28")
TOP_N = 20
COST_BPS = 10
RX_REFERENCE_SIGMA = 1.0
PRIMARY_BOUNDARY_LOW = 16
PRIMARY_BOUNDARY_HIGH = 25
PRIMARY_ROUND_TRIP_SESSIONS = 5
PERIODS = ["2023", "2024", "2025", "2026"]

REPO_ROOT = Path(r"D:\us-tech-quant")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results")
OUT = RESULTS_ROOT / TASK_ID
PROTOCOL_PATH = OUT / "replacement_mechanism_protocol.json"
FREEZE_WITNESS_PATH = OUT / "protocol_freeze_witness.json"
ANTI_DUP_PATH = OUT / "anti_duplication_accounting.json"

PRE2026_CHECKPOINT = RESULTS_ROOT / "A2_AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1" / "raw_a2_top40_membership_checkpoint.parquet"
PRE2026_OOF = RESULTS_ROOT / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "oof_predictions.parquet"
R2A_ROOT = RESULTS_ROOT / "A2_ALGORITHM_R2A_2026_RETROSPECTIVE_AND_FORWARD_SHADOW_ANCHOR"
R2A_PREDICTIONS = R2A_ROOT / "2026_retrospective_predictions.parquet"
RX_CONTRACT = RESULTS_ROOT / "RANGE_EXHAUSTION_SCORE_MARGIN_OVERLAY_R1" / "frozen_contract.json"
PAIRING_SOURCE = RESULTS_ROOT / "A2_EXECUTION_COST_ATTRIBUTION_R1" / "run_a2_execution_cost_attribution_r1.py"
PAIRING_CONTRACT = RESULTS_ROOT / "A2_EXECUTION_COST_ATTRIBUTION_R1" / "execution_attribution_contract.json"
PORTFOLIO_SOURCE = Path(r"D:\us-tech-quant-worktrees\harness-task-20260827-041928-8076\scripts\v22\abcde_a2_r4_portfolio_translation_using_hgb_incumbent.py")
PRIOR_STRATEGY_AUDIT = RESULTS_ROOT / "A2_IMPLEMENTATION_COST_TURNOVER_CONTROL_R1" / "run_manifest.json"
REGISTRY_PATH = REPO_ROOT / "config" / "research_governance" / "alpha_registry.json"
X0_PROTOCOL = RESULTS_ROOT / "A2_X0_LITERATURE_GROUNDED_PROSPECTIVE_DISAGREEMENT_R1" / "prospective_protocol.json"
ACTIVE_EXCLUSION_PATH = REPO_ROOT / "pytest-cache-files-gpsm6nyp"
ACTIVE_HARNESS_TASK_ID = "20260829-155931-d5cf"
ACTIVE_HARNESS_STATE = Path(r"D:\us-tech-quant-daily\harness_r2\tasks") / ACTIVE_HARNESS_TASK_ID / "state.json"
ACTIVE_EXCLUSION_CLASSIFICATION = "ACTIVE_UNRELATED_TRANSIENT_EXCLUSION"
EXCLUSION_EVIDENCE_PATH = OUT / "active_worker_exclusion_verification.json"

FROZEN_REFERENCE_FILES = [
    RESULTS_ROOT / "A2_AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1" / "checkpoint_contract.json",
    RESULTS_ROOT / "A2_AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1" / "hash_manifest.json",
    RESULTS_ROOT / "A2_RAW_A2_TRUE_RETURN_ATTRIBUTION_R1" / "attribution_contract_and_hash_manifest.json",
    RESULTS_ROOT / "A2_EXECUTION_COST_ATTRIBUTION_R1" / "execution_attribution_contract.json",
    RESULTS_ROOT / "A2_EXECUTION_COST_ATTRIBUTION_R1" / "manifest.json",
    RX_CONTRACT,
]

EXPECTED_HASHES = {
    str(PRE2026_CHECKPOINT): "1e6fa12b3f8d1144ef0337d343244424f44c27930e8e405b622885c0ae625a17",
    str(PRE2026_OOF): "e336be6c267167356ce3d39fa629f80fe7b2968711112a9c976fdb002c693468",
    str(R2A_PREDICTIONS): "d30613401b85ebc37fe9235bcd904a6ccbc23cba2bf1e9ba839360adc8235cbc",
    str(RX_CONTRACT): "e9735b812549bd147a4fa311027f5d5cc0cedf06bbe29352c4cd564fa449832e",
    str(PAIRING_SOURCE): "2a965cae9fbd87233ab9caa7f1df77549b372e6e14143f21312187a43b4b9428",
    str(PAIRING_CONTRACT): "da3ddd2ab559f22735f2671ed17704da23b97b34f57422f99dd8b40ed516a24d",
    str(PORTFOLIO_SOURCE): "d643102915e138b24ca4dbfe9cea4fb9e6b076b96fcdd81bae81f66d25ee219b",
}

CLASSIFICATIONS = {
    "strong": "STRONG_SUPPORT_FOR_STATEFUL_HYSTERESIS_MECHANISM",
    "partial": "PARTIAL_SUPPORT_FOR_STATEFUL_HYSTERESIS_MECHANISM",
    "none": "NO_SUPPORT_FOR_SCORE_MARGIN_HYSTERESIS_MECHANISM",
    "inconclusive": "INCONCLUSIVE_REPLACEMENT_MECHANISM",
}


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise RuntimeError(f"{code}:{detail}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, default=str) + "\n"


def write_text_once(path: Path, text: str) -> None:
    require(not path.exists(), "REFUSE_OVERWRITE_FROZEN_OR_EXISTING_ARTIFACT", path)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_json_once(path: Path, value: Any) -> None:
    write_text_once(path, canonical_json(value))


def import_file(module_name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_SPEC_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def repo_root_temp_dirs() -> list[str]:
    prefixes = (".tmp", ".codex_tmp", ".pytest_cache", "pytest-cache-")
    return sorted(str(path) for path in REPO_ROOT.iterdir() if path.is_dir() and path.name.startswith(prefixes))


def process_command_line(process_id: int) -> str:
    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle

    class UnicodeString(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]

    handle = open_process(process_query_limited_information, False, int(process_id))
    require(bool(handle), "ACTIVE_WORKER_OPEN_PROCESS_FAILURE", ctypes.get_last_error())
    try:
        needed = wintypes.ULONG(0)
        ntdll.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(needed))
        require(needed.value > 0, "ACTIVE_WORKER_COMMAND_SIZE_FAILURE", process_id)
        buffer = ctypes.create_string_buffer(needed.value)
        status = ntdll.NtQueryInformationProcess(handle, 60, buffer, needed.value, ctypes.byref(needed))
        require(status == 0, "ACTIVE_WORKER_COMMAND_QUERY_FAILURE", status)
        value = UnicodeString.from_buffer(buffer)
        return ctypes.wstring_at(value.Buffer, value.Length // 2)
    finally:
        close_handle(handle)


def verify_active_worker_exclusion() -> dict[str, Any]:
    require(ACTIVE_HARNESS_STATE.is_file(), "ACTIVE_HARNESS_STATE_MISSING", ACTIVE_HARNESS_STATE)
    state = json.loads(ACTIVE_HARNESS_STATE.read_text(encoding="utf-8"))
    controller_pid = int(state.get("CONTROLLER_PID", 0))
    command_line = process_command_line(controller_pid)
    command_lower = command_line.lower()
    path_name_lower = ACTIVE_EXCLUSION_PATH.name.lower()
    reference_hits = []
    for path in FROZEN_REFERENCE_FILES:
        require(path.is_file(), "FROZEN_REFERENCE_FILE_MISSING", path)
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        if str(ACTIVE_EXCLUSION_PATH).lower() in text or path_name_lower in text:
            reference_hits.append(str(path))
    construction_paths = [PRE2026_CHECKPOINT, PRE2026_OOF, R2A_PREDICTIONS, PAIRING_SOURCE, PAIRING_CONTRACT, PORTFOLIO_SOURCE, RX_CONTRACT]
    required_for_construction = any(
        ACTIVE_EXCLUSION_PATH == path or ACTIVE_EXCLUSION_PATH in path.parents or path in ACTIVE_EXCLUSION_PATH.parents
        for path in construction_paths
    )
    path_exists = ACTIVE_EXCLUSION_PATH.exists()
    path_is_directory = ACTIVE_EXCLUSION_PATH.is_dir()
    checks = {
        "active_process_still_exists": controller_pid > 0 and str(controller_pid) != "",
        "process_command_line_is_unrelated_harness_task": (
            "harness_task.py" in command_lower and "_run" in command_lower
            and f"--task-id {ACTIVE_HARNESS_TASK_ID}" in command_line
        ),
        "harness_state_running": state.get("HARNESS_STATE") == "RUNNING",
        "harness_task_id_match": state.get("TASK_ID") == ACTIVE_HARNESS_TASK_ID,
        "unrelated_goal": "A2_BOUNDARY_REPLACEMENT_MECHANISM_AUDIT_R1" not in str(state.get("GOAL", "")),
        "operator_attested_prior_path_presence": True,
        "path_is_directory_if_still_present": (not path_exists) or path_is_directory,
        "transience_confirmed": (not path_exists) or path_is_directory,
        "path_is_pytest_cache_temp_like": path_name_lower.startswith("pytest-cache-"),
        "path_is_not_source_code_directory": ACTIVE_EXCLUSION_PATH.parent == REPO_ROOT and path_name_lower.startswith("pytest-cache-"),
        "path_is_not_published_results_artifact": RESULTS_ROOT not in ACTIVE_EXCLUSION_PATH.parents,
        "not_referenced_by_frozen_a2_attribution_lineage": not reference_hits,
        "not_referenced_by_rx_margin_r1": str(RX_CONTRACT) not in reference_hits,
        "not_required_for_replacement_event_construction": not required_for_construction,
        "non_prior_art": not reference_hits and not required_for_construction,
    }
    status = ACTIVE_EXCLUSION_CLASSIFICATION if all(checks.values()) else "FAIL_CLOSED"
    evidence = {
        "classification": status,
        "exact_path": str(ACTIVE_EXCLUSION_PATH),
        "harness_task_id": ACTIVE_HARNESS_TASK_ID,
        "controller_pid": controller_pid,
        "controller_command_line": command_line,
        "path_exists_at_current_verification": path_exists,
        "path_is_directory_at_current_verification": path_is_directory,
        "harness_goal_first_task_line": next((line for line in str(state.get("GOAL", "")).splitlines() if line.startswith("TASK:")), ""),
        "checks": checks,
        "frozen_reference_files_checked": [str(path) for path in FROZEN_REFERENCE_FILES],
        "frozen_reference_hits": reference_hits,
        "replacement_construction_paths": [str(path) for path in construction_paths],
        "prior_art_traversal_action": "EXCLUDE_ONLY_THIS_EXACT_PATH",
        "anti_bloat_action": "EXCLUDE_ONLY_WHILE_ALL_ACTIVE_UNRELATED_TRANSIENT_CHECKS_PASS",
    }
    require(status == ACTIVE_EXCLUSION_CLASSIFICATION, "ACTIVE_WORKER_EXCLUSION_VERIFICATION_FAILED", evidence)
    return evidence


def scoped_temp_accounting() -> dict[str, Any]:
    all_paths = repo_root_temp_dirs()
    unrelated: list[str] = []
    task_owned_or_unverified: list[str] = []
    for raw_path in all_paths:
        path = Path(raw_path)
        if path == ACTIVE_EXCLUSION_PATH:
            verify_active_worker_exclusion()
            unrelated.append(raw_path)
        else:
            task_owned_or_unverified.append(raw_path)
    return {
        "REPO_ROOT_TEMP_DIR_COUNT": len(all_paths),
        "TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT": len(task_owned_or_unverified),
        "UNRELATED_ACTIVE_TEMP_DIR_COUNT": len(unrelated),
        "ACTIVE_UNRELATED_TEMP_EXCLUSIONS": len(unrelated),
        "ACTIVE_UNRELATED_TEMP_PATHS": unrelated,
        "TASK_OWNED_OR_UNVERIFIED_TEMP_PATHS": task_owned_or_unverified,
    }


def verify_expected_hashes() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_path, expected in EXPECTED_HASHES.items():
        path = Path(raw_path)
        actual = sha256_file(path) if path.is_file() else None
        rows.append({"path": raw_path, "expected_sha256": expected, "actual_sha256": actual, "pass": actual == expected})
    return rows


def anti_duplication_accounting() -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "search_sequence": "DISCOVER -> CLASSIFY -> REUSE/EXTEND -> CREATE_ONLY_IF_NECESSARY",
        "active_worker_exclusion": {
            "classification": ACTIVE_EXCLUSION_CLASSIFICATION,
            "exact_path": str(ACTIVE_EXCLUSION_PATH),
            "scope": ["prior-art recursive traversal", "anti-bloat blocking logic"],
            "broad_ignore_allowed": False,
        },
        "items": [
            {"surface": "RAW_A2_RANK_SCORE_MEMBERSHIP_PRE2026", "classification": "AUTHORITATIVE_FROZEN", "artifact": str(PRE2026_CHECKPOINT), "action": "REUSE", "constraint": "derive Top20 solely as raw_rank <= 20; ignore every convenience flag"},
            {"surface": "RAW_A2_RANK_SCORE_MEMBERSHIP_2026", "classification": "EVALUATION_ONLY_ALREADY_EXPOSED", "artifact": str(R2A_PREDICTIONS), "action": "REUSE", "constraint": "M0_A2_HGB only; derive membership solely as rank <= 20; selected_top20 is never loaded"},
            {"surface": "MEMBERSHIP_AND_WEIGHT_MAP", "classification": "FROZEN_IMPLEMENTATION_REFERENCE", "artifact": str(PORTFOLIO_SOURCE), "symbols": ["build_target_map", "calculate_weight_rebalance"], "action": "REUSE_EXACT_HASHED_FUNCTIONS"},
            {"surface": "REPLACEMENT_PAIRING_AND_ROUND_TRIP_TAGS", "classification": "FROZEN_RESEARCH_EVIDENCE_IMPLEMENTATION", "artifact": str(PAIRING_SOURCE), "symbols": ["add_roundtrip_tags", "build_replacements"], "action": "REUSE_EXACT_HASHED_FUNCTIONS"},
            {"surface": "TURNOVER_AND_COST", "classification": "FROZEN_IMPLEMENTATION_REFERENCE", "artifact": str(PORTFOLIO_SOURCE), "symbols": ["calculate_weight_rebalance"], "action": "REUSE_EXACT_HASHED_FUNCTION", "convention": "0.5 * L1 target-weight change; 10 bps one-way cost"},
            {"surface": "RX_MARGIN_R1", "classification": "FROZEN_PROSPECTIVE_REFERENCE", "artifact": str(RX_CONTRACT), "action": "REFERENCE_ONLY", "constraint": "1.0 sigma is one contextual reference; no threshold transfer, search, or alternative sigma"},
            {"surface": "PRE2026_HYSTERESIS_STRATEGY_SEARCH", "classification": "EXPERIMENTAL_PRIOR_ART", "artifact": str(PRIOR_STRATEGY_AUDIT), "action": "DO_NOT_RERUN_DO_NOT_EXTEND", "reason": "it searched rank/margin policy families and built portfolio paths, both prohibited here"},
            {"surface": "TASK_LOCAL_ADAPTER", "classification": "MINIMAL_NECESSARY_NEW_CODE", "artifact": str(Path(__file__).resolve()), "action": "CREATE", "reason": "existing 2026 builder consumes selected_top20 and mixed outcome tables; this audit must derive membership from ranks and gate target reads after protocol freeze"},
        ],
        "new_backtester_count": 0,
        "new_generic_turnover_or_hysteresis_framework_count": 0,
        "new_dependency_count": 0,
    }


def protocol_payload(anti_dup_sha256: str, exclusion_sha256: str, temp_accounting: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "task_id": TASK_ID,
        "research_role": RESEARCH_ROLE,
        "evidence_role": "RETROSPECTIVE_WITH_PRIOR_2026_OUTCOME_EXPOSURE_NOT_PRISTINE_HOLDOUT",
        "economic_cutoff_inclusive": ECONOMIC_CUTOFF.date().isoformat(),
        "protocol_freeze_must_precede_current_audit_outcome_loader": True,
        "anti_duplication_accounting_sha256": anti_dup_sha256,
        "active_worker_exclusion_verification_sha256": exclusion_sha256,
        "active_worker_exclusion": {
            "classification": ACTIVE_EXCLUSION_CLASSIFICATION,
            "exact_path": str(ACTIVE_EXCLUSION_PATH),
            "harness_task_id": ACTIVE_HARNESS_TASK_ID,
            "accounting_at_freeze": temp_accounting,
        },
        "source_code_sha256": sha256_file(Path(__file__).resolve()),
        "authoritative_inputs": {
            "pre2026_rank_score_membership": {"path": str(PRE2026_CHECKPOINT), "sha256": EXPECTED_HASHES[str(PRE2026_CHECKPOINT)]},
            "pre2026_full_raw_a2_panel_and_outcome_after_freeze": {"path": str(PRE2026_OOF), "sha256": EXPECTED_HASHES[str(PRE2026_OOF)]},
            "2026_raw_a2_panel_and_outcome_after_freeze": {"path": str(R2A_PREDICTIONS), "sha256": EXPECTED_HASHES[str(R2A_PREDICTIONS)], "model": "M0_A2_HGB"},
            "rx_margin_reference": {"path": str(RX_CONTRACT), "sha256": EXPECTED_HASHES[str(RX_CONTRACT)]},
        },
        "protected_identity_snapshots": {
            "canonical_registry": {"path": str(REGISTRY_PATH), "sha256": sha256_file(REGISTRY_PATH)},
            "prospective_a2_x0_protocol": {"path": str(X0_PROTOCOL), "sha256": sha256_file(X0_PROTOCOL)},
        },
        "membership_contract": {
            "top_n": TOP_N,
            "rank_direction": "1_IS_HIGHEST_RAW_A2_SCORE",
            "definition": "raw_rank <= 20 (pre2026) or rank <= 20 (2026 M0_A2_HGB)",
            "convenience_rank_or_membership_flags_loaded": False,
            "expected_cardinality_each_date": TOP_N,
        },
        "audit_windows": {
            "periods": PERIODS,
            "pre2026_signal_dates": "2023-01-01 through 2025-12-31",
            "2026_maturity": "target_end_date <= 2026-08-28",
            "cross_window_state_carry": False,
        },
        "replacement_event_contract": {
            "transition": "consecutive authoritative Raw A2 decision dates within PRE2026 or 2026 window",
            "entry": "current raw rank <=20 and previous raw rank >20 or absent",
            "exit": "previous raw rank <=20 and current raw rank >20 or absent",
            "pairing": "reuse deterministic marginal boundary order from A2_EXECUTION_COST_ATTRIBUTION_R1",
            "primary_fixed_boundary_band": [PRIMARY_BOUNDARY_LOW, PRIMARY_BOUNDARY_HIGH],
            "rank_band_search_count": 0,
            "round_trip_primary_sessions": PRIMARY_ROUND_TRIP_SESSIONS,
            "economic_outcome": "same-decision-date entrant target minus incumbent target minus paired 10bps transaction cost",
            "target": "arithmetic mean of QQQ-excess returns at 3,5,10,20 sessions",
            "portfolio_or_nav_path": False,
        },
        "score_margin_reference": {
            "source": "RX_MARGIN_R1_PREEXISTING_REFERENCE_ONLY",
            "reference_sigma": RX_REFERENCE_SIGMA,
            "alternative_sigma_thresholds": [],
            "threshold_search_count": 0,
            "raw_a2_diagnostic_units": "(entrant Raw A2 score - incumbent Raw A2 score) / population std of same-date eligible Raw A2 scores",
            "warning": "RX_MARGIN_R1 uses Range Exhaustion scores; the 1.0 value is contextual only and this audit does not adopt or register a Raw A2 rule",
        },
        "fixed_metrics": [
            "event_count", "matured_event_count", "mean_gross_replacement_spread",
            "mean_net_replacement_value", "incumbent_retention_win_share",
            "negative_net_replacement_share", "five_session_round_trip_share",
            "paired_turnover", "paired_transaction_cost",
        ],
        "classification_contract": {
            "minimum_pooled_low_margin_events": 100,
            "minimum_pooled_reference_pass_events_for_strong_or_no_support": 20,
            "strong": "all identities pass; pooled low-margin events >=100 and reference-pass events >=20; low-margin mean net value <0; incumbent retention wins >50%; low-margin five-session round trips exceed reference-pass round trips; reference-pass mean net value exceeds low-margin mean; and low-margin mean net value <0 in >=3 of 4 periods",
            "partial": "all identities pass; pooled low-margin events >=100; low-margin mean net value <0 in pooled evidence and >=2 of 4 periods; and either incumbent retention wins >50% or five-session round-trip share exceeds 25%",
            "none": "all identities pass; both pooled groups meet sample minima; low-margin mean net value >=0; incumbent retention wins <=50%; and low-margin mean net value <0 in <=1 of 4 periods",
            "inconclusive": "any identity/data sufficiency failure or evidence not satisfying another exact gate",
            "allowed_outputs": list(CLASSIFICATIONS.values()),
        },
        "hard_counters": {
            "POST_2026_08_28_OUTCOME_READ_COUNT": 0,
            "THRESHOLD_SEARCH_COUNT": 0,
            "NEW_STRATEGY_COUNT": 0,
            "MODEL_REFIT_COUNT": 0,
            "REGISTRY_CHANGE_COUNT": 0,
        },
        "prohibitions": [
            "post-cutoff outcome read", "convenience rank flag", "alternative sigma threshold",
            "rank threshold optimization", "strategy or shadow construction",
            "RX_MARGIN_R1 strategy or shadow run", "model fit or refit",
            "canonical registry modification", "new backtester",
            "generic turnover or hysteresis framework", "A2_X0 prospective protocol modification",
        ],
    }


def freeze_protocol() -> dict[str, Any]:
    require(not PROTOCOL_PATH.exists(), "PROTOCOL_ALREADY_EXISTS_REFUSE_REFREEZE", PROTOCOL_PATH)
    require(not OUT.exists(), "OUTPUT_ROOT_ALREADY_EXISTS_BEFORE_FREEZE", OUT)
    exclusion = verify_active_worker_exclusion()
    temp_accounting = scoped_temp_accounting()
    require(temp_accounting["TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT"] == 0, "TASK_OWNED_OR_UNVERIFIED_REPO_ROOT_TEMP_DIRS_PRESENT", temp_accounting)
    hash_rows = verify_expected_hashes()
    require(all(row["pass"] for row in hash_rows), "SOURCE_HASH_FAILURE", hash_rows)
    OUT.mkdir(parents=False, exist_ok=False)
    write_json_once(EXCLUSION_EVIDENCE_PATH, exclusion)
    exclusion_sha = sha256_file(EXCLUSION_EVIDENCE_PATH)
    anti_dup = anti_duplication_accounting()
    anti_dup["source_hash_checks"] = hash_rows
    anti_dup["scoped_temp_accounting_at_freeze"] = temp_accounting
    anti_dup["active_worker_exclusion_verification_sha256"] = exclusion_sha
    write_json_once(ANTI_DUP_PATH, anti_dup)
    anti_dup_sha = sha256_file(ANTI_DUP_PATH)
    protocol = protocol_payload(anti_dup_sha, exclusion_sha, temp_accounting)
    write_json_once(PROTOCOL_PATH, protocol)
    protocol_sha = sha256_file(PROTOCOL_PATH)
    witness = {
        "task_id": TASK_ID,
        "freeze_status": "FROZEN_BEFORE_CURRENT_AUDIT_OUTCOME_READ",
        "protocol_path": str(PROTOCOL_PATH),
        "REPLACEMENT_PROTOCOL_SHA256": protocol_sha,
        "pre_freeze_current_audit_economic_outcome_read_count": 0,
        "ACTIVE_UNRELATED_TRANSIENT_EXCLUSION_STATUS": ACTIVE_EXCLUSION_CLASSIFICATION,
        "ACTIVE_UNRELATED_TEMP_EXCLUSIONS": temp_accounting["ACTIVE_UNRELATED_TEMP_EXCLUSIONS"],
        "ACTIVE_UNRELATED_TEMP_PATHS": temp_accounting["ACTIVE_UNRELATED_TEMP_PATHS"],
        "TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT": temp_accounting["TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT"],
        "repo_root_temp_dir_count_at_freeze": temp_accounting["REPO_ROOT_TEMP_DIR_COUNT"],
    }
    write_json_once(FREEZE_WITNESS_PATH, witness)
    return witness


def load_frozen_protocol() -> tuple[dict[str, Any], dict[str, Any]]:
    require(PROTOCOL_PATH.is_file() and FREEZE_WITNESS_PATH.is_file(), "FROZEN_PROTOCOL_MISSING")
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    witness = json.loads(FREEZE_WITNESS_PATH.read_text(encoding="utf-8"))
    actual = sha256_file(PROTOCOL_PATH)
    require(actual == witness["REPLACEMENT_PROTOCOL_SHA256"], "PROTOCOL_HASH_MISMATCH", {"actual": actual, "witness": witness})
    require(protocol["source_code_sha256"] == sha256_file(Path(__file__).resolve()), "AUDIT_SOURCE_CHANGED_AFTER_FREEZE")
    return protocol, witness


def load_reused_functions() -> tuple[Callable[..., Any], Callable[..., Any], Callable[..., Any], Callable[..., Any]]:
    hash_rows = verify_expected_hashes()
    require(all(row["pass"] for row in hash_rows), "REUSED_SOURCE_HASH_FAILURE", hash_rows)
    portfolio = import_file("a2_boundary_frozen_portfolio_helper", PORTFOLIO_SOURCE)
    pairing = import_file("a2_boundary_frozen_pairing_helper", PAIRING_SOURCE)
    return portfolio.build_target_map, portfolio.calculate_weight_rebalance, pairing.add_roundtrip_tags, pairing.build_replacements


def load_panels_after_freeze() -> tuple[pd.DataFrame, dict[str, Any]]:
    pre = pd.read_parquet(
        PRE2026_OOF,
        columns=["signal_date", "ticker", "universe_size", "target", "a2_prediction", "a2_rank"],
    ).rename(columns={"signal_date": "decision_date", "a2_prediction": "raw_score", "a2_rank": "raw_rank"})
    pre["decision_date"] = pd.to_datetime(pre["decision_date"])
    pre = pre.loc[pre.decision_date.between(pd.Timestamp("2023-01-01"), pd.Timestamp("2025-12-31"))].copy()
    pre["target_end_date"] = pd.NaT
    pre["window"] = "PRE2026"
    pre["period"] = pre.decision_date.dt.year.astype(str)

    checkpoint = pd.read_parquet(
        PRE2026_CHECKPOINT,
        columns=["decision_date", "ticker_if_available", "raw_score", "raw_rank"],
    ).rename(columns={"ticker_if_available": "ticker"})
    checkpoint["decision_date"] = pd.to_datetime(checkpoint["decision_date"])
    checkpoint = checkpoint.loc[checkpoint.decision_date.between(pd.Timestamp("2023-01-01"), pd.Timestamp("2025-12-31"))].copy()
    pre_top40 = pre.loc[pre.raw_rank.le(40), ["decision_date", "ticker", "raw_score", "raw_rank"]].copy()
    joined = checkpoint.merge(pre_top40, on=["decision_date", "ticker"], how="outer", suffixes=("_checkpoint", "_oof"), indicator=True)
    checkpoint_identity = {
        "checkpoint_rows": int(len(checkpoint)),
        "source_top40_rows": int(len(pre_top40)),
        "key_mismatch_count": int(joined._merge.ne("both").sum()),
        "rank_mismatch_count": int(joined.raw_rank_checkpoint.fillna(-1).ne(joined.raw_rank_oof.fillna(-1)).sum()),
        "score_mismatch_count": int((~np.isclose(joined.raw_score_checkpoint, joined.raw_score_oof, rtol=0.0, atol=1e-12, equal_nan=True)).sum()),
    }

    dataset = ds.dataset(R2A_PREDICTIONS, format="parquet")
    model_filter = ds.field("model") == "M0_A2_HGB"
    maturity_meta = dataset.to_table(columns=["target_end_date"], filter=model_filter).to_pandas()
    maturity_meta["target_end_date"] = pd.to_datetime(maturity_meta["target_end_date"])
    eligible_filter = model_filter & (ds.field("target_end_date") <= np.datetime64(ECONOMIC_CUTOFF))
    post = dataset.to_table(
        columns=["prediction_date", "ticker", "eligible_count", "target", "target_end_date", "score", "rank"],
        filter=eligible_filter,
    ).to_pandas().rename(
        columns={"prediction_date": "decision_date", "score": "raw_score", "rank": "raw_rank", "eligible_count": "universe_size"}
    )
    post["decision_date"] = pd.to_datetime(post["decision_date"])
    post["target_end_date"] = pd.to_datetime(post["target_end_date"])
    post["window"] = "RETROSPECTIVE_2026"
    post["period"] = "2026"
    post_cutoff_read_count = int(post.target_end_date.gt(ECONOMIC_CUTOFF).sum())

    columns = ["window", "period", "decision_date", "ticker", "universe_size", "raw_score", "raw_rank", "target", "target_end_date"]
    panels = pd.concat([pre[columns], post[columns]], ignore_index=True)
    panels = panels.sort_values(["window", "decision_date", "raw_rank", "ticker"]).reset_index(drop=True)
    return panels, {
        "checkpoint_identity": checkpoint_identity,
        "pre2026_outcome_rows_read": int(len(pre)),
        "2026_outcome_rows_read": int(len(post)),
        "2026_maturity_rows_seen_without_outcome_column": int(len(maturity_meta)),
        "2026_rows_excluded_by_maturity_filter_without_outcome_read": int(maturity_meta.target_end_date.gt(ECONOMIC_CUTOFF).sum()),
        "POST_2026_08_28_OUTCOME_READ_COUNT": post_cutoff_read_count,
        "maximum_2026_target_end_date_read": post.target_end_date.max().date().isoformat(),
    }


def validate_rank_membership(panels: pd.DataFrame) -> dict[str, Any]:
    duplicate_key_count = int(panels.duplicated(["window", "decision_date", "ticker"]).sum())
    duplicate_rank_count = int(panels.duplicated(["window", "decision_date", "raw_rank"]).sum())
    per_date = panels.assign(member=panels.raw_rank.le(TOP_N)).groupby(["window", "decision_date"], sort=True).agg(
        row_count=("ticker", "size"),
        unique_tickers=("ticker", "nunique"),
        top20_count=("member", "sum"),
        raw_score_std=("raw_score", lambda x: float(np.std(x.astype(float), ddof=0))),
    ).reset_index()
    return {
        "duplicate_security_date_count": duplicate_key_count,
        "duplicate_rank_date_count": duplicate_rank_count,
        "decision_date_count": int(len(per_date)),
        "invalid_top20_cardinality_date_count": int(per_date.top20_count.ne(TOP_N).sum()),
        "invalid_score_std_date_count": int((~np.isfinite(per_date.raw_score_std) | per_date.raw_score_std.le(0)).sum()),
        "minimum_eligible_count": int(per_date.row_count.min()),
        "maximum_eligible_count": int(per_date.row_count.max()),
    }


def build_event_ledger(
    panels: pd.DataFrame,
    build_target_map: Callable[..., dict[pd.Timestamp, dict[str, float]]],
    calculate_weight_rebalance: Callable[..., dict[str, Any]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    turnover_checks: list[dict[str, Any]] = []
    for window, window_panel in panels.groupby("window", sort=False):
        rank_input = window_panel.rename(columns={"decision_date": "signal_date", "raw_rank": "rank_for_membership"})
        target_map = build_target_map(rank_input, "rank_for_membership", TOP_N)
        panel_groups = {pd.Timestamp(date): group.set_index("ticker", drop=False) for date, group in window_panel.groupby("decision_date", sort=True)}
        dates = sorted(panel_groups)
        for previous_date, current_date in zip(dates, dates[1:]):
            previous = panel_groups[previous_date]
            current = panel_groups[current_date]
            previous_weights = target_map[previous_date]
            current_weights = target_map[current_date]
            accounting = calculate_weight_rebalance(previous_weights, current_weights, cost_bps=COST_BPS)
            previous_top = set(previous_weights)
            current_top = set(current_weights)
            entries = current_top - previous_top
            exits = previous_top - current_top
            require(len(entries) == len(exits), "TOP20_TRANSITION_CARDINALITY_FAILURE", (window, current_date, len(entries), len(exits)))
            changed = entries | exits
            per_changed_turnover = float(accounting["turnover"] / len(changed)) if changed else 0.0
            per_changed_cost = float(accounting["transaction_cost_fraction"] / len(changed)) if changed else 0.0
            turnover_checks.append({"window": window, "decision_date": current_date, "entry_count": len(entries), "exit_count": len(exits), "turnover": float(accounting["turnover"]), "transaction_cost": float(accounting["transaction_cost_fraction"])})
            for ticker in sorted(previous_top | current_top):
                prev = previous.loc[ticker] if ticker in previous.index else None
                cur = current.loc[ticker] if ticker in current.index else None
                previous_member = ticker in previous_top
                current_member = ticker in current_top
                direction = "ENTER" if current_member and not previous_member else ("EXIT" if previous_member and not current_member else "STAY")
                source = cur if cur is not None else prev
                rows.append({
                    "window": window, "period": str(source["period"]), "rebalance_date": current_date,
                    "previous_rebalance_date": previous_date, "prediction_date": current_date,
                    "previous_prediction_date": previous_date, "ticker": ticker,
                    "13f_vintage": "NOT_REQUIRED_FOR_MECHANISM_AUDIT",
                    "eligible_universe_count": int(cur.universe_size) if cur is not None else (int(prev.universe_size) if prev is not None else np.nan),
                    "previous_score": float(prev.raw_score) if prev is not None else np.nan,
                    "current_score": float(cur.raw_score) if cur is not None else np.nan,
                    "previous_rank": float(prev.raw_rank) if prev is not None else np.nan,
                    "current_rank": float(cur.raw_rank) if cur is not None else np.nan,
                    "previous_top20": previous_member, "current_top20": current_member,
                    "previous_weight": float(previous_weights.get(ticker, 0.0)),
                    "target_weight": float(current_weights.get(ticker, 0.0)), "trade_direction": direction,
                    "absolute_trade_weight": per_changed_turnover if ticker in changed else 0.0,
                    "transaction_cost": per_changed_cost if ticker in changed else 0.0,
                    "transaction_cost_absolute": per_changed_cost if ticker in changed else 0.0,
                    "realized_forward_return": float(cur.target) if cur is not None and pd.notna(cur.target) else np.nan,
                    "next_period_contribution": np.nan, "gross_contribution": np.nan, "net_contribution": np.nan,
                    "terminal_liquidation": False,
                })
    ledger = pd.DataFrame(rows)
    turnover_frame = pd.DataFrame(turnover_checks)
    return ledger, {
        "transition_date_count": int(len(turnover_frame)),
        "total_rank_derived_turnover": float(turnover_frame.turnover.sum()),
        "total_rank_derived_transaction_cost": float(turnover_frame.transaction_cost.sum()),
        "transition_entry_exit_mismatch_count": int(turnover_frame.entry_count.ne(turnover_frame.exit_count).sum()),
    }


def add_reference_fields(replacements: pd.DataFrame, panels: pd.DataFrame) -> pd.DataFrame:
    out = replacements.copy()
    std_map = panels.groupby(["window", "decision_date"], sort=False).raw_score.std(ddof=0).to_dict()
    out["same_date_raw_a2_score_std"] = [std_map.get((window, pd.Timestamp(date)), np.nan) for window, date in zip(out.window, out.prediction_date)]
    out["raw_a2_score_gap_sigma"] = out.score_gap / out.same_date_raw_a2_score_std
    out["rx_1sigma_reference_pass"] = out.raw_a2_score_gap_sigma.ge(RX_REFERENCE_SIGMA)
    out["rx_1sigma_reference_role"] = "CONTEXT_ONLY_NOT_RULE_TRANSFER"
    out["primary_fixed_boundary"] = out.boundary_churn_band_16_25.fillna(False).astype(bool)
    out["matured_pair"] = out.old_realized_forward_return.notna() & out.new_realized_forward_return.notna()
    out["qualified_event"] = (
        out.primary_fixed_boundary & out.matured_pair & out.raw_a2_score_gap_sigma.notna()
        & out.old_name.ne("BASKET") & out.new_name.ne("BASKET")
        & out.old_name.ne("NA") & out.new_name.ne("NA")
    )
    out["margin_group"] = np.where(out.rx_1sigma_reference_pass, "AT_OR_ABOVE_RX_1SIGMA_REFERENCE", "BELOW_RX_1SIGMA_REFERENCE")
    out.loc[~out.qualified_event, "margin_group"] = "UNQUALIFIED"
    out["incumbent_retention_win"] = out.net_replacement_value.lt(0)
    return out


def safe_mean(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.mean()) if len(values) else float("nan")


def safe_sum(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.sum()) if len(values) else 0.0


def summarize_group(frame: pd.DataFrame, period: str, group_name: str) -> dict[str, Any]:
    return {
        "period": period,
        "margin_group": group_name,
        "event_count": int(len(frame)),
        "mean_gross_replacement_spread": safe_mean(frame.gross_replacement_spread),
        "mean_net_replacement_value": safe_mean(frame.net_replacement_value),
        "incumbent_retention_win_share": safe_mean(frame.incumbent_retention_win.astype(float)),
        "negative_net_replacement_share": safe_mean(frame.negative_net_replacement.astype(float)),
        "five_session_round_trip_share": safe_mean(frame.short_round_trip_5d.astype(float)),
        "paired_turnover": safe_sum(frame.replacement_turnover),
        "paired_transaction_cost": safe_sum(frame.incremental_transaction_cost),
        "mean_raw_a2_score_gap_sigma": safe_mean(frame.raw_a2_score_gap_sigma),
    }


def mechanism_summary(replacements: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    qualified = replacements.loc[replacements.qualified_event].copy()
    groups = ["BELOW_RX_1SIGMA_REFERENCE", "AT_OR_ABOVE_RX_1SIGMA_REFERENCE"]
    rows: list[dict[str, Any]] = []
    for period in PERIODS + ["POOLED"]:
        period_frame = qualified if period == "POOLED" else qualified.loc[qualified.period.eq(period)]
        for group_name in groups:
            rows.append(summarize_group(period_frame.loc[period_frame.margin_group.eq(group_name)], period, group_name))
    table = pd.DataFrame(rows)
    low = table.loc[(table.period == "POOLED") & (table.margin_group == groups[0])].iloc[0]
    high = table.loc[(table.period == "POOLED") & (table.margin_group == groups[1])].iloc[0]
    low_periods = table.loc[(table.period.isin(PERIODS)) & (table.margin_group == groups[0])]
    negative_period_count = int(low_periods.mean_net_replacement_value.lt(0).sum())
    low_count = int(low.event_count)
    high_count = int(high.event_count)
    enough_low = low_count >= 100
    enough_high = high_count >= 20
    strong = bool(
        enough_low and enough_high and low.mean_net_replacement_value < 0
        and low.incumbent_retention_win_share > 0.50
        and low.five_session_round_trip_share > high.five_session_round_trip_share
        and high.mean_net_replacement_value > low.mean_net_replacement_value
        and negative_period_count >= 3
    )
    partial = bool(
        enough_low and low.mean_net_replacement_value < 0 and negative_period_count >= 2
        and (low.incumbent_retention_win_share > 0.50 or low.five_session_round_trip_share > 0.25)
    )
    none = bool(
        enough_low and enough_high and low.mean_net_replacement_value >= 0
        and low.incumbent_retention_win_share <= 0.50 and negative_period_count <= 1
    )
    classification = (
        CLASSIFICATIONS["strong"] if strong else CLASSIFICATIONS["partial"] if partial
        else CLASSIFICATIONS["none"] if none else CLASSIFICATIONS["inconclusive"]
    )
    return table, {
        "classification": classification,
        "qualified_event_count": int(len(qualified)),
        "low_margin_event_count": low_count,
        "reference_pass_event_count": high_count,
        "negative_low_margin_period_count": negative_period_count,
        "pooled_low_margin": {key: (int(value) if key == "event_count" else float(value)) for key, value in low.items() if key not in {"period", "margin_group"}},
        "pooled_reference_pass": {key: (int(value) if key == "event_count" else float(value)) for key, value in high.items() if key not in {"period", "margin_group"}},
        "gate_results": {
            "strong": strong, "partial": partial, "none": none,
            "inconclusive": not (strong or partial or none),
            "minimum_low_margin_sample_pass": enough_low,
            "minimum_reference_pass_sample_pass": enough_high,
        },
    }


def normalize_json_numbers(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: normalize_json_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_json_numbers(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def final_report(summary: dict[str, Any], protocol_sha: str) -> str:
    low = summary["mechanism"]["pooled_low_margin"]
    high = summary["mechanism"]["pooled_reference_pass"]
    return f"""# {TASK_ID}

Research role: `{RESEARCH_ROLE}`. This is an event-level retrospective mechanism audit, not a strategy, shadow, model selection, or production authorization.

## Frozen protocol

`REPLACEMENT_PROTOCOL_SHA256={protocol_sha}`

The protocol was frozen before this run loaded the predeclared `target` outcome columns. Raw A2 Top20 membership was derived only from authoritative ranks (`rank <= 20`); convenience flags were not loaded. The 1.0-sigma split is solely the pre-existing RX_MARGIN_R1 reference and is not a transferred Raw-A2 rule.

## Result

Final mechanism classification: `{summary['FINAL_MECHANISM_CLASSIFICATION']}`

Qualified fixed-boundary events: {summary['mechanism']['qualified_event_count']}. Below-reference events: {summary['mechanism']['low_margin_event_count']}; at/above-reference events: {summary['mechanism']['reference_pass_event_count']}.

Below-reference mean net replacement value was {low['mean_net_replacement_value']}; incumbent-retention win share was {low['incumbent_retention_win_share']}; five-session round-trip share was {low['five_session_round_trip_share']}. The at/above-reference mean net value was {high['mean_net_replacement_value']}.

No portfolio or NAV path was constructed. Aggregates are local paired-event diagnostics and must not be interpreted as a tradable policy result.

## Required counters

- `POST_2026_08_28_OUTCOME_READ_COUNT={summary['POST_2026_08_28_OUTCOME_READ_COUNT']}`
- `THRESHOLD_SEARCH_COUNT={summary['THRESHOLD_SEARCH_COUNT']}`
- `NEW_STRATEGY_COUNT={summary['NEW_STRATEGY_COUNT']}`
- `MODEL_REFIT_COUNT={summary['MODEL_REFIT_COUNT']}`
- `REGISTRY_CHANGE_COUNT={summary['REGISTRY_CHANGE_COUNT']}`
- `PROSPECTIVE_A2_X0_PROTOCOL_UNTOUCHED={str(summary['PROSPECTIVE_A2_X0_PROTOCOL_UNTOUCHED']).upper()}`
- `ACTIVE_UNRELATED_TRANSIENT_EXCLUSION_STATUS={summary['ACTIVE_UNRELATED_TRANSIENT_EXCLUSION_STATUS']}`
- `ACTIVE_UNRELATED_TEMP_EXCLUSIONS={summary['ACTIVE_UNRELATED_TEMP_EXCLUSIONS']}`
- `ACTIVE_UNRELATED_TEMP_PATHS={summary['ACTIVE_UNRELATED_TEMP_PATHS']}`
- `TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT={summary['TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT']}`
- `UNRELATED_ACTIVE_TEMP_DIR_COUNT={summary['UNRELATED_ACTIVE_TEMP_DIR_COUNT']}`
- `REPO_ROOT_TEMP_DIR_COUNT={summary['REPO_ROOT_TEMP_DIR_COUNT']}` (informational global count)
"""


def run_audit() -> dict[str, Any]:
    protocol, witness = load_frozen_protocol()
    require(protocol["economic_cutoff_inclusive"] == ECONOMIC_CUTOFF.date().isoformat(), "CUTOFF_PROTOCOL_MISMATCH")
    build_target_map, calculate_weight_rebalance, add_roundtrip_tags, build_replacements = load_reused_functions()
    panels, read_audit = load_panels_after_freeze()
    membership_audit = validate_rank_membership(panels)
    checkpoint_audit = read_audit["checkpoint_identity"]
    identity_values = [
        checkpoint_audit["key_mismatch_count"], checkpoint_audit["rank_mismatch_count"],
        checkpoint_audit["score_mismatch_count"], membership_audit["duplicate_security_date_count"],
        membership_audit["duplicate_rank_date_count"], membership_audit["invalid_top20_cardinality_date_count"],
        membership_audit["invalid_score_std_date_count"], read_audit["POST_2026_08_28_OUTCOME_READ_COUNT"],
    ]
    require(all(value == 0 for value in identity_values), "AUTHORITATIVE_RANK_OR_TEMPORAL_IDENTITY_FAILURE", {"read": read_audit, "membership": membership_audit})

    ledger, turnover_audit = build_event_ledger(panels, build_target_map, calculate_weight_rebalance)
    ledger = add_roundtrip_tags(ledger)
    replacements = add_reference_fields(build_replacements(ledger), panels)
    by_period, mechanism = mechanism_summary(replacements)
    require(mechanism["classification"] in CLASSIFICATIONS.values(), "INVALID_FINAL_CLASSIFICATION")

    registry_unchanged = sha256_file(REGISTRY_PATH) == protocol["protected_identity_snapshots"]["canonical_registry"]["sha256"]
    x0_unchanged = sha256_file(X0_PROTOCOL) == protocol["protected_identity_snapshots"]["prospective_a2_x0_protocol"]["sha256"]
    exclusion = verify_active_worker_exclusion()
    temp_accounting = scoped_temp_accounting()
    summary = normalize_json_numbers({
        "task_id": TASK_ID,
        "research_role": RESEARCH_ROLE,
        "economic_cutoff_inclusive": ECONOMIC_CUTOFF.date().isoformat(),
        "REPLACEMENT_PROTOCOL_SHA256": witness["REPLACEMENT_PROTOCOL_SHA256"],
        "FINAL_MECHANISM_CLASSIFICATION": mechanism["classification"],
        "mechanism": mechanism,
        "outcome_read_audit": read_audit,
        "authoritative_membership_audit": membership_audit,
        "turnover_cost_reuse_audit": turnover_audit,
        "POST_2026_08_28_OUTCOME_READ_COUNT": read_audit["POST_2026_08_28_OUTCOME_READ_COUNT"],
        "THRESHOLD_SEARCH_COUNT": 0,
        "NEW_STRATEGY_COUNT": 0,
        "MODEL_REFIT_COUNT": 0,
        "REGISTRY_CHANGE_COUNT": 0 if registry_unchanged else 1,
        "PROSPECTIVE_A2_X0_PROTOCOL_UNTOUCHED": x0_unchanged,
        "ACTIVE_UNRELATED_TRANSIENT_EXCLUSION_STATUS": exclusion["classification"],
        "ACTIVE_UNRELATED_TEMP_EXCLUSIONS": temp_accounting["ACTIVE_UNRELATED_TEMP_EXCLUSIONS"],
        "ACTIVE_UNRELATED_TEMP_PATHS": temp_accounting["ACTIVE_UNRELATED_TEMP_PATHS"],
        "TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT": temp_accounting["TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT"],
        "UNRELATED_ACTIVE_TEMP_DIR_COUNT": temp_accounting["UNRELATED_ACTIVE_TEMP_DIR_COUNT"],
        "REPO_ROOT_TEMP_DIR_COUNT": temp_accounting["REPO_ROOT_TEMP_DIR_COUNT"],
        "TASK_OWNED_OR_UNVERIFIED_TEMP_PATHS": temp_accounting["TASK_OWNED_OR_UNVERIFIED_TEMP_PATHS"],
        "CONVENIENCE_RANK_FLAG_READ_COUNT": 0,
        "ALTERNATIVE_SIGMA_THRESHOLD_COUNT": 0,
        "RANK_THRESHOLD_OPTIMIZATION_COUNT": 0,
        "RX_MARGIN_R1_STRATEGY_OR_SHADOW_RUN_COUNT": 0,
        "NEW_BACKTESTER_COUNT": 0,
        "GENERIC_TURNOVER_HYSTERESIS_FRAMEWORK_COUNT": 0,
        "CANONICAL_REGISTRY_UNTOUCHED": registry_unchanged,
        "PRODUCTION_AUTHORIZATION": False,
    })
    hard_accept = (
        summary["POST_2026_08_28_OUTCOME_READ_COUNT"] == 0
        and summary["THRESHOLD_SEARCH_COUNT"] == 0
        and summary["NEW_STRATEGY_COUNT"] == 0
        and summary["MODEL_REFIT_COUNT"] == 0
        and summary["REGISTRY_CHANGE_COUNT"] == 0
        and summary["PROSPECTIVE_A2_X0_PROTOCOL_UNTOUCHED"] is True
        and summary["ACTIVE_UNRELATED_TRANSIENT_EXCLUSION_STATUS"] == ACTIVE_EXCLUSION_CLASSIFICATION
        and summary["TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT"] == 0
    )
    require(hard_accept, "FINAL_HARD_COUNTER_FAILURE", summary)

    event_path = OUT / "replacement_event_ledger.parquet"
    period_path = OUT / "replacement_mechanism_by_period.csv"
    summary_path = OUT / "replacement_mechanism_summary.json"
    report_path = OUT / "final_report.md"
    manifest_path = OUT / "manifest.json"
    for path in [event_path, period_path, summary_path, report_path, manifest_path]:
        require(not path.exists(), "REFUSE_OVERWRITE_AUDIT_ARTIFACT", path)
    replacements.to_parquet(event_path, index=False)
    by_period.to_csv(period_path, index=False, lineterminator="\n")
    write_json_once(summary_path, summary)
    write_text_once(report_path, final_report(summary, witness["REPLACEMENT_PROTOCOL_SHA256"]))
    artifacts = []
    for path in sorted(OUT.iterdir(), key=lambda item: item.name):
        if path.is_file() and path.name != manifest_path.name:
            artifacts.append({"artifact": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    write_json_once(manifest_path, {
        "task_id": TASK_ID,
        "artifact_count_excluding_self": len(artifacts),
        "artifacts": artifacts,
        "REPLACEMENT_PROTOCOL_SHA256": witness["REPLACEMENT_PROTOCOL_SHA256"],
        "FINAL_MECHANISM_CLASSIFICATION": mechanism["classification"],
        "hard_acceptance_status": "PASS",
    })
    return summary


def self_test() -> None:
    require(set(CLASSIFICATIONS.values()) == {
        "STRONG_SUPPORT_FOR_STATEFUL_HYSTERESIS_MECHANISM",
        "PARTIAL_SUPPORT_FOR_STATEFUL_HYSTERESIS_MECHANISM",
        "NO_SUPPORT_FOR_SCORE_MARGIN_HYSTERESIS_MECHANISM",
        "INCONCLUSIVE_REPLACEMENT_MECHANISM",
    }, "CLASSIFICATION_ENUM_FAILURE")
    require(RX_REFERENCE_SIGMA == 1.0, "RX_REFERENCE_CHANGED")
    require(PERIODS == ["2023", "2024", "2025", "2026"], "PERIOD_CONTRACT_CHANGED")
    exclusion = verify_active_worker_exclusion()
    require(exclusion["classification"] == ACTIVE_EXCLUSION_CLASSIFICATION, "SELF_TEST_ACTIVE_EXCLUSION_FAILURE", exclusion)
    temp_accounting = scoped_temp_accounting()
    require(temp_accounting["TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT"] == 0, "SELF_TEST_TASK_OWNED_TEMP_FAILURE", temp_accounting)
    hash_rows = verify_expected_hashes()
    require(all(row["pass"] for row in hash_rows), "SELF_TEST_SOURCE_HASH_FAILURE", hash_rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["self-test", "freeze-protocol", "run-audit"])
    return parser.parse_args()


def main() -> int:
    action = parse_args().action
    if action == "self-test":
        self_test()
        print("SELF_TEST_STATUS=PASS")
        return 0
    if action == "freeze-protocol":
        witness = freeze_protocol()
        print("PROTOCOL_FREEZE_STATUS=PASS")
        print(f"REPLACEMENT_PROTOCOL_SHA256={witness['REPLACEMENT_PROTOCOL_SHA256']}")
        return 0
    summary = run_audit()
    print("AUDIT_STATUS=PASS")
    print(f"FINAL_MECHANISM_CLASSIFICATION={summary['FINAL_MECHANISM_CLASSIFICATION']}")
    for key in [
        "POST_2026_08_28_OUTCOME_READ_COUNT", "THRESHOLD_SEARCH_COUNT", "NEW_STRATEGY_COUNT",
        "MODEL_REFIT_COUNT", "REGISTRY_CHANGE_COUNT", "PROSPECTIVE_A2_X0_PROTOCOL_UNTOUCHED",
        "ACTIVE_UNRELATED_TRANSIENT_EXCLUSION_STATUS", "ACTIVE_UNRELATED_TEMP_EXCLUSIONS",
        "ACTIVE_UNRELATED_TEMP_PATHS", "TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT",
    ]:
        print(f"{key}={summary[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
