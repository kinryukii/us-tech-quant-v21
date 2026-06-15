from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().with_name("v20_27_yahoo_cache_certification_and_active_input_staging.py")


def load_module():
    spec = importlib.util.spec_from_file_location("v20_27_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def read_first_row(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows
    return rows[0]


def configure_paths(module, root: Path) -> None:
    module.ROOT = root
    module.CONSOLIDATION = root / "outputs" / "v20" / "consolidation"
    module.READ_CENTER = root / "outputs" / "v20" / "read_center"
    module.OPS = root / "outputs" / "v20" / "ops"
    module.INPUT_BASE = root / "inputs" / "v20" / "outcome_benchmark"

    module.IN_READ_FIRST = module.OPS / "V20_26_READ_FIRST.txt"
    module.IN_GATE = module.CONSOLIDATION / "V20_26_GATE_DECISION.csv"
    module.IN_CACHE_REGISTER = module.CONSOLIDATION / "V20_26_YAHOO_CACHE_FILE_REGISTER.csv"
    module.IN_HASH_LEDGER = module.CONSOLIDATION / "V20_26_YAHOO_CACHE_HASH_LEDGER.csv"
    module.IN_RUN_LEDGER = module.CONSOLIDATION / "V20_26_RUN_ID_LEDGER.csv"
    module.IN_SCHEMA_AUDIT = module.CONSOLIDATION / "V20_26_CACHE_SCHEMA_AUDIT.csv"
    module.IN_DATE_COVERAGE = module.CONSOLIDATION / "V20_26_PRICE_DATE_COVERAGE_AUDIT.csv"
    module.IN_BENCH_COVERAGE = module.CONSOLIDATION / "V20_26_BENCHMARK_SYMBOL_COVERAGE_AUDIT.csv"
    module.IN_STAGED_REGISTER = module.CONSOLIDATION / "V20_26_STAGED_INPUT_CANDIDATE_REGISTER.csv"
    module.IN_NEXT_REQ = module.CONSOLIDATION / "V20_26_NEXT_CERTIFICATION_REQUIREMENTS.csv"
    module.IN_CANDIDATES = module.CONSOLIDATION / "V20_17_BACKTEST_INPUT_CANDIDATE_DATASET.csv"
    module.REQUIRED_INPUTS = [
        module.IN_READ_FIRST, module.IN_GATE, module.IN_CACHE_REGISTER, module.IN_HASH_LEDGER,
        module.IN_RUN_LEDGER, module.IN_SCHEMA_AUDIT, module.IN_DATE_COVERAGE,
        module.IN_BENCH_COVERAGE, module.IN_STAGED_REGISTER, module.IN_NEXT_REQ,
    ]

    module.TICKER_CACHE = module.INPUT_BASE / "yahoo_cache" / "v20_26" / "V20_26_YAHOO_TICKER_PRICE_CACHE.csv"
    module.BENCHMARK_CACHE = module.INPUT_BASE / "yahoo_cache" / "v20_26" / "V20_26_YAHOO_BENCHMARK_PRICE_CACHE.csv"
    module.STAGED_OUTCOME = module.INPUT_BASE / "staging" / "v20_26" / "V20_26_STAGED_YAHOO_OUTCOME_SOURCE_INPUT_CANDIDATE.csv"
    module.STAGED_BENCHMARK = module.INPUT_BASE / "staging" / "v20_26" / "V20_26_STAGED_YAHOO_BENCHMARK_SOURCE_INPUT_CANDIDATE.csv"
    module.ACTIVE_OUTCOME = module.INPUT_BASE / "V20_OUTCOME_SOURCE_INPUT.csv"
    module.ACTIVE_BENCHMARK = module.INPUT_BASE / "V20_BENCHMARK_SOURCE_INPUT.csv"

    for name in [
        "OUT_DEP", "OUT_DISCOVERY", "OUT_SCHEMA", "OUT_HASH", "OUT_RUN", "OUT_TICKER_QUALITY",
        "OUT_BENCH_QUALITY", "OUT_OUTCOME_CERT", "OUT_BENCH_CERT", "OUT_BENCH_SYMBOL",
        "OUT_WINDOW", "OUT_PIT", "OUT_DUP", "OUT_ACTIVE_AUDIT", "OUT_REGISTER",
        "OUT_BLOCKERS", "OUT_GAP", "OUT_NEXT", "OUT_GATE", "OUT_VALIDATION",
    ]:
        filename = getattr(module, name).name
        setattr(module, name, module.CONSOLIDATION / filename)
    module.REPORT = module.READ_CENTER / module.REPORT.name
    module.CURRENT_REPORT = module.READ_CENTER / module.CURRENT_REPORT.name
    module.READ_FIRST = module.OPS / module.READ_FIRST.name


def seed_dependencies(module) -> None:
    module.OPS.mkdir(parents=True, exist_ok=True)
    module.CONSOLIDATION.mkdir(parents=True, exist_ok=True)
    module.IN_READ_FIRST.write_text(
        "\n".join([
            "SOURCE_ADAPTER_ONLY: TRUE",
            "YAHOO_RUNTIME_REFRESH_EXECUTED: TRUE",
            "LOCAL_CACHE_CREATED: TRUE",
            "CERTIFICATION_EXECUTED: FALSE",
            "ACTIVE_OUTCOME_INPUT_CREATED: FALSE",
            "ACTIVE_BENCHMARK_INPUT_CREATED: FALSE",
            "BACKTEST_EXECUTED: FALSE",
        ]),
        encoding="utf-8",
    )
    write_csv(
        module.IN_GATE,
        [{
            "STATUS": "PASS_V20_26_YAHOO_RUNTIME_OUTCOME_BENCHMARK_SOURCE_ADAPTER",
            "ARCHITECTURE_CORRECTION_APPLIED": "TRUE",
            "MANUAL_STAGING_RECLASSIFIED_AS_FALLBACK": "TRUE",
            "YAHOO_RUNTIME_REFRESH_ATTEMPTED": "TRUE",
            "LOCAL_YAHOO_CACHE_CREATED": "TRUE",
            "READY_FOR_V20_27_YAHOO_CACHE_CERTIFICATION_NEXT": "TRUE",
            "ACTIVE_OUTCOME_INPUT_CREATED": "FALSE",
            "ACTIVE_BENCHMARK_INPUT_CREATED": "FALSE",
            "READY_FOR_VALUE_ATTACHMENT_NEXT": "FALSE",
            "READY_FOR_BACKTEST_EXECUTION_NEXT": "FALSE",
        }],
        ["STATUS", "ARCHITECTURE_CORRECTION_APPLIED", "MANUAL_STAGING_RECLASSIFIED_AS_FALLBACK", "YAHOO_RUNTIME_REFRESH_ATTEMPTED", "LOCAL_YAHOO_CACHE_CREATED", "READY_FOR_V20_27_YAHOO_CACHE_CERTIFICATION_NEXT", "ACTIVE_OUTCOME_INPUT_CREATED", "ACTIVE_BENCHMARK_INPUT_CREATED", "READY_FOR_VALUE_ATTACHMENT_NEXT", "READY_FOR_BACKTEST_EXECUTION_NEXT"],
    )
    for path in [
        module.IN_CACHE_REGISTER, module.IN_RUN_LEDGER, module.IN_SCHEMA_AUDIT,
        module.IN_DATE_COVERAGE, module.IN_BENCH_COVERAGE, module.IN_STAGED_REGISTER,
        module.IN_NEXT_REQ,
    ]:
        write_csv(path, [{"present": "TRUE"}], ["present"])
    write_csv(
        module.IN_CANDIDATES,
        [{"ticker": "AAA", "effective_price_date": "2026-06-12", "effective_observation_date": "2026-06-12"}],
        ["ticker", "effective_price_date", "effective_observation_date"],
    )


def cache_row(module, symbol: str, date: str, role: str) -> dict[str, str]:
    source_hash = f"hash-{role}-{symbol}-{date}"
    return {
        "symbol": symbol,
        "price_date": date,
        "open": "10",
        "high": "11",
        "low": "9",
        "close": "10.5",
        "adjusted_close": "10.5",
        "volume": "1000",
        "currency": "USD",
        "data_vendor_or_source_system": "Yahoo/yfinance",
        "provider_query_start_date": "2026-06-12",
        "provider_query_end_date": "2026-06-14",
        "provider_download_timestamp_utc": "2026-06-13T00:00:00+00:00",
        "source_artifact_id": f"V20_26_YAHOO_{role.upper()}::{symbol}",
        "source_hash": source_hash,
        "run_id": "RUN1",
        "active_runtime_flag": "TRUE",
        "historical_reference_flag": "FALSE",
        "created_at_utc": "2026-06-13T00:00:00+00:00",
        "notes": "test",
    }


def seed_caches(module) -> None:
    ticker_rows = [cache_row(module, "AAA", "2026-06-13", "ticker")]
    bench_rows = [cache_row(module, "SPY", "2026-06-13", "benchmark"), cache_row(module, "QQQ", "2026-06-13", "benchmark")]
    write_csv(module.TICKER_CACHE, ticker_rows, module.CACHE_FIELDS)
    write_csv(module.BENCHMARK_CACHE, bench_rows, module.CACHE_FIELDS)
    write_csv(
        module.IN_HASH_LEDGER,
        [
            {"cache_path": module.rel(module.TICKER_CACHE), "file_hash_sha256": module.sha_file(module.TICKER_CACHE)},
            {"cache_path": module.rel(module.BENCHMARK_CACHE), "file_hash_sha256": module.sha_file(module.BENCHMARK_CACHE)},
        ],
        ["cache_path", "file_hash_sha256"],
    )


def seed_staged(module, include_outcome: bool = True, include_benchmark: bool = True, pit_safe: bool = True) -> None:
    if include_outcome:
        signal = "2026-06-12" if pit_safe else "2026-06-14"
        write_csv(
            module.STAGED_OUTCOME,
            [{
                "ticker": "AAA", "signal_date": signal, "outcome_window": "forward_1d",
                "outcome_price_date": "2026-06-13", "outcome_close": "10.5", "adjusted_outcome_close": "10.5",
                "currency": "USD", "source_artifact_id": "V20_26_YAHOO_TICKER::AAA",
                "source_hash": "hash-ticker-AAA-2026-06-13", "run_id": "RUN1",
                "active_runtime_flag": "TRUE", "historical_reference_flag": "FALSE",
                "availability_date": "2026-06-13", "created_at_utc": "2026-06-13T00:00:00+00:00",
                "data_vendor_or_source_system": "Yahoo/yfinance", "notes": "test",
            }],
            module.OUTCOME_FIELDS,
        )
    if include_benchmark:
        signal = "2026-06-12" if pit_safe else "2026-06-14"
        rows = []
        for symbol in ["SPY", "QQQ"]:
            rows.append({
                "benchmark_symbol": symbol, "signal_date": signal, "benchmark_window": "benchmark_forward_1d",
                "benchmark_price_date": "2026-06-13", "benchmark_close": "10.5", "adjusted_benchmark_close": "10.5",
                "currency": "USD", "source_artifact_id": f"V20_26_YAHOO_BENCHMARK::{symbol}",
                "source_hash": f"hash-benchmark-{symbol}-2026-06-13", "run_id": "RUN1",
                "active_runtime_flag": "TRUE", "historical_reference_flag": "FALSE",
                "availability_date": "2026-06-13", "created_at_utc": "2026-06-13T00:00:00+00:00",
                "data_vendor_or_source_system": "Yahoo/yfinance", "notes": "test",
            })
        write_csv(module.STAGED_BENCHMARK, rows, module.BENCHMARK_FIELDS)


def run_case(include_outcome: bool, include_benchmark: bool, pit_safe: bool = True):
    module = load_module()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        configure_paths(module, root)
        seed_dependencies(module)
        seed_caches(module)
        seed_staged(module, include_outcome=include_outcome, include_benchmark=include_benchmark, pit_safe=pit_safe)
        assert module.main() == 0
        return read_first_row(module.OUT_GATE), read_first_row(module.OUT_VALIDATION), module.ACTIVE_OUTCOME.exists(), module.ACTIVE_BENCHMARK.exists()


def test_missing_outcome_blocks_v20_27() -> None:
    gate, validation, active_outcome, active_benchmark = run_case(include_outcome=False, include_benchmark=True)
    assert gate["READY_FOR_V20_28_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_NEXT"] == "FALSE"
    assert gate["OUTCOME_STAGED_CANDIDATE_CERTIFIED"] == "FALSE"
    assert validation["STATUS"].startswith("BLOCKED_V20_27")
    assert not active_outcome
    assert active_benchmark


def test_missing_benchmark_blocks_v20_27() -> None:
    gate, validation, active_outcome, active_benchmark = run_case(include_outcome=True, include_benchmark=False)
    assert gate["READY_FOR_V20_28_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_NEXT"] == "FALSE"
    assert gate["BENCHMARK_STAGED_CANDIDATE_CERTIFIED"] == "FALSE"
    assert validation["STATUS"].startswith("BLOCKED_V20_27")
    assert active_outcome
    assert not active_benchmark


def test_pit_unsafe_rows_block_v20_27() -> None:
    gate, validation, active_outcome, active_benchmark = run_case(include_outcome=True, include_benchmark=True, pit_safe=False)
    assert gate["READY_FOR_V20_28_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_NEXT"] == "FALSE"
    assert validation["STATUS"].startswith("BLOCKED_V20_27")
    assert not active_outcome
    assert not active_benchmark


def test_all_certified_inputs_pass_v20_27() -> None:
    gate, validation, active_outcome, active_benchmark = run_case(include_outcome=True, include_benchmark=True)
    assert gate["READY_FOR_V20_28_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_NEXT"] == "TRUE"
    assert gate["CERTIFICATION_BLOCKER_COUNT"] == "0"
    assert validation["STATUS"] == "PASS_V20_27_YAHOO_CACHE_CERTIFICATION_AND_ACTIVE_INPUT_STAGING"
    assert active_outcome
    assert active_benchmark


def test_boolean_parsing_is_deterministic() -> None:
    module = load_module()
    rows = [{"flag": "true"}, {"flag": "TRUE"}, {"flag": " True "}]
    assert module.true_all(rows, "flag")
    rows = [{"flag": "false"}, {"flag": "FALSE"}, {"flag": " False "}]
    assert module.false_all(rows, "flag")


if __name__ == "__main__":
    test_missing_outcome_blocks_v20_27()
    test_missing_benchmark_blocks_v20_27()
    test_pit_unsafe_rows_block_v20_27()
    test_all_certified_inputs_pass_v20_27()
    test_boolean_parsing_is_deterministic()
    print("PASS test_v20_27_yahoo_cache_certification_and_active_input_staging")
