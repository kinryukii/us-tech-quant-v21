"""Catalog CLI checks with synthetic data and no provider/model calls."""
import json
import sqlite3

import pandas as pd
import pytest

from scripts.storage import manage_data as cli
from scripts.storage.storage_r2a import CATALOG_SCHEMA_SQL, CATALOG_ROLE, DataStore, StoragePaths


@pytest.fixture
def store(tmp_path):
    roots = ["repo_root", "data_root", "cache_root", "daily_root", "backtest_root", "results_root", "envs_root"]
    result = DataStore(StoragePaths(**{key: tmp_path / key for key in roots}))
    result.catalog_path.parent.mkdir(parents=True)
    with sqlite3.connect(result.catalog_path) as connection:
        connection.executescript(CATALOG_SCHEMA_SQL)
        connection.executemany("INSERT INTO catalog_metadata VALUES (?, ?)", [
            ("schema_version", "1"), ("catalog_role", CATALOG_ROLE)
        ])
    return result


def price_file(store, ticker="ABC", adjustment="raw", first="2026-08-19", last="2026-08-21"):
    path = store.paths.data_root / "stocks" / ticker / f"daily_{adjustment}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"ticker": [ticker, ticker], "date": [first, last], "close": [10., 11.]}).to_parquet(path)
    with sqlite3.connect(store.catalog_path) as connection:
        connection.execute("""INSERT INTO data_files
            (dataset,ticker,adjustment,path,row_count,min_date,max_date,is_current)
            VALUES ('prices_daily',?,?,?,?,?,?,1)""", (ticker, adjustment, str(path), 2, first, last))
    return path


def test_subscription_is_idempotent_and_identity_remains_pending(store):
    args = dict(provider_code="US.LEN.B", ticker="LEN/B", start="2019-01-01",
                target="2026-09-11", identity_source="unknown")
    first = cli.register_subscription(store, **args)
    second = cli.register_subscription(store, **args)
    assert first == second
    assert first["subscription"]["status"] == "PENDING_IDENTITY"
    assert first["strategy_universe_changed"] is False
    assert first["download_started"] is False
    assert len(cli.read_catalog(store)[1]) == 1
    args["ticker"] = "LEN.A"
    with pytest.raises(ValueError, match="already belongs"):
        cli.register_subscription(store, **args)


def test_identity_evidence_is_not_automatically_accepted(store):
    result = cli.register_subscription(store, provider_code="US.ABC", ticker="ABC", start="2019-01-01",
                                       target="2026-09-11", identity_source="source-manifest:abc")
    assert result["subscription"]["status"] == "REQUESTED_IDENTITY_REVIEW"
    assert result["identity_authority_changed"] is False


def test_provider_only_additions_remain_in_acquisition_scope(store):
    price_file(store)
    cli.register_subscription(store, provider_code='US.NEW', ticker='NEW', start='2020-01-01',
                              target='2026-09-11', identity_source='unknown')
    with sqlite3.connect(store.catalog_path) as connection:
        connection.execute("""INSERT INTO data_files
            (dataset,ticker,adjustment,path,is_current) VALUES (?,?,?,?,1)""",
            ('prices_daily_yahoo', 'ONLYY', 'split_adjusted', str(store.paths.data_root / 'onlyy.parquet')))
    before=store.catalog_path.read_bytes()
    assert cli.acquisition_tickers(store)==['ABC','NEW','ONLYY']
    assert store.catalog_path.read_bytes()==before


def test_plan_covers_prefix_tail_missing_adjustment_and_subscription(store):
    price_file(store)
    cli.register_subscription(store, provider_code="US.LEN.B", ticker="LEN/B", start="2019-01-01",
                              target="2026-09-11", identity_source="unknown")
    rows = cli.build_plan(store, start="2026-08-18", target="2026-09-04")
    abc = [row for row in rows if row["ticker"] == "ABC"]
    assert [(row["adjustment"], row["start"], row["end"], row["reason"]) for row in abc] == [
        ("raw", "2026-08-18", "2026-08-18", "PREFIX_GAP"),
        ("raw", "2026-08-22", "2026-09-04", "TAIL_GAP"),
        ("qfq", "2026-08-18", "2026-09-04", "MISSING_DATA"),
    ]
    added = [row for row in rows if row["ticker"] == "LEN/B"]
    assert len(added) == 2
    assert {row["moomoo_symbol"] for row in added} == {"US.LEN.B"}
    assert {row["identity_status"] for row in added} == {"PENDING_IDENTITY"}


def test_missing_file_overrides_apparent_complete_catalog_coverage(store):
    path = price_file(store, first="2019-01-01", last="2026-09-11")
    path.unlink()
    plan = cli.build_plan(store, start="2026-09-01", target="2026-09-04", adjustments=["raw"])
    assert plan[0]["reason"] == "MISSING_FILE"
    assert cli.status(store)["price_files_missing_on_disk"] == 1


def test_nontrivial_transport_requires_explicit_subscription_and_ambiguity_blocks(store):
    rows = cli.build_plan(store, start="2026-09-01", target="2026-09-04", tickers=["BRK.B"])
    assert {row["mapping_status"] for row in rows} == {"BLOCKED_PROVIDER_MAPPING_REQUIRED"}
    for provider in ["US.BRK.B", "US.BRK-B"]:
        cli.register_subscription(store, provider_code=provider, ticker="BRK.B", start="2019-01-01",
                                  target="2026-09-11", identity_source="unknown")
    rows = cli.build_plan(store, start="2026-09-01", target="2026-09-04", tickers=["BRK.B"])
    assert {row["mapping_status"] for row in rows} == {"BLOCKED_AMBIGUOUS_PROVIDER_MAPPING"}
    assert {row["moomoo_symbol"] for row in rows} == {""}


def test_status_and_plan_do_not_change_catalog(store):
    price_file(store)
    before = store.catalog_path.read_bytes()
    assert cli.status(store)["price_tickers"] == 1
    rows = cli.build_plan(store, start="2026-09-01", target="2026-09-04")
    output = store.paths.results_root / "fetch-plan.csv"
    cli.write_plan(store, rows, output)
    assert output.is_file()
    assert store.catalog_path.read_bytes() == before
    with pytest.raises(ValueError, match="outside configured"):
        cli.write_plan(store, rows, store.paths.repo_root / "bad.csv")


def test_cli_prices_stdout_limit_and_plan_output(store, monkeypatch, capsys):
    price_file(store)
    monkeypatch.setattr(cli, "resolve_storage_paths", lambda **kwargs: store.paths)
    assert cli.main(["prices", "--ticker", "ABC", "--adjustment", "raw", "--start", "2026-08-01",
                     "--end", "2026-09-01", "--limit", "1"]) == 0
    output = capsys.readouterr().out
    assert len(output.strip().splitlines()) == 2
    plan_file = store.paths.results_root / "fetch-plan.csv"
    assert cli.main(["plan", "--start", "2026-08-01", "--target", "2026-09-01", "--output", str(plan_file)]) == 0
    assert json.loads(capsys.readouterr().out)["download_started"] is False
    assert cli.main(["prices", "--ticker", "ABC", "--start", "2026-08-01", "--end", "2026-09-01", "--limit", "0"]) == 2
    assert "limit" in capsys.readouterr().err
