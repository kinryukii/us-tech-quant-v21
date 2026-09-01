"""First and only economic evaluation of the frozen Raw-A2 HHI R2 shadow.

The runner is deliberately split into ``--freeze`` and ``--evaluate``.  The
freeze stage hashes identities and writes the complete evaluation manifest
without semantically reading an economic outcome.  The evaluation stage
refuses to run if that byte-level manifest or its source fingerprint changes.

Portfolio accounting is not reimplemented here.  Pre-2026 uses the exact E5
replay/cost/metric implementation already reconciled to authoritative Raw A2;
2026 uses the existing frozen open-ended Raw-A2 replay.  The task-local code is
an adapter, attribution/QA layer, and compact report writer only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


TASK = "A2_HHI_R2_FROZEN_ECONOMIC_EVALUATION_R1"
REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
CACHE = Path(r"D:\us-tech-quant-cache")
OUT = RESULTS / TASK
MANIFEST = OUT / "economic_evaluation_manifest.json"
ANTI_DUP = OUT / "anti_duplication_audit.json"
THIS_SOURCE = REPO / "a2_hhi_r2_frozen_economic_evaluation_r1.py"

R2_ROOT = RESULTS / "A2_SINGLE_SECTOR_RISK_BUDGET_DESIGN_AND_FREEZE_R2"
R2_PROTOCOL = R2_ROOT / "r2_design_protocol.json"
R2_CONTRACT = R2_ROOT / "frozen_contract.json"
R2_STRUCTURAL = R2_ROOT / "structural_dry_run.csv"
R2_LEDGER = R2_ROOT / "intervention_ledger.parquet"
CLOSURE_ROOT = RESULTS / "A2_HHI_R2_STRUCTURAL_ACCOUNTING_CLOSURE_AUDIT_R1"
CLOSURE_SUMMARY = CLOSURE_ROOT / "summary.json"
CLOSURE_HHI = CLOSURE_ROOT / "hhi_reconciliation.csv"

BASE = RESULTS / "A_VS_A2_QUARTERLY_13F_R1"
A2_ROOT = BASE / "A2"
MODEL = A2_ROOT / "final_full_pre2026_hgb.joblib"
OOF = A2_ROOT / "oof_predictions.parquet"
TOP20 = A2_ROOT / "top20_selections.parquet"
PORTFOLIO = A2_ROOT / "portfolio_daily.parquet"
REGISTRY = REPO / "config" / "research_governance" / "alpha_registry.json"

R2_SOURCE = REPO / "a2_single_sector_risk_budget_design_and_freeze_r2.py"
CLOSURE_SOURCE = REPO / "a2_hhi_r2_structural_accounting_closure_audit_r1.py"
R1_SOURCE = REPO / "a2_single_sector_risk_budget_design_and_freeze_r1.py"
PRETOP_SOURCE = REPO / "scripts" / "v22" / "a2_pretop20_candidate_recovery_and_membership_deconcentration_r1.py"
GLOBAL_REPLAY_SOURCE = REPO / "scripts" / "v22" / "a2_global_ff12_hold_replace_r1.py"
E5_SOURCE = RESULTS / "A2_EXECUTION_EFFICIENCY_R2_PREREGISTERED_HYSTERESIS" / "run_a2_execution_efficiency_r2.py"
OLD_2026_SOURCE = REPO / "scripts" / "v22" / "a_a2_2026_pre_risk_holdout_r1.py"
BETA_SECTOR_SOURCE = REPO / "a2_beta_sector_risk_contribution_audit_r1.py"
H2H_PYC = REPO / "__pycache__" / ".codex_tmp_frozen_h2h_run.cpython-312.pyc"

FOUR = RESULTS / "RAW_A2_FOUR_LAYER_ALPHA_IDENTITY_ATTRIBUTION_R1"
FOUR_PROTOCOL = FOUR / "attribution_protocol.json"
SECTOR_ATTRIBUTION = FOUR / "holdings_sector_attribution.csv"
MATCHED = RESULTS / "RAW_A2_FROZEN_MATCHED_CONTROL_COMPLETION_R1" / "matched_pairs.parquet"
TAXONOMY = RESULTS / "A2_SEC_CIK_IDENTITY_GAP_CLOSE_AND_DECONCENTRATION_AUTORUN_R1" / "pit_ff12_ff48_taxonomy.parquet"
H2H_ROOT = RESULTS / "LATEST_2026_FROZEN_STRATEGY_HEAD_TO_HEAD_R1"
H2H_DAILY = H2H_ROOT / "daily_returns.csv"
H2H_SUMMARY = H2H_ROOT / "summary.json"
RISK_PANEL = RESULTS / "A2_BETA_SECTOR_RISK_CONTRIBUTION_AUDIT_R1" / "holding_risk_panel.parquet"
RISK_PROTOCOL = RESULTS / "A2_BETA_SECTOR_RISK_CONTRIBUTION_AUDIT_R1" / "risk_contribution_audit_protocol.json"
RISK_ANTI_DUP = RESULTS / "A2_BETA_SECTOR_RISK_CONTRIBUTION_AUDIT_R1" / "anti_duplication_audit.json"
PROSPECTIVE = RESULTS / "A2_X0_LITERATURE_GROUNDED_PROSPECTIVE_DISAGREEMENT_R1"

POST_TOP20 = CACHE / "A2_BETA_SECTOR_RISK_CONTRIBUTION_AUDIT_R1" / "raw_a2_2026_top20.parquet"
POST_PRICES = CACHE / "A2_BETA_SECTOR_RISK_CONTRIBUTION_AUDIT_R1" / "reused_prices.parquet"
POST_BENCH = CACHE / "A2_BETA_SECTOR_RISK_CONTRIBUTION_AUDIT_R1" / "reused_benchmarks.parquet"

EXPECTED = {
    MODEL: "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b",
    R2_PROTOCOL: "4a0c9af86527366744f3baa70e765a46608a39d9ee8de8479ced5231768f7ad6",
    R2_CONTRACT: "4c34c19d840980c390de134438dfb984dbe0981df06d2aac24d8ad441c6d33f9",
    CLOSURE_SUMMARY: "dac500f54357fbf438b70a0a7c47a3351abe2ff161f17b2e944cbca505166b25",
    OOF: "e336be6c267167356ce3d39fa629f80fe7b2968711112a9c976fdb002c693468",
    TOP20: "5e5203fdcd9a1e53fe1e2d64cd8c1adb78df4bd7acc733394d4dbd62392b8b20",
    PORTFOLIO: "4e55f1a76952b864349dc058f1f42809f0792afd7060623c44c33c1a1cd45d73",
    TAXONOMY: "515427bfe4d450540bcf8b04a9ce5fd50f706c551300a46450f5e4669b7d552f",
    SECTOR_ATTRIBUTION: "902dfd663f71849d2787086abdad71dda5a2aaf43cd42e90c83de2bef2f48871",
    H2H_DAILY: "88cc41428e46344ee28d9dcf6f2ad61de9992f75c1a2d9da968f0069f792d88b",
    H2H_PYC: "5e48c36e88ceb9e6e2b6a63b2ce6579f6be6a8f92e41289bed96a1823d9ae92f",
    RISK_PROTOCOL: "8384f59418142bfbb90d681231fc5bac78c48ad48f18f4ed29c65eca68363504",
}

ECONOMIC_CUTOFF = pd.Timestamp("2026-08-28")
LATEST_COMPLETE = pd.Timestamp("2026-08-27")
LATEST_SIGNAL = pd.Timestamp("2026-08-26")
TOP_N = 20
WEIGHT = 0.05
TOL = 1e-10
EVIDENCE_LABEL = "RETROSPECTIVE_EXPOSED_SHADOW_DIAGNOSTIC"


class EvaluationFailure(RuntimeError):
    pass


def require(condition: bool, code: str, detail: Any = "") -> None:
    if not condition:
        raise EvaluationFailure(f"{code}:{detail}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=True)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, pd.DataFrame):
        return json_safe(value.to_dict("records"))
    if isinstance(value, pd.Series):
        return json_safe(value.to_dict())
    if isinstance(value, (pd.Timestamp,)):
        return value.date().isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(json_safe(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ols_hac(y: np.ndarray, x: np.ndarray, maxlags: int = 5) -> dict[str, Any]:
    """Fixed OLS with Bartlett/Newey-West covariance; no external engine."""
    yv = np.asarray(y, dtype=float)
    xv = np.asarray(x, dtype=float)
    require(xv.ndim == 2 and len(yv) == len(xv) and len(yv) > xv.shape[1], "OLS_INPUT")
    bread = np.linalg.pinv(xv.T @ xv)
    params = bread @ xv.T @ yv
    residual = yv - xv @ params
    scores = xv * residual[:, None]
    meat = scores.T @ scores
    for lag in range(1, min(maxlags, len(yv) - 1) + 1):
        weight = 1.0 - lag / (maxlags + 1.0)
        gamma = scores[lag:].T @ scores[:-lag]
        meat += weight * (gamma + gamma.T)
    covariance = bread @ meat @ bread
    se = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    tvalues = np.divide(params, se, out=np.full_like(params, np.nan), where=se > 0)
    centered = yv - yv.mean()
    denom = float(centered @ centered)
    r_squared = 1.0 - float(residual @ residual) / denom if denom > 0 else np.nan
    return {"params": params, "residual": residual, "tvalues": tvalues, "r_squared": r_squared}


def import_file(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_SPEC", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def tree_snapshot(root: Path) -> dict[str, Any]:
    files = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        files.append([path.relative_to(root).as_posix(), path.stat().st_size, sha256_file(path)])
    return {"file_count": len(files), "tree_sha256": stable_hash(files), "files": files}


def repo_temp_dirs() -> list[str]:
    prefixes = (".tmp", ".codex_tmp", ".pytest_cache", "pytest-cache-")
    return sorted(str(p) for p in REPO.iterdir() if p.is_dir() and p.name.startswith(prefixes))


def verify_frozen_identities() -> dict[str, Any]:
    for path, expected in EXPECTED.items():
        require(path.is_file(), "FROZEN_INPUT_MISSING", path)
        require(sha256_file(path) == expected, "FROZEN_INPUT_HASH", path)
    contract = json.loads(R2_CONTRACT.read_text(encoding="utf-8"))
    require(contract.get("frozen_name") == "A2_HHI_NONINCREASING_ENTRY_GUARD_SHADOW_R2", "R2_NAME")
    require(contract.get("rule_family") == "DIRECT_HHI_NONINCREASING_ENTRY_GUARD_R2", "R2_RULE")
    require(contract.get("parent_a2", {}).get("model_sha256") == EXPECTED[MODEL], "R2_PARENT_MODEL")
    closure = json.loads(CLOSURE_SUMMARY.read_text(encoding="utf-8"))
    require(closure.get("final_classification") == "PASS_STRUCTURAL_ACCOUNTING_CLOSED", "CLOSURE_STATUS")
    event = closure.get("event_closure", {})
    require(event.get("all_alternative_interventions") == 2230, "CLOSURE_ALL_INTERVENTIONS", event)
    require(event.get("optional_interventions") == 2209, "CLOSURE_OPTIONAL_INTERVENTIONS", event)
    require(event.get("forced_interventions") == 21, "CLOSURE_FORCED_INTERVENTIONS", event)
    require(event.get("accounting_unexplained_event_count") == 0, "CLOSURE_UNEXPLAINED", event)
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    rows = [row for row in registry.get("models", []) if row.get("model_id") == "A2_HGB"]
    require(len(rows) == 1 and rows[0].get("model_sha256") == EXPECTED[MODEL], "RAW_A2_REGISTRY")
    return {"contract": contract, "closure": closure, "registry_sha256": sha256_file(REGISTRY)}


def source_rows() -> list[dict[str, Any]]:
    roles = {
        MODEL: "frozen Raw A2 model",
        OOF: "authoritative pre-2026 full ranked surface",
        TOP20: "authoritative pre-2026 Raw A2 membership",
        PORTFOLIO: "authoritative pre-2026 Raw A2 economic path",
        R2_PROTOCOL: "frozen R2 design protocol",
        R2_CONTRACT: "frozen R2 contract",
        R2_LEDGER: "frozen intervention ledger",
        CLOSURE_SUMMARY: "structural accounting closure",
        CLOSURE_HHI: "closed structural membership/HHi ledger",
        TAXONOMY: "frozen PIT FF12/FF48 source",
        SECTOR_ATTRIBUTION: "authoritative sector peer and benchmark surface",
        MATCHED: "frozen matched-control complete cases",
        H2H_DAILY: "authoritative 2026 Raw A2 economic path",
        H2H_SUMMARY: "authoritative 2026 identity",
        H2H_PYC: "frozen 2026 full-rank inference implementation",
        POST_PRICES: "frozen 2026 equity price bundle through 2026-08-27",
        POST_BENCH: "frozen 2026 SPY/QQQ/SOXX bundle through 2026-08-27",
        R2_SOURCE: "frozen R2 transition adapter",
        CLOSURE_SOURCE: "closed transition audit/membership recorder",
        R1_SOURCE: "R1 ordering/taxonomy/turnover implementation reused by R2",
        PRETOP_SOURCE: "authoritative candidate and taxonomy extension",
        GLOBAL_REPLAY_SOURCE: "reconciled pre-2026 replay adapter",
        E5_SOURCE: "reconciled portfolio/cost/metric engine",
        OLD_2026_SOURCE: "frozen open-ended 2026 replay engine",
        BETA_SECTOR_SOURCE: "sector/return/factor-source compatibility methods",
        FOUR_PROTOCOL: "frozen sector and factor methodology",
        RISK_PROTOCOL: "parent sector-risk mechanism protocol",
        RISK_ANTI_DUP: "prior component reuse audit",
        REGISTRY: "canonical registry read-only identity",
        THIS_SOURCE: "task-local orchestration and diagnostic source",
    }
    rows = []
    for path, role in roles.items():
        require(path.is_file(), "SOURCE_MISSING", path)
        rows.append({"path": str(path), "role": role, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return rows


def anti_duplication_payload(sources: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "task_id": TASK,
        "ANTI_DUPLICATION_AUDIT_STATUS": "PASS_REUSE_DISCOVERY_COMPLETED_BEFORE_EVALUATOR_BUILD",
        "search_terms": ["economic_replay", "portfolio_replay", "shadow_evaluation", "strategy_comparison", "head_to_head", "net_return", "turnover", "transaction_cost", "sector_hhi", "max_drawdown", "factor_beta", "portfolio_metrics"],
        "lineages_inspected": [
            "Raw A2 authoritative economic replay", "R1/R2 transition implementation",
            "sector-risk audit replay utilities", "A-vs-A2 economic evaluator",
            "LATEST_2026_FROZEN_STRATEGY_HEAD_TO_HEAD_R1", "buy/sell/sizing and execution replay",
            "sector correction/deconcentration evaluators", "execution cost attribution",
            "four-layer and extended factor attribution", "MaxDD/Sharpe/beta utilities",
        ],
        "REUSE_PORTFOLIO_REPLAY": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT:E5_PRE2026_PLUS_FROZEN_OPEN_ENDED_2026",
        "REUSE_COST_ENGINE": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT:10_BPS_ONE_WAY_E5_AND_FROZEN_2026",
        "REUSE_METRIC_ENGINE": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT:E5_PERFORMANCE_AND_FROZEN_DRAWDOWN",
        "REUSE_FACTOR_EXPOSURE_ENGINE": "EXTEND_EXISTING_PARTIAL_COMPONENT:FROZEN_FOUR_LAYER_SEQUENTIAL_ORTHOGONAL_OLS_METHOD_MINIMAL_ADAPTER",
        "REUSE_SECTOR_ATTRIBUTION_ENGINE": "REUSE_EXISTING_AUTHORITATIVE_COMPONENT:FOUR_LAYER_PIT_FF12_PEER_AND_BENCHMARK",
        "NEW_BACKTESTER_CREATED": False,
        "NEW_COST_ENGINE_CREATED": False,
        "NEW_GENERIC_PORTFOLIO_ENGINE_CREATED": False,
        "minimal_task_local_scope": "orchestration, full-window target binding, fixed attribution, QA, and reporting only",
        "source_inventory": sources,
        "task_owned_repo_root_temp_dir_count_at_freeze": len(repo_temp_dirs()),
        "completed_before_economic_outcome_semantic_read": True,
    }


def manifest_payload(identities: dict[str, Any], anti_sha: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "task_id": TASK,
        "research_role": "FROZEN_SHADOW_ECONOMIC_EVALUATION_FIRST_AND_ONLY",
        "evidence_label": EVIDENCE_LABEL,
        "frozen_before_economic_outcome_reads": True,
        "economic_outcome_read_count_at_freeze": 0,
        "raw_a2": {"alias": "A2_HGB", "model_sha256": EXPECTED[MODEL], "portfolio": "TOP20_EQUAL_WEIGHT_LONG_ONLY", "ranking": "A2_SCORE_DESC_THEN_TICKER_ASC"},
        "r2": {"name": "A2_HHI_NONINCREASING_ENTRY_GUARD_SHADOW_R2", "rule_family": "DIRECT_HHI_NONINCREASING_ENTRY_GUARD_R2", "protocol_sha256": EXPECTED[R2_PROTOCOL], "contract_sha256": EXPECTED[R2_CONTRACT], "contract_immutable": True},
        "structural_closure": {"classification": "PASS_STRUCTURAL_ACCOUNTING_CLOSED", "summary_sha256": EXPECTED[CLOSURE_SUMMARY], "alternative_interventions": 2230, "optional": 2209, "forced": 21, "unexplained": 0},
        "evaluation_windows": {
            "WINDOW_A_AUTHORITATIVE_PRE2026": {"signal_start": "2023-01-03", "signal_end": "2025-12-29", "economic_start": "2023-01-04", "economic_end": "2025-12-31", "evidence": "OOF_RETROSPECTIVE_EXPOSED_RESEARCH_EVIDENCE"},
            "WINDOW_B_EXPOSED_2026": {"signal_start": "2026-01-02", "signal_end": "2026-08-26", "economic_start": "2026-01-05", "economic_end": "2026-08-27", "evidence": "EXPOSED_EVALUATION_ONLY"},
            "WINDOW_C_FULL_COMBINED_DIAGNOSTIC": {"construction": "chronological concatenation of A and B; independent window replay initializations retained", "evidence": EVIDENCE_LABEL},
        },
        "temporal_wall": {"economic_cutoff": "2026-08-28", "latest_allowed_completed_session": "2026-08-27", "maturity": "outcomes included only when realization session <= 2026-08-28", "post_cutoff_reads_forbidden": True},
        "portfolio_replay": {"pre2026": "existing E5.replay reconciled byte-for-byte to authoritative portfolio_daily", "2026": "existing reconstruct_open_ended reconciled to frozen H2H RAW_A2", "execution": "signal close to next session open", "only_membership_differs": True},
        "cost": {"rate": 0.001, "label": "10_BPS_ONE_WAY_TURNOVER", "formula": "0.5 * traded_notional * 0.001", "primary": "NET"},
        "metrics": ["total_net_return", "annualized_return_cagr", "Sharpe", "annualized_volatility", "MaxDD", "Calmar", "Sortino", "turnover", "total_cost", "worst_day", "best_day", "gross_analogs"],
        "concentration": {"taxonomy": "frozen PIT FF12; UNKNOWN explicit", "hhi": "sum_s(W_s^2)", "max_sector_weight": "max_s W_s", "active_overweight": "max_s max(W_s-W_benchmark_s,0)"},
        "factor_exposure": {"returns": "authoritative QFQ open-to-open SPY/QQQ/SOXX on exact economic dates", "order": ["SPY", "QQQ_ORTH_TO_SPY", "SOXX_ORTH_TO_SPY_AND_QQQ_ORTH"], "regression": "OLS intercept plus three orthogonal factors, HAC Newey-West lag 5"},
        "selection": {"stock_return": "next execution open to h-th subsequent execution open; realization must be <= cutoff", "sector_adjusted": "stock return minus compounded same-date PIT FF12 eligible-universe peer return", "matched": "frozen matched-control complete cases only; no new matching", "statuses": ["CANONICAL_RAW_A2", "R2_ONLY", "RAW_A2_ONLY", "COMMON"]},
        "interventions": {"primary_ledger": "frozen 2230 pre-2026 intervention ledger", "optional_and_forced_separate": True, "horizons": [1, 5, 20], "rank_buckets": ["LE40", "41_60", "61_100", "101_200", "GT200"], "inference": "date-level mean alternative-minus-canonical then HAC lag 5"},
        "worst_best_days": "sort full-window Raw A2 net returns with date tie-break; fixed ceil(10%) bottom/top sets; evaluate R2 on identical dates",
        "drawdown": "reuse deterministic peak-to-trough-to-recovery maximum drawdown record independently for WINDOW_A, WINDOW_B, FULL; compare R2 on each Raw episode and report R2-specific worst",
        "classification_logic": {
            "order": ["INCONCLUSIVE", "ECONOMICALLY_PROMISING", "FAIL_RETURN_ENGINE_DESTRUCTION", "FAIL_NO_MEANINGFUL_ECONOMIC_BENEFIT", "MIXED"],
            "inconclusive": "any identity mismatch, Raw replay max error >1e-10, temporal violation, factor comparison unavailable, or materially incomplete R2 valuation",
            "concentration_material": "absolute average HHI reduction >=0.05 and relative reduction >=25%",
            "promising": "concentration_material AND delta Sharpe>=-0.10 AND delta annualized return>=-0.05 AND delta MaxDD>=-0.03 AND R2 turnover<=1.05*Raw AND at least 2 of 4 yearly active returns positive AND top3 positive active-month share<=0.75 AND abs(SPY beta delta)<=0.20",
            "return_engine_destruction": "concentration_material AND (delta annualized return<=-0.10 OR (delta total net return<=-0.30 AND at least 3 of 4 yearly active returns negative) OR (optional intervention 1d mean<0 with HAC t<=-1.96 AND delta annualized return<=-0.05))",
            "no_meaningful_benefit": "concentration_material AND delta annualized return<0 AND delta Sharpe<0 AND delta MaxDD<=0",
            "mixed": "all other complete replays with material concentration reduction",
        },
        "prohibitions": {"R2_modification": False, "rescue_variant_search": False, "rank_cap_search": False, "sector_cap_search": False, "optimizer": False, "promotion": False, "registry_change": False, "prospective_protocol_change": False},
        "anti_duplication_sha256": anti_sha,
        "source_inventory": sources,
        "protected_before": {"prospective": tree_snapshot(PROSPECTIVE), "registry_sha256": identities["registry_sha256"]},
    }
    payload["manifest_payload_sha256"] = stable_hash(payload)
    return payload


def freeze() -> None:
    require(not OUT.exists(), "OUTPUT_ROOT_ALREADY_EXISTS", OUT)
    require(not repo_temp_dirs(), "REPO_ROOT_TEMP_PRESENT", repo_temp_dirs())
    identities = verify_frozen_identities()
    OUT.mkdir(parents=True, exist_ok=False)
    sources = source_rows()
    anti = anti_duplication_payload(sources)
    write_json(ANTI_DUP, anti)
    payload = manifest_payload(identities, sha256_file(ANTI_DUP), sources)
    write_json(MANIFEST, payload)
    print(f"ANTI_DUPLICATION_AUDIT_STATUS={anti['ANTI_DUPLICATION_AUDIT_STATUS']}")
    print(f"ECONOMIC_EVALUATION_MANIFEST_SHA256={sha256_file(MANIFEST)}")
    print("ECONOMIC_OUTCOME_READ_COUNT=0")


def verify_manifest() -> tuple[dict[str, Any], str]:
    require(MANIFEST.is_file() and ANTI_DUP.is_file(), "MANIFEST_NOT_FROZEN")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    declared = manifest.pop("manifest_payload_sha256")
    require(stable_hash(manifest) == declared, "MANIFEST_PAYLOAD_MUTATION")
    manifest["manifest_payload_sha256"] = declared
    require(manifest["economic_outcome_read_count_at_freeze"] == 0, "OUTCOME_READ_AT_FREEZE")
    for row in manifest["source_inventory"]:
        path = Path(row["path"])
        require(path.is_file() and sha256_file(path) == row["sha256"], "SOURCE_CHANGED_AFTER_FREEZE", path)
    verify_frozen_identities()
    return manifest, sha256_file(MANIFEST)


def benchmark_weights_and_peers() -> tuple[dict[pd.Timestamp, dict[str, float]], pd.DataFrame]:
    structural_cols = ["record_type", "signal_date", "realization_date", "taxonomy_level", "sector", "portfolio_weight", "benchmark_weight", "benchmark_sector_return"]
    frame = pd.read_csv(SECTOR_ATTRIBUTION, usecols=structural_cols, low_memory=False)
    frame["signal_date"] = pd.to_datetime(frame.signal_date, errors="coerce").dt.normalize()
    frame["realization_date"] = pd.to_datetime(frame.realization_date, errors="coerce").dt.normalize()
    frame = frame.loc[frame.signal_date.notna() & frame.realization_date.notna() & frame.realization_date.le(ECONOMIC_CUTOFF)]
    daily = frame.loc[frame.record_type.eq("DAILY_SECTOR") & frame.taxonomy_level.eq("FF12")].copy()
    daily = daily.drop_duplicates(["signal_date", "sector"], keep="first")
    weights = {pd.Timestamp(d): dict(zip(g.sector.astype(str), g.benchmark_weight.astype(float))) for d, g in daily.groupby("signal_date", sort=True)}
    return weights, daily


def load_2026_ranked_pool(beta: Any) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    prices = pd.read_parquet(POST_PRICES)
    bench = pd.read_parquet(POST_BENCH)
    for frame in (prices, bench):
        frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.normalize()
        require(frame.trade_date.max() <= LATEST_COMPLETE, "POST_CUTOFF_PRICE_ROW", frame.trade_date.max())
    h2h = beta.load_h2h_module()
    r2a = h2h.load_module("eval_r2a", h2h.R2A_SOURCE)
    r1 = h2h.load_module("eval_r1", h2h.R1_SOURCE)
    engine = h2h.load_module("eval_engine", h2h.ENGINE_SOURCE)
    qqq = bench.loc[bench.ticker.astype(str).str.upper().eq("QQQ")].copy()
    active, members = r2a.validate_pit_manifest(qqq)
    universe = r2a.active_universe_by_date(qqq, active, members, LATEST_SIGNAL)
    ng_freeze = json.loads((h2h.NG_ROOT / "freeze_manifest.json").read_text(encoding="utf-8"))
    ng_ridge = joblib.load(Path(ng_freeze["artifacts"]["ridge_model"]["path"]))
    ng_q90 = joblib.load(Path(ng_freeze["artifacts"]["q90_model"]["path"]))
    matrix, coverage = r2a.build_scored_matrix(r1, prices, qqq, universe, ng_ridge, ng_q90, LATEST_SIGNAL)
    matrix = matrix.loc[pd.to_datetime(matrix.signal_date).between("2026-01-02", LATEST_SIGNAL)].copy()
    matrix["security_id"] = matrix.ticker.astype(str)
    matrix["target"] = np.nan
    matrix["target_end_date"] = pd.NaT
    matrix["outer_fold"] = "EXPOSED_2026_EVALUATION_INFERENCE_ONLY"
    lineage = json.loads((RESULTS / "A2_ALGORITHM_BENCHMARK_R1A_TEMPORAL_BASELINE_RECONSTRUCTION" / "a2_temporal_lineage.json").read_text(encoding="utf-8"))
    features = list(lineage["feature_names"])
    raw_model = joblib.load(MODEL)
    featured = engine.materialize_factors(matrix.copy())
    prediction = raw_model.predict(featured[features].to_numpy(float))
    ranked = h2h.ranked_frame(r1, matrix, prediction, "RAW_A2")
    ranked["signal_date"] = pd.to_datetime(ranked.signal_date).dt.normalize()
    ranked["ticker"] = ranked.ticker.astype(str).str.upper()
    score_col = "score" if "score" in ranked else "prediction"
    ranked = ranked.rename(columns={score_col: "a2_prediction", "rank": "a2_rank"})
    ranked = ranked.sort_values(["signal_date", "a2_rank", "ticker"], kind="mergesort")
    expected = ranked.sort_values(["signal_date", "a2_prediction", "ticker"], ascending=[True, False, True], kind="mergesort").copy()
    expected["check_rank"] = expected.groupby("signal_date").cumcount() + 1
    require(expected.a2_rank.astype(int).eq(expected.check_rank).all(), "2026_RANK_IDENTITY")
    cached_top = pd.read_parquet(POST_TOP20, columns=["signal_date", "ticker", "A2_rank"])
    cached_top["signal_date"] = pd.to_datetime(cached_top.signal_date).dt.normalize()
    cached_top["ticker"] = cached_top.ticker.astype(str).str.upper()
    check = ranked.loc[ranked.a2_rank.le(TOP_N), ["signal_date", "ticker", "a2_rank"]].merge(cached_top, on=["signal_date", "ticker"], how="outer", indicator=True)
    require(check._merge.eq("both").all() and check.a2_rank.astype(int).eq(check.A2_rank.astype(int)).all(), "2026_TOP20_IDENTITY")
    counts = ranked.groupby("signal_date").size()
    audit = {"dates": int(ranked.signal_date.nunique()), "rows": len(ranked), "min_candidates": int(counts.min()), "max_candidates": int(counts.max()), "model_sha256": sha256_file(MODEL), "model_refit_count": 0, "latest_signal": str(ranked.signal_date.max().date()), "coverage_rows": len(coverage)}
    return ranked[["signal_date", "ticker", "a2_prediction", "a2_rank"]].copy(), prices, bench, audit


def bind_2026_taxonomy(pre_panel: pd.DataFrame, post_pool: pd.DataFrame, sector: pd.DataFrame, beta: Any) -> tuple[pd.DataFrame, dict[str, Any]]:
    latest = pre_panel.sort_values("signal_date").drop_duplicates("ticker", keep="last").set_index("ticker").ff12.astype(str).to_dict()
    post = post_pool.copy()
    post["ff12"] = post.ticker.map(latest).fillna("UNKNOWN")
    raw_top = post.loc[post.a2_rank.le(TOP_N), ["signal_date", "ticker", "ff12"]].copy()
    raw_top = raw_top.rename(columns={"ff12": "FF12"})
    recovered, rec_audit = beta.reconcile_unknown_2026_ff12(raw_top, sector)
    recovered_map = recovered.loc[recovered.FF12.ne("UNKNOWN")].sort_values("signal_date").drop_duplicates("ticker", keep="last").set_index("ticker").FF12.to_dict()
    post["ff12"] = post.ticker.map(recovered_map).fillna(post.ff12).fillna("UNKNOWN")
    inferred = post.loc[post.a2_rank.le(TOP_N)].groupby(["signal_date", "ff12"]).size().mul(WEIGHT).rename("inferred").reset_index()
    frozen = sector.loc[sector.signal_date.ge("2026-01-01"), ["signal_date", "sector", "portfolio_weight"]].rename(columns={"sector": "ff12", "portfolio_weight": "frozen"})
    check = inferred.merge(frozen, on=["signal_date", "ff12"], how="outer").fillna(0.0)
    max_error = float((check.inferred - check.frozen).abs().max())
    require(max_error <= TOL, "2026_RAW_TAXONOMY_IDENTITY", max_error)
    audit = {"carry_forward_source": str(TAXONOMY), "new_tickers_explicit_unknown": sorted(post.loc[~post.ticker.isin(latest), "ticker"].unique()), "unknown_row_fraction": float(post.ff12.eq("UNKNOWN").mean()), "raw_top20_sector_weight_max_error": max_error, "raw_top20_unknown_reconciliation": rec_audit}
    return post, audit


def structural_targets() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    r2 = import_file("eval_r2", R2_SOURCE)
    closure = import_file("eval_closure", CLOSURE_SOURCE)
    r1 = r2.import_r1()
    beta = import_file("eval_beta", BETA_SECTOR_SOURCE)
    pre_panel, pre_benchmark, pre_facts = r1.load_structural_inputs()
    sector_weights, sector = benchmark_weights_and_peers()
    post_pool, post_prices, post_bench, inference_audit = load_2026_ranked_pool(beta)
    post_panel, taxonomy_audit = bind_2026_taxonomy(pre_panel, post_pool, sector, beta)
    combined = pd.concat([pre_panel[["signal_date", "ticker", "a2_prediction", "a2_rank", "ff12"]], post_panel], ignore_index=True)
    combined["signal_date"] = pd.to_datetime(combined.signal_date).dt.normalize()
    expected_dates = set(combined.signal_date.unique())
    require(expected_dates.issubset(set(sector_weights)), "BENCHMARK_DATE_MISSING", sorted(expected_dates - set(sector_weights))[:5])
    events, daily, interventions, facts = closure.audit_replay(r2, combined, sector_weights)
    daily["signal_date"] = pd.to_datetime(daily.signal_date).dt.normalize()
    interventions["signal_date"] = pd.to_datetime(interventions.signal_date).dt.normalize()
    pre_daily = daily.loc[daily.signal_date.lt("2026-01-01")].copy()
    frozen = pd.read_csv(CLOSURE_HHI, usecols=["signal_date", "ending_holdings_json", "independently_recomputed_r2_hhi", "raw_a2_hhi"])
    frozen["signal_date"] = pd.to_datetime(frozen.signal_date).dt.normalize()
    check = pre_daily.merge(frozen, on="signal_date", validate="one_to_one")
    require(len(check) == 750, "PRE_STRUCTURAL_DATE_IDENTITY", len(check))
    require(float((check.independently_recomputed_r2_hhi_x - check.independently_recomputed_r2_hhi_y).abs().max()) <= TOL, "PRE_R2_HHI_DRIFT")
    require(check.ending_holdings_json_x.eq(check.ending_holdings_json_y).all(), "PRE_R2_MEMBERSHIP_DRIFT")
    require(facts["membership_transition_error_count"] == 0 and facts["unresolved_entry_slot_count"] == 0, "COMBINED_TRANSITION_ERROR", facts)
    audit = {"pre_facts": pre_facts, "2026_inference": inference_audit, "2026_taxonomy": taxonomy_audit, "combined_transition": facts, "total_signal_dates": len(daily), "post_signal_dates": int(daily.signal_date.ge("2026-01-01").sum())}
    return combined, daily, events, interventions, post_prices, post_bench, audit


def target_map_from_panel(panel: pd.DataFrame, daily: pd.DataFrame, start: str, end: str) -> tuple[dict[pd.Timestamp, dict[str, float]], dict[pd.Timestamp, dict[str, float]]]:
    part = panel.loc[panel.signal_date.between(start, end)].copy()
    raw = {pd.Timestamp(d): {str(t): WEIGHT for t in g.sort_values(["a2_rank", "ticker"]).head(TOP_N).ticker} for d, g in part.groupby("signal_date", sort=True)}
    dpart = daily.loc[daily.signal_date.between(start, end)]
    r2 = {pd.Timestamp(row.signal_date): {str(t): WEIGHT for t in json.loads(row.ending_holdings_json)} for row in dpart.itertuples(index=False)}
    require(set(raw) == set(r2) and all(len(x) == TOP_N for x in r2.values()), "TARGET_MAP_IDENTITY")
    return raw, r2


def replay_pre(panel: pd.DataFrame, daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    global_replay = import_file("eval_global_replay", GLOBAL_REPLAY_SOURCE)
    e5 = import_file("eval_e5", E5_SOURCE)
    pre = panel.loc[panel.signal_date.lt("2026-01-01")]
    raw_targets, r2_targets = target_map_from_panel(panel, daily, "2023-01-03", "2025-12-29")
    prices = global_replay.load_prices(set(pre.ticker) | {"SPY", "SOXX"}, [2023, 2024, 2025])
    dates = sorted(raw_targets)
    execution, signal_map = global_replay.execution_contract(prices, dates, 2025)
    raw_path = global_replay.replay_targets(e5, "C0_MECHANICAL_RAW", raw_targets, prices, execution, signal_map, raw_targets)
    r2_path = global_replay.replay_targets(e5, "A2_HHI_R2", r2_targets, prices, execution, signal_map, raw_targets)
    authoritative = pd.read_parquet(PORTFOLIO)
    authoritative["execution_date"] = pd.to_datetime(authoritative.execution_date).dt.normalize()
    check = raw_path.daily.merge(authoritative, on="execution_date", validate="one_to_one")
    errors = {
        "net": float((check.net_return - check.reconstructed_daily_return).abs().max()),
        "gross": float((check.gross_return - check.reconstructed_gross_return).abs().max()),
        "turnover": float((check.turnover - check.reconstructed_turnover).abs().max()),
        "cost": float((check.transaction_cost_amount - check.reconstructed_transaction_cost).abs().max()),
        "nav": float((check.nav - check.reconstructed_nav).abs().max()),
    }
    require(len(check) == 751 and max(errors.values()) <= TOL, "RAW_PRE_REPLAY_MISMATCH", errors)
    return raw_path.daily, r2_path.daily, prices, {"raw_replay_errors": errors, "sessions": len(check), "engine_source": str(E5_SOURCE)}


def replay_2026(panel: pd.DataFrame, daily: pd.DataFrame, prices: pd.DataFrame, bench: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    old = import_file("eval_old_2026", OLD_2026_SOURCE)
    raw_targets, r2_targets = target_map_from_panel(panel, daily, "2026-01-02", "2026-08-26")
    calendar = pd.DatetimeIndex(sorted(bench.loc[bench.ticker.astype(str).str.upper().eq("QQQ"), "trade_date"].unique()))
    old.EFFECTIVE_START = pd.Timestamp("2026-01-02")
    old.COST_BPS = 10
    raw_path = old.reconstruct_open_ended("RAW_A2", raw_targets, prices, calendar, LATEST_COMPLETE)
    r2_path = old.reconstruct_open_ended("A2_HHI_R2", r2_targets, prices, calendar, LATEST_COMPLETE)
    raw = raw_path.daily.iloc[1:].copy()
    r2 = r2_path.daily.iloc[1:].copy()
    auth = pd.read_csv(H2H_DAILY, usecols=["date", "strategy", "net_return", "turnover"])
    auth = auth.loc[auth.strategy.eq("RAW_A2")].copy()
    auth["date"] = pd.to_datetime(auth.date).dt.normalize()
    check = raw.merge(auth, on="date", validate="one_to_one")
    errors = {"net": float((check.daily_return - check.net_return).abs().max()), "turnover": float((check.turnover_x - check.turnover_y).abs().max())}
    require(len(check) == 163 and max(errors.values()) <= TOL, "RAW_2026_REPLAY_MISMATCH", errors)
    missing = {"raw": raw_path.missing_price_events, "r2": r2_path.missing_price_events}
    require(not any(row.get("kind") in {"SKIPPED_BUY", "BLOCKED_SELL"} for row in missing["r2"]), "R2_MATERIAL_PRICE_FAILURE", missing["r2"][:10])
    return raw, r2, {"raw_replay_errors": errors, "sessions": len(check), "missing_price_events": missing, "engine_source": str(OLD_2026_SOURCE)}


def normalize_daily(pre_raw: pd.DataFrame, pre_r2: pd.DataFrame, post_raw: pd.DataFrame, post_r2: pd.DataFrame, structural: pd.DataFrame) -> pd.DataFrame:
    def pre_part(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
        x = frame.copy()
        return x.rename(columns={"execution_date": "date", "signal_date": "signal_date", "gross_return": f"{prefix}_gross_return", "net_return": f"{prefix}_net_return", "turnover": f"{prefix}_turnover", "transaction_cost_fraction": f"{prefix}_cost", "nav": f"{prefix}_nav"})[["date", "signal_date", f"{prefix}_gross_return", f"{prefix}_net_return", f"{prefix}_turnover", f"{prefix}_cost", f"{prefix}_nav"]]
    a = pre_part(pre_raw, "raw").merge(pre_part(pre_r2, "r2"), on=["date", "signal_date"], validate="one_to_one")
    a["window"] = "WINDOW_A_AUTHORITATIVE_PRE2026"

    def post_part(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
        x = frame.copy().sort_values("date").reset_index(drop=True)
        prior = x.nav.shift(1).fillna(1.0)
        cost = x.transaction_cost / prior
        gross = x.daily_return + cost
        signal = pd.Series(pd.DatetimeIndex(x.date).map(lambda d: pd.NaT), index=x.index)
        return pd.DataFrame({"date": pd.to_datetime(x.date).dt.normalize(), "signal_date": signal, f"{prefix}_gross_return": gross, f"{prefix}_net_return": x.daily_return, f"{prefix}_turnover": x.turnover, f"{prefix}_cost": cost, f"{prefix}_nav": x.nav})
    braw = post_part(post_raw, "raw")
    br2 = post_part(post_r2, "r2")
    b = braw.merge(br2.drop(columns="signal_date"), on="date", validate="one_to_one")
    post_signals = sorted(structural.loc[structural.signal_date.ge("2026-01-01"), "signal_date"])
    require(len(post_signals) == len(b), "POST_SIGNAL_EXECUTION_COUNT")
    b["signal_date"] = post_signals
    b["window"] = "WINDOW_B_EXPOSED_2026"
    out = pd.concat([a, b], ignore_index=True).sort_values("date", kind="mergesort").reset_index(drop=True)
    out["date"] = pd.to_datetime(out.date).dt.normalize()
    out["signal_date"] = pd.to_datetime(out.signal_date).dt.normalize()
    out["active_net_return"] = out.r2_net_return - out.raw_net_return
    for prefix in ("raw", "r2"):
        out[f"{prefix}_nav_rebased"] = (1.0 + out[f"{prefix}_net_return"]).cumprod()
    return out


def metrics(frame: pd.DataFrame, prefix: str) -> dict[str, float]:
    r = frame[f"{prefix}_net_return"].to_numpy(float)
    g = frame[f"{prefix}_gross_return"].to_numpy(float)
    n = len(r)
    total = float(np.prod(1 + r) - 1)
    gross_total = float(np.prod(1 + g) - 1)
    annual = float((1 + total) ** (252 / n) - 1) if total > -1 and n else np.nan
    vol = float(np.std(r, ddof=0) * np.sqrt(252))
    arithmetic = float(np.mean(r) * 252)
    downside = float(np.sqrt(np.mean(np.minimum(r, 0) ** 2)) * np.sqrt(252))
    nav = np.r_[1.0, np.cumprod(1 + r)]
    dd = nav / np.maximum.accumulate(nav) - 1
    mdd = float(dd.min())
    return {
        "sessions": n, "total_net_return": total, "total_gross_return": gross_total,
        "annualized_return": annual, "annualized_arithmetic_return": arithmetic,
        "sharpe": float(arithmetic / vol) if vol else np.nan, "volatility": vol,
        "max_drawdown": mdd, "calmar": float(annual / abs(mdd)) if mdd < 0 else np.nan,
        "sortino": float(arithmetic / downside) if downside else np.nan,
        "turnover": float(frame[f"{prefix}_turnover"].sum()), "total_cost": float(frame[f"{prefix}_cost"].sum()),
        "worst_day": float(r.min()), "best_day": float(r.max()),
    }


def concentration_table(panel: pd.DataFrame, structural: pd.DataFrame, sector: pd.DataFrame) -> pd.DataFrame:
    lookup = panel.set_index(["signal_date", "ticker"]).ff12.astype(str).to_dict()
    benchmark = {pd.Timestamp(d): dict(zip(g.sector.astype(str), g.benchmark_weight.astype(float))) for d, g in sector.groupby("signal_date")}
    rows = []
    for row in structural.itertuples(index=False):
        date = pd.Timestamp(row.signal_date)
        day = panel.loc[panel.signal_date.eq(date)].sort_values(["a2_rank", "ticker"])
        raw = list(day.head(TOP_N).ticker.astype(str))
        r2 = list(json.loads(row.ending_holdings_json))
        record: dict[str, Any] = {"signal_date": date}
        for name, tickers in (("raw", raw), ("r2", r2)):
            counts = pd.Series([lookup[(date, ticker)] for ticker in tickers]).value_counts()
            weights = counts.astype(float) * WEIGHT
            active = [float(weights.get(s, 0.0) - benchmark[date].get(s, 0.0)) for s in set(weights.index) | set(benchmark[date])]
            record[f"{name}_hhi"] = float(np.square(weights).sum())
            record[f"{name}_max_sector_weight"] = float(weights.max())
            record[f"{name}_max_active_overweight"] = float(max([0.0] + active))
        rows.append(record)
    return pd.DataFrame(rows)


def benchmark_returns(pre_prices: pd.DataFrame, post_bench: pd.DataFrame, dates: Iterable[pd.Timestamp]) -> pd.DataFrame:
    wanted = {"SPY", "QQQ", "SOXX"}
    pre = pre_prices.loc[pre_prices.ticker.isin(wanted), ["ticker", "trade_date", "open"]].copy()
    post = post_bench.loc[post_bench.ticker.isin(wanted), ["ticker", "trade_date", "open"]].copy()
    prices = pd.concat([pre, post], ignore_index=True).sort_values(["ticker", "trade_date"]).drop_duplicates(["ticker", "trade_date"], keep="last")
    wide = prices.pivot(index="trade_date", columns="ticker", values="open").sort_index()
    returns = wide.pct_change(fill_method=None)
    result = returns.reindex(pd.DatetimeIndex(dates))[sorted(wanted)].reset_index().rename(columns={"trade_date": "date", "index": "date", "SPY": "spy_return", "QQQ": "qqq_return", "SOXX": "soxx_return"})
    require(result[["spy_return", "qqq_return", "soxx_return"]].notna().all().all(), "BENCHMARK_RETURN_COVERAGE")
    return result


def factor_exposures(daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    slices = {"FULL_COMBINED": daily, "PRE2026": daily.loc[daily.window.str.contains("PRE2026")], "2026_EXPOSED": daily.loc[daily.window.str.contains("2026")]}
    slices.update({f"YEAR_{year}": group for year, group in daily.groupby(daily.date.dt.year)})
    for window, frame in slices.items():
        spy = frame.spy_return.to_numpy(float)
        qqq = frame.qqq_return.to_numpy(float)
        soxx = frame.soxx_return.to_numpy(float)
        qfit = ols_hac(qqq, np.column_stack([np.ones(len(spy)), spy]))
        qorth = qfit["residual"]
        sfit = ols_hac(soxx, np.column_stack([np.ones(len(spy)), spy, qorth]))
        sorth = sfit["residual"]
        x = np.column_stack([np.ones(len(spy)), spy, qorth, sorth])
        for strategy, col in (("RAW_A2", "raw_net_return"), ("R2", "r2_net_return")):
            fit = ols_hac(frame[col].to_numpy(float), x)
            rows.append({"window": window, "strategy": strategy, "N": len(frame), "alpha_daily": float(fit["params"][0]), "SPY_BETA": float(fit["params"][1]), "QQQ_ORTH_BETA": float(fit["params"][2]), "SOXX_ORTH_BETA": float(fit["params"][3]), "SPY_TSTAT": float(fit["tvalues"][1]), "QQQ_ORTH_TSTAT": float(fit["tvalues"][2]), "SOXX_ORTH_TSTAT": float(fit["tvalues"][3]), "r_squared": float(fit["r_squared"])})
    return pd.DataFrame(rows)


def return_calendar(prices: pd.DataFrame, bench: pd.DataFrame, signal_dates: Iterable[pd.Timestamp]) -> dict[tuple[pd.Timestamp, int], tuple[pd.Timestamp, pd.Timestamp]]:
    calendar = pd.DatetimeIndex(sorted(set(prices.trade_date) | set(bench.trade_date)))
    result = {}
    for signal in sorted(pd.Timestamp(x) for x in signal_dates):
        pos = int(np.searchsorted(calendar.to_numpy(), np.datetime64(signal), side="right"))
        if pos >= len(calendar):
            continue
        entry = pd.Timestamp(calendar[pos])
        for horizon in (1, 5, 20):
            if pos + horizon < len(calendar):
                realization = pd.Timestamp(calendar[pos + horizon])
                if realization <= ECONOMIC_CUTOFF:
                    result[(signal, horizon)] = (entry, realization)
    return result


def stock_outcomes(panel: pd.DataFrame, pre_prices: pd.DataFrame, post_prices: pd.DataFrame, post_bench: pd.DataFrame, sector: pd.DataFrame, structural: pd.DataFrame, interventions: pd.DataFrame) -> pd.DataFrame:
    pre_raw = pre_prices.attrs.get("raw_counterfactual", pre_prices)
    all_prices = pd.concat([pre_raw[["ticker", "trade_date", "open"]], post_prices[["ticker", "trade_date", "open"]]], ignore_index=True)
    all_prices["ticker"] = all_prices.ticker.astype(str).str.upper()
    all_prices["trade_date"] = pd.to_datetime(all_prices.trade_date).dt.normalize()
    all_prices = all_prices.loc[all_prices.trade_date.le(ECONOMIC_CUTOFF)].sort_values(["ticker", "trade_date"]).drop_duplicates(["ticker", "trade_date"], keep="last")
    lookup = all_prices.set_index(["trade_date", "ticker"]).open
    cal = return_calendar(all_prices, post_bench, panel.signal_date.unique())
    peer1 = sector.set_index(["signal_date", "sector"]).benchmark_sector_return.to_dict()
    sector_dates = sorted(pd.Timestamp(x) for x in sector.signal_date.unique())
    sector_pos = {date: i for i, date in enumerate(sector_dates)}
    membership = structural.set_index("signal_date").ending_holdings_json.map(json.loads).to_dict()
    extra_keys = set(zip(pd.to_datetime(interventions.signal_date).dt.normalize(), interventions.canonical_entrant.astype(str))) | set(zip(pd.to_datetime(interventions.signal_date).dt.normalize(), interventions.alternative_entrant.astype(str)))
    rows = []
    for row in panel[["signal_date", "ticker", "a2_rank", "ff12"]].itertuples(index=False):
        date = pd.Timestamp(row.signal_date)
        raw_held = int(row.a2_rank) <= TOP_N
        r2_held = str(row.ticker) in set(membership[date])
        if not raw_held and not r2_held and (date, str(row.ticker)) not in extra_keys:
            continue
        item: dict[str, Any] = {"signal_date": date, "ticker": str(row.ticker), "a2_rank": int(row.a2_rank), "ff12": str(row.ff12), "raw_held": raw_held, "r2_held": r2_held, "selected_status": "COMMON" if raw_held and r2_held else "RAW_A2_ONLY" if raw_held else "R2_ONLY"}
        for h in (1, 5, 20):
            dates = cal.get((date, h))
            value = np.nan
            if dates:
                p0 = lookup.get((dates[0], str(row.ticker)), np.nan)
                p1 = lookup.get((dates[1], str(row.ticker)), np.nan)
                if pd.notna(p0) and pd.notna(p1) and float(p0) > 0:
                    value = float(p1) / float(p0) - 1.0
            item[f"future_return_{h}d"] = value
            idx = sector_pos.get(date)
            legs = [] if idx is None else [peer1.get((sector_dates[j], str(row.ff12)), np.nan) for j in range(idx, min(idx + h, len(sector_dates)))]
            peer = float(np.prod(1 + np.asarray(legs, float)) - 1) if len(legs) == h and np.isfinite(legs).all() else np.nan
            item[f"sector_peer_return_{h}d"] = peer
            item[f"sector_adjusted_return_{h}d"] = value - peer if np.isfinite(value) and np.isfinite(peer) else np.nan
        rows.append(item)
    out = pd.DataFrame(rows)
    matched = pd.read_parquet(MATCHED, columns=["signal_date", "horizon", "a2_ticker", "matched_excess", "realization_date", "post_cutoff_outcome"])
    matched["signal_date"] = pd.to_datetime(matched.signal_date).dt.normalize()
    matched["realization_date"] = pd.to_datetime(matched.realization_date).dt.normalize()
    require(not matched.post_cutoff_outcome.fillna(False).astype(bool).any(), "MATCHED_POST_CUTOFF_FLAG")
    matched = matched.loc[matched.realization_date.le(ECONOMIC_CUTOFF)]
    for h in (1, 5, 20):
        part = matched.loc[matched.horizon.eq(h), ["signal_date", "a2_ticker", "matched_excess"]].rename(columns={"a2_ticker": "ticker", "matched_excess": f"matched_excess_{h}d"}).drop_duplicates(["signal_date", "ticker"])
        part["ticker"] = part.ticker.astype(str).str.upper()
        out = out.merge(part, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    return out


def hac_tstat(values: pd.DataFrame, value_col: str) -> float:
    x = values[["signal_date", value_col]].dropna().groupby("signal_date")[value_col].mean()
    if len(x) < 10:
        return np.nan
    fit = ols_hac(x.to_numpy(float), np.ones((len(x), 1)))
    return float(fit["tvalues"][0])


def intervention_economics(interventions: pd.DataFrame, outcomes: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    ledger = interventions.copy()
    left_cols = ["signal_date", "ticker", *[f"future_return_{h}d" for h in (1, 5, 20)], *[f"sector_adjusted_return_{h}d" for h in (1, 5, 20)]]
    alt = outcomes[left_cols].rename(columns={"ticker": "alternative_entrant", **{f"future_return_{h}d": f"alternative_return_{h}d" for h in (1, 5, 20)}, **{f"sector_adjusted_return_{h}d": f"alternative_sector_adjusted_{h}d" for h in (1, 5, 20)}})
    can = outcomes[left_cols].rename(columns={"ticker": "canonical_entrant", **{f"future_return_{h}d": f"canonical_return_{h}d" for h in (1, 5, 20)}, **{f"sector_adjusted_return_{h}d": f"canonical_sector_adjusted_{h}d" for h in (1, 5, 20)}})
    ledger = ledger.merge(alt, on=["signal_date", "alternative_entrant"], how="left", validate="many_to_one").merge(can, on=["signal_date", "canonical_entrant"], how="left", validate="many_to_one")
    for h in (1, 5, 20):
        ledger[f"alternative_minus_canonical_{h}d"] = ledger[f"alternative_return_{h}d"] - ledger[f"canonical_return_{h}d"]
    ledger["rank_bucket"] = pd.cut(ledger.alternative_rank, bins=[-np.inf, 40, 60, 100, 200, np.inf], labels=["LE40", "41_60", "61_100", "101_200", "GT200"])
    frozen = ledger.loc[ledger.signal_date.lt("2026-01-01")].copy()
    require(int(frozen.request_type.eq("OPTIONAL_RAW_A2_ENTRY").sum()) == 2209 and int(frozen.request_type.eq("FORCED_EXIT_REPLACEMENT").sum()) == 21, "FROZEN_INTERVENTION_COUNT")
    summary: dict[str, Any] = {"optional_n": 2209, "forced_n": 21, "exposed_2026_continuation_n": int(ledger.signal_date.ge("2026-01-01").sum())}
    optional = frozen.loc[frozen.request_type.eq("OPTIONAL_RAW_A2_ENTRY")]
    for h in (1, 5, 20):
        x = optional[f"alternative_minus_canonical_{h}d"].dropna()
        summary[f"optional_{h}d"] = {"N": len(x), "mean": float(x.mean()), "median": float(x.median()), "win_rate": float(x.gt(0).mean()), "hac_tstat": hac_tstat(optional, f"alternative_minus_canonical_{h}d")}
    rank = {}
    for bucket, group in frozen.groupby("rank_bucket", observed=True):
        rank[str(bucket)] = {"N": len(group), "return_1d": float(group.alternative_return_1d.mean()), "sector_adjusted_1d": float(group.alternative_sector_adjusted_1d.mean()), "return_5d": float(group.alternative_return_5d.mean()), "return_20d": float(group.alternative_return_20d.mean())}
    summary["rank_buckets"] = rank
    return ledger, summary


def yearly_and_monthly(daily: pd.DataFrame, concentration: pd.DataFrame, factors: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    merged = daily.copy()
    rows = []
    for year, group in merged.groupby(merged.date.dt.year):
        rm, smet = metrics(group, "raw"), metrics(group, "r2")
        f = factors.loc[factors.window.eq(f"YEAR_{year}")].set_index("strategy")
        rows.append({"year": int(year), "evidence": "2026_EXPOSED" if year == 2026 else "RETROSPECTIVE_EXPOSED", "raw_net_return": rm["total_net_return"], "r2_net_return": smet["total_net_return"], "active_return": smet["total_net_return"] - rm["total_net_return"], "raw_sharpe": rm["sharpe"], "r2_sharpe": smet["sharpe"], "raw_max_drawdown": rm["max_drawdown"], "r2_max_drawdown": smet["max_drawdown"], "raw_avg_hhi": float(group.raw_hhi.mean()), "r2_avg_hhi": float(group.r2_hhi.mean()), "raw_turnover": rm["turnover"], "r2_turnover": smet["turnover"], "spy_beta_raw": float(f.loc["RAW_A2", "SPY_BETA"]), "spy_beta_r2": float(f.loc["R2", "SPY_BETA"])})
    yearly = pd.DataFrame(rows)
    month_rows = []
    for month, group in daily.groupby(daily.date.dt.to_period("M")):
        raw_return = float(np.prod(1 + group.raw_net_return) - 1)
        r2_return = float(np.prod(1 + group.r2_net_return) - 1)
        month_rows.append({"month": str(month), "raw_net_return": raw_return, "r2_net_return": r2_return, "active_return": r2_return - raw_return, "sessions": len(group)})
    return yearly, pd.DataFrame(month_rows)


def drawdown_record(frame: pd.DataFrame, prefix: str, window: str, episode_source: str = "SELF") -> dict[str, Any]:
    x = frame.sort_values("date").reset_index(drop=True)
    nav = np.cumprod(1 + x[f"{prefix}_net_return"].to_numpy(float))
    peaks = np.maximum.accumulate(nav)
    dd = nav / peaks - 1
    trough = int(np.argmin(dd))
    peak = int(np.argmax(nav[:trough + 1]))
    recovery = None
    for i in range(trough + 1, len(nav)):
        if nav[i] >= nav[peak] - 1e-12:
            recovery = i
            break
    return {"window": window, "episode_source": episode_source, "strategy": prefix.upper(), "start": str(x.date.iloc[peak].date()), "trough": str(x.date.iloc[trough].date()), "recovery": str(x.date.iloc[recovery].date()) if recovery is not None else None, "max_drawdown": float(dd[trough])}


def drawdown_table(daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    slices = {"PRE2026": daily.loc[daily.window.str.contains("PRE2026")], "2026_EXPOSED": daily.loc[daily.window.str.contains("2026")], "FULL": daily}
    for name, group in slices.items():
        raw = drawdown_record(group, "raw", name)
        r2 = drawdown_record(group, "r2", name)
        rows.extend([raw, r2])
        start, end = pd.Timestamp(raw["start"]), pd.Timestamp(raw["recovery"] or group.date.max())
        episode = group.loc[group.date.between(start, end)].copy()
        comp = drawdown_record(episode, "r2", name, "RAW_A2_EPISODE")
        comp["raw_episode_start"] = raw["start"]
        comp["raw_episode_trough"] = raw["trough"]
        comp["raw_episode_recovery"] = raw["recovery"]
        comp["raw_episode_drawdown"] = raw["max_drawdown"]
        comp["drawdown_delta"] = comp["max_drawdown"] - raw["max_drawdown"]
        rows.append(comp)
    return pd.DataFrame(rows)


def selection_summary(outcomes: pd.DataFrame) -> dict[str, Any]:
    result = {}
    groups = {"CANONICAL_RAW_A2": outcomes.loc[outcomes.raw_held], "R2_ONLY": outcomes.loc[outcomes.selected_status.eq("R2_ONLY")], "RAW_A2_ONLY": outcomes.loc[outcomes.selected_status.eq("RAW_A2_ONLY")], "COMMON": outcomes.loc[outcomes.selected_status.eq("COMMON")]}
    for name, group in groups.items():
        result[name] = {"N": len(group), **{f"forward_return_{h}d": float(group[f"future_return_{h}d"].mean()) for h in (1, 5, 20)}, "sector_adjusted_1d": float(group.sector_adjusted_return_1d.mean()), "matched_excess_1d": float(group.matched_excess_1d.mean()), "matched_N_1d": int(group.matched_excess_1d.notna().sum())}
    return result


def tail_test(daily: pd.DataFrame) -> dict[str, float]:
    n = int(math.ceil(0.10 * len(daily)))
    worst = daily.sort_values(["raw_net_return", "date"], kind="mergesort").head(n)
    best = daily.sort_values(["raw_net_return", "date"], ascending=[False, True], kind="mergesort").head(n)
    return {"N_each": n, "RAW_WORST_DECILE_RETURN": float(worst.raw_net_return.mean()), "R2_WORST_DECILE_RETURN": float(worst.r2_net_return.mean()), "WORST_DECILE_DELTA": float((worst.r2_net_return - worst.raw_net_return).mean()), "RAW_BEST_DECILE_RETURN": float(best.raw_net_return.mean()), "R2_BEST_DECILE_RETURN": float(best.r2_net_return.mean()), "BEST_DECILE_DELTA": float((best.r2_net_return - best.raw_net_return).mean())}


def classify(raw: dict[str, float], r2: dict[str, float], concentration: pd.DataFrame, yearly: pd.DataFrame, monthly: pd.DataFrame, intervention: dict[str, Any], factor: pd.DataFrame, replay_ok: bool) -> tuple[str, dict[str, Any]]:
    delta = {"net_return": r2["total_net_return"] - raw["total_net_return"], "annualized_return": r2["annualized_return"] - raw["annualized_return"], "sharpe": r2["sharpe"] - raw["sharpe"], "max_drawdown": r2["max_drawdown"] - raw["max_drawdown"], "turnover": r2["turnover"] - raw["turnover"], "avg_hhi": float(concentration.r2_hhi.mean() - concentration.raw_hhi.mean())}
    hhi_relative = float(-delta["avg_hhi"] / concentration.raw_hhi.mean())
    positive_months = monthly.loc[monthly.active_return.gt(0), "active_return"]
    top3_share = float(positive_months.nlargest(3).sum() / positive_months.sum()) if positive_months.sum() > 0 else 1.0
    full_factor = factor.loc[factor.window.eq("FULL_COMBINED")].set_index("strategy")
    beta_delta = float(full_factor.loc["R2", "SPY_BETA"] - full_factor.loc["RAW_A2", "SPY_BETA"])
    negative_years = int(yearly.active_return.lt(0).sum())
    positive_years = int(yearly.active_return.gt(0).sum())
    concentration_material = bool(delta["avg_hhi"] <= -0.05 and hhi_relative >= 0.25)
    promising = bool(concentration_material and delta["sharpe"] >= -0.10 and delta["annualized_return"] >= -0.05 and delta["max_drawdown"] >= -0.03 and r2["turnover"] <= 1.05 * raw["turnover"] and positive_years >= 2 and top3_share <= 0.75 and abs(beta_delta) <= 0.20)
    opt = intervention["optional_1d"]
    destruction = bool(concentration_material and (delta["annualized_return"] <= -0.10 or (delta["net_return"] <= -0.30 and negative_years >= 3) or (opt["mean"] < 0 and opt["hac_tstat"] <= -1.96 and delta["annualized_return"] <= -0.05)))
    no_benefit = bool(concentration_material and delta["annualized_return"] < 0 and delta["sharpe"] < 0 and delta["max_drawdown"] <= 0)
    if not replay_ok:
        label = "INCONCLUSIVE_ECONOMIC_REPLAY"
    elif promising:
        label = "ECONOMICALLY_PROMISING_FROZEN_SECTOR_SHADOW"
    elif destruction:
        label = "FAIL_RETURN_ENGINE_DESTRUCTION"
    elif no_benefit:
        label = "FAIL_NO_MEANINGFUL_ECONOMIC_BENEFIT"
    else:
        label = "MIXED_SECTOR_DIVERSIFICATION_TRADEOFF"
    gates = {"deltas": delta, "relative_hhi_reduction": hhi_relative, "positive_years": positive_years, "negative_years": negative_years, "top3_positive_month_share": top3_share, "spy_beta_delta": beta_delta, "concentration_material": concentration_material, "promising_gate": promising, "destruction_gate": destruction, "no_meaningful_benefit_gate": no_benefit}
    return label, gates


def plot_outputs(daily: pd.DataFrame, concentration: pd.DataFrame, yearly: pd.DataFrame, monthly: pd.DataFrame) -> None:
    plt.figure(figsize=(9, 5)); plt.plot(daily.date, daily.raw_nav_rebased, label="Raw A2"); plt.plot(daily.date, daily.r2_nav_rebased, label="R2"); plt.legend(); plt.ylabel("Rebased net NAV"); plt.tight_layout(); plt.savefig(OUT / "nav_comparison.png", dpi=150); plt.close()
    active = (1 + daily.r2_net_return).rolling(63).apply(np.prod, raw=True) / (1 + daily.raw_net_return).rolling(63).apply(np.prod, raw=True) - 1
    plt.figure(figsize=(9, 4)); plt.plot(daily.date, active); plt.axhline(0, color="black", lw=.8); plt.ylabel("63-session R2/Raw active return"); plt.tight_layout(); plt.savefig(OUT / "rolling_active_performance.png", dpi=150); plt.close()
    m = daily.dropna(subset=["raw_hhi", "r2_hhi"]).assign(month=lambda x: x.date.dt.to_period("M").astype(str), delta_hhi=lambda x: x.r2_hhi-x.raw_hhi).groupby("month", as_index=False).delta_hhi.mean().merge(monthly, on="month", validate="one_to_one")
    plt.figure(figsize=(6, 5)); plt.scatter(m.delta_hhi, m.active_return, c=m.active_return, cmap="coolwarm"); plt.axhline(0, color="black", lw=.8); plt.xlabel("Monthly mean R2 minus Raw HHI"); plt.ylabel("Monthly R2 minus Raw return"); plt.tight_layout(); plt.savefig(OUT / "hhi_vs_performance_tradeoff.png", dpi=150); plt.close()
    x = np.arange(len(yearly)); w=.35; plt.figure(figsize=(8, 5)); plt.bar(x-w/2, yearly.raw_net_return, w, label="Raw A2"); plt.bar(x+w/2, yearly.r2_net_return, w, label="R2"); plt.xticks(x, yearly.year); plt.axhline(0,color="black",lw=.8); plt.legend(); plt.ylabel("Net return"); plt.tight_layout(); plt.savefig(OUT / "yearly_return_risk_comparison.png", dpi=150); plt.close()


def concise_report(summary: dict[str, Any]) -> str:
    f = summary["full_window"]
    c = summary["concentration"]
    i = summary["intervention_economics"]["optional_1d"]
    return f"""# A2 HHI R2 frozen economic evaluation

**Status:** `{summary['FINAL_ECONOMIC_CLASSIFICATION']}`  
**Evidence:** `{EVIDENCE_LABEL}`; this is exposed retrospective evidence and is not promotion authority.

The frozen R2 rule reduced average FF12 HHI from {c['AVG_HHI_RAW']:.6f} to {c['AVG_HHI_R2']:.6f}.  Full-window net return was {f['RAW_A2']['total_net_return']:.2%} for Raw A2 and {f['R2']['total_net_return']:.2%} for R2; Sharpe was {f['RAW_A2']['sharpe']:.3f} versus {f['R2']['sharpe']:.3f}; MaxDD was {f['RAW_A2']['max_drawdown']:.2%} versus {f['R2']['max_drawdown']:.2%}.  Turnover was {f['RAW_A2']['turnover']:.3f} versus {f['R2']['turnover']:.3f}.

Across the 2,209 frozen optional interventions, the alternative-minus-canonical 1-day mean was {i['mean']:.4%}, median {i['median']:.4%}, win rate {i['win_rate']:.2%}, and date-level HAC t-stat {i['hac_tstat']:.3f}.  All years and the exposed 2026 window are retained in `yearly_metrics.csv`; deep-rank substitution diagnostics are retained in `intervention_economics.csv` and `summary.json`.

The classification follows the manifest frozen before outcome reads.  No cap, rank limit, softer guard, optimizer, or R3 variant was tested.  Raw A2 remains canonical, and the protected A2/X0 prospective protocol was unchanged.
"""


def console(summary: dict[str, Any]) -> str:
    f = summary["full_window"]; raw=f["RAW_A2"]; r2=f["R2"]; d=summary["classification_gates"]["deltas"]; c=summary["concentration"]; fac=summary["factor_full"]; inter=summary["intervention_economics"]; tails=summary["tail_test"]
    factor = {row["strategy"]: row for row in fac}
    rb = inter["rank_buckets"]
    fmt=lambda x: "NA" if x is None or (isinstance(x,float) and not math.isfinite(x)) else str(x)
    lines = ["="*60,"A2 HHI R2 FROZEN ECONOMIC EVALUATION","="*60,f"STATUS={summary['STATUS']}","",f"RAW_A2_IDENTITY_STATUS={summary['RAW_A2_IDENTITY_STATUS']}",f"R2_PROTOCOL_HASH_STATUS={summary['R2_PROTOCOL_HASH_STATUS']}",f"R2_CONTRACT_HASH_STATUS={summary['R2_CONTRACT_HASH_STATUS']}",f"STRUCTURAL_CLOSURE_STATUS={summary['STRUCTURAL_CLOSURE_STATUS']}","",f"ECONOMIC_EVALUATION_MANIFEST_SHA256={summary['ECONOMIC_EVALUATION_MANIFEST_SHA256']}","",f"ECONOMIC_CUTOFF={summary['ECONOMIC_CUTOFF']}",f"LATEST_USED_SESSION={summary['LATEST_USED_SESSION']}",f"POST_2026_08_28_OUTCOME_READ_COUNT={summary['POST_2026_08_28_OUTCOME_READ_COUNT']}","","-"*60,"ANTI-DUPLICATION","-"*60,"",f"ANTI_DUPLICATION_AUDIT_STATUS={summary['ANTI_DUPLICATION_AUDIT_STATUS']}","",f"REUSE_PORTFOLIO_REPLAY={summary['REUSE_PORTFOLIO_REPLAY']}",f"REUSE_COST_ENGINE={summary['REUSE_COST_ENGINE']}",f"REUSE_METRIC_ENGINE={summary['REUSE_METRIC_ENGINE']}",f"REUSE_FACTOR_EXPOSURE_ENGINE={summary['REUSE_FACTOR_EXPOSURE_ENGINE']}",f"REUSE_SECTOR_ATTRIBUTION_ENGINE={summary['REUSE_SECTOR_ATTRIBUTION_ENGINE']}","","NEW_BACKTESTER_CREATED=FALSE","NEW_COST_ENGINE_CREATED=FALSE","NEW_GENERIC_PORTFOLIO_ENGINE_CREATED=FALSE","","-"*60,"FULL WINDOW","-"*60,"","METRIC                RAW_A2        R2          DELTA"]
    for label,key in [("NET_RETURN","total_net_return"),("ANNUALIZED_RETURN","annualized_return"),("SHARPE","sharpe"),("VOLATILITY","volatility"),("MAX_DRAWDOWN","max_drawdown"),("CALMAR","calmar"),("SORTINO","sortino"),("TURNOVER","turnover"),("TOTAL_COST","total_cost")]: lines.append(f"{label:<22}{raw[key]:<14.10f}{r2[key]:<14.10f}{r2[key]-raw[key]:.10f}")
    lines += ["","-"*60,"SECTOR RISK","-"*60,"",f"AVG_HHI_RAW={c['AVG_HHI_RAW']}",f"AVG_HHI_R2={c['AVG_HHI_R2']}",f"DELTA_AVG_HHI={c['DELTA_AVG_HHI']}","",f"P90_HHI_RAW={c['P90_HHI_RAW']}",f"P90_HHI_R2={c['P90_HHI_R2']}","",f"MAX_SECTOR_WEIGHT_RAW={c['MAX_SECTOR_WEIGHT_RAW']}",f"MAX_SECTOR_WEIGHT_R2={c['MAX_SECTOR_WEIGHT_R2']}","",f"AVG_ACTIVE_OVERWEIGHT_RAW={c['AVG_ACTIVE_OVERWEIGHT_RAW']}",f"AVG_ACTIVE_OVERWEIGHT_R2={c['AVG_ACTIVE_OVERWEIGHT_R2']}","","-"*60,"SYSTEMATIC EXPOSURE","-"*60,"",f"SPY_BETA_RAW={factor['RAW_A2']['SPY_BETA']}",f"SPY_BETA_R2={factor['R2']['SPY_BETA']}","",f"QQQ_ORTH_BETA_RAW={factor['RAW_A2']['QQQ_ORTH_BETA']}",f"QQQ_ORTH_BETA_R2={factor['R2']['QQQ_ORTH_BETA']}","",f"SOXX_ORTH_BETA_RAW={factor['RAW_A2']['SOXX_ORTH_BETA']}",f"SOXX_ORTH_BETA_R2={factor['R2']['SOXX_ORTH_BETA']}","","-"*60,"INTERVENTION ECONOMICS","-"*60,"",f"OPTIONAL_INTERVENTION_N={inter['optional_n']}","",f"ALT_MINUS_CANONICAL_1D_MEAN={inter['optional_1d']['mean']}",f"ALT_MINUS_CANONICAL_1D_MEDIAN={inter['optional_1d']['median']}",f"ALT_MINUS_CANONICAL_1D_WIN_RATE={inter['optional_1d']['win_rate']}",f"ALT_MINUS_CANONICAL_1D_HAC_TSTAT={inter['optional_1d']['hac_tstat']}","",f"ALT_MINUS_CANONICAL_5D_MEAN={inter['optional_5d']['mean']}",f"ALT_MINUS_CANONICAL_20D_MEAN={inter['optional_20d']['mean']}","","-"*60,"RANK DEPTH","-"*60,"",f"ALT_RANK_LE40_SELECTION={rb.get('LE40',{}).get('sector_adjusted_1d')}",f"ALT_RANK_41_60_SELECTION={rb.get('41_60',{}).get('sector_adjusted_1d')}",f"ALT_RANK_61_100_SELECTION={rb.get('61_100',{}).get('sector_adjusted_1d')}",f"ALT_RANK_101_200_SELECTION={rb.get('101_200',{}).get('sector_adjusted_1d')}",f"ALT_RANK_GT200_SELECTION={rb.get('GT200',{}).get('sector_adjusted_1d')}","","-"*60,"YEARLY","-"*60,"","YEAR    RAW_RETURN    R2_RETURN    ACTIVE    RAW_SHARPE    R2_SHARPE"]
    for row in summary["yearly"]: lines.append(f"{row['year']}    {row['raw_net_return']:.10f}    {row['r2_net_return']:.10f}    {row['active_return']:.10f}    {row['raw_sharpe']:.10f}    {row['r2_sharpe']:.10f}")
    lines += ["","-"*60,"DOWNSIDE / UPSIDE","-"*60,"",f"RAW_WORST_DECILE_RETURN={tails['RAW_WORST_DECILE_RETURN']}",f"R2_WORST_DECILE_RETURN={tails['R2_WORST_DECILE_RETURN']}",f"WORST_DECILE_DELTA={tails['WORST_DECILE_DELTA']}","",f"RAW_BEST_DECILE_RETURN={tails['RAW_BEST_DECILE_RETURN']}",f"R2_BEST_DECILE_RETURN={tails['R2_BEST_DECILE_RETURN']}",f"BEST_DECILE_DELTA={tails['BEST_DECILE_DELTA']}","","-"*60,"TRADEOFF","-"*60,"",f"DELTA_NET_RETURN={d['net_return']}",f"DELTA_SHARPE={d['sharpe']}",f"DELTA_MAXDD={d['max_drawdown']}",f"DELTA_TURNOVER={d['turnover']}",f"DELTA_AVG_HHI={d['avg_hhi']}","","-"*60,"FINAL","-"*60,"",f"FINAL_ECONOMIC_CLASSIFICATION={summary['FINAL_ECONOMIC_CLASSIFICATION']}","",f"CORE_NUMERICAL_REASON={summary['CORE_NUMERICAL_REASON']}","","SEARCH_COUNT_FOR_R2_RESCUE_VARIANTS=0","","CANONICAL_REGISTRY_CHANGE=FALSE","RAW_A2_UNCHANGED=TRUE","PROSPECTIVE_A2_X0_PROTOCOL_UNTOUCHED=TRUE","",f"NEXT_RESEARCH_PRIORITY={summary['NEXT_RESEARCH_PRIORITY']}","","TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT=0","",f"ARTIFACT_DIR={OUT}","="*60]
    return "\n".join(lines)


def evaluate() -> None:
    manifest, manifest_sha = verify_manifest()
    protected_before = manifest["protected_before"]
    panel, structural, events, interventions, post_prices, post_bench, structural_audit = structural_targets()
    pre_raw, pre_r2, pre_prices, pre_audit = replay_pre(panel, structural)
    post_raw, post_r2, post_audit = replay_2026(panel, structural, post_prices, post_bench)
    daily = normalize_daily(pre_raw, pre_r2, post_raw, post_r2, structural)
    factors = benchmark_returns(pre_prices, post_bench, daily.date)
    daily = daily.merge(factors, on="date", validate="one_to_one")
    factor_table = factor_exposures(daily)
    _, sector = benchmark_weights_and_peers()
    concentration = concentration_table(panel, structural, sector)
    daily = daily.merge(concentration, on="signal_date", how="left", validate="many_to_one")
    require(len(daily) == 914, "FULL_DAILY_SESSION_COUNT", len(daily))
    full_raw, full_r2 = metrics(daily, "raw"), metrics(daily, "r2")
    outcomes = stock_outcomes(panel, pre_prices, post_prices, post_bench, sector, structural, interventions)
    intervention_table, intervention_summary = intervention_economics(interventions, outcomes)
    yearly, monthly = yearly_and_monthly(daily, concentration, factor_table)
    drawdowns = drawdown_table(daily)
    tails = tail_test(daily)
    selection = selection_summary(outcomes)
    label, gates = classify(full_raw, full_r2, concentration, yearly, monthly, intervention_summary, factor_table, True)
    next_priority = {"ECONOMICALLY_PROMISING_FROZEN_SECTOR_SHADOW": "DECIDE_PROSPECTIVE_SECTOR_SHADOW_REGISTRATION_WITHOUT_RETUNING", "MIXED_SECTOR_DIVERSIFICATION_TRADEOFF": "STOP_IN_SAMPLE_R2_REDESIGN_AND_REASSESS_AT_SLEEVE_LEVEL", "FAIL_RETURN_ENGINE_DESTRUCTION": "CLOSE_SECURITY_LEVEL_SECTOR_BUDGET_BRANCH_AND_MOVE_TO_TAIL_RISK_OR_SLEEVE_LEVEL_CAPITAL_LIMIT", "FAIL_NO_MEANINGFUL_ECONOMIC_BENEFIT": "CLOSE_SECURITY_LEVEL_SECTOR_BUDGET_BRANCH_AND_MOVE_TO_TAIL_RISK_OR_SLEEVE_LEVEL_CAPITAL_LIMIT", "INCONCLUSIVE_ECONOMIC_REPLAY": "DO_NOT_READ_FURTHER_ECONOMICS_FIX_IDENTITY_OR_REPLAY_BLOCKER"}[label]
    conc_summary = {"AVG_HHI_RAW": float(concentration.raw_hhi.mean()), "AVG_HHI_R2": float(concentration.r2_hhi.mean()), "DELTA_AVG_HHI": float(concentration.r2_hhi.mean() - concentration.raw_hhi.mean()), "P90_HHI_RAW": float(concentration.raw_hhi.quantile(.9)), "P90_HHI_R2": float(concentration.r2_hhi.quantile(.9)), "MAX_HHI_RAW": float(concentration.raw_hhi.max()), "MAX_HHI_R2": float(concentration.r2_hhi.max()), "MAX_SECTOR_WEIGHT_RAW": float(concentration.raw_max_sector_weight.max()), "MAX_SECTOR_WEIGHT_R2": float(concentration.r2_max_sector_weight.max()), "AVG_ACTIVE_OVERWEIGHT_RAW": float(concentration.raw_max_active_overweight.mean()), "AVG_ACTIVE_OVERWEIGHT_R2": float(concentration.r2_max_active_overweight.mean()), "P90_ACTIVE_OVERWEIGHT_RAW": float(concentration.raw_max_active_overweight.quantile(.9)), "P90_ACTIVE_OVERWEIGHT_R2": float(concentration.r2_max_active_overweight.quantile(.9))}
    core = f"average HHI {conc_summary['AVG_HHI_RAW']:.6f}->{conc_summary['AVG_HHI_R2']:.6f}; net return {full_raw['total_net_return']:.4f}->{full_r2['total_net_return']:.4f}; Sharpe {full_raw['sharpe']:.3f}->{full_r2['sharpe']:.3f}; MaxDD {full_raw['max_drawdown']:.3f}->{full_r2['max_drawdown']:.3f}; optional 1d alt-minus-canonical {intervention_summary['optional_1d']['mean']:.6f} (HAC t={intervention_summary['optional_1d']['hac_tstat']:.2f})"
    anti = json.loads(ANTI_DUP.read_text(encoding="utf-8"))
    positive_months = monthly.loc[monthly.active_return.gt(0), "active_return"]
    top1_positive_month_share = float(positive_months.nlargest(1).sum() / positive_months.sum()) if positive_months.sum() > 0 else 1.0
    summary = {
        "STATUS": "PASS_COMPLETED_FIRST_AND_ONLY_FROZEN_ECONOMIC_EVALUATION",
        "FINAL_ECONOMIC_CLASSIFICATION": label,
        "CORE_NUMERICAL_REASON": core,
        "NEXT_RESEARCH_PRIORITY": next_priority,
        "RAW_A2_IDENTITY_STATUS": "PASS",
        "R2_PROTOCOL_HASH_STATUS": "PASS",
        "R2_CONTRACT_HASH_STATUS": "PASS",
        "STRUCTURAL_CLOSURE_STATUS": "PASS_STRUCTURAL_ACCOUNTING_CLOSED",
        "ECONOMIC_EVALUATION_MANIFEST_SHA256": manifest_sha,
        "ECONOMIC_CUTOFF": "2026-08-28", "LATEST_USED_SESSION": "2026-08-27", "POST_2026_08_28_OUTCOME_READ_COUNT": 0,
        "evidence_label": EVIDENCE_LABEL,
        "ANTI_DUPLICATION_AUDIT_STATUS": anti["ANTI_DUPLICATION_AUDIT_STATUS"],
        **{key: anti[key] for key in ["REUSE_PORTFOLIO_REPLAY", "REUSE_COST_ENGINE", "REUSE_METRIC_ENGINE", "REUSE_FACTOR_EXPOSURE_ENGINE", "REUSE_SECTOR_ATTRIBUTION_ENGINE"]},
        "NEW_BACKTESTER_CREATED": False, "NEW_COST_ENGINE_CREATED": False, "NEW_GENERIC_PORTFOLIO_ENGINE_CREATED": False,
        "full_window": {"RAW_A2": full_raw, "R2": full_r2}, "concentration": conc_summary,
        "factor_full": factor_table.loc[factor_table.window.eq("FULL_COMBINED")].to_dict("records"),
        "factor_all_windows": factor_table.to_dict("records"), "selection_quality": selection,
        "intervention_economics": intervention_summary, "yearly": yearly.to_dict("records"),
        "monthly": {"best_active_month": monthly.loc[monthly.active_return.idxmax()].to_dict(), "worst_active_month": monthly.loc[monthly.active_return.idxmin()].to_dict(), "top1_positive_month_share": top1_positive_month_share, "top3_positive_month_share": gates["top3_positive_month_share"]},
        "tail_test": tails, "drawdown": drawdowns.to_dict("records"), "classification_gates": gates,
        "replay_audit": {"pre2026": pre_audit, "2026": post_audit, "structural": structural_audit},
        "safety": {"SEARCH_COUNT_FOR_R2_RESCUE_VARIANTS": 0, "CANONICAL_REGISTRY_CHANGE": False, "RAW_A2_UNCHANGED": True, "PROSPECTIVE_A2_X0_PROTOCOL_UNTOUCHED": True, "TASK_OWNED_REPO_ROOT_TEMP_DIR_COUNT": 0},
    }
    daily.to_parquet(OUT / "daily_comparison.parquet", index=False, compression="zstd")
    yearly.to_csv(OUT / "yearly_metrics.csv", index=False, lineterminator="\n")
    monthly.to_csv(OUT / "monthly_active_metrics.csv", index=False, lineterminator="\n")
    intervention_table.to_csv(OUT / "intervention_economics.csv", index=False, lineterminator="\n")
    factor_table.to_csv(OUT / "factor_exposure_comparison.csv", index=False, lineterminator="\n")
    drawdowns.to_csv(OUT / "drawdown_comparison.csv", index=False, lineterminator="\n")
    write_json(OUT / "summary.json", summary)
    (OUT / "concise_report.md").write_text(concise_report(summary), encoding="utf-8")
    plot_outputs(daily, concentration, yearly, monthly)
    require(tree_snapshot(PROSPECTIVE)["tree_sha256"] == protected_before["prospective"]["tree_sha256"], "PROSPECTIVE_TREE_CHANGED")
    require(sha256_file(REGISTRY) == protected_before["registry_sha256"], "REGISTRY_CHANGED")
    require(not repo_temp_dirs(), "TASK_OWNED_REPO_TEMP", repo_temp_dirs())
    expected_files = {"anti_duplication_audit.json", "economic_evaluation_manifest.json", "daily_comparison.parquet", "yearly_metrics.csv", "monthly_active_metrics.csv", "intervention_economics.csv", "factor_exposure_comparison.csv", "drawdown_comparison.csv", "summary.json", "concise_report.md", "nav_comparison.png", "rolling_active_performance.png", "hhi_vs_performance_tradeoff.png", "yearly_return_risk_comparison.png"}
    require({p.name for p in OUT.iterdir() if p.is_file()} == expected_files, "ARTIFACT_SET", sorted(p.name for p in OUT.iterdir()))
    print(console(summary))


def self_test() -> None:
    sample = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=20), "raw_net_return": np.linspace(-.01, .01, 20), "r2_net_return": np.linspace(-.008, .009, 20), "raw_gross_return": np.linspace(-.009, .011, 20), "r2_gross_return": np.linspace(-.007, .010, 20), "raw_turnover": .1, "r2_turnover": .08, "raw_cost": .0001, "r2_cost": .00008})
    require(metrics(sample, "raw")["sessions"] == 20, "SELF_METRICS")
    require(tail_test(sample)["N_each"] == 2, "SELF_TAIL")
    print("SELF_TEST=PASS_NO_ECONOMIC_OUTCOME_READ")


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--freeze", action="store_true")
    group.add_argument("--evaluate", action="store_true")
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.freeze:
        freeze()
    elif args.evaluate:
        evaluate()
    else:
        self_test()


if __name__ == "__main__":
    main()
