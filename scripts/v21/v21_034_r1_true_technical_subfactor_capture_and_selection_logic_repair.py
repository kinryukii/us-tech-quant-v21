#!/usr/bin/env python
"""V21.034-R1 true technical subfactor capture and selection logic repair.

Research-only repair-plan stage. It maps available granular technical fields,
assesses true reweighting readiness, and hardens future best-variant selection
rules after V21.033-R1A diagnosed a no-op/tie artifact.
"""

from __future__ import annotations

import csv
import math
import re
from datetime import UTC, datetime
from pathlib import Path


STAGE = "V21.034-R1_TRUE_TECHNICAL_SUBFACTOR_CAPTURE_AND_SELECTION_LOGIC_REPAIR"
PASS_STATUS = "PASS_V21_034_R1_TRUE_TECHNICAL_SUBFACTOR_REPAIR_READY"
PARTIAL_STATUS = "PARTIAL_PASS_V21_034_R1_TRUE_SUBFACTOR_CAPTURE_LIMITED"
BLOCKED_STATUS = "BLOCKED_V21_034_R1_INPUTS_MISSING"
DECISION = "TRUE_TECHNICAL_SUBFACTOR_CAPTURE_REPAIR_READY_SELECTION_LOGIC_HARDENED_OFFICIAL_UPDATE_BLOCKED"

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "outputs" / "v21" / "factors"
READ_CENTER_DIR = ROOT / "outputs" / "v21" / "read_center"

V32_SUMMARY = OUT_DIR / "V21_032_R1_TECHNICAL_VARIANT_BACKTEST_SUMMARY.csv"
V33_SUMMARY = OUT_DIR / "V21_033_R1_TECHNICAL_VARIANT_ROBUSTNESS_SUMMARY.csv"
V33A_SUMMARY = OUT_DIR / "V21_033_R1A_TECHNICAL_VARIANT_SELECTION_DIAGNOSTIC_SUMMARY.csv"
V33A_DELTA = OUT_DIR / "V21_033_R1A_TECHNICAL_VARIANT_SCORE_RANK_DELTA_AUDIT.csv"

SUMMARY_OUT = OUT_DIR / "V21_034_R1_TRUE_TECHNICAL_SUBFACTOR_REPAIR_SUMMARY.csv"
SOURCE_MAP_OUT = OUT_DIR / "V21_034_R1_TECHNICAL_SUBFACTOR_SOURCE_MAP.csv"
READINESS_OUT = OUT_DIR / "V21_034_R1_TRUE_REWEIGHTING_READINESS_MATRIX.csv"
RULES_OUT = OUT_DIR / "V21_034_R1_VARIANT_SELECTION_RULE_REPAIR_SPEC.csv"
QUEUE_OUT = OUT_DIR / "V21_034_R1_TECHNICAL_REPAIR_QUEUE.csv"
REPORT_OUT = READ_CENTER_DIR / "V21_034_R1_TRUE_TECHNICAL_SUBFACTOR_CAPTURE_AND_SELECTION_LOGIC_REPAIR_REPORT.md"

REQUIRED_INPUTS = [V32_SUMMARY, V33_SUMMARY, V33A_SUMMARY, V33A_DELTA]

SUBFACTORS = [
    "RSI", "RSI_SLOPE", "KDJ_K", "KDJ_D", "KDJ_J", "KDJ_CROSS", "MACD", "MACD_SIGNAL",
    "MACD_HIST", "BB_POSITION", "BB_WIDTH", "BB_WIDTH_CHANGE", "MA20_DISTANCE", "MA50_DISTANCE",
    "EMA20_DISTANCE", "VOLUME_RATIO", "VOLUME_TREND", "VOLATILITY", "MOMENTUM", "BREAKOUT",
    "PULLBACK", "OVERHEAT", "TECHNICAL_SCORE", "STRATEGY_SCORE", "RISK_SCORE", "FINAL_SCORE",
    "FORWARD_RETURN_5D", "FORWARD_RETURN_10D", "FORWARD_RETURN_20D", "FORWARD_RETURN_60D",
]

RAW_REQUIRED = {
    "RSI", "KDJ_K", "KDJ_D", "KDJ_J", "MACD", "MACD_SIGNAL", "MACD_HIST", "BB_POSITION",
    "BB_WIDTH", "MA20_DISTANCE", "MA50_DISTANCE", "EMA20_DISTANCE", "VOLUME_RATIO", "VOLATILITY",
}

PATTERNS = {
    "RSI": [r"(^|_)rsi($|_)"],
    "RSI_SLOPE": [r"rsi.*slope", r"rsi.*change"],
    "KDJ_K": [r"kdj.*(^|_)k($|_)", r"(^|_)k_value($|_)"],
    "KDJ_D": [r"kdj.*(^|_)d($|_)", r"(^|_)d_value($|_)"],
    "KDJ_J": [r"kdj.*(^|_)j($|_)", r"(^|_)j_value($|_)"],
    "KDJ_CROSS": [r"kdj.*cross", r"stoch.*cross"],
    "MACD": [r"(^|_)macd($|_)", r"macd_line"],
    "MACD_SIGNAL": [r"macd.*signal"],
    "MACD_HIST": [r"macd.*hist", r"macd.*bar"],
    "BB_POSITION": [r"bb.*position", r"bollinger.*position", r"bb.*pct"],
    "BB_WIDTH": [r"bb.*width", r"bollinger.*width"],
    "BB_WIDTH_CHANGE": [r"bb.*width.*change", r"bollinger.*width.*change"],
    "MA20_DISTANCE": [r"ma20.*distance", r"distance.*ma20", r"sma20.*distance"],
    "MA50_DISTANCE": [r"ma50.*distance", r"distance.*ma50", r"sma50.*distance"],
    "EMA20_DISTANCE": [r"ema20.*distance", r"distance.*ema20"],
    "VOLUME_RATIO": [r"volume.*ratio", r"relative.*volume"],
    "VOLUME_TREND": [r"volume.*trend", r"volume.*slope"],
    "VOLATILITY": [r"volatility", r"atr", r"stddev"],
    "MOMENTUM": [r"momentum"],
    "BREAKOUT": [r"breakout"],
    "PULLBACK": [r"pullback"],
    "OVERHEAT": [r"overheat", r"overbought"],
    "TECHNICAL_SCORE": [r"technical_score", r"normalized_technical_score"],
    "STRATEGY_SCORE": [r"strategy_score", r"normalized_strategy_score"],
    "RISK_SCORE": [r"risk_score", r"normalized_risk_score"],
    "FINAL_SCORE": [r"baseline_score", r"baseline_detected_score", r"final_score", r"^score$"],
    "FORWARD_RETURN_5D": [r"forward_return_5d"],
    "FORWARD_RETURN_10D": [r"forward_return_10d"],
    "FORWARD_RETURN_20D": [r"forward_return_20d"],
    "FORWARD_RETURN_60D": [r"forward_return_60d"],
}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in fields})


def fmt(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.10f}"
    return value


def fnum(value: object) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def first(rows: list[dict[str, str]]) -> dict[str, str]:
    return rows[0] if rows else {}


def yes(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def candidate_files() -> list[Path]:
    roots = [
        ROOT / "outputs" / "v20" / "consolidation",
        ROOT / "outputs" / "v20" / "factors",
        ROOT / "outputs" / "v20" / "backtest",
        ROOT / "outputs" / "v21" / "factors",
        ROOT / "outputs" / "v21" / "consolidation",
        ROOT / "outputs" / "v21" / "factor_backtest",
        ROOT / "outputs" / "v21" / "ablation",
        ROOT / "outputs" / "v21" / "read_center",
    ]
    files = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.csv"):
            files.append(path)
            if len(files) >= 600:
                return sorted(set(files))
    return sorted(set(files))


def header(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return next(csv.reader(handle), [])
    except (OSError, UnicodeDecodeError, StopIteration):
        return []


def role(path: Path) -> str:
    s = str(path).lower()
    if "consolidation" in s:
        return "CONSOLIDATION"
    if "factor_backtest" in s or "backtest" in s:
        return "BACKTEST_OR_SNAPSHOT"
    if "ablation" in s:
        return "ABLATION"
    if "factors" in s:
        return "V21_FACTORS"
    return "OTHER"


def detect_cols(headers: list[str], subfactor: str) -> list[str]:
    out = []
    for col in headers:
        ncol = norm(col)
        for pattern in PATTERNS[subfactor]:
            if re.search(pattern, ncol):
                if subfactor == "MACD" and ("signal" in ncol or "hist" in ncol):
                    continue
                out.append(col)
                break
    return sorted(set(out))


def count_column(path: Path, column: str) -> tuple[int, int, int, int]:
    non_null = 0
    total = 0
    dates = set()
    tickers = set()
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                total += 1
                value = row.get(column, "")
                if str(value).strip() != "":
                    non_null += 1
                date = row.get("as_of_date") or row.get("date") or row.get("_as_of_date")
                ticker = row.get("ticker") or row.get("_ticker")
                if date:
                    dates.add(date)
                if ticker:
                    tickers.add(ticker)
                if total >= 25000:
                    break
    except (OSError, UnicodeDecodeError):
        pass
    return non_null, max(0, total - non_null), len(dates), len(tickers)


def build_source_map() -> list[dict[str, object]]:
    headers_by_file = [(path, header(path)) for path in candidate_files()]
    rows = []
    for sub in SUBFACTORS:
        matches = []
        for path, cols in headers_by_file:
            detected = detect_cols(cols, sub)
            for col in detected:
                matches.append((path, col))
                if len(matches) >= 20:
                    break
            if len(matches) >= 20:
                break
        first_match = matches[0] if matches else (None, "")
        non_null = missing = dates = tickers = 0
        if first_match[0] is not None:
            non_null, missing, dates, tickers = count_column(first_match[0], first_match[1])
        required = sub in RAW_REQUIRED or sub.startswith("FORWARD_RETURN")
        detected_bool = bool(matches)
        usable_reweight = detected_bool and non_null > 0 and sub in RAW_REQUIRED
        usable_eval = detected_bool and non_null > 0 and (sub.startswith("FORWARD_RETURN") or sub in {"FINAL_SCORE", "TECHNICAL_SCORE"})
        value_type = "REALIZED_FORWARD_RETURN" if sub.startswith("FORWARD_RETURN") else "RAW_TECHNICAL_SUBFACTOR" if sub in RAW_REQUIRED else "SCORE_OR_CONTEXT"
        rows.append({
            "subfactor_name": sub,
            "required_for_true_reweighting": yes(sub in RAW_REQUIRED),
            "detected": yes(detected_bool),
            "detected_column_names": "; ".join(sorted({col for _path, col in matches})),
            "source_file_path": str(first_match[0].relative_to(ROOT)) if first_match[0] else "",
            "source_file_role": role(first_match[0]) if first_match[0] else "",
            "non_null_count": non_null,
            "missing_count": missing,
            "distinct_as_of_dates": dates,
            "distinct_tickers": tickers,
            "usable_for_reweighting": yes(usable_reweight),
            "usable_for_forward_return_evaluation": yes(usable_eval),
            "value_type": value_type,
            "normalization_required": yes(sub in RAW_REQUIRED),
            "directionality_known": yes(sub in {"TECHNICAL_SCORE", "STRATEGY_SCORE", "RISK_SCORE", "FINAL_SCORE"} or sub.startswith("FORWARD_RETURN")),
            "notes": "Detected and non-null." if detected_bool and non_null > 0 else "Missing or empty; record as unavailable for true reweighting.",
        })
    return rows


def has(source_map: list[dict[str, object]], sub: str) -> bool:
    row = next((r for r in source_map if r["subfactor_name"] == sub), {})
    return row.get("usable_for_reweighting") == "TRUE" or row.get("usable_for_forward_return_evaluation") == "TRUE"


def readiness(source_map: list[dict[str, object]], upstream_issue_confirmed: bool) -> list[dict[str, object]]:
    components = {
        "RAW_TECHNICAL_SUBFACTOR_COLUMNS": list(RAW_REQUIRED),
        "RSI_REWEIGHTING": ["RSI"],
        "KDJ_REWEIGHTING": ["KDJ_K", "KDJ_D", "KDJ_J"],
        "MACD_REWEIGHTING": ["MACD", "MACD_SIGNAL", "MACD_HIST"],
        "BB_REWEIGHTING": ["BB_POSITION", "BB_WIDTH"],
        "MA_EMA_REWEIGHTING": ["MA20_DISTANCE", "MA50_DISTANCE", "EMA20_DISTANCE"],
        "VOLUME_REWEIGHTING": ["VOLUME_RATIO"],
        "VOLATILITY_REWEIGHTING": ["VOLATILITY"],
        "MOMENTUM_DEDUPING": ["RSI", "KDJ_K", "MACD", "MOMENTUM"],
        "OVERHEAT_DOUBLE_PENALTY_AUDIT": ["OVERHEAT", "RISK_SCORE"],
        "FORWARD_RETURN_EVALUATION": ["FORWARD_RETURN_5D", "FORWARD_RETURN_10D", "FORWARD_RETURN_20D"],
        "BENCHMARK_COMPARISON": [],
        "VARIANT_SCORE_DELTA_VALIDATION": ["FINAL_SCORE", "TECHNICAL_SCORE"],
        "VARIANT_RANK_DELTA_VALIDATION": ["FINAL_SCORE"],
        "TOP_BUCKET_DELTA_VALIDATION": ["FINAL_SCORE"],
        "BEST_VARIANT_SELECTION_LOGIC": [],
    }
    rows = []
    for component, required in components.items():
        present = [item for item in required if has(source_map, item)]
        missing = [item for item in required if item not in present]
        true_ready = bool(required) and not missing and component not in {"FORWARD_RETURN_EVALUATION", "VARIANT_SCORE_DELTA_VALIDATION", "VARIANT_RANK_DELTA_VALIDATION", "TOP_BUCKET_DELTA_VALIDATION"}
        if component == "BEST_VARIANT_SELECTION_LOGIC":
            true_ready = True
            status = "REPAIR_SPEC_READY"
            reason = "Hard selection rules generated by this stage."
        elif missing:
            status = "NOT_READY"
            reason = "Required raw inputs missing or not usable."
        else:
            status = "READY"
            reason = "Required inputs are present in local artifacts."
        proxy_allowed = False if upstream_issue_confirmed and component in {"BEST_VARIANT_SELECTION_LOGIC", "VARIANT_SCORE_DELTA_VALIDATION", "VARIANT_RANK_DELTA_VALIDATION", "TOP_BUCKET_DELTA_VALIDATION", "RAW_TECHNICAL_SUBFACTOR_COLUMNS"} else False
        rows.append({
            "component": component,
            "readiness_status": status,
            "required_inputs_present": "|".join(present),
            "required_inputs_missing": "|".join(missing),
            "can_do_true_reweighting": yes(true_ready),
            "can_do_proxy_reweighting": yes(component in {"FORWARD_RETURN_EVALUATION", "BENCHMARK_COMPARISON"} and not upstream_issue_confirmed),
            "proxy_reweighting_allowed": yes(proxy_allowed),
            "reason": reason,
            "required_repair": "Add or expose required raw subfactor fields and rerun matured backtest." if missing else "Keep validation gate active.",
            "priority": "HIGH" if missing or component == "BEST_VARIANT_SELECTION_LOGIC" else "MEDIUM",
        })
    return rows


def rules() -> list[dict[str, object]]:
    names = [
        ("BEST_VARIANT_MUST_HAVE_POSITIVE_EXCESS_VS_BASELINE", "Previously best variant could be named with zero edge.", "Require mean_excess_vs_baseline > 0 across primary window/bucket and no negative robustness override."),
        ("BEST_VARIANT_MUST_CHANGE_SCORE", "Proxy variant could be a score no-op.", "Require nonzero score_changed_ratio before best selection."),
        ("BEST_VARIANT_MUST_CHANGE_RANK", "Proxy variant could preserve all ranks.", "Require nonzero rank_changed_ratio before best selection."),
        ("BEST_VARIANT_MUST_CHANGE_TOP_BUCKET_COMPOSITION", "Top bucket could be identical to baseline.", "Require TOP20 or primary top-bucket composition delta before naming best variant."),
        ("BEST_VARIANT_MUST_NOT_BE_SELECTED_BY_TIEBREAK_ONLY", "Tie/default ordering could assign best_shadow_variant_name.", "If all candidates tie baseline, set best_shadow_variant_name blank and status diagnostic-only."),
        ("BEST_VARIANT_MUST_PASS_HIT_RATE_GATE", "Hit-rate gate was only downstream.", "Require candidate_hit_rate >= baseline_hit_rate."),
        ("BEST_VARIANT_MUST_NOT_WORSEN_DOWNSIDE_GATE", "Downside degradation can be hidden by mean return.", "Require downside_rate <= baseline_downside_rate when available."),
        ("BEST_VARIANT_MUST_REPORT_SCORING_METHOD", "Scoring method quality can be ambiguous.", "Emit TRUE_SUBFACTOR_REWEIGHTING, PROXY_LIMITED, or PROXY_RESCORING for every variant."),
        ("PROXY_RESCORING_MUST_BE_LABELLED_LIMITED", "Proxy rescoring could look like true reweighting.", "Label proxy rescoring limited and block adoption-oriented interpretation."),
        ("PROXY_NOOP_CANNOT_BE_BEST_VARIANT", "No-op proxy could be selected as best.", "Block best selection when score/rank/top-bucket deltas are zero."),
        ("CURRENT_PENDING_OBSERVATIONS_EXCLUDED_FROM_REALIZED_EVIDENCE", "Immature observations cannot count as realized evidence.", "Exclude pending current observations from performance evaluation."),
        ("OFFICIAL_ADOPTION_ALWAYS_BLOCKED_IN_RESEARCH_STAGE", "Research stages must not mutate official state.", "Always set official adoption and mutation permissions FALSE."),
    ]
    return [{
        "rule_id": f"V21_034_R1_RULE_{idx:03d}",
        "rule_name": name,
        "applies_to_stage": "Future V21 technical variant backtests and adoption gates",
        "old_behavior": old,
        "new_required_behavior": new,
        "mandatory": "TRUE",
        "failure_status_if_violated": "BLOCK_BEST_VARIANT_SELECTION_AND_MARK_DIAGNOSTIC_ONLY",
        "rationale": "Prevents V21.032-R1 style no-op/tie artifact from being treated as a shadow edge.",
    } for idx, (name, old, new) in enumerate(names, start=1)]


def repair_queue(source_map: list[dict[str, object]]) -> list[dict[str, object]]:
    items = [
        ("RSI_FIELDS", "Technical raw factor source", "Add or expose granular RSI fields if missing.", "RSI|RSI_SLOPE", "rsi_value|rsi_slope"),
        ("KDJ_FIELDS", "Technical raw factor source", "Add or expose KDJ K/D/J and cross-state fields if missing.", "KDJ_K|KDJ_D|KDJ_J|KDJ_CROSS", "kdj_k|kdj_d|kdj_j|kdj_cross_state"),
        ("MACD_FIELDS", "Technical raw factor source", "Add or expose MACD line/signal/histogram fields if missing.", "MACD|MACD_SIGNAL|MACD_HIST", "macd_line|macd_signal|macd_hist"),
        ("BB_FIELDS", "Technical raw factor source", "Add BB position, width, and width-change fields if missing.", "BB_POSITION|BB_WIDTH|BB_WIDTH_CHANGE", "bb_position|bb_width|bb_width_change"),
        ("MA_EMA_DISTANCE", "Technical raw factor source", "Add MA/EMA distance fields.", "MA20_DISTANCE|MA50_DISTANCE|EMA20_DISTANCE", "ma20_distance|ma50_distance|ema20_distance"),
        ("VOLUME_CONFIRMATION", "Technical raw factor source", "Add volume confirmation fields.", "VOLUME_RATIO|VOLUME_TREND", "volume_ratio|volume_trend"),
        ("VOL_OVEREXTENSION", "Technical raw factor source", "Add volatility and overextension fields.", "VOLATILITY|OVERHEAT", "volatility|overheat_score"),
        ("RSI_REGIME_LABELS", "Market regime/context source", "Add trend/range regime labels for RSI interpretation.", "TREND_RANGE_CONTEXT", "rsi_regime_context"),
        ("DELTA_VALIDATION", "Variant selector", "Add score/rank delta validation before variant selection.", "variant_score|variant_rank|baseline_rank", "score_changed_ratio|rank_changed_ratio"),
        ("POSITIVE_EXCESS_GATE", "Variant selector", "Add strict positive-excess best-variant gate.", "forward_return_windows", "positive_excess_gate_pass"),
        ("BENCHMARK_DECOMP", "Adoption gate", "Add benchmark beta decomposition before any adoption gate.", "QQQ|SPY|SOXX benchmark returns", "benchmark_decomposition_status"),
    ]
    return [{
        "repair_item_id": f"V21_034_R1_REPAIR_{idx:03d}",
        "repair_target": target,
        "current_issue": issue,
        "proposed_fix": issue,
        "required_input_fields": inputs,
        "output_fields_to_add": outputs,
        "downstream_stage_affected": "V21.032/V21.033 technical variant research pipeline",
        "priority": "HIGH" if idx <= 10 else "MEDIUM",
        "official_use_allowed_after_repair": "FALSE",
        "shadow_use_allowed_after_repair": "TRUE",
        "notes": "Repair enables future shadow research only; official adoption remains separately blocked.",
    } for idx, (_key, target, issue, inputs, outputs) in enumerate(items, start=1)]


SUMMARY_FIELDS = [
    "stage", "final_status", "decision", "research_only", "official_use_allowed", "official_weight_mutation_allowed",
    "official_ranking_mutation_allowed", "trade_action_allowed", "broker_execution_allowed", "real_book_mutation_allowed",
    "upstream_v21_032_final_status", "upstream_v21_033_final_status", "upstream_v21_033_r1a_final_status",
    "upstream_issue_confirmed", "technical_subfactor_capture_ready", "true_subfactor_reweighting_ready",
    "proxy_reweighting_allowed", "no_op_variant_selection_blocked", "zero_excess_best_selection_blocked",
    "rank_unchanged_best_selection_blocked", "top_bucket_unchanged_best_selection_blocked",
    "best_variant_positive_excess_required", "best_variant_rank_delta_required", "best_variant_top_bucket_delta_required",
    "data_trust_alpha_weight_allowed", "next_recommended_stage",
]
SOURCE_FIELDS = [
    "subfactor_name", "required_for_true_reweighting", "detected", "detected_column_names", "source_file_path",
    "source_file_role", "non_null_count", "missing_count", "distinct_as_of_dates", "distinct_tickers",
    "usable_for_reweighting", "usable_for_forward_return_evaluation", "value_type", "normalization_required",
    "directionality_known", "notes",
]
READINESS_FIELDS = [
    "component", "readiness_status", "required_inputs_present", "required_inputs_missing", "can_do_true_reweighting",
    "can_do_proxy_reweighting", "proxy_reweighting_allowed", "reason", "required_repair", "priority",
]
RULE_FIELDS = [
    "rule_id", "rule_name", "applies_to_stage", "old_behavior", "new_required_behavior", "mandatory",
    "failure_status_if_violated", "rationale",
]
QUEUE_FIELDS = [
    "repair_item_id", "repair_target", "current_issue", "proposed_fix", "required_input_fields",
    "output_fields_to_add", "downstream_stage_affected", "priority", "official_use_allowed_after_repair",
    "shadow_use_allowed_after_repair", "notes",
]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    READ_CENTER_DIR.mkdir(parents=True, exist_ok=True)
    if any(not path.exists() or path.stat().st_size == 0 for path in REQUIRED_INPUTS):
        final_status = BLOCKED_STATUS
        source_map = []
        ready = []
        rule_rows = rules()
        queue = repair_queue([])
        upstream_issue = False
        s32 = s33 = s33a = {}
    else:
        s32, s33, s33a = first(read_csv(V32_SUMMARY)), first(read_csv(V33_SUMMARY)), first(read_csv(V33A_SUMMARY))
        upstream_issue = (
            s33a.get("variant_score_changed") == "FALSE"
            and s33a.get("variant_rank_changed") == "FALSE"
            and s33a.get("zero_excess_detected") == "TRUE"
        )
        source_map = build_source_map()
        ready = readiness(source_map, upstream_issue)
        rule_rows = rules()
        queue = repair_queue(source_map)
        raw_ready_count = sum(1 for row in source_map if row["subfactor_name"] in RAW_REQUIRED and row["usable_for_reweighting"] == "TRUE")
        final_status = PASS_STATUS if upstream_issue else PARTIAL_STATUS
        if raw_ready_count < max(3, len(RAW_REQUIRED) // 2):
            final_status = PARTIAL_STATUS

    raw_ready_count = sum(1 for row in source_map if row.get("subfactor_name") in RAW_REQUIRED and row.get("usable_for_reweighting") == "TRUE")
    capture_ready = raw_ready_count >= len(RAW_REQUIRED)
    true_ready = capture_ready and upstream_issue
    summary = [{
        "stage": STAGE,
        "final_status": final_status,
        "decision": DECISION,
        "research_only": "TRUE",
        "official_use_allowed": "FALSE",
        "official_weight_mutation_allowed": "FALSE",
        "official_ranking_mutation_allowed": "FALSE",
        "trade_action_allowed": "FALSE",
        "broker_execution_allowed": "FALSE",
        "real_book_mutation_allowed": "FALSE",
        "upstream_v21_032_final_status": s32.get("final_status", ""),
        "upstream_v21_033_final_status": s33.get("final_status", ""),
        "upstream_v21_033_r1a_final_status": s33a.get("final_status", ""),
        "upstream_issue_confirmed": yes(upstream_issue),
        "technical_subfactor_capture_ready": yes(capture_ready),
        "true_subfactor_reweighting_ready": yes(true_ready),
        "proxy_reweighting_allowed": "FALSE",
        "no_op_variant_selection_blocked": "TRUE",
        "zero_excess_best_selection_blocked": "TRUE",
        "rank_unchanged_best_selection_blocked": "TRUE",
        "top_bucket_unchanged_best_selection_blocked": "TRUE",
        "best_variant_positive_excess_required": "TRUE",
        "best_variant_rank_delta_required": "TRUE",
        "best_variant_top_bucket_delta_required": "TRUE",
        "data_trust_alpha_weight_allowed": "FALSE",
        "next_recommended_stage": "V21.035_R1_TRUE_TECHNICAL_SUBFACTOR_DATA_PRODUCER_AND_BACKTEST_REBUILD",
    }]
    write_csv(SUMMARY_OUT, summary, SUMMARY_FIELDS)
    write_csv(SOURCE_MAP_OUT, source_map or [{"subfactor_name": "INPUTS_MISSING", "detected": "FALSE", "usable_for_reweighting": "FALSE", "notes": "Required upstream inputs missing."}], SOURCE_FIELDS)
    write_csv(READINESS_OUT, ready or [{"component": "INPUTS_MISSING", "readiness_status": "BLOCKED", "proxy_reweighting_allowed": "FALSE", "reason": "Required upstream inputs missing."}], READINESS_FIELDS)
    write_csv(RULES_OUT, rule_rows, RULE_FIELDS)
    write_csv(QUEUE_OUT, queue, QUEUE_FIELDS)

    missing = [row["subfactor_name"] for row in source_map if row.get("required_for_true_reweighting") == "TRUE" and row.get("usable_for_reweighting") != "TRUE"]
    report = f"""# {STAGE}

Generated: {datetime.now(UTC).isoformat()}

## Final status and decision

- final_status: {final_status}
- decision: {DECISION}

## Summary of V21.032, V21.033, and V21.033-R1A findings

V21.032 final_status: {s32.get("final_status", "")}
V21.033 final_status: {s33.get("final_status", "")}
V21.033-R1A final_status: {s33a.get("final_status", "")}
Upstream no-op/tie issue confirmed: {yes(upstream_issue)}

## Why RSI_DEEMPHASIZED is not accepted

V21.033-R1A found zero excess, unchanged scores, unchanged ranks, and unchanged top buckets. RSI_DEEMPHASIZED remains rejected for shadow adoption and cannot support official adoption.

## Whether true technical subfactor columns were found

Raw technical subfactor usable count: {raw_ready_count} of {len(RAW_REQUIRED)} required fields. See `{SOURCE_MAP_OUT.relative_to(ROOT)}`.

## Missing or unusable subfactor columns

{", ".join(missing) if missing else "No required raw subfactor gaps detected."}

## Whether true reweighting is currently possible

true_subfactor_reweighting_ready: {yes(true_ready)}

## Why proxy reweighting was insufficient

Proxy reweighting was insufficient because prior candidate scoring did not change scores, ranks, or top-bucket composition, allowing a tie/default artifact to be named as best.

## New best-variant selection rules

See `{RULES_OUT.relative_to(ROOT)}`. Future best variants must have positive excess versus baseline, nonzero score delta, nonzero rank delta, and top-bucket composition delta.

## Repair queue

See `{QUEUE_OUT.relative_to(ROOT)}`.

## Why official mutation remains blocked

Official mutation remains blocked because this is a research-only repair-plan stage, all official mutation flags are FALSE, DATA_TRUST alpha weight remains disallowed, and true technical reweighting is not production-ready.

## Next recommended stage

{summary[0]["next_recommended_stage"]}
"""
    REPORT_OUT.write_text(report, encoding="utf-8")
    print(f"STAGE_NAME={STAGE}")
    print(f"final_status={final_status}")
    print(f"decision={DECISION}")
    print(f"upstream_issue_confirmed={yes(upstream_issue)}")
    print(f"technical_subfactor_capture_ready={yes(capture_ready)}")


if __name__ == "__main__":
    main()
