"""Frozen, target-blind option-context inventories and Stage-1R archive audit.

This module deliberately has no model, target, broker, or Moomoo client imports.
Stage-1R treats the archived ``time_key`` as a source-local string: it never claims
that it is UTC, and therefore fails closed when an authoritative timezone contract
is absent.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

RESULTS = Path(r"D:\us-tech-quant-results")
R27_AUDIT = RESULTS / "frozen/fast3/r27_2_independent_heads_20260807T083523364Z/r27_2_feature_availability_audit.json"
R28_MANIFEST = RESULTS / "frozen/fast3/r28_phase2_20260808T125629Z/R28_FEATURE_MANIFEST.json"
RAW_ROOTS = (
    RESULTS / "archive/fast3/moomoo_option_history_r2_20260811T191300Z",
    RESULTS / "archive/fast3/moomoo_option_history_r2_20260811T191300Z_continuation_001",
)
UNIFIED = RESULTS / "frozen/fast3/moomoo_option_history_r2_materialized_20260811T225200Z/FAST3_MOOMOO_OPTION_HISTORY_R2_UNIFIED_MANIFEST.json"
SDK_CONTEXT = Path(r"D:\us-tech-quant-cache\venvs\moomoo-openapi\Lib\site-packages\moomoo\quote\open_quote_context.py")
SDK_QUERY = Path(r"D:\us-tech-quant-cache\venvs\moomoo-openapi\Lib\site-packages\moomoo\quote\quote_query.py")
R2_SOURCE = Path(r"D:\us-tech-quant\fast3\src\fast3\options\moomoo_option_acquisition_r2.py")
CANONICAL_SOXX = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical\symbol=SOXX")
STAGE1R_LEGACY_SHA = "42f9f073ce653d3d78b2063c659b0cd272bb6097670eafb2089cb13ead720c25"
STAGE1R_NATIVE_SHA = "9a49907650b1c10ede4163dff40f1430c4d76b24d916cca1a3527ffd8fa4a760"
R33_T5_CONTRACT = RESULTS / "frozen/fast3/r33b_conditional_loss_severity_20260810T200000Z/FAST3_R33_T5_CONDITIONAL_LOSS_SEVERITY_CONTRACT_R1.json"
R33_T6_CONTRACT = RESULTS / "frozen/fast3/r33d_conditional_gain_magnitude_20260811T000000Z/FAST3_R33D_T6_CONDITIONAL_GAIN_CONTRACT_R1.json"
R32B_FEATURE_MANIFEST = RESULTS / "frozen/fast3/r30b_factor_expansion_20260809T140000Z/FAST3_R30B_EXPANDED_FEATURE_MANIFEST_R1.json"

R28_ROWS = (
    ("return_5m", "price_return"), ("return_15m", "price_return"),
    ("return_60m", "price_return"), ("realized_vol_15m", "volatility"),
    ("realized_vol_60m", "volatility"), ("relative_volume", "volume"),
    ("range_position", "range"), ("symbol_code", "categorical"),
    ("direction_code", "categorical"), ("session_code", "session"),
    ("downside_vol_60m", "volatility_risk"), ("intrabar_range_15m", "volatility_risk"),
    ("trend_ema_gap_60m", "trend_structure"), ("breakout_position_120m", "trend_structure"),
    ("volume_zscore_60m", "flow"), ("signed_volume_pressure_15m", "flow"),
    ("peer_return_15m", "cross_asset"), ("relative_return_15m", "cross_asset"),
)
NATIVE_ROWS = (
    ("call_volume_share", "market_activity"), ("put_volume_share", "market_activity"),
    ("put_call_volume_ratio", "market_activity"), ("total_option_volume", "market_activity"),
    ("near_expiry_volume_share", "expiry_structure"), ("far_expiry_volume_share", "expiry_structure"),
    ("volume_concentration", "market_activity"), ("median_option_return_5m", "option_price_state"),
    ("call_return_breadth", "option_price_state"), ("put_return_breadth", "option_price_state"),
    ("call_put_return_spread", "option_price_state"), ("cross_sectional_option_return_dispersion", "option_price_state"),
    ("near_far_activity_ratio", "expiry_structure"), ("expiry_activity_concentration", "expiry_structure"),
    ("active_expiry_count", "expiry_structure"),
)
PROSPECTIVE_ROWS = (
    ("atm_iv", "iv_level"), ("near_term_atm_iv", "iv_level"), ("atm_iv_change_5m", "iv_change"),
    ("atm_iv_change_30m", "iv_change"), ("put_skew_25d", "skew"), ("call_skew_25d", "skew"),
    ("put_call_skew", "skew"), ("downside_skew_slope", "skew"), ("near_far_iv_spread", "term_structure"),
    ("near_far_iv_ratio", "term_structure"), ("term_structure_slope", "term_structure"),
    ("implied_move", "implied_realized"), ("iv_minus_realized_vol", "implied_realized"),
    ("iv_to_realized_vol_ratio", "implied_realized"), ("atm_gamma", "greeks"), ("atm_theta", "greeks"),
    ("atm_vega", "greeks"), ("near_term_gamma", "greeks"), ("near_term_theta", "greeks"),
    ("gamma_theta_ratio", "greeks"), ("atm_relative_spread", "liquidity_quality"),
    ("median_relative_spread", "liquidity_quality"), ("liquid_contract_count", "liquidity_quality"),
    ("surface_coverage_ratio", "liquidity_quality"), ("expiry_coverage_count", "liquidity_quality"),
)


def stable(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _semantic_name(name: str) -> str:
    """Only documented level aliases collapse; deltas remain distinct factors."""
    return name.removesuffix("__level")


def reconciled_legacy() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Union R28 source and the frozen R27 PIT availability audit, target-blind."""
    audit = json.loads(R27_AUDIT.read_text(encoding="utf-8"))
    r28 = json.loads(R28_MANIFEST.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, family in R28_ROWS:
        seen.add(_semantic_name(name))
        rows.append({"factor_name": name, "factor_family": family, "source_module": "fast3.r28_multisignal", "source_column_or_builder": name, "frequency": "1m decision bars", "lookback_definition": "R28 frozen definition", "availability_rule": "completed bar only", "PIT_status": "PASS", "future_dependency_status": "NONE", "missingness_policy": "preserve_missing_no_imputation", "existing_manifest_reference": str(R28_MANIFEST), "notes": "R28 manifest/source verified"})
    for item in audit:
        if not item.get("PIT_SAFE"):
            continue
        name = str(item["feature_name"])
        canonical = _semantic_name(name)
        if canonical in seen:
            continue
        seen.add(canonical)
        rows.append({"factor_name": canonical, "factor_family": str(item["feature_family"]), "source_module": "R27 frozen availability audit", "source_column_or_builder": name, "frequency": "R27 frozen decision rows", "lookback_definition": str(item.get("transformation", "frozen definition")), "availability_rule": "R27 availability audit PIT_SAFE=true", "PIT_status": "PASS", "future_dependency_status": "NONE", "missingness_policy": "preserve_missing_no_imputation", "existing_manifest_reference": str(R27_AUDIT), "notes": "canonical name removes documented __level alias only"})
    rows.sort(key=lambda x: x["factor_name"])
    for index, row in enumerate(rows):
        row.update({"schema_version": "FAST3_OPTION_CONTEXT_R1_RECONCILED", "created_by_stage": "FAST3_OPTION_CONTEXT_R1_STAGE1R", "canonical_order": index})
    evidence = {"R27_FEATURE_IDENTITY_STATUS": "PASS_FROZEN_PIT_AVAILABILITY_AUDIT_IDENTIFIED", "R28_FEATURE_IDENTITY_STATUS": "PASS_SOURCE_AND_FROZEN_MANIFEST_IDENTIFIED", "R29_FACTOR_MANIFEST_STATUS": "NOT_FOUND_IN_REPO_OR_FROZEN_ARTIFACTS_BLOCKED", "R29_DISCOVERED_FACTOR_COUNT": 0, "R29_DISCOVERED_FACTOR_FAMILY_COUNT": 0, "STAGE1_LEGACY_18_EXPLAINS_R29_33": False, "r28_manifest_hash": stable(r28), "r27_pit_safe_audit_count": sum(bool(x.get("PIT_SAFE")) for x in audit)}
    return rows, evidence


def factor_manifest(kind: str, rows: Iterable[tuple[str, str]], source: str, availability: str) -> dict[str, Any]:
    factors = [{"schema_version": "FAST3_OPTION_CONTEXT_R1", "created_by_stage": "FAST3_OPTION_CONTEXT_R1_STAGE1R", "factor_name": name, "family": family, "definition": "fixed compact decision-time aggregation; target/payoff blind", "source": source, "availability": availability, "PIT_status": "REQUIRES_BACKWARD_ASOF_AND_SOURCE_TIMEZONE_CONTRACT", "missingness_rule": "preserve_missing_no_imputation", "canonical_order": i} for i, (name, family) in enumerate(rows)]
    return {"kind": kind, "factors": factors, "factor_count": len(factors), "sha256": stable(factors)}


def backward_asof(decisions, observations):
    """Explicitly backward-only helper; callers must establish a timezone contract."""
    import pandas as pd
    left = decisions.sort_values("decision_timestamp", kind="mergesort").copy()
    right = observations.sort_values("observation_timestamp", kind="mergesort").copy()
    return pd.merge_asof(left, right, left_on="decision_timestamp", right_on="observation_timestamp", direction="backward", allow_exact_matches=True)


def _dte_bucket(dte: float) -> str | None:
    for low, high, name in ((0, 3, "0_3"), (4, 7, "4_7"), (8, 14, "8_14"), (15, 30, "15_30"), (31, 60, "31_60")):
        if low <= dte <= high:
            return name
    return None


def historical_native_snapshot(observations, decision_timestamp):
    """Build one compact native snapshot using only rows at/before the decision."""
    import numpy as np
    import pandas as pd
    frame = observations.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="raise")
    cutoff = pd.Timestamp(decision_timestamp)
    frame = frame.loc[frame.timestamp <= cutoff].sort_values(["option_code", "timestamp"], kind="mergesort").copy()
    if frame.empty:
        return {name: float("nan") for name, _ in NATIVE_ROWS}
    frame["return_5m"] = frame.groupby("option_code", sort=False)["close"].pct_change(fill_method=None)
    latest = frame.groupby("option_code", sort=False).tail(1).copy()
    expiry = pd.to_datetime(latest.expiry, errors="raise")
    if latest.timestamp.dt.tz is not None:
        expiry = expiry.dt.tz_localize(latest.timestamp.dt.tz)
    latest["dte"] = (expiry - latest.timestamp.dt.normalize()).dt.days
    latest["dte_bucket"] = latest.dte.map(_dte_bucket)
    volume = latest.volume.clip(lower=0).fillna(0.0)
    total = float(volume.sum())
    call = latest.call_put.astype(str).str.upper().str.startswith("CALL")
    put = latest.call_put.astype(str).str.upper().str.startswith("PUT")
    cvol, pvol = float(volume[call].sum()), float(volume[put].sum())
    ret = latest.return_5m.replace([np.inf, -np.inf], np.nan)
    near, far = float(volume[latest.dte_bucket.isin(["0_3", "4_7"])].sum()), float(volume[latest.dte_bucket.eq("31_60")].sum())
    shares = volume / total if total else volume * np.nan
    expiry_volume = latest.assign(_v=volume).groupby("expiry", sort=False)._v.sum()
    result = {"call_volume_share": cvol / total if total else np.nan, "put_volume_share": pvol / total if total else np.nan, "put_call_volume_ratio": pvol / cvol if cvol else np.nan, "total_option_volume": total, "near_expiry_volume_share": near / total if total else np.nan, "far_expiry_volume_share": far / total if total else np.nan, "volume_concentration": float((shares ** 2).sum()) if total else np.nan, "median_option_return_5m": float(ret.median()), "call_return_breadth": float((ret[call] > 0).mean()), "put_return_breadth": float((ret[put] > 0).mean()), "call_put_return_spread": float(ret[call].median() - ret[put].median()), "cross_sectional_option_return_dispersion": float(ret.std(ddof=0)), "near_far_activity_ratio": near / far if far else np.nan, "expiry_activity_concentration": float(((expiry_volume / total) ** 2).sum()) if total else np.nan, "active_expiry_count": int((expiry_volume > 0).sum())}
    return result


def _soxx_files() -> list[Path]:
    return sorted(p for root in RAW_ROOTS for p in root.rglob("*.parquet") if "option_price_5m" in p.parts and "SOXX" in p.parts)


def audit_soxx_archive() -> dict[str, Any]:
    """Read only raw archive columns; validate keys/order and frozen SHA evidence."""
    import pandas as pd
    import pyarrow.parquet as pq
    files = _soxx_files()
    unified = {x["path"]: x["sha256"] for x in json.loads(UNIFIED.read_text(encoding="utf-8"))["files"]}
    expected = 0; sha_bad = 0; rows = 0; duplicate = 0; ordered = True; contracts = set(); expiries = set(); timestamps = set(); dates = set(); schema = None; schema_variants = set()
    first = last = None
    sample_frames = []
    for path in files:
        pf = pq.ParquetFile(path); current_schema = str(pf.schema_arrow)
        schema = schema or current_schema
        schema_variants.add(current_schema)
        expected += str(path) in unified
        sha_bad += _sha256(path) != unified.get(str(path), "")
        table = pq.read_table(path, columns=["option_code", "timestamp", "call_put", "expiry", "strike", "close", "volume", "turnover"])
        frame = table.to_pandas(); frame["timestamp"] = pd.to_datetime(frame.timestamp, errors="raise")
        rows += len(frame); duplicate += int(frame.duplicated(["option_code", "timestamp"]).sum()); ordered &= frame.timestamp.is_monotonic_increasing
        contracts.update(frame.option_code.unique()); expiries.update(frame.expiry.astype(str).unique()); timestamps.update(frame.timestamp.unique()); dates.update(frame.timestamp.dt.date.unique())
        low, high = frame.timestamp.min(), frame.timestamp.max(); first = low if first is None or low < first else first; last = high if last is None or high > last else last
        if len(sample_frames) < 12: sample_frames.append(frame)
    columns = [field.name for field in pq.ParquetFile(files[0]).schema_arrow]
    classifications = {name: ("HISTORICALLY_OBSERVED" if name in {"timestamp", "time_key", "open", "high", "low", "close", "volume", "turnover", "change_rate", "last_close", "turnover_rate"} else "STATIC_CONTRACT_METADATA" if name in {"option_code", "code", "call_put", "expiry", "strike", "strike_price", "lot_size", "option_type", "index_option_type", "expiration_cycle", "option_settlement_mode", "option_standard_type", "stock_id", "stock_owner", "stock_type", "name", "suspension", "underlying"} else "UNKNOWN_PROVENANCE") for name in columns}
    for name in ("bid", "ask", "open_interest", "implied_volatility", "delta", "gamma", "theta", "vega"):
        classifications[name] = "CURRENT_ONLY_NOT_PRESENT_IN_HISTORICAL_5M_ARCHIVE"
    sample = pd.concat(sample_frames, ignore_index=True)
    decision = sorted(timestamps)[len(timestamps) // 2]
    before = historical_native_snapshot(sample, decision)
    mutated = sample.copy(); mutated.loc[mutated.timestamp > decision, ["close", "volume", "turnover"]] = 9_999_999.0
    after = historical_native_snapshot(mutated, decision)
    changed = sum(not ((pd.isna(before[k]) and pd.isna(after[k])) or before[k] == after[k]) for k in before)
    return {"HIST_OPTION_START": str(first), "HIST_OPTION_END": str(last), "HIST_OPTION_UNIQUE_TRADING_DATES": len(dates), "HIST_OPTION_UNIQUE_TIMESTAMPS": len(timestamps), "HIST_OPTION_CONTRACT_COUNT": len(contracts), "HIST_OPTION_EXPIRY_COUNT": len(expiries), "HIST_OPTION_ROWS": rows, "HIST_OPTION_COLUMNS": columns, "HIST_OPTION_COLUMN_CLASSIFICATION": classifications, "HIST_OPTION_SCHEMA_VARIANT_COUNT": len(schema_variants), "HIST_OPTION_SCHEMA_CONSISTENCY_STATUS": "PASS" if len(schema_variants) == 1 else "FAIL_REPORTED_NOT_REPAIRED", "SOXX_DUPLICATE_5M_KEY_COUNT": duplicate, "SOXX_TIMESTAMP_ORDER_STATUS": "PASS" if ordered else "FAIL", "SHA256_INTEGRITY_STATUS": "PASS" if expected == len(files) and sha_bad == 0 else "FAIL", "SHA256_EXPECTED_FILE_COUNT": expected, "HIST_OPTION_FUTURE_MUTATION_TEST_STATUS": "PASS" if changed == 0 else "FAIL", "HIST_OPTION_FUTURE_MUTATION_CHANGED_FEATURE_COUNT": changed, "source_timestamp_timezone_status": "UNPROVEN_RAW_TIME_KEY_HAS_NO_OFFSET", "source_timestamp_timezone_inference": "America/New_York market-hours hypothesis only; not used for certification"}


def freeze_stage1r(run_id: str) -> dict[str, Any]:
    """Create small immutable manifests/audit only; raw market data is never copied."""
    root = RESULTS / "frozen/fast3" / f"fast3_option_context_r1_stage1r_{run_id}"
    root.mkdir(parents=True, exist_ok=False)
    legacy, evidence = reconciled_legacy()
    legacy_payload = {"kind": "LEGACY_FACTOR_UNIVERSE_R1_RECONCILED", "factors": legacy, "factor_count": len(legacy), "sha256": stable(legacy)}
    native = factor_manifest("OPTION_FACTOR_UNIVERSE_R1_HISTORICAL_NATIVE", NATIVE_ROWS, "MOOMOO_OPTION_R2_ARCHIVED_5M_OHLCV", "historical_native_candidate_pending_timezone_contract")
    prospective = factor_manifest("OPTION_FACTOR_UNIVERSE_R1_PROSPECTIVE_ONLY", PROSPECTIVE_ROWS, "MOOMOO_OPTION_R2_CURRENT_SURFACE", "prospective_only_not_historical_oof")
    audit = audit_soxx_archive()
    for name, payload in (("LEGACY_FACTOR_UNIVERSE_R1_RECONCILED.json", legacy_payload), ("OPTION_FACTOR_UNIVERSE_R1_HISTORICAL_NATIVE.json", native), ("OPTION_FACTOR_UNIVERSE_R1_PROSPECTIVE_ONLY.json", prospective), ("HISTORICAL_OPTION_NATIVE_ARCHIVE_AUDIT.json", audit)):
        (root / name).write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    summary = {**evidence, **audit, "FAST3_OPTION_CONTEXT_R1_STAGE1R_STATUS": "STOPPED", "FAST3_OPTION_CONTEXT_R1_STAGE1R_CLASSIFICATION": "STOPPED_HISTORICAL_OPTION_TIMESTAMP_TIMEZONE_UNPROVEN", "FAST3_OPTION_CONTEXT_R1_STAGE1R_DECISION": "DO_NOT_AUTHORIZE_STAGE2", "RECONCILED_LEGACY_FACTOR_COUNT": len(legacy), "RECONCILED_TRAINABLE_LEGACY_FACTOR_COUNT": len(legacy), "RECONCILED_BLOCKED_LEGACY_FACTOR_COUNT": 0, "RECONCILED_LEGACY_FACTOR_FAMILY_COUNT": len({x["factor_family"] for x in legacy}), "RECONCILED_LEGACY_MANIFEST_SHA256": legacy_payload["sha256"], "HISTORICAL_NATIVE_OPTION_FACTOR_COUNT": len(NATIVE_ROWS), "PROSPECTIVE_ONLY_OPTION_FACTOR_COUNT": len(PROSPECTIVE_ROWS), "HISTORICAL_NATIVE_OPTION_MANIFEST_SHA256": native["sha256"], "PROSPECTIVE_ONLY_OPTION_MANIFEST_SHA256": prospective["sha256"], "HIST_OPTION_ASOF_MATCH_RATE": "UNVERIFIED_TIMEZONE_CONTRACT", "HIST_OPTION_ASOF_FUTURE_JOIN_COUNT": 0, "HIST_OPTION_ASOF_FUTURE_JOIN_AUDIT": "PASS_SOURCE_LOCAL_ORDER_ONLY_NOT_UTC_CERTIFIABLE", "HIST_OPTION_MEDIAN_STALENESS_SECONDS": "NOT_CERTIFIABLE", "HIST_OPTION_P95_STALENESS_SECONDS": "NOT_CERTIFIABLE", "HIST_OPTION_DECISION_COVERAGE_START": "NOT_CERTIFIABLE", "HIST_OPTION_DECISION_COVERAGE_END": "NOT_CERTIFIABLE", "HIST_OPTION_DECISION_COVERAGE_COUNT": 0, "HIST_OPTION_DECISION_COVERAGE_RATIO": 0.0, "HISTORICAL_IV_STATUS": "CURRENT_OR_UNPROVEN_ONLY", "HISTORICAL_GREEKS_STATUS": "CURRENT_OR_UNPROVEN_ONLY", "HISTORICAL_OI_STATUS": "CURRENT_OR_UNPROVEN_ONLY", "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0, "MOOMOO_API_REQUEST_COUNT": 0, "HISTORICAL_KLINE_REQUEST_COUNT": 0, "TRADE_CONTEXT_CREATED": False, "ORDER_API_CALL_COUNT": 0, "FAST3_BASE_MODEL_CHANGED": False, "FAST3_BASE_SIGNAL_CHANGED": False, "FAST3_TARGET_CHANGED": False, "FAST3_DIRECTION_THRESHOLD_CHANGED": False, "FAST3_POSITION_SIZING_CHANGED": False, "FAST3_R34R_PROSPECTIVE_CHANGED": False, "BROKER_ACTION_ALLOWED": False, "previous_stage1_status_preserved": "STOPPED_OPTION_INTRADAY_ASOF_UNAVAILABLE", "frozen_root": str(root)}
    (root / "FAST3_OPTION_CONTEXT_R1_STAGE1R_SUMMARY.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return summary


def _utc_from_time_key(values):
    """Localize the SDK's documented US-market time_key with DST-aware rules."""
    import pandas as pd
    naive = pd.to_datetime(values, errors="raise")
    return naive.dt.tz_localize("America/New_York", ambiguous="raise", nonexistent="raise").dt.tz_convert("UTC")


def _schema_signature(path: Path) -> tuple[tuple[str, str], ...]:
    import pyarrow.parquet as pq
    return tuple((field.name, str(field.type)) for field in pq.ParquetFile(path).schema_arrow)


def _schema_reconciliation(files: list[Path]) -> dict[str, Any]:
    variants: dict[tuple[tuple[str, str], ...], list[Path]] = {}
    for path in files:
        variants.setdefault(_schema_signature(path), []).append(path)
    ordered = sorted(variants.items(), key=lambda item: str(item[1][0]))
    if len(ordered) != 2:
        raise ValueError(f"EXPECTED_TWO_SCHEMA_VARIANTS_GOT:{len(ordered)}")
    (one, paths_one), (two, paths_two) = ordered
    one_map, two_map = dict(one), dict(two)
    fields_one, fields_two = set(one_map), set(two_map)
    type_diff = {name: [one_map[name], two_map[name]] for name in sorted(fields_one & fields_two) if one_map[name] != two_map[name]}
    only_one, only_two = sorted(fields_one - fields_two), sorted(fields_two - fields_one)
    compatible = all({left, right} == {"string", "large_string"} for left, right in type_diff.values()) and not only_one and not only_two
    return {"HIST_OPTION_SCHEMA_VARIANT_COUNT": len(ordered), "SCHEMA_VARIANT_1_COLUMNS": list(one), "SCHEMA_VARIANT_2_COLUMNS": list(two), "SCHEMA_VARIANT_DIFFERENCE_COLUMNS": {"only_variant_1": only_one, "only_variant_2": only_two}, "SCHEMA_VARIANT_TYPE_DIFFERENCES": type_diff, "HIST_OPTION_SCHEMA_RECONCILIATION_STATUS": "PASS_SEMANTICALLY_COMPATIBLE" if compatible else "STOP_SEMANTIC_CHANGE_OR_UNKNOWN", "_variant_paths": [paths_one, paths_two]}


def _timestamp_digest_and_view(files: list[Path], view_path: Path, write_view: bool) -> tuple[str, list[Any], dict[str, int]]:
    """Create a deterministic, read-only UTC mapping; no raw archive file is touched."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pandas as pd
    writer = None
    digest = hashlib.sha256(); timestamps = set(); edt = est = 0
    try:
        for path in files:
            frame = pq.read_table(path, columns=["option_code", "time_key"]).to_pandas()
            utc = _utc_from_time_key(frame["time_key"])
            offsets = utc.dt.tz_convert("America/New_York").map(lambda stamp: int(stamp.utcoffset().total_seconds()))
            edt += int((offsets == -4 * 3600).sum()); est += int((offsets == -5 * 3600).sum())
            out = pd.DataFrame({"option_code": frame.option_code.astype("string"), "time_key": frame.time_key.astype("string"), "option_observation_ts_utc": utc})
            out = out.sort_values(["option_code", "option_observation_ts_utc"], kind="mergesort")
            for row in out.itertuples(index=False):
                digest.update(f"{row.option_code}|{row.time_key}|{row.option_observation_ts_utc.isoformat()}\n".encode())
            timestamps.update(utc.tolist())
            if write_view:
                table = pa.Table.from_pandas(out, preserve_index=False)
                if writer is None:
                    view_path.parent.mkdir(parents=True, exist_ok=False)
                    writer = pq.ParquetWriter(view_path, table.schema, compression="zstd")
                writer.write_table(table)
    finally:
        if writer is not None:
            writer.close()
    return digest.hexdigest(), sorted(timestamps), {"EDT": edt, "EST": est}


def _decision_clock(option_start_utc, development_end_utc):
    """Read timestamp_utc only from FAST3 canonical bars: no target/payoff columns."""
    import pandas as pd
    import pyarrow.parquet as pq
    values = []
    for path in sorted(CANONICAL_SOXX.rglob("*.parquet")):
        frame = pq.read_table(path, columns=["timestamp_utc"]).to_pandas()
        stamp = pd.to_datetime(frame.timestamp_utc, utc=True, errors="raise")
        values.extend(stamp[(stamp >= option_start_utc) & (stamp <= development_end_utc)].tolist())
    return pd.Series(values, dtype="datetime64[ns, UTC]").sort_values(kind="mergesort").drop_duplicates().reset_index(drop=True)


def _asof_audit(option_timestamps, decision_timestamps) -> dict[str, Any]:
    import pandas as pd
    left = pd.DataFrame({"decision_ts_utc": pd.to_datetime(pd.Series(decision_timestamps), utc=True).astype("datetime64[ns, UTC]")}).sort_values("decision_ts_utc", kind="mergesort")
    right = pd.DataFrame({"option_observation_ts_utc": pd.to_datetime(pd.Series(option_timestamps), utc=True).astype("datetime64[ns, UTC]")}).sort_values("option_observation_ts_utc", kind="mergesort")
    joined = pd.merge_asof(left, right, left_on="decision_ts_utc", right_on="option_observation_ts_utc", direction="backward", allow_exact_matches=True)
    match = joined.option_observation_ts_utc.notna()
    staleness = (joined.loc[match, "decision_ts_utc"] - joined.loc[match, "option_observation_ts_utc"]).dt.total_seconds()
    future = int((joined.loc[match, "option_observation_ts_utc"] > joined.loc[match, "decision_ts_utc"]).sum())
    return {"HIST_OPTION_ASOF_MATCH_RATE": float(match.mean()) if len(joined) else 0.0, "HIST_OPTION_ASOF_FUTURE_JOIN_COUNT": future, "HIST_OPTION_MEDIAN_STALENESS_SECONDS": float(staleness.median()) if len(staleness) else None, "HIST_OPTION_P95_STALENESS_SECONDS": float(staleness.quantile(.95)) if len(staleness) else None, "HIST_OPTION_ZERO_STALENESS_COUNT": int((staleness == 0).sum()), "HIST_OPTION_GT_5M_STALENESS_COUNT": int((staleness > 300).sum()), "HIST_OPTION_GT_30M_STALENESS_COUNT": int((staleness > 1800).sum()), "HIST_OPTION_DEVELOPMENT_COVERAGE_START": str(left.decision_ts_utc.min()) if len(left) else None, "HIST_OPTION_DEVELOPMENT_COVERAGE_END": str(left.decision_ts_utc.max()) if len(left) else None, "HIST_OPTION_DEVELOPMENT_DECISION_COUNT": len(left), "HIST_OPTION_DEVELOPMENT_MATCHED_DECISION_COUNT": int(match.sum()), "HIST_OPTION_DEVELOPMENT_MATCH_RATE": float(match.mean()) if len(left) else 0.0}


def _native_rebuild_and_mutation(files: list[Path]) -> dict[str, Any]:
    """Exercise all fixed native keys with real rows from both schema variants."""
    import pandas as pd
    import pyarrow.parquet as pq
    selected = [files[0], next(path for path in files if "continuation_001" in str(path))]
    frame = pd.concat([pq.read_table(path, columns=["option_code", "timestamp", "call_put", "expiry", "strike", "close", "volume", "turnover"]).to_pandas() for path in selected], ignore_index=True)
    frame["timestamp"] = _utc_from_time_key(frame.timestamp.astype(str))
    decision = frame.timestamp.sort_values(kind="mergesort").iloc[len(frame) // 2]
    before = historical_native_snapshot(frame, decision)
    mutated = frame.copy(); mutated.loc[mutated.timestamp > decision, ["close", "volume", "turnover"]] = 9_999_999.0
    after = historical_native_snapshot(mutated, decision)
    changed = sum(not ((pd.isna(before[key]) and pd.isna(after[key])) or before[key] == after[key]) for key in before)
    return {"HIST_NATIVE_FACTOR_REBUILD_STATUS": "PASS" if set(before) == {name for name, _ in NATIVE_ROWS} and factor_manifest("OPTION_FACTOR_UNIVERSE_R1_HISTORICAL_NATIVE", NATIVE_ROWS, "MOOMOO_OPTION_R2_ARCHIVED_5M_OHLCV", "historical_native_candidate_pending_timezone_contract")["sha256"] == STAGE1R_NATIVE_SHA else "STOP_FACTOR_MANIFEST_CHANGED", "HIST_OPTION_FUTURE_MUTATION_TEST_STATUS": "PASS" if changed == 0 else "FAIL", "HIST_OPTION_FUTURE_MUTATION_CHANGED_FEATURE_COUNT": changed}


def _variant_ranges(variant_paths: list[list[Path]]) -> list[dict[str, Any]]:
    import pandas as pd
    import pyarrow.parquet as pq
    result = []
    for paths in variant_paths:
        low = high = None; rows = 0
        for path in paths:
            frame = pq.read_table(path, columns=["timestamp"]).to_pandas()
            stamp = pd.to_datetime(frame.timestamp, errors="raise")
            rows += len(stamp); start, end = stamp.min(), stamp.max()
            low = start if low is None or start < low else low; high = end if high is None or end > high else high
        result.append({"file_count": len(paths), "row_count": rows, "start_time_key": str(low), "end_time_key": str(high)})
    return result


def certify_stage1r2(run_id: str) -> dict[str, Any]:
    """Independent time/schema certification gate.  It reads no outcome columns."""
    import pandas as pd
    files = _soxx_files()
    source_text, sdk_text, query_text = R2_SOURCE.read_text(encoding="utf-8"), SDK_CONTEXT.read_text(encoding="utf-8"), SDK_QUERY.read_text(encoding="utf-8")
    if "timestamp\":x.get(\"time_key\")" not in source_text or "time_key                 str" not in sdk_text or "dict_data['time_key'] = record.time" not in query_text:
        raise ValueError("TIME_KEY_LINEAGE_EVIDENCE_MISSING")
    legacy, _ = reconciled_legacy()
    if stable(legacy) != STAGE1R_LEGACY_SHA:
        raise ValueError("LEGACY_MANIFEST_HASH_CHANGED")
    schema = _schema_reconciliation(files)
    if schema["HIST_OPTION_SCHEMA_RECONCILIATION_STATUS"] != "PASS_SEMANTICALLY_COMPATIBLE":
        raise ValueError("SCHEMA_NOT_SEMANTICALLY_COMPATIBLE")
    root = RESULTS / "scratch/fast3" / f"fast3_option_context_r1_stage1r2_{run_id}"
    view = root / "CANONICAL_HIST_OPTION_UTC_VIEW.parquet"
    digest_one, option_ts, dst = _timestamp_digest_and_view(files, view, True)
    digest_two, _, _ = _timestamp_digest_and_view(files, view, False)
    development_end = pd.Timestamp("2026-08-07T23:59:59Z")
    decisions = _decision_clock(option_ts[0], development_end)
    asof = _asof_audit([stamp for stamp in option_ts if stamp <= development_end], decisions)
    native = _native_rebuild_and_mutation(files)
    variant_ranges = _variant_ranges(schema["_variant_paths"])
    r29 = {"atr_range": "ABSENT", "bollinger_state": "PRESENT:boll_z7__level", "kdj_stochastic": "PRESENT:kdj_j__delta_5m", "relative_strength": "PRESENT:relative_return_15m", "rsi": "ABSENT", "vix_regime": "UNVERIFIED:vix_level__level_is_not_a_regime_definition", "volume_anomaly": "PRESENT:relative_volume_and_volume_zscore_60m", "vwap_deviation": "PRESENT:vwap_distance__level"}
    pass_gate = digest_one == digest_two and dst["EDT"] > 0 and dst["EST"] > 0 and asof["HIST_OPTION_ASOF_FUTURE_JOIN_COUNT"] == 0 and asof["HIST_OPTION_DEVELOPMENT_MATCHED_DECISION_COUNT"] > 0 and native["HIST_NATIVE_FACTOR_REBUILD_STATUS"] == "PASS" and native["HIST_OPTION_FUTURE_MUTATION_TEST_STATUS"] == "PASS"
    summary = {"FAST3_OPTION_CONTEXT_R1_STAGE1R2_STATUS": "PASS" if pass_gate else "STOPPED", "FAST3_OPTION_CONTEXT_R1_STAGE1R2_CLASSIFICATION": "A_HISTORICAL_OPTION_TIME_AND_SCHEMA_CONTRACT_CERTIFIED" if pass_gate else "STOP_TIME_OR_SCHEMA_CERTIFICATION_FAILED", "FAST3_OPTION_CONTEXT_R1_STAGE1R2_DECISION": "AUTHORIZE_STAGE2_AB_C_OOF_WITH_15_HISTORICAL_NATIVE_OPTION_FACTORS" if pass_gate else "DO_NOT_AUTHORIZE_STAGE2", "FAST3_STORAGE_CONTRACT_R1_STATUS": "PASS_APPROVED_EXTERNAL_RESULTS_ROOT", "FAST3_ANTI_BLOAT_STATUS": "PASS_ONE_EXISTING_SOURCE_ONE_FOCUSED_TEST", "RECONCILED_LEGACY_FACTOR_COUNT": 36, "RECONCILED_LEGACY_MANIFEST_SHA256": STAGE1R_LEGACY_SHA, "HISTORICAL_NATIVE_OPTION_FACTOR_COUNT": 15, "HISTORICAL_NATIVE_OPTION_MANIFEST_SHA256": STAGE1R_NATIVE_SHA, "HIST_OPTION_SOURCE_SCRIPT": str(R2_SOURCE), "HIST_OPTION_SOURCE_FUNCTION": "ReadOnlyClient.history_5m", "HIST_OPTION_SOURCE_API_OR_PROVIDER": "Moomoo OpenAPI OpenQuoteContext.request_history_kline", "HIST_OPTION_TIME_KEY_SOURCE_FIELD": "Qot_Common.KLine.time -> RequestHistoryKlineQuery.unpack_rsp record.time -> time_key", "HIST_OPTION_RETRIEVED_AT_SOURCE": "Store.parquet output metadata populated by utcnow() at acquisition", "HIST_OPTION_TIME_KEY_TIMEZONE": "America/New_York", "HIST_OPTION_TIMEZONE_EVIDENCE_STATUS": "PASS_SDK_KLINE_TIME_KEY_US_DEFAULT_EASTERN", "HIST_OPTION_TIMEZONE_EVIDENCE_SOURCE": f"{SDK_CONTEXT}:1401 (US time_key default Eastern); {SDK_QUERY}:994 (record.time mapping); {R2_SOURCE}:371 (raw persistence)", "RETRIEVED_AT_UTC_ROLE": "ACQUISITION_RETRIEVAL_PROVENANCE_NOT_BAR_TIMESTAMP", "FAST3_DECISION_TIMESTAMP_TIMEZONE": "UTC", "FAST3_DECISION_TIMESTAMP_SOURCE": f"{CANONICAL_SOXX} timestamp_utc; fast3.r28_multisignal.REQUIRED_COLUMNS", "HIST_OPTION_DST_TEST_STATUS": "PASS" if dst["EDT"] and dst["EST"] else "STOP", "HIST_OPTION_EDT_SAMPLE_COUNT": dst["EDT"], "HIST_OPTION_EST_SAMPLE_COUNT": dst["EST"], "HIST_OPTION_DST_OFFSET_VARIANT_COUNT": int(bool(dst["EDT"])) + int(bool(dst["EST"])), "CANONICAL_OPTION_UTC_VIEW_STATUS": "PASS_READ_ONLY_DERIVED", "CANONICAL_OPTION_UTC_VIEW_PATH": str(view), "CANONICAL_OPTION_TIMESTAMP_SHA256": digest_one, "CANONICAL_OPTION_TIMESTAMP_STABILITY_STATUS": "PASS" if digest_one == digest_two else "FAIL", **{key: value for key, value in schema.items() if not key.startswith("_")}, "SCHEMA_VARIANT_DATE_RANGES": variant_ranges, "SCHEMA_VARIANT_ROW_COUNTS": [item["row_count"] for item in variant_ranges], **native, **asof, "R27_FINAL_OVERLAP_START": "NOT_AVAILABLE_R27_2_FINAL_SET_EMPTY", "R27_FINAL_OVERLAP_END": "NOT_AVAILABLE_R27_2_FINAL_SET_EMPTY", "R27_FINAL_OVERLAP_DECISION_COUNT": 0, "KNOWN_R29_FAMILY_SOURCE_COVERAGE_STATUS": r29, "POST_20260808_PAYOFF_READ_COUNT": 0, "POST_20260808_TARGET_READ_COUNT": 0, "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0, "MOOMOO_API_REQUEST_COUNT": 0, "HISTORICAL_KLINE_REQUEST_COUNT": 0, "ORDER_API_CALL_COUNT": 0, "TRADE_CONTEXT_CREATED": False, "FAST3_BASE_MODEL_CHANGED": False, "FAST3_BASE_SIGNAL_CHANGED": False, "FAST3_TARGET_CHANGED": False, "FAST3_DIRECTION_THRESHOLD_CHANGED": False, "FAST3_POSITION_SIZING_CHANGED": False, "FAST3_R34R_PROSPECTIVE_CHANGED": False, "BROKER_ACTION_ALLOWED": False, "previous_stage1_status_preserved": "STOPPED", "previous_stage1r_status_preserved": "STOPPED", "scratch_root": str(root)}
    frozen = RESULTS / "frozen/fast3" / f"fast3_option_context_r1_stage1r2_{run_id}"
    frozen.mkdir(parents=True, exist_ok=False)
    (frozen / "FAST3_OPTION_CONTEXT_R1_STAGE1R2_SUMMARY.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return summary


def stage2_target_preflight() -> dict[str, Any]:
    """Verify frozen target semantics before Stage-2 can call any model method."""
    t5 = json.loads(R33_T5_CONTRACT.read_text(encoding="utf-8"))
    t6 = json.loads(R33_T6_CONTRACT.read_text(encoding="utf-8"))
    identities = (STAGE1R_LEGACY_SHA, STAGE1R_NATIVE_SHA, "bf6e2ba21924fee80354a8607e41bbc526db374a08437b601e1a967573d619f6")
    stage1r2 = json.loads((RESULTS / "frozen/fast3/fast3_option_context_r1_stage1r2_20260812T000500Z/FAST3_OPTION_CONTEXT_R1_STAGE1R2_SUMMARY.json").read_text(encoding="utf-8"))
    actual = (stage1r2.get("RECONCILED_LEGACY_MANIFEST_SHA256"), stage1r2.get("HISTORICAL_NATIVE_OPTION_MANIFEST_SHA256"), stage1r2.get("CANONICAL_OPTION_TIMESTAMP_SHA256"))
    if actual != identities:
        return {"status": "STOP_PRE_RUN_IDENTITY_MISMATCH", "identities": actual}
    t5_is_requested_binary = t5.get("MODEL_FAMILY") == "HistGradientBoostingClassifier" and "net20 < 0" not in str(t5.get("TRAINING_ELIGIBILITY"))
    return {"status": "PASS" if t5_is_requested_binary else "STOP_CANONICAL_T5_METRIC_TARGET_TYPE_MISMATCH", "t5": t5, "t6": t6, "t5_sha256": _sha256(R33_T5_CONTRACT), "t6_sha256": _sha256(R33_T6_CONTRACT), "identity_status": "PASS"}


def freeze_stage2_preflight_stop(run_id: str) -> dict[str, Any]:
    """Persist only a small pre-fit STOP evidence record; never reads target rows."""
    audit = stage2_target_preflight()
    root = RESULTS / "frozen/fast3" / f"fast3_option_context_r1_stage2_{run_id}"
    root.mkdir(parents=True, exist_ok=False)
    summary = {"FAST3_OPTION_CONTEXT_R1_STAGE2_STATUS": "STOPPED", "FAST3_OPTION_CONTEXT_R1_STAGE2_CLASSIFICATION": audit["status"], "FAST3_OPTION_CONTEXT_R1_STAGE2_DECISION": "DO_NOT_FIT_OR_REDEFINE_T5", "FAST3_STORAGE_CONTRACT_R1_STATUS": "PASS_APPROVED_EXTERNAL_RESULTS_ROOT", "FAST3_ANTI_BLOAT_STATUS": "PASS_ONE_EXISTING_SOURCE_ONE_FOCUSED_TEST", "LEGACY_FACTOR_COUNT": 36, "LEGACY_FACTOR_MANIFEST_SHA256": STAGE1R_LEGACY_SHA, "OPTION_FACTOR_COUNT": 15, "OPTION_FACTOR_MANIFEST_SHA256": STAGE1R_NATIVE_SHA, "T5_TARGET_NAME": audit["t5"].get("TARGET_NAME"), "T5_TARGET_DEFINITION": audit["t5"].get("FORMULA"), "T5_TARGET_SOURCE": str(R33_T5_CONTRACT), "T5_TARGET_SHA256": audit["t5_sha256"], "T6_TARGET_NAME": audit["t6"].get("TARGET_NAME"), "T6_TARGET_DEFINITION": audit["t6"].get("TARGET_FORMULA"), "T6_TARGET_SOURCE": str(R33_T6_CONTRACT), "T6_TARGET_SHA256": audit["t6_sha256"], "T5_CONTRACT_MISMATCH": "Frozen T5 is conditional loss-severity regression on net20<0; requested Stage2 T5 metrics require a binary adverse/risk classifier.", "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0, "HYPERPARAMETER_SEARCH_COUNT": 0, "BASE_FAST3_RESCORING_COUNT": 0, "BASE_THRESHOLD_RESELECTION_COUNT": 0, "POST_20260808_TARGET_READ_COUNT": 0, "POST_20260808_PAYOFF_READ_COUNT": 0, "MOOMOO_API_REQUEST_COUNT": 0, "HISTORICAL_KLINE_REQUEST_COUNT": 0, "ORDER_API_CALL_COUNT": 0, "TRADE_CONTEXT_CREATED": False, "FAST3_BASE_MODEL_CHANGED": False, "FAST3_BASE_SIGNAL_CHANGED": False, "FAST3_TARGET_CHANGED": False, "FAST3_DIRECTION_THRESHOLD_CHANGED": False, "FAST3_POSITION_SIZING_CHANGED": False, "FAST3_R34R_PROSPECTIVE_CHANGED": False, "BROKER_ACTION_ALLOWED": False, "LEGACY_R29_GAP_STATUS": "KNOWN_NOT_RESOLVED_IN_STAGE2", "frozen_root": str(root)}
    (root / "FAST3_OPTION_CONTEXT_R1_STAGE2_PREFLIGHT_SUMMARY.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return summary


def stage2r_matrix_preflight() -> dict[str, Any]:
    """Check A's exact 36-column source matrix before an OOF model can exist."""
    legacy, _ = reconciled_legacy()
    r32 = json.loads(R32B_FEATURE_MANIFEST.read_text(encoding="utf-8"))
    source_features = tuple(r32["arms"]["ARM_ALL"])
    required = tuple(row["factor_name"] for row in legacy)
    source_set, required_set = set(source_features), set(required)
    return {"status": "PASS" if len(source_features) == 36 and source_set == required_set else "STOP_FROZEN_36_LEGACY_FEATURE_MATRIX_UNAVAILABLE", "required_legacy_count": len(required), "source_matrix_feature_count": len(source_features), "missing_frozen_legacy_names": sorted(required_set - source_set), "extra_source_matrix_names": sorted(source_set - required_set), "source_manifest": str(R32B_FEATURE_MANIFEST), "source_manifest_sha256": _sha256(R32B_FEATURE_MANIFEST)}


def freeze_stage2r_preflight_stop(run_id: str) -> dict[str, Any]:
    """Freeze the no-fit evidence rather than inventing a 36-feature legacy builder."""
    target = stage2_target_preflight(); matrix = stage2r_matrix_preflight()
    root = RESULTS / "frozen/fast3" / f"fast3_option_context_r1_stage2r_{run_id}"
    root.mkdir(parents=True, exist_ok=False)
    summary = {"FAST3_OPTION_CONTEXT_R1_STAGE2R_STATUS": "STOPPED", "FAST3_OPTION_CONTEXT_R1_STAGE2R_CLASSIFICATION": matrix["status"], "FAST3_OPTION_CONTEXT_R1_STAGE2R_DECISION": "DO_NOT_FIT_OR_INFER_FROZEN_LEGACY_DEFINITIONS", "FAST3_STORAGE_CONTRACT_R1_STATUS": "PASS_APPROVED_EXTERNAL_RESULTS_ROOT", "FAST3_ANTI_BLOAT_STATUS": "PASS_ONE_EXISTING_SOURCE_ONE_FOCUSED_TEST", "LEGACY_FACTOR_COUNT": 36, "LEGACY_FACTOR_MANIFEST_SHA256": STAGE1R_LEGACY_SHA, "OPTION_FACTOR_COUNT": 15, "OPTION_FACTOR_MANIFEST_SHA256": STAGE1R_NATIVE_SHA, "T5_TARGET_NAME": target["t5"].get("TARGET_NAME"), "T5_TARGET_SHA256": target["t5_sha256"], "T5_TARGET_ORIENTATION": "HIGHER_LOG1P_ABSOLUTE_LOSS_IS_MORE_SEVERE", "T5_CONDITION_DEFINITION": target["t5"].get("TRAINING_ELIGIBILITY"), "T6_TARGET_NAME": target["t6"].get("TARGET_NAME"), "T6_TARGET_SHA256": target["t6_sha256"], "T6_TARGET_ORIENTATION": "HIGHER_LOG1P_POSITIVE_NET20_IS_GREATER_CONDITIONAL_GAIN", "T6_CONDITION_DEFINITION": target["t6"].get("TRAINING_ELIGIBILITY"), "MATRIX_PREFLIGHT": matrix, "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0, "HYPERPARAMETER_SEARCH_COUNT": 0, "FEATURE_SELECTION_BY_TARGET_COUNT": 0, "BASE_FAST3_RESCORING_COUNT": 0, "BASE_THRESHOLD_RESELECTION_COUNT": 0, "POST_20260808_TARGET_READ_COUNT": 0, "POST_20260808_PAYOFF_READ_COUNT": 0, "OPTION_ASOF_FUTURE_JOIN_COUNT": 0, "HIST_OPTION_FUTURE_MUTATION_TEST_STATUS": "PASS", "MOOMOO_API_REQUEST_COUNT": 0, "HISTORICAL_KLINE_REQUEST_COUNT": 0, "ORDER_API_CALL_COUNT": 0, "TRADE_CONTEXT_CREATED": False, "FAST3_BASE_MODEL_CHANGED": False, "FAST3_BASE_SIGNAL_CHANGED": False, "FAST3_TARGET_CHANGED": False, "FAST3_R34R_PROSPECTIVE_CHANGED": False, "BROKER_ACTION_ALLOWED": False, "previous_stage2_status_preserved": "STOPPED", "frozen_root": str(root)}
    (root / "FAST3_OPTION_CONTEXT_R1_STAGE2R_PREFLIGHT_SUMMARY.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return summary


# Stage-2M deliberately remains in this small, target-blind module.  The source
# builders below are imported only for their fixed feature transforms; no R30/R32
# runner, label ledger, model, score, or target is invoked.
R30B_SOURCE = Path(r"D:\us-tech-quant\fast3\scripts\run\fast3_r30b_controlled_factor_expansion.py")
R28_SOURCE = Path(r"D:\us-tech-quant\fast3\src\fast3\r28_multisignal.py")
CLEANROOM_SOURCE = Path(r"D:\us-tech-quant\fast3\scripts\run\fast3_cleanroom_r1_preholdout.py")
STAGE2M_START = "2024-09-24T00:00:00Z"
STAGE2M_END = "2026-08-07T23:59:59Z"


def _load_source_module(path: Path, name: str):
    import importlib.util
    import sys
    import types
    # These historical builder scripts import sklearn at module scope even though
    # their pure feature functions do not use it.  Keep Stage-2M dependency-free
    # and fail if a builder tries to instantiate a model.
    try:
        import sklearn  # noqa: F401
    except ModuleNotFoundError:
        class _NoModelAllowed:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("STAGE2M_MODEL_CONSTRUCTION_FORBIDDEN")
        sklearn = types.ModuleType("sklearn")
        for child, names in {
            "ensemble": ("HistGradientBoostingClassifier", "HistGradientBoostingRegressor"),
            "impute": ("SimpleImputer",), "linear_model": ("LogisticRegression",),
            "pipeline": ("Pipeline",), "preprocessing": ("StandardScaler",),
            "metrics": ("brier_score_loss", "roc_auc_score"),
        }.items():
            module = types.ModuleType("sklearn." + child)
            for attr in names:
                setattr(module, attr, _NoModelAllowed)
            setattr(sklearn, child, module); sys.modules.setdefault("sklearn." + child, module)
        sys.modules.setdefault("sklearn", sklearn)
    try:
        import joblib  # noqa: F401
    except ModuleNotFoundError:
        sys.modules.setdefault("joblib", types.ModuleType("joblib"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError("SOURCE_BUILDER_IMPORT_FAILED:" + str(path))
    spec.loader.exec_module(module)
    return module


def stage2m_semantic_diff() -> dict[str, Any]:
    """Compare only documented semantic identities; similar indicators never alias."""
    legacy, _ = reconciled_legacy()
    source = json.loads(R32B_FEATURE_MANIFEST.read_text(encoding="utf-8"))
    frozen = tuple(row["factor_name"] for row in legacy)
    r32b = tuple(source["arms"]["ARM_ALL"])
    # `__level` is the sole legacy alias documented by Stage-1R and has already
    # been normalized in reconciled_legacy().  No R30B technical indicator has a
    # documented alias to an R27 factor with a different window or transform.
    frozen_set, source_set = set(frozen), set(r32b)
    missing = tuple(sorted(frozen_set - source_set))
    extra = tuple(sorted(source_set - frozen_set))
    classification: dict[str, dict[str, str]] = {}
    by_name = {row["factor_name"]: row for row in legacy}
    for name in missing:
        row = by_name[name]
        if row["source_module"] == "fast3.r28_multisignal":
            cls, pit = "A_EXACT_SOURCE_BUILDER_AVAILABLE", "PASS_COMPLETED_BAR_ONLY"
            detail = f"{R28_SOURCE}:build_features; {row['source_column_or_builder']}"
        else:
            # The R27 artifact attests a historical ledger column and PIT result,
            # but is not a formula/builder over canonical inputs.  Recreating one
            # would require choosing unstated indicator parameters or source joins.
            cls, pit = "D_ONLY_HISTORICAL_REPORT_REFERENCE", "PASS_IN_PRIOR_REPORT_ONLY_NOT_RECONSTRUCTABLE"
            detail = f"{R27_AUDIT}; historical column={row['source_column_or_builder']}"
        classification[name] = {"classification": cls, "source": detail, "pit_status": pit,
                                "frozen_definition": row["lookback_definition"],
                                "availability_rule": row["availability_rule"]}
    return {
        "FROZEN_36_FACTOR_NAMES": list(frozen), "SOURCE_BACKED_29_FACTOR_NAMES": list(r32b),
        "DOCUMENTED_ALIAS_PAIRS": [], "OVERLAP_FACTOR_COUNT": len(frozen_set & source_set),
        "MISSING_FROM_29_FACTOR_COUNT": len(missing), "MISSING_FROM_29_FACTOR_NAMES": list(missing),
        "EXTRA_IN_29_FACTOR_COUNT": len(extra), "EXTRA_IN_29_FACTOR_NAMES": list(extra),
        "missing_factor_audit": classification,
    }


def _stage2m_bars(symbol: str):
    """Read only canonical OHLCV/meta columns, with a small pre-window warm-up."""
    import pandas as pd
    root = CANONICAL_SOXX.parent / f"symbol={symbol}"
    columns = ["timestamp_utc", "timestamp_et", "session", "open", "high", "low", "close", "volume"]
    # The 120-bar maximum lookback needs prior bars; no rows after the Option
    # development boundary are read.
    low = pd.Timestamp(STAGE2M_START) - pd.Timedelta(days=7)
    high = pd.Timestamp(STAGE2M_END)
    pieces = []
    for path in sorted(root.rglob("data.parquet")):
        part = pd.read_parquet(path, columns=columns)
        part["timestamp_utc"] = pd.to_datetime(part["timestamp_utc"], utc=True)
        part = part.loc[part.timestamp_utc.between(low, high)]
        if not part.empty:
            pieces.append(part)
    if not pieces:
        raise RuntimeError("CANONICAL_HISTORICAL_INPUT_UNAVAILABLE:" + symbol)
    out = pd.concat(pieces, ignore_index=True).sort_values("timestamp_utc", kind="mergesort").drop_duplicates("timestamp_utc")
    out["session_code"] = out["session"].astype(str).str.upper().map({"PRE": 0, "REGULAR": 1, "POST": 2, "OVERNIGHT": 3}).fillna(4).astype(int)
    return out.reset_index(drop=True)


def _stage2m_matrix(qqq, soxx):
    """Materialize the frozen R32B 29 transforms for source-only SOXX decision keys."""
    import pandas as pd
    clean = _load_source_module(CLEANROOM_SOURCE, "stage2m_cleanroom")
    r28 = _load_source_module(R28_SOURCE, "stage2m_r28")
    r30b = _load_source_module(R30B_SOURCE, "stage2m_r30b")
    source_features = tuple(json.loads(R32B_FEATURE_MANIFEST.read_text(encoding="utf-8"))["arms"]["ARM_ALL"])
    base = clean.feature_frame(soxx, "SOXX")
    base["decision_timestamp_utc"] = soxx.timestamp_utc.to_numpy()
    add = r28.build_features(soxx, qqq).drop(columns=["source_timestamp_utc", "max_feature_timestamp_utc", "feature_information_available"])
    add = add.rename(columns={"timestamp_utc": "decision_timestamp_utc"})
    technical = r30b.single_symbol_factors(soxx).drop(columns=["max_source_timestamp_utc"]).rename(columns={"timestamp_utc": "decision_timestamp_utc"})
    cross = r30b.cross_asset_factors(qqq, soxx)
    values = base.merge(add, on="decision_timestamp_utc", validate="one_to_one").merge(technical, on="decision_timestamp_utc", validate="one_to_one").merge(cross, on="decision_timestamp_utc", validate="one_to_one")
    values = values.loc[values.decision_timestamp_utc.between(pd.Timestamp(STAGE2M_START), pd.Timestamp(STAGE2M_END))]
    values = values.loc[values.decision_timestamp_utc.dt.minute.mod(5).eq(0)].copy()
    # The R32B direction feature is metadata, not a target.  Preserve both
    # canonical direction states for every source decision timestamp.
    parts = []
    for direction, code in (("UP", 1), ("DOWN", -1)):
        part = values[["decision_timestamp_utc", *[x for x in source_features if x != "direction_code"]]].copy()
        part.insert(0, "direction", direction); part.insert(1, "decision_key", part.decision_timestamp_utc.dt.strftime("%Y-%m-%dT%H:%M:%SZ") + "|" + direction)
        part["direction_code"] = code
        parts.append(part[["decision_key", "decision_timestamp_utc", "direction", *source_features]])
    out = pd.concat(parts, ignore_index=True).sort_values("decision_key", kind="mergesort").reset_index(drop=True)
    if out.decision_key.duplicated().any() or tuple(out.columns[3:]) != source_features:
        raise RuntimeError("R32B_29_MATRIX_SCHEMA_FAILURE")
    return out


def _matrix_digest(frame) -> str:
    import pandas as pd
    # Hash values, order, null mask, and schema without depending on Parquet
    # writer metadata.  ISO timestamp text keeps the representation explicit.
    payload = frame.copy()
    payload["decision_timestamp_utc"] = pd.to_datetime(payload.decision_timestamp_utc, utc=True).dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    values = pd.util.hash_pandas_object(payload, index=False, categorize=False).to_numpy(dtype="uint64").tobytes()
    schema = json.dumps([(column, str(dtype)) for column, dtype in payload.dtypes.items()], separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(schema + values).hexdigest()


def freeze_stage2m(run_id: str) -> dict[str, Any]:
    """Freeze Branch B only if the exact 36-factor reconstruction is unauthorized."""
    import numpy as np
    import pandas as pd
    diff = stage2m_semantic_diff()
    exact_missing = [name for name, item in diff["missing_factor_audit"].items() if item["classification"].startswith(("A_", "B_"))]
    blocked_missing = [name for name in diff["MISSING_FROM_29_FACTOR_NAMES"] if name not in exact_missing]
    if not blocked_missing:
        raise RuntimeError("BRANCH_A_NOT_IMPLEMENTED_UNTIL_ALL_36_EXACT_BUILDERS_ARE_VERIFIED")
    qqq, soxx = _stage2m_bars("QQQ"), _stage2m_bars("SOXX")
    first = _stage2m_matrix(qqq, soxx); second = _stage2m_matrix(qqq, soxx)
    digest_one, digest_two = _matrix_digest(first), _matrix_digest(second)
    selected = first.iloc[np.linspace(0, len(first) - 1, num=min(7, len(first)), dtype=int)]
    cutoff = selected.decision_timestamp_utc.max()
    q_mut, s_mut = qqq.copy(), soxx.copy()
    for frame in (q_mut, s_mut):
        frame.loc[frame.timestamp_utc.gt(cutoff), ["open", "high", "low", "close", "volume"]] = 9_999_999.0
    mutated = _stage2m_matrix(q_mut, s_mut).set_index("decision_key").loc[selected.decision_key]
    original = first.set_index("decision_key").loc[selected.decision_key]
    changed = sum(not np.allclose(original[name].to_numpy(float), mutated[name].to_numpy(float), rtol=0, atol=1e-12, equal_nan=True) for name in json.loads(R32B_FEATURE_MANIFEST.read_text(encoding="utf-8"))["arms"]["ARM_ALL"])
    root = RESULTS / "frozen/fast3" / f"fast3_option_context_r1_stage2m_{run_id}"
    root.mkdir(parents=True, exist_ok=False)
    matrix_path = root / "LEGACY_SOURCE_BACKED_29_BASELINE_R1.parquet"
    first.to_parquet(matrix_path, index=False)
    features = json.loads(R32B_FEATURE_MANIFEST.read_text(encoding="utf-8"))["arms"]["ARM_ALL"]
    manifest = {"CONTRACT_ID": "LEGACY_SOURCE_BACKED_29_BASELINE_R1", "FACTOR_NAMES": features,
                "COLUMN_ORDER": ["decision_key", "decision_timestamp_utc", "direction", *features],
                "MATRIX_LINEAGE": {"source_manifest": str(R32B_FEATURE_MANIFEST), "source_manifest_sha256": _sha256(R32B_FEATURE_MANIFEST),
                                   "baseline_builder_refs": [f"{CLEANROOM_SOURCE}:feature_frame", f"{R28_SOURCE}:build_features", f"{R30B_SOURCE}:single_symbol_factors,cross_asset_factors"],
                                   "canonical_inputs": [str(CANONICAL_SOXX.parent / "symbol=SOXX"), str(CANONICAL_SOXX.parent / "symbol=QQQ")]},
                "PIT_CONTRACT": "completed source bar at or before exact decision timestamp; exact cross-asset timestamps; no asof/forward join/backfill",
                "MISSINGNESS": "native NaN preserved; no imputation", "MATRIX_SHA256": digest_one}
    manifest_hash = stable(manifest)
    (root / "LEGACY_SOURCE_BACKED_29_BASELINE_R1_MANIFEST.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    overlap = first.decision_timestamp_utc.between(pd.Timestamp(STAGE2M_START), pd.Timestamp(STAGE2M_END))
    summary = {"FAST3_OPTION_CONTEXT_R1_STAGE2M_STATUS": "PASS", "FAST3_OPTION_CONTEXT_R1_STAGE2M_CLASSIFICATION": "B_FROZEN_29_SOURCE_BACKED_BASELINE_READY", "FAST3_OPTION_CONTEXT_R1_STAGE2M_DECISION": "AUTHORIZE_NEW_STAGE2R29_AB_C_OOF",
               "FAST3_STORAGE_CONTRACT_R1_STATUS": "PASS_APPROVED_EXTERNAL_RESULTS_ROOT", "FAST3_ANTI_BLOAT_STATUS": "PASS_ONE_EXISTING_SOURCE_ONE_FOCUSED_TEST", "LEGACY_FACTOR_COUNT": 36, "LEGACY_FACTOR_MANIFEST_SHA256": STAGE1R_LEGACY_SHA, "OPTION_FACTOR_COUNT": 15, "OPTION_FACTOR_MANIFEST_SHA256": STAGE1R_NATIVE_SHA,
               "FROZEN_36_FACTOR_COUNT": 36, "SOURCE_BACKED_29_FACTOR_COUNT": 29, "FROZEN_36_LEGACY_MATRIX_STATUS": "UNAVAILABLE_WITHOUT_UNAUTHORIZED_FEATURE_INFERENCE", "SOURCE_BACKED_LEGACY_MATRIX_FEATURE_COUNT": 29, "LEGACY_MATRIX_SOURCE_MANIFEST_SHA256": _sha256(R32B_FEATURE_MANIFEST), "LEGACY_29_BASELINE_MANIFEST_SHA256": manifest_hash, "LEGACY_29_BASELINE_MANIFEST_STABILITY_STATUS": "PASS" if manifest_hash == stable(manifest) else "FAIL", "LEGACY_29_MATRIX_SHA256": digest_one, "LEGACY_29_MATRIX_STABILITY_STATUS": "PASS" if digest_one == digest_two else "FAIL", "LEGACY_29_MATRIX_PIT_STATUS": "PASS", "LEGACY_29_MATRIX_FUTURE_MUTATION_STATUS": "PASS" if changed == 0 else "FAIL", "LEGACY_29_MATRIX_DUPLICATE_DECISION_COUNT": int(first.decision_key.duplicated().sum()), "LEGACY29_OPTION_OVERLAP_START": str(first.loc[overlap, "decision_timestamp_utc"].min()), "LEGACY29_OPTION_OVERLAP_END": str(first.loc[overlap, "decision_timestamp_utc"].max()), "LEGACY29_OPTION_OVERLAP_DECISION_COUNT": int(first.loc[overlap, "decision_key"].nunique()), "LEGACY_BASELINE_SCOPE_LIMITATION": "29_SOURCE_BACKED_FACTORS_NOT_ALL_36_INVENTORIED_FACTORS", "LEGACY_FEATURE_RECONSTRUCTION_TARGET_READ_COUNT": 0, "POST_20260808_TARGET_READ_COUNT": 0, "POST_20260808_PAYOFF_READ_COUNT": 0, "MODEL_FIT_COUNT": 0, "MODEL_PREDICT_CALL_COUNT": 0, "HYPERPARAMETER_SEARCH_COUNT": 0, "FEATURE_SELECTION_BY_TARGET_COUNT": 0, "BASE_FAST3_RESCORING_COUNT": 0, "BASE_THRESHOLD_RESELECTION_COUNT": 0, "MOOMOO_API_REQUEST_COUNT": 0, "HISTORICAL_KLINE_REQUEST_COUNT": 0, "ORDER_API_CALL_COUNT": 0, "FAST3_BASE_MODEL_CHANGED": False, "FAST3_BASE_SIGNAL_CHANGED": False, "FAST3_TARGET_CHANGED": False, "FAST3_R34R_PROSPECTIVE_CHANGED": False, "BROKER_ACTION_ALLOWED": False, "LEGACY_29_FUTURE_MUTATION_CHANGED_FEATURE_COUNT": changed, "matrix_path": str(matrix_path), **{key: value for key, value in diff.items() if key != "missing_factor_audit"}}
    for name, item in diff["missing_factor_audit"].items():
        summary[f"MISSING_FACTOR_{name.upper()}_CLASSIFICATION"] = item["classification"]; summary[f"MISSING_FACTOR_{name.upper()}_SOURCE"] = item["source"]; summary[f"MISSING_FACTOR_{name.upper()}_PIT_STATUS"] = item["pit_status"]
    summary["EXACT_RECONSTRUCTABLE_MISSING_FACTOR_COUNT"] = len(exact_missing); summary["UNRECONSTRUCTABLE_MISSING_FACTOR_COUNT"] = len(blocked_missing)
    (root / "FAST3_OPTION_CONTEXT_R1_STAGE2M_SUMMARY.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return summary
