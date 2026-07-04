from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.v21 import v21_179e_dram_intraday_replay_validation as replay


STAGE = "V21.180_DRAM_INTRADAY_CONFIRMATION_SNAPSHOT_RUNNER"
OUT = ROOT / "outputs" / "v21" / STAGE

V175_INTRADAY_1M = ROOT / "outputs" / "v21" / "V21.175_INTRADAY_CONFIRMATION_GATE_FOR_DRAM_R1" / "dram_intraday_ohlcv_1m.csv"
V178_PLAN = ROOT / "outputs" / "v21" / "V21.178_DAILY_DRAM_PLAN_CHAIN_ORCHESTRATOR_R1" / "dram_daily_chain_final_decision.csv"
V178_R1A_PLAN = ROOT / "outputs" / "v21" / "V21.178_R1A_DAILY_DRAM_CHAIN_EXECUTION_MODE" / "dram_daily_chain_final_decision_EXECUTION_MODE.csv"

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
}

FINAL_PASS = "PASS_V21_180_INTRADAY_SNAPSHOT_READY"
FINAL_PARTIAL = "PARTIAL_PASS_V21_180_INTRADAY_DATA_UNAVAILABLE"
FINAL_WARN = "WARN_V21_180_PLAN_OR_SIGNAL_INCOMPLETE"
FINAL_FAIL = "FAIL_V21_180_SNAPSHOT_NOT_SAFE"

EXECUTION_STATES = {
    "DATA_STALE_BLOCK",
    "PLAN_BLOCKED_INVALID_BOUNDS",
    "INTRADAY_DATA_UNAVAILABLE",
    "PLAN_READY_WAIT_MARKET",
    "WAIT_H1_CONFIRMATION",
    "WAIT_15M_SETUP",
    "WAIT_1M_TRIGGER",
    "ENTRY_ALLOWED",
    "NO_CHASE_BLOCK",
    "STOP_RISK_ACTIVE",
}


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def load_latest_plan(paths: list[Path] | None = None) -> tuple[dict[str, Any], str]:
    paths = paths or [V178_R1A_PLAN, V178_PLAN]
    frames = []
    source = ""
    for path in paths:
        df = replay.read_csv(path)
        if df.empty:
            continue
        df["_source_path"] = rel(path)
        frames.append(df)
    if not frames:
        return {}, ""
    raw = pd.concat(frames, ignore_index=True)
    lower = {str(c).strip().lower(): c for c in raw.columns}
    ticker_col = lower.get("ticker")
    if ticker_col:
        raw = raw[raw[ticker_col].astype(str).str.upper().str.strip().eq("DRAM")]
    run_col = lower.get("run_timestamp")
    if run_col:
        raw["_sort_ts"] = pd.to_datetime(raw[run_col], errors="coerce")
        raw = raw.sort_values("_sort_ts")
    row = raw.tail(1).iloc[0]
    source = str(row.get("_source_path", ""))

    def get(*names: str, default: Any = "") -> Any:
        for name in names:
            col = lower.get(name.lower())
            if col and col in row:
                return row[col]
        return default

    plan = {
        "ticker": "DRAM",
        "entry": float(get("planned_entry_base", default=np.nan)),
        "no_chase": float(get("no_chase_above", default=np.nan)),
        "stop": float(get("stop_loss_base", default=np.nan)),
        "latest_price_date_used": str(get("latest_price_date_used", "latest_price_date", default="")),
        "plan_date": str(get("latest_plan_date", "plan_date", default="")),
        "trade_plan_currentness": str(get("trade_plan_currentness", default="UNKNOWN")),
        "staleness_status": str(get("staleness_status", default="")),
        "refresh_required": str(get("refresh_required", default="False")).strip().lower() in {"true", "1", "yes"},
        "source_path": source,
    }
    return plan, source


def completed_intraday_snapshot(path: Path, as_of: pd.Timestamp | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = replay.normalize_intraday(replay.read_csv(path))
    if raw.empty:
        return raw, raw
    raw = raw.sort_values("datetime").reset_index(drop=True)
    cutoff = as_of if as_of is not None else pd.Timestamp(raw["bar_end"].max())
    completed = raw[raw["bar_end"].le(cutoff)].copy()
    # Exclude the most recent bar from live/manual snapshots because a cached feed can include an in-progress minute.
    if as_of is None and len(completed) > 0:
        completed = completed.iloc[:-1].copy()
    return raw, completed.reset_index(drop=True)


def evaluate_snapshot(plan: dict[str, Any], bars: pd.DataFrame, config: replay.ReplayConfig) -> tuple[dict[str, Any], pd.DataFrame]:
    entry = float(plan.get("entry", np.nan))
    no_chase = float(plan.get("no_chase", np.nan))
    stop = float(plan.get("stop", np.nan))
    latest_ts = "" if bars.empty else pd.Timestamp(bars.iloc[-1]["bar_end"])
    latest_price = np.nan if bars.empty else float(bars.iloc[-1]["close"])

    if not np.isfinite(entry) or not np.isfinite(no_chase) or not np.isfinite(stop) or not (stop < entry < no_chase):
        state = "PLAN_BLOCKED_INVALID_BOUNDS"
        h1 = "H1_NEUTRAL_WAIT"
        m15 = "M15_WAIT_PULLBACK"
        m1 = "M1_FALSE_BREAKOUT_WAIT"
    elif str(plan.get("trade_plan_currentness", "")).upper() not in {"CURRENT", "CURRENT_OR_RECENT"} or bool(plan.get("refresh_required", False)):
        state = "DATA_STALE_BLOCK"
        h1 = "H1_NEUTRAL_WAIT"
        m15 = "M15_WAIT_PULLBACK"
        m1 = "M1_FALSE_BREAKOUT_WAIT"
    elif bars.empty:
        state = "INTRADAY_DATA_UNAVAILABLE"
        h1 = "H1_NEUTRAL_WAIT"
        m15 = "M15_WAIT_PULLBACK"
        m1 = "M1_FALSE_BREAKOUT_WAIT"
    else:
        hard = replay.hard_execution_state(latest_price, no_chase, stop, config)
        if hard == "NO_CHASE_BLOCK":
            h1 = "H1_OVEREXTENDED_NO_CHASE"
            m15 = "M15_OVERHEATED_BLOCK"
            m1 = "M1_TOO_LATE_NO_CHASE"
            state = "NO_CHASE_BLOCK"
        elif hard == "STOP_RISK_ACTIVE":
            h1 = "H1_BEARISH_BLOCK"
            m15 = "M15_WAIT_PULLBACK"
            m1 = "M1_FALSE_BREAKOUT_WAIT"
            state = "STOP_RISK_ACTIVE"
        else:
            as_of = pd.Timestamp(latest_ts)
            h1_bars = replay.aggregate_completed(bars, as_of, "60min")
            m15_bars = replay.aggregate_completed(bars, as_of, "15min")
            h1 = replay.h1_signal(h1_bars, no_chase)
            m15 = replay.m15_signal(m15_bars, entry, no_chase)
            m1 = replay.m1_signal(bars[bars["bar_end"].le(as_of)], entry, no_chase)
            if latest_price < entry * (1 - config.entry_zone_pct):
                state = "PLAN_READY_WAIT_MARKET"
            elif h1 != "H1_BULLISH_CONFIRM":
                state = "WAIT_H1_CONFIRMATION"
            elif m15 != "M15_ENTRY_ZONE_VALID":
                state = "WAIT_15M_SETUP"
            elif m1 != "M1_TRIGGER_READY":
                state = "WAIT_1M_TRIGGER"
            else:
                state = "ENTRY_ALLOWED"

    signal_rows = pd.DataFrame(
        [
            {"timeframe": "1h", "signal_state": h1, "completed_bar_count": 0 if bars.empty else len(replay.aggregate_completed(bars, latest_ts, "60min")) if latest_ts != "" else 0},
            {"timeframe": "15m", "signal_state": m15, "completed_bar_count": 0 if bars.empty else len(replay.aggregate_completed(bars, latest_ts, "15min")) if latest_ts != "" else 0},
            {"timeframe": "1m", "signal_state": m1, "completed_bar_count": int(len(bars))},
        ]
    )
    snapshot = {
        "execution_state": state,
        "latest_completed_bar_end": "" if latest_ts == "" else str(latest_ts),
        "latest_completed_price": latest_price,
        "DRAM_ENTRY": entry,
        "DRAM_NO_CHASE": no_chase,
        "DRAM_STOP": stop,
        "latest_price_date_used": plan.get("latest_price_date_used", ""),
        "plan_date": plan.get("plan_date", ""),
        "trade_plan_currentness": plan.get("trade_plan_currentness", ""),
        "h1_signal": h1,
        "m15_signal": m15,
        "m1_signal": m1,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
    }
    if state not in EXECUTION_STATES:
        snapshot["execution_state"] = "DATA_STALE_BLOCK"
    return snapshot, signal_rows


def final_status(state: str, protected_changed: bool) -> str:
    if protected_changed:
        return FINAL_FAIL
    if state == "INTRADAY_DATA_UNAVAILABLE":
        return FINAL_PARTIAL
    if state in {"PLAN_BLOCKED_INVALID_BOUNDS", "DATA_STALE_BLOCK"}:
        return FINAL_WARN
    return FINAL_PASS


def run_stage(
    out_dir: Path = OUT,
    intraday_path: Path = V175_INTRADAY_1M,
    plan_paths: list[Path] | None = None,
    as_of: pd.Timestamp | None = None,
    config: replay.ReplayConfig = replay.ReplayConfig(),
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    before = replay.protected_hashes()
    plan, _ = load_latest_plan(plan_paths)
    raw_bars, bars = completed_intraday_snapshot(intraday_path, as_of)
    if not plan:
        plan = {
            "entry": np.nan,
            "no_chase": np.nan,
            "stop": np.nan,
            "latest_price_date_used": "",
            "plan_date": "",
            "trade_plan_currentness": "MISSING",
            "refresh_required": True,
            "source_path": "",
        }
    snapshot, signals = evaluate_snapshot(plan, bars, config)
    after = replay.protected_hashes()
    changed = [path for path, digest in before.items() if after.get(path) != digest]
    protected_changed = bool(changed)
    status = final_status(snapshot["execution_state"], protected_changed)
    if protected_changed:
        snapshot["execution_state"] = "DATA_STALE_BLOCK"
    snapshot = {
        "stage": STAGE,
        "final_status": status,
        **snapshot,
        "protected_outputs_modified": protected_changed,
        "changed_protected_paths": changed,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(out_dir / "dram_intraday_snapshot_state.json", snapshot)
    replay.write_csv(out_dir / "dram_intraday_snapshot_signal_table.csv", signals)
    dq = pd.DataFrame(
        [
            {
                "input_name": "latest_dram_daily_execution_plan",
                "path": plan.get("source_path", ""),
                "exists": bool(plan.get("source_path", "")),
                "row_count": 1 if plan.get("source_path", "") else 0,
                "status": "PASS" if plan.get("source_path", "") else "WARN_MISSING_PLAN",
            },
            {
                "input_name": "latest_dram_1m_intraday_data",
                "path": rel(intraday_path),
                "exists": intraday_path.exists(),
                "row_count_raw": int(len(raw_bars)),
                "row_count_completed_used": int(len(bars)),
                "excluded_latest_bar_as_unfinished": bool(len(raw_bars) > len(bars)),
                "first_completed_timestamp": "" if bars.empty else str(bars["datetime"].min()),
                "last_completed_bar_end": "" if bars.empty else str(bars["bar_end"].max()),
                "status": "PASS" if not bars.empty else "WARN_INTRADAY_DATA_UNAVAILABLE",
            },
        ]
    )
    replay.write_csv(out_dir / "dram_intraday_snapshot_data_quality_report.csv", dq)
    manifest = {
        "stage": STAGE,
        "final_status": status,
        "execution_state": snapshot["execution_state"],
        "signal_table_row_count": int(len(signals)),
        "exactly_one_execution_state_output": True,
        "intraday_completed_bar_count": int(len(bars)),
        "latest_price_date_used": snapshot.get("latest_price_date_used", ""),
        **{**POLICY, "protected_outputs_modified": protected_changed},
        "changed_protected_paths": changed,
        "output_directory": rel(out_dir),
        "created_at_utc": snapshot["created_at_utc"],
    }
    write_json(out_dir / "manifest.json", manifest)
    report = [
        STAGE,
        f"FINAL_STATUS={status}",
        f"execution_state={snapshot['execution_state']}",
        f"latest_completed_bar_end={snapshot['latest_completed_bar_end']}",
        f"latest_completed_price={snapshot['latest_completed_price']}",
        f"DRAM_ENTRY={snapshot['DRAM_ENTRY']}",
        f"DRAM_NO_CHASE={snapshot['DRAM_NO_CHASE']}",
        f"DRAM_STOP={snapshot['DRAM_STOP']}",
        f"trade_plan_currentness={snapshot['trade_plan_currentness']}",
        f"h1_signal={snapshot['h1_signal']}",
        f"m15_signal={snapshot['m15_signal']}",
        f"m1_signal={snapshot['m1_signal']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"protected_outputs_modified={str(protected_changed).lower()}",
    ]
    (out_dir / "V21.180_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    manifest = run_stage()
    print(json.dumps(manifest, indent=2, default=str))
    return 0 if not str(manifest.get("final_status", "")).startswith("FAIL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
