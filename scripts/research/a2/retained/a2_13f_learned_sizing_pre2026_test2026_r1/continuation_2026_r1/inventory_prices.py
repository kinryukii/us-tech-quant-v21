"""Read-only metadata inventory for the original 2026Q1 Raw A2 universe."""
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

OUT = Path(__file__).resolve().parent
ROOT = Path("D:/us-tech-quant-cache/13f_pit_v1/moomoo_daily_raw")
LAYERS = [ROOT, *(ROOT / name for name in ("v16r_incremental", "v16r2_incremental",
                                           "v16r3_incremental", "v17d_incremental"))]
MEMBERS = Path("D:/us-tech-quant-results/A_VS_A2_QUARTERLY_13F_R1/universe/quarterly_universe_members.parquet")

def main():
    members = pd.read_parquet(MEMBERS, columns=["quarter", "ticker", "moomoo_transport_code"])
    members = members.loc[members.quarter.eq("2026Q1")].copy()
    rows = []
    for row in members.itertuples(index=False):
        basename = row.moomoo_transport_code.replace(".", "_") + ".parquet"
        paths = [layer / basename for layer in LAYERS if (layer / basename).exists()]
        record = {"ticker": row.ticker, "code": row.moomoo_transport_code,
                  "raw_paths": "|".join(str(path) for path in paths),
                  "file_exists": bool(paths), "max_time_key": ""}
        values = []
        for path in paths:
            source = pq.ParquetFile(path)
            position = source.schema.names.index("time_key")
            values.extend(source.metadata.row_group(i).column(position).statistics.max
                          for i in range(source.metadata.num_row_groups)
                          if source.metadata.row_group(i).column(position).statistics is not None)
        if values:
            record["max_time_key"] = str(max(values))
        rows.append(record)
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT / "RAW_2026Q1_CANDIDATE_PRICE_COVERAGE.csv", index=False)
    print({"candidate_codes": len(frame), "direct_raw_files": int(frame.file_exists.sum()),
           "missing_direct_raw_files": int((~frame.file_exists).sum()),
           "max_date_distribution": frame.max_time_key.value_counts().head(12).to_dict()})

if __name__ == "__main__":
    main()
