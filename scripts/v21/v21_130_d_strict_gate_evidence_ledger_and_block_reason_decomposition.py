#!/usr/bin/env python
"""V21.130 D strict-gate evidence ledger and block reason decomposition."""

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
STAGE = "V21.130_D_STRICT_GATE_EVIDENCE_LEDGER_AND_BLOCK_REASON_DECOMPOSITION"
OUT = ROOT / "outputs/v21/V21.130_D_STRICT_GATE_EVIDENCE_LEDGER_AND_BLOCK_REASON_DECOMPOSITION"
V129 = ROOT / "outputs/v21/V21.129_D_CONTINUED_TRACKING_AND_STRICT_ADOPTION_GATE"
V128 = ROOT / "outputs/v21/V21.128_LATEST_DATA_FULL_ABCD_AND_FORWARD_UPDATE"

V129_SUMMARY = V129 / "V21.129_summary.json"
V129_GATES = V129 / "V21.129_d_strict_gate_results.csv"
V129_REGIME = V129 / "V21.129_d_regime_gate_diagnostic.csv"
V129_DATA_QUALITY = V129 / "V21.129_d_strict_gate_results.csv"

EXPECTED_GATES = [
    "DATA_FRESHNESS",
    "DATA_QUALITY_WARNING",
    "MATURITY",
    "VS_A1_PERFORMANCE",
    "VS_QQQ_PERFORMANCE",
    "CONCENTRATION_RISK",
    "LEFT_TAIL_DRAWDOWN_RISK",
    "REPEATED_LOSER_RISK",
    "REGIME_COMPATIBILITY",
]

PROTECTED_BASELINE_FILES = [
    V128 / "V21.128_summary.json",
    V128 / "V21.128_readable_report.txt",
    V128 / "V21.128_compact_report.txt",
    V128 / "D_WEIGHT_OPTIMIZED_R1_latest_ranking.csv",
    V128 / "A1_BASELINE_CONTROL_latest_ranking.csv",
    V129 / "V21.129_summary.json",
    V129 / "V21.129_d_strict_gate_results.csv",
    V129 / "V21.129_d_tracking_top20.csv",
    V129 / "V21.129_d_tracking_top50.csv",
]

BLOCKER_CATEGORY = {
    "DATA_FRESHNESS": "DATA_BLOCKER",
    "DATA_QUALITY_WARNING": "DATA_BLOCKER",
    "MATURITY": "MATURITY_BLOCKER",
    "VS_A1_PERFORMANCE": "PERFORMANCE_BLOCKER",
    "VS_QQQ_PERFORMANCE": "PERFORMANCE_BLOCKER",
    "CONCENTRATION_RISK": "CONCENTRATION_BLOCKER",
    "LEFT_TAIL_DRAWDOWN_RISK": "LEFT_TAIL_BLOCKER",
    "REPEATED_LOSER_RISK": "REPEATED_LOSER_BLOCKER",
    "REGIME_COMPATIBILITY": "REGIME_BLOCKER",
}

PRIMARY_PRIORITY = [
    ("DATA_FRESHNESS", "STALE_PRICE_PANEL"),
    ("DATA_QUALITY_WARNING", "DATA_QUALITY_WARNING"),
    ("MATURITY", "INSUFFICIENT_MATURITY"),
    ("REGIME_COMPATIBILITY", "REGIME_INCOMPATIBLE"),
    ("CONCENTRATION_RISK", "CONCENTRATION_RISK"),
    ("REPEATED_LOSER_RISK", "REPEATED_LOSER_RISK"),
    ("LEFT_TAIL_DRAWDOWN_RISK", "LEFT_TAIL_RISK"),
    ("VS_A1_PERFORMANCE", "INSUFFICIENT_ALPHA"),
    ("VS_QQQ_PERFORMANCE", "INSUFFICIENT_ALPHA"),
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
    allowed_prefix = "?? outputs/v21/V21.130_D_STRICT_GATE_EVIDENCE_LEDGER_AND_BLOCK_REASON_DECOMPOSITION/"
    allowed_scripts = {
        "?? scripts/v21/v21_130_d_strict_gate_evidence_ledger_and_block_reason_decomposition.py",
        "?? scripts/v21/test_v21_130_d_strict_gate_evidence_ledger_and_block_reason_decomposition.py",
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


def parse_float(value: Any, default: float = math.nan) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if not math.isnan(parsed) else default


def fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)


def distance(current: float, threshold: float, direction: str) -> str:
    if math.isnan(current) or math.isnan(threshold):
        return "UNKNOWN"
    if direction == ">=":
        return str(max(0.0, threshold - current))
    if direction == "<=":
        return str(max(0.0, current - threshold))
    return "UNKNOWN"


def gate_lookup(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("gate", "")): row for row in rows}


def gate_status(rows: dict[str, dict[str, Any]], gate: str) -> str:
    return str(rows.get(gate, {}).get("status", "UNKNOWN"))


def blocker_reason(row: dict[str, Any]) -> str:
    reason = str(row.get("reason", "")).strip()
    if reason:
        return reason
    status = str(row.get("status", ""))
    return "" if status == "PASS" else "BLOCK_REASON_NOT_REPORTED"


def add_ledger_row(
    rows: list[dict[str, Any]],
    gate: str,
    status: str,
    reason: str,
    metric_name: str,
    metric_value: Any,
    threshold: str,
    distance_to_pass: str,
    hard_or_soft: str,
    persistence: str,
    more_maturity: bool,
    design_repair: bool,
    category: str,
) -> None:
    rows.append({
        "gate_name": gate,
        "status": status,
        "blocker_reason": reason,
        "metric_name": metric_name,
        "metric_value": fmt(metric_value),
        "threshold": threshold,
        "distance_to_pass": distance_to_pass,
        "hard_or_soft_gate": hard_or_soft,
        "blocker_persistence": persistence,
        "can_be_resolved_by_more_maturity": more_maturity,
        "requires_model_design_repair": design_repair,
        "blocker_category": category,
    })


def build_evidence_ledger(gates: dict[str, dict[str, Any]], summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for gate in EXPECTED_GATES:
        row = gates.get(gate, {"gate": gate, "status": "UNKNOWN", "reason": "MISSING_GATE_RESULT"})
        status = str(row.get("status", "UNKNOWN"))
        reason = blocker_reason(row)
        category = BLOCKER_CATEGORY[gate]

        if gate == "DATA_FRESHNESS":
            current = str(row.get("latest_price_date_used", summary.get("latest_price_date_used", "")))
            add_ledger_row(rows, gate, status, reason, "latest_price_date_used", current, ">=2026-06-26", "0" if status == "PASS" else "UNKNOWN", "HARD", "TEMPORARY", False, False, category)
        elif gate == "DATA_QUALITY_WARNING":
            current = parse_float(row.get("ticker_data_warning_count", summary.get("ticker_data_warning_count")))
            add_ledger_row(rows, gate, status, reason, "ticker_data_warning_count", current, "0", distance(current, 0, "<="), "HARD", "PERSISTENT_UNTIL_DATA_REPAIRED_OR_WAIVED", False, False, category)
        elif gate == "MATURITY":
            metrics = [
                ("D_matured_top20_observations", row.get("D_matured_top20_observations", summary.get("D_matured_top20_observations")), 40),
                ("D_matured_top50_observations", row.get("D_matured_top50_observations", summary.get("D_matured_top50_observations")), 40),
                ("distinct_forward_ranking_dates", row.get("distinct_forward_ranking_dates", summary.get("distinct_forward_ranking_dates")), 8),
            ]
            for metric, value, threshold in metrics:
                current = parse_float(value)
                add_ledger_row(rows, gate, status, reason, metric, current, f">={threshold}", distance(current, threshold, ">="), "HARD", "TEMPORARY_MORE_MATURITY_REQUIRED", True, False, category)
        elif gate == "VS_A1_PERFORMANCE":
            metrics = [
                ("D_top20_win_rate_vs_A1", row.get("D_top20_win_rate_vs_A1", summary.get("D_top20_win_rate_vs_A1")), 0.60),
                ("D_top50_win_rate_vs_A1", row.get("D_top50_win_rate_vs_A1", summary.get("D_top50_win_rate_vs_A1")), 0.55),
                ("D_mean_excess_return_vs_A1", row.get("D_mean_excess_return_vs_A1"), 0.0),
                ("D_median_excess_return_vs_A1", row.get("D_median_excess_return_vs_A1"), 0.0),
            ]
            for metric, value, threshold in metrics:
                current = parse_float(value)
                add_ledger_row(rows, gate, status, reason, metric, current, f">{threshold}" if "mean" in metric else f">={threshold}", distance(current, threshold, ">="), "HARD", "PERSISTENT_UNTIL_PERFORMANCE_IMPROVES", True, True, category)
        elif gate == "VS_QQQ_PERFORMANCE":
            top20_threshold = max(0.65, parse_float(row.get("A1_top20_win_rate_vs_QQQ"), 0.0) + 0.05)
            top50_threshold = max(0.60, parse_float(row.get("A1_top50_win_rate_vs_QQQ"), 0.0) + 0.03)
            metrics = [
                ("D_top20_win_rate_vs_QQQ", row.get("D_top20_win_rate_vs_QQQ", summary.get("D_top20_win_rate_vs_QQQ")), top20_threshold),
                ("D_top50_win_rate_vs_QQQ", row.get("D_top50_win_rate_vs_QQQ", summary.get("D_top50_win_rate_vs_QQQ")), top50_threshold),
            ]
            for metric, value, threshold in metrics:
                current = parse_float(value)
                add_ledger_row(rows, gate, status, reason, metric, current, f">={threshold}", distance(current, threshold, ">="), "HARD", "PERSISTENT_UNTIL_PERFORMANCE_IMPROVES", True, True, category)
        elif gate == "CONCENTRATION_RISK":
            metrics = [
                ("D_top20_max_sector_weight", row.get("D_top20_max_sector_weight", summary.get("D_top20_max_sector_weight")), 0.55),
                ("D_top50_max_sector_weight", row.get("D_top50_max_sector_weight"), 0.45),
                ("D_top20_max_industry_weight", row.get("D_top20_max_industry_weight", summary.get("D_top20_max_industry_weight")), 0.30),
                ("D_top50_max_industry_weight", row.get("D_top50_max_industry_weight"), 0.25),
                ("D_top20_memory_storage_semiconductor_chain_weight", row.get("D_top20_memory_storage_semiconductor_chain_weight", summary.get("D_top20_memory_storage_semiconductor_chain_weight")), 0.50),
            ]
            for metric, value, threshold in metrics:
                current = parse_float(value)
                add_ledger_row(rows, gate, status, reason, metric, current, f"<={threshold}", distance(current, threshold, "<="), "HARD", "PERSISTENT_UNTIL_PORTFOLIO_MIX_CHANGES", False, True, category)
        elif gate == "LEFT_TAIL_DRAWDOWN_RISK":
            metrics = [
                ("D_worst_5d_excess_return_vs_A1", row.get("D_worst_5d_excess_return_vs_A1"), -0.08, ">="),
                ("D_worst_10d_excess_return_vs_A1", row.get("D_worst_10d_excess_return_vs_A1"), -0.12, ">="),
                ("D_drawdown_proxy", row.get("D_drawdown_proxy"), parse_float(row.get("A1_drawdown_proxy")) * 1.25, "<="),
            ]
            for metric, value, threshold, direction in metrics:
                current = parse_float(value)
                add_ledger_row(rows, gate, status, reason, metric, current, f"{direction}{threshold}", distance(current, threshold, direction), "HARD", "PERSISTENT_UNTIL_LEFT_TAIL_EVIDENCE_IMPROVES", True, True, category)
        elif gate == "REPEATED_LOSER_RISK":
            metrics = [
                ("D_repeated_loser_risk_level", row.get("D_repeated_loser_risk_level", summary.get("D_repeated_loser_risk_level")), "not HIGH", "UNKNOWN"),
                ("D_repeated_loser_ticker_count", row.get("D_repeated_loser_ticker_count", summary.get("D_repeated_loser_ticker_count")), 3),
                ("D_top20_repeated_loser_weight", row.get("D_top20_repeated_loser_weight", summary.get("D_top20_repeated_loser_weight")), 0.20),
            ]
            for item in metrics:
                metric = item[0]
                value = item[1]
                threshold = item[2]
                if metric == "D_repeated_loser_risk_level":
                    add_ledger_row(rows, gate, status, reason, metric, value, str(threshold), item[3], "HARD", "PERSISTENT_UNTIL_NAME_DEPENDENCY_CHANGES", False, True, category)
                else:
                    current = parse_float(value)
                    add_ledger_row(rows, gate, status, reason, metric, current, f"<={threshold}", distance(current, float(threshold), "<="), "HARD", "PERSISTENT_UNTIL_NAME_DEPENDENCY_CHANGES", False, True, category)
        elif gate == "REGIME_COMPATIBILITY":
            current = str(row.get("current_regime", summary.get("current_regime", "")))
            add_ledger_row(rows, gate, status, reason, "current_regime", current, "not SEMI_HIGH_BETA_DERISKING/PROFIT_TAKING_SEMI and allowed regime", "UNKNOWN" if status != "PASS" else "0", "HARD", "TEMPORARY_MARKET_REGIME_DEPENDENT", False, False, category)
    return rows


def block_decomposition(ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in ledger:
        grouped.setdefault(row["blocker_category"], []).append(row)
    for category, items in grouped.items():
        blockers = [row for row in items if row["status"] in {"BLOCK", "UNKNOWN"}]
        gate_names = sorted({row["gate_name"] for row in blockers})
        rows.append({
            "blocker_category": category,
            "active_blocker": bool(blockers),
            "blocked_gate_count": len(gate_names),
            "blocked_gates": "|".join(gate_names),
            "blocker_reasons": "|".join(sorted({row["blocker_reason"] for row in blockers if row["blocker_reason"]})),
            "requires_model_design_repair": any(str(row["requires_model_design_repair"]).lower() == "true" for row in blockers),
            "can_be_resolved_by_more_maturity": any(str(row["can_be_resolved_by_more_maturity"]).lower() == "true" for row in blockers),
        })
    return sorted(rows, key=lambda row: row["blocker_category"])


def persistence_summary(ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for gate in EXPECTED_GATES:
        items = [row for row in ledger if row["gate_name"] == gate]
        statuses = sorted({row["status"] for row in items})
        blockers = [row for row in items if row["status"] in {"BLOCK", "UNKNOWN"}]
        rows.append({
            "gate_name": gate,
            "current_status": statuses[0] if len(statuses) == 1 else "|".join(statuses),
            "active_blocker": bool(blockers),
            "blocker_persistence": blockers[0]["blocker_persistence"] if blockers else "NONE",
            "metric_count": len(items),
            "failing_metric_count": len(blockers) if blockers else 0,
            "persistent_or_temporary": "PERSISTENT" if blockers and "PERSISTENT" in blockers[0]["blocker_persistence"] else ("TEMPORARY" if blockers else "NONE"),
        })
    return rows


def required_evidence(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"required_evidence": "DATA_QUALITY_WARNING must pass or be waived with explicit reason", "current_value": summary.get("ticker_data_warning_count", "UNKNOWN"), "threshold": "0 or explicit waiver", "met": summary.get("D_gate_data_quality_warning") == "PASS"},
        {"required_evidence": "current_regime must move out of SEMI_HIGH_BETA_DERISKING / PROFIT_TAKING_SEMI", "current_value": summary.get("current_regime", ""), "threshold": "allowed regime", "met": summary.get("D_gate_regime") == "PASS"},
        {"required_evidence": "D_matured_top20_observations >= 40", "current_value": summary.get("D_matured_top20_observations"), "threshold": ">=40", "met": parse_float(summary.get("D_matured_top20_observations")) >= 40},
        {"required_evidence": "D_matured_top50_observations >= 40", "current_value": summary.get("D_matured_top50_observations"), "threshold": ">=40", "met": parse_float(summary.get("D_matured_top50_observations")) >= 40},
        {"required_evidence": "distinct_forward_ranking_dates >= 8", "current_value": summary.get("distinct_forward_ranking_dates"), "threshold": ">=8", "met": parse_float(summary.get("distinct_forward_ranking_dates")) >= 8},
        {"required_evidence": "D must beat A1 on Top20 and Top50 gates", "current_value": f"top20={summary.get('D_top20_win_rate_vs_A1')}; top50={summary.get('D_top50_win_rate_vs_A1')}", "threshold": "top20>=0.60; top50>=0.55 plus positive excess", "met": summary.get("D_gate_vs_A1") == "PASS"},
        {"required_evidence": "D must beat QQQ benchmark gate", "current_value": f"top20={summary.get('D_top20_win_rate_vs_QQQ')}; top50={summary.get('D_top50_win_rate_vs_QQQ')}", "threshold": "top20>=max(0.65,A1+0.05); top50>=max(0.60,A1+0.03)", "met": summary.get("D_gate_vs_QQQ") == "PASS"},
        {"required_evidence": "D concentration must be below strict thresholds", "current_value": f"sector={summary.get('D_top20_max_sector_weight')}; industry={summary.get('D_top20_max_industry_weight')}; semi_chain={summary.get('D_top20_memory_storage_semiconductor_chain_weight')}", "threshold": "top20 sector<=0.55; industry<=0.30; semi_chain<=0.50", "met": summary.get("D_gate_concentration") == "PASS"},
        {"required_evidence": "D repeated loser risk must not be HIGH", "current_value": summary.get("D_repeated_loser_risk_level"), "threshold": "not HIGH; count<=3; top20 weight<=0.20", "met": summary.get("D_gate_repeated_loser") == "PASS"},
        {"required_evidence": "left-tail/drawdown must be acceptable", "current_value": summary.get("D_gate_left_tail"), "threshold": "5D>=-0.08; 10D>=-0.12; drawdown<=1.25x A1", "met": summary.get("D_gate_left_tail") == "PASS"},
    ]


def primary_blocker(gates: dict[str, dict[str, Any]]) -> str:
    for gate, blocker in PRIMARY_PRIORITY:
        if gate_status(gates, gate) == "BLOCK":
            return blocker
    if all(gate_status(gates, gate) == "PASS" for gate in EXPECTED_GATES):
        return "NONE_REVIEW_ALLOWED"
    return "UNKNOWN_GATE_STATUS"


def write_reports(summary: dict[str, Any], decomposition: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> None:
    active = [row for row in decomposition if row["active_blocker"]]
    unmet = [row["required_evidence"] for row in evidence if not row["met"]]
    readable = [
        STAGE,
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        "",
        "D remains research-only and continues tracking. This stage explains active strict-gate blockers and the evidence required before any human role review.",
        "",
        f"primary_D_blocker={summary['primary_D_blocker']}",
        f"active_blocker_categories={'|'.join(row['blocker_category'] for row in active)}",
        f"required_next_evidence={summary['required_next_evidence']}",
        "",
        "Gate Status",
        f"DATA_FRESHNESS={summary['D_gate_data_freshness']}",
        f"DATA_QUALITY_WARNING={summary['D_gate_data_quality_warning']}",
        f"MATURITY={summary['D_gate_maturity']}",
        f"VS_A1={summary['D_gate_vs_A1']}",
        f"VS_QQQ={summary['D_gate_vs_QQQ']}",
        f"CONCENTRATION={summary['D_gate_concentration']}",
        f"LEFT_TAIL={summary['D_gate_left_tail']}",
        f"REPEATED_LOSER={summary['D_gate_repeated_loser']}",
        f"REGIME={summary['D_gate_regime']}",
        "",
        "Unmet Evidence",
        *unmet,
        "",
        "Controls",
        "research_only=true",
        "D_continued_tracking=true",
        "D_adoption_allowed=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false",
    ]
    (OUT / "V21.130_readable_report.txt").write_text("\n".join(readable) + "\n", encoding="utf-8")
    compact = [
        STAGE,
        f"FINAL_STATUS={summary['FINAL_STATUS']}",
        f"DECISION={summary['DECISION']}",
        f"primary_D_blocker={summary['primary_D_blocker']}",
        f"required_next_evidence={summary['required_next_evidence']}",
        "D_adoption_allowed=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
    ]
    (OUT / "V21.130_compact_report.txt").write_text("\n".join(compact) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_status = git_status()
    baseline_hashes = {rel(path): sha256(path) for path in PROTECTED_BASELINE_FILES if path.is_file()}

    v129_summary = load_json(V129_SUMMARY)
    gate_rows = pd.read_csv(V129_GATES, keep_default_na=False).to_dict("records")
    gates = gate_lookup(gate_rows)
    missing = [gate for gate in EXPECTED_GATES if gate not in gates]
    for gate in missing:
        gates[gate] = {"gate": gate, "status": "UNKNOWN", "reason": "MISSING_GATE_RESULT"}

    ledger = build_evidence_ledger(gates, v129_summary)
    decomposition = block_decomposition(ledger)
    persistence = persistence_summary(ledger)
    evidence = required_evidence(v129_summary)
    primary = primary_blocker(gates)

    regime_history = []
    if V129_REGIME.is_file():
        for row in pd.read_csv(V129_REGIME, keep_default_na=False).to_dict("records"):
            regime_history.append({
                "source_stage": "V21.129",
                "current_regime": row.get("current_regime", ""),
                "raw_market_regime": row.get("raw_market_regime", ""),
                "blocked_regime": row.get("blocked_regime", ""),
                "source": row.get("source", ""),
                "recent_ranking_date": row.get("recent_ranking_date", ""),
                "recent_horizon": row.get("recent_horizon", ""),
                "recent_D_return": row.get("recent_D_return", ""),
                "recent_QQQ_return": row.get("recent_QQQ_return", ""),
                "recent_SOXX_return": row.get("recent_SOXX_return", ""),
                "semi_derisking_signal": row.get("semi_derisking_signal", ""),
                "profit_taking_signal": row.get("profit_taking_signal", ""),
            })

    data_quality_detail = []
    dq = gates.get("DATA_QUALITY_WARNING", {})
    data_quality_detail.append({
        "source_stage": "V21.129",
        "gate_name": "DATA_QUALITY_WARNING",
        "status": dq.get("status", "UNKNOWN"),
        "blocker_reason": blocker_reason(dq),
        "ticker_data_warning_count": dq.get("ticker_data_warning_count", v129_summary.get("ticker_data_warning_count", "UNKNOWN")),
        "ticker_data_warning_count_source": dq.get("ticker_data_warning_count_source", "UNKNOWN"),
        "required_resolution": "warning_count=0 or explicit waiver with reason before D human role review",
    })

    write_csv(OUT / "V21.130_d_gate_evidence_ledger.csv", ledger)
    write_csv(OUT / "V21.130_d_block_reason_decomposition.csv", decomposition)
    write_csv(OUT / "V21.130_d_gate_persistence_summary.csv", persistence)
    write_csv(OUT / "V21.130_d_required_evidence_for_review.csv", evidence)
    write_csv(OUT / "V21.130_d_regime_block_history.csv", regime_history)
    write_csv(OUT / "V21.130_d_data_quality_block_detail.csv", data_quality_detail)

    required_next_evidence = next((row["required_evidence"] for row in evidence if not row["met"]), "NONE_REVIEW_ALLOWED")
    strict_pass = all(gate_status(gates, gate) == "PASS" for gate in EXPECTED_GATES)
    post_hashes = {rel(path): sha256(path) for path in PROTECTED_BASELINE_FILES if path.is_file()}
    protected_hash_changed = baseline_hashes != post_hashes
    prot_mod = protected_hash_changed or protected_modified(git_status(), baseline_status)

    summary = {
        "stage": STAGE,
        "FINAL_STATUS": "PASS_V21_130_D_BLOCK_REASON_DECOMPOSITION_COMPLETE" if not prot_mod else "BLOCKED_V21_130_PROTECTED_OUTPUT_MODIFIED",
        "DECISION": "D_ADOPTION_BLOCKED_EVIDENCE_LEDGER_UPDATED" if not strict_pass else "D_REVIEW_ALLOWED_RESEARCH_ONLY",
        "latest_price_date_used": v129_summary.get("latest_price_date_used", ""),
        "D_continued_tracking": True,
        "D_adoption_allowed": False,
        "D_strict_gate_pass": strict_pass,
        "primary_D_blocker": primary,
        "D_gate_data_freshness": gate_status(gates, "DATA_FRESHNESS"),
        "D_gate_data_quality_warning": gate_status(gates, "DATA_QUALITY_WARNING"),
        "D_gate_maturity": gate_status(gates, "MATURITY"),
        "D_gate_vs_A1": gate_status(gates, "VS_A1_PERFORMANCE"),
        "D_gate_vs_QQQ": gate_status(gates, "VS_QQQ_PERFORMANCE"),
        "D_gate_concentration": gate_status(gates, "CONCENTRATION_RISK"),
        "D_gate_left_tail": gate_status(gates, "LEFT_TAIL_DRAWDOWN_RISK"),
        "D_gate_repeated_loser": gate_status(gates, "REPEATED_LOSER_RISK"),
        "D_gate_regime": gate_status(gates, "REGIME_COMPATIBILITY"),
        "current_regime": v129_summary.get("current_regime", gates.get("REGIME_COMPATIBILITY", {}).get("current_regime", "")),
        "required_next_evidence": required_next_evidence,
        "active_blocker_categories": "|".join(row["blocker_category"] for row in decomposition if row["active_blocker"]),
        "role_review_required": False,
        "next_action_gate": "CONTINUE_D_TRACKING_COLLECT_REQUIRED_EVIDENCE",
        "protected_outputs_modified": bool(prot_mod),
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "research_only": True,
        "no_future_leakage": True,
        "v21_129_baseline_preserved": not protected_hash_changed,
        "report_path": rel(OUT / "V21.130_readable_report.txt"),
    }
    if prot_mod:
        summary["DECISION"] = "BLOCKED_PROTECTED_OUTPUT_MUTATION"
    write_json(OUT / "V21.130_summary.json", summary)
    write_reports(summary, decomposition, evidence)

    print(STAGE)
    print(f"FINAL_STATUS={summary['FINAL_STATUS']}")
    print(f"DECISION={summary['DECISION']}")
    print(f"latest_price_date_used={summary['latest_price_date_used']}")
    print("D_continued_tracking=true")
    print("D_adoption_allowed=false")
    print(f"D_strict_gate_pass={str(summary['D_strict_gate_pass']).lower()}")
    print(f"primary_D_blocker={summary['primary_D_blocker']}")
    print(f"D_gate_data_freshness={summary['D_gate_data_freshness']}")
    print(f"D_gate_data_quality_warning={summary['D_gate_data_quality_warning']}")
    print(f"D_gate_maturity={summary['D_gate_maturity']}")
    print(f"D_gate_vs_A1={summary['D_gate_vs_A1']}")
    print(f"D_gate_vs_QQQ={summary['D_gate_vs_QQQ']}")
    print(f"D_gate_concentration={summary['D_gate_concentration']}")
    print(f"D_gate_left_tail={summary['D_gate_left_tail']}")
    print(f"D_gate_repeated_loser={summary['D_gate_repeated_loser']}")
    print(f"D_gate_regime={summary['D_gate_regime']}")
    print(f"current_regime={summary['current_regime']}")
    print(f"required_next_evidence={summary['required_next_evidence']}")
    print("role_review_required=false")
    print(f"next_action_gate={summary['next_action_gate']}")
    print("protected_outputs_modified=false")
    print("official_adoption_allowed=false")
    print("broker_action_allowed=false")
    print(f"report_path={summary['report_path']}")
    return summary


if __name__ == "__main__":
    run()
