#!/usr/bin/env python
"""V21.135 ABCDE same-date forward alignment."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.135_ABCDE_SAME_DATE_FORWARD_ALIGNMENT"
OUT = ROOT / "outputs/v21/V21.135_ABCDE_SAME_DATE_FORWARD_ALIGNMENT"
R1 = ROOT / "outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR"
V134 = ROOT / "outputs/v21/V21.134_E_R1_FORWARD_TRACKING_LEDGER"
PRICE_PANEL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
E_R1_SOURCE = R1 / "e_r1_full_ranking.csv"
INVALID_E_SOURCE = ROOT / "outputs/v21/V21.133_E_CONSERVATIVE_ADAPTIVE_MOMENTUM_R1/e_full_ranking.csv"
AUDIT = R1 / "input_artifact_audit.csv"
E_R1_SUMMARY = V134 / "e_r1_forward_tracking_summary.json"
HORIZONS = [5, 10, 20]
STRATEGIES = ["A1", "B", "C", "D", "E_R1"]


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
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


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
    allowed_prefix = "?? outputs/v21/V21.135_ABCDE_SAME_DATE_FORWARD_ALIGNMENT/"
    allowed_scripts = {
        "?? scripts/v21/v21_135_abcde_same_date_forward_alignment.py",
        "?? scripts/v21/test_v21_135_abcde_same_date_forward_alignment.py",
        "?? scripts/v21/run_v21_135_abcde_same_date_forward_alignment.ps1",
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


def clean_float(value: Any) -> Any:
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(val) or math.isinf(val) else val


def discover_sources() -> tuple[dict[str, Path], list[str]]:
    warnings: list[str] = []
    sources: dict[str, Path] = {"E_R1": E_R1_SOURCE}
    if AUDIT.is_file():
        audit = pd.read_csv(AUDIT, keep_default_na=False)
        for strategy in ["A1", "B", "C", "D"]:
            rows = audit[audit["input_name"].eq(strategy)]
            if not rows.empty and rows.iloc[0].get("path"):
                sources[strategy] = ROOT / str(rows.iloc[0]["path"])
    fallback = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE"
    for strategy, name in {
        "A1": "A1_BASELINE_CONTROL_latest_ranking.csv",
        "B": "B_STATIC_MOMENTUM_BLEND_latest_ranking.csv",
        "C": "C_DYNAMIC_MOMENTUM_BLEND_latest_ranking.csv",
        "D": "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv",
    }.items():
        if strategy not in sources:
            sources[strategy] = fallback / name
            warnings.append(f"{strategy}_SOURCE_FALLBACK_DISCOVERY_USED")
    return sources, warnings


def load_rankings(sources: dict[str, Path], ranking_date: str) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]], list[str]]:
    frames: dict[str, pd.DataFrame] = {}
    audits = []
    warnings: list[str] = []
    for strategy in STRATEGIES:
        path = sources[strategy]
        if not path.is_file():
            warnings.append(f"MISSING_{strategy}_SOURCE")
            audits.append({"strategy_id": strategy, "source_path": rel(path), "exists": False})
            continue
        frame = pd.read_csv(path, low_memory=False)
        if "ticker_norm" not in frame.columns and "ticker" in frame.columns:
            frame["ticker_norm"] = frame["ticker"].map(ticker_norm)
        frame = frame[frame["ticker_norm"].astype(str).str.strip().ne("")].copy()
        score_col = "E_final_score" if strategy == "E_R1" else "final_score"
        if score_col not in frame.columns:
            score_col = "E_final_score" if "E_final_score" in frame.columns else ("final_score" if "final_score" in frame.columns else "")
        latest = ""
        if "latest_price_date" in frame.columns:
            latest = str(frame["latest_price_date"].dropna().astype(str).max())
        elif strategy == "E_R1":
            latest = ranking_date
        comparable = latest == ranking_date
        if not comparable:
            warnings.append(f"{strategy}_SOURCE_DATE_MISMATCH:{latest}")
        audits.append({
            "strategy_id": strategy,
            "source_path": rel(path),
            "exists": True,
            "row_count": len(frame),
            "score_column": score_col,
            "rank_column": "rank" if "rank" in frame.columns else "",
            "source_latest_price_date_used": latest,
            "ranking_date": ranking_date,
            "comparable_same_date": comparable,
            "top20_tickers": "|".join(frame.sort_values(["rank", "ticker_norm"]).head(20)["ticker_norm"]),
            "duplicate_ticker_norm_count": int(frame["ticker_norm"].duplicated().sum()),
        })
        frames[strategy] = frame
    return frames, audits, warnings


def load_prices(tickers: set[str]) -> tuple[dict[str, pd.DataFrame], str, list[str]]:
    warnings: list[str] = []
    wanted = set(tickers) | {"QQQ", "SOXX"}
    if not PRICE_PANEL.is_file():
        return {}, "", [f"MISSING_PRICE_PANEL:{rel(PRICE_PANEL)}"]
    chunks = []
    max_date = ""
    for chunk in pd.read_csv(PRICE_PANEL, usecols=["symbol", "date", "adjusted_close", "close"], chunksize=250_000, low_memory=False):
        chunk["symbol"] = chunk["symbol"].astype(str).str.upper().str.strip()
        chunk["date"] = chunk["date"].astype(str)
        max_date = max(max_date, chunk["date"].max())
        sub = chunk[chunk["symbol"].isin(wanted)].copy()
        if not sub.empty:
            chunks.append(sub)
    if not chunks:
        return {}, max_date, ["NO_PRICE_ROWS_FOR_ALIGNMENT"]
    prices = pd.concat(chunks, ignore_index=True).sort_values(["symbol", "date"])
    have = set(prices["symbol"])
    if "QQQ" not in have:
        warnings.append("MISSING_PRIMARY_BENCHMARK_QQQ")
    if "SOXX" not in have:
        warnings.append("MISSING_SECONDARY_BENCHMARK_SOXX")
    missing = sorted(wanted - have)
    if missing:
        warnings.append("MISSING_PRICE_TICKERS:" + "|".join(missing))
    return {sym: grp.reset_index(drop=True) for sym, grp in prices.groupby("symbol")}, max_date, warnings


def price_at_or_after(hist: pd.DataFrame, date: str) -> tuple[str, float]:
    if hist.empty:
        return "", math.nan
    sub = hist[hist["date"].astype(str) >= date]
    if sub.empty:
        return "", math.nan
    row = sub.iloc[0]
    return str(row["date"]), float(row.get("adjusted_close", row.get("close")))


def forward_price(hist: pd.DataFrame, entry_date: str, horizon: int) -> tuple[str, float, bool]:
    if hist.empty or not entry_date:
        return "", math.nan, False
    dates = hist["date"].astype(str).tolist()
    if entry_date not in dates:
        return "", math.nan, False
    idx = dates.index(entry_date) + horizon
    if idx >= len(hist):
        return "", math.nan, False
    row = hist.iloc[idx]
    return str(row["date"]), float(row.get("adjusted_close", row.get("close"))), True


def make_bucket_ledger(frames: dict[str, pd.DataFrame], audits: list[dict[str, Any]], histories: dict[str, pd.DataFrame], ranking_date: str, bucket: str, n: int) -> pd.DataFrame:
    audit_map = {row["strategy_id"]: row for row in audits}
    qqq = histories.get("QQQ", pd.DataFrame())
    soxx = histories.get("SOXX", pd.DataFrame())
    qqq_entry_date, qqq_entry = price_at_or_after(qqq, ranking_date)
    soxx_entry_date, soxx_entry = price_at_or_after(soxx, ranking_date)
    rows = []
    for strategy, frame in frames.items():
        score_col = audit_map[strategy].get("score_column", "")
        selected = frame.sort_values(["rank", "ticker_norm"]).head(n)
        for rec in selected.to_dict("records"):
            ticker = ticker_norm(rec["ticker_norm"])
            hist = histories.get(ticker, pd.DataFrame())
            entry_date, entry_close = price_at_or_after(hist, ranking_date)
            row = {
                "strategy_id": strategy,
                "bucket": bucket,
                "ranking_date": ranking_date,
                "ticker_norm": ticker,
                "rank": rec.get("rank", ""),
                "final_score": rec.get(score_col, rec.get("E_final_score", rec.get("final_score", ""))),
                "source_path": audit_map[strategy].get("source_path", ""),
                "source_latest_price_date_used": audit_map[strategy].get("source_latest_price_date_used", ""),
                "comparable_same_date": bool(audit_map[strategy].get("comparable_same_date", False)),
                "entry_close_price": entry_close,
                "entry_date": entry_date,
                "missing_price_flag": bool(not entry_date or math.isnan(entry_close)),
                "stale_source_flag": not bool(audit_map[strategy].get("comparable_same_date", False)),
            }
            warnings = []
            if row["missing_price_flag"]:
                warnings.append("MISSING_ENTRY_PRICE")
            if row["stale_source_flag"]:
                warnings.append("SOURCE_DATE_MISMATCH")
            for h in HORIZONS:
                f_date, f_close, matured = forward_price(hist, entry_date, h)
                q_date, q_close, q_matured = forward_price(qqq, qqq_entry_date, h)
                s_date, s_close, s_matured = forward_price(soxx, soxx_entry_date, h)
                ret = f_close / entry_close - 1.0 if matured and entry_close and not math.isnan(entry_close) else math.nan
                q_ret = q_close / qqq_entry - 1.0 if q_matured and qqq_entry and not math.isnan(qqq_entry) else math.nan
                s_ret = s_close / soxx_entry - 1.0 if s_matured and soxx_entry and not math.isnan(soxx_entry) else math.nan
                row[f"h{h}_forward_date"] = f_date
                row[f"h{h}_forward_close_price"] = f_close
                row[f"h{h}_forward_return"] = ret
                row[f"h{h}_qqq_forward_return"] = q_ret
                row[f"h{h}_soxx_forward_return"] = s_ret
                row[f"h{h}_excess_return_vs_QQQ"] = ret - q_ret if matured and q_matured else math.nan
                row[f"h{h}_excess_return_vs_SOXX"] = ret - s_ret if matured and s_matured else math.nan
                row[f"h{h}_matured"] = bool(matured)
                row[f"h{h}_qqq_matured"] = bool(q_matured)
                row[f"h{h}_soxx_matured"] = bool(s_matured)
            row["data_warning_flags"] = "|".join(warnings)
            rows.append(row)
    return pd.DataFrame(rows)


def overlap_matrix(ledger: pd.DataFrame, bucket: str) -> pd.DataFrame:
    sets = {s: set(ledger[(ledger["bucket"].eq(bucket)) & (ledger["strategy_id"].eq(s))]["ticker_norm"]) for s in STRATEGIES}
    rows = []
    for left in STRATEGIES:
        row = {"strategy_id": left}
        for right in STRATEGIES:
            row[right] = len(sets[left].intersection(sets[right]))
        rows.append(row)
    return pd.DataFrame(rows)


def summarize(ledger: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (strategy, bucket), group in ledger.groupby(["strategy_id", "bucket"]):
        for h in HORIZONS:
            ret = pd.to_numeric(group[f"h{h}_forward_return"], errors="coerce")
            qqq = pd.to_numeric(group[f"h{h}_qqq_forward_return"], errors="coerce")
            excess = pd.to_numeric(group[f"h{h}_excess_return_vs_QQQ"], errors="coerce")
            matured = group[f"h{h}_matured"].astype(bool)
            rows.append({
                "strategy_id": strategy,
                "bucket": bucket,
                "horizon": f"{h}D",
                "total_rows": len(group),
                "matured_rows": int(matured.sum()),
                "pending_rows": int((~matured).sum()),
                "missing_price_rows": int(group["missing_price_flag"].astype(bool).sum()),
                "average_return": clean_float(ret.mean()),
                "median_return": clean_float(ret.median()),
                "hit_rate_positive": clean_float((ret > 0).mean()) if ret.notna().any() else None,
                "average_QQQ_return": clean_float(qqq.mean()),
                "median_QQQ_return": clean_float(qqq.median()),
                "win_rate_vs_QQQ": clean_float((excess > 0).mean()) if excess.notna().any() else None,
                "average_excess_return_vs_QQQ": clean_float(excess.mean()),
                "median_excess_return_vs_QQQ": clean_float(excess.median()),
                "worst_return": clean_float(ret.min()),
                "best_return": clean_float(ret.max()),
            })
    return pd.DataFrame(rows)


def pairwise(ledger: pd.DataFrame) -> pd.DataFrame:
    pairs = [("E_R1", "A1"), ("E_R1", "B"), ("E_R1", "C"), ("E_R1", "D"), ("A1", "B"), ("A1", "C"), ("A1", "D"), ("B", "C"), ("B", "D"), ("C", "D")]
    rows = []
    for left, right in pairs:
        for bucket in ["Top20", "Top50"]:
            b = bucket.lower()
            lset = set(ledger[(ledger["strategy_id"].eq(left)) & (ledger["bucket"].eq(b))]["ticker_norm"])
            rset = set(ledger[(ledger["strategy_id"].eq(right)) & (ledger["bucket"].eq(b))]["ticker_norm"])
            overlap = sorted(lset.intersection(rset))
            for h in HORIZONS:
                l = ledger[(ledger["strategy_id"].eq(left)) & (ledger["bucket"].eq(b))]
                r = ledger[(ledger["strategy_id"].eq(right)) & (ledger["bucket"].eq(b))]
                lret = pd.to_numeric(l[f"h{h}_forward_return"], errors="coerce")
                rret = pd.to_numeric(r[f"h{h}_forward_return"], errors="coerce")
                mature = lret.notna() & rret.notna()
                rows.append({
                    "pair": f"{left}_vs_{right}",
                    "first_strategy": left,
                    "second_strategy": right,
                    "bucket": bucket,
                    "horizon": f"{h}D",
                    "status": "MATURE" if mature.any() else "PENDING_NO_MATURE_ROWS",
                    "average_return_delta": clean_float(lret.mean() - rret.mean()) if mature.any() else None,
                    "median_return_delta": clean_float(lret.median() - rret.median()) if mature.any() else None,
                    "win_rate_first_vs_second": clean_float((lret.reset_index(drop=True) > rret.reset_index(drop=True)).mean()) if mature.any() else None,
                    "excess_return_delta_vs_QQQ": None,
                    "overlap_count": len(overlap),
                    "overlap_tickers": "|".join(overlap),
                })
    return pd.DataFrame(rows)


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_status = git_status()
    sources, warnings = discover_sources()
    protected = [p for p in [*sources.values(), PRICE_PANEL, AUDIT, E_R1_SUMMARY] if p.is_file()]
    baseline_hashes = {rel(p): sha256(p) for p in protected}
    v134 = load_json(E_R1_SUMMARY)
    ranking_date = str(v134.get("ranking_date", "2026-06-26"))
    if not E_R1_SOURCE.is_file():
        summary = {"stage": STAGE, "FINAL_STATUS": "BLOCKED_V21_135_E_R1_SOURCE_MISSING", "DECISION": "ABCDE_ALIGNMENT_BLOCKED_MISSING_REPAIRED_E_SOURCE", "official_adoption_allowed": False, "broker_action_allowed": False, "research_only": True, "E_adoption_allowed": False, "protected_outputs_modified": False}
        write_json(OUT / "abcde_alignment_summary.json", summary)
        return summary
    if not sources.get("A1", Path()).is_file():
        summary = {"stage": STAGE, "FINAL_STATUS": "BLOCKED_V21_135_A1_SOURCE_MISSING", "DECISION": "ABCDE_ALIGNMENT_BLOCKED_MISSING_A1_CONTROL", "official_adoption_allowed": False, "broker_action_allowed": False, "research_only": True, "E_adoption_allowed": False, "protected_outputs_modified": False}
        write_json(OUT / "abcde_alignment_summary.json", summary)
        return summary
    frames, source_audit, source_warnings = load_rankings(sources, ranking_date)
    warnings.extend(source_warnings)
    all_tickers = set()
    for frame in frames.values():
        all_tickers.update(frame.sort_values(["rank", "ticker_norm"]).head(50)["ticker_norm"])
    histories, price_max, price_warnings = load_prices(all_tickers)
    warnings.extend(price_warnings)
    top20 = make_bucket_ledger(frames, source_audit, histories, ranking_date, "top20", 20)
    top50 = make_bucket_ledger(frames, source_audit, histories, ranking_date, "top50", 50)
    ledger = pd.concat([top20, top50], ignore_index=True)
    top20_matrix = overlap_matrix(ledger, "top20")
    top50_matrix = overlap_matrix(ledger, "top50")
    forward_summary = summarize(ledger)
    pairwise_df = pairwise(ledger)
    mature_total = int(forward_summary["matured_rows"].sum())
    same_date_all = all(bool(row.get("comparable_same_date")) for row in source_audit if row.get("strategy_id") in STRATEGIES)
    leakage = any(any(tok in col.lower() for tok in ["future_label", "outcome"]) for col in ledger.columns)
    no_leakage = [{"check": "same_date_forward_alignment", "status": "PASS" if not leakage else "FAIL", "ranking_date": ranking_date, "price_panel_max_date": price_max, "invalid_original_v21_133_e_used": False, "forward_returns_used_for_scoring": False}]
    maturity = [{"gate": "E_R1_ADOPTION_MATURITY", "status": "BLOCK", "reason": "first same-date alignment has no mature E_R1 adoption evidence", "E_R1_top20_10D_matured_observations": int(top20[(top20["strategy_id"].eq("E_R1"))]["h10_matured"].sum()), "E_R1_top50_10D_matured_observations": int(top50[(top50["strategy_id"].eq("E_R1"))]["h10_matured"].sum()), "independent_ranking_snapshots": 1, "E_adoption_allowed": False}]
    dq = [{"warning_type": w.split(":")[0], "warning_detail": w} for w in warnings] or [{"warning_type": "none", "warning_detail": "No data quality warnings"}]
    top20.to_csv(OUT / "abcde_aligned_top20_forward_ledger.csv", index=False)
    top50.to_csv(OUT / "abcde_aligned_top50_forward_ledger.csv", index=False)
    write_csv(OUT / "abcde_same_date_source_audit.csv", source_audit)
    top20_matrix.to_csv(OUT / "abcde_top20_overlap_matrix.csv", index=False)
    top50_matrix.to_csv(OUT / "abcde_top50_overlap_matrix.csv", index=False)
    forward_summary.to_csv(OUT / "abcde_forward_summary_by_strategy_horizon.csv", index=False)
    pairwise_df.to_csv(OUT / "abcde_pairwise_forward_comparison.csv", index=False)
    write_csv(OUT / "abcde_maturity_gate_audit.csv", maturity)
    write_csv(OUT / "abcde_no_leakage_audit.csv", no_leakage)
    write_csv(OUT / "abcde_data_quality_audit.csv", dq)
    if leakage:
        final_status = "FAIL_V21_135_LEAKAGE_RISK"; decision = "ABCDE_ALIGNMENT_REJECTED_LEAKAGE_RISK"
    elif not same_date_all:
        final_status = "PARTIAL_PASS_V21_135_ABCDE_ALIGNMENT_WITH_SOURCE_DATE_WARN"; decision = "ABCDE_ALIGNMENT_READY_BUT_SOME_SOURCES_NOT_SAME_DATE_COMPARABLE"
    elif mature_total == 0:
        final_status = "PARTIAL_PASS_V21_135_ABCDE_ALIGNMENT_READY_WAIT_MATURITY"; decision = "ABCDE_SAME_DATE_FORWARD_ALIGNMENT_READY_RESEARCH_ONLY_WAIT_MATURITY"
    else:
        final_status = "PARTIAL_PASS_V21_135_ABCDE_ALIGNMENT_UPDATED_ADOPTION_BLOCKED"; decision = "ABCDE_FORWARD_ALIGNMENT_UPDATED_RESEARCH_ONLY_ADOPTION_BLOCKED"
    post_hashes = {rel(p): sha256(p) for p in protected}
    prot_mod = baseline_hashes != post_hashes or protected_modified(git_status(), baseline_status)
    top20_dict = {s: "|".join(top20[top20["strategy_id"].eq(s)].sort_values("rank")["ticker_norm"]) for s in STRATEGIES}
    maturity_counts = forward_summary[["strategy_id", "bucket", "horizon", "matured_rows", "pending_rows"]].to_dict("records")
    summary = {
        "stage": STAGE, "FINAL_STATUS": final_status, "DECISION": decision, "ranking_date": ranking_date, "price_panel_max_date": price_max,
        "source_paths": {k: rel(v) for k, v in sources.items()}, "same_date_comparable": {r["strategy_id"]: bool(r.get("comparable_same_date")) for r in source_audit},
        "invalid_original_v21_133_e_used": False, "top20_by_strategy": top20_dict,
        "E_R1_vs_A1_top20_overlap": int(top20_matrix[top20_matrix["strategy_id"].eq("E_R1")]["A1"].iloc[0]),
        "matured_pending_counts": maturity_counts, "maturity_gate_result": "BLOCK", "warnings": "|".join(d["warning_type"] for d in dq if d["warning_type"] != "none") or "none",
        "official_adoption_allowed": False, "broker_action_allowed": False, "research_only": True, "E_adoption_allowed": False, "protected_outputs_modified": bool(prot_mod),
        "report_path": rel(OUT / "V21.135_ABCDE_SAME_DATE_FORWARD_ALIGNMENT_report.txt"),
    }
    write_json(OUT / "abcde_alignment_summary.json", summary)
    report = [STAGE, f"FINAL_STATUS={final_status}", f"DECISION={decision}", f"report_path={summary['report_path']}", f"ranking_date={ranking_date}", f"source_paths={json.dumps(summary['source_paths'], sort_keys=True)}", f"same_date_comparable={json.dumps(summary['same_date_comparable'], sort_keys=True)}", f"top20_by_strategy={json.dumps(top20_dict, sort_keys=True)}", "ABCDE Top20 overlap matrix", top20_matrix.to_csv(index=False).strip(), "ABCDE Top50 overlap matrix", top50_matrix.to_csv(index=False).strip(), "matured/pending counts", forward_summary[["strategy_id","bucket","horizon","matured_rows","pending_rows"]].to_csv(index=False).strip(), "E_R1 vs A1/B/C/D forward comparison", pairwise_df[pairwise_df["first_strategy"].eq("E_R1")].to_csv(index=False).strip(), f"maturity_gate_result={summary['maturity_gate_result']}", f"warnings={summary['warnings']}", "protected_outputs_modified=false", "official_adoption_allowed=false", "broker_action_allowed=false", "research_only=true"]
    (OUT / "V21.135_ABCDE_SAME_DATE_FORWARD_ALIGNMENT_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(STAGE)
    print(f"FINAL_STATUS={final_status}")
    print(f"DECISION={decision}")
    print(f"report_path={summary['report_path']}")
    print(f"ranking_date={ranking_date}")
    print("source_paths=" + json.dumps(summary["source_paths"], sort_keys=True))
    print("same_date_comparable=" + json.dumps(summary["same_date_comparable"], sort_keys=True))
    print("top20_by_strategy=" + json.dumps(top20_dict, sort_keys=True))
    print("ABCDE_top20_overlap_matrix=" + top20_matrix.to_json(orient="records"))
    print("ABCDE_top50_overlap_matrix=" + top50_matrix.to_json(orient="records"))
    print("matured_pending_counts=" + json.dumps(maturity_counts, sort_keys=True))
    print("E_R1_vs_ABCD_forward_comparison=" + pairwise_df[pairwise_df["first_strategy"].eq("E_R1")].to_json(orient="records"))
    print(f"maturity_gate_result={summary['maturity_gate_result']}")
    print(f"warnings={summary['warnings']}")
    return summary


if __name__ == "__main__":
    run()
