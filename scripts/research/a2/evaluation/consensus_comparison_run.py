"""Frozen383-coordinate orchestration; existing producers, estimators and account own math."""
from __future__ import annotations

from collections import OrderedDict, Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import pickle
import uuid

import joblib
import pandas as pd

from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.storage.storage_r2a import write_json_atomic
from scripts.research.a2.evaluation import consensus_method_extension as extension
from scripts.research.a2.training import consensus_forecast_recovery as recovery
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash

RESEARCH_ID = "CONSENSUS100_PTO_3000_PRE2026_FULL_METHOD_COMPLETION_R12"
YEARS = (2023, 2024, 2025)
SCOPE_FILE = "COMPARISON_RESEARCH_SCOPE.json"
FREEZE_FILE = "CONSENSUS_METHOD_MATRIX_FREEZE.json"
BRIDGES_SCHEMA = "CONSENSUS_COMPARISON_CACHE_BRIDGES_R12"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def ref(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def pin(reference):
    require(set(reference) >= {"path", "sha256"} and ref(reference["path"])["sha256"] == reference["sha256"],
            "COMPARISON_PIN_CHANGED")
    return Path(reference["path"]).resolve()


def metadata(path, max_bytes=512*1024):
    path = Path(path)
    require(path.stat().st_size <= max_bytes, "COMPARISON_BOUNDED_METADATA_REQUIRED")
    return json.loads(path.read_text(encoding="utf-8"))


class DiskRiskCache(dict):
    """Canonical dict-compatible store; each pickle binds an immutable exact snapshot."""
    def __init__(self, root, max_resident=2, *, entries=()):
        super().__init__()
        self.root = Path(root).resolve()
        assert_safe_output_path(self.root, kind="backtest", paths=resolve())
        require(type(max_resident) is int and max_resident >= 1, "POSITIVE_RESIDENT_CACHE_BOUND_REQUIRED")
        self.max_resident = max_resident
        self._resident = OrderedDict()
        self.root.mkdir(parents=True, exist_ok=True)
        for key, reference in entries:
            self._admit(key, reference)

    def _admit(self, key, reference):
        path = Path(reference["path"]).resolve()
        require(path.is_relative_to(self.root), "RISK_CACHE_REFERENCE_OUTSIDE_OWN_STORE")
        if dict.__contains__(self, key):
            require(dict.__getitem__(self, key) == reference, "RISK_CACHE_EXACT_KEY_CONTENT_CHANGED")
        dict.__setitem__(self, key, dict(reference))

    def __getitem__(self, key):
        reference = dict.__getitem__(self, key)
        path = pin(reference)
        if key not in self._resident:
            self._resident[key] = joblib.load(path)
        self._resident.move_to_end(key)
        while len(self._resident) > self.max_resident:
            self._resident.popitem(last=False)
        return self._resident[key]

    def __setitem__(self, key, value):
        if dict.__contains__(self, key):
            # Compare with the immutable disk value, never a caller-mutated
            # resident alias. NumPy/joblib roundtrips need not preserve bytes.
            self._resident.pop(key, None)
            original = joblib.load(pin(dict.__getitem__(self, key)))
            require(content_hash(original) == content_hash(value), "RISK_CACHE_EXACT_KEY_CONTENT_CHANGED")
            return
        temporary = self.root / ("pending_" + uuid.uuid4().hex + ".joblib")
        joblib.dump(value, temporary)
        reference = ref(temporary)
        destination = self.root / (reference["sha256"] + ".joblib")
        if destination.exists():
            require(ref(destination)["sha256"] == reference["sha256"], "RISK_CACHE_CONTENT_ADDRESS_CHANGED")
            temporary.unlink()  # Only this invocation's unsaved temporary blob.
        else:
            temporary.replace(destination)
        reference["path"] = str(destination)
        self._admit(key, reference)
        self._resident[key] = value
        self._resident.move_to_end(key)
        while len(self._resident) > self.max_resident:
            self._resident.popitem(last=False)

    def get(self, key, default=None):
        return self[key] if key in self else default

    def items(self):
        for key in self:
            yield key, self[key]

    def values(self):
        for key in self:
            yield self[key]

    def update(self, other=(), **kwargs):
        if isinstance(other, DiskRiskCache):
            for key, reference in dict.items(other):
                self._admit(key, reference)
        else:
            for key, value in (other.items() if hasattr(other, "items") else other):
                self[key] = value
        for key, value in kwargs.items():
            self[key] = value

    def snapshot_ref(self):
        entries = [[pickle.dumps(key, protocol=5).hex(), reference] for key, reference in dict.items(self)]
        entries.sort(key=lambda item: item[0])
        value = dict(schema="CONSENSUS_EXACT_RISK_CACHE_SNAPSHOT_R12", root=str(self.root),
                     max_resident=self.max_resident, entries=entries)
        identity = extension._digest(value)
        path = self.root / ("snapshot_" + identity + ".json")
        if path.exists():
            require(metadata(path, 16*1024*1024) == value, "IMMUTABLE_RISK_CACHE_SNAPSHOT_CHANGED")
        else:
            write_json_atomic(path, value)
        return ref(path)

    def __reduce_ex__(self, protocol):
        return (_restore_risk_cache, (self.snapshot_ref(),))


def _restore_risk_cache(reference):
    value = metadata(pin(reference), 16*1024*1024)
    require(value["schema"] == "CONSENSUS_EXACT_RISK_CACHE_SNAPSHOT_R12", "EXACT_RISK_CACHE_SNAPSHOT_REQUIRED")
    return DiskRiskCache(value["root"], value["max_resident"],
        entries=[(pickle.loads(bytes.fromhex(key)), reference) for key, reference in value["entries"]])


def extension_scope(scope):
    comparison, account, budget = scope["comparison"], scope["account"], scope["budget"]
    require(account == dict(currency="USD", type="CASH", initial_cash=3000, fractional=True,
        independent_empty_account_per_coordinate=True, continuous_replay_years=list(YEARS),
        max_positions=20, max_single_weight=.1, max_gross=.95, minimum_trade_usd=5,
        one_way_all_in_bps=10, fixed_per_fill_usd=0, settlement_enabled=True,
        decision_clock="AFTER_SIGNAL_CLOSE_THEN_NEXT_LEGAL_OPEN", same_corporate_action_and_quote_qualification=True),
        "COMPARISON_ORIGINAL_ACCOUNT_CONTRACT_CHANGED")
    require(budget["prior_fit_units"] == 2063 and budget["max_fit_units"] == 10000
        and budget["no_reset"] is True and budget["failed_attempts_count"] is True,
        "COMPARISON_CUMULATIVE_BUDGET_CHANGED")
    return extension.validate_scope(dict(schema=extension.SCHEMA, research_id=RESEARCH_ID,
        forecast_packs=list(comparison["forecast_packs"]), risk_combinations=comparison["risk_combinations"],
        decision_methods=comparison["decision_methods"], selection_boundary_exclusive="2026-01-01",
        initial_cash=3000, prior_fit_units=2063, max_fit_units=10000, lookback_sessions=120,
        controls=list(extension.CONTROLS), fee_config=dict(one_way_all_in_bps=10., fixed_per_fill_usd=0.,
            minimum_trade_usd=5., settlement_enabled=True)))


def plan(run, scope):
    run = Path(run).resolve()
    assert_safe_output_path(run, kind="backtest", paths=resolve())
    require(metadata(run/SCOPE_FILE) == scope and scope["schema"] == "CONSENSUS_COMPARISON_RESEARCH_SCOPE_R12"
        and scope["research_id"] == RESEARCH_ID and scope["output_run"] == str(run)
        and scope["train_and_development_before"] == "2026-01-01"
        and all(scope.get(k) is False for k in ("test2026_read_authorized", "confirmation_read_authorized", "real_trades_authorized", "old_account_state_reused")),
        "EXACT_PRE2026_MASTER_COMPARISON_SCOPE_REQUIRED")
    frozen = extension_scope(scope)
    coordinates_ref = scope["comparison"]["matrix_coordinates_ref"]
    coordinate_path = pin(coordinates_ref)
    require(coordinate_path == run/"COMPARISON_COORDINATES.jsonl" and coordinate_path.stat().st_size <= 256*1024,
            "EXACT_BOUNDED_COORDINATE_MANIFEST_REQUIRED")
    rows = [json.loads(line) for line in coordinate_path.read_text(encoding="utf-8").splitlines() if line]
    require(len(rows) == scope["comparison"]["total_planned_coordinates"] == 383
        and len({r["coordinate_id"] for r in rows}) == 383, "EXACT383_COORDINATES_REQUIRED")
    aliases = extension.catalogue()["exact_owner_decision_aliases"]
    risk_aliases = extension.catalogue()["exact_same_input_risk_aliases"]
    seen, representatives, planned = set(), {}, []
    for row in rows:
        coordinate = extension.Coordinate(*(row[k] for k in ("forecast_pack", "risk_combination", "decision_method")))
        extension.validate_scope(frozen, coordinate)
        require(coordinate.identity not in seen and row["status"] == "PLANNED_NOT_ATTEMPTED", "DUPLICATE_OR_PREFILLED_COMPARISON_COORDINATE")
        seen.add(coordinate.identity)
        combination = frozen["risk_combinations"][coordinate.risk_combination]
        members = {}
        for member, weight in zip(combination["members"], combination["weights"]):
            member = risk_aliases.get(member, member)
            members[member] = members.get(member, 0.) + weight
        key = (coordinate.forecast_pack, extension._digest(sorted(members.items())),
               aliases.get(coordinate.decision_method, coordinate.decision_method))
        representative = representatives.setdefault(key, row["coordinate_id"])
        planned.append(dict(row, exact_alias_of=None if representative == row["coordinate_id"] else representative))
    freeze = metadata(run/FREEZE_FILE)
    root_ref = freeze.get("root_scope_ref", freeze.get("comparison_scope_ref"))
    require(root_ref == ref(run/SCOPE_FILE) and freeze.get("matrix_coordinates_ref") == coordinates_ref,
            "MATRIX_FREEZE_EXACT_MASTER_AND_COORDINATES_REQUIRED")
    require(freeze.get("research_id") == RESEARCH_ID and freeze.get("output_run") == str(run), "MATRIX_FREEZE_RUN_IDENTITY_CHANGED")
    return frozen, planned, ref(run/FREEZE_FILE)


def qualification(coordinate, frozen, *, bank_dependencies, r2_fit, scenarios, references, rl_factory):
    members = frozen["risk_combinations"][coordinate.risk_combination]["members"]
    if any(m in extension.R2_METHODS for m in members) and not callable(r2_fit):
        return "TYPED_R2_QUALIFIED_INPUT_PROVIDER_REQUIRED"
    if any(m in ("SINGLE_INDEX", "INDUSTRY", "FUNDAMENTAL") for m in members) and not callable(bank_dependencies):
        return "QUALIFIED_MARKET_OR_EXPOSURE_DEPENDENCIES_REQUIRED"
    if "NONLINEAR_SHRINKAGE" in members:
        return "GENUINE_NONLINEAR_SHRINKAGE_BACKEND_NOT_SNAPSHOTTED"
    if coordinate.decision_method in extension.SCENARIO_METHODS and not scenarios:
        return "QUALIFIED_MATURE_SHAREHOLDER_H5_SCENARIOS_REQUIRED"
    if coordinate.decision_method in ("reference_regularization", "tracking_error") and not references:
        return "QUALIFIED_FROZEN_REFERENCE_REQUIRED"
    if coordinate.decision_method in extension.EXTERNAL_DECISION_METHODS and not callable(rl_factory):
        return "QUALIFIED_FROZEN_RL_POLICY_FACTORY_REQUIRED"
    return None


def bank_adapter(runner, run, receipt, cache, freeze_ref, bridges):
    values = runner.values
    pins = dict(runner.source_pins(), comparison=ref(__file__), extension=ref(extension.__file__))
    log = run/"FIT_LOG.jsonl"
    old_started = getattr(runner, "_carryover_fit_started", lambda token: False)
    def fit(method, past, *, params, dependencies, event):
        require(pd.Timestamp(past.index.max()) < pd.Timestamp(params["fit_cutoff"]) <= pd.Timestamp("2026-01-01"),
                "PRE2026_RISK_FIT_INPUT_REQUIRED")
        # Reconstruct only the old owner's exact cache identity, never a new
        # speculative retry identity. A code-routing change is not new evidence.
        legacy = hashlib.sha256(pd.util.hash_pandas_object(past, index=True).to_numpy().tobytes())
        legacy.update(repr(tuple(map(str, past.columns))).encode())
        legacy.update(str(past.attrs.get("source_id", "UNKNOWN")).encode())
        legacy_key = (pd.Timestamp(event["month"]), method, 120, legacy.hexdigest())
        legacy_event = dict(event, input_sha256=legacy.hexdigest())
        legacy_token = values.digest(dict(source_pins=runner.source_pins(), event=legacy_event))
        exact_domain = hashlib.sha256(pd.util.hash_pandas_object(past, index=True).to_numpy().tobytes())
        exact_domain.update(repr(tuple(map(str, past.columns))).encode())
        exact_domain.update(extension._digest(dict(fit_assets=tuple(past.columns), source_metadata=past.attrs)).encode())
        same_legacy_domain = not dependencies and exact_domain.hexdigest() == event["input_sha256"]
        if same_legacy_domain and legacy_key in cache and tuple(event["assets"]) == tuple(past.columns):
            bundle = cache[legacy_key]
            expected = extension.bank._parameters(method, params)
            if (tuple(bundle.assets) == tuple(past.columns) and tuple(bundle.fitted_dates) == tuple(d.isoformat() for d in past.index)
                and bundle.specification == expected):
                bridges.append(dict(legacy_cache_key=repr(legacy_key), input_sha256=event["input_sha256"],
                    legacy_started_token=legacy_token, disposition="EXACT_INPUT_DOMAIN_PARAMS_SOURCE_CACHE_BRIDGE", status=bundle.status))
                return bundle
        token = values.digest(dict(source_pins=pins, event=event, parameters=extension.bank._parameters(method, params), freeze_ref=freeze_ref))
        require(not (same_legacy_domain and old_started(legacy_token)), "OLD_FAILED_OR_UNBRIDGED_CHECKPOINT_TUPLE_NO_RETRY")
        require(not any(e.get("event") == "FIT_STARTED" and e.get("reuse_tuple_sha256") == token for e in values._events(log)),
                "MATRIX_FAILED_OR_UNCHECKPOINTED_TUPLE_NO_RETRY")
        spent = 2063 + sum(e.get("fit_units", 0) for e in values._events(log) if e.get("event") == "FIT_STARTED")
        if spent + extension.risk_fit_unit_upper(method) > 10000:
            receipt["budget_exhausted"] = True
            raise RuntimeError("CUMULATIVE_FIT_BUDGET_EXHAUSTED; NO_PARTIAL_BANK_RESERVATION")
        return values._fit_job("risk", method, past, None, None, None, dependencies, [], params,
            log=log, auth=dict(max_fit_units=10000, budget_bucket="consensus_comparison_risk"), prior=2063,
            year=pd.Timestamp(params["fit_cutoff"]).year, tuple_sha=token, receipt=receipt,
            worker_target=extension.risk_fit_worker)
    return fit


def _publications(run, pack, specification, reader, runner, provider=None):
    provider = recovery.published_fusion_forecasts if provider is None else provider
    require(callable(provider), "QUALIFIED_PUBLICATION_PROVIDER_REQUIRED")
    frames, pins = [], []
    for year in YEARS:
        frame, reference = provider(run, specification["fusion_method"], year,
            reader, packet_id=specification["packet_id"])
        dates = pd.to_datetime(frame["signal_date"])
        require(not frame.empty and dates.ge(f"{year}-01-01").all() and dates.lt(f"{year+1}-01-01").all(),
                "EXACT_PRE2026_PUBLICATION_YEAR_REQUIRED")
        require(reference["year"] == year and reference["packet_id"] == specification["packet_id"]
            and reference["method"] == specification["fusion_method"], "PACK_PUBLICATION_IDENTITY_CHANGED")
        frames.append(frame); pins.append(reference)
    return runner.compatible_forecasts(pd.concat(frames, ignore_index=True)), pins


def run_all(run, runner, loaded, reader, freeze_ref, scope, *, bank_dependencies=None,
            r2_fit=None, scenarios=None, references=None, rl_factory=None, publication_provider=None):
    """Execute only the frozen manifest; every actual cell owns a fresh account."""
    run = Path(run).resolve()
    frozen, planned, matrix_freeze_ref = plan(run, scope)
    publisher = recovery.published_fusion_forecasts if publication_provider is None else publication_provider
    require(callable(publisher) and hasattr(publisher, "__code__"), "SOURCE_BOUND_PUBLICATION_FUNCTION_REQUIRED")
    publisher_identity = dict(source=ref(publisher.__code__.co_filename), name=publisher.__qualname__)
    require(callable(getattr(runner, "_matrix_evaluation_source", None))
        and callable(getattr(runner, "_matrix_execution_guard", None)), "LEGAL_PRIVATE_C_MATRIX_RUNNER_REQUIRED")
    actual_run, _, actual_freeze = runner.contract(run)
    require(Path(actual_run).resolve() == run and actual_freeze == freeze_ref, "EXACT_C_OUTPUT_RUN_AND_FREEZE_REQUIRED")
    require(metadata(pin(freeze_ref)).get("method_matrix_scope_ref") == matrix_freeze_ref,
            "C_ADMISSION_MUST_BIND_THIS_EXACT_MATRIX_FREEZE")
    returns = loaded["returns"]
    require(isinstance(returns, pd.DataFrame) and not returns.empty and isinstance(returns.index, pd.DatetimeIndex)
        and returns.index.max() < pd.Timestamp("2026-01-01"), "QUALIFIED_PRE2026_RETURNS_REQUIRED")
    dates = pd.DatetimeIndex(loaded["market"].dates)
    require(dates.min() >= pd.Timestamp("2023-01-01") and dates.max() < pd.Timestamp("2026-01-01")
        and set(dates.year) == set(YEARS), "EXACT_CONTINUOUS_2023_2025_MARKET_REQUIRED")
    root = run/"evaluation"/"consensus_comparison"
    root.mkdir(parents=True, exist_ok=True)
    index_path = root/"status_index.json"
    identity = extension._digest(dict(master=ref(run/SCOPE_FILE), matrix=matrix_freeze_ref, consumer=freeze_ref,
        comparison=ref(__file__), extension=ref(extension.__file__), publication_provider=publisher_identity))
    if index_path.exists():
        index = metadata(index_path)
        require(index["identity_sha256"] == identity and [r["coordinate_id"] for r in index["coordinates"]] ==
            [r["coordinate_id"] for r in planned], "COMPARISON_RESUME_IDENTITY_CHANGED")
    else:
        index = dict(schema="CONSENSUS_COMPARISON_STATUS_R12", identity_sha256=identity,
            coordinates=[dict(r, actual_account_attempted=False) for r in planned])
        write_json_atomic(index_path, index)
    cache = DiskRiskCache(root/"risk_store", max_resident=2)
    # Initialize through the same C guard before admitting any new-run snapshot.
    def initialize(run, cache):
        return cache
    runner._matrix_execution_guard(initialize)(run, cache)
    if index.get("risk_cache_snapshot_ref"):
        cache.update(_restore_risk_cache(index["risk_cache_snapshot_ref"]))
    bridge_path = root/"cache_bridges.json"
    bridge_record = metadata(bridge_path, 16*1024*1024) if bridge_path.exists() else dict(schema=BRIDGES_SCHEMA, bridges=[])
    require(isinstance(bridge_record, dict) and bridge_record.get("schema") == BRIDGES_SCHEMA
        and isinstance(bridge_record.get("bridges"), list), "EXACT_COMPARISON_CACHE_BRIDGES_SCHEMA_REQUIRED")
    bridges = bridge_record["bridges"]
    packs, pack_errors = {}, {}
    by_id = {r["coordinate_id"]: r for r in index["coordinates"]}
    for row in index["coordinates"]:
        if row["status"] == "IN_PROGRESS":
            coordinate = extension.Coordinate(*(row[k] for k in ("forecast_pack", "risk_combination", "decision_method")))
            receipt_path = run/"evaluation"/"consensus_account"/("matrix__"+coordinate.identity)/"receipt.json"
            terminal = receipt_path.exists() and metadata(receipt_path).get("status") in ("COMPLETE", "NOT_TESTABLE", "FAILED_NO_RETRY")
            row.update(status="PLANNED_NOT_ATTEMPTED" if terminal else "FAILED_NO_RETRY",
                       reason="RESUME_CHECKPOINT_VALIDATED_BY_ORIGINAL_E" if terminal else "UNRECEIPTED_ACCOUNT_ATTEMPT_PRESERVED_NO_RETRY")
        if row["status"] != "PLANNED_NOT_ATTEMPTED":
            if row.get("receipt_ref"): pin(row["receipt_ref"])
            continue
        coordinate = extension.Coordinate(*(row[k] for k in ("forecast_pack", "risk_combination", "decision_method")))
        if row["exact_alias_of"] is not None:
            original = by_id[row["exact_alias_of"]]
            require(original["status"] != "PLANNED_NOT_ATTEMPTED", "ALIAS_REQUIRES_PRIOR_TERMINAL_COORDINATE")
            row.update(status="EXACT_ALIAS_REUSED" if original["status"] == "COMPLETE" else original["status"],
                alias_is_independent_mechanism=False, alias_target_status=original["status"],
                receipt_ref=original.get("receipt_ref"), reason=original.get("reason"))
            write_json_atomic(index_path, index);continue
        reason = qualification(coordinate, frozen, bank_dependencies=bank_dependencies, r2_fit=r2_fit,
            scenarios=scenarios, references=references, rl_factory=rl_factory)
        if reason:
            row.update(status="INPUT_QUALIFICATION_BLOCKED", reason=reason)
            write_json_atomic(index_path, index);continue
        pack = coordinate.forecast_pack
        if pack not in packs and pack not in pack_errors:
            try: packs[pack] = _publications(run, pack, scope["comparison"]["forecast_packs"][pack], reader, runner, publisher)
            except Exception as error: pack_errors[pack] = type(error).__name__ + ":" + str(error)
        if pack in pack_errors:
            row.update(status="INPUT_QUALIFICATION_BLOCKED", reason=pack_errors[pack])
            write_json_atomic(index_path, index);continue
        forecasts, publication_pins = packs[pack]
        row.update(status="IN_PROGRESS", account_entry_requested=True)
        write_json_atomic(index_path, index)
        active_receipt = {}
        def bounded_bank_fit(method, past, *, params, dependencies, event):
            require("receipt" in active_receipt, "ACCOUNT_RECEIPT_REQUIRED_BEFORE_PHYSICAL_FIT")
            return bank_adapter(runner, run, active_receipt["receipt"], cache, matrix_freeze_ref, bridges)(
                method, past, params=params, dependencies=dependencies, event=event)
        def factory(forecasts, returns, config, fee_config, actual, receipt, shared_cache, cell_identity):
            require(Path(actual).resolve() == run and shared_cache is cache, "ONE_C_GUARDED_RISK_CACHE_INSTANCE_REQUIRED")
            active_receipt["receipt"] = receipt
            policy = binding.ConsensusJointPolicy(forecasts, returns, config=config, fee_config=fee_config,
                shared_risk_cache=cache)
            row["actual_account_attempted"] = True
            return policy
        def external_factory(method, forecasts, past_daily_returns, *, config, fee_config, **owner_kwargs):
            # RL controls activity over the exact same frozen P/R proposal.
            # Its base therefore uses this cell's receipt, global fit budget and
            # C-guarded cache; Root supplies only the frozen activity policy.
            base_coordinate = extension.Coordinate(coordinate.forecast_pack, coordinate.risk_combination, "cost_aware")
            base = extension.bind_joint(runner.joint, scope=frozen, coordinate=base_coordinate,
                bank_fit=bounded_bank_fit, bank_dependencies=bank_dependencies, r2_fit=r2_fit,
                scenarios=scenarios, references=references)
            base_policy = base.ConsensusJointPolicy(forecasts, past_daily_returns,
                config=base.PolicyConfig(coordinate.risk_combination, "cost_aware", 120),
                fee_config=fee_config, **owner_kwargs)
            return rl_factory(method, forecasts, past_daily_returns, config=config, fee_config=fee_config,
                base_policy=base_policy, **owner_kwargs)
        try:
            binding = extension.bind_joint(runner.joint, scope=frozen, coordinate=coordinate,
                bank_fit=bounded_bank_fit, bank_dependencies=bank_dependencies, r2_fit=r2_fit,
                scenarios=scenarios, references=references, external_policy_factory=external_factory if callable(rl_factory) else None)
            result = extension.evaluate_flow(runner, coordinate, run, coordinate.forecast_pack,
                coordinate.risk_combination, coordinate.decision_method, forecasts, returns, loaded,
                freeze_ref, publication_pins, cache, binding=binding, make_policy=factory)
            receipt_ref = ref(result["receipt_path"])
            require(metadata(pin(receipt_ref)) == json.loads(json.dumps(result, default=str)), "ACTUAL_ACCOUNT_RECEIPT_CHANGED")
            row.update(status="BUDGET_EXHAUSTED_NOT_COMPLETED" if result.get("budget_exhausted") else
                "INPUT_QUALIFICATION_BLOCKED" if result["status"] == "NOT_TESTABLE" else result["status"],
                account_receipt_status=result["status"], receipt_ref=receipt_ref,
                reason=result.get("failure", {}).get("reason", result.get("reason")))
        except Exception as error:
            row.update(status="FAILED_NO_RETRY", reason=type(error).__name__ + ":" + str(error))
        index["risk_cache_snapshot_ref"] = cache.snapshot_ref()
        write_json_atomic(bridge_path, dict(schema=BRIDGES_SCHEMA, bridges=bridges))
        write_json_atomic(index_path, index)
    summary = dict(schema="CONSENSUS_COMPARISON_EXECUTION_SUMMARY_R12", status_counts=dict(Counter(r["status"] for r in index["coordinates"])),
        identity_sha256=identity, coordinates_ref=ref(index_path), planned_coordinates=383,
        actual_account_attempts=sum(r["actual_account_attempted"] for r in index["coordinates"]),
        all_planned_coordinates_resolved=all(r["status"] not in ("PLANNED_NOT_ATTEMPTED", "IN_PROGRESS") for r in index["coordinates"]),
        budget_exhaustion_is_incomplete=any(r["status"] == "BUDGET_EXHAUSTED_NOT_COMPLETED" for r in index["coordinates"]),
        exact_cache_bridges=bridges, cache_resident_limit=2,
        performance_gap="C initial legacy cache imports eagerly once; E budget-summary iterates disk bundles; cell states bind immutable refs, not all bundles",
        independent_holdout_claim=False, test2026_rows_read=0, confirmation_rows_read=0, economic_PASS=False)
    write_json_atomic(root/"summary.json", summary)
    return summary
