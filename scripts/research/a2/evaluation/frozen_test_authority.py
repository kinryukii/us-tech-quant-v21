"""Three exact frozen-task admissions for fresh-cash descriptive 2026 evaluation.

This is a source/custody gate, not an account engine or source certifier. It reads
only declared references once. A verified object can be reused by the controller,
policy and feature adapter without hashing the same large files per session.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import pandas as pd

TASK = "V24_A_FROZEN_THREE_POLICY_2026_RANDOM_START_EVALUATION_R1"
PLAN_SHA256 = "65ee05f2e434c35634bdc62d08bca7a494f92beb431bfd22e7c3254831de5b44"
AGGREGATE_TASK = "V24_A_13F_AGGREGATE_TOP100_RETEST_20261008_R1"
AGGREGATE_PLAN_SHA256 = "19942f20e0434b5fb70a6f0b0b6d2c6079b2f3057ade910c8c530e3f4a48da27"
CONSENSUS_TASK = "V24_A_13F_CONSENSUS_TOP100_RETEST_20261009_R1"
CONSENSUS_PLAN_SHA256 = "3e3b4ec5e241c59be19a264e55ee57e4e677f1b67ab8d1986d3f5fdb8a4382cc"
CONSENSUS_PARENT_SCHEDULE_SHA256 = "4dafa6e7cf4e980a04b880d4b1bec1bec711a038f602e60de5fb730fac37ad78"
RAW_SELECTOR_SHA256 = "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b"

ALL_AMOUNT_TASK = "A_ALL_AMOUNT100_RANDOM_TEST2026_20261009_R1"
ALL_CONSENSUS_TASK = "A_ALL_CONSENSUS100_RANDOM_TEST2026_20261009_R1"
ALL_POOL_ROOT_TASK = "A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1"
ALL_POOL_PLAN_SHA256 = "a5aa9d35bda475ce791ad4f7bd66f76159c3af7344d63ae9f01c5678f9e75f26"
ALL_POOL_SCOPE_SHA256 = "df573b2fa1ad03333f84aeee2b8df3c35779abb08bb73e4903d722dc63de19f0"
ALL_POOL_SCHEDULE_SHA256 = "903e6b72d8c1c55f7214b1761f8a6ee607faca5caa5e9d67210d94eb5ba60f3a"
ALL_POOL_DESCENDANTS = {
    ALL_AMOUNT_TASK: ("568299330ea97dab93ee5fd9da32c23006ab49b988df8cb3f39b4b8fe2286b3f", AGGREGATE_TASK, AGGREGATE_PLAN_SHA256, "cafc66c53bfb602635a19c3297b4127cf1442defd8a06d8381d9ee0b85da8c3c"),
    ALL_CONSENSUS_TASK: ("43c0285253ad77801d6f92cb04e56fcdfb44d8e1d8e739d988760f60af16cb79", CONSENSUS_TASK, CONSENSUS_PLAN_SHA256, "2a8321b3f20fb8836ced6e4c9543df1619ed2bb2ffaf515a7a9575d38dc80688"),
}


def pool_descendant_tasks():
    return tuple(ALL_POOL_DESCENDANTS)


def consensus_variant_tasks():
    return (CONSENSUS_TASK, ALL_CONSENSUS_TASK)


def pool_descendant_schedule(ref):
    _require(isinstance(ref, dict) and ref.get("sha256") == ALL_POOL_SCHEDULE_SHA256,
             "POOL_DESCENDANT_ROOT_SCHEDULE_REQUIRED")
    schedule = _document(ref)
    _require(schedule.get("task_id") == ALL_POOL_ROOT_TASK
             and schedule.get("as_of") == "2026-10-09T03:46:22+00:00"
             and schedule.get("common_end") == "2026-10-08"
             and len(schedule.get("windows", [])) == 101,
             "POOL_DESCENDANT_ROOT_SCHEDULE_CHANGED")
    return schedule


def _pool_descendant_plan(plan, task):
    _, parent_task, parent_sha, candidate_sha = ALL_POOL_DESCENDANTS[task]
    pref = plan.get("frozen_parent_plan_ref", {})
    _require(pref.get("sha256") == parent_sha and plan.get("parent_contract_ref") == pref,
             "POOL_DESCENDANT_PARENT_PLAN_REQUIRED")
    parent = six_path_plan(pref)
    _require(parent.get("task_id") == parent_task, "POOL_DESCENDANT_PARENT_IDENTITY_CHANGED")
    unchanged = ("candidates", "benchmarks", "account", "universe_change", "model_rule",
                 "test_interval", "training_content_cutoff_exclusive", "earlier_cutoffs_retained")
    _require(all(plan.get(k) == parent.get(k) for k in unchanged)
             and plan.get("comparison", {}).get("benchmark_contract") == parent.get("comparison", {}).get("benchmark_contract"),
             "POOL_DESCENDANT_ORIGINAL_SCIENCE_CHANGED")
    cref = plan.get("frozen_parent_candidate_manifest_ref", {})
    _require(cref.get("sha256") == candidate_sha, "POOL_DESCENDANT_PARENT_CANDIDATES_REQUIRED")
    _physical(cref)
    root_ref, scope_ref = plan.get("root_plan_ref", {}), plan.get("scope_addendum_ref", {})
    _require(root_ref.get("sha256") == ALL_POOL_PLAN_SHA256
             and scope_ref.get("sha256") == ALL_POOL_SCOPE_SHA256
             and plan.get("root_task_id") == ALL_POOL_ROOT_TASK
             and plan.get("as_of_utc") == "2026-10-09T03:46:22+00:00"
             and plan.get("evaluation_target_end") == "2026-10-08", "POOL_DESCENDANT_SCOPE_CHANGED")
    root, scope = _document(root_ref), _document(scope_ref)
    _require(root.get("task_id") == scope.get("task_id") == ALL_POOL_ROOT_TASK
             and scope.get("root_plan_ref") == root_ref
             and any(b.get("original_task_id") == parent_task for b in scope.get("branches", [])),
             "POOL_DESCENDANT_SCOPE_PARENT_MISSING")
    pool_descendant_schedule(plan.get("comparison", {}).get("exact_window_source_ref"))



def universe_variant_tasks():
    return (AGGREGATE_TASK, CONSENSUS_TASK, *pool_descendant_tasks())


def six_path_tasks():
    return (TASK, *universe_variant_tasks())


def six_path_plan_sha256(task_id):
    pins = {TASK: PLAN_SHA256, AGGREGATE_TASK: AGGREGATE_PLAN_SHA256,
            CONSENSUS_TASK: CONSENSUS_PLAN_SHA256}
    pins.update({key: value[0] for key, value in ALL_POOL_DESCENDANTS.items()})
    _require(task_id in pins, "DESCRIPTIVE_EXACT_TASK_REQUIRED")
    return pins[task_id]


def six_path_plan(plan_ref):
    """Only the three explicit human-requested six-path evaluation designs."""
    pins = {six_path_plan_sha256(task): task for task in six_path_tasks()}
    _require(isinstance(plan_ref, dict) and plan_ref.get("sha256") in pins,
             "DESCRIPTIVE_FROZEN_PLAN_REQUIRED")
    plan = _document(plan_ref)
    expected = pins[plan_ref["sha256"]]
    _require(plan.get("task_id", TASK) == expected, "DESCRIPTIVE_PLAN_IDENTITY_CHANGED")
    if expected == CONSENSUS_TASK:
        change = plan.get("universe_change", {})
        _require(plan.get("parent_contract_ref", {}).get("sha256") == AGGREGATE_PLAN_SHA256
                 and change.get("selection_rule") == "MANAGER_COUNT_WEIGHT_SUM"
                 and change.get("new_selection") == "DISTINCT_MANAGER_COUNT_DESC_WEIGHT_SUM_DESC_CUSIP_ASC_TOP100"
                 and change.get("rank_column") == "consensus_rank"
                 and plan.get("comparison", {}).get("exact_window_source_ref", {}).get("sha256") == CONSENSUS_PARENT_SCHEDULE_SHA256,
                 "CONSENSUS_FROZEN_SELECTION_OR_PARENT_CHANGED")
    if expected in pool_descendant_tasks():
        _pool_descendant_plan(plan, expected)
    return plan


def aggregate_evaluation_tuple(plan_ref, original_policy_tuple_sha256):
    """Keep original policy identity separate from the changed scientific question."""
    pins = {six_path_plan_sha256(task): task for task in universe_variant_tasks()}
    _require(plan_ref.get("sha256") in pins, "AGGREGATE_FROZEN_PLAN_REQUIRED")
    return hashlib.sha256(json.dumps(dict(task_id=pins[plan_ref["sha256"]],
        original_policy_tuple_sha256=original_policy_tuple_sha256,
        plan_sha256=plan_ref["sha256"], raw_selector_sha256=RAW_SELECTOR_SHA256),
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
PATH_IDS = ("RAW_s10", "R6_BUY_TREE", "R6_REPLACE_TREE",
            "A_BREADTH_R1_ngboost_REF_s10", "QQQ_BUY_AND_HOLD", "SPY_BUY_AND_HOLD")
MODEL_IDS = PATH_IDS[1:4]
POLICY_TUPLE_SHA256 = {
    "RAW_s10": "cbef40dd5c44be027c1cf38d53bf4310f252ba3aedc4d994ae5b1aba618d1bc4",
    "R6_BUY_TREE": "de1037b60ce161df8bb1ab36309ec63f53d1a1b61f18eb6ad2f7693a7b1b57b0",
    "R6_REPLACE_TREE": "4e70b1b99b26648a722079a8c5363b45e0490ef53c509e733595ed7d9ed81782",
    "A_BREADTH_R1_ngboost_REF_s10": "2a6e5c0dc25e14633e37dfb6d88ec9fcb2e372922395ea28f12405776c04066f",
}
MODEL_SHA256 = {
    "R6_BUY_TREE": "2423c3b859e040a52e3891201bdd0a2816e67c89a8a89c8508f96ef9b20ee7ba",
    "R6_REPLACE_TREE": "e1195c7b7c6ca9ba8aec163f031585469bd81bf18a5c6f879cd6c0a6c2d93313",
    "A_BREADTH_R1_ngboost_REF_s10": "02bb8fd1351f75e6fe44ad43ab81644d06f3f820a1550cfd5385eed517ced99a",
}
SOURCE_GROUPS = ("market_quote", "security_identity", "corporate_actions",
                 "action_inputs", "quote_quality")
INFERENCE_SOURCE_GROUPS = tuple(k for k in SOURCE_GROUPS if k != "corporate_actions")
INFERENCE_REF_SCHEMA = "A_2026_FROZEN_MODEL_INFERENCE_AUTHORITY_REF_R1"
_SEAL = object()
_INFERENCE_SEAL = object()


def _require(ok, code):
    if not ok:
        raise ValueError(code)


def _physical(ref):
    _require(isinstance(ref, dict) and isinstance(ref.get("path"), str)
             and bool(ref["path"]) and re.fullmatch(r"[0-9a-f]{64}", str(ref.get("sha256", ""))),
             "DESCRIPTIVE_PHYSICAL_REFERENCE_REQUIRED")
    path = Path(ref["path"])
    # Reject forbidden drives lexically, before existence checks or hashing.
    _require(path.drive.upper() not in ("E:", "F:"), "DESCRIPTIVE_FORBIDDEN_DRIVE")
    _require(path.is_absolute() and path.is_file(), "DESCRIPTIVE_REFERENCE_FILE_REQUIRED")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    _require(digest.hexdigest() == ref["sha256"], "DESCRIPTIVE_SOURCE_SHA_CHANGED")
    return path


def _document(ref):
    value = json.loads(_physical(ref).read_text(encoding="utf-8-sig"))
    _require(isinstance(value, dict), "DESCRIPTIVE_OBJECT_REQUIRED")
    return value


def _day(value):
    _require(isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)),
             "DESCRIPTIVE_SESSION_DATE_REQUIRED")
    day = pd.Timestamp(value)
    _require(day.date().isoformat() == value, "DESCRIPTIVE_SESSION_DATE_REQUIRED")
    return day


@dataclass(frozen=True)
class _SourcePolicyCustody:
    task_id: str
    policy_ids: tuple
    seal: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class ValidatedDescriptiveAuthority:
    task_id: str
    window_id: str
    start: pd.Timestamp
    end: pd.Timestamp
    as_of: pd.Timestamp
    feature_history_start: pd.Timestamp
    allowed_path_ids: tuple
    provenance_json: str
    _seal: object = field(repr=False, compare=False)
    runtime_policy_ids: tuple = ()
    capability: str = "ACCOUNT"
    research_cash_reconstruction_json: str = "{}"
    research_terminal_reconstruction_json: str = "{}"
    source_ready_policy_ids: tuple = ()
    _source_policy_custody: object = field(default=None, repr=False, compare=False)

    def __reduce__(self):
        raise TypeError("Revalidate physical descriptive authority instead of deserializing it")


def a_profile_tasks():
    from scripts.research.a2.evaluation.frozen_a94_profile import profile_tasks
    return profile_tasks()


def _verified(value):
    _require(type(value) is ValidatedDescriptiveAuthority
             and value.task_id in (*six_path_tasks(), *a_profile_tasks()), "VALIDATED_DESCRIPTIVE_AUTHORITY_REQUIRED")
    _require(value.capability in ("ACCOUNT", "INFERENCE_ONLY"),
             "DESCRIPTIVE_UNKNOWN_CAPABILITY")
    expected_seal = _INFERENCE_SEAL if value.capability == "INFERENCE_ONLY" else _SEAL
    _require(value._seal is expected_seal, "VALIDATED_DESCRIPTIVE_AUTHORITY_REQUIRED")
    custody = value._source_policy_custody
    if custody is not None:
        _require(type(custody) is _SourcePolicyCustody and custody.seal is _SEAL
            and custody.task_id == value.task_id and value.source_ready_policy_ids == custody.policy_ids,
            "DESCRIPTIVE_SOURCE_POLICY_CUSTODY_CHANGED")
    else:
        _require(value.source_ready_policy_ids == (), "DESCRIPTIVE_SOURCE_POLICY_CUSTODY_REQUIRED")
    if value.capability == "INFERENCE_ONLY":
        _require(value.task_id == TASK and value.allowed_path_ids == MODEL_IDS,
                 "DESCRIPTIVE_EXACT_THREE_INFERENCE_REQUIRED")
    return value


def benchmark_contract(plan, candidate_id):
    """Project the already frozen ETF comparison contract; no new policy choice."""
    _require(candidate_id in PATH_IDS[4:], "DESCRIPTIVE_BENCHMARK_NOT_REGISTERED")
    account, comparison = plan.get("account", {}), plan.get("comparison", {})
    text = comparison.get("benchmark_contract")
    _require(account.get("fractional") is True
             and account.get("execution") == "ORIGINAL_NEXT_LEGAL_RAW_OPEN"
             and account.get("friction_bps_each_executed_notional") == 10
             and account.get("terminal_liquidation") is False
             and isinstance(text, str) and bool(text),
             "DESCRIPTIVE_FROZEN_BENCHMARK_CONTRACT_REQUIRED")
    return dict(ticker=candidate_id.split("_", 1)[0], policy="BUY_AND_HOLD",
        fractional=True, execution=account["execution"], friction_bps=10,
        corporate_actions="SOURCE_BACKED_DIVIDENDS_SPLITS_CASH",
        terminal_liquidation=False, frozen_plan_contract=text)


def load_descriptive_authority(authority):
    """Account admission always retains all five literal-True source gates."""
    return _load_descriptive_authority(authority, inference_only=False)


def load_descriptive_inference_authority(authority):
    """Exact three-model capability; never grants a policy/account source role."""
    if (type(authority) is ValidatedDescriptiveAuthority
            and authority.capability == "INFERENCE_ONLY"):
        return _verified(authority)
    if isinstance(authority, dict) and authority.get("schema") == INFERENCE_REF_SCHEMA:
        return _load_descriptive_authority(authority, inference_only=True)
    # Existing account-qualified A6/AGGREGATE callers retain their old admission.
    return load_descriptive_authority(authority)


def _load_descriptive_authority(authority, *, inference_only):
    """Shared immutable custody/plan/policy validator; never decode models."""
    if type(authority) is ValidatedDescriptiveAuthority:
        value = _verified(authority)
        _require(value.capability == "ACCOUNT", "DESCRIPTIVE_INFERENCE_ONLY_CANNOT_RUN_ACCOUNT")
        return value
    if not inference_only and isinstance(authority, dict):
        _require(authority.get("schema") != INFERENCE_REF_SCHEMA,
                 "DESCRIPTIVE_INFERENCE_ONLY_CANNOT_RUN_ACCOUNT")
    if not inference_only and isinstance(authority, dict) and authority.get("task_id") in a_profile_tasks():
        from scripts.research.a2.evaluation.frozen_a94_profile import load_authority
        return load_authority(authority)
    expected_ref = INFERENCE_REF_SCHEMA if inference_only else "A_2026_DESCRIPTIVE_AUTHORITY_REF_R1"
    tasks = (TASK,) if inference_only else six_path_tasks()
    _require(isinstance(authority, dict)
             and authority.get("schema") == expected_ref
             and authority.get("task_id") in tasks, "DESCRIPTIVE_EXACT_TASK_REQUIRED")
    task = authority["task_id"]
    bound = _document(authority.get("admission_ref"))
    admission_schema = ("A_2026_FROZEN_MODEL_INFERENCE_ADMISSION_R1" if inference_only
                        else "A_2026_DESCRIPTIVE_ACCOUNT_ADMISSION_R1")
    admission_status = ("SOURCE_AND_POLICY_BOUND_FOR_FROZEN_INFERENCE_ONLY" if inference_only
                        else "SOURCE_AND_POLICY_BOUND_FOR_DESCRIPTIVE_EVALUATION")
    _require(bound.get("schema") == admission_schema
             and bound.get("task_id") == task and bound.get("status") == admission_status,
             "DESCRIPTIVE_ADMISSION_NOT_BOUND")
    if inference_only:
        _require(authority.get("capability") == bound.get("capability") == "INFERENCE_ONLY"
                 and bound.get("account_execution_allowed") is False,
                 "DESCRIPTIVE_INFERENCE_CAPABILITY_REQUIRED")
    _require(bound.get("strict_PIT_promotion_eligible") is False
             and bound.get("production_qualified") is False
             and bound.get("finalist_selected") is False
             and type(bound.get("new_fit")) is int and bound["new_fit"] == 0,
             "DESCRIPTIVE_RESEARCH_ONLY_NO_FIT")
    plan_ref = bound.get("plan_ref")
    plan = six_path_plan(plan_ref)
    _require(plan.get("task_id") == task, "DESCRIPTIVE_PLAN_IDENTITY_CHANGED")
    if task == TASK:
        _require(plan.get("status") == "EVALUATION_DESIGN_FROZEN_BEFORE_2026_POLICY_REPLAY"
                 and plan.get("allow_2027_read") is False
                 and plan.get("pre2026_parent_remains_closed") is True,
                 "DESCRIPTIVE_PLAN_IDENTITY_CHANGED")
    else:
        _require(plan_ref["sha256"] == six_path_plan_sha256(task)
                 and plan.get("status") == "DESIGN_FIXED_BEFORE_NEW_UNIVERSE_POLICY_REPLAY"
                 and plan.get("test_interval") == ["2026-01-01", "2027-01-01"]
                 and plan.get("budget", {}).get("new_fit") == 0,
                 "AGGREGATE_FROZEN_PLAN_REQUIRED")
    allowed_ids = MODEL_IDS if inference_only else PATH_IDS
    _require(bound.get("allowed_path_ids") == list(allowed_ids),
             "DESCRIPTIVE_EXACT_THREE_INFERENCE_REQUIRED" if inference_only else "DESCRIPTIVE_SIX_POLICIES_REQUIRED")
    _require(bound.get("initial_cash_usd") == 3000
             and bound.get("initial_holdings") == []
             and bound.get("initial_receivables") == []
             and bound.get("friction_bps") == 10
             and bound.get("fresh_account") is True, "DESCRIPTIVE_FRESH_USD3000_10BPS_REQUIRED")
    sources = bound.get("source_refs")
    source_groups = INFERENCE_SOURCE_GROUPS if inference_only else SOURCE_GROUPS
    _require(isinstance(sources, dict) and set(sources) == set(source_groups),
             "DESCRIPTIVE_SOURCE_SLOTS_UNBOUND")
    for ref in sources.values():
        _physical(ref)
    qualification = _document(bound.get("source_qualification_ref"))
    qualification_schema = ("A_2026_FROZEN_MODEL_INFERENCE_SOURCE_QUALIFICATION_R1" if inference_only
                            else "A_2026_DESCRIPTIVE_SOURCE_QUALIFICATION_R1")
    qualification_status = ("QUALIFIED_FOR_FROZEN_INFERENCE_ONLY" if inference_only
                            else "QUALIFIED_FOR_DECLARED_RESEARCH_SCOPE")
    _require(qualification.get("schema") == qualification_schema
             and qualification.get("task_id") == task
             and qualification.get("status") == qualification_status
             and qualification.get("source_refs") == sources,
             "DESCRIPTIVE_SOURCE_QUALIFICATION_UNBOUND")
    if inference_only:
        _require(qualification.get("capability") == "INFERENCE_ONLY",
                 "DESCRIPTIVE_INFERENCE_CAPABILITY_REQUIRED")
    groups = qualification.get("groups")
    _require(isinstance(groups, dict) and set(groups) == set(source_groups)
             and all(groups[k] is True for k in source_groups), "DESCRIPTIVE_SOURCE_GATE_NOT_TRUE")
    if inference_only:
        _require(bound.get("research_cash_reconstruction") is None
                 and bound.get("research_terminal_reconstruction") is None,
                 "DESCRIPTIVE_INFERENCE_ONLY_CANNOT_ADMIT_ACCOUNTING")
    cash_binding_json = _load_post_verified_binding(bound, sources, task, "research_cash_reconstruction")
    terminal_binding_json = _load_post_verified_binding(bound, sources, task, "research_terminal_reconstruction")
    if task in universe_variant_tasks():
        # Qualification must describe this new input set; a parent-task seal is
        # neither a replacement for source evidence nor a pool-change approval.
        universe_ref = bound.get("universe_source_ref")
        _require(qualification.get("universe_source_ref") == universe_ref
                 and qualification.get("plan_ref") == plan_ref,
                 "AGGREGATE_UNIVERSE_SOURCE_UNBOUND")
        universe = _document(universe_ref)
        _require(universe.get("task_id") == task
                 and universe.get("source_refs", {}).get("evaluation_plan") == plan_ref
                 and universe.get("universe_change") == plan.get("universe_change"),
                 "AGGREGATE_UNIVERSE_TASK_OR_CONTRACT_CHANGED")
        raw = bound.get("raw_selector_ref")
        _require(isinstance(raw, dict) and raw.get("sha256") == RAW_SELECTOR_SHA256
                 and qualification.get("raw_selector_ref") == raw,
                 "AGGREGATE_RAW_SELECTOR_CHANGED")
        _physical(raw)
        review_ref = bound.get("lineage_review_ref")
        review = _document(review_ref)
        _require(review.get("task_id") == task
                 and review.get("schema") == "A_UNIVERSE_VARIANT_SOURCE_LINEAGE_REVIEW_R1"
                 and review.get("status") == "STRUCTURAL_NONREDUNDANCY_SUPPORTED_EXECUTION_QUALIFICATION_PENDING"
                 and review.get("independent") is True
                 and review.get("plan_ref", {}).get("sha256") == plan_ref["sha256"]
                 and qualification.get("lineage_review_ref") == review_ref,
                 "AGGREGATE_LINEAGE_REVIEW_UNBOUND")
    models = bound.get("model_refs")
    _require(isinstance(models, dict) and set(models) == set(MODEL_IDS),
             "DESCRIPTIVE_MODEL_IDENTITIES_UNBOUND")
    for name, ref in models.items():
        _require(isinstance(ref, dict) and ref.get("sha256") == MODEL_SHA256[name],
                 "DESCRIPTIVE_EXACT_FROZEN_MODEL_REQUIRED")
        _physical(ref)
    candidates = _document(bound.get("candidate_manifest_ref"))
    rows = candidates.get("candidates")
    _require(candidates.get("task_id") == task and isinstance(rows, list)
             and [r.get("candidate_id") for r in rows if isinstance(r, dict)] == list(PATH_IDS),
             "DESCRIPTIVE_CANDIDATE_IDENTITIES_UNBOUND")
    for row in rows:
        _require(re.fullmatch(r"[0-9a-f]{64}", str(row.get("scientific_tuple_sha256", "")))
                 and row.get("friction_bps") == 10, "DESCRIPTIVE_CANDIDATE_CONTRACT_CHANGED")
        name = row["candidate_id"]
        if name in POLICY_TUPLE_SHA256:
            _require(row["scientific_tuple_sha256"] == POLICY_TUPLE_SHA256[name],
                     "DESCRIPTIVE_EXACT_FROZEN_POLICY_REQUIRED")
        else:
            expected = benchmark_contract(plan, name)
            _require(row.get("benchmark_contract") == expected,
                     "DESCRIPTIVE_BENCHMARK_CONTRACT_CHANGED")
            commitment = hashlib.sha256(json.dumps(expected, sort_keys=True,
                separators=(",", ":")).encode("utf-8")).hexdigest()
            _require(row["scientific_tuple_sha256"] == commitment,
                     "DESCRIPTIVE_BENCHMARK_COMMITMENT_CHANGED")
        if task in universe_variant_tasks():
            _require(row.get("original_policy_tuple_sha256") == row["scientific_tuple_sha256"]
                     and row.get("variant_evaluation_tuple_sha256") ==
                         aggregate_evaluation_tuple(plan_ref, row["scientific_tuple_sha256"]),
                     "AGGREGATE_SCIENTIFIC_QUESTION_IDENTITY_CHANGED")
        if name in MODEL_IDS:
            _require(row.get("model_ref") == models[name],
                     "DESCRIPTIVE_CANDIDATE_MODEL_MISMATCH")
    windows = bound.get("windows")
    _require(isinstance(windows, list) and 1 <= len(windows) <= 101
             and all(isinstance(w, dict) and isinstance(w.get("window_id"), str)
                     and bool(w["window_id"]) for w in windows)
             and len({w["window_id"] for w in windows}) == len(windows),
             "DESCRIPTIVE_FROZEN_WINDOWS_REQUIRED")
    if task == CONSENSUS_TASK:
        parent_schedule = _document(plan["comparison"]["exact_window_source_ref"])
        _require(parent_schedule.get("task_id") == AGGREGATE_TASK,
                 "CONSENSUS_EXACT_PARENT_SCHEDULE_REQUIRED")
        parent_windows = {w["window_id"]: w for w in parent_schedule["windows"]}
        _require(all(w["window_id"] in parent_windows
                     and all(w.get(k) == parent_windows[w["window_id"]][k] for k in ("start", "end"))
                     for w in windows), "CONSENSUS_WINDOW_CHANGED")
    if task in pool_descendant_tasks():
        root_schedule = pool_descendant_schedule(plan["comparison"]["exact_window_source_ref"])
        _require(windows == root_schedule["windows"] and bound.get("as_of") == root_schedule["as_of"],
                 "POOL_DESCENDANT_ACCOUNT_WINDOWS_CHANGED")
    selected = [w for w in windows if w["window_id"] == authority.get("window_id")]
    _require(len(selected) == 1, "DESCRIPTIVE_WINDOW_NOT_REGISTERED")
    as_of = pd.Timestamp(bound.get("as_of"))
    _require(not pd.isna(as_of) and as_of.tzinfo is not None, "DESCRIPTIVE_AS_OF_REQUIRED")
    history_start = _day(bound.get("feature_history_start"))
    for window in windows:
        start, end = _day(window.get("start")), _day(window.get("end"))
        _require(pd.Timestamp("2026-01-01") <= start < end < pd.Timestamp("2027-01-01"),
                 "DESCRIPTIVE_2026_WINDOW_REQUIRED")
        close = (end + pd.Timedelta(hours=16)).tz_localize("America/New_York")
        _require(close <= as_of, "DESCRIPTIVE_INCOMPLETE_SESSION")
    start, end = _day(selected[0]["start"]), _day(selected[0]["end"])
    _require(pd.Timestamp("2023-01-01") <= history_start <= start,
             "DESCRIPTIVE_FEATURE_CONTEXT_BOUNDARY")
    provenance = dict(schema=authority["schema"], task_id=task,
        admission_ref=authority["admission_ref"], plan_ref=plan_ref,
        window_id=authority["window_id"], start=str(start.date()), end=str(end.date()),
        as_of=as_of.isoformat(), source_qualification_ref=bound["source_qualification_ref"],
        candidate_manifest_ref=bound["candidate_manifest_ref"],
        strict_PIT_promotion_eligible=False, production_qualified=False, finalist_selected=False,
        new_fit=0, account_initialization="FRESH_USD3000_NO_INHERITED_POSITIONS_OR_RECEIVABLES")
    if task in universe_variant_tasks():
        provenance.update(universe_source_ref=bound["universe_source_ref"],
            raw_selector_ref=bound["raw_selector_ref"], lineage_review_ref=bound["lineage_review_ref"],
            variant_evaluation_tuples={r["candidate_id"]: r["variant_evaluation_tuple_sha256"] for r in rows},
            reused_policy_identity_is_not_full_evaluation_identity=True)
    if inference_only:
        provenance.update(capability="INFERENCE_ONLY", account_execution_allowed=False)
    return ValidatedDescriptiveAuthority(task, authority["window_id"], start, end, as_of,
        history_start, allowed_ids, json.dumps(provenance, sort_keys=True),
        _INFERENCE_SEAL if inference_only else _SEAL,
        capability="INFERENCE_ONLY" if inference_only else "ACCOUNT",
        research_cash_reconstruction_json=cash_binding_json,
        research_terminal_reconstruction_json=terminal_binding_json)


_TERMINAL_COMMITMENT_FIELDS = (
    "event_id", "old_security_id", "ticker", "effective_at", "available_at",
    "cash_per_old_share", "currency", "amount_unit", "quantity_coordinate",
    "quantity_source_reference", "quantity_source_fingerprint", "source_type",
    "source_reference", "source_fingerprint", "action_type", "effective_clock_basis",
)


def _load_post_verified_binding(bound, sources, task, key):
    binding = bound.get(key)
    if binding is None:
        return "{}"
    tasks = six_path_tasks() if key == "research_cash_reconstruction" else (TASK,)
    tasks = (*tasks, *a_profile_tasks())
    _require(task in tasks and isinstance(binding, dict)
             and binding.get("task_id") == task
             and binding.get("clock_role") == "POST_VERIFIED_ACCOUNTING_ONLY"
             and binding.get("strict_PIT_promotion_eligible") is False
             and binding.get("production_qualified") is False,
             "DESCRIPTIVE_POST_VERIFIED_EXACT_TASK_REQUIRED")
    if task in a_profile_tasks():
        from scripts.research.a2.evaluation.frozen_a94_profile import _post_verified_binding_header
        _post_verified_binding_header(binding, key)
    catalogue = _document(sources["corporate_actions"])
    _require(catalogue.get(key) == binding,
             "DESCRIPTIVE_POST_VERIFIED_SOURCE_COMMITMENT_CHANGED")
    terminal = key == "research_terminal_reconstruction"
    entries = binding.get("events")
    fields = {"event_fingerprint", "reconstruction_ref"} | ({"terminal_terms"} if terminal else set())
    _require(isinstance(entries, list) and bool(entries)
             and all(isinstance(e, dict) and set(e) == fields
                     and re.fullmatch(r"[0-9a-f]{64}", str(e.get("event_fingerprint", "")))
                     and isinstance(e.get("reconstruction_ref"), dict)
                     and set(e["reconstruction_ref"]) == {"path", "sha256"} for e in entries)
             and len({e["event_fingerprint"] for e in entries}) == len(entries),
             "DESCRIPTIVE_POST_VERIFIED_EVENT_PINS_REQUIRED")
    for entry in entries:
        _physical(entry["reconstruction_ref"])
        if terminal:
            terms = entry["terminal_terms"]
            _require(isinstance(terms, dict)
                     and set(terms) == set(_TERMINAL_COMMITMENT_FIELDS) | {"settlement"}
                     and terms["settlement"] is None and terms["available_at"] is None
                     and terms["effective_clock_basis"] == "SOURCE_EFFECTIVE_BY_OPEN_UPPER_BOUND",
                     "DESCRIPTIVE_TERMINAL_UNKNOWN_SETTLEMENT_COMMITMENT_REQUIRED")
            _physical({"path": terms["source_reference"], "sha256": terms["source_fingerprint"]})
            _physical({"path": terms["quantity_source_reference"], "sha256": terms["quantity_source_fingerprint"]})
    return json.dumps(binding, sort_keys=True)


def validate_reconstructed_accounting_events(authority, events, *, require_exact=False):
    """Reuse one admission seal; no source IO or wider-task admission at runtime."""
    from scripts.v22.corporate_action_transition_r1 import (
        ResearchReconstructedCashEvent, ResearchPostVerifiedTerminalEvent)
    value = _verified(authority)
    _require(value.capability == "ACCOUNT", "DESCRIPTIVE_INFERENCE_ONLY_CANNOT_RUN_ACCOUNT")
    _require(value.task_id in (*six_path_tasks(), *a_profile_tasks()),
             "DESCRIPTIVE_POST_VERIFIED_EXACT_TASK_REQUIRED")
    for cls, serialized in (
        (ResearchReconstructedCashEvent, value.research_cash_reconstruction_json),
        (ResearchPostVerifiedTerminalEvent, value.research_terminal_reconstruction_json),
    ):
        binding = json.loads(serialized)
        if binding:
            _require(isinstance(binding, dict) and binding.get("task_id") == value.task_id
                     and binding.get("clock_role") == "POST_VERIFIED_ACCOUNTING_ONLY"
                     and binding.get("strict_PIT_promotion_eligible") is False
                     and binding.get("production_qualified") is False
                     and (cls is ResearchReconstructedCashEvent or value.task_id in
                          (TASK, *a_profile_tasks())),
                     "DESCRIPTIVE_POST_VERIFIED_EXACT_TASK_REQUIRED")
            if value.task_id in a_profile_tasks():
                from scripts.research.a2.evaluation.frozen_a94_profile import _post_verified_binding_header
                key = ("research_terminal_reconstruction" if cls is ResearchPostVerifiedTerminalEvent
                       else "research_cash_reconstruction")
                _post_verified_binding_header(binding, key)
        expected = {e["event_fingerprint"]: e for e in binding.get("events", [])}
        actual = []
        for event in (e for e in events if isinstance(e, cls)):
            event.__post_init__()
            actual.append(event.event_fingerprint)
            entry = expected.get(event.event_fingerprint)
            _require(entry is not None and entry["reconstruction_ref"] == {
                "path": event.reconstruction_ref, "sha256": event.reconstruction_sha256},
                "DESCRIPTIVE_POST_VERIFIED_EVENT_CHANGED")
            if cls is ResearchPostVerifiedTerminalEvent:
                terms = {k: getattr(event, k) for k in _TERMINAL_COMMITMENT_FIELDS}
                _require(entry["terminal_terms"] == {**terms, "settlement": None},
                         "DESCRIPTIVE_TERMINAL_TERMS_CHANGED")
        _require(len(actual) == len(set(actual)), "DESCRIPTIVE_DUPLICATE_POST_VERIFIED_EVENT")
        if require_exact:
            _require(set(actual) == set(expected), "DESCRIPTIVE_POST_VERIFIED_CATALOGUE_CHANGED")
    return value


def require_descriptive_decision(authority, date, path_id=None, *, inference_only=False):
    """Pure per-session check; use an already validated authority object."""
    value = _verified(authority)
    _require(inference_only is True or value.capability == "ACCOUNT",
             "DESCRIPTIVE_INFERENCE_ONLY_CANNOT_RUN_ACCOUNT")
    day = pd.Timestamp(date)
    _require(not pd.isna(day) and day.tzinfo is None and day == day.normalize()
             and value.start <= day <= value.end, "DESCRIPTIVE_DECISION_OUTSIDE_WINDOW")
    if path_id is not None:
        _require(path_id in value.allowed_path_ids, "DESCRIPTIVE_POLICY_NOT_REGISTERED")
        if value.task_id in a_profile_tasks():
            from scripts.research.a2.evaluation.frozen_a94_profile import require_runtime_policy
            require_runtime_policy(value, (path_id,))
    return value


def validate_descriptive_input_dates(authority, dates, *, feature_context=False):
    """Feature context is input-only; this grants no labels, fitting or selection."""
    value = _verified(authority)
    dates = pd.DatetimeIndex(dates)
    start = value.feature_history_start if feature_context is True else value.start
    _require(len(dates) > 0 and dates.tz is None and not dates.hasnans
             and dates.equals(dates.normalize()) and dates.min() >= start
             and dates.max() <= value.end, "DESCRIPTIVE_INPUT_OUTSIDE_WINDOW")
    return value


def validate_descriptive_account(authority, dates, path_ids, account_config, execution_friction):
    value = load_descriptive_authority(authority)
    dates = pd.DatetimeIndex(dates)
    validate_descriptive_input_dates(value, dates)
    _require(dates.is_monotonic_increasing and dates.is_unique
             and dates[0] == value.start and dates[-1] == value.end,
             "DESCRIPTIVE_ACCOUNT_CALENDAR_CHANGED")
    ids = tuple(path_ids)
    _require(bool(ids) and len(set(ids)) == len(ids)
             and ids == tuple(p for p in value.allowed_path_ids if p in ids), "DESCRIPTIVE_POLICY_ORDER_CHANGED")
    _require(account_config.get("initial_nav") == 3000
             and account_config.get("initial_cash", 3000) == 3000
             and account_config.get("initial_holdings", []) == []
             and account_config.get("initial_receivables", []) == [],
             "DESCRIPTIVE_FRESH_USD3000_REQUIRED")
    if value.task_id in a_profile_tasks():
        from scripts.research.a2.evaluation.frozen_a94_profile import validate_account_friction
        return validate_account_friction(value, ids, execution_friction)
    _require(isinstance(execution_friction, dict) and execution_friction.get("one_way_bps") == 10,
             "DESCRIPTIVE_FIXED_10BPS_REQUIRED")
    return value


def validate_descriptive_policy(authority, candidates):
    """Validate full A94 policy specs; pass the returned authority to the overlay.

    Existing six-path callers retain their original policy/model admission.
    """
    value = load_descriptive_authority(authority)
    if value.task_id in a_profile_tasks():
        from scripts.research.a2.evaluation.frozen_a94_profile import validate_policy
        return validate_policy(value, candidates)
    _require(isinstance(candidates, (list, tuple)) and bool(candidates)
             and all(isinstance(c, dict) for c in candidates), "DESCRIPTIVE_POLICY_NOT_REGISTERED")
    ids = tuple(c.get("candidate_id") for c in candidates)
    _require(len(set(ids)) == len(ids) and ids == tuple(p for p in value.allowed_path_ids if p in ids),
             "DESCRIPTIVE_POLICY_ORDER_CHANGED")
    return value
