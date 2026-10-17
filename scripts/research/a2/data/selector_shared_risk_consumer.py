"""Metadata qualification and guarded exact consumption of existing B risk states.

No risk estimator, history assembler, numerical outcome reader or refit lives here.
Raw is projected to three identity keys. Covariance is deserialized only after a
C13 formal freeze pins this receipt, this source, the bank and the exact artifact.
"""
from __future__ import annotations
import hashlib, json, re
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.training.selector_classical_risk import safe_d, pin, put
from scripts.research.a2.evaluation.selector_account_compare import pre2026, sha, readj
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash

REPO = Path(__file__).resolve().parents[4]
ID = "V24_C_SELECTOR_RISK_CONSTRAINED_AND_CLASSICAL_STATISTICS_C13"
KEYS = ["signal_date", "ticker", "security_uid"]
LIMIT = pd.Timestamp("2026-01-01", tz="UTC")
FAMILIES = ("R01_DIAG", "R02_SAMPLE", "R03_LW", "R04_OAS", "R05_CONSTANT_CORRELATION",
    "R06_EWMA", "R07_PCA", "R08_QQQ_RESIDUAL", "R09_QQQ_FF48_HIERARCHICAL",
    "R10_GARCH", "R11_GJR_GARCH", "R12_DOWNSIDE", "R13_CVAR", "R14_REGIME",
    "R15_JACKKNIFE", "R16_DISAGREEMENT", "R17_HIERARCHICAL_POSTERIOR", "R18_EB")
METHODS = {"R06_EWMA": ("R3", "RD", "monthly"), "R08_QQQ_RESIDUAL": ("R3", "RB", "monthly"),
    "R17_HIERARCHICAL_POSTERIOR": ("R4", "SHR_HP", "quarterly"), "R18_EB": ("R4", "SHR_EB", "quarterly")}


def utc(value):
    t = pd.Timestamp(value)
    if pd.isna(t) or t.tzinfo is None: raise ValueError("EXPLICIT_TIMEZONE_REQUIRED")
    return t.tz_convert("UTC")


def decision_close(day):
    return (pd.Timestamp(day).normalize().tz_localize("America/New_York") + pd.Timedelta(hours=16)).tz_convert("UTC")


def period(t, cadence):
    t = utc(t)
    if cadence not in {"monthly", "quarterly"}: raise ValueError("NATIVE_CADENCE_REQUIRED")
    return (t.year, t.month if cadence == "monthly" else (t.month-1)//3+1)


def namespace(uid):
    if not isinstance(uid, str) or not re.fullmatch(r"[A-Z0-9*@#]{9}", uid):
        raise ValueError("EXACT_CANONICAL_CUSIP_REQUIRED")
    return "CUSIP:" + uid


def current_map(frame):
    if not {"ticker", "security_uid"}.issubset(frame.columns) or frame.empty:
        raise ValueError("FULL_U_KEYS_REQUIRED")
    if frame[["ticker", "security_uid"]].isna().any().any() or frame.ticker.duplicated().any() or frame.security_uid.duplicated().any():
        raise ValueError("UNIQUE_FULL_U_IDENTITY_REQUIRED")
    return dict(frame[["ticker", "security_uid"]].itertuples(index=False, name=None))


def u_hash(frame):
    values = sorted(current_map(frame).items())
    return hashlib.sha256(("\n".join(a+"|"+u for a,u in values)+"\n").encode()).hexdigest()


def validate_source(context, cutoff):
    for key in ("id", "version", "sha256", "execution_semantics"):
        if key not in context: raise ValueError("TYPED_SOURCE_METADATA_REQUIRED")
    e = context["execution_semantics"]
    if (not context["id"] or not context["version"] or not re.fullmatch(r"[0-9a-f]{64}", context["sha256"])
        or e.get("status") != "FROZEN_HISTORY_MECHANISM_SOURCE_BOUND"
        or e.get("return_coordinate") != "shareholder_value_open_return"
        or not e.get("identity_epoch") or e.get("strict_PIT_promotion_eligible") is not False
        or e.get("quote_qualified") is not False or e.get("historical_authority_status") != "UNKNOWN"
        or e.get("observation_time_assumed") is not True
        or not re.fullmatch(r"[0-9a-f]{64}", e.get("scientific_contract_sha256", ""))):
        raise ValueError("MECHANISM_SOURCE_CANNOT_GRANT_STRICT_AUTHORITY")
    available = utc(e["assumed_observation_at"])
    if available > utc(cutoff) or available >= LIMIT: raise ValueError("LATE_SOURCE_AVAILABILITY")
    if utc(e["actual_snapshot_timestamp"]) < available: raise ValueError("SNAPSHOT_PRECEDES_ASSUMED_CLOCK")


def qualify_current_u(record, current_u, decision_at, cadence, source_context):
    """Check one whole domain, preserving original bank order; no numeric reads."""
    at, asof, cutoff = map(utc, (decision_at, record["as_of"], record["cutoff"]))
    if at >= LIMIT or asof >= LIMIT or cutoff >= LIMIT or not cutoff < asof <= at:
        raise ValueError("STATE_CLOCK_OR_PRE2026_BOUNDARY")
    if period(at, cadence) != period(asof, cadence): raise ValueError("NATIVE_REFRESH_PERIOD_EXPIRED")
    if (record.get("domain_role") != "FULL_REQUESTED_POOL" or record.get("reusable") is not True
        or record.get("exact_reuse_only") is not True or record.get("strict_PIT_promotion_eligible") is not False
        or record.get("admission") != "CONDITIONAL_SOURCE_ONLY_EXACT_STATE"
        or record.get("status", record.get("original_status")) not in
            {"CONDITIONAL_FROZEN_HISTORY_MECHANISM", "PASS_FROZEN_HISTORY_MECHANISM"}):
        raise ValueError("EXACT_SOURCE_ONLY_FULL_DOMAIN_REQUIRED")
    h = record.get("horizon_sessions", 5)
    if type(h) is not int or h != 5: raise ValueError("NATIVE_H5_ONLY_NO_SCALED_HORIZON")
    assets, uids, epochs = record["assets"], record["asset_uids"], record["asset_epochs"]
    if len(assets) != len(set(assets)) or set(assets) != set(uids) or set(assets) != set(epochs) or not all(epochs.values()):
        raise ValueError("EXACT_ORDER_UID_EPOCH_REQUIRED")
    expected = {a: namespace(uids[a]) for a in assets}
    if current_map(current_u) != expected: raise ValueError("FULL_U_OR_UID_MISMATCH_NO_PADDING")
    if record.get("covariance_shape") is not None and record["covariance_shape"] != [len(assets), len(assets)]:
        raise ValueError("COVARIANCE_HEADER_SHAPE")
    if record.get("finite_check") is False: raise ValueError("COVARIANCE_HEADER_NONFINITE")
    if "psd_check" in record and record["psd_check"] not in {"CHOLESKY_WITH_DECLARED_ROUNDOFF_RIDGE", "NONNEGATIVE_DIAGONAL"}:
        raise ValueError("COVARIANCE_HEADER_PSD")
    validate_source(source_context, cutoff)
    primary = record.get("primary_source")
    if primary and (primary.get("source_identity"), primary.get("source_version"), primary.get("source_sha256"),
                    primary.get("identity_epoch"), primary.get("return_coordinate")) != (
        source_context["id"], source_context["version"], source_context["sha256"],
        source_context["execution_semantics"]["identity_epoch"], "shareholder_value_open_return"):
        raise ValueError("SOURCE_IDENTITY_VERSION_EPOCH_MISMATCH")
    if source_context["execution_semantics"]["scientific_contract_sha256"] != record["source_contract"]["sha256"]:
        raise ValueError("SOURCE_CONTRACT_BINDING_MISMATCH")
    return dict(status="SHARED_EXACT_REUSE", ordered_assets=list(assets),
        ordered_bank_uids=[uids[a] for a in assets], ordered_consumer_uids=[expected[a] for a in assets],
        asset_epochs=epochs, full_u_sha256=u_hash(current_u), horizon_sessions=5,
        actual_numeric_shape_check="DEFERRED_UNTIL_FORMAL_FREEZE", strict_PIT_promotion_eligible=False)


def raw_keys(ref):
    p = safe_d(ref["path"])
    # Shared footer guard executes before body projection. No score/rank/Y is projected.
    frame = pre2026(p, KEYS, "signal_date")
    pin(ref)
    frame["signal_date"] = pd.to_datetime(frame.signal_date).dt.normalize()
    if frame.signal_date.lt("2023-01-01").any() or frame.duplicated(["signal_date", "ticker"]).any():
        raise ValueError("C13_CALENDAR_AND_FULL_U_KEYS")
    for _, x in frame.groupby("signal_date", sort=True): current_map(x)
    return frame.sort_values(["signal_date", "ticker"]).reset_index(drop=True)


def _r3_source(record, source, design, node):
    if (node["assets"] != record["assets"] or node["asset_uids"] != record["asset_uids"]
        or node["asset_epochs"] != record["asset_epochs"] or node["cutoff"] != record["cutoff"]
        or node.get("declarations", {}).get("stock_horizons") != [5]
        or node.get("declarations", {}).get("observation_time_assumed") is not True):
        raise ValueError("R3_NATIVE_SUPPORT_IDENTITY_BINDING")
    # Projection of existing owner _receipt recipe, not a new publication authority.
    return dict(id="extended_shareholder_y5", version="FROZEN_EXISTING_BYTES_R3",
        sha256=source["sources"]["extended_shareholder_y5"]["sha256"], execution_semantics=dict(
        scientific_contract_sha256=record["source_contract"]["sha256"], status="FROZEN_HISTORY_MECHANISM_SOURCE_BOUND",
        return_coordinate="shareholder_value_open_return", identity_epoch="CURRENT_POOL_OBSERVED_UIDS:"+content_hash(record["asset_epochs"]),
        strict_PIT_promotion_eligible=False, historical_authority_status="UNKNOWN", quote_qualified=False,
        observation_time_assumed=True, assumed_observation_at=record["cutoff"],
        actual_snapshot_timestamp=design["actual_snapshot_timestamp"], benchmark_proxy_allowed=False),
        metadata_origin="EXISTING_FROZEN_OWNER_RECEIPT_RECIPE; ACTUAL_TYPED_RECEIPT_CHECK_DEFERRED_TO_LOAD")


def recompute_qualification(spec):
    """0 fit/state/outcome: recompute exact native-period full-U coverage from keys."""
    required = {"raw_keys", "namespace_source", "r3_bank", "r3_producer", "r3_support", "r3_source_inputs",
                "r3_design", "r4_bank", "r4_support", "r4_specification", "r4_authority"}
    if set(spec) != required: raise ValueError("EXACT_METADATA_SPEC_FIELDS_REQUIRED")
    frame = raw_keys(spec["raw_keys"])
    text = pin(spec["namespace_source"]).read_text(encoding="utf-8")
    if "members['security_uid']='CUSIP:'+members.cusip.astype(str).str.strip().str.upper()" not in text:
        raise ValueError("NAMESPACE_BRIDGE_SOURCE_NOT_PROVEN")
    docs = {k: readj(pin(v)) for k,v in spec.items() if k not in {"raw_keys", "namespace_source"}}
    days = [d.strftime("%Y-%m-%d") for d in sorted(frame.signal_date.unique())]
    if len(frame) != 313668 or len(days) != 752: raise ValueError("ORIGINAL_FULL_U_CALENDAR_REQUIRED")
    current = {d.strftime("%Y-%m-%d"): x for d,x in frame.groupby("signal_date", sort=True)}
    day_hashes = {day:u_hash(x) for day,x in current.items()}
    r4groups = {g["as_of"]:g for g in docs["r4_support"]["groups"]}
    r3nodes = {(n["method"],n["as_of"]):n for n in docs["r3_support"]["nodes"]}
    records = []
    for r in docs["r4_bank"]["states"]:
        if r["method"] not in {"SHR_HP", "SHR_EB", "SHR_CC", "SHR_FACTOR"}: continue
        g = r4groups[r["as_of"]]; q = g["metadata_qualification"]
        if q["assets"] != r["assets"] or q["uids"] != r["asset_uids"] or g["asset_epochs"] != r["asset_epochs"]:
            raise ValueError("R4_SUPPORT_FULL_DOMAIN_BINDING")
        records.append(dict(bank="R4", cadence="quarterly", record=r, source_context=q["source"],
            source_support_sha256=g["source_support_sha256"], metadata_proof_sha256=q["metadata_proof_sha256"],
            nominal_n=q["nominal_n"], overlap_n_div5_proxy=q["structural_n"],
            independent_effective_sample_size="UNKNOWN; floor(N/5) is only overlap upper bound",
            active_ff48_groups=q["active_groups"], missing_ff48=sum(v is None for v in q["industry_groups"].values()),
            market_source=q["market_source"], industry_source=q["industry_source"]))
    for r in docs["r3_bank"]["states"]:
        if r.get("stage_id") != "full" or r["method"] not in {"RD", "RB"}: continue
        n = r3nodes[(r["method"], r["as_of"])]
        records.append(dict(bank="R3", cadence="monthly", record=r,
            source_context=_r3_source(r,docs["r3_source_inputs"],docs["r3_design"],n),
            support_ref=spec["r3_support"], nominal_n="ORIGINAL_MIN30_PASS; vector not serialized in bank header",
            overlap_n_div5_proxy="UNKNOWN_METADATA_VECTOR", independent_effective_sample_size="UNKNOWN"))
    records.sort(key=lambda x:(x["bank"],x["record"]["as_of"],x["record"]["method"]))
    for s in records:
        r=s["record"]; start=utc(r["as_of"]).strftime("%Y-%m-%d")
        pin(r["source_contract"])
        if s["bank"]=="R4" and (r["support_ref"] != spec["r4_support"] or r["specification_ref"] != spec["r4_specification"]):
            # Paths may use Windows separators; compare physical pinned path + exact SHA.
            if (safe_d(r["support_ref"]["path"]) != safe_d(spec["r4_support"]["path"])
                or r["support_ref"]["sha256"] != spec["r4_support"]["sha256"]
                or safe_d(r["specification_ref"]["path"]) != safe_d(spec["r4_specification"]["path"])
                or r["specification_ref"]["sha256"] != spec["r4_specification"]["sha256"]):
                raise ValueError("R4_SUPPORT_SPEC_PIN_BINDING")
        matched=[]; continuity=True
        expected={a:namespace(r["asset_uids"][a]) for a in r["assets"]}
        for day in days:
            at=decision_close(day)
            if at < utc(r["as_of"]) or period(at,s["cadence"]) != period(r["as_of"],s["cadence"]): continue
            actual=current_map(current[day])
            # Any UID/gap exit since refresh prevents treating re-entry as same epoch.
            continuity = continuity and all(actual.get(a)==u for a,u in expected.items())
            try:
                qualify_current_u(r,current[day],at,s["cadence"],s["source_context"])
                if continuity: matched.append(day)
            except ValueError as e:
                if str(e) != "FULL_U_OR_UID_MISMATCH_NO_PADDING": raise
        s["eligible_dates"]=matched; s["eligible_dates_sha256"]=hashlib.sha256(("\n".join(matched)+"\n").encode()).hexdigest()
        s["carry_period"]="ONLY_NATIVE_"+s["cadence"].upper()+"_PERIOD_NO_CROSS_FAILED_REFRESH"
        s["ordered_consumer_uids"]=[namespace(r["asset_uids"][a]) for a in r["assets"]]
        s["artifact_values_read"]=False
    families={}
    for family in FAMILIES:
        if family in METHODS:
            bank,method,cadence=METHODS[family]
            refs=[s for s in records if s["bank"]==bank and s["record"]["method"]==method]
            eligible=sorted({day for s in refs for day in s["eligible_dates"]})
            mask=[day in set(eligible) for day in days]
            families[family]=dict(status="SHARED_EXACT_REUSE", qualification="PARTIAL_COMPLETE_FULL_U_DATES_ONLY",
                original_method=method, native_cadence=cadence, native_horizons=[5], state_count=len(refs),
                eligible_dates=eligible, eligible_date_count=len(eligible), blocked_date_count=len(days)-len(eligible),
                mask_packbits_big_hex=np.packbits(mask,bitorder="big").tobytes().hex(),
                per_year={str(y):sum(day.startswith(str(y)) for day in eligible) for y in (2023,2024,2025)},
                common_primary_complete=False, producer_fit_calls=0)
        else:
            reason=("SHR_CC is HP-marginal identity-shrunk native correlation, not classical sample constant-correlation" if family=="R05_CONSTANT_CORRELATION" else
                "SHR_FACTOR differs from frozen QQQ+FF48 hierarchical residual recipe; Jan2023 all FF48 absent, later partial; market-only fallback is not equivalence" if family=="R09_QQQ_FF48_HIERARCHICAL" else
                "RU retains sigma jackknife uncertainty, not standalone full-domain replica covariance matrices" if family=="R15_JACKKNIFE" else
                "R3 RE member bank is LW/OAS/PCA/RB, not C13 fixed LW/OAS/factor/EWMA members" if family=="R16_DISAGREEMENT" else
                "No exact native full-U artifact; original 252-origin full-domain support has assets below min30; all-past alternative full-domain input still needs owner qualification")
            families[family]=dict(status="BLOCKED_INPUT", reason=reason, producer_fit_calls=0,
                shared_owner_available=family not in {"R13_CVAR", "R16_DISAGREEMENT"},
                next_legal_action="SHARED_PRODUCER_FIT only after existing owner qualifies exact full-U input/recipe; no C risk platform")
    lines=[d+"|"+a+"|"+u for d,x in current.items() for a,u in sorted(current_map(x).items())]
    return dict(schema="C13_SHARED_RISK_METADATA_QUALIFICATION_V1", research_id=ID, status="METADATA_QUALIFIED_PARTIAL",
        spec=spec, namespace_bridge=dict(rule="CUSIP: + same stripped uppercase canonical CUSIP; no ticker stitching", source=spec["namespace_source"]),
        calendar=days, calendar_sha256=hashlib.sha256(("\n".join(days)+"\n").encode()).hexdigest(),
        full_u_keys_sha256=hashlib.sha256(("\n".join(lines)+"\n").encode()).hexdigest(), full_u_day_sha256=day_hashes,
        rows=len(frame), dates=len(days), state_refs=records, families=families,
        horizons_present=[5], horizons_unavailable=[3,10,20], coverage_2021_2022=False,
        exact_state_provenance="Original producer SHA is retained even if current source changed; artifact bytes guarded after formal freeze",
        counters=dict(new_fit_calls=0,new_state_estimations=0,numeric_outcome_reads=0,model_deserializations=0,test2026_rows_read=0,EF_access=0),
        mechanism_research_eligible=True, strict_PIT_promotion_eligible=False, account_qualification_granted=False,
        qualification_is_not_formal_freeze=True, no_primary_calendar_shrink=True, no_unknown_padding=True)


def admit_state(qualification, family, current_u, decision_at):
    if family not in METHODS: raise ValueError("FAMILY_HAS_NO_QUALIFIED_EXACT_STATE")
    day=utc(decision_at).strftime("%Y-%m-%d")
    if qualification.get("research_id")!=ID or qualification.get("status")!="METADATA_QUALIFIED_PARTIAL":
        raise ValueError("C13_QUALIFICATION_REQUIRED")
    if day not in qualification["families"][family]["eligible_dates"] or qualification["full_u_day_sha256"].get(day)!=u_hash(current_u):
        raise ValueError("DATE_OR_FULL_U_NOT_QUALIFIED_NO_PADDING")
    bank,method,cadence=METHODS[family]
    selected=[s for s in qualification["state_refs"] if s["bank"]==bank and s["record"]["method"]==method and day in s["eligible_dates"]]
    if len(selected)!=1: raise ValueError("EXACT_SINGLE_NATIVE_STATE_REQUIRED")
    s=selected[0]
    order=qualify_current_u(s["record"],current_u,decision_at,cadence,s["source_context"])
    return s,order


def load_state(family, *, design_ref, review_ref, qualification_ref, current_u, decision_at):
    """Load one existing RiskState after formal freeze; never estimate or pad."""
    d=readj(pin(design_ref)); review=readj(pin(review_ref)); q=readj(pin(qualification_ref))
    if (d.get("research_id")!=ID or d.get("risk_qualification")!=qualification_ref
        or d.get("strict_PIT_promotion_eligible") is not False or d.get("test2026_locked") is not True
        or review.get("status")!="PASS" or review.get("research_id")!=ID
        or review.get("design_sha256")!=design_ref["sha256"] or review.get("source_pins")!=d.get("sources")
        or d.get("sources",{}).get(str(Path(__file__).resolve()))!=sha(__file__)):
        raise ValueError("FORMAL_FREEZE_REQUIRED_BEFORE_PICKLE")
    for path,digest in d["sources"].items(): pin(dict(path=path,sha256=digest))
    for k,v in q["spec"].items(): pin(v)
    s,order=admit_state(q,family,current_u,decision_at); r=s["record"]
    artifact=pin(r["artifact"])
    import joblib
    state=joblib.load(artifact)
    from scripts.research.a2.risk.shared_risk_engine_r2 import SourceReceipt
    stored=state.source_receipt
    if isinstance(stored,dict):
        fields=set(SourceReceipt.__dataclass_fields__)
        extras=set(stored)-fields
        if extras-set(("cutoff","horizon_sessions")):
            raise ValueError("UNRECOGNIZED_PERSISTED_SOURCE_RECEIPT_FIELDS")
        if "cutoff" in stored and utc(stored["cutoff"])!=utc(state.cutoff):
            raise ValueError("PERSISTED_RECEIPT_CUTOFF_MISMATCH")
        if "horizon_sessions" in stored and (type(stored["horizon_sessions"]) is not int
                or stored["horizon_sessions"]!=state.horizon or stored["horizon_sessions"]!=5):
            raise ValueError("PERSISTED_RECEIPT_HORIZON_MISMATCH")
        receipt=SourceReceipt(**{k:v for k,v in stored.items() if k in fields})
    else:
        receipt=stored
    registered_status=r.get("status",r.get("original_status"))
    if (registered_status not in {"PASS_FROZEN_HISTORY_MECHANISM","CONDITIONAL_FROZEN_HISTORY_MECHANISM"}
        or state.status!=registered_status or state.risk_state_id!=r["risk_state_id"]
        or state.method!=r["method"] or list(state.assets)!=order["ordered_assets"]
        or state.horizon!=5 or utc(state.as_of)!=utc(r["as_of"]) or utc(state.cutoff)!=utc(r["cutoff"])
        or state.return_coordinate!="shareholder_value_open_return"
        or state.identity_epoch!=s["source_context"]["execution_semantics"]["identity_epoch"]
        or not isinstance(receipt,SourceReceipt)
        or receipt.cache_identity()!= {k:v for k,v in s["source_context"].items() if k!="metadata_origin"}
        or state.blocked_assets):
        raise ValueError("DESERIALIZED_STATE_IDENTITY_OR_SOURCE_CHANGED")
    receipt.validate(state.cutoff)
    from scripts.research.a2.risk.joint_risk_estimators import validate_covariance
    matrix=np.asarray(state.covariance,float)
    if matrix.shape!=(len(state.assets),len(state.assets)) or not np.isfinite(matrix).all():
        raise ValueError("DESERIALIZED_COVARIANCE_SHAPE_FINITE")
    validate_covariance(matrix,regularize=False)
    if r.get("covariance_sha256") and content_hash(matrix)!=r["covariance_sha256"]:
        raise ValueError("COVARIANCE_CONTENT_PIN_CHANGED")
    return state,order