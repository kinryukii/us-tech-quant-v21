"""Synthetic method-story checks using the real DEMO UI runtime; no business reads."""
import ast,json,os,shutil,subprocess
from pathlib import Path
from copy import deepcopy
import pytest
from apps.demo_console.components import method_explainer as component
from apps.demo_console.components import strategy_workbench as owner
from apps.demo_console.i18n import catalog,language_scope,tr


def test_stories_are_one_compatible_projection_and_cannot_mutate_owner():
    for sid in owner.METHOD_STORIES:
        story=owner.method_story(sid)
        assert tuple(x['id'] for x in story['steps'])==component.STEP_IDS
        assert owner.METHOD_EXPLANATIONS[sid]==tuple(story[k] for k in ('kind','native_output','portfolio_contract','input_contract','technical'))
        assert owner.METHOD_QUESTIONS[sid]==story['question']
        snapshot=deepcopy(owner.METHOD_STORIES[sid]);story['steps'][0]['body']='SYNTHETIC_MUTATION'
        assert owner.METHOD_STORIES[sid]==snapshot
    with pytest.raises(ValueError,match='SOURCE_CONFIRMED'):owner.method_story('UNCONFIRMED_MODEL')


@pytest.mark.parametrize('language',('en','zh','ja'))
def test_payload_localizes_steps_and_terms_without_scores_or_parameters(language):
    with language_scope(language):
        for sid in owner.METHOD_STORIES:
            story=owner.method_story(sid);payload=component.method_payload(story)
            assert payload['strategy_id']==sid and payload['language']==language
            assert tuple(x['id'] for x in payload['steps'])==component.STEP_IDS
            assert payload['technical']==tr(story['technical'])
            messages=[story['question'],story['boundary'],*component.COPY.values(),*component.STEP_TITLES,
                      *(x['body'] for x in story['steps']),*(x for pair in story['glossary'] for x in pair),*story['assumptions'],*story['blind_spots'],*story['research_prompts']]
            for message in messages:
                assert message in catalog(),message
                assert all(catalog()[message][code].strip() for code in ('zh','ja'))
            assert not any(k in payload for k in ('scores','holdings','probabilities','returns','model_ref'))
            if language!='en':assert payload['question']!=story['question']


def test_component_is_data_free_and_keyboard_responsive():
    tree=ast.parse(Path(component.__file__).read_text(encoding='utf-8'))
    imports=[n for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))]
    assert all((isinstance(n,ast.Import) and all(x.name=='streamlit' for x in n.names)) or
               (isinstance(n,ast.ImportFrom) and n.module=='apps.demo_console.i18n') for n in imports)
    assert all(x not in component.JS for x in ('fetch(','.setStateValue(','.setTriggerValue(','.innerHTML','eval('))
    assert 'aria-live="polite"' in component.HTML and '<details' in component.HTML
    assert '@media(max-width:640px)' in component.CSS and 'prefers-reduced-motion' in component.CSS


def _script():
    import importlib,streamlit as st
    from apps.demo_console.components import method_explainer
    importlib.reload(method_explainer)
    from apps.demo_console.components.strategy_workbench import render_method_explanation
    from apps.demo_console.i18n import language_scope
    with language_scope(st.session_state.get('language','en')):
        render_method_explanation(st.session_state['workspace_strategy'],key='synthetic_explainer')


@pytest.mark.parametrize('language',('en','zh','ja'))
def test_real_demo_component_preserves_research_context(language):
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_function(_script,default_timeout=20)
    state={'workspace_strategy':'R7_GROSS_LINEAR','decision_date':'2025-12-02','workspace_sample':'historical',
           '_research_case_ticker':'SYNTHETIC_ONLY','language':language,'presentation_mode':True}
    for k,v in state.items():app.session_state[k]=v
    app.run();assert not app.exception and not app.error
    assert len(app.get('bidi_component'))==1
    assert not app.button and not app.dataframe and not app.metric and not app.get('iframe')
    for k,v in state.items():assert app.session_state[k]==v


def test_shipped_frontend_handlers_have_no_python_events():
    direct=os.pathsep.join(x for x in os.environ.get('PATH','').split(os.pathsep) if Path(x).name.lower()!='volta')
    node=shutil.which('node',path=direct) or shutil.which('node')
    if not node:pytest.skip('Node unavailable')
    harness=r"""
const fs=require('fs');const {js,data}=JSON.parse(fs.readFileSync(0,'utf8'));
function el(dataset={}){return {dataset,attrs:{},textContent:'',children:[],setAttribute(k,v){this.attrs[k]=v;},focus(){this.focused=true;},replaceChildren(){this.children=[];},append(...n){this.children.push(...n);}};}
global.document={createElement:tag=>el({tag})};
const buttons=data.steps.map(s=>{const b=el({step:s.id}),label=el();b.querySelector=()=>label;return b;});
const copy=Object.keys(data.copy).map(k=>el({copy:k}));
const nodes=Object.fromEntries(['.method-name','.question','.mechanism','.native','.input-contract','.boundary','.glossary','.assumptions','.blind-spots','.research-prompts','.follow','.step-counter','.step-detail h3','.step-detail p'].map(s=>[s,el()]));
const root=el();root.querySelector=q=>nodes[q];root.querySelectorAll=q=>q==='[data-copy]'?copy:q==='[data-step]'?buttons:[];
const render=new Function(js.replace('export default function(component)','return function(component)'))();
const instance={parentElement:{querySelector:()=>root},data,setStateValue(){throw Error('Python event');},setTriggerValue(){throw Error('Python event');}};
function check(v,m){if(!v)throw Error(m);}
const cleanup=render(instance);check(root.dataset.selected==='question','default');check(root.dataset.presentation==='on','presentation mode consumed');
render({...instance,data:{...data,presentation:false,motion_enabled:false}});check(root.dataset.presentation==='off'&&root.dataset.motion==='off','compact mode and reduced motion independent');
render(instance);check(root.dataset.presentation==='on','presentation mode restored');
buttons[2].onclick();check(root.dataset.selected==='mechanism'&&nodes['.step-detail p'].textContent===data.steps[2].body,'mechanism');
check(buttons.filter(b=>b.attrs['aria-pressed']==='true').length===1,'single selection');
nodes['.follow'].onclick();check(root.dataset.selected==='output','native output');
buttons[3].onkeydown({key:'End',preventDefault(){}});check(root.dataset.selected==='portfolio'&&buttons[4].focused,'keyboard');
nodes['.follow'].onclick();check(root.dataset.selected==='question','restart');
buttons[0].onkeydown({key:'ArrowLeft',preventDefault(){}});check(root.dataset.selected==='portfolio','wrap');
check(nodes['.glossary'].children.length===data.glossary.length*2,'terms');check(nodes['.research-prompts'].children.length===data.research_prompts.length,'research reminders');
render({...instance,data:{...data,language:'zh'}});check(root.dataset.selected==='portfolio'&&root.lang==='zh','language');
render({...instance,data:{...data,strategy_id:'SYNTHETIC_OTHER'}});check(root.dataset.selected==='question','new method');
cleanup();check(buttons.every(b=>b.onclick===null&&b.onkeydown===null)&&nodes['.follow'].onclick===null,'cleanup');
check(copy.every(c=>c.textContent===data.copy[c.dataset.copy]),'text only');console.log('method frontend PASS');
"""
    with language_scope('ja'):payload=component.method_payload(owner.method_story('R7_GROSS_LINEAR'))
    result=subprocess.run([node,'-e',harness],input=json.dumps({'js':component.JS,'data':payload}),capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='method frontend PASS'


SHOWCASE_IDS=('RAW_A2','HGB_DIAG_5','R7_GROSS_LINEAR','R6_DURATION_TREE','R10_DIRECT_H5_RIDGE_MID')


def _case_script():
    from apps.demo_console.components.strategy_workbench import render_strategy_cases
    from apps.demo_console.tests.test_method_explainer import SHOWCASE_IDS
    render_strategy_cases({},strategy_ids=SHOWCASE_IDS)


def test_hidden_query_keeps_accepted_cards_and_global_date_and_can_open_shared_ml():
    from streamlit.testing.v1 import AppTest
    from apps.demo_console.tests.test_localized_tabs import _open_expander
    app=AppTest.from_function(_case_script,default_timeout=20)
    app.session_state['workspace_strategy']='R7_GROSS_LINEAR'
    app.session_state['decision_date']='2026-01-05'
    app.session_state['workspace_sample']='test_2026'
    app.session_state['language']='en'
    app.run();assert not app.exception
    expected={'workbench_method_'+sid for sid in SHOWCASE_IDS}
    assert {w.key for w in app.button if w.key.startswith('workbench_method_')}==expected
    assert not app.selectbox
    _open_expander(app,'workbench_other_methods')
    query=app.selectbox(key='workbench_catalog_method')
    assert len(query.options)==3
    query.select('R6_BUY_NEURAL').run()
    assert not app.exception and app.session_state['workspace_strategy']=='R6_BUY_NEURAL'
    assert app.session_state['decision_date']=='2026-01-05'
    assert {w.key for w in app.button if w.key.startswith('workbench_method_')}==expected
    payload=json.loads(app.get('bidi_component')[0].proto.json)
    assert payload['strategy_id']=='R6_BUY_NEURAL'
    app.button(key='workbench_open_ml').click().run()
    assert not app.exception and app.session_state['workspace']=='Machine learning'
    assert app.session_state['workspace_strategy']=='R6_BUY_NEURAL'
    assert app.session_state['decision_date']=='2026-01-05'


def test_existing_hidden_global_focus_is_not_replaced_with_raw():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_function(_case_script,default_timeout=20)
    app.session_state['workspace_strategy']='RAW_s10'
    app.session_state['decision_date']='2025-12-02'
    app.run();assert not app.exception
    assert app.session_state['workspace_strategy']=='RAW_s10'
    payload=json.loads(app.get('bidi_component')[0].proto.json)
    assert payload['strategy_id']=='RAW_s10'
    assert len([w for w in app.button if w.key.startswith('workbench_method_')])==5


def test_eight_methods_keep_distinct_native_roles_and_research_reminders():
    assert len(owner.WORKSPACE_STRATEGIES)==len(owner.METHOD_STORIES)==8
    for sid in owner.METHOD_STORIES:
        story=owner.method_story(sid)
        assert story['assumptions'] and story['blind_spots'] and len(story['research_prompts'])>=2
    assert owner.method_story('RAW_s10')['input_contract']!=owner.method_story('RAW_A2')['input_contract']
    assert 'proxy ages 0, 7 and 14' in owner.method_story('R6_DURATION_TREE')['technical']
    assert 'not a prediction of the number of days' in owner.method_story('R6_DURATION_TREE')['technical']
    assert 'exact tie or unknown' in owner.method_story('R6_BUY_NEURAL')['technical']


def test_projection_typography_is_scoped_and_narrow_layout_can_reduce_it():
    css=component.CSS
    assert '.method-explainer[data-presentation="on"] .flow strong {font-size:15px}' in css
    assert '.method-explainer[data-presentation="on"] summary {font-size:16px}' in css
    assert '.method-explainer[data-presentation="on"] .step-detail p {font-size:19px}' in css
    narrow=css.split('@media(max-width:480px)',1)[1].split('@media(prefers-reduced-motion:reduce)',1)[0]
    assert '.step-detail p {font-size:15px}' in narrow and 'dl {font-size:14px}' in narrow
    assert 'grid-template-columns:repeat(2,minmax(0,1fr))' in css
    for presentation in (False,True):
        payload=component.method_payload(owner.method_story('R7_GROSS_LINEAR'),presentation=presentation,motion_enabled=False)
        assert payload['presentation'] is presentation and payload['motion_enabled'] is False
