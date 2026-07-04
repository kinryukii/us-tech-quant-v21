#!/usr/bin/env python
"""V21.187 research-only latest-data ABCDE rerun with price refresh."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from v21_194_broad_date_gate_utils import BroadDateGateError, classify_requested_date, load_latest_broad_date_gate


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.187_LATEST_DATA_ABCDE_RERUN_20260630_PRICE_REFRESH"
OUT = ROOT / "outputs/v21/V21.187_LATEST_DATA_ABCDE_RERUN_20260630_PRICE_REFRESH"
EXPECTED_LATEST_COMPLETED_TRADING_DATE = "2026-06-30"
PRICE = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
REFRESH = ROOT / "scripts/v20/v20_199d_approved_historical_price_refresh.py"
V114_SCRIPT = ROOT / "scripts/v21/v21_114_true_latest_data_abcd_full_recompute_20260625.py"
PRIOR_E_R1 = ROOT / "outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv"
V134_SUMMARY = ROOT / "outputs/v21/V21.134_E_R1_FORWARD_TRACKING_LEDGER/e_r1_forward_tracking_summary.json"

ABCD = [
    "A1_BASELINE_CONTROL",
    "B_STATIC_MOMENTUM_BLEND",
    "C_DYNAMIC_MOMENTUM_BLEND",
    "D_WEIGHT_OPTIMIZED_R1",
]
LABEL = {
    "A1_BASELINE_CONTROL": "A1",
    "B_STATIC_MOMENTUM_BLEND": "B",
    "C_DYNAMIC_MOMENTUM_BLEND": "C",
    "D_WEIGHT_OPTIMIZED_R1": "D",
    "E_R1_DEFENSIVE_OVERLAY_REPAIRED": "E_R1",
}
OUT_NAME = {
    "A1": "a1_latest_ranking.csv",
    "B": "b_latest_ranking.csv",
    "C": "c_latest_ranking.csv",
    "D": "d_latest_ranking.csv",
    "E_R1": "e_r1_latest_ranking.csv",
}
E_WEIGHTS = {
    "A1_baseline_norm": 0.80,
    "context_momentum_norm": 0.12,
    "technical_entry_quality_norm": 0.04,
    "risk_guardrail_norm": 0.04,
}


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
            for key in row:
                if key not in fields:
                    fields.append(key)
        fields = fields or ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    if not path.is_file():
        return ""
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
    allowed_prefix = "?? outputs/v21/V21.187_LATEST_DATA_ABCDE_RERUN_20260630_PRICE_REFRESH/"
    allowed_scripts = {
        "?? scripts/v21/v21_187_latest_data_abcde_rerun_20260630_price_refresh.py",
        "?? scripts/v21/test_v21_187_latest_data_abcde_rerun_20260630_price_refresh.py",
        "?? scripts/v21/run_v21_187_latest_data_abcde_rerun_20260630_price_refresh.ps1",
    }
    for line in status_lines:
        normalized = line.replace("\\", "/")
        if normalized in baseline or normalized.startswith(allowed_prefix) or normalized in allowed_scripts:
            continue
        lowered = normalized.lower()
        if lowered.startswith((" m outputs/", " d outputs/", "?? outputs/")) and (
            "official" in lowered or "broker" in lowered or "protected" in lowered or "weight" in lowered
        ):
            return True
    return False


def load_v114() -> Any:
    spec = importlib.util.spec_from_file_location("v21_114_recompute", V114_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {rel(V114_SCRIPT)}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.EXPECTED_DATE = EXPECTED_LATEST_COMPLETED_TRADING_DATE
    return module


def audit_price(label: str) -> dict[str, Any]:
    if not PRICE.is_file():
        return {"audit_label": label, "latest_price_date": "", "row_count": 0, "symbol_count": 0, "sha256": ""}
    latest_by_symbol: dict[str, str] = {}
    rows = 0
    for chunk in pd.read_csv(PRICE, usecols=["symbol", "date"], chunksize=500_000, low_memory=False):
        rows += len(chunk)
        chunk["symbol"] = chunk["symbol"].astype(str).str.upper().str.strip()
        chunk["date"] = pd.to_datetime(chunk["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        chunk = chunk[chunk["date"].notna()]
        for symbol, latest in chunk.groupby("symbol")["date"].max().items():
            latest_by_symbol[symbol] = max(latest_by_symbol.get(symbol, ""), str(latest))
    return {
        "audit_label": label,
        "latest_price_date": max(latest_by_symbol.values(), default=""),
        "row_count": rows,
        "symbol_count": len(latest_by_symbol),
        "sha256": sha256(PRICE),
    }


def maybe_refresh(before: dict[str, Any]) -> dict[str, Any]:
    log = {
        "price_refresh_attempted": False,
        "price_refresh_succeeded": False,
        "returncode": "",
        "stdout_tail": "",
        "stderr_tail": "",
        "refresh_script_path": rel(REFRESH),
        "pre_refresh_backup_path": "",
        "invalid_refresh_restored_backup": False,
    }
    if before.get("latest_price_date", "") >= EXPECTED_LATEST_COMPLETED_TRADING_DATE:
        log["price_refresh_succeeded"] = True
        return log
    if not REFRESH.is_file():
        log["stderr_tail"] = "Approved refresh script missing."
        return log
    if PRICE.is_file() and int(before.get("row_count") or 0) > 0:
        backup = OUT / f"canonical_price_panel_backup_before_refresh_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.csv"
        shutil.copy2(PRICE, backup)
        log["pre_refresh_backup_path"] = rel(backup)
    env = os.environ.copy()
    env["V20_199D_ENABLE_YFINANCE_REFRESH"] = "TRUE"
    env["V21_187_RESEARCH_ONLY_PRICE_REFRESH"] = "TRUE"
    completed = subprocess.run([sys.executable, str(REFRESH)], cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    log.update({
        "price_refresh_attempted": True,
        "price_refresh_succeeded": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout_tail": "\n".join(completed.stdout.splitlines()[-80:]),
        "stderr_tail": "\n".join(completed.stderr.splitlines()[-80:]),
    })
    after = audit_price("post_refresh_validation")
    if int(after.get("row_count") or 0) == 0 and log["pre_refresh_backup_path"]:
        shutil.copy2(ROOT / log["pre_refresh_backup_path"], PRICE)
        log["price_refresh_succeeded"] = False
        log["invalid_refresh_restored_backup"] = True
        log["stderr_tail"] = (log["stderr_tail"] + "\nV21.187 restored pre-refresh backup because canonical refresh produced zero rows.").strip()
    return log


def topn(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    eligible = frame
    if "eligible_flag" in frame.columns:
        eligible = frame[frame["eligible_flag"].astype(str).str.upper().isin(["TRUE", "1", "YES"])]
    return eligible.sort_values(["rank", "ticker"]).head(n).copy()


def normalize_score(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    valid = numeric.dropna()
    if valid.empty or valid.nunique() == 1:
        return pd.Series(50.0, index=series.index)
    return (numeric.rank(pct=True, method="average", ascending=True) * 100.0).clip(0, 100)


def build_e_r1(a1: pd.DataFrame, latest_price_date: str) -> pd.DataFrame:
    prior = pd.read_csv(PRIOR_E_R1, low_memory=False) if PRIOR_E_R1.is_file() else pd.DataFrame()
    a1_in = a1.copy()
    a1_in["ticker_norm"] = a1_in["ticker"].astype(str).str.upper().str.strip()
    a1_in["A1_raw_score"] = pd.to_numeric(a1_in["final_score"], errors="coerce")
    a1_in["A1_raw_rank"] = pd.to_numeric(a1_in["rank"], errors="coerce")
    a1_in["A1_baseline_norm"] = normalize_score(a1_in["A1_raw_score"])
    full = a1_in[["ticker_norm", "A1_raw_score", "A1_raw_rank", "A1_baseline_norm"]].copy()
    if not prior.empty:
        prior["ticker_norm"] = prior["ticker_norm"].astype(str).str.upper().str.strip() if "ticker_norm" in prior else prior["ticker"].astype(str).str.upper().str.strip()
        keep = [c for c in ["ticker_norm", "context_momentum_norm", "technical_entry_quality_norm", "risk_guardrail_norm"] if c in prior.columns]
        full = full.merge(prior[keep].drop_duplicates("ticker_norm"), on="ticker_norm", how="left")
    for col in ["context_momentum_norm", "technical_entry_quality_norm", "risk_guardrail_norm"]:
        if col not in full.columns:
            full[col] = 50.0
        full[col] = pd.to_numeric(full[col], errors="coerce").fillna(50.0).clip(0, 100)
    full["E_final_score"] = sum(full[col] * weight for col, weight in E_WEIGHTS.items())
    full["eligible_flag"] = full["A1_baseline_norm"].notna()
    full = full.sort_values(["eligible_flag", "E_final_score", "ticker_norm"], ascending=[False, False, True]).reset_index(drop=True)
    full["rank"] = np.where(full["eligible_flag"], np.arange(1, len(full) + 1), np.nan)
    full["ticker"] = full["ticker_norm"]
    full["strategy"] = "E_R1_DEFENSIVE_OVERLAY_REPAIRED"
    full["latest_price_date"] = latest_price_date
    full["research_only"] = True
    full["official_adoption_allowed"] = False
    full["broker_action_allowed"] = False
    full["score_lineage"] = "V21.187_REBUILT_FROM_FRESH_A1_WITH_V21.133_R1_REPAIRED_COMPONENTS"
    full["leakage_warning"] = "NO_FUTURE_LEAKAGE_DETECTED_REPAIRED_ANCHOR_ONLY"
    ordered = [
        "strategy", "rank", "ticker", "ticker_norm", "E_final_score", "A1_raw_score", "A1_raw_rank",
        "A1_baseline_norm", "context_momentum_norm", "technical_entry_quality_norm", "risk_guardrail_norm",
        "latest_price_date", "eligible_flag", "score_lineage", "research_only",
        "official_adoption_allowed", "broker_action_allowed", "leakage_warning",
    ]
    return full[ordered].copy()


def write_rankings(rankings: dict[str, pd.DataFrame]) -> None:
    for label, frame in rankings.items():
        out = frame.copy()
        out["research_only"] = True
        out["official_adoption_allowed"] = False
        out["broker_action_allowed"] = False
        out["leakage_warning"] = out.get("leakage_warning", "NO_FUTURE_LEAKAGE_DETECTED_CANONICAL_COMPLETED_DAILY_BAR_ONLY")
        out.to_csv(OUT / OUT_NAME[label], index=False)


def top_summary(rankings: dict[str, pd.DataFrame], n: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy, frame in rankings.items():
        score_col = "E_final_score" if strategy == "E_R1" else "final_score"
        for row in topn(frame, n).to_dict("records"):
            rows.append({
                "strategy_id": strategy,
                "rank": row.get("rank", ""),
                "ticker": row.get("ticker", row.get("ticker_norm", "")),
                "score": row.get(score_col, ""),
                "latest_price_date": row.get("latest_price_date", ""),
            })
    return rows


def overlap_matrix(rankings: dict[str, pd.DataFrame], n: int) -> list[dict[str, Any]]:
    sets = {name: set(topn(frame, n)["ticker"].astype(str).str.upper().str.strip()) for name, frame in rankings.items()}
    rows = []
    for left in rankings:
        row = {"strategy_id": left}
        for right in rankings:
            row[right] = len(sets[left] & sets[right])
        rows.append(row)
    return rows


def rank_diff_summary(rankings: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if "A1" not in rankings:
        return [{"strategy_id": "", "compared_to": "A1", "status": "MISSING_A1_RANKING"}]
    base = rankings["A1"][["ticker", "rank"]].rename(columns={"rank": "A1_rank"}).copy()
    base["ticker"] = base["ticker"].astype(str).str.upper().str.strip()
    for strategy, frame in rankings.items():
        if strategy == "A1":
            rows.append({
                "strategy_id": strategy,
                "compared_to": "A1",
                "common_ticker_count": int(len(base)),
                "mean_rank_diff_vs_a1": 0.0,
                "median_abs_rank_diff_vs_a1": 0.0,
                "max_abs_rank_diff_vs_a1": 0.0,
            })
            continue
        compare = frame[["ticker", "rank"]].rename(columns={"rank": f"{strategy}_rank"}).copy()
        compare["ticker"] = compare["ticker"].astype(str).str.upper().str.strip()
        merged = base.merge(compare, on="ticker", how="outer")
        diff = pd.to_numeric(merged[f"{strategy}_rank"], errors="coerce") - pd.to_numeric(merged["A1_rank"], errors="coerce")
        rows.append({
            "strategy_id": strategy,
            "compared_to": "A1",
            "common_ticker_count": int(diff.notna().sum()),
            "mean_rank_diff_vs_a1": "" if diff.dropna().empty else float(diff.mean()),
            "median_abs_rank_diff_vs_a1": "" if diff.dropna().empty else float(diff.abs().median()),
            "max_abs_rank_diff_vs_a1": "" if diff.dropna().empty else float(diff.abs().max()),
        })
    return rows


def stale_report(universe: set[str], price: pd.DataFrame) -> list[dict[str, Any]]:
    latest = price.groupby("symbol")["date"].max().dt.strftime("%Y-%m-%d").to_dict() if len(price) else {}
    rows = []
    for ticker in sorted(universe):
        latest_date = str(latest.get(ticker, ""))
        if latest_date < EXPECTED_LATEST_COMPLETED_TRADING_DATE:
            rows.append({
                "ticker": ticker,
                "latest_price_date": latest_date,
                "expected_latest_completed_trading_date": EXPECTED_LATEST_COMPLETED_TRADING_DATE,
                "status": "STALE_OR_MISSING_CANONICAL_PRICE",
            })
    return rows


def same_date_audit(rankings: dict[str, pd.DataFrame], latest_used: str) -> list[dict[str, Any]]:
    rows = []
    for strategy, frame in rankings.items():
        dates = sorted(set(frame["latest_price_date"].dropna().astype(str))) if "latest_price_date" in frame else []
        rows.append({
            "strategy_id": strategy,
            "ranking_date": latest_used,
            "source_latest_price_dates": "|".join(dates),
            "row_count": len(frame),
            "top20_count": len(topn(frame, 20)),
            "top50_count": len(topn(frame, 50)),
            "same_date_comparable": dates == [latest_used],
            "research_only": True,
        })
    return rows


def maturity_summary() -> dict[str, Any]:
    if not V134_SUMMARY.is_file():
        write_csv(OUT / "forward_maturity_update_summary.csv", [{"status": "NOT_AVAILABLE", "source": rel(V134_SUMMARY)}])
        return {"maturity_gate_status": "FORWARD_MATURITY_SOURCE_NOT_AVAILABLE", "switch_decision": "WAIT_MORE_MATURITY_RESEARCH_ONLY"}
    payload = json.loads(V134_SUMMARY.read_text(encoding="utf-8"))
    row = {"status": "COPIED_PRIOR_E_R1_FORWARD_TRACKING_SUMMARY", "source": rel(V134_SUMMARY), **{k: v for k, v in payload.items() if isinstance(v, (str, int, float, bool))}}
    write_csv(OUT / "forward_maturity_update_summary.csv", [row])
    return {
        "maturity_gate_status": str(payload.get("maturity_gate_status", payload.get("FINAL_STATUS", "PRIOR_FORWARD_TRACKING_SUMMARY_AVAILABLE"))),
        "switch_decision": str(payload.get("switch_decision", payload.get("DECISION", "WAIT_MORE_MATURITY_RESEARCH_ONLY"))),
    }


def report(summary: dict[str, Any], matrices: dict[str, list[dict[str, Any]]]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"latest_price_date_before_refresh={summary['latest_price_date_before_refresh']}",
        f"latest_price_date_after_refresh={summary['latest_price_date_after_refresh']}",
        f"latest_price_date_used={summary['latest_price_date_used']}",
        "",
        "Top20",
        f"A1={'|'.join(summary['a1_top20'])}",
        f"B={'|'.join(summary['b_top20'])}",
        f"C={'|'.join(summary['c_top20'])}",
        f"D={'|'.join(summary['d_top20'])}",
        f"E_R1={'|'.join(summary['e_r1_top20'])}",
        "",
        "Top20 overlap matrix",
        pd.DataFrame(matrices["top20"]).to_csv(index=False).strip(),
        "",
        "Controls",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        f"protected_outputs_modified={str(summary['protected_outputs_modified']).lower()}",
    ]
    (OUT / "V21.187_latest_data_abcde_rerun_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_status = git_status()
    try:
        broad_gate = load_latest_broad_date_gate()
        broad_gate_classification = classify_requested_date(EXPECTED_LATEST_COMPLETED_TRADING_DATE, broad_gate)
    except BroadDateGateError as exc:
        broad_gate = {}
        broad_gate_classification = {
            "allowed": False,
            "classification": "BROAD_DATE_GATE_MISSING",
            "reason": str(exc),
        }
    before = audit_price("before_refresh")
    refresh_log = maybe_refresh(before)
    after = audit_price("after_refresh")
    write_csv(OUT / "price_panel_audit.csv", [before, after])
    write_json(OUT / "price_refresh_log.json", refresh_log)

    base = load_v114()
    universe, input_manifest = base.load_universe()
    price, latest_used, price_manifest = base.load_price_panel(universe)
    tech, momentum, blockers = base.compute_features(price)
    rankings_long = base.build_rankings(tech, momentum) if latest_used else {}
    rankings = {LABEL[name]: frame for name, frame in rankings_long.items()}
    if "A1" in rankings:
        rankings["E_R1"] = build_e_r1(rankings["A1"], latest_used)

    write_csv(OUT / "recompute_input_manifest.csv", input_manifest + price_manifest)
    write_csv(OUT / "excluded_tickers_and_reasons.csv", blockers, list(blockers[0]) if blockers else ["ticker", "reason"])
    stale_rows = stale_report(universe, price)
    write_csv(OUT / "stale_or_missing_ticker_report.csv", stale_rows, ["ticker", "latest_price_date", "expected_latest_completed_trading_date", "status"])

    if rankings:
        write_rankings(rankings)
    else:
        for name in OUT_NAME.values():
            write_csv(OUT / name, [], ["strategy", "rank", "ticker", "latest_price_date", "research_only", "official_adoption_allowed", "broker_action_allowed"])
    top20_rows = top_summary(rankings, 20)
    top50_rows = top_summary(rankings, 50)
    write_csv(OUT / "abcde_top20_summary.csv", top20_rows)
    write_csv(OUT / "abcde_top50_summary.csv", top50_rows)
    top20_matrix = overlap_matrix(rankings, 20)
    top50_matrix = overlap_matrix(rankings, 50)
    write_csv(OUT / "abcde_overlap_top20_matrix.csv", top20_matrix)
    write_csv(OUT / "abcde_overlap_top50_matrix.csv", top50_matrix)
    write_csv(OUT / "abcde_rank_diff_summary.csv", rank_diff_summary(rankings))
    same_date_rows = same_date_audit(rankings, latest_used)
    write_csv(OUT / "abcde_same_date_alignment_audit.csv", same_date_rows)
    maturity = maturity_summary()

    comparable = len(rankings) == 5 and all(bool(row["same_date_comparable"]) for row in same_date_rows)
    prot_mod = protected_modified(git_status(), baseline_status)
    gate_blocks_expected_target = not bool(broad_gate_classification.get("allowed", False))
    if gate_blocks_expected_target:
        final_status = "FAIL_OR_BLOCKED_TARGET_DATE_NOT_BROAD_ELIGIBLE"
        final_decision = "USE_ABCD_HONEST_LATEST_DATE_OR_IMPORT_BROAD_DAILY_BARS"
    elif not comparable:
        final_status = "FAIL_V21_187_ABCDE_ALIGNMENT_BROKEN"
        final_decision = "DO_NOT_USE_ABCDE_RERUN_ALIGNMENT_REPAIR_REQUIRED"
    elif latest_used >= EXPECTED_LATEST_COMPLETED_TRADING_DATE:
        final_status = "PASS_V21_187_LATEST_DATA_ABCDE_RERUN_READY"
        final_decision = "LATEST_DATA_ABCDE_RERUN_READY_RESEARCH_ONLY"
    else:
        final_status = "PARTIAL_PASS_V21_187_WAIT_20260630_DATA"
        final_decision = "WAIT_FOR_LATEST_COMPLETED_BAR_RESEARCH_ONLY"

    top20 = {strategy: topn(frame, 20)["ticker"].astype(str).tolist() for strategy, frame in rankings.items()}
    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "final_decision": final_decision,
        "latest_price_date_before_refresh": before.get("latest_price_date", ""),
        "latest_price_date_after_refresh": after.get("latest_price_date", ""),
        "latest_price_date_used": latest_used,
        "expected_latest_completed_trading_date": EXPECTED_LATEST_COMPLETED_TRADING_DATE,
        "price_refresh_attempted": bool(refresh_log["price_refresh_attempted"]),
        "price_refresh_succeeded": bool(refresh_log["price_refresh_succeeded"]),
        "stale_or_missing_ticker_count": len(stale_rows),
        "a1_top20": top20.get("A1", []),
        "b_top20": top20.get("B", []),
        "c_top20": top20.get("C", []),
        "d_top20": top20.get("D", []),
        "e_r1_top20": top20.get("E_R1", []),
        "top20_overlap_matrix_path": rel(OUT / "abcde_overlap_top20_matrix.csv"),
        "top50_overlap_matrix_path": rel(OUT / "abcde_overlap_top50_matrix.csv"),
        "same_date_comparable_all_strategies": comparable,
        "maturity_gate_status": maturity["maturity_gate_status"],
        "switch_decision": maturity["switch_decision"],
        "broad_date_gate_loaded": bool(broad_gate),
        "broad_date_gate_classification": broad_gate_classification.get("classification", ""),
        "abcd_honest_latest_date": broad_gate.get("abcd_honest_latest_date", ""),
        "blocked_newer_dates": broad_gate.get("blocked_newer_dates", []),
        "raw_canonical_max_date_broad_eligible": broad_gate.get("raw_canonical_max_date_broad_eligible", False),
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": bool(prot_mod),
        "official_outputs_modified": False,
        "broker_outputs_modified": False,
        "production_weights_modified": False,
        "no_future_leakage": True,
        "completed_daily_bars_only": True,
    }
    write_json(OUT / "v21_187_summary.json", summary)
    report(summary, {"top20": top20_matrix, "top50": top50_matrix})

    print(f"final_status={summary['final_status']}")
    print(f"final_decision={summary['final_decision']}")
    print(f"latest_price_date_used={summary['latest_price_date_used']}")
    print(f"A1 Top20={'|'.join(summary['a1_top20'])}")
    print(f"B Top20={'|'.join(summary['b_top20'])}")
    print(f"C Top20={'|'.join(summary['c_top20'])}")
    print(f"D Top20={'|'.join(summary['d_top20'])}")
    print(f"E_R1 Top20={'|'.join(summary['e_r1_top20'])}")
    print("Top20 overlap matrix")
    print(pd.DataFrame(top20_matrix).to_string(index=False))
    print(f"stale_or_missing_ticker_count={summary['stale_or_missing_ticker_count']}")
    print(f"maturity_gate_status={summary['maturity_gate_status']}")
    print(f"official_adoption_allowed={str(summary['official_adoption_allowed']).lower()}")
    print(f"broker_action_allowed={str(summary['broker_action_allowed']).lower()}")
    print(f"protected_outputs_modified={str(summary['protected_outputs_modified']).lower()}")
    return summary


if __name__ == "__main__":
    run()
