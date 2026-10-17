"""Exact metadata profile for the authorized 94-policy descriptive comparison.

Extends the common custody gate; no model decoder, input reader, or account engine.
Source qualification here binds declarations, not scientific PIT certification.
"""
from __future__ import annotations
import json
from dataclasses import replace
from pathlib import Path
import pandas as pd
from scripts.common.storage_paths import resolve

TASK = "DEMO_VS_A_STATEFUL_FROZEN_TEST2026_R1"
_ROOT = Path(r"D:\us-tech-quant-results\_maintenance\DEMO_VS_A_STATEFUL_FROZEN_TEST2026_R1")
_PINS = {
    "plan": ("EVALUATION_PLAN.json", "83eadbe14f021a84cb1349865f9635b2f971e9301e4f756388e1079b0e053157"),
    "inventory": ("A_FROZEN_CANDIDATE_INVENTORY.json", "e8eca101f29f4e05fd70cc1b41f4a680c9352ad42f5f489a32eada8b026c91ec"),
    "old_states": ("A_OLD57_SERIALIZED_STATE_AUDIT.json", "e8afd4d49a87eedd12958f0cb9479ad2b2df32a2abd50f6ebf2b91f4c8440a65"),
    "new_states": ("A_NEW37_FROZEN_STATE_DEPENDENCIES.json", "744111627545fa637b51f7245de4dfccf2681b9f34a9aa7686acd53b1299d4c7"),
    "raw_selector": ("A_ORIGINAL_UNIVERSE_EXTENSION_AUDIT.json", "9794a474bc81ba55b267afcddcbf41c8644391e6b1d9494e93fc30eb46c1b95d"),
    "fusion": ("A_OLD57_INFERENCE_ADAPTER_REQUIREMENTS.json", "5f07ae3ad9e91e7b3f11afecccd45126e7df5e21c0262b93dfd6118dc573a86a"),
}


ALL_TASK = "A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1"
_ALL_ROOT = Path("D:/us-tech-quant-results/_maintenance/A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1")
# Incomplete pins deliberately prevent real execution before the new freeze.
_ALL_PINS = {
    "plan": ("EVALUATION_PLAN_CONSENSUS_ALL_A_R2.json", "0c8cef4cab24a93f064000ca9271fbe6cfc1ac8ca9ff8658453bfb5f41dc5a7e"),
    "inventory": ("A_ALL_FROZEN_CANDIDATE_INVENTORY.json", "3a4d491fad4fcd79bad84f93257345592bd2f9a0c7077eebae9a81bee6f5f7dc"),
    "schedule": ("RANDOM_WINDOWS.json", "903e6b72d8c1c55f7214b1761f8a6ee607faca5caa5e9d67210d94eb5ba60f3a"),
    "new_states": ("A_ALL_FROZEN_STATE_DEPENDENCIES.json", "84d2f4a644d1fdfae4f6954a3751be3bc156ec0141f537dbf64cdb55a0bf25a9"),
    "old_states": (str(_ROOT / "A_OLD57_SERIALIZED_STATE_AUDIT.json"), "e8afd4d49a87eedd12958f0cb9479ad2b2df32a2abd50f6ebf2b91f4c8440a65"),
    "fusion": (str(_ROOT / "A_OLD57_INFERENCE_ADAPTER_REQUIREMENTS.json"), "5f07ae3ad9e91e7b3f11afecccd45126e7df5e21c0262b93dfd6118dc573a86a"),
    "raw_selector": ("CONSENSUS_RAW_SELECTOR_SCOPE_R2.json", "0c82334a83f6225ecaf7043f310ad6b267a255d5dd6d3044408aab818d398bd9"),
}
_ALL_POST_VERIFIED_DECISION_PIN = ("A_ALL_CONSENSUS_POST_VERIFIED_CASH_TERMINAL_SOURCE_DECISION_R2.json", "c21244976f21c6ce905378d9c715146ab660b33e59ef4f7e5a75a246d16baf20")
_CONSENSUS_SOURCE_REF = dict(path="D:/us-tech-quant-backtests/V24_A_13F_CONSENSUS_TOP100_RETEST_20261009_R1/source_snapshots/source_manifest.json", sha256="86ee6aa47e605c911010f9ee76d943c0f41ddc1bd2ffa970f969cce97c7d1463")


REPAIR_TASK = "A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1"
_REPAIR_ROOT = Path("D:/us-tech-quant-results/_maintenance") / REPAIR_TASK
_REPAIR_SOURCE_ROOT = Path("D:/us-tech-quant-backtests") / REPAIR_TASK / "20261010T155614+0000_8a89315b/derived/consensus_inputs"
_REPAIR_PINS = {
    "plan": ("EVALUATION_PLAN.json", "9114d8618ab4fe2c490d991a06bad39f130336178f135aa8c138c809da3d91f2"),
    "inventory": ("RAW_CANDIDATE_INVENTORY_R2.json", "8873967086da2483304effe3d03a80b179d71e11e6e45fd8ef707cbe70cf81db"),
    "common_runtime": ("COMMON_RUNTIME_CONTRACT_R4.json", "a6b8d5705f1ca8d70fa4d3ce99f28bb2101effcb131de20da45633adc9c61004"),
    "source_manifest": (str(_REPAIR_SOURCE_ROOT / "SOURCE_MANIFEST.json"), "112c596625e3cef490c01f902294924f738b498f50098172348e2e2d6c5ac644"),
    "source_catalog": (str(_REPAIR_SOURCE_ROOT / "RAW_VARIANT_SOURCE_CATALOG_R4.json"), "a1199acf57c5a8ccac69645a8b71fb6f9582034ddb0e709049e3b68ad4972694"),
}
_REPAIR_POST_VERIFIED_DECISION_PIN = ("POST_VERIFIED_ACCOUNTING_DECISION_R2.json", "5d3414ca3e1dc17feab1888f3f68cb8f0d7fce1ea34706f3f27b6463bd89aba4")
_REPAIR_MANAGERS = ("akre", "altimeter", "appaloosa", "ark", "baupost", "berkshire", "citadel", "coatue", "d1_capital", "de_shaw", "dragoneer", "duquesne", "elliott", "himalaya", "light_street", "lone_pine", "millennium", "pershing_square", "point72", "situational_awareness", "soros", "third_point", "tiger_global", "viking", "whale_rock")
REPAIR_VARIANTS = tuple("TOP" + str(n) for n in (100, 200, 300, 400)) + tuple("LOO_" + m + "_TOP100" for m in _REPAIR_MANAGERS)


_REPAIR_ACCOUNT_GROUPS = (
    "R10_DIRECT_MEAN4_ELASTICNET_HIGH", "R10_DIRECT_MEAN4_ELASTICNET_MID",
    "R10_DIRECT_MEAN4_FT_TRANSFORMER_HIGH", "R10_DIRECT_MEAN4_FT_TRANSFORMER_LOW", "R10_DIRECT_MEAN4_FT_TRANSFORMER_MID",
    "R10_DIRECT_MEAN4_HUBER_HIGH", "R10_DIRECT_MEAN4_HUBER_LOW",
    "R10_SEQUENCE_GRU_L20_HIGH", "R10_SEQUENCE_GRU_L20_LOW", "R10_SEQUENCE_GRU_L20_MID",
    "R10_SEQUENCE_LSTM_L20_HIGH", "R10_SEQUENCE_LSTM_L20_LOW", "R10_SEQUENCE_LSTM_L20_MID",
    "R10_SEQUENCE_TCN_L20_HIGH", "R10_SEQUENCE_TCN_L20_LOW", "R10_SEQUENCE_TCN_L20_MID",
)

def profile_tasks():
    return (TASK, ALL_TASK, REPAIR_TASK)


_POST_VERIFIED_DECISION_PIN = (
    "A94_POST_VERIFIED_CASH_TERMINAL_SOURCE_DECISION.json",
    "444d8f6f52cb1d10de9ac9377e63c84107f2a8344873f53901c2b21e3b496188",
)


def required_action_roles(candidate_id, *, authority=None, bindings=None):
    """Frozen runtime roles, independent of scores, holdings and outcomes."""
    if authority is not None and authority.task_id in (ALL_TASK, REPAIR_TASK):
        bindings = json.loads(authority.provenance_json)["candidate_bindings"]
    if bindings is not None:
        rows = [r for r in bindings if r["candidate_id"] == candidate_id]
        _common()._require(len(rows) == 1, "ALL_A_FROZEN_ACTION_ROLE_REQUIRED")
        return tuple(rows[0]["required_action_roles"])
    if candidate_id.startswith("R6_"):
        role = candidate_id.split("_")[1].lower()
        _common()._require(role in ("buy", "hold", "replace", "duration", "distribution"),
                           "A94_UNKNOWN_ACTION_ROLE")
        return ("R6:distribution", "R6:distribution_pair") if role == "distribution" else ("R6:" + role,)
    if candidate_id.startswith("R10_DIRECT_MEAN4_"):
        return ("R10:ENTRY", "R10:INCUMBENT")
    if candidate_id.startswith("R10_SEQUENCE_"):
        return ("R10:JOINT_SEQUENCE",)
    if candidate_id.startswith("R10_HAZARD_"):
        return ("R10:HAZARD",)
    return ()  # OLD57 exact IDs/specifications remain inventory-bound.


def _post_verified_decision_ref(task_id=TASK, *, recovered=False):
    _common()._require(not recovered or task_id == REPAIR_TASK, "REPAIR_RECOVERY_DECISION_SCOPE_REQUIRED")
    if task_id == TASK:
        name, digest = _POST_VERIFIED_DECISION_PIN
        root = _ROOT
    elif task_id == REPAIR_TASK:
        name, digest = (("POST_VERIFIED_RECOVERY_ACCOUNTING_DECISION_R1.json", "e2cecec0717a181d14e8ad9d0afb5e8899b3b69ecb52110b9037a4991830d05a")
            if recovered else _REPAIR_POST_VERIFIED_DECISION_PIN)
        root = _REPAIR_ROOT
    else:
        _common()._require(task_id == ALL_TASK and _ALL_POST_VERIFIED_DECISION_PIN is not None,
                           "ALL_A_POST_VERIFIED_DECISION_NOT_FROZEN")
        name, digest = _ALL_POST_VERIFIED_DECISION_PIN
        root = _ALL_ROOT
    return {"path": str(root / name), "sha256": digest}


def _post_verified_binding_header(binding, key):
    """No IO: reject task splices and unauthorized terminal economics at runtime."""
    f = _common()
    f._require(isinstance(binding, dict) and binding.get("task_id") in profile_tasks()
        and (binding.get("authorization_ref") == _post_verified_decision_ref(binding.get("task_id"))
            or binding.get("task_id") == REPAIR_TASK and binding.get("authorization_ref") == _post_verified_decision_ref(REPAIR_TASK, recovered=True)),
        "A94_POST_VERIFIED_HUMAN_DECISION_REQUIRED")
    if key == "research_terminal_reconstruction" and binding["task_id"] == TASK:
        entries = binding.get("events")
        f._require(isinstance(entries, list) and len(entries) == 1,
                   "A94_DBRG_TERMINAL_SCOPE_REQUIRED")
        terms = entries[0].get("terminal_terms", {})
        effective = pd.Timestamp(terms.get("effective_at"))
        f._require(terms.get("ticker") == "DBRG" and terms.get("cash_per_old_share") == 16.0
            and terms.get("currency") == "USD" and terms.get("available_at") is None
            and terms.get("settlement") is None
            and terms.get("effective_clock_basis") == "SOURCE_EFFECTIVE_BY_OPEN_UPPER_BOUND"
            and effective == pd.Timestamp("2026-09-30T13:30:00Z"),
            "A94_DBRG_TERMINAL_SCOPE_REQUIRED")


def _accounting_decision(bound, contract):
    """Exact human pin is required only for post-verified accounting."""
    f = _common()
    keys = ("research_cash_reconstruction", "research_terminal_reconstruction")
    active = [k for k in keys if bound.get(k) is not None]
    if not active:
        f._require(bound.get("post_verified_accounting_decision_ref") is None,
                   "A94_POST_VERIFIED_DECISION_WITHOUT_BINDING")
        return None
    expected = contract.get("recovery_accounting_decision_ref") or _post_verified_decision_ref(contract["task_id"])
    f._require(bound.get("post_verified_accounting_decision_ref") == expected,
               "A94_POST_VERIFIED_HUMAN_DECISION_REQUIRED")
    decision = _document(expected)
    f._require(decision.get("schema") == "A94_POST_VERIFIED_CASH_TERMINAL_SOURCE_DECISION_R1"
        and decision.get("task_id") == contract["task_id"]
        and decision.get("status") == "HUMAN_AUTHORIZED_NOT_SOURCE_OR_RUNTIME_ADMISSION"
        and decision.get("candidate_scope") == ("EXACT94_FROZEN_EMPTY_START_RESEARCH_POLICIES" if contract["task_id"] == TASK
            else "EXACT_ORIGINAL_KNOWN19_RECOVERED_SINGLE_GROUP_TOP100_FRESH_RANDOM_RESEARCH" if contract.get("repaired_group_id")
            else "EXACT_PINNED_RAW_S10_CONSENSUS_SENSITIVITY_FRESH_RANDOM_RESEARCH" if contract["task_id"] == REPAIR_TASK
            else "EXACT_PINNED_FULL_A_INVENTORY_FRESH_RANDOM_RESEARCH")
        and decision.get("clock_role") == "POST_VERIFIED_ACCOUNTING_ONLY"
        and decision.get("original_plan_ref") == contract["metadata_refs"]["plan"]
        and decision.get("candidate_manifest_ref") == contract["metadata_refs"]["inventory"]
        and pd.Timestamp(decision.get("economic_as_of_utc")) == pd.Timestamp(_contract_as_of(contract))
        and decision.get("separate_A6_permission_inherited") is False,
        "A94_POST_VERIFIED_HUMAN_DECISION_CHANGED")
    denied = decision.get("prohibitions", {})
    f._require(all(denied.get(k) is False for k in (
        "model_or_H5_input_authority", "new_fit", "parameter_or_rule_change", "strategy_selection",
        "production_qualified", "strict_PIT_promotion_eligible", "broker_orders",
        "source_or_account_admitted_by_decision_alone", "economic_window_extended")),
        "A94_POST_VERIFIED_ACCOUNTING_ONLY_REQUIRED")
    if contract["task_id"] in (ALL_TASK, REPAIR_TASK) and "research_terminal_reconstruction" in active:
        actual = [e.get("terminal_terms") for e in bound["research_terminal_reconstruction"].get("events", [])]
        f._require(bool(actual) and _exact(actual, decision.get("authorized_terminal_terms")),
                   "ALL_A_EXACT_AUTHORIZED_TERMINAL_TERMS_REQUIRED")
    for key in active:
        if contract["task_id"] == REPAIR_TASK:
            f._require(bound[key].get("authorization_ref") == expected, "REPAIR_EXACT_GROUP_ACCOUNTING_DECISION_REQUIRED")
        _post_verified_binding_header(bound[key], key)
    return expected


def _source_ready_policies(qualification, sources, ids, *, bindings=None):
    """Keep source failures visible without certifying the entire action slot."""
    f = _common()
    groups = qualification.get("groups")
    f._require(isinstance(groups, dict) and set(groups) == set(f.SOURCE_GROUPS)
        and all(groups[k] is True for k in f.SOURCE_GROUPS if k != "action_inputs"),
        "DESCRIPTIVE_SOURCE_GATE_NOT_TRUE")
    per_candidate = qualification.get("candidate_source_qualification")
    if per_candidate is None:
        f._require(groups["action_inputs"] is True, "DESCRIPTIVE_SOURCE_GATE_NOT_TRUE")
        f._require(bindings is None, "ALL_A_EXPLICIT_PER_CANDIDATE_QUALIFICATION_REQUIRED")
        return list(ids)
    f._require(isinstance(per_candidate, dict) and set(per_candidate) == set(ids),
               "A94_EXACT_CANDIDATE_SOURCE_QUALIFICATION_REQUIRED")
    ready = []
    for cid in ids:
        item = per_candidate[cid]
        f._require(isinstance(item, dict)
            and item.get("required_action_roles") == list(required_action_roles(cid) if bindings is None else required_action_roles(cid, bindings=bindings))
            and item.get("source_ref") == sources["action_inputs"],
            "A94_CANDIDATE_SOURCE_ROLE_CHANGED")
        status = item.get("status")
        f._require(status in ("QUALIFIED", "BLOCKED"), "A94_CANDIDATE_SOURCE_STATUS_REQUIRED")
        if status == "QUALIFIED":
            if bindings is not None:
                row = next(r for r in bindings if r["candidate_id"] == cid)
                f._require(row["dependency_closure"]["status"] == "COMPLETE"
                    and row["runtime_owner"] in ("STATEFUL_OVERLAY", "FINAL_ACTION_OVERLAY"),
                    "ALL_A_UNCLOSED_POLICY_CANNOT_RUN")
            ready.append(cid)
        else:
            f._require(isinstance(item.get("reason"), str) and bool(item["reason"].strip()),
                       "A94_BLOCKED_SOURCE_REASON_REQUIRED")
    f._require(bool(ready) and groups["action_inputs"] is (len(ready) == len(ids)),
               "A94_PARTIAL_SOURCE_GATE_MISREPRESENTED")
    return ready


def _exact(left, right):
    return json.dumps(left, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")) == json.dumps(right, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _common():
    from scripts.research.a2.evaluation import frozen_test_authority
    return frozen_test_authority


def _roots():
    paths = resolve(Path(__file__).resolve().parents[4])
    return tuple(Path(getattr(paths, k)).resolve() for k in ("results_root", "cache_root", "backtest_root"))


def _safe_path(ref):
    f = _common()
    f._require(isinstance(ref, dict) and isinstance(ref.get("path"), str), "A94_REFERENCE_REQUIRED")
    path = Path(ref["path"])
    f._require(path.is_absolute() and path.drive.upper() not in ("E:", "F:"), "A94_PHYSICAL_ROOT_REQUIRED")
    physical = path.resolve(strict=True)
    f._require(physical.is_file() and any(physical.is_relative_to(r) for r in _roots()), "A94_PHYSICAL_ROOT_REQUIRED")
    return path


def _physical(ref):
    _safe_path(ref)
    return _common()._physical(ref)


def _document(ref):
    path = _safe_path(ref)
    _common()._require(path.stat().st_size <= 16 * 1024 * 1024, "A94_METADATA_SIZE_BOUND")
    value = json.loads(_physical(ref).read_text(encoding="utf-8-sig"))
    _common()._require(isinstance(value, dict), "A94_METADATA_OBJECT_REQUIRED")
    return value


def frozen_profile_contract():
    """Original exact94/111 profile; all original pins remain unchanged."""
    refs = {key: {"path": str(_ROOT / name), "sha256": digest} for key, (name, digest) in _PINS.items()}
    return _profile_contract(TASK, refs, {key: _document(ref) for key, ref in refs.items()}, legacy=True)


def _profile_contract(task, refs, docs, *, legacy):
    f = _common()
    plan, inventory = docs["plan"], docs["inventory"]
    f._require(plan.get("task_id") == task and plan.get("training_content_cutoff_exclusive") == "2026-01-01"
        and plan.get("development_validation_cutoff_exclusive") == "2026-01-01"
        and plan.get("test_interval") == ["2026-01-01", "2027-01-01"], "A94_FROZEN_PLAN_REQUIRED")
    rows = inventory.get("candidates")
    f._require(isinstance(rows, list) and bool(rows) and (not legacy or len(rows) == 94) and all(isinstance(r, dict) for r in rows), "A94_EXACT_INVENTORY_REQUIRED")
    ids = [r.get("candidate_id") for r in rows]
    f._require(all(isinstance(i, str) and i for i in ids) and len(set(ids)) == len(rows), "A94_EXACT_INVENTORY_REQUIRED")
    bindings = []
    for row in rows:
        spec = row.get("specification")
        f._require(isinstance(spec, dict) and spec.get("candidate_id") == row["candidate_id"]
            and spec.get("scientific_tuple_sha256") == row.get("scientific_tuple_sha256")
            and spec.get("execution_friction", {}).get("one_way_bps") in (5, 10, 20), "A94_FULL_FROZEN_SPEC_REQUIRED")
        fields = ("candidate_id", "scientific_tuple_sha256", "specification")
        if not legacy:
            fields += ("source_group", "runtime_owner", "required_action_roles", "dependency_closure")
            f._require(all(k in row for k in fields), "ALL_A_FROZEN_RUNTIME_BINDING_REQUIRED")
        bindings.append({k: row[k] for k in fields})
        if not legacy:
            bindings[-1]["lookback"] = row.get("lookback")
    old, newer, fusion = docs["old_states"], docs["new_states"], docs["fusion"]
    f._require(not legacy or (len(old.get("value_models", [])) == 13 and len(old.get("risk_models", [])) == 12
        and len(newer.get("model_states", [])) == 81 and len(newer.get("external_scaler_states", [])) == 4),
        "A94_STATE_CLOSURE_REQUIRED")
    states, seen = {}, {}
    def add(key, model, receipt):
        f._require(isinstance(model, dict) and isinstance(receipt, dict), "A94_STATE_CLOSURE_REQUIRED")
        identity = model.get("path")
        item = dict(model_ref=model, receipt_ref=receipt)
        if identity in seen:
            f._require(seen[identity] == item, "A94_CONFLICTING_STATE_IDENTITY")
        else:
            states[key] = item
            seen[identity] = item
    for row in old["value_models"]:
        m = row["metadata"]
        add("old_value:" + row["model_id"], dict(path=m["model_path"], sha256=m["model_sha256"]), row["receipt_ref"])
    for row in old["risk_models"]:
        add("old_risk:" + row["risk_id"], row["bundle_ref"], row["receipt_ref"])
    for group, prefix in (("model_states", "new_model:"), ("external_scaler_states", "new_scaler:")):
        for row in newer[group]:
            add(prefix + row["slot_id"], dict(path=row["model_path"], sha256=row["model_sha256"]), row["receipt_ref"])
    experts = fusion.get("fusion_expert2025_closure", {}).get("experts", [])
    f._require([r.get("model_id") for r in experts] == ["ridge", "hgb", "lgb"]
        and all(r.get("year") == 2025 for r in experts), "A94_FUSION_EXPERT_CLOSURE_REQUIRED")
    for row in experts:
        add("fusion_expert:" + row["model_id"], row["model_ref"], row["receipt_ref"])
    f._require(not legacy or (len(states) == 111 and "fusion_expert:lgb" in states), "A94_111_STATES_REQUIRED")
    raw = docs["raw_selector"]["same_model_not_same_universe"]
    model = raw["frozen_Raw_A2_model"]
    vintage = raw["historical_2026_model_metadata"]
    raw_binding = dict(model_ref={k: model[k] for k in ("path", "sha256")},
        feature_source_ref={k: raw["frozen_feature_source"][k] for k in ("path", "sha256")},
        ordered_32_features=raw["ordered_32_features"], original_universe_contract=docs["raw_selector"]["original_contract"],
        model_vintage={k: vintage[k] for k in ("year", "train_start", "train_end", "labelmax", "model_role")})
    f._require(len(raw_binding["ordered_32_features"]) == 32 and vintage["model_role"] == "FROZEN_FULL_PRE2026_FOR_2026_INFERENCE_ONLY"
        and pd.Timestamp(vintage["labelmax"]) < pd.Timestamp("2026-01-01"), "A94_ORIGINAL_RAW_SELECTOR_REQUIRED")
    if not legacy:
        raw_binding.update(_application_pool_scope(task, refs, docs))
        _validate_full_inventory(bindings, states)
    return dict(task_id=task, metadata_refs=refs, plan=plan, candidate_bindings=bindings, state_refs=states,
        raw_selector_binding=raw_binding)


def _application_pool_scope(task, refs, docs):
    """Bind the explicitly authorized application pool; never relabel training."""
    f = _common()
    plan, rawdoc = docs["plan"], docs["raw_selector"]
    scope = plan.get("A_scope", {})
    if scope.get("universe_variant") is None:
        f._require(rawdoc.get("application_pool_origin") is None,
                   "ALL_A_UNDECLARED_APPLICATION_POOL")
        return {}
    f._require(task == ALL_TASK and scope.get("universe_variant") == "CONSENSUS100"
        and scope.get("universe_application_authorized") is True
        and scope.get("no_new_algorithm_combinations") is True
        and rawdoc.get("schema") == "ALL_A_CONSENSUS100_FROZEN_RAW_SELECTOR_APPLICATION_SCOPE_R2"
        and rawdoc.get("task_id") == task and rawdoc.get("plan_ref") == refs["plan"]
        and rawdoc.get("scope_amendment_ref") == plan.get("scope_amendment_ref")
        and rawdoc.get("consensus_contract_ref") == scope.get("universe_contract_ref")
        and rawdoc.get("application_pool_origin") == "CONSENSUS_TOP100_FULL_PIT32_APPLICATION_POOL"
        and rawdoc.get("new_model_or_fit") is False
        and rawdoc.get("pre2026_training_identity_unchanged") is True,
        "ALL_A_CONSENSUS_APPLICATION_SCOPE_REQUIRED")
    _physical(plan["scope_amendment_ref"])
    parent = _document(scope["universe_contract_ref"])
    universe = _document(_CONSENSUS_SOURCE_REF)
    f._require(_exact(scope.get("universe_rule"), parent.get("universe_change"))
        and _exact(rawdoc.get("original_contract"), scope.get("universe_rule"))
        and _exact(universe.get("universe_change"), scope.get("universe_rule")),
        "ALL_A_CONSENSUS_UNIVERSE_CONTRACT_CHANGED")
    original_ref = {"path": str(_ROOT / _PINS["raw_selector"][0]), "sha256": _PINS["raw_selector"][1]}
    f._require(rawdoc.get("training_source_original24_audit_ref") == original_ref,
               "ALL_A_ORIGINAL_TRAINING_IDENTITY_REQUIRED")
    training = _document(original_ref)
    f._require(_exact(rawdoc["same_model_not_same_universe"], training["same_model_not_same_universe"]),
               "ALL_A_FROZEN_RAW_MODEL_OR_FEATURES_CHANGED")
    return dict(universe_variant="CONSENSUS100",
        application_pool_origin=rawdoc["application_pool_origin"],
        universe_contract_ref=scope["universe_contract_ref"],
        universe_source_ref=dict(_CONSENSUS_SOURCE_REF),
        scope_amendment_ref=plan["scope_amendment_ref"])


def _validate_full_inventory(bindings, states):
    f = _common()
    roles = {"R6:" + r for r in ("buy", "hold", "replace", "duration", "distribution", "distribution_pair")}
    roles.update(("R10:ENTRY", "R10:INCUMBENT", "R10:HAZARD", "R10:JOINT_SEQUENCE", "R7:GROSS"))
    for row in bindings:
        declared, dep = row["required_action_roles"], row["dependency_closure"]
        f._require(isinstance(row["source_group"], str) and bool(row["source_group"])
            and row["runtime_owner"] in ("STATEFUL_OVERLAY", "FINAL_ACTION_OVERLAY", "UNSUPPORTED_ORIGINAL_OWNER")
            and isinstance(declared, list) and len(set(declared)) == len(declared)
            and set(declared).issubset(roles), "ALL_A_FROZEN_RUNTIME_BINDING_REQUIRED")
        f._require(isinstance(dep, dict) and dep.get("status") in ("COMPLETE", "BLOCKED")
            and isinstance(dep.get("state_ids"), list) and len(set(dep["state_ids"])) == len(dep["state_ids"]),
            "ALL_A_DEPENDENCY_CLOSURE_REQUIRED")
        if dep["status"] == "COMPLETE":
            f._require(all(k in states for k in dep["state_ids"])
                and row["runtime_owner"] != "UNSUPPORTED_ORIGINAL_OWNER"
                and "R7:GROSS" not in declared
                and (bool(declared) == (row["runtime_owner"] == "FINAL_ACTION_OVERLAY")),
                "ALL_A_COMPLETE_DEPENDENCIES_REQUIRED")
        else:
            f._require(isinstance(dep.get("reason"), str) and bool(dep["reason"].strip()),
                "ALL_A_UNCLOSED_POLICY_REASON_REQUIRED")


def profile_contract(task_id=TASK, *, pool_variant_id=None, repaired_group_release_ref=None, source_execution_context=None):
    if task_id == REPAIR_TASK:
        raw = _repair_contract(pool_variant_id, source_execution_context=source_execution_context)
        return raw if repaired_group_release_ref is None else _repaired_group_contract(raw, repaired_group_release_ref)
    _common()._require(pool_variant_id is None and repaired_group_release_ref is None and source_execution_context is None, "REPAIR_VARIANT_ON_OLD_TASK")
    if task_id == TASK:
        return frozen_profile_contract()
    f = _common()
    f._require(task_id == ALL_TASK, "DESCRIPTIVE_EXACT_TASK_REQUIRED")
    required = {"plan", "inventory", "old_states", "new_states", "raw_selector", "fusion", "schedule"}
    f._require(set(_ALL_PINS) == required, "ALL_A_PROFILE_NOT_FROZEN")
    refs = {key: {"path": str(_ALL_ROOT / name), "sha256": digest} for key, (name, digest) in _ALL_PINS.items()}
    docs = {key: _document(ref) for key, ref in refs.items()}
    contract = _profile_contract(task_id, refs, docs, legacy=False)
    plan = contract["plan"]
    f._require(plan.get("schema") == "ALL_FROZEN_A_AND_ACTUAL_DEMO_RANDOM2026_DESCRIPTIVE_PLAN_R1"
        and (plan.get("A_scope", {}).get("no_new_algorithm_combinations") is True
             if contract["raw_selector_binding"].get("universe_variant") == "CONSENSUS100"
             else plan.get("A_scope", {}).get("no_new_combinations") is True)
        and all(type(plan.get("constraints", {}).get(k)) is int and plan["constraints"][k] == 0
                for k in ("new_fit", "calibration", "parameter_search", "policy_selection", "new_strategy_combinations")),
        "ALL_A_ORIGINAL_FROZEN_SCIENCE_REQUIRED")
    expected = build_random_schedule(docs["schedule"].get("common_sessions", []),
        as_of=plan["as_of_utc"], candidate_ids=[r["candidate_id"] for r in contract["candidate_bindings"]])
    f._require(_exact(docs["schedule"], expected), "ALL_A_EXACT_RANDOM_SCHEDULE_REQUIRED")
    contract["schedule"] = expected
    return contract


def _contract_as_of(contract):
    return contract["as_of_utc"] if contract["task_id"] == REPAIR_TASK else contract["plan"]["as_of_utc"]


def contract_for_authority(authority):
    """Resolve a sealed variant; old callers keep their original contract."""
    value = _common()._verified(authority)
    if json.loads(value.provenance_json).get("schema") == "REMAINING10_DESCRIPTIVE_AUTHORITY_REF_R1":
        from scripts.research.a2.evaluation.remaining10_profile import contract_for_authority as remaining10_contract
        return remaining10_contract(value)
    if value.task_id != REPAIR_TASK:
        return profile_contract(value.task_id)
    provenance = json.loads(value.provenance_json)
    contract = profile_contract(value.task_id, pool_variant_id=provenance.get("pool_variant_id"),
        repaired_group_release_ref=provenance.get("repaired_group_release_ref"))
    _require_repair_binding(provenance, contract)
    return contract


def _require_repair_binding(document, contract):
    if contract["task_id"] != REPAIR_TASK:
        return
    refs = contract["metadata_refs"]
    _common()._require(document.get("pool_variant_id") == contract["pool_variant_id"]
        and document.get("source_catalog_ref") == refs["source_catalog"]
        and document.get("source_bundle_ref") == refs["source_bundle"]
        and document.get("common_runtime_contract_ref") == refs["common_runtime"]
        and document.get("repaired_group_release_ref") == contract.get("repaired_group_release_ref")
        and document.get("repaired_group_id") == contract.get("repaired_group_id"),
        "REPAIR_VARIANT_SOURCE_BINDING_CHANGED")


_REPAIR_CA_SOURCE_HELPER_REF = {'path': 'D:\\us-tech-quant-cache\\_maintenance\\A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1\\source_compatibility\\ca_exact_source_compatibility.py', 'sha256': '8c8cae73eb88e1bb79a94555c2a0fda44722004c7ba69b41c5a4f85fc4d0c361'}
_REPAIR_CA_SOURCE_PROOF_REF = {'path': 'D:\\us-tech-quant-results\\_maintenance\\A_ALL_REPAIR_AND_CONSENSUS_SENSITIVITY_20261011_R1\\CA_EXACT_SOURCE_COMPATIBILITY_ROOT_SEAL_R1.json', 'sha256': 'e1e98f335241bd6724d75f5c8860501c3d9f3fb853749f86fe71afd4e98eabcb'}


def repair_source_execution_owner(owner_ref, *, task_id=REPAIR_TASK, source_execution_context=None):
    """Exact task source-owner seam; ordinary physical readers remain strict."""
    import importlib.util
    f = _common()
    f._require(task_id == REPAIR_TASK, "EXACT_REPAIR_SOURCE_CONTEXT_REQUIRED")
    ca_path = Path("D:/us-tech-quant/scripts/v22/corporate_action_transition_r1.py").resolve()
    if Path(owner_ref.get("path", "")).resolve() != ca_path:
        if source_execution_context is not None:
            from scripts.research.a2.evaluation.remaining10_profile import verify_unused_fusion_owner, verify_recovered_cbc_owner
            if verify_unused_fusion_owner(owner_ref, source_execution_context) or verify_recovered_cbc_owner(owner_ref, source_execution_context):
                return None
        f._physical(owner_ref)
        return None
    helper_ref, proof_ref = _REPAIR_CA_SOURCE_HELPER_REF, _REPAIR_CA_SOURCE_PROOF_REF
    if source_execution_context is not None:
        from scripts.research.a2.evaluation.remaining10_profile import source_execution_context as remaining10_context
        f._require(_exact(source_execution_context, remaining10_context(source_execution_context.get("research_id"))), "REMAINING10_EXACT_SOURCE_EXECUTION_CONTEXT")
        helper_ref, proof_ref = source_execution_context["helper_ref"], source_execution_context["proof_ref"]
    helper_path = f._physical(helper_ref)
    f._physical(proof_ref)
    spec = importlib.util.spec_from_file_location("_repair_exact_ca_source_selection", helper_path)
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    evidence = owner.verify_declared_source(owner_ref, proof_ref, context_task_id=task_id)
    f._physical(helper_ref)
    f._physical(proof_ref)
    return evidence


def _repair_contract(pool_variant_id, *, source_execution_context=None):
    """Closed RAW-only descendant; no generic metadata-authorized task/variant."""
    f = _common()
    f._require(pool_variant_id in REPAIR_VARIANTS, "REPAIR_EXACT_POOL_VARIANT_REQUIRED")
    f._require(set(_REPAIR_PINS) == {"plan", "inventory", "common_runtime", "source_manifest", "source_catalog"},
        "REPAIR_PROFILE_NOT_FROZEN")
    refs = {k: dict(path=str(_REPAIR_ROOT / name), sha256=digest) for k, (name, digest) in _REPAIR_PINS.items()}
    docs = {k: _document(ref) for k, ref in refs.items()}
    parent = profile_contract(ALL_TASK)
    plan, inventory, runtime, manifest, catalog = (docs[k] for k in
        ("plan", "inventory", "common_runtime", "source_manifest", "source_catalog"))
    f._require(plan.get("schema") == "EXPOSED_2026_REPAIR_AND_CONSENSUS_EVALUATION_PLAN_R1"
        and plan.get("task_id") == REPAIR_TASK and type(plan.get("fit_count_in_frozen_inference")) is int
        and plan["fit_count_in_frozen_inference"] == 0
        and plan.get("evaluation_start") == "2026-01-02" and plan.get("evaluation_end") == "2026-10-08"
        and plan.get("window_count") == 101 and plan.get("expected_raw_accounts") == 2929
        and all(plan.get("original_inputs", {}).get(k + "_ref") == parent["metadata_refs"][k]
                for k in ("plan", "inventory", "schedule"))
        and plan.get("consensus_list_manifest_ref") == refs["source_manifest"], "REPAIR_FROZEN_PLAN_REQUIRED")
    planned = plan.get("variants", [])
    f._require([r.get("pool_variant_id") for r in planned] == list(REPAIR_VARIANTS)
        and manifest.get("task_id") == catalog.get("task_id") == REPAIR_TASK
        and manifest.get("schema") == "CONSENSUS_SENSITIVITY_SOURCE_MANIFEST_R1"
        and catalog.get("schema") == "A_REPAIR_RAW_VARIANT_SOURCE_CATALOG_R1"
        and set(manifest.get("variants", {})) == set(catalog.get("variants", {})) == set(REPAIR_VARIANTS)
        and catalog.get("variant_order") == list(REPAIR_VARIANTS)
        and catalog.get("plan_ref") == refs["plan"]
        and catalog.get("source_manifest_ref") == refs["source_manifest"]
        and catalog.get("same_original_activation_clock") is True
        and catalog.get("original_window_schedule_ref") == parent["metadata_refs"]["schedule"],
        "REPAIR_EXACT_VARIANT_CATALOG_REQUIRED")
    for index, row in enumerate(planned):
        variant = row["pool_variant_id"]
        expected = dict(n=(100, 200, 300, 400)[index] if index < 4 else 100,
            cohort_count=25 if index < 4 else 24, excluded_manager=None if index < 4 else _REPAIR_MANAGERS[index - 4])
        entry = catalog["variants"][variant]
        f._require(all(row.get(k) == manifest["variants"][variant].get(k) == entry.get(k) == v for k, v in expected.items())
            and _exact(row.get("list_source_entry"), manifest["variants"][variant])
            and entry.get("status") in ("READY", "PENDING")
            and (isinstance(entry.get("source_bundle_ref"), dict) if entry["status"] == "READY"
                 else entry.get("source_bundle_ref") is None and bool(entry.get("reason"))),
            "REPAIR_VARIANT_MEMBERSHIP_OR_READINESS_CHANGED")
    selected = catalog["variants"][pool_variant_id]
    f._require(selected["status"] == "READY", "REPAIR_VARIANT_SOURCE_NOT_READY")
    refs["source_bundle"] = selected["source_bundle_ref"]
    bundle = _document(refs["source_bundle"])
    source_entry = manifest["variants"][pool_variant_id]
    f._require(bundle.get("schema") == "CONSENSUS_VARIANT_INPUT_BUNDLE_R1"
        and bundle.get("task_id") == REPAIR_TASK and bundle.get("pool_variant_id") == pool_variant_id
        and bundle.get("plan_ref") == refs["plan"] and bundle.get("source_manifest_ref") == refs["source_manifest"]
        and bundle.get("universe_source_ref") == refs["source_manifest"]
        and bundle.get("universe_variant") == "CONSENSUS_SENSITIVITY"
        and bundle.get("selection_rule") == "MANAGER_COUNT_WEIGHT_SUM"
        and bundle.get("original_window_schedule_ref") == parent["metadata_refs"]["schedule"]
        and _exact(bundle.get("list_source_entry"), source_entry)
        and all(bundle.get(k) == selected[k] for k in ("n", "cohort_count", "excluded_manager"))
        and bundle.get("execution_admission_inherited") is False,
        "REPAIR_VARIANT_SOURCE_BUNDLE_CHANGED")
    parent_rows = _document(parent["metadata_refs"]["inventory"])["candidates"]
    original = [r for r in parent_rows if r["candidate_id"] == "RAW_s10"]
    f._require(inventory.get("task_id") == REPAIR_TASK
        and inventory.get("parent_inventory_ref") == parent["metadata_refs"]["inventory"]
        and len(original) == 1 and _exact(inventory.get("candidates"), original), "REPAIR_ORIGINAL_RAW_ONLY_REQUIRED")
    binding = next(r for r in parent["candidate_bindings"] if r["candidate_id"] == "RAW_s10")
    f._require(runtime.get("schema") == "A_REPAIR_COMMON_MATH_OWNER_CONTRACT_R1"
        and runtime.get("task_id") == REPAIR_TASK and runtime.get("plan_ref") == refs["plan"]
        and runtime.get("candidate_inventory_ref") == refs["inventory"]
        and runtime.get("schedule_ref") == parent["metadata_refs"]["schedule"]
        and runtime.get("cash_decision_ref") == _post_verified_decision_ref(REPAIR_TASK)
        and _exact(runtime.get("raw_specification"), binding["specification"])
        and isinstance(runtime.get("owners"), list) and bool(runtime["owners"]), "REPAIR_COMMON_MATH_CONTRACT_CHANGED")
    source_execution_compatibility = None
    for owner in runtime["owners"]:
        evidence = repair_source_execution_owner(owner, task_id=REPAIR_TASK, source_execution_context=source_execution_context)
        if evidence is not None:
            f._require(source_execution_compatibility is None, "DUPLICATE_COMPATIBLE_SOURCE_OWNER")
            source_execution_compatibility = evidence
    proof = bundle.get("full_pit32_pool", {})
    lists = {k: source_entry[k] for k in ("members_ref", "schedule_ref", "ledger_ref")}
    f._require(proof.get("universe_variant") == "CONSENSUS_SENSITIVITY"
        and proof.get("pool_variant_id") == pool_variant_id
        and proof.get("universe_source_ref") == proof.get("source_manifest_ref") == refs["source_manifest"]
        and all(proof.get(k) == selected[k] for k in ("n", "cohort_count", "excluded_manager"))
        and _exact(proof.get("variant_list_refs"), lists)
        and proof.get("physical_pool_ref") == bundle.get("physical_pool_ref")
        and isinstance(proof.get("origin"), str) and bool(proof["origin"])
        and set(proof.get("sessions", {})) == set(parent["schedule"]["common_sessions"]),
        "REPAIR_FULL_POOL_PROOF_CHANGED")
    for ref in (*lists.values(), bundle["physical_pool_ref"]):
        _physical(ref)
    support = bundle.get("value_holding_support", {})
    support_ref = bundle.get("value_holding_support_manifest_ref")
    support_manifest = _document(support_ref)
    f._require(support.get("origin") == "CONSENSUS_SENSITIVITY_ASOF_HOLDING_VALUE_SUPPORT"
        and support.get("role") == "OFFPOOL_HOLDING_VALUE_CONTINUITY_ONLY"
        and support.get("domain_policy") == "CURRENT_POOL_UNION_PREVIOUSLY_EFFECTIVE_MEMBERS_ASOF"
        and support.get("no_future_first_membership") is True and support.get("no_new_buy_eligibility") is True
        and all(support.get(k) == proof.get(k) for k in ("universe_variant", "pool_variant_id", "n",
            "cohort_count", "excluded_manager", "universe_source_ref", "source_manifest_ref", "feature_order_sha256"))
        and _exact(support.get("variant_list_refs"), lists)
        and _exact(support.get("daily_top100_sessions"), proof["sessions"])
        and isinstance(support.get("sessions"), dict) and set(support["sessions"]) == set(proof["sessions"])
        and support_manifest.get("task_id") == REPAIR_TASK
        and support_manifest.get("pool_variant_id") == pool_variant_id
        and _exact(support_manifest.get("value_holding_support"), support)
        and support_manifest.get("physical_daily_top100_ref") == bundle["physical_pool_ref"]
        and support_manifest.get("physical_support_ref") == bundle.get("physical_value_support_ref")
        and support_manifest.get("physical_support_ref") != bundle["physical_pool_ref"],
        "REPAIR_ASOF_VALUE_SUPPORT_SOURCE_CHANGED")
    _physical(bundle["physical_value_support_ref"])
    support_proof = dict(support, support_manifest_ref=support_ref, source_ref=proof["source_ref"])
    raw = dict(parent["raw_selector_binding"])
    raw.update(universe_variant="CONSENSUS_SENSITIVITY", application_pool_origin=proof["origin"],
        universe_source_ref=refs["source_manifest"], pool_variant_id=pool_variant_id,
        source_catalog_ref=refs["source_catalog"], source_bundle_ref=refs["source_bundle"],
        common_runtime_contract_ref=refs["common_runtime"], variant_list_refs=lists,
        physical_pool_ref=bundle["physical_pool_ref"], n=selected["n"], cohort_count=selected["cohort_count"],
        excluded_manager=selected["excluded_manager"], parent_raw_selector_binding=parent["raw_selector_binding"])
    metadata = dict(parent["metadata_refs"], **refs)
    result = dict(task_id=REPAIR_TASK, metadata_refs=metadata, plan=plan,
        source_catalog_ref=refs["source_catalog"], source_bundle_ref=refs["source_bundle"],
        common_runtime_contract_ref=refs["common_runtime"],
        source_execution_compatibility=source_execution_compatibility,
        as_of_utc=parent["plan"]["as_of_utc"], pool_variant_id=pool_variant_id,
        candidate_bindings=[binding], state_refs={"old_value:ridge": parent["state_refs"]["old_value:ridge"]},
        raw_selector_binding=raw, schedule=parent["schedule"],
        schedule_role="ORIGINAL_WINDOW_RECORDS_ONLY_NEW_RAW_POLICY_SCOPE", full_pit32_pool=proof,
        full_pit32_value_support=support_proof, physical_value_support_ref=bundle["physical_value_support_ref"])


    if source_execution_context is not None:
        f._require(pool_variant_id == "TOP100" and tuple(result["state_refs"]) == ("old_value:ridge",)
            and [r["candidate_id"] for r in result["candidate_bindings"]] == ["RAW_s10"]
            and binding["specification"].get("value_model") == "ridge", "REMAINING10_BASELINE_RAW_RIDGE_ONLY")
    return result


def build_random_schedule(common_sessions, *, as_of, candidate_ids):
    """Reuse original pure PCG64 selection; no model, source or account reads."""
    from scripts.research.a2.evaluation.stateful_frozen_six_path import completed_calendar, random_window_records, SEED
    f = _common()
    f._require(isinstance(candidate_ids, (list, tuple)) and bool(candidate_ids)
        and all(isinstance(cid, str) and cid for cid in candidate_ids)
        and len(set(candidate_ids)) == len(candidate_ids), "ALL_A_COMPLETE_INVENTORY_IDS_REQUIRED")
    dates, now = completed_calendar(common_sessions, as_of=as_of)
    windows, eligible, count = random_window_records(dates)
    return dict(task_id=ALL_TASK, common_sessions=[str(d.date()) for d in dates], windows=windows,
        path_ids=list(candidate_ids), common_end=str(dates[-1].date()), as_of=now.isoformat(),
        random_generator="numpy.random.Generator(PCG64)", seed=SEED,
        eligible_random_start_count=eligible, random_start_count=count,
        account_paths=len(windows)*len(candidate_ids), account_paths_max=101*len(candidate_ids),
        first_day_semantics="CASH_ONLY_SIGNAL_CONTEXT_THEN_NEXT_OPEN;NO_INHERITED_STATE",
        overlapping_starts_not_independent_trials=True)


def load_authority(authority, *, source_execution_context=None):
    if isinstance(authority, dict) and authority.get("schema") == "REMAINING10_DESCRIPTIVE_AUTHORITY_REF_R1":
        from scripts.research.a2.evaluation.remaining10_profile import load_authority as remaining10_authority
        return remaining10_authority(authority)
    if isinstance(authority, dict) and authority.get("schema") == "A_ALL_BENCHMARK_AUTHORITY_REF_R1":
        return load_benchmark_authority(authority)
    f = _common()
    f._require(isinstance(authority, dict) and authority.get("schema") == "A_2026_DESCRIPTIVE_AUTHORITY_REF_R1"
        and authority.get("task_id") in profile_tasks(), "DESCRIPTIVE_EXACT_TASK_REQUIRED")
    task = authority["task_id"]
    bound = _document(authority.get("admission_ref"))
    f._require(bound.get("schema") == "A_2026_DESCRIPTIVE_ACCOUNT_ADMISSION_R1" and bound.get("task_id") == task
        and bound.get("status") == "SOURCE_AND_POLICY_BOUND_FOR_DESCRIPTIVE_EVALUATION", "DESCRIPTIVE_ADMISSION_NOT_BOUND")
    f._require(all(bound.get(k) is False for k in ("strict_PIT_promotion_eligible", "production_qualified", "finalist_selected"))
        and type(bound.get("new_fit")) is int and bound["new_fit"] == 0, "DESCRIPTIVE_RESEARCH_ONLY_NO_FIT")
    contract = profile_contract(task, pool_variant_id=authority.get("pool_variant_id"),
        repaired_group_release_ref=authority.get("repaired_group_release_ref"), source_execution_context=source_execution_context)
    _require_repair_binding(authority, contract)
    _require_repair_binding(bound, contract)
    f._require(bound.get("plan_ref") == contract["metadata_refs"]["plan"]
        and bound.get("candidate_manifest_ref") == contract["metadata_refs"]["inventory"], "A94_PINNED_METADATA_REQUIRED")
    bindings = contract["candidate_bindings"]
    ids = tuple(r["candidate_id"] for r in bindings)
    f._require(bound.get("allowed_path_ids") == list(ids) and _exact(bound.get("candidate_bindings"), bindings), "A94_FULL_POLICY_BINDING_CHANGED")
    f._require(bound.get("state_refs") == contract["state_refs"], "A94_FULL_STATE_BINDING_CHANGED")
    f._require(bound.get("initial_cash_usd") == 3000 and bound.get("initial_holdings") == []
        and bound.get("initial_receivables") == [] and bound.get("fresh_account") is True, "DESCRIPTIVE_FRESH_USD3000_REQUIRED")
    as_of = pd.Timestamp(bound.get("as_of"))
    expected_as_of = pd.Timestamp(_contract_as_of(contract))
    f._require(not pd.isna(as_of) and as_of.tzinfo is not None and as_of == expected_as_of, "A94_PINNED_AS_OF_REQUIRED")
    windows = bound.get("windows")
    if task == TASK:
        f._require(isinstance(windows, list) and len(windows) == 1 and isinstance(windows[0], dict)
            and isinstance(windows[0].get("window_id"), str) and bool(windows[0]["window_id"])
            and windows[0]["window_id"] == authority.get("window_id"), "A94_SINGLE_COMMON_WINDOW_REQUIRED")
        window = windows[0]
    else:
        schedule = contract["schedule"]
        f._require(bound.get("schedule_ref") == contract["metadata_refs"]["schedule"]
            and _exact(windows, schedule["windows"]), "ALL_A_EXACT_RANDOM_SCHEDULE_REQUIRED")
        matches = [w for w in windows if w["window_id"] == authority.get("window_id")]
        f._require(len(matches) == 1, "ALL_A_FROZEN_WINDOW_REQUIRED")
        window = matches[0]
    start, end = f._day(window.get("start")), f._day(window.get("end"))
    history = f._day(bound.get("feature_history_start"))
    f._require(pd.Timestamp("2026-01-01") <= start < end < pd.Timestamp("2027-01-01")
        and (end + pd.Timedelta(hours=16)).tz_localize("America/New_York") <= as_of, "DESCRIPTIVE_INCOMPLETE_SESSION")
    f._require(pd.Timestamp("2023-01-01") <= history <= start, "DESCRIPTIVE_FEATURE_CONTEXT_BOUNDARY")
    sources = bound.get("source_refs")
    f._require(isinstance(sources, dict) and set(sources) == set(f.SOURCE_GROUPS), "DESCRIPTIVE_SOURCE_SLOTS_UNBOUND")
    # Read the small declared scope BEFORE touching any potentially mixed-year view.
    qualification = _document(bound.get("source_qualification_ref"))
    f._require(qualification.get("schema") == "A_2026_DESCRIPTIVE_SOURCE_QUALIFICATION_R1"
        and qualification.get("task_id") == task and qualification.get("status") == "QUALIFIED_FOR_DECLARED_RESEARCH_SCOPE"
        and qualification.get("source_refs") == sources and qualification.get("as_of") == bound["as_of"], "DESCRIPTIVE_SOURCE_QUALIFICATION_UNBOUND")
    _require_repair_binding(qualification, contract)
    if task == REPAIR_TASK:
        f._require(_exact(qualification.get("full_pit32_pool"), contract["full_pit32_pool"]), "REPAIR_FULL_POOL_PROOF_CHANGED")
        f._require(_exact(qualification.get("full_pit32_value_support"), contract["full_pit32_value_support"]),
            "REPAIR_VALUE_SUPPORT_PROOF_CHANGED")
    f._require(qualification.get("common_calendar_start") == (str(start.date()) if task == TASK else contract["schedule"]["windows"][0]["start"])
        and qualification.get("common_calendar_end") == str(end.date())
        and qualification.get("common_calendar_selection") == "SOURCE_AVAILABILITY_AND_ORIGINAL_CALENDAR_ONLY",
        "A94_SOURCE_ONLY_COMMON_CALENDAR_REQUIRED")
    f._require(_exact(qualification.get("raw_selector_binding"), contract["raw_selector_binding"]),
        "A94_ORIGINAL_RAW_SELECTOR_REQUIRED")
    groups, slices = qualification.get("groups"), qualification.get("source_slices")
    ready_ids = _source_ready_policies(qualification, sources, ids,
        bindings=None if task == TASK else bindings)
    decision_ref = _accounting_decision(bound, contract)
    f._require(isinstance(slices, dict) and set(slices) == set(f.SOURCE_GROUPS), "A94_BOUNDED_SOURCE_VIEWS_REQUIRED")
    for key, ref in sources.items():
        scope = slices[key]
        f._require(isinstance(scope, dict) and scope.get("source_ref") == ref
            and scope.get("no_2027_content") is True and scope.get("view_only") is True,
            "A94_BOUNDED_SOURCE_VIEWS_REQUIRED")
        first, last = f._day(scope.get("content_start")), f._day(scope.get("content_end"))
        f._require(history <= first <= last <= end, "A94_SOURCE_SCOPE_OUTSIDE_WINDOW")
        if scope.get("clock_role") == "POST_VERIFIED_ACCOUNTING_ONLY":
            f._require(key == "corporate_actions" and decision_ref is not None,
                       "A94_SOURCE_SCOPE_OUTSIDE_WINDOW")
            captured = pd.Timestamp(scope.get("captured_at"))
            f._require(decision_ref is not None and scope.get("available_at") is None
                and scope.get("historical_available_at_bound") is False
                and not pd.isna(captured) and captured.tzinfo is not None,
                "A94_POST_VERIFIED_CAPTURE_IS_NOT_HISTORICAL_AVAILABILITY")
        elif scope.get("clock_role") == "FROZEN_HISTORY_RESEARCH_OBSERVATIONS_NOT_HISTORICAL_DELIVERY_CERTIFICATION":
            # The original descriptive plan permits frozen historical observations;
            # this explicit role does not certify historical API delivery or H5.
            f._require(key != "corporate_actions"
                and scope.get("source_clock_semantics") == scope["clock_role"]
                and scope.get("available_at") is None
                and scope.get("historical_available_at_bound") is False
                and qualification.get("original_plan_ref") == contract["metadata_refs"]["plan"]
                and all(qualification.get(k) is False for k in (
                    "strict_PIT_promotion_eligible", "production_qualified", "finalist_selected"))
                and type(qualification.get("new_fit")) is int and qualification["new_fit"] == 0,
                "A94_FROZEN_HISTORY_RESEARCH_ROLE_REQUIRED")
            facts = scope.get("source_observation_fact_refs")
            f._require(isinstance(facts, list) and bool(facts),
                       "A94_FROZEN_HISTORY_SOURCE_FACTS_REQUIRED")
            for fact in facts:
                _physical(fact)
        else:
            f._require(scope.get("historical_available_at_bound") is not False,
                       "A94_SOURCE_SCOPE_OUTSIDE_WINDOW")
            available = pd.Timestamp(scope.get("available_at"))
            f._require(not pd.isna(available) and available.tzinfo is not None
                and available <= as_of, "A94_SOURCE_SCOPE_OUTSIDE_WINDOW")
    for ref in sources.values():
        _physical(ref)
    cash_binding = f._load_post_verified_binding(bound, sources, task, "research_cash_reconstruction")
    terminal_binding = f._load_post_verified_binding(bound, sources, task, "research_terminal_reconstruction")
    _physical(contract["raw_selector_binding"]["model_ref"])
    for state in contract["state_refs"].values():
        _physical(state["model_ref"])
        _document(state["receipt_ref"])
    provenance = dict(schema=authority["schema"], task_id=task, admission_ref=authority["admission_ref"],
        plan_ref=bound["plan_ref"], candidate_manifest_ref=bound["candidate_manifest_ref"],
        metadata_refs=contract["metadata_refs"], window_id=authority["window_id"],
        source_qualification_ref=bound["source_qualification_ref"], source_refs=sources,
        start=str(start.date()), end=str(end.date()), as_of=as_of.isoformat(),
        candidate_bindings=bindings, raw_selector_binding=contract["raw_selector_binding"],
        state_closure_scope=("111_POLICY_VALUE_RISK_R6_R10_SCALER_STATES_PLUS_SEPARATE_RAW_CLASSIFIER" if task == TASK
            else "EXACT_PINNED_FULL_INVENTORY_CLOSURE_PLUS_SEPARATE_RAW_CLASSIFIER"),
        strict_PIT_promotion_eligible=False, production_qualified=False,
        finalist_selected=False, new_fit=0, source_gate_level="DECLARED_SOURCE_CUSTODY_NOT_PIT_CERTIFICATION",
        runtime_full_policy_validation="CONTROLLER_MUST_CALL_validate_descriptive_policy_BEFORE_OVERLAY",
        source_clock_roles={key: scope.get("clock_role", "HISTORICAL_AVAILABLE_AT_BOUND")
                            for key, scope in slices.items()},
        source_ready_policy_ids=ready_ids,
        candidate_source_qualification=qualification.get("candidate_source_qualification"),
        post_verified_accounting_decision_ref=decision_ref)
    if task == REPAIR_TASK:
        provenance.update(pool_variant_id=contract["pool_variant_id"], source_catalog_ref=contract["metadata_refs"]["source_catalog"],
            source_bundle_ref=contract["metadata_refs"]["source_bundle"], common_runtime_contract_ref=contract["metadata_refs"]["common_runtime"],
            repaired_group_id=contract.get("repaired_group_id"), repaired_group_release_ref=contract.get("repaired_group_release_ref"))
    return f.ValidatedDescriptiveAuthority(task, authority["window_id"], start, end, as_of, history, ids,
        json.dumps(provenance, sort_keys=True, allow_nan=False), f._SEAL,
        research_cash_reconstruction_json=cash_binding,
        research_terminal_reconstruction_json=terminal_binding,
        source_ready_policy_ids=tuple(ready_ids),
        _source_policy_custody=f._SourcePolicyCustody(task, tuple(ready_ids), f._SEAL))


def _specs(value):
    return {r["candidate_id"]: r["specification"] for r in json.loads(value.provenance_json)["candidate_bindings"]}


def validate_policy(value, candidates):
    """Actual overlay policy dicts must equal their full original specs; no extras."""
    f = _common()
    f._require(isinstance(candidates, (list, tuple)) and bool(candidates)
        and all(isinstance(c, dict) for c in candidates), "A94_FULL_RUNTIME_POLICY_REQUIRED")
    ids = tuple(c.get("candidate_id") for c in candidates)
    f._require(len(set(ids)) == len(ids) and ids == tuple(p for p in value.allowed_path_ids if p in ids), "DESCRIPTIVE_POLICY_ORDER_CHANGED")
    specs = _specs(value)
    f._require(all(_exact(c, specs[i]) for c, i in zip(candidates, ids)), "A94_RUNTIME_FULL_SPEC_CHANGED")
    provenance = json.loads(value.provenance_json)
    f._require(all(i in provenance.get("source_ready_policy_ids", value.allowed_path_ids) for i in ids),
               "A94_RUNTIME_POLICY_SOURCE_NOT_QUALIFIED")
    provenance["runtime_policy_ids"] = list(ids)
    return replace(value, provenance_json=json.dumps(provenance, sort_keys=True, allow_nan=False), runtime_policy_ids=ids)


def require_runtime_policy(value, ids):
    value = _common()._verified(value)
    verified = value.runtime_policy_ids
    _common()._require(bool(ids) and all(i in verified for i in ids), "A94_FULL_RUNTIME_POLICY_VALIDATION_REQUIRED")
    ready = value.source_ready_policy_ids or value.allowed_path_ids
    _common()._require(all(i in ready for i in ids), "A94_RUNTIME_POLICY_SOURCE_NOT_QUALIFIED")
    return value


def validate_account_friction(value, ids, friction):
    require_runtime_policy(value, ids)
    specs = _specs(value)
    _common()._require(isinstance(friction, dict) and all(_exact(friction, specs[i]["execution_friction"]) for i in ids),
        "A94_ORIGINAL_FRICTION_BATCH_REQUIRED")
    return value


_BENCHMARK_SOURCE_REF = {
    "path": "D:/us-tech-quant-backtests/A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1/20261009T040010+0000_ebc89ace/derived/consensus_source_extension/SOURCE_BUNDLE.json",
    "sha256": "99175c6894f73c425a7715417157f3fe23c52e1cd30e56a930e083e49803d5da",
}


def benchmark_candidates(contract):
    """Exact two original ETF policies; the 175-policy inventory is untouched."""
    f = _common()
    f._require(contract["task_id"] == ALL_TASK
        and contract["raw_selector_binding"].get("universe_variant") == "CONSENSUS100"
        and contract["plan"].get("metrics", {}).get("benchmark_one_way_bps") == 10
        and contract["plan"].get("planned_denominator", {}).get("benchmarks") == 202,
        "ALL_A_EXACT_TWO_BENCHMARK_SCOPE_REQUIRED")
    from scripts.research.a2.evaluation.stateful_frozen_six_path import load_frozen_policies
    rows = load_frozen_policies(contract["raw_selector_binding"]["universe_contract_ref"])[4:]
    f._require([r["candidate_id"] for r in rows] == list(f.PATH_IDS[4:]),
        "ALL_A_EXACT_TWO_BENCHMARK_SCOPE_REQUIRED")
    return rows


def load_benchmark_authority(authority):
    """Closed two-ETF descendant of verified sources, never an A-model capability."""
    f = _common()
    f._require(authority.get("schema") == "A_ALL_BENCHMARK_AUTHORITY_REF_R1"
        and authority.get("task_id") == ALL_TASK, "ALL_A_BENCHMARK_TASK_REQUIRED")
    bound = _document(authority.get("admission_ref"))
    contract = profile_contract(ALL_TASK)
    f._require(bound.get("schema") == "A_ALL_BENCHMARK_ACCOUNT_ADMISSION_R1"
        and bound.get("task_id") == ALL_TASK
        and bound.get("plan_ref") == contract["metadata_refs"]["plan"]
        and bound.get("schedule_ref") == contract["metadata_refs"]["schedule"]
        and bound.get("windows") == contract["schedule"]["windows"]
        and bound.get("account_execution_allowed") is True
        and all(bound.get(k) is False for k in ("strict_PIT_promotion_eligible", "production_qualified", "finalist_selected"))
        and type(bound.get("new_fit")) is int and bound["new_fit"] == 0,
        "ALL_A_BENCHMARK_FROZEN_SCOPE_REQUIRED")
    source_ref = bound.get("source_bundle_ref")
    f._require(isinstance(source_ref, dict) and source_ref.get("sha256") == _BENCHMARK_SOURCE_REF["sha256"]
        and _physical(source_ref) == _physical(_BENCHMARK_SOURCE_REF), "ALL_A_BENCHMARK_SOURCE_CHANGED")
    source = _document(source_ref)
    f._require(source.get("task_id") == ALL_TASK and source.get("universe_variant") == "CONSENSUS100"
        and source.get("plan_ref") == bound["plan_ref"], "ALL_A_BENCHMARK_SOURCE_CHANGED")
    base_ref = bound.get("verified_source_authority_ref")
    f._require(isinstance(base_ref, dict) and base_ref.get("schema") == "A_2026_DESCRIPTIVE_AUTHORITY_REF_R1"
        and base_ref.get("task_id") == ALL_TASK and base_ref.get("window_id") == "MAIN",
        "ALL_A_BENCHMARK_VERIFIED_SOURCE_AUTHORITY_REQUIRED")
    base = load_authority(base_ref)
    provenance = json.loads(base.provenance_json)
    sources = provenance["source_refs"]
    f._require(sources["corporate_actions"] == source["account_catalog_ref"]
        and _document(sources["action_inputs"]).get("source_bundle_ref") == source_ref,
        "ALL_A_BENCHMARK_SOURCE_AUTHORITY_MISMATCH")
    q = _document(bound.get("source_qualification_ref"))
    f._require(q.get("schema") == "A_ALL_TWO_BENCHMARK_SOURCE_QUALIFICATION_R1"
        and q.get("task_id") == ALL_TASK and q.get("source_bundle_ref") == source_ref
        and q.get("source_refs") == sources
        and isinstance(q.get("groups"), dict) and set(q["groups"]) == set(f.SOURCE_GROUPS)
        and all(q["groups"][key] is True for key in f.SOURCE_GROUPS)
        and q.get("action_inputs_scope") == "ORIGINAL_BUY_AND_HOLD_NO_MODEL_INPUT"
        and q.get("common_sessions") == contract["schedule"]["common_sessions"]
        and q.get("bars_ref") == source["bars_ref"]
        and q.get("fresh_cash_usd") == 3000 and q.get("initial_holdings") == []
        and q.get("initial_receivables") == [] and q.get("one_way_bps") == 10
        and q.get("terminal_liquidation") is False,
        "ALL_A_BENCHMARK_SOURCE_QUALIFICATION_REQUIRED")
    for fact in q.get("source_fact_refs", []):
        _physical(fact)
    f._require(bool(q.get("source_fact_refs")), "ALL_A_BENCHMARK_PHYSICAL_FACTS_REQUIRED")
    candidates = benchmark_candidates(contract)
    ids = tuple(f.PATH_IDS[4:])
    f._require(bound.get("allowed_path_ids") == list(ids) and _exact(bound.get("candidates"), candidates),
        "ALL_A_EXACT_TWO_BENCHMARK_SCOPE_REQUIRED")
    provenance.update(schema=authority["schema"], admission_ref=authority["admission_ref"],
        source_qualification_ref=bound["source_qualification_ref"], benchmark_only=True,
        benchmark_schedule=contract["schedule"], source_bundle_ref=source_ref,
        candidate_bindings=[dict(candidate_id=r["candidate_id"], specification=r) for r in candidates],
        source_ready_policy_ids=list(ids), runtime_policy_ids=[],
        original_source_authority_ref=base_ref, benchmark_models_required=False,
        benchmark_source_completeness_unknown=q.get("source_completeness_unknown", True))
    value = replace(base, allowed_path_ids=ids, runtime_policy_ids=(),
        provenance_json=json.dumps(provenance, sort_keys=True, allow_nan=False),
        source_ready_policy_ids=ids, _source_policy_custody=f._SourcePolicyCustody(ALL_TASK, ids, f._SEAL))
    return benchmark_window_authority(value, authority.get("window_id"))


def benchmark_window_authority(value, window_id):
    """Project only a previously admitted exact frozen benchmark window, no IO."""
    f = _common(); value = f._verified(value)
    p = json.loads(value.provenance_json)
    f._require(value.task_id == ALL_TASK and p.get("benchmark_only") is True
        and value.allowed_path_ids == tuple(f.PATH_IDS[4:]), "ALL_A_BENCHMARK_CAPABILITY_REQUIRED")
    matches = [w for w in p["benchmark_schedule"]["windows"] if w["window_id"] == window_id]
    f._require(len(matches) == 1, "ALL_A_FROZEN_WINDOW_REQUIRED")
    w = matches[0]; start, end = f._day(w["start"]), f._day(w["end"])
    p.update(window_id=window_id, start=str(start.date()), end=str(end.date()))
    return replace(value, window_id=window_id, start=start, end=end,
        provenance_json=json.dumps(p, sort_keys=True, allow_nan=False))


def _repaired_group_contract(raw_contract, release_ref):
    """Finite original missing-group closure, distinct from the RAW-only arm."""
    from copy import deepcopy
    from scripts.research.a2.training.stateful_values import digest
    f = _common()
    f._require(raw_contract["pool_variant_id"] == "TOP100", "REPAIR_GROUP_TOP100_ONLY")
    recovery_ref = dict(path=str(_REPAIR_ROOT / "MISSING_COMPONENT_CONTRACT.json"),
        sha256="f2be0d964ae9141b354ff0fbcfcc642ac940927d9f39274e58eff44155e18cf5")
    inventory_ref = dict(path=str(_REPAIR_ROOT / "REPAIRED_CANDIDATE_INVENTORY_R1.json"),
        sha256="a1f19af2cb01c5908779b7515e970e1b3009aa5a3c66c86b1e57fdb806cc1174")
    recovery, inventory, release = (_document(x) for x in (recovery_ref, inventory_ref, release_ref))
    f._require(recovery.get("schema") == "A_MISSING_COMPONENT_CONTRACT_R1"
        and recovery.get("task_id") == inventory.get("task_id") == release.get("task_id") == REPAIR_TASK
        and release.get("schema") == "A_REPAIR_ORIGINAL_GROUP_RELEASE_R1"
        and release.get("status") == "ROOT_RELEASED_ORIGINAL_COMPONENT_GROUP"
        and release.get("plan_ref") == raw_contract["metadata_refs"]["plan"]
        and release.get("recovery_contract_ref") == recovery_ref
        and release.get("candidate_inventory_ref") == inventory_ref
        and release.get("pool_variant_id") == "TOP100"
        and all(release.get(k) == raw_contract[k] for k in
            ("source_catalog_ref", "source_bundle_ref", "common_runtime_contract_ref"))
        and release.get("new_fit_in_inference") == 0 and type(release.get("new_fit_in_inference")) is int,
        "REPAIR_EXACT_GROUP_RELEASE_REQUIRED")
    parent = _document(recovery["inventory_ref"])
    allowed = [r for r in parent["candidates"] if any(c["candidate_id"] == r["candidate_id"]
        and c["classification"] != "MISSING_EVENT_CENSOR_SCIENTIFIC_SCHEMA" for c in recovery["components"])]
    f._require(len(allowed) == 19 and _exact(inventory.get("candidates"), allowed)
        and tuple(r["candidate_id"] for r in allowed if r["runtime_owner"] == "FINAL_ACTION_OVERLAY") == _REPAIR_ACCOUNT_GROUPS,
        "REPAIR_KNOWN19_INVENTORY_CHANGED")
    cid = release.get("candidate_id")
    matches = [r for r in allowed if r["candidate_id"] == cid]
    f._require(len(matches) == 1, "REPAIR_ORIGINAL_GROUP_REQUIRED")
    original = matches[0]
    definition = next(c for c in recovery["components"] if c["candidate_id"] == cid)
    f._require(original.get("runtime_owner") == definition.get("original_runtime_owner") == "FINAL_ACTION_OVERLAY",
        "REPAIR_ORIGINAL_ACCOUNT_DECODER_UNAVAILABLE")
    closure = _document(release.get("closure_ref"))
    f._require(closure.get("schema") == "ORIGINAL_MISSING_CANDIDATE_COMPONENT_CLOSURE_R1"
        and closure.get("task_id") == REPAIR_TASK and closure.get("candidate_id") == cid
        and closure.get("contract_ref") == recovery_ref
        and closure.get("status") == "MODEL_DEPENDENCY_CLOSURE_COMPLETE"
        and closure.get("model_dependencies_complete") is True
        and _exact(closure.get("frozen_bundle"), definition["frozen_bundle"])
        and _exact(definition["frozen_bundle"], original["specification"]["frozen_bundle"])
        and [r.get("slot_id") for r in closure.get("nodes", [])] == original["model_ids"],
        "REPAIR_ORIGINAL_MODEL_BUNDLE_CHANGED")
    expected_scalers = list(dict.fromkeys(s for n in definition["nodes"] for s in n.get("external_scaler_dependencies", [])))
    f._require([r.get("slot_id") for r in closure.get("scalers", [])] == expected_scalers,
        "REPAIR_SHARED_SCALER_CLOSURE_CHANGED")
    newer = _document(release.get("new_states_ref"))
    old_newer = _document(raw_contract["metadata_refs"]["new_states"])
    f._require(newer.get("schema") == "A_REPAIR_GROUP_FROZEN_STATE_DEPENDENCIES_R1"
        and newer.get("task_id") == REPAIR_TASK and newer.get("candidate_id") == cid
        and newer.get("closure_ref") == release["closure_ref"]
        and newer.get("authority_refs") == old_newer["authority_refs"], "REPAIR_NEW_STATE_AUTHORITY_CHANGED")
    rows, scales, states, views = [], [], {}, {}
    for is_scaler, entries in ((False, closure["nodes"]), (True, closure.get("scalers", []))):
        for entry in entries:
            sid = entry["slot_id"]
            node = next(n for n in (recovery["shared_scalers"] if is_scaler else definition["nodes"]) if n["slot_id"] == sid)
            failure_ref = node["receipt_ref"] if is_scaler else node["original_failure_ref"]
            failure = _document(failure_ref)
            mr, rr = entry.get("model_ref"), entry.get("receipt_ref")
            model_path, receipt_path = _physical(mr), _physical(rr)
            receipt = _document(rr)
            existing = node.get("model_ref") if is_scaler else node.get("existing_model_ref")
            recovered = not (existing is not None and mr == existing and rr == failure_ref)
            if recovered:
                f._require(receipt.get("schema") in ("ORIGINAL_L20_COMPONENT_RECOVERY_R1", "ORIGINAL_COMPONENT_RECOVERY_FIT_R1")
                    and receipt.get("task_id") == REPAIR_TASK and receipt.get("contract_ref") == recovery_ref
                    and receipt.get("original_failure_ref") == failure_ref and receipt.get("model_ref") == mr
                    and all(type(receipt.get(k)) is int and receipt[k] == 0 for k in ("model_predict", "account_replay"))
                    and type(receipt.get("fit_units")) is int and receipt.get("fit_units") == 1, "REPAIR_RECOVERED_RECEIPT_IDENTITY_CHANGED")
                source_refs = receipt.get("original_source_refs", receipt.get("source_refs"))
                f._require(source_refs == recovery["original_source_refs"], "REPAIR_ORIGINAL_FIT_SOURCE_CHANGED")
                for ref in source_refs: f._physical(ref)
                f._physical(receipt["driver_ref"])
                inp = _document(receipt.get("input_ref"))
                tup = receipt.get("scientific_tuple", receipt.get("original_scientific_tuple"))
                f._require(inp.get("new_fit") == 0 and type(inp.get("new_fit")) is int and isinstance(tup, dict)
                    and pd.Timestamp(inp["signal_max"]) < pd.Timestamp("2025-01-01")
                    and pd.Timestamp(inp["maturity_max"]) < pd.Timestamp("2025-01-01"), "REPAIR_FROZEN_TRAINING_INPUT_REQUIRED")
                if receipt["schema"] == "ORIGINAL_L20_COMPONENT_RECOVERY_R1":
                    keys = ("slot_id", "family", "capacity", "seed", "group", "lookback", "horizon", "year", "bucket", "objective", "cutoff_exclusive", "prefix")
                    f._require(_exact(receipt.get("original_failed_spec"), {k:failure[k] for k in keys})
                        and all(tup.get(k) == failure[k] for k in keys)
                        and inp.get("task_id") == REPAIR_TASK and inp.get("contract_ref") == recovery_ref
                        and inp.get("status") == "ORIGINAL_L20_SCALER_TRANSFORM_PREPARED"
                        and pd.Timestamp(inp["signal_max"]) < pd.Timestamp("2025-01-01")
                        and pd.Timestamp(inp["maturity_max"]) < pd.Timestamp("2025-01-01")
                        and tup.get("features") == inp.get("features")
                        and all(tup.get(k+"_sha256") == inp["arrays"][k]["array_sha256"] for k in ("x","target","dates","weights"))
                        and tup.get("x_shape") == inp["arrays"]["x"]["shape"]
                        and tup.get("target_shape") == inp["arrays"]["target"]["shape"], "REPAIR_ORIGINAL_L20_INPUT_CHANGED")
                    scaler_entry = next(e for e in closure["scalers"] if e["slot_id"] == "HAZARD_SEQUENCE_JOINTSEQ_L20_2025_SCALER")
                    f._require(inp.get("scaler_model_ref") == scaler_entry["model_ref"]
                        and inp.get("scaler_receipt_ref") == scaler_entry["receipt_ref"], "REPAIR_L20_SCALER_INPUT_CHANGED")
                    _physical(inp["source_input_ref"])
                    f._require(inp["source_input_ref"] == _document(scaler_entry["receipt_ref"])["input_ref"],
                        "REPAIR_L20_ORIGINAL_SCALER_INPUT_CHANGED")
                    f._require(receipt.get("scientific_tuple_sha256") == digest(tup), "REPAIR_RECOVERY_TUPLE_CHANGED")
                else:
                    expected = node["scientific_tuple"] if is_scaler else node["original_scientific_tuple"]
                    f._require(_exact(tup, expected)
                        and inp.get("status") == ("ORIGINAL_SCALER_INPUT_COMMITMENTS_EXACT" if is_scaler else "ORIGINAL_INPUT_COMMITMENTS_EXACT"),
                        "REPAIR_ORIGINAL_TRAINING_TUPLE_CHANGED")
                    f._require((inp.get("original_scaler_ref") == failure_ref if is_scaler else sid in inp.get("slot_ids", ()))
                        and inp.get("features") == tup.get("features")
                        and all(inp["arrays"][k]["array_sha256"] == tup[k+"_sha256"] for k in ("x","dates","weights"))
                        and inp["arrays"]["x"]["shape"] == tup["x_shape"], "REPAIR_ORIGINAL_INPUT_COMMITMENTS_CHANGED")
                    if not is_scaler:
                        f._require(inp["arrays"]["target"]["array_sha256"] == tup["target_sha256"]
                            and inp["arrays"]["target"]["shape"] == tup["target_shape"]
                            and inp.get("scaler_ref") in [e["model_ref"] for e in closure["scalers"]],
                            "REPAIR_ORIGINAL_INPUT_SCALER_OR_TARGET_CHANGED")
                if not is_scaler:
                    f._require(_exact(receipt.get("metadata", {}).get("parameters"), node["original_model_configuration"])
                        and ("epochs" not in node["original_model_configuration"]
                            or receipt["metadata"].get("epochs") == node["original_model_configuration"]["epochs"]
                                and receipt["metadata"].get("final_epoch_only") is True), "REPAIR_ORIGINAL_FIXED_MODEL_CONFIGURATION_CHANGED")
            else:
                tup = receipt.get("scientific_tuple")
                f._require(_exact(tup, node.get("scientific_tuple") if is_scaler else node.get("original_scientific_tuple")),
                    "REPAIR_ORIGINAL_EXISTING_TUPLE_CHANGED")
            f._require(receipt.get("status") == "TRAINED" and tup.get("year") == 2025
                and tup.get("slot_id") == sid and tup.get("design_sha256") == definition["original_contract_ref"]["sha256"]
                and (is_scaler or tup.get("cutoff_exclusive") == "2025-01-01")
                and model_path.parent == receipt_path.parent, "REPAIR_ORIGINAL_ACTION_STATE_CHANGED")
            row = {k:tup[k] for k in ("slot_id","year","family","capacity","seed","objective")}
            row.update(stage="R10", status="TRAINED", group=tup.get("group", "JOINT_SEQUENCE"),
                lookback=tup.get("lookback", definition["frozen_bundle"].get("lookback")), feature_order=tup["features"],
                model_path=mr["path"], model_sha256=mr["sha256"], receipt_ref=rr)
            (scales if is_scaler else rows).append(row)
            key = ("new_scaler:" if is_scaler else "new_model:") + sid
            states[key] = dict(model_ref=mr, receipt_ref=rr)
            if recovered:
                views[key] = dict(status="TRAINED", year=2025, model_path=mr["path"], model_sha256=mr["sha256"],
                    scientific_tuple=tup, scientific_tuple_sha256=digest(tup))
    def required_rows(actual, expected):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            all(_exact(a.get(k), v) for k,v in e.items()) for a,e in zip(actual, expected))
    f._require(required_rows(newer.get("model_states"), rows) and required_rows(newer.get("external_scaler_states"), scales)
        and newer.get("state_refs") == states, "REPAIR_PHYSICAL_STATE_METADATA_CHANGED")
    old_candidate = next(r for r in old_newer["candidate_rows"] if r["candidate_id"] == cid)
    expected_candidate = dict(old_candidate, external_scaler_ids=expected_scalers)
    f._require(len(newer.get("candidate_rows", [])) == 1
        and all(_exact(newer["candidate_rows"][0].get(k), v) for k,v in expected_candidate.items()
            if k not in ("serialized_pre2026_state_evidence", "full_runtime_admission")), "REPAIR_ORIGINAL_ACTION_CANDIDATE_CHANGED")
    binding = {k:deepcopy(original[k]) for k in ("candidate_id","scientific_tuple_sha256","specification","source_group","runtime_owner","required_action_roles","lookback")}
    binding["dependency_closure"] = dict(status="COMPLETE", state_ids=list(states), reason=None)
    result = dict(raw_contract)
    result.update(repaired_group_id=cid, repaired_group_release_ref=release_ref,
        recovery_accounting_decision_ref=_post_verified_decision_ref(REPAIR_TASK, recovered=True),
        recovered_state_receipt_views=views, candidate_bindings=[binding],
        state_refs={**raw_contract["state_refs"], **states})
    result["metadata_refs"] = dict(raw_contract["metadata_refs"], inventory=inventory_ref,
        recovery_contract=recovery_ref, recovery_release=release_ref, new_states=release["new_states_ref"])
    return result


def repaired_group_inventory_projection_required(value):
    """Only single repaired groups need projection; numerical four and Cox three keep all rows."""
    f = _common()
    f._verified(value)
    provenance = json.loads(value.provenance_json)
    if (provenance.get("schema") == "REMAINING10_DESCRIPTIVE_AUTHORITY_REF_R1"
            and provenance.get("research_id") in ("A_TOP100_SOLVER_CONTINUATION_20261012_R1",
                "A_TOP100_COX_LANDMARK_H5_CONFIRMATION_20261012_R1")):
        from scripts.research.a2.evaluation.remaining10_profile import numerical_calendar_capable, cox_calendar_capable
        cox = provenance["research_id"] == "A_TOP100_COX_LANDMARK_H5_CONFIRMATION_20261012_R1"
        f._require((cox_calendar_capable(value) if cox else numerical_calendar_capable(value)),
            "REMAINING10_COX_INVENTORY_SCOPE_REQUIRED" if cox else "REMAINING10_NUMERICAL_INVENTORY_SCOPE_REQUIRED")
        return False
    return repaired_group_calendar_capable(value)


def repaired_group_calendar_capable(value):
    """No IO; only an already validated, single original repaired action group."""
    f = _common()
    f._verified(value)
    if value.task_id != REPAIR_TASK:
        return False
    provenance = json.loads(value.provenance_json)
    if provenance.get("schema") == "REMAINING10_DESCRIPTIVE_AUTHORITY_REF_R1":
        from scripts.research.a2.evaluation.remaining10_profile import numerical_calendar_capable, cox_calendar_capable
        return numerical_calendar_capable(value) or cox_calendar_capable(value)
    cid = provenance.get("repaired_group_id")
    refs = provenance.get("metadata_refs", {})
    rows = provenance.get("candidate_bindings", [])
    release = provenance.get("repaired_group_release_ref")
    return (cid in _REPAIR_ACCOUNT_GROUPS and value.allowed_path_ids == value.runtime_policy_ids == (cid,)
        and provenance.get("pool_variant_id") == "TOP100"
        and refs.get("recovery_contract") == dict(path=str(_REPAIR_ROOT / "MISSING_COMPONENT_CONTRACT.json"),
            sha256="f2be0d964ae9141b354ff0fbcfcc642ac940927d9f39274e58eff44155e18cf5")
        and isinstance(release, dict) and isinstance(release.get("path"), str) and bool(release["path"])
        and isinstance(release.get("sha256"), str) and len(release["sha256"]) == 64
        and refs.get("recovery_release") == release
        and len(rows) == 1 and rows[0].get("candidate_id") == cid
        and rows[0].get("runtime_owner") == "FINAL_ACTION_OVERLAY"
        and rows[0].get("dependency_closure", {}).get("status") == "COMPLETE")
