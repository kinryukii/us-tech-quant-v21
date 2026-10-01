"""Offline ETF references from small, physically separated Moomoo projections.

No strategy is rerun and no market data is fetched. ETF prices are descriptive
comparisons, not new confirmation evidence or an alteration to the A/A2 study.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from math import isfinite
from pathlib import Path
import struct

import pyarrow as pa
import pyarrow.parquet as pq

from apps.demo_console.adapters.artifact_reader import ArtifactError, iso_date
from scripts.common.storage_paths import resolve

_LABELS = {"QQQ": "QQQ · Nasdaq-100 ETF", "SPY": "SPY · S&P 500 ETF"}
_COLUMNS = ("date", "ticker", "open", "source", "adjustment")
_SNAPSHOT = "moomoo_only_20260815_020646"


@dataclass(frozen=True)
class BenchmarkSpec:
    symbol: str
    window: str
    path: Path
    sha256: str
    start_date: str
    end_date: str
    row_count: int
    source_sha256: str


@dataclass(frozen=True)
class BenchmarkConfig:
    manifest_path: Path
    manifest_sha256: str
    artifacts: tuple[BenchmarkSpec, ...]


@dataclass(frozen=True)
class BenchmarkPoint:
    date: str
    price: float
    daily_return: float
    equity: float
    drawdown: float


@dataclass(frozen=True)
class BenchmarkSeries:
    symbol: str
    label: str
    provider: str = "MOOMOO_OPEND"
    adjustment: str = "QFQ"
    basis: str = "OPEN_TO_OPEN"
    points: tuple[BenchmarkPoint, ...] = ()
    total_return: float | None = None
    max_drawdown: float | None = None
    source_refs: tuple[tuple[str, str], ...] = ()
    error: str | None = None
    debug_error: str | None = None


@dataclass(frozen=True)
class BenchmarkHistory:
    series: tuple[BenchmarkSeries, ...] = ()
    start_date: str | None = None
    end_date: str | None = None
    baseline_date: str | None = None
    error: str | None = None
    debug_error: str | None = None


def default_benchmarks_config() -> BenchmarkConfig:
    root = resolve().results_root / "demo-console" / "benchmarks"
    source = {"QQQ": "b4f2747ad3b7ede54edc953bfe359c1d51c0c4f29142d2c58be92adf88df35e0",
              "SPY": "ba958eab27badb3d742e16c9f99bf7b29d02d97e7f34a0aa07fc84a7f85a0c69"}
    bindings = (
        ("QQQ", "historical", "3c4f92c7b45775c8a014ceab5c393be410b11f213643e597f196dedf98615b79"),
        ("SPY", "historical", "f44b54569c7e0201855fd73ef500d7a19e4249cd7a4fc417ff6db9062ee0d361"),
        ("QQQ", "recorded_2026", "3f6ac9091b1f1406ce060aa0fbb421b3f20333cc621aa5e9f037998d516d994b"),
        ("SPY", "recorded_2026", "704fdf37759049ad9c43392452e2ac3401966807341012857dc5c9dbc4242f21"),
    )
    artifacts = tuple(BenchmarkSpec(symbol, window, root / f"{symbol.lower()}_{window}.parquet", digest,
        "2023-01-04" if window == "historical" else "2026-06-15",
        "2025-12-30" if window == "historical" else "2026-08-13",
        750 if window == "historical" else 42, source[symbol]) for symbol, window, digest in bindings)
    return BenchmarkConfig(root / "manifest.json",
        "9eca5b8ab3ea566dfadf544d6a044b052f631f2d536f14ab3b735a1473838e6f", artifacts)


def _validate_dates(dates, baseline_date):
    if not isinstance(dates, tuple) or not dates:
        raise ArtifactError("BENCHMARK_DATES_REQUIRED")
    normalized = tuple(iso_date(day) for day in dates)
    if normalized != dates or dates != tuple(sorted(set(dates))):
        raise ArtifactError("BENCHMARK_DATE_ORDER_OR_DUPLICATE")
    if baseline_date is not None and (iso_date(baseline_date) != baseline_date or baseline_date >= dates[0]):
        raise ArtifactError("BENCHMARK_INVALID_BASELINE_DATE")


def _window(dates, baseline_date):
    _validate_dates(dates, baseline_date)
    first = baseline_date or dates[0]
    if "2023-01-04" <= first <= dates[-1] <= "2025-12-30":
        return "historical"
    if "2026-06-15" <= first <= dates[-1] <= "2026-08-13":
        return "recorded_2026"
    raise ArtifactError("BENCHMARK_WINDOW_NOT_BOUND")


def _read_manifest(config):
    with config.manifest_path.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != config.manifest_sha256:
            raise ArtifactError("BENCHMARK_MANIFEST_IDENTITY_MISMATCH")
        handle.seek(0)
        manifest = json.load(handle)
    if (manifest.get("schema") != "DEMO_BENCHMARK_LOCAL_PROJECTION_V1"
            or manifest.get("status") != "DISPLAY_ONLY_LOCAL_PROJECTION"
            or manifest.get("provider") != "MOOMOO_OPEND" or manifest.get("adjustment") != "QFQ"
            or manifest.get("basis") != "OPEN_TO_OPEN" or manifest.get("source_policy") != "MOOMOO_ONLY"
            or manifest.get("source_snapshot") != _SNAPSHOT):
        raise ArtifactError("BENCHMARK_SOURCE_IDENTITY_MISMATCH")
    return manifest


def _binding(spec, manifest):
    bounds = {"historical": ("2023-01-04", "2025-12-30"), "recorded_2026": ("2026-06-15", "2026-08-13")}
    if (spec.window not in bounds or not bounds[spec.window][0] <= iso_date(spec.start_date)
            <= iso_date(spec.end_date) <= bounds[spec.window][1]
            or type(spec.row_count) is not int or spec.row_count < 1):
        raise ArtifactError("BENCHMARK_INVALID_ARTIFACT_CONTRACT")
    matches = [row for row in manifest.get("artifacts", [])
               if row.get("symbol") == spec.symbol and row.get("window") == spec.window]
    if len(matches) != 1:
        raise ArtifactError("BENCHMARK_ARTIFACT_BINDING_MISMATCH")
    row = matches[0]
    expected = {"path": str(spec.path), "sha256": spec.sha256, "start_date": spec.start_date,
                "end_date": spec.end_date, "rows": spec.row_count, "source_sha256": spec.source_sha256}
    if any(row.get(key) != value for key, value in expected.items()):
        raise ArtifactError("BENCHMARK_ARTIFACT_BINDING_MISMATCH")
    source = manifest.get("sources", {}).get(spec.symbol, {})
    if source.get("sha256") != spec.source_sha256:
        raise ArtifactError("BENCHMARK_SOURCE_BINDING_MISMATCH")
    return source


def _read_prices(spec):
    # Exact footer only before identity hashing and projection. Historical and
    # 2026 references have separate files; no date filter opens the other one.
    with spec.path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        if size < 12:
            raise ArtifactError("BENCHMARK_INVALID_PARQUET")
        handle.seek(-8, 2)
        trailer = handle.read(8)
        footer_size = struct.unpack("<I", trailer[:4])[0]
        if trailer[4:] != b"PAR1" or footer_size > size - 12:
            raise ArtifactError("BENCHMARK_INVALID_PARQUET_FOOTER")
        handle.seek(size - 8 - footer_size)
        footer = handle.read(footer_size)
        metadata = pq.read_metadata(pa.BufferReader(b"PAR1" + footer + trailer))
        names = metadata.schema.to_arrow_schema().names
        if metadata.num_rows != spec.row_count or spec.row_count < 1 or set(_COLUMNS) - set(names):
            raise ArtifactError("BENCHMARK_SCHEMA_OR_COUNT_MISMATCH")
        schema_metadata = metadata.metadata or {}
        if (schema_metadata.get(b"demo_projection_schema") != b"BENCHMARK_OPEN_REFERENCE_V1"
                or schema_metadata.get(b"source_csv_sha256") != spec.source_sha256.encode("ascii")
                or schema_metadata.get(b"source_snapshot") != _SNAPSHOT.encode("ascii")):
            raise ArtifactError("BENCHMARK_PROJECTION_LINEAGE_MISMATCH")
        lows, highs = [], []
        for group in range(metadata.num_row_groups):
            for name, expected in (("date", None), ("ticker", spec.symbol),
                                   ("source", "MOOMOO_OPEND"), ("adjustment", "qfq")):
                stats = metadata.row_group(group).column(names.index(name)).statistics
                if stats is None or not stats.has_min_max or stats.null_count != 0:
                    raise ArtifactError("BENCHMARK_UNPROVEN_INPUT_BOUNDARY")
                if name == "date":
                    low, high = iso_date(stats.min), iso_date(stats.max)
                    if not spec.start_date <= low <= high <= spec.end_date:
                        raise ArtifactError("BENCHMARK_DATE_BOUNDARY_MISMATCH")
                    lows.append(low)
                    highs.append(high)
                elif stats.min != expected or stats.max != expected:
                    raise ArtifactError("BENCHMARK_SECURITY_OR_PROVIDER_MISMATCH")
        if not lows or (min(lows), max(highs)) != (spec.start_date, spec.end_date):
            raise ArtifactError("BENCHMARK_EXACT_ARCHIVE_BOUNDARY_MISMATCH")
        handle.seek(0)
        if hashlib.file_digest(handle, "sha256").hexdigest() != spec.sha256:
            raise ArtifactError("BENCHMARK_ARTIFACT_IDENTITY_MISMATCH")
        rows = pq.ParquetFile(handle).read(columns=list(_COLUMNS)).to_pylist()
    calendar = tuple(iso_date(row["date"]) for row in rows)
    if calendar != tuple(sorted(set(calendar))):
        raise ArtifactError("BENCHMARK_ARCHIVE_DATE_ORDER_OR_DUPLICATE")
    for row in rows:
        value = row["open"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
            raise ArtifactError("BENCHMARK_INVALID_OPEN_PRICE")
        if (row["ticker"], row["source"], row["adjustment"]) != (spec.symbol, "MOOMOO_OPEND", "qfq"):
            raise ArtifactError("BENCHMARK_SECURITY_OR_PROVIDER_MISMATCH")
    return calendar, {row["date"]: float(row["open"]) for row in rows}


def _aligned_points(calendar, prices, dates, baseline_date):
    required = ((baseline_date,) if baseline_date is not None else ()) + dates
    if any(day not in prices for day in required):
        raise ArtifactError("BENCHMARK_REQUIRED_DATE_MISSING")
    if calendar[calendar.index(required[0]):calendar.index(required[-1]) + 1] != required:
        raise ArtifactError("BENCHMARK_NONCONTIGUOUS_WINDOW_OR_BASELINE")
    baseline = prices[baseline_date or dates[0]]
    previous, peak, points = baseline, 1.0, []
    for day in dates:
        value = prices[day]
        equity = value / baseline
        peak = max(peak, equity)
        points.append(BenchmarkPoint(day, value, value / previous - 1, equity, equity / peak - 1))
        previous = value
    return tuple(points)


def _series(symbol, dates, baseline_date, window, config, manifest):
    try:
        specs = [spec for spec in config.artifacts if spec.symbol == symbol and spec.window == window]
        if len(specs) != 1:
            raise ArtifactError("BENCHMARK_SPEC_MISSING_OR_AMBIGUOUS")
        spec = specs[0]
        source = _binding(spec, manifest)
        calendar, prices = _read_prices(spec)
        points = _aligned_points(calendar, prices, dates, baseline_date)
        return BenchmarkSeries(symbol, _LABELS[symbol], points=tuple(points),
            total_return=points[-1].equity - 1, max_drawdown=min(point.drawdown for point in points),
            source_refs=((str(config.manifest_path), config.manifest_sha256),
                         (str(spec.path), spec.sha256), (source.get("path", ""), spec.source_sha256)))
    except Exception as exc:
        return BenchmarkSeries(symbol, _LABELS[symbol],
            error="This ETF reference is unavailable for the complete selected window.",
            debug_error=f"{type(exc).__name__}: {exc}")


def read_benchmarks(dates: tuple[str, ...], baseline_date: str | None = None,
                    *, config: BenchmarkConfig | None = None) -> BenchmarkHistory:
    """Align two unchanged ETF paths without filling or truncating observations.

    With no baseline date, the first requested open is equity 1 and return 0.
    A cropped window may supply its immediately preceding execution date; the
    first displayed return is then included, with pre-window equity still 1.
    The two ETF files fail independently. Source paths in the recorded manifest
    are provenance only and are never reopened by the UI reader.
    """
    try:
        window = _window(dates, baseline_date)
        config = config or default_benchmarks_config()
        manifest = _read_manifest(config)
        return BenchmarkHistory(tuple(_series(symbol, dates, baseline_date, window, config, manifest)
                                      for symbol in _LABELS), dates[0], dates[-1], baseline_date)
    except Exception as exc:
        return BenchmarkHistory(error="ETF references are unavailable for the selected window.",
                                debug_error=f"{type(exc).__name__}: {exc}")

@dataclass(frozen=True)
class UpdatedBenchmarkConfig:
    """Hash-bound independent ETF projection; never alters the frozen binding."""
    manifest_path: Path
    manifest_sha256: str


def _valid_digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def default_updated_benchmarks_config() -> UpdatedBenchmarkConfig:
    reference = resolve().results_root / "demo-console" / "benchmarks" / "updated_reference.json"
    binding = json.loads(reference.read_text(encoding="utf-8"))
    if not _valid_digest(binding.get("sha256")) or not isinstance(binding.get("path"), str):
        raise ArtifactError("BENCHMARK_UPDATED_REFERENCE_INVALID")
    path = Path(binding["path"])
    if not path.is_absolute():
        raise ArtifactError("BENCHMARK_UPDATED_REFERENCE_PATH_INVALID")
    return UpdatedBenchmarkConfig(path, binding["sha256"])


def _updated_manifest(config):
    if not _valid_digest(config.manifest_sha256):
        raise ArtifactError("BENCHMARK_MANIFEST_IDENTITY_MISMATCH")
    with config.manifest_path.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != config.manifest_sha256:
            raise ArtifactError("BENCHMARK_MANIFEST_IDENTITY_MISMATCH")
        handle.seek(0)
        manifest = json.load(handle)
    if (manifest.get("schema_version") != 1 or manifest.get("adjustment") != "RAW"
            or manifest.get("basis") != "OPEN_TO_OPEN_PRICE_RETURN"
            or manifest.get("provider") != "MOOMOO_OPEND_AND_MASSIVE"):
        raise ArtifactError("BENCHMARK_UPDATED_SOURCE_IDENTITY_MISMATCH")
    artifacts = manifest.get("artifacts")
    if (not isinstance(artifacts, list) or len(artifacts) != 2
            or {row.get("symbol") for row in artifacts} != set(_LABELS)):
        raise ArtifactError("BENCHMARK_UPDATED_ARTIFACT_SET_INVALID")
    return manifest


def _updated_prices(spec):
    first, last = spec.get("start_date"), spec.get("end_date")
    count = spec.get("row_count")
    if (iso_date(first) != first or iso_date(last) != last or first > last
            or type(count) is not int or count < 1 or not _valid_digest(spec.get("sha256"))):
        raise ArtifactError("BENCHMARK_INVALID_ARTIFACT_CONTRACT")
    source_refs = spec.get("source_refs")
    if (not isinstance(source_refs, list) or not source_refs
            or any(not isinstance(item.get("path"), str) or not item["path"]
                   or not _valid_digest(item.get("sha256")) for item in source_refs)):
        raise ArtifactError("BENCHMARK_SOURCE_BINDING_MISMATCH")
    path = Path(spec["path"])
    if not path.is_absolute():
        raise ArtifactError("BENCHMARK_ARTIFACT_PATH_INVALID")
    with path.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != spec["sha256"]:
            raise ArtifactError("BENCHMARK_ARTIFACT_IDENTITY_MISMATCH")
        handle.seek(0)
        parquet = pq.ParquetFile(handle)
        if parquet.metadata.num_rows != count or set(_COLUMNS) - set(parquet.schema_arrow.names):
            raise ArtifactError("BENCHMARK_SCHEMA_OR_COUNT_MISMATCH")
        rows = parquet.read(columns=list(_COLUMNS)).to_pylist()
    calendar = tuple(iso_date(row["date"]) for row in rows)
    if (calendar != tuple(sorted(set(calendar))) or (calendar[0], calendar[-1]) != (first, last)):
        raise ArtifactError("BENCHMARK_ARCHIVE_DATE_ORDER_OR_BOUNDARY")
    for row in rows:
        price = row["open"]
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not isfinite(price) or price <= 0:
            raise ArtifactError("BENCHMARK_INVALID_OPEN_PRICE")
        if (row["ticker"] != spec["symbol"] or row["adjustment"] != "raw"
                or row["source"] not in ("MOOMOO_OPEND", "MASSIVE_GROUPED")):
            raise ArtifactError("BENCHMARK_SECURITY_OR_PROVIDER_MISMATCH")
    return calendar, {day: float(row["open"]) for day, row in zip(calendar, rows)}


def _updated_series(symbol, dates, baseline_date, config, manifest):
    metadata = dict(provider=manifest["provider"], adjustment="RAW", basis="OPEN_TO_OPEN_PRICE_RETURN")
    try:
        spec = next(row for row in manifest["artifacts"] if row["symbol"] == symbol)
        calendar, prices = _updated_prices(spec)
        points = _aligned_points(calendar, prices, dates, baseline_date)
        return BenchmarkSeries(symbol, _LABELS[symbol], **metadata, points=points,
            total_return=points[-1].equity - 1, max_drawdown=min(point.drawdown for point in points),
            source_refs=((str(config.manifest_path), config.manifest_sha256),
                         (spec["path"], spec["sha256"]),
                         *((item["path"], item["sha256"]) for item in spec["source_refs"])))
    except Exception as exc:
        return BenchmarkSeries(symbol, _LABELS[symbol], **metadata,
            error="This ETF reference is unavailable for the complete selected window.",
            debug_error=f"{type(exc).__name__}: {exc}")


def read_updated_benchmarks(dates: tuple[str, ...], baseline_date: str | None = None,
                            *, config: UpdatedBenchmarkConfig | None = None) -> BenchmarkHistory:
    """Read actual RAW open-price returns, excluding dividends, for exact dates.

    No baseline means first requested open = 1; an explicit immediately preceding
    execution date includes the first daily return. Callers choose sample bounds;
    this reader never prepends a prior sample or fills/truncates missing prices.
    Source refs are hash-recorded provenance and are not reopened by the UI.
    """
    try:
        _validate_dates(dates, baseline_date)
        config = config or default_updated_benchmarks_config()
        manifest = _updated_manifest(config)
        return BenchmarkHistory(tuple(_updated_series(symbol, dates, baseline_date, config, manifest)
                                      for symbol in _LABELS), dates[0], dates[-1], baseline_date)
    except Exception as exc:
        return BenchmarkHistory(error="ETF references are unavailable for the selected window.",
                                debug_error=f"{type(exc).__name__}: {exc}")

