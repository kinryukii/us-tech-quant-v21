"""Synthetic chronological and native-interface checks; no real predictions."""
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.ensemble.joint_oof_bridge import (
    fit_native_bridge,apply_native_bridge,BridgeDependencyError,
)

def small(role='return'):
    raw=pd.DataFrame({'signal_date':pd.to_datetime(['2021-01-04','2021-01-04','2021-01-05']),
                      'ticker':['A','B','C'],'source_cutoff':pd.Timestamp('2021-01-01')})
    if role=='return':raw['m__raw']=[0.,1.,2.]
    elif role=='rank':raw['m__rank']=[10.,20.,30.];raw.signal_date=pd.Timestamp('2021-01-04')
    elif role=='probability':raw['m__p']=[.1,.5,.9]
    elif role=='quantile':
        raw['m__q10']=[-.1,0.,.1];raw['m__q50']=[0.,.1,.2];raw['m__q90']=[.1,.3,.5]
    elif role=='distribution':raw['m__location']=[0.,1.,2.];raw['m__scale']=[1.,2.,3.]
    truth=raw[['signal_date','ticker']].copy()
    truth['y_open5']=[1.,1.5,2.]
    truth['label_mature_date']=pd.Timestamp('2021-01-13');truth['label_available']=True
    spec={'native_name':'m','minimum_rows':2}
    return raw,truth,spec

def future(raw):
    frame=raw.copy();frame['signal_date']=pd.Timestamp('2022-01-03')
    frame['source_cutoff']=pd.Timestamp('2022-01-01')
    return frame

def test_all_rows_date_equal_scaler_and_no_return_clipping():
    raw,truth,spec=small()
    bundle=fit_native_bridge(raw,truth,'2022-01-01',spec)
    assert bundle['fit_rows']==3 and bundle['native_base_fit_units']==0
    assert bundle['fit_units']==3 and bundle['optimizer_fit_units']==2
    assert bundle['scaler'].mean_[0]==pytest.approx(1.25)
    assert bundle['target_weighted_mean']==pytest.approx(1.625)
    assert bundle['target_clip'] is None

def test_more_than_40000_rows_are_all_fitted_without_legacy_sampling():
    count=40001
    raw=pd.DataFrame({'signal_date':pd.Timestamp('2021-01-04'),
                      'ticker':['T'+str(i) for i in range(count)],
                      'source_cutoff':pd.Timestamp('2021-01-01'),
                      'm__raw':np.arange(count)/count})
    truth=raw[['signal_date','ticker']].copy()
    truth['y_open5']=2.+raw['m__raw']*.1;truth['label_mature_date']=pd.Timestamp('2021-01-13')
    bundle=fit_native_bridge(raw,truth,'2022-01-01',{'native_name':'m'})
    assert bundle['fit_rows']==count
    assert bundle['target_weighted_mean']>2.

def test_future_source_cutoff_rejected_and_exact_maturity_cutoff_excluded():
    raw,truth,spec=small()
    illegal=raw.copy();illegal.loc[0,'source_cutoff']=pd.Timestamp('2021-01-06')
    with pytest.raises(ValueError,match='NATIVE_SOURCE_CUTOFF_AFTER_SIGNAL'):
        fit_native_bridge(illegal,truth,'2022-01-01',spec)
    truth.loc[0,'label_mature_date']=pd.Timestamp('2022-01-01')
    bundle=fit_native_bridge(raw,truth,'2022-01-01',spec)
    assert bundle['fit_rows']==2
    assert pd.Timestamp(bundle['label_mature_max'])<pd.Timestamp('2022-01-01')

def test_rank_percentile_uses_full_cross_section_before_label_join():
    raw,truth,spec=small('rank')
    truth=truth.iloc[[0,2]].copy()
    bundle=fit_native_bridge(raw,truth,'2022-01-01',spec)
    assert bundle['schema']['role']=='rank'
    assert bundle['scaler'].mean_[0]==pytest.approx(2/3)
    result=apply_native_bridge(future(raw),bundle)
    pd.testing.assert_series_equal(result['m__rank'],raw['m__rank'])
    assert result.expected_return_coordinate.eq('FIVE_SESSION_NEXT_OPEN_SHAREHOLDER_VALUE_RETURN').all()

def test_probability_kept_native_and_missing_requested_interface_fails():
    raw,truth,spec=small('probability')
    bundle=fit_native_bridge(raw,truth,'2022-01-01',spec)
    result=apply_native_bridge(future(raw),bundle)
    pd.testing.assert_series_equal(result['m__p'],raw['m__p'])
    assert result.native_role.eq('probability').all()
    with pytest.raises(BridgeDependencyError,match='MISSING_NATIVE_DEPENDENCY'):
        fit_native_bridge(raw.drop(columns='m__p').assign(m__raw=0.),truth,'2022-01-01',
                          {**spec,'native_role':'probability'})

def test_quantile_and_distribution_scale_calibrated_native_values_preserved():
    for role,field in [('quantile','m__q10'),('distribution','m__scale')]:
        raw,truth,spec=small(role)
        bundle=fit_native_bridge(raw,truth,'2022-01-01',spec)
        out=apply_native_bridge(future(raw),bundle)
        pd.testing.assert_series_equal(out[field],raw[field])
        assert bundle['native_scale_ratio']>0
        assert bundle['fit_units']==4 and 'native_scale_ratio' in bundle['estimated_states']
        assert np.isfinite(out.sigma).all()
    assert out.sigma.iloc[1]/out.sigma.iloc[0]==pytest.approx(2.)

def test_missing_native_row_preserved_as_unavailable_and_no_history_application():
    raw,truth,spec=small()
    bundle=fit_native_bridge(raw,truth,'2022-01-01',spec)
    frame=future(raw);frame.loc[1,'m__raw']=np.nan
    result=apply_native_bridge(frame,bundle)
    assert len(result)==len(frame)
    assert not result.loc[1,'bridge_available']
    assert pd.isna(result.loc[1,'mu']) and pd.isna(result.loc[1,'sigma'])
    with pytest.raises(ValueError,match='BRIDGE_APPLIED_TO_ITS_TRAINING_HISTORY'):
        apply_native_bridge(raw,bundle)

def test_future_pre2026_append_does_not_change_earlier_bridge_fit():
    raw,truth,spec=small()
    old=fit_native_bridge(raw,truth,'2022-01-01',spec)
    extra=raw.copy();extra['signal_date']=pd.Timestamp('2023-01-03');extra['source_cutoff']=pd.Timestamp('2023-01-01');extra['m__raw']=1e6
    more=fit_native_bridge(pd.concat([raw,extra],ignore_index=True),truth,'2022-01-01',spec)
    np.testing.assert_array_equal(old['scaler'].mean_,more['scaler'].mean_)
    np.testing.assert_array_equal(old['model'].coef_,more['model'].coef_)
    assert old['oof_lineage_digest']==more['oof_lineage_digest']

def test_test_content_and_incomplete_native_base_maturity_are_rejected():
    raw,truth,spec=small()
    later=raw.copy();later['signal_date']=pd.Timestamp('2026-01-02')
    with pytest.raises(ValueError,match='NATIVE_CONTENT_OUTSIDE_TIME_BOUNDARY'):
        fit_native_bridge(later,truth,'2022-01-01',spec)
    raw['source_label_mature_max']=raw.source_cutoff
    with pytest.raises(ValueError,match='NATIVE_BASE_LABEL_MATURITY_NOT_PRIOR'):
        fit_native_bridge(raw,truth,'2022-01-01',spec)
