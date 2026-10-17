"""Postdecision-only exact-key H5 projection for C13 descriptive diagnostics.

No label producer, risk estimator or historical authority is added. Existing
ProjectedReader owns predicate/column reads; existing observed-UID segment owner
proves continuity. Publication/revision clocks remain UNKNOWN frozen history.
"""
from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq
from scripts.research.a2.evaluation import joint_frozen_history_risk_r3 as owner
from scripts.research.a2.data import shared_risk_inputs_r3 as identity_owner
from scripts.research.a2.data import selector_shared_risk_consumer as namespace_owner
namespace=namespace_owner.namespace
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash
from scripts.research.a2.evaluation.selector_constrained_evidence import RESEARCH_ID,H5_COORDINATE

KEYS=["signal_date","security_uid","ticker"]
SOURCE_SHA={"labels":"555fef4dea2112809af44c388025852d9363bc7f55b40b2e4871f526568c9eb9",
 "identity":"db68417c267bf80daeb7f7564e91dc99e25ef9dc5c413c7b24583e273f05c174",
 "membership":"c03cc35f3569cb968c3d48cefd08488c75c02389e5e430d11526a0284ad2b637",
 "calendar":"38aaf0fad388e38aa87d04ab8ab10a004a889cd0ef20e7774be4a62bb3a155b5"}
META=tuple(c for c in identity_owner.STOCK_METADATA if c!="security_id")


def _require(ok,message):
    if not ok: raise ValueError(message)


def requested_keys(frame):
    _require(isinstance(frame,pd.DataFrame) and set(KEYS).issubset(frame)
        and not frame.columns.has_duplicates,"UNAMBIGUOUS_REQUESTED_KEYS_REQUIRED")
    k=frame[KEYS].copy();k.signal_date=pd.to_datetime(k.signal_date)
    _require(len(k)>0 and k.signal_date.notna().all() and k.signal_date.dt.tz is None
        and k.signal_date.eq(k.signal_date.dt.normalize()).all() and k.signal_date.lt("2026-01-01").all()
        and not k.duplicated(["signal_date","ticker"]).any()
        and not k.duplicated(["signal_date","security_uid"]).any()
        and all(k[c].map(lambda x:isinstance(x,str) and bool(x)).all() for c in KEYS[1:]),
        "PRE2026_UNIQUE_REQUESTED_UID_TICKER_KEYS_REQUIRED")
    return k.sort_values(KEYS,kind="stable").reset_index(drop=True)


def _ref(ref):
    _require(isinstance(ref,dict) and set(("path","sha256")).issubset(ref),"EXACT_PIN_REQUIRED")
    p=owner._safe_source(ref["path"]);owner._pin(p,ref["sha256"],"C13_POSTDECISION")
    return p


def _json_ref(ref):
    return owner.read_json(_ref(ref))


def gates(design_ref,review_ref,decision_gate_ref,keys):
    d=_json_ref(design_ref);r=_json_ref(review_ref);g=_json_ref(decision_gate_ref)
    _require(d.get("research_id")==RESEARCH_ID and d.get("official_freeze") is True
        and d.get("formal_freeze_applied") is True and d.get("mechanism_research_eligible") is True
        and d.get("strict_PIT_promotion_eligible") is False and d.get("test2026_locked") is True
        and d.get("new2026_estimation_authorized") is False,
        "FORMAL_MECHANISM_ONLY_FREEZE_REQUIRED_BEFORE_Y")
    _require(r.get("status")=="PASS" and r.get("design_sha256")==design_ref["sha256"]
        and r.get("source_pins")==d.get("sources"),"PINNED_FREEZE_REVIEW_REQUIRED_BEFORE_Y")
    _require(g.get("status")=="PASS" and g.get("research_id")==RESEARCH_ID
        and g.get("design_sha256")==design_ref["sha256"] and g.get("review_sha256")==review_ref["sha256"]
        and g.get("decision_frozen") is True and g.get("outcome_reads_before_gate")==0
        and g.get("requested_keys_sha256")==content_hash(keys),"TERMINAL_DECISION_AND_KEY_FREEZE_REQUIRED_BEFORE_Y")
    _require(all(name in g for name in ("score_assembly_ref","solve_ledger_ref")),"TERMINAL_ARTIFACT_PINS_REQUIRED")
    for name in ("score_assembly_ref","solve_ledger_ref"):_ref(g[name])
    source_pins=d["sources"]
    for p in (Path(__file__),Path(owner.__file__),Path(identity_owner.__file__),Path(namespace_owner.__file__)):
        _require(source_pins.get(str(p))==owner.sha(p),"EXACT_OUTCOME_READER_SOURCE_PIN_REQUIRED")
    refs=d["h5_sources"]
    _require(set(refs)==set(SOURCE_SHA) and all(refs[n].get("sha256")==h for n,h in SOURCE_SHA.items()),
        "ORIGINAL_FOUR_H5_SOURCES_REQUIRED")
    return d,refs


class H5ProjectedReader(owner.ProjectedReader):
    """Initialize four qualified sources; inherit the sole existing read method."""
    def __init__(self,refs):
        self.phase,self.sources,self.audit="support",refs,[];self.datasets={}
        for name,ref in refs.items():
            p=_ref(ref);f=pq.ParquetFile(p)
            clocks=("signal_date","execution_date","label_end_date","label_mature_date") if name=="labels" else (
                "trade_date",) if name=="calendar" else ("signal_date",)
            for col in clocks:
                i=f.schema_arrow.get_field_index(col);_require(i>=0,"SOURCE_CLOCK_REQUIRED")
                for rg in range(f.metadata.num_row_groups):
                    group=f.metadata.row_group(rg);s=group.column(i).statistics
                    _require(s is not None and s.null_count is not None,"UNKNOWN_SOURCE_FOOTER")
                    if col!="signal_date" and name=="labels" and s.null_count==group.num_rows:continue
                    _require(s.has_min_max and pd.Timestamp(s.max)<pd.Timestamp("2026-01-01")
                        and (s.null_count==0 or name=="labels" and col!="signal_date"),"PHYSICAL_PRE2026_SOURCE_REQUIRED")
            self.datasets[str(p)]=ds.dataset(p,format="parquet")


def _native_uid(value):
    if not isinstance(value,str):raise ValueError("UNBOUND_UID")
    return namespace(value[6:] if value.startswith("CUSIP:") else value)


def qualify_metadata(keys,calendar,origin,membership,labels):
    """No numeric outcome. Missing, ambiguous or boundary-crossing keys remain."""
    days,closes=identity_owner._calendar(calendar)
    _require(set(("signal_date","ticker","security_id","cusip")).issubset(origin)
        and set(("signal_date","ticker","cusip")).issubset(membership)
        and set(META).issubset(labels),"H5_IDENTITY_AND_CLOCK_METADATA_REQUIRED")
    origin=origin.copy();membership=membership.copy();labels=labels.copy()
    for f in (origin,membership,labels):
        f.signal_date=pd.to_datetime(f.signal_date)
        _require(f.signal_date.notna().all() and f.signal_date.dt.tz is None
            and f.signal_date.isin(days).all(),"PRE2026_CALENDAR_METADATA_REQUIRED")
    duplicates={id(f):set(f.loc[f.duplicated(["signal_date","ticker"],keep=False),["signal_date","ticker"]].itertuples(index=False,name=None))
                for f in (origin,membership,labels)}
    oi=origin.drop_duplicates(["signal_date","ticker"],keep=False).set_index(["signal_date","ticker"])
    li=labels.drop_duplicates(["signal_date","ticker"],keep=False).set_index(["signal_date","ticker"])
    history=membership.loc[~membership.duplicated(["signal_date","ticker"],keep=False),["signal_date","ticker","cusip"]].copy()
    def uid(v):
        try:return namespace(v.strip().upper())
        except (ValueError,AttributeError):return None
    history["security_id"]=history.cusip.map(uid)
    history["available_at"]=history.signal_date.map(identity_owner._clock)
    by_ticker={t:f for t,f in history.groupby("ticker",sort=False)}
    rows=[]
    for row in keys.itertuples(index=False):
        date,security,ticker=row.signal_date,row.security_uid,row.ticker;key=(date,ticker)
        out=dict(signal_date=date,security_uid=security,ticker=ticker,return_value=np.nan,
            qualified=False,qualification_reason="BLOCKED_IDENTITY_OR_LABEL_METADATA_MISSING",label_coordinate=H5_COORDINATE)
        if key not in oi.index or key not in li.index:rows.append(out);continue
        o,l=oi.loc[key],li.loc[key];i=days.get_loc(date)
        if i<1 or i+6>=len(days):out["qualification_reason"]="BLOCKED_PREDECESSOR_OR_H5_CALENDAR";rows.append(out);continue
        try:origin_uid=_native_uid(o.security_id)
        except ValueError:origin_uid=None
        if origin_uid!=security or uid(o.cusip)!=security:
            out["qualification_reason"]="BLOCKED_ORIGIN_UID_MISMATCH";rows.append(out);continue
        if "security_id_type" in o and o.security_id_type!="CUSIP":
            out["qualification_reason"]="BLOCKED_NON_CUSIP_ORIGIN";rows.append(out);continue
        window=days[i-1:i+7]
        if any((d,ticker) in duplicates[id(membership)] for d in window):
            out["qualification_reason"]="BLOCKED_AMBIGUOUS_MEMBERSHIP";rows.append(out);continue
        cutoff=identity_owner._clock(days[i+6])+pd.Timedelta(nanoseconds=1)
        local=by_ticker.get(ticker,history.iloc[:0])
        local=local.loc[local.signal_date.between(window[0],window[-1])]
        segment=identity_owner._segments(local,days,closes,(ticker,),
            {ticker:security},{ticker:"OBSERVED_UID_WINDOW"},cutoff)[ticker]
        if segment is None or segment[0]>i-1:
            out["qualification_reason"]="BLOCKED_UID_BOUNDARY_OR_MEMBERSHIP_GAP";rows.append(out);continue
        execution,end,mature=(pd.Timestamp(l[c]) for c in ("execution_date","label_end_date","label_mature_date"))
        good=(execution==days[i+1] and end==days[i+6] and not pd.isna(mature) and mature>=end
            and mature<pd.Timestamp("2026-01-01") and l.label_coordinate==H5_COORDINATE
            and identity_owner._true(l.label_available) and identity_owner._true(l.endpoint_pair_available)
            and identity_owner._false(l.label_unsupported_common_event))
        out.update(execution_date=execution,label_end_date=end,label_mature_date=mature,
            predecessor_uid=security,predecessor_date=days[i-1],identity_window_start=days[segment[0]],
            qualified=bool(good),qualification_reason="QUALIFIED_FROZEN_HISTORY_METADATA" if good else "BLOCKED_H5_CLOCK_OR_EVENT_FLAGS")
        rows.append(out)
    return pd.DataFrame(rows)


def read_h5(design_ref,review_ref,decision_gate_ref,requested_keys_df):
    keys=requested_keys(requested_keys_df);_,refs=gates(design_ref,review_ref,decision_gate_ref,keys)
    reader=H5ProjectedReader(refs)
    cal=reader.read("calendar",("trade_date",),date_field="trade_date").trade_date
    days,_=identity_owner._calendar(cal);earliest=days.get_indexer([keys.signal_date.min()])[0]
    last=days.get_indexer([keys.signal_date.max()])[0]
    _require(earliest>=0 and last>=0,"REQUESTED_KEYS_ON_LEGAL_CALENDAR_REQUIRED")
    tickers=tuple(sorted(keys.ticker.unique()));start=days[max(0,earliest-1)]
    stop=days[last+7] if last+7<len(days) else None
    members=reader.read("membership",("signal_date","ticker","cusip"),date_field="signal_date",start=start,stop=stop,tickers=tickers)
    origins=[];labels=[]
    for date,g in keys.groupby("signal_date",sort=True):
        names=tuple(g.ticker)
        origins.append(reader.read("identity",("signal_date","ticker","security_id","security_id_type","cusip"),date_field="signal_date",day=date,tickers=names))
        labels.append(reader.read("labels",META,date_field="signal_date",day=date,tickers=names))
    out=qualify_metadata(keys,cal,pd.concat(origins,ignore_index=True),members,pd.concat(labels,ignore_index=True))
    reader.phase="postdecision";reads=0
    for date,g in out.loc[out.qualified].groupby("signal_date",sort=True):
        values=reader.read("labels",("signal_date","ticker","y_open5"),date_field="signal_date",day=date,tickers=tuple(g.ticker))
        _require(not values.duplicated(["signal_date","ticker"]).any(),"AMBIGUOUS_H5_VALUE_KEYS")
        mapped=g[["signal_date","ticker"]].merge(values,on=["signal_date","ticker"],how="left",validate="one_to_one")
        v=pd.to_numeric(mapped.y_open5,errors="coerce").to_numpy(float);finite=np.isfinite(v)
        out.loc[g.index,"return_value"]=np.where(finite,v,np.nan);out.loc[g.index,"qualified"]=finite
        out.loc[g.index[~finite],"qualification_reason"]="BLOCKED_NONFINITE_H5_VALUE";reads+=len(g)
    for ref in refs.values():_ref(ref)
    receipt=dict(schema="C13_POSTDECISION_H5_SOURCE_RECEIPT_V1",research_id=RESEARCH_ID,
        design_ref=design_ref,review_ref=review_ref,decision_gate_ref=decision_gate_ref,source_refs=refs,
        requested_keys_sha256=content_hash(keys),requested_keys=len(keys),numeric_origin_keys=reads,
        qualified_finite_keys=int(out.qualified.sum()),blocked_keys=int((~out.qualified).sum()),projections=reader.audit,
        return_coordinate=H5_COORDINATE,identity_policy="NO_CROSS_IDENTITY_STITCHING; predecessor through endpoint same observed CUSIP",
        publication_revision_authority="UNKNOWN",available_at_basis="assumed policy clock; not historical vintage proof",
        strict_PIT_promotion_eligible=False,outcome_reads_before_gate=0,new_fits=0,new_state_estimations=0,test2026_reads=0)
    return out,receipt
