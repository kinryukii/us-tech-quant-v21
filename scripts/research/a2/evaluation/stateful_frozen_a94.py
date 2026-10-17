"""Exact A94 runtime seam over the existing stateful replay/account owners.

No inputs, models, inference, source certification or alternate account engine.
The original inventory chooses OLD57/NEW37 and each original friction batch.
"""
from __future__ import annotations
from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
import json
import hashlib
import pandas as pd

from scripts.research.a2.evaluation import frozen_test_authority as authority
from scripts.research.a2.evaluation import frozen_a94_profile as profile
from scripts.research.a2.training import stateful_replay as replay
from scripts.research.a2.training.stateful_account import StatefulOverlay
from scripts.research.a2.training.stateful_final_action import FinalActionOverlay
from scripts.research.a2.training.stateful_final_action_packets import decode_resource_proposals

_SEAL = object()
_SOURCE_KWARGS = frozenset(("events", "known_at", "unsupported", "entitlement_enabled",
    "entitlement_events", "entitlement_security_tickers", "entitlement_source_binding"))


def _require(ok, code):
    if not ok:
        raise ValueError(code)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class _BatchStamp:
    """Per-instance immutable custody; dataclasses.replace cannot rewrite it."""
    __slots__ = ("_bound",)

    def __init__(self, token, group, ids, candidates, scoped, friction, coverage):
        _require(token is _SEAL, "A94_PREPARED_BATCH_REQUIRED")
        object.__setattr__(self, "_bound", (token, group, ids, candidates, scoped,
            _canonical(candidates), _canonical(friction), _canonical(coverage)))

    def __setattr__(self, name, value):
        raise TypeError("A94 batch custody is immutable")

    def verify(self, batch):
        token, group, ids, candidates, scoped, specs, cost, _ = self._bound
        _require(token is _SEAL and batch.source_group == group and batch.candidate_ids == ids
            and batch.candidates is candidates and batch.scoped_authority is scoped
            and batch.canonical_specs == specs and _canonical(batch.execution_friction) == cost,
            "A94_BATCH_CUSTODY_CHANGED")


def _digest(value):
    digest = hashlib.sha256()
    encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    for chunk in encoder.iterencode(value):
        digest.update(chunk.encode("utf-8"))
    return digest.hexdigest()


@dataclass(frozen=True)
class PreparedBatch:
    source_group: str
    candidate_ids: tuple
    candidates: tuple
    scoped_authority: authority.ValidatedDescriptiveAuthority
    execution_friction: dict
    canonical_specs: str = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    def __reduce__(self):
        raise TypeError("Rebuild exact A94 batches from validated physical authority")


def prepare_batches(admitted, candidates):
    """Validate the source-ready subset against all94; preserve original cost groups.

    The returned batches contain task-owned copies. Mutating the caller's list
    cannot change execution; mutating a returned batch is detected at execution.
    The inventory read is metadata-only and occurs once, never per decision.
    """
    admitted = authority.load_descriptive_authority(admitted)
    _require(admitted.task_id in profile.profile_tasks(), "A94_EXACT_TASK_REQUIRED")
    provenance = json.loads(admitted.provenance_json)
    ready = provenance.get("source_ready_policy_ids", admitted.allowed_path_ids)
    _require(isinstance(ready, (list, tuple)) and bool(ready)
        and tuple(ready) == tuple(cid for cid in admitted.allowed_path_ids if cid in ready)
        and len(set(ready)) == len(ready), "A94_SOURCE_READY_POLICIES_REQUIRED")
    _require(isinstance(candidates, (list, tuple)), "A94_SOURCE_READY_POLICIES_REQUIRED")
    snapshot = tuple(deepcopy(candidates))
    _require(len(snapshot) == len(ready) and tuple(c.get("candidate_id") for c in snapshot if isinstance(c, dict))
        == tuple(ready), "A94_SOURCE_READY_POLICIES_REQUIRED")
    checked = authority.validate_descriptive_policy(admitted, snapshot)
    provenance = json.loads(checked.provenance_json)
    inventory = profile._document(provenance["candidate_manifest_ref"])
    qualification = profile._document(provenance["source_qualification_ref"])
    _require(qualification.get("task_id") == admitted.task_id
        and qualification.get("source_refs") == provenance.get("source_refs"), "A94_SOURCE_QUALIFICATION_BINDING_CHANGED")
    new_ids = [cid for cid in ready if (profile.required_action_roles(cid) if admitted.task_id == profile.TASK else profile.required_action_roles(cid, authority=admitted))]
    coverage = None
    if new_ids:
        coverage = qualification.get("action_packet_coverage")
        _require(isinstance(coverage, dict) and coverage.get("source_ref") == provenance["source_refs"]["action_inputs"]
            and coverage.get("candidate_ids") == new_ids
            and all(type(coverage.get(k)) is int and coverage[k] == 0 for k in
                ("new_fit_count", "future_unmatured_probe_outcomes_read", "outcome_columns_in_model_features")),
            "A94_ACTION_COMPUTATION_COVERAGE_REQUIRED")
        needs_probe = any(role in ("R6:duration", "R10:HAZARD") for cid in new_ids for role in (profile.required_action_roles(cid) if admitted.task_id == profile.TASK else profile.required_action_roles(cid, authority=admitted)))
        if needs_probe:
            probe = coverage.get("matured_probe_state")
            _require(isinstance(probe, dict) and probe.get("source_ref") == provenance["source_refs"]["action_inputs"]
                and probe.get("causal_rule") == "previous_probe_mature_date < current_signal_date"
                and probe.get("prior_probe_mature_before_current_decision") is True
                and isinstance(probe.get("key_sha256"), str) and len(probe["key_sha256"]) == 64
                and all(c in "0123456789abcdef" for c in probe["key_sha256"]), "A94_CAUSAL_PROBE_BINDING_REQUIRED")
            probe_as_of = pd.to_datetime(probe.get("as_of_utc"), errors="coerce")
            _require(isinstance(probe_as_of, pd.Timestamp) and not pd.isna(probe_as_of)
                and probe_as_of.tzinfo is not None and probe_as_of <= checked.as_of,
                "A94_CAUSAL_PROBE_BINDING_REQUIRED")
    # Custody of an upstream per-decision proof is not a PIT source certification.
    rows = inventory.get("candidates")
    if profile.repaired_group_calendar_capable(checked):
        _require(isinstance(rows, list), "A94_ORIGINAL_INVENTORY_REQUIRED")
        rows = [row for row in rows if isinstance(row, dict)
                and row.get("candidate_id") == checked.allowed_path_ids[0]]
    _require(isinstance(rows, list) and [r.get("candidate_id") for r in rows if isinstance(r, dict)]
        == list(admitted.allowed_path_ids), "A94_ORIGINAL_INVENTORY_REQUIRED")
    legacy = admitted.task_id == profile.TASK
    if legacy:
        _require(len(rows) == 94 and Counter(r.get("source_group") for r in rows) == {"OLD57": 57, "NEW37": 37},
            "A94_ORIGINAL_SOURCE_GROUPS_REQUIRED")
    def owner(row):
        return row["source_group"] if legacy else row["runtime_owner"]
    original_groups = {(owner(row), row["specification"]["execution_friction"]["one_way_bps"]) for row in rows}
    if legacy:
        _require(original_groups == {("OLD57", 5), ("OLD57", 10), ("OLD57", 20), ("NEW37", 10)},
            "A94_ORIGINAL_FOUR_BATCHES_REQUIRED")
    by_id = {row["candidate_id"]:row for row in rows}
    action_owner = "NEW37" if legacy else "FINAL_ACTION_OVERLAY"
    _require(new_ids == [cid for cid in ready if owner(by_id[cid]) == action_owner], "A94_ORIGINAL_SOURCE_GROUPS_REQUIRED")
    groups = {}
    for candidate in snapshot:
        row = by_id[candidate["candidate_id"]]
        friction = candidate["execution_friction"]
        _require(not legacy or row["source_group"] == "OLD57" or friction.get("one_way_bps") == 10,
            "A94_NEW37_ORIGINAL_10BPS_REQUIRED")
        key = (owner(row), _canonical(friction))
        groups.setdefault(key, []).append(candidate)
    _require(all((group, json.loads(cost)["one_way_bps"]) in original_groups for group, cost in groups),
        "A94_ORIGINAL_FOUR_BATCHES_REQUIRED")
    batches = []
    for (group, _), specs in groups.items():
        same = tuple(specs)
        scoped = authority.validate_descriptive_policy(checked, same)
        batches.append(PreparedBatch(group, tuple(c["candidate_id"] for c in same), same, scoped,
            deepcopy(same[0]["execution_friction"]), _canonical(same),
            _BatchStamp(_SEAL, group, tuple(c["candidate_id"] for c in same), same, scoped,
                same[0]["execution_friction"], coverage if group == action_owner else None)))
    return tuple(batches)


def _check(batch):
    _require(type(batch) is PreparedBatch and type(batch._seal) is _BatchStamp, "A94_PREPARED_BATCH_REQUIRED")
    batch._seal.verify(batch)
    authority.load_descriptive_authority(batch.scoped_authority)
    _require(batch.scoped_authority.task_id in profile.profile_tasks()
        and batch.source_group in (("OLD57", "NEW37") if batch.scoped_authority.task_id == profile.TASK
                                  else ("STATEFUL_OVERLAY", "FINAL_ACTION_OVERLAY"))
        and batch.candidate_ids == tuple(c.get("candidate_id") for c in batch.candidates)
        and batch.scoped_authority.runtime_policy_ids == batch.candidate_ids
        and _canonical(batch.candidates) == batch.canonical_specs, "A94_ACTUAL_POLICY_SNAPSHOT_CHANGED")
    _require(all(_canonical(c["execution_friction"]) == _canonical(batch.execution_friction)
        for c in batch.candidates), "A94_ACTUAL_FRICTION_CHANGED")
    return batch


def _packet_payload(batch, action_packets):
    rows = []
    for cid in batch.candidate_ids:
        by_day = action_packets[cid]
        _require(isinstance(by_day, Mapping), "A94_ACTION_COMPUTATION_COVERAGE_REQUIRED")
        sessions = []
        for key, records in by_day.items():
            day = pd.Timestamp(key)
            _require(not pd.isna(day) and day.tzinfo is None and day == day.normalize()
                and isinstance(records, (list, tuple)) and all(isinstance(r, dict) for r in records),
                "A94_ACTION_PACKET_SCHEMA_CHANGED")
            sessions.append(dict(signal_date=str(day.date()), proposals=list(records)))
        sessions.sort(key=lambda r:r["signal_date"])
        _require(len({r["signal_date"] for r in sessions}) == len(sessions), "A94_ACTION_PACKET_DUPLICATE_SESSION")
        rows.append(dict(candidate_id=cid, sessions=sessions))
    return rows


def _sid_payload(sid_by_key):
    rows = []
    for key, value in sid_by_key.items():
        _require(isinstance(key, tuple) and len(key) == 2 and isinstance(key[1], str), "A94_SID_MAP_SCHEMA_CHANGED")
        day = pd.Timestamp(key[0])
        _require(not pd.isna(day) and day.tzinfo is None and day == day.normalize(), "A94_SID_MAP_SCHEMA_CHANGED")
        # Missing identity stays invalid; only its fingerprint uses JSON null.
        encoded = None if pd.isna(value) else value
        rows.append([str(day.date()), key[1], encoded])
    rows.sort(key=lambda r:(r[0],r[1]))
    _require(len({(r[0],r[1]) for r in rows}) == len(rows), "A94_SID_MAP_SCHEMA_CHANGED")
    return rows


def _action_coverage(batch, market, action_packets, sid_by_key):
    proof = json.loads(batch._seal._bound[-1])
    dates = pd.DatetimeIndex(market.dates)
    _require(len(dates) >= 2 and dates.tz is None and dates.equals(dates.normalize())
        and dates.is_unique and dates.is_monotonic_increasing, "A94_ACTION_CALENDAR_CHANGED")
    calendar = [str(d.date()) for d in dates]
    decisions = calendar  # Original owner also audits a terminal decision without a later fill.
    _require(proof.get("candidate_ids") == list(batch.candidate_ids) and proof.get("decision_dates") == decisions,
        "A94_ACTION_COMPUTATION_COVERAGE_REQUIRED")
    payload = _packet_payload(batch, action_packets)
    sid = _sid_payload(sid_by_key)
    _require(proof.get("action_packets_sha256") == _digest(payload)
        and proof.get("sid_by_key_sha256") == _digest(sid),
        "A94_ACTION_COMPUTATION_PAYLOAD_CHANGED")
    statuses = proof.get("computed_sessions")
    _require(isinstance(statuses, dict) and set(statuses) == set(batch.candidate_ids),
        "A94_ACTION_COMPUTATION_COVERAGE_REQUIRED")
    for item in payload:
        days = {r["signal_date"]:r["proposals"] for r in item["sessions"]}
        _require(set(days) == set(decisions), "A94_ACTION_COMPUTATION_COVERAGE_REQUIRED")
        expected = {day:dict(status="COMPUTED_WITH_PROPOSALS" if days[day] else "COMPUTED_NO_PROPOSALS",
            proposal_count=len(days[day])) for day in decisions}
        _require(_canonical(statuses[item["candidate_id"]]) == _canonical(expected),
            "A94_ACTION_COMPUTATION_COVERAGE_REQUIRED")
    _require(all(row[0] in calendar for row in sid), "A94_SID_MAP_OUTSIDE_WINDOW")
    by_policy = {item["candidate_id"]:{r["signal_date"]:r["proposals"] for r in item["sessions"]} for item in payload}
    return {day:(_digest([dict(candidate_id=cid, proposals=by_policy[cid][day]) for cid in batch.candidate_ids]),
        _digest([row for row in sid if row[0] == day])) for day in decisions}


@dataclass(frozen=True)
class BoundActionCalendar:
    """Validated full-calendar source reused by fresh random accounts, not state."""
    candidate_ids: tuple
    source_proof_json: str = field(repr=False)
    packets: object = field(repr=False)
    sid: object = field(repr=False)
    dates: tuple
    commitments: object = field(repr=False)
    _proof: object = field(repr=False, compare=False)

    def __reduce__(self):
        raise TypeError("Rebind the original complete action calendar")


def bind_action_calendar(batch, market, action_packets, sid_by_key):
    """Validate the immutable full source proof once; never compute predictions."""
    _check(batch)
    _require((batch.scoped_authority.task_id == profile.ALL_TASK
        or profile.repaired_group_calendar_capable(batch.scoped_authority))
        and batch.source_group == "FINAL_ACTION_OVERLAY", "ALL_A_ACTION_CALENDAR_SCOPE_REQUIRED")
    dates = pd.DatetimeIndex(market.dates)
    _require(dates[0] == batch.scoped_authority.start and dates[-1] == batch.scoped_authority.end,
        "ALL_A_ACTION_CALENDAR_FULL_SCOPE_REQUIRED")
    commitments = MappingProxyType(_action_coverage(batch, market, action_packets, sid_by_key))
    proof_json = batch._seal._bound[-1]
    days = tuple(str(d.date()) for d in dates)
    provenance = json.loads(batch.scoped_authority.provenance_json)
    source = _canonical(provenance["source_qualification_ref"])
    stamp = (_SEAL, batch.candidate_ids, proof_json, action_packets, sid_by_key, days, commitments, source)
    return BoundActionCalendar(batch.candidate_ids, proof_json, action_packets, sid_by_key, days, commitments, stamp)


def _window_action_calendar(batch, market, value):
    _require(type(value) is BoundActionCalendar and len(value._proof) == 8,
        "ALL_A_BOUND_ACTION_CALENDAR_REQUIRED")
    token, ids, proof, packets, sid, days, commitments, source = value._proof
    _require(token is _SEAL and value.candidate_ids == ids == batch.candidate_ids
        and value.source_proof_json == proof == batch._seal._bound[-1]
        and value.packets is packets and value.sid is sid and value.dates == days
        and value.commitments is commitments and (batch.scoped_authority.task_id == profile.ALL_TASK
        or profile.repaired_group_calendar_capable(batch.scoped_authority))
        and _canonical(json.loads(batch.scoped_authority.provenance_json)["source_qualification_ref"]) == source,
        "ALL_A_ACTION_CALENDAR_CUSTODY_CHANGED")
    dates = pd.DatetimeIndex(market.dates)
    _require(len(dates) >= 2 and dates.tz is None and dates.equals(dates.normalize())
        and dates.is_monotonic_increasing and dates.is_unique
        and dates[0] == batch.scoped_authority.start and dates[-1] == batch.scoped_authority.end,
        "ALL_A_ACTION_WINDOW_CHANGED")
    selected = tuple(str(d.date()) for d in dates)
    _require(selected == tuple(d for d in days if selected[0] <= d <= selected[-1]),
        "ALL_A_ACTION_WINDOW_NOT_EXACT_SUBSET")
    # Only used session values reach _ActionGuard; that guard rechecks the original
    # full-source daily hashes before and after every decision. No cohort reset.
    return packets, sid, {d:commitments[d] for d in selected}


class _ActionGuard:
    """Only a current-session private copy reaches the fixed action overlay."""
    def __init__(self, batch, packets, sid, commitments):
        self.batch, self.source_packets, self.source_sid = batch, packets, sid
        self.commitments = commitments
        self.actions, self.sid = {cid:{} for cid in batch.candidate_ids}, {}
        self.sid_count = len(sid)
        self.sid_keys = {}
        for key in sid:
            self.sid_keys.setdefault(str(pd.Timestamp(key[0]).date()), []).append(key)
        self.day = None

    def stage(self, date):
        day = pd.Timestamp(date)
        key = str(day.date())
        _require(key in self.commitments and set(self.source_packets) == set(self.batch.candidate_ids)
            and len(self.source_sid) == self.sid_count, "A94_ACTION_INPUT_SNAPSHOT_CHANGED")
        self.actions.clear(); self.sid.clear()
        for cid in self.batch.candidate_ids:
            by_day = self.source_packets[cid]
            _require(day in by_day, "A94_ACTION_INPUT_SNAPSHOT_CHANGED")
            self.actions[cid] = {day:deepcopy(by_day[day])}
        for original in self.sid_keys.get(key, ()):
            _require(original in self.source_sid, "A94_ACTION_INPUT_SNAPSHOT_CHANGED")
            self.sid[(day, original[1])] = deepcopy(self.source_sid[original])
        self.day = day
        self.verify()

    def verify(self):
        _require(self.day is not None, "A94_ACTION_INPUT_SNAPSHOT_CHANGED")
        key = str(self.day.date())
        _require(set(self.actions) == set(self.batch.candidate_ids)
            and all(set(by_day) == {self.day} for by_day in self.actions.values()), "A94_ACTION_INPUT_SNAPSHOT_CHANGED")
        payload = [dict(candidate_id=cid, proposals=list(self.actions[cid][self.day])) for cid in self.batch.candidate_ids]
        _require((_digest(payload), _digest(_sid_payload(self.sid))) == self.commitments[key],
            "A94_ACTION_INPUT_SNAPSHOT_CHANGED")


class _BoundOverlay:
    """Guard the actual collection used by both overlay and replay audit loops."""
    def __init__(self, batch, overlay, action_guard=None):
        self._batch, self._overlay, self._action_guard = batch, overlay, action_guard
        self._check_actual()

    def _check_actual(self):
        _check(self._batch)
        _require(self._overlay.candidates is self._batch.candidates
            and self._overlay.descriptive_evaluation_authority is self._batch.scoped_authority,
            "A94_OVERLAY_CANDIDATE_COLLECTION_CHANGED")
        if self._batch.source_group in ("NEW37", "FINAL_ACTION_OVERLAY"):
            _require(self._overlay.raw.candidates is self._batch.candidates
                and self._overlay.raw.descriptive_evaluation_authority is self._batch.scoped_authority,
                "A94_OVERLAY_CANDIDATE_COLLECTION_CHANGED")
            _require(self._overlay.action_packets is self._action_guard.actions
                and self._overlay.sid_by_key is self._action_guard.sid, "A94_ACTION_INPUT_SNAPSHOT_CHANGED")

    def __call__(self, di, context):
        if self._action_guard is not None:
            self._action_guard.stage(context.signal_date)
        self._check_actual()
        result = self._overlay(di, context)
        # A provider/callback mutating policy data cannot return a target to the
        # sole account engine. The original decoder/optimizer is unchanged.
        self._check_actual()
        if self._action_guard is not None:
            self._action_guard.verify()
        return result

    def __getattr__(self, name):
        return getattr(self._overlay, name)


def execute_batch(batch, *, market, packets, top, qualified, vol, account,
                  stock_present, raw_selector_present, account_source_kwargs,
                  risk_provider=None, action_packets=None, sid_by_key=None, action_calendar=None):
    """Forward one prepared batch to the sole original replay/account engine.

    No caller-selectable factory or decoder. Consume and release each returned
    replay/frames before the next batch when bounded memory is required.
    Source/inference readiness remains the original providers' responsibility.
    """
    _check(batch)
    if any(c.get("gross", "fixed") != "fixed" for c in batch.candidates):
        _require(callable(risk_provider), "A94_FROZEN_RISK_PROVIDER_REQUIRED")
    _require(isinstance(account_source_kwargs, Mapping) and set(account_source_kwargs) <= _SOURCE_KWARGS,
        "A94_UNREGISTERED_ACCOUNT_OVERRIDE")
    source = deepcopy(dict(account_source_kwargs))
    _require(source.get("entitlement_enabled") is True and isinstance(source.get("entitlement_source_binding"), Mapping),
        "A94_ORIGINAL_CA_ACCOUNT_BINDING_REQUIRED")
    action_guard = None
    if batch.source_group in ("NEW37", "FINAL_ACTION_OVERLAY"):
        if action_calendar is not None:
            _require(action_packets is None and sid_by_key is None, "ALL_A_ACTION_INPUTS_AMBIGUOUS")
            action_packets, sid_by_key, commitments = _window_action_calendar(batch, market, action_calendar)
        else:
            _require(isinstance(action_packets, Mapping) and set(action_packets) == set(batch.candidate_ids)
                and isinstance(sid_by_key, Mapping), "A94_ORIGINAL_ACTION_AND_SID_INPUTS_REQUIRED")
            commitments = _action_coverage(batch, market, action_packets, sid_by_key)
        action_guard = _ActionGuard(batch, action_packets, sid_by_key, commitments)
    else:
        _require(action_packets is None and sid_by_key is None and action_calendar is None, "A94_OLD57_ACTION_OVERRIDE_FORBIDDEN")
    def fixed_factory(actual, *args, **kwargs):
        _check(batch)
        _require(actual is batch.candidates and kwargs.get("descriptive_evaluation_authority") is batch.scoped_authority,
            "A94_OVERLAY_CANDIDATE_COLLECTION_CHANGED")
        if batch.source_group in ("OLD57", "STATEFUL_OVERLAY"):
            original = StatefulOverlay(actual, *args, **kwargs)
        else:
            original = FinalActionOverlay(actual, *args, **kwargs, action_packets=action_guard.actions,
                resource_decoder=decode_resource_proposals, sid_by_key=action_guard.sid)
        return _BoundOverlay(batch, original, action_guard)
    result = replay.execute_market(market, batch.candidates, packets, top, qualified, vol, deepcopy(account),
        stock_present=stock_present, raw_selector_present=raw_selector_present, risk_provider=risk_provider,
        execution_friction=deepcopy(batch.execution_friction), policy_factory=fixed_factory,
        descriptive_evaluation_authority=batch.scoped_authority, **source)
    _check(batch)
    return result
