"""Fail-closed executor for A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1.

The portfolio contract is frozen outside this runner. This program reconciles
the exact certified pre-2026 score, universe, and PIT-sector files. It creates
no economic portfolio when the only sector coverage is the already selected
Raw A2 Top20 because that would silently reintroduce a Top20 cutoff.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


TASK_ID = "A2_SECTOR_NEUTRAL_RELATIVE_VALUE_SLEEVE_R1"
CONTRACT_ID = "A2_SECTOR_NEUTRAL_CONTINUOUS_RANK_RV_V1"
STATUS = "PASS_UNTESTABLE_AUTHORITATIVE_DATA_GAP"
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK_ID
BASE = RESULTS / "A_VS_A2_QUARTERLY_13F_R1"
CONTRACT = OUT / "rv_contract.json"
FROZEN_BASELINE_MANIFEST = BASE / "audit" / "freeze_r1" / "frozen_baseline_manifest.json"
OOF = BASE / "A2" / "oof_predictions.parquet"
TOP20 = BASE / "A2" / "top20_selections.parquet"
ELIGIBLE = BASE / "universe" / "daily_eligible_universe_membership.parquet"
TAXONOMY = RESULTS / "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1" / "pit_ff12_ff48_taxonomy.parquet"

EXPECTED_SHA256 = {
    CONTRACT: "146af857798c21441b24a1106d32112878ffba43be289ac69098b9a4c070e9c8",
    FROZEN_BASELINE_MANIFEST: "398cff8076f8c761d87c12ce195ba98e9201209499caaaf7a14ae05ac1605125",
    OOF: "e336be6c267167356ce3d39fa629f80fe7b2968711112a9c976fdb002c693468",
    TOP20: "5e5203fdcd9a1e53fe1e2d64cd8c1adb78df4bd7acc733394d4dbd62392b8b20",
    ELIGIBLE: "c03cc35f3569cb968c3d48cefd08488c75c02389e5e430d11526a0284ad2b637",
    TAXONOMY: "515427bfe4d450540bcf8b04a9ce5fd50f706c551300a46450f5e4669b7d552f",
}

ECONOMIC_COLUMNS = [
    "scope", "year", "status", "observations", "cumulative_gross_return",
    "gross_annual_return", "net_annual_return", "annualized_volatility",
    "gross_sharpe", "net_sharpe", "maximum_drawdown", "downside_deviation",
    "expected_shortfall_5pct", "long_leg_contribution", "short_leg_contribution",
    "cost_drag", "spy_beta", "raw_a2_correlation",
]


class ContractFailure(RuntimeError):
    """A frozen identity or temporal contract is not satisfied."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractFailure(code)


def verify_frozen_inputs() -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path, expected in EXPECTED_SHA256.items():
        require(path.is_file(), f"MISSING_FROZEN_INPUT:{path}")
        observed = sha256_file(path)
        require(observed == expected, f"FROZEN_INPUT_HASH_MISMATCH:{path}")
        rows[str(path)] = {"expected_sha256": expected, "observed_sha256": observed, "status": "PASS"}
    return rows


def normalize_keys(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["signal_date"] = pd.to_datetime(result["signal_date"]).dt.normalize()
    result["ticker"] = result["ticker"].astype(str).str.strip().str.upper()
    return result


def sector_neutral_weights(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply the one frozen geometry to an already legal complete input frame."""
    required = {"ticker", "sector", "score"}
    require(required.issubset(frame.columns), "WEIGHT_INPUT_SCHEMA_MISSING")
    work = frame.dropna(subset=["ticker", "sector", "score"]).copy()
    require(not work.empty, "NO_LEGAL_WEIGHT_INPUT")
    require(not work.duplicated("ticker").any(), "DUPLICATE_TICKER_IN_WEIGHT_INPUT")
    work["p"] = work.groupby("sector", sort=False)["score"].rank(method="average", pct=True, ascending=True)
    work["signal"] = work["p"] - work.groupby("sector", sort=False)["p"].transform("mean")
    long_raw = float(work.loc[work.signal > 0, "signal"].sum())
    short_raw = float(-work.loc[work.signal < 0, "signal"].sum())
    require(long_raw > 0 and short_raw > 0, "NO_TWO_SIDED_LEGAL_TARGET")
    require(abs(long_raw - short_raw) <= 1e-12, "RAW_SIGNAL_NOT_DOLLAR_NEUTRAL")
    work["weight"] = work["signal"] / long_raw
    sector_net = work.groupby("sector", sort=False)["weight"].sum().abs().max()
    require(float(sector_net) <= 1e-12, "SECTOR_NET_EXPOSURE_NONZERO")
    require(abs(float(work.loc[work.weight > 0, "weight"].sum()) - 1.0) <= 1e-12, "LONG_GROSS_BAD")
    require(abs(float(-work.loc[work.weight < 0, "weight"].sum()) - 1.0) <= 1e-12, "SHORT_GROSS_BAD")
    return work.sort_values("ticker", kind="mergesort").reset_index(drop=True)


def reconcile_coverage() -> tuple[pd.DataFrame, dict[str, Any]]:
    # Projection intentionally excludes the pre-2026 realized target column.
    oof = normalize_keys(pd.read_parquet(OOF, columns=["signal_date", "ticker", "universe_size", "split", "a2_prediction", "a2_rank"]))
    eligible = normalize_keys(pd.read_parquet(ELIGIBLE, columns=["signal_date", "ticker"]))
    taxonomy = normalize_keys(pd.read_parquet(TAXONOMY, columns=["signal_date", "ticker", "execution_date", "information_cutoff_utc", "ff12", "taxonomy_status"]))
    top20 = normalize_keys(pd.read_parquet(TOP20, columns=["signal_date", "ticker", "a2_rank"]))

    for name, frame in {"OOF": oof, "ELIGIBLE": eligible, "TAXONOMY": taxonomy, "TOP20": top20}.items():
        require(not frame.duplicated(["signal_date", "ticker"]).any(), f"DUPLICATE_KEYS:{name}")
        require(frame.signal_date.max() <= pd.Timestamp("2025-12-31"), f"POST2025_DATE:{name}")

    eligible_keys = pd.MultiIndex.from_frame(eligible[["signal_date", "ticker"]])
    oof_keys = pd.MultiIndex.from_frame(oof[["signal_date", "ticker"]])
    require(oof_keys.isin(eligible_keys).all(), "OOF_NOT_SUBSET_OF_PIT_ELIGIBLE_UNIVERSE")

    joined = oof.merge(
        taxonomy[["signal_date", "ticker", "ff12", "taxonomy_status"]],
        on=["signal_date", "ticker"], how="left", validate="one_to_one",
    )
    joined["sector_row_present"] = joined.ff12.notna()
    joined["sector_available"] = joined.ff12.notna() & joined.taxonomy_status.eq("PIT_SEC_SIC_MAPPED")
    matched = joined.loc[joined.sector_available].copy()
    matched_keys = pd.MultiIndex.from_frame(matched[["signal_date", "ticker"]])
    physical_taxonomy_keys = pd.MultiIndex.from_frame(taxonomy[["signal_date", "ticker"]])
    top20_keys = pd.MultiIndex.from_frame(top20[["signal_date", "ticker"]])
    physical_taxonomy_equals_top20 = bool(
        len(physical_taxonomy_keys) == len(top20_keys)
        and physical_taxonomy_keys.isin(top20_keys).all()
        and top20_keys.isin(physical_taxonomy_keys).all()
    )
    valid_taxonomy_subset_top20 = bool(len(matched_keys) > 0 and matched_keys.isin(top20_keys).all())
    matched_gt20 = int((matched.a2_rank > 20).sum())
    matched_non_top20 = int((~matched_keys.isin(top20_keys)).sum())
    selection_conditioned = bool(valid_taxonomy_subset_top20 and matched_gt20 == 0 and matched_non_top20 == 0)
    taxonomy_cutoff = pd.to_datetime(taxonomy.information_cutoff_utc, utc=True)
    taxonomy_execution = pd.to_datetime(taxonomy.execution_date)
    cutoff_after_signal_date = int((taxonomy_cutoff.dt.date > taxonomy.signal_date.dt.date).sum())
    cutoff_after_execution_date = int((taxonomy_cutoff.dt.date > taxonomy_execution.dt.date).sum())
    cutoff_equal_signal_date = int((taxonomy_cutoff.dt.date == taxonomy.signal_date.dt.date).sum())

    coverage_rows: list[dict[str, Any]] = []
    for year in range(2020, 2026):
        part = joined.loc[joined.signal_date.dt.year == year]
        sector_rows = int(part.sector_available.sum())
        coverage_rows.append({
            "scope": str(year), "year": year,
            "score_sessions": int(part.signal_date.nunique()), "score_rows": int(len(part)),
            "pit_eligible_rows": int((eligible.signal_date.dt.year == year).sum()),
            "sector_matched_rows": sector_rows,
            "sector_coverage_ratio": float(sector_rows / len(part)) if len(part) else np.nan,
            "matched_rank_min": float(part.loc[part.sector_available, "a2_rank"].min()) if sector_rows else np.nan,
            "matched_rank_max": float(part.loc[part.sector_available, "a2_rank"].max()) if sector_rows else np.nan,
            "matched_rank_gt20_rows": int(((part.a2_rank > 20) & part.sector_available).sum()),
            "status": "UNTESTABLE_SELECTION_CONDITIONED_TAXONOMY" if len(part) else "NA_NO_RAW_A2_OOF_SCORE",
        })
    coverage_rows.append({
        "scope": "FULL_PRE2026", "year": np.nan,
        "score_sessions": int(joined.signal_date.nunique()), "score_rows": int(len(joined)),
        "pit_eligible_rows": int(len(eligible)), "sector_matched_rows": int(joined.sector_available.sum()),
        "sector_coverage_ratio": float(joined.sector_available.mean()),
        "matched_rank_min": float(matched.a2_rank.min()) if len(matched) else np.nan,
        "matched_rank_max": float(matched.a2_rank.max()) if len(matched) else np.nan,
        "matched_rank_gt20_rows": matched_gt20,
        "status": "UNTESTABLE_SELECTION_CONDITIONED_TAXONOMY" if selection_conditioned else "REVIEW_REQUIRED",
    })
    audit = {
        "task_id": TASK_ID,
        "status": STATUS if selection_conditioned else "REVIEW_REQUIRED",
        "raw_a2_score_rows": int(len(oof)),
        "raw_a2_score_sessions": int(oof.signal_date.nunique()),
        "raw_a2_score_min_date": oof.signal_date.min().date().isoformat(),
        "raw_a2_score_max_date": oof.signal_date.max().date().isoformat(),
        "pit_eligible_rows": int(len(eligible)), "taxonomy_rows": int(len(taxonomy)),
        "sector_matched_rows": int(joined.sector_available.sum()),
        "sector_coverage_ratio": float(joined.sector_available.mean()),
        "matched_rank_min": int(matched.a2_rank.min()) if len(matched) else None,
        "matched_rank_max": int(matched.a2_rank.max()) if len(matched) else None,
        "matched_rank_gt20_rows": matched_gt20,
        "matched_non_top20_rows": matched_non_top20,
        "physical_taxonomy_keyset_equals_raw_a2_top20": physical_taxonomy_equals_top20,
        "valid_taxonomy_keyset_subset_of_raw_a2_top20": valid_taxonomy_subset_top20,
        "selection_conditioned_taxonomy": selection_conditioned,
        "taxonomy_status_counts": {str(key): int(value) for key, value in taxonomy.taxonomy_status.value_counts(dropna=False).items()},
        "taxonomy_cutoff_after_signal_date_rows": cutoff_after_signal_date,
        "taxonomy_cutoff_after_execution_date_rows": cutoff_after_execution_date,
        "taxonomy_cutoff_equal_signal_date_rows": cutoff_equal_signal_date,
        "pit_taxonomy_timing_status": "PASS_DAY_LEVEL_WITH_INTRADAY_UNRESOLVED" if cutoff_after_signal_date == 0 and cutoff_after_execution_date == 0 else "FAIL",
        "portfolio_constructed": False, "economic_data_opened": False,
        "blocking_reason": (
            "The certified PIT taxonomy physical keyset is exactly the existing Raw A2 Top20, "
            "and every valid mapped sector row is a subset of that Top20. "
            "Using them would silently impose the prohibited Top20 cutoff and would not test "
            "the frozen continuous eligible-universe geometry."
        ),
        "component_evidence_status": "UNTESTABLE_MISSING_AUTHORITATIVE_EVIDENCE",
        "required_remediation": (
            "A separately frozen, PIT-certified sector surface covering the Raw A2 scored eligible universe; "
            "no backfill from current classifications is permitted."
        ),
    }
    return pd.DataFrame(coverage_rows), audit


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    frame.to_csv(path, index=False, na_rep="NA", lineterminator="\n")


def empty_daily_sleeve() -> pd.DataFrame:
    return pd.DataFrame({
        "execution_date": pd.Series(dtype="datetime64[ns]"),
        "gross_return": pd.Series(dtype="float64"),
        "transaction_cost_return": pd.Series(dtype="float64"),
        "net_return": pd.Series(dtype="float64"),
        "turnover": pd.Series(dtype="float64"),
        "long_turnover": pd.Series(dtype="float64"),
        "short_turnover": pd.Series(dtype="float64"),
        "traded_notional": pd.Series(dtype="float64"),
        "long_gross": pd.Series(dtype="float64"),
        "short_gross": pd.Series(dtype="float64"),
        "net_exposure": pd.Series(dtype="float64"),
        "long_name_count": pd.Series(dtype="int64"),
        "short_name_count": pd.Series(dtype="int64"),
        "status": pd.Series(dtype="string"),
    })


def na_economic_rows() -> pd.DataFrame:
    rows = [{"scope": str(year), "year": year, "status": "NA_AUTHORITATIVE_DATA_GAP", "observations": 0} for year in range(2020, 2026)]
    rows.append({"scope": "FULL_PRE2026", "year": np.nan, "status": "NA_AUTHORITATIVE_DATA_GAP", "observations": 0})
    return pd.DataFrame(rows).reindex(columns=ECONOMIC_COLUMNS)


def write_fail_closed_outputs(coverage: pd.DataFrame, audit: dict[str, Any], hashes: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / "coverage_report.csv", coverage)
    empty_daily_sleeve().to_parquet(OUT / "daily_sleeve_returns.parquet", index=False)
    write_csv(OUT / "annual_economics.csv", na_economic_rows())
    write_csv(OUT / "cost_turnover_report.csv", pd.DataFrame([{
        "scope": "FULL_PRE2026", "status": "NA_AUTHORITATIVE_DATA_GAP", "canonical_cost_bps": 10.0,
        "turnover": np.nan, "long_turnover": np.nan, "short_turnover": np.nan,
        "traded_notional": np.nan, "cost_drag": np.nan,
    }]))
    write_csv(OUT / "factor_exposure_report.csv", pd.DataFrame([
        {"scope": "FULL_PRE2026", "factor": factor, "exposure": np.nan, "status": "NA_AUTHORITATIVE_DATA_GAP"}
        for factor in ["SPY_BETA", "QQQ_BETA", "SOXX_BETA", "SAFE_AUTHORITATIVE_FACTOR_STACK"]
    ]))
    write_csv(OUT / "sector_neutrality_report.csv", pd.DataFrame([
        {"metric": "sector_coverage_ratio", "value": audit["sector_coverage_ratio"], "status": "FAIL_SELECTION_CONDITIONED_TAXONOMY"},
        {"metric": "matched_rank_max", "value": audit["matched_rank_max"], "status": "FAIL_SELECTION_CONDITIONED_TAXONOMY"},
        {"metric": "matched_rank_gt20_rows", "value": audit["matched_rank_gt20_rows"], "status": "FAIL_SELECTION_CONDITIONED_TAXONOMY"},
        {"metric": "sector_gross_exposure", "value": np.nan, "status": "NA_PORTFOLIO_NOT_CONSTRUCTED"},
        {"metric": "max_abs_sector_net_exposure", "value": np.nan, "status": "NA_PORTFOLIO_NOT_CONSTRUCTED"},
        {"metric": "total_long_gross", "value": np.nan, "status": "NA_PORTFOLIO_NOT_CONSTRUCTED"},
        {"metric": "total_short_gross", "value": np.nan, "status": "NA_PORTFOLIO_NOT_CONSTRUCTED"},
        {"metric": "total_net", "value": np.nan, "status": "NA_PORTFOLIO_NOT_CONSTRUCTED"},
    ]))
    write_csv(OUT / "orthogonality_report.csv", pd.DataFrame([
        {"scope": "FULL_PRE2026", "metric": metric, "value": np.nan, "status": "NA_AUTHORITATIVE_DATA_GAP"}
        for metric in ["RAW_A2_DAILY_CORRELATION", "RAW_A2_MONTHLY_CORRELATION", "DRAWDOWN_OVERLAP", "UP_MARKET_CORRELATION", "DOWN_MARKET_CORRELATION", "RESIDUAL_CORRELATION_AFTER_SPY", "RESIDUAL_CORRELATION_AFTER_SPY_QQQ"]
    ]))
    write_csv(OUT / "contribution_concentration_report.csv", pd.DataFrame([
        {"scope": "FULL_PRE2026", "metric": metric, "value": np.nan, "status": "NA_AUTHORITATIVE_DATA_GAP"}
        for metric in ["LONG_NAME_COUNT", "SHORT_NAME_COUNT", "EFFECTIVE_N", "HERFINDAHL", "SECTOR_BREADTH", "TOP5_DATE_CONTRIBUTION", "TOP10_DATE_CONTRIBUTION", "TOP10_TICKER_CONTRIBUTION"]
    ]))

    write_json(OUT / "statistical_validation.json", {
        "schema_version": "1.0.0", "task_id": TASK_ID,
        "status": "UNTESTABLE_AUTHORITATIVE_DATA_GAP",
        "primary_hypothesis_count": 1, "portfolio_spec_count": 1, "portfolio_spec_search_count": 0,
        "observations": 0, "mean_daily_return": None, "standard_error": None,
        "hac_lags": 5, "hac_t_stat": None, "confidence_interval_95": [None, None],
        "skew": None, "excess_kurtosis": None, "effective_observations": None,
        "reason": audit["blocking_reason"],
    })
    write_json(OUT / "authority_reconciliation.json", {
        "schema_version": "1.0.0", "task_id": TASK_ID,
        "status": "PASS_IDENTITY_UNTESTABLE_INPUT_COVERAGE",
        "raw_a2_entity_id": "RAW_A2_HGB_BASELINE",
        "raw_a2_specification_fingerprint": "0abead89334ad578eff4683f0a3d1878e7e6c6b1daf157298ca0e7322f9ebfcb",
        "frozen_baseline_manifest_sha256": EXPECTED_SHA256[FROZEN_BASELINE_MANIFEST],
        "raw_a2_oof_sha256": EXPECTED_SHA256[OOF],
        "pit_sector_taxonomy_sha256": EXPECTED_SHA256[TAXONOMY],
        "frozen_input_hash_validation": hashes, "coverage_audit": audit,
        "top40_substitution_used": False, "unknown_taxonomy_source_open_count": 0,
    })
    write_json(OUT / "execution_counters.json", {
        "post_2025_realized_label_metric_read_count": 0,
        "post_2025_model_evaluation_metric_read_count": 0,
        "post_2025_outcome_derived_metadata_read_count": 0,
        "post_2025_return_read_count": 0, "post_2025_nav_read_count": 0,
        "post_2025_pnl_read_count": 0, "post_2025_ic_read_count": 0,
        "post_2025_auroc_read_count": 0, "2026_economic_outcome_read_count": 0,
        "holdout_peek_count": 0, "mixed_source_content_open_count": 0,
        "new_feature_count": 0, "modified_feature_count": 0,
        "new_predictive_target_count": 0, "new_predictive_model_spec_count": 0,
        "new_predictive_model_fit_count": 0, "new_hyperparameter_trial_count": 0,
        "portfolio_spec_count": 1, "portfolio_spec_search_count": 0,
        "new_threshold_search_count": 0, "new_topk_search_count": 0,
        "new_rebalance_search_count": 0, "new_holding_period_search_count": 0,
        "new_cost_grid_count": 0, "new_blend_weight_search_count": 0,
        "new_component_subset_search_count": 0, "new_optimizer_search_count": 0,
        "closed_branch_reopen_count": 0, "new_dependency_count": 0,
        "harness_modification_count": 0,
    })
    (OUT / "implementability_report.md").write_text(
        "# Implementability audit\n\n"
        f"TASK={TASK_ID}\nSTATUS={STATUS}\nPORTFOLIO_CONSTRUCTED=FALSE\n"
        "BORROW_IMPLEMENTABILITY_STATUS=UNPROVEN\n"
        "IMPLEMENTABILITY_LIMITATION=NO_AUTHORITATIVE_BORROW_SHORT_AVAILABILITY_DATA\n\n"
        "The fixed sleeve cannot be constructed from the certified inputs. The physical PIT FF12 keyset is exactly the existing Raw A2 Top20, and all valid mapped rows are a subset of it. Using that surface would silently turn the no-cutoff eligible-universe contract into a Top20 long/short sizing branch.\n\n"
        "Turnover, traded notional, ADV participation, liquidity, price-level, microcap, crowding, concentration, leverage-path, and rebalancing-intensity results are NA, not zero. No borrow cost or short availability was invented, and no live-tradability claim is made.\n",
        encoding="utf-8",
    )


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    hashes = verify_frozen_inputs()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    require(contract["contract_id"] == CONTRACT_ID, "CONTRACT_ID_MISMATCH")
    require(contract["contract_status"] == "FROZEN_OUTCOME_BLIND", "CONTRACT_NOT_FROZEN")
    coverage, audit = reconcile_coverage()
    require(audit["selection_conditioned_taxonomy"], "EXPECTED_FAIL_CLOSED_DATA_GAP_NOT_ESTABLISHED")
    write_fail_closed_outputs(coverage, audit, hashes)
    summary = {
        "task": TASK_ID, "status": STATUS,
        "rv_contract_sha256": EXPECTED_SHA256[CONTRACT],
        "legal_pre2026_sessions": audit["raw_a2_score_sessions"],
        "constructible_sleeve_sessions": 0,
        "raw_a2_score_sessions": audit["raw_a2_score_sessions"],
        "coverage": 0.0,
        "raw_sector_match_ratio": audit["sector_coverage_ratio"],
        "annual_evaluable_years": 0,
        "positive_years": None, "portfolio_constructed": False,
        "borrow_implementability_status": "UNPROVEN", "reason": audit["blocking_reason"],
    }
    write_json(OUT / "run_summary.json", summary)
    for key, value in summary.items():
        print(f"{key.upper()}={value}")
    return summary


if __name__ == "__main__":
    run()
