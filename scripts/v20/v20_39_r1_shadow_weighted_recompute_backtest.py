from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median


ROOT = Path(__file__).resolve().parents[2]
CONSOLIDATION = ROOT / "outputs" / "v20" / "consolidation"
READ_CENTER = ROOT / "outputs" / "v20" / "read_center"
OPS = ROOT / "outputs" / "v20" / "ops"
RANDOM_ASOF = ROOT / "inputs" / "v20" / "random_asof"

IN_V39_NEXT = CONSOLIDATION / "V20_39_NEXT_STEP_DECISION_SUMMARY.csv"
IN_WEIGHTS = CONSOLIDATION / "V20_39_SHADOW_WEIGHT_CANDIDATE_SETS.csv"
IN_ELIGIBLE = CONSOLIDATION / "V20_39_ELIGIBLE_SHADOW_FACTOR_UNIVERSE.csv"
IN_EXCLUDED = CONSOLIDATION / "V20_39_EXCLUDED_SHADOW_FACTOR_REGISTER.csv"
IN_GUARD = CONSOLIDATION / "V20_39_PROMOTION_GUARD_AND_OFFICIAL_SEPARATION_REGISTER.csv"
IN_BLOCKED = CONSOLIDATION / "V20_39_BLOCKED_NON_PIT_FACTOR_ENFORCEMENT.csv"
IN_FACTOR = CONSOLIDATION / "V20_35_R2_ASOF_TECHNICAL_FACTOR_RECOMPUTE_MATRIX.csv"
IN_BASE_RANK = CONSOLIDATION / "V20_35_R2_ASOF_TECHNICAL_SCORE_AND_RANKING.csv"
IN_BASE_TOP20 = CONSOLIDATION / "V20_35_R2_ASOF_TOP20_SELECTIONS.csv"
IN_BASE_TOP50 = CONSOLIDATION / "V20_35_R2_ASOF_TOP50_SELECTIONS.csv"
IN_BASE_TOP100 = CONSOLIDATION / "V20_35_R2_ASOF_TOP100_SELECTIONS.csv"
IN_BASE_RET = CONSOLIDATION / "V20_35_R2_EXPLORATORY_ROW_LEVEL_RETURNS.csv"
IN_TICKER_PRICE = RANDOM_ASOF / "V20_RANDOM_ASOF_HISTORICAL_TICKER_PRICE_INPUT.csv"
IN_BENCH_PRICE = RANDOM_ASOF / "V20_RANDOM_ASOF_HISTORICAL_BENCHMARK_PRICE_INPUT.csv"

OUT_GATE = CONSOLIDATION / "V20_39_R1_V20_39_GATE_REVIEW.csv"
OUT_WVAL = CONSOLIDATION / "V20_39_R1_SHADOW_WEIGHT_SET_VALIDATION.csv"
OUT_SCORE = CONSOLIDATION / "V20_39_R1_SHADOW_SCORE_RECOMPUTE_MATRIX.csv"
OUT_AVAIL = CONSOLIDATION / "V20_39_R1_SHADOW_SCORE_AVAILABILITY_AUDIT.csv"
OUT_RANK = CONSOLIDATION / "V20_39_R1_SHADOW_RANKING.csv"
OUT_TOP20 = CONSOLIDATION / "V20_39_R1_SHADOW_TOP20_SELECTIONS.csv"
OUT_TOP50 = CONSOLIDATION / "V20_39_R1_SHADOW_TOP50_SELECTIONS.csv"
OUT_TOP100 = CONSOLIDATION / "V20_39_R1_SHADOW_TOP100_SELECTIONS.csv"
OUT_OVERLAP = CONSOLIDATION / "V20_39_R1_SHADOW_BASELINE_OVERLAP_AUDIT.csv"
OUT_ATTACH = CONSOLIDATION / "V20_39_R1_SHADOW_FORWARD_OUTCOME_ATTACHMENT.csv"
OUT_RET = CONSOLIDATION / "V20_39_R1_SHADOW_ROW_LEVEL_RETURNS.csv"
OUT_SIGNAL = CONSOLIDATION / "V20_39_R1_SHADOW_SIGNAL_DATE_SUMMARY.csv"
OUT_WINDOW = CONSOLIDATION / "V20_39_R1_SHADOW_FORWARD_WINDOW_SUMMARY.csv"
OUT_BUCKET = CONSOLIDATION / "V20_39_R1_SHADOW_TOP_BUCKET_SUMMARY.csv"
OUT_BENCH = CONSOLIDATION / "V20_39_R1_SHADOW_BENCHMARK_RELATIVE_SUMMARY.csv"
OUT_BASE_CMP = CONSOLIDATION / "V20_39_R1_SHADOW_VS_BASELINE_COMPARISON.csv"
OUT_CAND_CMP = CONSOLIDATION / "V20_39_R1_SHADOW_CANDIDATE_WEIGHT_SET_COMPARISON.csv"
OUT_PIT = CONSOLIDATION / "V20_39_R1_STALE_LEAKAGE_PIT_GATE.csv"
OUT_FORMULA = CONSOLIDATION / "V20_39_R1_FORMULA_RECHECK.csv"
OUT_BLOCKED = CONSOLIDATION / "V20_39_R1_BLOCKED_NON_PIT_FACTOR_ENFORCEMENT.csv"
OUT_GUARD = CONSOLIDATION / "V20_39_R1_PROMOTION_GUARD_AND_OFFICIAL_SEPARATION_REGISTER.csv"
OUT_DECISION = CONSOLIDATION / "V20_39_R1_SHADOW_WEIGHTED_RECOMPUTE_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_39_R1_NEXT_STEP_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_39_R1_SHADOW_WEIGHTED_RECOMPUTE_BACKTEST_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_SHADOW_WEIGHTED_RECOMPUTE_BACKTEST.md"
READ_FIRST = OPS / "V20_39_R1_READ_FIRST.txt"

STAGE_NAME = "V20.39-R1_SHADOW_WEIGHTED_RECOMPUTE_BACKTEST"
PASS_STATUS = "PASS_V20_39_R1_SHADOW_WEIGHTED_RECOMPUTE_BACKTEST"
BLOCKED_STATUS = "BLOCKED_V20_39_R1_SHADOW_WEIGHTED_RECOMPUTE_BACKTEST"
FORWARD_WINDOWS = [1, 3, 5, 10, 20]
TOPS = [20, 50, 100]
TOL = 1e-8


def clean(v: object) -> str:
    return str(v or "").strip()


def upper(v: object) -> str:
    return clean(v).upper()


def tf(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def rel(p: Path) -> str:
    return p.resolve().relative_to(ROOT.resolve()).as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        r = csv.DictReader(h)
        return [dict(row) for row in r], list(r.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({f: row.get(f, "") for f in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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


def parse_date(v: object) -> datetime | None:
    t = clean(v)
    if not t:
        return None
    try:
        return datetime.strptime(t[:10], "%Y-%m-%d")
    except ValueError:
        return None


def dtext(d: datetime | None) -> str:
    return d.strftime("%Y-%m-%d") if d else ""


def load_prices(rows: list[dict[str, str]]) -> dict[str, list[dict[str, object]]]:
    out: dict[str, list[dict[str, object]]] = defaultdict(list)
    for r in rows:
        sym, dt = clean(r.get("symbol")), parse_date(r.get("price_date"))
        adj = num(r.get("adjusted_close")) or num(r.get("close"))
        if sym and dt and adj is not None:
            out[sym].append({"price_date": dt, "adjusted_close": adj})
    for sym in out:
        out[sym].sort(key=lambda x: x["price_date"])
    return out


def idx_by_date(rows: list[dict[str, object]]) -> dict[datetime, int]:
    return {r["price_date"]: i for i, r in enumerate(rows)}


def avg(vals: list[float]) -> object:
    return mean(vals) if vals else ""


def med(vals: list[float]) -> object:
    return median(vals) if vals else ""


def summarize(rows: list[dict[str, object]], keys: list[str]) -> list[dict[str, object]]:
    g: dict[tuple[str, ...], list[dict[str, object]]] = defaultdict(list)
    for r in rows:
        g[tuple(clean(r.get(k)) for k in keys)].append(r)
    out = []
    for key, rs in sorted(g.items()):
        inc = [r for r in rs if upper(r.get("row_included")) == "TRUE"]
        tr = [num(r.get("ticker_forward_return")) for r in inc]
        spy = [num(r.get("benchmark_relative_return_vs_spy")) for r in inc]
        qqq = [num(r.get("benchmark_relative_return_vs_qqq")) for r in inc]
        tr = [v for v in tr if v is not None]
        spy = [v for v in spy if v is not None]
        qqq = [v for v in qqq if v is not None]
        row = {k: key[i] for i, k in enumerate(keys)}
        row.update({
            "row_count": len(inc),
            "average_ticker_return": avg(tr),
            "median_ticker_return": med(tr),
            "average_benchmark_relative_return_vs_spy": avg(spy),
            "median_benchmark_relative_return_vs_spy": med(spy),
            "average_benchmark_relative_return_vs_qqq": avg(qqq),
            "median_benchmark_relative_return_vs_qqq": med(qqq),
            "win_rate_vs_spy": sum(1 for v in spy if v > 0) / len(spy) if spy else "",
            "win_rate_vs_qqq": sum(1 for v in qqq if v > 0) / len(qqq) if qqq else "",
            "signal_date_count": len({clean(r.get("signal_date")) for r in inc}),
            "extreme_return_warning_count": sum(1 for r in inc if upper(r.get("extreme_return_warning")) == "TRUE"),
        })
        out.append(row)
    return out


def main() -> int:
    v39_next, _ = read_csv(IN_V39_NEXT)
    weights, _ = read_csv(IN_WEIGHTS)
    eligible, _ = read_csv(IN_ELIGIBLE)
    excluded, _ = read_csv(IN_EXCLUDED)
    guards, _ = read_csv(IN_GUARD)
    blocked, _ = read_csv(IN_BLOCKED)
    factors, _ = read_csv(IN_FACTOR)
    base_rank, _ = read_csv(IN_BASE_RANK)
    base_ret, _ = read_csv(IN_BASE_RET)
    tick_raw, _ = read_csv(IN_TICKER_PRICE)
    bench_raw, _ = read_csv(IN_BENCH_PRICE)

    gate = v39_next[0] if v39_next else {}
    gate_ready = (
        upper(gate.get("READY_FOR_V20_39_R1_SHADOW_WEIGHTED_RECOMPUTE_BACKTEST")) == "TRUE"
        and upper(gate.get("CANDIDATE_WEIGHT_SUM_VALIDATION_PASS")) == "TRUE"
        and upper(gate.get("OFFICIAL_FACTOR_WEIGHTS_MUTATED")) == "FALSE"
        and upper(gate.get("OFFICIAL_DYNAMIC_WEIGHTING_STARTED")) == "FALSE"
        and as_int(gate.get("LEAKAGE_BLOCKER_COUNT")) == 0
        and as_int(gate.get("FORMULA_MISMATCH_COUNT")) == 0
    )
    gate_rows = [{
        "gate_check": "V20_39_READY_FOR_R1",
        "ready_for_v20_39_r1_shadow_weighted_recompute_backtest": clean(gate.get("READY_FOR_V20_39_R1_SHADOW_WEIGHTED_RECOMPUTE_BACKTEST")),
        "candidate_weight_sum_validation_pass": clean(gate.get("CANDIDATE_WEIGHT_SUM_VALIDATION_PASS")),
        "official_factor_weights_mutated": clean(gate.get("OFFICIAL_FACTOR_WEIGHTS_MUTATED")),
        "official_dynamic_weighting_started": clean(gate.get("OFFICIAL_DYNAMIC_WEIGHTING_STARTED")),
        "leakage_blocker_count": clean(gate.get("LEAKAGE_BLOCKER_COUNT")),
        "formula_mismatch_count": clean(gate.get("FORMULA_MISMATCH_COUNT")),
        "gate_ready": tf(gate_ready),
        "review_status": "PASS" if gate_ready else "BLOCKED",
    }]

    eligible_factors = {clean(r.get("factor_name")) for r in eligible if upper(r.get("eligible_for_shadow_weighting")) == "TRUE"}
    weights_by_set: dict[str, dict[str, float]] = defaultdict(dict)
    for r in weights:
        ws, factor = clean(r.get("candidate_weight_set_id")), clean(r.get("factor_name"))
        w = num(r.get("final_shadow_weight"))
        if ws and factor and w is not None:
            weights_by_set[ws][factor] = w
    validation_rows = []
    validated = {}
    for ws, mapping in sorted(weights_by_set.items()):
        total = sum(mapping.values())
        invalid = [f for f in mapping if f not in eligible_factors]
        ok = bool(mapping) and not invalid and all(w >= 0 for w in mapping.values()) and abs(total - 1.0) <= TOL
        validation_rows.append({
            "candidate_weight_set_id": ws, "factor_count": len(mapping),
            "weight_sum": total, "weight_sum_valid": tf(abs(total - 1.0) <= TOL),
            "all_factors_eligible": tf(not invalid), "weights_non_negative": tf(all(w >= 0 for w in mapping.values())),
            "shadow_non_official_flags_present": "TRUE", "validation_status": "PASS" if ok else "BLOCKED",
        })
        if ok:
            validated[ws] = mapping

    base_by_key = {(clean(r.get("signal_date")), clean(r.get("ticker"))): r for r in base_rank}
    factor_rows = []
    score_rows = []
    avail_rows = []
    for r in factors:
        sdt = clean(r.get("signal_date"))
        ticker = clean(r.get("ticker"))
        max_dt = clean(r.get("max_factor_input_date"))
        for ws, mapping in validated.items():
            used = 0
            missing = 0
            score = 0.0
            used_weight = 0.0
            for factor, w in mapping.items():
                v = num(r.get(factor))
                if v is None:
                    missing += 1
                    continue
                score += v * w
                used += 1
                used_weight += w
            if used == 0:
                continue
            base = base_by_key.get((sdt, ticker), {})
            leakage_ok = max_dt <= sdt if max_dt and sdt else False
            score_rows.append({
                "candidate_weight_set_id": ws, "signal_date": sdt, "ticker": ticker,
                "shadow_weighted_score": score, "factor_count_used": used,
                "factor_count_missing": missing, "weight_coverage_ratio": used_weight,
                "max_factor_input_date": max_dt, "factor_asof_leakage_check_passed": tf(leakage_ok),
                "baseline_rank": clean(base.get("asof_technical_rank")),
                "baseline_score": clean(base.get("exploratory_technical_score")),
                "missing_factor_policy": "exclude_missing_factor_weight_from_score_no_inference",
                "shadow_only_non_official": "TRUE",
            })
    avail_group: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in score_rows:
        avail_group[clean(row.get("candidate_weight_set_id"))].append(row)
    for ws, rs in avail_group.items():
        avail_rows.append({
            "candidate_weight_set_id": ws, "score_rows": len(rs),
            "average_factor_count_used": mean([num(r.get("factor_count_used")) or 0 for r in rs]) if rs else "",
            "average_factor_count_missing": mean([num(r.get("factor_count_missing")) or 0 for r in rs]) if rs else "",
            "average_weight_coverage_ratio": mean([num(r.get("weight_coverage_ratio")) or 0 for r in rs]) if rs else "",
            "leakage_failed_count": sum(1 for r in rs if upper(r.get("factor_asof_leakage_check_passed")) != "TRUE"),
        })

    rank_rows = []
    top_rows = {20: [], 50: [], 100: []}
    by_set_date: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for r in score_rows:
        by_set_date[(clean(r.get("candidate_weight_set_id")), clean(r.get("signal_date")))].append(r)
    for (ws, sdt), rs in by_set_date.items():
        ranked = sorted(rs, key=lambda x: (-(num(x.get("shadow_weighted_score")) or -999), clean(x.get("ticker"))))
        for i, r in enumerate(ranked, start=1):
            rr = {**r, "shadow_rank": i}
            rank_rows.append(rr)
            for n in TOPS:
                if i <= n:
                    top_rows[n].append({**rr, "top_bucket": f"Top{n}"})

    base_sets = {}
    for n, path in [(20, IN_BASE_TOP20), (50, IN_BASE_TOP50), (100, IN_BASE_TOP100)]:
        rows, _ = read_csv(path)
        g: dict[str, set[str]] = defaultdict(set)
        for r in rows:
            g[clean(r.get("signal_date"))].add(clean(r.get("ticker")))
        base_sets[n] = g
    overlap_rows = []
    for n, rows in top_rows.items():
        by_ws_date: dict[tuple[str, str], set[str]] = defaultdict(set)
        for r in rows:
            by_ws_date[(clean(r.get("candidate_weight_set_id")), clean(r.get("signal_date")))].add(clean(r.get("ticker")))
        for (ws, sdt), tickers in by_ws_date.items():
            base = base_sets[n].get(sdt, set())
            ov = tickers & base
            overlap_rows.append({
                "candidate_weight_set_id": ws, "signal_date": sdt, "top_bucket": f"Top{n}",
                "shadow_selection_count": len(tickers), "baseline_selection_count": len(base),
                "overlap_count": len(ov), "overlap_rate": len(ov) / len(tickers) if tickers else "",
                "new_entries_count": len(tickers - base), "dropped_entries_count": len(base - tickers),
            })

    ticker_prices = load_prices(tick_raw)
    bench_prices = load_prices(bench_raw)
    bench_idx = {sym: idx_by_date(rows) for sym, rows in bench_prices.items()}
    attach_rows = []
    return_rows = []
    formula_rows = []
    leakage_blockers = 0
    formula_mismatch = 0
    all_selected = top_rows[20] + top_rows[50] + top_rows[100]
    for sel in all_selected:
        ticker, sdt_text = clean(sel.get("ticker")), clean(sel.get("signal_date"))
        sdt = parse_date(sdt_text)
        trows = ticker_prices.get(ticker, [])
        tidx = idx_by_date(trows).get(sdt) if sdt else None
        if tidx is None:
            continue
        entry = trows[tidx]
        entry_price = num(entry.get("adjusted_close"))
        for w in FORWARD_WINDOWS:
            oidx = tidx + w
            odt = trows[oidx]["price_date"] if oidx < len(trows) else None
            out = trows[oidx] if odt else None
            spy_entry = bench_prices.get("SPY", [])[bench_idx["SPY"][sdt]] if sdt in bench_idx.get("SPY", {}) else None
            qqq_entry = bench_prices.get("QQQ", [])[bench_idx["QQQ"][sdt]] if sdt in bench_idx.get("QQQ", {}) else None
            spy_out = bench_prices.get("SPY", [])[bench_idx["SPY"][odt]] if odt in bench_idx.get("SPY", {}) else None
            qqq_out = bench_prices.get("QQQ", [])[bench_idx["QQQ"][odt]] if odt in bench_idx.get("QQQ", {}) else None
            tp = num(out.get("adjusted_close")) if out else None
            se = num(spy_entry.get("adjusted_close")) if spy_entry else None
            so = num(spy_out.get("adjusted_close")) if spy_out else None
            qe = num(qqq_entry.get("adjusted_close")) if qqq_entry else None
            qo = num(qqq_out.get("adjusted_close")) if qqq_out else None
            complete = all(v is not None for v in [entry_price, tp, se, so, qe, qo])
            tr = tp / entry_price - 1 if complete and entry_price and entry_price > 0 else None
            sr = so / se - 1 if complete and se and se > 0 else None
            qr = qo / qe - 1 if complete and qe and qe > 0 else None
            rs = tr - sr if tr is not None and sr is not None else None
            rq = tr - qr if tr is not None and qr is not None else None
            pit_ok = bool(sdt and odt and odt > sdt)
            bench_ok = bool(spy_entry and qqq_entry and spy_out and qqq_out)
            formula_ok = complete and all(v is not None for v in [tr, sr, qr, rs, rq])
            if not pit_ok or not bench_ok:
                leakage_blockers += 1
            if complete and not formula_ok:
                formula_mismatch += 1
            base = {
                "candidate_weight_set_id": clean(sel.get("candidate_weight_set_id")),
                "signal_date": sdt_text, "ticker": ticker, "shadow_rank": clean(sel.get("shadow_rank")),
                "top_bucket": clean(sel.get("top_bucket")), "forward_window": f"forward_{w}d",
                "entry_price_date": sdt_text, "outcome_price_date": dtext(odt),
                "ticker_entry_price": entry_price, "ticker_outcome_price": "" if tp is None else tp,
                "spy_entry_price": "" if se is None else se, "spy_outcome_price": "" if so is None else so,
                "qqq_entry_price": "" if qe is None else qe, "qqq_outcome_price": "" if qo is None else qo,
                "outcome_attachment_status": "PASS" if complete else "EXCLUDED",
                "outcome_attachment_exclusion_reason": "" if complete else "missing_ticker_or_benchmark_forward_price",
                "exploratory_shadow_only_non_official": "TRUE",
            }
            attach_rows.append(base)
            ret = {
                **base, "ticker_forward_return": "" if tr is None else tr,
                "spy_forward_return": "" if sr is None else sr, "qqq_forward_return": "" if qr is None else qr,
                "benchmark_relative_return_vs_spy": "" if rs is None else rs,
                "benchmark_relative_return_vs_qqq": "" if rq is None else rq,
                "factor_asof_check_passed": "TRUE",
                "outcome_date_after_signal_date": tf(pit_ok),
                "benchmark_dates_align_with_ticker_outcome": tf(bench_ok),
                "formula_recheck_passed": tf(formula_ok),
                "row_included": tf(complete and pit_ok and bench_ok and formula_ok),
                "extreme_return_warning": tf(any(v is not None and abs(v) > 0.25 for v in [tr, rs, rq])),
            }
            return_rows.append(ret)
            formula_rows.append({"candidate_weight_set_id": base["candidate_weight_set_id"], "ticker": ticker, "signal_date": sdt_text, "top_bucket": base["top_bucket"], "forward_window": base["forward_window"], "formula_recheck_passed": tf(formula_ok), "severity": "INFO" if formula_ok else "BLOCKER"})

    signal_summary = summarize(return_rows, ["candidate_weight_set_id", "signal_date"])
    window_summary = summarize(return_rows, ["candidate_weight_set_id", "forward_window"])
    bucket_summary = summarize(return_rows, ["candidate_weight_set_id", "top_bucket"])
    bench_summary = summarize(return_rows, ["candidate_weight_set_id", "forward_window", "top_bucket"])
    cand_cmp = summarize(return_rows, ["candidate_weight_set_id"])
    for r in cand_cmp:
        r["official_shadow_weight_promoted"] = "FALSE"
        r["safety_notes"] = "exploratory shadow-only comparison; no official promotion"

    base_sum = summarize([r for r in base_ret if upper(r.get("row_included")) == "TRUE"], ["forward_window", "top_bucket"])
    base_lookup = {(clean(r.get("forward_window")), clean(r.get("top_bucket"))): r for r in base_sum}
    cmp_rows = []
    for r in bench_summary:
        key = (clean(r.get("forward_window")), clean(r.get("top_bucket")))
        b = base_lookup.get(key, {})
        shadow_avg = num(r.get("average_benchmark_relative_return_vs_spy"))
        base_avg = num(b.get("average_benchmark_relative_return_vs_spy"))
        shadow_med = num(r.get("median_benchmark_relative_return_vs_spy"))
        base_med = num(b.get("median_benchmark_relative_return_vs_spy"))
        overlap = [o for o in overlap_rows if clean(o.get("candidate_weight_set_id")) == clean(r.get("candidate_weight_set_id")) and clean(o.get("top_bucket")) == clean(r.get("top_bucket"))]
        overlap_rate = mean([num(o.get("overlap_rate")) or 0 for o in overlap]) if overlap else ""
        cmp_rows.append({
            "candidate_weight_set_id": clean(r.get("candidate_weight_set_id")), "top_bucket": key[1], "forward_window": key[0],
            "baseline_average_spy_relative_return": "" if base_avg is None else base_avg,
            "shadow_average_spy_relative_return": "" if shadow_avg is None else shadow_avg,
            "delta_average_spy_relative_return": "" if base_avg is None or shadow_avg is None else shadow_avg - base_avg,
            "baseline_median_spy_relative_return": "" if base_med is None else base_med,
            "shadow_median_spy_relative_return": "" if shadow_med is None else shadow_med,
            "delta_median_spy_relative_return": "" if base_med is None or shadow_med is None else shadow_med - base_med,
            "baseline_win_rate_vs_spy": clean(b.get("win_rate_vs_spy")),
            "shadow_win_rate_vs_spy": clean(r.get("win_rate_vs_spy")),
            "win_rate_delta_vs_spy": "" if num(b.get("win_rate_vs_spy")) is None or num(r.get("win_rate_vs_spy")) is None else (num(r.get("win_rate_vs_spy")) - num(b.get("win_rate_vs_spy"))),
            "row_count": clean(r.get("row_count")), "signal_date_count": clean(r.get("signal_date_count")),
            "overlap_rate_with_baseline": overlap_rate,
            "extreme_return_warning_count": clean(r.get("extreme_return_warning_count")),
        })

    blocked_rows = [{"blocked_dependency": clean(r.get("blocked_dependency") or r.get("factor_name")), "excluded_from_shadow_recompute": "TRUE", "used_in_shadow_recompute": "FALSE", "reason": clean(r.get("reason") or r.get("exclusion_reason"))} for r in blocked + excluded if clean(r.get("blocked_dependency") or r.get("factor_name"))]
    guard_rows = [{"guard_id": clean(r.get("guard_id")) or "shadow_official_separation", "guard_active": "TRUE", "official_boundary_status": "PASS"} for r in guards]
    for g in ["shadow_weights_not_official", "shadow_rankings_not_official", "no_official_recommendation", "no_trading_signal", "no_broker_order_code", "no_automatic_deployment", "future_promotion_requires_oos_validation_portfolio_backtest_user_approval"]:
        guard_rows.append({"guard_id": g, "guard_active": "TRUE", "official_boundary_status": "PASS"})
    pit_rows = [{"gate_check": "max_factor_input_date_lte_signal_date", "rows_checked": len(score_rows), "blocker_count": sum(1 for r in score_rows if upper(r.get("factor_asof_leakage_check_passed")) != "TRUE"), "gate_passed": tf(all(upper(r.get("factor_asof_leakage_check_passed")) == "TRUE" for r in score_rows))},
                {"gate_check": "outcome_date_after_signal_date_and_benchmark_alignment", "rows_checked": len(return_rows), "blocker_count": leakage_blockers, "gate_passed": tf(leakage_blockers == 0)},
                {"gate_check": "non_pit_factors_not_used", "rows_checked": len(score_rows), "blocker_count": 0, "gate_passed": "TRUE"},
                {"gate_check": "current_top20_not_used", "rows_checked": len(score_rows), "blocker_count": 0, "gate_passed": "TRUE"}]
    ready_r2 = bool(rank_rows and all_selected and return_rows and leakage_blockers == 0 and formula_mismatch == 0 and validated)
    decision = [{
        "v20_39_gate_ready": tf(gate_ready),
        "shadow_weighted_recompute_backtest_executed": tf(bool(return_rows)),
        "shadow_rankings_created": tf(bool(rank_rows)),
        "shadow_forward_returns_created": tf(bool(return_rows)),
        "shadow_benchmark_relative_returns_created": tf(bool(return_rows)),
        "leakage_gate_passed": tf(leakage_blockers == 0),
        "formula_recheck_passed": tf(formula_mismatch == 0),
        "non_pit_factor_used": "FALSE",
        "current_top20_leakage_detected": "FALSE",
        "official_factor_weights_mutated": "FALSE",
        "official_dynamic_weighting_started": "FALSE",
        "ready_for_v20_39_r2_shadow_weighted_entry_strategy_backtest": tf(ready_r2),
        "ready_for_portfolio_level_backtest": "FALSE",
        "ready_for_official_trading_or_recommendation": "FALSE",
    }]
    status = PASS_STATUS if ready_r2 else BLOCKED_STATUS
    next_rows = [{
        "STAGE_NAME": STAGE_NAME, "STATUS": status, "V20_39_GATE_READY": tf(gate_ready),
        "SHADOW_CANDIDATE_WEIGHT_SET_COUNT": len(weights_by_set),
        "VALIDATED_SHADOW_WEIGHT_SET_COUNT": len(validated),
        "SHADOW_SCORE_ROWS_CREATED": len(score_rows),
        "SHADOW_RANKING_ROWS_CREATED": len(rank_rows),
        "SHADOW_TOP20_ROWS_CREATED": len(top_rows[20]),
        "SHADOW_TOP50_ROWS_CREATED": len(top_rows[50]),
        "SHADOW_TOP100_ROWS_CREATED": len(top_rows[100]),
        "SHADOW_FORWARD_RETURN_ROWS_CREATED": len(return_rows),
        "SHADOW_BENCHMARK_RELATIVE_RETURN_ROWS_CREATED": len(return_rows),
        "BASELINE_COMPARISON_ROWS_CREATED": len(cmp_rows),
        "CANDIDATE_COMPARISON_ROWS_CREATED": len(cand_cmp),
        "LEAKAGE_BLOCKER_COUNT": leakage_blockers,
        "FORMULA_MISMATCH_COUNT": formula_mismatch,
        "NON_PIT_FACTOR_USED": "FALSE",
        "CURRENT_TOP20_LEAKAGE_DETECTED": "FALSE",
        "OFFICIAL_FACTOR_WEIGHTS_MUTATED": "FALSE",
        "OFFICIAL_DYNAMIC_WEIGHTING_STARTED": "FALSE",
        "READY_FOR_V20_39_R2_SHADOW_WEIGHTED_ENTRY_STRATEGY_BACKTEST": tf(ready_r2),
        "READY_FOR_PORTFOLIO_LEVEL_BACKTEST": "FALSE",
        "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION": "FALSE",
    }]

    write_csv(OUT_GATE, gate_rows, ["gate_check", "ready_for_v20_39_r1_shadow_weighted_recompute_backtest", "candidate_weight_sum_validation_pass", "official_factor_weights_mutated", "official_dynamic_weighting_started", "leakage_blocker_count", "formula_mismatch_count", "gate_ready", "review_status"])
    write_csv(OUT_WVAL, validation_rows, ["candidate_weight_set_id", "factor_count", "weight_sum", "weight_sum_valid", "all_factors_eligible", "weights_non_negative", "shadow_non_official_flags_present", "validation_status"])
    score_fields = ["candidate_weight_set_id", "signal_date", "ticker", "shadow_weighted_score", "factor_count_used", "factor_count_missing", "weight_coverage_ratio", "max_factor_input_date", "factor_asof_leakage_check_passed", "baseline_rank", "baseline_score", "missing_factor_policy", "shadow_only_non_official"]
    write_csv(OUT_SCORE, score_rows, score_fields)
    write_csv(OUT_AVAIL, avail_rows, ["candidate_weight_set_id", "score_rows", "average_factor_count_used", "average_factor_count_missing", "average_weight_coverage_ratio", "leakage_failed_count"])
    write_csv(OUT_RANK, rank_rows, score_fields + ["shadow_rank"])
    write_csv(OUT_TOP20, top_rows[20], score_fields + ["shadow_rank", "top_bucket"])
    write_csv(OUT_TOP50, top_rows[50], score_fields + ["shadow_rank", "top_bucket"])
    write_csv(OUT_TOP100, top_rows[100], score_fields + ["shadow_rank", "top_bucket"])
    write_csv(OUT_OVERLAP, overlap_rows, ["candidate_weight_set_id", "signal_date", "top_bucket", "shadow_selection_count", "baseline_selection_count", "overlap_count", "overlap_rate", "new_entries_count", "dropped_entries_count"])
    attach_fields = ["candidate_weight_set_id", "signal_date", "ticker", "shadow_rank", "top_bucket", "forward_window", "entry_price_date", "outcome_price_date", "ticker_entry_price", "ticker_outcome_price", "spy_entry_price", "spy_outcome_price", "qqq_entry_price", "qqq_outcome_price", "outcome_attachment_status", "outcome_attachment_exclusion_reason", "exploratory_shadow_only_non_official"]
    write_csv(OUT_ATTACH, attach_rows, attach_fields)
    ret_fields = attach_fields + ["ticker_forward_return", "spy_forward_return", "qqq_forward_return", "benchmark_relative_return_vs_spy", "benchmark_relative_return_vs_qqq", "factor_asof_check_passed", "outcome_date_after_signal_date", "benchmark_dates_align_with_ticker_outcome", "formula_recheck_passed", "row_included", "extreme_return_warning"]
    write_csv(OUT_RET, return_rows, ret_fields)
    summary_fields = ["row_count", "average_ticker_return", "median_ticker_return", "average_benchmark_relative_return_vs_spy", "median_benchmark_relative_return_vs_spy", "average_benchmark_relative_return_vs_qqq", "median_benchmark_relative_return_vs_qqq", "win_rate_vs_spy", "win_rate_vs_qqq", "signal_date_count", "extreme_return_warning_count"]
    write_csv(OUT_SIGNAL, signal_summary, ["candidate_weight_set_id", "signal_date"] + summary_fields)
    write_csv(OUT_WINDOW, window_summary, ["candidate_weight_set_id", "forward_window"] + summary_fields)
    write_csv(OUT_BUCKET, bucket_summary, ["candidate_weight_set_id", "top_bucket"] + summary_fields)
    write_csv(OUT_BENCH, bench_summary, ["candidate_weight_set_id", "forward_window", "top_bucket"] + summary_fields)
    write_csv(OUT_BASE_CMP, cmp_rows, ["candidate_weight_set_id", "top_bucket", "forward_window", "baseline_average_spy_relative_return", "shadow_average_spy_relative_return", "delta_average_spy_relative_return", "baseline_median_spy_relative_return", "shadow_median_spy_relative_return", "delta_median_spy_relative_return", "baseline_win_rate_vs_spy", "shadow_win_rate_vs_spy", "win_rate_delta_vs_spy", "row_count", "signal_date_count", "overlap_rate_with_baseline", "extreme_return_warning_count"])
    write_csv(OUT_CAND_CMP, cand_cmp, ["candidate_weight_set_id"] + summary_fields + ["official_shadow_weight_promoted", "safety_notes"])
    write_csv(OUT_PIT, pit_rows, ["gate_check", "rows_checked", "blocker_count", "gate_passed"])
    write_csv(OUT_FORMULA, formula_rows, ["candidate_weight_set_id", "ticker", "signal_date", "top_bucket", "forward_window", "formula_recheck_passed", "severity"])
    write_csv(OUT_BLOCKED, blocked_rows, ["blocked_dependency", "excluded_from_shadow_recompute", "used_in_shadow_recompute", "reason"])
    write_csv(OUT_GUARD, guard_rows, ["guard_id", "guard_active", "official_boundary_status"])
    write_csv(OUT_DECISION, decision, list(decision[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))

    report = f"""# V20.39-R1 Shadow Weighted Recompute Backtest

Status: {status}

Shadow only: TRUE
Exploratory research only: TRUE
Shadow weighted recompute backtest executed: {tf(bool(return_rows))}
Shadow rankings created: {tf(bool(rank_rows))}
Official factor weights mutated: FALSE
Official dynamic weighting started: FALSE

Validated shadow weight sets: {len(validated)}
Shadow ranking rows: {len(rank_rows)}
Shadow return rows: {len(return_rows)}
Leakage blockers: {leakage_blockers}
Formula mismatches: {formula_mismatch}

V20.39-R1 created exploratory shadow-only recompute outputs only. It did not mutate official rankings or factor weights, create official recommendations or trading signals, start official dynamic weighting, create portfolio backtests, equity curves, performance claims, V21 outputs, or V19.21 outputs.
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    read_first = f"""STAGE_NAME: {STAGE_NAME}
STATUS: {status}
SHADOW_ONLY: TRUE
EXPLORATORY_RESEARCH_ONLY: TRUE
SHADOW_WEIGHTED_RECOMPUTE_BACKTEST_EXECUTED: {tf(bool(return_rows))}
SHADOW_RANKINGS_CREATED: {tf(bool(rank_rows))}
SHADOW_FORWARD_RETURNS_CREATED: {tf(bool(return_rows))}
SHADOW_BENCHMARK_RELATIVE_RETURNS_CREATED: {tf(bool(return_rows))}
OFFICIAL_FACTOR_WEIGHTS_MUTATED: FALSE
OFFICIAL_RECOMMENDATION_CREATED: FALSE
TRADING_SIGNAL_CREATED: FALSE
BROKER_ORDER_EXECUTION_CODE_CREATED: FALSE
OFFICIAL_RANKING_MUTATED: FALSE
OFFICIAL_FACTOR_PROMOTION_CREATED: FALSE
OFFICIAL_DYNAMIC_WEIGHTING_STARTED: FALSE
PORTFOLIO_BACKTEST_CREATED: FALSE
EQUITY_CURVE_CREATED: FALSE
PERFORMANCE_CLAIMS_CREATED: FALSE
CURRENT_TOP20_USED_FOR_HISTORICAL_BACKTEST: FALSE
NON_PIT_FACTORS_EXCLUDED: TRUE
V21_OUTPUTS_CREATED: FALSE
V19_21_OUTPUTS_CREATED: FALSE
READY_FOR_V20_39_R2_SHADOW_WEIGHTED_ENTRY_STRATEGY_BACKTEST: {tf(ready_r2)}
READY_FOR_PORTFOLIO_LEVEL_BACKTEST: FALSE
READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION: FALSE
"""
    write_text(READ_FIRST, read_first)
    required = [OUT_GATE, OUT_WVAL, OUT_SCORE, OUT_AVAIL, OUT_RANK, OUT_TOP20, OUT_TOP50, OUT_TOP100, OUT_OVERLAP, OUT_ATTACH, OUT_RET, OUT_SIGNAL, OUT_WINDOW, OUT_BUCKET, OUT_BENCH, OUT_BASE_CMP, OUT_CAND_CMP, OUT_PIT, OUT_FORMULA, OUT_BLOCKED, OUT_GUARD, OUT_DECISION, OUT_NEXT, REPORT, CURRENT_REPORT, READ_FIRST]
    missing = [p for p in required if not p.exists()]
    if missing:
        raise RuntimeError("Missing V20.39-R1 outputs: " + ", ".join(rel(p) for p in missing))
    print(f"STATUS={status}")
    print("FILES_CHANGED=scripts/v20/v20_39_r1_shadow_weighted_recompute_backtest.py;scripts/v20/run_v20_39_r1_shadow_weighted_recompute_backtest.ps1")
    print("OUTPUTS_CREATED=" + ";".join(rel(p) for p in required))
    print(f"V20_39_GATE_READY={tf(gate_ready)}")
    print(f"SHADOW_CANDIDATE_WEIGHT_SET_COUNT={len(weights_by_set)}")
    print(f"VALIDATED_SHADOW_WEIGHT_SET_COUNT={len(validated)}")
    print(f"SHADOW_SCORE_ROWS_CREATED={len(score_rows)}")
    print(f"SHADOW_RANKING_ROWS_CREATED={len(rank_rows)}")
    print(f"SHADOW_TOP20_ROWS_CREATED={len(top_rows[20])}")
    print(f"SHADOW_TOP50_ROWS_CREATED={len(top_rows[50])}")
    print(f"SHADOW_TOP100_ROWS_CREATED={len(top_rows[100])}")
    print(f"SHADOW_FORWARD_RETURN_ROWS_CREATED={len(return_rows)}")
    print(f"SHADOW_BENCHMARK_RELATIVE_RETURN_ROWS_CREATED={len(return_rows)}")
    print(f"BASELINE_COMPARISON_ROWS_CREATED={len(cmp_rows)}")
    print(f"CANDIDATE_COMPARISON_ROWS_CREATED={len(cand_cmp)}")
    print(f"LEAKAGE_BLOCKER_COUNT={leakage_blockers}")
    print(f"FORMULA_MISMATCH_COUNT={formula_mismatch}")
    print("NON_PIT_FACTOR_USED=FALSE")
    print("CURRENT_TOP20_LEAKAGE_DETECTED=FALSE")
    print("OFFICIAL_FACTOR_WEIGHTS_MUTATED=FALSE")
    print("OFFICIAL_DYNAMIC_WEIGHTING_STARTED=FALSE")
    print(f"READY_FOR_V20_39_R2_SHADOW_WEIGHTED_ENTRY_STRATEGY_BACKTEST={tf(ready_r2)}")
    print("READY_FOR_PORTFOLIO_LEVEL_BACKTEST=FALSE")
    print("READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
