"""New-task binding of the existing shareholder and settled-cash owners.

This module reads only declared contract metadata. The caller must supply raw
share market arrays and qualified source-backed event terms. Corporate quantity,
rights, blocked-event and payment logic remain the existing owners' code.
"""
from __future__ import annotations
import ast
import copy
import hashlib
import json
from pathlib import Path
import re
import types
import numpy as np
import pandas as pd
from scripts.research.a2.evaluation import continuous_research_account as owner
from scripts.research.a2.evaluation.consensus_cash_account import run_cash_account, FeeConfig
from scripts.v22 import corporate_action_transition_r1 as ca

TASK = "CONSENSUS100_PTO_3000_20261012_R1"
SCHEMA = "CONSENSUS100_SOURCE_BOUND_SHAREHOLDER_ACCOUNT_AUTHORITY_R1"
CHILD_RESEARCH_ID = "CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2"
CHILD_RUN = Path("D:/us-tech-quant-backtests/CONSENSUS100_PTO_3000_PRE2026_SOURCE_COMPLETION_R2/20261012T025603+0000_4a58260e")
CONTINUATION_REF = dict(path=str(CHILD_RUN / "CONTINUATION_SCOPE.json"), sha256="0a0220d73bffef0db6b427a79a1e10abd34b3bf9725d68ebe5f6366369a5da41")
CONVENTION_REF = dict(path=str(CHILD_RUN / "ACCOUNT_CONVENTION_SCOPE.json"), sha256="71ccae1d26b09cd972747a1876f7750b940e5b133abac5010c0a7bf28045eba8")
FX_CONVENTION_REF = dict(path=str(CHILD_RUN / "ACCOUNT_FX_CONVENTION_SCOPE.json"), sha256="51599f455458fce9393f684db1b243ee723426b44e2253c2918b5a21e31f0449")
FX_AVAILABILITY_REF = dict(path=str(CHILD_RUN / "FX_SOURCE_AVAILABILITY_QUALIFICATION.json"), sha256="4e1749b0758d258783c5a2ddcc9d2f407d686d6d29a16f89d6b8ff4fd784e8b8")
STOCK_EVENT_TERMS = {("DHR", "2023-10-02"): ("VLTO", 1, 3, "COMMON_SHARE"),
    ("FTV", "2025-06-30"): ("RAL", 1, 3, "COMMON_SHARE"),
    ("LBTYK", "2024-11-13"): ("SNRE", 1, 5, "AMERICAN_DEPOSITARY_SHARE")}

OWNER_SHA = "db11f23272d9fca24165804c936778c25f53988e89c6fba0fa304a8966c70b04"
OWNER_AST_SHA = "bfb77c0c24f358410c5093973559e8976f0d58aae258c17547656da8ba547cd5"
CA_SHA = "142c36633e47633fff5c9c63be030536fa7b1dba8a67f8432643c084f4dcdce4"
CA_AST_SHA = "97149f6da69550a1514f5cf4ca2639dcfaf3e1ce8712f770c8bb5d83d34a8e2f"


def _metadata_ref(ref, *, scope=False, child=False):
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise ValueError("EXACT_TASK_METADATA_REF_REQUIRED")
    p = Path(ref["path"]).resolve()
    task_path = TASK in p.parts or child is True and p.is_relative_to(CHILD_RUN.resolve())
    if not task_path or not re.fullmatch(r"[0-9a-f]{64}", str(ref["sha256"])):
        raise ValueError("NEW_TASK_METADATA_REF_REQUIRED")
    if p.suffix.lower() != ".json" or p.stat().st_size > 1024 * 1024:
        raise ValueError("SMALL_TASK_JSON_METADATA_REF_REQUIRED")
    if hashlib.sha256(p.read_bytes()).hexdigest() != ref["sha256"]:
        raise ValueError("TASK_METADATA_REF_CHANGED")
    payload = json.loads(p.read_text(encoding="utf-8"))
    if payload.get("task_id", payload.get("research_id")) != TASK:
        raise ValueError("TASK_METADATA_IDENTITY_CHANGED")
    if scope and payload.get("schema") != "CONSENSUS100_ACCOUNT_SOURCE_SCOPE_R1":
        raise ValueError("CURRENT_TASK_ACCOUNT_SOURCE_SCOPE_REQUIRED")
    return dict(ref)


def _validate_source_completion_scopes(authority):
    if (authority.get("continuation_scope_ref") != CONTINUATION_REF
            or authority.get("account_convention_scope_ref") != CONVENTION_REF):
        raise ValueError("EXACT_SOURCE_COMPLETION_AND_ACCOUNT_CONVENTION_REFS_REQUIRED")
    for ref in (CONTINUATION_REF, CONVENTION_REF):
        _metadata_ref(ref, child=True)
    continuation = json.loads(Path(CONTINUATION_REF["path"]).read_text(encoding="utf-8"))
    convention = json.loads(Path(CONVENTION_REF["path"]).read_text(encoding="utf-8"))
    boundaries = continuation.get("boundaries", {})
    if (continuation.get("schema") != "CONSENSUS_PRE2026_SOURCE_COMPLETION_CONTINUATION_SCOPE_R1"
            or continuation.get("research_id") != CHILD_RESEARCH_ID
            or continuation.get("task_id") != TASK
            or continuation.get("parent_research_id") != TASK
            or Path(continuation.get("run", "")).resolve() != CHILD_RUN.resolve()
            or boundaries.get("no_new_2026_sample_or_outcome_read_authorized") is not True
            or boundaries.get("FAST3_Confirmation_access") is not False):
        raise ValueError("EXACT_PRE2026_CONTINUATION_SCOPE_REQUIRED")
    stock = convention.get("stock_distribution_research_convention", {})
    if (convention.get("schema") != "CONSENSUS_SOURCE_COMPLETION_ACCOUNT_CONVENTION_R1"
            or convention.get("status") != "FROZEN_BEFORE_NEW_ACCOUNT_REPLAY_OR_SELECTION"
            or convention.get("research_id") != CHILD_RESEARCH_ID or convention.get("task_id") != TASK
            or convention.get("continuation_scope_ref") != CONTINUATION_REF
            or stock.get("mode") != ca.STOCK_DISTRIBUTION_RESEARCH_MODE
            or stock.get("parent_share_multiplier") != 1.
            or stock.get("exact_supported_event_tickers") != ["DHR", "FTV", "LBTYK"]
            or stock.get("supported_event_delivery_scope") != "DELIVERY_NO_LATER_THAN_EX_SESSION"
            or stock.get("pending_stock_claim_without_qualified_close_nav_mark") != "HARD_BLOCK"
            or stock.get("actual_broker_fractional_distribution_or_cash_in_lieu_execution_certified") is not False):
        raise ValueError("EXACT_FROZEN_BENEFICIAL_FRACTIONAL_RESEARCH_CONVENTION_REQUIRED")


def _validate_foreign_cash_scopes(authority):
    if (authority.get("account_fx_convention_scope_ref") != FX_CONVENTION_REF
            or authority.get("fx_source_availability_qualification_ref") != FX_AVAILABILITY_REF):
        raise ValueError("EXACT_FROZEN_CAD_AND_SOURCE_AVAILABILITY_SCOPE_REFS_REQUIRED")
    for ref in (FX_CONVENTION_REF, FX_AVAILABILITY_REF):
        _metadata_ref(ref, child=True)
    convention = json.loads(Path(FX_CONVENTION_REF["path"]).read_text(encoding="utf-8"))
    qualification = json.loads(Path(FX_AVAILABILITY_REF["path"]).read_text(encoding="utf-8"))
    if (convention.get("schema") != "CONSENSUS_SOURCE_COMPLETION_CAD_CLAIM_CONVENTION_R1"
            or convention.get("research_id") != CHILD_RESEARCH_ID
            or convention.get("continuation_scope_ref") != CONTINUATION_REF
            or convention.get("account_convention_scope_ref") != CONVENTION_REF
            or convention.get("conversion_friction_bps") != 25.
            or convention.get("declared_cad_amount_as_usd_allowed") is not False
            or convention.get("actual_broker_fx_rate_fee_payment_or_tax_certified") is not False
            or qualification.get("schema") != "CONSENSUS_FX_RELEASE_DATE_AVAILABILITY_QUALIFICATION_R1"
            or qualification.get("fx_convention_scope_ref") != FX_CONVENTION_REF
            or qualification.get("research_id") != CHILD_RESEARCH_ID
            or qualification.get("available_at_convention") != "END_OF_CERTIFIED_RELEASE_DATE_AMERICA_NEW_YORK_23_59_59_CONVERTED_TO_UTC"
            or qualification.get("actual_timestamp_authority") != "UNKNOWN_RETAINED"
            or qualification.get("same_release_date_market_close_mark_allowed") is not False):
        raise ValueError("FROZEN_CAD_GROSS_CLAIM_AND_CONSERVATIVE_AVAILABILITY_REQUIRED")


def validate_task_authority(events, authority):
    """Authorize this task only; old admissions remain source-fact evidence."""
    events = tuple(events)
    expected = dict(schema=SCHEMA, task_id=TASK,
        scientific_identity="CONSENSUS100_PTO_SOURCE_BOUND_RESEARCH_ACCOUNT",
        clock_role="POST_VERIFIED_ACCOUNTING_ONLY", scope_start="2023-01-01",
        scope_end_exclusive="2026-01-01", raw_price_coordinate="RAW_ACTUAL_SHARE",
        strict_PIT_promotion_eligible=False, production_qualified=False,
        quote_qualified=False, certified_NAV=False,
        accounting_clock_convention="ORDINARY_CASH_PAY_DATE_END_NEXT_ACCOUNT_SESSION")
    extra = {"frozen_contract_ref", "source_scope_ref", "market_source_binding",
        "event_fingerprints", "ordinary_cash_event_fingerprints",
        "frozen_history_cash_admission", "terminal_source_authority"}
    completion = isinstance(authority, dict) and any(k in authority for k in ("continuation_scope_ref", "account_convention_scope_ref"))
    if completion:
        extra |= {"continuation_scope_ref", "account_convention_scope_ref"}
    foreign_scope = isinstance(authority, dict) and any(k in authority for k in ("account_fx_convention_scope_ref", "fx_source_availability_qualification_ref"))
    if foreign_scope:
        extra |= {"account_fx_convention_scope_ref", "fx_source_availability_qualification_ref"}
    if (not isinstance(authority, dict) or set(authority) != set(expected) | extra
            or any(type(authority.get(k)) is not type(v) or authority.get(k) != v for k,v in expected.items())):
        raise ValueError("NEW_TASK_SHAREHOLDER_AUTHORITY_REQUIRED")
    if completion:
        _validate_source_completion_scopes(authority)
    _metadata_ref(authority["frozen_contract_ref"], child=completion)
    _metadata_ref(authority["source_scope_ref"], scope=True, child=completion)
    market = authority["market_source_binding"]
    if (not isinstance(market, dict) or market.get("task_id") != TASK
            or market.get("quantity_coordinate") != "RAW_ACTUAL_SHARE"
            or market.get("historical_quote_vintage_status") != "UNKNOWN"
            or not isinstance(market.get("source_refs"), list) or not market["source_refs"]
            or not isinstance(market.get("coverage_gaps"), list)):
        raise ValueError("RAW_SHARE_MARKET_SOURCE_BINDING_REQUIRED")
    for ref in market["source_refs"]:
        if (not isinstance(ref,dict) or not isinstance(ref.get("path"),str)
                or not re.fullmatch(r"[0-9a-f]{64}",str(ref.get("sha256")))):
            raise ValueError("MARKET_SOURCE_PIN_REQUIRED")
    if any(not isinstance(e,(ca.SourceBackedEntitlementEvent,ca.SourceBackedTerminalEvent,ca.SourceBackedStockDistributionEvent))
           or isinstance(e,ca.ResearchPostVerifiedTerminalEvent)
           or not pd.Timestamp("2023-01-01") <= ca._entitlement_effective_day(e) < pd.Timestamp("2026-01-01") for e in events):
        raise ValueError("TASK_PRE2026_TYPED_EVENT_SCOPE_REQUIRED")
    foreign_events = tuple(e for e in events if isinstance(e, ca.SourceBackedForeignCashEvent))
    if foreign_events and not (completion and foreign_scope):
        raise ValueError("CAD_CASH_EXACT_CHILD_FX_RESEARCH_SCOPE_REQUIRED")
    if foreign_scope:
        if not completion:
            raise ValueError("CAD_CASH_SOURCE_COMPLETION_SCOPE_REQUIRED")
        _validate_foreign_cash_scopes(authority)
    if any(e.ticker != "TRP" for e in foreign_events):
        raise ValueError("CAD_CASH_EXACT_TRP_COMMON_SCOPE_REQUIRED")
    stock_events = tuple(e for e in events if isinstance(e, ca.SourceBackedStockDistributionEvent))
    if stock_events and not completion:
        raise ValueError("STOCK_DISTRIBUTION_EXACT_CHILD_RESEARCH_SCOPE_REQUIRED")
    for event in stock_events:
        if STOCK_EVENT_TERMS.get((event.ticker, event.ex_date)) != (event.child_ticker,
                event.child_ratio_numerator, event.child_ratio_denominator, event.child_quantity_unit):
            raise ValueError("SOURCE_COMPLETION_EXACT_THREE_STOCK_EVENT_TERMS_REQUIRED")
    pins = authority["event_fingerprints"]
    if not isinstance(pins,list) or len(set(pins)) != len(pins) or sorted(pins) != sorted(e.event_fingerprint for e in events):
        raise ValueError("TASK_EXACT_EVENT_CATALOGUE_REQUIRED")
    ordinary = authority["ordinary_cash_event_fingerprints"]
    actual_ordinary = [e.event_fingerprint for e in events if not isinstance(e,ca.SourceBackedTerminalEvent) and e.action_type=="CASH_DIVIDEND"]
    if not isinstance(ordinary,list) or sorted(ordinary) != sorted(actual_ordinary):
        raise ValueError("TASK_EXACT_ORDINARY_CASH_CATALOGUE_REQUIRED")
    # Reuse unchanged source-fact validators. Their old task IDs are provenance,
    # never this task's execution authority or permission to read new inputs.
    admission = ca._validate_frozen_history_cash_admission(events, authority["frozen_history_cash_admission"])
    terminals = tuple(e for e in events if isinstance(e,ca.ResearchReconstructedTerminalEvent))
    terminal_fact = authority["terminal_source_authority"]
    if terminals:
        if ca._validate_research_account_authority(terminals,terminal_fact) is None:
            raise ValueError("ORIGINAL_TERMINAL_SOURCE_FACT_BINDING_REQUIRED")
    elif terminal_fact is not None:
        raise ValueError("UNUSED_TERMINAL_SOURCE_FACT_AUTHORITY")
    for event in events:
        if isinstance(event,ca.ResearchReconstructedCashEvent):
            event.__post_init__(source_scope="B_FROZEN_PRE2026_ACCOUNTING_ONLY")
        else:
            event.__post_init__()
    return {**copy.deepcopy(authority), "frozen_history_cash_admission":admission}


def make_task_authority(events, *, frozen_contract_ref, source_scope_ref, market_source_binding,
                        frozen_history_cash_admission=None, terminal_source_authority=None,
                        continuation_scope_ref=None, account_convention_scope_ref=None,
                        account_fx_convention_scope_ref=None, fx_source_availability_qualification_ref=None):
    events=tuple(events)
    result=dict(schema=SCHEMA, task_id=TASK,
        scientific_identity="CONSENSUS100_PTO_SOURCE_BOUND_RESEARCH_ACCOUNT",
        clock_role="POST_VERIFIED_ACCOUNTING_ONLY",scope_start="2023-01-01",scope_end_exclusive="2026-01-01",
        raw_price_coordinate="RAW_ACTUAL_SHARE",strict_PIT_promotion_eligible=False,production_qualified=False,
        quote_qualified=False,certified_NAV=False,accounting_clock_convention="ORDINARY_CASH_PAY_DATE_END_NEXT_ACCOUNT_SESSION",
        frozen_contract_ref=frozen_contract_ref,source_scope_ref=source_scope_ref,market_source_binding=market_source_binding,
        event_fingerprints=sorted(e.event_fingerprint for e in events),
        ordinary_cash_event_fingerprints=sorted(e.event_fingerprint for e in events if not isinstance(e,ca.SourceBackedTerminalEvent) and e.action_type=="CASH_DIVIDEND"),
        frozen_history_cash_admission=frozen_history_cash_admission,terminal_source_authority=terminal_source_authority)
    if continuation_scope_ref is not None or account_convention_scope_ref is not None:
        result.update(continuation_scope_ref=continuation_scope_ref, account_convention_scope_ref=account_convention_scope_ref)
    if account_fx_convention_scope_ref is not None or fx_source_availability_qualification_ref is not None:
        result.update(account_fx_convention_scope_ref=account_fx_convention_scope_ref,
            fx_source_availability_qualification_ref=fx_source_availability_qualification_ref)
    return validate_task_authority(events,result)


def _project_continuous(engine_factory, bound_events, bound_authority):
    for module, expected in ((owner,OWNER_SHA),(ca,CA_SHA)):
        if hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()!=expected:
            raise ValueError("SHAREHOLDER_OWNER_SOURCE_CHANGED")
    tree=ast.parse(Path(owner.__file__).read_text(encoding="utf-8"))
    function=copy.deepcopy(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="run_continuous_account"))
    if hashlib.sha256(ast.dump(function).encode()).hexdigest()!=OWNER_AST_SHA:
        raise ValueError("SHAREHOLDER_OWNER_AST_CHANGED")
    ca_tree=ast.parse(Path(ca.__file__).read_text(encoding="utf-8"))
    ca_function=next(n for n in ca_tree.body if isinstance(n,ast.FunctionDef) and n.name=="apply_entitlement_lifecycle")
    if hashlib.sha256(ast.dump(ca_function).encode()).hexdigest()!=CA_AST_SHA:
        raise ValueError("ENTITLEMENT_LIFECYCLE_OWNER_AST_CHANGED")
    edits=[]
    def replace(old,new):
        old_nodes,new_nodes=ast.parse(old).body,ast.parse(new).body
        matches=[]
        for node in ast.walk(function):
            for field,value in ast.iter_fields(node):
                if isinstance(value,list):
                    for index in range(len(value)-len(old_nodes)+1):
                        if all(isinstance(value[index+j],ast.AST) and ast.dump(value[index+j])==ast.dump(old_nodes[j]) for j in range(len(old_nodes))):
                            matches.append((value,index))
        if len(matches)!=1:raise ValueError("SHAREHOLDER_EXACT_ANCHOR_CHANGED:"+old)
        nodes,index=matches[0];nodes[index:index+len(old_nodes)]=new_nodes;edits.append(old)
    replace('''full_selector_scope = (isinstance(research_account_authority, dict)
    and research_account_authority.get("schema") == "C_FULL_SELECTOR_FIXED_POLICY_ACCOUNT_AUTHORITY_V1")''',
        '''full_selector_scope = (isinstance(research_account_authority, dict)
    and research_account_authority.get("schema") == _task_schema)''')
    replace('previous_daily_cash = np.full(s, capital, dtype=float)',
        'previous_daily_cash = np.full(s, capital, dtype=float)\nprevious_unsettled_cash = np.zeros(s)')
    replace('error = out.cash.to_numpy(float) - previous_daily_cash[rr] - paid - actual_sells + actual_buys',
        'error = out.cash.to_numpy(float) - previous_daily_cash[rr] - paid - actual_sells + actual_buys + out.transaction_cost_amount.to_numpy(float) + out.unsettled_cash.to_numpy(float) - previous_unsettled_cash[rr]')
    replace('previous_daily_cash[rr] = out.cash.to_numpy(float)',
        'previous_daily_cash[rr] = out.cash.to_numpy(float)\nprevious_unsettled_cash[rr] = out.unsettled_cash.to_numpy(float)')
    # Initial validation has already read/pinned the task metadata and immutable
    # event facts once. The existing owner forwards the same authority object and
    # creates at most one new tuple for the active catalogue. Keep those exact
    # identities bound instead of reopening metadata for every path/session.
    accepted_catalogues = {id(bound_events): bound_events}
    def bound_validator(events, authority):
        if authority is not bound_authority:
            raise ValueError("TASK_BOUND_AUTHORITY_IDENTITY_CHANGED")
        prior = accepted_catalogues.get(id(events))
        if prior is not events:
            if (not isinstance(events, tuple) or len(events) != len(bound_events)
                    or any(a is not b for a, b in zip(events, bound_events))):
                raise ValueError("TASK_BOUND_ACTIVE_EVENT_CATALOGUE_CHANGED")
            accepted_catalogues[id(events)] = events
        return bound_authority
    lifecycle = types.FunctionType(ca.apply_entitlement_lifecycle.__code__,
        {**ca.apply_entitlement_lifecycle.__globals__,"_validate_research_account_authority":bound_validator,
         "_FULL_SELECTOR_ACCOUNT_SCHEMA":SCHEMA},argdefs=ca.apply_entitlement_lifecycle.__defaults__,closure=ca.apply_entitlement_lifecycle.__closure__)
    lifecycle.__kwdefaults__=ca.apply_entitlement_lifecycle.__kwdefaults__
    namespace={**owner.__dict__,"_task_schema":SCHEMA,"_validate_research_account_authority":bound_validator,
               "apply_entitlement_lifecycle":lifecycle,"_engine_with_entitlement_hook":engine_factory}
    module=ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[]))
    exec(compile(module,owner.__file__,"exec"),namespace)
    return namespace["run_continuous_account"],dict(owner_source_sha256=OWNER_SHA,owner_ast_sha256=OWNER_AST_SHA,
        corporate_owner_source_sha256=CA_SHA,corporate_lifecycle_ast_sha256=CA_AST_SHA,
        task_projected_ast_sha256=hashlib.sha256(ast.dump(function).encode()).hexdigest(),ast_anchor_count=len(edits),
        original_owners_unchanged=True,task_metadata_validation="ONCE BEFORE REPLAY; exact authority and immutable event identities during lifecycle",lifecycle_algorithm="UNCHANGED EXISTING OWNER; task authority global binding only")


def run_shareholder_cash_account(market,path_ids,policy,*,task_authority,settlement_calendar,fee_config=None,
        corporate_actions=(),corporate_action_known_at=None,unsupported_events=(),
        entitlement_events=(),entitlement_security_tickers=None,entitlement_source_binding=None,
        research_quote_domain=None,research_ca_accounting_convention=None,usable_a=None,ledger_callback=None,
        foreign_fx_marks=()):
    """Complete existing raw-share lifecycle + task cash/cost replay bridge.

    Caller supplies qualified pre2026 market arrays and source facts. This API
    does not load prices or event caches and cannot authorize future/test reads.
    Both normal-trade settlement and corporate receivables remain NAV assets;
    only actual releases can fund orders. Quote provenance stays UNKNOWN.
    """
    events=tuple(entitlement_events);authority=validate_task_authority(events,task_authority)
    if market.dates[0]<pd.Timestamp("2023-01-01") or market.dates[-1]>=pd.Timestamp("2026-01-01"):
        raise ValueError("TASK_SOURCE_BOUND_ACCOUNT_PRE2026_2023PLUS_ONLY")
    if any(ca._entitlement_effective_day(e) < market.dates[0] for e in events):
        raise ValueError("CALLER_EVENT_CATALOGUE_MUST_MATCH_ACCOUNT_PREFIX")
    config=fee_config or FeeConfig()
    account_config=dict(base_currency="USD",initial_nav=3000.,initial_cash=3000.,initial_holdings=[],
        fractional_shares=True,integer_share_rounding=False,cash_interest=0,transaction_cost_bps=0,
        financing=False,borrowed_cash=False,long_only=True,max_positions=20,max_weight=.10,max_invested=.95,capacity_fraction=.01)
    projections=[]
    def engine_factory(hook, operational_exit_hook=None):
        def engine(common_market,ids,wrapped,**kwargs):
            kwargs.pop("cost_bps",None)
            return run_cash_account(common_market,ids,wrapped,fee_config=config,settlement_calendar=settlement_calendar,
                corporate_action_hook=hook,usable_a=usable_a,**kwargs)
        if operational_exit_hook is not None:
            hook._stock_distribution_operational_mask = operational_exit_hook
        _,lineage=owner._engine_with_entitlement_hook(hook, operational_exit_hook=operational_exit_hook)
        projections.append(lineage)
        return engine,lineage
    runner,lineage=_project_continuous(engine_factory,events,authority)
    result=runner(market,path_ids,policy,account_config,corporate_actions=tuple(corporate_actions),
        corporate_action_known_at=corporate_action_known_at,unsupported_events=tuple(unsupported_events),
        entitlement_enabled=True,entitlement_events=events,entitlement_security_tickers=entitlement_security_tickers,
        entitlement_source_binding=entitlement_source_binding,research_account_authority=authority,
        research_quote_domain=research_quote_domain,research_ca_accounting_convention=research_ca_accounting_convention,
        ledger_callback=ledger_callback,execution_friction=None,foreign_fx_marks=foreign_fx_marks,
        foreign_conversion_friction_bps=25. if any(isinstance(e,ca.SourceBackedForeignCashEvent) for e in events) else None)
    result.final_state["unsettled_trade_cash"]=result.final_unsettled_cash.copy()
    result.final_state["total_cash_assets"]=result.final_cash+result.final_unsettled_cash+result.final_state["receivable_value_usd"]
    result.metadata.update(consensus_shareholder_bridge=True,shareholder_bridge_lineage=lineage,
        task_account_authority=authority,normal_trade_settlement="SINGLE CONSENSUS_CASH_ACCOUNT OWNER",
        costs="ONE_WAY_ALL_IN_PROXY_PLUS_FIXED_FEE; benchmark raw open; no separate spread/slippage debit",
        quote_vintage_status="UNKNOWN",certified_NAV=False,conditional_shareholder_research_only=True,
        transaction_cost_semantics="consensus fee_for_notional once per actual fill; account_config zero legacy cost is owner compatibility only")
    return result