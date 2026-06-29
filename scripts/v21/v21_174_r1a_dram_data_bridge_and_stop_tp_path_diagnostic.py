from __future__ import annotations

import hashlib
import json
import subprocess
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


STAGE = "V21.174_R1A_DRAM_DATA_BRIDGE_AND_STOP_TP_PATH_DIAGNOSTIC"
OUT = ROOT / "outputs" / "v21" / STAGE
V174_OUT = ROOT / "outputs" / "v21" / "V21.174_REALISTIC_EXECUTION_BACKTEST_AND_TACTICAL_TRADE_ENGINE_R1"
PRICE_PATH = v174.PRICE_PATH

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "canonical_price_panel_modified": False,
}

DRAM_ALIASES = {"DRAM.US", "DRAM.O", "DRAM.N"}
BRIDGE_COLUMNS = ["date", "ticker", "open", "high", "low", "close", "volume"]
REQUIRED_PLAN_COLS = {
    "ranking_date",
    "ticker",
    "strategy_state",
    "planned_entry",
    "stop_loss",
    "take_profit_1",
    "take_profit_2",
    "risk_per_share",
    "trade_allowed",
}
REQUIRED_SIM_COLS = {
    "horizon",
    "ticker",
    "strategy_state",
    "filled",
    "fill_date",
    "exit_reason",
    "realistic_pnl_pct",
    "max_adverse_excursion_pct",
    "max_favorable_excursion_pct",
}
VARIANTS = {
    "BASE": {"stop_atr_mult": 1.0, "tp1_r_mult": 1.5, "tp2_r_mult": 2.5},
    "TIGHT": {"stop_atr_mult": 0.6, "tp1_r_mult": 1.2, "tp2_r_mult": 2.0},
    "WIDE": {"stop_atr_mult": 1.4, "tp1_r_mult": 2.0, "tp2_r_mult": 3.0},
}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame()


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


def source_type(path: Path) -> str:
    s = rel(path).lower()
    if "price" in s or "ohlcv" in s:
        return "price_panel"
    if "ranking" in s or "rank" in s:
        return "ranking"
    if "watch" in s:
        return "watchlist"
    if "ledger" in s:
        return "ledger"
    return "other"


def detect_ticker_col(df: pd.DataFrame) -> str | None:
    return v174.first_col(df, ["ticker", "symbol", "ticker_norm", "underlying", "asset", "security"])


def detect_dram_symbols(values: pd.Series) -> tuple[bool, bool, list[str], bool]:
    normalized = values.dropna().astype(str).str.upper().str.strip()
    exact = normalized.eq("DRAM")
    alias = normalized.isin(DRAM_ALIASES)
    bdry_nonmatch = normalized.eq("BDRY")
    matches = sorted(set(normalized[exact | alias].tolist()))
    return bool(exact.any()), bool(alias.any()), matches, bool(bdry_nonmatch.any())


def latest_date(df: pd.DataFrame) -> str:
    dcol = v174.first_col(df, ["date", "asof_date", "latest_price_date", "latest_price_date_used", "ranking_date"])
    if dcol is None:
        return ""
    dates = pd.to_datetime(df[dcol], errors="coerce").dropna()
    return str(dates.max().date()) if not dates.empty else ""


def usable_ohlcv(df: pd.DataFrame, ticker_col: str | None) -> bool:
    if ticker_col is None:
        return False
    cols = {c.lower() for c in df.columns}
    return {"date", "open", "high", "low", "close"}.issubset(cols)


def normalize_bridge_rows(df: pd.DataFrame, ticker_col: str) -> pd.DataFrame:
    work = df.copy()
    work["_ticker_norm"] = work[ticker_col].astype(str).str.upper().str.strip()
    work = work[work["_ticker_norm"].isin({"DRAM", *DRAM_ALIASES})].copy()
    if work.empty:
        return pd.DataFrame(columns=BRIDGE_COLUMNS)
    colmap = {c.lower(): c for c in work.columns}
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(work[colmap["date"]], errors="coerce").dt.strftime("%Y-%m-%d"),
            "ticker": "DRAM",
            "open": pd.to_numeric(work[colmap["open"]], errors="coerce"),
            "high": pd.to_numeric(work[colmap["high"]], errors="coerce"),
            "low": pd.to_numeric(work[colmap["low"]], errors="coerce"),
            "close": pd.to_numeric(work[colmap["close"]], errors="coerce"),
            "volume": pd.to_numeric(work[colmap["volume"]], errors="coerce") if "volume" in colmap else np.nan,
        }
    )
    out = out.dropna(subset=["date", "open", "high", "low", "close"])
    return out.sort_values("date").drop_duplicates(["date", "ticker"], keep="last")[BRIDGE_COLUMNS]


def rg_dram_files() -> list[Path]:
    roots = [ROOT / "outputs", ROOT / "data", ROOT / "scripts"]
    existing = [str(p) for p in roots if p.exists()]
    if not existing:
        return []
    try:
        proc = subprocess.run(
            ["rg", "-l", "--ignore-case", r"\bDRAM\b", *existing],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        paths = []
        for line in proc.stdout.splitlines():
            p = (ROOT / line).resolve() if not Path(line).is_absolute() else Path(line)
            if p.exists() and p.is_file():
                paths.append(p)
        return sorted(set(paths))
    except Exception:
        return []


def audit_file(path: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    row = {
        "source_file": rel(path),
        "source_type": source_type(path),
        "ticker_column_detected": "",
        "dram_exact_found": False,
        "dram_alias_found": False,
        "matching_symbols": "",
        "latest_date_if_available": "",
        "row_count_if_available": 0,
        "usable_for_daily_ohlcv": False,
        "notes": "",
    }
    bridge = pd.DataFrame(columns=BRIDGE_COLUMNS)
    if path.suffix.lower() != ".csv":
        row["notes"] = "TEXT_REFERENCE_ONLY"
        return row, bridge
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        row["notes"] = f"CSV_READ_FAILED:{type(exc).__name__}"
        return row, bridge
    ticker_col = detect_ticker_col(df)
    row["ticker_column_detected"] = ticker_col or ""
    row["row_count_if_available"] = len(df)
    row["latest_date_if_available"] = latest_date(df)
    if ticker_col is None:
        row["notes"] = "NO_TICKER_COLUMN"
        return row, bridge
    exact, alias, matches, bdry = detect_dram_symbols(df[ticker_col])
    row["dram_exact_found"] = exact
    row["dram_alias_found"] = alias
    row["matching_symbols"] = "|".join(matches)
    row["usable_for_daily_ohlcv"] = bool((exact or alias) and usable_ohlcv(df, ticker_col))
    notes = []
    if bdry:
        notes.append("BDRY_NON_MATCH_FOUND")
    if row["usable_for_daily_ohlcv"]:
        bridge = normalize_bridge_rows(df, ticker_col)
        if bridge.empty:
            row["usable_for_daily_ohlcv"] = False
            notes.append("OHLCV_SCHEMA_PRESENT_BUT_NO_USABLE_DRAM_ROWS")
    row["notes"] = "|".join(notes)
    return row, bridge


def dram_availability_audit(price_panel: pd.DataFrame, ranking_files: dict[str, v174.RankingInput]) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    rows: list[dict[str, Any]] = []
    bridge_parts: list[pd.DataFrame] = []

    if not price_panel.empty:
        exact, alias, matches, bdry = detect_dram_symbols(price_panel["ticker"])
        dram_rows = price_panel[price_panel["ticker"].astype(str).str.upper().str.strip().isin({"DRAM", *DRAM_ALIASES})]
        rows.append(
            {
                "source_file": rel(PRICE_PATH),
                "source_type": "price_panel",
                "ticker_column_detected": "ticker",
                "dram_exact_found": exact,
                "dram_alias_found": alias,
                "matching_symbols": "|".join(matches),
                "latest_date_if_available": latest_date(dram_rows) if not dram_rows.empty else latest_date(price_panel),
                "row_count_if_available": len(dram_rows),
                "usable_for_daily_ohlcv": bool(not dram_rows.empty and usable_ohlcv(price_panel, "ticker")),
                "notes": "CANONICAL_PANEL_NOT_MUTATED" + ("|BDRY_NON_MATCH_FOUND" if bdry else ""),
            }
        )
    for state, inp in ranking_files.items():
        exact, alias, matches, bdry = detect_dram_symbols(inp.frame["ticker"])
        rows.append(
            {
                "source_file": rel(inp.path),
                "source_type": "ranking",
                "ticker_column_detected": "ticker",
                "dram_exact_found": exact,
                "dram_alias_found": alias,
                "matching_symbols": "|".join(matches),
                "latest_date_if_available": latest_date(inp.frame),
                "row_count_if_available": int((inp.frame["ticker"].astype(str).str.upper().str.strip() == "DRAM").sum()),
                "usable_for_daily_ohlcv": False,
                "notes": f"ranking_state={state}" + ("|BDRY_NON_MATCH_FOUND" if bdry else ""),
            }
        )

    already = {Path(r["source_file"]).name for r in rows}
    for path in rg_dram_files():
        if path.name in already and path.resolve() == PRICE_PATH.resolve():
            continue
        audit, bridge = audit_file(path)
        rows.append(audit)
        if audit["usable_for_daily_ohlcv"] and path.resolve() != PRICE_PATH.resolve() and not bridge.empty:
            bridge_parts.append(bridge)

    audit_df = pd.DataFrame(rows)
    bridge_df = pd.concat(bridge_parts, ignore_index=True) if bridge_parts else pd.DataFrame(columns=BRIDGE_COLUMNS)
    if not bridge_df.empty:
        bridge_df = bridge_df.sort_values("date").drop_duplicates(["date", "ticker"], keep="last")[BRIDGE_COLUMNS]
    ranking_found = bool(audit_df.query("source_type == 'ranking'")["dram_exact_found"].any()) if not audit_df.empty else False
    price_found = bool(
        audit_df.query("source_type == 'price_panel' and usable_for_daily_ohlcv == True")["dram_exact_found"].any()
    ) if not audit_df.empty else False
    alias_found = bool(audit_df["dram_alias_found"].any()) if not audit_df.empty else False
    external_ohlcv = not bridge_df.empty
    if ranking_found and price_found:
        classification = "DRAM_FOUND_IN_RANKING_AND_PRICE"
    elif ranking_found:
        classification = "DRAM_FOUND_IN_RANKING_ONLY"
    elif price_found:
        classification = "DRAM_FOUND_IN_PRICE_ONLY"
    elif alias_found:
        classification = "DRAM_SYMBOL_ALIAS_SUSPECTED"
    elif external_ohlcv:
        classification = "DRAM_PRICE_BRIDGE_REQUIRED"
    else:
        classification = "DRAM_NOT_FOUND_ANYWHERE"
    return audit_df, bridge_df, classification


def create_bridge_file(bridge_df: pd.DataFrame, out_dir: Path = OUT) -> bool:
    out_dir.mkdir(parents=True, exist_ok=True)
    if bridge_df.empty:
        pd.DataFrame(columns=BRIDGE_COLUMNS).to_csv(out_dir / "dram_price_bridge_daily_ohlcv.csv", index=False)
        return False
    bridge_df[BRIDGE_COLUMNS].to_csv(out_dir / "dram_price_bridge_daily_ohlcv.csv", index=False)
    return True


def prior_outputs_available(prior_dir: Path = V174_OUT) -> bool:
    return (prior_dir / "execution_trade_plan_ledger.csv").exists() and (prior_dir / "execution_simulation_results.csv").exists()


def stop_tp_integrity_audit(prior_dir: Path = V174_OUT) -> tuple[pd.DataFrame, bool, bool]:
    plan = read_csv(prior_dir / "execution_trade_plan_ledger.csv")
    sim = read_csv(prior_dir / "execution_simulation_results.csv")
    path_audit = read_csv(prior_dir / "stop_take_profit_path_audit.csv")
    rows: list[dict[str, Any]] = []

    missing_plan = sorted(REQUIRED_PLAN_COLS - set(plan.columns))
    rows.append({"check_name": "plan_required_columns_present", "passed": not missing_plan, "severity": "ERROR" if missing_plan else "INFO", "details": "|".join(missing_plan)})
    missing_sim = sorted(REQUIRED_SIM_COLS - set(sim.columns))
    rows.append({"check_name": "simulation_required_columns_present", "passed": not missing_sim, "severity": "ERROR" if missing_sim else "INFO", "details": "|".join(missing_sim)})
    path_rows = len(path_audit)
    rows.append({"check_name": "path_audit_rows_present", "passed": path_rows > 0, "severity": "WARN" if path_rows == 0 else "INFO", "details": f"path_audit_rows={path_rows}"})
    if not plan.empty and REQUIRED_PLAN_COLS.issubset(plan.columns):
        null_thresholds = int(plan[["stop_loss", "take_profit_1", "take_profit_2"]].isna().any(axis=1).sum())
        rows.append({"check_name": "stop_tp_columns_not_null", "passed": null_thresholds == 0, "severity": "ERROR" if null_thresholds else "INFO", "details": f"null_threshold_rows={null_thresholds}"})
        wide_ratio = ((pd.to_numeric(plan["take_profit_1"], errors="coerce") - pd.to_numeric(plan["planned_entry"], errors="coerce")) / pd.to_numeric(plan["planned_entry"], errors="coerce")).median()
        rows.append({"check_name": "threshold_width_diagnostic", "passed": True, "severity": "INFO", "details": f"median_tp1_distance_pct={wide_ratio:.6f}" if pd.notna(wide_ratio) else "median_tp1_distance_pct=nan"})
    else:
        rows.append({"check_name": "stop_tp_columns_not_null", "passed": False, "severity": "ERROR", "details": "plan empty or missing required columns"})
    if not sim.empty and "exit_reason" in sim.columns:
        stop_tp_total = int(sim["exit_reason"].isin(["STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2"]).sum())
        zero_confirmed = stop_tp_total == 0
        rows.append({"check_name": "v21_174_stop_tp_zero_confirmed", "passed": zero_confirmed, "severity": "INFO", "details": f"stop_tp_total={stop_tp_total}"})
        if "horizon" in sim.columns:
            rows.append({"check_name": "horizon_grouping_present", "passed": sim["horizon"].notna().any(), "severity": "INFO", "details": "|".join(sorted(sim["horizon"].dropna().astype(str).unique()))})
    else:
        zero_confirmed = False
        rows.append({"check_name": "v21_174_stop_tp_zero_confirmed", "passed": False, "severity": "ERROR", "details": "simulation empty or exit_reason missing"})
    if not path_audit.empty and {"bar_date", "stop_loss", "take_profit_1", "take_profit_2"}.issubset(path_audit.columns):
        touched = int(path_audit[["stop_touched", "tp1_touched", "tp2_touched"]].astype(str).apply(lambda s: s.str.lower().eq("true")).any(axis=1).sum()) if {"stop_touched", "tp1_touched", "tp2_touched"}.issubset(path_audit.columns) else 0
        rows.append({"check_name": "path_audit_trigger_flags_available", "passed": True, "severity": "INFO", "details": f"trigger_touch_rows={touched}"})
    else:
        rows.append({"check_name": "path_audit_trigger_flags_available", "passed": False, "severity": "WARN", "details": "trigger columns missing or path audit empty"})
    audit = pd.DataFrame(rows)
    integrity_passed = not audit[audit["severity"].eq("ERROR")]["passed"].eq(False).any()
    return audit, zero_confirmed, bool(integrity_passed)


def variant_plan(plan_row: pd.Series, variant: str) -> dict[str, Any]:
    params = VARIANTS[variant]
    row = plan_row.to_dict()
    base_risk = float(row["risk_per_share"])
    risk = base_risk * params["stop_atr_mult"]
    entry = float(row["planned_entry"])
    row["stop_loss"] = entry - risk
    row["take_profit_1"] = entry + params["tp1_r_mult"] * risk
    row["take_profit_2"] = entry + params["tp2_r_mult"] * risk
    row["risk_per_share"] = risk
    row["reward_risk_to_tp1"] = params["tp1_r_mult"]
    row["trade_allowed"] = str(row.get("trade_allowed")).lower() in {"true", "1", "yes"} or row.get("trade_allowed") is True
    return row


def replay_sensitivity(plan_df: pd.DataFrame, prices: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    sim_rows: list[dict[str, Any]] = []
    if plan_df.empty or not REQUIRED_PLAN_COLS.issubset(plan_df.columns):
        return pd.DataFrame(), pd.DataFrame()
    valid = plan_df[plan_df["trade_allowed"].astype(str).str.lower().isin(["true", "1", "yes"])].copy()
    for variant in VARIANTS:
        for hlabel, hdays in v174.HORIZONS.items():
            sims: list[dict[str, Any]] = []
            for _, plan_row in valid.iterrows():
                plan = variant_plan(plan_row, variant)
                sim, _audit = v174.simulate_trade(plan, prices.get(str(plan["ticker"]).upper(), pd.DataFrame()), hlabel, hdays)
                sim["variant"] = variant
                sims.append(sim)
                sim_rows.append(sim)
            sdf = pd.DataFrame(sims)
            filled = sdf[sdf["filled"].astype(bool)] if not sdf.empty and "filled" in sdf.columns else pd.DataFrame()
            pnl = pd.to_numeric(filled.get("realistic_pnl_pct", pd.Series(dtype=float)), errors="coerce")
            rows.append(
                {
                    "variant": variant,
                    "horizon": hlabel,
                    "valid_plan_count": len(valid),
                    "filled_count": int(sdf["filled"].astype(bool).sum()) if not sdf.empty else 0,
                    "no_fill_count": int(sdf["exit_reason"].eq("NO_FILL").sum()) if not sdf.empty else 0,
                    "stop_loss_count": int(sdf["exit_reason"].eq("STOP_LOSS").sum()) if not sdf.empty else 0,
                    "tp1_count": int(sdf["exit_reason"].eq("TAKE_PROFIT_1").sum()) if not sdf.empty else 0,
                    "tp2_count": int(sdf["exit_reason"].eq("TAKE_PROFIT_2").sum()) if not sdf.empty else 0,
                    "horizon_exit_count": int(sdf["exit_reason"].eq("HORIZON_EXIT").sum()) if not sdf.empty else 0,
                    "avg_realistic_pnl_pct": float(pnl.mean()) if not pnl.empty else np.nan,
                    "median_realistic_pnl_pct": float(pnl.median()) if not pnl.empty else np.nan,
                    "win_rate": float((pnl > 0).mean()) if not pnl.empty else np.nan,
                    "avg_mae_pct": float(pd.to_numeric(filled.get("max_adverse_excursion_pct", pd.Series(dtype=float)), errors="coerce").mean()) if not filled.empty else np.nan,
                    "avg_mfe_pct": float(pd.to_numeric(filled.get("max_favorable_excursion_pct", pd.Series(dtype=float)), errors="coerce").mean()) if not filled.empty else np.nan,
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(sim_rows)


def horizon_exit_attribution(sim_replay: pd.DataFrame) -> pd.DataFrame:
    if sim_replay.empty:
        return pd.DataFrame(columns=["strategy_state", "horizon", "count", "avg_realistic_pnl_pct", "median_realistic_pnl_pct", "win_rate", "avg_mae_pct", "avg_mfe_pct"])
    base = sim_replay[(sim_replay["variant"].eq("BASE")) & (sim_replay["exit_reason"].eq("HORIZON_EXIT"))].copy()
    if base.empty:
        return pd.DataFrame(columns=["strategy_state", "horizon", "count", "avg_realistic_pnl_pct", "median_realistic_pnl_pct", "win_rate", "avg_mae_pct", "avg_mfe_pct"])
    rows = []
    for (state, horizon), g in base.groupby(["strategy_state", "horizon"]):
        pnl = pd.to_numeric(g["realistic_pnl_pct"], errors="coerce")
        rows.append(
            {
                "strategy_state": state,
                "horizon": horizon,
                "count": len(g),
                "avg_realistic_pnl_pct": float(pnl.mean()),
                "median_realistic_pnl_pct": float(pnl.median()),
                "win_rate": float((pnl > 0).mean()),
                "avg_mae_pct": float(pd.to_numeric(g["max_adverse_excursion_pct"], errors="coerce").mean()),
                "avg_mfe_pct": float(pd.to_numeric(g["max_favorable_excursion_pct"], errors="coerce").mean()),
            }
        )
    return pd.DataFrame(rows)


def blocked_summary(out_dir: Path = OUT) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=["source_file", "source_type", "ticker_column_detected", "dram_exact_found", "dram_alias_found", "matching_symbols", "latest_date_if_available", "row_count_if_available", "usable_for_daily_ohlcv", "notes"]).to_csv(out_dir / "dram_data_availability_audit.csv", index=False)
    pd.DataFrame(columns=BRIDGE_COLUMNS).to_csv(out_dir / "dram_price_bridge_daily_ohlcv.csv", index=False)
    pd.DataFrame(columns=["check_name", "passed", "severity", "details"]).to_csv(out_dir / "stop_tp_path_integrity_audit.csv", index=False)
    pd.DataFrame().to_csv(out_dir / "stop_tp_sensitivity_summary.csv", index=False)
    pd.DataFrame().to_csv(out_dir / "horizon_exit_attribution.csv", index=False)
    summary = {
        "final_status": "BLOCKED_V21_174_R1A_MISSING_V21_174_OUTPUTS",
        "decision": "BLOCKED_MISSING_PRIOR_OUTPUTS",
        "latest_price_date_used": "",
        "dram_data_classification": "DRAM_NOT_FOUND_ANYWHERE",
        "dram_price_bridge_created": False,
        "dram_usable_daily_ohlcv_found": False,
        "stop_tp_zero_confirmed": False,
        "stop_tp_path_integrity_passed": False,
        "base_stop_loss_count": 0,
        "base_tp1_count": 0,
        "base_tp2_count": 0,
        "tight_stop_loss_count": 0,
        "tight_tp1_count": 0,
        "tight_tp2_count": 0,
        "wide_stop_loss_count": 0,
        "wide_tp1_count": 0,
        "wide_tp2_count": 0,
        "horizon_exit_count": 0,
        "warnings": ["BLOCKED_MISSING_PRIOR_OUTPUTS"],
        "daily_proxy_only": True,
        "intraday_claim_allowed": False,
        **POLICY,
    }
    (out_dir / "V21.174_R1A_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out_dir / "V21.174_R1A_readable_report.txt").write_text("BLOCKED_MISSING_PRIOR_OUTPUTS\n", encoding="utf-8")
    return summary


def counts_for(summary_df: pd.DataFrame, variant: str) -> tuple[int, int, int]:
    if summary_df.empty:
        return 0, 0, 0
    s = summary_df[summary_df["variant"].eq(variant)]
    return int(s["stop_loss_count"].sum()), int(s["tp1_count"].sum()), int(s["tp2_count"].sum())


def write_report(summary: dict[str, Any], horizon_attr: pd.DataFrame, out_dir: Path = OUT) -> None:
    lines = [
        STAGE,
        f"final_status: {summary['final_status']}",
        f"decision: {summary['decision']}",
        f"latest_price_date_used: {summary['latest_price_date_used']}",
        f"dram_data_classification: {summary['dram_data_classification']}",
        f"dram_price_bridge_created: {summary['dram_price_bridge_created']}",
        f"stop_tp_zero_confirmed: {summary['stop_tp_zero_confirmed']}",
        f"stop_tp_path_integrity_passed: {summary['stop_tp_path_integrity_passed']}",
        f"BASE stop/tp1/tp2: {summary['base_stop_loss_count']} / {summary['base_tp1_count']} / {summary['base_tp2_count']}",
        f"TIGHT stop/tp1/tp2: {summary['tight_stop_loss_count']} / {summary['tight_tp1_count']} / {summary['tight_tp2_count']}",
        f"WIDE stop/tp1/tp2: {summary['wide_stop_loss_count']} / {summary['wide_tp1_count']} / {summary['wide_tp2_count']}",
        f"horizon_exit_count: {summary['horizon_exit_count']}",
        "horizon_exit_attribution:",
    ]
    if horizon_attr.empty:
        lines.append("- none")
    else:
        for _, r in horizon_attr.head(20).iterrows():
            lines.append(f"- {r['strategy_state']} {r['horizon']}: count={r['count']} avg_pnl={r['avg_realistic_pnl_pct']:.6f} win_rate={r['win_rate']:.3f}")
    lines.extend(["warnings:", *([f"- {w}" for w in summary["warnings"]] if summary["warnings"] else ["- none"])])
    lines.extend(["daily_proxy_only: True", "intraday_claim_allowed: False", "research_only: True", "official_adoption_allowed: False", "broker_action_allowed: False", "protected_outputs_modified: False", "canonical_price_panel_modified: False"])
    (out_dir / "V21.174_R1A_readable_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(prior_dir: Path = V174_OUT, out_dir: Path = OUT) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    pre_price_hash = sha(PRICE_PATH)
    if not prior_outputs_available(prior_dir):
        blocked_summary(out_dir)
        return 0

    panel, prices, _dates, latest = v174.load_price_data()
    rankings, ranking_warnings = v174.discover_rankings()
    audit_df, bridge_df, dram_classification = dram_availability_audit(panel, rankings)
    audit_df.to_csv(out_dir / "dram_data_availability_audit.csv", index=False)
    bridge_created = create_bridge_file(bridge_df, out_dir)

    integrity, stop_zero, integrity_passed = stop_tp_integrity_audit(prior_dir)
    integrity.to_csv(out_dir / "stop_tp_path_integrity_audit.csv", index=False)
    plan = read_csv(prior_dir / "execution_trade_plan_ledger.csv")
    sensitivity, replay = replay_sensitivity(plan, prices)
    sensitivity.to_csv(out_dir / "stop_tp_sensitivity_summary.csv", index=False)
    horizon_attr = horizon_exit_attribution(replay)
    horizon_attr.to_csv(out_dir / "horizon_exit_attribution.csv", index=False)

    base_stop, base_tp1, base_tp2 = counts_for(sensitivity, "BASE")
    tight_stop, tight_tp1, tight_tp2 = counts_for(sensitivity, "TIGHT")
    wide_stop, wide_tp1, wide_tp2 = counts_for(sensitivity, "WIDE")
    warnings = list(ranking_warnings)
    all_zero = sum([base_stop, base_tp1, base_tp2, tight_stop, tight_tp1, tight_tp2, wide_stop, wide_tp1, wide_tp2]) == 0
    base_zero = sum([base_stop, base_tp1, base_tp2]) == 0
    tight_active = sum([tight_stop, tight_tp1, tight_tp2]) > 0
    if all_zero:
        warnings.append("WARN_STOP_TP_PATH_OR_THRESHOLD_REQUIRES_REVIEW")
    elif base_zero and tight_active:
        warnings.append("INFO_BASE_THRESHOLDS_WIDE_BUT_PATH_LOGIC_ACTIVE")

    post_price_hash = sha(PRICE_PATH)
    canonical_modified = pre_price_hash != post_price_hash
    dram_usable = bool(bridge_created or dram_classification in {"DRAM_FOUND_IN_RANKING_AND_PRICE", "DRAM_FOUND_IN_PRICE_ONLY"})
    if all_zero and not integrity_passed:
        final_status = "WARN_V21_174_R1A_STOP_TP_PATH_REVIEW_REQUIRED"
        decision = "STOP_TP_PATH_REVIEW_REQUIRED"
    elif dram_usable:
        final_status = "PASS_V21_174_R1A_DRAM_BRIDGE_AND_STOP_TP_DIAGNOSTIC_READY"
        decision = "DRAM_BRIDGE_READY_EXECUTION_DIAGNOSTIC_READY"
    else:
        final_status = "PARTIAL_PASS_V21_174_R1A_STOP_TP_DIAGNOSTIC_READY_DRAM_STILL_MISSING"
        decision = "STOP_TP_DIAGNOSTIC_READY_DRAM_DATA_STILL_REQUIRED"

    summary = {
        "final_status": final_status,
        "decision": decision,
        "latest_price_date_used": latest,
        "dram_data_classification": dram_classification,
        "dram_price_bridge_created": bridge_created,
        "dram_usable_daily_ohlcv_found": dram_usable,
        "stop_tp_zero_confirmed": stop_zero,
        "stop_tp_path_integrity_passed": integrity_passed,
        "base_stop_loss_count": base_stop,
        "base_tp1_count": base_tp1,
        "base_tp2_count": base_tp2,
        "tight_stop_loss_count": tight_stop,
        "tight_tp1_count": tight_tp1,
        "tight_tp2_count": tight_tp2,
        "wide_stop_loss_count": wide_stop,
        "wide_tp1_count": wide_tp1,
        "wide_tp2_count": wide_tp2,
        "horizon_exit_count": int(sensitivity["horizon_exit_count"].sum()) if not sensitivity.empty else 0,
        "warnings": warnings,
        "daily_proxy_only": True,
        "intraday_claim_allowed": False,
        **{**POLICY, "canonical_price_panel_modified": canonical_modified},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(out_dir),
    }
    (out_dir / "V21.174_R1A_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_report(summary, horizon_attr, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
