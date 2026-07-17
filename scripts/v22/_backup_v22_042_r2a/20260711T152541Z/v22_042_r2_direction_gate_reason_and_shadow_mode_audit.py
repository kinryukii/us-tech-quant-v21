#!/usr/bin/env python
"""V22.042 R2 direction gate reason and shadow-mode audit."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from pathlib import Path
from typing import Any


MODULE_ID = "V22.042_R2"
MODULE_NAME = "DIRECTION_GATE_REASON_AND_SHADOW_MODE_AUDIT"
STAGE = "V22.042_R2_DIRECTION_GATE_REASON_AND_SHADOW_MODE_AUDIT"
OUT_REL = Path("outputs") / "v22" / STAGE
V22_041_REL = Path("outputs") / "v22" / "V22.041_OPTION_INTRADAY_ETF_ONLY_RESEARCH_LAYER_R1"

PASS_STATUS = "PASS_V22_042_R2_DIRECTION_GATE_SHADOW_AUDIT_READY"
DECISION_SHADOW = "STRICT_GATE_WAIT_SHADOW_DIRECTION_AVAILABLE_RESEARCH_ONLY"
DECISION_ALL_WAIT = "ALL_DIRECTION_MODES_WAIT_RESEARCH_ONLY"
DECISION_STRICT = "STRICT_DIRECTION_GATE_READY_RESEARCH_ONLY"

REASON_FIELDS = ["reason_rank", "reason_code", "reason_detail", "official_gate_blocking", "shadow_relevant"]
MODE_FIELDS = ["gate_mode", "direction_label", "wait_state", "candidate_count", "reason_code", "official_gate", "shadow_only", "broker_action_allowed", "official_adoption_allowed", "research_only"]
CANDIDATE_FIELDS = ["gate_mode", "contract_id", "underlying", "expiration", "dte", "strike", "call_put", "bid", "ask", "mid", "spread_pct", "volume", "direction_action", "direction_label", "shadow_only", "broker_action_allowed", "official_adoption_allowed", "research_only"]
REJECT_FIELDS = CANDIDATE_FIELDS + ["reject_reason"]
SUMMARY_FIELDS = [
    "final_status", "final_decision", "execution_mode", "v22_041_summary_found",
    "v22_041_liquidity_candidate_count", "v22_041_real_readonly_quote_verified",
    "v22_041_fallback_rows_used", "intraday_data_available", "soxx_direction_label",
    "qqq_confirmation_label", "spy_confirmation_label",
    "strict_official_final_direction_label", "strict_official_wait_state",
    "strict_official_promoted_candidate_count", "semiconductor_only_shadow_direction_label",
    "semiconductor_only_shadow_candidate_count", "relaxed_broad_shadow_direction_label",
    "relaxed_broad_shadow_candidate_count", "primary_wait_reason_code",
    "secondary_wait_reason_code", "broad_confirmation_missing", "qqq_opposite_detected",
    "spy_opposite_detected", "shadow_modes_enabled", "shadow_only_no_broker_action",
    "trade_context_used", "unlock_trade_called", "place_order_called",
    "broker_action_allowed", "official_adoption_allowed", "research_only",
]


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="", errors="ignore") as handle:
        return [{k: (v or "") for k, v in row.items() if k is not None} for row in csv.DictReader(handle)]


def load_r1_module() -> Any:
    path = Path(__file__).with_name("v22_042_option_intraday_etf_direction_gate_r1.py")
    spec = importlib.util.spec_from_file_location("v22_042_r1_for_r2", path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise ImportError(f"Unable to load {path}")
    spec.loader.exec_module(module)
    return module


def load_latest_inputs(repo_root: Path) -> tuple[dict[str, Any], list[dict[str, str]], dict[str, Any]]:
    v41 = read_json(repo_root / V22_041_REL / "v22_041_summary.json")
    candidates = read_csv_rows(repo_root / V22_041_REL / "etf_option_liquidity_candidates.csv")
    v42 = read_json(repo_root / "outputs" / "v22" / "V22.042_OPTION_INTRADAY_ETF_DIRECTION_GATE_R1" / "v22_042_summary.json")
    return v41, candidates, v42


def opposite(direction: str) -> str:
    return "BEARISH" if direction == "BULLISH" else "BULLISH" if direction == "BEARISH" else ""


def semi_label(soxx: str) -> str:
    if soxx == "BULLISH":
        return "BULL_SEMICONDUCTOR"
    if soxx == "BEARISH":
        return "BEAR_SEMICONDUCTOR"
    return "MIXED_OR_WAIT"


def strict_label(soxx: str, qqq: str, spy: str, require_qqq: bool, require_spy: bool) -> str:
    if soxx == "BULLISH" and (not require_qqq or qqq == "BULLISH") and (not require_spy or spy == "BULLISH"):
        return "BULL_SEMICONDUCTOR_CONFIRMED"
    if soxx == "BEARISH" and (not require_qqq or qqq == "BEARISH") and (not require_spy or spy == "BEARISH"):
        return "BEAR_SEMICONDUCTOR_CONFIRMED"
    if soxx == "INTRADAY_DATA_INSUFFICIENT":
        return "INTRADAY_DATA_INSUFFICIENT"
    return "MIXED_OR_WAIT"


def relaxed_label(soxx: str, qqq: str, spy: str, require_spy: bool) -> str:
    if soxx not in {"BULLISH", "BEARISH"}:
        return "MIXED_OR_WAIT"
    opp = opposite(soxx)
    if qqq == opp or (require_spy and spy == opp):
        return "MIXED_OR_WAIT"
    return "BULL_SEMICONDUCTOR" if soxx == "BULLISH" else "BEAR_SEMICONDUCTOR"


def reason_codes(v41: dict[str, Any], soxx: str, qqq: str, spy: str, require_qqq: bool, require_spy: bool) -> list[dict[str, Any]]:
    codes: list[tuple[str, str, bool, bool]] = []
    if not v41 or int(v41.get("liquidity_candidate_count", 0) or 0) <= 0:
        codes.append(("WAIT_V22_041_CANDIDATES_MISSING", "V22.041 liquidity candidates are missing or zero.", True, False))
    if v41.get("fallback_rows_used") is True:
        codes.append(("WAIT_V22_041_FALLBACK_ROWS_USED", "V22.041 used fallback rows; live direction gate cannot cleanly promote.", True, False))
    if "INSUFFICIENT" in {soxx, qqq, spy}:
        codes.append(("WAIT_INTRADAY_DATA_INSUFFICIENT", "Intraday data is insufficient for one or more direction underlyings.", True, False))
    if soxx not in {"BULLISH", "BEARISH"}:
        codes.append(("WAIT_SOXX_MIXED", "SOXX is mixed/wait, so semiconductor direction is unavailable.", True, False))
    if soxx in {"BULLISH", "BEARISH"}:
        opp = opposite(soxx)
        if require_qqq and qqq == "MIXED_OR_WAIT":
            codes.append(("WAIT_QQQ_MIXED", "QQQ broad confirmation is mixed/wait.", True, True))
        if require_spy and spy == "MIXED_OR_WAIT":
            codes.append(("WAIT_SPY_MIXED", "SPY broad confirmation is mixed/wait.", True, True))
        if require_qqq and qqq == opp:
            codes.append(("WAIT_QQQ_OPPOSITE", "QQQ is explicitly opposite SOXX.", True, True))
        if require_spy and spy == opp:
            codes.append(("WAIT_SPY_OPPOSITE", "SPY is explicitly opposite SOXX.", True, True))
        if any(c[0] in {"WAIT_QQQ_MIXED", "WAIT_SPY_MIXED", "WAIT_QQQ_OPPOSITE", "WAIT_SPY_OPPOSITE"} for c in codes):
            codes.insert(0, ("WAIT_BROAD_CONFIRMATION_MISSING", "Required broad confirmation is missing or opposite.", True, True))
    if not codes:
        codes.append(("PASS_STRICT_DIRECTION_CONFIRMED", "Strict official direction gate confirmed.", False, False))
    if soxx in {"BULLISH", "BEARISH"}:
        codes.append(("SHADOW_SEMICONDUCTOR_ONLY_DIRECTION_AVAILABLE", "SOXX-only shadow direction is available.", False, True))
        if relaxed_label(soxx, qqq, spy, require_spy) != "MIXED_OR_WAIT":
            codes.append(("SHADOW_RELAXED_BROAD_DIRECTION_AVAILABLE", "Relaxed broad shadow direction is available.", False, True))
    return [{"reason_rank": i, "reason_code": code, "reason_detail": detail, "official_gate_blocking": blocking, "shadow_relevant": shadow} for i, (code, detail, blocking, shadow) in enumerate(codes, start=1)]


def map_candidates(candidates: list[dict[str, str]], direction: str, mode: str, shadow: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    promoted, rejected = [], []
    bull = direction in {"BULL_SEMICONDUCTOR", "BULL_SEMICONDUCTOR_CONFIRMED"}
    bear = direction in {"BEAR_SEMICONDUCTOR", "BEAR_SEMICONDUCTOR_CONFIRMED"}
    for row in candidates:
        underlying = str(row.get("underlying", "")).upper()
        cp = str(row.get("call_put", "")).upper()
        promote = (bull and underlying == "SOXL" and cp == "CALL") or (bear and underlying == "SOXS" and cp == "CALL")
        action = "PROMOTE_SOXL_CALL_RESEARCH" if bull and promote else "PROMOTE_SOXS_CALL_RESEARCH" if bear and promote else "WAIT_OR_DIRECTION_MISMATCH"
        record = {
            "gate_mode": mode,
            "contract_id": row.get("contract_id", ""),
            "underlying": underlying,
            "expiration": row.get("expiration", ""),
            "dte": row.get("dte", ""),
            "strike": row.get("strike", ""),
            "call_put": cp,
            "bid": row.get("bid", ""),
            "ask": row.get("ask", ""),
            "mid": row.get("mid", ""),
            "spread_pct": row.get("spread_pct", ""),
            "volume": row.get("volume", ""),
            "direction_action": action,
            "direction_label": direction,
            "shadow_only": shadow,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "research_only": True,
        }
        if promote:
            promoted.append(record)
        else:
            rejected.append({**record, "reject_reason": "DIRECTION_MISMATCH_OR_WAIT"})
    return promoted, rejected


def report_text(summary: dict[str, Any]) -> str:
    return "\n".join(["V22.042 R2 Direction Gate Reason And Shadow Mode Audit", *[f"{k}={summary.get(k)}" for k in SUMMARY_FIELDS]]) + "\n"


def run(
    repo_root: Path,
    execute: bool = False,
    use_v22_041_latest: bool = True,
    require_qqq_confirmation: bool = True,
    require_spy_confirmation: bool = False,
    enable_shadow_modes: bool = True,
    v22_041_summary: dict[str, Any] | None = None,
    candidates: list[dict[str, str]] | None = None,
    v22_042_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    out = repo_root / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    if v22_041_summary is None or candidates is None or v22_042_summary is None:
        v41, cand, v42 = load_latest_inputs(repo_root) if use_v22_041_latest else ({}, [], {})
        v22_041_summary = v22_041_summary or v41
        candidates = candidates if candidates is not None else cand
        v22_042_summary = v22_042_summary or v42
    soxx = v22_042_summary.get("soxx_direction_label", "INTRADAY_DATA_INSUFFICIENT")
    qqq = v22_042_summary.get("qqq_confirmation_label", "INTRADAY_DATA_INSUFFICIENT")
    spy = v22_042_summary.get("spy_confirmation_label", "INTRADAY_DATA_INSUFFICIENT")
    intraday_available = bool(v22_042_summary.get("intraday_data_available", False))
    strict = strict_label(soxx, qqq, spy, require_qqq_confirmation, require_spy_confirmation)
    semi = semi_label(soxx) if enable_shadow_modes else "MIXED_OR_WAIT"
    relaxed = relaxed_label(soxx, qqq, spy, require_spy_confirmation) if enable_shadow_modes else "MIXED_OR_WAIT"
    v41_ok = bool(v22_041_summary) and int(v22_041_summary.get("liquidity_candidate_count", 0) or 0) > 0 and v22_041_summary.get("fallback_rows_used") is not True
    strict_promoted, strict_rejected = map_candidates(candidates if v41_ok else [], strict, "strict_official_gate", False)
    semi_promoted, semi_rejected = map_candidates(candidates if v41_ok else [], semi, "semiconductor_only_shadow_gate", True)
    relaxed_promoted, relaxed_rejected = map_candidates(candidates if v41_ok else [], relaxed, "relaxed_broad_shadow_gate", True)
    reasons = reason_codes(v22_041_summary, soxx, qqq, spy, require_qqq_confirmation, require_spy_confirmation)
    primary = reasons[0]["reason_code"] if reasons else ""
    secondary = reasons[1]["reason_code"] if len(reasons) > 1 else ""
    if strict_promoted:
        decision = DECISION_STRICT
    elif semi_promoted or relaxed_promoted:
        decision = DECISION_SHADOW
    else:
        decision = DECISION_ALL_WAIT
    qqq_opposite = soxx in {"BULLISH", "BEARISH"} and qqq == opposite(soxx)
    spy_opposite = soxx in {"BULLISH", "BEARISH"} and spy == opposite(soxx)
    summary = {
        "module_id": MODULE_ID,
        "module_name": MODULE_NAME,
        "final_status": PASS_STATUS,
        "final_decision": decision,
        "execution_mode": "EXECUTE_READ_ONLY" if execute else "PLAN",
        "v22_041_summary_found": bool(v22_041_summary),
        "v22_041_liquidity_candidate_count": int(v22_041_summary.get("liquidity_candidate_count", 0) or 0) if v22_041_summary else 0,
        "v22_041_real_readonly_quote_verified": bool(v22_041_summary.get("real_readonly_quote_verified", False)),
        "v22_041_fallback_rows_used": bool(v22_041_summary.get("fallback_rows_used", False)),
        "intraday_data_available": intraday_available,
        "soxx_direction_label": soxx,
        "qqq_confirmation_label": qqq,
        "spy_confirmation_label": spy,
        "strict_official_final_direction_label": strict,
        "strict_official_wait_state": not bool(strict_promoted),
        "strict_official_promoted_candidate_count": len(strict_promoted),
        "semiconductor_only_shadow_direction_label": semi,
        "semiconductor_only_shadow_candidate_count": len(semi_promoted),
        "relaxed_broad_shadow_direction_label": relaxed,
        "relaxed_broad_shadow_candidate_count": len(relaxed_promoted),
        "primary_wait_reason_code": primary,
        "secondary_wait_reason_code": secondary,
        "broad_confirmation_missing": any(r["reason_code"] == "WAIT_BROAD_CONFIRMATION_MISSING" for r in reasons),
        "qqq_opposite_detected": qqq_opposite,
        "spy_opposite_detected": spy_opposite,
        "shadow_modes_enabled": enable_shadow_modes,
        "shadow_only_no_broker_action": True,
        "trade_context_used": False,
        "unlock_trade_called": False,
        "place_order_called": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "research_only": True,
    }
    mode_rows = [
        {"gate_mode": "strict_official_gate", "direction_label": strict, "wait_state": not bool(strict_promoted), "candidate_count": len(strict_promoted), "reason_code": primary, "official_gate": True, "shadow_only": False, "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True},
        {"gate_mode": "semiconductor_only_shadow_gate", "direction_label": semi, "wait_state": not bool(semi_promoted), "candidate_count": len(semi_promoted), "reason_code": "SHADOW_SEMICONDUCTOR_ONLY_DIRECTION_AVAILABLE" if semi_promoted else primary, "official_gate": False, "shadow_only": True, "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True},
        {"gate_mode": "relaxed_broad_shadow_gate", "direction_label": relaxed, "wait_state": not bool(relaxed_promoted), "candidate_count": len(relaxed_promoted), "reason_code": "SHADOW_RELAXED_BROAD_DIRECTION_AVAILABLE" if relaxed_promoted else primary, "official_gate": False, "shadow_only": True, "broker_action_allowed": False, "official_adoption_allowed": False, "research_only": True},
    ]
    write_csv(out / "direction_gate_reason_codes.csv", REASON_FIELDS, reasons)
    write_csv(out / "direction_gate_mode_comparison.csv", MODE_FIELDS, mode_rows)
    write_csv(out / "strict_official_direction_candidates.csv", CANDIDATE_FIELDS, strict_promoted)
    write_csv(out / "semiconductor_only_shadow_candidates.csv", CANDIDATE_FIELDS, semi_promoted)
    write_csv(out / "relaxed_broad_shadow_candidates.csv", CANDIDATE_FIELDS, relaxed_promoted)
    write_csv(out / "direction_gate_shadow_rejected_candidates.csv", REJECT_FIELDS, strict_rejected + semi_rejected + relaxed_rejected)
    write_json(out / "v22_042_r2_summary.json", summary)
    (out / "V22.042_R2_direction_gate_reason_and_shadow_mode_audit_report.txt").write_text(report_text(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--use-v22-041-latest", action="store_true", default=True)
    parser.add_argument("--no-use-v22-041-latest", dest="use_v22_041_latest", action="store_false")
    parser.add_argument("--require-qqq-confirmation", action="store_true", default=True)
    parser.add_argument("--no-require-qqq-confirmation", dest="require_qqq_confirmation", action="store_false")
    parser.add_argument("--require-spy-confirmation", action="store_true", default=False)
    parser.add_argument("--enable-shadow-modes", action="store_true", default=True)
    parser.add_argument("--disable-shadow-modes", dest="enable_shadow_modes", action="store_false")
    args = parser.parse_args(argv)
    summary = run(args.repo_root, args.execute, args.use_v22_041_latest, args.require_qqq_confirmation, args.require_spy_confirmation, args.enable_shadow_modes)
    for key in SUMMARY_FIELDS:
        print(f"{key}={summary.get(key)}")
    print(f"summary_path={args.repo_root / OUT_REL / 'v22_042_r2_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
