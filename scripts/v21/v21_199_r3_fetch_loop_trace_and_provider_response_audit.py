#!/usr/bin/env python
"""V21.199 R3 fetch-loop trace and provider-response audit."""

from __future__ import annotations

import json
import sys
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
    normalize_for_canonical,
    quality_gate,
)
from scripts.data_sources.moomoo_client import MoomooQuoteClient
from scripts.data_sources.moomoo_daily_ohlcv_fetcher import (
    SCHEMA,
    autype_for_mode,
    ktype_daily,
    normalize_kline_frame,
)
from scripts.data_sources.moomoo_market_state_gate import market_state_gate
from scripts.data_sources.moomoo_quota_auditor import audit_quota
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


STAGE = "V21.199_R3_FETCH_LOOP_TRACE_AND_PROVIDER_RESPONSE_AUDIT"
OUT = ROOT / "outputs/v21/V21.199_R3_FETCH_LOOP_TRACE_AND_PROVIDER_RESPONSE_AUDIT"


AUDIT_COLUMNS = [
    "fetch_order", "internal_symbol", "moomoo_code", "is_priority_symbol", "adjustment_mode",
    "request_attempted", "request_start_utc", "request_end_utc", "api_return_code", "api_return_message",
    "raw_row_count", "normalized_row_count", "latest_raw_date", "latest_completed_date", "page_count",
    "page_req_key_final_state", "fetch_exception_type", "fetch_exception_message", "accumulated_into_staging",
    "status_classification", "request_params",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def ret_ok(module: Any, ret: Any) -> bool:
    ok = getattr(module, "RET_OK", 0)
    return ret == ok or str(ret).upper() in {"0", "RET_OK", "OK"}


def payload_to_frame(payload: Any) -> pd.DataFrame:
    if isinstance(payload, pd.DataFrame):
        return payload.copy()
    if isinstance(payload, (list, tuple)):
        return pd.DataFrame(payload)
    return pd.DataFrame()


def priority_first_mapping(eligible_symbols: Iterable[str]) -> pd.DataFrame:
    fetch_symbols = build_fetch_universe(eligible_symbols, PRIORITY_SYMBOLS)
    priority = [s for s in PRIORITY_SYMBOLS if s in fetch_symbols]
    rest = [s for s in fetch_symbols if s not in set(priority)]
    return map_symbols(priority + rest, include_priority=False)


def request_history_pages(client: MoomooQuoteClient, internal_symbol: str, moomoo_code: str, adjustment_mode: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    frames = []
    page_req_key = None
    page_count = 0
    final_key = ""
    last_ret = ""
    last_msg = ""
    while True:
        params = {
            "code": moomoo_code,
            "ktype": ktype_daily(client.module),
            "autype": autype_for_mode(client.module, adjustment_mode),
        }
        if page_req_key is not None:
            params["page_req_key"] = page_req_key
        result = client.ctx.request_history_kline(**params)
        page_count += 1
        data = result
        next_key = None
        if isinstance(result, tuple):
            ret = result[0]
            data = result[1] if len(result) > 1 else pd.DataFrame()
            next_key = result[2] if len(result) > 2 else None
            last_ret = str(ret)
            if not ret_ok(client.module, ret):
                last_msg = str(data)
                return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), {
                    "api_return_code": last_ret, "api_return_message": last_msg, "page_count": page_count,
                    "page_req_key_final_state": str(next_key or ""), "api_ok": False, "request_params": json.dumps(params, default=str),
                }
        frame = payload_to_frame(data)
        frames.append(frame)
        final_key = str(next_key or "")
        if not next_key:
            break
        page_req_key = next_key
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), {
        "api_return_code": last_ret or "0", "api_return_message": last_msg, "page_count": page_count,
        "page_req_key_final_state": final_key, "api_ok": True, "request_params": json.dumps(params, default=str),
    }


def traced_fetch_loop(client: MoomooQuoteClient, mapping: pd.DataFrame, adjustment_mode: str, completed_date: str = "", stop_after: int | None = None, force_drop_after_fetch: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames = []
    audit_rows = []
    ok = mapping[mapping["mapping_status"].astype(str).str.upper().eq("PASS")].reset_index(drop=True)
    for i, row in ok.iterrows():
        if stop_after is not None and i >= stop_after:
            break
        sym = str(row["internal_symbol"]).upper()
        code = str(row["moomoo_code"])
        start = utc_now()
        raw = pd.DataFrame()
        norm = pd.DataFrame(columns=SCHEMA)
        meta = {"api_return_code": "", "api_return_message": "", "page_count": 0, "page_req_key_final_state": "", "request_params": ""}
        exc_type = ""
        exc_msg = ""
        status = "NOT_ATTEMPTED"
        try:
            raw, meta = request_history_pages(client, sym, code, adjustment_mode)
            raw_count = int(len(raw))
            if not meta.get("api_ok", False):
                status = "API_ERROR"
            elif raw_count == 0:
                status = "SUCCESS_EMPTY"
            else:
                norm = normalize_kline_frame(raw, sym, code, adjustment_mode, start)
                status = "NORMALIZATION_EMPTY" if norm.empty else "SUCCESS_NONEMPTY"
        except Exception as exc:
            raw_count = int(len(raw))
            status = "EXCEPTION"
            exc_type = type(exc).__name__
            exc_msg = str(exc)
        end = utc_now()
        accumulated = status == "SUCCESS_NONEMPTY"
        if force_drop_after_fetch is not None and len(frames) >= force_drop_after_fetch:
            accumulated = False
        if accumulated:
            frames.append(norm)
        latest_raw = ""
        if not raw.empty:
            raw_cols = {c: str(c).lower() for c in raw.columns}
            r = raw.rename(columns=raw_cols)
            source_col = "time_key" if "time_key" in r else "date" if "date" in r else None
            if source_col:
                latest_raw = str(pd.to_datetime(r[source_col], errors="coerce").dt.strftime("%Y-%m-%d").max())
        latest_completed = ""
        if not norm.empty:
            dates = norm["date"].astype(str)
            latest_completed = str(dates[dates <= completed_date].max()) if completed_date else str(dates.max())
        audit_rows.append({
            "fetch_order": i + 1, "internal_symbol": sym, "moomoo_code": code,
            "is_priority_symbol": sym in PRIORITY_SYMBOLS, "adjustment_mode": adjustment_mode.upper(),
            "request_attempted": True, "request_start_utc": start, "request_end_utc": end,
            "api_return_code": meta.get("api_return_code", ""), "api_return_message": meta.get("api_return_message", ""),
            "raw_row_count": raw_count, "normalized_row_count": int(len(norm)), "latest_raw_date": latest_raw,
            "latest_completed_date": latest_completed, "page_count": int(meta.get("page_count", 0) or 0),
            "page_req_key_final_state": meta.get("page_req_key_final_state", ""), "fetch_exception_type": exc_type,
            "fetch_exception_message": exc_msg, "accumulated_into_staging": accumulated,
            "status_classification": status, "request_params": meta.get("request_params", ""),
        })
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SCHEMA), pd.DataFrame(audit_rows, columns=AUDIT_COLUMNS)


def fallback_fetch(client: MoomooQuoteClient, symbol: str, mapping: pd.DataFrame, adjustment_mode: str, completed_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    row = mapping[mapping["internal_symbol"].astype(str).str.upper().eq(symbol)]
    if row.empty:
        return pd.DataFrame(columns=SCHEMA), pd.DataFrame([{
            "fetch_order": 1, "internal_symbol": symbol, "moomoo_code": "", "is_priority_symbol": True,
            "adjustment_mode": adjustment_mode.upper(), "request_attempted": False, "request_start_utc": "",
            "request_end_utc": "", "api_return_code": "", "api_return_message": "MAPPING_MISSING",
            "raw_row_count": 0, "normalized_row_count": 0, "latest_raw_date": "", "latest_completed_date": "",
            "page_count": 0, "page_req_key_final_state": "", "fetch_exception_type": "", "fetch_exception_message": "",
            "accumulated_into_staging": False, "status_classification": "NOT_ATTEMPTED", "request_params": "",
        }])
    return traced_fetch_loop(client, row, adjustment_mode, completed_date=completed_date)


def counts(audit: pd.DataFrame, staging: pd.DataFrame, planned: int) -> dict[str, Any]:
    attempted = int(audit["request_attempted"].astype(bool).sum()) if not audit.empty else 0
    return {
        "planned_fetch_symbol_count": int(planned),
        "actual_request_attempted_count": attempted,
        "api_success_count": int(audit["status_classification"].isin(["SUCCESS_NONEMPTY", "SUCCESS_EMPTY", "NORMALIZATION_EMPTY"]).sum()) if not audit.empty else 0,
        "api_empty_count": int(audit["status_classification"].eq("SUCCESS_EMPTY").sum()) if not audit.empty else 0,
        "api_failure_count": int(audit["status_classification"].eq("API_ERROR").sum()) if not audit.empty else 0,
        "exception_count": int(audit["status_classification"].eq("EXCEPTION").sum()) if not audit.empty else 0,
        "nonempty_response_symbol_count": int((audit["raw_row_count"] > 0).sum()) if not audit.empty else 0,
        "normalized_nonempty_symbol_count": int((audit["normalized_row_count"] > 0).sum()) if not audit.empty else 0,
        "accumulated_symbol_count": int(audit["accumulated_into_staging"].astype(bool).sum()) if not audit.empty else 0,
        "staging_distinct_symbol_count": int(staging["internal_symbol"].nunique()) if not staging.empty and "internal_symbol" in staging else 0,
    }


def priority_summary(symbol: str, audit: pd.DataFrame, fallback: pd.DataFrame, staging: pd.DataFrame, completed_date: str) -> dict[str, Any]:
    main = audit[audit["internal_symbol"].astype(str).str.upper().eq(symbol)] if not audit.empty else pd.DataFrame()
    fb = fallback.iloc[0].to_dict() if not fallback.empty else {}
    rows = staging[staging["internal_symbol"].astype(str).str.upper().eq(symbol)] if not staging.empty and "internal_symbol" in staging else pd.DataFrame()
    completed_rows = rows[rows["date"].astype(str) <= completed_date] if not rows.empty and completed_date else rows
    return {
        f"{symbol.lower()}_main_loop_attempted": bool(not main.empty and main["request_attempted"].astype(bool).any()),
        f"{symbol.lower()}_main_loop_status": "" if main.empty else str(main.iloc[0]["status_classification"]),
        f"{symbol.lower()}_main_loop_row_count": 0 if main.empty else int(main.iloc[0]["normalized_row_count"]),
        f"{symbol.lower()}_fallback_attempted": bool(not fallback.empty and fallback["request_attempted"].astype(bool).any()),
        f"{symbol.lower()}_fallback_status": str(fb.get("status_classification", "")),
        f"{symbol.lower()}_fallback_row_count": int(fb.get("normalized_row_count", 0) or 0),
        f"{symbol.lower()}_latest_completed_date": str(completed_rows["date"].max()) if not completed_rows.empty else "",
    }


def status(summary: dict[str, Any], gate_pass: bool, merge: dict[str, Any]) -> str:
    if summary["actual_request_attempted_count"] < summary["planned_fetch_symbol_count"]:
        return "FAIL_V21_199_R3_FETCH_LOOP_DID_NOT_ATTEMPT_ALL_SYMBOLS"
    if summary["nonempty_response_symbol_count"] < max(1, int(summary["planned_fetch_symbol_count"] * 0.50)):
        return "FAIL_V21_199_R3_PROVIDER_EMPTY_OR_ERROR_FOR_MOST_SYMBOLS"
    if summary["nonempty_response_symbol_count"] > 0 and summary["staging_distinct_symbol_count"] < int(summary["nonempty_response_symbol_count"] * 0.80):
        return "FAIL_V21_199_R3_STAGING_ACCUMULATION_TRUNCATED"
    if summary["trade_plan_candidate_rows"] == 0:
        return "FAIL_V21_199_R3_TRADE_PLAN_RAW_PANEL_EMPTY"
    if not summary["latest_moomoo_broad_honest_date"]:
        return "FAIL_V21_199_R3_BROAD_DATE_COVERAGE_INSUFFICIENT"
    if not gate_pass:
        return "FAIL_V21_199_R3_DATA_QUALITY_GATE_FAILED"
    return "PASS_V21_199_R3_READY_FOR_CANONICAL_UPDATE"


def write_empty_outputs(out: Path) -> None:
    pd.DataFrame(columns=AUDIT_COLUMNS).to_csv(out / "moomoo_fetch_loop_per_symbol_audit.csv", index=False)
    pd.DataFrame(columns=["status_classification", "count"]).to_csv(out / "moomoo_fetch_loop_failure_breakdown.csv", index=False)
    pd.DataFrame(columns=["priority_symbol"]).to_csv(out / "moomoo_priority_symbol_audit_r3.csv", index=False)
    pd.DataFrame(columns=AUDIT_COLUMNS).to_csv(out / "dram_fetch_fallback_audit.csv", index=False)
    pd.DataFrame(columns=AUDIT_COLUMNS).to_csv(out / "qqq_fetch_fallback_audit.csv", index=False)
    pd.DataFrame().to_csv(out / "moomoo_staging_accumulation_audit.csv", index=False)
    pd.DataFrame().to_csv(out / "moomoo_completed_date_gate_audit_r3.csv", index=False)
    pd.DataFrame().to_csv(out / "moomoo_broad_date_coverage_r3.csv", index=False)
    pd.DataFrame().to_csv(out / "moomoo_daily_ohlcv_staging_r3.csv", index=False)
    pd.DataFrame().to_csv(out / "moomoo_daily_ohlcv_research_canonical_candidate_r3.csv", index=False)
    pd.DataFrame().to_csv(out / "moomoo_daily_ohlcv_trade_plan_candidate_r3.csv", index=False)
    pd.DataFrame(columns=AUDIT_COLUMNS).to_csv(out / "moomoo_trade_plan_fetch_audit_r3.csv", index=False)
    pd.DataFrame().to_csv(out / "moomoo_data_quality_audit_r3.csv", index=False)


def write_report(summary: dict[str, Any], out: Path) -> None:
    keys = [
        "final_status", "final_decision", "planned_fetch_symbol_count", "actual_request_attempted_count",
        "api_success_count", "api_empty_count", "api_failure_count", "exception_count",
        "nonempty_response_symbol_count", "normalized_nonempty_symbol_count", "accumulated_symbol_count",
        "staging_distinct_symbol_count", "latest_raw_max_date", "latest_completed_candidate_date",
        "best_broad_candidate_date", "best_broad_candidate_coverage_ratio", "latest_moomoo_broad_honest_date",
        "dram_main_loop_attempted", "dram_main_loop_status", "dram_main_loop_row_count",
        "dram_fallback_attempted", "dram_fallback_status", "dram_fallback_row_count",
        "dram_latest_completed_date", "qqq_main_loop_attempted", "qqq_main_loop_status",
        "qqq_main_loop_row_count", "qqq_fallback_attempted", "qqq_fallback_status", "qqq_fallback_row_count",
        "trade_plan_candidate_rows", "trade_plan_failure_reason", "canonical_latest_date_before",
        "canonical_latest_date_after", "canonical_mutated", "research_only", "official_adoption_allowed",
        "broker_action_allowed", "trade_api_called",
    ]
    (out / "V21.199_R3_fetch_loop_trace_and_provider_response_audit_report.txt").write_text(
        "\n".join([STAGE] + [f"{k}={summary.get(k, '')}" for k in keys]) + "\n", encoding="utf-8"
    )


def run(
    client: MoomooQuoteClient | None = None,
    out_dir: Path = OUT,
    eligible_symbols: list[str] | None = None,
    apply_merge: bool = True,
    research_canonical_path: Path = DEFAULT_RESEARCH_CANONICAL,
    trade_plan_canonical_path: Path = DEFAULT_TRADE_PLAN_CANONICAL,
    stop_after: int | None = None,
    force_drop_after_fetch: int | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    before = latest_date(research_canonical_path)
    owns = client is None
    client = client or MoomooQuoteClient()
    health = client.health_check()
    base = {
        "stage": STAGE, "canonical_latest_date_before": before, "canonical_latest_date_after": before,
        "canonical_mutated": False, "research_only": True, "official_adoption_allowed": False,
        "broker_action_allowed": False, "trade_api_called": False,
    }
    if not health.get("minimal_quote_function_ok"):
        summary = {
            **base,
            "final_status": "FAIL_V21_199_R3_MOOMOO_OPEND_UNAVAILABLE",
            "final_decision": "STOP_BEFORE_STRATEGY_RERUN",
            "planned_fetch_symbol_count": 0,
            "actual_request_attempted_count": 0,
            "api_success_count": 0,
            "api_empty_count": 0,
            "api_failure_count": 0,
            "exception_count": 0,
            "nonempty_response_symbol_count": 0,
            "normalized_nonempty_symbol_count": 0,
            "accumulated_symbol_count": 0,
            "staging_distinct_symbol_count": 0,
            "latest_raw_max_date": "",
            "latest_completed_candidate_date": "",
            "best_broad_candidate_date": "",
            "best_broad_candidate_coverage_ratio": 0.0,
            "latest_moomoo_broad_honest_date": "",
            "dram_main_loop_attempted": False,
            "dram_main_loop_status": "",
            "dram_main_loop_row_count": 0,
            "dram_fallback_attempted": False,
            "dram_fallback_status": "",
            "dram_fallback_row_count": 0,
            "dram_latest_completed_date": "",
            "qqq_main_loop_attempted": False,
            "qqq_main_loop_status": "",
            "qqq_main_loop_row_count": 0,
            "qqq_fallback_attempted": False,
            "qqq_fallback_status": "",
            "qqq_fallback_row_count": 0,
            "trade_plan_candidate_rows": 0,
            "trade_plan_failure_reason": "MOOMOO_OPEND_UNAVAILABLE",
        }
        write_empty_outputs(out_dir); write_json(out_dir / "v21_199_r3_summary.json", summary); write_report(summary, out_dir)
        if owns: client.close()
        print(f"final_status={summary['final_status']}")
        return summary

    eligible = sorted({str(s).upper().strip() for s in (eligible_symbols or canonical_symbols(research_canonical_path)) if str(s).strip()})
    mapping = priority_first_mapping(eligible)
    planned = int(mapping["mapping_status"].astype(str).str.upper().eq("PASS").sum())
    market = market_state_gate(client)
    market.to_csv(out_dir / "moomoo_market_state_audit_r3.csv", index=False)
    market_open = regular_session_open(market)
    research, audit = traced_fetch_loop(client, mapping, "QFQ", stop_after=stop_after, force_drop_after_fetch=force_drop_after_fetch)
    completed_preview, completed_gate = completed_research_frame(research, market_open)
    completed_date = completed_gate["latest_completed_candidate_date"]
    dram_fb = pd.DataFrame(columns=AUDIT_COLUMNS)
    qqq_fb = pd.DataFrame(columns=AUDIT_COLUMNS)
    if research.empty or "DRAM" not in set(research.get("internal_symbol", pd.Series(dtype=str)).astype(str).str.upper()):
        dram_rows, dram_fb = fallback_fetch(client, "DRAM", mapping, "QFQ", completed_date)
        if not dram_rows.empty:
            research = pd.concat([research, dram_rows], ignore_index=True)
    if research.empty or "QQQ" not in set(research.get("internal_symbol", pd.Series(dtype=str)).astype(str).str.upper()):
        qqq_rows, qqq_fb = fallback_fetch(client, "QQQ", mapping, "QFQ", completed_date)
        if not qqq_rows.empty:
            research = pd.concat([research, qqq_rows], ignore_index=True)
    completed, completed_gate = completed_research_frame(research, market_open)
    completed_date = completed_gate["latest_completed_candidate_date"]
    trade, trade_audit = traced_fetch_loop(client, mapping, "RAW", completed_date=completed_date)
    trade_completed, _ = completed_research_frame(trade, market_open)
    research.to_csv(out_dir / "moomoo_daily_ohlcv_staging_r3.csv", index=False)
    completed.to_csv(out_dir / "moomoo_daily_ohlcv_research_canonical_candidate_r3.csv", index=False)
    trade_completed.to_csv(out_dir / "moomoo_daily_ohlcv_trade_plan_candidate_r3.csv", index=False)
    audit.to_csv(out_dir / "moomoo_fetch_loop_per_symbol_audit.csv", index=False)
    trade_audit.to_csv(out_dir / "moomoo_trade_plan_fetch_audit_r3.csv", index=False)
    dram_fb.to_csv(out_dir / "dram_fetch_fallback_audit.csv", index=False)
    qqq_fb.to_csv(out_dir / "qqq_fetch_fallback_audit.csv", index=False)
    audit["status_classification"].value_counts().rename_axis("status_classification").reset_index(name="count").to_csv(out_dir / "moomoo_fetch_loop_failure_breakdown.csv", index=False)
    gate_pass, gate_summary, coverage = quality_gate(completed, eligible, min_coverage_ratio=MIN_COVERAGE_RATIO)
    if coverage.empty:
        coverage = broad_date_coverage(completed, eligible, min_ratio=MIN_COVERAGE_RATIO)
    coverage.to_csv(out_dir / "moomoo_broad_date_coverage_r3.csv", index=False)
    best = coverage.sort_values(["coverage_ratio", "date"], ascending=[False, False]).head(1).to_dict("records")
    best_row = best[0] if best else {}
    c = counts(audit, research, planned)
    pri = {
        **priority_summary("DRAM", audit, dram_fb, research, completed_date),
        **priority_summary("QQQ", audit, qqq_fb, research, completed_date),
    }
    priority_rows = []
    for sym in PRIORITY_SYMBOLS:
        sub = audit[audit["internal_symbol"].astype(str).str.upper().eq(sym)]
        priority_rows.append({"priority_symbol": sym, "main_loop_attempted": not sub.empty, "main_loop_status": "" if sub.empty else sub.iloc[0]["status_classification"]})
    pd.DataFrame(priority_rows).to_csv(out_dir / "moomoo_priority_symbol_audit_r3.csv", index=False)
    pd.DataFrame([{**completed_gate, "best_broad_candidate_date": str(best_row.get("date", "")), "best_broad_candidate_coverage_ratio": float(best_row.get("coverage_ratio", 0.0) or 0.0)}]).to_csv(out_dir / "moomoo_completed_date_gate_audit_r3.csv", index=False)
    pd.DataFrame([{**c, "research_rows": len(research), "completed_rows": len(completed)}]).to_csv(out_dir / "moomoo_staging_accumulation_audit.csv", index=False)
    trade_failure = "" if len(trade_completed) else "|".join(sorted(set(trade_audit["status_classification"].astype(str)))) if not trade_audit.empty else "TRADE_PLAN_NOT_ATTEMPTED"
    merge = merge_canonical(
        completed, trade_completed, eligible,
        research_canonical_path=research_canonical_path,
        trade_plan_canonical_path=trade_plan_canonical_path,
        backup_dir=out_dir / "canonical_backups",
        min_coverage_ratio=MIN_COVERAGE_RATIO,
        apply=False,
    )
    summary = {
        **base, **completed_gate, **gate_summary, **c, **pri, **merge,
        "best_broad_candidate_date": str(best_row.get("date", "")),
        "best_broad_candidate_coverage_ratio": float(best_row.get("coverage_ratio", 0.0) or 0.0),
        "trade_plan_candidate_rows": int(len(trade_completed)),
        "trade_plan_failure_reason": trade_failure,
    }
    final = status(summary, gate_pass, merge)
    if final.startswith("PASS") and apply_merge:
        merge = merge_canonical(completed, trade_completed, eligible, research_canonical_path=research_canonical_path, trade_plan_canonical_path=trade_plan_canonical_path, backup_dir=out_dir / "canonical_backups", min_coverage_ratio=MIN_COVERAGE_RATIO, apply=True)
        summary.update(merge)
    summary["canonical_latest_date_after"] = latest_date(research_canonical_path)
    summary["canonical_mutated"] = bool(summary.get("canonical_updated", False))
    summary["final_status"] = final if not summary["canonical_mutated"] else "PASS_V21_199_R3_MOOMOO_CANONICAL_UPDATED"
    summary["final_decision"] = "CANONICAL_UPDATED_RUN_ABCDE_NEXT" if summary["final_status"].startswith("PASS") else "STOP_BEFORE_STRATEGY_RERUN"
    summary["quota"] = audit_quota(client)
    pd.DataFrame([summary]).to_csv(out_dir / "moomoo_data_quality_audit_r3.csv", index=False)
    write_json(out_dir / "v21_199_r3_summary.json", summary)
    write_report(summary, out_dir)
    if owns: client.close()
    for k in ["final_status", "final_decision", "planned_fetch_symbol_count", "actual_request_attempted_count", "nonempty_response_symbol_count", "staging_distinct_symbol_count", "trade_plan_candidate_rows", "canonical_mutated"]:
        print(f"{k}={summary.get(k, '')}")
    return summary


if __name__ == "__main__":
    run()
