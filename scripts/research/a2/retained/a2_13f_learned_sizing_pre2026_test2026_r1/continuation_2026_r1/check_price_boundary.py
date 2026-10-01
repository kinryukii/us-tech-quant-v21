"""Read-only, targeted original-builder boundary and PIT event check."""
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RUN = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1\scripts\run_rebuild.py")
MANIFEST = Path(r"D:\us-tech-quant-results\A2_PRE2026_RAW_MOOMOO_REHAB_BUILDER_R2\surface_manifest.json")
FACTOR = Path(r"D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1\rehab_factors.parquet")
STATUS = Path(r"D:\us-tech-quant-cache\13f_pit_v1\a_a2_quarterly_13f_r1\rehab_status.csv")


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    spec = importlib.util.spec_from_file_location("frozen_a2_original_producer", RUN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.END_EXCLUSIVE = pd.Timestamp("2026-07-15")
    frozen = json.loads(MANIFEST.read_text(encoding="utf-8"))
    inventory = pd.read_csv(HERE / "RAW_2026Q1_CANDIDATE_PRICE_COVERAGE.csv")
    rehab = pd.read_parquet(FACTOR)
    status = pd.read_csv(STATUS)
    out = []
    for ticker in ("AAPL", "AMZN", "MSFT"):
        hit = inventory.loc[inventory.ticker.eq(ticker)]
        assert len(hit) == 1 and bool(hit.file_exists.iloc[0]), ticker
        code = hit.code.iloc[0]
        assert status.loc[status.code.eq(code), "status"].eq("PASS").any(), code
        raw = module.load_raw_code(code, [Path(p) for p in hit.raw_paths.iloc[0].split("|")])
        raw = raw.loc[raw.trade_date.lt(module.END_EXCLUSIVE)]
        adjusted, events = module.adjusted_price_frame(code, ticker, raw, rehab, {})
        part = next(item for item in frozen["partitions"] if code in item["codes"])
        frozen_path = Path(frozen["surface_path"]) / part["relative_path"]
        assert sha(frozen_path) == part["sha256"]
        old = pd.read_parquet(frozen_path, filters=[("moomoo_transport_code", "==", code)])
        old["trade_date"] = pd.to_datetime(old.trade_date).dt.normalize()
        merged = old.merge(adjusted, on="trade_date", suffixes=("_old", "_new"), validate="one_to_one")
        cols = ["open", "close", "high", "low", "volume"]
        error = max(float(np.abs(merged[f"{c}_old"] - merged[f"{c}_new"]).max()) for c in cols)
        out.append({"ticker": ticker, "code": code, "frozen_overlap_rows": len(merged),
                    "frozen_overlap_last": str(merged.trade_date.max().date()),
                    "max_abs_field_error": error,
                    "continuation_first": str(adjusted.loc[adjusted.trade_date.ge("2026-01-01"), "trade_date"].min().date()),
                    "continuation_last": str(adjusted.trade_date.max().date()),
                    "events_2026_to_jul14": sum(pd.Timestamp(e["event_date"]) >= pd.Timestamp("2026-01-01") for e in events),
                    "frozen_partition_sha256": part["sha256"]})
        assert error <= 1e-9, (ticker, error)
    result = {"status": "PASS_TARGETED_ORIGINAL_BUILDER_BOUNDARY", "checks": out,
              "builder_source_sha256": sha(RUN), "rehab_factors_sha256": sha(FACTOR),
              "statement": "Only the three named 2026Q1 candidate codes were materialized; this is not complete price qualification."}
    (HERE / "PRICE_BOUNDARY_CHECK.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
