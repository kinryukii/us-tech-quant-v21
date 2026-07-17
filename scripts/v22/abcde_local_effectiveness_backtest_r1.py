
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import uuid
from pathlib import Path
from typing import Iterable

try:
    import duckdb
    import numpy as np
    import pandas as pd
except ImportError as exc:
    raise SystemExit(
        "Missing dependencies. Run:\n"
        "python -m pip install duckdb pandas numpy pyarrow"
    ) from exc


DATE_CANDIDATES = [
    "asof_date", "as_of_date", "signal_date", "trade_date",
    "price_date", "date", "datetime", "timestamp"
]
TICKER_CANDIDATES = [
    "ticker", "symbol", "stock_code", "security_code",
    "moomoo_symbol", "code"
]
STRATEGY_CANDIDATES = [
    "strategy", "strategy_name", "strategy_id", "model", "variant"
]
RANK_CANDIDATES = [
    "rank", "strategy_rank", "overall_rank", "final_rank",
    "panel_rank", "rank_within_strategy"
]
SCORE_CANDIDATES = [
    "score", "strategy_score", "final_score", "composite_score",
    "total_score", "ranking_score"
]
CLOSE_CANDIDATES = [
    "close", "qfq_close", "adj_close", "adjusted_close",
    "close_price", "price_close"
]

STRATEGY_ALIASES = {
    "A1": ["a1", "a1_control", "control"],
    "B": ["b", "b_static_momentum", "static_momentum"],
    "C": ["c", "c_dynamic_momentum", "dynamic_momentum"],
    "D": ["d", "d_weight_optimized", "weight_optimized", "optimized"],
    "E": ["e", "e_defensive", "defensive"],
}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def qident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def qlit(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def find_exact_or_contains(columns: list[str], candidates: list[str]) -> str | None:
    by_norm = {norm(c): c for c in columns}
    for cand in candidates:
        if cand in by_norm:
            return by_norm[cand]
    for c in columns:
        n = norm(c)
        if any(cand in n for cand in candidates):
            return c
    return None


def detect_forward_columns(columns: list[str]) -> dict[int, str]:
    result: dict[int, str] = {}
    patterns = [
        re.compile(r"(?i)(?:fwd|forward|future)[^0-9]*(1|5|10|20)[^0-9]*(?:d|day)?.*(?:ret|return)"),
        re.compile(r"(?i)(?:ret|return).*(?:fwd|forward|future)[^0-9]*(1|5|10|20)"),
        re.compile(r"(?i)(?:fwd|forward|future)[^0-9]*(1|5|10|20)[^0-9]*(?:d|day)?$"),
        re.compile(r"(?i)^(?:ret|return)[^0-9]*(1|5|10|20)[^0-9]*(?:d|day)?$"),
    ]
    for c in columns:
        n = norm(c)
        for pat in patterns:
            m = pat.search(n)
            if m:
                result[int(m.group(1))] = c
                break
    return result


def describe_csv(con: duckdb.DuckDBPyConnection, path: Path) -> list[str]:
    sql = f"DESCRIBE SELECT * FROM read_csv_auto({qlit(str(path))}, header=true, sample_size=200000)"
    return con.execute(sql).df()["column_name"].astype(str).tolist()


def describe_parquet(con: duckdb.DuckDBPyConnection, paths: list[Path]) -> list[str]:
    plist = "[" + ",".join(qlit(str(p)) for p in paths) + "]"
    sql = f"DESCRIBE SELECT * FROM read_parquet({plist}, union_by_name=true)"
    return con.execute(sql).df()["column_name"].astype(str).tolist()


def source_sql(paths: list[Path]) -> str:
    if not paths:
        raise ValueError("No source paths.")
    if all(p.suffix.lower() == ".parquet" for p in paths):
        plist = "[" + ",".join(qlit(str(p)) for p in paths) + "]"
        return f"read_parquet({plist}, union_by_name=true)"
    if len(paths) == 1:
        return (
            f"read_csv_auto({qlit(str(paths[0]))}, header=true, "
            "sample_size=200000, ignore_errors=true)"
        )
    plist = "[" + ",".join(qlit(str(p)) for p in paths) + "]"
    return (
        f"read_csv_auto({plist}, header=true, union_by_name=true, "
        "sample_size=200000, ignore_errors=true, filename=true)"
    )


def discover_panel(repo: Path, explicit: str | None) -> list[Path]:
    if explicit:
        p = Path(explicit)
        if p.is_dir():
            files = sorted(p.glob("technical_forward_join_panel_*.parquet"))
            if files:
                return files
            files = sorted(p.glob("*.parquet"))
            if files:
                return files
        if p.exists():
            return [p]
        raise FileNotFoundError(p)

    parquet_dirs = sorted(
        (repo / "exports").glob("ABCDE_BACKTEST_PANEL_EXTRACT_*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for d in parquet_dirs:
        files = sorted(d.glob("technical_forward_join_panel_*.parquet"))
        if files:
            return files

    csv_path = (
        repo / "outputs" / "v21"
        / "V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1"
        / "technical_forward_join_panel.csv"
    )
    if csv_path.exists():
        return [csv_path]
    raise FileNotFoundError("technical_forward_join_panel source not found")


def discover_ranking_files(repo: Path) -> list[Path]:
    patterns = [
        "outputs/**/abcde_strategy_ranking_master.csv",
        "outputs/**/abcde_strategy_ranking_master_*.csv",
    ]
    found: list[Path] = []
    for pat in patterns:
        found.extend(repo.glob(pat))
    return sorted(set(p.resolve() for p in found if p.is_file()))


def detect_wide_strategy_columns(columns: list[str]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    normalized = {c: norm(c) for c in columns}
    for strategy, aliases in STRATEGY_ALIASES.items():
        rank_col = None
        score_col = None
        for c, n in normalized.items():
            alias_hit = any(
                n == a or n.startswith(a + "_") or ("_" + a + "_") in ("_" + n + "_")
                for a in aliases
            )
            if not alias_hit:
                continue
            if "rank" in n:
                rank_col = c
            if "score" in n:
                score_col = c
        if rank_col or score_col:
            out[strategy] = {}
            if rank_col:
                out[strategy]["rank"] = rank_col
            if score_col:
                out[strategy]["score"] = score_col
    return out


def normalize_strategy(value: str) -> str:
    n = norm(value)
    for strategy, aliases in STRATEGY_ALIASES.items():
        if n == norm(strategy) or any(n == a or n.startswith(a + "_") for a in aliases):
            return strategy
    return str(value)


def parse_date_from_path(path: Path) -> pd.Timestamp | None:
    text = str(path)
    matches = re.findall(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", text)
    if not matches:
        return None
    y, m, d = matches[-1]
    try:
        return pd.Timestamp(f"{y}-{m}-{d}")
    except Exception:
        return None


def load_ranks_from_panel(
    con: duckdb.DuckDBPyConnection,
    paths: list[Path],
    columns: list[str],
    start_date: str,
    end_date: str,
    max_rank: int,
) -> pd.DataFrame | None:
    date_col = find_exact_or_contains(columns, DATE_CANDIDATES)
    ticker_col = find_exact_or_contains(columns, TICKER_CANDIDATES)
    strategy_col = find_exact_or_contains(columns, STRATEGY_CANDIDATES)
    rank_col = find_exact_or_contains(columns, RANK_CANDIDATES)
    score_col = find_exact_or_contains(columns, SCORE_CANDIDATES)
    src = source_sql(paths)

    if not date_col or not ticker_col:
        return None

    if strategy_col and (rank_col or score_col):
        rank_expr = (
            f"TRY_CAST({qident(rank_col)} AS DOUBLE)"
            if rank_col else
            f"ROW_NUMBER() OVER (PARTITION BY CAST({qident(date_col)} AS DATE), "
            f"{qident(strategy_col)} ORDER BY TRY_CAST({qident(score_col)} AS DOUBLE) DESC)"
        )
        score_expr = (
            f"TRY_CAST({qident(score_col)} AS DOUBLE)"
            if score_col else "NULL::DOUBLE"
        )
        sql = f"""
            SELECT
                CAST({qident(date_col)} AS DATE) AS signal_date,
                CAST({qident(ticker_col)} AS VARCHAR) AS ticker,
                CAST({qident(strategy_col)} AS VARCHAR) AS strategy,
                {rank_expr} AS rank,
                {score_expr} AS score
            FROM {src}
            WHERE CAST({qident(date_col)} AS DATE)
                  BETWEEN DATE {qlit(start_date)} AND DATE {qlit(end_date)}
            QUALIFY rank <= {int(max_rank)}
        """
        df = con.execute(sql).df()
        if not df.empty:
            df["strategy"] = df["strategy"].map(normalize_strategy)
            return df

    wide = detect_wide_strategy_columns(columns)
    if not wide:
        return None

    parts = []
    for strategy, cols in wide.items():
        rank_col_s = cols.get("rank")
        score_col_s = cols.get("score")
        if rank_col_s:
            rank_expr = f"TRY_CAST({qident(rank_col_s)} AS DOUBLE)"
        else:
            rank_expr = (
                f"ROW_NUMBER() OVER (PARTITION BY CAST({qident(date_col)} AS DATE) "
                f"ORDER BY TRY_CAST({qident(score_col_s)} AS DOUBLE) DESC)"
            )
        score_expr = (
            f"TRY_CAST({qident(score_col_s)} AS DOUBLE)"
            if score_col_s else "NULL::DOUBLE"
        )
        parts.append(f"""
            SELECT
                CAST({qident(date_col)} AS DATE) AS signal_date,
                CAST({qident(ticker_col)} AS VARCHAR) AS ticker,
                {qlit(strategy)} AS strategy,
                {rank_expr} AS rank,
                {score_expr} AS score
            FROM {src}
            WHERE CAST({qident(date_col)} AS DATE)
                  BETWEEN DATE {qlit(start_date)} AND DATE {qlit(end_date)}
            QUALIFY rank <= {int(max_rank)}
        """)
    df = con.execute(" UNION ALL ".join(parts)).df()
    return df if not df.empty else None


def load_ranks_from_snapshots(
    ranking_files: list[Path],
    max_rank: int,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in ranking_files:
        try:
            df = pd.read_csv(path, low_memory=False)
        except Exception:
            continue
        cols = list(df.columns)
        ticker_col = find_exact_or_contains(cols, TICKER_CANDIDATES)
        strategy_col = find_exact_or_contains(cols, STRATEGY_CANDIDATES)
        rank_col = find_exact_or_contains(cols, RANK_CANDIDATES)
        score_col = find_exact_or_contains(cols, SCORE_CANDIDATES)
        date_col = find_exact_or_contains(cols, DATE_CANDIDATES)
        if not ticker_col or not strategy_col or not (rank_col or score_col):
            continue

        out = pd.DataFrame()
        if date_col:
            out["signal_date"] = pd.to_datetime(df[date_col], errors="coerce").dt.normalize()
        else:
            inferred = parse_date_from_path(path)
            if inferred is None:
                continue
            out["signal_date"] = inferred

        out["ticker"] = df[ticker_col].astype(str)
        out["strategy"] = df[strategy_col].astype(str).map(normalize_strategy)
        if rank_col:
            out["rank"] = pd.to_numeric(df[rank_col], errors="coerce")
        else:
            out["score"] = pd.to_numeric(df[score_col], errors="coerce")
            out["rank"] = out.groupby(["signal_date", "strategy"])["score"].rank(
                ascending=False, method="first"
            )
        out["score"] = (
            pd.to_numeric(df[score_col], errors="coerce")
            if score_col else np.nan
        )
        out["source_file"] = str(path)
        out = out.dropna(subset=["signal_date", "ticker", "strategy", "rank"])
        out = out[out["rank"] <= max_rank]
        frames.append(out)

    if not frames:
        raise RuntimeError(
            "No usable historical ABCDE ranking rows were found. "
            "The large panel also did not expose strategy/rank columns."
        )

    result = pd.concat(frames, ignore_index=True)
    result = result.sort_values(["signal_date", "strategy", "rank"])
    result = result.drop_duplicates(["signal_date", "strategy", "ticker"], keep="last")
    return result


def load_forward_returns(
    con: duckdb.DuckDBPyConnection,
    paths: list[Path],
    columns: list[str],
    start_date: str,
    end_date: str,
) -> tuple[pd.DataFrame, dict[int, str]]:
    date_col = find_exact_or_contains(columns, DATE_CANDIDATES)
    ticker_col = find_exact_or_contains(columns, TICKER_CANDIDATES)
    fwd_cols = detect_forward_columns(columns)
    if not date_col or not ticker_col:
        raise RuntimeError("Could not detect date/ticker columns in forward panel.")
    if 1 not in fwd_cols:
        raise RuntimeError(
            "No 1-day forward return column detected. "
            "Open SCHEMA_REPORT.json and pass explicit mappings in a future revision."
        )

    src = source_sql(paths)
    selects = [
        f"CAST({qident(date_col)} AS DATE) AS date",
        f"CAST({qident(ticker_col)} AS VARCHAR) AS ticker",
    ]
    for h, c in sorted(fwd_cols.items()):
        selects.append(f"TRY_CAST({qident(c)} AS DOUBLE) AS fwd_{h}d")

    sql = f"""
        SELECT {", ".join(selects)}
        FROM {src}
        WHERE CAST({qident(date_col)} AS DATE)
              BETWEEN DATE {qlit(start_date)} AND DATE {qlit(end_date)}
    """
    df = con.execute(sql).df()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["ticker"] = df["ticker"].astype(str).str.upper().str.replace(r"^US\.", "", regex=True)
    agg = {f"fwd_{h}d": "first" for h in fwd_cols}
    df = df.groupby(["date", "ticker"], as_index=False).agg(agg)
    return df, fwd_cols


def map_execution_dates(signal_dates: pd.Series, calendar: np.ndarray, lag_days: int) -> pd.Series:
    values = pd.to_datetime(signal_dates).values.astype("datetime64[D]")
    idx = np.searchsorted(calendar, values, side="right") + max(lag_days - 1, 0)
    out = np.full(len(values), np.datetime64("NaT"), dtype="datetime64[D]")
    valid = idx < len(calendar)
    out[valid] = calendar[idx[valid]]
    return pd.to_datetime(out)


def max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    dd = equity / equity.cummax() - 1.0
    return float(dd.min()) if len(dd) else math.nan


def annualized_return(returns: pd.Series) -> float:
    r = returns.dropna()
    if r.empty:
        return math.nan
    total = float((1.0 + r).prod())
    if total <= 0:
        return -1.0
    return total ** (252.0 / len(r)) - 1.0


def summarize_daily(group: pd.DataFrame, return_col: str) -> dict:
    r = group[return_col].dropna()
    if r.empty:
        return {}
    vol = float(r.std(ddof=1) * math.sqrt(252)) if len(r) > 1 else math.nan
    ann = annualized_return(r)
    sharpe = (
        float(r.mean() / r.std(ddof=1) * math.sqrt(252))
        if len(r) > 1 and r.std(ddof=1) > 0 else math.nan
    )
    return {
        "observations": int(len(r)),
        "start_date": str(group["execution_date"].min().date()),
        "end_date": str(group["execution_date"].max().date()),
        "cumulative_return": float((1.0 + r).prod() - 1.0),
        "annualized_return": ann,
        "annualized_volatility": vol,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown(r),
        "positive_day_rate": float((r > 0).mean()),
        "mean_daily_return": float(r.mean()),
        "median_daily_return": float(r.median()),
    }


def calculate_turnover(holdings: pd.DataFrame, topk: int) -> pd.DataFrame:
    rows = []
    for strategy, g in holdings.groupby("strategy"):
        prev: set[str] | None = None
        for dt, day in g.sort_values("execution_date").groupby("execution_date"):
            current = set(day.loc[day["rank"] <= topk, "ticker"])
            if not current:
                continue
            turnover = math.nan if prev is None else 1.0 - len(prev & current) / max(len(prev), len(current))
            rows.append({
                "strategy": strategy,
                "topk": topk,
                "execution_date": dt,
                "turnover": turnover,
            })
            prev = current
    return pd.DataFrame(rows)


def run_backtest(
    ranks: pd.DataFrame,
    returns: pd.DataFrame,
    horizons: list[int],
    topks: list[int],
    lag_days: int,
    cost_bps: float,
    output_dir: Path,
) -> None:
    ranks = ranks.copy()
    ranks["signal_date"] = pd.to_datetime(ranks["signal_date"]).dt.normalize()
    ranks["ticker"] = ranks["ticker"].astype(str).str.upper().str.replace(r"^US\.", "", regex=True)
    ranks["rank"] = pd.to_numeric(ranks["rank"], errors="coerce")
    ranks = ranks.dropna(subset=["signal_date", "ticker", "strategy", "rank"])

    calendar = np.array(sorted(returns["date"].dropna().unique()), dtype="datetime64[D]")
    ranks["execution_date"] = map_execution_dates(ranks["signal_date"], calendar, lag_days)
    ranks = ranks.dropna(subset=["execution_date"])

    merged = ranks.merge(
        returns,
        left_on=["execution_date", "ticker"],
        right_on=["date", "ticker"],
        how="left",
        validate="many_to_one",
    )

    merged.to_parquet(output_dir / "joined_rank_forward_rows.parquet", index=False)

    benchmark = returns.groupby("date", as_index=False).agg(
        **{f"benchmark_fwd_{h}d": (f"fwd_{h}d", "mean") for h in horizons if f"fwd_{h}d" in returns}
    )
    qqq = returns[returns["ticker"].isin(["QQQ"])].copy()
    qqq = qqq.rename(columns={f"fwd_{h}d": f"qqq_fwd_{h}d" for h in horizons if f"fwd_{h}d" in qqq})

    daily_rows = []
    summary_rows = []
    event_rows = []
    turnover_frames = []

    for topk in topks:
        selected = merged[merged["rank"] <= topk].copy()
        if selected.empty:
            continue

        turnover = calculate_turnover(selected[["strategy", "execution_date", "ticker", "rank"]], topk)
        turnover_frames.append(turnover)

        for horizon in horizons:
            col = f"fwd_{horizon}d"
            if col not in selected.columns:
                continue

            daily = (
                selected.groupby(["strategy", "execution_date"], as_index=False)
                .agg(
                    gross_return=(col, "mean"),
                    holdings=(ticker_col := "ticker", "nunique"),
                    avg_rank=("rank", "mean"),
                )
            )
            daily = daily.merge(
                benchmark[["date", f"benchmark_fwd_{horizon}d"]],
                left_on="execution_date", right_on="date", how="left",
            ).drop(columns=["date"])
            if not qqq.empty and f"qqq_fwd_{horizon}d" in qqq:
                daily = daily.merge(
                    qqq[["date", f"qqq_fwd_{horizon}d"]],
                    left_on="execution_date", right_on="date", how="left",
                ).drop(columns=["date"])

            if horizon == 1:
                daily = daily.merge(
                    turnover[["strategy", "execution_date", "turnover"]],
                    on=["strategy", "execution_date"], how="left",
                )
                daily["net_return"] = daily["gross_return"] - daily["turnover"].fillna(0.0) * cost_bps / 10000.0
            else:
                daily["turnover"] = np.nan
                daily["net_return"] = daily["gross_return"]

            daily["excess_vs_universe"] = (
                daily["gross_return"] - daily[f"benchmark_fwd_{horizon}d"]
            )
            qqq_col = f"qqq_fwd_{horizon}d"
            daily["excess_vs_qqq"] = (
                daily["gross_return"] - daily[qqq_col]
                if qqq_col in daily.columns else np.nan
            )
            daily["topk"] = topk
            daily["horizon_days"] = horizon
            daily_rows.append(daily)

            for strategy, g in daily.groupby("strategy"):
                event_rows.append({
                    "strategy": strategy,
                    "topk": topk,
                    "horizon_days": horizon,
                    "observations": int(g["gross_return"].notna().sum()),
                    "mean_forward_return": float(g["gross_return"].mean()),
                    "median_forward_return": float(g["gross_return"].median()),
                    "positive_rate": float((g["gross_return"] > 0).mean()),
                    "mean_excess_vs_universe": float(g["excess_vs_universe"].mean()),
                    "mean_excess_vs_qqq": float(g["excess_vs_qqq"].mean()) if g["excess_vs_qqq"].notna().any() else math.nan,
                    "t_stat_vs_zero": (
                        float(g["gross_return"].mean() / g["gross_return"].std(ddof=1) * math.sqrt(g["gross_return"].notna().sum()))
                        if g["gross_return"].notna().sum() > 1 and g["gross_return"].std(ddof=1) > 0 else math.nan
                    ),
                })

                if horizon == 1:
                    gross = summarize_daily(g, "gross_return")
                    net = summarize_daily(g, "net_return")
                    row = {
                        "strategy": strategy,
                        "topk": topk,
                        "horizon_days": horizon,
                        **{f"gross_{k}": v for k, v in gross.items()},
                        **{f"net_{k}": v for k, v in net.items()},
                        "mean_turnover": float(g["turnover"].mean()),
                        "mean_excess_vs_universe": float(g["excess_vs_universe"].mean()),
                        "mean_excess_vs_qqq": float(g["excess_vs_qqq"].mean()) if g["excess_vs_qqq"].notna().any() else math.nan,
                    }
                    summary_rows.append(row)

    if not daily_rows:
        raise RuntimeError("No valid backtest rows were produced.")

    daily_all = pd.concat(daily_rows, ignore_index=True)
    daily_all.to_csv(output_dir / "strategy_daily_and_event_returns.csv", index=False)
    pd.DataFrame(summary_rows).to_csv(output_dir / "strategy_performance_summary.csv", index=False)
    pd.DataFrame(event_rows).to_csv(output_dir / "strategy_forward_event_summary.csv", index=False)
    if turnover_frames:
        pd.concat(turnover_frames, ignore_index=True).to_csv(
            output_dir / "strategy_turnover.csv", index=False
        )

    # Pairwise Top-20 Jaccard overlap by date.
    top20 = ranks[ranks["rank"] <= 20]
    overlap_rows = []
    for dt, day in top20.groupby("execution_date"):
        sets = {s: set(g["ticker"]) for s, g in day.groupby("strategy")}
        strategies = sorted(sets)
        for i, a in enumerate(strategies):
            for b in strategies[i + 1:]:
                union = sets[a] | sets[b]
                overlap_rows.append({
                    "execution_date": dt,
                    "strategy_a": a,
                    "strategy_b": b,
                    "intersection": len(sets[a] & sets[b]),
                    "union": len(union),
                    "jaccard": len(sets[a] & sets[b]) / len(union) if union else math.nan,
                })
    pd.DataFrame(overlap_rows).to_csv(output_dir / "strategy_top20_overlap.csv", index=False)

    # Rank IC on available ranked names.
    ic_rows = []
    for horizon in horizons:
        col = f"fwd_{horizon}d"
        if col not in merged.columns:
            continue
        for (strategy, dt), g in merged.groupby(["strategy", "execution_date"]):
            valid = g[["rank", col]].dropna()
            if len(valid) < 5:
                continue
            # Spearman is Pearson correlation of average ranks; avoid optional scipy runtime dependency.
            ic = valid["rank"].rank(method="average").corr(valid[col].rank(method="average"))
            ic_rows.append({
                "strategy": strategy,
                "execution_date": dt,
                "horizon_days": horizon,
                "rank_ic": -ic if pd.notna(ic) else np.nan,
                "names": len(valid),
            })
    ic_df = pd.DataFrame(ic_rows)
    ic_df.to_csv(output_dir / "strategy_rank_ic_daily.csv", index=False)
    if not ic_df.empty:
        (
            ic_df.groupby(["strategy", "horizon_days"], as_index=False)
            .agg(
                mean_rank_ic=("rank_ic", "mean"),
                median_rank_ic=("rank_ic", "median"),
                ic_positive_rate=("rank_ic", lambda s: float((s > 0).mean())),
                observations=("rank_ic", "count"),
            )
            .to_csv(output_dir / "strategy_rank_ic_summary.csv", index=False)
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Local, PIT-conscious ABCDE strategy comparison backtest."
    )
    parser.add_argument("--repo-root", default=r"D:\us-tech-quant")
    parser.add_argument("--panel-path", default=None)
    parser.add_argument("--start-date", default="2022-01-01")
    parser.add_argument("--end-date", default="2026-07-13")
    parser.add_argument("--topk", default="5,10,20,50")
    parser.add_argument("--lag-days", type=int, default=1)
    parser.add_argument("--cost-bps", type=float, default=5.0)
    parser.add_argument("--max-rank", type=int, default=50)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--input-mode", choices=["compact", "legacy"], default="compact")
    parser.add_argument("--rank-history-path", default=r"D:\us-tech-quant-backtests\_strategy_signal_history\ABCDE_R1\abcde_rank_history.parquet")
    parser.add_argument("--stock-data-root", default=r"D:\us-tech-quant-data\stocks")
    parser.add_argument("--output-root", default=r"D:\us-tech-quant-backtests\ABCDE_LOCAL_EFFECTIVENESS")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--forward-horizons", default="1,3,5,10,20")
    parser.add_argument("--allow-legacy-input", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo_root)
    if args.input_mode == "legacy" and not args.allow_legacy_input:
        raise RuntimeError("legacy input requires --allow-legacy-input")
    if args.input_mode == "compact":
        sys.path.insert(0, str(repo / "scripts/storage"))
        from abcde_signal_store import load_compact_rank_history, join_rankings_with_forward_returns
        run_id = args.run_id or uuid.uuid4().hex[:12]
        output_dir = Path(args.output_dir) if args.output_dir else Path(args.output_root) / f"{pd.Timestamp.utcnow().strftime('%Y%m%d_%H%M%S')}_{run_id}"
        try:
            output_dir.resolve().relative_to(repo.resolve())
            inside_repo = True
        except ValueError:
            inside_repo = False
        if inside_repo:
            raise RuntimeError("compact output must be outside repo")
        output_dir.mkdir(parents=True, exist_ok=False)
        horizons = sorted({int(x) for x in args.forward_horizons.split(",") if x.strip()})
        ranks = load_compact_rank_history(Path(args.rank_history_path), args.start_date, args.end_date).rename(columns={"research_date":"signal_date","strategy_id":"strategy"})
        joined = join_rankings_with_forward_returns(ranks.rename(columns={"signal_date":"research_date"}), horizons, Path(args.stock_data_root)).rename(columns={"research_date":"date", **{f"forward_{h}d":f"fwd_{h}d" for h in horizons}})
        returns = joined[["date","ticker", *[f"fwd_{h}d" for h in horizons]]].drop_duplicates(["date","ticker"])
        returns["date"] = pd.to_datetime(returns["date"])
        ranks["signal_date"] = pd.to_datetime(ranks["signal_date"])
        ranks = ranks[["signal_date","ticker","strategy","rank","score"]]
        run_backtest(ranks, returns, horizons, sorted({int(x.strip()) for x in args.topk.split(',') if x.strip()}), args.lag_days, args.cost_bps, output_dir)
        summary={"final_status":"PASS_ABCDE_COMPACT_BACKTEST_COMPLETE","input_mode":"COMPACT_RANKING_AND_PER_TICKER_QFQ","rank_history_path":args.rank_history_path,"stock_data_root":args.stock_data_root,"output_dir":str(output_dir),"run_id":run_id,"input_data_copied":False,"duplicate_market_data_count":0,"broker_action_allowed":False,"official_adoption_allowed":False,"research_only":True}
        (output_dir/"run_summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
        return 0
    panel_paths = discover_panel(repo, args.panel_path)
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else repo / "outputs" / "v22" / "V22.LOCAL_ABCDE_EFFECTIVENESS_BACKTEST_R1"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(output_dir / "abcde_backtest.duckdb"))
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='8GB'")
    con.execute(f"PRAGMA temp_directory={qlit(str(output_dir / 'duckdb_temp'))}")

    if all(p.suffix.lower() == ".parquet" for p in panel_paths):
        columns = describe_parquet(con, panel_paths)
    else:
        columns = describe_csv(con, panel_paths[0])

    forward_cols = detect_forward_columns(columns)
    if not forward_cols:
        raise RuntimeError(
            "No forward return columns detected in panel. "
            "Inspect panel_schema.json."
        )

    schema = {
        "panel_paths": [str(p) for p in panel_paths],
        "columns": columns,
        "detected_date": find_exact_or_contains(columns, DATE_CANDIDATES),
        "detected_ticker": find_exact_or_contains(columns, TICKER_CANDIDATES),
        "detected_strategy": find_exact_or_contains(columns, STRATEGY_CANDIDATES),
        "detected_rank": find_exact_or_contains(columns, RANK_CANDIDATES),
        "detected_score": find_exact_or_contains(columns, SCORE_CANDIDATES),
        "detected_forward_returns": forward_cols,
        "detected_wide_strategy_columns": detect_wide_strategy_columns(columns),
    }
    (output_dir / "panel_schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("Loading forward returns...")
    returns, forward_cols = load_forward_returns(
        con, panel_paths, columns, args.start_date, args.end_date
    )
    horizons = sorted(forward_cols)
    returns.to_parquet(output_dir / "deduplicated_forward_returns.parquet", index=False)

    print("Trying to load historical ABCDE ranks from large panel...")
    ranks = load_ranks_from_panel(
        con, panel_paths, columns, args.start_date, args.end_date, args.max_rank
    )
    rank_source = "technical_forward_join_panel"

    if ranks is None or ranks.empty:
        print("No usable strategy ranks in large panel; using archived ranking snapshots...")
        ranking_files = discover_ranking_files(repo)
        ranks = load_ranks_from_snapshots(ranking_files, args.max_rank)
        rank_source = "archived_abcde_ranking_snapshots"

    ranks.to_csv(output_dir / "normalized_historical_ranks.csv", index=False)

    unique_dates = int(ranks["signal_date"].nunique())
    unique_strategies = sorted(ranks["strategy"].dropna().astype(str).unique().tolist())
    topks = sorted({int(x.strip()) for x in args.topk.split(",") if x.strip()})

    print(
        f"rank_source={rank_source}\n"
        f"rank_dates={unique_dates}\n"
        f"strategies={unique_strategies}\n"
        f"forward_horizons={horizons}"
    )

    run_backtest(
        ranks=ranks,
        returns=returns,
        horizons=horizons,
        topks=topks,
        lag_days=args.lag_days,
        cost_bps=args.cost_bps,
        output_dir=output_dir,
    )

    summary = {
        "final_status": "PASS_LOCAL_ABCDE_EFFECTIVENESS_BACKTEST_COMPLETE",
        "rank_source": rank_source,
        "panel_paths": [str(p) for p in panel_paths],
        "start_date": args.start_date,
        "end_date": args.end_date,
        "rank_dates": unique_dates,
        "strategies": unique_strategies,
        "forward_horizons": horizons,
        "topk": topks,
        "lag_days": args.lag_days,
        "cost_bps_one_way": args.cost_bps,
        "output_dir": str(output_dir),
        "warning": (
            "INSUFFICIENT_HISTORICAL_RANK_DATES"
            if unique_dates < 60 else None
        ),
    }
    (output_dir / "run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("")
    print("=== LOCAL ABCDE BACKTEST COMPLETE ===")
    for k, v in summary.items():
        print(f"{k}={v}")
    print("")
    print("Key outputs:")
    print(output_dir / "strategy_performance_summary.csv")
    print(output_dir / "strategy_forward_event_summary.csv")
    print(output_dir / "strategy_rank_ic_summary.csv")
    print(output_dir / "strategy_top20_overlap.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
