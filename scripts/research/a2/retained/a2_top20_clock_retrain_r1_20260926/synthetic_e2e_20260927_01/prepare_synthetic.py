"""Prepare a tiny, explicitly synthetic R1 two-container execution fixture.

This writes no market-derived value and never changes a sealed R1 artifact.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
R1 = HERE.parent
SOURCE = HERE / "source"
OUT = HERE / "out"
BATCH = "a2_top20_clock_retrain_r1_20260926"
ASOF = "2026-09-25T15:34:48Z"
IPC_NAME = "r1-synthetic-e2e-ipc-20260927-01"
SIGNALS = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
SESSIONS = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"])


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def schema_sha(path: Path) -> str:
    schema = pq.ParquetFile(path).schema_arrow.remove_metadata()
    return hashlib.sha256(str(schema).encode("utf-8")).hexdigest()


def write_json(path: Path, value: dict) -> None:
    if path.exists():
        raise RuntimeError(f"SYNTHETIC_OUTPUT_ALREADY_EXISTS:{path}")
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def make_panel(features: list[str]) -> pd.DataFrame:
    rows = []
    for day_index, day in enumerate(SIGNALS):
        for rank in range(1, 41):
            security = (rank - 1 + 5 * day_index) % 50
            row = {
                "signal_date": day,
                "ticker": f"SYN{security:03d}",
                "security_id": f"SYNTHETIC_SECURITY_{security:03d}",
                "raw_rank": rank,
            }
            for feature_index, name in enumerate(features):
                if name == "raw_rank_strength":
                    value = 1.0 - (rank - 1) / 39.0
                elif name == "raw_score_z":
                    value = (20.5 - rank) / 11.543396380615196
                elif name == "volume_ratio_5d_20d":
                    value = 1.0 + 0.001 * security
                elif "vol" in name:
                    value = 0.02 + 0.0001 * (security + day_index)
                elif name == "price_vs_ma20":
                    value = 1.0 + 0.0005 * (security - 25)
                elif name in ("max_drawdown_20d", "distance_from_high_20d"):
                    value = -0.01 - 0.0002 * security
                else:
                    value = 0.001 * np.sin(security + day_index + feature_index)
                row[name] = float(value)
            rows.append(row)
    return pd.DataFrame(rows)


def make_prices() -> pd.DataFrame:
    rows = []
    for day_index, day in enumerate(SESSIONS):
        for security in range(50):
            opening = (10.0 + 0.2 * security) * (1.0 + 0.002 * day_index)
            closing = (opening * (1.0 + 0.0003 * ((security + day_index) % 5 - 2))
                       if day_index < 3 else np.nan)
            rows.append({"trade_date": day, "ticker": f"SYN{security:03d}",
                         "open": opening, "close": closing})
        rows.append({"trade_date": day, "ticker": "QQQ", "open": 100.0 + day_index,
                     "close": 100.0 + day_index if day_index < 3 else np.nan})
    return pd.DataFrame(rows)


def main() -> None:
    if any(SOURCE.iterdir()) or any(OUT.iterdir()):
        raise RuntimeError("SYNTHETIC_SOURCE_OR_OUTPUT_NOT_EMPTY")
    contract = json.loads((R1 / "test_handoff" / "PRETEST_BINDING.json").read_text(encoding="utf-8"))
    if contract["status"] != "PRETEST_BINDING_INCOMPLETE":
        raise RuntimeError("UNEXPECTED_R1_PRETEST_STATUS")
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location("r1_synthetic_prepare", R1 / "trainer_bundle" / "prepare.py")
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    panel = make_panel(list(module.FEATURES))
    prices = make_prices()
    panel_path = SOURCE / "panel.parquet"
    prices_path = SOURCE / "prices.parquet"
    panel.to_parquet(panel_path, index=False)
    prices.to_parquet(prices_path, index=False)
    lineage_sha = hashlib.sha256(b"SYNTHETIC_A2_IDENTITY_ONLY_NO_MARKET_SOURCE").hexdigest()
    builder_sha = sha(Path(__file__))
    source = {
        "batch": BATCH,
        "test_asof_utc": ASOF,
        "synthetic_only": True,
        "a2_lineage_sha256": lineage_sha,
        "feature_builder_sha256": builder_sha,
        "last_completed_signal_session": "2026-01-06",
        "last_available_execution_open": "2026-01-07",
        "open_observed_at_utc": "2026-01-07T14:31:00Z",
        "panel": {"path": "/test/panel.parquet", "sha256": sha(panel_path),
                  "schema_sha256": schema_sha(panel_path)},
        "prices": {"path": "/test/prices.parquet", "sha256": sha(prices_path),
                   "schema_sha256": schema_sha(prices_path)},
    }
    source_path = SOURCE / "SYNTHETIC_SOURCE_IDENTITY.json"
    write_json(source_path, source)
    manifest = {
        "status": "FROZEN_TEST_BATCH",
        "synthetic_only": True,
        "not_an_approved_r1_test_source": True,
        "batch": BATCH,
        "test_asof_utc": ASOF,
        "roster": contract["roster"],
        "training_output_seal_sha256": contract["training_output_seal_sha256"],
        "review_output_seal_sha256": contract["review_output_seal_sha256"],
        "runtime_image_id": contract["runtime_image_id"],
        "bound_files": contract["bound_files"],
        "decision_bundle_identity_sha256": contract["decision_bundle_identity_sha256"],
        "test_source": {
            **{key: source[key] for key in (
                "a2_lineage_sha256", "feature_builder_sha256",
                "last_completed_signal_session", "last_available_execution_open",
                "open_observed_at_utc", "panel", "prices")},
            "source_manifest_path": "/test/SYNTHETIC_SOURCE_IDENTITY.json",
            "source_manifest_sha256": sha(source_path),
            "mount_source": str(SOURCE),
        },
        "r1_host_root": str(R1),
        "approved_out_source": str(OUT),
        "runtime": {"approved_ipc_name": IPC_NAME},
    }
    manifest_path = OUT / "SYNTHETIC_FROZEN_TEST_BATCH.json"
    write_json(manifest_path, manifest)
    write_json(HERE / "PREP_RECEIPT.json", {
        "status": "SYNTHETIC_ONLY_NO_REAL_MARKET_SOURCE",
        "panel_rows": len(panel), "price_rows": len(prices),
        "signal_dates": [str(x.date()) for x in SIGNALS],
        "execution_dates": [str(x.date()) for x in SESSIONS[1:]],
        "source_identity_sha256": sha(source_path),
        "manifest_sha256": sha(manifest_path),
        "builder_sha256": builder_sha,
    })
    print("SYNTHETIC_R1_SOURCE_PREPARED", sha(manifest_path), flush=True)


if __name__ == "__main__":
    main()
