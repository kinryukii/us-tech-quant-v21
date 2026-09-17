"""Reader behavior against synthetic Parquet; no real research result access."""
from dataclasses import replace
from datetime import date

import pyarrow as pa
import pytest

from apps.demo_console.adapters.artifact_reader import ArtifactError, read_frozen_parquet
from apps.demo_console.config.demo_config import ArtifactSpec
from apps.demo_console.adapters.ranking_reader import read_ranking
from apps.demo_console.adapters.portfolio_reader import read_portfolio


def test_missing_file_is_explicit_io_error(artifact_dir):
    spec = ArtifactSpec("missing", artifact_dir / "missing.parquet", "0" * 64,
                        ("decision_date",))
    with pytest.raises(FileNotFoundError):
        read_frozen_parquet(spec, ("ticker",))


def test_empty_file_has_artifact_error(artifact_dir):
    path = artifact_dir / "empty.parquet"
    path.write_bytes(b"")
    spec = ArtifactSpec("empty", path, "0" * 64, ("decision_date",))
    with pytest.raises(ArtifactError) as caught:
        read_frozen_parquet(spec, ("ticker",))
    assert "EMPTY_OR_INVALID_PARQUET" in str(caught.value)


def test_sha_mismatch_fails_closed(make_artifact):
    spec = make_artifact([{"decision_date": date(2025, 12, 1), "ticker": "SYNTH"}])
    with pytest.raises(ArtifactError) as caught:
        read_frozen_parquet(replace(spec, sha256="0" * 64), ("ticker",))
    assert "ARTIFACT_IDENTITY_MISMATCH" in str(caught.value)


def test_required_column_missing_is_schema_error(make_artifact):
    spec = make_artifact([{"decision_date": date(2025, 12, 1), "ticker": "SYNTH"}])
    with pytest.raises(ArtifactError) as caught:
        read_frozen_parquet(spec, ("score",))
    assert "MISSING_COLUMNS:score" in str(caught.value)


def test_projection_preserves_real_fields_and_date_selection(make_artifact):
    spec = make_artifact([
        {"decision_date": date(2025, 12, 1), "ticker": "SYNTH_A", "score": 0.4,
         "unused_result": 91.0},
        {"decision_date": date(2025, 12, 2), "ticker": "SYNTH_B", "score": 0.7,
         "unused_result": -81.0},
    ])
    table = read_frozen_parquet(
        spec, ("decision_date", "ticker", "score"),
        filters=[("decision_date", "==", date(2025, 12, 2))],
    )
    assert table.column_names == ["decision_date", "ticker", "score"]
    assert table.to_pylist() == [
        {"decision_date": date(2025, 12, 2), "ticker": "SYNTH_B", "score": 0.7}
    ]


def test_valid_empty_table_is_clear_error(make_artifact):
    schema = pa.schema([("decision_date", pa.date32()), ("ticker", pa.string())])
    spec = make_artifact([], schema=schema)
    with pytest.raises(ArtifactError):
        read_frozen_parquet(spec, ("ticker",))


def test_explicit_nullable_previous_date_preserves_null_without_weakening_event_date(make_artifact):
    spec = make_artifact([
        {"decision_date": date(2025, 12, 1), "previous_date": None, "ticker": "SYNTH_FIRST"},
        {"decision_date": date(2025, 12, 2), "previous_date": date(2025, 12, 1), "ticker": "SYNTH_NEXT"},
    ], date_columns=("decision_date", "previous_date"))
    with pytest.raises(ArtifactError, match="UNPROVEN_DATE_BOUNDARY:previous_date"):
        read_frozen_parquet(spec, ("decision_date", "previous_date", "ticker"))
    nullable = replace(spec, nullable_date_columns=("previous_date",))
    rows = read_frozen_parquet(nullable, ("decision_date", "previous_date", "ticker")).to_pylist()
    assert rows[0]["previous_date"] is None
    assert rows[1]["previous_date"] == date(2025, 12, 1)
    with pytest.raises(ArtifactError, match="MISSING_TEMPORAL_CONTRACT"):
        read_frozen_parquet(replace(nullable, nullable_date_columns=spec.date_columns), ("ticker",))


@pytest.mark.parametrize("expose_optional", [False, True])
def test_top20_uses_recorded_rank_and_optional_fields(make_artifact, expose_optional):
    rows = [{"signal_date": "2025-12-01", "ticker": f"SYNTH_{rank:02}", "a2_rank": rank}
            for rank in range(20, 0, -1)]
    if expose_optional:
        for row in rows:
            # Deliberately increasing with rank: display must not rerank scores.
            row.update(a2_prediction=float(row["a2_rank"]), universe_size=99)
    spec = make_artifact(rows, date_columns=("signal_date",))
    ranking, universe = read_ranking(spec, "2025-12-01")
    assert [(row.rank, row.ticker) for row in ranking] == [
        (rank, f"SYNTH_{rank:02}") for rank in range(1, 21)
    ]
    assert universe == (99 if expose_optional else None)
    assert [row.score for row in ranking] == (
        [float(rank) for rank in range(1, 21)] if expose_optional else [None] * 20
    )
    assert all(row.raw_action is None and row.rx_action is None and row.final_action is None
               and row.rank_change is None and row.held_before is None for row in ranking)


@pytest.mark.parametrize("case", ["missing_date", "incomplete", "duplicate_rank", "duplicate_ticker"])
def test_invalid_top20_is_not_repaired_or_synthesized(make_artifact, case):
    rows = [{"signal_date": "2025-12-01", "ticker": f"SYNTH_{rank:02}", "a2_rank": rank}
            for rank in range(1, 21)]
    if case == "incomplete":
        rows.pop()
    elif case == "duplicate_rank":
        rows[-1]["a2_rank"] = 1
    elif case == "duplicate_ticker":
        rows[-1]["ticker"] = rows[0]["ticker"]
    spec = make_artifact(rows, date_columns=("signal_date",))
    with pytest.raises(ArtifactError):
        read_ranking(spec, "2025-12-02" if case == "missing_date" else "2025-12-01")


def test_portfolio_reads_shares_without_inventing_rx_actions(make_artifact):
    rows = [
        {"ticker": "SYNTH_RETAIN", "shares_before": 2.0, "shares_after": 3.0},
        {"ticker": "SYNTH_ENTER", "shares_before": 0.0, "shares_after": 4.0},
        {"ticker": "SYNTH_EXIT", "shares_before": 5.0, "shares_after": 0.0},
    ]
    for row in rows:
        row.update(date="2025-12-02", previous_date="2025-12-01", model="A2_HGB",
                   portfolio="TOP20_EQUAL_WEIGHT_LONG_ONLY")
    spec = make_artifact(rows, date_columns=("date", "previous_date"))
    holdings, before, previous_date = read_portfolio(spec, "2025-12-02")
    assert before == ("SYNTH_EXIT", "SYNTH_RETAIN")
    assert previous_date == "2025-12-01"
    assert [(row.ticker, row.held_before) for row in holdings] == [
        ("SYNTH_ENTER", False), ("SYNTH_RETAIN", True)
    ]
    assert all(row.rx_action is None and row.final_action is None and row.weight is None
               and row.score is None and row.rank is None for row in holdings)
