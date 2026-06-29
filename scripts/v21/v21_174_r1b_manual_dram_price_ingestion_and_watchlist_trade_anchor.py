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

from scripts.v21 import v21_174_realistic_execution_backtest_and_tactical_trade_engine_r1 as v174


STAGE = "V21.174_R1B_MANUAL_DRAM_PRICE_INGESTION_AND_WATCHLIST_TRADE_ANCHOR"
OUT = ROOT / "outputs" / "v21" / STAGE
PRICE_PATH = v174.PRICE_PATH

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "canonical_price_panel_modified": False,
}

BRIDGE_COLUMNS = ["date", "ticker", "open", "high", "low", "close", "volume"]
MANUAL_RELATIVE_PATHS = [
    "inputs/manual_prices/dram_daily_ohlcv.csv",
    "data/manual_prices/dram_daily_ohlcv.csv",
    "local/manual_watchlist_prices/dram_daily_ohlcv.csv",
    "inputs/manual_prices/DRAM_daily_ohlcv.csv",
    "data/manual_prices/DRAM_daily_ohlcv.csv",
    "local/manual_watchlist_prices/DRAM_daily_ohlcv.csv",
]
ALIASES = {
    "date": ["date", "datetime", "time"],
    "ticker": ["ticker", "symbol", "code"],
    "open": ["open", "o"],
    "high": ["high", "h"],
    "low": ["low", "l"],
    "close": ["close", "adj_close", "adj close", "c"],
    "volume": ["volume", "vol", "v"],
}
VARIANTS = {
    "BASE": {"stop_mult": 1.0, "tp1_mult": 1.5, "tp2_mult": 2.5},
    "TIGHT": {"stop_mult": 0.6, "tp1_mult": 1.2, "tp2_mult": 2.0},
}


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


def manual_paths(root: Path = ROOT) -> list[Path]:
    return [root / p for p in MANUAL_RELATIVE_PATHS]


def column_lookup(df: pd.DataFrame) -> dict[str, str]:
    normalized = {str(c).strip().lower(): c for c in df.columns}
    out: dict[str, str] = {}
    for target, aliases in ALIASES.items():
        for alias in aliases:
            if alias.lower() in normalized:
                out[target] = normalized[alias.lower()]
                break
    return out


def normalize_manual_ohlcv(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str], str]:
    warnings: list[str] = []
    if raw.empty:
        return pd.DataFrame(columns=BRIDGE_COLUMNS), ["WARN_EMPTY_MANUAL_FILE"], "EMPTY_MANUAL_FILE"
    cols = column_lookup(raw)
    missing = [c for c in ["date", "open", "high", "low", "close"] if c not in cols]
    if missing:
        return pd.DataFrame(columns=BRIDGE_COLUMNS), [f"WARN_MISSING_REQUIRED_COLUMNS:{'|'.join(missing)}"], "MISSING_REQUIRED_COLUMNS"
    work = raw.copy()
    if "ticker" in cols:
        ticker = work[cols["ticker"]].astype(str).str.upper().str.strip()
        work = work[ticker.eq("DRAM")].copy()
    else:
        warnings.append("WARN_MANUAL_FILE_NO_TICKER_COLUMN")
    if "volume" not in cols:
        warnings.append("WARN_VOLUME_MISSING")
        volume = 0
    else:
        volume = pd.to_numeric(work[cols["volume"]], errors="coerce").fillna(0)
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(work[cols["date"]], errors="coerce"),
            "ticker": "DRAM",
            "open": pd.to_numeric(work[cols["open"]], errors="coerce"),
            "high": pd.to_numeric(work[cols["high"]], errors="coerce"),
            "low": pd.to_numeric(work[cols["low"]], errors="coerce"),
            "close": pd.to_numeric(work[cols["close"]], errors="coerce"),
            "volume": volume,
        }
    )
    before = len(out)
    out = out.dropna(subset=["date", "open", "high", "low", "close"])
    out = out[(out["open"] > 0) & (out["high"] > 0) & (out["low"] > 0) & (out["close"] > 0)]
    out = out[(out["high"] >= out[["open", "low", "close"]].max(axis=1)) & (out["low"] <= out[["open", "high", "close"]].min(axis=1))]
    dropped = before - len(out)
    if dropped:
        warnings.append(f"WARN_INVALID_OHLC_ROWS_DROPPED:{dropped}")
    if out.empty:
        return pd.DataFrame(columns=BRIDGE_COLUMNS), warnings + ["WARN_NO_VALID_DRAM_ROWS"], "NO_VALID_DRAM_ROWS"
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out = out.sort_values("date").drop_duplicates(["date", "ticker"], keep="last")
    return out[BRIDGE_COLUMNS].reset_index(drop=True), warnings, "USABLE"


def audit_manual_inputs(paths: list[Path]) -> tuple[pd.DataFrame, pd.DataFrame, Path | None, list[str]]:
    rows: list[dict[str, Any]] = []
    usable_df = pd.DataFrame(columns=BRIDGE_COLUMNS)
    usable_path: Path | None = None
    all_warnings: list[str] = []
    for path in paths:
        exists = path.exists()
        readable = False
        usable = False
        raw_count = 0
        valid_count = 0
        latest = ""
        warnings: list[str] = []
        notes = ""
        if exists:
            raw = read_csv(path)
            readable = not raw.empty or path.stat().st_size > 0
            raw_count = len(raw)
            norm, warnings, notes = normalize_manual_ohlcv(raw)
            valid_count = len(norm)
            latest = str(norm["date"].max()) if not norm.empty else ""
            usable = valid_count > 0
            if usable and usable_path is None:
                usable_df = norm
                usable_path = path
            all_warnings.extend(warnings)
        rows.append(
            {
                "searched_path": rel(path),
                "exists": exists,
                "readable": readable,
                "usable": usable,
                "row_count_raw": raw_count,
                "row_count_valid": valid_count,
                "latest_date": latest,
                "warnings": "|".join(warnings),
                "notes": notes,
            }
        )
    return pd.DataFrame(rows), usable_df, usable_path, sorted(set(all_warnings))


def write_template(out_dir: Path = OUT) -> None:
    pd.DataFrame(columns=BRIDGE_COLUMNS).to_csv(out_dir / "manual_dram_daily_ohlcv_TEMPLATE.csv", index=False)


def add_atr(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    return v174.add_atr14(work).sort_values("date").reset_index(drop=True)


def tactical_levels(close: float, atr: float) -> dict[str, float]:
    planned = close - 0.35 * atr
    stop_base = planned - atr
    stop_tight = planned - 0.6 * atr
    risk_base = planned - stop_base
    risk_tight = planned - stop_tight
    return {
        "planned_entry_base": planned,
        "planned_entry_tight": planned,
        "no_chase_above": close * 1.03,
        "stop_loss_base": stop_base,
        "stop_loss_tight": stop_tight,
        "take_profit_1_base": planned + 1.5 * risk_base,
        "take_profit_2_base": planned + 2.5 * risk_base,
        "take_profit_1_tight": planned + 1.2 * risk_tight,
        "take_profit_2_tight": planned + 2.0 * risk_tight,
        "reward_risk_base": 1.5,
        "reward_risk_tight": 1.2,
    }


def build_anchor(bridge: pd.DataFrame, warnings: list[str]) -> pd.DataFrame:
    if bridge.empty:
        return pd.DataFrame(
            [
                {
                    "latest_date": "",
                    "ticker": "DRAM",
                    "latest_close": np.nan,
                    "atr14": np.nan,
                    "final_decision": "DRAM_MANUAL_DATA_MISSING",
                    "daily_proxy_only": True,
                    "technical_gate": "DAILY_PROXY_ONLY",
                    "market_gate": "DAILY_PROXY_ONLY",
                }
            ]
        )
    if len(bridge) < 30:
        warnings.append("WARN_INSUFFICIENT_DRAM_HISTORY")
        latest = bridge.iloc[-1]
        return pd.DataFrame(
            [
                {
                    "latest_date": latest["date"],
                    "ticker": "DRAM",
                    "latest_close": latest["close"],
                    "atr14": np.nan,
                    "final_decision": "DRAM_INSUFFICIENT_HISTORY",
                    "daily_proxy_only": True,
                    "technical_gate": "DAILY_PROXY_ONLY",
                    "market_gate": "DAILY_PROXY_ONLY",
                }
            ]
        )
    enriched = add_atr(bridge)
    latest = enriched.iloc[-1]
    atr = float(latest["atr14"]) if pd.notna(latest["atr14"]) else np.nan
    if pd.isna(atr) or atr <= 0 or float(latest["close"]) <= 0:
        warnings.append("WARN_INVALID_DRAM_ATR_OR_CLOSE")
        decision = "DRAM_INVALID_PRICE_DATA"
        levels = {}
    else:
        decision = "DRAM_DAILY_TACTICAL_ANCHOR_READY"
        levels = tactical_levels(float(latest["close"]), atr)
    return pd.DataFrame(
        [
            {
                "latest_date": str(pd.Timestamp(latest["date"]).date()),
                "ticker": "DRAM",
                "latest_close": float(latest["close"]),
                "atr14": atr,
                **levels,
                "daily_proxy_only": True,
                "technical_gate": "DAILY_PROXY_ONLY",
                "market_gate": "DAILY_PROXY_ONLY",
                "final_decision": decision,
            }
        ]
    )


def plan_from_row(row: pd.Series, variant: str) -> dict[str, Any]:
    levels = tactical_levels(float(row["close"]), float(row["atr14"]))
    if variant == "BASE":
        stop = levels["stop_loss_base"]
        tp1 = levels["take_profit_1_base"]
        tp2 = levels["take_profit_2_base"]
    else:
        stop = levels["stop_loss_tight"]
        tp1 = levels["take_profit_1_tight"]
        tp2 = levels["take_profit_2_tight"]
    planned = levels["planned_entry_base"]
    return {
        "trade_date": "",
        "ranking_date": str(pd.Timestamp(row["date"]).date()),
        "ticker": "DRAM",
        "strategy_state": "manual_watchlist_tactical_anchor",
        "planned_entry": planned,
        "no_chase_above": levels["no_chase_above"],
        "stop_loss": stop,
        "take_profit_1": tp1,
        "take_profit_2": tp2,
        "risk_per_share": planned - stop,
        "reward_risk_to_tp1": (tp1 - planned) / (planned - stop),
        "trade_allowed": True,
        "invalid_reason": "",
    }


def replay_manual_dram(bridge: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if len(bridge) < 30:
        return pd.DataFrame(), pd.DataFrame()
    price = add_atr(bridge)
    price["ticker"] = "DRAM"
    eligible_idx = [i for i in range(len(price)) if i >= 13 and pd.notna(price.loc[i, "atr14"]) and i + 1 < len(price)]
    eligible_idx = eligible_idx[-20:]
    results: list[dict[str, Any]] = []
    for i in eligible_idx:
        plan_row = price.loc[i]
        for variant in VARIANTS:
            plan = plan_from_row(plan_row, variant)
            for horizon, days in v174.HORIZONS.items():
                if i + days >= len(price):
                    continue
                sim, _audit = v174.simulate_trade(plan, price, horizon, days)
                results.append(
                    {
                        "plan_date": plan["ranking_date"],
                        "horizon": horizon,
                        "variant": variant,
                        "ticker": "DRAM",
                        "planned_entry": plan["planned_entry"],
                        "no_chase_above": plan["no_chase_above"],
                        "stop_loss": plan["stop_loss"],
                        "take_profit_1": plan["take_profit_1"],
                        "take_profit_2": plan["take_profit_2"],
                        "filled": sim["filled"],
                        "fill_date": sim["fill_date"],
                        "fill_price": sim["fill_price"],
                        "exit_date": sim["exit_date"],
                        "exit_price": sim["exit_price"],
                        "exit_reason": sim["exit_reason"],
                        "realistic_pnl_pct": sim["realistic_pnl_pct"],
                        "max_adverse_excursion_pct": sim["max_adverse_excursion_pct"],
                        "max_favorable_excursion_pct": sim["max_favorable_excursion_pct"],
                        "stop_hit": sim["stop_hit"],
                        "tp1_hit": sim["tp1_hit"],
                        "tp2_hit": sim["tp2_hit"],
                        "missed_trade": sim["missed_trade"],
                        "missed_reason": sim["missed_reason"],
                    }
                )
    res = pd.DataFrame(results)
    if res.empty:
        return res, pd.DataFrame()
    rows = []
    for (variant, horizon), g in res.groupby(["variant", "horizon"]):
        filled = g[g["filled"].astype(bool)]
        pnl = pd.to_numeric(filled["realistic_pnl_pct"], errors="coerce")
        rows.append(
            {
                "variant": variant,
                "horizon": horizon,
                "plan_count": len(g),
                "filled_count": int(g["filled"].astype(bool).sum()),
                "no_fill_count": int(g["exit_reason"].eq("NO_FILL").sum()),
                "stop_loss_count": int(g["exit_reason"].eq("STOP_LOSS").sum()),
                "tp1_count": int(g["exit_reason"].eq("TAKE_PROFIT_1").sum()),
                "tp2_count": int(g["exit_reason"].eq("TAKE_PROFIT_2").sum()),
                "horizon_exit_count": int(g["exit_reason"].eq("HORIZON_EXIT").sum()),
                "avg_realistic_pnl_pct": float(pnl.mean()) if not pnl.empty else np.nan,
                "median_realistic_pnl_pct": float(pnl.median()) if not pnl.empty else np.nan,
                "win_rate": float((pnl > 0).mean()) if not pnl.empty else np.nan,
                "avg_mae_pct": float(pd.to_numeric(filled["max_adverse_excursion_pct"], errors="coerce").mean()) if not filled.empty else np.nan,
                "avg_mfe_pct": float(pd.to_numeric(filled["max_favorable_excursion_pct"], errors="coerce").mean()) if not filled.empty else np.nan,
            }
        )
    return res, pd.DataFrame(rows)


def latest_trade_plan(anchor: pd.DataFrame) -> pd.DataFrame:
    row = anchor.iloc[0].to_dict() if not anchor.empty else {}
    decision = row.get("final_decision", "DRAM_MANUAL_DATA_MISSING")
    trade_allowed = decision == "DRAM_DAILY_TACTICAL_ANCHOR_READY"
    invalid = "" if trade_allowed else str(decision)
    return pd.DataFrame(
        [
            {
                "latest_date": row.get("latest_date", ""),
                "ticker": "DRAM",
                "latest_close": row.get("latest_close", np.nan),
                "planned_entry_base": row.get("planned_entry_base", np.nan),
                "planned_entry_tight": row.get("planned_entry_tight", np.nan),
                "no_chase_above": row.get("no_chase_above", np.nan),
                "stop_loss_base": row.get("stop_loss_base", np.nan),
                "stop_loss_tight": row.get("stop_loss_tight", np.nan),
                "take_profit_1_base": row.get("take_profit_1_base", np.nan),
                "take_profit_2_base": row.get("take_profit_2_base", np.nan),
                "take_profit_1_tight": row.get("take_profit_1_tight", np.nan),
                "take_profit_2_tight": row.get("take_profit_2_tight", np.nan),
                "final_decision": decision,
                "trade_allowed_daily_proxy": trade_allowed,
                "invalid_reason": invalid,
                "daily_proxy_only": True,
                "intraday_claim_allowed": False,
                "official_adoption_allowed": False,
                "broker_action_allowed": False,
            }
        ]
    )


def write_report(summary: dict[str, Any], template_created: bool, out_dir: Path = OUT) -> None:
    lines = [
        STAGE,
        f"final_status: {summary['final_status']}",
        f"decision: {summary['decision']}",
        f"manual_dram_source_found: {summary['manual_dram_source_found']}",
        f"manual_dram_source_path: {summary['manual_dram_source_path']}",
        f"manual_latest_date: {summary['manual_latest_date']}",
        f"manual_valid_row_count: {summary['manual_valid_row_count']}",
        f"template_created: {template_created}",
        f"tactical_anchor_created: {summary['dram_tactical_anchor_created']}",
        f"execution_replay_created: {summary['dram_execution_replay_created']}",
        f"BASE filled/stop/tp1/tp2: {summary['base_filled_count']} / {summary['base_stop_loss_count']} / {summary['base_tp1_count']} / {summary['base_tp2_count']}",
        f"TIGHT filled/stop/tp1/tp2: {summary['tight_filled_count']} / {summary['tight_stop_loss_count']} / {summary['tight_tp1_count']} / {summary['tight_tp2_count']}",
        "warnings:",
        *([f"- {w}" for w in summary["warnings"]] if summary["warnings"] else ["- none"]),
        "daily_proxy_only: True",
        "intraday_claim_allowed: False",
        "research_only: True",
        "official_adoption_allowed: False",
        "broker_action_allowed: False",
        "protected_outputs_modified: False",
        "canonical_price_panel_modified: False",
    ]
    (out_dir / "V21.174_R1B_readable_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def counts(audit: pd.DataFrame, variant: str, col: str) -> int:
    if audit.empty:
        return 0
    return int(audit[audit["variant"].eq(variant)][col].sum())


def main(root: Path = ROOT, out_dir: Path = OUT) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    pre_hash = sha(PRICE_PATH)
    audit, bridge, source_path, warnings = audit_manual_inputs(manual_paths(root))
    audit.to_csv(out_dir / "manual_dram_input_audit.csv", index=False)
    template_created = False
    file_exists_any = bool(audit["exists"].any()) if not audit.empty else False
    if bridge.empty:
        pd.DataFrame(columns=BRIDGE_COLUMNS).to_csv(out_dir / "dram_manual_price_bridge_daily_ohlcv.csv", index=False)
        write_template(out_dir)
        template_created = True
    else:
        bridge.to_csv(out_dir / "dram_manual_price_bridge_daily_ohlcv.csv", index=False)
    anchor = build_anchor(bridge, warnings)
    anchor.to_csv(out_dir / "dram_daily_tactical_anchor.csv", index=False)
    replay, stop_audit = replay_manual_dram(bridge)
    replay.to_csv(out_dir / "dram_execution_simulation_results.csv", index=False)
    stop_audit.to_csv(out_dir / "dram_stop_tp_path_audit.csv", index=False)
    latest_plan = latest_trade_plan(anchor)
    latest_plan.to_csv(out_dir / "dram_tactical_trade_plan_latest.csv", index=False)

    valid_count = len(bridge)
    latest_date = str(bridge["date"].max()) if not bridge.empty else ""
    anchor_ready = str(anchor.iloc[0].get("final_decision")) == "DRAM_DAILY_TACTICAL_ANCHOR_READY"
    replay_created = not replay.empty
    if anchor_ready and replay_created:
        final_status = "PASS_V21_174_R1B_DRAM_MANUAL_ANCHOR_READY"
        decision = "DRAM_MANUAL_WATCHLIST_ANCHOR_READY_DAILY_PROXY"
    elif bridge.empty and file_exists_any:
        final_status = "BLOCKED_V21_174_R1B_INVALID_MANUAL_DRAM_DATA"
        decision = "DRAM_MANUAL_DATA_INVALID"
    elif bridge.empty:
        final_status = "PARTIAL_PASS_V21_174_R1B_TEMPLATE_CREATED_WAIT_MANUAL_DRAM_DATA"
        decision = "WAIT_MANUAL_DRAM_DAILY_OHLCV_INPUT"
    elif valid_count < 30:
        final_status = "WARN_V21_174_R1B_INSUFFICIENT_DRAM_HISTORY"
        decision = "DRAM_MANUAL_DATA_INSUFFICIENT_HISTORY"
    else:
        final_status = "BLOCKED_V21_174_R1B_INVALID_MANUAL_DRAM_DATA"
        decision = "DRAM_MANUAL_DATA_INVALID"

    post_hash = sha(PRICE_PATH)
    summary = {
        "final_status": final_status,
        "decision": decision,
        "manual_dram_source_found": source_path is not None,
        "manual_dram_source_path": rel(source_path) if source_path else "",
        "manual_valid_row_count": valid_count,
        "manual_latest_date": latest_date,
        "dram_manual_bridge_created": not bridge.empty,
        "dram_tactical_anchor_created": anchor_ready,
        "dram_execution_replay_created": replay_created,
        "dram_latest_final_decision": latest_plan.iloc[0]["final_decision"],
        "base_filled_count": counts(stop_audit, "BASE", "filled_count"),
        "base_stop_loss_count": counts(stop_audit, "BASE", "stop_loss_count"),
        "base_tp1_count": counts(stop_audit, "BASE", "tp1_count"),
        "base_tp2_count": counts(stop_audit, "BASE", "tp2_count"),
        "tight_filled_count": counts(stop_audit, "TIGHT", "filled_count"),
        "tight_stop_loss_count": counts(stop_audit, "TIGHT", "stop_loss_count"),
        "tight_tp1_count": counts(stop_audit, "TIGHT", "tp1_count"),
        "tight_tp2_count": counts(stop_audit, "TIGHT", "tp2_count"),
        "warnings": sorted(set(warnings)),
        "daily_proxy_only": True,
        "intraday_claim_allowed": False,
        **{**POLICY, "canonical_price_panel_modified": pre_hash != post_hash},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(out_dir),
    }
    (out_dir / "V21.174_R1B_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_report(summary, template_created, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
