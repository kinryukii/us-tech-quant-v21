"""Read producer-supplied Top20 ranks. Never rerank scores or truncate a universe."""
import math

from apps.demo_console.adapters.artifact_reader import ArtifactError, iso_date, read_frozen_parquet
from apps.demo_console.config.demo_config import ArtifactSpec
from apps.demo_console.models import HoldingRow


def ranking_dates(spec: ArtifactSpec) -> tuple[str, ...]:
    dates = read_frozen_parquet(spec, ("signal_date",)).column("signal_date").to_pylist()
    return tuple(sorted({iso_date(value) for value in dates}))


def read_ranking(spec: ArtifactSpec, decision_date: str) -> tuple[tuple[HoldingRow, ...], int | None]:
    records = read_frozen_parquet(spec, ("signal_date", "ticker", "a2_rank"),
        [("signal_date", "==", decision_date)], ("a2_prediction", "universe_size")).to_pylist()
    return ranking_from_records(records)


def read_ranking_groups(spec: ArtifactSpec) -> dict[str, list[dict]]:
    """Verify once and group the same authorized projection for historical display."""
    records = read_frozen_parquet(spec, ("signal_date", "ticker", "a2_rank"),
        optional_columns=("a2_prediction", "universe_size")).to_pylist()
    groups: dict[str, list[dict]] = {}
    for row in records:
        groups.setdefault(iso_date(row["signal_date"]), []).append(row)
    return groups


def ranking_from_records(records: list[dict]) -> tuple[tuple[HoldingRow, ...], int | None]:
    """Apply the same recorded Top20 contract to a single verified date slice."""
    if not records:
        raise ArtifactError("DATE_NOT_AVAILABLE")
    tickers = [row["ticker"] for row in records]
    ranks = [row["a2_rank"] for row in records]
    if (len(records) != 20 or len(set(tickers)) != 20 or not all(isinstance(t, str) and t.strip() for t in tickers)
            or set(ranks) != set(range(1, 21))):
        raise ArtifactError("INCOMPLETE_OR_INVALID_TOP20")
    rows = []
    for row in records:
        score = row.get("a2_prediction")
        if score is not None and not math.isfinite(float(score)):
            raise ArtifactError("INVALID_SCORE")
        rows.append(HoldingRow(rank=int(row["a2_rank"]), ticker=row["ticker"],
                               score=float(score) if score is not None else None))
    sizes = {row.get("universe_size") for row in records}
    if len(sizes) != 1:
        raise ArtifactError("CONFLICTING_UNIVERSE_COUNT")
    size = sizes.pop()
    if size is not None and (size < 20 or int(size) != size):
        raise ArtifactError("INVALID_UNIVERSE_COUNT")
    return tuple(sorted(rows, key=lambda r: r.rank)), int(size) if size is not None else None
