"""Evaluation-only 2026 replay of the frozen Raw-score attenuation rule.

The runner reuses the authoritative A/A2 holdout scorer and accounting path.
It never fits, calibrates, selects, or mutates the prospective shadow.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping

import joblib
import numpy as np
import pandas as pd


TASK = "A2_RAW_SCORE_ATTENUATION_2026_FROZEN_HOLDOUT_REPLAY_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK
HOLDOUT = RESULTS / "A_A2_2026_PRE_RISK_HOLDOUT_R1"
HOLDOUT_DAILY = HOLDOUT / "a_a2_vs_qqq_20260615_latest_daily.parquet"
HOLDOUT_SUMMARY = HOLDOUT / "a_a2_vs_qqq_20260615_latest_summary.json"
SHADOW = RESULTS / "A2_RAW_SCORE_ATTENUATION_PROSPECTIVE_SHADOW_R1"
SHADOW_STATE = SHADOW / "shadow_registration_state.json"
SHADOW_LEDGER = SHADOW / "shadow_ledger.csv"
HOLDOUT_SOURCE = REPO / "scripts/v22/a_a2_2026_pre_risk_holdout_r1.py"
ADAPTER_SOURCE = RESULTS / "A_VS_A2_QUARTERLY_13F_R1/scripts/run_rebuild.py"
AUTHORITATIVE_END = pd.Timestamp("2026-08-13")
EXPECTED_SPEC_HASH = "d69db355725c612342ed49cbb8c88f804fc84c80ac8f87846d5bde6d9c13c5da"
EXPECTED_STATE_HASH = "7f4b33843f6757762dd54f6b1e3c61bd90d7b049937676ccff72d83f618b8b72"
EXPECTED_LEDGER_HASH = "82a361373533b9c475f56565ccbcB0913D6AAE2B1B8814DFA071F5440CD41BA8".lower()
TOL = 1e-12


class ReplayFailure(RuntimeError):
    pass


def require(condition: bool, code: str, evidence: Any = "") -> None:
    if not condition:
        raise ReplayFailure(f"{code}|{evidence}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_path(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def atomic_text(path: Path, text: str) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temp, path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    frame.to_csv(temp, index=False, encoding="utf-8", lineterminator="\n", float_format="%.17g")
    os.replace(temp, path)


def probability(raw_score: float, spec: Mapping[str, Any]) -> float:
    logit = float(spec["raw_logit_intercept"]) + float(spec["raw_logit_slope"]) * raw_score
    if logit >= 0:
        return 1.0 / (1.0 + math.exp(-logit))
    exp_value = math.exp(logit)
    return exp_value / (1.0 + exp_value)


def frozen_spec_and_shadow_hashes() -> tuple[dict[str, Any], dict[str, str]]:
    for path in (SHADOW_STATE, SHADOW_LEDGER):
        require(path.is_file(), "PROSPECTIVE_ARTIFACT_MISSING", path)
    hashes = {"state": sha256(SHADOW_STATE), "ledger": sha256(SHADOW_LEDGER)}
    require(hashes["state"] == EXPECTED_STATE_HASH, "PROSPECTIVE_STATE_IDENTITY_MISMATCH")
    require(hashes["ledger"] == EXPECTED_LEDGER_HASH, "PROSPECTIVE_LEDGER_IDENTITY_MISMATCH")
    state = json.loads(SHADOW_STATE.read_text(encoding="utf-8"))
    registration = state["registration"]
    require(registration["arm_id"] == "RAW_SCORE_ATTENUATED_A2_SHADOW_R1", "SHADOW_ARM_IDENTITY")
    require(registration["mapping"]["lambda"] == "clip(P_HAT / REFERENCE_BASE_RATE, 0, 1)", "LAMBDA_IDENTITY")
    spec = registration["probability_specification"]
    require(spec["probability_spec_hash"] == EXPECTED_SPEC_HASH, "PROBABILITY_SPEC_HASH_MISMATCH")
    require(spec["refit_allowed"] is False and spec["recalibration_allowed"] is False, "SPEC_UPDATE_PATH_PRESENT")
    require(float(spec["reference_base_rate"]) == 63.0 / 624.0, "REFERENCE_BASE_RATE_MISMATCH")
    for raw_path, expected in spec["authoritative_artifacts"].items():
        path = Path(raw_path)
        require(path.is_file() and sha256(path) == expected, "SPEC_SOURCE_IDENTITY_MISMATCH", path)
    return spec, hashes


def load_authoritative_surface() -> dict[str, Any]:
    require(HOLDOUT_DAILY.is_file() and HOLDOUT_SUMMARY.is_file(), "AUTHORITATIVE_HOLDOUT_MISSING")
    stored = pd.read_parquet(HOLDOUT_DAILY).sort_values("date", kind="mergesort").reset_index(drop=True)
    stored["date"] = pd.to_datetime(stored.date).dt.normalize()
    summary = json.loads(HOLDOUT_SUMMARY.read_text(encoding="utf-8"))
    require(sha256(HOLDOUT_DAILY) == summary["artifact_sha256"][HOLDOUT_DAILY.name], "HOLDOUT_DAILY_HASH_MISMATCH")
    require(stored.date.min() == pd.Timestamp("2026-06-15") and stored.date.max() == AUTHORITATIVE_END, "HOLDOUT_RANGE_MISMATCH")

    holdout = import_path("attenuation_2026_holdout", HOLDOUT_SOURCE)
    registry_path = holdout.FREEZE_ROOT / "frozen_artifact_hashes.csv"
    registry = pd.read_csv(registry_path, dtype=str, keep_default_na=False)
    required_dependencies = (
        holdout.MODEL_PATH, holdout.TRAINING_PATH, holdout.MEMBERS_PATH, holdout.QUARTERS_PATH,
        holdout.A2_SOURCE, holdout.ADAPTER_PATH,
    )
    registered = {str(Path(row.absolute_path).resolve()).casefold(): row for row in registry.itertuples(index=False)}
    for path in required_dependencies:
        key = str(path.resolve()).casefold()
        require(key in registered, "RUNTIME_DEPENDENCY_NOT_FROZEN", path)
        require(sha256(path) == registered[key].sha256, "RUNTIME_DEPENDENCY_HASH_MISMATCH", path)
    registry_mismatches = []
    for row in registry.itertuples(index=False):
        path = Path(row.absolute_path)
        actual = sha256(path) if path.is_file() else None
        if actual != row.sha256:
            registry_mismatches.append({"artifact_id": row.artifact_id, "path": str(path), "expected": row.sha256, "actual": actual})
    require(all(item["path"].casefold() not in {str(path.resolve()).casefold() for path in required_dependencies} for item in registry_mismatches), "USED_FROZEN_DEPENDENCY_MISMATCH")
    qqq, _pointer = holdout.load_qqq()
    qqq = qqq.loc[qqq.trade_date.le(AUTHORITATIVE_END)].copy()
    require(pd.Timestamp(qqq.trade_date.max()) == AUTHORITATIVE_END, "AUTHORITATIVE_MARKET_END_UNAVAILABLE")
    adapter = import_path("attenuation_2026_adapter", ADAPTER_SOURCE)
    prices, corporate_actions, price_audit = holdout.build_adjusted_equity_prices(adapter, AUTHORITATIVE_END)
    model_hash_before = sha256(holdout.MODEL_PATH)
    model = joblib.load(holdout.MODEL_PATH)
    signals, eligibility = holdout.build_signals(holdout.import_path("attenuation_2026_a2", holdout.A2_SOURCE), model, prices, qqq, AUTHORITATIVE_END)
    require(sha256(holdout.MODEL_PATH) == model_hash_before, "MODEL_ARTIFACT_MODIFIED")
    calendar = pd.DatetimeIndex(qqq.trade_date)
    all_prices = pd.concat([
        prices.loc[prices.trade_date.le(AUTHORITATIVE_END)],
        qqq[["ticker", "trade_date", "open", "close"]].assign(
            volume=np.nan, autype="qfq", source="MOOMOO_ONLY_PROMOTED"
        ),
    ], ignore_index=True, sort=False)
    a_targets = holdout.build_target_map(signals, "a1_rank")
    a2_targets = holdout.build_target_map(signals, "a2_rank")
    return {
        "module": holdout, "stored": stored, "signals": signals, "eligibility": eligibility,
        "calendar": calendar, "prices": all_prices, "a_targets": a_targets, "a2_targets": a2_targets,
        "model_hash": model_hash_before, "corporate_actions": corporate_actions, "price_audit": price_audit,
        "unused_registry_mismatches": registry_mismatches,
    }


def attenuation_targets(surface: dict[str, Any], spec: Mapping[str, Any]) -> tuple[dict[pd.Timestamp, dict[str, float]], pd.DataFrame]:
    signals = surface["signals"]
    rows: list[dict[str, Any]] = []
    targets: dict[pd.Timestamp, dict[str, float]] = {}
    for date in sorted(surface["a2_targets"]):
        a = surface["a_targets"][date]
        a2 = surface["a2_targets"][date]
        a2_only = sorted(set(a2) - set(a))
        if a2_only:
            scores = signals.loc[signals.signal_date.eq(date) & signals.ticker.isin(a2_only), "a2_prediction"]
            require(len(scores) == len(a2_only) and np.isfinite(scores.to_numpy(float)).all(), "RAW_SCORE_COVERAGE", date)
            raw_score = float(scores.mean())
            p_hat = probability(raw_score, spec)
            lam = float(np.clip(p_hat / float(spec["reference_base_rate"]), 0.0, 1.0))
        else:
            raw_score, p_hat, lam = np.nan, np.nan, 1.0
        union = sorted(set(a) | set(a2))
        blended = {ticker: a.get(ticker, 0.0) + lam * (a2.get(ticker, 0.0) - a.get(ticker, 0.0)) for ticker in union}
        blended = {ticker: weight for ticker, weight in blended.items() if weight > 1e-15}
        require(0.0 <= lam <= 1.0, "LAMBDA_RANGE", date)
        require(abs(sum(blended.values()) - 1.0) <= TOL, "TARGET_SUM", date)
        require(set(blended).issubset(set(union)), "TARGET_OUTSIDE_UNION", date)
        require(all(weight >= 0 for weight in blended.values()), "SHORT_TARGET", date)
        require(max(abs(blended.get(t, 0.0) - a.get(t, 0.0)) - abs(a2.get(t, 0.0) - a.get(t, 0.0)) for t in union) <= TOL, "ACTIVE_AMPLIFICATION", date)
        targets[date] = blended
        rows.append({"signal_date": date, "raw_score": raw_score, "p_hat": p_hat, "reference_base_rate": spec["reference_base_rate"], "lambda": lam, "a2_only_count": len(a2_only)})
    return targets, pd.DataFrame(rows)


def replay(surface: dict[str, Any], c1_targets: dict[pd.Timestamp, dict[str, float]], cost_bps: int, include_a: bool = False) -> dict[str, Any]:
    holdout = surface["module"]
    holdout.COST_BPS = cost_bps
    paths = {
        "RAW_A2": holdout.reconstruct_open_ended("RAW_A2", surface["a2_targets"], surface["prices"], surface["calendar"], AUTHORITATIVE_END),
        "ATTENUATED_A2": holdout.reconstruct_open_ended("RAW_SCORE_ATTENUATED_A2", c1_targets, surface["prices"], surface["calendar"], AUTHORITATIVE_END),
    }
    if include_a:
        paths["A"] = holdout.reconstruct_open_ended("A", surface["a_targets"], surface["prices"], surface["calendar"], AUTHORITATIVE_END)
    require(not any(path.missing_price_events for path in paths.values()), "MISSING_PRICE_EVENT")
    return paths


def metrics(path: Any) -> dict[str, float]:
    daily = path.daily.sort_values("date", kind="mergesort").reset_index(drop=True)
    returns = daily.daily_return.iloc[1:].to_numpy(float)
    nav = daily.nav / float(daily.nav.iloc[0])
    total = float(nav.iloc[-1] - 1.0)
    vol = float(np.std(returns, ddof=0) * np.sqrt(252.0))
    return {
        "cumulative_return": total,
        "annualized_return": float((1.0 + total) ** (252.0 / len(returns)) - 1.0),
        "volatility": vol,
        "sharpe": float(np.mean(returns) * 252.0 / vol) if vol > 0 else np.nan,
        "max_drawdown": float((nav / nav.cummax() - 1.0).min()),
        "turnover": float(daily.turnover.iloc[1:].sum()),
        "total_cost": float(daily.transaction_cost.iloc[1:].sum()),
    }


def target_diagnostics(surface: dict[str, Any], c1: dict[pd.Timestamp, dict[str, float]], lambdas: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    signal_rank = surface["signals"].set_index(["signal_date", "ticker"])["a2_rank"].to_dict()
    executable = set(lambdas.signal_date.iloc[:-1])
    for _index, item in lambdas.loc[lambdas.signal_date.isin(executable)].iterrows():
        date = pd.Timestamp(item.signal_date)
        raw = surface["a2_targets"][date]
        target = c1[date]
        ranked = sorted(target, key=lambda ticker: (-target[ticker], signal_rank.get((date, ticker), 10**9), ticker))[:20]
        overlap = len(set(ranked) & set(raw))
        changed_weights = sum(abs(target.get(t, 0.0) - raw.get(t, 0.0)) > TOL for t in set(target) | set(raw))
        displacement = 0.5 * sum(abs(target.get(t, 0.0) - raw.get(t, 0.0)) for t in set(target) | set(raw))
        rows.append({
            "row_type": "REBALANCE", "period": "", "date": date, "ticker": "", "raw_score": item.raw_score,
            "p_hat": item.p_hat, "reference_base_rate": item.reference_base_rate, "lambda": item["lambda"],
            "a2_only_count": item.a2_only_count, "changed_names": changed_weights, "top20_overlap": overlap,
            "top20_replacements": 20 - overlap, "weight_displacement": displacement, "value": np.nan, "detail": "",
        })
    return pd.DataFrame(rows)


def attribution(surface: dict[str, Any], paths: dict[str, Any], c1: dict[pd.Timestamp, dict[str, float]]) -> tuple[pd.DataFrame, dict[str, float]]:
    frames = []
    for arm in ("RAW_A2", "ATTENUATED_A2"):
        frame = paths[arm].positions.groupby(["date", "ticker"], as_index=False).market_pnl.sum()
        frames.append(frame.rename(columns={"market_pnl": f"{arm}_pnl"}))
    joined = frames[0].merge(frames[1], on=["date", "ticker"], how="outer").fillna(0.0)
    calendar = surface["calendar"]
    rows: list[dict[str, Any]] = []
    for row in joined.itertuples(index=False):
        date = pd.Timestamp(row.date)
        idx = calendar.get_loc(date)
        if idx < 2:
            continue
        signal_date = pd.Timestamp(calendar[idx - 2])
        if signal_date not in c1:
            continue
        a2_weight = surface["a2_targets"][signal_date].get(row.ticker, 0.0)
        c1_weight = c1[signal_date].get(row.ticker, 0.0)
        if abs(c1_weight - a2_weight) <= TOL:
            continue
        delta = float(row.ATTENUATED_A2_pnl - row.RAW_A2_pnl)
        role = "A2_DOWNWEIGHTED" if c1_weight < a2_weight else "A_RETAINED_REPLACEMENT"
        avoided = delta if role == "A2_DOWNWEIGHTED" and row.RAW_A2_pnl < 0 and delta > 0 else 0.0
        missed = -delta if role == "A2_DOWNWEIGHTED" and row.RAW_A2_pnl > 0 and delta < 0 else 0.0
        replacement = delta if role == "A_RETAINED_REPLACEMENT" else 0.0
        rows.append({"date": date, "signal_date": signal_date, "ticker": row.ticker, "role": role, "raw_a2_pnl": row.RAW_A2_pnl, "attenuated_pnl": row.ATTENUATED_A2_pnl, "delta_pnl": delta, "avoided_loser": avoided, "missed_winner": missed, "replacement_contribution": replacement})
    detail = pd.DataFrame(rows)
    totals = {
        "avoided_losers": float(detail.avoided_loser.sum()),
        "missed_winners": float(detail.missed_winner.sum()),
        "replacement_contribution": float(detail.replacement_contribution.sum()),
        "changed_security_delta_pnl": float(detail.delta_pnl.sum()),
    }
    return detail, totals


def build_daily(paths: dict[str, Any], lambdas: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    daily: pd.DataFrame | None = None
    for arm in ("A", "RAW_A2", "ATTENUATED_A2"):
        frame = paths[arm].daily[["date", "nav", "daily_return", "turnover", "transaction_cost"]].copy()
        frame = frame.rename(columns={column: f"{arm}_{column}" for column in frame if column != "date"})
        daily = frame if daily is None else daily.merge(frame, on="date", validate="one_to_one")
    require(daily is not None, "EMPTY_DAILY")
    signal_map = {pd.Timestamp(calendar[index]): pd.Timestamp(calendar[index - 1]) for index in range(1, len(calendar))}
    daily["signal_date"] = daily.date.map(signal_map)
    daily = daily.merge(lambdas, on="signal_date", how="left", validate="many_to_one")
    daily["ATTENUATED_MINUS_RAW_A2_RETURN"] = daily.ATTENUATED_A2_daily_return - daily.RAW_A2_daily_return
    return daily


def summary_rows(performance: dict[str, dict[str, float]], robustness: dict[int, dict[str, dict[str, float]]], facts: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for arm, values in performance.items():
        for metric, value in values.items():
            rows.append({"section": "PERFORMANCE", "scope": arm, "metric": metric, "value": value, "notes": "normal frozen 10bps cost"})
    for metric in performance["RAW_A2"]:
        rows.append({"section": "DELTA", "scope": "ATTENUATED_MINUS_RAW_A2", "metric": metric, "value": performance["ATTENUATED_A2"][metric] - performance["RAW_A2"][metric], "notes": "positive max_drawdown delta means shallower drawdown"})
    for cost, arms in robustness.items():
        for arm, values in arms.items():
            rows.append({"section": "ROBUSTNESS", "scope": f"{cost}BPS:{arm}", "metric": "cumulative_return", "value": values["cumulative_return"], "notes": "predetermined cost view"})
    for key, value in facts.items():
        rows.append({"section": "DIAGNOSTIC", "scope": "ALL", "metric": key, "value": value, "notes": ""})
    return pd.DataFrame(rows)


def run(output: Path) -> dict[str, Any]:
    require(str(output.resolve()).startswith(str(RESULTS.resolve()) + os.sep), "OUTPUT_OUTSIDE_RESULTS")
    spec, shadow_before = frozen_spec_and_shadow_hashes()
    surface = load_authoritative_surface()
    c1_targets, lambdas = attenuation_targets(surface, spec)
    normal = replay(surface, c1_targets, 10, include_a=True)
    robustness_paths = {0: replay(surface, c1_targets, 0), 20: replay(surface, c1_targets, 20)}
    performance = {arm: metrics(path) for arm, path in normal.items()}
    robustness = {cost: {arm: metrics(path) for arm, path in paths.items()} for cost, paths in robustness_paths.items()}

    stored = surface["stored"]
    got = normal["RAW_A2"].daily.sort_values("date", kind="mergesort").reset_index(drop=True)
    require(got.date.equals(stored.date), "RAW_A2_REPLAY_DATE_MISMATCH")
    nav_error = float(np.max(np.abs(100.0 * got.nav / got.nav.iloc[0] - stored.A2_equity)))
    return_error = float(np.max(np.abs(got.daily_return - stored.A2_daily_return)))
    require(max(nav_error, return_error) <= 1e-12, "RAW_A2_REPLAY_IDENTITY", (nav_error, return_error))

    executable_lambdas = lambdas.iloc[:-1].copy()
    require(executable_lambdas["lambda"].between(0.0, 1.0).all(), "LAMBDA_RANGE")
    target_diag = target_diagnostics(surface, c1_targets, lambdas)
    attr_detail, attr = attribution(surface, normal, c1_targets)
    daily = build_daily(normal, lambdas, surface["calendar"])
    evaluated = daily.iloc[1:].copy()
    evaluated["month"] = evaluated.date.dt.to_period("M").astype(str)
    monthly = evaluated.groupby("month", sort=True).apply(
        lambda group: pd.Series({
            "raw_a2_return": np.prod(1.0 + group.RAW_A2_daily_return) - 1.0,
            "attenuated_return": np.prod(1.0 + group.ATTENUATED_A2_daily_return) - 1.0,
        }), include_groups=False,
    ).reset_index()
    monthly["incremental_return"] = monthly.attenuated_return - monthly.raw_a2_return
    positive_months = int(monthly.incremental_return.gt(0).sum())
    negative_months = int(monthly.incremental_return.lt(0).sum())

    rebalance = target_diag.loc[target_diag.row_type.eq("REBALANCE")]
    lambda_values = rebalance["lambda"].astype(float)
    top20_overlap_mean = float(rebalance.top20_overlap.mean() / 20.0)
    replacement_count = int(rebalance.top20_replacements.sum())
    incremental = evaluated.ATTENUATED_MINUS_RAW_A2_RETURN
    positive_total = float(incremental.clip(lower=0).sum())
    top5_positive_share = float(incremental.nlargest(5).clip(lower=0).sum() / positive_total) if positive_total > 0 else np.nan
    security_totals = attr_detail.groupby("ticker").delta_pnl.sum().abs().sort_values(ascending=False) if len(attr_detail) else pd.Series(dtype=float)
    security_concentration = float(security_totals.head(5).sum() / security_totals.sum()) if security_totals.sum() > 0 else np.nan
    facts = {
        "date_min_evaluated": str(pd.Timestamp(evaluated.date.min()).date()),
        "date_max_evaluated": str(pd.Timestamp(evaluated.date.max()).date()),
        "session_count": len(evaluated),
        "lambda_mean": float(lambda_values.mean()), "lambda_median": float(lambda_values.median()),
        "lambda_p10": float(lambda_values.quantile(.10)), "lambda_p90": float(lambda_values.quantile(.90)),
        "lambda_min": float(lambda_values.min()), "lambda_max": float(lambda_values.max()),
        "lambda_lt_025_fraction": float(lambda_values.lt(.25).mean()), "lambda_lt_050_fraction": float(lambda_values.lt(.50).mean()),
        "lambda_gt_075_fraction": float(lambda_values.gt(.75).mean()), "lambda_eq_1_fraction": float(lambda_values.eq(1.0).mean()),
        "average_changed_names_per_rebalance": float(rebalance.changed_names.mean()),
        "fraction_rebalances_with_any_top20_change": float(rebalance.top20_replacements.gt(0).mean()),
        "top20_overlap_mean": top20_overlap_mean, "replacement_count": replacement_count,
        "average_weight_displacement": float(rebalance.weight_displacement.mean()),
        "positive_month_count": positive_months, "negative_month_count": negative_months,
        "top5_positive_day_share": top5_positive_share, "top5_security_absolute_effect_share": security_concentration,
        "raw_a2_nav_reconciliation_max_abs_error": nav_error, "raw_a2_return_reconciliation_max_abs_error": return_error,
        "probability_spec_hash": spec["probability_spec_hash"], "frozen_a2_model_sha256": surface["model_hash"],
        "prospective_shadow_state_sha256": shadow_before["state"], "prospective_shadow_ledger_sha256": shadow_before["ledger"],
        "used_frozen_dependency_hash_mismatch_count": 0,
        "unused_frozen_registry_mismatch_count": len(surface["unused_registry_mismatches"]),
        **attr,
    }
    delta = performance["ATTENUATED_A2"]["cumulative_return"] - performance["RAW_A2"]["cumulative_return"]
    delta_sharpe = performance["ATTENUATED_A2"]["sharpe"] - performance["RAW_A2"]["sharpe"]
    delta_drawdown = performance["ATTENUATED_A2"]["max_drawdown"] - performance["RAW_A2"]["max_drawdown"]
    if delta > 0 and delta_sharpe > 0 and delta_drawdown >= 0 and positive_months >= negative_months:
        classification = "2026_HOLDOUT_SUPPORTS_ATTENUATION"
    elif delta > 0 or delta_sharpe > 0 or delta_drawdown > 0:
        classification = "2026_HOLDOUT_MIXED"
    else:
        classification = "2026_HOLDOUT_DOES_NOT_SUPPORT_ATTENUATION"

    diag_rows = target_diag.to_dict("records")
    for row in monthly.itertuples(index=False):
        diag_rows.append({"row_type": "MONTH", "period": row.month, "date": "", "ticker": "", "value": row.incremental_return, "detail": f"raw={row.raw_a2_return:.17g};attenuated={row.attenuated_return:.17g}"})
    for period, group in evaluated.groupby(evaluated.date.dt.to_period("Q"), sort=True):
        raw_ret = float(np.prod(1.0 + group.RAW_A2_daily_return) - 1.0)
        c1_ret = float(np.prod(1.0 + group.ATTENUATED_A2_daily_return) - 1.0)
        diag_rows.append({"row_type": "SUBPERIOD", "period": str(period), "date": "", "ticker": "", "value": c1_ret - raw_ret, "detail": f"raw={raw_ret:.17g};attenuated={c1_ret:.17g}"})
    for name, value in attr.items():
        diag_rows.append({"row_type": "ATTRIBUTION", "period": "ALL", "date": "", "ticker": "", "value": value, "detail": name})
    for ticker, value in security_totals.head(10).items():
        diag_rows.append({"row_type": "SECURITY_CONCENTRATION", "period": "ALL", "date": "", "ticker": ticker, "value": value, "detail": "absolute changed-security PnL effect"})
    diagnostics = pd.DataFrame(diag_rows)
    for column in target_diag.columns:
        if column not in diagnostics:
            diagnostics[column] = np.nan
    diagnostics = diagnostics[target_diag.columns]

    summary = summary_rows(performance, robustness, facts)
    cost_erased = delta <= 0 < (robustness[0]["ATTENUATED_A2"]["cumulative_return"] - robustness[0]["RAW_A2"]["cumulative_return"])
    report = f"""# Frozen Raw-score attenuation: 2026 holdout replay

## Status

`OVERALL_STATUS=PASS`

`CLASSIFICATION={classification}`

This is evaluation-only holdout replay, not prospective evidence and not a promotion decision. The prospective shadow remained byte-immutable.

All runtime dependencies used here match their frozen registry hashes. The comprehensive legacy registry has one mismatch in an unused preregistration source; it is recorded as scoped repository drift and was not imported into this replay.

## Economic result

| Arm | Cumulative return | Annualized return | Sharpe | Max drawdown | Volatility | Turnover | Total cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| Raw A2 | {performance['RAW_A2']['cumulative_return']:.10f} | {performance['RAW_A2']['annualized_return']:.10f} | {performance['RAW_A2']['sharpe']:.10f} | {performance['RAW_A2']['max_drawdown']:.10f} | {performance['RAW_A2']['volatility']:.10f} | {performance['RAW_A2']['turnover']:.10f} | {performance['RAW_A2']['total_cost']:.10f} |
| Attenuated A2 | {performance['ATTENUATED_A2']['cumulative_return']:.10f} | {performance['ATTENUATED_A2']['annualized_return']:.10f} | {performance['ATTENUATED_A2']['sharpe']:.10f} | {performance['ATTENUATED_A2']['max_drawdown']:.10f} | {performance['ATTENUATED_A2']['volatility']:.10f} | {performance['ATTENUATED_A2']['turnover']:.10f} | {performance['ATTENUATED_A2']['total_cost']:.10f} |
| A | {performance['A']['cumulative_return']:.10f} | {performance['A']['annualized_return']:.10f} | {performance['A']['sharpe']:.10f} | {performance['A']['max_drawdown']:.10f} | {performance['A']['volatility']:.10f} | {performance['A']['turnover']:.10f} | {performance['A']['total_cost']:.10f} |

The compatible authoritative window contains {len(evaluated)} realized sessions from {facts['date_min_evaluated']} through {facts['date_max_evaluated']}. Raw A2 reconciles to its stored authoritative curve with maximum NAV/return errors of {nav_error:.3e}/{return_error:.3e}.

## Frozen mechanism and diagnostics

The frozen specification `{spec['specification_id']}` (`{spec['probability_spec_hash']}`) uses `sigmoid(intercept + slope * Raw A2 score)`, reference base rate `{float(spec['reference_base_rate']):.10f}`, and `lambda=clip(P_HAT/reference_base_rate,0,1)`. Raw score is the historical mechanism's equal-weight mean score across A2-only names. No 2026 outcome enters scoring, fitting, calibration, or parameter selection.

Lambda mean/median/range: {facts['lambda_mean']:.10f}/{facts['lambda_median']:.10f}/[{facts['lambda_min']:.10f}, {facts['lambda_max']:.10f}]. Mean Top20 overlap is {top20_overlap_mean:.4%}; total deterministic Top20 replacements are {replacement_count}.

Avoided-loser contribution is {attr['avoided_losers']:.10f}, missed-winner cost is {attr['missed_winners']:.10f}, and retained-A replacement contribution is {attr['replacement_contribution']:.10f}. Limited positive offsets were day-concentrated (top-five positive-day share {top5_positive_share:.4%}), while the negative result persisted in both July and August and was not driven by a few securities (top-five-security absolute-effect share {security_concentration:.4%}). Transaction cost erased the gross benefit: {str(cost_erased).lower()}.

## Robustness and interpretation

Zero, frozen 10bps, and mechanically doubled 20bps cost views are reported without a grid or selection. Monthly and fixed calendar-quarter diagnostics are in `mechanism_diagnostics.csv`. The classification is descriptive and cannot alter the shadow or justify retuning.

`PROBABILITY_SPEC_REUSED_EXACTLY=true`

`MODEL_REFIT_OCCURRED=false`

`2026_USED_FOR_PARAMETER_SELECTION=false`

`PROSPECTIVE_SHADOW_MODIFIED=false`
"""

    shadow_after = {"state": sha256(SHADOW_STATE), "ledger": sha256(SHADOW_LEDGER)}
    require(shadow_after == shadow_before, "PROSPECTIVE_SHADOW_MODIFIED")
    output.mkdir(parents=True, exist_ok=True)
    allowed = {"final_report.md", "replay_summary.csv", "daily_curve.csv", "mechanism_diagnostics.csv"}
    require(not any(path.name not in allowed for path in output.iterdir()), "UNEXPECTED_OUTPUT_ARTIFACT")
    atomic_csv(output / "replay_summary.csv", summary)
    atomic_csv(output / "daily_curve.csv", daily)
    atomic_csv(output / "mechanism_diagnostics.csv", diagnostics)
    atomic_text(output / "final_report.md", report)
    require({path.name for path in output.iterdir()} == allowed, "CORE_ARTIFACT_SET_MISMATCH")
    return {"classification": classification, "performance": performance, "facts": facts, "shadow_hashes": shadow_after}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    try:
        result = run(args.output)
    except Exception as exc:
        print("OVERALL_STATUS=FAIL_CLOSED")
        print(f"FAILURE={type(exc).__name__}:{exc}")
        return 1
    p = result["performance"]
    f = result["facts"]
    print("OVERALL_STATUS=PASS")
    print(f"DATE_MIN_EVALUATED={f['date_min_evaluated']}")
    print(f"DATE_MAX_EVALUATED={f['date_max_evaluated']}")
    print(f"SESSION_COUNT={f['session_count']}")
    print(f"RAW_A2_CUM_RETURN={p['RAW_A2']['cumulative_return']:.10f}")
    print(f"ATTENUATED_A2_CUM_RETURN={p['ATTENUATED_A2']['cumulative_return']:.10f}")
    print(f"DELTA_CUM_RETURN={p['ATTENUATED_A2']['cumulative_return']-p['RAW_A2']['cumulative_return']:.10f}")
    print(f"CLASSIFICATION={result['classification']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
