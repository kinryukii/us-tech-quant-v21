"""Prediction target semantics, fixed parameters and temporal sample checks."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

import common
import predictions_train as training


def frame(dates, ends):
    rows = pd.DataFrame(np.zeros((len(dates), len(common.FEATURES))), columns=common.FEATURES)
    rows["signal_date"] = pd.to_datetime(dates)
    rows["label_end_date"] = pd.to_datetime(ends)
    rows["ticker"] = [f"T{number}" for number in range(len(dates))]
    rows["label_available"] = True
    rows["new_buy_eligible"] = True
    rows["y_next_open"] = .01
    return rows


def test_sample_excludes_unmature_and_future_rows():
    rows = frame(["2023-12-27", "2023-12-29", "2024-01-02", "2023-07-03"],
                 ["2023-12-29", "2024-01-03", "2024-01-04", "2023-07-05"])
    rows.loc[3, "new_buy_eligible"] = False
    chosen = training.sample_stage(rows, "development")
    assert chosen.ticker.tolist() == ["T0"]
    assert chosen.label_end_date.lt(common.CUTOFFS["development"]).all()


def test_every_native_optional_parameter_is_strict_json_safe():
    for member in common.MEMBERS:
        model = training.estimator(member, .1 if member in common.QUANTILES else None)
        if hasattr(model, "get_params"):
            parameters = training.json_parameter({key:value for key,value in model.get_params(deep=False).items()
                if value is None or isinstance(value, (str, bool, int, float, np.generic))})
            json.dumps(parameters, allow_nan=False)
    sentinel = training.json_parameter({"missing":float("nan")})
    assert sentinel["missing"] == {"native_nonfinite_parameter":"nan"}


def test_fixed_budget_and_native_loss_contracts():
    assert training.MEMBERS == common.MEMBERS and len(training.MEMBERS) == 31
    assert training.estimator("ridge")[-1].alpha == 10
    assert training.estimator("elastic")[-1].l1_ratio == .5
    assert training.estimator("huber")[-1].max_iter == 1000
    for member in ["rf", "et", "prob_rf"]:
        params = training.estimator(member).get_params()
        assert (params["n_estimators"], params["max_depth"], params["min_samples_leaf"]) == (64, 6, 50)
    for member in ["hgb", "prob_hgb", "quant_hgb"]:
        params = training.estimator(member, .1 if member == "quant_hgb" else None).get_params()
        assert params["max_iter"] == 80 and params["max_depth"] == 3
        assert params["early_stopping"] is False
    for member in ["mlp", "resnet", "ft_transformer", "prob_mlp", "quant_mlp", "dist_mlp"]:
        model = training.estimator(member, .1 if member == "quant_mlp" else None)
        assert model.epochs == 8 and model.batch_size == 1024 and model.seed == common.SEED


class FakeProbability:
    def predict_proba(self, values):
        p = np.array([.25, .75])[:len(values)]
        return np.column_stack([1.-p, p])


class FakePoint:
    def __init__(self, value):
        self.value = value

    def predict(self, values):
        return np.full(len(values), self.value)


def test_probabilities_need_both_event_amplitudes():
    rows = frame(["2024-01-02", "2024-01-03"], ["2024-01-04", "2024-01-05"])
    result = training.predict_payload({"member":"prob_logistic", "models":[FakeProbability()],
        "positive_amplitude":.01, "nonpositive_amplitude":-.02}, rows)
    np.testing.assert_allclose(result.mu, [-.0125, .0025])
    np.testing.assert_array_equal(result.p_up, [.25, .75])


def test_quantiles_and_ranks_never_fabricate_mean_returns():
    rows = frame(["2024-01-02", "2024-01-03"], ["2024-01-04", "2024-01-05"])
    result = training.predict_payload({"member":"quant_hgb", "models":[
        FakePoint(-.1), FakePoint(.02), FakePoint(.1)]}, rows)
    assert result.mu.isna().all() and result.q50.eq(.02).all()
    rank = training.predict_payload({"member":"rank_xgb", "models":[FakePoint(7.)]}, rows)
    assert rank.mu.isna().all() and rank.rank_score.eq(7.).all()


def test_completed_full_delivery_has_93_temporal_receipts_and_62_typed_oof_files():
    """Run after training, before the parent freezes any 2026 inference."""
    source_hash = training.sha(common.DATA_SOURCE)
    source = training.source_frame(common.DATA_SOURCE)
    key_sets = {stage:source.loc[source.signal_date.dt.year.eq(year), ["signal_date", "ticker"]]
        .reset_index(drop=True) for stage,year in training.PREDICTION_YEAR.items()}
    receipts, predictions, estimator_fits = 0, 0, 0
    probability_roundoff = []
    for stage,cutoff in common.CUTOFFS.items():
        expected_keys = training.sample_stage(source, stage)[["signal_date", "ticker", "label_end_date"]]
        pd.testing.assert_frame_equal(pd.read_parquet(training.MODELS/f"sample_keys_{stage}.parquet"), expected_keys)
        for member in common.MEMBERS:
            path = training.MODELS/member/f"{stage}_RECEIPT.json"
            receipt = json.loads(path.read_text(encoding="utf-8"))
            assert receipt["status"] == "PASS"
            assert receipt["features"] == common.FEATURES
            assert receipt["seed"] == common.SEED
            assert receipt["source_sha256"] == source_hash
            assert receipt["target"] == "y_next_open"
            assert receipt["horizon"] == "next_open_to_following_open_1_session"
            assert receipt["return_clip"] == [-.2, .2]
            assert receipt["fit_2026_rows"] == receipt["prediction_2026_rows"] == 0
            assert receipt["hyperparameter_search_count"] == 0
            assert pd.Timestamp(receipt["train_signal_max"]) < pd.Timestamp(cutoff)
            assert pd.Timestamp(receipt["train_label_end_max"]) < pd.Timestamp(cutoff)
            assert receipt["train_rows"] == len(expected_keys)
            assert training.sha(receipt["artifact"]) == receipt["artifact_sha256"]
            assert training.sha(receipt["sample_keys_path"]) == receipt["sample_keys_sha256"]
            assert receipt["estimator_fit_count"] == (3 if member in common.QUANTILES else 1)
            for diagnostic in receipt["diagnostics"]:
                if "epochs" in diagnostic:
                    assert diagnostic["epochs"] == 8
                    assert diagnostic["optimizer_steps"] == 8*int(np.ceil(len(expected_keys)/1024))
                if "trained_boosting_rounds" in diagnostic:
                    assert diagnostic["trained_boosting_rounds"] == 80
            receipts += 1
            estimator_fits += receipt["estimator_fit_count"]
            if stage == "final":
                assert receipt["prediction"] is None
                continue
            prediction = receipt["prediction"]
            assert training.sha(prediction["path"]) == prediction["sha256"]
            values = pd.read_parquet(prediction["path"])
            pd.testing.assert_frame_equal(values[["signal_date", "ticker"]], key_sets[stage])
            assert not values.duplicated(["signal_date", "ticker"]).any()
            assert values.prediction_status.eq("PREDICTED").all()
            relevant = (["q10", "q50", "q90"] if member in common.QUANTILES else
                ["rank_score"] if member in common.RANKERS else ["mu", "p_up"]
                if member in common.CLASSIFIERS else ["mu", "sigma"]
                if member in common.DISTRIBUTIONS else ["mu"])
            assert np.isfinite(values[relevant].to_numpy(float)).all()
            if member in common.QUANTILES or member in common.RANKERS:
                assert values.mu.isna().all()
            if member in common.DISTRIBUTIONS:
                assert values.sigma.gt(0).all()
            if member in common.CLASSIFIERS:
                assert values.p_up.between(0, 1).all()
                native_dtype = np.dtype("float64")
                if member == "prob_xgb":
                    # Native XGB probabilities and their original amplitude
                    # arithmetic are float32, even though parquet columns were
                    # initialized as float64. Do not rewrite committed output
                    # to make an incorrectly float64-only test pass.
                    model = training.load_payload(member, stage)["models"][0]
                    probe = source.loc[source.signal_date.dt.year.eq(training.PREDICTION_YEAR[stage])].iloc[:4]
                    native_dtype = model.predict_proba(probe[common.FEATURES].to_numpy(float)).dtype
                    assert native_dtype == np.dtype("float32")
                # Eight native epsilons bound the rounded scalar casts,
                # products, subtraction and addition in p*a + (1-p)*b.
                roundoff_bound = 8*np.finfo(native_dtype).eps*(abs(receipt["positive_amplitude"])
                    +abs(receipt["nonpositive_amplitude"]))
                mapped = values.p_up*receipt["positive_amplitude"]+(1-values.p_up)*receipt["nonpositive_amplitude"]
                np.testing.assert_allclose(values.mu, mapped, rtol=0, atol=roundoff_bound)
                probability_roundoff.append({"member":member, "stage":stage,
                    "native_dtype":str(native_dtype), "max_absolute_difference":float(np.max(np.abs(values.mu-mapped))),
                    "arithmetic_roundoff_bound":float(roundoff_bound)})
            predictions += 1
    assert (receipts, predictions, estimator_fits) == (93, 62, 129)
    paused = json.loads((common.ROOT/"PAUSED.json").read_text(encoding="utf-8"))
    checked_preserved = []
    for relative,digest in paused["artifact_sha256"].items():
        if relative.startswith(("models/base/", "predictions/base/")):
            assert training.sha(common.ROOT/relative) == digest
            checked_preserved.append(relative)
    training.write_json(training.MODELS/"VERIFICATION.json", {"status":"PASS",
        "member_stage_receipts":receipts, "oof_prediction_files":predictions,
        "completed_estimator_fits":estimator_fits, "fit_2026_rows":0,
        "prediction_2026_rows":0, "source_sha256":source_hash,
        "preserved_pause_snapshot_files":len(checked_preserved),
        "probability_amplitude_roundoff":probability_roundoff,
        "code_sha256":{name:training.sha(common.ROOT/name) for name in ["predictions_train.py", "nn_models.py"]}})
