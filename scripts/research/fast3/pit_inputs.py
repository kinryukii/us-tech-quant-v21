"""Small read-only adapter for the bounded FAST3 stock study; no prices or scores.

The source bridge's old legal-date grid starts in 2023. Earlier mappings are
replayed from its sealed, header-verified name evidence and actual acceptance
timestamps, never by backfilling the materialized 2023 bridge. Missing optional
sources remain local exclusions. This file neither fetches nor fits anything.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

ROOT = Path("D:/us-tech-quant-results")
FOUNDATION = ROOT / "A2_FREE_PIT_SECURITY_IDENTITY_SIC_FF48_AND_FACTOR_RISK_FOUNDATION_R1"
UNIVERSE = ROOT / "A2_PIT13F_MATERIALIZATION_R1"
STATES = Path("D:/us-tech-quant-data/sec/recovery_20260913/historical/fundamental_feature_states.parquet")
STATES_MANIFEST = Path("D:/us-tech-quant-cache/sec_fundamental_pit_r1/derived_bulk_resume/fundamental_feature_states_manifest.json")
CALENDAR = Path("D:/us-tech-quant-data/reference/trading_calendar/XNYS/versions/xnys_sessions_f61c8f8d47cd94ae4b75.parquet")
NORMALIZER = Path(__file__).resolve().parents[1] / "a2/data/a2_free_pit_foundation_r1.py"
CUTOFF = pd.Timestamp("2026-01-01", tz="UTC")
ET = "America/New_York"
FUNDAMENTAL_FIELDS = (
    "revenue_yoy", "gross_margin", "operating_margin", "net_margin",
    "operating_cash_flow_margin", "free_cash_flow_margin", "accrual_quality",
    "asset_growth_yoy", "rd_to_revenue", "sbc_to_revenue", "filing_lag_days",
    "amendment_indicator", "fact_coverage_ratio",
)
FEATURE_COLUMNS = ["pit_institution_support_count", "pit_is_sic3674", *["pit_" + x for x in FUNDAMENTAL_FIELDS]]
SECTOR_COLUMN = "pit_sic4"
HASHES = {
    "final_manifest.json": "b1bc56359934b8632cbbf4eafbdddfe2d2f1f12b8c3703c799e664fce821bddc",
    "source_hash_manifest.json": "d9f3032b4c154ebd62e88291a36e6a4f1d2d1680b6f3d95ccc4675813afcfd73",
    "materialization_status.json": "8f0747322d8f313ed5d7ae63dbd3f8ba3fcbdb8919c9d0c29364262be38c93ff",
    "effective_universe_intervals.parquet": "cafd53e665143e56d31c3f7b5299593a099fc53a0032879d63fbd8abae6a0d30",
    "pit_sec_sic_ff12_ff48_eligible_surface.parquet": "591ecea001bf1f0b1b6ef7059a65b7e6efd45890befa149c0377d45b6aad6646",
    "security_identity_bridge.parquet": "439c9bfa1d92915f3c3a2fe7320d88f8db16e5fe1aacba6cb5f8720635641866",
    "sec_identity_evidence.parquet": "1f02ccbfd9fad7344445942e130c50af09cdaa2b5997b44def1658a2a0b45634",
    "sec_as_filed_sic_events.parquet": "1b50135121476a574a66b2331cc90e346e5d47232aec5df897a67e246a79a4fb",
    "fundamental_feature_states.parquet": "f080a4d4f54c7cded7c7149fb70481ed548bb5e93aed17675fab4ab76bb03eb6",
    "fundamental_feature_states_manifest.json": "f040d78c07762d3588c0dfd41cc599d5dcf14f0ddff6d7f6e62d3a80f56dd805",
    "a2_free_pit_foundation_r1.py": "420b0c049814d5e3475e47bc20bd5fe2a1466424651879c305f9d26d31727782",
    CALENDAR.name: "f61c8f8d47cd94ae4b75eab51566917bd809abd2afe8b280858fb04ba36e93e4",
}


class SourceContractError(ValueError):
    pass


def _verified(path: Path, manifest: dict) -> str:
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != HASHES[path.name]:
        raise SourceContractError("SOURCE_HASH_CHANGED:" + str(path))
    manifest["sources"][str(path)] = {"sha256": digest}
    return digest


def _json(path: Path, manifest: dict) -> dict:
    _verified(path, manifest)
    return json.loads(path.read_text(encoding="utf-8"))


def _read(path: Path, columns: list[str], date_column: str, manifest: dict) -> pd.DataFrame:
    """Predicate is passed to Arrow before materializing any source rows."""
    _verified(path, manifest)
    dataset = ds.dataset(path, format="parquet")
    missing = set(columns).difference(dataset.schema.names)
    if missing:
        raise SourceContractError("MISSING_FIELDS:" + ",".join(sorted(missing)))
    kind = dataset.schema.field(date_column).type
    if pa.types.is_string(kind) or pa.types.is_large_string(kind):
        boundary = pa.scalar("2026-01-01", type=kind)
    else:
        value = CUTOFF.to_pydatetime() if getattr(kind, "tz", None) else CUTOFF.tz_localize(None).to_pydatetime()
        boundary = pa.scalar(value, type=kind)
    frame = dataset.to_table(columns=columns, filter=ds.field(date_column) < boundary).to_pandas()
    manifest["sources"][str(path)].update({"columns": columns, "filter": date_column + " < 2026-01-01", "read_rows": len(frame)})
    return frame


def _foundation_contract(manifest: dict) -> dict:
    frozen = _json(FOUNDATION / "final_manifest.json", manifest)
    if frozen.get("status") != "PASS":
        raise SourceContractError("FOUNDATION_NOT_ACCEPTED")
    for name in ("sec_identity_evidence.parquet", "sec_as_filed_sic_events.parquet"):
        if frozen["files"][name]["sha256"] != HASHES[name]:
            raise SourceContractError("FOUNDATION_ACCEPTANCE_HASH_MISMATCH:" + name)
    return frozen


def _normalizer(manifest: dict, frozen: dict):
    """Reuse only the sealed pure name function, without importing its runner."""
    digest = _verified(NORMALIZER, manifest)
    if frozen["runner_sha256"] != digest:
        raise SourceContractError("NORMALIZER_NOT_SEALED")
    names = {"TOKEN_EXPANSIONS", "LEGAL_SUFFIXES", "TRAILING_JURISDICTIONS", "identity_name_key"}
    source = ast.parse(NORMALIZER.read_text(encoding="utf-8"))
    nodes = [node for node in source.body if (isinstance(node, ast.FunctionDef) and node.name in names) or
             (isinstance(node, ast.Assign) and any(isinstance(x, ast.Name) and x.id in names for x in node.targets))]
    if len(nodes) != 4:
        raise SourceContractError("NORMALIZER_DEFINITIONS_CHANGED")
    namespace = {"re": re, "Any": Any}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(NORMALIZER), "exec"), namespace)
    return namespace["identity_name_key"]


def _load_intervals(manifest: dict) -> pd.DataFrame:
    hashes = _json(UNIVERSE / "source_hash_manifest.json", manifest)
    status = _json(UNIVERSE / "materialization_status.json", manifest)
    if status.get("A2_PIT13F_MATERIALIZATION_R1_STATUS") != "PASS" or not status.get("AUTHORITATIVE_PIT_13F_UNIVERSE_FROZEN"):
        raise SourceContractError("UNIVERSE_NOT_ACCEPTED")
    ref = next(x for x in hashes["outputs"] if Path(x["path"]).name == "effective_universe_intervals.parquet")
    if ref["sha256"] != HASHES["effective_universe_intervals.parquet"]:
        raise SourceContractError("UNIVERSE_ACCEPTANCE_HASH_MISMATCH")
    return _read(UNIVERSE / "effective_universe_intervals.parquet", [
        "effective_start", "effective_end", "security_id", "cusip", "ticker", "issuer_name",
        "mapping_status", "institution_support_count", "artifact_label",
    ], "effective_start", manifest)


def _load_states(manifest: dict) -> pd.DataFrame:
    receipt = _json(STATES_MANIFEST, manifest)
    lineage = receipt.get("lineage_facts", {})
    if (receipt.get("state_sha256") != HASHES[STATES.name] or
            receipt.get("status") != "PASS_HASH_VALID_DURABLE_PREFIT_CHECKPOINT" or
            lineage.get("restatement_guard_status") != "PASS_ACCESSION_ASOF_NO_BACKFILL" or
            lineage.get("pit_effective_date_status") != "PASS_STRICT_NEXT_NYSE_SESSION"):
        raise SourceContractError("FUNDAMENTAL_CHECKPOINT_NOT_CERTIFIED")
    return _read(STATES, ["cik", "accession", "accepted_datetime", "feature_effective_date",
                          "lineage_hash", "accepted_source_sha256", *FUNDAMENTAL_FIELDS], "feature_effective_date", manifest)


def _validate_samples(samples: pd.DataFrame) -> pd.DataFrame:
    required = {"ticker", "date", "prediction_at_utc"}
    if not required.issubset(samples.columns):
        raise ValueError("SAMPLES_REQUIRE_TICKER_DATE_PREDICTION_TIMESTAMP")
    out = samples.copy().reset_index(drop=True)
    out["_pit_date"] = pd.to_datetime(out.date, errors="raise").dt.normalize()
    out["_pit_prediction"] = pd.to_datetime(out.prediction_at_utc, utc=True, errors="raise")
    local = out._pit_prediction.dt.tz_convert(ET)
    if (out._pit_date.isna().any() or out._pit_prediction.isna().any() or
            out._pit_prediction.ge(CUTOFF).any() or out._pit_date.ge(pd.Timestamp("2026-01-01")).any()):
        raise ValueError("PRE2026_NON_NULL_SAMPLE_BOUNDARY_REQUIRED")
    if not (local.dt.hour.eq(9) & local.dt.minute.eq(25) & local.dt.second.eq(0) &
            local.dt.tz_localize(None).dt.normalize().eq(out._pit_date)).all():
        raise ValueError("PREDICTION_MUST_BE_0925_NEW_YORK_ON_SAMPLE_DATE")
    if out.duplicated(["ticker", "_pit_date"]).any():
        raise ValueError("DUPLICATE_TICKER_DATE")
    return out


def _later_full_day(available: pd.Series) -> pd.Series:
    local = pd.to_datetime(available, utc=True).dt.tz_convert(ET).dt.tz_localize(None).dt.normalize()
    return (local + pd.Timedelta(days=1)).dt.tz_localize(ET).dt.tz_convert("UTC")


def _enrich(samples, intervals, evidence, events, states, name_key) -> pd.DataFrame:
    out = _validate_samples(samples)
    for column in FEATURE_COLUMNS + ["pit_sic4", "pit_cik"]:
        out[column] = np.nan
    for column in ["pit_security_id", "pit_identity_accession", "pit_sec_accession", "pit_sec_lineage_hash"]:
        out[column] = pd.Series(None, index=out.index, dtype="object")
    for column in ["pit_identity_available_at", "pit_sic_available_at", "pit_sec_available_at"]:
        out[column] = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns, UTC]")
    out["pit_eligible"] = False
    out["pit_eligibility_reason"] = "NO_HISTORICAL_QUALIFICATION"
    issuer_keys = pd.Series("", index=out.index)
    counts = np.zeros(len(out), dtype=int)
    if intervals is not None:
        for row in intervals.loc[intervals.ticker.isin(out.ticker.unique())].itertuples():
            mask = out.ticker.eq(row.ticker) & out._pit_date.between(pd.Timestamp(row.effective_start), pd.Timestamp(row.effective_end))
            if not mask.any():
                continue
            counts[mask] += 1
            if row.mapping_status != "RESOLVED" or str(row.security_id) != str(row.cusip) or row.artifact_label != "AUTHORITATIVE_PIT_INVESTABLE_UNIVERSE":
                continue
            out.loc[mask, "pit_eligible"] = True
            out.loc[mask, "pit_eligibility_reason"] = "HISTORICAL_13F_INTERVAL"
            out.loc[mask, "pit_security_id"] = str(row.security_id)
            out.loc[mask, "pit_institution_support_count"] = float(row.institution_support_count)
            if name_key is not None:
                issuer_keys.loc[mask] = name_key(row.issuer_name)
        ambiguous = counts > 1
        out.loc[ambiguous, "pit_eligible"] = False
        out.loc[ambiguous, "pit_eligibility_reason"] = "AMBIGUOUS_HISTORICAL_INTERVAL"
        out.loc[ambiguous, "pit_institution_support_count"] = np.nan
        issuer_keys.loc[ambiguous] = ""
    else:
        out["pit_eligibility_reason"] = "QUALIFICATION_SOURCE_UNVERIFIED"
    if evidence is not None:
        evidence = evidence.copy()
        evidence["_available"] = pd.to_datetime(evidence.accepted_timestamp_utc, utc=True) + pd.Timedelta(minutes=5)
        evidence["_usable"] = _later_full_day(evidence._available)
        for key in issuer_keys.loc[issuer_keys.ne("")].unique():
            group = evidence.loc[evidence.identity_name_key.eq(key)].sort_values(["_available", "adsh"])
            timeline = []
            for usable in group._usable.dropna().drop_duplicates():
                known = group.loc[group._usable.le(usable)]
                chosen = known.iloc[0]
                unique = known.cik.nunique() == 1
                timeline.append({"_usable": usable, "pit_cik": float(chosen.cik) if unique else np.nan,
                                 "pit_identity_accession": chosen.adsh if unique else None,
                                 "pit_identity_available_at": chosen._usable if unique else pd.NaT})
            if not timeline:
                continue
            indices = out.index[issuer_keys.eq(key) & out.pit_eligible]
            left = out.loc[indices, ["_pit_prediction"]].assign(_row=indices).sort_values("_pit_prediction")
            joined = pd.merge_asof(left, pd.DataFrame(timeline).sort_values("_usable"),
                                   left_on="_pit_prediction", right_on="_usable", direction="backward").set_index("_row")
            for column in ("pit_cik", "pit_identity_accession", "pit_identity_available_at"):
                out.loc[joined.index, column] = joined[column]
    if events is not None:
        events = events.copy()
        events["_available"] = pd.to_datetime(events.sic_available_at, utc=True)
        events["_usable"] = _later_full_day(events._available)
        for cik, indices in out.loc[out.pit_cik.notna()].groupby("pit_cik").groups.items():
            group = events.loc[events.cik.eq(cik)].sort_values(["_available", "accession_number"])
            timeline = []
            for available, simultaneous in group.groupby("_available", sort=True):
                chosen = simultaneous.iloc[-1]
                unique = simultaneous.assigned_sic.nunique() == 1
                timeline.append({"_usable": chosen._usable, "pit_sic4": float(chosen.assigned_sic) if unique else np.nan,
                                 "pit_sic_available_at": chosen._usable if unique else pd.NaT})
            if not timeline:
                continue
            right = pd.DataFrame(timeline).drop_duplicates("_usable", keep="last").sort_values("_usable")
            left = out.loc[indices, ["_pit_prediction"]].assign(_row=indices).sort_values("_pit_prediction")
            joined = pd.merge_asof(left, right, left_on="_pit_prediction", right_on="_usable", direction="backward").set_index("_row")
            for column in ("pit_sic4", "pit_sic_available_at"):
                out.loc[joined.index, column] = joined[column]
        out["pit_is_sic3674"] = out.pit_sic4.eq(3674).astype(float).where(out.pit_sic4.notna())
    if states is not None:
        states = states.copy()
        accepted = pd.to_datetime(states.accepted_datetime, utc=True)
        effective = pd.to_datetime(states.feature_effective_date).dt.normalize().dt.tz_localize(ET).dt.tz_convert("UTC")
        legal = accepted.lt(CUTOFF) & accepted.notna() & effective.notna() & states.lineage_hash.notna() & states.accepted_source_sha256.notna()
        states = states.loc[legal].copy()
        states["_available"] = pd.concat([accepted[legal], effective[legal]], axis=1).max(axis=1)
        for cik, indices in out.loc[out.pit_cik.notna()].groupby("pit_cik").groups.items():
            right = states.loc[states.cik.eq(cik)].sort_values(["_available", "accepted_datetime", "accession"]).drop_duplicates("_available", keep="last")
            if right.empty:
                continue
            left = out.loc[indices, ["_pit_prediction"]].assign(_row=indices).sort_values("_pit_prediction")
            merged = pd.merge_asof(left, right, left_on="_pit_prediction", right_on="_available", direction="backward")
            merged = merged.set_index("_row")
            for field in FUNDAMENTAL_FIELDS:
                out.loc[merged.index, "pit_" + field] = pd.to_numeric(merged[field], errors="coerce").replace([np.inf, -np.inf], np.nan)
            out.loc[merged.index, "pit_sec_available_at"] = merged["_available"]
            out.loc[merged.index, "pit_sec_accession"] = merged.accession
            out.loc[merged.index, "pit_sec_lineage_hash"] = merged.lineage_hash
    out["eligible"] = out.pit_eligible & out.pit_cik.notna() & out.pit_sic4.eq(3674)
    out["eligibility_reason"] = np.select(
        [~out.pit_eligible, out.pit_cik.isna(), out.pit_sic4.isna(), ~out.pit_sic4.eq(3674)],
        [out.pit_eligibility_reason, "NO_UNIQUE_ASOF_VERIFIED_ISSUER", "NO_ASOF_VERIFIED_SIC", "ASOF_SIC_NOT_3674"],
        default="HISTORICAL_13F_AND_ASOF_VERIFIED_SIC3674",
    )
    out["sector"] = out.pit_sic4.map(lambda x: "UNKNOWN" if pd.isna(x) else "SIC" + str(int(x)))
    return out.drop(columns=["_pit_date", "_pit_prediction"])


def add_pit_features(samples: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Preserve all sample rows. Imputation/scaling belong to model train folds."""
    _validate_samples(samples)
    manifest = {"sources": {}, "exclusions": [], "feature_columns": FEATURE_COLUMNS, "features": FEATURE_COLUMNS,
                "baseline_columns": ["pit_institution_support_count", "pit_is_sic3674"],
                "sector_column": SECTOR_COLUMN, "prediction_time": "09:25 America/New_York",
                "cutoff_exclusive": CUTOFF.isoformat(), "supervised_fit_count": 0,
                "identity_method": "SEALED_AS_FILED_NAME_EVIDENCE_UNIQUE_CIK_ASOF_WITH_CURRENT_HISTORICAL_CUSIP_INTERVAL",
                "availability_rules": {
                    "identity_and_sic": "accepted plus 5 minutes, strictly later New York calendar date, evaluated only on supplied trading sessions",
                    "fundamentals": "max(actual accepted timestamp, certified strict-next-NYSE-session feature_effective_date at New York midnight), backward asof at prediction timestamp",
                    "institutional_universe": "sealed effective_start/effective_end from historical public filing intervals; no current holdings backfill"},
                "old_2023_grid": "Old first_available_session/usable_decision_session are not backfilled; actual sealed acceptance timestamps are replayed."}
    def optional(label, call):
        try:
            return call()
        except (OSError, ValueError, KeyError, StopIteration) as error:
            manifest["exclusions"].append({"component": label, "reason": type(error).__name__ + ":" + str(error)})
            return None
    intervals = optional("historical_eligibility_and_institutional", lambda: _load_intervals(manifest))
    frozen = optional("foundation_acceptance", lambda: _foundation_contract(manifest))
    normalizer = optional("historical_name_function", lambda: _normalizer(manifest, frozen)) if frozen else None
    evidence = optional("sec_identity", lambda: _read(FOUNDATION / "sec_identity_evidence.parquet", [
        "cik", "identity_name_key", "accepted_timestamp_utc", "adsh", "name_role"], "accepted_timestamp_utc", manifest)) if normalizer else None
    events = optional("as_filed_sic", lambda: _read(FOUNDATION / "sec_as_filed_sic_events.parquet", [
        "cik", "assigned_sic", "sic_available_at", "acceptance_datetime", "accession_number"], "sic_available_at", manifest)) if frozen else None
    states = optional("sec_fundamentals", lambda: _load_states(manifest))
    enriched = _enrich(samples, intervals, evidence, events, states, normalizer)
    manifest["coverage"] = {"sample_rows": len(enriched), "historically_eligible_rows": int(enriched.pit_eligible.sum()),
                            "strict_semiconductor_eligible_rows": int(enriched.eligible.sum()),
                            "identity_rows": int(enriched.pit_cik.notna().sum()), "sic_rows": int(enriched.pit_sic4.notna().sum()),
                            "fundamental_rows": int(enriched.pit_sec_accession.notna().sum()),
                            "missing_by_feature": enriched[FEATURE_COLUMNS].isna().sum().to_dict()}
    return enriched, manifest


def universe_download_plan() -> dict:
    """Derive the union from ALL historical intervals and actual as-of evidence.

    A later daily surface is never a stock selector. The pre-screen below only
    avoids a multi-million-row Cartesian product: actual inclusion still needs
    a unique issuer and SIC3674 event available within a historical interval.
    """
    manifest = {"sources": {}}
    frozen = _foundation_contract(manifest)
    name_key = _normalizer(manifest, frozen)
    intervals = _load_intervals(manifest)
    evidence = _read(FOUNDATION / "sec_identity_evidence.parquet", [
        "cik", "identity_name_key", "accepted_timestamp_utc", "adsh", "name_role"], "accepted_timestamp_utc", manifest)
    events = _read(FOUNDATION / "sec_as_filed_sic_events.parquet", [
        "cik", "assigned_sic", "sic_available_at", "acceptance_datetime", "accession_number"], "sic_available_at", manifest)
    intervals["_name_key"] = intervals.issuer_name.map(name_key)
    semiconductor_ciks = set(events.loc[events.assigned_sic.eq(3674), "cik"])
    potential_keys = set(evidence.loc[evidence.cik.isin(semiconductor_ciks), "identity_name_key"])
    potential_intervals = intervals.loc[intervals._name_key.isin(potential_keys)]
    potential_symbols = sorted(potential_intervals.ticker.unique())
    calendar = _read(CALENDAR, ["trade_date", "is_session"], "trade_date", manifest)
    days = pd.to_datetime(calendar.loc[calendar.is_session, "trade_date"])
    days = days[days.ge(pd.Timestamp("2020-05-22"))]
    grid = pd.MultiIndex.from_product([potential_symbols, days], names=["ticker", "date"]).to_frame(index=False)
    grid["prediction_at_utc"] = (grid.date + pd.Timedelta(hours=9, minutes=25)).dt.tz_localize(ET).dt.tz_convert("UTC")
    qualified = _enrich(grid, intervals, evidence, events, None, name_key)
    keys = qualified.loc[qualified.eligible, ["ticker", "date", "pit_security_id"]].copy()
    keys["date"] = keys.date.dt.strftime("%Y-%m-%d")
    keys = keys.sort_values(["date", "ticker"]).reset_index(drop=True)
    selected = sorted(keys.ticker.unique())
    rows = []
    for ticker in selected:
        own = intervals.loc[intervals.ticker.eq(ticker)].sort_values("effective_start")
        key = keys.loc[keys.ticker.eq(ticker)]
        rows.append({"ticker": ticker, "download_start": str(own.effective_start.min().date()), "download_end": "2025-12-31",
                     "first_sic_qualified_date": key.date.min(), "last_sic_qualified_date": key.date.max(),
                     "qualified_days": len(key),
                     "historical_intervals": [{"start": str(r.effective_start.date()), "end": str(min(r.effective_end, pd.Timestamp("2025-12-31")).date()), "security_id": r.security_id} for r in own.itertuples()]})
    reviewed = intervals[["ticker", "security_id", "effective_start", "effective_end"]].copy()
    reviewed["review_status"] = np.select(
        [~intervals._name_key.isin(set(evidence.identity_name_key)), intervals._name_key.isin(potential_keys)],
        ["NO_PRE2026_VERIFIED_NAME_EVIDENCE", "CANDIDATE_REPLAYED_DATE_BY_DATE"],
        default="NO_PRE2026_VERIFIED_SIC3674_EVENT_FOR_NAME",
    )
    for column in ("effective_start", "effective_end"):
        reviewed[column] = pd.to_datetime(reviewed[column]).clip(upper=pd.Timestamp("2025-12-31")).dt.strftime("%Y-%m-%d")
    review_csv = reviewed.sort_values(["effective_start", "ticker", "security_id"]).to_csv(index=False, lineterminator="\n")
    serialized = keys.to_csv(index=False, lineterminator="\n")
    manifest["coverage"] = {"all_historical_intervals": len(intervals), "all_historical_tickers": int(intervals.ticker.nunique()),
                            "source_interval_review_counts": reviewed.review_status.value_counts().to_dict(),
                            "potential_replay_symbols": potential_symbols, "potential_replay_rows": len(qualified),
                            "qualified_rows": len(keys), "qualified_symbols": len(selected),
                            "not_qualified_reasons": qualified.loc[~qualified.eligible, "eligibility_reason"].value_counts().to_dict()}
    return {"selection_rule": "ALL pre2026 historical 13F intervals intersected with contemporaneously unique verified issuer and SIC3674; no later surface selection, outcomes, options ranking, or future completeness selection",
            "explicit_user_named_symbol": "NVDA", "other_symbols_origin": "AGENT_PROPOSED_HISTORICAL_ASOF_RULE",
            "symbols": selected, "tickers": selected, "alltickers": selected, "members": rows,
            "qualification_keys": keys.to_dict("records"), "qualification_keys_csv_sha256": hashlib.sha256(serialized.encode()).hexdigest(),
            "historical_interval_review": reviewed.to_dict("records"), "historical_interval_review_csv_sha256": hashlib.sha256(review_csv.encode()).hexdigest(),
            "source_manifest": manifest, "pit_source_manifest": manifest,
            "unresolved_scope": "No verified name/SIC evidence remains unclassified rather than inferred from current industry. This is the certifiable local-data universe, not every historical semiconductor security.",
            "prior_initial_audit": "The earlier 13776 count used a later materialized surface as a pre-screen; it was an unfrozen preliminary audit with zero fits or candidate comparisons. This plan recomputes from all historical intervals."}
