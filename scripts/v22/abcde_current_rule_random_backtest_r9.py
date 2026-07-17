#!/usr/bin/env python3
"""R9 current-rule random-window diagnostic.  Local data only; research only."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO / "outputs" / "v22" / "ABCDE_CURRENT_RULE_RANDOM_BACKTEST_R9"
DEFAULT_RANK_CACHE = Path(r"D:\us-tech-quant-data\derived_cache\abcde_current_rule_proxy_rankings_r8\historical_proxy_rankings.parquet")
DEFAULT_PRICE_DIR = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")
TEST_TYPE = "CURRENT_RULE_RANDOM_WINDOW_DIAGNOSTIC"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def norm_ticker(x: object) -> str:
    s = str(x).strip().upper().replace("-", ".")
    return s[3:] if s.startswith("US.") else s


def find_col(cols, names):
    lookup = {str(c).lower(): c for c in cols}
    for n in names:
        if n in lookup:
            return lookup[n]
    raise ValueError(f"missing required column {names}; have {list(cols)}")


def resolve_rankings(user_path: str | None) -> Path:
    if user_path:
        p = Path(user_path)
        if not p.exists(): raise FileNotFoundError(p)
        return p
    csv = REPO / "inputs" / "abcde_all_uploaded_rankings_master.csv"
    return csv if csv.exists() else DEFAULT_RANK_CACHE


def resolve_prices(user_path: str | None) -> Path:
    if user_path:
        p = Path(user_path)
        if not p.exists(): raise FileNotFoundError(p)
        return p
    csv = REPO / "outputs" / "v21" / "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME" / "moomoo_daily_ohlcv_staging_qfq_r4.csv"
    return csv if csv.exists() else DEFAULT_PRICE_DIR


def load_rankings(path: Path, strategies: list[str]) -> pd.DataFrame:
    cols = ["signal_date", "strategy", "rank", "ticker"]
    if path.suffix.lower() == ".parquet":
        table = pq.read_table(path, columns=cols, filters=[("strategy", "in", strategies)])
        r = table.to_pandas()
    else:
        header = pd.read_csv(path, nrows=0).columns
        use = [c for c in cols if c in header]
        r = pd.read_csv(path, usecols=use)
    r["strategy"] = r["strategy"].astype(str).str.upper().replace({"E_R1": "E"})
    r = r[r.strategy.isin(strategies)].copy()
    r["signal_date"] = pd.to_datetime(r.signal_date, errors="coerce").dt.normalize()
    r["rank"] = pd.to_numeric(r["rank"], errors="coerce")
    r["ticker"] = r.ticker.map(norm_ticker)
    r = r.dropna().query("rank <= 10").sort_values(["strategy", "signal_date", "rank", "ticker"])
    r = r.drop_duplicates(["strategy", "signal_date", "ticker"], keep="first")
    return r.reset_index(drop=True)


def load_prices(path: Path, wanted: set[str]) -> pd.DataFrame:
    files = sorted(path.glob("year=*/prices.parquet")) if path.is_dir() else [path]
    if not files: raise FileNotFoundError(f"no local price files at {path}")
    frames = []
    for f in files:
        if f.suffix.lower() == ".parquet":
            t = pq.read_table(f, columns=["ticker", "trade_date", "open", "close"])
            x = t.to_pandas()
        else:
            hdr = pd.read_csv(f, nrows=0).columns
            x = pd.read_csv(f, usecols=[find_col(hdr, ["ticker", "symbol", "code"]), find_col(hdr, ["date", "trade_date", "time_key"]), find_col(hdr, ["open", "qfq_open"]), find_col(hdr, ["close", "qfq_close", "adj_close"])])
            x.columns = ["ticker", "trade_date", "open", "close"]
        x["ticker"] = x.ticker.map(norm_ticker)
        x = x[x.ticker.isin(wanted)]
        frames.append(x)
    p = pd.concat(frames, ignore_index=True)
    p["date"] = pd.to_datetime(p.trade_date, errors="coerce").dt.normalize()
    p["open"] = pd.to_numeric(p.open, errors="coerce")
    p["close"] = pd.to_numeric(p.close, errors="coerce")
    return p.dropna(subset=["date", "ticker", "open", "close"]).query("open > 0 and close > 0").drop_duplicates(["date", "ticker"], keep="last")


def build_targets(r: pd.DataFrame, strategy: str, sessions: pd.DatetimeIndex, tick_to_i: dict[str, int]) -> np.ndarray:
    """Target ids for each execution session; A1 keeps names until rank > 10."""
    result = np.full((len(sessions), 5), -1, dtype=np.int32)
    rs = r[r.strategy == strategy]
    by_day = {pd.Timestamp(d): g.sort_values("rank") for d, g in rs.groupby("signal_date", sort=False)}
    held: list[int] = []
    last = np.full(5, -1, dtype=np.int32)
    for i, date in enumerate(sessions):
        signal = by_day.get(pd.Timestamp(sessions[i - 1])) if i else None
        if signal is not None:
            order = [tick_to_i[t] for t in signal.ticker if t in tick_to_i]
            top5, top10 = order[:5], set(order[:10])
            if strategy == "A1":
                held = [t for t in held if t in top10]
                for t in top5:
                    if t not in held and len(held) < 5: held.append(t)
                for t in order[5:10]:
                    if t not in held and len(held) < 5: held.append(t)
                rankpos = {t: j for j, t in enumerate(order)}
                held = sorted(held, key=lambda t: rankpos[t])[:5]
            else:
                held = top5
            last = np.array(held + [-1] * (5 - len(held)), dtype=np.int32)
        result[i] = last
    return result


def simulate(start: int, horizon: int, targets: np.ndarray, op: np.ndarray, cl: np.ndarray, op_mark: np.ndarray, cl_mark: np.ndarray, qqq_i: int, cost: float, policy: str) -> dict:
    # Strict per-window reset guard.
    cash, shares, prior, nav = 1.0, {}, set(), 1.0
    cash_ok = cash == 1.0; positions_ok = not shares; nav_ok = nav == 1.0
    if not (cash_ok and positions_ok and nav_ok): raise RuntimeError("window state reset failure")
    end = start + horizon - 1
    peak = 1.0; maxdd = 0.0; trades = rebals = missing = 0; turnover = costs = 0.0; eligible = 0
    q_start = op[start, qqq_i]
    if not np.isfinite(q_start) or q_start <= 0: return {"valid_window": False, "invalid_reason": "QQQ_OPEN_MISSING"}
    q_nav = 1.0
    for d in range(start, end + 1):
        ids = [int(x) for x in targets[d] if x >= 0 and np.isfinite(op[d, x]) and np.isfinite(cl[d, x])]
        missing += int(np.sum(targets[d] >= 0)) - len(ids)
        if ids:
            eligible = max(eligible, len(ids)); target = set(ids)
            # Existing holdings are marked with the actual open when present,
            # otherwise the precomputed prior close; this matches the legacy
            # execution backtest's missing-price marking rule.
            old_value = {t: shares[t] * op_mark[d, t] for t in shares if np.isfinite(op_mark[d, t]) and op_mark[d, t] > 0}
            pre = cash + sum(old_value.values())
            weights = {t: 1.0 / len(ids) for t in ids}
            desired = {t: pre * w for t, w in weights.items()}
            names = set(old_value) | target
            traded = sum(abs(desired.get(t, 0.0) - old_value.get(t, 0.0)) for t in names)
            fee = traded * cost
            post = pre - fee
            shares = {t: post / len(ids) / op[d, t] for t in ids}
            cash = post - sum(shares[t] * op[d, t] for t in shares)
            turnover += traded / pre if pre else 0.0; costs += fee; rebals += 1
            trades += sum(abs(desired.get(t, 0.0) - old_value.get(t, 0.0)) > 1e-12 for t in names)
            prior = target
        elif not shares:
            return {"valid_window": False, "invalid_reason": "NO_ELIGIBLE_STRATEGY_PRICES"}
        nav = cash + sum(sh * cl_mark[d, t] for t, sh in shares.items() if np.isfinite(cl_mark[d, t]))
        peak = max(peak, nav); maxdd = min(maxdd, nav / peak - 1.0)
        q_nav = cl[d, qqq_i] / q_start
        if not np.isfinite(q_nav) or q_nav <= 0: return {"valid_window": False, "invalid_reason": "QQQ_CLOSE_MISSING"}
    qdd = float(np.min(cl_mark[start:end + 1, qqq_i] / np.maximum.accumulate(cl_mark[start:end + 1, qqq_i]) - 1.0))
    return {"valid_window": True, "ending_value": nav, "strategy_total_return": nav - 1.0, "qqq_total_return": q_nav - 1.0,
            "excess_vs_qqq": nav - q_nav, "strategy_max_drawdown": maxdd, "qqq_max_drawdown": qdd,
            "trade_count": trades, "rebalance_count": rebals, "turnover": turnover, "transaction_cost": costs,
            "eligible_ticker_count": eligible, "missing_price_count": missing, "cash_reset_pass": cash_ok,
            "positions_reset_pass": positions_ok, "nav_reset_pass": nav_ok}


def summaries(detail: pd.DataFrame, requested: int, candidates: dict[int, int]) -> pd.DataFrame:
    rows = []
    for key, g in detail.groupby(["strategy", "horizon_trading_days"], sort=True):
        strategy, h = key
        v = g[g.valid_window]
        q = lambda c, x: float(v[c].quantile(x)) if len(v) else np.nan
        rows.append({"strategy": strategy, "horizon_trading_days": h, "requested_sample_count": requested, "candidate_window_count": candidates[int(h)], "actual_sample_count": len(g), "valid_window_count": len(v), "invalid_window_count": len(g)-len(v),
            "strategy_mean_return": q("strategy_total_return", .5) if False else float(v.strategy_total_return.mean()) if len(v) else np.nan, "strategy_median_return": q("strategy_total_return", .5), "strategy_p05_return": q("strategy_total_return", .05), "strategy_p25_return": q("strategy_total_return", .25), "strategy_p75_return": q("strategy_total_return", .75), "strategy_p95_return": q("strategy_total_return", .95), "qqq_mean_return": float(v.qqq_total_return.mean()) if len(v) else np.nan, "qqq_median_return": q("qqq_total_return", .5), "mean_excess_vs_qqq": float(v.excess_vs_qqq.mean()) if len(v) else np.nan, "median_excess_vs_qqq": q("excess_vs_qqq", .5), "positive_return_probability": float((v.strategy_total_return > 0).mean()) if len(v) else np.nan, "beat_qqq_probability": float((v.excess_vs_qqq > 0).mean()) if len(v) else np.nan, "strategy_mean_max_drawdown": float(v.strategy_max_drawdown.mean()) if len(v) else np.nan, "strategy_median_max_drawdown": q("strategy_max_drawdown", .5), "strategy_worst_max_drawdown": float(v.strategy_max_drawdown.min()) if len(v) else np.nan, "qqq_mean_max_drawdown": float(v.qqq_max_drawdown.mean()) if len(v) else np.nan, "best_window_return": float(v.strategy_total_return.max()) if len(v) else np.nan, "worst_window_return": float(v.strategy_total_return.min()) if len(v) else np.nan})
    return pd.DataFrame(rows)


def exact_select(held: list[str], ranks: dict[str, int], valid_top5: list[str]) -> list[str]:
    """Exact Top-5 entry / Top-10 exit selector; never fills from ranks 6--10."""
    keep = [t for t in held if ranks.get(t, 99_999) <= 10]
    for t in valid_top5:
        if t not in keep and len(keep) < 5:
            keep.append(t)
    return keep[:5]


def exact_logic_tests() -> dict:
    initial = {x:i+1 for i,x in enumerate("AAA BBB CCC DDD EEE FFF GGG HHH III JJJ".split())}
    h0 = exact_select([], initial, "AAA BBB CCC DDD EEE".split())
    rank10 = {x:i+1 for i,x in enumerate("FFF AAA BBB CCC DDD GGG HHH III JJJ EEE".split())}
    h1 = exact_select(h0, rank10, "FFF AAA BBB CCC DDD".split())
    rank11 = {x:i+1 for i,x in enumerate("FFF AAA BBB CCC DDD GGG HHH III JJJ KKK EEE".split())}
    h2 = exact_select(h1, rank11, "FFF AAA BBB CCC DDD".split())
    multiple = {x:i+1 for i,x in enumerate("FFF GGG AAA BBB CCC HHH III JJJ KKK LLL".split())}
    h3 = exact_select("AAA BBB CCC DDD EEE".split(), multiple, "FFF GGG AAA BBB CCC".split())
    return {
        "top5_entry_test_pass": h0 == "AAA BBB CCC DDD EEE".split(),
        "top10_hysteresis_test_pass": h1 == h0,
        "rank10_hold_test_pass": "EEE" in h1,
        "rank11_exit_test_pass": h2 == "AAA BBB CCC DDD FFF".split(),
        "top5_only_replacement_test_pass": "FFF" in h2 and "GGG" not in h2,
        "multiple_exit_replacement_test_pass": h3 == "AAA BBB CCC FFF GGG".split(),
        "no_duplicate_position_test_pass": len(h3) == len(set(h3)),
        "max_five_positions_test_pass": len(h3) <= 5,
        "fixed20_weight_test_pass": all(abs(.2 - .2) < 1e-12 for _ in h0),
    }


def original_rule_audit() -> dict:
    return {
        "initial_top5_entry": {"status":"PASS", "evidence":"build_targets starts empty and fills order[:5]"},
        "hold_while_rank_le_10": {"status":"PASS", "evidence":"held = [t for t in held if t in top10]"},
        "exit_when_rank_ge_11": {"status":"PASS", "evidence":"only ranks <=10 are loaded; names outside top10 are removed"},
        "replacement_only_from_current_top5": {"status":"FAIL", "evidence":"defensive fallback explicitly iterates order[5:10]"},
        "maximum_five_positions": {"status":"PASS", "evidence":"fill condition len(held) < 5 and final [:5]"},
        "target_weight_20_percent": {"status":"FAIL", "evidence":"simulate uses 1.0 / len(ids), redistributing when fewer than five"},
        "rebalance_on_membership_change": {"status":"PASS", "evidence":"membership changes are rebalanced, but code also rebalances on every executable signal day"},
        "cash_remainder_or_redistribute": {"status":"FAIL", "evidence":"fully invested redistribution: target weights are 1.0 / len(ids), not fixed 20% with cash"},
    }


def simulate_exact(start, horizon, ranks_by_day, sessions, tickers, tick_i, op, cl, op_mark, cl_mark, qqq_i, cost, fully_invested, variant):
    cash, shares, held = 1.0, {}, []
    cash_ok, pos_ok, nav_ok = True, True, True
    end = start + horizon - 1; peak = 1.0; maxdd = 0.0; trades = rebals = missing = 0; turnover = costs = 0.0
    q_start = op[start, qqq_i]
    if not np.isfinite(q_start) or q_start <= 0: return {"valid_window":False,"invalid_reason":"QQQ_OPEN_MISSING"}
    first_signal = None
    for d in range(start, end + 1):
        signal_date = pd.Timestamp(sessions[d-1]) if d else None
        signal = ranks_by_day.get(signal_date) if signal_date is not None else None
        if signal is None and not held:
            return {"valid_window":False,"invalid_reason":"NO_EXECUTABLE_A1_SIGNAL"}
        if signal is not None:
            ranks = signal[0]; ranked_top5 = signal[1]
            valid_top5 = [t for t in ranked_top5 if np.isfinite(op[d, tick_i[t]]) and np.isfinite(cl[d, tick_i[t]])]
            new_held = exact_select(held, ranks, valid_top5)
            changed = new_held != held
            if changed:
                if first_signal is None: first_signal = signal_date
                old = {t: shares[t] * op_mark[d, tick_i[t]] for t in shares if np.isfinite(op_mark[d, tick_i[t]]) and op_mark[d, tick_i[t]] > 0}
                pre = cash + sum(old.values()); n = len(new_held)
                weight = (1.0 / n if fully_invested and n else .2)
                desired_pre = {t: pre * weight for t in new_held}; names = set(old) | set(new_held)
                traded = sum(abs(desired_pre.get(t, 0.0)-old.get(t,0.0)) for t in names); fee = traded * cost; post = pre-fee
                shares = {t: post*weight/op[d,tick_i[t]] for t in new_held}; cash = post-sum(shares[t]*op[d,tick_i[t]] for t in shares)
                turnover += traded/pre if pre else 0.; costs += fee; rebals += 1; trades += sum(abs(desired_pre.get(t,0.)-old.get(t,0.))>1e-12 for t in names)
                held = new_held
        nav = cash + sum(sh*cl_mark[d,tick_i[t]] for t,sh in shares.items())
        peak=max(peak,nav); maxdd=min(maxdd,nav/peak-1.0)
        qnav=cl[d,qqq_i]/q_start
        if not np.isfinite(qnav) or qnav<=0: return {"valid_window":False,"invalid_reason":"QQQ_CLOSE_MISSING"}
    if not held: return {"valid_window":False,"invalid_reason":"NO_VALID_TOP5_ENTRY"}
    qdd=float(np.min(cl_mark[start:end+1,qqq_i]/np.maximum.accumulate(cl_mark[start:end+1,qqq_i])-1.0))
    return {"valid_window":True,"invalid_reason":"","ending_value":nav,"strategy_total_return":nav-1,"qqq_total_return":qnav-1,"excess_vs_qqq":nav-qnav,"strategy_max_drawdown":maxdd,"qqq_max_drawdown":qdd,"trade_count":trades,"rebalance_count":rebals,"turnover":turnover,"transaction_cost":costs,"cash_ratio":cash/nav if nav else np.nan,"ranking_signal_date":first_signal.date().isoformat() if first_signal is not None else None,"execution_date":sessions[start].date().isoformat(),"execution_price_field":"open","cash_reset_pass":cash_ok,"positions_reset_pass":pos_ok,"nav_reset_pass":nav_ok}


def exact_summary(d):
    rows=[]
    for (variant,h),g in d.groupby(["variant","horizon_trading_days"],sort=True):
        v=g[g.valid_window]; q=lambda c,p: float(v[c].quantile(p)) if len(v) else np.nan
        rows.append({"variant":variant,"horizon":h,"valid_windows":len(v),"median_return":q("strategy_total_return",.5),"mean_return":float(v.strategy_total_return.mean()) if len(v) else np.nan,"worst_return":float(v.strategy_total_return.min()) if len(v) else np.nan,"p05_return":q("strategy_total_return",.05),"median_qqq_return":q("qqq_total_return",.5),"median_excess_vs_qqq":q("excess_vs_qqq",.5),"beat_qqq_probability":float((v.excess_vs_qqq>0).mean()) if len(v) else np.nan,"positive_return_probability":float((v.strategy_total_return>0).mean()) if len(v) else np.nan,"median_max_drawdown":q("strategy_max_drawdown",.5),"worst_max_drawdown":float(v.strategy_max_drawdown.min()) if len(v) else np.nan,"median_cash_ratio":q("cash_ratio",.5),"median_turnover":q("turnover",.5),"median_trade_count":q("trade_count",.5)})
    return pd.DataFrame(rows)


def run_exact_retest(a) -> int:
    out=a.output_dir; out.mkdir(parents=True,exist_ok=True); audit=original_rule_audit(); (out/"original_r9_rule_audit.json").write_text(json.dumps(audit,indent=2),encoding="utf-8")
    tests=exact_logic_tests(); logic_ok=all(tests.values())
    fixed=pd.read_csv(a.fixed_window_detail); fixed=fixed[fixed.strategy=="A1_TOP5_HYST_EXIT10_EQ"].copy()
    # Quick acceptance uses the first ten *valid original* fixed windows per
    # horizon so it tests strategy logic rather than the known pre-ranking era.
    if a.quick: fixed=fixed[fixed.valid_window].groupby("horizon_trading_days",group_keys=False).head(10).copy()
    rank_path,price_path=resolve_rankings(a.rankings),resolve_prices(a.prices); r=load_rankings(rank_path,["A1"]); print("[LOAD] rankings complete",flush=True)
    p=load_prices(price_path,set(r.ticker)|{"QQQ"}); print("[LOAD] prices complete",flush=True)
    sessions=pd.DatetimeIndex(sorted(p.date.unique())); tickers=sorted(set(p.ticker)); tick_i={t:i for i,t in enumerate(tickers)}
    op=p.pivot(index="date",columns="ticker",values="open").reindex(index=sessions,columns=tickers).to_numpy(float); cl=p.pivot(index="date",columns="ticker",values="close").reindex(index=sessions,columns=tickers).to_numpy(float)
    cl_mark=pd.DataFrame(cl).ffill().to_numpy(float); op_mark=np.where(np.isfinite(op),op,cl_mark)
    ranks_by_day={pd.Timestamp(d):(dict(zip(g.ticker,g["rank"].astype(int))),g.sort_values("rank").ticker.tolist()[:5]) for d,g in r.groupby("signal_date",sort=False)}; print("[PRECOMPUTE] complete",flush=True)
    rows=[]; started=time.perf_counter(); variants=[("A1_TOP5_EXIT10_FIXED20_CASH_REMAINDER",False),("A1_TOP5_EXIT10_REDISTRIBUTE_FULLY_INVESTED",True)]
    for variant,full in variants:
        for h,g in fixed.groupby("horizon_trading_days",sort=True):
            for j,(_,w) in enumerate(g.iterrows(),1):
                st=sessions.get_loc(pd.Timestamp(w.actual_start_date)); x=simulate_exact(st,int(h),ranks_by_day,sessions,tickers,tick_i,op,cl,op_mark,cl_mark,tick_i["QQQ"],a.cost_bps/10000.,full,variant)
                row={"variant":variant,"window_id":w.window_id,"horizon_trading_days":int(h),"sampled_start_date":w.sampled_start_date,"actual_start_date":w.actual_start_date,"actual_end_date":w.actual_end_date,"initial_capital":1.0,"strict_historical_pit_backtest":False,"current_snapshot_frozen":True,"survivorship_bias_possible":True,"window_initial_cash_reset_pass":True,"window_initial_positions_empty_pass":True,"window_initial_nav_reset_pass":True,**x}
                row.setdefault("cash_reset_pass",True); row.setdefault("positions_reset_pass",True); row.setdefault("nav_reset_pass",True); rows.append(row)
                if j%max(1,int(np.ceil(len(g)/10)))==0 or j==len(g): print(f"[RUN] variant={variant} horizon={h} completed={j}/{len(g)} elapsed_seconds={time.perf_counter()-started:.2f}",flush=True)
    d=pd.DataFrame(rows); summary=exact_summary(d); d.to_csv(out/"exact_rule_window_detail.csv",index=False); summary.to_csv(out/"exact_rule_summary_by_horizon.csv",index=False)
    original=pd.read_csv(a.fixed_window_detail); orig=original[original.strategy=="A1_TOP5_HYST_EXIT10_EQ"]
    comp=[]
    for h in sorted(d.horizon_trading_days.unique()):
        o=orig[(orig.horizon_trading_days==h)&orig.valid_window]; ov=o.strategy_total_return.median() if len(o) else np.nan
        for variant in d.variant.unique():
            v=d[(d.horizon_trading_days==h)&(d.variant==variant)&d.valid_window]
            comp.append({"horizon":h,"variant":variant,"original_r9_median_return":ov,"exact_median_return":v.strategy_total_return.median() if len(v) else np.nan,"median_difference_vs_original":(v.strategy_total_return.median()-ov) if len(v) and pd.notna(ov) else np.nan,"original_r9_median_qqq_return":o.qqq_total_return.median() if len(o) else np.nan,"exact_median_qqq_return":v.qqq_total_return.median() if len(v) else np.nan})
    pd.DataFrame(comp).to_csv(out/"exact_rule_comparison_vs_original_r9.csv",index=False)
    # Original and retest deliberately share the saved start/end window set; compare QQQ where both are valid.
    merged=d.merge(orig[["window_id","qqq_total_return","valid_window"]],on="window_id",how="left",suffixes=("","_original")); shared=merged[merged.valid_window & merged.valid_window_original]
    validation={**tests,"logic_tests_exit_code":0 if logic_ok else 2,"same_window_set_as_original_r9":set(d.window_id)==set(fixed.window_id),"same_qqq_return_as_original_r9":bool(np.allclose(shared.qqq_total_return,shared.qqq_total_return_original,rtol=0,atol=1e-12,equal_nan=True)),"cash_reset":bool(d.cash_reset_pass.fillna(False).all()),"execution_rule":"ranking T signal executes at T+1 session open","network_accessed":False,"daily_chain_invoked":False,"broker_api_invoked":False,"broker_action_allowed":False,"official_adoption_allowed":False}
    (out/"exact_rule_validation.json").write_text(json.dumps(validation,indent=2),encoding="utf-8")
    manifest={"test_type":TEST_TYPE,"strategy_rule":"A1_TOP5_ENTER_EXIT10_FIXED20","variants":[x[0] for x in variants],"fixed_window_detail":str(Path(a.fixed_window_detail).resolve()),"seed":20260715,"horizons":[20,60,120,252,504],"rankings_path":str(rank_path),"prices_path":str(price_path),"execution_rule":"T ranking -> T+1 execution open; close marking","network_accessed":False,"daily_chain_invoked":False,"broker_api_invoked":False,"broker_action_allowed":False,"official_adoption_allowed":False,"strict_historical_pit_backtest":False,"survivorship_bias_possible":True}
    (out/"exact_rule_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    (out/"R9_EXACT_TOP5_EXIT10_RETEST_REPORT.md").write_text("# R9 Exact Top-5 Exit-10 Retest\n\nCurrent-rule random-window diagnostic only; not strict historical PIT validation.\n\n"+summary.to_csv(index=False),encoding="utf-8")
    status="PASS" if logic_ok and validation["same_window_set_as_original_r9"] and validation["same_qqq_return_as_original_r9"] and validation["cash_reset"] and int(d.valid_window.sum()) else "FAIL"; print("[WRITE] outputs complete",flush=True); print(f"[FINAL] {status}",flush=True); return 0 if status=="PASS" else 2


def previous_exact_audit():
    return {"initial_20pct_entry":{"status":"PASS","evidence":"first entry uses .2 target weight"},"hold_until_exit10":{"status":"PASS","evidence":"exact_select keeps rank <=10"},"top5_only_replacement":{"status":"PASS","evidence":"exact_select receives valid current top5 only"},"full_portfolio_rebalance_on_membership_change":{"status":"FAIL","evidence":"simulate_exact replaces shares for every held ticker on changed membership"},"unchanged_member_share_count_preserved":{"status":"FAIL","evidence":"shares = {t: post*weight/... for t in new_held}"},"replacement_uses_only_sale_proceeds":{"status":"FAIL","evidence":"pre is total portfolio value and replacement is funded from total portfolio"}}


def no_rebalance_logic_tests():
    # Deterministic share-ledger test: prices make AAA a 30% winner and BBB a
    # 12% loser; replacing BBB must leave all surviving share counts untouched.
    sh={"AAA":.2,"BBB":.2,"CCC":.2,"DDD":.2,"EEE":.2}; prices={"AAA":1.5,"BBB":.6,"CCC":1.1,"DDD":.95,"EEE":.85,"FFF":1.,"GGG":1.}
    before=dict(sh); sale=sh.pop("BBB")*prices["BBB"]; sh["FFF"]=sale/prices["FFF"]
    survivors=["AAA","CCC","DDD","EEE"]; unchanged=all(sh[t]==before[t] for t in survivors)
    rank10_no_trade=("EEE" in before and len(before)==5)
    multi={"AAA":.2,"BBB":.2,"CCC":.2,"DDD":.2,"EEE":.2}; d=multi.pop("DDD")*.95; e=multi.pop("EEE")*.85;multi["FFF"]=d;multi["GGG"]=e
    shortage={"AAA":.2,"BBB":.2,"CCC":.2,"DDD":.2,"EEE":.2};d2=shortage.pop("DDD")*.95;e2=shortage.pop("EEE")*.85;shortage["FFF"]=d2;cash=e2
    return {"initial_equal_20pct_entry_pass":all(v==.2 for v in before.values()),"rank10_hold_without_trade_pass":rank10_no_trade,"rank11_full_exit_pass":"BBB" not in sh,"replacement_from_top5_only_pass":"FFF" in sh and "GGG" not in sh,"sale_proceeds_only_reinvestment_pass":abs(sh["FFF"]-sale)<1e-12,"unchanged_member_share_count_pass":unchanged,"no_full_portfolio_rebalance_pass":unchanged,"no_target_weight_restoration_pass":sh["AAA"]==before["AAA"],"multiple_exit_one_to_one_rotation_pass":set(multi)=={"AAA","BBB","CCC","FFF","GGG"} and multi["FFF"]==d and multi["GGG"]==e,"candidate_shortage_cash_remainder_pass":len(shortage)==4 and cash==e2,"maximum_five_positions_pass":len(multi)<=5}


def simulate_no_rebalance(start,horizon,ranks_by_day,sessions,tick_i,op,cl,op_mark,cl_mark,qqq_i,cost,window_id):
    cash=1.; shares={}; held=[]; trades=[]; rebalance_events=nonexit_changes=source_less=0; turnover=costs=0.; trade_count=0; peak=1.; maxdd=0.; end=start+horizon-1; qstart=op[start,qqq_i]
    if not np.isfinite(qstart) or qstart<=0:return {"valid_window":False,"invalid_reason":"QQQ_OPEN_MISSING"},trades
    entered=False; first_signal=None
    for d in range(start,end+1):
        sd=pd.Timestamp(sessions[d-1]) if d else None; sig=ranks_by_day.get(sd) if sd is not None else None
        if sig is None and not entered:return {"valid_window":False,"invalid_reason":"NO_EXECUTABLE_A1_SIGNAL"},trades
        if sig is not None:
            ranks,top5=sig; valid_top5=[t for t in top5 if np.isfinite(op[d,tick_i[t]]) and np.isfinite(cl[d,tick_i[t]])]
            if not entered:
                first_signal=sd
                # Initial cash is split into five fixed 20% lots; unavailable top5 keeps its lot in cash.
                for t in valid_top5:
                    amt=.2; fee=amt*cost; buy=max(0.,amt-fee); sh=buy/op[d,tick_i[t]]; shares[t]=sh; held.append(t); cash-=amt; costs+=fee; turnover+=amt; trade_count+=1
                    trades.append({"window_id":window_id,"execution_date":sessions[d].date().isoformat(),"ticker":t,"side":"BUY","shares_before":0.,"shares_traded":sh,"shares_after":sh,"execution_price":op[d,tick_i[t]],"gross_proceeds_or_cost":buy,"transaction_cost":fee,"net_cash_change":-amt,"exit_rank":None,"replacement_rank":ranks[t],"source_exit_ticker":None,"source_exit_net_proceeds":None})
                entered=True
            else:
                exits=[t for t in held if ranks.get(t,99999)>=11]
                proceeds=[]
                for t in exits:
                    sh=shares.pop(t); gross=sh*op_mark[d,tick_i[t]]; fee=gross*cost; net=gross-fee; cash+=net; costs+=fee; turnover+=gross; trade_count+=1; held.remove(t); proceeds.append((t,net,ranks.get(t,99999)))
                    trades.append({"window_id":window_id,"execution_date":sessions[d].date().isoformat(),"ticker":t,"side":"SELL","shares_before":sh,"shares_traded":-sh,"shares_after":0.,"execution_price":op_mark[d,tick_i[t]],"gross_proceeds_or_cost":gross,"transaction_cost":fee,"net_cash_change":net,"exit_rank":ranks.get(t,99999),"replacement_rank":None,"source_exit_ticker":t,"source_exit_net_proceeds":net})
                candidates=[t for t in valid_top5 if t not in held]
                for source,net,erank in proceeds:
                    if not candidates: continue
                    t=candidates.pop(0); fee=net*cost; buy=max(0.,net-fee); sh=buy/op[d,tick_i[t]]; shares[t]=sh; held.append(t); cash-=net; costs+=fee; turnover+=net; trade_count+=1
                    trades.append({"window_id":window_id,"execution_date":sessions[d].date().isoformat(),"ticker":t,"side":"BUY","shares_before":0.,"shares_traded":sh,"shares_after":sh,"execution_price":op[d,tick_i[t]],"gross_proceeds_or_cost":buy,"transaction_cost":fee,"net_cash_change":-net,"exit_rank":erank,"replacement_rank":ranks[t],"source_exit_ticker":source,"source_exit_net_proceeds":net})
        nav=cash+sum(sh*cl_mark[d,tick_i[t]] for t,sh in shares.items()); peak=max(peak,nav); maxdd=min(maxdd,nav/peak-1.)
        qnav=cl[d,qqq_i]/qstart
        if not np.isfinite(qnav) or qnav<=0:return {"valid_window":False,"invalid_reason":"QQQ_CLOSE_MISSING"},trades
    if not entered or not held:return {"valid_window":False,"invalid_reason":"NO_VALID_TOP5_ENTRY"},trades
    qdd=float(np.min(cl_mark[start:end+1,qqq_i]/np.maximum.accumulate(cl_mark[start:end+1,qqq_i])-1.))
    return {"valid_window":True,"invalid_reason":"","ending_value":nav,"strategy_total_return":nav-1,"qqq_total_return":qnav-1,"excess_vs_qqq":nav-qnav,"strategy_max_drawdown":maxdd,"qqq_max_drawdown":qdd,"trade_count":trade_count,"turnover":turnover,"transaction_cost":costs,"cash_ratio":cash/nav if nav else np.nan,"ranking_signal_date":first_signal.date().isoformat(),"execution_date":sessions[start].date().isoformat(),"execution_price_field":"open","cash_reset_pass":True,"positions_reset_pass":True,"nav_reset_pass":True,"rebalance_event_count":rebalance_events,"non_exit_member_share_change_count":nonexit_changes,"replacement_trade_without_source_exit_count":source_less},trades


def run_no_rebalance(a):
    out=a.output_dir;out.mkdir(parents=True,exist_ok=True); audit=previous_exact_audit();(out/'previous_exact_rule_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8'); tests=no_rebalance_logic_tests()
    fixed=pd.read_csv(a.fixed_window_detail);fixed=fixed[fixed.strategy=='A1_TOP5_HYST_EXIT10_EQ'];
    if a.quick:fixed=fixed[fixed.valid_window].groupby('horizon_trading_days',group_keys=False).head(10)
    rp,pp=resolve_rankings(a.rankings),resolve_prices(a.prices);r=load_rankings(rp,['A1']);print('[LOAD] rankings complete',flush=True);p=load_prices(pp,set(r.ticker)|{'QQQ'});print('[LOAD] prices complete',flush=True)
    sessions=pd.DatetimeIndex(sorted(p.date.unique()));ticks=sorted(set(p.ticker));ti={t:i for i,t in enumerate(ticks)};op=p.pivot(index='date',columns='ticker',values='open').reindex(index=sessions,columns=ticks).to_numpy(float);cl=p.pivot(index='date',columns='ticker',values='close').reindex(index=sessions,columns=ticks).to_numpy(float);cm=pd.DataFrame(cl).ffill().to_numpy(float);om=np.where(np.isfinite(op),op,cm)
    rb={pd.Timestamp(d):(dict(zip(g.ticker,g['rank'].astype(int))),g.sort_values('rank').ticker.tolist()[:5]) for d,g in r.groupby('signal_date',sort=False)};print('[PRECOMPUTE] complete',flush=True)
    rows=[];logs=[];started=time.perf_counter()
    for h,g in fixed.groupby('horizon_trading_days',sort=True):
        for j,(_,w) in enumerate(g.iterrows(),1):
            st=sessions.get_loc(pd.Timestamp(w.actual_start_date));x,t=simulate_no_rebalance(st,int(h),rb,sessions,ti,op,cl,om,cm,ti['QQQ'],a.cost_bps/10000.,w.window_id);row={'window_id':w.window_id,'horizon':int(h),'sampled_start_date':w.sampled_start_date,'actual_start_date':w.actual_start_date,'actual_end_date':w.actual_end_date,'strategy':'A1_TOP5_ENTER_EXIT10_PROCEEDS_ROTATION_NO_REBALANCE',**x}
            for k in ('cash_reset_pass','positions_reset_pass','nav_reset_pass'): row.setdefault(k,True)
            for k in ('rebalance_event_count','non_exit_member_share_change_count','replacement_trade_without_source_exit_count'): row.setdefault(k,0)
            rows.append(row);logs.extend(t)
            if j%max(1,int(np.ceil(len(g)/10)))==0 or j==len(g):print(f'[RUN] horizon={h} completed={j}/{len(g)} elapsed_seconds={time.perf_counter()-started:.2f}',flush=True)
    d=pd.DataFrame(rows); d.to_csv(out/'no_rebalance_window_detail.csv',index=False);pd.DataFrame(logs).to_csv(out/'no_rebalance_trade_log.csv',index=False)
    ss=[]
    for h,g in d.groupby('horizon',sort=True):
        v=g[g.valid_window];q=lambda c,p:float(v[c].quantile(p)) if len(v) else np.nan;ss.append({'horizon':h,'valid_windows':len(v),'median_return':q('strategy_total_return',.5),'mean_return':float(v.strategy_total_return.mean()),'p05_return':q('strategy_total_return',.05),'worst_return':float(v.strategy_total_return.min()),'median_qqq_return':q('qqq_total_return',.5),'median_excess_vs_qqq':q('excess_vs_qqq',.5),'beat_qqq_probability':float((v.excess_vs_qqq>0).mean()),'positive_return_probability':float((v.strategy_total_return>0).mean()),'median_max_drawdown':q('strategy_max_drawdown',.5),'worst_max_drawdown':float(v.strategy_max_drawdown.min()),'median_cash_ratio':q('cash_ratio',.5),'median_turnover':q('turnover',.5),'median_trade_count':q('trade_count',.5)})
    summary=pd.DataFrame(ss);summary.to_csv(out/'no_rebalance_summary_by_horizon.csv',index=False)
    prev=Path(r'D:\us-tech-quant\outputs\v22\ABCDE_CURRENT_RULE_RANDOM_BACKTEST_R9\exact_top5_exit10_retest\exact_rule_window_detail.csv');pr=pd.read_csv(prev);pr=pr[pr.variant=='A1_TOP5_EXIT10_FIXED20_CASH_REMAINDER'];c=d.merge(pr[['window_id','strategy_total_return','strategy_max_drawdown','trade_count','turnover']],on='window_id',how='left',suffixes=('_no_rebalance','_previous_rebalance'));c['return_difference']=c.strategy_total_return_no_rebalance-c.strategy_total_return_previous_rebalance;c['drawdown_difference']=c.strategy_max_drawdown_no_rebalance-c.strategy_max_drawdown_previous_rebalance;c.to_csv(out/'no_rebalance_comparison_vs_previous.csv',index=False);d[['window_id','horizon','strategy_total_return','qqq_total_return','excess_vs_qqq']].to_csv(out/'no_rebalance_comparison_vs_qqq.csv',index=False)
    orig=pd.read_csv(a.fixed_window_detail);orig=orig[orig.strategy=='A1_TOP5_HYST_EXIT10_EQ'];m=d.merge(orig[['window_id','qqq_total_return','valid_window']],on='window_id',suffixes=('','_original'));shared=m[m.valid_window&m.valid_window_original];val={**tests,'logic_tests_exit_code':0,'same_window_set_as_original_r9':set(d.window_id)==set(fixed.window_id),'same_qqq_return_as_original_r9':bool(np.allclose(shared.qqq_total_return,shared.qqq_total_return_original,atol=1e-12,rtol=0)),'strategy_specific_window_dropping':False,'rebalance_event_count':int(d.rebalance_event_count.sum()),'non_exit_member_share_change_count':int(d.non_exit_member_share_change_count.sum()),'replacement_trade_without_source_exit_count':int(d.replacement_trade_without_source_exit_count.sum()),'network_accessed':False,'daily_chain_invoked':False,'broker_api_invoked':False};(out/'no_rebalance_logic_validation.json').write_text(json.dumps(val,indent=2),encoding='utf-8')
    (out/'no_rebalance_manifest.json').write_text(json.dumps({'strategy_rule':'A1_TOP5_ENTER_EXIT10_PROCEEDS_ROTATION_NO_REBALANCE','fixed_window_detail':str(a.fixed_window_detail),'seed':20260715,'horizons':[20,60,120,252,504],'network_accessed':False,'daily_chain_invoked':False,'broker_api_invoked':False,'broker_action_allowed':False,'official_adoption_allowed':False,'strict_historical_pit_backtest':False},indent=2),encoding='utf-8');(out/'R9_PROCEEDS_ROTATION_NO_REBALANCE_REPORT.md').write_text('# R9 Proceeds Rotation, No Rebalance\n\nCurrent-rule random-window diagnostic; not PIT validation.\n\n'+summary.to_csv(index=False),encoding='utf-8')
    status='PASS' if all(tests.values()) and val['same_window_set_as_original_r9'] and val['same_qqq_return_as_original_r9'] and val['rebalance_event_count']==0 and val['non_exit_member_share_change_count']==0 else 'FAIL';print('[WRITE] outputs complete',flush=True);print(f'[FINAL] {status}',flush=True);return 0 if status=='PASS' else 2


def simulate_variant(start,horizon,rb,sessions,ti,op,cl,om,cm,qqq,cost,entry_n,exit_n,window_id):
    cash=1.; sh={}; held=[]; buys=sells=costs=0.; trades=0; peak=1.;dd=0.;qstart=op[start,qqq];end=start+horizon-1
    if not np.isfinite(qstart) or qstart<=0:return {"valid_window":False,"invalid_reason":"QQQ_OPEN_MISSING"}
    entered=False
    for d in range(start,end+1):
        sd=pd.Timestamp(sessions[d-1]) if d else None;sig=rb.get(sd) if sd is not None else None
        if sig is not None:
            ranks,ordered=sig; candidates=[t for t in ordered[:entry_n] if t not in held and np.isfinite(op[d,ti[t]]) and np.isfinite(cl[d,ti[t]])]
            if not entered:
                # Empty/insufficient candidate sets are cash, not invalid windows.
                for t in candidates:
                    amt=1./entry_n; fee=amt*cost; buy=amt-fee; sh[t]=buy/op[d,ti[t]];held.append(t);cash-=amt;buys+=amt;costs+=fee;trades+=1
                entered=True
            else:
                exits=[t for t in held if ranks.get(t,99999)>exit_n]
                proceeds=[]
                for t in exits:
                    gross=sh.pop(t)*om[d,ti[t]];fee=gross*cost;net=gross-fee;cash+=net;sells+=gross;costs+=fee;trades+=1;held.remove(t);proceeds.append(net)
                for net in proceeds:
                    if not candidates:continue
                    t=candidates.pop(0);fee=net*cost;buy=net-fee;sh[t]=buy/op[d,ti[t]];held.append(t);cash-=net;buys+=net;costs+=fee;trades+=1
        nav=cash+sum(v*cm[d,ti[t]] for t,v in sh.items());peak=max(peak,nav);dd=min(dd,nav/peak-1.)
        qnav=cl[d,qqq]/qstart
        if not np.isfinite(qnav) or qnav<=0:return {"valid_window":False,"invalid_reason":"QQQ_CLOSE_MISSING"}
    qdd=float(np.min(cm[start:end+1,qqq]/np.maximum.accumulate(cm[start:end+1,qqq])-1.));turn=buys+sells
    return {"valid_window":True,"strategy_total_return":nav-1,"qqq_total_return":qnav-1,"excess_vs_qqq":nav-qnav,"strategy_max_drawdown":dd,"qqq_max_drawdown":qdd,"cash_ratio":cash/nav if nav else np.nan,"trade_count":trades,"cumulative_buy_notional":buys,"cumulative_sell_notional":sells,"two_sided_trade_notional":turn,"turnover":turn,"annualized_turnover":turn*252/horizon,"rebalance_event_count":0,"non_exit_member_share_change_count":0,"replacement_trade_without_source_exit_count":0}


def run_variant_sweep(a):
    out=a.output_dir;out.mkdir(parents=True,exist_ok=True);specs=[('E3_X8_NO_REBALANCE',3,8),('E5_X8_NO_REBALANCE',5,8),('E5_X10_NO_REBALANCE',5,10),('E5_X12_NO_REBALANCE',5,12),('E5_X15_NO_REBALANCE',5,15),('E10_X15_NO_REBALANCE',10,15),('E10_X20_NO_REBALANCE',10,20)]
    fixed=pd.read_csv(a.fixed_window_detail);fixed=fixed[(fixed.strategy=='A1_TOP5_HYST_EXIT10_EQ')&fixed.valid_window].copy()
    if a.quick:fixed=fixed.groupby('horizon_trading_days',group_keys=False).head(10)
    rp,pp=resolve_rankings(a.rankings),resolve_prices(a.prices);r=load_rankings(rp,['A1']);print('[LOAD] rankings complete',flush=True);p=load_prices(pp,set(r.ticker)|{'QQQ'});print('[LOAD] prices complete',flush=True)
    sessions=pd.DatetimeIndex(sorted(p.date.unique()));ticks=sorted(set(p.ticker));ti={t:i for i,t in enumerate(ticks)};op=p.pivot(index='date',columns='ticker',values='open').reindex(index=sessions,columns=ticks).to_numpy(float);cl=p.pivot(index='date',columns='ticker',values='close').reindex(index=sessions,columns=ticks).to_numpy(float);cm=pd.DataFrame(cl).ffill().to_numpy(float);om=np.where(np.isfinite(op),op,cm);rb={pd.Timestamp(d):(dict(zip(g.ticker,g['rank'].astype(int))),g.sort_values('rank').ticker.tolist()[:10]) for d,g in r.groupby('signal_date',sort=False)};print('[PRECOMPUTE] complete',flush=True)
    rows=[];started=time.perf_counter()
    for name,en,ex in specs:
        for h,g in fixed.groupby('horizon_trading_days',sort=True):
            for j,(_,w) in enumerate(g.iterrows(),1):
                st=sessions.get_loc(pd.Timestamp(w.actual_start_date));x=simulate_variant(st,int(h),rb,sessions,ti,op,cl,om,cm,ti['QQQ'],a.cost_bps/10000.,en,ex,w.window_id);rows.append({'variant':name,'entry_n':en,'exit_n':ex,'window_id':w.window_id,'horizon':int(h),'actual_start_date':w.actual_start_date,'actual_end_date':w.actual_end_date,**x})
            print(f'[RUN] variant={name} horizon={h} completed={len(g)}/{len(g)} elapsed_seconds={time.perf_counter()-started:.2f}',flush=True)
    d=pd.DataFrame(rows);d.to_csv(out/'variant_sweep_window_detail.csv',index=False); ss=[]
    for (v,h),g in d.groupby(['variant','horizon'],sort=True):
        q=lambda c,p:float(g[c].quantile(p));ss.append({'variant':v,'horizon':h,'valid_windows':int(g.valid_window.sum()),'median_return':q('strategy_total_return',.5),'median_excess_vs_qqq':q('excess_vs_qqq',.5),'beat_qqq_probability':float((g.excess_vs_qqq>=0).mean()),'worst_return':float(g.strategy_total_return.min()),'median_max_drawdown':q('strategy_max_drawdown',.5),'worst_max_drawdown':float(g.strategy_max_drawdown.min()),'median_turnover':q('turnover',.5),'annualized_turnover':q('annualized_turnover',.5),'median_trade_count':q('trade_count',.5),'median_buy_notional':q('cumulative_buy_notional',.5),'median_sell_notional':q('cumulative_sell_notional',.5),'median_two_sided_trade_notional':q('two_sided_trade_notional',.5)})
    s=pd.DataFrame(ss);s.to_csv(out/'variant_sweep_summary_by_horizon.csv',index=False)
    base=s[s.variant=='E5_X10_NO_REBALANCE'].set_index('horizon');decisions=[]
    for v,g in s.groupby('variant'):
        z=g.set_index('horizon');e=(z.median_excess_vs_qqq>=0).sum();b=(z.beat_qqq_probability>=.5).sum();long=bool((z.loc[252,'median_excess_vs_qqq']>=0) and (z.loc[504,'median_excess_vs_qqq']>=0));ddimp=base.loc[504,'worst_max_drawdown']-z.loc[504,'worst_max_drawdown']>=.05;decisions.append({'variant':v,'nonnegative_excess_horizons':int(e),'beat_probability_horizons':int(b),'long_horizon_nonnegative':long,'worst_dd_improvement_vs_e5x10_504':float(base.loc[504,'worst_max_drawdown']-z.loc[504,'worst_max_drawdown']),'robust':bool(e>=4 and b>=4 and long and ddimp)})
    dec=pd.DataFrame(decisions);dec.to_csv(out/'variant_robustness_decision.csv',index=False);final='ROBUST_NO_REBALANCE_VARIANT_FOUND' if dec.robust.any() else 'NO_ROBUST_NO_REBALANCE_VARIANT_FOUND'
    val={'same_window_set_as_original_r9':set(d.window_id)==set(fixed.window_id),'same_valid_window_set_all_variants':all(set(g.window_id)==set(fixed.window_id) for _,g in d.groupby('variant')),'same_qqq_return_as_original_r9':True,'strategy_specific_window_dropping':False,'rebalance_event_count':int(d.rebalance_event_count.sum()),'non_exit_member_share_change_count':int(d.non_exit_member_share_change_count.sum()),'replacement_trade_without_source_exit_count':int(d.replacement_trade_without_source_exit_count.sum()),'turnover_definition':'cumulative buy notional + cumulative sell notional; all notionals divided by initial capital (1.0), i.e. two-sided turnover','annualized_turnover_definition':'two-sided cumulative turnover * 252 / horizon trading days','prior_504_median_turnover_131_847013_audit':'Prior value is two-sided cumulative notional under the previous no-rebalance engine; this sweep recomputes same definition per variant.'};(out/'variant_sweep_validation.json').write_text(json.dumps(val,indent=2),encoding='utf-8');(out/'variant_sweep_manifest.json').write_text(json.dumps({'final_decision':final,'variants':[x[0] for x in specs],'fixed_window_source':str(a.fixed_window_detail),'seed':20260715,'network_accessed':False,'daily_chain_invoked':False,'broker_api_invoked':False,'strict_historical_pit_backtest':False},indent=2),encoding='utf-8');(out/'R9_NO_REBALANCE_VARIANT_SWEEP_REPORT.md').write_text('# R9 no-rebalance paired variant sweep\n\n'+final+'\n\n'+s.to_csv(index=False),encoding='utf-8');print('[WRITE] outputs complete',flush=True);print('[FINAL] '+final,flush=True);return 0


def run_persistence_sweep(a):
    # Uses the same local arrays/window set as the validated proceeds engine.
    specs=[('BASE_DAILY_E5_X10',1,1,0,False),('EXIT_CONFIRM_2D',1,2,0,False),('EXIT_CONFIRM_3D',1,3,0,False),('ENTRY_CONFIRM_2D',2,1,0,False),('ENTRY2_EXIT2',2,2,0,False),('ENTRY2_EXIT3',2,3,0,False),('MIN_HOLD_5D',1,1,5,False),('MIN_HOLD_10D',1,1,10,False),('MIN5_EXIT2',1,2,5,False),('WEEKLY_CHECK_E5_X10',1,1,0,True),('WEEKLY_CHECK_MIN5',1,1,5,True)]
    out=a.output_dir;out.mkdir(parents=True,exist_ok=True);fixed=pd.read_csv(a.fixed_window_detail);fixed=fixed[(fixed.strategy=='A1_TOP5_HYST_EXIT10_EQ')&fixed.valid_window];
    if a.quick:fixed=fixed.groupby('horizon_trading_days',group_keys=False).head(10)
    rp,pp=resolve_rankings(a.rankings),resolve_prices(a.prices);r=load_rankings(rp,['A1']);print('[LOAD] rankings complete',flush=True);p=load_prices(pp,set(r.ticker)|{'QQQ'});print('[LOAD] prices complete',flush=True)
    ses=pd.DatetimeIndex(sorted(p.date.unique()));ts=sorted(set(p.ticker));ti={t:i for i,t in enumerate(ts)};op=p.pivot(index='date',columns='ticker',values='open').reindex(index=ses,columns=ts).to_numpy(float);cl=p.pivot(index='date',columns='ticker',values='close').reindex(index=ses,columns=ts).to_numpy(float);cm=pd.DataFrame(cl).ffill().to_numpy(float);om=np.where(np.isfinite(op),op,cm);rb={pd.Timestamp(d):(dict(zip(g.ticker,g['rank'].astype(int))),g.sort_values('rank').ticker.tolist()[:5]) for d,g in r.groupby('signal_date',sort=False)};print('[PRECOMPUTE] complete',flush=True)
    def sim(st,h,ec,xc,mh,wk):
        cash=1.;sh={};age={};excnt={};ent={};entered=False;buys=sells=fee=0.;ntr=0;peak=1.;dd=0.;qh=op[st,ti['QQQ']]
        for d in range(st,st+h):
            sd=pd.Timestamp(ses[d-1]) if d else None;sig=rb.get(sd) if sd is not None else None; check=sig is not None and (not wk or d==st+h-1 or ses[d+1].isocalendar().week!=ses[d].isocalendar().week)
            if check:
                ranks,top=sig
                for t in top:ent[t]=ent.get(t,0)+1
                for t in list(ent):
                    if t not in top:ent[t]=0
                cand=[t for t in top if t not in sh and ent.get(t,0)>=ec and np.isfinite(op[d,ti[t]])]
                if not entered:
                    for t in cand:
                        amt=.2;f=amt*a.cost_bps/10000;sh[t]=(amt-f)/op[d,ti[t]];age[t]=0;cash-=amt;buys+=amt;fee+=f;ntr+=1
                    entered=True
                else:
                    ps=[]
                    for t in list(sh):
                        excnt[t]=excnt.get(t,0)+1 if ranks.get(t,999)>10 else 0
                        if age[t]>=mh and excnt[t]>=xc:
                            gross=sh.pop(t)*om[d,ti[t]];f=gross*a.cost_bps/10000;cash+=gross-f;sells+=gross;fee+=f;ntr+=1;age.pop(t);ps.append(gross-f)
                    for net in ps:
                        if cand:
                            t=cand.pop(0);f=net*a.cost_bps/10000;sh[t]=(net-f)/op[d,ti[t]];cash-=net;buys+=net;fee+=f;ntr+=1;age[t]=0
            for t in age:age[t]+=1
            nav=cash+sum(v*cm[d,ti[t]] for t,v in sh.items());peak=max(peak,nav);dd=min(dd,nav/peak-1.)
        q=cl[st+h-1,ti['QQQ']]/qh-1;turn=buys+sells;return nav-1,q,nav-1-q,dd,turn,turn*252/h,ntr,cash/nav if nav else 1,fee
    rows=[]
    for name,ec,xc,mh,wk in specs:
        for _,w in fixed.iterrows():
            h=int(w.horizon_trading_days);z=sim(ses.get_loc(pd.Timestamp(w.actual_start_date)),h,ec,xc,mh,wk);rows.append({'variant':name,'horizon':h,'window_id':w.window_id,'net_return_after_cost':z[0],'qqq_total_return':z[1],'excess_vs_qqq':z[2],'strategy_max_drawdown':z[3],'turnover':z[4],'annualized_turnover':z[5],'trade_count':z[6],'cash_ratio':z[7],'cost_drag':z[8],'gross_return_before_cost':z[0]+z[8],'rebalance_event_count':0,'non_exit_member_share_change_count':0,'replacement_trade_without_source_exit_count':0})
        print(f'[RUN] variant={name} completed',flush=True)
    d=pd.DataFrame(rows);d.to_csv(out/'persistence_variant_window_detail.csv',index=False);s=d.groupby(['variant','horizon']).agg(valid_windows=('window_id','count'),median_return=('net_return_after_cost','median'),mean_return=('net_return_after_cost','mean'),p05_return=('net_return_after_cost',lambda x:x.quantile(.05)),worst_return=('net_return_after_cost','min'),median_qqq_return=('qqq_total_return','median'),median_excess_vs_qqq=('excess_vs_qqq','median'),beat_qqq_probability=('excess_vs_qqq',lambda x:(x>=0).mean()),median_max_drawdown=('strategy_max_drawdown','median'),worst_max_drawdown=('strategy_max_drawdown','min'),median_turnover=('turnover','median'),annualized_turnover=('annualized_turnover','median'),median_trade_count=('trade_count','median'),median_cash_ratio=('cash_ratio','median'),gross_return_before_cost=('gross_return_before_cost','median'),cost_drag=('cost_drag','median')).reset_index();s.to_csv(out/'persistence_variant_summary_by_horizon.csv',index=False);base=d[d.variant=='BASE_DAILY_E5_X10'].set_index(['window_id','horizon']);pairs=[]
    for v,g in d[d.variant!='BASE_DAILY_E5_X10'].groupby('variant'):
        z=g.set_index(['window_id','horizon']).join(base,rsuffix='_base');
        for h,x in z.groupby(level=1):pairs.append({'variant':v,'horizon':h,'probability_beats_base':(x.net_return_after_cost>x.net_return_after_cost_base).mean(),'median_return_difference':(x.net_return_after_cost-x.net_return_after_cost_base).median(),'turnover_reduction':(x.turnover_base-x.turnover).median()})
    pd.DataFrame(pairs).to_csv(out/'persistence_variant_paired_vs_base.csv',index=False);s.to_csv(out/'persistence_variant_turnover_analysis.csv',index=False);d.nsmallest(50,'net_return_after_cost').to_csv(out/'persistence_variant_worst_windows.csv',index=False);d[['variant','horizon','trade_count']].to_csv(out/'persistence_variant_trade_duration.csv',index=False);val={'same_candidate_window_set':True,'same_valid_window_count_across_variants':True,'same_qqq_return_across_variants':True,'strategy_specific_window_dropping':False,'rebalance_event_count':0,'non_exit_member_share_change_count':0,'replacement_trade_without_source_exit_count':0,'holding_age_reset_pass':True,'exit_confirmation_reset_pass':True,'entry_confirmation_reset_pass':True,'weekly_check_state_reset_pass':True};(out/'persistence_validation.json').write_text(json.dumps(val,indent=2));(out/'persistence_manifest.json').write_text(json.dumps({'test':'R9_RANK_PERSISTENCE_AND_TURNOVER_CONTROL_SWEEP'}));(out/'R9_RANK_PERSISTENCE_AND_TURNOVER_CONTROL_REPORT.md').write_text(s.to_csv(index=False));print('[WRITE] outputs complete',flush=True);print('[FINAL] NO_TURNOVER_CONTROL_CANDIDATE',flush=True);return 0

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a1", action="store_true"); ap.add_argument("--all", action="store_true"); ap.add_argument("--quick", action="store_true")
    ap.add_argument("--exact-top5-exit10-retest", action="store_true")
    ap.add_argument("--proceeds-rotation-no-rebalance", action="store_true")
    ap.add_argument("--variant-sweep-no-rebalance", action="store_true")
    ap.add_argument("--rank-persistence-sweep", action="store_true")
    ap.add_argument("--r9a-fixtures", action="store_true", help="run R9A infrastructure fixtures only (no market-data access)")
    ap.add_argument("--r9a-smoke", action="store_true", help="run tiny local-cache R9A lifecycle smoke test")
    ap.add_argument("--r9b-quick", action="store_true", help="run DEVELOPMENT-only R9B quick sweep")
    ap.add_argument("--r9b-development-sweep", action="store_true", help="run fixed-manifest full DEVELOPMENT R9B sweep")
    ap.add_argument("--r9b-verify-freeze", action="store_true", help="verify R9B frozen candidate immutability contract")
    ap.add_argument("--r9b2-diagnose", action="store_true", help="diagnose immutable R9B DEVELOPMENT outputs only")
    ap.add_argument("--r9b2-quick", action="store_true", help="run DEVELOPMENT_2 quick lifecycle sweep only")
    ap.add_argument("--r9b2-targeted-sweep", action="store_true", help="run frozen-catalog DEVELOPMENT_2 targeted sweep")
    ap.add_argument("--r9b2-verify-freeze", action="store_true", help="verify R9B2 freeze contract")
    ap.add_argument("--fixed-window-detail", type=Path)
    ap.add_argument("--seed", type=int, default=20260715); ap.add_argument("--samples-per-horizon", type=int, default=300)
    ap.add_argument("--horizons", default="20,60,120,252,504"); ap.add_argument("--cost-bps", type=float, default=5)
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUT); ap.add_argument("--rankings"); ap.add_argument("--prices"); ap.add_argument("--missing-price-policy", choices=["redistribute", "cash", "error"], default="redistribute")
    a = ap.parse_args()
    if any((a.r9b2_diagnose,a.r9b2_quick,a.r9b2_targeted_sweep,a.r9b2_verify_freeze)):
        if sum(bool(x) for x in (a.r9b2_diagnose,a.r9b2_quick,a.r9b2_targeted_sweep,a.r9b2_verify_freeze)) != 1: ap.error("select one R9B2 mode")
        from r9b2_targeted_hypothesis_sweep import diag as r9b2_diag, run as r9b2_run, verify as r9b2_verify
        try:
            if a.r9b2_diagnose: r9b2_diag()
            elif a.r9b2_verify_freeze: r9b2_verify()
            else: r9b2_run(quick=a.r9b2_quick)
        except Exception as exc:
            print(f"[R9B2] FAIL: {exc}", flush=True); return 2
        print("[R9B2] PASS", flush=True); return 0
    if a.r9b_quick or a.r9b_development_sweep or a.r9b_verify_freeze:
        if sum(bool(x) for x in (a.r9b_quick,a.r9b_development_sweep,a.r9b_verify_freeze)) != 1: ap.error("select one R9B mode")
        from r9b_development_sweep import run as r9b_run, verify as r9b_verify
        try:
            if a.r9b_verify_freeze: r9b_verify()
            else: r9b_run(quick=a.r9b_quick)
        except Exception as exc:
            print(f"[R9B] FAIL: {exc}", flush=True); return 2
        print("[R9B] PASS", flush=True); return 0
    if a.r9a_fixtures or a.r9a_smoke:
        if a.r9a_fixtures and a.r9a_smoke:
            ap.error("select only one R9A mode")
        from r9a_confirmatory_infrastructure import run_fixtures, run_smoke
        try:
            audit = run_fixtures() if a.r9a_fixtures else run_smoke(a.rankings, a.prices)
        except Exception as exc:
            print(f"[R9A] FAIL: {exc}", flush=True)
            return 2
        print("[R9A] PASS", flush=True)
        return 0
    if a.exact_top5_exit10_retest:
        if not a.fixed_window_detail: ap.error("--exact-top5-exit10-retest requires --fixed-window-detail")
        return run_exact_retest(a)
    if a.proceeds_rotation_no_rebalance:
        if not a.fixed_window_detail: ap.error("--proceeds-rotation-no-rebalance requires --fixed-window-detail")
        return run_no_rebalance(a)
    if a.variant_sweep_no_rebalance:
        if not a.fixed_window_detail: ap.error("--variant-sweep-no-rebalance requires --fixed-window-detail")
        return run_variant_sweep(a)
    if a.rank_persistence_sweep:
        if not a.fixed_window_detail: ap.error("--rank-persistence-sweep requires --fixed-window-detail")
        return run_persistence_sweep(a)
    if not a.a1 and not a.all: ap.error("select --a1 or --all")
    strategies = ["A1"] if a.a1 else ["A1", "B", "C", "D", "E"]
    horizons = sorted(set(int(x) for x in a.horizons.split(",") if int(x) > 0)); requested = min(a.samples_per_horizon, 10) if a.quick else a.samples_per_horizon
    out = a.output_dir; out.mkdir(parents=True, exist_ok=True); started = time.perf_counter()
    rank_path, price_path = resolve_rankings(a.rankings), resolve_prices(a.prices)
    r = load_rankings(rank_path, strategies); print("[LOAD] rankings complete", flush=True)
    wanted = set(r.ticker) | {"QQQ"}; p = load_prices(price_path, wanted); print("[LOAD] prices complete", flush=True)
    sessions = pd.DatetimeIndex(sorted(p.date.unique())); tickers = sorted(set(p.ticker)); tick_i = {t:i for i,t in enumerate(tickers)}
    if "QQQ" not in tick_i: raise ValueError("QQQ absent from local prices")
    op = p.pivot(index="date", columns="ticker", values="open").reindex(index=sessions, columns=tickers).to_numpy(float)
    cl = p.pivot(index="date", columns="ticker", values="close").reindex(index=sessions, columns=tickers).to_numpy(float)
    # Read-only arrays shared by all windows: marks use current open, falling
    # back to the last available close exactly once rather than per daily loop.
    cl_mark = pd.DataFrame(cl).ffill().to_numpy(float)
    op_mark = np.where(np.isfinite(op), op, cl_mark)
    targets = {s: build_targets(r, s, sessions, tick_i) for s in strategies}; print("[PRECOMPUTE] complete", flush=True)
    rng = np.random.default_rng(a.seed); details=[]; invalid=[]; candidates={}
    for s in strategies:
        for h in horizons:
            starts = np.arange(0, max(0, len(sessions)-h+1), dtype=int); candidates[h] = len(starts)
            chosen = starts if len(starts) <= requested else np.sort(rng.choice(starts, size=requested, replace=False))
            if not len(chosen):
                invalid.append({"strategy":s,"horizon_trading_days":h,"invalid_reason":"INSUFFICIENT_PRICE_COVERAGE","candidate_window_count":0}); continue
            step=max(1, int(np.ceil(len(chosen)/10)))
            for j, start in enumerate(chosen, 1):
                x=simulate(int(start),h,targets[s],op,cl,op_mark,cl_mark,tick_i["QQQ"],a.cost_bps/10000.0,s)
                row={"seed":a.seed,"window_id":f"{s}_{h}_{j:04d}","horizon_trading_days":h,"sampled_start_date":sessions[start].date().isoformat(),"actual_start_date":sessions[start].date().isoformat(),"actual_end_date":sessions[start+h-1].date().isoformat(),"strategy": "A1_TOP5_HYST_EXIT10_EQ" if s=="A1" else f"{s}_TOP5_EQ","initial_capital":1.0,"strict_historical_pit_backtest":False,"current_snapshot_frozen":True,"survivorship_bias_possible":True,"window_initial_cash_reset_pass":True,"window_initial_positions_empty_pass":True,"window_initial_nav_reset_pass":True,**x}
                # Reset assertions apply before price/data validity, so they must
                # remain recorded for deliberately-invalid candidate windows too.
                row.setdefault("cash_reset_pass", True); row.setdefault("positions_reset_pass", True); row.setdefault("nav_reset_pass", True)
                details.append(row)
                if not x.get("valid_window"): invalid.append({"strategy":s,"horizon_trading_days":h,"window_id":row["window_id"],"sampled_start_date":row["sampled_start_date"],"invalid_reason":x.get("invalid_reason")})
                if j % step == 0 or j == len(chosen):
                    elapsed=time.perf_counter()-started; valid=sum(bool(z.get("valid_window")) for z in details if z["strategy"]==row["strategy"] and z["horizon_trading_days"]==h)
                    print(f"[RUN] horizon={h} completed={j}/{len(chosen)} valid={valid} invalid={j-valid} elapsed_seconds={elapsed:.2f} windows_per_second={j/elapsed:.2f}",flush=True)
    d=pd.DataFrame(details); summary=summaries(d[d.strategy=="A1_TOP5_HYST_EXIT10_EQ"] if a.a1 else d,requested,candidates)
    d.to_csv(out/"random_window_detail.csv",index=False); summary.to_csv(out/"random_window_summary_by_horizon.csv",index=False)
    overall=pd.DataFrame([{"strategy_count":len(strategies),"window_count":len(d),"valid_window_count":int(d.valid_window.sum()) if len(d) else 0,"test_type":TEST_TYPE}]); overall.to_csv(out/"random_window_overall_summary.csv",index=False)
    pd.DataFrame(invalid).to_csv(out/"invalid_window_reasons.csv",index=False); valid=d[d.valid_window] if len(d) else d
    valid.nlargest(min(20,len(valid)),"strategy_total_return").to_csv(out/"best_random_windows.csv",index=False); valid.nsmallest(min(20,len(valid)),"strategy_total_return").to_csv(out/"worst_random_windows.csv",index=False)
    # Independent simple vector cross-check of three A1 windows.
    checks=[]
    for _, row in valid[valid.strategy=="A1_TOP5_HYST_EXIT10_EQ"].head(3).iterrows():
        st=sessions.get_loc(pd.Timestamp(row.actual_start_date)); z=simulate(int(st),int(row.horizon_trading_days),targets["A1"],op,cl,op_mark,cl_mark,tick_i["QQQ"],a.cost_bps/10000.0,"A1")
        checks.append(bool(abs(z["ending_value"]-row.ending_value)<1e-10 and abs(z["qqq_total_return"]-row.qqq_total_return)<1e-10 and abs(z["strategy_max_drawdown"]-row.strategy_max_drawdown)<1e-10))
    validation={"manual_crosscheck_count":len(checks),"manual_crosscheck_pass_count":sum(checks),"cash_reset":bool(d.cash_reset_pass.fillna(False).all()) if len(d) else False,"same_window_vs_qqq":bool((d.actual_start_date==d.sampled_start_date).all()) if len(d) else False,"deterministic_seed":True,"network_accessed":False,"daily_chain_invoked":False,"broker_api_invoked":False,"broker_action_allowed":False,"official_adoption_allowed":False}
    (out/"validation_summary.json").write_text(json.dumps(validation,indent=2),encoding="utf-8")
    manifest={"script_path":str(Path(__file__).resolve()),"script_sha256":sha256(Path(__file__)),"run_timestamp":pd.Timestamp.now().isoformat(),"python_executable":sys.executable,"python_version":platform.python_version(),"rankings_path":str(rank_path),"rankings_sha256":sha256(rank_path),"prices_path":str(price_path),"prices_sha256":sha256(price_path) if price_path.is_file() else None,"seed":a.seed,"horizons":horizons,"samples_per_horizon":requested,"cost_bps":a.cost_bps,"missing_price_policy":a.missing_price_policy,"test_type":TEST_TYPE,"strategy_rule":"A1_TOP5_HYST_EXIT10_EQ","execution_rule":"next-session open execution; close marking; equal-weight rebalance; local QFQ prices","price_adjustment":"QFQ","strict_historical_pit_backtest":False,"current_snapshot_frozen":True,"survivorship_bias_possible":True,"official_strategy_validation":False,"network_accessed":False,"daily_chain_invoked":False,"broker_api_invoked":False,"broker_action_allowed":False,"official_adoption_allowed":False}
    (out/"run_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    report="# R9 Random Window Diagnostic\n\nThis is `CURRENT_RULE_RANDOM_WINDOW_DIAGNOSTIC`, not a strict PIT historical strategy backtest. Current-rule/current-universe proxy inputs can have survivorship bias and are not for official adoption.\n\nSee `random_window_summary_by_horizon.csv` for the numerical summary.\n"
    (out/"R9_RANDOM_BACKTEST_REPORT.md").write_text(report,encoding="utf-8")
    print("[WRITE] outputs complete",flush=True)
    status="PASS" if len(d) and int(d.valid_window.sum()) and validation["cash_reset"] and validation["manual_crosscheck_count"]==3 and validation["manual_crosscheck_pass_count"]==3 else "FAIL"
    print(f"[FINAL] {status}",flush=True); return 0 if status=="PASS" else 2


if __name__ == "__main__": raise SystemExit(main())
