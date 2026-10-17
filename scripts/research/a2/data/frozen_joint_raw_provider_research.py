"""Exact frozen RAW reuse for research accounts only.

The caller owns immutable-file validation and bounded decoding. An optional
caller callback decodes only actually required held rows. This module performs
no direct I/O, predictions, value replacement, or required-mask derivation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from typing import Mapping

import numpy as np
import pandas as pd

NAMESPACE = "FROZEN_HISTORY_JOINT_POLICY_RESEARCH"
_BOUNDARY = pd.Timestamp("2026-01-01")


class RawProviderFailure(ValueError):
    """Exact source/key failure for attachment to the actual account prefix."""

    def __init__(self, reason, key=None, **metadata):
        self.reason, self.key = reason, key
        self.receipt = dict(reason=reason, signal_date=key[0] if key else None,
                            ticker=key[1] if key else None, **metadata)
        super().__init__(reason + (":" + "|".join(key) if key else ""))


def _fail(reason, key=None, **metadata):
    raise RawProviderFailure(reason, key, **metadata)


def _token(kind, payload):
    value = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return kind + ":" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _day(value):
    try:
        result = pd.Timestamp(value)
    except (ValueError, TypeError, OverflowError):
        _fail("INVALID_SIGNAL_DATE")
    if pd.isna(result) or result.tz is not None or result != result.normalize():
        _fail("NAIVE_EXACT_SESSION_DATE_REQUIRED")
    if result >= _BOUNDARY:
        _fail("PRE2026_DATE_REQUIRED", (result.date().isoformat(), ""))
    return result.date().isoformat()


def _ticker(value):
    if not isinstance(value, str) or not value or value != value.strip():
        _fail("LITERAL_TICKER_REQUIRED")
    return value


def _ref(value, namespace):
    if not isinstance(value, Mapping):
        _fail("FROZEN_SOURCE_REFERENCE_REQUIRED")
    path, sha = value.get("path", value.get("source_ref")), value.get("sha256")
    ns = value.get("namespace", namespace)
    if (not isinstance(path, str) or not path.strip() or
            not isinstance(ns, str) or not ns.strip() or
            not isinstance(sha, str) or len(sha) != 64 or
            any(c not in "0123456789abcdef" for c in sha)):
        _fail("FROZEN_SOURCE_REFERENCE_REQUIRED")
    return dict(path=path, sha256=sha, namespace=ns)


def _row_identity(row, key):
    value = row.get("row_identity")
    if value is None:
        return dict(unique_key=list(key))
    if isinstance(value, bool) or not isinstance(value, (str, int)) or value == "" or (
            isinstance(value, int) and value < 0):
        _fail("INVALID_EXACT_ROW_IDENTITY", key)
    return dict(physical_row_identity=value)


@dataclass(frozen=True)
class RawDayValues:
    mu: np.ndarray
    sigma: np.ndarray
    provenance: tuple[dict, ...]


class FrozenJointRawProviderResearch:
    """Exact base presence has priority; only absent keys use held rows.

    Base keys are pairs or metadata mappings with optional physical row_identity.
    All passed keys must be on the passed axes. Held rows keep original columns:
    a2_prediction, raw_uncertainty, source_fit_cutoff, source_kind, feature_source.
    held_refs maps each original year to its immutable source reference.
    held_value_loader(year, ISO_day, tickers) optionally returns a DataFrame of
    exact required held values, with physical row_identity matching held_rows.
    With that callback, held_rows may be a metadata-only catalog; numeric values
    are never taken from the catalog or defaulted after a callback failure.
    cache_date_offset locates the passed date slice in the original frozen cache;
    provenance records both slice-relative and original-cache row coordinates.
    Numeric admissibility is checked only when a row is actually required.
    """

    strict_PIT = False
    production_qualified = False
    certified_NAV = False
    legal_identity_authority = False

    def __init__(self, *, dates, tickers, base_keys, mu, sigma, base_ref, cache_ref,
                 held_rows=(), held_refs=None, held_value_loader=None, cache_date_offset=0,
                 source_namespace=NAMESPACE):
        if not isinstance(source_namespace, str) or not source_namespace.strip():
            _fail("RESEARCH_NAMESPACE_REQUIRED")
        self.namespace = source_namespace
        if held_value_loader is not None and not callable(held_value_loader):
            _fail("HELD_VALUE_LOADER_CALLABLE_REQUIRED")
        self._held_value_loader = held_value_loader
        if isinstance(cache_date_offset, bool) or not isinstance(cache_date_offset, int) or cache_date_offset < 0:
            _fail("NONNEGATIVE_ORIGINAL_CACHE_DATE_OFFSET_REQUIRED")
        self._cache_date_offset = cache_date_offset
        self.dates = tuple(_day(d) for d in dates)
        self.tickers = tuple(_ticker(t) for t in tickers)
        if (not self.dates or len(set(self.dates)) != len(self.dates) or
                tuple(sorted(self.dates)) != self.dates):
            _fail("UNIQUE_ORDERED_DATE_AXIS_REQUIRED")
        if not self.tickers or len(set(self.tickers)) != len(self.tickers):
            _fail("UNIQUE_LITERAL_TICKER_AXIS_REQUIRED")
        self._di = {d: i for i, d in enumerate(self.dates)}
        self._ti = {t: i for i, t in enumerate(self.tickers)}
        self._base_ref = _ref(base_ref, "ORIGINAL_RAW_OOF")
        self._cache_ref = _ref(cache_ref, "ORIGINAL_MARKET_CACHE")
        self._held_refs = {}
        for year, ref in (held_refs or {}).items():
            if isinstance(year, bool) or not isinstance(year, int) or not 2023 <= year <= 2025:
                _fail("ORIGINAL_HELD_YEAR_REQUIRED")
            self._held_refs[year] = _ref(ref, "ORIGINAL_RAW_HELD_" + str(year))
        self._mu, self._sigma = np.asarray(mu), np.asarray(sigma)
        shape = (len(self.dates), len(self.tickers))
        if self._mu.shape != shape or self._sigma.shape != shape:
            _fail("EXACT_VALUE_AXIS_SHAPE_REQUIRED")
        if any(a.dtype.kind != "f" or a.dtype.itemsize > 8 for a in (self._mu, self._sigma)):
            _fail("ORIGINAL_FLOAT32_OR_FLOAT64_ARRAYS_REQUIRED")
        self._mu, self._sigma = self._mu.copy(), self._sigma.copy()
        self._mu.setflags(write=False)
        self._sigma.setflags(write=False)
        self._base, self._held = {}, {}
        evidence, physical_rows = {}, set()
        for item in base_keys:
            row = dict(item) if isinstance(item, Mapping) else dict(zip(
                ("signal_date", "ticker"), self._pair(item)))
            key = self._key(row)
            if key in self._base:
                _fail("DUPLICATE_BASE_KEY", key, source_ref=self._base_ref)
            self._identity_guard(row, key, evidence)
            for field, expected in (("source_ref", self._base_ref["path"]),
                                    ("source_sha256", self._base_ref["sha256"]),
                                    ("source_namespace", self._base_ref["namespace"])):
                if field in row and row[field] != expected:
                    _fail("BASE_SOURCE_PIN_MISMATCH", key, source_ref=self._base_ref, field=field)
            identity = _row_identity(row, key)
            self._physical_guard(identity, self._base_ref, key, physical_rows)
            self._base[key] = identity
        for item in held_rows:
            if not isinstance(item, Mapping):
                _fail("HELD_METADATA_MAPPING_REQUIRED")
            row = dict(item)
            key = self._key(row)
            year = row.get("source_year", date.fromisoformat(key[0]).year)
            if not isinstance(year, int) or isinstance(year, bool) or year not in self._held_refs:
                _fail("UNDECLARED_HELD_SOURCE", key, source_year=year)
            ref = self._held_refs[year]
            if date.fromisoformat(key[0]).year != year:
                _fail("HELD_ANNUAL_SOURCE_YEAR_MISMATCH", key, source_ref=ref)
            for field, expected in (("source_ref", ref["path"]),
                                    ("source_sha256", ref["sha256"]),
                                    ("source_namespace", ref["namespace"])):
                if field in row and row[field] != expected:
                    _fail("HELD_SOURCE_PIN_MISMATCH", key, source_ref=ref, field=field)
            if key in self._base:
                _fail("BASE_HELD_KEY_OVERLAP", key, base_present=True,
                      source_ref=self._base_ref, conflicting_source_ref=ref)
            if key in self._held:
                _fail("DUPLICATE_HELD_KEY", key, source_ref=ref)
            self._identity_guard(row, key, evidence)
            identity = _row_identity(row, key)
            self._physical_guard(identity, ref, key, physical_rows)
            self._held[key] = (row, identity, ref)
        self._identity_evidence = dict(evidence)
        self.axis_digest = _token("research_axes", dict(dates=self.dates, tickers=self.tickers))
        self.axis_tokens = tuple(_token("research_axis", dict(
            namespace=self.namespace, cache_sha256=self._cache_ref["sha256"],
            ordered_axes=self.axis_digest, column=i, ticker=t))
            for i, t in enumerate(self.tickers))

    @staticmethod
    def _pair(item):
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            _fail("EXACT_BASE_KEY_PAIR_REQUIRED")
        return item

    def _key(self, row):
        if "signal_date" not in row or "ticker" not in row:
            _fail("EXACT_FORECAST_KEY_REQUIRED")
        key = (_day(row["signal_date"]), _ticker(row["ticker"]))
        if key[0] not in self._di or key[1] not in self._ti:
            _fail("SOURCE_KEY_OUTSIDE_MARKET_AXES", key)
        return key

    @staticmethod
    def _physical_guard(identity, ref, key, seen):
        if "physical_row_identity" in identity:
            token = _token("physical_row", dict(ref=ref, identity=identity))
            if token in seen:
                _fail("DUPLICATE_PHYSICAL_ROW_IDENTITY", key, source_ref=ref)
            seen.add(token)

    @staticmethod
    def _identity_guard(row, key, evidence):
        for name in ("alias_of", "canonical_ticker", "normalized_ticker"):
            if row.get(name) is not None and row[name] != key[1]:
                _fail("UNSUPPORTED_ALIAS_OR_TICKER_CHANGE", key, field=name)
        for name in ("security_id", "cusip", "title_of_class", "share_class"):
            value = row.get(name)
            if value is None:
                continue
            if not isinstance(value, str):
                _fail("INVALID_EXPLICIT_IDENTITY_EVIDENCE", key, field=name)
            if not value:
                continue
            previous = evidence.setdefault((key[1], name), value)
            if previous != value:
                _fail("CONFLICTING_EXPLICIT_SECURITY_IDENTITY", key, field=name)


    @staticmethod
    def _held_extra(row, key, ref):
        try:
            cutoff = _day(row["source_fit_cutoff"])
            year = date.fromisoformat(key[0]).year
            if cutoff != str(year) + "-01-01" or not cutoff < key[0]:
                _fail("ORIGINAL_HELD_FIT_CUTOFF_MISMATCH", key, source_ref=ref)
            if any(not isinstance(row.get(f), str) or not row[f].strip()
                   for f in ("source_kind", "feature_source")):
                _fail("ORIGINAL_HELD_PRODUCER_METADATA_REQUIRED", key, source_ref=ref)
        except KeyError as error:
            _fail("ORIGINAL_HELD_FIELD_MISSING", key, source_ref=ref, field=error.args[0])
        except RawProviderFailure as error:
            if error.key == key:
                raise
            _fail("ORIGINAL_HELD_FIT_CLOCK_INVALID", key, source_ref=ref,
                  clock_reason=error.reason)
        return dict(source_fit_cutoff=cutoff, source_kind=row["source_kind"],
                    feature_source=row["feature_source"])

    def _load_held_required(self, day, required):
        if self._held_value_loader is None:
            return {}
        keys = [(day, self.tickers[col]) for col in np.flatnonzero(required)
                if (day, self.tickers[col]) not in self._base
                and (day, self.tickers[col]) in self._held]
        if not keys:
            return {}
        year = date.fromisoformat(day).year
        ref = self._held_refs[year]
        for key in keys:
            row, identity, _ = self._held[key]
            self._held_extra(row, key, ref)
            if "physical_row_identity" not in identity:
                _fail("HELD_LAZY_PHYSICAL_ROW_IDENTITY_REQUIRED", key, source_ref=ref)
        query = dict(source_year=year, signal_date=day, tickers=[key[1] for key in keys])
        try:
            frame = self._held_value_loader(year, day, tuple(query["tickers"]))
        except Exception as error:
            if isinstance(error, RawProviderFailure) and error.key in keys:
                raise
            _fail("HELD_VALUE_LOADER_FAILED", keys[0], source_ref=ref,
                  query=query, error_type=type(error).__name__)
        if not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique:
            _fail("HELD_VALUE_LOADER_EXACT_DATAFRAME_REQUIRED", keys[0],
                  source_ref=ref, query=query)
        missing = [name for name in ("signal_date", "ticker", "row_identity",
                                    "a2_prediction", "raw_uncertainty")
                   if name not in frame.columns]
        if missing:
            _fail("ORIGINAL_HELD_FIELD_MISSING", keys[0], source_ref=ref,
                  field=missing[0], query=query)
        requested, loaded = set(keys), {}
        evidence = dict(self._identity_evidence)
        for row in frame.to_dict("records"):
            try:
                key = self._key(row)
            except RawProviderFailure as error:
                _fail("HELD_LOADER_INVALID_RETURNED_KEY", keys[0], source_ref=ref,
                      query=query, key_reason=error.reason)
            if key not in requested:
                _fail("HELD_LOADER_RETURNED_UNREQUESTED_KEY", key,
                      source_ref=ref, query=query)
            if key in loaded:
                _fail("DUPLICATE_HELD_LOADER_KEY", key, source_ref=ref, query=query)
            catalog, identity, _ = self._held[key]
            if _row_identity(row, key) != identity:
                _fail("HELD_LOADER_ROW_IDENTITY_MISMATCH", key,
                      source_ref=ref, query=query, expected_row_identity=dict(identity))
            self._identity_guard(row, key, evidence)
            for field, expected in (("source_ref", ref["path"]),
                                    ("source_sha256", ref["sha256"]),
                                    ("source_namespace", ref["namespace"]),
                                    ("source_year", year),
                                    ("source_kind", catalog["source_kind"]),
                                    ("feature_source", catalog["feature_source"])):
                if field in row and row[field] != expected:
                    _fail("HELD_LOADER_METADATA_MISMATCH", key, source_ref=ref,
                          query=query, field=field)
            if "source_fit_cutoff" in row:
                try:
                    cutoff = _day(row["source_fit_cutoff"])
                except RawProviderFailure as error:
                    _fail("HELD_LOADER_METADATA_MISMATCH", key, source_ref=ref,
                          query=query, field="source_fit_cutoff", clock_reason=error.reason)
                if cutoff != self._held_extra(catalog, key, ref)["source_fit_cutoff"]:
                    _fail("HELD_LOADER_METADATA_MISMATCH", key, source_ref=ref,
                          query=query, field="source_fit_cutoff")
            loaded[key] = row
        for key in keys:
            if key not in loaded:
                _fail("EXACT_REQUIRED_HELD_VALUE_ROW_MISSING", key,
                      source_ref=ref, base_present=False, query=query)
        return loaded

    def for_day(self, signal_date, required_mask, *, tickers=None):
        day = _day(signal_date)
        if day not in self._di:
            _fail("EXACT_MARKET_DAY_MISSING", (day, ""))
        if tickers is not None and tuple(tickers) != self.tickers:
            _fail("ORDERED_MARKET_AXIS_CHANGED", (day, ""))
        required = np.asarray(required_mask)
        if required.shape != (len(self.tickers),) or required.dtype.kind != "b":
            _fail("EXACT_BOOLEAN_REQUIRED_MASK_REQUIRED", (day, ""))
        out_mu = np.full(len(self.tickers), np.nan)
        out_sigma = np.full(len(self.tickers), np.nan)
        provenance = []
        loaded_held = self._load_held_required(day, required)
        for col in np.flatnonzero(required):
            key = (day, self.tickers[col])
            base_present = key in self._base
            if base_present:
                ref, identity = self._base_ref, self._base[key]
                mean, uncertainty = self._mu[self._di[day], col], self._sigma[self._di[day], col]
                extra = dict(value_source_ref=dict(self._cache_ref),
                             value_cell_identity=dict(evaluation_date_index=self._di[day],
                                 original_cache_date_index=self._di[day] + self._cache_date_offset,
                                 column=int(col)))
            elif key in self._held:
                row, identity, ref = self._held[key]
                extra = self._held_extra(row, key, ref)
                if self._held_value_loader is not None:
                    row = loaded_held[key]
                    extra["value_loading"] = "REQUIRED_HELD_BATCH"
                else:
                    extra["value_loading"] = "IN_MEMORY_ORIGINAL_HELD_ROW"
                try:
                    mean, uncertainty = row["a2_prediction"], row["raw_uncertainty"]
                except KeyError as error:
                    _fail("ORIGINAL_HELD_FIELD_MISSING", key, source_ref=ref, field=error.args[0])
            else:
                _fail("EXACT_REQUIRED_RAW_ROW_MISSING", key, base_present=False,
                      consulted_source_refs=[dict(self._base_ref)] +
                      [dict(r) for r in self._held_refs.values()])
            values = (mean, uncertainty)
            if any(isinstance(v, (bool, str)) or
                   not isinstance(v, (int, float, np.integer, np.floating)) or
                   (isinstance(v, np.floating) and v.dtype.itemsize > 8) for v in values):
                _fail("INVALID_ORIGINAL_RAW_VALUE_TYPE", key, source_ref=ref, base_present=base_present)
            try:
                bad = [name for name, value in (("mu", mean), ("sigma", uncertainty))
                       if not np.isfinite(value) or (name == "sigma" and value < 0)]
            except (TypeError, ValueError, OverflowError):
                _fail("INVALID_ORIGINAL_RAW_VALUE_TYPE", key, source_ref=ref, base_present=base_present)
            if bad:
                _fail("NONFINITE_OR_NEGATIVE_ORIGINAL_REQUIRED_VALUE", key,
                      source_ref=ref, base_present=base_present, missing_fields=bad)
            if any(isinstance(v, (int, np.integer)) and int(float(v)) != v for v in values):
                _fail("ORIGINAL_VALUE_NOT_EXACTLY_REPRESENTABLE", key, source_ref=ref)
            out_mu[col], out_sigma[col] = mean, uncertainty
            provenance.append(dict(signal_date=day, ticker=key[1], base_present=base_present,
                source_ref=dict(ref), exact_row_identity=dict(identity),
                row_token=_token("research_row", dict(source=ref, signal_date=day,
                                                     ticker=key[1], identity=identity)),
                axis_token=self.axis_tokens[col], axis_column=int(col), **extra,
                legal_identity_authority=False, strict_PIT=False,
                production_qualified=False, certified_NAV=False))
        out_mu.setflags(write=False)
        out_sigma.setflags(write=False)
        return RawDayValues(out_mu, out_sigma, tuple(provenance))
