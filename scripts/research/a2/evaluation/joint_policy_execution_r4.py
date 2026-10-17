"""R4 policy binding: metadata carry discovery and unchanged account dispatch.

No new science, estimator, forecast, q/action/G implementation or account engine.
Discovery reads only cutoff-bound source metadata and stops each quarter at its
first hard domain failure. Economic replay is a separate caller-authorized phase.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass
from pathlib import Path
import json
import os
import numpy as np
import pandas as pd

from scripts.research.a2.evaluation import joint_short_risk_execution_r4 as producer
from scripts.research.a2.evaluation import joint_frozen_history_r3 as account
from scripts.research.a2.evaluation.joint_r4_runtime import ID, guard, stage_writer
from scripts.research.a2.inference.joint_shr_anchor_policy_r4 import AnchorContract, AnchorUse, ShrAnchorPolicy, METHODS
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
from scripts.research.a2.data.shared_risk_inputs_r3 import _calendar, _clock

old = producer.old
SPEC = "B_POLICY_SPECIFICATION.json"
SUPPORT = "POLICY_SUPPORT_R4.json"
BINDING = "POLICY_EXECUTION_BINDING_R4.json"


class PolicyInputBlocked(ValueError):
    pass


def _ref(path):
    return producer._ref(path)


def _spec(run):
    run = Path(run)
    spec = old.read_json(run / SPEC)
    if (spec.get("research_id") != ID or len(spec.get("original_main", ())) != 32
            or len(spec.get("original_sensitivity", ())) != 16
            or len(spec.get("original_interaction_contrasts", ())) != 12
            or spec.get("new_sensitivity") != [] or spec.get("new_interaction_contrasts") != []
            or any(spec.get(k) is not False for k in ("strict_PIT_promotion_eligible", "quote_qualified", "certified_nav_qualified"))
            or spec.get("test2026_reads") != 0 or spec.get("qualification_before_economic_replay") is not True):
        raise PolicyInputBlocked("EXACT_AUTHORISED_R4_POLICY_SCOPE_REQUIRED")
    anchors = spec.get("new_shr_anchors", ())
    if len(anchors) != 4 or tuple(r["risk"] for r in anchors) != METHODS:
        raise PolicyInputBlocked("EXACT_FOUR_NAMED_SHR_ANCHORS_REQUIRED")
    for row in anchors:
        expected = ("R4_SHR_ANCHOR_"+row["risk"], "P0", "Q0", "A0", "G0", 10, 1, 20260928)
        actual = tuple(row[k] for k in ("id", "prediction", "optimizer", "action", "gross", "cost_bps", "configs", "seed"))
        if actual != expected:
            raise PolicyInputBlocked("SHR_ANCHOR_TUPLE_CHANGED")
    for key in ("old_tuple_reference", "scope_authorisation_ref", "account_semantics_reference"):
        ref = spec[key]
        old._safe_source(ref["path"])
        old._pin(ref["path"], ref["sha256"], "policy:"+key)
    family = old.read_json(spec["old_tuple_reference"]["path"])
    # The immutable specification is the authorised exact tuple binding. No
    # new registration/family generator or risk-method substitution lives here.
    if family.get("research_id") != "V24_B_JOINT_FROZEN_HISTORY_RISK_R3":
        raise PolicyInputBlocked("EXACT_PARENT_TUPLE_IDENTITY_REQUIRED")
    return spec


def _quarter_group(group):
    if group.get("block_reason"):
        raise PolicyInputBlocked("QUARTER_SOURCE_METADATA_BLOCK:"+group["block_reason"])
    assets = tuple(group["requested_assets"])
    if not assets or assets != tuple(sorted(set(assets))):
        raise PolicyInputBlocked("EXACT_ORDERED_FULL_POOL_REQUIRED")
    uids, epochs = group["asset_uids"], group["asset_epochs"]
    if set(uids) != set(assets) or set(epochs) != set(assets):
        raise PolicyInputBlocked("COMPLETE_UID_EPOCH_KEYS_REQUIRED")
    if any(not isinstance(uids[a], str) or not uids[a] or not isinstance(epochs[a], str) or not epochs[a] for a in assets):
        raise PolicyInputBlocked("UNKNOWN_UID_EPOCH_FORBIDDEN")
    if len(set(uids.values())) != len(assets):
        raise PolicyInputBlocked("NONUNIQUE_SECURITY_UID")
    cutoff, asof = pd.Timestamp(group["cutoff"]), pd.Timestamp(group["as_of"])
    if cutoff.tzinfo is None or asof.tzinfo is None or not cutoff < asof or asof.tz_convert("UTC") >= pd.Timestamp("2026-01-01", tz="UTC"):
        raise PolicyInputBlocked("LEGAL_QUARTER_CUTOFF_REQUIRED")
    return assets, uids, epochs


def compare_pool(group, pool, decision_asof):
    """Pure metadata identity comparison; no covariance/domain enlargement."""
    assets, uids, epochs = _quarter_group(group)
    stamp = pd.Timestamp(decision_asof)
    if stamp.tzinfo is None or stamp < pd.Timestamp(group["as_of"]) or stamp >= pd.Timestamp("2026-01-01", tz="UTC"):
        raise PolicyInputBlocked("PRE2026_DECISION_NOT_BEFORE_RISK_ASOF_REQUIRED")
    current = tuple(pool["assets"])
    reason = None
    if pool.get("blocked_assets"):
        reason = "DAILY_CURRENT_UID_UNBOUND"
    elif current != assets:
        reason = "DAILY_FULL_REQUESTED_POOL_CHANGED"
    elif any(pool["asset_uids"].get(a) != uids[a] for a in assets):
        reason = "DAILY_SECURITY_UID_CHANGED"
    elif any(pool["asset_epochs"].get(a) != epochs[a] for a in assets):
        reason = "DAILY_CONTIGUOUS_SECURITY_EPOCH_CHANGED"
    uid_changes = [{"asset": a, "risk_uid": uids.get(a), "daily_uid": pool["asset_uids"].get(a)}
                   for a in assets if a in current and uids.get(a) != pool["asset_uids"].get(a)]
    epoch_changes = [{"asset": a, "risk_epoch": epochs.get(a), "daily_epoch": pool["asset_epochs"].get(a)}
                     for a in assets if a in current and epochs.get(a) != pool["asset_epochs"].get(a)]
    return dict(decision_asof=stamp.isoformat(), status="BLOCKED" if reason else "EXACT_DOMAIN_METADATA_MATCH",
        block_reason=reason, requested_count=len(current), fitted_count=len(assets),
        added_assets=sorted(set(current)-set(assets)), absent_assets=sorted(set(assets)-set(current)),
        uid_changes=uid_changes, epoch_changes=epoch_changes, blocked_assets=pool.get("blocked_assets", {}),
        current_pool_metadata_sha256=content_hash({k: pool[k] for k in ("assets", "asset_uids", "asset_epochs", "segment_starts", "blocked_assets")}),
        numeric_reads=0, outcome_reads=0, extra_risk_refreshes=0, covariance_modified=False)


class DailyMetadataPool:
    """Incrementally reuse current_pool on source metadata available by cutoff.

    Each physical read has its cutoff predicate before body read. Earlier legal
    rows can be retained in memory; future metadata is never loaded then filtered.
    """
    def __init__(self, reader, days):
        self.reader, self.days = reader, days
        self.history = pd.DataFrame(columns=old.FEATURE_META)
        self.loaded_through = None
    def __call__(self, day):
        day = pd.Timestamp(day).normalize()
        if day >= old.BOUNDARY or (self.loaded_through is not None and day <= self.loaded_through):
            raise PolicyInputBlocked("MONOTONE_PRE2026_METADATA_CUTOFF_REQUIRED")
        added = self.reader.read("prediction_features", old.FEATURE_META, date_field="signal_date",
            start=None if self.loaded_through is None else self.loaded_through+pd.Timedelta(days=1),
            stop=(day+pd.Timedelta(days=1) if day+pd.Timedelta(days=1)<old.BOUNDARY else None))
        self.history = added.copy() if self.history.empty else pd.concat([self.history, added], ignore_index=True)
        self.loaded_through = day
        # Full raw-date keys only: neither Open nor Close numerical values.
        raw = self.reader.read("raw_open_close", ("ticker", "trade_date"), date_field="trade_date", day=day)
        return old.current_pool(self.history, raw, self.days, _clock(day))


def discover_carry(groups, nodes, days, pool_provider):
    """Metadata-only quarterly support; a hard failure cannot become a winner."""
    if len(groups) != 12 or len(nodes) != 72:
        raise PolicyInputBlocked("EXACT_12_QUARTERS_72_RISK_SUPPORT_NODES_REQUIRED")
    schedules = producer.quarterly_schedule(days)
    if [{k:g[k] for k in ("as_of", "cutoff", "prior_date")} for g in groups] != schedules:
        raise PolicyInputBlocked("RISK_REFRESH_SCHEDULE_CHANGED")
    node_by_key = {(n["method"], n["as_of"]):n for n in nodes}
    if len(node_by_key) != 72:
        raise PolicyInputBlocked("DUPLICATE_RISK_SUPPORT_NODE")
    quarters = []
    for i, group in enumerate(groups):
        start = pd.Timestamp(group["as_of"])
        end = pd.Timestamp(groups[i+1]["as_of"]) if i+1 < len(groups) else pd.Timestamp("2026-01-01", tz="UTC")
        decision_days = [d for d in days if start <= _clock(d) < end]
        record = dict(as_of=group["as_of"], cutoff=group["cutoff"], next_refresh_as_of=end.isoformat(),
            planned_decision_days=len(decision_days), checked_decision_days=0, daily_keys=[], first_domain_block=None,
            required_full_requested_pool=True, check_basis="CURRENT_DECISION_CLOSE_METADATA_AVAILABLE_AT_CUTOFF")
        try:
            _quarter_group(group)
            for day in decision_days:
                result = compare_pool(group, pool_provider(day), _clock(day))
                record["daily_keys"].append(result)
                record["checked_decision_days"] += 1
                if result["block_reason"]:
                    record["first_domain_block"] = result
                    break
        except (KeyError, ValueError, TypeError) as error:
            record["first_domain_block"] = dict(block_reason=str(error), status="BLOCKED_METADATA_INPUT")
        record["remaining_days_not_read_after_input_block"] = (record["planned_decision_days"]-record["checked_decision_days"] if record["first_domain_block"] else 0)
        record["methods"] = {}
        for method in METHODS:
            node = node_by_key.get((method, group["as_of"]))
            reason = "MISSING_EXACT_RISK_SUPPORT_NODE" if node is None else node["metadata_block_reason"]
            if reason is None and record["first_domain_block"]:
                reason = record["first_domain_block"]["block_reason"]
            record["methods"][method] = dict(metadata_carry_eligible=reason is None, block_reason=reason,
                numerical_state_qualification="NOT_READ_IN_METADATA_PHASE",
                forecast_execution_event_support="NOT_ENTERED_AFTER_CARRY_BLOCK" if reason else "PENDING_EXACT_ACCOUNT_FORECAST_SOURCE_BINDING")
        quarters.append(record)
    paths = []
    for method in METHODS:
        failed = [q for q in quarters if not q["methods"][method]["metadata_carry_eligible"]]
        paths.append(dict(path_id="R4_SHR_ANCHOR_"+method, method=method,
            status="BLOCKED_SHR_POLICY_METADATA_CARRY" if failed else "CARRY_METADATA_MATCH_OTHER_SUPPORT_PENDING",
            full_carry_metadata_eligible=not failed, economic_replay_eligible=False,
            first_block=({"as_of":failed[0]["as_of"], "reason":failed[0]["methods"][method]["block_reason"]} if failed else None),
            strict_PIT_promotion_eligible=False, quote_qualified=False, certified_nav_qualified=False,
            new_fit_units=0, account_attempts=0))
    return dict(quarters=quarters, new_shr_paths=paths, numeric_reads=0, outcome_reads=0,
        account_attempts=0, new_fit_units=0, test2026_rows_read=0, no_outcome_based_support_shrink=True,
        per_quarter_early_stop_basis="FIRST_HARD_INPUT_IDENTITY_FAILURE; no economic outcome inspected")


def inherited_metadata(run, spec):
    """Reuse exact parent qualification metadata, never old economic ledgers."""
    parent = Path(spec["old_tuple_reference"]["path"]).parent
    ref = _ref(parent/"FAMILY_SUPPORT_QUALIFICATION_METADATA_R3.json")
    facts = old.read_json(ref["path"])
    boundary = facts["boundary"]
    for key in ("prediction_mu_sigma_values_read", "target_y_values_read", "Open_Close_ADV_values_read",
                "NAV_return_Sharpe_winner_values_read", "test2026_rows_read", "E_F_accesses", "new_fit_units", "account_attempts"):
        if boundary.get(key) != 0:
            raise PolicyInputBlocked("PARENT_QUALIFICATION_ONLY_METADATA_REQUIRED:"+key)
    for name, digest in facts["metadata_input_physical_sha256"].items():
        old._pin(parent/name, digest, "parent_support:"+name)
    source, _, source_ref = producer._source(run)
    if source_ref["path"] != str(parent/"FAMILY_SOURCE_INPUTS.json") or source_ref["sha256"] != facts["metadata_input_physical_sha256"]["FAMILY_SOURCE_INPUTS.json"]:
        raise PolicyInputBlocked("INHERITED_EXACT_SOURCE_INPUT_IDENTITY_REQUIRED")
    freeze_path = parent/"CONTROL_ACCOUNT_FREEZE.json"
    old._pin(freeze_path, spec["account_semantics_reference"]["sha256"], "parent_control_account")
    freeze = old.read_json(freeze_path)["freeze"]
    if freeze["source_sha256"] != account.source_pins() or freeze["one_way_friction_bps"] != 10:
        raise PolicyInputBlocked("EXACT_PARENT_ACCOUNT_POLICY_SOURCE_COST_REQUIRED")
    frozen_rows = {r["id"]:r for r in spec["original_main"]+spec["original_sensitivity"]}
    if len(frozen_rows) != 48 or len(facts["paths"]) != 48:
        raise PolicyInputBlocked("EXACT_ORIGINAL_48_PATHS_REQUIRED")
    reused, blocked, deferred = [], [], []
    for row in facts["paths"]:
        path = row["frozen_row"]
        if frozen_rows.get(path["id"]) != path:
            raise PolicyInputBlocked("ORIGINAL_TUPLE_MUTATED_OR_RENAMED")
        result = dict(path_id=path["id"], frozen_row=path, evidence_ref=ref,
            qualification_status=row["status"], strict_PIT_promotion_eligible=False,
            quote_qualified=False, certified_nav_qualified=False, new_fit_units=0, account_attempts=0)
        if row["status"] == "BLOCKED_FIRST_REQUIRED_FULLPOOL_RISK_REFRESH":
            result["first_required_risk"] = row["first_required_risk"]
            blocked.append(result)
        elif row["status"] == "EXISTING_10BPS_CONTROL_REUSE_CONDITIONALLY_QUALIFIED_UNCERTIFIED":
            result["control_qualification_ref"] = row["control_qualification_ref"]
            result["source_account_input_identity_exact_reuse"] = True
            result["input_sha256"] = freeze["input_sha256"]
            reused.append(result)
        else:
            deferred.append(result)
    if (len(reused), len(blocked), len(deferred)) != (2,42,4):
        raise PolicyInputBlocked("PARENT_2_CONTROL_42_RISK_4_COST_SCOPE_CHANGED")
    return dict(parent_support_ref=ref, reused_two_10bps_controls=reused,
        blocked_original_42_risk_paths=blocked, original_four_cost_controls_owner="ROOT_EXISTING_SCOPE_WRAPPER",
        original_four_cost_controls_metadata=deferred, source_inputs_ref=source_ref,
        original_risk_method_min30_unchanged=True, shr_states_not_substituted_for_original_risk_ids=True)


def p0_binding_metadata(run, spec):
    """Exact original P0 receipt/artifact custody only, no model/OOF body read."""
    parent=Path(spec["old_tuple_reference"]["path"]).parent
    reference=_ref(parent/"ALPHA_REUSE_RECEIPT.json")
    existing=old.read_json(reference["path"])
    p0=existing["P0"]
    roots=existing["roots"]
    def resolve_pin(descriptor, digest):
        if set(descriptor)!={"root","relative"} or descriptor["root"]!="B":
            raise PolicyInputBlocked("EXACT_EXISTING_P0_B_ROOT_REQUIRED")
        path=Path(roots["B"])/descriptor["relative"]
        old._safe_source(path)
        old._pin(path,digest,"p0_custody")
        return _ref(path)
    pins=[]
    for name in ("input_binding","initial_freeze"):
        pins.append(resolve_pin(p0[name]["path"],p0[name]["sha256"]))
    by_year={}
    for year in (2023,2024,2025):
        cutoff=f"{year}-01-01"
        pair=[r for r in p0["artifact_records"] if r["cutoff"]==cutoff]
        if len(pair)!=2 or {r["kind"] for r in pair}!={"five_day_HGB","five_day_calibration_HGB"} or not all(r["match"] is True for r in pair):
            raise PolicyInputBlocked("EXACT_EXISTING_P0_HGB_CALIBRATION_PAIR_REQUIRED")
        mature={r["maturity_max"] for r in pair}
        if len(mature)!=1 or pd.Timestamp(next(iter(mature)))>=pd.Timestamp(cutoff):
            raise PolicyInputBlocked("P0_PRE_CUTOFF_MATURITY_REQUIRED")
        exclusive=pd.Timestamp(cutoff).tz_localize("America/New_York").tz_convert("UTC")
        matured=_clock(pd.Timestamp(next(iter(mature))).normalize())
        record=dict(year=year,exclusive_fit_cutoff=exclusive.isoformat(),latest_matured_observation=matured.isoformat(),
            exclusive_clock_semantics="SOURCE_DATE_EXCLUSIVE_NEW_YORK_LOCAL_MIDNIGHT",
            maturity_clock_semantics="EXISTING_CALENDAR_SIGNAL_CLOSE_CLOCK",
            source_cutoff_date=cutoff,source_maturity_max=next(iter(mature)),source_receipt_ref=reference,
            fit_deserializations=0,OOF_values_read=0,new_fit_units=0)
        for row in pair:
            pins.append(resolve_pin(row["path"],row["actual_sha256"]))
        oof=[r for r in p0["initial_OOF"] if r["year"]==year]
        if len(oof)!=1 or oof[0]["matches_receipt"] is not True or pd.Timestamp(oof[0]["signal_max"])>=pd.Timestamp(f"{year+1}-01-01"):
            raise PolicyInputBlocked("EXACT_EXISTING_P0_ANNUAL_OOF_BOUNDARY_REQUIRED")
        pins.append(resolve_pin(oof[0]["path"],oof[0]["actual_sha256"]))
        pins.append(resolve_pin(oof[0]["receipt_path"],oof[0]["receipt_sha256"]))
        record["annual_OOF_ref"]=pins[-2]
        record["annual_OOF_receipt_ref"]=pins[-1]
        by_year[str(year)]=record
    return dict(receipt_ref=reference,P0=p0,annual_clock_bindings=by_year,physical_artifact_pins=pins,
        status="EXACT_EXISTING_P0_METADATA_CUSTODY_BOUND_NOT_NUMERIC_INFERENCE_QUALIFICATION",
        inherited_fit_units_counted_again=0,OOF_values_read=0,model_deserializations=0,new_fit_units=0,
        strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False)


def anchor_use_from_metadata(entry, state, *, next_refresh_as_of, p0_year_binding, source_authority_sha256):
    """Transport exact bank/state IDs and both P0 clocks, never rename risk IDs."""
    from scripts.research.a2.portfolio.shared_joint_adapter_r2 import risk_state_sha256
    if entry["method"] not in METHODS or entry["method"]!=state.method or entry["risk_state_id"]!=state.risk_state_id:
        raise PolicyInputBlocked("EXACT_NAMED_SHR_STATE_BINDING_REQUIRED")
    if entry.get("admission")!="CONDITIONAL_SOURCE_ONLY_EXACT_STATE" or tuple(entry["assets"])!=tuple(state.assets):
        raise PolicyInputBlocked("EXACT_SOURCE_ONLY_FULL_POOL_BANK_ENTRY_REQUIRED")
    return AnchorUse(method=state.method,risk_state_id=state.risk_state_id,risk_state_sha256=risk_state_sha256(state),
        as_of=entry["as_of"],cutoff=entry["cutoff"],next_refresh_as_of=str(next_refresh_as_of),
        pool_assets=tuple(entry["assets"]),pool_uids=tuple(entry["asset_uids"][a] for a in entry["assets"]),
        source_authority_sha256=source_authority_sha256,p0_receipt_sha256=p0_year_binding["source_receipt_ref"]["sha256"],
        p0_fit_cutoff=p0_year_binding["exclusive_fit_cutoff"],p0_matured_max=p0_year_binding["latest_matured_observation"],synthetic=False)


def support(run):
    run=Path(run)
    spec=_spec(run)
    source, _, _ = producer._source(run)
    risk_support=producer.read_support(run/producer.SUPPORT)
    if risk_support["specification_ref"] != _ref(run/producer.SPEC):
        raise PolicyInputBlocked("EXACT_RISK_SUPPORT_SPECIFICATION_REQUIRED")
    reader=old.ProjectedReader(source,phase="support")
    days,_=_calendar(reader.read("calendar",("trade_date",),date_field="trade_date").trade_date)
    result=discover_carry(risk_support["groups"],risk_support["nodes"],days,DailyMetadataPool(reader,days))
    binding=dict(schema="B_R4_POLICY_TECHNICAL_INPUT_BINDING_V1",research_id=ID,
        policy_spec_ref=_ref(run/SPEC),risk_spec_ref=_ref(run/producer.SPEC),risk_support_ref=_ref(run/producer.SUPPORT),
        source_authority_ref=_ref(run/"SOURCE_AUTHORITY.json"),P0_binding=p0_binding_metadata(run,spec),
        code_pins=[_ref(__file__),_ref(producer.__file__),_ref(account.__file__),
                   _ref(old.REPO/"scripts/research/a2/inference/joint_shr_anchor_policy_r4.py")],
        semantic_change=False,new_fit_units=0,numeric_reads=0,account_attempts=0,outcome_reads=0,test2026_rows_read=0)
    old.write(run,BINDING,binding,immutable=True)
    result.update(schema="B_R4_POLICY_QUALIFICATION_ONLY_SUPPORT_V1",research_id=ID,
        technical_binding_ref=_ref(run/BINDING),
        policy_spec_ref=_ref(run/SPEC),risk_support_ref=_ref(run/producer.SUPPORT),
        source_authority_ref=_ref(run/"SOURCE_AUTHORITY.json"),
        inherited=inherited_metadata(run,spec),projections=reader.audit,
        strict_PIT_promotion_eligible=False,quote_qualified=False,certified_nav_qualified=False)
    old.write(run,SUPPORT,result,immutable=True)
    return dict(status="POLICY_METADATA_SUPPORT_COMPLETE",support_ref=_ref(run/SUPPORT),
        blocked_shr_paths=sum(not p["full_carry_metadata_eligible"] for p in result["new_shr_paths"]),
        new_fit_units=0,account_attempts=0,numeric_reads=0,outcome_reads=0)


@dataclass(frozen=True)
class AnchorAccountFreeze(account.FrozenHistoryAccountFreeze):
    """Only path-id transport; all accounting and valuation stay with old owner."""
    anchor_path_id: str=""
    @property
    def path_ids(self):
        if self.anchor_path_id not in {"R4_SHR_ANCHOR_"+m for m in METHODS}:
            raise PolicyInputBlocked("ONLY_AUTHORISED_SHR_ACCOUNT_PATH")
        return (self.anchor_path_id,)


def run_anchor_account(run, market, raw_scores, *, event_inputs, uncertified_quality_only,
        freeze, expected_freeze_sha256, contract, input_provider, complete_support,
        expected_support_sha256, expected_matrix_sha256=None):
    """Dispatch one fully qualified anchor to unchanged policy/account owners.

    This API performs no data read, registration, support construction or fit.
    Caller must bind and freeze exact risk/P0/quote/event support before invoking.
    A metadata carry pass alone cannot activate an account.
    """
    if content_hash(complete_support)!=expected_support_sha256 or not isinstance(freeze,AnchorAccountFreeze):
        raise PolicyInputBlocked("EXACT_FROZEN_COMPLETE_ANCHOR_SUPPORT_REQUIRED")
    path=freeze.path_ids[0]
    true_fields=("full_carry_metadata_eligible","numerical_risk_state_qualified","P0_exact_oof_support_qualified",
                 "execution_quote_security_event_support_qualified","mechanism_account_input_coordinate_qualified")
    if (complete_support.get("research_id")!=ID or complete_support.get("path_id")!=path
            or any(complete_support.get(k) is not True for k in true_fields)
            or complete_support.get("strict_PIT_promotion_eligible") is not False
            or complete_support.get("quote_qualified") is not False
            or complete_support.get("certified_nav_qualified") is not False
            or complete_support.get("test2026_rows_read")!=0 or complete_support.get("source_authority_sha256")!=contract.source_authority_sha256
            or complete_support.get("matrix_sha256")!=contract.matrix_sha256
            or complete_support.get("account_freeze_sha256")!=expected_freeze_sha256):
        raise PolicyInputBlocked("ALL_ANCHOR_INPUT_SUPPORT_REQUIRED_BEFORE_ACCOUNT")
    if freeze.research_id!=ID or freeze.synthetic:
        raise PolicyInputBlocked("REGISTERED_REAL_R4_MECHANISM_ACCOUNT_REQUIRED")
    run=Path(run)
    matrix=guard(run,expected_matrix_sha256)
    if old.sha(run/"WHOLE_MATRIX_FREEZE.json")!=contract.matrix_sha256:
        raise PolicyInputBlocked("ANCHOR_CONTRACT_MATRIX_CHANGED")
    pinned={str(Path(p["path"]).resolve()):p["sha256"] for p in matrix.get("code_pins",())}
    for filename in (__file__,account.__file__,producer.__file__):
        if pinned.get(str(Path(filename).resolve()))!=old.sha(filename):
            raise PolicyInputBlocked("ACCOUNT_DISPATCH_CODE_NOT_IN_TOTAL_FREEZE")
    policy_spec=_spec(run)
    if policy_spec["scope_authorisation_ref"]["sha256"]!=contract.scope_authorisation_sha256:
        raise PolicyInputBlocked("ANCHOR_CONTRACT_SCOPE_AUTHORITY_CHANGED")
    if old.sha(run/"SOURCE_AUTHORITY.json")!=contract.source_authority_sha256:
        raise PolicyInputBlocked("ANCHOR_CONTRACT_SOURCE_AUTHORITY_CHANGED")
    events=dict(event_inputs)
    mask=np.asarray(uncertified_quality_only,bool)
    account._freeze_guard(freeze,expected_freeze_sha256,market,raw_scores,events,mask)
    before=account.input_digests(market,raw_scores,events,mask)
    policy=ShrAnchorPolicy(contract,contract.digest(),input_provider,mode="ACCOUNT_REPLAY")
    friction=dict(kind="FIXED_ADVERSE_OPEN_SLIPPAGE",one_way_bps=10,fee_bps=0,
        benchmark="NEXT_RAW_OPEN",authority="HYPOTHETICAL_RESEARCH_SCENARIO",scenario_id=ID+"::10bps")
    claim_path=run/"work"/("ANCHOR_ACCOUNT_ATTEMPT_"+path+".json")
    producer.assert_safe_output_path(claim_path,kind="backtest",paths=producer.resolve(old.REPO))
    claim_path.parent.mkdir(parents=True,exist_ok=True)
    descriptor=os.open(claim_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,"w",encoding="utf-8") as stream:
        json.dump(dict(path_id=path,reserved_account_attempts=1,fit_units=0,no_automatic_retry=True,
            account_freeze_sha256=expected_freeze_sha256,input_support_sha256=expected_support_sha256),stream)
        stream.flush();os.fsync(stream.fileno())
    replay=account.common.run_continuous_account(market,(path,),policy,dict(account.ACCOUNT),
        execution_friction=friction,**events)
    if before!=account.input_digests(market,raw_scores,events,mask):
        raise PolicyInputBlocked("SHARED_FROZEN_ACCOUNT_INPUT_MUTATION")
    qualification=account._qualify(replay,market,mask,freeze,{path:[]})
    # _qualify owns the economics. Replace only its generic controls label with
    # the exact policy-id binding; no numerical/account gate is changed here.
    replay.metadata["controls"]=[]
    replay.metadata["policy_paths"]=[path]
    replay.metadata["anchor_contract_sha256"]=contract.digest()
    replay.metadata["input_support_sha256"]=expected_support_sha256
    return account.FrozenHistoryMechanismResult(replay,qualification,expected_freeze_sha256,physical_account_replays=1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",required=True)
    parser.add_argument("--phase",choices=["support"],default="support")
    args=parser.parse_args()
    # Source/support discovery is zero-fit and can finish before whole-matrix
    # numerical activation. A future caller's account stage must invoke guard.
    with stage_writer(Path(args.run),"other"):
        result=support(args.run)
    print(json.dumps(old._json(result),allow_nan=False),flush=True)

if __name__=="__main__":
    main()



