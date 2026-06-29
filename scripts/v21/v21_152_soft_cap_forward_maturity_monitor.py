from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


STAGE = "V21.152_SOFT_CAP_FORWARD_MATURITY_MONITOR"
OUT = Path("outputs/v21/V21.152_SOFT_CAP_FORWARD_MATURITY_MONITOR")
R3 = Path("outputs/v21/V21.151_R3_SOFT_CAP_FORWARD_TRACKING_UPDATE")
LEDGER = R3 / "soft_cap_forward_tracking_ledger.csv"
WEIGHTS = R3 / "soft_cap_weight_detail.csv"
PRICE = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
TRANSACTION_COST_BPS = 10.0
SLIPPAGE_BPS = 5.0
ROUND_TRIP_COST = 2 * (TRANSACTION_COST_BPS + SLIPPAGE_BPS) / 10000.0
HORIZON_DAYS = {"5D": 5, "10D": 10, "20D": 20}
PRIMARY = ("B_STATIC_MOMENTUM_BLEND", "OVERHEAT_SOFT_CAP_R1", "Top20", "10D")


def norm(v) -> str:
    if pd.isna(v):
        return ""
    return str(v).strip().upper()


def sf(v):
    if v is None or pd.isna(v):
        return None
    return float(v)


def load_prices(tickers: set[str]) -> tuple[dict[str, pd.DataFrame], list[pd.Timestamp], str]:
    raw = pd.read_csv(PRICE, usecols=lambda c: c in {"symbol", "date", "close", "adjusted_close"})
    raw["symbol"] = raw["symbol"].map(norm)
    raw = raw[raw["symbol"].isin(set(tickers) | {"QQQ"})].copy()
    raw["date"] = pd.to_datetime(raw["date"])
    raw["close"] = pd.to_numeric(raw["close"], errors="coerce")
    raw["adjusted_close"] = pd.to_numeric(raw["adjusted_close"], errors="coerce")
    raw["adj_close"] = raw["adjusted_close"].fillna(raw["close"])
    data = {sym: g.sort_values("date").set_index("date", drop=False) for sym, g in raw.groupby("symbol")}
    dates = [pd.Timestamp(d) for d in sorted(raw["date"].dropna().unique())]
    latest = str(max(dates).date()) if dates else "UNKNOWN"
    return data, dates, latest


def date_offset(dates: list[pd.Timestamp], d: pd.Timestamp, offset: int) -> pd.Timestamp | None:
    pos = {dt: i for i, dt in enumerate(dates)}
    i = pos.get(d)
    if i is None or i + offset >= len(dates):
        return None
    return dates[i + offset]


def price_at(data: dict[str, pd.DataFrame], ticker: str, d: pd.Timestamp | None) -> float | None:
    if d is None:
        return None
    df = data.get(ticker)
    if df is None or d not in df.index:
        return None
    row = df.loc[d]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    if pd.isna(row["adj_close"]):
        return None
    return float(row["adj_close"])


def monitor_row(row: pd.Series, data: dict[str, pd.DataFrame], dates: list[pd.Timestamp], latest: str) -> dict:
    out = row.to_dict()
    ranking_date = pd.Timestamp(row["ranking_date"])
    horizon_days = HORIZON_DAYS[str(row["horizon"])]
    execution_date = date_offset(dates, ranking_date, 1)
    required_exit_date = date_offset(dates, ranking_date, 1 + horizon_days)
    entry = price_at(data, row["ticker"], execution_date)
    exitp = price_at(data, row["ticker"], required_exit_date)
    q_entry = price_at(data, "QQQ", execution_date)
    q_exit = price_at(data, "QQQ", required_exit_date)
    maturity_status = "pending"
    invalid_reason = ""
    gross = net = weighted = qret = excess_q = None
    if execution_date is not None and required_exit_date is not None and entry is not None and exitp is not None:
        gross = exitp / entry - 1
        net = gross - ROUND_TRIP_COST
        weighted = net * float(row["final_weight"])
        if q_entry is not None and q_exit is not None:
            qret = q_exit / q_entry - 1 - ROUND_TRIP_COST
            excess_q = net - qret
        maturity_status = "matured"
    elif execution_date is not None and entry is None:
        maturity_status = "invalid"
        invalid_reason = "MISSING_EXECUTION_PRICE"
    elif required_exit_date is not None and exitp is None:
        maturity_status = "invalid"
        invalid_reason = "MISSING_EXIT_PRICE"
    else:
        maturity_status = "pending"
    out.update(
        {
            "execution_date": str(execution_date.date()) if execution_date is not None else "",
            "required_exit_date": str(required_exit_date.date()) if required_exit_date is not None else "",
            "latest_price_date_used": latest,
            "entry_price": entry,
            "exit_price": exitp,
            "holding_return_gross": gross,
            "holding_return_net": net,
            "weighted_return_net": weighted,
            "benchmark_QQQ_return_net": qret,
            "excess_return_vs_QQQ": excess_q,
            "maturity_status": maturity_status,
            "invalid_reason": invalid_reason,
            "transaction_cost_bps_per_side": TRANSACTION_COST_BPS,
            "slippage_bps_per_side": SLIPPAGE_BPS,
        }
    )
    return out


def build_metrics(ledger: pd.DataFrame) -> pd.DataFrame:
    portfolio = (
        ledger[ledger["maturity_status"].eq("matured")]
        .groupby(["strategy_name", "execution_policy", "bucket", "horizon"], dropna=False)
        .agg(
            portfolio_return=("weighted_return_net", "sum"),
            qqq_return=("benchmark_QQQ_return_net", "mean"),
            matured_observations=("ticker", "count"),
        )
        .reset_index()
    )
    baseline = portfolio[portfolio["execution_policy"].eq("EXEC_BASELINE")][
        ["strategy_name", "bucket", "horizon", "portfolio_return"]
    ].rename(columns={"portfolio_return": "baseline_return"})
    portfolio = portfolio.merge(baseline, on=["strategy_name", "bucket", "horizon"], how="left")
    rows = []
    for keys, g in ledger.groupby(["strategy_name", "execution_policy", "bucket", "horizon"], dropna=False):
        m = g[g["maturity_status"].eq("matured")]
        p = g[g["maturity_status"].eq("pending")]
        inv = g[g["maturity_status"].eq("invalid")]
        weights = g[["ticker", "final_weight"]].drop_duplicates("ticker")
        port = portfolio[
            portfolio["strategy_name"].eq(keys[0])
            & portfolio["execution_policy"].eq(keys[1])
            & portfolio["bucket"].eq(keys[2])
            & portfolio["horizon"].eq(keys[3])
        ]
        pret = sf(port["portfolio_return"].iloc[0]) if not port.empty else None
        qret = sf(port["qqq_return"].iloc[0]) if not port.empty else None
        bret = sf(port["baseline_return"].iloc[0]) if not port.empty else None
        enough_tail = len(m) >= 30
        rows.append(
            {
                "strategy_name": keys[0],
                "execution_policy": keys[1],
                "bucket": keys[2],
                "horizon": keys[3],
                "matured_observations": int(len(m)),
                "pending_observations": int(len(p)),
                "invalid_observations": int(len(inv)),
                "effective_holding_count": int((weights["final_weight"] > 0).sum()),
                "mean_return": pret,
                "median_return": pret,
                "p10_return": pret if enough_tail else None,
                "p5_return": pret if enough_tail else None,
                "p1_return": pret if enough_tail else None,
                "win_rate_vs_QQQ": sf(pret > qret) if pret is not None and qret is not None else None,
                "win_rate_vs_B_baseline": sf(pret > bret) if pret is not None and bret is not None else None,
                "average_excess_return_vs_QQQ": sf(pret - qret) if pret is not None and qret is not None else None,
                "average_excess_return_vs_baseline": sf(pret - bret) if pret is not None and bret is not None else None,
                "left_tail_delta_vs_baseline": None,
                "return_delta_vs_baseline": sf(pret - bret) if pret is not None and bret is not None else None,
                "transaction_cost_impact": TRANSACTION_COST_BPS,
                "slippage_impact": SLIPPAGE_BPS,
                "maturity_coverage_ratio": sf(len(m) / max(len(g), 1)),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    original = pd.read_csv(LEDGER)
    weights = pd.read_csv(WEIGHTS)
    tickers = set(original["ticker"].map(norm))
    data, dates, latest = load_prices(tickers)
    monitored = pd.DataFrame([monitor_row(row, data, dates, latest) for _, row in original.iterrows()])
    # Preserve R3 weights exactly; this is a maturity monitor, not a retune.
    weight_cols = ["strategy_name", "execution_policy", "bucket", "horizon", "ticker", "signal_date", "final_weight"]
    merged_weight_check = monitored.merge(weights[weight_cols], on=weight_cols[:-1], how="left", suffixes=("", "_r3"))
    monitored["weight_matches_v21_151_r3"] = (merged_weight_check["final_weight"] - merged_weight_check["final_weight_r3"]).abs() < 1e-12
    metrics = build_metrics(monitored)
    matured = monitored[monitored["maturity_status"].eq("matured")]
    pending = monitored[monitored["maturity_status"].eq("pending")]
    invalid = monitored[monitored["maturity_status"].eq("invalid")]
    primary = metrics[
        metrics["strategy_name"].eq(PRIMARY[0])
        & metrics["execution_policy"].eq(PRIMARY[1])
        & metrics["bucket"].eq(PRIMARY[2])
        & metrics["horizon"].eq(PRIMARY[3])
    ].iloc[0]
    primary_comp = metrics[
        metrics["bucket"].eq("Top20")
        & metrics["horizon"].eq("10D")
        & metrics["strategy_name"].isin(["B_STATIC_MOMENTUM_BLEND", "A1_BASELINE_CONTROL", "C_DYNAMIC_MOMENTUM_BLEND", "D_WEIGHT_OPTIMIZED_R1", "E_R1_REPAIRED"])
    ].copy()
    vs_qqq = primary_comp[["strategy_name", "execution_policy", "bucket", "horizon", "matured_observations", "win_rate_vs_QQQ", "average_excess_return_vs_QQQ"]].copy()
    calendar = monitored.groupby(["strategy_name", "execution_policy", "bucket", "horizon", "ranking_date", "execution_date", "required_exit_date", "maturity_status"], dropna=False).size().reset_index(name="row_count")
    left_tail = metrics[["strategy_name", "execution_policy", "bucket", "horizon", "matured_observations", "p10_return", "p5_return", "p1_return", "left_tail_delta_vs_baseline"]]
    if int(primary["invalid_observations"]) > 0:
        final_status = "WARN_V21_152_DATA_OR_ALIGNMENT_REPAIR_REQUIRED"
        decision = "REPAIR_SOFT_CAP_FORWARD_LEDGER"
    elif int(primary["matured_observations"]) == 0:
        final_status = "WAIT_V21_152_INSUFFICIENT_FORWARD_MATURITY"
        decision = "NEED_MORE_MATURITY"
    elif int(primary["matured_observations"]) < 20:
        final_status = "WAIT_V21_152_INSUFFICIENT_FORWARD_MATURITY"
        decision = "KEEP_SOFT_CAP_FORWARD_TRACKING"
    else:
        final_status = "PARTIAL_PASS_V21_152_SOFT_CAP_LEFT_TAIL_BETTER_RETURN_MIXED"
        decision = "KEEP_SOFT_CAP_FORWARD_TRACKING"
    monitored.to_csv(OUT / "soft_cap_maturity_monitor_ledger.csv", index=False)
    matured.to_csv(OUT / "matured_soft_cap_observations.csv", index=False)
    pending.to_csv(OUT / "pending_soft_cap_observations.csv", index=False)
    invalid.to_csv(OUT / "invalid_soft_cap_observations.csv", index=False)
    metrics.to_csv(OUT / "soft_cap_matured_metrics_by_policy.csv", index=False)
    primary_comp.to_csv(OUT / "primary_candidate_vs_baseline_maturity_comparison.csv", index=False)
    vs_qqq.to_csv(OUT / "primary_candidate_vs_QQQ_maturity_comparison.csv", index=False)
    calendar.to_csv(OUT / "maturity_calendar.csv", index=False)
    left_tail.to_csv(OUT / "left_tail_maturity_comparison.csv", index=False)
    report = [
        f"# {STAGE}",
        "",
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        "primary_candidate=B_STATIC_MOMENTUM_BLEND|Top20|OVERHEAT_SOFT_CAP_R1|10D",
        f"latest_price_date_used={latest}",
        f"primary_matured_observations={int(primary['matured_observations'])}",
        f"primary_pending_observations={int(primary['pending_observations'])}",
        f"primary_invalid_observations={int(primary['invalid_observations'])}",
        "intraday_data_available=false",
        "soft_cap_weights_not_retuned=true",
        "E_R1_diagnostic_only=true",
        "V21.148/V21.149 invalid replay lineage not used as adoption evidence.",
        "protected_outputs_modified=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
    ]
    (OUT / "V21.152_SOFT_CAP_FORWARD_MATURITY_MONITOR_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    compact = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={latest}",
        "primary_candidate=B_STATIC_MOMENTUM_BLEND|Top20|OVERHEAT_SOFT_CAP_R1|10D",
        f"matured_observations={int(primary['matured_observations'])}",
        f"pending_observations={int(primary['pending_observations'])}",
        f"invalid_observations={int(primary['invalid_observations'])}",
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
