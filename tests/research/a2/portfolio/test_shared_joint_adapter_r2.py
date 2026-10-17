"""Pure synthetic frozen-receipt and Q/action/G feasibility tests; no replay."""
from dataclasses import asdict, replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.portfolio import shared_joint_adapter_r2 as adapter
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import AccountContext


ASOF = pd.Timestamp("2024-02-01", tz="UTC")
CUTOFF = pd.Timestamp("2024-01-31", tz="UTC")


def source():
    return adapter.FrozenSourceBinding("synthetic-stock-history", "v1", "a"*64,
                                      "shareholder_value_open_return", 5, "synthetic-epoch-v1")


def frozen_oof(n=12):
    assets = tuple(f"T{i:02}" for i in range(n))
    origins = ("2023-02-01T00:00:00Z", "2023-03-01T00:00:00Z", "2023-04-03T00:00:00Z")
    maturity = ("2023-02-08T00:00:00Z", "2023-03-08T00:00:00Z", "2023-04-10T00:00:00Z")
    clocks = tuple(("2023-01-01T00:00:00Z",)*3 for _ in range(5))
    current = tuple(tuple(.005+.001*k+i*.0001 for i in range(n)) for k in range(5))
    previous = tuple(tuple(tuple(.001*k+.002*j for _ in range(n)) for j in range(3)) for k in range(5))
    targets = tuple(tuple(.005+j*.002 for _ in range(n)) for j in range(3))
    return adapter.FrozenCalibratedOOFReceipt(
        "synthetic-frozen-five-member-calibrated-oof", source(), assets, adapter.P2_MEMBERS,
        str(CUTOFF), str(CUTOFF), ("2024-01-01T00:00:00Z",)*5,
        ("2024-01-01T00:00:00Z",)*5, current, origins, maturity, maturity,
        (origins,)*5, clocks, clocks, previous, targets,
        frozen_prior_oof_rms=tuple(np.sqrt(np.mean(
            (np.asarray(previous).mean(axis=0)-np.asarray(targets))**2, axis=0))),
    ).seal()


def p2(receipt, **kwargs):
    return adapter.compute_p2_disagreement(receipt, assets=receipt.assets, as_of=ASOF,
        prior_cutoff=CUTOFF, expected_source=source(),
        expected_receipt_sha256=receipt.frozen_sha256, **kwargs)


def fixture(n=25):
    assets = tuple(f"T{i:02}" for i in range(n))
    current = np.zeros((1, n)); current[0, 0] = .04; current[0, 1] = .02
    held = current > 0
    reserved = np.zeros((1, n), bool); reserved[0, 0] = True
    buy = np.ones((1, n), bool); buy[0, :2] = False
    decision = np.ones((1, n), bool); decision[0, 0] = False
    ctx = AccountContext(0, ASOF, ASOF, ("synthetic",), np.asarray(assets), held.astype(float),
        current, np.array([2820.]), np.array([.94]), np.array([3000.]), reserved,
        np.array([.04]), np.array([1]), np.array([.96]), np.array([19]), buy,
        np.zeros((1, n), bool), np.ones((1, n), bool), decision,
        np.zeros((1, n), bool), 20, .1, 1.)
    covariance = np.eye(n)*.0002 + .00001
    receipt = asdict(source()) | dict(cutoff=CUTOFF, synthetic=True, status="QUALIFIED_SYNTHETIC")
    risk = SimpleNamespace(risk_state_id="synthetic-risk-state", as_of=ASOF, cutoff=CUTOFF,
        assets=assets, source_identity=source().source_identity, return_coordinate=source().return_coordinate,
        horizon=5, identity_epoch=source().identity_epoch, covariance=covariance,
        source_receipt=receipt, status="PASS_SYNTHETIC", blocked_assets=())
    mu = np.linspace(.005, .012, n); mu[1] = .04
    return risk, mu, np.full(n, .01), ctx


def scenario_receipt(risk):
    rng = np.random.default_rng(23)
    days = pd.bdate_range("2023-01-02", periods=32, tz="UTC")
    maturity = days + pd.Timedelta(days=9)
    scenarios = rng.multivariate_normal(np.full(len(risk.assets), .002), risk.covariance, 32)
    return adapter.MatureScenarioReceipt(risk.assets, source(), str(CUTOFF), str(CUTOFF),
        tuple(str(v) for v in days), tuple(str(v) for v in maturity), tuple(str(v) for v in maturity),
        tuple(tuple(row) for row in scenarios), "PASS_SYNTHETIC", True).seal()


def evaluate(policy=None, inputs=None, **kwargs):
    risk, mu, uncertainty, ctx = inputs or fixture()
    return (policy or adapter.SharedJointAdapter()).evaluate(risk, mu, uncertainty, ctx,
        expected_source=source(), prior_cutoff=CUTOFF, synthetic_context=True, **kwargs)


def test_p2_uses_exact_five_calibrated_member_population_variance_and_prior_oof_mean_rms():
    receipt = frozen_oof()
    result = p2(receipt)
    prior = np.asarray(receipt.prior_calibrated_mu).mean(axis=0)
    rms = np.sqrt(np.mean((prior-np.asarray(receipt.prior_targets))**2, axis=0))
    variance = np.var(receipt.calibrated_mu, axis=0, ddof=0)
    np.testing.assert_array_equal(result.prior_oof_rms, rms)
    np.testing.assert_array_equal(result.sigma, np.sqrt(rms*rms+variance))
    np.testing.assert_array_equal(p2(receipt).sigma, result.sigma)
    assert result.physical_fit_count == 0


@pytest.mark.parametrize("mutation", ["member", "asset", "source", "version", "epoch", "payload"])
def test_p2_frozen_identity_member_and_source_mutation_fail_closed(mutation):
    receipt = frozen_oof()
    original = receipt.frozen_sha256
    if mutation == "member": receipt = replace(receipt, members=receipt.members[:-1])
    if mutation == "asset": receipt = replace(receipt, assets=receipt.assets[::-1])
    if mutation == "source": receipt = replace(receipt, source=replace(receipt.source, source_identity="other"))
    if mutation == "version": receipt = replace(receipt, source=replace(receipt.source, source_version="v2"))
    if mutation == "epoch": receipt = replace(receipt, source=replace(receipt.source, identity_epoch="other"))
    if mutation == "payload": receipt = replace(receipt, calibrated_mu=((.5,)*len(receipt.assets),)*5)
    with pytest.raises(adapter.AdapterBlocked):
        adapter.compute_p2_disagreement(receipt, assets=frozen_oof().assets, as_of=ASOF,
            prior_cutoff=CUTOFF, expected_source=source(), expected_receipt_sha256=original)


@pytest.mark.parametrize("mutation", ["fit", "calibration", "predicted", "maturity", "future_cutoff", "2026", "no_history"])
def test_p2_resealed_synthetic_future_or_in_sample_clocks_still_rejected(mutation):
    receipt = frozen_oof()
    if mutation in {"fit", "calibration", "predicted"}:
        name = {"fit": "fit_cutoffs", "calibration": "calibration_cutoffs", "predicted": "predicted_at"}[mutation]
        clocks = list(getattr(receipt, name)); row = list(clocks[0])
        row[0] = receipt.label_maturities[0] if mutation == "predicted" else receipt.origins[0]
        clocks[0] = tuple(row); receipt = replace(receipt, **{name: tuple(clocks)})
    if mutation == "maturity": receipt = replace(receipt, label_maturities=("2024-02-02T00:00:00Z",)*3)
    if mutation == "future_cutoff": receipt = replace(receipt, cutoff="2024-02-02T00:00:00Z")
    if mutation == "2026": receipt = replace(receipt, cutoff="2026-01-01T00:00:00Z")
    if mutation == "no_history": receipt = replace(receipt, origins=())
    with pytest.raises(adapter.AdapterBlocked): p2(receipt.seal())


@pytest.mark.parametrize("q", tuple(adapter.Q_METHODS))
@pytest.mark.parametrize("action", ["A0", "A1", "A2"])
@pytest.mark.parametrize("gross", tuple(adapter.G_METHODS))
def test_all_registered_q_action_g_combinations_synthetic_feasible(q, action, gross):
    inputs = fixture(); scenarios = scenario_receipt(inputs[0])
    kwargs = dict(scenarios=scenarios, expected_scenario_sha256=scenarios.frozen_sha256) if q == "Q2" else {}
    result = evaluate(adapter.SharedJointAdapter(q_role=q, action_role=action, gross_role=gross), inputs, **kwargs)
    weights = result.target.effective_weights
    assert result.synthetic and result.account_replay_count == result.physical_fit_count == 0
    assert np.count_nonzero(weights > 1e-10) <= 20
    assert weights.max() <= .1+1e-10 and weights.sum() <= 1+1e-10
    assert weights[0] == pytest.approx(.04)
    assert weights[1] <= .02+1e-10
    assert not result.global_optimum_claim
    if q == "Q3":
        assert result.execution_friction_bps == 10 and result.fees_bps == 0
        assert "SIGNAL_KNOWN" in result.equivalence


@pytest.mark.parametrize("mutation", ["version", "source", "identity", "asset", "coordinate", "future", "negative", "nan", "blocked"])
def test_risk_source_unit_cutoff_identity_and_psd_are_gates(mutation):
    risk, mu, uncertainty, ctx = fixture()
    if mutation == "version": risk.source_receipt["source_version"] = "v2"
    if mutation == "source": risk.source_identity = "swapped"
    if mutation == "identity": risk.identity_epoch = "swapped"
    if mutation == "asset": risk.assets = risk.assets[::-1]
    if mutation == "coordinate": risk.return_coordinate = "price_return"
    if mutation == "future": risk.source_receipt["cutoff"] = ASOF
    if mutation == "negative": risk.covariance[0, 0] = -.1
    if mutation == "nan": risk.covariance[0, 0] = np.nan
    if mutation == "blocked": risk.status = "BLOCKED"
    with pytest.raises(adapter.AdapterBlocked): evaluate(inputs=(risk, mu, uncertainty, ctx))


def test_cvar_absent_receipt_and_unqualified_real_scenario_never_fall_back():
    policy = adapter.SharedJointAdapter(q_role="Q2")
    with pytest.raises(adapter.AdapterBlocked, match="QUALIFIED_SCENARIO"): evaluate(policy)
    risk = fixture()[0]; receipt = scenario_receipt(risk)
    false_real = replace(receipt, synthetic=False, status="PASS_SYNTHETIC").seal()
    with pytest.raises(adapter.AdapterBlocked, match="SCENARIO"):
        evaluate(policy, scenarios=false_real, expected_scenario_sha256=false_real.frozen_sha256)
    changed = replace(receipt, scenarios=((.4,)*len(risk.assets),)*len(receipt.origins))
    with pytest.raises(adapter.AdapterBlocked, match="SCENARIO_RECEIPT_MUTATION"):
        evaluate(policy, scenarios=changed, expected_scenario_sha256=receipt.frozen_sha256)


def test_synthetic_context_is_explicit_and_real_activation_is_unavailable():
    risk, mu, uncertainty, ctx = fixture()
    with pytest.raises(adapter.AdapterBlocked, match="SYNTHETIC_CONTEXT"):
        adapter.SharedJointAdapter().evaluate(risk, mu, uncertainty, ctx,
            expected_source=source(), prior_cutoff=CUTOFF, synthetic_context=False)


def test_rule_hysteresis_adds_reserved_slot_before_q_and_holds_exact_units():
    risk, mu, sigma, ctx = fixture()
    current = ctx.current_weights.copy(); current[0, 2] = .04
    ctx = replace(ctx, current_weights=current, current_units=(current > 0).astype(float))
    mu[:] = .01; mu[2] = .009
    result = evaluate(adapter.SharedJointAdapter(action_role="A2"), (risk, mu, sigma, ctx))
    assert not result.target.explicit_mask[2]
    assert result.target.effective_weights[2] == pytest.approx(.04)
    assert np.count_nonzero(result.target.effective_weights > 1e-10) <= 20


def test_q3_execution_friction_reduces_turnover_even_with_zero_fee_identity():
    risk, mu, sigma, ctx = fixture(20)
    current = np.r_[np.full(10, .1), np.zeros(10)][None, :]
    ctx = replace(ctx, current_weights=current, current_units=(current > 0).astype(float),
                  reserved_mask=np.zeros_like(ctx.reserved_mask), decision_mask=np.ones_like(ctx.decision_mask),
                  buy_allowed=np.ones_like(ctx.buy_allowed))
    mu[:] = 0; mu[10:] = .0003; risk.covariance = np.eye(20)*.00001
    blind = evaluate(adapter.SharedJointAdapter(q_role="Q0"), (risk, mu, sigma, ctx))
    aware = evaluate(adapter.SharedJointAdapter(q_role="Q3"), (risk, mu, sigma, ctx))
    assert np.abs(aware.q-current[0]).sum() < np.abs(blind.q-current[0]).sum()
    assert aware.fees_bps == 0 and aware.execution_friction_bps == 10


def test_deterministic_exact_reuse_and_forecast_inputs_not_mutated():
    inputs = fixture(); before = inputs[1].copy()
    first, second = evaluate(inputs=inputs), evaluate(inputs=inputs)
    np.testing.assert_array_equal(first.target.effective_weights, second.target.effective_weights)
    np.testing.assert_array_equal(inputs[1], before)



def test_current_activation_rejects_qualified_real_risk_oof_and_scenarios():
    risk, mu, sigma, ctx = fixture()
    risk.status = "QUALIFIED"
    risk.source_receipt.update(status="QUALIFIED", synthetic=False)
    with pytest.raises(adapter.AdapterBlocked, match="ACTIVATION_PENDING"):
        evaluate(inputs=(risk, mu, sigma, ctx))
    real_oof = replace(frozen_oof(), status="QUALIFIED", synthetic=False).seal()
    with pytest.raises(adapter.AdapterBlocked, match="ACTIVATION_PENDING"):
        p2(real_oof)
    scenarios = replace(scenario_receipt(fixture()[0]), status="QUALIFIED", synthetic=False).seal()
    with pytest.raises(adapter.AdapterBlocked, match="ACTIVATION_PENDING"):
        evaluate(adapter.SharedJointAdapter(q_role="Q2"), scenarios=scenarios,
                 expected_scenario_sha256=scenarios.frozen_sha256)


def test_no_trade_band_hold_retains_units_and_infeasible_support_union_is_blocked():
    risk, mu, sigma, ctx = fixture(40)
    current = np.r_[np.full(20, .001), np.zeros(20)][None, :]
    ctx = replace(ctx, current_weights=current, current_units=(current > 0).astype(float),
                  reserved_mask=np.zeros_like(ctx.reserved_mask), decision_mask=np.ones_like(ctx.decision_mask),
                  buy_allowed=np.ones_like(ctx.buy_allowed))
    mu[:20] = -.1; mu[20:] = .1
    with pytest.raises(adapter.AdapterBlocked, match="FEASIBILITY"):
        evaluate(adapter.SharedJointAdapter(action_role="A1"), (risk, mu, sigma, ctx))


def test_mixed_clock_domain_future_current_calibration_and_ragged_oof_fail_closed():
    receipt = frozen_oof()
    mutations = [replace(receipt, current_fit_cutoffs=("2024-01-01",)*5),
                 replace(receipt, current_calibration_cutoffs=("2024-02-01T00:00:00Z",)*5),
                 replace(receipt, prior_calibrated_mu=(((),),)*5)]
    for changed in mutations:
        with pytest.raises(adapter.AdapterBlocked): p2(changed.seal())


def test_blocked_held_asset_is_reserved_while_blocked_unheld_cannot_buy():
    risk, mu, sigma, ctx = fixture()
    risk.blocked_assets = (risk.assets[1], risk.assets[2])
    result = evaluate(inputs=(risk, mu, sigma, ctx))
    assert not result.target.explicit_mask[1]
    assert result.target.effective_weights[1] == pytest.approx(.02)
    assert result.target.effective_weights[2] == 0



@pytest.mark.parametrize("gross", tuple(adapter.G_METHODS))
def test_native_shared_risk_state_dataclass_integrates_without_fit_or_replay(gross):
    from scripts.research.a2.risk.shared_risk_engine_r2 import RiskState, SourceReceipt, COORDINATE
    protocol, mu, sigma, ctx = fixture()
    binding = source()
    stock_receipt = SourceReceipt(binding.source_identity, binding.source_version,
        binding.source_sha256, CUTOFF, identity_epoch=binding.identity_epoch)
    stock_receipt.validate(CUTOFF)
    receipt = asdict(stock_receipt) | dict(cutoff=CUTOFF, horizon_sessions=5)
    covariance = protocol.covariance.copy(); covariance.flags.writeable = False
    marginal = np.sqrt(np.diag(covariance)); marginal.flags.writeable = False
    coverage = {asset: dict(observed=252, origin_sessions=252, uid="synthetic-"+asset,
                identity_epoch=binding.identity_epoch, source_qualified=True, missing_cells=0)
                for asset in protocol.assets}
    state = RiskState("native-synthetic-risk-state", ASOF, CUTOFF, protocol.assets,
        binding.source_identity, COORDINATE, 5, covariance, marginal, coverage,
        {asset: 50 for asset in protocol.assets}, binding.identity_epoch,
        float(np.linalg.cond(covariance)), 0., None, None, None, None, None, (),
        receipt, "PASS_SYNTHETIC", "RD", (), dict(real_fit=0, synthetic_fixture=True))
    policy = adapter.SharedJointAdapter(action_role="A2", gross_role=gross)
    native = evaluate(policy, (state, mu, sigma, ctx))
    expected = evaluate(policy, (protocol, mu, sigma, ctx))
    np.testing.assert_array_equal(native.target.effective_weights, expected.target.effective_weights)
    assert native.risk_state_id == state.risk_state_id
    assert native.physical_fit_count == native.account_replay_count == 0
    assert not state.covariance.flags.writeable
    assert not state.marginal_sigma.flags.writeable
    with pytest.raises(adapter.AdapterBlocked, match="RISK_STATE_NOT_QUALIFIED"):
        evaluate(policy, (replace(state, status="BLOCKED", covariance=None), mu, sigma, ctx))



def test_actual_rd_engine_to_q0_a0_g0_adapter_and_q2_source_gate():
    import importlib.util
    from pathlib import Path
    from scripts.research.a2.risk.shared_risk_engine_r2 import SharedRiskEngine
    fixture_path = Path(__file__).parents[1] / "risk" / "test_shared_risk_engine_r2.py"
    spec = importlib.util.spec_from_file_location("_reviewed_synthetic_rd_fixture", fixture_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inputs, asof = module.synthetic_input(assets=12, horizons=(5,))
    engine = SharedRiskEngine()
    state = engine.fit("RD", inputs, as_of=asof)
    assert state.status == "PASS_SYNTHETIC", state.notes
    counts = engine.budget.snapshot()["counts"]
    assert counts["covariance"] > 0 and engine.budget.learned_total > 0
    _, mu, sigma, ctx = fixture(12)
    ctx = replace(ctx, signal_date=asof.normalize(), signal_asof=asof,
                  tickers=np.asarray(state.assets))
    binding = adapter.FrozenSourceBinding.from_receipt(state.source_receipt)
    result = adapter.SharedJointAdapter(q_role="Q0", action_role="A0", gross_role="G0").evaluate(
        state, mu, sigma, ctx, expected_source=binding, prior_cutoff=state.cutoff,
        synthetic_context=True)
    assert result.risk_state_id == state.risk_state_id
    assert result.target.assets == state.assets
    assert result.requested_gross == 1
    assert result.target.effective_weights[0] == pytest.approx(.04)
    assert result.target.effective_weights[1] <= .02+1e-10
    assert np.count_nonzero(result.target.effective_weights > 1e-10) <= 20
    assert result.target.effective_weights.max() <= .1+1e-10
    assert result.physical_fit_count == result.account_replay_count == 0
    assert engine.budget.snapshot()["counts"] == counts
    with pytest.raises(adapter.AdapterBlocked, match="QUALIFIED_SCENARIO"):
        adapter.SharedJointAdapter(q_role="Q2", action_role="A0", gross_role="G0").evaluate(
            state, mu, sigma, ctx, expected_source=binding, prior_cutoff=state.cutoff,
            synthetic_context=True)
    assert engine.budget.snapshot()["counts"] == counts



class _UnreadablePriorTarget:
    """Audit payload sentinel: apply must neither convert nor serialize it."""
    def __float__(self):
        raise AssertionError("P2 apply attempted prior numeric target access")
    def __deepcopy__(self, memo):
        raise AssertionError("P2 apply attempted prior target deepcopy")
    def __sub__(self, value):
        raise AssertionError("P2 apply attempted target-based RMS generation")


def test_p2_applies_frozen_rms_without_prior_numeric_access_or_new_bridge_fit():
    receipt = frozen_oof()
    clean = p2(receipt)
    poison = tuple(tuple(_UnreadablePriorTarget() for _ in receipt.assets)
                   for _ in receipt.origins)
    audit_poison = replace(receipt, prior_targets=poison)
    result = p2(audit_poison)
    np.testing.assert_array_equal(result.sigma, clean.sigma)
    np.testing.assert_array_equal(result.prior_oof_rms, receipt.frozen_prior_oof_rms)
    assert result.rms_generation_budget_kind == "bridge_calibration"
    assert result.physical_fit_count == 0 and not result.rms_generation_executed
    schema = adapter.p2_receipt_contract()
    assert not schema["apply_prior_target_numeric_access"]
    assert schema["rms_generation_physical_kind"] == "bridge_calibration"


@pytest.mark.parametrize("bad_rms", [(), (-.1,)*12, (float("nan"),)*12, (.1,)*11])
def test_p2_requires_a_nonempty_frozen_valid_rms_and_refuses_implicit_generation(bad_rms):
    receipt = replace(frozen_oof(), frozen_prior_oof_rms=bad_rms)
    if np.isfinite(np.asarray(bad_rms)).all():
        receipt = receipt.seal()
    with pytest.raises(adapter.AdapterBlocked): p2(receipt)


def test_rebinding_changed_prior_audit_payload_or_rms_changes_frozen_identity():
    receipt = frozen_oof()
    original_sha = receipt.frozen_sha256
    changed_targets = tuple(tuple(99. for _ in receipt.assets) for _ in receipt.origins)
    rebound = replace(receipt, prior_targets=changed_targets).seal()
    assert rebound.frozen_sha256 != original_sha
    with pytest.raises(adapter.AdapterBlocked, match="RECEIPT_MUTATION"):
        adapter.compute_p2_disagreement(rebound, assets=receipt.assets, as_of=ASOF,
            prior_cutoff=CUTOFF, expected_source=source(), expected_receipt_sha256=original_sha)
    # A separately accepted frozen receipt uses its existing RMS, never new target values.
    np.testing.assert_array_equal(p2(rebound).sigma, p2(receipt).sigma)
    changed_rms = replace(receipt, frozen_prior_oof_rms=(.2,)*len(receipt.assets)).seal()
    with pytest.raises(adapter.AdapterBlocked, match="RECEIPT_MUTATION"):
        adapter.compute_p2_disagreement(changed_rms, assets=receipt.assets, as_of=ASOF,
            prior_cutoff=CUTOFF, expected_source=source(), expected_receipt_sha256=original_sha)


# Every value below is fabricated engineering input. No registered real family,
# account input, model or candidate is loaded or run.
def mechanism_fixture(method="RD"):
    from scripts.research.a2.risk.shared_risk_engine_r2 import RiskState, SourceReceipt
    protocol, mu, sigma, ctx = fixture()
    calendar = tuple(v.isoformat() for v in pd.bdate_range("2023-01-02", "2025-12-31", tz="UTC")
                     if not (v.month == 1 and v.day == 1))
    fit = pd.Timestamp("2024-02-01" if method == "RD" else "2024-01-02", tz="UTC")
    index = pd.DatetimeIndex(calendar); i = index.get_indexer([fit])[0]; cutoff = index[i-1]
    activation = adapter.FrozenMechanismActivation("SYNTHETIC_FROZEN_HISTORY_CONTRACT", "c"*64,
        "SYNTHETIC_NEW_MECHANISM", "SYNTHETIC_RUN", "f"*64, adapter.legal_calendar_sha256(calendar))
    receipt = SourceReceipt(source().source_identity, source().source_version, source().source_sha256,
        str(cutoff), synthetic=False, status="FROZEN_HISTORY_MECHANISM_SOURCE_BOUND",
        identity_epoch=source().identity_epoch, mechanism=True,
        scientific_contract_identity=activation.scientific_contract_identity,
        scientific_contract_sha256=activation.scientific_contract_sha256,
        actual_snapshot_timestamp="2025-12-31T23:59:00Z", observation_time_assumed=True)
    receipt.validate(cutoff)
    binding = asdict(receipt) | dict(cutoff=str(cutoff), horizon_sessions=5)
    covariance = protocol.covariance.copy(); covariance.flags.writeable = False
    state = RiskState("fabricated-mechanism-state", fit, cutoff, protocol.assets,
        source().source_identity, source().return_coordinate, 5, covariance,
        np.sqrt(np.diag(covariance)), {}, {}, source().identity_epoch,
        float(np.linalg.cond(covariance)), 0., None, None, None, None, None, (), binding,
        "PASS_FROZEN_HISTORY_MECHANISM", method, ("already-frozen-fabricated-state",), {})
    period = {"R0": "Y", "RD": "M", "RH": "Q"}[method]
    periods = index.tz_localize(None).to_period(period)
    later = np.flatnonzero((np.arange(len(index)) > i) & (periods != periods[i]))
    refresh = index[later[0]]
    use = adapter.RiskStateUseReceipt(state.risk_state_id, adapter.risk_state_sha256(state), source(),
        state.assets, state.identity_epoch, method, str(fit), str(cutoff), str(refresh), calendar).seal()
    decision = index[i+5]
    ctx = replace(ctx, signal_date=decision, signal_asof=decision)
    return (state, mu, sigma, ctx), activation, use


def mechanism_evaluate(inputs=None, activation=None, use=None, policy=None, **changes):
    default, default_activation, default_use = mechanism_fixture()
    state, mu, sigma, ctx = inputs or default
    activation = activation or default_activation; use = use or default_use
    options = dict(expected_source=source(), prior_cutoff=ctx.signal_asof-pd.Timedelta(days=1),
        execution_mode="frozen_history_mechanism", mechanism_activation=activation,
        expected_activation_sha256=activation.digest(), state_use_receipt=use,
        expected_state_use_sha256=use.frozen_sha256)
    options.update(changes)
    return (policy or adapter.SharedJointAdapter()).evaluate(state, mu, sigma, ctx, **options)


@pytest.mark.parametrize("method", ["R0", "RD", "RH"])
def test_explicit_mechanism_carries_frozen_annual_monthly_quarterly_state_without_new_fit(method):
    inputs, activation, use = mechanism_fixture(method)
    result = mechanism_evaluate(inputs, activation, use)
    assert not result.synthetic and result.execution_mode == "frozen_history_mechanism"
    assert result.scientific_contract_sha256 == activation.scientific_contract_sha256
    assert not result.strict_PIT_promotion_eligible and not result.certified_NAV and not result.quote_qualified
    assert result.physical_fit_count == result.account_replay_count == 0
    assert inputs[0].as_of < inputs[3].signal_asof
    assert not inputs[0].covariance.flags.writeable
    assert np.count_nonzero(result.target.effective_weights > 1e-10) <= 20
    assert result.target.effective_weights[0] == pytest.approx(.04)


@pytest.mark.parametrize("mutation", ["no_activation", "synthetic_hack", "promote", "contract", "snapshot",
    "state", "assets", "epoch", "refresh", "calendar", "role", "method", "activation_sha"])
def test_mechanism_requires_exact_frozen_family_source_state_and_scope(mutation):
    inputs, activation, use = mechanism_fixture(); state, mu, sigma, ctx = inputs
    options = {}
    if mutation == "no_activation": options["mechanism_activation"] = None
    if mutation == "synthetic_hack": options["synthetic_context"] = True
    if mutation == "promote": activation = replace(activation, strict_PIT_promotion_eligible=True)
    if mutation == "contract": state.source_receipt["scientific_contract_sha256"] = "d"*64
    if mutation == "snapshot": state.source_receipt["actual_snapshot_timestamp"] = "2022-01-01T00:00:00Z"
    if mutation == "state": state = replace(state, covariance=state.covariance*2)
    if mutation == "assets": state = replace(state, assets=state.assets[::-1])
    if mutation == "epoch": state = replace(state, identity_epoch="other-epoch")
    if mutation == "refresh": use = replace(use, next_refresh_as_of="2024-04-01T00:00:00Z").seal()
    if mutation == "calendar": use = replace(use, legal_sessions=use.legal_sessions[1:]).seal()
    if mutation == "role": activation = replace(activation, allowed_q_roles=("Q1",))
    if mutation == "method": activation = replace(activation, allowed_risk_methods=("R0",))
    if mutation == "activation_sha": options["expected_activation_sha256"] = "0"*64
    with pytest.raises(adapter.AdapterBlocked):
        mechanism_evaluate((state, mu, sigma, ctx), activation, use, **options)


@pytest.mark.parametrize("method", ["R0", "RD", "RH"])
def test_carry_expires_exactly_at_next_registered_refresh_and_never_refits(method):
    inputs, activation, use = mechanism_fixture(method)
    state, mu, sigma, ctx = inputs; refresh = pd.Timestamp(use.next_refresh_as_of)
    before = pd.DatetimeIndex(use.legal_sessions)
    before = before[before < refresh][-1]
    mechanism_evaluate((state, mu, sigma, replace(ctx, signal_asof=before, signal_date=before)), activation, use)
    with pytest.raises(adapter.AdapterBlocked, match="CARRY_EXPIRED"):
        mechanism_evaluate((state, mu, sigma, replace(ctx, signal_asof=refresh, signal_date=refresh)), activation, use)


def mechanism_scenarios(state, use):
    sessions = pd.DatetimeIndex(use.legal_sessions)
    origins, entries, endpoints = sessions[:32], sessions[1:33], sessions[6:38]
    rng = np.random.default_rng(37)
    values = rng.multivariate_normal(np.zeros(len(state.assets)), state.covariance, 32)
    return adapter.MatureScenarioReceipt(state.assets, source(), str(state.cutoff), str(state.cutoff),
        tuple(str(v) for v in origins), tuple(str(v) for v in endpoints), tuple(str(v) for v in endpoints),
        tuple(tuple(row) for row in values), "PASS_FROZEN_HISTORY_MECHANISM", False,
        mechanism_source_receipt=dict(state.source_receipt), entry_at=tuple(str(v) for v in entries),
        endpoint_at=tuple(str(v) for v in endpoints)).seal()


def test_q2_mechanism_uses_independently_bound_true_h5_mature_scenarios():
    inputs, activation, use = mechanism_fixture(); scenarios = mechanism_scenarios(inputs[0], use)
    result = mechanism_evaluate(inputs, activation, use, adapter.SharedJointAdapter(q_role="Q2"),
        scenarios=scenarios, expected_scenario_sha256=scenarios.frozen_sha256)
    assert not result.synthetic and result.physical_fit_count == result.account_replay_count == 0


@pytest.mark.parametrize("mutation", ["absent", "source_contract", "source_horizon", "horizon", "endpoint", "missing_clock", "immature"])
def test_q2_mechanism_missing_or_wrong_source_contract_horizon_or_maturity_blocks(mutation):
    inputs, activation, use = mechanism_fixture(); scenarios = mechanism_scenarios(inputs[0], use)
    if mutation == "absent": scenarios = None
    if mutation == "source_contract": scenarios.mechanism_source_receipt["scientific_contract_sha256"] = "d"*64
    if mutation == "source_horizon": scenarios.mechanism_source_receipt["horizon_sessions"] = 3
    if mutation == "horizon": scenarios = replace(scenarios, horizon_sessions=3)
    if mutation == "endpoint": scenarios = replace(scenarios, endpoint_at=scenarios.entry_at)
    if mutation == "missing_clock": scenarios = replace(scenarios, entry_at=())
    if mutation == "immature": scenarios = replace(scenarios, label_maturities=(str(ASOF),)*len(scenarios.origins))
    scenarios = scenarios.seal() if scenarios else None
    with pytest.raises(adapter.AdapterBlocked):
        mechanism_evaluate(inputs, activation, use, adapter.SharedJointAdapter(q_role="Q2"),
            scenarios=scenarios, expected_scenario_sha256=scenarios.frozen_sha256 if scenarios else None)


def weak_mechanism_p2(activation, source_receipt):
    receipt = frozen_oof()
    return replace(receipt, synthetic=False, status="PASS_FROZEN_HISTORY_MECHANISM",
        genuine_chronological_oof=False, prior_rms_coverage="BRIDGE_IN_TRAINING_RESIDUAL_FROZEN_RMS",
        mechanism_source_receipt=source_receipt,
        fit_cutoffs=((str(CUTOFF),)*len(receipt.origins),)*5,
        calibration_cutoffs=((str(CUTOFF),)*len(receipt.origins),)*5,
        predicted_at=((str(CUTOFF),)*len(receipt.origins),)*5).seal()


def test_weak_mechanism_p2_consumes_frozen_rms_without_relabelling_in_training_as_genuine_oof():
    inputs, activation, use = mechanism_fixture()
    activation = replace(activation, allow_weak_prior_rms=True)
    receipt = weak_mechanism_p2(activation, dict(inputs[0].source_receipt))
    clean = p2(receipt, execution_mode="frozen_history_mechanism", mechanism_activation=activation,
        expected_activation_sha256=activation.digest())
    poison = replace(receipt, prior_targets=tuple(tuple(_UnreadablePriorTarget() for _ in receipt.assets)
        for _ in receipt.origins))
    result = p2(poison, execution_mode="frozen_history_mechanism", mechanism_activation=activation,
        expected_activation_sha256=activation.digest())
    np.testing.assert_array_equal(result.sigma, clean.sigma)
    assert result.weak_coverage and not result.calibrated_uncertainty_certified
    assert result.prior_rms_coverage == "BRIDGE_IN_TRAINING_RESIDUAL_FROZEN_RMS"
    assert result.physical_fit_count == 0 and not result.rms_generation_executed
    assert not result.strict_PIT_promotion_eligible


@pytest.mark.parametrize("mutation", ["weak_permission", "genuine_claim", "future_bridge", "no_activation", "source_contract", "source_horizon"])
def test_weak_p2_mechanism_requires_explicit_coverage_contract_and_prior_frozen_clocks(mutation):
    inputs, activation, use = mechanism_fixture(); activation = replace(activation, allow_weak_prior_rms=True)
    receipt = weak_mechanism_p2(activation, dict(inputs[0].source_receipt))
    if mutation == "weak_permission": activation = replace(activation, allow_weak_prior_rms=False)
    if mutation == "genuine_claim": receipt = replace(receipt, genuine_chronological_oof=True).seal()
    if mutation == "future_bridge": receipt = replace(receipt, predicted_at=((str(ASOF),)*3,)*5).seal()
    if mutation == "source_contract": receipt.mechanism_source_receipt["scientific_contract_sha256"] = "d"*64; receipt = receipt.seal()
    if mutation == "source_horizon": receipt.mechanism_source_receipt["horizon_sessions"] = 3; receipt = receipt.seal()
    options = dict(execution_mode="frozen_history_mechanism", mechanism_activation=activation,
        expected_activation_sha256=activation.digest())
    if mutation == "no_activation": options["mechanism_activation"] = None
    with pytest.raises(adapter.AdapterBlocked): p2(receipt, **options)



def test_native_core_source_receipt_with_timestamp_clocks_binds_p2_without_reader_or_target_access():
    from scripts.research.a2.risk.shared_risk_engine_r2 import SourceReceipt
    inputs, activation, use = mechanism_fixture()
    activation = replace(activation, allow_weak_prior_rms=True)
    mapping = dict(inputs[0].source_receipt)
    mapping.pop("cutoff"); mapping.pop("horizon_sessions")
    mapping["available_at"] = CUTOFF
    mapping["actual_snapshot_timestamp"] = pd.Timestamp("2025-12-31", tz="UTC")
    receipt = weak_mechanism_p2(activation, SourceReceipt(**mapping))
    result = p2(receipt, execution_mode="frozen_history_mechanism", mechanism_activation=activation,
        expected_activation_sha256=activation.digest())
    assert result.weak_coverage and result.physical_fit_count == 0


def test_refresh_session_rejects_old_state_even_before_the_next_registered_close():
    inputs, activation, use = mechanism_fixture()
    state, mu, sigma, ctx = inputs
    # Fabricated Close timestamps expose the intraday boundary; no market data.
    calendar = tuple((pd.Timestamp(v)+pd.Timedelta(hours=20)).isoformat() for v in use.legal_sessions)
    activation = replace(activation, legal_calendar_sha256=adapter.legal_calendar_sha256(calendar))
    fit = state.as_of+pd.Timedelta(hours=20); cutoff = state.cutoff+pd.Timedelta(hours=20)
    source_receipt = dict(state.source_receipt, cutoff=str(cutoff))
    state = replace(state, as_of=fit, cutoff=cutoff, source_receipt=source_receipt)
    use = replace(use, risk_state_sha256=adapter.risk_state_sha256(state), fit_as_of=str(fit), fit_cutoff=str(cutoff),
        next_refresh_as_of=str(pd.Timestamp(use.next_refresh_as_of)+pd.Timedelta(hours=20)), legal_sessions=calendar).seal()
    before_close = pd.Timestamp(use.next_refresh_as_of).normalize()+pd.Timedelta(hours=10)
    with pytest.raises(adapter.AdapterBlocked, match="CARRY_EXPIRED"):
        mechanism_evaluate((state, mu, sigma, replace(ctx, signal_date=before_close, signal_asof=before_close)), activation, use)


@pytest.mark.parametrize("cost", [5, 10, 20])
def test_q3_frozen_cost_sensitivity_matches_signal_penalty_and_account_contract(cost):
    result = evaluate(adapter.SharedJointAdapter(q_role="Q3"), cost_bps=cost)
    assert result.execution_friction_bps == result.account_execution_friction_bps == cost
    assert result.fees_bps == 0
    inputs, activation, use = mechanism_fixture()
    real_mode_fixture = mechanism_evaluate(inputs, activation, use, adapter.SharedJointAdapter(q_role="Q3"), cost_bps=cost)
    assert real_mode_fixture.execution_friction_bps == real_mode_fixture.account_execution_friction_bps == cost
    assert real_mode_fixture.physical_fit_count == real_mode_fixture.account_replay_count == 0


@pytest.mark.parametrize("cost", [0, 7, 10.0, True])
def test_undeclared_execution_cost_never_reaches_optimizer(cost):
    with pytest.raises(adapter.AdapterBlocked, match="COST_SCENARIO"):
        evaluate(adapter.SharedJointAdapter(q_role="Q3"), cost_bps=cost)


def test_activation_cannot_silently_add_a_cost_sensitivity():
    inputs, activation, use = mechanism_fixture()
    activation = replace(activation, allowed_cost_bps=(10,))
    with pytest.raises(adapter.AdapterBlocked, match="COST_NOT_IN"):
        mechanism_evaluate(inputs, activation, use, adapter.SharedJointAdapter(q_role="Q3"), cost_bps=5)


@pytest.mark.parametrize('q_role,gross_role,action_role', [('Q0','G0','A0'),('Q1','G1','A1'),('Q3','G2','A2')])
def test_exact_forecast_support_ignores_inactive_missing_forecasts_without_covariance_padding(q_role,gross_role,action_role):
    risk,mu,sigma,ctx=fixture()
    buy=ctx.buy_allowed.copy(); decision=ctx.decision_mask.copy()
    buy[0,-1]=False; decision[0,-1]=False
    ctx=replace(ctx,buy_allowed=buy,decision_mask=decision)
    needed=(ctx.current_units[0]>adapter.EPS)|(ctx.current_weights[0]>adapter.EPS)|(ctx.decision_mask[0]&ctx.buy_allowed[0])
    support=adapter.FrozenForecastSupport(risk.assets,tuple(np.asarray(risk.assets)[needed]),str(ctx.signal_asof)).seal()
    kwargs=dict(forecast_support=support,expected_forecast_support_sha256=support.frozen_sha256)
    policy=adapter.SharedJointAdapter(q_role=q_role,gross_role=gross_role,action_role=action_role)
    clean=evaluate(policy,(risk,mu,sigma,ctx),**kwargs)
    dirty_mu=mu.copy(); dirty_sigma=sigma.copy(); dirty_mu[-1]=np.inf; dirty_sigma[-1]=np.nan
    dirty=evaluate(policy,(risk,dirty_mu,dirty_sigma,ctx),**kwargs)
    np.testing.assert_array_equal(clean.target.effective_weights,dirty.target.effective_weights)
    assert dirty.target.effective_weights[-1]==0 and len(dirty.q)==len(risk.assets)
    assert risk.covariance.shape==(len(risk.assets),len(risk.assets))


@pytest.mark.parametrize('mutation',['shrink','held_shrink','asof','assets','missing_mu','missing_sigma','missing_receipt_sha'])
def test_exact_forecast_support_does_not_invent_required_forecasts_or_shrink_actual_domain(mutation):
    risk,mu,sigma,ctx=fixture()
    needed=(ctx.current_units[0]>adapter.EPS)|(ctx.current_weights[0]>adapter.EPS)|(ctx.decision_mask[0]&ctx.buy_allowed[0])
    support=adapter.FrozenForecastSupport(risk.assets,tuple(np.asarray(risk.assets)[needed]),str(ctx.signal_asof)).seal()
    if mutation=='shrink': support=replace(support,required_assets=support.required_assets[:-1]).seal()
    if mutation=='held_shrink': support=replace(support,required_assets=support.required_assets[1:]).seal()
    if mutation=='asof': support=replace(support,signal_asof=str(CUTOFF)).seal()
    if mutation=='assets': support=replace(support,assets=support.assets[::-1]).seal()
    if mutation=='missing_mu': mu[3]=np.nan
    if mutation=='missing_sigma': sigma[3]=np.nan
    with pytest.raises(adapter.AdapterBlocked):
        evaluate(inputs=(risk,mu,sigma,ctx),forecast_support=support,
            expected_forecast_support_sha256=None if mutation=='missing_receipt_sha' else support.frozen_sha256)


def test_p2_exact_forecast_support_consumes_only_required_frozen_rms_and_current_member_columns():
    receipt=frozen_oof()
    support=adapter.FrozenForecastSupport(receipt.assets,receipt.assets[:-1],str(ASOF)).seal()
    kwargs=dict(forecast_support=support,expected_forecast_support_sha256=support.frozen_sha256)
    clean=p2(receipt,**kwargs)
    current=np.asarray(receipt.calibrated_mu).copy(); current[:,-1]=np.nan
    rms=np.asarray(receipt.frozen_prior_oof_rms).copy(); rms[-1]=np.inf
    dirty=replace(receipt,calibrated_mu=tuple(map(tuple,current)),frozen_prior_oof_rms=tuple(rms)).seal()
    changed=p2(dirty,**kwargs)
    np.testing.assert_array_equal(changed.sigma[:-1],clean.sigma[:-1])
    assert np.isnan(changed.sigma[-1]) and np.isnan(changed.calibrated_mean[-1])
    current[0,2]=np.nan
    dirty=replace(dirty,calibrated_mu=tuple(map(tuple,current))).seal()
    with pytest.raises(adapter.AdapterBlocked): p2(dirty,**kwargs)
