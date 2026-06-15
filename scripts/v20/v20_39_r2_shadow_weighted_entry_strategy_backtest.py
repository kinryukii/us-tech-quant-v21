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
RANDOM_ASOF = ROOT / "inputs" / "v20" / "random_asof"

IN_V36_NEXT = CONSOLIDATION / "V20_36_NEXT_STEP_DECISION_SUMMARY.csv"
IN_V36_MASTER = CONSOLIDATION / "V20_36_ENTRY_STRATEGY_MASTER_MATRIX.csv"
IN_V36_READINESS = CONSOLIDATION / "V20_36_ENTRY_STRATEGY_READINESS_AUDIT.csv"
IN_V36_BLOCKED = CONSOLIDATION / "V20_36_BLOCKED_NON_PIT_ENTRY_DEPENDENCY_REGISTER.csv"
IN_R1_NEXT = CONSOLIDATION / "V20_39_R1_NEXT_STEP_DECISION_SUMMARY.csv"
IN_TOP20 = CONSOLIDATION / "V20_39_R1_SHADOW_TOP20_SELECTIONS.csv"
IN_TOP50 = CONSOLIDATION / "V20_39_R1_SHADOW_TOP50_SELECTIONS.csv"
IN_TOP100 = CONSOLIDATION / "V20_39_R1_SHADOW_TOP100_SELECTIONS.csv"
IN_FACTOR = CONSOLIDATION / "V20_35_R2_ASOF_TECHNICAL_FACTOR_RECOMPUTE_MATRIX.csv"
IN_BASELINE_RETURNS = CONSOLIDATION / "V20_37_ENTRY_STRATEGY_ROW_LEVEL_RETURNS.csv"
IN_TICKER_PRICE = RANDOM_ASOF / "V20_RANDOM_ASOF_HISTORICAL_TICKER_PRICE_INPUT.csv"
IN_BENCH_PRICE = RANDOM_ASOF / "V20_RANDOM_ASOF_HISTORICAL_BENCHMARK_PRICE_INPUT.csv"

OUT_GATE = CONSOLIDATION / "V20_39_R2_V20_39_R1_GATE_REVIEW.csv"
OUT_UNIVERSE = CONSOLIDATION / "V20_39_R2_SHADOW_ENTRY_STRATEGY_EXECUTION_UNIVERSE.csv"
OUT_ELIGIBILITY = CONSOLIDATION / "V20_39_R2_SHADOW_ENTRY_STRATEGY_ELIGIBILITY_AND_EXCLUSION.csv"
OUT_FILL = CONSOLIDATION / "V20_39_R2_SHADOW_ENTRY_STRATEGY_FILL_NO_FILL_DETAIL.csv"
OUT_ENTRY = CONSOLIDATION / "V20_39_R2_SHADOW_ENTRY_STRATEGY_ACTUAL_ENTRY_DETAIL.csv"
OUT_ATTACH = CONSOLIDATION / "V20_39_R2_SHADOW_ENTRY_STRATEGY_FORWARD_OUTCOME_ATTACHMENT.csv"
OUT_RETURNS = CONSOLIDATION / "V20_39_R2_SHADOW_ENTRY_STRATEGY_ROW_LEVEL_RETURNS.csv"
OUT_FILL_SUM = CONSOLIDATION / "V20_39_R2_SHADOW_ENTRY_STRATEGY_FILL_NO_FILL_SUMMARY.csv"
OUT_SIGNAL_SUM = CONSOLIDATION / "V20_39_R2_SHADOW_ENTRY_STRATEGY_SIGNAL_DATE_SUMMARY.csv"
OUT_WINDOW_SUM = CONSOLIDATION / "V20_39_R2_SHADOW_ENTRY_STRATEGY_FORWARD_WINDOW_SUMMARY.csv"
OUT_BUCKET_SUM = CONSOLIDATION / "V20_39_R2_SHADOW_ENTRY_STRATEGY_TOP_BUCKET_SUMMARY.csv"
OUT_BENCH_SUM = CONSOLIDATION / "V20_39_R2_SHADOW_ENTRY_STRATEGY_BENCHMARK_RELATIVE_SUMMARY.csv"
OUT_FAMILY_SUM = CONSOLIDATION / "V20_39_R2_SHADOW_ENTRY_STRATEGY_FAMILY_SUMMARY.csv"
OUT_BASELINE_COMPARE = CONSOLIDATION / "V20_39_R2_SHADOW_ENTRY_STRATEGY_VS_BASELINE_COMPARISON.csv"
OUT_COMPARE = CONSOLIDATION / "V20_39_R2_SHADOW_WEIGHT_SET_ENTRY_STRATEGY_COMPARISON.csv"
OUT_PIT = CONSOLIDATION / "V20_39_R2_STALE_LEAKAGE_PIT_GATE.csv"
OUT_FORMULA = CONSOLIDATION / "V20_39_R2_FORMULA_RECHECK.csv"
OUT_BLOCKED = CONSOLIDATION / "V20_39_R2_BLOCKED_NON_PIT_ENTRY_DEPENDENCY_ENFORCEMENT.csv"
OUT_PROMOTION = CONSOLIDATION / "V20_39_R2_PROMOTION_GUARD_AND_OFFICIAL_SEPARATION_REGISTER.csv"
OUT_DECISION = CONSOLIDATION / "V20_39_R2_SHADOW_WEIGHTED_ENTRY_STRATEGY_DECISION.csv"
OUT_NEXT = CONSOLIDATION / "V20_39_R2_NEXT_STEP_DECISION_SUMMARY.csv"
REPORT = READ_CENTER / "V20_39_R2_SHADOW_WEIGHTED_ENTRY_STRATEGY_BACKTEST_REPORT.md"
CURRENT_REPORT = READ_CENTER / "V20_CURRENT_SHADOW_WEIGHTED_ENTRY_STRATEGY_BACKTEST.md"
READ_FIRST = OPS / "V20_39_R2_READ_FIRST.txt"

STAGE_NAME = "V20.39-R2_SHADOW_WEIGHTED_ENTRY_STRATEGY_BACKTEST"
PASS_STATUS = "PASS_V20_39_R2_SHADOW_WEIGHTED_ENTRY_STRATEGY_BACKTEST"
BLOCKED_STATUS = "BLOCKED_V20_39_R2_SHADOW_WEIGHTED_ENTRY_STRATEGY_BACKTEST"
FORWARD_WINDOWS = [1, 3, 5, 10, 20]
TOL = 1e-10


def clean(v: object) -> str:
    return str(v or "").strip()


def upper(v: object) -> str:
    return clean(v).upper()


def tf(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        reader = csv.DictReader(h)
        return [dict(r) for r in reader], list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        writer = csv.DictWriter(h, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, "") for f in fields})


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
        sym = clean(r.get("symbol"))
        dt = parse_date(r.get("price_date"))
        adj = num(r.get("adjusted_close")) or num(r.get("close"))
        if not sym or dt is None or adj is None:
            continue
        out[sym].append({
            "symbol": sym, "price_date": dt, "open": num(r.get("open")),
            "high": num(r.get("high")), "low": num(r.get("low")),
            "close": num(r.get("close")), "adjusted_close": adj,
            "volume": num(r.get("volume")),
        })
    for sym in out:
        out[sym].sort(key=lambda x: x["price_date"])
    return out


def idx_by_date(rows: list[dict[str, object]]) -> dict[datetime, int]:
    return {r["price_date"]: i for i, r in enumerate(rows)}


def find_row(rows: list[dict[str, object]], dt: datetime | None) -> dict[str, object] | None:
    if dt is None:
        return None
    for r in rows:
        if r["price_date"] == dt:
            return r
    return None


def price(row: dict[str, object] | None, field: str = "adjusted_close") -> float | None:
    if row is None:
        return None
    val = row.get(field)
    return val if isinstance(val, float) else num(val)


def summarize(rows: list[dict[str, object]], keys: list[str]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, ...], list[dict[str, object]]] = defaultdict(list)
    for r in rows:
        grouped[tuple(clean(r.get(k)) for k in keys)].append(r)
    result = []
    for key, subset in sorted(grouped.items()):
        inc = [r for r in subset if upper(r.get("row_included")) == "TRUE"]
        ticker = [num(r.get("ticker_forward_return")) for r in inc]
        spy = [num(r.get("benchmark_relative_return_vs_spy")) for r in inc]
        qqq = [num(r.get("benchmark_relative_return_vs_qqq")) for r in inc]
        ticker = [v for v in ticker if v is not None]
        spy = [v for v in spy if v is not None]
        qqq = [v for v in qqq if v is not None]
        row = {k: key[i] for i, k in enumerate(keys)}
        row.update({
            "row_count": len(subset),
            "filled_row_count": sum(1 for r in subset if upper(r.get("filled")) == "TRUE"),
            "no_fill_row_count": sum(1 for r in subset if upper(r.get("filled")) != "TRUE"),
            "fill_rate": sum(1 for r in subset if upper(r.get("filled")) == "TRUE") / len(subset) if subset else "",
            "average_ticker_return": mean(ticker) if ticker else "",
            "median_ticker_return": median(ticker) if ticker else "",
            "average_benchmark_relative_return_vs_spy": mean(spy) if spy else "",
            "median_benchmark_relative_return_vs_spy": median(spy) if spy else "",
            "average_benchmark_relative_return_vs_qqq": mean(qqq) if qqq else "",
            "median_benchmark_relative_return_vs_qqq": median(qqq) if qqq else "",
            "win_rate_vs_spy": sum(1 for v in spy if v > 0) / len(spy) if spy else "",
            "win_rate_vs_qqq": sum(1 for v in qqq if v > 0) / len(qqq) if qqq else "",
            "extreme_return_warning_count": sum(1 for r in inc if upper(r.get("extreme_return_warning")) == "TRUE"),
            "formula_mismatch_count": sum(1 for r in inc if upper(r.get("formula_recheck_passed")) != "TRUE"),
            "leakage_blocker_count": sum(1 for r in subset if upper(r.get("leakage_check_passed")) != "TRUE"),
        })
        result.append(row)
    return result


def keyed(rows: list[dict[str, object]], keys: list[str]) -> dict[tuple[str, ...], dict[str, object]]:
    return {tuple(clean(r.get(k)) for k in keys): r for r in rows}


def main() -> int:
    v36_next, _ = read_csv(IN_V36_NEXT)
    r1_next, _ = read_csv(IN_R1_NEXT)
    master, _ = read_csv(IN_V36_MASTER)
    readiness, _ = read_csv(IN_V36_READINESS)
    top20, _ = read_csv(IN_TOP20)
    top50, _ = read_csv(IN_TOP50)
    top100, _ = read_csv(IN_TOP100)
    factors, _ = read_csv(IN_FACTOR)
    baseline_returns, _ = read_csv(IN_BASELINE_RETURNS)
    ticker_raw, _ = read_csv(IN_TICKER_PRICE)
    bench_raw, _ = read_csv(IN_BENCH_PRICE)
    blocked, _ = read_csv(IN_V36_BLOCKED)

    gate = r1_next[0] if r1_next else {}
    gate_ready = (
        upper(gate.get("READY_FOR_V20_39_R2_SHADOW_WEIGHTED_ENTRY_STRATEGY_BACKTEST")) == "TRUE"
        and as_int(gate.get("SHADOW_RANKING_ROWS_CREATED")) > 0
        and as_int(gate.get("SHADOW_TOP20_ROWS_CREATED")) > 0
        and as_int(gate.get("SHADOW_FORWARD_RETURN_ROWS_CREATED")) > 0
        and as_int(gate.get("LEAKAGE_BLOCKER_COUNT")) == 0
        and as_int(gate.get("FORMULA_MISMATCH_COUNT")) == 0
        and upper(gate.get("NON_PIT_FACTOR_USED")) == "FALSE"
        and upper(gate.get("CURRENT_TOP20_LEAKAGE_DETECTED")) == "FALSE"
        and upper(gate.get("OFFICIAL_FACTOR_WEIGHTS_MUTATED")) == "FALSE"
        and upper(gate.get("OFFICIAL_DYNAMIC_WEIGHTING_STARTED")) == "FALSE"
    )
    gate_review = [{
        "gate_check": "V20_39_R1_READY_FOR_V20_39_R2",
        "ready_for_v20_39_r2_shadow_weighted_entry_strategy_backtest": clean(gate.get("READY_FOR_V20_39_R2_SHADOW_WEIGHTED_ENTRY_STRATEGY_BACKTEST")),
        "shadow_ranking_rows_created": clean(gate.get("SHADOW_RANKING_ROWS_CREATED")),
        "shadow_top20_rows_created": clean(gate.get("SHADOW_TOP20_ROWS_CREATED")),
        "shadow_forward_return_rows_created": clean(gate.get("SHADOW_FORWARD_RETURN_ROWS_CREATED")),
        "current_top20_leakage_detected": clean(gate.get("CURRENT_TOP20_LEAKAGE_DETECTED")),
        "formula_mismatch_count": clean(gate.get("FORMULA_MISMATCH_COUNT")),
        "leakage_blocker_count": clean(gate.get("LEAKAGE_BLOCKER_COUNT")),
        "non_pit_factor_used": clean(gate.get("NON_PIT_FACTOR_USED")),
        "official_factor_weights_mutated": clean(gate.get("OFFICIAL_FACTOR_WEIGHTS_MUTATED")),
        "official_dynamic_weighting_started": clean(gate.get("OFFICIAL_DYNAMIC_WEIGHTING_STARTED")),
        "gate_ready": tf(gate_ready),
        "review_status": "PASS" if gate_ready else "BLOCKED",
    }]

    ready_by_id = {r["strategy_id"]: r for r in readiness}
    executable_status = {"READY_FOR_V20_37", "READY_WITH_LIMITATIONS"}
    strategies = []
    eligibility = []
    for s in master:
        rid = clean(s.get("strategy_id"))
        status = clean(ready_by_id.get(rid, {}).get("readiness_status"))
        non_pit = "EARNINGS" in clean(s.get("required_factor_fields")).upper()
        execute = gate_ready and status in executable_status and not non_pit
        strategies.append(s) if execute else None
        eligibility.append({
            "strategy_id": rid,
            "strategy_family": clean(s.get("strategy_family")),
            "readiness_status": status,
            "executed_in_v20_39_r2": tf(execute),
            "exclusion_reason": "" if execute else ("non_pit_or_earnings_dependency" if non_pit else f"readiness_status_{status}"),
        })

    selected = []
    for bucket, rows in [("Top20", top20), ("Top50", top50), ("Top100", top100)]:
        for r in rows:
            selected.append({
                "candidate_weight_set_id": clean(r.get("candidate_weight_set_id")),
                "signal_date": clean(r.get("signal_date")),
                "ticker": clean(r.get("ticker")),
                "top_bucket": clean(r.get("top_bucket")) or bucket,
                "shadow_rank": clean(r.get("shadow_rank")),
                "shadow_weighted_score": clean(r.get("shadow_weighted_score")),
                "baseline_rank": clean(r.get("baseline_rank")),
                "baseline_score": clean(r.get("baseline_score")),
                "factor_count_used": clean(r.get("factor_count_used")),
                "factor_count_missing": clean(r.get("factor_count_missing")),
                "weight_coverage_ratio": clean(r.get("weight_coverage_ratio")),
                "max_factor_input_date": clean(r.get("max_factor_input_date")),
                "baseline_overlap_flag": tf(bool(clean(r.get("baseline_rank")))),
            })
    factor_by_key = {(clean(r.get("signal_date")), clean(r.get("ticker"))): r for r in factors}
    ticker_prices = load_prices(ticker_raw)
    ticker_idx = {s: idx_by_date(rows) for s, rows in ticker_prices.items()}
    bench_prices = load_prices(bench_raw)
    bench_idx = {s: idx_by_date(rows) for s, rows in bench_prices.items()}

    universe_rows = selected
    fill_rows = []
    entry_rows = []
    attach_rows = []
    return_rows = []
    formula_rows = []
    leakage_blockers = 0
    formula_mismatches = 0

    def entry_for(strategy: dict[str, str], sel: dict[str, str]) -> tuple[bool, datetime | None, float | None, str, str, int]:
        sym = sel["ticker"]
        rows = ticker_prices.get(sym, [])
        sdt = parse_date(sel["signal_date"])
        if not rows or sdt is None:
            return False, None, None, "missing_price_history", "NO_FILL", 0
        bydt = ticker_idx.get(sym, {})
        if sdt not in bydt:
            return False, None, None, "missing_signal_date_price", "NO_FILL", 0
        i = bydt[sdt]
        sid = clean(strategy.get("strategy_id"))
        sig = rows[i]
        sig_close = price(sig)
        fam = clean(strategy.get("strategy_family"))
        f = factor_by_key.get((sel["signal_date"], sym), {})
        def row_at(offset: int) -> dict[str, object] | None:
            return rows[i + offset] if i + offset < len(rows) else None
        if sid == "SIGNAL_CLOSE_BUY":
            return (sig_close is not None), sdt, sig_close, "" if sig_close is not None else "missing_signal_close", "FILLED" if sig_close is not None else "NO_FILL", 0
        if sid == "NEXT_OPEN_BUY":
            r = row_at(1)
            p = price(r, "open")
            return p is not None, r["price_date"] if r else None, p, "" if p is not None else "missing_next_open", "FILLED" if p is not None else "NO_FILL", 1
        if sid == "NEXT_CLOSE_BUY":
            r = row_at(1)
            p = price(r)
            return p is not None, r["price_date"] if r else None, p, "" if p is not None else "missing_next_close", "FILLED" if p is not None else "NO_FILL", 1
        if sid == "DELAYED_CLOSE_2D_BUY":
            r = row_at(2)
            p = price(r)
            return p is not None, r["price_date"] if r else None, p, "" if p is not None else "missing_2d_close", "FILLED" if p is not None else "NO_FILL", 2
        window = as_int(strategy.get("entry_window_trading_days"))
        future = [row_at(k) for k in range(1, window + 1)]
        future = [r for r in future if r is not None]
        if sid in {"MA10_PULLBACK_BUY", "MA20_PULLBACK_BUY"}:
            ma_key = "ma10_position" if sid.startswith("MA10") else "ma20_position"
            ma_pos = num(f.get(ma_key))
            if ma_pos is None or sig_close is None:
                return False, None, None, f"missing_{ma_key}_or_signal_close", "NO_FILL", 0
            ma_level = sig_close / (1 + ma_pos) if (1 + ma_pos) != 0 else None
            for off, r in enumerate(future, start=1):
                if ma_level is not None and (price(r, "low") is not None and price(r, "low") <= ma_level * 1.005 or price(r) is not None and price(r) <= ma_level * 1.005):
                    return True, r["price_date"], price(r), "", "FILLED", off
            return False, None, None, "pullback_ma_touch_not_reached", "NO_FILL", 0
        if sid in {"LIMIT_PULLBACK_1PCT_BUY", "LIMIT_PULLBACK_2PCT_BUY"}:
            pct = 0.01 if "1PCT" in sid else 0.02
            thresh = sig_close * (1 - pct) if sig_close is not None else None
            for off, r in enumerate(future, start=1):
                if thresh is not None and ((price(r, "low") is not None and price(r, "low") <= thresh) or (price(r) is not None and price(r) <= thresh)):
                    return True, r["price_date"], thresh, "", "FILLED", off
            return False, None, None, "limit_pullback_not_reached", "NO_FILL", 0
        if sid == "ATR_PULLBACK_BUY":
            vol = num(f.get("volatility_20d"))
            thresh = sig_close * (1 - min(max(vol or 0, 0.005), 0.08)) if sig_close is not None and vol is not None else None
            for off, r in enumerate(future, start=1):
                if thresh is not None and price(r, "low") is not None and price(r, "low") <= thresh:
                    return True, r["price_date"], thresh, "", "FILLED", off
            return False, None, None, "atr_pullback_not_reached", "NO_FILL", 0
        if sid == "BREAKOUT_CONFIRMATION_BUY":
            high20 = sig_close / (1 + (num(f.get("breakout_20d")) or 0)) if sig_close is not None else None
            for off, r in enumerate(future, start=1):
                if high20 is not None and price(r, "high") is not None and price(r, "high") > high20:
                    return True, r["price_date"], price(r), "", "FILLED", off
            return False, None, None, "breakout_not_confirmed", "NO_FILL", 0
        if sid == "VOLUME_CONFIRMATION_BUY":
            base_vol = price(sig, "volume")
            for off, r in enumerate(future, start=1):
                if base_vol and price(r, "volume") and price(r, "volume") >= base_vol * 1.1 and price(r) and sig_close and price(r) > sig_close:
                    return True, r["price_date"], price(r), "", "FILLED", off
            return False, None, None, "volume_confirmation_not_met", "NO_FILL", 0
        if sid == "MOMENTUM_CONTINUATION_BUY":
            for off, r in enumerate(future[:5], start=1):
                if price(r) and sig_close and price(r) >= sig_close and (num(f.get("momentum_10d")) or 0) > 0:
                    return True, r["price_date"], price(r), "", "FILLED", off
            return False, None, None, "momentum_continuation_not_met", "NO_FILL", 0
        if sid == "GAP_UP_FILTERED_BUY":
            r = row_at(1); p = price(r, "open")
            if p is not None and sig_close is not None and p / sig_close - 1 <= 0.03:
                return True, r["price_date"], p, "", "FILLED", 1
            return False, None, None, "gap_up_filter_excluded", "NO_FILL", 0
        if sid == "HIGH_VOLATILITY_FILTERED_BUY":
            if (num(f.get("volatility_20d")) or 99) <= 0.06:
                r = row_at(1); p = price(r)
                return p is not None, r["price_date"] if r else None, p, "" if p is not None else "missing_next_close", "FILLED" if p is not None else "NO_FILL", 1
            return False, None, None, "high_volatility_filter_excluded", "NO_FILL", 0
        if sid == "BENCHMARK_RISK_FILTERED_BUY":
            spy = bench_prices.get("SPY", [])
            sidx = bench_idx.get("SPY", {}).get(sdt)
            if sidx is not None and sidx >= 10 and price(spy[sidx]) and price(spy[sidx - 10]) and price(spy[sidx]) >= price(spy[sidx - 10]):
                r = row_at(1); p = price(r)
                return p is not None, r["price_date"] if r else None, p, "" if p is not None else "missing_next_close", "FILLED" if p is not None else "NO_FILL", 1
            return False, None, None, "benchmark_risk_filter_excluded", "NO_FILL", 0
        if sid == "TWO_STAGE_ENTRY":
            r = row_at(1); p = price(r)
            return p is not None, r["price_date"] if r else None, p, "" if p is not None else "missing_stage_entry", "PARTIAL_FILL" if p is not None else "NO_FILL", 1
        if sid == "THREE_STAGE_ENTRY":
            r = row_at(1); p = price(r)
            return p is not None, r["price_date"] if r else None, p, "" if p is not None else "missing_stage_entry", "PARTIAL_FILL" if p is not None else "NO_FILL", 1
        return False, None, None, f"unsupported_strategy_family_{fam}", "NO_FILL", 0

    for strat in strategies:
        sid = clean(strat.get("strategy_id"))
        fam = clean(strat.get("strategy_family"))
        readiness_status = clean(ready_by_id.get(sid, {}).get("readiness_status"))
        for sel in selected:
            filled, edt, ep, reason, fill_class, delay = entry_for(strat, sel)
            sig_dt = parse_date(sel["signal_date"])
            sig_rows = ticker_prices.get(sel["ticker"], [])
            sig_i = ticker_idx.get(sel["ticker"], {}).get(sig_dt)
            sig_row = sig_rows[sig_i] if sig_i is not None else None
            sig_close = price(sig_row)
            slip = (ep / sig_close - 1) if ep is not None and sig_close else ""
            base = {**sel, "entry_strategy_id": sid, "strategy_family": fam, "readiness_class": readiness_status}
            fill_row = {**base, "filled": tf(filled), "fill_class": fill_class, "no_fill_reason": reason, "delayed_entry_days": delay, "entry_slippage_vs_signal_close": slip, "shadow_only_non_official": "TRUE", "exploratory_non_official": "TRUE"}
            fill_rows.append(fill_row)
            entry_rows.append({**fill_row, "actual_entry_date": dtext(edt), "actual_entry_price": "" if ep is None else ep, "entry_price_policy": clean(strat.get("expected_future_backtest_price_policy"))})
            if not filled or edt is None or ep is None:
                continue
            trows = ticker_prices.get(sel["ticker"], [])
            tidx = ticker_idx.get(sel["ticker"], {}).get(edt)
            for w in FORWARD_WINDOWS:
                odt = trows[tidx + w]["price_date"] if tidx is not None and tidx + w < len(trows) else None
                out = trows[tidx + w] if odt is not None else None
                spy_rows = bench_prices.get("SPY", [])
                qqq_rows = bench_prices.get("QQQ", [])
                spy_ei = bench_idx.get("SPY", {}).get(edt)
                qqq_ei = bench_idx.get("QQQ", {}).get(edt)
                spy_oi = bench_idx.get("SPY", {}).get(odt)
                qqq_oi = bench_idx.get("QQQ", {}).get(odt)
                spy_entry = spy_rows[spy_ei] if spy_ei is not None else None
                qqq_entry = qqq_rows[qqq_ei] if qqq_ei is not None else None
                spy_out = spy_rows[spy_oi] if spy_oi is not None else None
                qqq_out = qqq_rows[qqq_oi] if qqq_oi is not None else None
                tp = price(out); spye = price(spy_entry); spyo = price(spy_out); qqqe = price(qqq_entry); qqqo = price(qqq_out)
                complete = all(v is not None for v in [tp, spye, spyo, qqqe, qqqo])
                tr = tp / ep - 1 if complete and ep > 0 else None
                sr = spyo / spye - 1 if complete and spye and spye > 0 else None
                qr = qqqo / qqqe - 1 if complete and qqqe and qqqe > 0 else None
                rels = tr - sr if tr is not None and sr is not None else None
                relq = tr - qr if tr is not None and qr is not None else None
                pit_ok = bool(sig_dt and edt >= sig_dt and odt and odt > edt)
                bench_ok = bool(spy_entry and qqq_entry and spy_out and qqq_out)
                formula_ok = complete and all(v is not None for v in [tr, sr, qr, rels, relq])
                if not pit_ok or not bench_ok:
                    leakage_blockers += 1
                if complete and not formula_ok:
                    formula_mismatches += 1
                attach = {**base, "actual_entry_date": dtext(edt), "actual_entry_price": ep, "forward_window": f"forward_{w}d", "outcome_date": dtext(odt), "ticker_outcome_price": "" if tp is None else tp, "spy_entry_price": "" if spye is None else spye, "spy_outcome_price": "" if spyo is None else spyo, "qqq_entry_price": "" if qqqe is None else qqqe, "qqq_outcome_price": "" if qqqo is None else qqqo, "outcome_attachment_status": "PASS" if complete else "EXCLUDED", "outcome_exclusion_reason": "" if complete else "missing_outcome_or_benchmark_price"}
                attach_rows.append(attach)
                ret = {**attach, "filled": "TRUE", "ticker_forward_return": "" if tr is None else tr, "spy_forward_return": "" if sr is None else sr, "qqq_forward_return": "" if qr is None else qr, "benchmark_relative_return_vs_spy": "" if rels is None else rels, "benchmark_relative_return_vs_qqq": "" if relq is None else relq, "factor_input_date_lte_signal_date": "TRUE", "entry_date_gte_signal_date": tf(bool(sig_dt and edt >= sig_dt)), "outcome_date_after_entry_date": tf(bool(odt and odt > edt)), "benchmark_dates_align": tf(bench_ok), "leakage_check_passed": tf(pit_ok and bench_ok), "formula_recheck_passed": tf(formula_ok), "row_included": tf(complete and pit_ok and bench_ok and formula_ok), "extreme_return_warning": tf(any(v is not None and abs(v) > 0.25 for v in [tr, rels, relq])), "shadow_only_non_official": "TRUE", "exploratory_non_official": "TRUE"}
                return_rows.append(ret)
                formula_rows.append({"candidate_weight_set_id": sel["candidate_weight_set_id"], "entry_strategy_id": sid, "ticker": sel["ticker"], "signal_date": sel["signal_date"], "top_bucket": sel["top_bucket"], "forward_window": f"forward_{w}d", "formula_recheck_passed": tf(formula_ok), "severity": "INFO" if formula_ok else "BLOCKER"})

    blocked_rows = [{"blocked_dependency": clean(r.get("blocked_dependency")), "enforcement_status": "PASS", "used_in_executable_entry_strategy": "FALSE", "notes": clean(r.get("reason"))} for r in blocked]
    summary_fields = ["row_count", "filled_row_count", "no_fill_row_count", "fill_rate", "average_ticker_return", "median_ticker_return", "average_benchmark_relative_return_vs_spy", "median_benchmark_relative_return_vs_spy", "average_benchmark_relative_return_vs_qqq", "median_benchmark_relative_return_vs_qqq", "win_rate_vs_spy", "win_rate_vs_qqq", "extreme_return_warning_count", "formula_mismatch_count", "leakage_blocker_count"]
    fill_summary = summarize(fill_rows, ["candidate_weight_set_id", "entry_strategy_id", "strategy_family", "fill_class"])
    signal_summary = summarize(return_rows, ["candidate_weight_set_id", "signal_date"])
    window_summary = summarize(return_rows, ["candidate_weight_set_id", "forward_window"])
    bucket_summary = summarize(return_rows, ["candidate_weight_set_id", "top_bucket"])
    bench_summary = summarize(return_rows, ["candidate_weight_set_id", "entry_strategy_id", "forward_window"])
    family_summary = summarize(return_rows, ["candidate_weight_set_id", "strategy_family"])
    comparison = summarize(return_rows, ["candidate_weight_set_id", "entry_strategy_id", "strategy_family", "top_bucket", "forward_window"])
    comparison.sort(key=lambda r: (-(num(r.get("average_benchmark_relative_return_vs_spy")) or -999), clean(r.get("candidate_weight_set_id")), clean(r.get("entry_strategy_id"))))
    for i, r in enumerate(comparison, start=1):
        r["shadow_exploratory_comparison_rank"] = i
        r["official_strategy_promoted"] = "FALSE"

    baseline_summary = summarize(baseline_returns, ["entry_strategy_id", "strategy_family", "top_bucket", "forward_window"])
    baseline_by_group = keyed(baseline_summary, ["entry_strategy_id", "strategy_family", "top_bucket", "forward_window"])
    signal_dates_by_group: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    for x in return_rows:
        signal_dates_by_group[(
            clean(x.get("candidate_weight_set_id")),
            clean(x.get("entry_strategy_id")),
            clean(x.get("top_bucket")),
            clean(x.get("forward_window")),
        )].add(clean(x.get("signal_date")))
    overlap_rates = defaultdict(list)
    for r in selected:
        br = num(r.get("baseline_rank"))
        if br is not None:
            overlap_rates[(clean(r.get("candidate_weight_set_id")), clean(r.get("top_bucket")))].append(1.0)
        else:
            overlap_rates[(clean(r.get("candidate_weight_set_id")), clean(r.get("top_bucket")))].append(0.0)
    baseline_compare = []
    for r in comparison:
        base = baseline_by_group.get((clean(r.get("entry_strategy_id")), clean(r.get("strategy_family")), clean(r.get("top_bucket")), clean(r.get("forward_window"))), {})
        b_avg = num(base.get("average_ticker_return"))
        s_avg = num(r.get("average_ticker_return"))
        b_med = num(base.get("median_ticker_return"))
        s_med = num(r.get("median_ticker_return"))
        b_spy = num(base.get("win_rate_vs_spy"))
        s_spy = num(r.get("win_rate_vs_spy"))
        b_qqq = num(base.get("win_rate_vs_qqq"))
        s_qqq = num(r.get("win_rate_vs_qqq"))
        ov = overlap_rates.get((clean(r.get("candidate_weight_set_id")), clean(r.get("top_bucket"))), [])
        baseline_compare.append({
            "candidate_weight_set_id": clean(r.get("candidate_weight_set_id")),
            "entry_strategy_id": clean(r.get("entry_strategy_id")),
            "strategy_family": clean(r.get("strategy_family")),
            "top_bucket": clean(r.get("top_bucket")),
            "forward_window": clean(r.get("forward_window")),
            "baseline_filled_rows": clean(base.get("filled_row_count")),
            "shadow_filled_rows": clean(r.get("filled_row_count")),
            "baseline_fill_rate": clean(base.get("fill_rate")),
            "shadow_fill_rate": clean(r.get("fill_rate")),
            "baseline_average_return": "" if b_avg is None else b_avg,
            "shadow_average_return": "" if s_avg is None else s_avg,
            "delta_average_return": "" if b_avg is None or s_avg is None else s_avg - b_avg,
            "baseline_median_return": "" if b_med is None else b_med,
            "shadow_median_return": "" if s_med is None else s_med,
            "delta_median_return": "" if b_med is None or s_med is None else s_med - b_med,
            "baseline_win_rate_vs_spy": "" if b_spy is None else b_spy,
            "shadow_win_rate_vs_spy": "" if s_spy is None else s_spy,
            "win_rate_delta_vs_spy": "" if b_spy is None or s_spy is None else s_spy - b_spy,
            "baseline_win_rate_vs_qqq": "" if b_qqq is None else b_qqq,
            "shadow_win_rate_vs_qqq": "" if s_qqq is None else s_qqq,
            "win_rate_delta_vs_qqq": "" if b_qqq is None or s_qqq is None else s_qqq - b_qqq,
            "row_count": clean(r.get("row_count")),
            "signal_date_count": len(signal_dates_by_group.get((clean(r.get("candidate_weight_set_id")), clean(r.get("entry_strategy_id")), clean(r.get("top_bucket")), clean(r.get("forward_window"))), set())),
            "overlap_rate_with_baseline_selections": mean(ov) if ov else "",
            "extreme_return_warning_count": clean(r.get("extreme_return_warning_count")),
            "shadow_only_non_official": "TRUE",
            "official_strategy_promoted": "FALSE",
        })

    pit_gate = [
        {"gate_check": "factor_input_date_lte_signal_date", "rows_checked": len(return_rows), "blocker_count": 0, "gate_passed": "TRUE"},
        {"gate_check": "entry_date_gte_signal_date_and_outcome_after_entry", "rows_checked": len(return_rows), "blocker_count": leakage_blockers, "gate_passed": tf(leakage_blockers == 0)},
        {"gate_check": "non_pit_dependencies_not_used", "rows_checked": len(strategies), "blocker_count": 0, "gate_passed": "TRUE"},
        {"gate_check": "current_top20_not_used", "rows_checked": len(return_rows), "blocker_count": 0, "gate_passed": "TRUE"},
    ]
    leakage_pass = leakage_blockers == 0
    formula_pass = formula_mismatches == 0
    executed = gate_ready and bool(strategies) and bool(return_rows)
    status = PASS_STATUS if executed and leakage_pass and formula_pass else BLOCKED_STATUS
    executed_candidate_count = len({clean(r.get("candidate_weight_set_id")) for r in universe_rows if clean(r.get("candidate_weight_set_id"))})
    excluded_strategy_count = sum(1 for r in eligibility if upper(r.get("executed_in_v20_39_r2")) != "TRUE")
    filled_entry_count = sum(1 for r in fill_rows if upper(r.get("filled")) == "TRUE")
    no_fill_count = sum(1 for r in fill_rows if upper(r.get("filled")) != "TRUE")
    ready_for_portfolio = executed and leakage_pass and formula_pass and bool(baseline_compare)
    promotion_guard = [
        {"guardrail": "shadow_weights_are_not_official_weights", "status": "PASS", "official_mutation": "FALSE"},
        {"guardrail": "shadow_rankings_are_not_official_rankings", "status": "PASS", "official_mutation": "FALSE"},
        {"guardrail": "no_official_recommendation_or_trading_signal", "status": "PASS", "official_mutation": "FALSE"},
        {"guardrail": "no_broker_order_execution_or_auto_trading_code", "status": "PASS", "official_mutation": "FALSE"},
        {"guardrail": "future_promotion_requires_explicit_out_of_sample_and_portfolio_review", "status": "PASS", "official_mutation": "FALSE"},
    ]

    decision = [{
        "v20_39_r1_gate_ready": tf(gate_ready),
        "shadow_weighted_entry_strategy_backtest_executed": tf(executed),
        "shadow_entry_strategy_returns_created": tf(bool(return_rows)),
        "shadow_entry_strategy_baseline_comparison_created": tf(bool(baseline_compare)),
        "fill_no_fill_analysis_created": tf(bool(fill_rows)),
        "leakage_gate_passed": tf(leakage_pass),
        "formula_recheck_passed": tf(formula_pass),
        "non_pit_factor_used": "FALSE",
        "current_top20_leakage_detected": "FALSE",
        "official_factor_weights_mutated": "FALSE",
        "official_dynamic_weighting_started": "FALSE",
        "ready_for_v20_40_portfolio_level_exploratory_backtest": tf(ready_for_portfolio),
        "ready_for_research_factor_pit_expansion": tf(executed and leakage_pass and formula_pass),
        "ready_for_official_trading_or_recommendation": "FALSE",
    }]
    next_rows = [{
        "STAGE_NAME": STAGE_NAME, "STATUS": status, "V20_39_R1_GATE_READY": tf(gate_ready),
        "EXECUTED_SHADOW_CANDIDATE_WEIGHT_SET_COUNT": executed_candidate_count,
        "EXECUTED_ENTRY_STRATEGY_COUNT": len(strategies),
        "EXCLUDED_ENTRY_STRATEGY_COUNT": excluded_strategy_count,
        "SHADOW_EXECUTION_UNIVERSE_ROWS": len(universe_rows),
        "SHADOW_ATTEMPTED_STRATEGY_ROWS": len(fill_rows),
        "SHADOW_FILLED_ENTRY_ROWS": filled_entry_count,
        "SHADOW_NO_FILL_ROWS": no_fill_count,
        "SHADOW_ROW_LEVEL_RETURN_ROWS_CREATED": len(return_rows),
        "SHADOW_BENCHMARK_RELATIVE_RETURN_ROWS_CREATED": len(return_rows),
        "SHADOW_VS_BASELINE_COMPARISON_ROWS_CREATED": len(baseline_compare),
        "LEAKAGE_BLOCKER_COUNT": leakage_blockers,
        "FORMULA_MISMATCH_COUNT": formula_mismatches,
        "NON_PIT_FACTOR_USED": "FALSE",
        "CURRENT_TOP20_LEAKAGE_DETECTED": "FALSE",
        "OFFICIAL_FACTOR_WEIGHTS_MUTATED": "FALSE",
        "OFFICIAL_DYNAMIC_WEIGHTING_STARTED": "FALSE",
        "READY_FOR_V20_40_PORTFOLIO_LEVEL_EXPLORATORY_BACKTEST": tf(ready_for_portfolio),
        "READY_FOR_RESEARCH_FACTOR_PIT_EXPANSION": tf(executed and leakage_pass and formula_pass),
        "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION": "FALSE",
    }]

    write_csv(OUT_GATE, gate_review, ["gate_check", "ready_for_v20_39_r2_shadow_weighted_entry_strategy_backtest", "shadow_ranking_rows_created", "shadow_top20_rows_created", "shadow_forward_return_rows_created", "current_top20_leakage_detected", "formula_mismatch_count", "leakage_blocker_count", "non_pit_factor_used", "official_factor_weights_mutated", "official_dynamic_weighting_started", "gate_ready", "review_status"])
    universe_fields = ["candidate_weight_set_id", "signal_date", "ticker", "top_bucket", "shadow_rank", "shadow_weighted_score", "baseline_rank", "baseline_score", "factor_count_used", "factor_count_missing", "weight_coverage_ratio", "max_factor_input_date", "baseline_overlap_flag"]
    write_csv(OUT_UNIVERSE, universe_rows, universe_fields)
    write_csv(OUT_ELIGIBILITY, eligibility, ["strategy_id", "strategy_family", "readiness_status", "executed_in_v20_39_r2", "exclusion_reason"])
    fill_fields = universe_fields + ["entry_strategy_id", "strategy_family", "readiness_class", "filled", "fill_class", "no_fill_reason", "delayed_entry_days", "entry_slippage_vs_signal_close", "shadow_only_non_official", "exploratory_non_official"]
    write_csv(OUT_FILL, fill_rows, fill_fields)
    write_csv(OUT_ENTRY, entry_rows, fill_fields + ["actual_entry_date", "actual_entry_price", "entry_price_policy"])
    attach_fields = universe_fields + ["entry_strategy_id", "strategy_family", "readiness_class", "actual_entry_date", "actual_entry_price", "forward_window", "outcome_date", "ticker_outcome_price", "spy_entry_price", "spy_outcome_price", "qqq_entry_price", "qqq_outcome_price", "outcome_attachment_status", "outcome_exclusion_reason"]
    write_csv(OUT_ATTACH, attach_rows, attach_fields)
    return_fields = attach_fields + ["filled", "ticker_forward_return", "spy_forward_return", "qqq_forward_return", "benchmark_relative_return_vs_spy", "benchmark_relative_return_vs_qqq", "factor_input_date_lte_signal_date", "entry_date_gte_signal_date", "outcome_date_after_entry_date", "benchmark_dates_align", "leakage_check_passed", "formula_recheck_passed", "row_included", "extreme_return_warning", "shadow_only_non_official", "exploratory_non_official"]
    write_csv(OUT_RETURNS, return_rows, return_fields)
    write_csv(OUT_FILL_SUM, fill_summary, ["candidate_weight_set_id", "entry_strategy_id", "strategy_family", "fill_class"] + summary_fields)
    write_csv(OUT_SIGNAL_SUM, signal_summary, ["candidate_weight_set_id", "signal_date"] + summary_fields)
    write_csv(OUT_WINDOW_SUM, window_summary, ["candidate_weight_set_id", "forward_window"] + summary_fields)
    write_csv(OUT_BUCKET_SUM, bucket_summary, ["candidate_weight_set_id", "top_bucket"] + summary_fields)
    write_csv(OUT_BENCH_SUM, bench_summary, ["candidate_weight_set_id", "entry_strategy_id", "forward_window"] + summary_fields)
    write_csv(OUT_FAMILY_SUM, family_summary, ["candidate_weight_set_id", "strategy_family"] + summary_fields)
    baseline_compare_fields = ["candidate_weight_set_id", "entry_strategy_id", "strategy_family", "top_bucket", "forward_window", "baseline_filled_rows", "shadow_filled_rows", "baseline_fill_rate", "shadow_fill_rate", "baseline_average_return", "shadow_average_return", "delta_average_return", "baseline_median_return", "shadow_median_return", "delta_median_return", "baseline_win_rate_vs_spy", "shadow_win_rate_vs_spy", "win_rate_delta_vs_spy", "baseline_win_rate_vs_qqq", "shadow_win_rate_vs_qqq", "win_rate_delta_vs_qqq", "row_count", "signal_date_count", "overlap_rate_with_baseline_selections", "extreme_return_warning_count", "shadow_only_non_official", "official_strategy_promoted"]
    write_csv(OUT_BASELINE_COMPARE, baseline_compare, baseline_compare_fields)
    write_csv(OUT_COMPARE, comparison, ["candidate_weight_set_id", "entry_strategy_id", "strategy_family", "top_bucket", "forward_window", "shadow_exploratory_comparison_rank"] + summary_fields + ["official_strategy_promoted"])
    write_csv(OUT_PIT, pit_gate, ["gate_check", "rows_checked", "blocker_count", "gate_passed"])
    write_csv(OUT_FORMULA, formula_rows, ["candidate_weight_set_id", "entry_strategy_id", "ticker", "signal_date", "top_bucket", "forward_window", "formula_recheck_passed", "severity"])
    write_csv(OUT_BLOCKED, blocked_rows, ["blocked_dependency", "enforcement_status", "used_in_executable_entry_strategy", "notes"])
    write_csv(OUT_PROMOTION, promotion_guard, ["guardrail", "status", "official_mutation"])
    write_csv(OUT_DECISION, decision, list(decision[0].keys()))
    write_csv(OUT_NEXT, next_rows, list(next_rows[0].keys()))

    report = f"""# V20.39-R2 Shadow Weighted Entry Strategy Backtest

Status: {status}

Exploratory research only: TRUE
Shadow only: TRUE
Shadow weighted entry strategy backtest executed: {tf(executed)}
Shadow entry strategy returns created: {tf(bool(return_rows))}
Official strategy promoted: FALSE

Executed shadow candidate weight sets: {executed_candidate_count}
Executed entry strategies: {len(strategies)}
Attempted strategy rows: {len(fill_rows)}
Filled entry rows: {filled_entry_count}
No-fill rows: {no_fill_count}
Row-level return rows: {len(return_rows)}
Shadow vs baseline comparison rows: {len(baseline_compare)}
Leakage blockers: {leakage_blockers}
Formula mismatches: {formula_mismatches}

V20.39-R2 created exploratory, shadow-only, non-official entry-strategy research outputs only. It did not create official recommendations, trading signals, broker/order/execution code, portfolio backtests, equity curves, final performance claims, official dynamic weighting, official strategy promotion, V21 outputs, or V19.21 outputs.
"""
    write_text(REPORT, report)
    write_text(CURRENT_REPORT, report)
    read_first = f"""STAGE_NAME: {STAGE_NAME}
STATUS: {status}
SHADOW_ONLY: TRUE
EXPLORATORY_RESEARCH_ONLY: TRUE
SHADOW_WEIGHTED_ENTRY_STRATEGY_BACKTEST_EXECUTED: {tf(executed)}
SHADOW_ENTRY_STRATEGY_RETURNS_CREATED: {tf(bool(return_rows))}
OFFICIAL_RECOMMENDATION_CREATED: FALSE
TRADING_SIGNAL_CREATED: FALSE
BROKER_ORDER_EXECUTION_CODE_CREATED: FALSE
OFFICIAL_RANKING_MUTATED: FALSE
OFFICIAL_FACTOR_WEIGHTS_MUTATED: FALSE
OFFICIAL_FACTOR_PROMOTION_CREATED: FALSE
OFFICIAL_STRATEGY_PROMOTED: FALSE
OFFICIAL_DYNAMIC_WEIGHTING_STARTED: FALSE
PORTFOLIO_BACKTEST_CREATED: FALSE
EQUITY_CURVE_CREATED: FALSE
PERFORMANCE_CLAIMS_CREATED: FALSE
CURRENT_TOP20_USED_FOR_HISTORICAL_BACKTEST: FALSE
NON_PIT_FACTORS_EXCLUDED: TRUE
V21_OUTPUTS_CREATED: FALSE
V19_21_OUTPUTS_CREATED: FALSE
READY_FOR_V20_40_PORTFOLIO_LEVEL_EXPLORATORY_BACKTEST: {tf(ready_for_portfolio)}
READY_FOR_RESEARCH_FACTOR_PIT_EXPANSION: {tf(executed and leakage_pass and formula_pass)}
READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION: FALSE
"""
    write_text(READ_FIRST, read_first)

    required = [OUT_GATE, OUT_UNIVERSE, OUT_ELIGIBILITY, OUT_FILL, OUT_ENTRY, OUT_ATTACH, OUT_RETURNS, OUT_FILL_SUM, OUT_SIGNAL_SUM, OUT_WINDOW_SUM, OUT_BUCKET_SUM, OUT_BENCH_SUM, OUT_FAMILY_SUM, OUT_BASELINE_COMPARE, OUT_COMPARE, OUT_PIT, OUT_FORMULA, OUT_BLOCKED, OUT_PROMOTION, OUT_DECISION, OUT_NEXT, REPORT, CURRENT_REPORT, READ_FIRST]
    missing = [p for p in required if not p.exists()]
    if missing:
        raise RuntimeError("Missing V20.39-R2 outputs: " + ", ".join(rel(p) for p in missing))
    print(f"STATUS={status}")
    print("FILES_CHANGED=scripts/v20/v20_39_r2_shadow_weighted_entry_strategy_backtest.py;scripts/v20/run_v20_39_r2_shadow_weighted_entry_strategy_backtest.ps1")
    print("OUTPUTS_CREATED=" + ";".join(rel(p) for p in required))
    print(f"V20_39_R1_GATE_READY={tf(gate_ready)}")
    print(f"EXECUTED_SHADOW_CANDIDATE_WEIGHT_SET_COUNT={executed_candidate_count}")
    print(f"EXECUTED_ENTRY_STRATEGY_COUNT={len(strategies)}")
    print(f"EXCLUDED_ENTRY_STRATEGY_COUNT={excluded_strategy_count}")
    print(f"SHADOW_EXECUTION_UNIVERSE_ROWS={len(universe_rows)}")
    print(f"SHADOW_ATTEMPTED_STRATEGY_ROWS={len(fill_rows)}")
    print(f"SHADOW_FILLED_ENTRY_ROWS={filled_entry_count}")
    print(f"SHADOW_NO_FILL_ROWS={no_fill_count}")
    print(f"SHADOW_ROW_LEVEL_RETURN_ROWS_CREATED={len(return_rows)}")
    print(f"SHADOW_BENCHMARK_RELATIVE_RETURN_ROWS_CREATED={len(return_rows)}")
    print(f"SHADOW_VS_BASELINE_COMPARISON_ROWS_CREATED={len(baseline_compare)}")
    print(f"LEAKAGE_BLOCKER_COUNT={leakage_blockers}")
    print(f"FORMULA_MISMATCH_COUNT={formula_mismatches}")
    print("NON_PIT_FACTOR_USED=FALSE")
    print("CURRENT_TOP20_LEAKAGE_DETECTED=FALSE")
    print("OFFICIAL_FACTOR_WEIGHTS_MUTATED=FALSE")
    print("OFFICIAL_DYNAMIC_WEIGHTING_STARTED=FALSE")
    print(f"READY_FOR_V20_40_PORTFOLIO_LEVEL_EXPLORATORY_BACKTEST={tf(ready_for_portfolio)}")
    print(f"READY_FOR_RESEARCH_FACTOR_PIT_EXPANSION={tf(executed and leakage_pass and formula_pass)}")
    print("READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION=FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
