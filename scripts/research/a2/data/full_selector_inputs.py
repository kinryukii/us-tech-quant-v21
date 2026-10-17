"""Full-U BASE32 adapter for the authorized fixed-policy C task.

Membership is fixed before model output. Existing pure feature and four-horizon
label producers remain authoritative; this adapter changes only representation,
projection and qualification. It never reads a score as a new learner feature.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.data.joint_input_binding import guard_parquet, sha256
from scripts.research.a2.training.stateful_inputs import FEATURES
from scripts.research.a2.training.selector_challenge import putj, now

ID = "V24_C_FULL_SELECTOR_FIXED_POLICY_FAST_R1"
REPO = Path(__file__).resolve().parents[4]
BOUNDARY = pd.Timestamp("2026-01-01")
KEYS = ["signal_date", "security_uid"]
SOURCES = {
    "members": {"path": "D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/universe/daily_eligible_universe_membership.parquet", "sha256": "c03cc35f3569cb968c3d48cefd08488c75c02389e5e430d11526a0284ad2b637"},
    "features": {"path": "D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/A/score_rank_ledger.parquet", "sha256": "0cb9a5acaa0c9f9e2170bf3964292388395c5bfce446fb25a4ad3dcdcc1d1b3b"},
    "hlabels": {"path": "D:/us-tech-quant-backtests/V24/20261003T092314+0000_4d0ba1cd/derived/horizon_labels.parquet", "sha256": "e32bb2ecf57e7cb5bf1931481055e7ddee5969082fc89ee101aaf9e62441aa61"},
    "raw": {"path": "D:/us-tech-quant-backtests/V24/20261001T091119+0000_126f67f0/predictions/scores_RAW_A2_SCORE_IN_COMMON_13F_UNIVERSE_pre2026.parquet", "sha256": "bdd3191c8537b419c187ecd274c5ae43b6dfdaf5d55d0015c5ca020b1b38274b"},
    "calendar": {"path": "D:/us-tech-quant-results/A2_STATEFUL_ACTION_AND_CASH_PRE2026_TEST2026_R1/cache/calendar_r1.parquet", "sha256": "38aaf0fad388e38aa87d04ab8ab10a004a889cd0ef20e7774be4a62bb3a155b5"},
}
LABEL_FIELDS = ["target", "ER_3D", "ER_5D", "ER_10D", "ER_20D"]
CLOCKS = ["target_end_date", *["target_end_date_" + str(h) + "d" for h in (3, 5, 10, 20)]]
CUTS = ("2023-04-01", "2023-07-01", "2024-01-01", "2024-07-01", "2025-01-01")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def keys_digest(frame):
    from hashlib import sha256 as digest
    rows = frame[KEYS].astype(str).sort_values(KEYS).to_csv(index=False, lineterminator="\n")
    return digest(rows.encode()).hexdigest()


def fixed_membership(members, features):
    m = members.copy()
    m["signal_date"] = pd.to_datetime(m.signal_date)
    f = features.copy()
    f["signal_date"] = pd.to_datetime(f.signal_date)
    require(not m.duplicated(["signal_date", "ticker"]).any(), "DUPLICATE_MEMBERSHIP_KEY")
    require(m.cusip.notna().all(), "SOURCE_UID_REQUIRED_NO_NEW_IDENTITY_GUESS")
    cusips = m.cusip.astype(str).str.strip().str.upper()
    require(cusips.ne("").all(), "EMPTY_SOURCE_UID_FORBIDDEN")
    m["security_uid"] = "CUSIP:" + cusips
    require(not m.duplicated(KEYS).any(), "DUPLICATE_DAILY_UID")
    require(not f.duplicated(["signal_date", "ticker"]).any(), "DUPLICATE_FEATURE_KEY")
    result = m.merge(f[["signal_date", "ticker", *FEATURES]], on=["signal_date", "ticker"],
                     how="left", validate="one_to_one", indicator=True)
    values = result[list(FEATURES)].to_numpy(float)
    require(not np.isinf(values).any(), "INFINITE_BASE32_INPUT")
    result["feature_source_present"] = result["_merge"].eq("both")
    result["missing_feature_count"] = (~np.isfinite(values)).sum(axis=1)
    result["feature_qualification"] = np.where(result.feature_source_present, "SOURCE_PRESENT_NAN_PAST_IMPUTATION", "SOURCE_NOT_TESTABLE")
    require(result.groupby("signal_date").U_t_fingerprint.nunique().eq(1).all(), "AMBIGUOUS_FULL_U_FINGERPRINT")
    return result.drop(columns="_merge").sort_values(KEYS, kind="stable").reset_index(drop=True)


def mature_mask(keys, labels, cutoff):
    c = pd.Timestamp(cutoff)
    require(c <= BOUNDARY, "TRAINING_CUTOFF_OUTSIDE_PRE2026")
    l = labels.copy()
    l["signal_date"] = pd.to_datetime(l.signal_date)
    for column in CLOCKS:
        l[column] = pd.to_datetime(l[column])
    require(not l.duplicated(KEYS).any(), "DUPLICATE_LABEL_KEY")
    joined = keys.merge(l, on=KEYS, how="left", suffixes=("", "_label"), validate="one_to_one")
    present = joined.target_end_date.notna()
    require(joined.loc[present, "U_t_fingerprint"].eq(joined.loc[present, "U_t_fingerprint_label"]).all(),
            "LABEL_FULL_U_FINGERPRINT_MISMATCH")
    require(joined.loc[present, "target_end_date"].eq(joined.loc[present, "target_end_date_20d"]).all(),
            "MEAN_ER_MATURITY_CHANGED")
    endpoints = joined[["target_end_date_3d", "target_end_date_5d", "target_end_date_10d", "target_end_date_20d"]]
    legal_clock = endpoints.notna().all(axis=1) & endpoints.iloc[:, 0].gt(joined.signal_date)
    for i in range(1, 4):
        legal_clock &= endpoints.iloc[:, i].gt(endpoints.iloc[:, i-1])
    require(legal_clock.loc[present].all(), "ORDERED_FORWARD_HORIZON_CLOCK_REQUIRED")
    available = joined.signal_date.lt(c) & joined[CLOCKS].notna().all(axis=1) & joined[CLOCKS].lt(c).all(axis=1)
    if "feature_source_present" in joined:
        available &= joined.feature_source_present
    return joined, available


def _checked_run(run):
    run = Path(run).resolve()
    assert_safe_output_path(run, kind="backtest", paths=resolve(REPO))
    cfg = json.loads((run / "run_config.json").read_text(encoding="utf-8"))
    require(cfg.get("research_id") == ID and cfg.get("research_only") is True, "NEW_TASK_ID_REQUIRED")
    require(cfg.get("strict_PIT_promotion_eligible") is False and cfg.get("training_cutoff_exclusive") == "2026-01-01",
            "RESEARCH_TIME_LOCK_REQUIRED")
    return run, cfg


def qualify(run):
    run, cfg = _checked_run(run)
    manifest = json.loads((run / "input_manifest.json").read_text(encoding="utf-8"))
    require(not (run / "DESIGN_FREEZE.json").exists(), "NO_INPUT_REWRITE_AFTER_FREEZE")
    frames, receipts = {}, {}
    # All physical time bounds and hashes pass before any numeric feature read.
    for name, ref in SOURCES.items():
        clocks = ["trade_date"] if name == "calendar" else ["signal_date", *CLOCKS] if name == "hlabels" else ["signal_date"]
        _, receipts[name] = guard_parquet(ref["path"], ref["sha256"], clocks)
    def project(name, columns):
        path = Path(SOURCES[name]["path"])
        before = (path.stat().st_size, path.stat().st_mtime_ns)
        frame = pq.read_table(path, columns=columns).to_pandas()
        require(before == (path.stat().st_size, path.stat().st_mtime_ns), "INPUT_CHANGED_DURING_PROJECTION")
        return frame
    members = project("members", ["signal_date", "ticker", "cusip", "U_t_fingerprint", "active_13f_quarter"])
    features = project("features", ["signal_date", "ticker", *FEATURES])
    full = fixed_membership(members, features)
    label_keys = project("hlabels", [*KEYS, "U_t_fingerprint", *CLOCKS])
    label_keys.signal_date = pd.to_datetime(label_keys.signal_date)
    calendar = pd.DatetimeIndex(pd.to_datetime(project("calendar", ["trade_date"]).trade_date))
    require(not calendar.has_duplicates and calendar.is_monotonic_increasing, "CALENDAR_INVALID")
    outer_dates = calendar[(calendar >= "2023-01-01") & (calendar < BOUNDARY)]
    outer = full.loc[full.signal_date.isin(outer_dates)]
    require(len(outer_dates) == 752 and pd.DatetimeIndex(sorted(outer.signal_date.unique())).equals(outer_dates),
            "COMMON_752_SESSION_DOMAIN_NOT_COMPLETE")
    raw_keys = project("raw", [*KEYS, "ticker", "U_t_fingerprint"])
    raw_keys.signal_date = pd.to_datetime(raw_keys.signal_date)
    require(not raw_keys.duplicated(KEYS).any(), "RAW_DUPLICATE_KEY")
    raw_binding = raw_keys.merge(outer[KEYS+["ticker", "U_t_fingerprint"]], on=KEYS, how="outer", suffixes=("_raw", "_full"), indicator=True, validate="one_to_one")
    require(raw_binding["_merge"].eq("both").all() and raw_binding.ticker_raw.eq(raw_binding.ticker_full).all() and raw_binding.U_t_fingerprint_raw.eq(raw_binding.U_t_fingerprint_full).all(), "RAW_EXACT_FULL_U_IDENTITY_BINDING_REQUIRED")
    training = {}
    for cut in CUTS:
        joined, mask = mature_mask(full.drop(columns=list(FEATURES)), label_keys, cut)
        pool = joined.loc[mask]
        require(not pool.empty, "EMPTY_MATURE_TRAINING_POOL")
        training[cut] = dict(rows=len(pool), dates=pool.signal_date.nunique(), key_sha256=keys_digest(pool),
                             max_signal_date=str(pool.signal_date.max()), max_label_end=str(pool.target_end_date.max()))
    keys = full.drop(columns=list(FEATURES))
    out = run / "derived/full_U_keys.parquet"
    require(not out.exists(), "PRESERVE_EXISTING_FULL_U_PREPARATION")
    keys.to_parquet(out, index=False)
    artifact = dict(path=str(out), sha256=sha256(out), rows=len(keys))
    report = dict(status="FULL_U_BASE32_PREPARED_LABEL_NUMERIC_FREE", research_id=ID, prepared_at=now(),
                  source_receipts=receipts, feature_order=list(FEATURES), full_U_keys=artifact,
                  rows=len(full), daily_universes=full.signal_date.nunique(), outer_rows=len(outer),
                  outer_sessions=len(outer_dates), year_sessions={str(y):int((outer_dates.year == y).sum()) for y in (2023,2024,2025)},
                  prediction_sessions_2024_2025=int((outer_dates.year >= 2024).sum()),
                  source_missing_stock_days=int((~full.feature_source_present).sum()),
                  legal_nan_stock_days=int(full.missing_feature_count.gt(0).sum()),
                  raw_full_U_key_match=keys_digest(raw_keys) == keys_digest(outer),
                  training=training, numerical_target_reads=0, prediction_fits=0, risk_estimates=0, accounts=0,
                  universe_defined_before_model_output=True, post2025_rows_read=0,
                  feature_missing_handling="PAST_DATE_BALANCED_SCALER_MEAN_IMPUTATION_KEEP32_NO_ROW_DROP")
    manifest.update(input_sources=SOURCES, input_qualification=report, frozen_feature_order=list(FEATURES))
    putj(run / "input_manifest.json", manifest)
    plan = json.loads((run / "EXEC_PLAN.json").read_text(encoding="utf-8"))
    plan["progress"].update(complete_full_U_stock_days=len(full), complete_outer_universe_dates=len(outer_dates),
                            base32_input_build_complete=True)
    plan["artifacts"]["full_U_keys"] = artifact
    plan["completed_expensive_stages"].append("FULL_U_BASE32_INPUT_QUALIFICATION_LABEL_NUMERIC_FREE")
    plan["exact_resume_point"] = "Integrate source owners and independently freeze generated finite DAG before first learning."
    putj(run / "EXEC_PLAN.json", plan)
    print(json.dumps({k:v for k,v in report.items() if k not in ("source_receipts", "training", "feature_order")},default=str),flush=True)
    return report


class FullSelectorReader:
    def __init__(self, run):
        self.run, self.cfg = _checked_run(run)
        self.manifest = json.loads((self.run / "input_manifest.json").read_text(encoding="utf-8"))
        self.qualification = self.manifest["input_qualification"]
        ref = self.qualification["full_U_keys"]
        require(sha256(ref["path"]) == ref["sha256"], "FULL_U_KEYS_CHANGED")
        self.keys = pd.read_parquet(ref["path"])
        self.keys.signal_date = pd.to_datetime(self.keys.signal_date)

    def features(self, start, stop):
        require(pd.Timestamp(start) < pd.Timestamp(stop) <= BOUNDARY, "FEATURE_WINDOW_INVALID")
        ref = self.manifest["input_sources"]["features"]
        guard_parquet(ref["path"], ref["sha256"], ["signal_date"])
        vector = pd.read_parquet(ref["path"], columns=["signal_date", "ticker", *FEATURES],
                                 filters=[("signal_date", ">=", pd.Timestamp(start)), ("signal_date", "<", pd.Timestamp(stop))])
        vector.signal_date = pd.to_datetime(vector.signal_date)
        keys = self.keys.loc[self.keys.signal_date.ge(start) & self.keys.signal_date.lt(stop)]
        out = keys.merge(vector, on=["signal_date", "ticker"], how="left", validate="one_to_one")
        require(len(out) == len(keys) and not np.isinf(out[list(FEATURES)].to_numpy(float)).any(), "FULL_U_FEATURE_PROJECTION_CHANGED")
        return out.sort_values(KEYS,kind="stable").reset_index(drop=True)

    def labels(self, start, cutoff):
        design_path = self.run / "DESIGN_FREEZE.json"
        gate_path = self.run / "FREEZE_ACCEPTANCE.json"
        require(design_path.exists() and gate_path.exists(), "INDEPENDENT_SCIENCE_RESOURCE_FREEZE_REQUIRED_BEFORE_TARGET_READ")
        design = json.loads(design_path.read_text(encoding="utf-8"))
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        require(design.get("inputs") == self.manifest["input_sources"] and design.get("full_U_keys") == self.qualification["full_U_keys"]
                and gate.get("input_manifest_sha256") == sha256(self.run / "input_manifest.json"), "FROZEN_INPUT_AUTHORITY_CHANGED")
        require(design.get("research_id") == ID and gate.get("status") == "PASS"
                and gate.get("design_sha256") == sha256(design_path), "FORMAL_FREEZE_GATE_INVALID")
        require(cutoff in (*design["cutoffs"], "2026-01-01") and pd.Timestamp(start) < pd.Timestamp(cutoff) <= BOUNDARY,
                "UNFROZEN_LABEL_WINDOW")
        ref = self.manifest["input_sources"]["hlabels"]
        guard_parquet(ref["path"], ref["sha256"], ["signal_date", *CLOCKS])
        filters = [("signal_date", ">=", pd.Timestamp(start)), ("signal_date", "<", pd.Timestamp(cutoff))]
        filters.extend((column, "<", pd.Timestamp(cutoff)) for column in CLOCKS)
        labels = pd.read_parquet(ref["path"], columns=[*KEYS, "U_t_fingerprint", *CLOCKS, *LABEL_FIELDS], filters=filters)
        labels.signal_date = pd.to_datetime(labels.signal_date)
        require(np.isfinite(labels[LABEL_FIELDS].to_numpy(float)).all(), "NONFINITE_MATURE_LABEL")
        require(np.allclose(labels.target, labels[LABEL_FIELDS[1:]].mean(axis=1), rtol=0, atol=1e-12), "ORIGINAL_EQUAL_MEAN_ER_CHANGED")
        joined, mask = mature_mask(self.keys, labels, cutoff)
        require(mask.loc[joined.signal_date.ge(start)].sum() == len(labels), "LABEL_NOT_BOUND_TO_FIXED_FULL_U")
        return labels


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--prepare", action="store_true", required=True)
    qualify(Path(parser.parse_args().run))


# Thin new-task risk input projection. Original B readers, source pins and label
# mathematics are unchanged. New observations require explicit frozen source refs.
RISK_IDENTITY_COLUMNS = ("ticker", "signal_date", "security_id", "available_at",
                         "identity_qualified", "source_identity")
RISK_STORED_H5_COLUMNS = (
    "ticker", "signal_date", "security_id", "execution_date", "label_end_date",
    "label_mature_date", "label_coordinate", "label_available",
    "label_unsupported_common_event", "endpoint_pair_available", "identity_epoch",
    "available_at", "y_open5",
)


def fixed_policy_risk_identity_epochs(history, calendar):
    """Source-only continuous UID segments; missing sessions break, never carry."""
    from scripts.research.a2.data.shared_risk_inputs_r3 import _calendar, _clock, _time
    days, _ = _calendar(calendar)
    require(isinstance(history, pd.DataFrame) and
            set(RISK_IDENTITY_COLUMNS) <= set(history), "RISK_IDENTITY_METADATA_REQUIRED")
    frame = history[list(RISK_IDENTITY_COLUMNS)].copy()
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    require(frame.signal_date.notna().all() and frame.signal_date.lt(BOUNDARY).all()
            and frame.signal_date.isin(days).all()
            and frame.signal_date.eq(frame.signal_date.dt.normalize()).all(),
            "RISK_IDENTITY_PRE2026_LEGAL_DATE_REQUIRED")
    frame["available_at"] = frame.available_at.map(_time)
    require(frame.available_at.lt(pd.Timestamp("2026-01-01",tz="UTC")).all(),
            "RISK_IDENTITY_FUTURE_AVAILABILITY")
    require(not frame.duplicated(["ticker","signal_date"]).any(),
            "RISK_IDENTITY_AMBIGUOUS_SESSION")
    position = {day:i for i,day in enumerate(days)}
    frame = frame.sort_values(["ticker","signal_date"],kind="stable").reset_index(drop=True)
    epochs = []
    previous = {}
    for row in frame.itertuples(index=False):
        uid = row.security_id
        qualified = (isinstance(row.identity_qualified,(bool,np.bool_))
                     and bool(row.identity_qualified)
                     and isinstance(uid,str) and uid and not uid.upper().startswith("UNKNOWN")
                     and isinstance(row.source_identity,str) and bool(row.source_identity)
                     and row.available_at <= _clock(row.signal_date))
        prior = previous.get(row.ticker)
        continued = (qualified and prior is not None and prior["qualified"]
                     and prior["position"]+1 == position[row.signal_date]
                     and prior["uid"]==uid and prior["source"]==row.source_identity)
        epoch = (prior["epoch"] if continued else
                 str(uid)+"::OBSERVED_SOURCE_SEGMENT_"+row.signal_date.strftime("%Y%m%d"))
        epochs.append(epoch if qualified else None)
        previous[row.ticker]=dict(uid=uid,source=row.source_identity,
            position=position[row.signal_date],qualified=qualified,epoch=epoch)
    frame["identity_epoch"] = epochs
    frame["source_session_qualified"] = frame.identity_epoch.notna()
    return frame


def fixed_policy_risk_metadata_contexts(full_U_keys, calendar, identity_history,
                                       source_support_events, *, security_coordinate,
                                       families=None):
    """Freeze entire historical training/OOF/policy union before numeric access.

    source_support_events are explicit date-asof pin/qualification events, not
    daily label appends or performance triggers. No price/label values consumed.
    """
    import copy
    from scripts.research.a2.data.shared_risk_inputs_r3 import _calendar, _clock, _time
    from scripts.research.a2.risk.mechanism_risk_adapter import (
        FIXED_POLICY_RISK_FAMILIES, fixed_policy_risk_refresh_nodes, content_hash)
    families = tuple(families or FIXED_POLICY_RISK_FAMILIES)
    days, closes = _calendar(calendar)
    require(bool(security_coordinate) and isinstance(security_coordinate,str),
            "EXACT_RISK_SECURITY_COORDINATE")
    require({"signal_date","ticker","security_uid","U_t_fingerprint"} <= set(full_U_keys),
            "FIXED_FULL_U_SOURCE_KEYS_REQUIRED")
    keys=full_U_keys[["signal_date","ticker","security_uid","U_t_fingerprint"]].copy()
    keys["signal_date"]=pd.to_datetime(keys.signal_date)
    require(keys.signal_date.lt(BOUNDARY).all() and keys.signal_date.isin(days).all()
            and not keys.duplicated(["signal_date","ticker"]).any()
            and not keys.duplicated(["signal_date","security_uid"]).any(),
            "EXACT_FULL_U_PRE2026_UID_AXIS")
    hist=fixed_policy_risk_identity_epochs(identity_history,days)
    lookup=hist.set_index(["signal_date","ticker"])
    membership=keys[["ticker","signal_date","security_uid"]].rename(columns={"security_uid":"security_id"})
    membership["available_at"]=membership.signal_date.map(_clock)
    membership["identity_qualified"]=True
    membership["source_identity"]="FROZEN_FULL_U_MEMBERSHIP_METADATA"
    membership=fixed_policy_risk_identity_epochs(membership,days).set_index(["signal_date","ticker"])
    events=list(source_support_events)
    require(bool(events),"RISK_SOURCE_SUPPORT_EVENTS_REQUIRED")
    last=None
    for event in events:
        at=_time(event["effective_at"])
        require(at<pd.Timestamp("2026-01-01",tz="UTC") and
                (last is None or at>last),"INCREASING_PRE2026_SOURCE_EVENTS")
        require(set(event["family_source_support"])==set(families),
                "SOURCE_EVENT_FIXED_FAMILY_MAP")
        last=at
    events=[{**e,"effective_at":_time(e["effective_at"])} for e in events]
    rows=[]; coverage=[]; day_map=[]
    positions={d:i for i,d in enumerate(days)}
    for day,part in keys.groupby("signal_date",sort=True):
        i=positions[day]
        require(i>=1,"PRIOR_LEGAL_CLOSE_REQUIRED")
        at,cutoff=closes[i],closes[i-1]
        active=[e for e in events if e["effective_at"]<=cutoff]
        require(bool(active),"SOURCE_EVENT_UNAVAILABLE_AT_CUTOFF")
        event=active[-1]
        part=part.sort_values("ticker",kind="stable")
        assets=tuple(part.ticker)
        uids=dict(zip(assets,part.security_uid))
        require(part.U_t_fingerprint.nunique()==1,"ONE_DAILY_FULL_U_FINGERPRINT")
        epochs={}; unresolved=[]
        for ticker,uid in uids.items():
            index=(day,ticker)
            if index in lookup.index:
                record=lookup.loc[index]
                require(record.security_id==uid,"CURRENT_FULL_U_UID_SOURCE_CONFLICT")
                if record.source_session_qualified and record.available_at<=at:
                    epochs[ticker]=record.identity_epoch
                    continue
            # Current membership is an observed UID, not proof of its past prices.
            # The node remains on the full axis; producer must report this gap.
            epochs[ticker]=membership.loc[(day,ticker),"identity_epoch"]
            unresolved.append(ticker)
        # H5 exits at i+6 and matures at that legal Close; all clocks must be
        # strictly before the previous Close, never just origin < cutoff.
        legal_origins=days[:max(i-7,0)][-252:]
        row=dict(decision_at=at.isoformat(),assets=assets,asset_uids=uids,
            asset_epochs=epochs,security_coordinate=security_coordinate,
            family_source_support=copy.deepcopy(event["family_source_support"]))
        rows.append(row)
        coverage.append(dict(decision_at=at.isoformat(),cutoff=cutoff.isoformat(),
            full_u_fingerprint=part.U_t_fingerprint.iloc[0],full_u_count=len(assets),
            unresolved_identity_count=len(unresolved),unresolved_identity_assets=unresolved,
            matured_h5_origin_count=len(legal_origins),
            window_start=None if len(legal_origins)==0 else legal_origins[0].isoformat(),
            window_end=None if len(legal_origins)==0 else legal_origins[-1].isoformat(),
            full_252_calendar_window=len(legal_origins)==252,
            numeric_reads=0))
        day_map.append(dict(decision_at=at.isoformat(),cutoff=cutoff.isoformat(),
            ordered_assets=list(assets),asset_uids=copy.deepcopy(uids),
            asset_epochs=copy.deepcopy(epochs),
            family_source_support=copy.deepcopy(row["family_source_support"]),
            metadata_sha256=content_hash(row)))
    plan=fixed_policy_risk_refresh_nodes(rows,families=families)
    active_by_family={}; by_date={}
    for node in plan["nodes"]:
        by_date.setdefault(node["decision_at"],[]).append(node)
    for item in day_map:
        for node in by_date.get(item["decision_at"],[]):
            active_by_family[node["family"]]=content_hash(node)
        item["family_context_ids"]=copy.deepcopy(active_by_family)
    return dict(schema="C_FIXED_POLICY_RISK_INPUT_CONTEXTS_R1",research_id=ID,
        plan=plan,decision_to_context=day_map,coverage=coverage,
        identity_epochs=hist,all_full_u_dates_retained=len(day_map)==keys.signal_date.nunique(),
        numeric_reads=0,labels_read=0,risk_fits=0,
        distinct_union_context_upper=plan["refresh_contexts"],
        learned_slot_upper=plan["learned_units_upper_bound"],
        unused_slots_status="NOT_REQUIRED_NOT_SUCCEEDED")


def fixed_policy_native_h5_plan(keys, calendar, qualified_identity_history,
                               raw_quote_keys, event_records, event_window,
                               *, source_identity, event_coverage):
    """Pure metadata wrapper of original native_endpoint_plan, including 2019.

    No absent event means 'no action' until a source coverage certificate covers
    exact ticker and endpoint window. This does not invent cash from QFQ factors.
    """
    from scripts.research.a2.training.stateful_mechanism_inputs import native_endpoint_plan
    from scripts.research.a2.data.shared_risk_inputs_r3 import _calendar
    days,_=_calendar(calendar)
    require(isinstance(source_identity,str) and bool(source_identity),
            "NEW_NATIVE_H5_SOURCE_IDENTITY")
    hist=fixed_policy_risk_identity_epochs(qualified_identity_history,days)
    require({"ticker","start","stop","source_complete"} <= set(event_coverage),
            "SOURCE_BOUND_EVENT_COVERAGE_REQUIRED")
    event_coverage=event_coverage.copy()
    for c in ("start","stop"):
        event_coverage[c]=pd.to_datetime(event_coverage[c])
    require(event_coverage.start.lt(event_coverage.stop).all()
            and event_coverage.stop.le(BOUNDARY).all(),"PRE2026_EVENT_COVERAGE_BOUNDS")
    qhist=hist[["ticker","signal_date","security_id"]].copy()
    # Unqualified sessions cannot be used by the original endpoint identity gate.
    qhist.loc[~hist.source_session_qualified,"security_id"]=None
    plan=native_endpoint_plan(keys,days,5,qhist,raw_quote_keys,
                              event_records,event_window,source_identity)
    lookup=hist.set_index(["signal_date","ticker"])
    epochs=[];covered=[]
    for row in plan.itertuples(index=False):
        identities=[]
        for day in (row.signal_date,row.execution_date,row.label_end_date):
            index=(day,row.ticker)
            identities.append(lookup.loc[index] if index in lookup.index else None)
        okay=(all(x is not None and x.source_session_qualified for x in identities)
              and len({x.identity_epoch for x in identities if x is not None})==1)
        epochs.append(identities[0].identity_epoch if okay else None)
        witness=event_coverage.loc[
            event_coverage.ticker.eq(row.ticker)
            & event_coverage.start.le(row.execution_date)
            & event_coverage.stop.gt(row.label_end_date)
            & event_coverage.source_complete.eq(True)]
        covered.append(len(witness)==1)
    plan["identity_epoch"]=epochs
    plan["event_source_window_complete"]=covered
    plan["mechanism_coordinate_supported"] &= plan.identity_epoch.notna() & plan.event_source_window_complete
    plan["raw_open_shareholder_quantity_formula_preserved"]=True
    plan["cash_from_affine_factor_fabricated"]=False
    return plan


def fixed_policy_native_h5_labels(plan, raw_quotes):
    """Actual endpoint values only after caller's frozen-source admission/ACK."""
    from scripts.research.a2.training.stateful_mechanism_inputs import native_labels
    from scripts.research.a2.data.shared_risk_inputs_r3 import STORED_LABEL_COORDINATE, _clock
    packet=native_labels(plan,raw_quotes)
    packet["y_open5"]=packet.label_value
    packet["label_available"]=packet.label_qualified
    packet["label_coordinate"]=STORED_LABEL_COORDINATE
    packet["available_at"]=packet.label_mature_date.map(
        lambda d:_clock(d) if pd.notna(d) else pd.NaT)
    packet["native_absolute_shareholder_h5"]=True
    packet["outer_er_target_used"]=False
    return packet[list(RISK_STORED_H5_COLUMNS)]


def fixed_policy_assemble_risk_context(stored_h5, calendar, context, *,
                                      source_receipt, identity_history,
                                      qqq_opens=None,qqq_receipt=None,
                                      industry_mapping=None,industry_receipt=None):
    """One existing typed assembly owner; no clone of B projection/estimator."""
    from scripts.research.a2.data.shared_risk_inputs_r3 import assemble_risk_inputs
    assets=tuple(context["ordered_assets"])
    require(len(assets)==len(set(assets)) and assets==tuple(sorted(assets))
            and set(context["asset_uids"])==set(assets)
            and set(context["asset_epochs"])==set(assets),"EXACT_CONTEXT_FULL_U_AXIS")
    return assemble_risk_inputs(stored_h5,calendar,assets=assets,
        asset_uids=context["asset_uids"],identity_epoch=source_receipt.identity_epoch,
        asset_epochs=context["asset_epochs"],source_receipt=source_receipt,
        cutoff=context["cutoff"],identity_history=identity_history,
        qqq_opens=qqq_opens,qqq_receipt=qqq_receipt,
        industry_mapping=industry_mapping,industry_receipt=industry_receipt)

def load_metadata_contexts(ref):
    """Expand exact compact metadata into the original owner control interface."""
    import copy
    from scripts.research.a2.risk.mechanism_risk_adapter import content_hash, FIXED_POLICY_RISK_FAMILIES
    require(set(ref) >= {"path","sha256"} and sha256(ref["path"]) == ref["sha256"],
            "FIXED_RISK_CONTEXT_REF_CHANGED")
    document=json.loads(Path(ref["path"]).read_text(encoding="utf8"))
    require(document.get("schema") == "C_FIXED_POLICY_RISK_INPUT_CONTEXTS_COMPACT_R1"
            and document.get("research_id") == ID
            and document.get("numeric_target_reads") == 0
            and document.get("risk_numeric_reads") == 0
            and document.get("risk_fits") == 0, "FIXED_METADATA_CONTEXT_SCHEMA")
    contexts={}
    for context in document["contexts"]:
        body={k:v for k,v in context.items() if k != "context_id"}
        require(context["context_id"] == content_hash(body)
                and context["context_id"] not in contexts,"CONTEXT_CANONICAL_ID_CHANGED")
        contexts[context["context_id"]]=context
    nodes=[]; active={}; nodes_by_date={}
    for compact in document["nodes"]:
        context=contexts[compact["context_id"]]
        node=dict(family=compact["family"],decision_at=compact["decision_at"],
            ordered_assets=copy.deepcopy(context["ordered_assets"]),
            asset_uids=copy.deepcopy(context["asset_uids"]),
            asset_epochs=copy.deepcopy(context["asset_epochs"]),
            trigger_reasons=copy.deepcopy(compact["trigger_reasons"]),
            structural_sha256=compact["structural_sha256"],
            recipe_sha256=compact["recipe_sha256"],learned_units_upper_bound=71)
        require(node["decision_at"] == context["decision_at"]
                and node["family"] in FIXED_POLICY_RISK_FAMILIES,"COMPACT_NODE_CONTEXT_IDENTITY")
        nodes.append(node)
        nodes_by_date.setdefault(node["decision_at"],[]).append(node)
    daily=[]
    for item in document["decision_to_context"]:
        context=contexts[item["context_id"]]
        for node in nodes_by_date.get(item["decision_at"],[]):
            active[node["family"]]=content_hash(node)
        require(set(active) == set(FIXED_POLICY_RISK_FAMILIES),"EXACT_FAMILY_CONTEXTS_REQUIRED")
        daily.append(dict(decision_at=item["decision_at"],cutoff=item["cutoff"],
            ordered_assets=copy.deepcopy(context["ordered_assets"]),
            asset_uids=copy.deepcopy(context["asset_uids"]),asset_epochs=copy.deepcopy(context["asset_epochs"]),
            family_context_ids=copy.deepcopy(active),context_id=item["context_id"],
            source_support_identity=copy.deepcopy(context["source_support_identity"]),
            family_source_support_identity=copy.deepcopy(context["family_source_support_identity"]),
            security_coordinate=context["security_coordinate"],
            matured_origin_start=item["matured_origin_start"],
            matured_origin_stop_exclusive=item["matured_origin_stop_exclusive"],
            signal_date=item["signal_date"],maximum_weighted_units=71))
    require(len(daily) == document["retained_decision_dates"]
            and len(contexts) == len({n["decision_at"] for n in nodes})
            and len(nodes) == document["family_nodes"]
            and 71*len(contexts) == document["learned_units_upper_bound"],
            "FIXED_CONTEXT_SCHEDULE_OR_BUDGET_CHANGED")
    return dict(schema="C_FIXED_POLICY_RISK_INPUT_CONTEXTS_R1",research_id=ID,
        plan=dict(schema="C_FULL_U_FIXED_POLICY_RISK_PLAN_R1",recipe=document["recipe"],
            recipe_sha256=document["recipe_sha256"],nodes=nodes,refresh_contexts=len(contexts),
            learned_units_upper_bound=71*len(contexts),includes_all_supplied_training_oof_dates=True,
            numeric_reads=0),decision_to_context=daily,numeric_reads=0,labels_read=0,risk_fits=0,
        contexts_ref=dict(ref),compact_document=document)


def _fixed_policy_risk_binding(run, context=None):
    """Physical/frozen metadata admission; no target or quote-value projection."""
    from scripts.research.a2.risk.mechanism_risk_adapter import content_hash
    run,_=_checked_run(run)
    binding_path=run/"risk_inputs.json"
    binding=json.loads(binding_path.read_text(encoding="utf8"))
    design_path,accept_path=run/"DESIGN_FREEZE.json",run/"FREEZE_ACCEPTANCE.json"
    require(design_path.exists() and accept_path.exists(),"RISK_INPUT_INDEPENDENT_FREEZE_REQUIRED")
    design=json.loads(design_path.read_text(encoding="utf8"))
    accept=json.loads(accept_path.read_text(encoding="utf8"))
    binding_ref=dict(path=str(binding_path),sha256=sha256(binding_path))
    require(binding.get("schema")=="C_FIXED_POLICY_RISK_SOURCE_BINDING_R1"
            and binding.get("research_id")==ID and design.get("research_id")==ID
            and accept.get("status")=="PASS"
            and accept.get("design_sha256")==sha256(design_path)
            and design.get("risk_inputs")==binding_ref
            and accept.get("risk_inputs_sha256")==binding_ref["sha256"],
            "FROZEN_RISK_SOURCE_BINDING_CHANGED")
    document=load_metadata_contexts(binding["contexts_ref"])["compact_document"]
    require(binding.get("source_work_package_sha256")==document["source_work_package_sha256"],
            "RISK_SOURCE_WORK_PACKAGE_IDENTITY")
    sources=binding["source_refs"]
    required={"absolute_h5","dated_cusip_history","calendar_pre2026","calendar_2019","qqq_qfq","ff48","raw_2019_candidate"}
    require(set(sources)==required and sources==document["source_work_package"]["known_source_refs"],
            "FIXED_KNOWN_RISK_SOURCE_CLOSURE_REQUIRED")
    flat={k:v for k,v in sources.items() if k!="qqq_qfq"}
    flat.update({"qqq_"+year:ref for year,ref in sources["qqq_qfq"].items()})
    require(set(sources["qqq_qfq"])==set(map(str,range(2019,2026))),"FIXED_QQQ_YEAR_CLOSURE")
    for name,ref in flat.items():
        require(set(ref)>={"path","sha256"} and sha256(ref["path"])==ref["sha256"],
                "RISK_SOURCE_PHYSICAL_CHANGED:"+name)
        pq.ParquetFile(ref["path"]) # Footer only, before value decoding.
    keyref=document["full_U_keys"]
    require(sha256(keyref["path"])==keyref["sha256"],"RISK_FULL_U_CHANGED")
    exact=None
    if context is not None:
        candidates=[c for c in document["contexts"] if c["decision_at"]==context["decision_at"]]
        require(len(candidates)==1,"EXACT_FROZEN_REFRESH_CONTEXT_REQUIRED")
        exact=candidates[0]
        require(tuple(context["ordered_assets"])==tuple(exact["ordered_assets"])
                and context["asset_uids"]==exact["asset_uids"]
                and context["asset_epochs"]==exact["asset_epochs"],
                "REFRESH_FULL_U_UID_EPOCH_CHANGED")
    return run,binding,design,binding_ref,document,exact


def _fixed_policy_parquet_projection(ref, columns, date_column, start, stop, *, assets=None,
                                      asset_column="ticker", extra_filters=()):
    """Arrow predicate first; never whole mixed-year load followed by filtering."""
    import pyarrow as pa
    schema=pq.ParquetFile(ref["path"]).schema_arrow
    require(set(columns)<=set(schema.names),"RISK_SOURCE_PROJECTED_SCHEMA_REQUIRED")
    def scalar(value,field):
        kind=schema.field(field).type
        if pa.types.is_string(kind) or pa.types.is_large_string(kind):
            return pd.Timestamp(value).date().isoformat()
        return pd.Timestamp(value).to_pydatetime()
    filters=[(date_column,">=",scalar(start,date_column)),(date_column,"<",scalar(stop,date_column))]
    if assets is not None:filters.append((asset_column,"in",list(assets)))
    filters.extend(extra_filters)
    result=pq.read_table(ref["path"],columns=list(columns),filters=filters).to_pandas()
    result[date_column]=pd.to_datetime(result[date_column])
    require(result[date_column].ge(start).all() and result[date_column].lt(stop).all()
            and result[date_column].lt(BOUNDARY).all(),"RISK_PROJECTION_DATE_BOUND")
    return result


def _fixed_policy_native_metadata(sources, assets, uids, epochs, days, start, cutoff):
    """Exact old CUSIP namespace transport, continuous suffix and H5 metadata."""
    from scripts.research.a2.data.shared_risk_inputs_r3 import _clock,STORED_LABEL_COORDINATE
    cutoff_day=pd.Timestamp(cutoff).tz_convert("America/New_York").tz_localize(None).normalize()
    ids=_fixed_policy_parquet_projection(sources["dated_cusip_history"],
        ("signal_date","ticker","security_id","security_id_type","cusip"),"signal_date",start,cutoff_day+pd.Timedelta(days=1),
        assets=assets)
    sid=ids.security_id.fillna("").astype(str)
    cusip=ids.cusip.fillna("").astype(str).str.strip().str.upper()
    valid=ids.security_id_type.eq("CUSIP") & sid.eq(cusip) & cusip.ne("")
    ids["security_id"]=("CUSIP:"+cusip).where(valid)
    require(not ids.duplicated(["ticker","signal_date"]).any(),"AMBIGUOUS_SOURCE_UID_HISTORY")
    position={d:i for i,d in enumerate(days)}
    end=position[cutoff_day]
    ids["available_at"]=ids.signal_date.map(_clock)
    ids["identity_epoch"]=None
    contiguous={}
    for asset in assets:
        part=ids.loc[ids.ticker.eq(asset)].sort_values("signal_date",kind="stable")
        expected=end;accepted=[]
        for row in part.iloc[::-1].itertuples():
            if position.get(row.signal_date)!=expected or row.security_id!=uids[asset]:break
            accepted.append(row.Index);expected-=1
        contiguous[asset]=dict(first_position=expected+1,last_position=end) if accepted else None
        ids.loc[accepted,"identity_epoch"]=epochs[asset]
    fields=("signal_date","ticker","execution_date","label_end_date","label_mature_date",
        "endpoint_pair_available","label_available","label_unsupported_common_event","label_coordinate")
    labels=_fixed_policy_parquet_projection(sources["absolute_h5"],fields,"signal_date",start,cutoff_day,
        assets=assets,extra_filters=[("label_mature_date","<",cutoff_day.to_pydatetime())])
    for c in ("execution_date","label_end_date","label_mature_date"):labels[c]=pd.to_datetime(labels[c])
    require(not labels.duplicated(["ticker","signal_date"]).any(),"AMBIGUOUS_NATIVE_H5_SOURCE")
    labels=labels.merge(ids[["ticker","signal_date","security_id","identity_epoch"]],
        on=["ticker","signal_date"],how="left",validate="one_to_one")
    labels["available_at"]=labels.label_mature_date.map(_clock)
    okay=labels.label_available.eq(True)&labels.endpoint_pair_available.eq(True)&labels.label_unsupported_common_event.eq(False)
    okay &= labels.label_coordinate.eq(STORED_LABEL_COORDINATE)
    qualified=[]
    for index,row in labels.iterrows():
        segment=contiguous[row.ticker]
        oi,ei,xi=(position.get(row[c],-1) for c in ("signal_date","execution_date","label_end_date"))
        qualified.append(bool(okay.loc[index] and segment is not None
            and segment["first_position"]<=oi and xi<=segment["last_position"]
            and ei==oi+1 and xi==ei+5 and row.label_mature_date>=row.label_end_date
            and row.security_id==uids[row.ticker] and row.identity_epoch==epochs[row.ticker]
            and row.available_at<pd.Timestamp(cutoff)))
    labels["native_metadata_qualified"]=qualified
    return labels,ids,contiguous


def _fixed_policy_selected_h5_values(ref, metadata):
    """Only qualified exact ticker/origin rows; no value reads for missing rows."""
    selected=metadata.loc[metadata.native_metadata_qualified]
    out=metadata.copy();out["y_open5"]=np.nan
    if selected.empty:return out,0
    filters=[]
    for ticker,part in selected.groupby("ticker",sort=True):
        filters.append([("ticker","=",ticker),("signal_date","in",list(part.signal_date.dt.to_pydatetime()))])
    values=pq.read_table(ref["path"],columns=["signal_date","ticker","y_open5"],filters=filters).to_pandas()
    values.signal_date=pd.to_datetime(values.signal_date)
    require(not values.duplicated(["signal_date","ticker"]).any(),"DUPLICATE_NUMERIC_H5_PROJECTION")
    expected=set(zip(selected.signal_date,selected.ticker))
    require(set(zip(values.signal_date,values.ticker))==expected
            and np.isfinite(values.y_open5.to_numpy(float)).all(),"EXACT_FINITE_NATIVE_H5_VALUES")
    lookup=values.set_index(["signal_date","ticker"]).y_open5
    for index,row in selected.iterrows():out.loc[index,"y_open5"]=lookup.loc[(row.signal_date,row.ticker)]
    return out,len(values)


def load_fixed_policy_risk_inputs(run, context, *, reservation_ack):
    """Actual mature input packaging after the same durable 71-slot group ACK.

    Known old absolute H5/dated CUSIP/QQQ/FF48 producers are reused. First-window
    cells without independent historical UID/H5 proof remain NaN on the full
    252-origin/full-U grid; original kernels disclose model completion.
    """
    import copy
    from dataclasses import replace
    from scripts.research.a2.data.shared_risk_inputs_r3 import (
        assemble_risk_inputs,_clock,_calendar,STOCK_METADATA,COORDINATE,BENCHMARK_PROXY_COORDINATE)
    from scripts.research.a2.risk.shared_risk_engine_r2 import SourceReceipt,META
    from scripts.research.a2.risk.mechanism_risk_adapter import content_hash,fixed_policy_risk_specification
    run,binding,design,binding_ref,document,exact=_fixed_policy_risk_binding(run,context)
    day=pd.Timestamp(exact["signal_date"]);cutoff=pd.Timestamp(exact["cutoff"])
    expected_reservation="RISK_REFRESH|"+day.date().isoformat()
    require(isinstance(reservation_ack,dict) and reservation_ack.get("ack") is True
            and reservation_ack.get("reserved_units")==71
            and reservation_ack.get("reservation_id")==expected_reservation,
            "DURABLE_EXACT_REFRESH_ACK_REQUIRED_BEFORE_NUMERIC")
    assets=tuple(exact["ordered_assets"]);uids=dict(exact["asset_uids"]);epochs=dict(exact["asset_epochs"])
    days,_=_calendar(document["calendar_sessions"]);sources=binding["source_refs"]
    start=pd.Timestamp(exact["matured_origin_start"])
    labels,history,segments=_fixed_policy_native_metadata(sources,assets,uids,epochs,days,start,cutoff)
    # Until here only source hashes, footer, UID, clock and qualification fields.
    domain="C_FIXED_FULL_U_CONTEXT:"+exact["context_id"]
    snapshot=pd.Timestamp(binding["actual_snapshot_timestamp"])
    require(snapshot.tzinfo is not None and snapshot>=cutoff,"ACTUAL_RISK_SOURCE_SNAPSHOT_CLOCK")
    receipt_base=dict(source_version=binding_ref["sha256"],available_at=cutoff,
        synthetic=False,mechanism=True,status="FROZEN_HISTORY_MECHANISM_SOURCE_BOUND",
        return_coordinate=COORDINATE,identity_epoch=domain,quote_qualified=False,
        historical_authority_status="UNKNOWN",strict_PIT_promotion_eligible=False,
        scientific_contract_identity=ID,scientific_contract_sha256=sha256(run/"DESIGN_FREEZE.json"),
        actual_snapshot_timestamp=snapshot,observation_time_assumed=True)
    receipt=SourceReceipt(source_identity="C_FIXED_NATIVE_ABSOLUTE_H5_SOURCE",
        source_sha256=sources["absolute_h5"]["sha256"],**receipt_base)
    receipt.validate(cutoff)
    labels,numeric_h5_rows=_fixed_policy_selected_h5_values(sources["absolute_h5"],labels)
    # QQQ is the explicitly declared original QFQ open proxy, not stock H5.
    quote_frames=[]
    qstart=start;qstop=cutoff.tz_convert("America/New_York").tz_localize(None).normalize()
    for year,ref in sources["qqq_qfq"].items():
        if int(year)<qstart.year or int(year)>qstop.year:continue
        quote_frames.append(_fixed_policy_parquet_projection(ref,("ticker","trade_date","open"),
            "trade_date",qstart,qstop+pd.Timedelta(days=1),assets=("QQQ",)))
    qqq=pd.concat(quote_frames,ignore_index=True) if quote_frames else None
    qreceipt=SourceReceipt(source_identity="C_FIXED_EXPLICIT_QQQ_QFQ_OPEN_PROXY",
        source_sha256=content_hash(sources["qqq_qfq"]),**{**receipt_base,
            "return_coordinate":BENCHMARK_PROXY_COORDINATE,"benchmark_proxy_allowed":True})
    # FF48 is independent as-filed metadata; no current classification carry.
    ff=_fixed_policy_parquet_projection(sources["ff48"],
        ("decision_date","canonical_security_id","ticker_at_date","identity_status",
            "sic_available_at","ff48_code","taxonomy_status"),
        "decision_date",pd.Timestamp("2023-01-01"),qstop,assets=assets,asset_column="ticker_at_date") if qstop>pd.Timestamp("2023-01-01") else pd.DataFrame()
    industry=None;ireceipt=None
    if not ff.empty:
        # Source canonical_security_id is accepted only if it equals exact
        # current prefixed CUSIP or exact bare source CUSIP. No ticker mapping.
        ff["asset"]=ff.ticker_at_date
        ff["uid"]=ff.canonical_security_id.astype(str).map(
            lambda v:v if v.startswith("CUSIP:") else "CUSIP:"+v if __import__("re").fullmatch("[A-Z0-9]{9}",v) else "")
        ff=ff.loc[[uid==uids[a] for a,uid in zip(ff.asset,ff.uid)]].copy()
        ff["group"]=ff.ff48_code
        ff["available_at"]=pd.to_datetime(ff.sic_available_at,utc=True)
        ff["effective_at"]=ff.decision_date.map(_clock)
        # No qualification is inferred from a group number alone.
        qualified=ff.identity_status.eq("AUTHORITATIVE")
        qualified &= ff.taxonomy_status.eq("STRICT_PIT_SIC_FF12_FF48_MAPPED")
        industry=ff.loc[qualified,["asset","uid","group","available_at","effective_at"]]
        ireceipt=SourceReceipt(source_identity="C_FIXED_ASFILED_FF48",
            source_sha256=sources["ff48"]["sha256"],**receipt_base)
    assembly=assemble_risk_inputs(labels,days,assets=assets,asset_uids=uids,
        identity_epoch=domain,source_receipt=receipt,cutoff=cutoff,identity_history=history,
        asset_epochs=epochs,qqq_opens=qqq,qqq_receipt=qreceipt,industry_mapping=industry,industry_receipt=ireceipt)
    source=assembly.risk_input
    positions={d:i for i,d in enumerate(days)}
    origins=days[(days>=start)&(days<pd.Timestamp(exact["matured_origin_stop_exclusive"]))]
    require(len(origins)==252,"FIXED_FULL_252_MATURED_GRID_REQUIRED")
    grid=[]
    for origin in origins:
        i=positions[origin];entry,end=days[i+1],days[i+6]
        for asset in assets:
            grid.append(dict(asset=asset,origin_at=_clock(origin),entry_at=_clock(entry,opening=True),
                endpoint_at=_clock(end,opening=True),matured_at=_clock(end),available_at=_clock(end),
                horizon=5,uid=uids[asset],identity_epoch=domain,source_identity=receipt.source_identity))
    grid=pd.DataFrame(grid,columns=list(META))
    values=source.observations[["asset","origin_at","return_value"]]
    require(not values.duplicated(["asset","origin_at"]).any(),"AMBIGUOUS_PACKAGED_NATIVE_OBSERVATION")
    full=grid.merge(values,on=["asset","origin_at"],how="left",validate="one_to_one")
    support=full[["asset","origin_at"]].copy()
    support["qualified"]=full.return_value.notna() # Values decoded only after exact durable ACK.
    result=replace(source,observations=full)
    proof=dict(assets=list(assets),asset_uids=uids,asset_epochs=epochs,
        security_coordinate=exact["security_coordinate"],
        source_support_identity=copy.deepcopy(exact["source_support_identity"]),
        family_source_support_identity=copy.deepcopy(exact["family_source_support_identity"]),
        source_qualified=True,maturity_qualified=True,current_axis_source_only=True,
        native_historical_coverage_not_inferred_from_current_axis=True)
    projection=content_hash(dict(binding_sha256=binding_ref["sha256"],context_id=exact["context_id"],
        assets=assets,uids=uids,cutoff=cutoff.isoformat(),origins=list(origins.map(pd.Timestamp.isoformat)),
        source_refs=sources,source_metadata_qualified_keys=list(zip(labels.loc[labels.native_metadata_qualified].ticker,
            labels.loc[labels.native_metadata_qualified].signal_date.map(pd.Timestamp.isoformat)))))
    native_scenario=dict(native=True,horizon_sessions=5,return_coordinate=COORDINATE,
        assets=list(assets),asset_uids=uids,source_cache_identity=receipt.cache_identity(),
        cutoff=cutoff.isoformat(),recipe_sha256=content_hash(fixed_policy_risk_specification()),
        source_projection_sha256=projection,scenario_completion_permitted=False,
        source_identity_proof_required_per_cell=True)
    return dict(inputs=result,support_metadata=support,current_identity_proof=proof,
        native_scenario_receipt=native_scenario,native_scenario_source_projection_sha256=projection,
        reservation_ack=copy.deepcopy(reservation_ack),support_declarations=dict(assembly.support_declarations),
        numeric_read_counts=dict(native_h5_rows=numeric_h5_rows,qqq_open_rows=0 if qqq is None else len(qqq),
            post2025_rows=0),risk_estimates=0,scientific_retry=0)


def load_fixed_policy_outer_h5(run, terminal, clock):
    """Final-gated absolute H5 projection; missing rows retained, never zero-filled."""
    from scripts.research.a2.data.shared_risk_inputs_r3 import STORED_LABEL_COORDINATE
    run,binding,design,binding_ref,document,_=_fixed_policy_risk_binding(run)
    terminal_path=run/"POLICY_TERMINAL.json"
    require(terminal_path.exists() and isinstance(terminal,dict)
            and json.loads(terminal_path.read_text(encoding="utf8"))==terminal
            and terminal.get("research_id")==ID
            and terminal.get("status")=="ALL_POLICIES_FROZEN_BEFORE_OUTCOMES"
            and terminal.get("all_scientific_nodes_terminal") is True
            and terminal.get("design_sha256")==sha256(run/"DESIGN_FREEZE.json"),
            "FINAL_FULL_SELECTOR_TERMINAL_GATE_REQUIRED_BEFORE_OUTER_H5")
    # Physical final authority + read-only existing sole ledger, never a boolean
    # supplied by a caller or a second mutable ledger.
    import sqlite3
    db=sqlite3.connect((run/"TASK_LEDGER.sqlite").resolve().as_uri()+"?mode=ro",uri=True)
    try:
        require(db.execute("SELECT design_sha256 FROM authority").fetchall()==
                [(sha256(run/"DESIGN_FREEZE.json"),)],"OUTER_LEDGER_AUTHORITY_CHANGED")
        actual={n:k for n,k in db.execute("SELECT node_id,kind FROM nodes")}
        require(actual=={n["node_id"]:n["kind"] for n in design["dag"]["nodes"]},
                "OUTER_LEDGER_DAG_CHANGED")
        learned={"ESTIMATOR","SCALER","CALIBRATOR","META_MODEL","META_SCALER","META_TARGET_SCALE",
            "HYBRID_ESTIMATOR","HYBRID_SCALER","RISK_LEARNED_UNIT","RISK_REFRESH_DISPATCH",
            "MEMBER_SOLVE","WHOLE_SET_GATE"}
        require(not any(k in learned and s in ("NAMED","STARTED")
                for k,s in db.execute("SELECT kind,status FROM nodes")),
                "OUTER_ALL_SCIENTIFIC_NODES_TERMINAL_REQUIRED")
    finally:db.close()
    for ref in [terminal["assembly_ref"],*terminal["policy_refs"].values()]:
        require(sha256(ref["path"])==ref["sha256"],"OUTER_TERMINAL_POLICY_ARTIFACT_CHANGED")
    require({"signal_date","ticker","security_uid"}<=set(clock),"EXACT_OUTER_H5_CLOCK_KEYS")
    keys=clock[["signal_date","ticker","security_uid"]].copy()
    keys.signal_date=pd.to_datetime(keys.signal_date)
    require(keys.signal_date.ge("2023-01-01").all() and keys.signal_date.lt(BOUNDARY).all()
            and not keys.duplicated(["signal_date","ticker"]).any(),"OUTER_H5_PRE2026_EXACT_KEYS")
    sources=binding["source_refs"];start=keys.signal_date.min();stop=keys.signal_date.max()+pd.Timedelta(days=1)
    labels=_fixed_policy_parquet_projection(sources["absolute_h5"],
        ("signal_date","ticker","execution_date","label_end_date","label_mature_date",
         "label_available","endpoint_pair_available","label_unsupported_common_event","label_coordinate"),
        "signal_date",start,stop,assets=keys.ticker.unique(),
        extra_filters=[("label_mature_date","<",BOUNDARY.to_pydatetime())])
    ids=_fixed_policy_parquet_projection(sources["dated_cusip_history"],
        ("signal_date","ticker","security_id","security_id_type","cusip"),
        "signal_date",start,BOUNDARY,assets=keys.ticker.unique())
    ids["security_uid"]="CUSIP:"+ids.cusip.astype(str).str.strip().str.upper()
    ids["uid_qualified"]=ids.security_id_type.eq("CUSIP")&ids.security_id.eq(ids.cusip)&ids.cusip.notna()
    require(not ids.duplicated(["signal_date","ticker"]).any(),"OUTER_IDENTITY_AMBIGUOUS")
    source_lookup=ids.set_index(["signal_date","ticker"])
    labels=labels.merge(ids[["signal_date","ticker","security_uid","uid_qualified"]],
        on=["signal_date","ticker"],how="left",validate="one_to_one")
    joined=keys.merge(labels,on=["signal_date","ticker"],how="left",validate="one_to_one",suffixes=("","_source"))
    joined["native_metadata_qualified"]=(joined.security_uid.eq(joined.security_uid_source)
        &joined.uid_qualified.eq(True)&joined.label_available.eq(True)
        &joined.endpoint_pair_available.eq(True)&joined.label_unsupported_common_event.eq(False)
        &joined.label_coordinate.eq(STORED_LABEL_COORDINATE))
    days=pd.DatetimeIndex(pd.to_datetime(document["calendar_sessions"]))
    position={d:i for i,d in enumerate(days)}
    endpoint_uid=[]
    for row in joined.itertuples():
        i=position.get(row.signal_date,-1)
        okay=i>=0 and i+6<len(days)
        if okay:
            expected_entry,expected_exit=days[i+1],days[i+6]
            okay=(pd.Timestamp(row.execution_date)==expected_entry
                and pd.Timestamp(row.label_end_date)==expected_exit
                and pd.Timestamp(row.label_mature_date)>=expected_exit
                and pd.Timestamp(row.label_mature_date)<BOUNDARY)
            for identity_day in days[i:i+7]:
                index=(identity_day,row.ticker)
                if index not in source_lookup.index:
                    okay=False;break
                identity=source_lookup.loc[index]
                if not bool(identity.uid_qualified) or identity.security_uid!=row.security_uid:
                    okay=False;break
        endpoint_uid.append(bool(okay))
    joined["native_metadata_qualified"] &= pd.Series(endpoint_uid,index=joined.index,dtype=bool)
    values,count=_fixed_policy_selected_h5_values(sources["absolute_h5"],joined)
    values["h5_status"]=np.where(values.native_metadata_qualified,"NATIVE_ABSOLUTE_H5_COMPLETE","NATIVE_H5_NOT_TESTABLE")
    return dict(frame=values,numeric_h5_rows=count,source_ref=sources["absolute_h5"],
        unknown_tail_fabricated=False,missing_filled_with_zero=False,outer_er_used=False)
