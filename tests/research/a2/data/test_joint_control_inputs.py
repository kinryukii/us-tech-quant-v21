"""Synthetic missing-key/maturity/identity checks; no real model/data readers."""
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.data.joint_control_inputs import infer_missing_raw_keys
from scripts.research.a2.data.joint_input_binding import FEATURES

class Model:
    def predict(self,x):return x[:,0]*2

def inputs():
    held=pd.DataFrame({"signal_date":pd.to_datetime(["2023-01-03"]*3),"ticker":["A","B","C"]})
    for name in FEATURES:held[name]=[1.,2.,3.]
    raw=pd.DataFrame({"signal_date":pd.to_datetime(["2023-01-03"]*2),"ticker":["A","B"],"a2_prediction":[7.,np.nan]})
    manifest={"contract":{"year":2023,"feature_columns":list(FEATURES),"train_end":"2022-12-01","labelmax":"2022-12-30","prediction_min_date":"2023-01-03"}}
    return held,raw,manifest

def test_existing_key_and_even_nonfinite_forecast_are_never_replaced():
    held,raw,manifest=inputs();before=raw.copy()
    out=infer_missing_raw_keys(held,raw,Model(),manifest)
    assert out.ticker.tolist()==["C"] and out.a2_prediction.tolist()==[6.]
    assert out.raw_uncertainty.tolist()==[0.]
    pd.testing.assert_frame_equal(raw,before)

@pytest.mark.parametrize("field",["train_end","labelmax"])
def test_exact_cutoff_training_or_labels_rejected(field):
    held,raw,manifest=inputs();manifest["contract"][field]="2023-01-01"
    with pytest.raises(ValueError,match="MATURITY"):
        infer_missing_raw_keys(held,raw,Model(),manifest)

def test_future_content_rejected_before_model_prediction():
    held,raw,manifest=inputs();held.loc[2,"signal_date"]=pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError,match="TEST_CONTENT"):
        infer_missing_raw_keys(held,raw,Model(),manifest)

def test_identity_and_duplicate_guards_do_not_infer_from_column_names_alone():
    held,raw,manifest=inputs();manifest["contract"]["feature_columns"]=list(reversed(FEATURES))
    with pytest.raises(ValueError,match="IDENTITY"):
        infer_missing_raw_keys(held,raw,Model(),manifest)
    held,raw,manifest=inputs();held=pd.concat([held,held.iloc[:1]],ignore_index=True)
    with pytest.raises(ValueError,match="DUPLICATE"):
        infer_missing_raw_keys(held,raw,Model(),manifest)


class NoPredict:
    def predict(self, x):
        raise AssertionError("invalid or empty domain must not reach prediction")


@pytest.mark.parametrize("table", ["held", "raw"])
@pytest.mark.parametrize("field,value", [
    ("signal_date", pd.NaT), ("signal_date", "invalid"),
    ("signal_date", pd.Timestamp("2023-01-03 12:00:00")),
    ("signal_date", pd.Timestamp("2023-01-03", tz="UTC")),
    ("ticker", None), ("ticker", np.nan), ("ticker", ""),
    ("ticker", " A"), ("ticker", 3),
])
def test_invalid_keys_fail_before_prediction(table, field, value):
    held, raw, manifest = inputs()
    frame = held if table == "held" else raw
    frame[field] = frame[field].astype(object)
    frame.loc[0, field] = value
    with pytest.raises(ValueError, match="INVALID_RAW_CONTROL"):
        infer_missing_raw_keys(held, raw, NoPredict(), manifest)


@pytest.mark.parametrize("field", ["train_end", "labelmax", "prediction_min_date"])
def test_missing_manifest_clock_is_never_assumed_legal(field):
    held, raw, manifest = inputs()
    manifest["contract"][field] = None
    with pytest.raises(ValueError, match="INVALID_RAW_MANIFEST_DATE"):
        infer_missing_raw_keys(held, raw, NoPredict(), manifest)


def test_duplicate_keys_are_checked_after_date_normalization():
    held, raw, manifest = inputs()
    raw = pd.concat([raw.iloc[:1], raw.iloc[:1]], ignore_index=True)
    raw["signal_date"] = ["2023-01-03", "2023-01-03 00:00:00"]
    with pytest.raises(ValueError, match="DUPLICATE"):
        infer_missing_raw_keys(held, raw, NoPredict(), manifest)


def test_predeployment_same_year_keys_are_excluded_without_future_filter():
    held, raw, manifest = inputs()
    early = held.iloc[2:3].copy()
    early["signal_date"] = pd.Timestamp("2023-01-02")
    held = pd.concat([early, held], ignore_index=True)
    out = infer_missing_raw_keys(held, raw, Model(), manifest)
    assert out.signal_date.tolist() == [pd.Timestamp("2023-01-03")]
    assert out.ticker.tolist() == ["C"]


def test_empty_missing_domain_does_not_call_model():
    held, raw, manifest = inputs()
    out = infer_missing_raw_keys(held.iloc[:2], raw, NoPredict(), manifest)
    assert out.empty


@pytest.mark.parametrize("bad", [np.array([np.nan]), np.ones((1, 1))])
def test_invalid_prediction_shape_or_value_is_rejected(bad):
    class BadModel:
        def predict(self, x): return bad
    held, raw, manifest = inputs()
    with pytest.raises(ValueError, match="INFERENCE_OUTPUT"):
        infer_missing_raw_keys(held, raw, BadModel(), manifest)
