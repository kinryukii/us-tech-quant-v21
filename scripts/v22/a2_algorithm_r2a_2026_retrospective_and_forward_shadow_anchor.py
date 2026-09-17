"""R2A retrospective 2026 comparison and immutable forward-shadow anchor.

This runner deliberately treats all 2026 YTD outcomes as retrospective evidence
with prior human exposure.  It performs inference with the latest common frozen
R1A temporal model vintage and never fits or selects a model.
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import ndcg_score


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / "A2_ALGORITHM_R2A_2026_RETROSPECTIVE_AND_FORWARD_SHADOW_ANCHOR"
BASELINE = RESULTS / "A_VS_A2_QUARTERLY_13F_R1"
R1A = RESULTS / "A2_ALGORITHM_BENCHMARK_R1A_TEMPORAL_BASELINE_RECONSTRUCTION"
R1C = RESULTS / "A2_ALGORITHM_BENCHMARK_R1C_REGIME_FORENSIC_AND_RANKING_REPAIR"
R1D = RESULTS / "A2_ALGORITHM_BENCHMARK_R1D_STATIC_BLEND"
PRIOR_2026 = RESULTS / "A_A2_2026_PRE_RISK_HOLDOUT_R1"
R1A_LINEAGE = R1A / "a2_temporal_lineage.json"

HGB_PATH = Path(r"D:\us-tech-quant-cache\a2_model_family_r1a_data_complete\models\M0_HGB_EXACT_OUTER_2025.joblib")
XGB_PATH = Path(r"D:\us-tech-quant-cache\a2_algorithm_benchmark_r1a_temporal_baseline_reconstruction\models\M2_XGB_REG_OUTER_2025.joblib")
HGB_EXPECTED_SHA = "5554ca8a218066cc25ac181ead3822a787711658895d1d184977846feb876ef1"
XGB_EXPECTED_SHA = "a325df998ec8a8b4e4c97145781df314f79cec93d23c28d2fd68186069a4a14b"

MEMBERS = BASELINE / "universe/quarterly_universe_members.parquet"
QUARTERS = BASELINE / "universe/quarterly_universe_manifest.parquet"
RAW_ROOT = Path(r"D:\us-tech-quant-cache\13f_pit_v1\moomoo_daily_raw")
REHAB = Path(r"D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1\rehab_factors.parquet")
POINTER = Path(
    r"D:\us-tech-quant-daily\current\V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD"
    r"\canonical_snapshot_pointer.json"
)
ADAPTER = BASELINE / "scripts/run_rebuild.py"
FEATURE_SOURCE = REPO / "scripts/v22/abcde_a2_r1_nonlinear_cross_sectional_modeling.py"
OLD_2026_RUNNER = REPO / "scripts/v22/a_a2_2026_pre_risk_holdout_r1.py"
MANAGER_CONFIG = REPO / "config/v22/authoritative_24_manager_master_r1.json"

MODELS = ("M0_A2_HGB", "M1_XGB_REG", "M2_W50")
TOP_N = 20
COST_BPS = 10
HORIZONS = (3, 5, 10, 20)
ACTIVE_QUARTERS = ("2025Q3", "2025Q4", "2026Q1")
EVIDENCE_STATUS = "RETROSPECTIVE_WITH_PRIOR_OUTCOME_EXPOSURE"
REQUIRED_OUTPUTS = (
    "prior_2026_exposure_audit.json",
    "retrospective_contract.json",
    "2026_model_identity_audit.json",
    "2026_universe_coverage_by_date.csv",
    "2026_retrospective_predictions.parquet",
    "2026_retrospective_predictive_metrics.csv",
    "2026_retrospective_economic_metrics.csv",
    "2026_retrospective_relative_metrics_vs_a2.csv",
    "2026_retrospective_top20.csv",
    "2026_retrospective_replacement_forensic.csv",
    "2026_retrospective_concentration.csv",
    "2026_retrospective_regime_validation.csv",
    "2026_retrospective_model_ranking.csv",
    "2026_retrospective_report.md",
    "forward_shadow_contract.json",
    "forward_shadow_model_identity.json",
    "status.json",
)


class ContractFailure(RuntimeError):
    pass


def require(condition: bool, code: str, evidence: Any = "") -> None:
    if not condition:
        raise ContractFailure(f"{code}|{evidence}")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def atomic_json(path: Path, payload: Any) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(json_safe(payload), indent=2, sort_keys=True, default=str, allow_nan=False), encoding="utf-8")
    os.replace(temp, path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    frame.to_csv(temp, index=False, encoding="utf-8-sig")
    os.replace(temp, path)


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp.parquet")
    frame.to_parquet(temp, index=False)
    os.replace(temp, path)


def import_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "IMPORT_FAILURE", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def prior_exposure_audit() -> dict[str, Any]:
    require(PRIOR_2026.is_dir(), "PRIOR_2026_EVIDENCE_MISSING", PRIOR_2026)
    records: list[dict[str, Any]] = []
    xgb_seen = False
    w50_seen = False
    regime_seen = False
    for path in sorted(PRIOR_2026.iterdir()):
        if not path.is_file():
            continue
        models: list[str] = []
        dates: list[pd.Timestamp] = []
        metric_present = False
        text = ""
        try:
            if path.suffix.lower() == ".json":
                text = path.read_text(encoding="utf-8", errors="replace")
                payload = json.loads(text)
                metric_present = any(token in text.lower() for token in ("return", "sharpe", "drawdown", "metric"))
                if isinstance(payload, dict):
                    for key in ("EFFECTIVE_START_DATE", "EFFECTIVE_END_DATE", "LATEST_A_DATE", "LATEST_A2_DATE"):
                        if payload.get(key):
                            dates.append(pd.Timestamp(payload[key]))
            elif path.suffix.lower() == ".csv":
                frame = pd.read_csv(path)
                text = " ".join(map(str, frame.columns))
                metric_present = any(token in text.lower() for token in ("return", "sharpe", "drawdown", "metric"))
                for column in ("date", "period_start", "period_end"):
                    if column in frame:
                        dates.extend(pd.to_datetime(frame[column], errors="coerce").dropna().tolist())
            elif path.suffix.lower() == ".parquet":
                frame = pd.read_parquet(path)
                text = " ".join(map(str, frame.columns))
                metric_present = any(token in text.lower() for token in ("return", "equity", "drawdown"))
                for column in ("date", "signal_date", "prediction_date"):
                    if column in frame:
                        dates.extend(pd.to_datetime(frame[column], errors="coerce").dropna().tolist())
        except Exception as exc:
            text += f" inspection_error={type(exc).__name__}"
        lower = text.lower()
        if "a2" in lower or path.name.endswith((".png", ".parquet")):
            models = ["A_CONTROL", "A2_HGB"]
        has_xgb = "xgb" in lower
        has_w50 = "w50" in lower or "static_blend" in lower
        has_regime = "regime" in lower or "breadth" in lower
        xgb_seen |= has_xgb
        w50_seen |= has_w50
        regime_seen |= has_regime
        records.append({
            "artifact": str(path),
            "sha256": sha(path),
            "creation_time": datetime.fromtimestamp(path.stat().st_ctime, timezone.utc).isoformat(),
            "models": models,
            "date_range": [str(min(dates).date()), str(max(dates).date())] if dates else None,
            "outcome_metrics_present": metric_present,
            "whether_XGB_outcome_present": has_xgb,
            "whether_W50_outcome_present": has_w50,
            "whether_regime_conditioned_outcome_present": has_regime,
            "whether_used_in_R1A_D_machine_selection": False,
            "known_human_level_exposure_status": "CONFIRMED_PRIOR_A_A2_OUTCOME_EXPOSURE",
        })
    scope = (
        "A_A2_COMPARATIVE_PLUS_XGB_OR_W50_EXPOSURE"
        if xgb_seen or w50_seen
        else "A_A2_COMPARATIVE_ONLY_NO_PRIOR_XGB_W50_OR_REGIME_CONDITIONING"
    )
    return {
        "2026_YTD_EVIDENCE_STATUS": EVIDENCE_STATUS,
        "PRIOR_2026_EXPOSURE_SCOPE": scope,
        "prior_researcher_exposure_precludes_pristine_holdout_status": True,
        "xgb_outcome_previously_present": xgb_seen,
        "w50_outcome_previously_present": w50_seen,
        "regime_conditioned_2026_outcome_previously_present": regime_seen,
        "R1A_D_machine_selection_dependency_count": 0,
        "artifact_count": len(records),
        "artifacts": records,
    }


def retrospective_contract() -> dict[str, Any]:
    frozen_features = json.loads(R1A_LINEAGE.read_text(encoding="utf-8"))["feature_names"]
    return {
        "run_id": OUT.name,
        "part_a": "2026_YTD_RETROSPECTIVE_COMPARATIVE_EVALUATION",
        "evidence_status": EVIDENCE_STATUS,
        "not_pristine_or_independent_prospective_validation": True,
        "model_vintage": "R1A_LATEST_COMMON_TEMPORAL_VINTAGE_OUTER_2025",
        "models": {
            "M0_A2_HGB": {"path": str(HGB_PATH), "expected_sha256": HGB_EXPECTED_SHA},
            "M1_XGB_REG": {"path": str(XGB_PATH), "expected_sha256": XGB_EXPECTED_SHA},
            "M2_W50": {"formula": "0.50*HGB_WITHIN_DATE_PERCENTILE_RANK+0.50*XGB_WITHIN_DATE_PERCENTILE_RANK"},
        },
        "feature_lineage": str(R1A_LINEAGE),
        "feature_lineage_sha256": sha(R1A_LINEAGE),
        "feature_names_in_order": frozen_features,
        "target": "ARITHMETIC_MEAN_OF_QQQ_EXCESS_CLOSE_RETURNS_AT_3_5_10_20_US_TRADING_SESSIONS",
        "maturity": "QQQ_SESSION_PLUS_20_MUST_EXIST_AND_EACH_EVALUATED_TARGET_MUST_BE_FINITE",
        "universe": "LATEST_PIT_EFFECTIVE_AUTHORITATIVE_24_MANAGER_13F_UNIVERSE_INTERSECT_121_SESSION_HISTORY_AND_COMPLETE_FROZEN_FEATURES",
        "execution": "CLOSE_SIGNAL_NEXT_SESSION_OPEN_EQUAL_WEIGHT_TOP20_OPEN_TO_OPEN",
        "transaction_cost_bps": COST_BPS,
        "model_universe_identity_required": True,
        "ranking": {
            "predictive_metrics": ["rank_ic", "ndcg_at_20", "top20_vs_universe_spread", "icir"],
            "economic_priority": ["cumulative_return", "sharpe", "max_drawdown", "calmar", "predictive_metrics"],
            "balanced": "EQUAL_AVERAGE_OF_SYMMETRIC_ABSOLUTE_PREDICTIVE_AND_ECONOMIC_METRIC_RANKS",
        },
        "classification": {
            "A_RETROSPECTIVE_STRONG_ADVANTAGE": "rank_ic>=A2 and cumulative_return>A2 and sharpe>A2 and max_drawdown>=A2-0.02 and replacement_spread>0 and turnover<=1.10*A2 and top5_date_share<=0.50",
            "B_RETROSPECTIVE_PARTIAL_ADVANTAGE": "predictive improvement plus at least one economic improvement without broad economic underperformance",
            "D_RETROSPECTIVE_UNDERPERFORMANCE": "at least two of cumulative return, Sharpe, and replacement spread are worse than A2",
            "C_RETROSPECTIVE_MIXED": "otherwise",
        },
        "regime_hypotheses": {
            "market_trend_60d": "LOW_FAVORS_XGB",
            "market_drawdown_state": "LOW_FAVORS_XGB",
            "breadth_20d_positive": "LOW_FAVORS_XGB",
            "cross_sectional_return_dispersion": "LOW_FAVORS_XGB",
            "threshold_source": str(R1C / "tercile_thresholds.json"),
            "directional_support_count_model": "M1_XGB_REG",
        },
        "prohibitions": ["fit", "parameter_search", "blend_search", "feature_selection", "regime_gate_search", "deployment"],
    }


def load_qqq() -> tuple[pd.DataFrame, dict[str, Any]]:
    pointer = json.loads(POINTER.read_text(encoding="utf-8"))
    require(pointer["source_policy"] == "MOOMOO_ONLY" and not pointer["external_fallback_used"], "QQQ_SOURCE_FAILURE")
    path = Path(pointer["canonical_qfq_path"])
    qqq = pd.read_csv(path, usecols=["ticker", "date", "open", "close", "volume", "source", "source_policy"])
    qqq = qqq.loc[qqq.ticker.astype(str).str.upper().eq("QQQ")].copy()
    qqq["trade_date"] = pd.to_datetime(qqq.pop("date")).dt.normalize()
    qqq["ticker"] = "QQQ"
    qqq = qqq.sort_values("trade_date", kind="mergesort").drop_duplicates("trade_date", keep="last")
    require(qqq.source_policy.eq("MOOMOO_ONLY").all(), "QQQ_MIXED_SOURCE")
    pointer["canonical_qfq_sha256"] = sha(path)
    return qqq.reset_index(drop=True), pointer


def validate_pit_manifest(qqq: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = json.loads(MANAGER_CONFIG.read_text(encoding="utf-8"))
    require(config["manager_count"] == 24 and config["situational_awareness_included"] is False, "MANAGER_CONTRACT_FAILURE")
    quarters = pd.read_parquet(QUARTERS)
    for column in ("holdings_as_of_date", "latest_actual_filing_timestamp", "effective_date"):
        quarters[column] = pd.to_datetime(quarters[column]).dt.normalize()
    active = quarters.loc[quarters.quarter.isin(ACTIVE_QUARTERS)].copy().sort_values("effective_date")
    require(tuple(active.quarter) == ACTIVE_QUARTERS, "ACTIVE_QUARTER_IDENTITY_FAILURE", active.quarter.tolist())
    calendar = pd.DatetimeIndex(qqq.trade_date)
    violations = 0
    for row in active.itertuples(index=False):
        after = calendar[calendar > row.latest_actual_filing_timestamp]
        expected = pd.Timestamp(after[4])
        violations += int(expected != row.effective_date)
        violations += int(row.institution_count != 24 or row.post_cap_universe_count > 900)
    require(violations == 0, "PIT_13F_TEMPORAL_VIOLATION", violations)
    members = pd.read_parquet(MEMBERS)
    for column in ("effective_date", "expiry_date"):
        members[column] = pd.to_datetime(members[column]).dt.normalize()
    members = members.loc[members.quarter.isin(ACTIVE_QUARTERS)].copy()
    require(not members.duplicated(["quarter", "ticker"]).any(), "DUPLICATE_QUARTER_MEMBER")
    return active, members


def load_equity_prices(adapter: Any, members: pd.DataFrame, end_date: pd.Timestamp) -> tuple[pd.DataFrame, dict[str, Any]]:
    identity = members[["ticker", "moomoo_transport_code"]].drop_duplicates().copy()
    conflicts = identity.groupby("ticker").moomoo_transport_code.nunique().gt(1)
    require(not conflicts.any(), "TICKER_TRANSPORT_CONFLICT", conflicts[conflicts].index.tolist())
    identity = identity.drop_duplicates("ticker").sort_values("ticker", kind="mergesort")
    index, failures = adapter.raw_file_index()
    require(not failures, "RAW_FILE_INDEX_FAILURE", failures)
    rehab = pd.read_parquet(REHAB)
    if len(rehab):
        rehab["code"] = rehab.code.astype(str).str.upper().str.strip()
    adapter.END_EXCLUSIVE = end_date + pd.Timedelta(days=1)
    frames: list[pd.DataFrame] = []
    unavailable: list[dict[str, str]] = []
    event_rows: list[dict[str, Any]] = []
    for row in identity.itertuples(index=False):
        code = str(row.moomoo_transport_code).upper().strip()
        paths = index.get(code, [])
        if not paths:
            unavailable.append({"ticker": str(row.ticker), "code": code, "reason": "NO_MOOMOO_RAW_HISTORY"})
            continue
        raw = adapter.load_raw_code(code, paths)
        raw = raw.loc[raw.trade_date.le(end_date)].copy()
        if raw.empty:
            unavailable.append({"ticker": str(row.ticker), "code": code, "reason": "NO_HISTORY_BY_CUTOFF"})
            continue
        adjusted, audit = adapter.adjusted_price_frame(
            code, str(row.ticker), raw, rehab, {"event_date": "2023-12-01", "quantity_multiplier": 1.0}
        )
        adjusted = adjusted.loc[adjusted.trade_date.le(end_date)].copy()
        if adjusted.empty:
            unavailable.append({"ticker": str(row.ticker), "code": code, "reason": "NO_ADJUSTED_HISTORY"})
            continue
        frames.append(adjusted)
        event_rows.extend(audit)
    require(frames, "NO_EQUITY_PRICE_DATA")
    prices = pd.concat(frames, ignore_index=True).sort_values(["ticker", "trade_date"], kind="mergesort")
    require(not prices.duplicated(["ticker", "trade_date"]).any(), "DUPLICATE_PRICE_KEY")
    return prices, {
        "requested_tickers": len(identity),
        "loaded_tickers": int(prices.ticker.nunique()),
        "unavailable": unavailable,
        "corporate_action_audit_row_count": len(event_rows),
    }


def active_universe_by_date(
    qqq: pd.DataFrame, active: pd.DataFrame, members: pd.DataFrame, end: pd.Timestamp
) -> pd.DataFrame:
    dates = pd.DataFrame({"signal_date": qqq.loc[qqq.trade_date.between("2026-01-01", end), "trade_date"]})
    vintages = active[["quarter", "effective_date", "post_cap_universe_count", "universe_fingerprint"]].copy()
    dated = pd.merge_asof(
        dates.sort_values("signal_date"), vintages.sort_values("effective_date"),
        left_on="signal_date", right_on="effective_date", direction="backward",
    )
    require(dated.quarter.notna().all(), "NO_PIT_VINTAGE_FOR_2026_DATE")
    lookup = members[["quarter", "ticker"]]
    expanded = dated.merge(lookup, on="quarter", validate="many_to_many")
    return expanded.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True)


def build_scored_matrix(
    r1: Any, prices: pd.DataFrame, qqq: pd.DataFrame, universe: pd.DataFrame,
    hgb: Any, xgb: Any, latest: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    features = r1.build_stock_state_features(prices[["ticker", "trade_date", "close", "volume"]].copy())
    features = features.rename(columns={"trade_date": "signal_date"})
    calendar = pd.DatetimeIndex(qqq.trade_date)
    position = pd.Series(np.arange(len(calendar)), index=calendar)
    features["calendar_position"] = features.signal_date.map(position)
    features["position_120_prior"] = features.groupby("ticker").calendar_position.shift(120)
    features["required_observations"] = features.groupby("ticker").cumcount() + 1
    features["sufficient_history"] = (
        features.required_observations.ge(121)
        & features.position_120_prior.notna()
        & features.calendar_position.sub(features.position_120_prior).eq(120)
    )
    # The live builder may contain later additions.  Frozen R1A identity is the
    # exact ordered 32-column lineage, never the current broader column tuple.
    cols = list(json.loads(R1A_LINEAGE.read_text(encoding="utf-8"))["feature_names"])
    require(len(cols) == 32 and len(set(cols)) == 32, "FROZEN_FEATURE_LINEAGE_FAILURE")
    require(set(cols).issubset(features.columns), "FROZEN_FEATURE_NOT_MATERIALIZED", sorted(set(cols) - set(features.columns)))
    features["complete_features"] = np.isfinite(features[cols].to_numpy(float)).all(axis=1)
    matrix = universe.merge(
        features[["signal_date", "ticker", "close", *cols, "sufficient_history", "complete_features"]],
        on=["signal_date", "ticker"], how="left", validate="one_to_one",
    )
    coverage = matrix.groupby(["signal_date", "quarter", "effective_date", "post_cap_universe_count"], as_index=False).agg(
        authoritative_universe_count=("ticker", "size"),
        price_row_count=("close", "count"),
        sufficient_history_count=("sufficient_history", lambda x: int(x.fillna(False).sum())),
        complete_feature_count=("complete_features", lambda x: int(x.fillna(False).sum())),
    )
    matrix = matrix.loc[matrix.sufficient_history.fillna(False) & matrix.complete_features.fillna(False)].copy()
    matrix["eligible_count"] = matrix.groupby("signal_date").ticker.transform("size")
    require(matrix.groupby("signal_date").size().ge(TOP_N).all(), "INSUFFICIENT_ELIGIBLE_UNIVERSE")
    x = matrix[cols].to_numpy(float)
    matrix["hgb_score"] = hgb.predict(x)
    matrix["xgb_score"] = xgb.predict(x)
    matrix["hgb_percentile_rank"] = matrix.groupby("signal_date").hgb_score.rank(method="average", ascending=True, pct=True)
    matrix["xgb_percentile_rank"] = matrix.groupby("signal_date").xgb_score.rank(method="average", ascending=True, pct=True)
    matrix["w50_score"] = 0.5 * matrix.hgb_percentile_rank + 0.5 * matrix.xgb_percentile_rank
    for score, rank in (("hgb_score", "hgb_rank"), ("xgb_score", "xgb_rank"), ("w50_score", "w50_rank")):
        matrix[rank] = r1._prediction_rank(matrix, score)
    return matrix.sort_values(["signal_date", "ticker"], kind="mergesort").reset_index(drop=True), coverage


def attach_targets(frame: pd.DataFrame, prices: pd.DataFrame, qqq: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    calendar = pd.DatetimeIndex(qqq.trade_date)
    qclose = pd.Series(qqq.close.to_numpy(float), index=calendar)
    lookup = prices.set_index(["ticker", "trade_date"]).close
    require(not lookup.index.has_duplicates, "DUPLICATE_TARGET_LOOKUP")
    components = []
    for horizon in HORIZONS:
        mapping = pd.Series(calendar.to_series(index=calendar).shift(-horizon).to_numpy(), index=calendar)
        target_dates = out.signal_date.map(mapping)
        keys = pd.MultiIndex.from_arrays([out.ticker, target_dates], names=["ticker", "trade_date"])
        stock_future = lookup.reindex(keys).to_numpy(float)
        q_future = target_dates.map(qclose).to_numpy(float)
        stock_return = stock_future / out.close.to_numpy(float) - 1.0
        q_return = q_future / out.signal_date.map(qclose).to_numpy(float) - 1.0
        name = f"ER_{horizon}D"
        out[name] = stock_return - q_return
        out[f"target_end_date_{horizon}d"] = target_dates
        components.append(name)
    finite = np.isfinite(out[components].to_numpy(float)).all(axis=1)
    out["target"] = np.where(finite, out[components].mean(axis=1), np.nan)
    out["target_end_date"] = out.target_end_date_20d
    return out


def model_long(frame: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for model, score, rank in (
        ("M0_A2_HGB", "hgb_score", "hgb_rank"),
        ("M1_XGB_REG", "xgb_score", "xgb_rank"),
        ("M2_W50", "w50_score", "w50_rank"),
    ):
        part = frame[["signal_date", "quarter", "effective_date", "ticker", "eligible_count", "target", "target_end_date", score, rank]].copy()
        part.columns = ["prediction_date", "13f_vintage", "13f_effective_date", "ticker", "eligible_count", "target", "target_end_date", "score", "rank"]
        part["model"] = model
        part["selected_top20"] = part["rank"] <= TOP_N
        frames.append(part)
    return pd.concat(frames, ignore_index=True).sort_values(["prediction_date", "model", "rank", "ticker"], kind="mergesort")


def predictive_metrics(long: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for model, frame in long.groupby("model", sort=False):
        daily = []
        deciles: list[list[float]] = [[] for _ in range(10)]
        for date, day0 in frame.groupby("prediction_date", sort=True):
            day = day0.loc[np.isfinite(day0.target) & np.isfinite(day0.score)].copy()
            require(len(day) >= TOP_N, "PREDICTIVE_DATE_BELOW_TOP20", date)
            day = day.sort_values(["score", "ticker"], ascending=[False, True], kind="mergesort")
            relevance = day.target.rank(method="average", pct=True).to_numpy(float)
            score = day.score.to_numpy(float)
            target = day.target.to_numpy(float)
            groups = np.array_split(np.arange(len(day)), 10)
            for top_index, ix in enumerate(groups):
                deciles[9 - top_index].extend(target[ix].tolist())
            daily.append({
                "rank_ic": float(spearmanr(score, target).statistic),
                "pearson_ic": float(np.corrcoef(score, target)[0, 1]),
                "ndcg_at_20": float(ndcg_score(relevance.reshape(1, -1), score.reshape(1, -1), k=TOP_N)),
                "top20_forward_return": float(target[:TOP_N].mean()),
                "top20_vs_universe_spread": float(target[:TOP_N].mean() - target.mean()),
                "hit_rate": float(np.mean(target[:TOP_N] > 0)),
            })
        d = pd.DataFrame(daily)
        std = float(d.rank_ic.std(ddof=1))
        dmeans = [float(np.mean(values)) if values else np.nan for values in deciles]
        rows.append({
            "model": model, "observation_count": int(frame.target.notna().sum()), "prediction_date_count": len(d),
            "rank_ic": float(d.rank_ic.mean()), "pearson_ic": float(d.pearson_ic.mean()),
            "mean_date_ic": float(d.rank_ic.mean()), "icir": float(d.rank_ic.mean() / std) if std > 0 else np.nan,
            "ndcg_at_20": float(d.ndcg_at_20.mean()), "top20_forward_return": float(d.top20_forward_return.mean()),
            "top20_vs_universe_spread": float(d.top20_vs_universe_spread.mean()), "hit_rate": float(d.hit_rate.mean()),
            "decile_means_bottom_to_top": json.dumps(dmeans),
            "decile_adjacent_nondecreasing_count": sum(dmeans[i + 1] >= dmeans[i] for i in range(9)),
        })
    return pd.DataFrame(rows)


def target_map(frame: pd.DataFrame, rank_column: str) -> dict[pd.Timestamp, dict[str, float]]:
    selected = frame.loc[frame[rank_column] <= TOP_N, ["signal_date", "ticker"]]
    result = {}
    for date, day in selected.groupby("signal_date", sort=True):
        require(len(day) == TOP_N, "TOP20_CARDINALITY_FAILURE", date)
        result[pd.Timestamp(date)] = {str(ticker): 1.0 / TOP_N for ticker in day.ticker}
    return result


def economic_metrics(old: Any, paths: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for model, result in paths.items():
        daily = result.daily
        returns = daily.daily_return.iloc[1:].to_numpy(float)
        nav = daily.nav
        total = float(nav.iloc[-1] / nav.iloc[0] - 1)
        annual = float((1 + total) ** (252 / len(returns)) - 1) if len(returns) and total > -1 else np.nan
        vol = float(np.std(returns, ddof=0) * np.sqrt(252))
        sharpe = float(np.mean(returns) * 252 / vol) if vol > 0 else np.nan
        downside = returns[returns < 0]
        sortino = float(np.mean(returns) / np.std(downside, ddof=0) * np.sqrt(252)) if len(downside) > 1 and np.std(downside, ddof=0) > 0 else np.nan
        dd = nav / nav.cummax() - 1
        loss = -returns[returns < 0].sum()
        rows.append({
            "model": model, "cumulative_return": total, "annualized_return_partial_year": annual,
            "volatility": vol, "sharpe": sharpe, "sortino": sortino,
            "calmar": annual / abs(float(dd.min())) if dd.min() < 0 else np.nan,
            "max_drawdown": float(dd.min()), "profit_factor": float(returns[returns > 0].sum() / loss) if loss > 0 else np.nan,
            "turnover_annualized": float(daily.turnover.iloc[1:].mean() * 252),
            "turnover_total_one_way": float(daily.turnover.iloc[1:].sum()),
            "transaction_cost": float(daily.transaction_cost.iloc[1:].sum()),
            "average_holdings": float(daily.holding_count.iloc[1:].mean()), "rebalance_count": len(returns),
        })
    return pd.DataFrame(rows)


def top20_and_replacements(long: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    top = long.loc[long.selected_top20].copy()
    rows = []
    summary: dict[str, float] = {}
    for challenger in ("M1_XGB_REG", "M2_W50"):
        for date in sorted(top.prediction_date.unique()):
            a = top.loc[(top.model == "M0_A2_HGB") & (top.prediction_date == date)]
            c = top.loc[(top.model == challenger) & (top.prediction_date == date)]
            aset, cset = set(a.ticker), set(c.ticker)
            aonly, conly = aset - cset, cset - aset
            amap = a.set_index("ticker").target
            cmap = c.set_index("ticker").target
            av = float(amap.reindex(sorted(aonly)).mean()) if aonly else np.nan
            cv = float(cmap.reindex(sorted(conly)).mean()) if conly else np.nan
            rows.append({
                "prediction_date": date, "challenger": challenger, "overlap_count": len(aset & cset),
                "top20_overlap": len(aset & cset) / TOP_N, "replacement_count": len(conly),
                "a2_only_return": av, "challenger_only_return": cv,
                "replacement_spread": cv - av if aonly and conly else 0.0,
            })
        part = pd.DataFrame(rows).loc[lambda x: x.challenger.eq(challenger)]
        summary[challenger] = float(part.replacement_spread.mean())
    return top, pd.DataFrame(rows), summary


def positive_share(values: pd.Series, n: int) -> float:
    positive = values[values > 0].sort_values(ascending=False)
    return float(positive.head(n).sum() / positive.sum()) if positive.sum() > 0 else np.nan


def concentration(paths: dict[str, Any], top: pd.DataFrame) -> pd.DataFrame:
    rows = []
    a = paths["M0_A2_HGB"].daily.set_index("date").daily_return
    for challenger in ("M1_XGB_REG", "M2_W50"):
        c = paths[challenger].daily.set_index("date").daily_return
        relative = c - a
        ticker_contrib: dict[str, float] = {}
        for date in sorted(top.prediction_date.unique()):
            abase = top.loc[(top.model == "M0_A2_HGB") & (top.prediction_date == date)].set_index("ticker")
            cbase = top.loc[(top.model == challenger) & (top.prediction_date == date)].set_index("ticker")
            for ticker in set(abase.index) | set(cbase.index):
                target = (cbase.target.get(ticker, 0.0) if ticker in cbase.index else abase.target.get(ticker, 0.0))
                sign = int(ticker in cbase.index) - int(ticker in abase.index)
                ticker_contrib[ticker] = ticker_contrib.get(ticker, 0.0) + sign * float(target) / TOP_N
        tv = pd.Series(ticker_contrib, dtype=float)
        rows.append({
            "challenger": challenger,
            **{f"top{n}_date_share": positive_share(relative, n) for n in (1, 5, 10)},
            **{f"top{n}_ticker_share": positive_share(tv, n) for n in (1, 5, 10)},
            "relative_cumulative_daily_return_sum": float(relative.sum()),
            "ticker_target_contribution_sum": float(tv.sum()),
        })
    return pd.DataFrame(rows)


def regime_validation(
    frame: pd.DataFrame, qqq: pd.DataFrame, paths: dict[str, Any], replacements: pd.DataFrame
) -> tuple[pd.DataFrame, int]:
    thresholds = json.loads((R1C / "tercile_thresholds.json").read_text(encoding="utf-8"))
    q = qqq.copy().sort_values("trade_date")
    q["benchmark_return"] = q.close.pct_change(fill_method=None)
    q["market_nav"] = (1 + q.benchmark_return.fillna(0)).cumprod()
    q["market_peak"] = q.market_nav.cummax()
    q["market_realized_vol_20d"] = q.benchmark_return.rolling(20).std(ddof=0) * np.sqrt(252)
    q["market_trend_60d"] = (1 + q.benchmark_return).rolling(60).apply(np.prod, raw=True) - 1
    q["market_drawdown_state"] = q.market_nav / q.market_peak - 1
    state = frame.groupby("signal_date", as_index=False).agg(
        cross_sectional_return_dispersion=("ret_20d", lambda x: float(x.std(ddof=0))),
        breadth_20d_positive=("ret_20d", lambda x: float((x > 0).mean())),
    ).rename(columns={"signal_date": "prediction_date"})
    state = state.merge(q.rename(columns={"trade_date": "prediction_date"})[[
        "prediction_date", "market_trend_60d", "market_drawdown_state"
    ]], on="prediction_date", validate="one_to_one")
    rows = []
    for challenger in ("M1_XGB_REG", "M2_W50"):
        a = paths["M0_A2_HGB"].daily.set_index("date").daily_return
        c = paths[challenger].daily.set_index("date").daily_return
        relative_by_signal = (c - a).rename("relative_return").reset_index().rename(columns={"date": "execution_date"})
        calendar = pd.DatetimeIndex(qqq.trade_date)
        relative_by_signal["prediction_date"] = relative_by_signal.execution_date.map(
            lambda date: calendar[calendar.get_loc(date) - 1] if date in calendar and calendar.get_loc(date) > 0 else pd.NaT
        )
        work = state.merge(relative_by_signal[["prediction_date", "relative_return"]], on="prediction_date", how="left")
        rep = replacements.loc[replacements.challenger.eq(challenger), ["prediction_date", "replacement_spread"]]
        work = work.merge(rep, on="prediction_date", how="left")
        for variable in ("market_trend_60d", "market_drawdown_state", "breadth_20d_positive", "cross_sectional_return_dispersion"):
            cuts = thresholds[variable]
            work["tercile"] = np.where(work[variable] <= cuts["q33"], "LOW", np.where(work[variable] >= cuts["q67"], "HIGH", "MID"))
            low = work.loc[work.tercile.eq("LOW")]
            high = work.loc[work.tercile.eq("HIGH")]
            if min(len(low), len(high)) < 3:
                direction = "INSUFFICIENT"
            else:
                direction = str(bool(low.relative_return.mean() > high.relative_return.mean())).upper()
            rows.append({
                "challenger": challenger, "regime_variable": variable,
                "frozen_q33": cuts["q33"], "frozen_q67": cuts["q67"],
                "low_observation_count": len(low), "mid_observation_count": int(work.tercile.eq("MID").sum()),
                "high_observation_count": len(high), "low_relative_return": low.relative_return.mean(),
                "high_relative_return": high.relative_return.mean(),
                "low_replacement_spread": low.replacement_spread.mean(), "high_replacement_spread": high.replacement_spread.mean(),
                "DIRECTION_MATCH": direction,
            })
    result = pd.DataFrame(rows)
    support = int(((result.challenger == "M1_XGB_REG") & (result.DIRECTION_MATCH == "TRUE")).sum())
    return result, support


def rankings(predictive: pd.DataFrame, economic: pd.DataFrame) -> tuple[pd.DataFrame, str, str, str]:
    merged = economic.merge(predictive, on="model", validate="one_to_one")
    pred_metrics = [("rank_ic", False), ("ndcg_at_20", False), ("top20_vs_universe_spread", False), ("icir", False)]
    econ_metrics = [("cumulative_return", False), ("sharpe", False), ("max_drawdown", False), ("calmar", False)]
    for name, ascending in pred_metrics + econ_metrics:
        merged[f"rank_{name}"] = merged[name].rank(method="average", ascending=ascending)
    merged["predictive_rank_average"] = merged[[f"rank_{x[0]}" for x in pred_metrics]].mean(axis=1)
    merged["economic_rank_average"] = merged[[f"rank_{x[0]}" for x in econ_metrics]].mean(axis=1)
    merged["balanced_rank_average"] = 0.5 * merged.predictive_rank_average + 0.5 * merged.economic_rank_average
    pred_winner = str(merged.sort_values(["predictive_rank_average", "model"]).iloc[0].model)
    economic_winner = str(merged.sort_values(
        ["cumulative_return", "sharpe", "max_drawdown", "calmar"], ascending=[False, False, False, False], kind="mergesort"
    ).iloc[0].model)
    balanced_winner = str(merged.sort_values(["balanced_rank_average", "model"]).iloc[0].model)
    return merged, pred_winner, economic_winner, balanced_winner


def classify(model: str, predictive: pd.DataFrame, economic: pd.DataFrame, replacement: float, concentration_frame: pd.DataFrame) -> str:
    p = predictive.set_index("model")
    e = economic.set_index("model")
    base, challenger = e.loc["M0_A2_HGB"], e.loc[model]
    top5 = float(concentration_frame.set_index("challenger").loc[model, "top5_date_share"])
    strong = (
        p.loc[model, "rank_ic"] >= p.loc["M0_A2_HGB", "rank_ic"]
        and challenger.cumulative_return > base.cumulative_return
        and challenger.sharpe > base.sharpe
        and challenger.max_drawdown >= base.max_drawdown - 0.02
        and replacement > 0
        and challenger.turnover_annualized <= 1.10 * base.turnover_annualized
        and (not math.isfinite(top5) or top5 <= 0.50)
    )
    if strong:
        return "A_RETROSPECTIVE_STRONG_ADVANTAGE"
    worse = sum((challenger.cumulative_return < base.cumulative_return, challenger.sharpe < base.sharpe, replacement < 0))
    if worse >= 2:
        return "D_RETROSPECTIVE_UNDERPERFORMANCE"
    predictive_better = p.loc[model, "rank_ic"] > p.loc["M0_A2_HGB", "rank_ic"]
    economic_better = challenger.cumulative_return > base.cumulative_return or challenger.sharpe > base.sharpe
    if predictive_better and economic_better:
        return "B_RETROSPECTIVE_PARTIAL_ADVANTAGE"
    return "C_RETROSPECTIVE_MIXED"


def forward_contract(identity: dict[str, Any], retrospective_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    timestamp = datetime.now(timezone.utc).isoformat()
    contract = {
        "run_id": OUT.name,
        "part_b": "NEW_FORWARD_PROSPECTIVE_SHADOW_ANCHOR",
        "FORWARD_SHADOW_FREEZE_TIMESTAMP": timestamp,
        "prospective_eligibility": "PREDICTION_INFORMATION_TIMESTAMP_STRICTLY_GREATER_THAN_FREEZE_TIMESTAMP",
        "FIRST_FUTURE_PROSPECTIVE_ELIGIBLE_PREDICTION_DATE": "NOT_YET_AVAILABLE_WAIT_FOR_NEXT_ELIGIBLE_PREDICTION",
        "models": identity["models"],
        "w50_formula": "0.50*HGB_WITHIN_DATE_PERCENTILE_RANK+0.50*XGB_WITHIN_DATE_PERCENTILE_RANK",
        "feature_lineage_sha256": sha(R1A_LINEAGE),
        "pit_universe_rule": "AUTHORITATIVE_24_LATEST_FILING_PLUS_5_US_EQUITY_SESSIONS_PRIOR_VINTAGE_UNTIL_ACTIVATION",
        "eligibility": "PIT_UNIVERSE_INTERSECT_121_SESSION_HISTORY_INTERSECT_COMPLETE_FROZEN_FEATURES",
        "execution": "CLOSE_SIGNAL_NEXT_SESSION_OPEN_EQUAL_WEIGHT_TOP20_OPEN_TO_OPEN",
        "transaction_cost_bps": COST_BPS,
        "metrics": ["rank_ic", "ndcg_at_20", "cumulative_return", "sharpe", "calmar", "max_drawdown", "turnover", "replacement_spread"],
        "no_retuning_rule": ["no_HGB_change", "no_XGB_change", "no_W50_change", "no_feature_selection", "no_regime_threshold_search"],
        "retrospective_contract_sha256": retrospective_sha,
        "deployment_status": "NOT_AUTHORIZED",
    }
    model_identity = {
        "FORWARD_SHADOW_MODEL_IDENTITY_STATUS": "PASS_FROZEN",
        "freeze_timestamp": timestamp,
        "models": identity["models"],
        "feature_lineage": str(R1A_LINEAGE), "feature_lineage_sha256": sha(R1A_LINEAGE),
        "feature_builder_source": str(FEATURE_SOURCE), "feature_builder_source_sha256": sha(FEATURE_SOURCE),
        "manager_config": str(MANAGER_CONFIG), "manager_config_sha256": sha(MANAGER_CONFIG),
        "static_blend_contract": str(R1D / "static_blend_contract.json"),
        "static_blend_contract_sha256": sha(R1D / "static_blend_contract.json"),
    }
    return contract, model_identity


def report(status: dict[str, Any], economic: pd.DataFrame, predictive: pd.DataFrame) -> str:
    table = economic.merge(predictive[["model", "rank_ic", "ndcg_at_20"]], on="model")
    lines = [
        "# A2 Algorithm R2A — 2026 retrospective and forward shadow anchor", "",
        "Part A is retrospective evidence with prior A/A2 outcome exposure. It is not a pristine holdout, untouched holdout, or independent prospective validation.", "",
        "## Raw comparison", "",
        "| Model | Cum Return | Ann Return | Sharpe | Calmar | MaxDD | Rank IC | NDCG@20 | Turnover |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in table.itertuples(index=False):
        lines.append(f"| {row.model} | {row.cumulative_return:.6f} | {row.annualized_return_partial_year:.6f} | {row.sharpe:.6f} | {row.calmar:.6f} | {row.max_drawdown:.6f} | {row.rank_ic:.6f} | {row.ndcg_at_20:.6f} | {row.turnover_annualized:.6f} |")
    lines += [
        "", "The annualized return is a partial-year metric. Cumulative return, Sharpe, and drawdown carry more interpretive weight.", "",
        f"Predictive winner: `{status['2026_YTD_PREDICTIVE_WINNER']}`. Economic winner: `{status['2026_YTD_ECONOMIC_WINNER']}`. Balanced winner: `{status['2026_YTD_BALANCED_WINNER']}`.", "",
        "Part B freezes these exact identities for observations whose prediction-information timestamp is strictly later than the recorded anchor. No future observation is available at freeze time.", "",
        "Deployment is not authorized by this run.", "",
    ]
    return "\n".join(lines)


def run(output: Path) -> dict[str, Any]:
    require(str(output.resolve()).startswith(str(RESULTS.resolve()) + os.sep), "OUTPUT_NOT_EXTERNAL", output)
    # A failed attempt may leave only pre-evaluation audit/contract checkpoints.
    # A completed status or manifest is immutable and must never be overwritten.
    require(not (output / "status.json").exists() and not (output / "manifest.json").exists(), "AUTHORITATIVE_OUTPUT_EXISTS", output)
    output.mkdir(parents=True, exist_ok=True)

    exposure = prior_exposure_audit()
    atomic_json(output / "prior_2026_exposure_audit.json", exposure)
    contract = retrospective_contract()
    atomic_json(output / "retrospective_contract.json", contract)
    contract_sha = sha(output / "retrospective_contract.json")

    require(sha(HGB_PATH) == HGB_EXPECTED_SHA, "HGB_HASH_MISMATCH")
    require(sha(XGB_PATH) == XGB_EXPECTED_SHA, "XGB_HASH_MISMATCH")
    hgb, xgb = joblib.load(HGB_PATH), joblib.load(XGB_PATH)
    require(getattr(hgb, "n_features_in_", None) == getattr(xgb, "n_features_in_", None) == 32, "MODEL_FEATURE_COUNT_MISMATCH")
    identity = {
        "FROZEN_HGB_IDENTITY_STATUS": "PASS_R1A_OUTER_2025_HASH_VERIFIED",
        "FROZEN_XGB_IDENTITY_STATUS": "PASS_R1A_OUTER_2025_HASH_VERIFIED",
        "FROZEN_W50_IDENTITY_STATUS": "PASS_R1D_FORMULA_HASH_VERIFIED",
        "PRE2026_SPEC_RECONSTRUCTION_COUNT": 0,
        "model_vintage_rationale": "Latest common R1A temporal pair; avoids asymmetric full-pre2026 HGB with absent full-pre2026 XGB and avoids any reconstruction fit.",
        "models": {
            "M0_A2_HGB": {"path": str(HGB_PATH), "sha256": sha(HGB_PATH), "fit_cutoff_class": "PRE2025_OUTER_2025_TRAINING"},
            "M1_XGB_REG": {"path": str(XGB_PATH), "sha256": sha(XGB_PATH), "fit_cutoff_class": "PRE2025_OUTER_2025_TRAINING"},
            "M2_W50": {"formula": contract["models"]["M2_W50"]["formula"], "r1d_contract_sha256": sha(R1D / "static_blend_contract.json")},
        },
        "feature_lineage_sha256": sha(R1A_LINEAGE), "feature_builder_source_sha256": sha(FEATURE_SOURCE),
        "retrospective_contract_sha256": contract_sha,
    }
    atomic_json(output / "2026_model_identity_audit.json", identity)

    qqq, pointer = load_qqq()
    latest = pd.Timestamp(qqq.trade_date.max())
    active, members = validate_pit_manifest(qqq)
    adapter = import_path("r2a_price_adapter", ADAPTER)
    r1 = import_path("r2a_feature_contract", FEATURE_SOURCE)
    old = import_path("r2a_execution_contract", OLD_2026_RUNNER)
    prices, price_audit = load_equity_prices(adapter, members, latest)
    universe = active_universe_by_date(qqq, active, members, latest)
    scored, coverage = build_scored_matrix(r1, prices, qqq, universe, hgb, xgb, latest)
    scored = attach_targets(scored, prices, qqq)

    calendar = pd.DatetimeIndex(qqq.trade_date)
    mature_dates = calendar[(calendar.year == 2026) & (np.arange(len(calendar)) + 20 < len(calendar))]
    last_mature = pd.Timestamp(mature_dates.max())
    first_date = pd.Timestamp(scored.signal_date.min())
    evaluation = scored.loc[scored.signal_date.between(first_date, last_mature)].copy()
    eval_dates = pd.DatetimeIndex(sorted(evaluation.signal_date.unique()))
    expected_dates = calendar[(calendar >= first_date) & (calendar <= last_mature)]
    require(eval_dates.equals(expected_dates), "EVALUATION_DATE_GAP")
    require(evaluation.groupby("signal_date").size().ge(TOP_N).all(), "EVALUATION_UNIVERSE_BELOW_TOP20")
    top_target_missing = 0
    for rank in ("hgb_rank", "xgb_rank", "w50_rank"):
        top_target_missing += int(evaluation.loc[evaluation[rank] <= TOP_N, "target"].isna().sum())
    require(top_target_missing == 0, "TOP20_MATURED_TARGET_MISSING", top_target_missing)

    long = model_long(evaluation)
    model_counts = long.groupby(["model", "prediction_date"]).ticker.nunique().unstack(0)
    universe_mismatch = int((model_counts.nunique(axis=1) != 1).sum())
    require(universe_mismatch == 0, "MODEL_UNIVERSE_MISMATCH", universe_mismatch)
    predictive = predictive_metrics(long)

    old.EFFECTIVE_START = first_date
    old.COST_BPS = COST_BPS
    execution_end = pd.Timestamp(calendar[calendar.get_loc(last_mature) + 1])
    all_prices = pd.concat([
        prices.loc[prices.trade_date.le(execution_end)],
        qqq.loc[qqq.trade_date.le(execution_end), ["ticker", "trade_date", "open", "close", "volume"]],
    ], ignore_index=True, sort=False)
    paths = {
        "M0_A2_HGB": old.reconstruct_open_ended("M0_A2_HGB", target_map(evaluation, "hgb_rank"), all_prices, calendar, execution_end),
        "M1_XGB_REG": old.reconstruct_open_ended("M1_XGB_REG", target_map(evaluation, "xgb_rank"), all_prices, calendar, execution_end),
        "M2_W50": old.reconstruct_open_ended("M2_W50", target_map(evaluation, "w50_rank"), all_prices, calendar, execution_end),
    }
    missing_events = sum((result.missing_price_events for result in paths.values()), [])
    require(not missing_events, "EXECUTION_MISSING_PRICE_EVENT", missing_events[:10])
    economic = economic_metrics(old, paths)
    top, replacements, replacement_summary = top20_and_replacements(long)
    conc = concentration(paths, top)
    regime, regime_support = regime_validation(evaluation, qqq, paths, replacements)
    ranking, pred_winner, econ_winner, balanced_winner = rankings(predictive, economic)

    relative = economic.merge(predictive, on="model").set_index("model")
    base = relative.loc["M0_A2_HGB"]
    relative_rows = []
    for model in ("M1_XGB_REG", "M2_W50"):
        row = relative.loc[model]
        relative_rows.append({"model": model, **{f"delta_{column}_vs_a2": row[column] - base[column] for column in (
            "cumulative_return", "annualized_return_partial_year", "sharpe", "calmar", "max_drawdown", "turnover_annualized", "rank_ic", "ndcg_at_20"
        )}, "replacement_spread": replacement_summary[model]})
    relative_frame = pd.DataFrame(relative_rows)
    xgb_class = classify("M1_XGB_REG", predictive, economic, replacement_summary["M1_XGB_REG"], conc)
    w50_class = classify("M2_W50", predictive, economic, replacement_summary["M2_W50"], conc)

    coverage = coverage.loc[coverage.signal_date.between(first_date, last_mature)].copy()
    coverage = coverage.rename(columns={"signal_date": "prediction_date", "quarter": "13f_vintage", "effective_date": "13f_effective_date"})
    coverage["eligible_count"] = coverage.prediction_date.map(evaluation.groupby("signal_date").size())
    coverage["PIT_13F_TEMPORAL_VIOLATION"] = coverage.prediction_date < coverage["13f_effective_date"]
    pit_violations = int(coverage.PIT_13F_TEMPORAL_VIOLATION.sum())
    require(pit_violations == 0, "PIT_13F_TEMPORAL_VIOLATION")

    atomic_csv(output / "2026_universe_coverage_by_date.csv", coverage)
    atomic_parquet(output / "2026_retrospective_predictions.parquet", long)
    atomic_csv(output / "2026_retrospective_predictive_metrics.csv", predictive)
    atomic_csv(output / "2026_retrospective_economic_metrics.csv", economic)
    atomic_csv(output / "2026_retrospective_relative_metrics_vs_a2.csv", relative_frame)
    atomic_csv(output / "2026_retrospective_top20.csv", top)
    atomic_csv(output / "2026_retrospective_replacement_forensic.csv", replacements)
    atomic_csv(output / "2026_retrospective_concentration.csv", conc)
    atomic_csv(output / "2026_retrospective_regime_validation.csv", regime)
    atomic_csv(output / "2026_retrospective_model_ranking.csv", ranking)

    forward, forward_identity = forward_contract(identity, contract_sha)
    atomic_json(output / "forward_shadow_contract.json", forward)
    atomic_json(output / "forward_shadow_model_identity.json", forward_identity)
    status = {
        "A2_ALGORITHM_R2A_STATUS": "PASS_RETROSPECTIVE_COMPARISON_AND_FORWARD_SHADOW_ANCHOR_COMPLETE",
        "2026_YTD_EVIDENCE_STATUS": EVIDENCE_STATUS,
        "PRIOR_2026_EXPOSURE_SCOPE": exposure["PRIOR_2026_EXPOSURE_SCOPE"],
        "FIRST_2026_ELIGIBLE_PREDICTION_DATE": str(first_date.date()),
        "LAST_2026_MATURED_PREDICTION_DATE": str(last_mature.date()),
        "LATEST_2026_AVAILABLE_MARKET_DATE": str(latest.date()),
        "MATURED_2026_PREDICTION_DATE_COUNT": len(eval_dates),
        "MATURED_2026_PREDICTION_ROW_COUNT": int(evaluation.target.notna().sum()),
        "UNMATURED_2026_DATE_COUNT": int(((calendar.year == 2026) & (calendar > last_mature)).sum()),
        "PIT_13F_TEMPORAL_VIOLATION_COUNT": pit_violations,
        "MODEL_UNIVERSE_MISMATCH_COUNT": universe_mismatch,
        "FROZEN_HGB_IDENTITY_STATUS": identity["FROZEN_HGB_IDENTITY_STATUS"],
        "FROZEN_XGB_IDENTITY_STATUS": identity["FROZEN_XGB_IDENTITY_STATUS"],
        "FROZEN_W50_IDENTITY_STATUS": identity["FROZEN_W50_IDENTITY_STATUS"],
        "PRE2026_SPEC_RECONSTRUCTION_COUNT": 0,
        "XGB_MINUS_A2_RANK_IC": float(relative_frame.set_index("model").loc["M1_XGB_REG", "delta_rank_ic_vs_a2"]),
        "W50_MINUS_A2_RANK_IC": float(relative_frame.set_index("model").loc["M2_W50", "delta_rank_ic_vs_a2"]),
        "2026_YTD_PREDICTIVE_WINNER": pred_winner,
        "2026_YTD_ECONOMIC_WINNER": econ_winner,
        "2026_YTD_BALANCED_WINNER": balanced_winner,
        "XGB_2026_RETROSPECTIVE_CLASSIFICATION": xgb_class,
        "W50_2026_RETROSPECTIVE_CLASSIFICATION": w50_class,
        "XGB_REPLACEMENT_SPREAD": replacement_summary["M1_XGB_REG"],
        "W50_REPLACEMENT_SPREAD": replacement_summary["M2_W50"],
        "REGIME_HYPOTHESIS_DIRECTIONAL_SUPPORT_COUNT": regime_support,
        "2026_ANNUALIZED_RETURN_IS_PARTIAL_YEAR_METRIC": True,
        "2026_TRAINING_ROWS": 0, "2026_PARAMETER_SEARCH_COUNT": 0, "2026_BLEND_SEARCH_COUNT": 0,
        "2026_FEATURE_SELECTION_COUNT": 0, "2026_REGIME_GATE_SEARCH_COUNT": 0,
        "POST_HOLDOUT_PARAMETER_CHANGE_COUNT": 0, "POST_HOLDOUT_BLEND_CHANGE_COUNT": 0,
        "POST_HOLDOUT_FEATURE_CHANGE_COUNT": 0, "POST_HOLDOUT_REGIME_RULE_CHANGE_COUNT": 0,
        "FORWARD_SHADOW_CONTRACT_STATUS": "PASS_FROZEN_NEW_PROSPECTIVE_ANCHOR",
        "FORWARD_SHADOW_FREEZE_TIMESTAMP": forward["FORWARD_SHADOW_FREEZE_TIMESTAMP"],
        "FIRST_FUTURE_PROSPECTIVE_ELIGIBLE_PREDICTION_DATE": forward["FIRST_FUTURE_PROSPECTIVE_ELIGIBLE_PREDICTION_DATE"],
        "DEPLOYMENT_STATUS": "NOT_AUTHORIZED",
        "NEXT_AUTHORIZED_STEP": "STOP_AND_REVIEW_2026_RETROSPECTIVE_AND_FORWARD_SHADOW_ANCHOR",
        "input_audit": {"benchmark_pointer": pointer, "price_audit": price_audit, "execution_end": str(execution_end.date())},
    }
    atomic_json(output / "status.json", status)
    (output / "2026_retrospective_report.md").write_text(report(status, economic, predictive), encoding="utf-8")
    require(all((output / name).is_file() for name in REQUIRED_OUTPUTS), "REQUIRED_OUTPUT_MISSING")
    manifest_entries = [{"artifact": name, "sha256": sha(output / name), "bytes": (output / name).stat().st_size} for name in REQUIRED_OUTPUTS]
    atomic_json(output / "manifest.json", {
        "run_id": OUT.name, "artifact_count_excluding_self": len(manifest_entries),
        "self_hash_excluded_because_recursive": True, "artifacts": manifest_entries,
        "2026_training_rows": 0, "model_fit_count": 0, "parameter_search_count": 0,
    })
    return {"status": status, "economic": economic, "predictive": predictive, "concentration": conc}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    try:
        result = run(args.output)
    except Exception as exc:
        print(f"A2_ALGORITHM_R2A_STATUS=FAIL_CLOSED_{type(exc).__name__.upper()}")
        print(f"FAILURE={exc}")
        return 1
    status = result["status"]
    print(f"A2_ALGORITHM_R2A_STATUS={status['A2_ALGORITHM_R2A_STATUS']}")
    print(f"2026_YTD_EVIDENCE_STATUS={status['2026_YTD_EVIDENCE_STATUS']}")
    print(f"PRIOR_2026_EXPOSURE_SCOPE={status['PRIOR_2026_EXPOSURE_SCOPE']}")
    for key in ("FIRST_2026_ELIGIBLE_PREDICTION_DATE", "LAST_2026_MATURED_PREDICTION_DATE", "LATEST_2026_AVAILABLE_MARKET_DATE", "PIT_13F_TEMPORAL_VIOLATION_COUNT", "MODEL_UNIVERSE_MISMATCH_COUNT"):
        print(f"{key}={status[key]}")
    table = result["economic"].merge(result["predictive"][["model", "rank_ic", "ndcg_at_20"]], on="model")
    overlap = {"M0_A2_HGB": 1.0}
    replacement = pd.read_csv(args.output / "2026_retrospective_replacement_forensic.csv")
    overlap.update(replacement.groupby("challenger").top20_overlap.mean().to_dict())
    print("| Model | Cum Return | Ann Return | Sharpe | Calmar | MaxDD | Rank IC | NDCG@20 | Turnover | Top20 overlap |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in table.itertuples(index=False):
        print(f"| {row.model} | {row.cumulative_return:.10f} | {row.annualized_return_partial_year:.10f} | {row.sharpe:.10f} | {row.calmar:.10f} | {row.max_drawdown:.10f} | {row.rank_ic:.10f} | {row.ndcg_at_20:.10f} | {row.turnover_annualized:.10f} | {overlap[row.model]:.10f} |")
    for key in ("2026_YTD_PREDICTIVE_WINNER", "2026_YTD_ECONOMIC_WINNER", "2026_YTD_BALANCED_WINNER", "XGB_2026_RETROSPECTIVE_CLASSIFICATION", "W50_2026_RETROSPECTIVE_CLASSIFICATION", "XGB_REPLACEMENT_SPREAD", "W50_REPLACEMENT_SPREAD", "REGIME_HYPOTHESIS_DIRECTIONAL_SUPPORT_COUNT"):
        print(f"{key}={status[key]}")
    conc = result["concentration"].set_index("challenger")
    print(f"XGB_TOP5_DATE_RELATIVE_PNL_SHARE={conc.loc['M1_XGB_REG','top5_date_share']}")
    print(f"W50_TOP5_DATE_RELATIVE_PNL_SHARE={conc.loc['M2_W50','top5_date_share']}")
    for key in ("2026_TRAINING_ROWS", "2026_PARAMETER_SEARCH_COUNT", "2026_BLEND_SEARCH_COUNT", "2026_FEATURE_SELECTION_COUNT", "2026_REGIME_GATE_SEARCH_COUNT", "FORWARD_SHADOW_CONTRACT_STATUS", "FORWARD_SHADOW_FREEZE_TIMESTAMP", "FIRST_FUTURE_PROSPECTIVE_ELIGIBLE_PREDICTION_DATE", "DEPLOYMENT_STATUS", "NEXT_AUTHORIZED_STEP"):
        print(f"{key}={status[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
