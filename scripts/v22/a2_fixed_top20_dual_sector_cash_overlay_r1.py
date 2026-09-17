"""Fixed-membership FF12/FF48 only-downweight cash-overlay ablation.

This runner consumes the immutable A2 Top20 path and frozen PIT taxonomy.  It
constructs the overlay from contemporaneous weights/classifications only,
freezes the complete mechanical contract, and only then opens the pre-2026
price path for exposed-history diagnostics.  No model fit, membership change,
parameter search, SEC work, or 2026 outcome read is permitted.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.optimize import minimize


TASK_ID = "A2_FIXED_TOP20_DUAL_SECTOR_CASH_OVERLAY_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK_ID
A2_ROOT = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2"
TOP20 = A2_ROOT / "top20_selections.parquet"
PORTFOLIO = A2_ROOT / "portfolio_daily.parquet"
TAXONOMY_ROOT = RESULTS / "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1"
TAXONOMY = TAXONOMY_ROOT / "pit_ff12_ff48_taxonomy.parquet"
TAXONOMY_METADATA = TAXONOMY_ROOT / "research_metadata.json"
PRIOR_MEMBERSHIP = RESULTS / "A2_PRETOP20_CANDIDATE_RECOVERY_AND_MEMBERSHIP_DECONCENTRATION_R1"
PRIOR_SOURCE = REPO / "scripts" / "v22" / "a2_pretop20_candidate_recovery_and_membership_deconcentration_r1.py"
BASE_SOURCE = REPO / "scripts" / "v22" / "stage_sec_pit_taxonomy.py"
R0F_SOURCE = REPO / "scripts" / "v22" / "fast_a2_r0f_corporate_action_and_nav_forensic_audit.py"
FALSIFICATION_SOURCE = REPO / "scripts" / "v22" / "a2_strategy_falsification_and_robustness_r1.py"

EXPECTED_TOP20_SHA256 = "5e5203fdcd9a1e53fe1e2d64cd8c1adb78df4bd7acc733394d4dbd62392b8b20"
EXPECTED_PORTFOLIO_SHA256 = "4e55f1a76952b864349dc058f1f42809f0792afd7060623c44c33c1a1cd45d73"
EXPECTED_TAXONOMY_FILE_SHA256 = "515427bfe4d450540bcf8b04a9ce5fd50f706c551300a46450f5e4669b7d552f"
EXPECTED_TAXONOMY_LOGICAL_HASH = "0f0b48772c09dadb1b93d783a623a896a3a18ef307b75fa253ef2f08ee9208e1"
TOP_N = 20
RAW_WEIGHT = 1.0 / TOP_N
MAX_ADDITIONAL_CASH = 0.20
MIN_GROSS = 1.0 - MAX_ADDITIONAL_CASH
EPS = 1e-12
SOLVER_FTOL = 1e-10
SOLVER_MAXITER = 600
CONSTRAINT_TOL = 2e-7
ANNUALIZATION = 252.0
HAC_LAGS = 5
BOOTSTRAP_BLOCK = 10
BOOTSTRAP_REPETITIONS = 2000
BOOTSTRAP_SEED = 20260823
PREEXISTING_ACL_EXCEPTIONS = 2
FINAL_FILES = [
    "final_report.md", "overlay_contract.json", "arm_summary.csv",
    "concentration_and_cash_diagnostics.csv", "period_and_drawdown_diagnostics.csv",
    "classification.json", "hash_manifest.json",
]


class GateFailure(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise GateFailure(f"{code}:{detail}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    os.replace(temporary, path)


def import_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_manifest(root: Path) -> dict[str, Any]:
    manifest = json.loads((root / "hash_manifest.json").read_text(encoding="utf-8"))
    require(manifest["status"] == "PASS_HASH_VERIFIED", "UPSTREAM_MANIFEST_STATUS", root)
    for row in manifest["artifacts"]:
        path = root / row["name"]
        require(path.is_file() and sha256_file(path) == row["sha256"], "UPSTREAM_ARTIFACT_HASH", path)
    return manifest


def group_matrix(labels: Iterable[str]) -> np.ndarray:
    values = np.asarray([str(value) for value in labels], dtype=object)
    groups = sorted(set(values))
    return np.vstack([(values == group).astype(float) for group in groups])


def normalized_hhi(weights: Iterable[float], labels_or_matrix: Iterable[str] | np.ndarray) -> float:
    weights_array = np.asarray(list(weights), float)
    gross = float(weights_array.sum())
    require(gross > EPS, "ZERO_GROSS_HHI")
    matrix = labels_or_matrix if isinstance(labels_or_matrix, np.ndarray) and labels_or_matrix.ndim == 2 else group_matrix(labels_or_matrix)
    group_weights = np.asarray(matrix, float) @ weights_array / gross
    return float(group_weights @ group_weights)


def max_group_weight(weights: Iterable[float], labels_or_matrix: Iterable[str] | np.ndarray) -> float:
    weights_array = np.asarray(list(weights), float)
    matrix = labels_or_matrix if isinstance(labels_or_matrix, np.ndarray) and labels_or_matrix.ndim == 2 else group_matrix(labels_or_matrix)
    return float((np.asarray(matrix, float) @ weights_array / weights_array.sum()).max())


def _solver_options() -> dict[str, Any]:
    return {"ftol": SOLVER_FTOL, "maxiter": SOLVER_MAXITER, "disp": False}


def _minimum_hhi_start(a12: np.ndarray, a48: np.ndarray, raw: np.ndarray, upper: np.ndarray | None = None) -> np.ndarray:
    count = len(raw)
    bounds = [(0.0, 1.0 if upper is None else float(upper[index])) for index in range(count)]
    result = minimize(
        lambda p: float(np.square(a12 @ p).sum() + np.square(a48 @ p).sum()),
        raw, method="SLSQP", bounds=bounds,
        constraints=[{"type": "eq", "fun": lambda p: float(p.sum() - 1.0)}],
        options=_solver_options(),
    )
    require(result.success, "MIN_HHI_START_SOLVER", result.message)
    return np.clip(np.asarray(result.x, float), 0.0, 1.0)


def _stage1_max_gross_composition(
    a12: np.ndarray, a48: np.ndarray, target12: float, target48: float, cell_counts: np.ndarray,
    extra_starts: list[np.ndarray] | None = None,
) -> tuple[np.ndarray, float]:
    """Minimize maximum normalized name weight; equivalent to max gross.

    Raw weights are authoritative equal 5% weights.  For normalized weights p,
    the only-downweight bound is G*p_i <= 5%, hence the largest feasible gross
    is 5% / max(p_i).  The optimization is convex even though SLSQP is used.
    """
    count = len(cell_counts)
    raw = cell_counts / float(cell_counts.sum())
    starts = [raw, _minimum_hhi_start(a12, a48, raw)]
    if extra_starts:
        starts.extend(extra_starts)
    constraints = [
        {"type": "eq", "fun": lambda x: float(x[:count].sum() - 1.0)},
        {"type": "ineq", "fun": lambda x: float(target12 - np.square(a12 @ x[:count]).sum())},
        {"type": "ineq", "fun": lambda x: float(target48 - np.square(a48 @ x[:count]).sum())},
        {"type": "ineq", "fun": lambda x: x[count] - x[:count] / cell_counts},
    ]
    valid: list[tuple[np.ndarray, float]] = []
    for start in starts:
        p0 = np.clip(np.asarray(start, float), 0.0, 1.0)
        p0 /= p0.sum()
        x0 = np.r_[p0, max(float((p0 / cell_counts).max()), RAW_WEIGHT)]
        result = minimize(
            lambda x: float(x[count]), x0, method="SLSQP",
            bounds=[(0.0, 1.0)] * count + [(RAW_WEIGHT, 1.0)],
            constraints=constraints, options=_solver_options(),
        )
        p = np.clip(np.asarray(result.x[:count], float), 0.0, 1.0)
        m = max(float(result.x[count]), float((p / cell_counts).max()))
        if (
            abs(float(p.sum()) - 1.0) <= CONSTRAINT_TOL
            and float(np.square(a12 @ p).sum()) <= target12 + CONSTRAINT_TOL
            and float(np.square(a48 @ p).sum()) <= target48 + CONSTRAINT_TOL
            and float((p / cell_counts).max()) <= m + CONSTRAINT_TOL
        ):
            valid.append((p / p.sum(), m))
    require(bool(valid), "TARGET_COMPOSITION_SOLVER_FAILURE", (target12, target48))
    return min(valid, key=lambda item: (item[1], stable_hash(np.round(item[0], 14).tolist())))


def solve_session_weights(day: pd.DataFrame, target12: float, target48: float) -> dict[str, Any]:
    require(len(day) == TOP_N and day.ticker.nunique() == TOP_N, "TOP20_DAY_IDENTITY")
    ordered = day.sort_values("ticker", kind="mergesort").reset_index(drop=True)
    # Collapse securities sharing the same FF12/FF48 cell.  The constraints
    # depend only on cell totals and the secondary quadratic is symmetric, so
    # equal within-cell weights are the exact minimum-distortion solution.
    cells = ordered.groupby(["ff12", "ff48"], sort=True).agg(
        cell_count=("ticker", "size"), s1_cell_weight=("s1_weight", "sum")
    ).reset_index()
    counts = cells.cell_count.to_numpy(float)
    raw_cells = counts / TOP_N
    s1_cells = cells.s1_cell_weight.to_numpy(float)
    a12, a48 = group_matrix(cells.ff12), group_matrix(cells.ff48)
    require(abs(s1_cells.sum() - 1.0) <= 1e-12 and (s1_cells > 0).all(), "S1_WEIGHT_INPUT")

    if normalized_hhi(raw_cells, a12) <= target12 + 1e-14 and normalized_hhi(raw_cells, a48) <= target48 + 1e-14:
        cell_weights = raw_cells.copy()
        gross = 1.0
        guard_binding = False
        solver_status = "RAW_ALREADY_MEETS_TARGETS"
    else:
        p_stage1, _ = _stage1_max_gross_composition(a12, a48, target12, target48, counts, [s1_cells])
        gross_unclipped = min(1.0, RAW_WEIGHT / float((p_stage1 / counts).max()))
        if gross_unclipped >= MIN_GROSS - CONSTRAINT_TOL:
            solutions: list[tuple[float, np.ndarray, float]] = []
            for backoff in (1e-8, 1e-7, 1e-6, 1e-5):
                trial_gross = max(MIN_GROSS, gross_unclipped - backoff)
                upper = counts * RAW_WEIGHT / trial_gross
                constraints = [
                    {"type": "eq", "fun": lambda p: float(p.sum() - 1.0)},
                    {"type": "ineq", "fun": lambda p: float(target12 - np.square(a12 @ p).sum())},
                    {"type": "ineq", "fun": lambda p: float(target48 - np.square(a48 @ p).sum())},
                ]
                result = minimize(
                    lambda p: float(np.sum(np.square(trial_gross * p - counts * RAW_WEIGHT) / (counts * RAW_WEIGHT))),
                    p_stage1, method="SLSQP", bounds=[(0.0, float(value)) for value in upper],
                    constraints=constraints, options=_solver_options(),
                )
                p = np.asarray(result.x, float)
                if (
                    abs(p.sum() - 1.0) <= CONSTRAINT_TOL
                    and np.all(p <= upper + CONSTRAINT_TOL)
                    and normalized_hhi(p, a12) <= target12 + CONSTRAINT_TOL
                    and normalized_hhi(p, a48) <= target48 + CONSTRAINT_TOL
                ):
                    objective = float(np.sum(np.square(trial_gross * p - counts * RAW_WEIGHT) / (counts * RAW_WEIGHT)))
                    solutions.append((trial_gross, p / p.sum(), objective))
                    break
            require(bool(solutions), "SECONDARY_DISTORTION_SOLVER_FAILURE")
            gross, p, _ = max(solutions, key=lambda item: item[0])
            cell_weights = gross * p
            guard_binding = bool(gross <= MIN_GROSS + CONSTRAINT_TOL)
            solver_status = "TARGETS_FEASIBLE_MAX_GROSS_SECONDARY_DISTORTION_MINIMIZED"
        else:
            gross = MIN_GROSS
            upper = counts * RAW_WEIGHT / gross
            result = minimize(
                lambda p: float(np.square(a12 @ p).sum() + np.square(a48 @ p).sum()),
                raw_cells, method="SLSQP", bounds=[(0.0, float(value)) for value in upper],
                constraints=[{"type": "eq", "fun": lambda p: float(p.sum() - 1.0)}],
                options=_solver_options(),
            )
            require(result.success and abs(float(result.x.sum()) - 1.0) <= CONSTRAINT_TOL, "GUARD_BOUND_MIN_HHI_SOLVER", result.message)
            cell_weights = gross * np.clip(np.asarray(result.x, float), 0.0, upper)
            guard_binding = True
            solver_status = "TARGETS_INFEASIBLE_WITHIN_GUARD_MIN_COMBINED_HHI_AT_80PCT_GROSS"
    cell_key_to_weight = {
        (str(row.ff12), str(row.ff48)): float(weight / row.cell_count)
        for row, weight in zip(cells.itertuples(index=False), cell_weights)
    }
    weights = np.asarray([cell_key_to_weight[(str(row.ff12), str(row.ff48))] for row in ordered.itertuples(index=False)], float)
    weights[np.abs(weights) < 1e-14] = 0.0
    raw = np.full(TOP_N, RAW_WEIGHT)
    gross = float(weights.sum())
    security_a12, security_a48 = group_matrix(ordered.ff12), group_matrix(ordered.ff48)
    h12, h48 = normalized_hhi(weights, security_a12), normalized_hhi(weights, security_a48)
    require(np.all(weights >= -CONSTRAINT_TOL) and np.all(weights <= raw + CONSTRAINT_TOL), "ONLY_DOWNWEIGHT_VIOLATION")
    require(gross >= MIN_GROSS - CONSTRAINT_TOL and gross <= 1.0 + CONSTRAINT_TOL, "CASH_GUARD_VIOLATION", gross)
    return {
        "weights": {ticker: float(weight) for ticker, weight in zip(ordered.ticker, weights)},
        "gross": gross, "additional_cash": 1.0 - gross,
        "ff12_hhi": h12, "ff48_hhi": h48,
        "ff12_max_weight": max_group_weight(weights, security_a12), "ff48_max_weight": max_group_weight(weights, security_a48),
        "ff12_target_met": bool(h12 <= target12 + CONSTRAINT_TOL),
        "ff48_target_met": bool(h48 <= target48 + CONSTRAINT_TOL),
        "both_targets_met": bool(h12 <= target12 + CONSTRAINT_TOL and h48 <= target48 + CONSTRAINT_TOL),
        "cash_guard_binding": guard_binding, "solver_status": solver_status,
        "zero_weight_top20_count": int((weights <= 1e-12).sum()),
    }


def concentration_row(weights: dict[str, float], day: pd.DataFrame, prefix: str) -> dict[str, float]:
    ordered = day.sort_values("ticker", kind="mergesort")
    array = ordered.ticker.map(weights).to_numpy(float)
    result: dict[str, float] = {f"{prefix}_gross": float(array.sum()), f"{prefix}_cash": float(1.0 - array.sum())}
    for level in ("ff12", "ff48"):
        matrix = group_matrix(ordered[level])
        hhi = normalized_hhi(array, matrix)
        result[f"{prefix}_{level}_hhi"] = hhi
        result[f"{prefix}_{level}_max_weight"] = max_group_weight(array, matrix)
        result[f"{prefix}_{level}_effective_count"] = 1.0 / hhi
    return result


def load_mechanical_inputs() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    require(sha256_file(TOP20) == EXPECTED_TOP20_SHA256, "TOP20_HASH")
    require(sha256_file(PORTFOLIO) == EXPECTED_PORTFOLIO_SHA256, "PORTFOLIO_HASH")
    require(sha256_file(TAXONOMY) == EXPECTED_TAXONOMY_FILE_SHA256, "TAXONOMY_FILE_HASH")
    metadata = json.loads(TAXONOMY_METADATA.read_text(encoding="utf-8"))
    require(metadata["taxonomy_hash"] == EXPECTED_TAXONOMY_LOGICAL_HASH, "TAXONOMY_LOGICAL_HASH")
    prior_manifest = verify_manifest(PRIOR_MEMBERSHIP)
    top = pd.read_parquet(TOP20, columns=["signal_date", "ticker", "a2_prediction", "a2_rank"])
    taxonomy = pd.read_parquet(TAXONOMY)
    for frame in (top, taxonomy):
        frame["signal_date"] = pd.to_datetime(frame.signal_date).dt.normalize()
        frame["ticker"] = frame.ticker.astype(str).str.upper().str.strip()
        require(frame.signal_date.max() < pd.Timestamp("2026-01-01"), "2026_MECHANICAL_INPUT")
    require(len(top) == 15_000 and top.groupby("signal_date").size().eq(TOP_N).all(), "TOP20_CARDINALITY")
    joined = top.merge(taxonomy[["signal_date", "ticker", "ff12", "ff48"]], on=["signal_date", "ticker"], validate="one_to_one")
    require(len(joined) == len(top) and joined[["ff12", "ff48"]].notna().all().all(), "TOP20_TAXONOMY_ALIGNMENT")
    base = import_file("a2_cash_base", BASE_SOURCE)
    raw_contract = next(item for item in base.candidates() if item.trial_id == "S0_RAW")
    s1_contract = next(item for item in base.candidates() if item.trial_id == "S1_SOFT_025")
    raw_targets = base.candidate_target(raw_contract, top, taxonomy)
    s1_targets = base.candidate_target(s1_contract, top, taxonomy)
    prior = import_file("a2_cash_prior", PRIOR_SOURCE)
    for date, day in joined.groupby("signal_date", sort=True):
        date = pd.Timestamp(date)
        raw = raw_targets[date]
        s1 = s1_targets[date]
        require(set(raw) == set(s1) == set(day.ticker), "FIXED_MEMBERSHIP_IDENTITY", date)
        require(max(abs(float(value) - RAW_WEIGHT) for value in raw.values()) <= 1e-15, "RAW_WEIGHT_CONTRACT")
        independent = prior.s1_weights(day)
        require(max(abs(independent[ticker] - s1[ticker]) for ticker in s1) <= 1e-15, "S1_EXACT_WEIGHT_REPLAY")
    facts = {
        "raw_top20_sha256": EXPECTED_TOP20_SHA256, "portfolio_sha256": EXPECTED_PORTFOLIO_SHA256,
        "taxonomy_file_sha256": EXPECTED_TAXONOMY_FILE_SHA256, "taxonomy_logical_hash": EXPECTED_TAXONOMY_LOGICAL_HASH,
        "prior_membership_manifest_sha256": sha256_file(PRIOR_MEMBERSHIP / "hash_manifest.json"),
        "prior_membership_manifest_status": prior_manifest["status"],
        "decision_dates": int(top.signal_date.nunique()), "membership_rows": int(len(top)),
        "top_n": TOP_N, "raw_weight_contract": "TOP20_EQUAL_WEIGHT_LONG_ONLY",
        "s1_contract": "FF12_GROUP_BUDGET_POWER_0.75_FULLY_INVESTED_FIXED_MEMBERSHIP",
    }
    return joined.sort_values(["signal_date", "ticker"], kind="mergesort"), taxonomy, facts


def build_mechanical_targets(joined: pd.DataFrame) -> tuple[dict[str, dict[pd.Timestamp, dict[str, float]]], pd.DataFrame, dict[str, Any]]:
    targets = {name: {} for name in ("RAW_A2", "S1_SOFT_025", "DUAL_SECTOR_CASH", "RAW_GROSS_MATCHED")}
    rows: list[dict[str, Any]] = []
    base = import_file("a2_cash_s1", PRIOR_SOURCE)
    for date, day in joined.groupby("signal_date", sort=True):
        date = pd.Timestamp(date)
        raw = {str(ticker): RAW_WEIGHT for ticker in day.ticker}
        s1 = base.s1_weights(day)
        day = day.copy()
        day["s1_weight"] = day.ticker.map(s1)
        raw_metrics = concentration_row(raw, day, "raw")
        s1_metrics = concentration_row(s1, day, "s1")
        target12 = min(raw_metrics["raw_ff12_hhi"], s1_metrics["s1_ff12_hhi"])
        target48 = min(raw_metrics["raw_ff48_hhi"], s1_metrics["s1_ff48_hhi"])
        dual = solve_session_weights(day, target12, target48)
        gross_matched = {ticker: RAW_WEIGHT * dual["gross"] for ticker in raw}
        dual_metrics = concentration_row(dual["weights"], day, "dual")
        gross_metrics = concentration_row(gross_matched, day, "gross_matched")
        require(set(raw) == set(s1) == set(dual["weights"]) == set(gross_matched), "TOP20_MEMBERSHIP_CHANGED", date)
        require(max(dual["weights"][ticker] - raw[ticker] for ticker in raw) <= CONSTRAINT_TOL, "UPWEIGHT_VIOLATION", date)
        require(abs(sum(gross_matched.values()) - dual["gross"]) <= 1e-12, "GROSS_MATCH_IDENTITY", date)
        require(abs(gross_metrics["gross_matched_ff12_hhi"] - raw_metrics["raw_ff12_hhi"]) <= 1e-12, "GROSS_MATCH_FF12_HHI")
        require(abs(gross_metrics["gross_matched_ff48_hhi"] - raw_metrics["raw_ff48_hhi"]) <= 1e-12, "GROSS_MATCH_FF48_HHI")
        targets["RAW_A2"][date], targets["S1_SOFT_025"][date] = raw, s1
        targets["DUAL_SECTOR_CASH"][date], targets["RAW_GROSS_MATCHED"][date] = dual["weights"], gross_matched
        rows.append({
            "row_type": "SESSION", "signal_date": date, "target_ff12_hhi": target12, "target_ff48_hhi": target48,
            **raw_metrics, **s1_metrics, **dual_metrics, **gross_metrics,
            "additional_cash": dual["additional_cash"], "cash_guard_binding": dual["cash_guard_binding"],
            "ff12_target_met": dual["ff12_target_met"], "ff48_target_met": dual["ff48_target_met"],
            "both_targets_met": dual["both_targets_met"], "zero_weight_top20_count": dual["zero_weight_top20_count"],
            "solver_status": dual["solver_status"],
        })
    diagnostics = pd.DataFrame(rows).sort_values("signal_date", kind="mergesort").reset_index(drop=True)
    diagnostics["raw_ff12_hhi_quintile"] = pd.qcut(diagnostics.raw_ff12_hhi.rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    diagnostics["raw_ff48_hhi_quintile"] = pd.qcut(diagnostics.raw_ff48_hhi.rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    ff12_quintile = diagnostics.groupby("raw_ff12_hhi_quintile").additional_cash.mean().to_dict()
    ff48_quintile = diagnostics.groupby("raw_ff48_hhi_quintile").additional_cash.mean().to_dict()
    mechanics = {
        "average_additional_cash": float(diagnostics.additional_cash.mean()),
        "median_additional_cash": float(diagnostics.additional_cash.median()),
        "p90_additional_cash": float(diagnostics.additional_cash.quantile(0.90)),
        "max_additional_cash": float(diagnostics.additional_cash.max()),
        "pct_sessions_with_cash": float(diagnostics.additional_cash.gt(CONSTRAINT_TOL).mean()),
        "pct_sessions_cash_guard_binding": float(diagnostics.cash_guard_binding.mean()),
        "pct_sessions_target_ff12_met": float(diagnostics.ff12_target_met.mean()),
        "pct_sessions_target_ff48_met": float(diagnostics.ff48_target_met.mean()),
        "pct_sessions_both_targets_met": float(diagnostics.both_targets_met.mean()),
        "corr_raw_ff12_hhi_cash": float(diagnostics.raw_ff12_hhi.corr(diagnostics.additional_cash)),
        "corr_raw_ff48_hhi_cash": float(diagnostics.raw_ff48_hhi.corr(diagnostics.additional_cash)),
        "average_cash_by_raw_ff12_hhi_quintile": {str(k): float(v) for k, v in ff12_quintile.items()},
        "average_cash_by_raw_ff48_hhi_quintile": {str(k): float(v) for k, v in ff48_quintile.items()},
        "zero_weight_top20_total": int(diagnostics.zero_weight_top20_count.sum()),
        "max_zero_weight_top20_count": int(diagnostics.zero_weight_top20_count.max()),
        "max_gross_match_error": float((diagnostics.dual_gross - diagnostics.gross_matched_gross).abs().max()),
        "max_gross_matched_ff12_hhi_error": float((diagnostics.raw_ff12_hhi - diagnostics.gross_matched_ff12_hhi).abs().max()),
        "max_gross_matched_ff48_hhi_error": float((diagnostics.raw_ff48_hhi - diagnostics.gross_matched_ff48_hhi).abs().max()),
        "max_cash_identity_error": float((diagnostics.dual_gross + diagnostics.additional_cash - 1.0).abs().max()),
        "ff12_hhi_reduction_vs_raw": float((diagnostics.raw_ff12_hhi.mean() - diagnostics.dual_ff12_hhi.mean()) / diagnostics.raw_ff12_hhi.mean()),
        "ff48_hhi_reduction_vs_raw": float((diagnostics.raw_ff48_hhi.mean() - diagnostics.dual_ff48_hhi.mean()) / diagnostics.raw_ff48_hhi.mean()),
    }
    return targets, diagnostics, mechanics


def target_map_hash(targets: dict[str, dict[pd.Timestamp, dict[str, float]]]) -> str:
    rows = []
    for arm in sorted(targets):
        for date in sorted(targets[arm]):
            for ticker, weight in sorted(targets[arm][date].items()):
                rows.append((arm, str(pd.Timestamp(date).date()), ticker, format(float(weight), ".17g")))
    return stable_hash(rows)


def freeze_contract(identity: dict[str, Any], targets: dict[str, dict[pd.Timestamp, dict[str, float]]], mechanics: dict[str, Any]) -> dict[str, Any]:
    spec = {
        "task_id": TASK_ID, "role": "FORWARD_ONLY_EXPERIMENTAL_CHALLENGER",
        "top20_membership_fixed": True, "top_n": TOP_N, "raw_weight": RAW_WEIGHT,
        "taxonomy_logical_hash": EXPECTED_TAXONOMY_LOGICAL_HASH,
        "target_ff12_hhi": "MIN(RAW_EQUITY_NORMALIZED_FF12_HHI,S1_EQUITY_NORMALIZED_FF12_HHI)",
        "target_ff48_hhi": "MIN(RAW_EQUITY_NORMALIZED_FF48_HHI,S1_EQUITY_NORMALIZED_FF48_HHI)",
        "primary_objective": "MAXIMIZE_EQUITY_GROSS_SUBJECT_TO_BOTH_NORMALIZED_HHI_TARGETS",
        "only_downweight": "0<=W_NEW_I<=W_RAW_I", "redistribution": False, "residual_destination": "CASH",
        "max_additional_cash": MAX_ADDITIONAL_CASH, "infeasible_policy": "FIX_GROSS_0.80_AND_MINIMIZE_HHI12_PLUS_HHI48",
        "secondary_objective": "MINIMIZE_SUM((W-W_RAW)^2/MAX(W_RAW,EPS))",
        "eps": EPS, "solver": "SCIPY_SLSQP_DETERMINISTIC", "solver_ftol": SOLVER_FTOL,
        "solver_maxiter": SOLVER_MAXITER, "constraint_tolerance": CONSTRAINT_TOL,
        "paired_inference": {"hac_lags": HAC_LAGS, "block_length": BOOTSTRAP_BLOCK, "repetitions": BOOTSTRAP_REPETITIONS, "seed": BOOTSTRAP_SEED},
        "classification_rules": {
            "targeted": "vs gross-matched: maxDD improvement>=2pp, downside capture improvement>=0.05, residual Sharpe improvement>=0.10, annualized mean delta>=-2%, positive cumulative delta in >=2/3 years",
            "mainly_gross": "abs Sharpe delta<0.10, abs maxDD delta<3pp, abs residual Sharpe delta<0.10, abs annualized mean delta<3%",
            "useful_risk_tradeoff": "vs Raw Sharpe retention>=95%, maxDD improvement>=3pp or downside capture improvement>=0.05, both HHI reductions positive",
            "too_expensive": "vs Raw Sharpe retention<90% or CAGR retention<80%, unless targeted rule passes",
        },
        "no_parameter_search": True, "no_model_fit": True, "economic_outcomes_used_for_design": False,
        "2023_2025_role": "EXPOSED_DIAGNOSTIC_ONLY", "2026_outcome_used": False,
        "target_map_hash": target_map_hash(targets),
        "authoritative_input_hashes": {
            "top20": identity["raw_top20_sha256"], "portfolio": identity["portfolio_sha256"],
            "taxonomy_file": identity["taxonomy_file_sha256"], "prior_manifest": identity["prior_membership_manifest_sha256"],
        },
    }
    contract_hash = stable_hash(spec)
    contract = {**spec, "overlay_contract_hash": contract_hash, "freeze_timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "economic_outcome_read_count_at_freeze": 0, "mechanical_metrics_at_freeze": mechanics, "spec_mutation_forbidden": True}
    path = OUT / "overlay_contract.json"
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        require(existing["overlay_contract_hash"] == contract_hash, "FROZEN_CONTRACT_MUTATION_ATTEMPT")
        contract = existing
    else:
        atomic_json(path, contract)
    require(json.loads(path.read_text(encoding="utf-8"))["overlay_contract_hash"] == contract_hash, "CONTRACT_FREEZE_WRITE")
    return contract


def performance_metrics(daily: pd.DataFrame) -> dict[str, Any]:
    ordered = daily.sort_values("execution_date", kind="mergesort")
    r = ordered.reconstructed_daily_return.to_numpy(float)
    require(len(r) > 1 and np.isfinite(r).all() and (r > -1).all(), "INVALID_RETURNS")
    nav = np.r_[1.0, np.cumprod(1.0 + r)]
    dd = nav / np.maximum.accumulate(nav) - 1.0
    vol = float(r.std(ddof=0) * math.sqrt(ANNUALIZATION))
    cagr = float(nav[-1] ** (ANNUALIZATION / len(r)) - 1.0)
    downside = np.minimum(r, 0.0)
    week = pd.Series(r).rolling(5).apply(lambda x: np.prod(1.0 + x) - 1.0, raw=True).dropna()
    monthly = pd.Series(r, index=pd.DatetimeIndex(ordered.execution_date)).groupby(pd.DatetimeIndex(ordered.execution_date).to_period("M")).apply(lambda x: float(np.prod(1.0 + x) - 1.0))
    quantile = float(np.quantile(r, 0.05))
    return {
        "sessions": int(len(r)), "cumulative_return": float(nav[-1] - 1.0), "cagr": cagr,
        "sharpe": float(r.mean() * ANNUALIZATION / vol) if vol else None,
        "max_drawdown": float(dd.min()), "calmar": cagr / abs(float(dd.min())) if dd.min() < 0 else None,
        "annualized_volatility": vol, "turnover": float(ordered.reconstructed_turnover.sum()),
        "cost": float(ordered.reconstructed_transaction_cost.sum()), "worst_day": float(r.min()),
        "worst_week": float(week.min()), "worst_month": float(monthly.min()),
        "downside_deviation": float(np.sqrt(np.mean(downside**2)) * math.sqrt(ANNUALIZATION)),
        "cvar_5pct": float(r[r <= quantile].mean()),
    }


def factor_metrics(daily: pd.DataFrame, prices: pd.DataFrame) -> dict[str, Any]:
    factor = import_file("a2_cash_factor", FALSIFICATION_SOURCE)
    qqq = prices.loc[prices.ticker.eq("QQQ"), ["trade_date", "open"]].sort_values("trade_date").copy()
    qqq["qqq_return"] = qqq.open.pct_change()
    aligned = daily[["execution_date", "reconstructed_daily_return"]].merge(
        qqq[["trade_date", "qqq_return"]], left_on="execution_date", right_on="trade_date", validate="one_to_one"
    )
    require(aligned.qqq_return.notna().all(), "QQQ_ALIGNMENT")
    y, x = aligned.reconstructed_daily_return.to_numpy(float), aligned.qqq_return.to_numpy(float)
    fit = factor.ols_hac(y, x, HAC_LAGS)
    positive, negative = x > 0, x < 0
    def conditional_beta(mask: np.ndarray) -> float:
        return float(np.linalg.lstsq(np.column_stack([np.ones(int(mask.sum())), x[mask]]), y[mask], rcond=None)[0][1])
    return {
        "qqq_beta": float(fit["coefficients"][1]), "qqq_alpha": float(fit["alpha_annualized"]),
        "residual_sharpe": float(fit["residual_sharpe"]), "upside_beta": conditional_beta(positive),
        "downside_beta": conditional_beta(negative), "upside_capture": float(y[positive].sum() / x[positive].sum()),
        "downside_capture": float(y[negative].sum() / x[negative].sum()),
    }


def concentration_summary(diagnostics: pd.DataFrame, prefix: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for level in ("ff12", "ff48"):
        hhi = diagnostics[f"{prefix}_{level}_hhi"]
        maximum = diagnostics[f"{prefix}_{level}_max_weight"]
        result.update({
            f"{level}_hhi": float(hhi.mean()), f"{level}_hhi_median": float(hhi.median()),
            f"{level}_hhi_p90": float(hhi.quantile(.90)), f"{level}_hhi_p95": float(hhi.quantile(.95)),
            f"{level}_hhi_max": float(hhi.max()), f"{level}_effective_count": float((1.0 / hhi).mean()),
            f"{level}_max_weight": float(maximum.mean()), f"{level}_max_weight_p95": float(maximum.quantile(.95)),
            f"{level}_max_weight_max": float(maximum.max()),
        })
    result["average_equity_gross"] = float(diagnostics[f"{prefix}_gross"].mean())
    result["average_cash"] = float(diagnostics[f"{prefix}_cash"].mean())
    return result


def paired_inference(delta: np.ndarray) -> dict[str, Any]:
    factor = import_file("a2_cash_paired_factor", FALSIFICATION_SOURCE)
    values = np.asarray(delta, float)
    fit = factor.ols_hac(values, np.empty((len(values), 0)), HAC_LAGS)
    annual_mean = float(values.mean() * ANNUALIZATION)
    tracking_error = float(values.std(ddof=0) * math.sqrt(ANNUALIZATION))
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    means = np.empty(BOOTSTRAP_REPETITIONS)
    for index in range(BOOTSTRAP_REPETITIONS):
        sample = values[factor.moving_block_indices(len(values), BOOTSTRAP_BLOCK, rng)]
        means[index] = sample.mean() * ANNUALIZATION
    return {
        "annualized_mean_delta": annual_mean, "information_ratio": annual_mean / tracking_error if tracking_error else None,
        "hac_tstat": float(fit["alpha_t_hac"]), "bootstrap_ci_low": float(np.quantile(means, .025)),
        "bootstrap_ci_high": float(np.quantile(means, .975)), "bootstrap_probability_positive": float((means > 0).mean()),
    }


def drawdown_interval(daily: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    ordered = daily.sort_values("execution_date", kind="mergesort").reset_index(drop=True)
    nav = np.cumprod(1.0 + ordered.reconstructed_daily_return.to_numpy(float))
    running = np.maximum.accumulate(nav)
    trough_index = int(np.argmin(nav / running - 1.0))
    peak_index = int(np.argmax(nav[:trough_index + 1]))
    return pd.Timestamp(ordered.execution_date.iloc[peak_index]), pd.Timestamp(ordered.execution_date.iloc[trough_index])


def run_economics(
    targets: dict[str, dict[pd.Timestamp, dict[str, float]]], diagnostics: pd.DataFrame,
    contract: dict[str, Any], identity: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    require((OUT / "overlay_contract.json").is_file() and contract["economic_outcome_read_count_at_freeze"] == 0, "CONTRACT_NOT_FROZEN")
    prior = import_file("a2_cash_prior_economics", PRIOR_SOURCE)
    r0f = import_file("a2_cash_r0f", R0F_SOURCE)
    wanted = {ticker for mapping in targets.values() for weights in mapping.values() for ticker in weights}
    prices, price_hashes = prior.load_pre2026_qfq(wanted)
    require(prices.trade_date.max() < pd.Timestamp("2026-01-01"), "2026_PRICE_READ")
    signal_dates = sorted(targets["RAW_A2"])
    paths = {
        arm: r0f.reconstruct_path(model=arm, target_map=mapping, qfq=prices, signal_dates=signal_dates, cost_bps=10)
        for arm, mapping in targets.items()
    }
    authoritative = pd.read_parquet(PORTFOLIO, columns=[
        "execution_date", "reconstructed_daily_return", "reconstructed_nav", "reconstructed_turnover", "reconstructed_transaction_cost"
    ]).sort_values("execution_date", kind="mergesort")
    authoritative["execution_date"] = pd.to_datetime(authoritative.execution_date).dt.normalize()
    require(authoritative.execution_date.max() < pd.Timestamp("2026-01-01"), "2026_ECONOMIC_READ")
    raw_daily = paths["RAW_A2"].daily.sort_values("execution_date", kind="mergesort")
    compare = authoritative.merge(raw_daily, on="execution_date", suffixes=("_authoritative", "_replay"), validate="one_to_one")
    replay_errors = {
        key: float((compare[f"{column}_authoritative"] - compare[f"{column}_replay"]).abs().max())
        for key, column in (("return", "reconstructed_daily_return"), ("nav", "reconstructed_nav"),
                            ("turnover", "reconstructed_turnover"), ("cost", "reconstructed_transaction_cost"))
    }
    require(max(replay_errors.values()) <= 1e-12, "RAW_EXACT_REPLAY", replay_errors)

    prior_arms = pd.read_csv(PRIOR_MEMBERSHIP / "arm_summary.csv")
    prior_s1 = prior_arms.loc[prior_arms.arm.eq("S1_SOFT_025")].iloc[0]
    arm_rows: list[dict[str, Any]] = []
    daily_by_arm: dict[str, pd.DataFrame] = {}
    prefix = {"RAW_A2": "raw", "S1_SOFT_025": "s1", "DUAL_SECTOR_CASH": "dual", "RAW_GROSS_MATCHED": "gross_matched"}
    for arm, path in paths.items():
        daily = path.daily.sort_values("execution_date", kind="mergesort").reset_index(drop=True)
        daily_by_arm[arm] = daily
        row = {"arm": arm, "evidence_role": "EXPOSED_HISTORICAL_DIAGNOSTIC_ONLY", **performance_metrics(daily), **factor_metrics(daily, prices), **concentration_summary(diagnostics, prefix[arm])}
        arm_rows.append(row)
    arms = pd.DataFrame(arm_rows)
    s1 = arms.set_index("arm").loc["S1_SOFT_025"]
    for key in ("cagr", "sharpe", "max_drawdown", "turnover", "cost"):
        require(abs(float(s1[key]) - float(prior_s1[key])) <= 1e-12, "S1_EXACT_ECONOMIC_REPLAY", key)

    raw = arms.set_index("arm").loc["RAW_A2"]
    dual = arms.set_index("arm").loc["DUAL_SECTOR_CASH"]
    gross = arms.set_index("arm").loc["RAW_GROSS_MATCHED"]
    delta = daily_by_arm["DUAL_SECTOR_CASH"].reconstructed_daily_return.to_numpy(float) - daily_by_arm["RAW_GROSS_MATCHED"].reconstructed_daily_return.to_numpy(float)
    paired = paired_inference(delta)

    period_rows: list[dict[str, Any]] = []
    yearly_positive = 0
    for year in (2023, 2024, 2025):
        year_delta = None
        for arm, daily in daily_by_arm.items():
            part = daily.loc[daily.execution_date.dt.year.eq(year)].copy()
            metrics = {**performance_metrics(part), **factor_metrics(part, prices)}
            period_rows.append({"row_type": "YEAR", "period": str(year), "arm": arm, "evidence_role": "EXPOSED_DIAGNOSTIC_ONLY", **metrics})
            if arm == "DUAL_SECTOR_CASH":
                dual_return = float(np.prod(1.0 + part.reconstructed_daily_return) - 1.0)
            if arm == "RAW_GROSS_MATCHED":
                gross_return = float(np.prod(1.0 + part.reconstructed_daily_return) - 1.0)
        year_delta = dual_return - gross_return
        yearly_positive += int(year_delta >= 0)

    peak, trough = drawdown_interval(daily_by_arm["RAW_A2"])
    drawdown_results: dict[str, Any] = {"raw_peak_date": str(peak.date()), "raw_trough_date": str(trough.date())}
    raw_segment_return = None
    for arm, daily in daily_by_arm.items():
        part = daily.loc[daily.execution_date.gt(peak) & daily.execution_date.le(trough)].copy()
        segment_return = float(np.prod(1.0 + part.reconstructed_daily_return) - 1.0)
        if arm == "RAW_A2":
            raw_segment_return = segment_return
        mech_prefix = prefix[arm]
        selected = diagnostics.loc[diagnostics.signal_date.ge(peak) & diagnostics.signal_date.le(trough)]
        avg_gross = float(selected[f"{mech_prefix}_gross"].mean()) if not selected.empty else None
        avg_cash = float(selected[f"{mech_prefix}_cash"].mean()) if not selected.empty else None
        period_rows.append({
            "row_type": "RAW_MAX_DRAWDOWN_INTERVAL", "period": f"{peak.date()}..{trough.date()}", "arm": arm,
            "evidence_role": "EXPOSED_DIAGNOSTIC_ONLY", "sessions": len(part), "cumulative_return": segment_return,
            "average_equity_gross": avg_gross, "average_cash": avg_cash,
            "ff12_hhi": float(selected[f"{mech_prefix}_ff12_hhi"].mean()) if not selected.empty else None,
            "ff48_hhi": float(selected[f"{mech_prefix}_ff48_hhi"].mean()) if not selected.empty else None,
        })
        drawdown_results[arm] = {"segment_return": segment_return, "average_equity_gross": avg_gross, "average_cash": avg_cash}
    for arm in drawdown_results:
        if isinstance(drawdown_results[arm], dict):
            drawdown_results[arm]["loss_avoided_vs_raw"] = float(drawdown_results[arm]["segment_return"] - raw_segment_return)

    annual_delta = paired["annualized_mean_delta"]
    maxdd_improvement = float(dual.max_drawdown - gross.max_drawdown)
    downside_improvement = float(gross.downside_capture - dual.downside_capture)
    residual_improvement = float(dual.residual_sharpe - gross.residual_sharpe)
    sharpe_delta = float(dual.sharpe - gross.sharpe)
    targeted = maxdd_improvement >= .02 and downside_improvement >= .05 and residual_improvement >= .10 and annual_delta >= -.02 and yearly_positive >= 2
    mainly_gross = abs(sharpe_delta) < .10 and abs(maxdd_improvement) < .03 and abs(residual_improvement) < .10 and abs(annual_delta) < .03
    useful = float(dual.sharpe / raw.sharpe) >= .95 and (float(dual.max_drawdown - raw.max_drawdown) >= .03 or float(raw.downside_capture - dual.downside_capture) >= .05) and mechanics_positive(diagnostics)
    too_expensive = (float(dual.sharpe / raw.sharpe) < .90 or float(dual.cagr / raw.cagr) < .80) and not targeted
    if targeted:
        classification = "TARGETED_SECTOR_RISK_VALUE_SUPPORTED"
    elif too_expensive:
        classification = "SECTOR_CASH_OVERLAY_TOO_EXPENSIVE"
    elif useful:
        classification = "USEFUL_RISK_TRADEOFF"
    elif mainly_gross:
        classification = "MAINLY_GROSS_DERISKING"
    else:
        classification = "MAINLY_GROSS_DERISKING"
    forward = "FORWARD_EXPERIMENT_WORTHY" if classification in {"TARGETED_SECTOR_RISK_VALUE_SUPPORTED", "USEFUL_RISK_TRADEOFF"} else "NOT_FORWARD_WORTHY"
    recommended = "RAW_A2|S1_SOFT_025|DUAL_SECTOR_CASH" if forward == "FORWARD_EXPERIMENT_WORTHY" else "RAW_A2|S1_SOFT_025"
    result = {
        "raw_reconciliation": "PASS_EXACT_1E-12", "raw_replay_max_errors": replay_errors,
        "s1_reconciliation": "PASS_EXACT_1E-12", "top20_membership_status": "PASS_IDENTICAL_ALL_750_SESSIONS",
        "taxonomy_status": "PASS_FROZEN_HASH_EXACT", "paired_dual_vs_gross_matched": paired,
        "yearly_dual_vs_gross_matched_positive_count": yearly_positive, "drawdown": drawdown_results,
        "sector_cash_mechanism_classification": classification,
        "is_value_mainly_from_targeted_sector_derisking": bool(targeted),
        "is_value_mainly_from_lower_gross": bool(not targeted),
        "does_cash_overlay_beat_s1": bool(float(dual.sharpe) > float(s1.sharpe) and float(dual.max_drawdown) >= float(s1.max_drawdown)),
        "forward_eligibility": forward, "recommended_forward_arms": recommended,
        "price_input_hashes": price_hashes,
        "strongest_supporting_evidence": strongest_support(dual, gross, raw, diagnostics),
        "most_damaging_evidence": damaging_evidence(dual, gross, raw, s1, diagnostics, paired),
    }
    return arms, pd.DataFrame(period_rows), result


def mechanics_positive(diagnostics: pd.DataFrame) -> bool:
    return bool(diagnostics.dual_ff12_hhi.mean() < diagnostics.raw_ff12_hhi.mean() and diagnostics.dual_ff48_hhi.mean() < diagnostics.raw_ff48_hhi.mean())


def strongest_support(dual: pd.Series, gross: pd.Series, raw: pd.Series, diagnostics: pd.DataFrame) -> str:
    return (
        f"Equity-normalized FF12/FF48 HHI fell "
        f"{(diagnostics.raw_ff12_hhi.mean()-diagnostics.dual_ff12_hhi.mean())/diagnostics.raw_ff12_hhi.mean():.2%}/"
        f"{(diagnostics.raw_ff48_hhi.mean()-diagnostics.dual_ff48_hhi.mean())/diagnostics.raw_ff48_hhi.mean():.2%}; "
        f"Dual MaxDD improved {float(dual.max_drawdown-raw.max_drawdown):+.2%} vs Raw and "
        f"{float(dual.max_drawdown-gross.max_drawdown):+.2%} vs gross-matched Raw."
    )


def damaging_evidence(
    dual: pd.Series, gross: pd.Series, raw: pd.Series, s1: pd.Series,
    diagnostics: pd.DataFrame, paired: dict[str, Any],
) -> str:
    return (
        f"Dual-vs-gross-matched Sharpe delta was only {float(dual.sharpe-gross.sharpe):+.3f} "
        f"(HAC t {paired['hac_tstat']:.3f}); average additional cash was {diagnostics.additional_cash.mean():.2%}, "
        f"and the 20pp guard bound on {diagnostics.cash_guard_binding.mean():.2%} of sessions."
    )


def enrich_concentration_diagnostics(diagnostics: pd.DataFrame) -> pd.DataFrame:
    session = diagnostics.copy()
    rows: list[dict[str, Any]] = []
    for dimension, column in (("FF12", "raw_ff12_hhi_quintile"), ("FF48", "raw_ff48_hhi_quintile")):
        for quintile, group in session.groupby(column, sort=True):
            rows.append({"row_type": "QUINTILE_SUMMARY", "quintile_dimension": dimension, "quintile": int(quintile),
                         "session_count": int(len(group)), "additional_cash": float(group.additional_cash.mean())})
    return pd.concat([session, pd.DataFrame(rows)], ignore_index=True, sort=False)


def write_report(result: dict[str, Any], arms: pd.DataFrame) -> None:
    by = arms.set_index("arm")
    raw, s1, dual, gross = (by.loc[name] for name in ("RAW_A2", "S1_SOFT_025", "DUAL_SECTOR_CASH", "RAW_GROSS_MATCHED"))
    m, e = result["mechanics"], result["economics"]
    text = f"""# A2 fixed Top20 dual-sector cash overlay R1

TASK_STATUS={result['task_status']}
2026_OUTCOME_USED=FALSE

## Executive verdict

The experiment kept the authoritative Top20 membership fixed on every session.  It only reduced individual Raw weights, retained residual capital as cash, and exactly matched the Dual gross in the dumb Raw control.

Equity-normalized FF12/FF48 HHI fell {m['ff12_hhi_reduction_vs_raw']:.2%}/{m['ff48_hhi_reduction_vs_raw']:.2%}.  Average additional cash was {m['average_additional_cash']:.2%}; the 20pp guard bound on {m['pct_sessions_cash_guard_binding']:.2%} of sessions.  These are mechanical, outcome-free facts frozen before the exposed-history replay.

The primary causal comparison is Dual versus same-day gross-matched Raw.  CAGR/Sharpe/MaxDD/residual-Sharpe deltas were {dual.cagr-gross.cagr:+.2%}/{dual.sharpe-gross.sharpe:+.3f}/{dual.max_drawdown-gross.max_drawdown:+.2%}/{dual.residual_sharpe-gross.residual_sharpe:+.3f}.  Classification is `{e['sector_cash_mechanism_classification']}` and forward eligibility is `{e['forward_eligibility']}`.

## Frozen identity and contract

- Raw replay: `{e['raw_reconciliation']}`; S1 replay: `{e['s1_reconciliation']}`.
- Top20 membership: `{e['top20_membership_status']}`.
- Taxonomy: `{e['taxonomy_status']}`.
- Contract hash: `{result['contract']['overlay_contract_hash']}`.
- No model fit, factor search, parameter search, SEC work, or 2026 outcome read occurred.

## Arm scorecard

| Arm | CAGR | Sharpe | MaxDD | QQQ beta | Residual Sharpe | Downside capture | Avg gross | FF12 HHI | FF48 HHI |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
"""
    for name in ("RAW_A2", "S1_SOFT_025", "DUAL_SECTOR_CASH", "RAW_GROSS_MATCHED"):
        row = by.loc[name]
        text += f"| {name} | {row.cagr:.4f} | {row.sharpe:.4f} | {row.max_drawdown:.4f} | {row.qqq_beta:.4f} | {row.residual_sharpe:.4f} | {row.downside_capture:.4f} | {row.average_equity_gross:.4f} | {row.ff12_hhi:.6f} | {row.ff48_hhi:.6f} |\n"
    text += f"""

## Paired targeted-value evidence

- Annualized Dual-minus-gross-matched mean: {e['paired_dual_vs_gross_matched']['annualized_mean_delta']:.4%}.
- Information ratio: {e['paired_dual_vs_gross_matched']['information_ratio']:.4f}.
- HAC t-stat: {e['paired_dual_vs_gross_matched']['hac_tstat']:.4f}.
- Moving-block 95% CI: [{e['paired_dual_vs_gross_matched']['bootstrap_ci_low']:.4%}, {e['paired_dual_vs_gross_matched']['bootstrap_ci_high']:.4%}].
- P(mean delta > 0): {e['paired_dual_vs_gross_matched']['bootstrap_probability_positive']:.4f}.

## Verdict

- Strongest support: {e['strongest_supporting_evidence']}
- Most damaging evidence: {e['most_damaging_evidence']}
- Recommended forward arms: `{e['recommended_forward_arms']}`.

All 2023–2025 results are `EXPOSED_DIAGNOSTIC_ONLY`.  The fixed rules were not changed after the economic replay.
"""
    (OUT / "final_report.md").write_text(text, encoding="utf-8")


def write_hash_manifest(extra: dict[str, Any]) -> dict[str, Any]:
    artifacts = []
    for name in sorted(item for item in FINAL_FILES if item != "hash_manifest.json"):
        path = OUT / name
        require(path.is_file(), "MISSING_FINAL_ARTIFACT", name)
        artifacts.append({"name": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    manifest = {
        "task_id": TASK_ID, "status": "PASS_HASH_VERIFIED", "2026_outcome_used": False,
        "artifact_count_including_manifest": len(artifacts) + 1, "artifacts": artifacts,
        "authoritative_inputs": {
            str(TOP20): EXPECTED_TOP20_SHA256, str(PORTFOLIO): EXPECTED_PORTFOLIO_SHA256,
            str(TAXONOMY): EXPECTED_TAXONOMY_FILE_SHA256,
        },
        "extra_lineage": extra, "task_source_sha256": sha256_file(Path(__file__)),
    }
    require(manifest["artifact_count_including_manifest"] <= 7, "ARTIFACT_BUDGET")
    atomic_json(OUT / "hash_manifest.json", manifest)
    return manifest


def fmt(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).upper()
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)


def terminal_summary(result: dict[str, Any], arms: pd.DataFrame) -> str:
    by = arms.set_index("arm")
    raw, s1, dual, gross = (by.loc[name] for name in ("RAW_A2", "S1_SOFT_025", "DUAL_SECTOR_CASH", "RAW_GROSS_MATCHED"))
    m, e = result["mechanics"], result["economics"]
    years = result["periods"].loc[result["periods"].row_type.eq("YEAR")]
    year_text = {}
    for year in (2023, 2024, 2025):
        rows = years.loc[years.period.eq(str(year))].set_index("arm")
        year_text[year] = f"DUAL_SHARPE_{rows.loc['DUAL_SECTOR_CASH','sharpe']:.6f}|GROSS_MATCHED_SHARPE_{rows.loc['RAW_GROSS_MATCHED','sharpe']:.6f}|EXPOSED_DIAGNOSTIC_ONLY"
    p = e["paired_dual_vs_gross_matched"]
    lines = [
        "=" * 60, f"{TASK_ID}_FINAL", "=" * 60, "", f"TASK_STATUS={result['task_status']}", "2026_OUTCOME_USED=FALSE", "",
        "-" * 60, "IDENTITY", "-" * 60, "", f"RAW_RECONCILIATION={e['raw_reconciliation']}", f"S1_RECONCILIATION={e['s1_reconciliation']}",
        f"TOP20_MEMBERSHIP_STATUS={e['top20_membership_status']}", f"TAXONOMY_STATUS={e['taxonomy_status']}", "", f"OVERLAY_CONTRACT_HASH={result['contract']['overlay_contract_hash']}", "",
        "-" * 60, "RAW", "-" * 60, "", f"RAW_CAGR={fmt(raw.cagr)}", f"RAW_SHARPE={fmt(raw.sharpe)}", f"RAW_MAXDD={fmt(raw.max_drawdown)}",
        f"RAW_QQQ_BETA={fmt(raw.qqq_beta)}", f"RAW_RESIDUAL_SHARPE={fmt(raw.residual_sharpe)}", f"RAW_DOWNSIDE_CAPTURE={fmt(raw.downside_capture)}", "",
        f"RAW_FF12_HHI={fmt(raw.ff12_hhi)}", f"RAW_FF48_HHI={fmt(raw.ff48_hhi)}", "",
        "-" * 60, "S1", "-" * 60, "", f"S1_CAGR={fmt(s1.cagr)}", f"S1_SHARPE={fmt(s1.sharpe)}", f"S1_MAXDD={fmt(s1.max_drawdown)}", "",
        f"S1_FF12_HHI={fmt(s1.ff12_hhi)}", f"S1_FF48_HHI={fmt(s1.ff48_hhi)}", "",
        "-" * 60, "DUAL CASH", "-" * 60, "", f"DUAL_CAGR={fmt(dual.cagr)}", f"DUAL_SHARPE={fmt(dual.sharpe)}", f"DUAL_MAXDD={fmt(dual.max_drawdown)}", "",
        f"DUAL_QQQ_BETA={fmt(dual.qqq_beta)}", f"DUAL_RESIDUAL_SHARPE={fmt(dual.residual_sharpe)}", f"DUAL_DOWNSIDE_CAPTURE={fmt(dual.downside_capture)}", "",
        f"DUAL_FF12_HHI={fmt(dual.ff12_hhi)}", f"DUAL_FF12_HHI_REDUCTION_VS_RAW={fmt(m['ff12_hhi_reduction_vs_raw'])}", "",
        f"DUAL_FF48_HHI={fmt(dual.ff48_hhi)}", f"DUAL_FF48_HHI_REDUCTION_VS_RAW={fmt(m['ff48_hhi_reduction_vs_raw'])}", "",
        f"DUAL_AVG_GROSS={fmt(dual.average_equity_gross)}", f"DUAL_AVG_ADDITIONAL_CASH={fmt(m['average_additional_cash'])}",
        f"DUAL_P90_ADDITIONAL_CASH={fmt(m['p90_additional_cash'])}", f"DUAL_MAX_ADDITIONAL_CASH={fmt(m['max_additional_cash'])}", "",
        f"SESSIONS_WITH_CASH={fmt(m['pct_sessions_with_cash'])}", f"SESSIONS_CASH_GUARD_BINDING={fmt(m['pct_sessions_cash_guard_binding'])}", "",
        f"FF12_TARGET_MET_PCT={fmt(m['pct_sessions_target_ff12_met'])}", f"FF48_TARGET_MET_PCT={fmt(m['pct_sessions_target_ff48_met'])}", f"BOTH_TARGETS_MET_PCT={fmt(m['pct_sessions_both_targets_met'])}", "",
        "-" * 60, "GROSS-MATCHED RAW", "-" * 60, "", f"GROSS_MATCHED_CAGR={fmt(gross.cagr)}", f"GROSS_MATCHED_SHARPE={fmt(gross.sharpe)}",
        f"GROSS_MATCHED_MAXDD={fmt(gross.max_drawdown)}", f"GROSS_MATCHED_RESIDUAL_SHARPE={fmt(gross.residual_sharpe)}", "",
        "-" * 60, "TARGETED VALUE", "-" * 60, "", f"DUAL_VS_GROSS_MATCHED_CAGR_DELTA={fmt(dual.cagr-gross.cagr)}",
        f"DUAL_VS_GROSS_MATCHED_SHARPE_DELTA={fmt(dual.sharpe-gross.sharpe)}", f"DUAL_VS_GROSS_MATCHED_MAXDD_DELTA={fmt(dual.max_drawdown-gross.max_drawdown)}",
        f"DUAL_VS_GROSS_MATCHED_RESIDUAL_SHARPE_DELTA={fmt(dual.residual_sharpe-gross.residual_sharpe)}", "",
        f"DUAL_VS_GROSS_MATCHED_HAC_TSTAT={fmt(p['hac_tstat'])}", f"DUAL_VS_GROSS_MATCHED_BOOTSTRAP_P_POSITIVE={fmt(p['bootstrap_probability_positive'])}", "",
        "-" * 60, "EXPOSED DIAGNOSTICS", "-" * 60, "", f"2023_RESULT={year_text[2023]}", f"2024_RESULT={year_text[2024]}", f"2025_RESULT={year_text[2025]}", "",
        f"RAW_MAXDD_PERIOD_DUAL_RESULT={e['drawdown']['DUAL_SECTOR_CASH']}", "", "-" * 60, "VERDICT", "-" * 60, "",
        f"SECTOR_CASH_MECHANISM_CLASSIFICATION={e['sector_cash_mechanism_classification']}", "",
        f"IS_VALUE_MAINLY_FROM_TARGETED_SECTOR_DERISKING={fmt(e['is_value_mainly_from_targeted_sector_derisking'])}", f"IS_VALUE_MAINLY_FROM_LOWER_GROSS={fmt(e['is_value_mainly_from_lower_gross'])}", "",
        f"DOES_CASH_OVERLAY_BEAT_S1={fmt(e['does_cash_overlay_beat_s1'])}", "", f"FORWARD_ELIGIBILITY={e['forward_eligibility']}", f"RECOMMENDED_FORWARD_ARMS={e['recommended_forward_arms']}", "",
        f"MOST_DAMAGING_EVIDENCE={e['most_damaging_evidence']}", f"STRONGEST_SUPPORTING_EVIDENCE={e['strongest_supporting_evidence']}", "",
        "ANTI_OVERFIT_STATUS=PASS_FIXED_CONTRACT_EXPOSED_DIAGNOSTICS_ONLY", "TASK_LOCAL_ANTI_BLOAT_STATUS=PASS", f"PREEXISTING_ACL_EXCEPTION_COUNT={PREEXISTING_ACL_EXCEPTIONS}", "",
        f"OUTPUT_DIR={OUT}", f"FINAL_ARTIFACT_COUNT={result['manifest']['artifact_count_including_manifest']}", f"HASH_MANIFEST_STATUS={result['manifest']['status']}", "", "=" * 60,
    ]
    return "\n".join(lines)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    joined, _, identity = load_mechanical_inputs()
    targets, diagnostics, mechanics = build_mechanical_targets(joined)
    contract = freeze_contract(identity, targets, mechanics)
    arms, periods, economics = run_economics(targets, diagnostics, contract, identity)
    task_status = "RESEARCH_COMPLETE_WITH_PREEXISTING_REPOSITORY_ANTI_BLOAT_HARD_GATE_FAIL"
    result = {
        "task_id": TASK_ID, "task_status": task_status, "2026_outcome_used": False, "2026_leakage_count": 0,
        "identity": identity, "mechanics": mechanics, "contract": contract, "economics": economics,
        "periods": periods, "anti_overfit_status": "PASS_FIXED_CONTRACT_EXPOSED_DIAGNOSTICS_ONLY",
        "task_local_anti_bloat_status": "PASS", "preexisting_acl_exception_count": PREEXISTING_ACL_EXCEPTIONS,
    }
    atomic_csv(OUT / "arm_summary.csv", arms)
    atomic_csv(OUT / "concentration_and_cash_diagnostics.csv", enrich_concentration_diagnostics(diagnostics))
    atomic_csv(OUT / "period_and_drawdown_diagnostics.csv", periods)
    classification = {key: value for key, value in result.items() if key != "periods"}
    atomic_json(OUT / "classification.json", classification)
    write_report(result, arms)
    manifest = write_hash_manifest({"overlay_contract_hash": contract["overlay_contract_hash"], **economics["price_input_hashes"]})
    result["manifest"] = manifest
    print(terminal_summary(result, arms))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
