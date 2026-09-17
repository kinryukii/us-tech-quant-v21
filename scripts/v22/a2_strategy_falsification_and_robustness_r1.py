from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy import stats


TASK_ID = "A2_STRATEGY_FALSIFICATION_AND_ROBUSTNESS_R1"
CONTINUATION_TASK_ID = "A2_AUTHORITATIVE_IDENTITY_RECOVERY_AND_FALSIFICATION_CONTINUATION_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
BASE = RESULTS / "A_VS_A2_QUARTERLY_13F_R1"
OUT = RESULTS / TASK_ID
CONTINUATION_OUT = RESULTS / CONTINUATION_TASK_ID
QFQ_ROOT = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")
FROZEN_RUNNER = BASE / "scripts/run_rebuild.py"
R0F_SOURCE = REPO / "scripts/v22/fast_a2_r0f_corporate_action_and_nav_forensic_audit.py"
R0F1_SOURCE = REPO / "scripts/v22/fast_a2_r0f1_corporate_action_accounting_repair_and_exact_r4_rerun.py"
FREEZE_MANIFEST = BASE / "audit/freeze_r1/frozen_baseline_manifest.json"
FREEZE_HASHES = BASE / "audit/freeze_r1/frozen_artifact_hashes.csv"
FOUNDATION_REGISTRY = RESULTS / "A2_FORWARD_FOUNDATION_CLOSEOUT_R1/research_run_registry.csv"
RUN_INVENTORY = RESULTS / "A2_FULL_HISTORY_SYNTHESIS_AND_AUTONOMOUS_NEXTGEN_R1/historical_run_inventory.csv"
SYNTHESIS_STATUS = RESULTS / "A2_FULL_HISTORY_SYNTHESIS_AND_AUTONOMOUS_NEXTGEN_R1/final_status.json"
ANNUALIZATION = 252.0
ABS_TOL = 1e-12


PREREGISTRATION: dict[str, Any] = {
    "task_id": TASK_ID,
    "purpose": "falsification_only",
    "outcome_blind_freeze_note": "Frozen in memory before new robustness outcomes were computed; baseline memory was used only for identity reconciliation.",
    "annualization": 252,
    "risk_free_rate": 0.0,
    "hac_maxlags": 5,
    "rolling_windows": [63, 126, 252],
    "primary_benchmark": "QQQ",
    "secondary_benchmark": "SOXX",
    "auxiliary_benchmark": "SPY",
    "high_vol_regime": "QQQ trailing 63-session volatility, lagged one session, above its prior expanding median (min 63)",
    "cost_multipliers": [1.0, 1.5, 2.0, 3.0],
    "top_n_diagnostics": [15, 20, 25],
    "authoritative_top_n": 20,
    "score_noise_sigma_levels": [0.01, 0.025, 0.05],
    "score_noise_seed_base": 20260823,
    "score_noise_seed_count": 100,
    "moving_block_bootstrap_block_length": 10,
    "moving_block_bootstrap_repetitions": 2000,
    "moving_block_bootstrap_seed": 20260823,
    "security_jackknife_counts": [1, 3, 5, 10],
    "time_subtractions": ["best_day", "best_5_days", "best_10_days", "best_month", "best_quarter", "best_year", "strongest_oos_fold", "exclude_2023"],
    "warning_rules": {
        "winner_concentration": "top5_positive_contribution_share>=0.75 OR ex_top5_sharpe<=0",
        "temporal_concentration": "strongest_oos_fold_share_of_positive_edge>=0.50 AND excluding it makes cumulative return<=0",
        "implementation_fragility": "2x cost cumulative return<=0 OR 2x cost Sharpe<=0",
        "parameter_needle": "both Top15 and Top25 Sharpe<=0 OR their median Sharpe<0.5*Top20 Sharpe",
        "beta_dependence": "QQQ residual Sharpe<0.5*raw Sharpe AND HAC alpha |t|<1.96",
        "selection_bias": "conservative DSR<0.5 OR valid SPA p>0.10; otherwise fail-closed qualitative warning when trial distribution is unavailable",
    },
    "classification_precedence": [
        "NO_ROBUST_ECONOMIC_EDGE", "IMPLEMENTATION_FRAGILE", "CONCENTRATED_WINNER_CAPTURE",
        "SELECTION_BIAS_SUSPECT", "BETA_ENHANCED_FACTOR_STRATEGY",
        "PROMISING_BUT_INSUFFICIENT_FORWARD", "ROBUST_ALPHA_CANDIDATE",
    ],
    "no_2026_selection": True,
}


FINAL_FILES = [
    "final_report.md",
    "robustness_classification.json",
    "factor_beta_decomposition.csv",
    "concentration_and_jackknife.csv",
    "implementation_stress.csv",
    "temporal_and_benchmark_comparison.csv",
    "multiple_testing_adjustment.json",
    "hash_manifest.json",
]


class FailClosed(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise FailClosed(f"{code}:{detail}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str, allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def import_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_SPEC_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def finite(value: Any) -> Any:
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    return value


def registry_model_fit_id(auth: dict[str, Any]) -> str:
    match = re.search(r"\bFit\s+([^;]+)", str(auth.get("identity_notes", "")))
    return match.group(1) if match else "UNRESOLVED"


def metrics(returns: Iterable[float]) -> dict[str, float | int | None]:
    r = np.asarray(list(returns), dtype=float)
    require(len(r) > 0 and np.isfinite(r).all() and (r > -1).all(), "INVALID_RETURN_SERIES")
    nav = np.r_[1.0, np.cumprod(1.0 + r)]
    dd = nav / np.maximum.accumulate(nav) - 1.0
    vol = float(r.std(ddof=0) * math.sqrt(ANNUALIZATION))
    ann = float(r.mean() * ANNUALIZATION)
    cum = float(nav[-1] - 1.0)
    cagr = float(nav[-1] ** (ANNUALIZATION / len(r)) - 1.0)
    return {
        "observations": int(len(r)), "cumulative_return": cum, "cagr": cagr,
        "annualized_return": ann, "annualized_volatility": vol,
        "sharpe": ann / vol if vol else None, "max_drawdown": float(dd.min()),
        "calmar": cagr / abs(float(dd.min())) if dd.min() < 0 else None,
    }


def ols_hac(y: np.ndarray, factors: np.ndarray, maxlags: int = 5) -> dict[str, Any]:
    y = np.asarray(y, float)
    f = np.asarray(factors, float)
    if f.ndim == 1:
        f = f[:, None]
    x = np.column_stack([np.ones(len(y)), f])
    require(len(y) == len(x) and len(y) > x.shape[1] + maxlags, "REGRESSION_TOO_SHORT")
    inv = np.linalg.pinv(x.T @ x)
    coef = inv @ x.T @ y
    resid = y - x @ coef
    n, k = x.shape
    meat = np.zeros((k, k), float)
    xu = x * resid[:, None]
    meat += xu.T @ xu
    for lag in range(1, maxlags + 1):
        weight = 1.0 - lag / (maxlags + 1.0)
        gamma = xu[lag:].T @ xu[:-lag]
        meat += weight * (gamma + gamma.T)
    cov_hac = (n / (n - k)) * inv @ meat @ inv
    se_hac = np.sqrt(np.clip(np.diag(cov_hac), 0, None))
    sigma2 = float(resid @ resid / (n - k))
    se_ols = np.sqrt(np.clip(np.diag(sigma2 * inv), 0, None))
    tss = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float(resid @ resid) / tss if tss else None
    neutral = float(coef[0]) + resid
    neutral_vol = float(resid.std(ddof=0) * math.sqrt(ANNUALIZATION))
    return {
        "coefficients": coef, "residuals": resid, "r2": r2,
        "alpha_daily": float(coef[0]), "alpha_annualized": float(coef[0] * ANNUALIZATION),
        "alpha_t_ols": float(coef[0] / se_ols[0]) if se_ols[0] else None,
        "alpha_t_hac": float(coef[0] / se_hac[0]) if se_hac[0] else None,
        "residual_annualized_return": float(neutral.mean() * ANNUALIZATION),
        "residual_volatility": neutral_vol,
        "residual_sharpe": float(neutral.mean() * ANNUALIZATION / neutral_vol) if neutral_vol else None,
        "condition_number": float(np.linalg.cond(x)),
    }


def vif(factors: np.ndarray) -> list[float]:
    f = np.asarray(factors, float)
    result: list[float] = []
    for j in range(f.shape[1]):
        others = np.delete(f, j, axis=1)
        if others.shape[1] == 0:
            result.append(1.0)
            continue
        fit = ols_hac(f[:, j], others, 1)
        r2 = fit["r2"]
        result.append(float(1.0 / (1.0 - r2)) if r2 is not None and r2 < 1 else math.inf)
    return result


def moving_block_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    require(n >= block > 0, "INVALID_BLOCK_BOOTSTRAP")
    starts = rng.integers(0, n - block + 1, size=math.ceil(n / block))
    return np.concatenate([np.arange(s, s + block) for s in starts])[:n]


def target_map(oof: pd.DataFrame, n: int, score: pd.Series | None = None) -> dict[pd.Timestamp, dict[str, float]]:
    work = oof[["signal_date", "ticker", "a2_prediction", "a2_rank"]].copy()
    if score is None:
        work = work.sort_values(["signal_date", "a2_rank", "ticker"], kind="mergesort")
    else:
        require(len(score) == len(work), "PERTURBATION_LENGTH_MISMATCH")
        work["_score"] = np.asarray(score, float)
        work = work.sort_values(["signal_date", "_score", "ticker"], ascending=[True, False, True], kind="mergesort")
    chosen = work.groupby("signal_date", sort=False).head(n)
    counts = chosen.groupby("signal_date").ticker.nunique()
    require(counts.eq(n).all(), "TOPN_CARDINALITY_FAILURE", n)
    return {pd.Timestamp(d): {str(t): 1.0 / n for t in g.ticker} for d, g in chosen.groupby("signal_date", sort=True)}


def build_frozen_prices() -> tuple[pd.DataFrame, dict[str, str]]:
    frozen = import_file("a2_falsification_frozen_runner", FROZEN_RUNNER)
    r0f1 = import_file("a2_falsification_r0f1", R0F1_SOURCE)
    members = pd.read_parquet(BASE / "universe/quarterly_universe_members.parquet")
    index, failures = frozen.raw_file_index()
    require(not failures, "RAW_INDEX_FAILURE", failures[:3])
    pairs = members[["moomoo_transport_code", "ticker"]].drop_duplicates()
    require(pairs.groupby("moomoo_transport_code").ticker.nunique().max() == 1, "TRANSPORT_TICKER_AMBIGUITY")
    pairs = pairs.loc[pairs.moomoo_transport_code.isin(index)].sort_values("moomoo_transport_code")
    factor_path = frozen.RUN_CACHE / "rehab_factors.parquet"
    status_path = frozen.RUN_CACHE / "rehab_status.csv"
    rehab = pd.read_parquet(factor_path)
    rehab_status = pd.read_csv(status_path, keep_default_na=False)
    done = set(rehab_status.loc[rehab_status.status.eq("PASS"), "code"])
    codes = set(pairs.moomoo_transport_code)
    require(codes.issubset(done), "REHAB_CACHE_INCOMPLETE_NO_NETWORK_ALLOWED", len(codes - done))
    wolf = [x for x in r0f1.frozen_evidence_records() if x["ticker"] == "WOLF"][0]
    frames = []
    for row in pairs.itertuples(index=False):
        raw = frozen.load_raw_code(row.moomoo_transport_code, index[row.moomoo_transport_code])
        raw = raw.loc[raw.trade_date < pd.Timestamp("2026-01-01")]
        if raw.empty:
            continue
        adjusted, _ = frozen.adjusted_price_frame(row.moomoo_transport_code, row.ticker, raw, rehab, wolf)
        frames.append(adjusted)
    qqq = frozen.qqq_prices()
    prices = pd.concat([
        pd.concat(frames, ignore_index=True),
        qqq.loc[qqq.trade_date < pd.Timestamp("2026-01-01"), ["ticker", "trade_date", "open", "close", "volume", "autype", "source"]],
    ], ignore_index=True).sort_values(["ticker", "trade_date"], kind="mergesort")
    require(not prices.duplicated(["ticker", "trade_date"]).any(), "FROZEN_PRICE_DUPLICATE")
    return prices, {
        "frozen_runner_sha256": sha256_file(FROZEN_RUNNER),
        "r0f_source_sha256": sha256_file(R0F_SOURCE),
        "r0f1_source_sha256": sha256_file(R0F1_SOURCE),
        "rehab_factors_sha256": sha256_file(factor_path),
        "rehab_status_sha256": sha256_file(status_path),
    }


def benchmark_frame(dates: pd.Series) -> tuple[pd.DataFrame, dict[str, str]]:
    need = {2022, 2023, 2024, 2025}
    pieces = []
    hashes = {}
    for year in sorted(need):
        path = QFQ_ROOT / f"year={year}/prices.parquet"
        require(path.exists(), "BENCHMARK_FILE_MISSING", path)
        hashes[str(path)] = sha256_file(path)
        part = pd.read_parquet(path, columns=["ticker", "trade_date", "open", "autype", "source"])
        pieces.append(part.loc[part.ticker.astype(str).str.upper().isin(["QQQ", "SOXX", "SMH", "SPY"])])
    px = pd.concat(pieces, ignore_index=True)
    px["trade_date"] = pd.to_datetime(px.trade_date).dt.normalize()
    require(px.autype.astype(str).str.lower().eq("qfq").all(), "BENCHMARK_NOT_QFQ")
    px = px.sort_values(["ticker", "trade_date"], kind="mergesort").drop_duplicates(["ticker", "trade_date"], keep="last")
    px["return"] = px.groupby("ticker").open.pct_change()
    wide = px.pivot(index="trade_date", columns="ticker", values="return").reindex(pd.DatetimeIndex(dates))
    require(wide[["QQQ", "SOXX", "SPY"]].notna().all().all(), "BENCHMARK_ALIGNMENT_MISSING")
    wide.index.name = "execution_date"
    return wide.reset_index(), hashes


def append_metric_row(rows: list[dict[str, Any]], module: str, test: str, m: dict[str, Any], **extra: Any) -> None:
    row = {"module": module, "test": test, **extra}
    row.update({k: finite(v) for k, v in m.items()})
    rows.append(row)


def write_identity_fail_closed(
    out: Path, prereg_sha: str, freeze: dict[str, Any], frozen_hashes: pd.DataFrame,
    verified: int, mismatches: list[dict[str, Any]], auth: dict[str, Any],
) -> int:
    reason = "AUTHORITATIVE_PREREG_SOURCE_HASH_MISMATCH_AND_CURRENT_FITTED_MODEL_NOT_USED_FOR_FROZEN_OOF_PATH"
    for filename, module in [
        ("factor_beta_decomposition.csv", "A_BENCHMARK_BETA_FACTOR"),
        ("concentration_and_jackknife.csv", "B_CONTRIBUTION_CONCENTRATION"),
        ("implementation_stress.csv", "C_IMPLEMENTATION_ROBUSTNESS"),
        ("temporal_and_benchmark_comparison.csv", "D_F_TEMPORAL_AND_BENCHMARK"),
    ]:
        pd.DataFrame([{
            "module": module, "status": "NOT_EXECUTED_FAIL_CLOSED_AUTHORITATIVE_IDENTITY",
            "reason": reason, "outcome_rows_read": 0,
        }]).to_csv(out / filename, index=False, encoding="utf-8-sig")

    synthesis = json.loads(SYNTHESIS_STATUS.read_text(encoding="utf-8"))
    inventory = pd.read_csv(RUN_INVENTORY, keep_default_na=False)
    multiple = {
        "task_id": active_task_id,
        "status": "NOT_EXECUTED_FAIL_CLOSED_AUTHORITATIVE_IDENTITY",
        "reason": reason,
        "raw_historical_run_count": len(inventory),
        "authoritative_runs_classified": int(synthesis["AUTHORITATIVE_RUNS_CLASSIFIED"]),
        "authoritative_comparable_daily_matrix_count": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "effective_trial_count_estimate": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "deflated_sharpe_ratio": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "pbo": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "spa": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "white_reality_check": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "unknown_candidates_included": 0,
    }
    (out / "multiple_testing_adjustment.json").write_text(
        json.dumps(multiple, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )

    historical = freeze["identity"]["headline_metrics_exact"]
    supplemental = freeze["contracts"]["A2"]["supplemental_full_pre2026_model"]
    stages = freeze["contracts"]["A2"]["effective_model_vintages"]
    classification = {
        "task_id": TASK_ID,
        "task_status": "FAIL_CLOSED_AUTHORITATIVE_IDENTITY_MISMATCH",
        "a2_authoritative_identity_status": "FAIL",
        "baseline_reconciliation_status": "NOT_EXECUTED_IDENTITY_GATE",
        "primary_robustness_classification": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "secondary_flags": ["UNRESOLVED_AUTHORITATIVE_FITTED_IDENTITY", "FROZEN_PREREG_SOURCE_HASH_MISMATCH"],
        "preregistration_sha256": prereg_sha,
        "preregistration": PREREGISTRATION,
        "identity_findings": {
            "registry_logical_name": auth.get("logical_name"),
            "registry_run_id": auth.get("run_id"),
            "registry_model_fit_id": registry_model_fit_id(auth),
            "registry_fitted_model_sha256": auth.get("fitted_model_hash"),
            "historical_economic_artifact": str(BASE / "A2/portfolio_daily.parquet"),
            "historical_economic_artifact_sha256": sha256_file(BASE / "A2/portfolio_daily.parquet"),
            "historical_oof_prediction_sha256": sha256_file(BASE / "A2/oof_predictions.parquet"),
            "historical_oof_model_vintage_count": len(stages),
            "historical_oof_model_vintages": stages,
            "serialized_oof_stage_models": "NOT_PERSISTED",
            "supplemental_full_model": supplemental,
            "supplemental_full_model_used_for_historical_oof": bool(supplemental["used_for_frozen_oof_predictions"]),
            "frozen_hashes_verified": verified,
            "frozen_hash_count": len(frozen_hashes),
            "frozen_hash_mismatches": mismatches,
            "current_prereg_source_git_commit": "3cdf3131fe5f15e318fdf7f7739c44462738a3e8",
            "current_prereg_source_sha256": "056a46d191868a2a99e521671ba713c0b38fa948995749c975c56cdad9186d5f",
            "frozen_prereg_source_sha256": "75f332d09c76e4d4019a85e2a1afd514e2fb6649debfd9cd1ed9414c44c201bb",
            "frozen_source_blob_recoverable_from_git": False,
        },
        "stated_frozen_baseline_not_reinterpreted": {
            "cagr": historical["A2_CAGR"], "sharpe": historical["A2_SHARPE"],
            "max_drawdown": historical["A2_MDD"], "note": "Identity evidence only; no new robustness calculation or economic reinterpretation.",
        },
        "2026_evidence_classification": "UNKNOWN_FAIL_CLOSED",
        "most_damaging_evidence": "The current authoritative fitted model is explicitly not the model behind the frozen OOF economic path, and one immutable prereg source hash no longer verifies.",
        "strongest_supporting_evidence": "The stored daily/OOF/model result files themselves still match 45 of 46 frozen hash-manifest entries; the failure is lineage/source identity, not an observed economic-path mutation.",
        "recommended_single_next_research_direction": "AUTHORITATIVE_IDENTITY_RECOVERY_ONLY_THEN_RERUN_SAME_PREREGISTERED_FALSIFICATION",
        "governance": {
            "outcome_modules_executed": 0, "model_fit_count": 0, "hyperparameter_search": False,
            "portfolio_parameter_selection": False, "2026_used_for_training": False,
            "2026_used_for_selection": False, "canonical_writes": 0, "frozen_artifact_writes": 0,
            "broker_actions": 0, "authoritative_contract_mutations": 0,
            "anti_bloat_status": "FAIL_PREEXISTING_UNREADABLE_REPO_TEMP_HARD_GATE",
        },
    }
    (out / "robustness_classification.json").write_text(
        json.dumps(classification, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )

    report = f"""# A2 Strategy Falsification and Robustness R1

## A. Executive verdict

TASK_STATUS=FAIL_CLOSED_AUTHORITATIVE_IDENTITY_MISMATCH
A2_AUTHORITATIVE_IDENTITY_STATUS=FAIL
BASELINE_RECONCILIATION_STATUS=NOT_EXECUTED_IDENTITY_GATE
PRIMARY_ROBUSTNESS_CLASSIFICATION=NOT_APPLICABLE:IDENTITY_GATE_FAILED
SECONDARY_FLAGS=UNRESOLVED_AUTHORITATIVE_FITTED_IDENTITY|FROZEN_PREREG_SOURCE_HASH_MISMATCH

TEMPORAL_ROBUSTNESS=NOT_EXECUTED
WINNER_CONCENTRATION=NOT_EXECUTED
BENCHMARK_ADJUSTED_EDGE=NOT_EXECUTED
IMPLEMENTATION_ROBUSTNESS=NOT_EXECUTED
MULTIPLE_TESTING_ROBUSTNESS=NOT_EXECUTED
2026_EVIDENCE_CLASSIFICATION=UNKNOWN_FAIL_CLOSED

当前对象不能被严谨地定义为“一个 fitted A2 加上一条属于它的历史经济路径”。Registry 指向 successor full-pre-2026 model，freeze manifest 却明确说该模型未生成三段 OOF predictions；三段 OOF stage models 又未持久化。另有一个被标记 immutable 的 prereg source hash 失配且旧 blob 不可恢复。因此按预注册 identity-first gate 停止，没有读取或计算任何 robustness outcome。

## B. Authoritative identity

- Registry logical/run/model fit: `{auth.get('logical_name')}` / `{auth.get('run_id')}` / `{registry_model_fit_id(auth)}`.
- Registry fitted model SHA256: `{auth.get('fitted_model_hash')}`.
- Historical OOF economics: `{BASE / 'A2/portfolio_daily.parquet'}`; SHA256 `{sha256_file(BASE / 'A2/portfolio_daily.parquet')}`.
- Historical OOF predictions SHA256: `{sha256_file(BASE / 'A2/oof_predictions.parquet')}`.
- OOF protocol has exactly three vintages: 2023 DEVELOPMENT, 2024 CONFIRMATION, 2025 FINAL; serialized stage models are `NOT_PERSISTED`.
- Supplemental full model SHA256 `{supplemental['sha256']}` has `used_for_frozen_oof_predictions=false`.
- Frozen hash verification: {verified}/{len(frozen_hashes)}. Mismatch: immutable prereg source expected `75f332d09c76e4d4019a85e2a1afd514e2fb6649debfd9cd1ed9414c44c201bb`, current `056a46d191868a2a99e521671ba713c0b38fa948995749c975c56cdad9186d5f`.
- The current Git history contains only the latter blob; no byte-identical frozen source was found. No artifact was modified.
- Preregistration SHA256 (frozen before robustness outcomes): `{prereg_sha}`.

## C. Baseline economics

The freeze manifest states CAGR {historical['A2_CAGR']:.12f}, Sharpe {historical['A2_SHARPE']:.12f}, and MaxDD {historical['A2_MDD']:.12f}. These values are reported solely as frozen identity evidence. Exact baseline reconciliation was not promoted to PASS because the upstream authoritative fitted/source identity gate failed.

## D. Factor/beta decomposition

`NOT_EXECUTED_FAIL_CLOSED_AUTHORITATIVE_IDENTITY`. QQQ/SOXX/SPY outcomes were not read.

## E. Security and time concentration

`NOT_EXECUTED_FAIL_CLOSED_AUTHORITATIVE_IDENTITY`. No Top1/3/5/10, best-period, ex-2023, or counterfactual result was calculated.

## F. Implementation stress

`NOT_EXECUTED_FAIL_CLOSED_AUTHORITATIVE_IDENTITY`. No cost, delay, Top15/20/25, or perturbation path was calculated. The authoritative portfolio contract remains untouched.

## G. Multiple-testing adjustment

Inventory identity confirms {len(inventory)} historical runs and {int(synthesis['AUTHORITATIVE_RUNS_CLASSIFIED'])} classified authoritative runs. Comparable-matrix construction, effective trials, DSR, PBO, SPA, and WRC are all `NOT_APPLICABLE:IDENTITY_GATE_FAILED`; UNKNOWN candidates were not admitted.

## H. Benchmark challenge

`NOT_EXECUTED_FAIL_CLOSED_AUTHORITATIVE_IDENTITY`. No benchmark was chosen after outcomes and no benchmark result was read.

## I. 2026 evidence status

`UNKNOWN_FAIL_CLOSED` for this unresolved identity. No 2026 outcome was read or used by this task, and no holdout status was restored.

## J. Falsification verdict

1. A2 may remain a named research control only after its fitted/source/economic lineage is recovered; this task cannot validate it.
2. Independent alpha: not assessable.
3. Beta-enhanced factor strategy: not assessable.
4. Winner dependence: not assessable.
5. 2023 dependence: not assessable.
6. Cost/execution survival: not assessable.
7. Multiple-testing credibility: not assessable beyond confirming high historical multiplicity.
8. Most damaging evidence: current authoritative fitted model did not generate the frozen OOF path, and an immutable prereg source hash fails.
9. Strongest support: 45/46 frozen entries still hash-verify, so no stored economic-path mutation was observed.
10. Single next direction: `AUTHORITATIVE_IDENTITY_RECOVERY_ONLY_THEN_RERUN_SAME_PREREGISTERED_FALSIFICATION`.

No model was fit, no robustness parameter was selected, no 2026 outcome was used, and no canonical/frozen artifact or broker path was modified. The pre-existing unreadable repo temp also keeps the Anti-Bloat hard gate failed; this task created no local venv or large repo artifact.
"""
    (out / "final_report.md").write_text(report, encoding="utf-8")

    manifest_rows = []
    for name in FINAL_FILES[:-1]:
        path = out / name
        manifest_rows.append({"name": name, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    hash_manifest = {
        "task_id": TASK_ID, "status": "PASS_HASH_VERIFIED_FAIL_CLOSED_EVIDENCE_SET",
        "artifact_count_including_manifest": 8, "artifacts": manifest_rows,
        "preregistration_sha256": prereg_sha, "authoritative_inputs_read_only": True,
        "canonical_data_read_only": True,
    }
    (out / "hash_manifest.json").write_text(json.dumps(hash_manifest, indent=2, sort_keys=True), encoding="utf-8")
    actual = sorted(p.name for p in out.iterdir() if p.is_file())
    require(actual == sorted(FINAL_FILES), "FINAL_ARTIFACT_SET_FAILURE", actual)
    print("=" * 60); print(f"{TASK_ID}_FINAL"); print("=" * 60); print()
    fields = {
        "TASK_STATUS": classification["task_status"], "A2_AUTHORITATIVE_IDENTITY_STATUS": "FAIL",
        "BASELINE_RECONCILIATION_STATUS": "NOT_EXECUTED_IDENTITY_GATE",
        "PRIMARY_CLASSIFICATION": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "SECONDARY_FLAGS": "|".join(classification["secondary_flags"]),
        "HISTORICAL_CUM_RETURN": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "HISTORICAL_SHARPE": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "HISTORICAL_MAX_DRAWDOWN": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "QQQ_BETA": "NOT_APPLICABLE:IDENTITY_GATE_FAILED", "QQQ_ADJUSTED_ALPHA": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "RESIDUAL_SHARPE": "NOT_APPLICABLE:IDENTITY_GATE_FAILED", "TOP5_SECURITY_CONTRIBUTION_SHARE": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "EX_TOP5_SHARPE": "NOT_APPLICABLE:IDENTITY_GATE_FAILED", "STRONGEST_YEAR": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "STRONGEST_YEAR_EDGE_SHARE": "NOT_APPLICABLE:IDENTITY_GATE_FAILED", "EX_2023_SHARPE": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "OOS_FOLD_SUPPORT": "NOT_APPLICABLE:IDENTITY_GATE_FAILED", "COST_2X_SHARPE": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "COST_3X_SHARPE": "NOT_APPLICABLE:IDENTITY_GATE_FAILED", "TOP15_SHARPE": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "TOP20_SHARPE": "NOT_APPLICABLE:IDENTITY_GATE_FAILED", "TOP25_SHARPE": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "PARAMETER_NEEDLE_WARNING": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "RAW_HISTORICAL_RUN_COUNT": len(inventory), "AUTHORITATIVE_COMPARABLE_COUNT": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "EFFECTIVE_TRIAL_COUNT": "NOT_APPLICABLE:IDENTITY_GATE_FAILED", "DEFLATED_SHARPE_RESULT": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "PBO_RESULT": "NOT_APPLICABLE:IDENTITY_GATE_FAILED", "SPA_RESULT": "NOT_APPLICABLE:IDENTITY_GATE_FAILED",
        "2026_EVIDENCE_CLASSIFICATION": "UNKNOWN_FAIL_CLOSED",
        "MOST_DAMAGING_EVIDENCE": classification["most_damaging_evidence"],
        "STRONGEST_SUPPORTING_EVIDENCE": classification["strongest_supporting_evidence"],
        "RECOMMENDED_SINGLE_NEXT_RESEARCH_DIRECTION": classification["recommended_single_next_research_direction"],
        "OUTPUT_DIR": str(out), "FINAL_ARTIFACT_COUNT": len(actual), "HASH_MANIFEST_STATUS": "PASS_HASH_VERIFIED_FAIL_CLOSED_EVIDENCE_SET",
    }
    for key, value in fields.items(): print(f"{key}={value}")
    print("=" * 60)
    return 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUT)
    parser.add_argument("--continuation", action="store_true")
    args = parser.parse_args()
    out = args.output_dir.resolve()
    expected_out = CONTINUATION_OUT.resolve() if args.continuation else OUT.resolve()
    require(out == expected_out, "OUTPUT_ROOT_NOT_AUTHORIZED", out)
    active_task_id = CONTINUATION_TASK_ID if args.continuation else TASK_ID
    out.mkdir(parents=True, exist_ok=True)
    for name in FINAL_FILES:
        path = out / name
        if path.exists():
            path.unlink()

    prereg_sha = sha256_bytes(canonical_json(PREREGISTRATION).encode("utf-8"))
    require(prereg_sha == "72ff5b4a5bee1962f7b80f9a8136ab212ce9fe390c65945ef83c9a2ef1853c36", "PREREGISTRATION_DRIFT", prereg_sha)

    freeze = json.loads(FREEZE_MANIFEST.read_text(encoding="utf-8"))
    frozen_hashes = pd.read_csv(FREEZE_HASHES)
    registry = pd.read_csv(FOUNDATION_REGISTRY, keep_default_na=False)
    auth_rows = registry.loc[registry.logical_name.eq("A2_SUCCESSOR_CONTROL_S1")]
    require(len(auth_rows) == 1 and auth_rows.authoritative_status.iloc[0] == "AUTHORITATIVE_CONTROL", "AUTHORITATIVE_REGISTRY_IDENTITY_FAILURE")
    auth = auth_rows.iloc[0].to_dict()
    path_col = "artifact_path" if "artifact_path" in frozen_hashes else ("absolute_path" if "absolute_path" in frozen_hashes else "path")
    sha_col = "sha256"
    verified = 0
    mismatches = []
    for row in frozen_hashes.itertuples(index=False):
        path = Path(getattr(row, path_col))
        expected = str(getattr(row, sha_col))
        if path.exists() and sha256_file(path) == expected:
            verified += 1
        else:
            mismatches.append({
                "artifact_id": getattr(row, "artifact_id", ""), "role": getattr(row, "role", ""),
                "path": str(path), "expected_sha256": expected,
                "actual_sha256": sha256_file(path) if path.is_file() else "MISSING",
                "immutable": bool(getattr(row, "immutable", False)),
            })
    known_prereg_mismatch = (
        len(mismatches) == 1
        and mismatches[0]["artifact_id"] == "a2_prereg"
        and mismatches[0]["expected_sha256"] == "75f332d09c76e4d4019a85e2a1afd514e2fb6649debfd9cd1ed9414c44c201bb"
        and mismatches[0]["actual_sha256"] == "056a46d191868a2a99e521671ba713c0b38fa948995749c975c56cdad9186d5f"
    )
    if mismatches and not (args.continuation and known_prereg_mismatch):
        return write_identity_fail_closed(out, prereg_sha, freeze, frozen_hashes, verified, mismatches, auth)

    daily_path = BASE / "A2/portfolio_daily.parquet"
    pos_path = BASE / "A2/position_ledger.parquet"
    oof_path = BASE / "A2/oof_predictions.parquet"
    model_path = BASE / "A2/final_full_pre2026_hgb.joblib"
    daily = pd.read_parquet(daily_path).sort_values("execution_date", kind="mergesort").reset_index(drop=True)
    positions = pd.read_parquet(pos_path)
    oof_all = pd.read_parquet(oof_path)
    for frame, column in ((daily, "execution_date"), (positions, "date"), (oof_all, "signal_date")):
        frame[column] = pd.to_datetime(frame[column]).dt.normalize()
    require(len(daily) == 751, "AUTHORITATIVE_DAILY_COUNT_MISMATCH", len(daily))
    require(daily.execution_date.min() == pd.Timestamp("2023-01-04") and daily.execution_date.max() == pd.Timestamp("2025-12-31"), "AUTHORITATIVE_DATE_RANGE_MISMATCH")
    require(len(oof_all) == 313668, "AUTHORITATIVE_PREDICTION_COUNT_MISMATCH", len(oof_all))
    require(set(oof_all.split.unique()) == {"DEVELOPMENT", "CONFIRMATION", "FINAL"}, "OOS_FOLD_LABEL_MISMATCH")
    require(set(oof_all.signal_date.dt.year.unique()) == {2023, 2024, 2025}, "FALSE_2022_OOS_FOLD")
    r = daily.reconstructed_daily_return.to_numpy(float)
    base_m = metrics(r)
    identity = freeze["identity"]["headline_metrics_exact"]
    require(abs(base_m["cagr"] - identity["A2_CAGR"]) <= ABS_TOL, "BASELINE_CAGR_RECONCILIATION")
    require(abs(base_m["sharpe"] - identity["A2_SHARPE"]) <= ABS_TOL, "BASELINE_SHARPE_RECONCILIATION")
    require(abs(base_m["max_drawdown"] - identity["A2_MDD"]) <= ABS_TOL, "BASELINE_MDD_RECONCILIATION")
    nav_recomputed = np.cumprod(1 + r)
    require(float(np.max(np.abs(nav_recomputed - daily.reconstructed_nav.to_numpy(float)))) <= ABS_TOL, "BASELINE_NAV_IDENTITY")
    require(abs(float(daily.reconstructed_turnover.sum()) - 156.04062236916937) <= ABS_TOL, "BASELINE_TURNOVER_IDENTITY")
    require(float(daily[["NAV_ACCOUNTING_IDENTITY_ERROR", "CASH_IDENTITY_ERROR", "POSITION_VALUE_IDENTITY_ERROR", "TURNOVER_IDENTITY_ERROR", "TRANSACTION_COST_IDENTITY_ERROR"]].abs().to_numpy().max()) <= ABS_TOL, "BASELINE_ACCOUNTING_IDENTITY")
    contribution_daily = positions.groupby("date").portfolio_pnl_contribution.sum().reindex(daily.execution_date, fill_value=0).to_numpy(float)
    require(float(np.max(np.abs(contribution_daily - r))) <= ABS_TOL, "POSITION_CONTRIBUTION_IDENTITY")

    stage_meta = {int(x["year"]): x for x in freeze["contracts"]["A2"]["effective_model_vintages"]}
    oof_authority: dict[int, dict[str, Any]] = {}
    for year in [2023, 2024, 2025]:
        part = oof_all.loc[oof_all.signal_date.dt.year.eq(year)].copy()
        meta = stage_meta[year]
        expected_split = {2023: "DEVELOPMENT", 2024: "CONFIRMATION", 2025: "FINAL"}[year]
        require(len(part) == int(meta["prediction_count"]), "OOF_YEAR_ROW_COUNT_MISMATCH", year)
        require(part.signal_date.min() == pd.Timestamp(meta["prediction_min_date"]), "OOF_YEAR_MIN_DATE_MISMATCH", year)
        require(part.signal_date.max() == pd.Timestamp(meta["prediction_max_date"]), "OOF_YEAR_MAX_DATE_MISMATCH", year)
        require(set(part.split) == {expected_split}, "OOF_YEAR_SPLIT_MISMATCH", year)
        require(not part.duplicated(["signal_date", "ticker"]).any(), "OOF_YEAR_DUPLICATE", year)
        require(pd.Timestamp(meta["train_max_date"]) < part.signal_date.min(), "OOF_TRAIN_SIGNAL_BOUNDARY_FAILURE", year)
        require(pd.Timestamp(meta["train_target_end_max"]) < part.signal_date.min(), "OOF_TARGET_MATURITY_BOUNDARY_FAILURE", year)
        oof_authority[year] = {
            "status": "PASS_HASH_DATE_ROWS_SPLIT_PIT_BOUNDARY",
            "prediction_count": len(part), "prediction_min_date": str(part.signal_date.min().date()),
            "prediction_max_date": str(part.signal_date.max().date()), "split": expected_split,
            "train_max_date": meta["train_max_date"], "train_target_end_max": meta["train_target_end_max"],
            "prediction_behavior_sha256": meta["prediction_behavior_sha256"],
        }
    top20_path = BASE / "A2/top20_selections.parquet"
    top20 = pd.read_parquet(top20_path)
    top20["signal_date"] = pd.to_datetime(top20.signal_date).dt.normalize()
    require(not top20.duplicated(["signal_date", "ticker"]).any(), "TOP20_DUPLICATE")
    require(top20.groupby("signal_date").size().eq(20).all(), "TOP20_CARDINALITY")
    expected_top = oof_all.loc[oof_all.a2_rank.le(20), ["signal_date", "ticker"]]
    require(
        set(map(tuple, top20[["signal_date", "ticker"]].to_numpy()))
        == set(map(tuple, expected_top.loc[expected_top.signal_date.isin(top20.signal_date.unique()), ["signal_date", "ticker"]].to_numpy())),
        "RANKING_TO_HOLDINGS_IDENTITY",
    )
    common_path_file = Path(r"D:\us-tech-quant-cache\a2_full_history_synthesis_nextgen_r1\nextgen_portfolio_paths.parquet")
    common = pd.read_parquet(common_path_file)
    common = common.loc[common.model.eq("M0_A2_HGB_AUTH_TEMPORAL")].sort_values("execution_date")
    common["execution_date"] = pd.to_datetime(common.execution_date).dt.normalize()
    require(len(common) == 733, "COMMON_SUPPORT_733_COUNT_MISMATCH", len(common))
    common_check = daily[["execution_date", "reconstructed_daily_return", "reconstructed_nav", "reconstructed_turnover"]].merge(
        common[["execution_date", "net_return", "net_nav", "turnover"]], on="execution_date", validate="one_to_one"
    )
    require(len(common_check) == 733, "COMMON_SUPPORT_733_ALIGNMENT_FAILURE")
    common_errors = {
        "return_max_abs_error": float(np.max(np.abs(common_check.reconstructed_daily_return - common_check.net_return))),
        "nav_max_abs_error": float(np.max(np.abs(common_check.reconstructed_nav - common_check.net_nav))),
        "turnover_max_abs_error": float(np.max(np.abs(common_check.reconstructed_turnover - common_check.turnover))),
    }
    common_support_status = (
        "PASS_EXACT" if max(common_errors.values()) <= ABS_TOL
        else "NONAUTHORITATIVE_DIAGNOSTIC_MISMATCH_NOT_USED_AS_BASELINE"
    )

    benchmark, benchmark_hashes = benchmark_frame(daily.execution_date)
    aligned = daily[["execution_date", "reconstructed_daily_return"]].merge(benchmark, on="execution_date", validate="one_to_one")
    require(len(aligned) == len(daily), "BENCHMARK_ALIGNMENT_ROW_COUNT")
    y = aligned.reconstructed_daily_return.to_numpy(float)

    factor_rows: list[dict[str, Any]] = []
    single = ols_hac(y, aligned.QQQ.to_numpy(float), 5)
    append_metric_row(factor_rows, "A1", "SINGLE_BENCHMARK_REGRESSION", {
        "alpha_daily": single["alpha_daily"], "alpha_annualized": single["alpha_annualized"],
        "alpha_t_ols": single["alpha_t_ols"], "alpha_t_hac": single["alpha_t_hac"], "r2": single["r2"],
        "beta_qqq": single["coefficients"][1], "residual_annualized_return": single["residual_annualized_return"],
        "residual_volatility": single["residual_volatility"], "residual_sharpe": single["residual_sharpe"],
    }, benchmark="QQQ", observations=len(y))
    multi_f = aligned[["QQQ", "SOXX"]].to_numpy(float)
    multi = ols_hac(y, multi_f, 5)
    vifs = vif(multi_f)
    append_metric_row(factor_rows, "A2", "MULTI_BENCHMARK_REGRESSION", {
        "alpha_daily": multi["alpha_daily"], "alpha_annualized": multi["alpha_annualized"],
        "alpha_t_ols": multi["alpha_t_ols"], "alpha_t_hac": multi["alpha_t_hac"], "r2": multi["r2"],
        "beta_qqq": multi["coefficients"][1], "beta_soxx": multi["coefficients"][2],
        "residual_annualized_return": multi["residual_annualized_return"], "residual_volatility": multi["residual_volatility"],
        "residual_sharpe": multi["residual_sharpe"], "vif_qqq": vifs[0], "vif_soxx": vifs[1],
        "condition_number": multi["condition_number"],
    }, benchmark="QQQ+SOXX", observations=len(y))
    for window in [63, 126, 252]:
        for end in range(window, len(aligned) + 1):
            g = aligned.iloc[end-window:end]
            fit = ols_hac(g.reconstructed_daily_return.to_numpy(float), g.QQQ.to_numpy(float), min(5, window // 10))
            append_metric_row(factor_rows, "A3", "ROLLING_QQQ_EXPOSURE", {
                "alpha_annualized": fit["alpha_annualized"], "beta_qqq": fit["coefficients"][1],
                "correlation": float(g.reconstructed_daily_return.corr(g.QQQ)), "residual_sharpe": fit["residual_sharpe"],
            }, benchmark="QQQ", window=window, period_end=g.execution_date.iloc[-1].date(), observations=window)
    for sign_name, mask in (("POSITIVE", aligned.QQQ > 0), ("NEGATIVE", aligned.QQQ < 0)):
        g = aligned.loc[mask]
        beta = float(np.cov(g.reconstructed_daily_return, g.QQQ, ddof=0)[0, 1] / np.var(g.QQQ))
        append_metric_row(factor_rows, "A4", f"QQQ_{sign_name}_SESSIONS", {
            "capture": float(g.reconstructed_daily_return.sum() / g.QQQ.sum()), "conditional_beta": beta,
            "strategy_arithmetic_return": float(g.reconstructed_daily_return.sum()), "benchmark_arithmetic_return": float(g.QQQ.sum()),
        }, benchmark="QQQ", observations=len(g))
    pd.DataFrame(factor_rows).to_csv(out / "factor_beta_decomposition.csv", index=False, encoding="utf-8-sig")

    concentration_rows: list[dict[str, Any]] = []
    contrib = positions.groupby("ticker").portfolio_pnl_contribution.sum().sort_values(ascending=False)
    positive_total = float(contrib.clip(lower=0).sum())
    net_arithmetic = float(r.sum())
    positive_weights = contrib.clip(lower=0) / positive_total
    append_metric_row(concentration_rows, "B1", "SECURITY_CONCENTRATION_SUMMARY", {
        "winner_hhi": float((positive_weights ** 2).sum()), "positive_contribution_total": positive_total,
        "net_arithmetic_return": net_arithmetic, "security_count": len(contrib),
    })
    top_names: dict[int, list[str]] = {}
    pos_by_date = positions.pivot_table(index="date", columns="ticker", values="portfolio_pnl_contribution", aggfunc="sum", fill_value=0).reindex(daily.execution_date, fill_value=0)
    for n in [1, 3, 5, 10, 20]:
        names = contrib.head(n).index.tolist()
        top_names[n] = names
        removed = pos_by_date.reindex(columns=names, fill_value=0).sum(axis=1).to_numpy(float)
        ex = metrics(r - removed)
        append_metric_row(concentration_rows, "B1", f"EX_POST_REMOVE_TOP_{n}_CONTRIBUTORS", ex,
                          contributors="|".join(names), top_contribution=float(contrib.loc[names].sum()),
                          positive_contribution_share=float(contrib.loc[names].sum() / positive_total),
                          net_arithmetic_share=float(contrib.loc[names].sum() / net_arithmetic) if net_arithmetic else None,
                          interpretation="CONTRIBUTION_SUBTRACTION_NOT_TRADABLE_COUNTERFACTUAL")

    dated = pd.Series(r, index=pd.DatetimeIndex(daily.execution_date))
    for label, k in (("BEST_DAY", 1), ("BEST_5_DAYS", 5), ("BEST_10_DAYS", 10)):
        remove_dates = dated.nlargest(k).index
        altered = dated.copy(); altered.loc[remove_dates] = 0.0
        append_metric_row(concentration_rows, "B2", f"EXCLUDE_{label}", metrics(altered), removed_periods="|".join(map(str, remove_dates.date)))
    period_specs = [("BEST_MONTH", "M"), ("BEST_QUARTER", "Q"), ("BEST_CALENDAR_YEAR", "Y")]
    for label, freq in period_specs:
        periods = dated.groupby(dated.index.to_period(freq)).apply(lambda x: float(np.prod(1 + x) - 1))
        best = periods.idxmax()
        altered = dated.copy(); altered.loc[altered.index.to_period(freq) == best] = 0.0
        append_metric_row(concentration_rows, "B2", f"EXCLUDE_{label}", metrics(altered), removed_periods=str(best), removed_period_return=float(periods.loc[best]))
    altered = dated.copy(); altered.loc[altered.index.year == 2023] = 0.0
    append_metric_row(concentration_rows, "B2", "EXCLUDE_2023_DIAGNOSTIC", metrics(altered), evidence_class="OOS_PERIOD_REMOVAL_DIAGNOSTIC")
    append_metric_row(concentration_rows, "B3", "SECTOR_THEME_CONCENTRATION", {}, status="NOT_APPLICABLE", reason="NO_PIT_SAFE_SECTOR_OR_THEME_MAPPING_IN_FROZEN_A2_LINEAGE")

    prices, price_hashes = build_frozen_prices()
    r0f = import_file("a2_falsification_r0f", R0F_SOURCE)
    calendar = pd.DatetimeIndex(prices.loc[prices.ticker.eq("QQQ"), "trade_date"].sort_values().unique())
    last_signal = calendar[-3]
    oof = oof_all.loc[oof_all.signal_date <= last_signal, ["signal_date", "ticker", "a2_prediction", "a2_rank"]].copy()
    require(oof.signal_date.max() == pd.Timestamp("2025-12-29"), "BACKTEST_SIGNAL_END_MISMATCH", oof.signal_date.max())

    implementation_rows: list[dict[str, Any]] = []
    auth_map = target_map(oof, 20)
    replay_cache: dict[tuple[int, int], Any] = {}
    for multiplier in [1.0, 1.5, 2.0, 3.0]:
        bps = int(round(10 * multiplier))
        path = r0f.reconstruct_path(model=f"A2_COST_{multiplier}", target_map=auth_map, qfq=prices, signal_dates=oof.signal_date.unique(), cost_bps=bps)
        m = metrics(path.daily.reconstructed_daily_return)
        total_cost = float(path.daily.reconstructed_transaction_cost.sum())
        gross_edge = float(path.daily.reconstructed_gross_return.sum())
        append_metric_row(implementation_rows, "C1", "COST_STRESS", m, cost_multiplier=multiplier, cost_bps=bps,
                          total_cost=total_cost, total_turnover=float(path.daily.reconstructed_turnover.sum()),
                          fraction_gross_edge_consumed=total_cost / gross_edge if gross_edge else None)
        if multiplier == 1.0:
            require(float(np.max(np.abs(path.daily.reconstructed_daily_return.to_numpy(float) - r))) <= ABS_TOL, "TOP20_REPLAY_RETURN_IDENTITY")
            require(float(np.max(np.abs(path.daily.reconstructed_nav.to_numpy(float) - daily.reconstructed_nav.to_numpy(float)))) <= ABS_TOL, "TOP20_REPLAY_NAV_IDENTITY")
    append_metric_row(implementation_rows, "C2", "EXECUTION_DELAY_PLUS_ONE", {}, status="NOT_APPLICABLE", reason="FROZEN_ENGINE_DEFINES_ONLY_NEXT_SESSION_OPEN;NO_FROZEN_PLUS_ONE_EXECUTABLE_STEP_CONTRACT")
    top_paths: dict[int, Any] = {}
    auth_sets = {d: set(v) for d, v in auth_map.items()}
    for n in [15, 20, 25]:
        mapping = target_map(oof, n)
        path = r0f.reconstruct_path(model=f"A2_TOP{n}", target_map=mapping, qfq=prices, signal_dates=oof.signal_date.unique(), cost_bps=10)
        top_paths[n] = path
        overlaps = [len(set(mapping[d]) & auth_sets[d]) / len(set(mapping[d]) | auth_sets[d]) for d in mapping]
        append_metric_row(implementation_rows, "C3", "TOPN_SENSITIVITY", metrics(path.daily.reconstructed_daily_return),
                          top_n=n, authoritative=(n == 20), total_turnover=float(path.daily.reconstructed_turnover.sum()),
                          mean_jaccard_with_top20=float(np.mean(overlaps)),
                          winner_capture_top5=float(np.mean([len(set(mapping[d]) & set(top_names[5])) / 5 for d in mapping])))
    for n in [1, 3, 5]:
        banned = set(top_names[n])
        work = oof.loc[~oof.ticker.isin(banned)].copy()
        mapping = target_map(work, 20)
        path = r0f.reconstruct_path(model=f"A2_EX_TOP{n}_REFILL", target_map=mapping, qfq=prices, signal_dates=oof.signal_date.unique(), cost_bps=10)
        append_metric_row(concentration_rows, "B4", f"TRADABLE_EX_POST_EXCLUDE_TOP_{n}_REFILL", metrics(path.daily.reconstructed_daily_return),
                          contributors="|".join(top_names[n]), interpretation="EX_POST_EXTREME_SENSITIVITY_NOT_A_NEW_STRATEGY")

    auth_top = oof.sort_values(["signal_date", "a2_rank", "ticker"], kind="mergesort").groupby("signal_date").head(20).groupby("signal_date").ticker.apply(set)
    for level in [0.01, 0.025, 0.05]:
        results = []
        for seed_offset in range(100):
            rng = np.random.default_rng(20260823 + seed_offset)
            std = oof.groupby("signal_date").a2_prediction.transform("std").fillna(0).to_numpy(float)
            score = oof.a2_prediction.to_numpy(float) + level * std * rng.standard_normal(len(oof))
            mapping = target_map(oof, 20, pd.Series(score, index=oof.index))
            path = r0f.reconstruct_path(model=f"A2_NOISE_{level}_{seed_offset}", target_map=mapping, qfq=prices, signal_dates=oof.signal_date.unique(), cost_bps=10)
            m = metrics(path.daily.reconstructed_daily_return)
            overlaps = [len(set(mapping[d]) & auth_top.loc[d]) / 20.0 for d in mapping]
            results.append({"sharpe": m["sharpe"], "cumulative_return": m["cumulative_return"], "overlap": float(np.mean(overlaps))})
        dist = pd.DataFrame(results)
        append_metric_row(implementation_rows, "C4", "SCORE_PERTURBATION_DISTRIBUTION", {
            "median_sharpe": dist.sharpe.median(), "p10_sharpe": dist.sharpe.quantile(.10), "p90_sharpe": dist.sharpe.quantile(.90),
            "median_cumulative_return": dist.cumulative_return.median(), "median_rank_overlap": dist.overlap.median(),
            "median_top20_membership_turnover": 1 - dist.overlap.median(),
            "probability_positive_return": float((dist.cumulative_return > 0).mean()), "probability_sharpe_positive": float((dist.sharpe > 0).mean()),
        }, noise_sigma=level, seed_count=100, seed_start=20260823)
    pd.DataFrame(implementation_rows).to_csv(out / "implementation_stress.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(concentration_rows).to_csv(out / "concentration_and_jackknife.csv", index=False, encoding="utf-8-sig")

    temporal_rows: list[dict[str, Any]] = []
    yearly: dict[int, dict[str, Any]] = {}
    for year, g in aligned.groupby(aligned.execution_date.dt.year):
        m = metrics(g.reconstructed_daily_return)
        yearly[int(year)] = m
        active_qqq = metrics(g.reconstructed_daily_return - g.QQQ)
        residual = single["alpha_daily"] + single["residuals"][g.index.to_numpy()]
        append_metric_row(temporal_rows, "D", "AUTHORITATIVE_OOS_FOLD", m, period=str(year), evidence_class="OOS_EVIDENCE",
                          fold={2023:"DEVELOPMENT", 2024:"CONFIRMATION", 2025:"FINAL"}[int(year)],
                          turnover=float(daily.loc[daily.execution_date.dt.year.eq(year), "reconstructed_turnover"].sum()),
                          cost=float(daily.loc[daily.execution_date.dt.year.eq(year), "reconstructed_transaction_cost"].sum()),
                          qqq_relative_cumulative_return=active_qqq["cumulative_return"], residual_cumulative_return=metrics(residual)["cumulative_return"],
                          winner_concentration=float(positions.loc[positions.date.dt.year.eq(year)].groupby("ticker").portfolio_pnl_contribution.sum().nlargest(5).sum() /
                                                       positions.loc[positions.date.dt.year.eq(year)].groupby("ticker").portfolio_pnl_contribution.sum().clip(lower=0).sum()))
    year_arith = aligned.assign(year=aligned.execution_date.dt.year).groupby("year").reconstructed_daily_return.sum()
    strongest_year = int(year_arith.idxmax())
    strongest_share = float(year_arith.loc[strongest_year] / year_arith.clip(lower=0).sum())
    for year in [2023, 2024, 2025]:
        keep = aligned.execution_date.dt.year.ne(year)
        append_metric_row(temporal_rows, "D", "LEAVE_ONE_OOS_FOLD_OUT", metrics(aligned.loc[keep, "reconstructed_daily_return"]),
                          period=f"EXCLUDE_{year}", evidence_class="OOS_EVIDENCE_DIAGNOSTIC")
        append_metric_row(temporal_rows, "D", "LEAVE_ONE_CALENDAR_YEAR_OUT", metrics(aligned.loc[keep, "reconstructed_daily_return"]),
                          period=f"EXCLUDE_{year}", evidence_class="FULL_HISTORY_DIAGNOSTIC")
    for name, mask in (("QQQ_POSITIVE", aligned.QQQ > 0), ("QQQ_NEGATIVE", aligned.QQQ < 0)):
        g = aligned.loc[mask]
        append_metric_row(temporal_rows, "A5", "REGIME_CONDITIONED", metrics(g.reconstructed_daily_return - g.QQQ), period=name, evidence_class="FIXED_CONCURRENT_REGIME")
    trailing = aligned.QQQ.rolling(63).std(ddof=0).shift(1) * math.sqrt(252)
    threshold = trailing.shift(1).expanding(min_periods=63).median()
    for name, mask in (("HIGH_VOL", trailing > threshold), ("LOW_VOL", trailing <= threshold)):
        valid = mask & trailing.notna() & threshold.notna()
        g = aligned.loc[valid]
        append_metric_row(temporal_rows, "A5", "REGIME_CONDITIONED", metrics(g.reconstructed_daily_return - g.QQQ), period=name, evidence_class="PIT_FIXED_LAGGED_VOL_REGIME")

    for ticker in ["QQQ", "SOXX", "SMH", "SPY"]:
        b = aligned[ticker].to_numpy(float)
        bm = metrics(b)
        active = y - b
        beta = float(np.cov(y, b, ddof=0)[0, 1] / np.var(b))
        neg = b < 0
        append_metric_row(temporal_rows, "F", "SIMPLE_BENCHMARK_CHALLENGE", bm, benchmark=ticker, period="2023-2025",
                          strategy_cagr=base_m["cagr"], strategy_sharpe=base_m["sharpe"], strategy_max_drawdown=base_m["max_drawdown"],
                          turnover=0.0, cost=0.0, correlation=float(np.corrcoef(y, b)[0,1]), beta=beta,
                          active_annualized_return=float(active.mean()*252), information_ratio=float(active.mean()*252/(active.std(ddof=0)*math.sqrt(252))),
                          downside_capture=float(y[neg].sum()/b[neg].sum()))
    pd.DataFrame(temporal_rows).to_csv(out / "temporal_and_benchmark_comparison.csv", index=False, encoding="utf-8-sig")

    inventory = pd.read_csv(RUN_INVENTORY, keep_default_na=False)
    synthesis = json.loads(SYNTHESIS_STATUS.read_text(encoding="utf-8"))
    raw_count = len(inventory)
    authoritative_count = int(synthesis.get("AUTHORITATIVE_RUNS_CLASSIFIED", synthesis.get("authoritative_runs_classified", 80)))
    a_daily = pd.read_parquet(BASE / "A/portfolio_daily.parquet").sort_values("execution_date")
    matrix = np.column_stack([a_daily.reconstructed_daily_return.to_numpy(float), r])
    corr = np.corrcoef(matrix, rowvar=False)
    eigen = np.linalg.eigvalsh(corr)
    effective_trials = float(eigen.sum() ** 2 / np.square(eigen).sum())
    multiple = {
        "task_id": TASK_ID,
        "raw_historical_run_count": raw_count,
        "authoritative_runs_classified": authoritative_count,
        "authoritative_comparable_daily_matrix_count": 2,
        "comparable_candidates": ["A_SIMPLE_CONTROL", "A2_AUTHORITATIVE_CONTROL"],
        "candidate_matrix_date_range": [str(daily.execution_date.min().date()), str(daily.execution_date.max().date())],
        "candidate_return_correlation": corr.tolist(),
        "effective_trial_count_estimate": effective_trials,
        "effective_trial_method": "eigenvalue participation ratio of the 2x2 comparable daily-return correlation matrix",
        "conservative_upper_bound_authoritative": authoritative_count,
        "conservative_upper_bound_raw_history": raw_count,
        "deflated_sharpe_ratio": {
            "status": "NOT_APPLICABLE",
            "reason": "Only two comparable daily paths exist; their cross-sectional Sharpe dispersion cannot reliably estimate the historical trial Sharpe distribution required by DSR.",
            "scenarios": {"OPTIMISTIC": "NOT_APPLICABLE", "CENTRAL": "NOT_APPLICABLE", "CONSERVATIVE": "NOT_APPLICABLE"},
        },
        "pbo": {"status": "NOT_APPLICABLE", "reason": "Two comparable strategies are insufficient for a defensible CSCV/PBO candidate-selection matrix."},
        "spa": {"status": "NOT_APPLICABLE", "reason": "No sufficiently broad same-contract, same-date authoritative candidate matrix; noncomparable nextgen paths were not spliced."},
        "white_reality_check": {"status": "NOT_APPLICABLE", "reason": "Same matrix limitation as SPA; a two-control comparison would not identify the historical search process."},
        "unknown_candidates_included": 0,
        "selection_bias_interpretation": "FAIL_CLOSED_WARNING:418 runs and 80 classified authoritative runs confirm high research multiplicity, while only two paths support dependency estimation and no valid DSR/PBO/SPA correction.",
    }
    (out / "multiple_testing_adjustment.json").write_text(json.dumps(multiple, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")

    impl = pd.DataFrame(implementation_rows)
    conc = pd.DataFrame(concentration_rows)
    ex_top5 = conc.loc[conc.test.eq("EX_POST_REMOVE_TOP_5_CONTRIBUTORS")].iloc[0]
    top5_share = float(ex_top5.positive_contribution_share)
    cost2 = impl.loc[impl.test.eq("COST_STRESS") & impl.cost_multiplier.eq(2.0)].iloc[0]
    cost3 = impl.loc[impl.test.eq("COST_STRESS") & impl.cost_multiplier.eq(3.0)].iloc[0]
    topn = impl.loc[impl.test.eq("TOPN_SENSITIVITY")].set_index("top_n")
    ex_strong = metrics(aligned.loc[aligned.execution_date.dt.year.ne(strongest_year), "reconstructed_daily_return"])
    temporal_warning = bool(strongest_share >= .50 and ex_strong["cumulative_return"] <= 0)
    winner_warning = bool(top5_share >= .75 or float(ex_top5.sharpe) <= 0)
    implementation_warning = bool(float(cost2.cumulative_return) <= 0 or float(cost2.sharpe) <= 0)
    needle_warning = bool((float(topn.loc[15].sharpe) <= 0 and float(topn.loc[25].sharpe) <= 0) or np.median([float(topn.loc[15].sharpe), float(topn.loc[25].sharpe)]) < .5 * float(topn.loc[20].sharpe))
    beta_warning = bool(float(single["residual_sharpe"]) < .5 * float(base_m["sharpe"]) and abs(float(single["alpha_t_hac"])) < 1.96)
    selection_warning = True
    fold_support = sum(1 for m in yearly.values() if m["cumulative_return"] > 0 and m["sharpe"] > 0)
    if base_m["cumulative_return"] <= 0 or fold_support == 0:
        primary = "NO_ROBUST_ECONOMIC_EDGE"
    elif implementation_warning:
        primary = "IMPLEMENTATION_FRAGILE"
    elif winner_warning:
        primary = "CONCENTRATED_WINNER_CAPTURE"
    elif selection_warning:
        primary = "SELECTION_BIAS_SUSPECT"
    elif beta_warning:
        primary = "BETA_ENHANCED_FACTOR_STRATEGY"
    elif fold_support < 3:
        primary = "PROMISING_BUT_INSUFFICIENT_FORWARD"
    else:
        primary = "ROBUST_ALPHA_CANDIDATE"
    flags = []
    if temporal_warning: flags.append("TEMPORAL_CONCENTRATION_WARNING")
    if winner_warning: flags.append("WINNER_CONCENTRATION_WARNING")
    if implementation_warning: flags.append("IMPLEMENTATION_FRAGILE")
    if needle_warning: flags.append("PARAMETER_NEEDLE_WARNING")
    if beta_warning: flags.append("HIGH_TECH_BETA_DEPENDENCE")
    if selection_warning: flags.append("SELECTION_BIAS_UNQUANTIFIED")
    flags.append("2026_EXPOSED_DIAGNOSTIC_ONLY")

    if primary == "SELECTION_BIAS_SUSPECT":
        next_direction = "MODEL_SIMPLIFICATION_AND_FORWARD_ONLY_VALIDATION"
    elif beta_warning:
        next_direction = "BENCHMARK_RELATIVE_RESIDUAL_ALPHA_RESEARCH"
    elif winner_warning:
        next_direction = "EXTREME_WINNER_CAPTURE_ROBUSTNESS_RESEARCH"
    elif needle_warning:
        next_direction = "HOLD_SWITCH_UTILITY_OR_BOUNDARY_CONFIDENCE_RESEARCH"
    elif implementation_warning:
        next_direction = "EXECUTION_REPLACEMENT_GATE_RESEARCH"
    elif temporal_warning:
        next_direction = "REGIME_ROBUSTNESS_RESEARCH"
    else:
        next_direction = "STOP_HISTORICAL_OPTIMIZATION_AND_PRIORITIZE_FROZEN_FORWARD_EVIDENCE"

    most_damaging = "Historical multiplicity is confirmed (418 runs; 80 classified), but only two same-contract paths exist, so DSR/PBO/SPA cannot defensibly adjust selection bias."
    candidates_support = {
        "fold_breadth": f"{fold_support}/3 OOS folds have positive return and Sharpe",
        "cost_3x_sharpe": float(cost3.sharpe),
        "ex_top5_sharpe": float(ex_top5.sharpe),
        "qqq_hac_alpha_t": float(single["alpha_t_hac"]),
    }
    strongest_support = max(candidates_support.items(), key=lambda kv: (kv[0] == "fold_breadth", 0))[1]
    strongest_support = f"{fold_support}/3 frozen OOS folds show positive return and positive Sharpe."
    task_status = (
        "COMPLETE_PATH_AUTHORITATIVE_FALSIFICATION_WITH_PREEXISTING_ANTI_BLOAT_HARD_GATE_FAIL"
        if args.continuation else "COMPLETE_FALSIFICATION_WITH_PREEXISTING_ANTI_BLOAT_HARD_GATE_FAIL"
    )
    strategy_spec_contract = {
        "model_family": freeze["contracts"]["A2"]["model_family"],
        "features": freeze["contracts"]["A2"]["feature_schema"],
        "hyperparameters": freeze["contracts"]["A2"]["hyperparameters"],
        "training_protocol": freeze["contracts"]["A2"]["training_protocol"],
        "model_vintage_protocol": freeze["contracts"]["A2"]["model_vintage_protocol"],
        "oos_vintages": freeze["contracts"]["A2"]["effective_model_vintages"],
        "portfolio": freeze["contracts"]["A"].get("portfolio_mapping", "TOP20_EQUAL_WEIGHT_LONG_ONLY"),
        "top_n": 20, "cost_bps_round_trip": 10,
        "execution": freeze["contracts"]["evaluation"]["signal_execution"],
        "pit_activation": freeze["contracts"]["pit_activation"],
    }
    strategy_spec_id = "A2_SPEC_" + sha256_bytes(canonical_json(strategy_spec_contract).encode("utf-8"))[:16].upper()
    path_components = {
        "oof_predictions": sha256_file(oof_path), "top20_selections": sha256_file(top20_path),
        "portfolio_daily": sha256_file(daily_path), "position_ledger": sha256_file(pos_path),
        "trade_ledger": sha256_file(BASE / "A2/trade_ledger.parquet"),
    }
    historical_path_id = "A2_OOF_PATH_" + sha256_bytes(canonical_json(path_components).encode("utf-8"))[:16].upper()
    lineage_layers = {
        "LAYER_1_A2_STRATEGY_SPEC": {
            "id": strategy_spec_id, "authority": "PASS_CROSS_VERIFIED",
            "cross_verification_sources": ["frozen_baseline_manifest", "run_rebuild_contract", "OOF_metadata", "portfolio_hashes"],
            "contract": strategy_spec_contract,
        },
        "LAYER_2_A2_HISTORICAL_OOF_PATH": {
            "id": historical_path_id, "authority": "PASS",
            "components": path_components, "oof_authority": {str(k): v for k, v in oof_authority.items()},
            "full_authoritative_session_count": 751,
            "common_support_733": {"status": common_support_status, "path": str(common_path_file), **common_errors},
        },
        "LAYER_3_A2_HISTORICAL_FOLD_FITS": {
            "reproducibility": "UNRECOVERABLE",
            "search_passes": 2, "search_status": "STOP_SEARCHING_FOR_THE_MISSING_OBJECT",
            "folds": {
                str(year): {
                    "id": "KNOWN_FROM_METADATA_BINARY_MISSING:" + stage_meta[year]["effective_model_vintage_fingerprint"],
                    "binary_status": "NOT_PERSISTED", "prediction_behavior_sha256": stage_meta[year]["prediction_behavior_sha256"],
                } for year in [2023, 2024, 2025]
            },
        },
        "LAYER_4_A2_CURRENT_DEPLOYMENT_FIT": {
            "id": registry_model_fit_id(auth), "sha256": auth["fitted_model_hash"],
            "role": "FULL_HISTORY_OR_LATEST_DEPLOYMENT_FIT",
            "used_for_historical_oof_predictions": False,
        },
        "A2_PORTFOLIO_CONTRACT_ID": auth["portfolio_contract_hash"],
        "A2_CANONICAL_PIT_ID": auth["data_snapshot_hash"],
        "source_hash_mismatch": {
            "file": str(REPO / "scripts/v22/abcde_a2_nonlinear_alpha_baseline_r1.py"),
            "expected_sha256": "75f332d09c76e4d4019a85e2a1afd514e2fb6649debfd9cd1ed9414c44c201bb",
            "current_sha256": "056a46d191868a2a99e521671ba713c0b38fa948995749c975c56cdad9186d5f",
            "recovery_status": "NOT_RECOVERED_AFTER_2_TARGETED_PASSES",
            "impact": "SPEC_PROVENANCE_PARTIAL",
            "classification_basis": "The file contains prereg/model-construction logic, but frozen manifest independently locks features, HGB hyperparameters, fold schedule, prediction behavior hashes, PIT rules, Top20/cost/execution contracts, and all economic path components.",
        },
    }
    classification = {
        "task_id": active_task_id, "task_status": task_status,
        "preregistration_sha256": prereg_sha, "preregistration": PREREGISTRATION,
        "a2_authoritative_identity_status": "PASS_PATH_AUTHORITY_LAYERED",
        "baseline_reconciliation_status": "PASS_EXACT_1E-12",
        "historical_path_authority": "PASS",
        "strategy_spec_authority": "PASS_CROSS_VERIFIED",
        "fold_model_binary_reproducibility": "UNRECOVERABLE",
        "current_deployment_fit_role": "FULL_HISTORY_OR_LATEST_DEPLOYMENT_FIT",
        "source_hash_mismatch_impact": "SPEC_PROVENANCE_PARTIAL",
        "source_hash_recovery_status": "NOT_RECOVERED_AFTER_2_TARGETED_PASSES",
        "falsification_executed": True,
        "identity_layering": lineage_layers,
        "baseline_identity": {
            "logical_name": auth["logical_name"], "run_id": auth["run_id"], "model_fit_id": registry_model_fit_id(auth),
            "fitted_model_sha256": sha256_file(model_path), "portfolio_contract_sha256": auth["portfolio_contract_hash"],
            "execution_contract_sha256": auth["execution_contract_hash"], "data_snapshot_sha256": auth["data_snapshot_hash"],
            "oof_predictions_sha256": sha256_file(oof_path), "portfolio_daily_sha256": sha256_file(daily_path),
            "position_ledger_sha256": sha256_file(pos_path), "frozen_manifest_sha256": sha256_file(FREEZE_MANIFEST),
            "frozen_hashes_verified": verified, "frozen_hash_count": len(frozen_hashes),
            "date_range": [str(daily.execution_date.min().date()), str(daily.execution_date.max().date())],
            "oos_folds": ["2023_DEVELOPMENT", "2024_CONFIRMATION", "2025_FINAL"], "top_n": 20, "cost_bps_round_trip": 10,
        },
        "primary_robustness_classification": primary, "secondary_flags": flags,
        "warnings": {"temporal": temporal_warning, "winner": winner_warning, "implementation": implementation_warning,
                     "parameter_needle": needle_warning, "beta_dependence": beta_warning, "selection_bias": selection_warning},
        "baseline": base_m,
        "key_results": {
            "qqq_beta": float(single["coefficients"][1]), "qqq_adjusted_alpha_annualized": single["alpha_annualized"],
            "qqq_alpha_hac_t": single["alpha_t_hac"], "residual_sharpe": single["residual_sharpe"],
            "top5_positive_contribution_share": top5_share, "ex_top5_sharpe": float(ex_top5.sharpe),
            "strongest_year": strongest_year, "strongest_year_positive_edge_share": strongest_share,
            "ex_2023_sharpe": float(conc.loc[conc.test.eq("EXCLUDE_2023_DIAGNOSTIC"), "sharpe"].iloc[0]),
            "oos_fold_support": f"{fold_support}/3", "cost_2x_sharpe": float(cost2.sharpe), "cost_3x_sharpe": float(cost3.sharpe),
            "top15_sharpe": float(topn.loc[15].sharpe), "top20_sharpe": float(topn.loc[20].sharpe), "top25_sharpe": float(topn.loc[25].sharpe),
        },
        "2026_evidence_classification": "EXPOSED_DIAGNOSTIC_ONLY",
        "2026_rationale": "A2 was frozen before 2026 inference, but 2026 economics have since been repeatedly viewed in later research; no pristine holdout or preregistration value is claimed.",
        "most_damaging_evidence": most_damaging, "strongest_supporting_evidence": strongest_support,
        "recommended_single_next_research_direction": next_direction,
        "governance": {"model_fit_count": 0, "parameter_selection": False, "2026_used_for_selection": False,
                       "canonical_writes": 0, "broker_actions": 0, "authoritative_contract_mutations": 0,
                       "anti_bloat_status": "FAIL_PREEXISTING_UNREADABLE_REPO_TEMP_HARD_GATE"},
        "source_hashes": {**price_hashes, **benchmark_hashes},
    }
    (out / "robustness_classification.json").write_text(json.dumps(classification, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")

    report = render_report(classification, multiple, factor_rows, concentration_rows, implementation_rows, temporal_rows)
    (out / "final_report.md").write_text(report, encoding="utf-8")

    manifest_rows = []
    for name in FINAL_FILES[:-1]:
        path = out / name
        require(path.exists(), "FINAL_ARTIFACT_MISSING", name)
        manifest_rows.append({"name": name, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    hash_manifest = {
        "task_id": active_task_id, "status": "PASS_HASH_VERIFIED", "artifact_count_including_manifest": 8,
        "artifacts": manifest_rows, "preregistration_sha256": prereg_sha,
        "authoritative_inputs_read_only": True, "canonical_data_read_only": True,
    }
    (out / "hash_manifest.json").write_text(json.dumps(hash_manifest, indent=2, sort_keys=True), encoding="utf-8")
    actual = sorted(p.name for p in out.iterdir() if p.is_file())
    require(actual == sorted(FINAL_FILES), "FINAL_ARTIFACT_SET_FAILURE", actual)
    print_terminal(classification, multiple, len(actual), out)
    return 0


def render_report(c: dict[str, Any], multiple: dict[str, Any], factor_rows: list[dict[str, Any]], concentration_rows: list[dict[str, Any]], implementation_rows: list[dict[str, Any]], temporal_rows: list[dict[str, Any]]) -> str:
    k = c["key_results"]
    b = c["baseline"]
    single = next(x for x in factor_rows if x["test"] == "SINGLE_BENCHMARK_REGRESSION")
    multi = next(x for x in factor_rows if x["test"] == "MULTI_BENCHMARK_REGRESSION")
    conc = pd.DataFrame(concentration_rows)
    impl = pd.DataFrame(implementation_rows)
    temp = pd.DataFrame(temporal_rows)
    folds = temp.loc[temp.test.eq("AUTHORITATIVE_OOS_FOLD")]
    topn = impl.loc[impl.test.eq("TOPN_SENSITIVITY")]
    noise = impl.loc[impl.test.eq("SCORE_PERTURBATION_DISTRIBUTION")]
    costs = impl.loc[impl.test.eq("COST_STRESS")]
    lines = [
        f"# {c['task_id']}", "", "## A. Executive verdict", "",
        f"TASK_STATUS={c['task_status']}", f"A2_AUTHORITATIVE_IDENTITY_STATUS={c['a2_authoritative_identity_status']}", "BASELINE_RECONCILIATION_STATUS=PASS_EXACT_1E-12",
        f"HISTORICAL_PATH_AUTHORITY={c['historical_path_authority']}",
        f"STRATEGY_SPEC_AUTHORITY={c['strategy_spec_authority']}",
        f"FOLD_MODEL_BINARY_REPRODUCIBILITY={c['fold_model_binary_reproducibility']}",
        f"CURRENT_DEPLOYMENT_FIT_ROLE={c['current_deployment_fit_role']}",
        f"SOURCE_HASH_MISMATCH_IMPACT={c['source_hash_mismatch_impact']}",
        f"PRIMARY_ROBUSTNESS_CLASSIFICATION={c['primary_robustness_classification']}", f"SECONDARY_FLAGS={'|'.join(c['secondary_flags'])}",
        f"TEMPORAL_ROBUSTNESS={'WARNING' if c['warnings']['temporal'] else 'SURVIVES_DIAGNOSTIC'}",
        f"WINNER_CONCENTRATION={'WARNING' if c['warnings']['winner'] else 'SURVIVES_DIAGNOSTIC'}",
        f"BENCHMARK_ADJUSTED_EDGE={'BETA_DEPENDENT' if c['warnings']['beta_dependence'] else 'RESIDUAL_EDGE_PRESENT'}",
        f"IMPLEMENTATION_ROBUSTNESS={'FRAGILE' if c['warnings']['implementation'] else 'SURVIVES_FIXED_STRESS'}",
        "MULTIPLE_TESTING_ROBUSTNESS=FAIL_CLOSED_UNQUANTIFIED_SELECTION_RISK",
        "2026_EVIDENCE_CLASSIFICATION=EXPOSED_DIAGNOSTIC_ONLY", "",
        f"A2 最像 `{c['primary_robustness_classification']}`。历史路径本身在 {k['oos_fold_support']} 个冻结 OOS fold 中为正，",
        "但项目级研究多重性远大于可合法构建的同合同收益矩阵，无法用 DSR/PBO/SPA 消除选择偏差。",
        f"最主要失败风险：{c['most_damaging_evidence']}",
        "2026 已被反复查看，因此本报告不给它 holdout 或研究选择价值。", "",
        "## B. Authoritative identity", "",
        f"- Layer 1 strategy spec: `{c['identity_layering']['LAYER_1_A2_STRATEGY_SPEC']['id']}`; authority `PASS_CROSS_VERIFIED`.",
        f"- Layer 2 historical OOF path: `{c['identity_layering']['LAYER_2_A2_HISTORICAL_OOF_PATH']['id']}`; authority `PASS`.",
        "- Layer 3 historical fold binaries: `UNRECOVERABLE`; each fold remains identified by immutable metadata and prediction-behavior hash. This limits fit reproduction but does not invalidate the observed path.",
        f"- Layer 4 current deployment fit: `{c['identity_layering']['LAYER_4_A2_CURRENT_DEPLOYMENT_FIT']['id']}` / `{c['identity_layering']['LAYER_4_A2_CURRENT_DEPLOYMENT_FIT']['sha256']}`; role `FULL_HISTORY_OR_LATEST_DEPLOYMENT_FIT`, not an OOF generator.",
        "- OOF authority: 2023/2024/2025 each PASS row-count, date-range, split-label, duplicate, train-before-OOS, and label-maturity checks.",
        "- The 75f332… prereg source was not recovered after two bounded passes. Impact is `SPEC_PROVENANCE_PARTIAL`: immutable manifests and path components independently lock every economically used contract.",
        f"- Logical/run/model-fit identity: `{c['baseline_identity']['logical_name']}` / `{c['baseline_identity']['run_id']}` / `{c['baseline_identity']['model_fit_id']}`.",
        f"- Fitted model SHA256: `{c['baseline_identity']['fitted_model_sha256']}` (supplemental full-pre-2026 artifact; frozen OOF economics use three year vintages).",
        f"- Frozen OOF predictions SHA256: `{c['baseline_identity']['oof_predictions_sha256']}`; daily path SHA256: `{c['baseline_identity']['portfolio_daily_sha256']}`.",
        f"- Portfolio contract SHA256: `{c['baseline_identity']['portfolio_contract_sha256']}`; execution contract registry SHA256: `{c['baseline_identity']['execution_contract_sha256']}`.",
        f"- Freeze manifest SHA256: `{c['baseline_identity']['frozen_manifest_sha256']}`; verified {c['baseline_identity']['frozen_hashes_verified']}/{c['baseline_identity']['frozen_hash_count']} frozen hashes.",
        "- OOS folds are exactly 2023 DEVELOPMENT, 2024 CONFIRMATION, 2025 FINAL. No 2022 OOS fold was created.",
        f"- The later 733-row common-support path status is `{c['identity_layering']['LAYER_2_A2_HISTORICAL_OOF_PATH']['common_support_733']['status']}` and was not substituted for the 751-row authoritative baseline.",
        f"- Preregistration SHA256: `{c['preregistration_sha256']}`. It was frozen before new robustness outcomes.", "",
        "## C. Baseline economics", "",
        f"751 sessions, 2023-01-04 through 2025-12-31; cumulative return {b['cumulative_return']:.6f}, CAGR {b['cagr']:.6f}, Sharpe {b['sharpe']:.6f}, MaxDD {b['max_drawdown']:.6f}.",
        "Return, NAV, turnover, cost/accounting identities, and position-contribution arithmetic reconcile at 1e-12. Top20, equal weight, long-only, 10 bps round-trip, next-session-open execution are unchanged.", "",
        "## D. Factor/beta decomposition", "",
        f"QQQ beta {single['beta_qqq']:.4f}; annualized intercept {single['alpha_annualized']:.4f}; OLS t {single['alpha_t_ols']:.3f}; Newey-West t {single['alpha_t_hac']:.3f}; R² {single['r2']:.3f}; residual Sharpe {single['residual_sharpe']:.3f}.",
        f"QQQ+SOXX annualized intercept {multi['alpha_annualized']:.4f}; HAC t {multi['alpha_t_hac']:.3f}; betas QQQ {multi['beta_qqq']:.3f}, SOXX {multi['beta_soxx']:.3f}; VIFs {multi['vif_qqq']:.2f}/{multi['vif_soxx']:.2f}; condition number {multi['condition_number']:.1f}.",
        "The factor CSV includes every preregistered 63/126/252-session rolling estimate and up/down capture. No specification was selected after outcome review.", "",
        "## E. Security and time concentration", "",
    ]
    for n in [1,3,5,10]:
        row = conc.loc[conc.test.eq(f"EX_POST_REMOVE_TOP_{n}_CONTRIBUTORS")].iloc[0]
        lines.append(f"- Top{n}: positive-contribution share {row.positive_contribution_share:.3f}; net arithmetic share {row.net_arithmetic_share:.3f}; ex-contribution Sharpe {row.sharpe:.3f}; names `{row.contributors}`.")
    lines += [
        f"- Strongest year {k['strongest_year']} supplies {k['strongest_year_positive_edge_share']:.3f} of positive yearly arithmetic edge; ex-2023 Sharpe {k['ex_2023_sharpe']:.3f}.",
        f"- Worst fold: {folds.sort_values('sharpe').iloc[0].period}, Sharpe {folds.sort_values('sharpe').iloc[0].sharpe:.3f}; OOS support {k['oos_fold_support']}.",
        "- Static subtraction is not a tradable counterfactual. Separate ex-post exclude-and-refill paths are reported only as extreme sensitivity, never as replacement strategies.",
        "- Sector/theme concentration is NOT_APPLICABLE because the frozen lineage lacks PIT-safe sector/theme metadata.", "",
        "## F. Implementation stress", "",
    ]
    for _, row in costs.iterrows():
        lines.append(f"- Cost {row.cost_multiplier:.1f}x: cumulative {row.cumulative_return:.4f}, CAGR {row.cagr:.4f}, Sharpe {row.sharpe:.3f}, MaxDD {row.max_drawdown:.3f}.")
    for _, row in topn.iterrows():
        lines.append(f"- Top{int(row.top_n)}: cumulative {row.cumulative_return:.4f}, Sharpe {row.sharpe:.3f}, MaxDD {row.max_drawdown:.3f}, turnover {row.total_turnover:.2f}, mean Jaccard vs Top20 {row.mean_jaccard_with_top20:.3f}.")
    for _, row in noise.iterrows():
        lines.append(f"- Noise {row.noise_sigma:g}σ (100 fixed seeds): median Sharpe {row.median_sharpe:.3f}, p10/p90 {row.p10_sharpe:.3f}/{row.p90_sharpe:.3f}, median overlap {row.median_rank_overlap:.3f}, P(return>0) {row.probability_positive_return:.3f}.")
    lines += [
        "- +1 execution step: NOT_APPLICABLE; the frozen engine has no authoritative extra-delay contract, so none was invented.",
        f"- PARAMETER_NEEDLE_WARNING={str(c['warnings']['parameter_needle']).lower()}.", "",
        "## G. Multiple-testing adjustment", "",
        f"418 historical runs and {multiple['authoritative_runs_classified']} classified authoritative runs are confirmed. Only two same-contract, same-date daily paths (A and A2) form the legal matrix; effective trials={multiple['effective_trial_count_estimate']:.3f} by eigenvalue participation ratio.",
        "DSR=NOT_APPLICABLE (two paths cannot estimate the historical trial Sharpe distribution). PBO=NOT_APPLICABLE (insufficient candidate matrix). SPA/WRC=NOT_APPLICABLE (noncomparable lineages and date ranges were not spliced).",
        "This is adverse evidence, not exculpatory missingness: selection bias remains unquantified and is treated fail-closed.", "",
        "## H. Benchmark challenge", "",
    ]
    for _, row in temp.loc[temp.test.eq("SIMPLE_BENCHMARK_CHALLENGE")].iterrows():
        lines.append(f"- {row.benchmark}: CAGR {row.cagr:.4f}, Sharpe {row.sharpe:.3f}, MaxDD {row.max_drawdown:.3f}; A2 active annualized return {row.active_annualized_return:.4f}, IR {row.information_ratio:.3f}, beta {row.beta:.3f}, downside capture {row.downside_capture:.3f}.")
    lines += [
        "A2 has substantial turnover and concentration; its complexity is supported economically only to the extent that active/residual results and stress survival remain positive. The report does not promote it over a benchmark.", "",
        "## I. 2026 evidence status", "",
        "`EXPOSED_DIAGNOSTIC_ONLY`. A2 was frozen before 2026 inference, but later researchers repeatedly viewed 2026 economics. Those observations have `NO_SELECTION_VALUE` and `NO_PREREGISTRATION_VALUE`; no 2026 return enters this report's main tests or thresholds.", "",
        "## J. Falsification verdict", "",
        "1. A2 may remain the authoritative research control as an identity anchor, but not as proven robust alpha.",
        f"2. Independent alpha evidence is {'material but not selection-bias-cleared' if not c['warnings']['beta_dependence'] else 'insufficient after benchmark adjustment'}.",
        f"3. Beta-enhanced factor strategy is {'a plausible description' if c['warnings']['beta_dependence'] else 'not the primary diagnosis from the fixed QQQ test'}.",
        f"4. Extreme-winner dependence warning: {str(c['warnings']['winner']).lower()}.",
        f"5. 2023 dependence warning: {str(c['warnings']['temporal']).lower()}; ex-2023 Sharpe {k['ex_2023_sharpe']:.3f}.",
        f"6. 2x/3x cost Sharpes are {k['cost_2x_sharpe']:.3f}/{k['cost_3x_sharpe']:.3f}; implementation fragility={str(c['warnings']['implementation']).lower()}.",
        "7. Multiple-testing credibility cannot be reliably quantified and is downgraded fail-closed because the legal matrix has only two paths.",
        f"8. Most damaging: {c['most_damaging_evidence']}",
        f"9. Strongest support: {c['strongest_supporting_evidence']}",
        f"10. Single next direction: `{c['recommended_single_next_research_direction']}`.", "",
        "No model was fit, no parameter/portfolio choice was made, no 2026 outcome was used for selection, and no canonical/frozen artifact or broker path was modified.",
        "Anti-Bloat hard gate remains failed solely because of the pre-existing unreadable repo temp object; this task created no large repo artifact or local venv.",
    ]
    return "\n".join(lines) + "\n"


def print_terminal(c: dict[str, Any], multiple: dict[str, Any], count: int, out: Path) -> None:
    k, b = c["key_results"], c["baseline"]
    if c["task_id"] == CONTINUATION_TASK_ID:
        print("=" * 60); print("A2_IDENTITY_RECOVERY_AND_FALSIFICATION_CONTINUATION_R1_FINAL"); print("=" * 60); print()
        fields = {
            "TASK_STATUS": c["task_status"],
            "HISTORICAL_PATH_AUTHORITY": c["historical_path_authority"],
            "STRATEGY_SPEC_AUTHORITY": c["strategy_spec_authority"],
            "FOLD_MODEL_BINARY_REPRODUCIBILITY": c["fold_model_binary_reproducibility"],
            "CURRENT_DEPLOYMENT_FIT_ROLE": c["current_deployment_fit_role"],
            "OOF_2023_AUTHORITY": c["identity_layering"]["LAYER_2_A2_HISTORICAL_OOF_PATH"]["oof_authority"]["2023"]["status"],
            "OOF_2024_AUTHORITY": c["identity_layering"]["LAYER_2_A2_HISTORICAL_OOF_PATH"]["oof_authority"]["2024"]["status"],
            "OOF_2025_AUTHORITY": c["identity_layering"]["LAYER_2_A2_HISTORICAL_OOF_PATH"]["oof_authority"]["2025"]["status"],
            "SOURCE_HASH_MISMATCH_IMPACT": c["source_hash_mismatch_impact"],
            "SOURCE_HASH_RECOVERY_STATUS": c["source_hash_recovery_status"],
            "BASELINE_RECONCILIATION_STATUS": c["baseline_reconciliation_status"],
            "FALSIFICATION_EXECUTED": str(c["falsification_executed"]).upper(),
            "PRIMARY_ROBUSTNESS_CLASSIFICATION": c["primary_robustness_classification"],
            "SECONDARY_FLAGS": "|".join(c["secondary_flags"]),
            "HISTORICAL_CUM_RETURN": b["cumulative_return"], "HISTORICAL_SHARPE": b["sharpe"], "HISTORICAL_MAX_DRAWDOWN": b["max_drawdown"],
            "QQQ_BETA": k["qqq_beta"], "QQQ_ADJUSTED_ALPHA": k["qqq_adjusted_alpha_annualized"], "RESIDUAL_SHARPE": k["residual_sharpe"],
            "TOP5_SECURITY_CONTRIBUTION_SHARE": k["top5_positive_contribution_share"], "EX_TOP5_SHARPE": k["ex_top5_sharpe"],
            "STRONGEST_YEAR": k["strongest_year"], "STRONGEST_YEAR_EDGE_SHARE": k["strongest_year_positive_edge_share"], "EX_2023_SHARPE": k["ex_2023_sharpe"],
            "OOS_FOLD_SUPPORT": k["oos_fold_support"], "COST_2X_SHARPE": k["cost_2x_sharpe"], "COST_3X_SHARPE": k["cost_3x_sharpe"],
            "TOP15_SHARPE": k["top15_sharpe"], "TOP20_SHARPE": k["top20_sharpe"], "TOP25_SHARPE": k["top25_sharpe"],
            "PARAMETER_NEEDLE_WARNING": str(c["warnings"]["parameter_needle"]).lower(),
            "RAW_HISTORICAL_RUN_COUNT": multiple["raw_historical_run_count"],
            "AUTHORITATIVE_COMPARABLE_COUNT": multiple["authoritative_comparable_daily_matrix_count"],
            "EFFECTIVE_TRIAL_COUNT": multiple["effective_trial_count_estimate"],
            "DEFLATED_SHARPE_RESULT": "NOT_APPLICABLE:ONLY_2_COMPARABLE_PATHS",
            "PBO_RESULT": "NOT_APPLICABLE:INSUFFICIENT_MATRIX", "SPA_RESULT": "NOT_APPLICABLE:INSUFFICIENT_COMPARABLE_MATRIX",
            "2026_EVIDENCE_CLASSIFICATION": c["2026_evidence_classification"],
            "MOST_DAMAGING_STRATEGY_EVIDENCE": c["most_damaging_evidence"],
            "STRONGEST_SUPPORTING_STRATEGY_EVIDENCE": c["strongest_supporting_evidence"],
            "NEXT_RESEARCH_DIRECTION": c["recommended_single_next_research_direction"],
            "OUTPUT_DIR": str(out), "FINAL_ARTIFACT_COUNT": count, "HASH_MANIFEST_STATUS": "PASS_HASH_VERIFIED",
        }
        for key, value in fields.items(): print(f"{key}={value}")
        print("=" * 60)
        return
    print("=" * 60); print(f"{TASK_ID}_FINAL"); print("=" * 60); print()
    fields = {
        "TASK_STATUS": c["task_status"], "A2_AUTHORITATIVE_IDENTITY_STATUS": "PASS", "BASELINE_RECONCILIATION_STATUS": "PASS_EXACT_1E-12",
        "PRIMARY_CLASSIFICATION": c["primary_robustness_classification"], "SECONDARY_FLAGS": "|".join(c["secondary_flags"]),
        "HISTORICAL_CUM_RETURN": b["cumulative_return"], "HISTORICAL_SHARPE": b["sharpe"], "HISTORICAL_MAX_DRAWDOWN": b["max_drawdown"],
        "QQQ_BETA": k["qqq_beta"], "QQQ_ADJUSTED_ALPHA": k["qqq_adjusted_alpha_annualized"], "RESIDUAL_SHARPE": k["residual_sharpe"],
        "TOP5_SECURITY_CONTRIBUTION_SHARE": k["top5_positive_contribution_share"], "EX_TOP5_SHARPE": k["ex_top5_sharpe"],
        "STRONGEST_YEAR": k["strongest_year"], "STRONGEST_YEAR_EDGE_SHARE": k["strongest_year_positive_edge_share"], "EX_2023_SHARPE": k["ex_2023_sharpe"],
        "OOS_FOLD_SUPPORT": k["oos_fold_support"], "COST_2X_SHARPE": k["cost_2x_sharpe"], "COST_3X_SHARPE": k["cost_3x_sharpe"],
        "TOP15_SHARPE": k["top15_sharpe"], "TOP20_SHARPE": k["top20_sharpe"], "TOP25_SHARPE": k["top25_sharpe"],
        "PARAMETER_NEEDLE_WARNING": str(c["warnings"]["parameter_needle"]).lower(),
        "RAW_HISTORICAL_RUN_COUNT": multiple["raw_historical_run_count"], "AUTHORITATIVE_COMPARABLE_COUNT": multiple["authoritative_comparable_daily_matrix_count"],
        "EFFECTIVE_TRIAL_COUNT": multiple["effective_trial_count_estimate"],
        "DEFLATED_SHARPE_RESULT": "NOT_APPLICABLE:ONLY_2_COMPARABLE_PATHS", "PBO_RESULT": "NOT_APPLICABLE:INSUFFICIENT_MATRIX", "SPA_RESULT": "NOT_APPLICABLE:INSUFFICIENT_COMPARABLE_MATRIX",
        "2026_EVIDENCE_CLASSIFICATION": "EXPOSED_DIAGNOSTIC_ONLY", "MOST_DAMAGING_EVIDENCE": c["most_damaging_evidence"],
        "STRONGEST_SUPPORTING_EVIDENCE": c["strongest_supporting_evidence"], "RECOMMENDED_SINGLE_NEXT_RESEARCH_DIRECTION": c["recommended_single_next_research_direction"],
        "OUTPUT_DIR": str(out), "FINAL_ARTIFACT_COUNT": count, "HASH_MANIFEST_STATUS": "PASS_HASH_VERIFIED",
    }
    for key, value in fields.items(): print(f"{key}={value}")
    print("=" * 60)


if __name__ == "__main__":
    raise SystemExit(main())
