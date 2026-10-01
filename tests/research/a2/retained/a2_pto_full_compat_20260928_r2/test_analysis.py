"""Synthetic-only tests: no production panels, prices, or result files read."""
import math
import numpy as np
import pandas as pd
import pytest

from shared import paths
from analyze_results import (validate_coverage, factor_main_effects, build_effects,
                             reconstruct_next_open_labels, prediction_metrics,
                             attach_solver_evidence, render_report, METRICS)


def all_frames():
    roster = paths()
    frames = {}
    for year in [2025, 2026]:
        frame = roster.copy()
        frame["year"] = year
        frame["research_status"] = "REPLAY_COMPLETE"
        frame["failure_reason"] = ""
        for j, metric in enumerate(METRICS):
            frame[metric] = (np.arange(len(frame)) % 7 - 3) * .01 + j * .001
        failure = frame.members.str.split("|").map(lambda x: "linear_q" in x)
        frame.loc[failure, "research_status"] = "FAILED_PREDICTION_OR_FUSION"
        frame.loc[failure, "failure_reason"] = "linear_q LP fixed budget failed; no replacement"
        frame.loc[failure, METRICS] = np.nan
        frames[year] = frame
    return frames


def cell(group, risk, optimizer, value, fusion="identity", status="REPLAY_COMPLETE"):
    row = dict(year=2025, path_id=f"{group}__{fusion}__{risk}__{optimizer}",
               group=group, fusion=fusion, risk=risk, optimizer=optimizer,
               layer="pto", members=group, research_status=status,
               replay_complete=status == "REPLAY_COMPLETE", failure_reason="" if status == "REPLAY_COMPLETE" else "frozen member failed")
    for metric in METRICS:
        row[metric] = value if status == "REPLAY_COMPLETE" else np.nan
    return row


def test_exact_8194_each_year_and_failures_retained():
    combined = validate_coverage(all_frames())
    assert len(combined) == 16388
    assert combined.groupby("year").size().to_dict() == {2025: 8194, 2026: 8194}
    for year in [2025, 2026]:
        target = combined.loc[combined.year.eq(year) & combined.layer.eq("target_fusion")]
        assert len(target) == 286 and not target.replay_complete.any()
        assert target.indicative_return.isna().all()
    assert set(combined.result_sign) >= {"POSITIVE", "NEGATIVE", "FAILED_OR_UNRESOLVED"}
    main = factor_main_effects(combined)
    predictors = main.loc[main.dimension.eq("predictor")]
    assert predictors.groupby("year").size().eq(31).all()
    assert predictors.loc[predictors.level.eq("linear_q"), "failed_cells"].eq(52).all()


@pytest.mark.parametrize("damage", ["missing", "duplicate", "extra", "relabel", "year", "one_year"])
def test_coverage_rejects_every_structural_error(damage):
    frames = all_frames()
    if damage == "missing":
        frames[2026] = frames[2026].iloc[:-1]
    elif damage == "duplicate":
        frames[2026].loc[0, "path_id"] = frames[2026].loc[1, "path_id"]
    elif damage == "extra":
        frames[2026].loc[0, "path_id"] = "unregistered_search"
    elif damage == "relabel":
        frames[2026].loc[0, "risk"] = "future_risk"
    elif damage == "year":
        frames[2026].loc[0, "year"] = 2025
    else:
        frames.pop(2026)
    with pytest.raises(ValueError):
        validate_coverage(frames)


def test_four_cell_interaction_is_conditional_and_has_right_sign():
    frame = pd.DataFrame([cell("ridge", "diagonal", "positive_equal", .02),
                          cell("hgb", "diagonal", "positive_equal", .05),
                          cell("ridge", "sample", "positive_equal", .04),
                          cell("hgb", "sample", "positive_equal", .11)])
    paired, did = build_effects(frame)
    observed = did.loc[did.family.eq("predictor_x_risk")].iloc[0]
    assert observed.comparison_status == "AVAILABLE"
    assert observed["indicative_return__delta"] == pytest.approx(.11-.04-.05+.02)
    direct = paired.loc[paired.family.eq("predictor") & paired.risk.eq("sample")].iloc[0]
    assert direct["indicative_return__delta"] == pytest.approx(.11-.04)
    assert direct["mean_gross_exposure__delta"] == pytest.approx(.11-.04)
    assert direct["total_fees__delta"] == pytest.approx(.11-.04)
    assert {observed[k] for k in ["a1_b1_path_id", "a0_b1_path_id", "a1_b0_path_id", "a0_b0_path_id"]} == set(frame.path_id)


def test_failure_in_one_required_cell_never_imputed_as_zero():
    frame = pd.DataFrame([cell("ridge", "diagonal", "positive_equal", .02),
                          cell("hgb", "diagonal", "positive_equal", .05),
                          cell("ridge", "sample", "positive_equal", .04, status="FAILED_PREDICTION_OR_FUSION"),
                          cell("hgb", "sample", "positive_equal", .11)])
    paired, did = build_effects(frame)
    observed = did.loc[did.family.eq("predictor_x_risk")].iloc[0]
    assert observed.comparison_status == "UNAVAILABLE_REQUIRED_CELL"
    assert pd.isna(observed["indicative_return__delta"])
    assert observed.a0_b1_failure_reason == "frozen member failed"
    unavailable = paired.loc[paired.family.eq("predictor") & paired.risk.eq("sample")].iloc[0]
    assert pd.isna(unavailable["total_fees__delta"])


def test_target_and_rl_are_distinct_independent_account_contrasts():
    pto = cell("all_outputs", "diagonal", "mean_variance", .1, fusion="equal")
    rows = [pto]
    for method, value in [("target_equal", .08), ("target_median", .07)]:
        row = cell("all_outputs", "diagonal", method, value, fusion="equal")
        row["layer"] = "target_fusion"
        rows.append(row)
    for method, value in [("reinforce", .06), ("reinforce_zero", .02), ("ppo", .04), ("ppo_zero", .03)]:
        row = cell("rl", "implicit", method, value, fusion="none")
        row.update(layer="rl_control", path_id=method)
        rows.append(row)
    paired, _ = build_effects(pd.DataFrame(rows))
    target = paired.loc[paired.family.eq("target_fusion_vs_independent_mean_variance")]
    assert len(target) == 2
    assert target.loc[target.level.eq("target_equal"), "indicative_return__delta"].iloc[0] == pytest.approx(-.02)
    rl = paired.loc[paired.family.eq("rl_trained_vs_same_initialization_zero")]
    assert len(rl) == 2
    assert rl.loc[rl.level.eq("reinforce"), "indicative_return__delta"].iloc[0] == pytest.approx(.04)


def test_next_open_clock_maturity_and_shared_quality_conflicts():
    calendar = pd.to_datetime(["2026-02-24", "2026-02-25", "2026-02-26", "2026-02-27", "2026-03-02"])
    panel = pd.DataFrame({"signal_date": [calendar[0], calendar[1], calendar[2], calendar[-1]],
                          "ticker": ["OK", "GLW", "GLW", "OK"], "new_buy_eligible": True})
    prices = pd.DataFrame([(d, ticker, 100+10*i, False) for i, d in enumerate(calendar) for ticker in ["OK", "GLW"]],
                          columns=["trade_date", "ticker", "open", "price_quality_warning"])
    labels = reconstruct_next_open_labels(panel, prices, calendar,
                                          {(calendar[2], "GLW")}, {(calendar[2], "GLW"), (calendar[3], "GLW")})
    assert labels.loc[0, "y_next_open"] == pytest.approx(120/110-1)
    assert labels.loc[0, "execution_date"] == calendar[1] and labels.loc[0, "label_end_date"] == calendar[2]
    assert labels.loc[1, "label_unavailable_reason"] == "PRICE_MISSING_OR_QUALITY_WARNING"
    assert labels.loc[2, "label_unavailable_reason"] == "UNAVAILABLE_KNOWN_CONFLICT"
    assert labels.loc[3, "label_unavailable_reason"] == "LABEL_NOT_MATURE"
    assert labels.loc[1:, "y_next_open"].isna().all()
    altered = prices.copy()
    altered.loc[(altered.trade_date == calendar[0]) & altered.ticker.eq("OK"), "open"] = 9999
    rebuilt = reconstruct_next_open_labels(panel.iloc[:1], altered, calendar)
    assert rebuilt.y_next_open.iloc[0] == labels.y_next_open.iloc[0]


def test_native_metrics_date_weighting_invalid_scale_and_raw_crossing():
    dates = pd.to_datetime(["2025-01-02"]*2+["2025-01-03", "2025-01-06", "2025-01-07"])
    labels = pd.DataFrame({"signal_date": dates, "ticker": list("ABCDE"), "y_next_open": [.1, -.1, .2, np.nan, .3],
                           "label_available": [True, True, True, False, True], "new_buy_eligible": [True, True, True, True, False]})
    raw = labels[["signal_date", "ticker"]].copy()
    raw["r__raw"] = 0.
    raw["p__p"] = [.8, .2, .5, .9, .9]
    raw["q__q10"], raw["q__q50"], raw["q__q90"] = 0., -.1, .3
    raw["d__location"], raw["d__scale"] = 0., [.1, .1, 0, .1, .1]
    calibrated = raw[["signal_date", "ticker"]].copy()
    for name in ["r", "p", "q", "d", "failed"]:
        calibrated[name+"__mu"] = 0. if name != "failed" else np.nan
        calibrated[name+"__uncertainty"] = .1
    calibrated["p__calibrated_p"] = raw["p__p"]
    streams = calibrated[["signal_date", "ticker"]].copy()
    streams["r__identity"] = 0.
    metrics = prediction_metrics(raw, calibrated, streams, labels, 2025,
                                 predictors=["r", "p", "q", "d", "failed"],
                                 families={"point": ["r", "failed"], "probability": ["p"], "quantile": ["q"], "distribution": ["d"]},
                                 failures={"failed": "fixed declared member failed"})
    def result(source, model, statistic):
        return metrics.loc[metrics.source.eq(source) & metrics.model.eq(model) & metrics.statistic.eq(statistic)].iloc[0]
    mse = result("calibrated_mean", "r", "mse")
    assert mse.value == pytest.approx((.01+.04)/2)
    assert mse.row_weighted_value == pytest.approx(.06/3)
    assert mse.candidate_keys == 4 and mse.valid_rows == 3 and mse.excluded_unmatured_or_bad_label == 1
    brier = result("native_probability", "p", "brier")
    assert brier.value == pytest.approx((.04+.25)/2)
    assert result("native_quantile", "q", "crossing_rate").value == 1.
    nll = result("native_gaussian_distribution", "d", "gaussian_nll")
    assert nll.valid_rows == 2 and nll.invalid_or_missing_predictions == 1
    assert nll.value == pytest.approx(math.log(.1)+.5+.5*math.log(2*math.pi))
    failure = result("calibrated_mean", "failed", "mse")
    assert failure.status == "FAILED_OR_NO_VALID_OBSERVATIONS" and pd.isna(failure.value)
    constant = result("calibrated_mean", "r", "rank_ic")
    assert constant.valid_days == 0 and constant.constant_or_too_small_days == 2


def test_solver_iteration_limit_is_visible_and_report_contains_limits():
    combined = validate_coverage(all_frames())
    part = combined.loc[combined.year.eq(2025)].copy()
    solver = pd.DataFrame([dict(path_id=part.path_id.iloc[0], status="ITERATION_LIMIT", decisions=2, maximum_residual=.2, iterations=40)])
    enriched = attach_solver_evidence(part, solver)
    assert enriched.solver_statuses.iloc[0] == "ITERATION_LIMIT" and enriched.solver_decisions.iloc[0] == 2
    main = factor_main_effects(combined)
    paired, did = build_effects(combined)
    assert len(paired) > 30000 and len(did) == 45704
    unavailable_targets = paired.loc[paired.family.eq("target_fusion_vs_independent_mean_variance")]
    assert len(unavailable_targets) == 572 and unavailable_targets.comparison_status.eq("UNAVAILABLE_REQUIRED_CELL").all()
    report = render_report(combined, main, paired, did, pd.DataFrame(),
                           {"QUALIFIED": 62393, "UNKNOWN": 47271, "PROVEN_INELIGIBLE": 2204})
    for phrase in ["16388", "62392", "BLOCKED_DATA", "linear_q", "286", "不提供虚假的显著性", "现金", "费用", "换手"]:
        assert phrase in report
