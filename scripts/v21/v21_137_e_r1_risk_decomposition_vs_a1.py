#!/usr/bin/env python
"""V21.137 E_R1 risk decomposition versus A1."""

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
STAGE = "V21.137_E_R1_RISK_DECOMPOSITION_VS_A1"
OUT = ROOT / "outputs/v21/V21.137_E_R1_RISK_DECOMPOSITION_VS_A1"
A1_SOURCE = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE/A1_BASELINE_CONTROL_latest_ranking.csv"
E_SOURCE = ROOT / "outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv"
ALIGNMENT_SUMMARY = ROOT / "outputs/v21/V21.135_ABCDE_SAME_DATE_FORWARD_ALIGNMENT/abcde_alignment_summary.json"
TOP20_OVERLAP = ROOT / "outputs/v21/V21.135_ABCDE_SAME_DATE_FORWARD_ALIGNMENT/abcde_top20_overlap_matrix.csv"
TOP50_OVERLAP = ROOT / "outputs/v21/V21.135_ABCDE_SAME_DATE_FORWARD_ALIGNMENT/abcde_top50_overlap_matrix.csv"
TOP20_ENTRIES = ROOT / "outputs/v21/V21.136_E_R1_OVERLAY_INFLUENCE_AND_CALIBRATION_DIAGNOSTIC/e_r1_top20_entries_exits.csv"
TOP50_ENTRIES = ROOT / "outputs/v21/V21.136_E_R1_OVERLAY_INFLUENCE_AND_CALIBRATION_DIAGNOSTIC/e_r1_top50_entries_exits.csv"
CONTRIB = ROOT / "outputs/v21/V21.136_E_R1_OVERLAY_INFLUENCE_AND_CALIBRATION_DIAGNOSTIC/e_r1_component_contribution_decomposition.csv"
OVERLAY_SUMMARY = ROOT / "outputs/v21/V21.136_E_R1_OVERLAY_INFLUENCE_AND_CALIBRATION_DIAGNOSTIC/e_r1_overlay_diagnostic_summary.json"
PRICE_PANEL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
METADATA_CANDIDATES = [
    ROOT / "outputs/v21/V21.111_R3A_EXPOSURE_METADATA_BRIDGE_AND_R3_RERUN/r3_rerun/top50_metadata_summary.csv",
    ROOT / "outputs/v21/V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT/d_only_ticker_profile.csv",
    ROOT / "outputs/v21/V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT/eligible_universe_sector_baseline.csv",
]
REPEATED_CANDIDATES = [
    ROOT / "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE/V21.129_d_repeated_loser_diagnostic.csv",
    ROOT / "outputs/v21/V21.111_D_FAILURE_MODE_DECOMPOSITION/repeated_loss_tickers.csv",
    ROOT / "outputs/v21/V21.119_R1_FORWARD_MATURITY_UPDATE_AFTER_REFRESH/repeated_loser_after_refresh_update.csv",
]
ALLOWED_DECISIONS = {
    "E_R1_RISK_PROFILE_ACCEPTABLE_WAIT_MATURITY",
    "E_R1_RISK_PROFILE_ACCEPTABLE_WITH_WARN_WAIT_MATURITY",
    "E_R1_RISK_PROFILE_WORSE_THAN_A1_REVIEW_REQUIRED",
    "E_R1_REJECT_STRUCTURAL_RISK",
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
    allowed_prefix = "?? outputs/v21/V21.137_E_R1_RISK_DECOMPOSITION_VS_A1/"
    allowed_scripts = {
        "?? scripts/v21/v21_137_e_r1_risk_decomposition_vs_a1.py",
        "?? scripts/v21/test_v21_137_e_r1_risk_decomposition_vs_a1.py",
        "?? scripts/v21/run_v21_137_e_r1_risk_decomposition_vs_a1.ps1",
    }
    for line in status_lines:
        normalized = line.replace("\\", "/")
        if normalized in baseline or normalized.startswith(allowed_prefix) or normalized in allowed_scripts:
            continue
        lowered = normalized.lower()
        if lowered.startswith((" m outputs/", " d outputs/", "?? outputs/")) and ("official" in lowered or "broker" in lowered or "protected" in lowered):
            return True
    return False


def ticker_norm(value: Any) -> str:
    return str(value).upper().strip()


def load_metadata() -> tuple[dict[str, dict[str, str]], str, list[str]]:
    warnings: list[str] = []
    mapping: dict[str, dict[str, str]] = {}
    source = ""
    for path in METADATA_CANDIDATES:
        if not path.is_file():
            continue
        frame = pd.read_csv(path, low_memory=False)
        if "ticker" not in frame.columns:
            continue
        source = rel(path)
        for row in frame.to_dict("records"):
            t = ticker_norm(row.get("ticker"))
            if t and t != "NAN":
                mapping[t] = {
                    "sector": str(row.get("sector", row.get("Sector", "UNKNOWN")) or "UNKNOWN"),
                    "industry": str(row.get("industry", row.get("Industry", "UNKNOWN")) or "UNKNOWN"),
                }
        if mapping:
            break
    if not mapping:
        warnings.append("METADATA_SOURCE_MISSING")
    return mapping, source, warnings


def split_tickers(value: Any) -> set[str]:
    return {ticker_norm(x) for x in str(value or "").replace(",", "|").split("|") if ticker_norm(x) and ticker_norm(x) != "NAN"}


def load_repeated() -> tuple[set[str], str, bool, list[str]]:
    warnings: list[str] = []
    for path in REPEATED_CANDIDATES:
        if not path.is_file():
            continue
        frame = pd.read_csv(path, low_memory=False, keep_default_na=False)
        tickers: set[str] = set()
        for col in frame.columns:
            if "ticker" in col.lower() or "loser" in col.lower():
                for val in frame[col].head(20):
                    tickers |= split_tickers(val)
        if tickers:
            return tickers, rel(path), True, warnings
    warnings.append("REPEATED_LOSER_SOURCE_MISSING_PRICE_PROXY_ONLY")
    return set(), "", False, warnings


def hhi(values: pd.Series) -> float:
    counts = values.fillna("UNKNOWN").value_counts(normalize=True)
    return float((counts ** 2).sum()) if len(counts) else math.nan


def concentration(strategy: str, bucket: str, frame: pd.DataFrame, metadata: dict[str, dict[str, str]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = []
    enriched = []
    for t in frame["ticker_norm"]:
        meta = metadata.get(t, {"sector": "UNKNOWN", "industry": "UNKNOWN"})
        enriched.append({"strategy": strategy, "bucket": bucket, "ticker_norm": t, **meta})
    e = pd.DataFrame(enriched)
    for exposure in ["sector", "industry"]:
        for rank, (bucket_name, count) in enumerate(e[exposure].value_counts().items(), start=1):
            rows.append({"strategy": strategy, "bucket": bucket, "exposure_type": exposure, "bucket_name": bucket_name, "count": int(count), "weight": count / len(e), "rank": rank})
    sector_counts = e["sector"].value_counts(normalize=True)
    industry_counts = e["industry"].value_counts(normalize=True)
    metric = {
        "strategy": strategy,
        "bucket": bucket,
        "top_sector_weight": float(sector_counts.max()) if len(sector_counts) else math.nan,
        "top_industry_weight": float(industry_counts.max()) if len(industry_counts) else math.nan,
        "unique_sectors": int(e["sector"].nunique()),
        "unique_industries": int(e["industry"].nunique()),
        "sector_hhi": hhi(e["sector"]),
        "industry_hhi": hhi(e["industry"]),
        "metadata_coverage_ratio": float((e["sector"] != "UNKNOWN").mean()) if len(e) else 0.0,
    }
    return metric, rows


def load_prices(tickers: set[str], ranking_date: str) -> tuple[dict[str, pd.DataFrame], list[str]]:
    warnings = []
    chunks = []
    if not PRICE_PANEL.is_file():
        return {}, ["PRICE_PANEL_MISSING"]
    for chunk in pd.read_csv(PRICE_PANEL, usecols=["symbol", "date", "adjusted_close"], chunksize=250_000, low_memory=False):
        chunk["symbol"] = chunk["symbol"].astype(str).str.upper().str.strip()
        chunk["date"] = chunk["date"].astype(str)
        sub = chunk[chunk["symbol"].isin(tickers) & (chunk["date"] <= ranking_date)].copy()
        if not sub.empty:
            chunks.append(sub)
    if not chunks:
        return {}, ["NO_PRICE_ROWS_FOR_RISK_PROXY"]
    prices = pd.concat(chunks).sort_values(["symbol", "date"])
    missing = sorted(tickers - set(prices["symbol"]))
    if missing:
        warnings.append("MISSING_PRICE_TICKERS:" + "|".join(missing))
    return {sym: grp.reset_index(drop=True) for sym, grp in prices.groupby("symbol")}, warnings


def risk_proxy(ticker: str, hist: pd.DataFrame, ranking_date: str) -> dict[str, Any]:
    if hist.empty:
        return {"ticker_norm": ticker, "price_history_available": False, "latest_price_date_used": "", "trailing_20d_return": None, "trailing_60d_return": None, "trailing_volatility_proxy": None, "worst_rolling_5d_return": None, "worst_rolling_10d_return": None, "worst_rolling_20d_return": None, "max_drawdown_proxy": None, "left_tail_warning_flag": True}
    close = pd.to_numeric(hist["adjusted_close"], errors="coerce").dropna()
    ret = close.pct_change()
    def trailing(n: int) -> Any:
        return float(close.iloc[-1] / close.iloc[-n - 1] - 1) if len(close) > n and close.iloc[-n - 1] else None
    def worst(n: int) -> Any:
        vals = close.pct_change(n).dropna()
        return float(vals.min()) if len(vals) else None
    dd = close / close.cummax() - 1
    worst20 = worst(20)
    return {"ticker_norm": ticker, "price_history_available": True, "latest_price_date_used": str(hist["date"].max()), "trailing_20d_return": trailing(20), "trailing_60d_return": trailing(60), "trailing_volatility_proxy": float(ret.tail(60).std()) if len(ret.dropna()) else None, "worst_rolling_5d_return": worst(5), "worst_rolling_10d_return": worst(10), "worst_rolling_20d_return": worst20, "max_drawdown_proxy": float(dd.min()) if len(dd) else None, "left_tail_warning_flag": bool(worst20 is not None and worst20 <= -0.20)}


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_status = git_status()
    protected = [p for p in [A1_SOURCE, E_SOURCE, ALIGNMENT_SUMMARY, TOP20_OVERLAP, TOP50_OVERLAP, TOP20_ENTRIES, TOP50_ENTRIES, CONTRIB, OVERLAY_SUMMARY, PRICE_PANEL] if p.is_file()]
    baseline_hashes = {rel(p): sha256(p) for p in protected}
    warnings = []
    if not A1_SOURCE.is_file() or not E_SOURCE.is_file():
        summary = {"stage": STAGE, "FINAL_STATUS": "BLOCKED_V21_137_E_R1_OR_A1_SOURCE_MISSING", "DECISION": "E_R1_RISK_DECOMPOSITION_BLOCKED_MISSING_SOURCE", "official_adoption_allowed": False, "broker_action_allowed": False, "research_only": True, "E_adoption_allowed": False, "protected_outputs_modified": False}
        write_json(OUT / "e_r1_risk_decomposition_summary.json", summary)
        return summary
    align = load_json(ALIGNMENT_SUMMARY); ranking_date = str(align.get("ranking_date", "2026-06-26"))
    a1 = pd.read_csv(A1_SOURCE, low_memory=False); a1["ticker_norm"] = a1["ticker"].map(ticker_norm)
    e = pd.read_csv(E_SOURCE, low_memory=False); e["ticker_norm"] = e["ticker_norm"].map(ticker_norm)
    metadata, metadata_source, meta_warn = load_metadata(); warnings.extend(meta_warn)
    repeated, repeated_source, repeated_available, repeated_warn = load_repeated(); warnings.extend(repeated_warn)
    buckets = {"top20": 20, "top50": 50}
    conc_metrics = []; exposure_rows = {"top20": [], "top50": []}
    selected: dict[tuple[str, str], pd.DataFrame] = {}
    for strategy, frame in [("A1", a1.rename(columns={"rank": "rank"})), ("E_R1", e)]:
        for bucket, n in buckets.items():
            sel = frame.sort_values(["rank", "ticker_norm"]).head(n).copy()
            selected[(strategy, bucket)] = sel
            metric, rows = concentration(strategy, bucket, sel, metadata)
            conc_metrics.append(metric); exposure_rows[bucket].extend(rows)
    conc_df = pd.DataFrame(conc_metrics)
    deltas = []
    for bucket in buckets:
        a = conc_df[(conc_df["strategy"].eq("A1")) & (conc_df["bucket"].eq(bucket))].iloc[0]
        er = conc_df[(conc_df["strategy"].eq("E_R1")) & (conc_df["bucket"].eq(bucket))].iloc[0]
        row = {"bucket": bucket}
        for col in ["top_sector_weight", "top_industry_weight", "unique_sectors", "unique_industries", "sector_hhi", "industry_hhi", "metadata_coverage_ratio"]:
            row[f"A1_{col}"] = a[col]; row[f"E_R1_{col}"] = er[col]; row[f"delta_E_R1_minus_A1_{col}"] = er[col] - a[col]
        deltas.append(row)
    if any(row["A1_metadata_coverage_ratio"] < 0.95 or row["E_R1_metadata_coverage_ratio"] < 0.95 for row in deltas):
        warnings.append("PARTIAL_OR_MISSING_METADATA_COVERAGE")
    write_csv(OUT / "e_r1_vs_a1_concentration_comparison.csv", deltas)
    write_csv(OUT / "e_r1_sector_industry_exposure_top20.csv", exposure_rows["top20"])
    write_csv(OUT / "e_r1_sector_industry_exposure_top50.csv", exposure_rows["top50"])
    tickers = set().union(*[set(df["ticker_norm"]) for df in selected.values()])
    prices, price_warn = load_prices(tickers, ranking_date); warnings.extend(price_warn)
    proxy_rows = [risk_proxy(t, prices.get(t, pd.DataFrame()), ranking_date) for t in sorted(tickers)]
    proxy = pd.DataFrame(proxy_rows)
    proxy.to_csv(OUT / "e_r1_ticker_left_tail_proxy.csv", index=False)
    contrib = pd.read_csv(CONTRIB, low_memory=False) if CONTRIB.is_file() else e.copy()
    entry20 = pd.read_csv(TOP20_ENTRIES, keep_default_na=False) if TOP20_ENTRIES.is_file() else pd.DataFrame(columns=["change_type","ticker_norm"])
    entry50 = pd.read_csv(TOP50_ENTRIES, keep_default_na=False) if TOP50_ENTRIES.is_file() else pd.DataFrame(columns=["change_type","ticker_norm"])
    def attribution(entries: pd.DataFrame, bucket: str) -> list[dict[str, Any]]:
        rows = []
        ranks = a1[["ticker_norm", "rank"]].rename(columns={"rank": "A1_rank"}).merge(e[["ticker_norm", "rank"]].rename(columns={"rank": "E_R1_rank"}), on="ticker_norm", how="outer")
        for rec in entries.to_dict("records"):
            t = ticker_norm(rec["ticker_norm"]); meta = metadata.get(t, {"sector": "UNKNOWN", "industry": "UNKNOWN"})
            c = contrib[contrib["ticker_norm"].eq(t)].head(1).to_dict("records")
            p = proxy[proxy["ticker_norm"].eq(t)].head(1).to_dict("records")
            r = ranks[ranks["ticker_norm"].eq(t)].head(1).to_dict("records")
            row = {"ticker_norm": t, "action": rec["change_type"], "bucket": bucket, **(r[0] if r else {}), **meta, **(c[0] if c else {}), **(p[0] if p else {}), "repeated_loser_flag": t in repeated, "data_quality_flag": "MISSING_PRICE" if not p or not p[0].get("price_history_available") else "", "left_tail_warning_flag": bool(p and p[0].get("left_tail_warning_flag"))}
            rows.append(row)
        return rows
    write_csv(OUT / "e_r1_top20_entry_exit_risk_attribution.csv", attribution(entry20, "top20"))
    write_csv(OUT / "e_r1_top50_entry_exit_risk_attribution.csv", attribution(entry50, "top50"))
    left_rows = []
    for bucket in buckets:
        for strategy in ["A1", "E_R1"]:
            names = set(selected[(strategy, bucket)]["ticker_norm"])
            sub = proxy[proxy["ticker_norm"].isin(names)]
            left_rows.append({"strategy": strategy, "bucket": bucket, "average_trailing_volatility": sub["trailing_volatility_proxy"].mean(), "median_trailing_volatility": sub["trailing_volatility_proxy"].median(), "worst_trailing_5d_return": sub["worst_rolling_5d_return"].min(), "worst_trailing_10d_return": sub["worst_rolling_10d_return"].min(), "worst_trailing_20d_return": sub["worst_rolling_20d_return"].min(), "average_max_drawdown_proxy": sub["max_drawdown_proxy"].mean(), "median_max_drawdown_proxy": sub["max_drawdown_proxy"].median(), "left_tail_threshold_breach_count": int(sub["left_tail_warning_flag"].sum())})
    left_df = pd.DataFrame(left_rows)
    deltas_left = []
    for bucket in buckets:
        a = left_df[(left_df["strategy"].eq("A1")) & (left_df["bucket"].eq(bucket))].iloc[0]
        er = left_df[(left_df["strategy"].eq("E_R1")) & (left_df["bucket"].eq(bucket))].iloc[0]
        row = {"bucket": bucket}
        for col in left_df.columns:
            if col not in {"strategy", "bucket"}:
                row[f"A1_{col}"] = a[col]; row[f"E_R1_{col}"] = er[col]; row[f"delta_E_R1_minus_A1_{col}"] = er[col] - a[col]
        deltas_left.append(row)
    write_csv(OUT / "e_r1_vs_a1_left_tail_proxy_comparison.csv", deltas_left)
    rep_rows = []
    for bucket in buckets:
        for strategy in ["A1", "E_R1"]:
            names = set(selected[(strategy, bucket)]["ticker_norm"])
            overlap = sorted(names & repeated)
            rep_rows.append({"strategy": strategy, "bucket": bucket, "repeated_loser_source_available": repeated_available, "repeated_loser_source_path": repeated_source, "repeated_loser_ticker_count": len(overlap), "repeated_loser_weight": len(overlap) / len(names), "repeated_loser_overlap": "|".join(overlap), "entries_that_are_repeated_losers": "|".join(sorted((set(entry20[entry20["change_type"].eq("ENTRY")]["ticker_norm"]) if bucket == "top20" else set(entry50[entry50["change_type"].eq("ENTRY")]["ticker_norm"])) & repeated)), "exits_that_are_repeated_losers": "|".join(sorted((set(entry20[entry20["change_type"].eq("EXIT")]["ticker_norm"]) if bucket == "top20" else set(entry50[entry50["change_type"].eq("EXIT")]["ticker_norm"])) & repeated))})
    write_csv(OUT / "e_r1_vs_a1_repeated_loser_comparison.csv", rep_rows)
    dq_rows = []
    for bucket in buckets:
        for strategy in ["A1", "E_R1"]:
            names = set(selected[(strategy, bucket)]["ticker_norm"])
            subp = proxy[proxy["ticker_norm"].isin(names)]
            meta_missing = sum(1 for t in names if metadata.get(t, {"sector": "UNKNOWN"})["sector"] == "UNKNOWN")
            dq_rows.append({"strategy": strategy, "bucket": bucket, "missing_price_count": int((~subp["price_history_available"].astype(bool)).sum()), "stale_price_count": int((subp["latest_price_date_used"].astype(str) < ranking_date).sum()), "insufficient_history_count": int((subp["price_history_available"].astype(bool) & subp["trailing_60d_return"].isna()).sum()), "metadata_missing_count": meta_missing, "warning_ticker_count": int((~subp["price_history_available"].astype(bool)).sum()) + meta_missing, "data_quality_coverage_ratio": 1 - (meta_missing / len(names))})
    write_csv(OUT / "e_r1_vs_a1_data_quality_comparison.csv", dq_rows)
    conc_worse = any(r["delta_E_R1_minus_A1_top_sector_weight"] > 0.10 or r["delta_E_R1_minus_A1_top_industry_weight"] > 0.10 for r in deltas)
    left_worse = any((r["delta_E_R1_minus_A1_left_tail_threshold_breach_count"] > 2) or (r["delta_E_R1_minus_A1_average_max_drawdown_proxy"] < -0.05) for r in deltas_left)
    has_warn = bool(warnings)
    leakage = any(any(tok in col.lower() for tok in ["forward_return", "future_label", "outcome"]) for col in proxy.columns)
    if leakage:
        status = "FAIL_V21_137_E_R1_LEAKAGE_RISK"; decision = "E_R1_RISK_DECOMPOSITION_REJECTED_LEAKAGE_RISK"
    elif conc_worse or left_worse:
        status = "WARN_V21_137_E_R1_RISK_WORSE_THAN_A1"; decision = "E_R1_RISK_PROFILE_WORSE_THAN_A1_REVIEW_REQUIRED"
    elif has_warn:
        status = "PARTIAL_PASS_V21_137_E_R1_RISK_PROFILE_ACCEPTABLE_WITH_WARN"; decision = "E_R1_RISK_PROFILE_ACCEPTABLE_WITH_WARN_WAIT_MATURITY"
    else:
        status = "PASS_V21_137_E_R1_RISK_PROFILE_ACCEPTABLE"; decision = "E_R1_RISK_PROFILE_ACCEPTABLE_WAIT_MATURITY"
    post_hashes = {rel(p): sha256(p) for p in protected}
    prot_mod = baseline_hashes != post_hashes or protected_modified(git_status(), baseline_status)
    summary = {"stage": STAGE, "FINAL_STATUS": status, "DECISION": decision, "ranking_date": ranking_date, "A1_source_path": rel(A1_SOURCE), "E_R1_source_path": rel(E_SOURCE), "top20_entries": "|".join(entry20[entry20["change_type"].eq("ENTRY")]["ticker_norm"]), "top20_exits": "|".join(entry20[entry20["change_type"].eq("EXIT")]["ticker_norm"]), "metadata_source": metadata_source, "metadata_warning": any("METADATA" in warning for warning in warnings), "repeated_loser_source_available": repeated_available, "repeated_loser_source_path": repeated_source, "risk_verdict": decision, "warnings": "|".join(warnings) if warnings else "none", "protected_outputs_modified": bool(prot_mod), "official_adoption_allowed": False, "broker_action_allowed": False, "research_only": True, "E_adoption_allowed": False, "report_path": rel(OUT / "V21.137_E_R1_RISK_DECOMPOSITION_VS_A1_report.txt")}
    write_json(OUT / "e_r1_risk_decomposition_summary.json", summary)
    report = [STAGE, f"FINAL_STATUS={status}", f"DECISION={decision}", f"ranking_date={ranking_date}", f"A1_source_path={rel(A1_SOURCE)}", f"E_R1_source_path={rel(E_SOURCE)}", f"E_R1_Top20_entries={summary['top20_entries']}", f"E_R1_Top20_exits={summary['top20_exits']}", "sector concentration comparison", pd.DataFrame(deltas).to_csv(index=False).strip(), "left-tail proxy comparison", pd.DataFrame(deltas_left).to_csv(index=False).strip(), "repeated-loser comparison", pd.DataFrame(rep_rows).to_csv(index=False).strip(), "data quality comparison", pd.DataFrame(dq_rows).to_csv(index=False).strip(), f"risk_verdict={decision}", f"warnings={summary['warnings']}", "protected_outputs_modified=false", "official_adoption_allowed=false", "broker_action_allowed=false", "research_only=true", "E_adoption_allowed=false"]
    (OUT / "V21.137_E_R1_RISK_DECOMPOSITION_VS_A1_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(STAGE); print(f"FINAL_STATUS={status}"); print(f"DECISION={decision}"); print(f"report_path={summary['report_path']}"); print(f"E_R1_Top20_entries={summary['top20_entries']}"); print(f"E_R1_Top20_exits={summary['top20_exits']}"); print("concentration_summary=" + pd.DataFrame(deltas).to_json(orient="records")); print("left_tail_summary=" + pd.DataFrame(deltas_left).to_json(orient="records")); print("repeated_loser_summary=" + pd.DataFrame(rep_rows).to_json(orient="records")); print("data_quality_summary=" + pd.DataFrame(dq_rows).to_json(orient="records")); print(f"warnings={summary['warnings']}")
    return summary


if __name__ == "__main__":
    run()
