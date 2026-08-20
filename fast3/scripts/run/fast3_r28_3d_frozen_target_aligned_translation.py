"""FAST3 R28.3D frozen first-touch economic-translation audit only."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(r"D:\us-tech-quant")
DATA = Path(r"D:\us-tech-quant-data")
RESULTS = Path(r"D:\us-tech-quant-results")
A_SOURCE = REPO / "fast3" / "scripts" / "run" / "fast3_r28_3a_frozen_economic_attribution.py"
B_SOURCE = REPO / "fast3" / "scripts" / "run" / "fast3_r28_3b_soxx_natural_baseline.py"
C_SUMMARY = RESULTS / "frozen" / "fast3" / "r28_3c_frozen_event_conditioned_path_audit_20260809_r2" / "R28_3C_SUMMARY.json"
A_SUMMARY = RESULTS / "frozen" / "fast3" / "r28_3a_frozen_economic_attribution_20260809_r2" / "R28_3A_SUMMARY.json"
OUT = RESULTS / "frozen" / "fast3" / "r28_3d_frozen_target_aligned_translation_20260809"
CANONICAL = DATA / "fast3" / "moomoo_24h_1m" / "canonical"
THRESHOLD, HORIZON, SEED, RUNS = .01, pd.Timedelta(hours=24), 28304, 1000


class AuditStop(RuntimeError): pass


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path); mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None; spec.loader.exec_module(mod); return mod


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""): digest.update(block)
    return digest.hexdigest()


def touch_reconciliation() -> dict:
    c = json.loads(C_SUMMARY.read_text(encoding="utf-8"))
    if c.get("FAST3_R28_3C_STATUS") != "PASS": raise AuditStop("FAST3_R28_3D_STATUS=STOPPED_IDENTITY_MISMATCH")
    return {"status": "PASS_DIFFERENT_COHORTS_NOT_A_BUG",
            "up_top5_median_definition": "only UP_FIRST rows among UP frozen-score Top5; time from frozen underlying reference entry to first UP touch",
            "down_top5_median_definition": "only DOWN_FIRST rows among DOWN frozen-score Top5; time from frozen underlying reference entry to first DOWN touch",
            "up_ladder_1p00_definition": "all UP frozen-score Top5 candidates that reached +1%, including paths where DOWN touched first",
            "down_ladder_1p00_definition": "all DOWN frozen-score Top5 candidates that reached -1%, including paths where UP touched first",
            "why_values_differ": "the ladder includes opposite-first paths and is not restricted to favorable-first events; both use the same underlying-entry time anchor and frozen +/-1% threshold."}


def canonical_underlying(b, r1, symbol: str) -> pd.DataFrame:
    source = json.loads((b.FREEZE / "cleanroom_r2_preholdout_source_manifest.json").read_text(encoding="utf-8"))
    records = [z for z in source["files"] if z["symbol"] == symbol]
    if not records: raise AuditStop("STOP_CANONICAL_UNDERLYING_MISSING")
    frames = []
    for item in records:
        path = Path(item["path"])
        if DATA not in path.parents or sha(path) != item["sha256"]: raise AuditStop("STOP_CANONICAL_SOURCE_IDENTITY_MISMATCH")
        frames.append(pd.read_parquet(path, columns=["timestamp_et", "timestamp_utc", "session", "open", "high", "low", "close", "volume"]))
    raw = pd.concat(frames, ignore_index=True); raw["timestamp_utc"] = pd.to_datetime(raw.timestamp_utc, utc=True)
    raw["timestamp_et"] = pd.to_datetime(raw.timestamp_et, utc=True).dt.tz_convert("America/New_York")
    raw = raw.sort_values("timestamp_utc", kind="mergesort").drop_duplicates("timestamp_utc").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"): raw[col] = pd.to_numeric(raw[col], errors="coerce")
    raw["valid"] = ((raw.open > 0) & (raw.high >= raw[["open", "low", "close"]].max(axis=1)) & (raw.low <= raw[["open", "high", "close"]].min(axis=1)))
    return raw


def underlying_touches(points: pd.DataFrame, b, r1, raw: pd.DataFrame) -> pd.DataFrame:
    ns = raw.timestamp_utc.astype("int64").to_numpy(); decision = points.timestamp.astype("int64").to_numpy()
    decision_i = np.searchsorted(ns, decision)
    if (decision_i >= len(raw)).any() or not np.array_equal(ns[decision_i], decision): raise AuditStop("STOP_FROZEN_CANDIDATE_NOT_IN_CANONICAL_SOURCE")
    valid_i = np.flatnonzero(raw.valid.to_numpy(bool)); entry_i = valid_i[np.searchsorted(valid_i, decision_i + 1)]
    deadline = ns[entry_i] + HORIZON.value; coverage_i = np.searchsorted(ns, deadline, side="left"); horizon_i = np.searchsorted(ns, deadline, side="right") - 1
    if (coverage_i >= len(raw)).any() or (horizon_i <= entry_i).any() or not (raw.timestamp_et.iloc[coverage_i].to_numpy() <= r1.DEVELOPMENT_END).all(): raise AuditStop("STOP_FROZEN_CANDIDATE_HORIZON_INCOMPLETE")
    high_tree, high_size = r1.build_tree(raw.high.to_numpy(float), True); low_tree, low_size = r1.build_tree(raw.low.to_numpy(float), False); entry = raw.open.to_numpy(float)[entry_i]
    up = np.fromiter((r1.first_cross(high_tree, high_size, int(i), int(j), float(p * 1.01), True) for i,j,p in zip(entry_i,horizon_i,entry)), dtype=int, count=len(points))
    down = np.fromiter((r1.first_cross(low_tree, low_size, int(i), int(j), float(p * .99), False) for i,j,p in zip(entry_i,horizon_i,entry)), dtype=int, count=len(points))
    label = b.first_touch_labels(up, down); out = points[["candidate_id", "underlying_symbol"]].copy(); out["frozen_label"] = label
    touch = np.where(label == "UP_FIRST", up, np.where(label == "DOWN_FIRST", down, -1)); out["touch_timestamp"] = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns, UTC]")
    actual = touch >= 0; out.loc[actual, "touch_timestamp"] = pd.to_datetime(ns[touch[actual]], utc=True).to_numpy(); out["reference_price"] = entry
    return out


def action_bars() -> tuple[dict, dict]:
    sys.path.insert(0, str(REPO / "fast3" / "src"))
    from fast3.economics import executable_payoff_ledger_calendar_hard_r26a2 as r26
    bars, manifests = {}, {}
    for symbol in ("TQQQ", "SQQQ", "SOXL", "SOXS"):
        bars[symbol], manifests[symbol] = r26.legal_bars(CANONICAL, symbol)
    return bars, {"canonical_partition_manifest_hash": r26.stable_hash(manifests), "symbols": manifests}


def attach_first_touch_exit(x: pd.DataFrame, touches: pd.DataFrame, bars: dict) -> pd.DataFrame:
    """One frozen treatment: favorable first touch -> first legal action-ETF open at/after touch."""
    out = x.merge(touches, on=["candidate_id", "underlying_symbol"], how="left", validate="many_to_one")
    if out.frozen_label.isna().any(): raise AuditStop("STOP_TOUCH_JOIN_FAILURE")
    favorable = ((out["head"].eq("UP") & out.frozen_label.eq("UP_FIRST")) | (out["head"].eq("DOWN") & out.frozen_label.eq("DOWN_FIRST")))
    out["event_state"] = np.where(favorable, "FAVORABLE_FIRST", np.where(out.frozen_label.eq("NO_EVENT"), "NO_EVENT", "ADVERSE_FIRST"))
    out["first_touch_exit_timestamp"] = out.exit; out["first_touch_exit_price"] = out.exit_price; out["first_touch_exit_reason"] = "FROZEN_24H_TIMEOUT_OR_ADVERSE_FIRST"
    out["first_touch_executable"] = True; out["first_touch_nonexecutable_reason"] = None
    for instrument, part in out.loc[favorable].groupby("action_instrument", sort=False):
        right = bars[instrument][["timestamp_et", "open"]].rename(columns={"timestamp_et": "bar_timestamp", "open": "bar_open"}).sort_values("bar_timestamp")
        left = part[["candidate_id", "touch_timestamp", "entry_timestamp"]].copy(); left["target"] = pd.concat([left.touch_timestamp, left.entry_timestamp], axis=1).max(axis=1)
        joined = pd.merge_asof(left.sort_values("target"), right, left_on="target", right_on="bar_timestamp", direction="forward", allow_exact_matches=True).set_index("candidate_id")
        idx = out.candidate_id.isin(joined.index) & out.action_instrument.eq(instrument)
        mapped = out.loc[idx, "candidate_id"].map(joined.bar_timestamp); price = out.loc[idx, "candidate_id"].map(joined.bar_open)
        legal = mapped.notna() & (mapped >= out.loc[idx, "entry_timestamp"])
        out.loc[idx, "first_touch_exit_timestamp"] = mapped.where(legal); out.loc[idx, "first_touch_exit_price"] = price.where(legal)
        out.loc[idx, "first_touch_exit_reason"] = np.where(legal, "FIRST_LEGAL_ACTION_ETF_OPEN_AT_OR_AFTER_FROZEN_TARGET_TOUCH", "TARGET_TOUCH_EXIT_BAR_UNAVAILABLE")
        out.loc[idx, "first_touch_executable"] = legal.to_numpy()
        out.loc[idx & ~out.first_touch_executable, "first_touch_nonexecutable_reason"] = "TARGET_TOUCH_EXIT_BAR_UNAVAILABLE"
    if (~out.first_touch_executable & favorable).any(): raise AuditStop("STOP_TARGET_TOUCH_NONEXECUTABLE")
    out["first_touch_gross"] = out.first_touch_exit_price / out.entry_price - 1
    out["first_touch_net10"] = out.first_touch_gross - .001; out["first_touch_net20"] = out.first_touch_gross - .002
    return out


def stats(x: pd.DataFrame, prefix: str = "first_touch") -> dict:
    v = x[f"{prefix}_net20"] if prefix == "first_touch" else x.net20
    gross = x[f"{prefix}_gross"] if prefix == "first_touch" else x.gross; net10 = x[f"{prefix}_net10"] if prefix == "first_touch" else x.net10
    return {"trade_count": int(len(x)), "win_count": int((v > 0).sum()), "loss_count": int((v < 0).sum()), "win_rate": float((v > 0).mean()), "mean_gross": float(gross.mean()), "median_gross": float(gross.median()), "mean_net10": float(net10.mean()), "median_net10": float(net10.median()), "mean_net20": float(v.mean()), "median_net20": float(v.median()), "p05_net20": float(v.quantile(.05)), "p25_net20": float(v.quantile(.25)), "p75_net20": float(v.quantile(.75)), "p95_net20": float(v.quantile(.95)), "best_trade": float(v.max()), "worst_trade": float(v.min())}


def distribution(x: pd.DataFrame, column: str) -> dict:
    y = x[column]; return {"mean":float(y.mean()),"median":float(y.median()),"std":float(y.std()), **{f"p{int(q*100):02d}":float(y.quantile(q)) for q in (.01,.05,.10,.25,.75,.90,.95,.99)}, "worst_trade":float(y.min()),"best_trade":float(y.max()),"loss_rate":float((y<0).mean()),"loss_below_minus1pct":float((y<-.01).mean()),"loss_below_minus2pct":float((y<-.02).mean())}


def table_by(x: pd.DataFrame, field: str) -> pd.DataFrame:
    rows=[]
    for key, part in x.groupby(field, sort=True): rows.append({field:str(key), **stats(part)})
    return pd.DataFrame(rows)


def match_plan(a, real, eligible): return a.match_plan(real, eligible)


def placebo(a, real, eligible) -> tuple[pd.DataFrame, dict]:
    rng, plan, rows, levels = np.random.default_rng(SEED), match_plan(a, real, eligible), [], None
    if not plan: raise AuditStop("STOP_MATCHED_PLACEBO_UNMATCHED")
    for run in range(1, RUNS + 1):
        sample, used = a.matched_once(real, eligible, rng, plan)
        if len(sample) != len(real): raise AuditStop("STOP_MATCHED_PLACEBO_UNMATCHED")
        if levels is None: levels = used
        paths = sample.outcome_path.value_counts(); rows.append({"run":run,"trade_count":len(sample),"signal_cardinality_conserved":len(sample)==len(real),"unique_placebo_signal_count":int(sample.candidate_id.nunique()),"unique_outcome_path_count":int(paths.size),"shared_outcome_path_count":int((paths>1).sum()),"max_signals_per_outcome_path":int(paths.max()), **stats(sample)})
    runs=pd.DataFrame(rows); values=runs.mean_net20.to_numpy(); actual=float(real.first_touch_net20.mean())
    summary={"random_seed":SEED,"random_run_count":RUNS,**{f"match_level_{i}_count":int(sum(x==i for x in levels)) for i in range(5)},"unmatched_count":0,"signal_cardinality_conserved":bool(runs.signal_cardinality_conserved.all()),"net20_median":float(np.quantile(values,.5)),"net20_p90":float(np.quantile(values,.9)),"net20_p95":float(np.quantile(values,.95)),"net20_p99":float(np.quantile(values,.99)),"net20_max":float(values.max()),"real_net20_percentile":float((values<=actual).mean()),"net20_p":float((1+(values>=actual).sum())/(RUNS+1)),"shared_outcome_path_count":int(runs.shared_outcome_path_count.max()),"max_signals_per_outcome_path":int(runs.max_signals_per_outcome_path.max())}
    return runs,summary


def run() -> dict:
    a,b=load(A_SOURCE,"r28_3a_for_d"),load(B_SOURCE,"r28_3b_for_d"); rec=touch_reconciliation(); old=json.loads(A_SUMMARY.read_text(encoding="utf-8"))
    if old.get("status")!="PASS" or old["identity"] != a.EXPECTED_IDENTITY: raise AuditStop("FAST3_R28_3D_STATUS=STOPPED_IDENTITY_MISMATCH")
    contract,r1=b.load_contract(); all_rows,payoff,identity=a.read_frozen(); selected=all_rows.loc[all_rows.selected].copy(); baseline=a.execute(selected)
    reverse = a.execute(selected.assign(head=selected["head"].map({"UP":"DOWN","DOWN":"UP"})))
    a.validate_baseline(baseline, reverse, {"reverse":reverse, "minus1":a.execute(a.shifted(selected,payoff,-1)), "plus1":a.execute(a.shifted(selected,payoff,1)), "plus2":a.execute(a.shifted(selected,payoff,2))})
    candidates=all_rows[["candidate_id","underlying_symbol","timestamp","target_first","head"]].drop_duplicates(["candidate_id","head"]); points=candidates[["candidate_id","underlying_symbol","timestamp"]].drop_duplicates().reset_index(drop=True)
    touches=pd.concat([underlying_touches(points.loc[points.underlying_symbol.eq(symbol)].reset_index(drop=True),b,r1,canonical_underlying(b,r1,symbol)) for symbol in ("QQQ","SOXX")],ignore_index=True)
    joined=candidates.merge(touches,on=["candidate_id","underlying_symbol"],how="left",validate="many_to_one")
    expected=(joined.frozen_label.eq("UP_FIRST") & joined["head"].eq("UP")) | (joined.frozen_label.eq("DOWN_FIRST") & joined["head"].eq("DOWN"))
    if not np.array_equal(expected.to_numpy(bool),joined.target_first.to_numpy(bool)): raise AuditStop("STOP_FROZEN_LABEL_RECONCILIATION_FAILURE")
    econ=a.add_economics(all_rows); up=econ["head"].eq("UP"); econ["action_instrument"]=np.where(up,econ.up_action_instrument,econ.down_action_instrument); econ["entry_timestamp"]=np.where(up,econ.up_entry_timestamp_et,econ.down_entry_timestamp_et); econ["entry_price"]=np.where(up,econ.up_entry_price,econ.down_entry_price); econ["exit_price"]=np.where(up,econ.up_exit_price,econ.down_exit_price); econ["candidate_id"]=econ.candidate_id.astype(str); econ["entry_timestamp"]=pd.to_datetime(econ.entry_timestamp,utc=True)
    bars,bar_identity=action_bars()
    if bar_identity["canonical_partition_manifest_hash"] != str(payoff.canonical_partition_manifest_hash.iloc[0]): raise AuditStop("STOP_ACTION_ETF_CANONICAL_IDENTITY_MISMATCH")
    translated=attach_first_touch_exit(econ.loc[econ.valid].copy(),touches,bars); real=baseline[["candidate_id","head"]].merge(translated,on=["candidate_id","head"],how="left",validate="one_to_one")
    if real.first_touch_net20.isna().any() or len(real)!=len(baseline): raise AuditStop("STOP_PAIRED_RECONCILIATION_FAILURE")
    paired=real.copy(); paired["original_net20"]=paired.net20; paired["delta_net20"]=paired.first_touch_net20-paired.original_net20
    runs,matched=placebo(a,real,translated)
    by_direction,by_symbol=table_by(real,"head"),table_by(real,"underlying_symbol"); local=real.timestamp.dt.tz_convert("America/New_York"); real["year"]=local.dt.year; by_year=table_by(real,"year")
    favorable=real.event_state.eq("FAVORABLE_FIRST"); saved=paired.loc[favorable,"delta_net20"]
    delta=float(paired.delta_net20.mean()); primary="STRONG_PASS" if stats(real)["mean_net20"]>0 and matched["real_net20_percentile"]>=.95 and matched["net20_p"]<=.05 else ("FAIL" if matched["real_net20_percentile"]<.90 or matched["net20_p"]>.10 else "WEAK_OR_MIXED")
    classification="A_TARGET_ALIGNED_ECONOMIC_EDGE_CONFIRMED" if primary=="STRONG_PASS" else ("B_TARGET_ALIGNED_TRANSLATION_IMPROVES_PAYOFF_BUT_MATCHED_EDGE_UNCONFIRMED" if delta>.0005 else ("D_TARGET_ALIGNED_TRANSLATION_WORSE" if delta<-.0005 else "C_TARGET_ALIGNED_TRANSLATION_NO_MEANINGFUL_IMPROVEMENT"))
    if OUT.exists(): raise AuditStop("STOP_R28_3D_OUTPUT_PATH_EXISTS")
    OUT.mkdir(parents=True); translated.to_csv(OUT/"R28_3D_FIRST_TOUCH_TRADE_LEDGER.csv",index=False); paired.to_csv(OUT/"R28_3D_PAIRED_ORIGINAL_VS_FIRST_TOUCH.csv",index=False); by_direction.to_csv(OUT/"R28_3D_FIRST_TOUCH_BY_DIRECTION.csv",index=False); by_symbol.to_csv(OUT/"R28_3D_FIRST_TOUCH_BY_SYMBOL.csv",index=False); by_year.to_csv(OUT/"R28_3D_FIRST_TOUCH_BY_YEAR.csv",index=False); runs.to_csv(OUT/"R28_3D_MATCHED_PLACEBO_RUNS.csv",index=False)
    payload={"FAST3_R28_3D_STATUS":"PASS","FAST3_R28_3D_CLASSIFICATION":classification,"touch_time_reconciliation":rec,"identity":{**identity,"action_canonical":bar_identity},"entry_contract_source":str(a.COMPLETION),"entry_price_semantics":"first legal action-ETF one-minute open strictly after frozen anchor within 15 minutes","exit_semantics":"favorable first touch: first legal action-ETF one-minute open at/after max(touch, actual entry); adverse/no-event: frozen 24h closeout","instrument_mapping_source":str(a.COMPLETION),"frozen_selection_rule":"R28 selected=true; frozen HGB threshold with original one-global-position execution","selected_signal_count":int(selected.selected.sum()),"baseline":stats(baseline,prefix="original"),"first_touch":stats(real),"first_touch_by_direction":by_direction.to_dict(orient="records"),"distribution":{"original":distribution(paired,"original_net20"),"first_touch":distribution(paired,"first_touch_net20")},"paired":{"count":len(paired),"delta_mean":delta,"delta_median":float(paired.delta_net20.median()),"positive_share":float((paired.delta_net20>0).mean()),"negative_share":float((paired.delta_net20<0).mean()),"zero_share":float((paired.delta_net20==0).mean())},"giveback_capture":{"favorable_touch_trade_count":int(favorable.sum()),"first_touch_exit_better_count":int((saved>0).sum()),"original_exit_better_count":int((saved<0).sum()),"mean_saved_giveback_net20":float(saved.mean()),"median_saved_giveback_net20":float(saved.median())},"matched_placebo":matched,"reconciliation":{"selected_signal_count":int(selected.selected.sum()),"executed_trade_count":len(real),"explicit_nonexecutable_count":0,"explicit_other_state_count":int(selected.selected.sum())-len(real),"favorable_first_count":int(real.event_state.eq("FAVORABLE_FIRST").sum()),"adverse_first_count":int(real.event_state.eq("ADVERSE_FIRST").sum()),"no_event_count":int(real.event_state.eq("NO_EVENT").sum()),"dropped_row_count":0,"dropped_row_reasons":{}},"year_positive":{"up":int((by_year[by_year.year.notna()].mean_net20>0).sum()),"down":None},"primary_hypothesis_result":primary,"constraints":{"model_retrain_count":0,"model_predict_call_count":0,"post_freeze_rescoring_count":0,"prospective_data_used":False,"data_root_write_count":0,"future_path_used_for_outcome_audit_only":True,"future_path_used_for_model_input":False,"live_trading_allowed":False},"r29_allowed_to_resume":False,"live_trading_allowed":False}
    (OUT/"R28_3D_MATCHED_PLACEBO_SUMMARY.json").write_text(json.dumps(matched,indent=2),encoding="utf-8"); (OUT/"R28_3D_SUMMARY.json").write_text(json.dumps(payload,indent=2,default=str),encoding="utf-8"); (OUT/"R28_3D_REPORT.md").write_text("# FAST3 R28.3D Frozen Target-Aligned First-Touch Economic Translation\n\n"+json.dumps(payload,indent=2,default=str),encoding="utf-8"); return payload

if __name__=="__main__":
    try: print(json.dumps(run(),indent=2,default=str))
    except AuditStop as exc: print(str(exc)); raise SystemExit(2)
