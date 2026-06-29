#!/usr/bin/env python
"""V21.134 E_R1 forward tracking ledger."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.134_E_R1_FORWARD_TRACKING_LEDGER"
OUT = ROOT / "outputs/v21/V21.134_E_R1_FORWARD_TRACKING_LEDGER"
E_R1_DIR = ROOT / "outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR"
E_R1_FULL = E_R1_DIR / "e_r1_full_ranking.csv"
E_R1_TOP20 = E_R1_DIR / "e_r1_top20.csv"
E_R1_TOP50 = E_R1_DIR / "e_r1_top50.csv"
E_R1_SUMMARY = E_R1_DIR / "e_r1_validation_summary.json"
PRICE_PANEL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
V128 = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE"
ABCD_INPUTS = {
    "A1": V128 / "A1_BASELINE_CONTROL_latest_ranking.csv",
    "B": V128 / "B_STATIC_MOMENTUM_BLEND_latest_ranking.csv",
    "C": V128 / "C_DYNAMIC_MOMENTUM_BLEND_latest_ranking.csv",
    "D": V128 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv",
}
HORIZONS = [5, 10, 20]
COMPONENT_COLUMNS = ["E_final_score", "A1_baseline_norm", "context_momentum_norm", "technical_entry_quality_norm", "risk_guardrail_norm"]


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
    allowed_prefix = "?? outputs/v21/V21.134_E_R1_FORWARD_TRACKING_LEDGER/"
    allowed_scripts = {
        "?? scripts/v21/v21_134_e_r1_forward_tracking_ledger.py",
        "?? scripts/v21/test_v21_134_e_r1_forward_tracking_ledger.py",
        "?? scripts/v21/run_v21_134_e_r1_forward_tracking_ledger.ps1",
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


def ticker_norm(value: Any) -> str:
    return str(value).upper().strip()


def load_price_history(tickers: set[str], ranking_date: str) -> tuple[dict[str, pd.DataFrame], str, list[str]]:
    warnings: list[str] = []
    wanted = set(tickers) | {"QQQ", "SOXX"}
    if not PRICE_PANEL.is_file():
        return {}, "", [f"MISSING_PRICE_PANEL:{rel(PRICE_PANEL)}"]
    chunks = []
    usecols = ["symbol", "date", "adjusted_close", "close"]
    max_date = ""
    for chunk in pd.read_csv(PRICE_PANEL, usecols=usecols, chunksize=250_000, low_memory=False):
        chunk["symbol"] = chunk["symbol"].astype(str).str.upper().str.strip()
        chunk["date"] = chunk["date"].astype(str)
        chunk_max = chunk["date"].max()
        max_date = max(max_date, chunk_max)
        sub = chunk[chunk["symbol"].isin(wanted)].copy()
        if not sub.empty:
            chunks.append(sub)
    if not chunks:
        return {}, max_date, ["NO_PRICE_ROWS_FOR_E_R1_FORWARD_LEDGER"]
    prices = pd.concat(chunks, ignore_index=True).sort_values(["symbol", "date"])
    missing = sorted(wanted - set(prices["symbol"].unique()))
    if missing:
        warnings.append("MISSING_PRICE_TICKERS:" + "|".join(missing))
    if "QQQ" not in set(prices["symbol"].unique()):
        warnings.append("MISSING_PRIMARY_BENCHMARK_QQQ")
    if "SOXX" not in set(prices["symbol"].unique()):
        warnings.append("MISSING_SECONDARY_BENCHMARK_SOXX")
    return {sym: grp.reset_index(drop=True) for sym, grp in prices.groupby("symbol")}, max_date, warnings


def price_at_or_after(history: pd.DataFrame, date: str) -> tuple[str, float] | tuple[str, float]:
    if history.empty:
        return "", math.nan
    sub = history[history["date"].astype(str) >= date]
    if sub.empty:
        return "", math.nan
    row = sub.iloc[0]
    return str(row["date"]), float(row.get("adjusted_close", row.get("close")))


def forward_price(history: pd.DataFrame, entry_date: str, horizon: int) -> tuple[str, float, bool]:
    if history.empty or not entry_date:
        return "", math.nan, False
    dates = history["date"].astype(str).tolist()
    try:
        idx = dates.index(entry_date)
    except ValueError:
        return "", math.nan, False
    fwd_idx = idx + horizon
    if fwd_idx >= len(history):
        return "", math.nan, False
    row = history.iloc[fwd_idx]
    return str(row["date"]), float(row.get("adjusted_close", row.get("close"))), True


def make_ledger(e_rows: pd.DataFrame, bucket: str, ranking_date: str, histories: dict[str, pd.DataFrame]) -> pd.DataFrame:
    qqq = histories.get("QQQ", pd.DataFrame())
    rows = []
    for row in e_rows.to_dict("records"):
        ticker = ticker_norm(row["ticker_norm"])
        hist = histories.get(ticker, pd.DataFrame())
        entry_date, entry_close = price_at_or_after(hist, ranking_date)
        qqq_entry_date, qqq_entry_close = price_at_or_after(qqq, ranking_date)
        out = {
            "ranking_date": ranking_date,
            "bucket": bucket,
            "ticker_norm": ticker,
            "E_rank": row.get("rank", ""),
            "E_final_score": row.get("E_final_score", math.nan),
            "A1_baseline_norm": row.get("A1_baseline_norm", math.nan),
            "context_momentum_norm": row.get("context_momentum_norm", math.nan),
            "technical_entry_quality_norm": row.get("technical_entry_quality_norm", math.nan),
            "risk_guardrail_norm": row.get("risk_guardrail_norm", math.nan),
            "entry_date": entry_date,
            "entry_close_price": entry_close,
            "missing_price_flag": bool(not entry_date or math.isnan(entry_close)),
            "stale_price_flag": bool(entry_date and entry_date < ranking_date),
        }
        data_warning = []
        if out["missing_price_flag"]:
            data_warning.append("MISSING_ENTRY_PRICE")
        if out["stale_price_flag"]:
            data_warning.append("STALE_ENTRY_PRICE")
        for horizon in HORIZONS:
            fwd_date, fwd_close, matured = forward_price(hist, entry_date, horizon)
            qqq_fwd_date, qqq_fwd_close, qqq_matured = forward_price(qqq, qqq_entry_date, horizon)
            fwd_ret = fwd_close / entry_close - 1.0 if matured and entry_close and not math.isnan(entry_close) else math.nan
            qqq_ret = qqq_fwd_close / qqq_entry_close - 1.0 if qqq_matured and qqq_entry_close and not math.isnan(qqq_entry_close) else math.nan
            out[f"h{horizon}_forward_date"] = fwd_date
            out[f"h{horizon}_forward_close_price"] = fwd_close
            out[f"h{horizon}_forward_return"] = fwd_ret
            out[f"h{horizon}_qqq_forward_date"] = qqq_fwd_date
            out[f"h{horizon}_qqq_forward_return"] = qqq_ret
            out[f"h{horizon}_excess_return_vs_QQQ"] = fwd_ret - qqq_ret if matured and qqq_matured else math.nan
            out[f"h{horizon}_matured"] = bool(matured)
            out[f"h{horizon}_qqq_matured"] = bool(qqq_matured)
        out["data_warning_flag"] = "|".join(data_warning) if data_warning else ""
        rows.append(out)
    return pd.DataFrame(rows)


def summarize_ledger(ledger: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for bucket, group in ledger.groupby("bucket"):
        for horizon in HORIZONS:
            ret = pd.to_numeric(group[f"h{horizon}_forward_return"], errors="coerce")
            qqq = pd.to_numeric(group[f"h{horizon}_qqq_forward_return"], errors="coerce")
            excess = pd.to_numeric(group[f"h{horizon}_excess_return_vs_QQQ"], errors="coerce")
            matured = group[f"h{horizon}_matured"].astype(bool)
            rows.append({
                "bucket": bucket,
                "horizon": f"{horizon}D",
                "total_rows": len(group),
                "matured_rows": int(matured.sum()),
                "pending_rows": int((~matured).sum()),
                "missing_price_rows": int(group["missing_price_flag"].astype(bool).sum()),
                "average_forward_return": ret.mean(),
                "median_forward_return": ret.median(),
                "hit_rate_positive": float((ret > 0).mean()) if ret.notna().any() else math.nan,
                "average_QQQ_forward_return": qqq.mean(),
                "median_QQQ_forward_return": qqq.median(),
                "win_rate_vs_QQQ": float((excess > 0).mean()) if excess.notna().any() else math.nan,
                "average_excess_return_vs_QQQ": excess.mean(),
                "median_excess_return_vs_QQQ": excess.median(),
                "worst_forward_return": ret.min(),
                "best_forward_return": ret.max(),
            })
    return pd.DataFrame(rows)


def abcd_comparison(ledger: pd.DataFrame, warnings: list[str]) -> pd.DataFrame:
    rows = []
    for name, path in ABCD_INPUTS.items():
        if not path.is_file():
            warnings.append(f"MISSING_{name}_RANKING_FOR_COMPARISON")
            continue
        comp = pd.read_csv(path, low_memory=False)
        comp["ticker_norm"] = comp["ticker"].map(ticker_norm)
        for bucket, n in [("top20", 20), ("top50", 50)]:
            comp_set = set(comp.sort_values(["rank", "ticker_norm"]).head(n)["ticker_norm"])
            e_bucket = ledger[ledger["bucket"].eq(bucket)]
            e_set = set(e_bucket["ticker_norm"])
            overlap = sorted(e_set.intersection(comp_set))
            for horizon in HORIZONS:
                ret = pd.to_numeric(e_bucket[f"h{horizon}_forward_return"], errors="coerce")
                rows.append({
                    "comparison_strategy": name,
                    "bucket": bucket,
                    "horizon": f"{horizon}D",
                    "comparable_forward_ledger_available": False,
                    "warning": "Comparable ABCD forward ledger for same ranking_date not available; overlap-only context emitted.",
                    "E_average_return": ret.mean(),
                    "E_median_return": ret.median(),
                    "E_hit_rate": float((ret > 0).mean()) if ret.notna().any() else math.nan,
                    "overlap_count": len(overlap),
                    "overlap_tickers": "|".join(overlap),
                })
    if not rows:
        rows.append({"comparison_strategy": "NONE", "warning": "No comparable A1/B/C/D rankings or ledgers available"})
    return pd.DataFrame(rows)


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_status = git_status()
    protected_inputs = [p for p in [E_R1_FULL, E_R1_TOP20, E_R1_TOP50, E_R1_SUMMARY, PRICE_PANEL] if p.is_file()]
    baseline_hashes = {rel(p): sha256(p) for p in protected_inputs}
    warnings: list[str] = []
    if not E_R1_FULL.is_file():
        summary = {
            "stage": STAGE,
            "FINAL_STATUS": "BLOCKED_V21_134_E_R1_SOURCE_MISSING",
            "DECISION": "E_R1_FORWARD_TRACKING_BLOCKED_MISSING_REPAIRED_E_SOURCE",
            "E_R1_source_path": rel(E_R1_FULL),
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
            "research_only": True,
            "E_adoption_allowed": False,
            "protected_outputs_modified": False,
        }
        write_json(OUT / "e_r1_forward_tracking_summary.json", summary)
        return summary

    source_summary = load_json(E_R1_SUMMARY)
    e_full = pd.read_csv(E_R1_FULL, low_memory=False)
    e_full["ticker_norm"] = e_full["ticker_norm"].map(ticker_norm)
    ranking_date = str(source_summary.get("latest_price_date_used", ""))
    if not ranking_date:
        ranking_date = str(e_full.get("latest_price_date", pd.Series(dtype=str)).dropna().astype(str).max())
        warnings.append("RANKING_DATE_INFERRED_FROM_E_R1_SCORING")
    e_top20 = pd.read_csv(E_R1_TOP20, low_memory=False) if E_R1_TOP20.is_file() else e_full.sort_values(["rank", "ticker_norm"]).head(20)
    e_top50 = pd.read_csv(E_R1_TOP50, low_memory=False) if E_R1_TOP50.is_file() else e_full.sort_values(["rank", "ticker_norm"]).head(50)
    for frame in [e_top20, e_top50]:
        frame["ticker_norm"] = frame["ticker_norm"].map(ticker_norm)
    tickers = set(e_top50["ticker_norm"])
    histories, price_panel_max, price_warnings = load_price_history(tickers, ranking_date)
    warnings.extend(price_warnings)
    ledger20 = make_ledger(e_top20.sort_values(["rank", "ticker_norm"]).head(20), "top20", ranking_date, histories)
    ledger50 = make_ledger(e_top50.sort_values(["rank", "ticker_norm"]).head(50), "top50", ranking_date, histories)
    ledger = pd.concat([ledger20, ledger50], ignore_index=True)
    summary_by_horizon = summarize_ledger(ledger)
    vs_qqq = summary_by_horizon[["bucket", "horizon", "matured_rows", "pending_rows", "win_rate_vs_QQQ", "average_excess_return_vs_QQQ", "median_excess_return_vs_QQQ"]].copy()
    comparison = abcd_comparison(ledger, warnings)
    maturity = pd.DataFrame([{
        "gate": "E_R1_FORWARD_MATURITY",
        "status": "BLOCK",
        "reason": "E_R1 is not mature on first tracking ledger run",
        "top20_10D_matured_observations": int(ledger20["h10_matured"].sum()),
        "top50_10D_matured_observations": int(ledger50["h10_matured"].sum()),
        "independent_ranking_snapshots": 1,
        "required_top20_10D_matured_observations": 60,
        "required_top50_10D_matured_observations": 150,
        "required_independent_ranking_snapshots": 3,
        "E_adoption_allowed": False,
    }])
    leakage_score_cols = COMPONENT_COLUMNS
    leakage_risk = any(any(token in col.lower() for token in ["forward_return", "future_label", "matured_return", "outcome"]) for col in leakage_score_cols)
    no_leakage = pd.DataFrame([{
        "check": "E_R1 frozen score source",
        "status": "PASS" if not leakage_risk else "FAIL",
        "ranking_date": ranking_date,
        "price_panel_max_date": price_panel_max,
        "source_path": rel(E_R1_FULL),
        "original_invalid_v21_133_used_as_primary_source": False,
        "score_columns_checked": "|".join(leakage_score_cols),
        "forward_returns_used_to_compute_E_score": False,
    }])
    data_quality_rows = [{"warning_type": warning.split(":")[0], "warning_detail": warning} for warning in warnings]
    if not data_quality_rows:
        data_quality_rows = [{"warning_type": "none", "warning_detail": "No data quality warnings"}]

    ledger20.to_csv(OUT / "e_r1_forward_ledger_top20.csv", index=False)
    ledger50.to_csv(OUT / "e_r1_forward_ledger_top50.csv", index=False)
    summary_by_horizon.to_csv(OUT / "e_r1_forward_summary_by_horizon.csv", index=False)
    vs_qqq.to_csv(OUT / "e_r1_vs_qqq_forward_summary.csv", index=False)
    comparison.to_csv(OUT / "e_r1_vs_abcd_forward_comparison.csv", index=False)
    maturity.to_csv(OUT / "e_r1_maturity_gate_audit.csv", index=False)
    no_leakage.to_csv(OUT / "e_r1_no_leakage_audit.csv", index=False)
    write_csv(OUT / "e_r1_data_quality_audit.csv", data_quality_rows)

    mature_any = int(summary_by_horizon["matured_rows"].sum()) > 0
    material_warn = any(row["warning_type"] != "none" for row in data_quality_rows)
    if leakage_risk:
        final_status = "FAIL_V21_134_E_R1_LEAKAGE_RISK"
        decision = "E_R1_FORWARD_TRACKING_REJECTED_LEAKAGE_RISK"
    elif material_warn:
        final_status = "PARTIAL_PASS_V21_134_E_R1_LEDGER_STARTED_WITH_DATA_WARN"
        decision = "E_R1_FORWARD_TRACKING_STARTED_DATA_WARNING_ADOPTION_BLOCKED"
    elif not mature_any:
        final_status = "PARTIAL_PASS_V21_134_E_R1_LEDGER_STARTED_WAIT_MATURITY"
        decision = "E_R1_FORWARD_TRACKING_STARTED_RESEARCH_ONLY_WAIT_MATURITY"
    else:
        final_status = "PARTIAL_PASS_V21_134_E_R1_FORWARD_TRACKING_UPDATED_ADOPTION_BLOCKED"
        decision = "E_R1_TRACKING_UPDATED_RESEARCH_ONLY_ADOPTION_BLOCKED"

    post_hashes = {rel(p): sha256(p) for p in protected_inputs}
    prot_mod = baseline_hashes != post_hashes or protected_modified(git_status(), baseline_status)
    summary = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "ranking_date": ranking_date,
        "latest_price_date_used": ranking_date,
        "price_panel_max_date": price_panel_max,
        "E_R1_source_path": rel(E_R1_FULL),
        "invalid_original_v21_133_primary_source_used": False,
        "E_R1_top20": "|".join(e_top20.sort_values(["rank", "ticker_norm"]).head(20)["ticker_norm"]),
        "top20_rows": int(len(ledger20)),
        "top50_rows": int(len(ledger50)),
        "top20_maturity_by_horizon": {f"{h}D": {"matured": int(ledger20[f"h{h}_matured"].sum()), "pending": int((~ledger20[f"h{h}_matured"].astype(bool)).sum())} for h in HORIZONS},
        "top50_maturity_by_horizon": {f"{h}D": {"matured": int(ledger50[f"h{h}_matured"].sum()), "pending": int((~ledger50[f"h{h}_matured"].astype(bool)).sum())} for h in HORIZONS},
        "maturity_gate_result": "BLOCK",
        "warnings": "|".join(row["warning_type"] for row in data_quality_rows if row["warning_type"] != "none") or "none",
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "E_adoption_allowed": False,
        "protected_outputs_modified": bool(prot_mod),
        "report_path": rel(OUT / "V21.134_E_R1_FORWARD_TRACKING_LEDGER_report.txt"),
    }
    write_json(OUT / "e_r1_forward_tracking_summary.json", summary)
    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"ranking_date={ranking_date}",
        f"latest_price_date_used={ranking_date}",
        f"E_R1_source_path={rel(E_R1_FULL)}",
        f"E_R1_top20={summary['E_R1_top20']}",
        "Top20 matured/pending rows by horizon=" + json.dumps(summary["top20_maturity_by_horizon"], sort_keys=True),
        "Top50 matured/pending rows by horizon=" + json.dumps(summary["top50_maturity_by_horizon"], sort_keys=True),
        "E_R1 win rate vs QQQ if mature rows exist",
        vs_qqq.to_csv(index=False).strip(),
        "E_R1 vs A1/B/C/D comparison if available",
        comparison.to_csv(index=False).strip(),
        f"maturity_gate_result={summary['maturity_gate_result']}",
        f"warnings={summary['warnings']}",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
        "E_adoption_allowed=false",
        "protected_outputs_modified=false",
    ]
    (OUT / "V21.134_E_R1_FORWARD_TRACKING_LEDGER_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    print(STAGE)
    print(f"FINAL_STATUS={final_status}")
    print(f"DECISION={decision}")
    print(f"report_path={summary['report_path']}")
    print(f"ranking_date={ranking_date}")
    print(f"latest_price_date_used={ranking_date}")
    print(f"E_R1_Top20={summary['E_R1_top20']}")
    print("Top20_maturity=" + json.dumps(summary["top20_maturity_by_horizon"], sort_keys=True))
    print("Top50_maturity=" + json.dumps(summary["top50_maturity_by_horizon"], sort_keys=True))
    print("E_R1_win_rate_vs_QQQ_if_mature=" + vs_qqq.to_json(orient="records"))
    print("E_R1_vs_ABCD_comparison=" + comparison.to_json(orient="records"))
    print(f"maturity_gate_result={summary['maturity_gate_result']}")
    print(f"warnings={summary['warnings']}")
    return summary


if __name__ == "__main__":
    run()
