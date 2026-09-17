"""Join frozen display records. Contains no strategy decisions or producers."""
from __future__ import annotations

from dataclasses import replace

from apps.demo_console.adapters.artifact_reader import ArtifactError, iso_date
from apps.demo_console.adapters.portfolio_reader import (
    execution_dates, execution_metadata_from_records, portfolio_from_records,
    read_execution_groups, read_execution_metadata, read_portfolio, read_portfolio_groups,
)
from apps.demo_console.adapters.ranking_reader import (
    ranking_dates, ranking_from_records, read_ranking, read_ranking_groups,
)
from apps.demo_console.adapters.system_status_reader import learning_profile, pipeline_stages, read_freeze
from apps.demo_console.config.demo_config import DemoConfig, default_config
from apps.demo_console.models import DecisionOverview, PipelineStage, Provenance


LIMITATIONS = (
    "Historical frozen Raw A2 research baseline. This is neither a live account nor a combined Raw A2 + stateful RX portfolio.",
    "Stateful RX has no authorized pre-2026 holding/replacement trace here. RX actions and the combined final portfolio are unavailable.",
    "Entered / retained / exited compare actual Raw A2 holding snapshots; they are not explanations of RX decisions.",
    "Turnover and holdings are replay execution observations, available after the signal date; they are not decision-time inputs.",
    "Information as-of is the recorded close signal date. Exact information timestamp and historical security IDs are not exposed.",
    "Rank change compares recorded Top20 ranks only; a name absent from the previous Top20 has no exposed previous rank.",
    "Frozen results were assembled retrospectively. Evidence integrity does not establish new PIT validation, independent holdout status or live readiness.",
)


def load_overview(date: str | None = None, config: DemoConfig | None = None) -> DecisionOverview:
    """Contain ordinary missing/schema/identity errors without exposing tracebacks."""
    available: tuple[str, ...] = ()
    try:
        if date is not None and iso_date(date) >= "2026-01-01":
            raise ArtifactError("POST2025_DATE_BLOCKED")
        config = config or default_config()
        manifest = read_freeze(config)
        available = ranking_dates(config.ranking)
        if not available:
            raise ArtifactError("NO_HISTORICAL_DATES")
        selected = date or available[-1]
        if selected not in available:
            raise ArtifactError("DATE_NOT_AVAILABLE")
        return _assemble_snapshot(selected, available, config, manifest,
            lambda day: read_ranking(config.ranking, day),
            lambda: execution_dates(config.daily),
            lambda day: read_portfolio(config.positions, day),
            lambda day: read_execution_metadata(config.daily, day))
    except Exception as exc:
        return _unavailable(date, available, exc)


def _alignment(available: tuple[str, ...], executions: tuple[str, ...]) -> None:
    # Existing attribution consumer signal_maps() establishes this frozen-calendar
    # alignment. Display joins do not become a separate execution policy.
    if len(executions) != len(available) + 1 or any(s >= e for s, e in zip(available, executions[:-1])):
        raise ArtifactError("SIGNAL_EXECUTION_ALIGNMENT_UNPROVEN")


def _unavailable(date, available, exc) -> DecisionOverview:
    return DecisionOverview(decision_date=date, available_dates=available,
        pipeline=(PipelineStage("Evidence", "BLOCKED", "Artifact access, date, schema or identity could not be verified."),),
        limitations=LIMITATIONS,
        error="Historical decision unavailable. Check the selected date and the frozen source bindings in Debug mode.",
        debug_error=f"{type(exc).__name__}: {exc}")


def _assemble_snapshot(selected, available, config, manifest,
                       get_ranking, get_executions, get_portfolio, get_metadata) -> DecisionOverview:
    """One join/validation path for single-day readers and verified in-memory slices."""
    index = available.index(selected)
    ranking, universe = get_ranking(selected)
    previous_ranking = get_ranking(available[index - 1])[0] if index else ()
    old_ranks = {row.ticker: row.rank for row in previous_ranking}
    ranking = tuple(replace(row, rank_change=old_ranks[row.ticker] - row.rank
        if row.ticker in old_ranks else None) for row in ranking)
    limitations = list(LIMITATIONS)
    holdings, previous, retained, entered, exited = (), None, None, None, None
    turnover, execution = None, None
    portfolio_error = None
    try:
        executions = get_executions()
        _alignment(available, executions)
        execution = executions[index]
        current, before, previous_date = get_portfolio(execution)
        if previous_date != selected:
            raise ArtifactError("POSITION_SIGNAL_DATE_MISMATCH")
        metadata = get_metadata(execution)
        if metadata.get("actual_risky_name_count") not in (None, len(current)):
            raise ArtifactError("PORTFOLIO_COUNT_MISMATCH")
        if index:
            old_holdings, _, _ = get_portfolio(executions[index - 1])
            previous = tuple(row.ticker for row in old_holdings)
            if set(previous) != set(before):
                raise ArtifactError("PREDECESSOR_HOLDINGS_MISMATCH")
            now, old = {row.ticker for row in current}, set(previous)
            retained, entered, exited = tuple(sorted(now & old)), tuple(sorted(now - old)), tuple(sorted(old - now))
        ranking = tuple(replace(row, held_before=row.ticker in before) for row in ranking)
        # Do not attach ranking/score to holdings: the portfolio layer is distinct.
        holdings = current
        turnover = metadata.get("reconstructed_turnover")
    except Exception as exc:
        portfolio_error = f"{type(exc).__name__}: {exc}"
        holdings, previous, retained, entered, exited, turnover = (), None, None, None, None, None
        limitations.append("Portfolio evidence is unavailable or failed verification. Raw A2 Top20 remains independently inspectable.")
    sources = [str(config.manifest_path), str(config.hash_manifest_path), str(config.ranking.path)]
    hashes = [(str(config.manifest_path), config.manifest_sha256),
              (str(config.hash_manifest_path), config.hash_manifest_sha256),
              (str(config.ranking.path), config.ranking.sha256)]
    if holdings:
        sources.extend([str(config.positions.path), str(config.daily.path)])
        hashes.extend([(str(config.positions.path), config.positions.sha256), (str(config.daily.path), config.daily.sha256)])
    contract = manifest.get("contracts", {})
    provenance = Provenance(
        decision_date=selected, information_as_of=selected, execution_date=execution,
        universe_identity=None,
        strategy_identity="Raw A2 control · historical portfolio",
        artifact_sources=tuple(sources),
        producer_identity=manifest.get("artifact_producer_metadata", {}).get("absolute_path"),
        alpha_implementation=contract.get("A2", {}).get("source_path"),
        replay_identity=manifest.get("frozen_baseline_name"),
        artifact_hashes=tuple(hashes), raw_status=manifest.get("status"),
        config_identity=contract.get("A2", {}).get("config_fingerprint"))
    stages = pipeline_stages(manifest, True, bool(holdings))
    if portfolio_error:
        stages = tuple(replace(stage, status="AVAILABLE", detail="Ranking and metadata integrity verified; portfolio evidence has a separate error.")
                       if stage.name == "Evidence" else stage for stage in stages)
    return DecisionOverview(decision_date=selected, available_dates=available, ranking=ranking,
        holdings=holdings, previous_holdings=previous, retained=retained, entered=entered, exited=exited,
        turnover=turnover, eligible_universe_count=universe, pipeline=stages,
        provenance=provenance, limitations=tuple(limitations), debug_error=portfolio_error,
        previous_decision_date=available[index - 1] if index else None,
        learning=learning_profile(manifest))


def load_history(end_date: str | None = None, window: int | None = 60,
                 config: DemoConfig | None = None) -> tuple[DecisionOverview, ...]:
    """Return recorded snapshots through a selected date with bounded input reads.

    Each invocation verifies the original frozen metadata and each consumed
    Parquet projection once. There is no persistent cache. Windowing limits
    output only: the first displayed point retains its true prior snapshot.
    Global failures return one safe error model instead of a false empty history.
    """
    available: tuple[str, ...] = ()
    try:
        if end_date is not None and iso_date(end_date) >= "2026-01-01":
            raise ArtifactError("POST2025_DATE_BLOCKED")
        if window is not None and (isinstance(window, bool) or not isinstance(window, int) or window <= 0):
            raise ArtifactError("INVALID_HISTORY_WINDOW")
        config = config or default_config()
        manifest = read_freeze(config)
        ranking_groups = read_ranking_groups(config.ranking)
        available = tuple(sorted(ranking_groups))
        if not available:
            raise ArtifactError("NO_HISTORICAL_DATES")
        selected = end_date or available[-1]
        if selected not in available:
            raise ArtifactError("DATE_NOT_AVAILABLE")
        selected_dates = available[:available.index(selected) + 1]
        if window is not None:
            selected_dates = selected_dates[-window:]

        execution_groups, position_groups = {}, {}
        executions: tuple[str, ...] = ()
        execution_error, position_error = None, None
        try:
            execution_groups = read_execution_groups(config.daily)
            executions = tuple(sorted(execution_groups))
            _alignment(available, executions)
        except Exception as exc:
            execution_error = exc
        if execution_error is None:
            try:
                position_groups = read_portfolio_groups(config.positions)
            except Exception as exc:
                position_error = exc

        def get_executions():
            if execution_error is not None:
                raise execution_error
            return executions

        def get_portfolio(day):
            if position_error is not None:
                raise position_error
            return portfolio_from_records(position_groups.get(day, []))

        snapshots = []
        for day in selected_dates:
            try:
                snapshots.append(_assemble_snapshot(day, available, config, manifest,
                    lambda date: ranking_from_records(ranking_groups.get(date, [])),
                    get_executions, get_portfolio,
                    lambda date: execution_metadata_from_records(execution_groups.get(date, []))))
            except Exception as exc:
                snapshots.append(_unavailable(day, available, exc))
        return tuple(snapshots)
    except Exception as exc:
        return (_unavailable(end_date, available, exc),)
