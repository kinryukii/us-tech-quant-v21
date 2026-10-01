"""Descriptive analysis of the fixed roster; no fitting or model selection.

Public pure-frame APIs are used by synthetic tests.  The CLI requires both
completed years and the existing full-batch freeze before reading 2026 outcomes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import math

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from shared import (ROOT, PREDICTORS, POINTS, PROB, QUANTILE, DISTRIBUTION,
                    RANK, GROUPS, RISKS, OPTIMIZERS, TARGET_FUSIONS, paths,
                    read_json, write_json, sha)

YEARS = (2025, 2026)
EXPECTED_PER_YEAR = 8194
DIMENSIONS = ["members", "group", "fusion", "risk", "optimizer", "layer"]
BASELINES = {"predictor": "ridge", "fusion": "equal", "risk": "diagonal",
             "optimizer": "positive_equal", "composition": "all_points"}
METRICS = ["indicative_return", "indicative_max_drawdown", "annualized_volatility",
           "sharpe_zero_rf", "mean_gross_exposure", "mean_cash_weight",
           "total_fees", "turnover", "mean_daily_return_per_previous_invested_fraction",
           "uncertified_nav_days", "blocked_orders",
           "optimization_iteration_limit_decisions"]
REPLAY_STATUSES = {"REPLAY_COMPLETE", "REPLAY_COMPLETE_WITH_APPROXIMATE_SOLVES"}
KEYS = ["signal_date", "ticker"]


def validate_coverage(frames: dict[int, pd.DataFrame], roster=None,
                      required_years=YEARS) -> pd.DataFrame:
    """Fail closed on missing, duplicated, extra, or relabelled strategies."""
    roster = paths() if roster is None else roster.copy()
    counts = roster.layer.value_counts().to_dict()
    if len(roster) != EXPECTED_PER_YEAR or counts != {"pto": 7904, "target_fusion": 286, "rl_control": 4}:
        raise ValueError("PREDECLARED_ROSTER_NOT_8194")
    if roster.path_id.duplicated().any():
        raise ValueError("DUPLICATE_DECLARED_PATH")
    if set(frames) != set(required_years):
        raise ValueError("BOTH_FIXED_EVALUATION_YEARS_REQUIRED")
    result = []
    expected = set(roster.path_id)
    for year in required_years:
        frame = frames[year].copy()
        if len(frame) != EXPECTED_PER_YEAR or frame.path_id.duplicated().any() or set(frame.path_id) != expected:
            raise ValueError(f"INCOMPLETE_OR_EXTRA_PATH_COVERAGE:{year}")
        if "research_status" not in frame or frame.research_status.isna().any():
            raise ValueError(f"UNRESOLVED_STATUS:{year}")
        if "year" in frame and not pd.to_numeric(frame.year).eq(year).all():
            raise ValueError(f"YEAR_MISMATCH:{year}")
        checked = frame.merge(roster, on="path_id", how="left", validate="one_to_one", suffixes=("", "__declared"))
        for column in DIMENSIONS:
            declared = column + "__declared"
            if declared in checked:
                if not checked[column].fillna("").astype(str).eq(checked[declared].fillna("").astype(str)).all():
                    raise ValueError(f"DECLARED_DIMENSION_MISMATCH:{year}:{column}")
                checked = checked.drop(columns=declared)
        checked["year"] = int(year)
        checked["replay_complete"] = checked.research_status.isin(REPLAY_STATUSES)
        for metric in METRICS:
            if metric not in checked:
                checked[metric] = np.nan
            checked[metric] = pd.to_numeric(checked[metric], errors="coerce")
        returns = checked.indicative_return
        checked["result_sign"] = np.select(
            [~checked.replay_complete, ~np.isfinite(returns), returns.gt(0), returns.lt(0)],
            ["FAILED_OR_UNRESOLVED", "NONFINITE_RESULT", "POSITIVE", "NEGATIVE"], default="ZERO")
        checked["fee_fraction_initial_nav"] = checked.total_fees / 1e6
        checked["predictor_identity"] = np.where(checked.layer.eq("pto") & checked.fusion.eq("identity"), checked.group, "")
        result.append(checked)
    combined = pd.concat(result, ignore_index=True)
    if len(combined) != EXPECTED_PER_YEAR * len(required_years) or combined.duplicated(["year", "path_id"]).any():
        raise ValueError("TWO_YEAR_COVERAGE_NOT_EXACT")
    return combined


def factor_main_effects(combinations: pd.DataFrame) -> pd.DataFrame:
    """Marginal cell summaries, retaining failures and finite metric counts."""
    rows = []
    for year, frame in combinations.groupby("year", sort=True):
        pto = frame.loc[frame.layer.eq("pto")]
        definitions = [
            ("predictor", pto.loc[pto.fusion.eq("identity")], ["group"]),
            ("fusion", pto.loc[pto.fusion.ne("identity")], ["group", "fusion"]),
            ("risk", pto, ["risk"]), ("optimizer", pto, ["optimizer"]),
            ("target_fusion", frame.loc[frame.layer.eq("target_fusion")], ["optimizer"]),
            ("rl_control", frame.loc[frame.layer.eq("rl_control")], ["optimizer"]),
        ]
        for dimension, subset, columns in definitions:
            for key, block in subset.groupby(columns, sort=True):
                key = key if isinstance(key, tuple) else (key,)
                context = dict(zip(columns, key))
                success = block.loc[block.replay_complete]
                row = dict(year=year, dimension=dimension, level=str(key[-1]),
                           within_group=context.get("group", ""), legal_cells=len(block),
                           replayed_cells=len(success), failed_cells=len(block)-len(success),
                           positive_cells=int(success.result_sign.eq("POSITIVE").sum()),
                           negative_cells=int(success.result_sign.eq("NEGATIVE").sum()),
                           zero_cells=int(success.result_sign.eq("ZERO").sum()),
                           weighting="one declared cell one vote; descriptive, correlated")
                for metric in METRICS:
                    value = success[metric].replace([np.inf, -np.inf], np.nan).dropna()
                    row[metric + "__n"] = len(value)
                    for statistic in ["mean", "median", "min", "max"]:
                        row[metric + "__" + statistic] = getattr(value, statistic)() if len(value) else np.nan
                rows.append(row)
    return pd.DataFrame(rows)


def build_effects(combinations: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fixed-baseline paired contrasts and four-cell difference-in-differences.

    Deltas are treatment minus reference.  Drawdowns are negative numbers, so a
    positive drawdown delta means a shallower drawdown.  No significance tests.
    """
    look = {(int(r["year"]), r["layer"], r["group"], r["fusion"], r["risk"], r["optimizer"]): r
            for r in combinations.to_dict("records")}
    paired, interactions = [], []

    def key(y, g, f, r, o, layer="pto"):
        return (int(y), layer, g, f, r, o)

    def identifier(k):
        return k[-1] if k[1] == "rl_control" else "__".join(k[2:])

    def contrast(family, dimension, level, reference, ks, details, did=False):
        cells = [look.get(k) for k in ks]
        names = ["treatment", "reference"] if not did else ["a1_b1", "a0_b1", "a1_b0", "a0_b0"]
        ready = all(c is not None and c.get("replay_complete", False) for c in cells)
        row = dict(year=ks[0][0], family=family, dimension=dimension, level=level,
                   reference_level=reference, comparison_status="AVAILABLE" if ready else "UNAVAILABLE_REQUIRED_CELL",
                   formula="a1b1-a0b1-a1b0+a0b0" if did else "treatment-reference", **details)
        for name, k, c in zip(names, ks, cells):
            row[name + "_path_id"] = identifier(k)
            row[name + "_status"] = "MISSING" if c is None else c.get("research_status", "UNRESOLVED")
            row[name + "_failure_reason"] = "MISSING_DECLARED_CELL" if c is None else str(c.get("failure_reason", ""))
        for metric in METRICS:
            values = [np.nan if c is None else c.get(metric, np.nan) for c in cells]
            finite = ready and all(pd.notna(v) and np.isfinite(float(v)) for v in values)
            row[metric + "__delta"] = (values[0]-values[1]-values[2]+values[3] if did else values[0]-values[1]) if finite else np.nan
            row[metric + "__finite"] = bool(finite)
            if not did:
                row[metric + "__treatment"], row[metric + "__reference"] = values
        (interactions if did else paired).append(row)

    for year, frame in combinations.groupby("year", sort=True):
        pto = frame.loc[frame.layer.eq("pto")]
        forecasts = list(pto[["group", "fusion"]].drop_duplicates().itertuples(index=False, name=None))
        singles = [p for p in PREDICTORS if ((pto.group == p) & (pto.fusion == "identity")).any()]
        risk_levels = [r for r in RISKS if pto.risk.eq(r).any()]
        opt_levels = [o for o in OPTIMIZERS if pto.optimizer.eq(o).any()]
        cooperation = [(g, f) for g, f in forecasts if f != "identity"]
        groups = sorted({g for g, _ in cooperation})
        for predictor in singles:
            if predictor == "ridge":
                continue
            for risk in risk_levels:
                for opt in opt_levels:
                    details = dict(group=predictor, fusion="identity", risk=risk, optimizer=opt)
                    contrast("predictor", "predictor", predictor, "ridge",
                             [key(year, predictor, "identity", risk, opt), key(year, "ridge", "identity", risk, opt)], details)
        for group, fusion in cooperation:
            if fusion == "equal":
                continue
            for risk in risk_levels:
                for opt in opt_levels:
                    details = dict(group=group, fusion=fusion, risk=risk, optimizer=opt)
                    contrast("fusion_within_group", "fusion", fusion, "equal",
                             [key(year, group, fusion, risk, opt), key(year, group, "equal", risk, opt)], details)
        for group, fusion in forecasts:
            for risk in risk_levels:
                for opt in opt_levels:
                    details = dict(group=group, fusion=fusion, risk=risk, optimizer=opt)
                    if risk != "diagonal":
                        contrast("risk_fixed_forecast_optimizer", "risk", risk, "diagonal",
                                 [key(year, group, fusion, risk, opt), key(year, group, fusion, "diagonal", opt)], details)
                    if opt != "positive_equal":
                        contrast("optimizer_fixed_forecast_risk", "optimizer", opt, "positive_equal",
                                 [key(year, group, fusion, risk, opt), key(year, group, fusion, risk, "positive_equal")], details)
                    if risk != "diagonal" and opt != "positive_equal":
                        contrast("risk_x_optimizer", "risk:optimizer", risk+":"+opt, "diagonal:positive_equal",
                                 [key(year, group, fusion, risk, opt), key(year, group, fusion, "diagonal", opt),
                                  key(year, group, fusion, risk, "positive_equal"), key(year, group, fusion, "diagonal", "positive_equal")], details, True)
        for predictor in singles:
            if predictor == "ridge":
                continue
            for risk in risk_levels:
                for opt in opt_levels:
                    details = dict(group=predictor, fusion="identity", risk=risk, optimizer=opt)
                    if risk != "diagonal":
                        contrast("predictor_x_risk", "predictor:risk", predictor+":"+risk, "ridge:diagonal",
                                 [key(year, predictor, "identity", risk, opt), key(year, "ridge", "identity", risk, opt),
                                  key(year, predictor, "identity", "diagonal", opt), key(year, "ridge", "identity", "diagonal", opt)], details, True)
                    if opt != "positive_equal":
                        contrast("predictor_x_optimizer", "predictor:optimizer", predictor+":"+opt, "ridge:positive_equal",
                                 [key(year, predictor, "identity", risk, opt), key(year, "ridge", "identity", risk, opt),
                                  key(year, predictor, "identity", risk, "positive_equal"), key(year, "ridge", "identity", risk, "positive_equal")], details, True)
        for group, fusion in cooperation:
            if fusion == "equal":
                continue
            for risk in risk_levels:
                for opt in opt_levels:
                    details = dict(group=group, fusion=fusion, risk=risk, optimizer=opt)
                    if risk != "diagonal":
                        contrast("fusion_x_risk", "fusion:risk", fusion+":"+risk, "equal:diagonal",
                                 [key(year, group, fusion, risk, opt), key(year, group, "equal", risk, opt),
                                  key(year, group, fusion, "diagonal", opt), key(year, group, "equal", "diagonal", opt)], details, True)
                    if opt != "positive_equal":
                        contrast("fusion_x_optimizer", "fusion:optimizer", fusion+":"+opt, "equal:positive_equal",
                                 [key(year, group, fusion, risk, opt), key(year, group, "equal", risk, opt),
                                  key(year, group, fusion, risk, "positive_equal"), key(year, group, "equal", risk, "positive_equal")], details, True)
                    if group != "all_points" and "all_points" in groups:
                        contrast("composition_x_fusion", "composition:fusion", group+":"+fusion, "all_points:equal",
                                 [key(year, group, fusion, risk, opt), key(year, "all_points", fusion, risk, opt),
                                  key(year, group, "equal", risk, opt), key(year, "all_points", "equal", risk, opt)], details, True)
        target = frame.loc[frame.layer.eq("target_fusion")]
        for r in target.itertuples():
            details = dict(group=r.group, fusion=r.fusion, risk=r.risk, optimizer=r.optimizer)
            contrast("target_fusion_vs_independent_mean_variance", "target_fusion", r.optimizer, "mean_variance",
                     [key(year, r.group, r.fusion, r.risk, r.optimizer, "target_fusion"), key(year, r.group, r.fusion, r.risk, "mean_variance")], details)
            if r.optimizer == "target_median":
                contrast("target_fusion_paired", "target_fusion", "target_median", "target_equal",
                         [key(year, r.group, r.fusion, r.risk, "target_median", "target_fusion"), key(year, r.group, r.fusion, r.risk, "target_equal", "target_fusion")], details)
        for method in ["reinforce", "ppo"]:
            if frame.path_id.eq(method).any():
                contrast("rl_trained_vs_same_initialization_zero", "rl_control", method, method+"_zero",
                         [key(year, "rl", "none", "implicit", method, "rl_control"), key(year, "rl", "none", "implicit", method+"_zero", "rl_control")],
                         dict(group="rl", fusion="none", risk="implicit", optimizer=method))
    return pd.DataFrame(paired), pd.DataFrame(interactions)


def reconstruct_next_open_labels(panel, prices, calendar, known_input_conflicts=(), known_price_conflicts=()):
    """Evaluation-only label reconstruction; retain unavailable keys and reasons."""
    panel = panel.copy()
    panel.signal_date = pd.to_datetime(panel.signal_date)
    prices = prices.copy()
    prices.trade_date = pd.to_datetime(prices.trade_date)
    if panel.duplicated(KEYS).any() or prices.duplicated(["ticker", "trade_date"]).any():
        raise ValueError("DUPLICATE_LABEL_INPUT_KEYS")
    calendar = pd.DatetimeIndex(sorted(pd.to_datetime(calendar).unique()))
    positions = calendar.get_indexer(panel.signal_date)
    if (positions < 0).any():
        raise ValueError("SIGNAL_OUTSIDE_LABEL_CALENDAR")
    for field, offset in [("execution_date", 1), ("label_end_date", 2)]:
        values = np.full(len(panel), np.datetime64("NaT"), dtype="datetime64[ns]")
        valid = positions + offset < len(calendar)
        values[valid] = calendar.to_numpy()[positions[valid]+offset]
        panel[field] = values
    quote = prices.set_index(["ticker", "trade_date"])
    data = []
    for field in ["execution_date", "label_end_date"]:
        idx = pd.MultiIndex.from_arrays([panel.ticker.astype(str), panel[field]])
        price = quote.open.reindex(idx).to_numpy(float)
        if "price_quality_warning" in quote:
            warning = quote.price_quality_warning.reindex(idx).fillna(True).to_numpy(bool)
        else:
            warning = ~np.isfinite(price)
        conflict = np.asarray([(pd.Timestamp(d), str(t)) in set(known_price_conflicts) for d, t in zip(panel[field], panel.ticker)], bool)
        data.append((price, warning | conflict))
    first, bad_first = data[0]
    last, bad_last = data[1]
    conflict = np.asarray([(pd.Timestamp(d), str(t)) in set(known_input_conflicts) for d, t in zip(panel.signal_date, panel.ticker)], bool)
    if "known_input_conflict" in panel:
        conflict |= panel.known_input_conflict.fillna(True).to_numpy(bool)
    valid = np.isfinite(first) & (first > 0) & np.isfinite(last) & (last > 0) & ~bad_first & ~bad_last & ~conflict
    with np.errstate(divide="ignore", invalid="ignore"):
        y = last / first - 1
    valid &= np.isfinite(y)
    panel["y_next_open"] = np.where(valid, y, np.nan)
    panel["label_available"] = valid
    panel["label_unavailable_reason"] = np.select(
        [conflict, panel.label_end_date.isna(), bad_first | bad_last, ~valid],
        ["UNAVAILABLE_KNOWN_CONFLICT", "LABEL_NOT_MATURE", "PRICE_MISSING_OR_QUALITY_WARNING", "INVALID_POSITIVE_OPEN"], default="")
    return panel


def _aligned_predictions(frame, labels):
    if frame.duplicated(KEYS).any() or labels.duplicated(KEYS).any():
        raise ValueError("DUPLICATE_PREDICTION_OR_LABEL_KEY")
    keys = labels[KEYS].copy()
    keys.signal_date = pd.to_datetime(keys.signal_date)
    frame = frame.copy()
    frame.signal_date = pd.to_datetime(frame.signal_date)
    if not frame.merge(keys, on=KEYS, how="left", indicator=True)._merge.eq("both").all():
        raise ValueError("PREDICTION_OUTSIDE_EVALUATION_LABEL_KEYS")
    return labels.merge(frame, on=KEYS, how="left", validate="one_to_one")


def prediction_metrics(raw, calibrated, streams, labels, year,
                       predictors=PREDICTORS, families=None, failures=None) -> pd.DataFrame:
    """Native statistics stay separate from calibrated tradable-return statistics.

    The primary estimate averages stock rows within date and then dates equally.
    All candidate keys, missing labels, invalid scales, and failed models count.
    """
    families = families or {"point": POINTS, "probability": PROB, "quantile": QUANTILE,
                            "distribution": DISTRIBUTION, "ranking": RANK}
    failures = failures or {}
    labels = labels.copy()
    labels.signal_date = pd.to_datetime(labels.signal_date)
    scope = labels.new_buy_eligible.fillna(False).to_numpy(bool) if "new_buy_eligible" in labels else np.ones(len(labels), bool)
    mature = labels.label_available.fillna(False).to_numpy(bool) & np.isfinite(labels.y_next_open.to_numpy(float))
    common = scope & mature
    y = labels.y_next_open.to_numpy(float)
    dates = labels.signal_date.to_numpy()
    aligned = {"native": _aligned_predictions(raw, labels), "calibrated": _aligned_predictions(calibrated, labels),
               "stream": _aligned_predictions(streams, labels)}
    rows = []

    def values(frame, column):
        return frame[column].to_numpy(float) if column in frame else np.full(len(labels), np.nan)

    def metric(source, model, statistic, value, valid, failure="", nominal=None):
        use = common & np.asarray(valid, bool) & np.isfinite(value)
        series = pd.Series(np.asarray(value)[use], index=pd.DatetimeIndex(dates[use]))
        date_means = series.groupby(level=0).mean()
        rows.append(dict(year=int(year), source=source, model=model, statistic=statistic,
                         value=float(date_means.mean()) if len(date_means) else np.nan,
                         row_weighted_value=float(series.mean()) if len(series) else np.nan,
                         nominal=nominal, candidate_keys=int(scope.sum()), mature_candidate_keys=int(common.sum()),
                         excluded_unmatured_or_bad_label=int((scope & ~mature).sum()),
                         valid_rows=int(use.sum()), invalid_or_missing_predictions=int((common & ~use).sum()),
                         valid_days=len(date_means), constant_or_too_small_days=np.nan,
                         status="AVAILABLE" if len(series) else "FAILED_OR_NO_VALID_OBSERVATIONS",
                         failure_reason=str(failure), scope="current qualified new-buy candidates; affine next-open return",
                         weighting="equal date means; row-weighted diagnostic also supplied"))

    def rank_ic(source, model, prediction, failure=""):
        valid = common & np.isfinite(prediction)
        frame = pd.DataFrame({"date": dates[valid], "p": prediction[valid], "y": y[valid]})
        correlations = []
        for _, block in frame.groupby("date", sort=True):
            if len(block) >= 2 and block.p.nunique() >= 2 and block.y.nunique() >= 2:
                correlations.append(float(block.p.rank(method="average").corr(block.y.rank(method="average"))))
        rows.append(dict(year=int(year), source=source, model=model, statistic="rank_ic",
                         value=float(np.mean(correlations)) if correlations else np.nan, row_weighted_value=np.nan,
                         nominal=None, candidate_keys=int(scope.sum()), mature_candidate_keys=int(common.sum()),
                         excluded_unmatured_or_bad_label=int((scope & ~mature).sum()), valid_rows=int(valid.sum()),
                         invalid_or_missing_predictions=int((common & ~valid).sum()), valid_days=len(correlations),
                         constant_or_too_small_days=int(frame.date.nunique()-len(correlations)),
                         status="AVAILABLE" if correlations else "FAILED_OR_NO_NONCONSTANT_DATES",
                         failure_reason=str(failure), scope="current qualified new-buy candidates; affine next-open return",
                         weighting="equal dates, daily Spearman; constant dates explicitly unavailable"))

    native = aligned["native"]
    cal = aligned["calibrated"]
    for name in predictors:
        failure = failures.get(name, "")
        if name in families.get("point", []):
            p = values(native, name+"__raw")
            metric("native_point", name, "mse", (p-y)**2, np.isfinite(p), failure)
            metric("native_point", name, "bias", p-y, np.isfinite(p), failure)
            rank_ic("native_point", name, p, failure)
        if name in families.get("probability", []):
            for source, field, frame in [("native_probability", "__p", native), ("calibrated_probability", "__calibrated_p", cal)]:
                p = values(frame, name+field)
                valid = np.isfinite(p) & (p >= 0) & (p <= 1)
                target = (y > 0).astype(float)
                clipped = np.clip(p, 1e-12, 1-1e-12)
                metric(source, name, "brier", (p-target)**2, valid, failure)
                metric(source, name, "log_loss", -(target*np.log(clipped)+(1-target)*np.log1p(-clipped)), valid, failure)
        if name in families.get("quantile", []):
            q = np.column_stack([values(native, name+"__"+s) for s in ["q10", "q50", "q90"]])
            valid = np.isfinite(q).all(axis=1)
            crossing = (q[:, 0] > q[:, 1]) | (q[:, 1] > q[:, 2])
            metric("native_quantile", name, "crossing_rate", crossing.astype(float), valid, failure, 0)
            for source, quantiles in [("native_quantile", q), ("sorted_quantile_diagnostic", np.sort(q, axis=1))]:
                for j, alpha in enumerate([.1, .5, .9]):
                    residual = y-quantiles[:, j]
                    metric(source, name, f"pinball_q{int(alpha*100)}", np.maximum(alpha*residual, (alpha-1)*residual), valid, failure)
                    metric(source, name, f"coverage_q{int(alpha*100)}", (y <= quantiles[:, j]).astype(float), valid, failure, alpha)
                metric(source, name, "interval80_coverage", ((y >= quantiles[:, 0]) & (y <= quantiles[:, 2])).astype(float), valid, failure, .8)
                metric(source, name, "interval80_width", quantiles[:, 2]-quantiles[:, 0], valid, failure)
        if name in families.get("distribution", []):
            location, scale = values(native, name+"__location"), values(native, name+"__scale")
            valid = np.isfinite(location) & np.isfinite(scale) & (scale > 0)
            with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                nll = np.log(scale) + .5*((y-location)/scale)**2 + .5*math.log(2*math.pi)
            metric("native_gaussian_distribution", name, "gaussian_nll", nll, valid, failure)
            metric("native_gaussian_distribution", name, "mean_scale", scale, valid, failure)
            metric("native_gaussian_distribution", name, "interval80_coverage", (np.abs(y-location) <= 1.2815515655446004*scale).astype(float), valid, failure, .8)
        if name in families.get("ranking", []):
            rank_ic("native_ranking", name, values(native, name+"__rank"), failure)
        mu = values(cal, name+"__mu")
        scale = values(cal, name+"__uncertainty")
        metric("calibrated_mean", name, "mse", (mu-y)**2, np.isfinite(mu), failure)
        metric("calibrated_mean", name, "bias", mu-y, np.isfinite(mu), failure)
        rank_ic("calibrated_mean", name, mu, failure)
        metric("calibrated_uncertainty", name, "mean_scale", scale, np.isfinite(scale) & (scale > 0), failure)
    forecast = aligned["stream"]
    stream_names = [c for c in streams if c not in KEYS and c not in labels.columns]
    for name in stream_names:
        mu = values(forecast, name)
        failure = failures.get(name, "")
        metric("forecast_stream", name, "mse", (mu-y)**2, np.isfinite(mu), failure)
        metric("forecast_stream", name, "bias", mu-y, np.isfinite(mu), failure)
        rank_ic("forecast_stream", name, mu, failure)
    return pd.DataFrame(rows)


def load_evaluation_labels(year, inputs):
    if year == 2025:
        labels = pd.read_parquet(inputs["pre_panel"], columns=KEYS+["new_buy_eligible", "label_available", "label_end_date", "y_next_open"])
        # Keep the last immature keys; an unavailable label never becomes zero.
        return labels.loc[labels.signal_date.dt.year.eq(year)].reset_index(drop=True)
    if year != 2026 or not (ROOT/"FROZEN_BEFORE_2026.json").exists():
        raise RuntimeError("FREEZE_REQUIRED_BEFORE_2026_LABEL_EVALUATION")
    from market_runtime import KNOWN_INPUT_CONFLICTS, KNOWN_PRICE_CONFLICTS
    labels = pd.read_parquet(inputs["test_panel"], columns=KEYS+["new_buy_eligible", "known_input_conflict"])
    labels = labels.loc[labels.signal_date.le("2026-09-22")].reset_index(drop=True)
    meta = pq.ParquetFile(inputs["test_prices"])
    columns = ["trade_date", "ticker", "open"]
    if "price_quality_warning" in meta.schema_arrow.names:
        columns.append("price_quality_warning")
    prices = pd.read_parquet(inputs["test_prices"], columns=columns)
    calendar = pd.read_parquet(inputs["calendar"], columns=["trade_date", "is_test"])
    return reconstruct_next_open_labels(labels, prices, calendar.loc[calendar.is_test, "trade_date"],
                                        KNOWN_INPUT_CONFLICTS, KNOWN_PRICE_CONFLICTS)


def attach_solver_evidence(frame, solver):
    """A failed/approximate solve is evidence, never silently a dropped cell."""
    frame = frame.copy()
    if solver.empty:
        frame["solver_statuses"] = "NOT_APPLICABLE_OR_NO_SOLVER_ROWS"
        frame["solver_decisions"] = 0
        return frame
    if solver.duplicated(["path_id", "status"]).any():
        raise ValueError("DUPLICATE_SOLVER_SUMMARY_CELL")
    agg = solver.groupby("path_id").agg(solver_statuses=("status", lambda x: "|".join(sorted(set(x.astype(str))))),
                                       solver_decisions=("decisions", "sum"), solver_iterations=("iterations", "sum"),
                                       solver_maximum_residual=("maximum_residual", "max"))
    result = frame.merge(agg, left_on="path_id", right_index=True, how="left", validate="one_to_one")
    result["solver_statuses"] = result.solver_statuses.fillna("NOT_APPLICABLE_OR_NO_SOLVER_ROWS")
    result["solver_decisions"] = result.solver_decisions.fillna(0).astype(int)
    return result


def _table(frame, columns, limit=None):
    if limit is not None:
        frame = frame.head(limit)
    if frame.empty:
        return "无可用记录。\n"
    def cell(value):
        if pd.isna(value):
            return "NA"
        if isinstance(value, (float, np.floating)):
            return f"{value:.6g}"
        return str(value).replace("|", " / ").replace("\n", " ")
    content = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"]*len(columns)) + " |"]
    content += ["| " + " | ".join(cell(row[c]) for c in columns) + " |" for row in frame.to_dict("records")]
    return "\n".join(content) + "\n"


def render_report(combinations, main, paired, interactions, prediction, gate_counts=None, inventory=None):
    """Chinese report cites the exhaustive CSVs, avoiding a stitched champion."""
    text = ["# 固定清单 Predict-then-Optimize 组合实验\n",
            "事前清单每年 8194 条、两年 16388 条；单预测器 1612、组内预测合作 6292、目标仓位融合 286、强化学习与同初始化零更新对照 4。完整正负结果及失败均在 ALL_COMBINATIONS.csv，未将每层冠军拼接成新策略。\n",
            "收益和回撤为冻结价格坐标内的指示性账户结果，尚未认证为真实股东总回报。2025 已有历史使用，2026 保留此前曝光记录，不能宣称盲测。2026 完整原候选池仍 BLOCKED_DATA；这里可执行的是 qualified 研究范围，每日 UNKNOWN 不升格、不用旧 A2 TOP20 缩小候选池。原 62393 个 qualified 新买候选键中 GLW 已知冲突隔离 1 键，运行侧 62392，UNKNOWN 原数 47271 不变。\n",
            "13F 使用原 24 家机构各取 TOP100 后的并集。新季度未公开，或公开后尚未达到最晚实际申报后的第 5 个美股交易日，继续使用最近已生效季度且保留买入资格；不能从未来季度补池。历史机构选择、身份映射和供应商到达时间仍有审计局限。GLW 已知结构冲突按共同不可预测／不可新买及价格质量规则处理。\n",
            "所有学习、标准化、校准及时间合法折外融合学习仅使用 2026 年以前数据。2025 使用 validation 工件，2026 使用 final 工件。全批冻结后只做评估；本报告不触发重训、增加成员、种子、期限或权重搜索。\n",
            "## 覆盖与全部结果\n"]
    coverage = combinations.groupby(["year", "layer", "research_status", "result_sign"], dropna=False).size().reset_index(name="paths")
    text.append(_table(coverage, list(coverage.columns)))
    if gate_counts:
        text.append("原候选池键状态：" + "；".join(f"{k}={v}" for k, v in gate_counts.items()) + "。qualified 身份不等于全部输入可用；已知冲突另行屏蔽。\n")
    text.append("## 完整组合的描述性最好与最差结果\n")
    text.append("以下按完整账户的指示性收益排序，仅用于描述已冻结结果；不据此回流选择。低回撤必须连同敞口、现金、费用、换手和未认证天数阅读。不同账户执行和持仓路径独立，不能将目标仓位融合解释成账户收益的算术平均。\n")
    columns = ["path_id", "indicative_return", "indicative_max_drawdown", "mean_gross_exposure", "mean_cash_weight", "total_fees", "turnover", "uncertified_nav_days", "optimization_iteration_limit_decisions"]
    for year, frame in combinations.groupby("year"):
        for layer in ["pto", "target_fusion", "rl_control"]:
            success = frame.loc[frame.layer.eq(layer) & frame.replay_complete & np.isfinite(frame.indicative_return)]
            text.append(f"### {year} / {layer}\n")
            if layer == "rl_control":
                text.append(_table(success.sort_values("path_id"), columns))
            else:
                chosen = pd.concat([success.nlargest(3, "indicative_return"), success.nsmallest(3, "indicative_return")]).drop_duplicates("path_id")
                text.append(_table(chosen, columns))
    text.extend(["## 按预测、风险和优化维度比较\n",
                 "FACTOR_MAIN_EFFECTS.csv 按固定合法单元等权汇总：31 个单预测器只比较 identity；融合只在相同成员组内比较；风险和优化在全部冻结预测流上报告边际作用。每项保留可运行数、失败数、正负数及有限指标数。边际均值混合了多个条件，不能单独解释为因果效应。\n",
                 "PAIRED_EFFECTS.csv 使用事前固定基准：predictor 对 ridge，组内 fusion 对 equal，risk 对 diagonal，optimizer 对 positive_equal。其余层固定，输出两侧原值和差值；失败参照不填零。target fusion 单列，并与同预测流／风险的独立 mean_variance 账户比较；REINFORCE／PPO 分别对同初始化 zero，明确列出现金和敞口变化。\n"])
    main_columns = ["year", "dimension", "within_group", "level", "legal_cells", "replayed_cells", "failed_cells", "indicative_return__mean", "indicative_max_drawdown__mean", "mean_gross_exposure__mean", "mean_cash_weight__mean", "total_fees__mean", "turnover__mean"]
    text.append(_table(main, main_columns))
    pair_counts = paired.groupby(["year", "family", "comparison_status"]).size().reset_index(name="contrasts") if len(paired) else pd.DataFrame()
    text.append(_table(pair_counts, list(pair_counts.columns)))
    text.extend(["## 条件交互作用\n",
                 "INTERACTIONS.csv 保存四个完整路径及 a1b1 − a0b1 − a1b0 + a0b0：预测器×风险、预测器×优化、融合×风险、融合×优化、风险×优化，以及成员组成×融合。最后一项改变整个成员组，不能解释为某个单成员的独立贡献。风险／优化仅通过账户和目标层作用，因此交互不自动等于预测学习提升。\n"])
    if len(interactions):
        for family, block in interactions.groupby("family", sort=True):
            rows = []
            for year, yearblock in block.groupby("year"):
                available = yearblock.loc[yearblock.comparison_status.eq("AVAILABLE")]
                row = dict(year=year, family=family, legal_four_cell_contrasts=len(yearblock),
                           available=len(available), unavailable=len(yearblock)-len(available))
                for metric in ["indicative_return", "indicative_max_drawdown", "mean_gross_exposure", "total_fees", "turnover"]:
                    finite = available[metric+"__delta"].dropna()
                    row[metric+"__mean_did"] = finite.mean() if len(finite) else np.nan
                    row[metric+"__min_did"] = finite.min() if len(finite) else np.nan
                    row[metric+"__max_did"] = finite.max() if len(finite) else np.nan
                rows.append(row)
            table = pd.DataFrame(rows)
            text.append(_table(table, list(table.columns)))
    text.extend(["这些账户共享日期、候选和预测，配对与交互大量重复使用单元；不能当作独立同分布样本，不提供虚假的显著性检验或多重比较后的冠军置信度。差值与 DID 均为描述性条件差异，其他更高阶条件可从全组合表复核。\n",
                 "## 原生预测与校准指标\n",
                 "PREDICTION_METRICS.csv 分开列分类 Brier／Logloss，原生分位 pinball／覆盖／交叉（另列排序修复诊断），高斯分布 NLL／尺度／80% 覆盖，以及各预测器和预测流的校准均值 MSE、偏差与每日 Spearman rank IC。主指标先在当日股票行内平均，再对日期等权；股票行等权值作为诊断同时保留。未成熟标签、价格质量警告、已知冲突、无预测与无常量可比较日都显式计数。仅评估当日 qualified 新买候选，held-only 83 行不当成新的选股候选。\n",
                 "原生分位中位数、方向概率和排序分数各有不同统计含义，不能直接把它们当作收益均值用 MSE 排一个总榜。分布尺度与 y_abs_next_open 的一日绝对收益代理也不能称为已经观测的多期限实现波动率。预测误差不作为本批重新选模型的依据。\n"])
    if len(prediction):
        summary = prediction.groupby(["year", "source", "statistic", "status"], dropna=False).agg(models=("model", "size"), mean_metric=("value", "mean"), min_valid_rows=("valid_rows", "min"), max_missing=("invalid_or_missing_predictions", "max")).reset_index()
        text.append(_table(summary, list(summary.columns)))
    text.append("## 失败、近似求解与审计\n")
    failed = combinations.loc[~combinations.replay_complete]
    if len(failed):
        failures = failed.groupby(["year", "research_status", "failure_reason"], dropna=False).size().reset_index(name="paths")
        text.append(_table(failures, list(failures.columns)))
    else:
        text.append("完整清单无未完成账户；全部负结果仍保留。\n")
    for year, frame in combinations.groupby("year"):
        target = frame.loc[frame.layer.eq("target_fusion")]
        if len(target) == 286 and not target.replay_complete.any():
            text.append(f"{year} 的 286 条 target_fusion 路径全部不可运行：all_outputs 的完整成员集合包含失败的 linear_q，不删该成员、不以其他预测替代。失败不是账户负收益，也不能按零收益并入绩效均值。\n")
    solver_columns = ["year", "research_status", "solver_statuses"]
    if "solver_statuses" in combinations:
        solver = combinations.groupby(solver_columns, dropna=False).agg(paths=("path_id", "size"), iteration_limit_decisions=("optimization_iteration_limit_decisions", "sum"), maximum_residual=("solver_max_proximal_residual", "max")).reset_index()
        text.append(_table(solver, list(solver.columns)))
    text.append("ITERATION_LIMIT 不是已认证最优解；达到迭代上限的路径与次数完整保留，不将其静默更名为收敛。公共账户守恒、日期、容量和逐账本核验收据见 audits 与各类别 DONE.json。预测→目标→订单→成交→费用→净值由 path_id／decision_id／signal_date／execution_date 连接。\n")
    if inventory is not None and len(inventory):
        text.append(_table(inventory, ["year", "category", "artifact", "rows"]))
    text.append("本批到事前清单为止。报告生成只读取冻结工件和评估结果，没有追加成员、种子、期限、融合权重或依据 2026 表现修改规则。\n")
    return "\n".join(text)


def analyze_completed_batch(output_dir=None):
    """The only file-reading analysis entry point. No learning APIs imported."""
    from freeze_batch import verify_freeze
    verify_freeze()
    output = Path(output_dir) if output_dir is not None else ROOT/"results/analysis"
    frames, inventory, hashes, pred_frames = {}, [], {}, []
    inputs = read_json(ROOT/"input_paths.json")
    for year in YEARS:
        folder = ROOT/"results"/f"evaluation_{year}"
        pred_folder = ROOT/"predictions"/f"evaluation_{year}"
        if not (folder/"COMPLETE.json").exists() or not (pred_folder/"COMPLETE.json").exists():
            raise RuntimeError(f"ALL_FROZEN_COMBINATIONS_MUST_COMPLETE_BEFORE_ANALYSIS:{year}")
        account_receipt = read_json(folder/"COMPLETE.json")
        if account_receipt.get("status") != "ALL_DECLARED_PATHS_RESOLVED" or account_receipt.get("declared") != EXPECTED_PER_YEAR:
            raise ValueError(f"INVALID_ACCOUNT_COMPLETION_RECEIPT:{year}")
        source = folder/"ALL_PATHS.csv"
        frame = pd.read_csv(source)
        hashes[str(source.resolve())] = sha(source)
        solvers = []
        for category in ["pto", "target_fusion", "rl_control"]:
            category_folder = folder/category
            solver_path = category_folder/"SOLVER_SUMMARY.csv"
            if solver_path.exists():
                selected = pd.read_csv(solver_path)
                if len(selected):
                    solvers.append(selected)
                hashes[str(solver_path.resolve())] = sha(solver_path)
            for name in ["daily", "positions", "orders", "fills", "execution_results", "contexts", "operational_actions", "optimization"]:
                ledger = category_folder/(name+".parquet")
                if ledger.exists():
                    inventory.append(dict(year=year, category=category, artifact=name, rows=pq.ParquetFile(ledger).metadata.num_rows))
        frame = attach_solver_evidence(frame, pd.concat(solvers, ignore_index=True) if solvers else pd.DataFrame())
        # Add the precise prediction-stage failure to the generic account reason.
        coverage = pd.read_csv(pred_folder/"STREAM_COVERAGE.csv")
        failure_map = coverage.set_index("stream_id").failure.fillna("").to_dict()
        frame["forecast_failure"] = (frame.group+"__"+frame.fusion).map(failure_map).fillna("")
        frame["failure_reason"] = frame.get("failure_reason", pd.Series("", index=frame.index)).fillna("")
        frames[year] = frame
        pred_receipt = read_json(pred_folder/"COMPLETE.json")
        failures = {**pred_receipt.get("base_failures", {}), **failure_map}
        prediction = {}
        for name in ["raw", "calibrated", "streams"]:
            file = pred_folder/(name+".parquet")
            prediction[name] = pd.read_parquet(file)
            hashes[str(file.resolve())] = sha(file)
        labels = load_evaluation_labels(year, inputs)
        pred_frames.append(prediction_metrics(**prediction, labels=labels, year=year, failures=failures))
    combined = validate_coverage(frames)
    main = factor_main_effects(combined)
    paired, interactions = build_effects(combined)
    prediction = pd.concat(pred_frames, ignore_index=True)
    gate = pd.read_parquet(inputs["full_gate"], columns=["current_frozen_status"])
    gate_counts = {str(k): int(v) for k, v in gate.current_frozen_status.value_counts().items()}
    if len(gate) != 111868 or gate_counts != {"QUALIFIED": 62393, "UNKNOWN": 47271, "PROVEN_INELIGIBLE": 2204}:
        raise ValueError("ORIGINAL_FULL_POOL_GATE_CHANGED")
    inventory = pd.DataFrame(inventory)
    output.mkdir(parents=True, exist_ok=True)
    products = {"ALL_COMBINATIONS.csv": combined, "FACTOR_MAIN_EFFECTS.csv": main,
                "PAIRED_EFFECTS.csv": paired, "INTERACTIONS.csv": interactions,
                "PREDICTION_METRICS.csv": prediction, "LEDGER_INVENTORY.csv": inventory}
    for name, frame in products.items():
        frame.to_csv(output/name, index=False)
    (output/"REPORT.md").write_text(render_report(combined, main, paired, interactions, prediction, gate_counts, inventory), encoding="utf-8")
    for source, expected in hashes.items():
        if sha(source) != expected:
            raise RuntimeError("ANALYSIS_INPUT_CHANGED_DURING_READ:"+source)
    verify_freeze()
    receipt = dict(status="COMPLETE_FIXED_ROSTER_DESCRIPTIVE_ANALYSIS", years=list(YEARS),
                   paths_per_year=EXPECTED_PER_YEAR, resolved_path_years=len(combined),
                   candidate_gate=gate_counts, main_rows=len(main), paired_rows=len(paired),
                   interaction_rows=len(interactions), prediction_metric_rows=len(prediction),
                   frozen_parameter_updates=0, seed_or_weight_searches=0, baselines=BASELINES,
                   source_sha256=hashes, outputs_sha256={p.name: sha(p) for p in output.iterdir() if p.is_file() and p.name != "ANALYSIS_RECEIPT.json"},
                   statistical_interpretation="descriptive, dependent cells; no IID inference or 2026 selection feedback")
    write_json(output/"ANALYSIS_RECEIPT.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT/"results/analysis")
    args = parser.parse_args()
    receipt = analyze_completed_batch(args.output_dir)
    print(json.dumps({"status": receipt["status"], "path_years": receipt["resolved_path_years"], "output": str(args.output_dir)}, ensure_ascii=False), flush=True)
