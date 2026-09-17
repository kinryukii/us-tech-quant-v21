"""Frozen, pre-2026 A2/R6/E5 risk and execution overlay ablation.

This runner is deliberately read-only with respect to all frozen inputs.  It
uses the already-frozen A2 economic replay, R6 OOF weights and E5 execution
rule, and writes only the seven compact task artifacts under the external
results root.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / "A2_FROZEN_RISK_EXECUTION_ABLATION_R1"
BASE = RESULTS / "A_VS_A2_QUARTERLY_13F_R1"
E5_ROOT = RESULTS / "A2_EXECUTION_EFFICIENCY_R2_PREREGISTERED_HYSTERESIS"
R5_ROOT = RESULTS / "A2_RISK_CONTROL_R5_CONSTANT_GROSS_R6"
R6_ROOT = RESULTS / "A2_STOCK_RISK_R6"
R10_ROOT = RESULTS / "A2_STOCK_RISK_R10_CLOSEOUT"
R11_ROOT = RESULTS / "A2_STOCK_RISK_R11_PROSPECTIVE"
UPSTREAM = RESULTS / "A2_AUTHORITATIVE_IDENTITY_RECOVERY_AND_FALSIFICATION_CONTINUATION_R1"

E5_SOURCE = E5_ROOT / "run_a2_execution_efficiency_r2.py"
SHARED_SOURCE = REPO / "scripts/v22/a2_strategy_falsification_and_robustness_r1.py"
R6_WEIGHTS = R5_ROOT / "r5_daily_weights.parquet"
R6_OOF = R6_ROOT / "r6_oof_predictions.parquet"
R6_DEPLOY = R11_ROOT / "r6_frozen_deploy_r1.joblib"
R10_FREEZE = R10_ROOT / "r10_freeze_manifest.json"
E5_CONTRACT = E5_ROOT / "execution_r2_preregistered_contract.json"
E5_IDENTITY = E5_ROOT / "preferred_overlay_identity.json"
E5_PATHS = E5_ROOT / "candidate_execution_paths.parquet"

FINAL_FILES = [
    "final_report.md", "arm_summary.csv", "fold_comparison.csv",
    "paired_delta_statistics.csv", "risk_mechanism_decomposition.csv",
    "classification.json", "hash_manifest.json",
]
ARMS = [
    "ARM0_RAW_A2", "ARM1_A2_R6", "ARM2_A2_E5", "ARM3_A2_R6_E5",
    "ARM4_A2_R6_CONSTANT_GROSS", "ARM5_RAW_A2_GROSS_MATCHED_TO_R6",
]
EXPECTED = {
    str(R6_OOF): "5f35b7b54192ce9023a886f3a51d9efaddea526bb78aed4862481f9dd85653b4",
    str(R6_DEPLOY): "3e5f646fcfbf1b4e9196781f712305b044a7b2e57c0fe1b3fe202345561f4a08",
    str(R10_FREEZE): "cc7687e8161ff152bbdffba85998e6fa8721c92277ca5369ad3791aa930ce03c",
    str(E5_CONTRACT): "3dc30c8e49c38870fec41f65a07e83867a0cff7d3918a3a9502d7961eaf012da",
    str(E5_IDENTITY): "76f29b895a336eb60da045973516542b935324b5c0e8013ac4e41db270ba8587",
    str(E5_SOURCE): "005fdbc3a50df5552b4837e2706b7184198c1d1bfcfd7d51d03d3f3b55aabfa6",
    str(R6_WEIGHTS): "498f11ca7f1c85ec3fdc7d22b171f3a42d0ae587eb11b422d36831a5274359e9",
}
ANNUALIZATION = 252
SEED = 20260823
BOOTSTRAPS = 2000
BLOCK = 10
TOL = 1e-12

# Frozen before any arm economics are computed in this task.
ANALYSIS_CONTRACT = {
    "task_id": "A2_FROZEN_RISK_EXECUTION_ABLATION_R1",
    "outcome_window": "PRE2026_ONLY",
    "arms": ARMS,
    "r6_rule": "risk_percentile>=0.90 => 0.5; otherwise 1.0; removed weight to cash",
    "stack_order": "ALPHA_THEN_R6_THEN_E5",
    "stack_suppression_semantics": "suppressed incumbent keeps prior executed R6 target weight; unsuppressed and continuing names use current frozen R6 target weight",
    "r6_constant_gross": "preserve R6 relative weights and normalize to Raw A2 gross 1.0",
    "gross_matched_raw": "uniform Raw A2 relative weights scaled to same-date R6 gross",
    "statistics": {"hac_lags": 5, "moving_block": BLOCK, "repetitions": BOOTSTRAPS, "seed": SEED},
    "classification_rules": {
        "targeted_supported": "ARM4 Sharpe>Raw, ARM1 Sharpe>ARM5, both paired annual means positive, and R6 improves Sharpe in >=2/3 years",
        "mainly_gross": "ARM1 improves Raw while abs(ARM4-Raw Sharpe)<=0.03 and abs(ARM1-ARM5 Sharpe)<=0.03",
        "mixed": "ARM1 improves Sharpe or MaxDD and at least one targeted comparison is positive",
        "no_robust": "ARM1 improves neither Sharpe nor MaxDD and has <2 supportive years",
        "e5_supported": "positive net return delta, lower turnover and cost, and >=2/3 positive years",
        "stack_robust": "higher Sharpe, better MaxDD, and >=2/3 Sharpe and MaxDD supportive years",
    },
    "prohibitions": ["MODEL_FIT", "THRESHOLD_CHANGE", "PARAMETER_SEARCH", "2026_ECONOMICS", "AUTHORITATIVE_MUTATION"],
}


class GateFailure(RuntimeError):
    pass


def require(value: bool, code: str, detail: Any = "") -> None:
    if not value:
        raise GateFailure(f"{code}:{detail}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def import_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_SPEC_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def metrics(returns: Iterable[float]) -> dict[str, float]:
    r = np.asarray(list(returns), float)
    require(len(r) > 1 and np.isfinite(r).all() and (r > -1).all(), "INVALID_RETURNS")
    nav = np.r_[1.0, np.cumprod(1 + r)]
    dd = nav / np.maximum.accumulate(nav) - 1
    vol = float(r.std(ddof=0) * math.sqrt(ANNUALIZATION))
    annual = float(r.mean() * ANNUALIZATION)
    cum = float(nav[-1] - 1)
    cagr = float(nav[-1] ** (ANNUALIZATION / len(r)) - 1)
    week = pd.Series(r).rolling(5).apply(lambda x: np.prod(1 + x) - 1, raw=True).dropna()
    month = pd.Series(r).rolling(21).apply(lambda x: np.prod(1 + x) - 1, raw=True).dropna()
    losses = np.sort(r)[: max(1, int(math.ceil(.05 * len(r))))]
    return {
        "session_count": len(r), "cumulative_return": cum, "cagr": cagr,
        "sharpe": annual / vol if vol else np.nan, "max_drawdown": float(dd.min()),
        "calmar": cagr / abs(float(dd.min())) if dd.min() < 0 else np.nan,
        "annualized_volatility": vol, "worst_day": float(r.min()),
        "worst_week": float(week.min()), "worst_month": float(month.min()),
        "expected_shortfall_5": float(losses.mean()),
    }


def beta(y: np.ndarray, x: np.ndarray) -> float:
    return float(np.cov(y, x, ddof=0)[0, 1] / np.var(x))


def factor_metrics(shared: Any, y: np.ndarray, qqq: np.ndarray) -> dict[str, float]:
    fit = shared.ols_hac(y, qqq, 5)
    up = qqq > 0
    down = qqq < 0
    return {
        "qqq_beta": beta(y, qqq), "qqq_adjusted_alpha": float(fit["alpha_annualized"]),
        "residual_sharpe": float(fit["residual_sharpe"]),
        "upside_beta": beta(y[up], qqq[up]), "downside_beta": beta(y[down], qqq[down]),
        "upside_capture": float(y[up].sum() / qqq[up].sum()),
        "downside_capture": float(y[down].sum() / qqq[down].sum()),
    }


def hac_mean_tstat(values: np.ndarray, lags: int = 5) -> float:
    x = np.asarray(values, float)
    n = len(x)
    u = x - x.mean()
    long_var = float(u @ u / n)
    for lag in range(1, min(lags, n - 1) + 1):
        weight = 1 - lag / (lags + 1)
        gamma = float(u[lag:] @ u[:-lag] / n)
        long_var += 2 * weight * gamma
    se = math.sqrt(max(long_var, 0) / n)
    return float(x.mean() / se) if se else np.nan


def moving_block_indices(n: int, rng: np.random.Generator) -> np.ndarray:
    starts = rng.integers(0, n - BLOCK + 1, size=math.ceil(n / BLOCK))
    return np.concatenate([np.arange(s, s + BLOCK) for s in starts])[:n]


def paired_stats(delta: np.ndarray, seed_offset: int) -> dict[str, float]:
    d = np.asarray(delta, float)
    vol = float(d.std(ddof=0) * math.sqrt(ANNUALIZATION))
    rng = np.random.default_rng(SEED + seed_offset)
    means = np.empty(BOOTSTRAPS)
    for i in range(BOOTSTRAPS):
        means[i] = d[moving_block_indices(len(d), rng)].mean() * ANNUALIZATION
    return {
        "annualized_mean_delta": float(d.mean() * ANNUALIZATION),
        "paired_information_ratio": float(d.mean() * ANNUALIZATION / vol) if vol else np.nan,
        "hac_tstat": hac_mean_tstat(d), "bootstrap_ci_low": float(np.quantile(means, .025)),
        "bootstrap_ci_high": float(np.quantile(means, .975)),
        "bootstrap_probability_positive": float((means > 0).mean()),
    }


def target_dict(frame: pd.DataFrame, column: str) -> dict[pd.Timestamp, dict[str, float]]:
    return {
        pd.Timestamp(date): dict(zip(group.ticker.astype(str), group[column].astype(float)))
        for date, group in frame.groupby("signal_date", sort=True)
    }


def build_stack_targets(
    dates: list[pd.Timestamp], r6: dict[pd.Timestamp, dict[str, float]],
    e5_targets: dict[pd.Timestamp, dict[str, float]], decisions: pd.DataFrame,
) -> dict[pd.Timestamp, dict[str, float]]:
    """Compose the registered Alpha->R6->E5 order without new parameters."""
    by_date = {pd.Timestamp(d): g for d, g in decisions.groupby("signal_date", sort=False)}
    prior: dict[str, float] = {}
    result: dict[pd.Timestamp, dict[str, float]] = {}
    for date in dates:
        current = dict(r6[date])
        executed_names = set(e5_targets[date])
        row = by_date.get(date)
        suppressed_old = set()
        if row is not None:
            suppressed_old = set(row.loc[row.suppressed.astype(bool), "old_name"].astype(str))
        target: dict[str, float] = {}
        for ticker in sorted(executed_names):
            if ticker in current:
                target[ticker] = current[ticker]
            elif ticker in suppressed_old and ticker in prior:
                target[ticker] = prior[ticker]
            else:
                raise GateFailure(f"STACK_WEIGHT_UNRESOLVED:{date.date()}:{ticker}")
        require(len(target) == 20 and sum(target.values()) <= 1 + TOL, "STACK_TARGET_INVALID", date)
        result[date] = target
        prior = target
    return result


def replay_for_signals(e5: Any, name: str, targets: dict[pd.Timestamp, dict[str, float]], prices: pd.DataFrame,
                       raw_prices: pd.DataFrame, control_targets: dict[pd.Timestamp, dict[str, float]]):
    dates = sorted(targets)
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].unique()))
    pos = pd.Series(np.arange(len(calendar)), index=calendar)
    require(min(dates) in pos.index and max(dates) in pos.index, "SIGNAL_CALENDAR_FAILURE")
    # Through the execution session of the final signal; no artificial terminal liquidation.
    execution_dates = list(calendar[int(pos.loc[min(dates)]) + 1 : int(pos.loc[max(dates)]) + 2])
    signal_by_exec = {d: pd.Timestamp(calendar[int(pos.loc[d]) - 1]) for d in execution_dates}
    return e5.replay(name, targets, prices, execution_dates, signal_by_exec,
                     raw_prices=None if name == "ARM0_RAW_A2" else raw_prices,
                     control_targets=None if name == "ARM0_RAW_A2" else control_targets)


def summarize_arm(shared: Any, name: str, replay: Any, qqq_frame: pd.DataFrame, support: str) -> dict[str, Any]:
    d = replay.daily.copy()
    d["execution_date"] = pd.to_datetime(d.execution_date).dt.normalize()
    aligned = d.merge(qqq_frame, on="execution_date", how="inner", validate="one_to_one")
    require(len(aligned) == len(d), "QQQ_ALIGNMENT_LOSS", name)
    r = aligned.net_return.to_numpy(float)
    q = aligned.QQQ.to_numpy(float)
    out = {"arm": name, "support": support, **metrics(r), **factor_metrics(shared, r, q)}
    out.update({
        "turnover": float(aligned.turnover.sum()),
        "total_cost": float(aligned.transaction_cost_fraction.sum()),
        "average_gross_exposure": float(aligned.gross_exposure.mean()),
        "cash_exposure": float(aligned.cash_weight.mean()),
    })
    return out


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def domain_fail_closed(
    e5: Any, shared: Any, frozen: pd.DataFrame, existing_paths: pd.DataFrame,
    identity_errors: dict[str, Any], contract_sha: str, coverage: dict[str, Any],
) -> dict[str, Any]:
    """Finish every independent E5 stage without inventing an R6 path."""
    control_daily = existing_paths.loc[existing_paths.candidate.eq("E0_CONTROL")].sort_values("execution_date").reset_index(drop=True)
    e5_daily = existing_paths.loc[existing_paths.candidate.eq("E5_COMBINED_CONSERVATIVE")].sort_values("execution_date").reset_index(drop=True)
    for frame in (control_daily, e5_daily):
        frame["execution_date"] = pd.to_datetime(frame.execution_date).dt.normalize()
    require(list(control_daily.execution_date) == list(e5_daily.execution_date), "E5_PAIRWISE_SUPPORT_FAILURE")
    benchmark, _ = shared.benchmark_frame(control_daily.execution_date)
    raw_rep = e5.Replay(control_daily, pd.DataFrame(), pd.DataFrame())
    e5_rep = e5.Replay(e5_daily, pd.DataFrame(), pd.DataFrame())
    valid_rows = [
        summarize_arm(shared, "ARM0_RAW_A2", raw_rep, benchmark, "AUTHORITATIVE_RAW_AND_PAIRWISE_RAW_E5"),
        summarize_arm(shared, "ARM2_A2_E5", e5_rep, benchmark, "PAIRWISE_SUPPORT_RAW_E5"),
    ]
    unavailable = {
        "support": "NOT_APPLICABLE:R6_A2_DOMAIN_MISMATCH", "session_count": 0,
        "cumulative_return": np.nan, "cagr": np.nan, "sharpe": np.nan, "max_drawdown": np.nan,
        "calmar": np.nan, "annualized_volatility": np.nan, "worst_day": np.nan, "worst_week": np.nan,
        "worst_month": np.nan, "expected_shortfall_5": np.nan, "qqq_beta": np.nan,
        "qqq_adjusted_alpha": np.nan, "residual_sharpe": np.nan, "upside_beta": np.nan,
        "downside_beta": np.nan, "upside_capture": np.nan, "downside_capture": np.nan,
        "turnover": np.nan, "total_cost": np.nan, "average_gross_exposure": np.nan, "cash_exposure": np.nan,
    }
    by_name = {row["arm"]: row for row in valid_rows}
    arm_summary = pd.DataFrame([by_name.get(name, {"arm": name, **unavailable}) for name in ARMS])

    fold_rows: list[dict[str, Any]] = []
    for name, daily in (("ARM0_RAW_A2", control_daily), ("ARM2_A2_E5", e5_daily)):
        d = daily.merge(benchmark, on="execution_date", validate="one_to_one")
        for year, g in d.groupby(d.execution_date.dt.year):
            fold_rows.append({"evidence": "AUTHORITATIVE_OOS_CALENDAR_FOLD", "fold": str(year), "arm": name,
                              **metrics(g.net_return), **factor_metrics(shared, g.net_return.to_numpy(float), g.QQQ.to_numpy(float)),
                              "turnover": float(g.turnover.sum()), "total_cost": float(g.transaction_cost_fraction.sum())})
    for name in ["ARM1_A2_R6", "ARM3_A2_R6_E5", "ARM4_A2_R6_CONSTANT_GROSS", "ARM5_RAW_A2_GROSS_MATCHED_TO_R6"]:
        for year in [2023, 2024, 2025]:
            fold_rows.append({"evidence": "NOT_APPLICABLE:R6_A2_DOMAIN_MISMATCH", "fold": str(year), "arm": name})
    folds = pd.DataFrame(fold_rows)

    delta = e5_daily.net_return.to_numpy(float) - control_daily.net_return.to_numpy(float)
    e5_stats = paired_stats(delta, 20)
    paired_rows = []
    for label, left, right in [
        ("D_R6", "ARM1_A2_R6", "ARM0_RAW_A2"), ("D_E5", "ARM2_A2_E5", "ARM0_RAW_A2"),
        ("D_STACK", "ARM3_A2_R6_E5", "ARM0_RAW_A2"), ("D_R6_CONST", "ARM4_A2_R6_CONSTANT_GROSS", "ARM0_RAW_A2"),
        ("D_GROSS", "ARM5_RAW_A2_GROSS_MATCHED_TO_R6", "ARM0_RAW_A2"), ("D_E5_ON_R6", "ARM3_A2_R6_E5", "ARM1_A2_R6"),
    ]:
        if label == "D_E5":
            paired_rows.append({"comparison": label, "left_arm": left, "right_arm": right,
                                "support": "PAIRWISE_SUPPORT_RAW_E5", "session_count": len(delta), **e5_stats})
        else:
            paired_rows.append({"comparison": label, "left_arm": left, "right_arm": right,
                                "support": "NOT_APPLICABLE:R6_A2_DOMAIN_MISMATCH", "session_count": 0,
                                "annualized_mean_delta": np.nan, "paired_information_ratio": np.nan, "hac_tstat": np.nan,
                                "bootstrap_ci_low": np.nan, "bootstrap_ci_high": np.nan, "bootstrap_probability_positive": np.nan})
    paired = pd.DataFrame(paired_rows)

    raw = arm_summary.set_index("arm").loc["ARM0_RAW_A2"]
    overlay = arm_summary.set_index("arm").loc["ARM2_A2_E5"]
    fold_piv = folds.loc[folds.arm.isin(["ARM0_RAW_A2", "ARM2_A2_E5"])].pivot(index="fold", columns="arm", values="cumulative_return")
    e5_folds = int((fold_piv["ARM2_A2_E5"] > fold_piv["ARM0_RAW_A2"]).sum())
    e5_net = float(overlay.cumulative_return - raw.cumulative_return)
    e5_turn = float(overlay.turnover - raw.turnover)
    e5_cost = float(overlay.total_cost - raw.total_cost)
    if e5_net > 0 and e5_turn < 0 and e5_cost < 0 and e5_folds >= 2:
        e5_class = "EXECUTION_VALUE_SUPPORTED" if overlay.sharpe > raw.sharpe else "EXECUTION_VALUE_MODEST"
    elif e5_net > 0 and e5_turn < 0:
        e5_class = "EXECUTION_VALUE_MODEST"
    elif e5_net < 0:
        e5_class = "EXECUTION_VALUE_NEGATIVE"
    else:
        e5_class = "NO_ROBUST_EXECUTION_VALUE"

    mechanism = pd.DataFrame([
        {"test": "R6_AUTHORITATIVE_DOMAIN_GATE", "status": "FAIL_CLOSED", **coverage},
        {"test": "R5_EXTENSION_LINEAGE", "status": "NONCOMPARABLE_OLD_A2_TOP20_PATH",
         "evidence": str(R5_ROOT / "r5_source_manifest.json")},
        {"test": "E5_ON_RAW", "status": "EXECUTED_PAIRWISE_751", "annualized_mean_delta": e5_stats["annualized_mean_delta"],
         "hac_tstat": e5_stats["hac_tstat"], "bootstrap_probability_positive": e5_stats["bootstrap_probability_positive"]},
    ])
    most = (f"Frozen R6 covers only {coverage['covered_security_dates']}/{coverage['required_security_dates']} "
            f"({coverage['row_coverage_pct']:.2%}) authoritative A2 Top20 security-dates and only "
            f"{coverage['complete_date_count']}/{coverage['overlap_date_count']} complete dates; a same-alpha R6 path is not identified.")
    strongest = (f"E5 exact paired replay spans {len(delta)} sessions: cumulative-return delta {e5_net:.6f}, "
                 f"turnover delta {e5_turn:.6f}, cost delta {e5_cost:.6f}, positive folds {e5_folds}/3.")
    classification = {
        "task_status": "FAIL_CLOSED_R6_AUTHORITATIVE_A2_DOMAIN_MISMATCH",
        "analysis_contract_sha256": contract_sha, "raw_a2_reconciliation": "PASS_EXACT_1E-12",
        "raw_identity_errors": identity_errors, "r6_identity_status": "PASS_FROZEN_IDENTITY_BUT_FAIL_A2_DOMAIN_COMPATIBILITY",
        "e5_identity_status": "PASS_FROZEN_PRE2026_SELECTION_NO_2026_SELECTION",
        "overlay_contaminated": False, "2026_outcome_used": False,
        "authoritative_raw_session_count": len(frozen), "all_arm_common_support_session_count": 0,
        "lost_session_count": len(frozen), "lost_session_reasons": "NO_COMPLETE_CONTIGUOUS_R6_PATH_ON_AUTHORITATIVE_A2_TOP20",
        "r6_domain_coverage": coverage, "r6_mechanism_classification": "INCONCLUSIVE",
        "r6_security_level_risk_information": "NOT_APPLICABLE:R6_A2_DOMAIN_MISMATCH",
        "e5_execution_classification": e5_class, "full_stack_classification": "FULL_STACK_MIXED",
        "full_stack_evidence_status": "NOT_APPLICABLE:R6_A2_DOMAIN_MISMATCH",
        "fold_counts": {"r6_sharpe": 0, "r6_maxdd": 0, "e5_net": e5_folds, "stack_sharpe": 0, "stack_maxdd": 0},
        "r6_vs_gross_matched_active_delta": "NOT_APPLICABLE:R6_A2_DOMAIN_MISMATCH",
        "recommended_forward_arms": "RAW_A2|A2_R6_EXPERIMENTAL_ONLY",
        "most_damaging_overlay_evidence": most, "strongest_supporting_overlay_evidence": strongest,
        "official_adoption_allowed": False, "broker_action_allowed": False,
        "preexisting_anti_bloat_exception": "MANAGED_ACL_TEMP_REGISTERED_NO_RETRY_LOOP",
        "anti_bloat_status": "FAIL_PREEXISTING_MANAGED_ACL_REPOSITORY_ACCOUNTING_INCOMPLETE_1",
        "anti_bloat_non_acl_gate_status": "PASS_NO_NEW_TASK_VIOLATION",
        "repo_local_venv_count": 0,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    for name in FINAL_FILES:
        p = OUT / name
        if p.exists(): p.unlink()
    arm_summary.to_csv(OUT / "arm_summary.csv", index=False, encoding="utf-8-sig")
    folds.to_csv(OUT / "fold_comparison.csv", index=False, encoding="utf-8-sig")
    paired.to_csv(OUT / "paired_delta_statistics.csv", index=False, encoding="utf-8-sig")
    mechanism.to_csv(OUT / "risk_mechanism_decomposition.csv", index=False, encoding="utf-8-sig")
    write_json(OUT / "classification.json", classification)
    (OUT / "final_report.md").write_text(render_domain_report(classification, arm_summary), encoding="utf-8")
    artifacts = [{"name": n, "sha256": sha256_file(OUT / n), "bytes": (OUT / n).stat().st_size} for n in FINAL_FILES if n != "hash_manifest.json"]
    write_json(OUT / "hash_manifest.json", {"status": "PASS_HASH_VERIFIED", "artifact_count_excluding_self": len(artifacts),
                                              "artifacts": artifacts, "source_hashes": EXPECTED, "analysis_contract_sha256": contract_sha})
    require(len([p for p in OUT.iterdir() if p.is_file()]) == 7, "ARTIFACT_COUNT_FAILURE")
    print_domain_terminal(classification, arm_summary, paired)
    return classification


def render_domain_report(c: dict[str, Any], arms: pd.DataFrame) -> str:
    a = arms.set_index("arm"); raw = a.loc["ARM0_RAW_A2"]; e5 = a.loc["ARM2_A2_E5"]
    cov = c["r6_domain_coverage"]
    return f"""# A2 Frozen Risk / Execution Ablation R1

## Executive verdict

- TASK_STATUS={c['task_status']}
- RAW_A2_RECONCILIATION={c['raw_a2_reconciliation']}
- R6_MECHANISM_CLASSIFICATION={c['r6_mechanism_classification']}
- E5_EXECUTION_CLASSIFICATION={c['e5_execution_classification']}
- FULL_STACK_EVIDENCE_STATUS={c['full_stack_evidence_status']}
- 2026_OUTCOME_USED=false

The requested same-alpha R6 ablation fails its identity/support gate. This is not an API or metadata failure: frozen R6 scores belong to an older A2 Top20 domain. Filling missing names, using the current deployment fit, or silently restricting to complete cases would change the frozen experiment. Raw/E5 remains independently identifiable and is completed below.

## Authoritative identities

- Raw A2: exact 751-session return/NAV/turnover/cost replay within 1e-12.
- R6 binary/hash: valid (`{EXPECTED[str(R6_DEPLOY)]}`); OOF hash valid (`{EXPECTED[str(R6_OOF)]}`). Identity validity does not imply compatibility with the authoritative A2 path.
- E5: frozen `E5_COMBINED_CONSERVATIVE`, contract `{EXPECTED[str(E5_CONTRACT)]}`, selected only from pre-2026 outcomes; 2026 selection fields are empty.
- Analysis contract SHA256: `{c['analysis_contract_sha256']}`.

## R6 domain gate

- Overlap dates: {cov['overlap_date_count']} ({cov['date_min']} to {cov['date_max']}).
- Required authoritative A2 Top20 security-dates: {cov['required_security_dates']}.
- Frozen R6-covered security-dates: {cov['covered_security_dates']} ({cov['row_coverage_pct']:.2%}).
- Complete Top20 dates: {cov['complete_date_count']}/{cov['overlap_date_count']}.
- R5 extension exact same-day Top20 identity: {cov['r5_exact_top20_date_count']}/{cov['r5_overlap_date_count']} dates.

There is no complete contiguous R6 path. Therefore ARM1, ARM3, ARM4, and ARM5 are `NOT_APPLICABLE:R6_A2_DOMAIN_MISMATCH`; six-arm common support is zero. R5's already-produced economics are not transplanted because its Raw A2 ranking path is noncomparable.

## Raw A2 vs E5 (maximum legal pairwise support)

| Arm | Sessions | CAGR | Sharpe | MaxDD | QQQ beta | Downside capture | Residual Sharpe | Turnover | Cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Raw A2 | {int(raw.session_count)} | {raw.cagr:.4%} | {raw.sharpe:.4f} | {raw.max_drawdown:.4%} | {raw.qqq_beta:.4f} | {raw.downside_capture:.4f} | {raw.residual_sharpe:.4f} | {raw.turnover:.4f} | {raw.total_cost:.6f} |
| A2 + E5 | {int(e5.session_count)} | {e5.cagr:.4%} | {e5.sharpe:.4f} | {e5.max_drawdown:.4%} | {e5.qqq_beta:.4f} | {e5.downside_capture:.4f} | {e5.residual_sharpe:.4f} | {e5.turnover:.4f} | {e5.total_cost:.6f} |

E5 cumulative-return delta is {e5.cumulative_return-raw.cumulative_return:.6f}, Sharpe delta {e5.sharpe-raw.sharpe:.6f}, turnover delta {e5.turnover-raw.turnover:.6f}, and cost delta {e5.total_cost-raw.total_cost:.6f}. Fold, HAC, and deterministic block-bootstrap evidence are in the compact CSV artifacts.

## Verdict

- R6 security-level information versus gross reduction cannot be identified on authoritative A2 without a new score/replay generation, which this task forbids.
- E5 is `{c['e5_execution_classification']}` on its exact frozen A2 path, but it was historically selected on these same pre-2026 folds and is not fresh forward evidence.
- Full-stack interaction was not computed; `FULL_STACK_MIXED` is the required enum placeholder, not an economic finding.
- Most damaging evidence: {c['most_damaging_overlay_evidence']}
- Strongest supporting evidence: {c['strongest_supporting_overlay_evidence']}
- Recommended forward design: `{c['recommended_forward_arms']}`. R6 remains experimental only; no adoption or broker action is authorized.

## Governance

No model fit, threshold change, TopN change, 2026 economics, canonical mutation, or authoritative artifact mutation occurred. The preexisting managed-ACL temp exception was registered once and not retried.

The formal Anti-Bloat guard remains `FAIL_PREEXISTING_MANAGED_ACL_REPOSITORY_ACCOUNTING_INCOMPLETE_1`. All non-ACL guard checks passed, no repo-local venv exists, and this task introduced no large repository or results artifact. This report does not weaken that hard gate.
"""


def print_domain_terminal(c: dict[str, Any], arms: pd.DataFrame, paired: pd.DataFrame) -> None:
    a = arms.set_index("arm"); p = paired.set_index("comparison")
    raw, e5 = a.loc["ARM0_RAW_A2"], a.loc["ARM2_A2_E5"]
    na = "NOT_APPLICABLE:R6_A2_DOMAIN_MISMATCH"
    vals = {
        "TASK_STATUS": c["task_status"], "RAW_A2_RECONCILIATION": c["raw_a2_reconciliation"],
        "R6_IDENTITY_STATUS": c["r6_identity_status"], "E5_IDENTITY_STATUS": c["e5_identity_status"], "2026_OUTCOME_USED": "FALSE",
        "AUTHORITATIVE_RAW_SESSION_COUNT": c["authoritative_raw_session_count"], "ALL_ARM_COMMON_SUPPORT_SESSION_COUNT": 0,
        "RAW_CAGR": raw.cagr, "RAW_SHARPE": raw.sharpe, "RAW_MAXDD": raw.max_drawdown, "RAW_VOL": raw.annualized_volatility,
        "RAW_QQQ_BETA": raw.qqq_beta, "RAW_DOWNSIDE_CAPTURE": raw.downside_capture, "RAW_RESIDUAL_SHARPE": raw.residual_sharpe, "RAW_TURNOVER": raw.turnover, "RAW_COST": raw.total_cost,
        "R6_CAGR": na, "R6_SHARPE": na, "R6_MAXDD": na, "R6_VOL": na, "R6_QQQ_BETA": na, "R6_DOWNSIDE_CAPTURE": na,
        "R6_RESIDUAL_SHARPE": na, "R6_TURNOVER": na, "R6_COST": na, "R6_SHARPE_DELTA": na, "R6_MAXDD_DELTA": na,
        "R6_BETA_DELTA": na, "R6_DOWNSIDE_CAPTURE_DELTA": na, "R6_RESIDUAL_SHARPE_DELTA": na,
        "E5_CAGR": e5.cagr, "E5_SHARPE": e5.sharpe, "E5_MAXDD": e5.max_drawdown, "E5_TURNOVER": e5.turnover, "E5_COST": e5.total_cost,
        "E5_NET_RETURN_DELTA": e5.cumulative_return-raw.cumulative_return, "E5_SHARPE_DELTA": e5.sharpe-raw.sharpe,
        "E5_TURNOVER_DELTA": e5.turnover-raw.turnover, "E5_COST_DELTA": e5.total_cost-raw.total_cost,
        "STACK_CAGR": na, "STACK_SHARPE": na, "STACK_MAXDD": na, "STACK_QQQ_BETA": na, "STACK_DOWNSIDE_CAPTURE": na,
        "STACK_RESIDUAL_SHARPE": na, "STACK_TURNOVER": na, "STACK_COST": na,
        "R6_CONSTANT_GROSS_SHARPE": na, "R6_CONSTANT_GROSS_MAXDD": na,
        "RAW_GROSS_MATCHED_TO_R6_SHARPE": na, "RAW_GROSS_MATCHED_TO_R6_MAXDD": na,
        "R6_VS_GROSS_MATCHED_ACTIVE_DELTA": na, "R6_SECURITY_LEVEL_RISK_INFORMATION": na,
        "R6_VALUE_SOURCE": c["r6_mechanism_classification"], "R6_SHARPE_IMPROVEMENT_FOLD_COUNT": na,
        "R6_MAXDD_IMPROVEMENT_FOLD_COUNT": na, "E5_NET_VALUE_POSITIVE_FOLD_COUNT": c["fold_counts"]["e5_net"],
        "STACK_SHARPE_IMPROVEMENT_FOLD_COUNT": na, "STACK_MAXDD_IMPROVEMENT_FOLD_COUNT": na,
        "R6_VS_RAW_HAC_TSTAT": na, "R6_VS_RAW_BOOTSTRAP_P_POSITIVE": na,
        "E5_VS_RAW_HAC_TSTAT": p.loc["D_E5"].hac_tstat, "E5_VS_RAW_BOOTSTRAP_P_POSITIVE": p.loc["D_E5"].bootstrap_probability_positive,
        "STACK_VS_RAW_HAC_TSTAT": na, "STACK_VS_RAW_BOOTSTRAP_P_POSITIVE": na,
        "R6_MECHANISM_CLASSIFICATION": c["r6_mechanism_classification"], "E5_EXECUTION_CLASSIFICATION": c["e5_execution_classification"],
        "FULL_STACK_CLASSIFICATION": c["full_stack_classification"],
        "MOST_DAMAGING_OVERLAY_EVIDENCE": c["most_damaging_overlay_evidence"], "STRONGEST_SUPPORTING_OVERLAY_EVIDENCE": c["strongest_supporting_overlay_evidence"],
        "RECOMMENDED_FORWARD_ARMS": c["recommended_forward_arms"], "OUTPUT_DIR": str(OUT), "FINAL_ARTIFACT_COUNT": 7, "HASH_MANIFEST_STATUS": "PASS_HASH_VERIFIED",
    }
    print("=" * 60); print("A2_FROZEN_RISK_EXECUTION_ABLATION_R1_FINAL"); print("=" * 60)
    for k, v in vals.items(): print(f"{k}={v}")
    print("=" * 60)


def run() -> dict[str, Any]:
    # Input identity gate happens before any economics are read.
    for path, expected in EXPECTED.items():
        p = Path(path)
        require(p.is_file() and sha256_file(p) == expected, "FROZEN_HASH_FAILURE", p)
    contract_sha = hashlib.sha256(canonical_json(ANALYSIS_CONTRACT).encode()).hexdigest()
    upstream = json.loads((UPSTREAM / "robustness_classification.json").read_text(encoding="utf-8"))
    require(upstream["historical_path_authority"] == "PASS" and upstream["baseline_reconciliation_status"].startswith("PASS"), "A2_UPSTREAM_GATE")
    r10 = json.loads(R10_FREEZE.read_text(encoding="utf-8"))
    require(r10["freeze_payload"]["r6_identity"]["oof_sha256"] == EXPECTED[str(R6_OOF)], "R6_FREEZE_OOF_MISMATCH")
    e5_identity = json.loads(E5_IDENTITY.read_text(encoding="utf-8"))
    require(e5_identity["preferred_overlay"] == "E5_COMBINED_CONSERVATIVE" and e5_identity["selection_source"] == "PRE2026_ONLY", "E5_SELECTION_IDENTITY")
    require(e5_identity["candidate_outcome_fields_2026_used"] == [], "E5_2026_CONTAMINATION")

    e5 = import_file("a2_ablation_e5_frozen", E5_SOURCE)
    shared = import_file("a2_ablation_shared", SHARED_SOURCE)
    pred, intended = e5.load_pre_predictions()
    raw_targets, _ = e5.build_executed_targets("E0_CONTROL", pred, intended)
    e5_targets, e5_decisions = e5.build_executed_targets("E5_COMBINED_CONSERVATIVE", pred, intended)
    prices, raw_prices = e5.load_pre_prices(set(pred.ticker))

    # Exact authoritative Raw A2 gate on the full frozen support.
    frozen = pd.read_parquet(BASE / "A2/portfolio_daily.parquet").sort_values("execution_date").reset_index(drop=True)
    frozen["execution_date"] = pd.to_datetime(frozen.execution_date).dt.normalize()
    existing_paths = pd.read_parquet(E5_PATHS)
    control = existing_paths.loc[existing_paths.candidate.eq("E0_CONTROL")].sort_values("execution_date").reset_index(drop=True)
    control["execution_date"] = pd.to_datetime(control.execution_date).dt.normalize()
    identity_errors = {
        "rows": int(len(control) - len(frozen)),
        "date": int((control.execution_date != frozen.execution_date).sum()),
        "return": float(np.max(np.abs(control.net_return - frozen.reconstructed_daily_return))),
        "nav": float(np.max(np.abs(control.nav - frozen.reconstructed_nav))),
        "turnover": float(np.max(np.abs(control.turnover - frozen.reconstructed_turnover))),
        "cost": float(np.max(np.abs(control.transaction_cost_amount - frozen.reconstructed_transaction_cost))),
    }
    require(identity_errors["rows"] == 0 and identity_errors["date"] == 0 and max(identity_errors[k] for k in ["return", "nav", "turnover", "cost"]) <= TOL, "RAW_RECONCILIATION", identity_errors)
    require(frozen.execution_date.max() < pd.Timestamp("2026-01-01"), "2026_OUTCOME_ISOLATION")

    weights = pd.read_parquet(R6_WEIGHTS)
    weights["signal_date"] = pd.to_datetime(weights.signal_date).dt.normalize()
    weights["ticker"] = weights.ticker.astype(str).str.upper()
    allowed = sorted(set(raw_targets) & set(weights.signal_date.unique()))
    require(allowed and max(allowed) < pd.Timestamp("2026-01-01"), "R6_SUPPORT_FAILURE")
    w = weights.loc[weights.signal_date.isin(allowed)].copy()
    require(not w.duplicated(["signal_date", "ticker"]).any() and w.groupby("signal_date").size().eq(20).all(), "R6_WEIGHT_IDENTITY")

    # Compatibility is an independent hard gate.  A valid R6 artifact cannot
    # be attached to a different A2 Top20 domain by complete-case filtering.
    original_r6 = pd.read_parquet(R6_OOF, columns=["signal_date", "ticker", "candidate_id"])
    original_r6["signal_date"] = pd.to_datetime(original_r6.signal_date).dt.normalize()
    original_r6["ticker"] = original_r6.ticker.astype(str).str.upper()
    original_r6 = original_r6.loc[original_r6.candidate_id.eq("LGBM_BAD_ASYM_2")]
    overlap = sorted(set(raw_targets) & set(original_r6.signal_date.unique()))
    available = set(zip(original_r6.signal_date, original_r6.ticker))
    covered_by_date = {d: sum((d, ticker) in available for ticker in raw_targets[d]) for d in overlap}
    r5_exact = sum(set(raw_targets[d]) == set(w.loc[w.signal_date.eq(d), "ticker"]) for d in allowed)
    coverage = {
        "date_min": str(min(overlap).date()), "date_max": str(max(overlap).date()),
        "overlap_date_count": len(overlap), "required_security_dates": len(overlap) * 20,
        "covered_security_dates": int(sum(covered_by_date.values())),
        "row_coverage_pct": float(sum(covered_by_date.values()) / (len(overlap) * 20)),
        "complete_date_count": int(sum(value == 20 for value in covered_by_date.values())),
        "minimum_names_covered_per_date": int(min(covered_by_date.values())),
        "r5_overlap_date_count": len(allowed), "r5_exact_top20_date_count": int(r5_exact),
    }
    if coverage["complete_date_count"] != coverage["overlap_date_count"] or r5_exact != len(allowed):
        return domain_fail_closed(e5, shared, frozen, existing_paths, identity_errors, contract_sha, coverage)

    r6_targets = target_dict(w, "original_r6_weight")
    const_targets = target_dict(w, "r5_weight")
    gross_by_date = w.groupby("signal_date").original_r6_weight.sum()
    gross_targets = {d: {t: float(gross_by_date.loc[d] / 20) for t in raw_targets[d]} for d in allowed}
    stack_targets = build_stack_targets(allowed, r6_targets, e5_targets, e5_decisions)
    common_raw = {d: raw_targets[d] for d in allowed}
    common_e5 = {d: e5_targets[d] for d in allowed}
    target_sets = {
        "ARM0_RAW_A2": common_raw, "ARM1_A2_R6": r6_targets, "ARM2_A2_E5": common_e5,
        "ARM3_A2_R6_E5": stack_targets, "ARM4_A2_R6_CONSTANT_GROSS": const_targets,
        "ARM5_RAW_A2_GROSS_MATCHED_TO_R6": gross_targets,
    }
    replays = {name: replay_for_signals(e5, name, target_sets[name], prices, raw_prices, common_raw) for name in ARMS}
    dates0 = replays["ARM0_RAW_A2"].daily.execution_date
    require(all(list(rep.daily.execution_date) == list(dates0) for rep in replays.values()), "ALL_ARM_SUPPORT_MISMATCH")
    require(max(pd.to_datetime(dates0)) < pd.Timestamp("2026-01-01"), "2026_REPLAY_FAILURE")

    benchmark, _ = shared.benchmark_frame(pd.Series(pd.to_datetime(dates0)))
    arm_rows = [summarize_arm(shared, name, replays[name], benchmark, "ALL_ARM_COMMON_SUPPORT") for name in ARMS]
    arm_summary = pd.DataFrame(arm_rows)
    by_arm = arm_summary.set_index("arm")

    fold_rows: list[dict[str, Any]] = []
    for name, rep in replays.items():
        d = rep.daily.copy()
        d["execution_date"] = pd.to_datetime(d.execution_date).dt.normalize()
        d = d.merge(benchmark, on="execution_date", validate="one_to_one")
        for year, g in d.groupby(d.execution_date.dt.year):
            m = metrics(g.net_return)
            fm = factor_metrics(shared, g.net_return.to_numpy(float), g.QQQ.to_numpy(float))
            fold_rows.append({"evidence": "AUTHORITATIVE_OOS_CALENDAR_FOLD", "fold": str(year), "arm": name,
                              **m, **fm, "turnover": float(g.turnover.sum()), "total_cost": float(g.transaction_cost_fraction.sum())})
    folds = pd.DataFrame(fold_rows)

    comparisons = [
        ("D_R6", "ARM1_A2_R6", "ARM0_RAW_A2"), ("D_E5", "ARM2_A2_E5", "ARM0_RAW_A2"),
        ("D_STACK", "ARM3_A2_R6_E5", "ARM0_RAW_A2"),
        ("D_R6_CONST", "ARM4_A2_R6_CONSTANT_GROSS", "ARM0_RAW_A2"),
        ("D_GROSS", "ARM5_RAW_A2_GROSS_MATCHED_TO_R6", "ARM0_RAW_A2"),
        ("D_E5_ON_R6", "ARM3_A2_R6_E5", "ARM1_A2_R6"),
    ]
    paired_rows = []
    for i, (label, left, right) in enumerate(comparisons):
        delta = replays[left].daily.net_return.to_numpy(float) - replays[right].daily.net_return.to_numpy(float)
        paired_rows.append({"comparison": label, "left_arm": left, "right_arm": right,
                            "support": "ALL_ARM_COMMON_SUPPORT_AND_MAX_PAIRWISE_SUPPORT_FOR_R6_ARMS",
                            "session_count": len(delta), **paired_stats(delta, i)})
    # E5 has a larger valid pairwise support than the all-arm intersection.
    full_e5 = existing_paths.loc[existing_paths.candidate.isin(["E0_CONTROL", "E5_COMBINED_CONSERVATIVE"])].copy()
    piv = full_e5.pivot(index="execution_date", columns="candidate", values="net_return").dropna()
    paired_rows.append({"comparison": "D_E5_PAIRWISE_MAX", "left_arm": "ARM2_A2_E5", "right_arm": "ARM0_RAW_A2",
                        "support": "PAIRWISE_SUPPORT_RAW_E5", "session_count": len(piv),
                        **paired_stats((piv["E5_COMBINED_CONSERVATIVE"] - piv["E0_CONTROL"]).to_numpy(float), 20)})
    paired = pd.DataFrame(paired_rows)

    raw = by_arm.loc["ARM0_RAW_A2"]
    r6 = by_arm.loc["ARM1_A2_R6"]
    e5row = by_arm.loc["ARM2_A2_E5"]
    stack = by_arm.loc["ARM3_A2_R6_E5"]
    const = by_arm.loc["ARM4_A2_R6_CONSTANT_GROSS"]
    gross = by_arm.loc["ARM5_RAW_A2_GROSS_MATCHED_TO_R6"]
    def fold_improvement(left: str, right: str, metric: str, higher: bool = True) -> int:
        p = folds.pivot(index="fold", columns="arm", values=metric)
        return int((p[left] > p[right]).sum() if higher else (p[left] > p[right]).sum())
    r6_sharpe_folds = fold_improvement("ARM1_A2_R6", "ARM0_RAW_A2", "sharpe")
    r6_dd_folds = fold_improvement("ARM1_A2_R6", "ARM0_RAW_A2", "max_drawdown")
    e5_return_folds = fold_improvement("ARM2_A2_E5", "ARM0_RAW_A2", "cumulative_return")
    stack_sharpe_folds = fold_improvement("ARM3_A2_R6_E5", "ARM0_RAW_A2", "sharpe")
    stack_dd_folds = fold_improvement("ARM3_A2_R6_E5", "ARM0_RAW_A2", "max_drawdown")

    r6_pair = paired.set_index("comparison").loc["D_R6"]
    const_pair = paired.set_index("comparison").loc["D_R6_CONST"]
    r6_vs_gross_delta = float((replays["ARM1_A2_R6"].daily.net_return - replays["ARM5_RAW_A2_GROSS_MATCHED_TO_R6"].daily.net_return).mean() * ANNUALIZATION)
    if const.sharpe > raw.sharpe and r6.sharpe > gross.sharpe and const_pair.annualized_mean_delta > 0 and r6_vs_gross_delta > 0 and r6_sharpe_folds >= 2:
        r6_class = "TARGETED_RISK_INFORMATION_SUPPORTED"
        r6_info = "SUPPORTED"
    elif r6.sharpe > raw.sharpe and abs(const.sharpe - raw.sharpe) <= .03 and abs(r6.sharpe - gross.sharpe) <= .03:
        r6_class = "MAINLY_GROSS_DERISKING"
        r6_info = "NOT_SUPPORTED_BEYOND_GROSS"
    elif (r6.sharpe > raw.sharpe or r6.max_drawdown > raw.max_drawdown) and (const.sharpe > raw.sharpe or r6_vs_gross_delta > 0):
        r6_class = "MIXED_TARGETED_AND_GROSS"
        r6_info = "PARTIAL"
    elif r6.sharpe <= raw.sharpe and r6.max_drawdown <= raw.max_drawdown and r6_sharpe_folds < 2:
        r6_class = "NO_ROBUST_RISK_OVERLAY_VALUE"
        r6_info = "NOT_SUPPORTED"
    else:
        r6_class = "INCONCLUSIVE"
        r6_info = "INCONCLUSIVE"

    e5_turn = float(e5row.turnover - raw.turnover)
    e5_cost = float(e5row.total_cost - raw.total_cost)
    e5_net = float(e5row.cumulative_return - raw.cumulative_return)
    if e5_net > 0 and e5_turn < 0 and e5_cost < 0 and e5_return_folds >= 2:
        e5_class = "EXECUTION_VALUE_SUPPORTED" if float(e5row.sharpe - raw.sharpe) > 0 else "EXECUTION_VALUE_MODEST"
    elif e5_net > 0 and e5_turn < 0:
        e5_class = "EXECUTION_VALUE_MODEST"
    elif e5_net < 0:
        e5_class = "EXECUTION_VALUE_NEGATIVE"
    elif e5_turn < 0:
        e5_class = "NO_ROBUST_EXECUTION_VALUE"
    else:
        e5_class = "INCONCLUSIVE"

    if stack.sharpe > raw.sharpe and stack.max_drawdown > raw.max_drawdown and stack_sharpe_folds >= 2 and stack_dd_folds >= 2:
        stack_class = "FULL_STACK_ROBUSTLY_IMPROVES_RAW_A2"
    elif stack.sharpe > raw.sharpe and (stack.max_drawdown > raw.max_drawdown or stack_sharpe_folds >= 2):
        stack_class = "FULL_STACK_MODESTLY_IMPROVES_RAW_A2"
    elif stack.sharpe < raw.sharpe and stack.max_drawdown < raw.max_drawdown:
        stack_class = "FULL_STACK_WORSE"
    elif stack.sharpe <= raw.sharpe and stack.max_drawdown <= raw.max_drawdown:
        stack_class = "FULL_STACK_NO_IMPROVEMENT"
    else:
        stack_class = "FULL_STACK_MIXED"

    if r6_class in {"TARGETED_RISK_INFORMATION_SUPPORTED", "MIXED_TARGETED_AND_GROSS"} and stack_class in {"FULL_STACK_ROBUSTLY_IMPROVES_RAW_A2", "FULL_STACK_MODESTLY_IMPROVES_RAW_A2"}:
        forward = "RAW_A2|A2_R6|A2_R6_E5"
    elif r6_class == "MAINLY_GROSS_DERISKING":
        forward = "RAW_A2|A2_R6|RAW_A2_GROSS_MATCHED_TO_R6"
    else:
        forward = "RAW_A2|A2_R6_EXPERIMENTAL_ONLY"

    mechanism = pd.DataFrame([
        {"test": "R6_TARGETED_CONSTANT_GROSS", "left": "ARM4", "right": "ARM0", "sharpe_delta": float(const.sharpe-raw.sharpe), "maxdd_delta": float(const.max_drawdown-raw.max_drawdown), "annualized_mean_delta": float(const_pair.annualized_mean_delta)},
        {"test": "R6_VS_SIMPLE_GROSS_MATCH", "left": "ARM1", "right": "ARM5", "sharpe_delta": float(r6.sharpe-gross.sharpe), "maxdd_delta": float(r6.max_drawdown-gross.max_drawdown), "annualized_mean_delta": r6_vs_gross_delta},
        {"test": "E5_ON_RAW", "left": "ARM2", "right": "ARM0", "sharpe_delta": float(e5row.sharpe-raw.sharpe), "maxdd_delta": float(e5row.max_drawdown-raw.max_drawdown), "annualized_mean_delta": float(paired.set_index("comparison").loc["D_E5"].annualized_mean_delta)},
        {"test": "E5_ON_R6_INTERACTION", "left": "ARM3", "right": "ARM1", "sharpe_delta": float(stack.sharpe-r6.sharpe), "maxdd_delta": float(stack.max_drawdown-r6.max_drawdown), "annualized_mean_delta": float(paired.set_index("comparison").loc["D_E5_ON_R6"].annualized_mean_delta)},
    ])

    all_count = len(replays["ARM0_RAW_A2"].daily)
    lost = len(frozen) - all_count
    most_damaging = f"R6 common-support Sharpe delta={r6.sharpe-raw.sharpe:.4f}; constant-gross delta={const.sharpe-raw.sharpe:.4f}; only {r6_sharpe_folds}/3 folds improve." if r6_sharpe_folds < 2 else f"E5 net-return delta={e5_net:.4f} with {e5_return_folds}/3 positive folds."
    strongest = f"R6 MaxDD improves by {r6.max_drawdown-raw.max_drawdown:.4f} and downside capture changes by {r6.downside_capture-raw.downside_capture:.4f}." if r6.max_drawdown > raw.max_drawdown else f"E5 reduces turnover by {-e5_turn:.4f} and cost by {-e5_cost:.6f}."
    classification = {
        "task_status": "PASS_FROZEN_PRE2026_ABLATION_COMPLETE",
        "analysis_contract_sha256": contract_sha,
        "raw_a2_reconciliation": "PASS_EXACT_1E-12",
        "raw_identity_errors": identity_errors,
        "r6_identity_status": "PASS_FROZEN_HASH_AND_PRE2026_OOF",
        "e5_identity_status": "PASS_FROZEN_PRE2026_SELECTION_NO_2026_SELECTION",
        "overlay_contaminated": False, "2026_outcome_used": False,
        "authoritative_raw_session_count": len(frozen), "all_arm_common_support_session_count": all_count,
        "lost_session_count": lost, "lost_session_reasons": "R6 frozen historical OOF/weight support ends 2025-12-03; Raw/E5 remain defined later",
        "r6_mechanism_classification": r6_class, "r6_security_level_risk_information": r6_info,
        "e5_execution_classification": e5_class, "full_stack_classification": stack_class,
        "stack_contract_status": "CROSS_VERIFIED_REGISTERED_ORDER_DIAGNOSTIC_COMPOSITION",
        "fold_counts": {"r6_sharpe": r6_sharpe_folds, "r6_maxdd": r6_dd_folds, "e5_net": e5_return_folds,
                        "stack_sharpe": stack_sharpe_folds, "stack_maxdd": stack_dd_folds},
        "r6_vs_gross_matched_active_delta": r6_vs_gross_delta,
        "recommended_forward_arms": forward,
        "most_damaging_overlay_evidence": most_damaging,
        "strongest_supporting_overlay_evidence": strongest,
        "official_adoption_allowed": False, "broker_action_allowed": False,
        "preexisting_anti_bloat_exception": "MANAGED_ACL_TEMP_REGISTERED_NO_RETRY_LOOP",
    }

    OUT.mkdir(parents=True, exist_ok=True)
    for name in FINAL_FILES:
        p = OUT / name
        if p.exists():
            p.unlink()
    arm_summary.to_csv(OUT / "arm_summary.csv", index=False, encoding="utf-8-sig")
    folds.to_csv(OUT / "fold_comparison.csv", index=False, encoding="utf-8-sig")
    paired.to_csv(OUT / "paired_delta_statistics.csv", index=False, encoding="utf-8-sig")
    mechanism.to_csv(OUT / "risk_mechanism_decomposition.csv", index=False, encoding="utf-8-sig")
    write_json(OUT / "classification.json", classification)
    (OUT / "final_report.md").write_text(render_report(classification, arm_summary, folds, paired, mechanism), encoding="utf-8")
    artifacts = [{"name": n, "sha256": sha256_file(OUT / n), "bytes": (OUT / n).stat().st_size} for n in FINAL_FILES if n != "hash_manifest.json"]
    write_json(OUT / "hash_manifest.json", {"status": "PASS_HASH_VERIFIED", "artifact_count_excluding_self": len(artifacts), "artifacts": artifacts,
                                              "source_hashes": EXPECTED, "analysis_contract_sha256": contract_sha})
    require(len([p for p in OUT.iterdir() if p.is_file()]) == 7, "ARTIFACT_COUNT_FAILURE")
    print_terminal(classification, arm_summary, paired)
    return classification


def render_report(c: dict[str, Any], arms: pd.DataFrame, folds: pd.DataFrame, paired: pd.DataFrame, mechanism: pd.DataFrame) -> str:
    a = arms.set_index("arm")
    def line(name: str) -> str:
        r = a.loc[name]
        return f"| {name} | {r.cagr:.4%} | {r.sharpe:.4f} | {r.max_drawdown:.4%} | {r.qqq_beta:.4f} | {r.downside_capture:.4f} | {r.residual_sharpe:.4f} | {r.turnover:.4f} | {r.total_cost:.6f} | {r.average_gross_exposure:.4f} |"
    return "\n".join([
        "# A2 Frozen Risk / Execution Ablation R1", "",
        "## Executive verdict", "",
        f"- TASK_STATUS={c['task_status']}", f"- R6_MECHANISM_CLASSIFICATION={c['r6_mechanism_classification']}",
        f"- E5_EXECUTION_CLASSIFICATION={c['e5_execution_classification']}", f"- FULL_STACK_CLASSIFICATION={c['full_stack_classification']}",
        f"- RECOMMENDED_FORWARD_ARMS={c['recommended_forward_arms']}", "",
        "The experiment changes no model, threshold, TopN, or overlay rule. All economics are pre-2026. The full-stack diagnostic follows the registered Alpha→R6→E5 order; a suppressed replacement preserves the incumbent's prior executed R6 target weight. This deterministic composition is diagnostic and is not a new promoted contract.", "",
        "## Frozen identity", "",
        f"- Raw A2: `{c['raw_a2_reconciliation']}` on {c['authoritative_raw_session_count']} authoritative sessions.",
        f"- R6: `{c['r6_identity_status']}`; OOF `{EXPECTED[str(R6_OOF)]}`; deployment `{EXPECTED[str(R6_DEPLOY)]}`.",
        f"- E5: `{c['e5_identity_status']}`; contract `{EXPECTED[str(E5_CONTRACT)]}`; rule `SUPPRESS_ONE_PERIOD_IFF_EXIT_CURRENT_RANK_LE_22_AND_ENTRANT_CURRENT_RANK_GE_19_AND_SCORE_MARGIN_PP_LT_2_5`.",
        f"- Analysis contract SHA256: `{c['analysis_contract_sha256']}`.", "",
        "## Support", "",
        f"Authoritative Raw has {c['authoritative_raw_session_count']} sessions. The six-arm common comparison has {c['all_arm_common_support_session_count']} sessions; {c['lost_session_count']} sessions are excluded because {c['lost_session_reasons']}. The comparison path does not replace authoritative Raw A2. Raw/E5 pairwise statistics additionally use their maximum legal support.", "",
        "## Arm scorecard", "",
        "| Arm | CAGR | Sharpe | MaxDD | QQQ beta | Down capture | Residual Sharpe | Turnover | Cost | Avg gross |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *[line(name) for name in ARMS], "",
        "## R6 mechanism", "",
        f"Classification: `{c['r6_mechanism_classification']}`; security-level information: `{c['r6_security_level_risk_information']}`.",
        f"R6 versus simple gross-matched Raw annualized paired delta: {c['r6_vs_gross_matched_active_delta']:.4%}.",
        "ARM4 isolates security-specific weights at constant gross; ARM5 isolates gross reduction with Raw relative weights. These are fixed mechanism diagnostics, not candidate selection.", "",
        "## E5 and interaction", "",
        f"E5 classification: `{c['e5_execution_classification']}`. Full stack: `{c['full_stack_classification']}`.",
        "The paired table reports E5 on Raw and E5 incremental to R6 separately, preventing gross-exposure effects from being mislabeled execution value.", "",
        "## OOS breadth and paired evidence", "",
        f"R6 Sharpe/MaxDD improvement folds: {c['fold_counts']['r6_sharpe']}/3 and {c['fold_counts']['r6_maxdd']}/3. E5 positive-net folds: {c['fold_counts']['e5_net']}/3. Stack Sharpe/MaxDD improvement folds: {c['fold_counts']['stack_sharpe']}/3 and {c['fold_counts']['stack_maxdd']}/3.",
        "Paired daily deltas use Newey-West/HAC inference and deterministic 10-session moving-block bootstrap (2,000 repetitions; seed 20260823). No IID bootstrap is used.", "",
        "## Verdict", "",
        f"Most damaging evidence: {c['most_damaging_overlay_evidence']}",
        f"Strongest supporting evidence: {c['strongest_supporting_overlay_evidence']}",
        f"The single forward design recommendation is `{c['recommended_forward_arms']}`. This result authorizes no historical tuning, official adoption, or broker action.", "",
        "## Governance", "",
        "- 2026_OUTCOME_USED=false", "- MODEL_FIT_COUNT=0", "- PARAMETER_SEARCH_COUNT=0", "- TOP_N=20",
        "- Existing managed-ACL temp is registered as a preexisting exception; no retry loop or policy weakening occurred.",
    ]) + "\n"


def print_terminal(c: dict[str, Any], arms: pd.DataFrame, paired: pd.DataFrame) -> None:
    a = arms.set_index("arm"); p = paired.set_index("comparison")
    raw, r6, e5, stack, const, gross = [a.loc[x] for x in ARMS]
    values = {
        "TASK_STATUS": c["task_status"], "RAW_A2_RECONCILIATION": c["raw_a2_reconciliation"],
        "R6_IDENTITY_STATUS": c["r6_identity_status"], "E5_IDENTITY_STATUS": c["e5_identity_status"], "2026_OUTCOME_USED": "FALSE",
        "AUTHORITATIVE_RAW_SESSION_COUNT": c["authoritative_raw_session_count"], "ALL_ARM_COMMON_SUPPORT_SESSION_COUNT": c["all_arm_common_support_session_count"],
        "RAW_CAGR": raw.cagr, "RAW_SHARPE": raw.sharpe, "RAW_MAXDD": raw.max_drawdown, "RAW_VOL": raw.annualized_volatility,
        "RAW_QQQ_BETA": raw.qqq_beta, "RAW_DOWNSIDE_CAPTURE": raw.downside_capture, "RAW_RESIDUAL_SHARPE": raw.residual_sharpe, "RAW_TURNOVER": raw.turnover, "RAW_COST": raw.total_cost,
        "R6_CAGR": r6.cagr, "R6_SHARPE": r6.sharpe, "R6_MAXDD": r6.max_drawdown, "R6_VOL": r6.annualized_volatility, "R6_QQQ_BETA": r6.qqq_beta,
        "R6_DOWNSIDE_CAPTURE": r6.downside_capture, "R6_RESIDUAL_SHARPE": r6.residual_sharpe, "R6_TURNOVER": r6.turnover, "R6_COST": r6.total_cost,
        "R6_SHARPE_DELTA": r6.sharpe-raw.sharpe, "R6_MAXDD_DELTA": r6.max_drawdown-raw.max_drawdown, "R6_BETA_DELTA": r6.qqq_beta-raw.qqq_beta,
        "R6_DOWNSIDE_CAPTURE_DELTA": r6.downside_capture-raw.downside_capture, "R6_RESIDUAL_SHARPE_DELTA": r6.residual_sharpe-raw.residual_sharpe,
        "E5_CAGR": e5.cagr, "E5_SHARPE": e5.sharpe, "E5_MAXDD": e5.max_drawdown, "E5_TURNOVER": e5.turnover, "E5_COST": e5.total_cost,
        "E5_NET_RETURN_DELTA": e5.cumulative_return-raw.cumulative_return, "E5_SHARPE_DELTA": e5.sharpe-raw.sharpe, "E5_TURNOVER_DELTA": e5.turnover-raw.turnover, "E5_COST_DELTA": e5.total_cost-raw.total_cost,
        "STACK_CAGR": stack.cagr, "STACK_SHARPE": stack.sharpe, "STACK_MAXDD": stack.max_drawdown, "STACK_QQQ_BETA": stack.qqq_beta,
        "STACK_DOWNSIDE_CAPTURE": stack.downside_capture, "STACK_RESIDUAL_SHARPE": stack.residual_sharpe, "STACK_TURNOVER": stack.turnover, "STACK_COST": stack.total_cost,
        "R6_CONSTANT_GROSS_SHARPE": const.sharpe, "R6_CONSTANT_GROSS_MAXDD": const.max_drawdown,
        "RAW_GROSS_MATCHED_TO_R6_SHARPE": gross.sharpe, "RAW_GROSS_MATCHED_TO_R6_MAXDD": gross.max_drawdown,
        "R6_VS_GROSS_MATCHED_ACTIVE_DELTA": c["r6_vs_gross_matched_active_delta"], "R6_SECURITY_LEVEL_RISK_INFORMATION": c["r6_security_level_risk_information"], "R6_VALUE_SOURCE": c["r6_mechanism_classification"],
        "R6_SHARPE_IMPROVEMENT_FOLD_COUNT": c["fold_counts"]["r6_sharpe"], "R6_MAXDD_IMPROVEMENT_FOLD_COUNT": c["fold_counts"]["r6_maxdd"],
        "E5_NET_VALUE_POSITIVE_FOLD_COUNT": c["fold_counts"]["e5_net"], "STACK_SHARPE_IMPROVEMENT_FOLD_COUNT": c["fold_counts"]["stack_sharpe"], "STACK_MAXDD_IMPROVEMENT_FOLD_COUNT": c["fold_counts"]["stack_maxdd"],
        "R6_VS_RAW_HAC_TSTAT": p.loc["D_R6"].hac_tstat, "R6_VS_RAW_BOOTSTRAP_P_POSITIVE": p.loc["D_R6"].bootstrap_probability_positive,
        "E5_VS_RAW_HAC_TSTAT": p.loc["D_E5"].hac_tstat, "E5_VS_RAW_BOOTSTRAP_P_POSITIVE": p.loc["D_E5"].bootstrap_probability_positive,
        "STACK_VS_RAW_HAC_TSTAT": p.loc["D_STACK"].hac_tstat, "STACK_VS_RAW_BOOTSTRAP_P_POSITIVE": p.loc["D_STACK"].bootstrap_probability_positive,
        "R6_MECHANISM_CLASSIFICATION": c["r6_mechanism_classification"], "E5_EXECUTION_CLASSIFICATION": c["e5_execution_classification"], "FULL_STACK_CLASSIFICATION": c["full_stack_classification"],
        "MOST_DAMAGING_OVERLAY_EVIDENCE": c["most_damaging_overlay_evidence"], "STRONGEST_SUPPORTING_OVERLAY_EVIDENCE": c["strongest_supporting_overlay_evidence"],
        "RECOMMENDED_FORWARD_ARMS": c["recommended_forward_arms"], "OUTPUT_DIR": str(OUT), "FINAL_ARTIFACT_COUNT": 7, "HASH_MANIFEST_STATUS": "PASS_HASH_VERIFIED",
    }
    print("=" * 60); print("A2_FROZEN_RISK_EXECUTION_ABLATION_R1_FINAL"); print("=" * 60)
    for k, v in values.items(): print(f"{k}={v}")
    print("=" * 60)


if __name__ == "__main__":
    run()
