from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020"
OUT = Path("outputs/v21/V21.140_EXTEND_HISTORICAL_PRICE_PANEL_TO_2020")
START_DATE = pd.Timestamp("2020-01-01")
CANONICAL = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
LOCAL_CACHE = Path("state/v18/price_cache")
REGISTRY = Path("outputs/v21/V21.139_MULTI_STRATEGY_RANDOM_ASOF_BACKTEST/V21.139_strategy_registry_used.csv")
BENCHMARKS = ["QQQ", "SOXX", "SPY", "SMH", "XLK"]

CONTROL_FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
}


def norm_ticker(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().upper()


def first_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lower = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_hash(row: pd.Series) -> str:
    fields = [
        row.get("symbol", ""),
        row.get("date", ""),
        row.get("open", ""),
        row.get("high", ""),
        row.get("low", ""),
        row.get("close", ""),
        row.get("adjusted_close", ""),
        row.get("volume", ""),
        row.get("source_provider", ""),
        row.get("source_artifact", ""),
    ]
    return hashlib.sha256("|".join(map(str, fields)).encode("utf-8")).hexdigest()


def discover_universe() -> tuple[list[str], list[dict]]:
    tickers: set[str] = set(BENCHMARKS)
    source_rows: list[dict] = []
    if REGISTRY.exists():
        registry = pd.read_csv(REGISTRY)
        for _, reg in registry.iterrows():
            path = Path(str(reg.get("source_path", "")))
            if not path.exists():
                continue
            try:
                df = pd.read_csv(path)
            except Exception as exc:  # noqa: BLE001
                source_rows.append({
                    "source_path": str(path).replace("\\", "/"),
                    "source_type": "strategy_ranking",
                    "read_status": "READ_FAILED",
                    "warning": str(exc),
                    "ticker_count": 0,
                })
                continue
            tcol = first_col(df, ["ticker_norm", "ticker", "symbol"])
            if tcol is None:
                source_rows.append({
                    "source_path": str(path).replace("\\", "/"),
                    "source_type": "strategy_ranking",
                    "read_status": "NO_TICKER_COLUMN",
                    "warning": "ticker column not detected",
                    "ticker_count": 0,
                })
                continue
            values = sorted({norm_ticker(v) for v in df[tcol] if norm_ticker(v)})
            tickers.update(values)
            source_rows.append({
                "source_path": str(path).replace("\\", "/"),
                "source_type": "strategy_ranking",
                "read_status": "READ_OK",
                "warning": "",
                "ticker_count": len(values),
            })
    for benchmark in BENCHMARKS:
        source_rows.append({
            "source_path": "REQUIRED_BENCHMARK",
            "source_type": "benchmark",
            "read_status": "INCLUDED",
            "warning": "",
            "ticker_count": 1,
            "ticker": benchmark,
        })
    return sorted(tickers), source_rows


def normalize_price_frame(df: pd.DataFrame, source_provider: str, source_artifact: str, source_priority: int) -> pd.DataFrame:
    symbol_col = first_col(df, ["symbol", "ticker"])
    date_col = first_col(df, ["date", "price_date"])
    if symbol_col is None or date_col is None:
        return pd.DataFrame()
    out = pd.DataFrame()
    out["symbol"] = df[symbol_col].map(norm_ticker)
    out["date"] = pd.to_datetime(df[date_col], errors="coerce")
    for dst, candidates in {
        "open": ["open", "Open"],
        "high": ["high", "High"],
        "low": ["low", "Low"],
        "close": ["close", "Close"],
        "adjusted_close": ["adjusted_close", "adj_close", "Adj Close"],
        "volume": ["volume", "Volume"],
    }.items():
        col = first_col(df, candidates)
        out[dst] = pd.to_numeric(df[col], errors="coerce") if col else np.nan
    if out["adjusted_close"].isna().all() and out["close"].notna().any():
        out["adjusted_close"] = out["close"]
    out["source_provider"] = source_provider
    out["source_artifact"] = source_artifact
    out["refresh_timestamp"] = df[first_col(df, ["refresh_timestamp", "updated_at"])].astype(str) if first_col(df, ["refresh_timestamp", "updated_at"]) else ""
    out["price_row_status"] = "RESEARCH_EXTENDED_OBSERVED_OHLCV"
    out["source_priority"] = source_priority
    out = out[(out["symbol"] != "") & out["date"].notna() & (out["date"] >= START_DATE)].copy()
    return out


def load_extended_panel(tickers: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    source_audit: list[dict] = []
    ticker_set = set(tickers)
    if LOCAL_CACHE.exists():
        for ticker in tickers:
            path = LOCAL_CACHE / f"{ticker}.csv"
            if not path.exists():
                source_audit.append({
                    "ticker": ticker,
                    "source_path": str(path).replace("\\", "/"),
                    "source_provider": "LOCAL_V18_PRICE_CACHE",
                    "source_used": False,
                    "row_count": 0,
                    "first_date": "",
                    "last_date": "",
                    "file_hash": "",
                    "warning": "LOCAL_CACHE_FILE_MISSING",
                })
                continue
            df = pd.read_csv(path)
            norm = normalize_price_frame(df.assign(ticker=ticker), "LOCAL_V18_PRICE_CACHE", str(path).replace("\\", "/"), 1)
            frames.append(norm)
            source_audit.append({
                "ticker": ticker,
                "source_path": str(path).replace("\\", "/"),
                "source_provider": "LOCAL_V18_PRICE_CACHE",
                "source_used": True,
                "row_count": int(len(norm)),
                "first_date": "" if norm.empty else str(norm["date"].min().date()),
                "last_date": "" if norm.empty else str(norm["date"].max().date()),
                "file_hash": file_hash(path),
                "warning": "",
            })
    if CANONICAL.exists():
        canon = pd.read_csv(CANONICAL)
        norm = normalize_price_frame(canon, "V20_199D_CANONICAL_READ_ONLY", str(CANONICAL).replace("\\", "/"), 2)
        norm = norm[norm["symbol"].isin(ticker_set)].copy()
        frames.append(norm)
        for ticker, group in norm.groupby("symbol"):
            source_audit.append({
                "ticker": ticker,
                "source_path": str(CANONICAL).replace("\\", "/"),
                "source_provider": "V20_199D_CANONICAL_READ_ONLY",
                "source_used": True,
                "row_count": int(len(group)),
                "first_date": str(group["date"].min().date()),
                "last_date": str(group["date"].max().date()),
                "file_hash": file_hash(CANONICAL),
                "warning": "READ_ONLY_OVERLAY_CANONICAL_PRIORITY_ON_DUPLICATE_DATES",
            })
    panel = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if panel.empty:
        return panel, pd.DataFrame(source_audit)
    panel = panel.sort_values(["symbol", "date", "source_priority"]).drop_duplicates(["symbol", "date"], keep="last")
    panel = panel.sort_values(["symbol", "date"]).reset_index(drop=True)
    panel["date"] = panel["date"].dt.strftime("%Y-%m-%d")
    panel["row_hash"] = panel.apply(row_hash, axis=1)
    panel = panel[
        [
            "symbol",
            "date",
            "open",
            "high",
            "low",
            "close",
            "adjusted_close",
            "volume",
            "source_provider",
            "source_artifact",
            "refresh_timestamp",
            "row_hash",
            "price_row_status",
        ]
    ]
    return panel, pd.DataFrame(source_audit)


def longest_missing_gap(dates: pd.Series, expected_dates: pd.DatetimeIndex) -> int:
    have = set(pd.to_datetime(dates).dt.normalize())
    longest = current = 0
    for d in expected_dates:
        if d.normalize() in have:
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return int(longest)


def build_coverage(panel: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame()
    work = panel.copy()
    work["date"] = pd.to_datetime(work["date"])
    latest = work["date"].max()
    benchmark_dates = work[work["symbol"].isin(["SPY", "QQQ"])]["date"].drop_duplicates().sort_values()
    expected = pd.DatetimeIndex(benchmark_dates)
    if expected.empty:
        expected = pd.bdate_range(START_DATE, latest)
    rows = []
    for ticker in tickers:
        g = work[work["symbol"].eq(ticker)].copy()
        first = g["date"].min() if not g.empty else pd.NaT
        last = g["date"].max() if not g.empty else pd.NaT
        available = int(g["date"].nunique()) if not g.empty else 0
        expected_count = int(len(expected))
        raw_coverage = available / expected_count if expected_count else 0.0
        coverage = min(raw_coverage, 1.0)
        missing = max(expected_count - available, 0)
        years = {year: bool((g["date"].dt.year == year).any()) if not g.empty else False for year in range(2020, 2027)}
        first_str = "" if pd.isna(first) else str(first.date())
        last_str = "" if pd.isna(last) else str(last.date())
        no_data_before_2021 = pd.isna(first) or first > pd.Timestamp("2020-12-31")
        no_data_before_2022 = pd.isna(first) or first > pd.Timestamp("2021-12-31")
        no_data_before_2023 = pd.isna(first) or first > pd.Timestamp("2022-12-31")
        latest_stale = pd.isna(last) or last < latest
        longest_gap = longest_missing_gap(g["date"], expected) if not g.empty else expected_count
        missing_adjusted_close = bool(g["adjusted_close"].isna().any()) if not g.empty else True
        warning_flags = []
        if no_data_before_2023:
            warning_flags.append("NO_DATA_BEFORE_2023")
        if no_data_before_2022:
            warning_flags.append("NO_DATA_BEFORE_2022")
        if no_data_before_2021:
            warning_flags.append("NO_DATA_BEFORE_2021")
        if missing_adjusted_close:
            warning_flags.append("MISSING_ADJUSTED_CLOSE")
        if latest_stale:
            warning_flags.append("STALE_LATEST_DATE")
        if longest_gap > 10:
            warning_flags.append("LARGE_MISSING_GAP")
        if pd.notna(first) and first > START_DATE + pd.Timedelta(days=120):
            warning_flags.append("IPO_AFTER_2020_OR_LOCAL_HISTORY_START_RISK")
        if ticker in BENCHMARKS and (g.empty or latest_stale):
            warning_flags.append("BENCHMARK_MISSING_OR_STALE")
        rows.append({
            "symbol": ticker,
            "first_available_date": first_str,
            "last_available_date": last_str,
            "expected_trading_days": expected_count,
            "available_trading_days": available,
            "coverage_ratio": coverage,
            "missing_day_count": missing,
            "longest_missing_gap": longest_gap,
            "has_2020_data": years[2020],
            "has_2021_data": years[2021],
            "has_2022_data": years[2022],
            "has_2023_data": years[2023],
            "has_2024_data": years[2024],
            "has_2025_data": years[2025],
            "has_2026_data": years[2026],
            "usable_for_5D": available >= 6 and not latest_stale,
            "usable_for_10D": available >= 11 and not latest_stale,
            "usable_for_20D": available >= 21 and not latest_stale,
            "usable_for_random_backtest_2020_plus": coverage >= 0.70 and years[2021] and years[2022] and not latest_stale,
            "no_data_before_2023": no_data_before_2023,
            "no_data_before_2022": no_data_before_2022,
            "no_data_before_2021": no_data_before_2021,
            "missing_adjusted_close": missing_adjusted_close,
            "stale_latest_date": latest_stale,
            "large_missing_gaps": longest_gap > 10,
            "ticker_symbol_change_risk": "UNKNOWN_CURRENT_UNIVERSE_ONLY",
            "delisting_survivorship_risk": "CURRENT_UNIVERSE_ONLY_MISSING_DELISTED_TICKERS",
            "ipo_after_2020": bool(pd.notna(first) and first > START_DATE + pd.Timedelta(days=120)),
            "benchmark_missing_data": ticker in BENCHMARKS and (g.empty or latest_stale),
            "warning_flags": "|".join(warning_flags) if warning_flags else "NONE",
        })
    return pd.DataFrame(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tickers, registry_sources = discover_universe()
    panel, source_audit = load_extended_panel(tickers)
    if panel.empty:
        raise SystemExit("No usable local price data found")

    coverage = build_coverage(panel, tickers)
    latest_price_date = str(pd.to_datetime(panel["date"]).max().date())
    adj = panel.pivot_table(index="date", columns="symbol", values="adjusted_close", aggfunc="last").reset_index()
    missing = coverage[coverage["warning_flags"].ne("NONE")].copy()
    delist = coverage[coverage["delisting_survivorship_risk"].ne("")][
        ["symbol", "ticker_symbol_change_risk", "delisting_survivorship_risk", "ipo_after_2020", "first_available_date", "warning_flags"]
    ].copy()
    bench = coverage[coverage["symbol"].isin(BENCHMARKS)].copy()
    source_audit = pd.concat([source_audit, pd.DataFrame(registry_sources)], ignore_index=True, sort=False)

    ticker_rows = coverage[~coverage["symbol"].isin(BENCHMARKS)]
    back_to_2020 = ticker_rows["first_available_date"].ne("") & (pd.to_datetime(ticker_rows["first_available_date"]) <= pd.Timestamp("2020-01-31"))
    enough_after_2021 = ticker_rows["usable_for_random_backtest_2020_plus"]
    strict_2020_ratio = float(back_to_2020.mean()) if len(ticker_rows) else 0.0
    usable_ratio = float(enough_after_2021.mean()) if len(ticker_rows) else 0.0
    median_coverage = float(ticker_rows["coverage_ratio"].median()) if len(ticker_rows) else 0.0
    benchmark_ok = bool(bench["usable_for_20D"].all()) if not bench.empty else False

    if strict_2020_ratio >= 0.85:
        final_status = "PASS_V21_140_EXTENDED_PRICE_PANEL_READY_WITH_SURVIVORSHIP_WARN"
        decision = "EXTENDED_PRICE_PANEL_READY_FOR_DIAGNOSTIC_RANDOM_RETEST"
    elif usable_ratio >= 0.70:
        final_status = "PARTIAL_PASS_V21_140_EXTENDED_PRICE_PANEL_PARTIAL_COVERAGE"
        decision = "EXTENDED_RANDOM_RETEST_ALLOWED_DIAGNOSTIC_ONLY_WITH_COVERAGE_WARN"
    else:
        final_status = "BLOCKED_V21_140_EXTENDED_PRICE_PANEL_INSUFFICIENT"
        decision = "DO_NOT_RERUN_EXTENDED_RANDOM_BACKTEST"

    summary = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "start_date": "2020-01-01",
        "latest_price_date_used": latest_price_date,
        "ticker_count": int(len(tickers)),
        "strategy_ticker_count": int(len(ticker_rows)),
        "tickers_with_2020_data": int(ticker_rows["has_2020_data"].sum()),
        "tickers_without_2020_data": int((~ticker_rows["has_2020_data"]).sum()),
        "strict_2020_01_coverage_ratio": strict_2020_ratio,
        "usable_after_2021_coverage_ratio": usable_ratio,
        "coverage_ratio_median": median_coverage,
        "benchmark_coverage_ok": benchmark_ok,
        "survivorship_bias_warning": "CURRENT_UNIVERSE_ONLY_SURVIVORSHIP_BIAS;MISSING_HISTORICAL_UNIVERSE_MEMBERSHIP;MISSING_DELISTED_TICKERS",
        "pit_strict_possible_from_price_only": False,
        "source_method": "LOCAL_V18_PRICE_CACHE_PLUS_READ_ONLY_V20_199D_CANONICAL_OVERLAY_NO_WEB_FETCH",
        "output_directory": str(OUT).replace("\\", "/"),
        **CONTROL_FLAGS,
    }

    panel.to_csv(OUT / "V21.140_extended_ohlcv_panel_2020_plus.csv", index=False)
    adj.to_csv(OUT / "V21.140_extended_adjusted_close_panel_2020_plus.csv", index=False)
    coverage.to_csv(OUT / "V21.140_price_coverage_by_ticker.csv", index=False)
    missing.to_csv(OUT / "V21.140_missing_data_report.csv", index=False)
    delist.to_csv(OUT / "V21.140_delisting_and_symbol_warning_report.csv", index=False)
    bench.to_csv(OUT / "V21.140_benchmark_coverage_report.csv", index=False)
    source_audit.to_csv(OUT / "V21.140_data_source_audit.csv", index=False)
    with (OUT / "V21.140_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, allow_nan=False)

    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        "start_date=2020-01-01",
        f"latest_price_date_used={latest_price_date}",
        f"ticker_count={len(tickers)}",
        f"tickers_with_2020_data={summary['tickers_with_2020_data']}",
        f"tickers_without_2020_data={summary['tickers_without_2020_data']}",
        f"coverage_ratio_median={median_coverage}",
        f"benchmark_coverage_ok={str(benchmark_ok).lower()}",
        f"source_method={summary['source_method']}",
        "survivorship_bias_warning=CURRENT_UNIVERSE_ONLY_SURVIVORSHIP_BIAS;MISSING_HISTORICAL_UNIVERSE_MEMBERSHIP;MISSING_DELISTED_TICKERS",
        "pit_strict_possible_from_price_only=false",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
    ]
    (OUT / "V21.140_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    print(STAGE)
    print(f"FINAL_STATUS={final_status}")
    print(f"DECISION={decision}")
    print("start_date=2020-01-01")
    print(f"latest_price_date_used={latest_price_date}")
    print(f"ticker_count={len(tickers)}")
    print(f"tickers_with_2020_data={summary['tickers_with_2020_data']}")
    print(f"tickers_without_2020_data={summary['tickers_without_2020_data']}")
    print(f"coverage_ratio_median={median_coverage}")
    print(f"benchmark_coverage_ok={str(benchmark_ok).lower()}")
    print("survivorship_bias_warning=CURRENT_UNIVERSE_ONLY_SURVIVORSHIP_BIAS")
    print("pit_strict_possible_from_price_only=false")
    print(f"output directory={str(OUT).replace(chr(92), '/')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
