"""Inspect exported HTML as a viewer would, using synthetic adapter outputs."""
from dataclasses import asdict, replace
import ast
from html.parser import HTMLParser
import importlib
from pathlib import Path
import shutil
import subprocess

import pytest

from apps.demo_console.adapters.decision_reader import load_overview


class _Document(HTMLParser):
    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.tags = []
        self.attributes = []
        self.fragments = []
        self._table = self._row = self._cell = None
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)
        if tag == "table":
            self._table = []
            self.tables.append(self._table)
        elif tag == "tr" and self._table is not None:
            self._row = []
            self._table.append(self._row)
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = []

    def handle_data(self, data):
        self.fragments.append(data)
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr":
            self._row = None
        elif tag == "table":
            self._table = None

    @property
    def text(self):
        return " ".join(self.fragments)


def _render(model, *, presentation=True):
    from apps.demo_console.tools.render_static_preview import render_html
    return render_html(model, presentation=presentation)


def test_preview_exposes_two_complete_real_record_tables(make_overview_config):
    model = load_overview(config=make_overview_config())
    assert model.error is model.debug_error is None
    document = _Document(_render(model))
    ticker_tables = [table for table in document.tables if table and "Ticker" in table[0]]
    assert len(ticker_tables) == 2, "Overview must distinguish Top20 and recorded holdings"
    expected = {row.ticker for row in model.ranking}
    assert expected == {row.ticker for row in model.holdings}
    for table in ticker_tables:
        assert len(table[1:]) == 20
        column = table[0].index("Ticker")
        assert {row[column] for row in table[1:]} == expected
    ranking_table = next(table for table in ticker_tables if "Rank" in table[0])
    assert [int(row[ranking_table[0].index("Rank")]) for row in ranking_table[1:]] == list(range(1, 21))
    assert "STATIC PREVIEW" in document.text.upper()
    assert "READ ONLY" in document.text.upper()
    assert "2025-12-02" in document.text


def test_static_export_reuses_presentation_components(make_overview_config):
    from apps.demo_console.components.pipeline_status import pipeline_html
    from apps.demo_console.components.portfolio_summary import summary_html, transition_html
    from apps.demo_console.components.top20_table import table_html
    from apps.demo_console.components.visuals import header_html, styles

    model = load_overview(config=make_overview_config())
    before = asdict(model)
    markup = _render(model)
    for component in (styles(), header_html(model), summary_html(model), transition_html(model),
                      pipeline_html(model.pipeline), table_html(model.ranking), table_html(model.holdings)):
        assert component in markup
    assert "Static export of the recorded snapshot" in markup
    assert "runtime acceptance is pending" not in markup.lower()
    assert 'class="metric"' not in markup, "Legacy six-card report returned"
    assert asdict(model) == before


def test_presentation_redacts_paths_hashes_and_debug_without_changing_model(make_overview_config):
    model = load_overview(config=make_overview_config())
    path = r"D:\private\synthetic-source.parquet"
    digest = "bd34" * 16
    raw_status = "SYNTHETIC_INTERNAL_FINAL_STATUS_WITH_LONG_TASK_IDENTIFIER"
    debug_error = r"SyntheticError: D:\private\unavailable-input.parquet"
    model = replace(model, debug_error=debug_error, provenance=replace(
        model.provenance, artifact_sources=(path,), artifact_hashes=((path, digest),),
        producer_identity=path, raw_status=raw_status,
    ))
    before = asdict(model)
    on, off = _render(model), _render(model, presentation=False)
    # A debug JSON block may encode backslashes; it still exposes the full value.
    on_text = _Document(on).text.replace("\\\\", "\\")
    off_text = _Document(off).text.replace("\\\\", "\\")
    for private in (path, digest, raw_status, debug_error):
        assert private not in on and private not in on_text
        assert private in off_text
    assert "synthetic-source.parquet" in on_text
    assert "not exposed" in on_text.lower().replace("_", " ")
    assert asdict(model) == before


@pytest.mark.parametrize("presentation", [True, False])
def test_preview_escapes_untrusted_artifact_text(make_overview_config, presentation):
    model = load_overview(config=make_overview_config())
    malicious_ticker = "<script>alert('synthetic')</script>"
    malicious_path = r"D:\private\<img src=x onerror=alert(1)>.parquet"
    model = replace(model, ranking=(replace(model.ranking[0], ticker=malicious_ticker),),
                    provenance=replace(model.provenance, artifact_sources=(malicious_path,)))
    markup = _render(model, presentation=presentation)
    document = _Document(markup)
    assert malicious_ticker not in markup
    assert malicious_ticker in document.text
    assert "script" not in document.tags and "img" not in document.tags
    assert not any(name.lower().startswith("on") for name, _ in document.attributes)
    assert "&lt;img" in markup


def test_unexposed_optional_fields_remain_unavailable_in_preview(make_overview_config):
    model = load_overview(config=make_overview_config(optional=False))
    assert model.error is model.debug_error is None
    document = _Document(_render(model))
    assert "N/A" in document.text
    assert "RX" in document.text and "unavailable" in document.text.lower()
    ticker_tables = [table for table in document.tables if table and "Ticker" in table[0]]
    for table in ticker_tables:
        assert "Score" not in table[0]
        assert "RX action" not in table[0] and "Raw A2 action" not in table[0]
        assert "Final action" not in table[0]
    assert model.rx_accepted_changes is model.rx_prevented_changes is None


def test_streamlit_modules_import_without_starting_app():
    pytest.importorskip("streamlit", reason="Streamlit is unavailable; actual import smoke cannot execute")
    for module in ("apps.demo_console.app", "apps.demo_console.pages.overview",
                   "apps.demo_console.components.top20_table"):
        assert importlib.import_module(module)


def test_current_streamlit_views_do_not_use_deprecated_api():
    root = Path(__file__).parents[1]
    paths = [root / "app.py", *sorted((root / "pages").glob("*.py")),
             *sorted((root / "components").glob("*.py"))]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            assert all(keyword.arg != "use_container_width" for keyword in node.keywords), path
            assert ast.unparse(node.func) not in {"st.components.v1.html", "st.components.v1.iframe"}, path


def test_cli_loads_effective_script_local_telemetry_setting(monkeypatch):
    pytest.importorskip("streamlit", reason="Effective Streamlit configuration requires its runtime")
    from click.testing import CliRunner
    from streamlit import config
    from streamlit.web import cli

    class ConfigCaptured(Exception):
        pass

    script = (Path(__file__).parents[1] / "app.py").resolve()
    options = {}
    original = cli.bootstrap.load_config_options
    # Restore Streamlit's process-global config after exercising its real CLI.
    monkeypatch.setattr(config, "_main_script_path", config._main_script_path)
    monkeypatch.setattr(config, "_config_options", config._config_options)

    def capture_config(*args, **kwargs):
        original(*args, **kwargs)
        options["telemetry"] = config.get_option("browser.gatherUsageStats")
        options["files"] = config.get_config_files("config.toml")
        # Stop before credentials, script imports, sockets, or server startup.
        raise ConfigCaptured()

    monkeypatch.setattr(cli.bootstrap, "load_config_options", capture_config)
    result = CliRunner().invoke(cli.main, ["run", str(script)])
    assert isinstance(result.exception, ConfigCaptured), result.output
    assert options["telemetry"] is False
    assert str(script.parent / ".streamlit" / "config.toml") in options["files"]


def test_local_launcher_is_valid_powershell_without_executing_it():
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        pytest.skip("PowerShell parser unavailable on this platform")
    path = (Path(__file__).parents[1] / "start.ps1").resolve()
    literal = "'" + str(path).replace("'", "''") + "'"
    command = ("$tokens=$null; $parseErrors=$null; "
               f"$null=[System.Management.Automation.Language.Parser]::ParseFile({literal},"
               "[ref]$tokens,[ref]$parseErrors); "
               "if ($parseErrors.Count) { $parseErrors | Out-String; exit 1 }")
    result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", command],
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
