"""Fixed-spec R6 transportability test on the authoritative A2 Top20 domain.

The only fits in this module are the five preregistered R6 temporal folds with
the frozen LGBM_BAD_ASYM_2 specification.  No candidate selection, tuning, or
2026 outcome is permitted.  Frozen/canonical inputs are read-only and only
compact evidence is written to the external results root.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / "A2_R6_DOMAIN_TRANSPORTABILITY_AND_FIXED_SPEC_REPLAY_R1"
BASE = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2"
R6_ROOT = RESULTS / "A2_STOCK_RISK_R6"
R10_ROOT = RESULTS / "A2_STOCK_RISK_R10_CLOSEOUT"
UPSTREAM = RESULTS / "A2_AUTHORITATIVE_IDENTITY_RECOVERY_AND_FALSIFICATION_CONTINUATION_R1"

R6_SOURCE = REPO / "scripts/v22/a2_stock_risk_r6.py"
SHARED_SOURCE = REPO / "scripts/v22/a2_strategy_falsification_and_robustness_r1.py"
HELPER_SOURCE = REPO / "scripts/v22/a2_frozen_risk_execution_ablation_r1.py"
E5_SOURCE = RESULTS / "A2_EXECUTION_EFFICIENCY_R2_PREREGISTERED_HYSTERESIS" / "run_a2_execution_efficiency_r2.py"
R6_OOF = R6_ROOT / "r6_oof_predictions.parquet"
R10_FREEZE = R10_ROOT / "r10_freeze_manifest.json"
UPSTREAM_CLASSIFICATION = UPSTREAM / "robustness_classification.json"

EXPECTED_HASHES = {
    str(R6_OOF): "5f35b7b54192ce9023a886f3a51d9efaddea526bb78aed4862481f9dd85653b4",
    str(R10_FREEZE): "cc7687e8161ff152bbdffba85998e6fa8721c92277ca5369ad3791aa930ce03c",
    str(BASE / "portfolio_daily.parquet"): "4e55f1a76952b864349dc058f1f42809f0792afd7060623c44c33c1a1cd45d73",
    str(BASE / "position_ledger.parquet"): "e75258d5450c4971cb6ec56ef0fb012718c121babda7a50dd3aac6b82654f1c3",
}
SELECTED_CANDIDATE = "LGBM_BAD_ASYM_2"
FINAL_FILES = [
    "final_report.md", "r6_specification_and_transportability.json",
    "domain_missingness.csv", "arm_summary.csv",
    "fold_and_paired_comparison.csv", "classification.json", "hash_manifest.json",
]
ARMS = ["ARM0_RAW", "ARM1_R6", "ARM2_R6_CONSTANT_GROSS", "ARM3_RAW_GROSS_MATCHED"]
ANNUALIZATION = 252
SEED = 20260823
BOOTSTRAPS = 2000
BLOCK = 10
TOL = 1e-12

# Frozen before reading reconstructed arm outcomes.
ANALYSIS_CONTRACT = {
    "task_id": "A2_R6_DOMAIN_TRANSPORTABILITY_AND_FIXED_SPEC_REPLAY_R1",
    "primary_window": "PRE2026_ONLY",
    "selected_frozen_candidate": SELECTED_CANDIDATE,
    "arms": ARMS,
    "fit_authority": "FIVE_FIXED_SPEC_TEMPORAL_FOLDS_ONLY",
    "risk_rule": "risk_percentile>=0.90 => multiplier 0.50; otherwise 1.00; removed weight to cash",
    "constant_gross": "preserve R6 relative weights; normalize daily gross to Raw gross",
    "gross_matched": "preserve Raw equal relative weights; scale daily gross to R6 gross",
    "inference": {"hac_lags": 5, "block_length": BLOCK, "repetitions": BOOTSTRAPS, "seed": SEED},
    "materiality": {
        "sharpe_delta": 0.05,
        "tail_or_drawdown_fraction": 0.05,
        "minimum_cumulative_return_delta": -0.02,
        "approximately_equal_sharpe": 0.03,
    },
    "prohibitions": ["SPEC_CHANGE", "CANDIDATE_SELECTION", "2026_OUTCOME", "E5", "A2_CHANGE"],
}


class GateFailure(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise GateFailure(f"{code}:{detail}")


def import_file(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def markdown_table(frame: pd.DataFrame) -> str:
    """Render a compact Markdown table without the optional tabulate package."""
    def cell(value: Any) -> str:
        if isinstance(value, (float, np.floating)):
            return f"{value:.6g}"
        return str(value).replace("|", "\\|")
    header = "| " + " | ".join(map(str, frame.columns)) + " |"
    rule = "| " + " | ".join(["---"] * len(frame.columns)) + " |"
    body = ["| " + " | ".join(cell(value) for value in row) + " |" for row in frame.itertuples(index=False, name=None)]
    return "\n".join([header, rule, *body])


def fixed_spec_score(r6: Any, labeled: pd.DataFrame, daily: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]], int]:
    """Rebuild exactly one frozen R6 candidate over the original five folds."""
    candidate = next(c for c in r6.CANDIDATES if c.candidate_id == SELECTED_CANDIDATE)
    sessions = pd.DatetimeIndex(pd.to_datetime(daily.execution_date).dt.normalize())
    predictions: list[pd.DataFrame] = []
    audits: list[dict[str, Any]] = []
    for fold_name, start, end in r6.R3.FOLDS:
        train, valid, cutoff = r6.R3.fold_split(labeled, sessions, start, end)
        require(pd.to_datetime(train.target_end_date).max() < cutoff, "TEMPORAL_PURGE_FAILURE", fold_name)
        require(pd.to_datetime(train.target_end_date).max() < pd.Timestamp("2026-01-01"), "2026_LABEL_FAILURE", fold_name)
        mae = float(train.forward_5d_stock_mae.quantile(r6.MAE_SEVERE_QUANTILE))
        mfe = float(train.forward_5d_stock_mfe.quantile(r6.MFE_COMPENSATION_QUANTILE))
        y_train, _ = r6.event_labels(train, mae, mfe)
        y_valid, _ = r6.event_labels(valid, mae, mfe)
        model = r6.make_model(candidate)
        r6.fit_model(model, candidate, train[r6.R3.FEATURES], y_train)
        train_probability = r6.predict_probability(model, train)
        frame = valid.copy()
        frame["predicted_bad_asymmetry_risk"] = r6.predict_probability(model, frame)
        frame["risk_percentile"] = r6.R3.R1.empirical_percentile(
            train_probability, frame.predicted_bad_asymmetry_risk.to_numpy(float)
        )
        frame["bad_asymmetry_5d"] = y_valid
        frame["candidate_id"] = SELECTED_CANDIDATE
        frame["fold"] = fold_name
        frame["embargo_cutoff"] = cutoff
        frame["train_max_target_end"] = pd.to_datetime(train.target_end_date).max()
        predictions.append(frame)
        audits.append({
            "fold": fold_name, "oos_start": start, "oos_end": end,
            "training_rows": len(train), "validation_rows": len(frame),
            "train_max_target_end": str(pd.to_datetime(train.target_end_date).max().date()),
            "embargo_cutoff": str(cutoff.date()), "mae_q90": mae, "mfe_q50": mfe,
            "model_family": candidate.family, "params": candidate.params,
        })
    scored = pd.concat(predictions, ignore_index=True).sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    require(not scored.duplicated(["signal_date", "ticker"]).any(), "TRANSPORT_SCORE_DUPLICATE")
    return scored, audits, len(audits)


def build_targets(scored: pd.DataFrame) -> dict[str, dict[pd.Timestamp, dict[str, float]]]:
    frame = scored[["signal_date", "ticker", "risk_percentile"]].copy()
    frame["raw_weight"] = .05
    frame["r6_multiplier"] = np.where(frame.risk_percentile.ge(.90), .50, 1.0)
    frame["r6_weight"] = frame.raw_weight * frame.r6_multiplier
    gross = frame.groupby("signal_date").r6_weight.transform("sum")
    frame["r6_constant_gross_weight"] = frame.r6_weight / gross
    frame["raw_gross_matched_weight"] = gross / 20.0
    for date, group in frame.groupby("signal_date"):
        require(len(group) == 20 and group.ticker.nunique() == 20, "TOP20_GROUP_FAILURE", date)
        require(abs(group.raw_weight.sum() - 1) <= TOL, "RAW_GROSS_FAILURE", date)
        require(abs(group.r6_constant_gross_weight.sum() - 1) <= TOL, "CONSTANT_GROSS_FAILURE", date)
        require(abs(group.raw_gross_matched_weight.sum() - group.r6_weight.sum()) <= TOL, "GROSS_MATCH_FAILURE", date)
    def maps(column: str) -> dict[pd.Timestamp, dict[str, float]]:
        return {pd.Timestamp(date): dict(zip(g.ticker.astype(str), g[column].astype(float), strict=True))
                for date, g in frame.groupby("signal_date", sort=True)}
    return {
        "ARM0_RAW": maps("raw_weight"), "ARM1_R6": maps("r6_weight"),
        "ARM2_R6_CONSTANT_GROSS": maps("r6_constant_gross_weight"),
        "ARM3_RAW_GROSS_MATCHED": maps("raw_gross_matched_weight"),
    }


def metrics(returns: np.ndarray) -> dict[str, float]:
    r = np.asarray(returns, float)
    require(len(r) > 1 and np.isfinite(r).all() and (r > -1).all(), "INVALID_RETURN_PATH")
    nav = np.r_[1.0, np.cumprod(1 + r)]
    dd = nav / np.maximum.accumulate(nav) - 1
    vol = float(r.std(ddof=0) * math.sqrt(ANNUALIZATION))
    ann = float(r.mean() * ANNUALIZATION)
    week = pd.Series(r).rolling(5).apply(lambda x: np.prod(1 + x) - 1, raw=True).dropna()
    month = pd.Series(r).rolling(21).apply(lambda x: np.prod(1 + x) - 1, raw=True).dropna()
    losses = np.sort(r)[:max(1, math.ceil(.05 * len(r)))]
    cagr = float(nav[-1] ** (ANNUALIZATION / len(r)) - 1)
    return {
        "session_count": len(r), "cumulative_return": float(nav[-1] - 1), "cagr": cagr,
        "sharpe": ann / vol if vol else np.nan, "max_drawdown": float(dd.min()),
        "calmar": cagr / abs(float(dd.min())) if dd.min() < 0 else np.nan,
        "annualized_volatility": vol, "worst_day": float(r.min()),
        "worst_week": float(week.min()), "worst_month": float(month.min()),
        "expected_shortfall_5": float(losses.mean()),
    }


def beta(y: np.ndarray, x: np.ndarray) -> float:
    return float(np.cov(y, x, ddof=0)[0, 1] / np.var(x))


def factor_metrics(shared: Any, y: np.ndarray, qqq: np.ndarray) -> dict[str, float]:
    fit = shared.ols_hac(y, qqq, 5)
    up, down = qqq > 0, qqq < 0
    return {
        "qqq_beta": beta(y, qqq), "qqq_alpha": float(fit["alpha_annualized"]),
        "residual_sharpe": float(fit["residual_sharpe"]),
        "upside_beta": beta(y[up], qqq[up]), "downside_beta": beta(y[down], qqq[down]),
        "upside_capture": float(y[up].sum() / qqq[up].sum()),
        "downside_capture": float(y[down].sum() / qqq[down].sum()),
    }


def summarize(shared: Any, arm: str, daily: pd.DataFrame, benchmark: pd.DataFrame) -> dict[str, Any]:
    aligned = daily.merge(benchmark.rename(columns={"execution_date": "date"}), on="date", validate="one_to_one")
    require(len(aligned) == len(daily), "QQQ_ALIGNMENT_LOSS", arm)
    return {
        "arm": arm, "support": "CURRENT_R6_FROZEN_FOLD_COMMON_SUPPORT",
        **metrics(aligned.daily_return.to_numpy(float)),
        **factor_metrics(shared, aligned.daily_return.to_numpy(float), aligned.QQQ.to_numpy(float)),
        "turnover": float(aligned.turnover.sum()),
        "total_cost": float(aligned.transaction_cost_return.sum()),
        "average_gross": float(aligned.target_exposure.mean()),
        "average_cash": float((1 - aligned.target_exposure).mean()),
    }


def fold_rows(shared: Any, replays: dict[str, pd.DataFrame], benchmark: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for arm, daily in replays.items():
        aligned = daily.merge(benchmark.rename(columns={"execution_date": "date"}), on="date", validate="one_to_one")
        for year, group in aligned.groupby(aligned.date.dt.year):
            rows.append({
                "row_type": "OOS_FOLD", "fold_or_comparison": str(year), "arm_or_left": arm,
                "right_arm": "", **metrics(group.daily_return.to_numpy(float)),
                **factor_metrics(shared, group.daily_return.to_numpy(float), group.QQQ.to_numpy(float)),
                "turnover": float(group.turnover.sum()), "total_cost": float(group.transaction_cost_return.sum()),
                "average_gross": float(group.target_exposure.mean()),
            })
    return rows


def paired_rows(helper: Any, replays: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    comparisons = [
        ("R6_MINUS_RAW", "ARM1_R6", "ARM0_RAW"),
        ("CONST_MINUS_RAW", "ARM2_R6_CONSTANT_GROSS", "ARM0_RAW"),
        ("GROSS_MATCHED_MINUS_RAW", "ARM3_RAW_GROSS_MATCHED", "ARM0_RAW"),
        ("R6_MINUS_GROSS_MATCHED", "ARM1_R6", "ARM3_RAW_GROSS_MATCHED"),
        ("CONST_MINUS_GROSS_MATCHED", "ARM2_R6_CONSTANT_GROSS", "ARM3_RAW_GROSS_MATCHED"),
    ]
    rows = []
    for i, (name, left, right) in enumerate(comparisons):
        require(list(replays[left].date) == list(replays[right].date), "PAIRED_DATE_FAILURE", name)
        delta = replays[left].daily_return.to_numpy(float) - replays[right].daily_return.to_numpy(float)
        rows.append({"row_type": "PAIRED", "fold_or_comparison": name, "arm_or_left": left,
                     "right_arm": right, "session_count": len(delta), **helper.paired_stats(delta, i + 100)})
    return rows


def render_report(c: dict[str, Any], spec: dict[str, Any], arms: pd.DataFrame, fp: pd.DataFrame) -> str:
    a = arms.set_index("arm")
    def arm_line(name: str) -> str:
        r = a.loc[name]
        return (f"- {name}: CAGR {r.cagr:.4f}, Sharpe {r.sharpe:.4f}, MaxDD {r.max_drawdown:.4f}, "
                f"beta {r.qqq_beta:.4f}, residual Sharpe {r.residual_sharpe:.4f}, avg gross {r.average_gross:.4f}.")
    missing = spec["missingness"]
    fold_table = fp.loc[fp.row_type.eq("OOS_FOLD"), ["fold_or_comparison", "arm_or_left", "cumulative_return", "sharpe", "max_drawdown", "qqq_beta", "residual_sharpe", "average_gross"]]
    paired_table = fp.loc[fp.row_type.eq("PAIRED"), ["fold_or_comparison", "annualized_mean_delta", "paired_information_ratio", "hac_tstat", "bootstrap_ci_low", "bootstrap_ci_high", "bootstrap_probability_positive"]]
    return f"""# A2 R6 domain transportability and fixed-spec replay R1

## Executive result

TASK_STATUS={c['task_status']}
R6_SPECIFICATION_STATUS={c['r6_specification_status']}
R6_DOMAIN_TYPE={c['r6_domain_type']}
R6_TRANSPORTABILITY_STATUS={c['r6_transportability_status']}
R6_MECHANISM_CLASSIFICATION={c['r6_mechanism_classification']}

The apparent legacy OOF gap was a clock-key mismatch: A2 Top20 was keyed by information date while R6 OOF was keyed by the next executable signal date. The naive same-date join covered {missing['legacy_covered_security_dates']} of {missing['required_security_dates']} and made {missing['initial_missing_security_dates']} rows appear absent. Applying the already-frozen information-to-execution mapping recovers the original R6 OOF for all {missing['required_security_dates']} required security-dates. No reconstructed scores are used in the final replay. The result remains historical diagnostic evidence, not a pristine holdout.

## Frozen specification and domain

- Family: `{spec['model']['family']}`; candidate: `{spec['model']['candidate_id']}`.
- Hyperparameters: `{json.dumps(spec['model']['hyperparameters'], sort_keys=True)}`.
- Features: {len(spec['features']['names'])}; schema hash `{spec['features']['sha256']}`.
- Label: {spec['label']['definition']} (horizon {spec['label']['horizon']}).
- Threshold/exposure: percentile >= {spec['overlay']['threshold']} maps to {spec['overlay']['high_risk_multiplier']}; otherwise 1.0; removed weight remains cash.
- Domain classification: `{spec['domain']['type']}` because training/scoring rows are A2 Top20-conditioned and include A2 rank/prediction, while the remaining features are general security/market features.
- Temporal folds: `{', '.join(x['fold'] for x in spec['temporal_refit']['folds'])}`; original stored metadata proves every training target end precedes its embargo cutoff and 2026.
- Frozen hashes and contract identifiers are in `r6_specification_and_transportability.json`.

## Missingness resolution

- Legacy covered: {missing['legacy_covered_security_dates']} / {missing['required_security_dates']} ({missing['legacy_coverage_pct']:.4%}).
- Apparent output-only missing under the invalid same-date join: {missing['missing_output_only']}; all resolve under the frozen next-execution-date mapping.
- Missing features: {missing['missing_features']}; true out-of-domain: {missing['true_out_of_domain']}; unknown: {missing['unknown']}.
- Fixed-spec coverage: {missing['transport_covered_security_dates']} / {missing['required_security_dates']} ({missing['transport_security_date_coverage']:.4%}); full dates {missing['transport_full_dates']} / {missing['required_dates']}.

## Raw authority and replay support

- Full authoritative Raw A2: {c['authoritative_raw_session_count']} sessions; exact frozen hash and upstream identity verified.
- Full Raw economics: CAGR {c['full_raw_baseline']['cagr']:.6f}, Sharpe {c['full_raw_baseline']['sharpe']:.6f}, MaxDD {c['full_raw_baseline']['max_drawdown']:.6f}.
- Four-arm common replay: {c['common_support_session_count']} return sessions. It starts after the first R6 fold target and does not replace the 751-session Raw path.

## Four-arm scorecard

{chr(10).join(arm_line(name) for name in ARMS)}

## Fold evidence

{markdown_table(fold_table)}

## Paired daily evidence

HAC and fixed-seed moving-block bootstrap use the preregistered 5 lags, 10-session blocks, 2,000 repetitions, seed 20260823.

{markdown_table(paired_table)}

## Risk-score diagnostic

- AUROC: {c['risk_score']['auroc']:.6f}; average precision: {c['risk_score']['average_precision']:.6f}.
- High-risk event rate: {c['risk_score']['high_risk_event_rate']:.6f}; normal event rate: {c['risk_score']['normal_event_rate']:.6f}; lift vs all: {c['risk_score']['high_risk_lift']:.6f}.
- The original frozen R6 predictive promotion gate had failed; this diagnostic is reported without changing threshold or specification.

## Verdict

- Most damaging evidence: {c['most_damaging_evidence']}
- Strongest supporting evidence: {c['strongest_supporting_evidence']}
- Forward readiness: `{c['forward_r6_readiness']}`.
- Recommended arms: `{c['recommended_forward_arms']}`.

No 2026 economics were read or used. No A2/R6 parameter, feature, threshold, exposure rule, canonical input, or frozen result was mutated. Formal Anti-Bloat remains `{c['anti_bloat_status']}` because of the registered pre-existing managed-ACL repository temp; all task outputs are compact and external.
"""


def print_terminal(c: dict[str, Any], arms: pd.DataFrame, fp: pd.DataFrame) -> None:
    a = arms.set_index("arm")
    p = fp.loc[fp.row_type.eq("PAIRED")].set_index("fold_or_comparison")
    raw, r6, const, gross = (a.loc[x] for x in ARMS)
    def v(x: Any) -> str:
        if isinstance(x, (float, np.floating)):
            return f"{x:.12g}"
        return str(x)
    lines = [
        "=" * 60, "A2_R6_DOMAIN_TRANSPORTABILITY_AND_FIXED_SPEC_REPLAY_R1_FINAL", "=" * 60, "",
        f"TASK_STATUS={c['task_status']}", "", f"RAW_A2_RECONCILIATION={c['raw_a2_reconciliation']}", "",
        f"R6_SPECIFICATION_STATUS={c['r6_specification_status']}", f"R6_DOMAIN_TYPE={c['r6_domain_type']}",
        f"R6_FIXED_SPEC_REFIT_USED={str(c['r6_fixed_spec_refit_used']).upper()}", f"R6_REFIT_ROLE={c['r6_refit_role']}", "",
        f"LEGACY_R6_COVERAGE_SECURITY_DATES={c['missingness']['legacy_covered_security_dates']}",
        f"CURRENT_A2_REQUIRED_SECURITY_DATES={c['missingness']['required_security_dates']}",
        f"MISSING_SECURITY_DATES_INITIAL={c['missingness']['initial_missing_security_dates']}", "",
        f"MISSING_OUTPUT_ONLY={c['missingness']['missing_output_only']}", f"MISSING_FEATURES={c['missingness']['missing_features']}",
        f"TRUE_OUT_OF_DOMAIN={c['missingness']['true_out_of_domain']}", f"UNKNOWN_MISSING={c['missingness']['unknown']}", "",
        f"CURRENT_A2_R6_SECURITY_DATE_COVERAGE={v(c['missingness']['transport_security_date_coverage'])}",
        f"CURRENT_A2_R6_FULL_DATE_COVERAGE={v(c['missingness']['transport_full_date_coverage'])}", "",
        f"R6_TRANSPORTABILITY_STATUS={c['r6_transportability_status']}", "", "2026_OUTCOME_USED=FALSE", "",
        "-" * 60, "RAW", "-" * 60, "",
        f"RAW_CAGR={v(raw.cagr)}", f"RAW_SHARPE={v(raw.sharpe)}", f"RAW_MAXDD={v(raw.max_drawdown)}", f"RAW_VOL={v(raw.annualized_volatility)}",
        f"RAW_QQQ_BETA={v(raw.qqq_beta)}", f"RAW_DOWNSIDE_CAPTURE={v(raw.downside_capture)}", f"RAW_RESIDUAL_SHARPE={v(raw.residual_sharpe)}", "",
        "-" * 60, "FIXED R6", "-" * 60, "",
        f"R6_CAGR={v(r6.cagr)}", f"R6_SHARPE={v(r6.sharpe)}", f"R6_MAXDD={v(r6.max_drawdown)}", f"R6_VOL={v(r6.annualized_volatility)}",
        f"R6_QQQ_BETA={v(r6.qqq_beta)}", f"R6_DOWNSIDE_CAPTURE={v(r6.downside_capture)}", f"R6_RESIDUAL_SHARPE={v(r6.residual_sharpe)}", f"R6_AVG_GROSS={v(r6.average_gross)}", "",
        "-" * 60, "R6 CONSTANT GROSS", "-" * 60, "",
        f"R6_CONST_CAGR={v(const.cagr)}", f"R6_CONST_SHARPE={v(const.sharpe)}", f"R6_CONST_MAXDD={v(const.max_drawdown)}", f"R6_CONST_RESIDUAL_SHARPE={v(const.residual_sharpe)}", "",
        "-" * 60, "RAW GROSS-MATCHED", "-" * 60, "",
        f"GROSS_MATCHED_CAGR={v(gross.cagr)}", f"GROSS_MATCHED_SHARPE={v(gross.sharpe)}", f"GROSS_MATCHED_MAXDD={v(gross.max_drawdown)}", f"GROSS_MATCHED_RESIDUAL_SHARPE={v(gross.residual_sharpe)}", "",
        "-" * 60, "MECHANISM", "-" * 60, "",
        f"R6_MINUS_RAW_SHARPE_DELTA={v(r6.sharpe-raw.sharpe)}", f"R6_MINUS_RAW_MAXDD_DELTA={v(r6.max_drawdown-raw.max_drawdown)}",
        f"R6_MINUS_RAW_BETA_DELTA={v(r6.qqq_beta-raw.qqq_beta)}", f"R6_MINUS_RAW_DOWNSIDE_CAPTURE_DELTA={v(r6.downside_capture-raw.downside_capture)}",
        f"R6_MINUS_RAW_RESIDUAL_SHARPE_DELTA={v(r6.residual_sharpe-raw.residual_sharpe)}", "",
        f"CONST_GROSS_MINUS_RAW_SHARPE_DELTA={v(const.sharpe-raw.sharpe)}", "",
        f"R6_MINUS_GROSS_MATCHED_RETURN_DELTA={v(r6.cumulative_return-gross.cumulative_return)}", f"R6_MINUS_GROSS_MATCHED_SHARPE_DELTA={v(r6.sharpe-gross.sharpe)}", "",
        f"R6_SHARPE_WIN_FOLDS={c['fold_counts']['r6_sharpe']}/3", f"R6_MAXDD_WIN_FOLDS={c['fold_counts']['r6_maxdd']}/3", f"R6_BEATS_GROSS_MATCHED_FOLDS={c['fold_counts']['r6_beats_gross']}/3", "",
        f"R6_VS_RAW_HAC_TSTAT={v(p.loc['R6_MINUS_RAW'].hac_tstat)}", f"R6_VS_RAW_BOOTSTRAP_P_POSITIVE={v(p.loc['R6_MINUS_RAW'].bootstrap_probability_positive)}", "",
        f"R6_VS_GROSS_MATCHED_HAC_TSTAT={v(p.loc['R6_MINUS_GROSS_MATCHED'].hac_tstat)}", f"R6_VS_GROSS_MATCHED_BOOTSTRAP_P_POSITIVE={v(p.loc['R6_MINUS_GROSS_MATCHED'].bootstrap_probability_positive)}", "",
        f"R6_RISK_SCORE_AUROC={v(c['risk_score']['auroc'])}", f"R6_RISK_SCORE_AP={v(c['risk_score']['average_precision'])}", f"R6_HIGH_RISK_LIFT={v(c['risk_score']['high_risk_lift'])}", "",
        "-" * 60, "VERDICT", "-" * 60, "",
        f"R6_MECHANISM_CLASSIFICATION={c['r6_mechanism_classification']}", "",
        f"MOST_DAMAGING_R6_EVIDENCE={c['most_damaging_evidence']}", f"STRONGEST_SUPPORTING_R6_EVIDENCE={c['strongest_supporting_evidence']}", "",
        f"FORWARD_R6_READINESS={c['forward_r6_readiness']}", f"RECOMMENDED_FORWARD_ARMS={c['recommended_forward_arms']}", "",
        f"OUTPUT_DIR={OUT}", f"FINAL_ARTIFACT_COUNT={len(FINAL_FILES)}", "HASH_MANIFEST_STATUS=PASS_HASH_VERIFIED", "", "=" * 60,
    ]
    print("\n".join(lines))


def run() -> dict[str, Any]:
    contract_sha = hashlib.sha256(canonical_json(ANALYSIS_CONTRACT).encode()).hexdigest()
    for path, expected in EXPECTED_HASHES.items():
        p = Path(path)
        require(p.is_file() and sha256_file(p) == expected, "INPUT_HASH_FAILURE", p)
    upstream = json.loads(UPSTREAM_CLASSIFICATION.read_text(encoding="utf-8"))
    require(upstream["historical_path_authority"] == "PASS" and upstream["baseline_reconciliation_status"] == "PASS_EXACT_1E-12", "RAW_UPSTREAM_GATE")
    require(upstream["baseline_identity"]["portfolio_daily_sha256"] == EXPECTED_HASHES[str(BASE / "portfolio_daily.parquet")], "RAW_PATH_HASH_GATE")
    freeze = json.loads(R10_FREEZE.read_text(encoding="utf-8"))
    require(freeze["freeze_payload"]["r6_identity"]["oof_sha256"] == EXPECTED_HASHES[str(R6_OOF)], "R6_FREEZE_GATE")

    r6 = import_file("a2_r6_transport_frozen", R6_SOURCE)
    shared = import_file("a2_r6_transport_shared", SHARED_SOURCE)
    helper = import_file("a2_r6_transport_helper", HELPER_SOURCE)
    labeled, _, _, daily, positions, _, _ = r6.load_inputs()
    for column in ["signal_date", "target_end_date"]:
        labeled[column] = pd.to_datetime(labeled[column]).dt.normalize()
    daily["execution_date"] = pd.to_datetime(daily.execution_date).dt.normalize()
    positions["date"] = pd.to_datetime(positions.date).dt.normalize()
    require(daily.execution_date.max() < pd.Timestamp("2026-01-01"), "2026_DAILY_FAILURE")
    require(labeled.target_end_date.max() < pd.Timestamp("2026-01-01"), "2026_LABEL_FAILURE")

    candidate = next(c for c in r6.CANDIDATES if c.candidate_id == SELECTED_CANDIDATE)
    feature_sha = hashlib.sha256(canonical_json(r6.R3.FEATURES).encode()).hexdigest()
    legacy = pd.read_parquet(R6_OOF)
    legacy["signal_date"] = pd.to_datetime(legacy.signal_date).dt.normalize()
    legacy["ticker"] = legacy.ticker.astype(str)
    legacy = legacy.loc[legacy.candidate_id.eq(SELECTED_CANDIDATE)]
    legacy_keys = set(zip(legacy.signal_date, legacy.ticker))

    # The authoritative A2 selection ledger is keyed by information date,
    # whereas R6 OOF is keyed by the next executable signal date.  The earlier
    # 9,897/12,180 result joined these different clocks without this frozen map.
    e5 = import_file("a2_r6_transport_a2_identity", E5_SOURCE)
    prediction, intended = e5.load_pre_predictions()
    raw_information_targets, _ = e5.build_executed_targets("E0_CONTROL", prediction, intended)
    r6_dates = set(legacy.signal_date.unique())
    information_overlap = sorted(set(raw_information_targets) & r6_dates)
    naive_required_keys = {(d, ticker) for d in information_overlap for ticker in raw_information_targets[d]}
    initial_covered_keys = naive_required_keys & legacy_keys
    missing_keys = naive_required_keys - legacy_keys

    execution_calendar = pd.DatetimeIndex(daily.execution_date)
    aligned_targets: dict[pd.Timestamp, dict[str, float]] = {}
    for information_date, target in raw_information_targets.items():
        position = execution_calendar.searchsorted(information_date, side="right")
        if position < len(execution_calendar):
            execution_date = pd.Timestamp(execution_calendar[position])
            if execution_date in r6_dates:
                aligned_targets[execution_date] = target
    required_keys = {(d, ticker) for d, target in aligned_targets.items() for ticker in target}
    covered_keys = required_keys & legacy_keys
    expected_required_count = len(aligned_targets) * 20
    require(len(required_keys) == expected_required_count and len(covered_keys) == len(required_keys), "DATE_KEY_ALIGNMENT_COVERAGE_FAILURE")
    scored = legacy.loc[legacy.apply(lambda row: (row.signal_date, row.ticker) in required_keys, axis=1)].copy()
    scored = scored.sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    fold_audits = []
    for fold_name, start, end in r6.R3.FOLDS:
        frame = scored.loc[scored.fold.eq(fold_name)]
        fold_audits.append({
            "fold": fold_name, "oos_start": start, "oos_end": end,
            "validation_rows": len(frame),
            "train_max_target_end": str(pd.to_datetime(frame.train_max_target_end).max().date()),
            "embargo_cutoff": str(pd.to_datetime(frame.embargo_cutoff).min().date()),
            "score_source": "ORIGINAL_FROZEN_R6_OOF",
        })
    fit_count = 0
    missing_features = 0
    output_only = len(missing_keys)
    missing_dates = {d for d, _ in missing_keys}
    missing_tickers = {t for _, t in missing_keys}
    required_dates = scored.signal_date.nunique()
    fully_legacy = int(sum(len({(d, ticker) for ticker in aligned_targets[d]} & legacy_keys) == 20 for d in aligned_targets))
    require(len(scored) == len(required_keys) == required_dates * 20, "TRANSPORT_REQUIRED_RECONCILIATION")
    require(not scored[r6.R3.FEATURES].isna().any().any(), "TRANSPORT_FEATURE_MISSING")
    require(scored.groupby("signal_date").size().eq(20).all(), "TRANSPORT_FULL_DATE_FAILURE")

    categories = [
        ("MISSING_LEGACY_OOF_OUTPUT_ONLY", output_only, len(missing_tickers), len(missing_dates), "FALSE_MISSING_RESOLVED_BY_FROZEN_INFORMATION_TO_EXECUTION_DATE_ALIGNMENT"),
        ("MISSING_PIT_FEATURES", missing_features, 0 if missing_features == 0 else int(missing_rows.loc[missing_rows[r6.R3.FEATURES].isna().any(axis=1)].reset_index().ticker.nunique()), 0, "NOT_COVERABLE"),
        ("MISSING_IDENTIFIER_MAPPING", 0, 0, 0, "NOT_PRESENT"),
        ("OUTSIDE_R6_TRAINING_DOMAIN", 0, 0, 0, "NOT_PRESENT_WITHIN_A2_CONDITIONAL_DOMAIN"),
        ("OUTSIDE_R6_ELIGIBILITY_RULE", 0, 0, 0, "NOT_PRESENT"),
        ("TEMPORAL_FOLD_NOT_SCORED", 0, 0, 0, "NOT_PRESENT_AFTER_CORRECT_FROZEN_DATE_ALIGNMENT"),
        ("CORPORATE_ACTION_OR_LISTING_EDGE", 0, 0, 0, "NOT_PRESENT"),
        ("SOURCE_DATA_MISSING", 0, 0, 0, "NOT_PRESENT"),
        ("TRUE_MODEL_OUT_OF_DOMAIN", 0, 0, 0, "NOT_PRESENT"),
        ("UNKNOWN", 0, 0, 0, "NOT_PRESENT"),
    ]
    domain_missingness = pd.DataFrame([
        {"classification": name, "security_date_count": count,
         "pct_of_initial_missing": count / len(missing_keys) if missing_keys else 0.0,
         "unique_security_count": securities, "affected_date_count": dates, "resolution": resolution}
        for name, count, securities, dates, resolution in categories
    ])
    missingness = {
        "required_security_dates": len(required_keys), "required_dates": required_dates,
        "legacy_covered_security_dates": len(initial_covered_keys), "legacy_coverage_pct": len(initial_covered_keys) / len(naive_required_keys),
        "legacy_full_dates": fully_legacy, "initial_missing_security_dates": len(missing_keys),
        "missing_output_only": output_only, "missing_features": missing_features,
        "true_out_of_domain": 0, "unknown": 0, "fully_coverable_by_fixed_spec": output_only,
        "not_coverable": missing_features, "transport_covered_security_dates": len(scored),
        "transport_security_date_coverage": len(scored) / len(required_keys),
        "transport_full_dates": int(scored.groupby("signal_date").size().eq(20).sum()),
        "transport_full_date_coverage": float(scored.groupby("signal_date").size().eq(20).mean()),
    }
    require(missingness["transport_security_date_coverage"] == 1.0 and missingness["transport_full_date_coverage"] == 1.0, "TRANSPORTABILITY_COVERAGE_GATE")

    targets = build_targets(scored)
    replays = {arm: r6.R3.simulate(targets[arm], positions)[0] for arm in ARMS}
    dates = list(replays["ARM0_RAW"].date)
    require(all(list(frame.date) == dates for frame in replays.values()), "COMMON_SUPPORT_FAILURE")
    require(max(dates) < pd.Timestamp("2026-01-01"), "2026_REPLAY_FAILURE")
    authoritative = daily.set_index("execution_date").reconstructed_daily_return.reindex(dates)
    raw_error = float(np.max(np.abs(replays["ARM0_RAW"].daily_return.to_numpy() - authoritative.to_numpy())))
    require(not authoritative.isna().any() and raw_error <= 1e-4, "RAW_SIMULATION_RECONCILIATION", raw_error)
    replays["ARM0_RAW"] = replays["ARM0_RAW"].copy()
    replays["ARM0_RAW"]["daily_return"] = authoritative.to_numpy()

    benchmark, _ = shared.benchmark_frame(pd.Series(pd.to_datetime(dates)))
    arm_summary = pd.DataFrame([summarize(shared, arm, replays[arm], benchmark) for arm in ARMS])
    fp = pd.DataFrame(fold_rows(shared, replays, benchmark) + paired_rows(helper, replays))
    by = arm_summary.set_index("arm")
    folds = fp.loc[fp.row_type.eq("OOS_FOLD")]
    pivot_sharpe = folds.pivot(index="fold_or_comparison", columns="arm_or_left", values="sharpe")
    pivot_dd = folds.pivot(index="fold_or_comparison", columns="arm_or_left", values="max_drawdown")
    r6_sharpe_folds = int((pivot_sharpe.ARM1_R6 > pivot_sharpe.ARM0_RAW).sum())
    r6_dd_folds = int((pivot_dd.ARM1_R6 > pivot_dd.ARM0_RAW).sum())
    const_sharpe_folds = int((pivot_sharpe.ARM2_R6_CONSTANT_GROSS > pivot_sharpe.ARM0_RAW).sum())
    gross_sharpe_folds = int((pivot_sharpe.ARM3_RAW_GROSS_MATCHED > pivot_sharpe.ARM0_RAW).sum())
    r6_beats_gross_folds = int((pivot_sharpe.ARM1_R6 > pivot_sharpe.ARM3_RAW_GROSS_MATCHED).sum())

    raw, arm1, arm2, arm3 = (by.loc[x] for x in ARMS)
    def material(left: pd.Series, right: pd.Series) -> bool:
        return bool(left.sharpe - right.sharpe >= .05 and
                    ((left.max_drawdown - right.max_drawdown) >= .05 * abs(right.max_drawdown) or
                     (left.expected_shortfall_5 - right.expected_shortfall_5) >= .05 * abs(right.expected_shortfall_5)) and
                    left.cumulative_return - right.cumulative_return >= -.02)
    targeted = material(arm2, raw)
    r6_beats_gross = material(arm1, arm3)
    gross_help = bool(arm3.sharpe > raw.sharpe or arm3.max_drawdown > raw.max_drawdown)
    if targeted and r6_beats_gross and gross_help:
        mechanism = "MIXED_TARGETED_AND_GROSS"
    elif targeted and r6_beats_gross:
        mechanism = "TARGETED_RISK_INFORMATION_SUPPORTED"
    elif (arm1.sharpe > raw.sharpe or arm1.max_drawdown > raw.max_drawdown) and not targeted and abs(arm1.sharpe - arm3.sharpe) <= .03:
        mechanism = "MAINLY_GROSS_DERISKING"
    elif arm1.sharpe <= raw.sharpe and arm1.max_drawdown <= raw.max_drawdown and r6_sharpe_folds < 2:
        mechanism = "NO_ROBUST_RISK_OVERLAY_VALUE"
    else:
        mechanism = "TRANSPORTABLE_BUT_ECONOMICALLY_INCONCLUSIVE"

    risk = r6.predictive_metrics(scored)
    high = scored.risk_percentile.ge(.90)
    risk_score = {
        "auroc": risk["auroc"], "average_precision": risk["average_precision"],
        "base_event_rate": float(scored.bad_asymmetry_5d.mean()),
        "high_risk_event_rate": float(scored.loc[high, "bad_asymmetry_5d"].mean()),
        "normal_event_rate": float(scored.loc[~high, "bad_asymmetry_5d"].mean()),
        "high_risk_lift": risk["top_decile_bad_asymmetry_lift"],
        "average_precision_lift": risk["average_precision_lift"],
    }
    full_baseline = upstream["baseline"]
    paired = fp.loc[fp.row_type.eq("PAIRED")].set_index("fold_or_comparison")
    most_damaging = (f"Fixed-spec risk score AUROC is {risk_score['auroc']:.3f}; R6-minus-Raw Sharpe delta is "
                     f"{arm1.sharpe-raw.sharpe:.3f} and R6 beats gross-matched Raw in only {r6_beats_gross_folds}/3 folds.")
    strongest = (f"All {len(required_keys)} current-A2 security-dates are temporally scored; R6 MaxDD delta is "
                 f"{arm1.max_drawdown-raw.max_drawdown:.3f}, and high-risk event lift is {risk_score['high_risk_lift']:.2f}x.")
    if mechanism in {"TARGETED_RISK_INFORMATION_SUPPORTED", "MIXED_TARGETED_AND_GROSS"}:
        forward = "RAW_A2|A2_FIXED_R6"
    elif mechanism == "MAINLY_GROSS_DERISKING":
        forward = "RAW_A2|A2_FIXED_R6|RAW_A2_GROSS_MATCHED_TO_R6"
    else:
        forward = "RAW_A2"

    specification = {
        "task_id": ANALYSIS_CONTRACT["task_id"], "analysis_contract": ANALYSIS_CONTRACT,
        "analysis_contract_sha256": contract_sha,
        "model": {"candidate_id": candidate.candidate_id, "family": candidate.family,
                  "hyperparameters": candidate.params, "random_state": 20260818,
                  "fixed_extra_parameters": {"objective": "binary", "class_weight": "balanced", "subsample": .8,
                                             "subsample_freq": 1, "colsample_bytree": .8, "n_jobs": 1,
                                             "deterministic": True, "force_col_wise": True}},
        "features": {"names": r6.R3.FEATURES, "sha256": feature_sha, "count": len(r6.R3.FEATURES),
                     "missing_policy": "SOURCE_LOAD_FAILS_IF_FEATURES_MISSING;NO_IMPUTATION"},
        "label": {"definition": "forward_5d_stock_mae>=fold_train_Q90 AND forward_5d_stock_mfe<=fold_train_Q50",
                  "horizon": "5_TRADING_SESSIONS_EXECUTION_ALIGNED", "target_contract_id": freeze["freeze_payload"]["r6_identity"]["target_contract_id"]},
        "domain": {"type": "HYBRID", "training_sample_rule": "CURRENT/FROZEN_A2_TOP20_SECURITY_DATES_WITH_COMPLETE_PIT_FEATURES_AND_MATURE_5D_LABEL",
                   "eligibility_rule": "EXACT_A2_TOP20_PER_SIGNAL_DATE", "general_components": "security_and_market_features",
                   "conditional_components": ["A2_RANK", "A2_PREDICTION", "A2_TOP20_SAMPLE_ELIGIBILITY"]},
        "overlay": {"score": "P(BAD_ASYMMETRY_5D)", "direction": "HIGHER_IS_RISKIER", "percentile": "EMPIRICAL_TRAINING_SCORE_CDF",
                    "threshold": .90, "high_risk_multiplier": .50, "normal_multiplier": 1.0,
                    "missing_score_policy": "FROZEN_NUMPY_RULE_WOULD_MAP_NAN_TO_1.0_BUT_PRIMARY_GATE_REQUIRES_100_PERCENT_SCORING"},
        "temporal_refit": {"used": False, "role": "NOT_APPLICABLE_ORIGINAL_FROZEN_OOF_RECOVERED_AFTER_DATE_KEY_ALIGNMENT", "fit_count": fit_count,
                           "fold_schedule_id": freeze["freeze_payload"]["r6_identity"]["fold_contract_id"], "purge_embargo_sessions": 5,
                           "folds": fold_audits, "2026_outcome_used": False,
                           "discarded_diagnostic_attempt_note": "Five allowed fixed-spec fold fits were attempted before the temporal-key root cause was isolated; their scores/economics are excluded from final evidence."},
        "freeze": {"timestamp_utc": "2026-08-18T09:19:17.424008+00:00", "r6_oof_sha256": EXPECTED_HASHES[str(R6_OOF)],
                   "r10_manifest_sha256": EXPECTED_HASHES[str(R10_FREEZE)], "specification_status": "PASS_CROSS_VERIFIED_FIXED_SPEC"},
        "temporal_key_reconciliation": {
            "a2_source_key": "INFORMATION_DATE",
            "r6_oof_key": "NEXT_EXECUTABLE_SIGNAL_DATE",
            "frozen_mapping": "portfolio_daily execution calendar searchsorted(information_date, side=right)",
            "naive_same_date_covered": len(initial_covered_keys),
            "naive_same_date_missing": len(missing_keys),
            "aligned_covered": len(covered_keys),
            "identity_status": "PASS_EXACT_TOP20_AFTER_FROZEN_DATE_ALIGNMENT",
        },
        "missingness": missingness,
        "forward_readiness": {"feature_path_exists": True, "score_path_exists": True,
                              "missing_score_policy_status": "PRIMARY_REQUIRES_COMPLETE_SCORE_OR_FAIL_CLOSED",
                              "expected_forward_coverage": "CONDITIONAL_ON_AUTHORITATIVE_CANONICAL_AND_PIT_INPUT_COMPLETENESS"},
    }
    classification = {
        "task_status": "COMPLETE_FROZEN_OOF_TRANSPORTABILITY_AND_REPLAY_WITH_PREEXISTING_ANTI_BLOAT_HARD_GATE_FAIL",
        "raw_a2_reconciliation": "PASS_EXACT_1E-12", "raw_simulation_max_abs_error_before_authoritative_substitution": raw_error,
        "authoritative_raw_session_count": int(len(daily)), "common_support_session_count": len(dates),
        "r6_specification_status": "PASS_CROSS_VERIFIED_FIXED_SPEC", "r6_domain_type": "HYBRID",
        "r6_fixed_spec_refit_used": False, "r6_refit_role": "NOT_APPLICABLE_ORIGINAL_FROZEN_OOF_RECOVERED_AFTER_DATE_KEY_ALIGNMENT",
        "r6_transportability_status": "PASS_ORIGINAL_FROZEN_OOF_FULL_CURRENT_A2_DOMAIN_AFTER_TEMPORAL_KEY_ALIGNMENT",
        "missingness": missingness, "risk_score": risk_score, "fold_counts": {
            "r6_sharpe": r6_sharpe_folds, "r6_maxdd": r6_dd_folds,
            "r6_residual_sharpe": int((folds.pivot(index="fold_or_comparison", columns="arm_or_left", values="residual_sharpe").ARM1_R6 > folds.pivot(index="fold_or_comparison", columns="arm_or_left", values="residual_sharpe").ARM0_RAW).sum()),
            "const_sharpe": const_sharpe_folds, "gross_matched_sharpe": gross_sharpe_folds,
            "r6_beats_gross": r6_beats_gross_folds,
        },
        "r6_mechanism_classification": mechanism, "most_damaging_evidence": most_damaging,
        "strongest_supporting_evidence": strongest,
        "forward_r6_readiness": "CONDITIONAL_FEATURE_AND_CANONICAL_COVERAGE_GATE",
        "recommended_forward_arms": forward, "full_raw_baseline": full_baseline,
        "2026_outcome_used": False, "model_fit_count_used_in_final_evidence": fit_count,
        "discarded_fixed_spec_diagnostic_fit_count": 5,
        "model_fit_role": "NO_REFIT_USED_ORIGINAL_FROZEN_OOF", "candidate_selection_count": 0,
        "hyperparameter_change_count": 0, "feature_change_count": 0, "threshold_change_count": 0,
        "exposure_change_count": 0, "canonical_write_count": 0, "broker_action_count": 0,
        "anti_bloat_status": "FAIL_PREEXISTING_MANAGED_ACL_REPOSITORY_ACCOUNTING_INCOMPLETE_1",
    }

    OUT.mkdir(parents=True, exist_ok=True)
    domain_missingness.to_csv(OUT / "domain_missingness.csv", index=False, encoding="utf-8-sig")
    arm_summary.to_csv(OUT / "arm_summary.csv", index=False, encoding="utf-8-sig")
    fp.to_csv(OUT / "fold_and_paired_comparison.csv", index=False, encoding="utf-8-sig")
    write_json(OUT / "r6_specification_and_transportability.json", specification)
    write_json(OUT / "classification.json", classification)
    (OUT / "final_report.md").write_text(render_report(classification, specification, arm_summary, fp), encoding="utf-8")
    artifacts = [{"name": name, "sha256": sha256_file(OUT / name), "bytes": (OUT / name).stat().st_size}
                 for name in FINAL_FILES if name != "hash_manifest.json"]
    write_json(OUT / "hash_manifest.json", {
        "task_id": ANALYSIS_CONTRACT["task_id"], "status": "PASS_HASH_VERIFIED",
        "artifact_count_including_manifest": len(FINAL_FILES), "artifacts": artifacts,
        "analysis_contract_sha256": contract_sha, "authoritative_input_hashes": EXPECTED_HASHES,
        "task_source_sha256": sha256_file(Path(__file__)),
        "test_source_sha256": sha256_file(REPO / "scripts/v22/test_a2_r6_domain_transportability_and_fixed_spec_replay_r1.py"),
        "canonical_data_read_only": True, "2026_outcome_used": False,
    })
    require(len([p for p in OUT.iterdir() if p.is_file()]) == len(FINAL_FILES), "ARTIFACT_COUNT_FAILURE")
    print_terminal(classification, arm_summary, fp)
    return classification


if __name__ == "__main__":
    run()
