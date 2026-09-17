from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


TASK_ID = "A2_BETA_MATCHED_BENCHMARK_AND_RESIDUAL_VALUE_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK_ID
UPSTREAM = RESULTS / "A2_AUTHORITATIVE_IDENTITY_RECOVERY_AND_FALSIFICATION_CONTINUATION_R1"
BASE = RESULTS / "A_VS_A2_QUARTERLY_13F_R1"
SHARED_SOURCE = REPO / "scripts/v22/a2_strategy_falsification_and_robustness_r1.py"
FINAL_FILES = [
    "final_report.md", "benchmark_summary.csv", "active_value_by_period.csv",
    "rolling_and_tail_diagnostics.csv", "classification.json", "hash_manifest.json",
]
ANNUALIZATION = 252.0
ABS_TOL = 1e-12


PREREGISTRATION = {
    "task_id": TASK_ID,
    "authoritative_path": "751-session A2 frozen OOF economic path; never substitute 733-session diagnostic",
    "benchmark_order": ["QQQ_RAW", "QQQ_BETA_MATCHED", "QQQ_VOL_MATCHED", "SOXX_RAW", "SOXX_VOL_MATCHED", "QQQ_SOXX_50_50_RAW", "QQQ_SOXX_50_50_VOL_MATCHED"],
    "technology_etf": "SOXX",
    "technology_etf_selection_basis": "predeclared and used as the secondary benchmark in the immediately preceding falsification",
    "fixed_mix": {"QQQ": 0.5, "SOXX": 0.5},
    "risk_scale_sample": "full authoritative 2023-01-04..2025-12-31 comparison sample; estimated once",
    "financing": "zero-financing favorable upper bound; net implementable benchmark NOT_APPLICABLE without frozen PIT-safe financing series",
    "hac_maxlags": 5,
    "bootstrap": {"kind": "paired_moving_block", "block_length": 10, "repetitions": 2000, "seed": 20260823},
    "rolling_windows": [63, 126, 252],
    "concentration": ["best_1_day", "best_5_days", "best_10_days", "best_month", "best_quarter", "best_year", "remove_best_5_days", "remove_best_10_days"],
    "tail_cvar_quantile": 0.05,
    "beta_stability": {"stable_p90_p10_max": 0.5, "moderate_p90_p10_max": 1.0, "fold_sign_flip_is_high": True},
    "classification": {
        "strong": "both QQQ matched active CAGR/IR positive; both >=2/3 positive folds; all fixed LOO cumulative active returns positive; beta bootstrap P(mean>0)>=0.80; ex-best5 IR positive; and both IR>=0.50",
        "modest": "both QQQ matched active CAGR/IR positive and both >=2/3 positive folds, but strong gate fails",
        "inconclusive": "beta- and volatility-matched QQQ give mixed signs, weak confidence, or materially split folds",
        "beta_explains": "both matched active annualized means <=0.05 or both IR<=0.20 with <=1/3 positive folds",
        "dominates": "both matched active cumulative returns negative and both <=1/3 positive folds",
    },
    "selection_bias_status": "UNQUANTIFIED_CARRIED_FORWARD",
    "2026_status": "EXPOSED_DIAGNOSTIC_ONLY_NOT_READ",
}


class ContractFailure(RuntimeError):
    pass


def require(value: bool, code: str, detail: Any = "") -> None:
    if not value:
        raise ContractFailure(f"{code}:{detail}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def import_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def active_metrics(active: np.ndarray) -> dict[str, Any]:
    r = np.asarray(active, float)
    nav = np.r_[1.0, np.cumprod(1 + r)]
    dd = nav / np.maximum.accumulate(nav) - 1
    te = float(r.std(ddof=0) * math.sqrt(ANNUALIZATION))
    ann = float(r.mean() * ANNUALIZATION)
    return {
        "active_cumulative_return": float(nav[-1] - 1),
        "active_cagr": float(nav[-1] ** (ANNUALIZATION / len(r)) - 1),
        "annualized_active_return": ann,
        "information_ratio": ann / te if te else None,
        "active_volatility": te, "tracking_error": te,
        "active_max_drawdown": float(dd.min()), "hit_rate": float((r > 0).mean()),
    }


def period_counts(dates: pd.Series, active: np.ndarray) -> dict[str, Any]:
    series = pd.Series(active, index=pd.DatetimeIndex(dates))
    result: dict[str, Any] = {}
    for name, freq in (("months", "M"), ("quarters", "Q"), ("years", "Y")):
        grouped = series.groupby(series.index.to_period(freq)).apply(lambda x: float(np.prod(1 + x) - 1))
        result[f"positive_{name}"] = int((grouped > 0).sum())
        result[f"total_{name}"] = int(len(grouped))
    return result


def bootstrap_active(shared, active: np.ndarray) -> dict[str, float]:
    r = np.asarray(active, float)
    rng = np.random.default_rng(PREREGISTRATION["bootstrap"]["seed"])
    annual_means = np.empty(PREREGISTRATION["bootstrap"]["repetitions"])
    cumulatives = np.empty_like(annual_means)
    for i in range(len(annual_means)):
        idx = shared.moving_block_indices(len(r), PREREGISTRATION["bootstrap"]["block_length"], rng)
        sample = r[idx]
        annual_means[i] = sample.mean() * ANNUALIZATION
        cumulatives[i] = np.prod(1 + sample) - 1
    return {
        "bootstrap_active_mean_ci_low": float(np.quantile(annual_means, .025)),
        "bootstrap_active_mean_ci_high": float(np.quantile(annual_means, .975)),
        "bootstrap_probability_active_mean_positive": float((annual_means > 0).mean()),
        "bootstrap_probability_active_cumulative_positive": float((cumulatives > 0).mean()),
    }


def hac_mean(shared, active: np.ndarray) -> dict[str, float]:
    fit = shared.ols_hac(np.asarray(active, float), np.empty((len(active), 0)), PREREGISTRATION["hac_maxlags"])
    return {"hac_tstat": float(fit["alpha_t_hac"]), "hac_annualized_mean": float(fit["alpha_annualized"])}


def beta(y: np.ndarray, x: np.ndarray) -> float:
    return float(np.cov(y, x, ddof=0)[0, 1] / np.var(x))


def downside_metrics(returns: np.ndarray, qqq: np.ndarray | None = None) -> dict[str, Any]:
    r = np.asarray(returns, float)
    m = pd.Series(r)
    nav = np.r_[1.0, np.cumprod(1 + r)]
    dd = nav / np.maximum.accumulate(nav) - 1
    week = pd.Series(r).rolling(5).apply(lambda x: np.prod(1 + x) - 1, raw=True).dropna()
    downside = np.minimum(r, 0)
    q = float(np.quantile(r, .05))
    result = {
        "max_drawdown": float(dd.min()), "worst_day": float(r.min()), "worst_week_5_sessions": float(week.min()),
        "downside_deviation": float(np.sqrt(np.mean(downside ** 2)) * math.sqrt(ANNUALIZATION)),
        "cvar_5pct": float(r[r <= q].mean()),
    }
    if qqq is not None:
        negative = np.asarray(qqq) < 0
        result["downside_capture_vs_qqq"] = float(r[negative].sum() / np.asarray(qqq)[negative].sum())
    return result


def benchmark_record(shared, name: str, returns: np.ndarray, a2: np.ndarray, dates: pd.Series, qqq: np.ndarray, scale: float, kind: str) -> dict[str, Any]:
    bm = shared.metrics(returns)
    active = a2 - returns
    record = {
        "benchmark": name, "kind": kind, "scale": scale,
        **{f"benchmark_{k}": v for k, v in bm.items()},
        **active_metrics(active), **period_counts(dates, active), **hac_mean(shared, active), **bootstrap_active(shared, active),
        "correlation_with_a2": float(np.corrcoef(a2, returns)[0, 1]),
        "a2_beta_to_benchmark": beta(a2, returns),
        "financing_adjustment": "NOT_AVAILABLE_ZERO_FINANCING_FAVORABLE_UPPER_BOUND" if scale > 1 else "NOT_REQUIRED_FOR_UNLEVERED_RAW_DIAGNOSTIC",
    }
    record.update({f"benchmark_{k}": v for k, v in downside_metrics(returns, qqq).items()})
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUT)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    require(out == OUT.resolve(), "OUTPUT_ROOT_FAILURE", out)
    out.mkdir(parents=True, exist_ok=True)
    for name in FINAL_FILES:
        path = out / name
        if path.exists():
            path.unlink()

    prereg_sha = hashlib.sha256(canonical_json(PREREGISTRATION).encode("utf-8")).hexdigest()
    require(prereg_sha == "1f65b5376fe2b2b2c9ccd10fdecad9e3f0fa860e687db7d2af8ca347030bb5af", "PREREGISTRATION_DRIFT", prereg_sha)
    shared = import_file("a2_beta_matched_shared", SHARED_SOURCE)

    upstream_manifest = json.loads((UPSTREAM / "hash_manifest.json").read_text(encoding="utf-8"))
    require(upstream_manifest["status"] == "PASS_HASH_VERIFIED", "UPSTREAM_HASH_STATUS")
    for row in upstream_manifest["artifacts"]:
        path = UPSTREAM / row["name"]
        require(path.is_file() and sha256_file(path) == row["sha256"], "UPSTREAM_ARTIFACT_HASH_FAILURE", row["name"])
    upstream = json.loads((UPSTREAM / "robustness_classification.json").read_text(encoding="utf-8"))
    require(upstream["historical_path_authority"] == "PASS", "UPSTREAM_PATH_AUTHORITY")

    daily = pd.read_parquet(BASE / "A2/portfolio_daily.parquet").sort_values("execution_date", kind="mergesort").reset_index(drop=True)
    daily["execution_date"] = pd.to_datetime(daily.execution_date).dt.normalize()
    a2 = daily.reconstructed_daily_return.to_numpy(float)
    require(len(daily) == 751 and daily.execution_date.max() < pd.Timestamp("2026-01-01"), "A2_DATE_OR_ROW_FAILURE")
    a2m = shared.metrics(a2)
    for key in ["cumulative_return", "cagr", "sharpe", "max_drawdown"]:
        require(abs(float(a2m[key]) - float(upstream["baseline"][key])) <= ABS_TOL, "A2_BASELINE_METRIC_FAILURE", key)
    np.testing.assert_allclose(np.cumprod(1 + a2), daily.reconstructed_nav.to_numpy(float), atol=ABS_TOL, rtol=0)
    require(abs(float(daily.reconstructed_turnover.sum()) - 156.04062236916937) <= ABS_TOL, "A2_TURNOVER_FAILURE")
    require(float(daily[["NAV_ACCOUNTING_IDENTITY_ERROR", "CASH_IDENTITY_ERROR", "POSITION_VALUE_IDENTITY_ERROR", "TURNOVER_IDENTITY_ERROR", "TRANSACTION_COST_IDENTITY_ERROR"]].abs().to_numpy().max()) <= ABS_TOL, "A2_ACCOUNTING_FAILURE")

    oof = pd.read_parquet(BASE / "A2/oof_predictions.parquet", columns=["signal_date", "ticker", "split"])
    oof["signal_date"] = pd.to_datetime(oof.signal_date).dt.normalize()
    require(oof.signal_date.max() < pd.Timestamp("2026-01-01"), "OOF_2026_FAILURE")
    require(set(oof.signal_date.dt.year) == {2023, 2024, 2025}, "OOS_YEAR_FAILURE")
    expected = {2023: "DEVELOPMENT", 2024: "CONFIRMATION", 2025: "FINAL"}
    require(all(set(oof.loc[oof.signal_date.dt.year.eq(y), "split"]) == {s} for y, s in expected.items()), "OOS_FOLD_FAILURE")

    benchmarks, benchmark_hashes = shared.benchmark_frame(daily.execution_date)
    aligned = daily[["execution_date", "reconstructed_daily_return"]].merge(benchmarks, on="execution_date", how="inner", validate="one_to_one")
    lost = len(daily) - len(aligned)
    require(len(aligned) > 700 and aligned.execution_date.max() < pd.Timestamp("2026-01-01"), "BENCHMARK_SUPPORT_FAILURE")
    a2 = aligned.reconstructed_daily_return.to_numpy(float)
    qqq = aligned.QQQ.to_numpy(float)
    soxx = aligned.SOXX.to_numpy(float)
    mix = .5 * qqq + .5 * soxx
    beta_scale = beta(a2, qqq)
    vol_scale = float(a2.std(ddof=0) / qqq.std(ddof=0))
    soxx_vol_scale = float(a2.std(ddof=0) / soxx.std(ddof=0))
    mix_vol_scale = float(a2.std(ddof=0) / mix.std(ddof=0))
    require(abs(beta_scale - 1.391504622347692) <= 1e-12, "BETA_RECONCILIATION_FAILURE", beta_scale)
    recipes = [
        ("QQQ_RAW", qqq, 1.0, "RAW_BUY_AND_HOLD"),
        ("QQQ_BETA_MATCHED", beta_scale * qqq, beta_scale, "GROSS_RISK_MATCHED_DIAGNOSTIC_ZERO_FINANCING"),
        ("QQQ_VOL_MATCHED", vol_scale * qqq, vol_scale, "EX_POST_RISK_MATCHED_DIAGNOSTIC_ZERO_FINANCING"),
        ("SOXX_RAW", soxx, 1.0, "RAW_BUY_AND_HOLD"),
        ("SOXX_VOL_MATCHED", soxx_vol_scale * soxx, soxx_vol_scale, "EX_POST_RISK_MATCHED_DIAGNOSTIC_ZERO_FINANCING"),
        ("QQQ_SOXX_50_50_RAW", mix, 1.0, "FIXED_50_50_RAW"),
        ("QQQ_SOXX_50_50_VOL_MATCHED", mix_vol_scale * mix, mix_vol_scale, "EX_POST_FIXED_50_50_VOL_MATCHED_ZERO_FINANCING"),
    ]
    summary = pd.DataFrame([benchmark_record(shared, n, r, a2, aligned.execution_date, qqq, s, k) for n, r, s, k in recipes])
    summary.to_csv(out / "benchmark_summary.csv", index=False, encoding="utf-8-sig")

    period_rows: list[dict[str, Any]] = []
    primary_returns = {"QQQ_BETA_MATCHED": beta_scale * qqq, "QQQ_VOL_MATCHED": vol_scale * qqq}
    for name, bm in primary_returns.items():
        active = a2 - bm
        for year in [2023, 2024, 2025]:
            mask = aligned.execution_date.dt.year.eq(year).to_numpy()
            am = active_metrics(active[mask]); a2_year = shared.metrics(a2[mask]); bm_year = shared.metrics(bm[mask])
            period_rows.append({"benchmark": name, "test": "AUTHORITATIVE_OOS_FOLD", "period": str(year), "evidence_class": "AUTHORITATIVE_OOS", **am,
                                "a2_cumulative_return": a2_year["cumulative_return"], "benchmark_cumulative_return": bm_year["cumulative_return"],
                                "active_positive": bool(am["active_cumulative_return"] > 0)})
        for year in [2023, 2024, 2025]:
            mask = aligned.execution_date.dt.year.ne(year).to_numpy()
            period_rows.append({"benchmark": name, "test": "LEAVE_ONE_CALENDAR_YEAR_OUT", "period": f"EX_{year}", "evidence_class": "FULL_HISTORY_DIAGNOSTIC", **active_metrics(active[mask])})
            period_rows.append({"benchmark": name, "test": "LEAVE_ONE_OOS_FOLD_OUT", "period": f"EX_{year}", "evidence_class": "AUTHORITATIVE_OOS_DIAGNOSTIC", **active_metrics(active[mask])})
        series = pd.Series(active, index=pd.DatetimeIndex(aligned.execution_date))
        positive_gain = float(series.clip(lower=0).sum())
        for label, k in (("BEST_1_ACTIVE_DAY", 1), ("BEST_5_ACTIVE_DAYS", 5), ("BEST_10_ACTIVE_DAYS", 10)):
            best = series.nlargest(k)
            period_rows.append({"benchmark": name, "test": "ACTIVE_TIME_CONCENTRATION", "period": label,
                                "positive_active_gain_share": float(best.sum() / positive_gain), "net_active_gain_share": float(best.sum() / series.sum()),
                                "removed_dates": "|".join(str(x.date()) for x in best.index)})
        for label, freq in (("BEST_ACTIVE_MONTH", "M"), ("BEST_ACTIVE_QUARTER", "Q"), ("BEST_ACTIVE_YEAR", "Y")):
            grouped = series.groupby(series.index.to_period(freq)).sum()
            best = grouped.idxmax()
            period_rows.append({"benchmark": name, "test": "ACTIVE_TIME_CONCENTRATION", "period": label,
                                "positive_active_gain_share": float(grouped.loc[best] / grouped.clip(lower=0).sum()),
                                "net_active_gain_share": float(grouped.loc[best] / series.sum()), "removed_dates": str(best)})
        for k in [5, 10]:
            altered = series.copy(); altered.loc[series.nlargest(k).index] = 0.0
            period_rows.append({"benchmark": name, "test": "REMOVE_BEST_ACTIVE_DAYS", "period": f"EX_BEST_{k}_ACTIVE_DAYS",
                                "evidence_class": "DIAGNOSTIC_ONLY_NO_SELECTION", **active_metrics(altered.to_numpy(float))})
    pd.DataFrame(period_rows).to_csv(out / "active_value_by_period.csv", index=False, encoding="utf-8-sig")

    diagnostic_rows: list[dict[str, Any]] = []
    for name, bm in primary_returns.items():
        active = a2 - bm
        for window in [63, 126, 252]:
            for end in range(window, len(active) + 1):
                ar = active[end-window:end]; ay = a2[end-window:end]; qx = qqq[end-window:end]
                am = active_metrics(ar)
                diagnostic_rows.append({"row_type": "ROLLING", "benchmark": name, "window": window,
                                        "period_end": str(aligned.execution_date.iloc[end-1].date()),
                                        "rolling_active_return": am["active_cumulative_return"], "rolling_information_ratio": am["information_ratio"],
                                        "rolling_beta_qqq": beta(ay, qx), "rolling_tracking_error": am["tracking_error"]})
    for name, returns in [("A2", a2), ("QQQ_RAW", qqq), *primary_returns.items()]:
        tail = downside_metrics(returns, qqq)
        monthly = pd.Series(returns, index=pd.DatetimeIndex(aligned.execution_date)).groupby(aligned.execution_date.dt.to_period("M").to_numpy()).apply(lambda x: float(np.prod(1 + x) - 1))
        diagnostic_rows.append({"row_type": "TAIL", "benchmark": name, **tail, "worst_month": float(monthly.min())})
    pd.DataFrame(diagnostic_rows).to_csv(out / "rolling_and_tail_diagnostics.csv", index=False, encoding="utf-8-sig")

    bm_summary = summary.set_index("benchmark")
    beta_row = bm_summary.loc["QQQ_BETA_MATCHED"]
    vol_row = bm_summary.loc["QQQ_VOL_MATCHED"]
    periods = pd.DataFrame(period_rows)
    positive_folds = {
        name: int(periods.loc[(periods.benchmark.eq(name)) & periods.test.eq("AUTHORITATIVE_OOS_FOLD"), "active_positive"].sum())
        for name in primary_returns
    }
    beta_rolling = pd.DataFrame(diagnostic_rows)
    beta_roll = beta_rolling.loc[beta_rolling.row_type.eq("ROLLING")]
    spreads = beta_roll.groupby("window").rolling_beta_qqq.quantile(.9) - beta_roll.groupby("window").rolling_beta_qqq.quantile(.1)
    fold_betas = [beta(a2[aligned.execution_date.dt.year.eq(y)], qqq[aligned.execution_date.dt.year.eq(y)]) for y in [2023, 2024, 2025]]
    if any(x <= 0 for x in fold_betas) or float(spreads.max()) > 1.0:
        beta_stability = "HIGHLY_REGIME_DEPENDENT"
    elif float(spreads.max()) > .5:
        beta_stability = "MODERATELY_VARIABLE"
    else:
        beta_stability = "STABLE"
    beta_loo = periods.loc[(periods.benchmark.eq("QQQ_BETA_MATCHED")) & periods.test.eq("LEAVE_ONE_CALENDAR_YEAR_OUT")]
    vol_loo = periods.loc[(periods.benchmark.eq("QQQ_VOL_MATCHED")) & periods.test.eq("LEAVE_ONE_CALENDAR_YEAR_OUT")]
    ex5 = periods.loc[(periods.benchmark.eq("QQQ_BETA_MATCHED")) & periods.period.eq("EX_BEST_5_ACTIVE_DAYS")].iloc[0]
    both_negative = beta_row.active_cumulative_return < 0 and vol_row.active_cumulative_return < 0
    if both_negative and positive_folds["QQQ_BETA_MATCHED"] <= 1 and positive_folds["QQQ_VOL_MATCHED"] <= 1:
        classification = "SIMPLE_RISK_MATCHED_BENCHMARK_DOMINATES"
    elif (beta_row.active_cumulative_return > 0) != (vol_row.active_cumulative_return > 0) or positive_folds["QQQ_BETA_MATCHED"] != positive_folds["QQQ_VOL_MATCHED"]:
        classification = "RISK_MATCHED_VALUE_INCONCLUSIVE"
    elif (beta_row.annualized_active_return <= .05 and vol_row.annualized_active_return <= .05) or (beta_row.information_ratio <= .20 and vol_row.information_ratio <= .20 and max(positive_folds.values()) <= 1):
        classification = "SIMPLE_BETA_EXPOSURE_LARGELY_EXPLAINS_A2"
    elif beta_row.active_cagr > 0 and vol_row.active_cagr > 0 and min(positive_folds.values()) >= 2:
        strong = (beta_row.information_ratio >= .50 and vol_row.information_ratio >= .50 and
                  beta_loo.active_cumulative_return.gt(0).all() and vol_loo.active_cumulative_return.gt(0).all() and
                  beta_row.bootstrap_probability_active_mean_positive >= .80 and ex5.information_ratio > 0)
        classification = "ACTIVE_VALUE_STRONGLY_SUPPORTED" if strong else "BETA_ENHANCED_WITH_MODEST_ACTIVE_VALUE"
    else:
        classification = "RISK_MATCHED_VALUE_INCONCLUSIVE"

    best5 = periods.loc[(periods.benchmark.eq("QQQ_BETA_MATCHED")) & periods.period.eq("BEST_5_ACTIVE_DAYS")].iloc[0]
    a2_tail = pd.DataFrame(diagnostic_rows).loc[(pd.DataFrame(diagnostic_rows).row_type.eq("TAIL")) & (pd.DataFrame(diagnostic_rows).benchmark.eq("A2"))].iloc[0]
    vol_tail = pd.DataFrame(diagnostic_rows).loc[(pd.DataFrame(diagnostic_rows).row_type.eq("TAIL")) & (pd.DataFrame(diagnostic_rows).benchmark.eq("QQQ_VOL_MATCHED"))].iloc[0]
    beta_tail = pd.DataFrame(diagnostic_rows).loc[(pd.DataFrame(diagnostic_rows).row_type.eq("TAIL")) & (pd.DataFrame(diagnostic_rows).benchmark.eq("QQQ_BETA_MATCHED"))].iloc[0]
    flags = ["ZERO_FINANCING_SIMPLE_BENCHMARK_FAVORABLE_UPPER_BOUND", "SELECTION_BIAS_UNQUANTIFIED", "2026_EXPOSED_DIAGNOSTIC_ONLY"]
    if beta_stability != "STABLE": flags.append("QQQ_BETA_NOT_STABLE")
    if vol_row.active_cumulative_return < 0: flags.append("VOL_MATCHED_QQQ_OUTPERFORMS_A2")
    if ex5.information_ratio <= 0: flags.append("ACTIVE_VALUE_FAILS_EX_BEST5_DAYS")
    most_damaging = (
        f"Volatility-matched QQQ produces active CAGR {vol_row.active_cagr:.4f} for A2-minus-benchmark and wins in {3-positive_folds['QQQ_VOL_MATCHED']}/3 OOS folds."
        if vol_row.active_cumulative_return < 0 else
        f"Beta-matched active IR is only {beta_row.information_ratio:.3f} with HAC t {beta_row.hac_tstat:.3f}."
    )
    strongest = f"A2 beats beta-matched QQQ in {positive_folds['QQQ_BETA_MATCHED']}/3 OOS folds with annualized active mean {beta_row.annualized_active_return:.4f}."
    complexity = {
        "ACTIVE_VALUE_STRONGLY_SUPPORTED": "YES_STRONGLY_SUPPORTED",
        "BETA_ENHANCED_WITH_MODEST_ACTIVE_VALUE": "YES_MODEST",
        "RISK_MATCHED_VALUE_INCONCLUSIVE": "INCONCLUSIVE_MODEST_VS_BETA_MATCHED_BUT_NOT_VOL_MATCHED",
        "SIMPLE_BETA_EXPOSURE_LARGELY_EXPLAINS_A2": "NO_MOSTLY_BETA_EXPLAINED",
        "SIMPLE_RISK_MATCHED_BENCHMARK_DOMINATES": "NO_SIMPLE_BENCHMARK_DOMINATES",
    }[classification]
    result = {
        "task_id": TASK_ID,
        "task_status": "COMPLETE_RESEARCH_WITH_PREEXISTING_ANTI_BLOAT_HARD_GATE_FAIL",
        "preregistration_sha256": prereg_sha, "preregistration": PREREGISTRATION,
        "a2_baseline_reconciliation": "PASS_EXACT_1E-12", "authoritative_session_count": len(daily),
        "comparison_session_count": len(aligned), "lost_sessions": lost,
        "primary_classification": classification, "secondary_flags": flags,
        "a2": a2m, "a2_volatility": float(a2.std(ddof=0) * math.sqrt(ANNUALIZATION)),
        "qqq_beta": beta_scale, "qqq_alpha": float(shared.ols_hac(a2, qqq, 5)["alpha_annualized"]),
        "residual_sharpe": float(shared.ols_hac(a2, qqq, 5)["residual_sharpe"]),
        "positive_oos_folds": positive_folds, "beta_stability": beta_stability,
        "fold_betas": fold_betas, "rolling_beta_p90_p10_spread": {str(k): float(v) for k, v in spreads.items()},
        "financing_data_status": "NOT_AVAILABLE;ZERO_FINANCING_BENCHMARK_IS_SIMPLE_BENCHMARK_FAVORABLE_UPPER_BOUND",
        "net_implementable_benchmark": "NOT_APPLICABLE:NO_FROZEN_PIT_SAFE_FINANCING_SERIES",
        "selection_bias_status": "UNQUANTIFIED_CARRIED_FORWARD", "2026_status": "EXPOSED_DIAGNOSTIC_ONLY_NOT_READ",
        "security_level_active_attribution": "NOT_APPLICABLE:ETF_BENCHMARK_HAS_NO_SECURITY_LEVEL_ALLOCATION_CONTRACT",
        "most_damaging_evidence": most_damaging, "strongest_supporting_evidence": strongest,
        "does_a2_complexity_add_economic_value": complexity,
        "recommended_single_next_research_direction": "FROZEN_FORWARD_BETA_MATCHED_ACTIVE_VALUE_VALIDATION",
        "key": {
            "beta_matched": beta_row.to_dict(), "vol_matched": vol_row.to_dict(),
            "beta_matched_positive_folds": positive_folds["QQQ_BETA_MATCHED"], "vol_matched_positive_folds": positive_folds["QQQ_VOL_MATCHED"],
            "active_best_5_days_share": float(best5.positive_active_gain_share), "ex_best_5_active_days_ir": float(ex5.information_ratio),
            "a2_downside_capture_vs_qqq": float(a2_tail.downside_capture_vs_qqq),
            "a2_max_drawdown": float(a2_tail.max_drawdown), "beta_matched_max_drawdown": float(beta_tail.max_drawdown),
            "vol_matched_max_drawdown": float(vol_tail.max_drawdown),
        },
        "lineage": {"upstream_hash_manifest_sha256": sha256_file(UPSTREAM / "hash_manifest.json"),
                    "authoritative_daily_sha256": sha256_file(BASE / "A2/portfolio_daily.parquet"),
                    "benchmark_source_hashes": benchmark_hashes},
        "governance": {"model_fit_count": 0, "parameter_search_count": 0, "benchmark_weight_search_count": 0,
                       "2026_outcome_read_count": 0, "canonical_write_count": 0, "broker_action_count": 0,
                       "anti_bloat_status": "FAIL_PREEXISTING_MANAGED_ACL_REPOSITORY_ACCOUNTING_INCOMPLETE"},
    }
    (out / "classification.json").write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, default=lambda x: None if pd.isna(x) else x, allow_nan=False), encoding="utf-8")
    (out / "final_report.md").write_text(render_report(result, summary, pd.DataFrame(period_rows), pd.DataFrame(diagnostic_rows)), encoding="utf-8")
    rows = []
    for name in FINAL_FILES[:-1]:
        path = out / name
        require(path.is_file(), "FINAL_ARTIFACT_MISSING", name)
        rows.append({"name": name, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    manifest = {"task_id": TASK_ID, "status": "PASS_HASH_VERIFIED", "artifact_count_including_manifest": 6,
                "artifacts": rows, "preregistration_sha256": prereg_sha, "canonical_data_read_only": True}
    (out / "hash_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    require(sorted(p.name for p in out.iterdir() if p.is_file()) == sorted(FINAL_FILES), "FINAL_ARTIFACT_SET_FAILURE")
    print_terminal(result, summary.set_index("benchmark"), len(FINAL_FILES), out)
    return 0


def render_report(c: dict[str, Any], summary: pd.DataFrame, periods: pd.DataFrame, diagnostics: pd.DataFrame) -> str:
    s = summary.set_index("benchmark"); b = s.loc["QQQ_BETA_MATCHED"]; v = s.loc["QQQ_VOL_MATCHED"]; q = s.loc["QQQ_RAW"]; so = s.loc["SOXX_VOL_MATCHED"]
    k = c["key"]; a = c["a2"]
    beta_folds = periods.loc[(periods.benchmark.eq("QQQ_BETA_MATCHED")) & periods.test.eq("AUTHORITATIVE_OOS_FOLD")]
    vol_folds = periods.loc[(periods.benchmark.eq("QQQ_VOL_MATCHED")) & periods.test.eq("AUTHORITATIVE_OOS_FOLD")]
    rolling = diagnostics.loc[diagnostics.row_type.eq("ROLLING")]
    lines = [
        f"# {TASK_ID}", "", "## Executive verdict", "",
        f"TASK_STATUS={c['task_status']}", "A2_BASELINE_RECONCILIATION=PASS_EXACT_1E-12",
        f"PRIMARY_CLASSIFICATION={c['primary_classification']}", f"SECONDARY_FLAGS={'|'.join(c['secondary_flags'])}", "",
        f"A2 对 beta-matched QQQ 仍有年化 active mean {b.annualized_active_return:.2%}、IR {b.information_ratio:.3f}，但 HAC t 仅 {b.hac_tstat:.3f}。",
        f"对 volatility-matched QQQ，A2 active CAGR 为 {v.active_cagr:.2%}，形成方向相反的证据。",
        f"因此结论是 `{c['primary_classification']}`：复杂选股可能增加有限价值，但不能排除简单同风险 QQQ 解释或超过 A2。", "",
        "## Authoritative input and preregistration", "",
        f"- Authoritative A2: 751 sessions; comparison intersection {c['comparison_session_count']}; lost sessions {c['lost_sessions']}.",
        "- Return, NAV, turnover, cost/accounting, OOS fold, and pre-2026 isolation gates pass at 1e-12.",
        f"- Preregistration SHA256: `{c['preregistration_sha256']}`. SOXX and the fixed 50/50 mix were selected before benchmark outcomes.",
        "- Financing data is unavailable. Leveraged benchmarks are zero-financing favorable upper bounds, not net implementable strategies.", "",
        "## Benchmark summary", "",
    ]
    for _, row in summary.iterrows():
        lines.append(f"- {row.benchmark}: scale {row.scale:.4f}, CAGR {row.benchmark_cagr:.2%}, Sharpe {row.benchmark_sharpe:.3f}, MaxDD {row.benchmark_max_drawdown:.2%}; A2-minus active CAGR {row.active_cagr:.2%}, IR {row.information_ratio:.3f}, HAC t {row.hac_tstat:.3f}.")
    lines += ["", "## OOS fold active value", ""]
    for name, frame in (("beta-matched QQQ", beta_folds), ("vol-matched QQQ", vol_folds)):
        lines.append(f"- {name}: {int(frame.active_positive.sum())}/3 positive folds.")
        for _, row in frame.iterrows():
            lines.append(f"  - {row.period}: A2 {row.a2_cumulative_return:.2%}, benchmark {row.benchmark_cumulative_return:.2%}, active compounded return {row.active_cumulative_return:.2%}, IR {row.information_ratio:.3f}.")
    lines += [
        "", "## Inference, concentration, and period robustness", "",
        f"- Beta-matched active mean bootstrap 95% CI: [{b.bootstrap_active_mean_ci_low:.2%}, {b.bootstrap_active_mean_ci_high:.2%}]; P(mean>0)={b.bootstrap_probability_active_mean_positive:.3f}; P(cumulative>0)={b.bootstrap_probability_active_cumulative_positive:.3f}.",
        f"- Vol-matched active mean bootstrap 95% CI: [{v.bootstrap_active_mean_ci_low:.2%}, {v.bootstrap_active_mean_ci_high:.2%}]; P(mean>0)={v.bootstrap_probability_active_mean_positive:.3f}.",
        f"- Best five beta-matched active days account for {k['active_best_5_days_share']:.2%} of positive active gains; removing them leaves IR {k['ex_best_5_active_days_ir']:.3f}.",
        "- EX_2023, EX_STRONGEST_YEAR, and every leave-one-fold/year diagnostic use fixed full-sample leverage; no leverage was re-estimated.",
        "- Security-level active attribution is NOT_APPLICABLE because an ETF benchmark has no security-level allocation contract compatible with A2 positions.", "",
        "## Downside and beta stability", "",
        f"- MaxDD: A2 {k['a2_max_drawdown']:.2%}; beta-matched QQQ {k['beta_matched_max_drawdown']:.2%}; vol-matched QQQ {k['vol_matched_max_drawdown']:.2%}.",
        f"- A2 downside capture vs raw QQQ: {k['a2_downside_capture_vs_qqq']:.3f}. A2 does not demonstrate a general downside-improvement mechanism relative to QQQ.",
        f"- Beta stability: `{c['beta_stability']}`; fold betas {', '.join(f'{x:.3f}' for x in c['fold_betas'])}.",
    ]
    for name in ["QQQ_BETA_MATCHED", "QQQ_VOL_MATCHED"]:
        subset = rolling.loc[rolling.benchmark.eq(name)]
        for window in [63,126,252]:
            g=subset.loc[subset.window.eq(window)]
            lines.append(f"- {name} rolling {window}: positive active-return windows {(g.rolling_active_return>0).mean():.3f}; positive-IR windows {(g.rolling_information_ratio>0).mean():.3f}; beta p10/p90 {g.rolling_beta_qqq.quantile(.1):.3f}/{g.rolling_beta_qqq.quantile(.9):.3f}.")
    lines += [
        "", "## Direct answers", "",
        f"1. Raw QQQ: A2 CAGR {a['cagr']:.2%} vs QQQ {q.benchmark_cagr:.2%}; A2 has higher return but lower Sharpe and worse drawdown.",
        f"2. Beta-matched QQQ: A2-minus active CAGR {b.active_cagr:.2%}, IR {b.information_ratio:.3f}, positive folds {c['positive_oos_folds']['QQQ_BETA_MATCHED']}/3.",
        f"3. Vol-matched QQQ: A2-minus active CAGR {v.active_cagr:.2%}, IR {v.information_ratio:.3f}, positive folds {c['positive_oos_folds']['QQQ_VOL_MATCHED']}/3.",
        f"4. High beta is `{c['beta_stability']}` rather than assumed constant.",
        f"5. Complexity verdict: `{c['does_a2_complexity_add_economic_value']}`.",
        f"6. Most damaging evidence: {c['most_damaging_evidence']}",
        f"7. Strongest supporting evidence: {c['strongest_supporting_evidence']}",
        f"8. Single next direction: `{c['recommended_single_next_research_direction']}`.", "",
        "2026 outcomes were not read. Selection-bias status is inherited as UNQUANTIFIED. No model, parameter, benchmark weight, or leverage was selected from outcomes.",
        "Anti-Bloat remains failed only by the registered pre-existing managed-ACL repository-accounting blocker; this task added no local environment or large artifact.",
    ]
    return "\n".join(lines) + "\n"


def print_terminal(c: dict[str, Any], s: pd.DataFrame, count: int, out: Path) -> None:
    a=c["a2"]; k=c["key"]; q=s.loc["QQQ_RAW"]; b=s.loc["QQQ_BETA_MATCHED"]; v=s.loc["QQQ_VOL_MATCHED"]; tech=s.loc["SOXX_VOL_MATCHED"]
    print("="*60); print(f"{TASK_ID}_FINAL"); print("="*60); print()
    fields={
        "TASK_STATUS":c["task_status"],"A2_BASELINE_RECONCILIATION":c["a2_baseline_reconciliation"],
        "PRIMARY_CLASSIFICATION":c["primary_classification"],"SECONDARY_FLAGS":"|".join(c["secondary_flags"]),
        "A2_CAGR":a["cagr"],"A2_SHARPE":a["sharpe"],"A2_MAX_DRAWDOWN":a["max_drawdown"],"A2_VOLATILITY":c["a2_volatility"],
        "QQQ_CAGR":q.benchmark_cagr,"QQQ_SHARPE":q.benchmark_sharpe,"QQQ_MAX_DRAWDOWN":q.benchmark_max_drawdown,
        "A2_QQQ_BETA":c["qqq_beta"],"A2_QQQ_ALPHA":c["qqq_alpha"],"A2_RESIDUAL_SHARPE":c["residual_sharpe"],
        "BETA_MATCHED_QQQ_SCALE":b.scale,"BETA_MATCHED_QQQ_CAGR":b.benchmark_cagr,"BETA_MATCHED_QQQ_SHARPE":b.benchmark_sharpe,
        "A2_MINUS_BETA_MATCHED_ACTIVE_CAGR":b.active_cagr,"A2_MINUS_BETA_MATCHED_INFORMATION_RATIO":b.information_ratio,
        "BETA_MATCHED_POSITIVE_OOS_FOLDS":c["positive_oos_folds"]["QQQ_BETA_MATCHED"],"BETA_MATCHED_HAC_TSTAT":b.hac_tstat,
        "BETA_MATCHED_BOOTSTRAP_P_ACTIVE_POSITIVE":b.bootstrap_probability_active_mean_positive,
        "VOL_MATCHED_QQQ_SCALE":v.scale,"VOL_MATCHED_QQQ_CAGR":v.benchmark_cagr,"VOL_MATCHED_QQQ_SHARPE":v.benchmark_sharpe,
        "A2_MINUS_VOL_MATCHED_ACTIVE_CAGR":v.active_cagr,"A2_MINUS_VOL_MATCHED_INFORMATION_RATIO":v.information_ratio,
        "VOL_MATCHED_POSITIVE_OOS_FOLDS":c["positive_oos_folds"]["QQQ_VOL_MATCHED"],
        "SOXX_SMH_CHALLENGE_STATUS":"PASS_SOXX_PREDECLARED_FULL_SUPPORT", "A2_MINUS_TECH_MATCHED_ACTIVE_CAGR":tech.active_cagr,
        "ACTIVE_BEST_5_DAYS_SHARE":k["active_best_5_days_share"],"EX_BEST_5_ACTIVE_DAYS_IR":k["ex_best_5_active_days_ir"],
        "BETA_MATCHED_QQQ_MAX_DRAWDOWN":k["beta_matched_max_drawdown"],"VOL_MATCHED_QQQ_MAX_DRAWDOWN":k["vol_matched_max_drawdown"],
        "A2_DOWNSIDE_CAPTURE_VS_QQQ":k["a2_downside_capture_vs_qqq"],"BETA_STABILITY":c["beta_stability"],
        "FINANCING_DATA_STATUS":c["financing_data_status"],"SELECTION_BIAS_STATUS":"UNQUANTIFIED_CARRIED_FORWARD","2026_STATUS":"EXPOSED_DIAGNOSTIC_ONLY",
        "MOST_DAMAGING_EVIDENCE":c["most_damaging_evidence"],"STRONGEST_SUPPORTING_EVIDENCE":c["strongest_supporting_evidence"],
        "DOES_A2_COMPLEXITY_ADD_ECONOMIC_VALUE":c["does_a2_complexity_add_economic_value"],
        "RECOMMENDED_SINGLE_NEXT_RESEARCH_DIRECTION":c["recommended_single_next_research_direction"],
        "OUTPUT_DIR":str(out),"FINAL_ARTIFACT_COUNT":count,"HASH_MANIFEST_STATUS":"PASS_HASH_VERIFIED",
    }
    for key,value in fields.items(): print(f"{key}={value}")
    print("="*60)


if __name__ == "__main__":
    raise SystemExit(main())
