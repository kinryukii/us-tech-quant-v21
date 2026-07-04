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


STAGE = "V21.183_DRAM_INTRADAY_FORWARD_OUTCOME_UPDATER"
OUT = ROOT / "outputs" / "v21" / STAGE
V182 = ROOT / "outputs" / "v21" / "V21.182_DRAM_INTRADAY_FORWARD_TRACKING_LEDGER"
LEDGER = V182 / "dram_intraday_forward_tracking_ledger.csv"
INTRADAY_1M = ROOT / "outputs" / "v21" / "V21.175_INTRADAY_CONFIRMATION_GATE_FOR_DRAM_R1" / "dram_intraday_ohlcv_1m.csv"

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
}

FINAL_PASS = "PASS_V21_183_FORWARD_OUTCOMES_UPDATED"
FINAL_PARTIAL = "PARTIAL_PASS_V21_183_FORWARD_OUTCOMES_PARTIALLY_UPDATED"
FINAL_WAIT = "PARTIAL_PASS_V21_183_WAIT_MORE_FORWARD_DATA"
FINAL_WARN = "WARN_V21_183_NO_LEDGER_ROWS_TO_UPDATE"
FINAL_FAIL = "FAIL_V21_183_OUTCOME_UPDATE_NOT_SAFE"

OUTCOME_FIELDS = [
    "forward_30m_return",
    "forward_60m_return",
    "eod_return",
    "next_day_return",
    "mae_30m",
    "mfe_30m",
    "mae_60m",
    "mfe_60m",
    "hit_no_chase_after_snapshot",
    "hit_stop_after_snapshot",
    "entry_allowed_followthrough_flag",
    "wait_state_was_correct_flag",
    "missed_move_flag",
    "outcome_status",
]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def needs_update(row: pd.Series) -> bool:
    for field in ["forward_30m_return", "forward_60m_return", "eod_return", "next_day_return", "outcome_status"]:
        if field not in row or pd.isna(row.get(field)) or str(row.get(field, "")).strip() == "":
            return True
    return False


def ret(frame: pd.DataFrame, start_price: float) -> float:
    return float(frame.iloc[-1]["close"] / start_price - 1.0) if not frame.empty and start_price > 0 else np.nan


def mae(frame: pd.DataFrame, start_price: float) -> float:
    return float(frame["low"].min() / start_price - 1.0) if not frame.empty and start_price > 0 else np.nan


def mfe(frame: pd.DataFrame, start_price: float) -> float:
    return float(frame["high"].max() / start_price - 1.0) if not frame.empty and start_price > 0 else np.nan


def outcome_for_row(row: pd.Series, bars: pd.DataFrame, strong_move_threshold: float = 0.01) -> dict[str, Any]:
    ts = pd.to_datetime(row.get("latest_completed_bar_end", ""), errors="coerce")
    price = pd.to_numeric(pd.Series([row.get("latest_completed_price", np.nan)]), errors="coerce").iloc[0]
    no_chase = pd.to_numeric(pd.Series([row.get("no_chase", np.nan)]), errors="coerce").iloc[0]
    stop = pd.to_numeric(pd.Series([row.get("stop", np.nan)]), errors="coerce").iloc[0]
    state = str(row.get("execution_state", ""))
    out = {field: np.nan for field in OUTCOME_FIELDS}
    if pd.isna(ts) or pd.isna(price) or bars.empty:
        out["outcome_status"] = "PENDING_FORWARD_DATA"
        return out

    future = bars[bars["datetime"].gt(ts)].copy()
    if future.empty:
        out["outcome_status"] = "PENDING_FORWARD_DATA"
        return out

    next30 = future.head(30)
    next60 = future.head(60)
    out["forward_30m_return"] = ret(next30, price) if len(next30) >= 30 else np.nan
    out["mae_30m"] = mae(next30, price) if len(next30) >= 30 else np.nan
    out["mfe_30m"] = mfe(next30, price) if len(next30) >= 30 else np.nan
    out["forward_60m_return"] = ret(next60, price) if len(next60) >= 60 else np.nan
    out["mae_60m"] = mae(next60, price) if len(next60) >= 60 else np.nan
    out["mfe_60m"] = mfe(next60, price) if len(next60) >= 60 else np.nan

    same_day = future[future["datetime"].dt.date.eq(ts.date())]
    out["eod_return"] = ret(same_day.tail(1), price) if not same_day.empty else np.nan
    next_day = future[future["datetime"].dt.date > ts.date()]
    if not next_day.empty:
        first_next_day = next_day[next_day["datetime"].dt.date.eq(next_day.iloc[0]["datetime"].date())]
        out["next_day_return"] = ret(first_next_day.tail(1), price)

    out["hit_no_chase_after_snapshot"] = bool(pd.notna(no_chase) and future["high"].ge(no_chase).any())
    out["hit_stop_after_snapshot"] = bool(pd.notna(stop) and future["low"].le(stop).any())

    max_up = float(future["high"].max() / price - 1.0) if price > 0 else np.nan
    adverse = float(future["low"].min() / price - 1.0) if price > 0 else np.nan
    if state.startswith("WAIT_"):
        missed = bool(pd.notna(max_up) and max_up >= strong_move_threshold)
        out["missed_move_flag"] = missed
        out["wait_state_was_correct_flag"] = bool(not missed and not out["hit_no_chase_after_snapshot"])
    elif state == "ENTRY_ALLOWED":
        out["entry_allowed_followthrough_flag"] = bool(pd.notna(max_up) and max_up >= 0.005 and not out["hit_stop_after_snapshot"])
    else:
        out["missed_move_flag"] = False

    if len(next30) < 30:
        out["outcome_status"] = "PENDING_FORWARD_DATA"
    elif len(next60) < 60:
        out["outcome_status"] = "PARTIAL_30M_AVAILABLE_PENDING_60M"
    elif pd.isna(out["next_day_return"]):
        out["outcome_status"] = "PARTIAL_INTRADAY_AVAILABLE_PENDING_NEXT_DAY"
    else:
        out["outcome_status"] = "COMPLETE"
    if pd.notna(adverse) and adverse < -0.05:
        out["large_adverse_move_note"] = True
    return out


def update_ledger(ledger: pd.DataFrame, bars: pd.DataFrame) -> tuple[pd.DataFrame, int, int, int]:
    out = ledger.copy()
    for field in OUTCOME_FIELDS:
        if field not in out.columns:
            out[field] = np.nan
    object_fields = [
        "hit_no_chase_after_snapshot",
        "hit_stop_after_snapshot",
        "entry_allowed_followthrough_flag",
        "wait_state_was_correct_flag",
        "missed_move_flag",
        "outcome_status",
    ]
    for field in object_fields:
        if field in out.columns:
            out[field] = out[field].astype(object)
    updated = 0
    partial = 0
    pending = 0
    for idx, row in out.iterrows():
        if not needs_update(row):
            continue
        vals = outcome_for_row(row, bars)
        for key, value in vals.items():
            if key not in out.columns:
                out[key] = np.nan
            out.at[idx, key] = value
        status = str(vals.get("outcome_status", ""))
        if status == "PENDING_FORWARD_DATA":
            pending += 1
        elif status.startswith("PARTIAL"):
            partial += 1
            updated += 1
        elif status == "COMPLETE":
            updated += 1
    out["research_only"] = True
    out["official_adoption_allowed"] = False
    out["broker_action_allowed"] = False
    return out, updated, partial, pending


def decide(row_count: int, updated: int, partial: int, pending: int, protected_changed: bool) -> str:
    if protected_changed:
        return FINAL_FAIL
    if row_count == 0:
        return FINAL_WARN
    if updated > 0 and pending == 0 and partial == 0:
        return FINAL_PASS
    if updated > 0:
        return FINAL_PARTIAL
    return FINAL_WAIT


def run_stage(out_dir: Path = OUT, ledger_path: Path = LEDGER, intraday_path: Path = INTRADAY_1M) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    before = replay.protected_hashes()
    ledger = replay.read_csv(ledger_path)
    bars = replay.normalize_intraday(replay.read_csv(intraday_path))
    if ledger.empty:
        updated_ledger = ledger.copy()
        updated = partial = pending = 0
    else:
        updated_ledger, updated, partial, pending = update_ledger(ledger, bars)

    replay.write_csv(out_dir / "dram_intraday_forward_tracking_ledger_with_outcomes.csv", updated_ledger)
    pending_rows = updated_ledger[updated_ledger.get("outcome_status", pd.Series(dtype=str)).astype(str).str.contains("PENDING", na=False)] if not updated_ledger.empty else pd.DataFrame()
    replay.write_csv(out_dir / "dram_intraday_forward_pending_rows.csv", pending_rows)
    after = replay.protected_hashes()
    changed = [path for path, digest in before.items() if after.get(path) != digest]
    status = decide(len(updated_ledger), updated, partial, pending, bool(changed))
    summary = pd.DataFrame(
        [
            {
                "ledger_row_count": int(len(updated_ledger)),
                "rows_updated": int(updated),
                "partial_rows": int(partial),
                "pending_rows": int(pending),
                "complete_rows": int(updated_ledger.get("outcome_status", pd.Series(dtype=str)).astype(str).eq("COMPLETE").sum()) if not updated_ledger.empty else 0,
                "protected_outputs_modified": bool(changed),
                "broker_action_allowed": False,
                "research_only": True,
            }
        ]
    )
    replay.write_csv(out_dir / "dram_intraday_forward_outcome_update_summary.csv", summary)
    manifest = {
        "stage": STAGE,
        "final_status": status,
        "ledger_loaded": not ledger.empty,
        "intraday_1m_row_count": int(len(bars)),
        "ledger_row_count": int(len(updated_ledger)),
        "rows_updated": int(updated),
        "partial_rows": int(partial),
        "pending_rows": int(pending),
        **{**POLICY, "protected_outputs_modified": bool(changed)},
        "changed_protected_paths": changed,
        "output_directory": replay.rel(out_dir),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(out_dir / "manifest.json", manifest)
    report = [
        STAGE,
        f"FINAL_STATUS={status}",
        f"ledger_row_count={len(updated_ledger)}",
        f"rows_updated={updated}",
        f"partial_rows={partial}",
        f"pending_rows={pending}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"protected_outputs_modified={str(bool(changed)).lower()}",
    ]
    (out_dir / "V21.183_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    manifest = run_stage()
    print(json.dumps(manifest, indent=2, default=str))
    return 1 if str(manifest.get("final_status", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
