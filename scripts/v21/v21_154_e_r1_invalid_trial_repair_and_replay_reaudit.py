from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT"
OUT = Path("outputs/v21/V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT")
V148 = Path("outputs/v21/V21.148_E_R1_A1_PIT_LITE_REPLAY_DIAGNOSTIC_ONLY")
V149 = Path("outputs/v21/V21.149_E_R1_DEFENSIVE_OVERLAY_AND_INVALID_TRIAL_AUDIT")
TRIALS = V148 / "V21.148_trial_level_replay_returns.csv"
INVALID_148 = V148 / "V21.148_invalid_trials.csv"
SUMMARY_148 = V148 / "V21.148_summary.json"
SUMMARY_149 = V149 / "V21.149_summary.json"
PRICE = Path("outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020/V21.140_extended_adjusted_close_panel_2020_plus.csv")
A1_RANK = Path("outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/A1_BASELINE_CONTROL_latest_ranking.csv")
E_R1_RANK = Path("outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv")

INVALID_REASONS = [
    "INVALID_INSUFFICIENT_VALID_HOLDINGS",
    "INVALID_MISSING_ENTRY_PRICE",
    "INVALID_MISSING_EXIT_PRICE",
    "INVALID_INSUFFICIENT_FORWARD_WINDOW",
    "INVALID_BENCHMARK_MISSING",
    "INVALID_DUPLICATE_TICKERS",
    "INVALID_EMPTY_RANKING",
    "INVALID_UNIVERSE_MISMATCH",
    "INVALID_UNKNOWN",
]


def norm(v) -> str:
    if pd.isna(v):
        return ""
    return str(v).strip().upper()


def first_col(df: pd.DataFrame, cols: list[str]) -> str | None:
    lower = {c.lower(): c for c in df.columns}
    for c in cols:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_ranking(path: Path, strategy: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    tcol = first_col(df, ["ticker_norm", "ticker", "symbol"])
    rcol = first_col(df, ["rank", "adjusted_rank"])
    scol = first_col(df, ["E_final_score", "final_score", "score"])
    df["ticker_norm"] = df[tcol].map(norm)
    df["rank"] = pd.to_numeric(df[rcol], errors="coerce") if rcol else np.arange(1, len(df) + 1)
    df["score"] = pd.to_numeric(df[scol], errors="coerce") if scol else np.nan
    df["strategy_name"] = strategy
    return df[df["ticker_norm"].ne("")].drop_duplicates("ticker_norm").sort_values("rank")


def price_value(prices: pd.DataFrame, ticker: str, d: pd.Timestamp) -> float | None:
    if ticker not in prices.columns or d not in prices.index:
        return None
    val = prices.at[d, ticker]
    if pd.isna(val):
        return None
    return float(val)


def candidate_reason(prices: pd.DataFrame, ticker: str, entry: pd.Timestamp, exitd: pd.Timestamp, max_date: pd.Timestamp) -> str:
    if ticker not in prices.columns:
        return "INVALID_UNIVERSE_MISMATCH"
    if entry not in prices.index or exitd not in prices.index or exitd > max_date:
        return "INVALID_INSUFFICIENT_FORWARD_WINDOW"
    if price_value(prices, ticker, entry) is None:
        return "INVALID_MISSING_ENTRY_PRICE"
    if price_value(prices, ticker, exitd) is None:
        return "INVALID_MISSING_EXIT_PRICE"
    return ""


def build_trial(
    row: pd.Series,
    ranking: pd.DataFrame,
    prices: pd.DataFrame,
    max_date: pd.Timestamp,
) -> tuple[dict, list[dict]]:
    requested = int(row["portfolio_n"])
    entry = pd.Timestamp(row["asof_date"])
    exitd = pd.Timestamp(row["exit_date"])
    strategy = row["strategy_id"]
    bucket = row["portfolio_size"]
    horizon = row["horizon"]
    holding_rows = []
    if ranking.empty:
        tv = trial_base(row, 0, requested, False, "INVALID_EMPTY_RANKING", "No ranking rows available")
        return tv, holding_rows
    if ranking["ticker_norm"].duplicated().any():
        dup = "INVALID_DUPLICATE_TICKERS"
    else:
        dup = ""
    selected = []
    for _, c in ranking.iterrows():
        ticker = c["ticker_norm"]
        reason = candidate_reason(prices, ticker, entry, exitd, max_date)
        is_initial_top = int(c["rank"]) <= requested if pd.notna(c["rank"]) else False
        if not reason and len(selected) < requested:
            entry_px = price_value(prices, ticker, entry)
            exit_px = price_value(prices, ticker, exitd)
            ret = exit_px / entry_px - 1
            selected.append((ticker, ret, c["rank"], c["score"], is_initial_top))
            holding_rows.append(
                {
                    "trial_id": row["trial_id"],
                    "as_of_date": row["asof_date"],
                    "strategy_name": strategy,
                    "portfolio_bucket": bucket,
                    "holding_horizon": horizon,
                    "ticker": ticker,
                    "rank": c["rank"],
                    "score": c["score"],
                    "is_initial_top_bucket": is_initial_top,
                    "is_refill": not is_initial_top,
                    "entry_price": entry_px,
                    "exit_price": exit_px,
                    "holding_return": ret,
                    "holding_valid": True,
                    "invalid_reason": "",
                    "refill_source": "LOWER_RANK_REFILL_SAME_DATE_STRATEGY" if not is_initial_top else "",
                }
            )
        elif reason and is_initial_top:
            holding_rows.append(
                {
                    "trial_id": row["trial_id"],
                    "as_of_date": row["asof_date"],
                    "strategy_name": strategy,
                    "portfolio_bucket": bucket,
                    "holding_horizon": horizon,
                    "ticker": ticker,
                    "rank": c["rank"],
                    "score": c["score"],
                    "is_initial_top_bucket": True,
                    "is_refill": False,
                    "entry_price": price_value(prices, ticker, entry) if ticker in prices.columns and entry in prices.index else None,
                    "exit_price": price_value(prices, ticker, exitd) if ticker in prices.columns and exitd in prices.index else None,
                    "holding_return": None,
                    "holding_valid": False,
                    "invalid_reason": reason,
                    "refill_source": "",
                }
            )
        if len(selected) >= requested:
            break
    bench_reason = candidate_reason(prices, "QQQ", entry, exitd, max_date)
    valid_count = len(selected)
    invalid_count = max(requested - valid_count, 0)
    if dup:
        primary = dup
        detail = "Ranking contained duplicate tickers before de-duplication"
        valid = False
    elif bench_reason:
        primary = "INVALID_BENCHMARK_MISSING"
        detail = f"QQQ benchmark unavailable: {bench_reason}"
        valid = False
    elif valid_count < requested:
        primary = "INVALID_INSUFFICIENT_VALID_HOLDINGS"
        detail = f"Only {valid_count} valid holdings after deterministic same-ranking refill"
        valid = False
    else:
        primary = ""
        detail = ""
        valid = True
    tv = trial_base(row, valid_count, invalid_count, valid, primary, detail)
    if valid:
        tv["portfolio_return"] = float(np.mean([x[1] for x in selected]))
        tv["QQQ_return"] = price_value(prices, "QQQ", exitd) / price_value(prices, "QQQ", entry) - 1
    return tv, holding_rows


def trial_base(row: pd.Series, valid_count: int, invalid_count: int, valid: bool, reason: str, detail: str) -> dict:
    return {
        "trial_id": row["trial_id"],
        "as_of_date": row["asof_date"],
        "strategy_name": row["strategy_id"],
        "comparison_group": "E_R1_REPAIRED_vs_A1_BASELINE_CONTROL",
        "portfolio_bucket": row["portfolio_size"],
        "holding_horizon": row["horizon"],
        "requested_holding_count": int(row["portfolio_n"]),
        "valid_holding_count": int(valid_count),
        "invalid_holding_count": int(invalid_count),
        "is_valid_trial": bool(valid),
        "invalid_reason_primary": reason,
        "invalid_reason_detail": detail,
        "portfolio_return": None,
        "QQQ_return": None,
    }


def as_row_dict(row) -> dict:
    return row._asdict() if hasattr(row, "_asdict") else dict(row)


def build_trial_fast(
    row,
    rank_info: dict,
    prices: pd.DataFrame,
    price_row_cache: dict[pd.Timestamp, pd.Series | None],
    max_date: pd.Timestamp,
) -> tuple[dict, list[dict]]:
    r = as_row_dict(row)
    requested = int(r["portfolio_n"])
    entry = pd.Timestamp(r["asof_date"])
    exitd = pd.Timestamp(r["exit_date"])
    strategy = r["strategy_id"]
    bucket = r["portfolio_size"]
    horizon = r["horizon"]
    tickers = rank_info["tickers"]
    ranks = rank_info["ranks"]
    scores = rank_info["scores"]
    if len(tickers) == 0:
        return trial_base(pd.Series(r), 0, requested, False, "INVALID_EMPTY_RANKING", "No ranking rows available"), []
    if exitd > max_date or entry not in prices.index or exitd not in prices.index:
        return trial_base(pd.Series(r), 0, requested, False, "INVALID_INSUFFICIENT_FORWARD_WINDOW", "Entry or exit date outside price panel"), []
    entry_row = price_row_cache.get(entry)
    if entry_row is None:
        entry_row = prices.loc[entry]
        price_row_cache[entry] = entry_row
    exit_row = price_row_cache.get(exitd)
    if exit_row is None:
        exit_row = prices.loc[exitd]
        price_row_cache[exitd] = exit_row
    bench_missing = "QQQ" not in prices.columns or pd.isna(entry_row.get("QQQ", np.nan)) or pd.isna(exit_row.get("QQQ", np.nan))
    entry_vals = entry_row.reindex(tickers)
    exit_vals = exit_row.reindex(tickers)
    valid_mask = entry_vals.notna().to_numpy() & exit_vals.notna().to_numpy()
    valid_idx = np.flatnonzero(valid_mask)
    selected_idx = valid_idx[:requested]
    selected = len(selected_idx)
    holding_rows = []
    initial_end = min(requested, len(tickers))
    initial_invalid_idx = [i for i in range(initial_end) if not valid_mask[i]]
    for i in initial_invalid_idx:
        if pd.isna(entry_vals.iloc[i]):
            reason = "INVALID_MISSING_ENTRY_PRICE"
        elif pd.isna(exit_vals.iloc[i]):
            reason = "INVALID_MISSING_EXIT_PRICE"
        else:
            reason = "INVALID_UNKNOWN"
        holding_rows.append(
            {
                "trial_id": r["trial_id"],
                "as_of_date": r["asof_date"],
                "strategy_name": strategy,
                "portfolio_bucket": bucket,
                "holding_horizon": horizon,
                "ticker": tickers[i],
                "rank": ranks[i],
                "score": scores[i],
                "is_initial_top_bucket": True,
                "is_refill": False,
                "entry_price": None if pd.isna(entry_vals.iloc[i]) else float(entry_vals.iloc[i]),
                "exit_price": None if pd.isna(exit_vals.iloc[i]) else float(exit_vals.iloc[i]),
                "holding_return": None,
                "holding_valid": False,
                "invalid_reason": reason,
                "refill_source": "",
            }
        )
    returns = []
    for i in selected_idx:
        entry_px = float(entry_vals.iloc[i])
        exit_px = float(exit_vals.iloc[i])
        ret = exit_px / entry_px - 1
        returns.append(ret)
        is_initial = bool(i < requested)
        holding_rows.append(
            {
                "trial_id": r["trial_id"],
                "as_of_date": r["asof_date"],
                "strategy_name": strategy,
                "portfolio_bucket": bucket,
                "holding_horizon": horizon,
                "ticker": tickers[i],
                "rank": ranks[i],
                "score": scores[i],
                "is_initial_top_bucket": is_initial,
                "is_refill": not is_initial,
                "entry_price": entry_px,
                "exit_price": exit_px,
                "holding_return": ret,
                "holding_valid": True,
                "invalid_reason": "",
                "refill_source": "LOWER_RANK_REFILL_SAME_DATE_STRATEGY" if not is_initial else "",
            }
        )
    if bench_missing:
        valid = False
        reason = "INVALID_BENCHMARK_MISSING"
        detail = "QQQ benchmark missing for entry or exit date"
    elif selected < requested:
        valid = False
        reason = "INVALID_INSUFFICIENT_VALID_HOLDINGS"
        detail = f"Only {selected} valid holdings after deterministic same-ranking refill"
    else:
        valid = True
        reason = ""
        detail = ""
    tv = trial_base(pd.Series(r), selected, max(requested - selected, 0), valid, reason, detail)
    if valid:
        tv["portfolio_return"] = float(np.mean(returns))
        tv["QQQ_return"] = float(exit_row["QQQ"] / entry_row["QQQ"] - 1)
    return tv, holding_rows


def clean_stats(paired: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, g in paired.groupby(["portfolio_bucket", "holding_horizon"], dropna=False):
        valid = g[g["paired_valid"]].copy()
        invalid_count = int((~g["paired_valid"]).sum())
        e = valid["E_R1_return"].dropna()
        a = valid["A1_return"].dropna()
        diff = e.to_numpy() - a.to_numpy() if len(e) == len(a) else np.array([])
        e_tail = e[e <= e.quantile(0.05)] if len(e) else pd.Series(dtype=float)
        a_tail = a[a <= a.quantile(0.05)] if len(a) else pd.Series(dtype=float)
        rows.append(
            {
                "portfolio_bucket": keys[0],
                "holding_horizon": keys[1],
                "valid_paired_trial_count": int(len(valid)),
                "invalid_paired_trial_count": invalid_count,
                "invalid_rate": invalid_count / max(len(g), 1),
                "E_R1_average_return": float(e.mean()) if len(e) else None,
                "A1_average_return": float(a.mean()) if len(a) else None,
                "E_R1_minus_A1_average_return": float(np.mean(diff)) if len(diff) else None,
                "E_R1_winrate_vs_A1": float((diff > 0).mean()) if len(diff) else None,
                "E_R1_left_tail_5pct": float(e_tail.mean()) if len(e_tail) else None,
                "A1_left_tail_5pct": float(a_tail.mean()) if len(a_tail) else None,
                "E_R1_left_tail_advantage": bool(e_tail.mean() > a_tail.mean()) if len(e_tail) and len(a_tail) else False,
                "E_R1_drawdown_proxy": float(e.min()) if len(e) else None,
                "A1_drawdown_proxy": float(a.min()) if len(a) else None,
                "QQQ_average_return": float(valid["QQQ_return"].mean()) if len(valid) else None,
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s148 = load_json(SUMMARY_148)
    s149 = load_json(SUMMARY_149)
    src_trials = pd.read_csv(TRIALS)
    src_invalid = pd.read_csv(INVALID_148)
    reproduced_invalid = int((~src_trials["valid_trial"].astype(bool)).sum())
    expected_invalid = int(s148.get("invalid_trial_count", -1))
    reproduction_warning = "" if reproduced_invalid == expected_invalid else f"Expected {expected_invalid}, reproduced {reproduced_invalid}"
    prices = pd.read_csv(PRICE)
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.set_index("date").sort_index()
    max_date = prices.index.max()
    rankings = {
        "A1_BASELINE_CONTROL": load_ranking(A1_RANK, "A1_BASELINE_CONTROL"),
        "E_R1_REPAIRED": load_ranking(E_R1_RANK, "E_R1_REPAIRED"),
    }
    rank_info = {}
    for strategy, rdf in rankings.items():
        rank_info[strategy] = {
            "tickers": rdf["ticker_norm"].tolist(),
            "ranks": rdf["rank"].tolist(),
            "scores": rdf["score"].tolist(),
        }
    trial_rows, holding_rows = [], []
    needed = src_trials[src_trials["strategy_id"].isin(rankings)].copy()
    price_row_cache: dict[pd.Timestamp, pd.Series | None] = {}
    for row in needed.itertuples(index=False):
        strategy = getattr(row, "strategy_id")
        tv, hh = build_trial_fast(row, rank_info[strategy], prices, price_row_cache, max_date)
        trial_rows.append(tv)
        holding_rows.extend(hh)
    trial_df = pd.DataFrame(trial_rows)
    holding_df = pd.DataFrame(holding_rows)
    a = trial_df[trial_df["strategy_name"].eq("A1_BASELINE_CONTROL")].rename(
        columns={
            "is_valid_trial": "A1_valid",
            "invalid_reason_primary": "A1_invalid_reason",
            "portfolio_return": "A1_return",
        }
    )
    e = trial_df[trial_df["strategy_name"].eq("E_R1_REPAIRED")].rename(
        columns={
            "is_valid_trial": "E_R1_valid",
            "invalid_reason_primary": "E_R1_invalid_reason",
            "portfolio_return": "E_R1_return",
        }
    )
    pair_keys = ["trial_id", "as_of_date", "portfolio_bucket", "holding_horizon"]
    paired = e[pair_keys + ["E_R1_valid", "E_R1_invalid_reason", "E_R1_return", "QQQ_return"]].merge(
        a[pair_keys + ["A1_valid", "A1_invalid_reason", "A1_return"]],
        on=pair_keys,
        how="outer",
    )
    paired["paired_valid"] = paired["E_R1_valid"].fillna(False).astype(bool) & paired["A1_valid"].fillna(False).astype(bool) & paired["QQQ_return"].notna()
    paired["paired_invalid_reason"] = np.where(
        paired["paired_valid"],
        "",
        "E_R1=" + paired["E_R1_invalid_reason"].fillna("MISSING_SIDE") + "|A1=" + paired["A1_invalid_reason"].fillna("MISSING_SIDE"),
    )
    stats = clean_stats(paired)
    reason_count = trial_df["invalid_reason_primary"].replace("", "VALID").value_counts().rename_axis("invalid_reason").reset_index(name="count")
    for reason in INVALID_REASONS:
        if reason not in set(reason_count["invalid_reason"]):
            reason_count = pd.concat([reason_count, pd.DataFrame([{"invalid_reason": reason, "count": 0}])], ignore_index=True)
    invalid_trials = trial_df[~trial_df["is_valid_trial"]].copy()
    if invalid_trials.empty:
        invalid_trials = pd.DataFrame(columns=trial_df.columns)
    by_date = invalid_trials.groupby(["as_of_date", "invalid_reason_primary"], dropna=False).size().reset_index(name="count")
    by_strategy = invalid_trials.groupby(["strategy_name", "invalid_reason_primary"], dropna=False).size().reset_index(name="count")
    by_horizon = invalid_trials.groupby(["holding_horizon", "invalid_reason_primary"], dropna=False).size().reset_index(name="count")
    by_bucket = invalid_trials.groupby(["portfolio_bucket", "invalid_reason_primary"], dropna=False).size().reset_index(name="count")
    total_valid_paired = int(stats["valid_paired_trial_count"].sum())
    total_invalid_paired = int(stats["invalid_paired_trial_count"].sum())
    sufficient = total_valid_paired >= 1000 and (total_invalid_paired / max(total_valid_paired + total_invalid_paired, 1)) < 0.5
    left_tail_persisted = bool(stats["E_R1_left_tail_advantage"].any())
    if sufficient and left_tail_persisted:
        final_status = "PASS_V21_154_E_R1_REPLAY_REPAIRED_LEFT_TAIL_CONFIRMED"
        decision = "E_R1_DEFENSIVE_CANDIDATE_WAIT_FORWARD_MATURITY"
    elif sufficient:
        final_status = "PARTIAL_PASS_V21_154_E_R1_LEFT_TAIL_ADVANTAGE_NOT_CONFIRMED"
        decision = "E_R1_DEFENSIVE_CANDIDATE_DOWNGRADED_DIAGNOSTIC_ONLY"
    else:
        final_status = "BLOCKED_V21_154_E_R1_REPLAY_STILL_INVALID"
        decision = "E_R1_HISTORY_REPLAY_BLOCKED_USE_FORWARD_ONLY"
    summary = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "v21_148_invalid_trial_count_expected": expected_invalid,
        "v21_148_invalid_trial_count_reproduced": reproduced_invalid,
        "reproduction_warning": reproduction_warning,
        "v21_149_decision": s149.get("DECISION"),
        "total_valid_paired_trial_count": total_valid_paired,
        "total_invalid_paired_trial_count": total_invalid_paired,
        "paired_invalid_rate": total_invalid_paired / max(total_valid_paired + total_invalid_paired, 1),
        "E_R1_left_tail_advantage_persisted_clean": left_tail_persisted,
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
    }
    trial_df.to_csv(OUT / "trial_validity_ledger.csv", index=False)
    holding_df.to_csv(OUT / "holding_level_validity_ledger.csv", index=False)
    paired.to_csv(OUT / "paired_validity_ledger.csv", index=False)
    stats.to_csv(OUT / "clean_replay_summary.csv", index=False)
    reason_count.to_csv(OUT / "invalid_reason_count.csv", index=False)
    by_date.to_csv(OUT / "invalid_reason_by_date.csv", index=False)
    by_strategy.to_csv(OUT / "invalid_reason_by_strategy.csv", index=False)
    by_horizon.to_csv(OUT / "invalid_reason_by_horizon.csv", index=False)
    by_bucket.to_csv(OUT / "invalid_reason_by_bucket.csv", index=False)
    stats.to_csv(OUT / "e_r1_vs_a1_clean_replay_result.csv", index=False)
    (OUT / "V21.154_machine_summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"v21_148_invalid_trial_count_expected={expected_invalid}",
        f"v21_148_invalid_trial_count_reproduced={reproduced_invalid}",
        f"reproduction_warning={reproduction_warning or 'NONE'}",
        f"total_valid_paired_trial_count={total_valid_paired}",
        f"total_invalid_paired_trial_count={total_invalid_paired}",
        f"paired_invalid_rate={summary['paired_invalid_rate']}",
        f"E_R1_left_tail_advantage_persisted_clean={str(left_tail_persisted).lower()}",
        "partial_portfolios_excluded=true",
        "one_sided_invalid_pairs_excluded=true",
        "deterministic_refill=same_strategy_same_asof_same_ranking_lower_rank_only",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false",
        f"report_path={str(OUT / 'V21.154_readable_report.txt').replace(chr(92), '/')}",
    ]
    (OUT / "V21.154_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    print(json.dumps(summary, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
