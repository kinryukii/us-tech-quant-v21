"""Price source inventory restricted to original 2026 quarterly candidate pools."""
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
R1 = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1")
RAW = Path(r"D:\us-tech-quant-cache\13f_pit_v1\moomoo_daily_raw")
LAYERS = [RAW, *(RAW / name for name in ("v16r_incremental", "v16r2_incremental", "v16r3_incremental", "v17d_incremental"))]
CANON = Path(r"D:\us-tech-quant-data\canonical\moomoo_ohlcv\snapshot_id=data_layer_20260911_99642e55d6185fe2402b")


def main():
    old = pd.read_parquet(R1 / "universe/quarterly_universe_members.parquet",
                          columns=["quarter", "ticker", "moomoo_transport_code"])
    old = old.loc[old.quarter.isin(["2025Q3", "2025Q4", "2026Q1"])]
    q2 = pd.read_parquet(HERE / "Q2_ORIGINAL24_INITIAL_CANDIDATES.parquet",
                         columns=["quarter", "ticker", "moomoo_transport_code"])
    pools = pd.concat([old, q2], ignore_index=True)
    assert pools.groupby("quarter").ticker.nunique().to_dict() == {"2025Q3":643,"2025Q4":624,"2026Q1":613,"2026Q2":575}
    union = pools[["ticker", "moomoo_transport_code"]].drop_duplicates()
    assert union.groupby("ticker").moomoo_transport_code.nunique().max() == 1
    codes = union.moomoo_transport_code.unique()
    metadata = {}
    for code in codes:
        basename = code.replace(".", "_") + ".parquet"
        paths = [layer / basename for layer in LAYERS if (layer / basename).exists()]
        max_dates = []
        for path in paths:
            file = pq.ParquetFile(path)
            col = file.schema.names.index("time_key")
            max_dates.extend(file.metadata.row_group(i).column(col).statistics.max
                             for i in range(file.metadata.num_row_groups)
                             if file.metadata.row_group(i).column(col).statistics is not None)
        metadata[code] = {"raw_paths": "|".join(str(p) for p in paths),
                          "raw_direct_file_count": len(paths),
                          "raw_direct_last_date": str(max(max_dates))[:10] if max_dates else ""}
    for field in ("raw_paths", "raw_direct_file_count", "raw_direct_last_date"):
        pools[field] = pools.moomoo_transport_code.map(lambda code: metadata[code][field])
    # Read a completed *versioned* alternate source only for ticker/date coverage, not as compatible prices.
    canonical = pd.read_csv(CANON / "canonical_moomoo_ohlcv_daily_raw.csv", usecols=["ticker", "date"])
    latest = canonical.groupby("ticker").date.max()
    pools["canonical_20260911_raw_last_date"] = pools.ticker.map(latest).fillna("")
    pools.to_csv(HERE / "QUARTER_POOL_PRICE_INVENTORY.csv", index=False)
    print({"quarter_counts":pools.groupby("quarter").size().to_dict(),
           "union_codes":len(codes),
           "direct_missing_by_quarter":pools.groupby("quarter").raw_direct_file_count.apply(lambda x:int(x.eq(0).sum())).to_dict(),
           "raw_last_date_distribution":pools[["moomoo_transport_code","raw_direct_last_date"]].drop_duplicates().raw_direct_last_date.value_counts().head(7).to_dict(),
           "canonical_20260911_raw_coverage_by_quarter":pools.groupby("quarter").canonical_20260911_raw_last_date.apply(lambda x:int(x.ge("2026-09-11").sum())).to_dict()})


if __name__ == "__main__":
    main()
