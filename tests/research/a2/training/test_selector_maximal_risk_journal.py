"""Synthetic C14 conditional transport tests; no actual bank, cache or targets."""
import copy
import json
from pathlib import Path
from datetime import date, timedelta

import pytest
from scripts.research.a2.training import selector_maximal_risk_journal as j


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(j.canonical(value), encoding="utf-8")
    return dict(path=str(path), sha256=j.sha(path))


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    run = tmp_path / "C14"
    bank = tmp_path / "B_R5"
    run.mkdir()
    dates = [(date(2023, 1, 1) + timedelta(days=i)).isoformat() + "T00:00:00" for i in range(752)]
    nodes = []
    for role, count in j.RX_COUNTS.items():
        for index in range(count):
            nodes.append(dict(node_id=f"RX_MODEL|{role}|2023-07-01|SYNTHETIC_{index}",
                              kind="ESTIMATOR", cutoff="2023-07-01", candidate_id=role))
    requests = [f"HYBRID|{role}|{d}" for role in j.RX_COUNTS for d in dates[-502:]]
    classical = [f"C14_D{i:02d}" for i in range(1, 12) if i != 2]
    requests += [f"CLASSICAL|{role}|{d}" for role in classical for d in dates]
    requests += [f"MAIN|SYNTHETIC|{i}" for i in range(18528)]
    requests += [f"ORACLE|SYNTHETIC|{i}" for i in range(482)]
    assert len(requests) == 29542
    dag = dict(research_id=j.ID, active_ml_fit_state_nodes=656, conditional_risk_fit_state_nodes=144,
               maximum_named_fit_state_nodes=800, physical_fit_hard_cap=1800,
               optimizer_solve_hard_cap=30000, admissible_solve_request_ceiling=29542,
               conditional_hybrid_solves=3012, conditional_classical_solves=7520,
               scientific_retry=0, failed_reservation_refund=False,
               shared_risk_new_estimation_by_C=0, shared_risk_learned_cap=3000,
               conditional_ml_not_reserved_until_qualified=True,
               conditional_risk_fit_nodes=nodes, solve_request_ids=requests)
    families = dict(j.ACTIVE_RX)
    families.update({role: "SYNTHETIC_BLOCKED_FAMILY" for role in j.RX_COUNTS if role not in families})
    design = dict(research_id=j.ID, risk=dict(
        hybrid_bindings=[dict(candidate_id=r, family=f) for r, f in families.items()],
        classical_bindings=[dict(candidate_id=r, family="LW", existing_rule="D02") for r in classical]))
    write_json(run / "DESIGN_FREEZE.json", design)
    write_json(run / "PHYSICAL_DAG.json", dag)
    # These are opaque, deliberately invalid JSON baseline bytes. Parsing them
    # would fail this fixture before any test assertion.
    for name in ("SOURCE_CLOSURE_RECEIPT.json", "FIT_LEDGER.json", "SOLVE_LEDGER.json", "SOLVE_EVENTS.jsonl"):
        (run / name).write_bytes(b"SYNTHETIC_OPAQUE_BASELINE_NEVER_PARSE\n")
    hashes = {name: j.sha(run / name) for name in j.BASELINE_HASHES}
    monkeypatch.setattr(j, "RUN", run)
    monkeypatch.setattr(j, "B_RUN", bank)
    monkeypatch.setattr(j, "BASELINE_HASHES", hashes)
    # Only temporary synthetic destinations are admitted; the real resolver
    # remains read-only and is never used to initialize output roots.
    monkeypatch.setattr(j, "assert_safe_output_path",
                        lambda path, **kwargs: None if Path(path).resolve().is_relative_to(tmp_path.resolve())
                        else pytest.fail("non-synthetic output"))
    monkeypatch.setattr(j.owner, "safe_d", lambda path: Path(path))
    return dict(run=run, bank=bank, dates=dates, dag=dag, design=design, hashes=hashes)


def gate_for(synthetic, role="C14_RX_HGB_LW", mutate=None):
    run = synthetic["run"]
    families = {v["candidate_id"]: v["family"] for v in synthetic["design"]["risk"]["hybrid_bindings"]}
    families.update({v["candidate_id"]: v["family"] for v in synthetic["design"]["risk"]["classical_bindings"]})
    review = dict(status="PASS", research_id=j.ID, source_pins={
        str(Path(j.owner.__file__).resolve()): j.OWNER_SHA,
        str(Path(j.event.__file__).resolve()): j.EVENT_SHA,
        str(Path(j.__file__).resolve()): j.sha(j.__file__),
    })
    review_ref = write_json(run / (role + "_synthetic_review.json"), review)
    states = [dict(decision_date=d, state_ref=dict(path=str(synthetic["bank"] / f"state_{i}.joblib"),
                sha256="a" * 64), header_qualified=True, current_UID_qualified=True,
                numeric_qualified=True, full_U_keys_sha256="b" * 64)
              for i, d in enumerate(synthetic["dates"])]
    value = dict(phase="FULL752_NUMERIC_INPUT_QUALIFIED", research_id=j.ID,
                 role=role, family=families[role], design_sha256=synthetic["hashes"]["DESIGN_FREEZE.json"],
                 dag_sha256=synthetic["hashes"]["PHYSICAL_DAG.json"], source_review=review_ref,
                 full_required_dates_qualified=True, test2026_rows_read=0, states=states)
    if mutate:
        mutate(value)
    return write_json(run / (role + "_numeric_gate.json"), value)


def activate(synthetic, role="C14_RX_HGB_LW"):
    journal = j.RiskJournal(synthetic["run"])
    journal.activate_role(role, gate_for(synthetic, role))
    return journal


def first_node(journal, role="C14_RX_HGB_LW"):
    return next(n for n, s in journal.slots.items() if s["candidate_id"] == role)


def test_baseline_opaque_hashes_original_files_untouched_and_one_delta(synthetic):
    before = {name: (synthetic["run"] / name).read_bytes() for name in synthetic["hashes"]}
    journal = activate(synthetic)
    assert journal.counts()["combined_fit_slots"] == 670
    assert journal.counts()["conditional_unreserved"] == 130
    assert len(journal.slots) == 144
    assert {name: (synthetic["run"] / name).read_bytes() for name in before} == before
    assert journal.path.name == "RISK_EXECUTION_DELTA.jsonl"
    assert not (synthetic["run"] / "risk_execution").exists()


def test_baseline_hash_conflict_blocks_before_delta_creation(synthetic):
    (synthetic["run"] / "SOLVE_LEDGER.json").write_bytes(b"changed")
    with pytest.raises(j.RiskJournalBlocked, match="PHYSICAL_AUTHORITY_PIN_CHANGED"):
        j.RiskJournal(synthetic["run"])
    assert not (synthetic["run"] / "RISK_EXECUTION_DELTA.jsonl").exists()


def test_baseline_change_after_open_blocks_mutation(synthetic):
    journal = j.RiskJournal(synthetic["run"])
    (synthetic["run"] / "FIT_LEDGER.json").write_bytes(b"changed")
    with pytest.raises(j.RiskJournalBlocked, match="PHYSICAL_AUTHORITY_CHANGED"):
        journal.activate_role("C14_RX_HGB_LW", gate_for(synthetic))


@pytest.mark.parametrize("change", [
    lambda d: d.update(physical_fit_hard_cap=1801),
    lambda d: d.update(admissible_solve_request_ceiling=30001),
    lambda d: d.update(failed_reservation_refund=True),
    lambda d: d["conditional_risk_fit_nodes"].__setitem__(1, copy.deepcopy(d["conditional_risk_fit_nodes"][0])),
    lambda d: d["solve_request_ids"].__setitem__(1, d["solve_request_ids"][0]),
])
def test_original_dag_caps_and_unique_named_namespace_cannot_change(synthetic, change):
    change(synthetic["dag"])
    ref = write_json(synthetic["run"] / "PHYSICAL_DAG.json", synthetic["dag"])
    synthetic["hashes"]["PHYSICAL_DAG.json"] = ref["sha256"]
    with pytest.raises(j.RiskJournalBlocked):
        j.RiskJournal(synthetic["run"])
    assert not (synthetic["run"] / "RISK_EXECUTION_DELTA.jsonl").exists()


@pytest.mark.parametrize("mutation,reason", [
    (lambda v: v.update(phase="SOURCE_ONLY_PASS"), "INDEPENDENT_FULL752"),
    (lambda v: v["states"].pop(), "FULL752_NUMERIC_GATE_NO_SHORTENING"),
    (lambda v: v["states"][0].update(numeric_qualified=False), "ALL_STATE_HEADER_UID_NUMERIC"),
    (lambda v: v["states"][0].update(current_UID_qualified=False), "ALL_STATE_HEADER_UID_NUMERIC"),
    (lambda v: v["states"][0]["state_ref"].update(sha256="wrong"), "EXACT_ORIGINAL_R5_STATE"),
    (lambda v: v.update(test2026_rows_read=1), "INDEPENDENT_FULL752"),
])
def test_source_only_shortened_missing_uid_or_unqualified_numeric_cannot_reserve(synthetic, mutation, reason):
    journal = j.RiskJournal(synthetic["run"])
    with pytest.raises(j.RiskJournalBlocked, match=reason):
        journal.activate_role("C14_RX_HGB_LW", gate_for(synthetic, mutate=mutation))
    assert journal.counts()["conditional_reserved"] == 0


def test_current_two_rx_heads_only_max28_and_gate_requires_source_review(synthetic):
    journal = activate(synthetic)
    journal.activate_role("C14_RX_XGB_QQQ_RESIDUAL", gate_for(synthetic, "C14_RX_XGB_QQQ_RESIDUAL"))
    assert journal.counts()["conditional_reserved"] == 28
    assert journal.counts()["combined_fit_slots"] == 684
    assert sum(s["status"] == "UNRESERVED" for s in journal.slots.values()) == 116
    with pytest.raises(j.RiskJournalBlocked, match="RX_FAMILY_NOT_CURRENTLY_QUALIFIED"):
        journal.activate_role("C14_RX_RIDGE_DIAG", gate_for(synthetic, "C14_RX_RIDGE_DIAG"))


def test_missing_exact_source_pin_blocks_full_numeric_gate(synthetic):
    journal = j.RiskJournal(synthetic["run"])
    ref = gate_for(synthetic)
    gate = json.loads(Path(ref["path"]).read_text())
    review = json.loads(Path(gate["source_review"]["path"]).read_text())
    review["source_pins"].pop(str(Path(j.__file__).resolve()))
    gate["source_review"] = write_json(Path(gate["source_review"]["path"]), review)
    ref = write_json(Path(ref["path"]), gate)
    with pytest.raises(j.RiskJournalBlocked, match="EXACT_REVIEWED_TRANSPORT_SOURCE_CLOSURE"):
        journal.activate_role("C14_RX_HGB_LW", ref)


@pytest.mark.parametrize("terminal", ["FAILED", "BLOCKED_DEPENDENCY"])
def test_fit_started_and_failed_never_retry_or_refund_even_after_reload(synthetic, terminal):
    journal = activate(synthetic)
    node = first_node(journal)
    with pytest.raises(j.RiskJournalBlocked, match="FIT_STARTED_TRANSITION"):
        journal.fit_ledger.finish(node, "COMPLETE", artifact={})
    assert journal.fit_ledger.begin(node, dict(cutoff="2023-07-01"))
    with pytest.raises(j.RiskJournalBlocked, match="ZERO_RETRY_RESERVED_ONLY"):
        journal.fit_ledger.begin(node, dict(cutoff="2023-07-01"))
    journal.fit_ledger.entered(node)
    journal.fit_ledger.finish(node, terminal, error="synthetic")
    reopened = j.RiskJournal(synthetic["run"])
    assert reopened.slots[node]["entered"] == 1
    assert reopened.counts()["conditional_reserved"] == 14
    with pytest.raises(j.RiskJournalBlocked, match="ZERO_RETRY_RESERVED_ONLY"):
        reopened.fit_ledger.begin(node, dict(cutoff="2023-07-01"))


def test_complete_fit_exact_reuse_artifact_identity_and_immutable_ledger_view(synthetic):
    journal = activate(synthetic)
    node = first_node(journal)
    identity = dict(cutoff="2023-07-01", synthetic_input="abc")
    journal.fit_ledger.begin(node, identity)
    journal.fit_ledger.entered(node)
    model = synthetic["run"] / "risk_execution" / "models" / (j.owner.content_hash(node) + ".joblib")
    model.parent.mkdir(parents=True)
    model.write_bytes(b"synthetic model placeholder, never deserialized")
    journal.fit_ledger.finish(node, "COMPLETE", artifact=dict(path=str(model), sha256=j.sha(model)))
    assert journal.fit_ledger.begin(node, identity) is False
    view = journal.fit_ledger.value
    view["slots"][node]["entered"] = 0
    assert journal.slots[node]["entered"] == 1
    with pytest.raises(j.RiskJournalBlocked, match="EXACT_MODEL_REUSE_IDENTITY_CHANGED"):
        journal.fit_ledger.begin(node, dict(cutoff="2023-07-01", synthetic_input="different"))


def test_unreserved_unnamed_nodes_and_wrong_model_destination_cannot_call_fit(synthetic):
    journal = j.RiskJournal(synthetic["run"])
    node = first_node(journal)
    called = []
    with pytest.raises(j.RiskJournalBlocked, match="QUALIFIED_RX_RESERVATION"):
        journal.stored_fit(node, {}, synthetic["run"] / "models" / "old.joblib", lambda: called.append(True))
    with pytest.raises(j.RiskJournalBlocked, match="UNNAMED_CONDITIONAL_FIT"):
        journal.fit_ledger.begin("MODEL|OLD", {})
    assert called == []


def test_classical_charge_before_operation_exact_cache_and_resume_no_second_call(synthetic):
    journal = activate(synthetic, "C14_D01")
    token = "CLASSICAL|C14_D01|" + synthetic["dates"][0]
    seen = []
    identity = dict(state_sha256="c" * 64, raw_U_sha256="d" * 64)
    def operation():
        durable = json.loads(journal.path.read_text().splitlines()[-1])
        assert durable["action"] == "SOLVE_ENTER"
        seen.append(True)
        return dict(chosen_uids=["SYNTHETIC_UID"], receipt=dict(optimizer_solve_calls=1))
    result = journal.classical_request(token, identity, operation)
    assert result["chosen_uids"] == ["SYNTHETIC_UID"]
    reopened = j.RiskJournal(synthetic["run"])
    assert reopened.classical_request(token, identity, operation) == result
    assert seen == [True]
    assert reopened.counts()["combined_charged_solves"] == 18007
    with pytest.raises(j.RiskJournalBlocked, match="EXACT_CLASSICAL_CHECKPOINT_CHANGED"):
        reopened.classical_request(token, dict(state_sha256="different"), operation)


def test_classical_failed_and_charged_incomplete_never_resolve_or_refund(synthetic):
    journal = activate(synthetic, "C14_D01")
    first, second = ["CLASSICAL|C14_D01|" + d for d in synthetic["dates"][:2]]
    def fail():
        raise ValueError("SYNTHETIC_OWNER_FAILURE")
    with pytest.raises(ValueError, match="SYNTHETIC_OWNER_FAILURE"):
        journal.classical_request(first, dict(input="synthetic"), fail)
    journal.solve_callback(journal.run, second)
    reopened = j.RiskJournal(journal.run)
    assert reopened.requests[first]["status"] == "FAILED"
    assert reopened.requests[second]["status"] == "ENTERED"
    for token in (first, second):
        with pytest.raises(j.RiskJournalBlocked, match="BLOCKED_CHARGED_CLASSICAL_NO_COMPLETE_CACHE"):
            reopened.classical_request(token, dict(input="synthetic"), lambda: pytest.fail("re-solve"))
    assert reopened.counts()["combined_charged_solves"] == 18008


def test_combined_solve_cap_and_unnamed_old_main_requests_block_before_operation(synthetic, monkeypatch):
    journal = activate(synthetic, "C14_D01")
    for token in ("CLASSICAL|C14_D02|" + synthetic["dates"][0], "MAIN|SYNTHETIC|0",
                  "CLASSICAL|C14_D01|2026-01-01T00:00:00"):
        with pytest.raises(j.RiskJournalBlocked, match="UNNAMED_CONDITIONAL_SOLVE"):
            journal.classical_request(token, dict(input="synthetic"), lambda: pytest.fail("optimizer"))
    monkeypatch.setattr(j, "BASELINE_SOLVES", 29542)
    token = "CLASSICAL|C14_D01|" + synthetic["dates"][0]
    with pytest.raises(j.RiskJournalBlocked, match="COMBINED_SOLVE_CAP_EXHAUSTED"):
        journal.classical_request(token, dict(input="synthetic"), lambda: pytest.fail("optimizer"))
    assert not journal.requests


def test_failed_fit_no_refund_or_entered_counter_overwrite(synthetic):
    journal = activate(synthetic)
    node = first_node(journal)
    journal.fit_ledger.begin(node, dict(cutoff="2023-07-01"))
    journal.fit_ledger.entered(node)
    with pytest.raises(j.RiskJournalBlocked, match="FIT_CONTROL_FIELDS_IMMUTABLE"):
        journal.fit_ledger.finish(node, "FAILED", entered=0)
    assert journal.slots[node]["status"] == "STARTED"
    assert journal.slots[node]["entered"] == 1


def test_concurrent_stale_writer_and_partial_delta_fail_closed(synthetic):
    first = activate(synthetic, "C14_D01")
    second = j.RiskJournal(first.run)
    token = "CLASSICAL|C14_D01|" + synthetic["dates"][0]
    first.solve_callback(first.run, token)
    with pytest.raises(j.RiskJournalBlocked, match="DELTA_CHANGED_OR_CONCURRENT_WRITER"):
        second.solve_callback(second.run, token)
    with first.path.open("ab") as stream:
        stream.write(b'{"partial":')
    with pytest.raises(j.RiskJournalBlocked, match="INCOMPLETE_DELTA_ROW"):
        j.RiskJournal(first.run)


def test_hybrid_existing_kernel_is_bound_once_without_mutating_owner_globals(synthetic, monkeypatch):
    journal = activate(synthetic)
    date_value = synthetic["dates"][-1]
    token = "HYBRID|C14_RX_HGB_LW|" + date_value
    original_globals = j.owner.checkpoint_decode.__globals__
    originals = {key: original_globals[key] for key in ("solve_state", "solve_callback", "complete_solve")}
    probes = []
    def binder(function, **kwargs):
        assert function is j.owner.checkpoint_decode
        assert kwargs["expected_sha256"] == j.OWNER_SHA
        deps = kwargs["dependencies"]
        assert set(deps) == set(originals)
        def kernel(run, named, raw, geometry, score, candidate, eligible):
            probes.append(True)
            deps["solve_callback"](run, named)
            raise ValueError("SYNTHETIC_MATCHER_FAILURE")
        return kernel
    monkeypatch.setattr(j.event, "bind_pinned_kernel", binder)
    with pytest.raises(ValueError, match="SYNTHETIC_MATCHER_FAILURE"):
        journal.checkpoint_decode(token, None, None, None, "C14_RX_HGB_LW", None)
    assert probes == [True]
    assert journal.requests[token]["status"] == "FAILED"
    assert all(original_globals[k] is v for k, v in originals.items())


def test_cached_request_view_returns_isolated_row_and_same_byte_resume(synthetic):
    journal = activate(synthetic, "C14_D01")
    token = "CLASSICAL|C14_D01|" + synthetic["dates"][0]
    journal.classical_request(token, dict(input="synthetic"), lambda: dict(chosen_uids=["synthetic"]))
    state = journal.solve_state(journal.run)
    state["requests"][token]["charged"] = 0
    assert journal.requests[token]["charged"] == 1
    with pytest.raises(TypeError):
        state["requests"][token] = {}
    bytes_before = journal.path.read_bytes()
    reopened = j.RiskJournal(journal.run)
    reopened.flush()
    assert reopened.path.read_bytes() == bytes_before


def test_block_remaining_terminalizes_only_unused_active_reservations_without_refund(synthetic):
    journal = activate(synthetic)
    nodes = sorted(n for n, s in journal.slots.items() if s["candidate_id"] == "C14_RX_HGB_LW")
    started = nodes[0]
    journal.fit_ledger.begin(started, dict(cutoff="2023-07-01"))
    journal.fit_ledger.entered(started)
    journal.fit_ledger.finish(started, "FAILED", error="synthetic capacity failure")
    before = journal.counts()
    blocked = journal.block_remaining("C14_RX_HGB_LW", "all synthetic capacities failed")
    assert blocked == nodes[1:]
    assert journal.slots[started]["status"] == "FAILED"
    assert journal.slots[started]["entered"] == 1
    assert all(journal.slots[n]["status"] == "BLOCKED_DEPENDENCY"
               and journal.slots[n]["entered"] == 0 for n in blocked)
    assert journal.counts() == before
    last = json.loads(journal.path.read_text().splitlines()[-1])
    assert last["action"] == "BLOCK_REMAINING"
    assert not any(s["status"] in {"RESERVED", "STARTED"} for s in journal.slots.values()
                   if s["candidate_id"] == "C14_RX_HGB_LW")
    reopened = j.RiskJournal(journal.run)
    stable = reopened.path.read_bytes()
    assert reopened.block_remaining("C14_RX_HGB_LW", "same terminal dependency") == []
    assert reopened.path.read_bytes() == stable
    for node in blocked:
        with pytest.raises(j.RiskJournalBlocked, match="ZERO_RETRY_RESERVED_ONLY"):
            reopened.fit_ledger.begin(node, dict(cutoff="2023-07-01"))


def test_block_remaining_cannot_hide_started_or_unactivated_fit(synthetic):
    journal = j.RiskJournal(synthetic["run"])
    with pytest.raises(j.RiskJournalBlocked, match="ACTIVATED_CURRENT_RX_ROLE_REQUIRED"):
        journal.block_remaining("C14_RX_HGB_LW", "source only")
    journal.activate_role("C14_RX_HGB_LW", gate_for(synthetic))
    node = first_node(journal)
    journal.fit_ledger.begin(node, dict(cutoff="2023-07-01"))
    stable = journal.path.read_bytes()
    with pytest.raises(j.RiskJournalBlocked, match="UNRESOLVED_STARTED_FIT"):
        journal.block_remaining("C14_RX_HGB_LW", "cannot silently drop started trial")
    assert journal.path.read_bytes() == stable
    assert journal.slots[node]["status"] == "STARTED"


def test_only_reviewed_risk_execution_model_path_and_exact_node_name_allowed(synthetic):
    journal = activate(synthetic)
    node = first_node(journal)
    name = j.owner.content_hash(node) + ".joblib"
    expected = journal.run / "risk_execution" / "models" / name
    assert journal.model_destination(expected, node) == expected
    for destination in (journal.run / "risk_delta" / "models" / name,
                        journal.run / "models" / name,
                        journal.run / "risk_execution" / "models" / "different.joblib"):
        with pytest.raises(j.RiskJournalBlocked):
            journal.model_destination(destination, node)


def test_backend_entry_combined_cap_blocks_before_entered_event(synthetic, monkeypatch):
    journal = activate(synthetic)
    node = first_node(journal)
    journal.fit_ledger.begin(node, dict(cutoff="2023-07-01"))
    stable = journal.path.read_bytes()
    monkeypatch.setattr(j, "FIT_CAP", 656)
    with pytest.raises(j.RiskJournalBlocked, match="COMBINED_BACKEND_CAP_EXHAUSTED"):
        journal.fit_ledger.entered(node)
    assert journal.slots[node]["entered"] == 0
    assert journal.path.read_bytes() == stable



@pytest.fixture
def source_guard(synthetic, monkeypatch):
    """Fixed terminal/source bridge made wholly from synthetic state and code."""
    journal = j.RiskJournal(synthetic["run"])
    current_sources = {relative: j.sha(j.REPO / relative) for relative in j.SOURCE_GUARD_SOURCES}
    monkeypatch.setattr(j, "SOURCE_GUARD_SOURCES", current_sources)
    original_pins = {str((j.REPO / relative).resolve()): value for relative, value in current_sources.items()}
    original_pins.update({str(Path(j.owner.__file__).resolve()): j.OWNER_SHA,
                          str(Path(j.event.__file__).resolve()): j.EVENT_SHA})
    review_ref = write_json(journal.run / "RISK_INPUT_SOURCE_REVIEW_R3.json",
                            dict(status="PASS", research_id=j.ID, source_pins=original_pins))
    gates = {}
    for role in sorted(j.SOURCE_GUARD_ROLES):
        gate = gate_for(synthetic, role, mutate=lambda v: v.update(source_review=review_ref))
        journal.activate_role(role, gate)
        gates[role] = json.loads(Path(gate["path"]).read_text())
    for role in j.ACTIVE_RX:
        journal.block_remaining(role, j.SOURCE_GUARD_BLOCK_REASON)
    token = "CLASSICAL|C14_D01|" + synthetic["dates"][0]
    journal.classical_request(token, dict(synthetic="fixed"), lambda: dict(synthetic="opaque-cache"))
    root = journal.run / "risk_execution" / "source_metadata_recovery_r1"
    qualification = write_json(root / "INPUT_QUALIFICATION_R1.json", dict(research_id=j.ID, roles=gates))
    raw = journal.path.read_bytes()
    prefix = dict(bytes=len(raw), lines=raw.count(b"\n"), sha256=j.sha(journal.path))
    monkeypatch.setattr(j, "SOURCE_GUARD_PREFIX", prefix)
    monkeypatch.setattr(j, "SOURCE_GUARD_CHARGED", 1)
    terminal = write_json(root / "RISK_DECISIONS_TERMINAL_R1.json", dict(
        status="RISK_DECISIONS_TERMINAL_JOINT_DELIVERY_PENDING", research_id=j.ID,
        delta=dict(path=str(journal.path), sha256=prefix["sha256"]),
        input_qualification=qualification, review_ref=review_ref,
        reserved_fit_slots=28, backend_entered=0, complete_fit_slots=0,
        failed_fit_slots=0, blocked_fit_slots=28, charged_solves=1,
        combined_charged_solves=j.BASELINE_SOLVES + 1, scientific_retry=0, test2026_rows_read=0))
    audit = write_json(root / "CHECKPOINT_CLASSICAL_RESUME_COMPLETE_R2.json", dict(
        research_id=j.ID, terminal=terminal, RX_reopened=False, preserved_engineering_blocked_fit_slots=28))
    refs = dict(original_source_review=review_ref, qualification=qualification,
                prior_terminal=terminal, prior_audit=audit)
    monkeypatch.setattr(j, "SOURCE_GUARD_REFS", {
        key: (str(Path(ref["path"]).relative_to(journal.run)), ref["sha256"]) for key, ref in refs.items()})
    backups = {}
    for relative, expected in current_sources.items():
        source = (j.REPO / relative).resolve()
        backup = journal.run / j.SOURCE_GUARD_BACKUP_ROOT / Path(relative).parent.name / source.name
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(source.read_bytes())
        backups[str(source)] = dict(path=str(backup), sha256=expected)
    value = dict(schema="C14_TERMINAL_SOURCE_GUARD_RECOVERY_V1", status="PASS", research_id=j.ID,
        classification="TERMINAL_BOUND_SOURCE_GUARD_ENGINEERING_ONLY", independent_review=True,
        scientific_contract_changed=False, scientific_retry=0, test2026_rows_read=0,
        source_pins=original_pins, source_backups=backups,
        recover_rx_nodes=sorted(n for n, s in journal.slots.items() if s["candidate_id"] in j.ACTIVE_RX),
        prior_delta=dict(path=str(journal.path), **prefix), **refs)
    reference = write_json(journal.run / j.SOURCE_GUARD_REVIEW_NAME, value)
    return dict(journal=journal, ref=reference, review=value, raw=raw, token=token,
                path=journal.run / j.SOURCE_GUARD_REVIEW_NAME)


def guard_open(value):
    return j.RiskJournal(value["journal"].run, source_guard_recovery_ref=value["ref"])


def test_source_guard_exact28_additive_once_replay_preserves_history_budget_and_cache(source_guard):
    journal = guard_open(source_guard)
    before = journal.counts()
    cache = copy.deepcopy(journal.requests)
    blocks = copy.deepcopy(journal._block_history)
    assert journal.recover_source_guard_zero_entry(source_guard["ref"]) == source_guard["review"]["recover_rx_nodes"]
    assert journal.path.read_bytes().startswith(source_guard["raw"])
    assert journal.counts() == before and journal.requests == cache and journal._block_history == blocks
    assert all(journal.slots[n]["status"] == "RESERVED"
               and journal.slots[n]["error"] == j.SOURCE_GUARD_BLOCK_REASON
               and journal.slots[n]["dependency_only"] is True
               and journal.slots[n]["source_guard_recovery_ref"] == source_guard["ref"]
               for n in source_guard["review"]["recover_rx_nodes"])
    last = json.loads(journal.path.read_text().splitlines()[-1])
    assert last["action"] == "SOURCE_GUARD_ZERO_ENTRY" and set(last["data"]) == {"review_ref", "nodes"}
    # Replay takes the approved custody from the event itself.
    replayed = j.RiskJournal(journal.run)
    assert replayed.slots == journal.slots and replayed._source_guard_recovered
    assert replayed.requests == cache and len(replayed.roles) == 8
    with pytest.raises(j.RiskJournalBlocked, match="ONCE_ONLY"):
        replayed.recover_source_guard_zero_entry(source_guard["ref"])
    replayed.classical_request(source_guard["token"], dict(synthetic="fixed"), lambda: pytest.fail("second solve"))


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(status="FAIL"),
    lambda r: r.update(independent_review=False),
    lambda r: r.update(scientific_contract_changed=True),
    lambda r: r.update(scientific_retry=True),
    lambda r: r.update(test2026_rows_read=1),
    lambda r: r["recover_rx_nodes"].pop(),
    lambda r: r["source_backups"].pop(next(iter(r["source_backups"]))),
    lambda r: r["source_pins"].pop(str(Path(j.__file__).resolve())),
    lambda r: r["prior_delta"].update(lines=1),
    lambda r: r["qualification"].update(sha256="f" * 64),
    lambda r: r["prior_terminal"].update(path=str(Path(r["prior_terminal"]["path"]).with_name("other.json"))),
])
def test_source_guard_review_missing_changed_authority_refuses_before_append(source_guard, mutation):
    mutation(source_guard["review"])
    source_guard["ref"] = write_json(source_guard["path"], source_guard["review"])
    with pytest.raises(j.RiskJournalBlocked):
        guard_open(source_guard)
    assert source_guard["journal"].path.read_bytes() == source_guard["raw"]


@pytest.mark.parametrize("mutation", [
    lambda journal, node: journal.slots[node].update(status="STARTED"),
    lambda journal, node: journal.slots[node].update(status="FAILED"),
    lambda journal, node: journal.slots[node].update(entered=1),
    lambda journal, node: journal.slots[node].update(identity={}),
    lambda journal, node: journal.slots[node].update(event=None),
    lambda journal, node: journal.slots[node].update(artifact={}),
    lambda journal, node: journal.slots[node].update(error="different engineering failure"),
    lambda journal, node: journal.slots[node].update(dependency_only=False),
    lambda journal, node: setattr(journal, "_fit_seen", True),
    lambda journal, node: journal._block_history[next(iter(j.ACTIVE_RX))][0].update(reason="different"),
    lambda journal, node: journal.requests[next(iter(journal.requests))].update(status="ENTERED"),
    lambda journal, node: journal.requests[next(iter(journal.requests))].update(status="FAILED"),
    lambda journal, node: journal.roles.pop("C14_D10"),
])
def test_source_guard_scientific_or_partial_engineering_state_never_reopens(source_guard, mutation):
    journal = guard_open(source_guard)
    mutation(journal, source_guard["review"]["recover_rx_nodes"][0])
    before = copy.deepcopy(journal.slots)
    with pytest.raises(j.RiskJournalBlocked):
        journal.recover_source_guard_zero_entry(source_guard["ref"])
    assert journal.path.read_bytes() == source_guard["raw"] and journal.slots == before


@pytest.mark.parametrize("kind", ["model", "sidecar", "prediction", "role-artifact"])
def test_source_guard_artifact_presence_refuses_without_reading_contents(source_guard, kind):
    journal = guard_open(source_guard)
    node = source_guard["review"]["recover_rx_nodes"][0]
    role = journal.slots[node]["candidate_id"]
    model = journal.run / "risk_execution" / "models" / (j.owner.content_hash(node) + ".joblib")
    destinations = dict(model=model, sidecar=model.with_name(model.name + ".partial"),
        prediction=journal.run / "predictions" / (role + ".parquet"),
        **{"role-artifact": journal.run / "risk_execution" / "source_guard_recovery_r1" / role / "panel.parquet"})
    destination = destinations[kind]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"SYNTHETIC_DO_NOT_DESERIALIZE")
    with pytest.raises(j.RiskJournalBlocked, match="ARTIFACT"):
        journal.recover_source_guard_zero_entry(source_guard["ref"])
    assert journal.path.read_bytes() == source_guard["raw"]


def test_source_guard_source_bridge_is_exact_four_preserves_original_gate_and_other_pin(source_guard, monkeypatch):
    actual_sha = j.sha
    own = Path(j.__file__).resolve()
    # Simulate a source-only successor hash without modifying the real file.
    monkeypatch.setattr(j, "sha", lambda path: "f" * 64 if Path(path).resolve() == own else actual_sha(path))
    source_guard["review"]["source_pins"][str(own)] = "f" * 64
    source_guard["ref"] = write_json(source_guard["path"], source_guard["review"])
    with pytest.raises(j.RiskJournalBlocked, match="EXACT_REVIEWED_TRANSPORT"):
        j.RiskJournal(source_guard["journal"].run)
    journal = guard_open(source_guard)
    assert all(v["qualification_ref"] == source_guard["journal"].roles[r]["qualification_ref"]
               for r, v in journal.roles.items())
    assert journal.pins[str(own)][0] == "f" * 64
    # A changed untouched owner cannot use the four-file exception.
    monkeypatch.setattr(j, "sha", lambda path: "e" * 64 if Path(path).resolve() == Path(j.owner.__file__).resolve()
                        else ("f" * 64 if Path(path).resolve() == own else actual_sha(path)))
    with pytest.raises(j.RiskJournalBlocked, match="PHYSICAL_AUTHORITY_PIN_CHANGED"):
        guard_open(source_guard)


def test_source_guard_failed_append_rolls_back_nested_slots_flags_and_history(source_guard, monkeypatch):
    journal = guard_open(source_guard)
    before = copy.deepcopy((journal.slots, journal._block_history))
    @j.contextmanager
    def reject(stream):
        raise OSError("SYNTHETIC_LOCK_REJECT")
        yield
    monkeypatch.setattr(j, "exclusive", reject)
    with pytest.raises(OSError, match="SYNTHETIC_LOCK_REJECT"):
        journal.recover_source_guard_zero_entry(source_guard["ref"])
    assert (journal.slots, journal._block_history) == before and not journal._source_guard_recovered
    assert journal.path.read_bytes() == source_guard["raw"]


def test_source_guard_stale_parallel_writer_and_partial_prefix_cannot_reopen(source_guard):
    first, second = guard_open(source_guard), guard_open(source_guard)
    first.recover_source_guard_zero_entry(source_guard["ref"])
    with pytest.raises(j.RiskJournalBlocked, match="DELTA_CHANGED_OR_CONCURRENT"):
        second.recover_source_guard_zero_entry(source_guard["ref"])
    with first.path.open("ab") as stream:
        stream.write(b'{"partial":')
    with pytest.raises(j.RiskJournalBlocked, match="INCOMPLETE_DELTA_ROW"):
        j.RiskJournal(first.run)


def test_source_guard_applied_recovery_does_not_allow_started_retry_after_replay(source_guard):
    journal = guard_open(source_guard)
    journal.recover_source_guard_zero_entry(source_guard["ref"])
    node = source_guard["review"]["recover_rx_nodes"][0]
    journal.fit_ledger.begin(node, dict(cutoff=journal.slots[node]["cutoff"]))
    journal.fit_ledger.entered(node)
    journal.fit_ledger.finish(node, "FAILED", error="synthetic scientific failure")
    reopened = j.RiskJournal(journal.run)
    with pytest.raises(j.RiskJournalBlocked, match="ZERO_RETRY_RESERVED_ONLY"):
        reopened.fit_ledger.begin(node, dict(cutoff=reopened.slots[node]["cutoff"]))
    assert reopened.slots[node]["entered"] == 1 and reopened.slots[node]["status"] == "FAILED"


def test_source_guard_direct_emit_cannot_bypass_same_artifact_gate(source_guard):
    journal = guard_open(source_guard)
    nodes = source_guard["review"]["recover_rx_nodes"]
    model = journal.run / "risk_execution" / "models" / (j.owner.content_hash(nodes[0]) + ".joblib")
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"SYNTHETIC_OPAQUE_FORBIDDEN_MODEL")
    before = copy.deepcopy(journal.slots)
    with pytest.raises(j.RiskJournalBlocked, match="ARTIFACT"):
        journal.emit("SOURCE_GUARD_ZERO_ENTRY", dict(review_ref=source_guard["ref"], nodes=nodes))
    assert journal.slots == before and not journal._source_guard_recovered
    assert journal.path.read_bytes() == source_guard["raw"]


def test_source_guard_artifact_appearing_at_append_lock_refuses_atomically(source_guard, monkeypatch):
    journal = guard_open(source_guard)
    nodes = source_guard["review"]["recover_rx_nodes"]
    model = journal.run / "risk_execution" / "models" / (j.owner.content_hash(nodes[0]) + ".joblib")
    original_lock = j.exclusive
    @j.contextmanager
    def artifact_at_lock(stream):
        with original_lock(stream):
            model.parent.mkdir(parents=True, exist_ok=True)
            model.write_bytes(b"SYNTHETIC_ARTIFACT_RACE")
            yield
    monkeypatch.setattr(j, "exclusive", artifact_at_lock)
    before = copy.deepcopy(journal.slots)
    with pytest.raises(j.RiskJournalBlocked, match="ARTIFACT"):
        journal.recover_source_guard_zero_entry(source_guard["ref"])
    assert journal.slots == before and not journal._source_guard_recovered
    assert journal.path.read_bytes() == source_guard["raw"]



@pytest.fixture
def post_reboot(source_guard, synthetic, monkeypatch):
    """A smaller synthetic solve checkpoint, with all original28 fit nodes."""
    old = source_guard["review"]
    source_values = {rel: j.sha(j.REPO / rel) for rel in j.POST_REBOOT_SOURCES}
    monkeypatch.setattr(j, "POST_REBOOT_SOURCES", source_values)
    post_pins = {str((j.REPO / rel).resolve()): h for rel, h in source_values.items()}
    old["source_pins"].update(post_pins)
    # All runtime refs are code only; no imports, native states or real results.
    runtime_pins = dict(old["source_pins"])
    for name in ("aggregate_13f_retest", "aggregate_frozen_runner", "demo_performance",
                 "demo_performance_prices", "demo_rx_performance", "frozen_a94_profile",
                 "frozen_history_research_quote_domain", "frozen_test_authority", "hgb_policy_alignment",
                 "joint_account_replay", "joint_account_runtime", "joint_continuation",
                 "joint_control_sensitivity_qualification_r4", "joint_control_sensitivity_r4",
                 "joint_event_account_dispatch_r5", "joint_event_risk_execution_r5",
                 "joint_execution_resume", "joint_frozen_history_r3", "joint_frozen_history_r3_runner",
                 "joint_frozen_history_risk_bank_r3", "joint_frozen_history_risk_r3"):
        path = (j.REPO / "scripts/research/a2/evaluation" / (name + ".py")).resolve()
        runtime_pins[str(path)] = j.sha(path)
    assert len(runtime_pins) == 30
    run = synthetic["run"]
    r4 = dict(status="PASS", research_id=j.ID, source_pins=runtime_pins,
              synthetic_only="original runtime source closure")
    r4ref = write_json(run / "RISK_INPUT_SOURCE_REVIEW_R4.json", r4)
    old["runtime_source_review"] = r4ref
    old["original_config"] = write_json(run / "risk_execution/EXECUTION_INPUTS_R3.json",
                                      dict(synthetic_metadata=True))
    old["B_freeze"] = write_json(synthetic["bank"] / "R5_SCIENCE_AND_EXECUTION_FREEZE.json",
                                dict(synthetic_metadata=True))
    old["original_publication_admission"] = write_json(run / "R5_PUBLICATION_ADMISSION_R3.json",
                                                       dict(synthetic_metadata=True))
    old["snapshot_transport"] = dict(synthetic_original_transport="metadata only")
    old["completed_artifacts"] = {}
    for role in ("C14_D01", "C14_D02", "C14_D05", "C14_D06", "C14_G1", "C14_G4"):
        leaves = {}
        for key in ("panels", "predicted_risk", "variance_diagnostics"):
            path = run / "risk_execution/source_guard_recovery_r1" / role / (key + ".opaque")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"SYNTHETIC_OPAQUE_ROLE_OUTPUT_NO_DECODING")
            leaves[key] = dict(path=str(path), sha256=j.sha(path), rows=752)
        old["completed_artifacts"][role] = leaves
    source_guard["ref"] = write_json(source_guard["path"], old)
    journal = guard_open(source_guard)
    sequence = journal.sequence
    journal.recover_source_guard_zero_entry(source_guard["ref"])
    artifacts, rows = {}, []
    def synthetic_row(action, data):
        # Setup is canonical metadata replay, with one synthetic file append.
        # New tests exercise constructor/admission; existing tests exercise
        # durable emit and fit/solve callbacks separately.
        payload = dict(sequence=journal.sequence, previous=journal.previous, action=action, data=data)
        row = dict(payload, sha256=j.digest(payload))
        journal.accept(row)
        rows.append(j.canonical(row) + "\n")
    for node in old["recover_rx_nodes"]:
        synthetic_row("FIT_BEGIN", dict(node=node, identity=dict(cutoff=journal.slots[node]["cutoff"], synthetic=True)))
        synthetic_row("FIT_ENTER", dict(node=node, event=dict(synthetic=True)))
        path = run / "risk_execution/models" / (j.owner.content_hash(node) + ".joblib")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"SYNTHETIC_OPAQUE_MODEL_NOT_JOBLIB")
        ref = dict(path=str(path), sha256=j.sha(path))
        synthetic_row("FIT_FINISH", dict(node=node, status="COMPLETE", details=dict(artifact=ref)))
        artifacts[node] = ref
    counts = {role: 1 for role in j.POST_REBOOT_COUNTS}
    monkeypatch.setattr(j, "POST_REBOOT_COUNTS", counts)
    for role in ("C14_D05", "C14_D06", "C14_D09"):
        token = "CLASSICAL|" + role + "|" + synthetic["dates"][0]
        result = dict(opaque="cache")
        synthetic_row("SOLVE_ENTER", dict(token=token))
        synthetic_row("SOLVE_COMPLETE", dict(token=token, receipt=dict(identity=dict(synthetic="checkpoint"),
                      result=result, result_sha256=j.digest(result))))
    for role in j.ACTIVE_RX:
        token = "HYBRID|" + role + "|" + synthetic["dates"][-1]
        matching = [dict(synthetic="opaque matching cache")]
        synthetic_row("SOLVE_ENTER", dict(token=token))
        synthetic_row("SOLVE_COMPLETE", dict(token=token, receipt=dict(identity=dict(synthetic="checkpoint"),
                      matching_records=matching, matching_sha256=j.owner.content_hash(matching))))
    with journal.path.open("ab") as stream:
        stream.write("".join(rows).encode("utf-8"))
    journal.last_stamp = j.stamp(journal.path)
    raw = journal.path.read_bytes()
    prefix = dict(bytes=len(raw), lines=raw.count(b"\n"), sha256=j.sha(journal.path))
    monkeypatch.setattr(j, "POST_REBOOT_PREFIX", prefix)
    monkeypatch.setattr(j, "POST_REBOOT_EVENT_SEQUENCE", sequence)
    maintenance = run / "synthetic_maintenance"
    monkeypatch.setattr(j, "POST_REBOOT_MAINTENANCE", maintenance)
    marker = write_json(run / "risk_execution/source_guard_recovery_r1/SOURCE_GUARD_RECOVERY_STARTED_R1.json",
        dict(review=source_guard["ref"], runtime_source_review=r4ref,
             status="STARTED_TERMINAL_SOURCE_GUARD_ENGINEERING_RECOVERY",
             scientific_retry=0, test2026_rows_read=0))
    completed = copy.deepcopy(old["completed_artifacts"])
    rx_receipts = {}
    names = dict(assembly="HYBRID_ASSEMBLY.json", panel="scores_pre2026.parquet",
                 native_pairs="native_pairs_pre2026.parquet", matching="matching_pre2026.parquet")
    for role in j.ACTIVE_RX:
        leaves, refs = {}, []
        for key, name in names.items():
            path = run / "risk_execution/source_guard_recovery_r1" / role / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"SYNTHETIC_OPAQUE_RX_OUTPUT_NOT_JSON_OR_PARQUET")
            leaves[key] = dict(path=str(path), sha256=j.sha(path))
            refs.append(dict(leaves[key], bytes=path.stat().st_size))
        completed[role] = leaves
        rx_receipts[role] = dict(role=role, status="HYBRID_COMPLETE",
            strict_PIT_promotion_eligible=False, fit_begin=14, fit_enter=14, fit_finish=14,
            fit_complete=14, fit_failed=0, solve_enter=1, solve_complete=1,
            scientific_retry=0, forecast2026_rows=0, artifact_refs=refs)
    hgbref = write_json(maintenance / "TERMINAL_SOURCE_GUARD_HGB_COMPLETE_OBSERVATION_R1.json",
                        dict(hgb_completion=rx_receipts["C14_RX_HGB_LW"]))
    independent = write_json(maintenance / "TERMINAL_SOURCE_GUARD_RX_COMPLETE_OBSERVATION_R1.json",
        dict(hgb_completion_observation=hgbref, xgb_completion=rx_receipts["C14_RX_XGB_QQQ_RESIDUAL"]))
    reboot = write_json(maintenance / "POST_REBOOT_CHECKPOINT_OBSERVATION_R1.json",
                        dict(synthetic_preserved_checkpoint=True))
    fixed = dict(original_source_guard_review=source_guard["ref"], prior_runtime_source_review=r4ref,
                 old_marker=marker, reboot_receipt=reboot, independent_RX_completion=independent)
    monkeypatch.setattr(j, "POST_REBOOT_REFS", {key: (
        "maintenance" if key in {"reboot_receipt", "independent_RX_completion"} else "run",
        str(Path(ref["path"]).relative_to(maintenance if key in {"reboot_receipt", "independent_RX_completion"} else run)),
        ref["sha256"]) for key, ref in fixed.items()})
    backups = {}
    for rel, expected in source_values.items():
        path = (j.REPO / rel).resolve()
        suffix = (Path("tests") / ("training" if path.name.endswith("journal.py") else "evaluation")
                  if rel.startswith("tests/") else Path(rel).parent.name)
        backup = run / j.POST_REBOOT_BACKUP_ROOT / suffix / path.name
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(path.read_bytes())
        backups[str(path)] = dict(path=str(backup), sha256=expected)
    r5 = copy.deepcopy(r4)
    r5["prior_runtime_source_review"] = r4ref
    r5ref = write_json(run / "RISK_INPUT_SOURCE_REVIEW_R5.json", r5)
    review = dict(schema="C14_POST_REBOOT_CLASSICAL_CHECKPOINT_V1", status="PASS", research_id=j.ID,
        classification="POST_REBOOT_CLASSICAL_ONLY_CHECKPOINT_ENGINEERING", independent_review=True,
        scientific_contract_changed=False, scientific_retry=0, test2026_rows_read=0,
        source_pins=post_pins, source_backups=backups,
        runtime_source_review=r5ref, checkpoint_delta=dict(path=str(journal.path), **prefix),
        old_recovery_event=dict(sequence=sequence, review_ref=source_guard["ref"], nodes=old["recover_rx_nodes"]),
        input_qualification=old["qualification"], completed_fit_artifacts=artifacts,
        completed_role_artifacts=completed, remaining_classical_roles=["C14_D09", "C14_D10", "C14_D11"],
        snapshot_transport=old["snapshot_transport"], execution_configuration=old["original_config"],
        B_freeze=old["B_freeze"], original_publication_admission=old["original_publication_admission"], **fixed)
    assert set(review) == j.POST_REBOOT_FIELDS
    path = run / j.POST_REBOOT_REVIEW_NAME
    reference = write_json(path, review)
    return dict(journal=journal, review=review, ref=reference, path=path, raw=raw,
                old=old, old_ref=source_guard["ref"], r4=r4, r5=r5, synthetic=synthetic)


def post_open(value):
    return j.RiskJournal(value["journal"].run, post_reboot_checkpoint_ref=value["ref"])


def post_update(value):
    value["ref"] = write_json(value["path"], value["review"])


def test_post_reboot_exact_checkpoint_replay_opaque_artifacts_complete_cache_and_remaining_only(post_reboot):
    journal = post_open(post_reboot)
    assert journal._post_reboot_checked and journal._source_guard_recovered
    assert journal.sequence == j.POST_REBOOT_PREFIX["lines"] and len(journal.requests) == 6
    assert all(journal.slots[n]["status"] == "COMPLETE" for n in post_reboot["old"]["recover_rx_nodes"])
    stable = journal.path.read_bytes()
    assert stable == post_reboot["raw"]
    journal.classical_request("CLASSICAL|C14_D01|" + journal.dates[0], dict(synthetic="fixed"),
                              lambda: pytest.fail("completed old operation called"))
    assert journal.path.read_bytes() == stable
    # An allowed original date charges once; later journal constructors replay
    # the immutable checkpoint then the same canonical classical tail.
    token = "CLASSICAL|C14_D09|" + journal.dates[1]
    journal.classical_request(token, dict(synthetic="tail"), lambda: dict(opaque="new classical cache"))
    replay = post_open(post_reboot)
    replay.classical_request(token, dict(synthetic="tail"), lambda: pytest.fail("second tail operation"))
    assert replay.path.read_bytes().startswith(stable) and len(replay.requests) == 7
    assert replay._block_history == journal._block_history


def test_post_reboot_formal_closed_metadata_mutations_refuse_before_append(post_reboot):
    baseline = copy.deepcopy(post_reboot["review"])
    changes = [
        lambda r: r.update(extra=True), lambda r: r.update(status="FAIL"),
        lambda r: r.update(independent_review=False), lambda r: r.update(scientific_contract_changed=True),
        lambda r: r.update(scientific_retry=True), lambda r: r.update(test2026_rows_read=True),
        lambda r: r["source_pins"].pop(next(iter(r["source_pins"]))),
        lambda r: r["source_backups"].pop(next(iter(r["source_backups"]))),
        lambda r: r["source_pins"].update({str(j.REPO / "extra.py"): "a" * 64}),
        lambda r: r["checkpoint_delta"].update(lines=1),
        lambda r: r["old_recovery_event"].update(sequence=0),
        lambda r: r["remaining_classical_roles"].append("C14_D01"),
        lambda r: r["input_qualification"].update(sha256="f" * 64),
        lambda r: r["completed_fit_artifacts"].pop(next(iter(r["completed_fit_artifacts"]))),
        lambda r: r["completed_role_artifacts"].pop("C14_G1"),
        lambda r: r["completed_role_artifacts"]["C14_D01"]["panels"].update(sha256="f" * 64),
        lambda r: r["completed_role_artifacts"]["C14_RX_HGB_LW"]["panel"].update(path=str(j.RUN / "wrong.parquet")),
    ]
    for mutate in changes:
        post_reboot["review"] = copy.deepcopy(baseline)
        mutate(post_reboot["review"])
        post_update(post_reboot)
        with pytest.raises(j.RiskJournalBlocked):
            post_open(post_reboot)
        assert post_reboot["journal"].path.read_bytes() == post_reboot["raw"]


def test_post_reboot_only_journal_r5_increment_prior_chain_cannot_change(post_reboot):
    stable = copy.deepcopy(post_reboot["r5"])
    r5path = Path(post_reboot["review"]["runtime_source_review"]["path"])
    alterations = [
        lambda r: r.update(status="FAIL"), lambda r: r.update(research_id="OTHER"),
        lambda r: r["source_pins"].update({str(Path(j.owner.__file__).resolve()): "f" * 64}),
        lambda r: r["prior_runtime_source_review"].update(sha256="f" * 64),
        lambda r: r.update(extra=True),
    ]
    for mutate in alterations:
        value = copy.deepcopy(stable)
        mutate(value)
        post_reboot["review"]["runtime_source_review"] = write_json(r5path, value)
        post_update(post_reboot)
        with pytest.raises(j.RiskJournalBlocked, match="ONLY_JOURNAL_RUNTIME"):
            post_open(post_reboot)
        assert post_reboot["journal"].path.read_bytes() == post_reboot["raw"]


def test_post_reboot_dual_physical_backup_new_source_private_bridge_no_global_pin(post_reboot, monkeypatch):
    actual = j.sha
    own = Path(j.__file__).resolve()
    own_key = str(own)
    old_sha = post_reboot["review"]["source_pins"][own_key]
    monkeypatch.setattr(j, "sha", lambda path: "f" * 64 if Path(path).resolve() == own else actual(path))
    post_reboot["review"]["source_pins"][own_key] = "f" * 64
    post_reboot["r5"]["source_pins"][own_key] = "f" * 64
    post_reboot["review"]["runtime_source_review"] = write_json(
        Path(post_reboot["review"]["runtime_source_review"]["path"]), post_reboot["r5"])
    post_update(post_reboot)
    with pytest.raises(j.RiskJournalBlocked, match="PHYSICAL_AUTHORITY_PIN_CHANGED"):
        j.RiskJournal(post_reboot["journal"].run)
    journal = post_open(post_reboot)
    assert journal.pins[own_key][0] == "f" * 64
    with pytest.raises(j.RiskJournalBlocked, match="PHYSICAL_AUTHORITY_PIN_CHANGED"):
        journal.pin(own, old_sha)
    with pytest.raises(j.RiskJournalBlocked, match="EXACT_OLD_DECLARED"):
        journal._fixed_transport_pin(own, "f" * 64)
    backup = Path(post_reboot["review"]["source_backups"][own_key]["path"])
    backup.write_bytes(b"SYNTHETIC_ALTERED_OLD_BACKUP")
    with pytest.raises(j.RiskJournalBlocked, match="PHYSICAL_AUTHORITY_PIN_CHANGED"):
        post_open(post_reboot)


def test_post_reboot_old_authority_marker_and_completed_outputs_remain_continuously_pinned(post_reboot):
    journal = post_open(post_reboot)
    paths = [
        Path(post_reboot["old_ref"]["path"]),
        Path(post_reboot["review"]["prior_runtime_source_review"]["path"]),
        Path(post_reboot["review"]["old_marker"]["path"]),
        Path(post_reboot["review"]["independent_RX_completion"]["path"]),
        Path(post_reboot["review"]["completed_role_artifacts"]["C14_RX_HGB_LW"]["assembly"]["path"]),
        Path(post_reboot["review"]["completed_role_artifacts"]["C14_D05"]["panels"]["path"]),
        Path(next(iter(post_reboot["review"]["completed_fit_artifacts"].values()))["path"]),
    ]
    for path in paths:
        raw = path.read_bytes()
        path.write_bytes(raw + b"SYNTHETIC_CHANGED")
        with pytest.raises(j.RiskJournalBlocked, match="PHYSICAL_AUTHORITY"):
            journal.verify()
        with pytest.raises(j.RiskJournalBlocked):
            post_open(post_reboot)
        path.write_bytes(raw)
        # Reopen obtains restored current stamps; existing objects remain stale.
        journal = post_open(post_reboot)
    assert journal.path.read_bytes() == post_reboot["raw"]


def test_post_reboot_boundary_requires_complete_once_paired_exact_original_state(post_reboot):
    journal = post_open(post_reboot)
    snapshots = copy.deepcopy((journal.slots, journal.requests, journal.roles,
                               journal._block_history, journal._source_guard_recovered))
    node = post_reboot["old"]["recover_rx_nodes"][0]
    token = next(iter(journal.requests))
    mutations = [
        lambda x: x.slots[node].update(status="STARTED"),
        lambda x: x.slots[node].update(status="FAILED"),
        lambda x: x.slots[node].update(entered=0),
        lambda x: x.slots[node].update(artifact={"path": str(x.run / "wrong.joblib"), "sha256": "a"*64}),
        lambda x: x.requests[token].update(status="ENTERED"),
        lambda x: x.requests[token].update(status="FAILED"),
        lambda x: x.requests.pop(token),
        lambda x: x.roles.pop("C14_D11"),
        lambda x: x._block_history["C14_RX_HGB_LW"].append(copy.deepcopy(x._block_history["C14_RX_HGB_LW"][0])),
        lambda x: setattr(x, "_source_guard_recovered", False),
    ]
    for mutate in mutations:
        (journal.slots, journal.requests, journal.roles, journal._block_history,
         journal._source_guard_recovered) = copy.deepcopy(snapshots)
        journal._post_reboot_checked = False
        mutate(journal)
        with pytest.raises(j.RiskJournalBlocked):
            journal._post_reboot_boundary()
    assert journal.path.read_bytes() == post_reboot["raw"]


def test_post_reboot_tail_all_other_actions_tokens_and_repeat_recovery_refuse_without_append(post_reboot):
    journal = post_open(post_reboot)
    stable = journal.path.read_bytes()
    denied = [
        ("HEADER", {}), ("ACTIVATE_ROLE", {"role": "C14_D01"}),
        ("BLOCK_REMAINING", {"role": "C14_RX_HGB_LW"}),
        ("FIT_BEGIN", {"node": post_reboot["old"]["recover_rx_nodes"][0], "identity": {}}),
        ("FIT_ENTER", {"node": post_reboot["old"]["recover_rx_nodes"][0]}),
        ("FIT_FINISH", {"node": post_reboot["old"]["recover_rx_nodes"][0], "status": "COMPLETE"}),
        ("SOURCE_GUARD_ZERO_ENTRY", {"review_ref": post_reboot["old_ref"], "nodes": []}),
        ("SOLVE_ENTER", {"token": "HYBRID|C14_RX_HGB_LW|" + journal.dates[-1]}),
        ("SOLVE_ENTER", {"token": "CLASSICAL|C14_D01|" + journal.dates[1]}),
        ("SOLVE_ENTER", {"token": "CLASSICAL|C14_D09|" + journal.dates[0]}),
        ("SOLVE_ENTER", {"token": "CLASSICAL|C14_D10|2026-01-01T00:00:00"}),
    ]
    for action, data in denied:
        with pytest.raises(j.RiskJournalBlocked, match="POST_REBOOT"):
            journal.emit(action, data)
        assert journal.path.read_bytes() == stable
    with pytest.raises(j.RiskJournalBlocked):
        journal.recover_source_guard_zero_entry(post_reboot["old_ref"])
    assert journal.path.read_bytes() == stable


def test_post_reboot_tail_charged_failed_no_complete_never_retries(post_reboot):
    journal = post_open(post_reboot)
    token = "CLASSICAL|C14_D10|" + journal.dates[0]
    calls = []
    def failed():
        calls.append(1)
        raise ArithmeticError("SYNTHETIC_SCIENTIFIC_FAILURE")
    with pytest.raises(ArithmeticError):
        journal.classical_request(token, dict(synthetic="failed"), failed)
    replay = post_open(post_reboot)
    assert replay.requests[token]["status"] == "FAILED" and calls == [1]
    stable = journal.path.read_bytes()
    with pytest.raises(j.RiskJournalBlocked, match="NO_COMPLETE"):
        replay.classical_request(token, dict(synthetic="failed"), lambda: pytest.fail("scientific retry"))
    assert journal.path.read_bytes() == stable
    open_token = "CLASSICAL|C14_D11|" + replay.dates[0]
    replay.solve_callback(replay.run, open_token)
    reopened = post_open(post_reboot)
    with pytest.raises(j.RiskJournalBlocked, match="NO_COMPLETE"):
        reopened.classical_request(open_token, dict(synthetic="open"), lambda: pytest.fail("charged retry"))


@pytest.mark.parametrize("action,data", [
    ("ACTIVATE_ROLE", {"role": "C14_D03"}),
    ("FIT_BEGIN", {"node": "UNNAMED", "identity": {}}),
    ("SOLVE_ENTER", {"token": "CLASSICAL|C14_D01|2023-01-02T00:00:00"}),
    ("SOLVE_ENTER", {"token": "HYBRID|C14_RX_HGB_LW|2025-01-01T00:00:00"}),
])
def test_post_reboot_constructor_tail_replay_cannot_bypass_action_token_whitelist(post_reboot, action, data):
    journal = post_open(post_reboot)
    payload = dict(sequence=journal.sequence, previous=journal.previous, action=action, data=data)
    row = dict(payload, sha256=j.digest(payload))
    with journal.path.open("ab") as stream:
        stream.write((j.canonical(row) + "\n").encode("utf-8"))
    with pytest.raises(j.RiskJournalBlocked, match="POST_REBOOT"):
        post_open(post_reboot)
    assert journal.path.read_bytes().startswith(post_reboot["raw"])


def test_post_reboot_corrupted_or_partial_immutable_checkpoint_refuses_before_replay(post_reboot):
    path = post_reboot["journal"].path
    raw = post_reboot["raw"]
    path.write_bytes(raw[:-1])
    with pytest.raises(j.RiskJournalBlocked, match="PRESERVED_CHECKPOINT"):
        post_open(post_reboot)
    path.write_bytes(b"X" + raw[1:])
    with pytest.raises(j.RiskJournalBlocked, match="PRESERVED_CHECKPOINT"):
        post_open(post_reboot)
