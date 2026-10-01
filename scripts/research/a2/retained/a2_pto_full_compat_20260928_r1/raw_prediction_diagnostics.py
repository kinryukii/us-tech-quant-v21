"""Score every original typed prediction object after freeze; never learn.

Prices at both next-open endpoints must be positive, finite, and quality-valid.
2025 additionally retains the original pre-2026 maturity/availability contract.
2026 remains a qualified-context, previously observed diagnostic window.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from common import ROOT, MEMBERS, POINT, CLASSIFIERS, QUANTILES, DISTRIBUTIONS, RANKERS, FEATURES, sha, pd, np
from freeze_all import verify_freeze
from scipy.special import ndtr
from scipy.stats import norm

KEY = ["signal_date", "ticker"]
OUT = ROOT / "analysis"
SOURCES = {}
OUTPUT_COLUMNS = ["mu", "p_up", "q10", "q50", "q90", "sigma", "rank_score"]


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def bound_parquet(relative):
    path = ROOT / relative
    SOURCES[relative] = sha(path)
    return pd.read_parquet(path)


def read_json(relative):
    path = ROOT / relative
    SOURCES[relative] = sha(path)
    return json.loads(path.read_text(encoding="utf-8"))


def indexed_values(matrix, day_index, ticker_index, offset, default=np.nan):
    values = np.full(len(day_index), default, dtype=float)
    valid = (day_index >= 0) & (ticker_index >= 0) & (day_index+offset < len(matrix))
    if valid.any():
        values[valid] = matrix.to_numpy()[day_index[valid]+offset, ticker_index[valid]]
    return values


def actual_labels(context, prices, calendar, year, exclude_source_extreme_warning=True):
    """Default preserves the original conservative diagnostic support.

    The source label_price_warning is an extreme-return hint, not proof of bad
    prices. Inclusive diagnostics disable this optional exclusion explicitly.
    """
    context = context.copy()
    context["signal_date"] = pd.to_datetime(context.signal_date)
    prices = prices.copy()
    prices["trade_date"] = pd.to_datetime(prices.trade_date)
    days = pd.DatetimeIndex(pd.to_datetime(calendar.trade_date)).sort_values()
    require(not days.duplicated().any(), "DUPLICATE_LABEL_CALENDAR")
    require(not context.duplicated(KEY).any() and not prices.duplicated(["trade_date", "ticker"]).any(), "DUPLICATE_LABEL_SOURCE_KEYS")
    opened = prices.pivot(index="trade_date", columns="ticker", values="open").reindex(days)
    positions = days.get_indexer(context.signal_date)
    ticker_positions = opened.columns.get_indexer(context.ticker)
    nopen = indexed_values(opened, positions, ticker_positions, 1)
    fopen = indexed_values(opened, positions, ticker_positions, 2)
    numeric = np.isfinite(nopen) & np.isfinite(fopen) & (nopen > 0.) & (fopen > 0.)
    maturity = (positions >= 0) & (positions+2 < len(days))
    end = np.full(len(context), np.datetime64("NaT"), dtype="datetime64[ns]")
    execution = end.copy()
    end[maturity] = days.to_numpy()[positions[maturity]+2]
    execution[maturity] = days.to_numpy()[positions[maturity]+1]
    maturity &= (execution > context.signal_date.to_numpy()) & (end > execution)
    quality = np.ones(len(context), dtype=bool)
    quality_column_available = "price_quality_warning" in prices
    if quality_column_available:
        warning = prices.assign(_warning=prices.price_quality_warning.fillna(True).astype(bool)).pivot(index="trade_date", columns="ticker", values="_warning")
        warning = warning.reindex(index=days, columns=opened.columns).fillna(True)
        quality &= indexed_values(warning, positions, ticker_positions, 1, default=1.) == 0.
        quality &= indexed_values(warning, positions, ticker_positions, 2, default=1.) == 0.
    source_available = np.ones(len(context), dtype=bool)
    extreme_hint = np.zeros(len(context), dtype=bool)
    optional_warning_mask = np.zeros(len(context), dtype=bool)
    if year == 2025:
        source_available &= context.label_available.fillna(False).to_numpy(bool)
        if "label_price_warning" in context:
            extreme_hint = context.label_price_warning.fillna(False).to_numpy(bool)
            optional_warning_mask = context.label_price_warning.fillna(True).to_numpy(bool)
        source_end = pd.to_datetime(context.label_end_date).to_numpy()
        source_available &= (source_end > context.signal_date.to_numpy()) & (source_end < np.datetime64("2026-01-01"))
        source_available &= np.isfinite(context.y_next_open.to_numpy(float))
        require(pd.Series(days).lt("2026-01-01").all(), "2025_LABEL_SOURCE_READS_2026")
    before_optional_hint = maturity & numeric & quality & source_available
    excluded_hint_rows = int((before_optional_hint & optional_warning_mask).sum()) if exclude_source_extreme_warning else 0
    if exclude_source_extreme_warning:
        source_available &= ~optional_warning_mask
    labels = np.divide(fopen, nopen, out=np.full(len(context), np.nan), where=numeric)-1.
    if year == 2025:
        check = maturity & numeric & quality & source_available
        np.testing.assert_allclose(labels[check], context.loc[check, "y_next_open"].to_numpy(float), rtol=1e-10, atol=1e-12)
    available = maturity & numeric & quality & source_available & np.isfinite(labels)
    status = np.repeat("VALID_MATURE_TARGET", len(context)).astype(object)
    status[~source_available] = "EXCLUDED_PRE_SOURCE_LABEL_CONTRACT"
    status[~numeric] = "EXCLUDED_NONPOSITIVE_OR_NONFINITE_ENDPOINT_OPEN"
    status[~quality] = "EXCLUDED_ENDPOINT_PRICE_QUALITY"
    status[~maturity] = "EXCLUDED_UNMATURE_OR_INVALID_LABEL_CLOCK"
    result = context[KEY].copy()
    result["y_next_open"] = labels
    result["execution_date"] = execution
    result["label_end_date"] = end
    result["label_available"] = available
    result["raw_label_status"] = status
    counts = {str(key): int(value) for key, value in pd.Series(status).value_counts().items()}
    return result, {"label_status_counts": counts, "quality_column_available": quality_column_available,
                    "mature_clock_rows": int(maturity.sum()), "positive_finite_endpoint_rows": int(numeric.sum()),
                    "quality_valid_endpoint_rows": int(quality.sum()), "source_contract_rows": int(source_available.sum()),
                    "source_extreme_hint_rows": int(extreme_hint.sum()), "source_extreme_hint_legal_rows_before_optional_exclusion": int((before_optional_hint & extreme_hint).sum()),
                    "source_extreme_hint_rows_excluded": excluded_hint_rows, "source_extreme_hint_is_proven_bad_price": False,
                    "exclude_source_extreme_warning": bool(exclude_source_extreme_warning)}


def pinball(target, prediction, quantile):
    residual = target-prediction
    return float(np.mean(np.maximum(quantile*residual, (quantile-1.)*residual))) if len(residual) else np.nan


def normal_diagnostics(target, mean, scale, prefix):
    if not len(target):
        return {prefix + "finite_normal_score_rows": 0}
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        standardized = (target-mean)/scale
        nll = .5*np.log(2*np.pi)+np.log(scale)+.5*standardized**2
    finite_nll = np.isfinite(nll)
    pit = ndtr(standardized)
    output = {prefix + "finite_normal_score_rows": int(finite_nll.sum()), prefix + "nonfinite_normal_score_rows": int((~finite_nll).sum()),
              prefix + "normal_nll": float(np.mean(nll[finite_nll])) if finite_nll.any() else np.nan,
              prefix + "pit_mean": float(np.mean(pit)), prefix + "pit_std": float(np.std(pit)),
              prefix + "pit_q10": float(np.quantile(pit, .1)), prefix + "pit_q50": float(np.quantile(pit, .5)), prefix + "pit_q90": float(np.quantile(pit, .9)),
              prefix + "pit_below_05_fraction": float(np.mean(pit < .05)), prefix + "pit_above_95_fraction": float(np.mean(pit > .95))}
    histogram, _ = np.histogram(pit, bins=np.linspace(0., 1., 11))
    for i, count in enumerate(histogram):
        output[prefix + f"pit_bin_{i:02d}_fraction"] = float(count/len(pit))
    for coverage in [.5, .8, .95]:
        critical = norm.ppf((1.+coverage)/2.)
        output[prefix + f"normal_central_{int(coverage*100)}_coverage"] = float(np.mean(np.abs(standardized) <= critical))
    return output


def raw_interface(member):
    if member in CLASSIFIERS:
        return "event_probability_and_train_amplitude", ["p_up", "mu"]
    if member in QUANTILES:
        return "conditional_quantile_knots", ["q10", "q50", "q90"]
    if member in DISTRIBUTIONS:
        return "conditional_normal_distribution", ["mu", "sigma"]
    if member in RANKERS:
        return "within_signal_ranking_score", ["rank_score"]
    return "robust_return_location" if member == "huber" else "point_return", ["mu"]


def main(exclude_source_extreme_warning=True, output_suffix=""):
    require(output_suffix in ["", "_INCLUSIVE_EXTREME_HINTS"], "UNREGISTERED_RAW_DIAGNOSTIC_OUTPUT_SCOPE")
    freeze = verify_freeze()
    freeze_hash = sha(ROOT / "FREEZE.json")
    stamp = datetime.now(timezone.utc).isoformat()
    inference = read_json("predictions/base/final/INFERENCE_RECEIPT.json")
    require(inference["completed_members"] == 31 and not inference["failures"], "FINAL_RAW_PREDICTIONS_INCOMPLETE")
    base_verify = read_json("models/base/VERIFICATION.json")
    final_verify = read_json("predictions/base/final/VERIFICATION.json")
    native_dtypes = {(2025, row["member"]): row["native_dtype"] for row in base_verify["probability_amplitude_roundoff"] if row["stage"] == "validation"}
    native_dtypes.update({(2026, row["member"]): row["probability_native_dtype"] for row in final_verify["member_diagnostics"] if row["member"] in CLASSIFIERS})
    records, daily = [], []
    for year, stage, prefix in [(2025, "validation", "pre"), (2026, "final", "test")]:
        context = bound_parquet("data/pre.parquet" if year == 2025 else "data/test.parquet")
        context = context.loc[pd.to_datetime(context.signal_date).dt.year.eq(year)].reset_index(drop=True)
        prices = bound_parquet(f"data/{prefix}_prices.parquet")
        calendar = bound_parquet(f"data/{prefix}_calendar.parquet")
        actual, label_info = actual_labels(context, prices, calendar, year, exclude_source_extreme_warning=exclude_source_extreme_warning)
        for member in MEMBERS:
            relative = f"predictions/base/{stage}/{member}.parquet"
            raw = bound_parquet(relative)
            require(not raw.duplicated(KEY).any(), "DUPLICATED_RAW_PREDICTION_KEYS")
            pd.testing.assert_frame_equal(raw[KEY], context[KEY], check_dtype=False)
            object_name, relevant = raw_interface(member)
            joined = raw.merge(actual, on=KEY, how="left", validate="one_to_one")
            finite_prediction = np.isfinite(joined[relevant].to_numpy(float)).all(axis=1)
            if member in DISTRIBUTIONS:
                finite_prediction &= joined.sigma.gt(0.).to_numpy()
            if member in CLASSIFIERS:
                finite_prediction &= joined.p_up.between(0., 1.).to_numpy()
            finite_label = joined.label_available & np.isfinite(joined.y_next_open)
            valid = finite_label & finite_prediction
            evaluated = joined.loc[valid]
            y = evaluated.y_next_open.to_numpy(float)
            clipped = np.clip(y, -.2, .2)
            training_receipt = read_json(f"models/base/{member}/{stage}_RECEIPT.json")
            record = {"year": year, "stage": stage, "member": member, "raw_object": object_name, "status": "RAW_TYPED_OBJECT_DIAGNOSTIC",
                "evaluation_scope": "PRE2026_AVAILABLE_CONTEXT_DIAGNOSTIC" if year == 2025 else "OBSERVED_HISTORY_QUALIFIED_SUBPOOL_DIAGNOSTIC",
                "formal_full_pool_status": "BLOCKED_DATA", "previous_2026_exposure_preserved": True,
                "prediction_rows": len(raw), "mature_clock_rows": label_info["mature_clock_rows"], "finite_legal_label_rows": int(finite_label.sum()),
                "finite_typed_prediction_rows": int(finite_prediction.sum()), "evaluated_rows": len(evaluated),
                "excluded_label_rows": int((~finite_label).sum()), "excluded_prediction_rows_with_legal_labels": int((finite_label & ~finite_prediction).sum()),
                "extreme_raw_label_rows": int(np.sum(np.abs(y) > .2)),
                "label_status_counts": json.dumps(label_info["label_status_counts"], sort_keys=True),
                "endpoint_price_quality_column_available": label_info["quality_column_available"], "positive_finite_endpoint_rows": label_info["positive_finite_endpoint_rows"],
                "source_extreme_hint_rows": label_info["source_extreme_hint_rows"],
                "source_extreme_hint_legal_rows_before_optional_exclusion": label_info["source_extreme_hint_legal_rows_before_optional_exclusion"],
                "source_extreme_hint_rows_excluded": label_info["source_extreme_hint_rows_excluded"],
                "source_extreme_hint_is_proven_bad_price": False,
                "diagnostic_warning_scope": "EXCLUDES_SOURCE_EXTREME_RETURN_HINTS" if exclude_source_extreme_warning else "INCLUDES_SOURCE_EXTREME_RETURN_HINTS",
                "signal_first": str(raw.signal_date.min()), "signal_last": str(raw.signal_date.max()),
                "label_end_max": str(evaluated.label_end_date.max()) if len(evaluated) else None,
                "train_cutoff_exclusive": training_receipt["cutoff_exclusive"], "train_label_end_max": training_receipt["train_label_end_max"],
                "raw_prediction_sha256": SOURCES[relative], "raw_prediction_path": relative,
                "freeze_receipt_sha256": freeze_hash, "producer_sha256": sha(Path(__file__)), "created_utc": stamp,
                "fit_calls": 0, "learning_update_calls": 0, "selection_or_tuning_calls": 0,
                "iid_test_or_pvalue": False, "labels_cost_adjusted": False, "gross_price_index_not_shareholder_total_return": True}
            if member in POINT or member in DISTRIBUTIONS or member in CLASSIFIERS:
                mean = evaluated.mu.to_numpy(float)
                record["raw_location_rmse_unclipped"] = float(np.sqrt(np.mean((mean-y)**2))) if len(y) else np.nan
                record["raw_location_rmse_clipped_target"] = float(np.sqrt(np.mean((mean-clipped)**2))) if len(y) else np.nan
                record["location_is_precise_unclipped_expected_return"] = False
            if member in CLASSIFIERS:
                probability = evaluated.p_up.to_numpy(float)
                record["brier_native_event_probability"] = float(np.mean((probability-(y > 0.))**2)) if len(y) else np.nan
                record["native_probability_dtype"] = native_dtypes[(year, member)]
                record["probability_has_new_eval_calibration"] = False
                record["probability_event"] = "y_next_open > 0"
                record["amplitude_source"] = "TRAINING_CUTOFF_ONLY_CLIPPED_TARGET"
            if member in QUANTILES:
                q = evaluated[["q10", "q50", "q90"]].to_numpy(float)
                sorted_q = np.sort(q, axis=1)
                all_q = raw[["q10", "q50", "q90"]].to_numpy(float)
                all_finite = np.isfinite(all_q).all(axis=1)
                crossing_all = (all_q[all_finite, 0] > all_q[all_finite, 1]) | (all_q[all_finite, 1] > all_q[all_finite, 2])
                crossing = (q[:, 0] > q[:, 1]) | (q[:, 1] > q[:, 2])
                record["raw_crossing_prediction_rows"] = int(crossing_all.sum())
                record["raw_crossing_evaluated_rows"] = int(crossing.sum())
                record["fixed_sorted_crossing_evaluated_rows"] = 0
                record["fixed_sort_is_readonly_diagnostic"] = True
                record["quantile_median_is_called_mean"] = False
                for variant, knots in [("raw", q), ("fixed_sorted", sorted_q)]:
                    for index, quantile in enumerate([.1, .5, .9]):
                        knot = f"q{int(100*quantile)}"
                        record[f"{variant}_{knot}_pinball_unclipped"] = pinball(y, knots[:, index], quantile)
                        record[f"{variant}_{knot}_pinball_clipped_target"] = pinball(clipped, knots[:, index], quantile)
                        record[f"{variant}_{knot}_coverage_unclipped"] = float(np.mean(y <= knots[:, index])) if len(y) else np.nan
                        record[f"{variant}_{knot}_coverage_clipped_target"] = float(np.mean(clipped <= knots[:, index])) if len(y) else np.nan
                    record[f"{variant}_q10_q90_coverage_unclipped"] = float(np.mean((y >= knots[:, 0]) & (y <= knots[:, 2]))) if len(y) else np.nan
                    record[f"{variant}_q10_q90_coverage_clipped_target"] = float(np.mean((clipped >= knots[:, 0]) & (clipped <= knots[:, 2]))) if len(y) else np.nan
            if member in DISTRIBUTIONS:
                mean, scale = evaluated.mu.to_numpy(float), evaluated.sigma.to_numpy(float)
                record.update(normal_diagnostics(y, mean, scale, "raw_label_"))
                record.update(normal_diagnostics(clipped, mean, scale, "clipped_target_"))
                record["normal_sigma_min"] = float(np.min(scale)) if len(scale) else np.nan
                record["normal_sigma_max"] = float(np.max(scale)) if len(scale) else np.nan
                record["normal_object_not_recalibrated_here"] = True
            if member in RANKERS:
                member_days = []
                for signal_date in pd.to_datetime(raw.signal_date).drop_duplicates():
                    group = evaluated.loc[evaluated.signal_date.eq(signal_date)]
                    usable = len(group) >= 2 and group.rank_score.nunique() > 1 and group.y_next_open.nunique() > 1
                    daily_record = {"year": year, "member": member, "signal_date": signal_date, "rows": len(group),
                        "raw_rank_score_ic": float(group.rank_score.corr(group.y_next_open, method="spearman")) if usable else np.nan,
                        "raw_rank_score_ic_clipped_target": float(group.rank_score.corr(group.y_next_open.clip(-.2, .2), method="spearman")) if usable else np.nan,
                        "status": "DESCRIPTIVE_DAILY_IC" if usable else "INSUFFICIENT_LABELS_OR_CONSTANT_INPUT",
                        "raw_rank_not_renamed_return": True, "evaluation_scope": record["evaluation_scope"], "iid_test_or_pvalue": False}
                    member_days.append(daily_record)
                scores = np.array([day["raw_rank_score_ic"] for day in member_days], dtype=float)
                finite_scores = scores[np.isfinite(scores)]
                record["raw_rank_score_daily_ic_mean"] = float(np.mean(finite_scores)) if len(finite_scores) else np.nan
                record["raw_rank_score_daily_ic_median"] = float(np.median(finite_scores)) if len(finite_scores) else np.nan
                record["raw_rank_score_daily_ic_positive_fraction"] = float(np.mean(finite_scores > 0.)) if len(finite_scores) else np.nan
                record["raw_rank_score_daily_ic_finite_days"] = len(finite_scores)
                record["raw_rank_score_daily_ic_total_days"] = len(member_days)
                daily.extend(member_days)
            records.append(record)
    require(len(records) == len(MEMBERS)*2 == 62, "RAW_DIAGNOSTIC_MEMBER_COVERAGE_INCOMPLETE")
    require(verify_freeze() == freeze and sha(ROOT / "FREEZE.json") == freeze_hash, "FROZEN_ARTIFACT_MUTATION")
    for relative, digest in SOURCES.items():
        require(sha(ROOT / relative) == digest, "RAW_DIAGNOSTIC_SOURCE_MUTATION:" + relative)
    for record in records:
        record["freeze_hashes_verified_before"] = record["freeze_hashes_verified_after"] = len(freeze["artifact_sha256"])
        record["source_sha256"] = json.dumps(SOURCES, sort_keys=True)
    OUT.mkdir(exist_ok=True)
    paths = [OUT / f"RAW_PREDICTION_DIAGNOSTICS{output_suffix}.csv", OUT / f"RAW_RANK_DAILY_IC{output_suffix}.csv"]
    require(not any(path.exists() for path in paths), "REFUSE_OVERWRITE_RAW_DIAGNOSTICS")
    pd.DataFrame(records).to_csv(paths[0], index=False, encoding="utf-8-sig")
    pd.DataFrame(daily).to_csv(paths[1], index=False, encoding="utf-8-sig")
    print(json.dumps({"status": "COMPLETE_62_RAW_TYPED_DIAGNOSTICS", "rows": len(records), "daily_rank_rows": len(daily),
                      "fit_calls": 0, "learning_update_calls": 0, "freeze_hashes_verified_after": len(freeze["artifact_sha256"]), "formal_2026_full_pool_status": "BLOCKED_DATA"}))


if __name__ == "__main__":
    main()
