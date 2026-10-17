"""Shared source-only quote classification and execution-only engine projection.

No outcome, holding, forecast or account state enters classification. Source
custody and bounded decoding belong to the existing source-binding owners.
The immutable common engine remains the sole execution implementation.
"""
from __future__ import annotations

import ast
import copy
from datetime import date
import hashlib
import math
from pathlib import Path
from numbers import Real

import numpy as np
import pandas as pd

ENGINE_SHA256 = "200462d48816918a5b9fe72f2239a81d01f69a32d57922e8e47cf1ee4c06ee1b"
PENDING_AST_SHA256 = "a262f09b9c8748a6f9e25dc3681b27954907579ff67537d3c4d7277d1ad8d6b7"
USABLE_GLOBAL = "_research_quote_execution_a"
PROOF_GLOBAL = "_research_quote_execution_coordinate_proof"
PROOF_AUDIT_KEY = "exact_execution_coordinate_identity_error_max"
EXECUTION_IDENTITY_TOL_USD = 1e-5
AUDIT_AST_SHA256 = "9b7bab40554120c2474f9598f19345601b0ae141929ba0d06d9c5a53f4928e26"
TERMINAL_GATE_AST_SHA256 = "91965df31644705da0eeea9da584eb2db3b60202608dbf658d72f759676b6380"
CLASSES = {
    "A": "EXACT_FROZEN_RAW_QUOTE_RESEARCH_USABLE",
    "B": "RAW_ROW_MISSING",
    "C": "OPEN_OR_CLOSE_INVALID",
    "D": "SECURITY_COORDINATE_AMBIGUOUS",
    "E": "KNOWN_REAL_QUOTE_DEFECT",
    "F": "TERMINAL_OR_NONTRADABLE",
    "G": "SOURCE_AUTHORITY_UNRESOLVED",
}
PRIORITY = ("F", "D", "E", "B", "C", "G", "A")
QUALIFICATION = dict(strict_PIT=False, production_qualified=False,
                     quote_qualified=False, certified_NAV=False,
                     legal_identity_authority=False)
_RECORD_FIELDS = {
    "date", "ticker", "masked", "raw_rows", "raw_coordinate_proof",
    "identity_proof", "identity_conflicts", "coordinate_conflicts",
    "quality_origins", "known_real_defect_flags", "known_real_defect_scope",
    "terminal_contracts", "source_availability",
}
_ROW_FIELDS = {"date", "ticker", "open", "close", "row_identity", "source_ref",
               "coordinate", "code"}


class QuoteDomainFailure(ValueError):
    def __init__(self, reason, key=None, **metadata):
        self.reason, self.key = reason, key
        self.receipt = dict(reason=reason, key=key, **metadata)
        super().__init__(reason + (":" + "|".join(key) if key else ""))


def _fail(reason, key=None, **metadata):
    raise QuoteDomainFailure(reason, key, **metadata)


def _day(value):
    if not isinstance(value, str):
        _fail("CANONICAL_QUOTE_DATE_REQUIRED")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail("CANONICAL_QUOTE_DATE_REQUIRED")
    if parsed.isoformat() != value:
        _fail("CANONICAL_QUOTE_DATE_REQUIRED")
    return parsed


def _source(ref):
    if not isinstance(ref, dict):
        return None
    path, sha = ref.get("path"), ref.get("sha256")
    if isinstance(path, str) and path[:2].upper() in ("E:", "F:"):
        _fail("FORBIDDEN_SOURCE_DRIVE")
    if (not isinstance(path, str) or not path.strip() or
            not isinstance(sha, str) or len(sha) != 64 or
            any(c not in "0123456789abcdef" for c in sha)):
        return None
    return path, sha


def _positive(value):
    return isinstance(value, Real) and not isinstance(value, (bool, np.bool_)) and math.isfinite(value) and value > 0


def _flags(value, key, field):
    if not isinstance(value, list) or any(not isinstance(v, dict) or
            not isinstance(v.get("reason"), str) or not v["reason"].strip() for v in value):
        _fail("TYPED_SOURCE_REASON_LIST_REQUIRED", key, field=field)
    return value


def _reject_forbidden(value):
    forbidden = {"pnl", "return", "returns", "annual_returns", "sharpe", "score",
                 "rank", "forecast", "risk", "holdings", "held", "units", "cash",
                 "current_units", "current_weights", "future_account_state",
                 "candidate_id", "selected"}
    if isinstance(value, dict):
        for name, child in value.items():
            if isinstance(name, str) and name.lower() in forbidden:
                _fail("FORBIDDEN_QUOTE_CLASSIFICATION_INPUT", field=name)
            _reject_forbidden(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_forbidden(child)


def classify_quote_key(record):
    """Apply one outcome-independent rule to either source-binding branch.

    Missing source authority is G, never invented evidence of a real defect.
    An empty real-defect list is scoped to the explicitly checked approved
    sources, and does not certify the wider provider/security universe.
    """
    _reject_forbidden(record)
    if not isinstance(record, dict) or set(record) != _RECORD_FIELDS:
        _fail("FORBIDDEN_OR_MISSING_QUOTE_INPUT_FIELDS",
              fields=sorted(set(record) ^ _RECORD_FIELDS) if isinstance(record, dict) else [])
    ticker = record["ticker"]
    day = _day(record["date"])
    if not isinstance(ticker, str) or not ticker or ticker != ticker.strip():
        _fail("LITERAL_QUOTE_TICKER_REQUIRED")
    key = (record["date"], ticker)
    if not date(2023, 1, 1) <= day < date(2026, 1, 1):
        _fail("QUOTE_KEY_OUTSIDE_PRE2026_DOMAIN", key)
    if type(record["masked"]) is not bool or record["masked"] is not True:
        _fail("OLD_QUALITY_TRUE_POPULATION_REQUIRED", key)
    if not isinstance(record["source_availability"], str) or not record["source_availability"].strip():
        _fail("SOURCE_AVAILABILITY_STATUS_REQUIRED", key)
    rows = record["raw_rows"]
    if not isinstance(rows, list) or any(not isinstance(row, dict) or
            not set(row).issubset(_ROW_FIELDS) for row in rows):
        _fail("EXACT_RAW_SOURCE_ROW_PROJECTION_REQUIRED", key)
    groups = {c: set() for c in CLASSES}
    reasons = set()

    def add(letter, reason):
        groups[letter].add(reason)

    if not rows:
        add("B", "RAW_ROW_MISSING")
    elif len(rows) != 1:
        add("D", "RAW_ROW_NOT_UNIQUE")
    for row in rows:
        if row.get("date") != record["date"] or row.get("ticker") != ticker:
            add("D", "RAW_ROW_KEY_MISMATCH")
        physical = row.get("row_identity")
        physical_ok = (isinstance(physical, (str, int, np.integer)) and
                       not isinstance(physical, (bool, np.bool_)) and
                       (bool(physical) if isinstance(physical, str) else physical >= 0))
        if _source(row.get("source_ref")) is None or not physical_ok:
            add("G", "RAW_ROW_SOURCE_OR_PHYSICAL_IDENTITY_UNRESOLVED")
        if "coordinate" in row and row["coordinate"] != "RAW_UNADJUSTED":
            add("D", "RAW_ROW_COORDINATE_CONFLICT")
        for field in ("open", "close"):
            if not _positive(row.get(field)):
                add("C", "RAW_" + field.upper() + "_INVALID")
    proof = record["raw_coordinate_proof"]
    if not isinstance(proof, dict) or _source(proof.get("source_ref")) is None:
        add("G", "RAW_COORDINATE_SOURCE_UNRESOLVED")
    elif proof.get("status") == "UNKNOWN":
        add("G", "RAW_COORDINATE_SOURCE_UNRESOLVED")
    elif proof.get("status") != "RAW_UNADJUSTED":
        add("D", "RAW_COORDINATE_NOT_EXACT_UNADJUSTED")
    identity = record["identity_proof"]
    if not isinstance(identity, dict) or _source(identity.get("source_ref")) is None:
        add("G", "SECURITY_IDENTITY_SOURCE_UNRESOLVED")
    elif identity.get("status") == "AMBIGUOUS":
        add("D", "SOURCE_SECURITY_IDENTITY_AMBIGUOUS")
    elif identity.get("status") != "EXACT_UNIQUE":
        add("G", "SECURITY_IDENTITY_SOURCE_UNRESOLVED")
    elif identity.get("kind") == "OPAQUE_FROZEN_BUNDLE":
        if not isinstance(identity.get("token"), str) or not identity["token"].strip():
            add("G", "OPAQUE_BUNDLE_IDENTITY_TOKEN_UNRESOLVED")
    elif identity.get("kind") == "DATED_SECURITY_MAPPING":
        try:
            covering = (identity.get("ticker") == ticker and bool(identity.get("sid")) and
                        _day(identity["start"]) <= day < _day(identity["end"]))
        except (KeyError, QuoteDomainFailure):
            covering = False
        if not covering:
            add("D", "DATED_SECURITY_IDENTITY_NOT_COVERING_EXACT_KEY")
    else:
        add("G", "SECURITY_IDENTITY_AUTHORITY_KIND_UNRESOLVED")
    for field in ("identity_conflicts", "coordinate_conflicts"):
        for flag in _flags(record[field], key, field):
            if _source(flag.get("source_ref")) is None:
                add("G", field.upper() + "_SOURCE_UNRESOLVED")
            else:
                add("D", field.upper() + ":" + flag["reason"])

    scope = record["known_real_defect_scope"]
    refs = scope.get("source_refs") if isinstance(scope, dict) else None
    approved = set()
    if (not isinstance(scope, dict) or scope.get("status") != "BOUND_APPROVED_SOURCES_CHECKED"
            or not isinstance(refs, list) or not refs):
        add("G", "REAL_DEFECT_CHECK_SOURCE_SCOPE_UNRESOLVED")
    else:
        for ref in refs:
            source = _source(ref)
            if source is None:
                add("G", "REAL_DEFECT_CHECK_SOURCE_SCOPE_UNRESOLVED")
            else:
                approved.add(source)
    origins = _flags(record["quality_origins"], key, "quality_origins")
    if not origins:
        add("G", "OLD_QUALITY_ORIGIN_UNEXPLAINED")
    for origin in origins:
        reasons.add("OLD_QUALITY_ORIGIN:" + origin["reason"])
        source = _source(origin.get("source_ref"))
        if source is None or source not in approved:
            add("G", "QUALITY_ORIGIN_NOT_IN_BOUND_APPROVED_SCOPE")
        elif origin.get("kind") == "KNOWN_REAL_QUOTE_DEFECT":
            add("E", "KNOWN_REAL_QUOTE_DEFECT:" + origin["reason"])
        elif origin.get("kind") not in ("MECHANISM_ONLY", "ADJUSTED_RAW_DIFFERENCE_ONLY"):
            add("G", "OLD_QUALITY_ORIGIN_UNRESOLVED:" + origin["reason"])
    for flag in _flags(record["known_real_defect_flags"], key, "known_real_defect_flags"):
        if _source(flag.get("source_ref")) not in approved:
            add("G", "REAL_DEFECT_FLAG_SOURCE_UNRESOLVED")
        else:
            add("E", "KNOWN_REAL_QUOTE_DEFECT:" + flag["reason"])

    contracts = _flags(record["terminal_contracts"], key, "terminal_contracts")
    for contract in contracts:
        if _source(contract.get("source_ref")) is None:
            add("G", "TERMINAL_CONTRACT_SOURCE_UNRESOLVED")
            continue
        try:
            start = _day(contract["start"])
            end = _day(contract["end"]) if contract.get("end") is not None else date.max
        except (KeyError, QuoteDomainFailure):
            add("G", "TERMINAL_CONTRACT_CLOCK_UNRESOLVED")
            continue
        if contract.get("ticker") != ticker or not start < end:
            add("D", "TERMINAL_CONTRACT_KEY_OR_INTERVAL_CONFLICT")
        elif start <= day < end:
            add("F", "TERMINAL_OR_NONTRADABLE:" + contract["reason"])
    letter = next(c for c in PRIORITY if c == "A" or groups[c])
    blockers = sorted({reason for values in groups.values() for reason in values})
    return dict(key=dict(date=record["date"], ticker=ticker),
                classification=letter, classification_name=CLASSES[letter],
                usable_for_research_execution=letter == "A",
                usable_for_research_outcome_valuation=letter == "A",
                blocking_flags=blockers, reason_flags=sorted(reasons | set(blockers)),
                source_availability=record["source_availability"],
                known_real_defect_scope=copy.deepcopy(scope),
                qualification=dict(QUALIFICATION), evidence=copy.deepcopy(record))


def classify_population(records):
    decisions = [classify_quote_key(record) for record in records]
    keys = [(v["key"]["date"], v["key"]["ticker"]) for v in decisions]
    if len(set(keys)) != len(keys):
        _fail("DUPLICATE_QUOTE_POPULATION_KEY")
    return sorted(decisions, key=lambda v: (v["key"]["date"], v["key"]["ticker"]))


def build_usable_a_mask(dates, tickers, quality, decisions, *, raw_open, raw_close):
    """Bind complete classified old masks to one runtime's exact original cells."""
    days = pd.DatetimeIndex(dates)
    names = tuple(tickers)
    if (days.empty or days.tz is not None or days.hasnans or days.has_duplicates or
            not days.is_monotonic_increasing or not days.equals(days.normalize()) or
            days[0] < pd.Timestamp("2023-01-01") or days[-1] >= pd.Timestamp("2026-01-01") or
            not names or len(set(names)) != len(names) or
            any(not isinstance(t, str) or not t or t != t.strip() for t in names)):
        _fail("EXACT_PRE2026_MARKET_AXES_REQUIRED")
    shape = (len(days), len(names))
    base = np.asarray(quality)
    opens, closes = np.asarray(raw_open), np.asarray(raw_close)
    if base.dtype.kind != "b" or base.shape != shape or opens.shape != shape or closes.shape != shape:
        _fail("EXACT_QUOTE_BINDING_ARRAY_SHAPES_REQUIRED")
    di = {str(d.date()): i for i, d in enumerate(days)}
    ti = {t: i for i, t in enumerate(names)}
    usable = np.zeros(shape, bool)
    seen, covered, outside = set(), set(), []
    for decision in decisions:
        expected = classify_quote_key(decision["evidence"])
        if decision != expected:
            _fail("QUOTE_DECISION_NOT_DERIVED_FROM_EVIDENCE")
        key = (decision["key"]["date"], decision["key"]["ticker"])
        if key in seen:
            _fail("DUPLICATE_QUOTE_POPULATION_KEY", key)
        seen.add(key)
        if key[0] not in di or key[1] not in ti:
            outside.append(dict(date=key[0], ticker=key[1]))
            continue
        ij = (di[key[0]], ti[key[1]])
        if not base[ij]:
            _fail("QUOTE_DECISION_KEY_NOT_IN_OLD_MASK", key)
        covered.add(ij)
        if decision["classification"] == "A":
            row = decision["evidence"]["raw_rows"][0]
            if opens[ij] != row["open"] or closes[ij] != row["close"]:
                _fail("A_RAW_VALUE_DOES_NOT_MATCH_ORIGINAL_MARKET_CELL", key)
            usable[ij] = True
    required = set(zip(*np.nonzero(base)))
    if required != covered:
        missing = sorted(required - covered)
        key = (str(days[missing[0][0]].date()), names[missing[0][1]]) if missing else None
        _fail("OLD_QUALITY_POPULATION_COVERAGE_INCOMPLETE", key, missing_count=len(missing))
    usable.setflags(write=False)
    return usable, dict(runtime_old_mask_keys=len(required), covered_keys=len(covered),
                        usable_a_keys=int(usable.sum()), outside_runtime_keys=outside,
                        original_quality_changed=False, qualification=dict(QUALIFICATION))



def execution_coordinate_proof(units_before, cash_before, units_after, cash_after,
        execution_open, row_present, execution_valid_open, buy_quantity,
        sell_quantity, buy_notional, sell_notional, buy_cost, sell_cost, fees, rate):
    """Independent identities in the engine's own execution coordinate.

    This is price-index units times its execution Open, not a claim that the
    engine arrays are raw shares/prices. Existing continuous-owner raw-share
    translation and friction checks remain necessary for that separate claim.
    The fixed 1e-5 USD terminal tolerance is inherited from the original gate.
    """
    before, after = np.asarray(units_before), np.asarray(units_after)
    cb, ca, fee = map(np.asarray, (cash_before, cash_after, fees))
    price = np.asarray(execution_open)
    present, valid = map(np.asarray, (row_present, execution_valid_open))
    matrices = [np.asarray(v) for v in (buy_quantity, sell_quantity, buy_notional,
                                        sell_notional, buy_cost, sell_cost)]
    if (before.ndim != 2 or after.shape != before.shape or
            any(v.shape != before.shape for v in matrices) or
            any(v.shape != before.shape[:1] for v in (cb, ca, fee)) or
            price.shape != before.shape[1:] or
            any(v.dtype.kind != "b" or v.shape != price.shape for v in (present, valid)) or
            not isinstance(rate, Real) or not math.isfinite(rate) or not 0 <= rate < 1):
        _fail("EXACT_EXECUTION_PROOF_SHAPES_REQUIRED")
    bq, sq, bn, sn, bc, sc = matrices
    delta = after - before
    traded = (np.abs(delta) > 0) | (bq > 0) | (sq > 0) | (bn > 0) | (sn > 0) | (bc > 0) | (sc > 0)
    invalid = (traded & (~present | ~valid | ~np.isfinite(price) | (price <= 0))[None, :]).sum(axis=1)
    bad_matrix = ~np.isfinite(before) | ~np.isfinite(after) | (before < 0) | (after < 0)
    for values in matrices:
        bad_matrix |= ~np.isfinite(values) | (values < 0)
    invalid += bad_matrix.sum(axis=1)
    invalid += (~np.isfinite(cb) | ~np.isfinite(ca) | ~np.isfinite(fee) | (fee < 0)).astype(int)
    # A nontraded unavailable quote contributes zero, never a substituted quote.
    used_price = np.where(traded, price[None, :], 0.)
    cash_error = ca - cb + np.sum(delta * used_price, axis=1) + fee
    quantity_residual = delta - (bq - sq)
    quantity_error = np.max(np.abs(quantity_residual * used_price), axis=1)
    notional_error = np.maximum(np.max(np.abs(bn - bq * used_price), axis=1),
                                np.max(np.abs(sn - sq * used_price), axis=1))
    fee_error = fee - np.sum(bc + sc, axis=1)
    rate_error = np.maximum(np.max(np.abs(bc - bn * rate), axis=1),
                            np.max(np.abs(sc - sn * rate), axis=1))
    errors = np.stack([np.abs(cash_error), quantity_error, notional_error,
                       np.abs(fee_error), rate_error], axis=1)
    identity_error = np.max(errors, axis=1)
    identity_error[(invalid > 0) | ~np.isfinite(errors).all(axis=1)] = np.inf
    return dict(cash_delta=ca-cb,
        execution_coordinate_position_delta=np.sum(delta * used_price, axis=1),
        transaction_cost=fee.copy(), execution_cash_identity_error=cash_error,
        execution_quantity_identity_error_units=np.max(np.abs(quantity_residual), axis=1),
        execution_quantity_identity_error_usd=quantity_error,
        execution_notional_identity_error=notional_error,
        execution_fee_identity_error=fee_error, execution_cost_rate_identity_error=rate_error,
        invalid_execution_cell_count=invalid, identity_error=identity_error)


def _ast_hash(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def project_pending_execution_ast(function_node, engine_source_sha256):
    """Project execution admission and its accounting-only comparator.

    Callers physically verify the immutable source and bind USABLE_GLOBAL and
    PROOF_GLOBAL. Original decision marks, masks, quality and all old diagnostic
    computations remain byte-for-byte identical in normalized reverse AST.
    The legacy mixed-mark self-finance error remains an audit/daily diagnostic;
    only its one terminal comparator is replaced by same-coordinate identities.
    """
    if engine_source_sha256 != ENGINE_SHA256:
        _fail("IMMUTABLE_COMMON_ENGINE_SOURCE_CHANGED")
    node = copy.deepcopy(function_node)
    if not isinstance(node, ast.FunctionDef) or node.name != "run_many":
        _fail("ORIGINAL_RUN_MANY_AST_REQUIRED")
    loops = [n for n in node.body if isinstance(n, ast.For) and ast.unparse(n.target) == "(di, date)"]
    if len(loops) != 1:
        _fail("ORIGINAL_SESSION_LOOP_ANCHOR_CHANGED")
    blocks = [n for n in loops[0].body if isinstance(n, ast.If) and ast.unparse(n.test) == "pending is not None"]
    if len(blocks) != 1 or _ast_hash(blocks[0]) != PENDING_AST_SHA256:
        _fail("ORIGINAL_PENDING_BLOCK_AST_CHANGED")
    initializers = [n for n in node.body if isinstance(n, ast.Assign) and
                    any(isinstance(t, ast.Name) and t.id == "audit" for t in n.targets)]
    gates = [n for n in node.body if isinstance(n, ast.If) and
             any(isinstance(v, ast.Constant) and v.value == "self_finance_error_max" for v in ast.walk(n.test))]
    if (len(initializers) != 1 or _ast_hash(initializers[0]) != AUDIT_AST_SHA256 or
            len(gates) != 1 or _ast_hash(gates[0]) != TERMINAL_GATE_AST_SHA256):
        _fail("ORIGINAL_ACCOUNTING_COMPARATOR_ANCHOR_CHANGED")
    block = blocks[0]
    class Replace(ast.NodeTransformer):
        count = 0
        def visit_Name(self, item):
            if item.id == "valid_open" and isinstance(item.ctx, ast.Load):
                self.count += 1
                return ast.copy_location(ast.Name("execution_valid_open", ast.Load()), item)
            return item
    transform = Replace()
    transform.visit(block)
    if transform.count != 7:
        _fail("PENDING_VALID_OPEN_EXACT_COUNT_CHANGED")
    prefix = ast.parse(
        "execution_valid_open = valid_open | (" + USABLE_GLOBAL +
        "[di] & _positive(market.open[di]) & market.row_present[di])\n"
        "_quote_units_before = units.copy()\n_quote_cash_before = cash.copy()").body
    suffix = ast.parse(
        "_quote_proof = " + PROOF_GLOBAL + "(\n"
        "    _quote_units_before, _quote_cash_before, units, cash, market.open[di],\n"
        "    market.row_present[di], execution_valid_open, quantity, sell_quantity,\n"
        "    amount, sell_amount, cost, sell_cost, fees, rate)\n"
        "audit['" + PROOF_AUDIT_KEY + "'] = max(audit['" + PROOF_AUDIT_KEY +
        "'], float(np.max(_quote_proof['identity_error'])))\n"
        "if ledger_callback is not None:\n"
        "    ledger_callback('execution_coordinate_proof', pd.DataFrame(dict(\n"
        "        path_id=id_array.copy(), date=np.repeat(date.to_datetime64(), s),\n"
        "        signal_date=np.repeat(market.dates[pi].to_datetime64(), s), **_quote_proof)))"
    ).body
    block.body[0:0] = prefix
    block.body.extend(suffix)
    init = ast.parse("audit['" + PROOF_AUDIT_KEY + "'] = 0.0").body[0]
    node.body.insert(node.body.index(initializers[0]) + 1, init)
    replaced_constants = []
    for value in ast.walk(gates[0].test):
        if isinstance(value, ast.Constant) and value.value == "self_finance_error_max":
            value.value = PROOF_AUDIT_KEY
            replaced_constants.append(value)
    if len(replaced_constants) != 1:
        _fail("ORIGINAL_SINGLE_SELF_FINANCE_COMPARATOR_CHANGED")
    node = ast.fix_missing_locations(node)
    reverse = copy.deepcopy(node)
    reverse.body = [n for n in reverse.body if ast.dump(n, include_attributes=False) !=
                    ast.dump(init, include_attributes=False)]
    reverse_loop = next(n for n in reverse.body if isinstance(n, ast.For) and ast.unparse(n.target) == "(di, date)")
    reverse_block = next(n for n in reverse_loop.body if isinstance(n, ast.If) and ast.unparse(n.test) == "pending is not None")
    reverse_block.body = reverse_block.body[len(prefix):-len(suffix)]
    class Undo(ast.NodeTransformer):
        def visit_Name(self, item):
            if item.id == "execution_valid_open" and isinstance(item.ctx, ast.Load):
                return ast.copy_location(ast.Name("valid_open", ast.Load()), item)
            return item
    Undo().visit(reverse_block)
    for gate in reverse.body:
        if isinstance(gate, ast.If):
            for value in ast.walk(gate.test):
                if isinstance(value, ast.Constant) and value.value == PROOF_AUDIT_KEY:
                    value.value = "self_finance_error_max"
    if ast.dump(reverse, include_attributes=False) != ast.dump(function_node, include_attributes=False):
        _fail("QUOTE_EXECUTION_REVERSE_PROJECTION_NOT_EXACT")
    return node, dict(engine_source_sha256=ENGINE_SHA256,
        original_pending_ast_sha256=PENDING_AST_SHA256, replaced_pending_loads=7,
        original_input_function_ast_sha256=_ast_hash(function_node),
        projected_function_ast_sha256=_ast_hash(node),
        reverse_projected_function_ast_sha256=_ast_hash(reverse),
        normalized_reverse_projection_exact=True,
        original_decision_quality_marks_nav_unchanged=True,
        accounting_comparator=dict(legacy_self_finance_diagnostic_retained=True,
            terminal_replacement_count=1, original_other_terminal_gates_retained=True,
            replacement_key=PROOF_AUDIT_KEY, fixed_tolerance_usd=EXECUTION_IDENTITY_TOL_USD,
            coordinate="engine price-index units times engine execution Open",
            raw_share_translation_requires_original_owner_assertions=True,
            callback_table="execution_coordinate_proof"),
        raw_close_in_policy_context=False, qualification=dict(QUALIFICATION))


def compile_execution_only_run_many(usable_a):
    """Standalone synthetic/owner adapter; never read data or execute here."""
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2 import fast_account
    mask = np.asarray(usable_a)
    if mask.dtype.kind != "b" or mask.ndim != 2:
        _fail("EXACT_BOOLEAN_EXECUTION_A_MASK_REQUIRED")
    mask = mask.copy()
    mask.setflags(write=False)
    source = Path(fast_account.__file__).read_bytes()
    actual = hashlib.sha256(source).hexdigest()
    if actual != ENGINE_SHA256:
        _fail("IMMUTABLE_COMMON_ENGINE_SOURCE_CHANGED")
    tree = ast.parse(source.decode("utf-8-sig"))
    original = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_many")
    node, receipt = project_pending_execution_ast(original, actual)
    namespace = dict(vars(fast_account))
    namespace[USABLE_GLOBAL] = mask
    namespace[PROOF_GLOBAL] = execution_coordinate_proof
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 fast_account.__file__, "exec"), namespace)
    projected = namespace["run_many"]
    def bound(market, *args, **kwargs):
        if mask.shape != market.open.shape:
            _fail("EXACT_EXECUTION_A_MASK_SHAPE_REQUIRED")
        return projected(market, *args, **kwargs)
    return bound, receipt


def outcome_raw_close_values(raw_units, raw_close, original_valid_close, usable_a, row_present):
    """Independent raw-share outcome values; no decision marks, NAV or state writes."""
    units, close = np.asarray(raw_units), np.asarray(raw_close)
    original, admitted, present = map(np.asarray, (original_valid_close, usable_a, row_present))
    if (units.ndim != 2 or close.shape != units.shape[1:] or
            any(m.dtype.kind != "b" or m.shape != close.shape for m in (original, admitted, present)) or
            not np.isfinite(units).all() or (units < 0).any()):
        _fail("EXACT_OUTCOME_SNAPSHOT_SHAPES_REQUIRED")
    legal = (original | admitted) & present & np.isfinite(close) & (close > 0)
    values = np.where(units > 1e-10, np.where(legal, close, np.nan)[None, :] * units, 0.)
    values.setflags(write=False)
    return values
