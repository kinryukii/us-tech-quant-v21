import pandas as pd
import pytest
from scripts.research.a2.evaluation.joint_method_coverage import (
    mature_training_mask, prior_oof_rows, date_weights,
)

def test_labels_crossing_cutoff_are_purged_and_trade_flag_independent():
    f = pd.DataFrame({
        "signal_date": pd.to_datetime(["2022-12-20", "2022-12-29"]),
        "execution_date": pd.to_datetime(["2022-12-21", "2022-12-30"]),
        "label_end_date": pd.to_datetime(["2022-12-29", "2023-01-09"]),
        "label_mature_date": pd.to_datetime(["2022-12-29", "2023-01-09"]),
        "fit_eligible": [True, True], "trade_eligible": [True, True],
        "y_open5": [.01, .02],
    })
    assert mature_training_mask(f, "2023-01-01").tolist() == [True, False]
    assert f.trade_eligible.tolist() == [True, True]
    with pytest.raises(ValueError, match="boundary"):
        mature_training_mask(f, "2027-01-01")

def test_calibration_excludes_unmatured_and_in_sample_predictions():
    f = pd.DataFrame({
        "signal_date": pd.to_datetime(["2022-01-03", "2022-01-03", "2022-12-30"]),
        "source_fit_cutoff": pd.to_datetime(["2022-01-01", "2023-01-01", "2022-01-01"]),
        "label_mature_date": pd.to_datetime(["2022-01-11", "2022-01-11", "2023-01-10"]),
        "label_end_date": pd.to_datetime(["2022-01-11", "2022-01-11", "2023-01-10"]),
        "fit_eligible": [True, True, True], "Ridge_raw": [.1, .1, .1],
        "y_open5": [.01, .01, .01],
    })
    result = prior_oof_rows(f, "2023-01-01", "Ridge_raw")
    assert result.index.tolist() == [0]

def test_date_equal_weights_do_not_overweight_large_cross_section():
    f = pd.DataFrame({"signal_date": pd.to_datetime(["2022-01-03"]*3+["2022-01-04"])})
    f["w"] = date_weights(f)
    sums = f.groupby("signal_date").w.sum()
    assert sums.iloc[0] == pytest.approx(sums.iloc[1])

from scripts.research.a2.evaluation.joint_method_stages import asof_exposures

def test_industry_exposure_requires_available_at_signal_and_before_cutoff():
    f = pd.DataFrame({
        "decision_date": ["2023-12-29"]*3,
        "ticker_at_date": ["A", "B", "C"],
        "sic_available_at": ["2023-12-29T20:00Z", "2023-12-29T22:00Z", "2024-01-02T00:00Z"],
        "identity_status": ["AUTHORITATIVE"]*3,
        "taxonomy_status": ["STRICT_PIT_SIC_FF12_FF48_MAPPED"]*3,
        "sic_source_sha256": ["source"]*3, "ff48_code": [1, 2, 3],
    })
    result = asof_exposures("INDUSTRY", f, "2024-01-01")
    assert result.index.tolist() == ["A"]
    assert result.attrs["pit_qualified"] is True

def test_fundamental_requires_all_three_availability_gates():
    f = pd.DataFrame({
        "ticker": ["A", "B", "C"],
        "accepted_datetime": ["2023-12-20T20:00Z"]*3,
        "feature_effective_date": ["2023-12-21", "2024-01-02", "2023-12-21"],
        "mapping_effective_date": ["2023-12-21", "2023-12-21", "2024-01-02"],
        "coverage_status": [True]*3, "corporate_action_scale_consistent": [True]*3,
        "mapping_confidence": ["A_EXISTING_AUDITED"]*3,
        "mapping_source": ["source"]*3, "accepted_source_sha256": ["sha"]*3,
        "revenue_yoy": [.1]*3, "operating_margin": [.1]*3,
        "asset_growth_yoy": [.1]*3, "accrual_quality": [.1]*3,
    })
    result = asof_exposures("FUNDAMENTAL", f, "2024-01-01")
    assert result.index.tolist() == ["A"]
