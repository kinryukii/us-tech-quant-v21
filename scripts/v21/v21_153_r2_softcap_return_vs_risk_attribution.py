from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.153_R2_SOFTCAP_RETURN_VS_RISK_ATTRIBUTION"
OUT = Path("outputs/v21/V21.153_R2_SOFTCAP_RETURN_VS_RISK_ATTRIBUTION")
V153 = Path("outputs/v21/V21.153_REALIZED_WINDOW_COMPARISON_20260616_TO_LATEST")
V153_R1 = Path("outputs/v21/V21.153_R1_ALL_STRATEGY_SOFTCAP_DELTA_SUMMARY")
V115 = Path("outputs/v21/V21.115_DAILY_TRUE_RECOMPUTE_LEDGER_20260616_TO_20260625/asof_2026-06-16")
E_R1 = Path("outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv")
PRICE = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
START = pd.Timestamp("2026-06-16")
TRANSACTION_COST_BPS = 10.0
SLIPPAGE_BPS = 5.0
ROUND_TRIP_COST = 2 * (TRANSACTION_COST_BPS + SLIPPAGE_BPS) / 10000.0
STRATEGY_FILES = {
    "A1_BASELINE_CONTROL": V115 / "A1_BASELINE_CONTROL_ranking_2026-06-16.csv",
    "B_STATIC_MOMENTUM_BLEND": V115 / "B_STATIC_MOMENTUM_BLEND_ranking_2026-06-16.csv",
    "C_DYNAMIC_MOMENTUM_BLEND": V115 / "C_DYNAMIC_MOMENTUM_BLEND_ranking_2026-06-16.csv",
    "D_WEIGHT_OPTIMIZED_R1": V115 / "D_WEIGHT_OPTIMIZED_R1_ranking_2026-06-16.csv",
    "E_R1_REPAIRED": E_R1,
}
STRATEGIES = list(STRATEGY_FILES)


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


def sf(v):
    if v is None or pd.isna(v):
        return None
    return float(v)


def load_ranking(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    tcol = first_col(df, ["ticker_norm", "ticker", "symbol"])
    rcol = first_col(df, ["rank", "adjusted_rank"])
    df["ticker"] = df[tcol].map(norm)
    df["rank"] = pd.to_numeric(df[rcol], errors="coerce") if rcol else np.arange(1, len(df) + 1)
    return df[df["ticker"].ne("")].drop_duplicates("ticker").sort_values("rank").head(20)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(n, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).rolling(n, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def add_indicators(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("date").copy()
    c = g["adj_close"]
    g["ret1"] = c.pct_change()
    g["ma20"] = c.rolling(20, min_periods=20).mean()
    g["rsi14"] = rsi(c)
    high14 = g["high"].rolling(14, min_periods=14).max()
    low14 = g["low"].rolling(14, min_periods=14).min()
    g["kdj_k"] = 100 * (c - low14) / (high14 - low14).replace(0, np.nan)
    return g.set_index("date", drop=False)


def load_prices(tickers: set[str]) -> tuple[dict[str, pd.DataFrame], list[pd.Timestamp], str]:
    raw = pd.read_csv(PRICE, usecols=lambda c: c in {"symbol", "date", "open", "high", "low", "close", "adjusted_close", "volume"})
    raw["symbol"] = raw["symbol"].map(norm)
    raw = raw[raw["symbol"].isin(set(tickers) | {"QQQ"})].copy()
    raw["date"] = pd.to_datetime(raw["date"])
    for c in ["open", "high", "low", "close", "adjusted_close", "volume"]:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    raw["adj_close"] = raw["adjusted_close"].fillna(raw["close"])
    data = {sym: add_indicators(g.drop(columns=["symbol"])) for sym, g in raw.groupby("symbol")}
    dates = [pd.Timestamp(d) for d in sorted(raw["date"].dropna().unique())]
    latest = str(max(dates).date())
    return data, dates, latest


def row_at(data: dict[str, pd.DataFrame], ticker: str, date: pd.Timestamp) -> pd.Series | None:
    df = data.get(ticker)
    if df is None or date not in df.index:
        return None
    row = df.loc[date]
    return row.iloc[0] if isinstance(row, pd.DataFrame) else row


def overheat(sig: pd.Series | None) -> bool:
    if sig is None:
        return False
    return bool(
        (sf(sig.get("rsi14")) is not None and sig["rsi14"] > 78)
        or (sf(sig.get("kdj_k")) is not None and sig["kdj_k"] > 88)
        or (sf(sig.get("ma20")) not in (None, 0) and sig["adj_close"] / sig["ma20"] - 1 > 0.12)
        or (sf(sig.get("ret1")) is not None and sig["ret1"] > 0.08)
    )


def weights(ranking: pd.DataFrame, data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    df = ranking.copy()
    base_w = 1 / len(df)
    df["original_weight"] = base_w
    df["overheat_flag"] = [overheat(row_at(data, t, START)) for t in df["ticker"]]
    cap = base_w * 0.5
    hot = df["overheat_flag"]
    freed = float((df.loc[hot, "original_weight"] - cap).sum())
    add = freed / int((~hot).sum()) if int((~hot).sum()) else 0.0
    df["final_soft_cap_weight"] = df["original_weight"]
    df.loc[hot, "final_soft_cap_weight"] = cap
    df.loc[~hot, "final_soft_cap_weight"] = df.loc[~hot, "original_weight"] + add
    df["weight_delta"] = df["final_soft_cap_weight"] - df["original_weight"]
    return df


def price_series(data: dict[str, pd.DataFrame], ticker: str, dates: list[pd.Timestamp]) -> pd.Series:
    vals = {}
    for d in dates:
        row = row_at(data, ticker, d)
        vals[d] = np.nan if row is None else row["adj_close"]
    return pd.Series(vals, dtype=float)


def max_drawdown(cum: pd.Series) -> tuple[float, pd.Timestamp | None]:
    if cum.empty:
        return np.nan, None
    dd = cum / cum.cummax() - 1
    return float(dd.min()), dd.idxmin()


def interpret(row: pd.Series) -> str:
    ret = row["return_delta"] > 0
    risk = row["drawdown_delta"] >= 0 or row["p5_delta"] >= 0
    if ret and risk:
        return "RETURN_AND_RISK_IMPROVER"
    if ret:
        return "RETURN_ENHANCER_RISK_MIXED"
    if risk:
        return "DEFENSIVE_ONLY_RETURN_MIXED"
    return "NO_CLEAR_EDGE"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    r1 = pd.read_csv(V153_R1 / "all_strategy_softcap_delta_summary.csv")
    rankings = {s: load_ranking(p) for s, p in STRATEGY_FILES.items() if p.exists()}
    tickers = {t for df in rankings.values() for t in df["ticker"]}
    data, all_dates, latest = load_prices(tickers)
    entry = min(d for d in all_dates if d > START)
    end = pd.Timestamp(latest)
    dates = [d for d in all_dates if entry <= d <= end]
    qqq = price_series(data, "QQQ", dates).pct_change().dropna()
    return_rows, risk_rows, cross_rows = [], [], []
    b_ticker_rows, day_rows, overheated_rows, recipient_rows = [], [], [], []
    drawdown_rows, p5_rows = [], []
    for strategy, ranking in rankings.items():
        w = weights(ranking, data)
        baseline_daily = pd.Series(0.0, index=dates[1:])
        soft_daily = pd.Series(0.0, index=dates[1:])
        ticker_details = []
        for _, h in w.iterrows():
            px = price_series(data, h["ticker"], dates)
            daily = px.pct_change().dropna()
            realized = px.iloc[-1] / px.iloc[0] - 1 - ROUND_TRIP_COST
            base_contrib = h["original_weight"] * realized
            soft_contrib = h["final_soft_cap_weight"] * realized
            baseline_daily = baseline_daily.add(daily * h["original_weight"], fill_value=0.0)
            soft_daily = soft_daily.add(daily * h["final_soft_cap_weight"], fill_value=0.0)
            ticker_details.append(
                {
                    "strategy": strategy,
                    "ticker": h["ticker"],
                    "original_rank": h["rank"],
                    "original_weight": h["original_weight"],
                    "overheat_flag": bool(h["overheat_flag"]),
                    "final_soft_cap_weight": h["final_soft_cap_weight"],
                    "weight_delta": h["weight_delta"],
                    "realized_return": realized,
                    "baseline_contribution": base_contrib,
                    "soft_cap_contribution": soft_contrib,
                    "contribution_delta": soft_contrib - base_contrib,
                    "worst_daily_return": daily.min(),
                    "drawdown_contribution": h["weight_delta"] * daily.min(),
                    "p5_day_contribution": h["weight_delta"] * daily.quantile(0.05),
                }
            )
        baseline_daily.iloc[0] -= ROUND_TRIP_COST
        soft_daily.iloc[0] -= ROUND_TRIP_COST
        delta_daily = soft_daily - baseline_daily
        baseline_cum = (1 + baseline_daily).cumprod()
        soft_cum = (1 + soft_daily).cumprod()
        bdd, bdd_date = max_drawdown(baseline_cum)
        sdd, sdd_date = max_drawdown(soft_cum)
        p5_date = delta_daily.idxmin()
        details = pd.DataFrame(ticker_details)
        capped = details[details["overheat_flag"]]
        recipients = details[~details["overheat_flag"]]
        return_rows.append(
            {
                "strategy": strategy,
                "return_delta": details["contribution_delta"].sum(),
                "capped_overheated_contribution_delta": capped["contribution_delta"].sum(),
                "redistributed_recipient_contribution_delta": recipients["contribution_delta"].sum(),
                "weight_effect": details["contribution_delta"].sum(),
                "selection_holding_return_effect": 0.0,
                "transaction_cost_slippage_effect": 0.0,
                "diagnostic_only": strategy == "E_R1_REPAIRED",
            }
        )
        risk_rows.append(
            {
                "strategy": strategy,
                "softcap_max_drawdown_date": str(sdd_date.date()) if sdd_date is not None else "",
                "baseline_max_drawdown": bdd,
                "softcap_max_drawdown": sdd,
                "drawdown_delta": sdd - bdd,
                "p5_delta": soft_daily.quantile(0.05) - baseline_daily.quantile(0.05),
                "redistributed_recipients_caused_risk_deterioration": bool(recipients["p5_day_contribution"].sum() < capped["p5_day_contribution"].sum()),
                "capped_names_lower_risk_after_cap": bool(capped["p5_day_contribution"].sum() > 0) if len(capped) else False,
                "diagnostic_only": strategy == "E_R1_REPAIRED",
            }
        )
        x = r1[r1["strategy"].eq(strategy)].iloc[0]
        classification = interpret(x)
        cross_rows.append(
            {
                "strategy": strategy,
                "return_delta": x["return_delta"],
                "drawdown_delta": x["drawdown_delta"],
                "p5_delta": x["p5_delta"],
                "source_of_return_improvement": "REDISTRIBUTED_WEIGHT_TO_NON_OVERHEATED_NAMES" if recipients["contribution_delta"].sum() > 0 else "CAPPED_NAMES_LOSS_REDUCTION",
                "source_of_risk_deterioration": "REDISTRIBUTED_WEIGHT_RECIPIENT_DOWNSIDE" if x["p5_delta"] < 0 else "NO_RISK_DETERIORATION_DETECTED",
                "softcap_classification": classification,
                "diagnostic_only": strategy == "E_R1_REPAIRED",
            }
        )
        drawdown_rows.append({"strategy": strategy, "drawdown_date": str(sdd_date.date()) if sdd_date is not None else "", "top_ticker_sources": "|".join(details.sort_values("drawdown_contribution").head(5)["ticker"]), "drawdown_delta": sdd - bdd})
        p5_rows.append({"strategy": strategy, "p5_source_date": str(p5_date.date()), "top_ticker_sources": "|".join(details.sort_values("p5_day_contribution").head(5)["ticker"]), "p5_delta": soft_daily.quantile(0.05) - baseline_daily.quantile(0.05)})
        if strategy == "B_STATIC_MOMENTUM_BLEND":
            for d in dates[1:]:
                day_contrib = []
                for _, h in w.iterrows():
                    px = price_series(data, h["ticker"], dates)
                    dr = px.pct_change().get(d, np.nan)
                    if pd.notna(dr):
                        day_contrib.append((h["ticker"], h["weight_delta"] * dr))
                day_contrib = sorted(day_contrib, key=lambda x: x[1])
                day_rows.append(
                    {
                        "date": str(d.date()),
                        "QQQ_daily_return": qqq.get(d, np.nan),
                        "B_baseline_daily_return": baseline_daily.get(d, np.nan),
                        "B_soft_cap_daily_return": soft_daily.get(d, np.nan),
                        "soft_cap_daily_delta": delta_daily.get(d, np.nan),
                        "QQQ_day_type": "DOWN" if qqq.get(d, 0) < 0 else "UP",
                        "is_choppy_day": abs(qqq.get(d, 0)) > qqq.abs().median(),
                        "top_positive_contribution_tickers": "|".join([t for t, _ in day_contrib[-3:]]),
                        "top_negative_contribution_tickers": "|".join([t for t, _ in day_contrib[:3]]),
                        "soft_cap_improved_day": bool(delta_daily.get(d, 0) > 0),
                    }
                )
            details["interpretation"] = np.select(
                [
                    (details["contribution_delta"] > 0) & (details["p5_day_contribution"] < 0),
                    details["contribution_delta"] > 0,
                    details["p5_day_contribution"] > 0,
                    details["p5_day_contribution"] < 0,
                ],
                ["RETURN_HELPER_RISK_HURTER", "RETURN_HELPER", "RISK_HELPER", "RISK_HURTER"],
                default="NEUTRAL",
            )
            b_ticker_rows = details.to_dict("records")
            overheated_rows.append(
                {
                    "strategy": strategy,
                    "capped_overheated_avg_return": capped["realized_return"].mean(),
                    "non_overheated_avg_return": recipients["realized_return"].mean(),
                    "did_capped_names_underperform_baseline_average": bool(capped["realized_return"].mean() < details["realized_return"].mean()),
                    "did_capped_names_contribute_less_to_losses": bool(capped["p5_day_contribution"].sum() > 0),
                    "did_capped_names_miss_upside": bool(capped["contribution_delta"].sum() < 0),
                    "were_capped_names_source_of_drawdown_p5_risk": bool(capped["p5_day_contribution"].sum() < 0),
                    "did_non_overheated_recipients_generate_most_return_improvement": bool(recipients["contribution_delta"].sum() > abs(capped["contribution_delta"].sum())),
                }
            )
            recipient_rows = recipients.sort_values("contribution_delta", ascending=False).to_dict("records")
    cross = pd.DataFrame(cross_rows)
    if (cross["softcap_classification"] == "RETURN_AND_RISK_IMPROVER").all():
        final_label = "PASS_V21_153_R2_RETURN_AND_RISK_IMPROVER"
        decision = "KEEP_SOFT_CAP_FORWARD_TRACKING_RETURN_SUPPORTIVE"
    elif (cross["return_delta"] > 0).any():
        final_label = "PARTIAL_PASS_V21_153_R2_RETURN_ENHANCER_RISK_MIXED"
        decision = "KEEP_SOFT_CAP_FORWARD_TRACKING_RISK_MIXED"
    elif (cross["drawdown_delta"] >= 0).any() or (cross["p5_delta"] >= 0).any():
        final_label = "PARTIAL_PASS_V21_153_R2_DEFENSIVE_ONLY_RETURN_MIXED"
        decision = "KEEP_DIAGNOSTIC_ONLY"
    else:
        final_label = "FAIL_V21_153_R2_NO_CLEAR_EDGE"
        decision = "REJECT_SOFT_CAP_RECENT_WINDOW_EVIDENCE"
    pd.DataFrame(return_rows).to_csv(OUT / "softcap_return_attribution_by_strategy.csv", index=False)
    pd.DataFrame(risk_rows).to_csv(OUT / "softcap_risk_attribution_by_strategy.csv", index=False)
    pd.DataFrame(b_ticker_rows).to_csv(OUT / "b_softcap_ticker_contribution_detail.csv", index=False)
    pd.DataFrame(day_rows).to_csv(OUT / "b_softcap_day_level_attribution.csv", index=False)
    pd.DataFrame(overheated_rows).to_csv(OUT / "overheated_name_validation.csv", index=False)
    pd.DataFrame(recipient_rows).to_csv(OUT / "redistributed_weight_recipient_audit.csv", index=False)
    pd.DataFrame(drawdown_rows).to_csv(OUT / "drawdown_source_audit.csv", index=False)
    pd.DataFrame(p5_rows).to_csv(OUT / "p5_source_audit.csv", index=False)
    cross.to_csv(OUT / "cross_strategy_softcap_interpretation.csv", index=False)
    b = cross[cross["strategy"].eq("B_STATIC_MOMENTUM_BLEND")].iloc[0]
    report = [
        f"# {STAGE}",
        "",
        f"FINAL_LABEL={final_label}",
        f"DECISION={decision}",
        f"B_classification={b['softcap_classification']}",
        f"B_return_delta={b['return_delta']}",
        f"B_drawdown_delta={b['drawdown_delta']}",
        f"B_p5_delta={b['p5_delta']}",
        "intraday_data_available=false",
        "soft_cap_not_retuned=true",
        "E_R1_diagnostic_only=true",
        "V21.148/V21.149 invalid replay lineage not used as adoption evidence.",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
    ]
    (OUT / "V21.153_R2_SOFTCAP_RETURN_VS_RISK_ATTRIBUTION_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    compact = [
        STAGE,
        f"FINAL_LABEL={final_label}",
        f"DECISION={decision}",
        f"B_classification={b['softcap_classification']}",
        f"B_source_of_return_improvement={b['source_of_return_improvement']}",
        f"B_source_of_risk_deterioration={b['source_of_risk_deterioration']}",
        "E_R1_diagnostic_only=true",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"output directory={str(OUT).replace(chr(92), '/')}",
    ]
    (OUT / "compact_readable_report.txt").write_text("\n".join(compact) + "\n", encoding="utf-8")
    for line in compact:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
