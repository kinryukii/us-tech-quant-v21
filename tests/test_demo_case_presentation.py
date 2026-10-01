"""Case-first composition and pending execution behavior, with synthetic records."""
from dataclasses import replace
from pathlib import Path
import sys

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append('D:/us-tech-quant')
import apps.demo_console, apps.demo_console.components, apps.demo_console.pages, apps.demo_console.adapters
for package, folder in ((apps.demo_console, ''), (apps.demo_console.components, 'components'),
                        (apps.demo_console.pages, 'pages'), (apps.demo_console.adapters, 'adapters')):
    package.__path__.insert(0, str(ROOT / 'apps/demo_console' / folder))

from apps.demo_console.models import DecisionOverview, HoldingRow, LearningProfile, ModelVintage, Provenance
from apps.demo_console.components import decision_trace as trace, system_overview as system
from apps.demo_console.pages import machine_learning as ml
from apps.demo_console.i18n import language_scope


def model():
    return DecisionOverview(decision_date='2026-09-22', available_dates=('2026-09-21','2026-09-22'),
        ranking=tuple(HoldingRow(n, f'SYNTH{n:02}', 1/n, held_before=n <= 20) for n in range(1,41)),
        previous_holdings=tuple(f'SYNTH{n:02}' for n in range(1,21)), eligible_universe_count=164,
        provenance=Provenance('2026-09-22','2026-09-22',None,config_identity='a'*64,
            artifact_sources=('synthetic.json',),artifact_hashes=(('synthetic.json','b'*64),)),
        learning=LearningProfile(feature_columns=('momentum',),source_fingerprint='a'*64,
            vintages=(ModelVintage(2026,'A2 frozen','2025-11-28','2025-12-30','2026-01-02','2026-09-22',100,40,'a'*64,'SERIALIZED'),)),
        source_id='A2_UPDATED_RESEARCH', execution_status='PENDING_NEXT_OPEN',
        scheduled_execution_date='2026-09-23', performance_cutoff_date='2026-09-22',ranking_limit=40)


def entry():
    from apps.demo_console.pages.machine_learning import _render_engine
    from apps.demo_console.components.system_overview import _render_secondary_tools
    from apps.demo_console.i18n import set_language
    from test_demo_case_presentation import model
    import streamlit as st
    from dataclasses import replace
    set_language('en')
    item = model()
    if st.session_state.get('without_performance'):
        item = replace(item,performance_cutoff_date=None)
    _render_engine(item)
    _render_secondary_tools(item)


def test_pending_trace_preserves_known_before_and_unknown_after():
    item = model()
    with language_scope('en'):
        facts = trace.trace_facts(item,'SYNTH01')
        assert facts['held_before'] is True and facts['held_after'] is None
        assert facts['execution_date'] is None
        html = trace.trace_html(facts)
        assert 'Awaiting next session open' in html
        assert 'Scheduled next open' in html and '2026-09-23' in html
        assert 'Membership is not fully recorded' not in html
        assert ml.case_explanation(facts) == "SYNTH01's signal is awaiting the next session open."


def test_verified_updated_hero_is_not_a_broken_metadata_state():
    with language_scope('en'):
        html = system.system_hero_html(model())
        assert 'Verified model' in html and 'Portfolio history through 2026-09-22' in html
        assert 'metadata incomplete' not in html and 'Portfolio linkage unavailable' not in html


def test_case_chain_marks_scheduled_open_and_keeps_execution_unfabricated():
    with language_scope('en'):
        facts = trace.trace_facts(model(),'SYNTH01')
        html = system._case_chain_html(facts)
        assert 'Held → Awaiting next session open' in html
        assert 'Scheduled next open' in html and 'Linked execution' not in html
        assert model().provenance.execution_date is None


def test_ml_opens_with_chart_and_case_before_collapsed_learning_notes():
    app = AppTest.from_function(entry, default_timeout=20).run()
    assert not app.exception
    html = [item.proto.body for item in app.get('html')]
    chart = next(i for i,text in enumerate(html) if 'Recorded score profile' in text)
    notes = next(i for i,text in enumerate(html) if 'Learning design' in text)
    assert chart < notes
    assert next(item for item in app.expander if item.label == 'Model mechanism and objective').proto.expanded is False
    assert not app.button(key='ml_case_recovery').disabled
    assert not app.button(key='system_risk').disabled
    assert 'awaiting the next session open' in '\n'.join(html)


def test_local_rank_band_changes_chart_picker_without_truncating_case_evidence():
    app = AppTest.from_function(entry, default_timeout=20)
    app.session_state['workspace_rank_band'] = '21–40'
    app.run()
    assert not app.exception
    assert app.selectbox(key='ml_engine_ticker').options == [f'SYNTH{n:02}' for n in range(21,41)]
    assert len(model().ranking) == 40
    assert trace.trace_facts(model(),'SYNTH01')['rank'] == 1
    app.button(key='ml_case_recovery').click().run()
    assert app.session_state['workspace'] == 'Research'
    assert app.session_state['_localized_tabs:research_tabs'] == 'Drawdown & recovery'


def test_no_verified_performance_keeps_risk_actions_disabled():
    app = AppTest.from_function(entry, default_timeout=20)
    app.session_state['without_performance'] = True
    app.run()
    assert not app.exception
    assert app.button(key='ml_case_recovery').disabled and app.button(key='system_risk').disabled


def test_updated_overview_has_four_real_metrics_without_control_placeholders():
    from types import SimpleNamespace
    summary = SimpleNamespace(net_total_return=.1,reference_net_total_return=None,reference_available=False,
        max_drawdown=SimpleNamespace(depth=-.02),gross_net_difference_pp=.12,observations=933)
    with language_scope('en'):
        html = system._research_metrics(summary,updated=True)
    assert html.count('<div class="uq-research-metric ') == 4
    assert '933' in html and 'Frozen A control' not in html


def test_frozen_trace_keeps_original_semantics():
    item = replace(model(),source_id='frozen',execution_status=None,scheduled_execution_date=None,
        performance_cutoff_date=None,ranking_limit=20,previous_holdings=None)
    with language_scope('en'):
        html = trace.trace_html(trace.trace_facts(item,'SYNTH01'))
    assert 'Original records' in html and 'Scheduled next open' not in html
    assert not trace.performance_available(item)
