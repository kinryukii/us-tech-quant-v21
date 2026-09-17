"""Display explicit shares-before/after snapshots; no portfolio reconstruction."""
import math

from apps.demo_console.adapters.artifact_reader import ArtifactError, iso_date, read_frozen_parquet
from apps.demo_console.config.demo_config import ArtifactSpec
from apps.demo_console.models import HoldingRow


def execution_dates(spec: ArtifactSpec) -> tuple[str, ...]:
    values = read_frozen_parquet(spec, ("execution_date",)).column("execution_date").to_pylist()
    return _execution_dates(values)


def _execution_dates(values) -> tuple[str, ...]:
    dates = tuple(sorted(iso_date(value) for value in values))
    if len(set(dates)) != len(dates):
        raise ArtifactError("DUPLICATE_EXECUTION_DATE")
    return dates


def read_portfolio(spec: ArtifactSpec, execution_date: str):
    records = read_frozen_parquet(spec,
        ("date", "previous_date", "ticker", "shares_before", "shares_after", "model", "portfolio"),
        [("date", "==", execution_date)]).to_pylist()
    return portfolio_from_records(records)


def read_portfolio_groups(spec: ArtifactSpec) -> dict[str, list[dict]]:
    records = read_frozen_parquet(spec,
        ("date", "previous_date", "ticker", "shares_before", "shares_after", "model", "portfolio")).to_pylist()
    groups: dict[str, list[dict]] = {}
    for row in records:
        groups.setdefault(iso_date(row["date"]), []).append(row)
    return groups


def portfolio_from_records(records: list[dict]):
    """Validate a verified execution slice without reconstructing positions."""
    if not records:
        raise ArtifactError("PORTFOLIO_NOT_AVAILABLE")
    if len({row["ticker"] for row in records}) != len(records):
        raise ArtifactError("DUPLICATE_HOLDING")
    if {row["model"] for row in records} != {"A2_HGB"} or {row["portfolio"] for row in records} != {"TOP20_EQUAL_WEIGHT_LONG_ONLY"}:
        raise ArtifactError("PORTFOLIO_IDENTITY_MISMATCH")
    before, after = set(), set()
    for row in records:
        if not isinstance(row["ticker"], str) or not row["ticker"].strip():
            raise ArtifactError("INVALID_HOLDING_TICKER")
        for field in ("shares_before", "shares_after"):
            if row[field] is None or not math.isfinite(row[field]) or row[field] < 0:
                raise ArtifactError("INVALID_HOLDING_QUANTITY")
        if row["shares_before"] > 0:
            before.add(row["ticker"])
        if row["shares_after"] > 0:
            after.add(row["ticker"])
    previous_dates = {iso_date(row["previous_date"]) for row in records}
    if len(previous_dates) != 1:
        raise ArtifactError("CONFLICTING_PREVIOUS_DATE")
    holdings = tuple(HoldingRow(rank=None, ticker=t, held_before=t in before) for t in sorted(after))
    return holdings, tuple(sorted(before)), previous_dates.pop()


def read_execution_metadata(spec: ArtifactSpec, execution_date: str) -> dict:
    rows = read_frozen_parquet(spec, ("execution_date", "model"),
        [("execution_date", "==", execution_date)],
        ("reconstructed_turnover", "actual_risky_name_count")).to_pylist()
    return execution_metadata_from_records(rows)


def read_execution_groups(spec: ArtifactSpec) -> dict[str, list[dict]]:
    rows = read_frozen_parquet(spec, ("execution_date", "model"),
        optional_columns=("reconstructed_turnover", "actual_risky_name_count")).to_pylist()
    _execution_dates(row["execution_date"] for row in rows)
    return {iso_date(row["execution_date"]): [row] for row in rows}


def execution_metadata_from_records(rows: list[dict]) -> dict:
    if len(rows) != 1 or rows[0]["model"] != "A2_HGB":
        raise ArtifactError("EXECUTION_IDENTITY_MISMATCH")
    value = rows[0].get("reconstructed_turnover")
    if value is not None and (not math.isfinite(value) or value < 0):
        raise ArtifactError("INVALID_TURNOVER")
    return rows[0]
