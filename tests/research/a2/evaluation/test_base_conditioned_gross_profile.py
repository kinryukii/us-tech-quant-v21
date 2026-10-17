"""Synthetic metadata and original pure validators; no numerical execution."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys
import types

import pytest

from scripts.research.a2.evaluation import base_conditioned_gross_profile as profile
from scripts.research.a2.evaluation import frozen_test_authority as f
from scripts.research.a2.evaluation import frozen_a94_profile as p


@pytest.fixture
def release(tmp_path, monkeypatch):
    original_state = profile._STATE
    names = ("_verified", "load_descriptive_authority", "require_descriptive_decision",
             "validate_descriptive_input_dates", "validate_descriptive_account",
             "validate_descriptive_policy", "validate_reconstructed_accounting_events")
    original_functions = {name: getattr(f, name) for name in names}
    monkeypatch.setattr(profile, "_STATE", None)
    monkeypatch.setattr(profile, "ROOT", tmp_path)
    def save(name, data):
        path = tmp_path / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return profile._reference(path)
    contract = save("contract.json", {"research_id": profile.TASK})
    candidates = [base + "__GROSS_" + learner for base in profile.BASES for learner in ("LINEAR", "TREE", "NEURAL")]
    inputs = save("inputs.json", {"candidate_ids": candidates})
    runtime_pin = save("runtime.json", {"source_only": True})
    scope_pin = save("scope.json", {"task_id": profile.TASK})
    for name, value in (("CONTRACT_REF", contract), ("INPUT_MANIFEST_REF", inputs),
                        ("RUNTIME_BINDING_REF", runtime_pin), ("SCOPE_REF", scope_pin)):
        monkeypatch.setattr(profile, name, value)
    monkeypatch.setattr(profile.runtime, "assert_runtime", lambda *a, **k: None)
    monkeypatch.setattr(profile.runtime, "source_execution_context", lambda *a, **k: {"binding": {"scope_ref": scope_pin}})
    profile.install_routes(runtime_pin, "HISTORY2024")
    source_refs = {key: save(key + ".json", {}) for key in f.SOURCE_GROUPS}
    friction = {"one_way_bps": 10}
    states = {}
    rows = []
    for base in profile.BASES:
        keys = []
        for group in ("ENTRY", "INCUMBENT"):
            key = base + group
            keys.append(key)
            states[key] = dict(role="base", base_id=base, group=group,
                model_ref=save(key + "_model.json", {"synthetic": True}),
                receipt_ref=save(key + "_receipt.json", {"synthetic": True}),
                signal_cutoff_exclusive="2024-01-01", label_maturity_cutoff_exclusive="2024-01-01")
        keys.append("raw")
        rows.append(dict(candidate_id=base, state_ids=keys,
            specification=dict(candidate_id=base, execution_friction=friction, action="raw")))
    states["raw"] = dict(role="raw", model_ref=save("raw_model.json", {"synthetic": True}),
        receipt_ref=save("raw_receipt.json", {"synthetic": True}),
        signal_cutoff_exclusive="2024-01-01", label_maturity_cutoff_exclusive="2024-01-01")
    policies = dict(task_id=profile.TASK, phase="HISTORY2024", status="FROZEN", candidate_bindings=rows)
    state_doc = dict(task_id=profile.TASK, phase="HISTORY2024", status="FROZEN", state_refs=states)
    q = dict(schema=profile.QUALIFICATION_SCHEMA, task_id=profile.TASK, phase="HISTORY2024",
        status="QUALIFIED_FOR_DECLARED_RESEARCH_SCOPE", contract_ref=contract, source_refs=source_refs,
        as_of="2024-10-08T22:00:00Z", formal_primary_metrics_allowed=False,
        groups={key: True for key in f.SOURCE_GROUPS}, source_slices={},
        common_calendar_start="2024-01-02", common_calendar_end="2024-10-04",
        common_calendar_selection="SOURCE_AVAILABILITY_AND_ORIGINAL_CALENDAR_ONLY",
        candidate_ids=list(profile.BASES), raw_selector_binding={"mode": "ORIGINAL"})
    for key, pin in source_refs.items():
        q["source_slices"][key] = dict(source_ref=pin, view_only=True, no_2027_content=True,
            read_filter_applied_before_economic_decode=True, content_start="2023-01-03", content_end="2024-10-04",
            clock_role="HISTORICAL_AVAILABLE_AT_BOUND", historical_available_at_bound=True,
            available_at="2024-10-08T21:00:00Z")
    bound = dict(schema=profile.RELEASE_SCHEMA, task_id=profile.TASK, phase="HISTORY2024",
        status="ROOT_SOURCE_AND_POLICY_BOUND", contract_ref=contract, input_manifest_ref=inputs,
        runtime_binding_ref=runtime_pin, scope_ref=scope_pin, new_fit=0,
        initial_cash_usd=3000, initial_holdings=[], initial_receivables=[], fresh_account=True,
        allowed_path_ids=list(profile.BASES), as_of=q["as_of"],
        windows=[dict(window_id="HISTORY2024", start="2024-01-02", end="2024-10-04")],
        signal_and_label_maturity_cutoff_exclusive="2024-10-07", feature_history_start="2023-01-03",
        source_refs=source_refs, raw_selector_binding=q["raw_selector_binding"],
        candidate_bindings=rows, state_refs=states,
        owner_refs={"profile": profile._reference(profile.__file__), "runtime": profile._reference(profile.runtime.__file__),
                    "authority": profile._reference(f.__file__), "policy": profile._reference(p.__file__)},
        driver_ref=profile._reference(profile.__file__), proof_refs={"synthetic": save("proof.json", {"synthetic": True})})
    bound.update({key: False for key in profile.NO_AUTHORITY_FLAGS})
    def commit():
        bound["source_qualification_ref"] = save("q.json", q)
        bound["candidate_manifest_ref"] = save("policies.json", policies)
        bound["state_manifest_ref"] = save("states.json", state_doc)
        pin = save("HISTORY_ACCOUNT_RELEASE.json", bound)
        return dict(schema=profile.SCHEMA, task_id=profile.TASK, release_ref=pin, window_id="HISTORY2024")
    yield dict(bound=bound, q=q, states=states, rows=rows, commit=commit, runtime_pin=runtime_pin,
               original_functions=original_functions, save=save, policies=policies, state_doc=state_doc)
    for name, fn in original_functions.items():
        setattr(f, name, fn)
    profile._STATE = original_state


def test_sealed_history_reuses_full_policy_date_cash_and_friction_checks(release):
    authority = f.load_descriptive_authority(release["commit"]())
    with pytest.raises(ValueError, match="FULL_RUNTIME_POLICY_VALIDATION_REQUIRED"):
        f.require_descriptive_decision(authority, "2024-01-02", path_id=profile.BASES[0])
    specs = [row["specification"] for row in release["rows"]]
    checked = f.validate_descriptive_policy(authority, specs)
    assert f.require_descriptive_decision(checked, "2024-01-02", path_id=profile.BASES[0]) is checked
    assert f.validate_descriptive_account(checked, ["2024-01-02", "2024-10-04"], profile.BASES,
        {"initial_nav": 3000}, {"one_way_bps": 10}) is checked
    with pytest.raises(ValueError, match="FRESH_USD3000"):
        f.validate_descriptive_account(checked, ["2024-01-02", "2024-10-04"], profile.BASES,
            {"initial_nav": 4000}, {"one_way_bps": 10})
    with pytest.raises(ValueError, match="ORIGINAL_FRICTION"):
        f.validate_descriptive_account(checked, ["2024-01-02", "2024-10-04"], profile.BASES,
            {"initial_nav": 3000}, {"one_way_bps": 0})
    with pytest.raises(ValueError, match="OUTSIDE_WINDOW"):
        f.require_descriptive_decision(checked, "2024-10-07", path_id=profile.BASES[0])
    assert json.loads(checked.provenance_json)["formal_primary_metrics_allowed"] is False


@pytest.mark.parametrize("field,value,reason", [
    ("status", "DRAFT", "ROOT_SEALED_RELEASE"),
    ("task_id", "OLD_TASK", "ROOT_SEALED_RELEASE"),
    ("phase", "FROZEN2026", "ROOT_SEALED_RELEASE"),
    ("new_fit", 1, "NO_FIT_OR_SELECTION"),
    ("formal_primary_metrics_allowed", True, "NO_FIT_OR_SELECTION"),
])
def test_unsealed_oldscope_crossphase_and_extra_authority_rejected(release, field, value, reason):
    release["bound"][field] = value
    with pytest.raises(ValueError, match=reason):
        f.load_descriptive_authority(release["commit"]())


def test_same_phase_idempotent_cross_phase_install_rejected(release):
    assert profile.install_routes(release["runtime_pin"], "HISTORY2024")["process_private_routes"]
    with pytest.raises(ValueError, match="ONE_PHASE_PER_PROCESS"):
        profile.install_routes(release["runtime_pin"], "FROZEN2026")


def test_cutoff_rejection_precedes_hashing_sources(release, monkeypatch):
    release["bound"]["windows"][0]["end"] = "2024-10-07"
    called = []
    monkeypatch.setattr(f, "_physical", lambda ref: called.append(ref))
    with pytest.raises(ValueError, match="HISTORICAL_EARLIER_CUTOFF"):
        f.load_descriptive_authority(release["commit"]())
    assert called == []


def test_source_clock_gates_precede_hashing_sources(release, monkeypatch):
    release["q"]["source_slices"]["market_quote"]["read_filter_applied_before_economic_decode"] = False
    called = []
    monkeypatch.setattr(f, "_physical", lambda ref: called.append(ref))
    with pytest.raises(ValueError, match="BOUNDED_SOURCE_SCOPE"):
        f.load_descriptive_authority(release["commit"]())
    assert called == []


def test_unknown_delivery_stays_nonprimary(release):
    item = release["q"]["source_slices"]["market_quote"]
    item.update(clock_role=profile.UNKNOWN_CLOCK, available_at=None, historical_available_at_bound=False,
                source_observation_fact_refs=[release["save"]("observation.json", {"synthetic": True})])
    value = f.load_descriptive_authority(release["commit"]())
    assert json.loads(value.provenance_json)["historical_delivery_certification"] == "RETAIN_ORIGINAL_UNKNOWN"
    assert json.loads(value.provenance_json)["formal_primary_metrics_allowed"] is False


@pytest.mark.parametrize("mutation", ["future_state", "missing_head", "policy_spec", "authority_scope"])
def test_state_policy_and_authority_custody_cannot_drift(release, mutation):
    if mutation == "future_state":
        release["states"]["raw"]["signal_cutoff_exclusive"] = "2025-01-01"
        with pytest.raises(ValueError, match="STATE_EARLIER_CUTOFF"):
            f.load_descriptive_authority(release["commit"]())
    elif mutation == "missing_head":
        release["rows"][0]["state_ids"] = [profile.BASES[0] + "ENTRY", "raw"]
        with pytest.raises(ValueError, match="BASE_HEAD_CLOSURE"):
            f.load_descriptive_authority(release["commit"]())
    else:
        value = f.load_descriptive_authority(release["commit"]())
        if mutation == "policy_spec":
            specs = deepcopy([row["specification"] for row in release["rows"]])
            specs[0]["action"] = "changed"
            with pytest.raises(ValueError, match="FULL_SPEC_CHANGED"):
                f.validate_descriptive_policy(value, specs)
        else:
            with pytest.raises(ValueError, match="ADMITTED_AUTHORITY_CHANGED"):
                f._verified(replace(value, end=f.pd.Timestamp("2026-01-01")))


def test_old_task_authority_keeps_original_route_and_seal(release):
    old = f.ValidatedDescriptiveAuthority(f.TASK, "OLD", f.pd.Timestamp("2026-01-02"),
        f.pd.Timestamp("2026-10-08"), f.pd.Timestamp("2026-10-09T00:00:00Z"),
        f.pd.Timestamp("2023-01-03"), ("raw20",), "{}", f._SEAL)
    assert f._verified(old) is old
    assert release["original_functions"]["_verified"](old) is old
    assert f.require_descriptive_decision(old, "2026-01-02", "raw20") is old


def test_event_validator_code_is_original_and_sealed_empty_catalogue_reused(release, monkeypatch):
    value = f.load_descriptive_authority(release["commit"]())
    module = types.ModuleType("scripts.v22.corporate_action_transition_r1")
    module.ResearchReconstructedCashEvent = type("Cash", (), {})
    module.ResearchPostVerifiedTerminalEvent = type("Terminal", (), {})
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert profile._STATE["load_post"].__code__ is f._load_post_verified_binding.__code__
    assert f.validate_reconstructed_accounting_events(value, (), require_exact=True) is value

@pytest.mark.parametrize("raw_cutoff", ["2024-01-01", "2026-01-01"])
def test_frozen_main_and100_exact_schedule_with_eight_separate_policies(release, monkeypatch, raw_cutoff):
    for name, fn in release["original_functions"].items():
        setattr(f, name, fn)
    profile._STATE = None
    profile.install_routes(release["runtime_pin"], "FROZEN2026")
    bound, q = release["bound"], release["q"]
    candidates = [base + "__GROSS_" + learner for base in profile.BASES for learner in ("LINEAR", "TREE", "NEURAL")]
    candidates += [base + "__GROSS_FIXED_050" for base in profile.BASES]
    release["states"]["raw"].update(signal_cutoff_exclusive=raw_cutoff,
                                    label_maturity_cutoff_exclusive=raw_cutoff)
    for base in profile.BASES:
        original = next(row for row in release["rows"] if row["candidate_id"] == base)
        for group in ("ENTRY", "INCUMBENT"):
            key = base + group + "_SCALER"
            state = deepcopy(release["states"][base + group])
            state.update(role="scaler", signal_cutoff_exclusive="2025-01-01",
                         label_maturity_cutoff_exclusive="2025-01-01")
            release["states"][key] = state
            original["state_ids"].append(key)
    rows = []
    for cid in candidates:
        base = cid.split("__GROSS_")[0]
        row = deepcopy(next(row for row in release["rows"] if row["candidate_id"] == base))
        row["candidate_id"] = row["specification"]["candidate_id"] = cid
        if not cid.endswith("FIXED_050"):
            state = deepcopy(release["states"]["raw"])
            state.update(role="gross", candidate_id=cid, signal_cutoff_exclusive="2024-10-07",
                         label_maturity_cutoff_exclusive="2024-10-07")
            release["states"][cid] = state
            row["state_ids"].append(cid)
        rows.append(row)
    windows = [dict(window_id="MAIN" if i == 0 else f"RANDOM_{i:03d}", start="2026-01-02", end="2026-10-08") for i in range(101)]
    schedule = release["save"]("schedule.json", {"windows": windows})
    monkeypatch.setattr(profile, "SCHEDULE_REF", schedule)
    bound.update(phase="FROZEN2026", allowed_path_ids=candidates, as_of="2026-10-09T22:00:00Z",
                 windows=windows, schedule_ref=schedule, candidate_bindings=rows)
    q.update(phase="FROZEN2026", candidate_ids=candidates, as_of=bound["as_of"],
             common_calendar_start="2026-01-02", common_calendar_end="2026-10-08")
    for item in q["source_slices"].values():
        item["content_end"] = "2026-10-08"
    release["policies"].update(phase="FROZEN2026", candidate_bindings=rows)
    release["state_doc"]["phase"] = "FROZEN2026"
    catalog_dir = profile.ROOT / profile.TASK / "synthetic_run" / "derived" / "gross_evaluation_sources"
    catalog_dir.mkdir(parents=True)
    catalog = release["save"](str(catalog_dir / "ACCOUNT_CATALOG.json"), {"synthetic_padding": "x" * 250_000})
    bound["source_refs"]["corporate_actions"] = catalog
    q["source_slices"]["corporate_actions"]["source_ref"] = catalog
    release["commit"]()
    pin = release["save"]("EVALUATION_ACCOUNT_RELEASE.json", bound)
    request = dict(schema=profile.SCHEMA, task_id=profile.TASK, release_ref=pin, window_id="RANDOM_100")
    value = f.load_descriptive_authority(request)
    assert value.allowed_path_ids == tuple(candidates)
    assert value.window_id == "RANDOM_100"
    assert len(profile._document(catalog)["synthetic_padding"]) == 250_000
    unrelated = release["save"]("unrelated_large_metadata.json", {"synthetic_padding": "x" * 250_000})
    with pytest.raises(ValueError, match="BOUNDED_SOURCE_OR_METADATA_REQUIRED"):
        profile._document(unrelated)
    old_phase = profile._STATE["phase"]
    profile._STATE["phase"] = "HISTORY2024"
    with pytest.raises(ValueError, match="BOUNDED_SOURCE_OR_METADATA_REQUIRED"):
        profile._document(catalog)
    profile._STATE["phase"] = old_phase
    checked = f.validate_descriptive_policy(value, [row["specification"] for row in rows])
    assert f.require_descriptive_decision(checked, "2026-10-08", candidates[-1]) is checked
    # Raw reuse cannot relax the other three role clocks.
    for role, illegal in (("raw", "2026-01-02"), ("base", "2025-01-02"),
                          ("scaler", "2025-01-02"), ("gross", "2024-10-08")):
        state = next(state for state in release["states"].values() if state["role"] == role)
        for clock in ("signal_cutoff_exclusive", "label_maturity_cutoff_exclusive"):
            before = state[clock]
            state[clock] = illegal
            bound["state_manifest_ref"] = release["save"]("states.json", release["state_doc"])
            request["release_ref"] = release["save"]("EVALUATION_ACCOUNT_RELEASE.json", bound)
            with pytest.raises(ValueError, match="STATE_EARLIER_CUTOFF_REQUIRED"):
                f.load_descriptive_authority(request)
            state[clock] = before
    bound["state_manifest_ref"] = release["save"]("states.json", release["state_doc"])
    bound["windows"][0]["end"] = "2026-10-09"
    request["release_ref"] = release["save"]("EVALUATION_ACCOUNT_RELEASE.json", bound)
    with pytest.raises(ValueError, match="EXACT_MAIN_PLUS100"):
        f.load_descriptive_authority(request)


def test_original_postverified_cash_event_commitment_admitted_and_change_rejected(release, monkeypatch):
    bound = release["bound"]
    reconstruction = release["save"]("reconstruction.json", {"synthetic": True})
    fingerprint = "a" * 64
    binding = dict(task_id=profile.TASK, clock_role=profile.POST_CLOCK,
                   strict_PIT_promotion_eligible=False, production_qualified=False,
                   events=[dict(event_fingerprint=fingerprint, reconstruction_ref=reconstruction)])
    decision = dict(task_id=profile.TASK, phase="HISTORY2024", status="ROOT_POST_VERIFIED_ACCOUNTING_ONLY_BOUND",
                    contract_ref=profile.CONTRACT_REF, clock_role=profile.POST_CLOCK, model_or_label_input_authority=False,
                    authorized_bindings={"research_cash_reconstruction": deepcopy(binding)})
    decision.update({key: False for key in profile.NO_AUTHORITY_FLAGS})
    decision_pin = release["save"]("decision.json", decision)
    binding["authorization_ref"] = decision_pin
    bound.update(post_verified_accounting_decision_ref=decision_pin, research_cash_reconstruction=binding)
    catalogue = release["save"]("corporate_actions.json", {"research_cash_reconstruction": binding})
    bound["source_refs"]["corporate_actions"] = catalogue
    release["q"]["source_slices"]["corporate_actions"].update(source_ref=catalogue,
        clock_role=profile.POST_CLOCK, available_at=None, historical_available_at_bound=False,
        captured_at="2026-10-13T00:00:00Z")
    value = f.load_descriptive_authority(release["commit"]())
    module = types.ModuleType("scripts.v22.corporate_action_transition_r1")
    class Cash:
        def __post_init__(self):
            assert self.event_fingerprint
    module.ResearchReconstructedCashEvent = Cash
    module.ResearchPostVerifiedTerminalEvent = type("Terminal", (), {})
    monkeypatch.setitem(sys.modules, module.__name__, module)
    event = Cash()
    event.event_fingerprint = fingerprint
    event.reconstruction_ref = reconstruction["path"]
    event.reconstruction_sha256 = reconstruction["sha256"]
    assert f.validate_reconstructed_accounting_events(value, [event], require_exact=True) is value
    event.event_fingerprint = "b" * 64
    with pytest.raises(ValueError, match="POST_VERIFIED_EVENT_CHANGED"):
        f.validate_reconstructed_accounting_events(value, [event], require_exact=True)