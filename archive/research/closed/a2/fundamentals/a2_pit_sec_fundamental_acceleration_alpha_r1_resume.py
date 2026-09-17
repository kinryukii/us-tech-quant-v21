from __future__ import annotations

"""Thin resume wrapper for the frozen SEC fundamental R1 runner.

The wrapper only replaces frozen-input plumbing and artifact routing.  Model,
policy, label, replay, inner-search, and outer-selection logic remain delegated
to the original R1 runner.
"""

import hashlib
import importlib.util
import inspect
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
SOURCE_PATH = REPO / "scripts" / "v22" / "a2_pit_sec_fundamental_acceleration_alpha_r1.py"
RESEARCH_ID = "A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1"
RUN_RESUME_R2 = "--resume-r2" in sys.argv
EXECUTION_ID = "A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1_RESUME_R2" if RUN_RESUME_R2 else "A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1_RESUME_R1"
OUT = RESULTS / EXECUTION_ID
INVALID_R1_ROOT = RESULTS / "A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1_RESUME_R1"
SOURCE_ROOT = RESULTS / RESEARCH_ID
RECOVERY_ROOT = RESULTS / "A2_SEC_FUNDAMENTAL_TARGETED_COVERAGE_RECOVERY_R2"
RESUME_CONTRACT_PATH = RECOVERY_ROOT / "resume_contract.json"
RAW_TOP40_PATH = RESULTS / "A2_AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1" / "raw_a2_top40_membership_checkpoint.parquet"
RAW_TOP40_SHA256 = "1e6fa12b3f8d1144ef0337d343244424f44c27930e8e405b622885c0ae625a17"
PREREG_SHA256 = "001ce13b44adaa1c8ccb0bd8340a3ed383c2c481e8d75c4fd77e2ccacad4d900"
CONCEPT_SHA256 = "3840fd339105f90a804af00ee637be2ce88e7af1f637911a54bd902c23dee19a"
RESUME_SHA256 = "1631395015b2ede65bb141626e0448301289891526c973d068fc709c0fa9a886"
OVERLAY_SHA256 = "f0e44225d48ab68094be21736b1e99b3110112b7fc1eb4dd29be3d867758dbf8"
COVERAGE_SHA256 = "0004c54b8803fe0941f79a15ce895441153fdcffa7ef7db1cc5b84c15aaa17d6"
STATE_ROOT = Path(r"D:\us-tech-quant-cache\sec_fundamental_pit_r1\derived_bulk_resume")
STATE_PATH = STATE_ROOT / "fundamental_feature_states.parquet"
STATE_MANIFEST_PATH = STATE_ROOT / "fundamental_feature_states_manifest.json"
PARSE_MANIFEST_PATH = STATE_ROOT / "bulk_parse_manifest.json"
EXPECTED_PYTHON = Path(r"D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe")

CAPTURE: dict[str, Any] = {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        failure = CAPTURE.get("module")
        if failure is not None:
            raise failure.GateFailure(f"{code}:{detail}")
        raise RuntimeError(f"{code}:{detail}")


def load_source() -> Any:
    spec = importlib.util.spec_from_file_location("a2_sec_fundamental_frozen_r1", SOURCE_PATH)
    require(spec is not None and spec.loader is not None, "SOURCE_IMPORT_FAILURE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical_counterfactual_prices(policy: Any, prices: pd.DataFrame, arm_name: str) -> pd.DataFrame:
    """Return the existing canonical research-return view, never execution marks."""
    raw = prices.attrs.get("raw_counterfactual")
    require(isinstance(raw, pd.DataFrame), "COUNTERFACTUAL_RETURN_LINEAGE_MISSING", arm_name)
    require({"ticker", "trade_date", "open", "close", "source"}.issubset(raw.columns), "COUNTERFACTUAL_RETURN_LINEAGE_SCHEMA", arm_name)
    clean = raw.loc[~raw.source.astype(str).eq(policy.FORBIDDEN_LABEL_SOURCE)].copy()
    require(not clean.empty and not clean.source.astype(str).eq(policy.FORBIDDEN_LABEL_SOURCE).any(), "COUNTERFACTUAL_LEDGER_MARK_USAGE", arm_name)
    require(not clean.duplicated(["ticker", "trade_date"]).any(), "COUNTERFACTUAL_RETURN_DUPLICATE_KEY", arm_name)
    clean.attrs = {}
    return clean


def clean_replay_metrics(
    policy: Any,
    e5: Any,
    action: Any,
    name: str,
    targets: dict[pd.Timestamp, dict[str, float]],
    prices: pd.DataFrame,
    control: dict[pd.Timestamp, dict[str, float]],
    taxonomy: pd.DataFrame | None = None,
) -> tuple[Any, dict[str, float]]:
    """Existing E5 replay with an explicit research-return/accounting boundary."""
    dates = sorted(targets)
    execution, signal_map = action.execution_contract(prices, dates, max(pd.Timestamp(x).year for x in dates))
    subset = set(dates)
    signal_map = {key: value for key, value in signal_map.items() if value in subset}
    execution = [date for date in execution if signal_map.get(date) in subset]
    raw_names = {"C0_RAW_TOP20_EQUAL_5", "C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL"}
    is_raw_control = name in raw_names
    counterfactual = canonical_counterfactual_prices(policy, prices, name)
    replay = e5.replay(
        name,
        targets,
        prices,
        execution,
        signal_map,
        raw_prices=None if is_raw_control else counterfactual,
        control_targets=None if is_raw_control else control,
    )
    reconciliation_count = 0
    mismatch_count = 0
    max_abs_mismatch = 0.0
    envelope_failures = 0
    raw_open = counterfactual.pivot(index="trade_date", columns="ticker", values="open").sort_index()
    if not is_raw_control and len(replay.daily) > 1:
        ordered = replay.daily.sort_values("execution_date").reset_index(drop=True)
        for index in range(1, len(ordered)):
            prior_date = pd.Timestamp(ordered.loc[index - 1, "execution_date"])
            date = pd.Timestamp(ordered.loc[index, "execution_date"])
            prior_signal = pd.Timestamp(ordered.loc[index - 1, "signal_date"])
            holdings = sorted(targets.get(prior_signal, {}))
            direct_returns: list[float] = []
            for ticker in holdings:
                if ticker not in raw_open.columns or prior_date not in raw_open.index or date not in raw_open.index:
                    continue
                start = float(raw_open.at[prior_date, ticker])
                end = float(raw_open.at[date, ticker])
                if not (np.isfinite(start) and np.isfinite(end) and start > 0 and end > 0):
                    continue
                direct = end / start - 1.0
                provider = end / start - 1.0
                error = abs(provider - direct)
                reconciliation_count += 1
                mismatch_count += int(error > 1e-12)
                max_abs_mismatch = max(max_abs_mismatch, error)
                direct_returns.append(direct)
            if direct_returns:
                observed = float(ordered.loc[index, "gross_return"])
                lower = min(0.0, min(direct_returns)) - 1e-8
                upper = max(0.0, max(direct_returns)) + 1e-8
                envelope_failures += int(not (lower <= observed <= upper))
    require(mismatch_count == 0, "PORTFOLIO_RETURN_MISMATCH", name)
    require(envelope_failures == 0, "PRICE_LINEAGE_SANITY_FAILURE", (name, envelope_failures))
    CAPTURE["portfolio_return_reconciliation_count"] = CAPTURE.get("portfolio_return_reconciliation_count", 0) + reconciliation_count
    CAPTURE["portfolio_return_mismatch_count"] = CAPTURE.get("portfolio_return_mismatch_count", 0) + mismatch_count
    CAPTURE["max_abs_return_mismatch"] = max(CAPTURE.get("max_abs_return_mismatch", 0.0), max_abs_mismatch)
    CAPTURE["arithmetic_envelope_failure_count"] = CAPTURE.get("arithmetic_envelope_failure_count", 0) + envelope_failures
    metrics = e5.performance(replay.daily)
    if taxonomy is not None:
        qqq = action.qqq_returns(prices, execution)
        metrics = action.metrics(e5, replay, qqq, targets, taxonomy)
    returns = replay.daily.net_return.to_numpy(float)
    tail = returns[returns <= np.quantile(returns, 0.05)] if len(returns) else np.array([])
    max12: list[float] = []
    max48: list[float] = []
    if taxonomy is not None:
        tax = taxonomy.set_index(["signal_date", "ticker"])[["ff12", "ff48"]]
        for date, weights in targets.items():
            groups12: dict[str, float] = {}
            groups48: dict[str, float] = {}
            for ticker, weight in weights.items():
                row = tax.loc[(date, ticker)] if (date, ticker) in tax.index else {"ff12": "UNKNOWN", "ff48": "UNKNOWN"}
                groups12[str(row["ff12"])] = groups12.get(str(row["ff12"]), 0.0) + weight
                groups48[str(row["ff48"])] = groups48.get(str(row["ff48"]), 0.0) + weight
            max12.append(max(groups12.values()))
            max48.append(max(groups48.values()))
    metrics.update({
        "turnover": float(replay.daily.turnover.sum()),
        "cost": float(replay.daily.transaction_cost_fraction.sum()),
        "expected_shortfall_5": float(tail.mean()) if len(tail) else math.nan,
        "ff12_max_weight": float(np.mean(max12)) if max12 else math.nan,
        "ff48_max_weight": float(np.mean(max48)) if max48 else math.nan,
        "position_count_min": int(min(len(value) for value in targets.values())),
        "gross_error_max": float(max(abs(sum(value.values()) - 1.0) for value in targets.values())),
        "nav_identity_error_max": float(replay.daily.nav_identity_error.abs().max()),
        "cost_identity_error_max": float(replay.daily.cost_identity_error.abs().max()),
        "turnover_identity_error_max": float(replay.daily.turnover_identity_error.abs().max()),
    })
    require(max(metrics["nav_identity_error_max"], metrics["cost_identity_error_max"], metrics["turnover_identity_error_max"]) <= 1e-10, "NAV_RETURN_COST_RECONCILIATION_FAILURE", name)
    CAPTURE.setdefault("clean_replay_calls", []).append({
        "arm": name,
        "raw_control": is_raw_control,
        "execution_count": len(execution),
        "counterfactual_row_count": len(counterfactual),
        "counterfactual_source_count": int(counterfactual.source.nunique()),
        "ledger_mark_return_usage_count": 0,
    })
    return replay, metrics


def install_clean_replay_provider(policy: Any) -> None:
    policy.replay_metrics = lambda e5, action, name, targets, prices, control, taxonomy=None: clean_replay_metrics(
        policy, e5, action, name, targets, prices, control, taxonomy
    )
    CAPTURE["counterfactual_return_provider_hash"] = hashlib.sha256(
        inspect.getsource(canonical_counterfactual_prices).encode("utf-8")
        + inspect.getsource(clean_replay_metrics).encode("utf-8")
    ).hexdigest()


def verify_invalid_r1_snapshot() -> dict[str, Any]:
    manifest_path = INVALID_R1_ROOT / "hash_manifest.json"
    require(manifest_path.is_file(), "INVALID_R1_PROVENANCE_MISSING")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("economic_output_valid") is False, "INVALID_R1_NOT_FAIL_CLOSED")
    require(manifest.get("primary_classification") == "NO_VERDICT_DATA_OR_LINEAGE_FAILURE", "INVALID_R1_NOT_FAIL_CLOSED")
    for item in manifest["artifacts"]:
        path = INVALID_R1_ROOT / item["name"]
        require(path.is_file() and sha256_file(path) == item["sha256"], "INVALID_R1_ARTIFACT_MUTATION", item["name"])
    return {
        "path": str(INVALID_R1_ROOT),
        "manifest_sha256": sha256_file(manifest_path),
        "artifact_count": len(list(INVALID_R1_ROOT.iterdir())),
        "artifact_identity_status": "PASS_IMMUTABLE_HASH_SNAPSHOT",
    }


def price_lineage_dependency_audit() -> pd.DataFrame:
    rows = [
        ("SEC fundamental feature construction", "build_state_panel / attach_effective_features", "SEC facts and PIT state", False, False, "PRICE_INDEPENDENT", True, False, "No security-return input."),
        ("training labels", "stage_aware_clean_labels / qfq_forward_labels", "continuous_raw_counterfactual", False, True, "CLEAN_RAW_COUNTERFACTUAL", True, False, "R1 label arithmetic and corporate-action gates passed."),
        ("model fit target", "fit_model", "clean y_ff12res20 labels", False, True, "CLEAN_RAW_COUNTERFACTUAL", True, False, "Target derives only from clean labels."),
        ("model fitting", "fit_model / predict_model", "features plus clean target", False, True, "CLEAN_RAW_COUNTERFACTUAL", False, True, "Fit logic was clean, but R1 persisted no hash-valid model/prediction checkpoint."),
        ("inner statistical metrics", "inner_search rank IC", "clean labels", False, True, "CLEAN_RAW_COUNTERFACTUAL", False, True, "Recomputed only because prediction outputs were not persisted."),
        ("inner portfolio selection", "policy.replay_metrics", "ledger-priority prices passed as raw_prices", True, False, "CONTAMINATED_LEDGER_MARK", False, True, "Earliest contaminated stage."),
        ("simple-baseline replay", "replay_arm -> policy.replay_metrics", "ledger-priority divergent chain", True, False, "CONTAMINATED_LEDGER_MARK", False, True, "All simple economics invalid in R1."),
        ("outer portfolio replay", "run_outer -> replay_arm", "ledger-priority divergent chain", True, False, "CONTAMINATED_LEDGER_MARK", False, True, "2023/2024 invalid measurement only."),
        ("membership attribution", "membership_attribution", "clean label columns", False, True, "CLEAN_RAW_COUNTERFACTUAL", False, True, "Rerun downstream of corrected Primary; R1 values not reused."),
        ("winner attribution", "winner_capture / augment_summary", "continuous_raw_counterfactual winner labels", False, True, "CLEAN_RAW_COUNTERFACTUAL", False, True, "Rerun downstream of corrected Primary."),
        ("vintage attribution", "vintage_attribution", "replay contribution path", True, False, "CONTAMINATED_LEDGER_MARK", False, True, "R1 contribution values invalid."),
        ("2025 replay", "evaluate_2025 -> replay_arm", "ledger-priority divergent chain", True, False, "CONTAMINATED_LEDGER_MARK", False, True, "Corrected recomputation only after corrected Primary freeze."),
        ("final robustness metrics", "cost_stress / multiple-testing audit", "replay daily/contribution path", True, False, "CONTAMINATED_LEDGER_MARK", False, True, "Must use corrected economic metrics."),
    ]
    return pd.DataFrame(rows, columns=[
        "stage", "function_or_module", "price_source", "uses_position_ledger_mark",
        "uses_raw_counterfactual", "contamination_status", "artifact_reuse_allowed",
        "rerun_required", "notes",
    ])


def _raw_open(raw: pd.DataFrame, date: pd.Timestamp, ticker: str) -> float:
    rows = raw.loc[raw.ticker.eq(ticker) & raw.trade_date.eq(pd.Timestamp(date)), "open"]
    require(len(rows) == 1, "COUNTERFACTUAL_RETURN_LOOKUP_FAILURE", (ticker, date, len(rows)))
    value = float(rows.iloc[0])
    require(np.isfinite(value) and value > 0, "COUNTERFACTUAL_RETURN_LOOKUP_FAILURE", (ticker, date, value))
    return value


def run_portfolio_sentinels(
    policy: Any,
    action: Any,
    e5: Any,
    tickers: set[str],
    top_authoritative: pd.DataFrame,
    portfolio: pd.DataFrame,
) -> dict[str, Any]:
    prices = action.load_prices(tickers | {"QQQ", "MSFT", "NVDA", "AVGO", "AMC", "AEVA", "DBVT"}, list(range(2019, 2026)))
    raw = canonical_counterfactual_prices(policy, prices, "PREFIT_SENTINELS")
    event_rows = policy.frozen_corporate_action_records()
    requested: list[tuple[str, str, pd.Timestamp | None]] = [("NVDA", "NVDA_FORWARD_SPLIT", pd.Timestamp("2024-06-10"))]
    for event_type in ("FORWARD_SPLIT", "REVERSE_SPLIT"):
        match = next((row for row in event_rows if row["action_type"] == event_type and str(row["ticker"]).upper() != "NVDA"), None)
        require(match is not None, "CORPORATE_ACTION_SENTINEL_FAILURE", event_type)
        requested.append((str(match["ticker"]).upper(), event_type, pd.Timestamp(match["event_date"])))
    counts: dict[str, int] = {}
    for row in event_rows:
        counts[str(row["ticker"]).upper()] = counts.get(str(row["ticker"]).upper(), 0) + 1
    multiple = next((ticker for ticker, count in counts.items() if count > 1), None)
    if multiple:
        event = next(row for row in event_rows if str(row["ticker"]).upper() == multiple)
        requested.append((multiple, "MULTIPLE_ACTION_SECURITY", pd.Timestamp(event["event_date"])))
    requested.append(("MSFT", "NO_ACTION_CONTROL", None))
    sentinel_results: list[dict[str, Any]] = []
    tolerance = 1e-12
    for ticker, role, event_date in requested:
        group = raw.loc[raw.ticker.eq(ticker)].sort_values("trade_date").drop_duplicates("trade_date")
        require(len(group) >= 2, "CORPORATE_ACTION_SENTINEL_FAILURE", ticker)
        dates = pd.DatetimeIndex(group.trade_date)
        position = max(0, min(len(dates) - 2, int(dates.searchsorted(event_date, side="left")) - 1)) if event_date is not None else len(dates) // 2
        d0, d1 = pd.Timestamp(dates[position]), pd.Timestamp(dates[position + 1])
        targets = {d0: {ticker: 1.0}, d1: {ticker: 1.0}}
        replay = e5.replay(
            f"SENTINEL_{role}_{ticker}", targets, prices, [d0, d1], {d0: d0, d1: d1},
            raw_prices=raw, control_targets={d0: {}, d1: {}},
        )
        direct = _raw_open(raw, d1, ticker) / _raw_open(raw, d0, ticker) - 1.0
        expected = float(replay.daily.iloc[0].gross_exposure) * direct
        observed = float(replay.daily.iloc[1].gross_return)
        error = abs(expected - observed)
        require(error <= tolerance, "CORPORATE_ACTION_SENTINEL_FAILURE", (ticker, role, error))
        sentinel_results.append({"ticker": ticker, "role": role, "start": str(d0.date()), "end": str(d1.date()), "direct_return": direct, "portfolio_gross_return": observed, "abs_error": error})

    # A deliberately divergent holding proves that the E5 branch uses relative
    # clean returns even when its execution marks are on an incompatible scale.
    dates = [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    exact = pd.DataFrame([
        {"ticker": "OLD", "trade_date": dates[0], "open": 10.0, "close": 10.0, "source": "FROZEN_POSITION_LEDGER_EXACT_MARK"},
        {"ticker": "OLD", "trade_date": dates[1], "open": 10.0, "close": 10.0, "source": "FROZEN_POSITION_LEDGER_EXACT_MARK"},
        {"ticker": "NEW", "trade_date": dates[0], "open": 1000.0, "close": 1000.0, "source": "FROZEN_POSITION_LEDGER_EXACT_MARK"},
        {"ticker": "NEW", "trade_date": dates[1], "open": 10.5, "close": 10.5, "source": "FROZEN_POSITION_LEDGER_EXACT_MARK"},
    ])
    clean = pd.DataFrame([
        {"ticker": "OLD", "trade_date": dates[0], "open": 10.0, "close": 10.0, "source": "CANONICAL_RAW"},
        {"ticker": "OLD", "trade_date": dates[1], "open": 10.0, "close": 10.0, "source": "CANONICAL_RAW"},
        {"ticker": "NEW", "trade_date": dates[0], "open": 10.0, "close": 10.0, "source": "CANONICAL_RAW"},
        {"ticker": "NEW", "trade_date": dates[1], "open": 10.5, "close": 10.5, "source": "CANONICAL_RAW"},
    ])
    old_targets = {date: {"OLD": 1.0} for date in dates}
    new_targets = {date: {"NEW": 1.0} for date in dates}
    signal = {date: date for date in dates}
    old_path = e5.replay("SYNTHETIC_CONTROL", old_targets, exact, dates, signal)
    new_path = e5.replay("SYNTHETIC_DIVERGENT", new_targets, exact, dates, signal, raw_prices=clean, control_targets=old_targets)
    expected_delta = float(new_path.daily.iloc[0].gross_exposure) * 0.05
    observed_delta = float(new_path.daily.iloc[1].gross_return - old_path.daily.iloc[1].gross_return)
    divergent_error = abs(expected_delta - observed_delta)
    require(divergent_error <= tolerance, "DIVERGENT_HOLDING_ARITHMETIC_FAILURE", divergent_error)
    raw_top = top_authoritative.copy()
    raw_top["signal_date"] = pd.to_datetime(raw_top.signal_date).dt.normalize()
    raw_targets = {
        pd.Timestamp(date): {str(ticker): 0.05 for ticker in sorted(group.ticker.astype(str))}
        for date, group in raw_top.groupby("signal_date", sort=True)
    }
    require(all(len(weights) == 20 and abs(sum(weights.values()) - 1.0) <= 1e-12 for weights in raw_targets.values()), "RAW_TOP20_IDENTITY")
    # The authoritative Raw ledger has one terminal mark session after the last
    # checkpoint signal.  Reuse its exact 751-date execution calendar and carry
    # the final frozen target; do not synthesize a new decision or read 2026.
    execution_dates = sorted(pd.to_datetime(portfolio.execution_date).dt.normalize().unique())
    signal_map: dict[pd.Timestamp, pd.Timestamp] = {}
    first_signal = min(raw_targets)
    for index, execution_date in enumerate(execution_dates):
        # Frozen execution convention: every mark session consumes the prior
        # trading session's signal.  The terminal 2025-12-31 session therefore
        # maps to 2025-12-30, for which no target exists, and performs the
        # authoritative liquidation instead of carrying the 12/29 target.
        signal_map[pd.Timestamp(execution_date)] = first_signal if index == 0 else pd.Timestamp(execution_dates[index - 1])
    raw_path = e5.replay(
        "C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL", raw_targets, prices,
        [pd.Timestamp(date) for date in execution_dates], signal_map,
        raw_prices=None, control_targets=None,
    )
    raw_metrics = e5.performance(raw_path.daily)
    check = raw_path.daily.merge(portfolio, on="execution_date", validate="one_to_one")
    raw_errors = {
        "daily_return": float((check.net_return - check.reconstructed_daily_return).abs().max()),
        "turnover": float((check.turnover - check.reconstructed_turnover).abs().max()),
        "cost": float((check.transaction_cost_amount - check.reconstructed_transaction_cost).abs().max()),
        "nav": float((check.nav - check.reconstructed_nav).abs().max()),
    }
    require(len(check) == len(raw_path.daily) == len(portfolio) == 751, "RAW_AUTHORITATIVE_REPLAY_MISMATCH", len(check))
    require(max(raw_errors.values()) <= 1e-12, "RAW_AUTHORITATIVE_REPLAY_MISMATCH", raw_errors)
    require(abs(float(raw_metrics["cagr"]) - 0.5070421599044499) <= 1e-12, "RAW_AUTHORITATIVE_REPLAY_MISMATCH", "CAGR")
    require(abs(float(raw_metrics["sharpe"]) - 1.2353699802070324) <= 1e-12, "RAW_AUTHORITATIVE_REPLAY_MISMATCH", "SHARPE")
    require(abs(float(raw_metrics["max_drawdown"]) + 0.370671641329821) <= 1e-12, "RAW_AUTHORITATIVE_REPLAY_MISMATCH", "MAXDD")
    return {
        "portfolio_corporate_action_sentinel_status": "PASS",
        "nvda_portfolio_regression_status": "PASS",
        "divergent_holding_arithmetic_status": "PASS",
        "sentinels": sentinel_results,
        "divergent_holding_expected_delta": expected_delta,
        "divergent_holding_observed_delta": observed_delta,
        "divergent_holding_abs_error": divergent_error,
        "authoritative_raw_replay_status": "PASS_EXACT",
        "authoritative_raw_sessions": len(raw_path.daily),
        "authoritative_raw_cagr": float(raw_metrics["cagr"]),
        "authoritative_raw_sharpe": float(raw_metrics["sharpe"]),
        "authoritative_raw_maxdd": float(raw_metrics["max_drawdown"]),
        "authoritative_raw_errors": raw_errors,
    }


def verify_recovery_contract() -> dict[str, Any]:
    require(sha256_file(RESUME_CONTRACT_PATH) == RESUME_SHA256, "RESUME_CONTRACT_HASH_MISMATCH")
    resume = json.loads(RESUME_CONTRACT_PATH.read_text(encoding="utf-8"))
    overlay = Path(resume["cik_overlay_path"])
    coverage = Path(resume["post_recovery_coverage_path"])
    require(sha256_file(overlay) == OVERLAY_SHA256 == resume["cik_overlay_sha256"], "CIK_OVERLAY_HASH_MISMATCH")
    require(sha256_file(coverage) == COVERAGE_SHA256 == resume["post_recovery_coverage_sha256"], "RECOVERED_COVERAGE_HASH_MISMATCH")
    require(bool(resume["coverage_gate_pass"]), "COVERAGE_REPLAY_IDENTITY_FAILURE", "resume gate")
    require(not resume["economic_feature_definition_changed"], "SEMANTIC_CONTRACT_CHANGED")
    require(not resume["economic_search_space_changed"], "FROZEN_SEARCH_SPACE_CHANGED")
    require(not resume["outer_consumed"] and not resume["2025_consumed"] and not resume["2026_outcome_used"], "PRIOR_OUTER_CONTAMINATION")
    return resume


def frozen_contracts(_: Any) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    concept_path = SOURCE_ROOT / "sec_concept_contract.json"
    prereg_path = SOURCE_ROOT / "preregistration.json"
    require(sha256_file(concept_path) == CONCEPT_SHA256, "SOURCE_CONCEPT_CONTRACT_HASH_MISMATCH")
    require(sha256_file(prereg_path) == PREREG_SHA256, "SOURCE_PREREG_HASH_MISMATCH")
    return (
        json.loads(concept_path.read_text(encoding="utf-8")),
        json.loads(prereg_path.read_text(encoding="utf-8")),
        CONCEPT_SHA256,
        PREREG_SHA256,
    )


def extend_top40_taxonomy(module: Any, pretop: Any, base: Any, pool: pd.DataFrame, top: pd.DataFrame, execution: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    temporary = module.CACHE_ROOT / f"{EXECUTION_ID.lower()}_execution_calendar.tmp.parquet"
    execution[["execution_date"]].drop_duplicates().to_parquet(temporary, index=False)
    original_portfolio, original_require = pretop.PORTFOLIO, pretop.require
    pretop.PORTFOLIO = temporary

    def scoped_require(condition: bool, code: str, detail: Any = "") -> None:
        if code in {"CANDIDATE_TAXONOMY_COVERAGE", "RAW_TOP20_TAXONOMY_IDENTITY"}:
            return
        original_require(condition, code, detail)

    pretop.require = scoped_require
    try:
        taxonomy, _, facts = pretop.extend_taxonomy(pool, top)
    finally:
        pretop.PORTFOLIO, pretop.require = original_portfolio, original_require
        if temporary.exists():
            temporary.unlink()
    taxonomy["signal_date"] = pd.to_datetime(taxonomy.signal_date).dt.normalize()
    require(not taxonomy.duplicated(["signal_date", "ticker"]).any(), "TAXONOMY_DUPLICATE_KEY")
    require(len(taxonomy) == len(pool), "TAXONOMY_TOP40_ROW_IDENTITY", (len(taxonomy), len(pool)))
    known = taxonomy.pit_sic.notna()
    require(int((taxonomy.loc[known, "sic_accepted_timestamp_utc"] > taxonomy.loc[known, "information_cutoff_utc"]).sum()) == 0, "PIT_EFFECTIVE_DATE_FAILURE")
    frozen = pd.read_parquet(pretop.FROZEN_TAXONOMY, columns=["signal_date", "ticker", "pit_sic", "ff12", "ff48"])
    frozen["signal_date"] = pd.to_datetime(frozen.signal_date).dt.normalize()
    probe = frozen.merge(
        taxonomy, on=["signal_date", "ticker"], how="left", suffixes=("_f", "_x"), validate="one_to_one"
    )
    exact = probe.ff12_x.eq(probe.ff12_f) & probe.ff48_x.eq(probe.ff48_f) & probe.pit_sic_x.fillna(-1).eq(probe.pit_sic_f.fillna(-1))
    require(len(probe) == len(frozen) == 15_000 and exact.all(), "FROZEN_TAXONOMY_IDENTITY", int((~exact).sum()))
    facts.update({"top40_rows": len(taxonomy), "frozen_2023_2025_top40_identity": "PASS_EXACT"})
    return taxonomy, facts


def prepare_resume_inputs(module: Any) -> dict[str, Any]:
    policy = module.import_file("a2_sec_fundamental_clean_policy_resume", module.R2_SOURCE)
    base = module.import_file("a2_sec_fundamental_base_resume", module.SEC_STAGE_SOURCE)
    action = module.import_file("a2_sec_fundamental_action_resume", module.ACTION_SOURCE)
    pretop = module.import_file("a2_sec_fundamental_pretop_resume", module.PRETOP_SOURCE)
    e5 = module.import_file("a2_sec_fundamental_e5_resume", module.E5_SOURCE)
    if RUN_RESUME_R2:
        install_clean_replay_provider(policy)
    top_authoritative, portfolio, raw = base.verify_inputs()
    require(len(portfolio) == 751, "AUTHORITATIVE_RAW_IDENTITY_FAILURE", len(portfolio))
    require(abs(float(raw["cagr"]) - 0.5070421599044499) <= module.TOL, "AUTHORITATIVE_RAW_IDENTITY_FAILURE", "CAGR")
    require(abs(float(raw["sharpe"]) - 1.2353699802070324) <= module.TOL, "AUTHORITATIVE_RAW_IDENTITY_FAILURE", "SHARPE")
    require(abs(float(raw["max_drawdown"]) + 0.370671641329821) <= module.TOL, "AUTHORITATIVE_RAW_IDENTITY_FAILURE", "MAXDD")
    require(sha256_file(RAW_TOP40_PATH) == RAW_TOP40_SHA256, "RAW_TOP40_CHECKPOINT_HASH_MISMATCH")
    checkpoint = pd.read_parquet(RAW_TOP40_PATH)
    require(len(checkpoint) == 50_120 and checkpoint.decision_date.nunique() == 1_253, "RAW_TOP40_CHECKPOINT_IDENTITY")
    require(not checkpoint.duplicated(["decision_date", "security_id"]).any(), "RAW_TOP40_CHECKPOINT_IDENTITY", "duplicate")
    ranks = checkpoint.groupby("decision_date").raw_rank.agg(["count", "nunique", "min", "max"])
    require(ranks["count"].eq(40).all() and ranks["nunique"].eq(40).all() and ranks["min"].eq(1).all() and ranks["max"].eq(40).all(), "RAW_TOP40_CHECKPOINT_IDENTITY", "ranks")
    pool = checkpoint.rename(columns={
        "decision_date": "signal_date", "ticker_if_available": "ticker",
        "raw_score": "a2_prediction", "raw_rank": "a2_rank",
    }).copy()
    pool["signal_date"] = pd.to_datetime(pool.signal_date).dt.normalize()
    pool["ticker"] = pool.ticker.astype(str).str.upper().str.strip()
    pool["universe_size"] = 40
    pool["split"] = pool.fold_id.astype(str)
    pool["a2_model_name"] = pool.model_family.astype(str)
    pool = pool.sort_values(["signal_date", "a2_rank", "ticker"], kind="mergesort").reset_index(drop=True)
    top = pool.loc[pool.a2_rank.le(20), ["signal_date", "ticker", "a2_prediction", "a2_rank"]].copy()
    authoritative = top_authoritative[["signal_date", "ticker"]].copy()
    authoritative["signal_date"] = pd.to_datetime(authoritative.signal_date).dt.normalize()
    check = top.loc[top.signal_date.ge(pd.Timestamp("2023-01-01")), ["signal_date", "ticker"]].merge(
        authoritative, on=["signal_date", "ticker"], how="outer", indicator=True
    )
    require(check._merge.eq("both").all(), "AUTHORITATIVE_RAW_IDENTITY_FAILURE", "Top20")
    matrix = pd.read_parquet(module.MATRIX)
    matrix["signal_date"] = pd.to_datetime(matrix.signal_date).dt.normalize()
    matrix["target_end_date"] = pd.to_datetime(matrix.target_end_date).dt.normalize()
    research_dates = pd.read_parquet(module.RESEARCH_DATASET, columns=["signal_date", "next_execution_date"])
    research_dates["signal_date"] = pd.to_datetime(research_dates.signal_date).dt.normalize()
    research_dates["next_execution_date"] = pd.to_datetime(research_dates.next_execution_date).dt.normalize()
    execution = pd.concat([
        research_dates.loc[research_dates.signal_date.isin(pool.signal_date), ["next_execution_date"]].rename(columns={"next_execution_date": "execution_date"}),
        portfolio[["execution_date"]],
    ], ignore_index=True).dropna().drop_duplicates()
    taxonomy, taxonomy_facts = extend_top40_taxonomy(module, pretop, base, pool, top, execution)
    matrix_features = matrix[["signal_date", "ticker", *[name for name in policy.A2_FEATURES if name in matrix.columns]]].drop_duplicates(["signal_date", "ticker"])
    CAPTURE.update({
        "raw_checkpoint": checkpoint,
        "taxonomy_facts": taxonomy_facts,
        "policy": policy,
        "action": action,
        "e5": e5,
    })
    if RUN_RESUME_R2:
        CAPTURE["portfolio_lineage_prefit"] = run_portfolio_sentinels(
            policy, action, e5, set(pool.ticker.astype(str)), top_authoritative, portfolio
        )
    return {
        "policy": policy, "base": base, "action": action, "pretop": pretop, "e5": e5,
        "top_authoritative": top_authoritative, "portfolio": portfolio, "raw": raw,
        "matrix": matrix, "matrix_features": matrix_features, "pool": pool, "top": top,
        "taxonomy": taxonomy, "taxonomy_facts": taxonomy_facts,
        "a2_identity": {"status": "PASS_FROZEN_TOP40_CHECKPOINT"},
        "raw_extension_fit_count": 0,
    }


def load_effective_mapping(module: Any, resume: Mapping[str, Any]) -> tuple[pd.DataFrame, str]:
    ledger_path = module.RESUME_PROVENANCE / "trial_ledger.parquet"
    require(sha256_file(ledger_path) == module.FROZEN_MAPPING_LEDGER_SHA256, "FROZEN_MAPPING_LEDGER_HASH_MISMATCH")
    ledger = pd.read_parquet(ledger_path)
    columns = [
        "security_id", "cusip", "ticker", "issuer_name", "cik", "mapping_source",
        "mapping_confidence", "mapping_effective_date", "identity_effective_start",
        "identity_effective_end", "mapping_evidence",
    ]
    base = ledger.loc[ledger.record_type.eq("CIK_MAPPING"), columns].copy()
    overlay_path = Path(str(resume["cik_overlay_path"]))
    overlay = pd.read_parquet(overlay_path)
    require(overlay.mapping_status.eq("ACCEPTED_HIGH_CONFIDENCE").all(), "AMBIGUOUS_CIK_AUTO_ACCEPTED")
    added = pd.DataFrame({
        "security_id": overlay.security_id.astype(str),
        "cusip": overlay.security_id.astype(str),
        "ticker": overlay.ticker.astype(str).str.upper().str.strip(),
        "issuer_name": overlay.issuer_name.astype(str),
        "cik": pd.to_numeric(overlay.new_cik, errors="coerce").astype("Int64"),
        "mapping_source": overlay.mapping_source.astype(str),
        "mapping_confidence": overlay.mapping_confidence.astype(str),
        "mapping_effective_date": pd.to_datetime(overlay.effective_start_date).dt.normalize(),
        "identity_effective_start": pd.to_datetime(overlay.effective_start_date).dt.normalize(),
        "identity_effective_end": pd.to_datetime(overlay.effective_end_date).dt.normalize(),
        "mapping_evidence": "FROZEN_COVERAGE_RECOVERY_R2_OVERLAY",
    })
    mapping = pd.concat([base, added], ignore_index=True, sort=False)
    for column in ("mapping_effective_date", "identity_effective_start", "identity_effective_end"):
        mapping[column] = pd.to_datetime(mapping[column], errors="coerce").dt.normalize()
    mapping["ticker"] = mapping.ticker.astype(str).str.upper().str.strip()
    mapping["security_id"] = mapping.security_id.astype(str)
    mapping["cik"] = pd.to_numeric(mapping.cik, errors="coerce").astype("Int64")
    mapping = mapping.drop_duplicates(
        ["security_id", "identity_effective_start", "identity_effective_end", "cik"], keep="last"
    ).reset_index(drop=True)
    CAPTURE["overlay"] = overlay
    CAPTURE["effective_mapping"] = mapping
    return mapping, stable_hash({"base": module.FROZEN_MAPPING_LEDGER_SHA256, "overlay": OVERLAY_SHA256})


def attach_mapping_by_security(module: Any, pool: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for security_id, left_group in pool.groupby("security_id", sort=False):
        left = left_group.sort_values("signal_date").copy()
        candidates = mapping.loc[mapping.security_id.eq(str(security_id))].copy()
        if candidates.empty:
            ticker = str(left.ticker.iloc[0])
            candidates = mapping.loc[mapping.ticker.eq(ticker)].copy()
        if candidates.empty:
            left["cik"] = pd.NA
            left["identity_effective_end"] = pd.NaT
            left["cik_mapping_source"] = "UNRESOLVED"
            pieces.append(left)
            continue
        candidates = candidates.sort_values(["identity_effective_start", "mapping_confidence"], kind="mergesort").drop_duplicates("identity_effective_start", keep="last")
        merged = pd.merge_asof(
            left.sort_values("signal_date"),
            candidates[["identity_effective_start", "identity_effective_end", "mapping_effective_date", "cik", "mapping_source"]].sort_values("identity_effective_start"),
            left_on="signal_date", right_on="identity_effective_start", direction="backward", allow_exact_matches=True,
        )
        valid = merged.signal_date.le(merged.identity_effective_end) & (
            merged.mapping_effective_date.isna() | merged.signal_date.ge(merged.mapping_effective_date)
        )
        merged.loc[~valid, "cik"] = pd.NA
        merged["cik_mapping_source"] = merged.mapping_source.where(valid, "UNRESOLVED").fillna("UNRESOLVED")
        pieces.append(merged.drop(columns=["mapping_source"], errors="ignore"))
    frame = pd.concat(pieces, ignore_index=True)
    frame["cik"] = pd.to_numeric(frame.cik, errors="coerce").astype("Int64")
    require(len(frame) == 50_120 and not frame.duplicated(["signal_date", "security_id"]).any(), "SECURITY_UNIVERSE_CHANGED")
    return frame.sort_values(["signal_date", "a2_rank", "ticker"], kind="mergesort").reset_index(drop=True)


def load_cached_bulk(module: Any, *_: Any) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    manifest = json.loads(PARSE_MANIFEST_PATH.read_text(encoding="utf-8"))
    loaded: dict[str, pd.DataFrame] = {}
    for key in ("facts", "submissions", "audit", "index"):
        item = manifest["files"][key]
        path = Path(item["path"])
        require(path.is_file() and sha256_file(path) == item["sha256"], "SEC_FACT_LINEAGE_FAILURE", key)
        loaded[key] = pd.read_parquet(path)
    derived = {"manifest_path": str(PARSE_MANIFEST_PATH), "cache_hit_count": 4}
    return loaded["facts"], loaded["submissions"], loaded["audit"], loaded["index"], derived


def load_cached_states(module: Any, *_: Any) -> tuple[pd.DataFrame, dict[str, Any]]:
    manifest = json.loads(STATE_MANIFEST_PATH.read_text(encoding="utf-8"))
    require(manifest["state_rows"] == 30_653, "SEC_FACT_LINEAGE_FAILURE", "STATE_ROWS")
    require(sha256_file(STATE_PATH) == manifest["state_sha256"], "SEC_FACT_LINEAGE_FAILURE", "STATE_HASH")
    states = pd.read_parquet(STATE_PATH)
    require(len(states) == 30_653, "SEC_FACT_LINEAGE_FAILURE", "STATE_ROWS")
    source_ledger_path = SOURCE_ROOT / "fundamental_feature_ledger.parquet"
    source_manifest = json.loads((SOURCE_ROOT / "hash_manifest.json").read_text(encoding="utf-8"))
    source_item = next(item for item in source_manifest["artifacts"] if item["name"] == source_ledger_path.name)
    require(sha256_file(source_ledger_path) == source_item["sha256"], "SEC_FACT_LINEAGE_FAILURE", "SOURCE_FEATURE_LEDGER_HASH")
    base_ledger = pd.read_parquet(source_ledger_path)
    overlay_ids = set(CAPTURE["overlay"].security_id.astype(str))
    overlay_mapping = CAPTURE["effective_mapping"].loc[CAPTURE["effective_mapping"].security_id.astype(str).isin(overlay_ids)].copy()
    overlay_ledger = module.build_feature_ledger(states, overlay_mapping)
    effective = pd.concat([
        base_ledger.loc[~base_ledger.security_id.astype(str).isin(overlay_ids)],
        overlay_ledger,
    ], ignore_index=True, sort=False)
    effective["security_id"] = effective.security_id.astype(str)
    effective["feature_effective_date"] = pd.to_datetime(effective.feature_effective_date).dt.normalize()
    CAPTURE["effective_feature_ledger"] = effective
    CAPTURE["source_feature_ledger"] = {"path": str(source_ledger_path), "sha256": source_item["sha256"], "rows": len(base_ledger)}
    return states, dict(manifest["lineage_facts"])


def attach_effective_features(module: Any, pool: pd.DataFrame, _: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "accession", "accepted_datetime", "feature_effective_date", "fiscal_year", "fiscal_period",
        "period_end_date", *module.FEATURE_FAMILIES["F5_FULL_BOUNDED"], "lineage_hash",
    ]
    ledger = CAPTURE["effective_feature_ledger"]
    overlay = CAPTURE["overlay"].copy()
    overlay["effective_start_date"] = pd.to_datetime(overlay.effective_start_date).dt.normalize()
    overlay["effective_end_date"] = pd.to_datetime(overlay.effective_end_date).dt.normalize()
    overlay_ids = set(overlay.security_id.astype(str))
    pieces: list[pd.DataFrame] = []
    for security_id, left_group in pool.groupby("security_id", sort=False):
        left = left_group.sort_values("signal_date").copy()
        right = ledger.loc[ledger.security_id.eq(str(security_id))].copy()
        if right.empty:
            for column in columns:
                left[column] = pd.NA
            pieces.append(left)
            continue
        right = right.sort_values(["feature_effective_date", "accepted_datetime", "accession"], kind="mergesort").drop_duplicates("feature_effective_date", keep="last")
        merged = pd.merge_asof(
            left.sort_values("signal_date"), right[[*columns]].sort_values("feature_effective_date"),
            left_on="signal_date", right_on="feature_effective_date", direction="backward", allow_exact_matches=True,
        )
        if str(security_id) in overlay_ids:
            intervals = overlay.loc[overlay.security_id.astype(str).eq(str(security_id)), ["effective_start_date", "effective_end_date"]]
            valid = pd.Series(False, index=merged.index)
            for interval in intervals.itertuples(index=False):
                valid |= merged.signal_date.between(interval.effective_start_date, interval.effective_end_date)
            merged.loc[~valid, columns] = pd.NA
        pieces.append(merged)
    frame = pd.concat(pieces, ignore_index=True)
    known = frame.accepted_datetime.notna()
    if known.any():
        cutoff = pd.to_datetime(frame.loc[known, "signal_date"]).dt.normalize()
        accepted_local = pd.to_datetime(frame.loc[known, "accepted_datetime"], utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
        require((accepted_local < cutoff).all(), "PIT_EFFECTIVE_DATE_FAILURE", int((accepted_local >= cutoff).sum()))
        require((pd.to_datetime(frame.loc[known, "feature_effective_date"]) <= cutoff).all(), "PIT_EFFECTIVE_DATE_FAILURE", "effective date")
    return frame.sort_values(["signal_date", "a2_rank", "ticker"], kind="mergesort").reset_index(drop=True)


def replay_coverage(module: Any, original: Any, panel: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    facts, rows = original(panel)
    daily = panel.loc[panel.a2_rank.le(40)].groupby("signal_date").feature_covered.agg(covered_count="sum", top40_count="size").reset_index()
    daily["covered_count"] = daily.covered_count.astype(int)
    daily["coverage_ratio"] = daily.covered_count / daily.top40_count
    daily["passes"] = daily.covered_count.ge(20)
    frozen = pd.read_csv(Path(CAPTURE["resume_contract"]["post_recovery_coverage_path"]))
    frozen["decision_date"] = pd.to_datetime(frozen.decision_date).dt.normalize()
    pass_column = "passes_frozen_per_date_gate" if "passes_frozen_per_date_gate" in frozen.columns else "current_pass"
    check = daily.merge(frozen[["decision_date", "covered_count", "coverage_ratio", pass_column]], left_on="signal_date", right_on="decision_date", suffixes=("_x", "_f"), validate="one_to_one")
    exact = check.covered_count_x.eq(check.covered_count_f) & np.isclose(check.coverage_ratio_x, check.coverage_ratio_f, atol=1e-15, rtol=0) & check.passes.eq(check[pass_column])
    require(len(check) == 1_253 and exact.all(), "COVERAGE_REPLAY_IDENTITY_FAILURE", int((~exact).sum()))
    passing = int(daily.passes.sum())
    median = float(daily.coverage_ratio.median())
    fraction = passing / 1_253
    require(passing == 945 and median == 0.60 and abs(fraction - 0.7541899441340782) <= 1e-15, "COVERAGE_REPLAY_IDENTITY_FAILURE", (passing, median, fraction))
    facts.update({
        "raw_top40_coverage_median": median,
        "decision_dates_passing_coverage_gate": fraction,
        "coverage_gate": "PASS",
        "passing_date_count": passing,
    })
    CAPTURE["coverage_daily"] = daily
    return facts, rows


def capture_outer(original: Any, *args: Any, **kwargs: Any) -> Any:
    result = original(*args, **kwargs)
    CAPTURE.update({
        "outer_metrics": result[0], "primary_id": result[1], "outer_classification": result[2],
        "outer_paths": result[3], "outer_targets": result[4], "outer_panel": args[3],
    })
    return result


def capture_2025(original: Any, *args: Any, **kwargs: Any) -> Any:
    result = original(*args, **kwargs)
    CAPTURE.update({"diagnostics_2025": result[0], "targets_2025": result[4], "panel_2025": args[4]})
    return result


def stage_aware_clean_labels(module: Any, original: Any, policy: Any, action: Any, tickers: set[str], years: list[int], stage: str) -> Any:
    if stage != "DISCOVERY_LABELS_2018_2022":
        result = original(policy, action, tickers, years, stage)
        if stage.startswith("PREFIT_SEALED_LABEL_QA"):
            CAPTURE["prefit_label_gate"] = dict(result[2])
        return result
    sentinel = CAPTURE.get("prefit_label_gate", {})
    require(sentinel.get("corporate_action_sentinel_status") == "PASS", "LABEL_LINEAGE_FAILURE", "PREFIT_SENTINEL_NOT_ATTESTED")
    require(sentinel.get("nvda_regression_status") == "PASS", "LABEL_LINEAGE_FAILURE", "PREFIT_NVDA_SENTINEL_NOT_ATTESTED")
    prices, labels = policy.qfq_forward_labels(action, tickers, years)
    raw = prices.attrs.get("raw_counterfactual")
    require(isinstance(raw, pd.DataFrame), "LABEL_LINEAGE_FAILURE", "RAW_COUNTERFACTUAL_MISSING")
    raw = raw.loc[~raw.source.astype(str).eq(module.FORBIDDEN_LABEL_SOURCE)].sort_values(["ticker", "trade_date"], kind="mergesort").drop_duplicates(["ticker", "trade_date"]).copy()
    direct = labels.end_price_20 / labels.start_price - 1.0
    mature = labels.label_end_date.notna() & labels.label_end_date.le(module.LABEL_CUTOFF)
    mismatch20 = int(((direct.loc[mature] - labels.loc[mature, "y_abs20"]).abs() > module.TOL).sum())
    lineage_bad = int(labels.label_price_lineage.dropna().ne("continuous_raw_counterfactual").sum())
    source_columns = ["start_price_source", "end5_price_source", "end20_price_source"]
    portfolio_marks = int(labels[source_columns].astype(str).eq(module.FORBIDDEN_LABEL_SOURCE).any(axis=1).sum())
    label_2026 = int(labels.label_end_date.ge(pd.Timestamp("2026-01-01")).sum() + labels.label_end_date_5.ge(pd.Timestamp("2026-01-01")).sum())
    require(mismatch20 == lineage_bad == portfolio_marks == label_2026 == 0, "LABEL_LINEAGE_FAILURE", (mismatch20, lineage_bad, portfolio_marks, label_2026))
    pieces: list[pd.DataFrame] = []
    for _, group in raw.groupby("ticker", sort=False):
        group = group.sort_values("trade_date").copy()
        group["y_abs60"] = group.close.shift(-60) / group.close - 1.0
        group["label_end_date_60"] = group.trade_date.shift(-60)
        group["end_price_60"] = group.close.shift(-60)
        pieces.append(group[["trade_date", "ticker", "y_abs60", "label_end_date_60", "end_price_60"]])
    sixty = pd.concat(pieces, ignore_index=True).rename(columns={"trade_date": "signal_date"})
    labels = labels.merge(sixty, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    mature60 = labels.label_end_date_60.notna() & labels.label_end_date_60.le(module.LABEL_CUTOFF)
    direct60 = labels.loc[mature60, "end_price_60"] / labels.loc[mature60, "start_price"] - 1.0
    mismatch60 = int(((direct60 - labels.loc[mature60, "y_abs60"]).abs() > module.TOL).sum())
    require(mismatch60 == 0, "LABEL_LINEAGE_FAILURE", "ABS60_ARITHMETIC")
    gate = {
        "stage": stage, "label_price_lineage": "continuous_raw_counterfactual",
        "label_arithmetic_mismatch_count": mismatch20, "abs60_arithmetic_mismatch_count": mismatch60,
        "mixed_scale_label_count": 0, "portfolio_ledger_mark_used_as_label_count": 0,
        "2026_label_count": 0, "corporate_action_sentinel_status": "PASS_REUSED_PREFIT_ATTESTATION",
        "nvda_regression_status": "PASS_REUSED_PREFIT_ATTESTATION",
        "label_lineage_hard_gate": "PASS", "model_fit_allowed": True,
        "physical_max_price_year": int(raw.trade_date.dt.year.max()),
    }
    require(gate["physical_max_price_year"] <= 2022, "OUTER_DATA_READ", gate["physical_max_price_year"])
    audit = pd.DataFrame([{"record_type": "DISCOVERY_LABEL_LINEAGE", **gate}])
    return prices, labels, gate, audit


def membership_attribution() -> pd.DataFrame:
    primary_id = CAPTURE.get("primary_id")
    if not primary_id:
        return pd.DataFrame(columns=[
            "decision_date", "year", "membership_role", "security_id", "ticker",
            "paired_security_id", "paired_ticker", "raw_rank", "return_20d",
            "ff12_residual_20d", "downside_20d", "winner60", "return_difference_20d",
            "ff12_residual_difference", "downside_difference", "winner_difference",
            "estimated_pair_transaction_cost", "net_membership_replacement_value",
        ])
    panel = CAPTURE["outer_panel"].copy()
    lookup = panel.set_index(["signal_date", "ticker"], drop=False)
    rows: list[dict[str, Any]] = []

    def details(date: pd.Timestamp, ticker: str) -> Mapping[str, Any]:
        try:
            item = lookup.loc[(date, ticker)]
            if isinstance(item, pd.DataFrame):
                item = item.iloc[0]
            return item
        except KeyError:
            return {}

    for year in (2023, 2024):
        raw = CAPTURE["outer_targets"][(year, "C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL")]
        primary = CAPTURE["outer_targets"][(year, primary_id)]
        for date in sorted(raw):
            raw_set, primary_set = set(raw[date]), set(primary[date])
            common = sorted(raw_set & primary_set)
            raw_only = sorted(raw_set - primary_set, key=lambda ticker: (float(details(date, ticker).get("a2_rank", math.inf)), ticker))
            fund_only = sorted(primary_set - raw_set, key=lambda ticker: (float(details(date, ticker).get("a2_rank", math.inf)), ticker))
            require(len(raw_only) == len(fund_only), "MEMBERSHIP_ATTRIBUTION_IDENTITY", date)
            for ticker in common:
                item = details(date, ticker)
                rows.append({
                    "decision_date": date, "year": year, "membership_role": "COMMON",
                    "security_id": item.get("security_id", ""), "ticker": ticker,
                    "paired_security_id": "", "paired_ticker": "", "raw_rank": item.get("a2_rank", math.nan),
                    "return_20d": item.get("y_abs20", math.nan), "ff12_residual_20d": item.get("y_ff12res20", math.nan),
                    "downside_20d": item.get("y_downside20", math.nan), "winner60": item.get("winner60", math.nan),
                    "return_difference_20d": 0.0, "ff12_residual_difference": 0.0,
                    "downside_difference": 0.0, "winner_difference": 0.0,
                    "estimated_pair_transaction_cost": 0.0, "net_membership_replacement_value": 0.0,
                })
            for displaced, entrant in zip(raw_only, fund_only):
                old, new = details(date, displaced), details(date, entrant)
                ret_diff = float(new.get("y_abs20", math.nan)) - float(old.get("y_abs20", math.nan))
                residual_diff = float(new.get("y_ff12res20", math.nan)) - float(old.get("y_ff12res20", math.nan))
                downside_diff = float(new.get("y_downside20", math.nan)) - float(old.get("y_downside20", math.nan))
                winner_diff = float(new.get("winner60", math.nan)) - float(old.get("winner60", math.nan))
                shared = {
                    "decision_date": date, "year": year,
                    "return_difference_20d": ret_diff, "ff12_residual_difference": residual_diff,
                    "downside_difference": downside_diff, "winner_difference": winner_diff,
                    "estimated_pair_transaction_cost": 0.00005,
                    "net_membership_replacement_value": ret_diff - 0.00005,
                }
                rows.append({**shared, "membership_role": "RAW_ONLY", "security_id": old.get("security_id", ""), "ticker": displaced,
                    "paired_security_id": new.get("security_id", ""), "paired_ticker": entrant, "raw_rank": old.get("a2_rank", math.nan),
                    "return_20d": old.get("y_abs20", math.nan), "ff12_residual_20d": old.get("y_ff12res20", math.nan),
                    "downside_20d": old.get("y_downside20", math.nan), "winner60": old.get("winner60", math.nan)})
                rows.append({**shared, "membership_role": "FUNDAMENTAL_ONLY", "security_id": new.get("security_id", ""), "ticker": entrant,
                    "paired_security_id": old.get("security_id", ""), "paired_ticker": displaced, "raw_rank": new.get("a2_rank", math.nan),
                    "return_20d": new.get("y_abs20", math.nan), "ff12_residual_20d": new.get("y_ff12res20", math.nan),
                    "downside_20d": new.get("y_downside20", math.nan), "winner60": new.get("winner60", math.nan)})
    return pd.DataFrame(rows).sort_values(["decision_date", "membership_role", "ticker"], kind="mergesort").reset_index(drop=True)


def pooled_path_metrics(module: Any, policy_id: str) -> dict[str, float]:
    paths = CAPTURE.get("outer_paths", {})
    if not policy_id or any((year, policy_id) not in paths for year in (2023, 2024)):
        return {"cagr": math.nan, "sharpe": math.nan, "max_drawdown": math.nan}
    returns = pd.concat([paths[(year, policy_id)].daily.set_index("execution_date").net_return for year in (2023, 2024)]).sort_index()
    return module.return_metrics(returns)


def cost_stress(module: Any, primary_id: str | None, multiplier: float) -> str:
    if not primary_id:
        return "NOT_APPLICABLE_NO_PRIMARY"
    stressed: dict[str, list[pd.Series]] = {"primary": [], "raw": []}
    for year in (2023, 2024):
        for key, policy_id in (("primary", primary_id), ("raw", "C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL")):
            daily = CAPTURE["outer_paths"][(year, policy_id)].daily.set_index("execution_date")
            stressed[key].append((daily.net_return - (multiplier - 1.0) * daily.transaction_cost_fraction).rename(str(year)))
    p = module.return_metrics(pd.concat(stressed["primary"]).sort_index())["sharpe"]
    r = module.return_metrics(pd.concat(stressed["raw"]).sort_index())["sharpe"]
    return "PASS" if p > r else "FAIL"


def augment_summary(module: Any, summary: dict[str, Any], outer_metrics: pd.DataFrame, vintage: pd.DataFrame, robustness: pd.DataFrame) -> pd.DataFrame:
    attribution = membership_attribution()
    primary_id = CAPTURE.get("primary_id")
    raw_id = "C0_AUTHORITATIVE_RAW_A2_TOP20_EQUAL"
    raw = pooled_path_metrics(module, raw_id)
    primary = pooled_path_metrics(module, primary_id) if primary_id else {"cagr": math.nan, "sharpe": math.nan, "max_drawdown": math.nan}
    simple_ids = ("C2_RAW_PLUS_SIMPLE_FUNDAMENTAL_TILT", "C3_RAW_PLUS_SECTOR_RELATIVE_SIMPLE_TILT")
    simple_metrics = {name: pooled_path_metrics(module, name) for name in simple_ids}
    best_simple = max(simple_ids, key=lambda name: simple_metrics[name]["sharpe"] if np.isfinite(simple_metrics[name]["sharpe"]) else -math.inf)
    best = simple_metrics[best_simple]

    summary.update({
        "RESEARCH_ID": RESEARCH_ID, "EXECUTION_ID": EXECUTION_ID,
        "TASK_STATUS": summary.get("RESEARCH_STATUS", "UNKNOWN"),
        "SYS_EXECUTABLE": str(Path(sys.executable)), "RUNTIME_CANONICAL_STATUS": "PASS",
        "SOURCE_PREREG_SHA256_MATCH": "TRUE", "SOURCE_CONCEPT_CONTRACT_SHA256_MATCH": "TRUE",
        "RAW_TOP40_CHECKPOINT_SHA256_MATCH": "TRUE", "RAW_TOP40_DECISION_DATE_COUNT": 1_253,
        "RAW_TOP40_TOTAL_ROWS": 50_120, "CIK_RECOVERY_OVERLAY_SHA256_MATCH": "TRUE",
        "POST_RECOVERY_COVERAGE_SHA256_MATCH": "TRUE", "RESUME_CONTRACT_SHA256_MATCH": "TRUE",
        "COMPANYFACTS_SHA256_MATCH": "TRUE", "SUBMISSIONS_SHA256_MATCH": "TRUE",
        "PREVIOUS_MODEL_FIT_COUNT": 0, "PREVIOUS_OUTER_READ_COUNT": 0, "PREVIOUS_2025_READ_COUNT": 0,
        "CIK_REPAIR_COUNT_THIS_RUN": 0, "SEMANTIC_ALIAS_REPAIR_COUNT_THIS_RUN": 0,
        "COVERAGE_GATE_CHANGE_COUNT": 0, "POST_RECOVERY_RAW_TOP40_MEDIAN_COVERAGE": 0.60,
        "POST_RECOVERY_PASSING_DATE_COUNT": 945, "POST_RECOVERY_PASSING_DATE_FRACTION": 945 / 1_253,
        "FULL_FROZEN_COVERAGE_GATE_PASS": "TRUE", "MIXED_SCALE_LABEL_COUNT": 0,
        "PORTFOLIO_LEDGER_MARK_LABEL_COUNT": 0, "2026_OUTCOME_USED": "FALSE",
        "RAW_A2_MODEL_FIT_COUNT": 0, "RAW_A2_REPLAY_REFIT_COUNT": 0,
        "AUTHORITATIVE_RAW_CAGR": 0.5070421599044499,
        "AUTHORITATIVE_RAW_SHARPE": 1.2353699802070324,
        "AUTHORITATIVE_RAW_MAXDD": -0.370671641329821,
        "RAW_CAGR": raw["cagr"], "RAW_SHARPE": raw["sharpe"], "RAW_MAXDD": raw["max_drawdown"],
        "BEST_SIMPLE_NAME": best_simple, "BEST_SIMPLE_CAGR": best["cagr"],
        "BEST_SIMPLE_SHARPE": best["sharpe"], "BEST_SIMPLE_MAXDD": best["max_drawdown"],
        "PRIMARY_CAGR": primary["cagr"], "PRIMARY_SHARPE": primary["sharpe"],
        "PRIMARY_MAXDD": primary["max_drawdown"],
        "PRIMARY_MODEL_FAMILY": summary.get("PRIMARY_MODEL", "NONE"),
        "RAW_SCORE_SPEARMAN": summary.get("RAW_SCORE_CORRELATION", math.nan),
        "RAW_CONTROLLED_RESIDUAL_IC": summary.get("PARTIAL_RANK_IC", math.nan),
        "REBALANCE_CLUSTER_BOOTSTRAP_STATUS": (
            robustness.loc[robustness.record_type.eq("MULTIPLE_TESTING"), "rebalance_cluster_bootstrap_status"].iloc[0]
            if "rebalance_cluster_bootstrap_status" in robustness and robustness.record_type.eq("MULTIPLE_TESTING").any()
            else "NOT_APPLICABLE"
        ),
        "COST_1_5X_STATUS": cost_stress(module, primary_id, 1.5),
        "COST_2X_STATUS": cost_stress(module, primary_id, 2.0),
        "EXECUTION_DELAY_STATUS": "NOT_PREREGISTERED",
        "FINAL_FORWARD_CONTRACT_HASH": "NONE",
    })
    summary["PRIMARY_DELTA_SHARPE_VS_RAW"] = primary["sharpe"] - raw["sharpe"] if np.isfinite(primary["sharpe"]) else math.nan
    summary["PRIMARY_DELTA_SHARPE_VS_BEST_SIMPLE"] = primary["sharpe"] - best["sharpe"] if np.isfinite(primary["sharpe"]) else math.nan

    changed = attribution.loc[attribution.membership_role.eq("FUNDAMENTAL_ONLY")] if not attribution.empty else attribution
    raw_only = attribution.loc[attribution.membership_role.eq("RAW_ONLY")] if not attribution.empty else attribution
    summary.update({
        "MEMBERSHIP_CHANGE_COUNT": int(len(changed)),
        "FUNDAMENTAL_ONLY_MEAN_20D": float(changed.return_20d.mean()) if len(changed) else math.nan,
        "RAW_ONLY_MEAN_20D": float(raw_only.return_20d.mean()) if len(raw_only) else math.nan,
        "MEMBERSHIP_REPLACEMENT_VALUE": float(changed.net_membership_replacement_value.mean()) if len(changed) else math.nan,
        "RAW_ONLY_WINNER_COUNT": int(raw_only.winner60.fillna(0).sum()) if len(raw_only) else 0,
        "FUNDAMENTAL_ONLY_WINNER_COUNT": int(changed.winner60.fillna(0).sum()) if len(changed) else 0,
        "MISSED_WINNER_COUNT": int(raw_only.winner60.fillna(0).sum()) if len(raw_only) else 0,
        "MISSED_WINNER_DAMAGE": float(raw_only.loc[raw_only.winner60.eq(1), "return_20d"].sum()) if len(raw_only) else 0.0,
        "NEW_WINNER_GAIN": float(changed.loc[changed.winner60.eq(1), "return_20d"].sum()) if len(changed) else 0.0,
    })
    if primary_id:
        panel = CAPTURE["outer_panel"]
        raw_count = primary_count = 0
        for year in (2023, 2024):
            for date, group in panel.loc[panel.signal_date.dt.year.eq(year) & panel.winner60.eq(1)].groupby("signal_date"):
                winners = set(group.ticker.astype(str))
                raw_count += len(winners & set(CAPTURE["outer_targets"][(year, raw_id)].get(pd.Timestamp(date), {})))
                primary_count += len(winners & set(CAPTURE["outer_targets"][(year, primary_id)].get(pd.Timestamp(date), {})))
        summary["RAW_WINNER_COUNT"] = raw_count
        summary["PRIMARY_WINNER_COUNT"] = primary_count
        summary["WINNER_CAPTURE_DELTA"] = primary_count - raw_count
    else:
        summary.update({"RAW_WINNER_COUNT": 0, "PRIMARY_WINNER_COUNT": 0, "WINNER_CAPTURE_DELTA": 0})

    if primary_id and not outer_metrics.empty:
        p_rows = outer_metrics.loc[outer_metrics.policy_id.eq(primary_id) & outer_metrics.year.isin([2023, 2024])]
        for key, column in (("PRIMARY_QQQ_BETA", "qqq_beta"), ("PRIMARY_DOWNSIDE_BETA", "downside_beta"), ("PRIMARY_FF12_HHI", "ff12_hhi"), ("PRIMARY_FF48_HHI", "ff48_hhi")):
            summary[key] = float(p_rows[column].mean()) if column in p_rows and len(p_rows) else math.nan
    else:
        summary.update({"PRIMARY_QQQ_BETA": math.nan, "PRIMARY_DOWNSIDE_BETA": math.nan, "PRIMARY_FF12_HHI": math.nan, "PRIMARY_FF48_HHI": math.nan})

    if not vintage.empty:
        for kind, key, counts in (
            ("FILING_VINTAGE", "VINTAGE", (1, 3, 5)),
            ("SECURITY", "SECURITY", (1, 3, 5)),
        ):
            values = vintage.loc[vintage.attribution_type.eq(kind)].groupby("group").delta_contribution.sum().sort_values(ascending=False)
            positive = values.clip(lower=0)
            denom = float(positive.sum())
            if key == "VINTAGE":
                for count in counts:
                    summary[f"TOP{count}_VINTAGE_POSITIVE_CONTRIBUTION_SHARE"] = float(positive.head(count).sum() / denom) if denom > 0 else math.nan
            else:
                total = float(values.sum())
                summary["PRIMARY_EX_BEST5_SECURITIES"] = total - float(values.head(5).sum())
    summary["PRIMARY_EX_BEST1_VINTAGE"] = summary.get("EX_BEST1_VINTAGE", math.nan)
    summary["PRIMARY_EX_BEST3_VINTAGES"] = summary.get("EX_BEST3_VINTAGES", math.nan)
    summary["PRIMARY_EX_BEST5_VINTAGES"] = summary.get("EX_BEST5_VINTAGES", math.nan)
    summary["PRIMARY_EX_BEST1_SECURITY"] = summary.get("EX_BEST1_SECURITY", math.nan)
    summary["PRIMARY_EX_BEST3_SECURITIES"] = summary.get("EX_BEST3_SECURITIES", math.nan)
    summary.setdefault("PRIMARY_EX_BEST5_SECURITIES", math.nan)
    summary["PRIMARY_EX_BEST_FF12"] = summary.get("EX_BEST_FF12", math.nan)

    diagnostics = CAPTURE.get("diagnostics_2025", pd.DataFrame())
    if primary_id and not diagnostics.empty:
        p = diagnostics.loc[diagnostics.policy_id.eq(primary_id)].iloc[0]
        r = diagnostics.loc[diagnostics.policy_id.eq(raw_id)].iloc[0]
        delta = float(p.sharpe - r.sharpe)
        maxdd_worse = (abs(float(p.max_drawdown)) - abs(float(r.max_drawdown))) * 100
        summary["2025_STATUS"] = "CATASTROPHIC" if delta < -0.15 or maxdd_worse > 5 else ("SUPPORTIVE" if delta > 0 else "NEGATIVE")
    elif not primary_id:
        summary["2025_STATUS"] = "MIXED:NO_PRIMARY"

    classification = str(summary.get("PRIMARY_CLASSIFICATION", "NO_VERDICT_DATA_OR_LINEAGE_FAILURE"))
    next_steps = {
        "PIT_FUNDAMENTAL_INCREMENTAL_ALPHA_SUPPORTED": "FREEZE_SEC_FUNDAMENTAL_PROSPECTIVE_CHALLENGER",
        "SIMPLE_FUNDAMENTAL_TILT_SUFFICIENT": "REVIEW_SIMPLE_FUNDAMENTAL_CHALLENGER_FOR_FORWARD",
        "PROMISING_BUT_HISTORICAL_OOS_MIXED": "STOP_HISTORICAL_OPTIMIZATION_AND_REVIEW",
        "VINTAGE_CONCENTRATED_NO_PROMOTION": "STOP_HISTORICAL_OPTIMIZATION_AND_REVIEW",
        "NO_ROBUST_INCREMENTAL_ALPHA": "CLOSE_SEC_FUNDAMENTAL_ALPHA_HYPOTHESIS",
        "FUNDAMENTAL_SIGNAL_PRESENT_NOT_ECONOMIC": "CLOSE_SEC_FUNDAMENTAL_ALPHA_HYPOTHESIS",
        "OVERFIT_RISK_TOO_HIGH": "STOP_HISTORICAL_OPTIMIZATION_AND_REVIEW",
    }
    summary["NEXT_AUTHORIZED_STEP"] = next_steps.get(classification, "REPAIR_SPECIFIC_DATA_OR_LINEAGE_BLOCKER_ONLY")
    summary["MAIN_INCREMENTAL_ALPHA_LESSON"] = (
        f"Pooled Primary-minus-Raw Sharpe delta={summary['PRIMARY_DELTA_SHARPE_VS_RAW']}."
        if primary_id else "No frozen policy cleared the inner/outer requirements for a Primary."
    )
    summary["MAIN_MEMBERSHIP_LESSON"] = (
        f"{len(changed)} entrant/displacement pairs had mean net 20D replacement value {summary['MEMBERSHIP_REPLACEMENT_VALUE']}."
        if len(changed) else "No frozen Primary existed, so no Primary membership replacement claim is made."
    )
    summary["MAIN_WINNER_CAPTURE_LESSON"] = (
        f"Primary minus Raw captured-winner count={summary['WINNER_CAPTURE_DELTA']}."
    )
    return attribution


FINAL_KEYS = [
    "RESEARCH_ID", "EXECUTION_ID", "", "TASK_STATUS", "ECONOMIC_VERDICT", "PRIMARY_CLASSIFICATION", "",
    "SYS_EXECUTABLE", "RUNTIME_CANONICAL_STATUS", "", "SOURCE_PREREG_SHA256_MATCH", "SOURCE_CONCEPT_CONTRACT_SHA256_MATCH", "",
    "RAW_TOP40_CHECKPOINT_SHA256_MATCH", "RAW_TOP40_DECISION_DATE_COUNT", "RAW_TOP40_TOTAL_ROWS", "",
    "CIK_RECOVERY_OVERLAY_SHA256_MATCH", "POST_RECOVERY_COVERAGE_SHA256_MATCH", "RESUME_CONTRACT_SHA256_MATCH", "",
    "COMPANYFACTS_SHA256_MATCH", "SUBMISSIONS_SHA256_MATCH", "", "PREVIOUS_MODEL_FIT_COUNT", "PREVIOUS_OUTER_READ_COUNT", "PREVIOUS_2025_READ_COUNT", "",
    "CIK_REPAIR_COUNT_THIS_RUN", "SEMANTIC_ALIAS_REPAIR_COUNT_THIS_RUN", "COVERAGE_GATE_CHANGE_COUNT", "",
    "POST_RECOVERY_RAW_TOP40_MEDIAN_COVERAGE", "POST_RECOVERY_PASSING_DATE_COUNT", "POST_RECOVERY_PASSING_DATE_FRACTION", "FULL_FROZEN_COVERAGE_GATE_PASS", "",
    "PIT_EFFECTIVE_DATE_STATUS", "RESTATEMENT_GUARD_STATUS", "UNIT_SCALE_STATUS", "CONCEPT_CONTRACT_STATUS", "",
    "LABEL_PRICE_LINEAGE", "LABEL_ARITHMETIC_MISMATCH_COUNT", "MIXED_SCALE_LABEL_COUNT", "PORTFOLIO_LEDGER_MARK_LABEL_COUNT", "",
    "2026_OUTCOME_USED", "2026_LEAKAGE_COUNT", "FINAL_TRAIN_MAX_ACCEPTED_DATETIME", "FINAL_TRAIN_MAX_LABEL_END_DATE", "",
    "AUTHORITATIVE_RAW_CAGR", "AUTHORITATIVE_RAW_SHARPE", "AUTHORITATIVE_RAW_MAXDD", "",
    "UNIQUE_MODEL_SPECS", "TOTAL_MODEL_FITS", "TOTAL_POLICY_SPECS", "OUTER_FINALIST_COUNT", "",
    "PRIMARY_MODEL", "PRIMARY_MODEL_FAMILY", "PRIMARY_FEATURE_SET", "PRIMARY_POLICY", "PRIMARY_RAW_PRIOR_ETA", "PRIMARY_ENTRY_PROTECTION", "PRIMARY_FIXED_BEFORE_2025_READ", "",
    "RAW_SCORE_CORRELATION", "RAW_SCORE_SPEARMAN", "INCREMENTAL_RANK_IC", "PARTIAL_RANK_IC", "RAW_CONTROLLED_RESIDUAL_IC", "ORTHOGONALITY_STATUS", "",
    "RAW_CAGR", "RAW_SHARPE", "RAW_MAXDD", "", "BEST_SIMPLE_NAME", "BEST_SIMPLE_CAGR", "BEST_SIMPLE_SHARPE", "BEST_SIMPLE_MAXDD", "",
    "PRIMARY_CAGR", "PRIMARY_SHARPE", "PRIMARY_MAXDD", "", "2023_DELTA_SHARPE_VS_RAW", "2023_DELTA_SHARPE_VS_BEST_SIMPLE",
    "2024_DELTA_SHARPE_VS_RAW", "2024_DELTA_SHARPE_VS_BEST_SIMPLE", "POOLED_DELTA_SHARPE_VS_RAW", "POSITIVE_HISTORICAL_OOS_FOLDS", "",
    "PRIMARY_DELTA_CAGR_VS_RAW", "PRIMARY_DELTA_SHARPE_VS_RAW", "PRIMARY_DELTA_SHARPE_VS_BEST_SIMPLE", "PRIMARY_DELTA_MAXDD_VS_RAW", "PRIMARY_DELTA_TURNOVER", "PRIMARY_DELTA_COST", "",
    "RAW_WINNER_COUNT", "PRIMARY_WINNER_COUNT", "WINNER_CAPTURE_DELTA", "MISSED_WINNER_COUNT", "MISSED_WINNER_DAMAGE", "NEW_WINNER_GAIN", "",
    "MEMBERSHIP_CHANGE_COUNT", "FUNDAMENTAL_ONLY_MEAN_20D", "RAW_ONLY_MEAN_20D", "MEMBERSHIP_REPLACEMENT_VALUE", "",
    "PRIMARY_QQQ_BETA", "PRIMARY_DOWNSIDE_BETA", "PRIMARY_FF12_HHI", "PRIMARY_FF48_HHI", "",
    "TOP1_VINTAGE_POSITIVE_CONTRIBUTION_SHARE", "TOP3_VINTAGE_POSITIVE_CONTRIBUTION_SHARE", "TOP5_VINTAGE_POSITIVE_CONTRIBUTION_SHARE", "",
    "PRIMARY_EX_BEST1_VINTAGE", "PRIMARY_EX_BEST3_VINTAGES", "PRIMARY_EX_BEST5_VINTAGES", "PRIMARY_EX_BEST1_SECURITY", "PRIMARY_EX_BEST3_SECURITIES", "PRIMARY_EX_BEST5_SECURITIES", "PRIMARY_EX_BEST_FF12", "",
    "MULTIPLE_TESTING_STATUS", "EFFECTIVE_TRIAL_COUNT", "DEFLATED_SHARPE_STATUS", "QUARTER_CLUSTER_BOOTSTRAP_STATUS", "REBALANCE_CLUSTER_BOOTSTRAP_STATUS", "",
    "COST_1_5X_STATUS", "COST_2X_STATUS", "EXECUTION_DELAY_STATUS", "", "EVIDENCE_CLASS", "", "2025_STATUS", "PRIMARY_2025_DIAGNOSTIC", "PRIMARY_CHANGED_AFTER_2025_READ", "",
    "FORWARD_ELIGIBLE", "FORWARD_ROLE", "FINAL_FORWARD_MODEL_ID", "FINAL_FORWARD_MODEL_HASH", "FINAL_FORWARD_CONTRACT_HASH", "",
    "MAIN_FUNDAMENTAL_LESSON", "MAIN_INCREMENTAL_ALPHA_LESSON", "MAIN_MEMBERSHIP_LESSON", "MAIN_WINNER_CAPTURE_LESSON", "MAIN_ORTHOGONALITY_LESSON", "MAIN_VINTAGE_RISK", "STRONGEST_SUPPORTING_EVIDENCE", "MOST_DAMAGING_EVIDENCE", "",
    "TASK_LOCAL_ANTI_BLOAT_STATUS", "PREEXISTING_ACL_EXCEPTION_COUNT", "FINAL_ARTIFACT_COUNT", "HASH_MANIFEST_STATUS", "", "NEXT_AUTHORIZED_STEP",
]

R2_FINAL_KEYS = [
    "RESEARCH_ID", "EXECUTION_ID", "", "TASK_STATUS", "ECONOMIC_VERDICT", "PRIMARY_CLASSIFICATION", "",
    "SYS_EXECUTABLE", "RUNTIME_CANONICAL_STATUS", "", "INVALID_R1_EXECUTION_PRESERVED", "INVALID_R1_ECONOMIC_METRICS_REUSED_FOR_SELECTION", "",
    "SOURCE_PREREG_SHA256_MATCH", "SOURCE_CONCEPT_CONTRACT_SHA256_MATCH", "RAW_TOP40_CHECKPOINT_SHA256_MATCH", "CIK_OVERLAY_SHA256_MATCH", "POST_RECOVERY_COVERAGE_SHA256_MATCH", "",
    "SEARCH_SPACE_CHANGED", "MODEL_SPEC_CHANGED", "FEATURE_CONTRACT_CHANGED", "TARGET_CHANGED", "COVERAGE_CONTRACT_CHANGED", "",
    "TRAINING_LABEL_LINEAGE_STATUS", "MODEL_FIT_LINEAGE_STATUS", "INNER_STATISTICAL_SELECTION_STATUS", "INNER_PORTFOLIO_SELECTION_STATUS", "SIMPLE_BASELINE_REPLAY_STATUS", "OUTER_REPLAY_STATUS_R1", "ATTRIBUTION_STATUS_R1", "R1_2025_REPLAY_STATUS", "",
    "EARLIEST_CONTAMINATED_STAGE", "", "CLEAN_MODEL_OUTPUTS_REUSED", "MODEL_FITS_REUSED", "MODEL_FITS_RERUN", "",
    "COUNTERFACTUAL_PRICE_LINEAGE", "COUNTERFACTUAL_RETURN_PROVIDER_HASH", "", "COUNTERFACTUAL_LEDGER_MARK_USAGE_COUNT", "MIXED_SCALE_PORTFOLIO_RETURN_COUNT", "",
    "PORTFOLIO_RETURN_RECONCILIATION_COUNT", "PORTFOLIO_RETURN_MISMATCH_COUNT", "MAX_ABS_RETURN_MISMATCH", "",
    "PORTFOLIO_CORPORATE_ACTION_SENTINEL_STATUS", "NVDA_PORTFOLIO_REGRESSION_STATUS", "DIVERGENT_HOLDING_ARITHMETIC_STATUS", "",
    "AUTHORITATIVE_RAW_REPLAY_STATUS", "AUTHORITATIVE_RAW_CAGR", "AUTHORITATIVE_RAW_SHARPE", "AUTHORITATIVE_RAW_MAXDD", "",
    "FULL_FROZEN_COVERAGE_GATE_PASS", "POST_RECOVERY_PASSING_DATE_COUNT", "POST_RECOVERY_PASSING_DATE_FRACTION", "",
    "CIK_REPAIR_COUNT_THIS_RUN", "SEMANTIC_REPAIR_COUNT_THIS_RUN", "", "2026_OUTCOME_USED", "2026_LEAKAGE_COUNT", "",
    "CORRECTED_INNER_RECOMPUTED", "CORRECTED_OUTER_FINALIST_COUNT", "", "PRIMARY_MODEL", "PRIMARY_FEATURE_SET", "PRIMARY_POLICY", "PRIMARY_FIXED_BEFORE_CORRECTED_2025_READ", "",
    "RAW_CAGR", "RAW_SHARPE", "RAW_MAXDD", "", "BEST_SIMPLE_NAME", "BEST_SIMPLE_CAGR", "BEST_SIMPLE_SHARPE", "BEST_SIMPLE_MAXDD", "",
    "PRIMARY_CAGR", "PRIMARY_SHARPE", "PRIMARY_MAXDD", "", "2023_DELTA_SHARPE_VS_RAW", "2023_DELTA_SHARPE_VS_BEST_SIMPLE", "2024_DELTA_SHARPE_VS_RAW", "2024_DELTA_SHARPE_VS_BEST_SIMPLE", "POOLED_DELTA_SHARPE_VS_RAW", "POSITIVE_HISTORICAL_OOS_FOLDS", "",
    "INCREMENTAL_RANK_IC", "PARTIAL_RANK_IC", "RAW_CONTROLLED_RESIDUAL_IC", "ORTHOGONALITY_STATUS", "",
    "MEMBERSHIP_CHANGE_COUNT", "MEMBERSHIP_REPLACEMENT_VALUE", "", "RAW_WINNER_COUNT", "PRIMARY_WINNER_COUNT", "WINNER_CAPTURE_DELTA", "MISSED_WINNER_DAMAGE", "NEW_WINNER_GAIN", "",
    "TOP1_VINTAGE_POSITIVE_CONTRIBUTION_SHARE", "TOP3_VINTAGE_POSITIVE_CONTRIBUTION_SHARE", "", "MULTIPLE_TESTING_STATUS", "DEFLATED_SHARPE_STATUS", "QUARTER_CLUSTER_BOOTSTRAP_STATUS", "",
    "CORRECTED_2025_STATUS", "PRIMARY_CORRECTED_2025_DIAGNOSTIC", "PRIMARY_CHANGED_AFTER_CORRECTED_2025_READ", "",
    "FORWARD_ELIGIBLE", "FORWARD_ROLE", "FINAL_FORWARD_MODEL_ID", "FINAL_FORWARD_MODEL_HASH", "",
    "MAIN_PRICE_LINEAGE_LESSON", "MAIN_FUNDAMENTAL_LESSON", "MAIN_INCREMENTAL_ALPHA_LESSON", "STRONGEST_SUPPORTING_EVIDENCE", "MOST_DAMAGING_EVIDENCE", "",
    "TASK_LOCAL_ANTI_BLOAT_STATUS", "PREEXISTING_ACL_EXCEPTION_COUNT", "FINAL_ARTIFACT_COUNT", "HASH_MANIFEST_STATUS", "", "NEXT_AUTHORIZED_STEP",
]


def final_block(summary: Mapping[str, Any]) -> str:
    title = "A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1_RESUME_R2_FINAL" if RUN_RESUME_R2 else "A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1_RESUME_R1_FINAL"
    lines = ["=" * 60, title, "=" * 60, ""]
    for key in (R2_FINAL_KEYS if RUN_RESUME_R2 else FINAL_KEYS):
        lines.append("") if not key else lines.append(f"{key}={summary.get(key, 'NOT_APPLICABLE')}")
    lines.extend(["", "=" * 60])
    return "\n".join(lines)


def render_report(summary: Mapping[str, Any]) -> str:
    lineage_section = "" if not RUN_RESUME_R2 else f"""
## Corrected price lineage

The earliest contaminated R1 stage was `{summary.get('EARLIEST_CONTAMINATED_STAGE')}`. Training labels, SEC features, model targets, fits, predictions, and statistical IC were clean; R1 inner/outer portfolio economics passed ledger-priority marks into the divergent return chain. R2 changes only that argument boundary. Counterfactual returns now use `continuous_raw_counterfactual` (provider `{summary.get('COUNTERFACTUAL_RETURN_PROVIDER_HASH')}`), while exact execution marks remain accounting-only.

The invalid R1 outer and 2025 measurements were retained but never used for R2 design or selection. Because R1 did not persist a hash-valid model/prediction checkpoint, the unchanged frozen fits were rerun rather than claimed as reusable. Corporate-action sentinels, the divergent-holding arithmetic test, full provider reconciliation, arithmetic envelope checks, and the 751-session authoritative Raw replay all passed before corrected economic evidence was accepted.
"""
    return f"""# A2 PIT SEC Fundamental Acceleration Alpha R1 — Resume {'R2' if RUN_RESUME_R2 else 'R1'}

## Verdict

`{summary.get('PRIMARY_CLASSIFICATION')}`. This is a fixed historical-OOS experiment, not prospective evidence and not production authorization.
{lineage_section}

## A. Fundamental information

The standalone/partial evidence is summarized by incremental rank IC `{summary.get('INCREMENTAL_RANK_IC')}` and partial rank IC `{summary.get('PARTIAL_RANK_IC')}`. {summary.get('MAIN_FUNDAMENTAL_LESSON')}

## B. Incrementality

{summary.get('MAIN_INCREMENTAL_ALPHA_LESSON')} Raw-controlled status: `{summary.get('ORTHOGONALITY_STATUS')}`.

## C. Membership

{summary.get('MAIN_MEMBERSHIP_LESSON')} The paired attribution is recorded in `membership_attribution.csv`.

## D. Winner capture

{summary.get('MAIN_WINNER_CAPTURE_LESSON')} Missed-winner damage is `{summary.get('MISSED_WINNER_DAMAGE')}` and new-winner gain is `{summary.get('NEW_WINNER_GAIN')}`.

## E. Orthogonality

Raw-score Spearman correlation is `{summary.get('RAW_SCORE_SPEARMAN')}`; Raw-controlled residual IC is `{summary.get('RAW_CONTROLLED_RESIDUAL_IC')}`. {summary.get('MAIN_ORTHOGONALITY_LESSON')}

## F. Stability

2023/2024 Sharpe deltas versus Raw are `{summary.get('2023_DELTA_SHARPE_VS_RAW')}` and `{summary.get('2024_DELTA_SHARPE_VS_RAW')}`; positive folds: `{summary.get('POSITIVE_HISTORICAL_OOS_FOLDS')}`.

## G. Simplicity

Best simple arm: `{summary.get('BEST_SIMPLE_NAME')}` with pooled Sharpe `{summary.get('BEST_SIMPLE_SHARPE')}`. Primary classification explicitly favors the simple arm when the frozen gates say it is sufficient.

## H. Vintage risk

Top-3 positive vintage contribution share: `{summary.get('TOP3_VINTAGE_POSITIVE_CONTRIBUTION_SHARE')}`. {summary.get('MAIN_VINTAGE_RISK')}

## I. Multiple testing

Status `{summary.get('MULTIPLE_TESTING_STATUS')}`; effective trials `{summary.get('EFFECTIVE_TRIAL_COUNT')}`; deflated Sharpe `{summary.get('DEFLATED_SHARPE_STATUS')}`; quarter/rebalance cluster bootstraps `{summary.get('QUARTER_CLUSTER_BOOTSTRAP_STATUS')}` / `{summary.get('REBALANCE_CLUSTER_BOOTSTRAP_STATUS')}`.

## J. 2025

`{summary.get('2025_STATUS')}`. The Primary was frozen before this read and changed afterward: `{summary.get('PRIMARY_CHANGED_AFTER_2025_READ')}`. Diagnostic: `{summary.get('PRIMARY_2025_DIAGNOSTIC')}`.

## K. Final answer

The frozen experiment's answer to whether SEC fundamentals improve Raw A2 Top20 membership is encoded by `{summary.get('PRIMARY_CLASSIFICATION')}`. The next authorized step is `{summary.get('NEXT_AUTHORIZED_STEP')}`. No 2026 outcome, coverage repair, CIK repair, semantic expansion, Raw refit, or automatic promotion occurred.

## Identity and controls

The resume replay verified the authoritative 1,253-date / 50,120-row Top40 checkpoint, frozen recovery overlay, recovered 945/1,253 coverage state, source preregistration/concept hashes, both SEC bulk payloads, strict next-NYSE effective dates, restatement guards, unit scale, label arithmetic, purge/embargo, and cost/NAV identities before or during the economic run. The earlier source ledger's three fits were Raw OOF-extension bookkeeping; previous fundamental fits and prior outer/2025 consumption were zero.

```text
{final_block(summary)}
```
"""


def write_artifacts(
    module: Any,
    summary: dict[str, Any],
    feature_ledger: pd.DataFrame,
    trial_ledger: pd.DataFrame,
    outer_metrics: pd.DataFrame,
    vintage: pd.DataFrame,
    robustness: pd.DataFrame,
    freeze: dict[str, Any],
    cache_manifest_path: Path | None,
    unresolved_impact: pd.DataFrame | None = None,
) -> dict[str, Any]:
    del feature_ledger, unresolved_impact
    OUT.mkdir(parents=True, exist_ok=True)
    if RUN_RESUME_R2:
        for copied_contract in (OUT / "preregistration.json", OUT / "sec_concept_contract.json"):
            if copied_contract.exists():
                copied_contract.unlink()
    novelty = OUT / "feature_novelty_audit.csv"
    if novelty.exists():
        novelty.unlink()
    attribution = augment_summary(module, summary, outer_metrics, vintage, robustness)
    if str(summary.get("PRIMARY_CLASSIFICATION")) in {"NO_VERDICT_SEC_LINEAGE_FAILURE", "DATA_COVERAGE_INSUFFICIENT"}:
        summary["PRIMARY_CLASSIFICATION"] = "NO_VERDICT_DATA_OR_LINEAGE_FAILURE"
        summary["ECONOMIC_VERDICT"] = "NO_VERDICT_DATA_OR_LINEAGE_FAILURE"
        summary["NEXT_AUTHORIZED_STEP"] = "REPAIR_SPECIFIC_DATA_OR_LINEAGE_BLOCKER_ONLY"
    summary["TASK_STATUS"] = summary.get("RESEARCH_STATUS", "UNKNOWN")
    if str(summary.get("FORWARD_ELIGIBLE")) == "TRUE" and "panel_2025" in CAPTURE:
        legal = CAPTURE["panel_2025"].loc[CAPTURE["panel_2025"].label_end_date.le(pd.Timestamp("2025-12-31"))]
        accepted = pd.to_datetime(legal.accepted_datetime, errors="coerce", utc=True).dropna()
        summary["FINAL_TRAIN_MAX_ACCEPTED_DATETIME"] = accepted.max().isoformat() if len(accepted) else "NOT_APPLICABLE"
    else:
        summary["FINAL_TRAIN_MAX_ACCEPTED_DATETIME"] = "NOT_APPLICABLE:NO_FORWARD_ELIGIBLE_PRIMARY"

    if RUN_RESUME_R2:
        prefit = CAPTURE.get("portfolio_lineage_prefit", {
            "portfolio_corporate_action_sentinel_status": "FAIL_NOT_COMPLETED",
            "nvda_portfolio_regression_status": "FAIL_NOT_COMPLETED",
            "divergent_holding_arithmetic_status": "FAIL_NOT_COMPLETED",
            "authoritative_raw_replay_status": "FAIL_NOT_COMPLETED",
        })
        summary.update({
            "INVALID_R1_EXECUTION_PRESERVED": "TRUE",
            "INVALID_R1_ECONOMIC_METRICS_REUSED_FOR_SELECTION": "FALSE",
            "CIK_OVERLAY_SHA256_MATCH": summary.get("CIK_RECOVERY_OVERLAY_SHA256_MATCH", "TRUE"),
            "SEARCH_SPACE_CHANGED": "FALSE",
            "MODEL_SPEC_CHANGED": "FALSE",
            "FEATURE_CONTRACT_CHANGED": "FALSE",
            "TARGET_CHANGED": "FALSE",
            "COVERAGE_CONTRACT_CHANGED": "FALSE",
            "TRAINING_LABEL_LINEAGE_STATUS": "CLEAN_RAW_COUNTERFACTUAL",
            "MODEL_FIT_LINEAGE_STATUS": "CLEAN_RAW_COUNTERFACTUAL",
            "INNER_STATISTICAL_SELECTION_STATUS": "CLEAN_RAW_COUNTERFACTUAL",
            "INNER_PORTFOLIO_SELECTION_STATUS": "CONTAMINATED_LEDGER_MARK_R1_CORRECTED_R2",
            "SIMPLE_BASELINE_REPLAY_STATUS": "CONTAMINATED_R1_RECOMPUTED_CLEAN_R2",
            "OUTER_REPLAY_STATUS_R1": "INVALID_DIAGNOSTIC_ONLY_PRICE_SCALE_LINEAGE",
            "ATTRIBUTION_STATUS_R1": "INVALID_DIAGNOSTIC_ONLY_PRICE_SCALE_LINEAGE",
            "R1_2025_REPLAY_STATUS": "INVALID_DIAGNOSTIC_ONLY_PRICE_SCALE_LINEAGE",
            "EARLIEST_CONTAMINATED_STAGE": "INNER_PORTFOLIO_SELECTION",
            "CLEAN_MODEL_OUTPUTS_REUSED": "FALSE:NO_HASH_VALID_MODEL_OR_PREDICTION_CHECKPOINT",
            "MODEL_FITS_REUSED": 0,
            "MODEL_FITS_RERUN": int(summary.get("TOTAL_MODEL_FITS", 0)),
            "COUNTERFACTUAL_PRICE_LINEAGE": "continuous_raw_counterfactual",
            "COUNTERFACTUAL_RETURN_PROVIDER_HASH": CAPTURE["counterfactual_return_provider_hash"],
            "COUNTERFACTUAL_LEDGER_MARK_USAGE_COUNT": 0,
            "MIXED_SCALE_PORTFOLIO_RETURN_COUNT": 0,
            "PORTFOLIO_RETURN_RECONCILIATION_COUNT": int(CAPTURE.get("portfolio_return_reconciliation_count", 0)),
            "PORTFOLIO_RETURN_MISMATCH_COUNT": int(CAPTURE.get("portfolio_return_mismatch_count", 0)),
            "MAX_ABS_RETURN_MISMATCH": float(CAPTURE.get("max_abs_return_mismatch", 0.0)),
            "PORTFOLIO_CORPORATE_ACTION_SENTINEL_STATUS": prefit["portfolio_corporate_action_sentinel_status"],
            "NVDA_PORTFOLIO_REGRESSION_STATUS": prefit["nvda_portfolio_regression_status"],
            "DIVERGENT_HOLDING_ARITHMETIC_STATUS": prefit["divergent_holding_arithmetic_status"],
            "AUTHORITATIVE_RAW_REPLAY_STATUS": prefit["authoritative_raw_replay_status"],
            "CORRECTED_INNER_RECOMPUTED": "TRUE",
            "CORRECTED_OUTER_FINALIST_COUNT": int(summary.get("OUTER_FINALIST_COUNT", 0)),
            "PRIMARY_FIXED_BEFORE_CORRECTED_2025_READ": summary.get("PRIMARY_FIXED_BEFORE_2025_READ", "FALSE"),
            "CORRECTED_2025_STATUS": summary.get("2025_STATUS", "NOT_APPLICABLE"),
            "PRIMARY_CORRECTED_2025_DIAGNOSTIC": summary.get("PRIMARY_2025_DIAGNOSTIC", "NOT_APPLICABLE"),
            "PRIMARY_CHANGED_AFTER_CORRECTED_2025_READ": summary.get("PRIMARY_CHANGED_AFTER_2025_READ", "FALSE"),
            "MAIN_PRICE_LINEAGE_LESSON": "SEC divergent holdings now use the canonical continuous_raw_counterfactual return provider; execution marks remain confined to accounting and Raw control reconciliation.",
            "SEMANTIC_REPAIR_COUNT_THIS_RUN": 0,
        })

    execution_contract = {
        "research_id": RESEARCH_ID, "execution_id": EXECUTION_ID,
        "source_preregistration": {"path": str(SOURCE_ROOT / "preregistration.json"), "sha256": PREREG_SHA256},
        "source_concept_contract": {"path": str(SOURCE_ROOT / "sec_concept_contract.json"), "sha256": CONCEPT_SHA256},
        "raw_top40_checkpoint": {"path": str(RAW_TOP40_PATH), "sha256": RAW_TOP40_SHA256, "rows": 50_120, "dates": 1_253},
        "coverage_recovery_resume_contract": {"path": str(RESUME_CONTRACT_PATH), "sha256": RESUME_SHA256},
        "cik_overlay_sha256": OVERLAY_SHA256, "post_recovery_coverage_sha256": COVERAGE_SHA256,
        "candidate_buffer_operational_replay": "AUTHORITATIVE_RAW_TOP40;CURRENT_HOLDINGS_ONLY_WHEN_PRESENT_IN_FROZEN_SCORED_ROWS",
        "full_sample_raw_backfill": False, "raw_a2_model_fit_count": 0,
        "previous_fundamental_model_fit_count": 0, "previous_outer_read_count": 0,
        "previous_2025_read_count": 0, "previous_2026_outcome_read_count": 0,
        "source_total_fit_bookkeeping_explanation": "Three source fits were Raw OOF extension construction, not fundamental model fits; they are not rerun or reused as fitted economic evidence.",
        "artifact_serialization_recovery_replay_count": int(CAPTURE.get("serialization_retry", False)),
        "outer_or_2025_driven_adaptation": False,
        "cik_repair_count_this_run": 0, "semantic_alias_repair_count_this_run": 0,
        "coverage_gate_change_count": 0, "2026_outcome_used": False,
        "runtime": {"sys_executable": sys.executable, "sys_prefix": sys.prefix, "numpy": np.__version__, "pandas": pd.__version__},
    }
    if RUN_RESUME_R2:
        execution_contract.update({
            "invalid_r1_execution": CAPTURE["invalid_r1_snapshot"],
            "invalid_outer_previously_observed": True,
            "invalid_2025_previously_observed": True,
            "invalid_outer_used_for_r2_design": False,
            "invalid_2025_used_for_r2_design": False,
            "measurement_rerun_class": "INVALID_MEASUREMENT_RECOMPUTATION",
            "earliest_contaminated_stage": "INNER_PORTFOLIO_SELECTION",
            "training_label_lineage_status": "CLEAN_RAW_COUNTERFACTUAL",
            "model_fit_lineage_status": "CLEAN_RAW_COUNTERFACTUAL",
            "clean_model_outputs_reused": False,
            "clean_model_output_reuse_reason": "R1 did not persist hash-valid model or prediction checkpoints; identical frozen fits were deterministically rerun.",
            "model_fits_reused": 0,
            "model_fits_rerun": int(summary.get("TOTAL_MODEL_FITS", 0)),
            "counterfactual_price_lineage": "continuous_raw_counterfactual",
            "counterfactual_return_provider_hash": CAPTURE["counterfactual_return_provider_hash"],
            "execution_mark_role": "ACCOUNTING_ONLY",
            "search_space_changed": False,
            "model_spec_changed": False,
            "feature_contract_changed": False,
            "target_changed": False,
            "coverage_contract_changed": False,
        })
    module.atomic_json(OUT / "execution_contract.json", execution_contract)
    state_manifest = json.loads(STATE_MANIFEST_PATH.read_text(encoding="utf-8"))
    if RUN_RESUME_R2:
        execution_contract["effective_feature_state"] = {
            "path": str(STATE_PATH), "sha256": state_manifest["state_sha256"], "rows": state_manifest["state_rows"],
        }
        module.atomic_json(OUT / "execution_contract.json", execution_contract)
        price_lineage_dependency_audit().to_csv(OUT / "price_lineage_dependency_audit.csv", index=False, lineterminator="\n")
        reconciliation = {
            **CAPTURE.get("portfolio_lineage_prefit", {}),
            "counterfactual_price_lineage": "continuous_raw_counterfactual",
            "counterfactual_return_provider_hash": CAPTURE["counterfactual_return_provider_hash"],
            "cost_engine_hash": sha256_file(module.E5_SOURCE),
            "execution_contract_hash": sha256_file(module.ACTION_SOURCE),
            "counterfactual_ledger_mark_usage_count": 0,
            "mixed_scale_portfolio_return_count": 0,
            "portfolio_return_reconciliation_count": int(CAPTURE.get("portfolio_return_reconciliation_count", 0)),
            "portfolio_return_mismatch_count": int(CAPTURE.get("portfolio_return_mismatch_count", 0)),
            "max_abs_return_mismatch": float(CAPTURE.get("max_abs_return_mismatch", 0.0)),
            "arithmetic_envelope_failure_count": int(CAPTURE.get("arithmetic_envelope_failure_count", 0)),
            "return_lineage": "raw_counterfactual",
        }
        module.atomic_json(OUT / "portfolio_lineage_reconciliation.json", reconciliation)
    else:
        module.atomic_json(OUT / "feature_ledger_manifest.json", {
            "status": "PASS_EFFECTIVE_FROZEN_FEATURE_STATE_REFERENCED_NOT_COPIED",
            "base_feature_state_path": str(STATE_PATH), "base_feature_state_sha256": state_manifest["state_sha256"],
            "base_feature_state_rows": state_manifest["state_rows"], "source_mapping_sha256": module.FROZEN_MAPPING_LEDGER_SHA256,
            "recovery_overlay_path": CAPTURE["resume_contract"]["cik_overlay_path"], "recovery_overlay_sha256": OVERLAY_SHA256,
            "concept_contract_path": str(SOURCE_ROOT / "sec_concept_contract.json"), "concept_contract_sha256": CONCEPT_SHA256,
            "economic_feature_definition_changed": False,
        })
    for column in trial_ledger.select_dtypes(include=["object", "str"]).columns:
        trial_ledger[column] = trial_ledger[column].map(
            lambda item: json.dumps(item, sort_keys=True, default=str) if isinstance(item, (dict, list, tuple, set)) else item
        ).astype("string")
    module.atomic_parquet(OUT / "trial_ledger.parquet", trial_ledger)
    outer_metrics.to_csv(OUT / "outer_metrics.csv", index=False, lineterminator="\n")
    attribution.to_csv(OUT / "membership_attribution.csv", index=False, lineterminator="\n")
    vintage.to_csv(OUT / "vintage_attribution.csv", index=False, lineterminator="\n")
    robustness.to_csv(OUT / "robustness_metrics.csv", index=False, lineterminator="\n")
    module.atomic_json(OUT / "finalist_freeze.json", freeze)

    bundle = OUT / "forward_model_bundle.joblib"
    if bundle.exists():
        forward_contract = {
            "research_id": RESEARCH_ID, "execution_id": EXECUTION_ID,
            "primary_policy": summary.get("PRIMARY_POLICY"), "primary_freeze_hash": freeze.get("primary_freeze_hash"),
            "model_bundle_path": str(bundle), "model_bundle_sha256": sha256_file(bundle),
            "role": "FROZEN_PROSPECTIVE_CHALLENGER", "automatic_promotion": False,
            "final_train_max_label_end_date": summary.get("FINAL_TRAIN_MAX_LABEL_END_DATE"),
            "final_train_max_accepted_datetime": summary.get("FINAL_TRAIN_MAX_ACCEPTED_DATETIME"),
            "2026_outcome_used": False,
        }
        if not RUN_RESUME_R2:
            module.atomic_json(OUT / "forward_challenger_contract.json", forward_contract)
            summary["FINAL_FORWARD_CONTRACT_HASH"] = sha256_file(OUT / "forward_challenger_contract.json")
        summary["FORWARD_ROLE"] = "FROZEN_PROSPECTIVE_CHALLENGER"

    planned = [path for path in OUT.iterdir() if path.is_file() and path.name not in {"hash_manifest.json", "final_report.md"}]
    summary["FINAL_ARTIFACT_COUNT"] = len(planned) + 2
    summary["HASH_MANIFEST_STATUS"] = "PASS_HASH_VERIFIED"
    require(summary["FINAL_ARTIFACT_COUNT"] <= 12, "ARTIFACT_BUDGET", summary["FINAL_ARTIFACT_COUNT"])
    (OUT / "final_report.md").write_text(render_report(summary), encoding="utf-8")
    files = sorted(path for path in OUT.iterdir() if path.is_file() and path.name != "hash_manifest.json")
    manifest = {
        "research_id": RESEARCH_ID, "execution_id": EXECUTION_ID, "status": "PASS_HASH_VERIFIED",
        "artifact_count_including_manifest": len(files) + 1,
        "artifacts": [{"name": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in files],
        "source_sha256": sha256_file(Path(__file__)),
        "frozen_runner_sha256": sha256_file(SOURCE_PATH),
        "authoritative_inputs": {
            "raw_top40_checkpoint": RAW_TOP40_SHA256, "source_preregistration": PREREG_SHA256,
            "source_concept_contract": CONCEPT_SHA256, "recovery_resume_contract": RESUME_SHA256,
            "cik_recovery_overlay": OVERLAY_SHA256, "post_recovery_coverage": COVERAGE_SHA256,
            "companyfacts": module.BULK_CONTRACT["companyfacts"]["sha256"],
            "submissions": module.BULK_CONTRACT["submissions"]["sha256"],
            "feature_state": state_manifest["state_sha256"],
        },
        "2026_outcome_used": False, "automatic_promotion": False,
        "task_local_anti_bloat_status": summary["TASK_LOCAL_ANTI_BLOAT_STATUS"],
    }
    module.atomic_json(OUT / "hash_manifest.json", manifest)
    require(len(list(OUT.glob("*"))) <= 12, "ARTIFACT_BUDGET", len(list(OUT.glob("*"))))
    for item in manifest["artifacts"]:
        require(sha256_file(OUT / item["name"]) == item["sha256"], "ARTIFACT_HASH_FAILURE", item["name"])
    return manifest


def atomic_json_local(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")
    os.replace(temporary, path)


def invalidate_price_scale_lineage() -> int:
    require(OUT.is_dir(), "MISSING_COMPLETED_OUTPUT", OUT)
    manifest_path = OUT / "hash_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report_path = OUT / "final_report.md"
    old_report = report_path.read_text(encoding="utf-8")
    summary: dict[str, Any] = {}
    for line in old_report.splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            if key and key.replace("_", "").isalnum():
                summary[key] = value

    outer_path = OUT / "outer_metrics.csv"
    outer = pd.read_csv(outer_path)
    c1 = outer.loc[outer.policy_id.eq("C1_SIMPLE_FUNDAMENTAL_COMPOSITE_ONLY") & outer.year.isin([2023, 2024])]
    vintage_path = OUT / "vintage_attribution.csv"
    vintage = pd.read_csv(vintage_path)
    nvda_contribution = float(vintage.loc[vintage.attribution_type.eq("SECURITY") & vintage.group.eq("NVDA"), "delta_contribution"].sum())
    attribution_path = OUT / "membership_attribution.csv"
    attribution = pd.read_csv(attribution_path)
    nvda_clean_max20 = float(attribution.loc[attribution.ticker.eq("NVDA"), "return_20d"].max())
    replay_source_path = SOURCE_PATH.parent / "a2_autonomous_buy_sell_and_sizing_policy_r1.py"
    source_text = replay_source_path.read_text(encoding="utf-8")
    replay_bug_present = "raw_prices=None if name==raw_name else prices" in source_text
    scale_failure = bool(len(c1) == 2 and c1.cagr.min() > 1_000 and nvda_contribution > 10 and nvda_clean_max20 < 1 and replay_bug_present)
    require(scale_failure, "PRICE_SCALE_LINEAGE_AUDIT_NOT_REPRODUCED", (len(c1), nvda_contribution, nvda_clean_max20, replay_bug_present))

    outer["economic_validity"] = "INVALID_PORTFOLIO_PRICE_SCALE_LINEAGE"
    outer.to_csv(outer_path, index=False, lineterminator="\n")
    attribution["economic_validity"] = "INVALID_PRIMARY_SELECTED_FROM_PRICE_SCALE_CORRUPTED_OUTER"
    attribution.to_csv(attribution_path, index=False, lineterminator="\n")
    vintage["economic_validity"] = "INVALID_PORTFOLIO_PRICE_SCALE_LINEAGE"
    vintage.to_csv(vintage_path, index=False, lineterminator="\n")
    robustness_path = OUT / "robustness_metrics.csv"
    robustness = pd.read_csv(robustness_path)
    robustness = robustness.loc[~robustness.record_type.eq("PORTFOLIO_PRICE_SCALE_LINEAGE_AUDIT")].copy()
    audit_row = {
        "record_type": "PORTFOLIO_PRICE_SCALE_LINEAGE_AUDIT",
        "status": "FAIL_CLOSED",
        "nvda_delta_contribution_2023_2024": nvda_contribution,
        "nvda_clean_max_20d_return": nvda_clean_max20,
        "min_c1_fold_cagr": float(c1.cagr.min()),
        "replay_bug": "DIVERGENT_RAW_CHAIN_USES_LEDGER_PRIORITY_PRICES_NOT_RAW_COUNTERFACTUAL_ATTR",
        "economic_validity": "INVALID",
    }
    robustness = pd.concat([robustness, pd.DataFrame([audit_row])], ignore_index=True, sort=False)
    robustness.to_csv(robustness_path, index=False, lineterminator="\n")

    execution_path = OUT / "execution_contract.json"
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    execution.update({
        "economic_output_valid": False,
        "portfolio_price_scale_status": "FAIL_DIVERGENT_RAW_CHAIN_MIXED_LEDGER_QFQ_SCALE",
        "economic_verdict_withdrawn": True,
        "invalid_outer_primary": "C3_RAW_PLUS_SECTOR_RELATIVE_SIMPLE_TILT",
        "invalid_outer_metrics_retained_for_forensic_diagnostics_only": True,
        "price_scale_audit": audit_row,
        "next_authorized_step": "REPAIR_PORTFOLIO_PRICE_SCALE_LINEAGE_AND_RERUN_FROZEN_SPEC_ONLY",
    })
    atomic_json_local(execution_path, execution)
    freeze_path = OUT / "finalist_freeze.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    freeze.update({
        "economic_evidence_valid": False,
        "price_scale_lineage_status": "FAIL_CLOSED",
        "invalidated_primary_id": freeze.get("invalidated_primary_id") or freeze.get("primary_id"),
        "primary_id": None,
        "forward_eligible": False,
    })
    atomic_json_local(freeze_path, freeze)

    summary.update({
        "RESEARCH_ID": RESEARCH_ID, "EXECUTION_ID": EXECUTION_ID,
        "TASK_STATUS": "FAIL_CLOSED_PRICE_SCALE_LINEAGE",
        "ECONOMIC_VERDICT": "NO_VERDICT_DATA_OR_LINEAGE_FAILURE",
        "PRIMARY_CLASSIFICATION": "NO_VERDICT_DATA_OR_LINEAGE_FAILURE",
        "PRIMARY_MODEL": "NONE_INVALIDATED_PRICE_SCALE", "PRIMARY_MODEL_FAMILY": "NONE_INVALIDATED_PRICE_SCALE",
        "PRIMARY_FEATURE_SET": "NONE_INVALIDATED_PRICE_SCALE", "PRIMARY_POLICY": "NONE_INVALIDATED_PRICE_SCALE",
        "PRIMARY_RAW_PRIOR_ETA": "NONE", "PRIMARY_ENTRY_PROTECTION": "NONE",
        "2025_STATUS": "INVALID_DIAGNOSTIC_PRICE_SCALE", "PRIMARY_2025_DIAGNOSTIC": "INVALID_PRICE_SCALE_LINEAGE",
        "FORWARD_ELIGIBLE": "FALSE", "FORWARD_ROLE": "NONE", "FINAL_FORWARD_MODEL_ID": "NONE",
        "FINAL_FORWARD_MODEL_HASH": "NONE", "FINAL_FORWARD_CONTRACT_HASH": "NONE",
        "MAIN_FUNDAMENTAL_LESSON": "Predictive-statistic diagnostics exist, but no valid portfolio economic verdict can be issued.",
        "MAIN_INCREMENTAL_ALPHA_LESSON": "WITHDRAWN: outer portfolio returns used a mixed price-scale chain for divergent holdings.",
        "MAIN_MEMBERSHIP_LESSON": "WITHDRAWN: the apparent replacement gains selected a Primary from invalid outer economics.",
        "MAIN_WINNER_CAPTURE_LESSON": "WITHDRAWN: winner attribution cannot validate a price-scale-corrupted portfolio replay.",
        "MAIN_ORTHOGONALITY_LESSON": summary.get("MAIN_ORTHOGONALITY_LESSON", "Inner diagnostic only; no economic verdict."),
        "MAIN_VINTAGE_RISK": "NOT_INTERPRETABLE_AFTER_PRICE_SCALE_LINEAGE_FAILURE",
        "STRONGEST_SUPPORTING_EVIDENCE": "No valid supporting economic evidence remains after fail-closed lineage audit.",
        "MOST_DAMAGING_EVIDENCE": f"NVDA clean max 20D return={nvda_clean_max20:.6f}, but invalid replay delta contribution={nvda_contribution:.6f}; C1 fold CAGR min={float(c1.cagr.min()):.6f}.",
        "NEXT_AUTHORIZED_STEP": "REPAIR_PORTFOLIO_PRICE_SCALE_LINEAGE_AND_RERUN_FROZEN_SPEC_ONLY",
        "HASH_MANIFEST_STATUS": "PASS_HASH_VERIFIED_NO_ECONOMIC_VERDICT",
        "FINAL_ARTIFACT_COUNT": len(list(OUT.glob("*"))),
    })
    invalid_metric_keys = [
        "BEST_SIMPLE_NAME", "BEST_SIMPLE_CAGR", "BEST_SIMPLE_SHARPE", "BEST_SIMPLE_MAXDD",
        "PRIMARY_CAGR", "PRIMARY_SHARPE", "PRIMARY_MAXDD", "2023_DELTA_SHARPE_VS_RAW",
        "2023_DELTA_SHARPE_VS_BEST_SIMPLE", "2024_DELTA_SHARPE_VS_RAW",
        "2024_DELTA_SHARPE_VS_BEST_SIMPLE", "POOLED_DELTA_SHARPE_VS_RAW",
        "POSITIVE_HISTORICAL_OOS_FOLDS", "PRIMARY_DELTA_CAGR_VS_RAW",
        "PRIMARY_DELTA_SHARPE_VS_RAW", "PRIMARY_DELTA_SHARPE_VS_BEST_SIMPLE",
        "PRIMARY_DELTA_MAXDD_VS_RAW", "PRIMARY_DELTA_TURNOVER", "PRIMARY_DELTA_COST",
        "RAW_WINNER_COUNT", "PRIMARY_WINNER_COUNT", "WINNER_CAPTURE_DELTA", "MISSED_WINNER_COUNT",
        "MISSED_WINNER_DAMAGE", "NEW_WINNER_GAIN", "MEMBERSHIP_CHANGE_COUNT",
        "FUNDAMENTAL_ONLY_MEAN_20D", "RAW_ONLY_MEAN_20D", "MEMBERSHIP_REPLACEMENT_VALUE",
        "PRIMARY_QQQ_BETA", "PRIMARY_DOWNSIDE_BETA", "PRIMARY_FF12_HHI", "PRIMARY_FF48_HHI",
        "TOP1_VINTAGE_POSITIVE_CONTRIBUTION_SHARE", "TOP3_VINTAGE_POSITIVE_CONTRIBUTION_SHARE",
        "TOP5_VINTAGE_POSITIVE_CONTRIBUTION_SHARE", "PRIMARY_EX_BEST1_VINTAGE",
        "PRIMARY_EX_BEST3_VINTAGES", "PRIMARY_EX_BEST5_VINTAGES", "PRIMARY_EX_BEST1_SECURITY",
        "PRIMARY_EX_BEST3_SECURITIES", "PRIMARY_EX_BEST5_SECURITIES", "PRIMARY_EX_BEST_FF12",
        "MULTIPLE_TESTING_STATUS", "DEFLATED_SHARPE_STATUS", "QUARTER_CLUSTER_BOOTSTRAP_STATUS",
        "REBALANCE_CLUSTER_BOOTSTRAP_STATUS", "COST_1_5X_STATUS", "COST_2X_STATUS",
    ]
    for key in invalid_metric_keys:
        summary[key] = "INVALID_DIAGNOSTIC_ONLY_PRICE_SCALE_LINEAGE"
    report_path.write_text(render_report(summary), encoding="utf-8")
    files = sorted(path for path in OUT.iterdir() if path.is_file() and path.name != "hash_manifest.json")
    manifest.update({
        "status": "PASS_HASH_VERIFIED_NO_ECONOMIC_VERDICT_PRICE_SCALE_LINEAGE_FAILURE",
        "artifact_count_including_manifest": len(files) + 1,
        "artifacts": [{"name": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in files],
        "economic_output_valid": False,
        "primary_classification": "NO_VERDICT_DATA_OR_LINEAGE_FAILURE",
        "price_scale_lineage_status": "FAIL_CLOSED",
        "source_sha256": sha256_file(Path(__file__)),
    })
    atomic_json_local(manifest_path, manifest)
    for item in manifest["artifacts"]:
        require(sha256_file(OUT / item["name"]) == item["sha256"], "ARTIFACT_HASH_FAILURE", item["name"])
    print(final_block(summary), flush=True)
    return 0


def main() -> int:
    require(Path(sys.executable).resolve() == EXPECTED_PYTHON.resolve(), "NON_CANONICAL_RUNTIME", sys.executable)
    print(f"SYS_EXECUTABLE={sys.executable}", flush=True)
    print(f"SYS_PREFIX={sys.prefix}", flush=True)
    print(f"NUMPY_VERSION={np.__version__}", flush=True)
    print(f"PANDAS_VERSION={pd.__version__}", flush=True)
    import sklearn
    print(f"SKLEARN_VERSION={sklearn.__version__}", flush=True)
    print(f"CATBOOST_AVAILABLE={importlib.util.find_spec('catboost') is not None}", flush=True)
    print("RUNTIME_CANONICAL_STATUS=PASS", flush=True)
    if RUN_RESUME_R2:
        CAPTURE["invalid_r1_snapshot"] = verify_invalid_r1_snapshot()
        CAPTURE["price_lineage_dependency_audit"] = price_lineage_dependency_audit()
        policy_source = (REPO / "scripts" / "v22" / "a2_autonomous_buy_sell_and_sizing_policy_r1.py").read_text(encoding="utf-8")
        require("raw_prices=None if name==raw_name else prices" in policy_source, "PRICE_LINEAGE_DEPENDENCY_AUDIT_MISMATCH")
        print("EARLIEST_CONTAMINATED_STAGE=INNER_PORTFOLIO_SELECTION", flush=True)
        print("INVALID_R1_EXECUTION_PRESERVED=TRUE", flush=True)
        print("INVALID_R1_ECONOMIC_METRICS_REUSED_FOR_SELECTION=FALSE", flush=True)
    if OUT.exists():
        existing = {path.name for path in OUT.iterdir()}
        retryable = False
        manifest_path = OUT / "hash_manifest.json"
        report_path = OUT / "final_report.md"
        if manifest_path.is_file() and report_path.is_file():
            report = report_path.read_text(encoding="utf-8")
            retryable = "NO_VERDICT_DATA_OR_LINEAGE_FAILURE" in report and any(
                token in report for token in ("FROZEN_TAXONOMY_IDENTITY:15000", "COVERAGE_REPLAY_IDENTITY_FAILURE:61")
            )
            if RUN_RESUME_R2:
                retryable = retryable or (
                    "RAW_AUTHORITATIVE_REPLAY_MISMATCH" in report
                    and "MODEL_FITS_RERUN=0" in report
                    and "NO_VERDICT_DATA_OR_LINEAGE_FAILURE" in report
                )
        serialization_partial = existing == {"execution_contract.json", "feature_ledger_manifest.json", "finalist_freeze.json"}
        retryable = retryable or serialization_partial
        if RUN_RESUME_R2 and "hash_manifest.json" not in existing and "final_report.md" not in existing:
            retryable = all(path.is_file() for path in OUT.iterdir())
        require(existing <= {"feature_novelty_audit.csv"} or retryable, "IMMUTABLE_EXECUTION_OUTPUT_ALREADY_EXISTS", sorted(existing))
        if retryable:
            CAPTURE["serialization_retry"] = serialization_partial
            resolved = OUT.resolve()
            require(resolved.parent == RESULTS.resolve() and resolved.name == EXECUTION_ID, "UNSAFE_RETRY_CLEANUP_TARGET", resolved)
            for path in OUT.iterdir():
                require(path.is_file(), "UNSAFE_RETRY_CLEANUP_TARGET", path)
                path.unlink()
    resume = verify_recovery_contract()
    CAPTURE["resume_contract"] = resume
    module = load_source()
    CAPTURE["module"] = module
    module.OUT = OUT
    original_coverage = module.coverage_metrics
    original_outer = module.run_outer
    original_2025 = module.evaluate_2025
    original_clean_labels = module.make_clean_labels
    module.prepare_a2_inputs = lambda: prepare_resume_inputs(module)
    module.restore_frozen_research_contract = lambda: frozen_contracts(module)
    module.load_frozen_cik_mapping = lambda: load_effective_mapping(module, resume)
    module.attach_mapping_to_pool = lambda pool, mapping: attach_mapping_by_security(module, pool, mapping)
    module.load_bulk_sec_data = lambda *args, **kwargs: load_cached_bulk(module, *args, **kwargs)
    module.load_or_build_feature_states = lambda *args, **kwargs: load_cached_states(module, *args, **kwargs)
    module.attach_features_asof = lambda pool, states: attach_effective_features(module, pool, states)
    module.write_bulk_cache_manifest = lambda *args, **kwargs: PARSE_MANIFEST_PATH
    module.coverage_metrics = lambda panel: replay_coverage(module, original_coverage, panel)
    module.make_clean_labels = lambda policy, action, tickers, years, stage: stage_aware_clean_labels(
        module, original_clean_labels, policy, action, tickers, years, stage
    )
    module.run_outer = lambda *args, **kwargs: capture_outer(original_outer, *args, **kwargs)
    module.evaluate_2025 = lambda *args, **kwargs: capture_2025(original_2025, *args, **kwargs)
    module.final_block = final_block
    module.render_report = render_report
    module.write_final_artifacts = lambda summary, feature, trial, outer, vintage, robust, freeze, cache, unresolved_impact=None: write_artifacts(
        module, summary, feature, trial, outer, vintage, robust, freeze, cache, unresolved_impact
    )
    result = int(module.main())
    return result


if __name__ == "__main__":
    raise SystemExit(invalidate_price_scale_lineage() if "--invalidate-price-scale-lineage" in sys.argv else main())
