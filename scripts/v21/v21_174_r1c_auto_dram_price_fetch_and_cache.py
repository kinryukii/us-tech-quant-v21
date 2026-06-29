from __future__ import annotations

import hashlib
import importlib
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

from scripts.v21 import v21_174_r1b_manual_dram_price_ingestion_and_watchlist_trade_anchor as r1b
from scripts.v21 import v21_174_realistic_execution_backtest_and_tactical_trade_engine_r1 as v174


STAGE = "V21.174_R1C_AUTO_DRAM_PRICE_FETCH_AND_CACHE"
OUT = ROOT / "outputs" / "v21" / STAGE
PRICE_PATH = v174.PRICE_PATH
BRIDGE_COLUMNS = ["date", "ticker", "open", "high", "low", "close", "volume"]
BRIDGE_SOURCE_COLUMNS = BRIDGE_COLUMNS + ["source_method"]

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "canonical_price_panel_modified": False,
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


def flatten_yfinance_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        flat = []
        for col in df.columns:
            parts = [str(x) for x in col if str(x) and str(x).lower() != "nan"]
            flat.append(parts[0] if parts else "")
        df = df.copy()
        df.columns = flat
    return df


def normalize_auto_ohlcv(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str], str]:
    warnings: list[str] = []
    if raw.empty:
        return pd.DataFrame(columns=BRIDGE_COLUMNS), ["WARN_AUTO_FETCH_EMPTY"], "AUTO_EMPTY"
    df = flatten_yfinance_columns(raw).copy()
    if "Date" not in df.columns and "date" not in {str(c).lower() for c in df.columns}:
        if df.index.name is not None or not isinstance(df.index, pd.RangeIndex):
            df = df.reset_index()
    aliases = r1b.column_lookup(df)
    missing = [c for c in ["date", "open", "high", "low", "close"] if c not in aliases]
    if missing:
        return pd.DataFrame(columns=BRIDGE_COLUMNS), [f"WARN_AUTO_MISSING_REQUIRED_COLUMNS:{'|'.join(missing)}"], "AUTO_MISSING_REQUIRED_COLUMNS"
    vol = pd.to_numeric(df[aliases["volume"]], errors="coerce").fillna(0) if "volume" in aliases else 0
    if "volume" not in aliases:
        warnings.append("WARN_VOLUME_MISSING")
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[aliases["date"]], errors="coerce"),
            "ticker": "DRAM",
            "open": pd.to_numeric(df[aliases["open"]], errors="coerce"),
            "high": pd.to_numeric(df[aliases["high"]], errors="coerce"),
            "low": pd.to_numeric(df[aliases["low"]], errors="coerce"),
            "close": pd.to_numeric(df[aliases["close"]], errors="coerce"),
            "volume": vol,
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
        return pd.DataFrame(columns=BRIDGE_COLUMNS), warnings + ["WARN_NO_VALID_DRAM_ROWS"], "AUTO_NO_VALID_ROWS"
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out = out.sort_values("date").drop_duplicates(["date", "ticker"], keep="last")
    return out[BRIDGE_COLUMNS].reset_index(drop=True), warnings, "USABLE"


def fetch_yfinance(fetcher: Any | None = None, cache_dir: Path | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    audit = {
        "fetch_method": "yfinance",
        "attempted": True,
        "success": False,
        "source": "DRAM",
        "error_message": "",
        "row_count_raw": 0,
        "row_count_valid": 0,
        "first_date": "",
        "latest_date": "",
        "warnings": "",
        "notes": "",
    }
    try:
        yf = fetcher if fetcher is not None else importlib.import_module("yfinance")
    except Exception as exc:
        audit["error_message"] = f"YFINANCE_IMPORT_FAILED:{type(exc).__name__}:{exc}"
        audit["notes"] = "manual_fallback_allowed"
        return pd.DataFrame(columns=BRIDGE_COLUMNS), audit
    try:
        cache = cache_dir or (OUT / "yfinance_cache")
        cache.mkdir(parents=True, exist_ok=True)
        if hasattr(yf, "set_tz_cache_location"):
            yf.set_tz_cache_location(str(cache))
        if hasattr(yf, "download"):
            raw = yf.download("DRAM", start="2026-04-01", progress=False, auto_adjust=False)
        else:
            raw = yf.Ticker("DRAM").history(period="6mo", auto_adjust=False)
        audit["row_count_raw"] = len(raw)
        norm, warnings, status = normalize_auto_ohlcv(raw)
        audit["row_count_valid"] = len(norm)
        audit["warnings"] = "|".join(warnings)
        audit["notes"] = status
        if not norm.empty:
            audit["success"] = True
            audit["first_date"] = str(norm["date"].min())
            audit["latest_date"] = str(norm["date"].max())
        elif not audit["error_message"]:
            audit["error_message"] = "YFINANCE_RETURNED_EMPTY_OR_INVALID_OHLCV"
        return norm, audit
    except Exception as exc:
        audit["error_message"] = f"YFINANCE_FETCH_FAILED:{type(exc).__name__}:{exc}"
        audit["notes"] = "manual_fallback_allowed"
        return pd.DataFrame(columns=BRIDGE_COLUMNS), audit


def manual_fallback(root: Path = ROOT) -> tuple[pd.DataFrame, str, list[str]]:
    _audit, bridge, source_path, warnings = r1b.audit_manual_inputs(r1b.manual_paths(root))
    return bridge, rel(source_path) if source_path else "", warnings


def anchor_for_source(bridge: pd.DataFrame, source_method: str, warnings: list[str]) -> pd.DataFrame:
    anchor = r1b.build_anchor(bridge, warnings)
    if not anchor.empty:
        anchor["source_method"] = source_method
        if anchor.iloc[0]["final_decision"] == "DRAM_DAILY_TACTICAL_ANCHOR_READY":
            anchor.loc[anchor.index[0], "final_decision"] = (
                "DRAM_AUTO_TACTICAL_ANCHOR_READY" if source_method == "AUTO_YFINANCE" else "DRAM_MANUAL_FALLBACK_ANCHOR_READY"
            )
        elif bridge.empty:
            anchor.loc[anchor.index[0], "final_decision"] = "DRAM_AUTO_FETCH_FAILED"
    return anchor


def replay_with_source(bridge: pd.DataFrame, source_method: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    results, audit = r1b.replay_manual_dram(bridge)
    if not results.empty:
        results["source_method"] = source_method
    if not audit.empty:
        audit["source_method"] = source_method
    return results, audit


def latest_plan(anchor: pd.DataFrame) -> pd.DataFrame:
    base = r1b.latest_trade_plan(anchor)
    if not base.empty:
        row = anchor.iloc[0] if not anchor.empty else {}
        base["atr14"] = row.get("atr14", np.nan) if hasattr(row, "get") else np.nan
        base["source_method"] = row.get("source_method", "") if hasattr(row, "get") else ""
        cols = [
            "latest_date",
            "ticker",
            "latest_close",
            "atr14",
            "planned_entry_base",
            "planned_entry_tight",
            "no_chase_above",
            "stop_loss_base",
            "stop_loss_tight",
            "take_profit_1_base",
            "take_profit_2_base",
            "take_profit_1_tight",
            "take_profit_2_tight",
            "source_method",
            "final_decision",
            "trade_allowed_daily_proxy",
            "invalid_reason",
            "daily_proxy_only",
            "intraday_claim_allowed",
            "official_adoption_allowed",
            "broker_action_allowed",
        ]
        base = base.reindex(columns=cols)
    return base


def count(audit: pd.DataFrame, variant: str, col: str) -> int:
    if audit.empty or col not in audit.columns:
        return 0
    return int(audit[audit["variant"].eq(variant)][col].sum())


def final_status_decision(
    source_method: str,
    valid_rows: int,
    anchor_created: bool,
    replay_created: bool,
    auto_success: bool,
    data_existed_but_invalid: bool,
) -> tuple[str, str]:
    if source_method == "AUTO_YFINANCE" and auto_success and valid_rows >= 30 and anchor_created and replay_created:
        return "PASS_V21_174_R1C_AUTO_DRAM_PRICE_READY", "DRAM_AUTO_PRICE_READY_DAILY_PROXY"
    if source_method == "MANUAL_FALLBACK" and valid_rows >= 30 and anchor_created and replay_created:
        return "PARTIAL_PASS_V21_174_R1C_USED_MANUAL_FALLBACK", "DRAM_PRICE_READY_FROM_MANUAL_FALLBACK"
    if data_existed_but_invalid and valid_rows == 0:
        return "BLOCKED_V21_174_R1C_INVALID_PRICE_DATA", "DRAM_PRICE_DATA_INVALID"
    if 0 < valid_rows < 30:
        return "WARN_V21_174_R1C_INSUFFICIENT_DRAM_HISTORY", "DRAM_DATA_INSUFFICIENT_HISTORY"
    return "WARN_V21_174_R1C_AUTO_FETCH_FAILED_WAIT_MANUAL_INPUT", "WAIT_MANUAL_DRAM_DAILY_OHLCV_INPUT"


def write_report(summary: dict[str, Any], out_dir: Path = OUT) -> None:
    lines = [
        STAGE,
        f"final_status: {summary['final_status']}",
        f"decision: {summary['decision']}",
        f"auto_fetch_attempted: {summary['auto_fetch_attempted']}",
        f"auto_fetch_success: {summary['auto_fetch_success']}",
        f"source_method_used: {summary['source_method_used']}",
        f"valid_row_count: {summary['valid_row_count']}",
        f"latest_dram_date: {summary['latest_dram_date']}",
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
    (out_dir / "V21.174_R1C_readable_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(root: Path = ROOT, out_dir: Path = OUT, fetcher: Any | None = None) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    pre_hash = sha(PRICE_PATH)

    auto_df, auto_audit = fetch_yfinance(fetcher)
    pd.DataFrame([auto_audit]).to_csv(out_dir / "dram_auto_fetch_audit.csv", index=False)
    if auto_audit["success"]:
        auto_df.to_csv(out_dir / "dram_auto_price_cache_daily_ohlcv.csv", index=False)
    else:
        pd.DataFrame(columns=BRIDGE_COLUMNS).to_csv(out_dir / "dram_auto_price_cache_daily_ohlcv.csv", index=False)

    manual_df = pd.DataFrame(columns=BRIDGE_COLUMNS)
    manual_source = ""
    manual_warnings: list[str] = []
    manual_used = False
    if not auto_audit["success"]:
        manual_df, manual_source, manual_warnings = manual_fallback(root)
        manual_used = not manual_df.empty

    if not auto_df.empty:
        bridge = auto_df.copy()
        source_method = "AUTO_YFINANCE"
    elif not manual_df.empty:
        bridge = manual_df.copy()
        source_method = "MANUAL_FALLBACK"
    else:
        bridge = pd.DataFrame(columns=BRIDGE_COLUMNS)
        source_method = "NONE"
    bridge_with_source = bridge.copy()
    if bridge_with_source.empty:
        bridge_with_source = pd.DataFrame(columns=BRIDGE_SOURCE_COLUMNS)
    else:
        bridge_with_source["source_method"] = source_method
        bridge_with_source = bridge_with_source[BRIDGE_SOURCE_COLUMNS]
    bridge_with_source.to_csv(out_dir / "dram_auto_price_bridge_daily_ohlcv.csv", index=False)

    warnings = []
    warnings.extend([w for w in str(auto_audit.get("warnings", "")).split("|") if w])
    warnings.extend(manual_warnings)
    if not auto_audit["success"]:
        warnings.append("WARN_AUTO_FETCH_FAILED")
    if not bridge.empty and len(bridge) < 30:
        warnings.append("WARN_INSUFFICIENT_DRAM_HISTORY")

    anchor = anchor_for_source(bridge, source_method, warnings)
    anchor.to_csv(out_dir / "dram_daily_tactical_anchor.csv", index=False)
    replay, stop_audit = replay_with_source(bridge, source_method)
    replay.to_csv(out_dir / "dram_execution_simulation_results.csv", index=False)
    stop_audit.to_csv(out_dir / "dram_stop_tp_path_audit.csv", index=False)
    plan = latest_plan(anchor)
    plan.to_csv(out_dir / "dram_tactical_trade_plan_latest.csv", index=False)

    valid_rows = len(bridge)
    latest_date = str(bridge["date"].max()) if not bridge.empty else ""
    latest_decision = str(plan.iloc[0]["final_decision"]) if not plan.empty else "DRAM_AUTO_FETCH_FAILED"
    anchor_created = latest_decision in {"DRAM_AUTO_TACTICAL_ANCHOR_READY", "DRAM_MANUAL_FALLBACK_ANCHOR_READY"}
    replay_created = not replay.empty
    data_existed_but_invalid = bool(auto_audit["row_count_raw"] > 0 and auto_audit["row_count_valid"] == 0 and not manual_used)
    final_status, decision = final_status_decision(
        source_method, valid_rows, anchor_created, replay_created, bool(auto_audit["success"]), data_existed_but_invalid
    )
    post_hash = sha(PRICE_PATH)
    summary = {
        "final_status": final_status,
        "decision": decision,
        "auto_fetch_attempted": bool(auto_audit["attempted"]),
        "auto_fetch_success": bool(auto_audit["success"]),
        "auto_fetch_method": "yfinance",
        "auto_fetch_error": auto_audit["error_message"],
        "manual_fallback_used": manual_used,
        "source_method_used": source_method,
        "valid_row_count": valid_rows,
        "latest_dram_date": latest_date,
        "dram_auto_cache_created": bool(auto_audit["success"]),
        "dram_price_bridge_created": not bridge.empty,
        "dram_tactical_anchor_created": anchor_created,
        "dram_execution_replay_created": replay_created,
        "dram_latest_final_decision": latest_decision,
        "base_filled_count": count(stop_audit, "BASE", "filled_count"),
        "base_stop_loss_count": count(stop_audit, "BASE", "stop_loss_count"),
        "base_tp1_count": count(stop_audit, "BASE", "tp1_count"),
        "base_tp2_count": count(stop_audit, "BASE", "tp2_count"),
        "tight_filled_count": count(stop_audit, "TIGHT", "filled_count"),
        "tight_stop_loss_count": count(stop_audit, "TIGHT", "stop_loss_count"),
        "tight_tp1_count": count(stop_audit, "TIGHT", "tp1_count"),
        "tight_tp2_count": count(stop_audit, "TIGHT", "tp2_count"),
        "warnings": sorted(set(warnings)),
        "daily_proxy_only": True,
        "intraday_claim_allowed": False,
        **{**POLICY, "canonical_price_panel_modified": pre_hash != post_hash},
        "manual_fallback_source_path": manual_source,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(out_dir),
    }
    (out_dir / "V21.174_R1C_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    write_report(summary, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
