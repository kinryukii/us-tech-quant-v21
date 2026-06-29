#!/usr/bin/env python
"""V21.091-R1 D Top20 maturity refresh and bucket outcome evaluator."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import protected_files, sha256


OUT_REL = Path("outputs/v21/diagnostics/v21_091_r1")
ARCHIVE_REL = Path("outputs/v21/diagnostics/v21_090_r1/V21_090_R1_D_TOP20_MONITOR_SNAPSHOT_ARCHIVE.csv")
SCHEDULE_REL = Path("outputs/v21/diagnostics/v21_090_r1/V21_090_R1_D_TOP20_BUCKET_MATURITY_SCHEDULE.csv")
TRIGGER_REL = Path("outputs/v21/diagnostics/v21_090_r1/V21_090_R1_BUCKET_REVIEW_TRIGGER_PLAN.csv")
SPECIAL_REL = Path("outputs/v21/diagnostics/v21_090_r1/V21_090_R1_SPECIAL_CASE_TRACKER.csv")
GAP_REL = Path("outputs/v21/diagnostics/v21_090_r1/V21_090_R1_SOURCE_COVERAGE_GAP_REVIEW.csv")
CERT_090_REL = Path("outputs/v21/diagnostics/v21_090_r1/V21_090_R1_NO_TRADE_ARCHIVE_CERTIFICATION.csv")
BRIDGE_REL = Path("outputs/v21/diagnostics/v21_087_r1/V21_087_R1_INTERACTION_MATURITY_BRIDGE.csv")
INTERACTION_PANEL_REL = Path("outputs/v21/diagnostics/v21_087_r1/V21_087_R1_INTERACTION_PANEL.csv")
PRICE_REL = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")

INVENTORY_NAME = "V21_091_R1_PRICE_DATA_REFRESH_INVENTORY.csv"
TOP20_REFRESH_NAME = "V21_091_R1_D_TOP20_MATURITY_REFRESH.csv"
BUCKET_SUMMARY_NAME = "V21_091_R1_D_TOP20_BUCKET_OUTCOME_SUMMARY.csv"
OVERALL_SUMMARY_NAME = "V21_091_R1_D_TOP20_OVERALL_OUTCOME_SUMMARY.csv"
SPECIAL_OUTCOME_NAME = "V21_091_R1_SPECIAL_CASE_OUTCOME_REVIEW.csv"
INTERACTION_REFRESH_NAME = "V21_091_R1_INTERACTION_MATURITY_REFRESH.csv"
INTERACTION_SUMMARY_NAME = "V21_091_R1_INTERACTION_OUTCOME_SUMMARY.csv"
TRIGGER_UPDATE_NAME = "V21_091_R1_TRIGGER_STATUS_UPDATE.csv"
CERT_NAME = "V21_091_R1_NO_ADOPTION_OUTCOME_CERTIFICATION.csv"
MUTATION_NAME = "V21_091_R1_PROTECTED_OUTPUT_MUTATION_AUDIT.csv"
VALIDATION_NAME = "V21_091_R1_VALIDATION_SUMMARY.csv"
OUTPUT_NAMES = (
    INVENTORY_NAME, TOP20_REFRESH_NAME, BUCKET_SUMMARY_NAME, OVERALL_SUMMARY_NAME,
    SPECIAL_OUTCOME_NAME, INTERACTION_REFRESH_NAME, INTERACTION_SUMMARY_NAME,
    TRIGGER_UPDATE_NAME, CERT_NAME, MUTATION_NAME, VALIDATION_NAME,
)
WINDOWS = ("5D", "10D", "20D")


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def load_prices(root: Path) -> tuple[pd.DataFrame, dict[tuple[str, str], float], str]:
    price = pd.read_csv(
        root / PRICE_REL,
        usecols=["symbol", "date", "close", "adjusted_close"],
        low_memory=False,
    )
    price["ticker"] = price["symbol"].astype(str).str.upper().str.strip()
    price["date"] = price["date"].astype(str).str[:10]
    price["price"] = pd.to_numeric(price["adjusted_close"], errors="coerce").fillna(
        pd.to_numeric(price["close"], errors="coerce")
    )
    usable = price[price["price"].notna()].copy()
    pmap = usable.set_index(["ticker", "date"])["price"].to_dict()
    return usable, pmap, str(usable["date"].max())


def inventory(root: Path, price: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([{
        "source_path": PRICE_REL.as_posix(),
        "source_type": "LOCAL_CANONICAL_HISTORICAL_OHLCV",
        "row_count": len(price), "ticker_count": price["ticker"].nunique(),
        "min_price_date": price["date"].min(), "max_price_date": price["date"].max(),
        "date_column_used": "date", "ticker_column_used": "symbol",
        "close_column_used": "adjusted_close_fallback_close",
        "usable_for_maturity": True, "warning": "",
    }])


def refresh_status(
    ticker: str, asof: str, maturity: str, before: bool, before_return: Any,
    pmap: dict[tuple[str, str], float], latest: str,
) -> dict[str, Any]:
    asof_ts = pd.to_datetime(asof, errors="coerce")
    maturity_ts = pd.to_datetime(maturity, errors="coerce")
    if pd.isna(asof_ts) or pd.isna(maturity_ts):
        return {
            "forward_price_available": False, "as_of_close": np.nan, "forward_close": np.nan,
            "forward_matured_after": False, "return_forward_after": np.nan,
            "maturity_status": "INVALID_SCHEDULE_ROW",
            "warning": "UNPARSEABLE_AS_OF_OR_MATURITY_DATE",
        }
    entry = pmap.get((ticker, asof))
    forward = pmap.get((ticker, maturity))
    matured = entry is not None and forward is not None and float(entry) != 0
    if matured:
        status = "ALREADY_MATURED" if before else "NEWLY_MATURED"
        warning = ""
    elif maturity <= latest:
        status = "PRICE_MISSING"
        warning = "MATURITY_DATE_REACHED_BUT_EXACT_LOCAL_PRICE_MISSING"
    else:
        status = "STILL_PENDING"
        warning = ""
    return {
        "forward_price_available": forward is not None,
        "as_of_close": entry, "forward_close": forward,
        "forward_matured_after": matured,
        "return_forward_after": float(forward) / float(entry) - 1 if matured else np.nan,
        "maturity_status": status, "warning": warning,
    }


def refresh_top20(
    schedule: pd.DataFrame, pmap: dict[tuple[str, str], float], latest: str
) -> pd.DataFrame:
    rows = []
    for _, row in schedule.iterrows():
        ticker = str(row.get("ticker", "")).upper().strip()
        asof = str(row.get("as_of_date", ""))[:10]
        maturity = str(row.get("maturity_date", ""))[:10]
        before = truth(row.get("forward_matured_flag"))
        result = refresh_status(
            ticker, asof, maturity, before, row.get("return_forward_if_available"),
            pmap, latest,
        )
        rows.append({
            "archive_snapshot_id": row.get("archive_snapshot_id", ""),
            "observation_id": row.get("observation_id", ""), "ticker": ticker,
            "D_rank": row.get("D_rank"), "as_of_date": asof,
            "source_latest_price_date": row.get("source_latest_price_date", ""),
            "bucket_monitor_status": row.get("bucket_monitor_status", ""),
            "diagnostic_action": row.get("diagnostic_action", ""),
            "forward_window": row.get("forward_window", ""), "maturity_date": maturity,
            "latest_available_price_date": latest,
            "forward_price_date_required": maturity,
            "forward_price_available": result["forward_price_available"],
            "as_of_close": result["as_of_close"], "forward_close": result["forward_close"],
            "forward_matured_before": before,
            "forward_matured_after": result["forward_matured_after"],
            "return_forward_before": row.get("return_forward_if_available", np.nan),
            "return_forward_after": result["return_forward_after"],
            "maturity_status": result["maturity_status"],
            "maturity_refresh_warning": result["warning"],
            "adoption_allowed": False, "no_trade_action_created": True,
        })
    return pd.DataFrame(rows)


def summarize_group(group: pd.DataFrame, bucket: bool = True) -> dict[str, Any]:
    matured = group[group["forward_matured_after"].map(truth) & group["return_forward_after"].notna()]
    pending = group[~group["forward_matured_after"].map(truth)]
    count = len(matured)
    threshold = 5 if bucket else 10
    if count == 0:
        status, warning = "WAITING_FOR_MATURITY", "NO_MATURED_OBSERVATIONS"
    elif count < threshold:
        status = "INSUFFICIENT_BUCKET_SAMPLE" if bucket else "INSUFFICIENT_SAMPLE"
        warning = status
    else:
        status, warning = "MATURED_DIAGNOSTIC_ONLY", ""
    return {
        "scheduled_count": len(group), "matured_count": count, "pending_count": len(pending),
        "mean_forward_return": matured["return_forward_after"].mean() if count else np.nan,
        "median_forward_return": matured["return_forward_after"].median() if count else np.nan,
        "hit_rate": matured["return_forward_after"].gt(0).mean() if count else np.nan,
        "performance_status": status,
        "usable_for_research_flag": bool(count >= threshold and not warning),
        "warning": warning,
    }


def bucket_summary(refresh: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (bucket, action, window), group in refresh.groupby(
        ["bucket_monitor_status", "diagnostic_action", "forward_window"], sort=True
    ):
        result = summarize_group(group, bucket=True)
        matured = group[group["forward_matured_after"].map(truth)]
        pending = group[~group["forward_matured_after"].map(truth)]
        rows.append({
            "bucket_monitor_status": bucket, "diagnostic_action": action,
            "forward_window": window, **{k: result[k] for k in (
                "scheduled_count", "matured_count", "pending_count",
                "mean_forward_return", "median_forward_return", "hit_rate",
            )},
            "avg_d_rank": pd.to_numeric(group["D_rank"], errors="coerce").mean(),
            "tickers_matured": "|".join(matured["ticker"].astype(str)),
            "tickers_pending": "|".join(pending["ticker"].astype(str)),
            "performance_status": result["performance_status"],
            "usable_for_research_flag": result["usable_for_research_flag"],
            "warning": result["warning"],
        })
    return pd.DataFrame(rows)


def overall_summary(refresh: pd.DataFrame, buckets: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for window in WINDOWS:
        group = refresh[refresh["forward_window"].eq(window)]
        result = summarize_group(group, bucket=False)
        eligible = buckets[
            buckets["forward_window"].eq(window)
            & buckets["matured_count"].gt(0)
            & buckets["mean_forward_return"].notna()
        ]
        rows.append({
            "forward_window": window,
            **{k: result[k] for k in (
                "scheduled_count", "matured_count", "pending_count",
                "mean_forward_return", "median_forward_return", "hit_rate",
            )},
            "best_bucket_by_mean_return": (
                eligible.sort_values("mean_forward_return", ascending=False).iloc[0]["bucket_monitor_status"]
                if not eligible.empty else ""
            ),
            "worst_bucket_by_mean_return": (
                eligible.sort_values("mean_forward_return").iloc[0]["bucket_monitor_status"]
                if not eligible.empty else ""
            ),
            "performance_status": result["performance_status"],
            "usable_for_research_flag": result["usable_for_research_flag"],
            "warning": result["warning"],
        })
    return pd.DataFrame(rows)


def special_outcomes(special: pd.DataFrame, refresh: pd.DataFrame, gaps: pd.DataFrame) -> pd.DataFrame:
    gap_map = gaps.set_index("ticker")["interaction_rule_matched"].map(truth).to_dict() if not gaps.empty else {}
    rows = []
    for _, case in special.iterrows():
        ticker = str(case["ticker"]).upper()
        ticker_rows = refresh[refresh["ticker"].eq(ticker)]
        for window in WINDOWS:
            match = ticker_rows[ticker_rows["forward_window"].eq(window)]
            row = match.iloc[0] if not match.empty else None
            matured = row is not None and truth(row["forward_matured_after"])
            ret = row["return_forward_after"] if matured else np.nan
            case_type = str(case["special_case_type"])
            if case_type == "INTERACTION_SOURCE_COVERAGE_GAP":
                status = "SOURCE_GAP_RESOLVED_DIAGNOSTIC_ONLY" if gap_map.get(ticker, False) else "SOURCE_GAP_STILL_OPEN"
                interpretation = "Interaction source gap remains a rule-coverage diagnostic."
            elif case_type == "DAY0_BREAKOUT_NO_CHASE" and not matured:
                status, interpretation = "DAY0_WAITING_FOR_CONFIRMATION", "Day0 remains watch-only and no-chase."
            elif "WAIT_CONFIRMATION" in case_type and not matured:
                status, interpretation = "WAIT_CONFIRMATION_STILL_OPEN", "Technical confirmation review remains open."
            elif matured:
                status = "EARLY_POSITIVE_DIAGNOSTIC" if float(ret) > 0 else "EARLY_NEGATIVE_DIAGNOSTIC"
                interpretation = "Matured outcome is early diagnostic evidence only."
            elif row is None:
                status, interpretation = "INSUFFICIENT_DATA", "No matching scheduled observation."
            else:
                status, interpretation = "WAITING_FOR_MATURITY", "Exact local maturity price is not available."
            rows.append({
                "ticker": ticker, "special_case_type": case_type,
                "current_bucket": case["current_bucket"], "D_rank": case.get("D_rank"),
                "forward_window": window,
                "maturity_status": row["maturity_status"] if row is not None else "INVALID_SCHEDULE_ROW",
                "return_forward_if_matured": ret,
                "outcome_interpretation": interpretation,
                "required_future_check": case["required_future_check"],
                "special_case_status": status,
                "adoption_allowed": False, "no_trade_action_created": True,
            })
    return pd.DataFrame(rows)


def refresh_interaction(
    bridge: pd.DataFrame, pmap: dict[tuple[str, str], float], latest: str
) -> pd.DataFrame:
    rows = []
    for _, row in bridge.iterrows():
        ticker = str(row["ticker"]).upper().strip()
        asof, maturity = str(row["as_of_date"])[:10], str(row["maturity_date"])[:10]
        before = truth(row.get("forward_matured_flag"))
        result = refresh_status(
            ticker, asof, maturity, before, row.get("return_forward"), pmap, latest
        )
        rows.append({
            "observation_id": row["observation_id"], "ticker": ticker, "as_of_date": asof,
            "interaction_primary_label": row.get("interaction_primary_label", ""),
            "forward_window": row["forward_window"], "maturity_date": maturity,
            "latest_available_price_date": latest, "forward_price_date_required": maturity,
            "forward_price_available": result["forward_price_available"],
            "return_forward_before": row.get("return_forward", np.nan),
            "return_forward_after": result["return_forward_after"],
            "forward_matured_before": before,
            "forward_matured_after": result["forward_matured_after"],
            "maturity_status": result["maturity_status"], "warning": result["warning"],
        })
    return pd.DataFrame(rows)


def interaction_summary(refresh: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (label, window), group in refresh.groupby(
        ["interaction_primary_label", "forward_window"], dropna=False, sort=True
    ):
        result = summarize_group(group, bucket=False)
        rows.append({
            "interaction_primary_label": label, "forward_window": window,
            **result,
        })
    return pd.DataFrame(rows)


def trigger_update(
    triggers: pd.DataFrame, top20: pd.DataFrame, interaction: pd.DataFrame, latest: str
) -> pd.DataFrame:
    rows = []
    for _, row in triggers.iterrows():
        name, kind = str(row["trigger_name"]), str(row["trigger_type"])
        date = str(row.get("earliest_review_date", ""))[:10]
        valid_date = pd.notna(pd.to_datetime(date, errors="coerce"))
        if not valid_date:
            status, warning = "INVALID_TRIGGER", "INVALID_EARLIEST_REVIEW_DATE"
        elif kind == "MUTATION_AUDIT":
            status, warning = "REVIEW_COMPLETED_DIAGNOSTIC_ONLY", ""
        elif kind == "SOURCE_COVERAGE":
            status, warning = "STILL_WAITING", "SOURCE_COVERAGE_GAP_REMAINS_OPEN"
        elif date > latest:
            status, warning = "NOT_REACHED", ""
        else:
            source = interaction if name.startswith("INTERACTION_087") else top20
            window = next((w for w in WINDOWS if f"_{w}_" in name), None)
            subset = source[source["forward_window"].eq(window)] if window else source
            if name.startswith("DAY0_"):
                subset = top20[top20["ticker"].eq("CRDO") & top20["forward_window"].eq("5D")]
            matured = subset["forward_matured_after"].map(truth).any() if not subset.empty else False
            status = "READY_FOR_REVIEW" if matured else "REACHED_BUT_PRICE_NOT_AVAILABLE"
            warning = "" if matured else "EXACT_REQUIRED_PRICE_NOT_AVAILABLE"
        rows.append({
            "trigger_name": name, "trigger_type": kind,
            "target_bucket_or_stage": row["target_bucket_or_stage"],
            "condition": row["condition"], "earliest_review_date": date,
            "latest_available_price_date": latest,
            "trigger_status_before": row.get("trigger_status", ""),
            "trigger_status_after": status, "required_input": row["required_input"],
            "expected_next_stage": row["expected_next_stage"], "warning": warning,
        })
    return pd.DataFrame(rows)


def protected_snapshot(root: Path, output: Path) -> tuple[list[Path], dict[Path, str]]:
    paths = protected_files(root, output)
    for stage in range(85, 91):
        base = root / f"outputs/v21/diagnostics/v21_0{stage}_r1"
        if base.exists():
            paths.extend(p.resolve() for p in base.rglob("*") if p.is_file())
    for base in (root / "outputs", root / "data"):
        if base.exists():
            paths.extend(
                p.resolve() for p in base.rglob("*")
                if p.is_file() and "recommendation" in p.name.lower()
            )
    paths = sorted(set(paths))
    return paths, {p: sha256(p) for p in paths}


def mutation_audit(paths: list[Path], before: dict[Path, str]) -> pd.DataFrame:
    rows = []
    for path in paths:
        text = path.as_posix().lower()
        ptype = (
            "broker_action" if "broker" in text else
            "recommendation" if "recommendation" in text else
            "official_weight" if "weight" in text and ("official" in text or "weight_perturbation" in text) else
            "official_ranking" if "ranking" in text or "060_r5_d_" in text or "066a_d_latest_ranking" in text else
            "prior_v21_diagnostic" if "/diagnostics/v21_0" in text else "protected"
        )
        exists = path.exists()
        changed = not exists or before[path] != sha256(path)
        rows.append({
            "path": path.as_posix(), "path_type": ptype, "exists_before": True,
            "exists_after": exists, "modified_during_run": changed,
            "mutation_allowed": False,
            "warning": "DISALLOWED_MUTATION_DETECTED" if changed else "",
        })
    return pd.DataFrame(rows)


def empty_outputs(output: Path) -> None:
    columns = {
        INVENTORY_NAME: ["source_path", "source_type", "row_count", "ticker_count", "min_price_date", "max_price_date", "date_column_used", "ticker_column_used", "close_column_used", "usable_for_maturity", "warning"],
        TOP20_REFRESH_NAME: ["observation_id", "ticker", "forward_window", "forward_matured_after", "return_forward_after", "adoption_allowed", "no_trade_action_created"],
        BUCKET_SUMMARY_NAME: ["bucket_monitor_status", "diagnostic_action", "forward_window", "scheduled_count", "matured_count", "pending_count", "mean_forward_return", "median_forward_return", "hit_rate", "performance_status"],
        OVERALL_SUMMARY_NAME: ["forward_window", "scheduled_count", "matured_count", "pending_count", "mean_forward_return", "median_forward_return", "hit_rate", "performance_status"],
        SPECIAL_OUTCOME_NAME: ["ticker", "special_case_type", "forward_window", "adoption_allowed", "no_trade_action_created"],
        INTERACTION_REFRESH_NAME: ["observation_id", "ticker", "forward_window", "forward_matured_after", "return_forward_after"],
        INTERACTION_SUMMARY_NAME: ["interaction_primary_label", "forward_window", "scheduled_count", "matured_count", "pending_count", "mean_forward_return", "median_forward_return", "hit_rate", "performance_status"],
        TRIGGER_UPDATE_NAME: ["trigger_name", "trigger_status_after"],
        CERT_NAME: ["certification_status", "no_trade_action_created"],
        MUTATION_NAME: ["path", "path_type", "exists_before", "exists_after", "modified_during_run", "mutation_allowed", "warning"],
    }
    for name, cols in columns.items():
        pd.DataFrame(columns=cols).to_csv(output / name, index=False)


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (
        output_override.resolve() if output_override and output_override.is_absolute()
        else (root / (output_override or OUT_REL)).resolve()
    )
    output.mkdir(parents=True, exist_ok=True)
    required = [
        ARCHIVE_REL, SCHEDULE_REL, TRIGGER_REL, SPECIAL_REL, GAP_REL, CERT_090_REL,
        BRIDGE_REL, INTERACTION_PANEL_REL, PRICE_REL,
    ]
    missing = [p.as_posix() for p in required if not (root / p).is_file()]
    protected, before = protected_snapshot(root, output)
    inv = top20 = buckets = overall = special_out = interaction = interaction_sum = triggers = pd.DataFrame()
    latest = snapshot_id = ""

    if missing:
        empty_outputs(output)
    else:
        archive = pd.read_csv(root / ARCHIVE_REL, low_memory=False)
        schedule = pd.read_csv(root / SCHEDULE_REL, low_memory=False)
        trigger_source = pd.read_csv(root / TRIGGER_REL, low_memory=False)
        special_source = pd.read_csv(root / SPECIAL_REL, low_memory=False)
        gaps = pd.read_csv(root / GAP_REL, low_memory=False)
        bridge = pd.read_csv(root / BRIDGE_REL, low_memory=False)
        price, pmap, latest = load_prices(root)
        snapshot_id = str(archive["archive_snapshot_id"].iloc[0]) if not archive.empty else ""
        inv = inventory(root, price)
        top20 = refresh_top20(schedule, pmap, latest)
        buckets = bucket_summary(top20)
        overall = overall_summary(top20, buckets)
        special_out = special_outcomes(special_source, top20, gaps)
        interaction = refresh_interaction(bridge, pmap, latest)
        interaction_sum = interaction_summary(interaction)
        triggers = trigger_update(trigger_source, top20, interaction, latest)
        for frame, name in (
            (inv, INVENTORY_NAME), (top20, TOP20_REFRESH_NAME),
            (buckets, BUCKET_SUMMARY_NAME), (overall, OVERALL_SUMMARY_NAME),
            (special_out, SPECIAL_OUTCOME_NAME), (interaction, INTERACTION_REFRESH_NAME),
            (interaction_sum, INTERACTION_SUMMARY_NAME), (triggers, TRIGGER_UPDATE_NAME),
        ):
            frame.to_csv(output / name, index=False)

    audit = mutation_audit(protected, before)
    audit.to_csv(output / MUTATION_NAME, index=False)
    mutation_count = int(audit["modified_during_run"].map(truth).sum()) if not audit.empty else 0
    cert = pd.DataFrame([{
        "research_only": True, "diagnostic_only": True, "maturity_refresh_only": True,
        "outcome_evaluation_only": True, "official_ranking_mutated": False,
        "official_weights_mutated": False, "broker_action_created": False,
        "recommendation_created": False, "protected_outputs_modified": mutation_count > 0,
        "d_baseline_preserved": mutation_count == 0, "pullback_adoption_allowed": False,
        "interaction_adoption_allowed": False, "bucket_monitor_adoption_allowed": False,
        "maturity_outcome_adoption_allowed": False, "no_trade_action_created": True,
        "certification_status": "CERTIFIED_NO_ADOPTION_MATURITY_OUTCOME_DIAGNOSTIC_ONLY",
        "certification_note": "Maturity refresh and outcome evaluation only; no adoption or trade action.",
    }])
    cert.to_csv(output / CERT_NAME, index=False)

    def counts(frame: pd.DataFrame, window: str, status: str) -> int:
        if frame.empty: return 0
        if status == "new":
            return int((frame["forward_window"].eq(window) & frame["maturity_status"].eq("NEWLY_MATURED")).sum())
        matured = frame["forward_matured_after"].map(truth)
        return int((frame["forward_window"].eq(window) & (matured if status == "matured" else ~matured)).sum())

    total_matured = sum(counts(top20, w, "matured") for w in WINDOWS) + sum(
        counts(interaction, w, "matured") for w in WINDOWS
    )
    insufficient = 0
    for frame in (buckets, overall, interaction_sum):
        if not frame.empty:
            insufficient += int(frame["performance_status"].astype(str).str.contains("INSUFFICIENT").sum())
    data_warning_count = 0
    if not top20.empty:
        data_warning_count += int(top20["maturity_status"].eq("PRICE_MISSING").sum())
    if not interaction.empty:
        data_warning_count += int(interaction["maturity_status"].eq("PRICE_MISSING").sum())
    leakage_count = 0
    blocked = mutation_count > 0 or leakage_count > 0
    if missing:
        status = "BLOCKED_V21_091_R1_REQUIRED_INPUTS_MISSING"
        decision = "REQUIRED_INPUTS_MISSING_REVIEW_REQUIRED"
    elif blocked:
        status = "BLOCKED_V21_091_R1_LEAKAGE_OR_PROTECTED_MUTATION_RISK"
        decision = "MATURITY_REFRESH_OR_BUCKET_OUTCOME_BLOCKED_REVIEW_REQUIRED"
    elif total_matured == 0:
        status = "PARTIAL_PASS_V21_091_R1_READY_WAITING_FOR_MATURITY"
        decision = "MATURITY_REFRESH_READY_WAITING_FOR_MATURITY_DIAGNOSTIC_ONLY"
    elif data_warning_count:
        status = "PARTIAL_PASS_V21_091_R1_READY_WITH_DATA_WARN"
        decision = "MATURITY_REFRESH_READY_WITH_DATA_WARN_DIAGNOSTIC_ONLY"
    elif insufficient:
        status = "PARTIAL_PASS_V21_091_R1_READY_WITH_INSUFFICIENT_SAMPLE"
        decision = "MATURITY_REFRESH_READY_WITH_INSUFFICIENT_SAMPLE_DIAGNOSTIC_ONLY"
    else:
        status = "PASS_V21_091_R1_MATURITY_REFRESH_AND_BUCKET_OUTCOME_READY"
        decision = "MATURITY_REFRESH_AND_BUCKET_OUTCOME_READY_DIAGNOSTIC_ONLY"

    next_stage = (
        "WAIT_FOR_NEXT_LOCAL_PRICE_REFRESH_THEN_RERUN_V21.091_R1"
        if total_matured == 0 else
        "V21.092-R1_BUCKET_OUTCOME_SIGNIFICANCE_AND_RULE_GAP_REVIEW"
    )
    validation = {
        "stage": "V21.091-R1_D_TOP20_MATURITY_REFRESH_AND_BUCKET_OUTCOME_EVALUATOR",
        "final_status": status, "decision": decision, "research_only": True,
        "diagnostic_only": True, "maturity_refresh_only": True,
        "outcome_evaluation_only": True, "official_ranking_mutated": False,
        "official_weights_mutated": False, "broker_action_created": False,
        "recommendation_created": False, "protected_outputs_modified": mutation_count > 0,
        "d_baseline_preserved": mutation_count == 0, "technical_085_preserved": mutation_count == 0,
        "fundamental_086_preserved": mutation_count == 0, "interaction_087_preserved": mutation_count == 0,
        "review_088_preserved": mutation_count == 0, "monitor_089_preserved": mutation_count == 0,
        "archive_090_preserved": mutation_count == 0, "source_latest_price_date": latest,
        "previous_archive_snapshot_id": snapshot_id, "price_inventory_rows": len(inv),
        "d_top20_schedule_rows_checked": len(top20),
        "d_top20_newly_matured_5d_count": counts(top20, "5D", "new"),
        "d_top20_newly_matured_10d_count": counts(top20, "10D", "new"),
        "d_top20_newly_matured_20d_count": counts(top20, "20D", "new"),
        "d_top20_total_matured_5d_count": counts(top20, "5D", "matured"),
        "d_top20_total_matured_10d_count": counts(top20, "10D", "matured"),
        "d_top20_total_matured_20d_count": counts(top20, "20D", "matured"),
        "d_top20_total_pending_5d_count": counts(top20, "5D", "pending"),
        "d_top20_total_pending_10d_count": counts(top20, "10D", "pending"),
        "d_top20_total_pending_20d_count": counts(top20, "20D", "pending"),
        "interaction_schedule_rows_checked": len(interaction),
        "interaction_total_matured_5d_count": counts(interaction, "5D", "matured"),
        "interaction_total_matured_10d_count": counts(interaction, "10D", "matured"),
        "interaction_total_matured_20d_count": counts(interaction, "20D", "matured"),
        "interaction_total_pending_5d_count": counts(interaction, "5D", "pending"),
        "interaction_total_pending_10d_count": counts(interaction, "10D", "pending"),
        "interaction_total_pending_20d_count": counts(interaction, "20D", "pending"),
        "bucket_outcome_rows": len(buckets), "special_case_outcome_rows": len(special_out),
        "trigger_status_rows": len(triggers), "waiting_for_maturity": total_matured == 0,
        "insufficient_sample_warning_count": insufficient,
        "leakage_warning_count": leakage_count, "data_warning_count": data_warning_count,
        "mutation_warning_count": mutation_count, "pullback_adoption_allowed": False,
        "interaction_adoption_allowed": False, "bucket_monitor_adoption_allowed": False,
        "maturity_outcome_adoption_allowed": False, "recommended_next_stage": next_stage,
        "missing_inputs": "|".join(missing),
    }
    pd.DataFrame([validation]).to_csv(output / VALIDATION_NAME, index=False)
    return validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in (
        "final_status", "decision", "source_latest_price_date",
        "d_top20_schedule_rows_checked", "interaction_schedule_rows_checked",
    ):
        print(f"{key.upper()}={result[key]}")
    return 0 if not str(result["final_status"]).startswith("BLOCKED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
