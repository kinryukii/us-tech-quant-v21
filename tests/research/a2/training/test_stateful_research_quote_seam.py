"""Synthetic proof: quote admission never waives corporate-action accounting."""
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.evaluation.continuous_research_account import run_continuous_account
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays, TargetDecision
from scripts.research.a2.training import stateful_research_quote_domain as domain


def inputs():
    dates = pd.to_datetime(["2023-12-29", "2024-01-02", "2024-01-03", "2024-01-04"])
    price = np.array([[10.], [10.], [11.], [12.]])
    market = MarketArrays(dates, ["S"], price.copy(), price.copy(),
        adv=np.full(price.shape, 1e9), signal_mask=np.ones(len(dates), bool))
    config = dict(base_currency="USD", initial_nav=3000., initial_cash=3000., initial_holdings=[],
        fractional_shares=True, integer_share_rounding=False, cash_interest=0,
        transaction_cost_bps=0, financing=False, borrowed_cash=False, long_only=True,
        max_positions=20, max_weight=1., max_invested=1., capacity_fraction=None)
    authority = dict(scientific_identity="FROZEN_HISTORY_RESEARCH_ACCOUNT",
        task_id="V24_A_FROZEN_HISTORY_RESEARCH_ACCOUNT_AND_POLICY_EVALUATION_R1",
        frozen_contract_sha256="a" * 64, clock_role="RECONSTRUCTED_REALIZED_EVENT",
        event_fingerprints=[], strict_PIT_promotion_eligible=False, production_qualified=False)
    event = dict(ticker="S", effective_date="2024-01-03", reason="SYNTHETIC_UNHANDLED_ACCOUNT_EVENT",
        source_reference="synthetic://event", source_fingerprint="b" * 64)
    record = dict(ticker="S", date="2024-01-03", masked=True, inherited_event_mask=True,
        raw_rows=[dict(ticker="S", date="2024-01-03", code="CODE_S", open=11., close=11.)],
        identity_records=[dict(sid="SID_S", ticker="S", start="2023-01-01", end="2026-01-01", coordinate="RAW_ACTUAL_SHARE")],
        code_tickers={"CODE_S": ["S"]}, coordinate="RAW_ACTUAL_SHARE", independent_quality_flags=[],
        mechanisms=[dict(ticker="S", date="2024-01-03", mask_origin="INHERITED_UNSUPPORTED_EVENT",
            reason=event["reason"], source_reference=event["source_reference"], source_fingerprint=event["source_fingerprint"])],
        terminal_contracts=[])
    decisions = domain.classify_population([record])
    assert decisions[0]["classification"] == "A"
    def policy(di, ctx):
        if di == 0:
            return TargetDecision(np.array([[.8]]), ctx.decision_mask)
        return TargetDecision(np.zeros((1, 1)), np.zeros((1, 1), bool))
    return market, config, authority, event, decisions, policy


def test_quote_admission_keeps_unsupported_accounting_exception(monkeypatch):
    market, config, authority, event, decisions, policy = inputs()
    monkeypatch.setattr(domain, "load_frozen_domain", lambda ref: {"decisions": decisions})
    old = run_continuous_account(market, ["P"], policy, config,
        unsupported_events=[event], research_account_authority=authority)
    new = run_continuous_account(market, ["P"], policy, config,
        unsupported_events=[event], research_account_authority=authority,
        research_quote_domain={"path": "SYNTHETIC_ONLY", "sha256": "c" * 64})
    assert old.positions.loc[old.positions.date.eq("2024-01-03"), "stale"].eq(True).all()
    assert new.positions.loc[new.positions.date.eq("2024-01-03"), "stale"].eq(False).all()
    assert old.accounting_exceptions.reason.tolist() == new.accounting_exceptions.reason.tolist()
    assert len(new.accounting_exceptions) == 1
    assert new.daily.loc[new.daily.date.ge("2024-01-03"), "accounting_qualified"].eq(False).all()
    assert new.daily.loc[new.daily.date.ge("2024-01-03"), "certified_nav"].isna().all()
    assert new.metadata["annual_reset"] is False


def test_independent_base_quality_survives_shared_quote_admission(monkeypatch):
    market, config, authority, event, decisions, policy = inputs()
    market.quality[2, 0] = True
    monkeypatch.setattr(domain, "load_frozen_domain", lambda ref: {"decisions": decisions})
    new = run_continuous_account(market, ["P"], policy, config,
        unsupported_events=[event], research_account_authority=authority,
        research_quote_domain={"path": "SYNTHETIC_ONLY", "sha256": "c" * 64})
    assert new.positions.loc[new.positions.date.eq("2024-01-03"), "stale"].eq(True).all()
    assert new.final_state["accounting_qualified"].tolist() == [False]


def test_shared_quote_domain_requires_separate_research_account_authority():
    market, config, _, event, _, policy = inputs()
    with pytest.raises(ValueError, match="RESEARCH_QUOTE_DOMAIN_REQUIRES_RESEARCH_ACCOUNT_AUTHORITY"):
        run_continuous_account(market, ["P"], policy, config, unsupported_events=[event],
            research_quote_domain={"path": "SYNTHETIC_ONLY", "sha256": "c" * 64})
