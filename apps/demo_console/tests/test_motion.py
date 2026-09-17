"""Exercise motion event gates and fail-open rendering without a browser."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from apps.demo_console.components import motion


class _Markup(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.tags, self.scripts, self.contexts = [], [], []
        self.styles = []
        self.in_script = False
        self.in_style = False
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        attrs = dict(attrs)
        assert not any(name.startswith("on") for name in attrs)
        if "data-uq-motion-config" in attrs:
            self.contexts.append(json.loads(attrs["data-uq-motion-config"]))
        self.in_script = tag == "script"
        self.in_style = tag == "style"

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False
        if tag == "style":
            self.in_style = False

    def handle_data(self, data):
        if self.in_script:
            self.scripts.append(data)
        if self.in_style:
            self.styles.append(data)


def test_motion_context_is_escaped_data_and_executable_script_is_fixed(monkeypatch):
    hostile = '\"><img src=x onerror=alert(1)></div><script>alert("x")</script>日本語'
    normal = _Markup(motion.motion_html("Overview", "2025-12-02"))
    malicious = _Markup(motion.motion_html(hostile, hostile, enabled=False))
    assert malicious.tags == normal.tags == ["style", "div", "script"]
    assert malicious.contexts == [{"view": hostile, "decision_date": hostile, "enabled": False}]
    assert malicious.scripts == normal.scripts
    calls = []
    monkeypatch.setattr(motion.st, "html", lambda body, **kwargs: calls.append((body, kwargs)))
    motion.render_motion("History", None, enabled=False)
    assert _Markup(calls[0][0]).contexts == [{"view": "History", "decision_date": None, "enabled": False}]
    assert calls[0][1] == {"unsafe_allow_javascript": True}


_DRIVER = r"""
const vm = require("node:vm");
let config, nextFrame = 0, forbidden = 0, writes = 0;
const queue = new Map(), effects = [], attributes = {}, mediaListeners = [];
const media = {matches: false, addEventListener: (_, fn) => mediaListeners.push(fn)};
const nodes = new Map();
for (const [selector, top] of [
  [".uq-page-header", 20], [".uq-date", 20], [".uq-metrics", 100],
  [".uq-snapshot-brief", 220], [".uq-table-shell", 300],
  [".uq-transition-panel", 300], [".uq-change-group", 350],
  [".st-key-uq_chart_panel", 520], [".uq-motion-enter", 1000],
  [".st-key-uq_performance_path", 230], [".st-key-uq_execution_quality", 430],
  [".st-key-uq_holding_matrix", 510], [".st-key-uq_demo_tour", 110],
  [".st-key-research_execution_turnover", 470],
  ['[class*="st-key-history_holding_matrix_"]', 540],
  [".uq-research-observation", 660], [".uq-research-evidence", 700],
]) {
  const node = {
    selector, isConnected: true, getClientRects: () => [{}],
    getBoundingClientRect: () => ({top, bottom: top + 45, width: 400}),
    contains: other => other.parent === node,
    setAttribute: () => {writes++;},
    animate(keyframes, options) {
      const listeners = {};
      const effect = {selector, keyframes, options, cancelled: false,
        addEventListener: (name, fn) => {listeners[name] = fn;},
        cancel() {this.cancelled = true; listeners.cancel?.();},
        finish() {listeners.finish?.();},
      };
      effects.push(effect);
      return effect;
    },
  };
  for (const name of ["textContent", "innerHTML", "innerText"]) {
    Object.defineProperty(node, name, {get: () => "Recorded value 20", set: () => {writes++;}});
  }
  node.style = new Proxy({}, {set: () => {writes++; return true;}});
  nodes.set(selector, node);
}
const main = {querySelectorAll: selector => selector.split(",").map(s => nodes.get(s.trim())).filter(Boolean)};
const document = {
  documentElement: {setAttribute: (key, value) => {attributes[key] = value;}},
  querySelectorAll: () => [{getAttribute: () => JSON.stringify(config)}],
  querySelector: () => main,
};
const window = {
  innerHeight: 720, matchMedia: () => media,
  requestAnimationFrame: callback => {queue.set(++nextFrame, callback); return nextFrame;},
  cancelAnimationFrame: id => queue.delete(id),
};
for (const key of ["fetch", "XMLHttpRequest", "WebSocket", "localStorage", "sessionStorage"]) {
  Object.defineProperty(window, key, {get: () => {forbidden++; throw Error("Forbidden capability");}});
}
const sandbox = vm.createContext({document, window});
function render(next, flush = true) {
  config = next;
  vm.runInContext(source, sandbox, {timeout: 1000});
  if (flush) {
    while (queue.size) {
      const [id, callback] = queue.entries().next().value;
      queue.delete(id); callback();
    }
  }
}
function reduced(value) {
  media.matches = value;
  mediaListeners.forEach(callback => callback());
}
const context = (view = "Overview", date = "2025-12-02", enabled = true) =>
  ({view, decision_date: date, enabled});
"""


def _run_js(scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable for the isolated DOM/animation harness")
    source = Path(motion.__file__).with_name("motion.js").read_text(encoding="utf-8")
    program = "const source = " + json.dumps(source) + ";\n" + _DRIVER + scenario
    result = subprocess.run([node, "--input-type=commonjs"], input=program, text=True,
                            encoding="utf-8", capture_output=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_same_context_never_replays_but_view_and_date_have_distinct_effects():
    result = _run_js(r"""
render(context());
const first = effects.length;
render(context()); // Language and filters do not enter the signature.
const repeated = effects.length;
render(context("Overview", "2025-12-01"));
const changed = effects.slice(repeated).map(effect => effect.selector);
const beforeView = effects.length;
render(context("Portfolio", "2025-12-01"));
console.log(JSON.stringify({first, repeated, changed,
  view: effects.slice(beforeView).map(effect => effect.selector),
  offscreen: effects.some(effect => effect.selector === ".uq-motion-enter"),
  fills: [...new Set(effects.map(effect => effect.options.fill))], writes, forbidden}));
""")
    assert result["first"] > 0 and result["repeated"] == result["first"]
    assert ".uq-date" in result["changed"] and ".uq-page-header" not in result["changed"]
    assert ".uq-page-header" in result["view"]
    assert result["offscreen"] is False
    assert set(result["fills"]) <= {"none", "backwards"}, "Effects must not retain styles after finishing"
    assert result["writes"] == result["forbidden"] == 0


def test_explicit_disable_cancels_running_and_pending_motion_without_replaying_on_enable():
    result = _run_js(r"""
render(context());
const first = effects.length;
render(context("Overview", "2025-12-01"), false);
render(context("Overview", "2025-12-01", false));
const disabled = attributes["data-uq-motion"];
const queued = queue.size;
render(context("Overview", "2025-12-01", true));
console.log(JSON.stringify({first, total: effects.length, queued, disabled,
  cancelled: effects.every(effect => effect.cancelled), writes, forbidden}));
""")
    assert result["first"] > 0 and result["total"] == result["first"]
    assert result["queued"] == 0 and result["disabled"] == "disabled"
    assert result["cancelled"] and result["writes"] == result["forbidden"] == 0


def test_reduced_motion_prevents_entry_and_cancels_effects_when_preference_changes():
    result = _run_js(r"""
reduced(true);
render(context());
const initial = effects.length;
const disabled = attributes["data-uq-motion"];
reduced(false);
render(context("History"));
const playing = effects.length;
reduced(true);
render(context("Evidence"));
console.log(JSON.stringify({initial, disabled, playing, total: effects.length,
  cancelled: effects.every(effect => effect.cancelled), listeners: mediaListeners.length, writes}));
""")
    assert result["initial"] == 0 and result["disabled"] == "disabled"
    assert result["playing"] > 0 and result["total"] == result["playing"]
    assert result["cancelled"] and result["listeners"] == 1 and result["writes"] == 0


def test_unavailable_animation_api_and_bad_context_leave_recorded_content_untouched():
    result = _run_js(r"""
for (const node of nodes.values()) node.animate = () => {throw Error("Unsupported effect");};
render(context());
render({view: null, decision_date: "bad", enabled: true});
console.log(JSON.stringify({effects: effects.length, writes, forbidden,
  visible: [...nodes.values()].every(node => node.textContent === "Recorded value 20")}));
""")
    assert result == {"effects": 0, "writes": 0, "forbidden": 0, "visible": True}


def test_research_execution_tour_and_matrix_enter_once_without_moving_chart_geometry():
    result = _run_js(r"""
nodes.get(".uq-metrics").parent = nodes.get(".st-key-uq_execution_quality");
nodes.get(".st-key-research_execution_turnover").parent = nodes.get(".st-key-uq_execution_quality");
nodes.get('[class*="st-key-history_holding_matrix_"]').parent = nodes.get(".st-key-uq_holding_matrix");
render(context("Research"));
const entering = effects.map(effect => ({selector: effect.selector, frames: effect.keyframes, options: effect.options}));
const first = effects.length;
render(context("Research")); // Chart filters, tabs and selections do not change the signature.
const afterFilter = effects.length;
render(context("Research", "2025-12-01"));
console.log(JSON.stringify({entering, first, afterFilter,
  dates: effects.slice(afterFilter).map(effect => effect.selector), writes, forbidden}));
""")
    effects = {effect["selector"]: effect for effect in result["entering"]}
    charts = (".st-key-uq_performance_path", ".st-key-uq_execution_quality", ".st-key-uq_holding_matrix")
    assert all(selector in effects for selector in (*charts, ".st-key-uq_demo_tour"))
    assert ".uq-metrics" not in effects and ".st-key-research_execution_turnover" not in effects
    assert '[class*="st-key-history_holding_matrix_"]' not in effects
    for selector in charts:
        assert all(set(frame) == {"opacity"} and .75 <= frame["opacity"] <= 1
                   for frame in effects[selector]["frames"]), "Chart geometry and hit targets must stay stationary"
        assert selector in result["dates"]
    assert ".st-key-uq_demo_tour" not in result["dates"]
    assert result["afterFilter"] == result["first"]
    assert result["writes"] == result["forbidden"] == 0


def test_pending_entry_is_cancelled_by_same_context_and_finished_effects_release_references():
    result = _run_js(r"""
render(context("History"), false);
render(context("History"));
const pendingCancelled = queue.size === 0 && effects.length === 0;
render(context("Research"));
const playing = window[Symbol.for("us-tech-quant.motion")].animations.size;
effects.forEach(effect => effect.finish());
const released = window[Symbol.for("us-tech-quant.motion")].animations.size;
render(context("Research", "2025-12-01"), false);
reduced(true);
const afterReduced = queue.size;
render(context("Research", "2025-12-01"));
console.log(JSON.stringify({pendingCancelled, playing, released, afterReduced,
  total: effects.length, listeners: mediaListeners.length, writes}));
""")
    assert result["pendingCancelled"] is True
    assert result["playing"] > 0 and result["released"] == result["afterReduced"] == 0
    assert result["total"] == result["playing"]
    assert result["listeners"] == 1 and result["writes"] == 0


def test_motion_styles_disable_all_controls_and_progress_even_before_javascript_runs():
    """Guard static CSS coverage; a short known-widget list misses future controls."""
    css = Path(motion.__file__).with_name("motion.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    def declarations(body):
        return dict(item.strip().split(":", 1) for item in body.split(";") if item.strip())

    required = {"transition": "none !important", "animation": "none !important",
                "scroll-behavior": "auto !important"}
    rules = [(set(selector.strip() for selector in prelude.split(",")), declarations(body))
             for prelude, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]
    universal_off = {'html[data-uq-motion="disabled"] ' + suffix for suffix in ("*", "*::before", "*::after")}
    assert any(universal_off <= selectors and all(props.get(key, "").strip() == value
                                                  for key, value in required.items())
               for selectors, props in rules), "Explicit off must include sidebar radio and replay progress descendants"
    reduced = re.search(r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{\s*([^{}]+)\{([^{}]*)\}", css)
    assert reduced is not None
    assert {selector.strip() for selector in reduced[1].split(",")} >= {"*", "*::before", "*::after"}
    assert all(declarations(reduced[2]).get(key, "").strip() == value for key, value in required.items())
    assert "data-uq-motion" not in reduced[1], "OS preference must work without the JavaScript marker"
    enabled = _Markup(motion.motion_html("Research", "2025-12-02", enabled=True))
    disabled = _Markup(motion.motion_html("Research", "2025-12-02", enabled=False))
    extra_css = disabled.styles[0][len(enabled.styles[0]):]
    universal = re.search(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", extra_css, flags=re.S))
    assert universal is not None
    assert {selector.strip() for selector in universal[1].split(",")} >= {"*", "*::before", "*::after"}
    assert all(declarations(universal[2]).get(key, "").strip() == value for key, value in required.items())
    assert disabled.scripts == enabled.scripts, "Explicit-off fallback changes CSS only, never executable data"
