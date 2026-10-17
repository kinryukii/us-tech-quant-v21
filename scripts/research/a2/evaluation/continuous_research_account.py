"""Persistent research traces using the immutable common account engine.

Year/fold boundaries never reset accounts. Locked continuation replays one
frozen full prefix and checks its ledger identity before accepting test rows.
"""
from __future__ import annotations
from dataclasses import dataclass, replace, asdict
import ast
import copy
from pathlib import Path
import re
import hashlib
import numpy as np
import pandas as pd
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import MarketArrays, TargetDecision, run_many
from scripts.v22.corporate_action_transition_r1 import (
    CorporateActionTransition, CorporateActionTransitionAdapter, apply_transition_to_positions,
    SourceBackedEntitlementEvent, SourceBackedTerminalEvent, ResearchReconstructedCashEvent,
    ResearchPostVerifiedTerminalEvent, SourceBackedStockDistributionEvent,
    SourceBackedForeignCashEvent, SourceBackedFXMark, select_foreign_fx_mark, foreign_claim_value_usd,
    EntitlementLifecycleState,
    apply_entitlement_lifecycle, RAW_OLD_SHARE_COORDINATE,
    _entitlement_effective_day, _entitlement_pay_date, _validate_research_account_authority,
)
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2 import fast_account as _common_engine

TOL = 1e-10
TERMINAL_LEDGER_COLUMNS = ["action_type", "effective_date", "effective_at", "effective_clock_basis",
    "remaining_raw_shares", "quantity_coordinate", "quantity_source_reference",
    "quantity_source_fingerprint", "pre_effective_engine_units", "pre_effective_quantity_factor",
    "settlement_source_reference", "settlement_source_fingerprint", "settlement_available_at",
    "cash_per_old_share", "currency", "amount_unit", "receivable_id"]

@dataclass(frozen=True)
class PersistentPolicyContext:
    common: object
    holding_age: np.ndarray
    entry_date: np.ndarray
    entry_price: np.ndarray
    entry_execution_open: np.ndarray
    current_units: np.ndarray
    receivable_value_usd: np.ndarray | None = None
    accounting_qualified: np.ndarray | None = None
    stock_distribution_forced_exit_mask: np.ndarray | None = None

    def __getattr__(self, name):
        return getattr(self.common, name)


# This projection binds the single retained execution algorithm. It adds only
# an accounting hook and non-spendable assets to the existing NAV identities.
ENTITLEMENT_ENGINE_SHA256 = "200462d48816918a5b9fe72f2239a81d01f69a32d57922e8e47cf1ee4c06ee1b"


_SESSION_BOUNDARY_TASK = "V24_A_FROZEN_HISTORY_SESSION_BOUNDARY_CA_ACCOUNTING_R1"
_SESSION_BOUNDARY_IDENTITY = "FROZEN_HISTORY_SESSION_BOUNDARY_CA_ACCOUNTING"
_SESSION_BOUNDARY_KEY = ("ticker", "effective_date", "reason", "source_reference", "source_fingerprint")
_SESSION_BOUNDARY_COMMITMENTS = {
    "contract_ref": "dec3076f9f100c0dbaf1d4cb9ead4980aaa00dfc17a378c52594ea5fb9f190df",
    "rule_ref": "3ad8a1e2e44424e8e563070a5e47a98893f9800eb32e19cdcc3ed950deef78a8",
    "population_ref": "91ae0889d3b0d7a924810c989ad8c16c53c19346180fee40f95658dce574f336",
}


def _session_boundary_mechanism_key(event):
    """Exact frozen source identity; never normalize a time into a session date."""
    if not isinstance(event, dict):
        return None
    values = tuple(event.get(k) for k in _SESSION_BOUNDARY_KEY)
    if any(not isinstance(v, str) or not v for v in values):
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", values[1]):
        return None
    if not re.fullmatch(r"[0-9a-f]{64}", values[4]):
        return None
    try:
        if pd.Timestamp(values[1]).date().isoformat() != values[1]:
            return None
    except (ValueError, TypeError):
        return None
    # A separately supplied effective instant/timezone is not a date-only record.
    if any(event.get(k) is not None for k in
           ("effective_at", "effective_time", "effective_timezone", "source_effective_at")):
        return None
    return values


def load_research_ca_accounting_convention(ref):
    """Load exact pre-attempt commitments, not caller admission booleans.

    Reuses canonical physical-reference custody. Only frozen JSON and source/code
    hash streams are read; no market rows or account results are decoded.
    """
    import json
    from collections import Counter
    from scripts.research.a2.training.stateful_research_quote_domain import _reference_path

    checked = {}
    def physical(reference):
        if not isinstance(reference, dict):
            raise ValueError("SESSION_BOUNDARY_PHYSICAL_REFERENCE_REQUIRED")
        key = (str(reference.get("path", "")), reference.get("sha256"))
        if key not in checked:
            checked[key] = _reference_path(reference)
        return checked[key]

    def references(value):
        if isinstance(value, dict):
            if "path" in value and "sha256" in value:
                physical(value)
            else:
                for child in value.values():
                    references(child)
        elif isinstance(value, list):
            for child in value:
                references(child)

    def identity(value, schema, status):
        if (value.get("schema") != schema or value.get("status") != status or
                value.get("task_id") != _SESSION_BOUNDARY_TASK or
                value.get("scientific_identity") != _SESSION_BOUNDARY_IDENTITY or
                value.get("namespace", _SESSION_BOUNDARY_IDENTITY) != _SESSION_BOUNDARY_IDENTITY or
                value.get("real_effective_clock_proven") is not False or
                value.get("research_session_boundary_assumption") is not True or
                value.get("strict_PIT_promotion_eligible") is not False or
                value.get("production_qualified") is not False):
            raise ValueError("SESSION_BOUNDARY_FROZEN_IDENTITY_OR_DECLARATION_CHANGED")

    frozen = json.loads(physical(ref).read_text(encoding="utf-8"))
    identity(frozen, "SESSION_BOUNDARY_CA_SOURCE_AND_CODE_FREEZE_R1", "FROZEN_BEFORE_ACCOUNT_ATTEMPT")
    for key, expected in _SESSION_BOUNDARY_COMMITMENTS.items():
        if frozen.get(key, {}).get("sha256") != expected:
            raise ValueError("SESSION_BOUNDARY_SCIENTIFIC_COMMITMENT_CHANGED")
    contract = json.loads(physical(frozen["contract_ref"]).read_text(encoding="utf-8"))
    rule = json.loads(physical(frozen["rule_ref"]).read_text(encoding="utf-8"))
    population = json.loads(physical(frozen["population_ref"]).read_text(encoding="utf-8"))
    identity(contract, "SESSION_BOUNDARY_CA_ACCOUNTING_CONTRACT_R1", "FROZEN_BEFORE_ANY_NEW_ACCOUNT")
    identity(rule, "SESSION_BOUNDARY_CA_RULE_R1", "FROZEN_BEFORE_ANY_NEW_ACCOUNT")
    identity(population, "SESSION_BOUNDARY_CA_POPULATION_R1", "FULL_FROZEN_SOURCE_POPULATION")
    if (contract.get("session_boundary_rule_ref") != frozen["rule_ref"] or
            contract.get("session_boundary_population_ref") != frozen["population_ref"] or
            population.get("rule_ref") != frozen["rule_ref"] or
            contract.get("human_authority") != frozen.get("human_authorization_ref") or
            rule.get("human_authorization_ref") != frozen.get("human_authorization_ref") or
            frozen.get("source_refs") != rule.get("source_refs") or
            population.get("source_refs") != rule.get("source_refs")):
        raise ValueError("SESSION_BOUNDARY_FROZEN_REFERENCE_CLOSURE_CHANGED")
    sources = rule.get("source_refs", {})
    required_sources = {"event_mechanism_source", "security_mapping", "cash_catalogue",
                        "original_event_input_binding", "original_static_event_source"}
    if not required_sources.issubset(sources):
        raise ValueError("SESSION_BOUNDARY_SOURCE_CUSTODY_INCOMPLETE")
    if (rule.get("exact_mechanism_key") != list(_SESSION_BOUNDARY_KEY) or
            rule.get("boundary") != "SESSION_PRE_TRADE_PRE_OPEN_LIFECYCLE_HOOK" or
            rule.get("declaration") != "THIS_IS_A_RESEARCH_ACCOUNTING_CONVENTION_NOT_AN_OBSERVED_REAL_WORLD_EFFECTIVE_INSTANT" or
            rule.get("typed_authority_priority") is not True or
            rule.get("no_term_inference") is not True or
            rule.get("observed8_whitelist") is not False or
            rule.get("decision_information_unchanged") is not True or
            rule.get("quote_rule_unchanged") is not True or
            rule.get("NAV_comparator_unchanged") is not True):
        raise ValueError("SESSION_BOUNDARY_RULE_SEMANTICS_CHANGED")
    for document in (frozen, contract, rule, population):
        references(document)
    pins = frozen.get("code_pins", {})
    if not isinstance(pins, dict) or not pins:
        raise ValueError("SESSION_BOUNDARY_CODE_CUSTODY_REQUIRED")
    pinned_paths = {physical(dict(path=p, sha256=sha)) for p, sha in pins.items()}
    required_code = {Path(__file__).resolve(), Path(_common_engine.__file__).resolve()}
    if not required_code.issubset(pinned_paths):
        raise ValueError("SESSION_BOUNDARY_OWNER_AND_ENGINE_CODE_PINS_REQUIRED")
    rows = population.get("rows")
    if not isinstance(rows, list) or not rows or population.get("original_unsupported_count") != len(rows):
        raise ValueError("SESSION_BOUNDARY_FULL_POPULATION_REQUIRED")
    eligible, seen = set(), set()
    for row in rows:
        key = _session_boundary_mechanism_key(row)
        if key is None or key in seen:
            raise ValueError("SESSION_BOUNDARY_POPULATION_KEY_INVALID_OR_DUPLICATED")
        seen.add(key)
        if row.get("disposition") != "SESSION_BOUNDARY_CONVENTION_ELIGIBLE":
            continue
        day = pd.Timestamp(key[1])
        candidates = row.get("dated_sid_candidates")
        if (not pd.Timestamp("2023-01-01") <= day < pd.Timestamp("2026-01-01") or
                row.get("date_only") is not True or
                row.get("independent_effective_clock_proven") is not False or
                row.get("coordinate") != "RAW_ACTUAL_SHARE" or
                type(row.get("dated_sid_count")) is not int or row["dated_sid_count"] != 1 or
                not isinstance(candidates, list) or len(candidates) != 1 or
                not isinstance(candidates[0], str) or not candidates[0] or
                key[2] not in rule.get("allowed_vendor_reasons", [])):
            raise ValueError("SESSION_BOUNDARY_ELIGIBLE_MECHANISM_NOT_DATE_ONLY_UNIQUE")
        eligible.add(key)
    if (not eligible or population.get("disposition_counts") != dict(Counter(r.get("disposition") for r in rows))):
        raise ValueError("SESSION_BOUNDARY_POPULATION_COUNTS_CHANGED")
    return dict(frozen, eligible_mechanism_keys=frozenset(eligible),
                population_row_count=len(rows), eligible_count=len(eligible), rule_definition=rule)


def _engine_with_entitlement_hook(hook, operational_exit_hook=None):
    source = Path(_common_engine.__file__).read_bytes()
    if hashlib.sha256(source).hexdigest() != ENTITLEMENT_ENGINE_SHA256:
        raise ValueError("ENTITLEMENT_IMMUTABLE_ENGINE_SOURCE_CHANGED")
    tree = ast.parse(source.decode("utf-8-sig"))
    original = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_many")
    node = copy.deepcopy(original)
    loop = next(n for n in node.body if isinstance(n, ast.For)
                and ast.unparse(n.target) == "(di, date)")
    loop.body.insert(0, ast.parse(
        "units, cash, entitlement_receivable = _entitlement_open_hook(di, date, units, cash)").body[0])
    expected = {
        "pre_nav": "cash + np.sum(np.where(held, units * np.where(_positive(opening), opening, 0.0), 0.0), axis=1)",
        "open_after": "cash + np.sum(np.where(held, units * np.where(_positive(opening), opening, 0.0), 0.0), axis=1)",
        "nav": "cash + values.sum(axis=1)",
        "nav_error": "np.where(_positive(nav), nav - cash - values.sum(axis=1), np.nan)",
    }
    seen = set()
    for statement in loop.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if not isinstance(target, ast.Name) or target.id not in expected:
            continue
        name = target.id
        wanted = ast.parse(expected[name], mode="eval").body
        if ast.dump(statement.value) != ast.dump(wanted) or name in seen:
            raise ValueError("ENTITLEMENT_ENGINE_AST_ANCHOR_CHANGED:" + name)
        if name == "nav_error":
            statement.value.args[1] = ast.BinOp(statement.value.args[1], ast.Sub(), ast.Name("entitlement_receivable", ast.Load()))
        else:
            statement.value = ast.BinOp(statement.value, ast.Add(), ast.Name("entitlement_receivable", ast.Load()))
        seen.add(name)
    if seen != set(expected):
        raise ValueError("ENTITLEMENT_ENGINE_AST_ANCHOR_MISSING")
    if operational_exit_hook is not None:
        matches = []
        for parent in ast.walk(node):
            for value in vars(parent).values():
                if isinstance(value, list):
                    for index, statement in enumerate(value):
                        if (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                                and isinstance(statement.targets[0], ast.Name)
                                and statement.targets[0].id == "op_mask"):
                            matches.append((value, index, statement))
        expected_op = ast.parse("op_mask=np.broadcast_to(op_shared,(s,n))").body[0]
        if len(matches) != 1 or ast.dump(matches[0][2]) != ast.dump(expected_op):
            raise ValueError("STOCK_DISTRIBUTION_OPERATIONAL_AST_ANCHOR_CHANGED")
        statements, index, _ = matches[0]
        statements[index+1:index+1] = ast.parse("""
stock_exit_mask = np.asarray(_entitlement_operational_exit_hook(di, date, units))
if stock_exit_mask.dtype.kind != 'b' or stock_exit_mask.shape != units.shape:
    raise ValueError('STOCK_DISTRIBUTION_OPERATIONAL_MASK_SHAPE_AND_BOOL_REQUIRED')
op_mask = op_mask | stock_exit_mask
""").body
    projected = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    namespace = dict(vars(_common_engine), _entitlement_open_hook=hook,
        _entitlement_operational_exit_hook=operational_exit_hook)
    exec(compile(projected, _common_engine.__file__, "exec"), namespace)
    lineage = dict(engine_source_sha256=ENTITLEMENT_ENGINE_SHA256,
        original_function_ast_sha256=hashlib.sha256(ast.dump(original).encode()).hexdigest(),
        projected_function_ast_sha256=hashlib.sha256(ast.dump(node).encode()).hexdigest(),
        ast_edits=["one pre-execution lifecycle hook", "receivable added to pre_nav/open_after/nav",
                   "receivable subtracted from NAV identity error"],
        execution_algorithm="original run_many; unchanged orders/cash scaling/fills/constraints")
    if operational_exit_hook is not None:
        lineage["ast_edits"].append("source-backed current delivered-stock operational mask before reservation/decision/pending")
    return namespace["run_many"], lineage


def _entitlement_identity_chains(events, security_tickers, corporate_actions=(), known_at=None):
    """Prove duplicate ticker aliases from the existing dated share-transition source.

    The catalogue and lifecycle binding stay fixed. Only the nonzero position SID
    changes at the proven session boundary; old receivable claims never migrate.
    """
    aliases = {}
    for sid, ticker in security_tickers.items():
        aliases.setdefault(ticker, set()).add(sid)
    aliases = {ticker: sids for ticker, sids in aliases.items() if len(sids) > 1}
    if not aliases:
        return {}
    corporate_actions = tuple(corporate_actions)
    if any(not isinstance(e, CorporateActionTransition) for e in corporate_actions):
        raise ValueError("ENTITLEMENT_ALIAS_TYPED_TRANSITION_REQUIRED")
    known_at = known_at or {}
    chains = {}
    for ticker, sids in aliases.items():
        chain = sorted((e for e in corporate_actions if e.old_security_id != e.new_security_id
                        and (e.old_ticker == ticker or e.new_ticker == ticker
                             or e.old_security_id in sids or e.new_security_id in sids)),
                       key=lambda e: (e.effective_date, e.old_security_id))
        if len(chain) != len(sids) - 1:
            raise ValueError("ENTITLEMENT_SECURITY_TICKER_BINDING_AMBIGUOUS")
        visited = {chain[0].old_security_id}
        previous_day = None
        previous_sid = chain[0].old_security_id
        for transition in chain:
            day = pd.Timestamp(transition.effective_date)
            if day.tzinfo is not None or day != day.normalize():
                raise ValueError("ENTITLEMENT_ALIAS_SESSION_DATE_REQUIRED")
            open_at = (day + pd.Timedelta(hours=9, minutes=30)).tz_localize("America/New_York").tz_convert("UTC")
            available = pd.Timestamp(known_at.get(transition.event_fingerprint, pd.NaT))
            if not (transition.old_ticker == transition.new_ticker == ticker
                    and transition.old_security_id in sids and transition.new_security_id in sids
                    and transition.cash_component_per_old_share == 0
                    and transition.quantity_multiplier > 0 and transition.repair_authorized
                    and transition.source_reference and transition.source_fingerprint
                    and not pd.isna(available) and available.tzinfo is not None and available <= open_at):
                raise ValueError("ENTITLEMENT_ALIAS_SOURCE_BACKED_SHARE_TRANSITION_REQUIRED")
            if (transition.old_security_id != previous_sid or transition.new_security_id in visited
                    or (previous_day is not None and day <= previous_day)):
                raise ValueError("ENTITLEMENT_ALIAS_LINEAR_FORWARD_CHAIN_REQUIRED")
            visited.add(transition.new_security_id)
            previous_sid, previous_day = transition.new_security_id, day
        if visited != sids:
            raise ValueError("ENTITLEMENT_ALIAS_LINEAR_FORWARD_CHAIN_REQUIRED")
        chains[ticker] = tuple(chain)
        # Same-SID share actions cannot revive a retired alias or name a future one.
        for transition in corporate_actions:
            if transition.old_security_id != transition.new_security_id:
                continue
            if (transition.old_ticker == ticker or transition.new_ticker == ticker
                    or transition.old_security_id in sids):
                day = pd.Timestamp(transition.effective_date)
                if (transition.old_ticker != ticker or transition.new_ticker != ticker
                        or any(day == pd.Timestamp(e.effective_date) for e in chain)
                        or transition.old_security_id != _entitlement_active_sid(chain, day)):
                    raise ValueError("ENTITLEMENT_SHARE_ACTION_DATED_SECURITY_IDENTITY_MISMATCH")
        for event in events:
            if event.ticker != ticker:
                continue
            day = _entitlement_effective_day(event)
            if any(day == pd.Timestamp(e.effective_date) for e in chain):
                raise ValueError("ENTITLEMENT_ALIAS_SAME_SESSION_ENTITLEMENT_PRIORITY_UNSUPPORTED")
            if event.old_security_id != _entitlement_active_sid(chain, day):
                raise ValueError("ENTITLEMENT_EVENT_DATED_SECURITY_IDENTITY_MISMATCH")
            if isinstance(event, SourceBackedTerminalEvent) and day < pd.Timestamp(chain[-1].effective_date):
                raise ValueError("ENTITLEMENT_ALIAS_TRANSITION_AFTER_TERMINAL_UNSUPPORTED")
    return chains


def _entitlement_active_sid(chain, day):
    sid = chain[0].old_security_id
    for transition in chain:
        if day < pd.Timestamp(transition.effective_date):
            break
        sid = transition.new_security_id
    return sid


def _entitlement_binding(events, security_tickers, binding, *, corporate_actions=(), corporate_action_known_at=None):
    if not isinstance(binding, dict) or binding.get("status") != "SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND":
        raise ValueError("ENTITLEMENT_SOURCE_COVERAGE_BINDING_REQUIRED")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(binding.get("source_fingerprint", ""))):
        raise ValueError("ENTITLEMENT_COVERAGE_SOURCE_SHA256_REQUIRED")
    if binding.get("quantity_coordinate") != RAW_OLD_SHARE_COORDINATE:
        raise ValueError("ENTITLEMENT_COVERAGE_QUANTITY_COORDINATE_MISMATCH")
    if any(not isinstance(e, (SourceBackedEntitlementEvent, SourceBackedTerminalEvent, SourceBackedStockDistributionEvent)) for e in events):
        raise ValueError("ENTITLEMENT_EVENT_TYPE_REQUIRED")
    fingerprints = [e.event_fingerprint for e in events]
    if len(set(fingerprints)) != len(fingerprints) or sorted(binding.get("event_fingerprints", [])) != sorted(fingerprints):
        raise ValueError("ENTITLEMENT_COVERAGE_EVENT_CATALOGUE_MISMATCH")
    if binding.get("security_tickers") != security_tickers:
        raise ValueError("ENTITLEMENT_COVERAGE_SECURITY_BINDING_MISMATCH")
    _entitlement_identity_chains(events, security_tickers, corporate_actions, corporate_action_known_at)
    terminal_sids = [e.old_security_id for e in events if isinstance(e, SourceBackedTerminalEvent)]
    if len(set(terminal_sids)) != len(terminal_sids):
        raise ValueError("DUPLICATE_TERMINAL_SECURITY_IDENTITY")
    for event in events:
        if security_tickers.get(event.old_security_id) != event.ticker:
            raise ValueError("ENTITLEMENT_EVENT_SECURITY_TICKER_MISMATCH")
        if isinstance(event, SourceBackedStockDistributionEvent) and security_tickers.get(event.child_security_id) != event.child_ticker:
            raise ValueError("STOCK_DISTRIBUTION_CHILD_SECURITY_TICKER_BINDING_REQUIRED")
    return copy.deepcopy(binding)


def _execution_friction(contract):
    if contract is None:
        return 0., None
    if not isinstance(contract, dict) or contract.get("kind") != "FIXED_ADVERSE_OPEN_SLIPPAGE":
        raise ValueError("EXPLICIT_RESEARCH_SLIPPAGE_CONTRACT_REQUIRED")
    bps = contract.get("one_way_bps")
    if (isinstance(bps, bool) or bps not in (0, 5, 10, 20)
        or contract.get("fee_bps") != 0
        or contract.get("benchmark") != "NEXT_RAW_OPEN"
        or contract.get("authority") != "HYPOTHETICAL_RESEARCH_SCENARIO"
        or not isinstance(contract.get("scenario_id"), str) or not contract["scenario_id"].strip()):
        raise ValueError("INVALID_FROZEN_RESEARCH_SLIPPAGE_SCENARIO")
    return float(bps), copy.deepcopy(contract)


def account_prefix_identity(replay, end, path_ids=None):
    end = pd.Timestamp(end)
    digest = hashlib.sha256()
    counts = {}
    wanted=None if path_ids is None else tuple(str(p) for p in path_ids)
    if wanted is not None and (not wanted or not set(wanted).issubset(replay.metadata['path_ids'])):
        raise ValueError('prefix path identity mismatch')
    tables = [
        ("daily", "date", ["date", "path_id"]),
        ("positions", "date", ["date", "path_id", "ticker"]),
        ("fills", "execution_date", ["execution_date", "path_id", "ticker", "side"]),
    ]
    if replay.metadata.get("entitlement_lifecycle_enabled", False):
        tables.append(("entitlements", "session", ["session", "path_id", "event_id", "phase"]))
    for name, clock, keys in tables:
        frame = getattr(replay, name)
        if wanted is not None:
            frame = frame.loc[frame.path_id.isin(wanted)]
        frame = frame.loc[pd.to_datetime(frame[clock]).le(end)].sort_values(keys,kind="stable").copy()
        semantic_columns = {
            "daily": ["path_id","date","cash","nav","certified_nav","gross_exposure","transaction_cost_amount","buy_notional","sell_notional","turnover","accounting_qualified"],
            "positions": ["path_id","date","ticker","index_units","mark","market_value","weight","holding_age","entry_date","entry_price","entry_execution_open","quantity_coordinate_factor","stale","unknown","accounting_qualified"],
            "fills": ["path_id","signal_date","execution_date","order_id","ticker","side","action","price","notional","index_units","index_units_before","index_units_after","transaction_cost","quantity_coordinate_factor"],
        }
        if name == "entitlements":
            semantic_columns[name] = ["path_id", "session", "event_id", "event_fingerprint", "old_security_id", "ticker", "phase", "ex_date", "record_date", "pay_date", "entitled_raw_shares", "amount_usd", "spendable_cash_delta", "source_fingerprint", "reason"]
            if "action_type" in frame and frame.action_type.eq("MERGER_CASH_CONVERSION").any():
                semantic_columns[name] += TERMINAL_LEDGER_COLUMNS
        elif name == "daily" and replay.metadata.get("entitlement_lifecycle_enabled", False):
            semantic_columns[name] += ["receivable_value_usd", "entitlement_cash_flow_usd"]
        frame = frame.reindex(columns=semantic_columns[name])
        for col in frame.select_dtypes(include=["float"]).columns:
            frame[col] = frame[col].round(10)
        digest.update(name.encode())
        digest.update(frame.to_csv(index=False,float_format="%.10f",na_rep="NA").encode())
        counts[name] = len(frame)
    return {"end_session": str(end.date()), "sha256": digest.hexdigest(),
            "row_counts": counts, "comparison_precision_decimals": 10}

def run_continuous_account(
    market: MarketArrays, path_ids, policy, account_config: dict, *,
    corporate_actions=(), corporate_action_known_at=None, unsupported_events=(),
    previous_prefix=None, locked_evaluation_receipt=None, ledger_callback=None,
    entitlement_enabled=False, entitlement_events=(), entitlement_security_tickers=None,
    entitlement_source_binding=None, execution_friction=None, research_account_authority=None,
    research_quote_domain=None, research_ca_accounting_convention=None,
    descriptive_evaluation_authority=None, foreign_fx_marks=(), foreign_conversion_friction_bps=None,
):
    """One fractional account per path across every supplied session.

    policy(local_session_index, PersistentPolicyContext) returns TargetDecision.
    Same-ticker, zero-cash source-backed share transforms reuse the common
    corporate-action transition function. Other events fail closed per ticker.
    Event availability and source coverage receipts are bound by the caller.
    """
    descriptive_authority = None
    if descriptive_evaluation_authority is not None:
        # Separate explicit user-named evaluation, never a fabricated finalist.
        # The old reconstructed-event and quote conventions stay pre-2026.
        if any(value is not None for value in (previous_prefix, locked_evaluation_receipt,
                research_account_authority, research_quote_domain, research_ca_accounting_convention)):
            raise ValueError("DESCRIPTIVE_FRESH_SCOPE_CANNOT_INHERIT_LEGACY_AUTHORITY")
        from scripts.research.a2.evaluation.frozen_test_authority import validate_descriptive_account
        path_ids = tuple(path_ids)
        descriptive_authority = validate_descriptive_account(
            descriptive_evaluation_authority, market.dates, path_ids, account_config, execution_friction)
    if (account_config.get("base_currency") != "USD"
        or account_config.get("fractional_shares") is not True
        or account_config.get("integer_share_rounding",False) is not False
        or account_config.get("cash_interest") != 0
        or account_config.get("transaction_cost_bps") != 0
        or account_config.get("financing") is not False
        or account_config.get("borrowed_cash",False) is not False
        or account_config.get("long_only") is not True):
        raise ValueError("R1 requires fractional USD, zero cost/interest, unfinanced long-only")
    slippage_bps, friction_contract = _execution_friction(execution_friction)
    entitlement_events = tuple(entitlement_events)
    foreign_events = tuple(e for e in entitlement_events if isinstance(e, SourceBackedForeignCashEvent))
    foreign_fx_marks = tuple(foreign_fx_marks)
    if foreign_events:
        if (entitlement_enabled is not True or market.dates[-1] >= pd.Timestamp("2026-01-01")
                or descriptive_authority is not None or foreign_conversion_friction_bps != 25.
                or any(not isinstance(m, SourceBackedFXMark) for m in foreign_fx_marks)):
            raise ValueError("SOURCE_QUALIFIED_PRE2026_CAD_RESEARCH_AND_FX_MARKS_REQUIRED")
    elif foreign_fx_marks or foreign_conversion_friction_bps is not None:
        raise ValueError("UNUSED_FOREIGN_FX_INPUTS_FOR_USD_ONLY_ACCOUNT")
    reconstructed_cash = tuple(e for e in entitlement_events if isinstance(e, ResearchReconstructedCashEvent))
    reconstructed_terminal = tuple(e for e in entitlement_events if isinstance(e, ResearchPostVerifiedTerminalEvent))
    post_verified = reconstructed_cash + reconstructed_terminal
    full_selector_scope = (isinstance(research_account_authority, dict)
        and research_account_authority.get("schema") == "C_FULL_SELECTOR_FIXED_POLICY_ACCOUNT_AUTHORITY_V1")
    research_authority = None
    if full_selector_scope:
        research_authority = _validate_research_account_authority(entitlement_events, research_account_authority)
        if (market.dates[0] < pd.Timestamp("2023-01-01")
                or market.dates[-1] >= pd.Timestamp("2026-01-01")
                or previous_prefix is not None or locked_evaluation_receipt is not None
                or descriptive_authority is not None or entitlement_enabled is not True):
            raise ValueError("FULL_SELECTOR_ACCOUNT_FRESH_PRE2026_SCOPE_REQUIRED")
    if (post_verified and not full_selector_scope) or (descriptive_authority is not None and (
            descriptive_authority.research_cash_reconstruction_json != "{}"
            or descriptive_authority.research_terminal_reconstruction_json != "{}")):
        from scripts.research.a2.evaluation.frozen_test_authority import validate_reconstructed_accounting_events
        validate_reconstructed_accounting_events(descriptive_authority, entitlement_events, require_exact=True)
    if not full_selector_scope:
        research_authority = _validate_research_account_authority(entitlement_events, research_account_authority)
    security_tickers = dict(entitlement_security_tickers or {})
    corporate_actions = tuple(corporate_actions)
    entitlement_binding = (_entitlement_binding(entitlement_events, security_tickers, entitlement_source_binding,
        corporate_actions=corporate_actions, corporate_action_known_at=corporate_action_known_at)
        if entitlement_enabled is True else None)
    identity_chains = (_entitlement_identity_chains(entitlement_events, security_tickers,
        corporate_actions, corporate_action_known_at) if entitlement_enabled is True else {})
    if entitlement_enabled is not True and (entitlement_events or security_tickers or entitlement_source_binding is not None):
        raise ValueError("ENTITLEMENT_INPUTS_REQUIRE_EXPLICIT_OPT_IN")
    if not isinstance(entitlement_enabled, bool):
        raise ValueError("ENTITLEMENT_OPT_IN_MUST_BE_BOOL")
    ca_convention = None
    if research_ca_accounting_convention is not None:
        if research_authority is None or entitlement_enabled is not True:
            raise ValueError("SESSION_BOUNDARY_REQUIRES_RESEARCH_AUTHORITY_AND_ENTITLEMENT_HOOK")
        if market.dates[-1] >= pd.Timestamp("2026-01-01"):
            raise ValueError("SESSION_BOUNDARY_PRE2026_ONLY")
        ca_convention = load_research_ca_accounting_convention(research_ca_accounting_convention)
    capital = account_config["initial_nav"]
    if not np.isfinite(capital) or capital <= 0 or account_config.get("initial_cash",capital) != capital or account_config.get("initial_holdings",[]) != []:
        raise ValueError("new common account must start empty with task-config capital")
    if market.dates[0] < pd.Timestamp("2023-01-01"):
        raise ValueError("common initial state begins at the first legal 2023 execution point")
    if market.dates[-1] >= pd.Timestamp("2026-01-01") and descriptive_authority is None:
        if not locked_evaluation_receipt or locked_evaluation_receipt.get("status") != "FINALIST_FROZEN" or len(str(locked_evaluation_receipt.get("sha256",""))) != 64 or previous_prefix is None:
            raise ValueError("locked 2026 replay requires finalist freeze and pre-2026 prefix receipt")
        if market.dates[-1] >= pd.Timestamp("2027-01-01"):
            raise ValueError("test replay is restricted to 2026")
    ids = tuple(str(p) for p in path_ids)
    n, s = len(market.tickers), len(ids)
    ti = {str(t): i for i,t in enumerate(market.tickers)}
    di = {d: i for i,d in enumerate(market.dates)}
    factors = np.ones((len(market.dates),n))
    event_receipts = []
    known_at = corporate_action_known_at or {}
    exceptions = list(unsupported_events)
    CorporateActionTransitionAdapter(corporate_actions)  # Same source duplicate-event guard.
    for event in sorted(corporate_actions,key=lambda e:(e.effective_date,e.old_security_id)):
        day = pd.Timestamp(event.effective_date)
        if day > market.dates[-1] or event.old_ticker not in ti or day < market.dates[0]:
            continue
        open_at = (day+pd.Timedelta(hours=9,minutes=30)).tz_localize("America/New_York").tz_convert("UTC")
        available = pd.Timestamp(known_at.get(event.event_fingerprint,pd.NaT))
        supported = (event.old_ticker == event.new_ticker and event.cash_component_per_old_share == 0
                     and event.quantity_multiplier > 0 and event.repair_authorized
                     and bool(event.source_reference) and bool(event.source_fingerprint)
                     and not pd.isna(available) and available.tzinfo is not None and available <= open_at)
        if not supported:
            exceptions.append({"ticker":event.old_ticker,"effective_date":str(day.date()),
                               "reason":"UNSUPPORTED_OR_UNAVAILABLE_CORPORATE_ACTION",
                               "source_reference":event.source_reference,
                               "source_fingerprint":event.source_fingerprint})
            continue
        converted,cash,record = apply_transition_to_positions(event,{event.old_ticker:1.},0.,day)
        if cash != 0 or set(converted) != {event.old_ticker}:
            raise ValueError("share-only coordinate transform cannot alter cash or ticker")
        multiplier = converted[event.old_ticker]
        factors[market.dates >= day,ti[event.old_ticker]] *= multiplier
        event_receipts.append({**record,"known_at":str(available),"research_coordinate_multiplier":multiplier})
    quality = market.quality.copy()
    inherited_event_quality = np.zeros_like(quality) if research_quote_domain is not None else None
    exception_by_ticker = {}
    for event in exceptions:
        if str(event["ticker"]) not in ti:
            continue
        day = pd.Timestamp(event["effective_date"])
        if day > market.dates[-1]:
            continue
        c = ti[str(event["ticker"])]
        quality[market.dates == day,c] = True
        if inherited_event_quality is not None:
            inherited_event_quality[market.dates == day,c] = True
        exception_by_ticker.setdefault(c,[]).append(event)
    if research_quote_domain is not None:
        # Independent research quote admission cannot waive corporate-action accounting.
        # Keep every exception and accounting lifecycle; only the inherited mask changes.
        if research_authority is None:
            raise ValueError("RESEARCH_QUOTE_DOMAIN_REQUIRES_RESEARCH_ACCOUNT_AUTHORITY")
        from scripts.research.a2.training.stateful_research_quote_domain import load_frozen_domain, apply_quote_domain
        domain = load_frozen_domain(research_quote_domain)
        quality, quote_domain_audit = apply_quote_domain(
            market.quality, inherited_event_quality, market.dates, market.tickers, domain["decisions"])
    terminal_events = tuple(e for e in entitlement_events if isinstance(e, SourceBackedTerminalEvent))
    stock_events = tuple(e for e in entitlement_events if isinstance(e, SourceBackedStockDistributionEvent))
    if stock_events and (market.dates[-1] >= pd.Timestamp("2026-01-01") or descriptive_authority is not None):
        raise ValueError("STOCK_DISTRIBUTION_PRE2026_RESEARCH_ONLY")
    for event in stock_events:
        if event.child_ticker not in ti:
            raise ValueError("STOCK_DISTRIBUTION_CHILD_RAW_MARKET_COLUMN_REQUIRED")
        if market.dates[0] <= _entitlement_effective_day(event) <= market.dates[-1] and _entitlement_effective_day(event) not in di:
            raise ValueError("STOCK_DISTRIBUTION_EX_SESSION_REQUIRED")

    terminal_closed = np.zeros_like(market.row_present, dtype=bool)
    for event in terminal_events:
        day = _entitlement_effective_day(event)
        if event.ticker in ti:
            if market.dates[0] <= day <= market.dates[-1] and day not in di:
                raise ValueError("TERMINAL_EFFECTIVE_SESSION_MISSING")
            if any(pd.Timestamp(ca.effective_date) == day and ca.old_ticker == event.ticker
                   for ca in corporate_actions):
                raise ValueError("TERMINAL_SAME_SESSION_SHARE_TRANSFORM_PRIORITY_UNSUPPORTED")
            terminal_closed[market.dates >= day, ti[event.ticker]] = True
    # Extinguished securities have no executable quote domain. Keep caller raw
    # prices/quality intact; the old mark can never value a zero share position.
    common_market = replace(market,open=market.open*factors,close=market.close*factors,
                            row_present=market.row_present & ~terminal_closed,
                            new_buy_eligible=market.new_buy_eligible & ~terminal_closed,
                            quality=quality,initial_marks=market.initial_marks.copy())
    entry_index = np.full((s,n),-1,dtype=int)
    entry_date = np.full((s,n),np.datetime64("NaT","ns"),dtype="datetime64[ns]")
    entry_price = np.full((s,n),np.nan)
    entry_factor = np.ones((s,n))
    current_units = np.zeros((s,n))
    enriched = {}
    accounting_exceptions = []
    reported_exceptions = set()
    boundary_processed = set() if ca_convention is not None else None
    boundary_rows = [] if ca_convention is not None else None
    invalid_paths = np.zeros(s,dtype=bool)
    terminal_settlement_missing = np.zeros(s,dtype=bool)
    entitlement_states = [EntitlementLifecycleState() for _ in ids]
    entitlement_rows = []
    entitlement_receivable = np.zeros(s)
    entitlement_cash_flow = np.zeros(s)
    fx_conversion_fees = np.zeros(s)
    foreign_claims_cad = np.zeros(s)
    previous_daily_cash = np.full(s, capital, dtype=float)
    actual_cash_error_max = 0.
    engine_lineage = None
    active_entitlements = tuple(e for e in entitlement_events if _entitlement_effective_day(e) >= market.dates[0])
    entitlement_lookup = {e.event_id: e for e in active_entitlements}
    unsupported_by_day = {}
    for c, events in exception_by_ticker.items():
        for event in events:
            unsupported_by_day.setdefault(pd.Timestamp(event["effective_date"]), []).append((c, event))
    path_index = {p:i for i,p in enumerate(ids)}
    def lifecycle_hook(j, date, units, cash):
        # Initial accounts are empty, so historical ex dates cannot confer claims.
        before_factors = factors[j-1] if j else np.ones(n)
        updated_units, updated_cash = units.copy(), cash.copy()
        entitlement_cash_flow[:] = 0.
        fx_conversion_fees[:] = 0.
        open_at = (date + pd.Timedelta(hours=9, minutes=30)).tz_localize("America/New_York").tz_convert("UTC")
        for r in range(s):
            for c, event in unsupported_by_day.get(date, ()):
                if ca_convention is not None:
                    mechanism = _session_boundary_mechanism_key(event)
                    token = (r, mechanism)
                    if mechanism in ca_convention["eligible_mechanism_keys"] and token not in boundary_processed:
                        engine_units = float(units[r, c])
                        prior_factor = float(before_factors[c])
                        if not np.isfinite(engine_units) or engine_units < -TOL or not np.isfinite(prior_factor) or prior_factor <= 0:
                            raise ValueError("SESSION_BOUNDARY_PRE_OPEN_QUANTITY_INVALID")
                        boundary_rows.append(dict(path_id=ids[r],
                            **{k: event[k] for k in _SESSION_BOUNDARY_KEY},
                            accounting_boundary_at=str(open_at),
                            pre_open_engine_units=engine_units,
                            prior_session_quantity_factor=prior_factor,
                            pre_open_raw_shares=engine_units * prior_factor,
                            disposition=("ACCOUNTING_BLOCKED" if engine_units > TOL else
                                         "NOT_APPLICABLE_TO_THIS_ACCOUNT_PREFIX"),
                            clock_role="RESEARCH_SESSION_BOUNDARY_ACCOUNTING_CONVENTION"))
                        boundary_processed.add(token)
                key = (r, c, str(event["effective_date"]))
                if units[r, c] > TOL and key not in reported_exceptions:
                    accounting_exceptions.append({"path_id": ids[r], **event,
                        "first_affected_session": str(date.date()), "nav_valid": False})
                    reported_exceptions.add(key)
                    invalid_paths[r] = True
            positions = {sid: float(units[r, ti[ticker]] * before_factors[ti[ticker]])
                         for sid, ticker in security_tickers.items() if ticker in ti}
            for ticker, chain in identity_chains.items():
                if ticker not in ti:
                    continue
                active_sid = _entitlement_active_sid(chain, date)
                # The new SID denotes post-transition RAW shares. Same-day ex or
                # terminal events are rejected above; old claim payments use no quantity.
                transition_today = any(date == pd.Timestamp(e.effective_date) for e in chain)
                factor = factors[j, ti[ticker]] if transition_today else before_factors[ti[ticker]]
                for sid, bound_ticker in security_tickers.items():
                    if bound_ticker == ticker:
                        positions[sid] = float(units[r, ti[ticker]] * factor) if sid == active_sid else 0.
            applied = apply_entitlement_lifecycle(active_entitlements, positions, float(cash[r]),
                execution_date=date, session_open_at=open_at, security_tickers=security_tickers,
                quantity_coordinate=RAW_OLD_SHARE_COORDINATE, state=entitlement_states[r], enabled=True,
                research_account_authority=research_authority,
                descriptive_accounting_authority=descriptive_authority if post_verified else None,
                stock_delivery_quote_qualified={e.child_security_id: bool(
                    market.row_present[j, ti[e.child_ticker]] and not quality[j, ti[e.child_ticker]]
                    and np.isfinite(market.open[j, ti[e.child_ticker]]) and market.open[j, ti[e.child_ticker]] > 0)
                    for e in stock_events},
                foreign_fx_mark=select_foreign_fx_mark(foreign_fx_marks, as_of=open_at) if foreign_events else None,
                foreign_conversion_friction_bps=foreign_conversion_friction_bps)
            extinguished_sids = {e.old_security_id for e in terminal_events
                if _entitlement_effective_day(e) <= date and e.ticker in ti}
            expected_positions = {**positions, **{sid: 0. for sid in extinguished_sids}}
            stock_deliveries = tuple(row for row in applied.records if row["phase"] == "STOCK_DISTRIBUTION_DELIVERED")
            for row in stock_deliveries:
                sid = row["child_security_id"]
                event = entitlement_lookup[row["event_id"]]
                if not isinstance(event, SourceBackedStockDistributionEvent) or sid != event.child_security_id:
                    raise ValueError("STOCK_DISTRIBUTION_DELIVERY_RECORD_IDENTITY_CHANGED")
                expected_positions[sid] = expected_positions.get(sid, 0.) + row["child_units"]
            if applied.positions != expected_positions:
                raise ValueError("ENTITLEMENT_HOOK_SHARE_CHANGE_REQUIRES_TYPED_TERMINAL_OR_STOCK_EVENT")
            for row in stock_deliveries:
                c = ti[row["child_ticker"]]
                if not np.isfinite(factors[j, c]) or factors[j, c] <= 0:
                    raise ValueError("STOCK_DISTRIBUTION_CHILD_RAW_QUANTITY_FACTOR_REQUIRED")
                updated_units[r, c] = applied.positions[row["child_security_id"]] / factors[j, c]
                if units[r, c] <= TOL:
                    entry_index[r, c] = j
                    entry_date[r, c] = date.to_datetime64()
                    entry_price[r, c] = market.open[j, c]
                    entry_factor[r, c] = factors[j, c]

            for sid in extinguished_sids:
                c = ti[security_tickers[sid]]
                event = next(e for e in terminal_events if e.old_security_id == sid)
                if (dict(applied.state.ex_quantities).get(event.event_id, 0.) * event.cash_per_old_share > 0
                        and event.settlement is None):
                    terminal_settlement_missing[r] = True
                updated_units[r, c] = 0.
                entry_index[r, c] = -1
                entry_date[r, c] = np.datetime64("NaT", "ns")
                entry_price[r, c] = np.nan
                entry_factor[r, c] = 1.
            entitlement_states[r] = applied.state
            updated_cash[r] = applied.cash
            entitlement_cash_flow[r] = applied.cash - cash[r]
            entitlement_receivable[r] = applied.receivable_value_usd
            fx_conversion_fees[r] = applied.fx_conversion_fee_usd
            foreign_claims_cad[r] = sum(c.amount_foreign for c in applied.state.foreign_cash_receivables)
            invalid_paths[r] |= not applied.accounting_qualified
            current_units[r] = updated_units[r]
            for record in applied.records:
                event = entitlement_lookup[record["event_id"]]
                is_terminal = isinstance(event, SourceBackedTerminalEvent)
                row = {"path_id": ids[r], **record,
                       "ex_date": None if is_terminal else event.ex_date,
                       "record_date": None if is_terminal else event.record_date,
                       "pay_date": (_entitlement_pay_date(event) if not is_terminal or (event.settlement is not None
                           and pd.Timestamp(event.settlement.available_at) <= open_at) else None)}
                if isinstance(event, SourceBackedForeignCashEvent):
                    row.update(currency=event.currency, amount_unit=event.amount_unit,
                        actual_broker_fx_payment_fee_tax_certified=False)
                if isinstance(event, SourceBackedStockDistributionEvent):
                    row.update(action_type=event.action_type, child_security_id=event.child_security_id,
                        child_ticker=event.child_ticker, child_ratio_numerator=event.child_ratio_numerator,
                        child_ratio_denominator=event.child_ratio_denominator,
                        child_quantity_unit=event.child_quantity_unit, delivery_date=event.delivery_date,
                        regular_trading_date=event.regular_trading_date,
                        research_mode=event.research_mode, original_cash_in_lieu_terms=event.original_cash_in_lieu_terms,
                        actual_broker_fractional_delivery_certified=False)
                if is_terminal:
                    c = ti[event.ticker]
                    row.update(action_type=event.action_type, effective_date=event.effective_date,
                        effective_at=event.effective_at, effective_clock_basis=event.effective_clock_basis,
                        quantity_coordinate=event.quantity_coordinate,
                        quantity_source_reference=event.quantity_source_reference,
                        quantity_source_fingerprint=event.quantity_source_fingerprint,
                        cash_per_old_share=event.cash_per_old_share,currency=event.currency,amount_unit=event.amount_unit,
                        receivable_id="TERMINAL_RECEIVABLE:"+hashlib.sha256(
                            (ids[r]+"\0"+event.event_fingerprint+"\0"+event.old_security_id).encode()).hexdigest())
                    if event.settlement is not None and pd.Timestamp(event.settlement.available_at) <= open_at:
                        row["settlement_available_at"] = event.settlement.available_at
                    if date == _entitlement_effective_day(event):
                        row.update(pre_effective_engine_units=float(units[r, c]),
                            pre_effective_quantity_factor=float(before_factors[c]))
                entitlement_rows.append(row)
                if (record["phase"] == "BLOCKED_ACCOUNTING_ENTITLEMENT"
                        or (is_terminal and record["phase"] == "SETTLEMENT_PENDING_AUTHORITY"
                            and event.settlement is None and event.cash_per_old_share > 0)):
                    if is_terminal and event.settlement is None:
                        row = {**row, "reason": "TERMINAL_SETTLEMENT_AUTHORITY_MISSING"}
                    accounting_exceptions.append({**row, "effective_date": str(_entitlement_effective_day(event).date()),
                        "first_affected_session": str(date.date()), "nav_valid": False})
        if not np.isfinite(updated_cash).all() or not np.isfinite(entitlement_receivable).all() or (updated_cash < 0).any() or (entitlement_receivable < 0).any():
            raise AssertionError("ENTITLEMENT_CASH_OR_RECEIVABLE_INVALID")
        return updated_units, updated_cash, entitlement_receivable.copy()

    def callback(name,frame):
        nonlocal actual_cash_error_max
        out = frame.copy()
        if name == "fills":
            ii = np.asarray([di[pd.Timestamp(d)] for d in out.execution_date],int)
            cc = np.asarray([ti[str(t)] for t in out.ticker],int)
            scale = factors[ii,cc]
            for col in ["price","index_units","index_units_before","index_units_after"]:
                out["engine_"+col] = out[col]
            out["price"] = market.open[ii,cc]
            for col in ["index_units","index_units_before","index_units_after"]:
                out[col] *= scale
            out["fractional_shares"] = out.index_units
            out["quantity_coordinate_factor"] = scale
            if friction_contract is not None:
                direction = np.where(out.side.eq("BUY"), 1., -1.)
                out["raw_Open"] = out.price
                out["benchmark_notional"] = out.notional
                out["actual_fill_price"] = out.price * (1. + direction * slippage_bps / 10000.)
                out["slippage_amount"] = out.notional * slippage_bps / 10000.
                out["actual_fill_notional"] = out.notional + direction * out.slippage_amount
                out["transaction_fee"] = 0.
                if not np.allclose(out.actual_fill_price * out.index_units, out.actual_fill_notional, rtol=1e-12, atol=1e-8) or not np.allclose(out.transaction_cost, out.slippage_amount, rtol=1e-12, atol=1e-8):
                    raise AssertionError("SLIPPAGE_FILL_PRICE_QUANTITY_CASH_IDENTITY")
            if not np.allclose(out.price*out.index_units,out.notional,rtol=1e-12,atol=1e-8):
                raise AssertionError("raw Open/quantity/notional translation mismatch")
            for row,j,c in zip(out.itertuples(),ii,cc):
                r = path_index[str(row.path_id)]
                current_units[r,c] = row.engine_index_units_after
                if row.side == "BUY" and row.engine_index_units_before <= TOL:
                    entry_index[r,c] = j; entry_date[r,c] = market.dates[j].to_datetime64(); entry_price[r,c] = row.price;entry_factor[r,c] = factors[j,c]
                if row.side == "SELL" and row.engine_index_units_after <= TOL:
                    entry_index[r,c] = -1;entry_date[r,c] = np.datetime64("NaT","ns");entry_price[r,c] = np.nan
        elif name == "positions":
            ii = np.asarray([di[pd.Timestamp(d)] for d in out.date],int)
            cc = np.asarray([ti[str(t)] for t in out.ticker],int)
            rr = np.asarray([path_index[str(p)] for p in out.path_id],int)
            out["engine_index_units"] = out.index_units;out["engine_mark"] = out.mark
            out["index_units"] *= factors[ii,cc];out["mark"] /= factors[ii,cc]
            out["fractional_shares"] = out.index_units;out["quantity_coordinate_factor"] = factors[ii,cc]
            out["holding_age"] = ii-entry_index[rr,cc]
            out["entry_date"] = entry_date[rr,cc]
            out["entry_execution_open"] = entry_price[rr,cc]
            out["entry_price"] = entry_price[rr,cc]*entry_factor[rr,cc]/factors[ii,cc]
            out["accounting_qualified"] = ~(invalid_paths[rr] | terminal_settlement_missing[rr])
        elif name == "orders":
            jj = np.asarray([di[pd.Timestamp(d)] for d in out.signal_date],int)
            cc = np.asarray([ti[str(t)] for t in out.ticker],int)
            for col in ["current_units","hold_units"]:
                out["engine_"+col] = out[col];out[col] *= factors[jj,cc]
        elif name == "execution_results":
            scale=[factors[di[pd.Timestamp(date)],ti[str(ticker)]] if not pd.isna(date) else 1.
                   for date,ticker in zip(out.execution_date,out.ticker)]
            out["engine_index_units"] = out.index_units;out["index_units"] *= np.asarray(scale)
            if terminal_events:
                out["terminal_event_id"] = None
                out["terminal_cancellation_reason"] = None
                for event in terminal_events:
                    closed = out.ticker.eq(event.ticker) & pd.to_datetime(out.execution_date).ge(_entitlement_effective_day(event))
                    out.loc[closed,"terminal_event_id"] = event.event_id
                    out.loc[closed,"terminal_cancellation_reason"] = "SOURCE_BACKED_OLD_SECURITY_EXTINGUISHED"
        elif name == "daily":
            rr = np.asarray([path_index[str(p)] for p in out.path_id], int)
            if stock_events:
                j = di[pd.Timestamp(out.date.iloc[0])]
                stock_operational_mask(j, market.dates[j], current_units)
            if entitlement_enabled:
                out["receivable_value_usd"] = entitlement_receivable[rr]
                out["entitlement_cash_flow_usd"] = entitlement_cash_flow[rr]
                if foreign_events:
                    # All admissible releases are available only after that
                    # release-day close. Open and close see the identical mark.
                    day = pd.Timestamp(out.date.iloc[0])
                    opening = (day + pd.Timedelta(hours=9, minutes=30)).tz_localize("America/New_York")
                    closing = (day + pd.Timedelta(hours=16)).tz_localize("America/New_York")
                    if select_foreign_fx_mark(foreign_fx_marks, as_of=opening) != select_foreign_fx_mark(foreign_fx_marks, as_of=closing):
                        raise ValueError("FX_RELEASE_DATE_BOUND_MUST_NOT_CHANGE_WITHIN_ACCOUNT_SESSION")
                    out["foreign_cash_receivable_cad"] = foreign_claims_cad[rr]
                    out["fx_conversion_fee_usd"] = fx_conversion_fees[rr]
            if friction_contract is not None:
                out["actual_buy_notional"] = out.buy_notional * (1. + slippage_bps / 10000.)
                out["actual_sell_notional"] = out.sell_notional * (1. - slippage_bps / 10000.)
                out["slippage_amount"] = (out.buy_notional + out.sell_notional) * slippage_bps / 10000.
                out["transaction_fee"] = 0.
            if entitlement_enabled or friction_contract is not None:
                actual_buys = out.buy_notional.to_numpy(float) * (1. + slippage_bps / 10000.)
                actual_sells = out.sell_notional.to_numpy(float) * (1. - slippage_bps / 10000.)
                paid = entitlement_cash_flow[rr] if entitlement_enabled else np.zeros(len(rr))
                error = out.cash.to_numpy(float) - previous_daily_cash[rr] - paid - actual_sells + actual_buys
                out["actual_cash_flow_identity_error"] = error
                actual_cash_error_max = max(actual_cash_error_max, float(np.max(np.abs(error))))
                if not np.allclose(error, 0., atol=1e-8, rtol=0.):
                    raise AssertionError("ACTUAL_CASH_FLOW_IDENTITY_WITH_ENTITLEMENT_AND_SLIPPAGE")
                previous_daily_cash[rr] = out.cash.to_numpy(float)
            for row in out.itertuples():
                r = path_index[str(row.path_id)]
                for c,events in exception_by_ticker.items():
                    for event in events:
                        key = (r,c,str(event["effective_date"]))
                        if pd.Timestamp(event["effective_date"]) == row.date and current_units[r,c] > TOL and key not in reported_exceptions:
                            if ca_convention is not None:
                                mechanism = _session_boundary_mechanism_key(event)
                                if mechanism in ca_convention["eligible_mechanism_keys"]:
                                    if (r, mechanism) not in boundary_processed:
                                        raise ValueError("SESSION_BOUNDARY_PRE_OPEN_HOOK_NOT_PROCESSED")
                                    continue
                            accounting_exceptions.append({"path_id":ids[r],**event,
                                "first_affected_session":str(row.date.date()),"nav_valid":False})
                            reported_exceptions.add(key)
                            invalid_paths[r] = True
            rr = np.asarray([path_index[str(p)] for p in out.path_id],int)
            out["engine_certified_nav"] = out.certified_nav
            unqualified = invalid_paths[rr] | terminal_settlement_missing[rr]
            out["accounting_qualified"] = ~unqualified
            out.loc[unqualified,"certified_nav"] = np.nan
            out.loc[unqualified,"net_return"] = np.nan
            if research_authority is not None:
                out["TOTAL_ECONOMIC_NAV"] = out.nav
                out["LIQUID_NAV"] = out.nav - entitlement_receivable[rr]
                out["research_accounting_qualified"] = ~invalid_paths[rr]
        if name in {"daily","fills","positions","orders","execution_results"}:
            enriched.setdefault(name,[]).append(out)
        if ledger_callback is not None:
            ledger_callback(name,out)
    current_stock_exit = np.zeros((s, n), dtype=bool)
    def stock_operational_mask(j, date, units):
        stock_exit = np.zeros_like(units, dtype=bool)
        for event in stock_events:
            c = ti[event.child_ticker]
            delivered = np.array([event.event_id in state.delivered_stock_event_ids for state in entitlement_states])
            held = delivered & (units[:, c] * factors[j, c] > TOL)
            if not held.any():
                continue
            marked = (market.row_present[j, c] and not quality[j, c]
                and np.isfinite(market.close[j, c]) and market.close[j, c] > 0)
            if not marked:
                for r in np.flatnonzero(held):
                    key = (int(r), event.event_id, "STOCK_CLOSE_MARK")
                    if key not in reported_exceptions:
                        accounting_exceptions.append(dict(path_id=ids[r], ticker=event.child_ticker,
                            effective_date=event.ex_date, first_affected_session=str(market.dates[j].date()),
                            reason="DELIVERED_STOCK_WITHOUT_QUALIFIED_RAW_CLOSE_NAV_MARK", nav_valid=False,
                            event_fingerprint=event.event_fingerprint, source_reference=event.source_reference,
                            source_fingerprint=event.source_fingerprint))
                        reported_exceptions.add(key)
                    invalid_paths[r] = True
                continue
            if (market.dates[j] >= pd.Timestamp(event.delivery_date)
                    and market.dates[j] >= pd.Timestamp(event.regular_trading_date)):
                # This field is bound to the then-known Top100 pool. Missing
                # alpha inputs never turn an eligible child into a forced exit.
                stock_exit[:, c] |= held & (not bool(market.new_buy_eligible[j, c]))
        current_stock_exit[:] = stock_exit
        return stock_exit
    if stock_events:
        lifecycle_hook._stock_distribution_operational_mask = stock_operational_mask
    def wrapped(j,context):
        age=np.where(entry_index >= 0,j-entry_index,-1)
        result=policy(j,PersistentPolicyContext(context,age.copy(),entry_date.copy(),
                      entry_price*entry_factor/factors[j][None,:],entry_price.copy(),context.current_units*factors[j][None,:],
                      entitlement_receivable.copy() if entitlement_enabled else None,
                      ~invalid_paths.copy() if entitlement_enabled else None,
                      current_stock_exit.copy() if stock_events else None))
        if not isinstance(result,TargetDecision):
            raise ValueError("policy must return the existing TargetDecision")
        if terminal_events and terminal_closed[j].any():
            weights = np.asarray(result.weights).copy()
            explicit = (context.decision_mask.copy() if result.explicit_mask is None
                        else np.asarray(result.explicit_mask).copy())
            if weights.shape != context.current_weights.shape or explicit.shape != weights.shape:
                raise ValueError("terminal policy decision shape mismatch")
            weights[:, terminal_closed[j]] = 0.
            explicit[:, terminal_closed[j]] = False
            result = TargetDecision(weights, explicit, result.raw_evidence_id)
        return result
    engine = run_many
    if entitlement_enabled:
        engine, engine_lineage = (_engine_with_entitlement_hook(lifecycle_hook, operational_exit_hook=stock_operational_mask)
            if stock_events else _engine_with_entitlement_hook(lifecycle_hook))
    engine_cost_bps = account_config["transaction_cost_bps"] if slippage_bps == 0 else slippage_bps
    replay=engine(common_market,ids,wrapped,initial_cash=capital,cost_bps=engine_cost_bps,
                    max_weight=account_config["max_weight"],max_positions=account_config["max_positions"],
                    max_invested=account_config["max_invested"],capacity_fraction=account_config.get("capacity_fraction"),
                    ledger_callback=callback)
    for name,chunks in enriched.items():
        setattr(replay,name,pd.concat(chunks,ignore_index=True))
    final_stock_exit = (stock_operational_mask(len(market.dates)-1, market.dates[-1], replay.final_units)
        if stock_events else np.zeros((s,n), dtype=bool))
    replay.accounting_exceptions=pd.DataFrame(accounting_exceptions)
    if entitlement_enabled:
        columns = ["path_id", "session", "event_id", "event_fingerprint", "old_security_id", "ticker", "phase", "ex_date", "record_date", "pay_date", "entitled_raw_shares", "amount_usd", "spendable_cash_delta", "source_fingerprint", "reason"]
        if terminal_events:
            columns += TERMINAL_LEDGER_COLUMNS
        if foreign_events:
            columns += ["currency", "amount_unit", "amount_foreign", "paid_gross_usd", "fx_conversion_fee_usd",
                "fx_observation_date", "fx_available_at", "fx_rate_unit", "fx_currency_per_usd", "fx_source_reference",
                "fx_source_fingerprint", "actual_broker_fx_payment_fee_tax_certified", "tax_withholding_mode"]
        if stock_events:
            columns += ["action_type", "child_security_id", "child_ticker", "child_units",
                "child_ratio_numerator", "child_ratio_denominator", "child_quantity_unit",
                "delivery_date", "regular_trading_date", "research_mode", "original_cash_in_lieu_terms",
                "parent_share_multiplier", "actual_broker_fractional_delivery_certified"]
            columns = list(dict.fromkeys(columns))
        if research_authority is not None or post_verified:
            columns += ["clock_role", "publication_available_at", "accounting_effective_at",
                        "reconstruction_ref", "reconstruction_sha256"]
        if post_verified:
            columns += ["accounting_boundary_role"]
        if full_selector_scope:
            columns += ["issuer_pay_date", "spendable_not_before", "accounting_clock_convention"]
        replay.entitlements = pd.DataFrame(entitlement_rows).reindex(columns=list(dict.fromkeys(columns)))
        replay.metadata.update(entitlement_lifecycle_enabled=True,
            entitlement_source_binding=entitlement_binding, entitlement_engine_projection=engine_lineage,
            entitlement_coverage_scope="declared source-backed events; unsupported exceptions retained",
            entitlement_quantity_coordinate=RAW_OLD_SHARE_COORDINATE)
        if terminal_events:
            replay.metadata.update(terminal_lifecycle_enabled=True,
                terminal_quote_domain="old security non-executable from source-backed effective session; no replacement price",
                terminal_events=[dict(event_id=e.event_id, event_fingerprint=e.event_fingerprint,
                    old_security_id=e.old_security_id, ticker=e.ticker, effective_date=e.effective_date,
                    settlement_authority_bound=e.settlement is not None) for e in terminal_events],
                terminal_settlement_qualified_by_path={ids[r]: bool(not terminal_settlement_missing[r]) for r in range(s)},
                terminal_settlement_semantics="cash only on or after independent source-confirmed payment date and availability; policy sees only legal known rights; missing complete settlement bundle makes held account unqualified")
    if research_authority is not None:
        replay.metadata.update(research_account_authority=copy.deepcopy(research_authority),
            research_account_scientific_identity=research_authority["scientific_identity"],
            strict_PIT_promotion_eligible=False, production_qualified=False,
            research_nav_semantics="TOTAL_ECONOMIC_NAV=cash+market_securities+receivables; LIQUID_NAV=cash+market_securities; receivables never fund orders")
    if entitlement_enabled or friction_contract is not None:
        replay.audit["actual_cash_flow_identity_error_max"] = actual_cash_error_max
    if friction_contract is not None:
        replay.metadata.update(execution_friction=friction_contract,
            fill_notional_semantics="notional/price remain raw Open benchmark; actual_fill_notional/actual_fill_price include adverse slippage",
            transaction_cost_semantics="total execution friction, not broker fee; transaction_fee is zero; cash already charged once")
    replay.final_state={"cash":replay.final_cash.copy(),"engine_units":replay.final_units.copy(),
                        "fractional_shares":replay.final_units*factors[-1][None,:],
                        "holding_age":np.where(entry_index>=0,len(market.dates)-1-entry_index,-1),
                        "entry_date":entry_date.copy(),"entry_price":entry_price*entry_factor/factors[-1][None,:],
                        "entry_execution_open":entry_price.copy(),
                        "last_session":str(market.dates[-1].date()),"accounting_qualified":~(invalid_paths | terminal_settlement_missing)}
    if stock_events:
        replay.final_state["stock_distribution_forced_exit_inventory_tickers"] = tuple(
            str(market.tickers[c]) for c in np.flatnonzero(final_stock_exit.any(axis=0)))
    if research_authority is not None:
        replay.final_state["research_accounting_qualified"] = ~invalid_paths.copy()
    if entitlement_enabled:
        replay.final_state.update(receivable_value_usd=entitlement_receivable.copy(),
            entitlement_states=tuple(entitlement_states),
            cash_receivables=tuple({"path_id": ids[r], **asdict(claim)} for r, state in enumerate(entitlement_states) for claim in state.receivables),
            stock_claims=tuple({"path_id": ids[r], **asdict(claim)} for r, state in enumerate(entitlement_states) for claim in state.stock_claims),
            foreign_cash_receivables=tuple({"path_id": ids[r], **asdict(claim)} for r, state in enumerate(entitlement_states) for claim in state.foreign_cash_receivables))
        if foreign_events:
            replay.metadata.update(foreign_cash_research_currency="CAD", foreign_fx_quote_unit="CAD_PER_USD",
                foreign_fx_available_clock="SOURCE_RELEASE_DATE_END_NY_CONSERVATIVE_BOUND_NOT_ACTUAL_TIME",
                fx_conversion_friction_bps=foreign_conversion_friction_bps,
                actual_broker_fx_payment_fee_or_tax_certified=False, tax_withholding="NOT_MODELED_GROSS_DIVIDEND_RESEARCH")
        if stock_events:
            replay.metadata.update(stock_distribution_research_mode=stock_events[0].research_mode,
                actual_broker_fractional_delivery_or_cash_in_lieu_certified=False,
                stock_claim_without_qualified_close_nav_mark="HARD_BLOCK",
                stock_distribution_forced_exit_scope="delivered regular-tradable child inventory currently buy-ineligible; first close decision and existing next legal Open execution")
    if previous_prefix is not None and account_prefix_identity(replay,previous_prefix["end_session"]) != previous_prefix:
        raise AssertionError("locked continuation changed frozen pre-2026 account prefix")
    replay.prefix_identity=(None if descriptive_authority is not None else
        account_prefix_identity(replay,min(market.dates[-1],pd.Timestamp("2025-12-31"))))
    replay.metadata.update(unit="fractional raw-share research coordinate; engine coordinates retained explicitly",
        account_config=dict(account_config),continuous_account=True,annual_reset=False,
        corporate_action_transition_source="scripts/v22/corporate_action_transition_r1.py",
        corporate_action_receipts=event_receipts,corporate_action_exceptions=exceptions,
        raw_open_fill_translation=True,live_official_auction_certification=False,
        pending_continuation_mode="frozen full-prefix replay and identity comparison",
        holding_age_semantics="sessions since first actual Open fill of current holding spell",
        entry_price_semantics="first fill translated to current share basis; entry_execution_open retains original raw receipt",
        accounting_exception_count=len(accounting_exceptions),
        unsupported_event_semantics="only effective session quote blocked; affected pre-existing held account stays unqualified; later first buys unaffected")
    if descriptive_authority is not None:
        import json
        replay.metadata.update(
            descriptive_evaluation_authority=json.loads(descriptive_authority.provenance_json),
            strict_PIT_promotion_eligible=False, production_qualified=False,
            evaluation_role="USER_NAMED_FROZEN_POLICY_DESCRIPTIVE_2026",
            pending_continuation_mode="INDEPENDENT_FRESH_CASH_WINDOW_NO_INHERITED_PREFIX")
        if reconstructed_cash:
            replay.metadata["research_cash_reconstruction"] = json.loads(
                descriptive_authority.research_cash_reconstruction_json)
            replay.metadata["cash_publication_clock_reconstructed"] = False
            replay.metadata["cash_accounting_clock_role"] = "POST_VERIFIED_ACCOUNTING_ONLY"
        if reconstructed_terminal:
            replay.metadata["research_terminal_reconstruction"] = json.loads(
                descriptive_authority.research_terminal_reconstruction_json)
            replay.metadata["terminal_publication_clock_reconstructed"] = False
            replay.metadata["terminal_accounting_clock_role"] = "POST_VERIFIED_ACCOUNTING_ONLY"
            replay.metadata["terminal_settlement_assumed"] = False
    if ca_convention is not None:
        columns = ["path_id", *_SESSION_BOUNDARY_KEY, "accounting_boundary_at",
                   "pre_open_engine_units", "prior_session_quantity_factor", "pre_open_raw_shares",
                   "disposition", "clock_role"]
        replay.research_ca_accounting_boundary_audit = pd.DataFrame(boundary_rows, columns=columns)
        replay.metadata["research_ca_accounting_convention"] = dict(
            scientific_identity=_SESSION_BOUNDARY_IDENTITY,
            source_and_code_freeze_ref=dict(research_ca_accounting_convention),
            contract_ref=ca_convention["contract_ref"], rule_ref=ca_convention["rule_ref"],
            population_ref=ca_convention["population_ref"],
            real_effective_clock_proven=False, research_session_boundary_assumption=True,
            strict_PIT_promotion_eligible=False, production_qualified=False,
            declaration=ca_convention["rule_definition"]["declaration"],
            population_row_count=ca_convention["population_row_count"],
            eligible_mechanism_count=ca_convention["eligible_count"],
            processed_path_mechanisms=len(boundary_rows),
            blocked_inherited_path_mechanisms=sum(r["disposition"] == "ACCOUNTING_BLOCKED" for r in boundary_rows),
            no_inherited_position_path_mechanisms=sum(r["disposition"] == "NOT_APPLICABLE_TO_THIS_ACCOUNT_PREFIX" for r in boundary_rows))
    return replay
