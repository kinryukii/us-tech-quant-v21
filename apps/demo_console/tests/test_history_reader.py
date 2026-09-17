"""Historical display boundaries and joins using only task-owned synthetic files."""

from collections import Counter
from dataclasses import asdict, replace
import hashlib
from pathlib import Path
import struct

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from apps.demo_console.adapters import artifact_reader, portfolio_reader, ranking_reader
from apps.demo_console.adapters.decision_reader import load_history, load_overview
from apps.demo_console.tests.test_authority_identity import _repin_hash_rows
from apps.demo_console.tests.test_read_only_contract import _ReadWatch


def _rewrite_synthetic(config, field, mutate):
    """Rebind only an explicitly synthetic fixture to exercise semantic failures."""
    spec = getattr(config, field)
    assert spec.path.parent.name.startswith("test-")
    rows = pq.read_table(spec.path).to_pylist()
    mutate(rows)
    pq.write_table(pa.Table.from_pylist(rows), spec.path)
    spec = replace(spec, sha256=hashlib.sha256(spec.path.read_bytes()).hexdigest())
    config = replace(config, **{field: spec})
    def repin(rows):
        for row in rows:
            if row["absolute_path"] == str(spec.path):
                row["sha256"] = spec.sha256
    return _repin_hash_rows(config, repin)


@pytest.mark.parametrize("optional", [True, False])
def test_history_matches_every_single_day_field(make_overview_config, optional):
    config = make_overview_config(optional=optional)
    history = load_history(window=None, config=config)
    assert [model.decision_date for model in history] == ["2025-12-01", "2025-12-02"]
    assert all(model.error is None and model.debug_error is None for model in history)
    assert [asdict(model) for model in history] == [
        asdict(load_overview(model.decision_date, config=config)) for model in history]


def test_window_has_true_predecessor_and_stops_at_selected_date(make_overview_config):
    config = make_overview_config()
    history = load_history("2025-12-02", window=1, config=config)
    assert len(history) == 1
    model = history[0]
    assert model.previous_decision_date == "2025-12-01"
    assert model.previous_holdings == tuple(f"SYNTH_{number:02}" for number in range(1, 21))
    assert model.entered == ("SYNTH_21",) and model.exited == ("SYNTH_01",)
    assert all(row.rank_change == 1 for row in model.ranking[:-1])
    assert model.ranking[-1].rank_change is None
    early = load_history("2025-12-01", window=60, config=config)
    assert [snapshot.decision_date for snapshot in early] == ["2025-12-01"]
    assert "SYNTH_21" not in {row.ticker for row in early[0].ranking}
    assert early[0].previous_decision_date is None
    assert early[0].previous_holdings is None
    assert asdict(early[0]) == asdict(load_overview("2025-12-01", config=config))


@pytest.mark.parametrize("end_date,window,code", [
    ("2026-01-01", 60, "POST2025_DATE_BLOCKED"),
    ("2027-03-01", None, "POST2025_DATE_BLOCKED"),
    ("not-a-date", 60, "INVALID_DATE"),
    (None, 0, "INVALID_HISTORY_WINDOW"),
    (None, -1, "INVALID_HISTORY_WINDOW"),
    (None, True, "INVALID_HISTORY_WINDOW"),
    (None, 1.5, "INVALID_HISTORY_WINDOW"),
])
def test_invalid_history_request_opens_no_files(monkeypatch, end_date, window, code):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid history request reached file access")
    monkeypatch.setattr(Path, "open", forbidden)
    history = load_history(end_date, window=window)
    assert len(history) == 1 and history[0].error
    assert code in history[0].debug_error
    assert not history[0].ranking and not history[0].holdings


def test_missing_date_is_a_safe_error_not_an_empty_history(make_overview_config):
    history = load_history("2025-12-05", config=make_overview_config())
    assert len(history) == 1 and history[0].error
    assert "DATE_NOT_AVAILABLE" in history[0].debug_error


@pytest.mark.parametrize("field", ["ranking", "positions"])
def test_changed_identity_is_rejected_without_inventing_empty_holdings(make_overview_config, field):
    config = make_overview_config()
    spec = getattr(config, field)
    original = bytearray(spec.path.read_bytes())
    original[4] ^= 1  # Synthetic data-page byte; keep the exact footer readable.
    spec.path.write_bytes(original)
    history = load_history(window=None, config=config)
    assert all("ARTIFACT_IDENTITY_MISMATCH" in model.debug_error for model in history)
    if field == "ranking":
        assert len(history) == 1 and history[0].error and not history[0].ranking
    else:
        assert len(history) == 2
        for model in history:
            assert model.error is None and len(model.ranking) == 20
            assert not model.holdings and model.entered is model.exited is model.retained is None
            assert model.turnover is None
            assert {stage.name: stage.status for stage in model.pipeline}["Portfolio"] == "UNAVAILABLE"
            assert asdict(model) == asdict(load_overview(model.decision_date, config=config))


def test_mixed_year_ranking_reads_footer_only_even_for_an_earlier_end_date(make_overview_config, monkeypatch):
    config = make_overview_config()
    rows = pq.read_table(config.ranking.path).to_pylist()
    rows.append({**rows[-1], "signal_date": "2026-01-02", "ticker": "SYNTH_FUTURE"})
    pq.write_table(pa.Table.from_pylist(rows), config.ranking.path, row_group_size=20)
    raw = config.ranking.path.read_bytes()
    footer_start = len(raw) - 8 - struct.unpack("<I", raw[-8:-4])[0]
    spans = []
    original_open = Path.open
    def watch_open(path, mode="r", *args, **kwargs):
        handle = original_open(path, mode, *args, **kwargs)
        if path.resolve() == config.ranking.path.resolve():
            assert mode == "rb"
            return _ReadWatch(handle, spans)
        return handle
    def forbidden(*args, **kwargs):
        raise AssertionError("Mixed-year history reached a data page or full-file hash")
    monkeypatch.setattr(Path, "open", watch_open)
    monkeypatch.setattr(artifact_reader.hashlib, "file_digest", forbidden)
    monkeypatch.setattr(artifact_reader.pq, "ParquetFile", forbidden)
    history = load_history("2025-12-01", config=config)
    assert len(history) == 1 and history[0].error
    assert "POST2025_ARTIFACT_BLOCKED" in history[0].debug_error
    assert spans and all(footer_start <= start <= end <= len(raw) for start, end in spans)


def test_batch_and_single_day_share_predecessor_and_calendar_validation(make_overview_config):
    config = make_overview_config()
    def wrong_before(rows):
        for row in rows:
            if row["date"] == "2025-12-03" and row["ticker"] == "SYNTH_01":
                row["shares_before"] = 0.0
    config = _rewrite_synthetic(config, "positions", wrong_before)
    model = load_history(window=1, config=config)[0]
    assert "PREDECESSOR_HOLDINGS_MISMATCH" in model.debug_error
    assert model.previous_holdings is model.entered is model.exited is None
    assert asdict(model) == asdict(load_overview("2025-12-02", config=config))
    config = _rewrite_synthetic(config, "daily", lambda rows: rows.pop())
    history = load_history(window=None, config=config)
    assert all("SIGNAL_EXECUTION_ALIGNMENT_UNPROVEN" in model.debug_error for model in history)
    assert all(asdict(model) == asdict(load_overview(model.decision_date, config=config)) for model in history)


def test_invalid_date_slice_does_not_erase_independent_valid_history(make_overview_config):
    config = _rewrite_synthetic(make_overview_config(), "ranking", lambda rows: rows.pop())
    history = load_history(window=None, config=config)
    assert len(history) == 2 and history[0].error is None
    assert history[1].error and "INCOMPLETE_OR_INVALID_TOP20" in history[1].debug_error
    assert asdict(history[1]) == asdict(load_overview("2025-12-02", config=config))


def test_history_opens_each_original_file_once_independent_of_window(make_overview_config, monkeypatch):
    config = make_overview_config()
    paths = [config.manifest_path, config.hash_manifest_path,
             config.ranking.path, config.positions.path, config.daily.path]
    before = {path.resolve(): path.read_bytes() for path in paths}
    counts, projections = Counter(), {}
    original_open = Path.open
    original_projection = artifact_reader.read_frozen_parquet
    def counted_open(path, mode="r", *args, **kwargs):
        if path.resolve() in before:
            assert mode == "rb"
            counts[path.resolve()] += 1
        return original_open(path, mode, *args, **kwargs)
    def projected(spec, columns, filters=None, optional_columns=()):
        projections[spec.path] = set(columns) | set(optional_columns)
        return original_projection(spec, columns, filters, optional_columns)
    with monkeypatch.context() as guard:
        guard.setattr(Path, "open", counted_open)
        guard.setattr(ranking_reader, "read_frozen_parquet", projected)
        guard.setattr(portfolio_reader, "read_frozen_parquet", projected)
        for window in (1, None):
            counts.clear()
            history = load_history(window=window, config=config)
            assert len(history) == (1 if window == 1 else 2)
            assert all(model.error is model.debug_error is None for model in history)
            assert counts == Counter({path: 1 for path in before})
    assert projections == {
        config.ranking.path: {"signal_date", "ticker", "a2_rank", "a2_prediction", "universe_size"},
        config.positions.path: {"date", "previous_date", "ticker", "shares_before", "shares_after", "model", "portfolio"},
        config.daily.path: {"execution_date", "model", "reconstructed_turnover", "actual_risky_name_count"},
    }
    assert {path: path.read_bytes() for path in before} == before
