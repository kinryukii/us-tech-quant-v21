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


STAGE = "V21.182_DRAM_INTRADAY_FORWARD_TRACKING_LEDGER"
OUT = ROOT / "outputs" / "v21" / STAGE
SNAPSHOT_DIR = ROOT / "outputs" / "v21" / "V21.180_DRAM_INTRADAY_CONFIRMATION_SNAPSHOT_RUNNER"
SNAPSHOT_JSON = SNAPSHOT_DIR / "dram_intraday_snapshot_state.json"
SNAPSHOT_SIGNAL_TABLE = SNAPSHOT_DIR / "dram_intraday_snapshot_signal_table.csv"
LEDGER = OUT / "dram_intraday_forward_tracking_ledger.csv"

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
}

FINAL_PASS = "PASS_V21_182_FORWARD_LEDGER_APPENDED"
FINAL_PARTIAL = "PARTIAL_PASS_V21_182_WAIT_MORE_FORWARD_OBSERVATIONS"
FINAL_WARN = "WARN_V21_182_NO_NEW_SNAPSHOT"
FINAL_FAIL = "FAIL_V21_182_FORWARD_LEDGER_NOT_SAFE"

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
]

LEDGER_COLUMNS = [
    "snapshot_run_id",
    "snapshot_created_at_utc",
    "append_timestamp_utc",
    "ticker",
    "latest_completed_bar_end",
    "latest_completed_price",
    "execution_state",
    "active_gate",
    "actionable_signal",
    "downstream_signals_computed_but_not_actionable",
    "blocking_reason",
    "h1_signal",
    "m15_signal",
    "m1_signal",
    "h1_actionable",
    "m15_actionable",
    "m1_actionable",
    "entry",
    "no_chase",
    "stop",
    "latest_price_date_used",
    "plan_date",
    "trade_plan_currentness",
    *OUTCOME_FIELDS,
    "research_only",
    "official_adoption_allowed",
    "broker_action_allowed",
]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def snapshot_id(snapshot: dict[str, Any]) -> str:
    raw = "|".join(
        [
            str(snapshot.get("ticker", "DRAM")),
            str(snapshot.get("latest_completed_bar_end", "")),
            str(snapshot.get("execution_state", "")),
        ]
    )
    import hashlib

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def actionability(snapshot: dict[str, Any]) -> dict[str, Any]:
    state = str(snapshot.get("execution_state", ""))
    active_gate = {
        "WAIT_H1_CONFIRMATION": "H1",
        "WAIT_15M_SETUP": "M15",
        "WAIT_1M_TRIGGER": "M1",
        "ENTRY_ALLOWED": "ENTRY",
        "NO_CHASE_BLOCK": "NO_CHASE",
        "STOP_RISK_ACTIVE": "STOP",
        "DATA_STALE_BLOCK": "DATA",
        "PLAN_BLOCKED_INVALID_BOUNDS": "PLAN",
        "INTRADAY_DATA_UNAVAILABLE": "DATA",
        "PLAN_READY_WAIT_MARKET": "DAILY_ENTRY_ZONE",
    }.get(state, "UNKNOWN")
    h1_actionable = state in {"WAIT_H1_CONFIRMATION"}
    m15_actionable = state in {"WAIT_15M_SETUP"}
    m1_actionable = state in {"WAIT_1M_TRIGGER"}
    actionable_signal = state == "ENTRY_ALLOWED"
    downstream_info = state == "WAIT_H1_CONFIRMATION"
    blocking_reason = {
        "WAIT_H1_CONFIRMATION": "H1_NOT_CONFIRMED_DOWNSTREAM_SIGNALS_INFORMATIONAL_ONLY",
        "WAIT_15M_SETUP": "M15_SETUP_NOT_CONFIRMED",
        "WAIT_1M_TRIGGER": "M1_TRIGGER_NOT_CONFIRMED",
        "NO_CHASE_BLOCK": "PRICE_AT_OR_ABOVE_NO_CHASE",
        "STOP_RISK_ACTIVE": "PRICE_AT_OR_NEAR_STOP",
        "DATA_STALE_BLOCK": "PLAN_OR_DATA_STALE",
        "PLAN_BLOCKED_INVALID_BOUNDS": "STOP_ENTRY_NO_CHASE_BOUNDS_INVALID",
        "INTRADAY_DATA_UNAVAILABLE": "NO_COMPLETED_INTRADAY_BARS",
        "PLAN_READY_WAIT_MARKET": "PRICE_NOT_IN_DAILY_ENTRY_ZONE",
        "ENTRY_ALLOWED": "",
    }.get(state, "UNKNOWN_EXECUTION_STATE")
    return {
        "active_gate": active_gate,
        "actionable_signal": actionable_signal,
        "downstream_signals_computed_but_not_actionable": downstream_info,
        "blocking_reason": blocking_reason,
        "h1_actionable": h1_actionable,
        "m15_actionable": m15_actionable,
        "m1_actionable": m1_actionable,
    }


def row_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    act = actionability(snapshot)
    row = {
        "snapshot_run_id": snapshot_id(snapshot),
        "snapshot_created_at_utc": snapshot.get("created_at_utc", ""),
        "append_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "ticker": "DRAM",
        "latest_completed_bar_end": snapshot.get("latest_completed_bar_end", ""),
        "latest_completed_price": snapshot.get("latest_completed_price", np.nan),
        "execution_state": snapshot.get("execution_state", ""),
        **act,
        "h1_signal": snapshot.get("h1_signal", ""),
        "m15_signal": snapshot.get("m15_signal", ""),
        "m1_signal": snapshot.get("m1_signal", ""),
        "entry": snapshot.get("DRAM_ENTRY", np.nan),
        "no_chase": snapshot.get("DRAM_NO_CHASE", np.nan),
        "stop": snapshot.get("DRAM_STOP", np.nan),
        "latest_price_date_used": snapshot.get("latest_price_date_used", ""),
        "plan_date": snapshot.get("plan_date", ""),
        "trade_plan_currentness": snapshot.get("trade_plan_currentness", ""),
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
    }
    for field in OUTCOME_FIELDS:
        row[field] = np.nan
    return row


def append_and_dedup(existing: pd.DataFrame, row: dict[str, Any]) -> tuple[pd.DataFrame, int, int]:
    new = pd.DataFrame([row])
    combined = pd.concat([existing, new], ignore_index=True, sort=False) if not existing.empty else new
    before = len(combined)
    combined = combined.drop_duplicates(["ticker", "latest_completed_bar_end", "execution_state"], keep="last")
    deduped = before - len(combined)
    appended = 0 if deduped else 1
    return combined.reindex(columns=LEDGER_COLUMNS), appended, deduped


def summary_frame(ledger: pd.DataFrame, appended: int, deduped: int) -> pd.DataFrame:
    rows = []
    if ledger.empty:
        return pd.DataFrame(
            [
                {
                    "ledger_row_count": 0,
                    "new_rows_appended": appended,
                    "deduplicated_row_count": deduped,
                    "entry_allowed_count": 0,
                    "wait_state_count": 0,
                    "blocked_state_count": 0,
                    "broker_action_allowed": False,
                    "research_only": True,
                }
            ]
        )
    rows.append(
        {
            "ledger_row_count": int(len(ledger)),
            "new_rows_appended": appended,
            "deduplicated_row_count": deduped,
            "entry_allowed_count": int(ledger["execution_state"].astype(str).eq("ENTRY_ALLOWED").sum()),
            "wait_state_count": int(ledger["execution_state"].astype(str).str.startswith("WAIT_").sum()),
            "blocked_state_count": int(ledger["execution_state"].astype(str).isin(["NO_CHASE_BLOCK", "STOP_RISK_ACTIVE", "DATA_STALE_BLOCK", "PLAN_BLOCKED_INVALID_BOUNDS", "INTRADAY_DATA_UNAVAILABLE"]).sum()),
            "broker_action_allowed": False,
            "research_only": True,
        }
    )
    return pd.DataFrame(rows)


def run_stage(
    out_dir: Path = OUT,
    snapshot_path: Path = SNAPSHOT_JSON,
    signal_table_path: Path = SNAPSHOT_SIGNAL_TABLE,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_path or (out_dir / "dram_intraday_forward_tracking_ledger.csv")
    before = replay.protected_hashes()
    snapshot = read_json(snapshot_path)
    existing = replay.read_csv(ledger_path)
    if not snapshot:
        ledger = existing.reindex(columns=LEDGER_COLUMNS) if not existing.empty else pd.DataFrame(columns=LEDGER_COLUMNS)
        replay.write_csv(out_dir / "dram_intraday_forward_tracking_ledger.csv", ledger, LEDGER_COLUMNS)
        latest = {"error": "V21.180 snapshot missing", **POLICY}
        write_json(out_dir / "dram_intraday_forward_tracking_latest_snapshot.json", latest)
        summary = summary_frame(ledger, 0, 0)
        replay.write_csv(out_dir / "dram_intraday_forward_tracking_summary.csv", summary)
        status = FINAL_WARN
        decision = "WAIT_FOR_NEXT_V21_180_SNAPSHOT"
        changed: list[str] = []
    else:
        row = row_from_snapshot(snapshot)
        ledger, appended, deduped = append_and_dedup(existing, row)
        replay.write_csv(out_dir / "dram_intraday_forward_tracking_ledger.csv", ledger, LEDGER_COLUMNS)
        signal_table = replay.read_csv(signal_table_path)
        latest = {**row, "source_snapshot_path": replay.rel(snapshot_path), "signal_table_rows": signal_table.to_dict("records") if not signal_table.empty else []}
        write_json(out_dir / "dram_intraday_forward_tracking_latest_snapshot.json", latest)
        summary = summary_frame(ledger, appended, deduped)
        replay.write_csv(out_dir / "dram_intraday_forward_tracking_summary.csv", summary)
        after = replay.protected_hashes()
        changed = [path for path, digest in before.items() if after.get(path) != digest]
        if changed:
            status = FINAL_FAIL
            decision = "FORWARD_LEDGER_NOT_SAFE_PROTECTED_OUTPUT_MUTATION"
        elif appended:
            status = FINAL_PASS
            decision = "FORWARD_LEDGER_APPENDED_RESEARCH_ONLY"
        elif deduped:
            status = FINAL_WARN
            decision = "NO_NEW_SNAPSHOT_DEDUPED"
        else:
            status = FINAL_PARTIAL
            decision = "WAIT_MORE_FORWARD_OBSERVATIONS"

    protected_modified = bool(changed) if snapshot else False
    manifest = {
        "stage": STAGE,
        "final_status": status,
        "decision": decision,
        "snapshot_loaded": bool(snapshot),
        "ledger_row_count": int(len(replay.read_csv(out_dir / "dram_intraday_forward_tracking_ledger.csv"))),
        "new_rows_appended": int(summary.iloc[0].get("new_rows_appended", 0)) if not summary.empty else 0,
        "deduplicated_row_count": int(summary.iloc[0].get("deduplicated_row_count", 0)) if not summary.empty else 0,
        **{**POLICY, "protected_outputs_modified": protected_modified},
        "changed_protected_paths": changed if snapshot else [],
        "output_directory": replay.rel(out_dir),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(out_dir / "manifest.json", manifest)
    report = [
        STAGE,
        f"FINAL_STATUS={status}",
        f"DECISION={decision}",
        f"snapshot_loaded={str(bool(snapshot)).lower()}",
        f"ledger_row_count={manifest['ledger_row_count']}",
        f"new_rows_appended={manifest['new_rows_appended']}",
        f"deduplicated_row_count={manifest['deduplicated_row_count']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"protected_outputs_modified={str(protected_modified).lower()}",
    ]
    (out_dir / "V21.182_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    manifest = run_stage()
    print(json.dumps(manifest, indent=2, default=str))
    return 0 if not str(manifest.get("final_status", "")).startswith("FAIL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
