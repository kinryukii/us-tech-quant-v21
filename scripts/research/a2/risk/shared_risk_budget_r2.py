"""Exact physical state accounting; no persistent trial authority.

Frozen-history mechanism activation uses the existing lifecycle reservation callback.
C's frozen slot ledger is deliberately not imported or edited by this adapter.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from threading import RLock

KINDS = (
    "model_fit", "scaler", "covariance", "regime_threshold",
    "jackknife_subfit", "horizon", "bridge_calibration",
    "deterministic_transform", "account_replay",
)
LEARNED_KINDS = frozenset(KINDS[:-2])


class StateBudgetError(ValueError):
    """A blocked physical operation, preserving any consumed reservation."""


def _normalized(value):
    if is_dataclass(value):
        return _normalized(asdict(value))
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise StateBudgetError("HASH_MAPPING_KEYS_MUST_BE_STRINGS")
        return {k: _normalized(v) for k, v in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_normalized(v) for v in value]
    if isinstance(value, (date, datetime)):
        return {"datetime": value.isoformat()}
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite": repr(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    # Pandas frames retain axes/dtypes; ndarray retains dtype/shape.
    if hasattr(value, "columns") and hasattr(value, "index") and hasattr(value, "to_numpy"):
        return {"columns": _normalized(value.columns.tolist()),
                "index": _normalized(value.index.tolist()),
                "dtypes": [str(d) for d in value.dtypes],
                "attrs": _normalized(value.attrs), "values": _normalized(value.to_numpy())}
    if hasattr(value, "index") and hasattr(value, "name") and hasattr(value, "to_numpy"):
        return {"series_name": _normalized(value.name), "index": _normalized(value.index.tolist()),
                "attrs": _normalized(value.attrs), "values": _normalized(value.to_numpy())}
    if hasattr(value, "dtype") and hasattr(value, "shape") and hasattr(value, "tolist"):
        return {"dtype": str(value.dtype), "shape": list(value.shape),
                "values": _normalized(value.tolist())}
    if hasattr(value, "item"):
        return _normalized(value.item())
    raise StateBudgetError("UNHASHABLE_STATE_INPUT:" + type(value).__name__)


def content_hash(value):
    encoded = json.dumps(_normalized(value), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class StateBudget:
    """One reservation per exact physical operation, including failed callbacks."""

    def __init__(self, limit=2048, *, limits=None, reserve_callback=None):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise StateBudgetError("NONNEGATIVE_LEARNED_LIMIT_REQUIRED")
        self.limit = limit
        self.limits = dict(limits or {})
        if any(k not in KINDS or isinstance(v, bool) or not isinstance(v, int) or v < 0
               for k, v in self.limits.items()):
            raise StateBudgetError("INVALID_KIND_LIMIT")
        if reserve_callback is not None and not callable(reserve_callback):
            raise StateBudgetError("DURABLE_RESERVATION_CALLABLE_REQUIRED")
        self.reserve_callback = reserve_callback
        self.counts = dict.fromkeys(KINDS, 0)
        self.events = []
        self._keys = set()
        self._lock = RLock()

    @property
    def learned_total(self):
        return sum(self.counts[k] for k in LEARNED_KINDS)

    def reserve(self, key, kind, name, context, inputs_sha256, parameters):
        with self._lock:
            if kind not in KINDS:
                raise StateBudgetError("UNKNOWN_PHYSICAL_KIND")
            if key in self._keys:
                raise StateBudgetError("DUPLICATE_RESERVATION_NO_RETRY")
            if kind == "account_replay":
                raise StateBudgetError("ACCOUNT_REPLAY_NOT_AUTHORIZED")
            if kind in LEARNED_KINDS and self.learned_total >= self.limit:
                raise StateBudgetError("PHYSICAL_LEARNED_CAP_EXCEEDED")
            if kind in self.limits and self.counts[kind] >= self.limits[kind]:
                raise StateBudgetError("PHYSICAL_KIND_CAP_EXCEEDED")
            synthetic, mechanism = context.get("synthetic", True), context.get("mechanism", False)
            if type(synthetic) is not bool or type(mechanism) is not bool or synthetic == mechanism:
                raise StateBudgetError("EXPLICIT_EXECUTION_MODE_REQUIRED")
            if mechanism and self.reserve_callback is None:
                raise StateBudgetError("MECHANISM_DURABLE_RESERVATION_REQUIRED")
            event = dict(key=key, kind=kind, name=name, status="RESERVED",
                         context=copy.deepcopy(context), inputs_sha256=inputs_sha256,
                         parameters=copy.deepcopy(parameters), synthetic=synthetic, mechanism=mechanism)
            self._keys.add(key)
            self.counts[kind] += 1
            self.events.append(event)
            # Occupancy stays consumed if the durable reservation adapter fails.
            try:
                if self.reserve_callback is not None:
                    self.reserve_callback(copy.deepcopy(event))
            except BaseException:
                event["status"] = "FAILED"
                raise
            return event

    def snapshot(self):
        with self._lock:
            return dict(counts=dict(self.counts), learned_total=self.learned_total,
                        limit=self.limit, events=copy.deepcopy(self.events),
                        authority=("EXISTING_LIFECYCLE_MECHANISM_RESERVATIONS"
                                   if any(e.get("mechanism") for e in self.events)
                                   else "SYNTHETIC_LOCAL_ACCOUNTING_ONLY"),
                        no_refund=True, retry_limit=0)


class StateCache:
    """Context-bound exact reuse; only succeeded, unchanged states can be reused."""

    def __init__(self, budget, *, source_identity, cutoff, assets,
                 return_coordinate, horizon, identity_epoch, synthetic=True, mechanism=False,
                 _records=None, _lock=None, _stack=None, _usage_log=None):
        if type(synthetic) is not bool or type(mechanism) is not bool:
            raise StateBudgetError("EXPLICIT_BOOLEAN_EXECUTION_MODE_REQUIRED")
        if not synthetic and not mechanism:
            raise StateBudgetError("SCIENTIFIC_ACTIVATION_PENDING")
        if synthetic and mechanism:
            raise StateBudgetError("SYNTHETIC_MECHANISM_MODES_ARE_DISTINCT")
        if mechanism:
            if budget.reserve_callback is None:
                raise StateBudgetError("MECHANISM_DURABLE_RESERVATION_REQUIRED")
            if (not isinstance(source_identity, dict)
                    or any(not source_identity.get(k) for k in ("id", "version", "sha256"))
                    or not isinstance(source_identity["sha256"], str)
                    or len(source_identity["sha256"]) != 64
                    or any(c not in "0123456789abcdef" for c in source_identity["sha256"])):
                raise StateBudgetError("MECHANISM_SOURCE_BINDING_REQUIRED")
        if not source_identity or not return_coordinate or not identity_epoch:
            raise StateBudgetError("SOURCE_COORDINATE_EPOCH_REQUIRED")
        try:
            parsed_cutoff = datetime.fromisoformat(str(cutoff).replace("Z", "+00:00"))
        except ValueError as exc:
            raise StateBudgetError("ISO_CUTOFF_REQUIRED") from exc
        if parsed_cutoff.tzinfo is None or parsed_cutoff.utcoffset() is None:
            raise StateBudgetError("TIMEZONE_AWARE_CUTOFF_REQUIRED")
        parsed_cutoff = parsed_cutoff.astimezone(timezone.utc)
        if parsed_cutoff >= datetime(2026, 1, 1, tzinfo=timezone.utc):
            raise StateBudgetError("PRE2026_CUTOFF_REQUIRED")
        cutoff = parsed_cutoff.isoformat()
        names = tuple(assets)
        if not names or len(set(names)) != len(names) or any(not isinstance(a, str) or not a for a in names):
            raise StateBudgetError("UNIQUE_ASSET_ORDER_REQUIRED")
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
            raise StateBudgetError("POSITIVE_INTEGER_HORIZON_REQUIRED")
        self.budget = budget
        self.context = dict(source_identity=copy.deepcopy(source_identity), cutoff=cutoff,
                            assets=names, return_coordinate=return_coordinate,
                            horizon=horizon, identity_epoch=copy.deepcopy(identity_epoch),
                            synthetic=synthetic, mechanism=mechanism)
        self._records = {} if _records is None else _records
        self._lock = RLock() if _lock is None else _lock
        self._stack = [] if _stack is None else _stack
        self.usage_log = [] if _usage_log is None else _usage_log

    def bind(self, **updates):
        context = copy.deepcopy(self.context)
        context.update(updates)
        return type(self)(self.budget, **context, _records=self._records, _lock=self._lock, _stack=self._stack,
                          _usage_log=self.usage_log)

    def learn(self, kind, name, inputs, compute, parameters=None):
        if not callable(compute) or not isinstance(name, str) or not name:
            raise StateBudgetError("NAMED_OPERATION_CALLABLE_REQUIRED")
        supplied_parameters = {} if parameters is None else parameters
        parameters = copy.deepcopy(supplied_parameters)
        parameters_sha = content_hash(parameters)
        context = copy.deepcopy(self.context)
        inputs_sha = content_hash(inputs)
        key = content_hash(dict(kind=kind, name=name, context=context,
                                inputs_sha256=inputs_sha, parameters=parameters))
        with self._lock:
            self.usage_log.append(key)
            if self._stack:
                parent = next(e for e in self.budget.events if e["key"] == self._stack[-1])
                if key not in parent.setdefault("dependencies", []):
                    parent["dependencies"].append(key)
            if key in self._records:
                prior = self._records[key]
                if prior["status"] != "SUCCEEDED":
                    raise StateBudgetError("FAILED_OR_RESERVED_STATE_NO_RETRY")
                if content_hash(prior["value"]) != prior["result_sha256"]:
                    raise StateBudgetError("CACHED_STATE_MUTATION")
                return copy.deepcopy(prior["value"])
            record = dict(status="RESERVED")
            self._records[key] = record
            try:
                event = self.budget.reserve(key, kind, name, context, inputs_sha, parameters)
            except BaseException:
                record["status"] = "FAILED"
                raise
            try:
                self._stack.append(key)
                try:
                    result = compute()
                finally:
                    self._stack.pop()
                if (inputs_sha != content_hash(inputs) or context != self.context
                        or parameters_sha != content_hash(supplied_parameters)):
                    raise StateBudgetError("FIT_INPUT_OR_CONTEXT_MUTATED")
                value = copy.deepcopy(result)
                result_sha = content_hash(value)
            except BaseException:
                record["status"] = event["status"] = "FAILED"
                raise
            record.update(status="SUCCEEDED", value=value, result_sha256=result_sha)
            event.update(status="SUCCEEDED", result_sha256=result_sha)
            return copy.deepcopy(value)

