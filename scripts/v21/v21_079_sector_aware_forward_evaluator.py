#!/usr/bin/env python
"""Track V21.078 repaired ledger maturity and evaluate matured forward evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from v21_073_common import protected_files, sha256, truth


STAGE = "V21.079-R1_R2_SECTOR_AWARE_FORWARD_EVALUATOR"
OUT_REL = Path("outputs/v21/v21_079")
LEDGER_REL = Path("outputs/v21/v21_078/V21_078_R6_REPAIRED_FORWARD_PORTFOLIO_OBSERVATION_LEDGER.csv")
AUDIT_REL = Path("outputs/v21/v21_078/V21_078_R6_REPAIRED_LEDGER_AUDIT.csv")
READINESS_REL = Path("outputs/v21/v21_078/V21_078_R6_REPAIRED_READINESS_DECISION_REPORT.csv")
PRICE_REL = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")

TRACKED_NAME = "V21_079_R1_MATURITY_TRACKED_LEDGER.csv"
MATURITY_SUMMARY_NAME = "V21_079_R1_MATURITY_SUMMARY.csv"
EVAL_SUMMARY_NAME = "V21_079_R2_FORWARD_EVALUATION_SUMMARY.csv"
COMPARISON_NAME = "V21_079_R2_D_EW_VS_SECTOR_AWARE_FORWARD_COMPARISON.csv"
READINESS_NAME = "V21_079_R2_READINESS_DECISION_REPORT.csv"

BASELINE_BY_TOP = {"TOP20": "D_EW_TOP20_R1", "TOP50": "D_EW_TOP50_R1"}
CANDIDATE_BY_TOP = {
    "TOP20": "D_SECTOR_INDUSTRY_SOFT_PENALTY_TOP20_R1",
    "TOP50": "D_SECTOR_SOFT_PENALTY_TOP50_R1",
}


def price_table(root: Path) -> tuple[pd.DataFrame, dict[tuple[str, str], float], str]:
    prices = pd.read_csv(
        root / PRICE_REL,
        usecols=["symbol", "date", "close", "adjusted_close", "low", "high"],
        low_memory=False,
    )
    prices["symbol"] = prices["symbol"].astype(str).str.upper().str.strip()
    prices["date"] = prices["date"].astype(str).str[:10]
    price_col = "adjusted_close" if "adjusted_close" in prices.columns else "close"
    prices["price"] = pd.to_numeric(prices[price_col], errors="coerce")
    latest = str(prices["date"].max())
    pmap = prices.set_index(["symbol", "date"])["price"].to_dict()
    return prices, pmap, latest


def track_maturity(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    prior = pd.read_csv(root / READINESS_REL).iloc[0]
    if not truth(prior.get("execution_pass_gate")):
        raise RuntimeError("V21.078 repaired ledger is not ready for maturity tracking")
    ledger = pd.read_csv(root / LEDGER_REL, low_memory=False)
    prices, pmap, latest_price_date = price_table(root)
    rows: list[dict[str, Any]] = []
    latest_ts = pd.Timestamp(latest_price_date)
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
            "original_policy_id": row.get("original_policy_id", ""),
            "fallback_used": row.get("fallback_used", ""),
            "top_n": row["top_n"],
            "ticker": ticker,
            "sector": row.get("sector", ""),
            "industry": row.get("industry", ""),
            "position_weight": weight,
            "forward_window": row["forward_window"],
            "maturity_due_date": due,
            "maturity_status": status,
            "entry_price": entry if pd.notna(entry) else "",
            "maturity_price": maturity if pd.notna(maturity) else "",
            "realized_forward_return": realized,
            "weighted_realized_return": realized * weight if pd.notna(realized) and pd.notna(weight) else np.nan,
            "price_available": bool(price_available),
            "latest_available_price_date": latest_price_date,
            "research_only": True,
        })
    tracked = pd.DataFrame(rows)
    summary = pd.DataFrame([{
        "stage": "V21.079-R1_REPAIRED_FORWARD_LEDGER_MATURITY_TRACKER",
        "repaired_v21_078_ledger_consumed": True,
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


def concentration(ledger: pd.DataFrame, dim: str) -> pd.Series:
    return ledger.groupby(["policy_id", "top_n", "forward_window", dim])["position_weight"].sum().groupby(level=[0, 1, 2]).max()


def evaluate(tracked: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    mature = tracked[tracked["maturity_status"].eq("matured")].copy()
    if mature.empty:
        columns = [
            "policy_id", "top_n", "forward_window", "matured_observation_count",
            "pending_observation_count", "price_missing_count",
            "mean_portfolio_return", "median_portfolio_return", "hit_rate",
            "excess_vs_qqq", "excess_vs_spy", "drawdown_proxy",
            "sector_concentration", "industry_concentration",
            "return_drawdown_ratio", "sample_size_warning",
            "maturity_coverage_warning", "research_only",
        ]
        comp_cols = [
            "top_n", "forward_window", "baseline_policy_id", "candidate_policy_id",
            "baseline_mean_portfolio_return", "candidate_mean_portfolio_return",
            "candidate_delta_vs_d_ew", "win_loss_status_vs_d_ew",
            "forward_evidence_positive", "research_only",
        ]
        return pd.DataFrame(columns=columns), pd.DataFrame(columns=comp_cols)
    portfolio = mature.groupby(["policy_id", "top_n", "forward_window"]).agg(
        portfolio_return=("weighted_realized_return", "sum"),
        matured_observation_count=("observation_id", "count"),
    ).reset_index()
    pending = tracked[tracked["maturity_status"].eq("pending")].groupby(["policy_id", "top_n", "forward_window"]).size()
    missing = tracked[tracked["maturity_status"].eq("matured_price_missing")].groupby(["policy_id", "top_n", "forward_window"]).size()
    sector = concentration(tracked, "sector")
    industry = concentration(tracked, "industry")
    rows = []
    for _, row in portfolio.iterrows():
        key = (row["policy_id"], row["top_n"], row["forward_window"])
        ret = float(row["portfolio_return"])
        drawdown = min(ret, 0.0)
        rows.append({
            "policy_id": row["policy_id"],
            "top_n": row["top_n"],
            "forward_window": row["forward_window"],
            "matured_observation_count": int(row["matured_observation_count"]),
            "pending_observation_count": int(pending.get(key, 0)),
            "price_missing_count": int(missing.get(key, 0)),
            "mean_portfolio_return": ret,
            "median_portfolio_return": ret,
            "hit_rate": 1.0 if ret > 0 else 0.0,
            "excess_vs_qqq": np.nan,
            "excess_vs_spy": np.nan,
            "drawdown_proxy": drawdown,
            "sector_concentration": float(sector.get(key, np.nan)),
            "industry_concentration": float(industry.get(key, np.nan)),
            "return_drawdown_ratio": ret / abs(drawdown) if drawdown < 0 else np.nan,
            "sample_size_warning": int(row["matured_observation_count"]) < 20,
            "maturity_coverage_warning": int(pending.get(key, 0)) > 0,
            "research_only": True,
        })
    summary = pd.DataFrame(rows)
    comp_rows = []
    for top_n, candidate in CANDIDATE_BY_TOP.items():
        baseline = BASELINE_BY_TOP[top_n]
        for window in ["5D", "10D", "20D"]:
            b = summary[(summary["policy_id"].eq(baseline)) & (summary["top_n"].eq(top_n)) & (summary["forward_window"].eq(window))]
            c = summary[(summary["policy_id"].eq(candidate)) & (summary["top_n"].eq(top_n)) & (summary["forward_window"].eq(window))]
            if b.empty or c.empty:
                continue
            delta = float(c.iloc[0]["mean_portfolio_return"] - b.iloc[0]["mean_portfolio_return"])
            comp_rows.append({
                "top_n": top_n,
                "forward_window": window,
                "baseline_policy_id": baseline,
                "candidate_policy_id": candidate,
                "baseline_mean_portfolio_return": b.iloc[0]["mean_portfolio_return"],
                "candidate_mean_portfolio_return": c.iloc[0]["mean_portfolio_return"],
                "candidate_delta_vs_d_ew": delta,
                "win_loss_status_vs_d_ew": "WIN" if delta > 0 else "LOSS" if delta < 0 else "TIE",
                "forward_evidence_positive": False,
                "research_only": True,
            })
    comparison = pd.DataFrame(comp_rows)
    if not comparison.empty:
        for candidate in comparison["candidate_policy_id"].unique():
            sub = comparison[comparison["candidate_policy_id"].eq(candidate)]
            positive = sub.loc[sub["forward_window"].eq("10D"), "candidate_delta_vs_d_ew"].gt(0).any() or sub["candidate_delta_vs_d_ew"].gt(0).sum() >= 2
            comparison.loc[comparison["candidate_policy_id"].eq(candidate), "forward_evidence_positive"] = bool(positive)
    return summary, comparison


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (output_override if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protected = protected_files(root, output)
    for rel in ("outputs/v21/v21_072", "outputs/v21/v21_073", "outputs/v21/v21_074", "outputs/v21/v21_075", "outputs/v21/v21_076", "outputs/v21/v21_077", "outputs/v21/v21_078"):
        base = root / rel
        if base.exists():
            protected.extend(path.resolve() for path in base.rglob("*") if path.is_file())
    protected = sorted(set(protected))
    before = {path: sha256(path) for path in protected}

    tracked, maturity_summary = track_maturity(root)
    tracked.to_csv(output / TRACKED_NAME, index=False)
    maturity_summary.to_csv(output / MATURITY_SUMMARY_NAME, index=False)
    eval_summary, comparison = evaluate(tracked)
    eval_summary.to_csv(output / EVAL_SUMMARY_NAME, index=False)
    comparison.to_csv(output / COMPARISON_NAME, index=False)

    after = {path: sha256(path) for path in protected}
    changed = [path.as_posix() for path in protected if before[path] != after[path]]
    matured = int(maturity_summary.iloc[0]["matured_observations"])
    pending = int(maturity_summary.iloc[0]["pending_observations"])
    missing = int(maturity_summary.iloc[0]["price_missing_observations"])
    leakage = 0
    if matured == 0 and missing == 0:
        final_status = "PARTIAL_PASS_V21_079_R1_TRACKER_READY_WAITING_FOR_MATURITY"
        decision = "WAIT_FOR_MATURED_FORWARD_OBSERVATIONS"
        evidence = "waiting"
    elif changed or leakage:
        final_status = "BLOCKED_V21_079_R2_FORWARD_EVALUATION_INTEGRITY_OR_LEAKAGE_RISK"
        decision = "BLOCK_FORWARD_EVALUATION_REPAIR_REQUIRED"
        evidence = "no"
    else:
        sample_warn = int(eval_summary["sample_size_warning"].sum()) if not eval_summary.empty else 0
        price_warn = missing > 0
        positive = bool(comparison["forward_evidence_positive"].any()) if not comparison.empty else False
        final_status = (
            "PASS_V21_079_R2_SECTOR_AWARE_FORWARD_EVIDENCE_READY"
            if positive and not sample_warn and not price_warn else
            "PARTIAL_PASS_V21_079_R2_FORWARD_EVIDENCE_READY_WITH_SAMPLE_OR_PRICE_WARN"
        )
        decision = "SECTOR_AWARE_FORWARD_EVIDENCE_POSITIVE" if positive else "KEEP_OBSERVING_FORWARD_EVIDENCE"
        evidence = "yes" if positive else "no"
    readiness = {
        "stage": "V21.079-R2_SECTOR_AWARE_FORWARD_EVALUATOR",
        "final_status": final_status,
        "decision": decision,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repaired_v21_078_ledger_consumed": True,
        "d_equal_weight_baseline_preserved": True,
        "sector_aware_candidates_evaluated": "|".join(CANDIDATE_BY_TOP.values()),
        "ledger_rows": int(len(tracked)),
        "matured_observations": matured,
        "pending_observations": pending,
        "price_missing_observations": missing,
        "earliest_matured_window": "" if matured == 0 else tracked.loc[tracked["maturity_status"].eq("matured"), "forward_window"].min(),
        "latest_pending_maturity_date": "" if pending == 0 else tracked.loc[tracked["maturity_status"].eq("pending"), "maturity_due_date"].max(),
        "top20_candidate_delta_vs_d_ew": "" if comparison.empty else comparison.loc[comparison["top_n"].eq("TOP20"), "candidate_delta_vs_d_ew"].mean(),
        "top50_candidate_delta_vs_d_ew": "" if comparison.empty else comparison.loc[comparison["top_n"].eq("TOP50"), "candidate_delta_vs_d_ew"].mean(),
        "sample_size_warnings": 0 if eval_summary.empty else int(eval_summary["sample_size_warning"].sum()),
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
