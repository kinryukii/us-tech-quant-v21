#!/usr/bin/env python
"""V21.090-R1 D Top20 monitor snapshot archive and maturity scheduler."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import protected_files, sha256


OUT_REL = Path("outputs/v21/diagnostics/v21_090_r1")
MONITOR_REL = Path("outputs/v21/diagnostics/v21_089_r1/V21_089_R1_D_TOP20_BUCKET_MONITOR.csv")
WATCHLIST_REL = Path("outputs/v21/diagnostics/v21_089_r1/V21_089_R1_D_TOP20_NO_TRADE_DIAGNOSTIC_WATCHLIST.csv")
BUCKET_REL = Path("outputs/v21/diagnostics/v21_089_r1/V21_089_R1_BUCKET_SUMMARY.csv")
V089_VALIDATION_REL = Path("outputs/v21/diagnostics/v21_089_r1/V21_089_R1_VALIDATION_SUMMARY.csv")
BRIDGE_REL = Path("outputs/v21/diagnostics/v21_087_r1/V21_087_R1_INTERACTION_MATURITY_BRIDGE.csv")
RECHECK_REL = Path("outputs/v21/diagnostics/v21_088_r1/V21_088_R1_INTERACTION_MATURITY_RECHECK.csv")
PRICE_REL = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")

ARCHIVE_NAME = "V21_090_R1_D_TOP20_MONITOR_SNAPSHOT_ARCHIVE.csv"
MANIFEST_NAME = "V21_090_R1_D_TOP20_MONITOR_HASH_MANIFEST.csv"
SCHEDULE_NAME = "V21_090_R1_D_TOP20_BUCKET_MATURITY_SCHEDULE.csv"
TRIGGER_NAME = "V21_090_R1_BUCKET_REVIEW_TRIGGER_PLAN.csv"
SPECIAL_NAME = "V21_090_R1_SPECIAL_CASE_TRACKER.csv"
GAP_NAME = "V21_090_R1_SOURCE_COVERAGE_GAP_REVIEW.csv"
CERT_NAME = "V21_090_R1_NO_TRADE_ARCHIVE_CERTIFICATION.csv"
MUTATION_NAME = "V21_090_R1_PROTECTED_OUTPUT_MUTATION_AUDIT.csv"
VALIDATION_NAME = "V21_090_R1_VALIDATION_SUMMARY.csv"
OUTPUT_NAMES = (
    ARCHIVE_NAME, MANIFEST_NAME, SCHEDULE_NAME, TRIGGER_NAME, SPECIAL_NAME,
    GAP_NAME, CERT_NAME, MUTATION_NAME, VALIDATION_NAME,
)
WINDOWS = (5, 10, 20)


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def local_now() -> datetime:
    return datetime.now().astimezone()


def file_metadata(path: Path, root: Path, snapshot_id: str, role: str) -> dict[str, Any]:
    exists = path.is_file()
    stat = path.stat() if exists else None
    return {
        "archive_snapshot_id": snapshot_id,
        "file_path": path.resolve().relative_to(root.resolve()).as_posix() if path.resolve().is_relative_to(root.resolve()) else path.as_posix(),
        "file_role": role,
        "exists": exists,
        "file_size_bytes": stat.st_size if stat else 0,
        "sha256": sha256(path) if exists else "",
        "modified_time_local": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat() if stat else "",
        "mutation_allowed": False,
        "warning": "" if exists else "FILE_NOT_FOUND",
    }


def price_data(root: Path) -> tuple[dict[tuple[str, str], float], str]:
    price = pd.read_csv(root / PRICE_REL, usecols=["symbol", "date", "close", "adjusted_close"], low_memory=False)
    price["ticker"] = price["symbol"].astype(str).str.upper().str.strip()
    price["date"] = price["date"].astype(str).str[:10]
    price["price"] = pd.to_numeric(price["adjusted_close"], errors="coerce").fillna(
        pd.to_numeric(price["close"], errors="coerce")
    )
    price = price[price["price"].notna()]
    return price.set_index(["ticker", "date"])["price"].to_dict(), str(price["date"].max())


def snapshot_id(monitor_path: Path, latest: str) -> str:
    return f"V21_090_R1::{latest}::{sha256(monitor_path)[:16]}"


def build_archive(monitor: pd.DataFrame, sid: str, created: str) -> pd.DataFrame:
    out = monitor[[
        "source_latest_price_date", "D_rank", "ticker", "D_final_score", "latest_close",
        "interaction_primary_label", "risk_bucket_from_v21_088", "bucket_monitor_status",
        "bucket_monitor_priority", "diagnostic_action",
    ]].copy()
    out.insert(0, "archive_snapshot_id", sid)
    out.insert(1, "archive_created_at_local", created)
    out.insert(2, "source_stage", "V21.089-R1")
    out["no_trade_action_created"] = True
    out["adoption_allowed"] = False
    out["not_a_trade_signal"] = True
    out["pullback_adoption_allowed"] = False
    out["interaction_adoption_allowed"] = False
    out["data_warning_flag"] = (
        ~monitor["technical_available"].map(truth)
        | ~monitor["fundamental_available"].map(truth)
        | ~monitor["interaction_available"].map(truth)
    )
    out["archive_note"] = "Immutable-style diagnostic snapshot; no ranking mutation or trade action."
    return out


def build_schedule(
    monitor: pd.DataFrame, sid: str, prices: dict[tuple[str, str], float], latest_price: str
) -> pd.DataFrame:
    rows = []
    for _, row in monitor.sort_values("D_rank").iterrows():
        ticker = str(row["ticker"]).upper()
        asof = str(row["as_of_date"])[:10]
        entry = prices.get((ticker, asof))
        for window in WINDOWS:
            maturity = (pd.Timestamp(asof) + pd.tseries.offsets.BDay(window)).date().isoformat()
            end = prices.get((ticker, maturity))
            matured = entry is not None and end is not None and float(entry) != 0
            rows.append({
                "archive_snapshot_id": sid,
                "observation_id": f"V21_090::{sid.split('::')[-1]}::{asof}::{ticker}::{window}D",
                "ticker": ticker, "D_rank": row["D_rank"], "as_of_date": asof,
                "source_latest_price_date": row["source_latest_price_date"],
                "bucket_monitor_status": row["bucket_monitor_status"],
                "diagnostic_action": row["diagnostic_action"],
                "forward_window": f"{window}D", "maturity_date": maturity,
                "latest_available_price_date": latest_price,
                "forward_matured_flag": bool(matured),
                "return_forward_if_available": float(end) / float(entry) - 1 if matured else np.nan,
                "maturity_status": "MATURED" if matured else "PENDING",
                "scheduled_review_stage": "V21.091-R1_D_TOP20_MATURITY_REFRESH_AND_BUCKET_OUTCOME_EVALUATOR",
                "adoption_allowed": False, "no_trade_action_created": True,
            })
    return pd.DataFrame(rows)


def build_special(monitor: pd.DataFrame, sid: str) -> pd.DataFrame:
    definitions = {
        "TWST": ("LOW_QUALITY_MOMENTUM_RISK", "Review quality and momentum persistence.", "QUALITY_STRONG|PROFITABILITY_IMPROVING|BALANCE_SHEET_STRONG|5D_10D_20D_PRICE"),
        "WYFI": ("LOW_QUALITY_MOMENTUM_RISK", "Review quality and momentum persistence.", "QUALITY_STRONG|PROFITABILITY_IMPROVING|BALANCE_SHEET_STRONG|5D_10D_20D_PRICE"),
        "ICHR": ("INTERACTION_SOURCE_COVERAGE_GAP", "Audit interaction rule coverage without changing current rules.", "TECHNICAL_LABELS|FUNDAMENTAL_LABELS|INTERACTION_RULE_MATCH"),
        "VECO": ("INTERACTION_SOURCE_COVERAGE_GAP", "Audit interaction rule coverage without changing current rules.", "TECHNICAL_LABELS|FUNDAMENTAL_LABELS|INTERACTION_RULE_MATCH"),
        "FORM": ("FUNDAMENTAL_WAIT_FOR_TECH_CONFIRMATION", "Wait for technical confirmation.", "MA20|MA50|MACD_HIST|RSI_SLOPE|VOLUME"),
        "ACLS": ("FUNDAMENTAL_WAIT_FOR_TECH_CONFIRMATION", "Wait for technical confirmation.", "MA20|MA50|MACD_HIST|RSI_SLOPE|VOLUME"),
        "SITM": ("WEAK_TECH_STRONG_FUNDAMENTAL_WAIT_CONFIRMATION", "Wait for technical recovery.", "MA20|MA50|MACD_HIST|RSI_SLOPE|BREAKOUT_CONFIRMATION"),
        "CRDO": ("DAY0_BREAKOUT_NO_CHASE", "Review Day1 confirmation; no chase.", "DAY1_CONTINUATION|BREAKOUT_VOLUME|BREAKOUT_FAILURE"),
    }
    rows = []
    by_ticker = monitor.set_index("ticker")
    for ticker, (case_type, check, fields) in definitions.items():
        if ticker not in by_ticker.index:
            continue
        row = by_ticker.loc[ticker]
        rows.append({
            "archive_snapshot_id": sid, "ticker": ticker, "D_rank": row["D_rank"],
            "special_case_type": case_type, "current_bucket": row["risk_bucket_from_v21_088"],
            "issue_summary": row["monitor_interpretation"], "required_future_check": check,
            "required_data_fields": fields, "current_status": "OPEN_DIAGNOSTIC_REVIEW",
            "adoption_allowed": False, "no_trade_action_created": True,
        })
    return pd.DataFrame(rows)


def build_gap_review(monitor: pd.DataFrame) -> pd.DataFrame:
    sub = monitor[monitor["risk_bucket_from_v21_088"].eq("INTERACTION_UNAVAILABLE_NEEDS_DATA_REVIEW")].copy()
    return pd.DataFrame({
        "ticker": sub["ticker"], "D_rank": sub["D_rank"],
        "technical_available": sub["technical_available"].map(truth),
        "fundamental_available": sub["fundamental_available"].map(truth),
        "interaction_rule_matched": sub["interaction_available"].map(truth),
        "missing_rule_reason": "NO_INTERACTION_RULE_MATCH_DESPITE_CURRENT_SOURCE_ROWS",
        "likely_gap_type": "SOURCE_COVERAGE_GAP",
        "proposed_rule_review": "FUTURE_DIAGNOSTIC_AUDIT_OF_UNMATCHED_VALID_LABEL_COMBINATIONS",
        "proposed_data_review": "VERIFY_TECHNICAL_AND_FUNDAMENTAL_LABEL_COVERAGE_AT_SAME_AS_OF_DATE",
        "adoption_allowed": False, "no_trade_action_created": True,
    })


def build_triggers(schedule: pd.DataFrame, bridge: pd.DataFrame, source_date: str) -> pd.DataFrame:
    def earliest(frame: pd.DataFrame, window: str | None = None, ticker: str | None = None) -> str:
        sub = frame
        if window is not None:
            sub = sub[sub["forward_window"].eq(window)]
        if ticker is not None:
            sub = sub[sub["ticker"].eq(ticker)]
        return str(sub["maturity_date"].min()) if not sub.empty else ""

    next_stage = "V21.091-R1_D_TOP20_MATURITY_REFRESH_AND_BUCKET_OUTCOME_EVALUATOR"
    specs = [
        ("D_TOP20_5D_BUCKET_MATURITY_REVIEW", "PRICE_MATURITY", "D_TOP20", "Exact 5D maturity price rows become available.", earliest(schedule, "5D"), SCHEDULE_NAME),
        ("D_TOP20_10D_BUCKET_MATURITY_REVIEW", "PRICE_MATURITY", "D_TOP20", "Exact 10D maturity price rows become available.", earliest(schedule, "10D"), SCHEDULE_NAME),
        ("D_TOP20_20D_BUCKET_MATURITY_REVIEW", "PRICE_MATURITY", "D_TOP20", "Exact 20D maturity price rows become available.", earliest(schedule, "20D"), SCHEDULE_NAME),
        ("INTERACTION_087_5D_MATURITY_REVIEW", "PRICE_MATURITY", "V21.087", "V21.087 5D bridge observations obtain exact maturity prices.", earliest(bridge, "5D"), BRIDGE_REL.as_posix()),
        ("INTERACTION_087_10D_MATURITY_REVIEW", "PRICE_MATURITY", "V21.087", "V21.087 10D bridge observations obtain exact maturity prices.", earliest(bridge, "10D"), BRIDGE_REL.as_posix()),
        ("INTERACTION_087_20D_MATURITY_REVIEW", "PRICE_MATURITY", "V21.087", "V21.087 20D bridge observations obtain exact maturity prices.", earliest(bridge, "20D"), BRIDGE_REL.as_posix()),
        ("LOW_QUALITY_MOMENTUM_TWST_WYFI_REVIEW", "SPECIAL_CASE_MATURITY", "TWST|WYFI", "First 5D maturity prices and refreshed quality fields are available.", min(earliest(schedule, "5D", "TWST"), earliest(schedule, "5D", "WYFI")), SCHEDULE_NAME),
        ("INTERACTION_DATA_GAP_ICHR_VECO_REVIEW", "SOURCE_COVERAGE", "ICHR|VECO", "Interaction rule coverage or source labels are refreshed.", source_date, GAP_NAME),
        ("DAY0_BREAKOUT_CRDO_DAY1_CONFIRMATION_REVIEW", "DAY1_CONFIRMATION", "CRDO", "Next business-day CRDO technical row is available.", (pd.Timestamp(source_date) + pd.tseries.offsets.BDay(1)).date().isoformat(), MONITOR_REL.as_posix()),
        ("PULLBACK_NON_ADOPTION_CONFIRMATION_RECHECK", "NON_ADOPTION_AUDIT", "PULLBACK", "Only recheck non-adoption after matured diagnostic evidence exists.", earliest(schedule, "20D"), RECHECK_REL.as_posix()),
        ("D_BASELINE_PRESERVATION_AUDIT", "MUTATION_AUDIT", "D_WEIGHT_OPTIMIZED_R1", "Run on every archive and maturity refresh.", source_date, MUTATION_NAME),
    ]
    rows = []
    latest = str(schedule["latest_available_price_date"].max())
    for name, kind, target, condition, date, required in specs:
        status = "READY" if date and date <= latest and kind not in {"SOURCE_COVERAGE", "MUTATION_AUDIT"} else "PENDING"
        if kind == "MUTATION_AUDIT":
            status = "READY"
        rows.append({
            "trigger_name": name, "trigger_type": kind, "target_bucket_or_stage": target,
            "condition": condition, "earliest_review_date": date, "required_input": required,
            "expected_next_stage": next_stage, "trigger_status": status,
            "warning": "EXACT_PRICE_OR_SOURCE_REFRESH_REQUIRED" if status == "PENDING" else "",
        })
    return pd.DataFrame(rows)


def protected_snapshot(root: Path, output: Path) -> tuple[list[Path], dict[Path, str]]:
    paths = protected_files(root, output)
    for stage in range(85, 90):
        base = root / f"outputs/v21/diagnostics/v21_0{stage}_r1"
        if base.exists():
            paths.extend(p.resolve() for p in base.rglob("*") if p.is_file())
    paths = sorted(set(paths))
    return paths, {p: sha256(p) for p in paths}


def mutation_audit(paths: list[Path], before: dict[Path, str]) -> pd.DataFrame:
    rows = []
    for path in paths:
        text = path.as_posix().lower()
        ptype = (
            "broker_action" if "broker" in text else
            "official_weight" if "weight" in text and ("official" in text or "weight_perturbation" in text) else
            "official_ranking" if "ranking" in text or "060_r5_d_" in text or "066a_d_latest_ranking" in text else
            "prior_v21_diagnostic" if "/diagnostics/v21_0" in text else "protected"
        )
        exists = path.exists()
        changed = not exists or before[path] != sha256(path)
        rows.append({
            "path": path.as_posix(), "path_type": ptype, "exists_before": True,
            "exists_after": exists, "modified_during_run": changed,
            "mutation_allowed": False, "warning": "DISALLOWED_MUTATION_DETECTED" if changed else "",
        })
    return pd.DataFrame(rows)


def empty_outputs(output: Path) -> None:
    columns = {
        ARCHIVE_NAME: ["archive_snapshot_id", "ticker", "adoption_allowed", "no_trade_action_created"],
        MANIFEST_NAME: ["archive_snapshot_id", "file_path", "file_role", "exists", "file_size_bytes", "sha256", "modified_time_local", "mutation_allowed", "warning"],
        SCHEDULE_NAME: ["archive_snapshot_id", "observation_id", "ticker", "forward_window", "adoption_allowed", "no_trade_action_created"],
        TRIGGER_NAME: ["trigger_name", "trigger_type", "target_bucket_or_stage", "condition", "earliest_review_date", "required_input", "expected_next_stage", "trigger_status", "warning"],
        SPECIAL_NAME: ["archive_snapshot_id", "ticker", "special_case_type", "adoption_allowed", "no_trade_action_created"],
        GAP_NAME: ["ticker", "likely_gap_type", "adoption_allowed", "no_trade_action_created"],
        CERT_NAME: ["archive_snapshot_id", "certification_status", "no_trade_action_created"],
        MUTATION_NAME: ["path", "path_type", "exists_before", "exists_after", "modified_during_run", "mutation_allowed", "warning"],
    }
    for name, cols in columns.items():
        pd.DataFrame(columns=cols).to_csv(output / name, index=False)


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (output_override if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    required = [MONITOR_REL, WATCHLIST_REL, BUCKET_REL, V089_VALIDATION_REL, BRIDGE_REL, RECHECK_REL, PRICE_REL]
    missing = [p.as_posix() for p in required if not (root / p).is_file()]
    protected, before = protected_snapshot(root, output)
    archive = schedule = triggers = special = gaps = pd.DataFrame()
    sid = latest = ""
    created = local_now().isoformat()

    if missing:
        empty_outputs(output)
    else:
        monitor = pd.read_csv(root / MONITOR_REL, low_memory=False)
        bridge = pd.read_csv(root / BRIDGE_REL, low_memory=False)
        prices, latest_price = price_data(root)
        latest = str(monitor["source_latest_price_date"].dropna().astype(str).str[:10].max())
        sid = snapshot_id(root / MONITOR_REL, latest)
        archive = build_archive(monitor, sid, created)
        schedule = build_schedule(monitor, sid, prices, latest_price)
        special = build_special(monitor, sid)
        gaps = build_gap_review(monitor)
        triggers = build_triggers(schedule, bridge, latest)
        for frame, name in (
            (archive, ARCHIVE_NAME), (schedule, SCHEDULE_NAME), (triggers, TRIGGER_NAME),
            (special, SPECIAL_NAME), (gaps, GAP_NAME),
        ):
            frame.to_csv(output / name, index=False)

    audit = mutation_audit(protected, before)
    audit.to_csv(output / MUTATION_NAME, index=False)
    mutation_count = int(audit["modified_during_run"].map(truth).sum()) if not audit.empty else 0
    cert = pd.DataFrame([{
        "archive_snapshot_id": sid, "research_only": True, "diagnostic_only": True,
        "archive_only": True, "scheduler_only": True, "official_ranking_mutated": False,
        "official_weights_mutated": False, "broker_action_created": False,
        "recommendation_created": False, "protected_outputs_modified": mutation_count > 0,
        "d_baseline_preserved": mutation_count == 0, "pullback_adoption_allowed": False,
        "interaction_adoption_allowed": False, "bucket_monitor_adoption_allowed": False,
        "no_trade_action_created": True,
        "certification_status": "CERTIFIED_NO_TRADE_DIAGNOSTIC_ARCHIVE_ONLY",
        "certification_note": "Archive and scheduler only; no ranking, recommendation, broker, or adoption action.",
    }])
    cert.to_csv(output / CERT_NAME, index=False)

    leakage_count = 0
    data_warning_count = len(gaps) if not gaps.empty else 0
    any_adoption = any(
        frame.get("adoption_allowed", pd.Series(dtype=bool)).map(truth).any()
        for frame in (archive, schedule, special, gaps)
    )
    no_trade_bad = any(
        (~frame.get("no_trade_action_created", pd.Series(dtype=bool)).map(truth)).any()
        for frame in (archive, schedule, special, gaps) if not frame.empty
    )
    blocked = mutation_count > 0 or leakage_count > 0 or any_adoption or no_trade_bad
    if missing:
        status = "BLOCKED_V21_090_R1_REQUIRED_INPUTS_MISSING"
        decision = "REQUIRED_INPUTS_MISSING_REVIEW_REQUIRED"
    elif blocked:
        status = "BLOCKED_V21_090_R1_LEAKAGE_OR_PROTECTED_MUTATION_RISK"
        decision = "D_TOP20_MONITOR_ARCHIVE_OR_SCHEDULER_BLOCKED_REVIEW_REQUIRED"
    elif data_warning_count:
        status = "PARTIAL_PASS_V21_090_R1_ARCHIVE_AND_SCHEDULER_READY_WITH_DATA_WARN"
        decision = "D_TOP20_MONITOR_ARCHIVE_AND_SCHEDULER_READY_WITH_DATA_WARN_DIAGNOSTIC_ONLY"
    else:
        status = "PASS_V21_090_R1_D_TOP20_MONITOR_ARCHIVE_AND_SCHEDULER_READY"
        decision = "D_TOP20_MONITOR_ARCHIVE_AND_SCHEDULER_READY_DIAGNOSTIC_ONLY"

    def window_count(window: str, matured: bool) -> int:
        if schedule.empty: return 0
        return int((schedule["forward_window"].eq(window) & schedule["forward_matured_flag"].map(truth).eq(matured)).sum())

    manifest_sources = [
        (root / MONITOR_REL, "V21_089_MONITOR_SOURCE"),
        (root / WATCHLIST_REL, "V21_089_WATCHLIST_SOURCE"),
        (root / BUCKET_REL, "V21_089_BUCKET_SUMMARY_SOURCE"),
        (root / V089_VALIDATION_REL, "V21_089_VALIDATION_SOURCE"),
        (root / BRIDGE_REL, "V21_087_INTERACTION_MATURITY_SOURCE"),
        (root / RECHECK_REL, "V21_088_MATURITY_RECHECK_SOURCE"),
        (root / PRICE_REL, "LOCAL_PRICE_SOURCE"),
    ]
    manifest_generated = [(output / name, "V21_090_GENERATED_OUTPUT") for name in OUTPUT_NAMES if name != MANIFEST_NAME]
    manifest_protected = [(p, "PROTECTED_AUDIT_REFERENCE") for p in protected]
    manifest_row_count = len({p.resolve() for p, _ in manifest_sources + manifest_generated + manifest_protected})
    validation = {
        "stage": "V21.090-R1_D_TOP20_MONITOR_SNAPSHOT_ARCHIVE_AND_MATURITY_SCHEDULER",
        "final_status": status, "decision": decision, "research_only": True,
        "diagnostic_only": True, "archive_only": True, "scheduler_only": True,
        "official_ranking_mutated": False, "official_weights_mutated": False,
        "broker_action_created": False, "recommendation_created": False,
        "protected_outputs_modified": mutation_count > 0, "d_baseline_preserved": mutation_count == 0,
        "technical_085_preserved": mutation_count == 0, "fundamental_086_preserved": mutation_count == 0,
        "interaction_087_preserved": mutation_count == 0, "review_088_preserved": mutation_count == 0,
        "monitor_089_preserved": mutation_count == 0, "source_latest_price_date": latest,
        "archive_snapshot_id": sid, "top20_archive_rows": len(archive),
        "hash_manifest_rows": manifest_row_count, "bucket_maturity_schedule_rows": len(schedule),
        "special_case_tracker_rows": len(special), "trigger_plan_rows": len(triggers),
        "source_coverage_gap_review_rows": len(gaps),
        "matured_5d_count": window_count("5D", True), "matured_10d_count": window_count("10D", True),
        "matured_20d_count": window_count("20D", True), "pending_5d_count": window_count("5D", False),
        "pending_10d_count": window_count("10D", False), "pending_20d_count": window_count("20D", False),
        "low_quality_momentum_cases": int(special["special_case_type"].eq("LOW_QUALITY_MOMENTUM_RISK").sum()) if not special.empty else 0,
        "source_coverage_gap_cases": len(gaps),
        "wait_confirmation_cases": int(special["special_case_type"].isin(["FUNDAMENTAL_WAIT_FOR_TECH_CONFIRMATION", "WEAK_TECH_STRONG_FUNDAMENTAL_WAIT_CONFIRMATION"]).sum()) if not special.empty else 0,
        "day0_no_chase_cases": int(special["special_case_type"].eq("DAY0_BREAKOUT_NO_CHASE").sum()) if not special.empty else 0,
        "pullback_adoption_allowed": False, "interaction_adoption_allowed": False,
        "bucket_monitor_adoption_allowed": False, "leakage_warning_count": leakage_count,
        "data_warning_count": data_warning_count, "mutation_warning_count": mutation_count,
        "recommended_next_stage": "V21.091-R1_D_TOP20_MATURITY_REFRESH_AND_BUCKET_OUTCOME_EVALUATOR",
        "generated_at_local": created, "missing_inputs": "|".join(missing),
    }
    pd.DataFrame([validation]).to_csv(output / VALIDATION_NAME, index=False)

    roles: dict[Path, str] = {}
    for path, role in manifest_sources + manifest_generated + manifest_protected:
        roles[path.resolve()] = role
    manifest = pd.DataFrame([
        file_metadata(path, root, sid, role) for path, role in sorted(roles.items(), key=lambda x: x[0].as_posix())
    ])
    manifest.to_csv(output / MANIFEST_NAME, index=False)
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in ("final_status", "decision", "source_latest_price_date", "archive_snapshot_id", "bucket_maturity_schedule_rows"):
        print(f"{key.upper()}={result[key]}")
    return 0 if not str(result["final_status"]).startswith("BLOCKED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
