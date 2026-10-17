"""Source-only technology explanations; synthetic UI, no data/model/account access."""
import ast
import builtins
import hashlib
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from apps.demo_console.components import technology_catalog as technology
from apps.demo_console.i18n import catalog, language_scope, tr


def _script():
    import streamlit as st
    from apps.demo_console.components.technology_catalog import render_technology_explorer
    from apps.demo_console.i18n import language_scope
    with language_scope(st.session_state.get("test_language", "en")):
        render_technology_explorer()


def test_original_six_capabilities_are_single_byte_preserved_definition_and_reexport():
    source = Path(technology.__file__).read_bytes()
    block = source[source.index(b"@dataclass(frozen=True)"):source.index(b"TECHNOLOGIES =")]
    assert hashlib.sha256(block).hexdigest() == "0b53e01e7a495ffc05bf76a2f40eaa58e329a210cb49b61c3ad21dfdfc3cdeb9"
    assert len(technology.CAPABILITIES) == 6 and len(technology.TECHNOLOGIES) == 11
    assert technology.TECHNOLOGIES[:6] == technology.CAPABILITIES
    assert all(isinstance(item, technology.Capability) for item in technology.TECHNOLOGIES)
    tree = ast.parse(Path(technology.__file__).with_name("system_overview.py").read_text(encoding="utf-8"))
    imports = [node for node in tree.body if isinstance(node, ast.ImportFrom)
               and node.module == "apps.demo_console.components.technology_catalog"]
    assert len(imports) == 1 and {item.name for item in imports[0].names} == {"Capability", "CAPABILITIES"}
    assert not any(isinstance(node, ast.ClassDef) and node.name == "Capability" for node in tree.body)
    assert not any(isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "CAPABILITIES"
               for t in node.targets) for node in tree.body)


def test_lightweight_import_does_not_load_research_or_optional_tools():
    script = r"""
import importlib.abc,sys
import streamlit
blocked=('apps.demo_console.adapters','apps.demo_console.components.system_overview',
         'apps.demo_console.components.ml_story','apps.demo_console.components.pit_timing',
         'scripts.research','scripts.v22','pandas','altair','torch','xgboost')
class Guard(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if any(fullname==p or fullname.startswith(p+'.') for p in blocked):
   raise AssertionError('Unexpected technology explorer dependency: '+fullname)
sys.meta_path.insert(0,Guard())
from apps.demo_console.components import technology_catalog
assert len(technology_catalog.TECHNOLOGIES)==11
assert not any(any(name==p or name.startswith(p+'.') for p in blocked) for name in sys.modules)
print('technology import data-free PASS')
"""
    result = subprocess.run([sys.executable, "-B", "-c", script], cwd=Path(__file__).parents[3],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "technology import data-free PASS"


@pytest.fixture
def explorer(monkeypatch):
    from streamlit.testing.v1 import AppTest
    original = builtins.__import__
    blocked = ("apps.demo_console.adapters", "scripts.research", "scripts.v22",
        "apps.demo_console.components.system_overview", "apps.demo_console.components.ml_story",
        "apps.demo_console.components.pit_timing")
    def guarded(name, *args, **kwargs):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in blocked):
            raise AssertionError("Closed technology detail imported a business or optional reader: " + name)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    app = AppTest.from_function(_script, default_timeout=20).run()
    assert not app.exception
    return app


def test_every_capability_is_editorial_and_closed_tools_load_nothing(explorer):
    titles = tuple(item.title for item in technology.TECHNOLOGIES)
    for title in titles:
        explorer.selectbox(key="technology_capability").select(title).run()
        assert not explorer.exception
        assert not explorer.get("iframe") and not explorer.dataframe and not explorer.get("vega_lite_chart")
        assert not any(widget.key in ("decision_date", "workspace_strategy", "workspace_sample") for widget in explorer.selectbox)
        assert not explorer.code  # Engineering paths are collapsed.
        item = next(item for item in technology.TECHNOLOGIES if item.title == title)
        assert any(item.question in node.value for node in explorer.markdown)


@pytest.mark.parametrize("language", ("en", "zh", "ja"))
def test_source_fields_and_native_selection_translate_without_changing_identity(explorer, language):
    chosen = "Machine learning methods"
    explorer.selectbox(key="technology_capability").select(chosen).run()
    explorer.session_state["test_language"] = language
    explorer.run()
    assert not explorer.exception
    widget = explorer.selectbox(key="technology_capability")
    assert widget.value == chosen and explorer.session_state["technology_capability"] == chosen
    with language_scope(language):
        assert widget.proto.raw_value == tr(chosen) and widget.proto.set_value
        for capability in technology.TECHNOLOGIES:
            for message in (capability.title, capability.question, capability.mechanism, capability.evidence, capability.scope):
                translated = tr(message)
                assert translated.strip()
                if language != "en":
                    assert catalog()[message][language] == translated and translated != message


def test_optional_atlas_and_synthetic_timing_load_only_after_native_open(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.tests.test_localized_tabs import _open_expander
    calls = []
    atlas = ModuleType("apps.demo_console.components.ml_story")
    atlas.render_feature_atlas = lambda: calls.append("source_atlas")
    pit = ModuleType("apps.demo_console.components.pit_timing")
    pit.render_pit_timing = lambda: calls.append("synthetic_timing")
    monkeypatch.setitem(sys.modules, atlas.__name__, atlas)
    monkeypatch.setitem(sys.modules, pit.__name__, pit)
    app = AppTest.from_function(_script, default_timeout=20).run()
    assert not app.exception and calls == []
    app.selectbox(key="technology_capability").select("Feature engineering").run()
    assert not app.exception and calls == []
    _open_expander(app, "technology_feature_atlas")
    assert not app.exception and calls == ["source_atlas"]
    app.selectbox(key="technology_capability").select("Information timing").run()
    assert not app.exception and calls == ["source_atlas"]
    _open_expander(app, "technology_pit_drill")
    assert not app.exception and calls == ["source_atlas", "synthetic_timing"]


def test_visible_capability_choices_share_canonical_selection_and_preserve_research_context(explorer):
    explorer.session_state["workspace_strategy"] = "R7_GROSS_LINEAR"
    explorer.session_state["decision_date"] = "2025-12-02"
    explorer.button(key="technology_quick_machine_learning_methods").click().run()
    assert not explorer.exception
    assert explorer.selectbox(key="technology_capability").value == "Machine learning methods"
    assert explorer.session_state["workspace_strategy"] == "R7_GROSS_LINEAR"
    assert explorer.session_state["decision_date"] == "2025-12-02"
    assert not explorer.dataframe and not explorer.get("iframe")
