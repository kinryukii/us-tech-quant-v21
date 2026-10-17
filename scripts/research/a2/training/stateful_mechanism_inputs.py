"""R10 frozen-history mechanism inputs, without an account or risk engine.

The only pair owner is the immutable R8 manifest. Numeric reads require an
explicit frozen R10 read permit; pure frame functions also support synthetic
verification. No prepare_inputs call, fit, fetch, source promotion or old write.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scripts.research.a2.training import stateful_inputs as owner

IDENTITY = "A_FROZEN_HISTORY_STATEFUL_MECHANISM_RESEARCH_ONLY"
BOUNDARY = owner.BOUNDARY
FEATURES = owner.FEATURES
HORIZONS = (3, 5, 10, 20)
PAIR_SHA = "e56a4de7a10f85f199604c0b329ff7f5f3884cfc736b8f56656d769e1a3883df"
FALSE_AUTHORITY = ("strict_PIT_promotion_eligible", "account_qualified",
                   "quote_authority_qualified", "certified_NAV_qualified",
                   "source_account_authority_upgraded")
STATE = ("raw_rank", "raw_score", "rank_change", "score_change",
         "cohort_age_sessions", "entrant", "raw_member", "friction")


def digest_file(path: Path | str) -> str:
    return owner.sha(path)


def _pre2026(values, *, nullable=False):
    dates = pd.to_datetime(values)
    if (not nullable and pd.isna(dates).any()) or (dates >= BOUNDARY).any():
        raise ValueError("2026_LOCKED_OR_INVALID_CLOCK")
    return dates


def _sid(value):
    return pd.notna(value) and str(value).strip().lower() not in ("", "nan", "none", "unknown")


def _calendar(values):
    cal = pd.DatetimeIndex(_pre2026(values))
    if cal.has_duplicates or not cal.is_monotonic_increasing:
        raise ValueError("INVALID_CALENDAR")
    return cal


def guard_sources(sources: Mapping[str, Mapping]) -> dict:
    """All physical hashes and all declared clock footers pass before body reads."""
    records = {}
    for name, spec in sources.items():
        path = Path(spec["path"])
        before = path.stat()
        if digest_file(path) != spec["sha256"]:
            raise ValueError("SOURCE_SHA:" + name)
        parquet = pq.ParquetFile(path)
        names = parquet.schema_arrow.names
        if not set(spec.get("required_columns", ())).issubset(names):
            raise ValueError("SOURCE_SCHEMA:" + name)
        if spec.get("rows") is not None and parquet.metadata.num_rows != spec["rows"]:
            raise ValueError("SOURCE_ROWS:" + name)
        clocks = list(spec.get("date_columns", [spec.get("date", "signal_date")]))
        ranges = {}
        for column in clocks:
            if column not in names:
                raise ValueError("SOURCE_CLOCK_MISSING:" + column)
            ranges[column] = []
            for n in range(parquet.num_row_groups):
                stat = parquet.metadata.row_group(n).column(names.index(column)).statistics
                count = parquet.metadata.row_group(n).num_rows
                if stat is None:
                    raise ValueError("CLOCK_FOOTER_MISSING:" + name + ":" + column)
                if stat.null_count == count:
                    if column == clocks[0]:
                        raise ValueError("PRIMARY_CLOCK_ALL_NULL")
                    ranges[column].append({"all_null": True, "rows": count})
                    continue
                if not stat.has_min_max or pd.Timestamp(stat.max) >= BOUNDARY:
                    raise ValueError("SOURCE_NOT_PHYSICALLY_PRE2026:" + name + ":" + column)
                ranges[column].append({"min": str(stat.min), "max": str(stat.max), "rows": count})
        after = path.stat()
        fingerprint = {"size": before.st_size, "mtime_ns": before.st_mtime_ns}
        if fingerprint != {"size": after.st_size, "mtime_ns": after.st_mtime_ns}:
            raise ValueError("SOURCE_CHANGED_DURING_GUARD")
        records[name] = {**dict(spec), "path": str(path), "file_fingerprint": fingerprint,
                         "hash_verified": True, "schema": names, "clock_ranges": ranges}
    return records


@dataclass(frozen=True)
class ReadPermit:
    design_path: str
    design_sha256: str
    authorization_path: str
    authorization_sha256: str
    source_hashes: Mapping[str, str]

    @classmethod
    def from_files(cls, design_path, design_sha256, authorization_path, authorization_sha256):
        """The root's reader receipt is explicit authority, never inferred from READY."""
        for path, expected in ((design_path, design_sha256), (authorization_path, authorization_sha256)):
            if digest_file(path) != expected:
                raise ValueError("READER_FREEZE_SHA_MISMATCH")
        design = json.loads(Path(design_path).read_text(encoding="utf-8"))
        receipt = json.loads(Path(authorization_path).read_text(encoding="utf-8"))
        if design.get("scientific_identity") != IDENTITY or receipt.get("scientific_identity") != IDENTITY:
            raise ValueError("R10_READER_IDENTITY")
        if receipt.get("frozen_design_sha256") != design_sha256:
            raise ValueError("READER_NOT_BOUND_TO_DESIGN")
        if receipt.get("real_numeric_read_authorized") is not True or receipt.get("2026_locked") is not True:
            raise ValueError("REAL_NUMERIC_READ_NOT_AUTHORIZED")
        if receipt.get("cutoff_exclusive") != "2026-01-01":
            raise ValueError("READER_BOUNDARY_CHANGED")
        if any(receipt.get(k) is not False for k in FALSE_AUTHORITY):
            raise ValueError("MECHANISM_AUTHORITY_PROMOTION_FORBIDDEN")
        hashes = receipt.get("source_hashes")
        if not isinstance(hashes, dict) or not hashes or any(not isinstance(v, str) or len(v) != 64 for v in hashes.values()):
            raise ValueError("READER_SOURCE_PINS_UNBOUND")
        return cls(str(design_path), design_sha256, str(authorization_path), authorization_sha256, hashes)


class MechanismReader:
    """Readonly binding to existing InputReader vector owner; no old-run mutation."""
    def __init__(self, permit: ReadPermit, sources, calendar, train_flags, pred_flags, *, metadata_pins=None):
        if not isinstance(permit, ReadPermit):
            raise ValueError("R10_READ_PERMIT_REQUIRED")
        records = guard_sources(sources)
        metadata_pins = metadata_pins or {}
        for name, pin in metadata_pins.items():
            if digest_file(pin["path"]) != pin["sha256"]:
                raise ValueError("METADATA_SOURCE_SHA:" + name)
        bound_hashes = {k: v["sha256"] for k, v in {**records, **metadata_pins}.items()}
        if bound_hashes != dict(permit.source_hashes):
            raise ValueError("READER_SOURCE_SET_NOT_FROZEN")
        self.permit = permit
        self.records = records
        self.calendar = _calendar(calendar)
        self.pred_flags = pred_flags.copy()
        self.train_flags = train_flags.copy()
        _pre2026(self.pred_flags.signal_date)
        _pre2026(self.train_flags.signal_date)
        # InputReader.__init__ invokes prepare_inputs and rewrites old manifests.
        # Bind its already-established vector method directly to guarded records.
        self._owner = object.__new__(owner.InputReader)
        self._owner.manifest = {"input_sources": records}
        self._owner.calendar = self.calendar
        self._owner.pred_flags = self.pred_flags
        self._owner.train_flags = self.train_flags

    def read(self, source, columns, filters):
        if source not in self.records or not filters:
            raise ValueError("BOUND_SOURCE_AND_FILTERS_REQUIRED")
        if digest_file(self.permit.authorization_path) != self.permit.authorization_sha256 or digest_file(self.permit.design_path) != self.permit.design_sha256:
            raise ValueError("READER_AUTH_CHANGED")
        result = self._owner._vectors(source, list(columns), filters)
        for c in self.records[source].get("date_columns", [self.records[source].get("date", "signal_date")]):
            if c in result:
                result[c] = _pre2026(result[c], nullable=c != "signal_date" and c != "trade_date")
        return result

    def prediction_vectors(self, start, end):
        start, end = pd.Timestamp(start), pd.Timestamp(end)
        if end > BOUNDARY or start >= end:
            raise ValueError("INVALID_READ_WINDOW")
        flags = self.pred_flags.loc[self.pred_flags.signal_date.ge(start) & self.pred_flags.signal_date.lt(end)].reset_index(drop=True)
        cols = ["signal_date", "ticker", *FEATURES, "raw_a2_rank", "raw_a2_prediction"]
        vectors = self.read("prediction_feature_panel", cols,
                            [("signal_date", ">=", start), ("signal_date", "<", end),
                             ("feature_available", "==", True), ("feature_source", "in", list(owner.ALLOWED_SOURCES))])
        return owner._join_vectors(flags, vectors, features=(*FEATURES, "raw_a2_rank", "raw_a2_prediction"))


def frozen_pairs(frame, *, actual_sha256=PAIR_SHA):
    """Validate immutable pre-label pair order and weights, without forming partners."""
    if actual_sha256 != PAIR_SHA:
        raise ValueError("R8_PAIR_IDENTITY_CHANGED")
    required = ("signal_date", "entrant", "entrant_sid", "incumbent", "incumbent_sid",
                "pair_id", "pair_count_before_labels", "pre_label_group_weight")
    if not set(required).issubset(frame):
        raise ValueError("PAIR_SCHEMA")
    result = frame.copy().reset_index(drop=True)
    result["signal_date"] = _pre2026(result.signal_date)
    if result.pair_id.duplicated().any() or result.duplicated(["signal_date", "entrant", "incumbent"]).any():
        raise ValueError("PAIR_DUPLICATE")
    grouped = result.groupby(["signal_date", "entrant"], sort=False)
    count = grouped.pair_id.transform("size")
    if not count.eq(result.pair_count_before_labels).all() or not np.allclose(result.pre_label_group_weight, 1 / count):
        raise ValueError("PAIR_PRELABEL_WEIGHTS_CHANGED")
    if not np.allclose(grouped.pre_label_group_weight.sum(), 1):
        raise ValueError("PAIR_WEIGHT_SUM")
    result["frozen_pair_order"] = np.arange(len(result))
    return result


def proxy_state(prediction, calendar, friction_bps=10):
    """Label-free projection of R6's exogenous cohort transitions; no pair loop.

    The small adaptation exists because the old owner combines transitions with
    prohibited two-partner mining. This state remains a proxy, never a fill age.
    """
    if friction_bps not in (5, 10, 20):
        raise ValueError("UNREGISTERED_FRICTION")
    cal = _calendar(calendar); index = {d: j for j, d in enumerate(cal)}
    pred = prediction.copy(); pred["signal_date"] = _pre2026(pred.signal_date)
    if pred.duplicated(["signal_date", "ticker"]).any() or not pred.signal_date.isin(cal).all():
        raise ValueError("STATE_KEYS")
    pred = pred.sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    pred["raw_rank"] = pred.raw_a2_rank
    pred["raw_score"] = pred.raw_a2_prediction
    groups = pred.groupby(["ticker", "security_id"], sort=False, dropna=False)
    pred["rank_change"] = pred.raw_rank - groups.raw_rank.shift(1)
    pred["score_change"] = pred.raw_score - groups.raw_score.shift(1)
    active, output = {}, []
    for date, day in pred.groupby("signal_date", sort=True):
        j = index[date]; rows = {str(r["ticker"]): r for r in day.to_dict("records")}
        for ticker, cohort in list(active.items()):
            current = rows.get(ticker)
            changed = current is not None and (not _sid(current["security_id"]) or str(current["security_id"]) != cohort["sid"])
            if j - cohort["inception"] >= 21 or changed:
                del active[ticker]
        entrants = [str(t) for t in day.loc[day.new_buy_eligible.eq(True)].sort_values(["raw_rank", "ticker"], na_position="last").ticker if str(t) not in active]
        incumbents = [t for t, c in active.items() if 0 <= j - c["inception"] < 21 and t in rows and rows[t]["feature_available"] is True]
        for ticker in sorted(set(entrants) | set(incumbents)):
            row = rows[ticker]
            if row["feature_available"] is not True or not _sid(row["security_id"]):
                continue
            cohort = active.get(ticker)
            age = j - cohort["inception"] if cohort and j >= cohort["inception"] else 0
            cid = cohort["id"] if cohort else "ENTRANT_" + str(date.date()) + "_" + ticker
            output.append({**row, "cohort_id": cid, "cohort_age_sessions": age,
                           "entrant": float(ticker in entrants), "raw_member": float(bool(row["is_raw_top20"])),
                           "friction": friction_bps / 10000, "state_role": "EXOGENOUS_COHORT_NOT_ACCOUNT"})
        for ticker in entrants:
            sid = rows[ticker]["security_id"]
            if _sid(sid) and j + 1 < len(cal):
                active[ticker] = {"sid": str(sid), "inception": j + 1, "id": str(date.date()) + "_" + str(sid) + "_" + ticker}
    return pd.DataFrame(output)


def native_endpoint_plan(keys, calendar, horizon, sid_projection, raw_quote_keys,
                         event_records, event_window: Callable, source_identity):
    """Only keys/flags/coordinates: H sessions use entry t+1 and exit t+h+1."""
    if horizon not in HORIZONS or not source_identity:
        raise ValueError("NATIVE_HORIZON_IDENTITY_REQUIRED")
    cal = _calendar(calendar); index = {d: j for j, d in enumerate(cal)}
    plan = keys[["signal_date", "ticker", "security_id"]].copy().reset_index(drop=True)
    plan["signal_date"] = _pre2026(plan.signal_date)
    if plan.duplicated(["signal_date", "ticker"]).any() or not plan.signal_date.isin(cal).all():
        raise ValueError("LABEL_KEYS")
    positions = plan.signal_date.map(index).to_numpy(int)
    for column, offset in (("execution_date", 1), ("label_end_date", horizon + 1)):
        plan[column] = [cal[j + offset] if j + offset < len(cal) else pd.NaT for j in positions]
    plan["label_mature_date"] = plan.label_end_date
    # Explicit mechanism observation approximation, distinct from actual provenance.
    plan["mechanism_observation_available_at"] = plan.label_end_date + pd.Timedelta(hours=16)
    plan["historical_available_at_bound"] = False
    plan["source_label_identity"] = source_identity
    plan["horizon_sessions"] = horizon
    plan["label_coordinate"] = f"R10_NATIVE_RAW_OPEN_SHAREHOLDER_H{horizon}_SUPPORTED_EVENTS"
    projection = sid_projection[["signal_date", "ticker", "security_id"]].copy()
    projection["signal_date"] = _pre2026(projection.signal_date)
    if projection.duplicated(["signal_date", "ticker"]).any():
        raise ValueError("SID_PROJECTION_DUPLICATE")
    projection = projection.sort_values(["ticker", "signal_date"])
    prev = projection.groupby("ticker", sort=False).security_id.shift(1)
    projection["segment"] = (projection.security_id.ne(prev) | ~projection.security_id.map(_sid)).groupby(projection.ticker, sort=False).cumsum()
    lookup = projection.set_index(["signal_date", "ticker"])
    segments = []
    for column, prefix in (("signal_date", "signal"), ("execution_date", "entry"), ("label_end_date", "exit")):
        idx = pd.MultiIndex.from_arrays([plan[column], plan.ticker], names=["signal_date", "ticker"])
        mapped = lookup.reindex(idx)
        plan[prefix + "_sid"] = mapped.security_id.to_numpy()
        segments.append(mapped.segment.to_numpy())
    plan["identity_epoch"] = plan.security_id.astype(str) + "::FROZEN_SEGMENT_" + pd.Series(segments[0], index=plan.index).astype(str)
    coordinate = (plan.security_id.map(_sid) & plan.entry_sid.eq(plan.security_id) & plan.exit_sid.eq(plan.security_id)
                  & plan.signal_sid.eq(plan.security_id) & (segments[0] == segments[1]) & (segments[1] == segments[2]))
    quotes = raw_quote_keys[["trade_date", "ticker"]].copy(); quotes["trade_date"] = _pre2026(quotes.trade_date)
    if quotes.duplicated(["trade_date", "ticker"]).any():
        raise ValueError("RAW_ENDPOINT_KEYS_DUPLICATE")
    quote_index = pd.MultiIndex.from_frame(quotes)
    entry = pd.MultiIndex.from_arrays([plan.execution_date, plan.ticker])
    exit_ = pd.MultiIndex.from_arrays([plan.label_end_date, plan.ticker])
    plan["endpoint_pair_available"] = entry.isin(quote_index) & exit_.isin(quote_index)
    quantity, unsupported, count = event_window(plan, event_records)
    plan["label_quantity_multiplier"] = quantity
    plan["label_unsupported_common_event"] = unsupported
    plan["label_common_event_count"] = count
    plan["mechanism_coordinate_supported"] = coordinate & plan.endpoint_pair_available & ~np.asarray(unsupported, bool) & np.isfinite(quantity) & (np.asarray(quantity) > 0)
    plan["strict_endpoint_source_qualified"] = False
    return plan


def native_labels(plan, raw_quotes, *, parent5=None):
    """New native y; old available parent5 rows retain exact y/maturity/SID."""
    quotes = raw_quotes[["trade_date", "ticker", "open"]].copy()
    quotes["trade_date"] = _pre2026(quotes.trade_date)
    if quotes.duplicated(["trade_date", "ticker"]).any():
        raise ValueError("RAW_ENDPOINT_DUPLICATE")
    lookup = quotes.set_index(["trade_date", "ticker"]).open
    out = plan.copy()
    prices = []
    for clock in ("execution_date", "label_end_date"):
        idx = pd.MultiIndex.from_arrays([out[clock], out.ticker], names=["trade_date", "ticker"])
        prices.append(lookup.reindex(idx).to_numpy(float))
    entry, exit_ = prices
    legal = out.mechanism_coordinate_supported.eq(True).to_numpy() & np.isfinite(entry) & np.isfinite(exit_) & (entry > 0) & (exit_ > 0)
    y = np.full(len(out), np.nan)
    y[legal] = exit_[legal] / entry[legal] * out.label_quantity_multiplier.to_numpy(float)[legal] - 1
    legal &= np.isfinite(y)
    y[~legal] = np.nan
    out["label_value"] = y; out["label_qualified"] = legal
    out["parent_valid5d_exact_reuse"] = False
    if parent5 is not None:
        if not out.horizon_sessions.eq(5).all():
            raise ValueError("PARENT5_ONLY_H5")
        parent = parent5.set_index(["signal_date", "ticker"])
        if parent.index.has_duplicates:
            raise ValueError("PARENT5_DUPLICATE")
        aligned = parent.reindex(pd.MultiIndex.from_frame(out[["signal_date", "ticker"]]))
        keep = aligned.label_available.eq(True).to_numpy()
        if not np.isfinite(aligned.loc[keep, "y_open5"].to_numpy(float)).all():
            raise ValueError("PARENT_VALID5_NONFINITE")
        if not aligned.loc[keep, "security_id"].reset_index(drop=True).eq(out.loc[keep, "security_id"].reset_index(drop=True)).all():
            raise ValueError("PARENT_VALID5_SID_CHANGED")
        old_mature = _pre2026(aligned.loc[keep, "label_mature_date"])
        out.loc[keep, "label_value"] = aligned.loc[keep, "y_open5"].to_numpy(float)
        out.loc[keep, "label_mature_date"] = old_mature.to_numpy()
        out.loc[keep, "label_qualified"] = True
        out.loc[keep, "parent_valid5d_exact_reuse"] = True
        out.loc[keep, "source_label_identity"] = "PARENT_VALID5D_EXACT_REUSE"
        out.loc[keep, "label_coordinate"] = aligned.loc[keep, "label_coordinate"].to_numpy() if "label_coordinate" in aligned else owner.LABEL
    out["strict_endpoint_source_qualified"] = False
    return out


def mean_labels(horizons):
    if set(horizons) != set(HORIZONS):
        raise ValueError("MEAN_REQUIRES_ALL_NATIVE_HORIZONS")
    key = ["signal_date", "ticker", "security_id"]
    base = horizons[3][key].reset_index(drop=True)
    values, clocks, legal = [], [], np.ones(len(base), bool)
    for h in HORIZONS:
        frame = horizons[h].reset_index(drop=True)
        if not frame[key].equals(base):
            raise ValueError("HORIZON_KEYS_OR_ORDER_CHANGED")
        values.append(frame.label_value.to_numpy(float))
        clocks.append(pd.to_datetime(frame.label_mature_date).to_numpy())
        legal &= frame.label_qualified.eq(True).to_numpy() & np.isfinite(values[-1])
    out = base.copy(); out["label_qualified"] = legal
    out["label_value"] = np.where(legal, np.mean(np.stack(values), axis=0), np.nan)
    out["label_mature_date"] = pd.DataFrame(np.stack(clocks).T).max(axis=1)
    out["source_label_identity"] = "R10_MEAN_NATIVE_H3_H5_H10_H20"
    out["strict_endpoint_source_qualified"] = False
    return out


def local_advantages(y_entrant, y_incumbent=None, *, friction_bps=10):
    if friction_bps not in (5, 10, 20):
        raise ValueError("UNREGISTERED_FRICTION")
    s = friction_bps / 10000; k = (1 - s) / (1 + s)
    e = np.asarray(y_entrant, dtype=float)
    result = {"ENTRY": k * (1 + e) - 1, "INCUMBENT": -(1 - s) * e,
              "CONTINUATION": e}
    if y_incumbent is not None:
        result["REPLACE"] = (1 - s) * (k * (1 + e) - (1 + np.asarray(y_incumbent, dtype=float)))
    return result


def attach_single_labels(state, labels, head, *, friction_bps=10):
    if head not in ("ENTRY", "INCUMBENT", "CONTINUATION"):
        raise ValueError("UNKNOWN_SINGLE_HEAD")
    frame = state.loc[state.entrant.eq(1) if head == "ENTRY" else state.entrant.eq(0)].copy()
    cols = ["signal_date", "ticker", "security_id", "label_value", "label_qualified", "label_mature_date", "source_label_identity"]
    frame = frame.merge(labels[cols], on=["signal_date", "ticker", "security_id"], how="left", sort=False, validate="one_to_one")
    frame["label_qualified"] = frame.label_qualified.eq(True) & np.isfinite(frame.label_value)
    frame["target"] = np.where(frame.label_qualified, local_advantages(frame.label_value, friction_bps=friction_bps)[head], np.nan)
    frame["objective"] = head
    return frame


def attach_pair_labels(pairs, state, labels, *, friction_bps=10):
    """Left joins preserve all frozen rows; missing labels never replace a partner."""
    frame = pairs.copy(); original = frame.pair_id.reset_index(drop=True)
    state_columns = [*FEATURES, *STATE]
    for prefix, ticker, sid in (("e_", "entrant", "entrant_sid"), ("i_", "incumbent", "incumbent_sid")):
        source = state[["signal_date", "ticker", "security_id", *state_columns]].copy()
        source = source.rename(columns={"ticker": ticker, "security_id": sid, **{c: prefix + c for c in state_columns}})
        frame = frame.merge(source, on=["signal_date", ticker, sid], how="left", sort=False, validate="many_to_one")
        lab = labels[["signal_date", "ticker", "security_id", "label_value", "label_qualified", "label_mature_date"]].rename(columns={"ticker": ticker, "security_id": sid, "label_value": prefix + "y", "label_qualified": prefix + "legal", "label_mature_date": prefix + "mature"})
        frame = frame.merge(lab, on=["signal_date", ticker, sid], how="left", sort=False, validate="many_to_one")
    if not frame.pair_id.reset_index(drop=True).equals(original):
        raise ValueError("FROZEN_PAIR_ORDER_CHANGED")
    for column in state_columns:
        frame["delta_" + column] = frame["e_" + column] - frame["i_" + column]
    available = frame["e_friction"].notna() & frame["i_friction"].notna()
    frame["label_qualified"] = frame.e_legal.eq(True) & frame.i_legal.eq(True) & np.isfinite(frame.e_y) & np.isfinite(frame.i_y) & available
    frame["target"] = np.where(frame.label_qualified, local_advantages(frame.e_y, frame.i_y, friction_bps=friction_bps)["REPLACE"], np.nan)
    frame["label_mature_date"] = frame[["e_mature", "i_mature"]].max(axis=1)
    count = frame.groupby(["signal_date", "entrant"], sort=False).label_qualified.transform("sum")
    frame["supported_training_group_weight"] = np.where(frame.label_qualified & count.gt(0), 1 / count.where(count.gt(0), 1), 0.0)
    frame["objective"] = "REPLACE"
    return frame


def full20_baskets(prediction, labels):
    """One equal Raw20 return only when every fixed member is supported."""
    output = []
    for date, day in prediction.groupby("signal_date", sort=True):
        raw = day.loc[day.is_raw_top20.eq(True)].sort_values(["raw_a2_rank", "ticker"])
        if len(raw) != 20 or raw.ticker.nunique() != 20 or not raw.raw_top20_set_complete.eq(True).all() or not raw.feature_available.eq(True).all() or not np.isfinite(raw[list(FEATURES)].to_numpy(float)).all():
            continue
        joined = raw.merge(labels[["signal_date", "ticker", "security_id", "label_value", "label_qualified", "label_mature_date"]], on=["signal_date", "ticker", "security_id"], how="left", validate="one_to_one")
        legal = len(joined) == 20 and joined.label_qualified.eq(True).all() and np.isfinite(joined.label_value).all()
        output.append({"signal_date": date, "basket_members": tuple(raw.ticker), "basket_sids": tuple(raw.security_id), "raw20_count": 20,
                       "label_qualified": bool(legal), "basket_y": float(joined.label_value.mean()) if legal else np.nan,
                       "label_mature_date": joined.label_mature_date.max() if legal else pd.NaT,
                       **{"mean_" + c: float(raw[c].mean()) for c in FEATURES},
                       "account_state_qualified": False})
    return pd.DataFrame(output)


def legal_rows(frame, cutoff, *, target="target"):
    """All legal rows; no 12,000 cap, strict signal AND maturity before own cutoff."""
    cutoff = pd.Timestamp(cutoff)
    if cutoff > BOUNDARY:
        raise ValueError("2026_LOCKED")
    signal = _pre2026(frame.signal_date)
    mature = _pre2026(frame.label_mature_date, nullable=True)
    mask = frame.label_qualified.eq(True) & np.isfinite(frame[target]) & signal.lt(cutoff) & mature.notna() & mature.lt(cutoff)
    return frame.loc[mask].copy()


def date_equal_weights(frame, *, base_column=None):
    if frame.empty:
        return np.empty(0, float)
    base = np.ones(len(frame), float) if base_column is None else frame[base_column].to_numpy(float)
    if not np.isfinite(base).all() or (base < 0).any():
        raise ValueError("INVALID_BASE_WEIGHT")
    grouped = pd.Series(base, index=frame.index).groupby(frame.signal_date, sort=False).transform("sum").to_numpy()
    return np.divide(base, grouped, out=np.zeros_like(base), where=grouped > 0)


def hazard_probes(incumbent, calendar, *, ages, stride):
    """Mature positive previous probe creates risk set; unknown probe censors."""
    if stride <= 0 or any(a < 0 for a in ages):
        raise ValueError("INVALID_HAZARD_DESIGN")
    cal = _calendar(calendar); output = []; probes = {}
    for row in incumbent.sort_values(["signal_date", "ticker"]).to_dict("records"):
        age = int(row["cohort_age_sessions"])
        if age not in ages:
            continue
        prev = probes.get(row["cohort_id"])
        at_risk = age == min(ages) or (prev is not None and prev["age"] == age - stride and prev["legal"] and prev["mature"] < row["signal_date"] and prev["value"] > 0)
        if not at_risk:
            continue
        legal = row.get("label_qualified") is True and np.isfinite(row.get("label_value", np.nan))
        output.append({**row, "probe_age": age, "target": float(row["label_value"] <= 0) if legal else np.nan,
                       "right_censored_unknown": not legal, "hazard_at_risk": True})
        probes[row["cohort_id"]] = {"age": age, "legal": legal, "mature": pd.Timestamp(row["label_mature_date"]) if legal else BOUNDARY,
                                    "value": row["label_value"] if legal else np.nan}
    return pd.DataFrame(output)


@dataclass(frozen=True)
class SequenceBlock:
    keys: pd.DataFrame
    dates: np.ndarray
    values: np.ndarray
    cell_observed: np.ndarray
    step_available: np.ndarray
    window_complete: np.ndarray
    columns: tuple[str, ...]
    role: str = "R10_PAST_ONLY_SAME_SID_MECHANISM_SEQUENCE"


def sequence_blocks(history, keys, calendar, length, columns: Sequence[str]):
    """Same-SID past calendar window, including signal day, explicit missing masks."""
    if length not in (5, 10, 20):
        raise ValueError("UNREGISTERED_SEQUENCE_LENGTH")
    cal = _calendar(calendar); index = {d: j for j, d in enumerate(cal)}
    hist = history.copy(); hist["signal_date"] = _pre2026(hist.signal_date)
    key = keys[["signal_date", "ticker", "security_id"]].copy().reset_index(drop=True)
    key["signal_date"] = _pre2026(key.signal_date)
    if hist.duplicated(["signal_date", "ticker"]).any() or not key.signal_date.isin(cal).all():
        raise ValueError("SEQUENCE_KEYS")
    lookup = hist.set_index(["signal_date", "ticker"])
    all_dates = np.full((len(key), length), np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
    x = np.full((len(key), length, len(columns)), np.nan)
    available = np.zeros((len(key), length), bool)
    # Call-local row indices reuse immutable windows without retaining extra tensors.
    window_rows = {}
    for n, row in enumerate(key.to_dict("records")):
        cache_key = (row["signal_date"], row["ticker"], row["security_id"], length) if isinstance(row["ticker"], str) and isinstance(row["security_id"], str) else None
        prior = window_rows.get(cache_key) if cache_key is not None else None
        if prior is not None:
            all_dates[n] = all_dates[prior]
            x[n] = x[prior]
            available[n] = available[prior]
            continue
        j = index[row["signal_date"]]; dates = cal[max(0, j - length + 1):j + 1]
        offset = length - len(dates); all_dates[n, offset:] = dates.to_numpy()
        idx = pd.MultiIndex.from_product([dates, [row["ticker"]]], names=["signal_date", "ticker"])
        part = lookup.reindex(idx)
        same = part.security_id.eq(row["security_id"]).to_numpy() & part.feature_available.eq(True).to_numpy()
        values = part[list(columns)].to_numpy(float)
        x[n, offset:] = np.where(same[:, None], values, np.nan)
        available[n, offset:] = same
        if cache_key is not None:
            window_rows[cache_key] = n
    return SequenceBlock(key, all_dates, x, np.isfinite(x), available, available.all(axis=1), tuple(columns))


@dataclass(frozen=True)
class MechanismFrames:
    state: pd.DataFrame
    labels: Mapping[object, pd.DataFrame]
    heads: Mapping[object, Mapping[str, pd.DataFrame]]
    gross: Mapping[object, pd.DataFrame]
    source_refs: Mapping[str, Mapping]
    real_account_state: bool = False


def build_frames(prediction, calendar, pairs, labels, *, friction_bps=10, source_refs=None, state=None):
    state = proxy_state(prediction, calendar, friction_bps) if state is None else state
    fixed = frozen_pairs(pairs)
    heads, gross = {}, {}
    for horizon, packet in labels.items():
        single = {h: attach_single_labels(state, packet, h, friction_bps=friction_bps) for h in ("ENTRY", "INCUMBENT", "CONTINUATION")}
        single["REPLACE"] = attach_pair_labels(fixed, state, packet, friction_bps=friction_bps)
        heads[horizon] = single
        gross[horizon] = full20_baskets(prediction, packet)
    return MechanismFrames(state, labels, heads, gross, source_refs or {})


BASE = owner.PARENT
R8_DERIVED = Path("D:/us-tech-quant-backtests/V24_A_STATE_AND_LABEL_FOUNDATION_PRE2026_R8/20261003T124029+0000_b73751bf/derived")


def r10_source_manifest():
    """Frozen existing inputs only; the root pins this complete map in its design."""
    specs = {name: dict(pin) for name, pin in owner.SOURCES.items()}
    specs["value_training_panel"]["date_columns"] = ["signal_date", "label_mature_date"]
    specs["five_day_extension"] = {"path": "D:/us-tech-quant-results/JOINT_TOP20_PORTFOLIO_POLICY_PRE2026_TEST2026_R1/V24/cache/five_day_shareholder_targets.parquet",
        "sha256": "555fef4dea2112809af44c388025852d9363bc7f55b40b2e4871f526568c9eb9", "rows": 907902,
        "date_columns": ["signal_date", "execution_date", "label_end_date", "label_mature_date"]}
    specs["r8_pair_keys"] = {"path": str(R8_DERIVED / "PAIR_SUPPORT_EXPANSION_KEYS.parquet"),
        "sha256": PAIR_SHA, "rows": 73433, "date": "signal_date"}
    meta = {
        "shared_risk_clock_owner": {"path": "D:/us-tech-quant/scripts/research/a2/data/shared_risk_inputs_r3.py",
            "sha256": "d398dcc77ab32ff8a15ee041deac4e6ab23fcd7542c456dd8eb44b03d526f997"},
        "event_binding": {"path": str(BASE / "ACCOUNT_EVENT_BINDING_R1.json"),
            "sha256": "dcccd212284b2a650e291c0c0fa8f42401f8329acd6b1ba491dfa2093521a2d9"},
        "event_window_owner": {"path": str(BASE / "LABEL_REPAIR_R1.py"),
            "sha256": "7ab35af794d1cbc5df1de84d72891bd5ff2605cbd44f6a1bfe0eff417fa74b59"},
        "parent_label_binding": {"path": str(BASE / "INPUT_BINDING_R1.json"),
            "sha256": "c3b16cf8608b27ca9587c19145c3af2faba9a5ccb7dd80b91b1a15d40b7a0742"}}
    return {"parquet_sources": specs, "metadata_pins": meta,
            "source_hashes": {k: v["sha256"] for k, v in {**specs, **meta}.items()},
            "future_source_flags": {k: False for k in FALSE_AUTHORITY}, "2026_locked": True}


def load_event_owner(metadata_pins):
    """Import the exact reviewed frozen window function, never its run() writer."""
    for key in ("event_binding", "event_window_owner"):
        pin = metadata_pins[key]
        if digest_file(pin["path"]) != pin["sha256"]:
            raise ValueError("EVENT_OWNER_PIN_CHANGED")
    binding = json.loads(Path(metadata_pins["event_binding"]["path"]).read_text(encoding="utf-8"))
    events = binding["event_records"]
    _pre2026(pd.Series([r["event_date"] for r in events]))
    path = Path(metadata_pins["event_window_owner"]["path"])
    spec = importlib.util.spec_from_file_location("r10_frozen_event_window_owner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return events, module.apply_event_windows


@dataclass(frozen=True)
class RealInputBundle:
    frames: MechanismFrames
    reader: MechanismReader
    prediction_history: pd.DataFrame
    native_endpoint_labels: Mapping[int, pd.DataFrame]
    metadata_coverage: Mapping
    source_manifest: Mapping
    real_fit: int = 0
    real_account: int = 0


def build_real_frames(permit: ReadPermit, design: Mapping):
    """One root-authorized read/production, returning frames without creating a run.

    All old available 5D values are exact reused. Newly supported 5D values are
    exact consumed from the existing extension under this distinct R10 identity;
    H3/H10/H20 use actual frozen raw endpoint pairs and the same event-window owner.
    """
    if not isinstance(permit, ReadPermit) or design.get("scientific_identity") != IDENTITY:
        raise ValueError("FROZEN_R10_DESIGN_AND_READ_PERMIT_REQUIRED")
    frozen = json.loads(Path(permit.design_path).read_text(encoding="utf-8"))
    if frozen != dict(design):
        raise ValueError("DESIGN_NOT_EXACT_FROZEN_BYTES")
    manifest = r10_source_manifest()
    if dict(permit.source_hashes) != manifest["source_hashes"]:
        raise ValueError("FULL_INPUT_SOURCE_MANIFEST_NOT_FROZEN")
    specs, meta = manifest["parquet_sources"], manifest["metadata_pins"]
    records = guard_sources(specs)
    # Materialize metadata only after EVERY parquet is physically pre-2026.
    def flags(name, columns):
        p = Path(records[name]["path"]); before = p.stat()
        f = pq.read_table(p, columns=list(columns)).to_pandas()
        if {"size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns} != records[name]["file_fingerprint"]:
            raise ValueError("SOURCE_CHANGED_DURING_METADATA_READ")
        return f
    cal = _calendar(flags("calendar", ["trade_date"]).trade_date)
    train = owner._flags(flags("value_training_panel", [*owner.TRAIN_FLAGS, "security_id"]), True)
    pred = owner._flags(flags("prediction_feature_panel", owner.PRED_FLAGS))
    pairs = flags("r8_pair_keys", ["signal_date", "entrant", "entrant_sid", "incumbent", "incumbent_sid", "cohort_age_sessions", "raw_rank", "pair_count_before_labels", "pre_label_group_weight", "pair_id"])
    fixed = frozen_pairs(pairs, actual_sha256=records["r8_pair_keys"]["sha256"])
    reader = MechanismReader(permit, specs, cal, train, pred, metadata_pins=meta)
    history = reader.prediction_vectors(cal.min(), BOUNDARY)
    state = proxy_state(history, cal, friction_bps=10)
    # Only the mechanically defined opportunity/state/Raw20 key union is labeled.
    # Historical endpoint inputs for shared risk can use the same plan producer
    # with their predeclared domain; this helper does not choose another domain.
    state_keys = state[["signal_date", "ticker", "security_id"]]
    raw_keys = pred.loc[pred.is_raw_top20.eq(True), ["signal_date", "ticker", "security_id"]]
    keys = pd.concat([state_keys, raw_keys], ignore_index=True).drop_duplicates().sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    if keys.duplicated(["signal_date", "ticker"]).any():
        raise ValueError("STATE_RAW20_SID_CONFLICT")
    quotes = reader.read("raw_market_prices", ["trade_date", "ticker", "open"], [("trade_date", "<", BOUNDARY)])
    quote_keys = quotes[["trade_date", "ticker"]]
    events, event_window = load_event_owner(meta)
    parent = reader.read("value_training_panel", ["signal_date", "ticker", "security_id", "label_available", "label_mature_date", "label_coordinate", "y_open5"],
                         [("signal_date", "<", BOUNDARY), ("label_available", "==", True)])
    extension = reader.read("five_day_extension", ["signal_date", "ticker", "execution_date", "label_end_date", "label_mature_date", "label_available", "label_unsupported_common_event", "label_quantity_multiplier", "y_open5"],
                            [("signal_date", "<", BOUNDARY), ("label_available", "==", True)])
    if not np.isfinite(extension.y_open5).all():
        raise ValueError("AVAILABLE_EXTENSION_NONFINITE_Y")
    packets = {}
    for h in HORIZONS:
        planned = native_endpoint_plan(keys, cal, h, pred, quote_keys, events, event_window, f"R10_NATIVE_H{h}_FROZEN_HISTORY_MECHANISM")
        packet = native_labels(planned, quotes, parent5=parent if h == 5 else None)
        if h == 5:
            old = extension.set_index(["signal_date", "ticker"])
            if old.index.has_duplicates:
                raise ValueError("EXISTING_EXTENSION_DUPLICATE")
            aligned = old.reindex(pd.MultiIndex.from_frame(packet[["signal_date", "ticker"]]))
            reuse = packet.label_qualified.eq(True).to_numpy() & ~packet.parent_valid5d_exact_reuse.to_numpy() & aligned.label_available.eq(True).to_numpy() & ~aligned.label_unsupported_common_event.eq(True).to_numpy()
            if reuse.any():
                if not np.allclose(packet.loc[reuse, "label_value"], aligned.loc[reuse, "y_open5"], rtol=0, atol=1e-12):
                    raise ValueError("EXISTING_EXTENSION_NATIVE_FORMULA_CHANGED")
                if not pd.to_datetime(aligned.loc[reuse, "label_mature_date"]).reset_index(drop=True).eq(packet.loc[reuse, "label_mature_date"].reset_index(drop=True)).all():
                    raise ValueError("EXISTING_EXTENSION_MATURITY_CHANGED")
                if not aligned.loc[reuse, "label_quantity_multiplier"].reset_index(drop=True).eq(packet.loc[reuse, "label_quantity_multiplier"].reset_index(drop=True)).all():
                    raise ValueError("EXISTING_EXTENSION_QUANTITY_CHANGED")
                packet.loc[reuse, "label_value"] = aligned.loc[reuse, "y_open5"].to_numpy(float)
                packet.loc[reuse, "source_label_identity"] = "R10_EXISTING_5D_EXTENSION_EXACT_VALUES"
        if not np.isfinite(packet.loc[packet.label_qualified.eq(True), "label_value"]).all():
            raise ValueError("SUPPORTED_Y_NONFINITE")
        packets[h] = packet
    all_packets = {**packets, "MEAN": mean_labels(packets)}
    frames = build_frames(history, cal, fixed, all_packets, source_refs={**records, **meta}, state=state)
    coverage = {str(h): {"label_rows": len(packet), "qualified_rows": int(packet.label_qualified.sum()),
                          "qualified_by_year": packet.loc[packet.label_qualified.eq(True)].groupby(packet.signal_date.dt.year).size().to_dict(),
                          "full20_qualified_dates": int(frames.gross[h].label_qualified.sum()) if not frames.gross[h].empty else 0}
                for h, packet in all_packets.items()}
    coverage.update(pair_rows=len(fixed), pair_sha256=PAIR_SHA, state_rows=len(state), source_authority_upgraded=False,
                    no_new_scientific_run_created=True, target_input_role="LOCAL_MECHANISM_NOT_CERTIFIED_ACCOUNT")
    return RealInputBundle(frames, reader, history, packets, coverage, manifest)


def native_risk_observations(packet, *, domain_epoch=None, composite_source_identity=None, asset_epochs=None):
    """Translate labels through the shared clock owner, retaining row provenance.

    Unassembled observations retain their security segment epoch. A caller may
    bind a whole risk domain only after supplying and matching the asset epochs;
    the original segment and label identities remain explicit proof columns.
    """
    from scripts.research.a2.data.shared_risk_inputs_r3 import _clock
    legal = packet.label_qualified.eq(True) & packet.mechanism_coordinate_supported.eq(True) & np.isfinite(packet.label_value)
    out = packet.loc[legal].copy()
    bound = domain_epoch is not None or composite_source_identity is not None or asset_epochs is not None
    if bound:
        if not isinstance(domain_epoch, str) or not domain_epoch or not isinstance(composite_source_identity, str) or not composite_source_identity or not isinstance(asset_epochs, dict):
            raise ValueError("COMPLETE_NATIVE_RISK_DOMAIN_BINDING_REQUIRED")
        matches = out.identity_epoch.eq(out.ticker.map(asset_epochs))
        out = out.loc[matches].copy()
    result = pd.DataFrame({"asset": out.ticker,
        "signal_date": out.signal_date, "execution_date": out.execution_date,
        "label_end_date": out.label_end_date, "label_mature_date": out.label_mature_date,
        "origin_at": out.signal_date.map(_clock),
        "entry_at": out.execution_date.map(lambda d: _clock(d, opening=True)),
        "endpoint_at": out.label_end_date.map(lambda d: _clock(d, opening=True)),
        "matured_at": out.label_mature_date.map(_clock),
        "available_at": [max(_clock(mature), _clock(end)) for mature, end in zip(out.label_mature_date, out.label_end_date)],
        "horizon": out.horizon_sessions, "uid": out.security_id,
        "identity_epoch": domain_epoch if bound else out.identity_epoch,
        "source_identity": composite_source_identity if bound else out.source_label_identity,
        "security_segment_epoch": out.identity_epoch,
        "original_label_identity": out.source_label_identity,
        "return_value": out.label_value, "quantity_multiplier": out.label_quantity_multiplier,
        "aggregate_domain_bound": bound,
        "mechanism_coordinate_supported": True, "strict_endpoint_source_qualified": False,
        "historical_available_at_bound": False})
    if len(result) and not ((result.origin_at < result.entry_at) & (result.entry_at < result.endpoint_at) & (result.endpoint_at <= result.matured_at) & (result.matured_at <= result.available_at)).all():
        raise ValueError("NATIVE_RISK_CLOCK_ORDER")
    return result.reset_index(drop=True)


GROSS_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)


def gross_decision_frame(gross_by_horizon, stock_forecasts, risk_context_by_date, *,
                         risk_columns, replacement_proxy_column="replacement_proxy",
                         context_qualified_column="risk_context_qualified", decision_dates=None,
                         friction_bps=10):
    """Fixed 5x5 Gross grid; no partial basket or manufactured context.

    The target is the mean of FOUR native-horizon utilities, including their
    separate squared returns. It is deliberately not utility(mean return).
    Forecast/risk producers own every supplied numeric context. This function
    only verifies fixed members and projects their values into declared columns.
    """
    if set(gross_by_horizon) != set(HORIZONS) or friction_bps not in (5, 10, 20):
        raise ValueError("GROSS_NATIVE_HORIZON_OR_FRICTION_IDENTITY")
    risk_columns = tuple(dict.fromkeys(risk_columns))
    if any(c in FEATURES or c.startswith("mean_") or c in ("target", "gross_previous_proxy", "gross_candidate") for c in risk_columns):
        raise ValueError("RISK_CONTEXT_COLLIDES_WITH_FROZEN_FEATURES")
    packets = {}
    for h in HORIZONS:
        f = gross_by_horizon[h].copy()
        if "signal_date" not in f:
            packets[h] = pd.DataFrame(columns=["signal_date"]).set_index("signal_date")
            continue
        f["signal_date"] = _pre2026(f.signal_date)
        if f.signal_date.duplicated().any():
            raise ValueError("GROSS_HORIZON_DATE_DUPLICATE")
        if "label_mature_date" in f:
            f["label_mature_date"] = _pre2026(f.label_mature_date, nullable=True)
        packets[h] = f.set_index("signal_date")
    dates = _calendar(decision_dates) if decision_dates is not None else pd.DatetimeIndex(sorted(set().union(*(set(f.index) for f in packets.values()))))
    forecasts = stock_forecasts.copy(); context = risk_context_by_date.copy()
    forecast_schema = {"signal_date", "ticker", "security_id", "pointAdvantage", "nativeSigma"}
    forecast_columns_bound = forecast_schema.issubset(forecasts)
    if "signal_date" in forecasts:
        forecasts["signal_date"] = _pre2026(forecasts.signal_date)
        if forecast_columns_bound and forecasts.duplicated(["signal_date", "ticker", "security_id"]).any():
            raise ValueError("GROSS_FORECAST_DUPLICATE")
    required_context = tuple(dict.fromkeys((*risk_columns, replacement_proxy_column)))
    context_schema = {"signal_date", context_qualified_column, *required_context}
    context_columns_bound = context_schema.issubset(context)
    if "signal_date" in context:
        context["signal_date"] = _pre2026(context.signal_date)
        if context.signal_date.duplicated().any():
            raise ValueError("GROSS_CONTEXT_DATE_DUPLICATE")
        context = context.set_index("signal_date")
    output = []; s = friction_bps / 10000
    for date in dates:
        reasons, label_reasons = [], []
        horizon_rows = {h: packets[h].loc[date] if date in packets[h].index else None for h in HORIZONS}
        first = next((r for r in horizon_rows.values() if r is not None), None)
        members = tuple(first.get("basket_members", ())) if first is not None else ()
        sids = tuple(first.get("basket_sids", ())) if first is not None else ()
        member_ok = len(members) == len(sids) == 20 and len(set(members)) == 20 and all(_sid(v) for v in sids)
        y, maturity = [], []
        for h, row in horizon_rows.items():
            if row is None:
                label_reasons.append("MISSING_REQUIRED_HORIZON_H" + str(h)); continue
            same_members = tuple(row.get("basket_members", ())) == members and tuple(row.get("basket_sids", ())) == sids
            value = row.get("basket_y", np.nan); clock = row.get("label_mature_date", pd.NaT)
            qualified = row.get("label_qualified") is True or isinstance(row.get("label_qualified"), np.bool_) and bool(row.get("label_qualified"))
            if not member_ok or not same_members or row.get("raw20_count") != 20 or not qualified or not np.isfinite(value) or pd.isna(clock):
                label_reasons.append("FULL20_LABEL_UNQUALIFIED_H" + str(h))
            y.append(float(value)); maturity.append(clock)
        label_supported = not label_reasons and len(y) == 4
        base_features = {"mean_" + c: first.get("mean_" + c, np.nan) if first is not None else np.nan for c in FEATURES}
        if not member_ok or not np.isfinite(np.asarray(list(base_features.values()), float)).all():
            reasons.append("FROZEN_RAW20_OR_FEATURE_CONTEXT_UNQUALIFIED")
        forecast_features = {"opportunity_breadth": np.nan, "average_positive_advantage": np.nan, "native_uncertainty_mean": np.nan}
        if not forecast_columns_bound or not member_ok:
            reasons.append("REQUIRED_FORECAST_SCHEMA_OR_MEMBER_IDENTITY_MISSING")
        else:
            current = forecasts.loc[forecasts.signal_date.eq(date)].set_index(["ticker", "security_id"])
            expected = pd.MultiIndex.from_tuples(list(zip(members, sids)), names=["ticker", "security_id"])
            aligned = current.reindex(expected)
            mean = aligned.pointAdvantage.to_numpy(float); sigma = aligned.nativeSigma.to_numpy(float)
            if not np.isfinite(mean).all() or not np.isfinite(sigma).all() or (sigma < 0).any():
                reasons.append("ALL20_NATIVE_FORECAST_CONTEXT_UNQUALIFIED")
            else:
                forecast_features = {"opportunity_breadth": float(np.mean(mean > 0)),
                                     "average_positive_advantage": float(np.mean(np.maximum(mean, 0))),
                                     "native_uncertainty_mean": float(np.mean(sigma))}
        context_features = {c: np.nan for c in required_context}
        if not context_columns_bound or date not in context.index:
            reasons.append("REQUIRED_RISK_REPLACEMENT_CONTEXT_UNBOUND")
        else:
            row = context.loc[date]
            accepted = row[context_qualified_column] is True or isinstance(row[context_qualified_column], np.bool_) and bool(row[context_qualified_column])
            vals = np.asarray([row[c] for c in required_context], float)
            if not accepted or not np.isfinite(vals).all():
                reasons.append("REQUIRED_RISK_REPLACEMENT_CONTEXT_UNQUALIFIED")
            else:
                context_features = dict(zip(required_context, vals))
        information_supported = not reasons
        mature = max(maturity) if label_supported else pd.NaT
        for previous in GROSS_GRID:
            for candidate in GROSS_GRID:
                utility = float(np.mean([candidate*v - s*abs(candidate-previous) - s*candidate*(1+v) - 5*candidate**2*v**2 for v in y])) if label_supported and information_supported else np.nan
                output.append({"signal_date": date, "sample_id": f"{date.date()}|GP{previous}|GC{candidate}",
                    "ticker": "FROZEN_RAW20_BASKET", "security_id": "R10_RAW20_DATE_MEMBERSHIP",
                    "basket_members": members, "basket_sids": sids, "raw20_count": len(members),
                    **base_features, **forecast_features, **context_features,
                    "gross_previous_proxy": previous, "gross_candidate": candidate,
                    "friction": s, "label_qualified": label_supported,
                    "information_supported": information_supported, "label_mature_date": mature,
                    "target": utility, "base_weight": 1., "reference_action": 1.,
                    "label_blocked_reason": "|".join(label_reasons) or None,
                    "information_blocked_reason": "|".join(reasons) or None,
                    "blocked_reason": "|".join((*label_reasons, *reasons)) or None,
                    **{"basket_y_H" + str(h): horizon_rows[h].get("basket_y", np.nan) if horizon_rows[h] is not None else np.nan for h in HORIZONS},
                    "utility_role": "MEAN_OF_NATIVE_HORIZON_GROSS_UTILITIES_NOT_SELF_FINANCING_ACCOUNT",
                    "account_state_qualified": False, "source_account_authority_upgraded": False})
    result = pd.DataFrame(output)
    result.attrs["feature_columns"] = tuple(dict.fromkeys((*base_features.keys(), *forecast_features.keys(), *required_context, "gross_previous_proxy", "gross_candidate", "friction"))) if output else ()
    result.attrs["native_horizons"] = HORIZONS
    result.attrs["all20_required"] = True
    result.attrs["2026_locked"] = True
    return result
