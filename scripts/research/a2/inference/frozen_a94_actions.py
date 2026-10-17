"""Exact NEW37 frozen state consumer; no producer, fit, account or research I/O.

Original R6/R10 encoders, native predictors, scaler objects and action decoders
retain numerical ownership. Inputs must carry source-qualified complete keys,
including causally matured probe state for duration/hazard. Missing producers
are explicit gaps; an empty mapping is never a substitute for computed state.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from sklearn.preprocessing import StandardScaler
from scripts.research.a2.inference import frozen_a94_values as base
from scripts.research.a2.training import stateful_decision as decision
from scripts.research.a2.training import stateful_decision_models as r6
from scripts.research.a2.training import stateful_mechanism as mechanism
from scripts.research.a2.training import stateful_mechanism_models as r10
from scripts.research.a2.training import stateful_final_action_packets as packets

_need, _json = base._need, base._json
_TOKEN = object()
_KEYS = ("signal_date", "sample_id", "ticker", "security_id")
_IDENTITY = (*_KEYS, "incumbent", "incumbent_sid", "entrant_ticker", "entrant_sid",
    "proxy_entrant", "cohort_age_sessions", "action_type", "probe_age", "hazard_at_risk")


def _array_digest(value):
    a = np.ascontiguousarray(value, dtype=float)
    return hashlib.sha256(str(a.shape).encode() + a.tobytes()).hexdigest()


def _signature(model, kind):
    if kind == "scaler":
        return (_array_digest(model.mean_), _array_digest(model.scale_),
            getattr(model, "n_features_in_", len(model.mean_)))
    extra = (model.objective, model.learner, tuple(model.features), tuple(model.dependencies)) if kind == "r6" else (_json(model.node), tuple(model.dependencies))
    scaler = None if kind != "r6" or model.scaler is None else (id(model.scaler), _signature(model.scaler, "scaler"))
    return (_json(model.metadata), id(model.estimator), extra, scaler)


@dataclass(frozen=True)
class ActionState:
    key: str
    kind: str
    authority: object = field(repr=False)
    model: object = field(repr=False)
    metadata_json: str = field(repr=False)
    receipt_json: str = field(repr=False)
    refs_json: str = field(repr=False)
    features: tuple
    _proof: object = field(repr=False, compare=False)

    def __reduce__(self):
        raise TypeError("A94_ACTION_HANDLE_NOT_SERIALIZABLE")


def _state(handle):
    _need(type(handle) is ActionState and len(handle._proof) == 10,
        "A94_ACTION_HANDLE_REQUIRED")
    p = handle._proof
    _need(p[0] is _TOKEN and handle.authority is p[1] and handle.model is p[2]
        and (handle.key, handle.kind, handle.metadata_json, handle.receipt_json,
             handle.refs_json, handle.features) == p[3:9]
        and _signature(handle.model, handle.kind) == p[9], "A94_ACTION_HANDLE_CHANGED")
    base._authority(handle.authority)
    return json.loads(handle.metadata_json)


class FrozenActionLoader:
    """Reuse the exact94 authority closure; retain/release models by family."""
    def __init__(self, authority):
        self.context = base.FrozenStateLoader(authority)
        contract = self.context._check()
        newer = base.profile._document(contract["metadata_refs"]["new_states"])
        self._rows = {"new_model:" + r["slot_id"]: r for r in newer["model_states"]}
        self._rows.update({"new_scaler:" + r["slot_id"]: r for r in newer["external_scaler_states"]})
        self._candidates = {r["candidate_id"]: r for r in newer["candidate_rows"]}
        self._original_refs = {k: v for k, v in newer["authority_refs"].items() if k in ("R6_contract", "R10_contract")}
        self._metadata_json = _json((self._rows, self._candidates, self._original_refs))
        self._context_proof = (self.context, self._metadata_json)

    @property
    def authority(self):
        return self.context.authority

    def _check(self):
        contract = self.context._check()
        _need(self.context is self._context_proof[0] and self._metadata_json == self._context_proof[1]
            and _json((self._rows, self._candidates, self._original_refs)) == self._metadata_json,
            "A94_ACTION_METADATA_CHANGED")
        return contract

    def load(self, key, *, model_ref=None, receipt_ref=None):
        contract = self._check()
        _need(key in self._rows and key in contract["state_refs"], "A94_UNKNOWN_ACTION_STATE")
        scoped = [self._candidates[cid] for cid in self.authority.runtime_policy_ids if cid in self._candidates]
        required = {"new_model:" + slot for candidate in scoped for slot in candidate["model_ids"]}
        required.update("new_scaler:" + slot for candidate in scoped for slot in candidate["external_scaler_ids"])
        _need(key in required, "A94_ACTION_STATE_OUTSIDE_SCOPED_POLICY")
        refs, row = contract["state_refs"][key], deepcopy(self._rows[key])
        _need((model_ref is None or model_ref == refs["model_ref"])
            and (receipt_ref is None or receipt_ref == refs["receipt_ref"]), "A94_REPLACED_ACTION_REFERENCE")
        path = base.profile._physical(refs["model_ref"])
        rp = base.profile._physical(refs["receipt_ref"])
        receipt = (deepcopy(contract["recovered_state_receipt_views"][key])
            if self.authority.task_id == base.profile.REPAIR_TASK and contract.get("repaired_group_id")
                and key in contract.get("recovered_state_receipt_views", {})
            else base.three._receipt_metadata(rp))
        tup = receipt.get("scientific_tuple", {})
        _need(row.get("status") == receipt.get("status") == "TRAINED"
            and type(row.get("year")) is int and row["year"] == receipt.get("year") == 2025
            and receipt.get("model_sha256") == refs["model_ref"]["sha256"] == row.get("model_sha256")
            and Path(receipt.get("model_path", "")).resolve() == path.resolve()
            and path.parent == rp.parent and base.values.digest(tup) == receipt.get("scientific_tuple_sha256"),
            "A94_ACTION_RECEIPT_OR_2025_STATE_CHANGED")
        kind = "scaler" if key.startswith("new_scaler:") else "r6" if row.get("stage") == "R6" else "r10"
        original = base.profile._document(self._original_refs["R6_contract" if kind == "r6" else "R10_contract"])
        if kind == "r6":
            objective, learner = row["objective"], row["learner"]
            columns = decision.PAIR if objective == "replace" else decision.SINGLE
            features = tuple(columns) + tuple(c + "__missing" for c in columns)
            slot = dict(stage="R6", objective=objective, learner=learner, year=2025, slot_id=row["slot_id"])
            boundary = base.three._day(tup.get("calibration_start"))
            _need(tup.get("slot") == slot and tup.get("seed") == receipt.get("seed") == r6.SEED
                and receipt.get("objective") == objective and receipt.get("learner") == learner
                and base.three._day(tup.get("training_signal_max")) < boundary
                and base.three._day(tup.get("training_maturity_max")) < boundary < pd.Timestamp("2025-01-01")
                and tup.get("contract_sha256") == original.get("specification_sha256")
                and tup.get("input_manifest_sha256") == original.get("input_manifest_sha256")
                and base.values.sha(path.parents[3] / "input_manifest.json") == tup["input_manifest_sha256"]
                and tuple(tup.get("feature_order", ())) == features, "A94_ORIGINAL_R6_TUPLE_CHANGED")
        else:
            features = tuple(row.get("feature_order", ()))
            _need(features and tuple(tup.get("features", ())) == features
                and tup.get("year") == 2025 and tup.get("slot_id") == row["slot_id"]
                and tup.get("family") == row["family"] and tup.get("capacity") == row["capacity"]
                and tup.get("seed") == row.get("seed")
                and tup.get("design_sha256") == self._original_refs["R10_contract"]["sha256"],
                "A94_ORIGINAL_R10_TUPLE_CHANGED")
            if kind == "r10":
                _need(tup.get("group") == row.get("group") and tup.get("objective") == row.get("objective")
                    and base.three._day(tup.get("cutoff_exclusive")) == pd.Timestamp("2025-01-01"),
                    "A94_ORIGINAL_R10_CUTOFF_CHANGED")
        model = joblib.load(path)
        if kind == "r6":
            _need(type(model) is r6.Model and model.objective == row["objective"] and model.learner == row["learner"]
                and tuple(model.features) == features and model.metadata.get("source_sha256") == r6.source_sha256()
                and model.metadata.get("native_source_sha256") == r6.NATIVE_SHA256
                and model.metadata.get("specifications") == r6.specifications(), "A94_R6_SERIALIZED_STATE_CHANGED")
        elif kind == "r10":
            _need(type(model) is r10.MechanismModel
                and model.node.get("family") == r10.canonical_family(row["family"])
                and all(model.node.get(k) == row.get(k) for k in ("capacity", "seed", "objective"))
                and model.metadata.get("source_pins") == r10.source_pins()
                and model.metadata.get("source_pins") == original.get("model_specifications", {}).get("source_pins")
                and list(model.metadata.get("feature_shape", ())) == tup["x_shape"][1:], "A94_R10_SERIALIZED_STATE_CHANGED")
        else:
            _need(type(model) is StandardScaler and len(model.mean_) == len(features)
                and len(model.scale_) == len(features) and np.isfinite(model.mean_).all()
                and np.isfinite(model.scale_).all() and (model.scale_ > 0).all(), "A94_SCALER_SERIALIZED_STATE_CHANGED")
        fields = (key, kind, _json(row), _json(receipt), _json(refs), features)
        proof = (_TOKEN, self.authority, model, *fields, _signature(model, kind))
        return ActionState(key, kind, self.authority, model, *fields[2:], proof)


def input_commitment(frame, features, tensor=None, supported=None):
    """Pure publisher digest; authority still comes from source qualification."""
    content = frame.reset_index(drop=True)
    result = dict(rows=len(content), keys_sha256=base.risk_owner.identity_frame(content[list(_KEYS)]),
        input_sha256=base.risk_owner.identity_frame(content),
        feature_order_sha256=base.values.digest(list(features)))
    if tensor is not None:
        result["tensor_sha256"] = _array_digest(tensor)
    result["supported_sha256"] = _array_digest(np.ones(len(content), bool) if supported is None else supported)
    return result


@dataclass(frozen=True)
class ActionInput:
    role: str
    frame: object = field(repr=False)
    tensor: object = field(repr=False)
    supported: object = field(repr=False)
    features: tuple
    authority: object = field(repr=False)
    _proof: object = field(repr=False, compare=False)


def role_features(role):
    if role in ("R6:replace", "R6:distribution_pair"):
        return tuple(decision.PAIR)
    if role.startswith("R6:") and role.split(":")[1] in ("buy", "hold", "duration", "distribution"):
        return tuple(decision.SINGLE)
    if role == "R10:ENTRY":
        return tuple(mechanism.SINGLE)
    if role == "R10:INCUMBENT":
        return (*mechanism.PAIR, "action_type")
    if role == "R10:HAZARD":
        return (*mechanism.SINGLE, "probe_age")
    if role == "R10:JOINT_SEQUENCE":
        return tuple(f"{side}_{c}" for side in ("e", "e_missing", "i", "i_missing") for c in mechanism.SINGLE) + ("action_type",)
    raise ValueError("A94_UNKNOWN_ACTION_INPUT_ROLE")


def bind_action_input(loader, role, frame, *, tensor=None, supported=None, lookback=None):
    loader._check()
    _need(type(frame) is pd.DataFrame and set(_KEYS).issubset(frame.columns)
        and not (set(frame.columns) & base.three._FORBIDDEN), "A94_ACTION_INPUT_SCHEMA_OR_OUTCOME")
    features = role_features(role)
    dates = pd.DatetimeIndex(pd.to_datetime(frame.signal_date))
    if len(dates):
        base.admission.validate_descriptive_input_dates(loader.authority, dates)
    _need(not frame.duplicated(["signal_date", "sample_id"]).any()
        and (not len(frame) or (dates.min() >= pd.Timestamp("2026-01-01") and dates.max() < pd.Timestamp("2027-01-01"))),
        "A94_ACTION_2026_UNIQUE_KEYS_REQUIRED")
    sequence = role == "R10:JOINT_SEQUENCE"
    _need((tensor is not None) == sequence and (sequence or set(features).issubset(frame.columns)),
        "A94_ACTION_ROLE_FEATURES_REQUIRED")
    input_binding_key = role
    if sequence:
        length = 5
        if loader.authority.task_id == base.profile.ALL_TASK or (loader.authority.task_id == base.profile.REPAIR_TASK
                and loader._check().get("repaired_group_id")):
            lengths = {c.get("lookback") for cid,c in loader._candidates.items()
                if cid in loader.authority.runtime_policy_ids and "R10:JOINT_SEQUENCE" in c.get("required_action_roles", ())}
            _need(type(lookback) is int and lookback in lengths, "ALL_A_FROZEN_SEQUENCE_LENGTH_REQUIRED")
            length = lookback
            input_binding_key = role + ":L" + str(length)
        else:
            _need(lookback in (None, 5), "A94_ORIGINAL_L5_SEQUENCE_MASK_REQUIRED")
        _need(np.shape(tensor) == (len(frame), length, len(features)) and not np.isinf(tensor).any()
            and supported is not None, "A94_ORIGINAL_L5_SEQUENCE_MASK_REQUIRED")
    else:
        _need(lookback is None, "ALL_A_UNEXPECTED_SEQUENCE_LENGTH")
    if role in ("R6:replace", "R6:distribution_pair"):
        _need({"incumbent", "incumbent_sid"}.issubset(frame.columns), "A94_ORIGINAL_PAIR_IDENTITY_REQUIRED")
    if role == "R6:distribution":
        _need("proxy_entrant" in frame and frame.proxy_entrant.isin([True, False]).all(), "A94_ORIGINAL_PROXY_ENTRANT_REQUIRED")
    if role in ("R10:INCUMBENT", "R10:JOINT_SEQUENCE"):
        _need({"action_type", "entrant_ticker", "entrant_sid"}.issubset(frame.columns), "A94_ORIGINAL_ACTION_IDENTITY_REQUIRED")
    default = (frame.e_friction.notna() & frame.i_friction.notna()).to_numpy() if role == "R10:INCUMBENT" else np.ones(len(frame), bool)
    mask = default if supported is None else np.asarray(supported)
    _need((role != "R10:INCUMBENT" or np.array_equal(mask, default))
        and (role not in ("R10:ENTRY", "R10:HAZARD") or mask.all())
        and (not role.startswith("R6:") or mask.all()), "A94_ORIGINAL_SUPPORT_MASK_CHANGED")
    _need(mask.dtype == np.dtype(bool) and mask.shape == (len(frame),), "A94_ACTION_SUPPORT_MASK_REQUIRED")
    provenance = json.loads(loader.authority.provenance_json)
    qualification = base.profile._document(provenance["source_qualification_ref"])
    proof = qualification.get("action_feature_inputs", {}).get(input_binding_key, {})
    _need(proof.get("status") == "SOURCE_BOUND_COMPLETE_ORIGINAL_COMPUTED_STATE"
        and proof.get("source_ref") == provenance["source_refs"].get("action_inputs")
        and proof.get("new_fit_count") == 0 and type(proof.get("new_fit_count")) is int
        and proof.get("outcome_columns_in_model_features") == 0
        and type(proof.get("outcome_columns_in_model_features")) is int,
        "A94_QUALIFIED_ACTION_FORWARD_PRODUCER_REQUIRED")
    computed = pd.DatetimeIndex(proof.get("computed_signal_dates", ()))
    base.admission.validate_descriptive_input_dates(loader.authority, computed)
    _need(set(dates).issubset(set(computed)), "A94_ACTION_COMPUTED_DATE_COVERAGE_REQUIRED")
    if role in ("R6:duration", "R10:HAZARD"):
        coverage = qualification.get("action_packet_coverage", {})
        mature = coverage.get("matured_probe_state", {})
        clock = pd.Timestamp(mature.get("as_of_utc"))
        _need(coverage.get("future_unmatured_probe_outcomes_read") == 0
            and type(coverage.get("future_unmatured_probe_outcomes_read")) is int
            and mature.get("source_ref") == provenance["source_refs"].get("action_inputs")
            and clock.tzinfo is not None and clock <= loader.authority.as_of
            and isinstance(mature.get("key_sha256"), str) and len(mature["key_sha256"]) == 64
            and all(c in "0123456789abcdef" for c in mature["key_sha256"])
            and mature.get("causal_rule") == "previous_probe_mature_date < current_signal_date"
            and mature.get("prior_probe_mature_before_current_decision") is True
            and proof.get("prior_probe_mature_before_current_decision") is True,
            "A94_CAUSAL_MATURED_PROBE_STATE_REQUIRED")
    snapshot = frame.reset_index(drop=True).copy(deep=True)
    x = None if tensor is None else np.asarray(tensor, float).copy()
    mask = mask.copy()
    commit = input_commitment(snapshot, features, x, mask)
    _need(proof.get("commitment") == commit, "A94_ACTION_KEYS_CONTENT_OR_MASK_CHANGED")
    stamp = (_TOKEN, role, snapshot, x, mask, features, loader.authority, _json(commit))
    return ActionInput(role, snapshot, x, mask, features, loader.authority, stamp)


def _input(value, handle, role):
    _state(handle)
    _need(type(value) is ActionInput and len(value._proof) == 8, "A94_ACTION_SOURCE_INPUT_REQUIRED")
    p = value._proof
    _need(p[0] is _TOKEN and value.role == p[1] == role and value.frame is p[2]
        and value.tensor is p[3] and value.supported is p[4] and value.features == p[5]
        and value.authority is p[6] is handle.authority
        and _json(input_commitment(value.frame, value.features, value.tensor, value.supported)) == p[7],
        "A94_ACTION_BOUND_INPUT_CHANGED")
    return value.frame


def predict_r6(handle, value):
    row = _state(handle)
    _need(handle.kind == "r6", "A94_R6_STATE_REQUIRED")
    pair = value.role == "R6:distribution_pair" and row["objective"] == "distribution"
    frame = _input(value, handle, "R6:distribution_pair" if pair else "R6:" + row["objective"])
    if pair:
        out = decision.distribution_replace_publication(handle.model, frame)
    else:
        x, names = decision.encode_features(frame, value.features)
        _need(tuple(names) == handle.features, "A94_R6_ENCODER_CHANGED")
        with threadpool_limits(limits=1):
            prediction = r6.predict(handle.model, x)
        out = frame[[c for c in _IDENTITY if c in frame]].copy()
        for key, coordinate in prediction.items():
            if key != "classes" and isinstance(coordinate, np.ndarray) and coordinate.shape == (len(frame),):
                out[key] = coordinate
    return _prediction(handle, value, out.reset_index(drop=True))


def predict_r10(handle, value, *, scaler=None):
    row = _state(handle)
    _need(handle.kind == "r10", "A94_R10_STATE_REQUIRED")
    frame = _input(value, handle, "R10:" + row["group"])
    if value.tensor is None:
        x, names = mechanism.encode(frame, value.features)
    else:
        length = row.get("lookback", 5) if (handle.authority.task_id == base.profile.ALL_TASK
            or handle.authority.task_id == base.profile.REPAIR_TASK
                and json.loads(handle.authority.provenance_json).get("repaired_group_id")) else 5
        _need(type(length) is int and value.tensor.shape[1] == length,
              "ALL_A_MODEL_SEQUENCE_LENGTH_MISMATCH")
        x, names = value.tensor.copy(), value.features
    _need(tuple(names) == handle.features, "A94_R10_ENCODER_CHANGED")
    scaled = r10.canonical_family(row["family"]) in r10.SCALED_FAMILIES
    if scaled:
        _need(scaler is not None, "A94_ORIGINAL_SHARED_SCALER_REQUIRED")
        sr = _state(scaler)
        suffix = f"_{row['family']}_{row['capacity']}_{row['seed']}"
        _need(row["slot_id"].endswith(suffix), "A94_SHARED_SCALER_SLOT_CHANGED")
        expected = row["slot_id"][:-len(suffix)] + "_SCALER"
        _need(scaler.kind == "scaler" and sr["slot_id"] == expected and scaler.authority is handle.authority
            and scaler.features == handle.features, "A94_SHARED_SCALER_IDENTITY_CHANGED")
        # Exact original R10 transform order: transform, reshape, then zero-fill.
        transformed = scaler.model.transform(x.reshape(-1, x.shape[-1])).reshape(x.shape) if len(x) else x.copy()
        x = np.nan_to_num(transformed, nan=0.)
    else:
        _need(scaler is None, "A94_UNEXPECTED_SCALER_FOR_UNSCALED_FAMILY")
        x = np.nan_to_num(x, nan=0.)
    with threadpool_limits(limits=1):
        prediction = r10.predict(handle.model, x) if len(x) else {}
    out = frame[[c for c in _IDENTITY if c in frame]].copy()
    for key, coordinate in prediction.items():
        if isinstance(coordinate, np.ndarray) and coordinate.shape == (len(frame),):
            out[key] = np.where(value.supported, coordinate, np.nan)
    return _prediction(handle, value, out.reset_index(drop=True))


@dataclass(frozen=True)
class ActionPrediction:
    frame: object = field(repr=False)
    state: ActionState = field(repr=False)
    source_input: ActionInput = field(repr=False)
    _proof: object = field(repr=False, compare=False)


def _prediction(handle, source, frame):
    stamp = (_TOKEN, handle, source, frame, base.risk_owner.identity_frame(frame))
    return ActionPrediction(frame, handle, source, stamp)


def _output(prediction):
    _need(type(prediction) is ActionPrediction and len(prediction._proof) == 5, "A94_FROZEN_ACTION_OUTPUT_REQUIRED")
    p = prediction._proof
    _need(p[0] is _TOKEN and prediction.state is p[1] and prediction.source_input is p[2]
        and prediction.frame is p[3] and base.risk_owner.identity_frame(prediction.frame) == p[4],
        "A94_FROZEN_ACTION_OUTPUT_CHANGED")
    _input(prediction.source_input, prediction.state, prediction.source_input.role)
    return prediction.state, prediction.frame


def decode_candidate(loader, candidate_id, predictions):
    """Complete fixed member set, original mean seed aggregation and decoder."""
    loader._check()
    _need(candidate_id in loader._candidates, "A94_UNKNOWN_ACTION_CANDIDATE")
    base.profile.require_runtime_policy(loader.authority, (candidate_id,))
    candidate = loader._candidates[candidate_id]
    _need(set(predictions) == set(candidate["model_ids"]), "A94_COMPLETE_FROZEN_MEMBER_SET_REQUIRED")
    rows, output = [], defaultdict(list)
    for slot in candidate["model_ids"]:
        published = predictions[slot]
        outputs = published if isinstance(published, tuple) else (published,)
        member_rows = []
        for prediction in outputs:
            state, frame = _output(prediction)
            row = _state(state)
            _need(row["slot_id"] == slot and state.authority is loader.authority, "A94_ACTION_MEMBER_IDENTITY_CHANGED")
            frame = frame.copy(); frame["_group"] = row.get("group", row.get("objective"))
            frame["_seed"] = row.get("seed"); frame["_member_slot"] = slot
            member_rows.append(frame)
        roles = [p.source_input.role for p in outputs]
        required = {"R6:distribution", "R6:distribution_pair"} if row.get("objective") == "distribution" else {"R6:" + row["objective"] if row.get("stage") == "R6" else "R10:" + row["group"]}
        _need(len(roles) == len(required) and set(roles) == required, "A94_COMPLETE_ORIGINAL_ACTION_ROLES_REQUIRED")
        # Original owner always publishes marginals before distribution pairs.
        order = {"R6:distribution": 0, "R6:distribution_pair": 1}
        rows.extend(frame for role, frame in sorted(zip(roles, member_rows), key=lambda item: order.get(item[0], 0)))
    if candidate_id.startswith("R6_"):
        objective = loader._rows["new_model:" + candidate["model_ids"][0]]["objective"]
        for frame in rows:
            for date, day in frame.groupby("signal_date", sort=True):
                day_output = output[pd.Timestamp(date)]
                for row in day.to_dict("records"):
                    decoder = packets.decode_r6_distribution_pair if "entrant_q10" in row else None
                    day_output.append(decoder(row, len(day_output)) if decoder else packets.decode_r6_row(row, objective, len(day_output)))
        return dict(output)
    combined = pd.concat(rows, ignore_index=True)
    for group, block in combined.groupby("_group", sort=False):
        seeds = [loader._rows["new_model:" + s]["seed"] for s in candidate["model_ids"]
            if loader._rows["new_model:" + s].get("group") == group]
        _need(len(seeds) in (1, 3) and len(set(seeds)) == len(seeds), "A94_FROZEN_SEED_SET_CHANGED")
        identities = [tuple(zip(f.signal_date.astype(str), f.sample_id.astype(str)))
            for _, f in block.groupby("_seed", sort=False)]
        _need(all(x == identities[0] for x in identities), "FROZEN_SEED_KEY_ORDER_MISMATCH")
        for _, members in block.groupby(["signal_date", "sample_id"], sort=False):
            _need(len(members) == len(seeds) and not members._seed.duplicated().any(), "FROZEN_SEED_BUNDLE_KEY_MISMATCH")
            first = members.iloc[0].to_dict()
            for column in ("ticker", "security_id", "incumbent", "entrant_ticker", "action_type"):
                if column in members:
                    _need(members[column].astype(str).nunique(dropna=False) == 1, "SEED_IDENTITY_OR_ACTION_TOKEN_MISMATCH")
            for column in ("mean", "q50", "probability"):
                if column in members:
                    first[column] = float(np.mean(members[column].to_numpy(float)))
            if first.get("action_type") == 1:
                first["entrant_security_id"] = first.get("entrant_sid")
            day_output = output[pd.Timestamp(first["signal_date"])]
            day_output.append(packets.decode_r10_row(first, len(day_output), group="INCUMBENT" if group == "JOINT_SEQUENCE" else group))
    return dict(output)
