"""Synthetic-only short-history support/posterior/cache integration."""
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.risk.short_history_risk_r4 import (
    METHODS, specification, qualify_metadata, fit_risk, make_cache,
)
from scripts.research.a2.risk.shared_risk_engine_r2 import SourceReceipt, RiskInput, SharedRiskEngine
from scripts.research.a2.risk.shared_risk_budget_r2 import StateBudget


def fixture_input(*, industry=True):
    sessions = pd.bdate_range("2021-01-01", "2025-03-31", tz="UTC")+pd.Timedelta(hours=21)
    as_of = pd.Timestamp("2025-01-01T21:00:00Z")
    cutoff_index = sessions.get_loc(as_of)-1
    end = cutoff_index-7
    origins = list(range(end-251, end+1))
    names = tuple(["D"+str(i) for i in range(8)] + ["S0", "S1"])
    rng = np.random.default_rng(20260928)
    market = rng.normal(0., .01, len(sessions))
    receipt = SourceReceipt("TEST_STOCK", "V1", "a"*64, pd.Timestamp("2020-01-01", tz="UTC"))
    qr = replace(receipt, source_identity="TEST_QQQ", source_sha256="b"*64)
    ir = replace(receipt, source_identity="TEST_FF48", source_sha256="c"*64)
    def records(symbols, source):
        rows = []
        for asset in symbols:
            idiosyncratic = rng.normal(0., .012, len(sessions))
            for oi in origins:
                row = dict(asset=asset, origin_at=sessions[oi],
                           entry_at=sessions[oi+1]-pd.Timedelta(hours=6),
                           endpoint_at=sessions[oi+6]-pd.Timedelta(hours=6),
                           matured_at=sessions[oi+6]-pd.Timedelta(hours=5),
                           available_at=sessions[oi+6]-pd.Timedelta(hours=4), horizon=5,
                           uid=asset, identity_epoch="SYNTHETIC_EPOCH", source_identity=source.source_identity)
                row["return_value"] = float(market[oi+1:oi+6].sum() + (0. if asset == "QQQ" else idiosyncratic[oi+1:oi+6].sum()))
                rows.append(row)
        return pd.DataFrame(rows)
    frame = records(names, receipt)
    for a, n in [("S0", 16), ("S1", 21)]:
        frame.loc[frame.asset.eq(a) & frame.origin_at.lt(sessions[origins[-n]]), "return_value"] = np.nan
    support = frame.loc[:, ["asset", "origin_at"]].copy()
    support["qualified"] = np.isfinite(frame.return_value)
    groups = pd.DataFrame(dict(asset=names, group=1,
                              available_at=pd.Timestamp("2023-01-01", tz="UTC"),
                              effective_at=pd.Timestamp("2023-01-01", tz="UTC"),
                              identity_epoch="SYNTHETIC_EPOCH", source_identity="TEST_FF48"))
    inputs = RiskInput(names, sessions, frame, receipt, {a:a for a in names},
                       qqq_observations=records(("QQQ",), qr), qqq_receipt=qr,
                       industry_mapping=groups if industry else None,
                       industry_receipt=ir if industry else None)
    return inputs, as_of, support


@pytest.mark.parametrize("method", METHODS[:4])
def test_short_history_full_domain_predictive_covariance(method):
    inputs, as_of, support = fixture_input()
    proof = qualify_metadata(inputs, as_of=as_of, support_metadata=support)
    state = fit_risk(method, inputs, as_of=as_of, support_metadata=support, expected_qualification=proof)
    assert state.status == "PASS_SYNTHETIC", state.notes
    assert state.assets == inputs.assets and state.covariance.shape == (10, 10)
    assert state.coverage["S0"]["nominal_n"] == 16
    assert state.coverage["S0"]["structural_effective_n_proxy"] == 3
    assert state.coverage["S1"]["power_likelihood_n"] == 4.2
    assert not state.coverage["S0"]["original_r3_min30_qualified"]
    assert state.coverage["S0"]["industry_mode"] == "FF48"
    assert np.linalg.eigvalsh(state.covariance).min() >= -1e-10
    assert state.fit_dependency_ids and not state.covariance.flags.writeable
    assert not state.notes["strict_PIT_promotion_eligible"]


def test_metadata_does_not_access_return_values_and_no_future_industry_backfill():
    inputs, as_of, support = fixture_input(industry=False)
    poison = inputs.observations.copy()
    poison["return_value"] = "not a number"
    proof = qualify_metadata(replace(inputs, observations=poison), as_of=as_of, support_metadata=support)
    assert not proof["active_groups"]
    state = fit_risk("SHR_HP", inputs, as_of=as_of, support_metadata=support)
    assert state.status == "PASS_SYNTHETIC"
    assert state.coverage["S0"]["industry_mode"] == "MARKET_ONLY"
    future = pd.DataFrame(dict(asset=inputs.assets, group=1, available_at=as_of+pd.Timedelta(days=1),
                              effective_at=as_of+pd.Timedelta(days=1), identity_epoch="SYNTHETIC_EPOCH",
                              source_identity="TEST_FF48"))
    ir = replace(inputs.source_receipt, source_identity="TEST_FF48", source_sha256="c"*64)
    appended = replace(inputs, industry_mapping=future, industry_receipt=ir)
    future_state = fit_risk("SHR_HP", appended, as_of=as_of, support_metadata=support)
    np.testing.assert_array_equal(state.covariance, future_state.covariance)
    assert state.risk_state_id == future_state.risk_state_id


def test_shared_substates_exact_reuse_and_cc_uses_hp_marginals():
    inputs, as_of, support = fixture_input()
    budget = StateBudget(limit=650)
    cache = make_cache(inputs, as_of=as_of, budget=budget)
    hp = fit_risk("SHR_HP", inputs, as_of=as_of, support_metadata=support, cache=cache)
    before = budget.learned_total
    repeated = fit_risk("SHR_HP", inputs, as_of=as_of, support_metadata=support, cache=cache)
    assert hp.risk_state_id == repeated.risk_state_id and budget.learned_total == before
    cc = fit_risk("SHR_CC", inputs, as_of=as_of, support_metadata=support, cache=cache)
    np.testing.assert_allclose(np.diag(cc.covariance), np.diag(hp.covariance), rtol=1e-10, atol=1e-12)
    assert budget.learned_total == before+1
    for m in ["SHR_EB", "SHR_FACTOR"]:
        assert fit_risk(m, inputs, as_of=as_of, support_metadata=support, cache=cache).status == "PASS_SYNTHETIC"
    assert budget.learned_total == 13
    assert budget.counts["deterministic_transform"] > 0
    for detail in hp.estimation_uncertainty.values():
        assert detail["predictive_parameter_variance"] > 0
        assert detail["sigma2_posterior"]["variance_of_variance"] > 0


@pytest.mark.parametrize("defect", ["n9", "unknown_uid", "coordinate", "epoch", "duplicate", "nan", "infinity"])
def test_hard_failure_does_not_remove_stock_or_weaken_r3(defect):
    inputs, as_of, support = fixture_input()
    frame = inputs.observations.copy()
    if defect == "n9":
        support.loc[support.asset.eq("S0"), "qualified"] = False
        last = support.loc[support.asset.eq("S0")].tail(9).index
        support.loc[last, "qualified"] = True
    elif defect == "unknown_uid":
        inputs = replace(inputs, asset_uids={**inputs.asset_uids, "S0":"UNKNOWN"})
    elif defect == "coordinate":
        inputs = replace(inputs, source_receipt=replace(inputs.source_receipt, return_coordinate="adjusted"))
    elif defect == "epoch":
        frame.loc[frame.asset.eq("S0"), "identity_epoch"] = "WRONG"
    elif defect == "duplicate":
        frame = pd.concat([frame, frame.iloc[-1:]], ignore_index=True)
    elif defect in {"nan", "infinity"}:
        frame.loc[frame.asset.eq("S0") & frame.return_value.notna(), "return_value"] = np.nan if defect == "nan" else np.inf
    inputs = replace(inputs, observations=frame)
    state = fit_risk("SHR_HP", inputs, as_of=as_of, support_metadata=support)
    assert state.status == "BLOCKED" and state.assets == inputs.assets
    assert state.covariance is None
    if defect == "n9":
        assert "FIXED_MINIMUM" in state.notes["block_reason"]


def test_original_min30_unchanged_and_future_numeric_append_invariance():
    inputs, as_of, support = fixture_input()
    assert SharedRiskEngine().fit("RH", inputs, as_of=as_of).status == "BLOCKED"
    budget = StateBudget(limit=650)
    cache = make_cache(inputs, as_of=as_of, budget=budget)
    baseline = fit_risk("SHR_HP", inputs, as_of=as_of, support_metadata=support, cache=cache)
    before = budget.learned_total
    future = inputs.observations.iloc[:1].copy()
    for f in ["origin_at", "entry_at", "endpoint_at", "matured_at", "available_at"]:
        future[f] = future[f]+pd.Timedelta(days=2000)
    future["return_value"] = "must not be decoded"
    appended = replace(inputs, observations=pd.concat([inputs.observations, future], ignore_index=True))
    state = fit_risk("SHR_HP", appended, as_of=as_of, support_metadata=support, cache=cache)
    assert state.status == "PASS_SYNTHETIC", state.notes
    assert state.risk_state_id == baseline.risk_state_id
    assert budget.learned_total == before


def test_budget_failure_is_preserved_and_not_retried():
    inputs, as_of, support = fixture_input()
    cache = make_cache(inputs, as_of=as_of, budget=StateBudget(limit=2))
    first = fit_risk("SHR_HP", inputs, as_of=as_of, support_metadata=support, cache=cache)
    assert first.status == "BLOCKED" and cache.budget.learned_total == 2
    assert "CAP" in first.notes["block_reason"]
    second = fit_risk("SHR_HP", inputs, as_of=as_of, support_metadata=support, cache=cache)
    assert second.status == "BLOCKED" and cache.budget.learned_total == 2
    assert "NO_RETRY" in second.notes["block_reason"]


@pytest.mark.parametrize("method", ["SHR_DYNAMIC", "SHR_ROBUST"])
def test_typed_not_applicable_zero_fit(method):
    inputs, as_of, support = fixture_input()
    cache = make_cache(inputs, as_of=as_of)
    state = fit_risk(method, inputs, as_of=as_of, support_metadata=support, cache=cache)
    assert state.status == "BLOCKED" and cache.budget.learned_total == 0
    assert "BLOCKED_" in state.notes["block_reason"]
    assert specification()["scientific_retry"] == 0


def test_unknown_support_key_and_foreign_qqq_clock_block_before_estimation():
    inputs, as_of, support = fixture_input()
    bad = support.iloc[-1:].copy()
    bad["asset"] = "UNKNOWN"
    with pytest.raises(ValueError, match="OUTSIDE_REQUESTED"):
        qualify_metadata(inputs, as_of=as_of, support_metadata=pd.concat([support,bad]))
    q = inputs.qqq_observations.copy()
    q.loc[q.index[-1],"endpoint_at"] -= pd.Timedelta(days=10)
    cache = make_cache(inputs,as_of=as_of)
    state = fit_risk("SHR_HP", replace(inputs,qqq_observations=q), as_of=as_of, support_metadata=support,cache=cache)
    assert state.status == "BLOCKED" and cache.budget.learned_total == 0


def test_qualified_group_insufficient_per_origin_is_frozen_market_only():
    inputs, as_of, support = fixture_input()
    # All eight donors still have >=60 rows, but an origin lacks five group donors.
    first = support.origin_at.min()
    support.loc[support.origin_at.eq(first)&support.asset.isin(["D0","D1","D2","D3"]),"qualified"]=False
    proof=qualify_metadata(inputs,as_of=as_of,support_metadata=support)
    assert not proof["active_groups"]
    state=fit_risk("SHR_HP",inputs,as_of=as_of,support_metadata=support)
    assert state.status=="PASS_SYNTHETIC",state.notes
    assert state.coverage["D0"]["industry_mode"]=="MARKET_ONLY"


def test_numeric_failure_reservation_preserved_without_retry():
    inputs,as_of,support=fixture_input()
    q=inputs.qqq_observations.copy()
    q["return_value"]=0.
    inputs=replace(inputs,qqq_observations=q)
    cache=make_cache(inputs,as_of=as_of)
    first=fit_risk("SHR_HP",inputs,as_of=as_of,support_metadata=support,cache=cache)
    assert first.status=="BLOCKED" and "VARIANCE_NOT_IDENTIFIABLE" in first.notes["block_reason"]
    failed=[v for v in cache.budget.events if v["status"]=="FAILED"]
    assert len(failed)==1 and failed[0]["kind"]=="covariance"
    reserved=cache.budget.learned_total
    second=fit_risk("SHR_HP",inputs,as_of=as_of,support_metadata=support,cache=cache)
    assert second.status=="BLOCKED" and "NO_RETRY" in second.notes["block_reason"]
    assert cache.budget.learned_total==reserved


def test_source_or_order_changes_do_not_exact_reuse():
    inputs,as_of,support=fixture_input(industry=False)
    cache=make_cache(inputs,as_of=as_of)
    baseline=fit_risk("SHR_HP",inputs,as_of=as_of,support_metadata=support,cache=cache)
    before=cache.budget.learned_total
    reordered=replace(inputs,assets=tuple(reversed(inputs.assets)))
    second=fit_risk("SHR_HP",reordered,as_of=as_of,support_metadata=support,cache=cache)
    assert second.status=="PASS_SYNTHETIC" and cache.budget.learned_total>before
    assert second.risk_state_id!=baseline.risk_state_id
    source=replace(inputs.source_receipt,source_version="V2",source_sha256="d"*64)
    third=fit_risk("SHR_HP",replace(inputs,source_receipt=source),as_of=as_of,support_metadata=support,cache=cache)
    assert third.status=="PASS_SYNTHETIC" and third.risk_state_id!=baseline.risk_state_id
