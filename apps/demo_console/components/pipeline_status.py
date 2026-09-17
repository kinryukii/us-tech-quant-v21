"""Evidence coverage with distinct readability and validation states."""
import streamlit as st
from apps.demo_console.components.visuals import section_header, text
from apps.demo_console.models import PipelineStage
from apps.demo_console.i18n import tr

_STATUS_STYLES = {
    "PASS": ("PASS", "pass"), "AVAILABLE": ("AVAILABLE", ""),
    "NOT_APPLICABLE": ("Not applicable", "limited"), "NOT_EXPOSED": ("NOT EXPOSED", "limited"),
    "UNAVAILABLE": ("UNAVAILABLE", "limited"), "BLOCKED": ("BLOCKED", "blocked"),
}


def _stage_label(name: str) -> str:
    return tr({"Portfolio": "Recorded portfolio", "Evidence": "Source integrity"}.get(name, name))


def pipeline_html(stages: tuple[PipelineStage, ...]) -> str:
    heading = section_header(tr("Evidence coverage"), tr("FROM SOURCE TO PORTFOLIO"))
    body = ''
    for number, stage in enumerate(stages, 1):
        label, kind = _STATUS_STYLES.get(stage.status, ("NOT EXPOSED", "limited"))
        body += (f'<div class="uq-evidence-row"><span class="uq-stage-title"><span class="uq-stage-index">{number:02}</span>'
                 f'{text(_stage_label(stage.name))}</span><span class="uq-evidence-badge {kind}">{text(tr(label))}</span></div>')
    if not stages:
        body = f'<div class="uq-empty">{text(tr("Pipeline evidence unavailable."))}</div>'
    return (f'<section id="evidence" class="uq-panel">{heading}{body}'
            f'<div class="uq-evidence-note">{text(tr("AVAILABLE = readable evidence."))}<br>'
            f'{text(tr("PASS = explicit validation, within the stated scope."))}</div></section>')


def _detail_text(detail: str) -> str:
    """Translate the known audit sentence while preserving its raw status code."""
    prefix = "Frozen audit reports temporal causality "
    suffix = "; no new PIT audit."
    if detail.startswith(prefix) and detail.endswith(suffix):
        status = detail[len(prefix):-len(suffix)]
        return tr("Frozen audit reports temporal causality {status}; no new PIT audit.", status=status)
    return tr(detail)


def render_pipeline(stages: tuple[PipelineStage, ...], *, presentation: bool) -> None:
    st.html(pipeline_html(stages))
    with st.expander(tr("Inspect evidence details"), expanded=False):
        for stage in stages:
            label, _ = _STATUS_STYLES.get(stage.status, ("NOT EXPOSED", "limited"))
            st.markdown(f"**{_stage_label(stage.name)} · {tr(label)}**")
            st.caption(_detail_text(stage.detail))
            if not presentation and stage.status not in _STATUS_STYLES:
                st.text(tr("Raw status: {status}", status=stage.status))
