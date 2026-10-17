"""Compile the frozen 32 roles into dependency/control manifests, without runners.

Risk physical counts come from complete synthetic callback traces. Planning slots
are an explicitly hypothetical calendar, never discovered candidate/support dates.
Unbound alpha/OOF physical decomposition remains parameterized and blocks execution.
"""
from __future__ import annotations

import copy
from collections import Counter
from .shared_risk_budget_r2 import KINDS, LEARNED_KINDS, content_hash

MEMBERS = ("ridge", "hgb", "xgb_rank", "logistic", "cat_uncertainty")
RISKS = ("R0", "RD", "RM", "RB", "RH", "RT", "RR", "RU", "RE")
SENSITIVITY = ("B_R_00", "B_R_01", "B_R_02", "B_R_19",
               "B_R_23", "B_R_24", "B_R_25", "B_R_27")
BASE_DOMAINS = ("stock_price_endpoints", "uid_security_identity", "corporate_action",
                "terminal", "quote", "revision", "availability")
CADENCE = {"R0": "annual", "RD": "monthly", "RM": "quarterly", "RB": "monthly",
           "RH": "quarterly", "RT": "monthly", "RR": "quarterly",
           "RU": "quarterly", "RE": "quarterly"}


def _seal(value):
    result = copy.deepcopy(value)
    result["immutable_payload_sha256"] = content_hash(value)
    return result


def verify_manifest(value):
    payload = {k: v for k, v in value.items() if k != "immutable_payload_sha256"}
    if value.get("immutable_payload_sha256") != content_hash(payload):
        raise ValueError("IMMUTABLE_MANIFEST_CHANGED")
    return True


def _validate(design):
    roles = design.get("primary_specs", [])
    if [r["id"] for r in roles] != [f"B_R_{i:02d}" for i in range(32)]:
        raise ValueError("FROZEN_32_ROLE_ORDER_REQUIRED")
    # Labels are fixed control/policy API identifiers, not an extensible grid.
    for role in roles:
        if role["prediction"] not in ("RAW_RANK", "P0", "P1", "P2"):
            raise ValueError("UNDECLARED_PREDICTION")
        if role["optimizer"] not in ("RAW_FIXED_SCORE", "SIMPLE_EQUAL", "Q0", "Q1", "Q2", "Q3"):
            raise ValueError("UNDECLARED_OPTIMIZER")
        if role["action"] not in ("RAW_ACTION", "SIMPLE_ACTION", "A0", "A1", "A2"):
            raise ValueError("UNDECLARED_ACTION")
        if role["gross"] not in ("RAW_FROZEN", "G0", "G1", "G2"):
            raise ValueError("UNDECLARED_GROSS")
    if not design.get("frozen") or design.get("freeze_allows_outcome_tuning") is not False:
        raise ValueError("FROZEN_OUTCOME_BLIND_DESIGN_REQUIRED")
    if tuple(design["prediction"]["P2"]["declared_members"]) != MEMBERS:
        raise ValueError("FROZEN_FIVE_MEMBER_ORDER_REQUIRED")
    declared = design["future_conditional_account_budget"]
    if tuple(declared["sensitivity_spec_ids"]) != SENSITIVITY:
        raise ValueError("FROZEN_16_SENSITIVITY_REQUIRED")
    for role in roles:
        if role["risk"] not in (*RISKS, "NONE") or role["cost_bps"] != 10 or role["configs"] != 1:
            raise ValueError("UNDECLARED_ROLE_OR_PRIMARY_COST")
    return roles


def _domains(role):
    domains = set(BASE_DOMAINS)
    if role["risk"] in ("RB", "RH", "RR", "RE"):
        domains.add("qqq")
    if role["risk"] == "RH":
        domains.add("pit_ff48")
    if role["risk"] == "RM":
        domains.add("horizon_3_5_10_20_maturity")
    elif role["risk"] != "NONE" or role["optimizer"] == "Q2":
        domains.add("horizon_5_maturity")
    if role["optimizer"] == "Q2":
        domains.add("real_mature_5d_scenarios")
    if role["prediction"] == "P2":
        domains.update(("frozen_calibrated_genuine_oof", "five_native_member_identities"))
    return sorted(domains)


def _slots(cadence, years):
    months = range(1, 13) if cadence == "monthly" else ((1, 4, 7, 10) if cadence == "quarterly" else (1,))
    return [f"{year}-{month:02d}" for year in years for month in months]


def _topological(nodes):
    pending = dict(nodes)
    ordered, completed = [], set()
    while pending:
        ready = sorted(k for k, n in pending.items() if set(n["dependencies"]) <= completed)
        if not ready:
            raise ValueError("DEPENDENCY_CYCLE_OR_MISSING_NODE")
        for key in ready:
            ordered.append(pending.pop(key))
            completed.add(key)
    return ordered


def build_package(design, *, direction_traces=None, planning_years=(2023, 2024, 2025)):
    """Return immutable manifest/DAG/budget/source_requirements; never write files.

    Each direction trace must be a complete single-direction synthetic snapshot
    against the SAME source/cutoff/UID fixture. Equal recorded keys then represent
    proven exact reuse at a common hypothetical planning slot. A trace shape
    changes under missing support/regime/identity: real scheduling remains UNKNOWN.
    """
    roles = _validate(design)
    if tuple(planning_years) != (2023, 2024, 2025):
        raise ValueError("FROZEN_THREE_YEAR_PLANNING_REQUIRED")
    traces = {} if direction_traces is None else direction_traces
    nodes, risk_roots, role_records = {}, {}, []

    def add(node_id, kind, dependencies=(), **metadata):
        node = dict(id=node_id, kind=kind, dependencies=sorted(set(dependencies)), **metadata)
        if node_id in nodes and nodes[node_id] != node:
            raise ValueError("EXACT_STATE_NODE_COLLISION")
        nodes[node_id] = node
        return node_id

    # No implicit P0/P1 versus native-member sharing: their target identities differ.
    for prediction in ("RAW_RANK", "P0", "P1", "P2"):
        deps = []
        if prediction == "P2":
            native = MEMBERS
        elif prediction in ("P0", "P1"):
            native = ("own_hgb5d" if prediction == "P0" else "own_ridge5d",)
        else:
            native = ("raw_rank_frozen",)
        for member in native:
            for year in planning_years:
                source = add(f"prediction_source:{member}:{year}", "source_dependency",
                    scientific_activation="PENDING", physical_fit_decomposition="UNBOUND",
                    source_identity="SOURCE_AND_CUTOFF_BINDING_REQUIRED",
                    member=member, annual_year=year, executes=False)
                if prediction == "RAW_RANK":
                    deps.append(source)
                    continue
                preprocessing = add(f"alpha_preprocessing_plan:{member}:{year}", "scaler", (source,),
                    scientific_activation="PENDING", physical_fit_decomposition="UNBOUND",
                    reservation_multiplicity="UNKNOWN_BIND_EXISTING_NATIVE_PIPELINE",
                    executes=False)
                model = add(f"alpha_model_plan:{member}:{year}", "model_fit", (preprocessing,),
                    scientific_activation="PENDING", physical_fit_decomposition="UNBOUND",
                    reservation_multiplicity="UNKNOWN_INCLUDES_REQUIRED_GENUINE_OOF_SUBFITS",
                    executes=False)
                if prediction == "P2":
                    model = add(f"alpha_bridge_plan:{member}:{year}", "bridge_calibration", (model,),
                        scientific_activation="PENDING", physical_fit_decomposition="UNBOUND",
                        recipe="existing joint_oof_bridge: StandardScaler/Ridge/residual_RMS/native_scale_ratio when required; genuine prior OOF only",
                        reservation_multiplicity="UNKNOWN_PRIOR_REUSABLE_OOF_AND_CALIBRATION_BINDING",
                        executes=False)
                deps.append(model)
        if prediction == "P2":
            for year in planning_years:
                warmup = add(f"prior_oof_warmup_receipts:{year}", "source_dependency",
                    scientific_activation="PENDING", physical_fit_decomposition="UNBOUND",
                    source_identity="GENUINE_PRIOR_OOF_WARMUP_AND_BRIDGE_RECEIPTS_REQUIRED",
                    prior_physical_states="UNKNOWN_SOURCE_BINDING_REQUIRED", executes=False)
                deps.append(add(f"alpha_prior_equal_oof_rms_plan:{year}", "bridge_calibration",
                    [warmup, *[f"alpha_bridge_plan:{member}:{year}" for member in MEMBERS]],
                    name="P2:prior_equal_OOF_RMS",
                    scientific_activation="PENDING",
                    physical_fit_decomposition="KNOWN_SINGLE_RMS_STATISTIC_IF_NEW",
                    reservation_multiplicity=1, qualified_exact_reuse_new_reservations=0,
                    source_receipt_field="frozen_prior_genuine_OOF_RMS",
                    annual_year=year, executes=False))
        add("prediction:" + prediction, "dependency_group", deps, executes=False)

    missing_traces = [risk for risk in RISKS if risk not in traces]
    for risk in RISKS:
        recipe = traces.get(risk, [])
        events = recipe.get("events", recipe) if isinstance(recipe, dict) else recipe
        if not isinstance(events, list):
            raise ValueError("COMPLETE_SYNTHETIC_EVENT_LIST_REQUIRED")
        all_roots = []
        for slot in _slots(CADENCE[risk], planning_years):
            dep_ids = []
            mapping = {e["key"]: f"risk_physical:{slot}:{e['key']}" for e in events}
            for event in events:
                if event["kind"] not in KINDS or event.get("synthetic") is not True:
                    raise ValueError("SYNTHETIC_PHYSICAL_TRACE_REQUIRED")
                if event["kind"] == "account_replay":
                    raise ValueError("NO_ACCOUNT_TRACE_ALLOWED")
                if event["status"] != "SUCCEEDED":
                    raise ValueError("FAILED_TRACE_NOT_A_SUCCESSFUL_PLANNING_RECIPE")
                children = event.get("dependencies", [])
                if any(child not in mapping for child in children):
                    raise ValueError("INCOMPLETE_TRACE_DEPENDENCY_CLOSURE")
                dep_ids.append(add(mapping[event["key"]], event["kind"],
                    [mapping[c] for c in children], name=event["name"],
                    planning_slot=slot, template_exact_key=event["key"],
                    inputs_hash_template=event["inputs_sha256"],
                    source_context_template=copy.deepcopy(event["context"]),
                    frozen_parameters=copy.deepcopy(event["parameters"]),
                    executes=False, synthetic_recipe=True))
            all_roots.append(add(f"risk_state:{risk}:{slot}", "dependency_group", dep_ids,
                risk=risk, cadence=CADENCE[risk], recipe_status="BOUND_SYNTHETIC" if risk in traces else "UNKNOWN",
                cutoff_rule="prior legal session Close", executes=False))
        risk_roots[risk] = add("risk:" + risk, "dependency_group", all_roots, executes=False)
    add("risk:NONE", "dependency_group", executes=False)

    # These graph nodes are function invocations per qualified decision, not fits.
    # Prediction/risk can share; policy outputs require each account's actual state.
    runs = [(r, 10, "main") for r in roles]
    runs += [(r, cost, "sensitivity") for r in roles if r["id"] in SENSITIVITY for cost in (5, 20)]
    for role, cost, scope in runs:
        p, risk = "prediction:" + role["prediction"], "risk:" + role["risk"]
        run_id = f"account:{role['id']}:{cost}bps"
        context = add(f"account_context:{role['id']}:{cost}bps", "source_dependency",
            scientific_activation="PENDING", executes=False,
            required_state_fields=["current_weights", "reserved_weights", "cash", "holding_age",
                                   "as_of", "cutoff", "source_identity", "account_state_value_hash"],
            state_rule="actual prior causal state of this continuous account path; labels do not establish equality")
        # These are account-bound API invocation templates, not proven exact states.
        q = add(f"q:{run_id}", "deterministic_transform", (p, risk, context),
                api=role["optimizer"], executes=False, account_context=context,
                template_only=True, exact_reuse_proven=False,
                multiplicity=f"N_qualified_decisions({run_id})")
        if role["action"] == "A2":
            nodes[q]["preallocation_gate"] = dict(
                api="A2", dependencies=[context, p, risk],
                frozen_parameters=copy.deepcopy(design.get("actions", {}).get(
                    "A2", "FROZEN_A2_PARAMETER_BINDING_REQUIRED")),
                stage="BEFORE_ALLOCATION", executes=False)
        gross = add(f"gross:{run_id}", "deterministic_transform", (q, risk, context),
                    api=role["gross"], executes=False, account_context=context,
                    template_only=True, exact_reuse_proven=False,
                    multiplicity=f"N_qualified_decisions({run_id})")
        action = add(f"action:{run_id}", "deterministic_transform", (q, gross, context),
                     api=role["action"], executes=False, account_context=context,
                     control_stage="POST_G_TARGET_WEIGHTS_CONTROL",
                     template_only=True, exact_reuse_proven=False,
                     multiplicity=f"N_qualified_decisions({run_id})")
        cost_id = add(f"cost:ADVERSE_NEXT_RAW_OPEN:{cost}bps", "deterministic_transform",
                      cost_bps=cost, executes=False, multiplicity=1)
        account = add(run_id, "account_replay", (action, gross, cost_id),
                      scientific_activation="PENDING", executes=False, continuous_across_years=True,
                      starting_cash=3000, account_count=1, selection_eligible=False,
                      selection_role_eligible=scope == "main")
        record = copy.deepcopy(role)
        record.update(run_id=account, scope=scope, cost_bps=cost,
            prediction_dependency=p, risk_dependency=risk, q_dependency=q,
            action_dependency=action, gross_dependency=gross, cost_identity=cost_id,
            required_source_domains=_domains(role),
            fit_dependencies="TRANSITIVE_DAG_LEARNED_NODES_AND_UNBOUND_ALPHA_OOF_RECIPE",
            reusable_state=[p, risk],
            policy_api_templates=[q, action, gross], account_context_dependency=context,
            blocked_conditions=["SOURCE_NOT_ACTIVATED", "EXACT_IDENTITY_BINDING_MISSING",
                                "SUPPORT_OR_MATURITY_MISSING", "PIT_OR_QUOTE_AUTHORITY_MISSING",
                                "FIT_DECOMPOSITION_OR_REMAINING_BUDGET_UNVERIFIED"],
            activation_status="SOURCE_AND_SCIENTIFIC_ACTIVATION_PENDING", executes=False)
        role_records.append(record)

    ordered = _topological(nodes)
    for record in role_records:
        visited, queue = set(), [record["run_id"]]
        while queue:
            current = queue.pop()
            if current not in visited:
                visited.add(current)
                queue.extend(nodes[current]["dependencies"])
        record["fit_dependencies"] = sorted(
            k for k in visited if nodes[k]["kind"] in LEARNED_KINDS)
        record["unbound_fit_dependencies"] = sorted(
            k for k in visited if nodes[k].get("physical_fit_decomposition") == "UNBOUND")
    risk_counts = dict.fromkeys(KINDS, 0)
    for n in ordered:
        if n.get("synthetic_recipe"):
            risk_counts[n["kind"]] += 1
    policy_counts = Counter(n["kind"] for n in ordered if not n.get("synthetic_recipe"))
    policy_transform_templates = policy_counts["deterministic_transform"] - 3
    expressions = dict(risk_counts)
    expressions["model_fit"] = f"{risk_counts['model_fit']} + N_new_model_and_OOF_states"
    expressions["scaler"] = f"{risk_counts['scaler']} + N_new_alpha_bridge_OOF_preprocessing_states"
    expressions["bridge_calibration"] = (
        f"{risk_counts['bridge_calibration']} + 3 - N_exact_reused_comparison_P2_RMS_states"
        " + N_new_other_bridge_calibration_OOF_error_states")
    expressions["deterministic_transform"] = (
        f"{risk_counts['deterministic_transform']} + sum_account(3*N_qualified_decisions(account)) + 3")
    expressions["account_replay"] = "48 - N_exact_reused_qualified_accounts"
    upper_expressions = dict(expressions)
    upper_expressions["deterministic_transform"] = (
        f"{risk_counts['deterministic_transform']} + 144*N_qualified_decisions_max + 3")
    assumptions = dict(
        calendar="ENGINEERING_HYPOTHESIS_ONLY_NOT_REAL_SESSION_OR_SUPPORT_DISCOVERY",
        years=list(planning_years), annual_slots=3, monthly_slots=36, quarterly_slots=12,
        session_rule="first legal session; prior-session cutoff, resolved only after qualified calendar activation",
        recipe="single complete synthetic fixture per direction; state equality only under exact source/input/cutoff/assets/units/horizon/parameters equality",
        support="all planning slots satisfy same synthetic recipe; actual eligible assets, identities, regime occupancy and decision count UNKNOWN",
        unknowns=["N_qualified_decisions(account)", "N_qualified_decisions_max", "N_new_model_and_OOF_states",
                  "N_new_alpha_bridge_OOF_preprocessing_states",
                  "N_new_other_bridge_calibration_OOF_error_states",
                  "N_exact_reused_comparison_P2_RMS_states", "N_exact_reused_qualified_accounts"],
        parameter_constraints=dict(N_exact_reused_comparison_P2_RMS_states="integer in [0,3]",
                                   all_other_new_state_counts="nonnegative bound integers required"),
        known_P2_comparison_prior_equal_OOF_RMS_states=3,
        P2_prior_warmup="genuine prior OOF/model/bridge/RMS source binding UNKNOWN; additional states included in N_new_other_*",
        caps="verification of existing prior occupancy and full concrete recipe required before execution")
    zero = dict.fromkeys(KINDS, 0)
    budget = _seal(dict(
        schema="B_R_PHYSICAL_BUDGET_R2", executes=False, current_real_execution_counts=zero,
        accounting_rule="reserve-before-fit; failed occupancy retained; same-key failed no retry; exact successful reuse only",
        missing_direction_traces=missing_traces,
        planning_recipe_counts=risk_counts if not missing_traces else "UNKNOWN_INCOMPLETE_SYNTHETIC_RECIPE",
        known_comparison_P2_RMS_states=3,
        comparison_P2_RMS_new_count="3 - N_exact_reused_comparison_P2_RMS_states",
        prior_warmup_RMS_state_count="UNKNOWN_SOURCE_BINDING_REQUIRED",
        min=dict(case="all physical learned states have qualified exact existing artifacts; no new fits",
                 incremental_physical_learned_counts={k: 0 for k in LEARNED_KINDS},
                 other_counts="policy algebra and unreused accounts remain conditional"),
        expected=dict(case="full frozen three-year planning schedule; complete support and specified recipe",
                      per_kind=expressions, status="PARAMETERIZED_REAL_ALPHA_OOF_AND_SUPPORT_UNKNOWN"),
        hard_upper=dict(case="one reservation per planned exact node; no retries or hidden search",
                        per_kind=upper_expressions, status="PARAMETERIZED_NOT_A_VERIFIED_EXECUTION_ALLOWANCE",
                        total_learned_attempt_cap=2048,
                        total_learned_constraint="sum(per_kind[learned]) <= min(2048, verified_stage_remaining, verified_global_remaining)",
                        prior_occupancy="UNKNOWN_MUST_REVERIFY",
                        global_cap_reference=4096,
                        cap_does_not_equal_unknown_dag_total=True),
        conditional_incremental_attempt_cap=2048,
        cap_check="learned total must be <= min(2048, verified stage/global remaining); missing parameter bounds BLOCK",
        assumptions=assumptions, policy_transform_templates=policy_transform_templates,
        account_plans=48, failed_fit_refund=0, retry_limit=0))
    manifest = _seal(dict(schema="B_R_32_EXECUTABLE_MANIFEST_R2",
        frozen_design_id=design["design_id"], frozen_design_payload_sha256=content_hash(design),
        activation_status="ENGINEERING_READY_SOURCE_AND_SCIENTIFIC_ACTIVATION_PENDING",
        main=role_records[:32], sensitivity=role_records[32:], main_count=32, sensitivity_count=16,
        performance_computed=False, executes=False))
    source = _seal(dict(schema="B_R_SOURCE_REQUIREMENT_SCHEMA_R2",
        activation_status="NOT_ACTIVATED", real_support_discovered=False, economic_results_read=False,
        roles={r["id"]: _domains(r) for r in roles},
        required_fields=dict(
            stock_price_endpoints=["origin", "entry_next_legal_raw_open", "endpoint_raw_open_by_horizon",
                                   "coordinate", "qualified_shareholder_value", "value_hash"],
            qqq=["official_qqq_identity", "same_horizon_endpoint", "qualified_daily_sessions_for_20_session_vol",
                 "available_at", "source_receipt", "no_cross_sectional_proxy"],
            horizon_5_maturity=["origin", "horizon_5", "entry_endpoint", "exit_endpoint",
                                "published_at", "mature_at", "qualified_common_support"],
            real_mature_5d_scenarios=["actual_qualified_5d_returns", "common_support_uid",
                                      "origin", "endpoint", "mature_at", "source_receipt"],
            frozen_calibrated_genuine_oof=["declared_five_members", "genuine_prior_oof_row_proof",
                                           "member_fit_cutoff", "bridge_cutoff", "label_maturity",
                                           "frozen_calibrated_mu", "frozen_prior_genuine_OOF_RMS",
                                           "rms_state_source_cutoff_receipt", "value_hash"],
            five_native_member_identities=["member_name", "native_target", "model_source_sha256",
                                            "feature_identity", "training_cutoff", "oof_receipt"],
            horizon_3_5_10_20_maturity=["origin", "horizon", "endpoint", "available_at", "mature_at", "common_support_uid"],
            pit_ff48=["security_uid", "ff48_group", "effective_from", "effective_to", "available_at", "source_receipt"],
            uid_security_identity=["security_uid", "identity_epoch", "effective_interval", "available_at"],
            corporate_action=["event_identity", "effective_at", "available_at", "shareholder_value_receipt"],
            terminal=["terminal_status", "effective_at", "available_at", "cash_or_successor_rights_receipt"],
            quote=["quote_authority", "execution_raw_open_receipt", "causal_availability"],
            revision=["source_version", "accepted_revision", "value_hash"],
            availability=["published_at", "available_at", "decision_at", "cutoff", "source_identity"]),
        learned_cutoff_exclusive="2026-01-01", fallback="BLOCKED_REQUIRED_DOMAIN_MISSING"))
    dag = _seal(dict(schema="B_R_DEPENDENCY_DAG_R2", nodes=ordered,
        topological_order=[n["id"] for n in ordered], assumptions=assumptions,
        main_roots=[r["run_id"] for r in role_records[:32]],
        sensitivity_roots=[r["run_id"] for r in role_records[32:]],
        current_executed_accounts=0, current_executed_real_fits=0,
        recipe_status="COMPLETE_SYNTHETIC" if not missing_traces else "UNKNOWN_INCOMPLETE"))
    return dict(manifest=manifest, dag=dag, budget=budget, source_requirements=source)

