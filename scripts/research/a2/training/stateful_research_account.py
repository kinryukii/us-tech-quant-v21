"""Research-only admission, persistence and economics around existing account APIs.

Strict R5 cannot admit frozen ex-post accounting or unknown settlement. This
child adds their separate identity and ten integrity checks. InputReader,
read_market/read_packet/read_risk_packets, execute_market and the original
corporate-action/account owners remain the only numerical implementations.
No controller, fitting, alternate engine or historical source discovery exists
here. The research corporate-action extension must be approved before real use.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.training import stateful_replay as replay
from scripts.research.a2.training import stateful_completion as meta
from scripts.storage.storage_r2a import assert_write_path, write_json_atomic

NAMESPACE = "FROZEN_HISTORY_RESEARCH_ACCOUNT"
TASK_ID = "V24_A_FROZEN_HISTORY_RESEARCH_ACCOUNT_AND_POLICY_EVALUATION_R1"
QUOTE_NAMESPACE = "FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN"
QUOTE_TASK_ID = "V24_A_FROZEN_HISTORY_RESEARCH_QUOTE_DOMAIN_DESCENDANT_R1"
SESSION_NAMESPACE = "FROZEN_HISTORY_SESSION_BOUNDARY_CA_ACCOUNTING"
SESSION_TASK_ID = "V24_A_FROZEN_HISTORY_SESSION_BOUNDARY_CA_ACCOUNTING_R1"
QUOTE_DESCENDANTS = (QUOTE_NAMESPACE, SESSION_NAMESPACE)
NAMESPACES = (NAMESPACE, *QUOTE_DESCENDANTS)
SESSION_FLAGS = dict(real_effective_clock_proven=False, research_session_boundary_assumption=True,
    strict_PIT_promotion_eligible=False, production_qualified=False)
GATES = ("DECISION_INFORMATION_FIREWALL", "EXECUTION_QUOTE_COORDINATE",
 "SECURITY_ACCOUNTING_CONTINUITY", "DOUBLE_ENTRY_ACCOUNTING", "CASH_IDENTITY",
 "CORPORATE_ACTION_AND_ENTITLEMENT", "RECEIVABLE_ACCOUNTING", "NAV_IDENTITY",
 "CONTINUOUS_YEAR_BOUNDARY", "SOURCE_CUSTODY_AND_REPRODUCIBILITY")
METRICS = ("terminal_TOTAL_ECONOMIC_NAV", "terminal_LIQUID_NAV", "cumulative_return",
 "annual_return", "MaxDD", "turnover", "trade_count", "BUY_SKIP_count",
 "HOLD_SELL_count", "REPLACE_count", "entrant_incumbent_replacement_frequency",
 "holding_duration", "Gross_distribution", "Cash_distribution", "receivable_exposure",
 "receivable_duration", "cost_drag", "frozen_cost_sensitivity", "yearly_relative_effect")
FIELDS = ("candidate_id", "source_method_ids", "action", "value_model", "control",
 "gross", "risk", "target_role", "action_cost_mode", "execution_friction", "forecast",
 "scientific_tuple_sha256")
BOUNDARY = pd.Timestamp("2026-01-01")


def require(ok, code):
    if not ok:
        raise ValueError(code)


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _roots():
    return resolve(replay.REPO)


def reference(ref, *, source=False):
    require(isinstance(ref, dict) and _sha(ref.get("sha256")) and isinstance(ref.get("path"), str),
            "RESEARCH_REFERENCE_REQUIRED")
    path = Path(ref["path"]).resolve()
    require(path.drive.upper() not in ("E:", "F:"), "RESEARCH_E_F_FORBIDDEN")
    roots = _roots()
    allowed = (roots.repo_root, roots.backtest_root, roots.results_root) if source else (
        roots.backtest_root, roots.results_root)
    require(any(path.is_relative_to(Path(root).resolve()) for root in allowed),
            "RESEARCH_REFERENCE_OUTSIDE_CANONICAL_ROOT")
    require(path.is_file() and replay.sha(path) == ref["sha256"], "RESEARCH_REFERENCE_CHANGED")
    return path


def namespace(auth=None):
    value = (auth or {}).get("namespace", NAMESPACE)
    require(value in NAMESPACES, "RESEARCH_NAMESPACE_UNKNOWN")
    return value


def accounting_contract_sha(auth):
    # The quote descendant never expands the common CA authority allowlist.
    key = "parent_account_contract_ref" if namespace(auth) in QUOTE_DESCENDANTS else "contract_ref"
    require(isinstance(auth.get(key), dict) and _sha(auth[key].get("sha256")),
            "RESEARCH_ACCOUNTING_CONTRACT_UNBOUND")
    return auth[key]["sha256"]


def validate_authority(authority, contract_sha, event_fingerprints=None):
    require(isinstance(authority, dict) and set(authority) == {"scientific_identity", "task_id",
            "frozen_contract_sha256", "clock_role", "strict_PIT_promotion_eligible",
            "production_qualified", "event_fingerprints"} and authority.get("scientific_identity") == NAMESPACE and
            authority.get("task_id") == TASK_ID and authority.get("frozen_contract_sha256") == contract_sha and
            authority.get("clock_role") == "RECONSTRUCTED_REALIZED_EVENT" and
            authority.get("strict_PIT_promotion_eligible") is False and
            authority.get("production_qualified") is False, "RESEARCH_ACCOUNT_AUTHORITY_REQUIRED")
    pins = authority.get("event_fingerprints")
    require(isinstance(pins, list) and len(set(pins)) == len(pins) and all(_sha(x) for x in pins),
            "RESEARCH_EVENT_ALLOWLIST_REQUIRED")
    if event_fingerprints is not None:
        require(pins == list(event_fingerprints), "RESEARCH_EVENT_ALLOWLIST_CHANGED")


def _same(actual, original):
    return all(actual.get(k, "none" if k == "forecast" else None) ==
               original.get(k, "none" if k == "forecast" else None) for k in FIELDS)


def validate_candidates(auth, candidates):
    from scripts.research.a2.training import stateful_breadth as breadth
    original = _read(reference(auth["original_catalogue_ref"]))
    manifest = _read(reference(auth["frozen37_manifest_ref"]))
    design = _read(reference(auth["breadth_design_ref"]))
    require(auth["original_catalogue_ref"]["sha256"] ==
            "611930988eeec394f8a2d5ac0466f63b382a02d87a362afcf361d0886495aeb8", "RESEARCH_CATALOGUE_IDENTITY")
    require(auth["frozen37_manifest_ref"]["sha256"] ==
            "c0ca38578f0879c2c477c02996487e971a85060b5a86c115acc979a5fcabb3ed", "RESEARCH_FROZEN37_IDENTITY")
    require(auth["breadth_design_ref"]["sha256"] == breadth.DESIGN_SHA, "RESEARCH_BREADTH19_IDENTITY")
    remaining = manifest["frozen_remaining_candidates"]; broad = breadth.validate_design(design)
    require(len(candidates) == 57 and len(remaining) == 37 and len(broad) == 19, "RESEARCH_EXACT57")
    frozen = {c["candidate_id"]: c for c in original}
    require(candidates[0]["candidate_id"] == "RAW_s10" and _same(candidates[0], frozen["RAW_s10"]),
            "RESEARCH_BASELINE_CHANGED")
    for c, expected in zip(candidates[1:38], remaining):
        require(c["candidate_id"] == expected["candidate_id"] and
                c["scientific_tuple_sha256"] == expected["scientific_tuple_sha256"] and
                _same(c, frozen[c["candidate_id"]]), "RESEARCH_FROZEN37_CHANGED")
    require(all(_same(c, expected) for c, expected in zip(candidates[38:], broad)), "RESEARCH_BREADTH19_CHANGED")
    require(len({c["candidate_id"] for c in candidates}) == 57 and
            len({c["scientific_tuple_sha256"] for c in candidates}) == 57,
            "RESEARCH_DUPLICATE_REQUIRES_EXACT_REUSE_REVIEW")
    return candidates


def security_mapping_records(binding):
    """Validate the frozen dated accounting map, separate from unchanged decision SID."""
    proof = _read(reference(binding["security_accounting_mapping_ref"]))
    records = proof.get("records")
    require(proof.get("status") == "FROZEN_RESEARCH_SECURITY_ACCOUNTING_MAPPING" and
            proof.get("role") == "ACCOUNTING_MAPPING_ONLY" and
            proof.get("coordinate") == "RAW_ACTUAL_SHARE" and
            proof.get("decision_information_unchanged") is True and
            isinstance(records, list) and bool(records) and
            binding.get("security_accounting_records") == records, "RESEARCH_SECURITY_MAPPING_PROOF")
    normalized = []
    for row in records:
        require(isinstance(row, dict) and set(row) == {"sid", "ticker", "start", "end", "coordinate"} and
                all(isinstance(row[k], str) and row[k].strip() for k in ("sid", "ticker", "start", "end")) and
                row["coordinate"] == "RAW_ACTUAL_SHARE", "RESEARCH_SECURITY_MAPPING_RECORD")
        start = pd.Timestamp(row["start"]); end = pd.Timestamp(row["end"])
        require(str(start.date()) == row["start"] and str(end.date()) == row["end"] and
                start.tz is None and end.tz is None and start < end <= BOUNDARY,
                "RESEARCH_SECURITY_MAPPING_INTERVAL")
        normalized.append(dict(row, start=start, end=end))
    for key in ("sid", "ticker"):
        groups = defaultdict(list)
        for row in normalized:
            groups[row[key]].append(row)
        for intervals in groups.values():
            ordered = sorted(intervals, key=lambda row: row["start"])
            require(all(left["end"] <= right["start"] for left, right in zip(ordered, ordered[1:])),
                    "RESEARCH_SECURITY_MAPPING_NOT_UNIQUE")
    return normalized


def source_closure_paths(research_namespace=NAMESPACE):
    """The reused readers, policy, account owner and receipt transports are pinned together."""
    paths = [Path(__file__), *replay.SOURCE_PATHS.values(), replay.PARENT / "STATEFUL_POLICY.py"]
    paths += [replay.REPO / relative for relative in (
        "scripts/research/a2/training/stateful_execution.py",
        "scripts/research/a2/training/stateful_completion.py",
        "scripts/research/a2/training/stateful_inputs.py",
        "scripts/research/a2/training/stateful_fusion.py",
        "scripts/research/a2/training/stateful_value_repair.py",
        "scripts/research/a2/retained/a2_predict_then_optimize_20260928_r1/fusion_models.py",
        "scripts/research/a2/retained/a2_predict_then_optimize_20260928_r1/common.py",
        "scripts/research/a2/risk/joint_risk_estimators.py",
        "scripts/research/a2/evaluation/joint_method_accounts.py",
        "scripts/v22/corporate_action_transition_r1.py",
        "scripts/common/storage_paths.py", "scripts/storage/storage_r2a.py")]
    require(research_namespace in NAMESPACES, "RESEARCH_NAMESPACE_UNKNOWN")
    if research_namespace in QUOTE_DESCENDANTS:
        paths.append(replay.REPO / "scripts/research/a2/training/stateful_research_quote_domain.py")
    return tuple(dict.fromkeys(p.resolve() for p in paths))



def _session_convention(auth, scientific=None):
    """Verify the independent accounting convention before any attempt is reserved."""
    from scripts.research.a2.evaluation import continuous_research_account as shared
    require(namespace(auth) == SESSION_NAMESPACE, "RESEARCH_SESSION_NAMESPACE_REQUIRED")
    scientific = scientific if scientific is not None else _read(reference(auth["contract_ref"]))
    require(all(auth.get(k) is v and scientific.get(k) is v for k, v in SESSION_FLAGS.items()),
            "RESEARCH_SESSION_ASSUMPTION_FLAGS_REQUIRED")
    require(all(isinstance(auth.get(k), dict) and auth[k] == scientific.get(k) for k in
        ("session_boundary_rule_ref", "session_boundary_population_ref", "parent_quote_contract_ref")),
        "RESEARCH_SESSION_REFERENCES_UNBOUND")
    ref = auth.get("research_ca_accounting_convention")
    reference(ref)
    loader = getattr(shared, "load_research_ca_accounting_convention", None)
    require(callable(loader), "RESEARCH_CA_CONVENTION_OWNER_EXTENSION_REQUIRED")
    frozen = loader(ref)
    require(frozen.get("contract_ref") == auth["contract_ref"] and
            frozen.get("rule_ref") == scientific["session_boundary_rule_ref"] and
            frozen.get("population_ref") == scientific["session_boundary_population_ref"],
            "RESEARCH_SESSION_CONVENTION_IDENTITY_CHANGED")
    return frozen


def _quote_domain(auth, scientific=None):
    """Keep quote science exact; only SESSION may repin the reviewed replay seam."""
    from scripts.research.a2.training import stateful_research_quote_domain as quote
    if namespace(auth) == SESSION_NAMESPACE:
        scientific = scientific if scientific is not None else _read(reference(auth["contract_ref"]))
        original = _read(reference(scientific["quote_domain_ref"]))
        envelope = _read(reference(auth["quote_domain_ref"]))
        require(auth["quote_domain_ref"] != scientific["quote_domain_ref"] and
                envelope.get("parent_quote_domain_ref") == scientific["quote_domain_ref"],
                "RESEARCH_SESSION_QUOTE_CUSTODY_LINEAGE_REQUIRED")
        require(all(envelope.get(k) == v for k, v in original.items() if k != "source_pins"),
                "RESEARCH_SESSION_QUOTE_SCIENCE_CHANGED")
        old_pins = original.get("source_pins", {}); new_pins = envelope.get("source_pins", {})
        replay_key = str(Path(replay.__file__).resolve())
        require(bool(old_pins) and set(new_pins) == set(old_pins) and replay_key in old_pins and
                new_pins[replay_key] == replay.sha(Path(replay.__file__)) and
                all(new_pins[k] == v for k, v in old_pins.items() if k != replay_key),
                "RESEARCH_SESSION_QUOTE_REPIN_NOT_EXACT_REPLAY_SEAM")
        parent = _read(reference(auth["parent_quote_contract_ref"]))
        require(parent.get("scientific_identity") == QUOTE_NAMESPACE and parent.get("task_id") == QUOTE_TASK_ID and
                parent.get("quote_domain_ref") == scientific["quote_domain_ref"] and
                parent.get("parent_account_contract_ref") == scientific["parent_account_contract_ref"],
                "RESEARCH_SESSION_QUOTE_PARENT_CHANGED")
    return quote.load_frozen_domain(auth["quote_domain_ref"])


def contract(run_dir):
    """Metadata and custody only; no model, forecast, market or ledger decoding."""
    run = Path(run_dir).resolve()
    require(run.is_relative_to(_roots().backtest_root.resolve()), "RESEARCH_RUN_OUTSIDE_CANONICAL_ROOT")
    config = meta.read_metadata(run, run / "run_config.json", meta.ALL)
    auth = config.get("research_account", {})
    require(config.get("phase") == "FROZEN" and auth.get("status") == "FROZEN" and
            auth.get("namespace") in NAMESPACES, "RESEARCH_FREEZE_REQUIRED")
    require(config.get("training_cutoff_exclusive") == "2026-01-01" and
            config.get("evaluation_years") == [2023, 2024, 2025] and config.get("capital_usd") == 3000 and
            config.get("fractional_primary") is True, "RESEARCH_ACCOUNT_OR_TIME_BOUNDARY")
    require(auth.get("max_new_fit_units") == 0 and auth.get("max_new_account_paths") == 57 and
            auth.get("baseline_candidate_id") == "RAW_s10", "RESEARCH_EXACT_BUDGET")
    scientific = _read(reference(auth["contract_ref"])); firewall = _read(reference(auth["firewall_ref"]))
    metrics = scientific.get("metrics", {}); budget = scientific.get("budget", {})
    research_namespace = namespace(auth)
    expected_task = {NAMESPACE: TASK_ID, QUOTE_NAMESPACE: QUOTE_TASK_ID, SESSION_NAMESPACE: SESSION_TASK_ID}[research_namespace]
    require(scientific.get("scientific_identity") == research_namespace and scientific.get("task_id") == expected_task and
            scientific.get("research_integrity_gates") == list(GATES) and
            scientific.get("annual_reset") is False and scientific.get("2026_locked") is True and
            scientific.get("full_sessions") == 752 and scientific.get("continuous_years") == [2023, 2024, 2025] and
            budget.get("max_new_fit_before_R9") == 0 and budget.get("planned_account_paths") == 57 and
            budget.get("scientific_retry") == 0 and scientific.get("strict_PIT_promotion_eligible") is False and
            scientific.get("production_qualified") is False and metrics.get("HAC_lag") == 20 and
            metrics.get("family_alpha") == .05 and metrics.get("Bonferroni_multiple_family_upper") == 220 and
            metrics.get("primary") == "PAIRED_DAILY_NET_LOG_RETURN_DIFFERENCE_TOTAL_ECONOMIC_NAV_VS_RAW_s10",
            "RESEARCH_PHASE0_CONTRACT_CHANGED")
    if research_namespace in QUOTE_DESCENDANTS:
        require(auth.get("certified_market_quote_authority") is False and
                scientific.get("certified_market_quote_authority") is False, "RESEARCH_QUOTE_CERTIFIED_AUTHORITY_FORBIDDEN")
        require(all(isinstance(auth.get(k), dict) and scientific.get(k) == auth[k]
                    for k in (("parent_account_contract_ref", "quote_domain_ref") if research_namespace == QUOTE_NAMESPACE
                              else ("parent_account_contract_ref",))),
                "RESEARCH_QUOTE_DESCENDANT_REFERENCES_UNBOUND")
        parent_contract = _read(reference(auth["parent_account_contract_ref"]))
        require(parent_contract.get("scientific_identity") == NAMESPACE and parent_contract.get("task_id") == TASK_ID
                and all(parent_contract.get(k) == scientific.get(k) for k in (
                    "research_integrity_gates", "annual_reset", "2026_locked", "full_sessions", "continuous_years",
                    "metrics", "firewall_ref", "candidates_ref", "frozen37_manifest_ref", "original_catalogue_ref", "breadth_design_ref")),
                "RESEARCH_QUOTE_PARENT_SCIENCE_CHANGED")
        _quote_domain(auth, scientific)
        if research_namespace == SESSION_NAMESPACE:
            _session_convention(auth, scientific)
    require(all(firewall.get(k) is True for k in ("decision_information_unchanged", "accounting_mapping_only",
        "outcome_no_decision_feedback")) and firewall.get("time", {}).get("2026_locked") is True,
        "RESEARCH_FIREWALL_UNBOUND")
    require(all(auth.get(k) == scientific.get(k) for k in ("firewall_ref", "candidates_ref",
        "frozen37_manifest_ref", "original_catalogue_ref", "breadth_design_ref")), "RESEARCH_PHASE0_REFERENCE_CHANGED")
    pins = auth.get("source_pins", {})
    required = source_closure_paths(research_namespace)
    require(isinstance(pins, dict) and all(str(p.resolve()) in pins for p in required), "RESEARCH_SOURCE_CLOSURE_INCOMPLETE")
    for path, pin in pins.items():
        reference(dict(path=path, sha256=pin), source=True)
    parent = Path(config["parent_run_dir"]).resolve()
    require(parent != run and parent.is_relative_to(_roots().backtest_root.resolve()), "RESEARCH_PARENT_IDENTITY")
    binding = _read(reference(auth["source_binding_ref"]))
    require(binding.get("status") == "FROZEN_RESEARCH_ACCOUNT_SOURCE_BINDING" and
            binding.get("quote_coordinate") == "RAW_ACTUAL_SHARE" and binding.get("future_adjusted_prices") is False and
            all(binding.get(k) is True for k in ("decision_information_unchanged", "accounting_mapping_only",
            "quote_coordinate_verified", "security_accounting_continuity_verified")), "RESEARCH_BINDING_UNBOUND")
    require(Path(binding["decision_input_manifest_ref"]["path"]).resolve() == parent / "input_manifest.json",
            "RESEARCH_PARENT_MANIFEST_MISMATCH")
    for key in ("decision_input_manifest_ref", "cash_source_bundle", "quote_coordinate_evidence_ref",
                "security_accounting_mapping_ref", "decision_firewall_proof_ref"):
        reference(binding[key])
    validate_authority(auth.get("research_account_authority"), accounting_contract_sha(auth))
    require(_sha(binding.get("MKFG_terminal_event_fingerprint")) and
            binding["MKFG_terminal_event_fingerprint"] in auth["research_account_authority"]["event_fingerprints"],
            "RESEARCH_MKFG_RECONSTRUCTION_UNBOUND")
    security_mapping_records(binding)
    candidates = validate_candidates(auth, _read(reference(auth["candidates_ref"])))
    history_budget(run, candidates, namespace(auth))
    return run, config, auth, candidates


def _history(run):
    from scripts.research.a2.training import stateful_execution as owner
    return owner._continuation_events(Path(run), "ACCOUNT_PATH_LOG.jsonl")


def history_budget(run, candidates, research_namespace=NAMESPACE):
    history = _history(run)
    starts = [e for e in history if e.get("event") == "ACCOUNT_PATH_ATTEMPT_STARTED"]
    ends = [e for e in history if e.get("event") in ("ACCOUNT_PATH_COMPLETE", "ACCOUNT_PATH_FAILED")]
    declared = {c["candidate_id"]: c for c in candidates}
    require(research_namespace in NAMESPACES, "RESEARCH_NAMESPACE_UNKNOWN")
    require(all(e.get("namespace") == research_namespace and e.get("continuation") is True for e in starts + ends),
            "RESEARCH_JOURNAL_NAMESPACE")
    require(len(starts) <= 57 and len({e.get("candidate_id") for e in starts}) == len(starts) and
            len({e.get("scientific_tuple_sha256") for e in starts}) == len(starts), "RESEARCH_CAP_OR_RETRY")
    require(all(e.get("candidate_id") in declared and e.get("scientific_tuple_sha256") ==
                declared[e["candidate_id"]]["scientific_tuple_sha256"] for e in starts + ends),
            "RESEARCH_JOURNAL_IDENTITY")
    require([e["candidate_id"] for e in starts] == [c["candidate_id"] for c in candidates[:len(starts)]],
            "RESEARCH_PATH_ORDER_CHANGED")
    require(all(e.get("path_units") == 1 for e in starts), "RESEARCH_ONE_PATH_UNIT")
    counts = Counter(e["candidate_id"] for e in ends)
    require(all(n == 1 for n in counts.values()) and set(counts).issubset(e["candidate_id"] for e in starts),
            "RESEARCH_TERMINAL_WITHOUT_UNIQUE_START")
    fit, partial = meta.read_events(Path(run), "FIT_LOG.jsonl")
    require(not partial and not any(e.get("event") in ("FIT_STARTED", "MODEL_YEAR_ATTEMPT_STARTED") for e in fit),
            "RESEARCH_NEW_FIT_FORBIDDEN")
    return dict(new_fit_units=0, new_account_path_attempts=len(starts),
        completed=sum(e["event"] == "ACCOUNT_PATH_COMPLETE" for e in ends),
        failed=sum(e["event"] == "ACCOUNT_PATH_FAILED" for e in ends), outstanding=len(starts) - len(ends),
        max_new_account_paths=57, strict_baseline_attempts_consumed=0, scientific_retry=0)


def worker_guard(run, config, auth):
    from scripts.research.a2.training import stateful_execution as owner
    token = os.environ.get(owner.CONTINUATION_LOCK_ENV)
    lock = Path(run) / "CONTINUATION_LOCK.json"
    require(token and lock.is_file(), "RESEARCH_WORKER_PARENT_LOCK_REQUIRED")
    state = meta.read_metadata(Path(run), lock, {k: meta.ALL for k in (
        "token", "namespace", "controller_source_sha256", "run_config_sha256")})
    require(state.get("token") == token and state.get("namespace") == namespace(auth) and
            state.get("controller_source_sha256") == replay.sha(Path(owner.__file__)) and
            state.get("run_config_sha256") == replay.sha(Path(run) / "run_config.json"),
            "RESEARCH_WORKER_PARENT_LOCK_MISMATCH")



def _decision_digest(market, arrays):
    h = hashlib.sha256()
    for item in (market.input_present, market.new_buy_eligible, *arrays):
        data = np.ascontiguousarray(item)
        h.update(str(data.dtype).encode()); h.update(str(data.shape).encode()); h.update(data.tobytes())
    return h.hexdigest()


def bound_inputs(auth, market, events, unsupported):
    """Consumed frozen catalogue; never invent available_at or a settlement date."""
    binding = _read(reference(auth["source_binding_ref"]))
    bundle = joblib.load(reference(binding["cash_source_bundle"]))
    keys = ("entitlement_enabled", "entitlement_events", "entitlement_security_tickers",
            "entitlement_source_binding")
    require(isinstance(bundle, dict) and all(k in bundle for k in keys) and
            bundle["entitlement_enabled"] is True, "RESEARCH_ENTITLEMENT_BUNDLE_REQUIRED")
    catalogue = tuple(bundle["entitlement_events"]); source = bundle["entitlement_source_binding"]
    mapping = security_mapping_records(binding)
    require(source.get("source_fingerprint") == binding["cash_binding_semantic_fingerprint"] and
            [e.event_fingerprint for e in catalogue] == binding["entitlement_catalogue_fingerprints"] and
            bundle["entitlement_security_tickers"] == binding["security_tickers"],
            "RESEARCH_CONSUMED_SOURCE_CHANGED")
    from scripts.v22.corporate_action_transition_r1 import (
        SourceBackedEntitlementEvent, SourceBackedTerminalEvent, _entitlement_effective_day)
    for event in catalogue:
        require(isinstance(event, (SourceBackedEntitlementEvent, SourceBackedTerminalEvent)), "RESEARCH_TYPED_EVENT")
        event.__post_init__()
        require(pd.Timestamp(_entitlement_effective_day(event)) < BOUNDARY and event.currency == "USD" and
                event.amount_unit == "USD_PER_RAW_OLD_SHARE" and event.quantity_coordinate == "RAW_OLD_SECURITY_SHARES",
                "RESEARCH_EVENT_DATE_OR_RAW_COORDINATE")
        effective = pd.Timestamp(_entitlement_effective_day(event))
        require(binding["security_tickers"].get(event.old_security_id) == event.ticker and
                sum(row["sid"] == event.old_security_id and row["ticker"] == event.ticker and
                    row["start"] <= effective < row["end"] for row in mapping) == 1,
                "RESEARCH_EVENT_SECURITY_BINDING_MISMATCH")
    validate_authority(auth["research_account_authority"], accounting_contract_sha(auth),
                       [e.event_fingerprint for e in catalogue if getattr(e, "clock_role", None) == "RECONSTRUCTED_REALIZED_EVENT"])
    from scripts.v22.corporate_action_transition_r1 import ResearchReconstructedTerminalEvent
    mkfg = [e for e in catalogue if isinstance(e, SourceBackedTerminalEvent) and e.ticker == "MKFG"]
    require(len(mkfg) == 1 and isinstance(mkfg[0], ResearchReconstructedTerminalEvent) and
            mkfg[0].cash_per_old_share == 5. and
            mkfg[0].event_fingerprint == binding["MKFG_terminal_event_fingerprint"],
            "RESEARCH_MKFG_RECONSTRUCTION_UNBOUND")
    from scripts.research.a2.evaluation.joint_method_accounts import with_effective_event_quality
    original_quality = market.quality.copy()
    market = with_effective_event_quality(market, {"corporate_actions": events, "unsupported_events": unsupported})
    quote_payload = None
    if namespace(auth) in QUOTE_DESCENDANTS:
        from scripts.research.a2.training import stateful_research_quote_domain as quote
        quote_payload = _quote_domain(auth)
        inherited = with_effective_event_quality(replace(market, quality=np.zeros_like(original_quality, dtype=bool)),
            {"corporate_actions": events, "unsupported_events": unsupported}).quality
        quality, quote_audit = quote.apply_quote_domain(original_quality, inherited,
            market.dates, market.tickers, quote_payload["decisions"])
        market = replace(market, quality=quality)
        binding = dict(binding, quote_domain_ref=auth["quote_domain_ref"], quote_domain_audit=quote_audit)
    removal = {tuple(x) for x in source["manifest"]["removal_keys"]}
    def key(row):
        return row.get("ticker"), str(pd.Timestamp(row.get("effective_date")).date()), row.get("source_fingerprint")
    remaining = tuple(row for row in unsupported if key(row) not in removal)
    kwargs = {k: bundle[k] for k in keys}
    kwargs["research_account_authority"] = auth["research_account_authority"]
    if quote_payload is not None:
        kwargs["research_quote_domain"] = dict(auth["quote_domain_ref"])
    if namespace(auth) == SESSION_NAMESPACE:
        _session_convention(auth)
        kwargs["research_ca_accounting_convention"] = dict(auth["research_ca_accounting_convention"])
        binding = dict(binding, research_ca_accounting_convention=auth["research_ca_accounting_convention"], **SESSION_FLAGS)
    return market, remaining, kwargs, binding


def add_dual_nav(result):
    """Use the sole owner's marks/cash/receivable; retain strict fields unchanged."""
    daily = result.daily.copy()
    require(not daily.empty and all(pd.Timestamp(d) < BOUNDARY for d in daily.date),
            "RESEARCH_PRE2026_DAILY_REQUIRED")
    assets = result.positions.groupby(["path_id", "date"]).market_value.sum(min_count=1)
    keys = pd.MultiIndex.from_frame(daily[["path_id", "date"]])
    daily["market_securities_value_usd"] = assets.reindex(keys, fill_value=0.).to_numpy(float)
    require("receivable_value_usd" in daily, "RESEARCH_RECEIVABLE_STATE_REQUIRED")
    daily["LIQUID_NAV"] = daily.cash + daily.market_securities_value_usd
    daily["TOTAL_ECONOMIC_NAV"] = daily.LIQUID_NAV + daily.receivable_value_usd
    daily["research_net_return"] = daily.groupby("path_id", sort=False).TOTAL_ECONOMIC_NAV.pct_change(fill_method=None)
    for _, group in daily.groupby("path_id", sort=False):
        daily.loc[group.index[0], "research_net_return"] = group.TOTAL_ECONOMIC_NAV.iloc[0] / 3000. - 1.
    daily["research_cash_weight"] = daily.cash / daily.TOTAL_ECONOMIC_NAV
    daily["research_gross"] = daily.market_securities_value_usd / daily.TOTAL_ECONOMIC_NAV
    return daily


def _execution_coordinate(result, path, market):
    fills = result.fills.loc[result.fills.path_id.eq(path)]
    if fills.empty:
        return True
    di = {pd.Timestamp(d): i for i, d in enumerate(market.dates)}
    ti = {str(t): i for i, t in enumerate(market.tickers)}
    if any(pd.Timestamp(d) not in di for d in fills.execution_date) or any(str(t) not in ti for t in fills.ticker):
        return False
    raw = np.asarray([market.open[di[pd.Timestamp(d)], ti[str(t)]] for d, t in zip(fills.execution_date, fills.ticker)])
    return bool(np.isfinite(raw).all() and (raw > 0).all() and
                np.allclose(fills.price, raw, rtol=1e-12, atol=1e-8) and
                np.allclose(fills.price * fills.index_units, fills.notional, rtol=1e-12, atol=1e-8))


def integrity_gates(result, path, binding, *, decision_unchanged, custody_verified,
                    market=None, expected_sessions=752, expected_year_sessions=None):
    """Research booleans only. Unknown settlement never becomes spendable cash."""
    daily = add_dual_nav(result)
    daily = daily.loc[daily.path_id.eq(path)].sort_values("date")
    positions = result.positions.loc[result.positions.path_id.eq(path)]
    checks = replay.qualification_checks(result, path)
    def identity(column):
        if column not in daily:
            return False
        data = daily[column].to_numpy(float)
        return bool(np.isfinite(data).all() and np.abs(data).max(initial=0.) <= 1e-8)
    exceptions = result.accounting_exceptions
    if not exceptions.empty:
        exceptions = exceptions.loc[exceptions.path_id.eq(path)]
    allowed = {"TERMINAL_SETTLEMENT_AUTHORITY_MISSING", "SETTLEMENT_PENDING_AUTHORITY"}
    exception_ok = bool(exceptions.empty or ("reason" in exceptions and exceptions.reason.isin(allowed).all()))
    cash_ok = identity("cash_flow_identity_error") and identity("actual_cash_flow_identity_error")
    double_entry = all(identity(c) for c in ("nav_identity_error", "cost_identity_error", "open_self_finance_error"))
    nav = daily.TOTAL_ECONOMIC_NAV.to_numpy(float)
    owner_nav = daily["engine_certified_nav"] if "engine_certified_nav" in daily else daily["nav"]
    nav_ok = bool(np.isfinite(nav).all() and (nav > 0).all() and
                  np.allclose(nav, owner_nav, rtol=1e-12, atol=1e-8) and
                  np.isfinite(daily.LIQUID_NAV).all() and daily.LIQUID_NAV.ge(0).all())
    quotes = (checks.get("quote_qualified") is True and binding.get("quote_coordinate_verified") is True and
              market is not None and _execution_coordinate(result, path, market))
    try:
        mapping = security_mapping_records(binding)
        by_ticker = defaultdict(list)
        for row in mapping:
            by_ticker[row["ticker"]].append(row)
        mapped = all(sum(row["start"] <= pd.Timestamp(position.date) < row["end"]
            for row in by_ticker[str(position.ticker)]) == 1 for position in positions.itertuples())
    except (KeyError, ValueError, TypeError, OSError):
        mapped = False
    coordinate = bool(positions.empty or (
        np.isfinite(positions[["index_units", "mark", "market_value"]]).all().all() and
        positions.index_units.ge(0).all() and np.allclose(
            positions.index_units * positions.mark, positions.market_value, rtol=1e-12, atol=1e-8)))
    table = result.entitlements.loc[result.entitlements.path_id.eq(path)]
    recognized = table.loc[table.phase.isin(("RECEIVABLE_RECOGNIZED", "MERGER_RECEIVABLE_RECOGNIZED"))]
    receivable = bool(np.isfinite(daily.receivable_value_usd).all() and daily.receivable_value_usd.ge(0).all() and
        (recognized.empty or recognized.spendable_cash_delta.eq(0).all()) and
        np.allclose(daily.TOTAL_ECONOMIC_NAV - daily.LIQUID_NAV, daily.receivable_value_usd, rtol=1e-12, atol=1e-8))
    path_index = list(result.metadata["path_ids"]).index(path)
    final_value = float(result.final_state["receivable_value_usd"][path_index])
    claims = result.final_state["entitlement_states"][path_index].receivables
    receivable = receivable and np.isclose(final_value, daily.receivable_value_usd.iloc[-1], rtol=0, atol=1e-8)
    receivable = bool(receivable and np.isclose(sum(c.amount_usd for c in claims), final_value, rtol=0, atol=1e-8))
    terminal_events = result.metadata.get("terminal_events", [])
    mkfg_pin = binding.get("MKFG_terminal_event_fingerprint")
    terminal_bound = bool(result.metadata.get("terminal_lifecycle_enabled") is True and _sha(mkfg_pin) and
        mkfg_pin in binding.get("entitlement_catalogue_fingerprints", []) and
        sum(event.get("ticker") == "MKFG" and event.get("event_fingerprint") == mkfg_pin
            for event in terminal_events) == 1)
    terminal = checks.get("terminal_identity_correct") is True and terminal_bound
    annual_counts = daily.date.dt.year.value_counts().to_dict()
    expected_year_sessions = expected_year_sessions or {2023: 250, 2024: 252, 2025: 250}
    continuous = bool(len(daily) == expected_sessions and not daily.date.duplicated().any() and
        annual_counts == expected_year_sessions and result.metadata.get("annual_reset") is False)
    groups = dict(zip(GATES, (
        decision_unchanged is True and binding.get("decision_information_unchanged") is True,
        quotes, coordinate and mapped and binding.get("security_accounting_continuity_verified") is True,
        double_entry and exception_ok, cash_ok,
        checks.get("entitlement_identity_correct") is True and terminal and exception_ok,
        receivable and terminal, nav_ok, continuous, custody_verified is True)))
    return dict(groups=groups, all_passed=all(v is True for v in groups.values()),
        gate_role="RESEARCH_INTEGRITY_ONLY", strict_PIT_promotion_eligible=False, production_qualified=False,
        terminal_settlement_qualified=checks.get("terminal_settlement_qualified"),
        accounting_exceptions_retained=len(exceptions), calendar_sessions=len(daily))


def _artifact(folder, name, frame):
    path = folder / (name + ".parquet"); bounds = {}
    for column in ("date", "signal_date", "execution_date", "session", "as_of"):
        if column in frame:
            dates = pd.to_datetime(frame[column], errors="coerce").dropna()
            if len(dates):
                boundary = BOUNDARY.tz_localize(dates.dt.tz) if dates.dt.tz else BOUNDARY
                require(dates.max() < boundary, "RESEARCH_OUTPUT_CLOCK_BOUNDARY")
                bounds[column] = dict(min=str(dates.min()), max=str(dates.max()))
    assert_write_path(path, "backtest"); frame.to_parquet(path, index=False)
    return dict(path=str(path), sha256=replay.sha(path), rows=len(frame),
                schema=list(frame.columns), clock_bounds=bounds, test_2026_rows_read=0)


def run_batch(run_dir, candidate_ids):
    """Thin worker: no second reader, execution loop or accounting implementation."""
    run, config, auth, all_candidates = contract(run_dir); worker_guard(run, config, auth)
    capability = runtime_capability(auth) if namespace(auth) in QUOTE_DESCENDANTS else runtime_capability()
    require(capability["available"], "RESEARCH_OWNER_EXTENSION_NOT_APPROVED_OR_APPLIED")
    before = history_budget(run, all_candidates, namespace(auth))
    require(before["outstanding"] == 0, "RESEARCH_OUTSTANDING_ATTEMPT")
    require(isinstance(candidate_ids, list) and bool(candidate_ids) and len(set(candidate_ids)) == len(candidate_ids),
            "RESEARCH_EXPLICIT_BATCH")
    start = before["new_account_path_attempts"]; candidates = all_candidates[start:start + len(candidate_ids)]
    require([c["candidate_id"] for c in candidates] == candidate_ids, "RESEARCH_NEXT_FROZEN_BATCH_ONLY")
    require(candidate_ids == ["RAW_s10"] if start == 0 else baseline_gate(run, auth)["all_passed"] is True,
            "RESEARCH_BASELINE_ONCE_AND_REQUIRED")
    friction = candidates[0]["execution_friction"]
    require(all(c["execution_friction"] == friction for c in candidates), "RESEARCH_BATCH_FRICTION")
    folder = run / "ledgers/stateful" / ("attempt_%04d" % (start + 1))
    assert_write_path(folder, "backtest"); require(not folder.exists(), "RESEARCH_EXISTING_OUTPUT")
    folder.mkdir(parents=True)
    from scripts.research.a2.training import stateful_execution as owner
    common = dict(namespace=namespace(auth), continuation=True, module_sha256=replay.sha(Path(__file__)),
        controller_module_sha256=replay.sha(Path(owner.__file__)),
        research_contract_sha256=auth["contract_ref"]["sha256"])
    for c in candidates:
        replay._append(run / "ACCOUNT_PATH_LOG.jsonl", dict(common, event="ACCOUNT_PATH_ATTEMPT_STARTED",
            path_units=1, candidate_id=c["candidate_id"], scientific_tuple_sha256=c["scientific_tuple_sha256"]))
    try:
        reader = replay._read_parent_inputs_readonly(Path(config["parent_run_dir"]))
        market, top, qualified, vol, stock, raw = replay.read_market(reader)
        require(len(market.dates) == 752 and all(d < BOUNDARY for d in market.dates), "RESEARCH_FULL_PRE2026_CALENDAR")
        decision_before = _decision_digest(market, (top, qualified, vol, stock, raw))
        packets = {}; worker_auth = {**auth, **auth.get("replay_source_pins", {})}
        worker_auth.update({k: replay.sha(p) for k, p in replay.SOURCE_PATHS.items()})
        worker_auth["input_manifest_sha256"] = replay.sha(Path(config["parent_run_dir"]) / "input_manifest.json")
        worker_auth["fusion_module_sha256"] = replay.sha(replay.REPO / "scripts/research/a2/training/stateful_fusion.py")
        worker_auth["value_repair_transport_sha256"] = replay.sha(replay.REPO / "scripts/research/a2/training/stateful_value_repair.py")
        for model in {c["value_model"] for c in candidates}:
            packets[model] = replay.read_packet(auth["value_packets"][model], reader, market.dates, market.tickers, auth=worker_auth)
            packets[model]["mu"] = np.where(stock, packets[model]["mu"], np.nan)
        providers = {}
        for method in {c["risk"] for c in candidates if c["risk"] not in ("diag", "diag20_reference")}:
            providers[method], _ = replay.read_risk_packets(worker_auth, reader,
                [c for c in candidates if c["risk"] == method], market.dates, vol, Path(config["parent_run_dir"]))
        def risk_provider(di, selected, tickers, method):
            return np.diag(vol[di, selected] ** 2) if method in ("diag", "diag20_reference") else providers[method](di, selected, tickers, method)
        old = replay._old(); account = old.config_adapter(replay._json(replay.PARENT / "R1_ACCOUNT_CONFIG.json"))
        events, known, unsupported, _ = old.frozen_events(replay._json(replay.PARENT / "INPUT_BINDING_R1.json"))
        market, unsupported, kwargs, binding = bound_inputs(auth, market, events, unsupported)
        decision_bound = _decision_digest(market, (top, qualified, vol, stock, raw))
        require(decision_before == decision_bound, "RESEARCH_ACCOUNTING_CHANGED_DECISION")
        result, frames = replay.execute_market(market, candidates, packets, top, qualified, vol, account,
            stock_present=stock, raw_selector_present=raw, events=events, known_at=known, unsupported=unsupported,
            risk_provider=risk_provider, execution_friction=friction, **kwargs)
        require(_decision_digest(market, (top, qualified, vol, stock, raw)) == decision_bound,
                "RESEARCH_EXECUTION_MUTATED_DECISION_INPUTS")
        contract(run); worker_guard(run, config, auth)
        frames["daily"] = add_dual_nav(result)
        gates = {c["candidate_id"]: integrity_gates(result, c["candidate_id"], binding,
            decision_unchanged=True, custody_verified=True, market=market) for c in candidates}
        if namespace(auth) == SESSION_NAMESPACE:
            frames["research_ca_accounting_boundary_audit"] = result.research_ca_accounting_boundary_audit
        records = {name: _artifact(folder, name, frame) for name, frame in frames.items()}
        audit = dict(status="RESEARCH_CONTINUOUS_PRE2026_REPLAY_COMPLETE", namespace=namespace(auth),
            research_contract_sha256=auth["contract_ref"]["sha256"], candidate_ids=candidate_ids,
            calendar_sessions=752, annual_reset=False, research_integrity=gates, artifacts=records,
            source_binding_ref=auth["source_binding_ref"], source_pins=auth["source_pins"],
            research_account_authority=auth["research_account_authority"],
            source_proof_refs={k: binding[k] for k in ("decision_input_manifest_ref", "cash_source_bundle",
                "quote_coordinate_evidence_ref", "security_accounting_mapping_ref", "decision_firewall_proof_ref")},
            decision_digest_before=decision_before, decision_digest_after=decision_bound,
            selection_performed=False, fit_units=0, test_2026_rows_read=0,
            strict_PIT_promotion_eligible=False, production_qualified=False)
        if namespace(auth) in QUOTE_DESCENDANTS:
            audit.update(quote_domain_ref=auth["quote_domain_ref"],
                parent_account_contract_ref=auth["parent_account_contract_ref"],
                quote_domain_audit=binding["quote_domain_audit"], certified_market_quote_authority=False)
        if namespace(auth) == SESSION_NAMESPACE:
            audit.update(research_ca_accounting_convention=auth["research_ca_accounting_convention"],
                research_ca_accounting_boundary_audit_ref=records["research_ca_accounting_boundary_audit"], **SESSION_FLAGS)
        write_json_atomic(folder / "audit.json", audit)
        for c in candidates:
            replay._append(run / "ACCOUNT_PATH_LOG.jsonl", dict(common, event="ACCOUNT_PATH_COMPLETE",
                candidate_id=c["candidate_id"], scientific_tuple_sha256=c["scientific_tuple_sha256"],
                audit_path=str(folder / "audit.json"), audit_sha256=replay.sha(folder / "audit.json")))
        return dict(status=audit["status"], candidate_ids=candidate_ids,
            audit_path=str(folder / "audit.json"), audit_sha256=replay.sha(folder / "audit.json"),
            research_integrity=gates, new_fit_units=0, economic_values_returned=False)
    except Exception as exc:
        failure = dict(type=type(exc).__name__, message=str(exc).split(":", 1)[0])
        failure_audit = dict(status="FAILED_RESEARCH_ACCOUNT_ATTEMPT_RETAINED",
            failure=failure, fit_units=0, test_2026_rows_read=0, candidate_ids=candidate_ids)
        if namespace(auth) == SESSION_NAMESPACE:
            failure_audit.update(namespace=SESSION_NAMESPACE, research_contract_sha256=auth["contract_ref"]["sha256"],
                research_ca_accounting_convention=auth["research_ca_accounting_convention"],
                certified_market_quote_authority=False, **SESSION_FLAGS)
        write_json_atomic(folder / "audit.json", failure_audit)
        for c in candidates:
            replay._append(run / "ACCOUNT_PATH_LOG.jsonl", dict(common, event="ACCOUNT_PATH_FAILED",
                candidate_id=c["candidate_id"], scientific_tuple_sha256=c["scientific_tuple_sha256"],
                failure=failure, audit_path=str(folder / "audit.json"), audit_sha256=replay.sha(folder / "audit.json")))
        raise


worker = run_batch


def baseline_gate(run, auth):
    ends = [e for e in _history(run) if e.get("candidate_id") == "RAW_s10" and
            e.get("event") in ("ACCOUNT_PATH_COMPLETE", "ACCOUNT_PATH_FAILED")]
    require(len(ends) <= 1, "RESEARCH_BASELINE_DUPLICATE_TERMINAL")
    groups = dict.fromkeys(GATES, False); state = "NOT_EXECUTED"
    if ends:
        event = ends[0]; state = event["event"]
        if state == "ACCOUNT_PATH_COMPLETE":
            path = Path(event["audit_path"]).resolve()
            require(path.is_relative_to(Path(run).resolve()) and replay.sha(path) == event["audit_sha256"],
                    "RESEARCH_BASELINE_AUDIT_CHANGED")
            schema = {"status": meta.ALL, "namespace": meta.ALL, "research_contract_sha256": meta.ALL,
                "research_integrity": {"RAW_s10": {"groups": {k: meta.ALL for k in GATES}}}}
            if namespace(auth) == SESSION_NAMESPACE:
                schema.update({k: meta.ALL for k in (*SESSION_FLAGS, "research_ca_accounting_convention")})
            audit = meta.read_metadata(Path(run), path, schema)
            require(audit.get("research_contract_sha256") == auth["contract_ref"]["sha256"] and
                    audit.get("status") == "RESEARCH_CONTINUOUS_PRE2026_REPLAY_COMPLETE", "RESEARCH_BASELINE_AUDIT_IDENTITY")
            if namespace(auth) in QUOTE_DESCENDANTS:
                require(audit.get("namespace") == namespace(auth), "RESEARCH_QUOTE_BASELINE_NAMESPACE")
            if namespace(auth) == SESSION_NAMESPACE:
                require(all(audit.get(k) is v for k, v in SESSION_FLAGS.items()) and
                        audit.get("research_ca_accounting_convention") == auth.get("research_ca_accounting_convention") and
                        isinstance(auth.get("research_ca_accounting_convention"), dict),
                        "RESEARCH_SESSION_BASELINE_ASSUMPTION_IDENTITY")
            supplied = audit.get("research_integrity", {}).get("RAW_s10", {}).get("groups", {})
            groups = {k: supplied.get(k) is True for k in GATES}
    passed = all(v is True for v in groups.values())
    result = dict(groups=groups, all_passed=passed, attempt_state=state,
        decision="ACTIVATE_FROZEN37_THEN_BREADTH19" if passed else "RESEARCH_ACCOUNT_BASELINE_BLOCKED",
        strict_PIT_promotion_eligible=False, production_qualified=False)
    if namespace(auth) in QUOTE_DESCENDANTS:
        result["certified_market_quote_authority"] = False
    if namespace(auth) == SESSION_NAMESPACE:
        result.update(namespace=SESSION_NAMESPACE, research_ca_accounting_convention=auth["research_ca_accounting_convention"], **SESSION_FLAGS)
    return result


def build_report(run_dir):
    run, _, auth, candidates = contract(run_dir)
    budget = history_budget(run, candidates, namespace(auth)); gate = baseline_gate(run, auth)
    status = ("FROZEN56_ACCOUNT_PATH_EXECUTION_COMPLETE" if budget["completed"] + budget["failed"] == 57
        else "RESEARCH_ACCOUNT_BASELINE_QUALIFIED" if gate["all_passed"] else
        "RESEARCH_ACCOUNT_BASELINE_BLOCKED" if budget["completed"] + budget["failed"] else "NOT_EXECUTED")
    if namespace(auth) in QUOTE_DESCENDANTS and status == "RESEARCH_ACCOUNT_BASELINE_QUALIFIED":
        status = "QUALIFIED_FROZEN_HISTORY_RESEARCH_RAW_s10"
    report = dict(status=status, run_dir=str(run), baseline_gate=gate, budget=budget,
        economic_evaluation_performed=False, selection_performed=False,
        strict_PIT_promotion_eligible=False, production_qualified=False, test_2026_rows_read=0)
    if namespace(auth) in QUOTE_DESCENDANTS:
        report.update(namespace=namespace(auth), quote_domain_ref=auth["quote_domain_ref"],
            parent_account_contract_ref=auth["parent_account_contract_ref"], certified_market_quote_authority=False)
    if namespace(auth) == SESSION_NAMESPACE:
        report.update(research_ca_accounting_convention=auth["research_ca_accounting_convention"], **SESSION_FLAGS)
    write_json_atomic(run / "RESEARCH_ACCOUNT_COMPLETION.json", report)
    return report



def runtime_capability(auth=None):
    """No run/reservation: report whether the separately reviewed owner extension exists."""
    import inspect
    from scripts.v22 import corporate_action_transition_r1 as ca
    missing = []
    if namespace(auth) in QUOTE_DESCENDANTS:
        if "research_quote_domain" not in inspect.signature(replay.execute_market).parameters:
            missing.append("stateful_replay.execute_market.research_quote_domain")
        if "research_quote_domain" not in inspect.signature(replay.run_continuous_account).parameters:
            missing.append("continuous_research_account.research_quote_domain")
    if namespace(auth) == SESSION_NAMESPACE:
        from scripts.research.a2.evaluation import continuous_research_account as shared
        if "research_ca_accounting_convention" not in inspect.signature(replay.execute_market).parameters:
            missing.append("stateful_replay.execute_market.research_ca_accounting_convention")
        if "research_ca_accounting_convention" not in inspect.signature(replay.run_continuous_account).parameters:
            missing.append("continuous_research_account.research_ca_accounting_convention")
        if not callable(getattr(shared, "load_research_ca_accounting_convention", None)):
            missing.append("continuous_research_account.load_research_ca_accounting_convention")
    if "research_account_authority" not in inspect.signature(replay.run_continuous_account).parameters:
        missing.append("continuous_research_account.research_account_authority")
    if not hasattr(ca, "ResearchReconstructedTerminalEvent"):
        missing.append("corporate_action_transition_r1.ResearchReconstructedTerminalEvent")
    return dict(available=not missing, missing=missing, real_execution_admitted=False)


def _distribution(series):
    data = pd.to_numeric(series, errors="coerce").dropna().to_numpy(float)
    return dict(count=len(data), mean=float(np.mean(data)) if len(data) else None,
        min=float(np.min(data)) if len(data) else None, max=float(np.max(data)) if len(data) else None,
        quantiles={str(q): float(np.quantile(data, q)) for q in (0., .25, .5, .75, 1.)} if len(data) else {})


def path_metrics(candidate, frames):
    """Descriptive metrics; no new scores, candidate selection or cost permutations."""
    path = candidate["candidate_id"]
    table = lambda name: frames[name].loc[frames[name].path_id.eq(path)].copy()
    daily = table("daily").sort_values("date"); fills = table("fills")
    actions = table("actions"); positions = table("positions")
    nav = daily.TOTAL_ECONOMIC_NAV.to_numpy(float)
    require(len(nav) and np.isfinite(nav).all() and (nav > 0).all(), "RESEARCH_METRIC_NAV_INVALID")
    peaks = np.maximum.accumulate(np.r_[3000., nav])[1:]
    annual = {}; annual_liquid = {}; previous = 3000.; previous_liquid = 3000.
    for year, group in daily.groupby(daily.date.dt.year, sort=True):
        current = float(group.TOTAL_ECONOMIC_NAV.iloc[-1])
        annual[str(year)] = current / previous - 1.; previous = current
        liquid_end = float(group.LIQUID_NAV.iloc[-1])
        annual_liquid[str(year)] = liquid_end / previous_liquid - 1. if previous_liquid > 0 else None
        previous_liquid = liquid_end
    counts = {str(k): int(v) for k, v in Counter(actions.policy_action).items()} if "policy_action" in actions else {}
    entrants = fills.loc[fills.side.eq("BUY") & fills.index_units_before.le(1e-10)]
    exits = fills.loc[fills.side.eq("SELL") & fills.index_units_after.le(1e-10)]
    entry_sessions = set(pd.to_datetime(entrants.execution_date)); exit_sessions = set(pd.to_datetime(exits.execution_date))
    cost = float(daily.transaction_cost_amount.sum())
    liquid = daily.LIQUID_NAV.to_numpy(float)
    liquid_peaks = np.maximum.accumulate(np.r_[3000., liquid])[1:]
    calendar = {pd.Timestamp(d): i for i, d in enumerate(daily.date)}
    open_spells = {}; completed_spells = []; terminal_closed = 0
    entitlements = frames.get("entitlements", pd.DataFrame())
    if not entitlements.empty:
        entitlements = entitlements.loc[entitlements.path_id.eq(path)]
    transitions = []
    for sequence, fill in enumerate(fills.sort_values(["execution_date", "ticker"], kind="stable").itertuples()):
        if fill.side == "BUY" and fill.index_units_before <= 1e-10:
            transitions.append((pd.Timestamp(fill.execution_date), 1, sequence, str(fill.ticker), "OPEN"))
        elif fill.side == "SELL" and fill.index_units_after <= 1e-10:
            transitions.append((pd.Timestamp(fill.execution_date), 1, sequence, str(fill.ticker), "SELL_CLOSE"))
    if not entitlements.empty:
        for event in entitlements.loc[entitlements.phase.eq("SECURITY_EXTINGUISHED")].itertuples():
            transitions.append((pd.Timestamp(event.session), 0, 0, str(event.ticker), "TERMINAL_CLOSE"))
    for date, _, _, ticker, transition in sorted(transitions):
        index = calendar[date]
        if transition == "OPEN":
            open_spells[ticker] = index
        elif ticker in open_spells:
            completed_spells.append(index - open_spells.pop(ticker))
            terminal_closed += int(transition == "TERMINAL_CLOSE")
    last_index = len(daily) - 1
    right_censored = [last_index - start for start in open_spells.values()]
    durations = []
    if not entitlements.empty:
        for event_id, event in entitlements.groupby("event_id", sort=False):
            recognized = event.loc[event.phase.isin(("RECEIVABLE_RECOGNIZED", "MERGER_RECEIVABLE_RECOGNIZED"))]
            if recognized.empty:
                continue
            begin = pd.Timestamp(recognized.session.iloc[0]); paid = event.loc[event.phase.eq("CASH_PAID")]
            end = pd.Timestamp(paid.session.iloc[-1]) if len(paid) else daily.date.iloc[-1]
            durations.append(dict(event_id=str(event_id), sessions=int(daily.date.ge(begin).mul(daily.date.le(end)).sum()),
                paid=bool(len(paid)), right_censored=not bool(len(paid))))
    traded = float((daily.buy_notional + daily.sell_notional).sum())
    return dict(candidate_id=path, scientific_tuple_sha256=candidate["scientific_tuple_sha256"],
        one_way_bps=candidate["execution_friction"]["one_way_bps"],
        terminal_TOTAL_ECONOMIC_NAV=float(nav[-1]), terminal_LIQUID_NAV=float(daily.LIQUID_NAV.iloc[-1]),
        cumulative_return=float(nav[-1] / 3000. - 1.), cumulative_return_liquid=float(liquid[-1] / 3000. - 1.),
        annual_return=annual, annual_return_liquid=annual_liquid, MaxDD_liquid=float(np.min(liquid / liquid_peaks - 1.)),
        MaxDD=float(np.min(nav / peaks - 1.)), turnover=float(daily.turnover.sum()), trade_count=len(fills),
        BUY_SKIP_count={k: counts.get(k, 0) for k in ("BUY_OR_ADD", "SKIP")},
        HOLD_SELL_count={k: counts.get(k, 0) for k in ("HOLD", "SELL_OR_REDUCE")}, action_counts=counts,
        REPLACE_count=None, REPLACE_identification="NO_PAIRED_REPLACE_ID_IN_FROZEN_DECODER",
        entrant_incumbent_replacement_frequency=dict(entrant_buy_fills=len(entrants),
            incumbent_full_exit_fills=len(exits), cooccurrence_execution_sessions=len(entry_sessions & exit_sessions),
            exact_pair_frequency=None, interpretation="Co-occurrence is descriptive; no invented replacement pair."),
        holding_duration=dict(observed_position_session_age=_distribution(positions.holding_age),
            completed_spells_sessions=_distribution(pd.Series(completed_spells, dtype=float)),
            open_spells_sessions=_distribution(pd.Series(right_censored, dtype=float)),
            open_spells_right_censored=True, terminal_extinguished_stock_spells=terminal_closed),
        Gross_distribution=_distribution(daily.research_gross), Cash_distribution=_distribution(daily.research_cash_weight),
        receivable_exposure=_distribution(daily.receivable_value_usd / daily.TOTAL_ECONOMIC_NAV),
        receivable_duration=dict(exposed_sessions=int(daily.receivable_value_usd.gt(0).sum()),
            terminal_censored=bool(daily.receivable_value_usd.iloc[-1] > 0), per_event=durations),
        cost_drag=dict(actual_cost_usd=cost, charged_cost_over_initial_capital=cost / 3000.,
            charged_cost_over_traded_notional=cost / traded if traded > 0 else None,
            slippage_amount=float(daily.slippage_amount.sum()) if "slippage_amount" in daily else None,
            no_cost_counterfactual_not_run=True), annual_reset=False)


def _hac_effect(differences):
    """Inherited one-sided normal comparison; retain all 220 registered hypotheses."""
    from scipy.stats import norm
    differences = np.asarray(differences, dtype=float)
    require(len(differences) > 0 and np.isfinite(differences).all(), "RESEARCH_CONTRAST_INVALID")
    count = len(differences); mean = float(np.mean(differences)); centered = differences - mean
    variance = float(centered @ centered) / count
    for lag in range(1, min(20, count - 1) + 1):
        variance += 2. * (1. - lag / 21.) * float(centered[lag:] @ centered[:-lag]) / count
    se = float(np.sqrt(max(0., variance) / count))
    statistic = mean / se if se > 0 else None
    p = float(norm.sf(statistic)) if statistic is not None else None
    critical = float(norm.ppf(1. - .05 / 220.))
    return dict(primary="PAIRED_NET_LOG", observations=count, mean_daily_net_log_difference=mean,
        cumulative_net_log_difference=float(differences.sum()), HAC_lag=20, standard_error=se,
        one_sided_p=p, two_sided_p=float(2. * norm.sf(abs(statistic))) if statistic is not None else None,
        Bonferroni_family=220, adjusted_p=min(1., p * 220.) if p is not None else None,
        alpha=.05, one_sided_normal_critical=critical, statistic=statistic,
        frozen_hypothesis_pass=bool(statistic > critical) if statistic is not None else None,
        selection_performed=False, finalist_acceptance_rule="NOT_ADOPTED_BY_THIS_EVALUATOR")


def _log_returns(daily):
    nav = daily.set_index("date").TOTAL_ECONOMIC_NAV.sort_index()
    require(not nav.index.duplicated().any() and np.isfinite(nav).all() and nav.gt(0).all(),
            "RESEARCH_CONTRAST_NAV_INVALID")
    return pd.Series(np.diff(np.log(np.r_[3000., nav.to_numpy(float)])), index=nav.index)


def paired_effect(daily, baseline):
    """Frozen paired net-log comparison, one-sided HAC20 / Bonferroni220 / alpha .05."""
    left = _log_returns(daily); right = _log_returns(baseline)
    require(left.index.equals(right.index), "RESEARCH_PAIRED_CALENDAR_MISMATCH")
    return _hac_effect(left.to_numpy(float) - right.to_numpy(float))


def frozen_contrasts(daily_by_id, specifications):
    """Only Phase0's exact B19 main/interactions; absent paths stay not testable."""
    results = []
    for index, specification in enumerate(specifications):
        terms = specification.get("terms", [[1, specification.get("candidate")],
                                            [-1, specification.get("reference")]])
        contrasts = [("PRIMARY", terms)]
        if "secondary_interaction_terms" in specification:
            contrasts.append(("SECONDARY_INTERACTION", specification["secondary_interaction_terms"]))
        for role, exact_terms in contrasts:
            require(isinstance(exact_terms, list) and len(exact_terms) >= 2 and
                    all(isinstance(t, list) and len(t) == 2 and t[0] in (-1, 1) and
                        isinstance(t[1], str) for t in exact_terms) and
                    sum(t[0] for t in exact_terms) == 0, "RESEARCH_FROZEN_CONTRAST_INVALID")
            item = dict(index=index, kind=specification["kind"], role=role, terms=exact_terms,
                specification=specification, selection_performed=False)
            missing = [cid for _, cid in exact_terms if cid not in daily_by_id]
            if missing:
                results.append(dict(item, status="NOT_TESTABLE_MISSING_QUALIFIED_PATHS", missing=missing))
                continue
            series = [(weight, _log_returns(daily_by_id[cid])) for weight, cid in exact_terms]
            calendar = series[0][1].index
            require(all(calendar.equals(s.index) for _, s in series), "RESEARCH_CONTRAST_CALENDAR_MISMATCH")
            differences = sum(weight * s.to_numpy(float) for weight, s in series)
            annual = {str(year): dict(mean_daily_net_log_difference=float(np.mean(differences[calendar.year == year])),
                cumulative_net_log_difference=float(np.sum(differences[calendar.year == year])))
                for year in sorted(set(calendar.year))}
            results.append(dict(item, status="FROZEN_CONTRAST_EVALUATED", effect=_hac_effect(differences),
                annual=annual, cross_year_directions=[int(np.sign(v["mean_daily_net_log_difference"]))
                    for v in annual.values()]))
    return results


def _clock_before_boundary(value):
    stamp = pd.Timestamp(value)
    boundary = BOUNDARY.tz_localize(stamp.tz) if stamp.tz else BOUNDARY
    return stamp < boundary


def evaluate(run_dir, output_dir):
    """Explicit economic consumer; read only own pinned pre2026 worker artifacts."""
    run, _, auth, candidates = contract(run_dir)
    budget = history_budget(run, candidates, namespace(auth))
    require(budget["outstanding"] == 0, "RESEARCH_EVALUATION_OUTSTANDING")
    out = Path(output_dir).resolve(); assert_safe_output_path(out, kind="results", paths=_roots())
    out.mkdir(parents=True, exist_ok=True)
    ends = {e["candidate_id"]: e for e in _history(run) if e.get("event") in (
        "ACCOUNT_PATH_COMPLETE", "ACCOUNT_PATH_FAILED")}
    reports = []; loaded = {}; daily_by_id = {}; audit_by_id = {}
    for candidate in candidates:
        cid = candidate["candidate_id"]; event = ends.get(cid)
        if not event or event["event"] != "ACCOUNT_PATH_COMPLETE":
            reports.append(dict(candidate_id=cid, status="FAILED" if event else "NOT_EXECUTED")); continue
        audit_path = Path(event["audit_path"]).resolve()
        require(audit_path.is_relative_to(run) and replay.sha(audit_path) == event["audit_sha256"],
                "RESEARCH_EVALUATION_AUDIT_CHANGED")
        audit = _read(audit_path)
        require(audit.get("status") == "RESEARCH_CONTINUOUS_PRE2026_REPLAY_COMPLETE" and
                audit.get("research_contract_sha256") == auth["contract_ref"]["sha256"] and
                audit.get("test_2026_rows_read") == 0, "RESEARCH_EVALUATION_BOUNDARY")
        gates = audit["research_integrity"][cid]; audit_by_id[cid] = gates
        if not all(gates.get("groups", {}).get(k) is True for k in GATES):
            reports.append(dict(candidate_id=cid, status="BLOCKED_RESEARCH_INTEGRITY", integrity_gates=gates)); continue
        key = str(audit_path)
        if key not in loaded:
            frames = {}
            for name, record in audit["artifacts"].items():
                path = Path(record["path"]).resolve()
                require(path.is_relative_to(run) and replay.sha(path) == record["sha256"] and
                        record.get("test_2026_rows_read") == 0, "RESEARCH_EVALUATION_ARTIFACT_CHANGED")
                require(all(_clock_before_boundary(b["max"]) for b in record["clock_bounds"].values()),
                        "RESEARCH_EVALUATION_CLOCK_BOUNDARY")
                frames[name] = pd.read_parquet(path)
            loaded[key] = frames
        daily_by_id[cid] = loaded[key]["daily"].loc[loaded[key]["daily"].path_id.eq(cid)].copy()
        reports.append(dict(status="RESEARCH_ACCOUNT_QUALIFIED", **path_metrics(candidate, loaded[key])))
    baseline = next((r for r in reports if r["candidate_id"] == "RAW_s10" and
                     r["status"] == "RESEARCH_ACCOUNT_QUALIFIED"), None)
    yearly = {}; paired = {}
    for row in reports:
        if "annual_return" not in row:
            continue
        row["yearly_relative_effect"] = {year: value - baseline["annual_return"][year]
            for year, value in row["annual_return"].items()} if baseline else None
        yearly[row["candidate_id"]] = dict(annual_return=row["annual_return"], relative_effect=row["yearly_relative_effect"],
            cross_year_directions=[int(np.sign(x)) for x in row["yearly_relative_effect"].values()]
            if row["yearly_relative_effect"] else None)
        if baseline:
            paired[row["candidate_id"]] = paired_effect(daily_by_id[row["candidate_id"]], daily_by_id["RAW_s10"])
    payloads = {
        "YEARLY_ECONOMIC_COMPARISON.json": dict(per_path=yearly, frozen_paired_net_log=paired,
            frozen_BREADTH19_contrasts=frozen_contrasts(daily_by_id,
                _read(reference(auth["contract_ref"]))["metrics"]["breadth_frozen_contrasts"])),
        "ACTION_BEHAVIOR_COMPARISON.json": {r["candidate_id"]: {k: r.get(k) for k in (
            "action_counts", "REPLACE_count", "REPLACE_identification", "entrant_incumbent_replacement_frequency",
            "holding_duration")} for r in reports},
        "COST_AND_TURNOVER_ANALYSIS.json": dict(
            cost_scenarios="Only original candidate 5/10/20bps; no extra permutations or zero-cost replay.",
            raw_reference="RAW_s10; different-friction cases explicitly retain their original bps.",
            per_path={r["candidate_id"]: {k: r.get(k) for k in (
                "one_way_bps", "cost_drag", "turnover", "Gross_distribution", "Cash_distribution")} for r in reports}),
        "RECEIVABLE_AND_CORPORATE_ACTION_AUDIT.json": dict(settlement_assumed=False, receivable_spendable=False,
            per_path={r["candidate_id"]: dict(
                receivable_exposure=r.get("receivable_exposure"), receivable_duration=r.get("receivable_duration"),
                research_integrity=audit_by_id.get(r["candidate_id"])) for r in reports}),
    }
    for name, data in payloads.items():
        (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pd.json_normalize(reports).to_csv(out / "ACCOUNT_PATH_RESULTS.csv", index=False)
    status = "FROZEN56_ACCOUNT_EVALUATION_COMPLETE" if len(ends) == 57 else (
        "RESEARCH_ACCOUNT_BASELINE_QUALIFIED" if baseline else "RESEARCH_ACCOUNT_BASELINE_BLOCKED")
    return dict(status=status, results_directory=str(out), paths_reported=len(reports),
        selection_performed=False, finalist="NOT_SELECTED_NO_NEW_SCORING_RULE",
        strict_PIT_promotion_eligible=False, production_qualified=False, test_2026_rows_read=0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--candidate", action="append", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run_batch(args.run_dir, args.candidate), sort_keys=True))


if __name__ == "__main__":
    main()
