"""Synthetic annual opportunity coverage, clock, and projection counterexamples."""
from dataclasses import replace
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.inference import reused_policy_inputs as inputs


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def source(tmp_path):
    def make(frame=None, receipt_changes=None):
        if frame is None:
            frame = pd.DataFrame(dict(
                signal_date=pd.to_datetime(["2023-01-03", "2023-01-03"]),
                ticker=["A", "B"], HGB_mu=[.01, .02], HGB_uncertainty=[.1, .2],
                source_fit_cutoff=pd.to_datetime(["2023-01-01"] * 2),
                fold_year=[2023, 2023],
                forbidden_target=[999., -999.], forbidden_account_pnl=[99999., -99999.],
            ))
        path = tmp_path / "annual.parquet"
        frame.to_parquet(path, index=False)
        receipt = dict(status="REAL_TRUE_OOF", year=2023, calibrated=True,
                       sha256=digest(path), source_fit_cutoff="2023-01-01",
                       source_label_maturity_max="2022-12-30 00:00:00")
        receipt.update(receipt_changes or {})
        receipt_path = tmp_path / "receipt.json"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        reference = inputs.AnnualOpportunityRef(
            2023, str(path), digest(path), str(receipt_path), digest(receipt_path),
            "a" * 64, "b" * 64, "2022-12-30",
        )
        return frame, reference
    return make


def call(reader, *, assets=("A", "B", "C"), eligible=(True, False, False),
         units=(0., 1., 0.), weights=None, day="2023-01-03",
         asof="2023-01-03T21:00:00+00:00"):
    return reader.for_decision(day, assets, eligible, units,
                               held_weights=weights, decision_as_of=asof)


def test_actual_held_and_eligible_union_preserves_order_without_future_holdings(source):
    _, reference = source()
    out = call(inputs.FrozenAnnualOpportunityReader({2023: reference}))
    assert out.assets == ("A", "B", "C")
    assert out.required.tolist() == [True, True, False]
    assert out.mean[:2].tolist() == [.01, .02]
    assert np.isnan(out.mean[2]) and np.isnan(out.uncertainty[2])
    receipt = out.source_receipt
    assert receipt["required_assets"] == ["A", "B"]
    assert receipt["historical_availability_authority"] == "UNKNOWN"
    assert receipt["strict_PIT"] is False
    assert receipt["additional_fit_units"] == receipt["additional_inference_rows"] == 0
    assert receipt["source_sha256"] == reference.sha256
    assert len(receipt["slice_content_sha256"]) == 64
    with pytest.raises(ValueError):
        out.mean[0] = 4


def test_positive_actual_weight_requires_cell_even_when_units_zero(source):
    _, reference = source()
    out = call(inputs.FrozenAnnualOpportunityReader({2023: reference}),
               units=(0., 0., 0.), weights=(0., .3, 0.))
    assert out.required.tolist() == [True, True, False]


def test_missing_held_key_blocks_without_eligibility_shrinking(source):
    _, reference = source()
    with pytest.raises(inputs.OpportunityInputUnavailable, match="MISSING_REQUIRED_OPPORTUNITY_KEY:C"):
        call(inputs.FrozenAnnualOpportunityReader({2023: reference}), units=(0., 1., .01))


@pytest.mark.parametrize("column,value", [
    ("HGB_mu", np.inf), ("HGB_mu", np.nan),
    ("HGB_uncertainty", -.1), ("HGB_uncertainty", np.nan),
])
def test_invalid_required_forecast_cannot_be_ignored_or_imputed(source, column, value):
    frame, _ = source()
    frame.loc[1, column] = value
    _, reference = source(frame)
    with pytest.raises(inputs.OpportunityInputUnavailable, match="INVALID_REQUIRED_OPPORTUNITY_VALUE"):
        call(inputs.FrozenAnnualOpportunityReader({2023: reference}))


def test_duplicate_source_keys_are_not_deduplicated(source):
    frame, _ = source()
    _, reference = source(pd.concat([frame, frame.iloc[:1]], ignore_index=True))
    with pytest.raises(ValueError, match="DUPLICATE_OPPORTUNITY_SOURCE_KEY"):
        call(inputs.FrozenAnnualOpportunityReader({2023: reference}))


@pytest.mark.parametrize("column,value", [
    ("fold_year", 2024), ("source_fit_cutoff", pd.Timestamp("2023-01-02")),
    ("signal_date", pd.Timestamp("2024-01-03")),
])
def test_fold_or_cutoff_mismatch_never_borrows_other_year_model(source, column, value):
    frame, _ = source()
    frame.loc[1, column] = value
    _, reference = source(frame)
    with pytest.raises(ValueError, match="KEY_FOLD_OR_CUTOFF"):
        call(inputs.FrozenAnnualOpportunityReader({2023: reference}))


def test_future_source_footer_blocks_before_body_read(source, monkeypatch):
    frame, _ = source()
    frame.loc[1, "signal_date"] = pd.Timestamp("2026-01-01")
    _, reference = source(frame)
    with pytest.raises(ValueError, match="Forbidden mixed/test input"):
        call(inputs.FrozenAnnualOpportunityReader({2023: reference}))


def test_receipt_identity_checked_before_parquet_read(source, monkeypatch):
    _, reference = source()
    reference = replace(reference, receipt_sha256="0" * 64)
    monkeypatch.setattr(inputs, "guard_parquet", lambda *args: pytest.fail("body reader reached"))
    with pytest.raises(ValueError, match="RECEIPT_SHA"):
        call(inputs.FrozenAnnualOpportunityReader({2023: reference}))


def test_source_physical_hash_is_not_typed_slice_or_receipt_hash(source):
    _, reference = source()
    reference = replace(reference, sha256=reference.receipt_sha256)
    with pytest.raises(ValueError, match="ORIGINAL_ANNUAL_LINEAGE"):
        call(inputs.FrozenAnnualOpportunityReader({2023: reference}))


def test_prior_label_maturity_is_not_waived_for_research(source):
    _, reference = source(receipt_changes={"source_label_maturity_max": "2023-01-01"})
    reference = replace(reference, label_maturity_max="2023-01-01")
    with pytest.raises(ValueError, match="ORIGINAL_ANNUAL_LINEAGE"):
        call(inputs.FrozenAnnualOpportunityReader({2023: reference}))


@pytest.mark.parametrize("asof", ["2023-01-03", "2023-01-04T21:00:00+00:00"])
def test_missing_timezone_or_different_decision_session_is_rejected(source, asof):
    _, reference = source()
    with pytest.raises(ValueError, match="INVALID_OPPORTUNITY_DECISION_CLOCK"):
        call(inputs.FrozenAnnualOpportunityReader({2023: reference}), asof=asof)


def test_annual_opportunity_clock_is_independent_of_prior_close_risk_clock(source):
    _, reference = source()
    # Jan 1 is later than the risk prior close Dec 30, but earlier than this
    # Jan 3 decision. This reader has no risk-clock parameter or backdating.
    out = call(inputs.FrozenAnnualOpportunityReader({2023: reference}))
    assert out.source_receipt["source_fit_cutoff"] == "2023-01-01T05:00:00+00:00"


def test_only_six_prediction_columns_read_and_annual_body_loaded_once(source, monkeypatch):
    _, reference = source()
    original = inputs.guard_parquet
    calls = []
    class File:
        def __init__(self, file):
            self.file, self.schema_arrow = file, file.schema_arrow
        def read(self, *, columns):
            calls.append(columns)
            assert columns == list(inputs.P0_COLUMNS)
            return self.file.read(columns=columns)
    def guard(*args):
        file, metadata = original(*args)
        return File(file), metadata
    monkeypatch.setattr(inputs, "guard_parquet", guard)
    reader = inputs.FrozenAnnualOpportunityReader({2023: reference})
    call(reader)
    call(reader, eligible=(False, True, False), units=(1., 0., 0.))
    assert len(calls) == 1


def test_forbidden_decision_year_stops_without_source_io(monkeypatch):
    monkeypatch.setattr(inputs, "guard_parquet", lambda *args: pytest.fail("source read"))
    with pytest.raises(ValueError, match="OUTSIDE_PRE2026"):
        call(inputs.FrozenAnnualOpportunityReader({}), day="2026-01-02",
             asof="2026-01-02T21:00:00+00:00")


@pytest.mark.parametrize("eligible,units,weights", [
    ((True, np.nan), (0., 0.), None),
    ((True, False), (0., np.nan), None),
    ((True, False), (0., -.01), None),
    ((True, False), (0., 0.), (0., np.inf)),
])
def test_runtime_account_state_cannot_be_guessed(eligible, units, weights):
    with pytest.raises(ValueError, match="INVALID_OPPORTUNITY"):
        inputs.required_opportunity_mask(eligible, units, weights)



def two_member_source(source, invalid=False):
    frame,_=source()
    frame['Ridge_mu']=[.03,.01]
    frame['Ridge_uncertainty']=[.04,.05]
    if invalid:frame.loc[1,'Ridge_mu']=np.nan
    _,ref=source(frame)
    ridge=replace(ref,model_sha256='c'*64,calibration_sha256='d'*64)
    return ref,ridge


def test_existing_ridge_and_explicit_equal_reuse_original_columns_without_fit(source,monkeypatch):
    ref,ridge=two_member_source(source)
    original=inputs.guard_parquet;reads=[]
    class Projection:
        def __init__(self,file):self.file=file
        def __getattr__(self,name):return getattr(self.file,name)
        def read(self,*,columns):
            reads.extend(columns)
            assert not any('target' in c or 'pnl' in c for c in columns)
            return self.file.read(columns=columns)
    def guard(*args):
        file,meta=original(*args)
        return Projection(file),meta
    monkeypatch.setattr(inputs,'guard_parquet',guard)
    ridge_out=call(inputs.FrozenAnnualOpportunityReader({2023:ridge},recipe='RIDGE'))
    assert ridge_out.mean[:2].tolist()==[.03,.01]
    out=call(inputs.FrozenAnnualOpportunityReader({2023:ref},recipe='RIDGE_HGB_EQUAL',ridge_references={2023:ridge}))
    np.testing.assert_allclose(out.mean[:2],[.02,.015])
    np.testing.assert_allclose(out.uncertainty[:2],[.01,.005])
    assert np.isnan(out.mean[2]) and not out.mean.flags.writeable
    r=out.source_receipt
    assert r['additional_fit_units']==r['additional_inference_rows']==0
    assert set(r['member_model_pins'])=={'Ridge','HGB'}
    assert not r['old_P1_P2_identity_claim']
    assert 'NOT_CALIBRATED' in r['uncertainty_scope']
    assert set(reads)<=set(['signal_date','ticker','source_fit_cutoff','fold_year','HGB_mu','HGB_uncertainty','Ridge_mu','Ridge_uncertainty'])


def test_two_member_missing_held_value_or_mismatched_source_never_falls_back_to_hgb(source):
    ref,ridge=two_member_source(source,invalid=True)
    reader=inputs.FrozenAnnualOpportunityReader({2023:ref},recipe='RIDGE_HGB_EQUAL',ridge_references={2023:ridge})
    with pytest.raises(inputs.OpportunityInputUnavailable,match='INVALID_REQUIRED'):
        call(reader)
    reader=inputs.FrozenAnnualOpportunityReader({2023:ref},recipe='RIDGE_HGB_EQUAL',ridge_references={2023:replace(ridge,sha256='0'*64)})
    with pytest.raises(ValueError,match='TWO_MEMBER_ANNUAL'):
        call(reader)



def test_two_model_pto_runs_through_common_account_with_actual_state_across_year(tmp_path):
    from scripts.research.a2.evaluation.continuous_research_account import run_continuous_account
    from scripts.research.a2.inference.reused_feasible_policy import ReusedFeasiblePolicy
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays
    dates=pd.to_datetime(['2023-12-29','2024-01-02','2024-01-03','2024-01-04'])
    assets=tuple(f'SYN{i:02}' for i in range(25));refs={};ridge_refs={}
    for year in (2023,2024):
        rows=[]
        for day in dates[dates.year==year]:
            # Pure fabricated forecasts. Rotate the strong opportunities after first fill.
            first=day<=pd.Timestamp('2024-01-02')
            for i,asset in enumerate(assets):
                mu=.2 if (i<10 if first else i>=15) else -.2
                rows.append(dict(signal_date=day,ticker=asset,HGB_mu=mu,Ridge_mu=mu+.01,
                    HGB_uncertainty=.01,Ridge_uncertainty=.02,source_fit_cutoff=pd.Timestamp(year,1,1),
                    fold_year=year,forbidden_target=999999.))
        frame=pd.DataFrame(rows);path=tmp_path/f'annual_{year}.parquet';frame.to_parquet(path,index=False)
        maturity=f'{year-1}-12-29';receipt=dict(status='REAL_TRUE_OOF',year=year,calibrated=True,
            sha256=digest(path),source_fit_cutoff=f'{year}-01-01',source_label_maturity_max=maturity)
        rp=tmp_path/f'receipt_{year}.json';rp.write_text(json.dumps(receipt),encoding='utf-8')
        ref=inputs.AnnualOpportunityRef(year,str(path),digest(path),str(rp),digest(rp),'a'*64,'b'*64,maturity)
        refs[year]=ref;ridge_refs[year]=replace(ref,model_sha256='c'*64,calibration_sha256='d'*64)
    reader=inputs.FrozenAnnualOpportunityReader(refs,recipe='RIDGE_HGB_EQUAL',ridge_references=ridge_refs)
    observed=[]
    def provider(j,ctx):
        out=reader.for_decision(ctx.signal_date,ctx.tickers,ctx.decision_mask[0]&ctx.buy_allowed[0],
            ctx.current_units[0],decision_as_of=ctx.signal_asof,held_weights=ctx.current_weights[0])
        observed.append(dict(day=ctx.signal_date,cash=float(ctx.cash[0]),units=ctx.current_units[0].copy(),
            age=ctx.holding_age[0].copy()))
        return dict(mu=out.mean,uncertainty=out.uncertainty,covariance=np.eye(25)*.001,
            covariance_psd_qualified=True,forecast_recipe=out.source_receipt['forecast_recipe'])
    policy=ReusedFeasiblePolicy('PTO_REUSE_ROBUST_COST',provider)
    prices=np.full((4,25),100.)
    market=MarketArrays(dates,assets,prices.copy(),prices.copy(),adv=np.full(prices.shape,1e9),
        signal_asof=[(d+pd.Timedelta(hours=16)).tz_localize('America/New_York') for d in dates])
    account=dict(base_currency='USD',initial_nav=3000,initial_cash=3000,initial_holdings=[],
        fractional_shares=True,integer_share_rounding=False,cash_interest=0,transaction_cost_bps=0,
        financing=False,borrowed_cash=False,long_only=True,max_positions=20,max_weight=.1,
        max_invested=1.,capacity_fraction=.01)
    friction=dict(kind='FIXED_ADVERSE_OPEN_SLIPPAGE',one_way_bps=10,fee_bps=0,
        benchmark='NEXT_RAW_OPEN',authority='HYPOTHETICAL_RESEARCH_SCENARIO',scenario_id='SYNTHETIC_PTO')
    replay=run_continuous_account(market,['SYNTHETIC_PTO'],policy,account,execution_friction=friction)
    assert len(observed)==4 and replay.metadata['annual_reset'] is False
    assert not observed[0]['units'].any() and observed[1]['units'].sum()>0
    assert observed[1]['cash']<3000
    first=replay.fills.loc[replay.fills.execution_date.eq(pd.Timestamp('2024-01-02'))]
    assert first.side.eq('BUY').all() and first.actual_fill_price.gt(100).all()
    assert first.fractional_shares.sum()==pytest.approx(observed[1]['units'].sum())
    assert np.any(observed[2]['age']>observed[1]['age'])
    rotated=replay.fills.loc[replay.fills.execution_date.eq(pd.Timestamp('2024-01-04'))]
    assert {'BUY','SELL'}<=set(rotated.side)
    assert rotated.loc[rotated.side.eq('BUY'),'actual_fill_price'].gt(100).all()
    assert rotated.loc[rotated.side.eq('SELL'),'actual_fill_price'].lt(100).all()
    assert replay.daily.transaction_cost_amount.sum()>0 and replay.accounting_exceptions.empty
    assert all(d['new_fit_units']==0 for d in policy.diagnostics)



@pytest.fixture
def raw_sources(tmp_path, monkeypatch):
    """Only fabricated raw scores/lineage; model paths deliberately do not exist."""
    def bound_json(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return dict(path=str(path), sha256=digest(path))
    base = tmp_path / "raw.parquet"
    pd.DataFrame(dict(signal_date=pd.to_datetime([f"{y}-01-03" for y in (2023, 2024, 2025)]),
        ticker=["A"] * 3, a2_prediction=[.03, -.02, .04], forbidden_target=[999.] * 3)).to_parquet(base, index=False)
    base_ref = dict(path=str(base), sha256=digest(base), namespace="ORIGINAL_RAW_OOF")
    models, held_refs, outputs = {}, {}, {}
    for year in (2023, 2024, 2025):
        contract = dict(year=year, train_end=f"{year-1}-12-01", labelmax=f"{year-1}-12-30",
            prediction_min_date=f"{year}-01-02", feature_columns=list(inputs.FEATURES))
        manifest_ref = bound_json(f"manifest_{year}.json", dict(contract=contract))
        model = dict(path=str(tmp_path / f"MUST_NOT_LOAD_MODEL_{year}.joblib"), sha256="a" * 64,
            manifest_path=manifest_ref["path"], manifest_sha256=manifest_ref["sha256"],
            **{key: contract[key] for key in ("train_end", "labelmax", "prediction_min_date")})
        models[str(year)] = model
        held_path = tmp_path / f"held_{year}.parquet"
        pd.DataFrame(dict(signal_date=pd.to_datetime([f"{year}-01-03"]), ticker=["B"],
            a2_prediction=[.07], raw_uncertainty=[.015], source_fit_cutoff=pd.to_datetime([f"{year}-01-01"]),
            source_kind=["FROZEN_RAW_ANNUAL_MISSING_HELD_KEY_INFERENCE"], feature_source=["SYNTHETIC_ONLY"],
            forbidden_future_pnl=[1e10])).to_parquet(held_path, index=False)
        held_refs[year] = dict(path=str(held_path), sha256=digest(held_path), namespace=f"ORIGINAL_RAW_HELD_{year}")
        outputs[str(year)] = dict(path=str(held_path), sha256=digest(held_path), model=model)
    freeze_ref = bound_json("freeze.json", dict(status="FROZEN_BEFORE_REAL_MISSING_KEY_INFERENCE",
        features=list(inputs.FEATURES), models=models, rank_units="ORIGINAL_NATIVE_MULTIHORIZON_RANK_ONLY"))
    for output in outputs.values(): output["input_freeze_sha256"] = freeze_ref["sha256"]
    validation_ref = bound_json("validation.json", dict(status="PASS_FROZEN_RAW_MISSING_HELD_KEY_INFERENCE",
        annual_outputs=outputs))
    monkeypatch.setattr(inputs, "RAW_CONTROL_BASE_REF", base_ref)
    monkeypatch.setattr(inputs, "RAW_CONTROL_HELD_REFS", held_refs)
    monkeypatch.setattr(inputs, "RAW_CONTROL_FREEZE_REF", freeze_ref)
    monkeypatch.setattr(inputs, "RAW_CONTROL_VALIDATION_REF", validation_ref)
    return dict(base=base, held_refs=held_refs, freeze_ref=freeze_ref, validation_ref=validation_ref)


def test_raw_reader_exact_base_and_lazy_held_preserve_api_without_market_or_model(raw_sources, monkeypatch):
    import joblib
    monkeypatch.setattr(joblib, "load", lambda *a, **kw: pytest.fail("market/model deserialization reached"))
    original = inputs.guard_parquet
    reads, guards = [], []
    class Projection:
        def __init__(self, file): self.file = file
        def read(self, *, columns):
            assert len(guards) == 4  # All physical cutoffs guard before score bodies.
            reads.append(columns)
            assert not any("target" in c or "pnl" in c for c in columns)
            return self.file.read(columns=columns)
    def guard(*args):
        file, metadata = original(*args)
        guards.append(args[0])
        return Projection(file), metadata
    monkeypatch.setattr(inputs, "guard_parquet", guard)
    reader = inputs.make_raw_control_reader()
    assert not guards and reader._provider is None
    out = call(reader, assets=("B", "A", "C"), eligible=(False, True, False), units=(1., 0., 0.))
    assert out.assets == ("B", "A", "C") and out.required.tolist() == [True, True, False]
    assert out.mean[:2].tolist() == [.07, .03]
    assert out.uncertainty[:2].tolist() == [.015, 0.]
    assert np.isnan(out.mean[2]) and not out.mean.flags.writeable
    assert len(guards) == 4 and reads[0] == ["signal_date", "ticker", "a2_prediction"]
    receipt = out.source_receipt
    assert receipt["forecast_recipe"] == reader.recipe == "ORIGINAL_RAW_A2"
    assert receipt["source_projection_not_market_cache"]
    from scripts.research.a2.evaluation.reused_policy_pair import PTO_ACCOUNT_PROFILE
    from scripts.research.a2.inference.reused_feasible_policy import RAW_SOURCE_REUSE_KIND
    assert PTO_ACCOUNT_PROFILE["recipes"][RAW_SOURCE_REUSE_KIND] == reader.recipe
    assert receipt["additional_fit_units"] == receipt["additional_inference_rows"] == 0
    assert {p["base_present"] for p in receipt["provenance"]} == {False, True}
    assert all("value_cell_identity" not in p for p in receipt["provenance"] if p["base_present"])
    other = call(reader, day="2024-01-03", asof="2024-01-03T21:00:00+00:00")
    assert other.mean[:2].tolist() == [-.02, .07] and len(guards) == 4
    assert not list(raw_sources["base"].parent.glob("MUST_NOT_LOAD_MODEL*.joblib"))


def test_raw_reader_requires_actual_held_key_without_mask_shrinking(raw_sources):
    with pytest.raises(inputs.OpportunityInputUnavailable, match="MISSING_REQUIRED_RAW_CONTROL_KEY:C"):
        call(inputs.make_raw_control_reader(), units=(0., 1., .01))


def test_raw_reader_preserves_missing_required_held_provider_failure(raw_sources, monkeypatch):
    import pyarrow.dataset as ds
    original = ds.dataset
    class MissingHeld:
        def __init__(self, dataset): self.dataset, self.schema = dataset, dataset.schema
        def to_table(self, **kwargs): return self.dataset.to_table(**kwargs).slice(0, 0)
    monkeypatch.setattr(ds, "dataset", lambda *a, **kw: MissingHeld(original(*a, **kw)))
    with pytest.raises(inputs.OpportunityInputUnavailable, match="EXACT_REQUIRED_HELD_VALUE_ROW_MISSING"):
        call(inputs.make_raw_control_reader())


@pytest.mark.parametrize("day,asof", [
    ("2026-01-02", "2026-01-02T21:00:00+00:00"),
    ("2023-01-03", "2023-01-03"),
    ("2023-01-03", "2023-01-04T21:00:00+00:00"),
])
def test_raw_reader_invalid_clock_stops_before_any_source_io(day, asof):
    def forbidden(): pytest.fail("source loader reached")
    with pytest.raises(ValueError):
        call(inputs.FrozenRawControlReader(provider_factory=forbidden), day=day, asof=asof)


def test_raw_mixed_future_held_footer_blocks_before_any_prediction_body(raw_sources, monkeypatch):
    path = Path(raw_sources["held_refs"][2025]["path"])
    pd.DataFrame(dict(signal_date=pd.to_datetime(["2026-01-02"]),
        source_fit_cutoff=pd.to_datetime(["2025-01-01"]))).to_parquet(path, index=False)
    monkeypatch.setattr(inputs, "_raw_control_metadata", lambda: {})
    monkeypatch.setitem(inputs.RAW_CONTROL_HELD_REFS, 2025, dict(path=str(path), sha256=digest(path)))
    original = inputs.guard_parquet
    class NeverRead:
        def read(self, **kwargs): pytest.fail("score body read before all footer guards")
    def guard(*args):
        file, metadata = original(*args)
        return NeverRead(), metadata
    monkeypatch.setattr(inputs, "guard_parquet", guard)
    with pytest.raises(ValueError, match="Forbidden mixed/test input"):
        call(inputs.make_raw_control_reader())


def test_raw_base_key_projection_retains_native_bits_order_and_existing_nan():
    frame = pd.DataFrame(dict(signal_date=pd.to_datetime(["2023-01-03"] * 3),
        ticker=["Z", "A", "B"], a2_prediction=np.array([-0., np.nan, .123456789012345])))
    out = inputs._project_raw_control_base(frame)
    assert out.ticker.tolist() == ["Z", "A", "B"] and out.row_identity.tolist() == [0, 1, 2]
    assert out.a2_prediction.to_numpy().tobytes() == frame.a2_prediction.to_numpy().tobytes()
    with pytest.raises(ValueError, match="DUPLICATE_BASE_KEY"):
        inputs._project_raw_control_base(pd.concat([frame, frame.iloc[:1]], ignore_index=True))
