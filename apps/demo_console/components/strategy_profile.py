"""Explain the bound frozen control, without inferring unexposed trading rules."""
from apps.demo_console.components.visuals import text
from apps.demo_console.models import DecisionOverview
from apps.demo_console.i18n import tr


def strategy_html(model: DecisionOverview) -> str:
    if model.error:
        return f'<div class="uq-muted">{text(tr("Strategy details unavailable until source verification succeeds."))}</div>'
    dates = model.available_dates
    coverage = f"{dates[0]} → {dates[-1]}" if dates else tr("Not exposed")
    version = model.provenance.config_identity
    facts = (
        ("Model", tr("Histogram gradient boosting")),
        ("Recorded selection", tr("Top 20 equities")),
        ("Portfolio contract", tr("Long only · Equal-weight target")),
        ("Signal → execution", tr("Close → next U.S. session open")),
        ("Archive coverage", coverage),
        ("Configuration", version[:8] if version else tr("Not exposed")),
    )
    return (f'<details class="uq-strategy-profile"><summary><span><b>{text(tr("STRATEGY PROFILE"))}</b>'
            f'<strong>{text(tr("Raw A2 control"))}</strong><span class="uq-strategy-tag">{text(tr("Frozen historical research"))}</span></span>'
            f'<span class="uq-strategy-expand">{text(tr("Explore strategy"))} <span aria-hidden="true">＋</span></span></summary>'
            '<div class="uq-strategy-body"><p>'
            + text(tr("A frozen cross-sectional model ranks eligible U.S. equities. This workspace replays the original Top 20 selections and subsequent Raw A2 holdings.")) + '</p>'
            + '<div class="uq-strategy-facts">' + ''.join(
                f'<div><span>{text(tr(label))}</span><strong>{text(value)}</strong></div>'
                for label, value in facts) + '</div>'
            + '<p class="uq-panel-note">'
            + text(tr("The frozen model target is mean excess return versus QQQ over 3, 5, 10 and 20 trading days; this describes its prediction target, not realized performance. Actual position weights and a separately specified rebalance frequency are not exposed here. Stateful RX is outside this recorded control portfolio."))
            + '</p></div></details>')
