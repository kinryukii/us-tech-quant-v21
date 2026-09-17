"""Offline synthetic benchmark isolation, source identity and window accounting."""
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import struct

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from apps.demo_console.adapters import benchmarks_reader as reader
from apps.demo_console.adapters.benchmarks_reader import BenchmarkConfig, BenchmarkSpec, read_benchmarks
from apps.demo_console.tests.test_read_only_contract import _ReadWatch

_DATES = ("2023-01-04", "2023-01-05", "2023-01-06", "2023-01-09")
_LATER = ("2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18")


@pytest.fixture
def benchmark_config(artifact_dir):
    def create(*, mutate_rows=None, mutate_manifest=None, statistics=True, mutate_metadata=None):
        specs, sources, artifacts = [], {}, []
        for symbol in ("QQQ", "SPY"):
            source_sha = ("c" if symbol == "QQQ" else "d") * 64
            sources[symbol] = {"path": f"X:/NEVER_OPEN/{symbol}.csv", "sha256": source_sha}
            for window, dates in (("historical", _DATES), ("recorded_2026", _LATER)):
                prices = (100., 110., 99., 101.) if symbol == "QQQ" else (100., 98., 97., 99.)
                rows = [{"date": day, "ticker": symbol, "open": price,
                         "source": "MOOMOO_OPEND", "adjustment": "qfq"} for day, price in zip(dates, prices)]
                metadata = {b"demo_projection_schema": b"BENCHMARK_OPEN_REFERENCE_V1",
                            b"source_csv_sha256": source_sha.encode(),
                            b"source_snapshot": reader._SNAPSHOT.encode()}
                if symbol == "QQQ" and window == "historical":
                    if mutate_rows:
                        mutate_rows(rows)
                    if mutate_metadata:
                        mutate_metadata(metadata)
                path = artifact_dir / f"{symbol}_{window}.parquet"
                table = pa.Table.from_pylist(rows).replace_schema_metadata(metadata)
                pq.write_table(table, path, row_group_size=1,
                               write_statistics=statistics if symbol == "QQQ" and window == "historical" else True)
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                spec = BenchmarkSpec(symbol, window, path, digest, dates[0], dates[-1], 4, source_sha)
                specs.append(spec)
                artifacts.append({"symbol":symbol,"window":window,"path":str(path),"sha256":digest,
                                  "start_date":dates[0],"end_date":dates[-1],"rows":4,"source_sha256":source_sha})
        manifest = {"schema":"DEMO_BENCHMARK_LOCAL_PROJECTION_V1","status":"DISPLAY_ONLY_LOCAL_PROJECTION",
                    "provider":"MOOMOO_OPEND","adjustment":"QFQ","basis":"OPEN_TO_OPEN",
                    "source_policy":"MOOMOO_ONLY","source_snapshot":reader._SNAPSHOT,
                    "sources":sources,"artifacts":artifacts}
        if mutate_manifest:
            mutate_manifest(manifest)
        path = artifact_dir / "benchmark_manifest.json"
        raw = json.dumps(manifest).encode()
        path.write_bytes(raw)
        return BenchmarkConfig(path, hashlib.sha256(raw).hexdigest(), tuple(specs))
    return create


def test_first_open_baseline_and_losses_are_kept(benchmark_config):
    history = read_benchmarks(_DATES, config=benchmark_config())
    assert history.error is None and history.baseline_date is None
    qqq, spy = history.series
    assert qqq.error is spy.error is None
    assert qqq.label == "QQQ · Nasdaq-100 ETF" and spy.label == "SPY · S&P 500 ETF"
    assert qqq.provider == "MOOMOO_OPEND" and qqq.adjustment == "QFQ" and qqq.basis == "OPEN_TO_OPEN"
    assert qqq.points[0].equity == 1 and qqq.points[0].daily_return == 0
    assert qqq.points[1].daily_return == pytest.approx(.1)
    assert qqq.points[2].daily_return == pytest.approx(-.1)
    assert qqq.max_drawdown == pytest.approx(-.1)
    assert spy.total_return == pytest.approx(-.01)
    assert len(qqq.source_refs) == 3
    with pytest.raises(FrozenInstanceError):
        qqq.points[0].equity = 2


def test_cropped_window_includes_first_return_from_prior_execution(benchmark_config):
    config = benchmark_config()
    history = read_benchmarks(_DATES[2:], baseline_date=_DATES[1], config=config)
    qqq = history.series[0]
    assert history.baseline_date == _DATES[1] and qqq.error is None
    assert qqq.points[0].equity == pytest.approx(.9)
    assert qqq.points[0].daily_return == pytest.approx(-.1)
    assert qqq.points[0].drawdown == pytest.approx(-.1)
    assert qqq.total_return == pytest.approx(101 / 110 - 1)
    independent = read_benchmarks(_DATES[2:], config=config).series[0]
    assert independent.points[0].daily_return == 0 and independent.points[0].equity == 1


@pytest.mark.parametrize("dates,baseline,code", [
    ((), None, "DATES_REQUIRED"), (list(_DATES), None, "DATES_REQUIRED"),
    (_DATES[::-1], None, "DATE_ORDER_OR_DUPLICATE"), ((_DATES[0], _DATES[0]), None, "DATE_ORDER_OR_DUPLICATE"),
    (("2025-12-30", "2026-06-15"), None, "WINDOW_NOT_BOUND"),
    (("2026-08-14",), None, "WINDOW_NOT_BOUND"),
    (_DATES, _DATES[0], "INVALID_BASELINE_DATE"), (_DATES, "not-a-date", "INVALID_DATE"),
])
def test_invalid_window_is_rejected_before_io(benchmark_config, monkeypatch, dates, baseline, code):
    config = benchmark_config()
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid request reached a file")
    monkeypatch.setattr(Path, "open", forbidden)
    history = read_benchmarks(dates, baseline, config=config)
    assert history.error and not history.series and code in history.debug_error


@pytest.mark.parametrize("dates,baseline,code", [
    ((_DATES[0], _DATES[2]), None, "NONCONTIGUOUS_WINDOW_OR_BASELINE"),
    (_DATES[2:], _DATES[0], "NONCONTIGUOUS_WINDOW_OR_BASELINE"),
    ((_DATES[0], "2023-01-07"), None, "REQUIRED_DATE_MISSING"),
])
def test_no_missing_days_or_baseline_gaps_are_filled(benchmark_config, dates, baseline, code):
    history = read_benchmarks(dates, baseline, config=benchmark_config())
    assert history.error is None
    assert all(series.error and not series.points and code in series.debug_error for series in history.series)


@pytest.mark.parametrize("dates,window", [(_DATES, "historical"), (_LATER, "recorded_2026")])
def test_only_requested_window_files_are_opened_and_sources_remain_untouched(benchmark_config, monkeypatch, dates, window):
    config = benchmark_config()
    paths = (config.manifest_path, *(spec.path for spec in config.artifacts if spec.window == window))
    before = {path:path.read_bytes() for path in paths}
    opened, original_open = [], Path.open
    def guarded(path, mode="r", *args, **kwargs):
        assert path in paths and mode == "rb", f"Unrelated date window or raw source opened: {path}"
        opened.append(path)
        return original_open(path, mode, *args, **kwargs)
    with monkeypatch.context() as guard:
        guard.setattr(Path, "open", guarded)
        history = read_benchmarks(dates, config=config)
    assert history.error is None and all(series.error is None for series in history.series)
    assert set(opened) == set(paths) and {path:path.read_bytes() for path in paths} == before


@pytest.mark.parametrize("case,code", [
    ("future", "DATE_BOUNDARY_MISMATCH"), ("earlier", "DATE_BOUNDARY_MISMATCH"),
    ("symbol", "SECURITY_OR_PROVIDER_MISMATCH"), ("provider", "SECURITY_OR_PROVIDER_MISMATCH"),
    ("adjustment", "SECURITY_OR_PROVIDER_MISMATCH"), ("no_stats", "UNPROVEN_INPUT_BOUNDARY"),
    ("null_date", "UNPROVEN_INPUT_BOUNDARY"), ("lineage", "PROJECTION_LINEAGE_MISMATCH"),
])
def test_failed_input_stays_in_footer_and_other_etf_survives(benchmark_config, monkeypatch, case, code):
    changes = {"future":{"date":"2026-01-01"},"earlier":{"date":"2022-12-30"},
               "symbol":{"ticker":"OTHER"},"provider":{"source":"OTHER_PROVIDER"},
               "adjustment":{"adjustment":"raw"},"null_date":{"date":None}}
    config = benchmark_config(mutate_rows=(lambda rows:rows[1].update(changes[case])) if case in changes else None,
        statistics=case != "no_stats",
        mutate_metadata=(lambda metadata:metadata.update({b"source_csv_sha256":b"invalid"})) if case == "lineage" else None)
    target = next(spec.path for spec in config.artifacts if spec.symbol == "QQQ" and spec.window == "historical")
    raw = target.read_bytes()
    footer_start = len(raw) - 8 - struct.unpack("<I", raw[-8:-4])[0]
    spans, original_open, original_digest, original_parquet = [], Path.open, reader.hashlib.file_digest, reader.pq.ParquetFile
    def watched(path, mode="r", *args, **kwargs):
        handle = original_open(path, mode, *args, **kwargs)
        return _ReadWatch(handle, spans) if path == target else handle
    def digest(handle, *args, **kwargs):
        assert Path(handle.name) != target, "Failed input reached a full-file hash"
        return original_digest(handle, *args, **kwargs)
    def parquet(handle, *args, **kwargs):
        assert Path(handle.name) != target, "Failed input reached a data page"
        return original_parquet(handle, *args, **kwargs)
    monkeypatch.setattr(Path, "open", watched)
    monkeypatch.setattr(reader.hashlib, "file_digest", digest)
    monkeypatch.setattr(reader.pq, "ParquetFile", parquet)
    qqq, spy = read_benchmarks(_DATES, config=config).series
    assert qqq.error and not qqq.points and code in qqq.debug_error
    assert spy.error is None and len(spy.points) == 4
    assert spans and all(footer_start <= start <= end <= len(raw) for start,end in spans)


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf"), None])
def test_invalid_price_discards_only_affected_reference(benchmark_config, value):
    config = benchmark_config(mutate_rows=lambda rows:rows[1].update(open=value))
    qqq, spy = read_benchmarks(_DATES, config=config).series
    assert qqq.error and not qqq.points and "INVALID_OPEN_PRICE" in qqq.debug_error
    assert spy.error is None


@pytest.mark.parametrize("target", ["manifest", "QQQ"])
def test_changed_bytes_do_not_inherit_source_identity(benchmark_config, target):
    config = benchmark_config()
    path = config.manifest_path if target == "manifest" else config.artifacts[0].path
    data = bytearray(path.read_bytes())
    data[4] ^= 1
    path.write_bytes(data)
    history = read_benchmarks(_DATES, config=config)
    if target == "manifest":
        assert history.error and not history.series and "MANIFEST_IDENTITY_MISMATCH" in history.debug_error
    else:
        qqq, spy = history.series
        assert qqq.error and not qqq.points and "ARTIFACT_IDENTITY_MISMATCH" in qqq.debug_error
        assert spy.error is None


@pytest.mark.parametrize("mutation,code", [
    (lambda m:m.update(provider="YAHOO"), "SOURCE_IDENTITY_MISMATCH"),
    (lambda m:m.update(status="PASS_NEW_CONFIRMATION"), "SOURCE_IDENTITY_MISMATCH"),
    (lambda m:m["artifacts"][0].update(sha256="0"*64), "ARTIFACT_BINDING_MISMATCH"),
    (lambda m:m["sources"]["QQQ"].update(sha256="0"*64), "SOURCE_BINDING_MISMATCH"),
])
def test_self_consistent_manifest_cannot_change_declared_semantics(benchmark_config, mutation, code):
    history = read_benchmarks(_DATES, config=benchmark_config(mutate_manifest=mutation))
    if code == "SOURCE_IDENTITY_MISMATCH":
        assert history.error and not history.series and code in history.debug_error
    else:
        qqq, spy = history.series
        assert qqq.error and code in qqq.debug_error and not qqq.points
        assert spy.error is None
