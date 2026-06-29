from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.errors import EmptyDataError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.v21 import v21_176_daily_dram_premarket_trade_plan_r1 as v176


STAGE = "V21.177_DAILY_DRAM_PLAN_LEDGER_AND_STALENESS_GATE_R1"
OUT = ROOT / "outputs" / "v21" / STAGE
V176_OUT = ROOT / "outputs" / "v21" / "V21.176_DAILY_DRAM_PREMARKET_TRADE_PLAN_R1"
PLAN_PATH = V176_OUT / "dram_daily_premarket_trade_plan_latest.csv"
SUMMARY_176_PATH = V176_OUT / "V21.176_daily_dram_summary.json"
DAILY_PRICE_PATH = ROOT / "outputs" / "v21" / "V21.174_R1C_AUTO_DRAM_PRICE_FETCH_AND_CACHE" / "dram_auto_price_bridge_daily_ohlcv.csv"
LEDGER_PATH = OUT / "dram_daily_plan_ledger.csv"
PRICE_PATH = v176.PRICE_PATH

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "canonical_price_panel_modified": False,
    "daily_frequency_only": True,
    "intraday_required": False,
}

LEDGER_COLUMNS = [
    "ledger_id",
    "run_timestamp",
    "plan_date",
    "target_trade_session",
    "ticker",
    "latest_close",
    "setup_classification",
    "final_decision",
    "position_mode",
    "planned_entry_base",
    "planned_entry_conservative",
    "no_chase_above",
    "stop_loss_base",
    "stop_loss_tight",
    "take_profit_1_base",
    "take_profit_2_base",
    "trade_allowed_daily_plan",
    "trade_allowed_current",
    "staleness_status",
    "invalid_reason",
    "next_required_condition",
    "daily_frequency_only",
    "intraday_required",
    "source_stage",
    "research_only",
    "broker_action_allowed",
    "official_adoption_allowed",
]
DEDUP_COLS = ["plan_date", "final_decision", "planned_entry_base", "no_chase_above", "stop_loss_base"]


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def sha(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_plan(path: Path = PLAN_PATH) -> pd.DataFrame:
    df = read_csv(path)
    if df.empty or "ticker" not in df.columns:
        return pd.DataFrame()
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    return df[df["ticker"].eq("DRAM")].tail(1).reset_index(drop=True)


def load_prices(path: Path = DAILY_PRICE_PATH) -> pd.DataFrame:
    return v176.load_daily(path)


def staleness_status(latest_price_date: str, run_date: pd.Timestamp | None = None) -> str:
    if not latest_price_date:
        return "STALE_BLOCK"
    run = (run_date or pd.Timestamp.now(tz=None)).normalize()
    latest = pd.to_datetime(latest_price_date, errors="coerce")
    if pd.isna(latest):
        return "STALE_BLOCK"
    age_days = int((run - latest.normalize()).days)
    if age_days > 7:
        return "STALE_BLOCK"
    if age_days > 3:
        return "STALE_WARN"
    return "CURRENT_OR_RECENT"


def boolish(v: Any) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes"}


def build_ledger_row(plan: pd.Series, latest_price_date: str, stale: str, run_ts: str, ledger_id: str) -> dict[str, Any]:
    allowed_plan = boolish(plan.get("trade_allowed_daily_plan", False))
    trade_allowed_current = bool(allowed_plan and stale != "STALE_BLOCK")
    return {
        "ledger_id": ledger_id,
        "run_timestamp": run_ts,
        "plan_date": str(plan.get("plan_date", "")),
        "target_trade_session": plan.get("target_trade_session", ""),
        "ticker": "DRAM",
        "latest_close": plan.get("latest_close", np.nan),
        "setup_classification": plan.get("setup_classification", ""),
        "final_decision": plan.get("final_decision", ""),
        "position_mode": plan.get("position_mode", ""),
        "planned_entry_base": plan.get("planned_entry_base", np.nan),
        "planned_entry_conservative": plan.get("planned_entry_conservative", np.nan),
        "no_chase_above": plan.get("no_chase_above", np.nan),
        "stop_loss_base": plan.get("stop_loss_base", np.nan),
        "stop_loss_tight": plan.get("stop_loss_tight", np.nan),
        "take_profit_1_base": plan.get("take_profit_1_base", np.nan),
        "take_profit_2_base": plan.get("take_profit_2_base", np.nan),
        "trade_allowed_daily_plan": allowed_plan,
        "trade_allowed_current": trade_allowed_current,
        "staleness_status": stale,
        "invalid_reason": plan.get("invalid_reason", ""),
        "next_required_condition": plan.get("next_required_condition", ""),
        "daily_frequency_only": True,
        "intraday_required": False,
        "source_stage": "V21.176_DAILY_DRAM_PREMARKET_TRADE_PLAN_R1",
        "research_only": True,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
    }


def duplicate_mask(ledger: pd.DataFrame, row: dict[str, Any]) -> pd.Series:
    if ledger.empty:
        return pd.Series(dtype=bool)
    mask = pd.Series(True, index=ledger.index)
    for c in DEDUP_COLS:
        if c in ["planned_entry_base", "no_chase_above", "stop_loss_base"]:
            mask &= pd.to_numeric(ledger[c], errors="coerce").round(8).eq(round(float(row[c]), 8))
        else:
            mask &= ledger[c].astype(str).eq(str(row[c]))
    return mask


def append_plan(ledger: pd.DataFrame, row: dict[str, Any]) -> tuple[pd.DataFrame, bool, bool]:
    if ledger.empty:
        return pd.DataFrame([row]).reindex(columns=LEDGER_COLUMNS), True, False
    dup = duplicate_mask(ledger, row)
    if bool(dup.any()):
        return ledger.reindex(columns=LEDGER_COLUMNS), False, True
    out = pd.concat([ledger, pd.DataFrame([row])], ignore_index=True)
    return out.reindex(columns=LEDGER_COLUMNS), True, False


def forward_slice(prices: pd.DataFrame, plan_date: str, days: int) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame()
    d = pd.to_datetime(plan_date, errors="coerce")
    if pd.isna(d):
        return pd.DataFrame()
    return prices[prices["date"] > d].sort_values("date").head(days).copy()


def evaluate_one(row: pd.Series, prices: pd.DataFrame) -> dict[str, Any]:
    plan_date = str(row.get("plan_date", ""))
    base = {
        "ledger_id": row.get("ledger_id", ""),
        "plan_date": plan_date,
        "final_decision": row.get("final_decision", ""),
        "setup_classification": row.get("setup_classification", ""),
        "position_mode": row.get("position_mode", ""),
        "staleness_status": row.get("staleness_status", ""),
    }
    if prices.empty:
        return {**base, "outcome_1d_status": "DATA_MISSING", "outcome_2d_status": "DATA_MISSING", "outcome_5d_status": "DATA_MISSING"}
    future5 = forward_slice(prices, plan_date, 5)
    statuses = {f"outcome_{h}d_status": "MATURED" if len(forward_slice(prices, plan_date, h)) >= h else "PENDING_MATURITY" for h in [1, 2, 5]}
    entry = float(row.get("planned_entry_base", np.nan))
    stop = float(row.get("stop_loss_base", np.nan))
    tp1 = float(row.get("take_profit_1_base", np.nan))
    tp2 = float(row.get("take_profit_2_base", np.nan))
    fill_date = ""
    fill_pos: int | None = None
    for pos, (_, bar) in enumerate(future5.iterrows()):
        if pd.notna(entry) and float(bar["low"]) <= entry <= float(bar["high"]):
            fill_date = str(pd.Timestamp(bar["date"]).date())
            fill_pos = pos
            break
    filled_within = {}
    for h in [1, 2, 5]:
        f = forward_slice(prices, plan_date, h)
        filled_within[f"filled_within_{h}d"] = bool(any(float(b["low"]) <= entry <= float(b["high"]) for _, b in f.iterrows())) if pd.notna(entry) and not f.empty else False
    hit_stop = hit_tp1 = hit_tp2 = False
    lows: list[float] = []
    highs: list[float] = []
    if fill_pos is not None:
        after_fill = future5.iloc[fill_pos:]
        for _, bar in after_fill.iterrows():
            low = float(bar["low"])
            high = float(bar["high"])
            lows.append(low)
            highs.append(high)
            if low <= stop:
                hit_stop = True
                break
            if high >= tp2:
                hit_tp1 = True
                hit_tp2 = True
                break
            if high >= tp1:
                hit_tp1 = True
                break
    horizon_returns = {}
    for h in [1, 2, 5]:
        f = forward_slice(prices, plan_date, h)
        horizon_returns[f"horizon_exit_return_{h}d"] = float(f.iloc[-1]["close"] / entry - 1.0) if len(f) >= h and pd.notna(entry) and entry > 0 else np.nan
    no_fill_5d = not filled_within["filled_within_5d"]
    ret5 = horizon_returns["horizon_exit_return_5d"]
    missed_win = bool(no_fill_5d and pd.notna(ret5) and ret5 > 0.03)
    avoided_loss = bool(no_fill_5d and pd.notna(ret5) and ret5 < 0)
    success = bool(fill_pos is not None and (hit_tp1 or hit_tp2) and not hit_stop)
    return {
        **base,
        **statuses,
        **filled_within,
        "first_fill_date": fill_date,
        "hit_stop_loss_within_5d": hit_stop,
        "hit_tp1_within_5d": hit_tp1,
        "hit_tp2_within_5d": hit_tp2,
        **horizon_returns,
        "max_adverse_excursion_5d": min(lows) / entry - 1.0 if lows and pd.notna(entry) else np.nan,
        "max_favorable_excursion_5d": max(highs) / entry - 1.0 if highs and pd.notna(entry) else np.nan,
        "missed_win_flag": missed_win,
        "avoided_loss_flag": avoided_loss,
        "plan_success_flag": success,
    }


def evaluate_outcomes(ledger: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    if ledger.empty:
        return pd.DataFrame()
    return pd.DataFrame([evaluate_one(row, prices) for _, row in ledger.iterrows()])


def calibration_summary(ledger: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    if ledger.empty:
        return pd.DataFrame()
    merged = ledger.merge(outcomes, on=["ledger_id", "plan_date", "final_decision", "setup_classification", "position_mode", "staleness_status"], how="left")
    rows = []
    for keys, g in merged.groupby(["final_decision", "setup_classification", "position_mode", "staleness_status"], dropna=False):
        rows.append(
            {
                "final_decision": keys[0],
                "setup_classification": keys[1],
                "position_mode": keys[2],
                "staleness_status": keys[3],
                "count": len(g),
                "current_count": int(g["staleness_status"].eq("CURRENT_OR_RECENT").sum()),
                "stale_warn_count": int(g["staleness_status"].eq("STALE_WARN").sum()),
                "stale_block_count": int(g["staleness_status"].eq("STALE_BLOCK").sum()),
                "matured_1d_count": int(g["outcome_1d_status"].eq("MATURED").sum()),
                "matured_2d_count": int(g["outcome_2d_status"].eq("MATURED").sum()),
                "matured_5d_count": int(g["outcome_5d_status"].eq("MATURED").sum()),
                "filled_5d_count": int(g["filled_within_5d"].fillna(False).astype(bool).sum()),
                "no_fill_5d_count": int((~g["filled_within_5d"].fillna(False).astype(bool)).sum()),
                "stop_loss_count": int(g["hit_stop_loss_within_5d"].fillna(False).astype(bool).sum()),
                "tp1_count": int(g["hit_tp1_within_5d"].fillna(False).astype(bool).sum()),
                "tp2_count": int(g["hit_tp2_within_5d"].fillna(False).astype(bool).sum()),
                "missed_win_count": int(g["missed_win_flag"].fillna(False).astype(bool).sum()),
                "avoided_loss_count": int(g["avoided_loss_flag"].fillna(False).astype(bool).sum()),
                "plan_success_count": int(g["plan_success_flag"].fillna(False).astype(bool).sum()),
                "avg_horizon_return_5d": pd.to_numeric(g["horizon_exit_return_5d"], errors="coerce").mean(),
                "avg_mae_5d": pd.to_numeric(g["max_adverse_excursion_5d"], errors="coerce").mean(),
                "avg_mfe_5d": pd.to_numeric(g["max_favorable_excursion_5d"], errors="coerce").mean(),
            }
        )
    return pd.DataFrame(rows)


def current_action(row: dict[str, Any]) -> tuple[str, str]:
    if row["staleness_status"] == "STALE_BLOCK":
        return "STALE_DO_NOT_USE", "Plan is older than the stale block threshold; do not use."
    if row["final_decision"] == "DRAM_TRADE_ALLOWED_LIMIT_ONLY" and row["trade_allowed_current"]:
        return "LIMIT_PLAN_ALLOWED", "Daily limit-only plan is current enough for research tracking."
    if "NO_CHASE" in str(row["final_decision"]):
        return "NO_CHASE", "No-chase condition prevents using the plan."
    if "NO_TRADE" in str(row["final_decision"]):
        return "NO_TRADE", "Daily setup is weak or invalid."
    return "WAIT", "Wait for next daily refresh or required condition."


def write_report(summary: dict[str, Any], out_dir: Path = OUT) -> None:
    lines = [
        STAGE,
        f"final_status: {summary['final_status']}",
        f"decision: {summary['decision']}",
        f"latest_price_date: {summary['latest_price_date']}",
        f"latest_plan_date: {summary['latest_plan_date']}",
        f"staleness_status: {summary['staleness_status']}",
        f"trade_allowed_current: {summary['trade_allowed_current']}",
        f"ledger rows before/after: {summary['ledger_rows_before']} / {summary['ledger_rows_after']}",
        f"new_plan_appended: {summary['new_plan_appended']}",
        f"duplicate_skipped: {summary['duplicate_skipped']}",
        f"latest_immediate_action_label: {summary['latest_immediate_action_label']}",
        f"matured 1d/2d/5d: {summary['matured_1d_count']} / {summary['matured_2d_count']} / {summary['matured_5d_count']}",
        f"filled/stop/tp1/tp2/missed_win/avoided_loss: {summary['filled_5d_count']} / {summary['stop_loss_count']} / {summary['tp1_count']} / {summary['tp2_count']} / {summary['missed_win_count']} / {summary['avoided_loss_count']}",
        "warnings:",
        *([f"- {w}" for w in summary["warnings"]] if summary["warnings"] else ["- none"]),
        "daily_frequency_only: True",
        "intraday_required: False",
        "research_only: True",
        "broker_action_allowed: False",
        "official_adoption_allowed: False",
    ]
    (out_dir / "V21.177_daily_dram_readable_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_blocked(out_dir: Path, warnings: list[str], price_missing: bool = False) -> None:
    pd.DataFrame(columns=LEDGER_COLUMNS).to_csv(out_dir / "dram_daily_plan_ledger.csv", index=False)
    pd.DataFrame().to_csv(out_dir / "dram_daily_plan_outcomes.csv", index=False)
    pd.DataFrame().to_csv(out_dir / "dram_daily_plan_calibration_summary.csv", index=False)
    pd.DataFrame().to_csv(out_dir / "dram_current_plan_review.csv", index=False)
    summary = {
        "final_status": "WARN_V21_177_DAILY_PRICE_MISSING" if price_missing else "BLOCKED_V21_177_MISSING_V21_176_OUTPUTS",
        "decision": "DAILY_DRAM_LEDGER_WARN_PRICE_MISSING" if price_missing else "DAILY_DRAM_LEDGER_BLOCKED_MISSING_PLAN",
        "v21_176_loaded": not price_missing,
        "latest_price_date": "",
        "latest_plan_date": "",
        "staleness_status": "STALE_BLOCK",
        "trade_allowed_current": False,
        "ledger_rows_before": 0,
        "ledger_rows_after": 0,
        "new_plan_appended": False,
        "duplicate_skipped": False,
        "latest_final_decision": "",
        "latest_immediate_action_label": "STALE_DO_NOT_USE",
        "pending_maturity_count": 0,
        "matured_1d_count": 0,
        "matured_2d_count": 0,
        "matured_5d_count": 0,
        "filled_5d_count": 0,
        "stop_loss_count": 0,
        "tp1_count": 0,
        "tp2_count": 0,
        "missed_win_count": 0,
        "avoided_loss_count": 0,
        "plan_success_count": 0,
        "warnings": warnings,
        **POLICY,
    }
    (out_dir / "V21.177_daily_dram_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_report(summary, out_dir)


def main(out_dir: Path = OUT, plan_path: Path = PLAN_PATH, price_path: Path = DAILY_PRICE_PATH, run_date: pd.Timestamp | None = None) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    pre_hash = sha(PRICE_PATH)
    plan_df = load_plan(plan_path)
    if plan_df.empty or not SUMMARY_176_PATH.exists():
        write_blocked(out_dir, ["WARN_V21_176_OUTPUTS_MISSING"])
        return 0
    prices = load_prices(price_path)
    if prices.empty:
        write_blocked(out_dir, ["WARN_DAILY_PRICE_BRIDGE_MISSING"], price_missing=True)
        return 0
    latest_price_date = str(pd.Timestamp(prices["date"].max()).date())
    latest_plan_date = str(plan_df.iloc[0].get("plan_date", ""))
    warnings: list[str] = []
    if latest_plan_date != latest_price_date:
        warnings.append("WARN_PLAN_DATE_MISMATCH")
    stale = staleness_status(latest_price_date, run_date)
    prior = read_csv(out_dir / "dram_daily_plan_ledger.csv")
    rows_before = len(prior)
    run_ts = datetime.now(timezone.utc).isoformat()
    ledger_id = hashlib.sha256(f"{latest_plan_date}|{plan_df.iloc[0].get('final_decision')}|{plan_df.iloc[0].get('planned_entry_base')}|{run_ts}".encode()).hexdigest()[:16]
    new_row = build_ledger_row(plan_df.iloc[0], latest_price_date, stale, run_ts, ledger_id)
    ledger, appended, dup = append_plan(prior, new_row)
    if dup:
        warnings.append("INFO_DUPLICATE_PLAN_SKIPPED")
    ledger.to_csv(out_dir / "dram_daily_plan_ledger.csv", index=False)
    outcomes = evaluate_outcomes(ledger, prices)
    outcomes.to_csv(out_dir / "dram_daily_plan_outcomes.csv", index=False)
    calib = calibration_summary(ledger, outcomes)
    calib.to_csv(out_dir / "dram_daily_plan_calibration_summary.csv", index=False)
    action_label, explanation = current_action(new_row)
    review = pd.DataFrame(
        [
            {
                "plan_date": latest_plan_date,
                "latest_price_date": latest_price_date,
                "staleness_status": stale,
                "trade_allowed_current": new_row["trade_allowed_current"],
                "final_decision": new_row["final_decision"],
                "position_mode": new_row["position_mode"],
                "planned_entry_base": new_row["planned_entry_base"],
                "no_chase_above": new_row["no_chase_above"],
                "stop_loss_base": new_row["stop_loss_base"],
                "take_profit_1_base": new_row["take_profit_1_base"],
                "take_profit_2_base": new_row["take_profit_2_base"],
                "immediate_action_label": action_label,
                "explanation": explanation,
            }
        ]
    )
    review.to_csv(out_dir / "dram_current_plan_review.csv", index=False)
    pending_count = int(outcomes[["outcome_1d_status", "outcome_2d_status", "outcome_5d_status"]].eq("PENDING_MATURITY").any(axis=1).sum()) if not outcomes.empty else 0
    matured_1d = int(outcomes["outcome_1d_status"].eq("MATURED").sum()) if not outcomes.empty else 0
    matured_2d = int(outcomes["outcome_2d_status"].eq("MATURED").sum()) if not outcomes.empty else 0
    matured_5d = int(outcomes["outcome_5d_status"].eq("MATURED").sum()) if not outcomes.empty else 0
    if stale == "STALE_BLOCK":
        final_status = "WARN_V21_177_PLAN_STALE_BLOCK"
        decision = "DAILY_DRAM_PLAN_STALE_DO_NOT_USE"
    elif stale == "STALE_WARN":
        final_status = "WARN_V21_177_PLAN_STALE_WARN"
        decision = "DAILY_DRAM_PLAN_STALE_DO_NOT_USE"
    elif pending_count == len(outcomes) and len(outcomes) > 0:
        final_status = "PARTIAL_PASS_V21_177_LEDGER_ACTIVE_WAIT_MATURITY"
        decision = "DAILY_DRAM_PLAN_LEDGER_ACTIVE_WAIT_MATURITY"
    else:
        final_status = "PASS_V21_177_DAILY_DRAM_LEDGER_ACTIVE"
        decision = "DAILY_DRAM_PLAN_LEDGER_ACTIVE"
    post_hash = sha(PRICE_PATH)
    summary = {
        "final_status": final_status,
        "decision": decision,
        "v21_176_loaded": True,
        "latest_price_date": latest_price_date,
        "latest_plan_date": latest_plan_date,
        "staleness_status": stale,
        "trade_allowed_current": bool(new_row["trade_allowed_current"]),
        "ledger_rows_before": rows_before,
        "ledger_rows_after": len(ledger),
        "new_plan_appended": appended,
        "duplicate_skipped": dup,
        "latest_final_decision": new_row["final_decision"],
        "latest_immediate_action_label": action_label,
        "pending_maturity_count": pending_count,
        "matured_1d_count": matured_1d,
        "matured_2d_count": matured_2d,
        "matured_5d_count": matured_5d,
        "filled_5d_count": int(outcomes["filled_within_5d"].fillna(False).astype(bool).sum()) if not outcomes.empty else 0,
        "stop_loss_count": int(outcomes["hit_stop_loss_within_5d"].fillna(False).astype(bool).sum()) if not outcomes.empty else 0,
        "tp1_count": int(outcomes["hit_tp1_within_5d"].fillna(False).astype(bool).sum()) if not outcomes.empty else 0,
        "tp2_count": int(outcomes["hit_tp2_within_5d"].fillna(False).astype(bool).sum()) if not outcomes.empty else 0,
        "missed_win_count": int(outcomes["missed_win_flag"].fillna(False).astype(bool).sum()) if not outcomes.empty else 0,
        "avoided_loss_count": int(outcomes["avoided_loss_flag"].fillna(False).astype(bool).sum()) if not outcomes.empty else 0,
        "plan_success_count": int(outcomes["plan_success_flag"].fillna(False).astype(bool).sum()) if not outcomes.empty else 0,
        "warnings": warnings,
        **{**POLICY, "canonical_price_panel_modified": pre_hash != post_hash},
        "created_at_utc": run_ts,
        "output_directory": rel(out_dir),
    }
    (out_dir / "V21.177_daily_dram_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_report(summary, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
