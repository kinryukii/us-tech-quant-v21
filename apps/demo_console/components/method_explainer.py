"""Reusable, source-free explanation of a method's five-stage decision flow.

All interaction stays inside the component DOM. No scores, fitted parameters,
model calls, business readers or events back to Python are generated here.
"""
import streamlit as st
from apps.demo_console.i18n import get_language, tr

STEP_IDS = ("question", "input", "mechanism", "output", "portfolio")
STEP_TITLES = ("Question", "Inputs", "Model mechanism", "Output", "Portfolio & records")
COPY = {
    "illustration": "Method illustration",
    "hint": "Choose a step, or follow the flow",
    "follow": "Follow the flow",
    "restart": "Start again",
    "counter": "Step {number} of {total}",
    "details": "Technical detail & terminology",
    "mechanism": "How the model works",
    "native": "Native output contract",
    "inputs": "Input contract",
    "glossary": "Terms in plain language",
    "boundary": "Training & evidence boundary",
    "research": "Research questions to keep in mind",
    "assumptions": "Working assumptions",
    "blind_spots": "What this method leaves out",
    "questions": "Questions to verify",
    "note": "Illustrative flow only. No stock scores, account data or portfolio calculations.",
}


def method_payload(story, *, presentation=True, motion_enabled=True):
    """Translate one explicit story; never discover methods or read their results."""
    if (not isinstance(story, dict) or not isinstance(story.get("strategy_id"), str)
            or not isinstance(story.get("label"), str)
            or not isinstance(story.get("steps"), (list, tuple))
            or tuple(step.get("id") for step in story["steps"]) != STEP_IDS):
        raise ValueError("INVALID_METHOD_STORY")
    return {"language": get_language(), "strategy_id": story["strategy_id"],
        "label": tr(story["label"]), "question": tr(story["question"]),
        "presentation": bool(presentation), "motion_enabled": bool(motion_enabled),
        "copy": {key: tr(value) for key, value in COPY.items()},
        "steps": [{"id": step["id"], "title": tr(title), "body": tr(step["body"])}
                  for step, title in zip(story["steps"], STEP_TITLES)],
        "technical": tr(story["technical"]), "native_output": tr(story["native_output"]),
        "input_contract": tr(story["input_contract"]), "boundary": tr(story["boundary"]),
        "glossary": [{"term": tr(term), "meaning": tr(meaning)} for term, meaning in story["glossary"]],
        **{field: [tr(value) for value in story[field]] for field in ("assumptions", "blind_spots", "research_prompts")}}


HTML = """
<section class="method-explainer">
  <header><span class="method-name"></span><span class="illustration" data-copy="illustration"></span><h2 class="question"></h2></header>
  <p class="hint" data-copy="hint"></p>
  <ol class="flow">
    <li><button type="button" data-step="question"><span>01</span><strong></strong></button></li>
    <li><button type="button" data-step="input"><span>02</span><strong></strong></button></li>
    <li><button type="button" data-step="mechanism"><span>03</span><strong></strong></button></li>
    <li><button type="button" data-step="output"><span>04</span><strong></strong></button></li>
    <li><button type="button" data-step="portfolio"><span>05</span><strong></strong></button></li>
  </ol>
  <article class="step-detail" aria-live="polite" aria-atomic="true"><span class="step-counter"></span><h3></h3><p></p></article>
  <div class="follow-row"><button type="button" class="follow"></button><p class="note" data-copy="note"></p></div>
  <details class="technical"><summary data-copy="details"></summary><div class="technical-body">
    <h3 data-copy="mechanism"></h3><p class="mechanism"></p>
    <div class="contracts"><div><h4 data-copy="native"></h4><p class="native"></p></div><div><h4 data-copy="inputs"></h4><p class="input-contract"></p></div></div>
    <h3 data-copy="glossary"></h3><dl class="glossary"></dl>
    <h3 data-copy="boundary"></h3><p class="boundary"></p>
  </div></details>
  <details class="research"><summary data-copy="research"></summary><div class="technical-body">
    <h3 data-copy="assumptions"></h3><ul class="assumptions research-list"></ul>
    <h3 data-copy="blind_spots"></h3><ul class="blind-spots research-list"></ul>
    <h3 data-copy="questions"></h3><ul class="research-prompts research-list"></ul>
  </div></details>
</section>
"""
CSS = """
.method-explainer {--ink:#11243a;--muted:#536780;--line:#dce5f0;--accent:#315efb;--soft:#f0f4fb;color:var(--ink);font:15px/1.7 "Segoe UI","Microsoft YaHei UI","Yu Gothic UI",sans-serif;min-width:0;max-width:100%;box-sizing:border-box}
.method-explainer * {box-sizing:border-box;overflow-wrap:anywhere}
header {padding:10px 0 22px;border-bottom:1px solid var(--line)}
.method-name {font-size:13px;font-weight:650;margin-right:14px}
.illustration {font-size:11px;color:var(--muted);padding:4px 9px;border:1px solid var(--line);border-radius:20px;background:#ffffffb8}
h2 {font-size:clamp(23px,2.5vw,32px);font-weight:600;letter-spacing:-.035em;line-height:1.35;margin:16px 0 0;max-width:900px}
.hint {font-size:12px;color:var(--muted);margin:20px 0 10px}
.flow {display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px;padding:0;margin:0;list-style:none}
.flow li {min-width:0}
.flow button {width:100%;height:100%;text-align:left;border:1px solid var(--line);border-radius:12px;background:#ffffffb8;color:var(--muted);padding:13px 14px;font:inherit;cursor:pointer;transition:background .15s,border-color .15s}
.flow button span {display:block;font:11px/1.4 ui-monospace,monospace;color:var(--muted);margin-bottom:7px}
.flow strong {font-size:13px;font-weight:600;line-height:1.4;display:block}
.flow button[aria-pressed="true"] {background:#edf2ff;border-color:#9ab0fb;color:var(--ink);box-shadow:inset 0 2px 0 var(--accent)}
.flow button[aria-pressed="true"] span {color:var(--accent)}
.step-detail {padding:22px 24px;margin-top:16px;background:linear-gradient(120deg,#ffffffd6,#eef4ffa6);border:1px solid #dce5f0;border-radius:14px;min-height:140px}
.step-counter {font:11px/1.5 ui-monospace,monospace;color:var(--accent)}
h3 {font-size:17px;font-weight:600;line-height:1.5;margin:7px 0}
.step-detail p {font-size:17px;line-height:1.8;max-width:920px;margin:8px 0 0}
.follow-row {display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin:13px 0 22px}
.follow {border:1px solid var(--line);background:#fff;border-radius:10px;color:var(--ink);padding:9px 16px;font-family:inherit;font-weight:600;font-size:13px;line-height:1.5;cursor:pointer;min-height:42px}
.note {font-size:11px;line-height:1.6;color:var(--muted);margin:0;flex:1 1 240px}
.technical,.research {border-top:1px solid var(--line);padding:14px 0}
summary {cursor:pointer;color:var(--ink);font-size:13px;font-weight:600;min-height:34px}
.technical-body {padding:14px 0 0;max-width:1040px}
.technical-body p {margin:5px 0 20px;color:var(--muted);font-size:14px;line-height:1.85}
.contracts {display:grid;grid-template-columns:1fr 1fr;gap:24px}
h4 {font-size:12px;font-weight:600;margin:4px 0}
dl {display:grid;grid-template-columns:minmax(100px,.65fr) minmax(0,2fr);gap:10px 24px;margin:10px 0 24px;font-size:13px}
dt {font-weight:600}dd {margin:0;color:var(--muted)}
.research-list {margin:7px 0 21px;padding-left:20px;color:var(--muted);font-size:14px;line-height:1.85}.research-list li+li{margin-top:7px}
button:focus-visible,summary:focus-visible {outline:2px solid var(--accent);outline-offset:3px}
.method-explainer[data-presentation="on"] .flow strong {font-size:15px}
.method-explainer[data-presentation="on"] summary {font-size:16px}
.method-explainer[data-presentation="on"] .technical-body p,
.method-explainer[data-presentation="on"] .research-list {font-size:16px}
.method-explainer[data-presentation="on"] dl {font-size:15px}
.method-explainer[data-presentation="on"] .step-detail p {font-size:19px}
@media(max-width:640px){.flow{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.flow li:last-child{grid-column:1/-1}.flow button{padding:11px 12px}.flow button span{margin-bottom:3px}.step-detail{padding:18px;min-height:0}.step-detail p{font-size:15px}.contracts{grid-template-columns:1fr;gap:0}dl{grid-template-columns:1fr;gap:3px}dd{margin-bottom:11px}h2{font-size:25px}.illustration{display:inline-block;margin-top:5px}}
@media(max-width:480px){
.method-explainer[data-presentation="on"] .flow strong {font-size:14px}
.method-explainer[data-presentation="on"] summary,
.method-explainer[data-presentation="on"] .technical-body p,
.method-explainer[data-presentation="on"] .research-list,
.method-explainer[data-presentation="on"] .step-detail p {font-size:15px}
.method-explainer[data-presentation="on"] dl {font-size:14px}
}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{transition:none!important;animation:none!important}}
.method-explainer[data-motion="off"] * {transition:none!important}
@media(prefers-reduced-transparency:reduce){.step-detail,.flow button,.illustration{background:#fff}}
@media(forced-colors:active){.flow button[aria-pressed="true"]{border:2px solid Highlight}.step-detail{border:1px solid CanvasText}}
"""
JS = """
export default function(component) {
  const {parentElement,data} = component;
  const root = parentElement.querySelector('.method-explainer');
  if (!root || data?.steps?.length !== 5) return;
  const previous = root.dataset.strategy === data.strategy_id ? root.dataset.selected : null;
  root.dataset.strategy = data.strategy_id;
  root.dataset.motion = data.motion_enabled ? 'on' : 'off';
  root.dataset.presentation = data.presentation ? 'on' : 'off';
  root.lang = data.language;
  root.setAttribute('aria-label',data.question);
  root.querySelector('.method-name').textContent = data.label;
  root.querySelector('.question').textContent = data.question;
  root.querySelectorAll('[data-copy]').forEach(node => {node.textContent = data.copy[node.dataset.copy] || '';});
  const buttons = [...root.querySelectorAll('[data-step]')];
  data.steps.forEach((step,index) => {buttons[index].querySelector('strong').textContent=step.title;});
  root.querySelector('.mechanism').textContent=data.technical;
  root.querySelector('.native').textContent=data.native_output;
  root.querySelector('.input-contract').textContent=data.input_contract;
  root.querySelector('.boundary').textContent=data.boundary;
  const glossary=root.querySelector('.glossary');
  glossary.replaceChildren();
  data.glossary.forEach(item => {
    const term=document.createElement('dt'), meaning=document.createElement('dd');
    term.textContent=item.term; meaning.textContent=item.meaning;
    glossary.append(term,meaning);
  });
  [['.assumptions',data.assumptions],['.blind-spots',data.blind_spots],['.research-prompts',data.research_prompts]].forEach(([selector,items])=>{
    const list=root.querySelector(selector);list.replaceChildren();
    items.forEach(text=>{const item=document.createElement('li');item.textContent=text;list.append(item);});
  });
  const follow=root.querySelector('.follow');
  const select=id => {
    const index=data.steps.findIndex(step=>step.id===id);
    if (index<0) return;
    const step=data.steps[index];
    root.dataset.selected=id;
    buttons.forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.step===id)));
    root.querySelector('.step-counter').textContent=data.copy.counter.replace('{number}',String(index+1)).replace('{total}',String(data.steps.length));
    root.querySelector('.step-detail h3').textContent=step.title;
    root.querySelector('.step-detail p').textContent=step.body;
    follow.textContent=index===data.steps.length-1 ? data.copy.restart : data.copy.follow;
  };
  buttons.forEach((button,index)=>{
    button.onclick=()=>select(button.dataset.step);
    button.onkeydown=event=>{
      let next;
      if(event.key==='ArrowRight'||event.key==='ArrowDown') next=(index+1)%buttons.length;
      if(event.key==='ArrowLeft'||event.key==='ArrowUp') next=(index-1+buttons.length)%buttons.length;
      if(event.key==='Home') next=0;
      if(event.key==='End') next=buttons.length-1;
      if(next!==undefined){event.preventDefault();buttons[next].focus();select(buttons[next].dataset.step);}
    };
  });
  follow.onclick=()=>{
    const index=data.steps.findIndex(step=>step.id===root.dataset.selected);
    select(data.steps[(index+1)%data.steps.length].id);
  };
  select(data.steps.some(step=>step.id===previous) ? previous : data.steps[0].id);
  return ()=>{buttons.forEach(button=>{button.onclick=null;button.onkeydown=null;});follow.onclick=null;};
}
"""

def render_method_explainer(story, *, presentation=True, key=None):
    """Display an explicit story; interactions do not mutate global selections."""
    component = st.components.v2.component("method_flow_explainer",html=HTML,css=CSS,js=JS,isolate_styles=True)
    return component(data=method_payload(story,presentation=presentation,
        motion_enabled=st.session_state.get("motion_enabled",True)),
        key=key or "method_flow:"+story["strategy_id"],width="stretch",height="content")
