"""Installed Streamlit config lookup only; no server, account or data reads."""
from pathlib import Path
import tomllib

_DEMO = Path(__file__).parents[1]
_REPO = _DEMO.parents[1]


def test_project_working_directory_loads_original_config_and_keeps_cli_runtime_flags(monkeypatch, tmp_path):
    from streamlit import config, file_util

    monkeypatch.chdir(_DEMO)
    monkeypatch.setattr(config, "_main_script_path", str(_DEMO / "launch/app.py"))
    # Never read a developer's global config while testing project discovery.
    monkeypatch.setattr(file_util, "get_streamlit_file_path", lambda name: str(tmp_path / "global" / name))
    monkeypatch.setattr(config, "_config_options", None)
    for name in tuple(__import__("os").environ):
        if name.startswith("STREAMLIT_"):
            monkeypatch.delenv(name)
    project = _DEMO / ".streamlit/config.toml"
    files = list(map(Path, config.get_config_files("config.toml")))
    assert project in files
    flags = {"server.address": "127.0.0.1", "server.port": 18506,
        "server.headless": True, "server.fileWatcherType": "none", "client.showErrorDetails": False}
    options = config.get_config_options(force_reparse=True, options_from_flags=flags)
    expected = tomllib.loads(project.read_text(encoding="utf-8"))
    def flattened(values, prefix=""):
        for name, value in values.items():
            key = prefix + name
            if isinstance(value, dict):
                yield from flattened(value, key + ".")
            else:
                yield key, value
    for key, value in flattened(expected):
        assert options[key].value == value
        if key not in flags:
            assert Path(options[key].where_defined) == project
    assert all(options[key].value == value for key, value in flags.items())


def test_old_repo_working_directory_skips_the_parent_config_of_thin_entry(monkeypatch, tmp_path):
    from streamlit import config, file_util

    monkeypatch.chdir(_REPO)
    monkeypatch.setattr(config, "_main_script_path", str(_DEMO / "launch/app.py"))
    monkeypatch.setattr(file_util, "get_streamlit_file_path", lambda name: str(tmp_path / "global" / name))
    files = list(map(Path, config.get_config_files("config.toml")))
    assert _DEMO / ".streamlit/config.toml" not in files
    assert _REPO / ".streamlit/config.toml" in files
    assert _DEMO / "launch/.streamlit/config.toml" in files

def test_native_palette_matches_shared_workspace_theme():
    import re
    shared = (_REPO / "apps/shared_ui/theme.css").read_text(encoding="utf-8")
    tokens = dict(re.findall(r"(--ui-[a-z-]+)\s*:\s*([^;]+);", shared))
    theme = tomllib.loads((_DEMO / ".streamlit/config.toml").read_text(encoding="utf-8"))["theme"]
    for option, token in {
        "primaryColor": "--ui-accent", "backgroundColor": "--ui-bg",
        "secondaryBackgroundColor": "--ui-soft", "textColor": "--ui-text",
        "borderColor": "--ui-line", "dataframeHeaderBackgroundColor": "--ui-soft",
        "dataframeBorderColor": "--ui-line", "baseRadius": "--ui-radius",
    }.items():
        assert theme[option] == tokens[token].strip()
    assert theme["sidebar"]["backgroundColor"] == tokens["--ui-nav"].strip()
