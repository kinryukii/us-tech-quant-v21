"""Pure in-memory packaging for the frozen-history B risk interface.

No readers, fitters, source discovery, price filling, label production or authority
promotion. Caller-owned membership metadata defines observed UID continuity;
label availability never defines inference support or an identity segment.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Mapping
import numpy as np
import pandas as pd

from scripts.research.a2.risk.shared_risk_engine_r2 import (
    RiskInput, SourceReceipt, COORDINATE, BENCHMARK_PROXY_COORDINATE, META, _time,
)

NY = "America/New_York"
BOUNDARY = pd.Timestamp("2026-01-01", tz="UTC")
STORED_LABEL_COORDINATE = "SHAREHOLDER_OPEN_T_PLUS_1_TO_T_PLUS_6_5_SESSION_RETURN_SUPPORTED_EVENTS_FAIL_CLOSED"
STOCK_METADATA = ("ticker", "signal_date", "security_id", "execution_date", "label_end_date",
                  "label_mature_date", "label_coordinate", "label_available",
                  "label_unsupported_common_event", "endpoint_pair_available")
OBSERVATION_COLUMNS = (*META, "return_value")


@dataclass(frozen=True)
class RiskInputAssembly:
    risk_input: RiskInput
    support_declarations: Mapping


def _require(frame, columns, name):
    if not isinstance(frame, pd.DataFrame) or not set(columns).issubset(frame.columns):
        raise ValueError(name + "_METADATA_SCHEMA_REQUIRED")


def _true(value):
    return isinstance(value, (bool, np.bool_)) and bool(value)


def _false(value):
    return isinstance(value, (bool, np.bool_)) and not bool(value)


def _same(value, expected):
    return isinstance(value, str) and value == expected


def _dates(values, name, *, nullable=False):
    result = []
    for value in values:
        t = pd.Timestamp(value)
        if pd.isna(t):
            if nullable:
                result.append(pd.NaT)
                continue
            raise ValueError(name + "_NULL_DATE")
        if t.tzinfo is not None or t != t.normalize():
            raise ValueError(name + "_EXPLICIT_DATE_ONLY_REQUIRED")
        if t >= pd.Timestamp("2026-01-01"):
            raise ValueError(name + "_PRE2026_REQUIRED")
        result.append(t)
    return pd.Series(result, index=values.index, dtype="datetime64[ns]")


@lru_cache(maxsize=4096)
def _clock(day, *, opening=False):
    hours, minutes = (9, 30) if opening else (16, 0)
    return (pd.Timestamp(day) + pd.Timedelta(hours=hours, minutes=minutes)).tz_localize(NY).tz_convert("UTC")


def _calendar(values):
    days = []
    for value in values:
        t = pd.Timestamp(value)
        if pd.isna(t):
            raise ValueError("LEGAL_CALENDAR_REQUIRED")
        if t.tzinfo is not None:
            local = t.tz_convert(NY)
            if (local.hour, local.minute, local.second, local.microsecond, local.nanosecond) != (16, 0, 0, 0, 0):
                raise ValueError("CALENDAR_NY1600_ASSUMED_CLOSE_REQUIRED")
            t = local.tz_localize(None).normalize()
        elif t != t.normalize():
            raise ValueError("CALENDAR_DATE_ONLY_REQUIRED")
        if t >= pd.Timestamp("2026-01-01"):
            raise ValueError("CALENDAR_PRE2026_REQUIRED")
        days.append(t)
    index = pd.DatetimeIndex(days)
    if index.empty or index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError("LEGAL_CALENDAR_REQUIRED")
    return index, pd.DatetimeIndex([_clock(d) for d in index])


def _segments(history, days, closes, assets, uids, epochs, cutoff):
    _require(history, ("ticker", "signal_date", "security_id", "available_at"), "IDENTITY_HISTORY")
    columns = ["ticker", "signal_date", "security_id", "available_at"]
    has_epoch = "identity_epoch" in history.columns
    if has_epoch:
        columns.append("identity_epoch")
    frame = history.loc[:, columns].copy()
    frame["signal_date"] = _dates(frame.signal_date, "IDENTITY_HISTORY")
    frame["available_at"] = frame.available_at.map(_time)
    if frame.available_at.ge(BOUNDARY).any():
        raise ValueError("IDENTITY_HISTORY_PRE2026_REQUIRED")
    if frame.duplicated(["ticker", "signal_date"]).any():
        raise ValueError("AMBIGUOUS_IDENTITY_SESSION")
    positions = {d: i for i, d in enumerate(days)}
    if any(d not in positions for d in frame.signal_date):
        raise ValueError("IDENTITY_NONCALENDAR_SESSION")
    legal = frame.loc[frame.available_at.le(cutoff) & frame.signal_date.map(_clock).le(cutoff)]
    expected = np.flatnonzero(closes <= cutoff)
    if not len(expected):
        raise ValueError("PRIOR_IDENTITY_SESSION_REQUIRED")
    last = int(expected[-1])
    segments = {}
    for asset in assets:
        rows = legal.loc[legal.ticker.eq(asset)].sort_values("signal_date")
        if (rows.empty or positions[rows.iloc[-1].signal_date] != last
                or not _same(rows.iloc[-1].security_id, uids[asset])
                or (has_epoch and not _same(rows.iloc[-1].identity_epoch, epochs[asset]))):
            segments[asset] = None
            continue
        start = last
        for row in rows.iloc[::-1].itertuples():
            position = positions[row.signal_date]
            if (position != start or not _same(row.security_id, uids[asset])
                    or (has_epoch and not _same(row.identity_epoch, epochs[asset]))):
                break
            start -= 1
        segments[asset] = (start + 1, last)
    return segments


def _stock_observations(labels, days, assets, uids, epochs, epoch, receipt, cutoff, segments):
    _require(labels, (*STOCK_METADATA, "y_open5"), "STORED_H5")
    # Metadata projection and the complete pre2026 guard precede every value access.
    columns = [*STOCK_METADATA, *[c for c in ("identity_epoch", "available_at") if c in labels.columns]]
    frame = labels.loc[:, columns].copy().reset_index(drop=True)
    for name in ("signal_date", "execution_date", "label_end_date", "label_mature_date"):
        frame[name] = _dates(frame[name], name.upper(), nullable=name != "signal_date")
    if "available_at" in frame:
        frame["available_at"] = frame.available_at.map(_time)
        if frame.available_at.ge(BOUNDARY).any():
            raise ValueError("LABEL_AVAILABILITY_PRE2026_REQUIRED")
        if any((t.tz_convert(NY).hour, t.tz_convert(NY).minute, t.tz_convert(NY).second, t.microsecond, t.nanosecond) != (16, 0, 0, 0, 0) for t in frame.available_at):
            raise ValueError("ASSUMED_LABEL_AVAILABILITY_NY1600_REQUIRED")
    if frame.duplicated(["ticker", "signal_date"]).any():
        raise ValueError("DUPLICATE_STORED_LABEL_ORIGIN")
    positions = {d: i for i, d in enumerate(days)}
    records, source_indices, supported = [], [], []
    for index, row in frame.iterrows():
        asset = row.ticker
        segment = segments.get(asset)
        if (asset not in assets or segment is None or not _same(row.security_id, uids[asset])
                or ("identity_epoch" in frame and not _same(row.identity_epoch, epochs[asset]))):
            continue
        oi = positions.get(row.signal_date, -1)
        if not segment[0] <= oi <= segment[1]:
            continue
        clocks_missing = any(pd.isna(row[c]) for c in ("execution_date", "label_end_date", "label_mature_date"))
        if clocks_missing:
            if _true(row.label_available):
                raise ValueError("LABEL_AVAILABLE_WITHOUT_ENDPOINT_OR_MATURITY")
            continue
        ei, xi = positions.get(row.execution_date, -1), positions.get(row.label_end_date, -1)
        if ei != oi + 1 or xi != ei + 5 or row.label_mature_date < row.label_end_date:
            raise ValueError("STORED_H5_CLOCK_OR_MATURITY_MISMATCH")
        if xi > segment[1]:
            continue  # Endpoint crosses the caller-observed current UID segment.
        origin, entry, endpoint = _clock(row.signal_date), _clock(row.execution_date, opening=True), _clock(row.label_end_date, opening=True)
        mature = _clock(row.label_mature_date)
        available = row.available_at if "available_at" in frame else mature
        if available < mature:
            raise ValueError("LABEL_AVAILABILITY_PRECEDES_MATURITY")
        if not max(origin, entry, endpoint, mature, available) < cutoff:
            continue
        okay = (_true(row.label_available) and _false(row.label_unsupported_common_event)
                and _true(row.endpoint_pair_available) and isinstance(row.label_coordinate, str)
                and row.label_coordinate == STORED_LABEL_COORDINATE)
        if _true(row.label_available) and (not isinstance(row.label_coordinate, str) or row.label_coordinate != STORED_LABEL_COORDINATE):
            raise ValueError("WRONG_STORED_LABEL_COORDINATE")
        records.append(dict(asset=asset, origin_at=origin, entry_at=entry, endpoint_at=endpoint,
                            matured_at=mature, available_at=available, horizon=5,
                            uid=uids[asset], identity_epoch=epoch, source_identity=receipt.source_identity,
                            return_value=np.nan))
        source_indices.append(index)
        supported.append(bool(okay))
    result = pd.DataFrame(records, columns=OBSERVATION_COLUMNS)
    selected = [source_indices[i] for i, okay in enumerate(supported) if okay]
    if selected:
        values = pd.to_numeric(labels["y_open5"].iloc[selected], errors="raise").to_numpy(float)
        if np.isinf(values).any():
            raise ValueError("INFINITE_STORED_LABEL")
        result.loc[np.flatnonzero(supported), "return_value"] = values
    return result


def _qqq_observations(opens, days, closes, receipt, primary, cutoff):
    if not isinstance(receipt, SourceReceipt):
        raise ValueError("TYPED_QQQ_SOURCE_RECEIPT_REQUIRED")
    receipt.validate(cutoff, role="benchmark", primary=primary)
    if receipt.return_coordinate != BENCHMARK_PROXY_COORDINATE or receipt.benchmark_proxy_allowed is not True:
        raise ValueError("EXPLICIT_QFQ_OPEN_PROXY_CONTRACT_REQUIRED")
    _require(opens, ("ticker", "trade_date"), "QQQ")
    dates = _dates(opens.trade_date, "QQQ")
    if "open" not in opens.columns:
        raise ValueError("QQQ_OPEN_REQUIRED_NO_CLOSE_SUBSTITUTION")
    mask = opens.ticker.eq("QQQ") & dates.map(_clock).lt(cutoff)
    keys = dates[mask]
    if keys.duplicated().any():
        raise ValueError("AMBIGUOUS_QQQ_OPEN_SESSION")
    if not keys.isin(days).all():
        raise ValueError("QQQ_NONCALENDAR_SESSION")
    values = pd.to_numeric(opens.loc[mask, "open"], errors="raise").to_numpy(float)
    if np.isinf(values).any() or np.any(values[np.isfinite(values)] <= 0):
        raise ValueError("QQQ_POSITIVE_FINITE_OPEN_REQUIRED")
    quotes = pd.Series(values, index=pd.DatetimeIndex(keys)).reindex(days)
    records = []
    for oi in range(len(days)):
        for h in (1, 5):
            ei, xi = oi + 1, oi + 1 + h
            if xi >= len(days) or closes[xi] >= cutoff:
                continue
            entry, endpoint = quotes.iloc[ei], quotes.iloc[xi]
            value = endpoint / entry - 1 if np.isfinite(entry) and np.isfinite(endpoint) else np.nan
            records.append(dict(asset="QQQ", origin_at=closes[oi], entry_at=_clock(days[ei], opening=True),
                endpoint_at=_clock(days[xi], opening=True), matured_at=closes[xi], available_at=closes[xi],
                horizon=h, uid="QQQ", identity_epoch=receipt.identity_epoch,
                source_identity=receipt.source_identity, return_value=value))
    return pd.DataFrame(records, columns=OBSERVATION_COLUMNS)


def _industry(mapping, receipt, primary, assets, uids, epoch, cutoff):
    if not isinstance(receipt, SourceReceipt):
        raise ValueError("TYPED_FF48_SOURCE_RECEIPT_REQUIRED")
    receipt.validate(cutoff, role="industry", primary=primary)
    columns = ("asset", "uid", "group", "available_at", "effective_at")
    _require(mapping, columns, "FF48")
    clocks = mapping.loc[:, ["asset", "uid", "available_at", "effective_at"]].copy()
    for c in ("available_at", "effective_at"):
        clocks[c] = clocks[c].map(_time)
        if clocks[c].ge(BOUNDARY).any():
            raise ValueError("FF48_PRE2026_REQUIRED")
    mask = clocks.available_at.le(cutoff) & clocks.effective_at.le(cutoff) & clocks.asset.isin(assets)
    legal = clocks.loc[mask].sort_values(["asset", "effective_at", "available_at"])
    if legal.duplicated(["asset", "effective_at", "available_at"]).any():
        raise ValueError("AMBIGUOUS_ASOF_FF48")
    selected = legal.groupby("asset", sort=False).tail(1)
    selected = selected.loc[[uid == uids[asset] for asset, uid in zip(selected.asset, selected.uid)]]
    result = selected.copy()
    result["group"] = pd.to_numeric(mapping.loc[selected.index, "group"], errors="coerce")
    result = result.loc[result.group.between(1, 48) & result.group.mod(1).eq(0)]
    result["group"] = result.group.astype(int)
    result["identity_epoch"] = epoch
    result["source_identity"] = receipt.source_identity
    return result.loc[:, ["asset", "group", "available_at", "effective_at", "identity_epoch", "source_identity"]]


def assemble_risk_inputs(stored_labels, calendar_sessions, *, assets, asset_uids, identity_epoch,
                         source_receipt, cutoff, identity_history, asset_epochs=None, qqq_opens=None, qqq_receipt=None,
                         industry_mapping=None, industry_receipt=None):
    """Package one caller-authorized snapshot. Does not fit or qualify an account.

    Identity history is independent membership metadata: ticker/signal_date/
    security_id/available_at. Optional history/label identity_epoch is honored;
    asset_epochs binds distinct per-asset observed epochs while the RiskInput
    uses the caller global epoch. Labels use the native stored H5 columns. FF48 is
    caller-projected asset/uid/group/available_at/effective_at metadata. No source
    alias or current ticker mapping is inferred. Missing/unsupported H5 values
    remain NaN; requested assets and inference support never depend on labels.
    """
    if not isinstance(source_receipt, SourceReceipt):
        raise ValueError("TYPED_PRIMARY_SOURCE_RECEIPT_REQUIRED")
    cutoff = _time(cutoff)
    if cutoff >= BOUNDARY:
        raise ValueError("PRE2026_CUTOFF_REQUIRED")
    source_receipt.validate(cutoff)
    assets = tuple(assets)
    if not assets or len(set(assets)) != len(assets) or set(asset_uids) != set(assets):
        raise ValueError("EXACT_REQUESTED_ASSETS_AND_UIDS_REQUIRED")
    if len(set(asset_uids.values())) != len(assets):
        raise ValueError("UNIQUE_CURRENT_UID_REQUIRED")
    if identity_epoch != source_receipt.identity_epoch or not all(isinstance(v, str) and v for v in asset_uids.values()):
        raise ValueError("EXPLICIT_UID_EPOCH_BINDING_REQUIRED")
    epochs = dict(asset_epochs) if asset_epochs is not None else {a: identity_epoch for a in assets}
    if set(epochs) != set(assets) or not all(isinstance(e, str) and e for e in epochs.values()):
        raise ValueError("EXPLICIT_CURRENT_ASSET_EPOCHS_REQUIRED")
    if asset_epochs is not None and "identity_epoch" not in identity_history.columns:
        raise ValueError("OBSERVED_EPOCH_METADATA_REQUIRED")
    days, closes = _calendar(calendar_sessions)
    segments = _segments(identity_history, days, closes, assets, asset_uids, epochs, cutoff)
    observations = _stock_observations(stored_labels, days, assets, asset_uids, epochs, identity_epoch,
                                       source_receipt, cutoff, segments)
    reasons = {m: [] for m in ("R0", "RD", "RM", "RB", "RH", "RT", "RR", "RU", "RE")}
    reasons["RM"].append("BLOCK_UNBOUND_STOCK_HORIZONS_3_10_20")
    if any(segments[a] is None for a in assets):
        for method in reasons:
            reasons[method].append("BLOCK_REQUESTED_ASSET_IDENTITY_SUPPORT")
    qframe, groups = None, None
    qreason, ireason = "BLOCK_QQQ_OPEN_SOURCE_UNBOUND", "BLOCK_ASOF_FF48_SOURCE_UNBOUND"
    if qqq_opens is not None and qqq_receipt is not None:
        try:
            qframe = _qqq_observations(qqq_opens, days, closes, qqq_receipt, source_receipt, cutoff)
            qreason = None
        except (ValueError, TypeError, KeyError) as error:
            qreason = str(error)
    if industry_mapping is not None and industry_receipt is not None:
        try:
            groups = _industry(industry_mapping, industry_receipt, source_receipt, assets, asset_uids, identity_epoch, cutoff)
            ireason = None if set(groups.asset) == set(assets) else "BLOCK_MISSING_OR_UID_UNBOUND_FF48"
        except (ValueError, TypeError, KeyError) as error:
            ireason = str(error)
    if qreason:
        for method in ("RB", "RH", "RR", "RE"):
            reasons[method].append(qreason)
    if ireason:
        reasons["RH"].append(ireason)
    result = RiskInput(assets, closes, observations, source_receipt, dict(asset_uids), identity_epoch,
                       qqq_observations=qframe, qqq_receipt=qqq_receipt,
                       industry_mapping=groups, industry_receipt=industry_receipt)
    declaration = dict(schema="B_FROZEN_HISTORY_TYPED_RISK_INPUTS_R3", cutoff=cutoff.isoformat(),
        requested_assets=list(assets), current_asset_epochs=epochs, stock_horizons=[5], missing_stock_horizons=[3, 10, 20],
        strict_PIT_promotion_eligible=False, source_policy="FROZEN_HISTORY_MECHANISM_RESEARCH_ONLY",
        historical_publication_and_revision_vintage="UNKNOWN", stored_label_coordinate=STORED_LABEL_COORDINATE,
        primary_return_coordinate=COORDINATE, observation_time_assumed=True,
        observation_clock="NY16:00; entry/endpoint NY09:30; all return clocks strictly before cutoff",
        numeric_fit_executed=False, account_qualification_executed=False,
        inference_support={a: segments[a] is not None for a in assets},
        inference_support_basis="CURRENT_UID_CONTIGUOUS_MEMBERSHIP_METADATA_ONLY_NOT_LABEL_COMPLETENESS",
        observed_current_segments={a: None if segments[a] is None else
            dict(uid=asset_uids[a], start_date=days[segments[a][0]].date().isoformat(),
                 end_date=days[segments[a][1]].date().isoformat()) for a in assets},
        unsupported_or_missing_label_policy="NaN; no zero and no inference-pool removal",
        qqq_proxy_formula="QFQ Open(s_i+h+1)/QFQ Open(s_i+1)-1; h=1,5; never Close replacement",
        qqq_return_coordinate=BENCHMARK_PROXY_COORDINATE, qqq_binding_reason=qreason,
        ff48_binding_reason=ireason, method_block_reasons=reasons,
        readiness="METADATA_ASSEMBLED_ONLY; covariance support/252 mature origins not yet qualified")
    return RiskInputAssembly(result, declaration)




def correct_rr_qqq_source_range(inputs: RiskInput, *, cutoff,
                                open_start_date, open_stop_date_exclusive) -> RiskInput:
    """Bound RR's existing QQQ observations to a declared 360-Open projection.

    This opt-in correction never estimates a state or reads return values. The
    caller must bind its separate correction receipt; original typed receipts,
    stock inputs and the ordinary assembler retain their original semantics.
    Missing Open endpoints inside the declared source range remain missing slots.
    """
    if not isinstance(inputs, RiskInput) or inputs.qqq_receipt is None:
        raise ValueError("RR_QQQ_SOURCE_RANGE_INPUT_REQUIRED")
    cutoff = _time(cutoff)
    if cutoff >= BOUNDARY:
        raise ValueError("RR_QQQ_SOURCE_RANGE_PRE2026_REQUIRED")
    inputs.source_receipt.validate(cutoff)
    inputs.qqq_receipt.validate(cutoff, role="benchmark", primary=inputs.source_receipt)
    if (inputs.qqq_receipt.return_coordinate != BENCHMARK_PROXY_COORDINATE
            or inputs.qqq_receipt.benchmark_proxy_allowed is not True):
        raise ValueError("RR_QQQ_EXPLICIT_OPEN_PROXY_REQUIRED")
    days, closes = _calendar(inputs.sessions)
    if cutoff not in closes:
        raise ValueError("RR_QQQ_LEGAL_PRIOR_CLOSE_CUTOFF_REQUIRED")
    dates = _dates(pd.Series([open_start_date, open_stop_date_exclusive]), "RR_QQQ_SOURCE_RANGE")
    start, stop = dates.iloc[0], dates.iloc[1]
    stop_position = int(closes.get_loc(cutoff))
    if stop_position < 360:
        raise ValueError("RR_QQQ_SOURCE_RANGE_REQUIRES_360_PRIOR_SESSIONS")
    start_position = stop_position - 360
    if start != days[start_position] or stop != days[stop_position]:
        raise ValueError("RR_QQQ_SOURCE_RANGE_DIFFERS_FROM_DECLARED_PRIOR360_PROJECTION")
    if start_position == 0:
        raise ValueError("RR_QQQ_SOURCE_RANGE_PRIOR_SIGNAL_REQUIRED")
    frame = inputs.qqq_observations
    _require(frame, OBSERVATION_COLUMNS, "RR_QQQ_OBSERVATIONS")
    if not frame.columns.is_unique:
        raise ValueError("RR_QQQ_OBSERVATIONS_UNIQUE_COLUMNS_REQUIRED")
    metadata = frame.loc[:, list(META)].copy()
    for field in ("origin_at", "entry_at", "endpoint_at", "matured_at", "available_at"):
        metadata[field] = metadata[field].map(_time)
        if metadata[field].ge(cutoff).any() or metadata[field].ge(BOUNDARY).any():
            raise ValueError("RR_QQQ_OBSERVATION_CLOCK_NOT_STRICTLY_PRIOR")
    for field, expected in (("asset", "QQQ"), ("uid", "QQQ"),
                            ("identity_epoch", inputs.qqq_receipt.identity_epoch),
                            ("source_identity", inputs.qqq_receipt.source_identity)):
        if not metadata[field].map(lambda value: _same(value, expected)).all():
            raise ValueError("RR_QQQ_OBSERVATION_IDENTITY_OR_SOURCE_MISMATCH")
    if metadata.duplicated(["asset", "origin_at", "horizon"]).any():
        raise ValueError("RR_QQQ_DUPLICATE_OBSERVATION_SLOT")
    positions = {value: i for i, value in enumerate(closes)}
    for row in metadata.itertuples(index=False):
        h = row.horizon
        if isinstance(h, (bool, np.bool_)) or not isinstance(h, (int, np.integer)) or h not in (1, 5):
            raise ValueError("RR_QQQ_H1_H5_PROXY_HORIZONS_REQUIRED")
        oi = positions.get(row.origin_at, -1)
        ei, xi = oi + 1, oi + 1 + int(h)
        if (oi < 0 or xi >= len(days) or row.entry_at != _clock(days[ei], opening=True)
                or row.endpoint_at != _clock(days[xi], opening=True)
                or row.matured_at != closes[xi] or row.available_at != closes[xi]):
            raise ValueError("RR_QQQ_OBSERVATION_CLOCK_MISMATCH")
    first_open, stop_open = _clock(start, opening=True), _clock(stop, opening=True)
    mask = metadata.entry_at.ge(first_open) & metadata.endpoint_at.lt(stop_open)
    kept = metadata.loc[mask]
    expected_slots = {(closes[i], h) for h in (1, 5)
                      for i in range(start_position - 1, stop_position - h - 1)}
    actual_slots = set(zip(kept.origin_at, kept.horizon))
    if len(kept) != len(expected_slots) or actual_slots != expected_slots:
        raise ValueError("RR_QQQ_SOURCE_RANGE_OBSERVATION_SLOTS_MISSING")
    bounded = frame.loc[mask].copy(deep=True)
    bounded.attrs["rr_qqq_source_range"] = dict(
        open_start_date=start.date().isoformat(), open_stop_date_exclusive=stop.date().isoformat(),
        projected_open_sessions=360, h1_observation_slots=359, h5_observation_slots=355,
        source_policy="CALLER_DECLARED_EXISTING_OPEN_PROJECTION_METADATA_ONLY",
        missing_slots="Preserved; no dropna, price fill or session compression",
        cutoff=cutoff.isoformat())
    return replace(inputs, qqq_observations=bounded)


__all__ = ["RiskInputAssembly", "assemble_risk_inputs", "STORED_LABEL_COORDINATE",
           "correct_rr_qqq_source_range"]
