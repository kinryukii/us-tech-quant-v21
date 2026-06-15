from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import types
from pathlib import Path


SCRIPT = Path(__file__).resolve().with_name("v20_26_yahoo_runtime_outcome_benchmark_source_adapter.py")


def load_module():
    spec = importlib.util.spec_from_file_location("v20_26_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def read_first(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    return rows[0]


def configure_paths(module, root: Path) -> None:
    module.ROOT = root
    module.CONSOLIDATION = root / "outputs" / "v20" / "consolidation"
    module.READ_CENTER = root / "outputs" / "v20" / "read_center"
    module.OPS = root / "outputs" / "v20" / "ops"
    module.INPUT_BASE = root / "inputs" / "v20" / "outcome_benchmark"
    module.YAHOO_CACHE = module.INPUT_BASE / "yahoo_cache"
    module.YAHOO_V20_26 = module.YAHOO_CACHE / "v20_26"
    module.STAGING_V20_26 = module.INPUT_BASE / "staging" / "v20_26"

    for name in [
        "IN_READ_FIRST", "IN_GATE", "IN_BLOCKERS", "IN_OUTCOME_PLAN", "IN_BENCHMARK_PLAN",
        "IN_COVERAGE", "IN_INPUT_REGISTER", "IN_OUTCOME_SCHEMA", "IN_BENCHMARK_SCHEMA",
        "IN_CANDIDATES", "OUT_DEP", "OUT_ARCH", "OUT_CONFIG", "OUT_SYMBOLS",
        "OUT_BENCHMARK_SYMBOLS", "OUT_ATTEMPT", "OUT_TICKER_STATUS", "OUT_BENCH_STATUS",
        "OUT_CACHE_REGISTER", "OUT_HASH", "OUT_RUN", "OUT_SCHEMA", "OUT_DATE_COVERAGE",
        "OUT_BENCH_COVERAGE", "OUT_STAGED_REGISTER", "OUT_BLOCKERS", "OUT_NEXT",
        "OUT_GATE", "OUT_VALIDATION", "OUT_SOURCE_DIAGNOSTICS",
    ]:
        current = getattr(module, name)
        base = module.OPS if current.name.endswith("READ_FIRST.txt") else module.CONSOLIDATION
        setattr(module, name, base / current.name)
    module.REPORT = module.READ_CENTER / module.REPORT.name
    module.CURRENT_REPORT = module.READ_CENTER / module.CURRENT_REPORT.name
    module.READ_FIRST = module.OPS / module.READ_FIRST.name
    module.TICKER_CACHE = module.YAHOO_V20_26 / "V20_26_YAHOO_TICKER_PRICE_CACHE.csv"
    module.BENCHMARK_CACHE = module.YAHOO_V20_26 / "V20_26_YAHOO_BENCHMARK_PRICE_CACHE.csv"
    module.STAGED_OUTCOME = module.STAGING_V20_26 / "V20_26_STAGED_YAHOO_OUTCOME_SOURCE_INPUT_CANDIDATE.csv"
    module.STAGED_BENCHMARK = module.STAGING_V20_26 / "V20_26_STAGED_YAHOO_BENCHMARK_SOURCE_INPUT_CANDIDATE.csv"
    module.REQUIRED_INPUTS = [
        module.IN_READ_FIRST, module.IN_GATE, module.IN_BLOCKERS, module.IN_OUTCOME_PLAN,
        module.IN_BENCHMARK_PLAN, module.IN_COVERAGE, module.IN_INPUT_REGISTER,
        module.IN_OUTCOME_SCHEMA, module.IN_BENCHMARK_SCHEMA,
    ]


def seed_dependencies(module) -> None:
    module.OPS.mkdir(parents=True, exist_ok=True)
    module.CONSOLIDATION.mkdir(parents=True, exist_ok=True)
    module.IN_READ_FIRST.write_text(
        "\n".join([
            "LOCAL_IMPORTER_OR_MANUAL_STAGING_ONLY: TRUE",
            "CERTIFICATION_EXECUTED: FALSE",
            "BACKTEST_EXECUTED: FALSE",
            "V21_OUTPUT_CREATED: FALSE",
            "V19_21_OUTPUT_CREATED: FALSE",
        ]),
        encoding="utf-8",
    )
    write_csv(module.IN_GATE, [{"STATUS": "PASS_V20_25_LOCAL_OUTCOME_BENCHMARK_IMPORTER_OR_MANUAL_STAGING"}], ["STATUS"])
    for path in [
        module.IN_BLOCKERS, module.IN_OUTCOME_PLAN, module.IN_BENCHMARK_PLAN, module.IN_COVERAGE,
        module.IN_INPUT_REGISTER, module.IN_OUTCOME_SCHEMA, module.IN_BENCHMARK_SCHEMA,
    ]:
        write_csv(path, [{"present": "TRUE"}], ["present"])
    write_csv(
        module.IN_CANDIDATES,
        [{"ticker": "AAA", "effective_price_date": "2026-06-12", "effective_observation_date": "2026-06-12"}],
        ["ticker", "effective_price_date", "effective_observation_date"],
    )


def install_empty_yfinance() -> object:
    class EmptyFrame:
        empty = True

    fake = types.SimpleNamespace(download=lambda *args, **kwargs: EmptyFrame())
    prior = sys.modules.get("yfinance")
    sys.modules["yfinance"] = fake
    return prior


def restore_yfinance(prior: object) -> None:
    if prior is None:
        sys.modules.pop("yfinance", None)
    else:
        sys.modules["yfinance"] = prior


def cache_row(symbol: str, date: str, role: str) -> dict[str, str]:
    return {
        "symbol": symbol,
        "price_date": date,
        "open": "10",
        "high": "11",
        "low": "9",
        "close": "10.5",
        "adjusted_close": "10.5",
        "volume": "100",
        "currency": "USD",
        "data_vendor_or_source_system": "Yahoo/yfinance",
        "provider_query_start_date": "2026-06-05",
        "provider_query_end_date": "2026-08-26",
        "provider_download_timestamp_utc": "2026-06-12T14:58:40+00:00",
        "source_artifact_id": f"V20_26_YAHOO_{role}::{symbol}",
        "source_hash": f"{symbol}_{date}_hash",
        "run_id": "V20_26_YAHOO_RUNTIME_TEST",
        "active_runtime_flag": "TRUE",
        "historical_reference_flag": "FALSE",
        "created_at_utc": "2026-06-12T14:58:40+00:00",
        "notes": "test_real_cache_row",
    }


def test_runtime_empty_without_cache_blocks_handoff() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        configure_paths(module, Path(tmp))
        seed_dependencies(module)
        prior = install_empty_yfinance()
        try:
            module.main()
        finally:
            restore_yfinance(prior)
        gate = read_first(module.OUT_GATE)
        assert gate["provider_available"] == "FALSE"
        assert gate["certified_cache_source_available"] == "FALSE"
        assert gate["READY_FOR_V20_27_YAHOO_CACHE_CERTIFICATION_NEXT"] == "FALSE"
        assert gate["official_recommendation_created"] == "FALSE"
        assert gate["weight_mutated"] == "FALSE"
        assert gate["trade_action_created"] == "FALSE"


def test_runtime_empty_with_existing_cache_hands_off_with_provenance() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        configure_paths(module, Path(tmp))
        seed_dependencies(module)
        write_csv(module.TICKER_CACHE, [cache_row("AAA", "2026-06-12", "TICKER")], module.CACHE_FIELDS)
        write_csv(
            module.BENCHMARK_CACHE,
            [cache_row("SPY", "2026-06-12", "BENCHMARK"), cache_row("QQQ", "2026-06-12", "BENCHMARK")],
            module.CACHE_FIELDS,
        )
        prior = install_empty_yfinance()
        try:
            module.main()
        finally:
            restore_yfinance(prior)
        gate = read_first(module.OUT_GATE)
        diag = read_first(module.OUT_SOURCE_DIAGNOSTICS)
        assert gate["provider_available"] == "FALSE"
        assert gate["certified_cache_source_used"] == "TRUE"
        assert gate["READY_FOR_V20_27_YAHOO_CACHE_CERTIFICATION_NEXT"] == "TRUE"
        assert gate["latest_available_cache_date"] == "2026-06-12"
        assert gate["first_required_target_date"] == "2026-06-13"
        assert gate["forward_target_dates_available"] == "FALSE"
        assert diag["cache_source_file"].endswith("V20_26_YAHOO_TICKER_PRICE_CACHE.csv")
        assert gate["ACTIVE_OUTCOME_INPUT_CREATED"] == "FALSE"
        assert gate["ACTIVE_BENCHMARK_INPUT_CREATED"] == "FALSE"


def main() -> int:
    tests = [
        test_runtime_empty_without_cache_blocks_handoff,
        test_runtime_empty_with_existing_cache_hands_off_with_provenance,
    ]
    for test in tests:
        test()
    print("PASS test_v20_26_yahoo_runtime_outcome_benchmark_source_adapter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
