"""Synthetic joins, unavailable fields and safe UI errors, without research runs."""
from dataclasses import asdict, replace
import builtins
from html.parser import HTMLParser
import io
import os
from pathlib import Path
import socket
import subprocess

import pytest

from apps.demo_console.adapters.decision_reader import load_overview
from apps.demo_console.adapters.system_status_reader import pipeline_stages


class _RecordedTables(HTMLParser):
    """Read semantic HTML tables emitted by st.html, including nested badges."""

    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._table = self._row = self._cell = None
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._table = []
            self.tables.append(self._table)
        elif tag == "tr" and self._table is not None:
            self._row = []
            self._table.append(self._row)
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"th", "td"} and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr":
            self._row = None
        elif tag == "table":
            self._table = None


@pytest.mark.parametrize("optional", [True, False])
def test_overview_constructs_truthful_snapshot_and_transition(make_overview_config, optional):
    config = make_overview_config(optional=optional)
    model = load_overview(config=config)
    assert model.error is None and model.debug_error is None
    assert model.decision_date == "2025-12-02"
    assert model.available_dates == ("2025-12-01", "2025-12-02")
    assert model.provenance.execution_date == "2025-12-03"
    assert len(model.ranking) == len(model.holdings) == 20
    assert model.entered == ("SYNTH_21",)
    assert model.exited == ("SYNTH_01",)
    assert model.retained == tuple(f"SYNTH_{i:02}" for i in range(2, 21))
    assert model.previous_holdings == tuple(f"SYNTH_{i:02}" for i in range(1, 21))
    assert model.turnover == (0.137 if optional else None)
    assert model.eligible_universe_count == (87 if optional else None)
    assert all(row.rank_change == 1 for row in model.ranking[:-1])
    assert model.ranking[-1].rank_change is None
    assert all(row.score is None and row.rank is None for row in model.holdings)
    assert all(row.rx_action is None and row.raw_action is None and row.final_action is None
               for row in (*model.ranking, *model.holdings))
    assert model.rx_accepted_changes is model.rx_prevented_changes is model.raw_proposed_changes is None
    assert {stage.name: stage.status for stage in model.pipeline}["RX"] == "NOT_EXPOSED"


def test_missing_manifest_becomes_safe_model_error(make_overview_config):
    config = make_overview_config()
    config = replace(config, manifest_path=config.manifest_path.parent / "missing.json")
    model = load_overview(config=config)
    assert model.error and "Traceback" not in model.error
    assert str(config.manifest_path) not in model.error
    assert "FileNotFoundError" in model.debug_error
    assert not model.ranking and not model.holdings
    assert model.pipeline[0].status == "BLOCKED"


def test_missing_decision_date_has_clear_error(make_overview_config):
    model = load_overview("2025-12-05", config=make_overview_config())
    assert model.error and "DATE_NOT_AVAILABLE" in model.debug_error
    assert not model.ranking and not model.holdings


def test_post2025_request_opens_no_artifacts(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Post-2025 request opened an artifact")
    monkeypatch.setattr(Path, "open", forbidden)
    model = load_overview("2026-01-01")
    assert model.error and "POST2025_DATE_BLOCKED" in model.debug_error


def test_partial_portfolio_failure_preserves_verified_top20(make_overview_config):
    config = make_overview_config()
    # Corrupt our own synthetic fixture after its synthetic identity was bound.
    config.positions.path.write_bytes(b"synthetic invalid parquet")
    model = load_overview(config=config)
    assert model.error is None and model.debug_error
    assert len(model.ranking) == 20 and not model.holdings
    assert model.entered is model.exited is model.retained is model.turnover is None
    assert {stage.name: stage.status for stage in model.pipeline}["Portfolio"] == "UNAVAILABLE"
    assert any("Portfolio evidence" in text for text in model.limitations)


def test_predecessor_mismatch_is_not_silently_reconciled(make_overview_config, monkeypatch):
    from apps.demo_console.adapters import decision_reader
    config = make_overview_config()
    original = decision_reader.read_portfolio

    def inconsistent(spec, execution):
        rows, before, previous = original(spec, execution)
        return (rows, ("SYNTH_UNEXPLAINED",), previous) if execution == "2025-12-03" else (rows, before, previous)

    monkeypatch.setattr(decision_reader, "read_portfolio", inconsistent)
    model = load_overview(config=config)
    assert "PREDECESSOR_HOLDINGS_MISMATCH" in model.debug_error
    assert len(model.ranking) == 20 and not model.holdings
    assert model.previous_holdings is model.entered is model.exited is None


def test_missing_pit_receipt_does_not_become_available():
    stages = {stage.name: stage.status for stage in pipeline_stages({}, True, False)}
    assert stages["PIT / Eligibility"] == "NOT_EXPOSED"
    assert stages["Features"] == stages["RX"] == "NOT_EXPOSED"
    assert stages["Portfolio"] == "UNAVAILABLE"


def test_complete_overview_performs_read_only_input_opens(make_overview_config, monkeypatch):
    config = make_overview_config()
    protected = {spec.path.resolve() for spec in (config.ranking, config.positions, config.daily)}
    protected.update((config.manifest_path.resolve(), config.hash_manifest_path.resolve()))
    original = Path.open
    observed = set()

    def guarded(path, mode="r", *args, **kwargs):
        if path.resolve() in protected:
            assert mode == "rb", "Overview attempted non-read-only access to a source"
            observed.add(path.resolve())
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    model = load_overview(config=config)
    assert model.error is model.debug_error is None
    assert observed == protected


def test_overview_has_no_write_network_broker_git_or_producer_side_effects(make_overview_config, monkeypatch):
    config = make_overview_config()
    paths = [spec.path for spec in (config.ranking, config.positions, config.daily)]
    paths.extend((config.manifest_path, config.hash_manifest_path))
    before = {path: path.read_bytes() for path in paths}

    def read_only(original):
        def guarded(file, mode="r", *args, **kwargs):
            assert not any(flag in mode for flag in "wax+"), "Reader attempted a filesystem write"
            return original(file, mode, *args, **kwargs)
        return guarded

    original_os_open = os.open

    def os_read_only(file, flags, *args, **kwargs):
        assert flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC) == 0
        return original_os_open(file, flags, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("Reader attempted network, process execution or directory mutation")

    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", read_only(builtins.open))
        guard.setattr(io, "open", read_only(io.open))
        guard.setattr(os, "open", os_read_only)
        guard.setattr(os, "mkdir", forbidden)
        guard.setattr(os, "system", forbidden)
        guard.setattr(subprocess, "run", forbidden)
        guard.setattr(subprocess, "Popen", forbidden)
        guard.setattr(socket, "socket", forbidden)
        guard.setattr(socket, "create_connection", forbidden)
        model = load_overview(config=config)
    assert model.error is model.debug_error is None
    assert len(model.holdings) == len(model.ranking) == 20
    assert {path: path.read_bytes() for path in paths} == before


def test_streamlit_overview_and_presentation_toggle(make_overview_config, monkeypatch, caplog,
                                                 landing_without_performance):
    pytest.importorskip("streamlit", reason="Streamlit runtime is required for UI execution smoke")
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.adapters import decision_reader

    config = make_overview_config()
    models = []
    debug_marker = "Synthetic debug evidence: private source inspection"

    def synthetic_overview(date=None):
        model = replace(load_overview(date, config=config), debug_error=debug_marker)
        models.append(asdict(model))
        return model

    def rendered_content(app):
        content = []
        for element in app:
            # Include labels/help as well as values, including collapsed content.
            if hasattr(element, "proto"):
                content.append(str(element.proto))
            try:
                value = element.value
            except AttributeError:
                continue
            if hasattr(value, "to_numpy"):
                content.extend(str(cell) for cell in value.to_numpy().flat)
            else:
                content.append(str(value))
        return "\n".join(content).replace("\\\\", "\\").replace("\\/", "/")

    def assert_record_tables(app, *, first=2, has_previous_rank=True):
        expected = {f"SYNTH_{number:02}" for number in range(first, first + 20)}
        for source in ("Raw A2 Top20", "Historical holdings"):
            app.selectbox(key="record_set").select(source).run()
            assert not app.exception and not app.error
            markup = "\n".join(element.proto.body for element in app.get("html"))
            tables = [table for table in _RecordedTables(markup).tables
                      if table and "Ticker" in table[0]]
            assert len(tables) == 1, "The selected record set has one complete table"
            table = tables[0]
            assert len(table[1:]) == 20
            ticker_column = table[0].index("Ticker")
            assert {row[ticker_column] for row in table[1:]} == expected
            assert not {"RX action", "Final action", "Raw A2 action"}.intersection(table[0])
            if source == "Historical holdings":
                assert not {"Rank", "Score", "ΔRank"}.intersection(table[0])
                continue
            rank_column = table[0].index("Rank")
            assert [int(row[rank_column]) for row in table[1:]] == list(range(1, 21))
            assert ("ΔRank" in table[0]) is has_previous_rank
            if has_previous_rank:
                change_column = table[0].index("ΔRank")
                assert all(row[change_column] == "↑ +1" for row in table[1:-1])
                assert table[-1][change_column] == "—"

    monkeypatch.setattr(decision_reader, "load_overview", synthetic_overview)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=20)
    app.run()
    assert not app.exception and not app.error
    assert app.radio(key="workspace").value == "Overview"
    assert app.toggle[0].value is True
    markup = "\n".join(element.proto.body for element in app.get("html"))
    assert not [table for table in _RecordedTables(markup).tables if table and "Ticker" in table[0]]
    assert 'class="uq-case-chain" data-ticker="SYNTH_02"' in markup
    assert app.selectbox(key="system_focus_ticker").value == "SYNTH_02"
    assert not any(element.label == "Selected decision · full portfolio overview"
                   for element in (*app.expander, *app.status))
    before = models[-1]
    presentation_text = rendered_content(app)
    assert "RX" in presentation_text and "NOT EXPOSED" in presentation_text
    private_values = list(before["provenance"]["artifact_sources"])
    private_values.extend(digest for _, digest in before["provenance"]["artifact_hashes"])
    private_values.extend((debug_marker, before["provenance"]["raw_status"]))
    assert all(value not in presentation_text for value in private_values if value)
    # Complete records belong to their real workspace and native source picker.
    app.radio(key="workspace").set_value("Portfolio").run()
    assert_record_tables(app)
    assert all(value not in rendered_content(app) for value in private_values if value)
    assert models[-1] == before, "Workspace or record-set selection changed the data model"
    app.toggle[0].set_value(False).run()
    assert not app.exception and not app.error
    assert_record_tables(app)
    debug_text = rendered_content(app)
    assert all(value in debug_text for value in private_values if value)
    assert models[-1] == before, "Presentation toggle changed the data model"
    # Changing the date must replace the whole snapshot, including table rows,
    # rank comparisons, the header, and the subsequent execution date.
    app.selectbox(key="decision_date").select("2025-12-01").run()
    assert not app.exception and not app.error
    assert_record_tables(app, first=1, has_previous_rank=False)
    earlier = models[-1]
    assert earlier["decision_date"] == "2025-12-01"
    assert earlier["provenance"]["execution_date"] == "2025-12-02"
    html = "\n".join(element.proto.body for element in app.get("html"))
    assert app.selectbox(key="decision_date").value == "2025-12-01"
    assert 'data-decision-date="2025-12-01"' in html
    context = next(element.proto.body for element in app.get("html")
                   if 'class="uq-case-context"' in element.proto.body)
    assert "<small>Execution date</small><b>2025-12-02</b>" in context
    assert 'data-decision-date="2025-12-02"' not in html
    app.selectbox(key="decision_date").select("2025-12-02").run()
    assert not app.exception and not app.error
    assert_record_tables(app)
    assert models[-1] == before, "Returning to a date changed its recorded model"
    assert "use_container_width" not in caplog.text
    assert "deprecated" not in caplog.text.lower()
