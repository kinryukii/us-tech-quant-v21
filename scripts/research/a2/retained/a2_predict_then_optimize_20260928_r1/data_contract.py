"""Frozen data interfaces for the TOP20 Predict-then-Optimize experiment.

Training functions can only open pre-2026 snapshots. Evaluation snapshots are
separate and expose no strategy outcome files. All sampling depends on keys.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "input"
SEED = 20260928
MAX_TRAIN_KEYS = 30000
TRAIN_CLIP = 0.20
FEATURES = (
    "ret_1d", "ret_3d", "ret_5d", "ret_10d", "ret_20d", "ret_40d", "ret_60d", "ret_120d",
    "price_vs_ma10", "price_vs_ma20", "price_vs_ma50", "price_vs_ma120",
    "ma10_vs_ma20", "ma20_vs_ma50", "ma50_vs_ma120", "realized_vol_5d", "realized_vol_10d",
    "realized_vol_20d", "realized_vol_60d", "downside_vol_20d", "upside_vol_20d",
    "distance_from_high_20d", "distance_from_high_60d", "distance_from_low_20d",
    "distance_from_low_60d", "max_drawdown_20d", "max_drawdown_60d", "avg_volume_20d",
    "avg_volume_60d", "volume_ratio_5d_20d", "volume_ratio_20d_60d", "avg_dollar_volume_20d",
)
STAGE_CUTOFFS = {
    "development": "2024-01-01", "validation": "2025-01-01", "final": "2026-01-01",
}
STAGE_ALIASES = {"early": "development"}
KEY = ["signal_date", "ticker"]


def sha256_file(path: str | Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require_schema(frame: pd.DataFrame, columns, *, name: str) -> None:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{name} missing required columns: {sorted(missing)}")


def validate_panel(frame: pd.DataFrame, *, name: str = "panel") -> None:
    require_schema(frame, [*KEY, *FEATURES, "new_buy_eligible"], name=name)
    if frame.empty or frame.duplicated(KEY).any():
        raise ValueError(f"{name} empty or duplicate signal/ticker keys")
    if frame[KEY].isna().any().any():
        raise ValueError(f"{name} missing signal/ticker keys")
    if not np.isfinite(frame[list(FEATURES)].to_numpy(float)).all():
        raise ValueError(f"{name} non-finite signal features")
    if not pd.api.types.is_bool_dtype(frame.new_buy_eligible) or frame.new_buy_eligible.isna().any():
        raise ValueError(f"{name} must have non-null boolean new-buy eligibility")


def validate_latest_effective(frame: pd.DataFrame, timing: pd.DataFrame, *, quarter_column: str) -> None:
    require_schema(frame, ["signal_date", quarter_column, "latest_filing_date", "quarter_effective_date"], name="13F panel")
    require_schema(timing, ["quarter", "latest_filing_date", "quarter_effective_date"], name="13F timing")
    q = timing.sort_values("quarter_effective_date").reset_index(drop=True)
    if q.quarter.duplicated().any() or q.quarter_effective_date.duplicated().any():
        raise ValueError("duplicate quarter timing")
    if q[["quarter", "latest_filing_date", "quarter_effective_date"]].isna().any().any():
        raise ValueError("missing quarter timing")
    if not q.latest_filing_date.lt(q.quarter_effective_date).all():
        raise ValueError("13F filing/effective clock impossible")
    dates = pd.to_datetime(frame.signal_date)
    index = np.searchsorted(q.quarter_effective_date.to_numpy(), dates.to_numpy(), side="right") - 1
    if (index < 0).any():
        raise ValueError("signal precedes first effective 13F quarter")
    if not np.array_equal(frame[quarter_column].astype(str).to_numpy(), q.quarter.astype(str).to_numpy()[index]):
        raise ValueError("signal does not use latest publicly filed and effective 13F quarter")
    for column in ["latest_filing_date", "quarter_effective_date"]:
        if not np.array_equal(pd.to_datetime(frame[column]).to_numpy(), q[column].to_numpy()[index]):
            raise ValueError(f"13F panel clock differs from timing: {column}")
    if not dates.gt(pd.to_datetime(frame.latest_filing_date)).all():
        raise ValueError("filing not public before signal")
    if not dates.ge(pd.to_datetime(frame.quarter_effective_date)).all():
        raise ValueError("future effective quarter")


def active_pool_quarter(timing: pd.DataFrame, signal_date, *, local_available: dict | None = None) -> str:
    """Publication/effectiveness governs switching; local absence never proves nonpublication."""
    require_schema(timing, ["quarter", "latest_filing_date", "quarter_effective_date"], name="13F timing")
    signal = pd.Timestamp(signal_date)
    eligible = timing.loc[
        pd.to_datetime(timing.latest_filing_date).lt(signal)
        & pd.to_datetime(timing.quarter_effective_date).le(signal)
    ].sort_values("quarter_effective_date")
    if eligible.empty:
        raise ValueError("no publicly filed and effective cohort at this signal")
    quarter = str(eligible.iloc[-1].quarter)
    if local_available is not None and not bool(local_available.get(quarter, False)):
        raise ValueError(f"INPUT_UNKNOWN_ALREADY_PUBLIC_EFFECTIVE_COHORT_LOCAL_MISSING: {quarter}")
    return quarter


def maturity_mask(frame: pd.DataFrame, cutoff: str) -> pd.Series:
    """The label's endpoint, as well as the observation, must be past-only."""
    require_schema(frame, [*KEY, "execution_date", "label_end_date", "label_available", "y_next_open"], name="training panel")
    if not pd.api.types.is_bool_dtype(frame.label_available) or frame.label_available.isna().any():
        raise ValueError("label_available must be a non-null boolean")
    signal = pd.to_datetime(frame.signal_date)
    execution = pd.to_datetime(frame.execution_date)
    endpoint = pd.to_datetime(frame.label_end_date)
    return (
        signal.lt(cutoff) & endpoint.lt(cutoff) & frame.label_available
        & np.isfinite(frame.y_next_open.to_numpy(float))
        & execution.gt(signal) & endpoint.gt(execution)
    )


def key_digest(signal_date, ticker: str, seed: int = SEED) -> str:
    payload = f"{seed}|{pd.Timestamp(signal_date).date().isoformat()}|{ticker}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def date_balanced_quotas(counts: pd.Series, budget: int = MAX_TRAIN_KEYS) -> pd.Series:
    """Equal date quotas, redistributing capacity when a date has fewer names."""
    counts = counts.sort_index().astype(int)
    if counts.empty or (counts <= 0).any():
        raise ValueError("each mature date must have at least one candidate")
    if budget < len(counts):
        raise ValueError("sampling budget cannot cover every mature date")
    quotas = pd.Series(0, index=counts.index, dtype=int)
    remaining = min(int(budget), int(counts.sum()))
    while remaining:
        capacity = counts - quotas
        active = capacity[capacity.gt(0)]
        if remaining < len(active):
            quotas.loc[active.index[:remaining]] += 1
            break
        increment = active.clip(upper=remaining // len(active))
        quotas.loc[active.index] += increment
        remaining -= int(increment.sum())
    if not quotas.gt(0).all() or int(quotas.sum()) != min(budget, int(counts.sum())):
        raise AssertionError("date-balanced quota construction failed")
    return quotas


def sample_training_keys(frame: pd.DataFrame, stage: str, *, budget: int = MAX_TRAIN_KEYS, seed: int = SEED) -> pd.DataFrame:
    stage = STAGE_ALIASES.get(stage, stage)
    if stage not in STAGE_CUTOFFS:
        raise ValueError(f"unknown training stage: {stage}")
    if frame.duplicated(KEY).any():
        raise ValueError("duplicate training keys")
    cutoff = STAGE_CUTOFFS[stage]
    mature = frame.loc[maturity_mask(frame, cutoff), KEY].copy()
    counts = mature.groupby("signal_date", sort=True).size()
    quotas = date_balanced_quotas(counts, budget)
    mature["sampling_sha256"] = [key_digest(d, str(t), seed) for d, t in mature[KEY].itertuples(index=False, name=None)]
    mature = mature.sort_values(["signal_date", "sampling_sha256", "ticker"], kind="stable")
    rank = mature.groupby("signal_date", sort=False).cumcount()
    selected = mature.loc[rank.lt(mature.signal_date.map(quotas))].copy()
    selected_counts = selected.groupby("signal_date").size()
    nrows, ndates = len(selected), len(selected_counts)
    selected["sample_weight"] = nrows / ndates / selected.signal_date.map(selected_counts)
    selected["stage"] = stage
    selected["cutoff_exclusive"] = cutoff
    selected = selected.sort_values(KEY, kind="stable").reset_index(drop=True)
    if set(selected.signal_date) != set(mature.signal_date):
        raise AssertionError("sampler lost a mature date")
    if not np.isclose(selected.sample_weight.mean(), 1.0):
        raise AssertionError("sample weights must have unit mean")
    return selected


def stage_frame(stage: str, *, input_root: str | Path | None = None) -> pd.DataFrame:
    """Load frozen keys; never re-sample or open evaluation inputs."""
    stage = STAGE_ALIASES.get(stage, stage)
    if stage not in STAGE_CUTOFFS:
        raise ValueError(f"unknown training stage: {stage}")
    directory = Path(input_root) if input_root is not None else INPUT
    frame = pd.read_parquet(directory / "pre2026.parquet")
    keys = pd.read_parquet(directory / f"stage_{stage}_keys.parquet")
    require_schema(keys, [*KEY, "sample_weight", "sampling_sha256", "stage", "cutoff_exclusive"], name="stage keys")
    if keys.duplicated(KEY).any() or len(keys) > MAX_TRAIN_KEYS:
        raise ValueError("invalid frozen stage-key budget or duplicates")
    if not keys.stage.eq(stage).all() or not keys.cutoff_exclusive.eq(STAGE_CUTOFFS[stage]).all():
        raise ValueError("stage keys have an incompatible cutoff")
    result = keys.merge(frame, on=KEY, how="left", validate="one_to_one", indicator=True)
    if not result._merge.eq("both").all():
        raise ValueError("frozen training key absent from pre-2026 snapshot")
    result = result.drop(columns="_merge")
    validate_panel(result, name=f"{stage} training")
    if not maturity_mask(result, STAGE_CUTOFFS[stage]).all():
        raise ValueError("training stage contains an immature or future label")
    if not result.sample_weight.gt(0).all():
        raise ValueError("nonpositive training sample weight")
    totals = result.groupby("signal_date").sample_weight.sum()
    if not np.allclose(totals, totals.iloc[0]):
        raise ValueError("training sample weights are not date balanced")
    result["y_train"] = result.y_next_open.clip(-TRAIN_CLIP, TRAIN_CLIP)
    return result.sort_values(KEY, kind="stable").reset_index(drop=True)


load_stage_training = stage_frame


def load_oof_frame(year: int, *, mature_only: bool = False, input_root: str | Path | None = None) -> pd.DataFrame:
    if year not in [2024, 2025]:
        raise ValueError("OOF years are frozen to 2024 and 2025")
    directory = Path(input_root) if input_root is not None else INPUT
    frame = pd.read_parquet(directory / "pre2026.parquet")
    frame = frame.loc[frame.signal_date.dt.year.eq(year)].copy()
    frame["oof_label_mature"] = maturity_mask(frame, f"{year+1}-01-01")
    if mature_only:
        frame = frame.loc[frame.oof_label_mature].copy()
    frame["y_train"] = frame.y_next_open.clip(-TRAIN_CLIP, TRAIN_CLIP)
    validate_panel(frame, name=f"{year} OOF panel")
    return frame.sort_values(KEY, kind="stable").reset_index(drop=True)


def load_eval_inputs(year: int, *, input_root: str | Path | None = None):
    """Return (panel, prices, calendar, operational_exits, metadata)."""
    if year not in [2025, 2026]:
        raise ValueError("evaluation years are frozen to 2025 and 2026")
    directory = (Path(input_root) if input_root is not None else INPUT) / f"eval_{year}"
    panel = pd.read_parquet(directory / "features.parquet")
    prices = pd.read_parquet(directory / "prices.parquet")
    calendar_frame = pd.read_parquet(directory / "calendar.parquet")
    operations = pd.read_csv(directory / "operational_exits.csv", dtype={"ticker": str, "reason": str, "source_id": str})
    operations["known_at"] = pd.to_datetime(operations.known_at, utc=True)
    operations["effective_date"] = pd.to_datetime(operations.effective_date)
    metadata = json.loads((directory / "METADATA.json").read_text(encoding="utf-8"))
    validate_panel(panel, name=f"{year} evaluation")
    require_schema(prices, ["ticker", "trade_date", "open", "close", "price_quality_warning"], name=f"{year} prices")
    if prices.duplicated(["ticker", "trade_date"]).any():
        raise ValueError("duplicate evaluation price keys")
    if not prices[["open", "close"]].gt(0).all().all():
        raise ValueError("nonpositive evaluation price coordinate")
    calendar = pd.DatetimeIndex(calendar_frame.trade_date)
    if not calendar.is_monotonic_increasing or not calendar.is_unique:
        raise ValueError("evaluation calendar must be ordered and unique")
    if not panel.signal_date.dt.year.eq(year).all():
        raise ValueError("evaluation snapshot contains another signal year")
    return panel, prices, calendar, operations, metadata


def load_pre2026_prices(*, input_root: str | Path | None = None) -> pd.DataFrame:
    directory = Path(input_root) if input_root is not None else INPUT
    prices = pd.read_parquet(directory / "pre2026_prices.parquet")
    require_schema(prices, ["ticker", "trade_date", "open", "close"], name="pre-2026 risk prices")
    if not prices.trade_date.lt("2026-01-01").all():
        raise ValueError("risk-training price snapshot includes 2026")
    return prices
