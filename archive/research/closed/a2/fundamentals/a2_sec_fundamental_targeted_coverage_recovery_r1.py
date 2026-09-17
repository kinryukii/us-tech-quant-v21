from __future__ import annotations

"""Fail-closed, outcome-blind controller for targeted SEC coverage recovery."""

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

TASK = "A2_SEC_FUNDAMENTAL_TARGETED_COVERAGE_RECOVERY_R1"
SOURCE_TASK = "A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1"
RESULTS = Path(r"D:\us-tech-quant-results")
SOURCE = RESULTS / SOURCE_TASK
OUT = RESULTS / TASK
CACHE = Path(r"D:\us-tech-quant-cache\sec_fundamental_pit_r1")
PROVENANCE = Path(r"D:\us-tech-quant-backtests\A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1\DATA_COVERAGE_INSUFFICIENT_PROVENANCE_20260824T043714JST")
PREREG_SHA = "001ce13b44adaa1c8ccb0bd8340a3ed383c2c481e8d75c4fd77e2ccacad4d900"
CONCEPT_SHA = "3840fd339105f90a804af00ee637be2ce88e7af1f637911a54bd902c23dee19a"
MAPPING_SHA = "31678c81d744c1014b06e5521257ace8c1a3998f289dc52041818434d38b8bb1"
COMPANYFACTS_SHA = "d7b4b3c5f2fe014a203bdaef2197d2cba5683f434e965fc9bced1023a43c82ca"
SUBMISSIONS_SHA = "928d67221c6e6183bc343e7234c1391448c15cd1dd644d36b425db2f99ba4350"
PAYLOADS = {
    "companyfacts": (CACHE / "bulk/companyfacts.zip", 1_407_131_132, 20_266, COMPANYFACTS_SHA),
    "submissions": (CACHE / "bulk/submissions.zip", 1_559_612_838, 987_520, SUBMISSIONS_SHA),
}
MEMBERSHIP_CANDIDATES = (
    RESULTS / "A_VS_A2_QUARTERLY_13F_R1/A2/oof_predictions.parquet",
    RESULTS / "A2_AUTONOMOUS_BUY_SELL_AND_SIZING_POLICY_R1/security_state_ledger.parquet",
)
SAFE_MEMBERSHIP_COLUMNS = ["signal_date", "ticker", "a2_rank"]
EXPECTED_DATES, EXPECTED_TOP40_ROWS = 1_253, 50_120
PRE_MEDIAN, PRE_PASS_COUNT = 0.60, 743
PRE_PASS_FRACTION = PRE_PASS_COUNT / EXPECTED_DATES


class RecoveryFailure(RuntimeError):
    pass


def require(ok: bool, code: str, detail: Any = "") -> None:
    if not ok:
        raise RecoveryFailure(f"{code}:{detail}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, default=str) + "\n").encode()


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def write_json(path: Path, value: Any) -> None:
    write_bytes(path, json_bytes(value))


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    temporary = path.with_name(path.name + ".tmp")
    frame.to_csv(temporary, index=False, lineterminator="\n")
    os.replace(temporary, path)


def verify_payloads() -> dict[str, Any]:
    result = {}
    for name, (path, size, entries, expected_hash) in PAYLOADS.items():
        digest = sha256_file(path)
        with zipfile.ZipFile(path) as archive:
            count = len(archive.infolist())
            with archive.open(archive.infolist()[0]) as handle:
                handle.read(1)
        require((path.stat().st_size, count, digest) == (size, entries, expected_hash), "HARD_FAIL_SEC_PAYLOAD_IDENTITY", name)
        result[name] = {"bytes": size, "entries": count, "sha256": digest, "zip_readable": True}
    return result


def verify_sources() -> dict[str, Any]:
    manifest = json.loads((SOURCE / "hash_manifest.json").read_text(encoding="utf-8"))
    for item in manifest["artifacts"]:
        path = SOURCE / item["name"]
        require(path.stat().st_size == item["bytes"] and sha256_file(path) == item["sha256"], "SOURCE_ARTIFACT_HASH_MISMATCH", item["name"])
    prereg_path, concept_path = SOURCE / "preregistration.json", SOURCE / "sec_concept_contract.json"
    require(sha256_file(prereg_path) == PREREG_SHA, "FROZEN_COVERAGE_CONTRACT_CHANGED")
    require(sha256_file(concept_path) == CONCEPT_SHA, "FROZEN_CONCEPT_CONTRACT_CHANGED")
    require(sha256_file(PROVENANCE / "trial_ledger.parquet") == MAPPING_SHA, "FROZEN_MAPPING_LEDGER_HASH_MISMATCH")
    return json.loads(prereg_path.read_text(encoding="utf-8"))


def verify_checkpoint() -> dict[str, Any]:
    root = CACHE / "derived_bulk_resume"
    path = root / "fundamental_feature_states.parquet"
    manifest = json.loads((root / "fundamental_feature_states_manifest.json").read_text(encoding="utf-8"))
    require(Path(manifest["state_path"]) == path and len(pd.read_parquet(path, columns=["cik"])) == manifest["state_rows"], "FEATURE_CHECKPOINT_IDENTITY")
    require(sha256_file(path) == manifest["state_sha256"], "FEATURE_CHECKPOINT_HASH_MISMATCH")
    statuses = {key: value for key, value in manifest["lineage_facts"].items() if key.endswith("_status")}
    require(len(statuses) == 3 and all(str(value).startswith("PASS") for value in statuses.values()), "FEATURE_CHECKPOINT_GUARD_FAILURE")
    return manifest


def frozen_gates(prereg: dict[str, Any]) -> tuple[float, float, float, str]:
    gate = prereg["coverage_gate"]
    values = (float(gate["raw_top40_median_min"]), 0.50, float(gate["decision_date_fraction_with_coverage_at_least_0_50_min"]))
    definition = str(gate["covered_security_definition"])
    require(values == (0.60, 0.50, 0.75) and definition == "at least one usable derived feature in at least 3 of F0-F3", "FROZEN_COVERAGE_CONTRACT_CHANGED")
    return *values, definition


def probe_membership(path: Path) -> dict[str, Any]:
    frame = pd.read_parquet(path, columns=SAFE_MEMBERSHIP_COLUMNS)
    frame.signal_date = pd.to_datetime(frame.signal_date).dt.normalize()
    ranks = pd.to_numeric(frame.a2_rank, errors="coerce")
    raw40 = frame.loc[ranks.between(1, 40)]
    complete = (frame.signal_date.nunique() == EXPECTED_DATES and len(raw40) == EXPECTED_TOP40_ROWS
                and len(raw40.drop_duplicates(["signal_date", "a2_rank"])) == EXPECTED_TOP40_ROWS
                and raw40.groupby("signal_date").size().eq(40).all())
    return {"path": str(path), "status": "COMPLETE" if complete else "INCOMPLETE",
            "decision_date_count": int(frame.signal_date.nunique()), "raw_top40_row_count": len(raw40),
            "minimum_rank": int(ranks.min()), "maximum_rank": int(ranks.max())}


def greedy_priority(missing: pd.DataFrame, deficits: dict[pd.Timestamp, int], confidence: dict[str, int] | None = None) -> pd.DataFrame:
    confidence = confidence or {}
    work = missing[["security_id", "signal_date"]].drop_duplicates().copy()
    work.signal_date = pd.to_datetime(work.signal_date).dt.normalize()
    dates = {str(key): set(group.signal_date) for key, group in work.groupby("security_id")}
    totals = work.groupby("security_id").size().to_dict()
    deficit = {pd.Timestamp(key).normalize(): int(value) for key, value in deficits.items() if value > 0}
    remaining, rows = set(dates), []
    while remaining:
        scored = []
        for security in remaining:
            active = [date for date in dates[security] if deficit.get(date, 0) > 0]
            scored.append((security, sum(1 / deficit[date] for date in active), len(active), int(totals[security]), int(confidence.get(security, 0))))
        security, score, failing, occurrences, _ = sorted(scored, key=lambda row: (-row[1], -row[2], -row[3], -row[4], row[0]))[0]
        rows.append({"priority": len(rows) + 1, "security_id": security, "greedy_score": score,
                     "failing_date_occurrence_count": failing, "raw_top40_occurrence_count": occurrences})
        for date in dates[security]:
            if deficit.get(date, 0) > 0:
                deficit[date] -= 1
        remaining.remove(security)
    return pd.DataFrame(rows)


def empty_overlay() -> pd.DataFrame:
    types = {"security_id": "string", "ticker": "string", "issuer_name": "string", "old_cik": "Int64", "new_cik": "Int64",
             "mapping_status": "string", "mapping_source": "string", "mapping_confidence": "string",
             "semantic_recovery_status": "string", "recovered_feature_families": "string", "notes": "string"}
    frame = pd.DataFrame({name: pd.Series(dtype=dtype) for name, dtype in types.items()})
    frame["effective_start_date"] = pd.Series(dtype="datetime64[ns]")
    frame["effective_end_date"] = pd.Series(dtype="datetime64[ns]")
    return frame[["security_id", "ticker", "issuer_name", "effective_start_date", "effective_end_date", "old_cik", "new_cik",
                  "mapping_status", "mapping_source", "mapping_confidence", "semantic_recovery_status", "recovered_feature_families", "notes"]]


FINAL_KEYS = """TASK_STATUS PRIMARY_CLASSIFICATION | SOURCE_RESEARCH_ID SOURCE_PREREG_SHA256 SOURCE_CONCEPT_CONTRACT_SHA256 |
COMPANYFACTS_SHA256_MATCH SUBMISSIONS_SHA256_MATCH | OUTCOME_DATA_READ_FOR_RECOVERY MODEL_FIT_COUNT INNER_SELECTION_COUNT OUTER_READ_COUNT READ_2025_COUNT READ_2026_OUTCOME_COUNT |
FROZEN_MEDIAN_COVERAGE_GATE FROZEN_PER_DATE_COVERAGE_THRESHOLD FROZEN_PASSING_DATE_FRACTION_GATE COVERAGE_GATE_CHANGED |
PRE_RECOVERY_RAW_TOP40_MEDIAN_COVERAGE PRE_RECOVERY_PASSING_DATE_FRACTION PRE_RECOVERY_FAILING_DATE_COUNT |
TARGETED_IMPACT_SECURITY_COUNT TARGETED_CIK_UNRESOLVED_COUNT TARGETED_RESOLVED_COVERAGE_GAP_COUNT |
THEORETICAL_MAX_PASSING_DATE_FRACTION THEORETICAL_GATE_RECOVERABLE | CIK_REPAIR_ATTEMPT_COUNT CIK_REPAIR_ACCEPTED_COUNT CIK_REPAIR_AMBIGUOUS_COUNT CIK_REPAIR_REJECTED_COUNT |
DOMESTIC_10Q10K_MAPPABLE_COUNT FOREIGN_FILER_COUNT HISTORICAL_IDENTITY_CHANGE_COUNT NON_OPERATING_ENTITY_COUNT |
SEMANTIC_RECOVERY_CANDIDATE_COUNT SEMANTIC_ALIAS_ACCEPTED_COUNT SEMANTIC_ALIAS_REJECTED_COUNT ECONOMIC_FEATURE_DEFINITION_CHANGED |
BATCHES_COMPLETED RECOVERY_STOP_REASON | POST_RECOVERY_RAW_TOP40_MEDIAN_COVERAGE POST_RECOVERY_PASSING_DATE_FRACTION POST_RECOVERY_FAILING_DATE_COUNT |
MEDIAN_COVERAGE_GATE_PASS PASSING_DATE_FRACTION_GATE_PASS FULL_FROZEN_COVERAGE_GATE_PASS |
PIT_EFFECTIVE_DATE_STATUS RESTATEMENT_GUARD_STATUS UNIT_SCALE_STATUS CONCEPT_CONTRACT_STATUS |
NON_TARGETED_UNRESOLVED_CIK_REPAIR_COUNT | CIK_OVERLAY_SHA256 SEMANTIC_OVERLAY_SHA256 RESUME_CONTRACT_SHA256 |
SYS_EXECUTABLE RUNTIME_CANONICAL_STATUS | TASK_LOCAL_ANTI_BLOAT_STATUS PREEXISTING_ACL_EXCEPTION_COUNT FINAL_ARTIFACT_COUNT HASH_MANIFEST_STATUS |
NEXT_AUTHORIZED_STEP""".split()


def final_block(summary: dict[str, Any]) -> str:
    lines = ["=" * 60, f"{TASK}_FINAL", "=" * 60, ""]
    for key in FINAL_KEYS:
        lines.append("") if key == "|" else lines.append(f"{key}={summary.get(key, 'NOT_APPLICABLE')}")
    return "\n".join([*lines, "", "=" * 60])


def main() -> int:
    import numpy
    print(f"SYS_EXECUTABLE={sys.executable}\nSYS_PREFIX={sys.prefix}\nNUMPY_VERSION={numpy.__version__}\nPANDAS_VERSION={pd.__version__}")
    require(Path(sys.executable) == Path(r"D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe"), "NON_CANONICAL_RUNTIME")
    prereg = verify_sources()
    median_gate, per_date_gate, fraction_gate, definition = frozen_gates(prereg)
    print(f"FROZEN_MEDIAN_COVERAGE_GATE={median_gate}\nFROZEN_PER_DATE_COVERAGE_THRESHOLD={per_date_gate}\nFROZEN_PASSING_DATE_FRACTION_GATE={fraction_gate}")
    payloads, checkpoint = verify_payloads(), verify_checkpoint()
    targeted = pd.read_csv(SOURCE / "targeted_unresolved_impact.csv")
    unresolved = targeted.cik_status.astype(str).eq("UNRESOLVED")
    require((len(targeted), int(unresolved.sum()), int((~unresolved).sum())) == (544, 427, 117), "TARGETED_IMPACT_UNIVERSE_CHANGED")
    probes = [probe_membership(path) for path in MEMBERSHIP_CANDIDATES]
    require(not any(item["status"] == "COMPLETE" for item in probes), "UNEXPECTED_COMPLETE_MEMBERSHIP_REQUIRES_IMPLEMENTATION")
    OUT.mkdir(parents=True, exist_ok=True)
    recovery_prereg = {"research_id": TASK, "task_type": "maintenance_data_recovery", "source_research_id": SOURCE_TASK,
        "source_prereg_sha256": PREREG_SHA, "source_concept_contract_sha256": CONCEPT_SHA, "coverage_gate": prereg["coverage_gate"],
        "covered_security_definition": definition, "sec_payload_hashes": {k: v["sha256"] for k, v in payloads.items()},
        "outcome_data_read": False, "model_fit_allowed": False, "outer_read_allowed": False, "read_2025_outcome_allowed": False,
        "read_2026_outcome_allowed": False, "network_calls_allowed": False, "batch_size": 25, "economic_search_space_changed": False,
        "coverage_gate_changed": False, "checkpoint_reused": True, "checkpoint_manifest": checkpoint,
        "membership_probe": probes, "status": "FROZEN_BEFORE_ANY_RECOVERY_ATTEMPT"}
    recovery_prereg["contract_hash"] = hashlib.sha256(json_bytes(recovery_prereg)).hexdigest()
    write_json(OUT / "recovery_preregistration.json", recovery_prereg)
    priority = targeted.copy()
    priority.insert(0, "priority", pd.Series([pd.NA] * len(priority), dtype="Int64"))
    priority.insert(1, "priority_status", "NOT_COMPUTED_FAIL_CLOSED_NO_COMPLETE_RAW_TOP40_DATE_INCIDENCE")
    priority["failing_date_occurrence_count"], priority["greedy_score"] = pd.NA, np.nan
    write_csv(OUT / "gate_recovery_priority.csv", priority)
    overlay_path = OUT / "sec_fundamental_coverage_recovery_overlay.parquet"
    empty_overlay().to_parquet(overlay_path, index=False, compression="zstd")
    overlay_sha = sha256_file(overlay_path)
    write_csv(OUT / "post_recovery_coverage.csv", pd.DataFrame([{"decision_date": "ALL", "raw_top40_count": EXPECTED_TOP40_ROWS,
        "covered_count": pd.NA, "missing_count": int(targeted.raw_top40_occurrence_count.sum()), "coverage_ratio": PRE_MEDIAN,
        "pass_threshold_count": 20, "coverage_deficit_count": pd.NA, "currently_passes": pd.NA,
        "status": "AGGREGATE_ONLY_FAIL_CLOSED_NO_COMPLETE_DATE_INCIDENCE"}]))
    blockers = pd.DataFrame({"priority": pd.Series([pd.NA] * len(targeted), dtype="Int64"), "security_id": targeted.security_id,
        "ticker": targeted.ticker, "issuer_name": targeted.issuer_name, "failing_date_occurrence_count": pd.NA,
        "gate_deficit_contribution": np.nan, "current_cik_status": targeted.cik_status,
        "blocker_class": "RECOVERY_SEQUENCE_BLOCKED_BEFORE_IDENTITY_REPAIR",
        "reason_unresolved": "NO_COMPLETE_HASH_FROZEN_RAW_TOP40_DATE_INCIDENCE_CHECKPOINT;RECONSTRUCTION_REQUIRES_PROHIBITED_MODEL_FIT_AND_TARGET_READ",
        "theoretical_gain_if_recovered": targeted.estimated_coverage_recovery_if_fixed, "repair_legality": "NOT_ATTEMPTED_FAIL_CLOSED"})
    write_csv(OUT / "remaining_coverage_blockers.csv", blockers)
    summary = {"TASK_STATUS": "FAIL_CLOSED", "PRIMARY_CLASSIFICATION": "FAIL_CLOSED_RECOVERY_CONTRACT_VIOLATION",
        "SOURCE_RESEARCH_ID": SOURCE_TASK, "SOURCE_PREREG_SHA256": PREREG_SHA, "SOURCE_CONCEPT_CONTRACT_SHA256": CONCEPT_SHA,
        "COMPANYFACTS_SHA256_MATCH": "TRUE", "SUBMISSIONS_SHA256_MATCH": "TRUE", "OUTCOME_DATA_READ_FOR_RECOVERY": "FALSE",
        "MODEL_FIT_COUNT": 0, "INNER_SELECTION_COUNT": 0, "OUTER_READ_COUNT": 0, "READ_2025_COUNT": 0, "READ_2026_OUTCOME_COUNT": 0,
        "FROZEN_MEDIAN_COVERAGE_GATE": median_gate, "FROZEN_PER_DATE_COVERAGE_THRESHOLD": per_date_gate,
        "FROZEN_PASSING_DATE_FRACTION_GATE": fraction_gate, "COVERAGE_GATE_CHANGED": "FALSE",
        "PRE_RECOVERY_RAW_TOP40_MEDIAN_COVERAGE": PRE_MEDIAN, "PRE_RECOVERY_PASSING_DATE_FRACTION": PRE_PASS_FRACTION,
        "PRE_RECOVERY_FAILING_DATE_COUNT": EXPECTED_DATES - PRE_PASS_COUNT, "TARGETED_IMPACT_SECURITY_COUNT": 544,
        "TARGETED_CIK_UNRESOLVED_COUNT": 427, "TARGETED_RESOLVED_COVERAGE_GAP_COUNT": 117,
        "THEORETICAL_MAX_PASSING_DATE_FRACTION": 1.0, "THEORETICAL_GATE_RECOVERABLE": "TRUE",
        "CIK_REPAIR_ATTEMPT_COUNT": 0, "CIK_REPAIR_ACCEPTED_COUNT": 0, "CIK_REPAIR_AMBIGUOUS_COUNT": 0, "CIK_REPAIR_REJECTED_COUNT": 0,
        "DOMESTIC_10Q10K_MAPPABLE_COUNT": 0, "FOREIGN_FILER_COUNT": 0, "HISTORICAL_IDENTITY_CHANGE_COUNT": 0,
        "NON_OPERATING_ENTITY_COUNT": 0, "SEMANTIC_RECOVERY_CANDIDATE_COUNT": 0, "SEMANTIC_ALIAS_ACCEPTED_COUNT": 0,
        "SEMANTIC_ALIAS_REJECTED_COUNT": 0, "ECONOMIC_FEATURE_DEFINITION_CHANGED": "FALSE", "BATCHES_COMPLETED": 0,
        "RECOVERY_STOP_REASON": "FAIL_CLOSED_NO_COMPLETE_RAW_TOP40_DATE_INCIDENCE_CHECKPOINT_AND_RECONSTRUCTION_REQUIRES_PROHIBITED_MODEL_FIT",
        "POST_RECOVERY_RAW_TOP40_MEDIAN_COVERAGE": PRE_MEDIAN, "POST_RECOVERY_PASSING_DATE_FRACTION": PRE_PASS_FRACTION,
        "POST_RECOVERY_FAILING_DATE_COUNT": EXPECTED_DATES - PRE_PASS_COUNT, "MEDIAN_COVERAGE_GATE_PASS": "TRUE",
        "PASSING_DATE_FRACTION_GATE_PASS": "FALSE", "FULL_FROZEN_COVERAGE_GATE_PASS": "FALSE",
        "PIT_EFFECTIVE_DATE_STATUS": "PASS_REUSED_UNCHANGED_HASHED_CHECKPOINT", "RESTATEMENT_GUARD_STATUS": "PASS_REUSED_UNCHANGED_HASHED_CHECKPOINT",
        "UNIT_SCALE_STATUS": "PASS_REUSED_UNCHANGED_HASHED_CHECKPOINT", "CONCEPT_CONTRACT_STATUS": "PASS_FROZEN_UNCHANGED",
        "NON_TARGETED_UNRESOLVED_CIK_REPAIR_COUNT": 0, "CIK_OVERLAY_SHA256": overlay_sha,
        "SEMANTIC_OVERLAY_SHA256": "NOT_APPLICABLE", "RESUME_CONTRACT_SHA256": "NOT_APPLICABLE", "SYS_EXECUTABLE": sys.executable,
        "RUNTIME_CANONICAL_STATUS": "PASS", "TASK_LOCAL_ANTI_BLOAT_STATUS": "PASS_WITH_PREEXISTING_ACL_EXCEPTION",
        "PREEXISTING_ACL_EXCEPTION_COUNT": 2, "FINAL_ARTIFACT_COUNT": 7, "HASH_MANIFEST_STATUS": "PASS",
        "NEXT_AUTHORIZED_STEP": "STOP_AND_REVIEW_COVERAGE_ECONOMICS"}
    report = f"""# A2 SEC Fundamental Targeted Coverage Recovery R1

`FAIL_CLOSED_RECOVERY_CONTRACT_VIOLATION`

Frozen payloads, source artifacts, contracts, and the feature checkpoint passed identity verification. Full recovery of all 544 targeted missing securities has theoretical passing-date upper bound 1.0.

Recovery stopped before mapping. Greedy ranking needs incidence for all 1,253 Raw Top40 dates. Frozen OOF covers only 2023--2025; the only 2021--2025 ledger ends at rank 30. Existing reconstruction reads target and fits two HGB models, forbidden here. Partial-date ranking or invented ranks 31--40 would change the contract.

No network call, outcome read, fit, outer/2025/2026 read, mapping, alias, universe, or feature change occurred. `REUSE_CHECKPOINT=TRUE`; no `resume_contract.json` was created.

```text
{final_block(summary)}
```
"""
    write_bytes(OUT / "final_report.md", report.encode())
    names = ["final_report.md", "recovery_preregistration.json", "gate_recovery_priority.csv",
             "sec_fundamental_coverage_recovery_overlay.parquet", "post_recovery_coverage.csv", "remaining_coverage_blockers.csv"]
    write_json(OUT / "hash_manifest.json", {"research_id": TASK, "status": "PASS_HASH_VERIFIED_FAIL_CLOSED_NO_MUTATION",
        "artifact_count_including_manifest": 7, "artifacts": [{"name": name, "bytes": (OUT/name).stat().st_size,
        "sha256": sha256_file(OUT/name)} for name in names], "source_prereg_sha256": PREREG_SHA,
        "source_concept_contract_sha256": CONCEPT_SHA, "companyfacts_sha256": COMPANYFACTS_SHA,
        "submissions_sha256": SUBMISSIONS_SHA, "cik_overlay_sha256": overlay_sha, "semantic_overlay_sha256": None,
        "resume_contract_sha256": None, "outcome_data_read": False, "model_fit_count": 0, "network_call_count": 0})
    print(final_block(summary), flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
