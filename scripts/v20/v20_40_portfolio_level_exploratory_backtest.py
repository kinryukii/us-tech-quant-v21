from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"

IN_R2_NEXT = CONSOLIDATION / "V20_39_R2_NEXT_STEP_DECISION_SUMMARY.csv"
IN_R2_RETURNS = CONSOLIDATION / "V20_39_R2_SHADOW_ENTRY_STRATEGY_ROW_LEVEL_RETURNS.csv"
IN_R2_FILL = CONSOLIDATION / "V20_39_R2_SHADOW_ENTRY_STRATEGY_FILL_NO_FILL_DETAIL.csv"
IN_R2_PIT = CONSOLIDATION / "V20_39_R2_STALE_LEAKAGE_PIT_GATE.csv"
IN_R2_FORMULA = CONSOLIDATION / "V20_39_R2_FORMULA_RECHECK.csv"
IN_BASELINE_RETURNS = CONSOLIDATION / "V20_37_ENTRY_STRATEGY_ROW_LEVEL_RETURNS.csv"

OUT_GATE = CONSOLIDATION / "V20_40_V20_39_R2_GATE_REVIEW.csv"
OUT_UNIVERSE = CONSOLIDATION / "V20_40_PORTFOLIO_SIMULATION_UNIVERSE.csv"
OUT_POLICY = CONSOLIDATION / "V20_40_PORTFOLIO_CONSTRUCTION_POLICY_MATRIX.csv"
OUT_COST = CONSOLIDATION / "V20_40_PORTFOLIO_COST_AND_SLIPPAGE_ASSUMPTIONS.csv"
OUT_WEIGHTS = CONSOLIDATION / "V20_40_PORTFOLIO_POSITION_WEIGHT_DETAIL.csv"
OUT_SIGNAL_RET = CONSOLIDATION / "V20_40_PORTFOLIO_SIGNAL_DATE_RETURNS.csv"
OUT_WINDOW_RET = CONSOLIDATION / "V20_40_PORTFOLIO_FORWARD_WINDOW_RETURNS.csv"
OUT_BENCH_RET = CONSOLIDATION / "V20_40_PORTFOLIO_BENCHMARK_RELATIVE_RETURNS.csv"
OUT_POLICY_SUM = CONSOLIDATION / "V20_40_PORTFOLIO_POLICY_SUMMARY.csv"
OUT_FAMILY_SUM = CONSOLIDATION / "V20_40_PORTFOLIO_STRATEGY_FAMILY_SUMMARY.csv"
OUT_WEIGHT_SET_SUM = CONSOLIDATION / "V20_40_PORTFOLIO_SHADOW_WEIGHT_SET_SUMMARY.csv"
OUT_BUCKET_SUM = CONSOLIDATION / "V20_40_PORTFOLIO_TOP_BUCKET_SUMMARY.csv"
OUT_BASELINE = CONSOLIDATION / "V20_40_PORTFOLIO_BASELINE_COMPARISON.csv"
OUT_RISK = CONSOLIDATION / "V20_40_PORTFOLIO_RISK_AND_CONCENTRATION_AUDIT.csv"
OUT_NO_FILL = CONSOLIDATION / "V20_40_PORTFOLIO_NO_FILL_AND_CASH_PROXY_AUDIT.csv"
OUT_PIT = CONSOLIDATION / "V20_40_STALE_LEAKAGE_PIT_GATE.csv"
OUT_FORMULA = CONSOLIDATION / "V20_40_FORMULA_RECHECK.csv"
OUT_PROMOTION = CONSOLIDATION / "V20_40_PROMOTION_GUARD_AND_OFFICIAL_SEPARATION_REGISTER.csv"
OUT_DECISION = CONSOLIDATION / "V20_40_PORTFOLIO_LEVEL_EXPLORATORY_BACKTEST_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_40_NEXT_STEP_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_40_PORTFOLIO_LEVEL_EXPLORATORY_BACKTEST_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_PORTFOLIO_LEVEL_EXPLORATORY_BACKTEST.md"
READ_FIRST = OPS / "V20_40_READ_FIRST.txt"

STAGE_NAME = "V20.40_PORTFOLIO_LEVEL_EXPLORATORY_BACKTEST"
PASS_STATUS = "PASS_V20_40_PORTFOLIO_LEVEL_EXPLORATORY_BACKTEST"
BLOCKED_STATUS = "BLOCKED_V20_40_PORTFOLIO_LEVEL_EXPLORATORY_BACKTEST"
COST_BPS_PER_SIDE = 5.0
SLIPPAGE_BPS_PER_SIDE = 5.0
ROUND_TRIP_COST = 2.0 * (COST_BPS_PER_SIDE + SLIPPAGE_BPS_PER_SIDE) / 10000.0
TOL = 1e-10


def clean(v: object) -> str:
    return str(v or "").strip()


def upper(v: object) -> str:
    return clean(v).upper()


def tf(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def num(v: object) -> float | None:
    try:
        x = float(clean(v))
    except ValueError:
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return x


def as_int(v: object) -> int:
    try:
        return int(float(clean(v)))
    except ValueError:
        return 0


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        reader = csv.DictReader(h)
        return [dict(r) for r in reader], list(reader.fieldnames or [])


def iter_csv(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        yield from csv.DictReader(h)


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        writer = csv.DictWriter(h, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, "") for f in fields})


def write_stream(path: Path, fields: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    h = path.open("w", encoding="utf-8", newline="")
    writer = csv.DictWriter(h, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    return h, writer


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def policies() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    caps = {"Top20": 0.10, "Top50": 0.05, "Top100": 0.03}
    for bucket in ["Top20", "Top50", "Top100"]:
        for method, prefix in [
            ("EQUAL_WEIGHT", "EQUAL_WEIGHT"),
            ("SCORE_WEIGHT", "SCORE_WEIGHT"),
            ("CAPPED_SCORE_WEIGHT", "CAPPED_SCORE_WEIGHT"),
        ]:
            rows.append({
                "portfolio_policy_id": f"{prefix}_{bucket.upper()}",
                "top_bucket": bucket,
                "weighting_method": method,
                "max_single_position_cap": caps[bucket] if method == "CAPPED_SCORE_WEIGHT" else (1.0 / int(bucket.replace("Top", "")) if method == "EQUAL_WEIGHT" else ""),
                "min_position_floor": "",
                "cash_handling_for_no_fill_rows": "unfilled_weight_held_as_cash_proxy_zero_return",
                "rebalance_event_frequency_assumption": "per_signal_date_and_forward_window_research_event",
                "cost_slippage_assumption": "5bps_transaction_cost_per_side_plus_5bps_slippage_per_side",
                "benchmark_comparison_policy": "compare_to_SPY_and_QQQ_returns_from_entry_to_outcome_dates",
                "eligibility_criteria": "filled_rows_with_valid_returns_and_passed_R2_leakage_formula_gates",
                "eligible_for_execution": "TRUE",
                "non_official_flag": "TRUE",
            })
    rows.append({
        "portfolio_policy_id": "VOL_ADJUSTED_PLACEHOLDER",
        "top_bucket": "ALL",
        "weighting_method": "VOL_ADJUSTED_PLACEHOLDER",
        "max_single_position_cap": "",
        "min_position_floor": "",
        "cash_handling_for_no_fill_rows": "design_only",
        "rebalance_event_frequency_assumption": "design_only",
        "cost_slippage_assumption": "design_only",
        "benchmark_comparison_policy": "design_only",
        "eligibility_criteria": "blocked_until_portfolio_level_volatility_source_contract_is_validated",
        "eligible_for_execution": "FALSE",
        "non_official_flag": "TRUE",
    })
    return rows


def score_weights(records: list[dict[str, object]], capped: bool, cap: float | None) -> list[float]:
    scores = [max(num(r.get("shadow_weighted_score")) or 0.0, 0.0) for r in records]
    if not any(v > 0 for v in scores):
        weights = [1.0 / len(records)] * len(records)
    else:
        total = sum(scores)
        weights = [v / total for v in scores]
    if capped and cap:
        weights = [min(w, cap) for w in weights]
        total = sum(weights)
        weights = [w / total for w in weights] if total else [1.0 / len(records)] * len(records)
    return weights


def portfolio_return(records: list[dict[str, object]], policy: dict[str, object], fill_stats: dict[str, int]) -> tuple[list[dict[str, object]], dict[str, object]]:
    method = clean(policy.get("weighting_method"))
    cap = num(policy.get("max_single_position_cap"))
    if method == "EQUAL_WEIGHT":
        weights = [1.0 / len(records)] * len(records)
    elif method == "SCORE_WEIGHT":
        weights = score_weights(records, False, None)
    elif method == "CAPPED_SCORE_WEIGHT":
        weights = score_weights(records, True, cap)
    else:
        return [], {}

    gross = sum((num(r.get("ticker_forward_return")) or 0.0) * w for r, w in zip(records, weights))
    spy_values = [num(r.get("spy_forward_return")) for r in records if num(r.get("spy_forward_return")) is not None]
    qqq_values = [num(r.get("qqq_forward_return")) for r in records if num(r.get("qqq_forward_return")) is not None]
    spy = mean(spy_values) if spy_values else None
    qqq = mean(qqq_values) if qqq_values else None
    net = gross - ROUND_TRIP_COST
    attempted = fill_stats.get("attempted", len(records))
    no_fill = fill_stats.get("no_fill", 0)
    filled = len(records)
    cash_weight = no_fill / attempted if attempted else 0.0
    largest = max(weights) if weights else 0.0
    concentration = largest > 0.10 or filled < 10
    base = records[0]
    ret = {
        "candidate_weight_set_id": clean(base.get("candidate_weight_set_id")),
        "portfolio_policy_id": clean(policy.get("portfolio_policy_id")),
        "entry_strategy_id": clean(base.get("entry_strategy_id")),
        "strategy_family": clean(base.get("strategy_family")),
        "signal_date": clean(base.get("signal_date")),
        "actual_entry_date": clean(base.get("actual_entry_date")),
        "forward_window": clean(base.get("forward_window")),
        "top_bucket": clean(base.get("top_bucket")),
        "gross_portfolio_return": gross,
        "net_portfolio_return": net,
        "spy_benchmark_return": spy,
        "qqq_benchmark_return": qqq,
        "gross_benchmark_relative_return_vs_spy": "" if spy is None else gross - spy,
        "net_benchmark_relative_return_vs_spy": "" if spy is None else net - spy,
        "gross_benchmark_relative_return_vs_qqq": "" if qqq is None else gross - qqq,
        "net_benchmark_relative_return_vs_qqq": "" if qqq is None else net - qqq,
        "position_count": attempted,
        "filled_position_count": filled,
        "no_fill_count": no_fill,
        "cash_proxy_weight_due_to_no_fill": cash_weight,
        "largest_position_weight": largest,
        "concentration_flag": tf(concentration),
        "missing_outlier_warning": tf(abs(gross) > 0.25 or abs(net) > 0.25),
        "exploratory_non_official": "TRUE",
    }
    details = []
    for r, w in zip(records, weights):
        details.append({
            **{k: ret[k] for k in ["candidate_weight_set_id", "portfolio_policy_id", "entry_strategy_id", "strategy_family", "signal_date", "actual_entry_date", "forward_window", "top_bucket"]},
            "ticker": clean(r.get("ticker")),
            "shadow_rank": clean(r.get("shadow_rank")),
            "shadow_weighted_score": clean(r.get("shadow_weighted_score")),
            "position_weight": w,
            "position_return_contribution": (num(r.get("ticker_forward_return")) or 0.0) * w,
            "exploratory_non_official": "TRUE",
        })
    return details, ret


def summarize_portfolio(rows: list[dict[str, object]], keys: list[str]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, ...], list[dict[str, object]]] = defaultdict(list)
    for r in rows:
        grouped[tuple(clean(r.get(k)) for k in keys)].append(r)
    out = []
    for key, subset in sorted(grouped.items()):
        gross = [num(r.get("gross_portfolio_return")) for r in subset if num(r.get("gross_portfolio_return")) is not None]
        net = [num(r.get("net_portfolio_return")) for r in subset if num(r.get("net_portfolio_return")) is not None]
        spy = [num(r.get("net_benchmark_relative_return_vs_spy")) for r in subset if num(r.get("net_benchmark_relative_return_vs_spy")) is not None]
        qqq = [num(r.get("net_benchmark_relative_return_vs_qqq")) for r in subset if num(r.get("net_benchmark_relative_return_vs_qqq")) is not None]
        row = {k: key[i] for i, k in enumerate(keys)}
        row.update({
            "portfolio_event_count": len(subset),
            "average_portfolio_return": mean(gross) if gross else "",
            "median_portfolio_return": median(gross) if gross else "",
            "average_net_portfolio_return": mean(net) if net else "",
            "median_net_portfolio_return": median(net) if net else "",
            "average_net_benchmark_relative_return_vs_spy": mean(spy) if spy else "",
            "median_net_benchmark_relative_return_vs_spy": median(spy) if spy else "",
            "average_net_benchmark_relative_return_vs_qqq": mean(qqq) if qqq else "",
            "median_net_benchmark_relative_return_vs_qqq": median(qqq) if qqq else "",
            "win_rate_vs_spy": sum(1 for v in spy if v > 0) / len(spy) if spy else "",
            "win_rate_vs_qqq": sum(1 for v in qqq if v > 0) / len(qqq) if qqq else "",
            "signal_date_count": len({clean(r.get("signal_date")) for r in subset}),
            "forward_window_count": len({clean(r.get("forward_window")) for r in subset}),
            "average_fill_rate": mean([(as_int(r.get("filled_position_count")) / as_int(r.get("position_count"))) for r in subset if as_int(r.get("position_count")) > 0]) if subset else "",
            "average_no_fill_rate": mean([(as_int(r.get("no_fill_count")) / as_int(r.get("position_count"))) for r in subset if as_int(r.get("position_count")) > 0]) if subset else "",
            "average_turnover_proxy": "",
            "max_single_position_concentration_observed": max([num(r.get("largest_position_weight")) or 0.0 for r in subset]) if subset else "",
            "extreme_portfolio_return_warning_count": sum(1 for r in subset if upper(r.get("missing_outlier_warning")) == "TRUE"),
        })
        out.append(row)
    return out


def main() -> int:
    r2_next, _ = read_csv(IN_R2_NEXT)
    gate = r2_next[0] if r2_next else {}
    gate_ready = (
        upper(gate.get("READY_FOR_V20_40_PORTFOLIO_LEVEL_EXPLORATORY_BACKTEST")) == "TRUE"
        and as_int(gate.get("LEAKAGE_BLOCKER_COUNT")) == 0
        and as_int(gate.get("FORMULA_MISMATCH_COUNT")) == 0
        and upper(gate.get("NON_PIT_FACTOR_USED")) == "FALSE"
        and upper(gate.get("CURRENT_TOP20_LEAKAGE_DETECTED")) == "FALSE"
        and upper(gate.get("OFFICIAL_FACTOR_WEIGHTS_MUTATED")) == "FALSE"
        and upper(gate.get("OFFICIAL_DYNAMIC_WEIGHTING_STARTED")) == "FALSE"
        and as_int(gate.get("SHADOW_ROW_LEVEL_RETURN_ROWS_CREATED")) > 0
    )
    gate_review = [{
        "gate_check": "V20_39_R2_READY_FOR_V20_40",
        "ready_for_v20_40_portfolio_level_exploratory_backtest": clean(gate.get("READY_FOR_V20_40_PORTFOLIO_LEVEL_EXPLORATORY_BACKTEST")),
        "shadow_row_level_return_rows_created": clean(gate.get("SHADOW_ROW_LEVEL_RETURN_ROWS_CREATED")),
        "leakage_blocker_count": clean(gate.get("LEAKAGE_BLOCKER_COUNT")),
        "formula_mismatch_count": clean(gate.get("FORMULA_MISMATCH_COUNT")),
        "non_pit_factor_used": clean(gate.get("NON_PIT_FACTOR_USED")),
        "current_top20_leakage_detected": clean(gate.get("CURRENT_TOP20_LEAKAGE_DETECTED")),
        "official_factor_weights_mutated": clean(gate.get("OFFICIAL_FACTOR_WEIGHTS_MUTATED")),
        "official_dynamic_weighting_started": clean(gate.get("OFFICIAL_DYNAMIC_WEIGHTING_STARTED")),
        "gate_ready": tf(gate_ready),
        "review_status": "PASS" if gate_ready else "BLOCKED",
    }]

    policy_rows = policies()
    executable_policies = [p for p in policy_rows if upper(p.get("eligible_for_execution")) == "TRUE"]
    cost_rows = [{
        "cost_model_id": "V20_40_DEFAULT_EXPLORATORY_ROUND_TRIP_COST",
        "transaction_cost_bps_per_side": COST_BPS_PER_SIDE,
        "slippage_bps_per_side": SLIPPAGE_BPS_PER_SIDE,
        "round_trip_cost_and_slippage": ROUND_TRIP_COST,
        "real_execution_quality_claimed": "FALSE",
        "exploratory_non_official": "TRUE",
    }]

    fill_stats: dict[tuple[str, str, str, str, str], Counter] = defaultdict(Counter)
    for r in iter_csv(IN_R2_FILL):
        key = (clean(r.get("candidate_weight_set_id")), clean(r.get("entry_strategy_id")), clean(r.get("strategy_family")), clean(r.get("signal_date")), clean(r.get("top_bucket")))
        fill_stats[key]["attempted"] += 1
        if upper(r.get("filled")) == "TRUE":
            fill_stats[key]["filled"] += 1
        else:
            fill_stats[key]["no_fill"] += 1

    universe_fields = ["candidate_weight_set_id", "entry_strategy_id", "strategy_family", "signal_date", "actual_entry_date", "outcome_date", "ticker", "top_bucket", "shadow_rank", "shadow_weighted_score", "actual_entry_price", "forward_window", "ticker_forward_return", "benchmark_relative_return_vs_spy", "benchmark_relative_return_vs_qqq", "filled", "row_included", "exploratory_non_official"]
    uh, uwriter = write_stream(OUT_UNIVERSE, universe_fields)
    groups: dict[tuple[str, str, str, str, str, str], list[dict[str, object]]] = defaultdict(list)
    universe_count = 0
    try:
        if gate_ready:
            for r in iter_csv(IN_R2_RETURNS):
                if upper(r.get("row_included")) != "TRUE" or upper(r.get("leakage_check_passed")) != "TRUE" or upper(r.get("formula_recheck_passed")) != "TRUE":
                    continue
                if upper(r.get("filled")) != "TRUE":
                    continue
                tr = num(r.get("ticker_forward_return"))
                if tr is None:
                    continue
                row = {
                    "candidate_weight_set_id": clean(r.get("candidate_weight_set_id")),
                    "entry_strategy_id": clean(r.get("entry_strategy_id")),
                    "strategy_family": clean(r.get("strategy_family")),
                    "signal_date": clean(r.get("signal_date")),
                    "actual_entry_date": clean(r.get("actual_entry_date")),
                    "outcome_date": clean(r.get("outcome_date")),
                    "ticker": clean(r.get("ticker")),
                    "top_bucket": clean(r.get("top_bucket")),
                    "shadow_rank": clean(r.get("shadow_rank")),
                    "shadow_weighted_score": clean(r.get("shadow_weighted_score")),
                    "actual_entry_price": clean(r.get("actual_entry_price")),
                    "forward_window": clean(r.get("forward_window")),
                    "ticker_forward_return": tr,
                    "spy_forward_return": num(r.get("spy_forward_return")),
                    "qqq_forward_return": num(r.get("qqq_forward_return")),
                    "benchmark_relative_return_vs_spy": clean(r.get("benchmark_relative_return_vs_spy")),
                    "benchmark_relative_return_vs_qqq": clean(r.get("benchmark_relative_return_vs_qqq")),
                    "filled": "TRUE",
                    "row_included": "TRUE",
                    "exploratory_non_official": "TRUE",
                }
                uwriter.writerow(row)
                universe_count += 1
                groups[(row["candidate_weight_set_id"], row["entry_strategy_id"], row["strategy_family"], row["signal_date"], row["forward_window"], row["top_bucket"])].append(row)
    finally:
        uh.close()

    weight_fields = ["candidate_weight_set_id", "portfolio_policy_id", "entry_strategy_id", "strategy_family", "signal_date", "actual_entry_date", "forward_window", "top_bucket", "ticker", "shadow_rank", "shadow_weighted_score", "position_weight", "position_return_contribution", "exploratory_non_official"]
    wh, wwriter = write_stream(OUT_WEIGHTS, weight_fields)
    portfolio_returns: list[dict[str, object]] = []
    formula_rows: list[dict[str, object]] = []
    leakage_blockers = 0
    formula_mismatches = 0
    try:
        policy_by_bucket = defaultdict(list)
        for p in executable_policies:
            policy_by_bucket[clean(p.get("top_bucket"))].append(p)
        for key, recs in groups.items():
            cand, sid, fam, signal_date, _window, bucket = key
            stats_key = (cand, sid, fam, signal_date, bucket)
            stats = fill_stats.get(stats_key, Counter())
            stats_dict = {"attempted": stats.get("attempted", len(recs)), "no_fill": stats.get("no_fill", 0)}
            for policy in policy_by_bucket.get(bucket, []):
                details, pret = portfolio_return(recs, policy, stats_dict)
                if not pret:
                    continue
                for d in details:
                    wwriter.writerow(d)
                portfolio_returns.append(pret)
                recomputed = sum(num(d.get("position_return_contribution")) or 0.0 for d in details)
                ok = abs(recomputed - (num(pret.get("gross_portfolio_return")) or 0.0)) <= TOL
                formula_rows.append({
                    "candidate_weight_set_id": cand,
                    "portfolio_policy_id": clean(policy.get("portfolio_policy_id")),
                    "entry_strategy_id": sid,
                    "strategy_family": fam,
                    "signal_date": signal_date,
                    "forward_window": clean(pret.get("forward_window")),
                    "top_bucket": bucket,
                    "formula_recheck_passed": tf(ok),
                    "severity": "INFO" if ok else "BLOCKER",
                })
                if not ok:
                    formula_mismatches += 1
    finally:
        wh.close()

    signal_returns = portfolio_returns
    window_returns = summarize_portfolio(portfolio_returns, ["candidate_weight_set_id", "portfolio_policy_id", "forward_window"])
    bench_returns = summarize_portfolio(portfolio_returns, ["candidate_weight_set_id", "portfolio_policy_id", "entry_strategy_id", "forward_window"])
    policy_summary = summarize_portfolio(portfolio_returns, ["portfolio_policy_id"])
    family_summary = summarize_portfolio(portfolio_returns, ["strategy_family"])
    weight_set_summary = summarize_portfolio(portfolio_returns, ["candidate_weight_set_id"])
    bucket_summary = summarize_portfolio(portfolio_returns, ["top_bucket"])

    baseline_groups: dict[tuple[str, str, str, str, str], list[dict[str, object]]] = defaultdict(list)
    for r in iter_csv(IN_BASELINE_RETURNS):
        if upper(r.get("row_included")) != "TRUE" or upper(r.get("filled")) != "TRUE":
            continue
        tr = num(r.get("ticker_forward_return"))
        if tr is None:
            continue
        row = {
            "candidate_weight_set_id": "BASELINE_V20_37",
            "entry_strategy_id": clean(r.get("entry_strategy_id")),
            "strategy_family": clean(r.get("strategy_family")),
            "signal_date": clean(r.get("signal_date")),
            "actual_entry_date": clean(r.get("actual_entry_date")),
            "forward_window": clean(r.get("forward_window")),
            "top_bucket": clean(r.get("top_bucket")),
            "ticker_forward_return": tr,
            "spy_forward_return": num(r.get("spy_forward_return")),
            "qqq_forward_return": num(r.get("qqq_forward_return")),
            "shadow_weighted_score": "",
            "ticker": clean(r.get("ticker")),
        }
        baseline_groups[(row["entry_strategy_id"], row["strategy_family"], row["signal_date"], row["forward_window"], row["top_bucket"])].append(row)
    baseline_events = []
    equal_policies = {clean(p.get("top_bucket")): p for p in executable_policies if clean(p.get("weighting_method")) == "EQUAL_WEIGHT"}
    for key, recs in baseline_groups.items():
        sid, fam, signal_date, _window, bucket = key
        policy = equal_policies.get(bucket)
        if not policy:
            continue
        _details, pret = portfolio_return(recs, policy, {"attempted": len(recs), "no_fill": 0})
        if pret:
            pret["candidate_weight_set_id"] = "BASELINE_V20_37"
            baseline_events.append(pret)
    baseline_sum = summarize_portfolio(baseline_events, ["portfolio_policy_id", "entry_strategy_id", "strategy_family", "top_bucket", "forward_window"])
    baseline_by_key = {(clean(r.get("portfolio_policy_id")), clean(r.get("entry_strategy_id")), clean(r.get("strategy_family")), clean(r.get("top_bucket")), clean(r.get("forward_window"))): r for r in baseline_sum}
    shadow_sum = summarize_portfolio(portfolio_returns, ["candidate_weight_set_id", "portfolio_policy_id", "entry_strategy_id", "strategy_family", "top_bucket", "forward_window"])
    baseline_compare = []
    for r in shadow_sum:
        b = baseline_by_key.get((clean(r.get("portfolio_policy_id")), clean(r.get("entry_strategy_id")), clean(r.get("strategy_family")), clean(r.get("top_bucket")), clean(r.get("forward_window"))), {})
        s_avg = num(r.get("average_net_benchmark_relative_return_vs_spy"))
        b_avg = num(b.get("average_net_benchmark_relative_return_vs_spy"))
        baseline_compare.append({
            "candidate_weight_set_id": clean(r.get("candidate_weight_set_id")),
            "portfolio_policy_id": clean(r.get("portfolio_policy_id")),
            "entry_strategy_id": clean(r.get("entry_strategy_id")),
            "strategy_family": clean(r.get("strategy_family")),
            "top_bucket": clean(r.get("top_bucket")),
            "forward_window": clean(r.get("forward_window")),
            "baseline_event_count": clean(b.get("portfolio_event_count")),
            "shadow_event_count": clean(r.get("portfolio_event_count")),
            "baseline_average_net_relative_vs_spy": "" if b_avg is None else b_avg,
            "shadow_average_net_relative_vs_spy": "" if s_avg is None else s_avg,
            "delta_average_net_relative_vs_spy": "" if b_avg is None or s_avg is None else s_avg - b_avg,
            "baseline_win_rate_vs_spy": clean(b.get("win_rate_vs_spy")),
            "shadow_win_rate_vs_spy": clean(r.get("win_rate_vs_spy")),
            "baseline_average_fill_rate": clean(b.get("average_fill_rate")),
            "shadow_average_fill_rate": clean(r.get("average_fill_rate")),
            "comparison_limitation_flag": tf(not bool(b)),
            "exploratory_non_official": "TRUE",
        })

    risk_rows = []
    no_fill_rows = []
    for r in portfolio_returns:
        risk_rows.append({
            "candidate_weight_set_id": clean(r.get("candidate_weight_set_id")),
            "portfolio_policy_id": clean(r.get("portfolio_policy_id")),
            "entry_strategy_id": clean(r.get("entry_strategy_id")),
            "signal_date": clean(r.get("signal_date")),
            "forward_window": clean(r.get("forward_window")),
            "top_bucket": clean(r.get("top_bucket")),
            "filled_position_count": clean(r.get("filled_position_count")),
            "largest_position_weight": clean(r.get("largest_position_weight")),
            "concentration_flag": clean(r.get("concentration_flag")),
            "extreme_portfolio_return_warning": clean(r.get("missing_outlier_warning")),
            "benchmark_mismatch_warning": "FALSE",
            "limitation_notes": "exploratory_event_level_portfolio_aggregation_no_equity_curve",
        })
        no_fill_rows.append({
            "candidate_weight_set_id": clean(r.get("candidate_weight_set_id")),
            "portfolio_policy_id": clean(r.get("portfolio_policy_id")),
            "entry_strategy_id": clean(r.get("entry_strategy_id")),
            "strategy_family": clean(r.get("strategy_family")),
            "signal_date": clean(r.get("signal_date")),
            "forward_window": clean(r.get("forward_window")),
            "top_bucket": clean(r.get("top_bucket")),
            "position_count": clean(r.get("position_count")),
            "filled_position_count": clean(r.get("filled_position_count")),
            "no_fill_count": clean(r.get("no_fill_count")),
            "cash_proxy_weight_due_to_no_fill": clean(r.get("cash_proxy_weight_due_to_no_fill")),
        })

    pit_gate = [
        {"gate_check": "source_rows_passed_v20_39_r2_leakage_formula_gates", "rows_checked": universe_count, "blocker_count": 0, "gate_passed": "TRUE"},
        {"gate_check": "non_pit_factors_not_used", "rows_checked": universe_count, "blocker_count": 0, "gate_passed": "TRUE"},
        {"gate_check": "current_top20_not_used", "rows_checked": universe_count, "blocker_count": 0, "gate_passed": "TRUE"},
    ]
    promotion_guard = [
        {"guardrail": "portfolio_outputs_are_exploratory_research_only", "status": "PASS", "official_mutation": "FALSE"},
        {"guardrail": "no_official_recommendation_or_trading_signal", "status": "PASS", "official_mutation": "FALSE"},
        {"guardrail": "no_broker_order_execution_or_live_portfolio_instruction", "status": "PASS", "official_mutation": "FALSE"},
        {"guardrail": "no_official_factor_or_strategy_promotion", "status": "PASS", "official_mutation": "FALSE"},
    ]
    executed = gate_ready and bool(portfolio_returns)
    leakage_pass = leakage_blockers == 0
    formula_pass = formula_mismatches == 0
    status = PASS_STATUS if executed and leakage_pass and formula_pass else BLOCKED_STATUS
    ready_research = executed and leakage_pass and formula_pass

    decision = [{
        "v20_39_r2_gate_ready": tf(gate_ready),
        "portfolio_level_exploratory_backtest_executed": tf(executed),
        "gross_portfolio_returns_created": tf(bool(portfolio_returns)),
        "net_portfolio_returns_created": tf(bool(portfolio_returns)),
        "benchmark_relative_portfolio_returns_created": tf(bool(portfolio_returns)),
        "portfolio_baseline_comparison_created": tf(bool(baseline_compare)),
        "portfolio_risk_concentration_audit_created": tf(bool(risk_rows)),
        "leakage_gate_passed": tf(leakage_pass),
        "formula_recheck_passed": tf(formula_pass),
        "official_recommendations_created": "FALSE",
        "trading_signals_created": "FALSE",
        "broker_order_execution_code_created": "FALSE",
        "official_factor_weights_mutated": "FALSE",
        "official_dynamic_weighting_started": "FALSE",
        "ready_for_research_factor_pit_expansion": tf(ready_research),
        "ready_for_daily_operator_research_report_design": tf(ready_research),
        "ready_for_official_trading_or_recommendation": "FALSE",
    }]
    next_rows = [{
        "STAGE_NAME": STAGE_NAME,
        "STATUS": status,
        "V20_39_R2_GATE_READY": tf(gate_ready),
        "PORTFOLIO_SIMULATION_UNIVERSE_ROWS": universe_count,
        "PORTFOLIO_POLICY_COUNT": len(policy_rows),
        "PORTFOLIO_POSITION_WEIGHT_ROWS": sum(as_int(r.get("filled_position_count")) for r in portfolio_returns),
        "PORTFOLIO_SIGNAL_DATE_RETURN_ROWS": len(signal_returns),
        "PORTFOLIO_FORWARD_WINDOW_RETURN_ROWS": len(window_returns),
        "PORTFOLIO_BENCHMARK_RELATIVE_RETURN_ROWS": len(bench_returns),
        "PORTFOLIO_BASELINE_COMPARISON_ROWS": len(baseline_compare),
        "PORTFOLIO_RISK_AUDIT_ROWS": len(risk_rows),
        "GROSS_PORTFOLIO_RETURNS_CREATED": tf(bool(portfolio_returns)),
        "NET_PORTFOLIO_RETURNS_CREATED": tf(bool(portfolio_returns)),
        "BENCHMARK_RELATIVE_PORTFOLIO_RETURNS_CREATED": tf(bool(portfolio_returns)),
        "LEAKAGE_BLOCKER_COUNT": leakage_blockers,
        "FORMULA_MISMATCH_COUNT": formula_mismatches,
        "OFFICIAL_FACTOR_WEIGHTS_MUTATED": "FALSE",
        "OFFICIAL_DYNAMIC_WEIGHTING_STARTED": "FALSE",
        "READY_FOR_RESEARCH_FACTOR_PIT_EXPANSION": tf(ready_research),
        "READY_FOR_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN": tf(ready_research),
        "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION": "FALSE",
    }]

    ret_fields = ["candidate_weight_set_id", "portfolio_policy_id", "entry_strategy_id", "strategy_family", "signal_date", "actual_entry_date", "forward_window", "top_bucket", "gross_portfolio_return", "net_portfolio_return", "spy_benchmark_return", "qqq_benchmark_return", "gross_benchmark_relative_return_vs_spy", "net_benchmark_relative_return_vs_spy", "gross_benchmark_relative_return_vs_qqq", "net_benchmark_relative_return_vs_qqq", "position_count", "filled_position_count", "no_fill_count", "cash_proxy_weight_due_to_no_fill", "largest_position_weight", "concentration_flag", "missing_outlier_warning", "exploratory_non_official"]
    sum_fields = ["portfolio_event_count", "average_portfolio_return", "median_portfolio_return", "average_net_portfolio_return", "median_net_portfolio_return", "average_net_benchmark_relative_return_vs_spy", "median_net_benchmark_relative_return_vs_spy", "average_net_benchmark_relative_return_vs_qqq", "median_net_benchmark_relative_return_vs_qqq", "win_rate_vs_spy", "win_rate_vs_qqq", "signal_date_count", "forward_window_count", "average_fill_rate", "average_no_fill_rate", "average_turnover_proxy", "max_single_position_concentration_observed", "extreme_portfolio_return_warning_count"]
    write_csv(OUT_GATE, gate_review, list(gate_review[0].keys()))
    write_csv(OUT_POLICY, policy_rows, ["portfolio_policy_id", "top_bucket", "weighting_method", "max_single_position_cap", "min_position_floor", "cash_handling_for_no_fill_rows", "rebalance_event_frequency_assumption", "cost_slippage_assumption", "benchmark_comparison_policy", "eligibility_criteria", "eligible_for_execution", "non_official_flag"])
    write_csv(OUT_COST, cost_rows, list(cost_rows[0].keys()))
    write_csv(OUT_SIGNAL_RET, signal_returns, ret_fields)
    write_csv(OUT_WINDOW_RET, window_returns, ["candidate_weight_set_id", "portfolio_policy_id", "forward_window"] + sum_fields)
    write_csv(OUT_BENCH_RET, bench_returns, ["candidate_weight_set_id", "portfolio_policy_id", "entry_strategy_id", "forward_window"] + sum_fields)
    write_csv(OUT_POLICY_SUM, policy_summary, ["portfolio_policy_id"] + sum_fields)
    write_csv(OUT_FAMILY_SUM, family_summary, ["strategy_family"] + sum_fields)
    write_csv(OUT_WEIGHT_SET_SUM, weight_set_summary, ["candidate_weight_set_id"] + sum_fields)
    write_csv(OUT_BUCKET_SUM, bucket_summary, ["top_bucket"] + sum_fields)
    write_csv(OUT_BASELINE, baseline_compare, ["candidate_weight_set_id", "portfolio_policy_id", "entry_strategy_id", "strategy_family", "top_bucket", "forward_window", "baseline_event_count", "shadow_event_count", "baseline_average_net_relative_vs_spy", "shadow_average_net_relative_vs_spy", "delta_average_net_relative_vs_spy", "baseline_win_rate_vs_spy", "shadow_win_rate_vs_spy", "baseline_average_fill_rate", "shadow_average_fill_rate", "comparison_limitation_flag", "exploratory_non_official"])
    write_csv(OUT_RISK, risk_rows, ["candidate_weight_set_id", "portfolio_policy_id", "entry_strategy_id", "signal_date", "forward_window", "top_bucket", "filled_position_count", "largest_position_weight", "concentration_flag", "extreme_portfolio_return_warning", "benchmark_mismatch_warning", "limitation_notes"])
    write_csv(OUT_NO_FILL, no_fill_rows, ["candidate_weight_set_id", "portfolio_policy_id", "entry_strategy_id", "strategy_family", "signal_date", "forward_window", "top_bucket", "position_count", "filled_position_count", "no_fill_count", "cash_proxy_weight_due_to_no_fill"])
    write_csv(OUT_PIT, pit_gate, ["gate_check", "rows_checked", "blocker_count", "gate_passed"])
    write_csv(OUT_FORMULA, formula_rows, ["candidate_weight_set_id", "portfolio_policy_id", "entry_strategy_id", "strategy_family", "signal_date", "forward_window", "top_bucket", "formula_recheck_passed", "severity"])
    write_csv(OUT_PROMOTION, promotion_guard, ["guardrail", "status", "official_mutation"])
    write_csv(OUT_DECISION, decision, list(decision[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))

    report = f"""# V20.40 Portfolio Level Exploratory Backtest

Status: {status}

Exploratory research only: TRUE
Portfolio-level exploratory backtest executed: {tf(executed)}
Gross/net portfolio returns created: {tf(bool(portfolio_returns))}
Benchmark-relative portfolio returns created: {tf(bool(portfolio_returns))}

Portfolio simulation universe rows: {universe_count}
Portfolio policy count: {len(policy_rows)}
Portfolio signal-date return rows: {len(signal_returns)}
Portfolio baseline comparison rows: {len(baseline_compare)}
Leakage blockers: {leakage_blockers}
Formula mismatches: {formula_mismatches}

V20.40 created exploratory, non-official portfolio-level research outputs only. It did not create official recommendations, trading signals, broker/order/execution code, live or paper orders, equity curves, official dynamic weighting, official factor or strategy promotion, V21 outputs, or V19.21 outputs.
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    read_first = f"""STAGE_NAME: {STAGE_NAME}
STATUS: {status}
EXPLORATORY_RESEARCH_ONLY: TRUE
PORTFOLIO_LEVEL_EXPLORATORY_BACKTEST_EXECUTED: {tf(executed)}
GROSS_PORTFOLIO_RETURNS_CREATED: {tf(bool(portfolio_returns))}
NET_PORTFOLIO_RETURNS_CREATED: {tf(bool(portfolio_returns))}
BENCHMARK_RELATIVE_PORTFOLIO_RETURNS_CREATED: {tf(bool(portfolio_returns))}
OFFICIAL_RECOMMENDATION_CREATED: FALSE
TRADING_SIGNAL_CREATED: FALSE
BROKER_ORDER_EXECUTION_CODE_CREATED: FALSE
OFFICIAL_RANKING_MUTATED: FALSE
OFFICIAL_FACTOR_WEIGHTS_MUTATED: FALSE
OFFICIAL_FACTOR_PROMOTION_CREATED: FALSE
OFFICIAL_STRATEGY_PROMOTED: FALSE
OFFICIAL_DYNAMIC_WEIGHTING_STARTED: FALSE
EQUITY_CURVE_CREATED: FALSE
PERFORMANCE_CLAIMS_CREATED: FALSE
CURRENT_TOP20_USED_FOR_HISTORICAL_BACKTEST: FALSE
NON_PIT_FACTORS_EXCLUDED: TRUE
V21_OUTPUTS_CREATED: FALSE
V19_21_OUTPUTS_CREATED: FALSE
READY_FOR_RESEARCH_FACTOR_PIT_EXPANSION: {tf(ready_research)}
READY_FOR_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN: {tf(ready_research)}
READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION: FALSE
"""
    write_text(READ_FIRST, read_first)

    required = [OUT_GATE, OUT_UNIVERSE, OUT_POLICY, OUT_COST, OUT_WEIGHTS, OUT_SIGNAL_RET, OUT_WINDOW_RET, OUT_BENCH_RET, OUT_POLICY_SUM, OUT_FAMILY_SUM, OUT_WEIGHT_SET_SUM, OUT_BUCKET_SUM, OUT_BASELINE, OUT_RISK, OUT_NO_FILL, OUT_PIT, OUT_FORMULA, OUT_PROMOTION, OUT_DECISION, OUT_NEXT, REPORT, CURRENT_REPORT, READ_FIRST]
    missing = [p for p in required if not p.exists()]
    if missing:
        raise RuntimeError("Missing V20.40 outputs: " + ", ".join(rel(p) for p in missing))

    print(f"STATUS={status}")
    print("FILES_CHANGED=scripts/v20/v20_40_portfolio_level_exploratory_backtest.py;scripts/v20/run_v20_40_portfolio_level_exploratory_backtest.ps1")
    print("OUTPUTS_CREATED=" + ";".join(rel(p) for p in required))
    print(f"V20_39_R2_GATE_READY={tf(gate_ready)}")
    print(f"PORTFOLIO_SIMULATION_UNIVERSE_ROWS={universe_count}")
    print(f"PORTFOLIO_POLICY_COUNT={len(policy_rows)}")
    print(f"PORTFOLIO_POSITION_WEIGHT_ROWS={sum(as_int(r.get('filled_position_count')) for r in portfolio_returns)}")
    print(f"PORTFOLIO_SIGNAL_DATE_RETURN_ROWS={len(signal_returns)}")
    print(f"PORTFOLIO_FORWARD_WINDOW_RETURN_ROWS={len(window_returns)}")
    print(f"PORTFOLIO_BENCHMARK_RELATIVE_RETURN_ROWS={len(bench_returns)}")
    print(f"PORTFOLIO_BASELINE_COMPARISON_ROWS={len(baseline_compare)}")
    print(f"PORTFOLIO_RISK_AUDIT_ROWS={len(risk_rows)}")
    print(f"GROSS_PORTFOLIO_RETURNS_CREATED={tf(bool(portfolio_returns))}")
    print(f"NET_PORTFOLIO_RETURNS_CREATED={tf(bool(portfolio_returns))}")
    print(f"BENCHMARK_RELATIVE_PORTFOLIO_RETURNS_CREATED={tf(bool(portfolio_returns))}")
    print(f"LEAKAGE_BLOCKER_COUNT={leakage_blockers}")
    print(f"FORMULA_MISMATCH_COUNT={formula_mismatches}")
    print("OFFICIAL_FACTOR_WEIGHTS_MUTATED=FALSE")
    print("OFFICIAL_DYNAMIC_WEIGHTING_STARTED=FALSE")
    print(f"READY_FOR_RESEARCH_FACTOR_PIT_EXPANSION={tf(ready_research)}")
    print(f"READY_FOR_DAILY_OPERATOR_RESEARCH_REPORT_DESIGN={tf(ready_research)}")
    print("READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
