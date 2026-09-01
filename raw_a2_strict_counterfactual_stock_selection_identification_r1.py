from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


TASK = "RAW_A2_STRICT_COUNTERFACTUAL_STOCK_SELECTION_IDENTIFICATION_R1"
ROOT = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK
FOUNDATION = RESULTS / "A2_FREE_PIT_SECURITY_IDENTITY_SIC_FF48_AND_FACTOR_RISK_FOUNDATION_R1"
TAXONOMY_TASK = RESULTS / "A2_COUNTERFACTUAL_TAXONOMY_REMAINING_GAP_RESOLUTION_R1"
A2_ROOT = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2"
TOP40_ROOT = RESULTS / "A2_AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1"
R4_ROOT = RESULTS / "ABCDE_A2_R4_PORTFOLIO_TRANSLATION_USING_HGB_INCUMBENT"
QFQ_ROOT = Path(r"D:\us-tech-quant-data\moomoo\source\prices_qfq")

TAXONOMY = TAXONOMY_TASK / "updated_pit_sec_sic_ff12_ff48_surface.parquet"
FACTOR = FOUNDATION / "security_factor_risk_surface.parquet"
TOP20 = A2_ROOT / "top20_selections.parquet"
TOP40 = TOP40_ROOT / "raw_a2_top40_membership_checkpoint.parquet"
FETCH_LEDGER = FOUNDATION / "moomoo_fetch_ledger.parquet"
REGISTRY_CONTEXT = OUT / "task_registry_context.json"
CONTRACT_PATH = OUT / "counterfactual_identification_contract.json"
CONTRACT_SHA_PATH = OUT / "counterfactual_identification_contract_sha256.txt"
ASSIGNMENTS = OUT / "matched_pairs_outcome_blind.parquet"
PREPARED_SAMPLE = OUT / "outcome_blind_analysis_sample.parquet"

REGISTRY_BASE_HEAD = "83491f866e9bedf6178c2cd0b38d72b13c694830c89de1293fc3b38a4d231587"
RAW_A2_ENTITY_ID = "RAW_A2_HGB_BASELINE"
RAW_A2_FINGERPRINT = "0abead89334ad578eff4683f0a3d1878e7e6c6b1daf157298ca0e7322f9ebfcb"
TAXONOMY_SHA = "c49b69615e16e617f4c460e30dbc669d51b1867c93e9ab5ef9c346984faea8f0"
FACTOR_SHA = "2d5df2e69d31909a89312d4236eab36055e543fbd1a0a9f2b972c03222922e7a"
TOP20_SHA = "5e5203fdcd9a1e53fe1e2d64cd8c1adb78df4bd7acc733394d4dbd62392b8b20"
TOP40_SHA = "1e6fa12b3f8d1144ef0337d343244424f44c27930e8e405b622885c0ae625a17"
EXPECTED_QFQ = {
    2020: "f9acd32fa2878458577b7fd2a8eff8d3f07acf13fc32c4323754a07265bc24fe",
    2021: "c8fd7c684fe7ef54705b99c3e6bd59c810d26af94f9dc27cf1ed7df4b32d5865",
    2022: "3b16247910d78e3961ff94c6c9d9030afaf200f3a30ae22205b0c5042483e588",
    2023: "a5a35422629920b7f5d063acabbb04f0ad410ec9f7e504de7daadd3b9d249bf6",
    2024: "7e14eb6735e7660e6895ab1a9a4ee86fa3ed1bd3ea976c56aeecfd75411e5eb8",
    2025: "b8a8abb5a8bdd7cbf9cf44ebba2f54bc09b60612c6fd8a7b7951aa064f9abc89",
}
MATCH_COVARIATES = ["beta_spy", "beta_qqq_orth", "beta_soxx_orth", "realized_vol_60", "adv60"]
HAC_LAGS = 5
PLACEBO_REPLICATIONS = 1000
PLACEBO_SEED = 271828
RANK_SHUFFLE_SEED = 314159


class ContractError(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise ContractError(f"{code}:{detail}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def value_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path: Path, value: Any) -> None:
    atomic_bytes(path, json.dumps(clean_json(value), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n")


def write_text(path: Path, value: str) -> None:
    atomic_bytes(path, value.encode("utf-8"))


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(descriptor)
    try:
        frame.to_parquet(name, index=False)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(descriptor)
    try:
        frame.to_csv(name, index=False, encoding="utf-8")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def ols_hac(y: Iterable[float], factors: np.ndarray | None = None, lags: int = HAC_LAGS) -> dict[str, Any]:
    """Raw-A2 canonical Bartlett HAC with n/(n-k) finite-sample correction."""
    yv = np.asarray(list(y), dtype=float)
    fv = np.empty((len(yv), 0), dtype=float) if factors is None else np.asarray(factors, dtype=float)
    if fv.ndim == 1:
        fv = fv[:, None]
    mask = np.isfinite(yv) & np.isfinite(fv).all(axis=1)
    yv, fv = yv[mask], fv[mask]
    x = np.column_stack([np.ones(len(yv)), fv])
    require(len(yv) > x.shape[1] + lags, "HAC_SAMPLE_TOO_SHORT", len(yv))
    inv = np.linalg.pinv(x.T @ x)
    coef = inv @ x.T @ yv
    residual = yv - x @ coef
    n, k = x.shape
    scores = x * residual[:, None]
    meat = scores.T @ scores
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1.0)
        gamma = scores[lag:].T @ scores[:-lag]
        meat += weight * (gamma + gamma.T)
    covariance = (n / (n - k)) * inv @ meat @ inv
    se = np.sqrt(np.clip(np.diag(covariance), 0.0, None))
    centered = yv - yv.mean()
    tss = float(centered @ centered)
    r2 = 1.0 - float(residual @ residual) / tss if tss > 0 else np.nan
    residual_vol = float(residual.std(ddof=0) * math.sqrt(252))
    return {
        "n": n,
        "k": k,
        "coef": coef,
        "residual": residual,
        "se": se,
        "t": np.divide(coef, se, out=np.full_like(coef, np.nan), where=se > 0),
        "r2": r2,
        "alpha_daily": float(coef[0]),
        "alpha_annualized": float(coef[0] * 252),
        "alpha_t_hac": float(coef[0] / se[0]) if se[0] > 0 else np.nan,
        "ci_low": float(coef[0] - 1.96 * se[0]),
        "ci_high": float(coef[0] + 1.96 * se[0]),
        "residual_sharpe": float((coef[0] + residual).mean() * 252 / residual_vol) if residual_vol > 0 else np.nan,
    }


def smd(treatment: Iterable[float], control: Iterable[float]) -> float:
    a = np.asarray(list(treatment), dtype=float)
    b = np.asarray(list(control), dtype=float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < 2 or len(b) < 2:
        return np.nan
    pooled = math.sqrt((float(a.var(ddof=1)) + float(b.var(ddof=1))) / 2.0)
    return float((a.mean() - b.mean()) / pooled) if pooled > 0 else 0.0


def positive_share(values: pd.Series, n: int) -> float:
    positive = values.loc[values > 0].sort_values(ascending=False)
    total = float(positive.sum())
    return float(positive.head(n).sum() / total) if total > 0 else np.nan


def load_structural_prices() -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    pieces: list[pd.DataFrame] = []
    manifest: list[dict[str, Any]] = []
    for year, expected in EXPECTED_QFQ.items():
        path = QFQ_ROOT / f"year={year}" / "prices.parquet"
        actual = sha256_file(path)
        require(actual == expected, "QFQ_HASH_MISMATCH", path)
        part = pd.read_parquet(path, columns=["ticker", "trade_date", "autype", "source"])
        part["trade_date"] = pd.to_datetime(part.trade_date).dt.normalize()
        require(part.trade_date.max() <= pd.Timestamp("2025-12-31"), "POST2025_PRICE_KEY", path)
        pieces.append(part)
        manifest.append({"path": str(path), "sha256": actual, "classification": "SAFE_PRE2026"})
    base = pd.concat(pieces, ignore_index=True)
    base["ticker"] = base.ticker.astype(str).str.upper()
    ledger_hash = sha256_file(FETCH_LEDGER)
    ledger = pd.read_parquet(FETCH_LEDGER, columns=["status", "artifact_path", "sha256", "ticker", "requested_end"])
    additions: list[pd.DataFrame] = []
    cache_manifest: list[dict[str, Any]] = []
    cache_root = (FOUNDATION / "provider_cache" / "moomoo_qfq").resolve()
    for row in ledger.loc[ledger.status.eq("PASS_FETCHED_AND_HASH_VERIFIED")].itertuples(index=False):
        path = Path(str(row.artifact_path)).resolve()
        require(path.is_relative_to(cache_root), "UNAPPROVED_PROVIDER_CACHE", path)
        require(str(row.requested_end) <= "2025-12-31", "POST2025_PROVIDER_REQUEST", path)
        actual = sha256_file(path)
        require(actual == str(row.sha256), "PROVIDER_CACHE_HASH_MISMATCH", path)
        frame = pd.read_parquet(path, columns=["ticker", "trade_date", "autype", "source"])
        frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.normalize()
        require(frame.trade_date.max() <= pd.Timestamp("2025-12-31"), "POST2025_PROVIDER_KEY", path)
        additions.append(frame)
        cache_manifest.append({"path": str(path), "sha256": actual, "classification": "SAFE_PRE2026_TASK_CACHE"})
    if additions:
        extra = pd.concat(additions, ignore_index=True)
        extra["ticker"] = extra.ticker.astype(str).str.upper()
        base_keys = set(base[["ticker", "trade_date"]].itertuples(index=False, name=None))
        require(not any(key in base_keys for key in extra[["ticker", "trade_date"]].itertuples(index=False, name=None)), "PROVIDER_CACHE_DUPLICATES_BASE")
        base = pd.concat([base, extra], ignore_index=True)
    require(not base.duplicated(["ticker", "trade_date"]).any(), "PRICE_KEY_DUPLICATE")
    manifest.append({"path": str(FETCH_LEDGER), "sha256": ledger_hash, "classification": "SAFE_STRUCTURAL_LEDGER"})
    manifest.extend(cache_manifest)
    return base.sort_values(["ticker", "trade_date"], kind="mergesort").reset_index(drop=True), manifest


def load_outcome_prices() -> pd.DataFrame:
    """Called only after the contract and its SHA have been verified."""
    pieces: list[pd.DataFrame] = []
    for year, expected in EXPECTED_QFQ.items():
        path = QFQ_ROOT / f"year={year}" / "prices.parquet"
        require(sha256_file(path) == expected, "QFQ_HASH_CHANGED_AFTER_FREEZE", path)
        part = pd.read_parquet(path, columns=["ticker", "trade_date", "open", "autype", "source"])
        part["trade_date"] = pd.to_datetime(part.trade_date).dt.normalize()
        pieces.append(part)
    base = pd.concat(pieces, ignore_index=True)
    base["ticker"] = base.ticker.astype(str).str.upper()
    ledger = pd.read_parquet(FETCH_LEDGER, columns=["status", "artifact_path", "sha256", "requested_end"])
    additions: list[pd.DataFrame] = []
    cache_root = (FOUNDATION / "provider_cache" / "moomoo_qfq").resolve()
    for row in ledger.loc[ledger.status.eq("PASS_FETCHED_AND_HASH_VERIFIED")].itertuples(index=False):
        path = Path(str(row.artifact_path)).resolve()
        require(path.is_relative_to(cache_root), "UNAPPROVED_PROVIDER_CACHE", path)
        require(sha256_file(path) == str(row.sha256), "PROVIDER_CACHE_HASH_CHANGED", path)
        frame = pd.read_parquet(path, columns=["ticker", "trade_date", "open", "autype", "source"])
        frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.normalize()
        additions.append(frame)
    if additions:
        extra = pd.concat(additions, ignore_index=True)
        extra["ticker"] = extra.ticker.astype(str).str.upper()
        base_keys = set(base[["ticker", "trade_date"]].itertuples(index=False, name=None))
        require(not any(key in base_keys for key in extra[["ticker", "trade_date"]].itertuples(index=False, name=None)), "PROVIDER_CACHE_DUPLICATES_BASE")
        base = pd.concat([base, extra], ignore_index=True)
    require(base.trade_date.max() <= pd.Timestamp("2025-12-31"), "POST2025_OUTCOME_READ")
    require(not base.duplicated(["ticker", "trade_date"]).any(), "OUTCOME_PRICE_DUPLICATE")
    base["open"] = pd.to_numeric(base.open, errors="coerce")
    return base.sort_values(["ticker", "trade_date"], kind="mergesort").reset_index(drop=True)


def calendar_map(signal_dates: Iterable[pd.Timestamp], qqq_dates: Iterable[pd.Timestamp]) -> dict[pd.Timestamp, tuple[pd.Timestamp, pd.Timestamp]]:
    calendar = pd.DatetimeIndex(sorted(pd.Timestamp(x) for x in set(qqq_dates)))
    result: dict[pd.Timestamp, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for signal in sorted(pd.Timestamp(x) for x in set(signal_dates)):
        position = int(np.searchsorted(calendar.to_numpy(), np.datetime64(signal), side="right"))
        if position + 1 < len(calendar):
            entry, exit_date = pd.Timestamp(calendar[position]), pd.Timestamp(calendar[position + 1])
            if exit_date <= pd.Timestamp("2025-12-31"):
                result[signal] = (entry, exit_date)
    return result


def missingness_rows(surface: pd.DataFrame, factor: pd.DataFrame) -> pd.DataFrame:
    work = surface.merge(
        factor[["decision_date", "canonical_security_id", "estimator_status", "realized_vol_60", "adv60"]],
        on=["decision_date", "canonical_security_id"], how="left", validate="one_to_one",
    )
    work["mapped"] = work.ff48_code.notna()
    work["year"] = work.decision_date.dt.year.astype(str)
    work["rank_bucket"] = pd.cut(work.a2_rank, [-np.inf, 20, 40, 100, 200, np.inf], labels=["RANK_1_20", "RANK_21_40", "RANK_41_100", "RANK_101_200", "RANK_GT_200"]).astype(str)
    work["selection_scope"] = np.where(work.a2_rank.le(20), "RANK_LE_20", "RANK_GT_20")
    work["factor_status"] = work.estimator_status.fillna("MISSING")
    for column, output in (("realized_vol_60", "volatility_bucket"), ("adv60", "liquidity_bucket")):
        values = work[column]
        try:
            work[output] = pd.qcut(values, 4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop").astype(str)
        except ValueError:
            work[output] = "UNAVAILABLE"
        work.loc[values.isna(), output] = "UNAVAILABLE"
    rows: list[dict[str, Any]] = []
    for dimension in ["year", "rank_bucket", "selection_scope", "factor_status", "volatility_bucket", "liquidity_bucket"]:
        for level, group in work.groupby(dimension, dropna=False, sort=True):
            mapped = int(group.mapped.sum())
            rows.append({"dimension": dimension, "level": str(level), "total": len(group), "mapped": mapped, "unmapped": len(group) - mapped, "mapping_coverage": mapped / len(group)})
    for year in (2020, 2021, 2022):
        rows.append({"dimension": "year", "level": str(year), "total": 0, "mapped": 0, "unmapped": 0, "mapping_coverage": np.nan})
    for dimension, reason in [
        ("listing_age", "UNAVAILABLE_NO_AUTHORITATIVE_FULL_SAMPLE_LISTING_DATE_FIELD"),
        ("exchange", "UNAVAILABLE_NULL_IN_CURRENT_STRICT_SURFACE"),
        ("market_cap", "UNAVAILABLE_NO_CERTIFIED_PIT_MARKET_CAP"),
        ("issuer_security_type", "UNAVAILABLE_NO_CERTIFIED_FULL_SAMPLE_FIELD"),
    ]:
        rows.append({"dimension": dimension, "level": reason, "total": len(work), "mapped": int(work.mapped.sum()), "unmapped": int((~work.mapped).sum()), "mapping_coverage": float(work.mapped.mean())})
    return pd.DataFrame(rows).sort_values(["dimension", "level"], kind="mergesort").reset_index(drop=True)


def match_outcome_blind(sample: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    valid = sample.ff48_code.notna() & sample.return_key_available & sample[MATCH_COVARIATES].notna().all(axis=1)
    selected_keys = set(sample.loc[sample.is_selected, ["decision_date", "canonical_security_id"]].itertuples(index=False, name=None))
    pairs: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for (date, ff48), group in sample.groupby(["decision_date", "ff48_code"], dropna=False, sort=True):
        selected = group.loc[group.is_selected].sort_values("canonical_security_id", kind="mergesort")
        eligible = group.loc[valid.loc[group.index]].copy()
        controls = eligible.loc[~eligible.is_selected].sort_values("canonical_security_id", kind="mergesort")
        for treatment in selected.itertuples(index=False):
            reason = "MATCHED"
            treatment_index = group.index[group.canonical_security_id.eq(treatment.canonical_security_id)][0]
            if pd.isna(ff48):
                reason = "UNMATCHED_FF48_UNMAPPED"
            elif not bool(valid.loc[treatment_index]):
                reason = "UNMATCHED_MISSING_PRICE_OR_COVARIATE"
            elif controls.empty:
                reason = "UNMATCHED_NO_SAME_FF48_CONTROL"
            if reason != "MATCHED":
                audit.append({"decision_date": date, "treatment_security_id": treatment.canonical_security_id, "status": reason})
                continue
            means = eligible[MATCH_COVARIATES].mean()
            stds = eligible[MATCH_COVARIATES].std(ddof=0).replace(0.0, 1.0)
            target = (pd.Series({c: getattr(treatment, c) for c in MATCH_COVARIATES}) - means) / stds
            control_z = (controls[MATCH_COVARIATES] - means) / stds
            distance = np.sqrt(np.square(control_z.to_numpy(float) - target.to_numpy(float)).sum(axis=1))
            minimum = float(distance.min())
            tied = controls.loc[np.isclose(distance, minimum, rtol=0.0, atol=1e-15)].sort_values("canonical_security_id", kind="mergesort")
            control = tied.iloc[0]
            require((date, str(control.canonical_security_id)) not in selected_keys, "SELECTED_CONTROL_LEAKAGE")
            row = {
                "decision_date": date, "entry_date": treatment.entry_date, "exit_date": treatment.exit_date,
                "ff48_code": float(ff48), "ff48_name": treatment.ff48_name,
                "treatment_security_id": treatment.canonical_security_id, "treatment_ticker": treatment.ticker_at_date,
                "control_security_id": control.canonical_security_id, "control_ticker": control.ticker_at_date,
                "distance": minimum,
            }
            for covariate in MATCH_COVARIATES:
                row[f"treatment_{covariate}"] = getattr(treatment, covariate)
                row[f"control_{covariate}"] = control[covariate]
            pairs.append(row)
            audit.append({"decision_date": date, "treatment_security_id": treatment.canonical_security_id, "status": "MATCHED"})
    return pd.DataFrame(pairs).sort_values(["decision_date", "treatment_security_id"], kind="mergesort").reset_index(drop=True), pd.DataFrame(audit)


def contract(input_manifest: dict[str, Any], runner_sha: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0", "task_id": TASK, "contract_status": "FROZEN_BEFORE_CURRENT_OUTCOME_VALUE_READ",
        "base_registry_head": REGISTRY_BASE_HEAD,
        "raw_a2": {"entity_id": RAW_A2_ENTITY_ID, "specification_fingerprint": RAW_A2_FINGERPRINT, "rank_direction": "RANK_1_IS_HIGHEST", "baseline_mutation_allowed": False},
        "sample": {"authoritative_denominator": 313668, "legal_decision_dates": 752, "strict_ff48_mapped": 297937, "structural_unmapped": 15731, "structural_unmapped_securities": 44, "economic_signal_dates": "PHYSICAL_TOP20_750_DATES", "conclusion_scope": "STRICT_PIT_FF48_MAPPED_COUNTERFACTUAL_SURFACE"},
        "primary_return": {"horizon_legal_sessions": 1, "fallback_primary_horizon_used": False, "entry": "FIRST_QQQ_LEGAL_SESSION_OPEN_STRICTLY_AFTER_SIGNAL", "exit": "FOLLOWING_QQQ_LEGAL_SESSION_OPEN", "economic_end": "2025-12-31", "no_fill": True, "no_horizon_search": True},
        "q1": {"group": ["decision_date", "ff48_code"], "rank_input": "authoritative_a2_rank", "valid_group": "N_GE_2_AND_NONCONSTANT_RANK", "percentile": "(N_WITHIN_ORDER_RANK)/(N-1) expressed as (N-r)/(N-1), best=1", "bucket": "min(10,floor(10*p)+1)", "bucket_count": 10, "primary": ["D10_MINUS_D1_DATE_EQUAL", "WITHIN_INDUSTRY_IC_DATE_EQUAL"], "search": False},
        "q2": {"exact": ["decision_date", "ff48_code"], "treatment": "PHYSICAL_AUTHORITATIVE_TOP20", "covariates": MATCH_COVARIATES, "unavailable_omitted": ["PIT_MARKET_CAP", "MOMENTUM", "GROWTH", "PROFITABILITY"], "standardization": "WITHIN_CELL_DDOF0_ZERO_VARIANCE_ZERO_CONTRIBUTION", "distance": "EQUAL_WEIGHT_STANDARDIZED_EUCLIDEAN", "ratio": "1_TO_1", "replacement": True, "tie": "CANONICAL_SECURITY_ID_LEXICAL", "no_rematch_after_outcome": True, "aggregate": "DATE_EQUAL_WEIGHT", "search": False},
        "q3": {"stack_a": ["SPY", "QQQ_ORTHOGONAL_TO_SPY", "SOXX_ORTHOGONAL_TO_SPY_QQQ"], "factor_returns": "ALIGNED_QFQ_OPEN_TO_OPEN", "orthogonalization": "FULL_EVALUATION_SAMPLE_SEQUENTIAL_FIXED_CANONICAL", "stack_b": "UNTESTABLE_AUTHORITATIVE_FACTOR_DATA_UNAVAILABLE", "factor_subset_search": False},
        "q4": {"benchmark": "STRICT_PIT_FF48_MAPPED_ELIGIBLE_UNIVERSE_EQUAL_WEIGHT", "portfolio": "PHYSICAL_TOP20_EQUAL_5_PERCENT", "complete_date_only": True, "renormalize_unmapped_holdings": False, "method": "BRINSON_FACHLER", "closure_tolerance": 1e-12},
        "q5": {"years": [2020, 2021, 2022, 2023, 2024, 2025], "concentration_denominator": "POSITIVE_CONTRIBUTION_MASS", "leave_out": ["LEAVE_ONE_NATURAL_YEAR_OUT", "REMOVE_TOP_5_SECURITY_CONTRIBUTORS", "REMOVE_TOP_10_DATE_CONTRIBUTORS"], "no_iterative_deletion": True},
        "q6": {"placebo_repetitions": PLACEBO_REPLICATIONS, "placebo_seed": PLACEBO_SEED, "placebo_primary": "FULL_SAMPLE_DATE_EQUAL_WEIGHTED_SELECTION_RETURN", "preserve": ["decision_date", "ff48_selection_count", "eligible_set"], "rank_shuffle_repetitions": PLACEBO_REPLICATIONS, "rank_shuffle_seed": RANK_SHUFFLE_SEED, "empirical_p": "(1+COUNT_NULL_GE_ACTUAL)/(N+1)"},
        "inference": {"method": "BARTLETT_NEWEY_WEST", "lags": HAC_LAGS, "finite_sample_correction": "N_OVER_N_MINUS_K", "confidence": 0.95, "source_sha256": "731079e519f3610fa18d76bea8f2d65dd15800a4679fc16ebf7896849756218c", "known_alternate_not_run": "HHI_R2_OMITS_FINITE_SAMPLE_CORRECTION"},
        "evidence_logic": {
            "q1_supported": "IC>0 AND D10-D1>0 AND MAX_T>=1.96", "q1_weak": "BOTH>0 AND MAX_T>=1.0",
            "q2_supported": "EFFECT>0,T>=1.96,MATCH_RATE>=0.80,MAX_POST_SMD<=0.25", "q2_weak": "EFFECT>0,T>=1.0,QUALITY_ADEQUATE",
            "q3_supported": "STACK_A_ALPHA>0 AND T>=1.96", "q3_weak": "ALPHA>0 AND T>=1.0",
            "q4_supported": "SELECTION_EFFECT>0 AND HAC_T>=1.96 AND CLOSURE", "q4_weak": "SELECTION_EFFECT>0 AND CLOSURE",
            "q5_supported": "POSITIVE_YEARS>=2/3,TOP10_DATE<0.5,TOP5_SECURITY<0.5,TOP1_FF48<0.5,LOYO_POSITIVE>=2/3,FIXED_REMOVALS_POSITIVE",
            "q6_supported": "PRIMARY_PLACEBO_P<=0.05", "q6_weak": "PRIMARY_PLACEBO_P<=0.10",
            "verdict_precedence": ["INTEGRITY_OR_MATERIAL_QUALITY_BLOCKING=>E", "ALL_SIX_SUPPORTED=>A", "MEANINGFUL_SELECTION_AND_Q5_FAIL=>C", "Q1_Q2_DIRECTIONAL_Q6_WEAK_OR_SUPPORTED_BROAD_BUT_Q3_OR_Q4_WEAK=>B", "Q1_Q2_Q6_NOT_SUPPORTED=>D", "OTHER_CONFLICTING_MEANINGFUL=>C"],
        },
        "anti_bloat": {"primary_hypothesis_count": 1, "new_feature_count": 0, "new_predictive_model_count": 0, "new_predictive_model_fit_count": 0, "new_horizon_search_count": 0, "new_matching_covariate_search_count": 0, "new_matching_method_search_count": 0, "new_bucket_count_search_count": 0, "new_factor_subset_search_count": 0, "new_factor_window_search_count": 0, "new_outlier_rule_search_count": 0, "new_portfolio_spec_count": 0, "new_optimizer_search_count": 0, "new_threshold_search_count": 0, "new_taxonomy_count": 0, "new_data_source_count": 0, "moomoo_history_request_count": 0},
        "temporal_counters": {"post_2025_realized_label_metric_read_count": 0, "post_2025_model_evaluation_metric_read_count": 0, "post_2025_outcome_derived_metadata_read_count": 0, "2026_economic_outcome_read_count": 0, "holdout_peek_count": 0, "mixed_source_content_open_count": 0},
        "prohibitions": ["NO_2026", "NO_RV", "NO_MODEL_FIT", "NO_NEW_DATA", "NO_OUTCOME_ADAPTATION", "NO_R2"],
        "authoritative_input_manifest_sha256": value_sha256(input_manifest), "runner_sha256": runner_sha,
    }


def prepare() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    require(not CONTRACT_PATH.exists(), "CONTRACT_ALREADY_EXISTS_REFUSE_REFREEZE", CONTRACT_PATH)
    require(REGISTRY_CONTEXT.exists(), "REGISTRY_CONTEXT_MISSING")
    context = json.loads(REGISTRY_CONTEXT.read_text(encoding="utf-8"))
    require(context.get("registry_head_sha256") == REGISTRY_BASE_HEAD, "REGISTRY_CONTEXT_HEAD_MISMATCH")
    core = {
        TAXONOMY: TAXONOMY_SHA, FACTOR: FACTOR_SHA, TOP20: TOP20_SHA, TOP40: TOP40_SHA,
        TAXONOMY_TASK / "taxonomy_surface_manifest.json": "65522ecb077e62f0be7ddf6d7ac15d6770e1e857daa1367575f11b00e17a0030",
        TAXONOMY_TASK / "counterfactual_readiness.json": "f7cce548b53781ba4315ee986d2cc4fc4477af9f07c737bed179f09953ccad16",
        FOUNDATION / "eligible_keyset_manifest.json": "89ed4aa689e2d6fec834e56187dba339f07cd4ea10da55d110c678c2c4653928",
        FOUNDATION / "factor_stack_contract.json": "46030d9d2ab24df1c8e11a2f81bc3641aace12967da5c9153341a7535f97cace",
        FOUNDATION / "exposure_estimator_contract.json": "15497c2719f202deebc11ca062b947f68d744792593b5a84d54211f787f7cd04",
        R4_ROOT / "a2_r4_portfolio_translation_contract_r1.json": "3d803330dee82a425b2544af16736547befea865dde5967e0de046b2ce83cd9d",
    }
    input_rows: list[dict[str, Any]] = []
    for path, expected in core.items():
        actual = sha256_file(path)
        require(actual == expected, "AUTHORITATIVE_INPUT_HASH_MISMATCH", path)
        input_rows.append({"path": str(path), "sha256": actual, "classification": "SAFE_PRE2026_OR_STRUCTURAL"})
    structural_prices, price_manifest = load_structural_prices()
    input_rows.extend(price_manifest)
    surface = pd.read_parquet(TAXONOMY, columns=["decision_date", "canonical_security_id", "ticker_at_date", "ff48_code", "ff48_name", "taxonomy_status", "a2_rank"])
    surface["decision_date"] = pd.to_datetime(surface.decision_date).dt.normalize()
    surface["ticker_at_date"] = surface.ticker_at_date.astype(str).str.upper()
    require(len(surface) == 313668 and surface.decision_date.nunique() == 752, "CANONICAL_DENOMINATOR_CONFLICT")
    require(not surface.duplicated(["decision_date", "canonical_security_id"]).any(), "CANONICAL_KEY_DUPLICATE")
    require(int(surface.ff48_code.notna().sum()) == 297937, "STRICT_FF48_MAPPED_CONFLICT")
    require(int(surface.loc[surface.ff48_code.isna(), "canonical_security_id"].nunique()) == 44, "STRUCTURAL_UNMAPPED_SECURITY_CONFLICT")
    factor = pd.read_parquet(FACTOR, columns=["decision_date", "canonical_security_id", "ticker_at_date", "estimator_status", *MATCH_COVARIATES])
    factor["decision_date"] = pd.to_datetime(factor.decision_date).dt.normalize()
    require(len(factor) == 313668 and not factor.duplicated(["decision_date", "canonical_security_id"]).any(), "FACTOR_KEYSET_CONFLICT")
    top20 = pd.read_parquet(TOP20, columns=["signal_date", "ticker", "a2_rank"])
    top20["signal_date"] = pd.to_datetime(top20.signal_date).dt.normalize()
    top20["ticker"] = top20.ticker.astype(str).str.upper()
    require(len(top20) == 15000 and top20.signal_date.nunique() == 750, "TOP20_CARDINALITY_CONFLICT")
    require(top20.groupby("signal_date").size().eq(20).all(), "TOP20_DAILY_CARDINALITY")
    joined_top = top20.merge(surface[["decision_date", "ticker_at_date", "a2_rank"]], left_on=["signal_date", "ticker"], right_on=["decision_date", "ticker_at_date"], how="left", suffixes=("_top20", "_surface"), validate="one_to_one")
    require(joined_top.decision_date.notna().all(), "TOP20_NOT_IN_ELIGIBLE_KEYSET")
    require(joined_top.a2_rank_top20.eq(joined_top.a2_rank_surface).all(), "TOP20_RANK_LINEAGE_MISMATCH")
    qqq_dates = structural_prices.loc[structural_prices.ticker.eq("QQQ"), "trade_date"]
    date_map = calendar_map(top20.signal_date.unique(), qqq_dates)
    require(len(date_map) == 750, "PRIMARY_HORIZON_CALENDAR_COVERAGE", len(date_map))
    analysis = surface.loc[surface.decision_date.isin(set(top20.signal_date))].copy()
    analysis = analysis.merge(factor.drop(columns="ticker_at_date"), on=["decision_date", "canonical_security_id"], how="left", validate="one_to_one")
    selected_keys = set(top20[["signal_date", "ticker"]].itertuples(index=False, name=None))
    analysis["is_selected"] = [(d, t) in selected_keys for d, t in analysis[["decision_date", "ticker_at_date"]].itertuples(index=False, name=None)]
    analysis["entry_date"] = analysis.decision_date.map(lambda d: date_map[d][0])
    analysis["exit_date"] = analysis.decision_date.map(lambda d: date_map[d][1])
    price_keys = set(structural_prices[["ticker", "trade_date"]].itertuples(index=False, name=None))
    analysis["entry_key_available"] = [(t, d) in price_keys for t, d in analysis[["ticker_at_date", "entry_date"]].itertuples(index=False, name=None)]
    analysis["exit_key_available"] = [(t, d) in price_keys for t, d in analysis[["ticker_at_date", "exit_date"]].itertuples(index=False, name=None)]
    analysis["return_key_available"] = analysis.entry_key_available & analysis.exit_key_available
    require(int(analysis.is_selected.sum()) == 15000, "TREATMENT_IDENTITY_CONFLICT")
    require(analysis.exit_date.max() <= pd.Timestamp("2025-12-31"), "POST2025_HORIZON")
    atomic_parquet(PREPARED_SAMPLE, analysis.sort_values(["decision_date", "a2_rank", "canonical_security_id"], kind="mergesort"))
    pairs, match_audit = match_outcome_blind(analysis)
    require(not pairs.empty, "NO_MATCHED_PAIRS")
    require(pairs.control_security_id.ne(pairs.treatment_security_id).all(), "SELF_MATCH")
    atomic_parquet(ASSIGNMENTS, pairs)
    atomic_csv(OUT / "outcome_blind_matching_audit.csv", match_audit)
    atomic_csv(OUT / "counterfactual_sample_missingness_report.csv", missingness_rows(surface, factor))
    runner_sha = sha256_file(Path(__file__).resolve())
    input_manifest = {
        "task_id": TASK, "registry_base_head": REGISTRY_BASE_HEAD, "raw_a2_entity_id": RAW_A2_ENTITY_ID,
        "raw_a2_fingerprint": RAW_A2_FINGERPRINT, "files": input_rows,
        "denominator": {"rows": len(surface), "dates": int(surface.decision_date.nunique()), "mapped": int(surface.ff48_code.notna().sum()), "unmapped": int(surface.ff48_code.isna().sum()), "unmapped_securities": int(surface.loc[surface.ff48_code.isna(), "canonical_security_id"].nunique())},
        "analysis_signal_dates": int(analysis.decision_date.nunique()), "outcome_blind_matched_pairs": len(pairs),
        "temporal_firewall": {"economic_end": "2025-12-31", "risk_registry": "DENYLISTED_DO_NOT_OPEN", "open_then_filter": False, "mixed_source_content_open_count": 0},
    }
    write_json(OUT / "authoritative_input_manifest.json", input_manifest)
    frozen = contract(input_manifest, runner_sha)
    write_json(CONTRACT_PATH, frozen)
    contract_sha = sha256_file(CONTRACT_PATH)
    write_text(CONTRACT_SHA_PATH, contract_sha + "\n")
    write_text(OUT / "outcome_blind_design_report.md", f"""# Outcome-blind identification design\n\nContract `{contract_sha}` was frozen before this execution opened any price `open` value or computed any current-task forward return.\n\n- Primary horizon: one legal next-open-to-following-open session; 20-session model-label maturity is not substituted.\n- Q1: one fixed within-FF48 decile/rank-IC design.\n- Q2: one deterministic 1:1 same-date/same-FF48 match on `{', '.join(MATCH_COVARIATES)}`. PIT market cap and momentum were unavailable and were not proxied.\n- Q3: one fixed tradable factor stack. Academic factors are predeclared untestable because the only known physical files are not safely isolated from post-2025 content.\n- Q4: complete-holdings Brinson-Fachler attribution; no renormalization.\n- Q5: fixed concentration and leave-out diagnostics only.\n- Q6: exactly 1,000 industry-consistent selection placebos and 1,000 within-industry rank shuffles with fixed seeds.\n\nThe 15,731 FF48-unmapped observations across 44 securities remain in the denominator and missingness report. No outcome-adaptive redesign is permitted.\n""")
    write_json(OUT / "prepare_summary.json", {"status": "PASS_CONTRACT_FROZEN", "contract_sha256": contract_sha, "runner_sha256": runner_sha, "matched_pairs": len(pairs), "selected_observations": 15000, "post_2025_outcome_read_count": 0, "mixed_source_content_open_count": 0})
    print(f"PREPARE_STATUS=PASS_CONTRACT_FROZEN\nCONTRACT_SHA256={contract_sha}\nOUTCOME_BLIND_MATCHED_PAIRS={len(pairs)}")


def verify_frozen_contract() -> dict[str, Any]:
    require(CONTRACT_PATH.exists() and CONTRACT_SHA_PATH.exists(), "FROZEN_CONTRACT_MISSING")
    expected = CONTRACT_SHA_PATH.read_text(encoding="utf-8").strip()
    require(sha256_file(CONTRACT_PATH) == expected, "FROZEN_CONTRACT_HASH_MISMATCH")
    frozen = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    require(frozen["contract_status"] == "FROZEN_BEFORE_CURRENT_OUTCOME_VALUE_READ", "CONTRACT_NOT_FROZEN")
    require(frozen["runner_sha256"] == sha256_file(Path(__file__).resolve()), "RUNNER_CHANGED_AFTER_CONTRACT_FREEZE")
    require(frozen["primary_return"]["horizon_legal_sessions"] == 1, "PRIMARY_HORIZON_MUTATED")
    require(frozen["q6"]["placebo_repetitions"] == PLACEBO_REPLICATIONS, "PLACEBO_COUNT_MUTATED")
    return frozen


def open_lookup(prices: pd.DataFrame) -> pd.Series:
    valid = prices.open.notna() & np.isfinite(prices.open) & prices.open.gt(0)
    return prices.loc[valid].set_index(["ticker", "trade_date"]).open


def attach_forward_return(sample: pd.DataFrame, lookup: pd.Series, ticker_column: str = "ticker_at_date") -> pd.Series:
    entry = pd.MultiIndex.from_arrays([sample[ticker_column].astype(str).str.upper(), pd.to_datetime(sample.entry_date).dt.normalize()])
    exit_key = pd.MultiIndex.from_arrays([sample[ticker_column].astype(str).str.upper(), pd.to_datetime(sample.exit_date).dt.normalize()])
    start = lookup.reindex(entry).to_numpy(float)
    end = lookup.reindex(exit_key).to_numpy(float)
    result = np.divide(end, start, out=np.full(len(sample), np.nan), where=np.isfinite(start) & np.isfinite(end) & (start > 0)) - 1.0
    return pd.Series(result, index=sample.index)


def q1_within_industry(sample: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    rows: list[pd.DataFrame] = []
    group_stats: list[dict[str, Any]] = []
    for (date, code), group in sample.loc[sample.ff48_code.notna() & sample.future_return.notna()].groupby(["decision_date", "ff48_code"], sort=True):
        if len(group) < 2 or group.a2_rank.nunique() < 2:
            continue
        frame = group.copy()
        order = frame.a2_rank.rank(method="average", ascending=True)
        percentile = (len(frame) - order) / (len(frame) - 1.0)
        frame["within_percentile"] = percentile
        frame["decile"] = np.minimum(10, np.floor(10.0 * percentile).astype(int) + 1)
        ic = frame.a2_rank.mul(-1).corr(frame.future_return, method="spearman")
        means = frame.groupby("decile").future_return.mean()
        spread = float(means.get(10, np.nan) - means.get(1, np.nan)) if 10 in means.index and 1 in means.index else np.nan
        group_stats.append({"decision_date": date, "ff48_code": code, "ff48_name": frame.ff48_name.iloc[0], "observation_count": len(frame), "within_industry_ic": ic, "d10_minus_d1": spread})
        rows.append(frame)
    ranked = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    groups = pd.DataFrame(group_stats)
    require(not ranked.empty and not groups.empty, "Q1_NO_VALID_GROUPS")
    date_series = groups.groupby("decision_date", as_index=False).agg(within_industry_ic=("within_industry_ic", "mean"), d10_minus_d1=("d10_minus_d1", "mean"), industry_count=("ff48_code", "nunique"))
    ic_fit = ols_hac(date_series.within_industry_ic.dropna())
    spread_fit = ols_hac(date_series.d10_minus_d1.dropna())
    bucket_rows = []
    for decile in range(1, 11):
        values = ranked.loc[ranked.decile.eq(decile), "future_return"]
        bucket_rows.append({"metric": f"D{decile}", "mean_future_return": values.mean(), "median_future_return": values.median(), "observation_count": len(values), "date_count": ranked.loc[ranked.decile.eq(decile), "decision_date"].nunique(), "industry_count": ranked.loc[ranked.decile.eq(decile), "ff48_code"].nunique()})
    bucket_rows.extend([
        {"metric": "D10_MINUS_D1", "mean_future_return": date_series.d10_minus_d1.mean(), "median_future_return": date_series.d10_minus_d1.median(), "observation_count": date_series.d10_minus_d1.notna().sum(), "date_count": date_series.loc[date_series.d10_minus_d1.notna(), "decision_date"].nunique(), "industry_count": groups.ff48_code.nunique(), "hac_t": spread_fit["alpha_t_hac"], "ci_low": spread_fit["ci_low"], "ci_high": spread_fit["ci_high"]},
        {"metric": "WITHIN_INDUSTRY_IC", "mean_future_return": date_series.within_industry_ic.mean(), "median_future_return": date_series.within_industry_ic.median(), "observation_count": date_series.within_industry_ic.notna().sum(), "date_count": date_series.loc[date_series.within_industry_ic.notna(), "decision_date"].nunique(), "industry_count": groups.ff48_code.nunique(), "hac_t": ic_fit["alpha_t_hac"], "ci_low": ic_fit["ci_low"], "ci_high": ic_fit["ci_high"]},
    ])
    atomic_csv(OUT / "within_industry_rank_results.csv", pd.DataFrame(bucket_rows))
    by_year = []
    for year in range(2020, 2026):
        year_dates = date_series.loc[date_series.decision_date.dt.year.eq(year)]
        if year_dates.empty:
            by_year.append({"year": year, "status": "NA_NO_AUTHORITATIVE_SAMPLE", "within_industry_ic": np.nan, "d10_minus_d1": np.nan, "date_count": 0})
        else:
            by_year.append({"year": year, "status": "EVALUABLE", "within_industry_ic": year_dates.within_industry_ic.mean(), "d10_minus_d1": year_dates.d10_minus_d1.mean(), "date_count": len(year_dates)})
    atomic_csv(OUT / "within_industry_rank_by_year.csv", pd.DataFrame(by_year))
    by_ff = groups.groupby(["ff48_code", "ff48_name"], as_index=False).agg(within_industry_ic=("within_industry_ic", "mean"), d10_minus_d1=("d10_minus_d1", "mean"), date_count=("decision_date", "nunique"), observation_count=("observation_count", "sum"))
    atomic_csv(OUT / "within_industry_rank_by_ff48.csv", by_ff)
    result = {
        "within_industry_ic": float(date_series.within_industry_ic.mean()), "within_industry_ic_hac_t": ic_fit["alpha_t_hac"],
        "d10_minus_d1": float(date_series.d10_minus_d1.mean()), "d10_minus_d1_hac_t": spread_fit["alpha_t_hac"],
        "monotonicity_violations": int((pd.Series([row["mean_future_return"] for row in bucket_rows[:10]]).diff().dropna() < 0).sum()),
        "positive_ic_years": int(sum(1 for row in by_year if row["status"] == "EVALUABLE" and row["within_industry_ic"] > 0)),
    }
    return result, ranked, groups


def q2_matched(sample: pd.DataFrame, lookup: pd.Series) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    pairs = pd.read_parquet(ASSIGNMENTS)
    require(len(pairs) > 0, "FROZEN_MATCH_ASSIGNMENTS_EMPTY")
    treatment_frame = pairs[["treatment_ticker", "entry_date", "exit_date"]].rename(columns={"treatment_ticker": "ticker_at_date"})
    control_frame = pairs[["control_ticker", "entry_date", "exit_date"]].rename(columns={"control_ticker": "ticker_at_date"})
    pairs["treatment_future_return"] = attach_forward_return(treatment_frame, lookup).to_numpy()
    pairs["control_future_return"] = attach_forward_return(control_frame, lookup).to_numpy()
    require(pairs[["treatment_future_return", "control_future_return"]].notna().all().all(), "OUTCOME_MISSING_AFTER_FROZEN_MATCH_NO_REMATCH")
    pairs["matched_selection_return"] = pairs.treatment_future_return - pairs.control_future_return
    pairs["year"] = pd.to_datetime(pairs.decision_date).dt.year
    atomic_parquet(OUT / "matched_pairs.parquet", pairs)
    date_series = pairs.groupby("decision_date", as_index=False).agg(matched_selection_return=("matched_selection_return", "mean"), pair_count=("matched_selection_return", "size"))
    fit = ols_hac(date_series.matched_selection_return)
    autocorrelations = [date_series.matched_selection_return.autocorr(lag) for lag in range(1, HAC_LAGS + 1)]
    finite_autocorrelations = [float(value) for value in autocorrelations if pd.notna(value)]
    denominator = max(1e-12, 1.0 + 2.0 * sum(finite_autocorrelations))
    effective_observations = min(float(len(date_series)), float(len(date_series) / denominator))
    selected_observations = int(sample.is_selected.sum())
    matched_observations = len(pairs)
    results = pd.DataFrame([
        {"metric": "DATE_EQUAL_WEIGHTED_PRIMARY", "value": date_series.matched_selection_return.mean(), "hac_t": fit["alpha_t_hac"], "ci_low": fit["ci_low"], "ci_high": fit["ci_high"], "observations": len(date_series)},
        {"metric": "PAIR_MEAN", "value": pairs.matched_selection_return.mean(), "observations": len(pairs)},
        {"metric": "PAIR_MEDIAN", "value": pairs.matched_selection_return.median(), "observations": len(pairs)},
        {"metric": "PAIR_POSITIVE_SHARE", "value": (pairs.matched_selection_return > 0).mean(), "observations": len(pairs)},
        {"metric": "ANNUALIZED_ARITHMETIC_EQUIVALENT", "value": date_series.matched_selection_return.mean() * 252, "observations": len(date_series)},
    ])
    atomic_csv(OUT / "matched_control_results.csv", results)
    by_year = []
    for year in range(2020, 2026):
        values = date_series.loc[pd.to_datetime(date_series.decision_date).dt.year.eq(year), "matched_selection_return"]
        by_year.append({"year": year, "status": "EVALUABLE" if len(values) else "NA_NO_AUTHORITATIVE_SAMPLE", "matched_selection_return": values.mean() if len(values) else np.nan, "date_count": len(values), "positive": bool(values.mean() > 0) if len(values) else None})
    by_year_frame = pd.DataFrame(by_year)
    atomic_csv(OUT / "matched_control_by_year.csv", by_year_frame)
    by_ff = pairs.groupby(["ff48_code", "ff48_name"], as_index=False).agg(matched_selection_return=("matched_selection_return", "mean"), median=("matched_selection_return", "median"), pair_count=("matched_selection_return", "size"), date_count=("decision_date", "nunique"))
    atomic_csv(OUT / "matched_control_by_ff48.csv", by_ff)
    valid_pool = sample.loc[sample.ff48_code.notna() & sample.return_key_available & sample[MATCH_COVARIATES].notna().all(axis=1)].copy()
    selected_cells = set(pairs[["decision_date", "ff48_code"]].itertuples(index=False, name=None))
    valid_pool = valid_pool.loc[[(d, c) in selected_cells for d, c in valid_pool[["decision_date", "ff48_code"]].itertuples(index=False, name=None)]]
    balance_rows = []
    for covariate in MATCH_COVARIATES:
        pre_t = valid_pool.loc[valid_pool.is_selected, covariate]
        pre_c = valid_pool.loc[~valid_pool.is_selected, covariate]
        post_t = pairs[f"treatment_{covariate}"]
        post_c = pairs[f"control_{covariate}"]
        balance_rows.append({"covariate": covariate, "pre_match_smd": smd(pre_t, pre_c), "post_match_smd": smd(post_t, post_c), "treatment_mean": post_t.mean(), "control_mean": post_c.mean()})
    balance = pd.DataFrame(balance_rows)
    reuse = pairs.control_security_id.value_counts()
    balance = pd.concat([balance, pd.DataFrame([{"covariate": "__CONTROL_REUSE__", "pre_match_smd": np.nan, "post_match_smd": np.nan, "treatment_mean": reuse.mean(), "control_mean": reuse.max()}])], ignore_index=True)
    atomic_csv(OUT / "matching_balance_report.csv", balance)
    result = {
        "selected_observations": selected_observations, "matched_observations": matched_observations,
        "match_rate": matched_observations / selected_observations, "post_match_max_abs_smd": float(balance.loc[balance.covariate.ne("__CONTROL_REUSE__"), "post_match_smd"].abs().max()),
        "matched_selection_return": float(date_series.matched_selection_return.mean()), "matched_selection_hac_t": fit["alpha_t_hac"],
        "matched_selection_hac_se": float(fit["se"][0]), "matched_selection_ci_low": fit["ci_low"], "matched_selection_ci_high": fit["ci_high"],
        "matched_selection_skew": float(date_series.matched_selection_return.skew()), "matched_selection_excess_kurtosis": float(date_series.matched_selection_return.kurt()),
        "matched_effective_observations": effective_observations,
        "matched_positive_years": int(by_year_frame.loc[by_year_frame.status.eq("EVALUABLE"), "positive"].sum()),
        "max_control_reuse_count": int(reuse.max()), "control_reuse_hhi": float(np.square(reuse / reuse.sum()).sum()),
    }
    return result, pairs, date_series


def aligned_factor_frame(prices: pd.DataFrame, dates: pd.DataFrame) -> pd.DataFrame:
    lookup = open_lookup(prices)
    rows = []
    for row in dates[["decision_date", "entry_date", "exit_date"]].drop_duplicates().itertuples(index=False):
        record = {"decision_date": pd.Timestamp(row.decision_date), "entry_date": pd.Timestamp(row.entry_date), "exit_date": pd.Timestamp(row.exit_date)}
        for ticker in ("SPY", "QQQ", "SOXX"):
            start = lookup.get((ticker, pd.Timestamp(row.entry_date)), np.nan)
            end = lookup.get((ticker, pd.Timestamp(row.exit_date)), np.nan)
            record[ticker] = float(end / start - 1.0) if np.isfinite(start) and np.isfinite(end) and start > 0 else np.nan
        rows.append(record)
    frame = pd.DataFrame(rows).sort_values("decision_date", kind="mergesort")
    require(frame[["SPY", "QQQ", "SOXX"]].notna().all().all(), "FACTOR_OUTCOME_COVERAGE")
    spy = frame.SPY.to_numpy(float)
    qx = np.column_stack([np.ones(len(frame)), spy])
    qcoef = np.linalg.lstsq(qx, frame.QQQ.to_numpy(float), rcond=None)[0]
    frame["QQQ_ORTH"] = frame.QQQ.to_numpy(float) - qx @ qcoef
    sx = np.column_stack([np.ones(len(frame)), spy, frame.QQQ_ORTH.to_numpy(float)])
    scoef = np.linalg.lstsq(sx, frame.SOXX.to_numpy(float), rcond=None)[0]
    frame["SOXX_ORTH"] = frame.SOXX.to_numpy(float) - sx @ scoef
    return frame


def q3_factor_residual(date_series: pd.DataFrame, prices: pd.DataFrame, sample: pd.DataFrame, lookup: pd.Series) -> dict[str, Any]:
    factors = aligned_factor_frame(prices, sample[["decision_date", "entry_date", "exit_date"]])
    aligned = date_series.merge(factors, on="decision_date", validate="one_to_one")
    x = aligned[["SPY", "QQQ_ORTH", "SOXX_ORTH"]].to_numpy(float)
    fit = ols_hac(aligned.matched_selection_return, x)
    rows = [{
        "series": "MATCHED_SELECTION_RETURN", "stack": "STACK_A_TRADABLE", "status": "PASS",
        "alpha_daily": fit["alpha_daily"], "alpha_annualized": fit["alpha_annualized"], "alpha_hac_t": fit["alpha_t_hac"],
        "residual_sharpe": fit["residual_sharpe"], "r_squared": fit["r2"],
        "beta_spy": fit["coef"][1], "beta_qqq_orth": fit["coef"][2], "beta_soxx_orth": fit["coef"][3], "observations": fit["n"],
    }]
    selected = sample.loc[sample.is_selected].copy()
    selected["future_return"] = attach_forward_return(selected, lookup)
    complete_counts = selected.groupby("decision_date").future_return.count()
    raw_dates = complete_counts.loc[complete_counts.eq(20)].index
    raw_series = selected.loc[selected.decision_date.isin(raw_dates)].groupby("decision_date", as_index=False).future_return.mean().rename(columns={"future_return": "raw_a2_return"})
    raw_aligned = raw_series.merge(factors, on="decision_date", validate="one_to_one")
    raw_fit = ols_hac(raw_aligned.raw_a2_return, raw_aligned[["SPY", "QQQ_ORTH", "SOXX_ORTH"]].to_numpy(float))
    rows.append({"series": "RAW_A2_EQUAL_WEIGHT_TOP20_GROSS", "stack": "STACK_A_TRADABLE", "status": "SUPPLEMENTARY_BRIDGE", "alpha_daily": raw_fit["alpha_daily"], "alpha_annualized": raw_fit["alpha_annualized"], "alpha_hac_t": raw_fit["alpha_t_hac"], "residual_sharpe": raw_fit["residual_sharpe"], "r_squared": raw_fit["r2"], "beta_spy": raw_fit["coef"][1], "beta_qqq_orth": raw_fit["coef"][2], "beta_soxx_orth": raw_fit["coef"][3], "observations": raw_fit["n"]})
    rows.append({"series": "MATCHED_SELECTION_RETURN", "stack": "STACK_B_ACADEMIC", "status": "UNTESTABLE_AUTHORITATIVE_FACTOR_DATA_UNAVAILABLE"})
    atomic_csv(OUT / "factor_residual_results.csv", pd.DataFrame(rows))
    diagnostics = {
        "stack_a": {"factor_order": ["SPY", "QQQ_ORTHOGONAL_TO_SPY", "SOXX_ORTHOGONAL_TO_SPY_QQQ"], "orthogonalization": "FULL_SAMPLE_SEQUENTIAL", "observations": fit["n"], "r_squared": fit["r2"], "residual_cumulative_contribution": float(np.prod(1.0 + fit["coef"][0] + fit["residual"]) - 1.0)},
        "stack_b": {"status": "UNTESTABLE_AUTHORITATIVE_FACTOR_DATA_UNAVAILABLE"},
        "hac": {"lags": HAC_LAGS, "finite_sample_correction": "N_OVER_N_MINUS_K"},
    }
    write_json(OUT / "factor_residual_diagnostics.json", diagnostics)
    return {"tradable_stack_residual_alpha": fit["alpha_annualized"], "tradable_stack_alpha_hac_t": fit["alpha_t_hac"], "tradable_stack_residual_sharpe": fit["residual_sharpe"], "academic_stack_status": "UNTESTABLE_AUTHORITATIVE_FACTOR_DATA_UNAVAILABLE", "academic_stack_residual_alpha": None, "academic_stack_alpha_hac_t": None, "academic_stack_residual_sharpe": None}


def q4_brinson(sample: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    industry_rows: list[dict[str, Any]] = []
    for date, day in sample.groupby("decision_date", sort=True):
        selected = day.loc[day.is_selected]
        mapped = day.loc[day.ff48_code.notna()]
        status = "PASS_COMPLETE"
        reasons: list[str] = []
        if len(selected) != 20:
            reasons.append("TOP20_CARDINALITY")
        if len(selected) and selected.ff48_code.isna().any():
            reasons.append("SELECTED_FF48_UNMAPPED")
        if len(selected) and selected.future_return.isna().any():
            reasons.append("SELECTED_RETURN_MISSING")
        if mapped.future_return.isna().any():
            reasons.append("MAPPED_BENCHMARK_RETURN_MISSING")
        if reasons:
            status = "INCOMPLETE_NO_RENORMALIZATION"
            rows.append({"decision_date": date, "status": status, "reason": ";".join(reasons), "total_active_return": np.nan, "industry_allocation_effect": np.nan, "within_industry_selection_effect": np.nan, "interaction_effect": np.nan, "closure_error": np.nan})
            continue
        benchmark_return = float(mapped.future_return.mean())
        portfolio_return = float(selected.future_return.mean())
        total = len(mapped)
        allocation = selection = interaction = 0.0
        for (code, name), industry in mapped.groupby(["ff48_code", "ff48_name"], sort=True):
            wb = len(industry) / total
            rb = float(industry.future_return.mean())
            p = selected.loc[selected.ff48_code.eq(code)]
            wp = len(p) / 20.0
            rp = float(p.future_return.mean()) if len(p) else rb
            a = (wp - wb) * (rb - benchmark_return)
            s = wb * (rp - rb)
            i = (wp - wb) * (rp - rb)
            allocation += a
            selection += s
            interaction += i
            industry_rows.append({"decision_date": date, "ff48_code": code, "ff48_name": name, "portfolio_weight": wp, "benchmark_weight": wb, "portfolio_industry_return": rp, "benchmark_industry_return": rb, "allocation_effect": a, "selection_effect": s, "interaction_effect": i})
        active = portfolio_return - benchmark_return
        closure = active - allocation - selection - interaction
        require(abs(closure) <= 1e-12, "BRINSON_CLOSURE", (date, closure))
        rows.append({"decision_date": date, "status": status, "reason": "", "total_active_return": active, "industry_allocation_effect": allocation, "within_industry_selection_effect": selection, "interaction_effect": interaction, "closure_error": closure})
    attribution = pd.DataFrame(rows)
    industry = pd.DataFrame(industry_rows)
    atomic_csv(OUT / "industry_allocation_selection_attribution.csv", attribution)
    passed = attribution.loc[attribution.status.eq("PASS_COMPLETE")].copy()
    require(len(passed) > HAC_LAGS + 2, "BRINSON_INSUFFICIENT_COMPLETE_DATES")
    by_year = []
    for year in range(2020, 2026):
        frame = passed.loc[passed.decision_date.dt.year.eq(year)]
        if frame.empty:
            by_year.append({"year": year, "status": "NA_NO_COMPLETE_ATTRIBUTION", "date_count": 0})
        else:
            by_year.append({"year": year, "status": "EVALUABLE", "date_count": len(frame), "total_active_return": frame.total_active_return.sum(), "industry_allocation_effect": frame.industry_allocation_effect.sum(), "within_industry_selection_effect": frame.within_industry_selection_effect.sum(), "interaction_effect": frame.interaction_effect.sum(), "max_abs_closure_error": frame.closure_error.abs().max()})
    atomic_csv(OUT / "industry_attribution_by_year.csv", pd.DataFrame(by_year))
    if industry.empty:
        by_ff = pd.DataFrame(columns=["ff48_code", "ff48_name", "allocation_effect", "selection_effect", "interaction_effect", "date_count"])
    else:
        by_ff = industry.groupby(["ff48_code", "ff48_name"], as_index=False).agg(allocation_effect=("allocation_effect", "sum"), selection_effect=("selection_effect", "sum"), interaction_effect=("interaction_effect", "sum"), date_count=("decision_date", "nunique"))
    atomic_csv(OUT / "industry_attribution_by_ff48.csv", by_ff)
    selection_fit = ols_hac(passed.within_industry_selection_effect)
    result = {
        "total_active_return": float(passed.total_active_return.sum()),
        "industry_allocation_effect": float(passed.industry_allocation_effect.sum()),
        "within_industry_selection_effect": float(passed.within_industry_selection_effect.sum()),
        "within_industry_selection_mean": float(passed.within_industry_selection_effect.mean()),
        "within_industry_selection_hac_t": selection_fit["alpha_t_hac"],
        "interaction_effect": float(passed.interaction_effect.sum()),
        "attribution_closure_error": float(passed.closure_error.abs().max()),
        "complete_sessions": len(passed), "incomplete_sessions": int(len(attribution) - len(passed)),
    }
    return result, by_ff


def q5_breadth(pairs: pd.DataFrame, date_series: pd.DataFrame) -> dict[str, Any]:
    pairs = pairs.copy()
    dates = int(date_series.decision_date.nunique())
    counts = pairs.groupby("decision_date").size().rename("date_count")
    pairs = pairs.merge(counts, on="decision_date", validate="many_to_one")
    pairs["additive_contribution"] = pairs.matched_selection_return / pairs.date_count / dates
    date_contribution = pairs.groupby("decision_date").additive_contribution.sum()
    security_contribution = pairs.groupby("treatment_security_id").additive_contribution.sum()
    industry_contribution = pairs.groupby("ff48_code").additive_contribution.sum()
    year_means = date_series.assign(year=pd.to_datetime(date_series.decision_date).dt.year).groupby("year").matched_selection_return.mean()
    ff_means = pairs.groupby("ff48_code").matched_selection_return.mean()
    top5_security_ids = security_contribution.loc[security_contribution > 0].nlargest(5).index
    top10_dates = date_contribution.loc[date_contribution > 0].nlargest(10).index
    without_security = pairs.loc[~pairs.treatment_security_id.isin(top5_security_ids)].groupby("decision_date").matched_selection_return.mean().mean()
    without_dates = date_series.loc[~date_series.decision_date.isin(top10_dates), "matched_selection_return"].mean()
    leave_rows = []
    for year in range(2020, 2026):
        evaluable = year in year_means.index
        estimate = date_series.loc[pd.to_datetime(date_series.decision_date).dt.year.ne(year), "matched_selection_return"].mean() if evaluable else np.nan
        leave_rows.append({"diagnostic": "LEAVE_ONE_NATURAL_YEAR_OUT", "left_out": year, "status": "EVALUABLE" if evaluable else "NA_NO_SAMPLE_YEAR", "estimate": estimate})
    leave_rows.extend([
        {"diagnostic": "REMOVE_TOP_5_SECURITY_CONTRIBUTORS", "left_out": "|".join(map(str, top5_security_ids)), "status": "EVALUABLE", "estimate": without_security},
        {"diagnostic": "REMOVE_TOP_10_DATE_CONTRIBUTORS", "left_out": "|".join(pd.Timestamp(x).date().isoformat() for x in top10_dates), "status": "EVALUABLE", "estimate": without_dates},
    ])
    atomic_csv(OUT / "leave_out_diagnostics.csv", pd.DataFrame(leave_rows))
    metrics = {
        "positive_years": int((year_means > 0).sum()), "evaluable_years": int(len(year_means)),
        "positive_industries": int((ff_means > 0).sum()), "evaluable_industries": int(len(ff_means)),
        "top1_date_contribution": positive_share(date_contribution, 1), "top5_date_contribution": positive_share(date_contribution, 5), "top10_date_contribution": positive_share(date_contribution, 10),
        "top1_security_contribution": positive_share(security_contribution, 1), "top5_security_contribution": positive_share(security_contribution, 5), "top10_security_contribution": positive_share(security_contribution, 10),
        "top1_ff48_contribution": positive_share(industry_contribution, 1), "top5_ff48_contribution": positive_share(industry_contribution, 5),
        "leave_one_year_out_sign_consistency": float(pd.Series([r["estimate"] for r in leave_rows if r["diagnostic"] == "LEAVE_ONE_NATURAL_YEAR_OUT" and r["status"] == "EVALUABLE"]).gt(0).mean()),
        "remove_top5_security_result": float(without_security), "remove_top10_date_result": float(without_dates),
    }
    atomic_csv(OUT / "contribution_concentration.csv", pd.DataFrame([{"metric": key, "value": value, "denominator": "POSITIVE_CONTRIBUTION_MASS" if "contribution" in key else "FIXED_DIAGNOSTIC"} for key, value in metrics.items()]))
    return metrics


def selection_placebo(sample: pd.DataFrame) -> dict[str, Any]:
    eligible = sample.loc[sample.ff48_code.notna() & sample.future_return.notna()].copy()
    eligible["industry_mean"] = eligible.groupby(["decision_date", "ff48_code"]).future_return.transform("mean")
    eligible["industry_excess"] = eligible.future_return - eligible.industry_mean
    actual_rows = eligible.loc[eligible.is_selected]
    actual_by_date = actual_rows.groupby("decision_date").industry_excess.mean()
    actual = float(actual_by_date.mean())
    dates = sorted(actual_rows.decision_date.unique())
    positions = {pd.Timestamp(date): index for index, date in enumerate(dates)}
    sums = np.zeros((PLACEBO_REPLICATIONS, len(dates)), dtype=float)
    counts = np.zeros((PLACEBO_REPLICATIONS, len(dates)), dtype=float)
    rng = np.random.default_rng(PLACEBO_SEED)
    selection_counts = actual_rows.groupby(["decision_date", "ff48_code"]).size()
    for (date, code), k_value in selection_counts.items():
        candidates = eligible.loc[eligible.decision_date.eq(date) & eligible.ff48_code.eq(code), "industry_excess"].to_numpy(float)
        k = int(k_value)
        require(k <= len(candidates), "PLACEBO_SELECTION_COUNT_EXCEEDS_ELIGIBLE")
        random = rng.random((PLACEBO_REPLICATIONS, len(candidates)))
        chosen = np.argpartition(random, kth=k - 1, axis=1)[:, :k]
        sampled = np.take_along_axis(np.broadcast_to(candidates, random.shape), chosen, axis=1).sum(axis=1)
        column = positions[pd.Timestamp(date)]
        sums[:, column] += sampled
        counts[:, column] += k
    require((counts > 0).all(), "PLACEBO_EMPTY_DATE")
    distribution = (sums / counts).mean(axis=1)
    p_value = float((1 + int((distribution >= actual).sum())) / (PLACEBO_REPLICATIONS + 1))
    percentile = float((distribution < actual).mean())
    frame = pd.DataFrame({"replication": np.arange(1, PLACEBO_REPLICATIONS + 1), "statistic": distribution})
    atomic_parquet(OUT / "placebo_distribution.parquet", frame)
    summary = {"replications": PLACEBO_REPLICATIONS, "seed": PLACEBO_SEED, "actual_statistic": actual, "placebo_mean": float(distribution.mean()), "placebo_std": float(distribution.std(ddof=1)), "empirical_percentile": percentile, "empirical_one_sided_p": p_value, "date_count": len(dates)}
    write_json(OUT / "placebo_summary.json", summary)
    return summary


def rank_shuffle_placebo(ranked: pd.DataFrame, actual_groups: pd.DataFrame) -> dict[str, Any]:
    dates = sorted(actual_groups.loc[actual_groups.d10_minus_d1.notna(), "decision_date"].unique())
    positions = {pd.Timestamp(date): index for index, date in enumerate(dates)}
    sums = np.zeros((PLACEBO_REPLICATIONS, len(dates)), dtype=float)
    counts = np.zeros((PLACEBO_REPLICATIONS, len(dates)), dtype=float)
    rng = np.random.default_rng(RANK_SHUFFLE_SEED)
    for (date, code), group in ranked.groupby(["decision_date", "ff48_code"], sort=True):
        if pd.Timestamp(date) not in positions:
            continue
        n10 = int(group.decile.eq(10).sum())
        n1 = int(group.decile.eq(1).sum())
        if n10 == 0 or n1 == 0:
            continue
        values = group.future_return.to_numpy(float)
        random = rng.random((PLACEBO_REPLICATIONS, len(values)))
        order = np.argsort(random, axis=1)
        top = np.take_along_axis(np.broadcast_to(values, random.shape), order[:, :n10], axis=1).mean(axis=1)
        bottom = np.take_along_axis(np.broadcast_to(values, random.shape), order[:, n10:n10 + n1], axis=1).mean(axis=1)
        column = positions[pd.Timestamp(date)]
        sums[:, column] += top - bottom
        counts[:, column] += 1
    valid = counts > 0
    require(valid.all(), "RANK_SHUFFLE_EMPTY_DATE")
    distribution = (sums / counts).mean(axis=1)
    actual = float(actual_groups.groupby("decision_date").d10_minus_d1.mean().dropna().mean())
    p_value = float((1 + int((distribution >= actual).sum())) / (PLACEBO_REPLICATIONS + 1))
    summary = {"replications": PLACEBO_REPLICATIONS, "seed": RANK_SHUFFLE_SEED, "actual_statistic": actual, "placebo_mean": float(distribution.mean()), "placebo_std": float(distribution.std(ddof=1)), "empirical_percentile": float((distribution < actual).mean()), "empirical_one_sided_p": p_value}
    write_json(OUT / "rank_shuffle_placebo_summary.json", summary)
    return summary


def evidence_statuses(q1: dict[str, Any], q2: dict[str, Any], q3: dict[str, Any], q4: dict[str, Any], q5: dict[str, Any], q6: dict[str, Any]) -> tuple[dict[str, str], str, str]:
    if q1["within_industry_ic"] > 0 and q1["d10_minus_d1"] > 0 and max(q1["within_industry_ic_hac_t"], q1["d10_minus_d1_hac_t"]) >= 1.96:
        s1 = "SUPPORTED"
    elif q1["within_industry_ic"] > 0 and q1["d10_minus_d1"] > 0 and max(q1["within_industry_ic_hac_t"], q1["d10_minus_d1_hac_t"]) >= 1.0:
        s1 = "WEAKLY_SUPPORTED"
    elif q1["within_industry_ic"] * q1["d10_minus_d1"] < 0:
        s1 = "MIXED"
    else:
        s1 = "NOT_SUPPORTED"
    quality = q2["match_rate"] >= 0.80 and q2["post_match_max_abs_smd"] <= 0.25
    if q2["matched_selection_return"] > 0 and q2["matched_selection_hac_t"] >= 1.96 and quality:
        s2 = "SUPPORTED"
    elif q2["matched_selection_return"] > 0 and q2["matched_selection_hac_t"] >= 1.0 and quality:
        s2 = "WEAKLY_SUPPORTED"
    elif q2["matched_selection_return"] > 0 and not quality:
        s2 = "MIXED"
    else:
        s2 = "NOT_SUPPORTED"
    if q3["tradable_stack_residual_alpha"] > 0 and q3["tradable_stack_alpha_hac_t"] >= 1.96:
        s3 = "SUPPORTED"
    elif q3["tradable_stack_residual_alpha"] > 0 and q3["tradable_stack_alpha_hac_t"] >= 1.0:
        s3 = "WEAKLY_SUPPORTED"
    else:
        s3 = "NOT_SUPPORTED"
    if q4["within_industry_selection_mean"] > 0 and q4["within_industry_selection_hac_t"] >= 1.96 and q4["attribution_closure_error"] <= 1e-12:
        s4 = "SUPPORTED"
    elif q4["within_industry_selection_mean"] > 0 and q4["attribution_closure_error"] <= 1e-12:
        s4 = "WEAKLY_SUPPORTED"
    else:
        s4 = "NOT_SUPPORTED"
    broad = (
        q5["evaluable_years"] > 0 and q5["positive_years"] / q5["evaluable_years"] >= 2 / 3
        and q5["top10_date_contribution"] < 0.5 and q5["top5_security_contribution"] < 0.5
        and q5["top1_ff48_contribution"] < 0.5 and q5["leave_one_year_out_sign_consistency"] >= 2 / 3
        and q5["remove_top5_security_result"] > 0 and q5["remove_top10_date_result"] > 0
    )
    s5 = "SUPPORTED" if broad else ("MIXED" if q2["matched_selection_return"] > 0 else "NOT_SUPPORTED")
    if q6["empirical_one_sided_p"] <= 0.05:
        s6 = "SUPPORTED"
    elif q6["empirical_one_sided_p"] <= 0.10:
        s6 = "WEAKLY_SUPPORTED"
    else:
        s6 = "NOT_SUPPORTED"
    statuses = {"Q1_WITHIN_INDUSTRY_RANK": s1, "Q2_MATCHED_CONTROL": s2, "Q3_FACTOR_RESIDUAL": s3, "Q4_SELECTION_ATTRIBUTION": s4, "Q5_BREADTH_CONCENTRATION": s5, "Q6_PLACEBO": s6}
    if q2["match_rate"] < 0.50 or q4["complete_sessions"] < 100:
        verdict, action = "PASS_COUNTERFACTUAL_IDENTIFICATION_INCONCLUSIVE_WITH_LIMITATIONS", "retain"
    elif all(value == "SUPPORTED" for value in statuses.values()):
        verdict, action = "PASS_GENUINE_STOCK_SELECTION_ALPHA_SUPPORTED", "strengthen_with_academic_factor_limitation"
    elif s5 != "SUPPORTED" and sum(statuses[key] in {"SUPPORTED", "WEAKLY_SUPPORTED"} for key in ["Q1_WITHIN_INDUSTRY_RANK", "Q2_MATCHED_CONTROL", "Q4_SELECTION_ATTRIBUTION", "Q6_PLACEBO"]) >= 2:
        verdict, action = "PASS_MIXED_OR_CONCENTRATED_STOCK_SELECTION_EVIDENCE", "retain_and_qualify_as_concentrated"
    elif s1 in {"SUPPORTED", "WEAKLY_SUPPORTED"} and s2 in {"SUPPORTED", "WEAKLY_SUPPORTED"} and s6 in {"SUPPORTED", "WEAKLY_SUPPORTED"} and s5 == "SUPPORTED":
        verdict, action = "PASS_SELECTION_INFORMATION_SUPPORTED_ECONOMICALLY_WEAK", "retain"
    elif s1 == "NOT_SUPPORTED" and s2 == "NOT_SUPPORTED" and s6 == "NOT_SUPPORTED":
        verdict, action = "PASS_NO_ROBUST_STOCK_SELECTION_ALPHA_AFTER_COUNTERFACTUAL", "weaken_selection_alpha_clause"
    else:
        verdict, action = "PASS_MIXED_OR_CONCENTRATED_STOCK_SELECTION_EVIDENCE", "retain_and_qualify_as_mixed"
    return statuses, verdict, action


def write_evidence_and_report(q1: dict[str, Any], q2: dict[str, Any], q3: dict[str, Any], q4: dict[str, Any], q5: dict[str, Any], q6: dict[str, Any], rank_placebo: dict[str, Any], statuses: dict[str, str], verdict: str, identity_action: str) -> None:
    matrix = pd.DataFrame([
        {"question": "Q1_WITHIN_INDUSTRY_RANK", "status": statuses["Q1_WITHIN_INDUSTRY_RANK"], "effect_size": q1["d10_minus_d1"], "inference": f"IC_HAC_T={q1['within_industry_ic_hac_t']:.6f};SPREAD_HAC_T={q1['d10_minus_d1_hac_t']:.6f}", "coverage": "STRICT_PIT_FF48_MAPPED", "limitation": "RANK_NOT_RAW_SCORE_FULL_SURFACE", "evidence_path": str(OUT / "within_industry_rank_results.csv")},
        {"question": "Q2_MATCHED_CONTROL", "status": statuses["Q2_MATCHED_CONTROL"], "effect_size": q2["matched_selection_return"], "inference": f"HAC_T={q2['matched_selection_hac_t']:.6f}", "coverage": f"MATCH_RATE={q2['match_rate']:.6f}", "limitation": "PIT_MARKET_CAP_AND_MOMENTUM_UNAVAILABLE", "evidence_path": str(OUT / "matched_control_results.csv")},
        {"question": "Q3_FACTOR_RESIDUAL", "status": statuses["Q3_FACTOR_RESIDUAL"], "effect_size": q3["tradable_stack_residual_alpha"], "inference": f"HAC_T={q3['tradable_stack_alpha_hac_t']:.6f}", "coverage": "TRADABLE_STACK", "limitation": "ACADEMIC_STACK_UNTESTABLE_AUTHORITATIVE_FACTOR_DATA_UNAVAILABLE", "evidence_path": str(OUT / "factor_residual_results.csv")},
        {"question": "Q4_SELECTION_ATTRIBUTION", "status": statuses["Q4_SELECTION_ATTRIBUTION"], "effect_size": q4["within_industry_selection_effect"], "inference": f"HAC_T={q4['within_industry_selection_hac_t']:.6f}", "coverage": f"COMPLETE_SESSIONS={q4['complete_sessions']}", "limitation": f"INCOMPLETE_SESSIONS={q4['incomplete_sessions']}", "evidence_path": str(OUT / "industry_allocation_selection_attribution.csv")},
        {"question": "Q5_BREADTH_CONCENTRATION", "status": statuses["Q5_BREADTH_CONCENTRATION"], "effect_size": q2["matched_selection_return"], "inference": f"POSITIVE_YEARS={q5['positive_years']}/{q5['evaluable_years']}", "coverage": f"INDUSTRIES={q5['evaluable_industries']}", "limitation": "FIXED_LEAVE_OUTS_SUPPLEMENTARY", "evidence_path": str(OUT / "contribution_concentration.csv")},
        {"question": "Q6_PLACEBO", "status": statuses["Q6_PLACEBO"], "effect_size": q6["actual_statistic"], "inference": f"EMPIRICAL_P={q6['empirical_one_sided_p']:.6f}", "coverage": f"DATES={q6['date_count']}", "limitation": "RANK_SHUFFLE_SUPPLEMENTARY", "evidence_path": str(OUT / "placebo_summary.json")},
    ])
    atomic_csv(OUT / "stock_selection_evidence_matrix.csv", matrix)
    verdict_payload = {
        "task_id": TASK, "verdict": verdict, "raw_a2_stock_selection_identity_status": verdict.removeprefix("PASS_"),
        "prior_identity": "MIXED_SYSTEMATIC_EXPOSURE_AND_PARTIAL_STOCK_SELECTION_ALPHA", "prior_identity_action": identity_action,
        "scope": "STRICT_PIT_FF48_MAPPED_COUNTERFACTUAL_SURFACE", "structural_missingness": {"observations": 15731, "securities": 44, "coverage": 0.9498482471912978, "non_random": True},
        "module_statuses": statuses, "academic_factor_limitation": "UNTESTABLE_AUTHORITATIVE_FACTOR_DATA_UNAVAILABLE",
        "strategy_promotion": False, "raw_a2_modified": False, "rv_economics_run": False,
    }
    write_json(OUT / "raw_a2_identity_verdict.json", verdict_payload)
    if verdict == "PASS_GENUINE_STOCK_SELECTION_ALPHA_SUPPORTED":
        resource = "portfolio/risk layer"
    else:
        resource = "new orthogonal information sleeve"
    report = f"""# Raw A2 strict counterfactual stock-selection identification\n\n## Verdict\n\n`{verdict}` on the `STRICT_PIT_FF48_MAPPED_COUNTERFACTUAL_SURFACE`. This is an identity diagnostic, not strategy promotion.\n\n## Direct answers\n\n1. **Within-industry ranking:** D10-minus-D1 is {q1['d10_minus_d1']:.6%} (HAC t {q1['d10_minus_d1_hac_t']:.3f}); mean within-industry rank IC is {q1['within_industry_ic']:.6f} (HAC t {q1['within_industry_ic_hac_t']:.3f}). Status: `{statuses['Q1_WITHIN_INDUSTRY_RANK']}`.\n2. **Selected versus matched peers:** the date-equal selected-minus-peer return is {q2['matched_selection_return']:.6%} per one-session horizon (HAC t {q2['matched_selection_hac_t']:.3f}), with match rate {q2['match_rate']:.2%} and maximum post-match absolute SMD {q2['post_match_max_abs_smd']:.3f}. Status: `{statuses['Q2_MATCHED_CONTROL']}`.\n3. **After systematic controls:** annualized Stack-A residual intercept is {q3['tradable_stack_residual_alpha']:.4%} (HAC t {q3['tradable_stack_alpha_hac_t']:.3f}; residual Sharpe {q3['tradable_stack_residual_sharpe']:.3f}). Academic Stack B is untestable because no certified physically isolated pre-2026 official factor-return file exists; no substitute was invented.\n4. **Industry allocation versus stock selection:** across {q4['complete_sessions']} complete dates, active arithmetic sum is {q4['total_active_return']:.6f}: allocation {q4['industry_allocation_effect']:.6f}, within-industry selection {q4['within_industry_selection_effect']:.6f}, interaction {q4['interaction_effect']:.6f}. Maximum closure error is {q4['attribution_closure_error']:.3e}. No unmapped holding was renormalized.\n5. **Breadth/concentration:** positive years {q5['positive_years']}/{q5['evaluable_years']}; positive FF48 groups {q5['positive_industries']}/{q5['evaluable_industries']}; top-10 date positive-mass share {q5['top10_date_contribution']:.2%}; top-5 security share {q5['top5_security_contribution']:.2%}; top-1 FF48 share {q5['top1_ff48_contribution']:.2%}. Status: `{statuses['Q5_BREADTH_CONCENTRATION']}`.\n6. **Industry-consistent placebo:** actual statistic {q6['actual_statistic']:.6%}, empirical percentile {q6['empirical_percentile']:.2%}, one-sided p={q6['empirical_one_sided_p']:.6f} from exactly 1,000 replications. Rank-shuffle p={rank_placebo['empirical_one_sided_p']:.6f}. Status: `{statuses['Q6_PLACEBO']}`.\n7. **Most accurate identity:** `{verdict.removeprefix('PASS_')}` within the mapped surface, with the academic-factor and non-random taxonomy limitations stated above.\n8. **Prior identity description:** `{identity_action}`. No result was used to modify the frozen design.\n9. **Remaining 5.015% taxonomy gap:** 15,731 observations across 44 securities are structurally non-random and remain visible. Conclusions do not extend to all possible Raw A2 securities.\n10. **Next research allocation:** `{resource}`. Further tuning of the defendant is not authorized by this diagnostic.\n\n## Fixed-design safeguards\n\nPrimary horizon is one next-open-to-following-open legal session. Matching used only five READY covariates and never rematched after outcome access. HAC is Bartlett/Newey-West lag 5 with n/(n-k) correction. Placebo counts and seeds were fixed in the hashed contract. No 2026 outcome, mixed source, Moomoo history, RV economics, model fit, feature, threshold, or optimizer was used.\n"""
    write_text(OUT / "final_report.md", report)


def analyze() -> None:
    frozen = verify_frozen_contract()
    require(ASSIGNMENTS.exists() and PREPARED_SAMPLE.exists(), "OUTCOME_BLIND_ASSIGNMENTS_MISSING")
    sample = pd.read_parquet(PREPARED_SAMPLE)
    for column in ("decision_date", "entry_date", "exit_date"):
        sample[column] = pd.to_datetime(sample[column]).dt.normalize()
    require(sample.decision_date.nunique() == 750 and int(sample.is_selected.sum()) == 15000, "PREPARED_SAMPLE_IDENTITY_CONFLICT")
    prices = load_outcome_prices()
    lookup = open_lookup(prices)
    sample["future_return"] = attach_forward_return(sample, lookup)
    q1, ranked, rank_groups = q1_within_industry(sample)
    q2, pairs, date_series = q2_matched(sample, lookup)
    atomic_parquet(OUT / "matched_selection_return_series.parquet", date_series)
    q3 = q3_factor_residual(date_series, prices, sample, lookup)
    q4, _ = q4_brinson(sample)
    q5 = q5_breadth(pairs, date_series)
    q6 = selection_placebo(sample)
    rank_placebo = rank_shuffle_placebo(ranked, rank_groups)
    statuses, verdict, action = evidence_statuses(q1, q2, q3, q4, q5, q6)
    write_evidence_and_report(q1, q2, q3, q4, q5, q6, rank_placebo, statuses, verdict, action)
    statistical = {
        "primary_hypothesis_count": 1, "primary_forward_horizon": 1, "hac_lags": HAC_LAGS, "hac_finite_sample_correction": "N_OVER_N_MINUS_K",
        "matched_mean_daily_return": q2["matched_selection_return"], "matched_hac_t": q2["matched_selection_hac_t"],
        "matched_hac_standard_error": q2["matched_selection_hac_se"], "matched_confidence_interval": [q2["matched_selection_ci_low"], q2["matched_selection_ci_high"]],
        "matched_skew": q2["matched_selection_skew"], "matched_excess_kurtosis": q2["matched_selection_excess_kurtosis"], "matched_effective_observations": q2["matched_effective_observations"],
        "within_industry_ic": q1["within_industry_ic"], "within_industry_ic_hac_t": q1["within_industry_ic_hac_t"],
        "d10_minus_d1": q1["d10_minus_d1"], "d10_minus_d1_hac_t": q1["d10_minus_d1_hac_t"],
    }
    write_json(OUT / "statistical_validation.json", statistical)
    summary = {
        "task": TASK, "status": verdict, "registry_base_head": REGISTRY_BASE_HEAD, "raw_a2_entity_id": RAW_A2_ENTITY_ID, "raw_a2_fingerprint": RAW_A2_FINGERPRINT,
        "contract_sha256": sha256_file(CONTRACT_PATH), "total_eligible_observations": 313668, "strict_ff48_mapped_observations": 297937, "strict_ff48_coverage": 297937 / 313668, "structural_unmapped_observations": 15731, "structural_unmapped_securities": 44, "primary_forward_horizon": 1,
        "q1": q1, "q2": q2, "q3": q3, "q4": q4, "q5": q5, "q6": q6, "rank_shuffle": rank_placebo, "statuses": statuses,
        "safety": frozen["anti_bloat"] | frozen["temporal_counters"] | {"rv_economics_run": False},
    }
    write_json(OUT / "analysis_summary.json", summary)
    validation = {
        "status": "PASS_SUBSTANTIVE_ANALYSIS_PENDING_INDEPENDENT_REVIEW_AND_REGISTRY", "task_id": TASK,
        "checks": {"contract_hash": True, "runner_hash": True, "strict_taxonomy_fingerprint": sha256_file(TAXONOMY) == TAXONOMY_SHA, "factor_risk_fingerprint": sha256_file(FACTOR) == FACTOR_SHA, "denominator_preserved": True, "no_new_data_source": True, "no_2026": True, "no_horizon_search": True, "no_matching_search": True, "no_factor_search": True, "no_bucket_search": True, "placebo_deterministic_contract": True, "attribution_closes": q4["attribution_closure_error"] <= 1e-12, "missing_rows_preserved": True, "no_rv": True, "no_moomoo": True},
        "zero_read_counters": frozen["temporal_counters"], "anti_bloat": frozen["anti_bloat"],
    }
    write_json(OUT / "final_validation.json", validation)
    print(f"ANALYZE_STATUS={verdict}\nMATCHED_SELECTION_RETURN={q2['matched_selection_return']}\nMATCHED_HAC_T={q2['matched_selection_hac_t']}\nPLACEBO_P={q6['empirical_one_sided_p']}")


def main() -> None:
    canonical = Path(r"D:\us-tech-quant-envs\us-tech-quant-main\Scripts\python.exe").resolve()
    require(Path(sys.executable).resolve() == canonical, "NON_CANONICAL_RUNTIME", sys.executable)
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["prepare", "analyze"])
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare()
    else:
        analyze()


if __name__ == "__main__":
    main()
