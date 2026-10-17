"""Synthetic-only metadata bank projection tests; no real files or fitting."""
import builtins
import copy
from pathlib import Path

import pytest

from scripts.research.a2.evaluation.joint_frozen_history_risk_bank_r3 import (
    BankMetadataError, build_risk_bank, projection_sha256)
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash, LEARNED_KINDS

SHA = "a"*64
CUTOFF = "2024-06-28T20:00:00+00:00"
ASOF = "2024-07-01T20:00:00+00:00"


def ref(name):
    return {"path": "D:/synthetic_metadata/" + name, "sha256": SHA}


def event(name, kind="scaler", owner="full", *, synthetic=True, status="FIT_COMPLETE"):
    context = dict(cutoff=CUTOFF, assets=["S1", "S2"],
        identity_epoch={"epoch": "synthetic_epoch", "uids": {"S1": "U1", "S2": "U2"}},
        source_identity={"source_id": "synthetic_source", "sha256": SHA},
        horizon=5, return_coordinate="synthetic_coordinate",
        synthetic=synthetic, mechanism=not synthetic)
    e = dict(kind=kind, name=name, context=context, inputs_sha256=SHA, parameters={},
        owner_stage_id=owner, status=status, learned_states=int(kind in LEARNED_KINDS),
        dependencies=[])
    e["key"] = content_hash({k: e[k] for k in
        ("kind", "name", "context", "inputs_sha256", "parameters")})
    if status == "FIT_COMPLETE":
        e["result_sha256"] = SHA
    return e


def node(name, keys, increment, *, synthetic=True):
    return dict(risk_node=name, method="RB", as_of=ASOF, cutoff=CUTOFF,
        assets=["S1", "S2"], asset_uids={"S1": "U1", "S2": "U2"},
        asset_epochs={"S1": "E1", "S2": "E2"},
        status="PASS_SYNTHETIC" if synthetic else "PASS_FROZEN_HISTORY_MECHANISM",
        risk_state_id=SHA, artifact=ref(name+".joblib")["path"], sha256=SHA,
        learned_states=increment, fit_dependency_ids=keys)


def stage(sid, nodes, cumulative, role="FULL_REQUESTED_POOL", parents=()):
    return dict(stage_id=sid, research_id="SYNTHETIC_EXISTING_"+sid, domain_role=role,
        science_ref=ref(sid+"_science.json"), source_inputs_ref=ref("inputs.json"),
        support_ref=ref(sid+"_support.json"), execution_ref=ref(sid+"_execution.json"),
        audit_ref=ref(sid+"_audit.json"), producer_code_pins=[ref("producer.py")],
        parent_stage_ids=list(parents), producer_complete=True, expected_node_count=len(nodes),
        audit=dict(schema="B_R3_RISK_STAGE_COMPACT_AUDIT_V1", nodes=nodes,
            account_attempts=0, test2026_rows_read=0, strict_PIT_promotion_eligible=False,
            no_refund=True, retry_limit=0, risk_fit_units=cumulative,
            actual_new_fit_units=cumulative, b_cumulative_fit_units=968+cumulative))


def fixture(*, synthetic=True):
    a = event("mean", synthetic=synthetic)
    b = event("cov", "covariance", synthetic=synthetic)
    c = event("psd", "deterministic_transform", synthetic=synthetic)
    b["dependencies"] = [a["key"]]
    d = event("threshold", "regime_threshold", "component", synthetic=synthetic)
    full = node("full_rb", [a["key"], b["key"], c["key"]], 2, synthetic=synthetic)
    component = node("component_rr", [a["key"], b["key"], d["key"]], 1, synthetic=synthetic)
    component["method"] = "RR"
    component["parent_requested"] = ["S1", "S2", "S3"]
    component["excluded_reasons"] = {"S3": ["UNKNOWN_UID"]}
    component["parent_origin_window"] = ["2024-01-02T21:00:00+00:00"]
    stages = [stage("full", [full], 2), stage("component", [component], 3,
        "SOURCE_QUALIFIED_COMPONENT", ("full",))]
    return dict(stages=stages, reservations=[a,b,c,d],
        artifact_checks={full["artifact"]:SHA, component["artifact"]:SHA},
        budget_scope=dict(prior_ledger={"reserved":968}, branch_cumulative_cap=4096,
            effective_new_cap=2048, stage1_learned_cap=1024),
        reservation_receipt_ref=ref("fixed_reservation_projection.json"),
        other_incremental_fit_units=0, synthetic=synthetic)


def build(f):
    return build_risk_bank(**f, verified_projection_sha256=projection_sha256(**f))


def test_stage_increments_are_not_cumulative_counters_or_reused_closure_counts():
    r = build(fixture())
    receipt = r["fixed_count_receipt"]
    assert receipt["physical_events_total"] == 4
    assert receipt["learned_risk_fit_units"] == 3
    assert [s["learned_fit_units"] for s in receipt["stages"]] == [2, 1]
    assert [s["observed_cumulative_counters"]["risk_fit_units"] for s in receipt["stages"]] == [2, 3]
    assert receipt["B_cumulative_fit_units"] == 971
    assert receipt["per_kind"]["deterministic_transform"] == 1
    assert receipt["per_kind"]["regime_threshold"] == 1
    assert receipt["projectwide_global_verified"] is False
    assert receipt["authority"] == "PROJECTION_OF_EXISTING_DURABLE_RISK_LEDGER"
    assert r["manifest"]["stage_status"] == "COMPLETE_WITH_TYPED_DIAGNOSTICS"
    assert len(r["manifest"]["states"]) == 2
    assert r["manifest"]["states"][1]["component_metadata"]["excluded_reasons"]["S3"] == ["UNKNOWN_UID"]


def test_no_io_or_fitting_and_no_input_mutation(monkeypatch):
    f = fixture()
    original = copy.deepcopy(f)
    def forbid(*a, **k):
        raise AssertionError("I/O forbidden")
    monkeypatch.setattr(builtins, "open", forbid)
    monkeypatch.setattr(Path, "open", forbid)
    r = build(f)
    assert f == original
    r["manifest"]["states"][0]["assets"].append("MUTATED")
    assert f == original
    assert r["manifest"]["new_fits"] == r["manifest"]["new_account_paths"] == 0


def test_real_mechanism_metadata_is_explicitly_not_synthetic():
    r = build(fixture(synthetic=False))
    assert r["manifest"]["synthetic_metadata_test"] is False
    assert all(n["original_status"] == "PASS_FROZEN_HISTORY_MECHANISM" for n in r["manifest"]["states"])
    assert r["manifest"]["strict_PIT_promotion_eligible"] is False
    assert r["manifest"]["full_pool_policy_qualification_granted"] is False


@pytest.mark.parametrize("change", ["UNKNOWN", "MISMATCH"])
def test_unverified_artifact_is_diagnostic(change):
    f = fixture()
    path = f["stages"][0]["audit"]["nodes"][0]["artifact"]
    if change == "UNKNOWN":
        f["artifact_checks"].pop(path)
    else:
        f["artifact_checks"][path] = "b"*64
    r = build(f)
    assert len(r["manifest"]["states"]) == 1
    assert "ARTIFACT_PHYSICAL_HASH_UNKNOWN_OR_MISMATCH" in r["manifest"]["blocked_or_unverified_diagnostics"][0]["reasons"]


def test_pass_without_risk_state_identity_stays_diagnostic():
    f = fixture()
    f["stages"][0]["audit"]["nodes"][0].pop("risk_state_id")
    r = build(f)
    assert "RISK_STATE_ID_UNBOUND" in r["manifest"]["blocked_or_unverified_diagnostics"][0]["reasons"]


@pytest.mark.parametrize("status", ["FIT_FAILURE", "STARTED", "INTERRUPTED_UNKNOWN"])
def test_failed_or_unfinished_reservations_occupy_budget_and_are_not_reusable(status):
    f = fixture()
    e = f["reservations"][-1]
    e["status"] = status
    e.pop("result_sha256")
    r = build(f)
    assert r["fixed_count_receipt"]["learned_risk_fit_units"] == 3
    assert r["fixed_count_receipt"]["B_cumulative_fit_units"] == 971
    assert len(r["manifest"]["states"]) == 1
    assert r["fixed_count_receipt"]["no_refund"] is True
    if status == "FIT_FAILURE":
        assert r["fixed_count_receipt"]["failed_reservations"] == [e["key"]]
    else:
        assert r["manifest"]["stage_status"] == "PARTIAL_OR_UNFINISHED"


def test_original_block_is_never_relabelled_pass():
    f = fixture()
    n = f["stages"][1]["audit"]["nodes"][0]
    n.update(status="BLOCKED_RISK_STATE_SUPPORT", block_reason="SYNTHETIC_GENUINE_GAP")
    r = build(f)
    d = r["manifest"]["blocked_or_unverified_diagnostics"][0]
    assert d["original_block_reason"] == "SYNTHETIC_GENUINE_GAP"
    assert d["original_status"] == "BLOCKED_RISK_STATE_SUPPORT"
    assert d["reusable"] is False


def test_projection_digest_detects_post_verification_change():
    f = fixture()
    digest = projection_sha256(**f)
    f["stages"][0]["audit"]["nodes"][0]["as_of"] = "2024-07-02T20:00:00+00:00"
    with pytest.raises(BankMetadataError, match="VERIFIED_PROJECTION"):
        build_risk_bank(**f, verified_projection_sha256=digest)


@pytest.mark.parametrize("field", ["notes", "covariance", "mu", "nav", "returns", "y_open5"])
def test_raw_value_payload_never_admitted(field):
    f = fixture()
    f["stages"][0]["audit"]["nodes"][0][field] = [1,2]
    with pytest.raises(BankMetadataError, match="METADATA_PROJECTION_REQUIRED"):
        build(f)


@pytest.mark.parametrize("case", ["duplicate", "key", "child", "uid", "cost", "mode", "account"])
def test_physical_operation_binding_fail_closed(case):
    f = fixture()
    if case == "duplicate":
        f["reservations"].append(copy.deepcopy(f["reservations"][0]))
    elif case == "key":
        f["reservations"][0]["parameters"]["changed"] = True
    elif case == "child":
        f["reservations"][0]["dependencies"] = ["b"*64]
    elif case == "uid":
        f["stages"][0]["audit"]["nodes"][0]["asset_uids"]["S1"] = "OTHER"
    elif case == "cost":
        f["reservations"][0]["learned_states"] = 0
    elif case == "mode":
        f["reservations"][0]["context"]["mechanism"] = True
    else:
        f["reservations"][0]["kind"] = "account_replay"
    with pytest.raises(BankMetadataError):
        build(f)


@pytest.mark.parametrize("clock", ["2025-12-31T23:30:00-05:00", "2024-06-28T20:00:00", "2026-01-01T00:00:00Z"])
def test_cutoff_guard_uses_utc_and_rejects_naive_or_2026(clock):
    f = fixture()
    f["stages"][0]["audit"]["nodes"][0]["cutoff"] = clock
    with pytest.raises(BankMetadataError):
        build(f)


@pytest.mark.parametrize("field", ["account_attempts", "test2026_rows_read", "retry_limit"])
def test_boolean_zero_is_not_an_audit_count(field):
    f = fixture()
    f["stages"][0]["audit"][field] = False
    with pytest.raises(BankMetadataError, match="NONNEGATIVE_INTEGER"):
        build(f)


def test_stage_counter_gap_and_orphan_are_not_silently_final():
    f = fixture()
    extra = event("orphan", "scaler", "component")
    f["reservations"].append(extra)
    r = build(f)
    assert r["manifest"]["stage_status"] == "PARTIAL_OR_UNFINISHED"
    assert r["fixed_count_receipt"]["learned_risk_fit_units"] == 4
    assert r["fixed_count_receipt"]["unassigned_node_closure_keys"] == [extra["key"]]


def test_additive_correction_keeps_prior_diagnostics_and_accounts_unchanged():
    f = fixture()
    old = f["stages"][1]["audit"]["nodes"][0]
    old.update(status="BLOCKED_RR_SOURCE_BINDING", block_reason="ORIGINAL_PRESERVED")
    new_event = event("corrected_vol", "scaler", "rr_correction")
    f["reservations"].append(new_event)
    corrected = node("corrected_rr:future", [f["reservations"][0]["key"],f["reservations"][1]["key"],new_event["key"]], 1)
    corrected["method"] = "RR"
    f["stages"].append(stage("rr_correction", [corrected], 4,
        "ADDITIVE_RISK_CORRECTION", ("component",)))
    f["artifact_checks"][corrected["artifact"]] = SHA
    f["previous_bank_ref"] = ref("prior_bank.json")
    r = build(f)
    assert len(r["manifest"]["states"]) == 2
    assert r["manifest"]["blocked_or_unverified_diagnostics"][0]["original_block_reason"] == "ORIGINAL_PRESERVED"
    assert r["fixed_count_receipt"]["stages"][-1]["learned_fit_units"] == 1
    assert r["fixed_count_receipt"]["B_cumulative_fit_units"] == 972
    assert r["manifest"]["previous_bank"] == ref("prior_bank.json")
    assert r["manifest"]["new_account_paths"] == 0


@pytest.mark.parametrize("parents", [[], ["rr_correction"], ["UNKNOWN"]])
def test_additive_requires_preceding_parent_not_self_or_cycle(parents):
    f = fixture()
    f["stages"].append(stage("rr_correction", [], 3, "ADDITIVE_RISK_CORRECTION", parents))
    with pytest.raises(BankMetadataError, match="ADDITIVE_PARENT"):
        build(f)


def test_substate_reuse_requires_actual_retained_value_artifact():
    f = fixture()
    value = dict(operation_key=f["reservations"][0]["key"], value_sha256=SHA,
        artifact=ref("retained_mean.joblib"))
    f["substate_artifacts"] = [value]
    with pytest.raises(BankMetadataError, match="SUBSTATE_VALUE_ARTIFACT_NOT_VERIFIED"):
        build(f)
    f["artifact_checks"][value["artifact"]["path"]] = SHA
    r = build(f)
    assert len(r["manifest"]["learned_substate_artifacts"]) == 1
    assert r["manifest"]["states"][0]["riskstate_artifact_retains_all_substate_values"] is False
    f["substate_artifacts"].append(copy.deepcopy(value))
    with pytest.raises(BankMetadataError, match="DUPLICATE_RETAINED"):
        build(f)


@pytest.mark.parametrize("field,value", [("prior", 0), ("risk", 2048), ("branch", 4096.0)])
def test_frozen_budget_cannot_be_reset_or_reinterpreted(field, value):
    f = fixture()
    if field == "prior":
        f["budget_scope"]["prior_ledger"]["reserved"] = value
    elif field == "risk":
        f["budget_scope"]["stage1_learned_cap"] = value
    else:
        f["budget_scope"]["branch_cumulative_cap"] = value
    with pytest.raises(BankMetadataError):
        build(f)


def test_shared_risk_and_other_stage_caps_count_failures():
    f = fixture()
    f["other_incremental_fit_units"] = 2046
    f["reservations"][-1]["status"] = "FIT_FAILURE"
    f["reservations"][-1].pop("result_sha256")
    with pytest.raises(BankMetadataError, match="CAP_EXCEEDED"):
        build(f)


def test_risk_stage_hard_cap_counts_each_unique_physical_reservation():
    f = fixture()
    for i in range(1022):
        f["reservations"].append(event("synthetic_extra_"+str(i), "scaler"))
    with pytest.raises(BankMetadataError, match="CAP_EXCEEDED"):
        build(f)


def test_finished_prefix_is_not_complete_when_producer_or_plan_unbound():
    for field in ("producer_complete", "expected_node_count"):
        f = fixture()
        f["stages"][1].pop(field)
        assert build(f)["manifest"]["stage_status"] == "PARTIAL_OR_UNFINISHED"


def test_scaler_alone_does_not_prove_covariance_state_closure():
    f = fixture()
    f["stages"][0]["audit"]["nodes"][0]["fit_dependency_ids"] = [f["reservations"][0]["key"]]
    assert "RISK_COVARIANCE_CLOSURE_UNBOUND" in build(f)["manifest"]["blocked_or_unverified_diagnostics"][0]["reasons"]


def test_nested_child_reservation_cannot_be_omitted_from_reusable_closure():
    f = fixture()
    keys = f["stages"][0]["audit"]["nodes"][0]["fit_dependency_ids"]
    keys.remove(f["reservations"][0]["key"])
    assert "NODE_PHYSICAL_CLOSURE_INCOMPLETE" in build(f)["manifest"]["blocked_or_unverified_diagnostics"][0]["reasons"]


def projected(f, *, rr=False):
    from scripts.research.a2.evaluation.joint_frozen_history_risk_bank_r3 import project_fixed_reservations
    events = []
    for e in f["reservations"]:
        value = copy.deepcopy(e)
        value.pop("owner_stage_id")
        value.update(stage="risk", started_utc="2026-10-03T00:00:00+00:00")
        events.append(value)
    full_keys = [e["key"] for e in f["reservations"] if e["owner_stage_id"] == "full"]
    return project_fixed_reservations(f["stages"], list(reversed(events)),
        full_stage_id="full", component_stage_id="component",
        correction_stage_id="rr_correction" if rr else None,
        verified_full_operation_keys=full_keys)


def test_fixed_projection_matches_keys_and_closures_not_array_position():
    f = fixture()
    p = projected(f)
    assert [e["owner_stage_id"] for e in p] == ["component", "full", "full", "full"]
    assert all("started_utc" not in e and "stage" not in e for e in p)
    assert {e["key"] for e in p} == {e["key"] for e in f["reservations"]}
    f["reservations"] = p
    assert build(f)["fixed_count_receipt"]["learned_risk_fit_units"] == 3


def test_tagged_correction_projects_its_actual_owner_and_retains_parent():
    f = fixture()
    extra = event("corrected", "scaler", "rr_correction")
    extra.update(corrected_rr_node="corrected_rr:future", correction_freeze_sha256=SHA)
    f["reservations"].append(extra)
    n = node("corrected_rr:future", [f["reservations"][0]["key"], f["reservations"][1]["key"], extra["key"]], 1)
    n.update(method="RR", correction_envelope={"research_id":"SYNTHETIC_CORRECTION", "spec_sha256":SHA})
    f["stages"].append(stage("rr_correction", [n], 4, "ADDITIVE_RISK_CORRECTION", ("component",)))
    f["artifact_checks"][n["artifact"]] = SHA
    f["reservations"] = projected(f, rr=True)
    r = build(f)
    assert [s["learned_fit_units"] for s in r["fixed_count_receipt"]["stages"]] == [2,1,1]
    assert r["manifest"]["states"][-1]["correction_metadata"]["correction_envelope"]["spec_sha256"] == SHA


@pytest.mark.parametrize("case", ["unclaimed", "full_keys", "tag_unknown", "tag_freeze"])
def test_owner_projection_never_guesses_unknown_provenance(case):
    f = fixture()
    if case == "unclaimed":
        f["reservations"].append(event("orphan"))
        f["reservations"][-1]["owner_stage_id"] = "component"
    elif case == "full_keys":
        f["stages"][0]["audit"]["nodes"][0]["fit_dependency_ids"].pop()
    else:
        f["reservations"][-1].update(corrected_rr_node="corrected_rr:unknown",
            correction_freeze_sha256="b"*64)
    with pytest.raises(BankMetadataError):
        projected(f)


def test_node_strict_upgrade_refused():
    f = fixture()
    f["stages"][0]["audit"]["nodes"][0]["strict_PIT_promotion_eligible"] = True
    with pytest.raises(BankMetadataError, match="STRICT_PROMOTION"):
        build(f)


def producer_lines(value, indent=2):
    import json
    return (json.dumps(value, indent=indent, allow_nan=False)+"\n").splitlines(keepends=True)


def ledger_metadata_fixture():
    f = fixture()
    events = []
    for e in f["reservations"]:
        v = copy.deepcopy(e)
        v.pop("owner_stage_id")
        v.update(stage="risk", synthetic=True, mechanism=False)
        events.append(v)
    value = dict(status="FROZEN_HISTORY_RISK_COMPONENT_STAGE_COMPLETE",
        fit_attempts=971, inherited_fit_units=968, new_fit_units=3, risk_fit_units=3,
        records=[n for s in f["stages"] for n in s["audit"]["nodes"]],
        failures=[], physical_events=events, account_paths=2, test2026_rows_read=0)
    return f, value


def test_old_review_scanner_skips_whole_notes_before_value_or_child_key_decode(monkeypatch):
    import scripts.research.a2.evaluation.joint_frozen_history_risk_bank_r3 as bank
    f, value = ledger_metadata_fixture()
    value["records"][0]["notes"] = {"PRIVATE_NUMERIC_PAYLOAD_KEY": {
        "covariance":[[123456.789]], "mu":["PRIVATE_LEARNED_VALUE"]}}
    original = bank.json.loads
    calls = []
    def guarded(text, *a, **k):
        assert "123456.789" not in text
        assert "PRIVATE_NUMERIC_PAYLOAD_KEY" not in text
        assert "PRIVATE_LEARNED_VALUE" not in text
        calls.append(text)
        return original(text, *a, **k)
    lines = producer_lines(value)
    monkeypatch.setattr(bank.json, "loads", guarded)
    selected = bank.project_fixed_producer_lines(iter(lines), profile="ledger")
    assert "notes" not in selected["records"][0]
    assert selected["physical_events"] == value["physical_events"]
    assert calls
    from scripts.research.a2.evaluation.joint_frozen_history_risk_bank_r3 import project_fixed_reservations
    events = project_fixed_reservations(f["stages"], selected["physical_events"],
        full_stage_id="full", component_stage_id="component",
        verified_full_operation_keys=[e["key"] for e in f["reservations"] if e["owner_stage_id"]=="full"])
    assert events == f["reservations"]


@pytest.mark.parametrize("profile", ["full_audit", "component_audit"])
def test_fixed_audit_projection_preserves_legal_metadata(profile):
    from scripts.research.a2.evaluation.joint_frozen_history_risk_bank_r3 import project_fixed_producer_lines
    f = fixture()
    audit = copy.deepcopy(f["stages"][0]["audit"])
    audit.update(execution_freeze_sha256=SHA, risk_support_sha256=SHA,
        inherited_prior_reserved=968, workers=1, library_threads=2,
        implementation_lineage={"unread_body":{"matrix":[[999999.123]]}},
        notes={"mu":[999999.123]},
        projections=[dict(source="synthetic_y5",columns=["signal_date","y_open5"],
            start="2024-01-02",stop="2024-06-28",day="None",exact_tickers=["S1"],
            maturity_predicate="2024-06-28",rows=100)])
    result = project_fixed_producer_lines(producer_lines(audit),profile=profile)
    assert "notes" not in result and "implementation_lineage" not in result
    assert result["projections"][0]["columns"] == ["signal_date","y_open5"]
    assert result["nodes"] == audit["nodes"]


@pytest.mark.parametrize("case", ["indent4","compact","unknown_root","unknown_context","wrong_schema",
                                 "missing_newline","trailing","oversize","numeric_uid_array"])
def test_fixed_projection_fails_closed_before_unexpected_payload_decode(case):
    from scripts.research.a2.evaluation.joint_frozen_history_risk_bank_r3 import project_fixed_producer_lines
    _, value = ledger_metadata_fixture()
    profile = "ledger"
    if case == "unknown_root":
        value["nav"] = [999999.123]
    elif case == "unknown_context":
        value["physical_events"][0]["context"]["covariance"] = [[999999.123]]
    elif case == "wrong_schema":
        profile = "full_audit"
        value = {"schema":"UNKNOWN_WRITER","nodes":[]}
    elif case == "numeric_uid_array":
        value["records"][0]["asset_uids"]["S1"] = [999999.123]
    lines = producer_lines(value, 4 if case=="indent4" else 2)
    if case == "compact":
        import json
        lines = [json.dumps(value)+"\n"]
    elif case == "missing_newline":
        lines[-1] = lines[-1].rstrip("\n")
    elif case == "trailing":
        lines.append("{}\n")
    elif case == "oversize":
        lines[0] = "{"+(" "*65536)+"\n"
    with pytest.raises(BankMetadataError):
        project_fixed_producer_lines(lines,profile=profile)


def test_fixed_projection_is_pure_and_accepts_crlf_from_fixed_writer(monkeypatch):
    from scripts.research.a2.evaluation.joint_frozen_history_risk_bank_r3 import project_fixed_producer_lines
    _, value = ledger_metadata_fixture()
    lines = [line.replace("\n","\r\n") for line in producer_lines(value)]
    def forbidden(*a, **k):
        raise AssertionError("File I/O forbidden")
    monkeypatch.setattr(builtins,"open",forbidden)
    monkeypatch.setattr(Path,"open",forbidden)
    assert project_fixed_producer_lines(lines,profile="ledger") == value


def test_fixed_scanner_preserves_exact_checkpoint_recovery_metadata():
    from scripts.research.a2.evaluation.joint_frozen_history_risk_bank_r3 import project_fixed_producer_lines
    _, value = ledger_metadata_fixture()
    value["records"][1].update(status="ABANDONED_CHECKPOINT_FAILURE",
        status_before_recovery="FIT_FAILURE", engineering_failure_preserved=True,
        recovery_audit_sha256=SHA)
    value["engineering_recovery_audits"] = [ref("fixed_recovery_audit.json")]
    result = project_fixed_producer_lines(producer_lines(value),profile="ledger")
    assert result["records"][1] == value["records"][1]
    assert result["engineering_recovery_audits"] == value["engineering_recovery_audits"]


COMPLETE_ID = "V24_B_COMPLETE_COMMON_H5_FF48_RISK_DIAGNOSTIC_R1"


def complete_fixture(*, corrected=False):
    from datetime import datetime, timedelta, timezone
    f = fixture()
    parent = f["stages"][1]["audit"]["nodes"][0]
    window = [(datetime(2023, 1, 1, tzinfo=timezone.utc)+timedelta(days=i)).isoformat()
              for i in range(252)]
    requested = dict(assets=["S1","S2","S3"], asset_uids={"S1":"U1","S2":"U2"},
        asset_epochs={"S1":"E1","S2":"E2"},
        segment_starts={"S1":window[0],"S2":window[0]}, blocked_assets={"S3":["UNKNOWN_UID"]})
    parent.update(parent_requested=requested, parent_origin_window=window)
    prior = dict(assets=["S1","S2"], parent_origin_window=window,
        asset_uids={"S1":"U1","S2":"U2"}, asset_epochs={"S1":"E1","S2":"E2"},
        segment_starts={"S1":window[0],"S2":window[0]},
        supported_h5_by_asset={"S1":252,"S2":100})
    domain = {k: ({x:v[x] for x in ["S1"]} if isinstance(v,dict)
                  else ["S1"] if k=="assets" else copy.deepcopy(v)) for k,v in prior.items()}
    extra = event("complete_cov", "covariance", "complete")
    extra["context"]["assets"] = ["S1"]
    extra["context"]["identity_epoch"]["uids"] = {"S1":"U1"}
    extra["key"] = content_hash({k:extra[k] for k in
        ("kind","name","context","inputs_sha256","parameters")})
    n = node("complete:RB@"+ASOF, [extra["key"]], 1)
    n.update(assets=["S1"], asset_uids={"S1":"U1"}, asset_epochs={"S1":"E1"},
        parent_requested=copy.deepcopy(requested), parent_origin_window=window,
        domain_comparison=dict(parent_origin_window_sha256=content_hash(window),
            parent_requested_sha256=content_hash(requested),
            prior_partial_domain=prior, complete_domain=domain,
            prior_partial_domain_sha256=content_hash(prior),
            complete_domain_sha256=content_hash(domain),
            counts_sha256=content_hash(prior["supported_h5_by_asset"]),
            parent_component_support_sha256=SHA, relation="STRICT_SUBSET",
            whole_scientific_equivalence="NOT_CLAIMED_FROM_RESEARCH_ID_OR_DOMAIN_ALONE"))
    extra.update(complete_common_node=n["risk_node"],
        complete_execution_freeze_sha256=SHA, complete_group_as_of=ASOF)
    if corrected:
        rr = event("corrected_mean", "scaler", "rr_correction")
        rr.update(corrected_rr_node="corrected_rr:future", correction_freeze_sha256=SHA)
        rn = node("corrected_rr:future", [f["reservations"][0]["key"],
            f["reservations"][1]["key"],rr["key"]],1)
        rn["method"] = "RR"
        f["reservations"].append(rr)
        f["stages"].append(stage("rr_correction",[rn],4,
            "ADDITIVE_RISK_CORRECTION",("component",)))
        f["artifact_checks"][rn["artifact"]] = SHA
    f["reservations"].append(extra)
    s = stage("complete",[n],5 if corrected else 4,"COMPLETE_COMMON_COMPONENT",("component",))
    s["research_id"] = COMPLETE_ID
    s["audit"]["stage_new_fit_units"] = 1
    f["stages"].append(s)
    f["artifact_checks"][n["artifact"]] = SHA
    return f


def complete_projected(f, **changes):
    from scripts.research.a2.evaluation.joint_frozen_history_risk_bank_r3 import project_fixed_reservations
    raw = [{k:copy.deepcopy(v) for k,v in e.items() if k!="owner_stage_id"}
           for e in f["reservations"]]
    for e in raw:
        e.update(stage="risk",started_utc="2026-10-03T00:00:00+00:00")
    if changes:
        raw[-1].update(changes)
    return project_fixed_reservations(f["stages"],list(reversed(raw)),
        full_stage_id="full",component_stage_id="component",complete_stage_id="complete",
        correction_stage_id="rr_correction" if len(f["stages"])==4 else None,
        verified_full_operation_keys=[e["key"] for e in f["reservations"]
            if e["owner_stage_id"]=="full"])


def complete_audit(f):
    s = f["stages"][-1]
    return dict(copy.deepcopy(s["audit"]),research_id=COMPLETE_ID,
        domain_role="COMPLETE_COMMON_COMPONENT",risk_complete_common_science_sha256=SHA,
        source_inputs_sha256=SHA,risk_support_sha256=SHA,execution_freeze_sha256=SHA)


def test_four_stage_complete_projection_uses_real_closure_and_keeps_cumulative_separate():
    f = complete_fixture(corrected=True)
    before = {e["key"]:copy.deepcopy(e["context"]) for e in f["reservations"]}
    f["reservations"] = complete_projected(f)
    assert all(e["context"]==before[e["key"]] for e in f["reservations"])
    r = build(f)
    assert r["fixed_count_receipt"]["learned_risk_fit_units"] == 5
    assert r["fixed_count_receipt"]["physical_events_total"] == 6
    assert [s["learned_fit_units"] for s in r["fixed_count_receipt"]["stages"]] == [2,1,1,1]
    assert [s["observed_cumulative_counters"]["risk_fit_units"]
            for s in r["fixed_count_receipt"]["stages"]] == [2,3,4,5]
    state = r["manifest"]["states"][-1]
    assert state["domain_role"] == "COMPLETE_COMMON_COMPONENT"
    assert state["component_metadata"]["domain_comparison"]["relation"] == "STRICT_SUBSET"
    assert state["full_pool_policy_qualification_granted"] is False
    assert r["manifest"]["new_fits"] == 0


@pytest.mark.parametrize("case", ["freeze","group","node","closure","dual","untagged","owner"])
def test_complete_owner_requires_tag_freeze_group_and_actual_node_closure(case):
    f = complete_fixture()
    e = f["reservations"][-1]
    if case=="freeze":
        e["complete_execution_freeze_sha256"]="b"*64
    elif case=="group":
        e["complete_group_as_of"]="2024-07-02T20:00:00+00:00"
    elif case=="node":
        e["complete_common_node"]="complete:RB@UNKNOWN"
    elif case=="closure":
        f["stages"][-1]["audit"]["nodes"][0]["fit_dependency_ids"]=[]
    elif case=="dual":
        e.update(corrected_rr_node="corrected_rr:future",correction_freeze_sha256=SHA)
    elif case=="untagged":
        e.pop("complete_common_node")
    else:
        e["owner_stage_id"]="component"
    with pytest.raises(BankMetadataError):
        build(f)
    if case!="owner":
        with pytest.raises(BankMetadataError):
            complete_projected(f)


@pytest.mark.parametrize("case", ["hash","counts_hash","parent_support","count","window","starts",
                                  "uid","order","equivalence_claim","relation","same_domain_new_fit"])
def test_complete_domain_proof_rejects_unsupported_identity_or_refitting(case):
    f = complete_fixture()
    n=f["stages"][-1]["audit"]["nodes"][0]
    p=n["domain_comparison"]
    if case=="hash":
        p["complete_domain_sha256"]="b"*64
    elif case=="counts_hash":
        p["counts_sha256"]=content_hash(p["complete_domain"]["supported_h5_by_asset"])
    elif case=="parent_support":
        p["parent_component_support_sha256"]="b"*64
    elif case=="count":
        p["complete_domain"]["supported_h5_by_asset"]["S1"]=251
    elif case=="window":
        p["complete_domain"]["parent_origin_window"].pop()
    elif case=="starts":
        n["parent_requested"]["segment_starts"]["S1"]="2023-01-02T00:00:00+00:00"
    elif case=="uid":
        p["complete_domain"]["asset_uids"]["S1"]="U_OTHER"
    elif case=="order":
        p["prior_partial_domain"]["assets"]=["S2"]
    elif case=="equivalence_claim":
        p["whole_scientific_equivalence"]="EQUIVALENT_FROM_RESEARCH_ID"
    elif case=="relation":
        p["relation"]="UNKNOWN"
    else:
        p["relation"]="REUSE_REQUIRED"
        p["prior_partial_domain"]=copy.deepcopy(p["complete_domain"])
    with pytest.raises(BankMetadataError):
        build(f)


def test_complete_fixed_profile_skips_notes_before_decoding_and_preserves_count_proof(monkeypatch):
    import scripts.research.a2.evaluation.joint_frozen_history_risk_bank_r3 as bank
    audit=complete_audit(complete_fixture())
    audit["notes"]={"DO_NOT_DECODE":{"covariance":[[876543.21]],"mu":["PRIVATE_VALUE"]}}
    audit["nodes"][0]["notes"]=copy.deepcopy(audit["notes"])
    original=bank.json.loads
    def guarded(text,*a,**k):
        assert not any(v in text for v in ("DO_NOT_DECODE","876543.21","PRIVATE_VALUE"))
        return original(text,*a,**k)
    monkeypatch.setattr(bank.json,"loads",guarded)
    result=bank.project_fixed_producer_lines(producer_lines(audit),profile="complete_audit")
    assert "notes" not in result and "notes" not in result["nodes"][0]
    proof=result["nodes"][0]["domain_comparison"]
    assert proof["counts_sha256"]==content_hash(proof["prior_partial_domain"]["supported_h5_by_asset"])
    assert result["stage_new_fit_units"]==1


@pytest.mark.parametrize("case",["wrong_identity","wrong_role","unknown_domain","matrix_domain","wrong_profile"])
def test_complete_profile_fails_closed_on_unexpected_schema(case):
    from scripts.research.a2.evaluation.joint_frozen_history_risk_bank_r3 import project_fixed_producer_lines
    audit=complete_audit(complete_fixture())
    profile="complete_audit"
    if case=="wrong_identity":
        audit["research_id"]="SYNTHETIC_OTHER"
    elif case=="wrong_role":
        audit["domain_role"]="FULL_REQUESTED_POOL"
    elif case=="unknown_domain":
        audit["nodes"][0]["domain_comparison"]["predictions"]=[876543.21]
    elif case=="matrix_domain":
        audit["nodes"][0]["domain_comparison"]["complete_domain"]["asset_uids"]["S1"]=[[876543.21]]
    else:
        profile="full_audit"
    with pytest.raises(BankMetadataError):
        project_fixed_producer_lines(producer_lines(audit),profile=profile)


def test_complete_stage_admin_units_cannot_copy_shared_cumulative_total():
    f=complete_fixture()
    f["stages"][-1]["audit"]["stage_new_fit_units"]=4
    with pytest.raises(BankMetadataError,match="ADMINISTRATIVE_INCREMENT"):
        build(f)


@pytest.mark.parametrize("timezone_alias",[False,True])
def test_complete_group_cap_counts_failed_reservations_without_refund(timezone_alias):
    f=complete_fixture()
    n=f["stages"][-1]["audit"]["nodes"][0]
    for i in range(31):
        e=copy.deepcopy(f["reservations"][-1])
        e.update(name="failed_complete_"+str(i),status="FIT_FAILURE")
        if timezone_alias and i%2:
            e["complete_group_as_of"]="2024-07-02T05:00:00+09:00"
        e.pop("result_sha256",None)
        e["key"]=content_hash({k:e[k] for k in
            ("kind","name","context","inputs_sha256","parameters")})
        f["reservations"].append(e)
        n["fit_dependency_ids"].append(e["key"])
    n["learned_states"]=32
    f["stages"][-1]["audit"]["stage_new_fit_units"]=32
    with pytest.raises(BankMetadataError,match="SCOPE_CAP"):
        build(f)


def test_blocked_complete_empty_domain_does_not_claim_complete_observation_support():
    f=complete_fixture()
    s=f["stages"][-1]
    s["audit"]["nodes"].append(dict(risk_node="complete:RH@blocked",method="RH",
        as_of=ASOF,cutoff=CUTOFF,assets=[],asset_uids={},asset_epochs={},
        status="METADATA_BLOCKED",learned_states=0,fit_dependency_ids=[],
        block_reason="NO_QUALIFIED_COMMON_DOMAIN"))
    s["expected_node_count"]+=1
    result=build(f)
    assert result["manifest"]["blocked_or_unverified_diagnostics"][-1]["original_block_reason"]=="NO_QUALIFIED_COMMON_DOMAIN"


def test_ticker_mu_is_metadata_key_not_prediction_value():
    f=fixture()
    mapping={}
    for e in f["reservations"]:
        old=e["key"]
        e["context"]["assets"]=["MU","S2"]
        e["context"]["identity_epoch"]["uids"]={"MU":"U1","S2":"U2"}
        e["key"]=content_hash({k:e[k] for k in
            ("kind","name","context","inputs_sha256","parameters")})
        mapping[old]=e["key"]
    for e in f["reservations"]:
        e["dependencies"]=[mapping[k] for k in e["dependencies"]]
    for s in f["stages"]:
        for n in s["audit"]["nodes"]:
            n.update(assets=["MU","S2"],asset_uids={"MU":"U1","S2":"U2"},
                     asset_epochs={"MU":"E1","S2":"E2"})
            n["fit_dependency_ids"]=[mapping[k] for k in n["fit_dependency_ids"]]
    assert build(f)["fixed_count_receipt"]["learned_risk_fit_units"]==3


def test_complete_stage_341_cap_is_separate_from_per_group_cap():
    from datetime import datetime, timedelta
    f=complete_fixture()
    s=f["stages"][-1]
    template_n=copy.deepcopy(s["audit"]["nodes"][0])
    template_e=copy.deepcopy(f["reservations"].pop())
    nodes=[]
    for group in range(12):
        asof=(datetime.fromisoformat(ASOF)+timedelta(days=group)).isoformat()
        n=copy.deepcopy(template_n)
        n.update(risk_node="complete:RB@"+asof,as_of=asof,fit_dependency_ids=[],
                 learned_states=29 if group<6 else 28)
        for i in range(n["learned_states"]):
            e=copy.deepcopy(template_e)
            e.update(name=f"complete_group_{group}_{i}",complete_common_node=n["risk_node"],
                     complete_group_as_of=asof)
            e["key"]=content_hash({k:e[k] for k in
                ("kind","name","context","inputs_sha256","parameters")})
            f["reservations"].append(e)
            n["fit_dependency_ids"].append(e["key"])
        nodes.append(n)
    s["audit"].update(nodes=nodes,stage_new_fit_units=342)
    s["expected_node_count"]=12
    with pytest.raises(BankMetadataError,match="SCOPE_CAP"):
        build(f)


def test_complete_segment_must_cover_the_fixed_252_parent_window():
    f=complete_fixture()
    n=f["stages"][-1]["audit"]["nodes"][0]
    p=n["domain_comparison"]
    future="2024-06-01T00:00:00+00:00"
    n["parent_requested"]["segment_starts"]["S1"]=future
    p["prior_partial_domain"]["segment_starts"]["S1"]=future
    p["complete_domain"]["segment_starts"]["S1"]=future
    with pytest.raises(BankMetadataError,match="SEGMENT_DOES_NOT_COVER"):
        build(f)


def test_exact_complete_writer_activation_and_node_pins_are_metadata_only():
    from scripts.research.a2.evaluation.joint_frozen_history_risk_bank_r3 import project_fixed_producer_lines
    f=complete_fixture()
    n=f["stages"][-1]["audit"]["nodes"][0]
    n.update(domain_role="COMPLETE_COMMON_COMPONENT",
        risk_complete_common_science_sha256=SHA,complete_execution_freeze_sha256=SHA)
    audit=complete_audit(f)
    audit.update(activation_receipt_sha256=SHA,max_additional_learned_units=341,
                 max_group_learned_units=31,account_equivalence=False)
    selected=project_fixed_producer_lines(producer_lines(audit),profile="complete_audit")
    assert selected["nodes"][0]["complete_execution_freeze_sha256"]==SHA
    assert selected["activation_receipt_sha256"]==SHA
    assert build(f)["manifest"]["states"][-1]["reusable"] is True
    _,ledger=ledger_metadata_fixture()
    ledger["complete_common_activation"]=dict(path="RISK_COMPLETE_COMMON_ACTIVATION_RECEIPT.json",
        sha256=SHA,execution_freeze_sha256=SHA)
    assert project_fixed_producer_lines(producer_lines(ledger),profile="ledger")==ledger


@pytest.mark.parametrize("field",["domain_role","risk_complete_common_science_sha256",
                                 "complete_execution_freeze_sha256"])
def test_complete_actual_node_pins_cannot_change_after_science_binding(field):
    f=complete_fixture()
    f["stages"][-1]["audit"]["nodes"][0][field]="WRONG" if field=="domain_role" else "b"*64
    with pytest.raises(BankMetadataError,match="CONFLICT"):
        build(f)


def test_node_run_start_is_administrative_clock_not_historical_input_cutoff():
    f=fixture()
    f["stages"][0]["audit"]["nodes"][0]["started_utc"]="2026-10-03T06:00:00+00:00"
    result=build(f)
    assert result["manifest"]["states"][0]["run_started_utc"]=="2026-10-03T06:00:00+00:00"
    assert result["manifest"]["states"][0]["cutoff"]==CUTOFF


def test_actual_uid_segment_date_schema_preserves_parent_hash_and_strict_fit_clocks():
    f=complete_fixture()
    n=f["stages"][-1]["audit"]["nodes"][0]
    p=n["domain_comparison"]
    for holder in (n["parent_requested"],p["prior_partial_domain"],p["complete_domain"]):
        holder["segment_starts"]={k:v[:10] for k,v in holder["segment_starts"].items()}
    p["parent_requested_sha256"]=content_hash(n["parent_requested"])
    p["prior_partial_domain_sha256"]=content_hash(p["prior_partial_domain"])
    p["complete_domain_sha256"]=content_hash(p["complete_domain"])
    assert build(f)["manifest"]["states"][-1]["reusable"] is True
    n["cutoff"]="2024-06-28"
    with pytest.raises(BankMetadataError,match="EXPLICIT_UTC"):
        build(f)


@pytest.mark.parametrize("value",["2026-01-01","2024-06-01","2023-01-01T00:00:00","2023-1-01"])
def test_uid_segment_date_schema_does_not_allow_future_or_naive_intraday_boundaries(value):
    f=complete_fixture()
    n=f["stages"][-1]["audit"]["nodes"][0]
    p=n["domain_comparison"]
    for holder in (n["parent_requested"],p["prior_partial_domain"],p["complete_domain"]):
        holder["segment_starts"]["S1"]=value
    with pytest.raises(BankMetadataError):
        build(f)


def test_same_day_aware_segment_after_first_origin_keeps_original_timestamp_block():
    f=complete_fixture()
    n=f["stages"][-1]["audit"]["nodes"][0]
    p=n["domain_comparison"]
    for holder in (n["parent_requested"],p["prior_partial_domain"],p["complete_domain"]):
        holder["segment_starts"]["S1"]="2023-01-01T23:00:00+00:00"
    with pytest.raises(BankMetadataError,match="SEGMENT_DOES_NOT_COVER"):
        build(f)
