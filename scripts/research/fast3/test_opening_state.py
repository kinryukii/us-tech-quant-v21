"""Synthetic native-Logistic fits; no historical data access."""
from collections import Counter
import json

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn._loss.loss import HalfBinomialLoss
from sklearn.linear_model._linear_loss import LinearModelLoss

try:
    from scripts.research.fast3 import opening_state_study as state
except ImportError:
    import model_part as state


@pytest.fixture(scope="module")
def synthetic_state_data():
    rng = np.random.default_rng(104729)
    rows = []
    for i, date in enumerate(pd.bdate_range("2021-01-04", periods=200)):
        tickers = state.STATE_TICKERS[:1 + (i % 3)] if i < 180 else state.STATE_TICKERS
        for ticker in tickers:
            o, l, b, q = rng.normal(scale=.01, size=4)
            d = o-b
            row = dict(date=date.strftime("%Y-%m-%d"), ticker=ticker,
                g=np.nan, abs_g=np.nan, o=o, l=l, s=abs(o)+.001, e=rng.uniform(),
                p=rng.uniform(-1, 1), v=np.nan, q=q, b=b, d=d, abs_d=abs(d),
                a=np.nan, sq=.002+abs(q), sb=.002+abs(b),
                quality_window_fraction=1.0, quality_units_verified=0.0)
            for horizon, end in (("H15", "10:02"), ("H60", "10:47"), ("H1230", "12:31")):
                row[f"y_{horizon}"] = int(o + .6*b + rng.normal(scale=.01) > 0)
                row[f"label_available_{horizon}"] = pd.Timestamp(row["date"] + " " + end, tz="America/New_York").tz_convert("UTC")
            rows.append(row)
    frame = pd.DataFrame(rows)
    train = frame[frame.date.le(pd.bdate_range("2021-01-04", periods=180)[-1].strftime("%Y-%m-%d"))].reset_index(drop=True)
    test = frame[~frame.index.isin(train.index)].reset_index(drop=True)
    config = {"quality_columns": ["quality_window_fraction", "quality_units_verified"],
              "fit_cutoff_utc": "2022-01-01T00:00:00Z"}
    return train, test, config


@pytest.fixture(scope="module")
def state_fit_events(tmp_path_factory, record_testsuite_property):
    events = []
    yield events
    count = Counter(e["status"] for e in events)
    report = {"identity": "SYNTHETIC_LOGISTIC_INTERFACE_ONLY", "supervised_fit_calls": count["STARTED"],
              "successful_native_solver_runs": count["FINISHED"], "events": events}
    (tmp_path_factory.getbasetemp() / "synthetic_state_fit_counts.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    record_testsuite_property("synthetic_state_supervised_fit_calls", count["STARTED"])


@pytest.fixture(scope="module")
def fitted_states(synthetic_state_data, state_fit_events):
    train, _, config = synthetic_state_data
    preprocessor = state.make_preprocessor(train, config)
    return {name: state.fit_state(train, "H1230", name, config, preprocessor,
                                 on_fit=state_fit_events.append) for name in ("M0", "M1", "BM")}


def test_exact_date_weight_C_mapping_and_library_objective(synthetic_state_data):
    train, _, config = synthetic_state_data
    weight = state.state_date_weights(train, config)
    totals = pd.Series(weight).groupby(train.date).sum()
    np.testing.assert_allclose(totals, 1, rtol=0, atol=1e-15)
    S = weight.sum()
    assert S == pytest.approx(180)
    assert 1/(state.state_parameters(S)["C"]*S) == pytest.approx(.01)
    # The installed loss must equal daily weighted mean LL + .01/2*||coef||².
    X = np.array([[1., .5/np.sqrt(10)], [-.4, -.3/np.sqrt(10)], [.2, 0.]])
    y, w, coef = np.array([1., 0., 1.]), np.array([.5, .5, 1.]), np.array([.3, .6, .7])
    loss = LinearModelLoss(HalfBinomialLoss(), fit_intercept=True)
    observed, _ = loss.loss_gradient(coef, X, y, sample_weight=w, l2_reg_strength=.01)
    score = X @ coef[:-1] + coef[-1]
    manual = w @ (np.logaddexp(0, score)-y*score)/w.sum() + .01/2*(.3**2 + 10*(.6/np.sqrt(10))**2)
    assert observed == pytest.approx(manual, rel=0, abs=1e-15)


def test_main_transforms_missing_flags_and_shrink_columns_identical(synthetic_state_data):
    train, _, config = synthetic_state_data
    preprocessor = state.make_preprocessor(train, config)
    m0, _ = state.state_design(preprocessor, train, "M0", config, train.ticker.unique())
    m1, _ = state.state_design(preprocessor, train, "M1", config, train.ticker.unique())
    pd.testing.assert_frame_equal(m0, m1.drop(columns=list(state.STATE_INTERACTIONS)))
    assert len([c for c in m0 if c.startswith("missing_")]) == 21
    assert m0.missing_ov.eq(1).all()
    np.testing.assert_allclose(m0.stock_o_NVDA, train.ticker.eq("NVDA") * m0.o / np.sqrt(10))
    np.testing.assert_allclose(m0.stock_intercept_NVDA, train.ticker.eq("NVDA") / np.sqrt(10))
    assert m0.stock_intercept_ENPH.eq(0).all()


def test_empty_columns_and_evaluation_extremes_leave_T_statistics_fixed(synthetic_state_data):
    train, test, config = synthetic_state_data
    preprocessor = state.make_preprocessor(train, config)
    saved = preprocessor["imputer"].statistics_.copy(), preprocessor["scaler"].mean_.copy(), preprocessor["scaler"].scale_.copy()
    assert preprocessor["metadata"]["median"][preprocessor["columns"].index("g")] == 0
    extreme = test.copy()
    extreme["g"], extreme["abs_g"], extreme["v"], extreme["a"] = 1000., 1000., 1000., 1.
    design, clipping = state.state_design(preprocessor, extreme, "M1", config, train.ticker.unique())
    assert design.g.eq(5).all() and clipping["g"] == len(test)
    for before, after in zip(saved, (preprocessor["imputer"].statistics_, preprocessor["scaler"].mean_, preprocessor["scaler"].scale_)):
        np.testing.assert_array_equal(before, after)
    # All raw interaction missingness is formed before median fill.
    missing_design, _ = state.state_design(preprocessor, test, "M1", config, train.ticker.unique())
    assert missing_design.ov.eq(0).all() and missing_design.missing_ov.eq(1).all()


def test_market_baseline_reads_only_market_fields(synthetic_state_data, fitted_states):
    _, test, _ = synthetic_state_data
    reduced = test.loc[:, ["ticker", *state.STATE_MARKET]]
    expected = state.predict_state(fitted_states["BM"], test)
    actual = state.predict_state(fitted_states["BM"], reduced)
    np.testing.assert_allclose(expected["p_up"], actual["p_up"], rtol=0, atol=1e-12)
    assert fitted_states["BM"]["metadata"]["coef_names"] == [*state.STATE_MARKET, *[f"missing_{c}" for c in state.STATE_MARKET]]


def test_native_fit_probability_and_no_calibrator(fitted_states, synthetic_state_data):
    _, test, _ = synthetic_state_data
    for model in fitted_states.values():
        result = state.predict_state(model, test)
        np.testing.assert_allclose(result["p_up"], 1/(1+np.exp(-result["raw_score"])), rtol=0, atol=1e-14)
        np.testing.assert_array_equal(result["predicted_up"], result["p_up"] >= .5)
        assert model["metadata"]["max_abs_gradient"] < 1e-5
        assert "calibrator" not in model
        assert model["metadata"]["actual_params"]["solver"] == "lbfgs"
        assert model["metadata"]["actual_params"]["l1_ratio"] == 0.0
        assert model["metadata"]["actual_params"]["max_iter"] == 2000
        assert model["metadata"]["actual_params"]["class_weight"] is None


def test_absent_T_stock_deviations_zero_and_unknown_stock_rejected(fitted_states, synthetic_state_data):
    train, test, config = synthetic_state_data
    model = fitted_states["M1"]
    design, _ = state.state_design(model["preprocessor"], test, "M1", config, model["trained_tickers"])
    assert design.stock_intercept_ENPH.eq(0).all() and design.stock_o_ENPH.eq(0).all()
    assert model["metadata"]["stock_deviation"]["stock_intercept_ENPH"] == 0
    invalid = test.copy()
    invalid.loc[0, "ticker"] = "TSM"
    with pytest.raises(state.FitFailure, match="OUT_OF_FIXED_STOCK_SCOPE"):
        state.predict_state(model, invalid)


def test_saved_state_model_replay_within_tolerance(fitted_states, synthetic_state_data, tmp_path):
    _, test, _ = synthetic_state_data
    for name, model in fitted_states.items():
        path = tmp_path / f"synthetic_state_{name}.joblib"
        joblib.dump(model, path)
        expected, actual = state.predict_state(model, test), state.predict_state(joblib.load(path), test)
        np.testing.assert_allclose(actual["p_up"], expected["p_up"], rtol=0, atol=1e-12)
        np.testing.assert_array_equal(actual["predicted_up"], expected["predicted_up"])


def test_training_maturity_2026_and_exact_preprocessor_identity(synthetic_state_data):
    train, _, config = synthetic_state_data
    invalid = train.copy()
    invalid.loc[0, "label_available_H1230"] = pd.Timestamp("2026-01-01T00:00:00Z")
    with pytest.raises(state.FitFailure, match="MATURITY_OR_PRE2026"):
        state.fit_state(invalid, "H1230", "M1", config)
    with pytest.raises(state.FitFailure, match="MATURITY_OR_PRE2026"):
        state.fit_state(train, "H1230", "M1", {**config, "fit_cutoff_utc": train.label_available_H1230.max().isoformat()})
    preprocessor = state.make_preprocessor(train, config)
    invalid = train.copy()
    invalid.loc[0, "o"] += .01
    with pytest.raises(state.FitFailure, match="EXACT_TRAINING_INPUTS"):
        state.fit_state(invalid, "H1230", "M1", config, preprocessor)
    invalid = train.copy()
    invalid.loc[0, "date"] = "2026-01-01"
    with pytest.raises(state.FitFailure, match="PREPROCESSOR_DATE_BOUNDARY"):
        state.make_preprocessor(invalid, config)


def test_invalid_training_is_rejected_before_fit(synthetic_state_data):
    train, _, config = synthetic_state_data
    single = train.copy()
    single["y_H1230"] = 0
    with pytest.raises(state.FitFailure, match="SINGLE_CLASS"):
        state.fit_state(single, "H1230", "M1", config)
    with pytest.raises(state.FitFailure, match="180"):
        state.fit_state(train[train.date.ne(train.date.max())], "H1230", "M1", config)
    with pytest.raises(ValueError, match="iteration"):
        state.state_parameters(180, 3000)
    assert state.state_parameters(180, 2000)["C"] == state.state_parameters(180, 4000)["C"]


def test_malformed_raw_interaction_is_not_silently_used(synthetic_state_data):
    train, _, config = synthetic_state_data
    invalid = train.copy()
    invalid["oe"] = 999.
    with pytest.raises(state.FitFailure, match="INTERACTION_DEFINITION_MISMATCH:oe"):
        state.make_preprocessor(invalid, config)


"""Data checks for merging into the one concentrated state-study test module."""
import importlib
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

from scripts.research.fast3 import opening_state_data as data


def state_old(date='2025-11-28'):
    x = pd.DataFrame({'ticker': ['NVDA'], 'security_uid': ['SEC-NVDA'], 'date': [date],
        'sample_id': ['NVDA|'+date], 'eligible': [True], 'prediction_eligible': [True],
        'opening_return': [.01], 'opening_return_5m': [-.003], 'opening_QQQ_return': [.002],
        'opening_SOXX_return': [.005], 'opening_rv': [.02], 'opening_QQQ_rv': [.01],
        'opening_SOXX_rv': [.013], 'opening_efficiency': [.5], 'opening_range_position': [.7],
        'opening_range': [.02], 'opening_valid_bar_fraction': [1.], 'opening_staleness_minutes': [0.],
        'opening_gap': [1000.], 'opening_relative_volume': [999.]})
    for name, clock in [('prediction_at_utc', '09:45'), ('feature_cutoff_utc', '09:44'),
                        ('label_start_utc', '09:46'), ('opening_last_feature_bar_end_utc', '09:44')]:
        x[name] = data.timestamps(x.date, clock)
    return x


def endpoint_bars(date='2025-11-28'):
    rows = []
    for clock, opening, close in [('09:44', 99., 100.), ('09:46', 10., 11.),
                                  ('09:47', 100., 101.), ('10:01', 101., 102.),
                                  ('10:46', 102., 103.), ('12:30', 103., 104.)]:
        rows.append({'symbol': 'NVDA', 'timestamp_utc': data.timestamps([date], clock).iloc[0],
                     'open': opening, 'close': close, 'high': max(opening, close),
                     'low': min(opening, close), 'volume': 100.})
    return pd.DataFrame(rows)


def state_calendar(date='2025-11-28', close='13:00'):
    return pd.DataFrame({'date': [date], 'market_open_utc': data.timestamps([date], '09:30'),
                         'market_close_utc': data.timestamps([date], close)})


def test_state_exact_0947_open_and_three_endpoint_closes_half_day():
    ends = data.endpoint_table(endpoint_bars(), state_calendar())
    z = data.attach_labels(data.compact_state(state_old()), ends).iloc[0]
    assert z.price_start == 100.
    assert [z.price_end_H15, z.price_end_H60, z.price_end_H1230] == [102., 103., 104.]
    assert [z.return_H15, z.return_H60, z.return_H1230] == pytest.approx([.02, .03, .04])
    assert z.label_available_H15.tz_convert('America/New_York').strftime('%H:%M') == '10:02'
    assert z.label_available_H60.tz_convert('America/New_York').strftime('%H:%M') == '10:47'
    assert z.label_available_H1230.tz_convert('America/New_York').strftime('%H:%M') == '12:31'


def test_state_missing_short_endpoint_does_not_remove_other_labels_or_prediction():
    bars = endpoint_bars()
    bars = bars[bars.timestamp_utc.ne(data.timestamps(['2025-11-28'], '10:01').iloc[0])]
    z = data.attach_labels(data.compact_state(state_old()), data.endpoint_table(bars, state_calendar()))
    assert len(z) == 1 and z.prediction_eligible.all()
    assert z.y_H15.isna().all() and z.y_H60.notna().all() and z.y_H1230.notna().all()
    assert z.label_reason_H15.iloc[0] == 'MISSING_OR_INVALID_END_1001'


def test_state_future_outcome_changes_cannot_change_compact_features():
    before = state_old()
    after = before.copy()
    after['price_at_09_46'], after['price_at_12_30'], after['return_remaining'] = 999., 1., -999.
    pd.testing.assert_frame_equal(data.compact_state(before), data.compact_state(after))


def test_state_uncertified_units_and_dependent_interactions_are_shared_missing():
    x = data.compact_state(state_old())
    assert x[data.UNIT_EXCLUDED].isna().all().all()
    assert x[['oe', 'de']].notna().all().all()
    assert x.unit_gap_reason.eq(data.UNIT_REASON).all()
    assert x.quality_gap_unit_uncertified.eq(1).all()
    assert x.quality_volume_unit_uncertified.eq(1).all()
    assert not any('missing_' in c for c in data.QUALITY_COLUMNS)


def test_state_log_returns_abs_efficiency_and_raw_interaction_missing_propagation():
    old = state_old()
    old['opening_return'], old['opening_efficiency'] = -.01, -.5
    x = data.compact_state(old).iloc[0]
    assert x.o == pytest.approx(np.log(.99))
    assert x.e == .5
    assert x.p == pytest.approx(.4)
    assert x.d == pytest.approx(np.log(.99)-np.log(1.005))
    assert x.oe == pytest.approx(x.o*x.e)
    old['opening_efficiency'] = np.nan
    x = data.compact_state(old)
    assert x[['oe', 'de']].isna().all().all()


def test_state_zero_known_range_and_path_are_zero_but_unknown_range_stays_missing():
    old = state_old()
    old['opening_range_position'], old['opening_range'], old['opening_efficiency'], old['opening_return'] = np.nan, 0., 0., 0.
    x = data.compact_state(old).iloc[0]
    assert x.p == 0. and x.e == 0.
    old['opening_range'] = np.nan
    assert np.isnan(data.compact_state(old).p.iloc[0])


def test_state_exact_endpoint_reader_filters_2026_before_materializing(tmp_path):
    store = data.DataStore(data.resolve(Path('D:/us-tech-quant'), cache_root=tmp_path))
    path = tmp_path/'mixed.parquet'
    pd.concat([endpoint_bars('2025-12-31'), endpoint_bars('2026-01-02')], ignore_index=True).to_parquet(path, index=False)
    out = data.read_exact_endpoints(store, [path], ['2025-12-31', '2026-01-02'])
    assert len(out) == 4
    assert out.timestamp_utc.max() < data.CUTOFF
    assert set(out.timestamp_utc.dt.tz_convert('America/New_York').dt.strftime('%H:%M')) == {'09:47', '10:01', '10:46', '12:30'}
    with pytest.raises(ValueError, match='Invalid'):
        data.endpoint_table(endpoint_bars('2026-01-02'), state_calendar('2026-01-02'))


def test_state_calendar_disallows_target_after_close_without_changing_short_labels():
    ends = data.endpoint_table(endpoint_bars(), state_calendar(close='11:00'))
    out = data.attach_labels(data.compact_state(state_old()), ends)
    assert out.y_H15.notna().all() and out.y_H60.notna().all()
    assert out.y_H1230.isna().all()
    assert out.label_reason_H1230.eq('CALENDAR_OUTSIDE_TARGET_SESSION').all()


def test_state_three_correlated_labels_do_not_triple_population_or_dates():
    x = data.attach_labels(data.compact_state(state_old()), data.endpoint_table(endpoint_bars(), state_calendar()))
    assert x.sample_id.nunique() == 1 and x.date.nunique() == 1
    assert len([c for c in x if c.startswith('y_')]) == 3


def test_state_optional_ledger_permission_denial_is_recorded_without_enabling_unit_fields(tmp_path, monkeypatch):
    import sqlite3
    from types import SimpleNamespace
    catalog = tmp_path/'catalog.sqlite3'
    with sqlite3.connect(catalog) as connection:
        connection.execute('CREATE TABLE data_files (dataset TEXT,ticker TEXT,path TEXT,source_sha256 TEXT,lineage_json TEXT,is_current INTEGER)')
    ledger = tmp_path/'restricted_optional_ledger.parquet'
    real_is_file = Path.is_file
    def permission_denied(path):
        if path == ledger:
            raise PermissionError(5, 'synthetic access denied', str(path))
        return real_is_file(path)
    monkeypatch.setattr(data, 'UNIT_LEDGER', ledger)
    monkeypatch.setattr(Path, 'is_file', permission_denied)
    audit = data.audit_units(SimpleNamespace(catalog_path=catalog), tmp_path/'absent_optional_code', '2020-05-22', '2025-12-31')
    failed = [r for r in audit['records_checked'] if r.get('role') == 'OPTIONAL_EXISTING_EVENT_LEDGER']
    assert len(failed) == 1
    assert failed[0]['status'] == 'UNVERIFIABLE_OPTIONAL_SOURCE'
    assert failed[0]['error_type'] == 'PermissionError'
    assert failed[0]['path'] == str(ledger)
    assert 'synthetic access denied' in failed[0]['reason']
    assert audit['status'] == 'UNIT_DEPENDENT_FIELD_CLASS_EXCLUDED'
    assert audit['excluded_columns'] == data.UNIT_EXCLUDED
    x = data.compact_state(state_old())
    assert x[data.UNIT_EXCLUDED].isna().all().all()
    assert x[['o','e','oe','de']].notna().all().all()
    assert all(r['status'] == 'UNVERIFIABLE_OPTIONAL_SOURCE' for r in audit['reviewed_source_code'])


def test_state_optional_catalog_and_provider_failures_remain_local(tmp_path, monkeypatch):
    import sqlite3
    from types import SimpleNamespace
    monkeypatch.setattr(data, 'UNIT_LEDGER', tmp_path/'no_ledger.parquet')
    denied = data.audit_units(SimpleNamespace(catalog_path=tmp_path/'missing_catalog.sqlite3'),
                              tmp_path/'optional_code', '2020-05-22', '2025-12-31')
    assert not denied['action_catalog_query_verified']
    assert denied['no_action_catalog_entry'] is None
    assert any(r.get('role') == 'OPTIONAL_ACTION_CATALOG' for r in denied['records_checked'])
    catalog = tmp_path/'catalog.sqlite3'
    with sqlite3.connect(catalog) as connection:
        connection.execute('CREATE TABLE data_files (dataset TEXT,ticker TEXT,path TEXT,source_sha256 TEXT,lineage_json TEXT,is_current INTEGER)')
        connection.execute('INSERT INTO data_files VALUES (?,?,?,?,?,?)',
                           ('corporate_actions_yahoo','NVDA',str(tmp_path/'missing_actions.parquet'),'bad_hash','{}',1))
    audit = data.audit_units(SimpleNamespace(catalog_path=catalog), tmp_path/'optional_code', '2020-05-22', '2025-12-31')
    assert audit['action_catalog_query_verified']
    assert any(r.get('role') == 'OPTIONAL_PROVIDER_ACTIONS' and r['error_type'] == 'FileNotFoundError' for r in audit['records_checked'])
    assert audit['excluded_columns'] == data.UNIT_EXCLUDED


"""Runner-only assertions for the one merged state-study test file; no fits."""
from pathlib import Path
import hashlib
import json
import importlib
import sys
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import pytest

from scripts.research.fast3 import opening_state_study as state


def runner_config():
    return {'main_columns': ['g','abs_g','o','l','s','e','p','v','q','b','d','abs_d','a','sq','sb'],
            'interaction_columns': ['ov','oe','o_abs_g','oa','dv','de'],
            'quality_columns': [], 'market_columns': ['q','b','sq','sb']}


def runner_frame(dates):
    x = pd.MultiIndex.from_product([dates, ['AMD','AVGO','ENPH','NVDA']], names=['date','ticker']).to_frame(index=False)
    x['sample_id'], x['security_uid'], x['eligible'] = x.ticker+'|'+x.date, x.ticker, True
    for key,clock in [('prediction_at_utc','09:45'),('feature_cutoff_utc','09:44'),('label_start_utc','09:46')]:
        x[key] = pd.to_datetime(x.date+' '+clock).dt.tz_localize('America/New_York').dt.tz_convert('UTC')
    for key in runner_config()['main_columns']+runner_config()['interaction_columns']:
        x[key] = .01
    for key in ['g','abs_g','v','a','ov','o_abs_g','oa','dv']:
        x[key] = np.nan
    x['price_start'] = 100.
    for h,(end,mature) in state.HORIZONS.items():
        x['y_'+h] = np.arange(len(x))%2
        x['return_'+h] = np.where(x['y_'+h].eq(1), .01, -.01)
        x['price_end_'+h] = 100.*(1+x['return_'+h])
        x['label_end_'+h] = pd.to_datetime(x.date+' '+end).dt.tz_localize('America/New_York').dt.tz_convert('UTC')
        x['label_available_'+h] = pd.to_datetime(x.date+' '+mature).dt.tz_localize('America/New_York').dt.tz_convert('UTC')
        x['label_reason_'+h] = 'OK'
    return x


def test_runner_quarter_boundaries_whole_day_maturity_and_horizon_missingness():
    x = runner_frame(['2022-12-30','2023-01-03'])
    boundary = state.quarter_boundary('2023Q1')
    assert boundary == pd.Timestamp('2023-01-01T00:00:00Z')
    t = state.training_rows(x, 'H1230', boundary)
    assert t.date.unique().tolist() == ['2022-12-30']
    assert len(t) == 4 and t.label_available_H1230.max() < boundary
    x.loc[0,'y_H15'] = np.nan
    assert len(state.training_rows(x,'H15',boundary)) == 3
    assert len(state.training_rows(x,'H1230',boundary)) == 4
    x.loc[1,'label_available_H15'] = boundary
    assert len(state.training_rows(x,'H15',boundary)) == 2
    with pytest.raises(ValueError, match='2026'):
        state.validate_state_panel(runner_frame(['2026-01-02']), runner_config())


def test_runner_global_training_maturity_cap_does_not_expand_with_boundary():
    x = runner_frame(['2025-12-31','2026-01-02'])
    rows = state.training_rows(x, 'H1230', pd.Timestamp('2027-01-01T00:00:00Z'))
    assert len(rows) == 4
    assert rows.label_available_H1230.lt(pd.Timestamp('2026-01-01T00:00:00Z')).all()


def test_runner_freeze_counts_111_132_and_preserves_all_three_E_populations(tmp_path,monkeypatch):
    x = runner_frame(pd.bdate_range('2022-01-03','2023-03-31').strftime('%Y-%m-%d').tolist())
    missing = x.index[x.date.eq('2023-01-03')][0]
    x.loc[missing,['y_H15','return_H15']] = np.nan
    dataset,output = tmp_path/'data',tmp_path/'evaluation'
    dataset.mkdir()
    x.to_parquet(dataset/'panel.parquet',index=False)
    cfg = runner_config() | {'panel_sha256':state.evidence.sha(dataset/'panel.parquet'), 'sample_manifest_sha256':'synthetic'}
    (dataset/'data_config.json').write_text(json.dumps(cfg),encoding='utf-8')
    monkeypatch.setattr(state,'state_code_identity',lambda:{'scope':'synthetic no fit'})
    protocol = state.freeze_state(dataset,output)
    assert protocol['budget']['planned_supervised'] == 111
    assert protocol['budget']['hard_cap'] == 132
    assert protocol['budget']['quarterly_models'] == 12*3*3
    ids = pd.read_parquet(output/'fold_sample_ids.parquet')
    e = ids[(ids.quarter=='2023Q1')&(ids.segment=='E')]
    expected = set(x.loc[x.date.ge('2023-01-01'),'sample_id'])
    for h in state.HORIZONS:
        assert set(e.loc[e.horizon.eq(h),'sample_id']) == expected
    assert x.loc[missing,'sample_id'] in expected
    assert not (output/'fit_events.jsonl').exists()


def test_runner_constant_fit_failure_keeps_requested_role_and_all_rows():
    x = runner_frame(['2023-01-03'])
    bundle = state.constant_state('M1','H1230',.61,'2022-12-30T17:31:00Z','MODEL_FAILURE_B1:synthetic')
    result,_ = state.prediction_rows(bundle,x,'H1230','M1',.61,'2023Q1')
    assert result.sample_id.tolist() == x.sample_id.tolist()
    assert result.model_id.eq('M1').all()
    assert result.actual_predictor.eq('B1').all()
    assert result.p_up.eq(.61).all() and result.fallback_reason.notna().all()


@pytest.mark.parametrize('model_id', ['M0','M1','BM'])
def test_runner_necessary_input_fallback_is_local_and_unit_isolation_alone_is_not(model_id,monkeypatch):
    x = runner_frame(['2023-01-03'])
    monkeypatch.setattr(state,'predict_state',lambda *_:{'p_up':np.full(4,.8),'raw_score':np.ones(4),'clip_counts':{}})
    bundle = {'kind':'learner','metadata':{'max_label_available_at':'2022-12-30T17:31:00Z'}}
    if model_id in ('M0','M1'):
        x.loc[0,'o'] = np.nan
    else:
        x.loc[0,['q','b','sq','sb']] = np.nan
        x.loc[1,'q'] = np.nan  # remaining market values still usable
    rows,_ = state.prediction_rows(bundle,x,'H1230',model_id,.61,'2023Q1')
    assert rows.p_up.iloc[0] == .61
    assert rows.p_up.iloc[1:].eq(.8).all()
    assert rows.fallback_reason.iloc[1:].isna().all()
    assert rows.actual_predictor.iloc[0] == 'B1'
    assert x[['g','v']].isna().all().all()
    assert len(rows) == len(x)


def test_runner_BM_all_nonfinite_market_inputs_are_missing(monkeypatch):
    x = runner_frame(['2023-01-03'])
    x.loc[0,['q','b','sq','sb']] = np.inf
    monkeypatch.setattr(state,'predict_state',lambda *_:{'p_up':np.full(4,.8),'raw_score':np.ones(4)})
    rows,_ = state.prediction_rows({'kind':'learner','metadata':{}},x,'H15','BM',.61,'2023Q1')
    assert rows.p_up.iloc[0] == .61
    assert rows.fallback_reason.iloc[0] == 'NECESSARY_INPUT_MISSING_B1'


def test_runner_B1_probability_is_daily_equal_not_stock_row_equal():
    x = runner_frame(['2022-12-29','2022-12-30'])
    x = pd.concat([x.iloc[:4],x.iloc[4:5]],ignore_index=True)
    x['y_H1230'] = [1,1,1,1,0]
    assert state.prior_probability(x,'H1230') == .5
    assert state.prior_probability(x.iloc[:0],'H1230') == .5


def test_runner_nonconvergence_retries_once_4000_same_samples_objective_and_preprocessor(tmp_path,monkeypatch):
    x = runner_frame(pd.bdate_range('2022-01-03',periods=180).strftime('%Y-%m-%d').tolist())
    cfg,pp = runner_config(),object()
    protocol = {'panel_sha256':'synthetic','source_code':{'code':'v1'},'model_contract':{'penalty':.01}}
    budget = state.evidence.Budget(tmp_path/'ledger.jsonl',hard_cap=132,retry_cap=21)
    calls=[]
    def fake_fit(train,h,model_id,config,preprocessor=None,max_iter=None,on_fit=None):
        calls.append((train.sample_id.tolist(),h,model_id,config,preprocessor,max_iter))
        on_fit({'status':'STARTED'})
        if len(calls)==1:
            on_fit({'status':'FAILED'})
            raise state.ConvergenceFailure('synthetic nonconvergence, no estimator executed')
        on_fit({'status':'FINISHED'})
        return {'metadata':{'max_label_available_at':train['label_available_'+h].max().isoformat()}}
    monkeypatch.setattr(state,'fit_state',fake_fit)
    result = state.recorded_state_fit(budget,x,'H1230','M1',cfg,pp,'2023Q1',protocol)
    assert len(calls)==2 and [v[-1] for v in calls]==[2000,4000]
    assert calls[0][:-1]==calls[1][:-1]
    assert calls[0][4] is pp and calls[1][4] is pp
    assert budget.calls==2 and budget.retries==1
    started=[v for v in budget.events if v['status']=='STARTED']
    assert started[0]['cache_key']==started[1]['cache_key']==result['cache_key']


def test_runner_fit_cap_and_second_nonconvergence_failure_preserve_ledger(tmp_path,monkeypatch):
    x = runner_frame(pd.bdate_range('2022-01-03',periods=180).strftime('%Y-%m-%d').tolist())
    protocol={'panel_sha256':'synthetic','source_code':{},'model_contract':{}}
    budget = state.evidence.Budget(tmp_path/'cap.jsonl',hard_cap=132,retry_cap=21)
    budget.calls=132
    monkeypatch.setattr(state,'fit_state',lambda *_args,**_kwargs:pytest.fail('cap must prevent call'))
    with pytest.raises(RuntimeError,match='FIT_BUDGET_EXHAUSTED'):
        state.recorded_state_fit(budget,x,'H15','M1',runner_config(),None,'2023Q1',protocol)
    assert budget.calls==132 and not budget.events
    budget=state.evidence.Budget(tmp_path/'failed.jsonl',hard_cap=132,retry_cap=21)
    def fail(*_args,**_kwargs):
        _kwargs['on_fit']({'status':'STARTED'})
        _kwargs['on_fit']({'status':'FAILED'})
        raise state.ConvergenceFailure('synthetic no fit')
    monkeypatch.setattr(state,'fit_state',fail)
    with pytest.raises(state.ConvergenceFailure):
        state.recorded_state_fit(budget,x,'H15','M1',runner_config(),None,'2023Q1',protocol)
    assert budget.calls==2 and budget.retries==1
    assert sum(v['status']=='FAILED' for v in budget.events)==2


def test_runner_paired_bootstrap_uses_10000_common_draws_and_Bonferroni_quantiles():
    dates=pd.bdate_range('2023-01-03',periods=61).strftime('%Y-%m-%d')
    base=np.linspace(.6,.7,len(dates))
    by={'M1':pd.DataFrame({'date':dates,'log_loss':base})}
    for i,name in enumerate(('M0','B0','B1','BM')):
        by[name]=pd.DataFrame({'date':dates,'log_loss':base+(i+1)*np.linspace(-.01,.02,len(dates))})
    actual,_=state.paired_state(by)
    rng=np.random.default_rng(104729)
    starts=rng.integers(0,61-20+1,size=(10000,4))
    indices=(starts[:,:,None]+np.arange(20)).reshape(10000,-1)[:,:61]
    draw_id=hashlib.sha256(starts.tobytes()).hexdigest()
    for name in ('M0','B0','B1','BM'):
        delta=by['M1'].log_loss.to_numpy()-by[name].log_loss.to_numpy()
        samples=delta[indices].mean(axis=1)
        qs=np.quantile(samples,[.025,.975,.05/6,1-.05/6])
        got=actual['M1-'+name]
        assert got['draw_identity']==draw_id
        assert [got[k] for k in ['ci95_low','ci95_high','ci_adjusted_low','ci_adjusted_high']]==pytest.approx(qs)
        assert got['dates']==61
    mismatched={**by,'BM':by['BM'].iloc[:-1]}
    with pytest.raises(ValueError,match='dates do not align'):
        state.paired_state(mismatched)


def test_runner_three_horizons_evaluation_retains_unique_market_experience(tmp_path):
    x=runner_frame(['2023-01-03','2023-01-04'])
    predictions=[]
    for h in state.HORIZONS:
        for model in ('M0','M1','BM','B0','B1'):
            bundle=state.constant_state(model,h,.5)
            rows,_=state.prediction_rows(bundle,x,h,model,.5,'2023Q1')
            predictions.append(rows)
    result=state.evaluate_state(pd.concat(predictions,ignore_index=True),x,tmp_path,[])
    assert result['unique_stock_days']==8
    assert result['unique_trading_days']==2
    assert result['related_labels_are_not_independent_samples']
    assert len(result['coverage'])==3
    assert all(v['prediction_rows']==8 and v['prediction_dates']==2 for v in result['coverage'])


def test_runner_default_B0_offline_no_bullish_class_protected_scope_and_replay(tmp_path):
    x=runner_frame(['2025-12-31'])
    bundle=state.constant_state('B0','H1230',.5,reason='H1230_NO_EXPLORATORY_SUPPORT')
    bundle['role']='NO_MODEL_SIGNAL'
    before=state.predict_state_offline(bundle,x)
    assert before.p_up.eq(.5).all() and before.predicted_up.isna().all()
    assert before.model_role.eq('NO_MODEL_SIGNAL').all()
    assert before.target_end.dt.tz_convert('America/New_York').dt.strftime('%H:%M').eq('12:30').all()
    assert not before[['ADOPTION_ALLOWED','LIVE_TRADING_ALLOWED','BROKER_ACTION_ALLOWED']].any().any()
    path=tmp_path/'default.joblib';joblib.dump(bundle,path)
    pd.testing.assert_frame_equal(before,state.predict_state_offline(joblib.load(path),x),check_exact=True)
    bad=x.copy();bad.loc[0,'ticker']='TSM'
    with pytest.raises(ValueError,match='stock-universe'):
        state.predict_state_offline(bundle,bad)
    with pytest.raises(ValueError,match='Wrong task/horizon'):
        state.predict_state_offline(bundle,x,'H15')


def test_runner_prediction_failure_retains_all_rows_and_prior_identity(monkeypatch):
    x=runner_frame(['2023-01-03'])
    def fail(*args):
        raise state.FitFailure('synthetic bad score; no fit')
    monkeypatch.setattr(state,'predict_state',fail)
    bundle={'kind':'learner','metadata':{'prior_predictor_id':'B0'}}
    rows,_=state.prediction_rows(bundle,x,'H15','M1',.5,'2023Q1')
    assert len(rows)==len(x) and rows.p_up.eq(.5).all()
    assert rows.actual_predictor.eq('B0').all()
    assert rows.fallback_reason.str.startswith('PREDICTION_FAILURE_B0').all()


def test_runner_rejected_preflight_is_not_an_estimator_fit(tmp_path,monkeypatch):
    x=runner_frame(pd.bdate_range('2022-01-03',periods=180).strftime('%Y-%m-%d').tolist())
    budget=state.evidence.Budget(tmp_path/'reject.jsonl',hard_cap=132,retry_cap=21)
    def fail(*args,**kwargs):
        raise state.FitFailure('synthetic invalid preprocessing, no estimator call')
    monkeypatch.setattr(state,'fit_state',fail)
    with pytest.raises(state.FitFailure):
        state.recorded_state_fit(budget,x,'H15','M1',runner_config(),None,'2023Q1',{'panel_sha256':'x','source_code':{},'model_contract':{}})
    assert budget.calls==budget.retries==0
    assert [e['status'] for e in budget.events]==['PREFLIGHT_REJECTED']
