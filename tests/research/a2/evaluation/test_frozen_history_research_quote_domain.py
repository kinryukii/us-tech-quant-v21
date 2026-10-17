"""Synthetic shared quote-rule and immutable execution-scope checks only."""
import ast
from copy import deepcopy
import hashlib
from pathlib import Path
from types import FunctionType, SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.evaluation import frozen_history_research_quote_domain as rule
from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2 import fast_account as engine


def ref(letter="a", name="raw"):
    return dict(path="synthetic://" + name, sha256=letter * 64)


def record(day="2023-01-04", ticker="S"):
    return dict(
        date=day, ticker=ticker, masked=True,
        raw_rows=[dict(date=day, ticker=ticker, open=12., close=99.,
                       row_identity=4, source_ref=ref(), coordinate="RAW_UNADJUSTED")],
        raw_coordinate_proof=dict(status="RAW_UNADJUSTED", source_ref=ref()),
        identity_proof=dict(kind="OPAQUE_FROZEN_BUNDLE", status="EXACT_UNIQUE",
                            token="research-axis-and-row", source_ref=ref()),
        identity_conflicts=[], coordinate_conflicts=[],
        quality_origins=[dict(kind="MECHANISM_ONLY", reason="UNSUPPORTED_ACCOUNTING_FACTOR",
                              source_ref=ref("b", "mechanism"))],
        known_real_defect_flags=[],
        known_real_defect_scope=dict(status="BOUND_APPROVED_SOURCES_CHECKED",
                                    source_refs=[ref(), ref("b", "mechanism")]),
        terminal_contracts=[], source_availability="UNKNOWN")


def fail(call, reason):
    with pytest.raises(rule.QuoteDomainFailure) as caught:
        call()
    assert caught.value.reason == reason
    assert caught.value.receipt["reason"] == reason
    return caught.value


def test_opaque_identity_and_mechanism_only_origin_allow_a_without_legal_authority():
    result = rule.classify_quote_key(record())
    assert result["classification"] == "A"
    assert result["usable_for_research_execution"]
    assert result["source_availability"] == "UNKNOWN"
    assert not any(result["qualification"].values())
    assert result["known_real_defect_scope"]["source_refs"] == record()["known_real_defect_scope"]["source_refs"]
    changed = record()
    changed["quality_origins"][0]["kind"] = "ADJUSTED_RAW_DIFFERENCE_ONLY"
    assert rule.classify_quote_key(changed)["classification"] == "A"


@pytest.mark.parametrize("letter", ["B", "C", "D", "E", "F", "G"])
def test_all_blocking_classes_are_distinct_and_preserve_source_reasons(letter):
    row = record()
    if letter == "B":
        row["raw_rows"] = []
    elif letter == "C":
        row["raw_rows"][0]["open"] = 0.
    elif letter == "D":
        row["identity_conflicts"] = [dict(reason="SAME_DAY_MULTIPLE_CODE_OR_MAPPING",
                                         source_ref=ref())]
    elif letter == "E":
        row["known_real_defect_flags"] = [dict(reason="EXPLICIT_APPROVED_RAW_DEFECT",
                                              source_ref=ref())]
    elif letter == "F":
        row["terminal_contracts"] = [dict(ticker="S", start=row["date"],
                                         reason="OLD_SECURITY_NONTRADABLE", source_ref=ref())]
    else:
        row["known_real_defect_scope"] = None
    result = rule.classify_quote_key(row)
    assert result["classification"] == letter
    assert result["blocking_flags"]
    assert not result["usable_for_research_execution"]
    assert "OLD_QUALITY_ORIGIN:UNSUPPORTED_ACCOUNTING_FACTOR" in result["reason_flags"]


@pytest.mark.parametrize("value", [None, np.nan, np.inf, -1., 0., True, "12"])
def test_invalid_raw_value_is_c_not_an_admitted_cash_or_factor_event(value):
    row = record()
    row["raw_rows"][0]["close"] = value
    assert rule.classify_quote_key(row)["classification"] == "C"


def test_terminal_priority_and_all_independent_blockers_are_retained():
    row = record()
    row["raw_rows"] = []
    row["identity_conflicts"] = [dict(reason="TICKER_AMBIGUOUS", source_ref=ref())]
    row["known_real_defect_flags"] = [dict(reason="BAD_RAW_SOURCE", source_ref=ref())]
    row["terminal_contracts"] = [dict(ticker="S", start=row["date"], reason="HALTED",
                                     source_ref=ref())]
    result = rule.classify_quote_key(row)
    assert result["classification"] == "F"
    assert {"RAW_ROW_MISSING", "IDENTITY_CONFLICTS:TICKER_AMBIGUOUS",
            "KNOWN_REAL_QUOTE_DEFECT:BAD_RAW_SOURCE", "TERMINAL_OR_NONTRADABLE:HALTED"} <= set(result["blocking_flags"])


def test_duplicate_raw_rows_key_mismatch_and_coordinate_conflict_are_d():
    for kind in ("duplicate", "key", "coordinate"):
        row = record()
        if kind == "duplicate":
            row["raw_rows"].append(deepcopy(row["raw_rows"][0]))
        elif kind == "key":
            row["raw_rows"][0]["ticker"] = "OTHER"
        else:
            row["raw_coordinate_proof"]["status"] = "ADJUSTED"
        assert rule.classify_quote_key(row)["classification"] == "D"


def test_missing_authority_is_g_and_unapproved_defect_is_not_invented_e():
    for field in ("raw_coordinate_proof", "identity_proof", "known_real_defect_scope"):
        row = record()
        row[field] = None
        assert rule.classify_quote_key(row)["classification"] == "G"
    row = record()
    row["known_real_defect_flags"] = [dict(reason="UNAPPROVED_CLAIM", source_ref=ref("c", "other"))]
    result = rule.classify_quote_key(row)
    assert result["classification"] == "G"
    assert not any(x.startswith("KNOWN_REAL_QUOTE_DEFECT:") for x in result["blocking_flags"])
    row = record()
    row["quality_origins"] = []
    assert rule.classify_quote_key(row)["classification"] == "G"


def test_dated_mapping_must_cover_exact_half_open_interval():
    row = record()
    row["identity_proof"] = dict(kind="DATED_SECURITY_MAPPING", status="EXACT_UNIQUE",
                                ticker="S", sid="SID", start="2023-01-01",
                                end="2026-01-01", source_ref=ref())
    assert rule.classify_quote_key(row)["classification"] == "A"
    row["identity_proof"]["end"] = row["date"]
    assert rule.classify_quote_key(row)["classification"] == "D"


@pytest.mark.parametrize("field", ["held", "pnl", "score", "rank", "forecast", "future_account_state"])
def test_forbidden_outcome_or_decision_inputs_are_rejected_even_when_nested(field):
    row = record()
    row["identity_proof"][field] = 0
    fail(lambda: rule.classify_quote_key(row), "FORBIDDEN_QUOTE_CLASSIFICATION_INPUT")


def test_bad_keys_mask_and_forbidden_drive_fail_before_io():
    row = record("2026-01-01")
    fail(lambda: rule.classify_quote_key(row), "QUOTE_KEY_OUTSIDE_PRE2026_DOMAIN")
    row = record()
    row["masked"] = False
    fail(lambda: rule.classify_quote_key(row), "OLD_QUALITY_TRUE_POPULATION_REQUIRED")
    row = record()
    row["raw_rows"][0]["source_ref"]["path"] = "E:/not-accessed"
    fail(lambda: rule.classify_quote_key(row), "FORBIDDEN_SOURCE_DRIVE")
    fail(lambda: rule.classify_population([record(), record()]), "DUPLICATE_QUOTE_POPULATION_KEY")


def test_mask_binding_requires_full_old_population_and_exact_raw_cells():
    days = pd.to_datetime(["2023-01-03", "2023-01-04"])
    quality = np.array([[False, False], [False, True]])
    opens, closes = np.array([[10., 10.], [10., 12.]]), np.array([[11., 11.], [11., 99.]])
    decisions = rule.classify_population([record(ticker="S"), record(ticker="OUTSIDE")])
    mask, audit = rule.build_usable_a_mask(days, ("OTHER", "S"), quality, decisions,
                                          raw_open=opens, raw_close=closes)
    np.testing.assert_array_equal(mask, quality)
    assert not mask.flags.writeable and audit["covered_keys"] == 1
    assert audit["outside_runtime_keys"] == [dict(date="2023-01-04", ticker="OUTSIDE")]
    assert audit["original_quality_changed"] is False
    fail(lambda: rule.build_usable_a_mask(days, ("OTHER", "S"), quality, [],
                                          raw_open=opens, raw_close=closes),
         "OLD_QUALITY_POPULATION_COVERAGE_INCOMPLETE")
    bad = deepcopy(decisions)
    bad[1]["usable_for_research_execution"] = False
    fail(lambda: rule.build_usable_a_mask(days, ("OTHER", "S"), quality, bad,
                                          raw_open=opens, raw_close=closes),
         "QUOTE_DECISION_NOT_DERIVED_FROM_EVIDENCE")
    opens[1, 1] = 999.
    fail(lambda: rule.build_usable_a_mask(days, ("OTHER", "S"), quality, decisions,
                                          raw_open=opens, raw_close=closes),
         "A_RAW_VALUE_DOES_NOT_MATCH_ORIGINAL_MARKET_CELL")


def market():
    return engine.MarketArrays(pd.to_datetime(["2023-01-03", "2023-01-04", "2023-01-05"]),
        ["S"], np.array([[10.], [12.], [14.]]), np.array([[11.], [99.], [15.]]),
        quality=np.array([[False], [True], [False]]), adv=np.full((3, 1), 1e9))


def policy(j, ctx):
    weights = np.array([[.5]]) if j == 0 else np.zeros((1, 1))
    explicit = ctx.decision_mask if j == 0 else np.zeros((1, 1), bool)
    return engine.TargetDecision(weights, explicit)


def options():
    return dict(initial_cash=3000., max_weight=1., max_invested=1., capacity_fraction=None)


def compare_replays(left, right):
    for name in ("daily", "positions", "orders", "fills", "execution_results",
                 "contexts", "operational_actions"):
        pd.testing.assert_frame_equal(getattr(left, name), getattr(right, name), check_exact=True)
    np.testing.assert_array_equal(left.final_units, right.final_units)
    np.testing.assert_array_equal(left.final_cash, right.final_cash)
    assert {k: right.audit[k] for k in left.audit} == left.audit
    assert set(right.audit) - set(left.audit) <= {rule.PROOF_AUDIT_KEY}
    assert right.audit.get(rule.PROOF_AUDIT_KEY, 0.) <= rule.EXECUTION_IDENTITY_TOL_USD
    assert left.metadata == right.metadata


def test_no_a_projection_is_bitwise_equivalent_to_original_defaults():
    data = market()
    unchanged = data.quality.tobytes()
    projected, receipt = rule.compile_execution_only_run_many(np.zeros((3, 1), bool))
    original = engine.run_many(data, ["synthetic"], policy, **options())
    same = projected(data, ["synthetic"], policy, **options())
    compare_replays(original, same)
    assert data.quality.tobytes() == unchanged
    assert receipt["replaced_pending_loads"] == 7
    assert receipt["normalized_reverse_projection_exact"] is True


def test_a_executes_only_original_pending_raw_open_and_keeps_old_close_decision_marks():
    data = market()
    original_bytes = tuple(a.tobytes() for a in (data.open, data.close, data.quality))
    mask = np.array([[False], [True], [False]])
    projected, _ = rule.compile_execution_only_run_many(mask)
    contexts = []
    def observed(j, ctx):
        contexts.append(ctx)
        return policy(j, ctx)
    replay = projected(data, ["synthetic"], observed, **options())
    fill = replay.fills.iloc[0]
    assert fill.signal_date == data.dates[0] and fill.execution_date == data.dates[1]
    assert fill.price == 12. and fill.cost_bps == 10.
    assert fill.index_units * fill.price == pytest.approx(fill.notional)
    assert fill.transaction_cost == pytest.approx(fill.notional * .001)
    day_positions = replay.positions.loc[replay.positions.date.eq(data.dates[1])]
    assert day_positions.mark.tolist() == [12.]  # Original purchase-open initialization.
    assert day_positions.mark_source.tolist() == ["open"]  # Not new raw Close=99.
    ctx = contexts[1]
    assert ctx.decision_mask.tolist() == [[False]] and ctx.reserved_mask.tolist() == [[True]]
    assert ctx.buy_allowed.tolist() == [[False]]
    assert ctx.nav[0] == pytest.approx(ctx.cash[0] + ctx.current_units[0, 0] * 12.)
    snapshot = rule.outcome_raw_close_values(ctx.current_units, data.close[1],
        np.array([False]), mask[1], data.row_present[1])
    assert snapshot[0, 0] == pytest.approx(ctx.current_units[0, 0] * 99.)
    assert ctx.nav[0] != pytest.approx(ctx.cash[0] + snapshot[0, 0])
    assert tuple(a.tobytes() for a in (data.open, data.close, data.quality)) == original_bytes


def test_non_a_order_still_rejects_and_does_not_gain_execution_authority():
    projected, _ = rule.compile_execution_only_run_many(np.zeros((3, 1), bool))
    replay = projected(market(), ["synthetic"], policy, **options())
    assert replay.fills.empty
    assert "PRICE_QUALITY_UNCERTIFIED" in set(replay.execution_results.reason)


def test_same_actual_prefix_keeps_all_old_policy_context_and_outputs():
    data = market()
    mask = np.array([[False], [True], [False]])
    projected, _ = rule.compile_execution_only_run_many(mask)
    observed = [[], []]
    outputs = [[], []]
    def keep(which):
        def callback(j, ctx):
            observed[which].append(ctx)
            output = engine.TargetDecision(np.zeros((1, 1)), np.zeros((1, 1), bool))
            outputs[which].append(output)
            return output
        return callback
    kwargs = dict(initial_cash=100., initial_units=np.array([10.]),
                  max_weight=1., max_invested=1., capacity_fraction=None)
    original = engine.run_many(data, ["synthetic"], keep(0), **kwargs)
    same_prefix = projected(data, ["synthetic"], keep(1), **kwargs)
    compare_replays(original, same_prefix)
    fields = ("current_units", "current_weights", "cash", "cash_weight", "nav",
              "reserved_mask", "reserved_weight", "reserved_slots",
              "available_budget", "available_slots", "buy_allowed",
              "sell_restricted", "input_present", "decision_mask", "operational_mask")
    for left, right, out_left, out_right in zip(observed[0], observed[1], outputs[0], outputs[1]):
        for field in fields:
            np.testing.assert_equal(getattr(left, field), getattr(right, field))
        np.testing.assert_array_equal(out_left.weights, out_right.weights)
        np.testing.assert_array_equal(out_left.explicit_mask, out_right.explicit_mask)


def original_ast():
    raw = Path(engine.__file__).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == rule.ENGINE_SHA256
    return next(n for n in ast.parse(raw.decode("utf-8-sig")).body
                if isinstance(n, ast.FunctionDef) and n.name == "run_many")


def test_projector_composes_with_existing_outside_edits_and_reverses_exactly():
    node = original_ast()
    loop = next(n for n in node.body if isinstance(n, ast.For) and ast.unparse(n.target) == "(di, date)")
    loop.body.insert(0, ast.parse("units = units").body[0])  # Synthetic existing lifecycle hook.
    before = ast.dump(node, include_attributes=False)
    projected, receipt = rule.project_pending_execution_ast(node, rule.ENGINE_SHA256)
    assert ast.dump(node, include_attributes=False) == before
    assert receipt["normalized_reverse_projection_exact"]
    assert receipt["original_input_function_ast_sha256"] == receipt["reverse_projected_function_ast_sha256"]
    assert receipt["projected_function_ast_sha256"] != receipt["original_input_function_ast_sha256"]
    assert sum(isinstance(n, ast.Name) and n.id == "execution_valid_open" and
               isinstance(n.ctx, ast.Load) for n in ast.walk(projected)) == 8  # Seven replacements plus proof input.


def test_projector_rejects_source_or_pending_edits_and_malformed_mask():
    node = original_ast()
    fail(lambda: rule.project_pending_execution_ast(node, "a" * 64),
         "IMMUTABLE_COMMON_ENGINE_SOURCE_CHANGED")
    loop = next(n for n in node.body if isinstance(n, ast.For) and ast.unparse(n.target) == "(di, date)")
    pending = next(n for n in loop.body if isinstance(n, ast.If) and ast.unparse(n.test) == "pending is not None")
    pending.body.append(ast.Pass())
    fail(lambda: rule.project_pending_execution_ast(node, rule.ENGINE_SHA256),
         "ORIGINAL_PENDING_BLOCK_AST_CHANGED")
    fail(lambda: rule.compile_execution_only_run_many(np.zeros((3, 1), int)),
         "EXACT_BOOLEAN_EXECUTION_A_MASK_REQUIRED")
    callback, _ = rule.compile_execution_only_run_many(np.zeros((1, 1), bool))
    fail(lambda: callback(market(), ["synthetic"], policy, **options()),
         "EXACT_EXECUTION_A_MASK_SHAPE_REQUIRED")


def test_legacy_mixed_mark_residual_is_preserved_beside_raw_execution_cash_identities():
    data = engine.MarketArrays(pd.to_datetime(["2023-01-03", "2023-01-04"]), ["S"],
        np.array([[10.], [12.]]), np.array([[10.], [13.]]),
        quality=np.array([[False], [True]]))
    projected, _ = rule.compile_execution_only_run_many(np.array([[False], [True]]))
    def exit_target(j, ctx):
        return engine.TargetDecision(np.zeros((1, 1)), ctx.decision_mask)
    replay = projected(data, ["synthetic"], exit_target, initial_cash=100.,
        initial_units=np.array([10.]), cost_bps=0., max_weight=1.,
        max_invested=1., capacity_fraction=None)
    fill = replay.fills.iloc[0]
    assert fill.side == "SELL" and fill.price == 12. and fill.notional == pytest.approx(100.)
    assert fill.index_units * fill.price == pytest.approx(fill.notional)
    assert replay.final_cash[0] - 100. == pytest.approx(fill.notional - fill.transaction_cost)
    last = replay.daily.iloc[-1]
    assert last.cash_flow_identity_error == pytest.approx(0.)
    assert last.cost_identity_error == pytest.approx(0.)
    assert last.open_self_finance_error == pytest.approx(100. / 6.)
    assert replay.audit["self_finance_error_max"] == pytest.approx(100. / 6.)
    assert replay.audit[rule.PROOF_AUDIT_KEY] < rule.EXECUTION_IDENTITY_TOL_USD


def test_independent_outcome_close_never_fills_missing_or_non_a_prices():
    units = np.array([[2., 0., 3.]])
    close = np.array([11., np.nan, 13.])
    result = rule.outcome_raw_close_values(units, close,
        np.array([True, False, False]), np.array([False, False, False]),
        np.array([True, False, True]))
    assert result[0, 0] == 22. and result[0, 1] == 0. and np.isnan(result[0, 2])
    assert not result.flags.writeable
    np.testing.assert_array_equal(units, [[2., 0., 3.]])


def proof_fixture():
    return dict(units_before=np.array([[2.]]), cash_before=np.array([20.]),
        units_after=np.array([[3.]]), cash_after=np.array([7.988]),
        execution_open=np.array([12.]), row_present=np.array([True]),
        execution_valid_open=np.array([True]), buy_quantity=np.array([[1.]]),
        sell_quantity=np.array([[0.]]), buy_notional=np.array([[12.]]),
        sell_notional=np.array([[0.]]), buy_cost=np.array([[.012]]),
        sell_cost=np.array([[0.]]), fees=np.array([.012]), rate=.001)


@pytest.mark.parametrize("field", ["cash_after", "units_after", "buy_cost",
                                   "buy_quantity", "buy_notional", "fees"])
def test_independent_execution_proof_detects_corrupted_cash_quantity_and_cost(field):
    inputs = proof_fixture()
    assert rule.execution_coordinate_proof(**inputs)["identity_error"][0] < 1e-10
    inputs[field] = inputs[field] + .1
    assert rule.execution_coordinate_proof(**inputs)["identity_error"][0] > rule.EXECUTION_IDENTITY_TOL_USD


@pytest.mark.parametrize("field,value", [
    ("execution_open", np.array([np.nan])), ("execution_open", np.array([0.])),
    ("row_present", np.array([False])), ("execution_valid_open", np.array([False])),
    ("units_after", np.array([[np.nan]])), ("buy_cost", np.array([[-.1]])),
])
def test_execution_proof_nonfinite_and_invalid_traded_cells_fail_closed(field, value):
    inputs = proof_fixture()
    inputs[field] = value
    assert np.isinf(rule.execution_coordinate_proof(**inputs)["identity_error"][0])


@pytest.mark.parametrize("field", ["cash_after", "units_after", "buy_cost"])
def test_projected_terminal_gate_catches_corrupted_independent_proof(field):
    mask = np.array([[False], [True], [False]])
    node, _ = rule.project_pending_execution_ast(original_ast(), rule.ENGINE_SHA256)
    namespace = dict(vars(engine))
    namespace[rule.USABLE_GLOBAL] = mask
    def corrupt(*args):
        inputs = dict(zip(proof_fixture(), args))
        inputs[field] = inputs[field] + .1
        return rule.execution_coordinate_proof(**inputs)
    namespace[rule.PROOF_GLOBAL] = corrupt
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 "synthetic://corrupted-proof", "exec"), namespace)
    with pytest.raises(AssertionError, match="independent vectorized account audit failed"):
        namespace["run_many"](market(), ["synthetic"], policy, **options())


def test_execution_coordinate_proof_is_separate_from_legacy_ledgers_and_stale_marks():
    data = market()
    chunks = []
    projected, receipt = rule.compile_execution_only_run_many(np.array([[False], [True], [False]]))
    replay = projected(data, ["synthetic"], policy, ledger_callback=lambda n, f: chunks.append((n, f)), **options())
    proof = pd.concat([f for n, f in chunks if n == "execution_coordinate_proof"])
    assert len(proof) == 2 and proof.identity_error.max() < rule.EXECUTION_IDENTITY_TOL_USD
    assert replay.audit["self_finance_error_max"] > 1.
    assert replay.audit[rule.PROOF_AUDIT_KEY] < rule.EXECUTION_IDENTITY_TOL_USD
    assert "identity_error" not in replay.daily
    assert receipt["accounting_comparator"]["legacy_self_finance_diagnostic_retained"]
    assert receipt["accounting_comparator"]["terminal_replacement_count"] == 1


def test_projector_rejects_modified_original_terminal_comparators():
    node = original_ast()
    gate = next(n for n in node.body if isinstance(n, ast.If) and
                any(isinstance(v, ast.Constant) and v.value == "self_finance_error_max" for v in ast.walk(n.test)))
    gate.test = ast.Constant(False)
    fail(lambda: rule.project_pending_execution_ast(node, rule.ENGINE_SHA256),
         "ORIGINAL_ACCOUNTING_COMPARATOR_ANCHOR_CHANGED")


def composed_entitlement_owner(mask, receipts):
    from scripts.research.a2.evaluation import continuous_research_account as owner
    # Reuse the existing guarded lifecycle factory, intercept only its final
    # AST compilation. The original owner and its source remain unchanged.
    actual_fix = ast.fix_missing_locations
    def composed_fix(tree):
        if isinstance(tree, ast.Module) and len(tree.body) == 1 and isinstance(tree.body[0], ast.FunctionDef) and tree.body[0].name == "run_many":
            projected, receipt = rule.project_pending_execution_ast(tree.body[0], rule.ENGINE_SHA256)
            receipts.append(receipt)
            return actual_fix(ast.Module(body=[projected], type_ignores=[]))
        return actual_fix(tree)
    ast_proxy = SimpleNamespace(**vars(ast))
    ast_proxy.fix_missing_locations = composed_fix
    engine_proxy = SimpleNamespace(**vars(engine))
    setattr(engine_proxy, rule.USABLE_GLOBAL, mask)
    setattr(engine_proxy, rule.PROOF_GLOBAL, rule.execution_coordinate_proof)
    factory_globals = dict(owner._engine_with_entitlement_hook.__globals__,
                           ast=ast_proxy, _common_engine=engine_proxy)
    factory = FunctionType(owner._engine_with_entitlement_hook.__code__,
                           factory_globals, owner._engine_with_entitlement_hook.__name__,
                           owner._engine_with_entitlement_hook.__defaults__,
                           owner._engine_with_entitlement_hook.__closure__)
    account_globals = dict(owner.run_continuous_account.__globals__,
                           _engine_with_entitlement_hook=factory)
    cloned = FunctionType(owner.run_continuous_account.__code__, account_globals,
                          owner.run_continuous_account.__name__,
                          owner.run_continuous_account.__defaults__,
                          owner.run_continuous_account.__closure__)
    cloned.__kwdefaults__ = dict(owner.run_continuous_account.__kwdefaults__ or {})
    return cloned


def entitlement_fixture():
    from scripts.v22.corporate_action_transition_r1 import (
        SourceBackedEntitlementEvent, RAW_OLD_SHARE_COORDINATE, USD_PER_RAW_OLD_SHARE)
    prices = np.array([[100.], [100.], [90.], [90.], [90.]])
    data = engine.MarketArrays(pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]),
        ["S"], prices, prices.copy(), adv=np.full_like(prices, 1e9))
    event = SourceBackedEntitlementEvent(event_id="div", action_type="CASH_DIVIDEND",
        old_security_id="secS", ticker="S", ex_date="2024-01-04",
        record_date="2024-01-04", pay_date="2024-01-06",
        available_at="2024-01-03 12:00:00+00:00", cash_per_old_share=10.,
        currency="USD", amount_unit=USD_PER_RAW_OLD_SHARE,
        quantity_coordinate=RAW_OLD_SHARE_COORDINATE, source_type="TIER2_LOCAL_CANONICAL",
        source_reference="synthetic://declared_dividend", source_fingerprint="c"*64)
    config = dict(base_currency="USD", initial_nav=3000, initial_cash=3000,
        initial_holdings=[], fractional_shares=True, integer_share_rounding=False,
        cash_interest=0, transaction_cost_bps=0, financing=False, borrowed_cash=False,
        long_only=True, max_positions=20, max_weight=1., max_invested=1., capacity_fraction=None)
    kwargs = dict(account_config=config, entitlement_enabled=True,
        entitlement_events=[event], entitlement_security_tickers={"secS":"S"},
        entitlement_source_binding=dict(status="SOURCE_BACKED_ENTITLEMENT_COVERAGE_BOUND",
            source_fingerprint="d"*64, event_fingerprints=[event.event_fingerprint],
            security_tickers={"secS":"S"}, quantity_coordinate=RAW_OLD_SHARE_COORDINATE))
    def rebalance(j, ctx):
        return engine.TargetDecision(np.ones_like(ctx.current_weights), ctx.decision_mask)
    return data, kwargs, rebalance


def test_actual_entitlement_enabled_factory_preserves_receivables_cash_and_no_a_defaults():
    from scripts.research.a2.evaluation import continuous_research_account as owner
    data, kwargs, rebalance = entitlement_fixture()
    receipts = []
    composed = composed_entitlement_owner(np.zeros(data.open.shape, bool), receipts)
    original = owner.run_continuous_account(data, ["synthetic"], rebalance, **kwargs)
    replay = composed(data, ["synthetic"], rebalance, **kwargs)
    # Existing owner metadata contains its original intermediate AST hash;
    # that hash is stable because composition happens at the final compile.
    compare_replays(original, replay)
    assert len(receipts) == 1 and receipts[0]["replaced_pending_loads"] == 7
    assert receipts[0]["normalized_reverse_projection_exact"]
    np.testing.assert_allclose(replay.daily.nav, 3000.)
    np.testing.assert_allclose(replay.daily.receivable_value_usd, [0, 0, 300, 300, 0])
    np.testing.assert_allclose(replay.daily.entitlement_cash_flow_usd, [0, 0, 0, 0, 300])
    assert replay.audit["actual_cash_flow_identity_error_max"] < 1e-8
    assert replay.audit[rule.PROOF_AUDIT_KEY] < rule.EXECUTION_IDENTITY_TOL_USD


def test_entitlement_enabled_factory_really_uses_a_execution_and_preserves_raw_translation():
    data, kwargs, rebalance = entitlement_fixture()
    data.quality[1, 0] = True
    data.close[1, 0] = 999.  # Deliberately forbidden decision Close on execution day.
    before = data.quality.tobytes()
    mask = np.zeros(data.open.shape, bool)
    mask[1, 0] = True
    receipts, streamed = [], []
    composed = composed_entitlement_owner(mask, receipts)
    replay = composed(data, ["synthetic"], rebalance,
                      ledger_callback=lambda n, f: streamed.append((n, f)), **kwargs)
    assert len(receipts) == 1
    fill = replay.fills.iloc[0]
    assert fill.execution_date == data.dates[1] and fill.price == 100.
    assert fill.fractional_shares * fill.price == pytest.approx(fill.notional)
    assert replay.audit["self_finance_error_max"] > 1.
    assert replay.audit[rule.PROOF_AUDIT_KEY] < rule.EXECUTION_IDENTITY_TOL_USD
    assert replay.audit["actual_cash_flow_identity_error_max"] < 1e-8
    assert data.quality.tobytes() == before
    assert any(n == "execution_coordinate_proof" for n, _ in streamed)
