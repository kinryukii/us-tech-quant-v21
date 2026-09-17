"""Synthetic boundary/metric checks only: every estimator fit is forbidden."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SOURCE = Path(__file__).with_name("modeling.py")
SPEC = importlib.util.spec_from_file_location("fast3_bounded_modeling_tests", SOURCE)
modeling = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(modeling)


@pytest.fixture(autouse=True)
def forbid_all_fitting(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("No actual or toy estimator fitting is allowed in these tests")
    for cls in (modeling.LogisticRegression, modeling.HistGradientBoostingClassifier,
                modeling.SimpleImputer, modeling.StandardScaler, modeling.Pipeline,
                modeling.FitRecorder):
        monkeypatch.setattr(cls, "fit", forbidden)


@pytest.fixture
def config():
    return {**deepcopy(modeling.FIXED_CONFIG), "candidate_ids": [x["id"] for x in modeling.CANDIDATES],
            "candidate_contract": deepcopy(modeling.CANDIDATE_CONTRACT),
            "feature_columns": ["pm_return", "lag_return"], "baseline_columns": ["market_return", "pit_sector_3674"]}


def make_panel(years=(2020, 2021), days=125):
    rows = []
    for year in years:
        for value in pd.bdate_range(f"{year}-01-01", periods=days):
            date = value.strftime("%Y-%m-%d")
            for ticker, ret in (("NVDA", 0.01), ("AMD", -0.01)):
                prediction = pd.Timestamp(date + " 09:25", tz="America/New_York").tz_convert("UTC")
                end = pd.Timestamp(date + " 12:30", tz="America/New_York").tz_convert("UTC")
                rows.append({"sample_id": date + "_" + ticker, "date": date, "ticker": ticker,
                    "prediction_at_utc": prediction, "label_end_utc": end,
                    "label_available_at_utc": end + pd.Timedelta(minutes=1), "return_3h": ret,
                    "y": int(ret > 0), "sector": "3674", "pm_return": np.nan, "lag_return": 0.01,
                    "market_return": 0.002, "pit_sector_3674": 1.0})
    return pd.DataFrame(rows)


def test_folds_group_complete_dates_and_expand(config):
    frame = modeling._validated_panel(make_panel(range(2020, 2026)), config)
    counts = []
    for year in range(2021, 2026):
        train, validation, detail = modeling._fold(frame, year)
        assert detail["status"] == "ELIGIBLE"
        assert not set(train.date) & set(validation.date)
        assert set(validation.date) == set(frame.loc[frame.date.str.startswith(str(year)), "date"])
        assert modeling._maturity(train).max() < validation.prediction_at_utc.min()
        assert validation.groupby("date").ticker.nunique().eq(2).all()
        counts.append(train.date.nunique())
    assert counts == [125, 250, 375, 500, 625]


def test_maturity_is_strict_and_uses_available_time(config):
    raw = make_panel()
    first = raw.loc[raw.date.str.startswith("2021"), "prediction_at_utc"].min()
    delayed_id = raw.iloc[0].sample_id
    raw.loc[0, "label_available_at_utc"] = first
    frame = modeling._validated_panel(raw, config)
    train, validation, detail = modeling._fold(frame, 2021)
    assert delayed_id not in set(train.sample_id)
    assert detail["purged_unmatured_rows"] == 1
    assert frame.loc[frame.sample_id.eq(delayed_id), "label_end_utc"].iloc[0] < first
    assert modeling._maturity(train).max() < first


def test_maturity_falls_back_to_endpoint_for_older_interface(config):
    frame = modeling._validated_panel(make_panel().drop(columns="label_available_at_utc"), config)
    train, validation, _ = modeling._fold(frame, 2021)
    pd.testing.assert_series_equal(modeling._maturity(train), train.label_end_utc)
    assert train.label_end_utc.max() < validation.prediction_at_utc.min()


def test_latest_2025_final_training_is_legal_without_fitting(config):
    frame = make_panel((2025,), days=1)
    for column, local_time in (("prediction_at_utc", "09:25"), ("label_end_utc", "12:30"), ("label_available_at_utc", "12:31")):
        frame[column] = pd.Timestamp("2025-12-31 " + local_time, tz="America/New_York").tz_convert("UTC")
    frame["date"] = "2025-12-31"
    frame["sample_id"] = frame.date + "_" + frame.ticker
    validated = modeling._validated_panel(frame, config)
    final = modeling._final_training(validated)
    assert len(final) == 2
    assert final.label_end_utc.eq(pd.Timestamp("2025-12-31T17:30:00Z")).all()
    assert final.label_available_at_utc.eq(pd.Timestamp("2025-12-31T17:31:00Z")).all()
    delayed = validated.copy()
    delayed.loc[delayed.index[0], "label_available_at_utc"] = modeling.CUTOFF
    assert len(modeling._final_training(delayed)) == 1
    with pytest.raises(ValueError, match="label_available_at_utc"):
        modeling._validated_panel(delayed, config)


@pytest.mark.parametrize("field,operation", [
    ("date", lambda frame: "2026-01-01"),
    ("label_available_at_utc", lambda frame: frame.label_end_utc.iloc[0] - pd.Timedelta(seconds=1)),
    ("label_end_utc", lambda frame: frame.label_end_utc.iloc[0] + pd.Timedelta(minutes=1)),
    ("prediction_at_utc", lambda frame: frame.prediction_at_utc.iloc[0] + pd.Timedelta(minutes=1)),
])
def test_cutoff_and_fixed_prediction_target_times_rejected(config, field, operation):
    frame = make_panel((2025,), 1)
    frame.loc[0, field] = operation(frame)
    with pytest.raises(ValueError):
        modeling._validated_panel(frame, config)


def weighted_fixture():
    return pd.DataFrame({"sample_id": ["a", "b", "c", "d"], "ticker": ["A", "A", "B", "C"],
        "date": ["2025-01-02", "2025-01-03", "2025-01-03", "2025-01-03"],
        "y": [1, 0, 0, 0], "return_3h": [0.01, -0.01, 0.0, -0.02]})


def test_metrics_and_training_weights_give_days_equal_influence():
    frame = weighted_fixture()
    weight = modeling._weights(frame)
    assert np.isclose(weight.mean(), 1)
    assert np.isclose(weight[0], weight[1:].sum())
    report = modeling.aggregate_metrics(frame, np.full(4, 0.9))
    expected_loss = (-np.log(0.9) - np.log(0.1)) / 2
    assert report["log_loss"] == pytest.approx(expected_loss)
    assert report["accuracy"] == 0.5
    assert report["brier"] == pytest.approx(0.41)
    assert report["dates"] == 2 and report["rows"] == 4
    assert report["flat_rows"] == 1 and report["strict_down_rows"] == 2
    assert report["same_day_auc"] is None and report["same_day_auc_eligible_dates"] == 0


def test_prior_probability_is_day_weighted_and_complement_includes_flats():
    frame = weighted_fixture()
    probability = modeling._historical_prior_probability(frame)
    assert probability == 0.5 and probability != frame.y.mean()
    bundle = {"model": {"kind": "historical_prior", "probability_up": probability},
              "feature_columns": [], "selected_candidate": "historical_prior"}
    prediction = modeling.predict_model(bundle, frame)
    assert prediction.probability_up.eq(0.5).all()
    assert prediction.probability_not_up.eq(0.5).all()
    assert "probability_down" not in prediction and "strict_down_probability" not in prediction
    assert prediction.predicted_up_at_0_5.all()


def test_reliability_fixed_bins_include_zero_and_one():
    frame = weighted_fixture()
    report = modeling._reliability(frame, np.array([0.0, 0.1, 0.9, 1.0]), "fixed")
    assert len(report) == 10 and sum(row["rows"] for row in report) == 4
    assert report[0]["rows"] == 1 and report[1]["rows"] == 1 and report[9]["rows"] == 2
    assert report[-1]["upper_inclusive"] is True


def test_insufficient_years_are_kept_and_later_year_is_possible(config):
    frame = modeling._validated_panel(make_panel((2023, 2024, 2025)), config)
    assert modeling._fold(frame, 2022)[2]["status"] == "SKIPPED_INSUFFICIENT_HISTORY"
    assert modeling._fold(frame, 2023)[2]["status"] == "SKIPPED_INSUFFICIENT_HISTORY"
    assert modeling._fold(frame, 2024)[2]["status"] == "ELIGIBLE"
    assert modeling._fold(frame, 2025)[2]["status"] == "ELIGIBLE"


def test_bootstrap_uses_dates_and_is_reproducible():
    rows = []
    for date in pd.bdate_range("2025-01-01", periods=60).strftime("%Y-%m-%d"):
        for name, loss in (("selected", 0.5), ("historical_prior", 0.7), ("market_sector_logit", 0.6)):
            rows.append({"date": date, "model": name, "log_loss": loss})
    daily = pd.DataFrame(rows)
    left, right = modeling.paired_comparison(daily), modeling.paired_comparison(daily)
    assert left == right
    assert all(row["paired_dates"] == 60 and row["replicates"] == 1000 for row in left)
    assert left[0]["ci_95_upper"] == pytest.approx(-0.2)
    assert left[1]["ci_95_lower"] == pytest.approx(-0.1)


def test_frozen_config_and_maximum_count_have_no_inner_baseline_fits(config):
    modeling._validate_config(config)
    inner_pairs = set()
    total = 0
    for outer_year in (2022, 2023, 2024, 2025):
        for year in range(2021, outer_year):
            inner_pairs.update((year, spec["id"]) for spec in modeling.CANDIDATES)
        total += 1 + len(modeling.BASELINES)
    inner_pairs.update((year, spec["id"]) for year in range(2021, 2026) for spec in modeling.CANDIDATES)
    total += len(inner_pairs) + 1 + len(modeling.BASELINES)
    assert len(inner_pairs) == 20 and total == modeling.FIT_BUDGET["maximum_total"] == 35
    assert modeling.FIT_BUDGET["baseline_inner"] == 0
    assert sum(value for key, value in modeling.FIT_BUDGET.items() if key != "maximum_total") == 35


@pytest.mark.parametrize("change", ["candidate_order", "extra_candidate", "parameter", "extra_parameter", "seed", "years"])
def test_config_mismatch_rejected_before_output_or_fitting(config, tmp_path, change):
    if change == "candidate_order": config["candidate_ids"].reverse()
    elif change == "extra_candidate": config["candidate_ids"].append("hidden_candidate")
    elif change == "parameter": config["candidate_contract"]["logit_C"] = [0.01, 1]
    elif change == "extra_parameter": config["candidate_contract"]["extra_trial"] = True
    elif change == "seed": config["seed"] += 1
    else: config["outer_years"] = [2025]
    target = tmp_path / "forbidden_output"
    with pytest.raises(ValueError, match="configuration mismatch"):
        modeling.train_research(pd.DataFrame(), config, target)
    assert not target.exists()


@pytest.mark.parametrize("column", ["open_price", "price_12_30", "flat", "label_available_at_utc", "unknown_feature"])
def test_label_metadata_and_unapproved_prefixes_cannot_enter_features(config, column):
    frame = make_panel((2025,), 1)
    if column not in frame: frame[column] = 1.0
    config["feature_columns"] = [column]
    with pytest.raises(ValueError, match="feature_columns"):
        modeling._validated_panel(frame, config)


def test_four_estimators_construct_exactly_frozen_specs_without_fitting():
    assert modeling.CANDIDATE_CONTRACT["logit_C"] == [0.1, 1]
    assert modeling.CANDIDATE_CONTRACT["hgb_max_leaf_nodes"] == [7, 15]
    for spec in modeling.CANDIDATES:
        estimator = modeling._make_model(spec)
        if spec["family"] == "logistic":
            assert estimator.named_steps["model"].C == spec["C"]
            assert estimator.named_steps["model"].max_iter == 1500
            assert estimator.named_steps["imputer"].keep_empty_features is True
            assert estimator.named_steps["imputer"].add_indicator is True
        else:
            assert estimator.max_leaf_nodes == spec["max_leaf_nodes"]
            assert estimator.max_iter == 150 and estimator.early_stopping is False
            assert estimator.learning_rate == 0.05 and estimator.l2_regularization == 10
            assert estimator.min_samples_leaf == 40


def test_code_candidate_drift_cannot_silently_ignore_config(config, monkeypatch):
    altered = deepcopy(list(modeling.CANDIDATES))
    altered[0]["C"] = 0.01
    monkeypatch.setattr(modeling, "CANDIDATES", tuple(altered))
    with pytest.raises(ValueError, match="code candidate specification drift"):
        modeling._validate_config(config)
