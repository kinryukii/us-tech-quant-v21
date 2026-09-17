"""Static HTML export of the same recorded overview and presentation components."""
from __future__ import annotations

import argparse
from html import escape
from pathlib import PureWindowsPath

from apps.demo_console.adapters.decision_reader import load_overview
from apps.demo_console.components.pipeline_status import pipeline_html
from apps.demo_console.components.portfolio_summary import chips, summary_html, transition_html
from apps.demo_console.components.top20_table import table_html
from apps.demo_console.components.strategy_profile import strategy_html
from apps.demo_console.components.visuals import header_html, section_header, styles
from apps.demo_console.models import DecisionOverview
from scripts.common.storage_paths import resolve_results_path


def _text(value) -> str:
    return escape("N/A" if value is None else str(value), quote=True)


def _short(value: str | None) -> str:
    if value is None:
        return "N/A"
    if len(value) >= 40 and all(c in "0123456789abcdef" for c in value.lower()):
        return value[:8] + "…"
    return PureWindowsPath(value).name if ":\\" in value or ":/" in value or value.startswith("/") else value


_EXPORT_CSS = """
:root{--uq-bg:#f3f5fa;--uq-panel:#fff;--uq-ink:#17294b;--uq-muted:#586985;--uq-line:#dce4f1;--uq-accent:#3864ee;--uq-amber:#c78639;color-scheme:light}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:16px}
body{margin:0;background:var(--uq-bg);color:var(--uq-ink);font:14px/1.5 "Segoe UI",Arial,sans-serif}
a:focus-visible,summary:focus-visible{outline:2px solid var(--uq-accent);outline-offset:4px}
.uq-export-shell{display:grid;grid-template-columns:196px minmax(0,1fr);min-height:100vh}
.uq-export-sidebar{--uq-ink:#e8eeff;--uq-muted:#acbadd;--uq-line:#2a3d64;--uq-accent:#9bb4ff;background:#0c1530;border-right:1px solid var(--uq-line);padding:24px 16px;color:var(--uq-muted)}
.uq-export-sidebar .uq-brand{margin-bottom:30px;font-size:13px;letter-spacing:.025em;color:var(--uq-ink)}
.uq-export-sidebar .uq-brand small{display:block;margin-top:4px;font-size:13px;font-weight:400;color:var(--uq-muted)}
.uq-export-sidebar .uq-brand-symbol{border-color:#405d9d;color:var(--uq-accent)}
.uq-export-sidebar .uq-brand-symbol span{background:#0c1530}
.uq-export-sidebar .uq-nav{font-size:14px;padding:11px 10px;border-radius:4px;color:var(--uq-muted)}
.uq-export-sidebar .uq-nav.active{background:#20376b;border-left:2px solid var(--uq-accent);color:var(--uq-ink)}
.uq-export-sidebar .uq-nav:hover{background:#182a50}
.uq-export-sidebar .uq-date{padding:0;border:0;text-align:left;margin:18px 10px}
.uq-export-sidebar .uq-date strong{color:var(--uq-ink);font-size:17px}
.uq-export-sidebar .uq-date span,.uq-export-sidebar .uq-nav-label{color:var(--uq-muted);font-size:13px}
.uq-export-sidebar .uq-sidebar-footer{font-size:13px;margin-top:38px;border-color:var(--uq-line);color:var(--uq-muted)}
.uq-export-sidebar .uq-sidebar-footer strong{color:var(--uq-ink);font-size:13px}
.uq-export-main{width:100%;max-width:1800px;margin:0 auto;padding:20px 24px 28px;min-width:0}
.uq-export-toolbar{display:flex;justify-content:space-between;align-items:center;gap:16px;padding-bottom:13px;margin-bottom:14px;border-bottom:1px solid var(--uq-line);font-size:13px;color:var(--uq-muted)}
.uq-export-toolbar a{color:var(--uq-accent);text-decoration:none}.uq-export-toolbar a:hover{text-decoration:underline}
.uq-export-toolbar b{font-size:13px;letter-spacing:.04em;font-weight:600}
.uq-export-main .uq-topline{margin-bottom:12px;font-size:13px;color:var(--uq-muted)}
.uq-export-main .uq-page-header{margin-bottom:16px;gap:20px}
.uq-export-main .uq-page-header h1{font-size:28px;letter-spacing:-.5px;margin-bottom:6px}
.uq-export-main .uq-page-header p{font-size:14px;color:var(--uq-muted)}
.uq-export-main>.uq-metrics{margin-top:0}
.uq-export-main>.uq-scope-strip{margin:12px 0 16px;font-size:13px;line-height:1.6}
.uq-export-layout{display:grid;grid-template-columns:minmax(0,2fr) minmax(310px,1fr);gap:16px;align-items:start}
.uq-export-layout>section,.uq-export-rail{min-width:0}
.uq-export-rank-panel{padding:16px;border:1px solid var(--uq-line);border-radius:5px;background:var(--uq-panel)}
.uq-export-records{margin:0}.uq-export-records h3{font-size:15px;font-weight:600;color:var(--uq-ink);margin:14px 0 6px}
.uq-export-records>p{font-size:13px;line-height:1.6;color:var(--uq-muted);margin:0 0 13px}
.uq-export-rail{display:flex;flex-direction:column;gap:16px}
.uq-export-rail>.uq-panel{margin:0;padding:16px;min-width:0}
.uq-export-rail .uq-section-head{align-items:flex-start;gap:10px;flex-wrap:wrap}
.uq-export-rail .uq-section-head h2{font-size:16px}
.uq-export-rail .uq-transition{grid-template-columns:1fr;gap:14px}
.uq-export-rail .uq-transition-summary{padding-right:0;border-right:0}
.uq-export-rail .uq-change-groups{grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.uq-export-details{margin:16px 0 0;border:1px solid var(--uq-line);border-radius:5px;background:var(--uq-panel);padding:14px 16px;font-size:14px;color:var(--uq-muted)}
.uq-export-rail>.uq-export-details{margin:0}
.uq-export-details summary{cursor:pointer;font-weight:600;font-size:14px;color:var(--uq-ink)}
.uq-export-details summary::marker{color:var(--uq-accent)}
.uq-export-details[open]>summary{padding-bottom:12px;margin-bottom:13px;border-bottom:1px solid var(--uq-line)}
.uq-export-details h3{font-size:14px;color:var(--uq-ink);margin:18px 0 7px}
.uq-export-details p,.uq-export-details li{font-size:13px;line-height:1.7}
.uq-export-details dl{display:grid;grid-template-columns:190px minmax(0,1fr);gap:10px 20px;margin:16px 0}
.uq-export-details dt{color:var(--uq-muted)}.uq-export-details dd{margin:0;color:var(--uq-ink);overflow-wrap:anywhere}
.uq-export-details li,.uq-export-details pre{overflow-wrap:anywhere;white-space:pre-wrap}
.uq-export-details pre{padding:12px;background:var(--uq-bg);border:1px solid var(--uq-line);border-radius:4px;font-size:13px}
.uq-export-error{padding:12px 16px;border:1px solid #d9b8a4;border-radius:5px;background:#f8ece6;color:#80503b}
.uq-export-main>.uq-footer{margin-top:20px;padding-top:16px;font-size:13px;color:var(--uq-muted)}
@media(max-width:1250px){.uq-export-layout{grid-template-columns:minmax(0,2fr) minmax(280px,1fr);gap:12px}.uq-export-rank-panel,.uq-export-rail>.uq-panel{padding:13px}}
@media(max-width:1080px){.uq-export-layout{grid-template-columns:minmax(0,1fr)}.uq-export-rail{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-items:start}.uq-export-main .uq-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:760px){.uq-export-shell{display:block}.uq-export-sidebar{display:none}.uq-export-main{padding:16px}.uq-export-toolbar{align-items:flex-start;flex-direction:column;gap:8px}.uq-export-rail{display:flex}.uq-export-details dl{grid-template-columns:1fr;gap:5px}.uq-export-details dd{margin-bottom:10px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
"""


def render_html(model: DecisionOverview, presentation: bool = True) -> str:
    """Export the supplied snapshot without mutating or reloading the model."""
    prov = model.provenance
    facts = [("Decision date", prov.decision_date), ("Previous decision date", model.previous_decision_date),
             ("Information as of", prov.information_as_of), ("Execution date", prov.execution_date),
             ("Universe identity", prov.universe_identity), ("Economic identity", prov.strategy_identity),
             ("Configuration identity", prov.config_identity), ("Artifact producer", prov.producer_identity),
             ("Alpha implementation", prov.alpha_implementation),
             ("Replay / freeze identity", prov.replay_identity)]
    details = "".join(f'<dt>{label}</dt><dd>{_text(_short(value) if presentation else value)}</dd>'
                      for label, value in facts)
    sources = "".join(f'<li>{_text(PureWindowsPath(value).name if presentation else value)}</li>'
                      for value in prov.artifact_sources) or '<li>Not exposed by current artifact</li>'
    hashes = "".join(f'<li>{_text(PureWindowsPath(source).name if presentation else source)}: '
                     f'{_text(_short(digest) if presentation else digest)}</li>'
                     for source, digest in prov.artifact_hashes)
    debug = "" if presentation else (f'<h3>Raw status / debug</h3><pre>{_text(prov.raw_status)}\n'
                                     f'{_text(model.debug_error)}</pre>')
    limitation_items = "".join(f"<li>{_text(item)}</li>" for item in model.limitations)
    unavailable_metrics = "".join(
        f'<li>{label}: {_text(value)}</li>' for label, value in (
            ("Raw A2 proposed changes", model.raw_proposed_changes),
            ("RX accepted changes", model.rx_accepted_changes),
            ("RX prevented changes", model.rx_prevented_changes)))
    evidence_details = "".join(
        f'<h3>{_text(stage.name)} · {_text(stage.status.replace("_", " "))}</h3>'
        f'<p>{_text(stage.detail)}</p>' for stage in model.pipeline)
    all_holdings = "".join(f'<h3>{label}</h3>{chips(values)}' for label, values in (
        ("Previous holdings", model.previous_holdings), ("Retained", model.retained),
        ("Entered", model.entered), ("Exited", model.exited)))
    errors = f'<p class="uq-export-error" role="alert">{_text(model.error)}</p>' if model.error else ""
    link = "overview_debug.html" if presentation else "overview.html"
    switch = "Open provenance view" if presentation else "Return to presentation"
    mode = "ON" if presentation else "OFF"
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>US Tech Quant | Static Overview</title><style>{styles()}{_EXPORT_CSS}</style></head>
<body><div class="uq-export-shell"><aside class="uq-export-sidebar" aria-label="Overview navigation">
<div class="uq-brand"><div class="uq-brand-symbol">Q<span>↗</span></div><div>US TECH QUANT<small>RESEARCH CONSOLE</small></div></div>
<div class="uq-nav-label">WORKSPACE</div>
<a class="uq-nav active" href="#portfolio-overview"><span>▦</span> Overview <b>01</b></a>
<a class="uq-nav" href="#portfolio-records"><span>≡</span> Portfolio records</a>
<a class="uq-nav" href="#evidence"><span>◇</span> Evidence &amp; scope</a>
<div class="uq-sidebar-rule"></div><div class="uq-nav-label">EXPORTED SNAPSHOT</div>
<div class="uq-date"><span>DECISION DATE</span><strong>{_text(model.decision_date)}</strong></div>
<div class="uq-sidebar-footer"><strong>RESEARCH / READ ONLY</strong>Historical evidence.<br>Static HTML export.</div></aside>
<main class="uq-export-main" id="portfolio-overview">
<div class="uq-export-toolbar"><b>STATIC PREVIEW · HTML EXPORT</b><span>Presentation Mode: {mode} · <a href="{link}">{switch}</a></span></div>
{header_html(model)}{errors}{summary_html(model)}{strategy_html(model)}
<div class="uq-scope-strip"><b>BASELINE SCOPE</b><span class="uq-scope-copy">Recorded Raw A2 historical portfolio.
Stateful RX trace and the combined final portfolio are <strong>NOT EXPOSED</strong>.
Holdings and turnover describe subsequent replay execution.</span></div>
<div class="uq-export-layout"><section id="portfolio-records" class="uq-export-rank-panel">
{section_header("Ranking records", "RAW A2 SNAPSHOT", f"{len(model.ranking)} ranked names")}
<section class="uq-export-records" id="ranking"><h3>Raw A2 Top20</h3>
<p>Producer-supplied ranking · Score is the recorded model output, not a probability or portfolio weight.</p>
{table_html(model.ranking)}</section></section>
<aside class="uq-export-rail">{transition_html(model)}{pipeline_html(model.pipeline)}
<details class="uq-export-details"><summary>Inspect evidence details</summary>{evidence_details}</details>
<details class="uq-export-details"><summary>Coverage &amp; limitations</summary><ul>{unavailable_metrics}</ul>
<p>N/A = not exposed by the current artifact. Ranking alone is not a trade decision.</p><ul>{limitation_items}</ul></details></aside></div>
<details class="uq-export-details" id="holdings"><summary>Historical holdings · {len(model.holdings)} recorded names</summary>
<section class="uq-export-records"><p>Recorded Raw A2 holdings · Previous holding refers to the preceding portfolio snapshot.</p>
{table_html(model.holdings)}</section></details>
<details class="uq-export-details"><summary>Compare all holdings across snapshots</summary>
<p>{_text(model.previous_decision_date)} → {_text(model.decision_date)}</p>{all_holdings}</details>
<details class="uq-export-details" id="provenance" {"" if presentation else "open"}><summary>Decision provenance</summary>
<dl>{details}</dl><h3>Artifact sources</h3><ul>{sources}</ul><h3>Artifact identities</h3><ul>{hashes}</ul>{debug}</details>
<footer class="uq-footer"><span>US TECH QUANT <span class="uq-separator">/</span> RESEARCH &amp; PORTFOLIO DECISION CONSOLE</span>
<span>Static export of the recorded snapshot · Read only</span></footer>
</main></div></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None)
    args = parser.parse_args()
    model = load_overview(args.date)
    if model.error or model.debug_error:
        raise SystemExit("Static export stopped: source verification failed. Inspect the existing adapter's debug result.")
    output = resolve_results_path("DEMO_CONSOLE_R1_RUNTIME_CLOSURE_AND_VISUAL_ACCEPTANCE")
    output.mkdir(parents=True, exist_ok=True)
    for name, presentation in (("overview.html", True), ("overview_debug.html", False)):
        path = output / name
        path.write_text(render_html(model, presentation), encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
