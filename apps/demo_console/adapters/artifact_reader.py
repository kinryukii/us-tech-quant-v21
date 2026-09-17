"""Fail closed before materializing data from any mixed-year input.

Only exact pinned files are accepted. Date bounds are proven from every row
group before hashing or reading data; filters alone are NOT an access boundary.
The same binary read-only handle is used for metadata, identity and projection.
"""
from __future__ import annotations

import hashlib
import struct
from datetime import date, datetime

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from apps.demo_console.config.demo_config import ArtifactSpec


class ArtifactError(ValueError):
    """An input failed the demo's narrow read contract."""


def iso_date(value: object) -> str:
    if isinstance(value, bytes):
        value = value.decode("ascii")
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    text = str(value)
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ArtifactError("INVALID_DATE") from exc
    if len(text) != 10:
        raise ArtifactError("INVALID_DATE_FORMAT")
    return parsed.isoformat()


def read_frozen_parquet(spec: ArtifactSpec, columns: tuple[str, ...],
                        filters: list | None = None,
                        optional_columns: tuple[str, ...] = ()) -> pa.Table:
    if not spec.date_columns or not set(spec.date_columns) - set(spec.nullable_date_columns):
        raise ArtifactError("MISSING_TEMPORAL_CONTRACT")
    with spec.path.open("rb") as handle:
        # ParquetFile may prefetch 64 KiB including data pages. Read only the
        # exact footer first so rejected inputs never expose data-page bytes.
        handle.seek(0, 2)
        size = handle.tell()
        if size < 12:
            raise ArtifactError("EMPTY_OR_INVALID_PARQUET")
        handle.seek(-8, 2)
        trailer = handle.read(8)
        footer_size = struct.unpack("<I", trailer[:4])[0]
        if trailer[4:] != b"PAR1" or footer_size > size - 12:
            raise ArtifactError("INVALID_PARQUET_FOOTER")
        handle.seek(size - 8 - footer_size)
        footer = handle.read(footer_size)
        metadata = pq.read_metadata(pa.BufferReader(b"PAR1" + footer + trailer))
        names = metadata.schema.to_arrow_schema().names
        if metadata.num_rows == 0:
            raise ArtifactError("EMPTY_ARTIFACT")
        for date_column in spec.date_columns:
            if date_column not in names:
                raise ArtifactError(f"MISSING_DATE_COLUMN:{date_column}")
            index = names.index(date_column)
            for group in range(metadata.num_row_groups):
                row_group = metadata.row_group(group)
                stats = row_group.column(index).statistics
                if (stats is None or not stats.has_min_max or stats.null_count is None
                        or (stats.null_count != 0 and date_column not in spec.nullable_date_columns)):
                    raise ArtifactError(f"UNPROVEN_DATE_BOUNDARY:{date_column}")
                if iso_date(stats.min) > iso_date(stats.max) or iso_date(stats.max) >= "2026-01-01":
                    raise ArtifactError(f"POST2025_ARTIFACT_BLOCKED:{date_column}")
        missing = set(columns) - set(names)
        if missing:
            raise ArtifactError("MISSING_COLUMNS:" + ",".join(sorted(missing)))
        handle.seek(0)
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != spec.sha256:
            raise ArtifactError(f"ARTIFACT_IDENTITY_MISMATCH:{spec.name}")
        parquet = pq.ParquetFile(handle)
        table = parquet.read(columns=list(columns) + [c for c in optional_columns if c in names and c not in columns])
        # The entire file was proven pre2026 before this data projection.
        for column, operator, value in filters or []:
            if operator != "==" or column not in columns:
                raise ArtifactError("UNSUPPORTED_DISPLAY_FILTER")
            scalar = pc.cast(pa.scalar(value), table.schema.field(column).type)
            table = table.filter(pc.equal(table[column], scalar))
        return table
