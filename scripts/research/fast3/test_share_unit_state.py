"""Zero-fit targeted checks for the fixed share-unit adapter."""
import numpy as np
import pandas as pd
import pytest

from scripts.research.fast3 import share_unit_data as unit


def event(date='2024-01-05', r=10, kind='PURE_FORWARD_SPLIT', available='2024-01-01'):
    return {'ticker': 'NVDA', 'event_type': kind, 'new_shares_per_old_share': r,
        'event_effective_time_UTC': pd.Timestamp(date+' 09:30', tz='America/New_York').tz_convert('UTC'),
        'historically_available_by_UTC': pd.Timestamp(available, tz='America/New_York').tz_convert('UTC')}


def clock(date, value):
    return pd.Timestamp(date+' '+value, tz='America/New_York').tz_convert('UTC')


@pytest.mark.parametrize('ratio,price,volume', [(10, 10, 1000), (.1, 1000, 10)])
def test_forward_reverse_economic_units(ratio, price, volume):
    p, v = unit.map_units(100., 100., ratio)
    assert (p, v) == (price, volume)
    assert p*v == 10000
    assert unit.map_units(120., 1., ratio)[0]/p == 1.2


def test_independent_bases_do_not_double_adjust_and_unbound_refused():
    assert unit.map_units(10., 1000., 10., 'DECISION_SHARE_UNITS', 'DECISION_SHARE_UNITS') == (10., 1000.)
    assert unit.map_units(10., 100., 10., 'DECISION_SHARE_UNITS', unit.RAW_BASIS) == (10., 1000.)
    with pytest.raises(ValueError, match='source units'):
        unit.map_units(10., 100., 10., unit.RAW_BASIS, 'OTHER_VENDOR_UNKNOWN')


def test_event_direction_cash_duplicate_and_two_events():
    e = event()
    cash = {**e, 'event_type': 'CASH_DIVIDEND', 'forward_adj_factorA': .987, 'forward_adj_factorB': 0,
            'new_shares_per_old_share': 999}
    two = event('2024-01-10', 2)
    events = [e, dict(e), cash, two]
    assert len(unit.canonical_events(events)) == 2
    assert unit.share_factor(events, 'NVDA', clock('2024-01-04', '16:00'), clock('2024-01-10', '09:45')) == 20
    assert unit.share_factor(events, 'NVDA', clock('2024-01-05', '09:30'), clock('2024-01-10', '09:45')) == 2
    assert unit.share_factor(events, 'NVDA', clock('2024-01-10', '09:30'), clock('2024-01-10', '09:45')) == 1
    with pytest.raises(ValueError, match='Conflicting duplicate'):
        unit.canonical_events([e, {**e, 'new_shares_per_old_share': 5}])
    with pytest.raises(ValueError, match='complex'):
        unit.canonical_events([{**e, 'event_type': 'SPIN_OFF'}])


def test_event_clock_availability_and_future_are_not_backfilled():
    e = event()
    later = event('2026-06-01', 17, available='2026-01-01')
    args = ('NVDA', clock('2024-01-04', '16:00'), clock('2024-01-05', '09:45'))
    assert unit.share_factor([e], *args) == unit.share_factor([e, later], *args) == 10
    assert unit.share_factor([e], 'NVDA', args[1], clock('2024-01-05', '09:29')) == 1
    with pytest.raises(ValueError, match='not knowable'):
        unit.share_factor([event(available='2024-01-06')], *args)
    with pytest.raises(ValueError, match='interval'):
        unit.share_factor([e], 'NVDA', args[1], clock('2026-01-01', '09:45'))


def inputs_with_holes():
    dates = pd.bdate_range('2024-01-01', periods=22).strftime('%Y-%m-%d').tolist()
    frame = pd.DataFrame({'date': dates, 'opening_price': 10., 'regular_close': 10., 'window_volume': 100.,
        'regular_close_utc': [clock(d, '16:00') for d in dates],
        'opening_unit_time_utc': [clock(d, '09:30') for d in dates]})
    return dates, frame


def test_previous20_means_calendar_sessions_min10_no_missing_zero():
    dates, frame = inputs_with_holes()
    # Ten valid sessions in previous20; older index0 must never rescue or distort mean.
    frame.loc[0, 'window_volume'] = 1e8
    frame.loc[1:10, 'window_volume'] = np.nan
    predictions = pd.DataFrame({'sample_id': ['s'], 'ticker': ['NVDA'], 'date': [dates[-1]],
        'prediction_at_utc': [clock(dates[-1], '09:45')]})
    got = unit.recover_ticker(predictions, frame, []).iloc[0]
    assert got.history_calendar_sessions == 20
    assert got.history_valid_windows == 10
    assert got.v == 0
    frame.loc[11, 'window_volume'] = np.nan
    got = unit.recover_ticker(predictions, frame, []).iloc[0]
    assert got.history_valid_windows == 9 and np.isnan(got.v)
    assert got.v_reason.startswith('FEWER_THAN_10')


def test_only_pre_split_history_sides_change_and_future_event_no_effect():
    dates, frame = inputs_with_holes()
    split_date = dates[15]
    frame.loc[:14, ['opening_price', 'regular_close']] = 100.
    frame.loc[15:, 'window_volume'] = 1000.
    e = event(split_date, 10, available=dates[0])
    predictions = pd.DataFrame({'sample_id': ['s'], 'ticker': ['NVDA'], 'date': [dates[-1]],
        'prediction_at_utc': [clock(dates[-1], '09:45')]})
    result = unit.recover_ticker(predictions, frame, [e])
    assert result.v.iloc[0] == 0 and result.g.iloc[0] == 0
    future = event('2026-06-01', 37, available='2026-01-02')
    pd.testing.assert_frame_equal(result, unit.recover_ticker(predictions, frame, [e, future]), check_exact=True)


def test_half_day_close_exact_and_missing_opening_bar_stays_missing():
    date = '2024-07-03'
    calendar = pd.DataFrame({'date': [date], 'market_open_utc': [clock(date, '09:30')],
        'market_close_utc': [clock(date, '13:00')]})
    rows = []
    for c in [f'09:{m:02}' for m in range(31, 45)]+['13:00', '16:00']:
        price = 11. if c=='13:00' else 777. if c=='16:00' else 10.
        rows.append({'symbol': 'NVDA', 'timestamp_utc': clock(date,c), 'open': price, 'close': price,
                     'high': price, 'low': price, 'volume': 100.})
    bars = pd.DataFrame(rows)
    result = unit.summarize_unit_inputs(bars, calendar).iloc[0]
    assert result.regular_close == 11 and result.window_volume == 1400
    result = unit.summarize_unit_inputs(bars[bars.timestamp_utc.ne(clock(date,'09:33'))], calendar).iloc[0]
    assert np.isnan(result.window_volume) and result.opening_price == 10


def test_gap_uses_immediately_previous_session_not_last_nonmissing():
    dates, frame = inputs_with_holes()
    frame.loc[20, 'regular_close'] = np.nan
    predictions = pd.DataFrame({'sample_id': ['s'], 'ticker': ['NVDA'], 'date': [dates[-1]],
        'prediction_at_utc': [clock(dates[-1], '09:45')]})
    result = unit.recover_ticker(predictions, frame, []).iloc[0]
    assert np.isnan(result.g) and result.v == 0
    assert result.g_reason.startswith('MISSING_OR_INVALID_EXACT')


def test_recovery_changes_only_authorized_fields_preserves_labels_and_missing_flags():
    full = pd.DataFrame({'sample_id': ['one','two'], 'prediction_eligible': [True,False],
        'ticker': ['NVDA','ANOTHER'], 'date': ['2024-01-10']*2, 'g': [np.nan]*2, 'v': [np.nan]*2,
        'abs_g': [np.nan]*2, 'a': [np.nan]*2, 'o': [.1,.2], 'd': [.02,.03], 'e': [.4,.5],
        'ov': [np.nan]*2, 'o_abs_g': [np.nan]*2, 'oa': [np.nan]*2, 'dv': [np.nan]*2,
        'oe': [.04,.1], 'de': [.008,.015], 'y_H15': [1,np.nan], 'y_H60': [np.nan,0],
        'quality_gap_unit_uncertified': [1.]*2, 'quality_volume_unit_uncertified': [1.]*2,
        'unit_gap_reason': ['OLD']*2, 'unit_volume_reason': ['OLD']*2})
    audit = pd.DataFrame({'sample_id': ['one'], 'g': [-.2], 'v': [.3], 'g_certified': [True],
                         'v_certified': [True], 'g_reason': ['OK'], 'v_reason': ['OK']})
    result = unit.apply_recovery(full, audit)
    assert result.ov.iloc[0] == .03 and result.oa.iloc[0] == -.1
    assert result.quality_gap_unit_uncertified.tolist() == [0., 1.]
    assert result.quality_volume_unit_uncertified.tolist() == [0., 1.]
    assert np.isnan(result.g.iloc[1])
    pd.testing.assert_frame_equal(full[[c for c in full if c not in unit.CHANGED_COLUMNS]],
                                 result[[c for c in full if c not in unit.CHANGED_COLUMNS]], check_exact=True)


def test_core_gate_keeps_label_missing_prediction_in_stock_quarter_denominator():
    dates = pd.bdate_range('2022-01-03', '2023-03-31').strftime('%Y-%m-%d').tolist()
    panel = pd.DataFrame({'sample_id': dates, 'ticker': 'NVDA', 'date': dates, 'g': .1, 'v': .2})
    for i, col in enumerate(unit.NEW_INTERACTIONS):
        panel[col] = np.arange(len(panel), dtype=float)*(i+1)
    for h in unit.parent_data.HORIZONS:
        panel['y_'+h] = 1.
        panel['label_available_'+h] = [clock(d,'12:31') for d in dates]
    test = panel.date.ge('2023-01-01')
    # Only H15 labels disappear; every original prediction remains denominator.
    panel.loc[test, 'y_H15'] = np.nan
    panel.loc[panel.index[test][:7], 'g'] = np.nan
    audit = panel[['sample_id']].assign(g_certified=True, v_certified=True)
    gate = unit.core_gate(panel,audit)
    q = next(x for x in gate['stock_quarter'] if x['ticker']=='NVDA' and x['quarter']=='2023Q1')
    assert q['eligible_prediction_rows'] == int(test.sum())
    assert q['g_v_joint_rows'] == int(test.sum())-7 and q['status']=='FAIL'
    final = {x['horizon']: x for x in gate['training_folds'] if x['quarter']=='FINAL'}
    assert final['H15']['train_rows'] < final['H60']['train_rows']
    assert len(gate['training_folds']) == 39 and len(gate['stock_quarter']) == 48
    with pytest.raises(ValueError, match='denominator'):
        unit.core_gate(panel, audit.iloc[:-1])
    with pytest.raises(ValueError, match='denominator'):
        unit.core_gate(panel, pd.concat([audit, audit.iloc[:1]], ignore_index=True))


"""Concentrated full-state runner checks; all data synthetic, zero estimator fits.

Run after installing the shared entrypoint, with pytest --basetemp pointing to
the current external cache. Mock fit events test accounting, not solver runs.
"""
import copy
import json
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn._loss.loss import HalfBinomialLoss
from sklearn.linear_model._linear_loss import LinearModelLoss

from scripts.research.fast3 import opening_state_study as state


RECOVERED = ("g", "abs_g", "v", "a", "ov", "o_abs_g", "oa", "dv")
UNIT_QUALITY = ("quality_gap_unit_uncertified", "quality_volume_unit_uncertified")


@pytest.fixture(autouse=True)
def forbid_actual_estimator_fits(monkeypatch, record_testsuite_property):
    def forbidden(*args, **kwargs):
        pytest.fail("This directed runner suite must execute zero estimator fits")
    monkeypatch.setattr(state.LogisticRegression, "fit", forbidden)
    record_testsuite_property("share_unit_runner_actual_estimator_fits", 0)


def full_config():
    return {"task_id": state.FULL_STATE_TASK,
            "main_columns": list(state.STATE_MAIN),
            "interaction_columns": list(state.STATE_INTERACTIONS),
            "quality_columns": list(UNIT_QUALITY),
            "fit_cutoff_utc": "2026-01-01T00:00:00Z",
            "core_input_gate": {"status": "PASS"}}


def synthetic_panel():
    dates = list(pd.bdate_range("2022-01-03", periods=180))
    dates += [pd.Period(q, freq="Q").start_time + pd.offsets.BDay(0)
              for q in state.QUARTERS]
    frame = pd.MultiIndex.from_product(
        [[d.strftime("%Y-%m-%d") for d in dates], sorted(state.STATE_TICKERS)],
        names=["date", "ticker"]).to_frame(index=False)
    rng = np.random.default_rng(104729)
    for name in state.STATE_MAIN:
        frame[name] = rng.normal(0, .01, len(frame))
    frame["abs_g"], frame["abs_d"] = frame.g.abs(), frame.d.abs()
    frame["a"] = np.sign(frame.g) * np.sign(frame.o)
    for name, (left, right) in state.STATE_INTERACTIONS.items():
        frame[name] = frame[left] * frame[right]
    for name in UNIT_QUALITY:
        frame[name] = 0.
    frame["unit_gap_reason"], frame["unit_volume_reason"] = "OK", "OK"
    frame["sample_id"] = frame.ticker + "|" + frame.date
    frame["security_uid"], frame["eligible"], frame["prediction_eligible"] = frame.ticker, True, True
    clocks = {"prediction_at_utc": "09:45", "feature_cutoff_utc": "09:44", "label_start_utc": "09:46"}
    for horizon, (end, mature) in state.HORIZONS.items():
        clocks["label_end_"+horizon], clocks["label_available_"+horizon] = end, mature
        frame["y_"+horizon] = np.arange(len(frame)) % 2
        frame["return_"+horizon] = np.where(frame["y_"+horizon].eq(1), .01, -.01)
        frame["label_reason_"+horizon] = "OK"
    for name, clock in clocks.items():
        frame[name] = pd.to_datetime(frame.date+" "+clock).dt.tz_localize("America/New_York").dt.tz_convert("UTC")
    return frame


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    state.evidence.write_json(path, data)


def repin(case, name):
    manifest_path = case["parent"] / "delivery-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for row in manifest["artifacts"]:
        if row["path"] == name:
            row["sha256"] = state.evidence.sha(case["parent"] / name)
            break
    else:
        raise AssertionError("Synthetic component was not pinned")
    write_json(manifest_path, manifest)
    case["config"]["parent_manifest_sha256"] = state.evidence.sha(manifest_path)


@pytest.fixture
def reuse_case(tmp_path, monkeypatch):
    """Real files/hashes, fictional objects and rows; no historical file reads."""
    parent, dataset = tmp_path/"parent", tmp_path/"parent"/"research-data"
    dataset.mkdir(parents=True)
    new = synthetic_panel()
    old = new.copy(deep=True)
    old[list(RECOVERED)] = np.nan
    old[list(UNIT_QUALITY)] = 1.
    old["unit_gap_reason"], old["unit_volume_reason"] = "UNBOUND", "UNBOUND"
    old.to_parquet(dataset/"panel.parquet", index=False)
    old.to_parquet(dataset/"sample_manifest.parquet", index=False)
    cfg = full_config()
    parent_cfg = {**cfg, "task_id": state.STATE_TASK,
                  "panel_sha256": state.evidence.sha(dataset/"panel.parquet"),
                  "sample_manifest_sha256": state.evidence.sha(dataset/"sample_manifest.parquet")}
    write_json(dataset/"data_config.json", parent_cfg)
    monkeypatch.setattr(state, "state_code_identity", lambda config=None: {"synthetic_shared_source": "fixed"})
    state.freeze_state(dataset, parent/"evaluation")
    models = parent/"evaluation"/"models"
    models.mkdir()
    columns = [*state.STATE_MAIN, *UNIT_QUALITY, *state.STATE_INTERACTIONS]
    # Synthetic saved column statistics, intentionally constructed without fitting.
    pp = {"columns": columns, "quality_columns": list(UNIT_QUALITY),
          "imputer": SimpleNamespace(statistics_=np.zeros(len(columns))),
          "scaler": SimpleNamespace(mean_=np.zeros(len(columns)), scale_=np.ones(len(columns)))}
    priors, prediction_parts = [], []
    for quarter in (*state.QUARTERS, "FINAL"):
        boundary = state.GLOBAL_CUTOFF if quarter == "FINAL" else state.quarter_boundary(quarter)
        for horizon in state.HORIZONS:
            train = state.training_rows(old, horizon, boundary)
            prior = state.prior_probability(train, horizon)
            priors.append({"quarter": quarter, "horizon": horizon, "p_up": prior,
                           "train": state.state_segment(train, horizon), "is_estimate": True})
            if quarter == "FINAL":
                continue
            test = old[pd.PeriodIndex(old.date, freq="Q") == quarter]
            for model_id in ("B0", "B1", "BM"):
                bundle = state.constant_state(model_id, horizon, .5 if model_id == "B0" else prior)
                rows, _ = state.prediction_rows(bundle, test, horizon, model_id, prior, quarter)
                prediction_parts.append(rows)
                if model_id == "BM":
                    bundle = {"kind": "learner", "model_id": "BM", "preprocessor": pp,
                              "config": parent_cfg, "trained_tickers": list(state.STATE_TICKERS)}
                joblib.dump(bundle, models/f"{quarter}_{horizon}_{model_id}.joblib")
    pd.concat(prediction_parts, ignore_index=True).to_parquet(parent/"evaluation"/"oos_predictions.parquet", index=False)
    write_json(parent/"evaluation"/"prior_estimates.json", priors)
    write_json(parent/"evaluation"/"diagnostics.json", [])
    write_json(parent/"evaluation"/"model_metadata.json", [])
    files = sorted(p for p in parent.rglob("*") if p.is_file())
    # Preserve the real parent manifest's stated shape without copying its data.
    for index in range(len(files), 251):
        path = parent/"synthetic-unused"/f"{index}.json"
        write_json(path, {"fixture_only": index})
        files.append(path)
    write_json(parent/"delivery-manifest.json", {"artifacts": [
        {"path": p.relative_to(parent).as_posix(), "sha256": state.evidence.sha(p)} for p in files]})
    cfg.update(parent_result_root=str(parent), parent_manifest_sha256=state.evidence.sha(parent/"delivery-manifest.json"))
    return {"parent": parent, "old": old, "new": new, "config": cfg, "tmp": tmp_path}


@pytest.mark.parametrize("status", [None, "PARTIAL", "UNRESOLVED", "FAIL"])
def test_full_reuse_requires_pass_before_reading_parent(status):
    cfg = {**full_config(), "core_input_gate": {"status": status}, "parent_result_root": "must-not-be-read"}
    with pytest.raises(ValueError, match="FULL_STATE_INPUT_GAP"):
        state.full_state_baseline_reuse(pd.DataFrame(), cfg)


def test_full_public_identity_does_not_change_internal_design_ids():
    full, parent = full_config(), {"task_id": state.STATE_TASK}
    assert state.is_full_state(full) and not state.is_full_state(parent)
    assert [state.public_state_id(m, full) for m in ("M0", "M1", "BM", "B0", "B1")] == ["M0_FULL", "M1_FULL", "BM", "B0", "B1"]
    assert state.public_state_id("M1", parent) == "M1"


def test_full_fixed_objective_date_weights_and_retry_parameters_unchanged():
    frame = pd.DataFrame({"date": ["2025-01-02"]*4+["2025-01-03"], "ticker": ["NVDA"]*5})
    weights = state.state_date_weights(frame, full_config())
    np.testing.assert_array_equal(weights, [.25, .25, .25, .25, 1.])
    params = state.state_parameters(weights.sum())
    assert params["C"] == 50 and params["solver"] == "lbfgs" and params["tol"] == 1e-6
    assert params["class_weight"] is None and params["fit_intercept"] is True
    assert params["l1_ratio"] == 0 and params["max_iter"] == 2000
    retry = state.state_parameters(weights.sum(), 4000)
    assert {k:v for k,v in retry.items() if k != "max_iter"} == {k:v for k,v in params.items() if k != "max_iter"}
    X, y, beta = np.array([[1., 1/np.sqrt(10)], [-.4, 0.]]), np.array([1., 0.]), np.array([.3, .6, .7])
    score = X@beta[:-1]+beta[-1]
    observed, _ = LinearModelLoss(HalfBinomialLoss(), fit_intercept=True).loss_gradient(beta, X, y, l2_reg_strength=.01)
    manual = np.mean(np.logaddexp(0, score)-y*score)+.01/2*(.3**2+10*(.6/np.sqrt(10))**2)
    assert observed == pytest.approx(manual, rel=0, abs=1e-15)
    contract = state.state_model_contract(full_config())
    assert contract == state.state_model_contract({**full_config(), "task_id": state.STATE_TASK})
    assert contract["public_intercept_penalty"] == 0
    assert contract["calibration"] is contract["cv"] is contract["early_stopping"] is None


def test_full_M0_M1_share_all_main_flags_and_stock_columns_T_only():
    frame, cfg = synthetic_panel(), full_config()
    train = frame[frame.date.lt("2023-01-01")].copy()
    train.loc[0, ["v", "ov", "dv"]] = np.nan
    pp = state.make_preprocessor(train, cfg)
    saved = copy.deepcopy(pp["metadata"])
    m0, _ = state.state_design(pp, train, "M0", cfg, train.ticker.unique())
    m1, _ = state.state_design(pp, train, "M1", cfg, train.ticker.unique())
    pd.testing.assert_frame_equal(m0, m1.drop(columns=list(state.STATE_INTERACTIONS)), check_exact=True)
    assert len([c for c in m0 if c.startswith("missing_")]) == 21
    assert m0.loc[0, "missing_v"] == m0.loc[0, "missing_ov"] == m0.loc[0, "missing_dv"] == 1
    np.testing.assert_allclose(m0.stock_intercept_NVDA, train.ticker.eq("NVDA")/np.sqrt(10), rtol=0, atol=0)
    test = frame[frame.date.ge("2023-01-01")].copy()
    test["g"], test["abs_g"], test["v"], test["a"] = 1e6, 1e6, 1e6, 1.
    for name, (left, right) in state.STATE_INTERACTIONS.items():
        test[name] = test[left]*test[right]
    design, clips = state.state_design(pp, test, "M1", cfg, train.ticker.unique())
    assert design.g.le(5).all() and design.g.ge(-5).all() and clips["g"] == len(test)
    assert pp["metadata"] == saved


def test_full_baseline_reuse_is_component_exact_with_zero_new_fits(reuse_case, monkeypatch):
    monkeypatch.setattr(state, "make_preprocessor", lambda *_: pytest.fail("Reuse must not fit preprocessing"))
    result = state.full_state_baseline_reuse(reuse_case["new"], reuse_case["config"])
    assert result["status"] == "EXACT_COMPONENT_REUSE"
    assert (result["BM_objects_reused"], result["B0_B1_objects_reused"], result["B1_estimates_reused"]) == (36, 72, 39)
    assert result["new_supervised_fits"] == result["new_preprocessor_fits"] == 0
    assert len(result["T_E_market_design_checks"]) == 72
    assert result["training_prior_checks_are_validation_not_new_estimates"] is True


@pytest.mark.parametrize("field", ["o", "q", "eligible", "feature_cutoff_utc", "return_H1230"])
def test_full_reuse_rejects_nonallowlisted_panel_changes(reuse_case, field):
    new = reuse_case["new"].copy()
    if field == "eligible":
        new.loc[0, field] = False
    elif field == "feature_cutoff_utc":
        new.loc[0, field] += pd.Timedelta(minutes=1)
    else:
        new.loc[0, field] += .001
    with pytest.raises((AssertionError, ValueError)):
        state.full_state_baseline_reuse(new, reuse_case["config"])


def test_full_reuse_rejects_component_hash_changes_before_loading(reuse_case):
    path = reuse_case["parent"]/"evaluation"/"models"/"2023Q1_H15_BM.joblib"
    path.write_bytes(b"corrupt synthetic object")
    with pytest.raises(ValueError, match="PARENT_COMPONENT_CHANGED"):
        state.full_state_baseline_reuse(reuse_case["new"], reuse_case["config"])


def test_full_reuse_rejects_manifest_identity_drift(reuse_case):
    reuse_case["config"]["parent_manifest_sha256"] = "0"*64
    with pytest.raises(ValueError, match="PARENT_MANIFEST"):
        state.full_state_baseline_reuse(reuse_case["new"], reuse_case["config"])


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "wrong_value"])
def test_full_reuse_requires_all_39_unique_matching_priors(reuse_case, mutation):
    name = "evaluation/prior_estimates.json"
    path = reuse_case["parent"]/name
    priors = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "missing":
        priors.pop()
    elif mutation == "duplicate":
        priors[-1] = copy.deepcopy(priors[0])
    else:
        priors[0]["p_up"] += .01
    write_json(path, priors)
    repin(reuse_case, name)
    with pytest.raises(ValueError, match="PRIOR"):
        state.full_state_baseline_reuse(reuse_case["new"], reuse_case["config"])


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_full_reuse_rejects_missing_or_duplicate_prediction_rows(reuse_case, mutation):
    name = "evaluation/oos_predictions.parquet"
    path = reuse_case["parent"]/name
    rows = pd.read_parquet(path)
    rows = rows.iloc[1:].copy() if mutation == "missing" else pd.concat([rows, rows.iloc[[0]]], ignore_index=True)
    rows.to_parquet(path, index=False)
    repin(reuse_case, name)
    with pytest.raises(ValueError, match="BASELINE_PREDICTION"):
        state.full_state_baseline_reuse(reuse_case["new"], reuse_case["config"])


def test_full_BM_design_never_reads_stock_effects_or_quality(reuse_case):
    model = joblib.load(reuse_case["parent"]/"evaluation"/"models"/"2023Q1_H15_BM.joblib")
    frame = reuse_case["new"]
    complete, _ = state.state_design(model["preprocessor"], frame, "BM", model["config"], model["trained_tickers"])
    minimal, _ = state.state_design(model["preprocessor"], frame[["ticker", *state.STATE_MARKET]], "BM", model["config"], model["trained_tickers"])
    assert list(minimal) == [*state.STATE_MARKET, *["missing_"+c for c in state.STATE_MARKET]]
    pd.testing.assert_frame_equal(complete, minimal, check_exact=True)


def test_full_freeze_records_75_new_fits_39_priors_reuse_and_same_folds(reuse_case):
    dataset, output = reuse_case["tmp"]/"new-data", reuse_case["tmp"]/"new-evaluation"
    dataset.mkdir()
    for name in ("panel.parquet", "sample_manifest.parquet"):
        reuse_case["new"].to_parquet(dataset/name, index=False)
    cfg = {**reuse_case["config"], "panel_sha256": state.evidence.sha(dataset/"panel.parquet"),
           "sample_manifest_sha256": state.evidence.sha(dataset/"sample_manifest.parquet")}
    write_json(dataset/"data_config.json", cfg)
    protocol = state.freeze_state(dataset, output)
    assert protocol["task_id"] == state.FULL_STATE_TASK
    assert protocol["budget"]["planned_supervised"] == 75
    assert protocol["budget"]["quarterly_models"] == 72
    assert protocol["budget"]["hard_cap"] == 132
    assert protocol["budget"]["BM_new_fits"] == 0
    assert protocol["budget"]["B1_reused_estimates"] == 39
    assert all(p["models"] == (["M1"] if p["quarter"] == "FINAL" else ["M0", "M1"]) for p in protocol["fit_plan"])
    pd.testing.assert_frame_equal(pd.read_parquet(output/"fold_sample_ids.parquet"),
                                 pd.read_parquet(reuse_case["parent"]/"evaluation"/"fold_sample_ids.parquet"), check_exact=True)
    saved = json.loads((output/"frozen_protocol.json").read_text(encoding="utf-8"))
    parent_protocol = json.loads((reuse_case["parent"]/"evaluation"/"frozen_protocol.json").read_text(encoding="utf-8"))
    final_folds = [row for row in saved["folds"] if row["quarter"] == "FINAL"]
    assert len(final_folds) == 3
    assert all(row["prediction"]["rows"] == 0 and row["prediction"]["label_maturity_max"] == "NaT" for row in final_folds)
    assert saved["folds"] == parent_protocol["folds"]
    assert protocol["ADOPTION_ALLOWED"] is protocol["LIVE_TRADING_ALLOWED"] is protocol["TRADE_API_ALLOWED"] is False
    assert not (output/"fit_events.jsonl").exists()


@pytest.mark.parametrize("failure", ["convergence_then_success", "convergence_twice", "ordinary", "preflight"])
def test_full_recorded_fit_failure_retry_and_public_identity(tmp_path, monkeypatch, failure):
    train, cfg, pp = synthetic_panel(), full_config(), object()
    protocol = {"panel_sha256": "synthetic", "source_code": {}, "model_contract": {"L2": .01}}
    budget = state.evidence.Budget(tmp_path/"mock-fit-events.jsonl", hard_cap=132, retry_cap=21)
    calls = []
    def mock_fit(t, h, model_id, config, preprocessor=None, max_iter=None, on_fit=None):
        calls.append((t.sample_id.tolist(), h, model_id, dict(config), preprocessor, max_iter))
        if failure == "preflight":
            raise state.FitFailure("mock preflight; no estimator fit")
        on_fit({"status": "STARTED"})
        if failure == "ordinary":
            on_fit({"status": "FAILED"})
            raise state.FitFailure("mock ordinary failure; no estimator fit")
        if len(calls) == 1 or failure == "convergence_twice":
            on_fit({"status": "FAILED"})
            raise state.ConvergenceFailure("mock convergence failure; no estimator fit")
        on_fit({"status": "FINISHED"})
        return {"metadata": {}}
    monkeypatch.setattr(state, "fit_state", mock_fit)
    if failure == "convergence_then_success":
        bundle = state.recorded_state_fit(budget, train, "H1230", "M1", cfg, pp, "FINAL", protocol)
        assert bundle["model_id"] == "M1" and bundle["public_model_id"] == "M1_FULL"
        assert bundle["task_id"] == state.FULL_STATE_TASK and bundle["TRADE_API_ALLOWED"] is False
    else:
        with pytest.raises(state.FitFailure):
            state.recorded_state_fit(budget, train, "H1230", "M1", cfg, pp, "FINAL", protocol)
    expected_calls = 2 if failure.startswith("convergence") else 1
    assert len(calls) == expected_calls
    assert budget.calls == (0 if failure == "preflight" else expected_calls)
    assert budget.retries == int(expected_calls == 2)
    assert all(e["public_model_id"] == "M1_FULL" for e in budget.events)
    if expected_calls == 2:
        assert calls[0][:-1] == calls[1][:-1]
        assert [v[-1] for v in calls] == [2000, 4000]
        assert len({e["cache_key"] for e in budget.events}) == 1


def test_full_fit_hard_cap_prevents_any_call(tmp_path, monkeypatch):
    budget = state.evidence.Budget(tmp_path/"cap-mock.jsonl", hard_cap=132, retry_cap=21)
    budget.calls = 132
    monkeypatch.setattr(state, "fit_state", lambda *_a, **_k: pytest.fail("hard cap must precede fit"))
    with pytest.raises(RuntimeError, match="FIT_BUDGET_EXHAUSTED"):
        state.recorded_state_fit(budget, synthetic_panel(), "H15", "M0", full_config(), None,
                                 "2023Q1", {"panel_sha256": "synthetic", "source_code": {}, "model_contract": {}})
    assert budget.calls == 132 and not budget.events


@pytest.mark.parametrize("ordinary_failure", [False, True])
def test_full_mock_orchestration_75_calls_baseline_reuse_and_B0_default(reuse_case, monkeypatch, ordinary_failure):
    """Execute orchestration with mocked solvers/evaluation, never historical data.

    The 75 mock STARTED events are explicitly separate from actual estimator
    fits (zero), and assert the run's control flow rather than model performance.
    """
    dataset, output = reuse_case["tmp"]/"mock-data", reuse_case["tmp"]/"mock-evaluation"
    dataset.mkdir()
    for name in ("panel.parquet", "sample_manifest.parquet"):
        reuse_case["new"].to_parquet(dataset/name, index=False)
    cfg = {**reuse_case["config"], "panel_sha256": state.evidence.sha(dataset/"panel.parquet"),
           "sample_manifest_sha256": state.evidence.sha(dataset/"sample_manifest.parquet")}
    write_json(dataset/"data_config.json", cfg)
    state.freeze_state(dataset, output)
    calls, preprocessors = [], []
    def mock_preprocessor(*args):
        marker = object()
        preprocessors.append(marker)
        return marker
    def mock_fit(train, horizon, model_id, config, preprocessor=None, max_iter=None, on_fit=None):
        calls.append((horizon, model_id, config["fit_cutoff_utc"], preprocessor))
        on_fit({"status": "STARTED", "synthetic_mock_only": True})
        if ordinary_failure and model_id == "M1" and horizon == "H1230":
            on_fit({"status": "FAILED", "synthetic_mock_only": True})
            raise state.FitFailure("synthetic ordinary failure, zero estimator fits")
        on_fit({"status": "FINISHED", "synthetic_mock_only": True})
        return {"metadata": {"max_label_available_at": train["label_available_"+horizon].max().isoformat()}}
    monkeypatch.setattr(state, "make_preprocessor", mock_preprocessor)
    monkeypatch.setattr(state, "fit_state", mock_fit)
    monkeypatch.setattr(state, "prior_probability", lambda *_: pytest.fail("FULL training must consume saved priors without new estimation"))
    monkeypatch.setattr(state, "predict_state", lambda _bundle, frame: {
        "p_up": np.full(len(frame), .55), "raw_score": np.full(len(frame), np.log(.55/.45)), "clip_counts": {}})
    monkeypatch.setattr(state, "evaluate_state", lambda *_args: {
        "PRIMARY_H1230_VERDICT": "NO_RELIABLE_ADVANTAGE", "H15_VERDICT": "NO_RELIABLE_ADVANTAGE",
        "H60_VERDICT": "NO_RELIABLE_ADVANTAGE", "STATE_INTERACTION_VERDICT": "NO_RELIABLE_ADVANTAGE"})
    result = state.train_state(dataset, output)
    assert len(calls) == 75 and len(preprocessors) == 39
    assert {c[1] for c in calls} == {"M0", "M1"}
    assert all(calls[i][3] is calls[i+1][3] for i in range(0, 72, 2))
    assert result["fit_counts"]["BM_new_fits"] == result["fit_counts"]["prior_estimates"] == 0
    assert result["fit_counts"]["supervised_total"] == 75
    assert result["fit_counts"]["quarterly"] == 72 and result["fit_counts"]["final"] == 3
    assert result["fit_counts"]["B1_estimates_reused"] == 39
    assert result["fit_counts"]["failed"] == (13 if ordinary_failure else 0)
    oos = pd.read_parquet(output/"oos_predictions.parquet")
    old_oos = pd.read_parquet(reuse_case["parent"]/"evaluation"/"oos_predictions.parquet")
    for model_id in ("B0", "B1", "BM"):
        new_rows = oos[oos.model_id.eq(model_id)].loc[:, old_oos.columns].reset_index(drop=True)
        old_rows = old_oos[old_oos.model_id.eq(model_id)].reset_index(drop=True)
        # All-null object audit columns can become nullable strings on concat.
        # Normalize only their text/null representation; all other dtypes stay exact.
        for frame in (new_rows, old_rows):
            for name in ("fit_cutoff", "fallback_reason"):
                assert frame[name].dropna().map(lambda value: isinstance(value, str)).all()
                frame[name] = frame[name].astype(pd.StringDtype(storage="python"))
        pd.testing.assert_frame_equal(new_rows, old_rows, check_exact=True)
    assert oos.groupby(["quarter", "horizon", "model_id"]).size().eq(4).all()
    assert oos.loc[oos.model_id.eq("M1"), "public_model_id"].eq("M1_FULL").all()
    if ordinary_failure:
        failed = oos[oos.model_id.eq("M1") & oos.horizon.eq("H1230")]
        assert failed.actual_predictor.eq("B1").all() and failed.public_actual_predictor.eq("B1").all()
        assert failed.fallback_reason.str.startswith("MODEL_FAILURE_B1").all()
    default = joblib.load(output/"default_predictor.joblib")
    assert default["model_id"] == "B0" and default["role"] == "NO_MODEL_SIGNAL"
    assert default["task_id"] == state.FULL_STATE_TASK
    assert default["ADOPTION_ALLOWED"] is default["LIVE_TRADING_ALLOWED"] is default["TRADE_API_ALLOWED"] is False
    assert "BROKER_ACTION_ALLOWED" not in default
    for horizon in state.HORIZONS:
        model = joblib.load(output/f"final_M1_FULL_{horizon}.joblib")
        assert model["model_id"] == "M1" and model["public_model_id"] == "M1_FULL"
        assert model["role"] == "RESEARCH_REPRODUCTION_ONLY"
    write_json(output/"ACTUAL_ESTIMATOR_FIT_COUNTS.json", {
        "actual_estimator_fits": 0, "mock_fit_invocations": len(calls), "mock_fit_events_are_scientific_fits": False})
