"""Generic, source-gated point-in-time Form 13F universe primitives.

This module owns no network client and no manager-specific logic.  It consumes
SEC-derived records keyed by CIK and accession and fails closed on incomplete
timestamps, identity, amendment semantics, or unsupported instruments.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

ET = "America/New_York"
ALLOWED_FORMS = frozenset({"13F-HR", "13F-HR/A"})
ELIGIBLE_INSTRUMENTS = frozenset({"COMMON_STOCK", "ADR_ADS"})
CAP_FORBIDDEN_COLUMNS = frozenset({
    "a1_score", "a2_score", "a1_raw_score", "a2_prediction", "raw_score",
    "target", "outcome", "future_return", "pnl", "sharpe", "volatility",
})
AUTHORITATIVE_MANAGER_COUNT = 24
AUTHORITATIVE_TOP_N = 100
AUTHORITATIVE_UNIVERSE_CAP = 900
SITUATIONAL_AWARENESS_CIK = "0002025719"


class Pit13FContractError(RuntimeError):
    """A fail-closed PIT 13F contract violation."""


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def normalized_cik(value: Any) -> str:
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if not digits or len(digits) > 10:
        raise Pit13FContractError("INVALID_CIK")
    return digits.zfill(10)


def accepted_utc(value: Any) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if pd.isna(parsed):
        raise Pit13FContractError("ACCEPTED_TIMESTAMP_MISSING")
    if parsed.tzinfo is None:
        raise Pit13FContractError("ACCEPTED_TIMESTAMP_TIMEZONE_MISSING")
    return parsed.tz_convert("UTC")


def decision_timestamp(signal_date: Any, cutoff: str = "16:00:00") -> pd.Timestamp:
    date = pd.Timestamp(signal_date).date().isoformat()
    return pd.Timestamp(f"{date} {cutoff}", tz=ET).tz_convert("UTC")


def filing_is_public_for_signal(accepted_timestamp: Any, signal_date: Any, cutoff: str = "16:00:00") -> bool:
    return bool(accepted_utc(accepted_timestamp) <= decision_timestamp(signal_date, cutoff))


def first_legal_signal_session(accepted_timestamp: Any, signal_sessions: Iterable[Any], cutoff: str = "16:00:00") -> pd.Timestamp:
    sessions = pd.DatetimeIndex(pd.to_datetime(list(signal_sessions))).sort_values().unique()
    legal = [session for session in sessions if filing_is_public_for_signal(accepted_timestamp, session, cutoff)]
    if not legal:
        raise Pit13FContractError("NO_LEGAL_SIGNAL_SESSION_IN_SCOPE")
    return pd.Timestamp(legal[0]).tz_localize(None)


def canonical_security_key(row: pd.Series | dict[str, Any]) -> str:
    get = row.get
    security_id = str(get("security_id", "") or "").strip()
    cusip = str(get("cusip", "") or "").strip().upper()
    ticker = str(get("ticker_resolved", get("ticker", "")) or "").strip().upper()
    if security_id:
        return f"SECURITY_ID:{security_id}"
    if cusip:
        return f"CUSIP:{cusip}"
    if ticker:
        raise Pit13FContractError("TICKER_ONLY_IDENTITY_FORBIDDEN")
    raise Pit13FContractError("SECURITY_IDENTITY_MISSING")


def classify_instrument(row: pd.Series | dict[str, Any]) -> str:
    put_call = str(row.get("put_call", row.get("PUTCALL", "")) or "").strip().upper()
    title = str(row.get("class", row.get("title_of_class", row.get("TITLEOFCLASS", ""))) or "").upper()
    if put_call in {"PUT", "CALL"}:
        return "OPTION"
    if any(token in title for token in ("ETF", "INDEX FUND", "EXCHANGE TRADED FUND")):
        return "ETF"
    if any(token in title for token in ("ADR", "ADS", "DEPOSITARY")):
        return "ADR_ADS"
    if any(token in title for token in ("COM", "COMMON", "CL A", "CL B", "ORD")):
        return "COMMON_STOCK"
    return "OTHER"


def eligible_holding(row: pd.Series | dict[str, Any], supported_security_ids: set[str] | None = None) -> bool:
    kind = classify_instrument(row)
    if kind not in ELIGIBLE_INSTRUMENTS:
        return False
    key = canonical_security_key(row)
    return supported_security_ids is None or key in supported_security_ids


def load_authoritative_manager_config(path: Path) -> dict[str, Any]:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    managers = config.get("managers", [])
    ciks = [normalized_cik(row.get("cik")) for row in managers]
    if config.get("classification") != "ACTIVE_AUTHORITATIVE":
        raise Pit13FContractError("AUTHORITATIVE_CONFIG_CLASSIFICATION_INVALID")
    if not config.get("authoritative_for_holdings_ingestion"):
        raise Pit13FContractError("AUTHORITATIVE_CONFIG_INGESTION_DISABLED")
    if config.get("manager_count") != AUTHORITATIVE_MANAGER_COUNT or len(ciks) != AUTHORITATIVE_MANAGER_COUNT:
        raise Pit13FContractError("AUTHORITATIVE_MANAGER_COUNT_NOT_24")
    if len(set(ciks)) != len(ciks):
        raise Pit13FContractError("AUTHORITATIVE_MANAGER_CIK_DUPLICATE")
    if config.get("situational_awareness_included") or SITUATIONAL_AWARENESS_CIK in ciks:
        raise Pit13FContractError("SITUATIONAL_AWARENESS_AUTHORITATIVE_FORBIDDEN")
    if config.get("per_manager_top_n") != AUTHORITATIVE_TOP_N:
        raise Pit13FContractError("AUTHORITATIVE_TOP100_CONTRACT_INVALID")
    if config.get("max_universe_size") != AUTHORITATIVE_UNIVERSE_CAP:
        raise Pit13FContractError("AUTHORITATIVE_UNIVERSE_CAP_INVALID")
    return config


def select_top100_qualifying_holdings(holdings: pd.DataFrame, top_n: int = AUTHORITATIVE_TOP_N) -> pd.DataFrame:
    """Select each manager's deterministic Top100 after instrument qualification."""
    if top_n != AUTHORITATIVE_TOP_N:
        raise Pit13FContractError("AUTHORITATIVE_TOP100_CANNOT_BE_OVERRIDDEN")
    work = holdings.copy()
    work["instrument_type"] = work.apply(classify_instrument, axis=1)
    work = work.loc[work.instrument_type.isin(ELIGIBLE_INSTRUMENTS)].copy()
    work["canonical_security_id"] = work.apply(canonical_security_key, axis=1)
    work["manager_portfolio_weight"] = pd.to_numeric(work.reported_value) / pd.to_numeric(work.manager_total_reported_value)
    if (~np.isfinite(work.manager_portfolio_weight) | work.manager_portfolio_weight.lt(0)).any():
        raise Pit13FContractError("INVALID_MANAGER_PORTFOLIO_WEIGHT")
    work["cik"] = work.cik.map(normalized_cik)
    work = work.sort_values(
        ["cik", "manager_portfolio_weight", "reported_value", "canonical_security_id", "accession"],
        ascending=[True, False, False, True, True], kind="mergesort",
    ).drop_duplicates(["cik", "canonical_security_id"], keep="first")
    work["manager_rank"] = work.groupby("cik", sort=True).cumcount() + 1
    return work.loc[work.manager_rank.le(top_n)].reset_index(drop=True)


def validate_filing_manifest(filings: pd.DataFrame) -> pd.DataFrame:
    required = {"manager", "cik", "accession", "form_type", "report_period", "accepted_timestamp", "sha256", "parse_status"}
    missing = sorted(required - set(filings.columns))
    if missing:
        raise Pit13FContractError(f"FILING_MANIFEST_COLUMNS_MISSING:{','.join(missing)}")
    out = filings.copy()
    out["cik"] = out["cik"].map(normalized_cik)
    if out["accession"].astype(str).duplicated().any():
        raise Pit13FContractError("DUPLICATED_ACCESSION_CACHE")
    if not out["form_type"].isin(ALLOWED_FORMS).all():
        raise Pit13FContractError("UNSUPPORTED_FORM_TYPE")
    out["accepted_timestamp"] = out["accepted_timestamp"].map(accepted_utc)
    if out["sha256"].astype(str).str.fullmatch(r"[0-9a-f]{64}").ne(True).any():
        raise Pit13FContractError("INVALID_SOURCE_SHA256")
    return out.sort_values(["cik", "accepted_timestamp", "accession"], kind="mergesort").reset_index(drop=True)


def latest_legal_filings(filings: pd.DataFrame, signal_date: Any, cutoff: str = "16:00:00") -> pd.DataFrame:
    valid = validate_filing_manifest(filings)
    valid = valid.loc[valid.accepted_timestamp.le(decision_timestamp(signal_date, cutoff))]
    if valid.empty:
        return valid
    # The latest public report period wins.  All filings for that period remain
    # available to the amendment resolver; no quarter-label-only join is used.
    max_period = valid.groupby("cik", sort=False).report_period.transform("max")
    return valid.loc[valid.report_period.eq(max_period)].copy()


def apply_amendment_semantics(filings: pd.DataFrame, holdings: pd.DataFrame) -> pd.DataFrame:
    required = {"accession", "amendment_type", "accepted_timestamp"}
    if not required.issubset(filings.columns) or "accession" not in holdings.columns:
        raise Pit13FContractError("AMENDMENT_INPUT_COLUMNS_MISSING")
    ordered = filings.sort_values(["accepted_timestamp", "accession"], kind="mergesort")
    current = pd.DataFrame(columns=holdings.columns)
    for filing in ordered.itertuples(index=False):
        rows = holdings.loc[holdings.accession.eq(filing.accession)].copy()
        form = str(getattr(filing, "form_type", ""))
        amendment = str(filing.amendment_type or "").upper()
        if form == "13F-HR":
            current = rows
        elif amendment == "RESTATEMENT":
            current = rows
        elif amendment in {"ADD_NEW_HOLDINGS", "ADDITIONAL_HOLDINGS"}:
            current = pd.concat([current, rows], ignore_index=True)
            keys = [c for c in ("cusip", "security_id", "put_call") if c in current.columns]
            if keys:
                current = current.drop_duplicates(keys, keep="last")
        else:
            raise Pit13FContractError("AMBIGUOUS_AMENDMENT_SEMANTICS")
    return current.reset_index(drop=True)


def build_raw_union(holdings: pd.DataFrame) -> pd.DataFrame:
    required = {"manager", "cik", "accession", "accepted_timestamp", "reported_value", "manager_total_reported_value"}
    if not required.issubset(holdings.columns):
        raise Pit13FContractError("HOLDING_COLUMNS_MISSING")
    work = select_top100_qualifying_holdings(holdings)
    grouped = work.groupby("canonical_security_id", sort=True)
    rows: list[dict[str, Any]] = []
    for security_id, group in grouped:
        manager_rows = group.sort_values(["manager", "accession"], kind="mergesort").drop_duplicates("manager", keep="last")
        rows.append({
            "canonical_security_id": security_id,
            "security_id": str(manager_rows.security_id.dropna().iloc[0]) if "security_id" in manager_rows and manager_rows.security_id.notna().any() else "",
            "cusip": str(manager_rows.cusip.dropna().iloc[0]) if "cusip" in manager_rows and manager_rows.cusip.notna().any() else "",
            "ticker": str(manager_rows.ticker.dropna().iloc[0]) if "ticker" in manager_rows and manager_rows.ticker.notna().any() else "",
            "manager_count": int(manager_rows.manager.nunique()),
            "manager_names": "|".join(manager_rows.manager.astype(str)),
            "manager_ciks": "|".join(manager_rows.cik.astype(str)),
            "manager_filing_accessions": "|".join(manager_rows.accession.astype(str)),
            "manager_filing_accepted_timestamps": "|".join(manager_rows.accepted_timestamp.astype(str)),
            "max_manager_portfolio_weight": float(manager_rows.manager_portfolio_weight.max()),
            "aggregate_reported_value": float(pd.to_numeric(manager_rows.reported_value).sum()),
            "first_public_source_timestamp": str(manager_rows.accepted_timestamp.min()),
            "latest_source_timestamp": str(manager_rows.accepted_timestamp.max()),
            "source_provenance_status": "SEC_ACCESSION_SHA256_REQUIRED",
        })
    return pd.DataFrame(rows).sort_values("canonical_security_id", kind="mergesort").reset_index(drop=True)


def apply_universe_cap(raw_union: pd.DataFrame, max_size: int = 900) -> tuple[pd.DataFrame, pd.DataFrame]:
    forbidden = sorted(CAP_FORBIDDEN_COLUMNS.intersection({c.lower() for c in raw_union.columns}))
    if forbidden:
        raise Pit13FContractError(f"CAP_MODEL_OR_OUTCOME_COLUMN_PRESENT:{','.join(forbidden)}")
    required = {"canonical_security_id", "manager_count", "max_manager_portfolio_weight", "aggregate_reported_value"}
    if not required.issubset(raw_union.columns) or max_size <= 0:
        raise Pit13FContractError("CAP_INPUT_INVALID")
    ranked = raw_union.sort_values(
        ["manager_count", "max_manager_portfolio_weight", "aggregate_reported_value", "canonical_security_id"],
        ascending=[False, False, False, True], kind="mergesort",
    ).reset_index(drop=True)
    ranked["cap_rank"] = np.arange(1, len(ranked) + 1, dtype=np.int64)
    ranked["raw_union_size"] = len(ranked)
    ranked["final_universe_size"] = min(len(ranked), max_size)
    ranked["cap_applied"] = len(ranked) > max_size
    final = ranked.loc[ranked.cap_rank.le(max_size)].copy()
    excluded = ranked.loc[ranked.cap_rank.gt(max_size)].copy()
    return final, excluded


def authoritative_quarter_activations(
    filings: pd.DataFrame, authoritative_ciks: Iterable[Any], trading_sessions: Iterable[Any],
) -> pd.DataFrame:
    """Activate only after all 24 managers file, on the fifth later US session."""
    required = {"quarter", "cik", "accepted_timestamp"}
    if not required.issubset(filings.columns):
        raise Pit13FContractError("AUTHORITATIVE_ACTIVATION_COLUMNS_MISSING")
    expected = {normalized_cik(value) for value in authoritative_ciks}
    if len(expected) != AUTHORITATIVE_MANAGER_COUNT or SITUATIONAL_AWARENESS_CIK in expected:
        raise Pit13FContractError("AUTHORITATIVE_ACTIVATION_MANAGER_SET_INVALID")
    sessions = pd.DatetimeIndex(pd.to_datetime(list(trading_sessions))).tz_localize(None).normalize().sort_values().unique()
    rows = []
    work = filings.copy(); work["cik"] = work.cik.map(normalized_cik); work["accepted_timestamp"] = work.accepted_timestamp.map(accepted_utc)
    for quarter, group in work.groupby("quarter", sort=True):
        present = set(group.cik)
        if present != expected:
            raise Pit13FContractError(f"AUTHORITATIVE_QUARTER_INCOMPLETE:{quarter}")
        latest = group.groupby("cik", sort=True).accepted_timestamp.max().max()
        later = sessions[sessions > latest.tz_convert(ET).tz_localize(None).normalize()]
        if len(later) < 5:
            raise Pit13FContractError(f"ACTIVATION_TRADING_CALENDAR_INSUFFICIENT:{quarter}")
        rows.append({"quarter": quarter, "latest_actual_filing_timestamp": latest, "effective_date": pd.Timestamp(later[4])})
    return pd.DataFrame(rows).sort_values(["effective_date", "quarter"], kind="mergesort").reset_index(drop=True)


def active_quarter_ledger(signal_sessions: Iterable[Any], activations: pd.DataFrame) -> pd.DataFrame:
    required = {"quarter", "effective_date"}
    if not required.issubset(activations.columns):
        raise Pit13FContractError("ACTIVE_QUARTER_COLUMNS_MISSING")
    ordered = activations.copy().sort_values(["effective_date", "quarter"], kind="mergesort")
    effective = pd.DatetimeIndex(pd.to_datetime(ordered.effective_date)).tz_localize(None).normalize()
    rows = []
    for session in pd.DatetimeIndex(pd.to_datetime(list(signal_sessions))).tz_localize(None).normalize().sort_values().unique():
        pos = int(effective.searchsorted(session, side="right") - 1)
        rows.append({"signal_date": pd.Timestamp(session), "active_quarter": None if pos < 0 else ordered.iloc[pos].quarter})
    return pd.DataFrame(rows)


def eligible_candidates_asof(
    candidates: Iterable[str], price_history: pd.DataFrame, signal_date: Any, min_observations: int,
) -> tuple[list[str], list[str]]:
    """Past eligibility depends only on price observations available by signal_date."""
    required = {"canonical_security_id", "date"}
    if not required.issubset(price_history.columns) or min_observations <= 0:
        raise Pit13FContractError("PRICE_ELIGIBILITY_INPUT_INVALID")
    cutoff = pd.Timestamp(signal_date).tz_localize(None).normalize()
    history = price_history.copy(); history["date"] = pd.to_datetime(history.date).dt.tz_localize(None).dt.normalize()
    history = history.loc[history.date.le(cutoff)].drop_duplicates(["canonical_security_id", "date"])
    counts = history.groupby("canonical_security_id", sort=True).size()
    ordered = sorted(set(map(str, candidates)))
    eligible = [security for security in ordered if int(counts.get(security, 0)) >= min_observations]
    return eligible, [security for security in ordered if security not in set(eligible)]


def rank_scores_within_universe(scores: pd.DataFrame, universe: pd.DataFrame, score_column: str) -> pd.DataFrame:
    required_scores = {"signal_date", "canonical_security_id", score_column}
    required_universe = {"signal_date", "canonical_security_id"}
    if not required_scores.issubset(scores.columns) or not required_universe.issubset(universe.columns):
        raise Pit13FContractError("DYNAMIC_RANK_INPUT_COLUMNS_MISSING")
    merged = universe[list(required_universe)].merge(scores[list(required_scores)], on=["signal_date", "canonical_security_id"], how="left", validate="one_to_one")
    if merged[score_column].isna().any():
        raise Pit13FContractError("FEATURE_OR_SCORE_COVERAGE_INSUFFICIENT")
    merged["dynamic_rank"] = merged.groupby("signal_date")[score_column].rank(method="first", ascending=False).astype(int)
    return merged.sort_values(["signal_date", "dynamic_rank", "canonical_security_id"], kind="mergesort").reset_index(drop=True)


def audit_target_maturity(signal_date: Any, training_end_date: Any, latest_target_maturity_date: Any) -> str:
    signal = pd.Timestamp(signal_date)
    training = pd.Timestamp(training_end_date)
    maturity = pd.Timestamp(latest_target_maturity_date)
    if training >= signal:
        return "FAIL_TRAINING_DATE_OVERLAP"
    if maturity >= signal:
        return "FAIL_TARGET_MATURITY_OVERLAP"
    return "PASS"


def duplicated_accession_count(cache_manifest: pd.DataFrame) -> int:
    if "accession" not in cache_manifest.columns:
        return 0
    return int(cache_manifest.accession.astype(str).duplicated(keep=False).sum())
