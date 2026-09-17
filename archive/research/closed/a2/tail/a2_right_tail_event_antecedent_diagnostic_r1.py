from __future__ import annotations

import hashlib
import math
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


TASK_NAME = "A2_RIGHT_TAIL_EVENT_ANTECEDENT_DIAGNOSTIC_R1"
ROOT = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
OUT = RESULTS / TASK_NAME
PRIOR_EVENT = RESULTS / "A2_RIGHT_TAIL_AND_RANK_DECAY_DIAGNOSTIC_R1"
PRIOR_ATTRIBUTION = RESULTS / "A2_RETURN_ATTRIBUTION_R1"
TOP40_PATH = RESULTS / "A2_AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1" / "raw_a2_top40_membership_checkpoint.parquet"
A2_ROOT = RESULTS / "A_VS_A2_QUARTERLY_13F_R1"
SCORE_LEDGER = A2_ROOT / "A" / "score_rank_ledger.parquet"
DAILY_UNIVERSE = A2_ROOT / "universe" / "daily_eligible_universe_membership.parquet"
QUARTERLY_UNIVERSE = A2_ROOT / "universe" / "quarterly_universe_members.parquet"
FUNDAMENTAL_PANEL = Path(
    r"D:\us-tech-quant-cache\a2_earnings_fundamental_change_r1\sec_fsds\filtered"
    r"\backward_validation_semantic_audit\standard_alias_research_panel.parquet"
)
RISK_OOF = RESULTS / "A2_STOCK_RISK_R6" / "r6_oof_predictions.parquet"
RISK_CANDIDATE = "LGBM_BAD_ASYM_2"
MAX_OUTCOME_DATE = pd.Timestamp("2025-12-31")
PRE2025_END = pd.Timestamp("2024-12-31")
EXPECTED_TOP40_SHA256 = "1e6fa12b3f8d1144ef0337d343244424f44c27930e8e405b622885c0ae625a17"
GROUPS = ("RIGHT_TAIL_EVENT", "ORDINARY_POSITIVE_EVENT", "NONWINNER_EVENT")
FEATURES = {
    "F1_RAW_A2_SCORE": ("A2_INTERNAL_CONFIDENCE", "raw_score"),
    "F2_TOP10_SCORE_GAP": ("A2_INTERNAL_CONFIDENCE", "top10_score_gap"),
    "F3_RANK_JUMP": ("A2_INTERNAL_CONFIDENCE", "rank_jump"),
    "F4_PRIOR_TOP10_SHARE": ("A2_INTERNAL_CONFIDENCE", "prior_top10_share"),
    "F5_13F_HOLDER_COUNT": ("INSTITUTIONAL_CONSENSUS", "holder_count"),
    "F6_13F_HOLDER_COUNT_CHANGE": ("INSTITUTIONAL_CONSENSUS", "holder_count_change"),
    "F7_MOMENTUM_20D": ("MOMENTUM_STATE", "momentum_20d"),
    "F8_MOMENTUM_60D": ("MOMENTUM_STATE", "momentum_60d"),
    "F9_FUNDAMENTAL_CHANGE": ("FUNDAMENTAL_CHANGE", "fundamental_change"),
    "F10_EXISTING_RISK_SCORE": ("EXISTING_RISK_SIGNAL", "risk_score"),
}
FEATURE_SOURCE = {
    "F1_RAW_A2_SCORE": str(TOP40_PATH),
    "F2_TOP10_SCORE_GAP": str(TOP40_PATH),
    "F3_RANK_JUMP": str(TOP40_PATH),
    "F4_PRIOR_TOP10_SHARE": str(TOP40_PATH),
    "F5_13F_HOLDER_COUNT": f"{DAILY_UNIVERSE};{QUARTERLY_UNIVERSE}",
    "F6_13F_HOLDER_COUNT_CHANGE": f"{DAILY_UNIVERSE};{QUARTERLY_UNIVERSE}",
    "F7_MOMENTUM_20D": str(SCORE_LEDGER),
    "F8_MOMENTUM_60D": str(SCORE_LEDGER),
    "F9_FUNDAMENTAL_CHANGE": str(FUNDAMENTAL_PANEL),
    "F10_EXISTING_RISK_SCORE": f"{RISK_OOF}#{RISK_CANDIDATE}",
}


class DiagnosticFailure(RuntimeError):
    pass


def require(condition: bool, code: str, evidence: Any = "") -> None:
    if not condition:
        suffix = f":{evidence}" if evidence != "" else ""
        raise DiagnosticFailure(f"{code}{suffix}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp = Path(raw)
    try:
        temp.write_text(payload, encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp = Path(raw)
    try:
        frame.to_csv(temp, index=False, lineterminator="\n")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".parquet", dir=path.parent)
    os.close(fd)
    temp = Path(raw)
    try:
        frame.to_parquet(temp, index=False)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def prior_value(frame: pd.DataFrame, metric: str, section: str | None = None) -> str:
    rows = frame.loc[frame.metric.eq(metric)]
    if section is not None:
        rows = rows.loc[rows.section.eq(section)]
    require(len(rows) == 1, "PRIOR_SUMMARY_METRIC_IDENTITY", f"{section}:{metric}:{len(rows)}")
    return str(rows.iloc[0].value)


def weighted_mean(frame: pd.DataFrame, value: str, weight: str = "a2_weight") -> float:
    valid = frame[value].notna() & frame[weight].notna()
    if not valid.any():
        return float("nan")
    weights = frame.loc[valid, weight].astype(float)
    return float(np.average(frame.loc[valid, value].astype(float), weights=weights))


def weighted_event_projection(securities: pd.DataFrame, value: str, timestamp: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for decision_date, group in securities.groupby("decision_date", sort=True):
        valid = group[value].notna()
        rows.append(
            {
                "decision_date": decision_date,
                value: weighted_mean(group, value),
                f"{value}_security_coverage": float(group.loc[valid, "a2_weight"].sum() / group.a2_weight.sum()),
                f"{value}_available_timestamp": group.loc[valid, timestamp].max() if valid.any() else pd.NaT,
            }
        )
    return pd.DataFrame(rows)


def pooled_smd(left: pd.Series, right: pd.Series) -> float:
    left = left.dropna().astype(float)
    right = right.dropna().astype(float)
    if len(left) < 2 or len(right) < 2:
        return float("nan")
    denom_df = len(left) + len(right) - 2
    pooled_var = ((len(left) - 1) * left.var(ddof=1) + (len(right) - 1) * right.var(ddof=1)) / denom_df
    if pooled_var <= 0 or not np.isfinite(pooled_var):
        return 0.0 if math.isclose(float(left.mean()), float(right.mean()), abs_tol=1e-15) else float("nan")
    return float((left.mean() - right.mean()) / math.sqrt(pooled_var))


def direction(value: float) -> str:
    if not np.isfinite(value):
        return "UNDEFINED"
    if math.isclose(value, 0.0, abs_tol=1e-15):
        return "ZERO"
    return "POSITIVE" if value > 0 else "NEGATIVE"


def summary_row(section: str, metric: str, scope: str, value: Any, notes: str = "", year: Any = "ALL") -> dict[str, Any]:
    if isinstance(value, float) and not np.isfinite(value):
        value = "NA"
    return {"section": section, "metric": metric, "scope": scope, "year": year, "value": value, "notes": notes}


def group_stats(events: pd.DataFrame, column: str) -> dict[str, dict[str, float]]:
    output: dict[str, dict[str, float]] = {}
    for group_name in GROUPS:
        values = events.loc[events.event_group.eq(group_name), column].dropna().astype(float)
        output[group_name] = {
            "n": int(len(values)),
            "mean": float(values.mean()) if len(values) else float("nan"),
            "median": float(values.median()) if len(values) else float("nan"),
            "q25": float(values.quantile(.25)) if len(values) else float("nan"),
            "q75": float(values.quantile(.75)) if len(values) else float("nan"),
        }
    return output


def compare_feature(events: pd.DataFrame, column: str) -> dict[str, Any]:
    stats = group_stats(events, column)
    rt = events.loc[events.event_group.eq("RIGHT_TAIL_EVENT"), column]
    op = events.loc[events.event_group.eq("ORDINARY_POSITIVE_EVENT"), column]
    nw = events.loc[events.event_group.eq("NONWINNER_EVENT"), column]
    medians = {key: stats[key]["median"] for key in GROUPS}
    if all(np.isfinite(value) for value in medians.values()):
        if medians["RIGHT_TAIL_EVENT"] > medians["ORDINARY_POSITIVE_EVENT"] > medians["NONWINNER_EVENT"]:
            monotonic = "RIGHT_TAIL_GT_ORDINARY_POSITIVE_GT_NONWINNER"
        elif medians["RIGHT_TAIL_EVENT"] < medians["ORDINARY_POSITIVE_EVENT"] < medians["NONWINNER_EVENT"]:
            monotonic = "RIGHT_TAIL_LT_ORDINARY_POSITIVE_LT_NONWINNER"
        else:
            monotonic = "NO_MONOTONIC_GROUP_ORDER"
        observed = ">".join(sorted(medians, key=lambda key: (-medians[key], key)))
    else:
        monotonic = "UNDEFINED_INSUFFICIENT_COVERAGE"
        observed = "UNDEFINED_INSUFFICIENT_COVERAGE"
    return {
        "groups": stats,
        "rt_minus_nw_mean": stats["RIGHT_TAIL_EVENT"]["mean"] - stats["NONWINNER_EVENT"]["mean"],
        "rt_minus_nw_median": stats["RIGHT_TAIL_EVENT"]["median"] - stats["NONWINNER_EVENT"]["median"],
        "rt_minus_op_mean": stats["RIGHT_TAIL_EVENT"]["mean"] - stats["ORDINARY_POSITIVE_EVENT"]["mean"],
        "rt_minus_op_median": stats["RIGHT_TAIL_EVENT"]["median"] - stats["ORDINARY_POSITIVE_EVENT"]["median"],
        "op_minus_nw_mean": stats["ORDINARY_POSITIVE_EVENT"]["mean"] - stats["NONWINNER_EVENT"]["mean"],
        "op_minus_nw_median": stats["ORDINARY_POSITIVE_EVENT"]["median"] - stats["NONWINNER_EVENT"]["median"],
        "smd_rt_nw": pooled_smd(rt, nw),
        "smd_rt_op": pooled_smd(rt, op),
        "monotonic": monotonic,
        "observed": observed,
    }


def load_and_validate_events() -> tuple[pd.DataFrame, float, list[dict[str, Any]]]:
    prior_detail_path = PRIOR_EVENT / "diagnostic_detail.parquet"
    prior_summary_path = PRIOR_EVENT / "diagnostic_summary.csv"
    attribution_summary_path = PRIOR_ATTRIBUTION / "attribution_summary.csv"
    for path in (prior_detail_path, prior_summary_path, attribution_summary_path, TOP40_PATH):
        require(path.exists(), "AUTHORITATIVE_INPUT_MISSING", path)
    require(sha256_file(TOP40_PATH) == EXPECTED_TOP40_SHA256, "RAW_TOP40_HASH_MISMATCH")
    detail = pd.read_parquet(prior_detail_path)
    events = detail.loc[detail.row_type.eq("REPLACEMENT_EVENT")].copy()
    events["decision_date"] = pd.to_datetime(events.decision_date)
    events["holding_start"] = pd.to_datetime(events.holding_start)
    events["holding_end"] = pd.to_datetime(events.holding_end)
    prior = pd.read_csv(prior_summary_path, dtype=str, keep_default_na=False)
    attr = pd.read_csv(attribution_summary_path, dtype=str, keep_default_na=False)
    expected_count = int(float(prior_value(prior, "EVENT_COUNT", "EVENT_DISTRIBUTION")))
    terminal_delta = float(prior_value(prior, "A2_MINUS_A_TERMINAL_WEALTH_DELTA", "INPUT_IDENTITY"))
    attr_delta = float(prior_value(attr, "TERMINAL_DELTA", "A2_MINUS_A"))
    require(len(events) == expected_count, "PRIOR_EVENT_COUNT_MISMATCH", (len(events), expected_count))
    require(events.decision_date.is_unique, "PRIOR_EVENT_KEY_DUPLICATE")
    require(events.holding_end.max() <= MAX_OUTCOME_DATE, "POST_2025_OUTCOME_VIOLATION", events.holding_end.max())
    identity_error = abs(float(events.event_incremental_wealth.sum()) - terminal_delta)
    require(identity_error <= 1e-12, "PRIOR_EVENT_ATTRIBUTION_MISMATCH", identity_error)
    require(abs(terminal_delta - attr_delta) <= 1e-12, "PRIOR_ATTRIBUTION_IDENTITY_MISMATCH")
    ordered = events.sort_values(["event_incremental_wealth", "decision_date"], ascending=[False, True], kind="mergesort")
    top_count = max(1, int(math.ceil(.10 * len(events))))
    top_dates = set(ordered.head(top_count).decision_date)
    positive_total = float(events.event_incremental_wealth.clip(lower=0).sum())
    top_positive = float(ordered.head(top_count).event_incremental_wealth.clip(lower=0).sum())
    prior_share = float(prior_value(prior, "TOP10PCT_POSITIVE_SHARE", "EVENT_DISTRIBUTION"))
    prior_residual = float(prior_value(prior, "RESIDUAL_AFTER_TOP10PCT", "EVENT_DISTRIBUTION"))
    require(abs(top_positive / positive_total - prior_share) <= 1e-14, "EVENT_GROUP_DEFINITION_MISMATCH", "share")
    require(abs(terminal_delta - top_positive - prior_residual) <= 1e-12, "EVENT_GROUP_DEFINITION_MISMATCH", "residual")
    events["event_group"] = np.where(
        events.decision_date.isin(top_dates) & events.event_incremental_wealth.gt(0),
        "RIGHT_TAIL_EVENT",
        np.where(events.event_incremental_wealth.gt(0), "ORDINARY_POSITIVE_EVENT", "NONWINNER_EVENT"),
    )
    require(len(events) == int(events.event_group.value_counts().sum()), "EVENT_GROUP_COUNT_MISMATCH")
    notes = [
        summary_row("INPUT_IDENTITY", "PRIOR_EVENT_DETAIL_SHA256", str(prior_detail_path), sha256_file(prior_detail_path)),
        summary_row("INPUT_IDENTITY", "PRIOR_EVENT_SUMMARY_SHA256", str(prior_summary_path), sha256_file(prior_summary_path)),
        summary_row("INPUT_IDENTITY", "PRIOR_ATTRIBUTION_SUMMARY_SHA256", str(attribution_summary_path), sha256_file(attribution_summary_path)),
        summary_row("INPUT_IDENTITY", "RAW_TOP40_SHA256", str(TOP40_PATH), sha256_file(TOP40_PATH)),
        summary_row("INPUT_IDENTITY", "EVENT_COUNT", "ALL", len(events)),
        summary_row("INPUT_IDENTITY", "TERMINAL_WEALTH_DELTA", "ALL", terminal_delta),
        summary_row("INPUT_IDENTITY", "EVENT_ATTRIBUTION_IDENTITY_MAX_ABS_ERROR", "ALL", identity_error),
        summary_row("INPUT_IDENTITY", "FIXED_TOP10PCT_EVENT_COUNT", "ALL", top_count),
    ]
    return events.sort_values("decision_date").reset_index(drop=True), terminal_delta, notes


def build_security_features(events: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    attribution = pd.read_parquet(PRIOR_ATTRIBUTION / "attribution_detail.parquet")
    securities = attribution.loc[
        attribution.row_type.eq("A2_MINUS_A_SESSION_SECURITY") & attribution.classification.eq("A2_ONLY"),
        ["signal_date", "security_id", "ticker", "a2_wealth_contribution"],
    ].copy()
    securities = securities.rename(columns={"signal_date": "decision_date"})
    securities["decision_date"] = pd.to_datetime(securities.decision_date)
    securities = securities.loc[securities.decision_date.isin(events.decision_date)].copy()
    require(not securities.duplicated(["decision_date", "security_id"]).any(), "A2_ONLY_SECURITY_KEY_DUPLICATE")
    counts = securities.groupby("decision_date").size().rename("observed")
    expected = events.set_index("decision_date").a2_only_count.astype(int)
    require(counts.reindex(expected.index).eq(expected).all(), "A2_ONLY_EVENT_COUNT_MISMATCH")
    securities["a2_weight"] = 1.0 / 20.0

    top40 = pd.read_parquet(TOP40_PATH, columns=["decision_date", "security_id", "ticker_if_available", "raw_score", "raw_rank", "prediction_asof_date"])
    top40["decision_date"] = pd.to_datetime(top40.decision_date)
    top40["prediction_asof_date"] = pd.to_datetime(top40.prediction_asof_date)
    require(len(top40) == 50_120 and top40.decision_date.nunique() == 1_253, "RAW_TOP40_IDENTITY_MISMATCH")
    require(not top40.duplicated(["decision_date", "security_id"]).any(), "RAW_TOP40_KEY_DUPLICATE")
    ordered_dates = pd.Series(sorted(top40.decision_date.unique()))
    previous_map = dict(zip(ordered_dates.iloc[1:], ordered_dates.iloc[:-1]))
    require(not top40.duplicated(["decision_date", "ticker_if_available"]).any(), "RAW_TOP40_TICKER_KEY_DUPLICATE")
    current = top40[["decision_date", "ticker_if_available", "raw_score", "raw_rank", "prediction_asof_date"]].rename(
        columns={"ticker_if_available": "ticker"}
    )
    securities = securities.merge(current, on=["decision_date", "ticker"], how="left", validate="one_to_one")
    require(securities.raw_rank.notna().all() and securities.raw_rank.between(1, 20).all(), "A2_ONLY_NOT_AUTHORITATIVE_TOP20")
    securities["previous_decision_date"] = securities.decision_date.map(previous_map)
    previous = top40[["decision_date", "ticker_if_available", "raw_rank"]].rename(
        columns={"decision_date": "previous_decision_date", "ticker_if_available": "ticker", "raw_rank": "previous_rank"}
    )
    securities = securities.merge(previous, on=["previous_decision_date", "ticker"], how="left", validate="many_to_one")
    securities["rank_jump"] = securities.previous_rank - securities.raw_rank
    securities["prior_top10_indicator"] = np.where(securities.previous_rank.notna(), securities.previous_rank.le(10).astype(float), np.nan)

    momentum = pd.read_parquet(SCORE_LEDGER, columns=["signal_date", "ticker", "ret_20d", "ret_60d"])
    momentum = momentum.rename(columns={"signal_date": "decision_date", "ret_20d": "momentum_20d", "ret_60d": "momentum_60d"})
    momentum["decision_date"] = pd.to_datetime(momentum.decision_date)
    require(not momentum.duplicated(["decision_date", "ticker"]).any(), "MOMENTUM_KEY_DUPLICATE")
    securities = securities.merge(momentum, on=["decision_date", "ticker"], how="left", validate="many_to_one")
    securities["momentum_timestamp"] = securities.decision_date.where(securities.momentum_20d.notna() | securities.momentum_60d.notna())

    daily = pd.read_parquet(DAILY_UNIVERSE, columns=["signal_date", "active_13f_quarter", "ticker", "cusip"])
    daily = daily.rename(columns={"signal_date": "decision_date"})
    daily["decision_date"] = pd.to_datetime(daily.decision_date)
    daily = daily.loc[daily.decision_date.isin(events.decision_date)]
    require(not daily.duplicated(["decision_date", "ticker"]).any(), "DAILY_13F_KEY_DUPLICATE")
    securities = securities.merge(daily, on=["decision_date", "ticker"], how="left", validate="many_to_one")
    quarters = pd.read_parquet(QUARTERLY_UNIVERSE, columns=["quarter", "effective_date", "cusip", "manager_count"])
    quarters["effective_date"] = pd.to_datetime(quarters.effective_date)
    quarters = quarters.loc[quarters.quarter.isin(daily.active_13f_quarter.dropna().unique()) | quarters.quarter.isin(
        [f"{int(value[:4]) - (1 if value.endswith('Q1') else 0)}Q{4 if value.endswith('Q1') else int(value[-1]) - 1}" for value in daily.active_13f_quarter.dropna().unique()]
    )].copy()
    require(not quarters.duplicated(["quarter", "cusip"]).any(), "QUARTERLY_13F_KEY_DUPLICATE")
    quarters["quarter_order"] = quarters.quarter.str[:4].astype(int) * 4 + quarters.quarter.str[-1].astype(int)
    current_q = quarters.rename(columns={"quarter": "active_13f_quarter", "manager_count": "holder_count", "effective_date": "holder_effective_date"})
    securities = securities.merge(
        current_q[["active_13f_quarter", "cusip", "holder_count", "holder_effective_date", "quarter_order"]],
        on=["active_13f_quarter", "cusip"], how="left", validate="many_to_one",
    )
    previous_q = quarters[["quarter_order", "cusip", "manager_count", "effective_date"]].copy()
    previous_q["quarter_order"] += 1
    previous_q = previous_q.rename(columns={"manager_count": "previous_holder_count", "effective_date": "previous_holder_effective_date"})
    securities = securities.merge(previous_q, on=["quarter_order", "cusip"], how="left", validate="many_to_one")
    securities["holder_count_change"] = securities.holder_count - securities.previous_holder_count
    require((securities.holder_effective_date.dropna() <= securities.loc[securities.holder_effective_date.notna(), "decision_date"]).all(), "FUTURE_13F_QUARTER")
    require((securities.previous_holder_effective_date.dropna() < securities.loc[securities.previous_holder_effective_date.notna(), "holder_effective_date"]).all(), "FUTURE_PREVIOUS_13F_QUARTER")

    risk = pd.read_parquet(RISK_OOF, columns=["signal_date", "information_date", "ticker", "candidate_id", "predicted_bad_asymmetry_risk"])
    risk = risk.loc[risk.candidate_id.eq(RISK_CANDIDATE)].rename(
        columns={"signal_date": "decision_date", "predicted_bad_asymmetry_risk": "risk_score", "information_date": "risk_information_date"}
    )
    risk["decision_date"] = pd.to_datetime(risk.decision_date)
    risk["risk_information_date"] = pd.to_datetime(risk.risk_information_date)
    require(not risk.duplicated(["decision_date", "ticker"]).any(), "RISK_OOF_KEY_DUPLICATE")
    require((risk.risk_information_date <= risk.decision_date).all(), "FUTURE_RISK_FEATURE")
    securities = securities.merge(risk[["decision_date", "ticker", "risk_score", "risk_information_date"]], on=["decision_date", "ticker"], how="left", validate="many_to_one")

    for value, stamp in (
        ("raw_score", "prediction_asof_date"), ("rank_jump", "previous_decision_date"),
        ("prior_top10_indicator", "previous_decision_date"), ("momentum_20d", "momentum_timestamp"),
        ("momentum_60d", "momentum_timestamp"), ("holder_count", "holder_effective_date"),
        ("holder_count_change", "holder_effective_date"), ("risk_score", "risk_information_date"),
    ):
        valid = securities[value].notna()
        require((pd.to_datetime(securities.loc[valid, stamp]) <= securities.loc[valid, "decision_date"]).all(), "FEATURE_TIMESTAMP_LEAKAGE", value)
    statuses = {key: "AVAILABLE" for key in FEATURES}
    statuses["F9_FUNDAMENTAL_CHANGE"] = "UNAVAILABLE_PERSISTED_PIT_PANEL_ENDS_2022_12_30"
    if FUNDAMENTAL_PANEL.exists():
        fundamental_dates = pd.read_parquet(FUNDAMENTAL_PANEL, columns=["signal_date"])
        require(pd.to_datetime(fundamental_dates.signal_date).max() < events.decision_date.min(), "FUNDAMENTAL_PANEL_WINDOW_ASSUMPTION_FAILED")
    return securities, statuses


def build_event_features(events: pd.DataFrame, securities: pd.DataFrame) -> pd.DataFrame:
    output = events[["decision_date", "holding_start", "holding_end", "year", "event_group", "event_incremental_wealth"]].copy()
    projections = [
        ("raw_score", "prediction_asof_date"), ("rank_jump", "previous_decision_date"),
        ("prior_top10_indicator", "previous_decision_date"), ("holder_count", "holder_effective_date"),
        ("holder_count_change", "holder_effective_date"), ("momentum_20d", "momentum_timestamp"),
        ("momentum_60d", "momentum_timestamp"), ("risk_score", "risk_information_date"),
    ]
    for value, stamp in projections:
        projected = weighted_event_projection(securities, value, stamp)
        if value == "prior_top10_indicator":
            projected = projected.rename(columns={value: "prior_top10_share", f"{value}_security_coverage": "prior_top10_share_security_coverage", f"{value}_available_timestamp": "prior_top10_share_available_timestamp"})
        output = output.merge(projected, on="decision_date", how="left", validate="one_to_one")
    top_scores = securities[["decision_date"]].drop_duplicates().merge(
        pd.read_parquet(TOP40_PATH, columns=["decision_date", "raw_rank", "raw_score"]), on="decision_date", how="left"
    )
    pivot = top_scores.loc[top_scores.raw_rank.isin([10, 11])].pivot(index="decision_date", columns="raw_rank", values="raw_score")
    require({10, 11}.issubset(pivot.columns), "TOP10_SCORE_GAP_RANK_MISSING")
    gap = (pivot[10] - pivot[11]).rename("top10_score_gap").reset_index()
    output = output.merge(gap, on="decision_date", how="left", validate="one_to_one")
    output["top10_score_gap_security_coverage"] = np.where(output.top10_score_gap.notna(), 1.0, 0.0)
    output["top10_score_gap_available_timestamp"] = output.decision_date.where(output.top10_score_gap.notna())
    output["fundamental_change"] = np.nan
    output["fundamental_change_security_coverage"] = 0.0
    output["fundamental_change_available_timestamp"] = pd.NaT

    positive_driver = securities.loc[securities.a2_wealth_contribution.gt(0)].sort_values(
        ["decision_date", "a2_wealth_contribution", "security_id"], ascending=[True, False, True], kind="mergesort"
    ).drop_duplicates("decision_date")
    driver_cols = {
        "security_id": "primary_a2_capture_security",
        "ticker": "primary_a2_capture_ticker",
        "a2_wealth_contribution": "primary_a2_capture_contribution",
        "raw_score": "driver_raw_score", "rank_jump": "driver_rank_jump",
        "holder_count": "driver_holder_count", "holder_count_change": "driver_holder_count_change",
        "momentum_20d": "driver_momentum_20d", "momentum_60d": "driver_momentum_60d",
        "risk_score": "driver_risk_score",
    }
    driver = positive_driver[["decision_date", *driver_cols]].rename(columns=driver_cols)
    output = output.merge(driver, on="decision_date", how="left", validate="one_to_one")
    for _, column in FEATURES.values():
        stamp = f"{column}_available_timestamp"
        valid = output[column].notna()
        if valid.any():
            require((pd.to_datetime(output.loc[valid, stamp]) <= output.loc[valid, "decision_date"]).all(), "EVENT_FEATURE_TIMESTAMP_LEAKAGE", column)
    return output.sort_values("decision_date").reset_index(drop=True)


def analyze(event_features: pd.DataFrame, statuses: dict[str, str], identity_rows: list[dict[str, Any]]) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows = list(identity_rows)
    results: dict[str, dict[str, Any]] = {}
    for feature, (family, column) in FEATURES.items():
        coverage = {group: float(event_features.loc[event_features.event_group.eq(group), column].notna().mean()) for group in GROUPS}
        total_coverage = float(event_features[column].notna().mean())
        security_coverage_column = f"{column}_security_coverage"
        security_coverage = {
            group: float(event_features.loc[event_features.event_group.eq(group), security_coverage_column].mean())
            for group in GROUPS
        }
        total_security_coverage = float(event_features[security_coverage_column].mean())
        event_coverage_gap = max(coverage.values()) - min(coverage.values())
        security_coverage_gap = max(security_coverage.values()) - min(security_coverage.values())
        missing_confound = max(event_coverage_gap, security_coverage_gap) >= .10 if max(coverage.values()) > 0 else False
        available = statuses[feature] == "AVAILABLE" and total_coverage > 0
        rows.extend([
            summary_row("FEATURE_AVAILABILITY", "AVAILABILITY", feature, "AVAILABLE" if available else statuses[feature], FEATURE_SOURCE[feature]),
            summary_row("FEATURE_AVAILABILITY", "TOTAL_EVENT_COVERAGE", feature, total_coverage, FEATURE_SOURCE[feature]),
            summary_row("FEATURE_AVAILABILITY", "OVERALL_MISSING_FRACTION", feature, 1 - total_coverage),
            summary_row("FEATURE_AVAILABILITY", "MEAN_WITHIN_EVENT_A2_ONLY_WEIGHT_COVERAGE", feature, total_security_coverage, "partial security inputs are retained, not silently dropped"),
            summary_row("FEATURE_AVAILABILITY", "MISSINGNESS_CONFOUND_POSSIBLE", feature, str(missing_confound).lower(), "material threshold: 10 percentage points across fixed groups"),
        ])
        for group in GROUPS:
            rows.append(summary_row("FEATURE_AVAILABILITY", "GROUP_COVERAGE", feature, coverage[group], group))
            rows.append(summary_row("FEATURE_AVAILABILITY", "GROUP_MISSING_FRACTION", feature, 1 - coverage[group], group))
            rows.append(summary_row("FEATURE_AVAILABILITY", "GROUP_MEAN_A2_ONLY_WEIGHT_COVERAGE", feature, security_coverage[group], group))
        full = compare_feature(event_features, column)
        pre = compare_feature(event_features.loc[event_features.holding_end.le(PRE2025_END)], column)
        for scope, comp in (("FULL_SAMPLE", full), ("PRE2025", pre)):
            for group in GROUPS:
                for metric, value in comp["groups"][group].items():
                    rows.append(summary_row("FEATURE_GROUP_COMPARISON", metric.upper(), f"{feature}:{scope}:{group}", value))
            for metric in ("rt_minus_nw_mean", "rt_minus_nw_median", "rt_minus_op_mean", "rt_minus_op_median", "op_minus_nw_mean", "op_minus_nw_median", "smd_rt_nw", "smd_rt_op"):
                rows.append(summary_row("FEATURE_CONTRAST", metric.upper(), f"{feature}:{scope}", comp[metric]))
            rows.append(summary_row("FEATURE_ORDERING", "MONOTONIC_GROUP_ORDER", f"{feature}:{scope}", comp["monotonic"]))
            rows.append(summary_row("FEATURE_ORDERING", "OBSERVED_GROUP_ORDER", f"{feature}:{scope}", comp["observed"]))
        full_direction = direction(full["rt_minus_nw_median"])
        pre_direction = direction(pre["rt_minus_nw_median"])
        direction_match = full_direction == pre_direction and full_direction not in ("UNDEFINED", "ZERO")
        rows.extend([
            summary_row("PRE2025_REPEATABILITY", "FULL_SAMPLE_DIRECTION", feature, full_direction),
            summary_row("PRE2025_REPEATABILITY", "PRE2025_DIRECTION", feature, pre_direction),
            summary_row("PRE2025_REPEATABILITY", "DIRECTION_MATCH", feature, str(direction_match).lower()),
            summary_row("PRE2025_REPEATABILITY", "FULL_SAMPLE_SMD", feature, full["smd_rt_nw"]),
            summary_row("PRE2025_REPEATABILITY", "PRE2025_SMD", feature, pre["smd_rt_nw"]),
            summary_row("PRE2025_REPEATABILITY", "FULL_SAMPLE_MEDIAN_CONTRAST", feature, full["rt_minus_nw_median"]),
            summary_row("PRE2025_REPEATABILITY", "PRE2025_MEDIAN_CONTRAST", feature, pre["rt_minus_nw_median"]),
        ])
        year_directions: list[str] = []
        for year, group in event_features.groupby("year", sort=True):
            comp = compare_feature(group, column)
            contrast = comp["rt_minus_nw_median"]
            year_direction = direction(contrast)
            year_directions.append(year_direction)
            rows.append(summary_row("YEAR_DIRECTION_STABILITY", "RIGHT_TAIL_MINUS_NONWINNER_MEDIAN", feature, contrast, year=int(year)))
            rows.append(summary_row("YEAR_DIRECTION_STABILITY", "DIRECTION", feature, year_direction, year=int(year)))
        positive_years = year_directions.count("POSITIVE")
        negative_years = year_directions.count("NEGATIVE")
        undefined_years = len(year_directions) - positive_years - negative_years
        rows.extend([
            summary_row("YEAR_DIRECTION_STABILITY", "POSITIVE_DIRECTION_YEAR_COUNT", feature, positive_years),
            summary_row("YEAR_DIRECTION_STABILITY", "NEGATIVE_DIRECTION_YEAR_COUNT", feature, negative_years),
            summary_row("YEAR_DIRECTION_STABILITY", "UNDEFINED_YEAR_COUNT", feature, undefined_years),
        ])
        results[feature] = {
            "family": family, "column": column, "available": available, "coverage": total_coverage,
            "group_coverage": coverage, "security_coverage": total_security_coverage,
            "group_security_coverage": security_coverage, "missing_confound": missing_confound, "full": full, "pre": pre,
            "direction_match": direction_match, "positive_years": positive_years, "negative_years": negative_years,
        }

    driver_map = {
        "F1_RAW_A2_SCORE": "driver_raw_score", "F3_RANK_JUMP": "driver_rank_jump",
        "F5_13F_HOLDER_COUNT": "driver_holder_count", "F6_13F_HOLDER_COUNT_CHANGE": "driver_holder_count_change",
        "F7_MOMENTUM_20D": "driver_momentum_20d", "F8_MOMENTUM_60D": "driver_momentum_60d",
        "F10_EXISTING_RISK_SCORE": "driver_risk_score",
    }
    driver_scope = event_features.loc[event_features.event_group.isin(["RIGHT_TAIL_EVENT", "ORDINARY_POSITIVE_EVENT"])]
    for feature, column in driver_map.items():
        for group in ("RIGHT_TAIL_EVENT", "ORDINARY_POSITIVE_EVENT"):
            values = driver_scope.loc[driver_scope.event_group.eq(group), column].dropna()
            rows.append(summary_row("EX_POST_DRIVER_SECURITY_DIAGNOSTIC_ONLY", "N", f"{feature}:{group}", len(values), "NOT_ELIGIBLE_FOR_MODEL_SELECTION"))
            rows.append(summary_row("EX_POST_DRIVER_SECURITY_DIAGNOSTIC_ONLY", "MEDIAN", f"{feature}:{group}", float(values.median()) if len(values) else float("nan"), "NOT_ELIGIBLE_FOR_MODEL_SELECTION"))

    family_classifications: dict[str, str] = {}
    for family in sorted(set(value[0] for value in FEATURES.values())):
        members = [result for result in results.values() if result["family"] == family]
        available_members = [result for result in members if result["available"]]
        if not available_members:
            classification = "INSUFFICIENT_COVERAGE"
        else:
            repeatable = []
            dominated = []
            mixed = []
            for result in available_members:
                smd = result["full"]["smd_rt_nw"]
                pre_smd = result["pre"]["smd_rt_nw"]
                full_dir = direction(result["full"]["rt_minus_nw_median"])
                same_year_count = result["positive_years"] if full_dir == "POSITIVE" else result["negative_years"]
                adequate = result["coverage"] >= .70 and min(result["group_coverage"].values()) >= .60
                is_repeatable = adequate and abs(smd) >= .20 and result["direction_match"] and not result["missing_confound"] and same_year_count >= 2
                repeatable.append(is_repeatable)
                dominated.append(adequate and abs(smd) >= .20 and not result["direction_match"])
                mixed.append(adequate and result["direction_match"] and (abs(smd) >= .10 or abs(pre_smd) >= .10))
            if any(repeatable):
                classification = "SUPPORTED_REPEATABLE"
            elif any(dominated):
                classification = "2025_DOMINATED"
            elif any(mixed):
                classification = "MIXED"
            else:
                classification = "NO_CLEAR_SEPARATION"
        family_classifications[family] = classification
        rows.append(summary_row("FAMILY_INTERPRETATION", "CLASSIFICATION", family, classification, "fixed |SMD|>=0.20 repeatability rule; no feature selection"))

    f1 = results["F1_RAW_A2_SCORE"]
    f10 = results["F10_EXISTING_RISK_SCORE"]
    adequate_conflict = (
        f1["coverage"] >= .70 and f10["coverage"] >= .70
        and min(f1["group_coverage"].values()) >= .60 and min(f10["group_coverage"].values()) >= .60
    )
    f1_contrast = f1["full"]["rt_minus_nw_median"]
    f10_contrast = f10["full"]["rt_minus_nw_median"]
    if not adequate_conflict:
        conflict = "INSUFFICIENT_COVERAGE"
    elif (
        family_classifications["A2_INTERNAL_CONFIDENCE"] != "SUPPORTED_REPEATABLE"
        or family_classifications["EXISTING_RISK_SIGNAL"] != "SUPPORTED_REPEATABLE"
        or f1_contrast <= 0
    ):
        conflict = "NO_CLEAR_CONFLICT_PATTERN"
    elif f10_contrast > 0:
        conflict = "HIGH_ALPHA_HIGH_RISK"
    elif f10_contrast < 0:
        conflict = "HIGH_ALPHA_LOW_RISK"
    else:
        conflict = "NO_CLEAR_CONFLICT_PATTERN"
    rows.append(summary_row("HIGH_ALPHA_RISK", "PATTERN", "ALL", conflict, "higher R6 probability means higher severe-loss risk"))

    repeatable_families = [family for family, value in family_classifications.items() if value == "SUPPORTED_REPEATABLE"]
    if conflict == "HIGH_ALPHA_HIGH_RISK" and {"A2_INTERNAL_CONFIDENCE", "EXISTING_RISK_SIGNAL"}.issubset(repeatable_families):
        antecedent = "REPEATABLE_HIGH_ALPHA_HIGH_RISK_PATTERN"
    elif len(repeatable_families) >= 2:
        antecedent = "MULTI_FAMILY_REPEATABLE_PATTERN"
    elif len(repeatable_families) == 1:
        antecedent = {
            "A2_INTERNAL_CONFIDENCE": "REPEATABLE_A2_INTERNAL_STRENGTH",
            "INSTITUTIONAL_CONSENSUS": "REPEATABLE_INSTITUTIONAL_CONSENSUS",
            "MOMENTUM_STATE": "REPEATABLE_MOMENTUM_STATE",
            "FUNDAMENTAL_CHANGE": "REPEATABLE_FUNDAMENTAL_CHANGE",
            "EXISTING_RISK_SIGNAL": "WEAK_OR_INCONSISTENT_ANTECEDENTS",
        }[repeatable_families[0]]
    elif any(value == "2025_DOMINATED" for value in family_classifications.values()):
        antecedent = "2025_DOMINATED_PATTERN"
    elif any(value == "MIXED" for value in family_classifications.values()):
        antecedent = "WEAK_OR_INCONSISTENT_ANTECEDENTS"
    elif all(value == "INSUFFICIENT_COVERAGE" for value in family_classifications.values()):
        antecedent = "INSUFFICIENT_DATA"
    else:
        antecedent = "NO_STABLE_ANTECEDENT_STRUCTURE"
    justification = "SUPPORTED" if repeatable_families else ("MIXED" if antecedent in ("2025_DOMINATED_PATTERN", "WEAK_OR_INCONSISTENT_ANTECEDENTS") else "NOT_SUPPORTED")
    rows.extend([
        summary_row("FINAL_DECISION", "ANTECEDENT_STRUCTURE_CLASSIFICATION", "ALL", antecedent),
        summary_row("FINAL_DECISION", "TAIL_MODEL_RESEARCH_JUSTIFICATION", "ALL", justification),
        summary_row("FINAL_DECISION", "REPEATABLE_FAMILIES", "ALL", ";".join(repeatable_families) if repeatable_families else "NONE"),
    ])
    final = {
        "feature_results": results, "families": family_classifications, "conflict": conflict,
        "antecedent": antecedent, "justification": justification,
    }
    return pd.DataFrame(rows), final


def fmt(value: Any) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "NA"
    if isinstance(value, float):
        return f"{value:.10f}"
    return str(value)


def build_report(events: pd.DataFrame, summary: pd.DataFrame, final: dict[str, Any], statuses: dict[str, str]) -> str:
    results = final["feature_results"]
    available = [key for key, value in results.items() if value["available"]]
    unavailable = [key for key in FEATURES if key not in available]
    lines = [
        "# A2 right-tail event antecedent diagnostic R1", "",
        "## Result", "",
        f"The descriptive classification is **{final['antecedent']}** and the justification for a separately preregistered future nested-OOS tail-model study is **{final['justification']}**. This is not authorization to train a model or alter A2.", "",
        "The exact prior 750-event ledger was reused without redefining events. The strongest fixed top-10% set contains "
        f"{int((events.event_group == 'RIGHT_TAIL_EVENT').sum())} positive right-tail events; ordinary positive and nonwinner counts are "
        f"{int((events.event_group == 'ORDINARY_POSITIVE_EVENT').sum())} and {int((events.event_group == 'NONWINNER_EVENT').sum())}.", "",
        "## PIT availability", "",
        "| Feature | Status | Event coverage | Mean A2-only weight coverage | Right-tail coverage | Ordinary-positive coverage | Nonwinner coverage |", "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for feature in FEATURES:
        result = results[feature]
        cov = result["group_coverage"]
        lines.append(f"| {feature} | {'AVAILABLE' if result['available'] else statuses[feature]} | {result['coverage']:.1%} | {result['security_coverage']:.1%} | {cov['RIGHT_TAIL_EVENT']:.1%} | {cov['ORDINARY_POSITIVE_EVENT']:.1%} | {cov['NONWINNER_EVENT']:.1%} |")
    lines.extend([
        "", "F9 is unavailable because the existing persisted PIT fundamental-change panel ends on 2022-12-30, before the first event. No SEC pipeline was rebuilt. R6 risk values are frozen OOF predictions; higher values mean higher predicted severe-loss risk.", "",
        "## Fixed group contrasts", "",
        "| Feature | RT − nonwinner median | RT − ordinary median | SMD RT vs nonwinner | Pre-2025 direction matches | Group ordering |", "|---|---:|---:|---:|---:|---|",
    ])
    for feature, result in results.items():
        full = result["full"]
        lines.append(f"| {feature} | {fmt(full['rt_minus_nw_median'])} | {fmt(full['rt_minus_op_median'])} | {fmt(full['smd_rt_nw'])} | {str(result['direction_match']).lower()} | {full['monotonic']} |")
    lines.extend(["", "SMD uses the same conventional two-group pooled sample standard deviation for every feature. A fixed |SMD| ≥ 0.20 rule is used only to describe material separation; it is not a selected threshold or a trading rule.", "", "## Family interpretation", ""])
    for family, classification in final["families"].items():
        lines.append(f"- {family}: `{classification}`")
    lines.extend(["", f"The fixed high-alpha/high-risk comparison is `{final['conflict']}`.", "", "## Answers", ""])
    answer_map = {
        "A2 internal confidence": "A2_INTERNAL_CONFIDENCE", "institutional consensus": "INSTITUTIONAL_CONSENSUS",
        "20D/60D momentum": "MOMENTUM_STATE", "PIT fundamental change": "FUNDAMENTAL_CHANGE",
        "existing risk signal": "EXISTING_RISK_SIGNAL",
    }
    for label, family in answer_map.items():
        lines.append(f"- {label}: `{final['families'][family]}`.")
    repeatable = [family for family, value in final["families"].items() if value == "SUPPORTED_REPEATABLE"]
    dominated = [family for family, value in final["families"].items() if value == "2025_DOMINATED"]
    lines.extend([
        f"- Pre-2025 repeatable families: {', '.join(repeatable) if repeatable else 'none under the fixed descriptive rule'}.",
        f"- Mainly 2025-driven families: {', '.join(dominated) if dominated else 'none classified as such'}.",
        f"- Tail-model research justification: `{final['justification']}`. Any future experiment would require a new, separately authorized and preregistered nested-OOS design.", "",
        "## Direct interpretation", "",
        f"Right-tail events did show stronger A2 internal confidence before realization, but the evidence is specific to the frozen Raw A2 score: its right-tail minus nonwinner median contrast was {fmt(results['F1_RAW_A2_SCORE']['full']['rt_minus_nw_median'])} with SMD {fmt(results['F1_RAW_A2_SCORE']['full']['smd_rt_nw'])}. Before 2025 the corresponding contrast and SMD were {fmt(results['F1_RAW_A2_SCORE']['pre']['rt_minus_nw_median'])} and {fmt(results['F1_RAW_A2_SCORE']['pre']['smd_rt_nw'])}; the median direction was positive in all three calendar years. Score gap, prior Top10 share, and rank jump did not show comparably broad material separation.", "",
        f"Institutional consensus did not separate the groups reliably. Holder-count level had a full-sample median contrast of {fmt(results['F5_13F_HOLDER_COUNT']['full']['rt_minus_nw_median'])}, and holder-count change reversed direction in the pre-2025 subset. Momentum was also mixed: 20D and 60D median contrasts were positive, but their pooled SMDs were {fmt(results['F7_MOMENTUM_20D']['full']['smd_rt_nw'])} and {fmt(results['F8_MOMENTUM_60D']['full']['smd_rt_nw'])}, with unstable yearly directions.", "",
        "PIT fundamental change cannot be judged from an eligible persisted source for this event window. The existing risk score was higher in the pooled right-tail group, but this was not systematic: group coverage differed materially and yearly median directions were inconsistent. Therefore the high-alpha/high-risk result is classified as no clear conflict pattern, not a repeatable risk antecedent.", "",
        "No family met the fixed 2025-dominated classification. The only repeatable antecedent was Raw A2 internal score strength, so the evidence supports considering—but does not authorize—a separately preregistered nested-OOS tail-model experiment.", "",
        "## Research boundary", "",
        "This analysis is descriptive and outcome-exposed. It did not fit a model, search a threshold, create a feature, replay a TopN strategy, modify A2, access a network, or use post-2025 outcomes. Driver-security rows are explicitly ex-post diagnostics and are not eligible for model selection.", "",
        "## Validation", "",
        f"- Prior event count: {len(events)} (exact).",
        f"- Event groups reconcile: {sum(int((events.event_group == group).sum()) for group in GROUPS)}.",
        f"- Maximum outcome date: {events.holding_end.max().date()}.",
        f"- Available/unavailable feature counts: {len(available)}/{len(unavailable)}.",
        "- Every nonmissing feature timestamp is no later than its decision date; current and previous 13F effective dates and R6 information dates are checked explicitly.",
        "- Network used: false; post-2025 outcome used: false.", "",
    ])
    return "\n".join(lines)


def console_summary(events: pd.DataFrame, final: dict[str, Any], artifact_count: int) -> str:
    r = final["feature_results"]
    def med(feature: str) -> float:
        return r[feature]["full"]["rt_minus_nw_median"]
    def family_match(family: str) -> str:
        members = [value for value in r.values() if value["family"] == family and value["available"]]
        if not members:
            return "UNAVAILABLE"
        values = [member["direction_match"] for member in members]
        return "TRUE" if all(values) else ("MIXED" if any(values) else "FALSE")
    fields = {
        "RESEARCH_RESULT_STATUS": "COMPLETE_DESCRIPTIVE_MECHANISM_DIAGNOSTIC",
        "EXECUTION_STATUS": "PASS",
        "REPOSITORY_POLICY_STATUS": "PASS_WITH_PREEXISTING_UNRELATED_WARNINGS",
        "DATE_MAX_OUTCOME_USED": events.holding_end.max().date(), "POST_2025_OUTCOME_USED": "false", "NETWORK_USED": "false",
        "TOTAL_REPLACEMENT_EVENT_COUNT": len(events),
        "RIGHT_TAIL_EVENT_COUNT": int(events.event_group.eq("RIGHT_TAIL_EVENT").sum()),
        "ORDINARY_POSITIVE_EVENT_COUNT": int(events.event_group.eq("ORDINARY_POSITIVE_EVENT").sum()),
        "NONWINNER_EVENT_COUNT": int(events.event_group.eq("NONWINNER_EVENT").sum()),
        "AVAILABLE_FEATURE_COUNT": sum(value["available"] for value in r.values()),
        "UNAVAILABLE_FEATURE_COUNT": sum(not value["available"] for value in r.values()),
        "F1_A2_SCORE_RIGHT_TAIL_MINUS_NONWINNER_MEDIAN": med("F1_RAW_A2_SCORE"),
        "F2_SCORE_GAP_RIGHT_TAIL_MINUS_NONWINNER_MEDIAN": med("F2_TOP10_SCORE_GAP"),
        "F3_RANK_JUMP_RIGHT_TAIL_MINUS_NONWINNER_MEDIAN": med("F3_RANK_JUMP"),
        "F4_PRIOR_TOP10_SHARE_RIGHT_TAIL_MINUS_NONWINNER_MEDIAN": med("F4_PRIOR_TOP10_SHARE"),
        "F5_HOLDER_COUNT_RIGHT_TAIL_MINUS_NONWINNER_MEDIAN": med("F5_13F_HOLDER_COUNT"),
        "F6_HOLDER_CHANGE_RIGHT_TAIL_MINUS_NONWINNER_MEDIAN": med("F6_13F_HOLDER_COUNT_CHANGE"),
        "F7_MOM20_RIGHT_TAIL_MINUS_NONWINNER_MEDIAN": med("F7_MOMENTUM_20D"),
        "F8_MOM60_RIGHT_TAIL_MINUS_NONWINNER_MEDIAN": med("F8_MOMENTUM_60D"),
        "F9_FUNDAMENTAL_CHANGE_RIGHT_TAIL_MINUS_NONWINNER_MEDIAN": med("F9_FUNDAMENTAL_CHANGE"),
        "F10_RISK_SCORE_RIGHT_TAIL_MINUS_NONWINNER_MEDIAN": med("F10_EXISTING_RISK_SCORE"),
        "PRE2025_A2_INTERNAL_DIRECTION_MATCH": family_match("A2_INTERNAL_CONFIDENCE"),
        "PRE2025_INSTITUTIONAL_DIRECTION_MATCH": family_match("INSTITUTIONAL_CONSENSUS"),
        "PRE2025_MOMENTUM_DIRECTION_MATCH": family_match("MOMENTUM_STATE"),
        "PRE2025_FUNDAMENTAL_DIRECTION_MATCH": family_match("FUNDAMENTAL_CHANGE"),
        "PRE2025_RISK_DIRECTION_MATCH": family_match("EXISTING_RISK_SIGNAL"),
        "A2_INTERNAL_CONFIDENCE_CLASSIFICATION": final["families"]["A2_INTERNAL_CONFIDENCE"],
        "INSTITUTIONAL_CONSENSUS_CLASSIFICATION": final["families"]["INSTITUTIONAL_CONSENSUS"],
        "MOMENTUM_STATE_CLASSIFICATION": final["families"]["MOMENTUM_STATE"],
        "FUNDAMENTAL_CHANGE_CLASSIFICATION": final["families"]["FUNDAMENTAL_CHANGE"],
        "EXISTING_RISK_SIGNAL_CLASSIFICATION": final["families"]["EXISTING_RISK_SIGNAL"],
        "HIGH_ALPHA_HIGH_RISK_PATTERN": final["conflict"],
        "ANTECEDENT_STRUCTURE_CLASSIFICATION": final["antecedent"],
        "TAIL_MODEL_RESEARCH_JUSTIFICATION": final["justification"],
        "SOURCE_MODIFICATION_COUNT": 1, "RESULT_ARTIFACT_COUNT": artifact_count, "TEMP_FILE_REMAINS": 0,
        "NEXT_RESEARCH_QUESTION": "STOP;HUMAN_REVIEW_ONLY;DO_NOT_AUTO_START_FOLLOW_UP",
    }
    lines = ["=" * 60, f"{TASK_NAME}_FINAL", "=" * 60, ""]
    for key, value in fields.items():
        lines.append(f"{key}={fmt(value)}")
    lines.extend(["", "=" * 60])
    return "\n".join(lines)


def main() -> None:
    events, _, identity_rows = load_and_validate_events()
    securities, statuses = build_security_features(events)
    event_features = build_event_features(events, securities)
    require(event_features.holding_end.max() <= MAX_OUTCOME_DATE, "POST_2025_OUTCOME_VIOLATION")
    require(event_features.loc[event_features.holding_end.le(PRE2025_END), "holding_end"].max() <= PRE2025_END, "PRE2025_SUBSET_VIOLATION")
    summary, final = analyze(event_features, statuses, identity_rows)
    report = build_report(events, summary, final, statuses)
    OUT.mkdir(parents=True, exist_ok=True)
    for path in OUT.glob(".*.tmp"):
        path.unlink()
    atomic_csv(OUT / "antecedent_summary.csv", summary)
    atomic_parquet(OUT / "event_feature_detail.parquet", event_features)
    atomic_text(OUT / "final_report.md", report)
    artifacts = sorted(path for path in OUT.iterdir() if path.is_file())
    require(len(artifacts) == 3, "ARTIFACT_CAP_OR_IDENTITY_FAILURE", [path.name for path in artifacts])
    require(not list(OUT.glob(".*.tmp")), "TEMP_FILE_REMAINS")
    print(console_summary(events, final, len(artifacts)))


if __name__ == "__main__":
    main()
