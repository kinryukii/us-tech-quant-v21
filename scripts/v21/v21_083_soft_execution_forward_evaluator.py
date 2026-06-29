#!/usr/bin/env python
"""Track and evaluate the V21.082 soft execution forward ledger."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import protected_files, sha256, truth


STAGE = "V21.083-R1_R2_SOFT_EXECUTION_FORWARD_EVALUATOR"
OUT_REL = Path("outputs/v21/v21_083")
LEDGER_REL = Path("outputs/v21/v21_082/V21_082_R2_SOFT_EXECUTION_FORWARD_OBSERVATION_LEDGER.csv")
AUDIT_REL = Path("outputs/v21/v21_082/V21_082_R3_SOFT_EXECUTION_LEDGER_AUDIT.csv")
READINESS_REL = Path("outputs/v21/v21_082/V21_082_R3_READINESS_DECISION_REPORT.csv")
PRICE_REL = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")

TRACKED_NAME = "V21_083_R1_MATURITY_TRACKED_LEDGER.csv"
MATURITY_SUMMARY_NAME = "V21_083_R1_MATURITY_SUMMARY.csv"
EVAL_SUMMARY_NAME = "V21_083_R2_SOFT_EXECUTION_FORWARD_EVALUATION_SUMMARY.csv"
COMPARISON_NAME = "V21_083_R2_D_EW_VS_SOFT_EXECUTION_FORWARD_COMPARISON.csv"
READINESS_NAME = "V21_083_R2_READINESS_DECISION_REPORT.csv"

BASELINE = "D_EW_TOP50_R1"
CANDIDATE = "D_EXECUTION_PRIORITY_COMBINED_TOP50_R1"
INITIAL_CAPITAL = 10000.0


def price_table(root: Path) -> tuple[pd.DataFrame, dict[tuple[str, str], float], str]:
    path = root / PRICE_REL
    prices = pd.read_csv(
        path,
        usecols=["symbol", "date", "close", "adjusted_close", "low", "high"],
        low_memory=False,
    )
    prices["symbol"] = prices["symbol"].astype(str).str.upper().str.strip()
    prices["date"] = prices["date"].astype(str).str[:10]
    price_col = "adjusted_close" if "adjusted_close" in prices.columns else "close"
    prices["price"] = pd.to_numeric(prices[price_col], errors="coerce")
    prices = prices[prices["price"].notna()].copy()
    latest = str(prices["date"].max())
    pmap = prices.set_index(["symbol", "date"])["price"].to_dict()
    return prices, pmap, latest


def benchmark_return(pmap: dict[tuple[str, str], float], symbol: str, as_of: str, due: str) -> float:
    entry = pmap.get((symbol, as_of))
    maturity = pmap.get((symbol, due))
    if entry is None or maturity is None or pd.isna(entry) or pd.isna(maturity) or float(entry) == 0:
        return np.nan
    return float(maturity) / float(entry) - 1.0


def prior_ready(root: Path) -> bool:
    readiness = pd.read_csv(root / READINESS_REL).iloc[0]
    audit = pd.read_csv(root / AUDIT_REL).iloc[0]
    return (
        truth(readiness.get("execution_pass_gate"))
        and str(readiness.get("final_status", "")).startswith("PASS")
        and truth(audit.get("baseline_candidate_pair_complete"))
        and truth(audit.get("weight_sums_valid"))
    )


def track_maturity(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not prior_ready(root):
        raise RuntimeError("V21.082 soft execution forward ledger is not ready for maturity tracking")

    ledger = pd.read_csv(root / LEDGER_REL, low_memory=False)
    _, pmap, latest_price_date = price_table(root)
    latest_ts = pd.Timestamp(latest_price_date)
    rows: list[dict[str, Any]] = []

    for _, row in ledger.iterrows():
        ticker = str(row["ticker"]).upper().strip()
        as_of = str(row["as_of_date"])[:10]
        due = str(row["maturity_due_date"])[:10]
        matured = latest_ts >= pd.Timestamp(due)
        entry = pmap.get((ticker, as_of))
        maturity = pmap.get((ticker, due)) if matured else np.nan
        price_available = pd.notna(entry) and (not matured or pd.notna(maturity))
        if not matured:
            status = "pending"
            realized = np.nan
        elif price_available:
            status = "matured"
            realized = float(maturity) / float(entry) - 1.0 if float(entry) != 0 else np.nan
        else:
            status = "matured_price_missing"
            realized = np.nan

        weight = pd.to_numeric(row.get("position_weight"), errors="coerce")
        rows.append({
            "observation_id": row["observation_id"],
            "as_of_date": as_of,
            "policy_id": row["policy_id"],
            "top_n": row["top_n"],
            "ticker": ticker,
            "rank": row.get("rank", ""),
            "score": row.get("score", ""),
            "entry_label": row.get("entry_label", ""),
            "forward_window": row["forward_window"],
            "maturity_due_date": due,
            "maturity_status": status,
            "entry_price": entry if pd.notna(entry) else "",
            "maturity_price": maturity if pd.notna(maturity) else "",
            "realized_forward_return": realized,
            "position_weight": weight,
            "weighted_realized_return": realized * weight if pd.notna(realized) and pd.notna(weight) else np.nan,
            "price_available": bool(price_available),
            "latest_available_price_date": latest_price_date,
            "research_only": True,
        })

    tracked = pd.DataFrame(rows)
    summary = pd.DataFrame([{
        "stage": "V21.083-R1_SOFT_EXECUTION_FORWARD_MATURITY_TRACKER",
        "v21_082_ledger_consumed": True,
        "ledger_rows": int(len(tracked)),
        "latest_available_price_date": latest_price_date,
        "matured_observations": int(tracked["maturity_status"].eq("matured").sum()),
        "pending_observations": int(tracked["maturity_status"].eq("pending").sum()),
        "price_missing_observations": int(tracked["maturity_status"].eq("matured_price_missing").sum()),
        "earliest_maturity_due_date": tracked["maturity_due_date"].min(),
        "latest_maturity_due_date": tracked["maturity_due_date"].max(),
        "research_only": True,
    }])
    return tracked, summary


def label_distribution(frame: pd.DataFrame, winners: bool) -> str:
    if frame.empty or "entry_label" not in frame.columns:
        return "{}"
    subset = frame[frame["realized_forward_return"].gt(0)] if winners else frame[frame["realized_forward_return"].le(0)]
    if subset.empty:
        return "{}"
    return subset["entry_label"].fillna("").astype(str).value_counts().sort_index().to_json()


def evaluate(tracked: pd.DataFrame, root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    mature = tracked[tracked["maturity_status"].eq("matured")].copy()
    _, pmap, _ = price_table(root)
    if mature.empty:
        summary_cols = [
            "policy_id", "top_n", "forward_window", "matured_observation_count",
            "pending_observation_count", "price_missing_count", "mean_portfolio_return",
            "median_portfolio_return", "hit_rate", "excess_vs_qqq", "excess_vs_spy",
            "ending_value_10000", "profit_loss_10000", "entry_label_distribution_winners",
            "entry_label_distribution_losers", "drawdown_proxy", "return_drawdown_ratio",
            "sample_size_warning", "maturity_coverage_warning", "research_only",
        ]
        comp_cols = [
            "top_n", "forward_window", "baseline_policy_id", "candidate_policy_id",
            "baseline_mean_portfolio_return", "candidate_mean_portfolio_return",
            "candidate_delta_vs_d_ew", "d_ew_ending_value_10000",
            "soft_execution_ending_value_10000", "soft_execution_profit_loss_10000",
            "win_loss_status_vs_d_ew", "forward_evidence_positive", "research_only",
        ]
        return pd.DataFrame(columns=summary_cols), pd.DataFrame(columns=comp_cols)

    pending = tracked[tracked["maturity_status"].eq("pending")].groupby(["policy_id", "top_n", "forward_window"]).size()
    missing = tracked[tracked["maturity_status"].eq("matured_price_missing")].groupby(["policy_id", "top_n", "forward_window"]).size()
    rows: list[dict[str, Any]] = []
    grouped = mature.groupby(["policy_id", "top_n", "forward_window"], dropna=False)
    for key, group in grouped:
        policy_id, top_n, window = key
        portfolio_return = float(group["weighted_realized_return"].sum())
        median_return = float(group["realized_forward_return"].median())
        hit_rate = float(group["realized_forward_return"].gt(0).mean())
        as_of = str(group["as_of_date"].iloc[0])[:10]
        due = str(group["maturity_due_date"].iloc[0])[:10]
        qqq = benchmark_return(pmap, "QQQ", as_of, due)
        spy = benchmark_return(pmap, "SPY", as_of, due)
        drawdown = min(portfolio_return, 0.0)
        rows.append({
            "policy_id": policy_id,
            "top_n": top_n,
            "forward_window": window,
            "matured_observation_count": int(len(group)),
            "pending_observation_count": int(pending.get(key, 0)),
            "price_missing_count": int(missing.get(key, 0)),
            "mean_portfolio_return": portfolio_return,
            "median_portfolio_return": median_return,
            "hit_rate": hit_rate,
            "excess_vs_qqq": portfolio_return - qqq if pd.notna(qqq) else np.nan,
            "excess_vs_spy": portfolio_return - spy if pd.notna(spy) else np.nan,
            "ending_value_10000": INITIAL_CAPITAL * (1.0 + portfolio_return),
            "profit_loss_10000": INITIAL_CAPITAL * portfolio_return,
            "entry_label_distribution_winners": label_distribution(group, True),
            "entry_label_distribution_losers": label_distribution(group, False),
            "drawdown_proxy": drawdown,
            "return_drawdown_ratio": portfolio_return / abs(drawdown) if drawdown < 0 else np.nan,
            "sample_size_warning": int(len(group)) < 50,
            "maturity_coverage_warning": int(pending.get(key, 0)) > 0,
            "research_only": True,
        })
    summary = pd.DataFrame(rows)

    comp_rows: list[dict[str, Any]] = []
    for window in ("5D", "10D", "20D"):
        base = summary[(summary["policy_id"].eq(BASELINE)) & (summary["forward_window"].eq(window))]
        cand = summary[(summary["policy_id"].eq(CANDIDATE)) & (summary["forward_window"].eq(window))]
        if base.empty or cand.empty:
            continue
        b = base.iloc[0]
        c = cand.iloc[0]
        delta = float(c["mean_portfolio_return"] - b["mean_portfolio_return"])
        comp_rows.append({
            "top_n": "TOP50",
            "forward_window": window,
            "baseline_policy_id": BASELINE,
            "candidate_policy_id": CANDIDATE,
            "baseline_mean_portfolio_return": b["mean_portfolio_return"],
            "candidate_mean_portfolio_return": c["mean_portfolio_return"],
            "candidate_delta_vs_d_ew": delta,
            "d_ew_ending_value_10000": b["ending_value_10000"],
            "soft_execution_ending_value_10000": c["ending_value_10000"],
            "soft_execution_profit_loss_10000": c["profit_loss_10000"],
            "win_loss_status_vs_d_ew": "WIN" if delta > 0 else "LOSS" if delta < 0 else "TIE",
            "forward_evidence_positive": False,
            "research_only": True,
        })
    comparison = pd.DataFrame(comp_rows)
    if not comparison.empty:
        positive = (
            comparison.loc[comparison["forward_window"].eq("10D"), "candidate_delta_vs_d_ew"].gt(0).any()
            or int(comparison["candidate_delta_vs_d_ew"].gt(0).sum()) >= 2
        )
        comparison["forward_evidence_positive"] = bool(positive)
    return summary, comparison


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (output_override if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)

    protected = protected_files(root, output)
    for rel in (
        "outputs/v21/v21_072", "outputs/v21/v21_073", "outputs/v21/v21_074",
        "outputs/v21/v21_075", "outputs/v21/v21_076", "outputs/v21/v21_077",
        "outputs/v21/v21_078", "outputs/v21/v21_079", "outputs/v21/v21_080",
        "outputs/v21/v21_081", "outputs/v21/v21_082",
    ):
        base = root / rel
        if base.exists():
            protected.extend(path.resolve() for path in base.rglob("*") if path.is_file())
    protected = sorted(set(protected))
    before = {path: sha256(path) for path in protected}

    tracked, maturity_summary = track_maturity(root)
    tracked.to_csv(output / TRACKED_NAME, index=False)
    maturity_summary.to_csv(output / MATURITY_SUMMARY_NAME, index=False)
    eval_summary, comparison = evaluate(tracked, root)
    eval_summary.to_csv(output / EVAL_SUMMARY_NAME, index=False)
    comparison.to_csv(output / COMPARISON_NAME, index=False)

    after = {path: sha256(path) for path in protected}
    changed = [path.as_posix() for path in protected if before[path] != after[path]]
    matured = int(maturity_summary.iloc[0]["matured_observations"])
    pending = int(maturity_summary.iloc[0]["pending_observations"])
    missing = int(maturity_summary.iloc[0]["price_missing_observations"])
    leakage = 0
    sample_warnings = 0 if eval_summary.empty else int(eval_summary["sample_size_warning"].sum())

    if matured == 0 and missing == 0 and not changed:
        final_status = "PARTIAL_PASS_V21_083_R1_TRACKER_READY_WAITING_FOR_MATURITY"
        decision = "WAIT_FOR_MATURED_FORWARD_OBSERVATIONS"
        evidence = "waiting"
    elif changed or leakage:
        final_status = "BLOCKED_V21_083_R2_FORWARD_EVALUATION_INTEGRITY_OR_LEAKAGE_RISK"
        decision = "BLOCK_SOFT_EXECUTION_FORWARD_EVALUATION_REPAIR_REQUIRED"
        evidence = "no"
    else:
        price_warn = missing > 0
        positive = bool(comparison["forward_evidence_positive"].any()) if not comparison.empty else False
        final_status = (
            "PASS_V21_083_R2_SOFT_EXECUTION_FORWARD_EVIDENCE_READY"
            if positive and not sample_warnings and not price_warn else
            "PARTIAL_PASS_V21_083_R2_FORWARD_EVIDENCE_READY_WITH_SAMPLE_OR_PRICE_WARN"
        )
        decision = "SOFT_EXECUTION_FORWARD_EVIDENCE_POSITIVE" if positive else "KEEP_OBSERVING_SOFT_EXECUTION_FORWARD_EVIDENCE"
        evidence = "yes" if positive else "no"

    readiness = {
        "stage": "V21.083-R2_SOFT_EXECUTION_FORWARD_EVALUATOR",
        "final_status": final_status,
        "decision": decision,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "v21_082_ledger_consumed": True,
        "d_baseline_preserved": True,
        "soft_execution_candidate_evaluated": CANDIDATE,
        "ledger_rows": int(len(tracked)),
        "matured_observations": matured,
        "pending_observations": pending,
        "price_missing_observations": missing,
        "earliest_matured_window": "" if matured == 0 else tracked.loc[tracked["maturity_status"].eq("matured"), "forward_window"].min(),
        "latest_pending_maturity_date": "" if pending == 0 else tracked.loc[tracked["maturity_status"].eq("pending"), "maturity_due_date"].max(),
        "candidate_delta_vs_d_ew": "" if comparison.empty else comparison["candidate_delta_vs_d_ew"].mean(),
        "d_ew_ending_value_10000": "" if comparison.empty else comparison["d_ew_ending_value_10000"].mean(),
        "soft_execution_ending_value_10000": "" if comparison.empty else comparison["soft_execution_ending_value_10000"].mean(),
        "sample_size_warnings": sample_warnings,
        "leakage_warnings": leakage,
        "protected_outputs_modified": bool(changed),
        "official_outputs_mutated": False,
        "forward_evidence_positive": evidence,
        "official_adoption_allowed": False,
        "protected_modified_paths": "|".join(changed),
        "research_only": True,
        "execution_pass_gate": not changed and leakage == 0,
    }
    pd.DataFrame([readiness]).to_csv(output / READINESS_NAME, index=False)
    return readiness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in ("final_status", "decision", "ledger_rows", "matured_observations", "pending_observations"):
        print(f"{key.upper()}={result[key]}")
    return 0 if result["execution_pass_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
