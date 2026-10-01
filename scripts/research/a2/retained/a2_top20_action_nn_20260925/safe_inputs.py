"""Local read-only fallback for the retired pre-2026 tail input worktree."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq

END = pd.Timestamp("2026-01-01")
CHECKPOINT = Path(r"D:\us-tech-quant-results\A2_AUTHORITATIVE_RAW_TOP40_MEMBERSHIP_CHECKPOINT_R1\raw_a2_top40_membership_checkpoint.parquet")
MATRIX = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\A2\training_matrix.parquet")
SURFACE = Path(r"D:\us-tech-quant-results\A2_PRE2026_RAW_MOOMOO_REHAB_BUILDER_R2\surface_manifest.json")
CALENDAR = Path(r"D:\us-tech-quant-data\reference\trading_calendar\XNYS\versions\xnys_sessions_f61c8f8d47cd94ae4b75.parquet")
HASHES = {
    CHECKPOINT: "1e6fa12b3f8d1144ef0337d343244424f44c27930e8e405b622885c0ae625a17",
    MATRIX: "31cc2b3dd2aa7a7c3372d56d5f3f351746b4ad06ef984563de576071913615fb",
    SURFACE: "94d3bec3c8fe34075b6dc4a3bc03954015b87c28247d3e49e79b254795c4c7ec",
    CALENDAR: "f61c8f8d47cd94ae4b75eab51566917bd809abd2afe8b280858fb04ba36e93e4",
}


def sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def physical_before_cutoff(path: Path, column: str) -> None:
    parquet = pq.ParquetFile(path)
    index = parquet.schema_arrow.names.index(column)
    for i in range(parquet.metadata.num_row_groups):
        stats = parquet.metadata.row_group(i).column(index).statistics
        if stats is None or not stats.has_min_max or pd.Timestamp(stats.max) >= END:
            raise RuntimeError(f"PHYSICAL_DATE_BOUNDARY_UNPROVEN:{path}:{column}")


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, None, dict]:
    for path, expected in HASHES.items():
        if sha256(path) != expected:
            raise RuntimeError(f"INPUT_HASH_MISMATCH:{path}")
    physical_before_cutoff(CHECKPOINT, "decision_date")
    physical_before_cutoff(MATRIX, "signal_date")
    physical_before_cutoff(MATRIX, "target_end_date")
    checkpoint = ds.dataset(CHECKPOINT, format="parquet").to_table().to_pandas()
    checkpoint = checkpoint.rename(columns={"decision_date": "signal_date", "ticker_if_available": "ticker"})
    matrix = ds.dataset(MATRIX, format="parquet").to_table().to_pandas()
    matrix = matrix.loc[pd.to_datetime(matrix.target_end_date).lt(END)]
    panel = checkpoint.merge(matrix, on=["signal_date", "ticker"], how="inner", validate="one_to_one")
    panel = panel.sort_values(["signal_date", "raw_rank", "ticker"]).reset_index(drop=True)
    if panel.empty or panel.groupby("signal_date").size().ne(40).any():
        raise RuntimeError("TOP40_PANEL_CARDINALITY")
    if panel.signal_date.ge(END).any() or panel.target_end_date.ge(END).any():
        raise RuntimeError("TRAINING_DATE_FAILURE")
    if (pd.to_datetime(panel.prediction_asof_date) > panel.signal_date).any():
        raise RuntimeError("FUTURE_PREDICTION")
    panel["raw_rank_strength"] = 1.0 - (panel.raw_rank.astype(float) - 1.0) / 39.0
    group = panel.groupby("signal_date").raw_score
    panel["raw_score_z"] = (panel.raw_score - group.transform("mean")) / group.transform(lambda x: x.std(ddof=0))
    manifest = json.loads(SURFACE.read_text(encoding="utf-8"))
    base = Path(manifest["surface_path"])
    parts = []
    for item in manifest["partitions"]:
        path = base / item["relative_path"]
        if sha256(path) != item["sha256"]:
            raise RuntimeError(f"SURFACE_PART_HASH_MISMATCH:{path}")
        physical_before_cutoff(path, "trade_date")
        parts.append(pq.read_table(path, columns=["ticker", "trade_date", "open", "close"]).to_pandas())
    prices = pd.concat(parts, ignore_index=True)
    sessions = ds.dataset(CALENDAR, format="parquet").to_table(
        columns=["trade_date"],
        filter=(ds.field("trade_date") >= "2020-01-01") & (ds.field("trade_date") < "2026-01-01"),
    ).to_pandas()
    calendar_only = pd.DataFrame({"ticker": "QQQ", "trade_date": pd.to_datetime(sessions.trade_date),
                                  "open": 1.0, "close": 1.0})
    prices = pd.concat([prices, calendar_only], ignore_index=True)
    if prices.trade_date.ge(END).any() or prices.duplicated(["ticker", "trade_date"]).any():
        raise RuntimeError("PRICE_BOUNDARY_OR_DUPLICATE")
    lineage = {"status": "PINNED_LOCAL_RECONSTRUCTION", "source_hashes": {str(k): v for k, v in HASHES.items()},
               "surface_manifest_hash": HASHES[SURFACE], "partition_count": len(parts),
               "benchmark": "pinned XNYS session calendar only; QQQ synthetic prices unused for labels or NAV",
               "reference": "D:/us-tech-quant/scripts/research/a2/factors/tail_research_inputs.py",
               "known_difference": "raw_score_z formula reconstructed; verify scaler identity before claiming exact reproduction"}
    return panel, prices, None, lineage
