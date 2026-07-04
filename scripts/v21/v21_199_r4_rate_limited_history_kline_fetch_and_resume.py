#!/usr/bin/env python
"""V21.199 R4 rate-limited Moomoo history K-line fetch with resume."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.data_sources.moomoo_canonical_merger import (
    DEFAULT_RESEARCH_CANONICAL,
    DEFAULT_TRADE_PLAN_CANONICAL,
    broad_date_coverage,
    merge_canonical,
    quality_gate,
)
from scripts.data_sources.moomoo_client import MoomooQuoteClient
from scripts.data_sources.moomoo_daily_ohlcv_fetcher import SCHEMA, autype_for_mode, ktype_daily, normalize_kline_frame
from scripts.data_sources.moomoo_market_state_gate import market_state_gate
from scripts.data_sources.moomoo_symbol_mapper import map_symbols
from scripts.v21.v21_199_r2_moomoo_full_universe_fetch_and_completed_date_gate import (
    MIN_COVERAGE_RATIO,
    PRIORITY_SYMBOLS,
    build_fetch_universe,
    canonical_symbols,
    completed_research_frame,
    latest_date,
    regular_session_open,
)


STAGE = "V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME"
OUT = ROOT / "outputs/v21/V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME"
CHECKPOINT_DIR = OUT / "checkpoints"
RATE_LIMIT_PATTERNS = ("每30秒最多60次", "频率太高")
EXCLUSION_REGISTRY = ROOT / "configs/v21/moomoo_symbol_exclusion_registry.csv"


AUDIT_COLS = [
    "fetch_order", "internal_symbol", "moomoo_code", "is_priority_symbol", "adjustment_mode",
    "request_attempted", "request_start_utc", "request_end_utc", "api_return_code", "api_return_message",
    "raw_row_count", "normalized_row_count", "latest_raw_date", "latest_completed_date", "page_count",
    "page_req_key_final_state", "retry_count", "fetch_exception_type", "fetch_exception_message",
    "accumulated_into_staging", "status_classification", "checkpoint_reused", "checkpoint_written",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def force_refetch() -> bool:
    return os.environ.get("MOOMOO_FORCE_REFETCH", "").strip().lower() in {"true", "1", "yes"}


def is_rate_limit_message(message: Any) -> bool:
    text = str(message)
    return any(pattern in text for pattern in RATE_LIMIT_PATTERNS)


def ret_ok(module: Any, ret: Any) -> bool:
    ok = getattr(module, "RET_OK", 0)
    return ret == ok or str(ret).upper() in {"0", "RET_OK", "OK"}


@dataclass
class HistoryKlineRateLimiter:
    max_calls_per_window: int = 55
    window_seconds: int = 30
    sleep_enabled: bool = True
    call_times: list[float] = field(default_factory=list)
    audit_rows: list[dict[str, Any]] = field(default_factory=list)

    def acquire(self, mode: str, symbol: str) -> None:
        now = time.monotonic()
        self.call_times = [t for t in self.call_times if now - t < self.window_seconds]
        slept = 0.0
        if len(self.call_times) >= self.max_calls_per_window:
            wait = self.window_seconds - (now - self.call_times[0]) + 0.01
            slept = max(0.0, wait)
            if self.sleep_enabled and slept > 0:
                time.sleep(slept)
            now = time.monotonic()
            self.call_times = [t for t in self.call_times if now - t < self.window_seconds]
        self.call_times.append(now)
        self.audit_rows.append({
            "timestamp_utc": utc_now(),
            "adjustment_mode": mode,
            "internal_symbol": symbol,
            "calls_in_window_after_acquire": len(self.call_times),
            "max_calls_per_window": self.max_calls_per_window,
            "window_seconds": self.window_seconds,
            "slept_seconds": slept,
        })


def limiter_from_env() -> HistoryKlineRateLimiter:
    return HistoryKlineRateLimiter(
        max_calls_per_window=env_int("MOOMOO_HISTORY_KLINE_MAX_CALLS_PER_WINDOW", 55),
        window_seconds=env_int("MOOMOO_HISTORY_KLINE_WINDOW_SECONDS", 30),
        sleep_enabled=os.environ.get("MOOMOO_HISTORY_KLINE_DISABLE_SLEEP", "").lower() not in {"true", "1"},
    )


def priority_first_mapping(eligible: Iterable[str]) -> pd.DataFrame:
    ordered = build_active_fetch_symbols(eligible)
    priority = [s for s in PRIORITY_SYMBOLS if s in ordered]
    rest = [s for s in ordered if s not in set(priority)]
    return map_symbols(priority + rest, include_priority=False)


def load_active_exclusions(registry_path: Path = EXCLUSION_REGISTRY) -> set[str]:
    if not registry_path.exists() or registry_path.stat().st_size == 0:
        return set()
    try:
        frame = pd.read_csv(registry_path)
    except pd.errors.EmptyDataError:
        return set()
    if "internal_symbol" not in frame:
        return set()
    active = frame
    if "active_exclusion" in frame:
        active = frame[frame["active_exclusion"].astype(str).str.lower().isin(["true", "1", "yes"])]
    return set(active["internal_symbol"].dropna().astype(str).str.upper().str.strip())


def build_active_fetch_symbols(eligible: Iterable[str], registry_path: Path = EXCLUSION_REGISTRY) -> list[str]:
    exclusions = load_active_exclusions(registry_path)
    filtered = [s for s in eligible if str(s).upper().strip() not in exclusions]
    return build_fetch_universe(filtered, PRIORITY_SYMBOLS)


def checkpoint_path(symbol: str, mode: str, checkpoint_dir: Path) -> Path:
    return checkpoint_dir / mode.upper() / f"{symbol.upper()}.csv"


def latest_raw_date(raw: pd.DataFrame) -> str:
    if raw.empty:
        return ""
    r = raw.rename(columns={c: str(c).lower() for c in raw.columns})
    col = "time_key" if "time_key" in r else "date" if "date" in r else None
    return "" if col is None else str(pd.to_datetime(r[col], errors="coerce").dt.strftime("%Y-%m-%d").max())


def request_once(client: MoomooQuoteClient, limiter: HistoryKlineRateLimiter, symbol: str, code: str, mode: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    limiter.acquire(mode, symbol)
    params = {"code": code, "ktype": ktype_daily(client.module), "autype": autype_for_mode(client.module, mode)}
    result = client.ctx.request_history_kline(**params)
    if isinstance(result, tuple):
        ret = result[0]
        payload = result[1] if len(result) > 1 else pd.DataFrame()
        page_key = result[2] if len(result) > 2 else None
        if not ret_ok(client.module, ret):
            return pd.DataFrame(), {"ok": False, "ret": ret, "msg": str(payload), "page_key": str(page_key or "")}
        return payload if isinstance(payload, pd.DataFrame) else pd.DataFrame(payload), {"ok": True, "ret": ret, "msg": "", "page_key": str(page_key or "")}
    return result if isinstance(result, pd.DataFrame) else pd.DataFrame(result), {"ok": True, "ret": 0, "msg": "", "page_key": ""}


def fetch_symbol_with_retry(
    client: MoomooQuoteClient,
    limiter: HistoryKlineRateLimiter,
    symbol: str,
    code: str,
    mode: str,
    checkpoint_dir: Path,
    retry_max: int | None = None,
    retry_backoff_seconds: int | None = None,
    sleep_enabled: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any], list[dict[str, Any]]]:
    retry_max = env_int("MOOMOO_HISTORY_KLINE_RETRY_MAX", 3) if retry_max is None else retry_max
    retry_backoff_seconds = env_int("MOOMOO_HISTORY_KLINE_RETRY_BACKOFF_SECONDS", 30) if retry_backoff_seconds is None else retry_backoff_seconds
    cp = checkpoint_path(symbol, mode, checkpoint_dir)
    if cp.exists() and not force_refetch():
        frame = pd.read_csv(cp)
        return frame, {
            "request_attempted": False, "api_return_code": "CHECKPOINT", "api_return_message": "",
            "raw_row_count": len(frame), "normalized_row_count": len(frame), "latest_raw_date": str(frame["date"].max()) if not frame.empty else "",
            "page_count": 0, "page_req_key_final_state": "", "retry_count": 0, "fetch_exception_type": "",
            "fetch_exception_message": "", "status_classification": "SUCCESS_NONEMPTY" if len(frame) else "SUCCESS_EMPTY",
            "checkpoint_reused": True, "checkpoint_written": False,
        }, []
    retry_rows = []
    start = utc_now()
    raw = pd.DataFrame()
    meta = {"ret": "", "msg": "", "page_key": ""}
    exc_type = ""
    exc_msg = ""
    retries = 0
    status = "NOT_ATTEMPTED"
    try:
        while True:
            raw, meta = request_once(client, limiter, symbol, code, mode)
            if meta["ok"]:
                status = "SUCCESS_EMPTY" if raw.empty else "SUCCESS_NONEMPTY"
                break
            if is_rate_limit_message(meta["msg"]):
                status = "RATE_LIMIT_ERROR"
                retry_rows.append({"timestamp_utc": utc_now(), "internal_symbol": symbol, "adjustment_mode": mode, "retry_number": retries + 1, "api_return_code": meta["ret"], "api_return_message": meta["msg"], "backoff_seconds": retry_backoff_seconds})
                if retries >= retry_max:
                    break
                retries += 1
                if sleep_enabled and retry_backoff_seconds > 0:
                    time.sleep(retry_backoff_seconds)
                continue
            status = "API_ERROR"
            break
    except Exception as exc:
        status = "EXCEPTION"
        exc_type = type(exc).__name__
        exc_msg = str(exc)
    normalized = pd.DataFrame(columns=SCHEMA)
    if status == "SUCCESS_NONEMPTY":
        normalized = normalize_kline_frame(raw, symbol, code, mode, start)
        if normalized.empty:
            status = "NORMALIZATION_EMPTY"
    written = False
    if not normalized.empty:
        cp.parent.mkdir(parents=True, exist_ok=True)
        normalized.to_csv(cp, index=False)
        written = True
    audit = {
        "request_attempted": True,
        "request_start_utc": start,
        "request_end_utc": utc_now(),
        "api_return_code": str(meta.get("ret", "")),
        "api_return_message": str(meta.get("msg", "")),
        "raw_row_count": int(len(raw)),
        "normalized_row_count": int(len(normalized)),
        "latest_raw_date": latest_raw_date(raw),
        "latest_completed_date": str(normalized["date"].max()) if not normalized.empty else "",
        "page_count": 1,
        "page_req_key_final_state": meta.get("page_key", ""),
        "retry_count": retries,
        "fetch_exception_type": exc_type,
        "fetch_exception_message": exc_msg,
        "status_classification": status,
        "checkpoint_reused": False,
        "checkpoint_written": written,
    }
    return normalized, audit, retry_rows


def fetch_mode(client: MoomooQuoteClient, mapping: pd.DataFrame, mode: str, limiter: HistoryKlineRateLimiter, checkpoint_dir: Path, sleep_enabled: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frames = []
    audits = []
    retries = []
    ok = mapping[mapping["mapping_status"].astype(str).str.upper().eq("PASS")].reset_index(drop=True)
    for i, row in ok.iterrows():
        sym = str(row["internal_symbol"]).upper()
        frame, audit, retry_rows = fetch_symbol_with_retry(client, limiter, sym, str(row["moomoo_code"]), mode, checkpoint_dir, sleep_enabled=sleep_enabled)
        audits.append({
            "fetch_order": i + 1, "internal_symbol": sym, "moomoo_code": str(row["moomoo_code"]),
            "is_priority_symbol": sym in PRIORITY_SYMBOLS, "adjustment_mode": mode.upper(),
            **audit, "accumulated_into_staging": not frame.empty,
        })
        retries.extend(retry_rows)
        if not frame.empty:
            frames.append(frame)
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SCHEMA)
    return data, pd.DataFrame(audits, columns=AUDIT_COLS), pd.DataFrame(retries)


def counts(audit: pd.DataFrame, planned: int) -> dict[str, int]:
    return {
        "planned_symbol_count": planned,
        "success_count": int(audit["normalized_row_count"].gt(0).sum()) if not audit.empty else 0,
        "rate_limit_retry_count": int(audit["retry_count"].sum()) if not audit.empty else 0,
        "final_failure_count": int((~audit["status_classification"].isin(["SUCCESS_NONEMPTY"])).sum()) if not audit.empty else planned,
        "checkpoint_reused_count": int(audit["checkpoint_reused"].astype(bool).sum()) if not audit.empty else 0,
        "checkpoint_written_count": int(audit["checkpoint_written"].astype(bool).sum()) if not audit.empty else 0,
    }


def symbol_status(audit: pd.DataFrame, symbol: str, prefix: str) -> dict[str, Any]:
    row = audit[audit["internal_symbol"].astype(str).str.upper().eq(symbol)]
    if row.empty:
        return {f"{prefix}_status": "", f"{prefix}_row_count": 0}
    first = row.iloc[0]
    return {f"{prefix}_status": str(first["status_classification"]), f"{prefix}_row_count": int(first["normalized_row_count"])}


def final_status(summary: dict[str, Any], gate_pass: bool) -> str:
    if summary["raw_success_count"] == 0 or summary["trade_plan_candidate_rows"] == 0:
        return "FAIL_V21_199_R4_TRADE_PLAN_RATE_LIMIT_OR_RAW_FETCH_FAILED"
    if summary["qfq_success_count"] < max(1, int(summary["qfq_planned_symbol_count"] * 0.95)):
        return "FAIL_V21_199_R4_QFQ_FETCH_INCOMPLETE"
    if not summary["latest_moomoo_broad_honest_date"]:
        return "FAIL_V21_199_R4_BROAD_DATE_COVERAGE_INSUFFICIENT"
    if not gate_pass:
        return "FAIL_V21_199_R4_DATA_QUALITY_GATE_FAILED"
    return "PASS_V21_199_R4_READY_FOR_CANONICAL_UPDATE"


def write_report(summary: dict[str, Any], out_dir: Path) -> None:
    keys = [
        "final_status", "final_decision", "qfq_planned_symbol_count", "qfq_success_count", "qfq_rate_limit_retry_count",
        "qfq_final_failure_count", "raw_planned_symbol_count", "raw_success_count", "raw_rate_limit_retry_count",
        "raw_final_failure_count", "checkpoint_reused_count", "checkpoint_written_count", "latest_raw_max_date",
        "latest_completed_candidate_date", "best_broad_candidate_date", "best_broad_candidate_coverage_ratio",
        "latest_moomoo_broad_honest_date", "dram_qfq_status", "dram_qfq_row_count", "dram_raw_status",
        "dram_raw_row_count", "qqq_qfq_status", "qqq_qfq_row_count", "qqq_raw_status", "qqq_raw_row_count",
        "trade_plan_candidate_rows", "trade_plan_failure_reason", "canonical_latest_date_before",
        "canonical_latest_date_after", "canonical_mutated", "research_only", "official_adoption_allowed",
        "broker_action_allowed", "trade_api_called",
    ]
    (out_dir / "V21.199_R4_rate_limited_history_kline_fetch_report.txt").write_text("\n".join([STAGE] + [f"{k}={summary.get(k, '')}" for k in keys]) + "\n", encoding="utf-8")


def empty_outputs(out_dir: Path) -> None:
    pd.DataFrame().to_csv(out_dir / "moomoo_rate_limiter_audit.csv", index=False)
    pd.DataFrame(columns=AUDIT_COLS).to_csv(out_dir / "moomoo_qfq_fetch_per_symbol_audit_r4.csv", index=False)
    pd.DataFrame(columns=AUDIT_COLS).to_csv(out_dir / "moomoo_raw_fetch_per_symbol_audit_r4.csv", index=False)
    pd.DataFrame().to_csv(out_dir / "moomoo_fetch_retry_audit_r4.csv", index=False)
    pd.DataFrame(columns=["path", "mode", "symbol"]).to_csv(out_dir / "moomoo_fetch_checkpoint_manifest_r4.csv", index=False)
    pd.DataFrame(columns=["priority_symbol", "qfq_status", "qfq_row_count", "raw_status", "raw_row_count"]).to_csv(out_dir / "moomoo_priority_symbol_audit_r4.csv", index=False)
    pd.DataFrame().to_csv(out_dir / "moomoo_completed_date_gate_audit_r4.csv", index=False)
    pd.DataFrame().to_csv(out_dir / "moomoo_broad_date_coverage_r4.csv", index=False)
    pd.DataFrame(columns=SCHEMA).to_csv(out_dir / "moomoo_daily_ohlcv_staging_qfq_r4.csv", index=False)
    pd.DataFrame(columns=SCHEMA).to_csv(out_dir / "moomoo_daily_ohlcv_staging_raw_r4.csv", index=False)
    pd.DataFrame().to_csv(out_dir / "moomoo_daily_ohlcv_research_canonical_candidate_r4.csv", index=False)
    pd.DataFrame().to_csv(out_dir / "moomoo_daily_ohlcv_trade_plan_candidate_r4.csv", index=False)
    pd.DataFrame().to_csv(out_dir / "moomoo_data_quality_audit_r4.csv", index=False)


def run(
    client: MoomooQuoteClient | None = None,
    out_dir: Path = OUT,
    eligible_symbols: list[str] | None = None,
    apply_merge: bool = True,
    research_canonical_path: Path = DEFAULT_RESEARCH_CANONICAL,
    trade_plan_canonical_path: Path = DEFAULT_TRADE_PLAN_CANONICAL,
    limiter: HistoryKlineRateLimiter | None = None,
    sleep_enabled: bool = True,
    current_exchange_date: str | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = out_dir / "checkpoints"
    before = latest_date(research_canonical_path)
    owns = client is None
    client = client or MoomooQuoteClient()
    health = client.health_check()
    base = {"stage": STAGE, "canonical_latest_date_before": before, "canonical_latest_date_after": before, "canonical_mutated": False, "research_only": True, "official_adoption_allowed": False, "broker_action_allowed": False, "trade_api_called": False}
    if not health.get("minimal_quote_function_ok"):
        summary = {
            **base,
            "final_status": "FAIL_V21_199_R4_MOOMOO_OPEND_UNAVAILABLE",
            "final_decision": "STOP_BEFORE_STRATEGY_RERUN",
            "qfq_planned_symbol_count": 0,
            "qfq_success_count": 0,
            "qfq_rate_limit_retry_count": 0,
            "qfq_final_failure_count": 0,
            "raw_planned_symbol_count": 0,
            "raw_success_count": 0,
            "raw_rate_limit_retry_count": 0,
            "raw_final_failure_count": 0,
            "checkpoint_reused_count": 0,
            "checkpoint_written_count": 0,
            "latest_raw_max_date": "",
            "latest_completed_candidate_date": "",
            "best_broad_candidate_date": "",
            "best_broad_candidate_coverage_ratio": 0.0,
            "latest_moomoo_broad_honest_date": "",
            "dram_qfq_status": "",
            "dram_qfq_row_count": 0,
            "dram_raw_status": "",
            "dram_raw_row_count": 0,
            "qqq_qfq_status": "",
            "qqq_qfq_row_count": 0,
            "qqq_raw_status": "",
            "qqq_raw_row_count": 0,
            "trade_plan_candidate_rows": 0,
            "trade_plan_failure_reason": "MOOMOO_OPEND_UNAVAILABLE",
        }
        empty_outputs(out_dir)
        write_json(out_dir / "v21_199_r4_summary.json", summary); write_report(summary, out_dir)
        if owns: client.close()
        print(f"final_status={summary['final_status']}")
        return summary
    eligible = sorted({str(s).upper().strip() for s in (eligible_symbols or canonical_symbols(research_canonical_path)) if str(s).strip()})
    mapping = priority_first_mapping(eligible)
    planned = int(mapping["mapping_status"].astype(str).str.upper().eq("PASS").sum())
    limiter = limiter or limiter_from_env()
    market = market_state_gate(client)
    market_open = regular_session_open(market)
    qfq, qfq_audit, qfq_retries = fetch_mode(client, mapping, "QFQ", limiter, checkpoint_dir, sleep_enabled=sleep_enabled)
    raw, raw_audit, raw_retries = fetch_mode(client, mapping, "RAW", limiter, checkpoint_dir, sleep_enabled=sleep_enabled)
    completed_qfq, completed_gate = completed_research_frame(qfq, market_open, current_exchange_date=current_exchange_date)
    completed_raw, _ = completed_research_frame(raw, market_open, current_exchange_date=current_exchange_date)
    qfq.to_csv(out_dir / "moomoo_daily_ohlcv_staging_qfq_r4.csv", index=False)
    raw.to_csv(out_dir / "moomoo_daily_ohlcv_staging_raw_r4.csv", index=False)
    completed_qfq.to_csv(out_dir / "moomoo_daily_ohlcv_research_canonical_candidate_r4.csv", index=False)
    completed_raw.to_csv(out_dir / "moomoo_daily_ohlcv_trade_plan_candidate_r4.csv", index=False)
    qfq_audit.to_csv(out_dir / "moomoo_qfq_fetch_per_symbol_audit_r4.csv", index=False)
    raw_audit.to_csv(out_dir / "moomoo_raw_fetch_per_symbol_audit_r4.csv", index=False)
    pd.concat([qfq_retries, raw_retries], ignore_index=True).to_csv(out_dir / "moomoo_fetch_retry_audit_r4.csv", index=False)
    pd.DataFrame(limiter.audit_rows).to_csv(out_dir / "moomoo_rate_limiter_audit.csv", index=False)
    pd.DataFrame([{"path": str(p), "mode": p.parent.name, "symbol": p.stem} for p in checkpoint_dir.rglob("*.csv")]).to_csv(out_dir / "moomoo_fetch_checkpoint_manifest_r4.csv", index=False)
    priority_rows = []
    for sym in PRIORITY_SYMBOLS:
        priority_rows.append({"priority_symbol": sym, **symbol_status(qfq_audit, sym, "qfq"), **symbol_status(raw_audit, sym, "raw")})
    pd.DataFrame(priority_rows).to_csv(out_dir / "moomoo_priority_symbol_audit_r4.csv", index=False)
    gate_pass, gate_summary, coverage = quality_gate(completed_qfq, eligible, min_coverage_ratio=MIN_COVERAGE_RATIO)
    if coverage.empty:
        coverage = broad_date_coverage(completed_qfq, eligible, min_ratio=MIN_COVERAGE_RATIO)
    coverage.to_csv(out_dir / "moomoo_broad_date_coverage_r4.csv", index=False)
    best = coverage.sort_values(["coverage_ratio", "date"], ascending=[False, False]).head(1).to_dict("records")
    best_row = best[0] if best else {}
    pd.DataFrame([{**completed_gate, "best_broad_candidate_date": str(best_row.get("date", "")), "best_broad_candidate_coverage_ratio": float(best_row.get("coverage_ratio", 0.0) or 0.0)}]).to_csv(out_dir / "moomoo_completed_date_gate_audit_r4.csv", index=False)
    qc = counts(qfq_audit, planned); rc = counts(raw_audit, planned)
    trade_reason = "" if len(completed_raw) else "|".join(sorted(set(raw_audit["status_classification"].astype(str)))) if not raw_audit.empty else "RAW_NOT_ATTEMPTED"
    merge = merge_canonical(completed_qfq, completed_raw, eligible, research_canonical_path=research_canonical_path, trade_plan_canonical_path=trade_plan_canonical_path, backup_dir=out_dir / "canonical_backups", min_coverage_ratio=MIN_COVERAGE_RATIO, apply=False)
    summary = {
        **base, **completed_gate, **gate_summary, **merge,
        "qfq_planned_symbol_count": qc["planned_symbol_count"], "qfq_success_count": qc["success_count"], "qfq_rate_limit_retry_count": qc["rate_limit_retry_count"], "qfq_final_failure_count": qc["final_failure_count"],
        "raw_planned_symbol_count": rc["planned_symbol_count"], "raw_success_count": rc["success_count"], "raw_rate_limit_retry_count": rc["rate_limit_retry_count"], "raw_final_failure_count": rc["final_failure_count"],
        "checkpoint_reused_count": qc["checkpoint_reused_count"] + rc["checkpoint_reused_count"], "checkpoint_written_count": qc["checkpoint_written_count"] + rc["checkpoint_written_count"],
        "best_broad_candidate_date": str(best_row.get("date", "")), "best_broad_candidate_coverage_ratio": float(best_row.get("coverage_ratio", 0.0) or 0.0),
        **symbol_status(qfq_audit, "DRAM", "dram_qfq"), **symbol_status(raw_audit, "DRAM", "dram_raw"),
        **symbol_status(qfq_audit, "QQQ", "qqq_qfq"), **symbol_status(raw_audit, "QQQ", "qqq_raw"),
        "trade_plan_candidate_rows": int(len(completed_raw)), "trade_plan_failure_reason": trade_reason,
    }
    status = final_status(summary, gate_pass)
    if status.startswith("PASS") and apply_merge:
        merge = merge_canonical(completed_qfq, completed_raw, eligible, research_canonical_path=research_canonical_path, trade_plan_canonical_path=trade_plan_canonical_path, backup_dir=out_dir / "canonical_backups", min_coverage_ratio=MIN_COVERAGE_RATIO, apply=True)
        summary.update(merge)
        status = "PASS_V21_199_R4_MOOMOO_CANONICAL_UPDATED"
    summary["canonical_latest_date_after"] = latest_date(research_canonical_path)
    summary["canonical_mutated"] = bool(summary.get("canonical_updated", False))
    summary["final_status"] = status
    summary["final_decision"] = "CANONICAL_UPDATED_RUN_ABCDE_NEXT" if status.startswith("PASS") else "STOP_BEFORE_STRATEGY_RERUN"
    pd.DataFrame([summary]).to_csv(out_dir / "moomoo_data_quality_audit_r4.csv", index=False)
    write_json(out_dir / "v21_199_r4_summary.json", summary)
    write_report(summary, out_dir)
    if owns: client.close()
    for k in ["final_status", "final_decision", "qfq_success_count", "raw_success_count", "qfq_rate_limit_retry_count", "raw_rate_limit_retry_count", "trade_plan_candidate_rows", "canonical_mutated"]:
        print(f"{k}={summary.get(k, '')}")
    return summary


if __name__ == "__main__":
    run()
