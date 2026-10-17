"""R11A1 publication prebind: metadata and synthetic handoff only.

No original 259-test rerun, numerical bank, labels, predictions, live ledger,
provider, estimator/scaler fit, reservation, backend or account execution.
"""
import copy
import json
import socket
import subprocess
import urllib.request
from pathlib import Path

import pytest
import requests
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
from scripts.research.a2.training import stateful_risk_handoff as h

c = h.c


@pytest.fixture(autouse=True)
def forbidden_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("NUMERIC_RESERVATION_BACKEND_PROVIDER_FORBIDDEN")
    owners = ((c.owner, "_fit_job"), (c.models, "fit"),
        (c.models, "fit_worker"), (c.models, "fit_weighted_scaler"),
        (StandardScaler, "fit"), (StandardScaler, "fit_transform"),
        (Ridge, "fit"), (HistGradientBoostingRegressor, "fit"),
        (c, "reserve_node"), (c, "dispatch_reserved"), (c, "execute_node"),
        (socket.socket, "connect"), (socket, "create_connection"),
        (requests.sessions.Session, "request"), (urllib.request, "urlopen"),
        (subprocess, "Popen"))
    for owner, name in owners:
        monkeypatch.setattr(owner, name, forbidden)


@pytest.fixture(scope="module")
def plan():
    return h.metadata_plan()


def synthetic_packet(plan, family="LW", *, year=2024, mode="train", pair=False):
    spec = plan.family(family)
    day = f"{year - 1}-12-12" if mode == "train" else f"{year}-06-12"
    assets = [f"SYNTHETIC_TICKER_{i:02d}" for i in range(21)]
    sids = {a: f"SYNTHETIC_SID_{i:02d}" for i, a in enumerate(assets)}
    uids = {a: f"SYNTHETIC_UID_{i:02d}" for i, a in enumerate(assets)}
    epochs = {a: "SYNTHETIC_EPOCH_1" for a in assets}
    meta = dict(research_id=c.B_RESEARCH_ID, family=family, method=spec["method"],
        recipe_sha256=spec["recipe_SHA"], producer_sha256=spec["producer_SHA"],
        source_path="D:/us-tech-quant-cache/SYNTHETIC_ONLY/source.joblib",
        source_sha256="b" * 64, source_identity="SYNTHETIC_SOURCE",
        source_version="SYNTHETIC_V1", bank_schema="B_R5_EVENT_RISK_BANK_V1",
        state_schema="SHARED_RISK_STATE_R2", schema_version=1,
        state_id="SYNTHETIC_STATE_" + family, state_sha256="a" * 64,
        state_available_at=day + "T21:30:00+00:00", as_of=day + "T21:00:00+00:00",
        cutoff=day + "T20:00:00+00:00", event_ids=["SYNTHETIC_EVENT"],
        fit_dependency_ids=["SYNTHETIC_PAID_DEPENDENCY"],
        ledger_ref="D:/us-tech-quant-cache/SYNTHETIC_ONLY/ledger.jsonl",
        ledger_sha256="c" * 64, ordered_U=assets, security_ids=sids, uids=uids,
        epochs=epochs, security_coordinate=c.COORDINATE,
        source_support_identity={"synthetic": True}, parameters={"synthetic": True},
        history_recipe={"origin_sessions": 252}, horizon=5,
        coordinate=spec["coordinate"], psd_qualified=True, coverage_qualified=True,
        source_still_valid=True, maturity_still_valid=True, qualification_status="QUALIFIED")
    ident = lambda a: dict(sid=sids[a], uid=uids[a], epoch=epochs[a])
    request = dict(request_id="SYNTHETIC_REQUEST_" + family, decision_date=day, decision_information_time=day + "T22:00:00+00:00",
        raw20=[ident(a) for a in assets[:20]], actor=ident(assets[0]),
        entrant=ident(assets[20]) if pair else None, action_type=1 if pair else 0)
    global_row = dict(event_id="SYNTHETIC_EVENT", family=family,
        publication_status="VERIFIED_MECHANISM_STATE", psd_qualified=True,
        coverage_qualified=True, typed_state_content_sha256=meta["state_sha256"],
        source_receipt_sha256=meta["source_sha256"], source_receipt={k: meta[k] for k in ("source_sha256", "source_identity", "source_version")},
        artifact_ref=dict(path="D:/us-tech-quant-cache/SYNTHETIC_ONLY/state.joblib", sha256="d" * 64),
        physical_artifact_pin_verified=True, state_metadata=copy.deepcopy(meta), risk_state_id=meta["state_id"])
    availability = dict(authority_kind="INDEPENDENT_STATE_AVAILABILITY",
        state_id=meta["state_id"], state_available_at=meta["state_available_at"],
        authority_ref=dict(path="D:/us-tech-quant-cache/SYNTHETIC_ONLY/time.json", sha256="e" * 64),
        authority_verified=True)
    identity = dict(decision_date=day, state_id=meta["state_id"],
        authority_ref=dict(path="D:/us-tech-quant-cache/SYNTHETIC_ONLY/identity.json", sha256="f" * 64),
        authority_verified=True, raw20=copy.deepcopy(request["raw20"]),
        actor=copy.deepcopy(request["actor"]), entrant=copy.deepcopy(request["entrant"]))
    global_row.update(state_availability_authority=copy.deepcopy(availability), available_clock_role="INDEPENDENT_STATE_AVAILABILITY", risk_state_id=meta["state_id"], method=meta["method"], as_of=meta["as_of"], cutoff=meta["cutoff"], assets=copy.deepcopy(meta["ordered_U"]), asset_uids=copy.deepcopy(meta["uids"]), asset_epochs=copy.deepcopy(meta["epochs"]), fit_dependency_ids=copy.deepcopy(meta["fit_dependency_ids"]))
    return meta, global_row, request, availability, identity


def assess(plan, packet, *, family="LW", head="ENTRY", year=2024, mode="train", compatible=True):
    meta, row, request, availability, identity = packet
    snapshot = h._snapshot(dict(view=dict(global_rows={meta.get("state_id"): row}, states=[meta]), engineering_compatible=True, own_identity_witnesses={request["request_id"]: identity}, verified_refs=[w["authority_ref"] for w in (availability, identity) if w.get("authority_ref")], own_alias_witnesses=[]))
    return h.qualify_metadata(plan, meta, row, request, family=family, head=head,
        year=year, mode=mode, availability_witness=availability,
        identity_witness=identity, engineering_compatible=compatible, snapshot=snapshot)


@pytest.fixture(scope="module")
def publication_fixture(plan):
    keys = h.expected_attempts()
    families = plan.design["families_order"]
    aliases = dict(schema=h.PUBLICATIONS["alias"][1], research_id=c.B_RESEARCH_ID,
        synthetic=True, states=[])
    alias_ref = dict(path="D:/us-tech-quant-cache/SYNTHETIC_ONLY/alias.json", sha256="f" * 64)
    refs = {slot: dict(path=f"D:/us-tech-quant-cache/SYNTHETIC_ONLY/{slot}.json", sha256=str(i) * 64)
            for i, slot in enumerate(c.SOURCE_SLOTS, 1)}
    attempts, states, blocks = [], [], []
    for j, (event_id, family) in enumerate(keys):
        status = ("VERIFIED_MECHANISM_STATE", "BLOCKED_PUBLICATION_VERIFICATION",
                  "RETAINED_BLOCKED_OR_FAILED")[j % 3]
        row = dict(event_id=event_id, family=family, publication_status=status,
                   attempt_status=("PASS", "BLOCKED", "FAILED")[j % 3])
        if family in families and status == "VERIFIED_MECHANISM_STATE":
            meta, template, *_ = synthetic_packet(plan, family)
            meta["state_id"] = f"SYNTHETIC_STATE_{j}"
            meta["event_ids"] = [event_id]
            row.update(template, event_id=event_id, family=family,
                       state_metadata=copy.deepcopy(meta), risk_state_id=meta["state_id"])
            states.append(meta)
        elif family in families:
            blocks.append(dict(event_id=event_id, family=family,
                               status="BLOCKED_STATE", original_attempt_status=row["attempt_status"]))
        attempts.append(row)
    global_manifest = dict(schema=h.PUBLICATIONS["global"][1], research_id=c.B_RESEARCH_ID,
        SID_alias_provenance=copy.deepcopy(alias_ref), publication_refs=refs,
        all_original_attempts_preserved=True, A_and_C_must_independently_qualify=True,
        states_and_retained_attempts=attempts)
    handoff = dict(schema="R11A1_B_R5_HANDOFF_MANIFEST_R1", research_id=c.B_RESEARCH_ID,
        version=1, states=states, **{slot: dict(ref, schema="SYNTHETIC_SLOT_SCHEMA", qualified=True)
                                   for slot, ref in refs.items()})
    wrapper = dict(schema=h.PUBLICATIONS["projection"][1], research_id=c.B_RESEARCH_ID,
        SID_alias_provenance=copy.deepcopy(alias_ref), handoff=handoff, typed_blocks=blocks,
        requested_state_count=sum(family in families for _, family in keys),
        requested_families=copy.deepcopy(families), A_consumer_qualification_granted=False,
        wholewindow_all_family_qualification_granted=False,
        consumer_schema_sha256=c.content_hash(c.handoff_schema()),
        consumer_schema_producer_ref=dict(path=str(Path(c.__file__)), sha256=h.CONSUMER_SHA))
    return global_manifest, wrapper, aliases, alias_ref


def view(plan, fixture):
    global_manifest, wrapper, alias, alias_ref = fixture
    return h.publication_view(plan, global_manifest, wrapper, alias, alias_ref=alias_ref)


def test_full_403_mixed_publication_preserves_A385_and_failures(plan, publication_fixture):
    result = view(plan, publication_fixture)
    assert result["global_attempt_count"] == 403
    assert result["A_requested_count"] == 385
    assert set(result["global_status_counts"]) == {"VERIFIED_MECHANISM_STATE",
        "BLOCKED_PUBLICATION_VERIFICATION", "RETAINED_BLOCKED_OR_FAILED"}
    assert all(result["global_status_counts"].values())
    assert sum(result["global_status_counts"].values()) == 403
    assert result["A_projected_count"] + result["A_blocked_count"] == 385
    assert result["A_projected_count"] > 0 and result["A_blocked_count"] > 0
    before = copy.deepcopy(publication_fixture)
    result["states"][0]["source_identity"] = "CHANGED_LOCAL_VIEW"
    assert publication_fixture == before


@pytest.mark.parametrize("case", ["global_missing_failure", "global_duplicate", "projection_drop_block",
    "projection_duplicate", "publication_as_A_PASS", "publication_as_wholewindow_PASS",
    "wrong_family_roster", "requested_denominator", "source_slot_false", "source_slot_drift",
    "consumer_sha_drift", "consumer_schema_drift", "wrong_alias_ref", "typed_physical_swap"])
def test_publication_rejects_denominator_custody_or_authority_promotion(plan, publication_fixture, case):
    global_manifest, wrapper, alias, alias_ref = copy.deepcopy(publication_fixture)
    if case == "global_missing_failure": global_manifest["states_and_retained_attempts"].pop()
    elif case == "global_duplicate": global_manifest["states_and_retained_attempts"].append(global_manifest["states_and_retained_attempts"][0])
    elif case == "projection_drop_block": wrapper["typed_blocks"].pop()
    elif case == "projection_duplicate": wrapper["handoff"]["states"].append(wrapper["handoff"]["states"][0])
    elif case == "publication_as_A_PASS": wrapper["A_consumer_qualification_granted"] = True
    elif case == "publication_as_wholewindow_PASS": wrapper["wholewindow_all_family_qualification_granted"] = True
    elif case == "wrong_family_roster": wrapper["requested_families"] = list(reversed(wrapper["requested_families"]))
    elif case == "requested_denominator": wrapper["requested_state_count"] -= 1
    elif case == "source_slot_false": wrapper["handoff"]["bank"]["qualified"] = False
    elif case == "source_slot_drift": wrapper["handoff"]["bank"]["sha256"] = "e" * 64
    elif case == "consumer_sha_drift": wrapper["consumer_schema_producer_ref"]["sha256"] = "e" * 64
    elif case == "consumer_schema_drift": wrapper["consumer_schema_sha256"] = "e" * 64
    elif case == "wrong_alias_ref": alias_ref["sha256"] = "e" * 64
    elif case == "typed_physical_swap":
        projected = wrapper["handoff"]["states"][0]
        row = next(r for r in global_manifest["states_and_retained_attempts"]
                   if r["event_id"] == projected["event_ids"][0] and r["family"] == projected["family"])
        row["typed_state_content_sha256"] = row["artifact_ref"]["sha256"]
    with pytest.raises(c.ConsumerBlocked):
        view(plan, (global_manifest, wrapper, alias, alias_ref))


def test_unpublished_empty_projection_preserves_whole_denominator(plan, publication_fixture):
    global_manifest, wrapper, alias, alias_ref = copy.deepcopy(publication_fixture)
    requested = {tuple((r["event_id"], r["family"])) for r in wrapper["typed_blocks"]}
    requested.update((m["event_ids"][0], m["family"]) for m in wrapper["handoff"]["states"])
    wrapper["handoff"] = None
    wrapper["typed_blocks"] = [dict(event_id=e, family=f, status="BLOCKED_SOURCE") for e, f in requested]
    result = view(plan, (global_manifest, wrapper, alias, alias_ref))
    assert result["A_projected_count"] == 0 and result["A_blocked_count"] == 385


@pytest.mark.parametrize("head", ["ENTRY", "UNIFIED_INCUMBENT"])
@pytest.mark.parametrize("year", [2024, 2025])
@pytest.mark.parametrize("mode", ["train", "eval"])
def test_independent_metadata_qualified_only_prenumerically(plan, head, year, mode):
    result = assess(plan, synthetic_packet(plan, year=year, mode=mode, pair=head=="UNIFIED_INCUMBENT"),
                    head=head, year=year, mode=mode)
    assert result["status"] == "ELIGIBLE" and result["failures"] == []
    assert c._sha(result["fingerprint"])
    assert result["evidence_level"] == "PRENUMERIC_METADATA_ONLY"
    assert result["numeric_execution_authorized"] is False


@pytest.mark.parametrize("case,expected", [
    ("raw20_missing_one", "BLOCKED_COVERAGE"), ("epoch_wrong", "BLOCKED_IDENTITY"),
    ("ticker_same_new_security", "BLOCKED_COVERAGE"), ("late_available", "BLOCKED_TIME"),
    ("asof_legal_available_illegal", "BLOCKED_TIME"), ("availability_absent", "BLOCKED_TIME"),
    ("PSD_false", "BLOCKED_PSD"), ("ledger_absent", "BLOCKED_LEDGER"),
    ("same_family_wrong_recipe", "BLOCKED_RECIPE"), ("expired_alias", "BLOCKED_IDENTITY"),
    ("typed_physical_swap", "BLOCKED_STATE"), ("typed_source_swap", "BLOCKED_STATE"),
    ("engineering_pin_unclosed", "BLOCKED_ENGINEERING_PIN")])
def test_prenumerical_scope_blocks_without_repair_or_fallback(plan, case, expected):
    packet = synthetic_packet(plan)
    meta, row, request, availability, identity = packet
    if case == "raw20_missing_one": request["raw20"].pop()
    elif case == "epoch_wrong": request["actor"]["epoch"] = "SYNTHETIC_EPOCH_2"
    elif case == "ticker_same_new_security":
        ticker = meta["ordered_U"][0]
        meta["security_ids"][ticker] = "SYNTHETIC_OTHER_SECURITY_SID"
    elif case == "late_available":
        meta["state_available_at"] = request["decision_date"] + "T22:30:00+00:00"
        availability["state_available_at"] = meta["state_available_at"]
    elif case == "asof_legal_available_illegal":
        meta["state_available_at"] = "2024-01-02T00:00:00+00:00"
        availability["state_available_at"] = meta["state_available_at"]
    elif case == "availability_absent": availability.clear()
    elif case == "PSD_false": meta["psd_qualified"] = False
    elif case == "ledger_absent": meta["ledger_ref"] = ""
    elif case == "same_family_wrong_recipe": meta["recipe_sha256"] = "f" * 64
    elif case == "expired_alias":
        request["alias_evidence"] = dict(state_id=meta["state_id"], event_ids=meta["event_ids"],
            decision_date="2023-12-11", qualified_for_exact_date=False)
    elif case == "typed_physical_swap": row["typed_state_content_sha256"] = row["artifact_ref"]["sha256"]
    elif case == "typed_source_swap": meta["state_sha256"] = meta["source_sha256"]
    before = copy.deepcopy(packet)
    result = assess(plan, packet, compatible=case != "engineering_pin_unclosed")
    assert result["status"] == expected
    assert result["failures"] and result["fingerprint"] is None
    assert result["numeric_execution_authorized"] is False
    assert packet == before
    assert len(request["raw20"]) == (19 if case == "raw20_missing_one" else 20)


@pytest.mark.parametrize("field", c.handoff_schema()["properties"]["states"]["items"]["required"])
@pytest.mark.parametrize("case", ["missing", "null"])
def test_required_state_metadata_missing_or_null_fail_closed(plan, field, case):
    packet = synthetic_packet(plan)
    if case == "missing": packet[0].pop(field)
    else: packet[0][field] = None
    result = assess(plan, packet)
    assert result["status"] == "BLOCKED_STATE" and result["fingerprint"] is None


def test_unbound_state_and_equal_asof_clock_do_not_manufacture_authority(plan):
    packet = synthetic_packet(plan)
    packet[0]["state_available_at"] = packet[0]["as_of"]
    packet[3].clear()
    assert assess(plan, packet)["status"] == "BLOCKED_TIME"
    packet[3].update(authority_kind="INDEPENDENT_STATE_AVAILABILITY", state_id=packet[0]["state_id"],
        state_available_at=packet[0]["state_available_at"], authority_verified=True,
        authority_ref=dict(path="D:/us-tech-quant-cache/SYNTHETIC_ONLY/time.json", sha256="e" * 64))
    packet[1]["state_availability_authority"] = copy.deepcopy(packet[3])
    assert assess(plan, packet)["status"] == "ELIGIBLE"
    result = h.qualify_metadata(plan, None, {}, {}, family="LW", head="ENTRY", year=2024, mode="train")
    assert result["status"] == "BLOCKED_SOURCE" and result["fingerprint"] is None


@pytest.mark.parametrize("field", h.FINGERPRINT_KEYS)
def test_every_fingerprint_dependency_changes_identity(plan, field):
    meta = synthetic_packet(plan)[0]
    before = h.binding_fingerprint(meta)
    changed = copy.deepcopy(meta)
    value = changed[field]
    if field.endswith("sha256"): changed[field] = "f" * 64
    elif isinstance(value, dict): changed[field] = dict(value, synthetic_change="DIFFERENT")
    elif isinstance(value, list): changed[field] = value + ["SYNTHETIC_DIFFERENT"]
    elif type(value) is int: changed[field] = value + 1
    else: changed[field] = value + "_CHANGED"
    assert h.binding_fingerprint(changed) != before
    assert h.binding_fingerprint(copy.deepcopy(meta)) == before
    assert h.fingerprint_input(meta) == {k: meta[k] for k in h.FINGERPRINT_KEYS}


@pytest.mark.parametrize("field", h.FINGERPRINT_KEYS)
def test_no_fake_fingerprint_for_unbound_dependency(plan, field):
    meta = synthetic_packet(plan)[0]
    meta[field] = None
    with pytest.raises(c.ConsumerBlocked, match="FINGERPRINT_UNBOUND"):
        h.binding_fingerprint(meta)


def test_28_scopes_keep_exact_original_nodes_masks_and_match_contract(plan):
    requirements = h.scope_requirements(plan)
    assert [r["scope"] for r in requirements] == plan.dag["scopes"]
    assert len(requirements) == 28
    assert {r["family"] for r in requirements} == set(plan.design["families_order"])
    assert {r["head"] for r in requirements} == {"ENTRY", "UNIFIED_INCUMBENT"}
    assert {r["year"] for r in requirements} == {2024, 2025}
    assert sum(len(r["node_ids"]) for r in requirements) == 140
    for requirement in requirements:
        nodes = plan.scope_nodes(requirement["scope"])
        assert requirement["node_ids"] == [n["node_id"] for n in nodes]
        assert requirement["node_spec_sha256"] == [n["node_spec_SHA"] for n in nodes]
        assert len(requirement["learners"]) == 4
        assert {n["learner"] for n in requirement["learners"]} == {"ridge", "hgb"}
        assert all(n["capacity"] == "MID" and n["seed"] == 20260928 for n in requirement["learners"])
        assert requirement["risk_fields"] == list(c.ENTRY_COLUMNS + (c.PAIR_COLUMNS if requirement["head"] == "UNIFIED_INCUMBENT" else ()))
        assert requirement["raw20"]["exact_unique_members"] == 20
        assert requirement["raw20"]["weight_per_member"] == "1/20"
        assert requirement["raw20"]["renormalization"] is False
        assert "own family/head/year mask" in requirement["matched_semantics"]
        assert "identical BASE/PLUS" in requirement["matched_semantics"]
        assert requirement["formal_state_bindings"] is None
        assert requirement["current_status"] == "BLOCKED_SOURCE"
    assert plan.dag["strict_planned_max"] == 140 and plan.dag["hard_physical_cap"] == 160
    assert plan.dag["unallocated"] == 20 and plan.dag["scientific_retry"] == 0


def test_single_family_block_does_not_poison_other_family_or_global_mask(plan):
    blocked = synthetic_packet(plan, "LW")
    blocked[0]["psd_qualified"] = False
    assert assess(plan, blocked, family="LW")["status"] == "BLOCKED_PSD"
    assert assess(plan, synthetic_packet(plan, "OAS"), family="OAS")["status"] == "ELIGIBLE"


def test_unknown_numeric_registry_pin_stays_strict_after_engineering_adoption(plan, monkeypatch):
    original = c.owner.sha
    registry = next(path for path in plan.design["base_feature_contract"]["source_code_pins"]
                    if path.replace("\\", "/").endswith("scripts/maintenance/research_registry.py"))
    expected = plan.design["base_feature_contract"]["source_code_pins"][registry]
    different = "f" * 64 if expected != "f" * 64 else "e" * 64
    monkeypatch.setattr(c.owner, "sha", lambda path: different if str(path) == registry else original(path))
    assert h.metadata_plan().dag == plan.dag
    assert len(h.scope_requirements(plan)) == 28
    with pytest.raises(c.ConsumerBlocked, match="PARENT_SOURCE_PIN_CHANGED_AT_EXECUTION"):
        c.validate_parent_source_pins(plan)
    assert original(c.__file__) == h.ADOPTED_CONSUMER_SHA
    assert original(h.CONSUMER_CUSTODY_PATH) == h.CONSUMER_SHA

@pytest.mark.parametrize("case", ["caller_true_only", "plain_dict", "forged_provenance", "mutated_seal", "absent_identity_pin", "absent_time_pin", "foreign_state"])
def test_caller_true_flags_or_changed_snapshot_cannot_grant_metadata_eligibility(plan, case):
    meta, row, request, availability, identity = synthetic_packet(plan)
    data = dict(view=dict(global_rows={meta["state_id"]: copy.deepcopy(row)}, states=[copy.deepcopy(meta)]),
        engineering_compatible=True, own_identity_witnesses={request["request_id"]: copy.deepcopy(identity)},
        verified_refs=[availability["authority_ref"], identity["authority_ref"]], own_alias_witnesses=[])
    snapshot = h._snapshot(data)
    if case == "caller_true_only": snapshot = None
    elif case == "plain_dict": snapshot = data
    elif case == "forged_provenance": snapshot = h.MetadataSnapshot(snapshot.data, snapshot.seal, object())
    elif case == "mutated_seal": snapshot.data["engineering_compatible"] = False
    elif case == "absent_identity_pin":
        data["verified_refs"] = [availability["authority_ref"]]
        snapshot = h._snapshot(data)
    elif case == "absent_time_pin":
        data["verified_refs"] = [identity["authority_ref"]]
        snapshot = h._snapshot(data)
    elif case == "foreign_state":
        data["view"]["states"] = []
        snapshot = h._snapshot(data)
    result = h.qualify_metadata(plan, meta, row, request, family="LW", head="ENTRY", year=2024,
        mode="train", availability_witness=availability, identity_witness=identity,
        engineering_compatible=True, snapshot=snapshot)
    assert result["status"].startswith("BLOCKED_") and result["fingerprint"] is None
    assert result["numeric_execution_authorized"] is False


@pytest.mark.parametrize("field", ["source_sha256", "source_identity", "source_version"])
def test_source_receipt_custody_is_independent_of_projection_metadata(plan, field):
    packet = synthetic_packet(plan)
    original_source = copy.deepcopy(packet[1]["source_receipt"])
    packet[0][field] = "a" * 64 if field == "source_sha256" else "SYNTHETIC_OTHER_SOURCE"
    result = assess(plan, packet)
    assert result["status"] == "BLOCKED_SOURCE"
    assert any(f["reason"] == "EXACT_INDEPENDENT_SOURCE_RECEIPT_CUSTODY" for f in result["failures"])
    assert packet[1]["source_receipt"] == original_source


@pytest.mark.parametrize("field", ["risk_state_id", "method", "as_of", "cutoff", "assets", "asset_uids", "asset_epochs", "fit_dependency_ids"])
def test_projection_cannot_change_original_global_row_metadata(plan, publication_fixture, field):
    fixture = copy.deepcopy(publication_fixture)
    rows = fixture[0]["states_and_retained_attempts"]
    projected = fixture[1]["handoff"]["states"][0]
    row = next(r for r in rows if r["event_id"] == projected["event_ids"][0] and r["family"] == projected["family"])
    value = row[field]
    if isinstance(value, dict): row[field] = dict(value, synthetic="DIFFERENT")
    elif isinstance(value, list): row[field] = value + ["DIFFERENT"]
    else: row[field] = value + "_DIFFERENT"
    with pytest.raises(c.ConsumerBlocked, match="EXACT_ORIGINAL_STATE_ROW_CUSTODY"):
        view(plan, fixture)


@pytest.mark.parametrize("value", [False, None, "true", 1])
def test_literal_owner_qualification_flags_do_not_use_truthiness(plan, value):
    packet = synthetic_packet(plan)
    packet[0]["psd_qualified"] = value
    result = assess(plan, packet)
    assert result["status"] == ("BLOCKED_STATE" if value is None else "BLOCKED_PSD")
    assert result["fingerprint"] is None

@pytest.mark.parametrize("dependency", ["formal_ref", "publication_binding", "availability_ref", "identity_ref", "identity_date", "alias_date"])
def test_qualification_fingerprint_binds_publication_and_own_authority_chain(plan, dependency):
    meta, row, request, availability, identity = synthetic_packet(plan)
    data = dict(view=dict(global_rows={meta["state_id"]: row}, states=[meta]),
        engineering_compatible=True, own_identity_witnesses={request["request_id"]: identity},
        verified_refs=[availability["authority_ref"], identity["authority_ref"]],
        formal_refs={"global": dict(path="D:/us-tech-quant-cache/SYNTHETIC_ONLY/global.json", sha256="1" * 64)},
        publication_bindings={"bank": dict(path=meta["source_path"], sha256=meta["source_sha256"])})
    alias = dict(decision_date=request["decision_date"], authority_ref=identity["authority_ref"])
    original = h.qualification_fingerprint(meta, h._snapshot(data), availability, identity, alias)
    assert h.qualification_fingerprint(copy.deepcopy(meta), h._snapshot(copy.deepcopy(data)),
        copy.deepcopy(availability), copy.deepcopy(identity), copy.deepcopy(alias)) == original
    changed_data, changed_time, changed_identity, changed_alias = map(copy.deepcopy, (data, availability, identity, alias))
    if dependency == "formal_ref": changed_data["formal_refs"]["global"]["sha256"] = "2" * 64
    elif dependency == "publication_binding": changed_data["publication_bindings"]["bank"]["sha256"] = "2" * 64
    elif dependency == "availability_ref": changed_time["authority_ref"]["sha256"] = "2" * 64
    elif dependency == "identity_ref": changed_identity["authority_ref"]["sha256"] = "2" * 64
    elif dependency == "identity_date": changed_identity["decision_date"] = "2023-12-11"
    elif dependency == "alias_date": changed_alias["decision_date"] = "2023-12-11"
    assert h.qualification_fingerprint(meta, h._snapshot(changed_data), changed_time,
        changed_identity, changed_alias) != original


def test_28_scope_qualification_retains_one_block_and_other_scope_eligible(plan):
    lw = synthetic_packet(plan, "LW")
    oas = synthetic_packet(plan, "OAS")
    lw[0]["psd_qualified"] = False
    states, rows, witnesses, verified = [], {}, {}, []
    requests = {}
    for family, packet in (("LW", lw), ("OAS", oas)):
        meta, row, request, availability, identity = packet
        request.update(state_id=meta["state_id"], mode="train")
        states.append(meta); rows[meta["state_id"]] = row
        witnesses[request["request_id"]] = identity
        verified.extend([availability["authority_ref"], identity["authority_ref"]])
        requests[family + "|ENTRY|2024"] = [request]
    snapshot = h._snapshot(dict(view=dict(states=states, global_rows=rows), engineering_compatible=True,
        own_identity_witnesses=witnesses, verified_refs=verified, own_alias_witnesses=[]))
    results = h.qualify_scopes(plan, snapshot, requests)
    by_scope = {result["scope"]: result for result in results}
    assert len(results) == 28
    assert by_scope["LW|ENTRY|2024"]["status"] == "BLOCKED_PSD"
    assert by_scope["OAS|ENTRY|2024"]["status"] == "ELIGIBLE"
    assert by_scope["OAS|ENTRY|2024"]["eligible_metadata_rows"] == 1
    assert by_scope["OAS|ENTRY|2024"]["matched_numeric_package_still_unbound"] is True
    assert all(result["numeric_execution_authorized"] is False for result in results)
    assert by_scope["OAS|ENTRY|2025"]["status"] == "BLOCKED_IDENTITY"

@pytest.mark.parametrize("case,expected", [
    ("exact_date", "ELIGIBLE"), ("interval_inside", "ELIGIBLE"),
    ("at_start", "ELIGIBLE"), ("available_at_decision", "ELIGIBLE"),
    ("at_end_exclusive", "BLOCKED_IDENTITY"), ("expired_interval", "BLOCKED_IDENTITY"),
    ("future_start", "BLOCKED_IDENTITY"), ("missing_start_no_fallback", "BLOCKED_IDENTITY"),
    ("missing_end_no_fallback", "BLOCKED_IDENTITY"), ("missing_available", "BLOCKED_IDENTITY"),
    ("late_available", "BLOCKED_IDENTITY"), ("missing_date_scope", "BLOCKED_IDENTITY"),
    ("wrong_exact_date", "BLOCKED_IDENTITY"), ("range_overrides_exact_date", "BLOCKED_IDENTITY"),
    ("malformed_range", "BLOCKED_IDENTITY"), ("zero_interval", "BLOCKED_IDENTITY")])
def test_alias_boundary_is_half_open_source_scope_without_membership_extension(plan, case, expected):
    meta, row, request, availability, identity = synthetic_packet(plan)
    alias = dict(state_id=meta["state_id"], event_ids=copy.deepcopy(meta["event_ids"]),
        decision_date=request["decision_date"], qualified_for_exact_date=True,
        available_at="2023-12-11T21:00:00+00:00", valid_date=request["decision_date"],
        authority_ref=dict(path="D:/us-tech-quant-cache/SYNTHETIC_ONLY/alias-authority.json", sha256="8" * 64))
    if case == "interval_inside": alias.update(valid_from="2023-12-11", valid_until_exclusive="2023-12-13")
    elif case == "at_start": alias.update(valid_from="2023-12-12", valid_until_exclusive="2023-12-13")
    elif case == "available_at_decision": alias["available_at"] = request["decision_information_time"]
    elif case == "at_end_exclusive": alias.update(valid_from="2023-12-11", valid_until_exclusive="2023-12-12")
    elif case == "expired_interval": alias.update(valid_from="2023-12-01", valid_until_exclusive="2023-12-11")
    elif case == "future_start": alias.update(valid_from="2023-12-13", valid_until_exclusive="2023-12-14")
    elif case == "missing_start_no_fallback": alias.update(valid_until_exclusive="2023-12-13")
    elif case == "missing_end_no_fallback": alias.update(valid_from="2023-12-11")
    elif case == "missing_available": alias.pop("available_at")
    elif case == "late_available": alias["available_at"] = "2023-12-12T22:01:00+00:00"
    elif case == "missing_date_scope": alias.pop("valid_date")
    elif case == "wrong_exact_date": alias["valid_date"] = "2023-12-11"
    elif case == "range_overrides_exact_date": alias.update(valid_from="2023-12-01", valid_until_exclusive="2023-12-11")
    elif case == "malformed_range": alias.update(valid_from="0", valid_until_exclusive="9999")
    elif case == "zero_interval": alias.update(valid_from="2023-12-12", valid_until_exclusive="2023-12-12")
    request["alias_evidence"] = alias
    snapshot = h._snapshot(dict(view=dict(global_rows={meta["state_id"]: row}, states=[meta]),
        engineering_compatible=True, own_identity_witnesses={request["request_id"]: identity},
        verified_refs=[availability["authority_ref"], identity["authority_ref"], alias["authority_ref"]],
        own_alias_witnesses=[alias]))
    before = copy.deepcopy(request)
    result = h.qualify_metadata(plan, meta, row, request, family="LW", head="ENTRY", year=2024,
        mode="train", availability_witness=availability, identity_witness=identity,
        engineering_compatible=True, snapshot=snapshot)
    assert result["status"] == expected
    assert request == before and result["numeric_execution_authorized"] is False
    if expected == "BLOCKED_IDENTITY":
        assert result["fingerprint"] is None
        assert any(f["reason"] == "EXPLICIT_ALIAS_DATE_SCOPE_AND_AVAILABILITY" for f in result["failures"])

def test_engineering_lineage_failure_preserves_independent_publication_preparation(plan, publication_fixture, monkeypatch):
    before = view(plan, publication_fixture)
    def changed_pin():
        raise c.ConsumerBlocked("SYNTHETIC_REGISTRY_DESCENDANT_PIN_CHANGED")
    monkeypatch.setattr(h, "registry_descendant_compatibility", changed_pin)
    engineering = h._engineering_prebind_status()
    assert engineering["semantic_compatible"] is False
    assert engineering["status"] == "BLOCKED_ENGINEERING_PIN"
    assert engineering["numeric_pin_accepted"] is False
    assert "SYNTHETIC_REGISTRY_DESCENDANT_PIN_CHANGED" in engineering["reason"]
    after = view(plan, publication_fixture)
    assert before == after and after["global_attempt_count"] == 403
    assert len(h.scope_requirements(plan)) == 28
    assert assess(plan, synthetic_packet(plan), compatible=engineering["semantic_compatible"])["status"] == "BLOCKED_ENGINEERING_PIN"

# Gate 1: exact registry engineering adoption and source-only publisher R2.
# Physical sources here are either reviewed code/receipts or synthetic tmp files.
# No real bank, ledger, label, prediction or numeric state is deserialized.
def test_current_engineering_descendant_loads_frozen_plan_without_science_change(plan):
    proof = h.registry_descendant_compatibility()
    assert proof["semantic_compatible"] is True
    assert proof["numeric_pin_accepted"] is True
    assert proof["current_sha256"] == h.CURRENT_REGISTRY_SHA
    assert proof["frozen_pin_sha256"] == h.OLD_REGISTRY_SHA
    assert proof["old_FrozenPlan_load_will_reject"] is False
    loaded = c.FrozenPlan.load()
    assert loaded.design == plan.design and loaded.dag == plan.dag
    assert c.validate_parent_source_pins(loaded) is True
    assert loaded.design["base_feature_contract"]["source_code_pins"][str(h.REGISTRY_PATH).replace("\\", "/")] == h.OLD_REGISTRY_SHA


@pytest.mark.parametrize("case", ["unknown_registry", "wrong_expected", "non_registry",
    "missing_lineage", "semantic_false", "different_current_proof"])
def test_parent_pin_exception_is_only_the_exact_reviewed_registry(monkeypatch, case):
    path, expected = h.REGISTRY_PATH, h.OLD_REGISTRY_SHA
    original = c.owner.sha
    if case == "unknown_registry":
        monkeypatch.setattr(c.owner, "sha", lambda p: "e" * 64 if Path(p) == path else original(p))
    elif case == "wrong_expected":
        expected = "e" * 64
    elif case == "non_registry":
        path = Path(c.__file__)
    elif case == "missing_lineage":
        absent = h.REGISTRY_LINEAGE["independent_review"][0]
        def missing(p):
            if Path(p) == absent:
                raise FileNotFoundError("SYNTHETIC_LINEAGE_UNAVAILABLE")
            return original(p)
        monkeypatch.setattr(c.owner, "sha", missing)
    elif case == "semantic_false":
        monkeypatch.setattr(h, "registry_descendant_compatibility", lambda: dict(semantic_compatible=False, current_sha256=h.CURRENT_REGISTRY_SHA))
    elif case == "different_current_proof":
        monkeypatch.setattr(h, "registry_descendant_compatibility", lambda: dict(semantic_compatible=True, current_sha256="e" * 64))
    assert c._parent_source_pin_matches(path, expected) is False


@pytest.mark.parametrize("key", tuple(h.REGISTRY_LINEAGE))
def test_every_registry_lineage_physical_pin_is_required(monkeypatch, key):
    original = c.owner.sha
    target = h.REGISTRY_LINEAGE[key][0]
    monkeypatch.setattr(c.owner, "sha", lambda p: "e" * 64 if Path(p) == target else original(p))
    with pytest.raises(c.ConsumerBlocked, match="ENGINEERING_LINEAGE_PIN_MISMATCH"):
        h.registry_descendant_compatibility()


def test_changed_other_parent_source_blocks_real_loader_and_runtime_gate(plan, monkeypatch):
    original = c.owner.sha
    target = next(Path(p) for p in plan.design["base_feature_contract"]["source_code_pins"] if Path(p) != h.REGISTRY_PATH)
    monkeypatch.setattr(c.owner, "sha", lambda p: "e" * 64 if Path(p) == target else original(p))
    with pytest.raises(c.ConsumerBlocked, match="PARENT_SOURCE_PIN_CHANGED:"):
        c.FrozenPlan.load()
    with pytest.raises(c.ConsumerBlocked, match="PARENT_SOURCE_PIN_CHANGED_AT_EXECUTION:"):
        c.validate_parent_source_pins(plan)


def test_original_published_consumer_and_adopted_runtime_have_separate_custody():
    result = h._consumer_source_provenance()
    assert result["published"] == dict(path=str(Path(c.__file__)), sha256=h.CONSUMER_SHA)
    assert result["runtime"] == dict(path=str(Path(c.__file__)), sha256=h.ADOPTED_CONSUMER_SHA)
    assert result["published_source_custody"] == dict(path=str(h.CONSUMER_CUSTODY_PATH), sha256=h.CONSUMER_SHA)
    assert result["engineering_descendant"] is True
    assert result["frozen_source_ref_rewritten"] is False
    assert result["published"]["sha256"] != result["runtime"]["sha256"]


@pytest.mark.parametrize("case", ["runtime_drift", "custody_drift", "custody_missing"])
def test_consumer_custody_or_current_source_drift_is_rejected(monkeypatch, case):
    original = c.owner.sha
    def changed(p):
        target = Path(p)
        if case == "runtime_drift" and target == Path(c.__file__):
            return "e" * 64
        if case.startswith("custody") and target == h.CONSUMER_CUSTODY_PATH:
            if case == "custody_missing":
                raise FileNotFoundError("SYNTHETIC_ORIGINAL_SOURCE_MISSING")
            return "e" * 64
        return original(p)
    monkeypatch.setattr(c.owner, "sha", changed)
    with pytest.raises((c.ConsumerBlocked, FileNotFoundError)):
        h._consumer_source_provenance()


@pytest.fixture
def synthetic_r2_publisher(tmp_path, monkeypatch):
    producer = tmp_path / "synthetic_r2_publisher.py"
    review = tmp_path / "synthetic_r2_review.json"
    receipt = tmp_path / "synthetic_r2_receipt.json"
    producer.write_text("# synthetic source only; never executed\n", encoding="utf-8")
    producer_sha = c.owner.sha(producer)
    review_body = dict(revision=dict(sha256=producer_sha),
        independent_source_review=dict(status="PASS"),
        guards_preserved=dict(source_chain_qualification_granted=False))
    review.write_text(json.dumps(review_body), encoding="utf-8")
    receipt.write_text(json.dumps(dict(synthetic=True, real_fit=0)), encoding="utf-8")
    for name, value in (("PUBLISHER_R2_PATH", producer), ("PUBLISHER_R2_SHA", producer_sha),
        ("PUBLISHER_R2_REVIEW", review), ("PUBLISHER_R2_REVIEW_SHA", c.owner.sha(review)),
        ("PUBLISHER_R2_RECEIPT", receipt), ("PUBLISHER_R2_RECEIPT_SHA", c.owner.sha(receipt))):
        monkeypatch.setattr(h, name, value)
    return dict(path=str(producer), sha256=producer_sha), review_body


def test_exact_reviewed_r2_publisher_chain_is_accepted(synthetic_r2_publisher):
    reference, _ = synthetic_r2_publisher
    before = copy.deepcopy(reference)
    result = h._publication_producer_provenance(reference)
    assert result == before and result is not reference and reference == before


@pytest.mark.parametrize("case", ["unknown_path", "unknown_sha", "producer_missing", "producer_drift",
    "review_missing", "review_drift", "receipt_missing", "receipt_drift",
    "review_bad_revision", "review_failed", "review_promotes_source"])
def test_r2_publisher_requires_exact_source_review_receipt_and_no_promotion(synthetic_r2_publisher, monkeypatch, case):
    reference, body = synthetic_r2_publisher
    if case == "unknown_path":
        reference["path"] = str(h.PUBLISHER_R2_PATH.with_name("unreviewed.py"))
    elif case == "unknown_sha":
        reference["sha256"] = "e" * 64
    elif case.endswith("missing"):
        dict(producer=h.PUBLISHER_R2_PATH, review=h.PUBLISHER_R2_REVIEW, receipt=h.PUBLISHER_R2_RECEIPT)[case.split("_")[0]].unlink()
    elif case.endswith("drift"):
        dict(producer=h.PUBLISHER_R2_PATH, review=h.PUBLISHER_R2_REVIEW, receipt=h.PUBLISHER_R2_RECEIPT)[case.split("_")[0]].write_text("SYNTHETIC_CHANGED_BYTES", encoding="utf-8")
    else:
        if case == "review_bad_revision": body["revision"]["sha256"] = "e" * 64
        elif case == "review_failed": body["independent_source_review"]["status"] = "FAIL"
        elif case == "review_promotes_source": body["guards_preserved"]["source_chain_qualification_granted"] = True
        h.PUBLISHER_R2_REVIEW.write_text(json.dumps(body), encoding="utf-8")
        monkeypatch.setattr(h, "PUBLISHER_R2_REVIEW_SHA", c.owner.sha(h.PUBLISHER_R2_REVIEW))
    with pytest.raises((c.ConsumerBlocked, FileNotFoundError)):
        h._publication_producer_provenance(reference)


def _bind_synthetic_publication(plan, publication_fixture, tmp_path, monkeypatch, mutation=None):
    global_manifest, wrapper, alias, _ = copy.deepcopy(publication_fixture)
    publisher = dict(path=str(h.PUBLISHER_R2_PATH), sha256=h.PUBLISHER_R2_SHA)
    consumer = dict(published=dict(path=str(Path(c.__file__)), sha256=h.CONSUMER_SHA),
        runtime=dict(path=str(Path(c.__file__)), sha256=h.ADOPTED_CONSUMER_SHA),
        engineering_descendant=True, frozen_source_ref_rewritten=False)
    physical = {}
    def save(virtual, local_name, body):
        local = tmp_path / local_name
        local.write_text(json.dumps(body), encoding="utf-8")
        ref = dict(path=str(virtual), sha256=c.owner.sha(local))
        physical[str(virtual)] = (ref, local)
        return ref
    qualification = save(h.RUN / "support/SYNTHETIC_QUALIFICATION.json", "qualification.json", dict(synthetic_only=True))
    bindings = dict(qualification=qualification)
    for slot, relative in (("bank", "models/risk/EVENT_RISK_BANK_R5.json"), ("ledger", "work/FIT_STATUS.json")):
        bindings[slot] = save(h.RUN / relative, slot + ".json", dict(synthetic_only=True, must_not_deserialize=True))
    bindings["freeze"] = save(h.RUN / "R5_SCIENCE_AND_EXECUTION_FREEZE.json", "freeze.json", dict(qualification_ref=qualification))
    alias_ref = save(h.RUN / h.PUBLICATIONS["alias"][0], "alias.json", alias)
    global_manifest.update(SID_alias_provenance=alias_ref,
        publication_refs=dict(bindings, publication_producer=copy.deepcopy(publisher), A_consumer=copy.deepcopy(consumer["published"])))
    wrapper["SID_alias_provenance"] = copy.deepcopy(alias_ref)
    for slot, ref in bindings.items():
        wrapper["handoff"][slot] = dict(ref, schema="SYNTHETIC_SLOT_SCHEMA", qualified=True)
    if mutation == "published_runtime_sha": global_manifest["publication_refs"]["A_consumer"]["sha256"] = h.ADOPTED_CONSUMER_SHA
    elif mutation == "published_path": global_manifest["publication_refs"]["A_consumer"]["path"] = "D:/SYNTHETIC/unreviewed.py"
    elif mutation == "published_producer": global_manifest["publication_refs"]["publication_producer"]["sha256"] = "e" * 64
    elif mutation == "wrapper_consumer": wrapper["consumer_schema_producer_ref"]["sha256"] = h.ADOPTED_CONSUMER_SHA
    refs = dict(alias=alias_ref)
    for name, body in (("global", global_manifest), ("projection", wrapper)):
        refs[name] = save(h.RUN / h.PUBLICATIONS[name][0], name + ".json", body)
    def pin(reference, *, expected_path=None):
        if reference == publisher:
            assert Path(reference["path"]) == Path(expected_path)
            return h.PUBLISHER_R2_PATH
        expected_ref, local = physical[reference["path"]]
        assert reference == expected_ref or {k: reference[k] for k in ("path", "sha256")} == expected_ref
        assert expected_path is None or Path(reference["path"]) == Path(expected_path)
        assert c.owner.sha(local) == reference["sha256"]
        return local
    monkeypatch.setattr(h, "_physical_pin", pin)
    monkeypatch.setattr(h, "_publication_producer_provenance", lambda ref: copy.deepcopy(publisher))
    monkeypatch.setattr(h, "_consumer_source_provenance", lambda: copy.deepcopy(consumer))
    monkeypatch.setattr(h, "_engineering_prebind_status", lambda: dict(semantic_compatible=True, numeric_pin_accepted=True))
    return h.bind_formal_publications(refs, publisher_ref=publisher), global_manifest, wrapper


def test_formal_binder_keeps_old_published_ref_separate_from_new_runtime(plan, publication_fixture, tmp_path, monkeypatch):
    snapshot, global_manifest, wrapper = _bind_synthetic_publication(plan, publication_fixture, tmp_path, monkeypatch)
    assert h._snapshot_valid(snapshot)
    assert snapshot.data["consumer_provenance"]["published"]["sha256"] == h.CONSUMER_SHA
    assert snapshot.data["consumer_provenance"]["runtime"]["sha256"] == h.ADOPTED_CONSUMER_SHA
    assert global_manifest["publication_refs"]["A_consumer"]["sha256"] == h.CONSUMER_SHA
    assert wrapper["consumer_schema_producer_ref"]["sha256"] == h.CONSUMER_SHA
    assert snapshot.data["view"]["global_attempt_count"] == 403
    assert snapshot.data["source_activated"] is False
    assert snapshot.data["registry_activated"] is False
    assert snapshot.data["numeric_execution_authorized"] is False


@pytest.mark.parametrize("mutation", ["published_runtime_sha", "published_path", "published_producer", "wrapper_consumer"])
def test_formal_binder_rejects_rewriting_original_published_refs(plan, publication_fixture, tmp_path, monkeypatch, mutation):
    with pytest.raises(c.ConsumerBlocked, match="EXACT_REVIEWED_PUBLICATION_OWNER_CHAIN|EXACT_EXISTING_CONSUMER_SCHEMA_PIN"):
        _bind_synthetic_publication(plan, publication_fixture, tmp_path, monkeypatch, mutation)


@pytest.mark.parametrize("family", ["SHR_HP", "SHR_CC"])
@pytest.mark.parametrize("head", ["ENTRY", "UNIFIED_INCUMBENT"])
@pytest.mark.parametrize("year", [2024, 2025])
def test_registry_adoption_cannot_promote_asof_to_independent_time_authority(plan, family, head, year):
    packet = synthetic_packet(plan, family, year=year, pair=head == "UNIFIED_INCUMBENT")
    meta, row, _, witness, _ = packet
    meta["state_available_at"] = meta["as_of"]
    row["available_clock_role"] = "ORIGINAL_STATE_AS_OF_MECHANISM_ASSUMPTION_NOT_HISTORICAL_PIT"
    row["state_availability_authority"] = None
    witness.clear()
    result = assess(plan, packet, family=family, head=head, year=year, compatible=True)
    assert result["status"] == "BLOCKED_TIME"
    assert result["fingerprint"] is None
    assert result["numeric_execution_authorized"] is False
    assert any(f["reason"] == "AS_OF_IS_NOT_INDEPENDENT_STATE_AVAILABILITY" for f in result["failures"])
