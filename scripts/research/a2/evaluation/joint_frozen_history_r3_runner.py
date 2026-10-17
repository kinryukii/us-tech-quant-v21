"""Bounded B frozen-history continuation; reuses registered inputs/common account.

Control stage only: no source archaeology, provider fetch, model fit or 2026
reader. New mechanism results never alter legacy quote/account qualifications.
"""
from __future__ import annotations
import argparse
import os
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import traceback
import joblib
import numpy as np
import pandas as pd
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.evaluation.joint_frozen_history_r3 import (
    FrozenHistoryAccountFreeze, input_digests, source_pins,
    run_frozen_history_controls)
from scripts.research.a2.evaluation.joint_continuation import raw_extension_into_inputs
from scripts.research.a2.evaluation.joint_method_accounts import evaluation_market, with_effective_event_quality, json_safe

REPO = Path(__file__).resolve().parents[4]
PARENT = "JOINT_TOP20_PORTFOLIO_POLICY_PRE2026_TEST2026_R1/V24"

def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()

def write(run, name, value, *, immutable=False):
    paths = resolve(REPO)
    target = run/name
    assert_safe_output_path(target, kind="backtest", paths=paths)
    target.parent.mkdir(parents=True, exist_ok=True)
    value = json_safe(value)
    if immutable and target.exists():
        if json.loads(target.read_text(encoding="utf-8")) != value:
            raise ValueError("IMMUTABLE_STAGE_CHANGED:"+name)
        return sha(target)
    temporary = target.with_name(target.name+".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    temporary.replace(target)
    return sha(target)

def load_control_inputs(run):
    """Only hash-proven, producer-bounded pre2026 input bytes; no outcome reader."""
    paths = resolve(REPO)
    run = Path(run).resolve()
    assert_safe_output_path(run, kind="backtest", paths=paths)
    if run.parent != paths.backtest_root/"V24":
        raise ValueError("EXPECTED_EXISTING_MANAGED_V24_RUN")
    state = json.loads((run/"EXECUTION_STATE.json").read_text(encoding="utf-8"))
    if state["Checkpoints"]["science_freeze_sha256"] != sha(run/"SCIENCE_FREEZE.json"):
        raise ValueError("SCIENCE_FREEZE_CHANGED")
    freeze = json.loads((run/"SCIENCE_FREEZE.json").read_text(encoding="utf-8"))
    if freeze["candidate_phase"] != "NOT_YET_FROZEN_OR_ACTIVATED" or freeze["control_stage"]["fit_units"] != 0:
        raise ValueError("CONTROL_STAGE_SCOPE_CHANGED")
    for pin in (freeze["source_authority"], freeze["snapshot_manifest"]):
        if sha(pin["path"]) != pin["sha256"]:
            raise ValueError("REGISTERED_SOURCE_SNAPSHOT_CHANGED")
    registration = run/"REGISTRATION_RECEIPT.json"
    if state["Checkpoints"]["registration_receipt_sha256"] != sha(registration):
        raise ValueError("REGISTRATION_RECEIPT_CHANGED")
    manifest = json.loads((run/"input_manifest.json").read_text(encoding="utf-8"))
    proof = manifest["pre2026_binary_cache_proof"]
    if not proof["producer_no_account_results"] or not proof["market_constructor_bound_pre2026_parquet_before_body_read"] or proof["receipt_test2026_reads"] != 0:
        raise ValueError("UNPROVED_BINARY_TEMPORAL_BOUNDARY")
    # Verify every recorded dependency before any data deserialization.
    for name, pin in manifest["input_sources"].items():
        if sha(pin["path"]) != pin["sha256"]:
            raise ValueError("BOUND_DEPENDENCY_CHANGED:"+name)
    records = manifest["input_sources"]
    inputs = joblib.load(records["market_cache"]["path"])
    if set(inputs) != {"market", "feature_cube", "mu", "sigma", "account", "replay_kwargs"}:
        raise ValueError("UNEXPECTED_CACHE_PAYLOAD")
    dates = pd.DatetimeIndex(inputs["market"].dates)
    if dates.hasnans or dates.has_duplicates or dates.max() >= pd.Timestamp("2026-01-01"):
        raise ValueError("CACHE_BOUNDARY_CHANGED")
    # This cube is not needed by the control; release it before replay.
    del inputs["feature_cube"]
    bound_raw_root = Path(records["raw_held_receipt"]["path"]).parent
    raw_reuse = raw_extension_into_inputs(SimpleNamespace(base_root=bound_raw_root), inputs)
    market, start = evaluation_market(inputs["market"])
    market = with_effective_event_quality(market, inputs["replay_kwargs"])
    events = joblib.load(records["cash_kwargs"]["path"])
    scores = inputs["mu"]["RAW_CONTROL"][start:].copy()
    exact = json.loads(Path(records["exact39_metadata"]["path"]).read_text(encoding="utf-8"))
    if exact["key_count"] != 39 or exact["lineage_numeric_checks_passed"] != 39 or exact["qualified_quote_keys"] != 0:
        raise ValueError("EXACT39_LEGACY_IDENTITY_CHANGED")
    quality_only = np.zeros(market.quality.shape, bool)
    di, ti = pd.Index(market.dates), pd.Index(market.tickers)
    keys = []
    for row in exact["rows"]:
        d, c = di.get_indexer([pd.Timestamp(row["date"])])[0], ti.get_indexer([row["ticker"]])[0]
        if d < 0 or c < 0 or not row["original_cache_values_equal_frozen_raw_rtol_1e_12"]:
            raise ValueError("EXACT39_RESEARCH_PROXY_BINDING")
        # This is explicitly an uncertified snapshot assumption, not source PASS.
        if market.quality[d,c]:
            quality_only[d,c] = True
        keys.append(dict(date=row["date"], ticker=row["ticker"], transport_code=row["transport_code"]))
    return market, scores, events, quality_only, raw_reuse, keys

def controls(run):
    run = Path(run).resolve()
    state = json.loads((run/"EXECUTION_STATE.json").read_text(encoding="utf-8"))
    if state.get("actual_account_attempts", 0) != 0 or (run/"CONTROL_STAGE_RESULT.json").exists():
        raise ValueError("EXISTING_ATTEMPT_RETAINED_NO_AUTOMATIC_ACCOUNT_RETRY")
    market, scores, events, mask, raw_reuse, keys = load_control_inputs(run)
    claim = run/"CONTROL_ATTEMPT_CLAIM.json"
    assert_safe_output_path(claim, kind="backtest", paths=resolve(REPO))
    descriptor = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(dict(run_id=run.name, reserved_control_attempts=2, pid=os.getpid(), no_automatic_retry=True), stream)
        stream.flush(); os.fsync(stream.fileno())
    freeze = FrozenHistoryAccountFreeze(
        research_id="V24_B_JOINT_FROZEN_HISTORY_RISK_R3",
        parent_research_id=PARENT.replace("/","::"),
        run_id=run.name,
        registration_receipt_sha256=sha(run/"REGISTRATION_RECEIPT.json"),
        input_sha256=input_digests(market, scores, events, mask),
        source_sha256=source_pins(),
        identity_assumption="Frozen ticker/code nominal common-or-ADS security and RAW_OLD_SECURITY_SHARES source-derived cash class; unresolved custody remains UNKNOWN; only exact39 uncertified price-quality proxy is assumed.",
        synthetic=False)
    payload = dict(freeze=asdict(freeze), expected_freeze_sha256=freeze.digest(),
        exact39_uncertified_proxy_keys=keys, raw_held_inference_reuse=raw_reuse,
        runner_sha256=sha(__file__), strict_PIT_promotion_eligible=False)
    write(run, "CONTROL_ACCOUNT_FREEZE.json", payload, immutable=True)
    state.update(actual_account_attempts=2, Progress="TWO_CONTROL_ATTEMPTS_RESERVED",
        Exact_resume_point="ACCOUNT_ATTEMPTS_RETAINED_INSPECT_CONTROL_STAGE_RESULT_NO_RETRY")
    state["Checkpoints"]["control_account_freeze_sha256"] = sha(run/"CONTROL_ACCOUNT_FREEZE.json")
    write(run, "EXECUTION_STATE.json", state)
    try:
        result = run_frozen_history_controls(market, scores, event_inputs=events,
            uncertified_quality_only=mask, freeze=freeze,
            expected_freeze_sha256=payload["expected_freeze_sha256"])
        replay = result.replay
        artifacts = {}
        for name in ("daily", "positions", "orders", "fills", "execution_results", "contexts",
                     "operational_actions", "accounting_exceptions", "entitlements"):
            frame = getattr(replay, name, None)
            if frame is None:
                continue
            target = run/"derived/controls"/(name+".parquet")
            assert_safe_output_path(target, kind="backtest", paths=resolve(REPO))
            target.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(target, index=False)
            artifacts[name] = dict(path=str(target), sha256=sha(target), rows=len(frame))
        qualified = all(v["mechanism_accounting_consistent"] for v in result.qualification_by_path.values())
        summary = dict(status="MECHANISM_CONTROLS_CONSISTENT_UNCERTIFIED" if qualified else "STOP_MECHANISM_CONTROLS_UNQUALIFIED",
            mechanism_controls_qualified=qualified, qualification=result.qualification_by_path,
            audit=replay.audit, artifacts=artifacts,
            strict_PIT_promotion_eligible=False, quote_qualified=False, certified_nav_qualified=False,
            actual_new_fit=0, actual_account_attempts=2, test2026_reads=0)
        write(run, "CONTROL_STAGE_RESULT.json", summary, immutable=True)
        state.update(Progress=summary["status"], Exact_resume_point="FREEZE_FAMILY_AND_QUALIFICATION_ONLY_SUPPORT" if qualified else "REPORT_CONTROL_FAIL_AND_COMPLETE_INDEPENDENT_LEGAL_DESIGN",
            Remaining_work="Qualified controls permit candidate family support discovery; new fits still need explicit budget/family closure",
            actual_new_fit=0)
        state["Completed_expensive_stages"].append("TWO_NEW_MECHANISM_CONTROL_REPLAYS")
        state["Checkpoints"]["control_stage_result_sha256"] = sha(run/"CONTROL_STAGE_RESULT.json")
        write(run, "EXECUTION_STATE.json", state)
        print(json.dumps(json_safe({k:v for k,v in summary.items() if k != "artifacts"})), flush=True)
        return summary
    except Exception as exc:
        failure = dict(status="FAILED_ATTEMPTS_RETAINED", error=type(exc).__name__+":"+str(exc),
            actual_account_attempts=2, actual_new_fit=0, strict_PIT_promotion_eligible=False)
        write(run, "CONTROL_STAGE_FAILURE.json", failure, immutable=True)
        state["Failures"].append(failure)
        state.update(Progress="CONTROL_FAILED_ATTEMPTS_RETAINED", Exact_resume_point="INSPECT_BOUNDED_ENGINEERING_FAILURE_NO_AUTOMATIC_RETRY")
        write(run, "EXECUTION_STATE.json", state)
        raise

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--phase", choices=("controls",), required=True)
    args = parser.parse_args()
    controls(Path(args.run))

if __name__ == "__main__":
    main()
