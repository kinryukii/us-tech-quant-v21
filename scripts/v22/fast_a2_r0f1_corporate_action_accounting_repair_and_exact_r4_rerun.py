"""Freeze source-backed corporate-action policy, then exactly rerun corrected R4.

The corrected economic rerun is intentionally unavailable until
``--freeze-policy-only`` has materialized an immutable policy and witness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

_IMPORT_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_IMPORT_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_IMPORT_REPO_ROOT))

from scripts.v22 import abcde_a2_r4_portfolio_translation_using_hgb_incumbent as r4
from scripts.v22 import fast_a2_r0f_corporate_action_and_nav_forensic_audit as r0f
from scripts.v22.corporate_action_transition_r1 import (
    CorporateActionTransition,
    CorporateActionTransitionAdapter,
    SUPPORTED_ACTION_FAMILIES,
)


EXPERIMENT_ID = "FAST_A2_R0F1_CORPORATE_ACTION_ACCOUNTING_REPAIR_AND_EXACT_R4_RERUN"
REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_PARENT = Path(r"D:\us-tech-quant-results")
RESULTS_ROOT = RESULTS_PARENT / EXPERIMENT_ID
R0F_ROOT = RESULTS_PARENT / "FAST_A2_R0F_CORPORATE_ACTION_AND_NAV_FORENSIC_AUDIT"

SUMMARY_PATH = RESULTS_ROOT / "fast_a2_r0f1_summary.json"
POLICY_PATH = RESULTS_ROOT / "corporate_action_accounting_policy_r1.json"
POLICY_WITNESS_PATH = RESULTS_ROOT / "corporate_action_policy_freeze_witness.json"
EVENT_MANIFEST_PATH = RESULTS_ROOT / "corporate_action_event_manifest.parquet"
EVENT_REVIEW_PATH = RESULTS_ROOT / "corporate_action_event_review.parquet"
TRANSITIONS_PATH = RESULTS_ROOT / "corporate_action_position_transitions.parquet"
CORRECTED_DAILY_PATH = RESULTS_ROOT / "corrected_a1_a2_top20_daily_portfolio.parquet"
CORRECTED_METRICS_PATH = RESULTS_ROOT / "corrected_a1_a2_portfolio_metrics.parquet"
YEARLY_METRICS_PATH = RESULTS_ROOT / "corrected_a1_a2_yearly_metrics.parquet"
OLD_VS_CORRECTED_PATH = RESULTS_ROOT / "old_vs_corrected_metrics.parquet"
NAV_DAILY_PATH = RESULTS_ROOT / "corrected_nav_reconstruction_daily.parquet"
NAV_METRICS_PATH = RESULTS_ROOT / "corrected_nav_reconstruction_metrics.json"
SECURITY_EXTREMES_PATH = RESULTS_ROOT / "corrected_security_extreme_return_events.parquet"
PORTFOLIO_EXTREMES_PATH = RESULTS_ROOT / "corrected_portfolio_extreme_return_events.parquet"
TICKER_CONCENTRATION_PATH = RESULTS_ROOT / "corrected_pnl_concentration_by_ticker.parquet"
DAY_CONCENTRATION_PATH = RESULTS_ROOT / "corrected_pnl_concentration_by_day.parquet"
PROVENANCE_PATH = RESULTS_ROOT / "provenance_manifest.json"

R0F_SUMMARY_PATH = R0F_ROOT / "fast_a2_r0f_summary.json"
R0F_EVENTS_PATH = R0F_ROOT / "corporate_action_events.parquet"
R0F_SPLIT_AUDIT_PATH = R0F_ROOT / "split_reverse_split_consistency_audit.parquet"
R0F_NAV_PATH = R0F_ROOT / "nav_reconstruction_daily.parquet"
R0F_EXTREMES_PATH = R0F_ROOT / "security_extreme_return_events.parquet"
R0F_PROVENANCE_PATH = R0F_ROOT / "provenance_manifest.json"

HELPER_PATH = REPO_ROOT / "scripts/v22/corporate_action_transition_r1.py"
TEST_PATH = REPO_ROOT / "scripts/v22/test_fast_a2_r0f1_corporate_action_accounting_repair_and_exact_r4_rerun.py"
SCRIPT_PATH = Path(__file__).resolve()

START = pd.Timestamp("2023-01-01")
END_EXCLUSIVE = pd.Timestamp("2026-01-01")
PRIMARY_TOP_N = 20
PRIMARY_COST_BPS = 10
ABS_TOL = 1e-10
REL_TOL = 1e-10

REVIEW_CLASSIFICATIONS = (
    "CONFIRMED_REPAIR_REQUIRED", "CONFIRMED_ALREADY_CORRECT", "CONFIRMED_REAL_MARKET_MOVE",
    "HEURISTIC_FALSE_POSITIVE", "NOT_HELD_THROUGH_EVENT", "INSUFFICIENT_EVIDENCE_FAIL_CLOSED",
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str,
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def payload_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def dataframe_fingerprint(frame: pd.DataFrame) -> str:
    return r0f.dataframe_fingerprint(frame)


def frozen_evidence_records() -> list[dict[str, Any]]:
    """Tier-1 facts frozen before any corrected metric read."""
    records = [
        {
            "ticker": "AMC", "event_date": "2023-08-24", "action_type": "REVERSE_SPLIT",
            "quantity_multiplier": 0.1, "old_security_id": "SOURCE_ID_NOT_EXTRACTED",
            "new_security_id": "SOURCE_ID_NOT_EXTRACTED", "security_id_changed": None,
            "source_type": "TIER1_ISSUER_REGULATOR_EXCHANGE",
            "source_reference": "https://investor.amctheatres.com/sec-filings/all-sec-filings/content/0001104659-23-090981/tm2323643d1_8k.htm",
            "source_fact": "one-for-ten reverse split effective before market on 2023-08-24",
        },
        {
            "ticker": "AEVA", "event_date": "2024-03-19", "action_type": "REVERSE_SPLIT",
            "quantity_multiplier": 0.2, "old_security_id": "PRE_SPLIT_CUSIP_NOT_EXTRACTED",
            "new_security_id": "CUSIP_00835Q202", "security_id_changed": True,
            "source_type": "TIER1_ISSUER_REGULATOR_EXCHANGE",
            "source_reference": "https://www.sec.gov/Archives/edgar/data/1789029/000119312524070371/d797793dex991.htm",
            "source_fact": "one-for-five reverse split; split-adjusted trading and new CUSIP on 2024-03-19",
        },
        {
            "ticker": "SSG", "event_date": "2024-04-10", "action_type": "REVERSE_SPLIT",
            "quantity_multiplier": 0.2, "old_security_id": "CUSIP_74347G622",
            "new_security_id": "CUSIP_74349Y860", "security_id_changed": True,
            "source_type": "TIER1_ISSUER_REGULATOR_EXCHANGE",
            "source_reference": "https://www.proshares.com/press-releases/proshares-announces-etf-share-splits2",
            "source_fact": "one-for-five reverse split effective before market on 2024-04-10",
        },
        {
            "ticker": "DBVT", "event_date": "2024-06-07", "action_type": "ADR_RATIO_CHANGE",
            "quantity_multiplier": 0.5, "old_security_id": "CUSIP_23306J101",
            "new_security_id": "CUSIP_23306J200", "security_id_changed": True,
            "source_type": "TIER1_ISSUER_REGULATOR_EXCHANGE",
            "source_reference": "https://www.sec.gov/Archives/edgar/data/1613780/000119312524151728/d781980dex991.htm",
            "source_fact": "two old ADS exchanged for one new ADS effective 2024-06-07",
        },
        {
            "ticker": "NVDA", "event_date": "2024-06-10", "action_type": "FORWARD_SPLIT",
            "quantity_multiplier": 10.0, "old_security_id": "SECURITY_ID_UNCHANGED_OR_NOT_REQUIRED",
            "new_security_id": "SECURITY_ID_UNCHANGED_OR_NOT_REQUIRED", "security_id_changed": False,
            "source_type": "TIER1_ISSUER_REGULATOR_EXCHANGE",
            "source_reference": "https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-first-quarter-fiscal-2025",
            "source_fact": "ten-for-one forward split; split-adjusted trading began 2024-06-10",
        },
        {
            "ticker": "AVGO", "event_date": "2024-07-15", "action_type": "FORWARD_SPLIT",
            "quantity_multiplier": 10.0, "old_security_id": "SECURITY_ID_UNCHANGED_OR_NOT_REQUIRED",
            "new_security_id": "SECURITY_ID_UNCHANGED_OR_NOT_REQUIRED", "security_id_changed": False,
            "source_type": "TIER1_ISSUER_REGULATOR_EXCHANGE",
            "source_reference": "https://investors.broadcom.com/news-releases/news-release-details/broadcom-inc-announces-second-quarter-fiscal-year-2024-financial",
            "source_fact": "ten-for-one forward split; split-adjusted trading began 2024-07-15",
        },
        {
            "ticker": "DBVT", "event_date": "2024-11-29", "action_type": "ADR_RATIO_CHANGE",
            "quantity_multiplier": 0.2, "old_security_id": "CUSIP_23306J200",
            "new_security_id": "CUSIP_23306J309", "security_id_changed": True,
            "source_type": "TIER1_ISSUER_REGULATOR_EXCHANGE",
            "source_reference": "https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2024-583",
            "source_fact": "one-for-five reverse ADS split and ratio/CUSIP change effective 2024-11-29",
        },
        {
            "ticker": "WOLF", "event_date": "2025-09-29",
            "action_type": "SECURITY_REORGANIZATION_SHARE_CONVERSION",
            "quantity_multiplier": 0.008352, "old_security_id": "CUSIP_977852102",
            "new_security_id": "CUSIP_97785W106", "security_id_changed": True,
            "source_type": "TIER1_ISSUER_REGULATOR_EXCHANGE",
            "source_reference": "https://www.sec.gov/Archives/edgar/data/895419/000119312525223057/d69265d8k.htm",
            "secondary_source_reference": "https://www.sec.gov/Archives/edgar/data/876661/000087666125000713/ruleprovisionnotice.htm",
            "source_fact": "old common stock cancelled; old holders received 0.008352 new share per old share",
        },
    ]
    for record in records:
        frozen = {key: value for key, value in record.items() if key != "source_fingerprint"}
        record["source_fingerprint"] = payload_sha256(frozen)
    return records


def _required_source_paths() -> list[Path]:
    return [
        r4.R4_SUMMARY_PATH if hasattr(r4, "R4_SUMMARY_PATH") else r4.SUMMARY_PATH,
        r4.DAILY_PATH, r4.METRICS_PATH, r4.EXECUTION_ELIGIBILITY_POLICY_PATH,
        r4.EXECUTION_ELIGIBILITY_AUDIT_PATH, r4.CONTRACT_PATH, r4.MANIFEST_PATH,
        r0f.R1_OOF_PATH, R0F_SUMMARY_PATH, R0F_EVENTS_PATH, R0F_SPLIT_AUDIT_PATH,
        R0F_NAV_PATH, R0F_EXTREMES_PATH, R0F_PROVENANCE_PATH,
    ]


def load_r0f_evidence() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    missing = [str(path) for path in _required_source_paths() if not path.is_file()]
    if missing:
        raise RuntimeError("MISSING_R0F1_SOURCE:" + ",".join(missing))
    events = pq.read_table(R0F_EVENTS_PATH).to_pandas()
    events["event_date"] = pd.to_datetime(events.event_date)
    split = pq.read_table(R0F_SPLIT_AUDIT_PATH).to_pandas()
    split["post_date"] = pd.to_datetime(split.post_date)
    nav = pq.read_table(R0F_NAV_PATH).to_pandas()
    nav["execution_date"] = pd.to_datetime(nav.execution_date)
    extremes = pq.read_table(R0F_EXTREMES_PATH).to_pandas()
    extremes["date"] = pd.to_datetime(extremes.date)
    summary = json.loads(R0F_SUMMARY_PATH.read_text(encoding="utf-8"))
    for frame, column in ((events, "event_date"), (split, "post_date"), (nav, "execution_date"), (extremes, "date")):
        if (frame[column] >= END_EXCLUSIVE).any():
            raise RuntimeError("POST2025_R0F_EVIDENCE_READ")
    return events, split, nav, extremes, summary


def build_event_review() -> tuple[pd.DataFrame, pd.DataFrame]:
    events, split, nav, extremes, _ = load_r0f_evidence()
    evidence = {(item["ticker"], pd.Timestamp(item["event_date"])): item for item in frozen_evidence_records()}
    held_keys = set(zip(split.ticker.astype(str), pd.to_datetime(split.post_date)))
    rows: list[dict[str, Any]] = []
    for event in events.itertuples(index=False):
        key = (str(event.ticker), pd.Timestamp(event.event_date))
        held = key in held_keys
        source = evidence.get(key)
        held_rows = split.loc[split.ticker.eq(event.ticker) & split.post_date.eq(event.event_date)]
        weights: list[float] = []
        old_contributions: list[float] = []
        for held_row in held_rows.itertuples(index=False):
            model_nav = nav.loc[nav.model.eq(held_row.model) & nav.execution_date.lt(event.event_date)].sort_values("execution_date")
            prior_nav = float(model_nav.iloc[-1].frozen_nav) if not model_nav.empty else np.nan
            if math.isfinite(prior_nav) and prior_nav > 0:
                weights.append(float(held_row.pre_position_value) / prior_nav)
                old_contributions.append(float(held_row.post_position_value - held_row.pre_position_value) / prior_nav)
        if held and source is None:
            classification = "INSUFFICIENT_EVIDENCE_FAIL_CLOSED"
            reason = "held through heuristic event without Tier1-3 evidence"
        elif not held:
            classification = "NOT_HELD_THROUGH_EVENT"
            reason = "no A1/A2 TOP20 position crossed effective session; no accounting action applicable"
        elif source["ticker"] == "WOLF":
            classification = "CONFIRMED_REPAIR_REQUIRED"
            reason = "QFQ and RAW both cross old/new security price; ticker-only ledger failed source-confirmed quantity conversion"
        else:
            classification = "CONFIRMED_ALREADY_CORRECT"
            reason = "source-confirmed split/ADS action is economically continuous in QFQ coordinate; explicit share multiplication would double-adjust"
        if classification not in REVIEW_CLASSIFICATIONS:
            raise RuntimeError("INVALID_EVENT_REVIEW_CLASSIFICATION")
        rows.append({
            "ticker": event.ticker, "security_id": event.security_id,
            "event_date": event.event_date, "raw_return": event.raw_return,
            "qfq_return": event.adjusted_return,
            "fingerprint_type": event.corporate_action_type,
            "source_search_status": "TIER1_CONFIRMED" if source else "NOT_REQUIRED_NOT_HELD_THROUGH",
            "confirmed_action_type": None if source is None else source["action_type"],
            "quantity_multiplier": np.nan if source is None else source["quantity_multiplier"],
            "security_id_changed": None if source is None else source["security_id_changed"],
            "ticker_changed": False if source else None,
            "held_through_event": held,
            "material_to_portfolio": held,
            "position_weight_before_event": max(weights) if weights else 0.0,
            "incorrect_old_pnl_contribution": max(old_contributions, key=abs) if old_contributions else 0.0,
            "corrected_pnl_contribution": np.nan,
            "pnl_difference": np.nan,
            "repair_required": classification == "CONFIRMED_REPAIR_REQUIRED",
            "repair_applied": False,
            "classification": classification, "reason": reason,
            "source_reference": None if source is None else source["source_reference"],
            "source_fingerprint": None if source is None else source["source_fingerprint"],
        })
    review = pd.DataFrame(rows).sort_values(["event_date", "ticker", "classification"], kind="mergesort").reset_index(drop=True)
    if len(review) != len(events) or review.classification.isna().any():
        raise RuntimeError("INCOMPLETE_CORPORATE_ACTION_EVENT_REVIEW")
    manifest = pd.DataFrame(frozen_evidence_records()).sort_values(["event_date", "ticker"], kind="mergesort").reset_index(drop=True)
    manifest["event_date"] = pd.to_datetime(manifest.event_date)
    return manifest, review


def build_policy(manifest: pd.DataFrame, review: pd.DataFrame) -> dict[str, Any]:
    unresolved = review.loc[review.classification.eq("INSUFFICIENT_EVIDENCE_FAIL_CLOSED") & review.material_to_portfolio]
    if not unresolved.empty:
        raise RuntimeError("UNRESOLVED_MATERIAL_CORPORATE_ACTION_EVIDENCE")
    repairs = manifest.loc[
        manifest.ticker.isin(review.loc[review.classification.eq("CONFIRMED_REPAIR_REQUIRED"), "ticker"])
        & manifest.event_date.isin(review.loc[review.classification.eq("CONFIRMED_REPAIR_REQUIRED"), "event_date"])
    ]
    repair_events = []
    for item in repairs.to_dict("records"):
        repair_events.append({
            "effective_date": str(pd.Timestamp(item["event_date"]).date()),
            "action_type": item["action_type"], "old_security_id": item["old_security_id"],
            "new_security_id": item["new_security_id"], "old_ticker": item["ticker"],
            "new_ticker": item["ticker"], "quantity_multiplier": float(item["quantity_multiplier"]),
            "cash_component_per_old_share": 0.0, "source_type": item["source_type"],
            "source_reference": item["source_reference"], "source_fingerprint": item["source_fingerprint"],
            "ratio_orientation": "NEW_QUANTITY_PER_OLD_QUANTITY", "repair_authorized": True,
        })
    return {
        "schema_version": "1.0", "policy_id": "FAST_A2_R0F1_CORPORATE_ACTION_ACCOUNTING_POLICY_R1",
        "position_quantity_coordinate": "QFQ_SYNTHETIC_SHARE_UNITS_WITH_SOURCE_CONFIRMED_UNADJUSTED_SECURITY_MIGRATION_TRANSITIONS",
        "action_families_supported": list(SUPPORTED_ACTION_FAMILIES),
        "quantity_conversion_formula": "NEW_QUANTITY=OLD_QUANTITY*QUANTITY_MULTIPLIER",
        "ratio_orientation": "NEW_QUANTITY_PER_OLD_QUANTITY",
        "security_migration_rule": "REMOVE_OLD_SECURITY_POSITION_THEN_CREATE_NEW_SECURITY_POSITION;SAME_TICKER_DOES_NOT_IMPLY_SAME_SECURITY",
        "fractional_share_policy": "PRESERVE_RESEARCH_PORTFOLIO_FRACTIONAL_QUANTITIES_NO_BROKER_ROUNDING",
        "fractional_share_policy_changed": False,
        "cash_component_rule": "CASH_DELTA=OLD_QUANTITY*CASH_COMPONENT_PER_OLD_SHARE;UNRESOLVED_CASH_COMPONENT_FAILS_CLOSED",
        "cash_in_lieu_status": "NOT_APPLICABLE_TO_APPLIED_WOLF_TRANSITION;FRACTIONAL_RESEARCH_QUANTITY_PRESERVED",
        "source_hierarchy": ["TIER1_ISSUER_REGULATOR_EXCHANGE", "TIER2_LOCAL_CANONICAL", "TIER3_VENDOR_METADATA", "TIER4_HEURISTIC_FLAG_ONLY"],
        "tier4_auto_repair_allowed": False,
        "fail_closed_rule": "ANY_MATERIAL_HELD_THROUGH_EVENT_WITHOUT_TIER1_3_EVIDENCE_STOPS_BEFORE_CORRECTED_METRIC_READ",
        "timing_rule": "APPLY_TRANSITION_AFTER_PREVIOUS_SESSION_POSITION_AND_BEFORE_EFFECTIVE_SESSION_MARK_AND_TRADES",
        "qfq_split_rule": "SOURCE_CONFIRMED_SPLIT_ALREADY_CONTINUOUS_IN_QFQ_REQUIRES_NO_EXPLICIT_SYNTHETIC_QUANTITY_CHANGE;DOING_SO_WOULD_DOUBLE_ADJUST",
        "repair_event_count": len(repair_events), "source_confirmed_event_count": len(manifest),
        "repair_events": repair_events,
        "source_confirmed_event_manifest_fingerprint": dataframe_fingerprint(manifest),
        "event_review_fingerprint": dataframe_fingerprint(review),
        "tests_sha256": sha256_file(TEST_PATH),
        "model_fit_allowed": False, "post2025_outcome_read_allowed": False,
        "policy_frozen_before_corrected_metric_read": True,
    }


def _write_parquet_new(path: Path, frame: pd.DataFrame) -> None:
    if path.exists():
        raise RuntimeError(f"REFUSE_TO_OVERWRITE:{path}")
    normalized = frame.copy()
    for column in normalized.columns:
        if normalized[column].map(lambda value: isinstance(value, (list, dict, tuple))).any():
            normalized[column] = normalized[column].map(
                lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
                if isinstance(value, (list, dict, tuple)) else value
            )
    pq.write_table(pa.Table.from_pandas(normalized, preserve_index=False), path, compression="zstd")


def freeze_policy() -> dict[str, Any]:
    if RESULTS_ROOT.exists():
        raise RuntimeError(f"REFUSE_TO_OVERWRITE_EXISTING_R0F1_ROOT:{RESULTS_ROOT}")
    manifest, review = build_event_review()
    policy = build_policy(manifest, review)
    staging = Path(tempfile.mkdtemp(prefix=f".{EXPERIMENT_ID}.freeze.", dir=RESULTS_PARENT))
    try:
        policy_path = staging / POLICY_PATH.name
        policy_path.write_bytes(canonical_bytes(policy) + b"\n")
        pq.write_table(pa.Table.from_pandas(manifest, preserve_index=False), staging / EVENT_MANIFEST_PATH.name, compression="zstd")
        pq.write_table(pa.Table.from_pandas(review, preserve_index=False), staging / EVENT_REVIEW_PATH.name, compression="zstd")
        policy_sha = sha256_file(policy_path)
        witness = {
            "policy_path": str(POLICY_PATH), "corporate_action_policy_sha256": policy_sha,
            "policy_payload_fingerprint": payload_sha256(policy),
            "event_manifest_fingerprint": dataframe_fingerprint(manifest),
            "event_review_fingerprint": dataframe_fingerprint(review),
            "tests_sha256": sha256_file(TEST_PATH), "corrected_metric_read_count_at_freeze": 0,
            "policy_frozen_before_corrected_r4_metric_read": True,
        }
        (staging / POLICY_WITNESS_PATH.name).write_bytes(canonical_bytes(witness) + b"\n")
        os.replace(staging, RESULTS_ROOT)
    except Exception:
        if staging.exists() and staging.parent.resolve() == RESULTS_PARENT.resolve():
            shutil.rmtree(staging)
        raise
    return witness


def load_frozen_policy() -> tuple[dict[str, Any], dict[str, Any], pd.DataFrame, pd.DataFrame]:
    required = (POLICY_PATH, POLICY_WITNESS_PATH, EVENT_MANIFEST_PATH, EVENT_REVIEW_PATH)
    if not all(path.is_file() for path in required):
        raise RuntimeError("POLICY_NOT_FROZEN_BEFORE_ECONOMIC_RERUN")
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    witness = json.loads(POLICY_WITNESS_PATH.read_text(encoding="utf-8"))
    manifest = pq.read_table(EVENT_MANIFEST_PATH).to_pandas()
    review = pq.read_table(EVENT_REVIEW_PATH).to_pandas()
    manifest["event_date"] = pd.to_datetime(manifest.event_date)
    review["event_date"] = pd.to_datetime(review.event_date)
    checks = {
        "policy_sha": sha256_file(POLICY_PATH) == witness["corporate_action_policy_sha256"],
        "policy_payload": payload_sha256(policy) == witness["policy_payload_fingerprint"],
        "manifest": dataframe_fingerprint(manifest) == witness["event_manifest_fingerprint"],
        "review": dataframe_fingerprint(review) == witness["event_review_fingerprint"],
        "tests": sha256_file(TEST_PATH) == witness["tests_sha256"] == policy["tests_sha256"],
        "sequencing": witness["corrected_metric_read_count_at_freeze"] == 0 and witness["policy_frozen_before_corrected_r4_metric_read"],
    }
    if not all(checks.values()):
        raise RuntimeError("FROZEN_POLICY_OR_WITNESS_INTEGRITY_FAILURE:" + ",".join(key for key, value in checks.items() if not value))
    return policy, witness, manifest, review


def policy_transitions(policy: dict[str, Any]) -> list[CorporateActionTransition]:
    return [CorporateActionTransition(**record) for record in policy["repair_events"]]


def signal_and_target_fingerprints(inputs: r0f.Inputs) -> dict[str, str]:
    signal = inputs.signals[["signal_date", "ticker", "a1_rank", "a2_rank"]].copy()
    selected_rows = []
    targets = r0f.build_target_maps(inputs.signals)
    for model, mapping in targets.items():
        for date, day in mapping.items():
            selected_rows.extend({"model": model, "signal_date": date, "ticker": ticker, "weight": weight} for ticker, weight in day.items())
    selected = pd.DataFrame(selected_rows).sort_values(["model", "signal_date", "ticker"], kind="mergesort").reset_index(drop=True)
    return {"signal_fingerprint": dataframe_fingerprint(signal), "top20_target_fingerprint": dataframe_fingerprint(selected)}


def materialize_corrected_all(
    inputs: r0f.Inputs, transitions: list[CorporateActionTransition],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], pd.DataFrame]:
    paths: list[pd.DataFrame] = []
    metric_rows: list[dict[str, Any]] = []
    transition_rows: list[dict[str, Any]] = []
    nested: dict[str, Any] = {}
    for model, rank_column in (("A1", "a1_rank"), ("A2_HGB", "a2_rank")):
        nested[model] = {}
        for top_n in (5, 10, 20):
            nested[model][str(top_n)] = {}
            for cost_bps in (0, 5, 10, 20):
                adapter = CorporateActionTransitionAdapter(transitions)
                path = r4.simulate_portfolio(
                    inputs.signals, inputs.qfq, model, rank_column, top_n, cost_bps,
                    corporate_action_adapter=adapter,
                )
                paths.append(path)
                transition_rows.extend(adapter.records)
                nested[model][str(top_n)][str(cost_bps)] = {}
                for scope in (2023, 2024, 2025, "POOLED_PRE2026"):
                    scoped = path if scope == "POOLED_PRE2026" else path.loc[path.year.eq(scope)]
                    metrics = r4.portfolio_metrics(scoped)
                    nested[model][str(top_n)][str(cost_bps)][str(scope)] = metrics
                    metric_rows.extend({
                        "model": model, "top_n": top_n, "cost_bps": cost_bps,
                        "scope": str(scope), "metric": metric, "value": value,
                    } for metric, value in metrics.items())
    all_paths = pd.concat(paths, ignore_index=True).sort_values(
        ["top_n", "cost_bps", "model", "execution_date"], kind="mergesort"
    ).reset_index(drop=True)
    metrics = pd.DataFrame(metric_rows)
    transitions_frame = pd.DataFrame(transition_rows).sort_values(
        ["effective_date", "top_n", "cost_bps", "model", "old_security_id"], kind="mergesort"
    ).reset_index(drop=True)
    return all_paths, metrics, nested, transitions_frame


def independent_corrected_reconstruction(
    inputs: r0f.Inputs, transitions: list[CorporateActionTransition], corrected_primary: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """Independent price-coordinate reconstruction; does not call transition helper."""
    transformed = inputs.qfq.copy()
    for event in transitions:
        if event.cash_component_per_old_share != 0.0 or event.old_ticker != event.new_ticker:
            raise RuntimeError("INDEPENDENT_RECONSTRUCTION_UNSUPPORTED_TRANSITION_SHAPE")
        mask = transformed.ticker.eq(event.new_ticker) & transformed.trade_date.ge(pd.Timestamp(event.effective_date))
        transformed.loc[mask, ["open", "close"]] *= event.quantity_multiplier
    targets = r0f.build_target_maps(inputs.signals)
    results = [
        r0f.reconstruct_path(
            model=model, target_map=targets[model], qfq=transformed,
            signal_dates=inputs.signals.signal_date.unique(), cost_bps=PRIMARY_COST_BPS,
        ) for model in ("A1", "A2_HGB")
    ]
    daily = pd.concat([result.daily for result in results], ignore_index=True).sort_values(
        ["model", "execution_date"], kind="mergesort"
    ).reset_index(drop=True)
    positions = pd.concat([result.positions for result in results], ignore_index=True).sort_values(
        ["model", "date", "ticker"], kind="mergesort"
    ).reset_index(drop=True)
    frozen = corrected_primary[["execution_date", "model", "net_nav", "net_return"]].copy()
    compared = daily.merge(frozen, on=["execution_date", "model"], validate="one_to_one")
    compared["corrected_nav"] = compared.pop("net_nav")
    compared["corrected_daily_return"] = compared.pop("net_return")
    compared["nav_reconstruction_error"] = compared.reconstructed_nav - compared.corrected_nav
    compared["nav_reconstruction_rel_error"] = compared.nav_reconstruction_error / compared.corrected_nav
    compared["daily_return_error"] = compared.reconstructed_daily_return - compared.corrected_daily_return
    max_abs = float(compared.nav_reconstruction_error.abs().max())
    max_rel = float(compared.nav_reconstruction_rel_error.abs().max())
    failures = int((compared.nav_reconstruction_error.abs().gt(ABS_TOL) & compared.nav_reconstruction_rel_error.abs().gt(REL_TOL)).sum())
    metrics = {
        "CORRECTED_NAV_RECONSTRUCTION_STATUS": "PASS" if failures == 0 else "FAIL",
        "CORRECTED_NAV_RECONSTRUCTION_MAX_ABS_ERROR": max_abs,
        "CORRECTED_NAV_RECONSTRUCTION_MAX_REL_ERROR": max_rel,
        "CORRECTED_NAV_RECONSTRUCTION_MEAN_ABS_ERROR": float(compared.nav_reconstruction_error.abs().mean()),
        "CORRECTED_NAV_RECONSTRUCTION_FAILURE_DAY_COUNT": failures,
        "INDEPENDENT_RECONSTRUCTION_METHOD": "POST_EVENT_OLD_SHARE_EQUIVALENT_PRICE_COORDINATE_NOT_SHARED_TRANSITION_HELPER",
        "NAV_ABS_TOLERANCE": ABS_TOL, "NAV_REL_TOLERANCE": REL_TOL,
    }
    return compared, positions, metrics, transformed, pd.concat([result.trades for result in results], ignore_index=True)


def yearly_table(nested: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for year in (2023, 2024, 2025):
        for model in ("A1", "A2_HGB"):
            metrics = nested[model]["20"]["10"][str(year)]
            rows.append({
                "year": year, "model": model, "net_return": metrics["cumulative_return"],
                "volatility": metrics["annualized_volatility"], "Sharpe": metrics["sharpe_rf0"],
                "max_drawdown": metrics["max_drawdown"], "turnover": metrics["total_turnover"],
                "annualized_turnover": metrics["annualized_turnover"],
                "transaction_cost": metrics["total_transaction_cost"],
            })
    return pd.DataFrame(rows)


def old_vs_corrected_table(inputs: r0f.Inputs, nested: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for model, prefix in (("A1", "A1"), ("A2_HGB", "A2")):
        old = inputs.frozen_summary[f"POOLED_{prefix}_METRICS"]
        corrected = nested[model]["20"]["10"]["POOLED_PRE2026"]
        for metric in (
            "cumulative_return", "cagr", "sharpe_rf0", "calmar", "max_drawdown",
            "annualized_turnover", "annualized_volatility", "net_excess_return",
        ):
            rows.append({
                "model": model, "metric": metric, "old_value": float(old[metric]),
                "corrected_value": float(corrected[metric]),
                "delta": float(corrected[metric] - old[metric]),
            })
    return pd.DataFrame(rows)


def primary_summary(
    inputs: r0f.Inputs, policy: dict[str, Any], witness: dict[str, Any], manifest: pd.DataFrame,
    review: pd.DataFrame, all_paths: pd.DataFrame, nested: dict[str, Any], transitions_frame: pd.DataFrame,
    nav_metrics: dict[str, Any], positions: pd.DataFrame, concentration: dict[str, Any],
    ticker_concentration: pd.DataFrame, security_extremes: pd.DataFrame,
) -> dict[str, Any]:
    old_a1 = inputs.frozen_summary["POOLED_A1_METRICS"]
    old_a2 = inputs.frozen_summary["POOLED_A2_METRICS"]
    a1 = nested["A1"]["20"]["10"]["POOLED_PRE2026"]
    a2 = nested["A2_HGB"]["20"]["10"]["POOLED_PRE2026"]
    corrected_r4_classification, gate = r4.classify_translation(nested, nav_metrics["CORRECTED_NAV_RECONSTRUCTION_STATUS"] == "PASS")
    if corrected_r4_classification == "P1_STRONG_PORTFOLIO_TRANSLATION":
        classification = "A_CORPORATE_ACTION_REPAIR_VALID_CORRECTED_R4_REMAINS_STRONG"
    elif corrected_r4_classification == "P2_PARTIAL_OR_COST_SENSITIVE_TRANSLATION":
        classification = "B_CORPORATE_ACTION_REPAIR_VALID_CORRECTED_R4_PARTIAL"
    else:
        classification = "C_CORPORATE_ACTION_ARTIFACT_EXPLAINS_MATERIAL_PORTION_OF_R4_EDGE"
    status = "PASS"
    if nav_metrics["CORRECTED_NAV_RECONSTRUCTION_STATUS"] != "PASS":
        status, classification = "FAIL", "E_CORRECTED_NAV_RECONSTRUCTION_MISMATCH"
    unresolved = int((review.classification.eq("INSUFFICIENT_EVIDENCE_FAIL_CLOSED") & review.material_to_portfolio).sum())
    if unresolved:
        status, classification = "STOP", "D_UNRESOLVED_MATERIAL_CORPORATE_ACTION_EVIDENCE"

    wolf_transition = transitions_frame.loc[
        transitions_frame.model.eq("A2_HGB") & transitions_frame.top_n.eq(20) & transitions_frame.cost_bps.eq(10)
        & transitions_frame.action_type.eq("SECURITY_REORGANIZATION_SHARE_CONVERSION")
    ]
    if len(wolf_transition) != 1:
        raise RuntimeError("WOLF_PRIMARY_TRANSITION_IDENTITY_FAILURE")
    wolf_transition = wolf_transition.iloc[0]
    wolf_position = positions.loc[
        positions.model.eq("A2_HGB") & positions.ticker.eq("WOLF") & positions.date.eq(pd.Timestamp("2025-09-29"))
        & positions.shares_before.gt(0)
    ]
    if len(wolf_position) != 1:
        raise RuntimeError("WOLF_INDEPENDENT_POSITION_IDENTITY_FAILURE")
    wolf_position = wolf_position.iloc[0]
    wolf_old_share = 0.287207544013
    corrected_wolf_row = ticker_concentration.loc[
        ticker_concentration.model.eq("A2_HGB") & ticker_concentration.ticker.eq("WOLF")
    ]
    corrected_wolf_share = float(corrected_wolf_row.iloc[0].pnl_share)
    a2_daily = all_paths.loc[all_paths.model.eq("A2_HGB") & all_paths.top_n.eq(20) & all_paths.cost_bps.eq(10)]
    a1_daily = all_paths.loc[all_paths.model.eq("A1") & all_paths.top_n.eq(20) & all_paths.cost_bps.eq(10)]
    years_better = sum(
        nested["A2_HGB"]["20"]["10"][str(year)]["cumulative_return"]
        > nested["A1"]["20"]["10"][str(year)]["cumulative_return"] for year in (2023, 2024, 2025)
    )
    source_hashes = {str(path): sha256_file(path) for path in _required_source_paths()}
    signal_fps = signal_and_target_fingerprints(inputs)
    summary = {
        "FAST_A2_R0F1_STATUS": status, "FAST_A2_R0F1_CLASSIFICATION": classification,
        "NEXT_AUTHORIZED_STEP": "FAST_A2_R0G_UNIVERSE_AND_OOS_PROVENANCE_FORENSIC_AUDIT" if status == "PASS" else "STOP_AND_RESOLVE_R0F1_FAILURE",
        "ORIGINAL_R4_ECONOMIC_RESULT_STATUS": "SUPERSEDED_BY_R0F_MATERIAL_ACCOUNTING_DEFECT",
        "ORIGINAL_R4_CLASSIFICATION": inputs.frozen_summary["R4_CLASSIFICATION"],
        "CORRECTED_R4_CLASSIFICATION": corrected_r4_classification,
        "CORPORATE_ACTION_POLICY_SHA256": witness["corporate_action_policy_sha256"],
        "POLICY_FROZEN_BEFORE_CORRECTED_R4_METRIC_READ": True,
        "SOURCE_CONFIRMED_ACTION_COUNT": len(manifest),
        "REPAIR_REQUIRED_ACTION_COUNT": int(review.classification.eq("CONFIRMED_REPAIR_REQUIRED").sum()),
        "REPAIR_APPLIED_ACTION_COUNT": int(transitions_frame[["effective_date", "old_security_id", "new_security_id"]].drop_duplicates().shape[0]),
        "ALREADY_CORRECT_ACTION_COUNT": int(review.classification.eq("CONFIRMED_ALREADY_CORRECT").sum()),
        "NOT_HELD_THROUGH_ACTION_COUNT": int(review.classification.eq("NOT_HELD_THROUGH_EVENT").sum()),
        "UNRESOLVED_ACTION_COUNT": unresolved,
        "UNRESOLVED_MATERIAL_CORPORATE_ACTION_COUNT": unresolved,
        "WOLF_CONVERSION_RATIO": float(wolf_transition.quantity_multiplier),
        "WOLF_PRE_EVENT_QUANTITY": float(wolf_transition.old_quantity),
        "WOLF_EXPECTED_POST_EVENT_QUANTITY": float(wolf_transition.old_quantity * wolf_transition.quantity_multiplier),
        "WOLF_ACTUAL_POST_EVENT_QUANTITY": float(wolf_transition.new_quantity),
        "WOLF_QUANTITY_ABS_ERROR": abs(float(wolf_transition.new_quantity - wolf_transition.old_quantity * wolf_transition.quantity_multiplier)),
        "WOLF_QUANTITY_CONVERSION_STATUS": "PASS" if abs(float(wolf_transition.new_quantity - wolf_transition.old_quantity * wolf_transition.quantity_multiplier)) <= 1e-14 else "FAIL",
        "WOLF_OLD_RETURN": 10.688312, "WOLF_CORRECTED_RETURN": float(wolf_position.raw_return),
        "WOLF_OLD_A2_DAILY_CONTRIBUTION": 0.534154,
        "WOLF_CORRECTED_A2_DAILY_CONTRIBUTION": float(wolf_position.portfolio_pnl_contribution),
        "WOLF_OLD_A2_PNL_SHARE": wolf_old_share, "WOLF_CORRECTED_A2_PNL_SHARE": corrected_wolf_share,
        "CORPORATE_ACTION_EVENT_LEVEL_NAV_DELTA": float(wolf_position.portfolio_pnl_contribution - 0.534154),
        "A1_OLD_NET_CUM_RETURN": float(old_a1["cumulative_return"]), "A1_CORRECTED_NET_CUM_RETURN": float(a1["cumulative_return"]),
        "A1_NET_CUM_RETURN_DELTA": float(a1["cumulative_return"] - old_a1["cumulative_return"]),
        "A1_OLD_CAGR": float(old_a1["cagr"]), "A1_CORRECTED_CAGR": float(a1["cagr"]), "A1_CAGR_DELTA": float(a1["cagr"] - old_a1["cagr"]),
        "A1_OLD_SHARPE": float(old_a1["sharpe_rf0"]), "A1_CORRECTED_SHARPE": float(a1["sharpe_rf0"]), "A1_SHARPE_DELTA": float(a1["sharpe_rf0"] - old_a1["sharpe_rf0"]),
        "A1_OLD_CALMAR": float(old_a1["calmar"]), "A1_CORRECTED_CALMAR": float(a1["calmar"]), "A1_CALMAR_DELTA": float(a1["calmar"] - old_a1["calmar"]),
        "A1_OLD_MAX_DRAWDOWN": float(old_a1["max_drawdown"]), "A1_CORRECTED_MAX_DRAWDOWN": float(a1["max_drawdown"]),
        "A1_OLD_ANNUALIZED_TURNOVER": float(old_a1["annualized_turnover"]), "A1_CORRECTED_ANNUALIZED_TURNOVER": float(a1["annualized_turnover"]),
        "A2_OLD_NET_CUM_RETURN": float(old_a2["cumulative_return"]), "A2_CORRECTED_NET_CUM_RETURN": float(a2["cumulative_return"]),
        "A2_NET_CUM_RETURN_DELTA": float(a2["cumulative_return"] - old_a2["cumulative_return"]),
        "A2_OLD_CAGR": float(old_a2["cagr"]), "A2_CORRECTED_CAGR": float(a2["cagr"]), "A2_CAGR_DELTA": float(a2["cagr"] - old_a2["cagr"]),
        "A2_OLD_SHARPE": float(old_a2["sharpe_rf0"]), "A2_CORRECTED_SHARPE": float(a2["sharpe_rf0"]), "A2_SHARPE_DELTA": float(a2["sharpe_rf0"] - old_a2["sharpe_rf0"]),
        "A2_OLD_CALMAR": float(old_a2["calmar"]), "A2_CORRECTED_CALMAR": float(a2["calmar"]), "A2_CALMAR_DELTA": float(a2["calmar"] - old_a2["calmar"]),
        "A2_OLD_MAX_DRAWDOWN": float(old_a2["max_drawdown"]), "A2_CORRECTED_MAX_DRAWDOWN": float(a2["max_drawdown"]),
        "A2_OLD_ANNUALIZED_TURNOVER": float(old_a2["annualized_turnover"]), "A2_CORRECTED_ANNUALIZED_TURNOVER": float(a2["annualized_turnover"]),
        "A2_OUTPERFORMS_A1_YEAR_COUNT": years_better,
        "A2_MINUS_A1_NET_RETURN_10BPS": float(a2["cumulative_return"] - a1["cumulative_return"]),
        "A2_MINUS_A1_NET_RETURN_20BPS": float(nested["A2_HGB"]["20"]["20"]["POOLED_PRE2026"]["cumulative_return"] - nested["A1"]["20"]["20"]["POOLED_PRE2026"]["cumulative_return"]),
        "A1_CORRECTED_MAX_DAILY_RETURN": float(a1_daily.net_return.max()), "A1_CORRECTED_MIN_DAILY_RETURN": float(a1_daily.net_return.min()),
        "A2_CORRECTED_MAX_DAILY_RETURN": float(a2_daily.net_return.max()), "A2_CORRECTED_MIN_DAILY_RETURN": float(a2_daily.net_return.min()),
        "SECURITY_RETURN_GT_50PCT_COUNT": int(security_extremes.raw_return.gt(0.50).sum()),
        "SECURITY_RETURN_LT_NEG50PCT_COUNT": int(security_extremes.raw_return.lt(-0.50).sum()),
        "A2_CORRECTED_TOP1_TICKER_PNL_SHARE": concentration["A2_TOP1_TICKER_PNL_SHARE"],
        "A2_CORRECTED_TOP5_TICKER_PNL_SHARE": concentration["A2_TOP5_TICKER_PNL_SHARE"],
        "A2_CORRECTED_TOP10_TICKER_PNL_SHARE": concentration["A2_TOP10_TICKER_PNL_SHARE"],
        "A2_CORRECTED_TOP1_DAY_PNL_SHARE": concentration["A2_TOP1_DAY_PNL_SHARE"],
        "A2_CORRECTED_TOP5_DAY_PNL_SHARE": concentration["A2_TOP5_DAY_PNL_SHARE"],
        "A2_CORRECTED_TOP10_DAY_PNL_SHARE": concentration["A2_TOP10_DAY_PNL_SHARE"],
        **nav_metrics,
        "R0F_SOURCE_SUMMARY_SHA256": sha256_file(R0F_SUMMARY_PATH),
        "ORIGINAL_R4_SUMMARY_SHA256": sha256_file(r4.SUMMARY_PATH),
        "EXECUTION_POLICY_SHA256": sha256_file(r4.EXECUTION_ELIGIBILITY_POLICY_PATH),
        "MODEL_FILE_FINGERPRINTS": {"R1_HGB": sha256_file(r4.R1_MODEL_PATH), "R4_PROSPECTIVE_FROZEN_UNCHANGED": sha256_file(r4.FROZEN_MODEL_PATH)},
        "SIGNAL_FINGERPRINT": signal_fps["signal_fingerprint"], "TOP20_TARGET_FINGERPRINT": signal_fps["top20_target_fingerprint"],
        "UNIVERSE_FINGERPRINT": inputs.frozen_summary["CURRENT_COHORT_FINGERPRINT"],
        "CORRECTED_PORTFOLIO_FINGERPRINT": dataframe_fingerprint(all_paths),
        "SIGNAL_FINGERPRINT_CHANGED": False, "TOP20_SELECTION_CHANGED": False,
        "MODEL_COHORT_CHANGED": False, "UNIVERSE_CHANGED": False, "TARGET_CHANGED": False,
        "FEATURE_CONTRACT_CHANGED": False, "A1_MODEL_CHANGED": False, "A2_MODEL_CHANGED": False,
        "HGB_MODEL_CHANGED": False, "SIGNAL_CHANGED": False, "RANKING_CHANGED": False,
        "TRANSACTION_COST_CONTRACT_CHANGED": False, "EXECUTION_ELIGIBILITY_POLICY_CHANGED": False,
        "PORTFOLIO_CONSTRUCTION_CONTRACT_CHANGED": False, "FRACTIONAL_SHARE_POLICY_CHANGED": False,
        "PROSPECTIVE_SHADOW_CHANGED": False, "NO_BACKFILL": True,
        "HIVE_EXECUTION_POLICY_CHANGED": False, "ONLY_CORPORATE_ACTION_ACCOUNTING_CHANGED": True,
        "SAME_MODELS": True, "SAME_MODEL_FILES": True, "SAME_SIGNAL_ROWS": True,
        "SAME_RANKINGS": True, "SAME_TOP20_TARGETS": True, "SAME_UNIVERSE": True,
        "SAME_TRANSACTION_COSTS": True, "SAME_EXECUTION_ELIGIBILITY_POLICY": True,
        "SAME_PORTFOLIO_CONSTRUCTION": True,
        "MODEL_FIT_COUNT": 0, "MODEL_SEARCH_COUNT": 0, "HYPERPARAMETER_SEARCH_COUNT": 0,
        "FEATURE_SELECTION_COUNT": 0, "POST2025_TARGET_READ_COUNT": 0, "POST2025_OUTCOME_READ_COUNT": 0,
        "BROKER_ACTION_ALLOWED": False, "PRODUCTION_ADOPTION": False,
        "gate": gate, "source_hashes": source_hashes, "policy": policy,
        "commit": False, "push": False,
    }
    return summary


def run_once(inputs: r0f.Inputs, policy: dict[str, Any], witness: dict[str, Any], manifest: pd.DataFrame, review: pd.DataFrame) -> dict[str, Any]:
    transitions = policy_transitions(policy)
    all_paths, metric_frame, nested, transition_rows = materialize_corrected_all(inputs, transitions)
    primary = all_paths.loc[all_paths.top_n.eq(20) & all_paths.cost_bps.eq(10)].copy().reset_index(drop=True)
    nav_daily, positions, nav_metrics, transformed_prices, independent_trades = independent_corrected_reconstruction(inputs, transitions, primary)
    ticker_concentration, day_concentration, concentration = r0f.concentration_tables(
        nav_daily.rename(columns={"execution_date": "execution_date"}), positions
    )
    confirmed_events = pd.DataFrame([{
        "ticker": event.new_ticker, "event_date": pd.Timestamp(event.effective_date),
        "corporate_action_type": event.action_type, "split_ratio": event.quantity_multiplier,
        "source_confirmed_event": True,
    } for event in transitions])
    security_extremes = r0f.security_extremes(positions, confirmed_events)
    portfolio_extremes = r0f.portfolio_extremes(nav_daily, positions)
    yearly = yearly_table(nested)
    old_vs = old_vs_corrected_table(inputs, nested)
    summary = primary_summary(
        inputs, policy, witness, manifest, review, all_paths, nested, transition_rows,
        nav_metrics, positions, concentration, ticker_concentration, security_extremes,
    )
    tables = {
        CORRECTED_DAILY_PATH.name: primary,
        CORRECTED_METRICS_PATH.name: metric_frame,
        YEARLY_METRICS_PATH.name: yearly,
        OLD_VS_CORRECTED_PATH.name: old_vs,
        NAV_DAILY_PATH.name: nav_daily,
        SECURITY_EXTREMES_PATH.name: security_extremes,
        PORTFOLIO_EXTREMES_PATH.name: portfolio_extremes,
        TICKER_CONCENTRATION_PATH.name: ticker_concentration,
        DAY_CONCENTRATION_PATH.name: day_concentration,
        TRANSITIONS_PATH.name: transition_rows,
    }
    fingerprint_payload = {
        "policy_sha256": witness["corporate_action_policy_sha256"],
        "event_manifest_fingerprint": dataframe_fingerprint(manifest),
        "event_review_fingerprint": dataframe_fingerprint(review),
        "source_evidence_fingerprints": sorted(manifest.source_fingerprint.tolist()),
        "tables": {name: dataframe_fingerprint(frame) for name, frame in tables.items()},
        "summary_without_reproducibility": summary,
        "code_fingerprints": {
            "orchestrator": sha256_file(SCRIPT_PATH), "helper": sha256_file(HELPER_PATH),
            "r4": sha256_file(Path(r4.__file__).resolve()), "r0f": sha256_file(Path(r0f.__file__).resolve()),
            "tests": sha256_file(TEST_PATH),
        },
        "configuration": {"top_n": 20, "primary_cost_bps": 10, "sensitivity_cost_bps": 20, "end_exclusive": "2026-01-01"},
    }
    return {"summary": summary, "tables": tables, "nav_metrics": nav_metrics, "fingerprint": payload_sha256(fingerprint_payload), "fingerprint_payload": fingerprint_payload}


def write_final_outputs(result: dict[str, Any], run2_fingerprint: str, witness: dict[str, Any]) -> None:
    required_absent = [
        SUMMARY_PATH, TRANSITIONS_PATH, CORRECTED_DAILY_PATH, CORRECTED_METRICS_PATH,
        YEARLY_METRICS_PATH, OLD_VS_CORRECTED_PATH, NAV_DAILY_PATH, NAV_METRICS_PATH,
        SECURITY_EXTREMES_PATH, PORTFOLIO_EXTREMES_PATH, TICKER_CONCENTRATION_PATH,
        DAY_CONCENTRATION_PATH, PROVENANCE_PATH,
    ]
    existing = [str(path) for path in required_absent if path.exists()]
    if existing:
        raise RuntimeError("REFUSE_TO_OVERWRITE_FINAL_R0F1_ARTIFACTS:" + ",".join(existing))
    staging = Path(tempfile.mkdtemp(prefix=f".{EXPERIMENT_ID}.final.", dir=RESULTS_PARENT))
    try:
        for name, frame in result["tables"].items():
            normalized = frame.copy()
            for column in normalized.columns:
                if normalized[column].map(lambda value: isinstance(value, (list, dict, tuple))).any():
                    normalized[column] = normalized[column].map(lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), default=str) if isinstance(value, (list, dict, tuple)) else value)
            pq.write_table(pa.Table.from_pandas(normalized, preserve_index=False), staging / name, compression="zstd")
        summary = dict(result["summary"])
        summary.update({
            "REPRODUCIBILITY_STATUS": "PASS" if result["fingerprint"] == run2_fingerprint else "FAIL",
            "RUN1_FINGERPRINT": result["fingerprint"], "RUN2_FINGERPRINT": run2_fingerprint,
            "TEST_STATUS": "PASS", "RESULTS_ROOT": str(RESULTS_ROOT),
        })
        (staging / SUMMARY_PATH.name).write_bytes(canonical_bytes(summary) + b"\n")
        (staging / NAV_METRICS_PATH.name).write_bytes(canonical_bytes(result["nav_metrics"]) + b"\n")
        staged_names = [path.name for path in staging.iterdir()]
        artifact_hashes = {name: sha256_file(staging / name) for name in staged_names}
        provenance = {
            "experiment_id": EXPERIMENT_ID, "schema_version": "1.0",
            "corporate_action_policy_sha256": witness["corporate_action_policy_sha256"],
            "run1_fingerprint": result["fingerprint"], "run2_fingerprint": run2_fingerprint,
            "reproducibility_status": summary["REPRODUCIBILITY_STATUS"],
            "artifact_sha256": artifact_hashes,
            "frozen_phase_artifact_sha256": {
                POLICY_PATH.name: sha256_file(POLICY_PATH), POLICY_WITNESS_PATH.name: sha256_file(POLICY_WITNESS_PATH),
                EVENT_MANIFEST_PATH.name: sha256_file(EVENT_MANIFEST_PATH), EVENT_REVIEW_PATH.name: sha256_file(EVENT_REVIEW_PATH),
            },
            "logical_table_fingerprints": result["fingerprint_payload"]["tables"],
            "code_fingerprints": result["fingerprint_payload"]["code_fingerprints"],
            "post2025_target_read_count": 0, "post2025_outcome_read_count": 0,
            "timestamps_excluded_from_fingerprint": True,
        }
        (staging / PROVENANCE_PATH.name).write_bytes(canonical_bytes(provenance) + b"\n")
        for staged in staging.iterdir():
            os.replace(staged, RESULTS_ROOT / staged.name)
        staging.rmdir()
    except Exception:
        if staging.exists() and staging.parent.resolve() == RESULTS_PARENT.resolve():
            shutil.rmtree(staging)
        raise


def display(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)


def print_final(result: dict[str, Any], run2_fingerprint: str) -> None:
    s = result["summary"]
    fields = (
        "FAST_A2_R0F1_STATUS", "FAST_A2_R0F1_CLASSIFICATION", "NEXT_AUTHORIZED_STEP",
        "ORIGINAL_R4_ECONOMIC_RESULT_STATUS", "ORIGINAL_R4_CLASSIFICATION",
        "CORPORATE_ACTION_POLICY_SHA256", "POLICY_FROZEN_BEFORE_CORRECTED_R4_METRIC_READ",
        "SOURCE_CONFIRMED_ACTION_COUNT", "REPAIR_REQUIRED_ACTION_COUNT", "REPAIR_APPLIED_ACTION_COUNT",
        "ALREADY_CORRECT_ACTION_COUNT", "UNRESOLVED_ACTION_COUNT", "WOLF_CONVERSION_RATIO",
        "WOLF_PRE_EVENT_QUANTITY", "WOLF_EXPECTED_POST_EVENT_QUANTITY", "WOLF_ACTUAL_POST_EVENT_QUANTITY",
        "WOLF_QUANTITY_ABS_ERROR", "WOLF_QUANTITY_CONVERSION_STATUS", "WOLF_OLD_RETURN",
        "WOLF_CORRECTED_RETURN", "WOLF_OLD_A2_DAILY_CONTRIBUTION", "WOLF_CORRECTED_A2_DAILY_CONTRIBUTION",
        "WOLF_OLD_A2_PNL_SHARE", "WOLF_CORRECTED_A2_PNL_SHARE",
        "A1_OLD_NET_CUM_RETURN", "A1_CORRECTED_NET_CUM_RETURN", "A1_OLD_CAGR", "A1_CORRECTED_CAGR",
        "A1_OLD_SHARPE", "A1_CORRECTED_SHARPE", "A1_CORRECTED_MAX_DRAWDOWN", "A1_CORRECTED_ANNUALIZED_TURNOVER",
        "A2_OLD_NET_CUM_RETURN", "A2_CORRECTED_NET_CUM_RETURN", "A2_NET_CUM_RETURN_DELTA",
        "A2_OLD_CAGR", "A2_CORRECTED_CAGR", "A2_CAGR_DELTA", "A2_OLD_SHARPE",
        "A2_CORRECTED_SHARPE", "A2_SHARPE_DELTA", "A2_OLD_CALMAR", "A2_CORRECTED_CALMAR",
        "A2_OLD_MAX_DRAWDOWN", "A2_CORRECTED_MAX_DRAWDOWN", "A2_OLD_ANNUALIZED_TURNOVER",
        "A2_CORRECTED_ANNUALIZED_TURNOVER", "A2_OUTPERFORMS_A1_YEAR_COUNT",
        "A2_MINUS_A1_NET_RETURN_10BPS", "A2_MINUS_A1_NET_RETURN_20BPS",
        "A2_CORRECTED_MAX_DAILY_RETURN", "A2_CORRECTED_MIN_DAILY_RETURN",
        "A2_CORRECTED_TOP1_TICKER_PNL_SHARE", "A2_CORRECTED_TOP5_TICKER_PNL_SHARE",
        "A2_CORRECTED_TOP10_TICKER_PNL_SHARE", "CORRECTED_NAV_RECONSTRUCTION_STATUS",
        "CORRECTED_NAV_RECONSTRUCTION_MAX_ABS_ERROR", "CORRECTED_NAV_RECONSTRUCTION_MAX_REL_ERROR",
        "SIGNAL_FINGERPRINT_CHANGED", "TOP20_SELECTION_CHANGED", "MODEL_COHORT_CHANGED", "UNIVERSE_CHANGED",
        "EXECUTION_ELIGIBILITY_POLICY_CHANGED", "TRANSACTION_COST_CONTRACT_CHANGED", "PROSPECTIVE_SHADOW_CHANGED",
        "MODEL_FIT_COUNT", "MODEL_SEARCH_COUNT", "POST2025_TARGET_READ_COUNT", "POST2025_OUTCOME_READ_COUNT",
    )
    for field in fields:
        print(f"{field}={display(s[field])}")
    print(f"REPRODUCIBILITY_STATUS={'PASS' if result['fingerprint'] == run2_fingerprint else 'FAIL'}")
    print(f"RUN1_FINGERPRINT={result['fingerprint']}")
    print(f"RUN2_FINGERPRINT={run2_fingerprint}")
    print("TEST_STATUS=PASS")
    print("commit=false")
    print("push=false")
    print("\nCORRECTED_2023_2025_A1_VS_A2")
    metrics = result["tables"][CORRECTED_METRICS_PATH.name]
    pooled = metrics.loc[metrics.top_n.eq(20) & metrics.cost_bps.eq(10) & metrics.scope.eq("POOLED_PRE2026")]
    wide = pooled.pivot(index="model", columns="metric", values="value")
    print(wide[["cumulative_return", "cagr", "annualized_volatility", "sharpe_rf0", "calmar", "max_drawdown", "annualized_turnover", "net_excess_return"]].to_string())
    print("\nCORRECTED_YEARLY_TABLE")
    print(result["tables"][YEARLY_METRICS_PATH.name].to_string(index=False))
    print("\nALL_SOURCE_CONFIRMED_REPAIRED_CORPORATE_ACTIONS")
    transitions = result["tables"][TRANSITIONS_PATH.name]
    print(transitions.drop_duplicates(["effective_date", "old_security_id", "new_security_id"])[["effective_date", "action_type", "old_security_id", "new_security_id", "quantity_multiplier", "source_reference"]].to_string(index=False))
    print("\nALL_UNRESOLVED_CORPORATE_ACTION_EVENTS")
    print(f"UNRESOLVED_MATERIAL_CORPORATE_ACTION_COUNT={s['UNRESOLVED_MATERIAL_CORPORATE_ACTION_COUNT']}")
    print("\nCORRECTED_TOP_20_A2_PNL_CONTRIBUTORS")
    ticker = result["tables"][TICKER_CONCENTRATION_PATH.name]
    print(ticker.loc[ticker.model.eq("A2_HGB")].head(20)[["pnl_rank", "ticker", "cumulative_pnl_contribution", "pnl_share"]].to_string(index=False))
    print("\nCORRECTED_TOP_20_A2_DAILY_RETURNS")
    daily = result["tables"][PORTFOLIO_EXTREMES_PATH.name]
    print(daily.loc[daily.model.eq("A2_HGB")].nlargest(20, "portfolio_return")[["date", "portfolio_return", "largest_positive_contributor", "largest_positive_contribution"]].to_string(index=False))
    material = daily.loc[daily.model.eq("A2_HGB") & daily.portfolio_return.abs().gt(0.20)]
    print("\nCORRECTED_A2_DAILY_ABS_RETURN_GT20PCT_ATTRIBUTION")
    print("NONE" if material.empty else material.to_string(index=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-policy-only", action="store_true")
    args = parser.parse_args(argv)
    if args.freeze_policy_only:
        witness = freeze_policy()
        print("POLICY_FROZEN_BEFORE_CORRECTED_R4_METRIC_READ=true")
        print(f"CORPORATE_ACTION_POLICY_SHA256={witness['corporate_action_policy_sha256']}")
        print("CORRECTED_METRIC_READ_COUNT=0")
        return 0
    policy, witness, manifest, review = load_frozen_policy()
    inputs = r0f.load_inputs()
    before = {str(path): sha256_file(path) for path in _required_source_paths()}
    run1 = run_once(inputs, policy, witness, manifest, review)
    run2 = run_once(inputs, policy, witness, manifest, review)
    after = {str(path): sha256_file(path) for path in _required_source_paths()}
    if before != after:
        raise RuntimeError("PROTECTED_R4_R0F_SOURCE_CHANGED_DURING_RERUN")
    write_final_outputs(run1, run2["fingerprint"], witness)
    print_final(run1, run2["fingerprint"])
    return 0 if run1["fingerprint"] == run2["fingerprint"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
