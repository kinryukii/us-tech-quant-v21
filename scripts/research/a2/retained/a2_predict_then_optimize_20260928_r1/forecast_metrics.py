"""Frozen, date-balanced forecast diagnostics; no fitting or model selection.

2025 targets are joined by exact keys from the pre-2026 snapshot. 2026 targets
are built from guarded next-session opens only after complete hash validation.
Returns are never clipped for evaluation. Proxy distribution diagnostics are
labelled separately from native quantiles, distributions and probabilities.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from common import ROOT, PROVIDERS, PROBS, DISTRIBUTIONS, QUANTILES, forecasts, read, sha, write
from freeze_batch import validate_global_freeze

KEY = ["signal_date", "ticker"]
LOG_EPSILON = 1e-12
QUANTILE_LEVELS = {"q10": .1, "q50": .5, "q90": .9}


def _unique_keys(frame, name):
    if frame.duplicated(KEY).any():
        raise ValueError(f"DUPLICATE_{name}_KEYS")


def labels_from_pre2026(keys, source):
    """Keep unavailable targets as rows instead of silently narrowing the pool."""
    _unique_keys(keys, "EXPECTED")
    _unique_keys(source, "SOURCE")
    required = KEY + ["execution_date", "label_end_date", "label_available", "y_next_open"]
    result = keys[KEY].merge(source[required], on=KEY, how="left", validate="one_to_one", indicator=True)
    signal = pd.to_datetime(result.signal_date)
    execution = pd.to_datetime(result.execution_date)
    endpoint = pd.to_datetime(result.label_end_date)
    target = pd.to_numeric(result.y_next_open, errors="coerce")
    chronological = signal.lt(execution) & execution.lt(endpoint)
    past_only = signal.lt("2026-01-01") & endpoint.lt("2026-01-01")
    available = result.label_available.eq(True).fillna(False) & np.isfinite(target) & chronological & past_only
    result["label_available"] = available
    result["y_next_open"] = target.where(available)
    result["label_missing_reason"] = np.select(
        [result._merge.eq("left_only"), ~chronological, ~past_only, ~np.isfinite(target), ~available],
        ["source_key_missing", "invalid_label_clock", "label_not_pre2026", "target_missing_or_nonfinite", "source_label_unavailable"],
        default="available")
    return result.drop(columns="_merge")


def labels_from_prices(keys, prices, calendar):
    """Signal t -> t+1 open -> t+2 open, without using missing labels to select."""
    _unique_keys(keys, "EXPECTED")
    required = ["ticker", "trade_date", "open", "price_quality_warning"]
    if any(column not in prices for column in required):
        raise ValueError("NEXT_OPEN_LABEL_PRICE_SCHEMA_MISSING")
    if prices.duplicated(["ticker", "trade_date"]).any():
        raise ValueError("DUPLICATE_PRICE_KEYS")
    calendar = pd.DatetimeIndex(pd.to_datetime(calendar))
    if not calendar.is_unique or not calendar.is_monotonic_increasing or calendar.hasnans:
        raise ValueError("LABEL_CALENDAR_MUST_BE_ORDERED_UNIQUE")
    result = keys[KEY].copy().reset_index(drop=True)
    result["signal_date"] = pd.to_datetime(result.signal_date)
    positions = calendar.get_indexer(result.signal_date)
    execution = np.full(len(result), np.datetime64("NaT"), dtype="datetime64[ns]")
    endpoint = execution.copy()
    first = (positions >= 0) & (positions + 1 < len(calendar))
    second = (positions >= 0) & (positions + 2 < len(calendar))
    execution[first] = calendar.to_numpy(dtype="datetime64[ns]")[positions[first] + 1]
    endpoint[second] = calendar.to_numpy(dtype="datetime64[ns]")[positions[second] + 2]
    result["execution_date"], result["label_end_date"] = execution, endpoint
    lookup = prices[required].copy()
    lookup["trade_date"] = pd.to_datetime(lookup.trade_date)
    for label, date_column in [("entry", "execution_date"), ("exit", "label_end_date")]:
        renamed = lookup.rename(columns={"trade_date": date_column, "open": f"open_{label}",
                                         "price_quality_warning": f"warning_{label}"})
        renamed[f"price_present_{label}"] = True
        result = result.merge(renamed, on=["ticker", date_column], how="left", validate="many_to_one")
    entry, exit_ = [pd.to_numeric(result[f"open_{label}"], errors="coerce") for label in ("entry", "exit")]
    present = result.price_present_entry.eq(True) & result.price_present_exit.eq(True)
    finite = np.isfinite(entry) & np.isfinite(exit_)
    positive = entry.gt(0) & exit_.gt(0)
    warning_clear = result.warning_entry.eq(False).fillna(False) & result.warning_exit.eq(False).fillna(False)
    complete_clock = first & second
    valid = complete_clock & present & finite & positive & warning_clear
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        target = exit_ / entry - 1
    valid &= np.isfinite(target)
    result["label_available"] = valid
    result["y_next_open"] = target.where(valid)
    result["label_missing_reason"] = np.select(
        [positions < 0, ~complete_clock, ~present, ~finite, ~positive, ~warning_clear, ~np.isfinite(target)],
        ["signal_not_in_calendar", "next_two_sessions_unavailable", "next_open_price_missing",
         "next_open_price_nonfinite", "next_open_price_nonpositive", "price_quality_warning_or_unknown", "target_nonfinite"],
        default="available")
    return result


def load_labels(year):
    if year not in (2025, 2026):
        raise ValueError("METRIC_YEAR_NOT_IN_FROZEN_CONTRACT")
    if year == 2026:
        validate_global_freeze()  # Always before the first evaluation input read.
    directory = ROOT / f"input/eval_{year}"
    features_path = directory / "features.parquet"
    keys = pd.read_parquet(features_path, columns=KEY).sort_values(KEY, kind="stable").reset_index(drop=True)
    if not keys.signal_date.dt.year.eq(year).all():
        raise ValueError("EVALUATION_SIGNAL_YEAR_MISMATCH")
    metadata = read(directory / "METADATA.json")
    hashes = {str(features_path.relative_to(ROOT)): sha(features_path)}
    if year == 2025:
        source_path = ROOT / "input/pre2026.parquet"
        source = pd.read_parquet(source_path, columns=KEY + ["execution_date", "label_end_date", "label_available", "y_next_open"])
        result = labels_from_pre2026(keys, source)
        hashes[str(source_path.relative_to(ROOT))] = sha(source_path)
    else:
        price_path, calendar_path = directory / "prices.parquet", directory / "calendar.parquet"
        prices = pd.read_parquet(price_path, columns=["ticker", "trade_date", "open", "price_quality_warning"])
        calendar = pd.read_parquet(calendar_path, columns=["trade_date"])
        result = labels_from_prices(keys, prices, calendar.trade_date)
        hashes.update({str(path.relative_to(ROOT)): sha(path) for path in (price_path, calendar_path)})
    return result, hashes, metadata


def _date_mean(series, dates):
    return pd.Series(series, index=dates.index).groupby(dates, sort=True).mean()


def _summary_mean(series):
    finite = pd.to_numeric(series, errors="coerce")
    finite = finite[np.isfinite(finite)]
    return float(finite.mean()) if len(finite) else np.nan


def _align(labels, prediction, columns):
    _unique_keys(labels, "LABEL")
    _unique_keys(prediction, "PREDICTION")
    expected = pd.MultiIndex.from_frame(labels[KEY])
    actual = pd.MultiIndex.from_frame(prediction[KEY])
    extra = len(actual.difference(expected))
    joined = labels.merge(prediction[KEY + columns], on=KEY, how="left", validate="one_to_one", indicator=True)
    return joined, extra


def normal_semantics(spec):
    if spec["fusion"] != "identity":
        return "fused_normal_moment_proxy"
    provider = spec["members"][0]
    if provider in DISTRIBUTIONS:
        return "native_Normal_distribution"
    if provider in QUANTILES:
        return "normal_width_approximation_to_native_quantiles"
    if provider in PROBS:
        return "training_class_amplitude_normal_moment_proxy"
    return "training_residual_normal_proxy; in-sample scale"


def forecast_diagnostics(labels, prediction, spec):
    columns = ["mu", "sigma", *QUANTILE_LEVELS]
    frame, extra = _align(labels, prediction, columns)
    for column in columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    dates, y, mu, sigma = frame.signal_date, frame.y_next_open, frame.mu, frame.sigma
    label_valid = frame.label_available.eq(True) & np.isfinite(y)
    score_valid = np.isfinite(mu)
    valid = label_valid & score_valid
    daily = pd.DataFrame(index=pd.DatetimeIndex(sorted(dates.unique()), name="signal_date"))
    daily["pool_rows"] = dates.value_counts().sort_index()
    daily["label_missing_rows"] = (~label_valid).groupby(dates).sum()
    daily["forecast_missing_rows"] = frame._merge.eq("left_only").groupby(dates).sum()
    daily["paired_mu_rows"] = valid.groupby(dates).sum()
    daily["mse"] = _date_mean(((mu - y) ** 2).where(valid), dates)
    daily["mae"] = _date_mean((mu - y).abs().where(valid), dates)
    ranked_mu = mu.where(valid).groupby(dates).rank(method="average")
    ranked_y = y.where(valid).groupby(dates).rank(method="average")
    centered_mu = ranked_mu - ranked_mu.groupby(dates).transform("mean")
    centered_y = ranked_y - ranked_y.groupby(dates).transform("mean")
    numerator = (centered_mu * centered_y).groupby(dates).sum(min_count=2)
    denominator = np.sqrt((centered_mu ** 2).groupby(dates).sum(min_count=2) * (centered_y ** 2).groupby(dates).sum(min_count=2))
    daily["day_spearman_ic"] = numerator / denominator.where(denominator > 0)
    nll_valid = valid & np.isfinite(sigma) & sigma.gt(0)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        nll = np.log(sigma) + .5 * np.log(2 * np.pi) + .5 * ((y - mu) / sigma) ** 2
    nll_valid &= np.isfinite(nll)
    daily["normal_nll"] = _date_mean(nll.where(nll_valid), dates)
    quantile_valid = label_valid.copy()
    for column, level in QUANTILE_LEVELS.items():
        usable = label_valid & np.isfinite(frame[column])
        delta = y - frame[column]
        daily[f"pinball_{column}"] = _date_mean(np.maximum(level * delta, (level - 1) * delta).where(usable), dates)
        daily[f"coverage_below_{column}"] = _date_mean(y.le(frame[column]).astype(float).where(usable), dates)
        quantile_valid &= np.isfinite(frame[column])
    daily["coverage_q10_q90"] = _date_mean((y.ge(frame.q10) & y.le(frame.q90)).astype(float).where(quantile_valid), dates)
    crossing = frame.q10.gt(frame.q50) | frame.q50.gt(frame.q90)
    daily["quantile_crossing_rows"] = (crossing & quantile_valid).groupby(dates).sum()
    # Selection always occurs on the complete provided input pool before labels are inspected.
    ordered = frame.loc[score_valid].sort_values(["signal_date", "mu", "ticker"], ascending=[True, False, True], kind="stable")
    selected = ordered.groupby("signal_date", sort=False).head(20)
    selected_valid = selected.label_available.eq(True) & np.isfinite(selected.y_next_open)
    daily["top20_selected_count"] = selected.groupby("signal_date").size()
    daily["top20_labelled_count"] = selected_valid.groupby(selected.signal_date).sum()
    daily["top20_target_mean_available_labels"] = _date_mean(selected.y_next_open.where(selected_valid), selected.signal_date)
    daily["pool_target_mean_available_labels"] = _date_mean(y.where(label_valid), dates)
    complete = (daily.pool_rows >= 20) & (daily.label_missing_rows == 0) & (daily.paired_mu_rows == daily.pool_rows) & (daily.top20_selected_count == 20)
    daily["top20_whole_input_pool_complete_date"] = complete
    daily["top20_target_mean"] = daily.top20_target_mean_available_labels.where(complete)
    daily["whole_input_pool_target_mean"] = daily.pool_target_mean_available_labels.where(complete)
    daily["top20_minus_whole_input_pool"] = daily.top20_target_mean - daily.whole_input_pool_target_mean
    semantics = sorted(prediction.marginal_semantics.dropna().astype(str).unique()) if "marginal_semantics" in prediction else [normal_semantics(spec)]
    metrics = dict(forecast_id=spec["forecast_id"], coalition=spec["coalition"], fusion=spec["fusion"],
        status="PASS" if extra == 0 and not frame._merge.eq("left_only").any() and score_valid.all() else "KEY_OR_SCORE_COVERAGE_FAILURE",
        expected_pool_rows=len(labels), forecast_rows=len(prediction), extra_forecast_keys=extra,
        missing_forecast_keys=int(frame._merge.eq("left_only").sum()), missing_label_rows=int((~label_valid).sum()),
        valid_mu_target_rows=int(valid.sum()), invalid_score_rows=int((~score_valid).sum()),
        valid_normal_nll_rows=int(nll_valid.sum()), invalid_normal_nll_rows=int((label_valid & ~nll_valid).sum()),
        days=len(daily), mse_days=int(daily.mse.notna().sum()), ic_days=int(daily.day_spearman_ic.notna().sum()),
        top20_complete_input_pool_days=int(complete.sum()), evaluation_clip=0, target_clipping="none",
        weighting="equal date weights; equal candidate weights within each eligible date",
        normal_nll_semantics=normal_semantics(spec), quantile_semantics=" | ".join(semantics),
        top20_selection="mu descending, ticker ascending for ties, before label filtering",
        whole_pool_semantics="entire provided input candidate pool; availability scope is reported separately")
    for column in ["mse", "mae", "day_spearman_ic", "normal_nll", "top20_target_mean", "whole_input_pool_target_mean", "top20_minus_whole_input_pool",
                   *[f"pinball_{q}" for q in QUANTILE_LEVELS], *[f"coverage_below_{q}" for q in QUANTILE_LEVELS], "coverage_q10_q90"]:
        metrics[column] = _summary_mean(daily[column])
    daily = daily.reset_index()
    daily["forecast_id"] = spec["forecast_id"]
    return metrics, daily


def native_probability_diagnostics(labels, prediction, provider):
    semantics = ("native_classifier_p_up" if provider in PROBS else
                 "native_Normal_implied_p_up" if provider in DISTRIBUTIONS else "native_probability_unavailable")
    base = dict(provider=provider, probability_semantics=semantics, evaluation_clip=0, target_clipping="none",
                logarithm_epsilon=LOG_EPSILON, proxy_probabilities_used=False)
    if provider not in PROBS + DISTRIBUTIONS:
        return dict(**base, status="NO_NATIVE_PROBABILITY", brier=np.nan, logloss=np.nan, evaluated_rows=0, evaluated_days=0,
                    expected_pool_rows=len(labels), missing_label_rows=int((~labels.label_available).sum()))
    if "p_up" not in prediction:
        return dict(**base, status="NATIVE_P_UP_MISSING", brier=np.nan, logloss=np.nan, evaluated_rows=0, evaluated_days=0,
                    expected_pool_rows=len(labels), missing_label_rows=int((~labels.label_available).sum()))
    frame, extra = _align(labels, prediction, ["p_up"])
    p = pd.to_numeric(frame.p_up, errors="coerce")
    label_valid = frame.label_available.eq(True) & np.isfinite(frame.y_next_open)
    probability_valid = np.isfinite(p) & p.between(0, 1)
    valid = label_valid & probability_valid
    y_up = frame.y_next_open.gt(0).astype(float)
    log_p = p.clip(LOG_EPSILON, 1 - LOG_EPSILON)
    brier = _date_mean(((p - y_up) ** 2).where(valid), frame.signal_date)
    logloss = _date_mean((-y_up * np.log(log_p) - (1 - y_up) * np.log1p(-log_p)).where(valid), frame.signal_date)
    return dict(**base, status="PASS" if extra == 0 and not frame._merge.eq("left_only").any() and probability_valid.all() else "NATIVE_PROBABILITY_COVERAGE_FAILURE",
        brier=_summary_mean(brier), logloss=_summary_mean(logloss), evaluated_rows=int(valid.sum()), evaluated_days=int(brier.notna().sum()),
        missing_label_rows=int((~label_valid).sum()), invalid_native_probability_rows=int((~probability_valid).sum()),
        missing_native_prediction_keys=int(frame._merge.eq("left_only").sum()), extra_native_prediction_keys=extra)


def run(year, *, resume=False):
    if year == 2026:
        validate_global_freeze()
    labels, label_hashes, metadata = load_labels(year)
    output = ROOT / f"diagnostics/forecast_metrics/{year}"
    receipt_path = output / "RECEIPT.json"
    if receipt_path.exists():
        if not resume:
            raise FileExistsError("PRESERVE_EXISTING_FORECAST_METRICS")
        saved = read(receipt_path)
        if saved["metric_code_sha256"] != sha(Path(__file__)) or saved["label_source_sha256"] != label_hashes:
            raise RuntimeError("METRIC_RESUME_SOURCE_HASH_CHANGED")
        for relative, value in {**saved["prediction_sha256"], **saved["output_sha256"]}.items():
            if sha(ROOT / relative) != value:
                raise RuntimeError("METRIC_RESUME_ARTIFACT_CHANGED")
        return saved
    output.mkdir(parents=True, exist_ok=True)
    metrics, daily, probabilities, prediction_hashes = [], [], [], {}
    for spec in forecasts():
        path = ROOT / f"predictions/forecasts/{year}" / (spec["forecast_id"] + ".parquet")
        if not path.exists():
            metrics.append(dict(forecast_id=spec["forecast_id"], coalition=spec["coalition"], fusion=spec["fusion"], status="MISSING_FORECAST", evaluation_clip=0))
            continue
        prediction_hashes[str(path.relative_to(ROOT))] = sha(path)
        try:
            result, dates = forecast_diagnostics(labels, pd.read_parquet(path), spec)
            result["input_pool_scope"] = metadata.get("scope", "see evaluation metadata")
            result["original_unfiltered_13f_pool_complete"] = metadata.get("original_unfiltered_13f_holdings_pool_complete", False)
            metrics.append(result)
            daily.append(dates)
        except Exception as exc:
            metrics.append(dict(forecast_id=spec["forecast_id"], coalition=spec["coalition"], fusion=spec["fusion"], status="FAILED", error=f"{type(exc).__name__}: {exc}", evaluation_clip=0))
    native_stage = "validation" if year == 2025 else "final"
    for provider in PROVIDERS:
        path = ROOT / "predictions/native" / native_stage / (provider + ".parquet")
        if not path.exists():
            probabilities.append(dict(provider=provider, status="MISSING_NATIVE_PREDICTION", proxy_probabilities_used=False))
            continue
        prediction_hashes[str(path.relative_to(ROOT))] = sha(path)
        try:
            native = pd.read_parquet(path, columns=KEY + ["p_up"])
            # Native annual OOF includes additional terminal signal keys; diagnostics
            # use exactly the frozen evaluation keys without treating extras as errors.
            native = labels[KEY].merge(native, on=KEY, how="left", validate="one_to_one")
            probabilities.append(native_probability_diagnostics(labels, native, provider))
        except Exception as exc:
            probabilities.append(dict(provider=provider, status="FAILED", error=f"{type(exc).__name__}: {exc}", proxy_probabilities_used=False))
    for result in metrics + probabilities:
        result.setdefault("evaluation_clip", 0)
        result.setdefault("expected_pool_rows", len(labels))
        result.setdefault("missing_label_rows", int((~labels.label_available).sum()))
    pd.DataFrame(metrics).to_csv(output / "FORECAST_METRICS.csv", index=False)
    pd.concat(daily, ignore_index=True).to_parquet(output / "FORECAST_DAILY.parquet", index=False) if daily else pd.DataFrame().to_parquet(output / "FORECAST_DAILY.parquet", index=False)
    pd.DataFrame(probabilities).to_csv(output / "NATIVE_PROBABILITY_METRICS.csv", index=False)
    labels.groupby("label_missing_reason").size().rename("rows").to_csv(output / "LABEL_AVAILABILITY.csv")
    paths = [output / filename for filename in ["FORECAST_METRICS.csv", "FORECAST_DAILY.parquet", "NATIVE_PROBABILITY_METRICS.csv", "LABEL_AVAILABILITY.csv"]]
    receipt = dict(status="PASS" if len(metrics) == 152 and all(row["status"] == "PASS" for row in metrics)
                   and len(probabilities) == 31 and all(row["status"] in ("PASS", "NO_NATIVE_PROBABILITY") for row in probabilities) else "PARTIAL_OR_FAILURE",
        year=year, forecasts_expected=152, forecasts_reported=len(metrics), native_probability_rows=len(probabilities),
        label_source_sha256=label_hashes, prediction_sha256=prediction_hashes,
        output_sha256={str(path.relative_to(ROOT)): sha(path) for path in paths}, metric_code_sha256=sha(Path(__file__)),
        eval_metadata=metadata, evaluation_clip=0, no_parameter_fitting=True, no_model_selection=True,
        label_rows=len(labels), available_labels=int(labels.label_available.sum()), missing_labels=int((~labels.label_available).sum()),
        target="next-session open to following-session open", probability_proxy_substitution=False,
        normal_density_semantics="native Normal models scored as native; all other Normal scores are labelled diagnostic proxies",
        global_freeze_sha256=sha(ROOT / "GLOBAL_FREEZE.json") if year == 2026 else None,
        created_utc=datetime.now(timezone.utc).isoformat())
    write(receipt_path, receipt)
    print(json.dumps({"event": "FORECAST_METRICS_DONE", "year": year, "status": receipt["status"],
                      "forecasts": len(metrics), "missing_labels": receipt["missing_labels"], "no_fit": True}), flush=True)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, choices=[2025, 2026], required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    run(args.year, resume=args.resume)


if __name__ == "__main__":
    main()
