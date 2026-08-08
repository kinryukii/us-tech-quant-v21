"""One-shot R28.3 frozen-ledger placebo/random falsification; never scores models."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

RESULTS = Path(r"D:\us-tech-quant-results")
SOURCE = Path(r"D:\us-tech-quant")
if str(SOURCE / "fast3" / "src") not in sys.path:
    sys.path.insert(0, str(SOURCE / "fast3" / "src"))
P2 = RESULTS / "frozen" / "fast3" / "r28_phase2_20260808T125629Z"
LEDGERS = RESULTS / "scratch" / "fast3" / "r28_phase2_20260808T125629Z" / "ledgers"
PAYOFF = RESULTS / "scratch" / "fast3" / "r27_2_independent_heads_20260806T235700000Z" / "r27_2_regenerated_r26a2_payoff_ledger.parquet"
CONTRACT = RESULTS / "frozen" / "fast3" / "cleanroom_r2_execution_contract_completion_20260808" / "execution_contract_completion.json"
RUNTIME = RESULTS / "runtime" / "fast3" / "r28_3_frozen_placebo_20260808"
SCRATCH = RESULTS / "scratch" / "fast3" / "r28_3_frozen_placebo_20260808"
FROZEN = RESULTS / "frozen" / "fast3" / "r28_3_frozen_placebo_20260808"
SEED, N = 28031, 1000


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def q(values: np.ndarray, p: float) -> float: return float(np.quantile(values, p))
def stats(x: pd.DataFrame) -> dict:
    if x.empty: return {"trade_count": 0, "win_rate": float("nan"), "mean_gross": float("nan"), "mean_net10": float("nan"), "mean_net20": float("nan"), "median_net20": float("nan")}
    return {"trade_count": int(len(x)), "win_rate": float((x.net20 > 0).mean()), "mean_gross": float(x.gross.mean()), "mean_net10": float(x.net10.mean()), "mean_net20": float(x.net20.mean()), "median_net20": float(x.net20.median())}


def session(ts: pd.Series) -> pd.Series:
    local = pd.to_datetime(ts, utc=True).dt.tz_convert("America/New_York")
    m = local.dt.hour * 60 + local.dt.minute
    return np.select([m.lt(240) | m.ge(1200), m.lt(570), m.lt(960)], ["NIGHT", "PREMARKET", "RTH"], default="AFTERHOURS")


def load() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    lineage = json.loads((P2 / "R28_PHASE2_LINEAGE.json").read_text())
    chosen = []
    for head in ("UP", "DOWN"):
        f = LEDGERS / f"R28_3_CROSS_ASSET_FLOW_{head}_IMMUTABLE_VALIDATION_LEDGER.parquet"
        if sha(f) != lineage["ledger_hashes"]["R28_3_CROSS_ASSET_FLOW"][head]: raise RuntimeError("STOP_FROZEN_R28_3_LEDGER_REPRODUCTION_FAILURE")
        x = pd.read_parquet(f)
        if not (x["head"].eq(head).all() and x.candidate.eq("R28_3_CROSS_ASSET_FLOW").all() and (x.selected == (x.probability >= x.frozen_threshold)).all()): raise RuntimeError("STOP_FROZEN_R28_3_LEDGER_REPRODUCTION_FAILURE")
        chosen.append(x)
    all_rows = pd.concat(chosen, ignore_index=True)
    if pd.to_datetime(all_rows.decision_timestamp_utc, utc=True).max() > pd.Timestamp("2025-02-01T05:00:00Z"): raise RuntimeError("STOP_PHASE3_INTERVAL_FORBIDDEN")
    pay = pd.read_parquet(PAYOFF)
    pay["outcome_key"] = pay.candidate_instrument.astype(str) + "|" + pd.to_datetime(pay.decision_timestamp_et, utc=True).astype(str)
    if pay.outcome_key.duplicated().any() or pay.execution_contract_hash.nunique() != 1: raise RuntimeError("STOP_FROZEN_PAYOFF_CONTRACT_AMBIGUOUS")
    all_rows["outcome_key"] = all_rows.underlying_symbol.astype(str) + "|" + pd.to_datetime(all_rows.decision_timestamp_utc, utc=True).astype(str)
    all_rows = all_rows.merge(pay, on="outcome_key", how="left", suffixes=("_signal", "_payoff"), validate="many_to_one")
    all_rows.rename(columns={"candidate_id_signal":"candidate_id", "candidate_id_payoff":"payoff_candidate_id"}, inplace=True)
    if all_rows.payoff_row_hash.isna().any(): raise RuntimeError("STOP_FROZEN_R28_3_LEDGER_REPRODUCTION_FAILURE")
    all_rows["timestamp"] = pd.to_datetime(all_rows.decision_timestamp_utc, utc=True)
    all_rows["session"] = session(all_rows.timestamp); all_rows["year"] = all_rows.timestamp.dt.year; all_rows["month"] = all_rows.timestamp.dt.month
    return all_rows, pay, {"lineage_sha256": sha(P2 / "R28_PHASE2_LINEAGE.json"), "payoff_sha256": sha(PAYOFF), "execution_contract_sha256": str(pay.execution_contract_hash.iat[0]), "execution_completion_sha256": sha(CONTRACT)}


def decisions(raw: pd.DataFrame) -> pd.DataFrame:
    """Frozen simultaneous-tie and one-global-position execution policy."""
    x = raw.copy()
    both = x.groupby(["underlying_symbol", "timestamp"])["head"].transform("nunique").gt(1)
    x = x.loc[~both].copy()
    tied = x.groupby("timestamp").size().reindex(x.timestamp).to_numpy() > 1
    x = x.loc[~tied].sort_values("timestamp").copy()
    side = x["head"].str.lower()
    x["valid"] = [bool(row[f"{d}_payoff_valid"]) for (_, row), d in zip(x.iterrows(), side)]
    x["gross"] = [row[f"{d}_action_gross_return"] for (_, row), d in zip(x.iterrows(), side)]
    x["net10"] = [row[f"{d}_action_net_return_10bps"] for (_, row), d in zip(x.iterrows(), side)]
    x["net20"] = [row[f"{d}_action_net_return_20bps"] for (_, row), d in zip(x.iterrows(), side)]
    x["exit"] = pd.to_datetime([row[f"{d}_actual_exit_timestamp_et"] for (_, row), d in zip(x.iterrows(), side)], utc=True)
    kept, until = [], None
    for i, row in x.iterrows():
        if not row.valid or pd.isna(row.exit) or (until is not None and row.timestamp < until): continue
        kept.append(i); until = row.exit
    return x.loc[kept].reset_index(drop=True)


def shifted(raw: pd.DataFrame, pay: pd.DataFrame, offset: int) -> tuple[pd.DataFrame, dict]:
    from fast3.economics import executable_payoff_ledger_calendar_hard_r26a2 as cal
    target = {(r.candidate_instrument, pd.Timestamp(r.decision_timestamp_et).tz_convert("America/New_York").date(), pd.Timestamp(r.decision_timestamp_et).tz_convert("America/New_York").time()): r.outcome_key for r in pay.itertuples()}
    dates = cal._holiday_dates(pd.Timestamp("2019-12-01", tz="UTC"), pd.Timestamp("2025-02-02", tz="UTC"))
    mapped = []
    for row in raw.itertuples():
        local = row.timestamp.tz_convert("America/New_York"); d = local.date(); step = 1 if offset > 0 else -1
        for _ in range(abs(offset)):
            d += timedelta(days=step)
            while d.weekday() >= 5 or d in dates: d += timedelta(days=step)
        key = (row.underlying_symbol, d, local.time())
        if key in target: mapped.append((row.Index, target[key]))
    if not mapped:
        return raw.iloc[0:0].copy(), {"generated_count":len(raw),"mapped_count":0,"unmapped_count":len(raw),"unique_placebo_signal_count":0,"unique_outcome_path_count":0,"shared_outcome_path_count":0,"max_signals_per_outcome_path":0,"signal_cardinality_conserved":True}
    # A direction-bearing placebo signal may legitimately share one directionless
    # market path with another signal.  Preserve every signal; only the lookup is
    # many-to-one.
    keys = pd.DataFrame(mapped, columns=["source_index", "outcome_path_key"]).merge(
        pay.rename(columns={"outcome_key":"outcome_path_key"}), on="outcome_path_key", how="left", validate="many_to_one")
    out = raw.loc[keys.source_index].copy().reset_index(drop=True)
    out["original_candidate_id"] = out["candidate_id"].astype(str)
    out["original_timestamp"] = out["timestamp"]
    out["shifted_timestamp"] = pd.to_datetime(keys["decision_timestamp_et"], utc=True).to_numpy()
    out["outcome_path_key"] = keys["outcome_path_key"].to_numpy()
    out["shift_type"] = f"SHIFT_{offset:+d}_TRADING_DAY"
    out["placebo_signal_id"] = [hashlib.sha256((cid+"|"+typ+"|"+str(ts)).encode()).hexdigest()
                                for cid,typ,ts in zip(out["original_candidate_id"],out["shift_type"],out["shifted_timestamp"])]
    for column in pay.columns:
        lookup_column = "outcome_path_key" if column == "outcome_key" else column
        out[column] = keys[lookup_column].to_numpy()
    out["timestamp"] = out["shifted_timestamp"]
    counts = out.outcome_path_key.value_counts()
    audit = {"generated_count":len(raw),"mapped_count":len(out),"unmapped_count":len(raw)-len(out),
             "unique_placebo_signal_count":int(out.placebo_signal_id.nunique()),
             "unique_outcome_path_count":int(counts.size),"shared_outcome_path_count":int((counts>1).sum()),
             "max_signals_per_outcome_path":int(counts.max()),
             "signal_cardinality_conserved":bool(len(out)==out.placebo_signal_id.nunique() and len(raw)==len(out)+(len(raw)-len(out)))}
    return out, audit


def random_null(selected: pd.DataFrame, eligible: pd.DataFrame, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    groups = list(selected.groupby(["underlying_symbol", "head", "session", "year", "month"], sort=False))
    pool = {k: g.index.to_numpy() for k, g in eligible.groupby(["underlying_symbol", "head", "session", "year", "month"], sort=False)}
    wr, net = [], []
    for _ in range(N):
        idx = np.concatenate([rng.choice(pool[k], len(g), replace=False) for k, g in groups])
        s = stats(decisions(eligible.loc[idx]))
        wr.append(s["win_rate"]); net.append(s["mean_net20"])
    return np.asarray(wr), np.asarray(net)


def predictive_null(all_rows: pd.DataFrame, head: str, rng: np.random.Generator) -> dict:
    x = all_rows.loc[all_rows["head"].eq(head)].copy(); x["stratum"] = x.underlying_symbol + "|" + x.session
    base = x.target_first.mean(); order = x.sort_values(["probability", "timestamp"], ascending=[False, True], kind="mergesort")
    k5, k10 = int(np.ceil(.05 * len(x))), int(np.ceil(.10 * len(x)))
    real5, real10 = order.head(k5).target_first.mean() / base, order.head(k10).target_first.mean() / base
    counts5, counts10 = order.head(k5).stratum.value_counts(), order.head(k10).stratum.value_counts()
    groups = {k: g.target_first.to_numpy() for k, g in x.groupby("stratum")}
    a5, a10 = [], []
    for _ in range(N):
        positives5 = positives10 = 0
        for key, values in groups.items():
            n10, n5 = int(counts10.get(key, 0)), int(counts5.get(key, 0))
            if n10:
                sample = rng.choice(values, n10, replace=False); positives10 += sample.sum(); positives5 += sample[:n5].sum()
        a5.append(positives5 / k5 / base); a10.append(positives10 / k10 / base)
    a5, a10 = np.asarray(a5), np.asarray(a10)
    return {"real_top5": float(real5), "real_top10": float(real10), "top5_p95": q(a5,.95), "top5_p99":q(a5,.99), "top5_max":float(a5.max()), "top10_p95":q(a10,.95), "top10_p99":q(a10,.99), "top10_max":float(a10.max()), "top5_p":float((1+(a5>=real5).sum())/(N+1)), "top10_p":float((1+(a10>=real10).sum())/(N+1))}


def run() -> dict:
    all_rows, pay, identity = load()
    selected = all_rows.loc[all_rows.selected].copy()
    real = decisions(selected)
    shifts = {name: shifted(selected, pay, n) for name, n in (("minus1", -1), ("plus1", 1), ("plus2", 2))}
    reverse = selected.copy(); reverse["head"] = reverse["head"].map({"UP":"DOWN","DOWN":"UP"})
    rng = np.random.default_rng(SEED); wr, net = random_null(selected, all_rows, rng)
    pred = {h: predictive_null(all_rows, h, rng) for h in ("UP","DOWN")}
    real_s, rev_s = stats(real), stats(decisions(reverse))
    shift_s = {name: {**stats(decisions(frame)), **audit} for name,(frame,audit) in shifts.items()}
    classification = ("STRONG_FALSIFICATION_PASS" if real_s["mean_net20"] > q(net,.95) and (1+(net>=real_s["mean_net20"]).sum())/(N+1)<=.05 and rev_s["mean_net20"] < real_s["mean_net20"] and all(shift_s[k]["mean_net20"] < real_s["mean_net20"] for k in shift_s) and all(pred[h]["real_top5"]>pred[h]["top5_p95"] for h in pred) else ("WEAK_OR_MIXED_FALSIFICATION" if real_s["mean_net20"]>q(net,.5) else "FALSIFICATION_FAILED_EDGE_NOT_DISTINCT_FROM_RANDOM"))
    summary = {"status":"PASS","classification":classification,"identity":identity,"random_seed":SEED,"random_run_count":N,"real":real_s,"reverse":rev_s,"shifts":shift_s,
      "random":{"win_rate_median":q(wr,.5),"win_rate_p90":q(wr,.9),"win_rate_p95":q(wr,.95),"win_rate_p99":q(wr,.99),"win_rate_max":float(wr.max()),"net20_median":q(net,.5),"net20_p90":q(net,.9),"net20_p95":q(net,.95),"net20_p99":q(net,.99),"net20_max":float(net.max()),"real_win_rate_percentile":float((wr<=real_s["win_rate"]).mean()),"real_net20_percentile":float((net<=real_s["mean_net20"]).mean()),"win_rate_p":float((1+(wr>=real_s["win_rate"]).sum())/(N+1)),"net20_p":float((1+(net>=real_s["mean_net20"]).sum())/(N+1))},"predictive":pred,
      "concentration":{"top_symbol_share":float(selected.underlying_symbol.value_counts(normalize=True).iloc[0]),"top_month_share":float(selected.groupby([selected.timestamp.dt.year,selected.timestamp.dt.month]).size().div(len(selected)).max()),"top5_day_share":float(selected.timestamp.dt.date.value_counts().head(5).sum()/len(selected))},"phase3_interval_used":False,"prospective_data_used":False,"post_freeze_rescoring_count":0,"data_root_write_count":0,
      "signal_cardinality_conserved":bool(all(v["signal_cardinality_conserved"] for v in shift_s.values())),
      "shared_outcome_path_count":int(sum(v["shared_outcome_path_count"] for v in shift_s.values())),
      "max_signals_per_outcome_path":int(max(v["max_signals_per_outcome_path"] for v in shift_s.values()))}
    for d in (RUNTIME,SCRATCH,FROZEN): d.mkdir(parents=True,exist_ok=False)
    (SCRATCH/"random_null_summary.json").write_text(json.dumps(summary["random"],indent=2))
    (FROZEN/"R28_3_FROZEN_PLACEBO_FALSIFICATION_SUMMARY.json").write_text(json.dumps(summary,indent=2,default=str))
    return summary


if __name__ == "__main__":
    result=run()
    print(json.dumps(result, indent=2, default=str))
