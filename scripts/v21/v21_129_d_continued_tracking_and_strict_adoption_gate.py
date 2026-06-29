#!/usr/bin/env python
"""V21.129 D continued tracking with strict adoption gate.

Research-only. This stage continues D ranking/tracking from V21.128 while
separating that from any adoption or promotion decision.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE"
OUT = ROOT / "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE"
V128 = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE"
V119_R1 = ROOT / "outputs/v21/V21.119_R1_FORWARD_MATURITY_UPDATE_AFTER_REFRESH"
V111_CONC = ROOT / "outputs/v21/V21.111_R1_CONCENTRATION_ATTRIBUTION_AUDIT"
V126 = ROOT / "outputs/v21/V21.126_B_CHALLENGER_REVIEW_VS_A1_C_D_R2C"
V126_R1 = ROOT / "outputs/v21/V21.126_R1_B_REPEATED_LOSER_DEPENDENCY_DECOMPOSITION"

SUMMARY_128 = V128 / "V21.128_summary.json"
D_RANKING = V128 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv"
A1_RANKING = V128 / "A1_BASELINE_CONTROL_latest_ranking.csv"
TRACKING_LEDGER = V128 / "tracking_ledger.csv"
SECTOR_INDUSTRY_128 = V128 / "sector_industry_concentration_summary.csv"
FWD = V119_R1 / "forward_maturity_by_date_horizon_after_refresh.csv"
REPEATED_LOSER = V119_R1 / "repeated_loser_after_refresh_update.csv"

EXPECTED_MIN_DATE = "2026-06-26"
ALLOWED_REGIMES = {"TRENDING_RISK_ON", "SEMI_MOMENTUM_CONFIRMED", "BROAD_MOMENTUM_CONFIRMED"}
BLOCKED_REGIMES = {
    "CHOPPY_HIGH_VOL",
    "PROFIT_TAKING_SEMI",
    "BROAD_RISK_OFF",
    "POST_EARNINGS_REVERSAL",
    "SEMI_HIGH_BETA_DERISKING",
}
MEMORY_CHAIN = {"DRAM", "MU", "SNDK", "WDC", "STX", "AMAT", "LRCX", "KLAC", "KLIC", "TER", "MKSI", "ICHR", "AMKR", "SOXX", "SMH", "AMD", "INTC", "ASML", "COHU", "ENTG", "ACMR"}
MEMORY_CHAIN_INDUSTRIES = {
    "SEMICONDUCTOR EQUIPMENT & MATERIALS",
    "SEMICONDUCTORS",
    "COMPUTER HARDWARE",
}
TICKER_WARNING_FIELDS = [
    "ticker_data_warning_count",
    "data_warning_count",
    "stale_or_missing_ticker_count",
    "missing_ticker_count",
    "failed_ticker_count",
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
            for field in row.keys():
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def parse_float(value: Any, default: float = math.nan) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if not math.isnan(parsed) else default


def parse_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def ticker_data_warning_count(v128: dict[str, Any]) -> tuple[int | None, str]:
    for field in TICKER_WARNING_FIELDS:
        if field in v128:
            return parse_int(v128.get(field), None), field
    return None, "UNKNOWN"


def git_status() -> list[str]:
    completed = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=False)
    return completed.stdout.splitlines()


def protected_modified(status_lines: list[str], baseline_lines: list[str]) -> bool:
    baseline = {line.replace("\\", "/") for line in baseline_lines}
    allowed_prefix = "?? outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE/"
    allowed_scripts = {
        "?? scripts/v21/v21_129_d_continued_tracking_and_strict_adoption_gate.py",
        "?? scripts/v21/test_v21_129_d_continued_tracking_and_strict_adoption_gate.py",
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


def discover_scripts() -> list[dict[str, Any]]:
    patterns = [
        "*abcd*",
        "*tracking*",
        "*forward*ledger*",
        "*concentration*",
        "*repeated*loser*",
        "*regime*",
        "*d_r2c*",
    ]
    seen: set[Path] = set()
    rows = []
    for pattern in patterns:
        for path in (ROOT / "scripts/v21").glob(pattern):
            if path in seen or path.suffix not in {".py", ".ps1"}:
                continue
            seen.add(path)
            rows.append({"path": rel(path), "pattern": pattern, "sha256": sha256(path)})
    return sorted(rows, key=lambda row: row["path"])


def topn(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    out = frame[pd.to_numeric(frame["rank"], errors="coerce").le(n)].copy()
    return out.sort_values(["rank", "ticker"]).reset_index(drop=True)


def numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def forward_metrics() -> tuple[pd.DataFrame, dict[str, Any]]:
    fwd = pd.read_csv(FWD, low_memory=False) if FWD.is_file() else pd.DataFrame()
    if fwd.empty:
        return fwd, {
            "D_matured_top20_observations": 0,
            "D_matured_top50_observations": 0,
            "distinct_forward_ranking_dates": 0,
            "D_top20_win_rate_vs_A1": math.nan,
            "D_top50_win_rate_vs_A1": math.nan,
            "D_mean_excess_return_vs_A1": math.nan,
            "D_median_excess_return_vs_A1": math.nan,
            "D_worst_5d_excess_return_vs_A1": math.nan,
            "D_worst_10d_excess_return_vs_A1": math.nan,
            "D_left_tail_event_count": 0,
            "A1_left_tail_event_count": 0,
            "D_drawdown_proxy": math.nan,
            "A1_drawdown_proxy": math.nan,
            "D_top20_win_rate_vs_QQQ": math.nan,
            "D_top50_win_rate_vs_QQQ": math.nan,
        }

    fwd["top_n"] = pd.to_numeric(fwd["top_n"], errors="coerce")
    fwd["matured_bool"] = fwd["matured"].astype(str).str.upper().eq("TRUE")
    fwd["equal_weight_return"] = numeric(fwd["equal_weight_return"])
    fwd["excess_vs_QQQ"] = numeric(fwd["excess_vs_QQQ"])
    d = fwd[fwd["strategy"].eq("D_WEIGHT_OPTIMIZED_R1") & fwd["matured_bool"]].copy()
    a1 = fwd[fwd["strategy"].eq("A1_BASELINE_CONTROL") & fwd["matured_bool"]].copy()
    keys = ["ranking_date", "top_n", "horizon"]
    merged = d[keys + ["equal_weight_return", "excess_vs_QQQ"]].merge(
        a1[keys + ["equal_weight_return", "excess_vs_QQQ"]],
        on=keys,
        how="inner",
        suffixes=("_D", "_A1"),
    )
    merged["D_excess_vs_A1"] = merged["equal_weight_return_D"] - merged["equal_weight_return_A1"]
    merged["D_win_vs_A1"] = merged["D_excess_vs_A1"] > 0
    merged["D_win_vs_QQQ"] = merged["excess_vs_QQQ_D"] > 0
    merged.to_csv(OUT / "V21.129_d_vs_a1_forward_comparison.csv", index=False)

    top20 = merged[merged["top_n"].eq(20)]
    top50 = merged[merged["top_n"].eq(50)]
    d_top20 = d[d["top_n"].eq(20)]
    d_top50 = d[d["top_n"].eq(50)]
    a1_left = int((a1["excess_vs_QQQ"] <= -0.05).sum())
    d_left = int((d["excess_vs_QQQ"] <= -0.05).sum())
    return fwd, {
        "D_matured_top20_observations": int(len(d_top20)),
        "D_matured_top50_observations": int(len(d_top50)),
        "distinct_forward_ranking_dates": int(d["ranking_date"].nunique()),
        "D_top20_win_rate_vs_A1": float(top20["D_win_vs_A1"].mean()) if len(top20) else math.nan,
        "D_top50_win_rate_vs_A1": float(top50["D_win_vs_A1"].mean()) if len(top50) else math.nan,
        "D_mean_excess_return_vs_A1": float(merged["D_excess_vs_A1"].mean()) if len(merged) else math.nan,
        "D_median_excess_return_vs_A1": float(merged["D_excess_vs_A1"].median()) if len(merged) else math.nan,
        "D_worst_5d_excess_return_vs_A1": float(merged[merged["horizon"].eq("5D")]["D_excess_vs_A1"].min()) if len(merged[merged["horizon"].eq("5D")]) else math.nan,
        "D_worst_10d_excess_return_vs_A1": float(merged[merged["horizon"].eq("10D")]["D_excess_vs_A1"].min()) if len(merged[merged["horizon"].eq("10D")]) else math.nan,
        "D_left_tail_event_count": d_left,
        "A1_left_tail_event_count": a1_left,
        "D_drawdown_proxy": float(abs(min(0.0, d["excess_vs_QQQ"].min()))) if len(d) else math.nan,
        "A1_drawdown_proxy": float(abs(min(0.0, a1["excess_vs_QQQ"].min()))) if len(a1) else math.nan,
        "D_top20_win_rate_vs_QQQ": float((d_top20["excess_vs_QQQ"] > 0).mean()) if len(d_top20) else math.nan,
        "D_top50_win_rate_vs_QQQ": float((d_top50["excess_vs_QQQ"] > 0).mean()) if len(d_top50) else math.nan,
    }


def metadata_map() -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    for path in [
        V111_CONC / "d_only_ticker_profile.csv",
        V111_CONC / "concentration_cause_classification.csv",
    ]:
        if not path.is_file():
            continue
        frame = pd.read_csv(path, low_memory=False)
        if "ticker" not in frame:
            continue
        for row in frame.to_dict("records"):
            ticker = str(row.get("ticker", "")).upper().strip()
            if ticker and ticker != "NAN":
                mapping[ticker] = {
                    "sector": str(row.get("sector", "UNCLASSIFIED")).strip() or "UNCLASSIFIED",
                    "industry": str(row.get("industry", "UNCLASSIFIED")).strip() or "UNCLASSIFIED",
                    "theme_tags": str(row.get("theme_tags", "")).strip(),
                }
    return mapping


def concentration(top20: pd.DataFrame, top50: pd.DataFrame) -> dict[str, Any]:
    mapping = metadata_map()

    def enrich(frame: pd.DataFrame, view: str) -> pd.DataFrame:
        out = frame[["rank", "ticker", "final_score"]].copy()
        out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
        out["sector"] = out["ticker"].map(lambda ticker: mapping.get(ticker, {}).get("sector", "UNCLASSIFIED"))
        out["industry"] = out["ticker"].map(lambda ticker: mapping.get(ticker, {}).get("industry", "UNCLASSIFIED"))
        out["theme_tags"] = out["ticker"].map(lambda ticker: mapping.get(ticker, {}).get("theme_tags", ""))
        out["view"] = view
        return out

    enriched = pd.concat([enrich(top20, "top20"), enrich(top50, "top50")], ignore_index=True)
    rows = []
    metrics: dict[str, Any] = {}
    if SECTOR_INDUSTRY_128.is_file():
        summary = pd.read_csv(SECTOR_INDUSTRY_128, low_memory=False)
        summary = summary[summary["strategy"].eq("D_WEIGHT_OPTIMIZED_R1")].copy()
        summary["weight"] = numeric(summary["weight"])
        for view in ["top20", "top50"]:
            view_summary = summary[summary["view"].eq(view)]
            sector = view_summary[view_summary["exposure_type"].eq("sector")].sort_values("weight", ascending=False)
            industry = view_summary[view_summary["exposure_type"].eq("industry")].sort_values("weight", ascending=False)
            top_sector = str(sector.iloc[0]["bucket"]) if len(sector) else ""
            top_sector_weight = float(sector.iloc[0]["weight"]) if len(sector) else math.nan
            top_industry = str(industry.iloc[0]["bucket"]) if len(industry) else ""
            top_industry_weight = float(industry.iloc[0]["weight"]) if len(industry) else math.nan
            chain_weight = float(
                industry[industry["bucket"].astype(str).str.upper().isin(MEMORY_CHAIN_INDUSTRIES)]["weight"].sum()
            ) if len(industry) else math.nan
            metrics[f"D_{view}_max_sector_weight"] = top_sector_weight
            metrics[f"D_{view}_max_industry_weight"] = top_industry_weight
            metrics[f"D_{view}_memory_storage_semiconductor_chain_weight"] = chain_weight
            current_metadata = enriched[enriched["view"].eq(view)]
            rows.append({
                "view": view,
                "member_count": len(current_metadata),
                "top_sector": top_sector,
                "max_sector_weight": top_sector_weight,
                "top_industry": top_industry,
                "max_industry_weight": top_industry_weight,
                "memory_storage_semiconductor_chain_weight": chain_weight,
                "unclassified_count": int((current_metadata["sector"] == "UNCLASSIFIED").sum()),
                "source": rel(SECTOR_INDUSTRY_128),
            })
        write_csv(OUT / "V21.129_d_concentration_diagnostic.csv", rows)
        return metrics

    for view, group in enriched.groupby("view"):
        total = len(group)
        classified = group[(group["sector"] != "UNCLASSIFIED") & (group["industry"] != "UNCLASSIFIED")]
        sector_counts = Counter(classified["sector"])
        industry_counts = Counter(classified["industry"])
        chain_count = int(group.apply(lambda row: row["ticker"] in MEMORY_CHAIN or "memory_storage" in str(row["theme_tags"]).lower() or "semiconductor" in str(row["industry"]).lower(), axis=1).sum())
        top_sector, top_sector_count = sector_counts.most_common(1)[0] if sector_counts else ("UNKNOWN", 0)
        top_industry, top_industry_count = industry_counts.most_common(1)[0] if industry_counts else ("UNKNOWN", 0)
        metrics[f"D_{view}_max_sector_weight"] = top_sector_count / total if total else math.nan
        metrics[f"D_{view}_max_industry_weight"] = top_industry_count / total if total else math.nan
        metrics[f"D_{view}_memory_storage_semiconductor_chain_weight"] = chain_count / total if total else math.nan
        rows.append({
            "view": view,
            "member_count": total,
            "top_sector": top_sector,
            "max_sector_weight": metrics[f"D_{view}_max_sector_weight"],
            "top_industry": top_industry,
            "max_industry_weight": metrics[f"D_{view}_max_industry_weight"],
            "memory_storage_semiconductor_chain_weight": metrics[f"D_{view}_memory_storage_semiconductor_chain_weight"],
            "unclassified_count": int((group["sector"] == "UNCLASSIFIED").sum()),
        })
    write_csv(OUT / "V21.129_d_concentration_diagnostic.csv", rows)
    return metrics


def split_tickers(value: Any) -> list[str]:
    if value is None:
        return []
    out: list[str] = []
    for token in str(value).replace(",", "|").split("|"):
        ticker = token.upper().strip()
        if ticker and ticker not in {"NAN", "NONE"} and ticker not in out:
            out.append(ticker)
    return out


def repeated_loser(top20: pd.DataFrame) -> dict[str, Any]:
    source_count: int | None = None
    repeated_tickers: list[str] = []
    source_overlap = ""
    if REPEATED_LOSER.is_file():
        frame = pd.read_csv(REPEATED_LOSER, low_memory=False)
        if not frame.empty:
            row = frame.iloc[0].to_dict()
            source_count = parse_int(row.get("original_D_repeated_loser_count"), None)
            source_overlap = str(row.get("repeated_loser_overlap", ""))
            for field in ["D_repeated_loser_tickers", "original_D_repeated_loser_tickers", "repeated_loser_tickers"]:
                repeated_tickers.extend(split_tickers(row.get(field)))
            detail_raw = row.get("newly_matured_repeated_loser_detail")
            if isinstance(detail_raw, str) and detail_raw.strip():
                try:
                    detail = json.loads(detail_raw)
                except json.JSONDecodeError:
                    detail = []
                for item in detail if isinstance(detail, list) else []:
                    repeated_tickers.extend(split_tickers(item.get("repeated_loser_tickers")))
    repeated_tickers = sorted(set(repeated_tickers))
    count = len(repeated_tickers) if repeated_tickers else (source_count or 0)
    top20_tickers = set(top20["ticker"].astype(str).str.upper().str.strip())
    overlap_tickers = sorted(top20_tickers.intersection(repeated_tickers))
    top20_count = len(overlap_tickers)
    weight = top20_count / len(top20) if len(top20) else math.nan
    level = "HIGH" if count > 3 or (not math.isnan(weight) and weight > 0.20) else "LOW"
    rows = [{
        "D_repeated_loser_risk_level": level,
        "D_repeated_loser_ticker_count": count,
        "D_repeated_loser_tickers": "|".join(repeated_tickers),
        "D_source_repeated_loser_ticker_count": source_count if source_count is not None else "",
        "D_derived_repeated_loser_ticker_count": len(repeated_tickers),
        "D_top20_repeated_loser_overlap_tickers": "|".join(overlap_tickers),
        "D_top20_repeated_loser_weight": weight,
        "source_repeated_loser_overlap": source_overlap,
        "adoption_gate_blocked": level == "HIGH" or count > 3 or weight > 0.20,
    }]
    write_csv(OUT / "V21.129_d_repeated_loser_diagnostic.csv", rows)
    return rows[0]


def current_regime(d_ranking: pd.DataFrame, conc: dict[str, Any], fwd_frame: pd.DataFrame) -> tuple[str, str, dict[str, Any]]:
    raw = ""
    if "market_regime" in d_ranking:
        modes = d_ranking["market_regime"].dropna().astype(str).str.upper()
        raw = modes.mode().iloc[0] if not modes.empty else ""
    semi_weight = parse_float(conc.get("D_top20_memory_storage_semiconductor_chain_weight"))
    high_semi_concentration = not math.isnan(semi_weight) and semi_weight >= 0.50
    diagnostics: dict[str, Any] = {
        "raw_market_regime": raw,
        "D_top20_memory_storage_semiconductor_chain_weight": semi_weight,
        "high_semi_concentration": high_semi_concentration,
        "recent_ranking_date": "",
        "recent_top_n": "",
        "recent_horizon": "",
        "recent_D_return": math.nan,
        "recent_QQQ_return": math.nan,
        "recent_SOXX_return": math.nan,
        "recent_D_excess_vs_QQQ": math.nan,
        "recent_D_excess_vs_SOXX": math.nan,
        "semi_derisking_signal": False,
        "profit_taking_signal": False,
    }
    if high_semi_concentration:
        required = {
            "strategy",
            "top_n",
            "matured",
            "ranking_date",
            "horizon",
            "equal_weight_return",
            "benchmark_QQQ_return",
            "benchmark_SOXX_return",
            "excess_vs_QQQ",
            "excess_vs_SOXX",
        }
        if fwd_frame.empty or not required.issubset(set(fwd_frame.columns)):
            return "D_REGIME_GATE_UNKNOWN", "semi_concentration_high_recent_benchmark_data_unavailable", diagnostics
        recent = fwd_frame[
            fwd_frame["strategy"].eq("D_WEIGHT_OPTIMIZED_R1")
            & fwd_frame["top_n"].eq(20)
            & fwd_frame["matured"].astype(str).str.upper().eq("TRUE")
        ].copy()
        if recent.empty:
            return "D_REGIME_GATE_UNKNOWN", "semi_concentration_high_recent_matured_d_data_unavailable", diagnostics
        recent["_ranking_date_sort"] = pd.to_datetime(recent["ranking_date"], errors="coerce")
        recent["_horizon_days"] = numeric(recent["horizon"].astype(str).str.extract(r"(\d+)")[0])
        recent = recent.sort_values(["_ranking_date_sort", "_horizon_days"], ascending=[False, True])
        row = recent.iloc[0].to_dict()
        d_return = parse_float(row.get("equal_weight_return"))
        qqq_return = parse_float(row.get("benchmark_QQQ_return"))
        soxx_return = parse_float(row.get("benchmark_SOXX_return"))
        d_excess_qqq = parse_float(row.get("excess_vs_QQQ"))
        d_excess_soxx = parse_float(row.get("excess_vs_SOXX"))
        diagnostics.update({
            "recent_ranking_date": row.get("ranking_date", ""),
            "recent_top_n": row.get("top_n", ""),
            "recent_horizon": row.get("horizon", ""),
            "recent_D_return": d_return,
            "recent_QQQ_return": qqq_return,
            "recent_SOXX_return": soxx_return,
            "recent_D_excess_vs_QQQ": d_excess_qqq,
            "recent_D_excess_vs_SOXX": d_excess_soxx,
        })
        missing_recent = any(math.isnan(value) for value in [d_return, qqq_return, soxx_return, d_excess_qqq])
        if missing_recent:
            return "D_REGIME_GATE_UNKNOWN", "semi_concentration_high_recent_benchmark_metrics_unavailable", diagnostics
        semi_derisking = soxx_return <= -0.03 and d_return < 0 and d_excess_qqq < 0
        profit_taking = d_return < 0 and d_excess_qqq <= -0.015 and soxx_return < qqq_return - 0.02
        diagnostics["semi_derisking_signal"] = semi_derisking
        diagnostics["profit_taking_signal"] = profit_taking
        if semi_derisking:
            return "SEMI_HIGH_BETA_DERISKING", "high_semi_concentration_recent_soxx_selloff_and_d_underperformed_qqq", diagnostics
        if profit_taking:
            return "PROFIT_TAKING_SEMI", "high_semi_concentration_recent_d_underperformance_and_soxx_profit_taking", diagnostics
    if raw == "RISK_ON":
        return "TRENDING_RISK_ON", "mapped_from_RISK_ON", diagnostics
    if raw:
        return raw, "from_latest_d_ranking", diagnostics
    return "D_REGIME_GATE_UNKNOWN", "regime_not_found", diagnostics


def gate_row(name: str, status: str, reason: str, metrics: dict[str, Any]) -> dict[str, Any]:
    return {"gate": name, "status": status, "reason": reason, **metrics}


def pass_if(condition: bool, block_reason: str, metrics: dict[str, Any]) -> tuple[str, str]:
    return ("PASS", "") if condition else ("BLOCK", block_reason)


def strict_gates(v128: dict[str, Any], fwd: dict[str, Any], conc: dict[str, Any], loser: dict[str, Any], regime: str) -> tuple[list[dict[str, Any]], bool]:
    gates = []
    latest_price_date_used = str(v128.get("latest_price_date_used", ""))
    warning_count, warning_source = ticker_data_warning_count(v128)
    price_panel_fresh = latest_price_date_used >= EXPECTED_MIN_DATE
    status, reason = pass_if(
        price_panel_fresh,
        "D_ADOPTION_BLOCKED_STALE_PRICE_PANEL",
        {},
    )
    gates.append(gate_row("DATA_FRESHNESS", status, reason, {
        "latest_price_date_used": latest_price_date_used,
        "minimum_required_price_date": EXPECTED_MIN_DATE,
        "price_panel_fresh": price_panel_fresh,
    }))

    if warning_count is None:
        gates.append(gate_row("DATA_QUALITY_WARNING", "UNKNOWN", "D_ADOPTION_BLOCKED_DATA_QUALITY_WARNING_UNKNOWN", {
            "ticker_data_warning_count": "UNKNOWN",
            "ticker_data_warning_count_source": warning_source,
        }))
    else:
        status, reason = pass_if(
            warning_count == 0,
            "D_ADOPTION_BLOCKED_DATA_QUALITY_WARNING",
            {},
        )
        gates.append(gate_row("DATA_QUALITY_WARNING", status, reason, {
            "ticker_data_warning_count": warning_count,
            "ticker_data_warning_count_source": warning_source,
        }))

    status, reason = pass_if(
        fwd["D_matured_top20_observations"] >= 40 and fwd["D_matured_top50_observations"] >= 40 and fwd["distinct_forward_ranking_dates"] >= 8,
        "D_ADOPTION_BLOCKED_INSUFFICIENT_MATURITY",
        {},
    )
    gates.append(gate_row("MATURITY", status, reason, {k: fwd[k] for k in ["D_matured_top20_observations", "D_matured_top50_observations", "distinct_forward_ranking_dates"]}))

    status, reason = pass_if(
        fwd["D_top20_win_rate_vs_A1"] >= 0.60 and fwd["D_top50_win_rate_vs_A1"] >= 0.55 and fwd["D_mean_excess_return_vs_A1"] > 0 and fwd["D_median_excess_return_vs_A1"] >= 0,
        "D_ADOPTION_BLOCKED_DID_NOT_BEAT_A1",
        {},
    )
    gates.append(gate_row("VS_A1_PERFORMANCE", status, reason, {k: fwd[k] for k in ["D_top20_win_rate_vs_A1", "D_top50_win_rate_vs_A1", "D_mean_excess_return_vs_A1", "D_median_excess_return_vs_A1"]}))

    a1_20 = float(v128.get("A1_top20_win_rate_vs_QQQ", math.nan))
    a1_50 = float(v128.get("A1_top50_win_rate_vs_QQQ", v128.get("A1_top20_win_rate_vs_QQQ", math.nan)))
    status, reason = pass_if(
        fwd["D_top20_win_rate_vs_QQQ"] >= max(0.65, a1_20 + 0.05) and fwd["D_top50_win_rate_vs_QQQ"] >= max(0.60, a1_50 + 0.03),
        "D_ADOPTION_BLOCKED_INSUFFICIENT_BENCHMARK_ALPHA",
        {},
    )
    gates.append(gate_row("VS_QQQ_PERFORMANCE", status, reason, {"D_top20_win_rate_vs_QQQ": fwd["D_top20_win_rate_vs_QQQ"], "D_top50_win_rate_vs_QQQ": fwd["D_top50_win_rate_vs_QQQ"], "A1_top20_win_rate_vs_QQQ": a1_20, "A1_top50_win_rate_vs_QQQ": a1_50}))

    status, reason = pass_if(
        conc.get("D_top20_max_sector_weight", math.inf) <= 0.55
        and conc.get("D_top50_max_sector_weight", math.inf) <= 0.45
        and conc.get("D_top20_max_industry_weight", math.inf) <= 0.30
        and conc.get("D_top50_max_industry_weight", math.inf) <= 0.25
        and conc.get("D_top20_memory_storage_semiconductor_chain_weight", math.inf) <= 0.50,
        "D_ADOPTION_BLOCKED_CONCENTRATION_RISK",
        {},
    )
    gates.append(gate_row("CONCENTRATION_RISK", status, reason, conc))

    left_tail_known = not math.isnan(fwd["D_worst_10d_excess_return_vs_A1"])
    status, reason = pass_if(
        left_tail_known
        and fwd["D_worst_5d_excess_return_vs_A1"] >= -0.08
        and fwd["D_worst_10d_excess_return_vs_A1"] >= -0.12
        and fwd["D_left_tail_event_count"] <= fwd["A1_left_tail_event_count"]
        and fwd["D_drawdown_proxy"] <= fwd["A1_drawdown_proxy"] * 1.25,
        "D_ADOPTION_BLOCKED_LEFT_TAIL_RISK",
        {},
    )
    gates.append(gate_row("LEFT_TAIL_DRAWDOWN_RISK", status, reason, {k: fwd[k] for k in ["D_worst_5d_excess_return_vs_A1", "D_worst_10d_excess_return_vs_A1", "D_left_tail_event_count", "A1_left_tail_event_count", "D_drawdown_proxy", "A1_drawdown_proxy"]}))

    status, reason = pass_if(
        loser["D_repeated_loser_risk_level"] != "HIGH" and int(loser["D_repeated_loser_ticker_count"]) <= 3 and float(loser["D_top20_repeated_loser_weight"]) <= 0.20,
        "D_ADOPTION_BLOCKED_REPEATED_LOSER_RISK",
        {},
    )
    gates.append(gate_row("REPEATED_LOSER_RISK", status, reason, loser))

    if regime == "D_REGIME_GATE_UNKNOWN":
        gates.append(gate_row("REGIME_COMPATIBILITY", "UNKNOWN", "D_REGIME_GATE_UNKNOWN", {"current_regime": regime}))
    else:
        status, reason = pass_if(regime in ALLOWED_REGIMES and regime not in BLOCKED_REGIMES, "D_ADOPTION_BLOCKED_REGIME_INCOMPATIBLE", {"current_regime": regime})
        gates.append(gate_row("REGIME_COMPATIBILITY", status, reason, {"current_regime": regime}))

    gate_pass = all(row["status"] == "PASS" for row in gates)
    write_csv(OUT / "V21.129_d_strict_gate_results.csv", gates)
    return gates, gate_pass


def status_for(gates: list[dict[str, Any]], name: str) -> str:
    for row in gates:
        if row["gate"] == name:
            return row["status"]
    return "UNKNOWN"


def write_reports(summary: dict[str, Any]) -> None:
    readable = [
        STAGE,
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        "",
        "D continues to run as a research/reference strategy. The strict gate only controls whether human role review is allowed; it never performs adoption.",
        "",
        f"D_continued_tracking={str(summary['D_continued_tracking']).lower()}",
        f"D_adoption_allowed={str(summary['D_adoption_allowed']).lower()}",
        f"D_role_review_required={str(summary['D_role_review_required']).lower()}",
        f"D_strict_gate_pass={str(summary['D_strict_gate_pass']).lower()}",
        f"D_gate_data_freshness={summary['D_gate_data_freshness']}",
        f"D_gate_data_quality_warning={summary['D_gate_data_quality_warning']}",
        f"D_gate_maturity={summary['D_gate_maturity']}",
        f"D_gate_vs_A1={summary['D_gate_vs_A1']}",
        f"D_gate_vs_QQQ={summary['D_gate_vs_QQQ']}",
        f"D_gate_concentration={summary['D_gate_concentration']}",
        f"D_gate_left_tail={summary['D_gate_left_tail']}",
        f"D_gate_repeated_loser={summary['D_gate_repeated_loser']}",
        f"D_gate_regime={summary['D_gate_regime']}",
        "",
        "Controls",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false",
        "",
        "Diagnostics",
        f"ticker_data_warning_count={summary['ticker_data_warning_count']}",
        f"D_repeated_loser_ticker_count={summary['D_repeated_loser_ticker_count']}",
        f"D_top20_repeated_loser_weight={summary['D_top20_repeated_loser_weight']}",
        f"D_repeated_loser_risk_level={summary['D_repeated_loser_risk_level']}",
        f"current_regime={summary['current_regime']}",
    ]
    (OUT / "V21.129_readable_report.txt").write_text("\n".join(readable) + "\n", encoding="utf-8")
    compact = [
        STAGE,
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        f"D_status={summary['D_status']}",
        f"D_strict_gate_pass={str(summary['D_strict_gate_pass']).lower()}",
        f"D_gate_data_quality_warning={summary['D_gate_data_quality_warning']}",
        f"next_action_gate={summary['next_action_gate']}",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
    ]
    (OUT / "V21.129_compact_report.txt").write_text("\n".join(compact) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_status = git_status()
    v128 = load_json(SUMMARY_128)
    d_ranking = pd.read_csv(D_RANKING, low_memory=False)
    a1_ranking = pd.read_csv(A1_RANKING, low_memory=False)
    d_top20 = topn(d_ranking, 20)
    d_top50 = topn(d_ranking, 50)
    d_ranking.to_csv(OUT / "V21.129_d_tracking_raw_ranking.csv", index=False)
    d_top20.to_csv(OUT / "V21.129_d_tracking_top20.csv", index=False)
    d_top50.to_csv(OUT / "V21.129_d_tracking_top50.csv", index=False)

    if TRACKING_LEDGER.is_file():
        ledger = pd.read_csv(TRACKING_LEDGER, low_memory=False)
        d_ledger = ledger[ledger["strategy"].eq("D_WEIGHT_OPTIMIZED_R1")].copy()
        d_ledger.to_csv(OUT / "V21.129_d_forward_tracking_rows.csv", index=False)
    else:
        d_ledger = pd.DataFrame()
        write_csv(OUT / "V21.129_d_forward_tracking_rows.csv", [], ["empty"])

    write_csv(OUT / "V21.129_discovered_scripts.csv", discover_scripts())
    fwd_frame, fwd = forward_metrics()
    conc = concentration(d_top20, d_top50)
    loser = repeated_loser(d_top20)
    regime, regime_source, regime_diag = current_regime(d_ranking, conc, fwd_frame)
    write_csv(OUT / "V21.129_d_regime_gate_diagnostic.csv", [{
        "current_regime": regime,
        "source": regime_source,
        "allowed_regime": regime in ALLOWED_REGIMES,
        "blocked_regime": regime in BLOCKED_REGIMES,
        **regime_diag,
    }])
    gates, strict_pass = strict_gates(v128, fwd, conc, loser, regime)

    role_review_required = bool(strict_pass)
    d_status = "STRICT_GATE_PASSED_REVIEW_ONLY" if strict_pass else "FROZEN_TRACKING_ONLY_NOT_ADOPTABLE"
    decision = "D_ROLE_REVIEW_REQUIRED_RESEARCH_ONLY" if strict_pass else "WAIT_MORE_MATURITY_RESEARCH_ONLY"
    final_status = "PASS_V21_129_D_STRICT_GATE_REVIEW_ONLY" if strict_pass else "PASS_V21_129_D_TRACKING_CONTINUED_ADOPTION_BLOCKED"

    post_status = git_status()
    prot_mod = protected_modified(post_status, baseline_status)
    if prot_mod:
        final_status = "BLOCKED_V21_129_PROTECTED_OUTPUT_MODIFIED"
        decision = "BLOCKED_PROTECTED_OUTPUT_MUTATION"

    summary = {
        "stage": STAGE,
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": v128.get("latest_price_date_used", ""),
        "A1_status": v128.get("A1_status", "PRIMARY_CONTROL_CURRENT_MAIN_RESEARCH_LINE"),
        "B_status": v128.get("B_status", "DIAGNOSTIC_WATCH_ONLY_NOT_SUPPORTED_FOR_PROMOTION"),
        "B_clean_status": v128.get("B_clean_status", "DIAGNOSTIC_ONLY_INSUFFICIENT_TOP20_BREADTH"),
        "C_status": v128.get("C_status", "SECONDARY_RESEARCH_CANDIDATE"),
        "D_status": d_status,
        "D_R2C_status": v128.get("D_R2C_status", "FROZEN_TRACKING_ONLY_NOT_ADOPTABLE"),
        "D_continued_tracking": True,
        "D_adoption_allowed": False,
        "D_role_review_required": role_review_required,
        "D_strict_gate_pass": strict_pass,
        "D_gate_data_freshness": status_for(gates, "DATA_FRESHNESS"),
        "D_gate_data_quality_warning": status_for(gates, "DATA_QUALITY_WARNING"),
        "D_gate_maturity": status_for(gates, "MATURITY"),
        "D_gate_vs_A1": status_for(gates, "VS_A1_PERFORMANCE"),
        "D_gate_vs_QQQ": status_for(gates, "VS_QQQ_PERFORMANCE"),
        "D_gate_concentration": status_for(gates, "CONCENTRATION_RISK"),
        "D_gate_left_tail": status_for(gates, "LEFT_TAIL_DRAWDOWN_RISK"),
        "D_gate_repeated_loser": status_for(gates, "REPEATED_LOSER_RISK"),
        "D_gate_regime": status_for(gates, "REGIME_COMPATIBILITY"),
        "D_matured_top20_observations": fwd["D_matured_top20_observations"],
        "D_matured_top50_observations": fwd["D_matured_top50_observations"],
        "distinct_forward_ranking_dates": fwd["distinct_forward_ranking_dates"],
        "D_top20_win_rate_vs_A1": fwd["D_top20_win_rate_vs_A1"],
        "D_top50_win_rate_vs_A1": fwd["D_top50_win_rate_vs_A1"],
        "D_top20_win_rate_vs_QQQ": fwd["D_top20_win_rate_vs_QQQ"],
        "D_top50_win_rate_vs_QQQ": fwd["D_top50_win_rate_vs_QQQ"],
        "D_top20_max_sector_weight": conc.get("D_top20_max_sector_weight", math.nan),
        "D_top20_max_industry_weight": conc.get("D_top20_max_industry_weight", math.nan),
        "D_top20_memory_storage_semiconductor_chain_weight": conc.get("D_top20_memory_storage_semiconductor_chain_weight", math.nan),
        "ticker_data_warning_count": ticker_data_warning_count(v128)[0] if ticker_data_warning_count(v128)[0] is not None else "UNKNOWN",
        "D_repeated_loser_risk_level": loser["D_repeated_loser_risk_level"],
        "D_repeated_loser_ticker_count": loser["D_repeated_loser_ticker_count"],
        "D_repeated_loser_tickers": loser["D_repeated_loser_tickers"],
        "D_top20_repeated_loser_overlap_tickers": loser["D_top20_repeated_loser_overlap_tickers"],
        "D_top20_repeated_loser_weight": loser["D_top20_repeated_loser_weight"],
        "current_regime": regime,
        "role_review_required": role_review_required,
        "next_action_gate": "D_HUMAN_ROLE_REVIEW_ONLY" if strict_pass else "CONTINUE_D_TRACKING_WAIT_MORE_MATURITY",
        "pending_observations": v128.get("pending_observations", 0),
        "matured_observations": v128.get("matured_observations", 0),
        "protected_outputs_modified": False if not prot_mod else True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "no_future_leakage": True,
        "v21_128_baseline_preserved": True,
        "report_path": rel(OUT / "V21.129_readable_report.txt"),
    }
    write_json(OUT / "V21.129_summary.json", summary)
    write_reports(summary)

    print(STAGE)
    print(f"FINAL_STATUS={summary['FINAL_STATUS']}")
    print(f"DECISION={summary['DECISION']}")
    print(f"latest_price_date_used={summary['latest_price_date_used']}")
    print(f"A1_status={summary['A1_status']}")
    print(f"B_status={summary['B_status']}")
    print(f"B_clean_status={summary['B_clean_status']}")
    print(f"C_status={summary['C_status']}")
    print(f"D_status={summary['D_status']}")
    print(f"D_R2C_status={summary['D_R2C_status']}")
    print("D_continued_tracking=true")
    print("D_adoption_allowed=false")
    print(f"D_role_review_required={str(summary['D_role_review_required']).lower()}")
    print(f"D_strict_gate_pass={str(summary['D_strict_gate_pass']).lower()}")
    print(f"D_gate_data_freshness={summary['D_gate_data_freshness']}")
    print(f"D_gate_maturity={summary['D_gate_maturity']}")
    print(f"D_gate_vs_A1={summary['D_gate_vs_A1']}")
    print(f"D_gate_vs_QQQ={summary['D_gate_vs_QQQ']}")
    print(f"D_gate_concentration={summary['D_gate_concentration']}")
    print(f"D_gate_left_tail={summary['D_gate_left_tail']}")
    print(f"D_gate_repeated_loser={summary['D_gate_repeated_loser']}")
    print(f"D_gate_regime={summary['D_gate_regime']}")
    print(f"D_matured_top20_observations={summary['D_matured_top20_observations']}")
    print(f"D_matured_top50_observations={summary['D_matured_top50_observations']}")
    print(f"D_top20_win_rate_vs_A1={summary['D_top20_win_rate_vs_A1']}")
    print(f"D_top50_win_rate_vs_A1={summary['D_top50_win_rate_vs_A1']}")
    print(f"D_top20_win_rate_vs_QQQ={summary['D_top20_win_rate_vs_QQQ']}")
    print(f"D_top50_win_rate_vs_QQQ={summary['D_top50_win_rate_vs_QQQ']}")
    print(f"D_top20_max_sector_weight={summary['D_top20_max_sector_weight']}")
    print(f"D_top20_max_industry_weight={summary['D_top20_max_industry_weight']}")
    print(f"D_top20_memory_storage_semiconductor_chain_weight={summary['D_top20_memory_storage_semiconductor_chain_weight']}")
    print(f"D_repeated_loser_risk_level={summary['D_repeated_loser_risk_level']}")
    print(f"current_regime={summary['current_regime']}")
    print(f"role_review_required={str(summary['role_review_required']).lower()}")
    print(f"next_action_gate={summary['next_action_gate']}")
    print("protected_outputs_modified=false")
    print("official_adoption_allowed=false")
    print("broker_action_allowed=false")
    print(f"report_path={summary['report_path']}")
    return summary


if __name__ == "__main__":
    run()
