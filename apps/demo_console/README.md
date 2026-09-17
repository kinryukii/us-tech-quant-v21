# US Tech Quant — Research & Portfolio Decision Console

A read-only Streamlit presentation workspace over existing frozen pre-2026
research artifacts. The current, explicitly authorized extension includes Raw A2
execution performance and a separately verified frozen A control. It does not
train models, rerun research, alter strategy rules, connect to a broker, or write
authoritative data.

## Five main sections

- **System overview (landing page; internal workspace key `Overview`):** one
  ranked-stock selector leads a four-step case: recorded information boundary,
  original model score/rank, before/after portfolio membership and linked
  execution date. The observed membership state is explicit, including names
  not held and unavailable membership. **Follow this case** starts the guided
  walkthrough; **Inspect this decision** opens its decision trace.
  The portfolio context follows the case. Its original net return path, frozen
  A control and return/cost/drawdown metrics describe the whole Raw A2 portfolio,
  not the selected stock's contribution. Changing the case does not change that
  path. The execution window and fee/comparison basis remain beside the metrics;
  the underwater path is expandable. The canvas reuses
  the canonical read-only `performance_reader.read_performance()` at the selected
  decision's linked execution cutoff, over the same already-authorized daily
  archives used by Research. Clicking a point or choosing an execution date
  updates the local daily-record inspector; it never changes the global decision
  date or extends that cutoff. The six-capability inspector is inside the
  collapsed **System mechanisms & research coverage** section: information timing, model lineage, execution
  mechanics, risk inspection, research discipline and storage separation. Each
  capability explains its mechanism, inspectable evidence and limits. This is
  an editorial explanation, not an accepted component registry or a live health
  monitor. Source-based engineering descriptions are distinguished from frozen
  replay observations; current adoption or operational status is not inferred.
  Comparison, portfolio recovery and the Reliability drill are secondary tools
  within this same collapsed section. The drill includes a clearly labeled synthetic example
  calling the canonical 13F pure timing functions. Fixed New York timestamps
  before, at and after the inclusive 16:00 cutoff, plus a timestamp without a
  timezone, demonstrate availability, deferral or rejection using only the two
  supplied sessions, January 2 and 3, 2025. It reads no filings, prices, models,
  registries or new result artifacts, and does not validate the full PIT chain.
  Its four stages show supplied input, canonical validation, timing impact and
  correction/recheck. The default missing-timezone case is rejected; the recheck
  supplies the explicit New York offset and actually runs the same pure helper.
  Changing the input clears a previous recheck; language changes preserve it.
- **Machine learning:** the selected date's complete recorded Top20 score profile
  sits beside a four-step research case: decision date, original rank/score,
  before/after membership and linked execution date. Clicking a score bar or selecting a
  ranked stock links its original rank, score and before/after portfolio membership.
  The chart preserves negative and zero scores, omits missing coordinates, and
  does not re-rank or turn scores into probabilities. The focused stock carries
  into the existing decision-trace and comparison actions without changing the
  global date. The two main actions inspect and compare the case; lineage,
  portfolio recovery and provenance are grouped in a secondary popover.
  Compact model context is below the working area; the mechanism
  schematic, objective and abbreviated configuration identity are inside
  **Model mechanism and objective**. The separate expandable feature atlas has
  32 feature definitions in five families. Other sections expose
  same-date dual-stock raw scores and ranks; 20/60-snapshot comparison charts;
  and annual training/label-maturity endpoints from the verified freeze.
  The selected studio section is retained across languages and navigation.
  Decision trace links a selected ranked name to the recorded eligible universe,
  raw score, prior membership and subsequent execution holdings, with the exact
  information/decision/execution dates. This is a factual record sequence, not
  local feature attribution or evidence of RX approval. Its actions carry the
  selected name into History or open the drawdown and recovery workspace.
  Original HGB parameters are displayed as configuration limits, not measured
  tree counts. The evidence map separates recorded metadata, historical outputs,
  missing local attribution, and uncomputed predictive-quality diagnostics.
  Historical stage models were not persisted; the supplemental full-period
  model is not substituted for historical predictions or explanations. The
  feature atlas shows definitions and formulas, never fabricated feature values.
- **Decisions & portfolio:** one main navigation item groups the existing
  `Portfolio` and `History` routes. A native segmented control switches between
  Holdings and Historical replay; external callbacks, selected dates and language
  changes retain the correct subgroup. Holdings provides ticker search,
  record-set and membership filters, a linked security inspector, and consecutive
  recorded holdings comparisons. Historical replay provides decision-date selection;
  20/60/120/all-snapshot windows; entries,
  exits and executed turnover; security rank/score trajectories; holdings bands;
  and inspectable snapshot and security logs. Missing observations remain gaps.
  The current Top20 holdings matrix preserves the current recorded ranking order,
  with at most 20 securities and the latest 60 snapshots in the selected window.
  Its cells describe subsequent execution holdings. Clicking a row updates the
  security selector, summary and trajectory; a later manual choice takes priority
  over an old matrix selection.
- **Performance & risk (internal route `Research`):** net/gross growth, window drawdown, monthly and yearly returns,
  the optional A control, daily return distribution, growth concentration,
  descriptive autocorrelation, fixed 63-execution-day rolling net returns and
  explicit evidence limits. Rolling windows use only the selected range, include
  their first day's return, and share observations; they are not independent
  trials. A read-only table under the rolling chart exposes the same start/end
  dates, observation counts and raw returns; the A column follows the chart's
  reference toggle and availability. An expandable matched-date table places each portfolio's cumulative
  net return beside its maximum drawdown and worst daily net return. This keeps
  the return comparison's downside visible without claiming a risk-adjusted rank.
  The wealth chart marks the deepest recorded drawdown with a pale amber span
  between its actual peak and trough, plus the trough's actual net-wealth point.
  An initial undated peak never creates a fabricated dated span.
  A dedicated **Drawdown & recovery** tab enumerates all underwater episodes
  inside the selected execution window. Each episode retains its actual peak,
  trough and observed recovery or unrecovered cutoff, together with depth and
  observed intervals. The default is the latest episode chronologically;
  selecting an episode changes only the display. Initial window baselines have
  no invented date, and a shorter window cannot borrow recovery from later rows.
  Episode records describe this portfolio's historical path, not independent
  trials, forecast recovery times or proof of a risk controller.
  A dedicated Execution frictions subtab
  shows days with recorded flags, cash/NAV, recorded simulated turnover, costs in
  source units and daily details. A month inspector drills into the selected
  window's recorded daily path, month-local drawdown and cost ledger; its month
  selector preserves valid choices across languages and never changes the global
  decision date. Clicking a recorded heatmap month opens this same inspector;
  later manual choices or changed windows supersede old chart selections.
  Missing fields are not converted to zero.
- **Research evidence (internal route `Evidence`):** information/decision/execution dates, source coverage, immutable
  artifact identities and limitations. Presentation Mode hides full private
  paths, complete hashes and debug details; turning it off exposes diagnostics,
  including a separately failed reference source.

The light canvas uses dark text and cobalt-blue actions; ink navigation and
dark analytical plots provide contrast, with amber drawdown accents. The top utility bar contains the global
decision-date selector and language selector. The narrow sidebar contains the
five main sections, previous/next snapshot controls and the Display & motion
popover. Its walkthrough launcher appears only outside Overview; the landing
page has a single main **Follow this case** entry. The former six-node navigation
map and duplicate full-portfolio panel are removed. Full holdings inspection
remains in Decisions & portfolio.

The landing panel places its actual execution window, recorded-fee basis and
same-study comparison scope directly above the return metrics. The displayed
end date is bounded by the selected decision's linked execution. The case and
its two main actions precede this portfolio context. Simulation flags remain
available in the inspector's popover. A compact geometric UTQ mark and consistent
tabular numerals identify the workspace. At narrow widths, the date and language
controls remain beside each other while the return metrics form two rows.
Key evidence notes follow Presentation Mode's text size instead of fixed tiny
type. Detailed walkthrough notes use a secondary popover; its current question and
navigation remain visible.

The ML engine includes a four-step selected-security case
joining the original rank and score with recorded before/after membership and
the linked execution date. Missing observations remain explicitly unrecorded.
The case links to portfolio drawdown and source provenance without changing the
global decision date. Portfolio drawdown is not represented as the security's
contribution. The validation map separates observable records from unestablished
claims, including incremental model advantage and independent confirmation.
These additions reuse the existing immutable models and readers; they add no
economic source, prediction-quality computation or new research evaluation.

The interface supports 中文, 日本語 and English using a local translation
catalog. Language changes preserve dates, filters and raw ticker
values. Fixed native tab groups store their original source identifiers, keeping
the active tab across translations and leaving/returning to its workspace.
History's security log also keeps its selected tab when the displayed ticker changes.
The language choice is URL-bound. No translation service is used.

Public design references: [Linear](https://linear.app/),
[Palantir AIP](https://www.palantir.com/platforms/aip/),
[Goldman Sachs Marquee](https://marquee.gs.com/welcome/our-platform/portfolio-analytics/equities)
and [Two Sigma](https://www.twosigma.com/). These public pages inform visual
hierarchy, typography and navigation only; they do not imply equivalent model
capabilities, investment results or production maturity.

The recommended walkthrough follows **System overview → Machine
learning → Portfolio → History → Research: Drawdown & recovery → Evidence**.
The opening stop follows one recorded case; the model stop inspects its original
score and lineage, and the Portfolio stop opens the ranked records with its
subsequent holding status. Each stop poses one question and points to the
available evidence. The shared
`start_guided_tour()` callback serves the landing action and sidebar launcher.
The tour carries the same valid ranked security through ML, Portfolio and
History while preserving the selected decision date; it does not start replay.
A compact case strip on every other page retains the stock, decision date and
execution date. Research additionally labels this as portfolio context.
Changing the comparison's primary security updates the shared case; its
secondary security remains independent. The model stop opens Model engine, and the Research
stop opens Drawdown & recovery with the full window through the selected
execution, so setbacks are inspected before the broader performance story.
Manual navigation preserves the user's selected Research tab and controls.
History playback starts only with **Play**, advances through
existing snapshots with a three-second timer between rendered frames, and supports
pause, resume and restart. Its range is locked to the chosen window and endpoint. Each frame shows
only the locked start through the current decision; stale timer events cannot
advance a changed view, date or window. Navigation and language changes pause it.
Playback and manual date selection change the research cutoff. For a full-range
presentation after demonstrating a few replay frames, pause and restore the
decision date to 2025-12-29 before continuing to Research. On leaving the tour,
keyboard focus returns to the visible landing action, sidebar launcher or
sidebar opener, with the page heading as a final visible fallback.

Display & motion controls provide presentation sizing and optional transitions.
Chart axis and legend text uses 15px in Presentation Mode and 13px otherwise,
without changing the displayed observations or scale domains.
Single-view charts size the complete frame, including axes and legends, so
native fullscreen retains the date axis within the available screen height.
Motion respects reduced-motion preferences. Score-chart hover highlighting is
client-side and preserves the underlying scores. The ML chart's click selection
updates the focused case without changing its date; stale or foreign selection events
cannot override a changed record context. Ranking tables retain recorded rank
order; scores are not probabilities, weights or returns.

## Run locally

From `D:\us-tech-quant`:

```powershell
./apps/demo_console/start.ps1
```

The launcher uses the existing external
`D:\us-tech-quant-envs\demo-console\Scripts\python.exe` runtime with Streamlit
1.63.0, resolved through the canonical storage helper. Its default remains
`127.0.0.1:8501`; use `-Port 8502` for an explicitly chosen alternate port.
The current demonstration session on **8504 is maintained separately** and does
not change the launcher's default or shared configuration.

The foreground launcher disables file watching, suppresses browser error details,
installs nothing, and restores its process environment on exit. Stop a console
you started with Ctrl+C. The app-local `.streamlit/config.toml` disables usage
telemetry. No global Streamlit configuration or environment is changed.

## Frozen sources and read boundary

The Raw A2 economic identity is `RAW_A2_HGB_BASELINE`, backed by the accepted
canonical `A2/` artifact arm. These are retrospectively assembled historical
research records, not live account positions or daily production output.
The default selected decision is **2025-12-29**, linked to execution on
**2025-12-30**; dates are selected by recorded coverage, not by returns.

Pinned inputs under `results_root/A_VS_A2_QUARTERLY_13F_R1`:

| Input | Consumed role |
| --- | --- |
| `audit/freeze_r1/frozen_baseline_manifest.json` | Frozen identity, producer, contracts and recorded audit metadata |
| `audit/freeze_r1/frozen_artifact_hashes.csv` | Exact path/hash/role bindings; references do not cause other artifacts to be opened |
| `A2/top20_selections.parquet` | Signal date, ticker, original rank, optional prediction and eligible-universe count |
| `A2/position_ledger.parquet` | Recorded date alignment, quantities and portfolio/model identity for membership comparisons |
| `A2/portfolio_daily.parquet` | Execution metadata; NAV, gross/net daily returns, cash, position value, turnover, costs, execution counts and accounting checks for Overview and Research |
| `A/portfolio_daily.parquet` | Optional fixed A control, using the same validated performance schema and execution calendar |

`config/demo_config.py` binds exact frozen SHA identities. Each Parquet read uses
one read-only handle: read only the exact footer, prove every declared date
column's row-group bounds are pre-2026, verify the hash, then project the columns
needed by that consumer. Primary dates cannot be null; the position source's
explicitly permitted initial `previous_date` nulls remain missing. Its additional
mark-date boundary is also checked. No unknown mixed-year file is loaded first
and filtered afterward. Missing statistics, columns, identity or hash mismatches
fail closed. No disk cache of economic records is written by the app.

Performance validation checks unique ascending execution dates, finite values,
positive NAV, returns above -100%, initial capital, terminal liquidation, model
identity and accounting continuity, including gross/net/cost relationships with
an absolute tolerance of `1e-12`. The A control additionally requires its frozen
model/contract/role bindings and the same complete execution calendar. If A is
missing or invalid, only the comparison becomes unavailable; verified A2 data
remains available. Requested 2026+ performance dates are rejected before I/O.

The extension consumes existing execution returns and NAV. It does not load
training data, full features, OOF prediction files, independent price histories,
broker data or real 2026 outcomes. It does not reconstruct new prices or run a
second strategy engine.

## Research interpretation

- The frozen execution archive spans **2023-01-04 through 2025-12-31**, with
  **751 rows**. At the latest selected decision's execution, **2025-12-30**, the
  Overview and Research views have **750 rows**. The final 2025-12-31 liquidation is excluded
  because it occurs after that execution. Earlier selections likewise stop at
  their linked execution. The adapter's explicit full-archive request
  `read_performance(None)` includes the terminal row; the selected-decision UI
  does not silently extend its cutoff to include it.
- Growth is rebased to 1 immediately before the first included daily return.
  The first observation and its entry cost are included. Shorter windows compound
  all included returns; their drawdown is measured within that window. Period
  tables distinguish a window cutting through recorded observations from an
  archive boundary. They do not invent missing trading days.
- Gross returns are before that execution's recorded transaction cost on the
  existing holdings path. Compounding them is **not a separate fee-free backtest**.
  Cost amounts, cash and position values retain the original initial-NAV unit
  (initial capital = 1), even in a shorter window. The sum of cost amounts is
  different from the gross–net compounded return gap in percentage points.
- The frozen A portfolio is a strategy control, **not QQQ or a market benchmark**.
  Same-date return differences do not establish risk-adjusted alpha. Concentration,
  positive-period frequency and autocorrelation are descriptive; the display
  does not claim independent statistical advantage, skill probability or live
  readiness, and does not infer Sharpe significance, DSR or PBO.
- Execution flags describe recorded simulation events. Zero means no such flag
  was recorded, not proof of execution capability. A buy cash scale below 1 can
  reflect ordinary fee funding. The first two holdings comparison gaps
  remain visible and do not create gaps in the separately validated performance
  series.
- Ranks and membership changes remain producer output and consecutive-record
  comparisons. They are not trade instructions, RX actions or inferred causes.
  Stateful RX has no authorized historical backfill here; its accepted/prevented
  actions and combined final portfolio remain **NOT_EXPOSED / N/A**. Previous-
  interval `position_weight` is not presented as a final holding weight.
- Recorded as-of dates and consumed-file checks do not constitute new upstream
  PIT validation or prove that retrospective history was untouched during model
  selection. Presentation Mode changes disclosure and sizing, never model values.

## Architecture and validation

`frozen outputs → adapters → immutable models → pages/components → Streamlit`.
`decision_reader.py` supplies decision/history snapshots; `performance_reader.py`
supplies cutoff-limited execution observations and the verified archive calendar.
Pure components compute display statistics from those immutable records. Native
selection callbacks link views, and the replay timer carries only date/token
metadata. Storage resolution and existing date-alignment contracts are reused.
`system_overview.py` joins the selected case's existing output and membership
records, then reuses the canonical performance reader and existing wealth,
drawdown and summary components for the portfolio context. Its native
execution selection inspects only records already inside the global cutoff;
there is no parallel reader, source archive or strategy calculation. Its folded
capability inspector uses source references without reading the current research
registry or operational status. `pit_timing.py` delegates
its fixed synthetic example to `accepted_utc`, `filing_is_public_for_signal` and
`first_legal_signal_session`; it does not implement a second timing policy or
call filing readers or research runners.
Charts use the installed Altair runtime; playback uses Streamlit's native
component API. No new runtime package is required.

Run the focused suite from the repository root:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& D:\us-tech-quant-envs\demo-console\Scripts\python.exe -B -c "import sys,streamlit,pandas,pyarrow; sys.path.append(r'D:\us-tech-quant-envs\us-tech-quant-main\Lib\site-packages'); import pytest; raise SystemExit(pytest.main(['-q','apps/demo_console/tests','-o','cache_dir=D:/us-tech-quant-results/demo-console/cache/pytest']))"
```

This reuses the existing quant environment's test runner without installing
packages or changing either environment. Fixtures use synthetic records in the
resolved external test cache. Coverage includes footer-first rejection, frozen
identity, accounting and cutoff checks, optional-control degradation, immutable
values, chart gaps, privacy, translations, guided navigation and replay. System
coverage includes default landing navigation, capability scope, the canonical
synthetic timing boundaries, and the walkthrough's initial drawdown tab. Native
AppTest events verify local execution inspection, score-to-security selection,
matrix-to-security linkage and translated tab persistence;
all tab contents continue to render. A skipped runtime test is not acceptance.

CUA now provides actual browser interaction and visual inspection against the
running local demonstration. Earlier localhost-access limitations are historical,
not the current validation status. The task's final report records the exact
focused-suite run and browser evidence rather than freezing a changing pass count
in this README. Harness preflight remains intentionally unused because its
independent-code path would read holdout content outside this UI task's scope.

## Historical static fallback

The original console exposed decision/membership evidence only. Before the user
provided the working Streamlit runtime, a thin English HTML export was retained
as an emergency preview. Those earlier scope and runtime notes do not describe
the current authorized performance extension or browser access.

```powershell
& D:\us-tech-quant-envs\demo-console\Scripts\python.exe -B -m apps.demo_console.tools.render_static_preview
```

The exporter writes `overview.html` and `overview_debug.html` under
`results_root/DEMO_CONSOLE_R1_RUNTIME_CLOSURE_AND_VISUAL_ACCEPTANCE`, using the same
read-only model and escaped display primitives. It is a static fallback, not a
replacement for the five-section Streamlit demonstration.
