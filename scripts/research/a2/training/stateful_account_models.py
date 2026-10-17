"""Frozen R9 native training adapters; no input I/O or training on import.

The existing runtime owns source admission, readers, durable fit receipts and
worker timeouts. This module consumes in-memory qualified batches, reuses the
native factory, and performs no account replay, calibration or registry writes.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import importlib.metadata
import json
import warnings

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from scripts.research.a2.training import stateful_decision_models as native_owner

DESIGN_SHA = "3e2e3e0cd272408b0b4ca03e9be3c7e26c1dbfeac03ec9bc5176918eed21830f"
HEADS = ("ENTRY_ADVANTAGE", "INCUMBENT_ADVANTAGE", "SCALAR_GROSS_ADVANTAGE")
FAMILIES = ("RIDGE", "HGB", "CATBOOST", "MLP")
CAPACITIES = ("LOW", "MID", "HIGH")
FACTORY_IDS = dict(RIDGE="ridge", HGB="hgb", CATBOOST="cat", MLP="mlp")
BASELINE_GATES = ("accounting", "quote_source", "certified_nav", "cash",
                  "entitlement", "terminal", "required_audits")
SOURCE_SLOTS = ("market_quote_authority", "security_identity_binding",
                "cash_source_bundle", "MKFG_terminal_binding", "MKFG_settlement_authority")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _array_sha(value):
    x = np.ascontiguousarray(value, dtype=np.float64)
    return hashlib.sha256(str(x.shape).encode() + x.tobytes()).hexdigest()


@dataclass(frozen=True)
class FrozenSpec:
    """Exact frozen metadata; runtime admission is a separate receipt."""
    design: dict

    @classmethod
    def from_design(cls, design):
        body = deepcopy(design)
        embedded = body.pop("scientific_design_sha256", None)
        if embedded != DESIGN_SHA or digest(body) != DESIGN_SHA:
            raise ValueError("R9_FROZEN_DESIGN_CHANGED")
        return cls(deepcopy(design))

    def verify(self):
        FrozenSpec.from_design(self.design)

    def fold(self, year):
        self.verify()
        found = [x for x in self.design["folds"] if x["outer_year"] == year]
        if len(found) != 1 or year not in (2024, 2025):
            raise ValueError("R9_FROZEN_OUTER_YEAR_REQUIRED")
        return deepcopy(found[0])

    def model(self, family, capacity):
        self.verify()
        if family not in FAMILIES or capacity not in CAPACITIES:
            raise ValueError("R9_FROZEN_FAMILY_CAPACITY_REQUIRED")
        m = next(x for x in self.design["models"] if x["family"] == family)
        return deepcopy(m), deepcopy(m["capacity_kwargs"][capacity])


def _clock(values):
    def one(value):
        if pd.isna(value):
            return pd.NaT
        t = pd.Timestamp(value)
        return (t.tz_localize("America/New_York") if t.tzinfo is None else t).tz_convert("UTC")
    return pd.DatetimeIndex([one(x) for x in values])


def _literal_flags(values):
    return np.asarray([type(x) in (bool, np.bool_) and bool(x) for x in values], bool)


def fold_masks(metadata, spec, year):
    """Only metadata is inspected before selecting numerical training rows."""
    f = spec.fold(year)
    required = ("row_key", "signal_asof", "label_mature_date", "label_available_at",
                "state_qualified", "label_qualified")
    if any(x not in metadata for x in required) or metadata.row_key.isna().any() or metadata.row_key.duplicated().any():
        raise ValueError("R9_ROW_METADATA_OR_UNIQUE_KEYS_REQUIRED")
    signal = _clock(metadata.signal_asof)
    mature = _clock(metadata.label_mature_date)
    available = _clock(metadata.label_available_at)
    start = _clock([f["core_signal_start_inclusive"]])[0]
    inner = _clock([f["inner_validation_start_inclusive"]])[0]
    outer = _clock([f["outer_cutoff_exclusive"]])[0]
    pre2026 = _clock(["2026-01-01"])[0]
    legal = (_literal_flags(metadata.state_qualified) & _literal_flags(metadata.label_qualified)
        & ~signal.isna() & ~mature.isna() & ~available.isna()
        & (signal >= start) & (signal < pre2026) & (mature >= signal)
        & (available >= mature) & (available < pre2026))
    return dict(
        core=np.asarray(legal & (signal < inner) & (mature < inner) & (available < inner)),
        validation=np.asarray(legal & (signal >= inner) & (signal < outer)
                              & (mature < outer) & (available < outer)),
        outer=np.asarray(legal & (signal < outer) & (mature < outer) & (available < outer)))


@dataclass
class HeadBatch:
    head: str
    metadata: pd.DataFrame
    X: object
    target: object
    weights: object
    features: tuple
    encoding_sha: str


@dataclass
class Prepared:
    head: str
    year: int
    phase: str
    cutoff: str
    X: np.ndarray
    y: np.ndarray
    weights: np.ndarray
    features: tuple
    row_keys: tuple
    identity: dict


def prepare_head(batch, spec, year, phase):
    if batch.head not in HEADS or phase not in ("core", "outer", "validation"):
        raise ValueError("R9_HEAD_OR_PHASE_INVALID")
    if not batch.features or len(set(batch.features)) != len(batch.features) or not batch.encoding_sha:
        raise ValueError("R9_FIXED_FEATURE_ENCODING_REQUIRED")
    masks = fold_masks(batch.metadata, spec, year)
    indices = np.flatnonzero(masks[phase])
    if len(indices) < 2:
        raise ValueError("BLOCKED_INPUT_R9_LEGAL_ROWS")
    # Deliberately no arbitrary row cap, subsampling, target clipping or imputation.
    x = np.asarray(batch.X[indices], float)
    y = np.asarray(batch.target[indices], float)
    w = np.asarray(batch.weights[indices], float)
    if x.shape != (len(indices), len(batch.features)) or y.shape != (len(indices),) or w.shape != y.shape:
        raise ValueError("R9_BATCH_ARRAY_SHAPE")
    if not np.isfinite(x).all() or not np.isfinite(y).all() or not np.isfinite(w).all() or (w < 0).any() or w.sum() <= 0:
        raise ValueError("R9_FINITE_ENCODED_INPUT_TARGET_WEIGHTS_REQUIRED")
    keys = tuple(map(str, batch.metadata.iloc[indices].row_key))
    cutoff = spec.fold(year)["core_signal_and_maturity_before" if phase == "core" else "outer_cutoff_exclusive"]
    identity = dict(head=batch.head, outer_year=year, phase=phase,
        ordered_training_row_keys_sha=digest(keys), ordered_features_sha=digest(batch.features),
        sample_weights_sha=_array_sha(w), fold_cutoff=cutoff,
        zero_fill_missing_flag_encoding_sha=batch.encoding_sha,
        runtime_version=importlib.metadata.version("scikit-learn"),
        input_matrix_custody_sha=_array_sha(x), target_custody_sha=_array_sha(y))
    return Prepared(batch.head, year, phase, cutoff, x, y, w, tuple(batch.features), keys, identity)


@dataclass
class FitBudget:
    """Reservations mirror the existing owner's receipt callback, not a registry.

    The caller must persist every callback before returning literal True. Real
    fits need a separately accepted admission receipt; synthetic attempts are
    explicitly outside the scientific 174. Failed identities cannot be retried.
    """
    spec: FrozenSpec
    admission: dict = field(default_factory=dict)
    synthetic: bool = False
    on_fit_started: object = None
    attempts: dict = field(default_factory=dict)
    head_inputs: dict = field(default_factory=dict)
    outer_choices: dict = field(default_factory=dict)

    def admitted(self):
        self.spec.verify()
        if self.synthetic is True:
            return
        receipt = self.admission
        flags = ("real_fit_authorized", "runtime_fit_admitted", "registry_admitted",
                 "qualified_reference_state", "qualified_counterfactual_labels", "source_pins_frozen")
        if (any(receipt.get(k) is not True for k in flags)
            or any(receipt.get("baseline_gates", {}).get(k) is not True for k in BASELINE_GATES)
            or any(receipt.get("source_slots", {}).get(k) is not True for k in SOURCE_SLOTS)
            or self.on_fit_started is None):
            raise ValueError("BLOCKED_R9_REAL_FIT_NOT_ADMITTED")

    def bind_head(self, prepared):
        context = (prepared.head, prepared.year, prepared.phase)
        identity = digest(prepared.identity)
        if context in self.head_inputs and self.head_inputs[context] != identity:
            raise ValueError("R9_HEAD_ROWS_WEIGHTS_OR_INPUTS_CHANGED")
        self.head_inputs[context] = identity

    def start(self, identity, *, stage, component):
        self.admitted()
        if stage not in ("inner", "outer") or component not in ("model", "scaler"):
            raise ValueError("R9_COMPONENT_OR_STAGE_INVALID")
        key = digest(identity)
        if key in self.attempts:
            raise ValueError("R9_SAME_IDENTITY_NO_SCIENTIFIC_RETRY")
        caps = self.spec.design["training_budget"]
        counts = self.counts()
        specific = caps[stage + ("_model_fit_cap" if stage == "inner" else "_max_model_fit_cap")] if component == "model" else caps[stage + ("_shared_scaler_fit_cap" if stage == "inner" else "_max_shared_scaler_fit_cap")]
        if (counts["attempts"] >= caps["physical_fit_hard_cap"]
            or counts[stage] >= caps[stage + "_component_fit_cap"]
            or counts[stage + "_" + component] >= specific):
            raise ValueError("BLOCKED_BUDGET_R9_BEFORE_FIT")
        event = dict(identity=deepcopy(identity), identity_sha=key, stage=stage,
            component=component, status="STARTED", fit_called=False, synthetic=self.synthetic is True)
        self.attempts[key] = event
        try:
            if self.on_fit_started is not None and self.on_fit_started(deepcopy(event)) is not True:
                raise ValueError("R9_EXISTING_OWNER_REJECTED_FIT_ACK")
        except BaseException as exc:
            self.finish(key, exc)
            raise
        return key

    def finish(self, key, error=None):
        self.attempts[key]["status"] = "FAILED" if error is not None else "COMPLETE"
        if error is not None:
            self.attempts[key]["error"] = type(error).__name__ + ":" + str(error)

    def counts(self):
        result = dict(attempts=len(self.attempts), real_fit_calls=0, synthetic_fit_calls=0,
            failed=0, inner=0, outer=0, inner_model=0, inner_scaler=0, outer_model=0, outer_scaler=0)
        for x in self.attempts.values():
            result[x["stage"]] += 1
            result[x["stage"] + "_" + x["component"]] += 1
            result["failed"] += x["status"] == "FAILED"
            result["synthetic_fit_calls" if x["synthetic"] else "real_fit_calls"] += x["fit_called"]
        return result


def _fit_call(budget, identity, stage, component, model, x, y, weights):
    key = budget.start(identity, stage=stage, component=component)
    try:
        budget.attempts[key]["fit_called"] = True
        with threadpool_limits(limits=2), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            if component == "scaler":
                model.fit(x, sample_weight=weights)
            else:
                model.fit(x, y, sample_weight=weights)
        # Fixed-epoch Adam intentionally reaches max_iter with tol=0. Preserve
        # that warning and verify the frozen final epoch below; never early stop.
        if identity.get("family") != "MLP" and any(type(w.message).__name__ == "ConvergenceWarning" for w in caught):
            raise RuntimeError("R9_UNRESOLVED_CONVERGENCE_NO_RETRY")
        budget.attempts[key]["warnings"] = [str(w.message) for w in caught]
        budget.finish(key)
    except BaseException as exc:
        budget.finish(key, exc)
        raise
    return key


@dataclass
class SharedScalers:
    complete: dict = field(default_factory=dict)

    def get(self, prepared, spec, budget):
        identity = {k: v for k, v in prepared.identity.items() if k != "target_custody_sha"}
        identity.update(component="SHARED_WEIGHTED_STANDARD_SCALER",
            scaler_kwargs=deepcopy(spec.design["preprocessing"]["scaler_kwargs"]))
        key = digest(identity)
        if key not in self.complete:
            scaler = StandardScaler(**identity["scaler_kwargs"])
            _fit_call(budget, identity, "inner" if prepared.phase == "core" else "outer",
                      "scaler", scaler, prepared.X, None, prepared.weights)
            self.complete[key] = scaler
        return self.complete[key], key


@dataclass
class HeadEnsemble:
    head: str
    family: str
    capacity: str
    features: tuple
    estimators: tuple
    scaler: object
    metadata: dict

    def predict(self, X):
        x = np.asarray(X, float)
        if x.ndim != 2 or x.shape[1] != len(self.features) or not np.isfinite(x).all():
            raise ValueError("R9_INFERENCE_FINITE_FEATURE_ORDER_REQUIRED")
        if not len(x):
            return np.empty(0)
        if self.scaler is not None:
            x = self.scaler.transform(x)
        with threadpool_limits(limits=2):
            predictions = np.column_stack([np.asarray(m.predict(x), float) for m in self.estimators])
        if predictions.shape != (len(x), len(self.estimators)) or not np.isfinite(predictions).all():
            raise ValueError("R9_NATIVE_PREDICTION_INVALID")
        return predictions.mean(axis=1)  # fixed equal seed mean, zero ensemble fits


def fit_head_ensemble(batch, spec, year, phase, family, capacity, *, budget, scalers, dependencies=(), selection=None):
    """One declared head/candidate; the existing runtime owns worker isolation."""
    budget.admitted()  # before accessing numerical batches or invoking factory
    if budget.spec.design != spec.design or phase not in ("core", "outer"):
        raise ValueError("R9_BUDGET_SPEC_OR_FIT_PHASE_CHANGED")
    if phase == "outer":
        if (not isinstance(selection, dict) or selection.get("outer_year") != year
            or selection.get("family") != family or selection.get("capacity") != capacity
            or selection.get("three_heads_common") is not True or selection.get("design_sha") != DESIGN_SHA
            or selection.get("outer_outcomes_used") is not False
            or selection.get("frozen37_BREADTH19_outcomes_used") is not False):
            raise ValueError("R9_OUTER_COMMON_SELECTED_PIPELINE_REQUIRED")
        selected = (family, capacity)
        if year in budget.outer_choices and budget.outer_choices[year] != selected:
            raise ValueError("R9_OUTER_COMMON_PIPELINE_CHANGED")
        budget.outer_choices[year] = selected
    prepared = prepare_head(batch, spec, year, phase)
    budget.bind_head(prepared)
    m, frozen_params = spec.model(family, capacity)
    native = native_owner._native(tuple(dependencies))
    scaler, scaler_id = None, None
    if family in ("RIDGE", "MLP"):
        scaler, scaler_id = scalers.get(prepared, spec, budget)
    x = scaler.transform(prepared.X) if scaler is not None else prepared.X
    if not np.isfinite(x).all():
        raise ValueError("R9_SCALED_INPUT_NONFINITE")
    estimators, fit_ids = [], []
    for seed in m["seeds"]:
        params = deepcopy(frozen_params)
        if "seed_kwarg" in m:
            params[m["seed_kwarg"]] = seed
        if "hidden_layer_sizes" in params:
            params["hidden_layer_sizes"] = tuple(params["hidden_layer_sizes"])
        estimator = native.estimator(FACTORY_IDS[family])
        estimator.set_params(**params)  # verbatim design kwargs, never a hidden search
        identity = dict(prepared.identity, family=family, capacity=capacity, seed=seed,
            native_source_sha=native_owner.NATIVE_SHA256, design_sha=DESIGN_SHA,
            frozen_kwargs=frozen_params, scaler_identity=scaler_id)
        fit_id = _fit_call(budget, identity, "inner" if phase == "core" else "outer",
                           "model", estimator, x, prepared.y, prepared.weights)
        # Fixed final epoch/iteration; factory warm starts or early stop cannot slip in.
        expected = frozen_params.get("max_iter", frozen_params.get("iterations"))
        observed = estimator.tree_count_ if family == "CATBOOST" else getattr(estimator, "n_iter_", None)
        if family != "RIDGE" and observed != expected:
            exc = RuntimeError("R9_FIXED_FINAL_ITERATION_NOT_COMPLETED")
            budget.finish(fit_id, exc)
            raise exc
        estimators.append(estimator)
        fit_ids.append(fit_id)
    return HeadEnsemble(batch.head, family, capacity, prepared.features, tuple(estimators), scaler,
        dict(design_sha=DESIGN_SHA, prepared_identity=prepared.identity, training_rows=len(prepared.y),
             fit_identity_shas=fit_ids, seeds=m["seeds"], shared_scaler_identity=scaler_id,
             calibrator_fits=0, ensemble_fits=0, synthetic=budget.synthetic is True,
             scientific_budget_included=budget.synthetic is not True))


def date_balanced_paired_regret(metadata, regret, weights, spec, year):
    """Caller fixed resolver supplies paired regret, never an incomplete oracle."""
    mask = fold_masks(metadata, spec, year)["validation"]
    if not mask.all() or not len(mask) or "matched_reference_group" not in metadata or not _literal_flags(metadata.matched_reference_group).all():
        raise ValueError("R9_QUALIFIED_MATCHED_INNER_VALIDATION_REQUIRED")
    r, w = np.asarray(regret, float), np.asarray(weights, float)
    if r.shape != (len(mask),) or w.shape != r.shape or not np.isfinite(r).all() or (r < 0).any() or not np.isfinite(w).all() or (w < 0).any():
        raise ValueError("R9_REGRET_OR_WEIGHTS_INVALID")
    dates = _clock(metadata.signal_asof).tz_convert("America/New_York").normalize()
    df = pd.DataFrame(dict(date=dates, weighted=r*w, weight=w))
    groups = df.groupby("date", sort=True).sum()
    if (groups.weight <= 0).any():
        raise ValueError("R9_DATE_WITHOUT_VALID_REGRET_WEIGHT")
    identity = digest(dict(year=year, ordered_validation_keys=list(map(str, metadata.row_key)),
        dates=list(map(str, dates)), sample_weights_sha=_array_sha(w)))
    return dict(paired_regret=float((groups.weighted/groups.weight).mean()),
                validation_identity=identity, validation_dates=len(groups),
                metric="DATE_BALANCED_PAIRED_REGRET_NOT_FULL_ACTION_ORACLE")


def select_common_family_capacity(candidate_receipts, spec, year):
    """Select once across all three heads using only the frozen inner score."""
    spec.fold(year)
    expected = {(f, c) for f in FAMILIES for c in CAPACITIES}
    if set(candidate_receipts) != expected:
        raise ValueError("R9_ALL_12_FROZEN_CANDIDATE_TERMINAL_RECEIPTS_REQUIRED")
    identities, valid = {}, []
    for (family, capacity), receipt in candidate_receipts.items():
        if receipt.get("outer_year") != year or receipt.get("phase") != "INNER_VALIDATION":
            raise ValueError("R9_SELECTION_OUTER_OUTCOME_OR_YEAR_FORBIDDEN")
        if receipt.get("status") in ("FAILED", "BLOCKED_INPUT", "BLOCKED_BUDGET"):
            continue
        if receipt.get("status") != "COMPLETE" or set(receipt.get("head_metrics", {})) != set(HEADS):
            raise ValueError("R9_THREE_HEAD_TERMINAL_METRICS_REQUIRED")
        scores = []
        for head in HEADS:
            metric = receipt["head_metrics"][head]
            value = metric.get("paired_regret")
            ident = metric.get("validation_identity")
            if not ident or not isinstance(value, (int, float)) or not np.isfinite(value) or value < 0:
                raise ValueError("R9_VALID_PAIRED_REGRET_REQUIRED")
            if head in identities and identities[head] != ident:
                raise ValueError("R9_CANDIDATE_VALIDATION_SUPPORT_CHANGED")
            identities[head] = ident
            scores.append(value)
        valid.append((float(np.mean(scores)), CAPACITIES.index(capacity), FAMILIES.index(family), family, capacity))
    if not valid:
        raise ValueError("BLOCKED_INPUT_R9_NO_COMMON_COMPLETE_PIPELINE")
    score, _, _, family, capacity = min(valid)
    return dict(outer_year=year, family=family, capacity=capacity,
        primary_inner_regret=score, three_heads_common=True, design_sha=DESIGN_SHA,
        validation_identity_by_head=identities, outer_outcomes_used=False,
        frozen37_BREADTH19_outcomes_used=False, calibrator_fits=0, ensemble_fits=0)
