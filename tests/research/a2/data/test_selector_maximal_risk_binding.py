"""C14 prebinding engineering checks; all inputs are synthetic and in memory.

No R5/run/data artifact is opened, no estimator or optimizer is called, and no
scientific state, solver journal, bootstrap or result artifact is produced.
"""
from copy import deepcopy
from dataclasses import replace
from io import StringIO
import json

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.data import selector_maximal_risk_binding as b
from scripts.research.a2.risk.event_risk_contract_r5 import structural_identity

AT = "2025-12-19T21:00:00+00:00"
DATES = tuple(str(day.date()) for day in pd.bdate_range("2023-01-02", periods=752))
EXPECTED_HYBRIDS = (
    ("C14_RX_RIDGE_DIAG", "DIAG"),
    ("C14_RX_HGB_LW", "LW"),
    ("C14_RX_XGB_QQQ_RESIDUAL", "QQQ_RESIDUAL"),
    ("C14_RX_CAT_DOWNSIDE_SEMIVARIANCE", "DOWNSIDE_SEMIVARIANCE"),
    ("C14_RX_MLP_REGIME_COVARIANCE", "REGIME_COVARIANCE"),
    ("C14_RX_QUANTILE_UNCERTAINTY_JACKKNIFE", "UNCERTAINTY_JACKKNIFE"),
)


@pytest.fixture(autouse=True)
def no_classical_optimizer(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Synthetic prebinding tests must never call an optimizer")
    monkeypatch.setattr(b.membership, "select", forbidden)


@pytest.fixture
def matrix():
    # Synthetic copies of the frozen role roster; never read DESIGN/DAG files.
    risk = b.contract.specification()
    risk["gate_families"] = {
        "G1": "LW", "G2": "TAIL_CVAR", "G3": "UNCERTAINTY_JACKKNIFE", "G4": "PCA_FACTOR"
    }
    risk["risk_efficiency_eligible_roles"] = [
        row["candidate_id"] for row in risk["classical_bindings"]
        if row["candidate_id"] not in {"C14_D02", "C14_D12"}
    ]
    nodes = [
        {"candidate_id": role, "fit_id": f"synthetic:{role}:{i:02d}",
         "stage": "scale" if i < 4 else "estimator"}
        for (role, _), count in zip(EXPECTED_HYBRIDS, (14, 14, 14, 34, 34, 34)) for i in range(count)
    ]
    solve_ids = [f"CLASSICAL|{role}|{day}" for role in risk["risk_efficiency_eligible_roles"] for day in DATES]
    solve_ids += [f"HYBRID|{role}|{day}" for role, _ in EXPECTED_HYBRIDS for day in DATES[-502:]]
    dag = {"conditional_risk_fit_nodes": nodes, "solve_request_ids": solve_ids}
    risk_specs = [{"hypothesis_id": f"synthetic-risk-{i:02d}",
                   "role": risk["risk_efficiency_eligible_roles"][i // 2],
                   "endpoint": "synthetic-native-H5-full732"} for i in range(20)]
    return b.requirement_matrix({"risk": risk, "evaluation": {"risk_specs": risk_specs}}, dag)


def requirement(matrix, role="C14_RX_HGB_LW"):
    return deepcopy(next(row for row in matrix["roles"] if row["role"] == role))


def inputs(role="C14_RX_HGB_LW", family="LW"):
    # Full U deliberately exceeds Raw40, proving that the adapter preserves it.
    assets = [f"SYN{i:03d}" for i in range(44)]
    current = {
        "assets": assets,
        "asset_uids": {a: f"synthetic-UID-{i:03d}" for i, a in enumerate(assets)},
        "asset_epochs": {a: f"synthetic-epoch-{i:03d}" for i, a in enumerate(assets)},
        "security_coordinate": "synthetic_shareholder_H5",
        "source_support_identity": {"source": "synthetic-only", "version": "fixture-1", "sha": "a" * 64},
    }
    signature = structural_identity(
        assets=tuple(assets), uids=current["asset_uids"], epochs=current["asset_epochs"],
        security_coordinate=current["security_coordinate"],
        source_support_identity=current["source_support_identity"],
    )
    binding = {"family": family, "method": family, "parameters": {"synthetic_fixed": 1},
               "history_recipe": "synthetic-past-only", "representation": "CONTINUOUS",
               "recipe_sha256": "b" * 64}
    record = {
        **deepcopy(current), "status": "PASS_FROZEN_HISTORY_MECHANISM",
        "strict_PIT_promotion_eligible": False, "family": family, "method": family,
        "risk_state_id": f"synthetic-state:{role}:{family}",
        "parameters": deepcopy(binding["parameters"]), "history_recipe": binding["history_recipe"],
        "representation": "CONTINUOUS", "recipe_sha256": binding["recipe_sha256"],
        "horizon_sessions": 5, "as_of": "2025-12-17T21:00:00+00:00",
        "cutoff": "2025-12-16T21:00:00+00:00", "available_at": "2025-12-18T21:00:00+00:00",
        "structural_identity": signature, "source_still_valid": True, "maturity_still_valid": True,
        "coverage_dates": DATES, "psd_qualified": True, "finite_check": True,
        "artifact_ref": {"path": str(b.contract.B_RUN / "synthetic-never-opened.joblib"), "sha256": "c" * 64},
    }
    if family == "TAIL_CVAR":
        record.update(scenario_qualified=True, scenario_horizon=5,
                      scenario_source_ref={"path": str(b.contract.B_RUN / "synthetic-nativeH5-never-opened.json"), "sha256": "e" * 64})
    if family in {"UNCERTAINTY_JACKKNIFE", "DISAGREEMENT_ENSEMBLE"}:
        record.update(replica_count=2, replicas_full_psd_qualified=True,
                      replica_refs=[{"path": str(b.contract.B_RUN / f"synthetic-replica-{i}-never-opened.json"), "sha256": "e" * 64}
                                    for i in range(2)])
    refs = {name: {"path": str(b.contract.B_RUN / f"synthetic-{name}-never-opened.json"), "sha256": "d" * 64}
            for name in ("bank", "freeze", "qualification", "ledger")}
    return {"record": record, "current": current, "decision_asof": AT,
            "binding": binding, "publication_refs": refs, "required_dates": DATES}


def numeric_fixture(role, family, covariance=None):
    source = inputs(role, family)
    cov = np.eye(44) if covariance is None else np.asarray(covariance, dtype=float)
    source["record"]["covariance_sha256"] = b.sha_array(cov)
    meta = b.RiskMetadata(role, family, source["record"], source["current"], AT,
                          source["binding"]["recipe_sha256"], source["binding"]["parameters"], DATES,
                          source["publication_refs"])
    current = source["current"]
    raw = [current["asset_uids"][a] for a in current["assets"][:40]]
    payload = {"family": family, "ordered_U": current["assets"].copy(),
               "uids": current["asset_uids"].copy(), "epochs": current["asset_epochs"].copy(),
               "covariance": cov.copy()}
    payload["state_id"] = meta.header["risk_state_id"]
    for key in ("method", "parameters", "history_recipe", "recipe_sha256", "horizon_sessions",
                "security_coordinate", "source_support_identity", "as_of", "cutoff", "available_at"):
        payload[key] = deepcopy(meta.header[key])
    return meta, payload, raw


def reseal_synthetic_header(meta, payload, **fields):
    # Construct a fresh synthetic projection; never mutate a previously bound seal.
    result = replace(meta, header={**deepcopy(meta.header), **fields})
    return result


def proposal_receipt(meta, proposal):
    receipt = {"candidate_id": "C14_P01", "decision_asof": meta.decision_asof,
               "chosen_uids": list(proposal), "exact_decoder_cache_complete": True,
               "artifact_ref": {"path": str(b.RUN / "synthetic-decoder-never-opened.json"), "sha256": "f" * 64},
               "decoder_request_id": "MAIN|C14_P01|2025-12-19T00:00:00"}
    return b.P01Proposal(receipt, receipt["artifact_ref"])


def veto(meta, payload, raw, proposal, *, receipt=None):
    return b.whole_set_veto(meta, payload, raw, proposal,
                            proposal_receipt=proposal_receipt(meta, proposal) if receipt is None else receipt)


def test_exact_role_matrix_retains_all_masks_slots_and_zero_execution(matrix):
    hybrids = [row for row in matrix["roles"] if row["solver_requirement"]["route"] == "HYBRID"]
    assert [(row["role"], row["required_family_method"]) for row in hybrids] == list(EXPECTED_HYBRIDS)
    assert [row["conditional_fit_slots"] for row in hybrids] == [14, 14, 14, 34, 34, 34]
    assert sum(row["conditional_fit_slots"] for row in matrix["roles"]) == 144
    assert matrix["slot_counts_by_classification"]["WAITING_R5_PUBLICATION"] == 28
    assert matrix["slot_counts_by_classification"]["STRUCTURALLY_UNSUPPORTED_BY_CURRENT_R5"] == 14
    assert matrix["slot_counts_by_classification"]["REQUIRES_ADDITIONAL_SPECIFIC_INPUT"] == 102
    assert len(matrix["roles"]) == 23 and len(matrix["risk_efficiency_hypotheses"]) == 20
    assert all(row["required_dates"] == list(DATES) for row in matrix["roles"])
    assert matrix["endpoint_requirements"]["input_scenario_source_is_distinct_from_realized_endpoint_source"] is True
    assert all(row["calendar_positions"] == 752 and row["learned_support_mask"] == 482
               and row["required_732_mature_day_support"] for row in matrix["roles"])
    assert requirement(matrix, "C14_D02")["solver_requirement"]["maximum_named_requests"] == 0
    assert requirement(matrix, "C14_D12")["current_status"] == "BLOCKED_BUDGET"
    assert requirement(matrix, "C14_RX7")["current_status"] == "BLOCKED_BUDGET"
    assert requirement(matrix, "C14_RX_RIDGE_DIAG")["current_status"] == "BLOCKED_BY_CURRENT_B_SCOPE"
    assert all(value == 0 for value in matrix["counts"].values())
    assert matrix["strict_PIT_promotion_eligible"] is False


def test_metadata_binding_returns_no_numeric_authority_and_defensive_copy(matrix):
    source = inputs()
    result = b.bind_role_metadata(requirement(matrix), **source)
    source["record"]["asset_epochs"]["SYN000"] = "later-mutated"
    assert result.header["asset_epochs"]["SYN000"] == "synthetic-epoch-000"
    assert result.family == "LW" and result.coverage_dates == DATES
    assert len(result.current["assets"]) == 44
    assert "covariance" not in result.header
    assert b.contract.qualify_header(result.header, result.current, AT, "b" * 64)["numeric_read_authority"] is False


@pytest.mark.parametrize("field,value,reason", [
    ("family", "OAS", "EXACT_FROZEN_ROLE_FAMILY"),
    ("method", "OAS", "EXACT_METHOD"),
    ("parameters", {"synthetic_fixed": 2}, "EXACT_METHOD"),
    ("history_recipe", "different-history", "EXACT_METHOD"),
    ("representation", "TWO_ANCHORS_ONLY", "ANCHOR"),
    ("security_coordinate", "other-coordinate", "SOURCE_COORDINATE"),
    ("source_support_identity", {"source": "wrong-source"}, "SOURCE_COORDINATE"),
    ("horizon_sessions", 3, "NATIVE_H5"),
    ("recipe_sha256", "e" * 64, "EXACT_RECIPE"),
    ("cutoff", "2025-12-17T21:00:00+00:00", "CUTOFF"),
    ("available_at", "2025-12-20T21:00:00+00:00", "AVAILABLE"),
    ("available_at", "2025-12-16T21:00:00+00:00", "AVAILABLE"),
    ("available_at", "2026-01-01T00:00:00+00:00", "PRE2026"),
    ("available_at", "2025-12-18", "PRE2026"),
    ("coverage_dates", DATES[:-1], "NO_SHORTENING"),
    ("psd_qualified", False, "PSD_AND_FINITE"),
    ("finite_check", False, "PSD_AND_FINITE"),
    ("source_still_valid", False, "SOURCE_OR_MATURITY"),
])
def test_metadata_exactness_blocks_only_dependent_input(matrix, field, value, reason):
    source = inputs()
    source["record"][field] = value
    with pytest.raises(ValueError, match=reason):
        b.bind_role_metadata(requirement(matrix), **source)


@pytest.mark.parametrize("field", ["assets", "asset_uids", "asset_epochs"])
def test_full_u_uid_epoch_metadata_rejects_padding_or_stitch(matrix, field):
    source = inputs()
    record = source["record"]
    if field == "assets":
        record[field] = record[field][:-1]
    else:
        record[field]["SYN000"] = record[field]["SYN001"]
    with pytest.raises(ValueError, match="FULL_U_UID_EPOCH"):
        b.bind_role_metadata(requirement(matrix), **source)


@pytest.mark.parametrize("case", ["2026_decision", "missing_ledger", "other_owner"])
def test_publication_and_decision_authority_fail_closed(matrix, case):
    source = inputs()
    if case == "2026_decision":
        source["decision_asof"] = "2026-01-01T00:00:00+00:00"
    elif case == "missing_ledger":
        source["publication_refs"].pop("ledger")
    else:
        source["publication_refs"]["bank"]["path"] = "D:/us-tech-quant-backtests/other-owner/synthetic.json"
    with pytest.raises(ValueError, match="PRE2026|ORIGINAL_R5"):
        b.bind_role_metadata(requirement(matrix), **source)


@pytest.mark.parametrize("family,missing,reason", [
    ("TAIL_CVAR", "scenario_qualified", "NATIVE_H5_SCENARIO"),
    ("TAIL_CVAR", "scenario_horizon", "NATIVE_H5_SCENARIO"),
    ("TAIL_CVAR", "scenario_source_ref", "NATIVE_H5_SCENARIO"),
    ("UNCERTAINTY_JACKKNIFE", "replica_count", "FULL_PSD_REPLICAS"),
    ("UNCERTAINTY_JACKKNIFE", "replicas_full_psd_qualified", "FULL_PSD_REPLICAS"),
    ("UNCERTAINTY_JACKKNIFE", "replica_refs", "FULL_PSD_REPLICAS"),
])
def test_tail_and_uncertainty_need_specific_native_inputs(matrix, family, missing, reason):
    role = "C14_G2" if family == "TAIL_CVAR" else "C14_G3"
    required = requirement(matrix, role)
    # Isolate input qualification for a hypothetical later valid publication.
    required["current_status"] = "WAITING_R5_PUBLICATION"
    source = inputs(role, family)
    source["record"].update(scenario_qualified=True, scenario_horizon=5,
                             scenario_source_ref={"synthetic": True}, replica_count=2,
                             replicas_full_psd_qualified=True, replica_refs=[{"synthetic": True}])
    source["record"].pop(missing)
    with pytest.raises(ValueError, match=reason):
        b.bind_role_metadata(required, **source)


def test_partial_publication_preserves_every_role_independently(matrix):
    good = inputs()
    late = inputs("C14_RX_XGB_QQQ_RESIDUAL", "QQQ_RESIDUAL")
    late["record"]["available_at"] = "2025-12-20T21:00:00+00:00"
    missing = inputs("C14_D05", "OAS")
    missing["record"]["coverage_dates"] = DATES[:-1]
    result = b.bind_partial_roles(matrix, {"C14_RX_HGB_LW": good,
                                          "C14_RX_XGB_QQQ_RESIDUAL": late, "C14_D05": missing})
    by_role = {row["role"]: row for row in result["roles"]}
    assert [row["role"] for row in result["roles"]] == [row["role"] for row in matrix["roles"]]
    assert by_role["C14_RX_HGB_LW"]["status"] == "READY_FOR_METADATA_BINDING"
    assert by_role["C14_RX_XGB_QQQ_RESIDUAL"]["status"] == "BLOCKED_SOURCE"
    assert by_role["C14_D05"]["status"] == "BLOCKED_INPUT"
    assert by_role["C14_D06"]["status"] == "WAITING_R5_PUBLICATION"
    assert by_role["C14_RX_RIDGE_DIAG"]["status"] == "BLOCKED_BY_CURRENT_B_SCOPE"
    assert by_role["C14_D12"]["status"] == by_role["C14_RX7"]["status"] == "BLOCKED_BUDGET"
    assert by_role["C14_D02"]["status"] == "READY_FOR_METADATA_BINDING"
    assert all((row["calendar_positions"], row["full_risk_mature_positions"], row["learned_positions"]) == (752, 732, 482)
               and row["numeric_execution_performed"] is False for row in result["roles"])
    assert all(value == 0 for value in result["counts"].values())
    assert result["strict_PIT_promotion_eligible"] is False
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("role,family", EXPECTED_HYBRIDS)
def test_hybrid_exact_family_no_fallback_even_with_typed_synthetic_meta(role, family):
    assert family != "OAS"
    meta, payload, raw = numeric_fixture(role, "OAS")
    with pytest.raises(ValueError, match="EXACT.*HYBRID|FAMILY"):
        b.hybrid_coordinates(meta, payload, raw)


def test_hybrid_full_u_and_pair_coordinates_remain_44_by_2_and_12_columns():
    meta, payload, raw = numeric_fixture("C14_RX_HGB_LW", "LW", np.diag(np.arange(1, 45)))
    original = payload["covariance"].copy()
    coords = b.hybrid_coordinates(meta, payload, raw)
    assert coords.shape == (44, 2)
    np.testing.assert_array_equal(coords[:, 0], np.arange(1, 45))
    pairs = b.pair_risk_columns(coords, [20, 21], [10, 11])
    assert pairs.shape == (2, 12)
    np.testing.assert_array_equal(pairs[:, 4:6], coords[[20, 21]] - coords[[10, 11]])
    np.testing.assert_array_equal(payload["covariance"], original)


@pytest.mark.parametrize("case,reason", [
    ("family", "FULL_U_UID_EPOCH"), ("ordered_U", "FULL_U_UID_EPOCH"),
    ("uids", "FULL_U_UID_EPOCH"), ("epochs", "FULL_U_UID_EPOCH"),
    ("short_matrix", "NO_NUMERIC_FULL_U_PADDING"), ("nonfinite", "NONFINITE"),
    ("non_psd", "NOT_PSD"), ("wrong_sha", "PAYLOAD_SHA"),
    ("short_raw", "RAW40"), ("duplicate_raw", "RAW40"),
])
def test_numeric_binding_blocks_no_padding_non_psd_or_unpinned_payload(case, reason):
    meta, payload, raw = numeric_fixture("C14_G1", "LW")
    if case == "family": payload["family"] = "OAS"
    elif case == "ordered_U": payload["ordered_U"].reverse()
    elif case == "uids": payload["uids"]["SYN000"] = "cross-identity"
    elif case == "epochs": payload["epochs"]["SYN000"] = "cross-epoch"
    elif case == "short_matrix": payload["covariance"] = np.eye(40)
    elif case == "nonfinite": payload["covariance"][0, 0] = np.nan
    elif case == "non_psd": payload["covariance"][0, 1] = payload["covariance"][1, 0] = 2
    elif case == "wrong_sha": payload["covariance"][0, 0] = 2
    elif case == "short_raw": raw.pop()
    else: raw[-1] = raw[0]
    with pytest.raises(ValueError, match=reason):
        veto(meta, payload, raw, raw[:20])


@pytest.mark.parametrize("role,family", [("C14_G1", "LW"), ("C14_G2", "TAIL_CVAR"),
                                          ("C14_G3", "UNCERTAINTY_JACKKNIFE"), ("C14_G4", "PCA_FACTOR")])
@pytest.mark.parametrize("passed", [True, False])
def test_gates_keep_or_veto_whole_decoded_set_without_rematch_refill(role, family, passed):
    cov = np.eye(44)
    if role == "C14_G1":
        cov[20:30, 20:30] *= .5 if passed else 3
    elif role == "C14_G4":
        for i in range(10):
            group = [10 + i, 20 + i, 30 + i]
            cov[np.ix_(group, group)] = .8
            cov[group, group] = 1
    meta, payload, raw = numeric_fixture(role, family, cov)
    proposal = raw[:10] + raw[20:30]
    if role == "C14_G2":
        scenes = -np.ones((3, 44))
        scenes[:, 20:30] *= .5 if passed else 3
        payload["scenarios"] = scenes
        meta = reseal_synthetic_header(meta, payload, scenario_sha256=b.sha_array(scenes))
    elif role == "C14_G3":
        second = np.eye(44)
        selected = slice(10, 20) if passed else slice(20, 30)
        second[selected, selected] *= 3
        replicas = np.stack([np.eye(44), second])
        payload["replicas"] = replicas
        meta = reseal_synthetic_header(meta, payload, replica_count=2, replica_sha256s=[b.sha_array(x) for x in replicas])
    elif role == "C14_G4" and not passed:
        proposal = raw[:10] + [raw[pos] for i in range(5) for pos in (20 + i, 30 + i)]
    result = veto(meta, payload, raw, proposal)
    assert result["status"] == ("PASS_WHOLE_SET" if passed else "VETO_WHOLE_SET")
    assert result["chosen_uids"] == (proposal if passed else raw[:20])
    assert result["proposal_uids"] == proposal and result["anchor"] == "C14_P01"
    assert result["rematching"] is False and result["refill"] is False and result["extra_solves"] == 0
    assert len(result["chosen_uids"]) == 20 and set(raw[:10]) <= set(result["chosen_uids"])


@pytest.mark.parametrize("role,family,field", [("C14_G2", "TAIL_CVAR", "scenarios"),
                                               ("C14_G3", "UNCERTAINTY_JACKKNIFE", "replicas")])
def test_covariance_or_scalar_sigma_cannot_substitute_for_native_tail_replicas(role, family, field):
    meta, payload, raw = numeric_fixture(role, family)
    meta = reseal_synthetic_header(meta, payload, replica_count=2, replica_sha256s=[])
    payload["sigma"] = np.ones(44)
    with pytest.raises(ValueError, match="SCENARIOS|REPLICA"):
        veto(meta, payload, raw, raw[:20])
    payload[field] = np.ones((2, 40)) if field == "scenarios" else np.ones((2, 40, 40))
    with pytest.raises(ValueError, match="SCENARIOS|REPLICA"):
        veto(meta, payload, raw, raw[:20])


@pytest.mark.parametrize("case,reason", [("hash", "REPLICA_PAYLOAD_SHA"),
                                         ("non_psd", "NOT_PSD"), ("one", "REPLICA_DIMENSION")])
def test_native_replica_hash_count_and_psd_are_each_required(case, reason):
    meta, payload, raw = numeric_fixture("C14_G3", "UNCERTAINTY_JACKKNIFE")
    replicas = np.stack([np.eye(44), np.eye(44)])
    if case == "non_psd": replicas[0, 0, 1] = replicas[0, 1, 0] = 2
    hashes = [b.sha_array(x) for x in replicas]
    if case == "hash": hashes[0] = "0" * 64
    if case == "one": replicas = replicas[:1]
    payload["replicas"] = replicas
    meta = reseal_synthetic_header(meta, payload, replica_count=2, replica_sha256s=hashes)
    with pytest.raises(ValueError, match=reason):
        veto(meta, payload, raw, raw[:20])


@pytest.mark.parametrize("case", ["hash", "nonfinite"])
def test_native_scenario_hash_and_finite_full_u_input_are_required(case):
    meta, payload, raw = numeric_fixture("C14_G2", "TAIL_CVAR")
    scenarios = -np.ones((3, 44))
    digest = b.sha_array(scenarios)
    if case == "hash": digest = "0" * 64
    else: scenarios[0, 0] = np.nan
    payload["scenarios"] = scenarios
    meta = reseal_synthetic_header(meta, payload, scenario_sha256=digest)
    with pytest.raises(ValueError, match="NATIVE_H5_SCENARIOS"):
        veto(meta, payload, raw, raw[:20])


@pytest.mark.parametrize("field,value", [
    ("state_id", "wrong-state"), ("method", "OAS"), ("recipe_sha256", "0" * 64),
    ("horizon_sessions", 3), ("cutoff", "2025-12-15T21:00:00+00:00"),
    ("as_of", "2025-12-16T21:00:00+00:00"),
    ("source_support_identity", {"source": "wrong-source"}),
    ("parameters", {"synthetic_fixed": 2}),
])
def test_numeric_state_source_method_time_parameters_match_typed_projection(field, value):
    meta, payload, raw = numeric_fixture("C14_G1", "LW")
    payload[field] = value
    with pytest.raises(ValueError, match="NUMERIC_STATE_SOURCE_METHOD_TIME_PARAMS"):
        veto(meta, payload, raw, raw[:20])


def test_sealed_metadata_rejects_later_identity_mutation():
    meta, payload, raw = numeric_fixture("C14_G1", "LW")
    meta.current["asset_epochs"]["SYN000"] = "later-epoch"
    with pytest.raises(ValueError, match="MUTATED_ROLE_METADATA"):
        veto(meta, payload, raw, raw[:20])


@pytest.mark.parametrize("field,value", [
    ("candidate_id", "C14_P04"),
    ("exact_decoder_cache_complete", False),
    ("chosen_uids", []),
    ("decision_asof", "2026-01-01T00:00:00+00:00"),
    ("decoder_request_id", "MAIN|C14_P04|2025-12-19"),
])
def test_gate_needs_complete_exact_p01_decoded_proposal_receipt(field, value):
    meta, payload, raw = numeric_fixture("C14_G1", "LW")
    data = deepcopy(proposal_receipt(meta, raw[:20]).receipt)
    data[field] = value
    receipt = b.P01Proposal(data, data["artifact_ref"])
    with pytest.raises(ValueError, match="P01|PROPOSAL|DECODER|RECEIPT|PRE2026"):
        veto(meta, payload, raw, raw[:20], receipt=receipt)


@pytest.mark.parametrize("case", ["nonfinite", "wrong_width", "out_of_domain"])
def test_missing_or_invalid_pair_coordinates_never_become_zero_features(case):
    coords = np.zeros((44, 2))
    challenger = [20]
    if case == "nonfinite": coords[0, 0] = np.nan
    elif case == "wrong_width": coords = np.zeros((44, 1))
    else: challenger = [44]
    with pytest.raises(ValueError, match="FINITE_PAIR_RISK_COORDINATES"):
        b.pair_risk_columns(coords, challenger, [10])


def test_raw_identity_has_no_metadata_numeric_input_or_optimizer_calls(matrix):
    raw = [f"synthetic-UID-{i:03d}" for i in range(40)]
    result = b.classical_route(requirement(matrix, "C14_D02"), None, None, raw, AT)
    assert result["chosen_uids"] == raw[:20] and result["optimizer_solve_calls"] == 0


class BeforePayloadValue(StringIO):
    def __init__(self, text, value_start):
        super().__init__(text)
        self.value_start = value_start
    def read(self, size=-1):
        assert self.tell() < self.value_start, "Forbidden numeric value was accessed"
        return super().read(size)


@pytest.mark.parametrize("key", sorted(b.NUMERIC_FIELDS))
def test_metadata_reader_rejects_payload_key_before_accessing_value(key):
    prefix = '{"nested":{"' + key.upper() + '":'
    stream = BeforePayloadValue(prefix + 'THIS_VALUE_MUST_NEVER_BE_READ}}', len(prefix))
    with pytest.raises(b.RiskBindingBlocked, match="PAYLOAD_FORBIDDEN"):
        b._MetadataJSON(stream).value()
    assert stream.tell() == len(prefix)


@pytest.mark.parametrize("text,reason", [
    ('{"role":"a","role":"b"}', "DUPLICATE"),
    ('{"role":1 "next":2}', "OBJECT"),
    ('{"role":', "PRIMITIVE"),
    ('{"role":"unfinished}', "TRUNCATED"),
    ('{"roles":[1,]}', "PRIMITIVE"),
    ('{"n":NaN}', "NONFINITE"),
])
def test_metadata_reader_rejects_duplicates_malformed_and_nonfinite(text, reason):
    with pytest.raises(ValueError, match=reason):
        b._MetadataJSON(StringIO(text)).value()


def test_metadata_reader_accepts_only_synthetic_metadata_without_payload():
    source = {"research_id": b.B_ID, "strict_PIT_promotion_eligible": False,
              "roles": [{"family": "LW", "horizon_sessions": 5, "psd_qualified": True}],
              "path_note": "synthetic never opened", "source_hash": "a" * 64}
    reader = b._MetadataJSON(StringIO(json.dumps(source)))
    assert reader.value() == source
    reader.space()
    assert reader.char == ""


@pytest.fixture
def native_publication(monkeypatch, matrix):
    source = inputs()
    current = source["current"]
    # Native bank records have source availability, not invented state fields.
    recipe = {"method": "LW", "history": "synthetic-frozen-mature-past", "horizon_sessions": 5}
    recipe_sha = b.content_hash(recipe)
    state_asof = DATES[0] + "T21:00:00+00:00"
    cutoff = "2022-12-30T21:00:00+00:00"
    native = {**deepcopy(current), "family": "LW", "method": "LW",
              "status": "PASS_FROZEN_HISTORY_MECHANISM", "as_of": state_asof, "cutoff": cutoff,
              "dependency_local_event_id": "synthetic-primary-event",
              "recipe_id": "synthetic-native-recipe", "risk_state_id": "synthetic-native-state",
              "artifact_ref": {"path": str(b.contract.B_RUN / "synthetic-native-state-never-opened.joblib"), "sha256": "c" * 64},
              "event_policy_binding": {"structural_identity": source["record"]["structural_identity"]},
              "covariance_sha256": None, "finite_check": True,
              "source_receipt": {"available_at": cutoff, "observation_time_assumed": True,
                                 "strict_PIT_promotion_eligible": False,
                                 "return_coordinate": current["security_coordinate"]}}
    assert "available_at" not in native and "parameters" not in native
    plan = {"research_id": b.B_ID, "estimator_recipes": {"synthetic-native-recipe": recipe},
            "method_bindings": [{"family": "LW", "method": "LW", "recipe_sha256": recipe_sha}]}
    support = {"research_id": b.B_ID, "daily_support_chain": [
        {"decision_asof": date + "T21:00:00+00:00",
         "dependency_local_event_ids": {"PRIMARY": "synthetic-primary-event"}} for date in DATES]}
    bank = {"schema": "B_R5_EVENT_RISK_BANK_V1", "research_id": b.B_ID,
            "states": [native], "blocked_or_failed": []}
    continuity = {"source_only_qualification": True, "real_numeric_reads": 0,
                  "family_continuity": {"LW": {"scope": "CONTINUOUS", "continuous_chain": True,
                                                "qualified_days": 752}}}
    publication = b.PublicationBinding(plan, support, bank, source["publication_refs"], continuity)
    pinned_calls = []
    def synthetic_sha(path):
        pinned_calls.append(str(path))
        return "d" * 64
    monkeypatch.setattr(b, "sha", synthetic_sha)
    required = requirement(matrix)
    required["required_dates"] = [date + "T00:00:00" for date in DATES]
    return {"publication": publication, "requirement": required, "current": current,
            "decision_asof": DATES[-1] + "T21:00:00+00:00", "pinned_calls": pinned_calls,
            "recipe": recipe}


def native_project(fixture, publication=None):
    return b.project_r5_role(fixture["publication"] if publication is None else publication,
                             fixture["requirement"], current=fixture["current"],
                             decision_asof=fixture["decision_asof"])


def test_native_r5_projector_uses_frozen_event_close_and_defers_numeric_psd(native_publication):
    fixture = native_publication
    publication = fixture["publication"]
    record = publication.bank["states"][0]
    result = native_project(fixture)
    assert publication.bank["schema"] == "B_R5_EVENT_RISK_BANK_V1"
    assert "available_at" not in record and "parameters" not in record
    assert result.header["available_at"] == record["as_of"]
    assert result.header["source_available_at"] == record["source_receipt"]["available_at"]
    assert result.header["available_at_basis"] == "FROZEN_EVENT_CLOSE_REPLAY_ASSUMPTION"
    assert result.header["psd_qualified"] == "DEFERRED_NUMERIC_EXACT_OWNER_CHECK"
    assert result.header["covariance_sha256"] is None
    assert result.header["covariance_digest_status"] == "DEFERRED_FROM_EXACT_PINNED_STATE"
    assert result.header["strict_PIT_promotion_eligible"] is False
    assert result.parameters == result.header["history_recipe"] == fixture["recipe"]
    assert result.coverage_dates == tuple(fixture["requirement"]["required_dates"])
    assert len(result.coverage_dates) == 752 and len(result.current["assets"]) == 44
    assert result.header["risk_state_id"] == "synthetic-native-state"
    assert len(fixture["pinned_calls"]) == len(publication.refs)
    result.verify()


def test_native_r5_projector_never_shortens_required752_mask(native_publication):
    fixture = native_publication
    publication = fixture["publication"]
    support = deepcopy(publication.support)
    support["daily_support_chain"].pop(0)
    shortened = replace(publication, support=support)
    with pytest.raises(ValueError, match="EXACT752_DATE_MASK_MISMATCH"):
        native_project(fixture, shortened)
    assert len(fixture["requirement"]["required_dates"]) == 752
    assert len(publication.support["daily_support_chain"]) == 752


def test_native_r5_projector_blocks_late_source_receipt_clock(native_publication):
    fixture = native_publication
    publication = fixture["publication"]
    bank = deepcopy(publication.bank)
    record = bank["states"][0]
    record["source_receipt"]["available_at"] = record["as_of"]
    late_source = replace(publication, bank=bank)
    with pytest.raises(ValueError, match="NATIVE_SOURCE_CLOCK_AND_EVENT_REPLAY_BOUNDARY"):
        native_project(fixture, late_source)


@pytest.mark.parametrize("case", ["incomplete", "anchor_only", "blocked_role"])
def test_native_r5_projector_rejects_unqualified_family_and_anchor(native_publication, matrix, case):
    fixture = native_publication
    publication = fixture["publication"]
    if case == "blocked_role":
        required = requirement(matrix, "C14_G2")
        with pytest.raises(ValueError, match="BLOCKED_BY_CURRENT_B_SCOPE"):
            b.project_r5_role(publication, required, current=fixture["current"],
                              decision_asof=fixture["decision_asof"])
        return
    continuity = deepcopy(publication.continuity)
    family = continuity["family_continuity"]["LW"]
    family["qualified_days"] = 751 if case == "incomplete" else 2
    if case == "anchor_only":
        family.update(scope="TWO_ANCHORS_ONLY", continuous_chain=False)
    with pytest.raises(ValueError, match="COMPLETE752_CURRENT_FAMILY_CHAIN_REQUIRED"):
        native_project(fixture, replace(publication, continuity=continuity))


@pytest.mark.parametrize("case,reason", [("mutated", "MUTATED_PUBLICATION_METADATA"),
                                         ("pin", "PHYSICAL_PIN_CHANGED"),
                                         ("custody", "CUSTODY_REFERENCE_ONLY")])
def test_publication_binding_verify_checks_seal_pins_and_owner_without_file_read(native_publication, monkeypatch, case, reason):
    publication = native_publication["publication"]
    if case == "mutated":
        publication.bank["states"][0]["risk_state_id"] = "later-mutated-state"
    elif case == "pin":
        monkeypatch.setattr(b, "sha", lambda path: "0" * 64)
    else:
        refs = deepcopy(publication.refs)
        refs["bank"]["path"] = "D:/us-tech-quant-backtests/other-owner/synthetic-never-opened.json"
        publication = replace(publication, refs=refs)
    with pytest.raises(ValueError, match=reason):
        publication.verify()



def test_reader_entry_absent_bank_stops_at_readiness_without_hash_json_or_joblib(monkeypatch):
    import sys
    from types import SimpleNamespace
    called = []
    ready = {"status": "WAITING_B_R5_NUMERIC_BANK", "files": {"bank": False, "freeze": True, "qualification": True},
             "numeric_reads": 0, "new_fits": 0, "new_solves": 0, "strict_PIT_promotion_eligible": False}
    def readiness():
        called.append("readiness")
        return ready
    def forbidden(*args, **kwargs):
        raise AssertionError("Absent bank must not trigger hashing, JSON, qualification or joblib")
    monkeypatch.setattr(b.contract, "readiness", readiness)
    for name in ("sha", "read_r5_metadata", "qualify_publication", "load_qualified_state"):
        monkeypatch.setattr(b, name, forbidden)
    monkeypatch.setitem(sys.modules, "joblib", SimpleNamespace(load=forbidden))
    result = b.read_publication_metadata()
    assert called == ["readiness"]
    assert result["status"] == "WAITING_R5_PUBLICATION" and result["publication"] is None
    assert result["readiness"] == ready and all(value == 0 for value in result["counts"].values())


@pytest.mark.parametrize("collection", ["states", "records"])
def test_reader_record_allowlist_blocks_unknown_alias_before_value_access(collection):
    alias = "covariance_alias"
    assert alias not in b.NUMERIC_FIELDS and alias not in b.BANK_STATE_KEYS
    prefix = '{"' + collection + '":[{"family":"LW","' + alias + '":'
    stream = BeforePayloadValue(prefix + 'FORBIDDEN_ALIAS_VALUE_MUST_NOT_BE_READ}]}', len(prefix))
    root_keys = b.BANK_KEYS if collection == "states" else b.LEDGER_KEYS
    with pytest.raises(b.RiskBindingBlocked, match="UNAPPROVED_R5_RECORD_FIELD:covariance_alias"):
        b._MetadataJSON(stream, root_keys=root_keys, record_collections=(collection,)).value()
    assert stream.tell() == len(prefix)


@pytest.mark.parametrize("case", ["valid", "wrong_baseline", "2026_counter"])
def test_reader_native_fit_status_without_research_id_is_scope_checked_in_memory(monkeypatch, case):
    from types import SimpleNamespace
    ledger = {"status": "B_R5_FINITE_EVENT_RISK_QUEUE_COMPLETE", "inherited_fit_units": 3027,
              "test2026_rows_read": 0, "account_paths": 0, "new_fit_units": 0,
              "records": [{"family": "LW", "method": "LW", "status": "PASS_FROZEN_HISTORY_MECHANISM", "finite_check": True}],
              "failures": [], "baseline_source": "synthetic-only frozen original R5 baseline"}
    assert "research_id" not in ledger
    if case == "wrong_baseline": ledger["inherited_fit_units"] = 3028
    elif case == "2026_counter": ledger["test2026_rows_read"] = 1
    text = json.dumps(ledger)
    reference = {"path": str(b.contract.B_RUN / "FIT_STATUS.json"), "sha256": "d" * 64}
    opened = []
    def in_memory_open(path, *args, **kwargs):
        assert str(path) == reference["path"]
        opened.append(str(path))
        return StringIO(text)
    # Patch the physical access methods too: no real path/config/stat/hash/open.
    with monkeypatch.context() as isolated:
        isolated.setattr(b.Path, "resolve", lambda path, *args, **kwargs: path)
        isolated.setattr(b.Path, "stat", lambda path, *args, **kwargs: SimpleNamespace(st_size=len(text.encode("utf-8"))))
        isolated.setattr(b.Path, "open", in_memory_open)
        isolated.setattr(b, "sha", lambda path: "d" * 64)
        isolated.setattr(b, "assert_safe_output_path", lambda *args, **kwargs: None)
        if case == "valid":
            result = b.read_r5_metadata(reference)
        else:
            with pytest.raises(ValueError, match="EXACT_ORIGINAL_R5_LEDGER_SCOPE_REQUIRED"):
                b.read_r5_metadata(reference)
    assert opened == [reference["path"]]
    if case == "valid": assert result == ledger and "research_id" not in result



def test_typed_p01_receipt_rejects_mutation_before_gate():
    meta, payload, raw = numeric_fixture("C14_G1", "LW")
    receipt = proposal_receipt(meta, raw[:20])
    receipt.receipt["chosen_uids"] = []
    with pytest.raises(ValueError, match="MUTATED_P01_PROPOSAL"):
        veto(meta, payload, raw, raw[:20], receipt=receipt)


@pytest.mark.parametrize("case", ["valid", "plain", "wrong_meta", "wrong_pin", "wrong_digest", "mutated"])
def test_missing_exporter_digest_needs_exact_sealed_native_payload(case):
    meta, values, raw = numeric_fixture("C14_G1", "LW")
    meta = reseal_synthetic_header(meta, values, covariance_sha256=None,
                                    covariance_digest_status="DEFERRED_FROM_EXACT_PINNED_STATE")
    payload = b.NativeRiskPayload(values, meta._seal, deepcopy(meta.header["artifact_ref"]),
                                 b.sha_array(values["covariance"]))
    if case == "plain": payload = values
    elif case == "wrong_meta": payload = replace(payload, metadata_seal="0" * 64)
    elif case == "wrong_pin": payload = replace(payload, artifact_ref={**payload.artifact_ref, "sha256": "0" * 64})
    elif case == "wrong_digest": payload = replace(payload, covariance_sha256="0" * 64)
    elif case == "mutated": payload.values["covariance"][0, 0] = 2
    if case == "valid":
        result = veto(meta, payload, raw, raw[:20])
        assert result["chosen_uids"] == raw[:20] and result["extra_solves"] == 0
    else:
        with pytest.raises(ValueError, match="ATTESTATION_REQUIRED|MUTATED_NATIVE_RISK_PAYLOAD"):
            veto(meta, payload, raw, raw[:20])


def test_classical_decision_clock_mismatch_blocks_before_membership_owner(matrix):
    meta, payload, raw = numeric_fixture("C14_D01", "LW")
    with pytest.raises(ValueError, match="EXACT_CLASSICAL_DECISION_CLOCK_REQUIRED"):
        b.classical_route(requirement(matrix, "C14_D01"), meta, payload, raw,
                           "2025-12-18T21:00:00+00:00")


@pytest.mark.parametrize("case", ["valid", "charged_incomplete", "wrong_pin", "wrong_matching_hash", "wrong_full_u", "wrong_pair_keys"])
def test_p01_cache_reader_reuses_one_complete_swap_with_exact_raw44_identity_in_memory(monkeypatch, case):
    from types import SimpleNamespace
    from scripts.research.a2.training import selector_maximal_breadth as decoder
    date = pd.Timestamp("2025-12-19")
    raw = pd.DataFrame({"signal_date": [date] * 44,
                        "security_uid": [f"synthetic-UID-{i:03d}" for i in range(44)],
                        "raw_rank": np.arange(1, 45), "raw_score": np.arange(44, 0, -1, dtype=float),
                        "U_t_fingerprint": ["synthetic-full44-identity"] * 44})
    geometry = decoder.pairs.geometry(raw)
    assert len(geometry) == 200 and len(raw) == 44
    identity = {"candidate_id": "C14_P01", "design_sha256": b.DESIGN_SHA,
                "pair_key_sha256": decoder.pairs.pair_key_sha256(geometry),
                "full_U_keys_sha256": decoder.content_hash(raw[[*decoder.KEYS, "raw_rank", "U_t_fingerprint"]].astype(str).values.tolist()),
                "score_sha256": "a" * 64, "eligibility_sha256": "b" * 64}
    matching = [{"signal_date": date.isoformat(), "challenger_uid": raw.security_uid.iloc[20],
                 "incumbent_uid": raw.security_uid.iloc[19], "challenger_raw_rank": 21,
                 "incumbent_raw_rank": 20, "predicted_edge": .125}]
    token = "MAIN|C14_P01|" + date.isoformat()
    request = {"status": "COMPLETE", "charged": 1, "identity": deepcopy(identity),
               "matching_records": matching, "matching_sha256": decoder.content_hash(matching)}
    if case == "charged_incomplete": request["status"] = "ENTERED"
    elif case == "wrong_matching_hash": request["matching_sha256"] = "0" * 64
    elif case == "wrong_full_u": raw.loc[43, "U_t_fingerprint"] = "different-outside-Raw40"
    elif case == "wrong_pair_keys":
        identity["pair_key_sha256"] = "0" * 64
        request["identity"] = deepcopy(identity)
    ledger = {"research_id": b.contract.ID, "hard_cap": 30000, "requests": {token: request}}
    text = json.dumps(ledger)
    reference = {"path": str(b.RUN / "SOLVE_LEDGER.json"), "sha256": "d" * 64}
    opened = []
    def in_memory_open(path, *args, **kwargs):
        assert str(path) == reference["path"]
        opened.append(str(path))
        return StringIO(text)
    def forbidden(*args, **kwargs):
        raise AssertionError("Cache reuse must never decode or solve")
    with monkeypatch.context() as isolated:
        isolated.setattr(b.Path, "resolve", lambda path, *args, **kwargs: path)
        isolated.setattr(b.Path, "stat", lambda path, *args, **kwargs: SimpleNamespace(st_size=len(text.encode("utf-8"))))
        isolated.setattr(b.Path, "open", in_memory_open)
        isolated.setattr(b, "sha", lambda path: "0" * 64 if case == "wrong_pin" else "d" * 64)
        isolated.setattr(decoder.pairs, "_exact_assignment", forbidden)
        if case == "valid":
            result = b.read_p01_proposal(reference, decision_asof=AT, raw_metadata=raw, expected_identity=identity)
        else:
            with pytest.raises(ValueError, match="NO_COMPLETE_CACHE|PHYSICAL_PIN_CHANGED|MATCH_CACHE_SHA_REQUIRED|FULL_U_AND200_PAIR_KEYS_REQUIRED"):
                b.read_p01_proposal(reference, decision_asof=AT, raw_metadata=raw, expected_identity=identity)
    assert opened == ([] if case == "wrong_pin" else [reference["path"]])
    if case == "valid":
        assert type(result) is b.P01Proposal
        chosen = result["chosen_uids"]
        assert len(chosen) == 20 and set(raw.security_uid.iloc[:10]) <= set(chosen)
        assert raw.security_uid.iloc[20] in chosen and raw.security_uid.iloc[19] not in chosen
        assert result["decoder_request_id"] == token and result["exact_decoder_cache_complete"] is True
        result.verify()


@pytest.mark.parametrize("case", ["valid", "wrong_freeze", "failed_retention"])
def test_publication_qualification_requires_native_custody_terminal_owner_and_failed_retention(native_publication, monkeypatch, case):
    fixture = native_publication
    plan = deepcopy(fixture["publication"].plan)
    support = deepcopy(fixture["publication"].support)
    bank = deepcopy(fixture["publication"].bank)
    refs = deepcopy(fixture["publication"].refs)
    refs["bank"]["path"] = str(b.contract.B_RUN / b.contract.FILES["bank"])
    refs["freeze"]["path"] = str(b.contract.B_RUN / b.contract.FILES["freeze"])
    refs.update({name: {"path": str(b.contract.B_RUN / f"synthetic-{name}.json"), "sha256": "d" * 64}
                 for name in ("source_authority", "plan", "support")})
    refs["model_producer"] = {"path": "D:/us-tech-quant/scripts/research/a2/risk/synthetic-never-opened-producer.py", "sha256": "d" * 64}
    failed = {"node_id": "synthetic-failed-node", "family": "LW", "status": "FAILED", "finite_check": False,
              "block_reason": "synthetic retained failure"}
    bank.update(qualification_ref=refs["qualification"], ledger_ref=refs["ledger"], new_fit_units=2,
                cumulative_fit_units=3029, account_attempts=0, test2026_rows_read=0,
                blocked_or_failed=[failed])
    ledger = {"status": "B_R5_FINITE_EVENT_RISK_QUEUE_COMPLETE", "new_fit_units": 2,
              "risk_fit_units": 2, "fit_attempts": 3029, "inherited_fit_units": 3027,
              "test2026_rows_read": 0, "account_paths": 0,
              "records": [*deepcopy(bank["states"]), deepcopy(failed)]}
    closure = {refs["model_producer"]["path"]: refs["model_producer"]["sha256"]}
    freeze = {"schema": "B_R5_SCIENCE_AND_EXECUTION_FREEZE_V1", "research_id": b.B_ID,
              "status": "FROZEN_BEFORE_NUMERIC", "test2026_reads": 0,
              "source_authority_ref": refs["source_authority"],
              "plan_ref": refs["plan"], "support_ref": refs["support"], "qualification_ref": refs["qualification"],
              "source_code_pins": [{"path": path, "sha256": digest} for path, digest in closure.items()]}
    qualification = {"schema": "B_R5_FINITE_EVENT_RISK_QUALIFICATION_V1", "research_id": b.B_ID,
                     "plan_ref": refs["plan"], "support_ref": refs["support"], "model_producer_ref": refs["model_producer"]}
    called = []
    def synthetic_chain(*args, **kwargs):
        called.append("source-only-chain")
        assert kwargs["pinned_refs"] == refs
        return deepcopy(fixture["publication"].continuity)
    monkeypatch.setattr(b.chain_owner, "qualify_chain", synthetic_chain)
    if case == "wrong_freeze": freeze["status"] = "STAGED"
    elif case == "failed_retention": bank["blocked_or_failed"] = []
    kwargs = {"refs": refs,
              "expected_content_sha256": {name: b.content_hash(value) for name, value in (("plan", plan), ("support", support), ("bank", bank))},
              "expected_code_pins": closure, "observed_code_pins": closure.copy()}
    if case == "valid":
        result = b.qualify_publication(plan, support, bank, freeze, qualification, ledger, **kwargs)
        assert type(result) is b.PublicationBinding and result.bank["blocked_or_failed"] == [failed]
        assert called == ["source-only-chain"] and result.continuity["real_numeric_reads"] == 0
    else:
        with pytest.raises(ValueError, match="SCIENCE_FREEZE_REQUIRED|ALL_FAILED_AND_BLOCKED_OWNER_RECORDS_MUST_REMAIN"):
            b.qualify_publication(plan, support, bank, freeze, qualification, ledger, **kwargs)
        assert called == []


def test_native_state_loader_rejects_nonpass_review_before_hash_or_joblib(monkeypatch):
    import sys
    from types import SimpleNamespace
    def forbidden(*args, **kwargs):
        raise AssertionError("Unreviewed native loader must not hash or load any artifact")
    monkeypatch.setattr(b, "sha", forbidden)
    monkeypatch.setitem(sys.modules, "joblib", SimpleNamespace(load=forbidden))
    with pytest.raises(ValueError, match="INDEPENDENT_EXACT_ADAPTER_REVIEW_REQUIRED"):
        b.load_qualified_state(None, None, source_review={"status": "BLOCKED", "research_id": b.contract.ID})



@pytest.mark.parametrize("collection", ["states", "blocked_or_failed", "records"])
@pytest.mark.parametrize("mapping", ["asset_uids", "asset_epochs"])
@pytest.mark.parametrize("identity", ["synthetic-MU-identity", None])
def test_reader_mu_identity_exception_accepts_only_exact_native_string_mapping(collection, mapping, identity):
    source = {collection: [{mapping: {"MU": identity, "SYN": "synthetic-other-identity"}}]}
    reader = b._MetadataJSON(StringIO(json.dumps(source)),
                             root_keys=b.LEDGER_KEYS if collection == "records" else b.BANK_KEYS,
                             record_collections=(collection,),
                             metadata_kind="ledger" if collection == "records" else "bank")
    assert reader.value() == source
    reader.space()
    assert reader.char == ""


@pytest.mark.parametrize("prefix,collections", [
    ('{"MU":', ()),
    ('{"mu":', ()),
    ('{"Mu":', ()),
    ('{"states":[{"MU":', ("states",)),
    ('{"states":[{"asset_uids":{"mu":', ("states",)),
    ('{"states":[{"source_receipt":{"asset_uids":{"MU":', ("states",)),
    ('{"states":[{"asset_uids":{"SYN":{"MU":', ("states",)),
    ('{"states":[{"asset_uids":[{"MU":', ("states",)),
    ('{"states":{"asset_uids":{"MU":', ("states",)),
    ('{"failures":[{"asset_epochs":{"MU":', ("records",)),
    ('{"records":[{"asset_epochs":{"MU":', ()),
])
def test_reader_mu_identity_exception_blocks_other_paths_before_value_access(prefix, collections):
    stream = BeforePayloadValue(prefix + 'FORBIDDEN_VALUE_MUST_NEVER_BE_READ', len(prefix))
    with pytest.raises(b.RiskBindingBlocked, match="PAYLOAD_FORBIDDEN"):
        b._MetadataJSON(stream, record_collections=collections,
                        metadata_kind="ledger" if collections == ("records",) else "bank" if collections == ("states",) else "other").value()
    assert stream.tell() == len(prefix)


@pytest.mark.parametrize("key", sorted(b.NUMERIC_FIELDS - {"mu"}))
def test_reader_mu_identity_exception_keeps_other_numeric_fields_blocked_before_value(key):
    prefix = '{"states":[{"asset_uids":{"' + key.upper() + '":'
    stream = BeforePayloadValue(prefix + 'FORBIDDEN_VALUE_MUST_NEVER_BE_READ}}]}', len(prefix))
    with pytest.raises(b.RiskBindingBlocked, match="PAYLOAD_FORBIDDEN"):
        b._MetadataJSON(stream, root_keys=b.BANK_KEYS, record_collections=("states",), metadata_kind="bank").value()
    assert stream.tell() == len(prefix)


@pytest.mark.parametrize("nonstring", ["[123456]", "123456", '{"hidden":123456}', "true"])
def test_reader_mu_identity_exception_rejects_nonstring_before_payload_body(nonstring):
    prefix = '{"records":[{"asset_epochs":{"MU":'
    # One structural lookahead determines the JSON type. No array member,
    # object key, remaining numeric token, or primitive body may be consumed.
    boundary = len(prefix) + 1
    stream = BeforePayloadValue(prefix + nonstring + '}}]}', boundary)
    with pytest.raises(b.RiskBindingBlocked):
        b._MetadataJSON(stream, root_keys=b.LEDGER_KEYS, record_collections=("records",), metadata_kind="ledger").value()
    assert stream.tell() <= boundary



# Exact producer metadata only. None retains an unknown UID/epoch; it conveys
# no risk qualification and never licenses numeric state or endpoint access.
_SYNTHETIC_C_COORDINATE = {
    "raw_transport_codes": ["SYNTHETIC_TRANSPORT"],
    "security_class_declaration": None, "security_id_type": None,
    "cusip": None, "mapping_status": None,
    "class_coordinate_status": "EXACT_FROZEN_INTERVAL_METADATA_DECLARATION",
    "strict_historical_authority": False,
}
_SYNTHETIC_F_SUPPORT = {"group": 48, "sic_source_sha256": "d" * 64, "available_at": AT}
_SYNTHETIC_SOURCE_REASONS = (
    "DECLARED_AVAILABLE_LABEL_ENDPOINT_METADATA_INVALID",
    "AMBIGUOUS_REQUIRED_SOURCE_LABEL_UID_KEYS",
    "WRONG_REQUIRED_STORED_LABEL_COORDINATE",
)
_SYNTHETIC_IDENTITY_REASONS = (
    "AMBIGUOUS_OR_MISSING_CURRENT_UID", "NONUNIQUE_CURRENT_UID", "UNKNOWN_CURRENT_UID",
)
_SYNTHETIC_SUPPORT_MU_LEAVES = (
    (("events", "*", "asset_uids"), "synthetic-UID-MU"),
    (("events", "*", "asset_epochs"), "synthetic-epoch-MU"),
    (("events", "*", "segment_starts"), "2025-12-19"),
    (("events", "*", "security_coordinates"), _SYNTHETIC_C_COORDINATE),
    (("events", "*", "qualified_ff48_support"), _SYNTHETIC_F_SUPPORT),
    (("events", "*", "history_support", "nominal_n"), 252),
    (("events", "*", "history_support", "source_metadata_blockers"), _SYNTHETIC_SOURCE_REASONS[0]),
    (("events", "*", "history_support", "current_identity_blockers"), _SYNTHETIC_IDENTITY_REASONS[0]),
    (("events", "*", "complete_structural_signature", "asset_uids"), "synthetic-UID-MU"),
    (("events", "*", "complete_structural_signature", "asset_epochs"), "synthetic-epoch-MU"),
    (("events", "*", "complete_structural_signature", "blocked_assets"), _SYNTHETIC_IDENTITY_REASONS[0]),
    (("events", "*", "complete_structural_signature", "security_coordinates"), _SYNTHETIC_C_COORDINATE),
    (("events", "*", "complete_structural_signature", "ff48_qualified_source_support"), _SYNTHETIC_F_SUPPORT),
    (("events", "*", "complete_structural_signature", "feature_source_support"), ["synthetic-feature-source"]),
)


def _synthetic_mu_leaf_document(path, value):
    node = {"MU": deepcopy(value)}
    for key in reversed(path):
        node = [node] if key == "*" else {key: node}
    return node


def _synthetic_support_mu_read(path, value, metadata_kind="support"):
    source = _synthetic_mu_leaf_document(path, value)
    reader = b._MetadataJSON(StringIO(json.dumps(source)), metadata_kind=metadata_kind)
    result = reader.value()
    reader.space()
    assert reader.char == ""
    return source, result


@pytest.mark.parametrize("path,value", _SYNTHETIC_SUPPORT_MU_LEAVES)
def test_reader_typed_mu_support_accepts_all14_exact_native_paths(path, value):
    assert len(_SYNTHETIC_SUPPORT_MU_LEAVES) == 14
    source, result = _synthetic_support_mu_read(path, value)
    assert result == source


@pytest.mark.parametrize("path", [
    ("events", "*", "asset_uids"), ("events", "*", "asset_epochs"),
    ("events", "*", "segment_starts"), ("events", "*", "qualified_ff48_support"),
    ("events", "*", "complete_structural_signature", "asset_uids"),
    ("events", "*", "complete_structural_signature", "asset_epochs"),
    ("events", "*", "complete_structural_signature", "ff48_qualified_source_support"),
])
def test_reader_typed_mu_support_retains_native_nullable_metadata(path):
    source, result = _synthetic_support_mu_read(path, None)
    assert result == source


@pytest.mark.parametrize("field,reason", [
    *(('source_metadata_blockers', reason) for reason in _SYNTHETIC_SOURCE_REASONS),
    *(('current_identity_blockers', reason) for reason in _SYNTHETIC_IDENTITY_REASONS),
])
def test_reader_typed_mu_support_accepts_exact_finite_reason_enums(field, reason):
    source, result = _synthetic_support_mu_read(("events", "*", "history_support", field), reason)
    assert result == source


@pytest.mark.parametrize("metadata_kind", [None, "bank", "ledger", "other"])
def test_reader_typed_mu_support_paths_do_not_expand_other_kinds(metadata_kind):
    prefix = '{"events":[{"asset_uids":{"MU":'
    stream = BeforePayloadValue(prefix + 'FORBIDDEN_VALUE_MUST_NEVER_BE_READ', len(prefix))
    with pytest.raises(b.RiskBindingBlocked, match="PAYLOAD_FORBIDDEN"):
        b._MetadataJSON(stream, metadata_kind=metadata_kind).value()
    assert stream.tell() == len(prefix)


@pytest.mark.parametrize("prefix", [
    '{"events":{"asset_uids":{"MU":',
    '{"events":[{"unknown":{"asset_uids":{"MU":',
    '{"events":[{"complete_structural_signature":{"unknown":{"asset_epochs":{"MU":',
    '{"events":[{"asset_uids":{"mu":',
    '{"events":[{"asset_uids":{"Mu":',
])
def test_reader_typed_mu_support_rejects_partial_deeper_and_case_alias_paths(prefix):
    stream = BeforePayloadValue(prefix + 'FORBIDDEN_VALUE_MUST_NEVER_BE_READ', len(prefix))
    with pytest.raises(b.RiskBindingBlocked, match="PAYLOAD_FORBIDDEN"):
        b._MetadataJSON(stream, metadata_kind="support").value()
    assert stream.tell() == len(prefix)


@pytest.mark.parametrize("path,value", [
    (("events", "*", "asset_uids"), []),
    (("events", "*", "asset_epochs"), True),
    (("events", "*", "segment_starts"), "2026-01-01"),
    (("events", "*", "segment_starts"), "2025-02-30"),
    (("events", "*", "segment_starts"), "2025-12-19T00:00:00+00:00"),
    (("events", "*", "history_support", "nominal_n"), True),
    (("events", "*", "history_support", "nominal_n"), -1),
    (("events", "*", "history_support", "nominal_n"), 253),
    (("events", "*", "history_support", "nominal_n"), 1.5),
    (("events", "*", "history_support", "source_metadata_blockers"), "UNKNOWN_REASON"),
    (("events", "*", "history_support", "current_identity_blockers"), _SYNTHETIC_SOURCE_REASONS[0]),
    (("events", "*", "complete_structural_signature", "blocked_assets"), None),
    (("events", "*", "complete_structural_signature", "feature_source_support"), [123456]),
    (("events", "*", "security_coordinates"), None),
    (("events", "*", "security_coordinates"), {key: value for key, value in _SYNTHETIC_C_COORDINATE.items() if key != "mapping_status"}),
    (("events", "*", "qualified_ff48_support"), {key: value for key, value in _SYNTHETIC_F_SUPPORT.items() if key != "available_at"}),
    (("events", "*", "security_coordinates"), {**_SYNTHETIC_C_COORDINATE, "strict_historical_authority": True}),
    (("events", "*", "security_coordinates"), {**_SYNTHETIC_C_COORDINATE, "class_coordinate_status": "UNKNOWN_CLASS"}),
    (("events", "*", "qualified_ff48_support"), {**_SYNTHETIC_F_SUPPORT, "group": True}),
    (("events", "*", "qualified_ff48_support"), {**_SYNTHETIC_F_SUPPORT, "group": 0}),
    (("events", "*", "qualified_ff48_support"), {**_SYNTHETIC_F_SUPPORT, "group": 49}),
    (("events", "*", "qualified_ff48_support"), {**_SYNTHETIC_F_SUPPORT, "sic_source_sha256": "not-a-hex-digest"}),
    (("events", "*", "qualified_ff48_support"), {**_SYNTHETIC_F_SUPPORT, "available_at": "2025-12-19T21:00:00"}),
    (("events", "*", "qualified_ff48_support"), {**_SYNTHETIC_F_SUPPORT, "available_at": "2026-01-01T00:00:00+00:00"}),
])
def test_reader_typed_mu_support_rejects_wrong_native_scalar_types_ranges_and_clocks(path, value):
    with pytest.raises(ValueError):
        _synthetic_support_mu_read(path, value)


@pytest.mark.parametrize("field,value", [
    ("security_coordinates", _SYNTHETIC_C_COORDINATE),
    ("qualified_ff48_support", _SYNTHETIC_F_SUPPORT),
])
def test_reader_typed_mu_support_unknown_coordinate_attribute_blocks_before_value(field, value):
    source = _synthetic_mu_leaf_document(("events", "*", field), {**value, "covariance_alias": 123456})
    text = json.dumps(source, separators=(",", ":"))
    token = '"covariance_alias":'
    boundary = text.index(token) + len(token)
    stream = BeforePayloadValue(text[:boundary] + 'FORBIDDEN_VALUE_MUST_NEVER_BE_READ', boundary)
    with pytest.raises(b.RiskBindingBlocked):
        b._MetadataJSON(stream, metadata_kind="support").value()
    assert stream.tell() == boundary


def test_reader_typed_mu_support_numeric_transport_code_blocks_before_token_body():
    coordinate = {**_SYNTHETIC_C_COORDINATE, "raw_transport_codes": [123456]}
    source = _synthetic_mu_leaf_document(("events", "*", "security_coordinates"), coordinate)
    text = json.dumps(source, separators=(",", ":"))
    number_start = text.index("123456")
    stream = BeforePayloadValue(text, number_start + 1)
    with pytest.raises(b.RiskBindingBlocked):
        b._MetadataJSON(stream, metadata_kind="support").value()
    assert stream.tell() <= number_start + 1


@pytest.mark.parametrize("metadata_kind", ["ledger", None, "bank", "support", "other"])
def test_reader_typed_mu_extra_ledger_identity_path_is_kind_scoped(metadata_kind):
    source = _synthetic_mu_leaf_document(("physical_events", "*", "context", "identity_epoch", "uids"), "synthetic-UID-MU")
    if metadata_kind == "ledger":
        reader = b._MetadataJSON(StringIO(json.dumps(source)), root_keys=b.LEDGER_KEYS, metadata_kind=metadata_kind)
        assert reader.value() == source
        reader.space()
        assert reader.char == ""
    else:
        prefix = '{"physical_events":[{"context":{"identity_epoch":{"uids":{"MU":'
        stream = BeforePayloadValue(prefix + 'FORBIDDEN_VALUE_MUST_NEVER_BE_READ', len(prefix))
        with pytest.raises(b.RiskBindingBlocked, match="PAYLOAD_FORBIDDEN"):
            b._MetadataJSON(stream, root_keys=b.LEDGER_KEYS, metadata_kind=metadata_kind).value()
        assert stream.tell() == len(prefix)


@pytest.mark.parametrize("nonstring", ["[123456]", "123456", "true", "null"])
def test_reader_typed_mu_extra_ledger_identity_rejects_nonstrings_before_payload_body(nonstring):
    prefix = '{"physical_events":[{"context":{"identity_epoch":{"uids":{"MU":'
    boundary = len(prefix) + 1
    stream = BeforePayloadValue(prefix + nonstring + '}}}}]}', boundary)
    with pytest.raises(b.RiskBindingBlocked):
        b._MetadataJSON(stream, root_keys=b.LEDGER_KEYS, metadata_kind="ledger").value()
    assert stream.tell() <= boundary



@pytest.mark.parametrize("path,value", [
    (("events", "*", "history_support", "nominal_n"), 0),
    (("events", "*", "qualified_ff48_support"), {**_SYNTHETIC_F_SUPPORT, "group": 1}),
    (("events", "*", "security_coordinates"), {
        **_SYNTHETIC_C_COORDINATE,
        "security_class_declaration": "synthetic declaration", "security_id_type": "synthetic id type",
        "cusip": "synthetic cusip", "mapping_status": "synthetic mapping status",
        "class_coordinate_status": "CLASS_COORDINATE_UNRESOLVED",
    }),
])
def test_reader_typed_mu_support_preserves_legal_boundaries_and_nullable_string_attributes(path, value):
    source, result = _synthetic_support_mu_read(path, value)
    assert result == source



def test_reader_typed_mu_without_explicit_metadata_kind_blocks_before_value():
    prefix = '{"states":[{"asset_uids":{"MU":'
    stream = BeforePayloadValue(prefix + 'FORBIDDEN_VALUE_MUST_NEVER_BE_READ', len(prefix))
    with pytest.raises(b.RiskBindingBlocked, match="PAYLOAD_FORBIDDEN"):
        b._MetadataJSON(stream, root_keys=b.BANK_KEYS, record_collections=("states",)).value()
    assert stream.tell() == len(prefix)


@pytest.mark.parametrize("prefix", [
    '{"events":[{"history_support":{"nominal_n":{"MU":',
    '{"events":[{"qualified_ff48_support":{"MU":{"group":',
])
@pytest.mark.parametrize("unicode_digits", ["\u0661\u0662\u0663", "\uff11\uff12\uff13"])
def test_reader_typed_mu_support_unicode_integer_blocks_before_token_body(prefix, unicode_digits):
    # The type lookahead may inspect the first character, but the remaining
    # token must never be consumed: native metadata integers use ASCII digits.
    boundary = len(prefix) + 1
    stream = BeforePayloadValue(prefix + unicode_digits + '}}}]}', boundary)
    with pytest.raises(b.RiskBindingBlocked):
        b._MetadataJSON(stream, metadata_kind="support").value()
    assert stream.tell() <= boundary



@pytest.fixture(scope="module")
def original_chain_source_only_template():
    # Reuse the existing complete synthetic owner fixture, never a published
    # plan/bank, and never copy its business qualification implementation.
    import importlib.util
    source_path = b.Path(__file__).resolve().parents[1] / "inference" / "test_joint_event_risk_chain_r5.py"
    spec = importlib.util.spec_from_file_location("c14_original_r5_chain_synthetic_fixture", source_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.fixture()


@pytest.fixture
def original_chain_rm_fixture(original_chain_source_only_template, monkeypatch):
    from scripts.research.a2.risk import event_risk_contract_r5 as event
    plan, support, bank, refs, codes = deepcopy(original_chain_source_only_template)
    assert tuple(plan["risk_families"]) == tuple(event.FAMILIES) and len(event.FAMILIES) == 16
    assert len(plan["nodes"]) == 55 and len(support["daily_support_chain"]) == 752
    # Local synthetic custody only; source pins stay the real immutable owner
    # and contract .py pins. No scientific native16 binding/proof is changed.
    synthetic_root = b.Path("D:/synthetic/R5")
    refs["plan"]["path"] = str(synthetic_root / "R5_FINITE_EVENT_RISK_PLAN.json")
    monkeypatch.setattr(b.contract, "B_RUN", synthetic_root)
    monkeypatch.setattr(b, "R5_PLAN_SHA", refs["plan"]["sha256"])
    sentinel = deepcopy(b.RM_UNBOUND_BINDING)
    sentinel["producer_sha256"] = refs["model_producer"]["sha256"]
    monkeypatch.setattr(b, "RM_UNBOUND_BINDING", sentinel)
    codes.update({str(b.Path(b.chain_owner.__file__).resolve()): b.CHAIN_OWNER_SHA,
                  str(b.Path(event.__file__).resolve()): b.EVENT_CONTRACT_SHA})
    original_open = b.Path.open
    source_opens = []
    def only_static_source_open(path, *args, **kwargs):
        assert path.suffix == ".py", "Synthetic qualification must never open JSON, model or data artifacts"
        source_opens.append(str(path))
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(b.Path, "open", only_static_source_open)
    return {"plan": plan, "support": support, "bank": bank, "refs": refs, "codes": codes,
            "event": event, "source_opens": source_opens}


def _original_chain_kwargs(fixture):
    return {"pinned_refs": fixture["refs"],
            "expected_content_sha256": {name: b.content_hash(fixture[name]) for name in ("plan", "support", "bank")},
            "expected_code_pins": fixture["codes"].copy(), "observed_code_pins": fixture["codes"].copy()}


def _declare_only_unbound_rm(fixture):
    plan = fixture["plan"]
    native = deepcopy(plan["method_bindings"])
    plan["method_bindings"].append(deepcopy(b.RM_UNBOUND_BINDING))
    plan["unbound_parent_RM_role_is_not_additional_research_family"] = True
    plan["RM_new_fit_units"] = 0
    assert plan["method_bindings"][:-1] == native
    assert fixture["bank"]["method_bindings"] == plan["method_bindings"]


def test_original_r5_rm_roster_uses_same_kernel_inputs_globals_and_all17_reports(original_chain_rm_fixture, monkeypatch):
    fixture = original_chain_rm_fixture
    _declare_only_unbound_rm(fixture)
    kwargs = _original_chain_kwargs(fixture)
    before = deepcopy((fixture["plan"], fixture["support"], fixture["bank"], kwargs))
    owner = b.chain_owner.qualify_chain
    owner_globals = dict(owner.__globals__)
    binder = fixture["event"].bind_pinned_kernel
    bound = []
    def observe_binding(function, **options):
        assert function is owner
        assert set(options["dependencies"]) == {"_need"}
        clone = binder(function, **options)
        assert clone.__code__ is owner.__code__
        assert clone.__globals__["_need"] is not owner.__globals__["_need"]
        assert all(clone.__globals__[key] is value for key, value in owner_globals.items() if key != "_need")
        bound.append(clone)
        return clone
    monkeypatch.setattr(fixture["event"], "bind_pinned_kernel", observe_binding)
    result = b.qualify_original_r5_chain(fixture["plan"], fixture["support"], fixture["bank"], **kwargs)
    assert len(bound) == 1
    assert (fixture["plan"], fixture["support"], fixture["bank"], kwargs) == before
    assert set(owner.__globals__) == set(owner_globals)
    assert all(owner.__globals__[key] is value for key, value in owner_globals.items())
    assert set(result["family_continuity"]) == set(fixture["event"].FAMILIES) | {"MULTI_HORIZON"}
    assert result["family_continuity"]["MULTI_HORIZON"] == {
        "scope": "UNBOUND_SOURCE", "continuous_chain": False, "qualified_days": 0,
        "first_input_blocker": {"reason": "RM_3_10_20_HORIZON_SOURCE_UNBOUND"},
    }
    assert result["daily_domain_count"] == 752 and result["all_seven_continuous"] is True
    assert len(result["retained_blocked_or_failed"]) == len(fixture["bank"]["blocked_or_failed"])
    assert result["source_only_qualification"] is True and result["strict_PIT_promotion_eligible"] is False
    assert result["real_numeric_reads"] == result["new_fit_units"] == result["account_attempts"] == result["test2026_rows_read"] == 0
    correction = result["metadata_compatibility_correction"]
    assert correction["corrected_reason"] == "ALL_FROZEN_FAMILIES_MUST_REMAIN_IN_REPORT"
    assert correction["original_kernel_code_reused"] is True
    assert correction["original_module_and_helper_globals_unchanged"] is True
    assert correction["original_input_metadata_unchanged"] is True
    assert correction["RM_new_fit_units"] == 0 and correction["RM_numeric_admission"] is False
    assert fixture["source_opens"] and all(path.endswith(".py") for path in fixture["source_opens"])


def test_original_r5_rm_roster_without_extra_binding_calls_unchanged_owner(original_chain_rm_fixture, monkeypatch):
    fixture = original_chain_rm_fixture
    kwargs = _original_chain_kwargs(fixture)
    owner = b.chain_owner.qualify_chain
    before = deepcopy((fixture["plan"], fixture["support"], fixture["bank"], kwargs))
    expected = owner(fixture["plan"], fixture["support"], fixture["bank"], **kwargs)
    def forbidden(*args, **kwargs):
        raise AssertionError("A native16 roster must not invoke the compatibility binder")
    monkeypatch.setattr(fixture["event"], "bind_pinned_kernel", forbidden)
    actual = b.qualify_original_r5_chain(fixture["plan"], fixture["support"], fixture["bank"], **kwargs)
    assert actual == expected and "metadata_compatibility_correction" not in actual
    assert (fixture["plan"], fixture["support"], fixture["bank"], kwargs) == before


@pytest.mark.parametrize("defect,reason", [
    ("extra", "ONLY_EXPLICIT_UNBOUND_RM_ROSTER_SENTINEL_ALLOWED"),
    ("missing_binding", "ONLY_EXPLICIT_UNBOUND_RM_ROSTER_SENTINEL_ALLOWED"),
    ("RM_ready", "EXACT_LITERAL_BLOCKED_RM_BINDING_REQUIRED"),
    ("RM_node", "EXACT16_NODE_AND_RECIPE_FAMILIES_NO_RM_REQUIRED"),
    ("RM_recipe", "EXACT16_NODE_AND_RECIPE_FAMILIES_NO_RM_REQUIRED"),
    ("flag_false", "RM_NOT_A_RESEARCH_FAMILY_AND_ZERO_FIT_UNITS_REQUIRED"),
    ("units_nonzero", "RM_NOT_A_RESEARCH_FAMILY_AND_ZERO_FIT_UNITS_REQUIRED"),
    ("units_bool", "RM_NOT_A_RESEARCH_FAMILY_AND_ZERO_FIT_UNITS_REQUIRED"),
    ("changed_RM_recipe", "EXACT_LITERAL_BLOCKED_RM_BINDING_REQUIRED"),
    ("changed_RM_producer", "EXACT_LITERAL_BLOCKED_RM_BINDING_REQUIRED"),
    ("producer_ref", "EXACT_LITERAL_BLOCKED_RM_BINDING_REQUIRED"),
    ("RM_bank_record", "NO_RM_OR_UNKNOWN_BANK_STATE_ALLOWED"),
])
def test_original_r5_rm_roster_rejects_any_scientific_scope_or_binding_change(original_chain_rm_fixture, defect, reason):
    fixture = original_chain_rm_fixture
    _declare_only_unbound_rm(fixture)
    plan, bank = fixture["plan"], fixture["bank"]
    sentinel = plan["method_bindings"][-1]
    if defect == "extra": plan["method_bindings"].append({**sentinel, "family": "SYNTHETIC_UNKNOWN_EXTRA"})
    elif defect == "missing_binding":
        plan["method_bindings"] = [binding for binding in plan["method_bindings"] if binding["family"] != "LW"]
        bank["method_bindings"] = plan["method_bindings"]
    elif defect == "RM_ready": sentinel["availability"] = "READY"
    elif defect == "RM_node":
        plan["nodes"][0]["families"].append("MULTI_HORIZON")
        plan["nodes"][0]["family_dependencies"]["MULTI_HORIZON"] = "PRIMARY"
    elif defect == "RM_recipe": next(iter(plan["estimator_recipes"].values()))["method_ids"]["MULTI_HORIZON"] = sentinel["method"]
    elif defect == "flag_false": plan["unbound_parent_RM_role_is_not_additional_research_family"] = False
    elif defect == "units_nonzero": plan["RM_new_fit_units"] = 1
    elif defect == "units_bool": plan["RM_new_fit_units"] = False
    elif defect == "changed_RM_recipe": sentinel["recipe_sha256"] = "0" * 64
    elif defect == "changed_RM_producer": sentinel["producer_sha256"] = "0" * 64
    elif defect == "producer_ref": fixture["refs"]["model_producer"]["sha256"] = "0" * 64
    else: bank["states"].append({**deepcopy(bank["states"][0]), "family": "MULTI_HORIZON"})
    kwargs = _original_chain_kwargs(fixture)
    before = deepcopy((plan, fixture["support"], bank, kwargs))
    with pytest.raises(ValueError, match=reason):
        b.qualify_original_r5_chain(plan, fixture["support"], bank, **kwargs)
    assert (plan, fixture["support"], bank, kwargs) == before


@pytest.mark.parametrize("defect", ["plan_ref", "owner_pin", "contract_pin", "owner_physical_hash", "contract_physical_hash", "content_hash"])
def test_original_r5_rm_roster_rejects_changed_source_and_content_pins(original_chain_rm_fixture, monkeypatch, defect):
    fixture = original_chain_rm_fixture
    _declare_only_unbound_rm(fixture)
    kwargs = _original_chain_kwargs(fixture)
    owner_path = b.Path(b.chain_owner.__file__).resolve()
    contract_path = b.Path(fixture["event"].__file__).resolve()
    if defect == "plan_ref": fixture["refs"]["plan"]["sha256"] = "0" * 64
    elif defect == "owner_pin": kwargs["expected_code_pins"][str(owner_path)] = "0" * 64
    elif defect == "contract_pin": kwargs["observed_code_pins"][str(contract_path)] = "0" * 64
    elif defect in ("owner_physical_hash", "contract_physical_hash"):
        bad_path = owner_path if defect == "owner_physical_hash" else contract_path
        physical_sha = b.sha
        monkeypatch.setattr(b, "sha", lambda path: "0" * 64 if b.Path(path).resolve() == bad_path else physical_sha(path))
    else: kwargs["expected_content_sha256"]["bank"] = "0" * 64
    with pytest.raises(ValueError, match="ROSTER_PLAN_PIN_REQUIRED|ROSTER_KERNEL_CLOSURE_REQUIRED|FROZEN_METADATA_CONTENT_CHANGED"):
        b.qualify_original_r5_chain(fixture["plan"], fixture["support"], fixture["bank"], **kwargs)


def test_original_r5_rm_roster_changed_owner_function_blocks_before_execution(original_chain_rm_fixture, monkeypatch):
    fixture = original_chain_rm_fixture
    _declare_only_unbound_rm(fixture)
    kwargs = _original_chain_kwargs(fixture)
    def forbidden(*args, **kwargs):
        raise AssertionError("A replacement owner function must never execute")
    monkeypatch.setattr(b.chain_owner, "qualify_chain", forbidden)
    with pytest.raises(ValueError, match="KERNEL_FUNCTION_SOURCE_PATH_MISMATCH"):
        b.qualify_original_r5_chain(fixture["plan"], fixture["support"], fixture["bank"], **kwargs)


def test_original_r5_rm_roster_injects_only_need_and_keeps_unrelated_false_guard(original_chain_rm_fixture, monkeypatch):
    fixture = original_chain_rm_fixture
    _declare_only_unbound_rm(fixture)
    kwargs = _original_chain_kwargs(fixture)
    owner = b.chain_owner.qualify_chain
    original_globals = dict(owner.__globals__)
    binder = fixture["event"].bind_pinned_kernel
    def probe_other_guard(function, **options):
        assert function is owner and set(options["dependencies"]) == {"_need"}
        kernel = binder(function, **options)
        kernel.__globals__["_need"](False, "SYNTHETIC_UNRELATED_NEED_MUST_REMAIN_BLOCKED")
        raise AssertionError("An unrelated false guard was bypassed")
    monkeypatch.setattr(fixture["event"], "bind_pinned_kernel", probe_other_guard)
    with pytest.raises(b.chain_owner.ChainQualificationBlocked, match="SYNTHETIC_UNRELATED_NEED_MUST_REMAIN_BLOCKED"):
        b.qualify_original_r5_chain(fixture["plan"], fixture["support"], fixture["bank"], **kwargs)
    assert set(owner.__globals__) == set(original_globals)
    assert all(owner.__globals__[key] is value for key, value in original_globals.items())



def test_original_r5_rm_roster_exact_assertion_can_be_corrected_only_once(original_chain_rm_fixture, monkeypatch):
    fixture = original_chain_rm_fixture
    _declare_only_unbound_rm(fixture)
    kwargs = _original_chain_kwargs(fixture)
    owner = b.chain_owner.qualify_chain
    original_globals = dict(owner.__globals__)
    before = deepcopy((fixture["plan"], fixture["support"], fixture["bank"], kwargs))
    binder = fixture["event"].bind_pinned_kernel
    bound = []
    def probe_repeated_legal_reason(function, **options):
        assert function is owner and set(options["dependencies"]) == {"_need"}
        kernel = binder(function, **options)
        assert kernel.__code__ is owner.__code__
        bound.append(kernel)
        guard = kernel.__globals__["_need"]
        assert guard is not owner.__globals__["_need"]
        guard(False, "ALL_FROZEN_FAMILIES_MUST_REMAIN_IN_REPORT")
        guard(False, "ALL_FROZEN_FAMILIES_MUST_REMAIN_IN_REPORT")
        raise AssertionError("A second correction of the same legal reason was allowed")
    monkeypatch.setattr(fixture["event"], "bind_pinned_kernel", probe_repeated_legal_reason)
    with pytest.raises(b.RiskBindingBlocked, match="ONLY_ONE_RM_ROSTER_ASSERTION_CORRECTION_ALLOWED"):
        b.qualify_original_r5_chain(fixture["plan"], fixture["support"], fixture["bank"], **kwargs)
    assert len(bound) == 1
    assert (fixture["plan"], fixture["support"], fixture["bank"], kwargs) == before
    assert set(owner.__globals__) == set(original_globals)
    assert all(owner.__globals__[key] is value for key, value in original_globals.items())
    assert all(bound[0].__globals__[key] is value for key, value in original_globals.items() if key != "_need")


def namespaced_numeric_fixture(role='C14_RX_HGB_LW', family='LW'):
    from pathlib import Path
    meta,payload,_=numeric_fixture(role,family)
    assets=meta.current['assets']; native={a:f'{i:09d}' for i,a in enumerate(assets)}
    from scripts.research.a2.data import selector_shared_risk_consumer as owner
    current={**deepcopy(meta.current),'asset_uids':native,
             'consumer_uids':{a:owner.namespace(native[a]) for a in assets},
             'consumer_namespace_owner_ref':dict(path=str(Path(owner.__file__).resolve()),
                 sha256='71a57696ba1596ee03c17939d561b75cfcd9870969aadc32991fc4e0dbf79fd3')}
    header={**deepcopy(meta.header),'asset_uids':deepcopy(native)}
    meta=replace(meta,current=current,header=header);payload['uids']=deepcopy(native)
    return meta,payload,[current['consumer_uids'][a] for a in assets[:40]]


def test_frozen_namespace_transport_keeps_native_payload_and_same_numeric_indices():
    meta,payload,raw=namespaced_numeric_fixture()
    before=deepcopy(payload['uids']);cov,indices=b._numeric_input(meta,payload,raw)
    assert indices==list(range(40)) and payload['uids']==before
    assert b.hybrid_coordinates(meta,payload,raw).shape==(44,2)


@pytest.mark.parametrize('case',['wrong_mapping','missing_asset','wrong_owner','bad_native','double_prefix','wrong_raw'])
def test_namespace_transport_fails_closed_without_new_identity_bridge(case):
    meta,payload,raw=namespaced_numeric_fixture(); current=deepcopy(meta.current)
    if case=='wrong_mapping':current['consumer_uids'][current['assets'][0]]='CUSIP:999999999'
    elif case=='missing_asset':current['consumer_uids'].pop(current['assets'][-1])
    elif case=='wrong_owner':current['consumer_namespace_owner_ref']['sha256']='f'*64
    elif case=='bad_native':current['asset_uids'][current['assets'][0]]='unknown'
    elif case=='double_prefix':current['asset_uids'][current['assets'][0]]=raw[0]
    elif case=='wrong_raw':raw[0]='CUSIP:999999999'
    if case in ('bad_native','double_prefix'):payload['uids']=deepcopy(current['asset_uids'])
    meta=replace(meta,current=current)
    with pytest.raises(ValueError):b._numeric_input(meta,payload,raw)


def test_frozen_namespace_veto_maps_proposal_only_and_never_rematches():
    meta,payload,raw=namespaced_numeric_fixture('C14_G1','LW')
    out=veto(meta,payload,raw,raw[:20]);assert out['chosen_uids']==raw[:20]
    assert out['extra_solves']==0 and out['rematching'] is False



@pytest.fixture
def bound_native_coordinate_publication(native_publication, monkeypatch):
    """Use the real current binder and projector over only synthetic metadata."""
    from scripts.research.a2.data import selector_maximal_risk_current as current_owner
    fixture = native_publication
    assets = fixture['current']['assets']
    uids = {asset: f'{index:09d}' for index, asset in enumerate(assets)}
    pool = dict(assets=list(assets), asset_uids=uids,
                asset_epochs=deepcopy(fixture['current']['asset_epochs']),
                segment_starts={asset: '2022-12-27' for asset in assets}, blocked_assets={})
    day = pd.Timestamp(DATES[-1]); at = current_owner._clock(day)
    signature = dict(ordered_assets=list(assets), asset_uids=deepcopy(uids),
                     asset_epochs=deepcopy(pool['asset_epochs']))
    event = dict(event_id='synthetic-current-event', decision_asof=at.isoformat(),
                 requested_assets=list(assets), asset_uids=deepcopy(uids),
                 asset_epochs=deepcopy(pool['asset_epochs']), segment_starts=deepcopy(pool['segment_starts']),
                 complete_structural_signature=signature, structural_signature_sha256=b.content_hash(signature),
                 dependency_local_event_ids={'PRIMARY': 'synthetic-primary-event'},
                 dependency_local_signature_sha256={'PRIMARY': 'a' * 64})
    raw = pd.DataFrame([dict(signal_date=day, ticker=asset, security_uid='CUSIP:' + uids[asset],
                             U_t_fingerprint='synthetic-full-U44', raw_rank=rank)
                        for rank, asset in enumerate(reversed(assets), start=1)], columns=current_owner.RAW_META)
    current = current_owner.bind_current(raw, pool, event, at, {'identity': 'b' * 64})
    publication = fixture['publication']; bank = deepcopy(publication.bank)
    native = bank['states'][0]
    for field in ('assets', 'asset_uids', 'asset_epochs', 'security_coordinate', 'source_support_identity'):
        native[field] = deepcopy(current[field])
    native['source_receipt']['return_coordinate'] = current['security_coordinate']
    native['event_policy_binding']['structural_identity'] = structural_identity(
        assets=tuple(assets), uids=current['asset_uids'], epochs=current['asset_epochs'],
        security_coordinate=current['security_coordinate'], source_support_identity=current['source_support_identity'])
    publication = replace(publication, bank=bank)
    calls = []; owner = b.bind_role_metadata
    def checked(*args, **kwargs):
        calls.append((args, deepcopy(kwargs)))
        return owner(*args, **kwargs)
    monkeypatch.setattr(b, 'bind_role_metadata', checked)
    return dict(fixture, publication=publication, current=current, decision_asof=at.isoformat(), binding_calls=calls)


def test_current_to_projector_to_header_keeps_native_risk_coordinate_and_original_gates(bound_native_coordinate_publication):
    from scripts.research.a2.risk.shared_risk_engine_r2 import COORDINATE
    from scripts.research.a2.data.shared_risk_inputs_r3 import STORED_LABEL_COORDINATE
    fixture = bound_native_coordinate_publication
    result = native_project(fixture)
    assert len(fixture['binding_calls']) == 1
    assert result.current['security_coordinate'] == result.header['security_coordinate'] == COORDINATE
    assert COORDINATE == 'shareholder_value_open_return' and COORDINATE != STORED_LABEL_COORDINATE
    assert len(result.current['assets']) == 44 and len(result.coverage_dates) == 752
    assert result.current['numeric_read_authority'] is False
    assert result.header['strict_PIT_promotion_eligible'] is False
    assert result.header['available_at_basis'] == 'FROZEN_EVENT_CLOSE_REPLAY_ASSUMPTION'
    assert result.header['source_available_at'] <= result.header['cutoff'] < result.header['as_of']
    assert result.header['structural_identity'] == fixture['publication'].bank['states'][0]['event_policy_binding']['structural_identity']
    result.verify()


@pytest.mark.parametrize('mutation,reason', [
    ('stored_label_marker', 'ORIGINAL_MECHANISM_SOURCE_TIME_ONLY'),
    ('wrong_coordinate', 'ORIGINAL_MECHANISM_SOURCE_TIME_ONLY'),
    ('missing_coordinate', 'ORIGINAL_MECHANISM_SOURCE_TIME_ONLY'),
    ('wrong_assumption', 'ORIGINAL_MECHANISM_SOURCE_TIME_ONLY'),
    ('missing_assumption', 'ORIGINAL_MECHANISM_SOURCE_TIME_ONLY'),
    ('numeric_assumption', 'ORIGINAL_MECHANISM_SOURCE_TIME_ONLY'),
    ('wrong_strict_pit', 'ORIGINAL_MECHANISM_SOURCE_TIME_ONLY'),
    ('missing_strict_pit', 'ORIGINAL_MECHANISM_SOURCE_TIME_ONLY'),
    ('numeric_strict_pit', 'ORIGINAL_MECHANISM_SOURCE_TIME_ONLY'),
    ('late_source_clock', 'NATIVE_SOURCE_CLOCK_AND_EVENT_REPLAY_BOUNDARY'),
    ('future_source_clock', 'PRE2026')])
def test_current_coordinate_integration_never_relaxes_receipt_flags_or_clock(bound_native_coordinate_publication, mutation, reason):
    from scripts.research.a2.data.shared_risk_inputs_r3 import STORED_LABEL_COORDINATE
    fixture = bound_native_coordinate_publication
    publication = fixture['publication']; bank = deepcopy(publication.bank)
    native = bank['states'][0]; receipt = native['source_receipt']
    if mutation == 'stored_label_marker': receipt['return_coordinate'] = STORED_LABEL_COORDINATE
    elif mutation == 'wrong_coordinate': receipt['return_coordinate'] = 'synthetic-wrong-coordinate'
    elif mutation == 'missing_coordinate': receipt.pop('return_coordinate')
    elif mutation == 'wrong_assumption': receipt['observation_time_assumed'] = False
    elif mutation == 'missing_assumption': receipt.pop('observation_time_assumed')
    elif mutation == 'numeric_assumption': receipt['observation_time_assumed'] = 1
    elif mutation == 'wrong_strict_pit': receipt['strict_PIT_promotion_eligible'] = True
    elif mutation == 'missing_strict_pit': receipt.pop('strict_PIT_promotion_eligible')
    elif mutation == 'numeric_strict_pit': receipt['strict_PIT_promotion_eligible'] = 0
    elif mutation == 'late_source_clock': receipt['available_at'] = native['as_of']
    elif mutation == 'future_source_clock': receipt['available_at'] = '2026-01-01T21:00:00+00:00'
    with pytest.raises(ValueError, match=reason):
        native_project(fixture, replace(publication, bank=bank))
    assert not fixture['binding_calls']
