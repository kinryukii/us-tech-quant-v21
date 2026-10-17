"""Synthetic investment domains only; no real market, source, risk or account I/O."""
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.inference import reused_r5_risk_inputs as owner


TASK = "V24_B_FAST_TRACK_PAIR_COMPLETION_R1"
ASSETS = ("INTC", "MKFG", "A", "B")
POLICIES = ("PTO_REUSE_ROBUST_COST", "RAW_A2_SOURCE_REUSE")


def freeze():
    return dict(task_id=TASK,
        pto_account_profile=dict(schema="B_PTO_MATCHED_SOURCE_ACCOUNT_PROFILE_V1",
                                 policies=list(POLICIES)),
        investment_exclusion_tickers=["INTC", "MKFG"],
        account_config=dict(initial_holdings=[]),
        source_retry_replay_from_original_beginning=True)


def context():
    return SimpleNamespace(tickers=ASSETS,
        signal_date=pd.Timestamp("2023-01-03"),
        signal_asof=pd.Timestamp("2023-01-03T21:00:00+00:00"),
        current_units=np.zeros(4), current_weights=np.zeros(4),
        decision_mask=np.ones(4, dtype=bool), buy_allowed=np.ones(4, dtype=bool))


def test_scope_omission_preserves_original_domain():
    f = freeze(); f.pop("investment_exclusion_tickers")
    ctx = context(); ctx.current_units[0] = 1.; ctx.current_weights[0] = .1
    result = owner.causal_held_domain(ctx, np.ones(4, dtype=bool),
        excluded_tickers=owner.frozen_investment_exclusion_tickers(f))
    assert result["assets"] == ASSETS
    assert result["eligible_mask"].all()
    assert "investment_exclusion_tickers" not in result


@pytest.mark.parametrize("defect", ["order", "extra", "tuple", "task", "profile", "holdings", "prefix"])
def test_scope_requires_exact_two_tickers_and_empty_original_start(defect):
    f = freeze()
    if defect == "order": f["investment_exclusion_tickers"].reverse()
    elif defect == "extra": f["investment_exclusion_tickers"].append("A")
    elif defect == "tuple": f["investment_exclusion_tickers"] = ("INTC", "MKFG")
    elif defect == "task": f["task_id"] = "ANOTHER_TASK"
    elif defect == "profile": f["pto_account_profile"]["schema"] = "ANOTHER_PROFILE"
    elif defect == "holdings": f["account_config"]["initial_holdings"] = [dict(ticker="INTC")]
    elif defect == "prefix": f["source_retry_replay_from_original_beginning"] = False
    with pytest.raises(owner.ExistingRiskInputUnavailable):
        owner.CausalHeldLWInputs._from_freeze(freeze=f, base_shared=None,
            account_id="SYNTHETIC", market_dates=(), master_assets=(), source_context=None,
            inherited_runtime_evidence_only=True)


def test_exclusion_preserves_other_held_actions_and_input_masks():
    ctx = context(); ctx.current_units[3] = 1.; ctx.current_weights[3] = .1
    pool = np.array([True, True, True, False]); before = deepcopy(vars(ctx))
    result = owner.causal_held_domain(ctx, pool, excluded_tickers=("INTC", "MKFG"))
    assert result["assets"] == ("A", "B")
    assert result["eligible_mask"].tolist() == [False, False, True, False]
    assert result["decision_mask"].tolist() == [False, False, True, True]
    assert result["buy_allowed"].tolist() == [False, False, True, False]
    assert result["original_eligible_mask"].tolist() == [True, True, True, False]
    assert pool.tolist() == [True, True, True, False]
    for field in ("current_units", "current_weights", "decision_mask", "buy_allowed"):
        np.testing.assert_array_equal(getattr(ctx, field), before[field])


@pytest.mark.parametrize("policy", POLICIES)
def test_both_accounts_exclude_before_first_source_projection(policy):
    calls = []
    class Reader:
        def read(self, name, columns, **kwargs):
            calls.append((name, kwargs["tickers"]))
            assert kwargs["tickers"] == ("A", "B")
            raise RuntimeError("SYNTHETIC_STOP_AFTER_FIRST_PROJECTION")
    ref = dict(path="D:/synthetic/source.json", sha256="a" * 64)
    source = object.__new__(owner.FrozenHeldSourceGuards)
    source.investment_exclusion_tickers = owner.frozen_investment_exclusion_tickers(freeze())
    source.base = SimpleNamespace(master_assets=ASSETS,
        _components=dict(reader=Reader(), refs=dict(source=ref)))
    source.binding = dict(source_manifest_ref=ref)
    book = SimpleNamespace(account_id=TASK + "::" + policy + "_S10",
                           required_guard_assets=lambda ctx: ())
    with pytest.raises(RuntimeError, match="SYNTHETIC_STOP_AFTER_FIRST_PROJECTION"):
        source.session(context(), dict(mask=np.ones(4, dtype=bool)), book)
    assert calls == [("uid_intervals", ("A", "B"))]


@pytest.mark.parametrize("field,index", [("current_units", 0), ("current_units", 1),
                                         ("current_weights", 0), ("current_weights", 1)])
def test_excluded_holdings_stop_before_any_source_or_book_call(field, index):
    ctx = context(); getattr(ctx, field)[index] = 1.
    source = object.__new__(owner.FrozenHeldSourceGuards)
    source.investment_exclusion_tickers = ("INTC", "MKFG")
    book = SimpleNamespace(required_guard_assets=lambda ctx: pytest.fail("book was reached"))
    with pytest.raises(owner.HeldLineageUnavailable, match="EXCLUDED_INVESTMENT_ACTUAL_HOLDING_FORBIDDEN"):
        source.session(ctx, dict(mask=np.ones(4, dtype=bool)), book)


@pytest.mark.parametrize("policy", POLICIES)
def test_required_request_filters_E_D_but_preserves_original_full_P_U(policy):
    ctx = context(); mask = np.ones(4, dtype=bool)
    original = dict(mask=mask, record=dict(assets=list(ASSETS)), receipt=dict(synthetic=True),
        event=dict(dependency_local_event_ids=dict(PRIMARY="SYNTHETIC"),
                   dependency_local_signature_sha256=dict(PRIMARY="b" * 64)))
    adapter = object.__new__(owner.ContinuousCausalLWInputs)
    adapter.investment_exclusion_tickers = ("INTC", "MKFG")
    adapter.account_id = TASK + "::" + policy + "_S10"
    adapter.base = SimpleNamespace(master_assets=ASSETS,
        _domain=lambda *args: original,
        _components=dict(calendar=pd.DatetimeIndex(["2022-12-30", "2023-01-03"])))
    request = adapter.describe_required_domains(ctx)
    assert request["P"] == list(ASSETS)
    assert request["U"] == sorted(ASSETS)
    assert request["E"] == request["D"] == ["A", "B"]
    assert request["H"] == []
    assert request["investment_exclusion_tickers"] == ["INTC", "MKFG"]
    assert mask.all() and ctx.buy_allowed.all() and ctx.decision_mask.all()


@pytest.mark.parametrize("ticker", ["INTC", "MKFG"])
def test_actual_excluded_fill_is_rejected_before_lineage_commit(ticker):
    calls = []
    adapter = object.__new__(owner.CausalHeldLWInputs)
    adapter.investment_exclusion_tickers = ("INTC", "MKFG")
    adapter.book = SimpleNamespace(observe_fills=lambda frame: calls.append(frame) or 1)
    with pytest.raises(owner.HeldLineageUnavailable, match="EXCLUDED_INVESTMENT_ACTUAL_FILL_FORBIDDEN"):
        adapter.observe_fills(pd.DataFrame([dict(ticker=ticker, side="BUY")]))
    assert calls == []
    assert adapter.observe_fills(pd.DataFrame([dict(ticker="A", side="BUY")])) == 1
    assert len(calls) == 1


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("with_exclusions", [False, True])
def test_qualified_domain_restrict_context_transports_frozen_exclusions(policy, with_exclusions, monkeypatch):
    from dataclasses import make_dataclass
    from scripts.research.a2.evaluation import reused_policy_pair as pair

    values = vars(context()).copy()
    values["tickers"] = np.asarray(ASSETS)
    for name in ("current_units", "current_weights", "decision_mask", "buy_allowed"):
        values[name] = values[name][None, :]
    ctx = make_dataclass("SyntheticContext", [(name, object) for name in values])(**values)
    f = freeze()
    if not with_exclusions:
        f.pop("investment_exclusion_tickers")
    scope = owner.frozen_investment_exclusion_tickers(f)
    original = dict(mask=np.ones(4, dtype=bool), receipt=dict(synthetic=True))
    noted = []

    def source_session(current, original_domain, book):
        return dict(domain=owner.causal_held_domain(current, original_domain["mask"],
                        excluded_tickers=scope),
                    held_guards={}, source_receipt=dict(synthetic=True), entry_seeds={})

    adapter = object.__new__(owner.CausalHeldLWInputs)
    adapter.investment_exclusion_tickers = scope
    adapter.account_id = TASK + "::" + policy + "_S10"
    adapter.base = SimpleNamespace(master_assets=ASSETS, _domain=lambda *args: original)
    adapter.sources = SimpleNamespace(session=source_session)
    adapter.book = SimpleNamespace(qualified_proofs=lambda *args: [],
        note_qualified_decision=lambda *args: noted.append(args))
    adapter._last = None
    domain = adapter.qualified_causal_domain(ctx)
    narrow = pair.restrict_causal_context(ctx, domain)
    wanted = ("A", "B") if with_exclusions else ASSETS
    assert tuple(narrow.tickers) == wanted
    assert narrow.current_units.shape == (1, len(wanted))
    assert narrow.decision_mask.all() and narrow.buy_allowed.all()
    assert tuple(ctx.tickers) == ASSETS and original["mask"].all()
    assert domain["receipt"].get("investment_exclusion_tickers", []) == list(scope)
    adapter.note_qualified_decision(ctx, domain)
    assert len(noted) == 1
    # The existing owner identity/context gate still rejects a copied receipt.
    with pytest.raises(owner.ExistingRiskInputUnavailable,
                       match="EXACT_ALREADY_QUALIFIED_CURRENT_DOMAIN_REQUIRED"):
        adapter.note_qualified_decision(ctx, dict(domain))
    assert len(noted) == 1

    forecast_calls = []
    def forecast_for_decision(day, assets, eligible, units, **kwargs):
        forecast_calls.append(tuple(assets))
        assert tuple(assets) == wanted
        assert eligible.all() and not np.any(units)
        recipe = (pair.PTO_FORECAST_RECIPE if policy == pair.PTO_REUSE_KIND
                  else "ORIGINAL_RAW_A2")
        return SimpleNamespace(assets=tuple(assets), mean=np.zeros(len(assets)),
            uncertainty=np.zeros(len(assets)), source_receipt=dict(forecast_recipe=recipe))

    numeric_calls = []
    def required_numeric(current, qualified):
        adapter._require_domain(current, qualified)
        numeric_calls.append(True)
        return SimpleNamespace(assets=qualified["assets"], columns=qualified["columns"],
            covariance=np.eye(len(wanted)), covariance_psd_qualified=True,
            source_receipt=dict(synthetic=True))
    adapter.for_required_domain = required_numeric

    def synthetic_target(kind, mean, uncertainty, covariance, current, **kwargs):
        assert kind == policy and tuple(current.tickers) == wanted
        assert (covariance is None) == (policy == pair.RAW_SOURCE_REUSE_KIND)
        return SimpleNamespace(target=SimpleNamespace(
            weights=np.full((1, len(wanted)), .1),
            explicit_mask=np.ones((1, len(wanted)), dtype=bool)), receipt=dict(synthetic=True))
    monkeypatch.setattr(pair, "feasible_target", synthetic_target)
    prepared = pair.causal_policy_decision(policy, ctx, adapter,
        SimpleNamespace(for_decision=forecast_for_decision))
    assert forecast_calls == [wanted]
    assert len(numeric_calls) == int(policy == pair.PTO_REUSE_KIND)
    assert len(noted) == 2
    # Apply the caller's full-master target transport to the actual returned axis.
    weights = np.zeros_like(ctx.current_weights)
    explicit = np.zeros_like(ctx.decision_mask)
    weights[:, prepared["columns"]] = prepared["result"].target.weights
    explicit[:, prepared["columns"]] = prepared["result"].target.explicit_mask
    assert weights[0].tolist() == ([0., 0., .1, .1] if with_exclusions else [.1] * 4)
    assert explicit[0].tolist() == ([False, False, True, True] if with_exclusions else [True] * 4)
    assert ctx.buy_allowed.all() and ctx.decision_mask.all()
    if with_exclusions:
        for changed in ("domain_scope_missing", "receipt_scope_missing", "receipt_scope_changed"):
            drift = deepcopy(domain)
            if changed == "domain_scope_missing":
                drift.pop("investment_exclusion_tickers")
            elif changed == "receipt_scope_missing":
                drift["receipt"].pop("investment_exclusion_tickers")
            else:
                drift["receipt"]["investment_exclusion_tickers"] = ["INTC"]
            with pytest.raises(ValueError, match="CAUSAL_FROZEN_INVESTMENT_EXCLUSION_RECEIPT_CHANGED"):
                pair.restrict_causal_context(ctx, drift)
