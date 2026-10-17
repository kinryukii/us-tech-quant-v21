"""Isolated synthetic session-boundary convention and physical-custody checks."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from scripts.common import storage_paths
from scripts.research.a2.evaluation import continuous_research_account as owner
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays, TargetDecision
from scripts.research.a2.training import stateful_research_quote_domain as quote
from scripts.v22.corporate_action_transition_r1 import (
    CorporateActionTransition, SourceBackedEntitlementEvent, ResearchReconstructedTerminalEvent,
    RAW_OLD_SHARE_COORDINATE, USD_PER_RAW_OLD_SHARE,
)


def mechanism(ticker="S", day="2024-01-04", **changes):
    row = dict(ticker=ticker, effective_date=day,
               reason="VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY",
               source_reference="synthetic://vendor/" + ticker,
               source_fingerprint="b" * 64)
    row.update(changes)
    return row


def population_row(event, **changes):
    row = dict(event, date_only=True, independent_effective_clock_proven=False,
               dated_sid_count=1, dated_sid_candidates=["SID_" + event["ticker"]],
               coordinate="RAW_ACTUAL_SHARE", disposition="SESSION_BOUNDARY_CONVENTION_ELIGIBLE")
    row.update(changes)
    return row


@pytest.fixture
def committed(monkeypatch, tmp_path):
    """Build physical synthetic commitments; never read real account/source rows."""
    repo = Path(owner.__file__).resolve().parents[4]
    monkeypatch.setattr(storage_paths, "resolve", lambda *a, **k: SimpleNamespace(
        repo_root=repo, results_root=tmp_path, cache_root=tmp_path / "cache",
        backtest_root=tmp_path / "backtests", data_root=tmp_path / "data"))
    def write(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
        return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    flags = dict(real_effective_clock_proven=False, research_session_boundary_assumption=True,
                 strict_PIT_promotion_eligible=False, production_qualified=False)
    def common(schema, status):
        return dict(schema=schema, status=status, task_id=owner._SESSION_BOUNDARY_TASK,
                    scientific_identity=owner._SESSION_BOUNDARY_IDENTITY, **flags)
    def build(rows=None):
        rows = rows or [population_row(mechanism())]
        human = write("human.json", {"scope": "SYNTHETIC_ONLY"})
        sources = {role: write(role + ".json", {"source": "SYNTHETIC_ONLY", "role": role})
                   for role in ("event_mechanism_source", "security_mapping", "cash_catalogue",
                                "original_event_input_binding", "original_static_event_source")}
        rule = dict(common("SESSION_BOUNDARY_CA_RULE_R1", "FROZEN_BEFORE_ANY_NEW_ACCOUNT"),
            exact_mechanism_key=list(owner._SESSION_BOUNDARY_KEY),
            boundary="SESSION_PRE_TRADE_PRE_OPEN_LIFECYCLE_HOOK",
            declaration="THIS_IS_A_RESEARCH_ACCOUNTING_CONVENTION_NOT_AN_OBSERVED_REAL_WORLD_EFFECTIVE_INSTANT",
            typed_authority_priority=True, no_term_inference=True, observed8_whitelist=False,
            decision_information_unchanged=True, quote_rule_unchanged=True, NAV_comparator_unchanged=True,
            allowed_vendor_reasons=["VENDOR_PRICE_TRANSFORM_WITHOUT_SHARE_AUTHORITY",
                                    "UNSUPPORTED_AFFINE_CASH_OR_MIXED_VENDOR_TRANSFORM"],
            human_authorization_ref=human, source_refs=sources)
        rule_ref = write("rule.json", rule)
        counts = {}
        for row in rows:
            counts[row["disposition"]] = counts.get(row["disposition"], 0) + 1
        population = dict(common("SESSION_BOUNDARY_CA_POPULATION_R1", "FULL_FROZEN_SOURCE_POPULATION"),
                          rule_ref=rule_ref, source_refs=sources, rows=rows,
                          original_unsupported_count=len(rows), disposition_counts=counts)
        population_ref = write("population.json", population)
        contract = dict(common("SESSION_BOUNDARY_CA_ACCOUNTING_CONTRACT_R1", "FROZEN_BEFORE_ANY_NEW_ACCOUNT"),
                        session_boundary_rule_ref=rule_ref, session_boundary_population_ref=population_ref,
                        human_authority=human)
        contract_ref = write("contract.json", contract)
        pins = {str(Path(p).resolve()): hashlib.sha256(Path(p).read_bytes()).hexdigest()
                for p in (owner.__file__, owner._common_engine.__file__, quote.__file__)}
        frozen = dict(common("SESSION_BOUNDARY_CA_SOURCE_AND_CODE_FREEZE_R1", "FROZEN_BEFORE_ACCOUNT_ATTEMPT"),
                      contract_ref=contract_ref, rule_ref=rule_ref, population_ref=population_ref,
                      human_authorization_ref=human, source_refs=sources, code_pins=pins)
        monkeypatch.setattr(owner, "_SESSION_BOUNDARY_COMMITMENTS",
                            {key: frozen[key]["sha256"] for key in
                             ("contract_ref", "rule_ref", "population_ref")})
        return write("freeze.json", frozen), frozen, write
    return build


def market(ticker="S", dates=None, prices=None):
    dates = pd.to_datetime(dates if dates is not None else
                          ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"])
    values = np.asarray(prices if prices is not None else [100.] * len(dates), float)[:, None]
    return MarketArrays(dates, [ticker], values.copy(), values.copy(), adv=np.full(values.shape, 1e9))


def config():
    return dict(base_currency="USD", initial_nav=3000., initial_cash=3000., initial_holdings=[],
                fractional_shares=True, integer_share_rounding=False, cash_interest=0,
                transaction_cost_bps=0, financing=False, borrowed_cash=False, long_only=True,
                max_positions=20, max_weight=1., max_invested=1., capacity_fraction=None)


def args(events=(), ticker="S"):
    mapping = {"SID_" + ticker: ticker}
    return dict(entitlement_enabled=True, entitlement_events=events, entitlement_security_tickers=mapping,
        entitlement_source_binding=dict(status="SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND",
            source_fingerprint="d" * 64, event_fingerprints=[e.event_fingerprint for e in events],
            security_tickers=mapping, quantity_coordinate=RAW_OLD_SHARE_COORDINATE),
        research_account_authority=dict(scientific_identity="FROZEN_HISTORY_RESEARCH_ACCOUNT",
            task_id="V24_A_FROZEN_HISTORY_RESEARCH_ACCOUNT_AND_POLICY_EVALUATION_R1",
            frozen_contract_sha256="a" * 64, clock_role="RECONSTRUCTED_REALIZED_EVENT",
            event_fingerprints=[e.event_fingerprint for e in events if isinstance(e, ResearchReconstructedTerminalEvent)],
            strict_PIT_promotion_eligible=False, production_qualified=False))


def quote_admission(monkeypatch, event):
    ticker, day = event["ticker"], event["effective_date"]
    row = dict(ticker=ticker, date=day, masked=True, inherited_event_mask=True,
        raw_rows=[dict(ticker=ticker, date=day, code="CODE_" + ticker, open=100., close=100.)],
        identity_records=[dict(sid="SID_" + ticker, ticker=ticker, start="2023-01-01", end="2026-01-01", coordinate="RAW_ACTUAL_SHARE")],
        code_tickers={"CODE_" + ticker: [ticker]}, coordinate="RAW_ACTUAL_SHARE", independent_quality_flags=[],
        mechanisms=[dict(event, date=day, mask_origin="INHERITED_UNSUPPORTED_EVENT")], terminal_contracts=[])
    decisions = quote.classify_population([row])
    assert decisions[0]["classification"] == "A"
    monkeypatch.setattr(quote, "load_frozen_domain", lambda ref: {"decisions": decisions})
    return dict(path="SYNTHETIC_QUOTE_ONLY", sha256="c" * 64)


def buy_at(index, trace=None, sell_at=None):
    def policy(j, ctx):
        if trace is not None:
            trace.append((j, ctx.signal_asof, ctx.current_units.copy(), ctx.current_weights.copy(),
                          ctx.cash.copy(), ctx.nav.copy(), ctx.holding_age.copy(), ctx.entry_date.copy()))
        explicit = j == index or j == sell_at
        return TargetDecision(np.full_like(ctx.current_weights, .8 if j == index else 0.),
                              np.full_like(ctx.decision_mask, explicit, dtype=bool))
    return policy


def assert_same(a, b):
    if isinstance(a, pd.DataFrame):
        assert_frame_equal(a, b, check_exact=True)
    elif isinstance(a, np.ndarray):
        np.testing.assert_array_equal(a, b)
    elif isinstance(a, dict):
        assert a.keys() == b.keys()
        for key in a: assert_same(a[key], b[key])
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b)
        for x, y in zip(a, b): assert_same(x, y)
    elif isinstance(a, float) and np.isnan(a):
        assert np.isnan(b)
    else:
        assert a == b


def without_convention(replay):
    values = dict(vars(replay)); values.pop("research_ca_accounting_boundary_audit", None)
    values["metadata"] = dict(values["metadata"])
    values["metadata"].pop("research_ca_accounting_convention", None)
    return values


def test_same_open_first_buy_changes_qualification_only_and_keeps_decision_trace(committed, monkeypatch):
    ref, _, _ = committed(); event = mechanism(); data = market()
    qref = quote_admission(monkeypatch, event); old_trace, new_trace = [], []
    common = dict(unsupported_events=[event], research_quote_domain=qref, **args())
    old = owner.run_continuous_account(data, ["P"], buy_at(1, old_trace), config(), **common)
    new = owner.run_continuous_account(data, ["P"], buy_at(1, new_trace), config(),
                                     research_ca_accounting_convention=ref, **common)
    assert old.final_state["accounting_qualified"].tolist() == [False]
    assert new.final_state["accounting_qualified"].tolist() == [True]
    assert new.accounting_exceptions.empty and len(old.accounting_exceptions) == 1
    assert new.fills.execution_date.iloc[0] == pd.Timestamp("2024-01-04")
    for table in ("fills", "orders", "positions"):
        # Qualification is the intended convention change; execution/state stay exact.
        assert_frame_equal(getattr(old, table).drop(columns=["accounting_qualified"], errors="ignore"),
                           getattr(new, table).drop(columns=["accounting_qualified"], errors="ignore"), check_exact=True)
    assert_same(old_trace, new_trace)
    audit = new.research_ca_accounting_boundary_audit
    assert audit.pre_open_engine_units.tolist() == [0.]
    assert audit.disposition.tolist() == ["NOT_APPLICABLE_TO_THIS_ACCOUNT_PREFIX"]
    assert new.metadata["research_ca_accounting_convention"]["real_effective_clock_proven"] is False
    assert_frame_equal(pd.DataFrame(data.quality), pd.DataFrame(np.zeros_like(data.quality)), check_exact=True)


@pytest.mark.parametrize("sell_at", [None, 1])
def test_inherited_pre_open_position_stays_blocked_even_if_sold_same_open(committed, monkeypatch, sell_at):
    ref, _, _ = committed(); event = mechanism(); qref = quote_admission(monkeypatch, event)
    replay = owner.run_continuous_account(market(), ["P"], buy_at(0, sell_at=sell_at), config(),
        unsupported_events=[event], research_quote_domain=qref,
        research_ca_accounting_convention=ref, **args())
    assert replay.final_state["accounting_qualified"].tolist() == [False]
    assert len(replay.accounting_exceptions) == 1
    assert replay.research_ca_accounting_boundary_audit.pre_open_raw_shares.tolist() == [24.]
    assert replay.research_ca_accounting_boundary_audit.disposition.tolist() == ["ACCOUNTING_BLOCKED"]


def test_next_session_first_buy_has_no_old_event_effect(committed, monkeypatch):
    ref, _, _ = committed(); event = mechanism()
    qref = quote_admission(monkeypatch, event)
    replay = owner.run_continuous_account(market(), ["P"], buy_at(2), config(),
        unsupported_events=[event], research_quote_domain=qref,
        research_ca_accounting_convention=ref, **args())
    assert replay.final_state["accounting_qualified"].tolist() == [True]
    assert replay.fills.execution_date.iloc[0] == pd.Timestamp("2024-01-05")
    assert replay.accounting_exceptions.empty


def test_omitted_and_explicit_none_are_exact_and_never_load_convention(monkeypatch):
    monkeypatch.setattr(owner, "load_research_ca_accounting_convention",
                        lambda ref: (_ for _ in ()).throw(AssertionError("None must not load")))
    event = mechanism(); qref = quote_admission(monkeypatch, event)
    common = dict(unsupported_events=[event], research_quote_domain=qref, **args())
    implicit = owner.run_continuous_account(market(), ["P"], buy_at(1), config(), **common)
    explicit = owner.run_continuous_account(market(), ["P"], buy_at(1), config(),
                                             research_ca_accounting_convention=None, **common)
    assert_same(vars(implicit), vars(explicit))
    assert "research_ca_accounting_convention" not in implicit.metadata
    assert not hasattr(implicit, "research_ca_accounting_boundary_audit")
    assert implicit.final_state["accounting_qualified"].tolist() == [False]


@pytest.mark.parametrize("field,value", [("reason", "UNBOUND_REASON"), ("source_fingerprint", "e" * 64)])
def test_same_ticker_date_unbound_mechanism_keeps_legacy_guard(committed, monkeypatch, field, value):
    ref, _, _ = committed(); event = mechanism(**{field: value}); qref = quote_admission(monkeypatch, event)
    replay = owner.run_continuous_account(market(), ["P"], buy_at(1), config(), unsupported_events=[event],
        research_quote_domain=qref, research_ca_accounting_convention=ref, **args())
    assert replay.final_state["accounting_qualified"].tolist() == [False]
    assert replay.research_ca_accounting_boundary_audit.empty


def test_general_rule_works_for_non_observed_ticker_and_separates_paths(committed, monkeypatch):
    event = mechanism("ZZ_SYNTHETIC"); ref, _, _ = committed([population_row(event)])
    qref = quote_admission(monkeypatch, event)
    def policy(j, ctx):
        weights = np.zeros_like(ctx.current_weights); explicit = np.zeros_like(ctx.decision_mask)
        if j in (0, 1): weights[j, 0] = .8; explicit[j, 0] = True
        return TargetDecision(weights, explicit)
    replay = owner.run_continuous_account(market(event["ticker"]), ["PREHELD", "ENTRANT"], policy, config(),
        unsupported_events=[event], research_quote_domain=qref,
        research_ca_accounting_convention=ref, **args(ticker=event["ticker"]))
    assert replay.final_state["accounting_qualified"].tolist() == [False, True]
    assert replay.research_ca_accounting_boundary_audit.disposition.tolist() == [
        "ACCOUNTING_BLOCKED", "NOT_APPLICABLE_TO_THIS_ACCOUNT_PREFIX"]


@pytest.mark.parametrize("kind", ["cash", "share", "MKFG"])
def test_typed_cash_share_and_terminal_lifecycles_are_exactly_unchanged(committed, kind):
    ref, _, _ = committed(); events = []; extra = {}; data = market(); ticker = "S"
    if kind == "cash":
        events = [SourceBackedEntitlementEvent(event_id="div", action_type="CASH_DIVIDEND", old_security_id="SID_S", ticker="S",
            ex_date="2024-01-04", record_date="2024-01-04", pay_date="2024-01-05", available_at="2024-01-03T12:00:00+00:00",
            cash_per_old_share=1., currency="USD", amount_unit=USD_PER_RAW_OLD_SHARE, quantity_coordinate=RAW_OLD_SHARE_COORDINATE,
            source_type="TIER2_LOCAL_CANONICAL", source_reference="synthetic://cash", source_fingerprint="f" * 64)]
    elif kind == "share":
        split = CorporateActionTransition("2024-01-04", "FORWARD_SPLIT", "old", "new", "S", "S", 2., 0.,
            "TIER2_LOCAL_CANONICAL", "synthetic://split", "a" * 64)
        extra = dict(corporate_actions=[split], corporate_action_known_at={split.event_fingerprint: "2024-01-03T12:00:00+00:00"})
        data = market(prices=[100., 100., 50., 50., 50.])
    else:
        ticker = "MKFG"; data = market(ticker, dates=["2025-04-23", "2025-04-24", "2025-04-25", "2025-04-28", "2025-04-29"])
        events = [ResearchReconstructedTerminalEvent(event_id="terminal", old_security_id="SID_MKFG", ticker="MKFG",
            effective_at="2025-04-25T13:30:00+00:00", available_at=None, cash_per_old_share=5., currency="USD",
            amount_unit=USD_PER_RAW_OLD_SHARE, quantity_coordinate=RAW_OLD_SHARE_COORDINATE,
            quantity_source_reference="synthetic://raw-coordinate", quantity_source_fingerprint="a" * 64,
            source_type="TIER2_LOCAL_CANONICAL", source_reference="synthetic://terminal", source_fingerprint="b" * 64,
            effective_clock_basis="SOURCE_EFFECTIVE_BY_OPEN_UPPER_BOUND", reconstruction_ref="synthetic://reconstruction", reconstruction_sha256="e" * 64)]
    common = dict(**args(events, ticker), **extra)
    old = owner.run_continuous_account(data, ["P"], buy_at(0), config(), **common)
    new = owner.run_continuous_account(data, ["P"], buy_at(0), config(), research_ca_accounting_convention=ref, **common)
    assert_same(without_convention(old), without_convention(new))
    assert new.research_ca_accounting_boundary_audit.empty
    if kind == "MKFG":
        assert new.final_state["fractional_shares"].tolist() == [[0.]]
        assert new.daily.entitlement_cash_flow_usd.eq(0).all()
        assert "CASH_PAID" not in new.entitlements.phase.tolist()
        assert new.daily.receivable_value_usd.iloc[-1] == 120.


@pytest.mark.parametrize("field,value", [("real_effective_clock_proven", True), ("research_session_boundary_assumption", False),
                                          ("strict_PIT_promotion_eligible", True), ("production_qualified", True)])
def test_false_or_missing_scientific_declaration_rejected(committed, field, value):
    _, frozen, write = committed(); frozen[field] = value
    with pytest.raises(ValueError, match="FROZEN_IDENTITY"):
        owner.load_research_ca_accounting_convention(write("changed_freeze.json", frozen))


def test_physical_source_and_scientific_commitment_tamper_rejected(committed):
    ref, frozen, write = committed()
    assert owner.load_research_ca_accounting_convention(ref)["eligible_count"] == 1
    bad = deepcopy(frozen); bad["rule_ref"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="SCIENTIFIC_COMMITMENT"):
        owner.load_research_ca_accounting_convention(write("bad_ref.json", bad))
    Path(frozen["source_refs"]["cash_catalogue"]["path"]).write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="PHYSICAL_SOURCE_CHANGED"):
        owner.load_research_ca_accounting_convention(ref)


@pytest.mark.parametrize("changes", [dict(date_only=False), dict(independent_effective_clock_proven=True),
                                      dict(effective_date="2024-01-04 12:00"), dict(effective_timezone="UNKNOWN"),
                                      dict(dated_sid_count=2), dict(coordinate="UNKNOWN")])
def test_intraday_unknown_timezone_or_unqualified_identity_cannot_become_date_only(committed, changes):
    row = population_row(mechanism()); row.update(changes); ref, _, _ = committed([row])
    with pytest.raises(ValueError, match="POPULATION_KEY|ELIGIBLE_MECHANISM"):
        owner.load_research_ca_accounting_convention(ref)


def test_convention_requires_actual_research_authority_and_preopen_hook(committed):
    ref, _, _ = committed()
    with pytest.raises(ValueError, match="REQUIRES_RESEARCH_AUTHORITY_AND_ENTITLEMENT_HOOK"):
        owner.run_continuous_account(market(), ["P"], buy_at(0), config(), research_ca_accounting_convention=ref)
    kwargs = args(); kwargs["research_account_authority"] = None
    with pytest.raises(ValueError, match="REQUIRES_RESEARCH_AUTHORITY_AND_ENTITLEMENT_HOOK"):
        owner.run_continuous_account(market(), ["P"], buy_at(0), config(), research_ca_accounting_convention=ref, **kwargs)
