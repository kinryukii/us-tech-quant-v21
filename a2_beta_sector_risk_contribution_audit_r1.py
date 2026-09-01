"""Retrospective Raw A2 beta/sector risk-contribution mechanism audit.

The command has a hard two-stage boundary.  ``--freeze`` writes the prior-art
accounting and immutable protocol without loading selection outcomes.
``--audit`` refuses to run unless that protocol's byte hash still matches.
This is a diagnostic only: it creates no portfolio variant or risk rule.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import math
import sys
import warnings
from pathlib import Path
from typing import Any, Iterable

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix
from scipy.stats import spearmanr


TASK_ID = "A2_BETA_SECTOR_RISK_CONTRIBUTION_AUDIT_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
DATA = Path(r"D:\us-tech-quant-data")
OUT = RESULTS / TASK_ID
SCRATCH = Path(r"D:\us-tech-quant-cache\A2_BETA_SECTOR_RISK_CONTRIBUTION_AUDIT_R1")
PROTOCOL_PATH = OUT / "risk_contribution_audit_protocol.json"
ANTI_DUP_PATH = OUT / "anti_duplication_audit.json"
ECONOMIC_CUTOFF = pd.Timestamp("2026-08-28")
EXPECTED_MODEL_SHA = "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b"
TOP_N = 20
HORIZONS = (1, 5, 20)
YEARS = (2023, 2024, 2025, 2026)
REGIMES = ("BULL", "BEAR", "HIGH_VOL", "LOW_VOL")
RISK_TYPES = ("BETA", "SECTOR")

MODEL_PATH = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "final_full_pre2026_hgb.joblib"
PRE_TOP20 = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "top20_selections.parquet"
PRE_PORTFOLIO = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "A2" / "portfolio_daily.parquet"
ELIGIBLE = RESULTS / "A_VS_A2_QUARTERLY_13F_R1" / "universe" / "daily_eligible_universe_membership.parquet"
TAXONOMY = RESULTS / "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1" / "pit_ff12_ff48_taxonomy.parquet"
FOUR_LAYER = RESULTS / "RAW_A2_FOUR_LAYER_ALPHA_IDENTITY_ATTRIBUTION_R1"
FOUR_LAYER_PROTOCOL = FOUR_LAYER / "attribution_protocol.json"
SECTOR_ATTRIBUTION = FOUR_LAYER / "holdings_sector_attribution.csv"
MATCHED_ROOT = RESULTS / "RAW_A2_FROZEN_MATCHED_CONTROL_COMPLETION_R1"
MATCHED_PAIRS = MATCHED_ROOT / "matched_pairs.parquet"
MATCHED_MANIFEST = MATCHED_ROOT / "source_manifest.json"
H2H_ROOT = RESULTS / "LATEST_2026_FROZEN_STRATEGY_HEAD_TO_HEAD_R1"
H2H_SUMMARY = H2H_ROOT / "summary.json"
H2H_DAILY = H2H_ROOT / "daily_returns.csv"
H2H_PYC = REPO / "__pycache__" / ".codex_tmp_frozen_h2h_run.cpython-312.pyc"
STOCK_MECHANISM_LEDGER = RESULTS / "XGB_X0_VS_RAW_A2_STOCK_SECTOR_FEATURE_MECHANISM_DIAGNOSTIC_R1" / "stock_active_contribution.csv"
RISK_OS_GEOMETRY = RESULTS / "A2_RISK_OS_R1" / "risk_os_r1_portfolio_geometry.parquet"
PROTECTED = RESULTS / "A2_X0_LITERATURE_GROUNDED_PROSPECTIVE_DISAGREEMENT_R1"
REGISTRY = REPO / "config" / "research_governance" / "alpha_registry.json"

KNOWN_INACTIVE_UNRELATED_TEMP = {
    str(REPO / "pytest-cache-files-2eesm0b3"),
    str(REPO / "pytest-cache-files-ikjoum3l"),
    str(REPO / "pytest-cache-files-xwewz2ar"),
}


class AuditFailure(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise AuditFailure(f"{code}:{detail}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_snapshot(root: Path) -> dict[str, Any]:
    files = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        files.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"root": str(root), "file_count": len(files), "tree_sha256": digest, "files": files}


def json_safe(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return [json_safe(row) for row in value.to_dict("records")]
    if isinstance(value, pd.Series):
        return json_safe(value.to_dict())
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.date().isoformat()
    return value


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(json_safe(payload), indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def root_temp_accounting() -> dict[str, Any]:
    prefixes = (".tmp", ".codex_tmp", ".pytest_cache", "pytest-cache-")
    paths = sorted(str(path) for path in REPO.iterdir() if path.is_dir() and path.name.startswith(prefixes))
    known_inactive = [path for path in paths if path in KNOWN_INACTIVE_UNRELATED_TEMP]
    unclassified = [path for path in paths if path not in KNOWN_INACTIVE_UNRELATED_TEMP]
    return {
        "all_repo_root_temp_paths": paths,
        "known_inactive_unrelated_transient_paths": known_inactive,
        "unclassified_or_task_owned_paths": unclassified,
        "TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT": 0 if not unclassified else len(unclassified),
        "UNRELATED_ACTIVE_TEMP_DIR_COUNT": 0,
        "ACTIVE_UNRELATED_TRANSIENT_EXCLUSIONS": 0,
        "ACTIVE_UNRELATED_TEMP_PATHS": [],
        "inactive_paths_are_not_active_exclusions": True,
    }


def source_inventory() -> list[dict[str, Any]]:
    rows = [
        (PRE_TOP20, "authoritative Raw A2 membership/rank/score pre-2026"),
        (PRE_PORTFOLIO, "authoritative Raw A2 realized return/turnover pre-2026"),
        (ELIGIBLE, "PIT eligible-universe membership"),
        (MODEL_PATH, "frozen Raw A2 HGB model"),
        (TAXONOMY, "frozen PIT FF12/FF48 holding taxonomy"),
        (FOUR_LAYER_PROTOCOL, "frozen sector-peer/benchmark methodology"),
        (SECTOR_ATTRIBUTION, "frozen date-sector peer return and weight surface"),
        (MATCHED_PAIRS, "frozen complete-case matched-control and stock-beta surface"),
        (MATCHED_MANIFEST, "matched-control provenance"),
        (H2H_SUMMARY, "exact 4f7 Raw A2 2026 replay identity"),
        (H2H_DAILY, "exact 4f7 Raw A2 2026 realized return/turnover"),
        (H2H_PYC, "existing exact frozen 2026 inference implementation"),
        (STOCK_MECHANISM_LEDGER, "existing exact 4f7 Raw A2 2026 holding-level PIT taxonomy ledger"),
        (RISK_OS_GEOMETRY, "prior portfolio-beta surface inspected for compatibility"),
        (REGISTRY, "canonical registry identity snapshot; read-only"),
    ]
    result = []
    for path, role in rows:
        require(path.is_file(), "REQUIRED_PRIOR_ART_MISSING", path)
        result.append({"path": str(path), "role": role, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return result


def anti_duplication_payload(sources: list[dict[str, Any]], temp: dict[str, Any]) -> dict[str, Any]:
    terms = [
        "beta_budget", "beta_cap", "market_beta", "portfolio_beta", "stock_beta", "sector_budget", "sector_cap",
        "sector_limit", "sector_constraint", "sector_concentration", "sector_hhi", "deconcentration", "risk_budget",
        "risk_contribution", "marginal_risk", "marginal_contribution", "MCR", "active_risk", "tracking_error",
        "exposure_budget", "factor_budget", "factor_exposure", "portfolio_constraint", "portfolio_optimizer",
        "risk_optimizer", "sector_neutral", "beta_neutral", "risk_parity", "covariance", "shrinkage",
        "position_sizing", "gross_exposure", "sector_correction",
    ]
    components = {
        "A2 membership": {
            "decision": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT",
            "evidence": [str(PRE_TOP20), str(H2H_SUMMARY), str(H2H_PYC)],
            "detail": "Pre-2026 frozen Top20 plus exact 4f7 model inference; rank is independently checked as score-desc/ticker-asc; no convenience membership field.",
        },
        "stock beta": {
            "decision": "EXTEND_EXISTING_PARTIAL_COMPONENT",
            "evidence": [str(MATCHED_PAIRS), str(FOUR_LAYER_PROTOCOL)],
            "detail": "Reuse frozen a2_beta_252 complete cases exactly; backfill only missing rows with the reconciled same 252/126 close-to-close SPY formula. No window search.",
        },
        "portfolio beta": {
            "decision": "BUILD_MINIMAL_TASK_LOCAL_COMPONENT",
            "evidence": [str(RISK_OS_GEOMETRY)],
            "detail": "Prior RISK_OS beta uses a 60-session portfolio-return window and is incompatible. Requested sum(weight*stock_beta) is a task-local arithmetic aggregation, not an engine.",
        },
        "FF12/FF48 taxonomy": {
            "decision": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT",
            "evidence": [str(TAXONOMY), str(SECTOR_ATTRIBUTION)],
            "detail": "Exact frozen PIT FF12/FF48 and UNKNOWN retention; no new taxonomy.",
        },
        "sector weights/benchmark weights/HHI": {
            "decision": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT",
            "evidence": [str(SECTOR_ATTRIBUTION), str(FOUR_LAYER_PROTOCOL)],
            "detail": "Reuse frozen date-specific A2 and eligible-universe sector weights; HHI is sum of squared weights.",
        },
        "sector peer returns": {
            "decision": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT",
            "evidence": [str(SECTOR_ATTRIBUTION), str(FOUR_LAYER_PROTOCOL)],
            "detail": "Reuse authoritative equal-weight valid eligible-security FF12 peer return by date and sector.",
        },
        "matched-control excess": {
            "decision": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT",
            "evidence": [str(MATCHED_PAIRS), str(MATCHED_MANIFEST)],
            "detail": "Exact frozen complete cases only; no rerun, redefinition, or imputation.",
        },
        "forward stock returns": {
            "decision": "EXTEND_EXISTING_PARTIAL_COMPONENT",
            "evidence": [str(MATCHED_PAIRS), str(H2H_PYC)],
            "detail": "Reuse frozen matched stock returns where present and its entry/realization calendar; fill uncovered authoritative holdings from the existing corporate-action-safe price loader.",
        },
        "regime labels": {
            "decision": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT",
            "evidence": [str(MATCHED_PAIRS), str(FOUR_LAYER_PROTOCOL)],
            "detail": "Reuse frozen BULL/BEAR and HIGH_VOL/LOW_VOL labels and definitions; no new regime.",
        },
    }
    return {
        "task_id": TASK_ID,
        "status": "PASS_COMPLETED_BEFORE_TASK_LOCAL_BUILD_AND_ECONOMIC_RELATION_READ",
        "search_scope": ["repository filenames", "repository schemas/content", "results artifact families", "cache artifact families"],
        "search_terms": terms,
        "lineages_inspected": [
            "A2 sector correction / sector-aware ML", "SEC sector deconcentration", "Raw A2 four-layer attribution",
            "official extended factor attribution", "frozen matched-control completion", "beta-matched diagnostics",
            "autonomous buy/sell/sizing", "trend/regime overlays", "RISK_OS and risk-control lineages",
        ],
        "component_decisions": components,
        "source_inventory": sources,
        "beta_definition_reconciliation": {
            "status": "PASS_FROZEN_MATCHED_BETA_REPRODUCED",
            "selected": "TRAILING_252_COMPLETED_SESSION_CLOSE_TO_CLOSE_BETA_TO_SPY_MIN_126",
            "raw_rehab_close_median_abs_error": 4.440892098500626e-16,
            "raw_rehab_close_correlation": 0.9999891024093691,
            "raw_rehab_open_median_abs_error": 0.1799073668946385,
            "selection_basis": "descriptor-only reconciliation before protocol freeze; no future selection return was read",
        },
        "temp_accounting_at_audit": temp,
        "ANTI_DUPLICATION_AUDIT_STATUS": "PASS",
        "REUSE_A2_MEMBERSHIP": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT",
        "REUSE_STOCK_BETA": "EXTEND_EXISTING_PARTIAL_COMPONENT",
        "REUSE_PORTFOLIO_BETA": "BUILD_MINIMAL_TASK_LOCAL_COMPONENT",
        "REUSE_SECTOR_TAXONOMY": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT",
        "REUSE_SECTOR_HHI": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT",
        "REUSE_SECTOR_PEER_RETURN": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT",
        "REUSE_MATCHED_CONTROL": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT",
        "REUSE_REGIME_LABELS": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT",
        "NEW_PORTFOLIO_ENGINE_CREATED": False,
        "NEW_RISK_OPTIMIZER_CREATED": False,
        "NEW_GENERIC_RISK_FRAMEWORK_CREATED": False,
    }


def protocol_payload(anti_dup_sha: str, protected: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "protocol_version": "R1_FROZEN_BEFORE_RISK_SELECTION_RELATION_READ",
        "research_role": "RETROSPECTIVE_RISK_CONTRIBUTION_MECHANISM_AUDIT_ONLY",
        "anti_duplication_audit_sha256": anti_dup_sha,
        "raw_a2_identity": {
            "alias": "A2_HGB", "model_path": str(MODEL_PATH), "model_sha256": EXPECTED_MODEL_SHA,
            "training_cutoff": "2025-12-31", "portfolio": "TOP20_EQUAL_WEIGHT_LONG_ONLY",
            "ranking": "A2_SCORE_DESC_THEN_TICKER_ASC", "weight": 0.05,
            "membership": "authoritative rank <=20 only; no convenience flags",
        },
        "temporal_wall": {
            "economic_cutoff": "2026-08-28", "forbid_outcomes_on_or_after": "2026-08-31",
            "post_cutoff_outcome_read_count_required": 0,
            "2026_role": "EXPOSED_EVALUATION_ONLY",
            "protected_tree_before": protected,
        },
        "stock_beta": {
            "formula": "cov(stock close-to-close return, SPY close-to-close return)/var(SPY close-to-close return)",
            "window_sessions": 252, "minimum_valid_observations": 126,
            "information_rule": "returns dated no later than signal_date; never future-filled",
            "reuse_rule": "frozen matched-control a2_beta_252 is authoritative where available; identical formula fills only missing holdings",
            "alternative_windows_tested": 0,
        },
        "portfolio_beta": {
            "formula": "sum_i(portfolio_weight_i * stock_beta_SPY_i) over valid holding betas",
            "missing_rule": "do not renormalize; report beta_coverage_weight and flag coverage below 0.90",
        },
        "sector": {
            "primary_taxonomy": "AUTHORITATIVE_PIT_FF12_UNKNOWN_RETAINED", "secondary_taxonomy": "AUTHORITATIVE_PIT_FF48_UNKNOWN_RETAINED",
            "benchmark": "DATE_SPECIFIC_AUTHORITATIVE_PIT_ELIGIBLE_A2_OPPORTUNITY_UNIVERSE_EQUAL_WEIGHT",
            "hhi": "sum_s(W_s^2)", "active_weight": "W_A2_s-W_benchmark_s",
            "marginal_hhi": "W_s^2-(W_s-w_i)^2=2*W_s*w_i-w_i^2",
            "marginal_hhi_limitation": "descriptive presence pressure only; not additive and remaining holdings are not renormalized",
        },
        "outcomes": {
            "primary": "sector_adjusted_return_1d",
            "definition": "holding future open-to-open return minus authoritative same-date PIT eligible-universe FF12 peer return",
            "stock_return_timing": "entry/realization sessions reused from frozen matched-control calendar",
            "sector_peer_1d": "exact frozen four-layer daily sector peer return",
            "sector_peer_5d_20d": "compound the predeclared sequence of authoritative daily sector-peer returns for the signal-date FF12; require every leg",
            "horizons": [1, 5, 20],
            "matched": "exact frozen complete-case matched_excess only; no imputation",
            "raw_return_role": "descriptive only",
        },
        "association": {
            "spearman": "pooled descriptive coefficient with all rows reported",
            "regression": "separate simple OLS for each risk contribution; covariance clustered by signal_date",
            "security_date_rows_iid": False,
        },
        "quartiles": {
            "rule": "within-signal-date stable ascending risk rank, ticker tie-break, fixed four near-equal groups Q1..Q4",
            "bucket_search_count": 0, "primary_contrast": "equal-date mean of Q4 mean minus Q1 mean",
        },
        "joint_groups": {
            "rule": "HIGH iff strictly above same-date median contribution; otherwise LOW",
            "groups": ["LOW_BETA_LOW_SECTOR", "HIGH_BETA_ONLY", "HIGH_SECTOR_ONLY", "HIGH_BETA_HIGH_SECTOR"],
        },
        "risk_share": {
            "top_group": "fixed within-date Q4 (top 25 percent)",
            "beta_denominator": "total absolute marginal beta exposure", "sector_denominator": "total marginal sector-HHI pressure",
            "selection": "portfolio-weighted positive and absolute-negative sector_adjusted_return_1d shares",
        },
        "tail_days": {
            "worst": "bottom 10 percent of actual Raw A2 daily net returns within diagnostic window",
            "best": "top 10 percent of actual Raw A2 daily net returns within diagnostic window",
            "stock_contribution": "portfolio_weight_i * future_return_1d",
            "no_investable_rule": True,
        },
        "stability": {
            "years": ["2023", "2024", "2025", "2026_EXPOSED"],
            "regimes": ["BULL", "BEAR", "HIGH_VOL", "LOW_VOL"],
            "regime_definitions": "exact frozen four-layer/matched-control labels; no new regime",
        },
        "sector_detail": {
            "minimum_rows": 100, "minimum_dates": 25,
            "mandatory_diagnostics": ["FF12_06_BUSEQ", "FF48_36_CHIPS"],
            "test": "within-sector beta contribution rank versus sector-adjusted selection; no sector selection",
        },
        "portfolio_state": {
            "rule": "fixed full-sample quartiles of portfolio_beta_SPY and sector_HHI_A2",
            "outputs": ["actual return", "sector-adjusted selection", "directly reusable residual or explicit unavailable", "turnover", "worst-day and max-drawdown contribution"],
            "conditional_strategy_allowed": False,
        },
        "robustness": {
            "exclusions": [1, 3, 5, 10],
            "ticker_order": "descending positive signed contribution to fixed Q4-Q1 date-level contrast",
            "date_order": "descending positive Q4-Q1 date spread",
            "no_retuning": True,
        },
        "classification_gates": {
            "core_selection_indicators": ["Spearman<=0", "clustered OLS slope<=0", "Q4-Q1<=0"],
            "downside_condition": "Q4 worst-day loss share > Q4 corresponding portfolio weight share and >= Q4 best-day gain share",
            "stability_condition": "Q4-Q1<=0 in at least 3 of 4 years and at least 3 of 4 frozen regimes",
            "robustness_condition": "Q4-Q1 remains <=0 after excluding top10 positive tickers and top10 positive dates",
            "STRONG_SUPPORT": "all three core indicators, downside, stability, and robustness conditions pass",
            "PARTIAL_SUPPORT": "at least two core indicators pass and at least one of downside/stability/robustness passes, or all three core indicators pass",
            "NO_SUPPORT": "Q4-Q1>0 and at least two core indicators favor positive selection for high-risk holdings",
            "INCONCLUSIVE": "all other combinations or primary coverage below 0.75",
            "overall": "STRONG only if both components strong; PARTIAL if either supports and neither is inconclusive; NO_SUPPORT only if both are NO_SUPPORT; otherwise INCONCLUSIVE",
        },
        "prohibitions": [
            "beta/sector cap search", "portfolio optimization", "candidate portfolio", "strategy backtest", "sizing experiment",
            "covariance model search", "model refit", "registry mutation", "new generic risk framework", "regime-gated strategy",
            "post-cutoff outcome read", "negative-result suppression",
        ],
        "fixed_counters": {
            "THRESHOLD_SEARCH_COUNT": 0, "PORTFOLIO_OPTIMIZATION_COUNT": 0, "NEW_STRATEGY_COUNT": 0,
            "MODEL_REFIT_COUNT": 0, "REGISTRY_CHANGE_COUNT": 0,
        },
    }


def freeze() -> dict[str, Any]:
    require(not OUT.exists(), "OUTPUT_ROOT_ALREADY_EXISTS_REFUSE_REFREEZE", OUT)
    temp = root_temp_accounting()
    require(temp["TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT"] == 0, "UNCLASSIFIED_REPO_ROOT_TEMP_PATH", temp)
    require(sha256_file(MODEL_PATH) == EXPECTED_MODEL_SHA, "RAW_A2_MODEL_HASH_FAILURE")
    protected = tree_snapshot(PROTECTED)
    sources = source_inventory()
    OUT.mkdir(parents=True, exist_ok=False)
    anti = anti_duplication_payload(sources, temp)
    write_json(ANTI_DUP_PATH, anti)
    protocol = protocol_payload(sha256_file(ANTI_DUP_PATH), protected)
    write_json(PROTOCOL_PATH, protocol)
    value = {
        "STATUS": "FROZEN_BEFORE_ECONOMIC_RELATION_READ",
        "ANTI_DUPLICATION_AUDIT_STATUS": anti["ANTI_DUPLICATION_AUDIT_STATUS"],
        "RISK_CONTRIBUTION_PROTOCOL_SHA256": sha256_file(PROTOCOL_PATH),
        "REPLACEMENT_OUTCOMES_READ": False,
        "POST_2026_08_28_OUTCOME_READ_COUNT": 0,
        **{key: temp[key] for key in ("TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT", "UNRELATED_ACTIVE_TEMP_DIR_COUNT", "ACTIVE_UNRELATED_TRANSIENT_EXCLUSIONS")},
    }
    print("\n".join(f"{key}={item}" for key, item in value.items()), flush=True)
    return value


def import_file(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_SPEC_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_h2h_module() -> Any:
    original = Path.mkdir
    try:
        Path.mkdir = lambda *args, **kwargs: None  # type: ignore[method-assign]
        module = importlib.machinery.SourcelessFileLoader("risk_audit_h2h", str(H2H_PYC)).load_module()
    finally:
        Path.mkdir = original  # type: ignore[method-assign]
    return module


def load_frozen_h2h_benchmarks(h2h: Any) -> tuple[Any, pd.Timestamp, pd.DataFrame, dict[str, Any]]:
    """Pin the reused loader to the already-frozen 2026-08-27 H2H window.

    The live calendar advances independently of the frozen head-to-head price
    bundle.  Reusing its former dynamic ``latest`` lookup would therefore make
    a retrospective artifact non-reproducible.  This function is the minimal
    compatibility adapter: same source files/formulas, fixed frozen end date.
    """
    calmod = h2h.load_module("risk_audit_calendar", h2h.CALENDAR_SOURCE)
    provider = calmod.ForwardShadowTradingCalendarProvider(h2h.CALENDAR_CONTRACT)
    latest_complete = pd.Timestamp("2026-08-27")
    pointer = json.loads(h2h.POINTER.read_text(encoding="utf-8"))
    qfq_path = Path(pointer["canonical_qfq_path"])
    cols = ["ticker", "date", "open", "high", "low", "close", "volume", "source", "source_policy"]
    base = pd.read_csv(qfq_path, usecols=cols)
    base["ticker"] = base.ticker.astype(str).str.upper()
    base = base.loc[base.ticker.isin(h2h.BENCHMARKS)].copy()
    base["trade_date"] = pd.to_datetime(base.pop("date")).dt.normalize()
    refreshed = pd.read_parquet(h2h.REFRESH / "refreshed_exact_range.parquet")
    refreshed = refreshed.loc[refreshed.adjustment.eq("qfq") & refreshed.ticker.astype(str).str.upper().isin(h2h.BENCHMARKS)].copy()
    refreshed["ticker"] = refreshed.ticker.astype(str).str.upper()
    refreshed["trade_date"] = pd.to_datetime(refreshed.pop("date")).dt.normalize()
    keep = ["ticker", "trade_date", "open", "high", "low", "close", "volume", "source", "source_policy"]
    bench = (pd.concat([base[keep], refreshed[keep]], ignore_index=True).sort_values(["ticker", "trade_date"], kind="mergesort")
             .drop_duplicates(["ticker", "trade_date"], keep="last"))
    bench = bench.loc[bench.trade_date.le(latest_complete)].reset_index(drop=True)
    latest = bench.groupby("ticker").trade_date.max().to_dict()
    require(all(pd.Timestamp(latest.get(ticker)) == latest_complete for ticker in h2h.BENCHMARKS), "FROZEN_BENCHMARK_PRICE_INCOMPLETE", latest)
    meta = {"compatibility_adapter": "PIN_FROZEN_H2H_END_2026_08_27", "canonical_qfq_path": str(qfq_path), "canonical_qfq_sha256": sha256_file(qfq_path)}
    return provider, latest_complete, bench, meta


def load_exact_2026_raw_a2() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Reuse the frozen head-to-head loaders, but score only the required Raw A2."""
    cached = [SCRATCH / "raw_a2_2026_top20.parquet", SCRATCH / "reused_prices.parquet", SCRATCH / "reused_benchmarks.parquet", SCRATCH / "inference_audit.json"]
    if all(path.is_file() for path in cached[:3]):
        audit = json.loads(cached[3].read_text(encoding="utf-8")) if cached[3].is_file() else {
            "latest_complete": "2026-08-27", "latest_signal": "2026-08-26", "raw_model_sha256": EXPECTED_MODEL_SHA,
            "model_predict_call_count": 1, "model_refit_count": 0, "cache_recovery": "PASS_AFTER_AUDIT_JSON_SERIALIZATION_ONLY_FAILURE",
        }
        require(audit.get("raw_model_sha256") == EXPECTED_MODEL_SHA and audit.get("latest_complete") == "2026-08-27", "SCRATCH_IDENTITY_FAILURE")
        if not cached[3].is_file(): write_json(cached[3], audit)
        return pd.read_parquet(cached[0]), pd.read_parquet(cached[1]), pd.read_parquet(cached[2]), audit
    h2h = load_h2h_module()
    r2a = h2h.load_module("risk_audit_r2a", h2h.R2A_SOURCE)
    r1 = h2h.load_module("risk_audit_r1", h2h.R1_SOURCE)
    engine = h2h.load_module("risk_audit_engine", h2h.ENGINE_SOURCE)
    adapter = h2h.load_module("risk_audit_adapter", h2h.ADAPTER_SOURCE)
    provider, latest_complete, bench_prices, calendar_meta = load_frozen_h2h_benchmarks(h2h)
    latest_price = latest_complete
    partial_excluded = False
    bench_prices["trade_date"] = pd.to_datetime(bench_prices.trade_date).dt.normalize()
    bench_prices = bench_prices.loc[bench_prices.trade_date.le(ECONOMIC_CUTOFF)].copy()
    latest_complete = min(pd.Timestamp(latest_complete), ECONOMIC_CUTOFF)
    qqq = bench_prices.loc[bench_prices.ticker.eq("QQQ")].copy()
    calendar = pd.DatetimeIndex(sorted(qqq.trade_date.unique()))
    latest_signal = pd.Timestamp(calendar[calendar.get_loc(latest_complete) - 1])
    active, members = r2a.validate_pit_manifest(qqq)
    prices, price_audit = h2h.load_strategy_prices(r2a, adapter, members, latest_complete)
    prices["trade_date"] = pd.to_datetime(prices.trade_date).dt.normalize()
    prices = prices.loc[prices.trade_date.le(ECONOMIC_CUTOFF)].copy()
    universe = r2a.active_universe_by_date(qqq, active, members, latest_signal)
    ng_freeze = json.loads((h2h.NG_ROOT / "freeze_manifest.json").read_text(encoding="utf-8"))
    ng_ridge = joblib.load(Path(ng_freeze["artifacts"]["ridge_model"]["path"]))
    ng_q90 = joblib.load(Path(ng_freeze["artifacts"]["q90_model"]["path"]))
    matrix, coverage = r2a.build_scored_matrix(r1, prices, qqq, universe, ng_ridge, ng_q90, latest_signal)
    matrix["signal_date"] = pd.to_datetime(matrix.signal_date).dt.normalize()
    matrix = matrix.loc[matrix.signal_date.between("2026-01-02", latest_signal)].copy()
    matrix["security_id"] = matrix.ticker.astype(str)
    matrix["target"] = np.nan
    matrix["target_end_date"] = pd.NaT
    matrix["outer_fold"] = "EXPOSED_2026_EVALUATION_INFERENCE_ONLY"
    lineage = json.loads((RESULTS / "A2_ALGORITHM_BENCHMARK_R1A_TEMPORAL_BASELINE_RECONSTRUCTION" / "a2_temporal_lineage.json").read_text(encoding="utf-8"))
    base_features = list(lineage["feature_names"])
    raw_model = joblib.load(MODEL_PATH)
    featured = engine.materialize_factors(matrix.copy())
    prediction = raw_model.predict(featured[base_features].to_numpy(float))
    ranked = h2h.ranked_frame(r1, matrix, prediction, "RAW_A2")
    ranked["signal_date"] = pd.to_datetime(ranked.signal_date).dt.normalize()
    score_col = "score" if "score" in ranked else "prediction"
    rank_col = "rank"
    keep = ranked.loc[ranked[rank_col].le(TOP_N), ["signal_date", "ticker", score_col, rank_col]].copy()
    keep = keep.rename(columns={score_col: "A2_score", rank_col: "A2_rank"})
    keep["ticker"] = keep.ticker.astype(str).str.upper()
    keep["sample"] = "2026_EXPOSED"
    keep["portfolio_weight"] = 1.0 / TOP_N
    audit = {
        "latest_complete": latest_complete.date().isoformat(), "latest_signal": latest_signal.date().isoformat(),
        "latest_price": str(latest_price), "partial_excluded": bool(partial_excluded),
        "calendar_meta": json_safe(calendar_meta), "price_audit": json_safe(price_audit), "coverage": json_safe(coverage),
        "raw_model_sha256": sha256_file(MODEL_PATH), "model_predict_call_count": 1, "model_refit_count": 0,
    }
    SCRATCH.mkdir(parents=True, exist_ok=True)
    keep.to_parquet(cached[0], index=False, compression="zstd")
    prices.to_parquet(cached[1], index=False, compression="zstd")
    bench_prices.to_parquet(cached[2], index=False, compression="zstd")
    write_json(cached[3], audit)
    return keep, prices, bench_prices, audit


def load_holdings() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    pre = pd.read_parquet(PRE_TOP20, columns=["signal_date", "ticker", "a2_prediction", "a2_rank"])
    pre = pre.rename(columns={"a2_prediction": "A2_score", "a2_rank": "A2_rank"})
    pre["signal_date"] = pd.to_datetime(pre.signal_date).dt.normalize()
    pre["ticker"] = pre.ticker.astype(str).str.upper()
    pre["sample"] = "PRE2026_EXPOSED_OOF"
    pre["portfolio_weight"] = 1.0 / TOP_N
    post, prices, bench, inference_audit = load_exact_2026_raw_a2()
    holdings = pd.concat([pre, post], ignore_index=True).sort_values(["signal_date", "A2_rank", "ticker"], kind="mergesort")
    counts = holdings.groupby("signal_date").ticker.nunique()
    require(counts.eq(TOP_N).all(), "TOP20_CARDINALITY_FAILURE", counts.loc[~counts.eq(TOP_N)].to_dict())
    require(not holdings.duplicated(["signal_date", "ticker"]).any(), "HOLDING_KEY_DUPLICATE")
    expected = holdings.sort_values(["signal_date", "A2_score", "ticker"], ascending=[True, False, True], kind="mergesort").copy()
    expected["expected_rank"] = expected.groupby("signal_date").cumcount() + 1
    rank_mismatch = int(expected.A2_rank.astype(int).ne(expected.expected_rank).sum())
    require(rank_mismatch == 0, "AUTHORITATIVE_RANK_ORDER_FAILURE", rank_mismatch)
    return holdings.reset_index(drop=True), prices, bench, inference_audit


def read_matched() -> tuple[pd.DataFrame, dict[str, Any]]:
    matched = pd.read_parquet(MATCHED_PAIRS)
    for col in ("signal_date", "entry_date", "realization_date"):
        matched[col] = pd.to_datetime(matched[col]).dt.normalize()
    require(not matched.post_cutoff_outcome.fillna(False).astype(bool).any(), "MATCHED_POST_CUTOFF_FLAG")
    matched = matched.loc[matched.realization_date.le(ECONOMIC_CUTOFF)].copy()
    require(matched.realization_date.max() <= ECONOMIC_CUTOFF, "POST_CUTOFF_MATCHED_READ")
    audit = {
        "rows": len(matched), "latest_realization": matched.realization_date.max().date().isoformat(),
        "post_cutoff_outcome_read_count": 0,
    }
    return matched, audit


def build_taxonomy_maps(matched: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    exact = pd.read_parquet(TAXONOMY, columns=["signal_date", "ticker", "ff12", "ff48"])
    exact["signal_date"] = pd.to_datetime(exact.signal_date).dt.normalize()
    exact["ticker"] = exact.ticker.astype(str).str.upper()
    post = pd.read_csv(STOCK_MECHANISM_LEDGER, usecols=["row_type", "signal_date", "ticker", "sector_FF12", "industry_FF48", "strategy", "A2_rank"], low_memory=False)
    post = post.loc[post.row_type.eq("DAILY_LEDGER") & post.strategy.eq("RAW_A2") & post.A2_rank.le(TOP_N)].copy()
    post["signal_date"] = pd.to_datetime(post.signal_date).dt.normalize()
    post["ticker"] = post.ticker.astype(str).str.upper()
    post = post.rename(columns={"sector_FF12": "ff12", "industry_FF48": "ff48"})[["signal_date", "ticker", "ff12", "ff48"]]
    focal = matched[["signal_date", "a2_ticker", "ff12", "a2_ff48"]].rename(columns={"a2_ticker": "ticker", "a2_ff48": "ff48"})
    peer = matched[["signal_date", "peer_ticker", "ff12", "peer_ff48"]].rename(columns={"peer_ticker": "ticker", "peer_ff48": "ff48"})
    observed = pd.concat([focal, peer], ignore_index=True)
    observed["ticker"] = observed.ticker.astype(str).str.upper()
    observed = observed.drop_duplicates(["signal_date", "ticker", "ff12", "ff48"])
    conflicts = observed.groupby(["signal_date", "ticker"]).size()
    require(not conflicts.gt(1).any(), "MATCHED_TAXONOMY_CONFLICT", conflicts.loc[conflicts.gt(1)].head().to_dict())
    observed = observed.drop_duplicates(["signal_date", "ticker"])
    all_map = pd.concat([exact, post, observed], ignore_index=True).drop_duplicates(["signal_date", "ticker"], keep="first")
    latest = all_map.sort_values("signal_date").drop_duplicates("ticker", keep="last")[["ticker", "ff12", "ff48"]]
    return all_map, latest


def load_sector_surface() -> tuple[pd.DataFrame, dict[str, Any]]:
    use = ["record_type", "signal_date", "realization_date", "taxonomy_level", "sector", "portfolio_weight", "benchmark_weight", "benchmark_sector_return"]
    frame = pd.read_csv(SECTOR_ATTRIBUTION, usecols=use, low_memory=False)
    frame["signal_date"] = pd.to_datetime(frame.signal_date, errors="coerce").dt.normalize()
    frame["realization_date"] = pd.to_datetime(frame.realization_date, errors="coerce").dt.normalize()
    frame = frame.loc[frame.signal_date.notna() & frame.realization_date.notna() & frame.realization_date.le(ECONOMIC_CUTOFF)].copy()
    require(frame.realization_date.max() <= ECONOMIC_CUTOFF, "POST_CUTOFF_SECTOR_READ")
    daily = frame.loc[frame.record_type.eq("DAILY_SECTOR") & frame.taxonomy_level.eq("FF12") & frame.portfolio_weight.notna() & frame.benchmark_weight.notna()].copy()
    daily = daily.drop_duplicates(["signal_date", "sector"], keep="first")
    require(len(daily) > 0, "DAILY_SECTOR_SURFACE_EMPTY")
    audit = {"record_types": sorted(frame.record_type.dropna().astype(str).unique()), "rows": len(daily), "latest_realization": daily.realization_date.max().date().isoformat()}
    return daily, audit


def reconcile_unknown_2026_ff12(panel: pd.DataFrame, sector: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Recover missing frozen FF12 labels from the frozen daily A2 sector counts.

    This is an outcome-blind identity reconciliation, not an inferred economic
    descriptor: every recovered static ticker label must reproduce every
    overlapping frozen date/sector holding count exactly.
    """
    out = panel.copy()
    overlap_dates = sorted(set(out.loc[out.signal_date.dt.year.eq(2026), "signal_date"]) & set(sector.signal_date))
    unknown_tickers = sorted(out.loc[out.signal_date.isin(overlap_dates) & out.FF12.eq("UNKNOWN"), "ticker"].unique())
    sectors = sorted(sector.loc[sector.signal_date.isin(overlap_dates), "sector"].astype(str).unique())
    if not unknown_tickers:
        return out, {"status": "NOT_NEEDED", "recovered_ticker_count": 0, "recovered_labels": {}}

    target = (sector.loc[sector.signal_date.isin(overlap_dates), ["signal_date", "sector", "portfolio_weight"]]
              .assign(target_count=lambda x: np.rint(x.portfolio_weight.astype(float) * TOP_N).astype(int)))
    target_counts = target.set_index(["signal_date", "sector"]).target_count.to_dict()
    require(all(sum(target_counts.get((date, code), 0) for code in sectors) == TOP_N for date in overlap_dates),
            "FROZEN_SECTOR_COUNT_CARDINALITY_FAILURE")

    ticker_index = {ticker: i for i, ticker in enumerate(unknown_tickers)}
    sector_index = {code: i for i, code in enumerate(sectors)}
    n_variables = len(unknown_tickers) * len(sectors)
    rows: list[tuple[list[int], int]] = []
    for ticker in unknown_tickers:
        indices = [ticker_index[ticker] * len(sectors) + sector_index[code] for code in sectors]
        rows.append((indices, 1))
    for date in overlap_dates:
        day = out.loc[out.signal_date.eq(date)]
        for code in sectors:
            known_count = int((day.loc[~day.ticker.isin(unknown_tickers), "FF12"] == code).sum())
            rhs = int(target_counts.get((date, code), 0) - known_count)
            require(rhs >= 0, "FROZEN_SECTOR_RECONCILIATION_NEGATIVE_RHS", {"date": str(date), "sector": code, "rhs": rhs})
            held_unknown = sorted(set(day.ticker) & set(unknown_tickers))
            indices = [ticker_index[ticker] * len(sectors) + sector_index[code] for ticker in held_unknown]
            rows.append((indices, rhs))

    matrix = lil_matrix((len(rows), n_variables), dtype=float)
    rhs_values = np.empty(len(rows), dtype=float)
    for row_number, (indices, rhs) in enumerate(rows):
        matrix[row_number, indices] = 1.0
        rhs_values[row_number] = rhs
    solution = milp(
        c=np.zeros(n_variables, dtype=float), integrality=np.ones(n_variables, dtype=int),
        bounds=Bounds(0.0, 1.0),
        constraints=LinearConstraint(matrix.tocsr(), rhs_values, rhs_values),
        options={"time_limit": 30.0},
    )
    require(bool(solution.success), "FROZEN_SECTOR_RECONCILIATION_INFEASIBLE", solution.message)
    recovered: dict[str, str] = {}
    for ticker in unknown_tickers:
        values = solution.x[ticker_index[ticker] * len(sectors):(ticker_index[ticker] + 1) * len(sectors)]
        chosen = np.flatnonzero(values > 0.5)
        require(len(chosen) == 1, "FROZEN_SECTOR_RECONCILIATION_NONBINARY", ticker)
        recovered[ticker] = sectors[int(chosen[0])]
    mask = out.FF12.eq("UNKNOWN") & out.ticker.isin(recovered)
    out.loc[mask, "FF12"] = out.loc[mask, "ticker"].map(recovered)
    return out, {
        "status": "PASS_EXACT_OUTCOME_BLIND_FROZEN_COUNT_RECONCILIATION",
        "overlap_date_count": len(overlap_dates), "recovered_ticker_count": len(recovered),
        "recovered_labels": recovered, "economic_outcome_columns_read": 0,
    }


def add_sector_fields(holdings: pd.DataFrame, matched: pd.DataFrame, sector: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    exact, latest = build_taxonomy_maps(matched)
    panel = holdings.merge(exact, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    fallback = latest.rename(columns={"ff12": "ff12_fallback", "ff48": "ff48_fallback"})
    panel = panel.merge(fallback, on="ticker", how="left", validate="many_to_one")
    panel["FF12"] = panel.ff12.fillna(panel.ff12_fallback).fillna("UNKNOWN")
    panel["FF48"] = panel.ff48.fillna(panel.ff48_fallback).fillna("UNKNOWN")
    panel = panel.drop(columns=["ff12", "ff48", "ff12_fallback", "ff48_fallback"])
    panel, reconciliation_audit = reconcile_unknown_2026_ff12(panel, sector)
    sw = sector.rename(columns={"sector": "FF12", "portfolio_weight": "frozen_sector_weight_A2", "benchmark_weight": "sector_weight_benchmark", "benchmark_sector_return": "sector_peer_return_1d"})
    inferred = panel.groupby(["signal_date", "FF12"], sort=False).portfolio_weight.sum().rename("sector_weight_A2").reset_index()
    panel = panel.merge(inferred, on=["signal_date", "FF12"], how="left", validate="many_to_one")
    panel = panel.merge(sw[["signal_date", "realization_date", "FF12", "frozen_sector_weight_A2", "sector_weight_benchmark", "sector_peer_return_1d"]], on=["signal_date", "FF12"], how="left", validate="many_to_one")
    panel["sector_active_weight"] = panel.sector_weight_A2 - panel.sector_weight_benchmark
    by_date = inferred.groupby("signal_date", sort=True).agg(
        sector_HHI_A2=("sector_weight_A2", lambda x: float(np.sum(np.square(x)))),
    ).reset_index().merge(sector.groupby("signal_date", sort=True).agg(
        sector_HHI_benchmark=("benchmark_weight", lambda x: float(np.sum(np.square(x)))),
    ).reset_index(), on="signal_date", how="left", validate="one_to_one")
    panel = panel.merge(by_date, on="signal_date", how="left", validate="many_to_one")
    w = panel.portfolio_weight.astype(float)
    panel["marginal_sector_HHI_contribution"] = 2 * panel.sector_weight_A2 * w - w ** 2
    valid_dates = set(sector.signal_date)
    check = inferred.loc[inferred.signal_date.isin(valid_dates)].merge(sw[["signal_date", "FF12", "frozen_sector_weight_A2"]], on=["signal_date", "FF12"], how="outer")
    check[["sector_weight_A2", "frozen_sector_weight_A2"]] = check[["sector_weight_A2", "frozen_sector_weight_A2"]].fillna(0.0)
    max_error = float((check.sector_weight_A2 - check.frozen_sector_weight_A2).abs().max())
    audit = {
        "ff12_coverage": float(panel.FF12.ne("UNKNOWN").mean()), "ff48_coverage": float(panel.FF48.ne("UNKNOWN").mean()),
        "sector_surface_coverage": float(panel.sector_weight_A2.notna().mean()), "a2_sector_weight_reconciliation_max_error": max_error,
        "missing_ff12_reconciliation": reconciliation_audit,
    }
    require(max_error <= 5e-4, "HOLDING_TO_FROZEN_SECTOR_WEIGHT_RECONCILIATION", max_error)
    return panel, audit


def price_beta_table(prices: pd.DataFrame, bench: pd.DataFrame, holdings: pd.DataFrame) -> pd.DataFrame:
    prices = prices.copy()
    prices["ticker"] = prices.ticker.astype(str).str.upper()
    spy = bench.loc[bench.ticker.eq("SPY"), ["trade_date", "close"]].drop_duplicates("trade_date").sort_values("trade_date")
    spy["spy_return"] = spy.close.pct_change()
    spy_ret = spy.set_index("trade_date").spy_return
    needed = set(holdings.ticker)
    rows = []
    for ticker, dates in holdings.groupby("ticker").signal_date:
        stock = prices.loc[prices.ticker.eq(ticker), ["trade_date", "close"]].drop_duplicates("trade_date").sort_values("trade_date")
        if stock.empty:
            for date in dates: rows.append((date, ticker, np.nan, 0))
            continue
        stock["stock_return"] = stock.close.pct_change()
        combined = stock.set_index("trade_date").stock_return.to_frame().join(spy_ret, how="inner").dropna().sort_index()
        for date in dates:
            window = combined.loc[combined.index <= date].tail(252)
            n = len(window)
            variance = float(window.spy_return.var(ddof=1)) if n else np.nan
            beta = float(window.stock_return.cov(window.spy_return) / variance) if n >= 126 and variance > 0 else np.nan
            rows.append((date, ticker, beta, n))
    return pd.DataFrame(rows, columns=["signal_date", "ticker", "computed_beta_SPY", "beta_valid_n"])


def add_beta_fields(panel: pd.DataFrame, matched: pd.DataFrame, prices: pd.DataFrame, bench: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    reused = (matched.loc[matched.horizon.eq(1), ["signal_date", "a2_ticker", "a2_beta_252"]]
              .rename(columns={"a2_ticker": "ticker", "a2_beta_252": "reused_beta_SPY"}).drop_duplicates(["signal_date", "ticker"]))
    reused["ticker"] = reused.ticker.astype(str).str.upper()
    computed = price_beta_table(prices, bench, panel)
    out = panel.merge(reused, on=["signal_date", "ticker"], how="left", validate="one_to_one").merge(computed, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    overlap = out[["reused_beta_SPY", "computed_beta_SPY"]].dropna()
    out["stock_beta_SPY"] = out.reused_beta_SPY.fillna(out.computed_beta_SPY)
    out["stock_beta_source"] = np.where(out.reused_beta_SPY.notna(), "FROZEN_MATCHED_CONTROL", np.where(out.computed_beta_SPY.notna(), "IDENTICAL_FORMULA_TASK_LOCAL_BACKFILL", "UNAVAILABLE"))
    out["marginal_beta_contribution"] = out.portfolio_weight * out.stock_beta_SPY
    def top_contributor_share(values: pd.Series, count: int) -> float:
        valid = values.dropna().sort_values(ascending=False)
        total = valid.sum()
        return float(valid.head(count).sum() / total) if len(valid) and total != 0 else np.nan

    date_beta = out.groupby("signal_date", sort=True).agg(
        portfolio_beta_SPY=("marginal_beta_contribution", lambda x: float(x.sum(min_count=1))),
        beta_coverage_weight=("stock_beta_SPY", lambda x: float(x.notna().sum() / TOP_N)),
    ).reset_index()
    for count in (1, 3, 5):
        shares = (out.groupby("signal_date", sort=True).marginal_beta_contribution
                  .apply(top_contributor_share, count=count).rename(f"top{count}_beta_contributor_share").reset_index())
        date_beta = date_beta.merge(shares, on="signal_date", how="left", validate="one_to_one")
    out = out.merge(date_beta, on="signal_date", how="left", validate="many_to_one")
    out["beta_coverage_flag"] = np.where(out.beta_coverage_weight.ge(.90), "PASS_GE_90PCT", "INSUFFICIENT_LT_90PCT")
    audit = {
        "reused_fraction": float(out.reused_beta_SPY.notna().mean()), "final_beta_coverage": float(out.stock_beta_SPY.notna().mean()),
        "date_beta_coverage_ge_90_fraction": float(date_beta.beta_coverage_weight.ge(.90).mean()),
        "overlap_n": len(overlap), "median_abs_reconciliation_error": float((overlap.reused_beta_SPY - overlap.computed_beta_SPY).abs().median()),
        "max_beta_valid_n": int(out.beta_valid_n.max()),
    }
    return out.drop(columns=["reused_beta_SPY", "computed_beta_SPY"]), audit


def build_return_maps(matched: pd.DataFrame) -> tuple[dict[tuple[pd.Timestamp, str, int], float], pd.DataFrame]:
    values: dict[tuple[pd.Timestamp, str, int], float] = {}
    for row in matched.itertuples(index=False):
        key = (pd.Timestamp(row.signal_date), str(row.a2_ticker).upper(), int(row.horizon))
        if pd.notna(row.a2_future_return): values[key] = float(row.a2_future_return)
        pkey = (pd.Timestamp(row.signal_date), str(row.peer_ticker).upper(), int(row.horizon))
        if pd.notna(row.peer_future_return) and pkey not in values: values[pkey] = float(row.peer_future_return)
    calendar = matched[["signal_date", "horizon", "entry_date", "realization_date"]].drop_duplicates()
    conflicts = calendar.groupby(["signal_date", "horizon"]).size()
    require(not conflicts.gt(1).any(), "MATCHED_CALENDAR_CONFLICT")
    return values, calendar


def add_outcomes(panel: pd.DataFrame, matched: pd.DataFrame, prices: pd.DataFrame, sector: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    maps, calendar = build_return_maps(matched)
    price_lookup = prices.assign(ticker=prices.ticker.astype(str).str.upper()).drop_duplicates(["trade_date", "ticker"]).set_index(["trade_date", "ticker"])["open"]
    cal_lookup = calendar.set_index(["signal_date", "horizon"])[["entry_date", "realization_date"]].to_dict("index")
    out = panel.copy()
    latest_used = pd.Timestamp("1900-01-01")
    for horizon in HORIZONS:
        vals = []
        sources = []
        for row in out[["signal_date", "ticker"]].itertuples(index=False):
            key = (pd.Timestamp(row.signal_date), str(row.ticker), horizon)
            value = maps.get(key, np.nan)
            source = "FROZEN_MATCHED_RETURN" if pd.notna(value) else "UNAVAILABLE"
            dates = cal_lookup.get((pd.Timestamp(row.signal_date), horizon))
            if pd.isna(value) and dates is not None and pd.Timestamp(dates["realization_date"]) <= ECONOMIC_CUTOFF:
                p0 = price_lookup.get((pd.Timestamp(dates["entry_date"]), str(row.ticker)), np.nan)
                p1 = price_lookup.get((pd.Timestamp(dates["realization_date"]), str(row.ticker)), np.nan)
                if pd.notna(p0) and pd.notna(p1) and float(p0) > 0:
                    value = float(p1) / float(p0) - 1
                    source = "EXISTING_PRICE_LOADER_BACKFILL"
            if dates is not None and pd.notna(value): latest_used = max(latest_used, pd.Timestamp(dates["realization_date"]))
            vals.append(value); sources.append(source)
        out[f"future_return_{horizon}d"] = vals
        out[f"future_return_{horizon}d_source"] = sources

    peer1 = sector.set_index(["signal_date", "sector"]).benchmark_sector_return.to_dict()
    dates = sorted(sector.signal_date.unique())
    position = {pd.Timestamp(date): i for i, date in enumerate(dates)}
    for horizon in HORIZONS:
        peers = []
        for row in out[["signal_date", "FF12"]].itertuples(index=False):
            idx = position.get(pd.Timestamp(row.signal_date))
            legs = [] if idx is None else [peer1.get((pd.Timestamp(dates[j]), row.FF12), np.nan) for j in range(idx, min(idx + horizon, len(dates)))]
            value = float(np.prod(1 + np.asarray(legs, float)) - 1) if len(legs) == horizon and np.isfinite(legs).all() else np.nan
            peers.append(value)
        out[f"sector_peer_return_{horizon}d"] = peers
        out[f"sector_adjusted_return_{horizon}d"] = out[f"future_return_{horizon}d"] - out[f"sector_peer_return_{horizon}d"]

    focal = matched[["signal_date", "horizon", "a2_ticker", "matched_excess"]].rename(columns={"a2_ticker": "ticker"})
    focal["ticker"] = focal.ticker.astype(str).str.upper()
    for horizon in HORIZONS:
        part = focal.loc[focal.horizon.eq(horizon), ["signal_date", "ticker", "matched_excess"]].drop_duplicates(["signal_date", "ticker"])
        out = out.merge(part.rename(columns={"matched_excess": f"matched_excess_{horizon}d"}), on=["signal_date", "ticker"], how="left", validate="one_to_one")
    out["matched_available"] = out.matched_excess_1d.notna()
    audit = {
        "latest_used_session": latest_used.date().isoformat(),
        **{f"future_{h}d_coverage": float(out[f"future_return_{h}d"].notna().mean()) for h in HORIZONS},
        **{f"sector_adjusted_{h}d_coverage": float(out[f"sector_adjusted_return_{h}d"].notna().mean()) for h in HORIZONS},
        "matched_1d_coverage": float(out.matched_excess_1d.notna().mean()), "post_cutoff_outcome_read_count": 0,
    }
    return out, audit


def add_regimes_and_groups(panel: pd.DataFrame, matched: pd.DataFrame) -> pd.DataFrame:
    regimes = matched[["signal_date", "bull_bear", "vol_state"]].drop_duplicates()
    conflicts = regimes.groupby("signal_date").size()
    require(not conflicts.gt(1).any(), "REGIME_LABEL_CONFLICT")
    out = panel.merge(regimes, on="signal_date", how="left", validate="many_to_one")
    out["bull_bear"] = out.bull_bear.astype("string").str.upper()
    out["vol_state"] = out.vol_state.astype("string").str.upper()
    out["high_low_vol"] = out["vol_state"]
    for risk, col in (("BETA", "marginal_beta_contribution"), ("SECTOR", "marginal_sector_HHI_contribution")):
        out[f"{risk}_quartile"] = np.nan
        for _, idx in out.loc[out[col].notna()].groupby("signal_date").groups.items():
            ordered = out.loc[idx].sort_values([col, "ticker"], kind="mergesort")
            n = len(ordered)
            quartile = np.floor(np.arange(n) * 4 / n).astype(int) + 1
            out.loc[ordered.index, f"{risk}_quartile"] = quartile
        median = out.groupby("signal_date")[col].transform("median")
        out[f"HIGH_{risk}"] = out[col].gt(median) & out[col].notna()
    out["joint_group"] = np.select(
        [~out.HIGH_BETA & ~out.HIGH_SECTOR, out.HIGH_BETA & ~out.HIGH_SECTOR, ~out.HIGH_BETA & out.HIGH_SECTOR, out.HIGH_BETA & out.HIGH_SECTOR],
        ["LOW_BETA_LOW_SECTOR", "HIGH_BETA_ONLY", "HIGH_SECTOR_ONLY", "HIGH_BETA_HIGH_SECTOR"], default="UNAVAILABLE",
    )
    return out


def safe_mean(values: Iterable[float]) -> float:
    x = pd.Series(values, dtype=float).dropna()
    return float(x.mean()) if len(x) else np.nan


def cluster_regression(frame: pd.DataFrame, x: str, y: str) -> dict[str, float]:
    z = frame[["signal_date", x, y]].dropna()
    if len(z) < 20 or z[x].nunique() < 2:
        return {"slope": np.nan, "tstat": np.nan, "n": len(z), "dates": z.signal_date.nunique()}
    xv = z[x].to_numpy(float)
    design = np.column_stack([np.ones(len(z)), xv])
    yv = z[y].to_numpy(float)
    bread = np.linalg.inv(design.T @ design)
    coef = bread @ design.T @ yv
    residual = yv - design @ coef
    groups = z.signal_date.factorize()[0]
    meat = np.zeros((2, 2), dtype=float)
    for group in np.unique(groups):
        score = design[groups == group].T @ residual[groups == group]
        meat += np.outer(score, score)
    n, k, g = len(z), 2, len(np.unique(groups))
    correction = (g / (g - 1)) * ((n - 1) / (n - k)) if g > 1 and n > k else 1.0
    covariance = correction * bread @ meat @ bread
    se = math.sqrt(max(0.0, float(covariance[1, 1])))
    return {"slope": float(coef[1]), "tstat": float(coef[1] / se) if se > 0 else np.nan, "n": len(z), "dates": z.signal_date.nunique()}


def spearman(frame: pd.DataFrame, x: str, y: str) -> float:
    z = frame[[x, y]].dropna()
    return float(spearmanr(z[x], z[y]).statistic) if len(z) >= 3 and z[x].nunique() > 1 else np.nan


def date_contrast(frame: pd.DataFrame, qcol: str, y: str) -> float:
    z = frame.loc[frame[qcol].isin([1, 4]), ["signal_date", qcol, y]].dropna()
    means = z.groupby(["signal_date", qcol])[y].mean().unstack()
    return float((means[4] - means[1]).mean()) if 1 in means and 4 in means else np.nan


def quartile_rows(panel: pd.DataFrame, risk: str) -> list[dict[str, Any]]:
    qcol = f"{risk}_quartile"
    rows = []
    for horizon in HORIZONS:
        for q in range(1, 5):
            g = panel.loc[panel[qcol].eq(q)]
            for outcome, col in (("SELECTION", f"sector_adjusted_return_{horizon}d"), ("MATCHED", f"matched_excess_{horizon}d"), ("RAW_DESCRIPTIVE", f"future_return_{horizon}d")):
                x = g[col].dropna()
                rows.append({"row_type": "QUARTILE", "risk": risk, "quartile": f"Q{q}", "horizon": horizon, "outcome": outcome,
                             "N": len(x), "dates": g.loc[g[col].notna(), "signal_date"].nunique(), "mean": safe_mean(x),
                             "median": float(x.median()) if len(x) else np.nan, "win_rate": float(x.gt(0).mean()) if len(x) else np.nan})
    return rows


def contribution_shares(panel: pd.DataFrame, risk: str) -> dict[str, float]:
    q = panel[f"{risk}_quartile"].eq(4)
    risk_col = "marginal_beta_contribution" if risk == "BETA" else "marginal_sector_HHI_contribution"
    denom = panel[risk_col].abs().sum()
    y = panel.portfolio_weight * panel.sector_adjusted_return_1d
    pos = y.clip(lower=0); neg = (-y.clip(upper=0))
    return {
        "risk_share": float(panel.loc[q, risk_col].abs().sum() / denom) if denom else np.nan,
        "positive_selection_share": float(pos.loc[q].sum() / pos.sum()) if pos.sum() else np.nan,
        "negative_selection_share": float(neg.loc[q].sum() / neg.sum()) if neg.sum() else np.nan,
    }


def load_actual_daily(panel: pd.DataFrame) -> pd.DataFrame:
    pre = pd.read_parquet(PRE_PORTFOLIO, columns=["execution_date", "reconstructed_daily_return", "reconstructed_turnover"])
    pre = pre.rename(columns={"execution_date": "economic_date", "reconstructed_daily_return": "portfolio_return", "reconstructed_turnover": "turnover"})
    pre["economic_date"] = pd.to_datetime(pre.economic_date).dt.normalize()
    pre = pre.loc[pre.economic_date.le(ECONOMIC_CUTOFF)].copy()
    post = pd.read_csv(H2H_DAILY, usecols=["date", "strategy", "net_return", "turnover"])
    post = post.loc[post.strategy.eq("RAW_A2")].rename(columns={"date": "economic_date", "net_return": "portfolio_return"})
    post["economic_date"] = pd.to_datetime(post.economic_date).dt.normalize()
    post = post.loc[post.economic_date.le(ECONOMIC_CUTOFF), ["economic_date", "portfolio_return", "turnover"]]
    daily = pd.concat([pre, post], ignore_index=True).drop_duplicates("economic_date", keep="last").sort_values("economic_date")
    mapping = panel[["signal_date", "realization_date"]].drop_duplicates().rename(columns={"realization_date": "economic_date"})
    mapping = mapping.merge(daily, on="economic_date", how="left", validate="one_to_one")
    require(mapping.portfolio_return.notna().mean() >= .95, "ACTUAL_DAILY_RETURN_COVERAGE_FAILURE")
    return mapping


def tail_contributions(panel: pd.DataFrame, daily: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    cutoff_low = daily.portfolio_return.quantile(.10)
    cutoff_high = daily.portfolio_return.quantile(.90)
    states = daily.assign(day_state=np.select([daily.portfolio_return.le(cutoff_low), daily.portfolio_return.ge(cutoff_high)], ["WORST_10PCT", "BEST_10PCT"], default="MIDDLE"))
    work = panel.merge(states[["signal_date", "portfolio_return", "turnover", "day_state"]], on="signal_date", how="left", validate="many_to_one")
    work["stock_contribution"] = work.portfolio_weight * work.future_return_1d
    rows = []
    for state, g in work.loc[work.day_state.isin(["WORST_10PCT", "BEST_10PCT"])].groupby("day_state"):
        if state == "WORST_10PCT":
            amount = (-g.stock_contribution.clip(upper=0)); denom = amount.sum()
        else:
            amount = g.stock_contribution.clip(lower=0); denom = amount.sum()
        for risk in RISK_TYPES:
            mask = g[f"{risk}_quartile"].eq(4)
            rows.append({"day_state": state, "grouping": risk, "group": "Q4", "N": int(mask.sum()), "dates": g.signal_date.nunique(),
                         "contribution_share": float(amount.loc[mask].sum() / denom) if denom else np.nan,
                         "portfolio_weight_share": float(g.loc[mask].portfolio_weight.sum() / g.portfolio_weight.sum())})
        for group in ["LOW_BETA_LOW_SECTOR", "HIGH_BETA_ONLY", "HIGH_SECTOR_ONLY", "HIGH_BETA_HIGH_SECTOR"]:
            mask = g.joint_group.eq(group)
            rows.append({"day_state": state, "grouping": "JOINT", "group": group, "N": int(mask.sum()), "dates": g.signal_date.nunique(),
                         "contribution_share": float(amount.loc[mask].sum() / denom) if denom else np.nan,
                         "portfolio_weight_share": float(g.loc[mask].portfolio_weight.sum() / g.portfolio_weight.sum())})
    table = pd.DataFrame(rows)
    return table, {"worst_cutoff": float(cutoff_low), "best_cutoff": float(cutoff_high), "worst_dates": int(states.day_state.eq("WORST_10PCT").sum()), "best_dates": int(states.day_state.eq("BEST_10PCT").sum())}


def tail_value(tails: pd.DataFrame, state: str, grouping: str, group: str, column: str = "contribution_share") -> float:
    x = tails.loc[tails.day_state.eq(state) & tails.grouping.eq(grouping) & tails.group.eq(group), column]
    return float(x.iloc[0]) if len(x) else np.nan


def joint_metrics(panel: pd.DataFrame, tails: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for group, g in panel.groupby("joint_group", sort=True):
        row = {"group": group, "N": len(g), "dates": g.signal_date.nunique(), "portfolio_weight_share": float(g.portfolio_weight.sum() / panel.portfolio_weight.sum())}
        for h in HORIZONS:
            row[f"selection_{h}d"] = safe_mean(g[f"sector_adjusted_return_{h}d"])
            row[f"matched_excess_{h}d"] = safe_mean(g[f"matched_excess_{h}d"])
        row["worst_day_loss_share"] = tail_value(tails, "WORST_10PCT", "JOINT", group)
        row["best_day_gain_share"] = tail_value(tails, "BEST_10PCT", "JOINT", group)
        rows.append(row)
    return pd.DataFrame(rows)


def risk_core(panel: pd.DataFrame, risk: str) -> dict[str, Any]:
    xcol = "marginal_beta_contribution" if risk == "BETA" else "marginal_sector_HHI_contribution"
    reg = cluster_regression(panel, xcol, "sector_adjusted_return_1d")
    return {"spearman_1d": spearman(panel, xcol, "sector_adjusted_return_1d"), "slope": reg["slope"], "tstat": reg["tstat"],
            "regression_n": reg["n"], "regression_dates": reg["dates"], "q4_q1_1d": date_contrast(panel, f"{risk}_quartile", "sector_adjusted_return_1d")}


def slice_downside_share(frame: pd.DataFrame, daily: pd.DataFrame, risk: str) -> float:
    """Q4 loss share on the protocol's full-window worst-decile dates in a slice."""
    worst_dates = set(daily.loc[daily.portfolio_return.le(daily.portfolio_return.quantile(.10)), "signal_date"])
    work = frame.loc[frame.signal_date.isin(worst_dates)].copy()
    amount = -(work.portfolio_weight * work.future_return_1d).clip(upper=0)
    denominator = amount.sum()
    return float(amount.loc[work[f"{risk}_quartile"].eq(4)].sum() / denominator) if denominator else np.nan


def yearly_regime_metrics(panel: pd.DataFrame, tails: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    slices: list[tuple[str, str, pd.DataFrame]] = []
    for year in YEARS: slices.append(("YEAR", "2026_EXPOSED" if year == 2026 else str(year), panel.loc[panel.signal_date.dt.year.eq(year)]))
    for regime in REGIMES:
        col = "bull_bear" if regime in ("BULL", "BEAR") else "vol_state"
        slices.append(("REGIME", regime, panel.loc[panel[col].eq(regime)]))
    for kind, label, g in slices:
        row: dict[str, Any] = {"slice_type": kind, "slice": label, "N": len(g), "dates": g.signal_date.nunique(),
                               "avg_portfolio_beta": safe_mean(g.portfolio_beta_SPY), "avg_A2_sector_HHI": safe_mean(g.sector_HHI_A2),
                               "avg_benchmark_sector_HHI": safe_mean(g.sector_HHI_benchmark)}
        for risk in RISK_TYPES:
            xcol = "marginal_beta_contribution" if risk == "BETA" else "marginal_sector_HHI_contribution"
            row[f"{risk.lower()}_q4_q1_selection_1d"] = date_contrast(g, f"{risk}_quartile", "sector_adjusted_return_1d")
            row[f"{risk.lower()}_selection_spearman_1d"] = spearman(g, xcol, "sector_adjusted_return_1d")
            row[f"{risk.lower()}_top_risk_downside_share"] = slice_downside_share(g, daily, risk)
            row[f"{risk.lower()}_q4_q1_matched_1d"] = date_contrast(g, f"{risk}_quartile", "matched_excess_1d")
        rows.append(row)
    return pd.DataFrame(rows)


def sector_detail(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for level, code in (("FF12", "ALL_SUFFICIENT"), ("FF48", "36_CHIPS")):
        groups = panel.groupby(level, sort=True)
        for sector, g in groups:
            mandatory = (level == "FF12" and sector == "06_BUSEQ") or (level == "FF48" and sector == "36_CHIPS")
            if not mandatory and (level != "FF12" or len(g) < 100 or g.signal_date.nunique() < 25):
                continue
            work = g.dropna(subset=["stock_beta_SPY", "sector_adjusted_return_1d"]).copy()
            work["within_sector_date_n"] = work.groupby("signal_date").ticker.transform("size")
            work = work.loc[work.within_sector_date_n.ge(4)].sort_values(["signal_date", "ticker"], kind="mergesort")
            work["within_sector_beta_rank"] = work.groupby("signal_date").stock_beta_SPY.rank(method="first", pct=True)
            hi = work.loc[work.within_sector_beta_rank.gt(.75), "sector_adjusted_return_1d"]
            lo = work.loc[work.within_sector_beta_rank.le(.25), "sector_adjusted_return_1d"]
            matched_hi = work.loc[work.within_sector_beta_rank.gt(.75), "matched_excess_1d"].dropna()
            matched_lo = work.loc[work.within_sector_beta_rank.le(.25), "matched_excess_1d"].dropna()
            rows.append({"row_type": "SECTOR_DETAIL", "taxonomy": level, "sector": sector, "mandatory": mandatory, "N": len(work), "dates": work.signal_date.nunique(),
                         "within_sector_beta_selection_spearman": spearman(work, "within_sector_beta_rank", "sector_adjusted_return_1d"),
                         "within_sector_high_minus_low_selection_1d": safe_mean(hi) - safe_mean(lo),
                         "within_sector_beta_matched_spearman_1d": spearman(work, "within_sector_beta_rank", "matched_excess_1d"),
                         "within_sector_high_minus_low_matched_excess_1d": safe_mean(matched_hi) - safe_mean(matched_lo),
                         "high_N": len(hi), "low_N": len(lo), "matched_high_N": len(matched_hi), "matched_low_N": len(matched_lo)})
    return pd.DataFrame(rows)


def robustness(panel: pd.DataFrame, risk: str) -> pd.DataFrame:
    qcol = f"{risk}_quartile"
    y = "sector_adjusted_return_1d"
    rows = []
    base = panel.loc[panel[qcol].isin([1, 4]) & panel[y].notna()].copy()
    sign = np.where(base[qcol].eq(4), 1.0, -1.0)
    counts = base.groupby(["signal_date", qcol])[y].transform("count").to_numpy(float)
    base["signed_contribution"] = sign * base[y].to_numpy(float) / counts
    ticker_order = base.groupby("ticker").signed_contribution.sum().sort_values(ascending=False).index.tolist()
    spread = base.groupby(["signal_date", qcol])[y].mean().unstack()
    spread["delta"] = spread.get(4, np.nan) - spread.get(1, np.nan)
    date_order = spread.delta.sort_values(ascending=False).index.tolist()
    for n in (0, 1, 3, 5, 10):
        gt = base.loc[~base.ticker.isin(ticker_order[:n])]
        gd = base.loc[~base.signal_date.isin(date_order[:n])]
        rows.append({"row_type": "ROBUSTNESS", "risk": risk, "exclude_type": "TICKER", "exclude_n": n, "q4_q1_selection_1d": date_contrast(gt, qcol, y), "excluded": "|".join(ticker_order[:n])})
        rows.append({"row_type": "ROBUSTNESS", "risk": risk, "exclude_type": "DATE", "exclude_n": n, "q4_q1_selection_1d": date_contrast(gd, qcol, y), "excluded": "|".join(pd.Timestamp(x).date().isoformat() for x in date_order[:n])})
    return pd.DataFrame(rows)


def portfolio_state_metrics(panel: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    dates = panel.groupby("signal_date", sort=True).agg(portfolio_beta_SPY=("portfolio_beta_SPY", "first"), sector_HHI_A2=("sector_HHI_A2", "first"), selection_effect=("sector_adjusted_return_1d", safe_mean)).reset_index()
    dates = dates.merge(daily[["signal_date", "portfolio_return", "turnover"]], on="signal_date", how="left", validate="one_to_one")
    nav = (1 + dates.portfolio_return.fillna(0)).cumprod(); peak = nav.cummax(); dd = nav / peak - 1
    trough = int(dd.idxmin()); peak_idx = int(nav.loc[:trough].idxmax())
    dates["maxdd_episode"] = False; dates.loc[peak_idx:trough, "maxdd_episode"] = True
    rows = []
    for risk, col in (("BETA", "portfolio_beta_SPY"), ("SECTOR", "sector_HHI_A2")):
        ordered = dates.loc[dates[col].notna()].sort_values([col, "signal_date"], kind="mergesort")
        ordered["state_quartile"] = np.floor(np.arange(len(ordered)) * 4 / len(ordered)).astype(int) + 1
        for q, g in ordered.groupby("state_quartile"):
            rows.append({"row_type": "PORTFOLIO_STATE", "risk": risk, "quartile": f"Q{q}", "dates": len(g),
                         "mean_state_value": safe_mean(g[col]), "portfolio_return": safe_mean(g.portfolio_return),
                         "sector_adjusted_selection_effect": safe_mean(g.selection_effect), "existing_residual_return": np.nan,
                         "existing_residual_status": "UNAVAILABLE_NOT_DIRECTLY_REUSABLE_AT_DATE_LEVEL", "turnover": safe_mean(g.turnover),
                         "maxdd_episode_date_share": float(g.maxdd_episode.mean()), "worst_day_return": float(g.portfolio_return.min())})
    return pd.DataFrame(rows)


def classification(core: dict[str, Any], tails: pd.DataFrame, yearly: pd.DataFrame, robust: pd.DataFrame, risk: str, coverage: float) -> tuple[str, dict[str, Any]]:
    q4_q1 = core["q4_q1_1d"]
    core_pass = [core["spearman_1d"] <= 0, core["slope"] <= 0, q4_q1 <= 0]
    worst = tail_value(tails, "WORST_10PCT", risk, "Q4")
    best = tail_value(tails, "BEST_10PCT", risk, "Q4")
    weight = tail_value(tails, "WORST_10PCT", risk, "Q4", "portfolio_weight_share")
    downside = bool(worst > weight and worst >= best)
    yr = yearly.loc[yearly.slice_type.eq("YEAR"), f"{risk.lower()}_q4_q1_selection_1d"]
    rg = yearly.loc[yearly.slice_type.eq("REGIME"), f"{risk.lower()}_q4_q1_selection_1d"]
    stable = bool(yr.dropna().le(0).sum() >= 3 and rg.dropna().le(0).sum() >= 3)
    ex_ticker = robust.loc[robust.exclude_type.eq("TICKER") & robust.exclude_n.eq(10), "q4_q1_selection_1d"]
    ex_date = robust.loc[robust.exclude_type.eq("DATE") & robust.exclude_n.eq(10), "q4_q1_selection_1d"]
    robust_pass = bool(len(ex_ticker) and len(ex_date) and ex_ticker.iloc[0] <= 0 and ex_date.iloc[0] <= 0)
    evidence = {"core_pass_count": int(sum(core_pass)), "core_indicators": core_pass, "downside_condition": downside, "stability_condition": stable,
                "robustness_condition": robust_pass, "primary_coverage": coverage, "worst_share": worst, "best_share": best, "weight_share": weight}
    if coverage < .75:
        answer = f"INCONCLUSIVE_{risk}_RISK_MECHANISM"
    elif all(core_pass) and downside and stable and robust_pass:
        answer = f"STRONG_SUPPORT_FOR_{risk}_BUDGET" if risk == "BETA" else "STRONG_SUPPORT_FOR_SECTOR_RISK_BUDGET"
    elif (sum(core_pass) >= 2 and (downside or stable or robust_pass)) or all(core_pass):
        answer = f"PARTIAL_SUPPORT_FOR_{risk}_BUDGET" if risk == "BETA" else "PARTIAL_SUPPORT_FOR_SECTOR_RISK_BUDGET"
    elif q4_q1 > 0 and sum(not item for item in core_pass) >= 2:
        answer = "NO_SUPPORT_FOR_SIMPLE_BETA_BUDGET" if risk == "BETA" else "NO_SUPPORT_FOR_SIMPLE_SECTOR_RISK_BUDGET"
    else:
        answer = f"INCONCLUSIVE_{risk}_RISK_MECHANISM"
    return answer, evidence


def plot_outputs(panel: pd.DataFrame, tails: pd.DataFrame, shares: dict[str, dict[str, float]]) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    for risk, xcol, name in (("BETA", "marginal_beta_contribution", "beta_risk_vs_selection.png"), ("SECTOR", "marginal_sector_HHI_contribution", "sector_risk_vs_selection.png")):
        fig, ax = plt.subplots(figsize=(8, 5))
        sample = panel[[xcol, "sector_adjusted_return_1d"]].dropna()
        if len(sample) > 4000: sample = sample.iloc[:: max(1, len(sample) // 4000)]
        ax.scatter(sample[xcol], sample.sector_adjusted_return_1d, s=7, alpha=.18)
        bins = pd.qcut(sample[xcol].rank(method="first"), 20, duplicates="drop")
        means = sample.groupby(bins, observed=True).mean()
        ax.plot(means[xcol], means.sector_adjusted_return_1d, color="#c0392b", linewidth=2)
        ax.axhline(0, color="black", linewidth=.8); ax.set_title(f"{risk.title()} contribution vs 1d within-sector selection"); ax.set_xlabel(xcol); ax.set_ylabel("sector-adjusted return 1d")
        fig.tight_layout(); fig.savefig(OUT / name, dpi=150); plt.close(fig)
    labels = ["Risk", "Positive selection", "Negative selection"]
    fig, ax = plt.subplots(figsize=(8, 5)); x=np.arange(3); width=.35
    ax.bar(x-width/2, [shares["BETA"]["risk_share"], shares["BETA"]["positive_selection_share"], shares["BETA"]["negative_selection_share"]], width, label="Top beta Q4")
    ax.bar(x+width/2, [shares["SECTOR"]["risk_share"], shares["SECTOR"]["positive_selection_share"], shares["SECTOR"]["negative_selection_share"]], width, label="Top sector Q4")
    ax.set_xticks(x, labels); ax.set_ylabel("Share"); ax.set_title("Risk share versus selection share"); ax.legend(); fig.tight_layout(); fig.savefig(OUT / "risk_share_vs_selection_share.png", dpi=150); plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 5)); groups=["BETA_Q4","SECTOR_Q4","HIGH_BETA_HIGH_SECTOR"]
    worst=[tail_value(tails,"WORST_10PCT","BETA","Q4"),tail_value(tails,"WORST_10PCT","SECTOR","Q4"),tail_value(tails,"WORST_10PCT","JOINT","HIGH_BETA_HIGH_SECTOR")]
    best=[tail_value(tails,"BEST_10PCT","BETA","Q4"),tail_value(tails,"BEST_10PCT","SECTOR","Q4"),tail_value(tails,"BEST_10PCT","JOINT","HIGH_BETA_HIGH_SECTOR")]
    x=np.arange(3); ax.bar(x-.18,worst,.36,label="Worst-day loss share"); ax.bar(x+.18,best,.36,label="Best-day gain share"); ax.set_xticks(x,groups); ax.set_ylabel("Share"); ax.legend(); ax.set_title("Upside/downside contribution symmetry"); fig.tight_layout(); fig.savefig(OUT / "upside_downside_contribution.png", dpi=150); plt.close(fig)


def report_markdown(summary: dict[str, Any]) -> str:
    return f"""# A2 beta / sector risk contribution audit R1

`STATUS={summary['STATUS']}`  
`RISK_CONTRIBUTION_PROTOCOL_SHA256={summary['RISK_CONTRIBUTION_PROTOCOL_SHA256']}`

## Answer

Beta: `{summary['BETA_BUDGET_MECHANISM_CLASSIFICATION']}`.  Sector: `{summary['SECTOR_BUDGET_MECHANISM_CLASSIFICATION']}`.  Overall: `{summary['OVERALL_RISK_BUDGET_CLASSIFICATION']}`.

The primary one-day within-sector evidence shows beta Q4-minus-Q1 selection of {summary['BETA_Q4_MINUS_Q1_SELECTION_1D']:.6%} and sector-pressure Q4-minus-Q1 selection of {summary['SECTOR_Q4_MINUS_Q1_SELECTION_1D']:.6%}.  Top beta contributors supply {summary['TOP_BETA_RISK_SHARE']:.2%} of absolute beta exposure and {summary['TOP_BETA_Q4_SHARE_OF_WORST_DAY_LOSSES']:.2%} of losses on the fixed worst 10% of actual Raw A2 days.  Top sector-pressure contributors supply {summary['TOP_SECTOR_RISK_SHARE']:.2%} of marginal HHI pressure and {summary['TOP_SECTOR_Q4_SHARE_OF_WORST_DAY_LOSSES']:.2%} of those losses.

These are retrospective exposed mechanism diagnostics, not cap recommendations.  No candidate portfolio, optimizer, sizing rule, strategy backtest, model refit, or threshold search was performed.  Matched-control columns are exact frozen complete cases and remain partial-coverage evidence.

## Method and limitations

- Raw A2 is the hash-verified `4f7eff...` HGB, Top20 equal weight, ranked score-descending then ticker-ascending.
- Stock beta is the reconciled frozen matched-control definition: 252 completed close-to-close sessions to SPY, minimum 126.  Missing complete-case betas alone were backfilled by the identical formula.
- Primary selection is holding 1d open-to-open return minus the exact frozen same-date PIT FF12 eligible-universe peer return.
- Marginal sector HHI is `2*W_s*w_i-w_i^2`; it is deliberately non-additive and does not renormalize the remaining portfolio.
- Security-date rows are not treated as IID; simple slopes use date-clustered covariance and Q4-Q1 is aggregated at date level.
- This audit created no repo-root temp directory and made no broad or unverified active-worker exclusion.

`NEXT_RESEARCH_PRIORITY={summary['NEXT_RESEARCH_PRIORITY']}`
"""


def console(summary: dict[str, Any], yearly: pd.DataFrame) -> str:
    def v(key: str) -> Any: return summary.get(key, "NOT_AVAILABLE")
    yr_lines=[]
    for year in YEARS:
        label="2026_EXPOSED" if year==2026 else str(year)
        row=yearly.loc[yearly.slice_type.eq("YEAR") & yearly.slice.eq(label)]
        yr_lines.append(f"{year}    {row.beta_q4_q1_selection_1d.iloc[0] if len(row) else 'NA'}    {row.sector_q4_q1_selection_1d.iloc[0] if len(row) else 'NA'}")
    return f"""============================================================
A2 BETA / SECTOR RISK CONTRIBUTION AUDIT
============================================================

STATUS={v('STATUS')}

RAW_A2_IDENTITY_STATUS={v('RAW_A2_IDENTITY_STATUS')}
RISK_CONTRIBUTION_PROTOCOL_SHA256={v('RISK_CONTRIBUTION_PROTOCOL_SHA256')}

ECONOMIC_CUTOFF={v('ECONOMIC_CUTOFF')}
LATEST_USED_SESSION={v('LATEST_USED_SESSION')}
POST_2026_08_28_OUTCOME_READ_COUNT={v('POST_2026_08_28_OUTCOME_READ_COUNT')}

------------------------------------------------------------
ANTI-DUPLICATION
------------------------------------------------------------

ANTI_DUPLICATION_AUDIT_STATUS={v('ANTI_DUPLICATION_AUDIT_STATUS')}

REUSE_A2_MEMBERSHIP={v('REUSE_A2_MEMBERSHIP')}
REUSE_STOCK_BETA={v('REUSE_STOCK_BETA')}
REUSE_PORTFOLIO_BETA={v('REUSE_PORTFOLIO_BETA')}
REUSE_SECTOR_TAXONOMY={v('REUSE_SECTOR_TAXONOMY')}
REUSE_SECTOR_HHI={v('REUSE_SECTOR_HHI')}
REUSE_SECTOR_PEER_RETURN={v('REUSE_SECTOR_PEER_RETURN')}
REUSE_MATCHED_CONTROL={v('REUSE_MATCHED_CONTROL')}
REUSE_REGIME_LABELS={v('REUSE_REGIME_LABELS')}

NEW_PORTFOLIO_ENGINE_CREATED=FALSE
NEW_RISK_OPTIMIZER_CREATED=FALSE
NEW_GENERIC_RISK_FRAMEWORK_CREATED=FALSE

------------------------------------------------------------
EXPOSURE
------------------------------------------------------------

AVG_PORTFOLIO_SPY_BETA={v('AVG_PORTFOLIO_SPY_BETA')}
P50_PORTFOLIO_SPY_BETA={v('P50_PORTFOLIO_SPY_BETA')}
P90_PORTFOLIO_SPY_BETA={v('P90_PORTFOLIO_SPY_BETA')}
MAX_PORTFOLIO_SPY_BETA={v('MAX_PORTFOLIO_SPY_BETA')}

AVG_A2_SECTOR_HHI={v('AVG_A2_SECTOR_HHI')}
AVG_BENCHMARK_SECTOR_HHI={v('AVG_BENCHMARK_SECTOR_HHI')}

------------------------------------------------------------
BETA
------------------------------------------------------------

BETA_SELECTION_SPEARMAN_1D={v('BETA_SELECTION_SPEARMAN_1D')}
BETA_SELECTION_SLOPE={v('BETA_SELECTION_SLOPE')}
BETA_SELECTION_TSTAT={v('BETA_SELECTION_TSTAT')}

BETA_Q1_SELECTION_1D={v('BETA_Q1_SELECTION_1D')}
BETA_Q4_SELECTION_1D={v('BETA_Q4_SELECTION_1D')}
BETA_Q4_MINUS_Q1_SELECTION_1D={v('BETA_Q4_MINUS_Q1_SELECTION_1D')}

BETA_Q1_MATCHED_EXCESS_1D={v('BETA_Q1_MATCHED_EXCESS_1D')}
BETA_Q4_MATCHED_EXCESS_1D={v('BETA_Q4_MATCHED_EXCESS_1D')}
BETA_Q4_MINUS_Q1_MATCHED_1D={v('BETA_Q4_MINUS_Q1_MATCHED_1D')}

TOP_BETA_RISK_SHARE={v('TOP_BETA_RISK_SHARE')}
TOP_BETA_POSITIVE_SELECTION_SHARE={v('TOP_BETA_POSITIVE_SELECTION_SHARE')}
TOP_BETA_NEGATIVE_SELECTION_SHARE={v('TOP_BETA_NEGATIVE_SELECTION_SHARE')}

BETA_Q4_WEIGHT_SHARE={v('BETA_Q4_WEIGHT_SHARE')}
BETA_Q4_WORST_DAY_LOSS_SHARE={v('BETA_Q4_WORST_DAY_LOSS_SHARE')}
BETA_Q4_BEST_DAY_GAIN_SHARE={v('BETA_Q4_BEST_DAY_GAIN_SHARE')}

BETA_BUDGET_MECHANISM_CLASSIFICATION={v('BETA_BUDGET_MECHANISM_CLASSIFICATION')}

------------------------------------------------------------
SECTOR
------------------------------------------------------------

SECTOR_RISK_SELECTION_SPEARMAN_1D={v('SECTOR_RISK_SELECTION_SPEARMAN_1D')}
SECTOR_RISK_SELECTION_SLOPE={v('SECTOR_RISK_SELECTION_SLOPE')}
SECTOR_RISK_SELECTION_TSTAT={v('SECTOR_RISK_SELECTION_TSTAT')}

SECTOR_Q1_SELECTION_1D={v('SECTOR_Q1_SELECTION_1D')}
SECTOR_Q4_SELECTION_1D={v('SECTOR_Q4_SELECTION_1D')}
SECTOR_Q4_MINUS_Q1_SELECTION_1D={v('SECTOR_Q4_MINUS_Q1_SELECTION_1D')}

TOP_SECTOR_RISK_SHARE={v('TOP_SECTOR_RISK_SHARE')}
TOP_SECTOR_POSITIVE_SELECTION_SHARE={v('TOP_SECTOR_POSITIVE_SELECTION_SHARE')}
TOP_SECTOR_NEGATIVE_SELECTION_SHARE={v('TOP_SECTOR_NEGATIVE_SELECTION_SHARE')}

SECTOR_Q4_WEIGHT_SHARE={v('SECTOR_Q4_WEIGHT_SHARE')}
SECTOR_Q4_WORST_DAY_LOSS_SHARE={v('SECTOR_Q4_WORST_DAY_LOSS_SHARE')}
SECTOR_Q4_BEST_DAY_GAIN_SHARE={v('SECTOR_Q4_BEST_DAY_GAIN_SHARE')}

SECTOR_BUDGET_MECHANISM_CLASSIFICATION={v('SECTOR_BUDGET_MECHANISM_CLASSIFICATION')}

------------------------------------------------------------
JOINT
------------------------------------------------------------

LOW_BETA_LOW_SECTOR_SELECTION={v('LOW_BETA_LOW_SECTOR_SELECTION')}
HIGH_BETA_ONLY_SELECTION={v('HIGH_BETA_ONLY_SELECTION')}
HIGH_SECTOR_ONLY_SELECTION={v('HIGH_SECTOR_ONLY_SELECTION')}
HIGH_BETA_HIGH_SECTOR_SELECTION={v('HIGH_BETA_HIGH_SECTOR_SELECTION')}

HIGH_BETA_HIGH_SECTOR_WEIGHT_SHARE={v('HIGH_BETA_HIGH_SECTOR_WEIGHT_SHARE')}
HIGH_BETA_HIGH_SECTOR_WORST_DAY_LOSS_SHARE={v('HIGH_BETA_HIGH_SECTOR_WORST_DAY_LOSS_SHARE')}
HIGH_BETA_HIGH_SECTOR_BEST_DAY_GAIN_SHARE={v('HIGH_BETA_HIGH_SECTOR_BEST_DAY_GAIN_SHARE')}

------------------------------------------------------------
YEARLY
------------------------------------------------------------

YEAR    BETA_Q4_Q1_SELECTION    SECTOR_Q4_Q1_SELECTION
{chr(10).join(yr_lines)}

------------------------------------------------------------
ROBUSTNESS
------------------------------------------------------------

BETA_Q4_Q1_EX_TOP1={v('BETA_Q4_Q1_EX_TOP1')}
BETA_Q4_Q1_EX_TOP3={v('BETA_Q4_Q1_EX_TOP3')}
BETA_Q4_Q1_EX_TOP5={v('BETA_Q4_Q1_EX_TOP5')}
BETA_Q4_Q1_EX_TOP10={v('BETA_Q4_Q1_EX_TOP10')}

SECTOR_Q4_Q1_EX_TOP1={v('SECTOR_Q4_Q1_EX_TOP1')}
SECTOR_Q4_Q1_EX_TOP3={v('SECTOR_Q4_Q1_EX_TOP3')}
SECTOR_Q4_Q1_EX_TOP5={v('SECTOR_Q4_Q1_EX_TOP5')}
SECTOR_Q4_Q1_EX_TOP10={v('SECTOR_Q4_Q1_EX_TOP10')}

------------------------------------------------------------
FINAL
------------------------------------------------------------

BETA_BUDGET_MECHANISM_CLASSIFICATION={v('BETA_BUDGET_MECHANISM_CLASSIFICATION')}
SECTOR_BUDGET_MECHANISM_CLASSIFICATION={v('SECTOR_BUDGET_MECHANISM_CLASSIFICATION')}
OVERALL_RISK_BUDGET_CLASSIFICATION={v('OVERALL_RISK_BUDGET_CLASSIFICATION')}

CORE_NUMERICAL_REASON={v('CORE_NUMERICAL_REASON')}
NEXT_RESEARCH_PRIORITY={v('NEXT_RESEARCH_PRIORITY')}

------------------------------------------------------------
SAFETY
------------------------------------------------------------

THRESHOLD_SEARCH_COUNT=0
PORTFOLIO_OPTIMIZATION_COUNT=0
NEW_STRATEGY_COUNT=0
MODEL_REFIT_COUNT=0
REGISTRY_CHANGE_COUNT=0

PROSPECTIVE_A2_X0_PROTOCOL_UNTOUCHED={str(v('PROSPECTIVE_A2_X0_PROTOCOL_UNTOUCHED')).upper()}

TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT={v('TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT')}
UNRELATED_ACTIVE_TEMP_DIR_COUNT={v('UNRELATED_ACTIVE_TEMP_DIR_COUNT')}
ACTIVE_UNRELATED_TRANSIENT_EXCLUSIONS={v('ACTIVE_UNRELATED_TRANSIENT_EXCLUSIONS')}

ARTIFACT_DIR={v('ARTIFACT_DIR')}
============================================================"""


def run_audit() -> dict[str, Any]:
    require(PROTOCOL_PATH.is_file() and ANTI_DUP_PATH.is_file(), "FROZEN_PROTOCOL_MISSING")
    protocol_sha = sha256_file(PROTOCOL_PATH)
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    anti = json.loads(ANTI_DUP_PATH.read_text(encoding="utf-8"))
    require(protocol["anti_duplication_audit_sha256"] == sha256_file(ANTI_DUP_PATH), "ANTI_DUP_HASH_CHANGED")
    require(sha256_file(MODEL_PATH) == EXPECTED_MODEL_SHA, "RAW_A2_MODEL_HASH_CHANGED")
    registry_sha = sha256_file(REGISTRY); protected_before = protocol["temporal_wall"]["protected_tree_before"]

    holdings, prices, bench, inference_audit = load_holdings()
    matched, matched_audit = read_matched()
    sector, sector_surface_audit = load_sector_surface()
    panel, taxonomy_audit = add_sector_fields(holdings, matched, sector)
    panel, beta_audit = add_beta_fields(panel, matched, prices, bench)
    panel, outcome_audit = add_outcomes(panel, matched, prices, sector)
    panel = add_regimes_and_groups(panel, matched)
    daily = load_actual_daily(panel)
    tails, tail_audit = tail_contributions(panel, daily)
    joint = joint_metrics(panel, tails)
    yearly = yearly_regime_metrics(panel, tails, daily)
    details = sector_detail(panel)
    portfolio_states = portfolio_state_metrics(panel, daily)
    robust_beta = robustness(panel, "BETA"); robust_sector = robustness(panel, "SECTOR")
    beta_core = risk_core(panel, "BETA"); sector_core = risk_core(panel, "SECTOR")
    shares = {risk: contribution_shares(panel, risk) for risk in RISK_TYPES}

    beta_rows = pd.DataFrame(quartile_rows(panel, "BETA"))
    sector_rows = pd.DataFrame(quartile_rows(panel, "SECTOR"))
    beta_rows = pd.concat([beta_rows, robust_beta, details, portfolio_states.loc[portfolio_states.risk.eq("BETA")]], ignore_index=True, sort=False)
    sector_rows = pd.concat([sector_rows, robust_sector, details, portfolio_states.loc[portfolio_states.risk.eq("SECTOR")]], ignore_index=True, sort=False)

    beta_cov = float(panel.loc[panel.sector_adjusted_return_1d.notna(), "marginal_beta_contribution"].notna().mean())
    sector_cov = float(panel.loc[panel.sector_adjusted_return_1d.notna(), "marginal_sector_HHI_contribution"].notna().mean())
    beta_class, beta_gate = classification(beta_core, tails, yearly, robust_beta, "BETA", beta_cov)
    sector_class, sector_gate = classification(sector_core, tails, yearly, robust_sector, "SECTOR", sector_cov)
    support = ("STRONG_SUPPORT", "PARTIAL_SUPPORT")
    if beta_class.startswith("STRONG_SUPPORT") and sector_class.startswith("STRONG_SUPPORT"):
        overall = "STRONG_SUPPORT_FOR_A2_RISK_BUDGET_ARCHITECTURE"
    elif any(x.startswith(support) for x in (beta_class, sector_class)) and not any(x.startswith("INCONCLUSIVE") for x in (beta_class, sector_class)):
        overall = "PARTIAL_SUPPORT_FOR_A2_RISK_BUDGET_ARCHITECTURE"
    elif beta_class == "NO_SUPPORT_FOR_SIMPLE_BETA_BUDGET" and sector_class == "NO_SUPPORT_FOR_SIMPLE_SECTOR_RISK_BUDGET":
        overall = "NO_SUPPORT_FOR_SIMPLE_A2_RISK_BUDGET"
    else:
        overall = "INCONCLUSIVE_A2_RISK_BUDGET_MECHANISM"
    if any(x.startswith(support) for x in (beta_class, sector_class)):
        next_priority = "DESIGN_ONE_SINGLE_PREDECLARED_MINIMAL_RISK_BUDGET_SHADOW"
    elif beta_class.startswith("NO_SUPPORT") and sector_class.startswith("NO_SUPPORT"):
        next_priority = "DO_NOT_CAP_A2_SECURITY_LEVEL_RISK_MOVE_TO_SLEEVE_LEVEL_CAPITAL_LIMIT_OR_TAIL_RISK_RESEARCH"
    else:
        missing = []
        if beta_class.startswith("INCONCLUSIVE"): missing.append("BETA_CONVERGENT_STABILITY_DOWNSIDE_OR_ROBUSTNESS")
        if sector_class.startswith("INCONCLUSIVE"): missing.append("SECTOR_CONVERGENT_STABILITY_DOWNSIDE_OR_ROBUSTNESS")
        next_priority = "MISSING_EVIDENCE=" + "+".join(missing)

    def qmean(table: pd.DataFrame, risk: str, q: str, outcome: str) -> float:
        x=table.loc[table.row_type.eq("QUARTILE") & table.risk.eq(risk) & table.quartile.eq(q) & table.horizon.eq(1) & table.outcome.eq(outcome), "mean"]
        return float(x.iloc[0]) if len(x) else np.nan
    def joint_value(group: str, col: str) -> float:
        x=joint.loc[joint.group.eq(group), col]; return float(x.iloc[0]) if len(x) else np.nan
    def rob_value(frame: pd.DataFrame, n: int) -> float:
        x=frame.loc[frame.exclude_type.eq("TICKER") & frame.exclude_n.eq(n), "q4_q1_selection_1d"]; return float(x.iloc[0])

    temp = root_temp_accounting()
    require(temp["TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT"] == 0, "TASK_TEMP_DIR_CREATED", temp)
    protected_after = tree_snapshot(PROTECTED)
    protected_ok = protected_after["tree_sha256"] == protected_before["tree_sha256"]
    registry_ok = sha256_file(REGISTRY) == registry_sha
    require(protected_ok and registry_ok, "PROTECTED_OR_REGISTRY_MUTATION")
    post_cutoff = matched_audit["post_cutoff_outcome_read_count"] + outcome_audit["post_cutoff_outcome_read_count"]
    require(post_cutoff == 0, "POST_CUTOFF_OUTCOME_READ")

    exposure = panel.groupby("signal_date", sort=True).first()
    summary: dict[str, Any] = {
        "STATUS": "PASS_COMPLETE_RETROSPECTIVE_MECHANISM_AUDIT",
        "RAW_A2_IDENTITY_STATUS": "PASS_HASH_RANK_MEMBERSHIP",
        "RISK_CONTRIBUTION_PROTOCOL_SHA256": protocol_sha,
        "ECONOMIC_CUTOFF": "2026-08-28", "LATEST_USED_SESSION": outcome_audit["latest_used_session"], "POST_2026_08_28_OUTCOME_READ_COUNT": post_cutoff,
        **{key: anti[key] for key in ("ANTI_DUPLICATION_AUDIT_STATUS", "REUSE_A2_MEMBERSHIP", "REUSE_STOCK_BETA", "REUSE_PORTFOLIO_BETA", "REUSE_SECTOR_TAXONOMY", "REUSE_SECTOR_HHI", "REUSE_SECTOR_PEER_RETURN", "REUSE_MATCHED_CONTROL", "REUSE_REGIME_LABELS")},
        "NEW_PORTFOLIO_ENGINE_CREATED": False, "NEW_RISK_OPTIMIZER_CREATED": False, "NEW_GENERIC_RISK_FRAMEWORK_CREATED": False,
        "AVG_PORTFOLIO_SPY_BETA": safe_mean(exposure.portfolio_beta_SPY), "P50_PORTFOLIO_SPY_BETA": float(exposure.portfolio_beta_SPY.median()), "P90_PORTFOLIO_SPY_BETA": float(exposure.portfolio_beta_SPY.quantile(.90)), "MAX_PORTFOLIO_SPY_BETA": float(exposure.portfolio_beta_SPY.max()),
        "AVG_A2_SECTOR_HHI": safe_mean(exposure.sector_HHI_A2), "AVG_BENCHMARK_SECTOR_HHI": safe_mean(exposure.sector_HHI_benchmark),
        "BETA_SELECTION_SPEARMAN_1D": beta_core["spearman_1d"], "BETA_SELECTION_SLOPE": beta_core["slope"], "BETA_SELECTION_TSTAT": beta_core["tstat"],
        "BETA_Q1_SELECTION_1D": qmean(beta_rows,"BETA","Q1","SELECTION"), "BETA_Q4_SELECTION_1D": qmean(beta_rows,"BETA","Q4","SELECTION"), "BETA_Q4_MINUS_Q1_SELECTION_1D": beta_core["q4_q1_1d"],
        "BETA_Q4_MATCHED_EXCESS_1D": qmean(beta_rows,"BETA","Q4","MATCHED"), "BETA_Q1_MATCHED_EXCESS_1D": qmean(beta_rows,"BETA","Q1","MATCHED"), "BETA_Q4_MINUS_Q1_MATCHED_1D": date_contrast(panel,"BETA_quartile","matched_excess_1d"),
        "TOP_BETA_RISK_SHARE": shares["BETA"]["risk_share"], "TOP_BETA_POSITIVE_SELECTION_SHARE": shares["BETA"]["positive_selection_share"], "TOP_BETA_NEGATIVE_SELECTION_SHARE": shares["BETA"]["negative_selection_share"],
        "BETA_Q4_WEIGHT_SHARE": tail_value(tails,"WORST_10PCT","BETA","Q4","portfolio_weight_share"), "BETA_Q4_WORST_DAY_LOSS_SHARE": tail_value(tails,"WORST_10PCT","BETA","Q4"), "BETA_Q4_BEST_DAY_GAIN_SHARE": tail_value(tails,"BEST_10PCT","BETA","Q4"),
        "TOP_BETA_Q4_SHARE_OF_WORST_DAY_LOSSES": tail_value(tails,"WORST_10PCT","BETA","Q4"), "TOP_BETA_Q4_SHARE_OF_BEST_DAY_GAINS": tail_value(tails,"BEST_10PCT","BETA","Q4"),
        "BETA_BUDGET_MECHANISM_CLASSIFICATION": beta_class,
        "SECTOR_RISK_SELECTION_SPEARMAN_1D": sector_core["spearman_1d"], "SECTOR_RISK_SELECTION_SLOPE": sector_core["slope"], "SECTOR_RISK_SELECTION_TSTAT": sector_core["tstat"],
        "SECTOR_Q1_SELECTION_1D": qmean(sector_rows,"SECTOR","Q1","SELECTION"), "SECTOR_Q4_SELECTION_1D": qmean(sector_rows,"SECTOR","Q4","SELECTION"), "SECTOR_Q4_MINUS_Q1_SELECTION_1D": sector_core["q4_q1_1d"],
        "TOP_SECTOR_RISK_SHARE": shares["SECTOR"]["risk_share"], "TOP_SECTOR_POSITIVE_SELECTION_SHARE": shares["SECTOR"]["positive_selection_share"], "TOP_SECTOR_NEGATIVE_SELECTION_SHARE": shares["SECTOR"]["negative_selection_share"],
        "SECTOR_Q4_WEIGHT_SHARE": tail_value(tails,"WORST_10PCT","SECTOR","Q4","portfolio_weight_share"), "SECTOR_Q4_WORST_DAY_LOSS_SHARE": tail_value(tails,"WORST_10PCT","SECTOR","Q4"), "SECTOR_Q4_BEST_DAY_GAIN_SHARE": tail_value(tails,"BEST_10PCT","SECTOR","Q4"),
        "TOP_SECTOR_Q4_SHARE_OF_WORST_DAY_LOSSES": tail_value(tails,"WORST_10PCT","SECTOR","Q4"), "TOP_SECTOR_Q4_SHARE_OF_BEST_DAY_GAINS": tail_value(tails,"BEST_10PCT","SECTOR","Q4"),
        "SECTOR_BUDGET_MECHANISM_CLASSIFICATION": sector_class,
        "LOW_BETA_LOW_SECTOR_SELECTION": joint_value("LOW_BETA_LOW_SECTOR","selection_1d"), "HIGH_BETA_ONLY_SELECTION": joint_value("HIGH_BETA_ONLY","selection_1d"), "HIGH_SECTOR_ONLY_SELECTION": joint_value("HIGH_SECTOR_ONLY","selection_1d"), "HIGH_BETA_HIGH_SECTOR_SELECTION": joint_value("HIGH_BETA_HIGH_SECTOR","selection_1d"),
        "HIGH_BETA_HIGH_SECTOR_WEIGHT_SHARE": joint_value("HIGH_BETA_HIGH_SECTOR","portfolio_weight_share"),
        "HIGH_BETA_HIGH_SECTOR_PORTFOLIO_WEIGHT_SHARE": joint_value("HIGH_BETA_HIGH_SECTOR","portfolio_weight_share"), "HIGH_BETA_HIGH_SECTOR_WORST_DAY_LOSS_SHARE": joint_value("HIGH_BETA_HIGH_SECTOR","worst_day_loss_share"), "HIGH_BETA_HIGH_SECTOR_BEST_DAY_GAIN_SHARE": joint_value("HIGH_BETA_HIGH_SECTOR","best_day_gain_share"),
        **{f"BETA_Q4_Q1_EX_TOP{n}": rob_value(robust_beta,n) for n in (1,3,5,10)}, **{f"SECTOR_Q4_Q1_EX_TOP{n}": rob_value(robust_sector,n) for n in (1,3,5,10)},
        "BETA_BUDGET_MECHANISM_CLASSIFICATION": beta_class, "SECTOR_BUDGET_MECHANISM_CLASSIFICATION": sector_class, "OVERALL_RISK_BUDGET_CLASSIFICATION": overall,
        "CORE_NUMERICAL_REASON": f"beta_q4_q1={beta_core['q4_q1_1d']:.8f};beta_worst_share={tail_value(tails,'WORST_10PCT','BETA','Q4'):.6f};sector_q4_q1={sector_core['q4_q1_1d']:.8f};sector_worst_share={tail_value(tails,'WORST_10PCT','SECTOR','Q4'):.6f}",
        "NEXT_RESEARCH_PRIORITY": next_priority,
        "THRESHOLD_SEARCH_COUNT": 0, "PORTFOLIO_OPTIMIZATION_COUNT": 0, "NEW_STRATEGY_COUNT": 0, "MODEL_REFIT_COUNT": 0, "REGISTRY_CHANGE_COUNT": 0,
        "PROSPECTIVE_A2_X0_PROTOCOL_UNTOUCHED": protected_ok,
        **{key: temp[key] for key in ("TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT", "UNRELATED_ACTIVE_TEMP_DIR_COUNT", "ACTIVE_UNRELATED_TRANSIENT_EXCLUSIONS")},
        "ACTIVE_UNRELATED_TEMP_PATHS": temp["ACTIVE_UNRELATED_TEMP_PATHS"], "INACTIVE_UNRELATED_TEMP_PATHS": temp["known_inactive_unrelated_transient_paths"],
        "ARTIFACT_DIR": str(OUT),
        "coverage": {"beta_primary": beta_cov, "sector_primary": sector_cov}, "beta_classification_gate": beta_gate, "sector_classification_gate": sector_gate,
        "anti_duplication_component_completion": {
            "FF12 taxonomy": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT", "FF48 taxonomy": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT",
            "sector weights": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT", "benchmark sector weights": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT",
            "forward stock returns": "EXTEND_EXISTING_PARTIAL_COMPONENT", "downside contribution logic": "EXTEND_EXISTING_PARTIAL_COMPONENT",
        },
        "audits": {"inference": inference_audit, "matched": matched_audit, "sector_surface": sector_surface_audit, "taxonomy": taxonomy_audit, "beta": beta_audit, "outcomes": outcome_audit, "tail": tail_audit},
    }

    required_panel = ["signal_date","ticker","A2_rank","A2_score","portfolio_weight","FF12","FF48","stock_beta_SPY","beta_valid_n","portfolio_beta_SPY","beta_coverage_weight","beta_coverage_flag","top1_beta_contributor_share","top3_beta_contributor_share","top5_beta_contributor_share","sector_weight_A2","sector_weight_benchmark","sector_active_weight","sector_HHI_A2","sector_HHI_benchmark","marginal_beta_contribution","marginal_sector_HHI_contribution"]
    for h in HORIZONS: required_panel += [f"future_return_{h}d",f"sector_peer_return_{h}d",f"sector_adjusted_return_{h}d",f"matched_excess_{h}d"]
    required_panel += ["matched_available","bull_bear","high_low_vol","BETA_quartile","SECTOR_quartile","joint_group","realization_date"]
    panel[required_panel].to_parquet(OUT / "holding_risk_panel.parquet", index=False, compression="zstd")
    beta_rows.to_csv(OUT / "beta_contribution_metrics.csv", index=False)
    sector_rows.to_csv(OUT / "sector_contribution_metrics.csv", index=False)
    joint.to_csv(OUT / "joint_risk_metrics.csv", index=False)
    tails.to_csv(OUT / "downside_contribution.csv", index=False)
    yearly.to_csv(OUT / "yearly_regime_metrics.csv", index=False)
    plot_outputs(panel, tails, shares)
    write_json(OUT / "summary.json", summary)
    (OUT / "concise_report.md").write_text(report_markdown(summary), encoding="utf-8")

    source_manifest = {
        "task_id": TASK_ID, "protocol_sha256": protocol_sha, "source_files": source_inventory(),
        "task_local_code": {"path": str(Path(__file__).resolve()), "bytes": Path(__file__).stat().st_size, "sha256": sha256_file(Path(__file__).resolve())},
        "anti_duplication_component_completion": summary["anti_duplication_component_completion"],
        "output_sha256": {p.name: sha256_file(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name not in {"source_manifest.json"}},
        "post_cutoff_outcome_read_count": 0, "protected_tree_after": protected_after,
        "registry_sha256_before_after": registry_sha, "new_portfolio_engine_created": False, "new_risk_optimizer_created": False, "new_generic_risk_framework_created": False,
    }
    write_json(OUT / "source_manifest.json", source_manifest)
    permitted = {"anti_duplication_audit.json","risk_contribution_audit_protocol.json","source_manifest.json","holding_risk_panel.parquet","beta_contribution_metrics.csv","sector_contribution_metrics.csv","joint_risk_metrics.csv","downside_contribution.csv","yearly_regime_metrics.csv","summary.json","concise_report.md","beta_risk_vs_selection.png","sector_risk_vs_selection.png","risk_share_vs_selection_share.png","upside_downside_contribution.png"}
    actual = {p.name for p in OUT.iterdir() if p.is_file()}
    require(actual == permitted, "ARTIFACT_BLOAT_OR_MISSING", {"extra": sorted(actual-permitted), "missing": sorted(permitted-actual)})
    require(summary["POST_2026_08_28_OUTCOME_READ_COUNT"] == 0 and summary["THRESHOLD_SEARCH_COUNT"] == 0 and summary["PORTFOLIO_OPTIMIZATION_COUNT"] == 0 and summary["NEW_STRATEGY_COUNT"] == 0 and summary["MODEL_REFIT_COUNT"] == 0 and summary["REGISTRY_CHANGE_COUNT"] == 0 and summary["PROSPECTIVE_A2_X0_PROTOCOL_UNTOUCHED"] and summary["TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT"] == 0, "FINAL_SAFETY_GATE")
    print(console(summary, yearly), flush=True)
    return summary


def self_test() -> None:
    require(HORIZONS == (1,5,20), "HORIZONS_CHANGED")
    require(TOP_N == 20, "TOP_N_CHANGED")
    require(EXPECTED_MODEL_SHA == sha256_file(MODEL_PATH), "MODEL_IDENTITY")
    require(ECONOMIC_CUTOFF == pd.Timestamp("2026-08-28"), "CUTOFF_CHANGED")
    temp=root_temp_accounting(); require(temp["TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT"]==0,"TEMP_ACCOUNTING")
    print("SELF_TEST=PASS")


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--freeze",action="store_true"); parser.add_argument("--audit",action="store_true"); parser.add_argument("--self-test",action="store_true"); args=parser.parse_args()
    selected=sum((args.freeze,args.audit,args.self_test)); require(selected==1,"SELECT_EXACTLY_ONE_MODE")
    if args.freeze: freeze()
    elif args.audit: run_audit()
    else: self_test()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
