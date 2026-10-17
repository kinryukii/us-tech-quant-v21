"""Thin R10 producer/consumer over the one shared risk implementation.

No reader, writer, controller, provider or account implementation lives here.
Root owns frozen admission, the durable weighted-unit reservation and persistence.
Metadata planning never reads return_value. Numeric estimation starts only after ACK.
"""
from dataclasses import asdict, replace
from pathlib import Path
import hashlib
import copy
import json
from types import FunctionType
import numpy as np
import pandas as pd
from . import joint_risk_estimators as joint
from . import short_history_risk_r4 as short
from .shared_risk_engine_r2 import (RiskInput, RiskState, META, COORDINATE,
    _calendar, _panel, _time, CUTOFF, SourceReceipt, SharedRiskEngine)
from .shared_risk_budget_r2 import StateBudget, StateCache, content_hash, LEARNED_KINDS
from scripts.research.a2.training.stateful_decision import _valid_sid
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2 import optimization as cvar_owner

CLASSICAL = ("DIAG", "SCOV", "LW", "OAS", "CONSTANT_CORR", "PCA", "FA", "GARCH", "GJR_GARCH")
SHORT = ("SHR_HP", "SHR_EB", "SHR_FACTOR", "SHR_CC")
HORIZONS = (3, 5, 10, 20)
FLAGS = ("strict_PIT_promotion_eligible", "account_qualified", "quote_authority_qualified",
         "certified_NAV_qualified", "source_account_authority_upgraded")
CAP = 220


def _sid(value):
    return _valid_sid(value) and not str(value).upper().startswith("A2_TICKER_")


def assemble_native(observations, *, sessions, assets, uids, asset_epochs,
                    source_receipt, identity_epoch, optional_shared_inputs=None):
    """Package caller-produced endpoints through the existing RiskInput schema.

    No endpoint/return construction lives here. The data owner has already bound
    per-security segments before projecting the composite physical source/domain.
    """
    assets=tuple(assets)
    columns=("security_segment_epoch","original_label_identity","quantity_multiplier",
             "aggregate_domain_bound","mechanism_coordinate_supported",
             "strict_endpoint_source_qualified","historical_available_at_bound")
    if (not isinstance(observations,pd.DataFrame) or not set(META+columns+("return_value",)).issubset(observations.columns)
            or set(uids)!=set(assets) or set(asset_epochs)!=set(assets) or any(not _sid(v) for v in uids.values())
            or source_receipt.identity_epoch!=identity_epoch):
        raise ValueError("NATIVE_DOMAIN_INPUT_PROOF_REQUIRED")
    frame=observations.loc[observations.asset.isin(assets)].copy()
    if (frame.empty or not frame.aggregate_domain_bound.map(lambda x:x is True or isinstance(x,np.bool_) and bool(x)).all()
            or not frame.mechanism_coordinate_supported.map(lambda x:isinstance(x,(bool,np.bool_)) and bool(x)).all()
            or not frame.strict_endpoint_source_qualified.map(lambda x:isinstance(x,(bool,np.bool_)) and not bool(x)).all()
            or not frame.historical_available_at_bound.map(lambda x:isinstance(x,(bool,np.bool_)) and not bool(x)).all()
            or not frame.uid.eq(frame.asset.map(uids)).all()
            or not frame.security_segment_epoch.eq(frame.asset.map(asset_epochs)).all()
            or not frame.identity_epoch.eq(identity_epoch).all()
            or not frame.source_identity.eq(source_receipt.source_identity).all()):
        raise ValueError("NATIVE_DOMAIN_PROVENANCE_OR_COORDINATE_MISMATCH")
    if not frame.original_label_identity.map(lambda x:isinstance(x,str) and bool(x)).all():
        raise ValueError("NATIVE_ORIGINAL_LABEL_IDENTITY_MISSING")
    optional=dict(optional_shared_inputs or {})
    if any(k not in {"qqq_observations","qqq_receipt","industry_mapping","industry_receipt"} for k in optional):
        raise ValueError("ONLY_EXISTING_SHARED_OPTIONAL_INPUTS")
    frame.attrs["r10_domain_binding"]=dict(assets=assets,uids=dict(uids),asset_epochs=dict(asset_epochs),
        identity_epoch=identity_epoch,source=source_receipt.cache_identity())
    return RiskInput(assets,sessions,frame,source_receipt,dict(uids),identity_epoch,**optional)


def reuse_admission(metadata, expected, *, decision_at):
    """Metadata exact whole-state applicability, never an economic/PIT authority."""
    keys=("risk_state_id","source_identity","source_cache_identity","assets","asset_uids",
          "identity_epoch","return_coordinate","horizon","as_of","cutoff")
    if any(k not in metadata or k not in expected or metadata[k]!=expected[k] for k in keys):
        raise ValueError("SHARED_STATE_EXACT_CONTEXT_MISMATCH")
    if (metadata.get("status") not in {"PASS_SYNTHETIC","PASS_FROZEN_HISTORY_MECHANISM"}
            or metadata["return_coordinate"]!=COORDINATE or metadata["horizon"] not in HORIZONS
            or not _time(metadata["cutoff"])<_time(metadata["as_of"])<=_time(decision_at)<CUTOFF
            or set(metadata["assets"])!=set(metadata["asset_uids"])
            or any(not _sid(v) for v in metadata["asset_uids"].values())):
        raise ValueError("SHARED_STATE_SOURCE_TIME_DOMAIN_BLOCKED")
    return dict(status="SHARED_EXACT_REUSE",verified=True,risk_state_id=metadata["risk_state_id"],
                expected_context_sha256=content_hash(expected),new_learned_units=0,
                **{k:False for k in FLAGS},**{"2026_locked":True})


def code_pins():
    paths = (__file__, joint.__file__, short.__file__, cvar_owner.__file__,
             Path(__file__).with_name("shared_risk_engine_r2.py"),
             Path(__file__).with_name("shared_risk_budget_r2.py"),
             Path(__file__).with_name("shared_risk_extensions_r2.py"),
             Path(__file__).parents[1]/"data"/"shared_risk_inputs_r3.py",
             Path(__file__).parents[1]/"retained"/"a2_pto_full_compat_20260928_r2"/"risk_models.py")
    return {str(Path(p)): hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}


def _seal(value):
    result = copy.deepcopy(value)
    result["plan_sha256"] = content_hash(result)
    return result


def _verify(plan):
    body = {k: v for k, v in plan.items() if k != "plan_sha256"}
    if content_hash(body) != plan.get("plan_sha256"):
        raise ValueError("RISK_PLAN_HASH_CHANGED")


def _supported(inputs, cutoff, horizon, support_metadata):
    """Use the original endpoint validator on unavailable-value placeholders."""
    if not isinstance(inputs, RiskInput):
        raise ValueError("EXISTING_RISK_INPUT_REQUIRED")
    if (set(inputs.asset_uids) != set(inputs.assets)
            or any(not _sid(v) for v in inputs.asset_uids.values())
            or len(set(inputs.asset_uids.values())) != len(inputs.assets)):
        raise ValueError("UNKNOWN_OR_AMBIGUOUS_SID")
    if inputs.source_receipt.identity_epoch != inputs.identity_epoch:
        raise ValueError("SOURCE_IDENTITY_EPOCH_MISMATCH")
    if not isinstance(support_metadata, pd.DataFrame) or not {"asset", "origin_at", "qualified"}.issubset(support_metadata):
        raise ValueError("SOURCE_SUPPORT_METADATA_REQUIRED")
    meta = inputs.observations.loc[:, list(META)].copy()
    clocks = ("origin_at", "entry_at", "endpoint_at", "matured_at", "available_at")
    for c in clocks:
        meta[c] = meta[c].map(_time)
    mask = meta.horizon.eq(horizon) & meta.asset.isin(inputs.assets)
    for c in clocks:
        mask &= meta[c].lt(cutoff) & meta[c].lt(CUTOFF)
    meta = meta.loc[mask]
    proof = support_metadata.loc[:, ["asset", "origin_at", "qualified"]].copy()
    proof["origin_at"] = proof.origin_at.map(_time)
    proof = proof.loc[proof.origin_at.lt(cutoff) & proof.asset.isin(inputs.assets)]
    if proof.duplicated(["asset", "origin_at"]).any():
        raise ValueError("DUPLICATE_SOURCE_SUPPORT")
    if not proof.qualified.map(lambda x: isinstance(x, (bool, np.bool_))).all():
        raise ValueError("LITERAL_BOOLEAN_SUPPORT_REQUIRED")
    meta = meta.merge(proof, on=["asset", "origin_at"], how="left", validate="one_to_one")
    if meta.qualified.isna().any():
        raise ValueError("SOURCE_SUPPORT_SLOT_MISSING")
    meta = meta.loc[meta.qualified.eq(True), list(META)]
    placeholder = meta.copy()
    placeholder["return_value"] = np.nan
    _panel(placeholder, inputs.assets, inputs.asset_uids, inputs.identity_epoch,
           inputs.source_receipt, inputs.sessions, cutoff, horizon)
    return meta


def _native_provenance(inputs,cutoff,horizon):
    columns=("security_segment_epoch","original_label_identity","quantity_multiplier",
             "aggregate_domain_bound","mechanism_coordinate_supported",
             "strict_endpoint_source_qualified","historical_available_at_bound")
    if not set(columns).issubset(inputs.observations.columns):
        return None
    meta=inputs.observations.loc[:,list(META+columns)].copy()
    for c in ("origin_at","entry_at","endpoint_at","matured_at","available_at"):
        meta[c]=meta[c].map(_time)
    mask=meta.asset.isin(inputs.assets)&meta.horizon.eq(horizon)
    for c in ("origin_at","entry_at","endpoint_at","matured_at","available_at"):
        mask &=meta[c].lt(cutoff)
    return content_hash(meta.loc[mask])


def audit(inputs, methods, *, horizon, as_of, support_metadata):
    """Metadata-only annual plan. All legal prior rows, no outcome cap or mining."""
    methods = tuple(methods)
    if not methods or len(set(methods)) != len(methods):
        raise ValueError("UNIQUE_FROZEN_METHODS_REQUIRED")
    if isinstance(horizon, bool) or horizon not in HORIZONS:
        raise ValueError("NATIVE_HORIZON_REQUIRED")
    if any(m not in CLASSICAL + SHORT + ("SEMI_SCOV",) for m in methods):
        raise ValueError("UNSCHEDULED_RISK_METHOD")
    if horizon != 5 and any(m not in {"LW", "DIAG"} for m in methods):
        raise ValueError("NATIVE_EXTRA_H_REFERENCE_ONLY")
    as_of, cutoff, sessions = _calendar(inputs, as_of, "R0")
    inputs.source_receipt.validate(cutoff)
    meta = _supported(inputs, cutoff, horizon, support_metadata)
    counts = meta.groupby("asset").size().reindex(inputs.assets, fill_value=0).astype(int).to_dict()
    primitive = tuple(m for m in methods if m not in SHORT)
    short_methods = tuple(m for m in methods if m in SHORT)
    blocks = []
    if primitive and any(n < 30 for n in counts.values()):
        blocks.append("BLOCKED_HISTORY:PRIMITIVE_REQUIRES_30_SUPPORTED_PRIOR_ROWS_PER_ASSET")
    if any(m in {"PCA", "FA"} for m in primitive) and len(inputs.assets) < 5:
        blocks.append("BLOCKED_INPUT:FIXED_FACTOR_COUNT_EXCEEDS_CALLER_MATRIX_DIMENSIONS")
    short_proof = None
    if short_methods:
        try:
            short_proof = short.qualify_metadata(inputs, as_of=as_of, support_metadata=support_metadata)
            for m in short_methods:
                blocks.extend(short_proof["method_block_reasons"][m])
        except (ValueError, KeyError, TypeError) as exc:
            blocks.append("BLOCKED_INPUT:" + str(exc))
    components = []
    regular = [m for m in primitive if m != "SEMI_SCOV"]
    if regular:
        components.append({"name": "shared_stock_preprocessing", "kind": "scaler", "units": 1})
    for m in regular:
        units = 2 if m in {"GARCH", "GJR_GARCH"} else 1
        components.append({"name": m, "kind": "covariance", "units": units})
    if "SEMI_SCOV" in primitive:
        components.extend([{"name": "semi_preprocessing", "kind": "scaler", "units": 1},
                           {"name": "centered_cov_min_return_zero", "kind": "covariance", "units": 1}])
    if short_methods:
        # Existing proof determines group-mean preprocessing; the rest is exact
        # shared dependency closure of the frozen four short-history recipes.
        count = 5 + int(bool(short_proof and short_proof["active_groups"]))
        hp = "SHR_HP" in short_methods or "SHR_CC" in short_methods
        count += 2 * int(hp) + int("SHR_CC" in short_methods)
        count += 2 * int("SHR_EB" in short_methods) + 2 * int("SHR_FACTOR" in short_methods)
        components.append({"name": "existing_H5_short_recipe_closure", "kind": "mixed", "units": count})
    units = sum(c["units"] for c in components)
    calendar = sessions[sessions <= as_of]
    return _seal(dict(schema="R10_SHARED_RISK_PLAN_R1", methods=methods, horizon=horizon,
        as_of=as_of.isoformat(), cutoff=cutoff.isoformat(), assets=inputs.assets,
        uids=dict(inputs.asset_uids), identity_epoch=inputs.identity_epoch,
        source=inputs.source_receipt.cache_identity(),
        assembly_binding=copy.deepcopy(inputs.observations.attrs.get("r10_domain_binding")),
        native_provenance_sha256=_native_provenance(inputs,cutoff,horizon),
        metadata_sha256=content_hash(meta), calendar_sha256=content_hash(calendar),
        supported_rows=counts, effective_independent_upper_bound={a:n//horizon for a,n in counts.items()},
        numeric_finiteness="UNKNOWN_NOT_READ", primitive_window="ALL_LEGAL_PRE_CUTOFF_ROWS",
        short_window="EXISTING_H5_LAST252_ORIGINS_RECIPE_UNCHANGED",
        short_metadata_proof=short_proof, components=components, required_units=units,
        hard_cap=CAP, block_reasons=blocks, status="BLOCKED" if blocks else "METADATA_READY",
        code_pins=code_pins(), **{k:False for k in FLAGS}, **{"2026_locked":True}))


def admission(plan, frozen_authorization):
    """No source qualification is inferred from scientific or document hashes."""
    _verify(plan)
    auth = frozen_authorization
    if (auth.get("frozen") is not True or auth.get("risk_fit_admitted") is not True
            or auth.get("plan_sha256") != plan["plan_sha256"]
            or auth.get("code_pins") != plan["code_pins"]
            or plan["code_pins"] != code_pins()
            or any(auth.get(k) is not False for k in FLAGS)
            or auth.get("2026_locked") is not True):
        raise ValueError("RISK_FROZEN_AUTHORIZATION_UNBOUND")
    remaining = auth.get("remaining_learned_units")
    if (type(remaining) is not int or not 0 <= remaining <= CAP
            or remaining < plan["required_units"]):
        raise ValueError("RISK_220_BUDGET_EXCEEDED")
    if plan["status"] != "METADATA_READY":
        raise ValueError("RISK_PLAN_INPUT_BLOCKED")
    return dict(status="ADMITTED_MECHANISM_ONLY", plan_sha256=plan["plan_sha256"],
                remaining_learned_units=remaining, **{k:False for k in FLAGS}, **{"2026_locked":True})


def _numeric_frame(inputs, meta, cutoff, horizon):
    # This function is called only after the durable whole-plan ACK.
    keys = meta.loc[:, ["asset", "origin_at", "horizon"]]
    values = inputs.observations.merge(keys, on=["asset", "origin_at", "horizon"], how="inner", validate="one_to_one")
    if not np.isfinite(pd.to_numeric(values.return_value, errors="raise").to_numpy(float)).all():
        raise ValueError("NONFINITE_REQUIRED_SOURCE_VALUE")
    return _panel(values, inputs.assets, inputs.asset_uids, inputs.identity_epoch,
                  inputs.source_receipt, inputs.sessions, cutoff, horizon)


def _make_state(method, inputs, plan, covariance, details, frame, dependencies):
    covariance, psd = joint.validate_covariance(covariance, regularize=False)
    condition = float(np.linalg.cond(covariance))
    if not np.isfinite(condition) or condition > 1e12:
        raise ValueError("ILL_CONDITIONED_RISK_STATE")
    covariance = np.array(covariance, copy=True); covariance.flags.writeable = False
    sigma = np.sqrt(np.diag(covariance)); sigma.flags.writeable = False
    observed = frame.count().astype(int).to_dict()
    coverage = {a:dict(observed=observed[a],uid=inputs.asset_uids[a],
                      identity_epoch=inputs.identity_epoch, mechanism_coordinate_supported=True)
                for a in inputs.assets}
    notes = dict(shared_owner="joint_risk_estimators", native_horizon=plan["horizon"],
                 risk_plan_sha256=plan["plan_sha256"], fixed_parameters=details, numeric=psd,
                 no_unknown_asset_fallback=True, scientific_retry=0,
                 source_clock="Explicit frozen-history assumption; not historical quote authority")
    identity = content_hash(dict(method=method,plan=plan["plan_sha256"],covariance=covariance,notes=notes))
    return RiskState(identity,_time(plan["as_of"]),_time(plan["cutoff"]),tuple(inputs.assets),
        inputs.source_receipt.source_identity,COORDINATE,plan["horizon"],covariance,sigma,coverage,
        {a:observed[a]//plan["horizon"] for a in inputs.assets},inputs.identity_epoch,
        condition,details.get("shrinkage"),None,None,None,None,None,(),asdict(inputs.source_receipt),
        "PASS_SYNTHETIC" if inputs.source_receipt.synthetic else "PASS_FROZEN_HISTORY_MECHANISM",
        method,tuple(dependencies),notes)


def _observed_garch(method, local, source, inputs, config, start, finish):
    """Original owner bytecode; private observer globals preserve parameter/LW order."""
    original = joint._estimate
    private = dict(original.__globals__)
    definition = private["_shared_garch_definition"]
    wolf = private["LedoitWolf"]

    def observed_definition():
        function, sha = definition()
        def observed_parameters(*args, **kwargs):
            token = start(method + ":parameters", "covariance", 1)
            try:
                value = function(*args, **kwargs)
                if not value[1].get("success") or not np.isfinite(value[0]).all():
                    finish(token, False)
                else:
                    finish(token, True)
                return value
            except Exception:
                finish(token, False)
                raise
        return observed_parameters, sha

    class ObservedWolf:
        def __init__(self, *args, **kwargs):
            self.inner = wolf(*args, **kwargs)
        def fit(self, *args, **kwargs):
            token = start(method + ":correlation_LW", "covariance", 1)
            try:
                self.inner.fit(*args, **kwargs)
            except Exception:
                finish(token, False)
                raise
            finish(token, True)
            return self.inner

    private.update(_shared_garch_definition=observed_definition, LedoitWolf=ObservedWolf)
    observer = FunctionType(original.__code__, private, original.__name__, original.__defaults__, original.__closure__)
    return observer(method, local, source.index, inputs.assets, None, None, config)


def estimate(inputs, plan, authorization, *, support_metadata, reserve_callback,
             on_component_start=None):
    """Root calls once. ACK reserves capacity; actual FIT_STARTED is separate.

    on_component_start receives a physical component immediately before the owner
    operation. When supplied it must return literal {ack: True}; it is the root's
    only durable actual-start ledger. No source/parser failure is called a fit.
    """
    admitted = admission(plan, authorization)
    current = audit(inputs, plan["methods"], horizon=plan["horizon"], as_of=plan["as_of"],support_metadata=support_metadata)
    if current != plan:
        raise ValueError("RISK_INPUT_METADATA_CHANGED")
    if not callable(reserve_callback):
        raise ValueError("DURABLE_RISK_RESERVATION_REQUIRED")
    if on_component_start is not None and not callable(on_component_start):
        raise ValueError("COMPONENT_START_CALLBACK_REQUIRED")
    ack = reserve_callback(dict(plan_sha256=plan["plan_sha256"],required_units=plan["required_units"],components=copy.deepcopy(plan["components"])))
    if (not isinstance(ack,dict) or ack.get("ack") is not True
            or ack.get("plan_sha256") != plan["plan_sha256"]
            or type(ack.get("reserved_units")) is not int
            or ack["reserved_units"] != plan["required_units"]
            or not isinstance(ack.get("reservation_id"),str) or not ack["reservation_id"]):
        raise ValueError("RISK_WHOLE_PLAN_ACK_REQUIRED_BEFORE_NUMERIC")
    receipt = dict(schema="R10_SHARED_RISK_PRODUCTION_RECEIPT_R1",plan_sha256=plan["plan_sha256"],
        reservation=ack,root_weighted_reserved_units=plan["required_units"],owner_actual_learned_units=0,
        attempted_learned_units=0,failed_started_units=0,unused_reserved_units=plan["required_units"],
        primitive_components=[],component_starts=[],states={},status="RUNNING",admission=admitted,
        scaler_fits=0,ML_estimator_fits=0,deterministic_transforms=0,failures=[],scientific_retry=0)

    def start(name, kind, units=1, key=None):
        if receipt["attempted_learned_units"] + units > plan["required_units"]:
            raise ValueError("ACTUAL_COMPONENTS_EXCEED_RESERVED_PLAN")
        event = dict(plan_sha256=plan["plan_sha256"],reservation_id=ack["reservation_id"],
                     name=name,kind=kind,units=units,status="FIT_STARTED",key=key)
        if on_component_start is not None:
            confirmation = on_component_start(copy.deepcopy(event))
            if not isinstance(confirmation,dict) or confirmation.get("ack") is not True:
                raise ValueError("ROOT_COMPONENT_START_ACK_REQUIRED")
        receipt["component_starts"].append(event)
        receipt["attempted_learned_units"] += units
        receipt["owner_actual_learned_units"] += units
        receipt["scaler_fits"] += units if kind == "scaler" else 0
        return event

    def finish(token, success):
        token["status"] = "SUCCEEDED" if success else "FAILED"

    def observe_cache(event):
        if event["kind"] not in LEARNED_KINDS:
            return
        # One old cache reservation covers two actual GARCH calls. Observe them
        # at the original parameter and correlation entry points instead.
        if event["name"] in {"primitive:GARCH", "primitive:GJR_GARCH"}:
            return
        start(event["name"],event["kind"],key=event["key"])

    budget = StateBudget(limit=plan["required_units"],reserve_callback=observe_cache)
    cutoff=_time(plan["cutoff"])
    cache=StateCache(budget,source_identity=inputs.source_receipt.cache_identity(),cutoff=cutoff.isoformat(),
        assets=inputs.assets,return_coordinate=COORDINATE,horizon=plan["horizon"],
        identity_epoch=dict(epoch=inputs.identity_epoch,uids=dict(inputs.asset_uids)),
        synthetic=inputs.source_receipt.synthetic,mechanism=inputs.source_receipt.mechanism)
    try:
        meta=_supported(inputs,cutoff,plan["horizon"],support_metadata)
        frame=_numeric_frame(inputs,meta,cutoff,plan["horizon"])
        params=dict(fit_cutoff=cutoff.isoformat(),return_unit=COORDINATE,
            return_horizon_sessions=plan["horizon"],source_id=content_hash(plan["source"]),
            information_set_id=content_hash(plan["identity_epoch"]))
        regular=[m for m in plan["methods"] if m in CLASSICAL]
        prepared=None
        if regular:
            names,coverage,prepared=cache.learn("scaler","stock_preprocessing",(frame,),
                lambda:joint._prepare(frame,{**joint.specs("LW"),**params}),parameters=params)
            if prepared is None or tuple(names[i] for i in prepared["positions"])!=tuple(inputs.assets):
                raise ValueError("NO_SUBSET_OR_UNKNOWN_ASSET_FALLBACK")
        for method in (m for m in plan["methods"] if m not in SHORT):
            try:
                local=prepared;source=frame;primitive=method
                if method=="SEMI_SCOV":
                    source=frame.clip(upper=0.);primitive="SCOV"
                    names,coverage,local=cache.learn("scaler","semi_preprocessing",(source,),
                        lambda:joint._prepare(source,{**joint.specs("SCOV"),**params}),parameters=params)
                    if local is None or tuple(names[i] for i in local["positions"])!=tuple(inputs.assets):
                        raise ValueError("NO_SEMI_SUBSET_FALLBACK")
                config={**joint.specs(primitive),**params}
                compute=(lambda primitive=primitive,local=local,source=source,config=config:
                    _observed_garch(primitive,local,source,inputs,config,start,finish)) if method in {"GARCH","GJR_GARCH"} else (
                    lambda primitive=primitive,local=local,source=source,config=config:
                    joint._estimate(primitive,local,source.index,inputs.assets,None,None,config))
                matrix,details,units=cache.learn("covariance","primitive:"+method,(local,source.index.tolist()),compute,parameters=config)
                expected=2 if method in {"GARCH","GJR_GARCH"} else 1
                if units!=expected:raise ValueError("OWNER_COMPONENT_COUNT_DRIFT")
                receipt["ML_estimator_fits"]+=units if method in {"LW","OAS","PCA","FA","GARCH","GJR_GARCH"} else 0
                receipt["primitive_components"].append(dict(method=method,actual_units=units))
                state=_make_state(method,inputs,plan,matrix,details,source,tuple(cache.usage_log))
                receipt["states"][method]=state
            except (ValueError,TypeError,KeyError,np.linalg.LinAlgError,RuntimeError) as exc:
                receipt["failures"].append(dict(method=method,type=type(exc).__name__,message=str(exc),scientific_retry=0))
        shorts=[m for m in plan["methods"] if m in SHORT]
        if shorts:
            shared_cache=short.make_cache(inputs,as_of=plan["as_of"],budget=budget)
            for method in shorts:
                try:
                    state=short.fit_risk(method,inputs,as_of=plan["as_of"],support_metadata=support_metadata,
                        cache=shared_cache,expected_qualification=plan["short_metadata_proof"])
                    if state.status not in {"PASS_SYNTHETIC","PASS_FROZEN_HISTORY_MECHANISM"}:
                        raise ValueError("SHORT_HISTORY_PRODUCTION_BLOCKED:"+str(state.notes.get("block_reason")))
                    receipt["states"][method]=state
                except (ValueError,TypeError,KeyError,np.linalg.LinAlgError,RuntimeError) as exc:
                    receipt["failures"].append(dict(method=method,type=type(exc).__name__,message=str(exc),scientific_retry=0))
        if not receipt["failures"] and receipt["attempted_learned_units"]!=plan["required_units"]:
            raise ValueError("PREOCCUPIED_OWNER_UNITS_MISMATCH")
        receipt["status"]=("COMPLETE_WITH_FAILED_DIRECTIONS" if receipt["states"] else "FAILED_NO_RETRY") if receipt["failures"] else "COMPLETE_MECHANISM_ONLY"
    except (ValueError,TypeError,KeyError,np.linalg.LinAlgError,RuntimeError) as exc:
        receipt["status"]="FAILED_NO_RETRY" if receipt["attempted_learned_units"] else "BLOCKED_INPUT"
        receipt["failures"].append(dict(type=type(exc).__name__,message=str(exc)))
    cache_status={e["key"]:e["status"] for e in budget.events}
    for event in receipt["component_starts"]:
        if event["key"] is not None:
            event["status"]=cache_status.get(event["key"],"FAILED")
    receipt["failed_started_units"]=sum(e["units"] for e in receipt["component_starts"] if e["status"]=="FAILED")
    receipt["unused_reserved_units"]=plan["required_units"]-receipt["attempted_learned_units"]
    receipt["logical_cache_learned_operations"]=budget.learned_total
    receipt["deterministic_transforms"]=budget.counts["deterministic_transform"]
    receipt["cache_receipt"]=budget.snapshot()
    receipt["budget_refund"]=False
    return receipt


def _state_matrix(state, assets, uids, decision_at, horizon):
    if (not isinstance(state,RiskState) or state.status not in {"PASS_SYNTHETIC","PASS_FROZEN_HISTORY_MECHANISM"}
            or not _time(state.cutoff)<_time(state.as_of)<=_time(decision_at)<CUTOFF
            or state.horizon!=horizon or state.return_coordinate!=COORDINATE):
        raise ValueError("RISK_STATE_TIME_HORIZON_OR_STATUS")
    if any(a not in state.assets or state.coverage.get(a,{}).get("uid")!=uids.get(a) for a in assets):
        raise ValueError("RISK_CONSUMER_SID_OR_DOMAIN_UNKNOWN")
    if (state.source_receipt.get("source_identity")!=state.source_identity
            or state.source_receipt.get("quote_qualified") is not False
            or state.source_receipt.get("strict_PIT_promotion_eligible") is not False):
        raise ValueError("RISK_SOURCE_RECEIPT_BINDING_OR_AUTHORITY")
    positions=[state.assets.index(a) for a in assets]
    matrix=np.asarray(state.covariance)[np.ix_(positions,positions)]
    matrix,_=joint.validate_covariance(matrix,regularize=False)
    condition=float(np.linalg.cond(matrix))
    if not np.isfinite(condition) or condition>1e12:raise ValueError("RISK_PROJECTION_CONDITION")
    return matrix,positions


def consumer_projection(states, representation, *, assets, uids, reference_assets,
                        decision_at, horizon=5, verified_state_refs):
    """Fixed equal-q numeric inference only; missing groups fail closed."""
    assets=tuple(assets);reference_assets=tuple(reference_assets)
    if (not assets or len(set(assets))!=len(assets) or set(uids)!=set(assets)
            or not reference_assets or len(set(reference_assets))!=len(reference_assets)
            or not set(reference_assets).issubset(assets)):
        raise ValueError("EXACT_REFERENCE_DOMAIN_REQUIRED")
    if any(not _sid(v) for v in uids.values()) or not _time(decision_at)<CUTOFF or horizon not in HORIZONS:
        raise ValueError("CONSUMER_SID_TIME_HORIZON_INVALID")
    if representation=="R0":
        return dict(features={},reference_weights={a:1/len(reference_assets) for a in reference_assets},
                    diagnostics={"calibration":"SEPARATE_MATURED_DIAGNOSTIC_NOT_AN_INPUT"},**{k:False for k in FLAGS},**{"2026_locked":True})
    required={"R1":("DIAG",),"R2":("LW","OAS","CONSTANT_CORR"),"R3":("RB","RH"),
              "R4":("RT",),"R5":("RR",),"R6":("RU","RE")}
    if representation=="R7":
        parts=[consumer_projection(states,r,assets=assets,uids=uids,reference_assets=reference_assets,
               decision_at=decision_at,horizon=horizon,verified_state_refs=verified_state_refs)
               for r in ("R2","R3","R4","R5","R6")]
        matrices=[p["reference_covariance"] for p in parts]
        matrix=sum(matrices)/5
        return _projection_result(matrix,assets,reference_assets,{"fixed_equal_group_count":5,
            "group_weights":{r:.2 for r in ("R2","R3","R4","R5","R6")},
            "group_features":{r:p["features"] for r,p in zip(("R2","R3","R4","R5","R6"),parts)}})
    if representation not in required:raise ValueError("FROZEN_REPRESENTATION_REQUIRED")
    factor_view=None
    if representation=="R3":
        def legal_factor(method):
            state=states.get(method);ref=verified_state_refs.get(method,{})
            if (not isinstance(state,RiskState) or ref.get("verified") is not True
                    or ref.get("risk_state_id")!=state.risk_state_id):return False
            try:_state_matrix(state,assets,uids,decision_at,horizon)
            except (ValueError,TypeError,KeyError,np.linalg.LinAlgError):return False
            return True
        if all(legal_factor(m) for m in ("RB","RH")):
            required["R3"]=("RB","RH");factor_view="QQQ_FF48_SHARED_WHOLE_STATES"
        elif legal_factor("PCA"):
            required["R3"]=("PCA",);factor_view="PCA_SHARED_WHOLE_STATE"
        else:raise ValueError("R3_PREDECLARED_FACTOR_VIEW_UNAVAILABLE")
    matrices=[];extra={} if factor_view is None else {"factor_view":factor_view}
    for method in required[representation]:
        state=states.get(method);ref=verified_state_refs.get(method,{})
        if (not isinstance(state,RiskState) or ref.get("verified") is not True
                or ref.get("risk_state_id")!=state.risk_state_id):
            raise ValueError("VERIFIED_WHOLE_STATE_REFERENCE_REQUIRED")
        matrix,pos=_state_matrix(state,assets,uids,decision_at,horizon);matrices.append(matrix)
        extra[method+"_observed_coverage"]={a:state.coverage[a] for a in assets}
        extra[method+"_effective_sample_size"]=state.effective_sample_size
        extra[method+"_shrinkage"]=state.shrinkage_intensity
        if method=="RB":extra["qqq_beta"]=np.asarray(state.qqq_relative_state["beta"])[pos]
        if method=="RH":extra["pooled_specific_variance"]=np.asarray(state.qqq_relative_state["pooled_specific_variance"])[pos]
        if method=="RT":
            extra["downside_variance"]=np.diag(np.asarray(state.downside_state["downside_second_moment"])[np.ix_(pos,pos)])
            scenarios=np.asarray(state.downside_state["scenario_returns"])[:,pos]
            if tuple(state.downside_state["scenario_assets"])!=state.assets or not np.isfinite(scenarios).all():
                raise ValueError("MATURED_CVAR_SCENARIO_PROOF_REQUIRED")
            q=np.asarray([1/len(reference_assets) if a in reference_assets else 0. for a in assets])
            cvar,gradient,eta=cvar_owner._smooth_cvar(q[None,:],scenarios[None,:,:])
            downside=np.asarray(state.downside_state["downside_second_moment"])[np.ix_(pos,pos)]
            extra.update(portfolio_downside_sigma=float(np.sqrt(max(q@downside@q,0.))),
                         fixed_q_smooth_CVaR=float(cvar[0]),stock_CVaR_gradient=gradient[0],
                         CVaR_alpha=cvar_owner.SPEC["cvar_alpha"],CVaR_eta=float(eta[0]))
        if method=="RR":
            extra["active_regime"]=state.regime_state["active_regime"]
            extra["regime_volatility"]=state.regime_state["current_volatility"]
        if method=="RU":extra["jackknife_sigma_SE"]=np.asarray(state.estimation_uncertainty["marginal_sigma_uncertainty"])[pos]
        if method=="RE":extra["covariance_disagreement"]=np.diag(np.asarray(state.model_disagreement["disagreement_diagonal"])[np.ix_(pos,pos)])
    return _projection_result(sum(matrices)/len(matrices),assets,reference_assets,extra)


def _projection_result(matrix,assets,reference_assets,extra):
    matrix,_=joint.validate_covariance(matrix,regularize=False)
    condition=float(np.linalg.cond(matrix))
    if not np.isfinite(condition) or condition>1e12:raise ValueError("AGGREGATE_RISK_CONDITION")
    q=np.asarray([1/len(reference_assets) if a in reference_assets else 0. for a in assets])
    sigma=float(np.sqrt(max(q@matrix@q,0.)));marginal=2*matrix@q
    marginal_sigma=np.sqrt(np.diag(matrix))
    corr=(matrix@q)/(marginal_sigma*sigma+1e-12)
    return dict(features=dict(stock_sigma=marginal_sigma,portfolio_sigma=sigma,portfolio_correlation=corr,
                marginal_variance=marginal,normalized_marginal_risk=marginal/(2*sigma+1e-12),**extra),
                reference_weights=dict(zip(assets,q.tolist())),reference_covariance=matrix,
                diagnostics=dict(PSD=True,condition_number=float(np.linalg.cond(matrix)),predicted_portfolio_sigma=sigma,
                                 calibration="SEPARATE_MATURED_DIAGNOSTIC_NOT_AN_INPUT"),
                **{k:False for k in FLAGS},**{"2026_locked":True})


def replacement_risk_delta(projection,entrant,incumbent):
    """Fixed return-unit coordinate; no penalty lambda or q learning."""
    assets=tuple(projection["reference_weights"])
    marginal=np.asarray(projection["features"]["marginal_variance"])
    sigma=projection["diagnostics"]["predicted_portfolio_sigma"]
    return float((marginal[assets.index(entrant)]-marginal[assets.index(incumbent)])/(2*sigma+1e-12))


STUDY_SCHEMA="R10_SHARED_RISK_STUDY_SPEC_R1"
SHARED_DIRECTIONS=("R0","RD","RB","RH","RT","RR","RU","RE")


def _file_sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle,"sha256").hexdigest()


R3_REPAIR_OLD_ADAPTER_SHA="cef53a33e918003a33c9514ad80bf90d41668909c8851d9e953d9f8873467931"
R3_REPAIR_HUMAN_REQUEST_SHA="b21c051fd55475e02949cbbf76887359c22de65cbf4b466af7a9220b36ccf351"
R3_REPAIR_PARENT_DESIGN_SHA="59126f1d0e42716f4558122556338d5038bf57a6a65a22f465c930c0392b3cb7"


def _reviewed_adapter_repair(spec,receipt):
    old=spec.get("code_pins");current=code_pins()
    if old==current:return True
    adapter_path=str(Path(__file__))
    if not isinstance(old,dict) or set(old)!=set(current):return False
    changed=[key for key in old if old[key]!=current[key]]
    if changed!=[adapter_path] or old[adapter_path]!=R3_REPAIR_OLD_ADAPTER_SHA:return False
    if not isinstance(receipt,dict):return False
    return (receipt.get("schema")=="R10_R3_PCA_CONSUMER_ENGINEERING_REPAIR_R1"
        and receipt.get("approved") is True and receipt.get("reviewed") is True
        and receipt.get("old_adapter_sha256")==R3_REPAIR_OLD_ADAPTER_SHA
        and receipt.get("new_adapter_sha256")==current[adapter_path]
        and receipt.get("human_request_sha256")==R3_REPAIR_HUMAN_REQUEST_SHA
        and receipt.get("parent_design_sha256")==R3_REPAIR_PARENT_DESIGN_SHA
        and receipt.get("old_code_pins")==old and receipt.get("new_code_pins")==current
        and type(receipt.get("risk_fit_started_before_repair")) is int
        and receipt["risk_fit_started_before_repair"]==0
        and receipt.get("repair_scope")=="PREDECLARED_R3_FACTOR_PCA_CONSUMER_OMISSION_ONLY"
        and receipt.get("scientific_target_changed") is False
        and receipt.get("budget_changed") is False
        and receipt.get("source_authority_activated") is False
        and receipt.get("2026_locked") is True)


def _check_study_spec(spec, engineering_repair_receipt=None):
    _verify(spec)
    if (spec.get("schema")!=STUDY_SCHEMA or not _reviewed_adapter_repair(spec,engineering_repair_receipt)
            or spec.get("max_risk_learned_units")!=CAP
            or spec.get("max_scheduled_learned_units")>CAP
            or any(spec.get(k) is not False for k in FLAGS)
            or spec.get("2026_locked") is not True):
        raise ValueError("EXACT_FROZEN_RISK_STUDY_SPEC_REQUIRED")


def _shared_bank(spec):
    """Return frozen bank metadata only. Numeric joblib loads are lazy and guarded."""
    ref=spec["shared_bank_manifest"]
    if _file_sha(ref["path"])!=ref["sha256"]:
        raise ValueError("SHARED_RISK_BANK_MANIFEST_CHANGED")
    body=json.loads(Path(ref["path"]).read_text(encoding="utf-8"))
    white={r["risk_state_id"]:r for r in spec["shared_state_whitelist"]}
    rows=[]
    for record in body["states"]:
        pin=white.get(record["risk_state_id"])
        if (pin is None or content_hash(record)!=pin["manifest_record_sha256"]
                or record.get("reusable") is not True or record.get("exact_reuse_only") is not True
                or record.get("automatic_refit") is not False):
            raise ValueError("SHARED_STATE_WHITELIST_CHANGED")
        rows.append(record)
    if len(rows)!=len(white):raise ValueError("SHARED_STATE_WHITELIST_COUNT_CHANGED")
    return rows


def _load_bank_state(record):
    """Only the accepted, physical-SHA-bound whole risk artifact is deserialized."""
    import joblib
    path=Path(record["artifact"]["path"])
    if path.suffix!=".joblib" or path.parent.name!="risk" or path.parent.parent.name!="models":
        raise ValueError("RISK_ARTIFACT_ONLY_READER")
    if _file_sha(path)!=record["artifact"]["sha256"]:
        raise ValueError("SHARED_RISK_ARTIFACT_SHA_CHANGED")
    source=record["source_contract"]
    if _file_sha(source["path"])!=source["sha256"]:
        raise ValueError("ORIGINAL_SHARED_SOURCE_CONTRACT_CHANGED")
    state=joblib.load(path)
    if (not isinstance(state,RiskState) or state.risk_state_id!=record["risk_state_id"]
            or state.method!=record["method"] or tuple(state.assets)!=tuple(record["assets"])
            or state.status!=record["original_status"]
            or any(state.coverage[a].get("uid")!=record["asset_uids"][a] for a in state.assets)
            or state.source_receipt.get("scientific_contract_sha256")!=source["sha256"]):
        raise ValueError("SHARED_WHOLE_STATE_IDENTITY_CHANGED")
    return state


def _real_native_inputs(bundle,spec):
    """Root-permitted reader + existing endpoint owner; no second parser/CA engine."""
    from scripts.research.a2.training import stateful_mechanism_inputs as source_owner
    from scripts.research.a2.data.shared_risk_inputs_r3 import _clock
    reader=bundle.reader
    cal=reader.calendar
    keys=pd.concat([reader.train_flags[["signal_date","ticker","security_id"]],
                    reader.pred_flags[["signal_date","ticker","security_id"]]],ignore_index=True).drop_duplicates()
    conflict=keys.duplicated(["signal_date","ticker"],keep=False)
    conflict_keys=keys.loc[conflict,["signal_date","ticker"]].drop_duplicates()
    keys=keys.loc[~conflict & keys.security_id.map(_sid) & keys.signal_date.isin(cal)].sort_values(["ticker","signal_date"])
    raw=reader.read("raw_market_prices",["trade_date","ticker","open"],[("trade_date","<",source_owner.BOUNDARY)])
    events,event_window=source_owner.load_event_owner(bundle.source_manifest["metadata_pins"])
    packets={}
    for h in HORIZONS:
        plan=source_owner.native_endpoint_plan(keys,cal,h,keys,raw[["trade_date","ticker"]],events,event_window,
                         "R10_NATIVE_RISK_HISTORY_H"+str(h))
        packets[h]=source_owner.native_labels(plan,raw)
    result={};domain_receipts=[]
    for year in spec["years"]:
        first=cal[cal.year==year][0];as_of=_clock(first)
        closecal=pd.DatetimeIndex([_clock(d) for d in cal]);cutoff=closecal[closecal.get_loc(as_of)-1]
        prior=packets[5].loc[packets[5].signal_date.lt(first)]
        if prior.empty:
            domain_receipts.append(dict(year=year,status="BLOCKED_HISTORY",reason="NO_PRE_ASOF_SID_ENDPOINT_HISTORY"));continue
        current=prior.sort_values(["ticker","signal_date"]).groupby("ticker",sort=True).tail(1)
        uids=dict(zip(current.ticker,current.security_id));epochs=dict(zip(current.ticker,current.identity_epoch))
        for h in HORIZONS:
            packet=packets[h]
            pre=(packet.signal_date.lt(first)&packet.label_end_date.lt(first)&packet.label_mature_date.lt(first)
                 &packet.identity_epoch.eq(packet.ticker.map(epochs)))
            legal=pre & packet.mechanism_coordinate_supported.eq(True)
            counts=packet.loc[legal].groupby("ticker").size()
            for role,minimum in (("PRIMITIVE",30),("SHORT",10)):
                if role=="SHORT" and h!=5:continue
                names=tuple(sorted(a for a in uids if counts.get(a,0)>=minimum))
                if not names:
                    domain_receipts.append(dict(year=year,horizon=h,role=role,status="BLOCKED_HISTORY",reason="NO_METADATA_SUPPORTED_DOMAIN"));continue
                selected=packet.loc[pre & packet.ticker.isin(names)].copy()
                bad=selected.mechanism_coordinate_supported.eq(True)&~selected.label_qualified.eq(True)
                if bad.any():
                    domain_receipts.append(dict(year=year,horizon=h,role=role,status="BLOCKED_INPUT",reason="SUPPORTED_ENDPOINT_NUMERIC_VALUE_MISSING",bad_rows=int(bad.sum())));continue
                local_uids={a:uids[a] for a in names};local_epochs={a:epochs[a] for a in names}
                epoch="R10_NATIVE_DOMAIN:"+content_hash(dict(year=year,role=role,uids=local_uids,epochs=local_epochs))
                source_id="R10_NATIVE_RISK_STOCK:"+str(year)+":"+role
                observed=source_owner.native_risk_observations(selected,domain_epoch=epoch,
                               composite_source_identity=source_id,asset_epochs=local_epochs)
                physical=content_hash(dict(raw=reader.records["raw_market_prices"]["sha256"],
                    metadata=bundle.source_manifest["source_hashes"],projection=content_hash(keys.loc[keys.signal_date.lt(first)&keys.ticker.isin(names)]),epochs=local_epochs))
                source=SourceReceipt(source_id,"R10_FROZEN_NATIVE_ENDPOINTS_V1",physical,_clock(max(cal[0],raw.trade_date.min())),
                    synthetic=False,status="FROZEN_HISTORY_MECHANISM_SOURCE_BOUND",identity_epoch=epoch,
                    mechanism=True,scientific_contract_identity="A_FROZEN_HISTORY_STATEFUL_MECHANISM_RESEARCH_ONLY",
                    scientific_contract_sha256=reader.permit.design_sha256,
                    actual_snapshot_timestamp=pd.Timestamp(reader.records["raw_market_prices"]["file_fingerprint"]["mtime_ns"],unit="ns",tz="UTC"),observation_time_assumed=True)
                inp=assemble_native(observed,sessions=closecal,assets=names,uids=local_uids,
                    asset_epochs=local_epochs,source_receipt=source,identity_epoch=epoch)
                proof=observed[["asset","origin_at"]].copy();proof["qualified"]=True
                result[(year,h,role)]=(inp,proof,as_of)
                domain_receipts.append(dict(year=year,horizon=h,role=role,status="METADATA_SUPPORTED_COMPONENT",
                     assets=names,asset_uids=local_uids,asset_epochs=local_epochs,source_identity=source.cache_identity(),
                     domain_identity=epoch,minimum_metadata_supported_rows=minimum,cutoff=cutoff.isoformat(),
                     omitted_from_component=tuple(sorted(set(uids)-set(names))),strict_PIT_promotion_eligible=False))
    # RM consumes actual endpoint observations at four horizons, while its old
    # shared estimator still returns an explicitly labelled H5 time-scale proxy.
    for key,(inp,proof,asof) in list(result.items()):
        year,h,role=key
        if h!=5 or role!="PRIMITIVE":continue
        other=[]
        epochs=inp.observations.attrs["r10_domain_binding"]["asset_epochs"]
        first=cal[cal.year==year][0]
        for horizon in (3,10,20):
            packet=packets[horizon]
            selected=packet.loc[packet.signal_date.lt(first)&packet.label_end_date.lt(first)&packet.label_mature_date.lt(first)&packet.ticker.isin(inp.assets)]
            other.append(source_owner.native_risk_observations(selected,domain_epoch=inp.identity_epoch,
                composite_source_identity=inp.source_receipt.source_identity,asset_epochs=epochs))
        attrs=copy.deepcopy(inp.observations.attrs)
        combined=pd.concat([inp.observations,*other],ignore_index=True)
        combined.attrs=attrs
        result[key]=(replace(inp,observations=combined),proof,asof)
    return result,domain_receipts,dict(conflicting_sid_keys=len(conflict_keys),
        auxiliary_sources="NO_INDEPENDENT_QQQ_OR_FF48_RECEIPT_IN_R10_INPUT_MANIFEST",
        regime_probability="BLOCKED_INPUT:RR_ONLY_ACTIVE_REGIME_AND_CURRENT_VOLATILITY_NOT_P_HIGH_VOL")


def _shared_produce(inputs,as_of,spec,reserve_callback,on_component_start):
    """The old shared engine owns every direction and subfit. Root owns starts."""
    plan=_seal(dict(schema="R10_SHARED_DIRECTION_PLAN_R1",as_of=_time(as_of).isoformat(),
        source=inputs.source_receipt.cache_identity(),assets=inputs.assets,uids=dict(inputs.asset_uids),
        methods=SHARED_DIRECTIONS,required_units=spec["shared_direction_max_units_per_year"],
        code_pins=code_pins(),component_budget="EXISTING_SHARED_CACHE_DEPENDENCY_CLOSURE"))
    payload=dict(plan_sha256=plan["plan_sha256"],required_units=plan["required_units"],components=[{"name":"SHARED9_CLOSURE","units":plan["required_units"]}])
    ack=reserve_callback(payload)
    if (not isinstance(ack,dict) or ack.get("ack") is not True or ack.get("plan_sha256")!=plan["plan_sha256"]
            or ack.get("reserved_units")!=plan["required_units"] or type(ack.get("reserved_units")) is not int):
        raise ValueError("SHARED_DIRECTION_RESERVATION_ACK_REQUIRED")
    starts=[]
    def observer(event):
        if event["kind"] in LEARNED_KINDS:
            record=dict(plan_sha256=plan["plan_sha256"],reservation_id=ack["reservation_id"],name=event["name"],kind=event["kind"],units=1,key=event["key"],status="FIT_STARTED")
            response=on_component_start(record)
            if not isinstance(response,dict) or response.get("ack") is not True:raise ValueError("ROOT_COMPONENT_START_ACK_REQUIRED")
            starts.append(record)
    budget=StateBudget(limit=plan["required_units"],reserve_callback=observer)
    engine=SharedRiskEngine(budget=budget)
    states={};blocked=[]
    for method in SHARED_DIRECTIONS:
        state=engine.fit(method,inputs,as_of=as_of)
        if state.status in {"PASS_SYNTHETIC","PASS_FROZEN_HISTORY_MECHANISM"}:states[method]=state
        else:blocked.append(dict(method=method,status="BLOCKED_SOURCE_OR_HISTORY",reason=state.notes.get("block_reason"),physical_dependency_ids=state.fit_dependency_ids))
    bykey={e["key"]:e["status"] for e in budget.events}
    for e in starts:e["status"]=bykey[e["key"]]
    blocked.append(dict(method="RM",status="NOT_SCHEDULED_NEW_SCALED_PROXY",reason="EXISTING_RM_H5_TIME_SCALE_APPROX_ONLY;NATIVE_H3_H5_H10_H20_DIAG_LW_ALREADY_SCHEDULED"))
    return dict(plan=plan,states=states,blocked=blocked,attempted_learned_units=len(starts),
        failed_started_units=sum(e["status"]=="FAILED" for e in starts),unused_reserved_units=plan["required_units"]-len(starts),
        component_starts=starts,cache_receipt=budget.snapshot(),RM_coordinate="H5_TIME_SCALE_APPROX_DIAGNOSTIC_ONLY_NOT_NATIVE_H3_H10_H20")


def produce_study_risk(bundle,frozen_design,*,reserve_callback,on_component_start,
                       synthetic_inputs=None,projection_requests=None,engineering_repair_receipt=None):
    """No-IO-output execution helper invoked only by the root's unique R10 writer.

    Numeric input reads and risk-only loads occur after an already frozen root
    ReadPermit. Returns the shared owner's state objects for root persistence;
    never creates a run, fit ledger, state file or account. Synthetic tests supply
    generated RiskInput dictionaries and skip the real reader entirely.
    """
    spec=frozen_design.get("risk_study_spec")
    # The original root executor supplies no new keyword. Read the one reviewed
    # metadata receipt only at the real production entry point, never at import.
    if engineering_repair_receipt is None and synthetic_inputs is None:
        receipt_path=Path("D:/us-tech-quant-results/_maintenance/V24_A_STATEFUL_ACTION_RISK_FULL_BREADTH_R10/R10_R3_PCA_CONSUMER_ENGINEERING_REPAIR.json")
        if receipt_path.is_file():
            if receipt_path.stat().st_size>65536:raise ValueError("COMPACT_SINGLE_ENGINEERING_RECEIPT_REQUIRED")
            engineering_repair_receipt=json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(spec,dict):raise ValueError("FROZEN_RISK_STUDY_SPEC_REQUIRED")
    _check_study_spec(spec,engineering_repair_receipt)
    if not callable(reserve_callback) or not callable(on_component_start):raise ValueError("UNIQUE_ROOT_LEDGER_CALLBACKS_REQUIRED")
    if synthetic_inputs is None:
        if getattr(getattr(bundle,"reader",None),"permit",None) is None:raise ValueError("ROOT_FROZEN_READ_PERMIT_REQUIRED")
        frozen=json.loads(Path(bundle.reader.permit.design_path).read_text(encoding="utf-8"))
        if frozen!=frozen_design or _file_sha(bundle.reader.permit.design_path)!=bundle.reader.permit.design_sha256:
            raise ValueError("RISK_ROOT_DESIGN_CHANGED")
        bank=_shared_bank(spec)
        native,domains,source_notes=_real_native_inputs(bundle,spec)
    else:
        if any(not v[0].source_receipt.synthetic for v in synthetic_inputs.values()):raise ValueError("GENERATED_SYNTHETIC_INPUTS_REQUIRED")
        native=synthetic_inputs;domains=[];source_notes={"synthetic":True};bank=[]
    produced=[];receipts=[];blocks=[]
    for year in spec["years"]:
        for h,role in ((5,"PRIMITIVE"),(3,"PRIMITIVE"),(10,"PRIMITIVE"),(20,"PRIMITIVE"),(5,"SHORT")):
            key=(year,h,role)
            if key not in native:
                blocks.append(dict(year=year,horizon=h,role=role,status="BLOCKED_INPUT_HISTORY"));continue
            inp,proof,asof=native[key]
            methods=SHORT if role=="SHORT" else CLASSICAL+("SEMI_SCOV",) if h==5 else ("DIAG","LW")
            plan=audit(inp,methods,horizon=h,as_of=asof,support_metadata=proof)
            if plan["status"]!="METADATA_READY":
                blocks.append(dict(year=year,horizon=h,role=role,status="BLOCKED_INPUT",reasons=plan["block_reasons"]));continue
            auth=dict(frozen=True,risk_fit_admitted=True,plan_sha256=plan["plan_sha256"],code_pins=plan["code_pins"],remaining_learned_units=CAP,**{k:False for k in FLAGS},**{"2026_locked":True})
            receipt=estimate(inp,plan,auth,support_metadata=proof,reserve_callback=reserve_callback,on_component_start=on_component_start)
            receipts.append(receipt)
            produced.extend(receipt["states"].values())
            if h==5 and role=="PRIMITIVE":
                direction=_shared_produce(inp,asof,spec,reserve_callback,on_component_start)
                receipts.append(direction);produced.extend(direction["states"].values());blocks.extend(direction["blocked"])
    requests=projection_requests
    if requests is None:
        if synthetic_inputs is not None:requests=[]
        else:
            from scripts.research.a2.data.shared_risk_inputs_r3 import _clock
            state=bundle.frames.state
            requests=[]
            rawflags=bundle.reader.pred_flags.loc[bundle.reader.pred_flags.is_raw_top20.eq(True)]
            rawdays={day:group for day,group in rawflags.groupby("signal_date",sort=True)}
            for day,group in state.groupby("signal_date",sort=True):
                if group.ticker.duplicated().any():raise ValueError("A_PROXY_STATE_SID_CONFLICT")
                raw=rawdays.get(day)
                if raw is None:continue
                mapping=pd.concat([group[["ticker","security_id"]],raw[["ticker","security_id"]]]).drop_duplicates()
                if mapping.ticker.duplicated().any():raise ValueError("A_RAW20_COHORT_SID_CONFLICT")
                assets=tuple(sorted(mapping.ticker));uids=dict(zip(mapping.ticker,mapping.security_id))
                raw_names=tuple(raw.ticker)
                incumbent=tuple(group.loc[group.entrant.eq(0),"ticker"])
                for cohort,reference in (("FROZEN_RAW20_EQUAL",raw_names),("A_PROXY_INCUMBENT_COHORT_EQUAL",incumbent)):
                    if not reference:continue
                    for horizon in HORIZONS:
                        requests.append(dict(date=str(day.date()),decision_at=_clock(day),assets=assets,
                            uids=uids,reference_assets=reference,horizon=horizon,cohort=cohort))
    loaded={};projections=[];coverage=[]
    priority={v:i for i,v in enumerate(spec["shared_domain_priority"])}
    for request in requests:
        selected={};refs={};at=_time(request["decision_at"])
        for method in {"DIAG","LW","OAS","CONSTANT_CORR","PCA","RB","RH","RT","RR","RU","RE"}:
            candidates=[s for s in produced if s.method==method and s.as_of<=at and s.horizon==request.get("horizon",5)
                and all(a in s.assets and s.coverage.get(a,{}).get("uid")==request["uids"].get(a) for a in request["assets"])]
            records=[r for r in bank if ("LW" if r["method"]=="R0" else r["method"])==method and _time(r["as_of"])<=at
                and all(a in r["assets"] and r["asset_uids"].get(a)==request["uids"].get(a) for a in request["assets"])]
            if candidates:
                state=max(candidates,key=lambda s:s.as_of)
            elif records:
                record=sorted(records,key=lambda r:(-_time(r["as_of"]).value,priority.get(r["domain_role"],99),r["risk_state_id"]))[0]
                rid=record["risk_state_id"]
                if rid not in loaded:loaded[rid]=_load_bank_state(record)
                state=loaded[rid]
            else:continue
            selected[method]=state;refs[method]={"verified":True,"risk_state_id":state.risk_state_id}
        for representation in spec["representations"]:
            try:
                value=consumer_projection(selected,representation,assets=request["assets"],uids=request["uids"],
                    reference_assets=request["reference_assets"],decision_at=at,horizon=request.get("horizon",5),verified_state_refs=refs)
                projections.append(dict(request=request,representation=representation,projection=value,state_refs=refs))
                coverage.append(dict(date=request.get("date"),cohort=request.get("cohort"),representation=representation,status="PASS_MECHANISM_PROJECTION"))
            except (ValueError,KeyError,TypeError) as exc:
                coverage.append(dict(date=request.get("date"),cohort=request.get("cohort"),representation=representation,status="BLOCKED_INPUT",reason=str(exc)))
    return dict(schema="R10_SHARED_RISK_STUDY_RESULT_R1",actual_producer_consumer_code_pins=code_pins(),
        engineering_repair_receipt=copy.deepcopy(engineering_repair_receipt),states=produced,shared_exact_refs=[r for r in bank if r["risk_state_id"] in loaded],
        projections=projections,coverage=coverage,production_receipts=receipts,domain_receipts=domains,blocks=blocks,source_notes=source_notes,
        attempted_learned_units=sum(r["attempted_learned_units"] for r in receipts),
        failed_started_units=sum(r["failed_started_units"] for r in receipts),new_account=0,
        **{k:False for k in FLAGS},**{"2026_locked":True})


RISK_NUMERIC_FEATURES=("stock_sigma","portfolio_sigma","portfolio_downside_sigma","portfolio_correlation","marginal_variance","normalized_marginal_risk",
    "qqq_beta","pooled_specific_variance","downside_variance","fixed_q_smooth_CVaR","stock_CVaR_gradient",
    "active_regime","regime_volatility","jackknife_sigma_SE","covariance_disagreement")


def projection_feature_rows(study):
    """Fixed numeric learning columns; source/SID/provenance stay separate.

    R7 preserves five groups' native extras with R2_/R3_/R4_/R5_/R6_ prefixes,
    while its common sigma/correlation/risk-delta use the fixed .2 covariance
    mixture. No extra fit, risk-penalty tuning or q optimization is introduced.
    """
    for item in study["projections"]:
        request=item["request"];features=item["projection"]["features"]
        groups={"risk":features}
        if item["representation"]=="R7":
            groups.update({"risk_"+k:v for k,v in features["group_features"].items()})
        for position,asset in enumerate(request["assets"]):
            row=dict(signal_date=request.get("date"),ticker=asset,security_id=request["uids"][asset],
                     horizon=request.get("horizon",5),representation=item["representation"],cohort=request.get("cohort"))
            for prefix,values in groups.items():
                for name in RISK_NUMERIC_FEATURES:
                    if name not in values:continue
                    value=values[name]
                    cell=value[position] if np.asarray(value).ndim==1 else value
                    if np.asarray(cell).ndim!=0 or not np.isfinite(float(cell)):
                        raise ValueError("FIXED_RISK_FEATURE_NONFINITE_OR_SHAPE")
                    row[prefix+"_"+name]=float(cell)
            row["risk_condition_number"]=item["projection"]["diagnostics"].get("condition_number")
            row["account_qualified"]=False
            yield row

# New C task adapter only. The frozen B owners and their default recipes are unchanged.
FIXED_POLICY_RESEARCH_ID = "V24_C_FULL_SELECTOR_FIXED_POLICY_FAST_R1"
FIXED_POLICY_RISK_FAMILIES = (
    "DIAG", "SAMPLE", "LW", "OAS", "CONSTANT_CORRELATION", "EWMA",
    "PCA_FACTOR", "QQQ_RESIDUAL", "FF48_HIERARCHICAL",
    "DOWNSIDE_SEMIVARIANCE", "TAIL_CVAR", "REGIME_COVARIANCE",
    "UNCERTAINTY_JACKKNIFE", "DISAGREEMENT_ENSEMBLE",
    "SHR_HP", "SHR_EB", "GARCH", "GJR_GARCH",
)
_FIXED_POLICY_CLASSIC = {
    "DIAG": "DIAG", "SAMPLE": "SCOV", "LW": "LW", "OAS": "OAS",
    "CONSTANT_CORRELATION": "CONSTANT_CORR", "EWMA": "EWMA",
    "PCA_FACTOR": "PCA", "GARCH": "GARCH", "GJR_GARCH": "GJR_GARCH",
}
_FIXED_POLICY_EXTENSIONS = {
    "QQQ_RESIDUAL": "RB", "FF48_HIERARCHICAL": "RH",
    "DOWNSIDE_SEMIVARIANCE": "RT", "REGIME_COVARIANCE": "RR",
    "UNCERTAINTY_JACKKNIFE": "RU", "DISAGREEMENT_ENSEMBLE": "RE",
}
FIXED_POLICY_RISK_COLUMNS = (
    "native_family_marginal_H5_variance", "covariance_with_equal_weight_full_U",
)


def fixed_policy_risk_specification():
    """One new task recipe; no B recipe, runner, or global calendar is changed."""
    from .joint_event_risk_estimators_r5 import specification as event_spec
    recipes = {}
    for family in FIXED_POLICY_RISK_FAMILIES:
        recipes[family] = {
            "output": "FULL_ORDERED_U", "horizon_sessions": 5,
            "coordinate": COORDINATE, "origin_window": 252,
            "cutoff": "EXCLUSIVE_PREVIOUS_LEGAL_CLOSE",
            "cadence": "INITIAL_AVAILABLE_MONTH_FIRST_AND_NECESSARY_INVALIDATION",
            "min_native_n": 30, "configs": 1, "seed": 20260928,
            "completion": "NONE_UNLESS_EXPLICIT_ORIGINAL_OWNER_MODEL_COMPLETION",
            "objective": "EQUAL_WEIGHT_COVARIANCE_VARIANCE",
        }
    for family, method in _FIXED_POLICY_CLASSIC.items():
        recipes[family]["native_owner"] = "joint_risk_estimators._estimate:" + method
        recipes[family]["parameters"] = joint.specs(method)
        recipes[family]["completion"] = joint.COMMON["unknown_assets"]
    for family, method in _FIXED_POLICY_EXTENSIONS.items():
        recipes[family]["native_owner"] = "SharedRiskEngine:" + method
        recipes[family]["completion"] = "R5_EXPLICIT_HP_CONDITIONAL_COMPLETION"
    recipes["FF48_HIERARCHICAL"]["all_u_asof_ff48_required"] = True
    recipes["DOWNSIDE_SEMIVARIANCE"]["objective"] = "ORIGINAL_HALF_LW_HALF_UNCENTERED_DOWNSIDE_VARIANCE"
    recipes["UNCERTAINTY_JACKKNIFE"].update(
        objective="FOUR_BLOCK_JACKKNIFE_PORTFOLIO_SIGMA_SE",
        replica_count=4, block_rule="CONTIGUOUS_ARRAY_SPLIT_DELETE_ONE",
        retain="FOUR_COMPLETE_PSD_COVARIANCES_NOT_SIGMA_OUTER_PRODUCTS")
    recipes["DISAGREEMENT_ENSEMBLE"].update(
        objective="FOUR_MEMBER_PORTFOLIO_SIGMA_POPULATION_STD",
        members=["LW", "OAS", "PCA", "RB"], weights=[.25]*4,
        retain="FOUR_COMPLETE_PSD_MEMBER_COVARIANCES")
    for family in ("SHR_HP", "SHR_EB"):
        recipes[family].update(native_owner="EventRiskEstimator.fit_family:" + family,
            parameters=event_spec(industry_mode="FF48_IF_ASOF_QUALIFIED"), min_native_n=0 if family=="SHR_HP" else 10,
            completion="KNOWN_CURRENT_UID_HP_PRIOR_IF_REQUIRED")
    recipes["TAIL_CVAR"].update(native_owner="retained.optimization._smooth_cvar",
        output="FULL_U_NATIVE_MATURED_H5_SCENARIOS", min_complete_scenarios=30,
        completion="NONE", objective="NATIVE_H5_SMOOTH_CVAR90_EPS5BP",
        alpha=cvar_owner.SPEC["cvar_alpha"],
        softplus_epsilon=cvar_owner.SPEC["cvar_softplus_epsilon"],
        eta_bisections=cvar_owner.SPEC["eta_bisections"])
    return dict(schema="C_FULL_U_FIXED_POLICY_RISK_R1",
        research_id=FIXED_POLICY_RESEARCH_ID, families=recipes,
        learned_units_per_refresh_upper_bound=71,
        full_u_held_only_account_axis_not_required=True,
        scientific_retry=0, no_outcome_trigger=True, strict_PIT_promotion_eligible=False)


def fixed_policy_risk_refresh_nodes(metadata_rows, *, families=FIXED_POLICY_RISK_FAMILIES):
    """Metadata only. Rows include training/OOF/calibration and policy dates."""
    families = tuple(families)
    if not families or len(set(families)) != len(families) or not set(families) <= set(FIXED_POLICY_RISK_FAMILIES):
        raise ValueError("FIXED_EIGHTEEN_FAMILY_SUBSET_REQUIRED")
    from .event_risk_contract_r5 import structural_identity
    rows = list(metadata_rows)
    previous_date, previous, nodes = None, {}, []
    recipe = fixed_policy_risk_specification()
    recipe_sha = content_hash(recipe)
    for row in rows:
        at = _time(row["decision_at"])
        if previous_date is not None and at <= previous_date:
            raise ValueError("UNIQUE_INCREASING_PRE2026_DECISION_ROWS_REQUIRED")
        if at >= CUTOFF:
            raise ValueError("PRE2026_RISK_REFRESH_ONLY")
        assets = tuple(row["assets"])
        uids, epochs = row["asset_uids"], row["asset_epochs"]
        if (not assets or len(set(assets)) != len(assets) or set(assets) != set(uids)
            or set(assets) != set(epochs) or any(not _sid(v) for v in uids.values())
            or any(not isinstance(v,str) or not v or v.upper().startswith("UNKNOWN") for v in epochs.values())):
            raise ValueError("FULL_ORDERED_U_UID_EPOCH_REQUIRED")
        month_first = previous_date is None or (at.year,at.month) != (previous_date.year,previous_date.month)
        for family in families:
            support = row["family_source_support"][family]
            signature = structural_identity(assets=assets,uids=uids,epochs=epochs,
                security_coordinate=row["security_coordinate"],source_support_identity=support)
            changed = previous.get(family) != signature
            if month_first or changed:
                reasons = (["INITIAL_AVAILABLE"] if family not in previous else
                    (["MONTH_FIRST"] if month_first else []) +
                    (["FULL_U_UID_EPOCH_OR_SOURCE_INVALIDATION"] if changed else []))
                nodes.append(dict(family=family,decision_at=at.isoformat(),
                    ordered_assets=list(assets),asset_uids=copy.deepcopy(uids),
                    asset_epochs=copy.deepcopy(epochs),trigger_reasons=reasons,
                    structural_sha256=signature,recipe_sha256=recipe_sha,
                    learned_units_upper_bound=71))
            previous[family] = signature
        previous_date = at
    # 71 is per union refresh context, not per family. Do not multiply by 18.
    contexts = {n["decision_at"] for n in nodes}
    return dict(schema="C_FULL_U_FIXED_POLICY_RISK_PLAN_R1",recipe=recipe,
        recipe_sha256=recipe_sha,nodes=nodes,refresh_contexts=len(contexts),
        learned_units_upper_bound=71*len(contexts),
        includes_all_supplied_training_oof_dates=True,numeric_reads=0)


def _fixed_policy_complete_matrix(native, native_assets, assets, prior):
    """Reuse the original R5 conditional law; never label completion as native."""
    from .event_risk_contract_r5 import conditional_prior_completion
    if tuple(native_assets) == tuple(assets):
        return joint.validate_covariance(native,regularize=False)[0], []
    positions = tuple(assets.index(a) for a in native_assets)
    matrix, proof = conditional_prior_completion(prior,native,positions)
    return matrix, proof["prior_only_positions"]


def _fixed_policy_cached_matrix(cache, *, name, assets):
    """Export an already SUCCEEDED canonical matrix without a second fit."""
    found = []
    for event in cache.budget.events:
        if event["name"] != name or tuple(event["context"]["assets"]) != tuple(assets):
            continue
        record = cache._records[event["key"]]
        if event["status"] != "SUCCEEDED" or record["status"] != "SUCCEEDED":
            raise ValueError("INCOMPLETE_REPLICA_NO_RETRY")
        if content_hash(record["value"]) != record["result_sha256"]:
            raise ValueError("REPLICA_CACHE_CHANGED")
        value = record["value"]
        matrix = value[0] if isinstance(value,tuple) else value["covariance"]
        found.append(joint.validate_covariance(matrix,regularize=False)[0])
    if len(found) != 1:
        raise ValueError("UNIQUE_EXACT_COMPLETED_REPLICA_REQUIRED")
    return found[0]


def estimate_fixed_policy_risk_refresh(inputs, *, as_of, support_metadata,
        current_identity_proof, authorization, reserve_callback,
        on_component_start=None, families=FIXED_POLICY_RISK_FAMILIES,
        native_scenario_receipt=None):
    """Thin fresh producer. Root freezes source/DAG and persists all objects.

    All returns remain behind the durable whole-refresh ACK. Existing B kernels,
    parameters, receipts and global dictionaries are unchanged.
    """
    from . import shared_risk_engine_r2 as engine
    from .joint_event_risk_estimators_r5 import EventRiskEstimator, specification as event_spec
    from .event_risk_contract_r5 import event_calendar, structural_identity
    families = tuple(families)
    recipe = fixed_policy_risk_specification()
    if (authorization.get("research_id") != FIXED_POLICY_RESEARCH_ID or authorization.get("frozen") is not True
        or authorization.get("recipe_sha256") != content_hash(recipe)
        or not families or len(set(families)) != len(families)
        or not set(families) <= set(FIXED_POLICY_RISK_FAMILIES)):
        raise ValueError("NEW_C_FIXED_RECIPE_FREEZE_REQUIRED")
    asof, cutoff, sessions = event_calendar(inputs,as_of)
    inputs.source_receipt.validate(cutoff)
    assets = tuple(inputs.assets)
    if (tuple(current_identity_proof["assets"]) != assets
        or current_identity_proof["asset_uids"] != dict(inputs.asset_uids)
        or current_identity_proof.get("source_qualified") is not True
        or current_identity_proof.get("maturity_qualified") is not True
        or inputs.source_receipt.return_coordinate != COORDINATE):
        raise ValueError("EXACT_FULL_U_SOURCE_UID_MATURITY_REQUIRED")
    structural_sha = structural_identity(assets=assets,uids=current_identity_proof["asset_uids"],
        epochs=current_identity_proof["asset_epochs"],security_coordinate=current_identity_proof["security_coordinate"],
        source_support_identity=current_identity_proof["source_support_identity"])
    # A metadata projection precedes every access to return_value.
    meta = short._metadata(inputs,cutoff,sessions)
    origins = pd.DatetimeIndex(meta.origin_at.unique()).sort_values()[-252:]
    if len(origins) != 252:
        raise ValueError("252_MATURED_PARENT_ORIGINS_REQUIRED")
    support = support_metadata.loc[:,["asset","origin_at","qualified"]].copy()
    support["origin_at"] = support.origin_at.map(_time)
    support = support.loc[support.origin_at.isin(origins)]
    if (not support.asset.isin(assets).all() or support.duplicated(["asset","origin_at"]).any()
        or not support.qualified.map(lambda x:isinstance(x,(bool,np.bool_))).all()):
        raise ValueError("EXACT_METADATA_SUPPORT_REQUIRED")
    legal = set(zip(meta.asset,meta.origin_at))
    if not set(zip(support.asset,support.origin_at)) <= legal:
        raise ValueError("SUPPORTED_ROW_WITHOUT_UID_MATURE_SOURCE")
    mask = support.pivot(index="origin_at",columns="asset",values="qualified").reindex(
        index=origins,columns=assets).fillna(False).astype(bool)
    ack = reserve_callback(dict(research_id=FIXED_POLICY_RESEARCH_ID,
        recipe_sha256=content_hash(recipe),as_of=asof.isoformat(),
        requested_families=list(families),maximum_weighted_units=71))
    if (not isinstance(ack,dict) or ack.get("ack") is not True
        or ack.get("reserved_units") != 71 or not ack.get("reservation_id")):
        raise ValueError("DURABLE_REFRESH_ACK_REQUIRED_BEFORE_NUMERIC")
    starts = []
    def start(name,kind,units=1,key=None):
        token = dict(name=name,kind=kind,units=units,key=key,status="FIT_STARTED")
        if on_component_start is not None:
            confirmation=on_component_start(copy.deepcopy(token))
            if not isinstance(confirmation,dict) or confirmation.get("ack") is not True:
                raise ValueError("COMPONENT_ACK_REQUIRED")
        starts.append(token)
        return token
    def finish(token,success): token["status"]="SUCCEEDED" if success else "FAILED"
    def observe(event):
        if event["kind"] in LEARNED_KINDS and event["name"] not in {"fixed:primitive:GARCH","fixed:primitive:GJR_GARCH"}:
            start(event["name"],event["kind"],key=event["key"])
    budget=StateBudget(limit=71,reserve_callback=observe)
    cache=StateCache(budget,**short._context(inputs,cutoff))
    selected=inputs.observations.loc[inputs.observations.origin_at.map(_time).isin(origins)]
    frame=engine._panel(selected,assets,inputs.asset_uids,inputs.identity_epoch,
        inputs.source_receipt,sessions,cutoff,5).reindex(index=origins,columns=assets)
    if not np.isfinite(frame.to_numpy(float)[mask.to_numpy(bool)]).all():
        raise ValueError("NONFINITE_REQUIRED_SOURCE_CELL")
    frame=frame.where(mask)
    params=dict(fit_cutoff=cutoff.isoformat(),return_unit=COORDINATE,
        return_horizon_sessions=5,source_id=content_hash(inputs.source_receipt.cache_identity()),
        information_set_id=content_hash(current_identity_proof))
    prepared=None
    results={}
    event_owner=None
    hp=None
    def event_estimator():
        nonlocal event_owner
        if event_owner is None:
            event_owner=EventRiskEstimator(event_spec(industry_mode="FF48_IF_ASOF_QUALIFIED"))
        return event_owner
    def hp_state():
        nonlocal hp
        if hp is None:
            owner=event_estimator()
            proof=owner.qualify(inputs,as_of=asof,support_metadata=support_metadata,current_identity_proof=current_identity_proof)
            hp=owner.fit_family("SHR_HP",inputs,as_of=asof,support_metadata=support_metadata,
                current_identity_proof=current_identity_proof,cache=cache,
                expected_qualification=proof,expected_recipe_sha256=owner.recipe_sha256)
            if hp.covariance is None:
                raise ValueError("EXPLICIT_HP_COMPLETION_SOURCE_UNAVAILABLE")
        return hp
    for family in families:
        family_start = len(starts)
        family_usage = len(cache.usage_log)
        try:
            family_support = (current_identity_proof.get("family_source_support_identity",{}).get(family)
                if family=="FF48_HIERARCHICAL" else current_identity_proof["source_support_identity"])
            family_structural = structural_identity(assets=assets,uids=dict(inputs.asset_uids),
                epochs=current_identity_proof["asset_epochs"],
                security_coordinate=current_identity_proof["security_coordinate"],
                source_support_identity=family_support)
            extras={}
            covariance=None
            if family in _FIXED_POLICY_CLASSIC:
                if prepared is None:
                    names,coverage,prepared=cache.learn("scaler","fixed:stock_preprocessing",(frame,),
                        lambda:joint._prepare(frame,{**joint.specs("LW"),**params}),
                        parameters={**params,"min_observations":30,"variance_floor":1e-12})
                    if prepared is None: raise ValueError("NO_NATIVE_ESTIMATION_COHORT")
                estimated=tuple(names[i] for i in prepared["positions"])
                method=_FIXED_POLICY_CLASSIC[family]
                config={**joint.specs(method),**params}
                compute=(lambda method=method,config=config:
                    _observed_garch(method,prepared,frame,inputs,config,start,finish)) if method in {"GARCH","GJR_GARCH"} else (
                    lambda method=method,config=config:joint._estimate(method,prepared,frame.index,estimated,None,None,config))
                native,details,count=cache.learn("covariance","fixed:primitive:"+method,
                    (prepared,frame.index.tolist()),compute,parameters=config)
                if count != (2 if method in {"GARCH","GJR_GARCH"} else 1):
                    raise ValueError("PHYSICAL_ESTIMATOR_COUNT_CHANGED")
                bundle=joint.RiskBundle(method,"FITTED",assets,tuple(origins.map(pd.Timestamp.isoformat)),
                    estimated_assets=estimated,covariance=native,coverage=coverage,
                    fallback_variance=float(np.median(prepared["marginal_variance"])),
                    fitted_state={**details,"return_unit":COORDINATE,"return_horizon_sessions":5})
                covariance, completion=joint.risk_matrix(bundle,assets,return_metadata=True)
                extras.update(native_assets=estimated,completion=completion,native_details=details)
            elif family in {"SHR_HP","SHR_EB"}:
                owner=event_estimator()
                proof=owner.qualify(inputs,as_of=asof,support_metadata=support_metadata,current_identity_proof=current_identity_proof)
                state=(hp_state() if family=="SHR_HP" else owner.fit_family(family,inputs,as_of=asof,
                    support_metadata=support_metadata,current_identity_proof=current_identity_proof,cache=cache,
                    expected_qualification=proof,expected_recipe_sha256=owner.recipe_sha256))
                if state.covariance is None: raise ValueError("SHORT_HISTORY_OWNER_BLOCKED")
                covariance=state.covariance
                extras.update(native_state=state,native_assets=state.assets)
            elif family=="TAIL_CVAR":
                receipt=native_scenario_receipt
                if (not isinstance(receipt,dict) or receipt.get("native") is not True
                    or receipt.get("horizon_sessions")!=5 or receipt.get("return_coordinate")!=COORDINATE
                    or tuple(receipt.get("assets",()))!=assets
                    or receipt.get("asset_uids")!=dict(inputs.asset_uids)
                    or receipt.get("source_cache_identity")!=inputs.source_receipt.cache_identity()
                    or receipt.get("cutoff")!=cutoff.isoformat()
                    or receipt.get("recipe_sha256")!=content_hash(recipe)
                    or not isinstance(receipt.get("source_projection_sha256"),str)
                    or len(receipt["source_projection_sha256"])!=64
                    or receipt.get("source_projection_sha256")!=authorization.get("native_scenario_source_projection_sha256")):
                    raise ValueError("INDEPENDENT_NATIVE_H5_SCENARIO_RECEIPT_REQUIRED")
                complete=frame.dropna(axis=0,how="any")
                if len(complete)<30: raise ValueError("FEWER_THAN_30_NATIVE_FULL_U_H5_SCENARIOS")
                extras.update(scenario_returns=complete.to_numpy(float),
                    scenario_origins=tuple(complete.index.map(pd.Timestamp.isoformat)),
                    scenario_assets=assets,native_scenario_receipt=copy.deepcopy(receipt))
            else:
                if family=="FF48_HIERARCHICAL":
                    event_estimator()._family_support(inputs,family,current_identity_proof,cutoff)
                    groups=engine._industries(inputs,assets,cutoff)
                    if tuple(groups.index)!=assets: raise ValueError("FULL_U_ASOF_FF48_MAPPING_REQUIRED_NO_MARKET_ONLY")
                native_assets=tuple(a for a in assets if mask[a].sum()>=30)
                if not native_assets: raise ValueError("NO_MIN30_NATIVE_COHORT")
                cohort=EventRiskEstimator._cohort_input(inputs,native_assets)
                legal_support=set((a,o) for a,o,qualified in support.itertuples(index=False,name=None) if qualified)
                cohort=replace(cohort,observations=cohort.observations.loc[
                    [(a,_time(o)) in legal_support for a,o in cohort.observations.loc[:,["asset","origin_at"]].itertuples(index=False,name=None)]].copy())
                subset_cache=cache.bind(**short._context(cohort,cutoff))
                owner=event_estimator()
                worker=SharedRiskEngine(budget=budget);worker.cache=subset_cache
                state=owner._engine_fit(worker,_FIXED_POLICY_EXTENSIONS[family],cohort,as_of=asof)
                if state.covariance is None: raise ValueError("NATIVE_EXTENSION_BLOCKED")
                prior=hp_state().covariance if native_assets!=assets else state.covariance
                covariance,completed=_fixed_policy_complete_matrix(state.covariance,native_assets,assets,prior)
                extras.update(native_state=state,native_assets=native_assets,
                    prior_only_positions=completed,completion="EXPLICIT_R5_HP_CONDITIONAL_LAW" if completed else "NATIVE_FULL_U")
                if family=="UNCERTAINTY_JACKKNIFE":
                    replicas=[_fixed_policy_cached_matrix(subset_cache,
                        name="primitive:LW:DELETE_BLOCK_"+str(b),assets=native_assets) for b in range(4)]
                    extras["psd_replicas"]=[_fixed_policy_complete_matrix(c,native_assets,assets,prior)[0] for c in replicas]
                elif family=="DISAGREEMENT_ENSEMBLE":
                    replicas=[_fixed_policy_cached_matrix(subset_cache,name="primitive:"+m,assets=native_assets)
                        for m in ("LW","OAS","PCA")]
                    replicas.append(_fixed_policy_cached_matrix(subset_cache,name="qqq_residual_lw",assets=native_assets))
                    # RB member is absolute beta*QQQ+residual, not residual covariance.
                    beta=np.asarray(state.qqq_relative_state["beta"])
                    qvar=state.qqq_relative_state["qqq_variance"]
                    replicas[-1]=qvar*np.outer(beta,beta)+replicas[-1]
                    extras["psd_replicas"]=[_fixed_policy_complete_matrix(c,native_assets,assets,prior)[0] for c in replicas]
            if covariance is not None:
                covariance=joint.validate_covariance(covariance,regularize=False)[0]
            results[family]=dict(status="ESTIMATED",family=family,assets=assets,
                asset_uids=dict(inputs.asset_uids),asset_epochs=copy.deepcopy(current_identity_proof["asset_epochs"]),
                as_of=asof.isoformat(),cutoff=cutoff.isoformat(),horizon_sessions=5,
                return_coordinate=COORDINATE,source_cache_identity=inputs.source_receipt.cache_identity(),
                recipe_sha256=content_hash(recipe),structural_sha256=family_structural,
                security_coordinate=current_identity_proof["security_coordinate"],
                source_support_identity=copy.deepcopy(family_support),
                covariance=covariance,**extras)
        except (ValueError,TypeError,KeyError,np.linalg.LinAlgError) as exc:
            entered = len(starts)>family_start or any(
                cache._records[k]["status"] in {"FAILED","RESERVED"}
                for k in cache.usage_log[family_usage:])
            results[family]=dict(status="TRAINING_FAILED" if entered else "SOURCE_NOT_TESTABLE",
                family=family,assets=assets,error_type=type(exc).__name__,
                reason=str(exc),scientific_retry=0,failed_capacity_retained=True)
    bykey={e["key"]:e for e in budget.events}
    for token in starts:
        if token["key"] is not None: token["status"]=bykey[token["key"]]["status"]
    weighted=sum(t["units"] for t in starts)
    if weighted>71: raise ValueError("WEIGHTED_REFRESH_LEARNED_CAP_EXCEEDED")
    return dict(states=results,component_starts=starts,weighted_learned_units=weighted,
        logical_cache_learned_units=budget.learned_total,cache_receipt=budget.snapshot(),
        scientific_retry=0,budget_refund=False,recipe_sha256=content_hash(recipe))



def _fixed_policy_qualified_state(state):
    assets=tuple(state["assets"])
    if (state.get("status") not in {"ESTIMATED","EXACT_REUSED"}
        or state.get("family") not in FIXED_POLICY_RISK_FAMILIES
        or state.get("horizon_sessions")!=5 or state.get("return_coordinate")!=COORDINATE
        or not _time(state["cutoff"]) < _time(state["as_of"]) < CUTOFF
        or len(set(assets))!=len(assets) or not assets
        or set(state.get("asset_uids",{}))!=set(assets)
        or len(set(state["asset_uids"].values()))!=len(assets)
        or not all(_sid(v) for v in state["asset_uids"].values())):
        raise ValueError("QUALIFIED_FULL_U_PRE2026_H5_RISK_STATE_REQUIRED")
    return assets


def fixed_policy_risk_objective(state, members):
    return _fixed_policy_risk_objective(state,members,validate=True)


def _fixed_policy_risk_objective(state, members, *, validate):
    """One frozen statistic; selected members never determine a fitted state."""
    assets=_fixed_policy_qualified_state(state); members=tuple(members)
    if not members or len(set(members))!=len(members) or not set(members)<=set(assets):
        raise ValueError("EXACT_MEMBER_DOMAIN_REQUIRED")
    q=np.array([1/len(members) if a in members else 0. for a in assets])
    family=state["family"]
    if family=="TAIL_CVAR":
        scenarios=np.asarray(state["scenario_returns"],float)
        if (tuple(state["scenario_assets"])!=assets or scenarios.ndim!=2
            or scenarios.shape[1]!=len(assets) or len(scenarios)<30 or not np.isfinite(scenarios).all()):
            raise ValueError("NATIVE_H5_FULL_U_SCENARIOS_REQUIRED")
        return float(cvar_owner._smooth_cvar(q[None,:],scenarios[None,:,:])[0][0])
    if family in {"UNCERTAINTY_JACKKNIFE","DISAGREEMENT_ENSEMBLE"}:
        replicas=state.get("psd_replicas",[])
        if len(replicas)!=4: raise ValueError("FOUR_FULL_PSD_MATRICES_REQUIRED")
        sigmas=[]
        for matrix in replicas:
            matrix=joint.validate_covariance(matrix,regularize=False)[0] if validate else np.asarray(matrix,float)
            if matrix.shape!=(len(assets),len(assets)):raise ValueError("FULL_REPLICA_AXIS_REQUIRED")
            sigmas.append(np.sqrt(max(float(q@matrix@q),0.)))
        sigmas=np.asarray(sigmas)
        return float(np.sqrt(.75*((sigmas-sigmas.mean())**2).sum())) if family=="UNCERTAINTY_JACKKNIFE" else float(sigmas.std(ddof=0))
    matrix=joint.validate_covariance(state["covariance"],regularize=False)[0] if validate else np.asarray(state["covariance"],float)
    if matrix.shape!=(len(assets),len(assets)):raise ValueError("FULL_COVARIANCE_AXIS_REQUIRED")
    return float(q@matrix@q)


def fixed_policy_bounded_swap(scores, security_uids, state, *, count=20,max_swaps=20,quality_floor=.975):
    """Vectorized deterministic local swaps; no per-candidate PSD or optimizer."""
    scores=np.asarray(scores,float);uids=tuple(security_uids);assets=tuple(state["assets"])
    if (len(scores)!=len(assets) or len(uids)!=len(assets) or len(set(uids))!=len(uids)
        or tuple(state["asset_uids"][a] for a in assets)!=uids
        or not np.isfinite(scores).all() or not all(_sid(u) for u in uids)
        or count!=20 or max_swaps!=20 or quality_floor!=.975 or len(assets)<20):
        raise ValueError("FROZEN_FULL_U_TOP20_SWAP_CONTRACT")
    order=sorted(range(len(assets)),key=lambda i:(-scores[i],uids[i]))
    quality=np.zeros(len(assets))
    quality[order]=np.arange(len(assets)-1,-1,-1)/max(len(assets)-1,1)
    selected=list(order[:20]);anchor=tuple(selected)
    floor=.975*float(quality[selected].mean())
    objective=fixed_policy_risk_objective(state,tuple(assets[i] for i in selected))
    family=state["family"]
    matrices=([np.asarray(c,float) for c in state["psd_replicas"]]
        if family in {"UNCERTAINTY_JACKKNIFE","DISAGREEMENT_ENSEMBLE"}
        else [] if family=="TAIL_CVAR" else [np.asarray(state["covariance"],float)])
    scenarios=np.asarray(state["scenario_returns"],float) if family=="TAIL_CVAR" else None
    accepted=[];evaluations=0
    for _ in range(20):
        outside=np.array([i for i in order if i not in selected],int)
        if not len(outside):break
        sum_quality=float(quality[selected].sum())
        row_sums=[matrix[:,selected].sum(axis=1) for matrix in matrices]
        variance=[float(matrix[np.ix_(selected,selected)].sum()/400.) for matrix in matrices]
        portfolio=scenarios[:,selected].sum(axis=1)/20. if scenarios is not None else None
        candidates=[]
        for out in selected:
            incoming=outside[(sum_quality-quality[out]+quality[outside])/20.>=floor]
            if not len(incoming):continue
            evaluations+=len(incoming)
            if scenarios is not None:
                # Same native CVaR owner, with precomputed equal-weight return:
                # one portfolio coordinate avoids a dense [pairs,scenarios,fullU] tensor.
                changes=(scenarios[:,incoming]-scenarios[:,out,None])/20.
                values=np.empty(len(incoming))
                for first in range(0,len(incoming),256):
                    batch=(portfolio[:,None]+changes[:,first:first+256]).T[:,:,None]
                    values[first:first+256]=cvar_owner._smooth_cvar(np.ones((len(batch),1)),batch)[0]
            else:
                risks=np.array([v+(2*(rows[incoming]-rows[out])+np.diag(matrix)[incoming]
                    +matrix[out,out]-2*matrix[incoming,out])/400.
                    for matrix,rows,v in zip(matrices,row_sums,variance)])
                if family=="UNCERTAINTY_JACKKNIFE":
                    sigmas=np.sqrt(np.maximum(risks,0.))
                    values=np.sqrt(.75*((sigmas-sigmas.mean(axis=0))**2).sum(axis=0))
                elif family=="DISAGREEMENT_ENSEMBLE":
                    values=np.sqrt(np.maximum(risks,0.)).std(axis=0,ddof=0)
                else:values=risks[0]
            if not np.isfinite(values).all():raise ValueError("NONFINITE_SWAP_OBJECTIVE")
            for incoming_id,value in zip(incoming,values):
                if value<objective:
                    candidates.append((float(value),uids[incoming_id],uids[out],int(incoming_id),out))
        if not candidates:break
        # Re-evaluate the winning full-set statistic to enforce actual strict
        # improvement despite roundoff in the fast rank-one difference formula.
        chosen=None
        for candidate in sorted(candidates,key=lambda item:item[:3]):
            proposed=[candidate[3] if i==candidate[4] else i for i in selected]
            exact=_fixed_policy_risk_objective(state,tuple(assets[i] for i in proposed),validate=False)
            if exact<objective:
                chosen=(candidate,proposed,exact);break
        if chosen is None:break
        best,selected,objective=chosen
        accepted.append(dict(in_uid=best[1],out_uid=best[2]))
    selected.sort(key=lambda i:(-scores[i],uids[i]))
    return dict(members=tuple(assets[i] for i in selected),
        anchor_members=tuple(assets[i] for i in anchor),accepted_swaps=accepted,
        ordinal_quality_floor=floor,selected_ordinal_mean=float(quality[selected].mean()),
        objective=objective,candidate_objective_evaluations=evaluations,
        no_strict_improvement=not accepted,global_optimal_claim=False)


def fixed_policy_single_stock_risk_features(state):
    """BASE32 plus exactly these two columns is new BASE34, never old228."""
    assets=_fixed_policy_qualified_state(state)
    matrix=joint.validate_covariance(state["covariance"],regularize=False)[0]
    if matrix.shape!=(len(assets),len(assets)):raise ValueError("EXACT_FULL_U_FEATURE_AXIS")
    q=np.full(len(assets),1/len(assets))
    return pd.DataFrame(dict(zip(FIXED_POLICY_RISK_COLUMNS,
        (np.diag(matrix),matrix@q))),index=pd.Index(assets,name="asset"))


def fixed_policy_whole_set_gate(kind, hgb_members, raw_members, state):
    """Missing input raises; it is never a successful Raw fallback decision."""
    _fixed_policy_qualified_state(state)
    required={"LW_VARIANCE":"LW","H5_CVAR":"TAIL_CVAR",
        "PSD_UNCERTAINTY":"UNCERTAINTY_JACKKNIFE","PCA_DIVERSIFICATION":"PCA_FACTOR"}
    if state.get("status") not in {"ESTIMATED","EXACT_REUSED"} or kind not in required or state.get("family")!=required[kind]:
        raise ValueError("EXACT_FOUR_GATE_OWNER_REQUIRED")
    if len(hgb_members)!=20 or len(raw_members)!=20 or len(set(hgb_members))!=20 or len(set(raw_members))!=20:
        raise ValueError("TWO_COMPLETE_TOP20_SETS_REQUIRED")
    if kind=="PCA_DIVERSIFICATION":
        assets=tuple(state["assets"])
        detail=state["native_details"]
        components=np.asarray(detail["components"],float)
        eigen=np.asarray(detail["factor_variance"],float)
        native=tuple(state["native_assets"])
        if components.shape!=(5,len(native)) or eigen.shape!=(5,):
            raise ValueError("FIVE_NATIVE_PCA_FACTOR_LOADINGS_REQUIRED")
        def concentration(members):
            if not set(members)<=set(assets):raise ValueError("PCA_MEMBER_NOT_IN_FULL_U")
            # Original independent-prior completion means zero common-factor exposure.
            q=np.array([1/20 if a in members else 0. for a in native])
            contribution=eigen*(components@q)**2
            total=contribution.sum()
            if total<=0:raise ValueError("PCA_FACTOR_CONTRIBUTIONS_UNIDENTIFIABLE")
            return float(((contribution/total)**2).sum())
        hgb,raw=concentration(hgb_members),concentration(raw_members)
    else:
        hgb=fixed_policy_risk_objective(state,hgb_members)
        raw=fixed_policy_risk_objective(state,raw_members)
    passed=hgb<=raw
    return dict(status="EVALUATED",passed=passed,
        members=tuple(hgb_members if passed else raw_members),
        hgb_statistic=hgb,raw_statistic=raw,missing_input_is_failure_condition=False)



def validate_fixed_policy_exact_reuse(state, *, decision_at, current_identity_proof,
        source_cache_identity, expected_state_digest, expected_recipe_sha256):
    """Frozen state reuse only; no fit, conversion or coordinate stitching."""
    from .event_risk_contract_r5 import structural_identity
    at = _time(decision_at)
    assets = tuple(current_identity_proof["assets"])
    structural = structural_identity(assets=assets,uids=current_identity_proof["asset_uids"],
        epochs=current_identity_proof["asset_epochs"],
        security_coordinate=current_identity_proof["security_coordinate"],
        source_support_identity=(current_identity_proof.get("family_source_support_identity",{}).get(state["family"])
            if state.get("family")=="FF48_HIERARCHICAL" else current_identity_proof["source_support_identity"]))
    if (state.get("status") not in {"ESTIMATED","EXACT_REUSED"}
        or state.get("family") not in FIXED_POLICY_RISK_FAMILIES
        or state.get("recipe_sha256") != expected_recipe_sha256
        or expected_recipe_sha256 != content_hash(fixed_policy_risk_specification())
        or tuple(state.get("assets",())) != assets
        or state.get("asset_uids") != current_identity_proof["asset_uids"]
        or state.get("asset_epochs") != current_identity_proof["asset_epochs"]
        or state.get("structural_sha256") != structural
        or state.get("source_cache_identity") != source_cache_identity
        or state.get("horizon_sessions") != 5
        or state.get("return_coordinate") != COORDINATE
        or not _time(state["cutoff"]) < _time(state["as_of"]) <= at < CUTOFF
        or current_identity_proof.get("source_qualified") is not True
        or current_identity_proof.get("maturity_qualified") is not True
        or content_hash(state) != expected_state_digest):
        raise ValueError("EXACT_COMPLETE_FULL_U_CLOCK_SOURCE_RECIPE_REUSE_REQUIRED")
    return dict(status="EXACT_REUSED",state_sha256=expected_state_digest,
        family=state["family"],as_of=state["as_of"],decision_at=at.isoformat(),
        numeric_reestimation=0,learned_units=0)
