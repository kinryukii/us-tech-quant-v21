from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pandas as pd


DATE_CANDIDATES = [
    "asof_date",
    "as_of_date",
    "signal_date",
    "trade_date",
    "price_date",
    "date",
    "timestamp",
    "datetime",
]

TICKER_CANDIDATES = [
    "ticker",
    "symbol",
    "stock_code",
    "security_code",
    "moomoo_symbol",
    "code",
]

IMPORTANT_NAME_PATTERN = re.compile(
    r"(?i)"
    r"(date|time|ticker|symbol|code|strategy|rank|score|weight|"
    r"forward|return|ret_|future|target|label|close|open|high|low|"
    r"price|volume|turnover|market|benchmark|regime|sector|industry|"
    r"factor|subfactor|technical|fundamental|risk|momentum|rsi|kdj|"
    r"boll|macd|ema|sma|ma\d+|volatility|breakout|pullback|trust)"
)

DROP_TEXT_PATTERN = re.compile(
    r"(?i)"
    r"(source_path|file_path|raw_payload|raw_json|request_json|"
    r"response_json|stack_trace|traceback|debug_text|long_description)"
)


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def detect_column(columns: list[str], candidates: list[str]) -> str | None:
    normalized = {normalize_name(c): c for c in columns}

    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]

    for column in columns:
        name = normalize_name(column)
        if any(candidate in name for candidate in candidates):
            return column

    return None


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while True:
            block = handle.read(block_size)
            if not block:
                break
            digest.update(block)

    return digest.hexdigest()


def inspect_csv(path: Path, sample_rows: int = 500) -> dict[str, Any]:
    header = pd.read_csv(path, nrows=0)
    columns = list(header.columns)

    sample = pd.read_csv(
        path,
        nrows=sample_rows,
        low_memory=False,
    )

    date_column = detect_column(columns, DATE_CANDIDATES)
    ticker_column = detect_column(columns, TICKER_CANDIDATES)

    column_info = []

    for index, column in enumerate(columns):
        series = sample[column]

        non_null = int(series.notna().sum())
        unique_sample = int(series.nunique(dropna=True))

        column_info.append(
            {
                "index": index,
                "column": column,
                "sample_dtype": str(series.dtype),
                "sample_non_null": non_null,
                "sample_unique": unique_sample,
            }
        )

    return {
        "path": str(path),
        "size_mb": round(path.stat().st_size / 1024 / 1024, 3),
        "column_count": len(columns),
        "date_column_detected": date_column,
        "ticker_column_detected": ticker_column,
        "columns": column_info,
    }


def choose_columns(
    sample: pd.DataFrame,
    date_column: str,
    ticker_column: str | None,
) -> tuple[list[str], list[str], list[str]]:
    keep_columns: list[str] = []
    numeric_columns: list[str] = []
    string_columns: list[str] = []

    for column in sample.columns:
        if DROP_TEXT_PATTERN.search(column):
            continue

        series = sample[column]

        always_keep = column == date_column or column == ticker_column
        name_is_important = bool(IMPORTANT_NAME_PATTERN.search(column))
        numeric = pd.api.types.is_numeric_dtype(series)
        boolean = pd.api.types.is_bool_dtype(series)

        low_cardinality_object = (
            pd.api.types.is_object_dtype(series)
            and series.nunique(dropna=True) <= 100
            and bool(
                re.search(
                    r"(?i)(type|group|bucket|regime|sector|industry|"
                    r"status|eligible|quality|side|direction)",
                    column,
                )
            )
        )

        if always_keep or name_is_important or numeric or boolean or low_cardinality_object:
            keep_columns.append(column)

            if numeric or boolean:
                numeric_columns.append(column)
            else:
                string_columns.append(column)

    if date_column not in keep_columns:
        keep_columns.insert(0, date_column)

    if ticker_column and ticker_column not in keep_columns:
        keep_columns.insert(1, ticker_column)

    return keep_columns, numeric_columns, string_columns


def build_forward_extract(
    source_path: Path,
    output_dir: Path,
    start_date: str,
    end_date: str,
    chunk_size: int,
) -> dict[str, Any]:
    header = pd.read_csv(source_path, nrows=0)
    all_columns = list(header.columns)

    date_column = detect_column(all_columns, DATE_CANDIDATES)
    ticker_column = detect_column(all_columns, TICKER_CANDIDATES)

    if not date_column:
        raise RuntimeError(
            "No date column detected. "
            f"Columns were: {all_columns}"
        )

    sample = pd.read_csv(
        source_path,
        nrows=1000,
        low_memory=False,
    )

    keep_columns, numeric_columns, string_columns = choose_columns(
        sample=sample,
        date_column=date_column,
        ticker_column=ticker_column,
    )

    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq

        parquet_available = True
    except ImportError:
        parquet_available = False
        pa = None
        pq = None

    writers: dict[int, Any] = {}
    output_paths: dict[int, Path] = {}
    row_counts: dict[int, int] = {}
    chunk_count = 0
    input_rows_seen = 0
    filtered_rows = 0

    csv_header_written: dict[int, bool] = {}

    for chunk in pd.read_csv(
        source_path,
        usecols=keep_columns,
        chunksize=chunk_size,
        low_memory=False,
    ):
        chunk_count += 1
        input_rows_seen += len(chunk)

        dates = pd.to_datetime(
            chunk[date_column],
            errors="coerce",
        )

        mask = (
            dates.notna()
            & (dates >= start_ts)
            & (dates <= end_ts)
        )

        chunk = chunk.loc[mask].copy()

        if chunk.empty:
            print(
                f"chunk={chunk_count} "
                f"input_rows_seen={input_rows_seen} "
                f"filtered_rows={filtered_rows}"
            )
            continue

        chunk[date_column] = dates.loc[mask].values

        for column in numeric_columns:
            if column == date_column:
                continue

            if column in chunk.columns:
                chunk[column] = pd.to_numeric(
                    chunk[column],
                    errors="coerce",
                ).astype("float64")

        for column in string_columns:
            if column == date_column:
                continue

            if column in chunk.columns:
                chunk[column] = chunk[column].astype("string")

        chunk["_calendar_year"] = chunk[date_column].dt.year.astype("int32")

        for year, year_frame in chunk.groupby("_calendar_year", sort=True):
            year = int(year)

            year_frame = year_frame.drop(columns=["_calendar_year"])
            row_counts[year] = row_counts.get(year, 0) + len(year_frame)
            filtered_rows += len(year_frame)

            if parquet_available:
                output_path = output_dir / (
                    f"technical_forward_join_panel_{year}.parquet"
                )

                table = pa.Table.from_pandas(
                    year_frame,
                    preserve_index=False,
                )

                if year not in writers:
                    writers[year] = pq.ParquetWriter(
                        output_path,
                        table.schema,
                        compression="zstd",
                        use_dictionary=True,
                    )
                    output_paths[year] = output_path
                else:
                    table = table.cast(writers[year].schema)

                writers[year].write_table(table)

            else:
                output_path = output_dir / (
                    f"technical_forward_join_panel_{year}.csv.gz"
                )

                year_frame.to_csv(
                    output_path,
                    mode="a",
                    index=False,
                    header=not csv_header_written.get(year, False),
                    compression="gzip",
                    encoding="utf-8",
                )

                csv_header_written[year] = True
                output_paths[year] = output_path

        print(
            f"chunk={chunk_count} "
            f"input_rows_seen={input_rows_seen} "
            f"filtered_rows={filtered_rows}"
        )

    for writer in writers.values():
        writer.close()

    file_manifest = []

    for year in sorted(output_paths):
        path = output_paths[year]

        file_manifest.append(
            {
                "year": year,
                "path": str(path),
                "filename": path.name,
                "rows": row_counts.get(year, 0),
                "size_mb": round(path.stat().st_size / 1024 / 1024, 3),
                "sha256": sha256_file(path),
            }
        )

    return {
        "source_path": str(source_path),
        "source_size_mb": round(
            source_path.stat().st_size / 1024 / 1024,
            3,
        ),
        "start_date": start_date,
        "end_date": end_date,
        "date_column": date_column,
        "ticker_column": ticker_column,
        "original_column_count": len(all_columns),
        "retained_column_count": len(keep_columns),
        "retained_columns": keep_columns,
        "parquet_available": parquet_available,
        "input_rows_seen": input_rows_seen,
        "filtered_rows": filtered_rows,
        "chunk_count": chunk_count,
        "files": file_manifest,
    }


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--repo-root",
        default=r"D:\us-tech-quant",
    )
    parser.add_argument(
        "--start-date",
        default="2022-01-01",
    )
    parser.add_argument(
        "--end-date",
        default="2026-07-13",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=100_000,
    )

    args = parser.parse_args()

    repo_root = Path(args.repo_root)

    forward_path = (
        repo_root
        / "outputs"
        / "v21"
        / "V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1"
        / "technical_forward_join_panel.csv"
    )

    long_path = (
        repo_root
        / "outputs"
        / "v21"
        / "V21.246_TECHNICAL_AND_FORWARD_PANEL_BUILD_FROM_MOOMOO_CACHE_R1"
        / "technical_subfactor_panel_long.csv"
    )

    if not forward_path.exists():
        raise FileNotFoundError(forward_path)

    if not long_path.exists():
        raise FileNotFoundError(long_path)

    timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")

    output_dir = (
        repo_root
        / "exports"
        / f"ABCDE_BACKTEST_PANEL_EXTRACT_{timestamp}"
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    print("=== SCHEMA INSPECTION ===")

    schema_report = {
        "technical_forward_join_panel": inspect_csv(forward_path),
        "technical_subfactor_panel_long": inspect_csv(long_path),
    }

    schema_path = output_dir / "SCHEMA_REPORT.json"

    schema_path.write_text(
        json.dumps(
            schema_report,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # 保存小样本，便于远程字段检查。
    pd.read_csv(
        forward_path,
        nrows=5000,
        low_memory=False,
    ).to_csv(
        output_dir / "technical_forward_join_panel_sample_5000.csv.gz",
        index=False,
        compression="gzip",
        encoding="utf-8",
    )

    pd.read_csv(
        long_path,
        nrows=5000,
        low_memory=False,
    ).to_csv(
        output_dir / "technical_subfactor_panel_long_sample_5000.csv.gz",
        index=False,
        compression="gzip",
        encoding="utf-8",
    )

    print("=== BUILDING FORWARD PANEL EXTRACT ===")

    extract_report = build_forward_extract(
        source_path=forward_path,
        output_dir=output_dir,
        start_date=args.start_date,
        end_date=args.end_date,
        chunk_size=args.chunk_size,
    )

    report_path = output_dir / "EXTRACT_REPORT.json"

    report_path.write_text(
        json.dumps(
            extract_report,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    manifest = pd.DataFrame(extract_report["files"])

    manifest.to_csv(
        output_dir / "EXTRACT_MANIFEST.csv",
        index=False,
        encoding="utf-8",
    )

    metadata_zip_base = output_dir / "ABCDE_PANEL_METADATA"

    shutil.make_archive(
        str(metadata_zip_base),
        "zip",
        root_dir=output_dir,
        base_dir=".",
    )

    print("")
    print("=== PANEL EXTRACT COMPLETE ===")
    print(f"output_dir={output_dir}")
    print(f"schema_report={schema_path}")
    print(f"extract_report={report_path}")
    print(
        f"metadata_zip={metadata_zip_base}.zip"
    )
    print(
        f"retained_column_count="
        f"{extract_report['retained_column_count']}"
    )
    print(
        f"input_rows_seen="
        f"{extract_report['input_rows_seen']}"
    )
    print(
        f"filtered_rows="
        f"{extract_report['filtered_rows']}"
    )

    for item in extract_report["files"]:
        print(
            f"year={item['year']} "
            f"rows={item['rows']} "
            f"size_mb={item['size_mb']} "
            f"path={item['path']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
