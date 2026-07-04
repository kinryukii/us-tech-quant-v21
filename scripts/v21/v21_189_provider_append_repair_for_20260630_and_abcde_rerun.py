#!/usr/bin/env python
"""V21.189 safe 2026-06-30 provider append and ABCDE rerun.

Research-only. Canonical writes require V21_189_APPLY_20260630_APPEND=TRUE.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from v21_194_broad_date_gate_utils import BroadDateGateError, classify_requested_date, load_latest_broad_date_gate


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.189_PROVIDER_APPEND_REPAIR_FOR_20260630_AND_ABCDE_RERUN"
OUT = ROOT / "outputs/v21/V21.189_PROVIDER_APPEND_REPAIR_FOR_20260630_AND_ABCDE_RERUN"
CANONICAL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
V114_SCRIPT = ROOT / "scripts/v21/v21_114_true_latest_data_abcd_full_recompute_20260625.py"
PRIOR_E_R1 = ROOT / "outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv"
EXPECTED_DATE = "2026-06-30"
REQUIRED_BASE_DATE = "2026-06-29"
APPLY_ENV = "V21_189_APPLY_20260630_APPEND"
OHLCV = ["open", "high", "low", "close", "adjusted_close", "volume"]
CANONICAL_FIELDS = [
    "symbol", "date", "open", "high", "low", "close", "adjusted_close",
    "volume", "source_provider", "source_artifact", "refresh_timestamp",
    "row_hash", "price_row_status",
]
ABCD = ["A1_BASELINE_CONTROL", "B_STATIC_MOMENTUM_BLEND", "C_DYNAMIC_MOMENTUM_BLEND", "D_WEIGHT_OPTIMIZED_R1"]
LABEL = {
    "A1_BASELINE_CONTROL": "A1",
    "B_STATIC_MOMENTUM_BLEND": "B",
    "C_DYNAMIC_MOMENTUM_BLEND": "C",
    "D_WEIGHT_OPTIMIZED_R1": "D",
}
OUT_RANK = {
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


def normalize(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.rename(columns={c: str(c).lower().strip().replace(" ", "_") for c in frame.columns}).copy()
    if "ticker" in out and "symbol" not in out:
        out = out.rename(columns={"ticker": "symbol"})
    if "adj_close" in out and "adjusted_close" not in out:
        out = out.rename(columns={"adj_close": "adjusted_close"})
    out["symbol"] = out["symbol"].astype(str).str.upper().str.strip()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in OHLCV:
        if col not in out:
            out[col] = np.nan
        out[col] = pd.to_numeric(out[col], errors="coerce")
    for col in CANONICAL_FIELDS:
        if col not in out:
            out[col] = ""
    out["adjusted_close"] = out["adjusted_close"].fillna(out["close"])
    out = out[CANONICAL_FIELDS]
    out = out[out["symbol"].ne("") & out["date"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)]
    out = out.dropna(subset=["open", "high", "low", "close", "adjusted_close", "volume"])
    return out.drop_duplicates(["symbol", "date"], keep="last").sort_values(["symbol", "date"]).reset_index(drop=True)


def load_canonical() -> pd.DataFrame:
    if not CANONICAL.is_file():
        return pd.DataFrame(columns=CANONICAL_FIELDS)
    return normalize(pd.read_csv(CANONICAL, low_memory=False))


def audit_frame(frame: pd.DataFrame, path: Path) -> dict[str, Any]:
    return {
        "path": rel(path),
        "row_count": int(len(frame)),
        "ticker_count": int(frame["symbol"].nunique()) if len(frame) else 0,
        "min_date": str(frame["date"].min()) if len(frame) else "",
        "max_date": str(frame["date"].max()) if len(frame) else "",
        "non_null_ohlcv_count": int(frame[OHLCV].notna().all(axis=1).sum()) if len(frame) else 0,
        "duplicate_symbol_date_count": int(frame.duplicated(["symbol", "date"]).sum()) if len(frame) else 0,
        "sha256": sha256(path) if path.is_file() else "",
    }


def row_hash(row: dict[str, Any]) -> str:
    text = "|".join(str(row.get(c, "")) for c in ["symbol", "date", "open", "high", "low", "close", "adjusted_close", "volume"])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fetch_20260630(tickers: list[str], batch_size: int = 20, retries: int = 2) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    diagnostics: list[dict[str, Any]] = []
    success: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    try:
        import yfinance as yf  # type: ignore
    except Exception as exc:
        for ticker in tickers:
            failed.append({"ticker": ticker, "failure_type": "YFINANCE_IMPORT_FAILED", "failure_reason": str(exc)})
        return pd.DataFrame(columns=CANONICAL_FIELDS), diagnostics, success, failed

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        for ticker in batch:
            last_error = ""
            got = False
            for attempt in range(1, retries + 1):
                try:
                    hist = yf.download(ticker, start=EXPECTED_DATE, end="2026-07-01", interval="1d", progress=False, auto_adjust=False, threads=False)
                    if isinstance(hist.columns, pd.MultiIndex):
                        hist.columns = [c[0] for c in hist.columns]
                    hist = hist.reset_index() if hist is not None else pd.DataFrame()
                    sub = hist[pd.to_datetime(hist.get("Date"), errors="coerce").dt.strftime("%Y-%m-%d").eq(EXPECTED_DATE)] if not hist.empty and "Date" in hist else pd.DataFrame()
                    if sub.empty:
                        last_error = "EMPTY_PROVIDER_RESPONSE_FOR_20260630"
                        diagnostics.append({"ticker": ticker, "attempt": attempt, "status": "EMPTY", "detail": last_error})
                        continue
                    rec = sub.iloc[0].to_dict()
                    row = {
                        "symbol": ticker,
                        "date": EXPECTED_DATE,
                        "open": rec.get("Open"),
                        "high": rec.get("High"),
                        "low": rec.get("Low"),
                        "close": rec.get("Close"),
                        "adjusted_close": rec.get("Adj Close", rec.get("Close")),
                        "volume": rec.get("Volume"),
                        "source_provider": "Yahoo/yfinance",
                        "source_artifact": f"V21.189:yfinance:start={EXPECTED_DATE};end=2026-07-01;symbol={ticker}",
                        "refresh_timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                        "price_row_status": "PROVIDER_OBSERVED_OHLCV_STAGE_LOCAL_20260630_APPEND",
                    }
                    row["row_hash"] = row_hash(row)
                    rows.append(row)
                    success.append({"ticker": ticker, "date": EXPECTED_DATE, "attempt": attempt, "status": "SUCCESS"})
                    diagnostics.append({"ticker": ticker, "attempt": attempt, "status": "SUCCESS", "detail": ""})
                    got = True
                    break
                except Exception as exc:
                    last_error = str(exc)
                    diagnostics.append({"ticker": ticker, "attempt": attempt, "status": "ERROR", "detail": last_error[:300]})
            if not got:
                failed.append({"ticker": ticker, "failure_type": "PROVIDER_APPEND_FAILED", "failure_reason": last_error})
    return normalize(pd.DataFrame(rows)) if rows else pd.DataFrame(columns=CANONICAL_FIELDS), diagnostics, success, failed


def candidate_valid(base: pd.DataFrame, candidate: pd.DataFrame) -> bool:
    if candidate.empty:
        return False
    return (
        str(candidate["date"].max()) >= EXPECTED_DATE
        and len(candidate) >= len(base)
        and candidate["symbol"].nunique() >= base["symbol"].nunique()
        and int(candidate.duplicated(["symbol", "date"]).sum()) == 0
        and int(candidate[OHLCV].notna().all(axis=1).sum()) == len(candidate)
    )


def apply_candidate(candidate_path: Path, base: pd.DataFrame, candidate: pd.DataFrame, valid: bool) -> dict[str, Any]:
    requested = os.environ.get(APPLY_ENV, "").upper() == "TRUE"
    audit = {
        "canonical_apply_requested": requested,
        "canonical_apply_succeeded": False,
        "canonical_backup_created": False,
        "canonical_restored_after_failed_apply": False,
        "backup_path": "",
        "apply_note": "",
    }
    if not requested:
        audit["apply_note"] = f"Dry mode. Set {APPLY_ENV}=TRUE after candidate validation."
        return audit
    if not valid:
        audit["apply_note"] = "REFUSED_INVALID_CANDIDATE"
        return audit
    backup = OUT / "canonical_backup_before_v21_189_apply.csv"
    shutil.copy2(CANONICAL, backup)
    audit["canonical_backup_created"] = True
    audit["backup_path"] = rel(backup)
    shutil.copy2(candidate_path, CANONICAL)
    after = load_canonical()
    if candidate_valid(base, after):
        audit["canonical_apply_succeeded"] = True
        audit["apply_note"] = "APPLIED_AND_VERIFIED"
    else:
        shutil.copy2(backup, CANONICAL)
        audit["canonical_restored_after_failed_apply"] = True
        audit["apply_note"] = "VERIFY_FAILED_RESTORED_BACKUP"
    return audit


def load_v114() -> Any:
    spec = importlib.util.spec_from_file_location("v21_114_recompute", V114_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {rel(V114_SCRIPT)}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.EXPECTED_DATE = EXPECTED_DATE
    return module


def topn(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    eligible = frame[frame["eligible_flag"].astype(str).str.upper().isin(["TRUE", "1", "YES"])] if "eligible_flag" in frame else frame
    return eligible.sort_values(["rank", "ticker"]).head(n).copy()


def norm_score(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.dropna().nunique() <= 1:
        return pd.Series(50.0, index=series.index)
    return (numeric.rank(pct=True, ascending=True) * 100.0).clip(0, 100)


def build_e_r1(a1: pd.DataFrame, latest: str) -> pd.DataFrame:
    prior = pd.read_csv(PRIOR_E_R1, low_memory=False) if PRIOR_E_R1.is_file() else pd.DataFrame()
    base = a1.copy()
    base["ticker_norm"] = base["ticker"].astype(str).str.upper().str.strip()
    full = base[["ticker_norm", "final_score", "rank"]].rename(columns={"final_score": "A1_raw_score", "rank": "A1_raw_rank"})
    full["A1_baseline_norm"] = norm_score(full["A1_raw_score"])
    if not prior.empty:
        prior["ticker_norm"] = prior["ticker_norm"].astype(str).str.upper().str.strip() if "ticker_norm" in prior else prior["ticker"].astype(str).str.upper().str.strip()
        keep = [c for c in ["ticker_norm", "context_momentum_norm", "technical_entry_quality_norm", "risk_guardrail_norm"] if c in prior]
        full = full.merge(prior[keep].drop_duplicates("ticker_norm"), on="ticker_norm", how="left")
    for col in ["context_momentum_norm", "technical_entry_quality_norm", "risk_guardrail_norm"]:
        if col not in full:
            full[col] = 50.0
        full[col] = pd.to_numeric(full[col], errors="coerce").fillna(50.0).clip(0, 100)
    full["E_final_score"] = sum(full[col] * weight for col, weight in E_WEIGHTS.items())
    full = full.sort_values(["E_final_score", "ticker_norm"], ascending=[False, True]).reset_index(drop=True)
    full["rank"] = np.arange(1, len(full) + 1)
    full["ticker"] = full["ticker_norm"]
    full["strategy"] = "E_R1_DEFENSIVE_OVERLAY_REPAIRED"
    full["latest_price_date"] = latest
    full["eligible_flag"] = True
    full["research_only"] = True
    full["official_adoption_allowed"] = False
    full["broker_action_allowed"] = False
    return full


def rerun_abcde(allowed: bool) -> tuple[dict[str, pd.DataFrame], bool, bool]:
    if not allowed:
        for name in OUT_RANK.values():
            write_csv(OUT / name, [], ["strategy", "rank", "ticker", "latest_price_date"])
        write_csv(OUT / "abcde_top20_summary.csv", [], ["strategy_id", "rank", "ticker", "score", "latest_price_date"])
        write_csv(OUT / "abcde_overlap_top20_matrix.csv", [], ["strategy_id", "A1", "B", "C", "D", "E_R1"])
        return {}, False, False
    base = load_v114()
    universe, _manifest = base.load_universe()
    price, latest, _price_manifest = base.load_price_panel(universe)
    tech, momentum, blockers = base.compute_features(price)
    if latest < EXPECTED_DATE or blockers:
        return {}, True, False
    rankings = {LABEL[k]: v for k, v in base.build_rankings(tech, momentum).items()}
    rankings["E_R1"] = build_e_r1(rankings["A1"], latest)
    rows = []
    sets = {}
    for label, frame in rankings.items():
        out = frame.copy()
        out["research_only"] = True
        out["official_adoption_allowed"] = False
        out["broker_action_allowed"] = False
        out.to_csv(OUT / OUT_RANK[label], index=False)
        t20 = topn(out, 20)
        sets[label] = set(t20["ticker"].astype(str))
        score_col = "E_final_score" if label == "E_R1" else "final_score"
        for rec in t20.to_dict("records"):
            rows.append({"strategy_id": label, "rank": rec.get("rank"), "ticker": rec.get("ticker"), "score": rec.get(score_col), "latest_price_date": rec.get("latest_price_date")})
    write_csv(OUT / "abcde_top20_summary.csv", rows)
    matrix = []
    for left in ["A1", "B", "C", "D", "E_R1"]:
        row = {"strategy_id": left}
        for right in ["A1", "B", "C", "D", "E_R1"]:
            row[right] = len(sets[left] & sets[right])
        matrix.append(row)
    write_csv(OUT / "abcde_overlap_top20_matrix.csv", matrix)
    comparable = all(str(df["latest_price_date"].max()) == EXPECTED_DATE for df in rankings.values())
    return rankings, True, comparable


def report(summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"canonical_latest_date_before={summary['canonical_latest_date_before']}",
        f"candidate_latest_date={summary['candidate_latest_date']}",
        f"canonical_latest_date_after={summary['canonical_latest_date_after']}",
        f"provider_success_ticker_count={summary['provider_success_ticker_count']}",
        f"provider_failed_ticker_count={summary['provider_failed_ticker_count']}",
        f"append_rows_created={summary['append_rows_created']}",
        f"abcde_rerun_attempted={summary['abcde_rerun_attempted']}",
        f"abcde_rerun_succeeded={summary['abcde_rerun_succeeded']}",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
    ]
    (OUT / "V21.189_provider_append_repair_and_abcde_rerun_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        broad_gate = load_latest_broad_date_gate()
        broad_gate_classification = classify_requested_date(EXPECTED_DATE, broad_gate)
    except BroadDateGateError as exc:
        broad_gate = {}
        broad_gate_classification = {
            "allowed": False,
            "classification": "BROAD_DATE_GATE_MISSING",
            "reason": str(exc),
        }
    base = load_canonical()
    before_audit = audit_frame(base, CANONICAL)
    write_csv(OUT / "canonical_before_append_audit.csv", [before_audit])

    provider_attempted = False
    append_rows = pd.DataFrame(columns=CANONICAL_FIELDS)
    diagnostics: list[dict[str, Any]] = []
    success: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    if before_audit["max_date"] >= REQUIRED_BASE_DATE:
        provider_attempted = True
        tickers = sorted(base["symbol"].dropna().astype(str).str.upper().unique())
        append_rows, diagnostics, success, failed = fetch_20260630(tickers)
    else:
        failed = [{"ticker": "", "failure_type": "CANONICAL_BELOW_20260629", "failure_reason": "Apply V21.188 recovery first."}]
    write_csv(OUT / "provider_fetch_diagnostics.csv", diagnostics, ["ticker", "attempt", "status", "detail"])
    write_csv(OUT / "provider_success_tickers.csv", success, ["ticker", "date", "attempt", "status"])
    write_csv(OUT / "provider_failed_tickers.csv", failed, ["ticker", "failure_type", "failure_reason"])
    append_rows.to_csv(OUT / "candidate_20260630_append_rows.csv", index=False)

    candidate = normalize(pd.concat([base, append_rows], ignore_index=True)) if len(append_rows) else base.copy()
    candidate_path = OUT / "candidate_canonical_through_20260630.csv"
    candidate.to_csv(candidate_path, index=False)
    candidate_audit = audit_frame(candidate, candidate_path)
    valid = candidate_valid(base, candidate)
    candidate_audit["candidate_panel_valid"] = valid
    write_csv(OUT / "candidate_canonical_audit.csv", [candidate_audit])

    apply_audit = apply_candidate(candidate_path, base, candidate, valid)
    write_csv(OUT / "canonical_apply_audit.csv", [apply_audit])
    after = load_canonical()
    after_latest = str(after["date"].max()) if len(after) else ""

    rerun_allowed = valid and bool(broad_gate_classification.get("allowed", False)) and (
        apply_audit["canonical_apply_succeeded"] or str(candidate["date"].max()) >= EXPECTED_DATE
    )
    rankings, rerun_attempted, same_date = rerun_abcde(rerun_allowed)
    rerun_succeeded = bool(rankings) and same_date
    top20 = {k: topn(v, 20)["ticker"].astype(str).tolist() for k, v in rankings.items()} if rankings else {}

    if before_audit["max_date"] < REQUIRED_BASE_DATE:
        final_status = "FAIL_V21_189_CANONICAL_RECOVERY_NOT_APPLIED"
        final_decision = "APPLY_V21_188_RECOVERY_FIRST"
    elif valid and not broad_gate_classification.get("allowed", False):
        final_status = "FAIL_OR_BLOCKED_TARGET_DATE_NOT_BROAD_ELIGIBLE"
        final_decision = "USE_ABCD_HONEST_LATEST_DATE_OR_IMPORT_BROAD_DAILY_BARS"
    elif rerun_succeeded:
        final_status = "PASS_V21_189_20260630_ABCDE_RERUN_READY"
        final_decision = "LATEST_20260630_ABCDE_RERUN_READY_RESEARCH_ONLY"
    elif valid and not apply_audit["canonical_apply_requested"]:
        final_status = "PARTIAL_PASS_V21_189_20260630_CANDIDATE_READY_NOT_APPLIED"
        final_decision = "CANDIDATE_READY_APPLY_REQUIRED_BEFORE_OFFICIAL_RERUN"
    else:
        final_status = "PARTIAL_PASS_V21_189_PROVIDER_STILL_BLOCKED_WAIT_DATA"
        final_decision = "WAIT_FOR_PROVIDER_OR_ALTERNATE_DATA_SOURCE_RESEARCH_ONLY"

    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "final_decision": final_decision,
        "canonical_latest_date_before": before_audit["max_date"],
        "candidate_latest_date": candidate_audit["max_date"],
        "canonical_latest_date_after": after_latest,
        "expected_latest_completed_trading_date": EXPECTED_DATE,
        "provider_fetch_attempted": provider_attempted,
        "provider_fetch_succeeded": len(success) > 0,
        "provider_success_ticker_count": len(success),
        "provider_failed_ticker_count": len(failed),
        "append_rows_created": int(len(append_rows)),
        "candidate_panel_created": candidate_path.is_file() and len(candidate) > 0,
        "candidate_panel_valid": bool(valid),
        "canonical_apply_requested": bool(apply_audit["canonical_apply_requested"]),
        "canonical_apply_succeeded": bool(apply_audit["canonical_apply_succeeded"]),
        "abcde_rerun_attempted": bool(rerun_attempted),
        "abcde_rerun_succeeded": bool(rerun_succeeded),
        "same_date_comparable_all_strategies": bool(same_date),
        "broad_date_gate_loaded": bool(broad_gate),
        "broad_date_gate_classification": broad_gate_classification.get("classification", ""),
        "abcd_honest_latest_date": broad_gate.get("abcd_honest_latest_date", ""),
        "blocked_newer_dates": broad_gate.get("blocked_newer_dates", []),
        "a1_top20": top20.get("A1", []),
        "b_top20": top20.get("B", []),
        "c_top20": top20.get("C", []),
        "d_top20": top20.get("D", []),
        "e_r1_top20": top20.get("E_R1", []),
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
    }
    write_json(OUT / "v21_189_summary.json", summary)
    report(summary)
    for key in [
        "final_status", "final_decision", "canonical_latest_date_before", "candidate_latest_date",
        "canonical_latest_date_after", "provider_success_ticker_count", "provider_failed_ticker_count",
        "append_rows_created", "abcde_rerun_attempted", "abcde_rerun_succeeded",
        "official_adoption_allowed", "broker_action_allowed",
    ]:
        print(f"{key}={summary[key]}")
    if top20:
        for key in ["a1_top20", "b_top20", "c_top20", "d_top20", "e_r1_top20"]:
            print(f"{key}={'|'.join(summary[key])}")
    return summary


if __name__ == "__main__":
    run()
