"""Data-free architecture exhibit and retained frozen-method case contracts."""
import builtins
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from apps.demo_console.components import strategy_workbench as workbench
from apps.demo_console.components import architecture_exhibit as exhibit
from apps.demo_console.i18n import language_scope
from apps.moomoo_trading_component.moomoo_component.strategy import (
    ACTIVE_PAPER_STRATEGY_IDS, APPLIED_STRATEGY_NAMES, QUERYABLE_STRATEGY_IDS,
)


def test_original_label_api_is_same_object_and_exact_canonical_order():
    from apps.demo_console.pages import selected_strategies as previous
    expected = {sid: "HGB + diagonal risk" if sid == "HGB_DIAG_5" else "Same-pool RAW · Consensus Top100" if sid == "RAW_s10" else APPLIED_STRATEGY_NAMES[sid]
                for sid in QUERYABLE_STRATEGY_IDS}
    assert workbench.WORKSPACE_STRATEGIES == expected
    assert tuple(workbench.WORKSPACE_STRATEGIES) == QUERYABLE_STRATEGY_IDS
    for name in ("WORKSPACE_STRATEGIES", "LEGACY_STRATEGIES", "strategy_label", "short_strategy_label"):
        assert getattr(previous, name) is getattr(workbench, name)
    assert workbench.LEGACY_STRATEGIES == {"HGB_FACTOR_5": "HGB + factor / shrinkage risk"}
    assert workbench.strategy_label("NOT_REGISTERED") == "NOT_REGISTERED"
    assert workbench.short_strategy_label("HGB_DIAG_5") == "HGB \u00b7 Diagonal"


@pytest.fixture
def homepage(monkeypatch):
    from streamlit.testing.v1 import AppTest
    imports = []
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name.startswith("apps.demo_console.adapters") or name == "apps.demo_console.pages.selected_strategies":
            imports.append(name)
            raise AssertionError("Technical exhibit imported a research reader")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    app = AppTest.from_string("""
import streamlit as st
import importlib
from apps.demo_console.i18n import language_scope
from apps.demo_console.components import architecture_exhibit
# AppTest creates a fresh Runtime; reload the module-level CCv2 registration there.
importlib.reload(architecture_exhibit)
from apps.demo_console.components.strategy_workbench import render_strategy_workbench
with language_scope(st.session_state.get('language', 'en')):
    render_strategy_workbench({}, st.session_state.get('presentation_mode', True))
""", default_timeout=20)
    app.session_state["language"] = "en"
    app.session_state["presentation_mode"] = True
    app.session_state["workspace_strategy"] = "R10_DIRECT_H5_RIDGE_MID"
    app.session_state["workspace_sample"] = "historical"
    app.session_state["decision_date"] = "2025-12-02"
    app.run()
    assert not app.exception
    yield app
    assert not imports


def test_homepage_mounts_one_v2_exhibit_without_case_cards_or_data(homepage):
    assert len(homepage.get("bidi_component")) == 1
    from apps.demo_console.components.technology_catalog import QUICK_CAPABILITIES
    quick = {"technology_quick_" + title.lower().replace(" ", "_") for title in QUICK_CAPABILITIES}
    assert {node.key for node in homepage.button} == {"exhibit_open_ml", "exhibit_open_charts", "exhibit_open_simulation"} | quick
    assert not homepage.dataframe and not homepage.get("iframe")
    assert not homepage.get("page_link")
    assert set(workbench.METHOD_EXPLANATIONS) == set(QUERYABLE_STRATEGY_IDS)
    assert all(word not in exhibit.HTML for word in ("Sharpe", "Cumulative return", "50.94"))
    assert exhibit.HTML.count('class="stage"') == 4
    assert exhibit.HTML.count('class="rail ') == 2


def test_language_mode_and_missing_date_do_not_reset_global_context(homepage):
    for language, mode in (("zh", False), ("ja", True), ("en", False)):
        homepage.session_state["language"] = language
        homepage.session_state["presentation_mode"] = mode
        homepage.session_state["decision_date"] = None
        homepage.run()
        assert not homepage.exception
        assert homepage.session_state["workspace_strategy"] == "R10_DIRECT_H5_RIDGE_MID"
        assert homepage.session_state["workspace_sample"] == "historical"
        assert homepage.session_state["decision_date"] is None
        assert len(homepage.get("bidi_component")) == 1


def test_cases_preserve_focus_and_original_observation_callback():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string("""
from apps.demo_console.components.strategy_workbench import render_strategy_cases
render_strategy_cases({})
""", default_timeout=20)
    app.session_state["workspace_strategy"] = "RAW_A2"
    app.session_state["decision_date"] = "2025-12-02"
    app.session_state["_rendered_workspace"] = "old-model"
    app.session_state["_research_case_ticker"] = "old-stock"
    app.run()
    app.button(key="workbench_method_R10_DIRECT_MEAN4_ELASTICNET_MID").click().run()
    assert not app.exception
    assert app.session_state["workspace_strategy"] == "R10_DIRECT_MEAN4_ELASTICNET_MID"
    assert app.session_state["decision_date"] == "2025-12-02"
    assert "_rendered_workspace" not in app.session_state
    assert "_research_case_ticker" not in app.session_state
    assert len(app.get("bidi_component")) == 1
    payload=json.loads(app.get("bidi_component")[0].proto.json)
    assert payload["strategy_id"]=="R10_DIRECT_MEAN4_ELASTICNET_MID"
    assert not app.get("page_link")
    assert len(app.button) == 7
    assert app.button(key="workbench_open_ml").label == "Open this ML workbench"
    assert app.button(key="workbench_open_decisions").label == "View recorded decisions"


def test_cold_component_import_has_no_research_or_numeric_dependencies():
    script = r"""
import importlib.abc,json,sys
import streamlit
blocked=('apps.demo_console.adapters','apps.demo_console.pages.selected_strategies','pandas','altair','torch','xgboost')
class Guard(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if any(fullname==prefix or fullname.startswith(prefix+'.') for prefix in blocked):
   raise AssertionError('Unexpected homepage dependency: '+fullname)
sys.meta_path.insert(0,Guard())
from apps.demo_console.components import strategy_workbench,architecture_exhibit
print(json.dumps({'forbidden_loaded':[name for name in sys.modules if any(name==p or name.startswith(p+'.') for p in blocked)]}))
"""
    result = subprocess.run([sys.executable, "-B", "-c", script], cwd=Path(__file__).resolve().parents[3],
                            text=True, capture_output=True, timeout=20, check=True)
    assert json.loads(result.stdout) == {"forbidden_loaded": []}


@pytest.mark.parametrize("language", ("en", "zh", "ja"))
def test_payload_is_localized_editorial_content_only(language):
    with language_scope(language):
        payload = exhibit.architecture_payload(False, motion_enabled=False)
    assert payload["language"] == language and payload["mode"] == "research"
    assert payload["motion_enabled"] is False
    assert [stage["id"] for stage in payload["stages"]] == ["pit", "inference", "risk", "execution", "lineage", "resources"]
    assert all(set(stage) == {"id", "title", "short", "input", "process", "output"} for stage in payload["stages"])
    assert all(isinstance(value, str) for stage in payload["stages"] for value in stage.values())
    assert not any(word in json.dumps(payload).lower() for word in ("account_id", "balance", "pnl", "probability"))


def test_accessibility_responsiveness_and_no_event_path_to_python():
    assert 'aria-live="polite"' in exhibit.HTML and 'aria-pressed="true"' in exhibit.HTML
    assert 'type="button"' in exhibit.HTML and 'aria-hidden="true"' in exhibit.HTML
    assert "max-width:560px" in exhibit.CSS and "repeat(2,minmax(0,1fr))" in exhibit.CSS
    assert "prefers-reduced-motion:reduce" in exhibit.CSS and "focus-visible" in exhibit.CSS
    assert 'data-motion="off"' in exhibit.CSS and "root.dataset.motion" in exhibit.JS
    assert "ArrowRight" in exhibit.JS and "ArrowLeft" in exhibit.JS
    assert "textContent" in exhibit.JS and "innerHTML" not in exhibit.JS
    assert "return () =>" in exhibit.JS
    for forbidden in ("fetch(", "XMLHttpRequest", "setStateValue", "setTriggerValue", "document.", "window.", "setInterval"):
        assert forbidden not in exhibit.JS


def test_actual_frontend_handlers_select_follow_keyboard_and_clean_up():
    """Run the shipped JS against minimal DOM interfaces; browser geometry is separately reviewed."""
    # Prefer the actual executable on PATH so the bounded Windows runner can
    # observe its exit and stdout directly rather than a Volta launcher.
    direct_path = os.pathsep.join(part for part in os.environ.get("PATH", "").split(os.pathsep)
                                  if Path(part).name.lower() != "volta")
    node = shutil.which("node", path=direct_path) or shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable for the component event check")
    harness = r"""
const fs = require('fs');
const {js,data} = JSON.parse(fs.readFileSync(0,'utf8'));
function el(dataset={}) {return {dataset,attributes:{},textContent:'',setAttribute(k,v){this.attributes[k]=v;},focus(){this.focused=true;}};}
const buttons = ['lineage','pit','inference','risk','execution','resources'].map(id=>el({stage:id}));
const copy = Object.keys(data.copy).map(key=>el({copy:key}));
const detail = ['input','process','output'].map(key=>el({detail:key}));
const title=el(), number=el(), follow=el(), stages=el();
const labels = Object.fromEntries(data.stages.flatMap(s=>[[`[data-title="${s.id}"]`,el()],[`[data-short="${s.id}"]`,el()]]));
const root = el();
root.querySelectorAll = query => ({'[data-copy]':copy,'[data-stage]':buttons,'[data-detail]':detail}[query]||[]);
root.querySelector = query => ({'.stages':stages,'.detail h2':title,'.detail-number':number,'.follow':follow}[query]||labels[query]);
const renderer = new Function(js.replace('export default function(component)', 'return function(component)'))();
const cleanup = renderer({parentElement:{querySelector:q=>q==='.exhibit'?root:null}, data});
function check(value,message) {if(!value)throw Error(message);}
check(root.dataset.selected==='pit','default stage');
buttons.find(b=>b.dataset.stage==='risk').onclick();
check(root.dataset.selected==='risk' && title.textContent===data.stages[2].title,'click updates title');
check(detail[1].textContent===data.stages[2].process,'click updates process');
check(buttons.filter(b=>b.attributes['aria-pressed']==='true').length===1,'single selected stage');
follow.onclick(); check(root.dataset.selected==='execution','follow advances');
follow.onclick(); check(root.dataset.selected==='pit','follow wraps');
let prevented=false;
buttons[1].onkeydown({key:'ArrowRight',preventDefault(){prevented=true;}});
check(prevented && buttons[2].focused && root.dataset.selected==='inference','keyboard advances and focuses');
buttons[2].onkeydown({key:'End',preventDefault(){}});
check(root.dataset.selected==='resources','keyboard end');
follow.onclick(); check(root.dataset.selected==='pit','resource rail starts the main flow');
buttons[0].onclick(); check(root.dataset.selected==='lineage','crosscut rail clickable');
follow.onclick(); check(root.dataset.selected==='pit','lineage rail starts the main flow');
root.dataset.selected='invalid'; cleanup();
check(buttons.every(b=>b.onclick===null && b.onkeydown===null) && follow.onclick===null,'listeners removed');
renderer({parentElement:{querySelector:()=>root},data});
check(root.dataset.selected==='pit','invalid state resets safely');
check(copy.every(c=>c.textContent===data.copy[c.dataset.copy]),'localized strings written as text');
renderer({parentElement:{querySelector:()=>root},data:{...data,guided_stage:'risk'}});
check(root.dataset.selected==='risk' && root.dataset.guided==='true','guide selects its stage');
buttons[1].onclick(); check(root.dataset.selected==='pit','guide still permits local exploration');
renderer({parentElement:{querySelector:()=>root},data:{...data,language:'zh',guided_stage:'risk'}});
check(root.dataset.selected==='risk','language rerender retains guided stage');
renderer({parentElement:{querySelector:()=>root},data});
check(root.dataset.guided==='false','normal browsing removes guided display mode');
console.log('frontend handlers PASS');
"""
    with language_scope("ja"):
        payload = exhibit.architecture_payload()
    result = subprocess.run([node, "-e", harness], input=json.dumps({"js": exhibit.JS, "data": payload}),
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "frontend handlers PASS"
