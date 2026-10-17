"""Focused synthetic-only research-account child checks; no real input readers."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import numpy as np
import pandas as pd
import pytest
from scripts.research.a2.training import stateful_research_account as child
from scripts.research.a2.training import stateful_replay as replay
from scripts.research.a2.training import stateful_execution as execution


def candidate(name="RAW_s10", number=1):
    return dict(candidate_id=name, scientific_tuple_sha256=("%064x" % number),
        value_model="ridge", action="raw", control="none", gross="fixed", risk="diag20_reference",
        forecast="none", action_cost_mode="blind", target_role="shareholder5d", source_method_ids=["SYNTHETIC"],
        execution_friction=dict(kind="FIXED_ADVERSE_OPEN_SLIPPAGE", scenario_id="SYNTHETIC_10BPS",
            one_way_bps=10, fee_bps=0, benchmark="NEXT_RAW_OPEN", authority="HYPOTHETICAL_RESEARCH_SCENARIO"))


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    dates = pd.to_datetime(["2023-12-28", "2023-12-29", "2024-01-02", "2024-12-31", "2025-01-02", "2025-01-03"])
    names = [f"SYNTHETIC_{i:02d}" for i in range(20)]
    mask = np.ones((6, 20), dtype=bool)
    price = np.full((6, 20), 10.)
    market = replay.MarketArrays(dates, names, price.copy(), price.copy(), input_present=mask.copy(),
        new_buy_eligible=mask.copy(), signal_asof=[d.tz_localize("America/New_York") + pd.Timedelta(hours=16) for d in dates])
    c = candidate()
    packets = {"ridge": dict(mu=np.full((6, 20), .04), sigma=np.full(6, .001),
        lineage=np.full(6, "SYNTHETIC_ONLY"))}
    account = dict(base_currency="USD", initial_nav=3000., initial_cash=3000., initial_holdings=[],
        fractional_shares=True, integer_share_rounding=False, transaction_cost_bps=0., cash_interest=0.,
        financing=False, borrowed_cash=False, long_only=True, max_weight=1., max_positions=20,
        max_invested=1., capacity_fraction=None)
    result, frames = replay.execute_market(market, [c], packets, mask, mask.copy(), np.full(mask.shape, .03),
        account, stock_present=mask.copy(), raw_selector_present=mask.copy(), execution_friction=c["execution_friction"])
    result.daily["receivable_value_usd"] = 0.
    result.daily["actual_cash_flow_identity_error"] = 0.
    result.entitlements = pd.DataFrame(columns=["path_id", "event_id", "phase"])
    result.final_state["entitlement_states"] = (SimpleNamespace(
        blocked_events=(), ex_quantities=(), paid_event_ids=(), receivables=()),)
    result.final_state["receivable_value_usd"] = np.zeros(1)
    records = [dict(sid=f"SID_{i}", ticker=name, start="2023-01-01", end="2026-01-01",
        coordinate="RAW_ACTUAL_SHARE") for i, name in enumerate(names)]
    proof_ref = write(tmp_path / "security_map.json", dict(status="FROZEN_RESEARCH_SECURITY_ACCOUNTING_MAPPING",
        role="ACCOUNTING_MAPPING_ONLY", coordinate="RAW_ACTUAL_SHARE", decision_information_unchanged=True,
        records=records))
    monkeypatch.setattr(child, "reference", lambda ref, **_: Path(ref["path"]))
    binding = dict(decision_information_unchanged=True, quote_coordinate_verified=True,
        security_accounting_continuity_verified=True, security_tickers={f"SID_{i}": name for i, name in enumerate(names)},
        security_accounting_records=records, security_accounting_mapping_ref=proof_ref,
        MKFG_terminal_event_fingerprint="f" * 64, entitlement_catalogue_fingerprints=["f" * 64])
    result.metadata.update(terminal_lifecycle_enabled=True,
        terminal_settlement_qualified_by_path={"RAW_s10": True}, terminal_events=[dict(
            event_id="SYNTHETIC_MKFG_UNHELD", ticker="MKFG", old_security_id="SYNTHETIC_MKFG_SID",
            event_fingerprint="f" * 64, effective_date="2024-01-02", settlement_authority_bound=False)])
    frames["daily"] = child.add_dual_nav(result)
    return result, frames, market, binding, c


def gates(synthetic):
    result, _, market, binding, _ = synthetic
    return child.integrity_gates(result, "RAW_s10", binding, decision_unchanged=True,
        custody_verified=True, market=market, expected_sessions=6,
        expected_year_sessions={2023: 2, 2024: 2, 2025: 2})


def test_ten_integrity_groups_use_existing_engine(synthetic):
    state = gates(synthetic)
    assert set(state["groups"]) == set(child.GATES)
    assert state["all_passed"] is True
    assert state["strict_PIT_promotion_eligible"] is False
    assert state["production_qualified"] is False


@pytest.mark.parametrize("error,expected", [
    ("cash_flow_identity_error", "CASH_IDENTITY"),
    ("actual_cash_flow_identity_error", "CASH_IDENTITY"),
    ("nav_identity_error", "DOUBLE_ENTRY_ACCOUNTING"),
    ("cost_identity_error", "DOUBLE_ENTRY_ACCOUNTING"),
    ("open_self_finance_error", "DOUBLE_ENTRY_ACCOUNTING")])
def test_actual_identity_error_blocks_even_when_binding_flags_true(synthetic, error, expected):
    synthetic[0].daily.loc[0, error] = .1
    assert gates(synthetic)["groups"][expected] is False


def test_fill_raw_coordinate_checked_against_market(synthetic):
    synthetic[0].fills.loc[synthetic[0].fills.index[0], "price"] *= 2
    assert gates(synthetic)["groups"]["EXECUTION_QUOTE_COORDINATE"] is False


def test_unmapped_actual_position_blocks_accounting_continuity(synthetic):
    synthetic[3]["security_accounting_records"] = []
    assert gates(synthetic)["groups"]["SECURITY_ACCOUNTING_CONTINUITY"] is False


def test_annual_reset_and_unknown_exception_block(synthetic):
    synthetic[0].metadata["annual_reset"] = True
    synthetic[0].accounting_exceptions = pd.DataFrame([dict(path_id="RAW_s10", reason="INVENTED_CASH")])
    state = gates(synthetic)["groups"]
    assert state["CONTINUOUS_YEAR_BOUNDARY"] is False
    assert state["DOUBLE_ENTRY_ACCOUNTING"] is False


def test_unknown_settlement_does_not_become_cash_or_strict_pass(synthetic, monkeypatch):
    result = synthetic[0]
    old = replay.qualification_checks
    def checks(*args):
        value = old(*args)
        value.update(terminal_identity_correct=True, terminal_settlement_qualified=False)
        return value
    monkeypatch.setattr(replay, "qualification_checks", checks)
    result.daily["engine_certified_nav"] += 500.
    result.daily["nav"] += 500.
    result.daily["receivable_value_usd"] = 500.
    result.final_state["receivable_value_usd"] = np.array([500.])
    result.final_state["entitlement_states"] = (SimpleNamespace(blocked_events=(),
        ex_quantities=(("SYNTHETIC_TERMINAL", 100.),), paid_event_ids=(),
        receivables=(SimpleNamespace(event_id="SYNTHETIC_TERMINAL", entitled_raw_shares=100., amount_usd=500.),)),)
    result.daily["certified_nav"] = np.nan
    result.daily["accounting_qualified"] = False
    before_cash = result.daily.cash.copy()
    result.accounting_exceptions = pd.DataFrame([dict(path_id="RAW_s10", reason="TERMINAL_SETTLEMENT_AUTHORITY_MISSING")])
    dual = child.add_dual_nav(result)
    assert dual.TOTAL_ECONOMIC_NAV.sub(dual.LIQUID_NAV).eq(500.).all()
    assert dual.cash.equals(before_cash) and dual.certified_nav.isna().all()
    state = gates(synthetic)
    assert state["all_passed"] is True and state["terminal_settlement_qualified"] is False
    assert result.daily.certified_nav.isna().all()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return dict(path=str(path), sha256=replay.sha(path))


@pytest.mark.parametrize("group", child.GATES)
@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_baseline_ten_literal_groups_reject_non_true(tmp_path, monkeypatch, group, value):
    supplied = dict.fromkeys(child.GATES, True); supplied[group] = value
    auth = dict(contract_ref=dict(sha256="a" * 64))
    ref = write(tmp_path / "audit.json", dict(status="RESEARCH_CONTINUOUS_PRE2026_REPLAY_COMPLETE",
        research_contract_sha256="a" * 64, research_integrity={"RAW_s10": dict(groups=supplied)}))
    monkeypatch.setattr(child, "_history", lambda _: [dict(event="ACCOUNT_PATH_COMPLETE",
        candidate_id="RAW_s10", audit_path=ref["path"], audit_sha256=ref["sha256"])])
    state = child.baseline_gate(tmp_path, auth)
    assert not state["all_passed"] and state["groups"][group] is False


@pytest.mark.parametrize("group", child.GATES)
def test_baseline_missing_group_never_passes(tmp_path, monkeypatch, group):
    supplied = dict.fromkeys(child.GATES, True); del supplied[group]
    ref = write(tmp_path / "audit.json", dict(status="RESEARCH_CONTINUOUS_PRE2026_REPLAY_COMPLETE",
        research_contract_sha256="a" * 64, research_integrity={"RAW_s10": dict(groups=supplied)}))
    monkeypatch.setattr(child, "_history", lambda _: [dict(event="ACCOUNT_PATH_COMPLETE",
        candidate_id="RAW_s10", audit_path=ref["path"], audit_sha256=ref["sha256"])])
    assert child.baseline_gate(tmp_path, dict(contract_ref=dict(sha256="a" * 64)))["all_passed"] is False


def test_gate_all_true_and_failed_attempt_are_distinct(tmp_path, monkeypatch):
    auth = dict(contract_ref=dict(sha256="a" * 64))
    ref = write(tmp_path / "audit.json", dict(status="RESEARCH_CONTINUOUS_PRE2026_REPLAY_COMPLETE",
        research_contract_sha256="a" * 64, research_integrity={"RAW_s10": dict(groups=dict.fromkeys(child.GATES, True))}))
    event = dict(event="ACCOUNT_PATH_COMPLETE", candidate_id="RAW_s10",
        audit_path=ref["path"], audit_sha256=ref["sha256"])
    monkeypatch.setattr(child, "_history", lambda _: [event])
    assert child.baseline_gate(tmp_path, auth)["decision"] == "ACTIVATE_FROZEN37_THEN_BREADTH19"
    event["event"] = "ACCOUNT_PATH_FAILED"
    state = child.baseline_gate(tmp_path, auth)
    assert not state["all_passed"] and state["attempt_state"] == "ACCOUNT_PATH_FAILED"


def test_worker_requires_parent_token_source_namespace_and_config(tmp_path, monkeypatch):
    write(tmp_path / "run_config.json", {})
    lock = dict(token="SYNTHETIC_TOKEN", namespace=child.NAMESPACE,
        controller_source_sha256=replay.sha(Path(execution.__file__)),
        run_config_sha256=replay.sha(tmp_path / "run_config.json"))
    write(tmp_path / "CONTINUATION_LOCK.json", lock)
    monkeypatch.setenv(execution.CONTINUATION_LOCK_ENV, "SYNTHETIC_TOKEN")
    child.worker_guard(tmp_path, {}, {})
    for field in tuple(lock):
        wrong = {**lock, field: "WRONG"}
        write(tmp_path / "CONTINUATION_LOCK.json", wrong)
        with pytest.raises(ValueError, match="LOCK_MISMATCH"):
            child.worker_guard(tmp_path, {}, {})


def test_budget_preserves_failed_attempt_and_strict_attempt_zero(tmp_path, monkeypatch):
    c = candidate()
    event = dict(namespace=child.NAMESPACE, continuation=True, path_units=1,
        candidate_id=c["candidate_id"], scientific_tuple_sha256=c["scientific_tuple_sha256"])
    journal = [dict(event, event="ACCOUNT_PATH_ATTEMPT_STARTED"), dict(event, event="ACCOUNT_PATH_FAILED")]
    monkeypatch.setattr(child, "_history", lambda _: journal)
    state = child.history_budget(tmp_path, [c])
    assert state["failed"] == 1 and state["new_account_path_attempts"] == 1
    assert state["strict_baseline_attempts_consumed"] == 0 and state["scientific_retry"] == 0
    journal.append(dict(event, event="ACCOUNT_PATH_ATTEMPT_STARTED"))
    with pytest.raises(ValueError, match="CAP_OR_RETRY"):
        child.history_budget(tmp_path, [c])


def test_decision_digest_detects_input_mutation(synthetic):
    market = synthetic[2]; mask = market.input_present.copy()
    before = child._decision_digest(market, (mask,))
    mask[0, 0] = False
    assert before != child._decision_digest(market, (mask,))


def test_dual_nav_forbids_even_synthetic_2026_as_account_window(synthetic):
    synthetic[0].daily.loc[0, "date"] = pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError, match="PRE2026"):
        child.add_dual_nav(synthetic[0])


def test_annual_returns_use_continuous_previous_year_end(synthetic):
    frames = synthetic[1]; daily = frames["daily"]
    daily["TOTAL_ECONOMIC_NAV"] = [3000., 3300., 3200., 3630., 3600., 3993.]
    daily["LIQUID_NAV"] = daily.TOTAL_ECONOMIC_NAV
    result = child.path_metrics(synthetic[4], frames)
    assert all(np.isclose(v, .1) for v in result["annual_return"].values())
    assert np.isclose(result["cumulative_return"], .331)
    assert result["REPLACE_count"] is None


def test_frozen_paired_comparison_keeps_family220_and_no_winner(synthetic):
    daily = synthetic[1]["daily"]
    state = child.paired_effect(daily, daily)
    assert state["cumulative_net_log_difference"] == 0.
    assert state["HAC_lag"] == 20 and state["Bonferroni_family"] == 220
    assert state["selection_performed"] is False


@pytest.mark.parametrize("key,value", [
    ("scientific_identity", "STRICT"), ("task_id", "OTHER"), ("clock_role", "ASSUMED"),
    ("strict_PIT_promotion_eligible", True), ("production_qualified", True),
    ("frozen_contract_sha256", "b" * 64)])
def test_research_authority_cannot_promote_or_rebind(key, value):
    authority = dict(scientific_identity=child.NAMESPACE, task_id=child.TASK_ID,
        clock_role="RECONSTRUCTED_REALIZED_EVENT", frozen_contract_sha256="a" * 64,
        strict_PIT_promotion_eligible=False, production_qualified=False, event_fingerprints=["c" * 64])
    child.validate_authority(authority, "a" * 64, ["c" * 64])
    authority[key] = value
    with pytest.raises(ValueError):
        child.validate_authority(authority, "a" * 64, ["c" * 64])


def test_capability_is_metadata_and_does_not_claim_admission():
    result = child.runtime_capability()
    assert result["real_execution_admitted"] is False
    assert isinstance(result["missing"], list)


def test_missing_owner_capability_stops_before_attempt_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(child, "contract", lambda _: (tmp_path, {}, {}, [candidate()]))
    monkeypatch.setattr(child, "worker_guard", lambda *_: None)
    monkeypatch.setattr(child, "runtime_capability", lambda: dict(available=False))
    with pytest.raises(ValueError, match="OWNER_EXTENSION"):
        child.run_batch(tmp_path, ["RAW_s10"])
    assert not (tmp_path / "ACCOUNT_PATH_LOG.jsonl").exists()


def test_final_receivable_claims_must_match_owner_and_daily(synthetic):
    result = synthetic[0]
    result.final_state["receivable_value_usd"] = np.array([1.])
    assert gates(synthetic)["groups"]["RECEIVABLE_ACCOUNTING"] is False


def test_final_claim_sum_must_match_owner_even_if_daily_equal(synthetic):
    result = synthetic[0]
    result.final_state["entitlement_states"] = (SimpleNamespace(blocked_events=(), paid_event_ids=(),
        ex_quantities=(("SYNTHETIC_CLAIM", 1.),), receivables=(SimpleNamespace(
            event_id="SYNTHETIC_CLAIM", entitled_raw_shares=1., amount_usd=1.),)),)
    assert gates(synthetic)["groups"]["RECEIVABLE_ACCOUNTING"] is False


def test_liquid_annual_return_keeps_previous_year_cash_receivable_boundary(synthetic):
    frames = synthetic[1]
    frames["daily"]["TOTAL_ECONOMIC_NAV"] = [3000., 3300., 3200., 3630., 3600., 3993.]
    frames["daily"]["LIQUID_NAV"] = [3000., 3000., 2800., 3300., 3200., 3630.]
    value = child.path_metrics(synthetic[4], frames)
    assert np.allclose(list(value["annual_return_liquid"].values()), [0., .1, .1])
    assert np.isclose(value["cumulative_return_liquid"], .21)
    assert value["MaxDD_liquid"] < 0.
    assert value["holding_duration"]["open_spells_right_censored"] is True


def test_authority_seventh_field_schema_rejects_unrecognized_promotions():
    authority = dict(scientific_identity=child.NAMESPACE, task_id=child.TASK_ID,
        clock_role="RECONSTRUCTED_REALIZED_EVENT", frozen_contract_sha256="a" * 64,
        strict_PIT_promotion_eligible=False, production_qualified=False, event_fingerprints=[])
    child.validate_authority(authority, "a" * 64)
    with pytest.raises(ValueError, match="AUTHORITY_REQUIRED"):
        child.validate_authority(dict(authority, relaxed_decision_PIT=True), "a" * 64)


def test_inherited_hac_is_one_sided_family220():
    from scipy.stats import norm
    effect = child._hac_effect(np.linspace(-.001, .003, 60))
    assert effect["one_sided_normal_critical"] == norm.ppf(1. - .05 / 220.)
    assert effect["one_sided_p"] == norm.sf(effect["statistic"])
    assert effect["adjusted_p"] == min(1., 220. * effect["one_sided_p"])
    assert effect["selection_performed"] is False


def test_frozen_breadth_contrasts_exact_terms_secondary_and_missing(synthetic):
    daily = synthetic[1]["daily"]
    spec = [dict(kind="MAIN_EFFECT", candidate="A", reference="B"),
        dict(kind="LEARNER_X_RISK_GROSS_BUNDLE_DID", terms=[[1, "A"], [-1, "B"], [-1, "C"], [1, "D"]],
             single_risk_or_gross_attribution=False),
        dict(kind="WITHIN_MLP_CONTROL", terms=[[1, "A"], [-1, "B"]],
             secondary_interaction_terms=[[1, "A"], [-1, "B"], [-1, "C"], [1, "D"]]),
        dict(kind="MAIN_EFFECT", candidate="UNAVAILABLE", reference="B")]
    result = child.frozen_contrasts({name: daily for name in "ABCD"}, spec)
    assert len(result) == 5 and result[-1]["status"] == "NOT_TESTABLE_MISSING_QUALIFIED_PATHS"
    assert result[-1]["missing"] == ["UNAVAILABLE"]
    assert all(row["effect"]["cumulative_net_log_difference"] == 0. for row in result[:-1])
    assert result[1]["terms"] == spec[1]["terms"]
    assert result[3]["role"] == "SECONDARY_INTERACTION"
    assert result[1]["specification"]["single_risk_or_gross_attribution"] is False
    assert all(row["selection_performed"] is False for row in result)


def test_frozen_contrast_never_trims_disagreeing_calendars(synthetic):
    daily = synthetic[1]["daily"]
    with pytest.raises(ValueError, match="CALENDAR_MISMATCH"):
        child.frozen_contrasts({"A": daily, "B": daily.iloc[1:]},
            [dict(kind="MAIN_EFFECT", candidate="A", reference="B")])


@pytest.mark.parametrize("research_namespace", child.NAMESPACES)
def test_nested_phase0_contract_matches_frozen_root_schema(tmp_path, monkeypatch, research_namespace):
    run = tmp_path / "run"; run.mkdir(); parent = tmp_path / "parent"
    refs = {key: dict(path=str(tmp_path / (key + ".json")), sha256="a" * 64)
        for key in ("contract_ref", "firewall_ref", "candidates_ref", "frozen37_manifest_ref",
                    "original_catalogue_ref", "breadth_design_ref", "source_binding_ref")}
    scientific = dict(scientific_identity=child.NAMESPACE, task_id=child.TASK_ID,
        research_integrity_gates=list(child.GATES), annual_reset=False, **{"2026_locked": True},
        full_sessions=752, continuous_years=[2023, 2024, 2025], strict_PIT_promotion_eligible=False,
        production_qualified=False, budget=dict(max_new_fit_before_R9=0, planned_account_paths=57,
            scientific_retry=0), metrics=dict(HAC_lag=20, family_alpha=.05, Bonferroni_multiple_family_upper=220,
            primary="PAIRED_DAILY_NET_LOG_RETURN_DIFFERENCE_TOTAL_ECONOMIC_NAV_VS_RAW_s10"),
        **{k: refs[k] for k in ("firewall_ref", "candidates_ref", "frozen37_manifest_ref",
                               "original_catalogue_ref", "breadth_design_ref")})
    firewall = dict(decision_information_unchanged=True, accounting_mapping_only=True,
        outcome_no_decision_feedback=True, time={"2026_locked": True})
    binding = dict(status="FROZEN_RESEARCH_ACCOUNT_SOURCE_BINDING", quote_coordinate="RAW_ACTUAL_SHARE",
        future_adjusted_prices=False, decision_information_unchanged=True, accounting_mapping_only=True,
        quote_coordinate_verified=True, security_accounting_continuity_verified=True,
        decision_input_manifest_ref=dict(path=str(parent / "input_manifest.json"), sha256="b" * 64),
        MKFG_terminal_event_fingerprint="f" * 64,
        security_accounting_records=[dict(sid="S", ticker="S", start="2023-01-01", end="2026-01-01",
                                         coordinate="RAW_ACTUAL_SHARE")],
        **{k: refs["firewall_ref"] for k in ("cash_source_bundle", "quote_coordinate_evidence_ref",
            "decision_firewall_proof_ref")})
    binding["security_accounting_mapping_ref"] = write(tmp_path / "security_proof.json",
        dict(status="FROZEN_RESEARCH_SECURITY_ACCOUNTING_MAPPING", role="ACCOUNTING_MAPPING_ONLY",
            coordinate="RAW_ACTUAL_SHARE", decision_information_unchanged=True,
            records=binding["security_accounting_records"]))
    for key, value in (("contract_ref", scientific), ("firewall_ref", firewall),
                       ("source_binding_ref", binding), ("candidates_ref", [])):
        Path(refs[key]["path"]).write_text(json.dumps(value), encoding="utf-8")
    required = child.source_closure_paths()
    authority = dict(scientific_identity=child.NAMESPACE, task_id=child.TASK_ID,
        clock_role="RECONSTRUCTED_REALIZED_EVENT", frozen_contract_sha256="a" * 64,
        strict_PIT_promotion_eligible=False, production_qualified=False, event_fingerprints=["f" * 64])
    auth = dict(refs, status="FROZEN", namespace=child.NAMESPACE, max_new_fit_units=0,
        max_new_account_paths=57, baseline_candidate_id="RAW_s10", research_account_authority=authority,
        source_pins={str(p.resolve()): "b" * 64 for p in required})
    if research_namespace in child.QUOTE_DESCENDANTS:
        from scripts.research.a2.training import stateful_research_quote_domain as quote
        parent_contract_ref = write(tmp_path / "synthetic_parent_science.json", deepcopy(scientific))
        quote_ref = dict(path=str(tmp_path / "synthetic_quote_domain.json"), sha256="d" * 64)
        scientific.update(scientific_identity=child.QUOTE_NAMESPACE, task_id=child.QUOTE_TASK_ID, certified_market_quote_authority=False,
            parent_account_contract_ref=parent_contract_ref, quote_domain_ref=quote_ref)
        Path(refs["contract_ref"]["path"]).write_text(json.dumps(scientific), encoding="utf-8")
        authority["frozen_contract_sha256"] = parent_contract_ref["sha256"]
        auth.update(namespace=child.QUOTE_NAMESPACE, certified_market_quote_authority=False, parent_account_contract_ref=parent_contract_ref,
            quote_domain_ref=quote_ref, source_pins={str(p.resolve()): "b" * 64
                for p in child.source_closure_paths(child.QUOTE_NAMESPACE)})
        monkeypatch.setattr(quote, "load_frozen_domain", lambda ref: dict(decisions=[]))
        if research_namespace == child.SESSION_NAMESPACE:
            from scripts.research.a2.evaluation import continuous_research_account as shared
            convention_ref = write(tmp_path / "synthetic_session_freeze.json", {})
            extra = dict(session_boundary_rule_ref=refs["firewall_ref"], session_boundary_population_ref=refs["candidates_ref"],
                parent_quote_contract_ref=write(tmp_path / "synthetic_quote_science.json", deepcopy(scientific)))
            scientific.update(scientific_identity=child.SESSION_NAMESPACE, task_id=child.SESSION_TASK_ID, **extra, **child.SESSION_FLAGS)
            auth.update(namespace=child.SESSION_NAMESPACE, research_ca_accounting_convention=convention_ref, **extra, **child.SESSION_FLAGS)
            Path(refs["contract_ref"]["path"]).write_text(json.dumps(scientific), encoding="utf-8")
            monkeypatch.setattr(child, "_quote_domain", lambda *args: dict(decisions=[]))
            monkeypatch.setattr(shared, "load_research_ca_accounting_convention", lambda ref:
                dict(contract_ref=refs["contract_ref"], rule_ref=extra["session_boundary_rule_ref"],
                     population_ref=extra["session_boundary_population_ref"]), raising=False)
    config = dict(phase="FROZEN", research_account=auth, training_cutoff_exclusive="2026-01-01",
        evaluation_years=[2023, 2024, 2025], capital_usd=3000, fractional_primary=True, parent_run_dir=str(parent))
    monkeypatch.setattr(child, "_roots", lambda: SimpleNamespace(backtest_root=tmp_path))
    monkeypatch.setattr(child.meta, "read_metadata", lambda *_: config)
    monkeypatch.setattr(child, "reference", lambda ref, **_: Path(ref["path"]))
    monkeypatch.setattr(child, "validate_candidates", lambda _, values: values)
    monkeypatch.setattr(child, "history_budget", lambda *_: {})
    assert child.contract(run)[2] == auth
    if research_namespace in child.QUOTE_DESCENDANTS:
        for field_owner in (auth, scientific):
            for illegal in (True, None, "false", 0):
                field_owner["certified_market_quote_authority"] = illegal
                Path(refs["contract_ref"]["path"]).write_text(json.dumps(scientific), encoding="utf-8")
                with pytest.raises(ValueError, match="QUOTE_CERTIFIED_AUTHORITY_FORBIDDEN"):
                    child.contract(run)
            field_owner["certified_market_quote_authority"] = False
            Path(refs["contract_ref"]["path"]).write_text(json.dumps(scientific), encoding="utf-8")
    scientific["metrics"]["Bonferroni_multiple_family_upper"] = 19
    Path(refs["contract_ref"]["path"]).write_text(json.dumps(scientific), encoding="utf-8")
    with pytest.raises(ValueError, match="PHASE0_CONTRACT_CHANGED"):
        child.contract(run)


def test_missing_terminal_identity_is_not_inferred_true(synthetic, monkeypatch):
    old = replay.qualification_checks
    def without_terminal(*args):
        value = old(*args); value.pop("terminal_identity_correct", None)
        return value
    monkeypatch.setattr(replay, "qualification_checks", without_terminal)
    state = gates(synthetic)["groups"]
    assert state["CORPORATE_ACTION_AND_ENTITLEMENT"] is False
    assert state["RECEIVABLE_ACCOUNTING"] is False


def test_source_closure_covers_all_runtime_source_promotions():
    paths = set(child.source_closure_paths())
    assert set(p.resolve() for p in replay.SOURCE_PATHS.values()).issubset(paths)
    for relative in ("training/stateful_execution.py", "training/stateful_completion.py",
            "training/stateful_inputs.py", "training/stateful_fusion.py", "training/stateful_value_repair.py",
            "risk/joint_risk_estimators.py", "evaluation/joint_method_accounts.py"):
        assert (replay.REPO / "scripts/research/a2" / relative).resolve() in paths


def test_missing_terminal_consumer_cannot_pass_empty_entitlement_table(synthetic):
    synthetic[0].metadata["terminal_lifecycle_enabled"] = False
    state = gates(synthetic)["groups"]
    assert state["CORPORATE_ACTION_AND_ENTITLEMENT"] is False
    assert state["RECEIVABLE_ACCOUNTING"] is False


def test_wrong_terminal_catalogue_fingerprint_cannot_pass(synthetic):
    synthetic[0].metadata["terminal_events"][0]["event_fingerprint"] = "a" * 64
    assert gates(synthetic)["groups"]["CORPORATE_ACTION_AND_ENTITLEMENT"] is False


def test_unrelated_security_proof_and_verified_flag_cannot_pass(synthetic, tmp_path):
    binding = synthetic[3]
    binding["security_accounting_mapping_ref"] = write(tmp_path / "unrelated.json", {"status": "SOME_OTHER_PROOF"})
    assert binding["security_accounting_continuity_verified"] is True
    assert gates(synthetic)["groups"]["SECURITY_ACCOUNTING_CONTINUITY"] is False


@pytest.mark.parametrize("change", ["overlap_sid", "overlap_ticker", "uncovered_date", "binding_mismatch"])
def test_security_mapping_requires_unique_dated_actual_position_coverage(synthetic, change):
    binding = synthetic[3]; ref = binding["security_accounting_mapping_ref"]
    proof = json.loads(Path(ref["path"]).read_text(encoding="utf-8"))
    if change.startswith("overlap"):
        row = dict(proof["records"][0])
        row["ticker" if change == "overlap_sid" else "sid"] = "DIFFERENT"
        proof["records"].append(row)
    elif change == "uncovered_date":
        for row in proof["records"]:
            row["start"] = "2024-01-01"
    binding["security_accounting_records"] = deepcopy(proof["records"])
    if change == "binding_mismatch":
        binding["security_accounting_records"][0]["sid"] = "WRONG"
    Path(ref["path"]).write_text(json.dumps(proof), encoding="utf-8")
    assert gates(synthetic)["groups"]["SECURITY_ACCOUNTING_CONTINUITY"] is False


def test_terminal_extinguishment_closes_stock_spell_without_sell_or_receivable_closure(synthetic):
    frames = synthetic[1]; name = frames["fills"].ticker.iloc[0]
    frames["entitlements"] = pd.DataFrame([
        dict(path_id="RAW_s10", event_id="SYNTHETIC_MKFG", ticker=name, session=pd.Timestamp("2024-01-02"),
             phase="SECURITY_EXTINGUISHED"),
        dict(path_id="RAW_s10", event_id="SYNTHETIC_MKFG", ticker=name, session=pd.Timestamp("2024-01-02"),
             phase="MERGER_RECEIVABLE_RECOGNIZED")])
    value = child.path_metrics(synthetic[4], frames)
    duration = value["holding_duration"]
    assert duration["terminal_extinguished_stock_spells"] == 1
    assert duration["completed_spells_sessions"]["count"] == 1
    assert duration["completed_spells_sessions"]["mean"] == 1.
    assert duration["open_spells_sessions"]["count"] == 19
    assert value["trade_count"] == len(frames["fills"])
    assert value["receivable_duration"]["per_event"] == [dict(event_id="SYNTHETIC_MKFG", sessions=4,
        paid=False, right_censored=True)]


def test_consumed_event_same_ticker_different_sid_mapping_is_rejected(synthetic, tmp_path, monkeypatch):
    from scripts.v22.corporate_action_transition_r1 import SourceBackedTerminalEvent
    event = SourceBackedTerminalEvent(event_id="SYNTHETIC_MKFG_SID_JOIN", old_security_id="SYNTHETIC_SID_A",
        ticker="MKFG", effective_at="2024-01-02T09:30:00-05:00", available_at="2023-12-29T16:00:00-05:00",
        cash_per_old_share=5., currency="USD", amount_unit="USD_PER_RAW_OLD_SHARE",
        quantity_coordinate="RAW_OLD_SECURITY_SHARES", quantity_source_reference="SYNTHETIC_ONLY_QUANTITY",
        quantity_source_fingerprint="a" * 64, source_type="TIER2_LOCAL_CANONICAL",
        source_reference="SYNTHETIC_ONLY_TERMINAL", source_fingerprint="b" * 64)
    records = [dict(sid="SYNTHETIC_SID_B", ticker="MKFG", start="2023-01-01", end="2026-01-01",
        coordinate="RAW_ACTUAL_SHARE")]
    proof = write(tmp_path / "conflicting_sid_mapping.json", dict(
        status="FROZEN_RESEARCH_SECURITY_ACCOUNTING_MAPPING", role="ACCOUNTING_MAPPING_ONLY",
        coordinate="RAW_ACTUAL_SHARE", decision_information_unchanged=True, records=records))
    binding = dict(security_accounting_records=records, security_accounting_mapping_ref=proof,
        cash_source_bundle=dict(path=str(tmp_path / "synthetic_bundle.joblib"), sha256="c" * 64),
        cash_binding_semantic_fingerprint="d" * 64, entitlement_catalogue_fingerprints=[event.event_fingerprint],
        security_tickers={"SYNTHETIC_SID_A": "MKFG"})
    binding_ref = write(tmp_path / "synthetic_event_binding.json", binding)
    monkeypatch.setattr(child.joblib, "load", lambda _: dict(entitlement_enabled=True,
        entitlement_events=(event,), entitlement_security_tickers=binding["security_tickers"],
        entitlement_source_binding=dict(source_fingerprint="d" * 64)))
    with pytest.raises(ValueError, match="EVENT_SECURITY_BINDING_MISMATCH"):
        child.bound_inputs(dict(source_binding_ref=binding_ref), synthetic[2], (), ())


@pytest.mark.parametrize("research_namespace", child.NAMESPACES)
def test_controller_recognizes_both_research_namespaces(tmp_path, research_namespace):
    write(tmp_path / "run_config.json", dict(research_account=dict(namespace=research_namespace)))
    assert execution._research_requested(tmp_path) is True
    write(tmp_path / "run_config.json", dict(research_account=dict(namespace="OTHER")))
    assert execution._research_requested(tmp_path) is False


def test_quote_descendant_source_closure_is_additive_only():
    old = set(child.source_closure_paths())
    new = set(child.source_closure_paths(child.QUOTE_NAMESPACE))
    assert new - old == {(replay.REPO / "scripts/research/a2/training/stateful_research_quote_domain.py").resolve()}
    assert old.issubset(new)


@pytest.mark.parametrize("research_namespace", child.QUOTE_DESCENDANTS)
def test_quote_identity_does_not_rebind_reconstructed_accounting_authority(research_namespace):
    auth = dict(namespace=research_namespace, contract_ref=dict(sha256="a" * 64),
        parent_account_contract_ref=dict(sha256="b" * 64))
    authority = dict(scientific_identity=child.NAMESPACE, task_id=child.TASK_ID,
        clock_role="RECONSTRUCTED_REALIZED_EVENT", frozen_contract_sha256="b" * 64,
        strict_PIT_promotion_eligible=False, production_qualified=False, event_fingerprints=[])
    child.validate_authority(authority, child.accounting_contract_sha(auth))
    with pytest.raises(ValueError, match="AUTHORITY_REQUIRED"):
        child.validate_authority(authority, auth["contract_ref"]["sha256"])
    with pytest.raises(ValueError, match="AUTHORITY_REQUIRED"):
        child.validate_authority(dict(authority, scientific_identity=child.QUOTE_NAMESPACE), "b" * 64)
    assert child.accounting_contract_sha(dict(contract_ref=dict(sha256="a" * 64))) == "a" * 64


def test_quote_worker_and_journal_are_namespace_isolated(tmp_path, monkeypatch):
    write(tmp_path / "run_config.json", {})
    auth = dict(namespace=child.QUOTE_NAMESPACE)
    lock = dict(token="SYNTHETIC_QUOTE_TOKEN", namespace=child.QUOTE_NAMESPACE,
        controller_source_sha256=replay.sha(Path(execution.__file__)),
        run_config_sha256=replay.sha(tmp_path / "run_config.json"))
    write(tmp_path / "CONTINUATION_LOCK.json", lock)
    monkeypatch.setenv(execution.CONTINUATION_LOCK_ENV, lock["token"])
    child.worker_guard(tmp_path, {}, auth)
    with pytest.raises(ValueError, match="LOCK_MISMATCH"):
        child.worker_guard(tmp_path, {}, {})
    c = candidate()
    event = dict(namespace=child.QUOTE_NAMESPACE, continuation=True, path_units=1,
        candidate_id=c["candidate_id"], scientific_tuple_sha256=c["scientific_tuple_sha256"])
    monkeypatch.setattr(child, "_history", lambda _: [dict(event, event="ACCOUNT_PATH_ATTEMPT_STARTED"),
        dict(event, event="ACCOUNT_PATH_FAILED")])
    assert child.history_budget(tmp_path, [c], child.QUOTE_NAMESPACE)["failed"] == 1
    with pytest.raises(ValueError, match="JOURNAL_NAMESPACE"):
        child.history_budget(tmp_path, [c])


def test_quote_baseline_checks_its_new_contract_and_namespace(tmp_path, monkeypatch):
    auth = dict(namespace=child.QUOTE_NAMESPACE, contract_ref=dict(sha256="a" * 64))
    audit = dict(status="RESEARCH_CONTINUOUS_PRE2026_REPLAY_COMPLETE", namespace=child.QUOTE_NAMESPACE,
        research_contract_sha256="a" * 64,
        research_integrity={"RAW_s10": dict(groups=dict.fromkeys(child.GATES, True))})
    ref = write(tmp_path / "audit.json", audit)
    event = dict(event="ACCOUNT_PATH_COMPLETE", candidate_id="RAW_s10", audit_path=ref["path"], audit_sha256=ref["sha256"])
    monkeypatch.setattr(child, "_history", lambda _: [event])
    gate = child.baseline_gate(tmp_path, auth)
    assert gate["all_passed"] is True and gate["certified_market_quote_authority"] is False
    audit["namespace"] = child.NAMESPACE
    event["audit_sha256"] = write(tmp_path / "audit.json", audit)["sha256"]
    with pytest.raises(ValueError, match="QUOTE_BASELINE_NAMESPACE"):
        child.baseline_gate(tmp_path, auth)


def test_quote_missing_protected_optional_seam_fails_before_attempt(tmp_path, monkeypatch):
    auth = dict(namespace=child.QUOTE_NAMESPACE)
    monkeypatch.setattr(child, "contract", lambda _: (tmp_path, {}, auth, [candidate()]))
    monkeypatch.setattr(child, "worker_guard", lambda *_: None)
    monkeypatch.setattr(replay, "execute_market", lambda: None)
    assert child.runtime_capability(auth)["available"] is False
    with pytest.raises(ValueError, match="OWNER_EXTENSION"):
        child.run_batch(tmp_path, ["RAW_s10"])
    assert not (tmp_path / "ACCOUNT_PATH_LOG.jsonl").exists()


def test_quote_completion_uses_child_status_without_qualifying_strict_account(tmp_path, monkeypatch):
    auth = dict(namespace=child.QUOTE_NAMESPACE, quote_domain_ref=dict(path="SYNTHETIC_QUOTE", sha256="a" * 64),
        parent_account_contract_ref=dict(path="SYNTHETIC_PARENT", sha256="b" * 64))
    monkeypatch.setattr(child, "contract", lambda _: (tmp_path, {}, auth, [candidate()]))
    monkeypatch.setattr(child, "history_budget", lambda *_: dict(completed=1, failed=0))
    monkeypatch.setattr(child, "baseline_gate", lambda *_: dict(all_passed=True))
    monkeypatch.setattr(child, "write_json_atomic", lambda *_: None)
    state = child.build_report(tmp_path)
    assert state["status"] == "QUALIFIED_FROZEN_HISTORY_RESEARCH_RAW_s10"
    assert state["namespace"] == child.QUOTE_NAMESPACE
    assert state["certified_market_quote_authority"] is False
    assert state["strict_PIT_promotion_eligible"] is False and state["production_qualified"] is False


@pytest.mark.parametrize("research_namespace", child.QUOTE_DESCENDANTS)
@pytest.mark.parametrize("base_quality", [False, True])
def test_quote_bound_inputs_keeps_unsupported_accounting_and_original_independent_quality(synthetic, tmp_path, monkeypatch, base_quality, research_namespace):
    from scripts.v22.corporate_action_transition_r1 import ResearchReconstructedTerminalEvent
    from scripts.research.a2.training import stateful_research_quote_domain as quote
    market = synthetic[2]
    market.quality[2, 0] = base_quality
    ticker = str(market.tickers[0]);other = str(market.tickers[1]);day = str(market.dates[2].date())
    records = deepcopy(synthetic[3]["security_accounting_records"])
    records.append(dict(sid="SYNTHETIC_MKFG", ticker="MKFG", start="2023-01-01", end="2026-01-01", coordinate="RAW_ACTUAL_SHARE"))
    proof = write(tmp_path / "synthetic_quote_security_proof.json", dict(status="FROZEN_RESEARCH_SECURITY_ACCOUNTING_MAPPING",
        role="ACCOUNTING_MAPPING_ONLY", coordinate="RAW_ACTUAL_SHARE", decision_information_unchanged=True, records=records))
    event = ResearchReconstructedTerminalEvent(event_id="SYNTHETIC_RECONSTRUCTED_TERMINAL", old_security_id="SYNTHETIC_MKFG", ticker="MKFG",
        effective_at=day + "T09:30:00-05:00", available_at=None, cash_per_old_share=5., currency="USD", amount_unit="USD_PER_RAW_OLD_SHARE",
        quantity_coordinate="RAW_OLD_SECURITY_SHARES", quantity_source_reference="SYNTHETIC_ONLY_QUANTITY", quantity_source_fingerprint="a" * 64,
        source_type="TIER2_LOCAL_CANONICAL", source_reference="SYNTHETIC_ONLY_TERMINAL", source_fingerprint="b" * 64,
        reconstruction_ref="SYNTHETIC_ONLY_RECONSTRUCTION", reconstruction_sha256="c" * 64)
    unsupported = (dict(ticker=ticker, effective_date=day, source_fingerprint="d" * 64, source_reference="SYNTHETIC_EVENT_A", reason="SYNTHETIC_CASH_WARNING"),
        dict(ticker=other, effective_date=day, source_fingerprint="e" * 64, source_reference="SYNTHETIC_EVENT_B", reason="SYNTHETIC_IDENTITY_WARNING"))
    evidence = dict(ticker=ticker, date=day, masked=True, inherited_event_mask=True,
        raw_rows=[dict(ticker=ticker, date=day, open=10., close=10., code="SYNTHETIC_CODE")],
        identity_records=[records[0]], code_tickers={"SYNTHETIC_CODE": [ticker]}, coordinate="RAW_ACTUAL_SHARE",
        independent_quality_flags=[], mechanisms=[dict(mask_origin="INHERITED_UNSUPPORTED_EVENT", ticker=ticker, date=day,
            source_fingerprint="d" * 64, source_reference="SYNTHETIC_EVENT_A", reason="SYNTHETIC_CASH_WARNING")], terminal_contracts=[])
    decisions = quote.classify_population([evidence])
    quote_ref = dict(path=str(tmp_path / "synthetic_quote_domain.json"), sha256="f" * 64)
    binding = dict(security_accounting_records=records, security_accounting_mapping_ref=proof,
        cash_source_bundle=dict(path=str(tmp_path / "synthetic_bundle.joblib"), sha256="a" * 64),
        cash_binding_semantic_fingerprint="b" * 64, entitlement_catalogue_fingerprints=[event.event_fingerprint],
        security_tickers={"SYNTHETIC_MKFG": "MKFG"}, MKFG_terminal_event_fingerprint=event.event_fingerprint)
    auth = dict(namespace=child.QUOTE_NAMESPACE, quote_domain_ref=quote_ref,
        source_binding_ref=write(tmp_path / "synthetic_binding.json", binding), contract_ref=dict(sha256="c" * 64),
        parent_account_contract_ref=dict(sha256="d" * 64), research_account_authority=dict(scientific_identity=child.NAMESPACE,
            task_id=child.TASK_ID, clock_role="RECONSTRUCTED_REALIZED_EVENT", frozen_contract_sha256="d" * 64,
            strict_PIT_promotion_eligible=False, production_qualified=False, event_fingerprints=[event.event_fingerprint]))
    bundle = dict(entitlement_enabled=True, entitlement_events=(event,), entitlement_security_tickers=binding["security_tickers"],
        entitlement_source_binding=dict(source_fingerprint="b" * 64, manifest=dict(removal_keys=[])))
    monkeypatch.setattr(child.joblib, "load", lambda _: bundle)
    monkeypatch.setattr(quote, "load_frozen_domain", lambda ref: dict(decisions=decisions))
    convention_calls = []
    if research_namespace == child.SESSION_NAMESPACE:
        auth.update(namespace=research_namespace, research_ca_accounting_convention=dict(path="SYNTHETIC_CA_CONVENTION", sha256="2" * 64))
        monkeypatch.setattr(child, "_quote_domain", lambda *args: dict(decisions=decisions))
        monkeypatch.setattr(child, "_session_convention", lambda value: convention_calls.append(value["research_ca_accounting_convention"]) or {})
    before = child._decision_digest(market, (market.input_present,))
    adjusted, remaining, kwargs, final_binding = child.bound_inputs(auth, market, (), unsupported)
    assert child._decision_digest(adjusted, (market.input_present,)) == before
    if research_namespace == child.SESSION_NAMESPACE:
        assert kwargs["research_ca_accounting_convention"] == auth["research_ca_accounting_convention"]
        assert convention_calls == [auth["research_ca_accounting_convention"]]
        assert final_binding["real_effective_clock_proven"] is False
        assert final_binding["research_session_boundary_assumption"] is True
    else:
        assert "research_ca_accounting_convention" not in kwargs
    assert remaining == unsupported and len(remaining) == 2
    assert bool(adjusted.quality[2, 0]) is base_quality
    assert bool(adjusted.quality[2, 1]) is True
    assert kwargs["research_quote_domain"] == quote_ref
    assert kwargs["research_account_authority"] == auth["research_account_authority"]
    assert final_binding["quote_domain_audit"]["accounting_records_changed"] is False
    assert np.array_equal(market.quality, synthetic[2].quality)



def _existing_controller_fixture(tmp_path, monkeypatch, groups, research_namespace=child.QUOTE_NAMESPACE):
    # Reuse the existing reviewed synthetic controller fixture; no copied engine.
    import importlib.util
    path = Path(__file__).with_name("test_stateful_continuation.py")
    spec = importlib.util.spec_from_file_location("synthetic_continuation_fixture", path)
    fixture_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_module)
    control, calls, candidates, _ = fixture_module.research_loop_fixture(tmp_path, monkeypatch, groups)
    control.auth["namespace"] = research_namespace
    return control, calls, candidates


@pytest.mark.parametrize("research_namespace", child.QUOTE_DESCENDANTS)
def test_quote_unique_controller_dispatches_exact57_with_original_order_and_friction(tmp_path, monkeypatch, research_namespace):
    from contextlib import contextmanager
    control, calls, candidates = _existing_controller_fixture(tmp_path, monkeypatch, dict.fromkeys(child.GATES, True), research_namespace)
    namespaces = []
    @contextmanager
    def lock(run, source_sha, namespace):
        namespaces.append(namespace)
        yield "SYNTHETIC_OWNED_LOCK"
    monkeypatch.setattr(execution, "continuation_lock", lock)
    state = execution._run_research_controller(control)
    assert state["status"] == "COMPLETED" and state["baseline_qualified"] is True
    assert namespaces == [research_namespace]
    assert [cid for group in calls for cid in group] == [c["candidate_id"] for c in candidates]
    assert calls[0] == ["RAW_s10"]
    for group in calls:
        assert len({next(c["execution_friction"]["one_way_bps"] for c in candidates if c["candidate_id"] == cid) for cid in group}) == 1
    assert len(execution.events(control.run, "ACCOUNT_PATH_LOG.jsonl")) == 114


@pytest.mark.parametrize("group", child.GATES)
@pytest.mark.parametrize("mutation", ["false", "null", "missing"])
@pytest.mark.parametrize("research_namespace", child.QUOTE_DESCENDANTS)
def test_quote_controller_each_literal_gate_blocks_combined_true(tmp_path, monkeypatch, group, mutation, research_namespace):
    groups = dict.fromkeys(child.GATES, True)
    if mutation == "missing": groups.pop(group)
    else: groups[group] = False if mutation == "false" else None
    control, calls, _ = _existing_controller_fixture(tmp_path, monkeypatch, groups, research_namespace)
    state = execution._run_research_controller(control)
    assert calls == [["RAW_s10"]]
    assert state["baseline_qualified"] is False
    assert state["activation_decision"] == "RESEARCH_ACCOUNT_BASELINE_BLOCKED"


# Session-boundary admission and custody: metadata/synthetic only, no real attempts.
def _session_metadata(tmp_path):
    scientific = dict(session_boundary_rule_ref=dict(path="SYNTHETIC_RULE", sha256="a" * 64),
        session_boundary_population_ref=dict(path="SYNTHETIC_POPULATION", sha256="b" * 64),
        parent_quote_contract_ref=dict(path="SYNTHETIC_QUOTE_SCIENCE", sha256="c" * 64), **child.SESSION_FLAGS)
    auth = dict(namespace=child.SESSION_NAMESPACE, **deepcopy(scientific),
        contract_ref=dict(path="SYNTHETIC_SESSION_SCIENCE", sha256="d" * 64),
        research_ca_accounting_convention=write(tmp_path / "synthetic_ca_freeze.json", {}))
    frozen = dict(contract_ref=auth["contract_ref"], rule_ref=scientific["session_boundary_rule_ref"],
        population_ref=scientific["session_boundary_population_ref"])
    return auth, scientific, frozen


@pytest.mark.parametrize("role", ["auth", "scientific"])
@pytest.mark.parametrize("flag", list(child.SESSION_FLAGS))
@pytest.mark.parametrize("bad", [None, 0, 1, "true"])
def test_session_convention_assumptions_are_literal(tmp_path, monkeypatch, role, flag, bad):
    from scripts.research.a2.evaluation import continuous_research_account as shared
    auth, scientific, frozen = _session_metadata(tmp_path)
    monkeypatch.setattr(child, "reference", lambda ref, **_: Path(ref["path"]))
    monkeypatch.setattr(shared, "load_research_ca_accounting_convention", lambda ref: frozen, raising=False)
    assert child._session_convention(auth, scientific) == frozen
    (auth if role == "auth" else scientific)[flag] = bad
    with pytest.raises(ValueError, match="ASSUMPTION_FLAGS_REQUIRED"):
        child._session_convention(auth, scientific)


@pytest.mark.parametrize("key", ["contract_ref", "rule_ref", "population_ref"])
def test_session_convention_cannot_bind_another_science_or_rule(tmp_path, monkeypatch, key):
    from scripts.research.a2.evaluation import continuous_research_account as shared
    auth, scientific, frozen = _session_metadata(tmp_path)
    monkeypatch.setattr(child, "reference", lambda ref, **_: Path(ref["path"]))
    monkeypatch.setattr(shared, "load_research_ca_accounting_convention", lambda ref: frozen, raising=False)
    frozen[key] = dict(path="UNRELATED", sha256="e" * 64)
    with pytest.raises(ValueError, match="CONVENTION_IDENTITY_CHANGED"):
        child._session_convention(auth, scientific)


def _session_quote_envelope(tmp_path, monkeypatch):
    from scripts.research.a2.training import stateful_research_quote_domain as quote
    replay_key = str(Path(replay.__file__).resolve())
    original = dict(schema="SYNTHETIC_ONLY", rule_definition={"NO_CLASSIFIER_CHANGE": True},
        module_ref=dict(path="SYNTHETIC_MODULE", sha256="a" * 64), population_ref=dict(path="SYNTHETIC_POP", sha256="b" * 64),
        source_refs={"synthetic": dict(path="SYNTHETIC_SOURCE", sha256="c" * 64)},
        source_pins={replay_key: "d" * 64, "SYNTHETIC_UNCHANGED": "e" * 64})
    parent_ref = write(tmp_path / "synthetic_parent_quote.json", original)
    envelope = dict(deepcopy(original), parent_quote_domain_ref=parent_ref)
    envelope["source_pins"][replay_key] = replay.sha(Path(replay.__file__))
    scientific = dict(quote_domain_ref=parent_ref, parent_account_contract_ref=dict(path="SYNTHETIC_BASE", sha256="f" * 64))
    parent_quote = dict(scientific_identity=child.QUOTE_NAMESPACE, task_id=child.QUOTE_TASK_ID, **scientific)
    auth = dict(namespace=child.SESSION_NAMESPACE,
        quote_domain_ref=write(tmp_path / "synthetic_quote_envelope.json", envelope),
        parent_quote_contract_ref=write(tmp_path / "synthetic_quote_science.json", parent_quote))
    monkeypatch.setattr(child, "reference", lambda ref, **_: Path(ref["path"]))
    consumed = []
    monkeypatch.setattr(quote, "load_frozen_domain", lambda ref: consumed.append(ref) or {"synthetic_verified": True})
    return auth, scientific, envelope, consumed


@pytest.mark.parametrize("field", ["rule_definition", "module_ref", "population_ref", "source_refs", "other_pin", "replay_pin", "extra_pin", "lineage"])
def test_session_quote_envelope_only_allows_exact_replay_physical_repin(tmp_path, monkeypatch, field):
    auth, scientific, envelope, consumed = _session_quote_envelope(tmp_path, monkeypatch)
    assert child._quote_domain(auth, scientific) == {"synthetic_verified": True}
    assert consumed == [auth["quote_domain_ref"]]
    if field in ("other_pin", "replay_pin", "extra_pin"):
        key = "SYNTHETIC_UNCHANGED" if field == "other_pin" else str(Path(replay.__file__).resolve()) if field == "replay_pin" else "EXTRA_PIN"
        envelope["source_pins"][key] = "1" * 64
    elif field == "lineage": envelope["parent_quote_domain_ref"] = {"sha256": "2" * 64}
    else: envelope[field] = {"CHANGED": True}
    auth["quote_domain_ref"] = write(Path(auth["quote_domain_ref"]["path"]), envelope)
    with pytest.raises(ValueError, match="RESEARCH_SESSION_QUOTE"):
        child._quote_domain(auth, scientific)
    assert len(consumed) == 1


@pytest.mark.parametrize("bad_role", ["replay", "owner", "loader"])
def test_session_runtime_missing_seam_blocks_before_account_attempt(tmp_path, monkeypatch, bad_role):
    from scripts.research.a2.evaluation import continuous_research_account as shared
    auth = dict(namespace=child.SESSION_NAMESPACE)
    def supported(research_quote_domain=None, research_ca_accounting_convention=None, research_account_authority=None): pass
    monkeypatch.setattr(replay, "execute_market", supported)
    monkeypatch.setattr(replay, "run_continuous_account", supported)
    monkeypatch.setattr(shared, "load_research_ca_accounting_convention", lambda ref: {}, raising=False)
    if bad_role == "loader": monkeypatch.setattr(shared, "load_research_ca_accounting_convention", None)
    else: monkeypatch.setattr(replay, "execute_market" if bad_role == "replay" else "run_continuous_account", lambda: None)
    assert not child.runtime_capability(auth)["available"]
    monkeypatch.setattr(child, "contract", lambda _: (tmp_path, {}, auth, [candidate()]))
    monkeypatch.setattr(child, "worker_guard", lambda *_: None)
    with pytest.raises(ValueError, match="OWNER_EXTENSION"):
        child.run_batch(tmp_path, ["RAW_s10"])
    assert not (tmp_path / "ACCOUNT_PATH_LOG.jsonl").exists()


@pytest.mark.parametrize("group", child.GATES)
@pytest.mark.parametrize("mutation", ["false", "null", "missing"])
def test_session_baseline_gate_ten_groups_and_convention_identity(tmp_path, monkeypatch, group, mutation):
    ref = dict(path="SYNTHETIC_CONVENTION", sha256="c" * 64)
    auth = dict(namespace=child.SESSION_NAMESPACE, contract_ref=dict(sha256="a" * 64), research_ca_accounting_convention=ref)
    audit = dict(status="RESEARCH_CONTINUOUS_PRE2026_REPLAY_COMPLETE", namespace=child.SESSION_NAMESPACE,
        research_contract_sha256="a" * 64, research_ca_accounting_convention=ref,
        research_integrity={"RAW_s10": dict(groups=dict.fromkeys(child.GATES, True))}, **child.SESSION_FLAGS)
    receipt = write(tmp_path / "audit.json", audit)
    event = dict(event="ACCOUNT_PATH_COMPLETE", candidate_id="RAW_s10", audit_path=receipt["path"], audit_sha256=receipt["sha256"])
    monkeypatch.setattr(child, "_history", lambda _: [event])
    assert child.baseline_gate(tmp_path, auth)["all_passed"] is True
    if mutation == "missing": del audit["research_integrity"]["RAW_s10"]["groups"][group]
    else: audit["research_integrity"]["RAW_s10"]["groups"][group] = False if mutation == "false" else None
    event["audit_sha256"] = write(tmp_path / "audit.json", audit)["sha256"]
    state = child.baseline_gate(tmp_path, auth)
    assert state["all_passed"] is False and state["groups"][group] is False
    assert state["real_effective_clock_proven"] is False and state["research_session_boundary_assumption"] is True
    assert state["certified_market_quote_authority"] is False


@pytest.mark.parametrize("failure", ["flags", "namespace", "convention"])
def test_session_all_true_gates_do_not_promote_wrong_assumption_receipt(tmp_path, monkeypatch, failure):
    ref = dict(path="SYNTHETIC_CONVENTION", sha256="c" * 64)
    auth = dict(namespace=child.SESSION_NAMESPACE, contract_ref=dict(sha256="a" * 64), research_ca_accounting_convention=ref)
    audit = dict(status="RESEARCH_CONTINUOUS_PRE2026_REPLAY_COMPLETE", namespace=child.SESSION_NAMESPACE,
        research_contract_sha256="a" * 64, research_ca_accounting_convention=ref,
        research_integrity={"RAW_s10": dict(groups=dict.fromkeys(child.GATES, True))}, **child.SESSION_FLAGS)
    if failure == "flags": audit["real_effective_clock_proven"] = True
    elif failure == "namespace": audit["namespace"] = child.QUOTE_NAMESPACE
    else: audit["research_ca_accounting_convention"] = None
    receipt = write(tmp_path / "audit.json", audit)
    monkeypatch.setattr(child, "_history", lambda _: [dict(event="ACCOUNT_PATH_COMPLETE", candidate_id="RAW_s10", audit_path=receipt["path"], audit_sha256=receipt["sha256"])])
    with pytest.raises(ValueError): child.baseline_gate(tmp_path, auth)


@pytest.mark.parametrize("finished", [1, 57])
def test_session_completion_keeps_assumption_and_exact57_semantics(tmp_path, monkeypatch, finished):
    auth = dict(namespace=child.SESSION_NAMESPACE, quote_domain_ref=dict(path="SYNTHETIC_QUOTE", sha256="a" * 64),
        parent_account_contract_ref=dict(path="SYNTHETIC_PARENT", sha256="b" * 64),
        research_ca_accounting_convention=dict(path="SYNTHETIC_CONVENTION", sha256="c" * 64))
    monkeypatch.setattr(child, "contract", lambda _: (tmp_path, {}, auth, [candidate()]))
    monkeypatch.setattr(child, "history_budget", lambda *_: dict(completed=finished, failed=0))
    monkeypatch.setattr(child, "baseline_gate", lambda *_: dict(all_passed=True))
    monkeypatch.setattr(child, "write_json_atomic", lambda *_: None)
    state = child.build_report(tmp_path)
    assert state["status"] == ("QUALIFIED_FROZEN_HISTORY_RESEARCH_RAW_s10" if finished == 1 else "FROZEN56_ACCOUNT_PATH_EXECUTION_COMPLETE")
    assert state["namespace"] == child.SESSION_NAMESPACE
    assert state["real_effective_clock_proven"] is False and state["research_session_boundary_assumption"] is True
    assert state["production_qualified"] is False and state["strict_PIT_promotion_eligible"] is False
    assert state["certified_market_quote_authority"] is False


def test_session_worker_persists_owner_boundary_audit_via_existing_artifact_transport(synthetic, tmp_path, monkeypatch):
    result, frames, _, binding, c = synthetic
    dates = pd.bdate_range("2023-01-02", periods=752)
    present = np.ones((752, 20), dtype=bool); prices = np.full((752, 20), 10.)
    market = replay.MarketArrays(dates, list(result.positions.ticker.unique()), prices, prices,
        input_present=present, new_buy_eligible=present,
        signal_asof=[d.tz_localize("America/New_York") + pd.Timedelta(hours=16) for d in dates])
    boundary = pd.DataFrame([dict(path_id="RAW_s10", event_date="2024-01-02", preopen_raw_shares=0.,
        disposition="NOT_APPLICABLE_TO_THIS_ACCOUNT_PREFIX")])
    result.research_ca_accounting_boundary_audit = boundary
    parent = tmp_path / "synthetic_parent"; write(parent / "input_manifest.json", {})
    convention_ref = dict(path="SYNTHETIC_CONVENTION", sha256="a" * 64)
    auth = dict(namespace=child.SESSION_NAMESPACE, contract_ref=dict(sha256="b" * 64),
        source_binding_ref=dict(path="SYNTHETIC_BINDING", sha256="c" * 64), source_pins={},
        value_packets={"ridge": "SYNTHETIC_PACKET"}, research_ca_accounting_convention=convention_ref,
        quote_domain_ref=dict(path="SYNTHETIC_QUOTE", sha256="d" * 64),
        parent_account_contract_ref=dict(path="SYNTHETIC_PARENT", sha256="e" * 64), research_account_authority={})
    binding = dict(binding, quote_domain_audit={})
    binding.update({k: dict(path="SYNTHETIC_PROOF", sha256="f" * 64) for k in
        ("decision_input_manifest_ref", "cash_source_bundle", "quote_coordinate_evidence_ref",
         "security_accounting_mapping_ref", "decision_firewall_proof_ref")})
    monkeypatch.setattr(child, "contract", lambda _: (tmp_path, dict(parent_run_dir=str(parent)), auth, [c]))
    monkeypatch.setattr(child, "worker_guard", lambda *_: None)
    monkeypatch.setattr(child, "runtime_capability", lambda *_: dict(available=True))
    monkeypatch.setattr(child, "history_budget", lambda *_: dict(outstanding=0, new_account_path_attempts=0))
    monkeypatch.setattr(child, "assert_write_path", lambda *_: None)
    monkeypatch.setattr(replay, "_read_parent_inputs_readonly", lambda *_: object())
    monkeypatch.setattr(replay, "read_market", lambda *_: (market, present, present, prices, present, present))
    monkeypatch.setattr(replay, "read_packet", lambda *_args, **_kwargs: dict(mu=prices.copy()))
    monkeypatch.setattr(replay, "_json", lambda *_: {})
    monkeypatch.setattr(replay, "_old", lambda: SimpleNamespace(config_adapter=lambda *_: None,
        frozen_events=lambda *_: ((), None, (), None)))
    monkeypatch.setattr(child, "bound_inputs", lambda *_: (market, (),
        dict(research_ca_accounting_convention=convention_ref), binding))
    execution_kwargs = []
    monkeypatch.setattr(replay, "execute_market", lambda *_args, **kwargs:
        execution_kwargs.append(kwargs) or (result, frames))
    monkeypatch.setattr(child, "integrity_gates", lambda *_args, **_kwargs: dict(groups=dict.fromkeys(child.GATES, True)))
    artifacts = {}; audits = []; journal = []
    def artifact(folder, name, frame):
        artifacts[name] = frame
        return dict(path=str(folder / (name + ".parquet")), sha256="1" * 64, rows=len(frame))
    monkeypatch.setattr(child, "_artifact", artifact)
    monkeypatch.setattr(child, "write_json_atomic", lambda _path, value: audits.append(value))
    monkeypatch.setattr(replay, "_append", lambda _path, value: journal.append(value))
    # Audit hashes are synthetic receipts here; no real output is replayed or read.
    original_sha = replay.sha
    monkeypatch.setattr(replay, "sha", lambda path: "2" * 64 if Path(path).name == "audit.json" else original_sha(path))
    state = child.run_batch(tmp_path, ["RAW_s10"])
    assert state["new_fit_units"] == 0
    assert execution_kwargs[0]["research_ca_accounting_convention"] == convention_ref
    assert artifacts["research_ca_accounting_boundary_audit"] is boundary
    audit = audits[-1]
    assert audit["research_ca_accounting_boundary_audit_ref"] == audit["artifacts"]["research_ca_accounting_boundary_audit"]
    assert audit["research_ca_accounting_convention"] == convention_ref
    assert audit["real_effective_clock_proven"] is False and audit["research_session_boundary_assumption"] is True
    assert [entry["event"] for entry in journal] == ["ACCOUNT_PATH_ATTEMPT_STARTED", "ACCOUNT_PATH_COMPLETE"]
