import copy
import pytest

from scripts.research.a2.risk.shared_risk_budget_r2 import StateBudget, StateCache
from scripts.research.a2.risk.shared_risk_manifest_r2 import (
    MEMBERS, RISKS, SENSITIVITY, build_package, verify_manifest,
)


def design():
    combinations = [
        ("RAW_RANK", "NONE", "RAW_FIXED_SCORE", "RAW_ACTION", "RAW_FROZEN"),
        ("RAW_RANK", "NONE", "SIMPLE_EQUAL", "SIMPLE_ACTION", "G0"),
        ("P0", "R0", "Q0", "A0", "G0"), ("P1", "R0", "Q0", "A0", "G0"),
        ("P2", "R0", "Q0", "A0", "G0"),
        *[("P0", risk, "Q0", "A0", "G0") for risk in RISKS[1:]],
        ("P0", "R0", "Q1", "A0", "G0"), ("P0", "R0", "Q2", "A0", "G0"),
        ("P0", "R0", "Q0", "A1", "G0"), ("P0", "R0", "Q0", "A2", "G0"),
        ("P0", "R0", "Q0", "A0", "G1"), ("P0", "R0", "Q0", "A0", "G2"),
        ("P0", "R0", "Q3", "A0", "G0"), ("P1", "RU", "Q0", "A0", "G0"),
        ("P2", "RE", "Q0", "A0", "G0"), ("P0", "RH", "Q1", "A0", "G0"),
        ("P0", "RT", "Q2", "A0", "G0"), ("P0", "RD", "Q0", "A1", "G0"),
        ("P0", "RR", "Q0", "A0", "G1"), ("P0", "RB", "Q0", "A0", "G2"),
        ("P0", "RU", "Q0", "A2", "G0"), ("P0", "RM", "Q0", "A0", "G1"),
        ("P0", "RU", "Q3", "A0", "G0"), ("P0", "RT", "Q0", "A1", "G0"),
        ("P2", "R0", "Q0", "A0", "G2"),
    ]
    roles = [dict(id=f"B_R_{i:02d}", prediction=p, risk=r, optimizer=q,
                  action=a, gross=g, cost_bps=10, configs=1)
             for i, (p, r, q, a, g) in enumerate(combinations)]
    return dict(design_id="FROZEN_SYNTHETIC_DESIGN", primary_specs=roles,
                frozen=True, freeze_allows_outcome_tuning=False,
                prediction={"P2": {"declared_members": list(MEMBERS)}},
                future_conditional_account_budget={"sensitivity_spec_ids": list(SENSITIVITY)})


def traces():
    # Same complete physical recipe is deliberately shared across directions;
    # tests prove graph de-duplication, not these directions' scientific methods.
    b = StateBudget()
    c = StateCache(b, source_identity="SYNTHETIC", cutoff="2025-01-01T00:00:00+00:00",
                   assets=("UID:A",), return_coordinate="absolute5d", horizon=5,
                   identity_epoch="epoch1")
    c.learn("covariance", "shared_lw", [1], lambda:
            c.learn("scaler", "mean", [1], lambda: [2]))
    return {risk: b.snapshot() for risk in RISKS}


def test_32_main_16_predeclared_sensitivity_and_real_execution_zero():
    package = build_package(design(), direction_traces=traces())
    manifest = package["manifest"]
    assert len(manifest["main"]) == 32
    assert len(manifest["sensitivity"]) == 16
    assert {r["id"] for r in manifest["sensitivity"]} == set(SENSITIVITY)
    assert {r["cost_bps"] for r in manifest["sensitivity"]} == {5, 20}
    assert package["dag"]["current_executed_accounts"] == 0
    assert all(not n["executes"] for n in package["dag"]["nodes"])
    assert len(package["dag"]["main_roots"]) == 32
    accounts = [n for n in package["dag"]["nodes"] if n["kind"] == "account_replay"]
    assert all(n["selection_eligible"] is False for n in accounts)
    assert sum(n["selection_role_eligible"] for n in accounts) == 32


def test_exact_reuse_is_one_per_month_not_32_times_every_state():
    package = build_package(design(), direction_traces=traces())
    counts = package["budget"]["planning_recipe_counts"]
    assert counts["covariance"] == 36
    assert counts["scaler"] == 36
    assert package["budget"]["account_plans"] == 48
    assert package["budget"]["min"]["incremental_physical_learned_counts"]["covariance"] == 0
    assert "N_new_model_and_OOF_states" in package["budget"]["hard_upper"]["per_kind"]["model_fit"]


def test_topological_edges_exist_and_per_role_fit_dependencies_are_explicit():
    dag = build_package(design(), direction_traces=traces())
    done = set()
    for node in dag["dag"]["nodes"]:
        assert set(node["dependencies"]) <= done
        done.add(node["id"])
    nodes = {n["id"]: n for n in dag["dag"]["nodes"]}
    for role in dag["manifest"]["main"] + dag["manifest"]["sensitivity"]:
        action = nodes[role["action_dependency"]]
        assert role["gross_dependency"] in action["dependencies"]
        assert action["control_stage"] == "POST_G_TARGET_WEIGHTS_CONTROL"
        if role["action"] == "A2":
            gate = nodes[role["q_dependency"]]["preallocation_gate"]
            assert gate["stage"] == "BEFORE_ALLOCATION"
            assert set(gate["dependencies"]) == {
                role["account_context_dependency"], role["prediction_dependency"],
                role["risk_dependency"]}
    anchor = dag["manifest"]["main"][2]
    assert len([k for k in anchor["fit_dependencies"] if k.startswith("risk_physical:")]) == 6
    assert len([k for k in anchor["fit_dependencies"] if k.startswith("alpha_model_plan:")]) == 3
    assert anchor["unbound_fit_dependencies"]
    assert not dag["manifest"]["main"][0]["fit_dependencies"]


def test_cost_sensitivity_policy_templates_bind_each_account_and_only_learned_state_shares():
    package = build_package(design(), direction_traces=traces())
    manifest = package["manifest"]
    anchor = manifest["main"][2]
    changed_cost = next(r for r in manifest["sensitivity"] if r["id"] == "B_R_02")
    assert anchor["prediction_dependency"] == changed_cost["prediction_dependency"]
    assert anchor["risk_dependency"] == changed_cost["risk_dependency"]
    assert anchor["q_dependency"] != changed_cost["q_dependency"]
    assert anchor["action_dependency"] != changed_cost["action_dependency"]
    assert anchor["gross_dependency"] != changed_cost["gross_dependency"]
    assert anchor["account_context_dependency"] != changed_cost["account_context_dependency"]
    assert anchor["reusable_state"] == [anchor["prediction_dependency"], anchor["risk_dependency"]]
    policy = [n for n in package["dag"]["nodes"] if n.get("template_only")]
    assert len(policy) == 144
    assert all(n["exact_reuse_proven"] is False for n in policy)
    assert package["budget"]["policy_transform_templates"] == 144
    assert "sum_account(3*N_qualified_decisions(account))" in package["budget"]["expected"]["per_kind"]["deterministic_transform"]
    assert "144*N_qualified_decisions_max" in package["budget"]["hard_upper"]["per_kind"]["deterministic_transform"]


def test_missing_traces_unknown_not_zero_or_false_exact_claim():
    package = build_package(design())
    assert package["dag"]["recipe_status"] == "UNKNOWN_INCOMPLETE"
    assert package["budget"]["planning_recipe_counts"] == "UNKNOWN_INCOMPLETE_SYNTHETIC_RECIPE"
    assert set(package["budget"]["missing_direction_traces"]) == set(RISKS)


def test_immutable_payload_verification_and_deterministic_build():
    a = build_package(design(), direction_traces=traces())
    b = build_package(design(), direction_traces=traces())
    assert a == b
    for artifact in a.values():
        assert verify_manifest(artifact)
    mutated = copy.deepcopy(a["manifest"])
    mutated["main"][0]["cost_bps"] = 20
    with pytest.raises(ValueError, match="CHANGED"):
        verify_manifest(mutated)


def test_source_requirements_fixed_family_no_support_discovery_and_missing_blocks():
    requirements = build_package(design())["source_requirements"]
    assert requirements["activation_status"] == "NOT_ACTIVATED"
    assert requirements["real_support_discovered"] is False
    assert "qqq" in requirements["roles"]["B_R_07"]
    assert "pit_ff48" in requirements["roles"]["B_R_08"]
    assert "horizon_3_5_10_20_maturity" in requirements["roles"]["B_R_06"]
    assert "real_mature_5d_scenarios" in requirements["roles"]["B_R_23"]
    assert "frozen_calibrated_genuine_oof" in requirements["roles"]["B_R_04"]


def test_trace_closure_failure_real_trace_failure_and_expansion_are_rejected():
    t = traces()
    t["R0"]["events"][0]["dependencies"] = ["missing"]
    with pytest.raises(ValueError, match="CLOSURE"):
        build_package(design(), direction_traces=t)
    t = traces()
    t["R0"]["events"][0]["synthetic"] = False
    with pytest.raises(ValueError, match="SYNTHETIC"):
        build_package(design(), direction_traces=t)
    d = design()
    d["primary_specs"].append(d["primary_specs"][-1])
    with pytest.raises(ValueError, match="32_ROLE"):
        build_package(d)


def test_p2_prior_equal_rms_is_explicit_single_learned_state_each_comparison_year():
    package = build_package(design(), direction_traces=traces())
    nodes = {n["id"]: n for n in package["dag"]["nodes"]}
    for year in (2023, 2024, 2025):
        rms = nodes[f"alpha_prior_equal_oof_rms_plan:{year}"]
        assert rms["kind"] == "bridge_calibration"
        assert rms["reservation_multiplicity"] == 1
        assert rms["qualified_exact_reuse_new_reservations"] == 0
        assert all(f"alpha_bridge_plan:{member}:{year}" in rms["dependencies"] for member in MEMBERS)
        assert rms["source_receipt_field"] == "frozen_prior_genuine_OOF_RMS"
        assert rms["executes"] is False
    assert package["budget"]["known_comparison_P2_RMS_states"] == 3
    assert "3 - N_exact_reused_comparison_P2_RMS_states" in package["budget"]["expected"]["per_kind"]["bridge_calibration"]
    assert package["budget"]["prior_warmup_RMS_state_count"] == "UNKNOWN_SOURCE_BINDING_REQUIRED"
    hard = package["budget"]["hard_upper"]
    assert hard["total_learned_attempt_cap"] == 2048
    assert hard["cap_does_not_equal_unknown_dag_total"] is True
    assert "verified_global_remaining" in hard["total_learned_constraint"]

