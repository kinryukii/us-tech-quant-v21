"""Thin R4 short-risk CLI over the existing projected reader/ledger/state owners.

Support is metadata-only; fitting requires the whole-matrix SHA, frozen support
and exact existing pre2026 source pins. No quote/PIT authority, account or model
selection is created here. Old R3 sources, matrices and banks remain untouched.
"""
from __future__ import annotations
import argparse
from dataclasses import replace
import gc
import json
import os
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from scripts.common.storage_paths import assert_safe_output_path, resolve
from scripts.research.a2.evaluation import joint_frozen_history_risk_r3 as old
from scripts.research.a2.evaluation.joint_r4_runtime import ID, CAPS, StageLedger, guard, stage_writer
from scripts.research.a2.risk import short_history_risk_r4 as risk
from scripts.research.a2.risk.shared_risk_budget_r2 import StateBudget, LEARNED_KINDS, content_hash
from scripts.research.a2.risk.shared_risk_engine_r2 import META, risk_state_contract
from scripts.research.a2.data.shared_risk_inputs_r3 import _calendar, _clock, STORED_LABEL_COORDINATE

SPEC = "RISK_SPECIFICATION_R3.json"
SUPPORT = "RISK_SUPPORT_R4_R2.json"
BANK = "derived/SHARED_RISK_BANK_MANIFEST_R4.json"
STAGE = "statistical_risk"


def _ref(path):
    path = Path(path)
    return dict(path=str(path), sha256=old.sha(path))


def read_support(path):
    """Bounded adapter for this owner's fixed metadata-only support names.

    Old read_json reserves 128MB for older support names only. R4 support is
    53.9MB of metadata counts/proofs; no data-column permissions are enlarged.
    """
    path=Path(path)
    if path.name not in {"RISK_SUPPORT_R4.json", "RISK_SUPPORT_R4_R1.json", "RISK_SUPPORT_R4_R2.json"}:
        raise ValueError("EXACT_R4_METADATA_SUPPORT_NAME_REQUIRED")
    if path.exists() and path.stat().st_size>32*1024*1024:
        if path.stat().st_size>128*1024*1024:
            raise ValueError("R4_METADATA_SUPPORT_SIZE_LIMIT")
        return json.loads(path.read_text(encoding="utf-8"))
    return old.read_json(path)


def _source(run):
    run = Path(run)
    authority = old.read_json(run / "SOURCE_AUTHORITY.json")
    if (authority.get("strict_PIT_promotion_eligible") is not False
            or authority.get("quote_qualified") is not False
            or authority.get("certified_nav_qualified") is not False):
        raise ValueError("R4_UNCERTIFIED_SOURCE_CONTRACT_REQUIRED")
    ref = authority.get("source_inputs_ref")
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise ValueError("EXPLICIT_EXISTING_SOURCE_INPUTS_REFERENCE_REQUIRED")
    if Path(ref["path"]).drive.upper() != "D:":
        raise ValueError("R4_SOURCE_INPUTS_MUST_STAY_ON_EXISTING_D_STORAGE_NO_EF_ACCESS")
    old._safe_source(ref["path"])
    old._pin(ref["path"], ref["sha256"], "r4_existing_source_inputs")
    source = old.read_json(ref["path"])
    science = dict(scientific_contract_identity=ID,
                   scientific_contract_sha256=old.sha(run / "SOURCE_AUTHORITY.json"),
                   actual_snapshot_timestamp=authority["actual_snapshot_timestamp"])
    return source, science, ref


def code_pins():
    modules = [__file__, risk.__file__, old.__file__,
               "scripts/research/a2/evaluation/joint_r4_runtime.py",
               "scripts/research/a2/data/shared_risk_inputs_r3.py",
               "scripts/research/a2/risk/shared_risk_budget_r2.py",
               "scripts/research/a2/risk/shared_risk_engine_r2.py",
               "scripts/research/a2/risk/joint_risk_estimators.py",
               "scripts/common/storage_paths.py", "scripts/research/a2/inference/joint_shr_anchor_policy_r4.py"]
    return [_ref(Path(name) if Path(name).is_absolute() else old.REPO / name) for name in modules]


def specification(run):
    _, _, source_ref = _source(run)
    result = dict(schema="B_R4_SHORT_RISK_PRODUCER_SPEC_V1", research_id=ID,
        scientific_mode="B_FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY",
        source_authority_ref=_ref(Path(run) / "SOURCE_AUTHORITY.json"), source_inputs_ref=source_ref,
        recipe=risk.specification(), producer_code_pins=code_pins(),
        years=[2023, 2024, 2025], cadence="quarterly", expected_refresh_count=12,
        methods=list(risk.METHODS), stage_learned_cap=CAPS[STAGE],
        learned_planning_upper_bound=156, upper_bound_is_not_actual_spend=True,
        inherited_b_baseline=1876, other_stages_reserved_upper_bound=sum(v for k,v in CAPS.items() if k!=STAGE),
        old_r3_min30_unchanged=True, test2026_rows_read=0, account_attempts=0,
        strict_PIT_promotion_eligible=False, quote_qualified=False, certified_nav_qualified=False,
        scientific_retry=0, full_requested_pool_no_asset_removal=True,
        source_only_bank= BANK, numeric_artifact_template="models/risk/{risk_state_id}.joblib")
    budget_ref=_ref(Path(run)/"BUDGET_SCOPE_FREEZE_R1.json")
    prior_spec=old.read_json(Path(run)/"RISK_SPECIFICATION.json")
    if prior_spec["recipe"]!=result["recipe"] or prior_spec["learned_planning_upper_bound"]!=result["learned_planning_upper_bound"]:
        raise ValueError("TECHNICAL_REBIND_CANNOT_CHANGE_RISK_RECIPE")
    result.update(budget_scope_ref=budget_ref,technical_rebind=dict(
        prior_specification_ref=_ref(Path(run)/"RISK_SPECIFICATION.json"),
        prior_support_ref=_ref(Path(run)/"RISK_SUPPORT_R4.json"), unactivated_preflight_specification_ref=_ref(Path(run)/"RISK_SPECIFICATION_R1.json"), prior_technical_specification_ref=_ref(Path(run)/"RISK_SPECIFICATION_R2.json"),
        semantic_change=False,risk_recipe_unchanged=True,metadata_support_recomputed=False,
        numeric_reads=0,fit_units=0,reason="PRE_NUMERIC_FINAL_STAGE_BUDGET_AND_RUNTIME_REBIND"))
    old.write(run, SPEC, result, immutable=True)
    return result


class CapturingReader(old.ProjectedReader):
    """Retain existing load_period's bounded metadata projection, not a new reader."""
    def read(self, name, columns, **kwargs):
        result = super().read(name, columns, **kwargs)
        if name == "extended_shareholder_y5":
            self.label_meta = result.loc[:, [c for c in columns if c != "y_open5"]].copy()
        elif name == "shareholder_y5":
            self.base_uid_meta = result.loc[:, ["ticker", "signal_date", "security_id"]].copy()
        elif name == "qqq_qfq_years":
            self.qqq_meta = result.loc[:, ["ticker", "trade_date"]].copy()
        return result


def source_support_keys(inputs, label_meta, base_uid_meta, pool):
    """Use source flags and as-of UID/epoch; never infer support from return values."""
    labels = label_meta.merge(base_uid_meta, on=["ticker", "signal_date"], how="left", validate="one_to_one")
    labels = labels.merge(pool["history"][["ticker", "signal_date", "identity_epoch"]],
                          on=["ticker", "signal_date"], how="left", validate="many_to_one")
    qualified = (labels.label_available.eq(True) & labels.endpoint_pair_available.eq(True)
                 & labels.label_unsupported_common_event.eq(False)
                 & labels.label_coordinate.eq(STORED_LABEL_COORDINATE)
                 & labels.security_id.eq(labels.ticker.map(pool["asset_uids"]))
                 & labels.identity_epoch.eq(labels.ticker.map(pool["asset_epochs"])))
    flags = labels.loc[:, ["ticker", "signal_date"]].copy()
    flags.columns = ["asset", "signal_date"]
    flags["origin_at"] = pd.to_datetime(flags.signal_date).map(_clock)
    flags["qualified"] = qualified.astype(bool)
    typed_keys = inputs.observations.loc[:, ["asset", "origin_at"]].copy()
    if typed_keys.duplicated(["asset", "origin_at"]).any():
        raise ValueError("DUPLICATE_TYPED_SOURCE_SUPPORT_KEY")
    result = typed_keys.merge(flags[["asset", "origin_at", "qualified"]],
                              on=["asset", "origin_at"], how="left", validate="one_to_one")
    result["qualified"] = result.qualified.fillna(False).astype(bool)
    return result


def qqq_metadata_only(inputs, qqq_meta, source, science, days, cutoff):
    """Construct clocks from existing exact Open keys, with unavailable NaN values.

    No price or numerical return is invented. Only fully present entry/end keys
    get a metadata slot; missing keys subsequently block qualification.
    """
    frame = qqq_meta.loc[qqq_meta.ticker.eq("QQQ"), ["trade_date"]].copy()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    if frame.trade_date.duplicated().any():
        raise ValueError("DUPLICATE_QQQ_OPEN_KEY")
    available = set(frame.trade_date)
    origins = pd.DatetimeIndex(inputs.observations.origin_at.unique()).sort_values()[-252:]
    receipt = old._receipt(source, science, cutoff, "EXISTING_QQQ_QFQ_OPEN_PROXY", benchmark=True)
    records = []
    for origin in origins:
        day = origin.tz_convert("America/New_York").tz_localize(None).normalize()
        oi = days.get_loc(day)
        ei, xi = oi+1, oi+6
        if xi >= len(days) or _clock(days[xi]) >= cutoff:
            continue
        if days[ei] not in available or days[xi] not in available:
            continue
        records.append(dict(asset="QQQ", origin_at=origin,
            entry_at=_clock(days[ei], opening=True), endpoint_at=_clock(days[xi], opening=True),
            matured_at=_clock(days[xi]), available_at=_clock(days[xi]), horizon=5, uid="QQQ",
            identity_epoch=receipt.identity_epoch, source_identity=receipt.source_identity, return_value=np.nan))
    return replace(inputs, qqq_observations=pd.DataFrame(records, columns=(*META, "return_value")), qqq_receipt=receipt)


def load_context(reader, source, science, days, cutoff, *, numeric):
    # allow_partial_uid=False is mandatory: the requested universe is retained.
    pool, assembly, declaration = old.load_period(reader, source, science, days, cutoff, numeric=numeric)
    if assembly is None:
        raise ValueError("FULL_REQUESTED_POOL_INPUT_BLOCK:" + declaration.get("reason", "UNKNOWN"))
    inputs = assembly.risk_input
    keys = source_support_keys(inputs, reader.label_meta, reader.base_uid_meta, pool)
    if not numeric:
        inputs = qqq_metadata_only(inputs, reader.qqq_meta, source, science, days, cutoff)
    return pool, inputs, keys


def compact_proof(proof):
    # Exact keys remain reproducible from pinned sources; this freezes their hash.
    return {k: v for k, v in proof.items() if k != "qualified_keys"}


def quarterly_schedule(days):
    selected = [n for n in old.schedule(days) if n["method"] == "RH"]
    if len(selected) != 12:
        raise ValueError("EXACT_12_PRE2026_QUARTERLY_REFRESHES_REQUIRED")
    return [{k: n[k] for k in ("as_of", "cutoff", "prior_date")} for n in selected]


def support(run):
    run = Path(run)
    spec = specification(run)
    source, science, _ = _source(run)
    reader = CapturingReader(source, phase="support")
    days, _ = _calendar(reader.read("calendar", ("trade_date",), date_field="trade_date").trade_date)
    groups, nodes = [], []
    for scheduled in quarterly_schedule(days):
        group = dict(**scheduled, metadata_qualification=None, block_reason=None)
        try:
            pool, inputs, keys = load_context(reader, source, science, days, pd.Timestamp(scheduled["cutoff"]), numeric=False)
            proof = risk.qualify_metadata(inputs, as_of=pd.Timestamp(scheduled["as_of"]), support_metadata=keys)
            group.update(metadata_qualification=compact_proof(proof), requested_assets=list(pool["assets"]),
                         asset_uids=pool["asset_uids"], asset_epochs=pool["asset_epochs"],
                         segment_starts=pool["segment_starts"], source_support_sha256=content_hash(keys))
        except (ValueError, TypeError, KeyError) as error:
            group["block_reason"] = str(error)
        groups.append(group)
        for method in risk.METHODS:
            reason = group["block_reason"]
            if method in {"SHR_DYNAMIC", "SHR_ROBUST"}:
                reason = spec["recipe"]["dynamic_status" if method == "SHR_DYNAMIC" else "robust_status"]
            elif reason is None:
                reasons = group["metadata_qualification"]["method_block_reasons"][method]
                reason = reasons[0] if reasons else None
            nodes.append(dict(risk_node=method+"@"+scheduled["as_of"], method=method,
                              as_of=scheduled["as_of"], cutoff=scheduled["cutoff"],
                              numeric_check_eligible=reason is None, metadata_block_reason=reason))
        gc.collect()
    result = dict(schema="B_R4_SHORT_RISK_METADATA_SUPPORT_V1", research_id=ID,
        source_authority_ref=spec["source_authority_ref"], source_inputs_ref=spec["source_inputs_ref"],
        specification_ref=_ref(run / SPEC), groups=groups, nodes=nodes,
        group_count=12, node_count=72, numeric_reads=0, learned_fit_units=0,
        account_attempts=0, test2026_rows_read=0, strict_PIT_promotion_eligible=False,
        quote_qualified=False, certified_nav_qualified=False, projections=reader.audit)
    old.write(run, SUPPORT, result, immutable=True)
    return dict(status="SUPPORT_COMPLETE", groups=12, nodes=72,
                numeric_check_eligible=sum(n["numeric_check_eligible"] for n in nodes), support_ref=_ref(run / SUPPORT))


def _fit_guard(run, expected_matrix_sha):
    matrix = guard(run, expected_matrix_sha)
    spec, sup = old.read_json(Path(run) / SPEC), read_support(Path(run) / SUPPORT)
    pinned = {str(Path(v["path"]).resolve()): v["sha256"] for v in matrix.get("pinned_artifacts", ())}
    budget_ref=matrix.get("budget_scope_ref")
    if not isinstance(budget_ref,dict) or set(budget_ref)!={"path","sha256"}:
        raise ValueError("EXACT_TOTAL_MATRIX_BUDGET_REFERENCE_REQUIRED")
    old._pin(budget_ref["path"],budget_ref["sha256"],"risk_budget_scope")
    budget_path=Path(budget_ref["path"])
    if pinned.get(str(budget_path.resolve()))!=budget_ref["sha256"]:
        raise ValueError("R4_TOTAL_MATRIX_MISSING_BUDGET_PIN")
    for name in (SPEC, SUPPORT, "SOURCE_AUTHORITY.json"):
        path = Path(run) / name
        if pinned.get(str(path.resolve())) != old.sha(path):
            raise ValueError("R4_TOTAL_MATRIX_MISSING_RISK_INPUT_PIN:" + name)
    for pin in spec["producer_code_pins"]:
        old._pin(pin["path"], pin["sha256"], "r4_risk_producer")
    if (spec["research_id"] != ID or spec["recipe"] != risk.specification()
            or sup["specification_ref"] != _ref(Path(run) / SPEC)
            or len(sup["groups"]) != 12 or len(sup["nodes"]) != 72):
        raise ValueError("R4_FROZEN_RISK_SPEC_OR_SUPPORT_CHANGED")
    return spec, sup


def _persist_state(run, state):
    path = Path(run) / "models/risk" / (state.risk_state_id+".joblib")
    assert_safe_output_path(path, kind="backtest", paths=resolve(old.REPO))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError("UNREGISTERED_EXISTING_RISK_ARTIFACT_PRESERVED")
    _atomic_joblib(state, path)
    return _ref(path)


def _atomic_joblib(value, path):
    assert_safe_output_path(path, kind="backtest", paths=resolve(old.REPO))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+".tmp")
    joblib.dump(value, temporary, compress=3)
    with temporary.open("r+b") as handle:
        os.fsync(handle.fileno())
    temporary.replace(path)


def _save_cache(run, cache, asof):
    target = Path(run)/"work"/("RISK_CACHE_"+pd.Timestamp(asof).date().isoformat()+".joblib")
    payload = dict(schema="B_R4_SHARED_RISK_RECOVERY_CACHE_V1", context=cache.context,
                   records=cache._records, budget_snapshot=cache.budget.snapshot())
    _atomic_joblib(payload,target)
    return _ref(target)


def _restore_cache(run, ledger, inputs, asof, reference):
    old._pin(reference["path"],reference["sha256"],"r4_exact_recovery_cache")
    payload=joblib.load(reference["path"])
    snapshot=payload["budget_snapshot"]
    # Existing group occupancy is represented in the restored budget exactly once.
    budget=StateBudget(limit=CAPS[STAGE]-ledger.status["new_fit_units"]+snapshot["learned_total"],reserve_callback=ledger.reserve)
    cache=risk.make_cache(inputs,as_of=pd.Timestamp(asof),budget=budget)
    if payload.get("schema")!="B_R4_SHARED_RISK_RECOVERY_CACHE_V1" or cache.context!=payload["context"]:
        raise ValueError("R4_RECOVERY_CACHE_CONTEXT_CHANGED")
    budget.counts=snapshot["counts"]
    budget.events=snapshot["events"]
    budget._keys={v["key"] for v in budget.events}
    cache._records=payload["records"]
    return cache


def bank_metadata(spec, sup, ledger_status, *, spec_ref, support_ref, ledger_ref):
    """Source-only shared-bank shape; R4 admission never borrows R3 method pins."""
    states, diagnostics = [], []
    for record in ledger_status["records"]:
        entry = {k: record.get(k) for k in ("risk_node", "method", "as_of", "cutoff", "assets", "asset_uids",
                 "asset_epochs", "risk_state_id", "fit_dependency_ids", "learned_states", "status", "block_reason",
                 "covariance_sha256", "covariance_shape", "finite_check", "psd_check", "primary_source")}
        entry.update(research_id=ID, domain_role="FULL_REQUESTED_POOL", exact_reuse_only=True,
                     horizon_sessions=5, return_coordinate="shareholder_value_open_return",
                     source_contract=spec["source_authority_ref"], specification_ref=spec_ref,
                     support_ref=support_ref, producer_code_pins=spec["producer_code_pins"],
                     strict_PIT_promotion_eligible=False, quote_qualified=False, certified=False,
                     account_qualification_granted=False, full_pool_policy_qualification_granted=False,
                     riskstate_artifact_retains_all_substate_values=False)
        if record.get("artifact_ref"):
            entry["artifact"] = record["artifact_ref"]
        if record.get("status") == "CONDITIONAL_FROZEN_HISTORY_MECHANISM" and record.get("artifact_ref"):
            entry.update(admission="CONDITIONAL_SOURCE_ONLY_EXACT_STATE", reusable=True)
            states.append(entry)
        else:
            entry.update(admission="DIAGNOSTIC_ONLY", reusable=False)
            diagnostics.append(entry)
    return dict(schema="B_R4_CONDITIONAL_RISK_BANK_METADATA_V1", research_id=ID,
        stage_status="COMPLETE_WITH_TYPED_DIAGNOSTICS" if len(ledger_status["records"]) == 72 else "PARTIAL_OR_UNFINISHED",
        state_contract={**risk_state_contract(), "r4_source_only_interface":True,
                        "min_asset_observations":10, "original_r3_min30_unchanged":True},
        r4_short_history_recipe=spec["recipe"], states=states,
        blocked_or_unverified_diagnostics=diagnostics, fixed_ledger_ref=ledger_ref,
        physical_operation_bindings=[{k:e[k] for k in
            ("key","kind","name","status","context","inputs_sha256","parameters","learned_states",
             "result_sha256","dependencies","stage","started_utc") if k in e}
            for e in ledger_status["physical_events"]],
        learned_substate_artifacts=[], standalone_substate_reuse_requires_retained_value_artifact=True,
        count_receipt=dict(inherited_b_baseline=1876, stage_new_units=ledger_status["new_fit_units"],
            cumulative_b_lower_bound=1876+ledger_status["new_fit_units"], branch_total_requires_other_stage_merge=True,
            stage_cap=CAPS[STAGE], upper_bound_is_not_actual_spend=True),
        account_attempts=0, test2026_rows_read=0, strict_PIT_promotion_eligible=False,
        quote_qualified=False, certified_nav_qualified=False)


def fit(run, *, expected_matrix_sha=None):
    run = Path(run)
    spec, sup = _fit_guard(run, expected_matrix_sha)
    source, science, _ = _source(run)
    (run / "work").mkdir(parents=True, exist_ok=True)
    with stage_writer(run, STAGE):
        ledger = StageLedger(run, STAGE, expected_matrix_sha=expected_matrix_sha)
        reader = CapturingReader(source, phase="fit")
        days, _ = _calendar(reader.read("calendar", ("trade_date",), date_field="trade_date").trade_date)
        if quarterly_schedule(days) != [{k:g[k] for k in ("as_of","cutoff","prior_date")} for g in sup["groups"]]:
            raise ValueError("FROZEN_R4_RISK_SCHEDULE_CHANGED")
        for group in sup["groups"]:
            planned = [n for n in sup["nodes"] if n["as_of"] == group["as_of"]]
            retained = [r for r in ledger.status["records"] if r["as_of"] == group["as_of"]]
            done = {r["risk_node"] for r in retained}
            for record in retained:
                if record.get("artifact_ref"):
                    old._pin(record["artifact_ref"]["path"], record["artifact_ref"]["sha256"], "retained_r4_risk_state")
            pending = [n for n in planned if n["risk_node"] not in done]
            if not pending:
                continue
            inputs, keys, cache, error = None, None, None, None
            active = [n for n in pending if n["numeric_check_eligible"]]
            if active:
                try:
                    # Revalidate source-support hashes before the numeric projection.
                    pool, metadata_inputs, metadata_keys = load_context(reader, source, science, days,
                        pd.Timestamp(group["cutoff"]), numeric=False)
                    proof = risk.qualify_metadata(metadata_inputs, as_of=pd.Timestamp(group["as_of"]), support_metadata=metadata_keys)
                    if compact_proof(proof) != group["metadata_qualification"] or content_hash(metadata_keys) != group["source_support_sha256"]:
                        raise ValueError("FROZEN_SOURCE_SUPPORT_PROJECTION_CHANGED")
                    pool, inputs, keys = load_context(reader, source, science, days, pd.Timestamp(group["cutoff"]), numeric=True)
                    if risk.qualify_metadata(inputs, as_of=pd.Timestamp(group["as_of"]), support_metadata=keys) != proof:
                        raise ValueError("NUMERIC_SOURCE_PROJECTION_CHANGED_METADATA_CONTEXT")
                    budget = StateBudget(limit=CAPS[STAGE]-ledger.status["new_fit_units"], reserve_callback=ledger.reserve)
                    cache = risk.make_cache(inputs, as_of=pd.Timestamp(group["as_of"]), budget=budget)
                    if retained:
                        reference=ledger.status.get("shared_cache_artifacts",{}).get(group["as_of"])
                        if reference is None:
                            raise ValueError("PARTIAL_GROUP_SHARED_CACHE_UNAVAILABLE_NO_SCIENTIFIC_REFIT")
                        cache=_restore_cache(run,ledger,inputs,group["as_of"],reference)
                except (ValueError, TypeError, KeyError) as failure:
                    error = str(failure)
            for node in pending:
                record = dict(risk_node=node["risk_node"], method=node["method"], as_of=node["as_of"], cutoff=node["cutoff"],
                              assets=group.get("requested_assets", []), asset_uids=group.get("asset_uids", {}),
                              asset_epochs=group.get("asset_epochs", {}), learned_states=0)
                if not node["numeric_check_eligible"] or error:
                    record.update(status="BLOCKED_METADATA" if not node["numeric_check_eligible"] else "BLOCKED_INPUT",
                                  block_reason=node["metadata_block_reason"] or error)
                else:
                    before = cache.budget.learned_total
                    try:
                        with threadpool_limits(limits=2):
                            state = risk.fit_risk(node["method"], inputs, as_of=pd.Timestamp(node["as_of"]),
                                support_metadata=keys, cache=cache, expected_qualification=proof)
                        ledger.sync(cache.budget.events)
                        record.update(status=state.status, risk_state_id=state.risk_state_id,
                                      artifact_ref=_persist_state(run, state),
                                      fit_dependency_ids=list(state.fit_dependency_ids),
                                      learned_states=cache.budget.learned_total-before,
                                      block_reason=state.notes.get("block_reason"),
                                      covariance_sha256=state.notes.get("covariance_sha256"),
                                      covariance_shape=None if state.covariance is None else list(state.covariance.shape),
                                      finite_check=state.covariance is not None,
                                      psd_check=state.notes.get("numeric_check",{}).get("psd_check"),
                                      primary_source={k:state.source_receipt[k] for k in
                                          ("source_identity","source_version","source_sha256","return_coordinate","identity_epoch")})
                    except (ValueError, TypeError, OSError, RuntimeError) as failure:
                        ledger.sync(cache.budget.events)
                        record.update(status="FIT_FAILURE", block_reason=str(failure), learned_states=cache.budget.learned_total-before)
                        ledger.status["failures"].append(dict(risk_node=node["risk_node"], error=str(failure)))
                if cache is not None:
                    reference=_save_cache(run,cache,group["as_of"])
                    ledger.status.setdefault("shared_cache_artifacts",{})[group["as_of"]]=reference
                ledger.status["records"].append(record)
                ledger.checkpoint()
                print(json.dumps(dict(risk_node=node["risk_node"], status=record["status"],
                                      stage_new_learned_units=ledger.status["new_fit_units"])), flush=True)
            gc.collect()
        ledger.status["status"] = "B_R4_STATISTICAL_RISK_FROZEN_QUEUE_COMPLETE"
        ledger.checkpoint()
        bank = bank_metadata(spec, sup, ledger.status, spec_ref=_ref(run/SPEC), support_ref=_ref(run/SUPPORT),
                             ledger_ref=_ref(run/"work/RISK_FIT_STATUS.json"))
        old.write(run, BANK, bank)
        return dict(status=ledger.status["status"], stage_new_learned_units=ledger.status["new_fit_units"],
                    risk_states=len(bank["states"]), diagnostics=len(bank["blocked_or_unverified_diagnostics"]),
                    bank_ref=_ref(run/BANK), test2026_rows_read=0, account_attempts=0)


def qualify_consumption(entry, *, ordered_assets, current_uids, signal_asof, expected_method):
    """Quarterly consumers fail closed if assets/UID change; never enlarge bank risk."""
    if (entry.get("admission") != "CONDITIONAL_SOURCE_ONLY_EXACT_STATE"
            or entry.get("method") != expected_method
            or tuple(entry.get("assets", ())) != tuple(ordered_assets)
            or entry.get("asset_uids") != dict(current_uids)):
        raise ValueError("BLOCKED_RISK_BANK_EXACT_METHOD_DOMAIN_OR_UID_MISMATCH")
    signal, fit = pd.Timestamp(signal_asof), pd.Timestamp(entry["as_of"])
    if signal.tzinfo is None or fit.tzinfo is None or signal < fit or signal >= pd.Timestamp("2026-01-01", tz="UTC"):
        raise ValueError("BLOCKED_RISK_BANK_FUTURE_OR_2026_APPLICATION")
    if signal.tz_convert("America/New_York").tz_localize(None).to_period("Q") != fit.tz_convert("America/New_York").tz_localize(None).to_period("Q"):
        raise ValueError("BLOCKED_RISK_BANK_QUARTER_CARRY_EXPIRED")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--phase", choices=("spec", "support", "fit"), required=True)
    parser.add_argument("--expected-matrix-sha")
    args = parser.parse_args()
    output = specification(args.run) if args.phase == "spec" else support(args.run) if args.phase == "support" else fit(args.run, expected_matrix_sha=args.expected_matrix_sha)
    print(json.dumps(old._json(output)), flush=True)


if __name__ == "__main__":
    main()




