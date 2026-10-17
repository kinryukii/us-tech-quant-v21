"""Data-free, locally interactive architecture exhibit using Streamlit CCv2.

All shapes illustrate mechanisms. No values are read from research or accounts.
"""
import streamlit as st

from apps.demo_console.i18n import get_language, tr

# Display copy only; the original owners continue to define all system behavior.
EXHIBIT_COPY = {
    "eyebrow": "SYSTEM / ENGINEERING",
    "title": "From market records.",
    "title_accent": "To traceable decisions.",
    "intro": "Explore the engineering between a market record and a simulated fill. Each stage carries its own inputs, limits and evidence.",
    "schematic": "Principle illustration",
    "hint": "Select a stage to explore",
    "follow": "Follow one record",
    "input": "Input", "process": "Process", "output": "Output",
    "lineage": "Versioned identity & traceability",
    "resources": "Published caches & bounded resources",
    "note": "Illustrative paths only. No live data, model execution or order submission.",
    "cases": "Methods as application cases",
}

EXHIBIT_STAGES = (
    {"id": "pit", "title": "Data & point-in-time", "short": "What was knowable?",
     "input": "Market records, publication times and security identities.",
     "process": "Align each input with its available time and dated identity; keep later information outside the decision boundary.",
     "output": "A dated, verified input set with explicit availability limits."},
    {"id": "inference", "title": "Frozen inference", "short": "Apply a fixed method",
     "input": "Verified features and a registered model with frozen transforms.",
     "process": "Apply the original feature order, fitted transforms and frozen model. Browsing does not train or select a model.",
     "output": "Method-specific scores, action proposals or a requested exposure level."},
    {"id": "risk", "title": "Portfolio & risk", "short": "Respect the constraints",
     "input": "Method outputs, existing holdings, cash and the bound policy.",
     "process": "Translate decisions under the method's risk, turnover and cash rules; preserve exact HOLD units where required.",
     "output": "Intended holdings and cash, distinct from executable orders."},
    {"id": "execution", "title": "Simulated execution", "short": "Verify what happened",
     "input": "Published targets, account observations and current quotes.",
     "process": "Apply the original account, quote, sizing and authorization checks, then reconcile observed orders and fills.",
     "output": "Separate target, order, fill and valuation records."},
    {"id": "lineage", "title": "Versioned identity & traceability", "short": "Keep the chain explainable",
     "input": "Input dates, registered identities, source versions and recorded decisions.",
     "process": "Retain original bindings and evidence so a displayed result can be traced back to its source and method.",
     "output": "A reviewable chain from published input to recorded outcome."},
    {"id": "resources", "title": "Published caches & bounded resources", "short": "Separate browsing from work",
     "input": "Published records and reusable caches from the existing daily workflow.",
     "process": "Read only the requested view; keep data acquisition, frozen inference and execution with their existing owners.",
     "output": "Responsive exploration without silently restarting the daily pipeline."},
)


def architecture_payload(presentation=True, *, motion_enabled=True, guided_stage=None):
    """Build a translated editorial payload without accessing business state."""
    return {"language": get_language(), "mode": "presentation" if presentation else "research",
            "motion_enabled": bool(motion_enabled),
            "guided_stage": guided_stage if guided_stage in {stage["id"] for stage in EXHIBIT_STAGES} else None,
            "copy": {key: tr(value) for key, value in EXHIBIT_COPY.items()},
            "stages": [{key: value if key == "id" else tr(value) for key, value in stage.items()}
                       for stage in EXHIBIT_STAGES]}


HTML = """
<section class="exhibit" aria-label="System architecture">
  <header class="hero">
    <div><p class="eyebrow" data-copy="eyebrow"></p><h1><span data-copy="title"></span><br><span class="accent" data-copy="title_accent"></span></h1></div>
    <div class="hero-side"><p data-copy="intro"></p><span class="schematic"><i></i><span data-copy="schematic"></span></span></div>
  </header>
  <div class="diagram-head"><span data-copy="hint"></span><button type="button" class="follow"><span data-copy="follow"></span><span aria-hidden="true">↗</span></button></div>
  <div class="diagram">
    <button type="button" class="rail top" data-stage="lineage" aria-pressed="false"><span class="rail-mark" aria-hidden="true">⌘</span><span data-copy="lineage"></span><span aria-hidden="true">↗</span></button>
    <svg class="wiring" viewBox="0 0 1120 300" preserveAspectRatio="none" aria-hidden="true">
      <defs><linearGradient id="wire"><stop stop-color="#315af4"/><stop offset="1" stop-color="#19a9b8"/></linearGradient></defs>
      <path class="wire-background" d="M 130 142 H 990 M 130 32 V 142 M 410 32 V 142 M 690 32 V 142 M 970 32 V 142 M 130 142 V 278 M 410 142 V 278 M 690 142 V 278 M 970 142 V 278"/>
      <path class="wire-active" d="M 130 142 H 990"/>
      <path class="wire-arrow" d="m 277 137 6 5 -6 5 m 280 -10 6 5 -6 5 m 280 -10 6 5 -6 5"/>
    </svg>
    <div class="stages" role="group">
      <button type="button" class="stage" data-stage="pit" aria-pressed="true">
        <span class="index">01 / PIT</span>
        <svg viewBox="0 0 220 166" aria-hidden="true">
          <path class="fine" d="M 25 39 H 195 M 25 72 H 195 M 25 105 H 195 M 25 138 H 195"/>
          <path class="faint" d="M 155 21 V 146 M 182 21 V 146"/>
          <path class="solid" d="M 25 39 H 127 M 25 72 H 127 M 25 105 H 127 M 25 138 H 127"/>
          <g class="dots"><circle cx="39" cy="39" r="5"/><circle cx="86" cy="39" r="5"/><circle cx="65" cy="72" r="5"/><circle cx="107" cy="105" r="5"/><circle cx="51" cy="138" r="5"/></g>
          <g class="future"><circle cx="172" cy="39" r="5"/><circle cx="153" cy="72" r="5"/><circle cx="185" cy="105" r="5"/></g>
          <path class="boundary" d="M 128 15 V 153"/><path class="arrow-tip" d="m 122 20 6 -6 6 6"/>
        </svg>
        <span class="stage-title" data-title="pit"></span><span class="stage-short" data-short="pit"></span>
      </button>
      <button type="button" class="stage" data-stage="inference" aria-pressed="false">
        <span class="index">02</span>
        <svg viewBox="0 0 220 166" aria-hidden="true">
          <path class="fine" d="M 20 86 H 53 M 53 86 89 45 H 135 M 53 86 89 127 H 135 M 135 45 172 25 H 200 M 135 45 172 67 H 200 M 135 127 172 106 H 200 M 135 127 172 147 H 200"/>
          <path class="solid" d="M 20 86 H 53 L 89 45 H 135 L 172 67 H 200"/>
          <g class="dots"><circle cx="53" cy="86" r="7"/><circle cx="135" cy="45" r="7"/><circle cx="200" cy="67" r="5"/></g>
          <g class="future"><circle cx="135" cy="127" r="7"/><circle cx="200" cy="25" r="5"/><circle cx="200" cy="106" r="5"/><circle cx="200" cy="147" r="5"/></g>
          <rect class="lock-body" x="89" y="83" width="29" height="26" rx="5"/><path class="lock" d="M 96 84 V 78 A 8 8 0 0 1 112 78 V 84 M 104 93 V 100"/>
        </svg>
        <span class="stage-title" data-title="inference"></span><span class="stage-short" data-short="inference"></span>
      </button>
      <button type="button" class="stage" data-stage="risk" aria-pressed="false">
        <span class="index">03</span>
        <svg viewBox="0 0 220 166" aria-hidden="true">
          <circle class="orbit" cx="100" cy="84" r="58"/><circle class="allocation" cx="100" cy="84" r="58"/>
          <circle class="inner" cx="100" cy="84" r="37"/><path class="fine" d="M 100 8 V 23 M 100 145 V 160 M 24 84 H 39 M 161 84 H 176"/>
          <path class="solid" d="m 81 84 13 13 26 -28"/>
          <path class="bar" d="M 184 131 V 108 M 196 131 V 88 M 208 131 V 64"/>
        </svg>
        <span class="stage-title" data-title="risk"></span><span class="stage-short" data-short="risk"></span>
      </button>
      <button type="button" class="stage" data-stage="execution" aria-pressed="false">
        <span class="index">04</span>
        <svg viewBox="0 0 220 166" aria-hidden="true">
          <path class="paper-back" d="M 38 34 H 135 V 132 H 38 Z"/><path class="paper-mid" d="M 56 23 H 153 V 121 H 56 Z"/>
          <path class="paper-front" d="M 75 12 H 166 L 183 29 V 144 L 170 138 158 144 145 138 132 144 119 138 106 144 94 138 75 144 Z"/>
          <path class="fine" d="M 91 44 H 163 M 91 60 H 146 M 91 78 H 126 M 91 95 H 126 M 91 112 H 118"/>
          <circle class="receipt" cx="160" cy="111" r="20"/><path class="check" d="m 150 111 7 7 14 -16"/>
        </svg>
        <span class="stage-title" data-title="execution"></span><span class="stage-short" data-short="execution"></span>
      </button>
    </div>
    <button type="button" class="rail bottom" data-stage="resources" aria-pressed="false"><span class="rail-mark" aria-hidden="true">≡</span><span data-copy="resources"></span><span aria-hidden="true">↗</span></button>
  </div>
  <section class="detail" aria-live="polite" aria-atomic="true">
    <div class="detail-heading"><span class="detail-number" aria-hidden="true">01</span><h2></h2></div>
    <div class="detail-flow"><div><span data-copy="input"></span><p data-detail="input"></p></div><div><span data-copy="process"></span><p data-detail="process"></p></div><div><span data-copy="output"></span><p data-detail="output"></p></div></div>
  </section>
  <p class="footnote" data-copy="note"></p>
</section>
"""

CSS = """
:host { color-scheme:light; }
* { box-sizing:border-box; }
.exhibit { --ink:#11243a; --muted:#586b80; --blue:#315af4; --cyan:#19a9b8; --line:#e3e8ef; color:var(--ink); background:transparent; font-family:var(--st-font),Arial,sans-serif; }
.hero { display:grid; grid-template-columns:1.45fr 1fr; align-items:end; gap:64px; padding:46px 0 42px; }
.eyebrow { font-size:11px; letter-spacing:.2em; font-weight:700; color:var(--muted); margin:0 0 22px; }
h1 { margin:0; font-size:clamp(48px,4.8vw,70px); letter-spacing:-.055em; font-weight:600; line-height:1.09; }
.accent { color:var(--blue); }
.hero-side { max-width:350px; padding-bottom:4px; }
.hero-side p { font-size:16px; line-height:1.75; color:var(--muted); margin:0 0 22px; }
.schematic { display:inline-flex; align-items:center; gap:8px; font-size:12px; color:var(--muted); }
.schematic i { width:6px; height:6px; border-radius:50%; background:var(--cyan); }
button { font:inherit; color:inherit; cursor:pointer; }
button:focus-visible { outline:3px solid var(--blue); outline-offset:4px; border-radius:4px; }
.diagram-head { display:flex; align-items:center; justify-content:space-between; gap:16px; font-size:12px; color:var(--muted); border-top:1px solid var(--line); padding:15px 0; }
.follow { display:flex; align-items:center; gap:16px; background:none; border:0; padding:6px 0 6px 12px; color:var(--blue); font-weight:600; }
.follow:hover { color:var(--blue); }
.diagram { position:relative; background-color:#f1f6fd; background-image:radial-gradient(ellipse at 8% 10%,#e1edff90,transparent 55%),radial-gradient(ellipse at 95% 85%,#d9f6f580,transparent 50%),radial-gradient(#c9d8ec80 .7px,transparent .7px); background-size:auto,auto,18px 18px;border:1px solid #ffffffeb;border-radius:24px;box-shadow:inset 0 1px 0 #fff,0 12px 40px #2048720a; padding:17px 24px 18px; overflow:hidden; }
.wiring { position:absolute; top:32px; left:0; width:100%; height:calc(100% - 64px); pointer-events:none; }
.wire-background { stroke:#dbe4f1; stroke-width:1; fill:none; }
.wire-active { stroke:url(#wire); stroke-width:1.5; fill:none; opacity:.24; stroke-dasharray:3 6; }
.wire-arrow { stroke:#91a5c7; stroke-width:1; fill:none; }
.rail { position:relative; display:flex; align-items:center; justify-content:center; gap:12px; width:max-content; max-width:100%; margin:auto; padding:8px 16px; border:1px solid #ccd9e9a0; background:#ffffffb8;box-shadow:inset 0 1px 0 #fff,0 4px 12px #1e416b08;backdrop-filter:blur(8px); color:var(--muted); font-size:12px; border-radius:24px; }
.rail-mark { font-size:18px; line-height:1; color:var(--cyan); }
.rail:hover,.rail[aria-pressed="true"] { border-color:var(--blue); color:var(--blue); background:#fff; }
.stages { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); position:relative; gap:28px; margin:20px 0 22px; }
.stage { min-width:0; display:flex; flex-direction:column; align-items:stretch; text-align:left; padding:8px 10px 12px; border:1px solid transparent; border-radius:18px; background:transparent; transition:background .18s ease; }
.stage:hover { background:#ffffffb8; }
.stage svg { width:100%; height:150px; overflow:visible; margin:6px 0 15px; }
.index { font-size:10px; font-weight:600; letter-spacing:.08em; color:#7c8c9e; }
.stage-title { font-size:18px; line-height:1.35; font-weight:600; letter-spacing:-.02em; }
.stage-short { margin-top:7px; font-size:12px; color:var(--muted); }
.stage[aria-pressed="true"] .stage-title { color:var(--blue); }
.stage[aria-pressed="true"] .index { color:var(--blue); }
.stage[aria-pressed="true"] { background:linear-gradient(145deg,#ffffffd9,#eff5ff99);border-color:#ffffffed;box-shadow:0 5px 20px #20487209,inset 0 1px 0 #fff; }
.fine,.faint { stroke:#bbc9db; stroke-width:1.5; fill:none; }
.faint { stroke:#d9e1ed; stroke-dasharray:3 5; }
.solid,.boundary,.lock,.arrow-tip { stroke:var(--blue); stroke-width:2; fill:none; }
.dots { fill:var(--blue); stroke:#f7f9fc; stroke-width:3; }
.future { fill:#f7f9fc; stroke:#b9c9db; stroke-width:1.5; }
.boundary { stroke:var(--cyan); stroke-width:1.7; }
.arrow-tip { stroke:var(--cyan); }
.lock-body { fill:#fff; stroke:var(--cyan); stroke-width:1.6; }
.lock { stroke:var(--cyan); stroke-width:1.6; }
.orbit { fill:#f7f9fc; stroke:#dce4ef; stroke-width:12; }
.allocation { fill:none; stroke:var(--blue); stroke-width:12; stroke-dasharray:110 12 70 12 40 120; transform:rotate(-90deg); transform-origin:100px 84px; }
.inner { fill:#fff; stroke:#dde6f3; stroke-width:1; }
.bar { stroke:var(--cyan); stroke-width:6; }
.paper-back { fill:#e8eef8; stroke:#c9d7e8; stroke-width:1; }
.paper-mid { fill:#f2f5fb; stroke:#b9cce2; stroke-width:1; }
.paper-front { fill:#fff; stroke:var(--blue); stroke-width:1.5; }
.receipt { fill:#e9f8f8; stroke:var(--cyan); stroke-width:1.5; }
.check { fill:none; stroke:var(--cyan); stroke-width:2; }
.detail { padding:24px 0 20px; border-bottom:1px solid var(--line); }
.detail-heading { display:flex; align-items:baseline; gap:12px; margin-bottom:14px; }
.detail-number { color:var(--blue); font:12px ui-monospace,monospace; }
h2 { margin:0; font-size:19px; letter-spacing:-.025em; font-weight:600; }
.detail-flow { display:grid; grid-template-columns:1fr 1.45fr 1fr; gap:36px; }
.detail-flow>div { position:relative; }
.detail-flow>div+div:before { content:'→'; position:absolute; left:-26px; top:26px; font-size:15px; color:#acbacd; }
.detail-flow span { color:var(--blue); font-size:11px; font-weight:600; letter-spacing:.04em; }
.detail-flow p { color:var(--muted); font-size:13px; line-height:1.65; margin:6px 0 0; }
.footnote { margin:12px 0 0; color:#6e7f92; font-size:11px; line-height:1.6; }
.exhibit[data-guided="true"] .hero { padding:12px 0 20px; gap:36px; }
.exhibit[data-guided="true"] h1 { font-size:36px; }
.exhibit[data-guided="true"] .eyebrow { margin-bottom:10px; }
.exhibit[data-guided="true"] .hero-side p { font-size:13px; line-height:1.6; margin-bottom:8px; }
@media(max-width:800px) { .hero { gap:22px; grid-template-columns:minmax(0,1fr); padding-top:32px; } h1 { font-size:48px; } .hero-side { max-width:100%; } .hero-side p { font-size:14px; margin-bottom:12px; } .stages { gap:8px; } .diagram { padding:17px 12px; } .stage { padding:8px 5px 12px; } .stage svg { height:120px; } .stage-title { font-size:15px; } .detail-flow { gap:24px; } .detail-flow>div+div:before { left:-19px; } }
@media(max-width:560px) { .hero { display:block; padding:25px 0 25px; } h1 { font-size:clamp(40px,10vw,52px); letter-spacing:-.05em; } .eyebrow { margin-bottom:16px; } .hero-side { max-width:100%; margin-top:20px; } .hero-side p { margin-bottom:12px; } .stages { grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; } .stage svg { height:125px; } .stage-title { font-size:16px; } .wiring { display:none; } .rail { font-size:11px; padding:8px 10px; gap:7px; } .detail-flow { grid-template-columns:1fr; gap:12px; } .detail-flow>div { padding-left:18px; border-left:1px solid var(--line); } .detail-flow>div+div:before { content:none; } .detail-flow p { margin-top:4px; } .diagram-head { font-size:11px; } }
@media(prefers-reduced-transparency:reduce) { .rail,.stage[aria-pressed="true"] {background:#fff;backdrop-filter:none} }
.exhibit[data-motion="off"] *, .exhibit[data-motion="off"] *::before, .exhibit[data-motion="off"] *::after { transition:none!important; animation:none!important; }
@media(prefers-reduced-motion:reduce) { *,*::before,*::after { transition:none!important; animation:none!important; scroll-behavior:auto!important; } }
"""

JS = """
export default function(component) {
  const {parentElement, data} = component;
  const root = parentElement.querySelector('.exhibit');
  if (!root || !data?.stages?.length) return;
  root.lang = data.language;
  root.dataset.mode = data.mode;
  root.dataset.motion = data.motion_enabled ? "on" : "off";
  root.dataset.guided = String(Boolean(data.guided_stage));
  root.setAttribute('aria-label', data.copy.eyebrow);
  root.querySelectorAll('[data-copy]').forEach(el => { el.textContent = data.copy[el.dataset.copy] || ''; });
  root.querySelector('.stages').setAttribute('aria-label', data.copy.hint);
  data.stages.forEach(stage => {
    const title = root.querySelector(`[data-title="${stage.id}"]`);
    const short = root.querySelector(`[data-short="${stage.id}"]`);
    if (title) title.textContent = stage.title;
    if (short) short.textContent = stage.short;
  });
  const buttons = [...root.querySelectorAll('[data-stage]')];
  const select = id => {
    const index = data.stages.findIndex(stage => stage.id === id);
    if (index < 0) return;
    const stage = data.stages[index];
    root.dataset.selected = id;
    buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.stage === id)));
    root.querySelector('.detail-number').textContent = String(index + 1).padStart(2, '0');
    root.querySelector('.detail h2').textContent = stage.title;
    root.querySelectorAll('[data-detail]').forEach(el => { el.textContent = stage[el.dataset.detail]; });
  };
  buttons.forEach(button => {
    button.onclick = () => select(button.dataset.stage);
    button.onkeydown = event => {
      const index = buttons.indexOf(button);
      let next;
      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % buttons.length;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index - 1 + buttons.length) % buttons.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = buttons.length - 1;
      if (next !== undefined) { event.preventDefault(); buttons[next].focus(); select(buttons[next].dataset.stage); }
    };
  });
  const follow = root.querySelector('.follow');
  follow.onclick = () => {
    const index = data.stages.findIndex(stage => stage.id === root.dataset.selected);
    select(data.stages[index >= 0 && index < 4 ? (index + 1) % 4 : 0].id);
  };
  const guided = data.stages.some(stage => stage.id === data.guided_stage) ? data.guided_stage : null;
  select(guided || (data.stages.some(stage => stage.id === root.dataset.selected) ? root.dataset.selected : 'pit'));
  return () => { buttons.forEach(button => { button.onclick = null; button.onkeydown = null; }); follow.onclick = null; };
}
"""

_ARCHITECTURE = st.components.v2.component(
    "system_architecture_exhibit", html=HTML, css=CSS, js=JS, isolate_styles=True)


def render_architecture(presentation=True):
    """Mount local explanatory interactions; there is no event path to Python."""
    from apps.demo_console.components.demo_tour import showcase_architecture_stage
    return _ARCHITECTURE(data=architecture_payload(presentation,
                             motion_enabled=st.session_state.get("motion_enabled", True),
                             guided_stage=showcase_architecture_stage()),
                         key="system_architecture_exhibit", width="stretch", height="content")
