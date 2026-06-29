from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.174_REALISTIC_EXECUTION_BACKTEST_AND_TACTICAL_TRADE_ENGINE_R1"
OUT = ROOT / "outputs" / "v21" / STAGE
PRICE_PATH = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
HORIZONS = {"5D": 5, "10D": 10, "20D": 20}

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
}

SUMMARY_FIELDS = [
    "final_status",
    "decision",
    "latest_price_date_used",
    "ranking_states_loaded",
    "candidate_count",
    "valid_trade_plan_count",
    "filled_trade_count",
    "no_fill_count",
    "invalid_trade_count",
    "stop_loss_count",
    "take_profit_1_count",
    "take_profit_2_count",
    "horizon_exit_count",
    "missed_win_count",
    "missed_loss_count",
    "dram_plan_generated",
    "dram_final_decision",
    "daily_proxy_only",
    "intraday_claim_allowed",
    "research_only",
    "official_adoption_allowed",
    "broker_action_allowed",
    "protected_outputs_modified",
]


@dataclass(frozen=True)
class RankingInput:
    state: str
    path: Path
    frame: pd.DataFrame


def norm(v: Any) -> str:
    if pd.isna(v):
        return ""
    return str(v).strip().upper()


def first_col(df: pd.DataFrame, names: list[str]) -> str | None:
    lower = {c.lower(): c for c in df.columns}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def sf(v: Any) -> float | None:
    if v is None or pd.isna(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def add_atr14(df: pd.DataFrame) -> pd.DataFrame:
    g = df.sort_values("date").copy()
    prev_close = g["close"].shift(1)
    tr = pd.concat(
        [
            g["high"] - g["low"],
            (g["high"] - prev_close).abs(),
            (g["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    g["atr14"] = tr.rolling(14, min_periods=14).mean()
    return g


def normalize_price_panel(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    ticker_col = first_col(raw, ["symbol", "ticker"])
    required = [ticker_col, "date", "open", "high", "low", "close"]
    if ticker_col is None or any(c not in raw.columns for c in required if c is not None):
        return pd.DataFrame()
    cols = [ticker_col, "date", "open", "high", "low", "close"]
    if "adjusted_close" in raw.columns:
        cols.append("adjusted_close")
    work = raw[cols].copy()
    work = work.rename(columns={ticker_col: "ticker"})
    work["ticker"] = work["ticker"].map(norm)
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    for col in ["open", "high", "low", "close", "adjusted_close"]:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    if "adjusted_close" not in work.columns:
        work["adjusted_close"] = work["close"]
    work = work.dropna(subset=["ticker", "date", "open", "high", "low", "close"])
    work = work[work["ticker"].ne("")]
    work = work.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last")
    parts = [add_atr14(g) for _, g in work.groupby("ticker", sort=False)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def load_price_data(path: Path = PRICE_PATH) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], list[pd.Timestamp], str]:
    panel = normalize_price_panel(read_csv(path))
    if panel.empty:
        return panel, {}, [], ""
    dates = [pd.Timestamp(d) for d in sorted(panel["date"].dropna().unique())]
    latest = str(max(dates).date()) if dates else ""
    by_ticker = {t: g.sort_values("date").reset_index(drop=True) for t, g in panel.groupby("ticker")}
    return panel, by_ticker, dates, latest


def latest_candidate_file(patterns: list[str]) -> Path | None:
    candidates: list[Path] = []
    for pat in patterns:
        candidates.extend((ROOT / "outputs" / "v21").rglob(pat))
    files = [p for p in candidates if p.is_file() and p.stat().st_size > 0]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def normalize_ranking(path: Path, state: str) -> pd.DataFrame:
    raw = read_csv(path)
    if raw.empty:
        return pd.DataFrame()
    tcol = first_col(raw, ["ticker", "ticker_norm", "symbol"])
    if tcol is None:
        return pd.DataFrame()
    rcol = first_col(raw, ["rank", "original_rank", "adjusted_rank"])
    dcol = first_col(raw, ["latest_price_date", "latest_price_date_used", "ranking_date", "asof_date"])
    work = raw.copy()
    work["ticker"] = work[tcol].map(norm)
    work["rank"] = pd.to_numeric(work[rcol], errors="coerce") if rcol else np.arange(1, len(work) + 1)
    work["ranking_date"] = (
        str(work[dcol].dropna().astype(str).iloc[0])[:10] if dcol and work[dcol].notna().any() else ""
    )
    work["strategy_state"] = state
    return work[work["ticker"].ne("")].drop_duplicates("ticker").sort_values("rank")


def discover_rankings() -> tuple[dict[str, RankingInput], list[str]]:
    specs = {
        "A1_CONTROL": [
            "*A1_BASELINE_CONTROL*latest_ranking.csv",
            "*A1_BASELINE_CONTROL*true_latest_ranking.csv",
            "*A1_BASELINE_CONTROL*top50*.csv",
        ],
        "C_R2_CHALLENGER": ["*c_r2*r1*shadow_ranking_top50.csv", "*c_r2*shadow_ranking_top50.csv"],
        "AI_BOTTLENECK_THEME": ["*ai_bottleneck_shadow_ranking_top50.csv", "*ai_bottleneck_top20.csv"],
        "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING": [
            "*switch_state_forward_ledger.csv",
            "*forward_tracking*ledger*.csv",
        ],
    }
    loaded: dict[str, RankingInput] = {}
    warnings: list[str] = []
    for state, patterns in specs.items():
        path = latest_candidate_file(patterns)
        if path is None:
            warnings.append(f"WARN_OPTIONAL_RANKING_MISSING:{state}")
            continue
        frame = normalize_ranking(path, state)
        if frame.empty:
            warnings.append(f"WARN_RANKING_UNUSABLE:{state}:{rel(path)}")
            continue
        loaded[state] = RankingInput(state, path, frame)
    return loaded, warnings


def previous_price_row(price: pd.DataFrame, ranking_date: str = "") -> pd.Series | None:
    if price.empty:
        return None
    work = price
    if ranking_date:
        d = pd.to_datetime(ranking_date, errors="coerce")
        if pd.notna(d):
            eligible = price[price["date"] <= d]
            if not eligible.empty:
                work = eligible
    row = work.sort_values("date").tail(1)
    return None if row.empty else row.iloc[0]


def calculate_trade_levels(previous_close: float, atr14: float | None = None) -> dict[str, float]:
    if atr14 is not None and pd.notna(atr14) and atr14 > 0:
        planned_entry = previous_close - 0.35 * atr14
        stop_loss = planned_entry - atr14
    else:
        planned_entry = previous_close * 0.985
        stop_loss = planned_entry * 0.97
    risk_per_share = planned_entry - stop_loss
    take_profit_1 = planned_entry + 1.5 * risk_per_share
    take_profit_2 = planned_entry + 2.5 * risk_per_share
    return {
        "planned_entry": float(planned_entry),
        "no_chase_above": float(previous_close * 1.03),
        "stop_loss": float(stop_loss),
        "take_profit_1": float(take_profit_1),
        "take_profit_2": float(take_profit_2),
        "risk_per_share": float(risk_per_share),
        "reward_risk_to_tp1": float((take_profit_1 - planned_entry) / risk_per_share) if risk_per_share > 0 else np.nan,
    }


def build_trade_plan_row(
    ticker: str,
    strategy_state: str,
    rank: float | int | None,
    ranking_date: str,
    price: pd.DataFrame | None,
) -> dict[str, Any]:
    base = {
        "trade_date": "",
        "ranking_date": ranking_date,
        "ticker": ticker,
        "strategy_state": strategy_state,
        "rank": rank,
        "entry_mode": "DAILY_PROXY_PULLBACK_LIMIT",
        "planned_entry": np.nan,
        "no_chase_above": np.nan,
        "stop_loss": np.nan,
        "take_profit_1": np.nan,
        "take_profit_2": np.nan,
        "risk_per_share": np.nan,
        "reward_risk_to_tp1": np.nan,
        "trade_allowed": False,
        "invalid_reason": "",
        "technical_gate": "DAILY_PROXY_ONLY",
    }
    prev = previous_price_row(price if price is not None else pd.DataFrame(), ranking_date)
    if prev is None:
        base["invalid_reason"] = "INVALID_DATA_MISSING_PRICE"
        return base
    close = sf(prev.get("close"))
    if close is None or close <= 0:
        base["invalid_reason"] = "INVALID_DATA_PREVIOUS_CLOSE_MISSING_OR_NON_POSITIVE"
        return base
    levels = calculate_trade_levels(close, sf(prev.get("atr14")))
    base.update(levels)
    base["ranking_date"] = str(pd.Timestamp(prev["date"]).date())
    base["trade_date"] = ""
    if levels["risk_per_share"] <= 0 or levels["reward_risk_to_tp1"] < 1.2:
        base["invalid_reason"] = "INVALID_RISK_REWARD"
    else:
        base["trade_allowed"] = True
    return base


def next_rows(price: pd.DataFrame, ranking_date: str, horizon_days: int) -> pd.DataFrame:
    if price.empty:
        return pd.DataFrame()
    d = pd.to_datetime(ranking_date, errors="coerce")
    if pd.isna(d):
        return price.sort_values("date").head(horizon_days)
    return price[price["date"] > d].sort_values("date").head(horizon_days)


def find_fill(plan: dict[str, Any], path: pd.DataFrame) -> tuple[pd.Series | None, float | None, str, bool, str]:
    if path.empty:
        return None, None, "NO_FILL", False, "NO_FUTURE_DAILY_BARS"
    entry = float(plan["planned_entry"])
    no_chase = float(plan["no_chase_above"])
    first = path.iloc[0]
    first_gap_no_chase = sf(first.get("open")) is not None and float(first["open"]) > no_chase
    if first_gap_no_chase:
        if len(path) >= 2:
            second = path.iloc[1]
            if float(second["close"]) > float(first["high"]) and float(second["low"]) <= no_chase <= float(second["high"]):
                return second, no_chase, "CONTINUATION_NO_CHASE_ABOVE_FILL", True, ""
        return None, None, "NO_FILL", True, "INVALID_NO_CHASE"
    if float(first["high"]) > no_chase and float(first["low"]) > entry:
        if len(path) >= 2:
            second = path.iloc[1]
            if float(second["close"]) > float(first["high"]) and float(second["low"]) <= no_chase <= float(second["high"]):
                return second, no_chase, "CONTINUATION_NO_CHASE_ABOVE_FILL", True, ""
        return None, None, "NO_FILL", True, "INVALID_NO_CHASE_OR_NO_PULLBACK"
    for _, row in path.iterrows():
        if float(row["low"]) <= entry <= float(row["high"]):
            return row, entry, "PULLBACK_LIMIT_FILL", False, ""
    return None, None, "NO_FILL", False, "PRICE_NEVER_TOUCHED_PLANNED_ENTRY"


def simulate_trade(plan: dict[str, Any], price: pd.DataFrame, horizon_label: str, horizon_days: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    common = {
        "horizon": horizon_label,
        "trade_date": plan.get("trade_date", ""),
        "ranking_date": plan.get("ranking_date", ""),
        "ticker": plan.get("ticker", ""),
        "strategy_state": plan.get("strategy_state", ""),
    }
    audit_rows: list[dict[str, Any]] = []
    if not bool(plan.get("trade_allowed")):
        row = {
            **common,
            "filled": False,
            "fill_date": "",
            "fill_price": np.nan,
            "exit_date": "",
            "exit_price": np.nan,
            "exit_reason": "INVALID",
            "realistic_pnl_pct": np.nan,
            "max_adverse_excursion_pct": np.nan,
            "max_favorable_excursion_pct": np.nan,
            "stop_hit": False,
            "tp1_hit": False,
            "tp2_hit": False,
            "missed_trade": False,
            "missed_reason": plan.get("invalid_reason", "INVALID"),
            "missed_return_pct": np.nan,
        }
        return row, audit_rows
    path = next_rows(price, str(plan["ranking_date"]), horizon_days)
    fill_row, fill_price, fill_mode, missed_trade, missed_reason = find_fill(plan, path)
    if fill_row is None or fill_price is None:
        horizon_close = sf(path.iloc[-1].get("close")) if not path.empty else None
        missed_return = (horizon_close / float(plan["planned_entry"]) - 1.0) if horizon_close else np.nan
        row = {
            **common,
            "filled": False,
            "fill_date": "",
            "fill_price": np.nan,
            "exit_date": "",
            "exit_price": np.nan,
            "exit_reason": "NO_FILL",
            "realistic_pnl_pct": 0.0,
            "max_adverse_excursion_pct": np.nan,
            "max_favorable_excursion_pct": np.nan,
            "stop_hit": False,
            "tp1_hit": False,
            "tp2_hit": False,
            "missed_trade": missed_trade or True,
            "missed_reason": missed_reason,
            "missed_return_pct": missed_return,
        }
        return row, audit_rows
    fill_date = pd.Timestamp(fill_row["date"])
    after_fill = path[path["date"] >= fill_date].sort_values("date")
    stop = float(plan["stop_loss"])
    tp1 = float(plan["take_profit_1"])
    tp2 = float(plan["take_profit_2"])
    exit_price = sf(after_fill.iloc[-1].get("close"))
    exit_date = pd.Timestamp(after_fill.iloc[-1]["date"])
    exit_reason = "HORIZON_EXIT"
    stop_hit = tp1_hit = tp2_hit = False
    lows: list[float] = []
    highs: list[float] = []
    for _, bar in after_fill.iterrows():
        low = float(bar["low"])
        high = float(bar["high"])
        lows.append(low)
        highs.append(high)
        bar_stop = low <= stop
        bar_tp1 = high >= tp1
        bar_tp2 = high >= tp2
        audit_rows.append(
            {
                **common,
                "bar_date": str(pd.Timestamp(bar["date"]).date()),
                "fill_mode": fill_mode,
                "bar_low": low,
                "bar_high": high,
                "stop_loss": stop,
                "take_profit_1": tp1,
                "take_profit_2": tp2,
                "stop_touched": bar_stop,
                "tp1_touched": bar_tp1,
                "tp2_touched": bar_tp2,
                "same_bar_stop_and_tp_touched": bool(bar_stop and (bar_tp1 or bar_tp2)),
                "path_assumption": "STOP_LOSS_FIRST_IF_SAME_DAILY_BAR",
                "technical_gate": "DAILY_PROXY_ONLY",
            }
        )
        if bar_stop:
            stop_hit = True
            exit_price = stop
            exit_date = pd.Timestamp(bar["date"])
            exit_reason = "STOP_LOSS"
            break
        if bar_tp2:
            tp1_hit = True
            tp2_hit = True
            exit_price = tp2
            exit_date = pd.Timestamp(bar["date"])
            exit_reason = "TAKE_PROFIT_2"
            break
        if bar_tp1:
            tp1_hit = True
            exit_price = tp1
            exit_date = pd.Timestamp(bar["date"])
            exit_reason = "TAKE_PROFIT_1"
            break
    mae = min(lows) / fill_price - 1.0 if lows else np.nan
    mfe = max(highs) / fill_price - 1.0 if highs else np.nan
    return {
        **common,
        "filled": True,
        "fill_date": str(fill_date.date()),
        "fill_price": fill_price,
        "exit_date": str(exit_date.date()),
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "realistic_pnl_pct": exit_price / fill_price - 1.0 if exit_price else np.nan,
        "max_adverse_excursion_pct": mae,
        "max_favorable_excursion_pct": mfe,
        "stop_hit": stop_hit,
        "tp1_hit": tp1_hit,
        "tp2_hit": tp2_hit,
        "missed_trade": False,
        "missed_reason": "",
        "missed_return_pct": np.nan,
    }, audit_rows


def classify_missed_trade(sim_row: dict[str, Any], plan_row: dict[str, Any]) -> str:
    reason = str(sim_row.get("missed_reason", ""))
    invalid = str(plan_row.get("invalid_reason", ""))
    if "NO_CHASE" in reason:
        return "INVALID_NO_CHASE"
    if "RISK_REWARD" in invalid:
        return "INVALID_RISK_REWARD"
    if invalid:
        return "INVALID_DATA"
    ret = sf(sim_row.get("missed_return_pct"))
    if ret is None or pd.isna(ret):
        return "MISSED_FLAT"
    if ret > 0.01:
        return "MISSED_WIN"
    if ret < -0.01:
        return "MISSED_LOSS"
    return "MISSED_FLAT"


def build_candidates(rankings: dict[str, RankingInput], prices: dict[str, pd.DataFrame]) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    candidates: list[dict[str, Any]] = []
    for state, inp in rankings.items():
        for _, row in inp.frame.head(20).iterrows():
            ticker = norm(row["ticker"])
            candidates.append(
                {
                    "ticker": ticker,
                    "strategy_state": state,
                    "rank": row.get("rank"),
                    "ranking_date": str(row.get("ranking_date") or ""),
                    "ranking_source": rel(inp.path),
                }
            )
    if "DRAM" not in prices and all(c["ticker"] != "DRAM" for c in candidates):
        warnings.append("WARN_DRAM_PRICE_OR_RANKING_MISSING")
    return candidates, warnings


def generate_dram_plan(rankings: dict[str, RankingInput], prices: dict[str, pd.DataFrame]) -> dict[str, Any]:
    price = prices.get("DRAM")
    ranking_state = ""
    rank = np.nan
    for state, inp in rankings.items():
        hit = inp.frame[inp.frame["ticker"].eq("DRAM")]
        if not hit.empty:
            ranking_state = state
            rank = hit.iloc[0].get("rank")
            break
    if price is None or price.empty:
        return {
            "ticker": "DRAM",
            "ranking_state": ranking_state,
            "rank": rank,
            "latest_close": np.nan,
            "planned_entry": np.nan,
            "no_chase_above": np.nan,
            "stop_loss": np.nan,
            "take_profit_1": np.nan,
            "take_profit_2": np.nan,
            "trade_allowed": False,
            "gate_status": "DATA_MISSING",
            "technical_gate": "DAILY_PROXY_ONLY",
            "market_gate": "DAILY_PROXY_ONLY",
            "final_decision": "DRAM_DATA_MISSING",
        }
    plan = build_trade_plan_row("DRAM", ranking_state or "DRAM_STANDALONE", rank, "", price)
    latest = price.sort_values("date").iloc[-1]
    latest_close = sf(latest.get("close"))
    if not plan["trade_allowed"]:
        decision = "DRAM_INVALID_RISK_REWARD" if "RISK_REWARD" in str(plan["invalid_reason"]) else "DRAM_DATA_MISSING"
    elif latest_close is not None and latest_close > float(plan["no_chase_above"]):
        decision = "DRAM_NO_CHASE"
    elif latest_close is not None and latest_close > float(plan["planned_entry"]):
        decision = "DRAM_WAIT_FOR_PULLBACK"
    else:
        decision = "DRAM_TRADE_ALLOWED_DAILY_PROXY"
    return {
        "ticker": "DRAM",
        "ranking_state": ranking_state,
        "rank": rank,
        "latest_close": latest_close,
        "planned_entry": plan["planned_entry"],
        "no_chase_above": plan["no_chase_above"],
        "stop_loss": plan["stop_loss"],
        "take_profit_1": plan["take_profit_1"],
        "take_profit_2": plan["take_profit_2"],
        "trade_allowed": bool(plan["trade_allowed"]),
        "gate_status": "DAILY_PROXY_ONLY" if plan["trade_allowed"] else plan["invalid_reason"],
        "technical_gate": "DAILY_PROXY_ONLY",
        "market_gate": "DAILY_PROXY_ONLY",
        "final_decision": decision,
    }


def write_report(summary: dict[str, Any], warnings: list[str]) -> None:
    lines = [
        STAGE,
        f"final_status: {summary['final_status']}",
        f"decision: {summary['decision']}",
        f"latest_price_date_used: {summary['latest_price_date_used']}",
        f"ranking_states_loaded: {', '.join(summary['ranking_states_loaded'])}",
        f"candidate_count: {summary['candidate_count']}",
        f"valid_trade_plan_count: {summary['valid_trade_plan_count']}",
        f"filled/no_fill/invalid: {summary['filled_trade_count']} / {summary['no_fill_count']} / {summary['invalid_trade_count']}",
        f"stop/tp1/tp2/horizon: {summary['stop_loss_count']} / {summary['take_profit_1_count']} / {summary['take_profit_2_count']} / {summary['horizon_exit_count']}",
        f"DRAM final decision: {summary['dram_final_decision']}",
        "technical/execution data label: DAILY_PROXY_ONLY",
        "intraday_claim_allowed: False",
        "research_only: True",
        "official_adoption_allowed: False",
        "broker_action_allowed: False",
        "protected_outputs_modified: False",
        "warnings:",
        *([f"- {w}" for w in warnings] if warnings else ["- none"]),
    ]
    (OUT / "V21.174_readable_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def empty_outputs_no_price() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    for name in [
        "execution_trade_plan_ledger.csv",
        "execution_simulation_results.csv",
        "missed_trade_attribution.csv",
        "stop_take_profit_path_audit.csv",
        "dram_tactical_trade_plan_latest.csv",
    ]:
        pd.DataFrame().to_csv(OUT / name, index=False)
    summary = {
        "final_status": "BLOCKED_V21_174_NO_PRICE_DATA",
        "decision": "EXECUTION_ENGINE_BLOCKED_NO_PRICE_DATA",
        "latest_price_date_used": "",
        "ranking_states_loaded": [],
        "candidate_count": 0,
        "valid_trade_plan_count": 0,
        "filled_trade_count": 0,
        "no_fill_count": 0,
        "invalid_trade_count": 0,
        "stop_loss_count": 0,
        "take_profit_1_count": 0,
        "take_profit_2_count": 0,
        "horizon_exit_count": 0,
        "missed_win_count": 0,
        "missed_loss_count": 0,
        "dram_plan_generated": False,
        "dram_final_decision": "DRAM_DATA_MISSING",
        "daily_proxy_only": True,
        "intraday_claim_allowed": False,
        **POLICY,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(OUT),
    }
    (OUT / "V21.174_execution_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_report(summary, ["BLOCKED_V21_174_NO_PRICE_DATA"])
    return summary


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    panel, prices, _dates, latest = load_price_data()
    if panel.empty:
        empty_outputs_no_price()
        return 0
    rankings, warnings = discover_rankings()
    candidates, cand_warnings = build_candidates(rankings, prices)
    warnings.extend(cand_warnings)

    plan_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        plan = build_trade_plan_row(
            candidate["ticker"],
            candidate["strategy_state"],
            candidate["rank"],
            candidate["ranking_date"],
            prices.get(candidate["ticker"]),
        )
        plan["ranking_source"] = candidate["ranking_source"]
        plan_rows.append(plan)
    plan_df = pd.DataFrame(plan_rows)
    if not plan_df.empty:
        for idx, row in plan_df.iterrows():
            path = prices.get(str(row["ticker"]))
            future = next_rows(path if path is not None else pd.DataFrame(), str(row["ranking_date"]), 1)
            if not future.empty:
                plan_df.loc[idx, "trade_date"] = str(pd.Timestamp(future.iloc[0]["date"]).date())
    plan_df.to_csv(OUT / "execution_trade_plan_ledger.csv", index=False)

    sim_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for plan in plan_rows:
        price = prices.get(str(plan["ticker"]), pd.DataFrame())
        for hlabel, hdays in HORIZONS.items():
            sim, audit = simulate_trade(plan, price, hlabel, hdays)
            sim_rows.append(sim)
            audit_rows.extend(audit)
    sim_df = pd.DataFrame(sim_rows)
    sim_df.to_csv(OUT / "execution_simulation_results.csv", index=False)
    pd.DataFrame(audit_rows).to_csv(OUT / "stop_take_profit_path_audit.csv", index=False)

    missed_rows: list[dict[str, Any]] = []
    plan_lookup = {(r["ticker"], r["strategy_state"], str(r["ranking_date"])): r for r in plan_rows}
    for sim in sim_rows:
        if sim.get("exit_reason") == "NO_FILL" or sim.get("exit_reason") == "INVALID":
            key = (sim["ticker"], sim["strategy_state"], str(sim["ranking_date"]))
            plan = plan_lookup.get(key, {})
            classification = classify_missed_trade(sim, plan)
            missed_rows.append({**sim, "missed_classification": classification})
    missed_df = pd.DataFrame(missed_rows)
    missed_df.to_csv(OUT / "missed_trade_attribution.csv", index=False)

    dram = generate_dram_plan(rankings, prices)
    pd.DataFrame([dram]).to_csv(OUT / "dram_tactical_trade_plan_latest.csv", index=False)

    valid_count = int(plan_df["trade_allowed"].sum()) if "trade_allowed" in plan_df.columns else 0
    invalid_count = int((~plan_df["trade_allowed"].astype(bool)).sum()) if "trade_allowed" in plan_df.columns else 0
    filled_count = int(sim_df["filled"].astype(bool).sum()) if "filled" in sim_df.columns else 0
    no_fill_count = int(sim_df["exit_reason"].eq("NO_FILL").sum()) if "exit_reason" in sim_df.columns else 0
    stop_count = int(sim_df["exit_reason"].eq("STOP_LOSS").sum()) if "exit_reason" in sim_df.columns else 0
    tp1_count = int(sim_df["exit_reason"].eq("TAKE_PROFIT_1").sum()) if "exit_reason" in sim_df.columns else 0
    tp2_count = int(sim_df["exit_reason"].eq("TAKE_PROFIT_2").sum()) if "exit_reason" in sim_df.columns else 0
    horizon_count = int(sim_df["exit_reason"].eq("HORIZON_EXIT").sum()) if "exit_reason" in sim_df.columns else 0
    missed_win = int(missed_df.get("missed_classification", pd.Series(dtype=str)).eq("MISSED_WIN").sum())
    missed_loss = int(missed_df.get("missed_classification", pd.Series(dtype=str)).eq("MISSED_LOSS").sum())

    if valid_count > 0 and len(sim_df) > 0:
        final_status = "PARTIAL_PASS_V21_174_DAILY_PROXY_ONLY"
        decision = "EXECUTION_DAILY_PROXY_READY_WAIT_INTRADAY_DATA"
    else:
        final_status = "WARN_V21_174_NO_VALID_TRADE_PLANS"
        decision = "EXECUTION_ENGINE_WARN_NO_VALID_TRADES"
    summary = {
        "final_status": final_status,
        "decision": decision,
        "latest_price_date_used": latest,
        "ranking_states_loaded": sorted(rankings.keys()),
        "candidate_count": len(candidates),
        "valid_trade_plan_count": valid_count,
        "filled_trade_count": filled_count,
        "no_fill_count": no_fill_count,
        "invalid_trade_count": invalid_count,
        "stop_loss_count": stop_count,
        "take_profit_1_count": tp1_count,
        "take_profit_2_count": tp2_count,
        "horizon_exit_count": horizon_count,
        "missed_win_count": missed_win,
        "missed_loss_count": missed_loss,
        "dram_plan_generated": True,
        "dram_final_decision": dram["final_decision"],
        "daily_proxy_only": True,
        "intraday_claim_allowed": False,
        **POLICY,
        "warning_count": len(warnings),
        "warnings": warnings,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(OUT),
    }
    missing = [f for f in SUMMARY_FIELDS if f not in summary]
    if missing:
        raise RuntimeError(f"summary missing required fields: {missing}")
    (OUT / "V21.174_execution_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_report(summary, warnings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
