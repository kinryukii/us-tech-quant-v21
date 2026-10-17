"""Exact94 forward state seam; original pure kernels, no reader/fit/publish.

Caller must supply original source-qualified prediction history and already
mature, causally available R6/native RAW shareholder H5 probe projections.
A returned frame is not source certification or permission to run an account.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import FunctionType, SimpleNamespace
import numpy as np
import pandas as pd
from scripts.research.a2.evaluation import frozen_test_authority as admission
from scripts.research.a2.evaluation import frozen_a94_profile as profile
from scripts.research.a2.data import state_label_foundation as foundation
from scripts.research.a2.training import stateful_decision as decision
from scripts.research.a2.training import stateful_inputs as original_inputs
from scripts.research.a2.training import stateful_mechanism_inputs as mechanism_inputs
from scripts.research.a2.training import stateful_mechanism as mechanism

_PINS = {
    foundation.__name__: "3a7e80a6f8e26859c6dcaf7ffe20f3d2502fc8322ce595600f8489a558b034ac",
    decision.__name__: "cb7f75e2da6daa8a6f2f933c898777fad4e8a2278fad21a145201155da4bf4f2",
    mechanism_inputs.__name__: "2ffeaeca4fb4993b4f17b9fa78af17788fdfaba504ef36790ea1eeca373e6f17",
    mechanism.__name__: "0b2553f90927ebbe86a1f6e34475a7a45baad31d4a9ef534ced669a1f106dbe9",
    original_inputs.__name__: "d82c3178d79ada55981645944a5ab79daa10de55ede357b607173d3f19ff25d9"}
_KEYS = ("signal_date", "ticker", "security_id")
_PRED = (*_KEYS, *original_inputs.FEATURES, "feature_available", "is_raw_top20",
    "new_buy_eligible", "raw_top20_set_complete", "raw_a2_rank", "raw_a2_prediction")
_OUTCOMES = frozenset(("y", "y_open5", "label_value", "target", "edge", "basket_y",
    "label_qualified", "label_mature_date", "label_available", "e_y", "i_y",
    "e_legal", "i_legal", "e_mature", "i_mature", "right_censored_unknown",
    "source_label_identity", "censor_endpoint", "supported_training_group_weight", "base_weight"))
_H5_SOURCE = "R10_NATIVE_H5_FROZEN_HISTORY_MECHANISM"
_H5_COORDINATE = "R10_NATIVE_RAW_OPEN_SHAREHOLDER_H5_SUPPORTED_EVENTS"


def _need(ok, code):
    if not ok:
        raise ValueError(code)


class _DateInputs:
    """Read-only call-local date adapter; original module remains unchanged."""
    __slots__ = ("_boundary",)
    def __init__(self, boundary):
        object.__setattr__(self, "_boundary", boundary)
    def __getattr__(self, key):
        return self._boundary if key == "BOUNDARY" else getattr(original_inputs, key)
    def __setattr__(self, key, value):
        raise TypeError("A94_PRIVATE_DATE_SCOPE_IMMUTABLE")


def _clone(fn, **bindings):
    namespace = dict(fn.__globals__)
    namespace.update(bindings)
    clone = FunctionType(fn.__code__, namespace, fn.__name__, fn.__defaults__, fn.__closure__)
    clone.__kwdefaults__ = None if fn.__kwdefaults__ is None else dict(fn.__kwdefaults__)
    return clone


def _clock_scope(value, date, as_of, calendar):
    value = admission.load_descriptive_authority(value)
    _need(value.task_id in profile.profile_tasks() and bool(value.runtime_policy_ids), "A94_SCOPED_STATE_AUTHORITY_REQUIRED")
    profile.require_runtime_policy(value, value.runtime_policy_ids)
    day, observed = pd.Timestamp(date), pd.Timestamp(as_of)
    _need(day.tzinfo is None and day == day.normalize() and pd.Timestamp("2026-01-01") <= day < pd.Timestamp("2027-01-01"), "A94_TEST_DECISION_REQUIRED")
    admission.validate_descriptive_input_dates(value, [day])
    _need(observed.tzinfo is not None and observed <= value.as_of
        and observed.tz_convert("America/New_York").date() == day.date()
        and observed >= day.tz_localize("America/New_York") + pd.Timedelta(hours=16), "A94_DECISION_ASOF_REQUIRED")
    def dates(values, *, nullable=False):
        d = pd.to_datetime(values)
        valid = pd.DatetimeIndex(d).dropna()
        _need((nullable or not pd.isna(d).any()) and (not len(valid) or valid.max() <= day), "A94_FUTURE_OR_INVALID_STATE_CLOCK")
        if len(valid):
            admission.validate_descriptive_input_dates(value, valid, feature_context=True)
        return d
    def cal(values):
        c = pd.DatetimeIndex(dates(values))
        _need(len(c) > 1 and c.is_unique and c.is_monotonic_increasing and c[-1] == day
            and c[0].year == 2023 and c[0].month == 1, "A94_ORIGINAL_2023_COHORT_PHASE_REQUIRED")
        return c
    return value, day, observed, dates, cal, cal(calendar)


def _probes(frame, pred, day, observed, native, cohort, calendar, parent=None):
    _need(type(frame) is pd.DataFrame, "A94_QUALIFIED_PROBE_READER_REQUIRED")
    _need(frame.index.is_unique, "A94_PROBE_ROW_INDEX_NOT_UNIQUE")
    columns = (*_KEYS, "label_mature_date", "observation_available_at")
    extra = ("label_qualified", "source_label_identity", "label_coordinate", "horizon_sessions") if native else ("feature_available", "label_available", "account_event_unhandled", "label_unsupported_common_event", "label_coordinate")
    _need(set((*columns, *extra, "label_value" if native else "y_open5")).issubset(frame), "A94_PROBE_SOURCE_SCHEMA_REQUIRED")
    reuse = native and frame.source_label_identity.eq("PARENT_VALID5D_EXACT_REUSE").any()
    if reuse:
        extra += ("parent_valid5d_exact_reuse",)
        _need(set(extra).issubset(frame), "A94_PARENT_H5_EXACT_PROOF_REQUIRED")
    meta = frame[list((*columns, *extra))].copy()
    signal, mature = pd.to_datetime(meta.signal_date), pd.to_datetime(meta.label_mature_date)
    clocks = meta.observation_available_at.map(pd.Timestamp)
    _need(all(not pd.isna(t) and t.tzinfo is not None for t in clocks), "A94_PROBE_AVAILABLE_CLOCK_UNBOUND")
    available = pd.to_datetime(clocks, utc=True)
    _need(not meta.duplicated(["signal_date", "ticker"]).any()
        and signal.notna().all() and mature.notna().all() and available.notna().all()
        and signal.lt(day).all() and mature.lt(day).all() and signal.le(mature).all()
        and available.le(observed).all(), "A94_PROBE_NOT_MATURE_OR_AVAILABLE_BEFORE_DECISION")
    _need(all(meta.security_id.map(decision._valid_sid)), "A94_PROBE_SID_REQUIRED")
    meta["signal_date"] = signal
    joined = meta.merge(pred[list(_KEYS)], on=["signal_date", "ticker"], how="left", suffixes=("", "_input"), validate="one_to_one")
    _need(joined.security_id.eq(joined.security_id_input).all(), "A94_PROBE_SID_CHANGED")
    if native:
        is_parent = meta.source_label_identity.eq("PARENT_VALID5D_EXACT_REUSE")
        _need(meta.label_qualified.eq(True).all() and meta.horizon_sessions.eq(5).all()
            and ((meta.source_label_identity.eq(_H5_SOURCE) & meta.label_coordinate.eq(_H5_COORDINATE)) | is_parent).all(), "A94_NATIVE_CA_SHAREHOLDER_H5_SOURCE_REQUIRED")
    else:
        _need(meta.label_coordinate.eq(original_inputs.LABEL).all()
            and meta.feature_available.eq(True).all() and meta.label_available.eq(True).all()
            and meta.account_event_unhandled.eq(False).all() and meta.label_unsupported_common_event.eq(False).all(), "A94_ORIGINAL_R6_QUALIFIED_LABEL_REQUIRED")
    # Original risk-set consumers are at fixed ages0/7/14, stride7. Late
    # publication cannot retroactively turn a missed historical probe positive.
    if not len(meta):
        return meta.assign(**{"label_value" if native else "y_open5":pd.Series(dtype=float)}), 0
    keys = cohort.loc[cohort.cohort_age_sessions.isin((0, 7)), [*_KEYS, "cohort_age_sessions"]]
    prior = meta.merge(keys, on=list(_KEYS), how="left", validate="one_to_one")
    positions = prior.signal_date.map({d:i for i,d in enumerate(calendar)}).to_numpy(float) + 7
    late = np.zeros(len(prior), bool)
    for n, (age, position) in enumerate(zip(prior.cohort_age_sessions, positions)):
        if pd.notna(age) and position < len(calendar):
            close = calendar[int(position)].tz_localize("America/New_York") + pd.Timedelta(hours=16)
            late[n] = available.iloc[n] > close
    meta = meta.loc[~late].copy()
    if reuse:
        _need(type(parent) is pd.DataFrame, "A94_PARENT_H5_EXACT_PROOF_REQUIRED")
        original = meta.loc[meta.source_label_identity.eq("PARENT_VALID5D_EXACT_REUSE")].merge(parent, on=list(_KEYS), how="left", suffixes=("", "_parent"), validate="one_to_one")
        _need(original.parent_valid5d_exact_reuse.eq(True).all() and original.horizon_sessions.eq(5).all()
            and original.label_coordinate.eq(original_inputs.LABEL).all()
            and pd.to_datetime(original.label_mature_date).eq(pd.to_datetime(original.label_mature_date_parent)).all()
            and pd.to_datetime(original.observation_available_at, utc=True).eq(pd.to_datetime(original.observation_available_at_parent, utc=True)).all(), "A94_PARENT_H5_EXACT_PROOF_REQUIRED")
    # Metadata is projected BEFORE any numerical outcome is accessed.
    value = frame.loc[meta.index, "label_value" if native else "y_open5"].to_numpy(float)
    _need(np.isfinite(value).all() and (value >= -1).all(), "A94_INVALID_SHAREHOLDER_PROBE")
    meta["signal_date"], meta["label_mature_date"] = signal.loc[meta.index], mature.loc[meta.index]
    meta["label_value" if native else "y_open5"] = value
    if reuse:
        original = meta.loc[meta.source_label_identity.eq("PARENT_VALID5D_EXACT_REUSE")].merge(parent, on=list(_KEYS), how="left", validate="one_to_one")
        _need(np.array_equal(original.label_value.to_numpy(float), original.y_open5.to_numpy(float)), "A94_PARENT_H5_VALUE_CHANGED")
    return meta, int(late.sum())


def _empty(frame, columns):
    return frame if len(frame) else pd.DataFrame(columns=list(dict.fromkeys(columns))).assign(signal_date=pd.Series(dtype="datetime64[ns]"))


def _clean(frame, day):
    f = frame.loc[pd.to_datetime(frame.signal_date).eq(day)].copy() if len(frame) else frame.copy()
    return f.drop(columns=[c for c in f if c in _OUTCOMES or c.endswith("_target") or c.startswith("target_H")], errors="ignore").reset_index(drop=True)


@dataclass(frozen=True)
class ForwardState:
    role_frames: dict
    joint_sequence: np.ndarray
    sequence_supported: np.ndarray
    sequence_features: tuple
    audit: dict


def _required_roles(auth, requested):
    all_roles = tuple("R6:" + role for role in decision.OBJECTIVES) + ("R6:distribution_pair",
        "R10:ENTRY", "R10:INCUMBENT", "R10:HAZARD", "R10:JOINT_SEQUENCE")
    if requested is None:
        return all_roles  # Preserve original all-role/qualified-probe callers.
    _need(isinstance(requested, (tuple, list)) and bool(requested)
        and all(isinstance(role, str) for role in requested)
        and len(set(requested)) == len(requested), "A94_REQUIRED_ACTION_ROLES_CHANGED")
    expected = {role for cid in auth.runtime_policy_ids for role in (profile.required_action_roles(cid) if auth.task_id == profile.TASK else profile.required_action_roles(cid, authority=auth))}
    _need(set(requested) == expected and expected.issubset(all_roles), "A94_REQUIRED_ACTION_ROLES_CHANGED")
    return tuple(role for role in all_roles if role in expected)


def build_current_state(authority, prediction_prefix, calendar_prefix, decision_date, *, decision_as_of,
                        r6_probe_rows, native_h5_probe_rows, action_source_ref, required_roles=None, sequence_length=5):
    """Compute once per day, share across models, release full-prefix locals.

    Prefix starts at original2023 phase. Caller performs bounded source reads;
    None retains all roles. Explicit roles must cover the scoped policies exactly;
    H5-free roles never touch probe readers. Missing required probes remain gaps.
    Output contains no outcomes and creates no source qualification or READY.
    """
    auth, day, observed, scoped_dates, scoped_calendar, calendar = _clock_scope(authority, decision_date, decision_as_of, calendar_prefix)
    requested = _required_roles(auth, required_roles)
    if auth.task_id == profile.TASK:
        _need(sequence_length == 5 and type(sequence_length) is int, "A94_ORIGINAL_L5_SEQUENCE_REQUIRED")
    elif "R10:JOINT_SEQUENCE" in requested:
        rows = json.loads(auth.provenance_json)["candidate_bindings"]
        lengths = {r.get("lookback") for r in rows if r["candidate_id"] in auth.runtime_policy_ids
                   and "R10:JOINT_SEQUENCE" in r["required_action_roles"]}
        _need(type(sequence_length) is int and sequence_length in lengths, "ALL_A_FROZEN_SEQUENCE_LENGTH_REQUIRED")
    for module in (foundation, decision, mechanism_inputs, mechanism, original_inputs):
        _need(hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() == _PINS[module.__name__], "A94_ORIGINAL_STATE_SOURCE_CHANGED")
    provenance = json.loads(auth.provenance_json)
    _need(action_source_ref == provenance["source_refs"]["action_inputs"], "A94_STATE_SOURCE_UNBOUND")
    _need(type(prediction_prefix) is pd.DataFrame and set(_PRED).issubset(prediction_prefix)
        and not set(prediction_prefix).intersection(_OUTCOMES), "A94_PREDICTION_PREFIX_SCHEMA_OR_OUTCOME")
    pred = prediction_prefix[list(_PRED)].copy().sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    pred["signal_date"] = scoped_dates(pred.signal_date)
    _need(pred.signal_date.isin(calendar).all() and pred.signal_date.eq(day).any()
        and not pred.duplicated(["signal_date", "ticker"]).any(), "A94_PREDICTION_PREFIX_KEYS_REQUIRED")
    for flag in ("feature_available", "is_raw_top20", "new_buy_eligible", "raw_top20_set_complete"):
        _need(pred[flag].notna().all() and pred[flag].isin([True, False]).all(), "A94_STATE_FLAGS_REQUIRED")
    # Only these inference kernels are cloned; no train/split/fit function exists here.
    legal = _clone(decision._legal_label, inputs=_DateInputs(day))
    sample = _clone(decision._sample, _legal_label=legal)
    build = _clone(decision.build_samples, inputs=_DateInputs(day + pd.Timedelta(days=1)), _sample=sample, _legal_label=legal)
    structural, structural_audit = build(pred, pd.DataFrame(columns=decision.LABEL_COLS), calendar)
    proxy = _clone(mechanism_inputs.proxy_state, _pre2026=scoped_dates, _calendar=scoped_calendar)
    state = proxy(pred, calendar, 10)
    if not len(state):
        state = pred.iloc[:0].assign(cohort_id=pd.Series(dtype=str), **{c:pd.Series(dtype=float) for c in mechanism_inputs.STATE})
    cohort_cols = (*_KEYS, "cohort_age_sessions")
    hazard_requested = "R10:HAZARD" in requested
    parent_reuse = hazard_requested and type(native_h5_probe_rows) is pd.DataFrame and "source_label_identity" in native_h5_probe_rows and native_h5_probe_rows.source_label_identity.eq("PARENT_VALID5D_EXACT_REUSE").any()
    read_r6 = "R6:duration" in requested or parent_reuse
    r6, r6late, h5late = None, 0, 0
    if read_r6:
        r6cohort = _empty(structural["hold"], cohort_cols)
        r6, r6late = _probes(r6_probe_rows, pred, day, observed, False, r6cohort, calendar)
    if "R6:duration" in requested:
        samples, r6audit = build(pred, r6[list(decision.LABEL_COLS)], calendar)
    else:
        samples, r6audit = structural, structural_audit
    del structural
    base = (*_KEYS, "sample_id", *decision.SINGLE, "cohort_id")
    roles = {}
    for role in decision.OBJECTIVES:
        cols = (*base, "incumbent", "incumbent_sid", *decision.PAIR) if role == "replace" else (*base, "probe_age")
        roles["R6:" + role] = _clean(_empty(samples[role], cols), day)
    roles["R6:distribution"]["proxy_entrant"] = roles["R6:distribution"].entrant.eq(1)
    roles["R6:distribution_pair"] = roles["R6:replace"].copy()
    tensor, supported, features, pair_count = np.empty((0, 5, 0)), np.empty(0, dtype=bool), (), 0
    if any(role.startswith("R10:") for role in requested):
        key_cols = (*_KEYS, "sample_id", "cohort_age_sessions", "raw_rank")
        keys = {role:roles["R6:" + role][list(key_cols)] for role in ("buy", "hold")}
        pairs = foundation.all_incumbent_pairs(keys)  # Original R8 ALL partners, never R6 max2.
        pair_count = len(pairs)
        if len(state):
            identity = state[["cohort_id", "ticker", "security_id"]].assign(inception=state.signal_date.map({d:i for i,d in enumerate(calendar)}) - state.cohort_age_sessions)
            _need(identity.groupby("cohort_id")[["ticker", "security_id", "inception"]].nunique(dropna=False).le(1).all().all(), "A94_COHORT_SID_CHANGED")
        label_cols = (*_KEYS, "label_value", "label_qualified", "label_mature_date", "source_label_identity")
        # Empty annotations preserve original feature-only left joins. They are
        # not a qualified H5 source and never produce a hazard risk set.
        native = state.iloc[:0][list(_KEYS)].copy()
        native["label_mature_date"] = pd.Series(dtype="datetime64[ns]")
        native["label_qualified"] = pd.Series(dtype=bool)
        native["label_value"] = pd.Series(dtype=float)
        native["source_label_identity"] = pd.Series(dtype="object")
        if hazard_requested:
            native, h5late = _probes(native_h5_probe_rows, pred, day, observed, True, state.loc[state.entrant.eq(0)], calendar, parent=r6)
        head = {name:mechanism_inputs.attach_single_labels(state, native[list(label_cols)], name) for name in ("ENTRY", "INCUMBENT", "CONTINUATION")}
        head["REPLACE"] = mechanism_inputs.attach_pair_labels(pairs, state, native[list(label_cols)])
        structured = mechanism.structured_action_frame(SimpleNamespace(heads={5:head}), 5)
        for name in ("ENTRY", "INCUMBENT"):
            roles["R10:" + name] = _clean(structured[name], day)
        if hazard_requested:
            hazard = _clone(mechanism_inputs.hazard_probes, _calendar=scoped_calendar)
            probes = _empty(hazard(head["CONTINUATION"], calendar, ages=(0, 7, 14), stride=7), (*base, "hazard_at_risk", "probe_age"))
            probes["sample_id"] = probes.signal_date.astype(str) + "|HAZARD|" + probes.cohort_id.astype(str)
            roles["R10:HAZARD"] = _clean(probes, day)
        if "R10:JOINT_SEQUENCE" in requested:
            blocks = _clone(mechanism_inputs.sequence_blocks, _pre2026=scoped_dates, _calendar=scoped_calendar)
            sequence = _clone(mechanism.sequence_dataset, inputs=SimpleNamespace(sequence_blocks=blocks))
            bundle = SimpleNamespace(prediction_history=pred, frames=SimpleNamespace(state=state), reader=SimpleNamespace(calendar=calendar))
            continuation = _clean(structured["CONTINUATION"], day)
            additions = {prefix+c:continuation[c] if prefix=="i_" else 0. for c in mechanism.SINGLE for prefix in ("i_", "e_", "delta_")}
            continuation = pd.concat([continuation, pd.DataFrame(additions, index=continuation.index)], axis=1)
            continuation["action_type"] = -1.
            joint = pd.concat([roles["R10:INCUMBENT"], continuation], ignore_index=True, sort=False)
            tensor, supported, features = sequence(bundle, joint, sequence_length)
            roles["R10:JOINT_SEQUENCE"] = joint
    roles = {role:frame for role, frame in roles.items() if role in requested}
    _need(set(roles) == set(requested) and all(not set(f).intersection(_OUTCOMES) for f in roles.values()), "A94_OUTCOME_EXPORT_FORBIDDEN")
    return ForwardState(roles, tensor, supported, features, dict(task_id=auth.task_id, decision_date=str(day.date()),
        decision_as_of=observed.isoformat(), action_source_ref=action_source_ref, source_certified=False,
        original_source_pins=dict(_PINS), original_cohort_phase="2023_PREFIX_NO_ANNUAL_RESET", r6_audit=r6audit,
        requested_roles=list(requested), sequence_length=sequence_length, probe_readers_consumed=dict(R6=bool(read_r6), native_H5=hazard_requested),
        pair_count=pair_count, late_publication_metadata_discarded=dict(R6=r6late, native_H5=h5late),
        late_publication_reason="NOT_AVAILABLE_AT_ORIGINAL_NEXT_STRIDE7_PROBE_CLOSE",
        new_fit_count=0, future_unmatured_probe_outcomes_read=0,
        outcome_columns_in_model_features=0, source_requirement="QUALIFIED_ORIGINAL_ROLE_FEATURES;QUALIFIED_H5_ONLY_FOR_DURATION_OR_HAZARD"))
