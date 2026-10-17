"""R5 zero-value event discovery over the existing pre2026 projected reader.

Current decision identity and prior mature history have separate clocks. No fit,
account, source promotion, numeric market field or zero-history observation is
made. The old current_pool predicate/UID checks are reused; a streaming identity
suffix is proven against the original helper. Normal label append is not an event.
"""
from __future__ import annotations
import argparse
from collections import Counter
from pathlib import Path
import json
import numpy as np
import pandas as pd
from scripts.common.storage_paths import resolve, assert_safe_output_path
from scripts.research.a2.evaluation import joint_frozen_history_risk_r3 as old
from scripts.research.a2.data.shared_risk_inputs_r3 import _calendar, _clock, STORED_LABEL_COORDINATE
from scripts.research.a2.risk.shared_risk_budget_r2 import content_hash

ID = "V24_B_DYNAMIC_FULLPOOL_RISK_AND_IDENTITY_R5"
OUTPUT = "support/EVENT_RISK_SUPPORT_R5.json"
SCOPE_SHA = "fd372840c695563f24b8318b14497c636995fbc71b9fde1cc932fc2efa7b4c80"
FF_META = ("decision_date", "canonical_security_id", "ticker_at_date", "sic_available_at", "ff48_code", "identity_status", "taxonomy_status", "sic_source_sha256", "source_fingerprints")
CLASS_META = ("effective_start", "effective_end", "ticker", "security_id", "security_id_type", "cusip", "title_of_class", "moomoo_transport_code", "mapping_status")


def known(value):
    return isinstance(value, str) and bool(value.strip()) and value.strip().upper() not in {"UNKNOWN", "UNBOUND", "NONE", "NULL", "?"}


def pool_identity(pool):
    return {k: pool[k] for k in ("assets", "asset_uids", "asset_epochs", "segment_starts", "blocked_assets")}


class MetadataPoolCursor:
    """Reuse the old current-day predicate; exact contiguous UID suffix only."""
    def __init__(self, days):
        self.days = pd.DatetimeIndex(days)
        self.positions = {d: i for i, d in enumerate(self.days)}
        self.suffix = {}
        self.last_position = None

    def step(self, day, today, raw):
        day = pd.Timestamp(day)
        i = self.positions[day]
        if self.last_position is not None and i != self.last_position + 1:
            raise ValueError("ALL_COMMON_SESSIONS_MUST_BE_PROCESSED")
        # Same predicate/all-current-row UID semantics, without per-asset
        # pandas history materialisation on every session.
        single = today.loc[~today.duplicated("ticker", keep=False), ["ticker", "security_id"]]
        updated = {}
        for asset, uid in single.itertuples(index=False, name=None):
            if isinstance(uid, str) and uid:
                previous = self.suffix.get(asset)
                updated[asset] = (uid, previous[1] if previous is not None and previous[0] == uid else day)
        self.suffix, self.last_position = updated, i
        accepted = today.feature_available.eq(True) & today.all_features_finite.eq(True) & today.feature_source.isin(old.FEATURE_TAGS)
        assets = tuple(sorted(set(today.loc[accepted, "ticker"]).intersection(set(raw.ticker))))
        uids, epochs, starts, blocked = {}, {}, {}, {}
        for asset in assets:
            item = updated.get(asset)
            if item is None:
                blocked[asset] = "AMBIGUOUS_OR_MISSING_CURRENT_UID"
                uids[asset], epochs[asset], starts[asset] = None, None, None
            else:
                uid, start = item
                uids[asset], starts[asset] = uid, start.date().isoformat()
                epochs[asset] = "OBSERVED_CONTIGUOUS_UID:" + content_hash(dict(asset=asset, uid=uid, start=starts[asset]))
        repeated = {uid for uid, count in Counter(u for u in uids.values() if u is not None).items() if count > 1}
        for asset in assets:
            if uids[asset] in repeated: blocked[asset] = "NONUNIQUE_CURRENT_UID"
        return dict(assets=assets, asset_uids=uids, asset_epochs=epochs, segment_starts=starts, blocked_assets=blocked, history=None)


def date_positions(series, days, *, nullable=False):
    dates = pd.to_datetime(series, errors="raise")
    if isinstance(dates.dtype, pd.DatetimeTZDtype):
        raise ValueError("SOURCE_METADATA_DATE_ONLY_REQUIRED")
    valid = dates.notna()
    if (not nullable and not valid.all()) or (dates[valid] != dates[valid].dt.normalize()).any() or dates[valid].ge(old.BOUNDARY).any():
        raise ValueError("PRE2026_DATE_ONLY_METADATA_REQUIRED")
    positions = days.get_indexer(dates)
    if np.any(valid.to_numpy() & (positions < 0)):
        raise ValueError("SOURCE_METADATA_NONCALENDAR_DATE")
    return positions


class HistoryMetadataIndex:
    """Metadata only. No y_open5 column may enter this object."""
    def __init__(self, labels, base_uids, days):
        if old.FORBIDDEN.intersection(labels.columns) or old.FORBIDDEN.intersection(base_uids.columns):
            raise ValueError("NUMERIC_OR_SCORE_METADATA_INPUT_FORBIDDEN")
        self.days = pd.DatetimeIndex(days)
        keys = ["ticker", "signal_date"]
        self.duplicate_base = set(map(tuple, base_uids.loc[base_uids.duplicated(keys, keep=False), keys].itertuples(index=False, name=None)))
        joined = labels.merge(base_uids.drop_duplicates(keys, keep="first"), on=keys, how="left", validate="many_to_one")
        self.records = {}
        for asset, frame in joined.groupby("ticker", sort=False):
            origin = date_positions(frame.signal_date, self.days)
            entry = date_positions(frame.execution_date, self.days, nullable=True)
            end = date_positions(frame.label_end_date, self.days, nullable=True)
            mature = date_positions(frame.label_mature_date, self.days, nullable=True)
            endpoint_valid = (entry == origin + 1) & (end == entry + 5) & (mature >= end) & (entry >= 0) & (end >= 0) & (mature >= 0)
            flags = frame.label_available.eq(True).to_numpy() & frame.endpoint_pair_available.eq(True).to_numpy() & frame.label_unsupported_common_event.eq(False).to_numpy()
            coordinate = frame.label_coordinate.eq(STORED_LABEL_COORDINATE).to_numpy()
            duplicated = frame.duplicated("signal_date", keep=False).to_numpy() | np.asarray([(asset, d) in self.duplicate_base for d in frame.signal_date])
            self.records[asset] = dict(origin=origin, entry=entry, end=end, mature=mature, uid=frame.security_id.to_numpy(), endpoint_valid=endpoint_valid, qualified=flags & coordinate, coordinate_bad=frame.label_available.eq(True).to_numpy() & ~coordinate, endpoint_bad=frame.label_available.eq(True).to_numpy() & ~endpoint_valid, duplicate=duplicated)

    def qualify(self, pool, cutoff_index):
        eligible = {}
        blockers = {}
        origins = set()
        for asset in pool["assets"]:
            row = self.records.get(asset)
            if row is None or pool["segment_starts"][asset] is None:
                eligible[asset] = None
                continue
            start = self.days.get_loc(pd.Timestamp(pool["segment_starts"][asset]))
            identity = (row["uid"] == pool["asset_uids"][asset]) & (row["origin"] >= start) & (row["origin"] >= max(0, cutoff_index - 306)) & (row["origin"] < cutoff_index)
            legal = identity & row["endpoint_valid"] & (row["entry"] < cutoff_index) & (row["end"] < cutoff_index) & (row["mature"] < cutoff_index)
            if np.any(identity & row["endpoint_bad"]):
                blockers[asset] = "DECLARED_AVAILABLE_LABEL_ENDPOINT_METADATA_INVALID"
            if np.any(identity & row["duplicate"]):
                blockers[asset] = "AMBIGUOUS_REQUIRED_SOURCE_LABEL_UID_KEYS"
            if np.any(identity & row["coordinate_bad"] & (row["mature"] < cutoff_index)):
                blockers[asset] = "WRONG_REQUIRED_STORED_LABEL_COORDINATE"
            eligible[asset] = (row["origin"][legal], row["qualified"][legal])
            origins.update(row["origin"][legal].tolist())
        window = sorted(origins)[-252:]
        window_set = set(window)
        counts = {asset: (0 if rows is None else int(np.sum(np.asarray([o in window_set for o in rows[0]], dtype=bool) & rows[1]))) for asset, rows in eligible.items()}
        return dict(parent_origin_count=len(window), parent_origins=[self.days[i].date().isoformat() for i in window], nominal_n=counts, short0=[a for a, n in counts.items() if n == 0], short_lt10=[a for a, n in counts.items() if n < 10], short_lt30=[a for a, n in counts.items() if n < 30], metadata_donors_ge60=[a for a, n in counts.items() if n >= 60], source_metadata_blockers=blockers, original_min30_unchanged=True, original_shr_min10_unchanged=True, numeric_finiteness="UNKNOWN_NOT_READ", prior_predictive_activation="REQUIRES_EXPLICIT_R5_SCIENTIFIC_FREEZE", observations_fabricated=0)


def ff48_lookup_reference(frame, pool, cutoff):
    rows = frame.loc[(frame._decision <= cutoff.tz_convert("America/New_York").tz_localize(None).normalize()) & (frame._available <= cutoff)]
    indexed = {(a, u): values for (a, u), values in rows.groupby(["ticker_at_date", "canonical_security_id"], sort=False)}
    result = {}
    for asset in pool["assets"]:
        exact = indexed.get((asset, pool["asset_uids"][asset]))
        if exact is None or exact.empty:
            result[asset] = None
            continue
        latest = exact.loc[exact._decision.eq(exact._decision.max())]
        if len(latest) != 1:
            result[asset] = None
            continue
        row = latest.iloc[0]
        g = row.ff48_code
        good = row.identity_status == "AUTHORITATIVE" and row.taxonomy_status == "STRICT_PIT_SIC_FF12_FF48_MAPPED" and pd.notna(g) and float(g).is_integer() and 1 <= int(g) <= 48 and known(row.sic_source_sha256) and len(row.sic_source_sha256) == 64 and known(row.source_fingerprints)
        result[asset] = dict(group=int(g), sic_source_sha256=row.sic_source_sha256, available_at=row._available.isoformat()) if good else None
    return result


def coordinate_lookup_reference(intervals, pool, day, raw):
    rows = intervals.loc[intervals._start.le(day) & intervals._end.ge(day)]
    indexed = {(a, u): part for (a, u), part in rows.groupby(["ticker", "security_id"], sort=False)}
    codes = {a: list(part.code.dropna().unique()) for a, part in raw.groupby("ticker", sort=False)}
    result = {}
    for asset in pool["assets"]:
        part = indexed.get((asset, pool["asset_uids"][asset]))
        if part is not None:
            # Identical class declarations from several manager/quarter rows are one coordinate.
            part = part.loc[:, ["security_id_type", "cusip", "title_of_class", "moomoo_transport_code", "mapping_status"]].drop_duplicates()
        bound = part is not None and len(part) == 1 and known(part.iloc[0].title_of_class)
        result[asset] = dict(raw_transport_codes=codes.get(asset, []), security_class_declaration=(part.iloc[0].title_of_class if bound else None), security_id_type=(part.iloc[0].security_id_type if bound else None), cusip=(part.iloc[0].cusip if bound else None), mapping_status=(part.iloc[0].mapping_status if bound else None), class_coordinate_status="EXACT_FROZEN_INTERVAL_METADATA_DECLARATION" if bound else "CLASS_COORDINATE_UNRESOLVED", strict_historical_authority=False)
    return result


class FF48MetadataIndex:
    """As-of indexing of the unchanged original FF48 qualification predicate."""
    def __init__(self, frame):
        self.groups = {(a, u): rows.sort_values("_decision").reset_index(drop=True) for (a, u), rows in frame.groupby(["ticker_at_date", "canonical_security_id"], sort=False)}
        self.axes = {key: (rows._decision.to_numpy(), rows._available.astype("datetime64[ns, UTC]").astype("int64").to_numpy()) for key, rows in self.groups.items()}

    def lookup(self, pool, cutoff):
        day = cutoff.tz_convert("America/New_York").tz_localize(None).normalize().to_datetime64()
        result = {}
        for asset in pool["assets"]:
            key = (asset, pool["asset_uids"][asset]); rows = self.groups.get(key)
            if rows is None:
                result[asset] = None
                continue
            dates, available = self.axes[key]
            legal = np.flatnonzero((dates <= day) & (available <= cutoff.value) & (available != np.iinfo(np.int64).min))
            if not len(legal):
                result[asset] = None
                continue
            latest = legal[dates[legal] == dates[legal[-1]]]
            if len(latest) != 1:
                result[asset] = None
                continue
            row = rows.iloc[int(latest[0])]; g = row.ff48_code
            good = row.identity_status == "AUTHORITATIVE" and row.taxonomy_status == "STRICT_PIT_SIC_FF12_FF48_MAPPED" and pd.notna(g) and float(g).is_integer() and 1 <= int(g) <= 48 and known(row.sic_source_sha256) and len(row.sic_source_sha256) == 64 and known(row.source_fingerprints)
            result[asset] = dict(group=int(g), sic_source_sha256=row.sic_source_sha256, available_at=row._available.isoformat()) if good else None
        return result


class CoordinateMetadataIndex:
    def __init__(self, intervals):
        self.groups = {(a, u): part for (a, u), part in intervals.groupby(["ticker", "security_id"], sort=False)}
        fields = ["security_id_type", "cusip", "title_of_class", "moomoo_transport_code", "mapping_status"]
        self.axes = {key: (rows._start.to_numpy(), rows._end.to_numpy(), [tuple(row) for row in rows.loc[:, fields].itertuples(index=False, name=None)]) for key, rows in self.groups.items()}

    def lookup(self, pool, day, raw):
        codes = {}
        for asset, code in raw.loc[:, ["ticker", "code"]].itertuples(index=False, name=None):
            if pd.notna(code) and code not in codes.setdefault(asset, []): codes[asset].append(code)
        result = {}; d = pd.Timestamp(day).to_datetime64()
        for asset in pool["assets"]:
            axis = self.axes.get((asset, pool["asset_uids"][asset])); declarations = set()
            if axis is not None:
                starts, ends, records = axis
                declarations = {records[int(i)] for i in np.flatnonzero((starts <= d) & (ends >= d))}
            bound = len(declarations) == 1 and known(next(iter(declarations))[2])
            record = next(iter(declarations)) if bound else [None] * 5
            result[asset] = dict(raw_transport_codes=codes.get(asset, []), security_class_declaration=record[2], security_id_type=record[0], cusip=record[1], mapping_status=record[4], class_coordinate_status="EXACT_FROZEN_INTERVAL_METADATA_DECLARATION" if bound else "CLASS_COORDINATE_UNRESOLVED", strict_historical_authority=False)
        return result

def structural_signature(pool, *, source_identity, coordinates, ff48, feature_tags):
    """No daily cutoff, counts, new-label keys, prices or outcomes enter trigger."""
    return dict(ordered_assets=list(pool["assets"]), asset_uids=pool["asset_uids"], asset_epochs=pool["asset_epochs"], blocked_assets=pool["blocked_assets"], source_identity=source_identity, security_coordinates=coordinates, ff48_qualified_source_support=ff48, feature_source_support=feature_tags)


def reasons(previous, current):
    if previous is None:
        return ["BOOTSTRAP_CURRENT_DECISION_POOL"]
    names = {"ordered_assets": "ORDERED_ASSET_DOMAIN_CHANGE", "asset_uids": "CURRENT_UID_CHANGE", "asset_epochs": "OBSERVED_IDENTITY_EPOCH_CHANGE", "blocked_assets": "CURRENT_IDENTITY_QUALIFICATION_CHANGE", "source_identity": "SOURCE_SEMANTIC_IDENTITY_CHANGE", "security_coordinates": "SECURITY_COORDINATE_CHANGE", "ff48_qualified_source_support": "FF48_QUALIFIED_SOURCE_SUPPORT_CHANGE", "feature_source_support": "FEATURE_SOURCE_SUPPORT_CHANGE"}
    return [label for key, label in names.items() if previous[key] != current[key]]


def source_binding(run, expected_scope_sha):
    paths = resolve(old.REPO)
    run = Path(run).resolve()
    assert_safe_output_path(run / "support", kind="backtest", paths=paths)
    if run.parent != paths.backtest_root / "V24":
        raise ValueError("MANAGED_R5_V24_RUN_REQUIRED")
    old._pin(run / "HUMAN_SCOPE_EXCERPTS.json", expected_scope_sha, "r5_scope")
    scope = old.read_json(run / "HUMAN_SCOPE_EXCERPTS.json")
    authority = old.read_json(run / "SOURCE_AUTHORITY.json")
    if scope["task_id"] != ID or authority["research_id"] != ID or any(authority[k] is not False for k in ("strict_PIT_promotion_eligible", "quote_qualified", "certified_nav_qualified")):
        raise ValueError("EXPLICIT_R5_UNCERTIFIED_METADATA_SCOPE_REQUIRED")
    if authority["risk_primary_coordinate"] != STORED_LABEL_COORDINATE or authority["EF_access"] is not False or authority["network_provider_fetch"] is not False:
        raise ValueError("EXACT_R5_SOURCE_BOUNDARIES_REQUIRED")
    ref = authority["source_inputs_ref"]
    old._safe_source(ref["path"]); old._pin(ref["path"], ref["sha256"], "r5_inherited_source")
    source = old.read_json(ref["path"])
    return run, scope, authority, source, ref


def discover(run, *, expected_scope_sha=SCOPE_SHA):
    run, scope, authority, source, source_ref = source_binding(run, expected_scope_sha)
    reader = old.ProjectedReader(source, phase="support")
    frames = {}
    frames["calendar"] = reader.read("calendar", ("trade_date",), date_field="trade_date")
    days, _ = _calendar(frames["calendar"].trade_date)
    requested = days[(days >= pd.Timestamp("2023-01-03")) & (days <= pd.Timestamp("2025-12-31"))]
    if len(requested) != 752 or requested[0] != pd.Timestamp("2023-01-03") or requested[-1] != pd.Timestamp("2025-12-31"):
        raise ValueError("EXACT_752_PRE2026_DECISION_SESSIONS_REQUIRED")
    features = reader.read("prediction_features", old.FEATURE_META, date_field="signal_date")
    features["signal_date"] = pd.to_datetime(features.signal_date)
    raw = reader.read("raw_open_close", ("ticker", "trade_date", "code"), date_field="trade_date")
    raw["trade_date"] = pd.to_datetime(raw.trade_date)
    history_start = days[max(0, days.get_loc(requested[0]) - 307)]
    labels = reader.read("extended_shareholder_y5", old.LABEL_META, date_field="signal_date", start=history_start)
    labels["signal_date"] = pd.to_datetime(labels.signal_date)
    base = reader.read("shareholder_y5", ("ticker", "signal_date", "security_id"), date_field="signal_date", start=history_start)
    base["signal_date"] = pd.to_datetime(base.signal_date)
    history = HistoryMetadataIndex(labels, base, days)
    ff = reader.read("ff48_surface", FF_META, date_field="decision_date")
    ff["_decision"] = pd.to_datetime(ff.decision_date)
    ff["_available"] = pd.to_datetime(ff.sic_available_at, utc=True, errors="coerce")
    intervals = reader.read("uid_intervals", CLASS_META, date_field="effective_start")
    intervals["_start"] = pd.to_datetime(intervals.effective_start)
    intervals["_end"] = pd.to_datetime(intervals.effective_end)
    qqq = reader.read("qqq_qfq_years", ("ticker", "trade_date"), date_field="trade_date", start=history_start, stop=pd.Timestamp("2025-12-31"))
    qdays = set(pd.to_datetime(qqq.trade_date))
    ff_index, coordinate_index = FF48MetadataIndex(ff), CoordinateMetadataIndex(intervals)
    feature_days = {d: part for d, part in features.groupby("signal_date", sort=False)}
    raw_days = {d: part for d, part in raw.groupby("trade_date", sort=False)}
    cursor = MetadataPoolCursor(days)
    empty_features, empty_raw = features.iloc[:0], raw.iloc[:0]
    source_identity = dict(source_inputs_sha256=source_ref["sha256"], source_authority_sha256=old.sha(run / "SOURCE_AUTHORITY.json"), risk_coordinate=authority["risk_primary_coordinate"], raw_share_coordinate=authority["raw_fill_coordinate"], benchmark_proxy_coordinate=authority["conditional_benchmark_proxy_coordinate"], historical_quote_authority_status="UNKNOWN")
    events, daily, audits = [], [], []
    previous = None
    local_previous, local_ids = {}, {}
    local_events = {name: [] for name in ("PRIMARY", "QQQ", "FF48")}
    audit_dates = {requested[0], pd.Timestamp("2023-02-22"), pd.Timestamp("2025-12-31")}
    counter = Counter()
    for day in days:
        if day > requested[-1]:
            break
        today, raw_today = feature_days.get(day, empty_features), raw_days.get(day, empty_raw)
        pool = cursor.step(day, today, raw_today)
        if day < requested[0]:
            continue
        i = days.get_loc(day); cutoff = _clock(days[i - 1]); decision = _clock(day)
        coordinates = coordinate_index.lookup(pool, day, raw_today)
        ff48 = ff_index.lookup(pool, cutoff)
        all_tags = {}
        for asset, tag in today.loc[:, ["ticker", "feature_source"]].itertuples(index=False, name=None):
            if pd.notna(tag): all_tags.setdefault(asset, set()).add(tag)
        all_tags = {a: sorted(values) for a, values in all_tags.items()}
        tags = {a: all_tags[a] for a in pool["assets"]}
        signature = structural_signature(pool, source_identity=source_identity, coordinates=coordinates, ff48=ff48, feature_tags=tags)
        primary = {k: v for k, v in signature.items() if k != "ff48_qualified_source_support"}
        qqq_identity = dict(primary=primary, independent_qqq_source_sha256=[p["sha256"] for p in source["sources"]["qqq_qfq_years"]])
        local_signatures = {"PRIMARY": primary, "QQQ": qqq_identity, "FF48": signature}
        for name, local in local_signatures.items():
            local_hash = content_hash(local)
            if local_previous.get(name) != local_hash:
                local_ids[name] = content_hash(dict(dependency=name, decision_asof=decision.isoformat(), structural_sha256=local_hash))
                local_events[name].append(dict(event_index=len(local_events[name]), event_id=local_ids[name], decision_date=day.date().isoformat(), structural_signature_sha256=local_hash))
            local_previous[name] = local_hash
        changes = reasons(previous, signature)
        if changes:
            support = history.qualify(pool, i - 1)
            origins = [days.get_loc(pd.Timestamp(o)) for o in support["parent_origins"]]
            required_q = {days[j + h] for j in origins for h in (1, 6)}
            support["qqq_h5_endpoint_key_support"] = bool(origins and required_q.issubset(qdays))
            support["qqq_missing_endpoint_dates"] = sorted(d.date().isoformat() for d in required_q - qdays)
            unknown = {a: "UNKNOWN_CURRENT_UID" for a in pool["assets"] if not known(pool["asset_uids"][a])}
            unknown.update(pool["blocked_assets"])
            support["current_identity_blockers"] = unknown
            event_id = content_hash(dict(decision_asof=decision.isoformat(), signature=signature))
            events.append(dict(event_index=len(events), event_id=event_id, decision_date=day.date().isoformat(), decision_asof=decision.isoformat(), fit_history_cutoff=cutoff.isoformat(), trigger_reasons=changes, complete_structural_signature=signature, dependency_local_signature_sha256=dict(local_previous), dependency_local_event_ids=dict(local_ids), structural_signature_sha256=content_hash(signature), requested_assets=list(pool["assets"]), asset_uids=pool["asset_uids"], asset_epochs=pool["asset_epochs"], segment_starts=pool["segment_starts"], current_identity_available_at=decision.isoformat(), current_identity_clock_status="EXPLICIT_FROZEN_HISTORY_OBSERVATION_ASSUMPTION", security_coordinates=coordinates, qualified_ff48_support=ff48, history_support=support, qualification="METADATA_DISCOVERY_ONLY_NOT_NUMERIC_OR_PRIOR_ACTIVATION"))
            counter.update(changes)
        daily.append(dict(decision_date=day.date().isoformat(), decision_asof=decision.isoformat(), prospective_history_cutoff=cutoff.isoformat(), support_epoch_event_id=events[-1]["event_id"], dependency_local_event_ids=dict(local_ids), dependency_local_signature_sha256=dict(local_previous), action="NEW_RISK_REFRESH_REQUIRED" if changes else "EXACT_PRIOR_STATE_REUSE_IF_NUMERIC_STATE_QUALIFIED", requested_asset_count=len(pool["assets"]), structural_signature_sha256=content_hash(signature), future_event_date_used=False))
        if day in audit_dates:
            reference = old.current_pool(features.loc[features.signal_date.le(day)], raw_today, days, decision)
            equal = content_hash(pool_identity(pool)) == content_hash(pool_identity(reference))
            audits.append(dict(decision_date=day.date().isoformat(), exact_old_helper_identity_equal=equal))
            if not equal:
                raise ValueError("STREAMING_IDENTITY_EPOCH_NOT_EQUIVALENT_TO_OLD_HELPER")
        previous = signature
        if len(daily) % 50 == 0:
            print(json.dumps(dict(metadata_sessions=len(daily), support_events=len(events), new_fit_units=0, numeric_reads=0)), flush=True)
    result = dict(schema="B_R5_EVENT_RISK_METADATA_SUPPORT_V1", research_id=ID, source_authority_ref=dict(path=str(run / "SOURCE_AUTHORITY.json"), sha256=old.sha(run / "SOURCE_AUTHORITY.json")), source_inputs_ref=source_ref, human_scope_ref=dict(path=str(run / "HUMAN_SCOPE_EXCERPTS.json"), sha256=expected_scope_sha), producer_code_pins=[dict(path=str(Path(p)), sha256=old.sha(p)) for p in (__file__, old.__file__, old.REPO / "scripts/research/a2/data/shared_risk_inputs_r3.py", old.REPO / "scripts/common/storage_paths.py")], decision_session_count=len(daily), structural_event_count=len(events), exact_reuse_session_count=len(daily)-len(events), dependency_local_event_counts={name: len(items) for name, items in local_events.items()}, dependency_local_events=local_events, trigger_reason_counts=dict(counter), events=events, daily_support_chain=daily, streaming_helper_equivalence_audits=audits, reader_projection_audit=reader.audit, temporal_rules=dict(current_pool="CURRENT_DECISION_CLOSE", history="MATURED_AVAILABLE_STRICTLY_BEFORE_PREVIOUS_LEGAL_CLOSE_WITH_CURRENT_UID_EPOCH_ONLY", parent_window="LAST_252_LEGAL_METADATA_ORIGINS_WITH_ORIGINAL_306_ORIGIN_SCAN_BOUND", trigger_excludes=["normal matured label append", "rolling window/cutoff clock", "numeric values", "NAV/return/performance"]), risk_numeric_finiteness="UNKNOWN_NOT_READ", scientific_prior_recipe_frozen=False, strict_PIT_promotion_eligible=False, quote_qualified=False, certified_nav_qualified=False, numeric_reads=0, return_value_reads=0, outcome_reads=0, new_fit_units=0, account_attempts=0, provider_fetches=0, EF_accesses=0, test2026_rows_read=0)
    old.write(run, OUTPUT, result, immutable=True)
    return dict(path=str(run / OUTPUT), sha256=old.sha(run / OUTPUT), decision_sessions=len(daily), structural_events=len(events), dependency_local_event_counts={name: len(items) for name, items in local_events.items()}, reused_sessions=len(daily)-len(events), known_uid_zero_history_event_contexts=sum(len(e["history_support"]["short0"]) for e in events), identity_blocked_event_contexts=sum(len(e["history_support"]["current_identity_blockers"]) for e in events), new_fit_units=0, numeric_reads=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--expected-scope-sha", default=SCOPE_SHA)
    args = parser.parse_args()
    run = Path(args.run)
    lease = run / "work/leases/event_risk_support"
    assert_safe_output_path(lease, kind="backtest", paths=resolve(old.REPO))
    (lease / "work").mkdir(parents=True, exist_ok=True)
    with old.task_writer(lease):
        result = discover(run, expected_scope_sha=args.expected_scope_sha)
    print(json.dumps(result, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()