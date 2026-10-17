"""Exact A94 no-fit carry-forward of original 2025 value/fusion/static-risk states.

Numerical kernels remain with their original owners. No source is fetched, model
loaded, input decoded or prediction made on import. Source-qualified full-pool
commitments must come from the existing pinned source-qualification document.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from scripts.research.a2.evaluation import frozen_test_authority as admission
from scripts.research.a2.evaluation import frozen_a94_profile as profile
from scripts.research.a2.inference import stateful_frozen_test as three
from scripts.research.a2.training import stateful_values as values
from scripts.research.a2.training import stateful_fusion as fusion
from scripts.research.a2.training import stateful_risk as risk_owner
from scripts.research.a2.risk import joint_risk_estimators as risk

_TOKEN = object()
_FORBIDDEN = three._FORBIDDEN
_KEYS = ("signal_date", "ticker")
_FLAGS = ("security_id", "feature_available", "input_present", "feature_source")


def _need(ok, code):
    if not ok:
        raise ValueError(code)


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _authority(value):
    value = admission.load_descriptive_authority(value)
    _need(value.task_id in profile.profile_tasks() and bool(value.runtime_policy_ids), "A94_SCOPED_POLICY_AUTHORITY_REQUIRED")
    profile.require_runtime_policy(value, value.runtime_policy_ids)
    return value


def _maturity(receipt, kind):
    tup = receipt.get("reuse_tuple", {})
    _need(receipt.get("year") == 2025 and receipt.get("status") in ("TRAINED", "EXACT_REUSED", "FITTED")
        and values.digest(tup) == receipt.get("reuse_tuple_sha256")
        and pd.Timestamp(tup.get("cutoff_exclusive")) == pd.Timestamp("2025-01-01"), "A94_ORIGINAL_2025_RECEIPT_REQUIRED")
    _need(receipt.get("scientific_feature_pit_qualified") is True, "A94_FROZEN_FEATURE_QUALIFICATION_REQUIRED")
    if kind != "risk":
        _need(receipt.get("scientific_target_qualified") is True, "A94_FROZEN_TARGET_QUALIFICATION_REQUIRED")
        boundary = pd.Timestamp(tup.get("training_signal_and_label_maturity_exclusive"))
        train = pd.Timestamp(receipt.get("train_label_maturity_max"))
        cal = pd.Timestamp(receipt.get("calibration_label_maturity_max"))
        _need(pd.notna(train) and pd.notna(cal) and pd.notna(boundary)
            and train < boundary < pd.Timestamp("2025-01-01") and cal < pd.Timestamp("2025-01-01")
            and pd.Timestamp(tup.get("calibration_label_maturity_exclusive")) == pd.Timestamp("2025-01-01"),
            "A94_ORIGINAL_MATURITY_REQUIRED")
    else:
        _need(receipt.get("scientific_return_proxy_qualified") is True
            and tup.get("annual_static") is True and tup.get("window_sessions") == 63
            and tup.get("return_horizon_sessions") == 1 and tup.get("return_unit") == risk_owner.UNIT
            and tup.get("horizon_rule") == "IID_5_X_STATIC_DAILY_COV", "A94_STATIC63_RISK_REQUIRED")


def _sources(receipt, kind, model_path):
    pins = receipt["reuse_tuple"]["source_pins"]
    if kind == "risk":
        paths = {"module_sha256": risk_owner.__file__, "joint_source_sha256": risk.__file__,
            "values_module_sha256": values.__file__, "input_reader_sha256": values.READER_SOURCE,
            "garch_definition_source_sha256": risk_owner.GARCH_PATH}
    elif kind == "fusion":
        paths = {"module_sha256": fusion.__file__, "native_source_sha256": fusion.NATIVE,
            "native_common_sha256": fusion.COMMON, "input_reader_sha256": values.READER_SOURCE,
            "value_module_sha256": values.__file__}
    else:
        paths = {"module_sha256": values.__file__, "native_source_sha256": values.NATIVE,
            "input_reader_sha256": values.READER_SOURCE}
    paths["input_manifest_sha256"] = Path(model_path).parents[4] / "input_manifest.json"
    _need(all(values.sha(path) == pins.get(key) for key, path in paths.items()), "A94_FROZEN_SOURCE_CHANGED")
    if kind == "fusion":
        _, _, auth, checked = fusion.frozen_contract(Path(model_path).parents[4], receipt["model_id"], 2025)
        _need(checked == pins and [r for r in auth["expert_oof"] if r["year"] < 2025]
            == receipt["reuse_tuple"]["expert_oof_pins"], "A94_PAST_FUSION_EXPERT_PINS_CHANGED")


@dataclass(frozen=True)
class _Stamp:
    token: object
    kind: str
    key: str
    authority: object
    model: object
    receipt_json: str
    model_ref_json: str
    receipt_ref_json: str
    features: tuple


@dataclass(frozen=True)
class FrozenState:
    kind: str
    key: str
    authority: object = field(repr=False)
    model: object = field(repr=False)
    receipt_json: str = field(repr=False)
    model_ref_json: str = field(repr=False)
    receipt_ref_json: str = field(repr=False)
    features: tuple
    _stamp: object = field(repr=False, compare=False)

    def __reduce__(self):
        raise TypeError("Revalidate original physical frozen state")


def _state(handle):
    _need(type(handle) is FrozenState and type(handle._stamp) is _Stamp, "A94_VALIDATED_STATE_REQUIRED")
    stamp = handle._stamp
    _need(stamp.token is _TOKEN and stamp.model is handle.model and stamp.authority is handle.authority
        and all(getattr(stamp, k) == getattr(handle, k) for k in
        ("kind", "key", "receipt_json", "model_ref_json", "receipt_ref_json", "features")), "A94_STATE_HANDLE_CHANGED")
    _authority(handle.authority)
    _need(_json(handle.model.receipt) == handle.receipt_json if handle.kind != "risk" else True,
        "A94_EMBEDDED_RECEIPT_CHANGED")
    return json.loads(handle.receipt_json)


class FrozenStateLoader:
    """Small metadata closure; loading one state never preloads other models.

    Retain/release returned handles by family in the caller's bounded worker.
    This loader has no global model cache and never invokes a training runner.
    """
    def __init__(self, authority):
        self.authority = _authority(authority)
        contract = profile.contract_for_authority(self.authority)
        self._contract_json = _json(contract)
        self._proof = (self.authority, self._contract_json)
        old = profile._document(contract["metadata_refs"]["old_states"])
        self._metadata = {"old_value:" + r["model_id"]: r["metadata"] for r in old["value_models"]}
        self._metadata.update({"old_risk:" + r["risk_id"]: r["metadata"] for r in old["risk_models"]})
        self._metadata_json = _json(self._metadata)

    def _check(self):
        _need(self.authority is self._proof[0] and self._contract_json == self._proof[1]
            and _json(self._metadata) == self._metadata_json, "A94_LOADER_CHANGED")
        return json.loads(self._contract_json)

    def load(self, key, *, model_ref=None, receipt_ref=None):
        contract = self._check()
        allowed = {k:v for k,v in contract["state_refs"].items()
            if k.startswith(("old_value:", "old_risk:", "fusion_expert:"))}
        _need(key in allowed, "A94_UNKNOWN_OR_UNBOUND_STATE")
        expected = allowed[key]
        _need((model_ref is None or model_ref == expected["model_ref"])
            and (receipt_ref is None or receipt_ref == expected["receipt_ref"]), "A94_REPLACED_STATE_REFERENCE")
        path = profile._physical(expected["model_ref"])
        receipt_path = profile._physical(expected["receipt_ref"])
        receipt = deepcopy(self._metadata.get(key)) if key in self._metadata else three._receipt_metadata(receipt_path)
        kind = "risk" if key.startswith("old_risk:") else "fusion" if key.startswith("old_value:fusion::") else "value"
        _maturity(receipt, kind)
        _need(receipt.get("model_sha256") == expected["model_ref"]["sha256"]
            and Path(receipt["model_path"]).resolve() == path.resolve()
            and receipt_path.parent == path.parent, "A94_RECEIPT_MODEL_BINDING_CHANGED")
        _sources(receipt, kind, path)
        features = tuple(receipt["reuse_tuple"].get("feature_binding", {}).get("features", ()))
        if kind != "risk":
            _need(features == tuple(contract["raw_selector_binding"]["ordered_32_features"])
                and receipt["reuse_tuple"]["feature_binding"] == values.feature_binding(), "A94_FEATURE_ORDER_CHANGED")
            (fusion._native if kind == "fusion" else values._native)(receipt.get("dependency_paths", ()))
        # All original CLI ValueFit artifacts use the same exact legacy class alias.
        model = three._load_frozen_model(path, "ngboost" if kind == "value" else kind)
        if kind == "risk":
            tup = receipt["reuse_tuple"]
            dates = pd.DatetimeIndex(receipt.get("fitted_dates", ()))
            _need(type(model) is risk.RiskBundle and model.status == "FITTED"
                and model.method_id == risk.canonical_method(receipt["method_id"])
                and len(dates) == 63 and dates.is_unique and dates.is_monotonic_increasing
                and dates.equals(pd.DatetimeIndex(tup["input_lineage"]["dates"]))
                and dates.equals(pd.DatetimeIndex(model.fitted_dates))
                and dates.min() == pd.Timestamp("2024-10-02") and dates.max() == pd.Timestamp("2024-12-31")
                and tuple(model.assets) == tuple(tup["input_lineage"]["assets"])
                and pd.Timestamp(model.specification.get("fit_cutoff")) == pd.Timestamp("2025-01-01")
                and model.fitted_state.get("return_horizon_sessions") == 1
                and model.fitted_state.get("return_unit") == risk_owner.UNIT, "A94_RISK_OBJECT_CHANGED")
        else:
            expected_type = fusion.FusionFit if kind == "fusion" else values.ValueFit
            _need(type(model) is expected_type and all(model.receipt.get(k) == receipt.get(k) for k in
                ("year", "model_id", "reuse_tuple", "reuse_tuple_sha256", "train_label_maturity_max", "calibration_label_maturity_max")),
                "A94_SERIALIZED_VALUE_OBJECT_CHANGED")
            if kind == "value":
                _need(tuple(model.native.features) == features and model.native.model_id == receipt["model_id"]
                    and model.calibration.get("model_id") == receipt["model_id"]
                    and np.isfinite(model.calibration["sigma"]) and model.calibration["sigma"] > 0,
                    "A94_VALUE_CALIBRATION_OR_ENCODER_CHANGED")
            else:
                _need(getattr(model.native, "method", None) == receipt["model_id"]
                    and np.isfinite(model.sigma) and model.sigma > 0, "A94_FUSION_STATE_CHANGED")
            # Original reuse loaders bind the verified external receipt in memory.
            model.receipt = deepcopy(receipt)
        packed = (_json(receipt), _json(expected["model_ref"]), _json(expected["receipt_ref"]))
        stamp = _Stamp(_TOKEN, kind, key, self.authority, model, *packed, features)
        return FrozenState(kind, key, self.authority, model, *packed, features, stamp)


def pool_session_commitment(frame, features):
    """Pure digest for the existing qualified producer; this does not certify it."""
    columns = [*_KEYS, *_FLAGS, *features]
    keys = frame[list(_KEYS)].reset_index(drop=True)
    return dict(rows=len(frame), keys_sha256=risk_owner.identity_frame(keys),
        input_sha256=risk_owner.identity_frame(frame[columns].reset_index(drop=True)))


@dataclass(frozen=True)
class FrozenPool:
    frame: object = field(repr=False)
    authority: object = field(repr=False)
    features: tuple
    _proof: object = field(repr=False, compare=False)


def _prepare_pool_frame(loader, frame):
    contract = loader._check()
    auth = loader.authority
    _need(isinstance(frame, pd.DataFrame) and not (set(frame.columns) & _FORBIDDEN), "A94_INFERENCE_ONLY_COLUMNS_REQUIRED")
    features = tuple(contract["raw_selector_binding"]["ordered_32_features"])
    _need(set((*_KEYS, *_FLAGS, *features)).issubset(frame.columns), "A94_FULL_POOL_SCHEMA_REQUIRED")
    dates = pd.DatetimeIndex(pd.to_datetime(frame.signal_date))
    admission.validate_descriptive_input_dates(auth, dates)
    _need(not frame.duplicated(list(_KEYS)).any() and dates.min() >= pd.Timestamp("2026-01-01")
        and dates.max() < pd.Timestamp("2027-01-01"), "A94_2026_UNIQUE_POOL_REQUIRED")
    return contract, auth, features


def _seal_pool_frame(frame, auth, features, proof):
    snapshot = frame.reset_index(drop=True).copy(deep=True)
    commits = {}
    for date, day in snapshot.groupby("signal_date", sort=False):
        key = str(pd.Timestamp(date).date())
        commits[key] = pool_session_commitment(day, features)
        _need(proof["sessions"].get(key) == commits[key], "A94_FULL_POOL_KEYS_OR_CONTENT_CHANGED")
    for name in ("feature_available", "input_present"):
        values._bool(snapshot[name], name)
    return FrozenPool(snapshot, auth, features, (_TOKEN, snapshot, auth, features, _json(commits)))


def bind_pool(loader, frame):
    """Require actual full-day PIT32 content to match source-qualified commitments."""
    contract, auth, features = _prepare_pool_frame(loader, frame)
    provenance = json.loads(auth.provenance_json)
    qualification = profile._document(provenance["source_qualification_ref"])
    proof = qualification.get("full_pit32_pool", {})
    raw_binding = contract["raw_selector_binding"]
    if auth.task_id == profile.REPAIR_TASK:
        _need(profile._exact(proof, contract["full_pit32_pool"]), "REPAIR_FULL_POOL_PROOF_CHANGED")
    origin = raw_binding.get("application_pool_origin", "ORIGINAL_24_MANAGER_FULL_PIT32_INFERENCE_POOL")
    if raw_binding.get("universe_variant") == "CONSENSUS100":
        _need(proof.get("universe_variant") == "CONSENSUS100"
            and proof.get("universe_source_ref") == raw_binding["universe_source_ref"]
            and proof.get("universe_contract_sha256") == values.digest(raw_binding["original_universe_contract"]),
            "ALL_A_CONSENSUS_POOL_SOURCE_REQUIRED")
    _need(proof.get("origin") == origin
        and proof.get("source_ref") in provenance["source_refs"].values()
        and proof.get("feature_order_sha256") == values.digest(list(features))
        and isinstance(proof.get("sessions"), dict), "A94_SOURCE_QUALIFIED_FULL_POOL_COMMITMENT_REQUIRED")
    return _seal_pool_frame(frame, auth, features, proof)


def bind_value_support(loader, frame):
    """Bind causal continuing-holding forecasts without expanding the buy pool.

    The original bind_pool still binds only its original source proof. This
    separate entry accepts only the exact consensus task's independently pinned
    as-of support, including every original daily pool row without alteration.
    """
    contract, auth, features = _prepare_pool_frame(loader, frame)
    raw = contract["raw_selector_binding"]
    repair = auth.task_id == profile.REPAIR_TASK
    _need((repair and raw.get("universe_variant") == "CONSENSUS_SENSITIVITY")
        or (auth.task_id == profile.ALL_TASK and raw.get("universe_variant") == "CONSENSUS100"),
        "ALL_A_VALUE_SUPPORT_SCOPE_REQUIRED")
    size = raw.get("n") if repair else 100
    _need(type(size) is int and size in (100, 200, 300, 400), "REPAIR_VALUE_SUPPORT_POOL_SIZE_CHANGED")
    _need(not ({"is_max_group", "is_raw_top20", "new_buy_eligible"} & set(frame.columns)),
          "ALL_A_VALUE_SUPPORT_CANNOT_SUPPLY_BUY_FLAGS")
    provenance = json.loads(auth.provenance_json)
    qualification = profile._document(provenance["source_qualification_ref"])
    original = qualification.get("full_pit32_pool", {})
    proof = qualification.get("full_pit32_value_support", {})
    if repair:
        _need(profile._exact(original, contract["full_pit32_pool"])
            and profile._exact(proof, contract["full_pit32_value_support"]), "REPAIR_VALUE_SUPPORT_PROOF_CHANGED")
    origin = "CONSENSUS_SENSITIVITY_ASOF_HOLDING_VALUE_SUPPORT" if repair else "CONSENSUS100_ASOF_HOLDING_VALUE_SUPPORT"
    _need(isinstance(proof, dict) and proof.get("origin") == origin
        and proof.get("role") == "OFFPOOL_HOLDING_VALUE_CONTINUITY_ONLY"
        and proof.get("domain_policy") == "CURRENT_POOL_UNION_PREVIOUSLY_EFFECTIVE_MEMBERS_ASOF"
        and proof.get("no_future_first_membership") is True
        and proof.get("no_new_buy_eligibility") is True
        and proof.get("source_ref") in provenance["source_refs"].values(),
        "ALL_A_VALUE_SUPPORT_ROLE_REQUIRED")
    _need(original.get("origin") == raw["application_pool_origin"]
        and original.get("universe_variant") == proof.get("universe_variant") == raw["universe_variant"]
        and original.get("universe_source_ref") == proof.get("universe_source_ref") == raw["universe_source_ref"]
        and (repair or original.get("universe_contract_sha256") == proof.get("universe_contract_sha256") == values.digest(raw["original_universe_contract"]))
        and original.get("feature_order_sha256") == proof.get("feature_order_sha256") == values.digest(list(features)),
        "ALL_A_VALUE_SUPPORT_ORIGINAL_UNIVERSE_CHANGED")
    manifest = profile._document(proof.get("support_manifest_ref"))
    declared = {k:v for k,v in proof.items() if k not in ("support_manifest_ref", "source_ref")}
    _need(manifest.get("task_id") == auth.task_id and manifest.get("value_holding_support") == declared
        and manifest.get("physical_daily_top100_ref") == original.get("physical_pool_ref")
        and manifest.get("physical_support_ref") != original.get("physical_pool_ref"),
        "ALL_A_VALUE_SUPPORT_MANIFEST_BINDING_CHANGED")
    for name in ("physical_support_ref", "physical_daily_top100_ref", "source_features_ref",
                 "source_dated_identity_ref", "source_flags_ref"):
        profile._physical(manifest.get(name))
    for name, reference in manifest.items():
        if name.endswith("_ref") and isinstance(reference, dict) and "path" in reference:
            profile._physical(reference)
    _need(proof.get("daily_top100_sessions") == original.get("sessions")
        and isinstance(proof.get("sessions"), dict)
        and set(proof["sessions"]) == set(original.get("sessions", {})),
        "ALL_A_VALUE_SUPPORT_ORIGINAL_DAILY_PROOFS_CHANGED")
    memberships = proof.get("daily_top100_tickers", {})
    _need(isinstance(memberships, dict) and set(memberships) == set(original["sessions"]),
          "ALL_A_VALUE_SUPPORT_DAILY_MEMBERS_REQUIRED")
    first = {}
    for day in sorted(memberships):
        names = memberships[day]
        _need(isinstance(names, list) and len(names) == len(set(names)) == size
            and all(isinstance(t, str) and t for t in names)
            and pd.Timestamp(day).strftime("%Y-%m-%d") == day
            and original["sessions"][day].get("rows") == size,
            "ALL_A_VALUE_SUPPORT_DAILY_TOP100_CHANGED")
        for ticker in names:
            first.setdefault(ticker, day)
    _need(proof.get("first_membership_by_ticker") == first,
          "ALL_A_VALUE_SUPPORT_FIRST_MEMBERSHIP_CHANGED")
    actual_days = {str(pd.Timestamp(d).date()) for d in frame.signal_date}
    _need(actual_days == set(proof["sessions"]), "ALL_A_VALUE_SUPPORT_FULL_CALENDAR_REQUIRED")
    for date, day in frame.groupby("signal_date", sort=False):
        key = str(pd.Timestamp(date).date())
        _need(all(t in first and first[t] <= key for t in day.ticker),
              "ALL_A_VALUE_SUPPORT_FUTURE_FIRST_MEMBERSHIP_FORBIDDEN")
        base = day.set_index("ticker", drop=False).reindex(memberships[key]).reset_index(drop=True)
        _need(pool_session_commitment(base, features) == original["sessions"][key],
              "ALL_A_VALUE_SUPPORT_ORIGINAL_TOP100_VALUES_CHANGED")
    return _seal_pool_frame(frame, auth, features, proof)


def _pool(pool, handle):
    _state(handle)
    _need(type(pool) is FrozenPool and pool._proof[0] is _TOKEN and pool.frame is pool._proof[1]
        and pool.authority is pool._proof[2] and pool.features == pool._proof[3]
        and pool.authority is handle.authority and pool.features == handle.features, "A94_SOURCE_BOUND_POOL_REQUIRED")
    commits = {str(pd.Timestamp(d).date()):pool_session_commitment(day, pool.features)
        for d,day in pool.frame.groupby("signal_date",sort=False)}
    _need(_json(commits) == pool._proof[4], "A94_BOUND_POOL_MUTATED")
    return pool.frame


@dataclass(frozen=True)
class FrozenPrediction:
    frame: object = field(repr=False)
    state: FrozenState = field(repr=False)
    pool: FrozenPool = field(repr=False)
    _proof: object = field(repr=False, compare=False)


def _prediction(handle, pool, out):
    receipt = json.loads(handle.receipt_json)
    out["year"], out["model_id"] = 2025, receipt["model_id"]
    out["evaluation_year"] = 2026
    out["model_sha256"] = json.loads(handle.model_ref_json)["sha256"]
    out["model_reuse_tuple_sha256"] = receipt["reuse_tuple_sha256"]
    out["prediction_role"] = "FROZEN_FORWARD_INFERENCE"
    proof = (_TOKEN, out, handle, pool, risk_owner.identity_frame(out))
    return FrozenPrediction(out, handle, pool, proof)


def predict_value(handle, pool):
    frame = _pool(pool, handle)
    _need(handle.kind == "value", "A94_VALUE_STATE_REQUIRED")
    receipt = json.loads(handle.receipt_json)
    model_id = receipt["model_id"]
    mask = values._bool(frame.feature_available, "feature_available") & values._bool(frame.input_present, "input_present")
    _need(frame.loc[mask, "feature_source"].isin(values.SOURCES).all(), "UNQUALIFIED_INFERENCE_SOURCE")
    out = frame[list(_KEYS)].copy()
    for c in ("prediction", "value_sigma", *values.diagnostic_columns(model_id)):
        out[c] = np.nan
    ids = np.flatnonzero(mask.to_numpy())
    for start in range(0, len(ids), 100_000):
        at = ids[start:start+100_000]
        x = values.transform(handle.model.native.scaler, frame.iloc[at][list(handle.features)].to_numpy(float))
        with threadpool_limits(limits=1):
            raw = handle.model.native.raw_predict(x)
        mu, sigma = values.calibrated_values(handle.model.calibration, raw)
        _need(np.isfinite(mu).all() and np.isfinite(sigma).all() and (sigma > 0).all(), "A94_NONFINITE_VALUE_PREDICTION")
        for c, vector in dict(prediction=mu, value_sigma=sigma, **values.raw_fields(model_id, raw)).items():
            out.iloc[at, out.columns.get_loc(c)] = vector
    out["prediction_qualified"] = mask.to_numpy()
    return _prediction(handle, pool, out)


def predict_fusion(handle, pool, experts):
    frame = _pool(pool, handle)
    _need(handle.kind == "fusion", "A94_FUSION_STATE_REQUIRED")
    method = json.loads(handle.receipt_json)["model_id"]
    packet = fusion.packet_for(method)
    _need(set(experts) == set(packet), "A94_ALL_THREE_ORIGINAL_EXPERTS_REQUIRED")
    frames = {}
    for name in packet:
        p = experts[name]
        _need(type(p) is FrozenPrediction and p._proof[0] is _TOKEN and p.frame is p._proof[1]
            and p.state is p._proof[2] and p.pool is p._proof[3] and p.pool is pool
            and p.state.authority is handle.authority and json.loads(p.state.receipt_json)["model_id"] == name
            and risk_owner.identity_frame(p.frame) == p._proof[4], "A94_FROZEN_EXPERT_FORWARD_PACKET_REQUIRED")
        _state(p.state)
        frames[name] = p.frame.rename(columns={"prediction":"expert_"+name})
    joined, x = fusion.join_packet(frame, frames, packet)
    valid = values._bool(frame.feature_available, "feature_available").to_numpy() & np.isfinite(x).all(axis=1)
    _need(frame.loc[valid, "feature_source"].isin(fusion.ALLOWED_SOURCES).all(), "A94_FUSION_INFERENCE_SOURCE")
    out = frame[list(_KEYS)].copy()
    out["prediction"], out["value_sigma"] = np.nan, np.nan
    if valid.any():
        state = fusion.join_state(joined.loc[valid].reset_index(drop=True), fusion.state_surface(joined, x)) if fusion.state_required(method) else np.zeros((int(valid.sum()),4))
        with threadpool_limits(limits=1):
            mu = handle.model.native.predict(x[valid], state)
        _need(np.isfinite(mu).all(), "A94_NONFINITE_FUSION_PREDICTION")
        out.loc[valid, "prediction"], out.loc[valid, "value_sigma"] = mu, handle.model.sigma
    out["prediction_qualified"] = valid
    return _prediction(handle, pool, out)


def risk_matrix_frozen(handle, assets):
    receipt = _state(handle)
    _need(handle.kind == "risk", "A94_RISK_STATE_REQUIRED")
    matrix, details = risk.risk_matrix(handle.model, assets, return_metadata=True)
    return matrix * 5., dict(details, original_model_year=2025, evaluation_year=2026,
        horizon_conversion="IID_1D_COVARIANCE_TIMES_5", return_horizon_sessions_output=5,
        model_sha256=json.loads(handle.model_ref_json)["sha256"], reuse_tuple_sha256=receipt["reuse_tuple_sha256"])


def risk_provider(handles, dates, vol):
    dates = pd.DatetimeIndex(dates)
    _need(bool(handles), "A94_FROZEN_RISK_HANDLES_REQUIRED")
    first = next(iter(handles.values()))
    auth = first.authority
    admission.validate_descriptive_input_dates(auth, dates)
    for method, handle in handles.items():
        _state(handle)
        _need(handle.authority is auth and handle.kind == "risk" and handle.key == "old_risk:"+method,
            "A94_FROZEN_RISK_METHOD_BINDING_CHANGED")
    metadata = []
    def provider(di, selected, tickers, method):
        admission.require_descriptive_decision(auth, dates[di])
        if method in ("diag", "diag20_reference"):
            return np.diag(np.asarray(vol)[di, selected] ** 2)
        _need(method in handles, "A94_UNBOUND_RISK_METHOD_NO_SUBSTITUTE")
        matrix, details = risk_matrix_frozen(handles[method], np.asarray(tickers)[selected])
        metadata.append(dict(details, signal_date=dates[di], risk_method=method))
        return matrix
    return provider, metadata
