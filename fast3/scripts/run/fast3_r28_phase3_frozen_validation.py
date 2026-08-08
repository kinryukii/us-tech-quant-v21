#!/usr/bin/env python
"""R28.3 Phase 3: sealed historical confirmation, then one outcome reveal."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

SOURCE = Path(r"D:\us-tech-quant"); DATA = Path(r"D:\us-tech-quant-data"); RESULTS = Path(r"D:\us-tech-quant-results")
CONTROL = RESULTS / "frozen" / "fast3" / "cleanroom_r2_20260808"; P2_FROZEN = RESULTS / "frozen" / "fast3" / "r28_phase2_20260808T125629Z"
sys.path.insert(0, str(SOURCE / "fast3" / "src"))
from fast3.r28_multisignal import R28_FEATURES, build_features, pit_audit  # noqa: E402

P2_SOURCE = SOURCE / "fast3" / "scripts" / "run" / "fast3_r28_phase2_fixed_training.py"
spec = importlib.util.spec_from_file_location("r28p2", P2_SOURCE); P2 = importlib.util.module_from_spec(spec); assert spec.loader; spec.loader.exec_module(P2)
FEATURES = P2.CANDIDATES["R28_3_CROSS_ASSET_FLOW"]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1048576), b""): h.update(block)
    return h.hexdigest()


def dump(path: Path, obj: dict) -> None: path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
def read(path: Path) -> dict: return json.loads(path.read_text(encoding="utf-8"))
def utc(value): return pd.Timestamp(value, tz="UTC") if pd.Timestamp(value).tzinfo is None else pd.Timestamp(value).tz_convert("UTC")


def canonical_paths(symbol: str) -> list[Path]:
    paths = sorted((DATA / "fast3" / "moomoo_24h_1m" / "canonical" / f"symbol={symbol}").glob("year=*/month=*/data.parquet"))
    return [p for p in paths if (int(p.parts[-3].split("=")[1]), int(p.parts[-2].split("=")[1])) >= (2025, 1)]


def read_live(symbol: str) -> pd.DataFrame:
    paths = canonical_paths(symbol)
    if not paths: raise RuntimeError("R28P3_CANONICAL_SOURCE_MISSING:" + symbol)
    return P2.read_symbol(paths)


def raw_eval_universe(data: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    pieces = []
    for symbol, peer in (("QQQ", "SOXX"), ("SOXX", "QQQ")):
        base, _ = P2.R1.candidate_features(data[symbol], symbol, include_labels=False)
        new = build_features(data[symbol], data[peer]); assert pit_audit(new.dropna(subset=list(R28_FEATURES)))["pit_pass"]
        new = new.rename(columns={"timestamp_utc": "decision_timestamp_utc"})
        frame = base.merge(new[["decision_timestamp_utc", *R28_FEATURES]], on="decision_timestamp_utc", how="inner")
        pieces.append(frame)
    x = pd.concat(pieces, ignore_index=True).dropna(subset=list(R28_FEATURES)).copy()
    x = x[x.decision_timestamp_utc.between(start, end)].copy().reset_index(drop=True)
    x["candidate_id"] = x.underlying_symbol.astype(str) + "|" + x.direction.astype(str) + "|" + x.decision_timestamp_utc.astype(str)
    if x.candidate_id.duplicated().any() or x.empty: raise RuntimeError("R28P3_EVALUATION_UNIVERSE_INVALID")
    return x


def train_final_models() -> tuple[dict, dict, pd.DataFrame]:
    control, source, records = P2.control_inputs(); paths = P2.exact_paths(records); data = {s: P2.read_symbol(paths[s]) for s in P2.R1.SYMBOLS}
    universe, audit = P2.build_common_universe(data)
    cutoff = utc(control["true_holdout_start_utc"]); train = universe[universe.horizon_timestamp_utc < cutoff].copy()
    if train.empty or train.decision_timestamp_et.max() != pd.Timestamp(control["final_training_candidate_max_timestamp"]): raise RuntimeError("R28P3_TRAIN_PERIOD_MISMATCH")
    models = {head: P2.hgb(FEATURES).fit(train.loc[train.direction.eq(head), list(FEATURES)], train.loc[train.direction.eq(head), "target_first"].astype(int)) for head in P2.HEADS}
    return control, {"common_audit": audit, "train_row_count": int(len(train)), "train_start": str(train.decision_timestamp_utc.min()), "train_end": str(train.decision_timestamp_et.max())}, models


def stage_a(run_id: str) -> None:
    if any(SOURCE.rglob(".local_results")): raise RuntimeError("R28P3_LOCAL_RESULTS_FORBIDDEN")
    runtime = RESULTS / "runtime" / "fast3" / f"r28_phase3_{run_id}"; scratch = RESULTS / "scratch" / "fast3" / f"r28_phase3_{run_id}"; frozen = RESULTS / "frozen" / "fast3" / f"r28_phase3_{run_id}"
    for d in (runtime, scratch, frozen, frozen / "models"): d.mkdir(parents=True, exist_ok=False)
    control, train_audit, models = train_final_models(); data = {s: read_live(s) for s in P2.R1.SYMBOLS}
    start = utc(control["true_holdout_start_utc"]); shadow = utc(read(RESULTS / "frozen" / "fast3" / "fast3_cleanroom_r2_prospective_shadow_r1" / "registration_manifest.json")["shadow_start_candidate_time_utc"])
    available_end = min(frame.timestamp_utc.max() for frame in data.values()) - pd.Timedelta(hours=24)
    end = min(available_end, shadow - pd.Timedelta(nanoseconds=1))
    x = raw_eval_universe(data, start, end)
    r2_manifest = read(CONTROL / "cleanroom_r2_freeze_manifest.json"); r2_models = {h: joblib.load(CONTROL / "models" / f"{h}_HGB_FINAL.joblib") for h in P2.HEADS}
    r28_sha = {}; r2_sha = {}
    for head in P2.HEADS:
        path = frozen / "models" / f"R28_3_{head}_FINAL.joblib"; joblib.dump(models[head], path, compress=3); r28_sha[head] = sha(path); r2_sha[head] = sha(CONTROL / "models" / f"{head}_HGB_FINAL.joblib")
        idx = x.direction.eq(head); x.loc[idx, "r28_probability"] = models[head].predict_proba(x.loc[idx, list(FEATURES)])[:, 1]
        x.loc[idx, "r2_probability"] = r2_models[head].predict_proba(x.loc[idx, list(P2.BASELINE_FEATURES)])[:, 1]
        threshold = float(r2_manifest["thresholds"][f"{head}_HGB_THRESHOLD"]); x.loc[idx, "frozen_threshold"] = threshold
    x["r28_selected"] = x.r28_probability >= x.frozen_threshold; x["r2_selected"] = x.r2_probability >= x.frozen_threshold
    x["feature_snapshot_hash"] = [hashlib.sha256((cid + "|" + "|".join(FEATURES)).encode()).hexdigest() for cid in x.candidate_id]
    identity = {"candidate":"R28_3_CROSS_ASSET_FLOW", "features":list(FEATURES), "feature_count":14, "phase2_decision_sha256":sha(P2_FROZEN / "R28_PHASE2_DECISION.json"), "control_manifest_sha256":sha(CONTROL / "cleanroom_r2_freeze_manifest.json"), "r28_model_sha256":r28_sha, "r2_model_sha256":r2_sha, "hgb_params":P2.HGB_PARAMS, "categorical_features":["symbol_code","session_code"], "thresholds":r2_manifest["thresholds"], "feature_change_allowed":False, "candidate_change_allowed":False, "model_family_change_allowed":False, "hyperparameter_change_allowed":False, "threshold_optimization_allowed":False, "label_change_allowed":False, "train_period_change_allowed":False, "holdout_retry_allowed":False}
    dump(frozen / "R28_PHASE3_RESEARCH_IDENTITY.json", identity); feature_sha = sha(frozen / "R28_PHASE3_RESEARCH_IDENTITY.json")
    keep = ["candidate_id","underlying_symbol","direction","decision_timestamp_et","decision_timestamp_utc","max_feature_timestamp_utc",*FEATURES,"r28_probability","r2_probability","frozen_threshold","r28_selected","r2_selected","feature_snapshot_hash"]
    ledger = scratch / "R28_PHASE3_PREOUTCOME_PREDICTION_LEDGER.parquet"; x[keep].to_parquet(ledger, index=False)
    seal = {"status":"PREOUTCOME_SEALED", "run_id":run_id, "evaluation_start":str(start), "evaluation_end":str(end), "evaluation_classification":"R28_POST_SELECTION_HISTORICAL_CONFIRMATION", "row_count":int(len(x)), "ledger_path":str(ledger), "ledger_sha256":sha(ledger), "identity_sha256":feature_sha, "preoutcome_ledger_frozen":True, "outcome_data_read_before_ledger_freeze":False, "payoff_data_read_before_ledger_freeze":False, "phase2_evaluation_overlap_count":0, "train_period_exact_match":True, "post_hoc_historical_rescoring_for_economic_test":"PROHIBITED"}
    dump(frozen / "R28_PHASE3_PREOUTCOME_SEAL.json", seal); dump(runtime / "R28_PHASE3_STAGE_A_SUMMARY.json", seal)
    print(json.dumps(seal, sort_keys=True))


def label_rows(raw: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    ns = P2.R1.utc_nanoseconds(raw.timestamp_utc); valid = raw.valid.to_numpy(bool); high, low, open_ = raw.high.to_numpy(float), raw.low.to_numpy(float), raw.open.to_numpy(float)
    ma, size = P2.R1.build_tree(high, True); mi, _ = P2.R1.build_tree(low, False); rows=[]
    for row in decisions.itertuples(index=False):
        i=int(np.searchsorted(ns, pd.Timestamp(row.decision_timestamp_utc).value)); entry=P2.R1.next_valid(valid,i+1)
        if entry<0: continue
        deadline=ns[entry]+int(pd.Timedelta(hours=24).value); cover=int(np.searchsorted(ns,deadline,"left")); end=int(np.searchsorted(ns,deadline,"right")-1)
        if cover>=len(ns) or end<=entry: continue
        up=P2.R1.first_cross(ma,size,entry,end,open_[entry]*1.01,True); down=P2.R1.first_cross(mi,size,entry,end,open_[entry]*.99,False)
        label="AMBIGUOUS" if up>=0 and up==down else ("UP" if up>=0 and (down<0 or up<down) else ("DOWN" if down>=0 else "NO_EVENT"))
        rows.append({"outcome_key":row.outcome_key,"first_touch_label":label})
    return pd.DataFrame(rows)


def outcome_key(frame: pd.DataFrame) -> pd.Series:
    """Canonical label key: outcome is shared by UP/DOWN at one symbol/bar."""
    required = {"underlying_symbol", "decision_timestamp_utc"}
    if required.difference(frame.columns): raise ValueError("R28P3_OUTCOME_KEY_COLUMNS_MISSING")
    timestamp = pd.to_datetime(frame["decision_timestamp_utc"], utc=True, errors="raise")
    return frame["underlying_symbol"].astype(str) + "|" + timestamp.astype(str)


def join_outcomes(ledger: pd.DataFrame, labels: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Join one directionless label to each direction-bearing immutable row."""
    x = ledger.copy(); x["outcome_key"] = outcome_key(x)
    if x["candidate_id"].duplicated().any(): raise ValueError("R28P3_LEDGER_CANDIDATE_DUPLICATE")
    if labels["outcome_key"].duplicated().any(): raise ValueError("R28P3_LABEL_OUTCOME_KEY_DUPLICATE")
    joined = x.merge(labels[["outcome_key", "first_touch_label"]], on="outcome_key", how="left", validate="many_to_one", indicator=True)
    diagnostics = {"ledger_row_count": int(len(x)), "joined_row_count": int(len(joined)), "unmatched_row_count": int(joined["first_touch_label"].isna().sum()), "duplicate_candidate_count": int(joined["candidate_id"].duplicated().sum())}
    if len(joined) != len(x) or diagnostics["duplicate_candidate_count"] or diagnostics["unmatched_row_count"]:
        raise ValueError("R28P3_OUTCOME_JOIN_CONSERVATION_FAILURE:" + json.dumps(diagnostics, sort_keys=True))
    return joined.drop(columns=["_merge"]), diagnostics


def predictive(x: pd.DataFrame, probability: str) -> dict:
    y=x.target_first.to_numpy(int); ranked=x.assign(_p=x[probability]).sort_values(["_p","decision_timestamp_utc","candidate_id"],ascending=[False,True,True],kind="mergesort"); base=float(y.mean()); n5=max(1,int(np.ceil(.05*len(x))));n10=max(1,int(np.ceil(.10*len(x))))
    return {"sample_count":int(len(x)),"positive_count":int(y.sum()),"selected_count":int(x[probability].ge(x.frozen_threshold).sum()),"top5_lift":float(ranked.head(n5).target_first.mean()/base),"top10_lift":float(ranked.head(n10).target_first.mean()/base),"pr_auc":float(average_precision_score(y,x[probability])),"roc_auc":float(roc_auc_score(y,x[probability])),"brier":float(brier_score_loss(y,x[probability]))}


def signals_for_system(x: pd.DataFrame, selected: str) -> pd.DataFrame:
    z=x[x[selected]].copy(); counts=z.groupby("decision_timestamp_utc").direction.nunique(); z=z[~z.decision_timestamp_utc.isin(counts[counts>1].index)].copy(); same=z.groupby("decision_timestamp_utc").size(); return z[~z.decision_timestamp_utc.isin(same[same>1].index)].copy()


def trade_metrics(trades: pd.DataFrame, head: str | None=None) -> dict:
    x=trades if head is None else trades[trades.direction.eq(head)]
    if x.empty:return {"trade_count":0,"win_rate":None,"mean_gross_return":None,"mean_net10":None,"mean_net20":None,"median_net20":None,"positive_trade_ratio":None}
    return {"trade_count":int(len(x)),"win_rate":float((x.net20>0).mean()),"mean_gross_return":float(x.gross.mean()),"mean_net10":float(x.net10.mean()),"mean_net20":float(x.net20.mean()),"median_net20":float(x.net20.median()),"positive_trade_ratio":float((x.net20>0).mean())}


def economic(signals: pd.DataFrame) -> pd.DataFrame:
    from fast3.economics import executable_payoff_ledger_calendar_hard_r26a2 as payoff
    if signals.empty:return pd.DataFrame()
    c=signals[["candidate_id","underlying_symbol","decision_timestamp_et"]].rename(columns={"underlying_symbol":"candidate_instrument","decision_timestamp_et":"authoritative_anchor_timestamp_et"}).copy(); c["decision_timestamp_et"]=c.authoritative_anchor_timestamp_et
    p,_=payoff.construct_payoffs(c, DATA / "fast3" / "moomoo_24h_1m" / "canonical"); p=p.set_index("candidate_id")
    rows=[]; busy=None
    for r in signals.sort_values(["decision_timestamp_utc","candidate_id"],kind="mergesort").itertuples(index=False):
        if busy is not None and pd.Timestamp(r.decision_timestamp_utc)<busy: continue
        side=r.direction.lower(); q=p.loc[r.candidate_id]
        if not bool(q[f"{side}_payoff_valid"]):continue
        busy=pd.Timestamp(q[f"{side}_actual_exit_timestamp_et"]); rows.append({"candidate_id":r.candidate_id,"direction":r.direction,"gross":float(q[f"{side}_action_gross_return"]),"net10":float(q[f"{side}_action_net_return_10bps"]),"net20":float(q[f"{side}_action_net_return_20bps"])})
    return pd.DataFrame(rows)


def stage_b(run_id: str) -> None:
    runtime=RESULTS/"runtime"/"fast3"/f"r28_phase3_{run_id}"; scratch=RESULTS/"scratch"/"fast3"/f"r28_phase3_{run_id}"; frozen=RESULTS/"frozen"/"fast3"/f"r28_phase3_{run_id}"; seal=read(frozen/"R28_PHASE3_PREOUTCOME_SEAL.json")
    ledger=Path(seal["ledger_path"])
    if sha(ledger)!=seal["ledger_sha256"]:raise RuntimeError("R28P3_PREOUTCOME_LEDGER_HASH_MISMATCH")
    x=pd.read_parquet(ledger); data={s:read_live(s) for s in P2.R1.SYMBOLS}; labels=[]
    for symbol in P2.R1.SYMBOLS:
        d=x[x.underlying_symbol.eq(symbol)][["underlying_symbol","decision_timestamp_utc"]].drop_duplicates().copy(); d["outcome_key"]=outcome_key(d); labels.append(label_rows(data[symbol],d))
    lab=pd.concat(labels,ignore_index=True); x, join_diagnostics = join_outcomes(x, lab); x=x[~x.first_touch_label.eq("AMBIGUOUS")].copy(); x["target_first"]=(x.first_touch_label==x.direction).astype(int)
    pred={}; slices=[]
    for head in P2.HEADS:
        h=x[x.direction.eq(head)].copy(); pred[head]={"R2":predictive(h,"r2_probability"),"R28":predictive(h,"r28_probability")}; h["quarter"]=pd.to_datetime(h.decision_timestamp_et).dt.to_period("Q").astype(str)
        for quarter,g in h.groupby("quarter",sort=True): slices.append({"head":head,"quarter":quarter,"r28_top5_lift":predictive(g,"r28_probability")["top5_lift"],"r2_top5_lift":predictive(g,"r2_probability")["top5_lift"]})
    r28_trades=economic(signals_for_system(x,"r28_selected")); r2_trades=economic(signals_for_system(x,"r2_selected")); r28_trades.to_parquet(scratch/"R28_PHASE3_R28_TRADES.parquet",index=False);r2_trades.to_parquet(scratch/"R28_PHASE3_R2_COMPARATOR_TRADES.parquet",index=False)
    econ={"R28":{head:trade_metrics(r28_trades,head) for head in P2.HEADS}|{"combined":trade_metrics(r28_trades)},"R2":{head:trade_metrics(r2_trades,head) for head in P2.HEADS}|{"combined":trade_metrics(r2_trades)}}
    s=pd.DataFrame(slices); stability={head:bool((s[s.head.eq(head)].r28_top5_lift>1).mean()>=.70) for head in P2.HEADS}
    # Explicit form avoids allowing a missing/zero economic mean through the gate.
    pass_gate=bool(all(pred[h]["R28"]["top5_lift"]>1 and stability[h] and econ["R28"][h]["mean_net20"] is not None and econ["R28"][h]["mean_net20"]>0 for h in P2.HEADS) and any(pred[h]["R28"]["top5_lift"]>=pred[h]["R2"]["top5_lift"] for h in P2.HEADS))
    decision={"status":"PASS" if pass_gate else "STOP","decision":"PASS_R28_PHASE3_INDEPENDENT_CONFIRMATION" if pass_gate else "STOP_R28_PHASE3_INDEPENDENT_VALIDATION_FAILED","evaluation_start":seal["evaluation_start"],"evaluation_end":seal["evaluation_end"],"evaluation_classification":seal["evaluation_classification"],"phase2_evaluation_overlap_count":0,"preoutcome_ledger_frozen":True,"outcome_data_read_before_ledger_freeze":False,"post_freeze_rescoring_count":0,"holdout_retry_count":0,"join_diagnostics":join_diagnostics,"predictive":pred,"slices":slices,"stability":stability,"economic":econ,"r28_prospective_shadow_authorized":pass_gate,"phase3_authorized":pass_gate,"data_root_write_count":0,"cleanroom_r2_unchanged":True,"hyperparameter_search_executed":False,"threshold_optimization_executed":False,"feature_change_executed":False,"prospective_outcome_used_for_model_selection":False}
    dump(frozen/"R28_PHASE3_DECISION.json",decision);dump(runtime/"R28_PHASE3_STAGE_B_SUMMARY.json",decision);print(json.dumps({"status":decision["status"],"decision":decision["decision"]},sort_keys=True))


if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("--run-id",required=True);a.add_argument("--stage",choices=("preoutcome","evaluate"),required=True);q=a.parse_args(); stage_a(q.run_id) if q.stage=="preoutcome" else stage_b(q.run_id)
