"""Frozen raw-return COVERAGE_ONLY staging; never fits or computes real factors.

Only the CLI calls the raw reader. Pure stage_coverage is testable on synthetic
frames. Every emitted table contains keys, dates, counts or status/masks only.
This version has no certified cash-unit or dated-economic-identity source.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

MODULE_DIR = Path("D:/us-tech-quant/scripts/research/a2/factors")
MODULE_FILES = {"inputs": "economic_return_inputs.py", "features": "economic_return_features.py",
                "targets": "economic_return_targets.py"}
TRANSPORT_CONDITION = "VENDOR_TRANSPORT_CONDITIONAL_NOT_ECONOMIC_CERTIFICATION"
ARCHIVE_SCHEMA = "ARCHIVED_ACTION_FIELDS_PRESENT_CURRENT_SDK_SCHEMA_INTERPRETATION"
QUERY_SCOPE = "PINNED_SUCCESSFUL_GET_REHAB_FULL_HISTORY_SNAPSHOT"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_pins(pins):
    for path, expected in pins.items():
        if sha(path) != expected:
            raise RuntimeError(f"PREFLIGHT_HASH_MISMATCH:{path}")


def key_fingerprint(panel):
    keys = panel[["signal_date", "ticker"]].copy()
    keys["signal_date"] = pd.to_datetime(keys.signal_date, errors="raise")
    if (keys.isna().any().any() or keys.signal_date.dt.tz is not None
            or not keys.signal_date.eq(keys.signal_date.dt.normalize()).all()
            or keys.duplicated().any()):
        raise RuntimeError("INVALID_COHORT_KEYS")
    keys["ticker"] = keys.ticker.astype(str)
    if keys.ticker.str.contains(r"[\t\r\n]").any() or keys.ticker.str.strip().eq("").any():
        raise RuntimeError("INVALID_COHORT_TICKER")
    keys = keys.sort_values(["signal_date", "ticker"], kind="stable")
    encoded = "".join(f"{date:%Y-%m-%d}\t{ticker}\n" for date, ticker in keys.itertuples(index=False, name=None))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_cohort(panel, expected):
    digest = key_fingerprint(panel)
    counts = panel.groupby("signal_date").size()
    if (len(panel) != expected["rows"] or len(counts) != expected["dates"]
            or not counts.eq(expected["names_per_date"]).all()
            or str(pd.Timestamp(panel.signal_date.min()).date()) != expected["first_date"]
            or str(pd.Timestamp(panel.signal_date.max()).date()) != expected["last_date"]
            or digest != expected["key_sha256"]):
        raise RuntimeError("FROZEN_COHORT_MISMATCH")
    return digest


def frozen_setup(contract_path, bindings_path):
    contract = json.loads(Path(contract_path).read_text(encoding="utf-8"))
    cohort = contract.get("cohort", {})
    if (contract.get("phase") != "COVERAGE_ONLY"
            or contract.get("runner_source_sha256") != sha(__file__)
            or cohort.get("rows") != 49400 or cohort.get("dates") != 1235
            or cohort.get("names_per_date") != 40
            or cohort.get("first_date") != "2021-01-04" or cohort.get("last_date") != "2025-12-02"
            or contract.get("event_query_scope") != QUERY_SCOPE
            or contract.get("event_identity_conditioning") not in (TRANSPORT_CONDITION, "UNCONFIRMED")
            or contract.get("action_schema_basis") not in (ARCHIVE_SCHEMA, "UNCONFIRMED")
            or contract.get("start_inclusive") != "2020-01-01"
            or contract.get("cutoff_exclusive") != "2026-01-01"):
        raise RuntimeError("COVERAGE_CONTRACT_NOT_FROZEN")
    pins = {str(Path(contract_path).resolve()): sha(contract_path),
            str(Path(__file__).resolve()): contract["runner_source_sha256"],
            str(Path(bindings_path).resolve()): contract["bindings_sha256"]}
    paths = {}
    for name, filename in MODULE_FILES.items():
        item = contract["modules"][name]
        path = Path(item.get("path", MODULE_DIR / filename)).resolve()
        paths[name] = path
        pins[str(path)] = item["sha256"]
    if contract["reader_source_sha256"] != contract["modules"]["inputs"]["sha256"]:
        raise RuntimeError("READER_HASH_CONTRACT_CONFLICT")
    for name in ("rehab_status", "sdk_schema", "original_ingest_source"):
        item = contract[name]
        pins[str(Path(item["path"]).resolve())] = item["sha256"]
    for item in contract.get("evidence", {}).values():
        pins[str(Path(item["path"]).resolve())] = item["sha256"]
    verify_pins(pins)  # No module import or table body access precedes this.
    modules = {}
    for name, path in paths.items():
        spec = importlib.util.spec_from_file_location(f"frozen_economic_{name}", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        modules[name] = module
    return contract, pins, modules


def event_evidence(events, bindings, query_status, contract, features):
    all_bindings = [*bindings["equities"], bindings["QQQ"]]
    mapping = {item["moomoo_transport_code"]: item["ticker"] for item in all_bindings}
    if len(mapping) != len(all_bindings) or len(set(mapping.values())) != len(mapping):
        raise RuntimeError("AMBIGUOUS_TRANSPORT_BINDING")
    if not {"code", "status", "row_count"}.issubset(query_status) or query_status.code.duplicated().any():
        raise RuntimeError("INVALID_QUERY_STATUS_SCHEMA")
    if not set(events.code).issubset(mapping):
        raise RuntimeError("EVENT_TRANSPORT_NOT_BOUND")
    source, sdk = bindings["rehab"], contract["sdk_schema"]
    original_columns = set(events.columns)
    complete = (contract["action_schema_basis"] == ARCHIVE_SCHEMA
                and set(features.ACTION_FIELDS).issubset(original_columns))
    conditional = contract["event_identity_conditioning"] == TRANSPORT_CONDITION
    prepared = events.copy()
    prepared["ticker"] = prepared.code.map(mapping)
    prepared["source_type"] = "PINNED_VENDOR_REHAB_ARCHIVE"
    prepared["source_reference"], prepared["source_fingerprint"] = source["path"], source["sha256"]
    prepared["sdk_schema_fingerprint"] = sdk["sha256"]
    prepared["action_fields_complete"] = complete
    # Explicit conditional analysis of the attested transport mapping only.
    # Strict economic identity remains false on EVERY returned observation.
    prepared["identity_unchanged"] = conditional
    prepared["cash_unit_basis"] = "UNCONFIRMED"
    prepared["cash_unit_source_reference"] = ""
    prepared["cash_unit_source_fingerprint"] = ""
    classified = features.classify_vendor_events(prepared)
    status = query_status.set_index("code")
    counts = events.groupby("code").size()
    coverage = []
    for code, ticker in mapping.items():
        passed = False
        if code in status.index:
            row = status.loc[code]
            number = pd.to_numeric(pd.Series([row.row_count]), errors="coerce").iloc[0]
            passed = (row.status == "PASS" and np.isfinite(number) and number >= 0
                      and number == int(number) and int(number) >= int(counts.get(code, 0)))
            if "error" in row.index and str(row.error).strip():
                passed = False
        coverage.append({"ticker": ticker, "coverage_start": contract["start_inclusive"],
                         "coverage_end": "2025-12-31", "complete": bool(passed),
                         "source_reference": contract["rehab_status"]["path"] + " | " + source["path"],
                         "source_fingerprint": contract["rehab_status"]["sha256"] + ":" + source["sha256"]})
    evidence = {"archive_action_columns_complete": complete,
                "action_schema_basis": contract["action_schema_basis"],
                "historical_sdk_version_certified": False,
                "event_identity_conditioning": contract["event_identity_conditioning"],
                "economic_identity_certified": False, "cash_unit_evidence_available": False,
                "query_scope": contract["event_query_scope"],
                "complete_query_codes": sum(row["complete"] for row in coverage),
                "query_row_count_check": "PRE2026_ARCHIVE_COUNT_LE_CAPTURED_FULL_QUERY_COUNT"}
    return classified, pd.DataFrame(coverage), evidence


def boolean_lookbacks(panel, returns, calendar):
    """Availability only: never OLS, R2, MAX, variance or skewness."""
    wide = returns.pivot(index="trade_date", columns="ticker", values="return_valid").reindex(calendar).fillna(False).astype(bool)
    current = returns.pivot(index="trade_date", columns="ticker", values="current_close_available").reindex(calendar).fillna(False).astype(bool)
    market_pairs = pd.concat([wide.QQQ.shift(lag, fill_value=False) for lag in range(6)], axis=1).all(axis=1)
    paired = wide.drop(columns="QQQ").mul(market_pairs, axis=0).astype(bool)
    counts = paired.rolling(126, min_periods=1).sum().shift(21).fillna(0).astype(int)
    rows, cols = calendar.get_indexer(panel.signal_date), counts.columns.get_indexer(panel.ticker)
    available_now = current.reindex(columns=counts.columns).to_numpy()[rows, cols] & current.QQQ.to_numpy()[rows]
    count_values = counts.to_numpy()[rows, cols]
    out = panel[["signal_date", "ticker"]].copy()
    out["delay_stale_paired_count"] = count_values
    out["delay_potential_window_support"] = (count_values >= 100) & available_now
    periods = calendar.to_period("M")
    expected = pd.Series(1, index=calendar).groupby(periods).sum()
    month_valid = wide.groupby(periods).sum()
    month_end = pd.Series(calendar, index=calendar).groupby(periods).max()
    next_session = pd.Series(calendar, index=calendar).shift(-1)
    measurement = next_session.dt.to_period("M") - 1
    expected_values = measurement.map(expected).fillna(0).to_numpy()[rows]
    valid_month = month_valid.reindex(pd.PeriodIndex(measurement, freq="M"))
    valid_values = valid_month.reindex(columns=counts.columns).fillna(0).to_numpy()[rows, cols]
    ended = measurement.map(month_end).le(pd.Series(calendar, index=calendar)).to_numpy()[rows]
    out["max_month_expected_sessions"] = expected_values.astype(int)
    out["max_month_valid_sessions"] = valid_values.astype(int)
    out["max_potential_month_support"] = ((expected_values > 0) & (valid_values == expected_values) & ended
                                            & current.reindex(columns=counts.columns).to_numpy()[rows, cols])
    return out


def stage_coverage(raw, events, panel, calendar, bindings, query_status, contract, features, targets):
    original_hash = validate_cohort(panel, contract["cohort"])
    classified, query_coverage, evidence = event_evidence(events, bindings, query_status, contract, features)
    if "economic_security_id" in raw:
        raise RuntimeError("THIS_PREFLIGHT_HAS_NO_DATED_IDENTITY_SOURCE")
    returns = features.build_accrual_returns(raw, classified, calendar, event_coverage=query_coverage)
    if returns.identity_continuity_certified.any():
        raise RuntimeError("UNEXPECTED_IDENTITY_CERTIFICATION")
    keys = panel[["signal_date", "ticker", "target_end_date"]].copy()
    coverage = targets.attach_economic_targets(keys, returns, calendar, return_column="daily_gross_return",
        expected_names_per_date=contract["cohort"]["names_per_date"], compute_values=False)
    if coverage.target.notna().any() or any(f"economic_stock_return_{h}d" in coverage for h in targets.HORIZONS):
        raise RuntimeError("FORBIDDEN_TARGET_VALUES")
    coverage = coverage.drop(columns="target").rename(columns={"target_valid": "transport_target_valid",
        "target_universe_complete": "transport_target_universe_complete"})
    coverage["strict_target_valid"] = False
    coverage["strict_target_universe_complete"] = False
    coverage["strict_identity_status"] = "UNCONFIRMED_DATED_ECONOMIC_IDENTITY"
    lookbacks = boolean_lookbacks(keys, returns, calendar)
    for column in lookbacks.columns.difference(["signal_date", "ticker"]):
        coverage[column] = lookbacks[column].to_numpy()
    if not coverage[["signal_date", "ticker"]].equals(panel[["signal_date", "ticker"]]):
        raise RuntimeError("COHORT_ORDER_OR_KEYS_CHANGED")
    validate_cohort(coverage, contract["cohort"])
    by_year = []
    for year, group in coverage.groupby(coverage.signal_date.dt.year):
        by_year.append({"year": int(year), "rows": len(group), "dates": group.signal_date.nunique(),
            "transport_valid_label_rows": int(group.transport_target_valid.sum()),
            "transport_complete_dates": group.loc[group.transport_target_universe_complete, "signal_date"].nunique(),
            "strict_valid_label_rows": 0, "strict_complete_dates": 0,
            "delay_potential_window_rows": int(group.delay_potential_window_support.sum()),
            "max_potential_month_rows": int(group.max_potential_month_support.sum())})
    summary = {"status": "DATA_CONTRACT_INCOMPLETE_IDENTITY_UNCONFIRMED", "phase": "COVERAGE_ONLY",
        "model_admission": "BLOCKED", "cohort": {**contract["cohort"], "observed_key_sha256": original_hash},
        "transport_valid_label_rows": int(coverage.transport_target_valid.sum()),
        "transport_complete_dates": coverage.loc[coverage.transport_target_universe_complete, "signal_date"].nunique(),
        "strict_valid_label_rows": 0, "strict_complete_dates": 0, "by_year": by_year,
        "event_status_counts": classified.event_status.value_counts().to_dict(),
        "daily_return_status_counts": returns.return_status.value_counts().to_dict(),
        "identity_status_counts": returns.identity_status.value_counts().to_dict(), "evidence": evidence,
        "post2025_row_values_materialized": 0, "numeric_targets_computed": 0, "actual_factors_computed": 0,
        "fits_added": 0, "candidate_comparisons_added": 0, "campaign_predictive_fits": 12,
        "campaign_candidate_comparisons": 3, "delay_rank_and_r2_gates": "NOT_EVALUATED",
        "limitations": ["Retrospective vendor archive; historical publication-PIT not certified",
            "No cash unit/currency evidence attached; cash events remain unsupported",
            "Transport-conditioned split/no-event arithmetic is not dated economic identity certification",
            "Boolean lookback support is not valid factor, alpha, broker cash or portfolio performance"]}
    return coverage, summary


def run(contract_path, bindings_path, results_dir, cache_dir):
    destinations = [Path(results_dir) / "coverage_summary.json", Path(results_dir) / "coverage_lineage.json",
                    Path(cache_dir) / "coverage_masks.parquet"]
    if any(path.exists() for path in destinations):
        raise RuntimeError("PREFLIGHT_OUTPUT_ALREADY_EXISTS")
    contract, pins, modules = frozen_setup(contract_path, bindings_path)
    query_status = pd.read_csv(contract["rehab_status"]["path"], keep_default_na=False,
                               dtype={"code": str, "status": str})
    raw, events, panel, calendar, lineage = modules["inputs"].load_economic_return_inputs(
        contract_path=Path(contract_path), bindings_path=Path(bindings_path))
    bindings = json.loads(Path(bindings_path).read_text(encoding="utf-8"))
    coverage, summary = stage_coverage(raw, events, panel, calendar, bindings, query_status,
                                      contract, modules["features"], modules["targets"])
    pins.update(lineage["source_and_input_hashes"])
    verify_pins(pins)
    lineage = {"raw_input_lineage": lineage, "preflight_pins": pins, "post_processing_hashes_match": True,
               "coverage_runner_source": str(Path(__file__).resolve()), "numeric_bodies_persisted": False,
               "output_columns": list(coverage.columns)}
    for path in destinations:
        path.parent.mkdir(parents=True, exist_ok=True)
    coverage.to_parquet(destinations[2], index=False)
    summary["coverage_masks_sha256"] = sha(destinations[2])
    for path, content in zip(destinations[:2], (summary, lineage)):
        path.write_text(json.dumps(content, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.contract, args.bindings, args.results_dir, args.cache_dir)
    print(json.dumps({key: result[key] for key in ("status", "transport_valid_label_rows", "strict_valid_label_rows", "fits_added")}))
