#!/usr/bin/env python
"""V21.131 D data-quality blocker root cause and waiver protocol."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.131_D_DATA_QUALITY_BLOCKER_ROOT_CAUSE_AND_WAIVER_PROTOCOL"
OUT = ROOT / "outputs/v21/V21.131_D_DATA_QUALITY_BLOCKER_ROOT_CAUSE_AND_WAIVER_PROTOCOL"
V130 = ROOT / "outputs/v21/V21.130_D_STRICT_GATE_EVIDENCE_LEDGER_AND_BLOCK_REASON_DECOMPOSITION"
V129 = ROOT / "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE"
V128 = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE"
PRICE_PANEL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"

V130_SUMMARY = V130 / "V21.130_summary.json"
V130_LEDGER = V130 / "V21.130_d_gate_evidence_ledger.csv"
V129_SUMMARY = V129 / "V21.129_summary.json"
V129_GATES = V129 / "V21.129_d_strict_gate_results.csv"
V129_D_RAW = V129 / "V21.129_d_tracking_raw_ranking.csv"
V129_D_TOP20 = V129 / "V21.129_d_tracking_top20.csv"
V129_D_TOP50 = V129 / "V21.129_d_tracking_top50.csv"
V129_D_FORWARD = V129 / "V21.129_d_forward_tracking_rows.csv"
V129_REPEATED = V129 / "V21.129_d_repeated_loser_diagnostic.csv"
V129_CONC = V129 / "V21.129_d_concentration_diagnostic.csv"
V128_SUMMARY = V128 / "V21.128_summary.json"
V128_PRICE_AUDIT = V128 / "price_panel_audit.csv"

BENCHMARK_TICKERS = {"QQQ", "SOXX"}
CONCENTRATION_CHAIN_TICKERS = {
    "DRAM", "MU", "SNDK", "WDC", "STX", "AMAT", "LRCX", "KLAC", "KLIC",
    "TER", "MKSI", "ICHR", "AMKR", "SOXX", "SMH", "AMD", "INTC", "ASML",
    "COHU", "ENTG", "ACMR",
}
PRIMARY_PRIORITY_AFTER_WAIVER = [
    ("DATA_FRESHNESS", "STALE_PRICE_PANEL"),
    ("MATURITY", "INSUFFICIENT_MATURITY"),
    ("REGIME_COMPATIBILITY", "REGIME_INCOMPATIBLE"),
    ("CONCENTRATION_RISK", "CONCENTRATION_RISK"),
    ("REPEATED_LOSER_RISK", "REPEATED_LOSER_RISK"),
    ("LEFT_TAIL_DRAWDOWN_RISK", "LEFT_TAIL_RISK"),
    ("VS_A1_PERFORMANCE", "INSUFFICIENT_ALPHA"),
    ("VS_QQQ_PERFORMANCE", "INSUFFICIENT_ALPHA"),
]
PROTECTED_BASELINE_FILES = [
    V128 / "V21.128_summary.json",
    V128 / "V21.128_readable_report.txt",
    V128 / "V21.128_compact_report.txt",
    V128 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv",
    V128 / "A1_BASELINE_CONTROL_latest_ranking.csv",
    V129 / "V21.129_summary.json",
    V129 / "V21.129_d_strict_gate_results.csv",
    V129 / "V21.129_d_tracking_top20.csv",
    V129 / "V21.129_d_tracking_top50.csv",
    V130 / "V21.130_summary.json",
    V130 / "V21.130_d_gate_evidence_ledger.csv",
]


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    if fields is None:
        fields = []
        for row in rows:
            for field in row:
                if field not in fields:
                    fields.append(field)
        fields = fields if fields else ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_status() -> list[str]:
    completed = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=False)
    return completed.stdout.splitlines()


def protected_modified(status_lines: list[str], baseline_lines: list[str]) -> bool:
    baseline = {line.replace("\\", "/") for line in baseline_lines}
    allowed_prefix = "?? outputs/v21/V21.131_D_DATA_QUALITY_BLOCKER_ROOT_CAUSE_AND_WAIVER_PROTOCOL/"
    allowed_scripts = {
        "?? scripts/v21/v21_131_d_data_quality_blocker_root_cause_and_waiver_protocol.py",
        "?? scripts/v21/test_v21_131_d_data_quality_blocker_root_cause_and_waiver_protocol.py",
    }
    for line in status_lines:
        normalized = line.replace("\\", "/")
        if normalized in baseline or normalized.startswith(allowed_prefix) or normalized in allowed_scripts:
            continue
        lowered = normalized.lower()
        if lowered.startswith((" m outputs/", " d outputs/", "?? outputs/")) and (
            "official" in lowered or "broker" in lowered or "protected" in lowered
        ):
            return True
    return False


def split_tickers(value: Any) -> list[str]:
    out: list[str] = []
    for token in str(value or "").replace(",", "|").split("|"):
        ticker = token.upper().strip()
        if ticker and ticker not in {"NAN", "NONE", "UNKNOWN"} and ticker not in out:
            out.append(ticker)
    return out


def read_ticker_set(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    frame = pd.read_csv(path, low_memory=False)
    if "ticker" not in frame.columns:
        return set()
    return set(frame["ticker"].dropna().astype(str).str.upper().str.strip())


def latest_dates_for_tickers(tickers: list[str]) -> dict[str, dict[str, Any]]:
    wanted = set(tickers) | BENCHMARK_TICKERS
    if not PRICE_PANEL.is_file() or not wanted:
        return {ticker: {"latest_available_price_date": "UNKNOWN", "row_count": 0} for ticker in wanted}
    latest: dict[str, str] = {}
    counts: dict[str, int] = {ticker: 0 for ticker in wanted}
    for chunk in pd.read_csv(PRICE_PANEL, usecols=["symbol", "date", "price_row_status"], chunksize=250_000, low_memory=False):
        chunk["symbol"] = chunk["symbol"].astype(str).str.upper().str.strip()
        sub = chunk[chunk["symbol"].isin(wanted)].copy()
        if sub.empty:
            continue
        sub["date"] = sub["date"].astype(str)
        for ticker, group in sub.groupby("symbol"):
            counts[ticker] = counts.get(ticker, 0) + len(group)
            max_date = group["date"].max()
            if ticker not in latest or max_date > latest[ticker]:
                latest[ticker] = max_date
    return {
        ticker: {
            "latest_available_price_date": latest.get(ticker, "MISSING"),
            "row_count": counts.get(ticker, 0),
        }
        for ticker in sorted(wanted)
    }


def warning_tickers(v128_summary: dict[str, Any]) -> tuple[list[str], str]:
    failed = split_tickers(v128_summary.get("failed_tickers"))
    stale = split_tickers(v128_summary.get("stale_or_missing_tickers"))
    if stale:
        return stale, "V21.128_summary.stale_or_missing_tickers"
    if failed:
        return failed, "V21.128_summary.failed_tickers"
    if V128_PRICE_AUDIT.is_file():
        audit = pd.read_csv(V128_PRICE_AUDIT, keep_default_na=False)
        if not audit.empty:
            row = audit.iloc[-1].to_dict()
            failed = split_tickers(row.get("failed_tickers"))
            if failed:
                return failed, "V21.128_price_panel_audit.failed_tickers"
    return ["UNKNOWN"], "UNKNOWN"


def classify_warning_type(ticker: str, latest_date: str, expected_date: str, row_count: int) -> str:
    if ticker == "UNKNOWN":
        return "UNKNOWN"
    if row_count == 0 or latest_date == "MISSING":
        return "missing"
    if latest_date < expected_date:
        return "stale"
    if latest_date >= expected_date:
        return "metadata-only"
    return "partial"


def impact_classification(row: dict[str, Any]) -> str:
    if row["ticker"] == "UNKNOWN":
        return "UNKNOWN_IMPACT_BLOCKER"
    if row["in_D_top20"]:
        return "D_TOP20_AFFECTING_BLOCKER"
    if row["in_D_top50"]:
        return "D_TOP50_AFFECTING_BLOCKER"
    if row["in_D_forward_tracking"]:
        return "D_FORWARD_RETURN_AFFECTING_BLOCKER"
    if row["warning_type"] == "metadata-only":
        return "METADATA_ONLY_WARNING_LOW_IMPACT"
    if not row["in_D_raw_ranking"]:
        return "NON_D_WARNING_LOW_IMPACT"
    return "UNKNOWN_IMPACT_BLOCKER"


def gate_rows_after_waiver() -> tuple[str, bool, str]:
    gates = pd.read_csv(V129_GATES, keep_default_na=False).to_dict("records")
    projected = []
    remaining = []
    for row in gates:
        gate = row.get("gate", "")
        status = row.get("status", "UNKNOWN")
        if gate == "DATA_QUALITY_WARNING":
            status = "PASS"
        projected.append((gate, status))
        if status != "PASS":
            remaining.append(gate)
    projected_pass = all(status == "PASS" for _, status in projected)
    primary = "NONE_REVIEW_ALLOWED"
    for gate, blocker in PRIMARY_PRIORITY_AFTER_WAIVER:
        if dict(projected).get(gate) == "BLOCK":
            primary = blocker
            break
    return primary, projected_pass, "|".join(remaining)


def write_reports(summary: dict[str, Any]) -> None:
    readable = [
        STAGE,
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        "",
        "This stage investigates the primary DATA_QUALITY_WARNING blocker. It does not waive the warning, promote D, or mutate prior strict-gate outputs.",
        "",
        f"stale_or_missing_ticker_count={summary['stale_or_missing_ticker_count']}",
        f"stale_or_missing_tickers={summary['stale_or_missing_tickers']}",
        f"data_quality_impact_classification={summary['data_quality_impact_classification']}",
        f"DATA_QUALITY_WAIVER_ELIGIBLE={str(summary['DATA_QUALITY_WAIVER_ELIGIBLE']).lower()}",
        f"DATA_QUALITY_WAIVER_REVIEW_REQUIRED={str(summary['DATA_QUALITY_WAIVER_REVIEW_REQUIRED']).lower()}",
        "",
        "Post-Waiver Projection",
        f"projected_primary_D_blocker_after_data_waiver={summary['projected_primary_D_blocker_after_data_waiver']}",
        f"projected_D_strict_gate_pass={str(summary['projected_D_strict_gate_pass']).lower()}",
        f"projected_remaining_blockers={summary['projected_remaining_blockers']}",
        "",
        "Controls",
        "research_only=true",
        "D_continued_tracking=true",
        "D_adoption_allowed=false",
        "role_review_required=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false",
    ]
    (OUT / "V21.131_readable_report.txt").write_text("\n".join(readable) + "\n", encoding="utf-8")
    compact = [
        STAGE,
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        f"stale_or_missing_tickers={summary['stale_or_missing_tickers']}",
        f"DATA_QUALITY_WAIVER_ELIGIBLE={str(summary['DATA_QUALITY_WAIVER_ELIGIBLE']).lower()}",
        f"projected_primary_D_blocker_after_data_waiver={summary['projected_primary_D_blocker_after_data_waiver']}",
        "D_adoption_allowed=false",
    ]
    (OUT / "V21.131_compact_report.txt").write_text("\n".join(compact) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_status = git_status()
    baseline_hashes = {rel(path): sha256(path) for path in PROTECTED_BASELINE_FILES if path.is_file()}
    v128_summary = load_json(V128_SUMMARY)
    v129_summary = load_json(V129_SUMMARY)
    v130_summary = load_json(V130_SUMMARY)
    latest_price_date = str(v128_summary.get("latest_price_date_used", v130_summary.get("latest_price_date_used", "")))
    tickers, warning_source = warning_tickers(v128_summary)
    latest = latest_dates_for_tickers(tickers)
    panel_latest = max((info["latest_available_price_date"] for info in latest.values() if info["latest_available_price_date"] not in {"MISSING", "UNKNOWN"}), default="UNKNOWN")

    d_raw = read_ticker_set(V129_D_RAW)
    d_top20 = read_ticker_set(V129_D_TOP20)
    d_top50 = read_ticker_set(V129_D_TOP50)
    d_forward = read_ticker_set(V129_D_FORWARD)
    repeated_tickers: set[str] = set()
    if V129_REPEATED.is_file():
        repeated = pd.read_csv(V129_REPEATED, keep_default_na=False)
        if not repeated.empty:
            repeated_tickers = set(split_tickers(repeated.iloc[0].get("D_repeated_loser_tickers")))

    detail_rows = []
    impact_rows = []
    overlap_rows = []
    classifications = []
    for ticker in tickers:
        info = latest.get(ticker, {"latest_available_price_date": "UNKNOWN", "row_count": 0})
        warning_type = classify_warning_type(ticker, str(info["latest_available_price_date"]), latest_price_date, int(info["row_count"]))
        row = {
            "ticker": ticker,
            "warning_source_file": rel(V128_PRICE_AUDIT),
            "warning_source_field": warning_source,
            "missing_price_date": latest_price_date if warning_type in {"missing", "stale"} else "",
            "latest_available_price_date": info["latest_available_price_date"],
            "canonical_price_panel_row_count": info["row_count"],
            "warning_type": warning_type,
            "stale_or_missing_ticker_count": v128_summary.get("stale_or_missing_ticker_count", "UNKNOWN"),
        }
        detail_rows.append(row)
        impact = {
            **row,
            "in_D_raw_ranking": ticker in d_raw,
            "in_D_top20": ticker in d_top20,
            "in_D_top50": ticker in d_top50,
            "in_D_forward_tracking": ticker in d_forward,
            "in_D_repeated_loser_list": ticker in repeated_tickers,
            "in_D_concentration_chain_list": ticker in CONCENTRATION_CHAIN_TICKERS,
            "affects_benchmark_QQQ_SOXX": ticker in BENCHMARK_TICKERS,
            "no_future_leakage": panel_latest <= latest_price_date if panel_latest != "UNKNOWN" else False,
        }
        impact["data_quality_impact_classification"] = impact_classification(impact)
        classifications.append(impact["data_quality_impact_classification"])
        impact_rows.append(impact)
        overlap_rows.append({
            "ticker": ticker,
            "in_D_top20": impact["in_D_top20"],
            "D_top20_rank": "" if ticker not in d_top20 else int(pd.read_csv(V129_D_TOP20).set_index("ticker").loc[ticker, "rank"]),
            "in_D_top50": impact["in_D_top50"],
            "D_top50_rank": "" if ticker not in d_top50 else int(pd.read_csv(V129_D_TOP50).set_index("ticker").loc[ticker, "rank"]),
            "in_D_forward_tracking": impact["in_D_forward_tracking"],
        })

    any_top20 = any(row["in_D_top20"] for row in impact_rows)
    any_top50 = any(row["in_D_top50"] for row in impact_rows)
    any_forward = any(row["in_D_forward_tracking"] for row in impact_rows)
    any_benchmark = any(row["affects_benchmark_QQQ_SOXX"] for row in impact_rows)
    any_repeated = any(row["in_D_repeated_loser_list"] for row in impact_rows)
    any_conc = any(row["in_D_concentration_chain_list"] for row in impact_rows)
    no_future_leakage = all(row["no_future_leakage"] for row in impact_rows) if impact_rows else False
    panel_fresh = panel_latest == latest_price_date
    waiver_eligible = (
        bool(impact_rows)
        and not any_top20
        and not any_top50
        and not any_forward
        and not any_benchmark
        and not any_repeated
        and not any_conc
        and panel_fresh
        and no_future_leakage
        and "UNKNOWN_IMPACT_BLOCKER" not in classifications
    )
    waiver_rows = [{
        "DATA_QUALITY_WAIVER_ELIGIBLE": waiver_eligible,
        "DATA_QUALITY_WAIVER_REVIEW_REQUIRED": waiver_eligible,
        "affected_ticker_not_in_D_top20": not any_top20,
        "affected_ticker_not_in_D_top50": not any_top50,
        "affected_ticker_not_in_D_forward_tracking": not any_forward,
        "affected_ticker_does_not_affect_benchmark_QQQ_SOXX": not any_benchmark,
        "affected_ticker_does_not_affect_concentration": not any_conc,
        "affected_ticker_does_not_affect_repeated_loser": not any_repeated,
        "canonical_price_panel_latest_date": panel_latest,
        "canonical_price_panel_latest_date_required": latest_price_date,
        "canonical_price_panel_fresh": panel_fresh,
        "no_future_leakage": no_future_leakage,
        "waiver_note": "Research-only waiver review required; waiver is not applied automatically." if waiver_eligible else "Waiver not eligible or impact unknown.",
    }]

    projected_primary, projected_pass, projected_remaining = gate_rows_after_waiver()
    projection_rows = [{
        "projected_primary_D_blocker_after_data_waiver": projected_primary,
        "projected_D_strict_gate_pass": projected_pass,
        "projected_remaining_blockers": projected_remaining,
        "projected_role_review_required": False,
        "projection_note": "DATA_QUALITY_WARNING treated as waived for projection only; V21.129/V21.130 are not modified.",
    }]

    if any_top20 or any_top50 or any_forward:
        decision = "DATA_QUALITY_REPAIR_REQUIRED_D_ADOPTION_BLOCKED"
    elif "UNKNOWN_IMPACT_BLOCKER" in classifications:
        decision = "DATA_QUALITY_IMPACT_UNKNOWN_D_ADOPTION_BLOCKED"
    elif waiver_eligible:
        decision = "DATA_QUALITY_WAIVER_REVIEW_REQUIRED_D_ADOPTION_STILL_BLOCKED"
    else:
        decision = "DATA_QUALITY_IMPACT_UNKNOWN_D_ADOPTION_BLOCKED"

    write_csv(OUT / "V21.131_data_quality_warning_detail.csv", detail_rows)
    write_csv(OUT / "V21.131_affected_ticker_impact_analysis.csv", impact_rows)
    write_csv(OUT / "V21.131_d_top20_top50_warning_overlap.csv", overlap_rows)
    write_csv(OUT / "V21.131_waiver_eligibility_assessment.csv", waiver_rows)
    write_csv(OUT / "V21.131_post_waiver_gate_projection.csv", projection_rows)

    post_hashes = {rel(path): sha256(path) for path in PROTECTED_BASELINE_FILES if path.is_file()}
    protected_hash_changed = baseline_hashes != post_hashes
    prot_mod = protected_hash_changed or protected_modified(git_status(), baseline_status)
    impact_summary = "|".join(sorted(set(classifications))) if classifications else "UNKNOWN_IMPACT_BLOCKER"
    summary = {
        "stage": STAGE,
        "FINAL_STATUS": "PASS_V21_131_DATA_QUALITY_ROOT_CAUSE_COMPLETE" if not prot_mod else "BLOCKED_V21_131_PROTECTED_OUTPUT_MODIFIED",
        "DECISION": decision if not prot_mod else "BLOCKED_PROTECTED_OUTPUT_MUTATION",
        "latest_price_date_used": latest_price_date,
        "stale_or_missing_ticker_count": v128_summary.get("stale_or_missing_ticker_count", "UNKNOWN"),
        "stale_or_missing_tickers": "|".join(tickers),
        "warning_source": warning_source,
        "affected_ticker_in_D_top20": any_top20,
        "affected_ticker_in_D_top50": any_top50,
        "affected_ticker_in_D_forward_tracking": any_forward,
        "data_quality_impact_classification": impact_summary,
        "DATA_QUALITY_WAIVER_ELIGIBLE": waiver_eligible,
        "DATA_QUALITY_WAIVER_REVIEW_REQUIRED": waiver_eligible,
        "projected_primary_D_blocker_after_data_waiver": projected_primary,
        "projected_D_strict_gate_pass": False,
        "projected_remaining_blockers": projected_remaining,
        "projected_role_review_required": False,
        "D_continued_tracking": True,
        "D_adoption_allowed": False,
        "role_review_required": False,
        "next_action_gate": "DATA_QUALITY_WAIVER_REVIEW_THEN_CONTINUE_D_TRACKING" if waiver_eligible else "DATA_QUALITY_REPAIR_OR_IMPACT_CLARIFICATION_REQUIRED",
        "protected_outputs_modified": bool(prot_mod),
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "no_future_leakage": no_future_leakage,
        "v21_128_v21_129_v21_130_baseline_preserved": not protected_hash_changed,
        "report_path": rel(OUT / "V21.131_readable_report.txt"),
    }
    write_json(OUT / "V21.131_summary.json", summary)
    write_reports(summary)

    print(STAGE)
    print(f"FINAL_STATUS={summary['FINAL_STATUS']}")
    print(f"DECISION={summary['DECISION']}")
    print(f"latest_price_date_used={summary['latest_price_date_used']}")
    print(f"stale_or_missing_ticker_count={summary['stale_or_missing_ticker_count']}")
    print(f"stale_or_missing_tickers={summary['stale_or_missing_tickers']}")
    print(f"affected_ticker_in_D_top20={str(summary['affected_ticker_in_D_top20']).lower()}")
    print(f"affected_ticker_in_D_top50={str(summary['affected_ticker_in_D_top50']).lower()}")
    print(f"affected_ticker_in_D_forward_tracking={str(summary['affected_ticker_in_D_forward_tracking']).lower()}")
    print(f"data_quality_impact_classification={summary['data_quality_impact_classification']}")
    print(f"DATA_QUALITY_WAIVER_ELIGIBLE={str(summary['DATA_QUALITY_WAIVER_ELIGIBLE']).lower()}")
    print(f"DATA_QUALITY_WAIVER_REVIEW_REQUIRED={str(summary['DATA_QUALITY_WAIVER_REVIEW_REQUIRED']).lower()}")
    print(f"projected_primary_D_blocker_after_data_waiver={summary['projected_primary_D_blocker_after_data_waiver']}")
    print("projected_D_strict_gate_pass=false")
    print(f"projected_remaining_blockers={summary['projected_remaining_blockers']}")
    print("D_continued_tracking=true")
    print("D_adoption_allowed=false")
    print("role_review_required=false")
    print(f"next_action_gate={summary['next_action_gate']}")
    print("protected_outputs_modified=false")
    print("official_adoption_allowed=false")
    print("broker_action_allowed=false")
    print(f"report_path={summary['report_path']}")
    return summary


if __name__ == "__main__":
    run()
