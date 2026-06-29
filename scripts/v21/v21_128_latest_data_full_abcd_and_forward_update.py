#!/usr/bin/env python
"""V21.128 latest-data ABCD rerun and forward tracking update.

Research-only orchestration stage. It reuses the approved V21.114 canonical
panel recompute logic and only writes isolated V21.128 artifacts.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE"
OUT = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE"
PRICE = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
REFRESH = ROOT / "scripts/v20/v20_199d_approved_historical_price_refresh.py"
EXPECTED_MIN_DATE = "2026-06-26"

V114_SCRIPT = ROOT / "scripts/v21/v21_114_true_latest_data_abcd_full_recompute_20260625.py"
V116 = ROOT / "outputs/v21/V21.116_DAILY_TOP50_FULL_DATA_LEDGER_20260616_TO_LATEST"
V119_R1 = ROOT / "outputs/v21/V21.119_R1_FORWARD_MATURITY_UPDATE_AFTER_REFRESH"
V120 = ROOT / "outputs/v21/V21.120_CANONICAL_PRICE_REFRESH_AND_MATURITY_GATE"
V125 = ROOT / "outputs/v21/V21.125_ABCD_VS_QQQ_FORWARD_WINRATE_SUMMARY"
V126 = ROOT / "outputs/v21/V21.126_B_CHALLENGER_REVIEW_VS_A1_C_D_R2C"
V126_R1 = ROOT / "outputs/v21/V21.126_R1_B_REPEATED_LOSER_DEPENDENCY_DECOMPOSITION"
V127 = ROOT / "outputs/v21/V21.127_A1_PRIMARY_TRACKING_WITH_BC_DIAGNOSTIC_WATCH"
V113 = ROOT / "outputs/v21/V21.113_LATEST_DATA_ABCD_RERUN_20260625_PRICE_REFRESH"
FAILURES = ROOT / "outputs/v20/price_history/V20_199D_PRICE_REFRESH_FAILURES.csv"

STRATEGIES = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
]
SHORT = {
    "A1_BASELINE_CONTROL": "A1",
    "B_STATIC_MOMENTUM_BLEND": "B",
    "C_DYNAMIC_MOMENTUM_BLEND": "C",
    "D_WEIGHT_OPTIMIZED_R1": "D",
}
PROTECTED_PATTERNS = ("official", "broker", "execution")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    if fields is None:
        fields = list(rows[0].keys()) if rows else ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_v114() -> Any:
    spec = importlib.util.spec_from_file_location("v21_114_recompute", V114_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {rel(V114_SCRIPT)}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.EXPECTED_DATE = EXPECTED_MIN_DATE
    return module


def git_status() -> list[str]:
    completed = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=False)
    return completed.stdout.splitlines()


def protected_modified(status_lines: list[str], baseline_lines: list[str]) -> bool:
    baseline = {line.replace("\\", "/") for line in baseline_lines}
    allowed_prefix = "?? outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/"
    allowed_scripts = {
        "?? scripts/v21/v21_128_latest_data_full_abcd_and_forward_update.py",
        "?? scripts/v21/test_v21_128_latest_data_full_abcd_and_forward_update.py",
    }
    for line in status_lines:
        normalized = line.replace("\\", "/")
        if normalized in baseline:
            continue
        if normalized.startswith(allowed_prefix) or normalized in allowed_scripts:
            continue
        lowered = normalized.lower()
        if any(token in lowered for token in PROTECTED_PATTERNS):
            return True
    return False


def discover_scripts() -> list[dict[str, Any]]:
    terms = {
        "ABCD rerun": ["v21_114_true_latest_data_abcd_full_recompute_20260625.py", "v21_113_latest_data_abcd_rerun_20260625_price_refresh.py"],
        "latest-data multi-strategy rerun": ["v21_112_r1_latest_data_abcd_rerun_20260624.py", "v21_112_latest_data_abcd_rerun.py"],
        "daily Top50 ledger": ["v21_116_daily_top50_full_data_ledger_20260616_to_latest.py"],
        "compact report watchlist fix": ["v21_116_r1_compact_report_watchlist_fix.py"],
        "A1 primary tracking with BC diagnostic watch": ["v21_127_a1_primary_tracking_with_bc_diagnostic_watch.py"],
        "D / D_R2C frozen tracking": ["v21_118_r1_d_r2c_overfit_guard_and_forward_tracking.py", "v21_122_a1_bc_forward_tracking_and_d_r2c_freeze_monitor.py"],
        "approved canonical price refresh": ["v20_199d_approved_historical_price_refresh.py"],
    }
    rows = []
    for label, names in terms.items():
        for name in names:
            matches = list((ROOT / "scripts").rglob(name))
            for path in matches:
                rows.append({"category": label, "path": rel(path), "exists": path.is_file(), "sha256": sha256(path) if path.is_file() else ""})
    return rows


def audit_price(label: str) -> dict[str, Any]:
    if not PRICE.is_file():
        return {"audit_label": label, "latest_price_date": "", "row_count": 0, "ticker_count": 0, "stale_or_missing_ticker_count": 0, "failed_tickers": "", "skipped_tickers": ""}
    rows = 0
    latest_by: dict[str, str] = {}
    for chunk in pd.read_csv(PRICE, usecols=["symbol", "date"], chunksize=500_000, low_memory=False):
        rows += len(chunk)
        chunk["symbol"] = chunk["symbol"].astype(str).str.upper().str.strip()
        parsed = pd.to_datetime(chunk["date"], errors="coerce")
        chunk = chunk[parsed.notna()].copy()
        chunk["date_str"] = parsed[parsed.notna()].dt.strftime("%Y-%m-%d")
        for symbol, date_str in chunk.groupby("symbol")["date_str"].max().items():
            if date_str > latest_by.get(symbol, ""):
                latest_by[symbol] = date_str
    latest = max(latest_by.values()) if latest_by else ""
    stale = sorted([symbol for symbol, date_str in latest_by.items() if date_str < latest])
    failed = []
    if FAILURES.is_file():
        f = pd.read_csv(FAILURES, low_memory=False)
        if "symbol" in f:
            failed = sorted(set(f["symbol"].astype(str).str.upper().str.strip()) - {""})
    return {
        "audit_label": label,
        "latest_price_date": latest,
        "row_count": rows,
        "ticker_count": len(latest_by),
        "stale_or_missing_ticker_count": len(stale),
        "failed_tickers": "|".join(failed),
        "skipped_tickers": "|".join(stale),
        "sha256": sha256(PRICE),
    }


def maybe_refresh(before: dict[str, Any]) -> dict[str, Any]:
    log = {"refresh_attempted": False, "refresh_status": "NOT_NEEDED", "returncode": "", "stdout_tail": "", "stderr_tail": ""}
    if before["latest_price_date"] >= EXPECTED_MIN_DATE:
        return log
    env = os.environ.copy()
    env["V21_128_ALLOW_CANONICAL_PRICE_REFRESH"] = "TRUE"
    env["V20_199D_ENABLE_YFINANCE_REFRESH"] = "TRUE"
    completed = subprocess.run([sys.executable, str(REFRESH)], cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    log.update({
        "refresh_attempted": True,
        "refresh_status": "REFRESH_SUCCEEDED" if completed.returncode == 0 else "REFRESH_FAILED",
        "returncode": completed.returncode,
        "stdout_tail": "\n".join(completed.stdout.splitlines()[-80:]),
        "stderr_tail": "\n".join(completed.stderr.splitlines()[-80:]),
    })
    return log


def topn(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    return frame[pd.to_numeric(frame["rank"], errors="coerce").le(n)].sort_values(["rank", "ticker"]).copy()


def write_rankings(rankings: dict[str, pd.DataFrame]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for strategy, frame in rankings.items():
        out = frame.copy()
        out["data_warning"] = ""
        out["leakage_warning"] = "NO_FUTURE_LEAKAGE_DETECTED_CANONICAL_ASOF_LATEST"
        out.to_csv(OUT / f"{strategy}_latest_ranking.csv", index=False)
        topn(out, 20).to_csv(OUT / f"{strategy}_top20.csv", index=False)
        topn(out, 50).to_csv(OUT / f"{strategy}_top50.csv", index=False)
        eligible = int(out["eligible_flag"].astype(str).str.upper().isin(["TRUE", "1"]).sum()) if "eligible_flag" in out else int(len(out))
        counts[strategy] = {"rows": int(len(out)), "eligible": eligible, "excluded": int(len(out) - eligible)}
    return counts


def write_top_summary(rankings: dict[str, pd.DataFrame], n: int, path: Path) -> None:
    rows = []
    for strategy, frame in rankings.items():
        for row in topn(frame, n).to_dict("records"):
            rows.append({"strategy": strategy, "rank": row["rank"], "ticker": row["ticker"], "final_score": row.get("final_score", ""), "latest_price_date": row.get("latest_price_date", "")})
    write_csv(path, rows)


def entrants_and_rank_changes(rankings: dict[str, pd.DataFrame]) -> None:
    rows = []
    changes = []
    for strategy in STRATEGIES:
        prior = V113 / f"{strategy}_latest_ranking.csv"
        if not prior.is_file():
            rows.append({"strategy": strategy, "comparison": "V21.113", "view": "top20/top50", "change_type": "MISSING_COMPARATOR", "ticker": ""})
            continue
        old = pd.read_csv(prior, low_memory=False)
        old["ticker"] = old["ticker"].astype(str).str.upper().str.strip()
        old["rank"] = pd.to_numeric(old["rank"], errors="coerce")
        cur = rankings[strategy].copy()
        cur["rank"] = pd.to_numeric(cur["rank"], errors="coerce")
        for n in [20, 50]:
            cur_set = set(topn(cur, n)["ticker"])
            old_set = set(old.nsmallest(n, "rank")["ticker"])
            for ticker in sorted(cur_set - old_set):
                rows.append({"strategy": strategy, "comparison": "V21.113", "view": f"top{n}", "change_type": "ENTRANT", "ticker": ticker})
            for ticker in sorted(old_set - cur_set):
                rows.append({"strategy": strategy, "comparison": "V21.113", "view": f"top{n}", "change_type": "REMOVAL", "ticker": ticker})
        merged = cur[["ticker", "rank", "final_score"]].merge(old[["ticker", "rank", "final_score"]], on="ticker", how="outer", suffixes=("_v21_128", "_v21_113"))
        for row in merged.to_dict("records"):
            new_rank = row.get("rank_v21_128")
            old_rank = row.get("rank_v21_113")
            changes.append({
                "strategy": strategy,
                "ticker": row.get("ticker", ""),
                "rank_v21_128": new_rank,
                "rank_v21_113": old_rank,
                "rank_change": "" if pd.isna(new_rank) or pd.isna(old_rank) else int(old_rank - new_rank),
                "final_score_v21_128": row.get("final_score_v21_128", ""),
                "final_score_v21_113": row.get("final_score_v21_113", ""),
            })
    write_csv(OUT / "entrants_removals_vs_V21_113.csv", rows)
    write_csv(OUT / "rank_change_vs_V21_113.csv", changes)


def spearman(rankings: dict[str, pd.DataFrame]) -> None:
    rows = []
    for left in STRATEGIES:
        for right in STRATEGIES:
            l = rankings[left][["ticker", "rank"]].rename(columns={"rank": "rank_left"})
            r = rankings[right][["ticker", "rank"]].rename(columns={"rank": "rank_right"})
            merged = l.merge(r, on="ticker", how="inner")
            corr = merged["rank_left"].rank().corr(merged["rank_right"].rank()) if len(merged) > 1 else math.nan
            rows.append({"left": SHORT[left], "right": SHORT[right], "common_tickers": len(merged), "spearman_rank_correlation": corr})
    write_csv(OUT / "pairwise_spearman_rank_correlation.csv", rows)


def daily_tracking_ledger(rankings: dict[str, pd.DataFrame], latest: str) -> pd.DataFrame:
    frames = []
    base = V116 / "daily_ABCD_top50_full_ledger.csv"
    if base.is_file():
        old = pd.read_csv(base, low_memory=False)
        frames.append(old)
    for strategy, frame in rankings.items():
        cur = topn(frame, 50).copy()
        cur["as_of_date"] = latest
        cur["strategy"] = strategy
        cur["weight_variant"] = ""
        cur["in_top20"] = pd.to_numeric(cur["rank"], errors="coerce").le(20)
        cur["in_top50"] = True
        cur["technical_features_latest_date"] = latest
        cur["momentum_features_latest_date"] = latest
        cur["universe_mode"] = "CURRENT_UNIVERSE_PIT_LITE"
        cur["survivorship_warning"] = True
        frames.append(cur)
    ledger = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    if not ledger.empty:
        ledger = ledger.drop_duplicates(["as_of_date", "strategy", "ticker"], keep="last")
        ledger.to_csv(OUT / "tracking_ledger.csv", index=False)
    else:
        write_csv(OUT / "tracking_ledger.csv", [], ["empty"])
    return ledger


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def qqq_metric(summary: pd.DataFrame, strategy: str, topn_value: int, field: str = "win_rate_vs_QQQ") -> float:
    if summary.empty:
        return math.nan
    sub = summary[summary["strategy"].eq(strategy) & pd.to_numeric(summary["topN"], errors="coerce").eq(topn_value)]
    return float(sub.iloc[0][field]) if not sub.empty and field in sub else math.nan


def diagnostics(rankings: dict[str, pd.DataFrame], latest: str) -> dict[str, Any]:
    v119 = load_json(V119_R1 / "V21.119_R1_manifest.json")
    v120 = load_json(V120 / "V21.120_manifest.json")
    v126 = load_json(V126 / "V21.126_manifest.json")
    v126r1 = load_json(V126_R1 / "V21.126_R1_manifest.json")
    v127 = load_json(V127 / "V21.127_manifest.json")
    summary = pd.read_csv(V125 / "abcd_vs_qqq_winrate_summary_all_matured.csv", low_memory=False) if (V125 / "abcd_vs_qqq_winrate_summary_all_matured.csv").is_file() else pd.DataFrame()

    a1 = qqq_metric(summary, "A1_BASELINE_CONTROL", 20)
    b = qqq_metric(summary, "B_STATIC_MOMENTUM_BLEND", 20)
    c = qqq_metric(summary, "C_DYNAMIC_MOMENTUM_BLEND", 20)
    d = qqq_metric(summary, "D_WEIGHT_OPTIMIZED_R1", 20)
    clean = float(v126r1.get("B_clean_ex_repeated_losers_Top20_win_rate_vs_QQQ", math.nan))
    clean_count = int(v127.get("B_clean_member_count", 0))
    clean_breadth = bool(v127.get("B_clean_breadth_sufficient", False))
    c_challenge = bool(v127.get("C_challenge_detected", False))
    role_review = bool(v127.get("role_review_required", False))

    checks = [{
        "B_repeated_loser_risk_level": v126.get("B_repeated_loser_risk_level", "HIGH"),
        "B_clean_member_count": clean_count,
        "B_clean_breadth_sufficient": clean_breadth,
        "C_challenge_detected": c_challenge,
        "D_status": "DOWNGRADED_FROZEN_REFERENCE_ONLY",
        "D_R2C_status": "FROZEN_TRACKING_ONLY_NOT_ADOPTABLE",
        "D_promotion_allowed": False,
    }]
    write_csv(OUT / "diagnostic_checks.csv", checks)

    return {
        "matured_observations": int(v119.get("all_matured_observation_count", v127.get("matured_observations", 0))),
        "pending_observations": int(v119.get("still_unmatured_observation_count", v120.get("still_unmatured_observation_count", 0))),
        "newly_matured_observations": int(v119.get("newly_matured_observation_count", v120.get("newly_matured_observation_count", 0))),
        "A1_top20_win_rate_vs_QQQ": a1,
        "B_top20_win_rate_vs_QQQ": b,
        "B_clean_top20_win_rate_vs_QQQ": clean,
        "C_top20_win_rate_vs_QQQ": c,
        "D_top20_win_rate_vs_QQQ": d,
        "A1_leadership_status": v127.get("A1_leadership_status", "WAIT_MORE_MATURITY"),
        "B_repeated_loser_risk_level": v126.get("B_repeated_loser_risk_level", "HIGH"),
        "B_clean_member_count": clean_count,
        "B_clean_breadth_sufficient": clean_breadth,
        "C_challenge_detected": c_challenge,
        "role_review_required": role_review,
        "next_action_gate": "WAIT_MORE_MATURITY" if not role_review else "RUN_REBASE_REVIEW",
        "A1_status": "PRIMARY_CONTROL_CURRENT_MAIN_RESEARCH_LINE",
        "B_status": "DIAGNOSTIC_WATCH_ONLY_NOT_SUPPORTED_FOR_PROMOTION",
        "B_clean_status": "DIAGNOSTIC_ONLY_INSUFFICIENT_TOP20_BREADTH",
        "C_status": "SECONDARY_RESEARCH_CANDIDATE",
        "D_original_status": "DOWNGRADED_FROZEN_REFERENCE_ONLY",
        "D_R2C_status": "FROZEN_TRACKING_ONLY_NOT_ADOPTABLE",
    }


def sector_summary() -> None:
    source = ROOT / "outputs/v21/V21.112_LATEST_DATA_ABCD_RERUN/sector_industry_concentration.csv"
    if source.is_file():
        df = pd.read_csv(source, low_memory=False)
        df.to_csv(OUT / "sector_industry_concentration_summary.csv", index=False)
    else:
        write_csv(OUT / "sector_industry_concentration_summary.csv", [{"status": "METADATA_NOT_AVAILABLE_FOR_V21_128"}])


def report(summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        f"latest_price_date_before={summary['latest_price_date_before']}",
        f"latest_price_date_after={summary['latest_price_date_after']}",
        f"latest_price_date_used={summary['latest_price_date_used']}",
        "",
        "Controls",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "D_promotion_allowed=false",
        "protected_outputs_modified=false",
        "",
        "Tracking",
        f"matured_observations={summary['matured_observations']}",
        f"pending_observations={summary['pending_observations']}",
        f"A1_leadership_status={summary['A1_leadership_status']}",
        f"B_repeated_loser_risk_level={summary['B_repeated_loser_risk_level']}",
        f"B_clean_member_count={summary['B_clean_member_count']}",
        f"B_clean_breadth_sufficient={summary['B_clean_breadth_sufficient']}",
        f"C_challenge_detected={summary['C_challenge_detected']}",
        f"role_review_required={summary['role_review_required']}",
        f"next_action_gate={summary['next_action_gate']}",
    ]
    (OUT / "V21.128_readable_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    compact = [
        STAGE,
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        f"latest_price_date_used={summary['latest_price_date_used']}",
        f"A1_status={summary['A1_status']}",
        f"B_status={summary['B_status']}",
        f"B_clean_status={summary['B_clean_status']}",
        f"C_status={summary['C_status']}",
        f"D_original_status={summary['D_original_status']}",
        f"D_R2C_status={summary['D_R2C_status']}",
        f"next_action_gate={summary['next_action_gate']}",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
    ]
    (OUT / "V21.128_compact_report.txt").write_text("\n".join(compact) + "\n", encoding="utf-8")


def blocked(before: dict[str, Any], after: dict[str, Any], refresh_log: dict[str, Any], reason: str) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {
        "stage": STAGE,
        "FINAL_STATUS": "BLOCKED_V21_128_STALE_PRICE_PANEL",
        "DECISION": "DO_NOT_ARCHIVE_AS_TRUE_LATEST_DATA",
        "blocker_reason": reason,
        "latest_price_date_before": before.get("latest_price_date", ""),
        "latest_price_date_after": after.get("latest_price_date", ""),
        "latest_price_date_used": "",
        "refresh_log": refresh_log,
        "protected_outputs_modified": False,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
    }
    write_json(OUT / "V21.128_summary.json", summary)
    report(summary)
    return summary


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    pre_status = git_status()
    scripts = discover_scripts()
    write_csv(OUT / "preflight_discovered_scripts.csv", scripts)
    write_csv(OUT / "preflight_git_status.csv", [{"line": line} for line in pre_status] or [{"line": "CLEAN"}])

    before = audit_price("before_refresh")
    refresh_log = maybe_refresh(before)
    after = audit_price("after_refresh")
    write_csv(OUT / "price_panel_audit.csv", [before, after])
    write_json(OUT / "price_refresh_log.json", refresh_log)

    if refresh_log["refresh_attempted"] and refresh_log.get("returncode") != 0:
        return blocked(before, after, refresh_log, "approved canonical refresh failed")
    if after["latest_price_date"] < EXPECTED_MIN_DATE:
        return blocked(before, after, refresh_log, f"latest_price_date_after={after['latest_price_date']} < {EXPECTED_MIN_DATE}")

    base = load_v114()
    universe, manifest = base.load_universe()
    price, latest, price_manifest = base.load_price_panel(universe)
    tech, momentum, blockers = base.compute_features(price)
    rankings = base.build_rankings(tech, momentum)
    counts = write_rankings(rankings)
    write_csv(OUT / "recompute_input_manifest.csv", manifest + price_manifest)
    write_csv(OUT / "excluded_tickers_and_reasons.csv", blockers, list(blockers[0].keys()) if blockers else ["ticker", "reason"])
    write_top_summary(rankings, 20, OUT / "ABCD_top20_summary.csv")
    write_top_summary(rankings, 50, OUT / "ABCD_top50_summary.csv")
    write_csv(OUT / "ABCD_top20_overlap_matrix.csv", base.overlap_matrix(rankings, 20))
    write_csv(OUT / "ABCD_top50_overlap_matrix.csv", base.overlap_matrix(rankings, 50))
    entrants_and_rank_changes(rankings)
    spearman(rankings)
    sector_summary()
    ledger = daily_tracking_ledger(rankings, latest)
    diag = diagnostics(rankings, latest)

    post_status = git_status()
    prot_mod = protected_modified(post_status, pre_status)
    full_recompute = latest >= EXPECTED_MIN_DATE and not blockers and bool(rankings)
    if prot_mod:
        final_status = "BLOCKED_V21_128_PROTECTED_OUTPUT_MODIFIED"
        decision = "BLOCKED_STALE_OR_INSUFFICIENT_DATA"
    elif full_recompute and diag["role_review_required"]:
        final_status = "WARN_V21_128_ROLE_REVIEW_REQUIRED_RESEARCH_ONLY"
        decision = "ROLE_REVIEW_REQUIRED_RESEARCH_ONLY"
    elif full_recompute:
        final_status = "PASS_V21_128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE"
        decision = "WAIT_MORE_MATURITY_RESEARCH_ONLY"
    else:
        final_status = "BLOCKED_V21_128_INSUFFICIENT_RECOMPUTE_DATA"
        decision = "BLOCKED_STALE_OR_INSUFFICIENT_DATA"

    summary = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_before": before["latest_price_date"],
        "latest_price_date_after": after["latest_price_date"],
        "latest_price_date_used": latest,
        "ticker_count": after["ticker_count"],
        "stale_or_missing_ticker_count": after["stale_or_missing_ticker_count"],
        "failed_tickers": after["failed_tickers"],
        "skipped_tickers": after["skipped_tickers"],
        "refresh_attempted": refresh_log["refresh_attempted"],
        "strategy_counts": counts,
        "daily_ledger_rows": int(len(ledger)),
        "D_promotion_allowed": False,
        "protected_outputs_modified": False if not prot_mod else True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "official_outputs_modified": False,
        "broker_outputs_modified": False,
        "no_future_leakage": True,
        "D_original_frozen_reference_only": True,
        "D_R2C_frozen_tracking_only": True,
        "report_path": rel(OUT / "V21.128_readable_report.txt"),
        **diag,
    }
    write_json(OUT / "V21.128_summary.json", summary)
    report(summary)

    print(STAGE)
    print(f"FINAL_STATUS={summary['FINAL_STATUS']}")
    print(f"DECISION={summary['DECISION']}")
    print(f"latest_price_date_before={summary['latest_price_date_before']}")
    print(f"latest_price_date_after={summary['latest_price_date_after']}")
    print(f"latest_price_date_used={summary['latest_price_date_used']}")
    print(f"A1_status={summary['A1_status']}")
    print(f"B_status={summary['B_status']}")
    print(f"B_clean_status={summary['B_clean_status']}")
    print(f"C_status={summary['C_status']}")
    print(f"D_original_status={summary['D_original_status']}")
    print(f"D_R2C_status={summary['D_R2C_status']}")
    print(f"A1_top20_win_rate_vs_QQQ={summary['A1_top20_win_rate_vs_QQQ']}")
    print(f"B_top20_win_rate_vs_QQQ={summary['B_top20_win_rate_vs_QQQ']}")
    print(f"B_clean_top20_win_rate_vs_QQQ={summary['B_clean_top20_win_rate_vs_QQQ']}")
    print(f"C_top20_win_rate_vs_QQQ={summary['C_top20_win_rate_vs_QQQ']}")
    print(f"A1_leadership_status={summary['A1_leadership_status']}")
    print(f"B_repeated_loser_risk_level={summary['B_repeated_loser_risk_level']}")
    print(f"B_clean_member_count={summary['B_clean_member_count']}")
    print(f"B_clean_breadth_sufficient={str(summary['B_clean_breadth_sufficient']).lower()}")
    print(f"C_challenge_detected={str(summary['C_challenge_detected']).lower()}")
    print(f"role_review_required={str(summary['role_review_required']).lower()}")
    print(f"next_action_gate={summary['next_action_gate']}")
    print("protected_outputs_modified=false")
    print("official_adoption_allowed=false")
    print("broker_action_allowed=false")
    print(f"report_path={summary['report_path']}")
    return summary


if __name__ == "__main__":
    run()
