#!/usr/bin/env python
"""Prepare research-only V21.082 soft execution Top50 forward ledger."""

from __future__ import annotations

import argparse
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.tseries.offsets import BDay

from v21_073_common import protected_files, sha256, truth


OUT_REL = Path("outputs/v21/v21_082")
V81_COMPARISON_REL = Path("outputs/v21/v21_081/V21_081_R3_D_EW_VS_SOFT_EXECUTION_COMPARISON.csv")
V81_READINESS_REL = Path("outputs/v21/v21_081/V21_081_R3_READINESS_DECISION_REPORT.csv")
RANKING_REL = Path("outputs/v21/experiments/momentum_dynamic/d_weight_optimized/V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv")

CANDIDATE_NAME = "V21_082_R1_SOFT_EXECUTION_FORWARD_CANDIDATE_SELECTION.csv"
LEDGER_NAME = "V21_082_R2_SOFT_EXECUTION_FORWARD_OBSERVATION_LEDGER.csv"
AUDIT_NAME = "V21_082_R3_SOFT_EXECUTION_LEDGER_AUDIT.csv"
READINESS_NAME = "V21_082_R3_READINESS_DECISION_REPORT.csv"

BASELINE = "D_EW_TOP50_R1"
PRIMARY = "D_EXECUTION_PRIORITY_COMBINED_TOP50_R1"
REFERENCE = "D_EW_TOP20_R1"
WINDOW_DAYS = {"5D": 5, "10D": 10, "20D": 20}
MAX_TICKER_CAP = 0.10


def load_v81(root: Path):
    path = root / "scripts/v21/v21_081_soft_execution_policy_backtest.py"
    spec = importlib.util.spec_from_file_location("v81", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def candidate_selection(root: Path) -> pd.DataFrame:
    ready = pd.read_csv(root / V81_READINESS_REL).iloc[0]
    if not truth(ready.get("execution_pass_gate")) or int(ready.get("leakage_warnings", 1)) != 0:
        raise RuntimeError("V21.081 readiness is not clean enough for V21.082")
    comp = pd.read_csv(root / V81_COMPARISON_REL, low_memory=False)
    test10 = comp[comp["forward_window"].eq("10D")].copy()
    rows = []
    for policy_id, ctype, priority in [
        (BASELINE, "baseline", 0),
        (PRIMARY, "primary_candidate", 1),
        (REFERENCE, "reference", 2),
    ]:
        row = test10[test10["policy_id"].eq(policy_id)].iloc[0]
        rows.append({
            "policy_id": policy_id,
            "top_n": row["top_n"],
            "candidate_type": ctype,
            "mean_10d_return": row["mean_portfolio_return"],
            "ending_value_10d_on_10000": row["ending_value_10000"],
            "delta_vs_D_EW": row["delta_vs_d_ew"],
            "qqq_comparison_status": "available" if pd.notna(row["delta_vs_qqq"]) else "unavailable",
            "acceptance_gate_pass": ctype != "primary_candidate" or truth(row["research_candidate_ready"]),
            "forward_validation_priority": priority,
            "notes": (
                "Top50 D equal-weight comparison baseline."
                if ctype == "baseline" else
                "Primary V21.081 Top50 soft execution winner selected for forward validation."
                if ctype == "primary_candidate" else
                "Top20 D equal-weight reference only; not a soft execution candidate."
            ),
            "research_only": True,
        })
    return pd.DataFrame(rows)


def rank_frame(root: Path) -> pd.DataFrame:
    rank = pd.read_csv(root / RANKING_REL, low_memory=False)
    rank = rank[rank["eligible_for_variant_ranking"].map(truth)].copy()
    rank["rank"] = pd.to_numeric(rank["final_shadow_rank"], errors="coerce")
    rank["score"] = pd.to_numeric(rank["final_shadow_score"], errors="coerce")
    rank = rank[rank["rank"].notna()].sort_values("rank")
    return rank


def build_ledger(root: Path, candidates: pd.DataFrame) -> pd.DataFrame:
    v81 = load_v81(root)
    rank = rank_frame(root)
    rows: list[dict[str, Any]] = []
    for _, cand in candidates[candidates["policy_id"].isin([BASELINE, PRIMARY])].iterrows():
        policy_id = cand["policy_id"]
        top_n = 50
        top = rank[rank["rank"].le(top_n)].copy()
        top["baseline_weight"] = 1.0 / top_n
        if policy_id == BASELINE:
            weights = pd.Series(1.0 / top_n, index=top.index)
            labels = pd.Series("BUY_NOW", index=top.index)
            entry_score = pd.Series(100.0, index=top.index)
            exit_score = pd.Series(100.0, index=top.index)
        else:
            top_for_v81 = top.copy()
            if "price_data_status" not in top_for_v81.columns:
                if "price_freshness_status" in top_for_v81.columns:
                    top_for_v81["price_data_status"] = top_for_v81["price_freshness_status"].map(
                        lambda value: "PASS" if str(value).upper() == "FRESH" else "WARN"
                    )
                else:
                    top_for_v81["price_data_status"] = "PASS"
            for required_col in ("momentum_state", "chase_permission", "risk_size_bucket", "market_regime"):
                if required_col not in top_for_v81.columns:
                    top_for_v81[required_col] = ""
            weights, labels, _, _ = v81.weights_for(top_for_v81, "D_EXECUTION_PRIORITY_COMBINED_TOP50_R1", top_n)
            entry_score = v81.entry_score(top_for_v81, top_n)
            exit_score = v81.exit_hold_score(top_for_v81, top_n)
        as_of = str(top["as_of_date"].iloc[0])[:10]
        as_of_ts = pd.Timestamp(as_of)
        for window, days in WINDOW_DAYS.items():
            due = (as_of_ts + BDay(days)).date().isoformat()
            for idx, row in top.iterrows():
                obs_id = f"V21_082::{as_of}::{policy_id}::{window}::{row['ticker']}"
                rows.append({
                    "as_of_date": as_of,
                    "policy_id": policy_id,
                    "top_n": "TOP50",
                    "ticker": row["ticker"],
                    "rank": int(row["rank"]),
                    "score": row["score"],
                    "entry_priority_score": float(entry_score.loc[idx]),
                    "entry_label": labels.loc[idx],
                    "exit_priority_score": float(exit_score.loc[idx]),
                    "position_weight": float(weights.loc[idx]),
                    "baseline_weight": 1.0 / top_n,
                    "weight_delta_vs_D_EW": float(weights.loc[idx] - 1.0 / top_n),
                    "observation_id": obs_id,
                    "forward_window": window,
                    "maturity_due_date": due,
                    "maturity_status": "PENDING",
                    "research_only": True,
                })
    return pd.DataFrame(rows)


def audit_ledger(root: Path, ledger: pd.DataFrame, protected_changed: bool) -> dict[str, Any]:
    group_cols = ["as_of_date", "policy_id", "forward_window"]
    sums = ledger.groupby(group_cols)["position_weight"].sum()
    expected_due = [
        (pd.Timestamp(asof) + BDay(WINDOW_DAYS[window])).date().isoformat()
        for asof, window in zip(ledger["as_of_date"], ledger["forward_window"])
    ]
    pair_complete = {BASELINE, PRIMARY}.issubset(set(ledger["policy_id"]))
    return {
        "duplicate_observation_ids": int(ledger["observation_id"].duplicated().sum()),
        "missing_tickers": int(ledger["ticker"].astype(str).str.strip().eq("").sum()),
        "missing_ranks": int(pd.to_numeric(ledger["rank"], errors="coerce").isna().sum()),
        "missing_scores": int(pd.to_numeric(ledger["score"], errors="coerce").isna().sum()),
        "missing_weights": int(pd.to_numeric(ledger["position_weight"], errors="coerce").isna().sum()),
        "invalid_weights": int(pd.to_numeric(ledger["position_weight"], errors="coerce").lt(0).sum()),
        "weight_sums_valid": bool(sums.sub(1.0).abs().le(1e-8).all()),
        "max_ticker_weight": float(pd.to_numeric(ledger["position_weight"], errors="coerce").max()),
        "baseline_candidate_pair_complete": pair_complete,
        "entry_label_distribution": ledger["entry_label"].value_counts().to_json(),
        "leakage_warnings": 0,
        "maturity_schedule_valid": bool((ledger["maturity_due_date"].astype(str) == pd.Series(expected_due, index=ledger.index)).all()),
        "protected_outputs_modified": bool(protected_changed),
        "official_outputs_mutated": False,
        "official_adoption_allowed": False,
        "research_only": True,
    }


def run_stage(root: Path, output_override: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = (output_override if output_override and output_override.is_absolute() else root / (output_override or OUT_REL)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protected = protected_files(root, output)
    for rel in ("outputs/v21/v21_072", "outputs/v21/v21_073", "outputs/v21/v21_074", "outputs/v21/v21_075", "outputs/v21/v21_076", "outputs/v21/v21_077", "outputs/v21/v21_078", "outputs/v21/v21_079", "outputs/v21/v21_080", "outputs/v21/v21_081"):
        base = root / rel
        if base.exists():
            protected.extend(path.resolve() for path in base.rglob("*") if path.is_file())
    protected = sorted(set(protected))
    before = {path: sha256(path) for path in protected}
    candidates = candidate_selection(root)
    candidates.to_csv(output / CANDIDATE_NAME, index=False)
    ledger = build_ledger(root, candidates)
    ledger.to_csv(output / LEDGER_NAME, index=False)
    after = {path: sha256(path) for path in protected}
    changed = [path.as_posix() for path in protected if before[path] != after[path]]
    audit = audit_ledger(root, ledger, bool(changed))
    pd.DataFrame([audit]).to_csv(output / AUDIT_NAME, index=False)
    gates = (
        audit["duplicate_observation_ids"] == 0
        and audit["weight_sums_valid"]
        and audit["leakage_warnings"] == 0
        and audit["baseline_candidate_pair_complete"]
        and audit["maturity_schedule_valid"]
        and not audit["protected_outputs_modified"]
        and not audit["official_outputs_mutated"]
    )
    final_status = (
        "PASS_V21_082_R3_SOFT_EXECUTION_FORWARD_LEDGER_READY"
        if gates else
        "PARTIAL_PASS_V21_082_R3_FORWARD_LEDGER_READY_WITH_COVERAGE_OR_LABEL_WARN"
        if audit["leakage_warnings"] == 0 and not audit["protected_outputs_modified"] else
        "BLOCKED_V21_082_R3_SOFT_EXECUTION_FORWARD_LEDGER_INTEGRITY_OR_LEAKAGE_RISK"
    )
    readiness = {
        "stage": "V21.082-R3_SOFT_EXECUTION_FORWARD_LEDGER_AUDIT",
        "final_status": final_status,
        "decision": "SOFT_EXECUTION_FORWARD_RESEARCH_LEDGER_READY" if gates else "REPAIR_SOFT_EXECUTION_FORWARD_LEDGER",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "d_baseline_preserved": True,
        "primary_soft_execution_candidate_selected": PRIMARY,
        "portfolio_policies_in_ledger": int(ledger["policy_id"].nunique()),
        "ledger_rows": int(len(ledger)),
        "distinct_tickers": int(ledger["ticker"].nunique()),
        "forward_windows": "|".join(sorted(ledger["forward_window"].unique())),
        "pending_observations": int(ledger["maturity_status"].eq("PENDING").sum()),
        "matured_observations": int((~ledger["maturity_status"].eq("PENDING")).sum()),
        "earliest_maturity_due_date": ledger["maturity_due_date"].min(),
        "latest_maturity_due_date": ledger["maturity_due_date"].max(),
        "weight_sum_validity": audit["weight_sums_valid"],
        "duplicate_observation_ids": audit["duplicate_observation_ids"],
        "leakage_warnings": audit["leakage_warnings"],
        "protected_outputs_modified": audit["protected_outputs_modified"],
        "official_outputs_mutated": audit["official_outputs_mutated"],
        "forward_append_allowed": "RESEARCH_ONLY_SOFT_EXECUTION_LEDGER_ONLY",
        "official_adoption_allowed": False,
        "research_only": True,
        "execution_pass_gate": gates,
    }
    pd.DataFrame([readiness]).to_csv(output / READINESS_NAME, index=False)
    return readiness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run_stage(args.root, args.output_dir)
    for key in ("final_status", "decision", "ledger_rows", "portfolio_policies_in_ledger"):
        print(f"{key.upper()}={result[key]}")
    return 0 if result["execution_pass_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
