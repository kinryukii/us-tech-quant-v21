#!/usr/bin/env python
"""V21.100-R1 diagnostic decomposition of the V21.100 no-edge decision."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUT = Path("outputs/v21")
BACKTEST = OUT / "v21_100_r5_event_row_weight_backtest_results.csv"
VARIANTS = OUT / "v21_100_r7_event_weight_variant_summary.csv"
ROBUSTNESS = OUT / "v21_100_r8_event_weight_robustness_checks.csv"
SUMMARY_100 = OUT / "v21_100_r9_event_risk_weight_grid_backtest_summary.json"
IMPACT = OUT / "v21_097_r3_event_type_impact_summary.csv"
VULNERABILITY = OUT / "v21_097_r4_ticker_event_vulnerability_summary.csv"
DASHBOARD = OUT / "v21_097_r6_current_d_event_risk_dashboard.csv"
D_BASELINE = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv"
)
INPUTS = (BACKTEST, VARIANTS, ROBUSTNESS, SUMMARY_100, IMPACT, VULNERABILITY, DASHBOARD)
OUTPUTS = (
    "v21_100_r1_failure_decomposition_input_validation.csv",
    "v21_100_r1_failure_decomposition_input_validation.json",
    "v21_100_r1_missed_upside_decomposition.csv",
    "v21_100_r1_ticker_concentration_audit.csv",
    "v21_100_r1_event_type_concentration_audit.csv",
    "v21_100_r1_placebo_failure_forensic.csv",
    "v21_100_r1_narrow_subset_diagnostic.csv",
    "v21_100_r1_event_weight_failure_decomposition_report.md",
    "v21_100_r1_event_weight_failure_decomposition_summary.json",
)
FOCUS_VARIANTS = (
    "POST_EVENT_OVERLAY_025",
    "POST_EVENT_OVERLAY_050",
    "FULL_EVENT_RISK_HEAVY",
    "EVENT_TYPE_PLUS_TICKER_HEAVY",
)


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    def default(value: Any) -> Any:
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            return None if np.isnan(value) else float(value)
        if isinstance(value, np.bool_):
            return bool(value)
        raise TypeError(type(value).__name__)
    path.write_text(json.dumps(payload, indent=2, default=default) + "\n", encoding="utf-8")


def protected_snapshot(root: Path, outputs: set[Path]) -> dict[str, str]:
    tokens = (
        "official", "broker", "protected", "forward_observation_ledger",
        "060_r5_d_", "066a_d_latest_ranking", "p03", "p04",
    )
    result: dict[str, str] = {}
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.resolve() not in outputs:
                if any(token in path.as_posix().lower() for token in tokens):
                    result[path.relative_to(root).as_posix()] = sha256(path)
    return result


def failure_reason(group: pd.DataFrame) -> str:
    count = len(group)
    loss = group["loss_reduction_5d"].mean()
    missed = group["missed_upside_5d"].mean()
    if count < 5:
        return "EVENT_COUNT_TOO_SMALL"
    if missed > loss:
        return "MISSED_UPSIDE_DOMINATES"
    if loss <= 0:
        return "LEFT_TAIL_REDUCTION_WEAK"
    return "MIXED_SIGNAL"


def missed_upside_decomposition(backtest: pd.DataFrame) -> pd.DataFrame:
    focus = backtest[backtest["variant_id"].isin(FOCUS_VARIANTS)].copy()
    rows = []
    for keys, group in focus.groupby(["variant_id", "event_type", "ticker"], sort=True):
        rows.append({
            "variant_id": keys[0], "event_type": keys[1], "ticker": keys[2],
            "event_count": len(group),
            "avoided_severe_loss_count": int(group["avoided_severe_loss_flag"].map(truth).sum()),
            "missed_large_winner_count": int(group["missed_large_winner_flag"].map(truth).sum()),
            "mean_loss_reduction_5d": group["loss_reduction_5d"].mean(),
            "mean_missed_upside_5d": group["missed_upside_5d"].mean(),
            "net_contribution_5d": (group["loss_reduction_5d"] - group["missed_upside_5d"]).sum(),
            "net_contribution_10d": (group["loss_reduction_10d"] - group["missed_upside_10d"]).sum(),
            "dominant_failure_reason": failure_reason(group),
            "research_only": True,
        })
    result = pd.DataFrame(rows)
    # Concentration labels are assigned only where a single ticker/type dominates a variant.
    for variant, group in result.groupby("variant_id"):
        improvement = focus[
            focus["variant_id"].eq(variant)
        ].groupby("ticker")["loss_reduction_5d"].sum()
        type_improvement = focus[
            focus["variant_id"].eq(variant)
        ].groupby("event_type")["loss_reduction_5d"].sum()
        if improvement.sum() > 0 and improvement.max() / improvement.sum() > .50:
            ticker = improvement.idxmax()
            mask = result["variant_id"].eq(variant) & result["ticker"].eq(ticker)
            result.loc[mask, "dominant_failure_reason"] = "TICKER_CONCENTRATION"
        if type_improvement.sum() > 0 and type_improvement.max() / type_improvement.sum() > .50:
            event_type = type_improvement.idxmax()
            mask = result["variant_id"].eq(variant) & result["event_type"].eq(event_type)
            result.loc[mask, "dominant_failure_reason"] = "EVENT_TYPE_CONCENTRATION"
    return result


def concentration_base(
    best: pd.DataFrame, key: str, rank_map: dict[str, Any] | None = None
) -> pd.DataFrame:
    rows = []
    total_improvement = best["loss_reduction_5d"].sum()
    total_missed = best["missed_upside_5d"].sum()
    for value, group in best.groupby(key, sort=True):
        improvement = group["loss_reduction_5d"].sum()
        missed = group["missed_upside_5d"].sum()
        row = {
            key: value,
            "event_count": len(group),
            "severe_loss_count": int(group["baseline_return_5d"].le(-.10).sum()),
            "avoided_severe_loss_count": int(group["avoided_severe_loss_flag"].map(truth).sum()),
            "missed_large_winner_count": int(group["missed_large_winner_flag"].map(truth).sum()),
            "net_contribution_5d": (group["loss_reduction_5d"] - group["missed_upside_5d"]).sum(),
            "net_contribution_10d": (group["loss_reduction_10d"] - group["missed_upside_10d"]).sum(),
            "share_of_total_improvement": improvement / total_improvement if total_improvement else 0.0,
            "share_of_total_missed_upside": missed / total_missed if total_missed else 0.0,
        }
        if rank_map is not None:
            row["current_d_rank"] = rank_map.get(str(value), np.nan)
        rows.append(row)
    return pd.DataFrame(rows)


def ticker_audit(
    best: pd.DataFrame, vulnerability: pd.DataFrame
) -> tuple[pd.DataFrame, bool]:
    rank_map = vulnerability.set_index("ticker")["current_rank"].to_dict()
    result = concentration_base(best, "ticker", rank_map)
    result = result.sort_values("share_of_total_improvement", ascending=False).reset_index(drop=True)
    top3 = result.head(3)["share_of_total_improvement"].sum()
    top5_improvement = result.head(5)["share_of_total_improvement"].sum()
    top5_missed = result.nlargest(5, "share_of_total_missed_upside")["share_of_total_missed_upside"].sum()
    risk = top5_improvement > .50 or top5_missed > .50
    result["concentration_bucket"] = np.select(
        [
            result["share_of_total_improvement"].ge(.20) | result["share_of_total_missed_upside"].ge(.20),
            result["share_of_total_improvement"].ge(.10) | result["share_of_total_missed_upside"].ge(.10),
        ],
        ["HIGH_CONCENTRATION", "MEDIUM_CONCENTRATION"],
        default="LOW_CONCENTRATION",
    )
    result["notes"] = (
        f"Top3 improvement share={top3:.4f}; top5 improvement share={top5_improvement:.4f}; "
        f"top5 missed-upside share={top5_missed:.4f}; concentration_risk={risk}."
    )
    columns = [
        "ticker", "current_d_rank", "event_count", "severe_loss_count",
        "avoided_severe_loss_count", "missed_large_winner_count",
        "net_contribution_5d", "net_contribution_10d",
        "share_of_total_improvement", "share_of_total_missed_upside",
        "concentration_bucket", "notes",
    ]
    return result[columns], risk


def event_type_audit(best: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    result = concentration_base(best, "event_type")
    result = result.sort_values("share_of_total_improvement", ascending=False).reset_index(drop=True)
    top_share = result["share_of_total_improvement"].max() if len(result) else 0
    top3 = result.head(3)["share_of_total_improvement"].sum()
    risk = bool(top_share > .50)
    buckets = []
    for _, row in result.iterrows():
        if row["event_count"] < 20:
            bucket = "TOO_FEW_EVENTS"
        elif row["net_contribution_5d"] < 0 and row["missed_large_winner_count"] > row["avoided_severe_loss_count"]:
            bucket = "MISSED_UPSIDE_DOMINATES"
        elif row["avoided_severe_loss_count"] == 0:
            bucket = "NO_EDGE"
        elif row["net_contribution_5d"] > 0:
            bucket = "PROMISING_SUBSET_DIAGNOSTIC_ONLY"
        else:
            bucket = "MIXED_SIGNAL"
        buckets.append(bucket)
    result["event_type_signal_bucket"] = buckets
    result["notes"] = (
        f"Largest event-type improvement share={top_share:.4f}; top3 share={top3:.4f}; "
        f"event_type_concentration_risk={risk}."
    )
    columns = [
        "event_type", "event_count", "severe_loss_count",
        "avoided_severe_loss_count", "missed_large_winner_count",
        "net_contribution_5d", "net_contribution_10d",
        "share_of_total_improvement", "share_of_total_missed_upside",
        "event_type_signal_bucket", "notes",
    ]
    return result[columns], risk


def placebo_forensic(robustness: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    placebo = robustness[robustness["check_name"].str.contains("placebo", case=False)].copy()
    rows = []
    for _, row in placebo.iterrows():
        passed = truth(row["beats_placebo"]) or str(row["check_status"]).upper() == "PASS"
        name = str(row["check_name"])
        if passed:
            interpretation = "PLACEBO_RESULT_INCONCLUSIVE"
        elif "ticker" in name:
            interpretation = "REAL_NOT_BETTER_THAN_RANDOM_TICKER_ASSIGNMENT"
        elif "event_type" in name:
            interpretation = "EDGE_EXPLAINED_BY_EVENT_TYPE_MIX"
        elif int(row.get("sample_size", 0)) < 30:
            interpretation = "SAMPLE_TOO_CONCENTRATED"
        else:
            interpretation = "EDGE_EXPLAINED_BY_TICKER_VOLATILITY"
        real = float(row["real_variant_left_tail_improvement"])
        placebo_score = float(row["left_tail_improvement"])
        rows.append({
            "placebo_type": name, "variant_id": row["variant_id"],
            "real_score": real, "placebo_score": placebo_score,
            "score_gap": real - placebo_score, "passed": passed,
            "failure_interpretation": interpretation, "research_only": True,
        })
    result = pd.DataFrame(rows)
    return result, bool((~result["passed"]).any()) if len(result) else False


def subset_diagnostics(
    best: pd.DataFrame,
    vulnerability: pd.DataFrame,
    robustness: pd.DataFrame,
    placebo_failed: bool,
) -> pd.DataFrame:
    vuln = vulnerability.set_index("ticker")
    sectors = vuln["sector_or_industry"].astype(str).to_dict()
    buckets = vuln["event_vulnerability_bucket"].astype(str).to_dict()
    text = best["event_type"].astype(str).str.lower()
    ticker_sector = best["ticker"].map(sectors).fillna("")
    definitions = {
        "earnings_occurrence_only": ("event_type contains earnings_occurrence", text.str.contains("earnings_occurrence")),
        "financing_only": ("event_type contains financing/offering/shelf", text.str.contains("financing|offering|shelf")),
        "ownership_event_only": ("event_type contains ownership/shareholder/proxy", text.str.contains("ownership|shareholder|proxy")),
        "8k_material_event_only": ("company material/other material/reg-fd events", text.str.contains("material_event|material_agreement|reg_fd")),
        "high_confidence_only": (
            "V21.100 high-confidence diagnostic proxy with usable 5D endpoint",
            best["baseline_return_5d"].notna(),
        ),
        "high_vulnerability_tickers_only": ("V21.097 ticker vulnerability bucket HIGH", best["ticker"].map(buckets).eq("HIGH")),
        "semiconductor_equipment_only": ("V21.097 sector_or_industry contains Semiconductor Equipment", ticker_sector.str.contains("Semiconductor Equipment", case=False)),
        "storage_semiconductor_only": ("V21.097 sector_or_industry contains Storage and Semiconductor", ticker_sector.str.contains("Storage", case=False) & ticker_sector.str.contains("Semiconductor", case=False)),
    }
    robust_map = {
        "earnings_occurrence_only": "earnings_only_subset",
        "financing_only": "financing_only_subset",
        "high_confidence_only": "high_confidence_only_subset",
    }
    rows = []
    for subset_id, (definition, mask) in definitions.items():
        group = best.loc[mask].copy()
        count = len(group)
        usable = int(group["baseline_return_5d"].notna().sum())
        severe_rate = float(group["baseline_return_5d"].le(-.10).mean()) if count else np.nan
        missed_rate = float(group["missed_large_winner_flag"].map(truth).mean()) if count else np.nan
        net = float((group["loss_reduction_5d"] - group["missed_upside_5d"]).mean()) if count else np.nan
        robust_name = robust_map.get(subset_id)
        matched = robustness[robustness["check_name"].eq(robust_name)] if robust_name else pd.DataFrame()
        placebo_status = str(matched.iloc[0]["check_status"]) if len(matched) else "NOT_AVAILABLE"
        if count < 20:
            recommendation = "NEED_MORE_DATA"
        elif pd.isna(net) or net <= 0:
            recommendation = "DO_NOT_USE"
        elif placebo_failed and placebo_status == "NOT_AVAILABLE":
            recommendation = "WATCH_FORWARD_ONLY"
        elif placebo_failed:
            recommendation = "REJECT_DUE_TO_PLACEBO"
        elif count < 100:
            recommendation = "NEED_MORE_DATA"
        else:
            recommendation = "PROMISING_BUT_NOT_ADOPTABLE"
        rows.append({
            "subset_id": subset_id, "subset_definition": definition,
            "event_count": count, "usable_event_count": usable,
            "severe_loss_rate": severe_rate, "missed_upside_rate": missed_rate,
            "net_research_score": net,
            "placebo_status_if_available": placebo_status,
            "subset_recommendation": recommendation, "research_only": True,
            "official_adoption_allowed": False,
        })
    return pd.DataFrame(rows)


def report(summary: dict[str, Any]) -> str:
    lines = ["# V21.100-R1 Event Weight Failure Decomposition", ""]
    lines.extend(f"- {key}: `{value}`" for key, value in summary.items())
    lines.extend([
        "",
        "The V21.100 severe-loss reduction remains a mechanical current-universe diagnostic, "
        "not evidence that event weights are effective. The decomposition does not create or "
        "apply new weights and does not authorize D integration.",
        "",
        "Historical pre-event random testing remains blocked. Any subset recommendation is "
        "forward-monitoring-only until PIT portfolio snapshots and independent forward evidence exist.",
    ])
    return "\n".join(lines) + "\n"


def run(root: Path) -> dict[str, Any]:
    out = root / OUT
    out.mkdir(parents=True, exist_ok=True)
    output_paths = {(out / name).resolve() for name in OUTPUTS}
    missing = [path.as_posix() for path in (*INPUTS, D_BASELINE) if not (root / path).is_file()]
    if missing:
        raise FileNotFoundError("Missing inputs: " + ", ".join(missing))
    input_hashes = {path.as_posix(): sha256(root / path) for path in INPUTS}
    prior_paths = sorted({
        path
        for prefix in ("v21_096*", "v21_097*", "v21_098*", "v21_099*", "v21_100*")
        for path in out.glob(prefix)
        if path.is_file() and path.resolve() not in output_paths
    })
    prior_hashes = {path.relative_to(root).as_posix(): sha256(path) for path in prior_paths}
    d_before = sha256(root / D_BASELINE)
    before = protected_snapshot(root, output_paths)

    backtest = pd.read_csv(root / BACKTEST, low_memory=False)
    variants = pd.read_csv(root / VARIANTS, low_memory=False)
    robustness = pd.read_csv(root / ROBUSTNESS, low_memory=False)
    summary_100 = json.loads((root / SUMMARY_100).read_text(encoding="utf-8"))
    impact = pd.read_csv(root / IMPACT, low_memory=False)
    vulnerability = pd.read_csv(root / VULNERABILITY, low_memory=False)
    dashboard = pd.read_csv(root / DASHBOARD, low_memory=False)
    best_id = str(summary_100.get("BEST_NET_SCORE_VARIANT", ""))
    checks = [
        ("v21_100_final_status_pass", summary_100.get("FINAL_STATUS") == "PASS", summary_100.get("FINAL_STATUS")),
        ("v21_100_expected_no_edge_decision", summary_100.get("DECISION") == "EVENT_WEIGHT_NO_LEFT_TAIL_EDGE_RESEARCH_ONLY", summary_100.get("DECISION")),
        ("best_diagnostic_variant_exists", best_id in set(variants["variant_id"]), best_id),
        ("placebo_checks_exist", robustness["check_name"].str.contains("placebo", case=False).any(), ""),
        ("historical_pre_event_random_backtest_blocked", summary_100.get("HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED") is False, ""),
        ("pit_leakage_warnings_zero", int(summary_100.get("PIT_LEAKAGE_WARNINGS", 1)) == 0, ""),
        ("supporting_diagnostics_loaded", len(impact) > 0 and len(vulnerability) > 0 and len(dashboard) > 0, ""),
        ("d_baseline_hash_available", bool(d_before), d_before),
    ]
    validation_rows = pd.DataFrame(checks, columns=["check_name", "passed", "detail"])
    validation = {
        "stage": "V21.100-R1_FAILURE_DECOMPOSITION_INPUT_VALIDATION",
        "status": "PASS" if validation_rows["passed"].all() else "FAIL",
        "input_v21_100_status": summary_100.get("FINAL_STATUS", "MISSING"),
        "input_v21_100_decision": summary_100.get("DECISION", "MISSING"),
        "best_diagnostic_variant": best_id,
        "historical_pre_event_random_backtest_allowed": False,
        "pit_leakage_warnings": int(summary_100.get("PIT_LEAKAGE_WARNINGS", 0)),
        "current_universe_diagnostic_only": True,
        "research_only": True, "official_adoption_allowed": False,
        "d_baseline_sha256_before": d_before,
    }
    validation_rows.to_csv(out / OUTPUTS[0], index=False)

    decomposition = missed_upside_decomposition(backtest)
    decomposition.to_csv(out / OUTPUTS[2], index=False)
    best = backtest[backtest["variant_id"].eq(best_id)].copy()
    ticker_result, ticker_concentration = ticker_audit(best, vulnerability)
    ticker_result.to_csv(out / OUTPUTS[3], index=False)
    event_result, event_concentration = event_type_audit(best)
    event_result.to_csv(out / OUTPUTS[4], index=False)
    placebo_result, placebo_failed = placebo_forensic(robustness)
    placebo_result.to_csv(out / OUTPUTS[5], index=False)
    subsets = subset_diagnostics(best, vulnerability, robustness, placebo_failed)
    subsets.to_csv(out / OUTPUTS[6], index=False)

    after = protected_snapshot(root, output_paths)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    d_after = sha256(root / D_BASELINE)
    d_preserved = d_after == d_before
    inputs_preserved = all(sha256(root / Path(path)) == digest for path, digest in input_hashes.items())
    prior_preserved = all(
        (root / relative).is_file() and sha256(root / relative) == digest
        for relative, digest in prior_hashes.items()
    )
    official_changed = [path for path in changed if "official" in path.lower() or "broker" in path.lower()]
    protected_modified = bool(changed or not d_preserved or not inputs_preserved or not prior_preserved)
    validation.update({
        "d_baseline_sha256_after": d_after, "d_baseline_preserved": d_preserved,
        "input_files_preserved": inputs_preserved,
        "v21_096_through_v21_100_artifacts_preserved": prior_preserved,
    })
    if protected_modified or official_changed:
        validation["status"] = "FAIL"
    write_json(out / OUTPUTS[1], validation)

    best_row = variants.set_index("variant_id").loc[best_id]
    missed_dominates = float(best_row["missed_upside_penalty"]) >= float(best_row["left_tail_improvement"])
    forward_recommendations = subsets["subset_recommendation"].isin(
        ["WATCH_FORWARD_ONLY", "PROMISING_BUT_NOT_ADOPTABLE"]
    )
    promising_count = int(forward_recommendations.sum())
    if placebo_failed:
        primary = "PLACEBO_WEAKNESS_RANDOM_TICKER_ASSIGNMENT"
    elif missed_dominates:
        primary = "MISSED_UPSIDE_DOMINATES"
    elif ticker_concentration:
        primary = "TICKER_CONCENTRATION"
    elif event_concentration:
        primary = "EVENT_TYPE_CONCENTRATION"
    else:
        primary = "CURRENT_UNIVERSE_BIAS_NO_PIT_PORTFOLIO_SEQUENCE"
    pit_warnings = int(validation["pit_leakage_warnings"])
    if pit_warnings:
        decision = "REJECT_FAILURE_DECOMPOSITION_DUE_TO_PIT_LEAKAGE"
    elif protected_modified or official_changed:
        decision = "REJECT_FAILURE_DECOMPOSITION_DUE_TO_PROTECTED_MUTATION"
    elif missed_dominates and placebo_failed:
        decision = "EVENT_WEIGHT_REJECTED_KEEP_FORWARD_MONITOR_ONLY"
    elif promising_count:
        decision = "NARROW_EVENT_SUBSETS_FORWARD_MONITOR_ONLY"
    else:
        decision = "EVENT_WEIGHT_RESEARCH_FREEZE_RECOMMENDED"
    summary = {
        "FINAL_STATUS": "PASS" if validation["status"] == "PASS" and not pit_warnings and not protected_modified else "FAIL",
        "DECISION": decision,
        "INPUT_V21_100_STATUS": summary_100.get("FINAL_STATUS", "MISSING"),
        "BEST_DIAGNOSTIC_VARIANT": best_id,
        "PRIMARY_FAILURE_REASON": primary,
        "MISSED_UPSIDE_DOMINATES": bool(missed_dominates),
        "TICKER_CONCENTRATION_DETECTED": bool(ticker_concentration),
        "EVENT_TYPE_CONCENTRATION_DETECTED": bool(event_concentration),
        "PLACEBO_FAILURE_CONFIRMED": bool(placebo_failed),
        "PROMISING_SUBSETS_FOUND": promising_count > 0,
        "PROMISING_SUBSETS_COUNT": promising_count,
        "FORWARD_ONLY_SUBSETS_RECOMMENDED": subsets.loc[forward_recommendations, "subset_id"].tolist(),
        "EVENT_WEIGHT_RESEARCH_ALLOWED": True,
        "EVENT_WEIGHT_D_INTEGRATION_ALLOWED": False,
        "HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED": False,
        "PIT_LEAKAGE_WARNINGS": pit_warnings,
        "PROTECTED_OUTPUTS_MODIFIED": protected_modified,
        "OFFICIAL_OUTPUTS_MODIFIED": bool(official_changed),
        "RESEARCH_ONLY": True, "OFFICIAL_ADOPTION_ALLOWED": False,
        "D_BASELINE_PRESERVED": d_preserved,
        "RECOMMENDED_NEXT_STAGE": "V21.101_NARROW_EVENT_SUBSET_FORWARD_MONITOR_OR_RESEARCH_FREEZE",
    }
    write_json(out / OUTPUTS[8], summary)
    (out / OUTPUTS[7]).write_text(report(summary), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    summary = run(args.root.resolve())
    for key, value in summary.items():
        print(f"{key}={value}")
    return 0 if summary["FINAL_STATUS"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
