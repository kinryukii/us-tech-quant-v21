from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().with_name("v20_28_outcome_benchmark_value_attachment_retry_from_certified_yahoo_inputs.py")


def load_module():
    spec = importlib.util.spec_from_file_location("v20_28_under_test", SCRIPT)
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


def first_row(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows
    return rows[0]


def configure(module, root: Path) -> None:
    module.ROOT = root
    module.CONSOLIDATION = root / "outputs" / "v20" / "consolidation"
    module.READ_CENTER = root / "outputs" / "v20" / "read_center"
    module.OPS = root / "outputs" / "v20" / "ops"
    module.INPUT_BASE = root / "inputs" / "v20" / "outcome_benchmark"
    module.IN_READ_FIRST = module.OPS / "V20_27_READ_FIRST.txt"
    module.IN_GATE = module.CONSOLIDATION / "V20_27_GATE_DECISION.csv"
    module.IN_REGISTER = module.CONSOLIDATION / "V20_27_CERTIFIED_ACTIVE_INPUT_REGISTER.csv"
    module.IN_ACTIVE_AUDIT = module.CONSOLIDATION / "V20_27_ACTIVE_INPUT_FILE_CREATION_AUDIT.csv"
    module.IN_NEXT = module.CONSOLIDATION / "V20_27_NEXT_VALUE_ATTACHMENT_REQUIREMENTS.csv"
    module.IN_BLOCKERS = module.CONSOLIDATION / "V20_27_BLOCKER_REGISTER.csv"
    module.IN_CANDIDATES = module.CONSOLIDATION / "V20_17_BACKTEST_INPUT_CANDIDATE_DATASET.csv"
    module.OUTCOME_INPUT = module.INPUT_BASE / "V20_OUTCOME_SOURCE_INPUT.csv"
    module.BENCHMARK_INPUT = module.INPUT_BASE / "V20_BENCHMARK_SOURCE_INPUT.csv"
    module.REQUIRED_INPUTS = [
        module.IN_READ_FIRST, module.IN_GATE, module.IN_REGISTER, module.IN_ACTIVE_AUDIT,
        module.IN_NEXT, module.IN_BLOCKERS, module.OUTCOME_INPUT, module.BENCHMARK_INPUT,
        module.IN_CANDIDATES,
    ]
    for name in [
        "OUT_DEP", "OUT_SELECT", "OUT_DISCOVERY", "OUT_OUTCOME_KEY", "OUT_BENCH_KEY",
        "OUT_OUTCOME_ATTACH", "OUT_BENCH_ATTACH", "OUT_ATTACHED", "OUT_COVERAGE",
        "OUT_BENCH_COVERAGE", "OUT_WINDOW_COVERAGE", "OUT_PIT", "OUT_DUP",
        "OUT_BLOCKERS", "OUT_NEXT_REQ", "OUT_GATE", "OUT_VALIDATION",
    ]:
        setattr(module, name, module.CONSOLIDATION / getattr(module, name).name)
    module.REPORT = module.READ_CENTER / module.REPORT.name
    module.CURRENT_REPORT = module.READ_CENTER / module.CURRENT_REPORT.name
    module.READ_FIRST = module.OPS / module.READ_FIRST.name


def seed_common(module, gate_ready: bool) -> None:
    module.OPS.mkdir(parents=True, exist_ok=True)
    module.CONSOLIDATION.mkdir(parents=True, exist_ok=True)
    module.IN_READ_FIRST.write_text(
        "\n".join([
            "CERTIFICATION_AND_ACTIVE_INPUT_STAGING_ONLY: TRUE",
            "YAHOO_RUNTIME_REFRESH_EXECUTED: FALSE",
            f"ACTIVE_OUTCOME_INPUT_CREATED: {'TRUE' if gate_ready else 'FALSE'}",
            f"ACTIVE_BENCHMARK_INPUT_CREATED: {'TRUE' if gate_ready else 'FALSE'}",
            "BACKTEST_EXECUTED: FALSE",
        ]),
        encoding="utf-8",
    )
    write_csv(
        module.IN_GATE,
        [{
            "STATUS": "PASS_V20_27_YAHOO_CACHE_CERTIFICATION_AND_ACTIVE_INPUT_STAGING" if gate_ready else "BLOCKED_V20_27_YAHOO_CACHE_CERTIFICATION_AND_ACTIVE_INPUT_STAGING",
            "YAHOO_CACHE_CERTIFICATION_EXECUTED": "TRUE",
            "YAHOO_TICKER_CACHE_CERTIFIED": "TRUE",
            "YAHOO_BENCHMARK_CACHE_CERTIFIED": "TRUE",
            "OUTCOME_STAGED_CANDIDATE_CERTIFIED": "TRUE" if gate_ready else "FALSE",
            "BENCHMARK_STAGED_CANDIDATE_CERTIFIED": "TRUE" if gate_ready else "FALSE",
            "ACTIVE_OUTCOME_INPUT_CREATED": "TRUE" if gate_ready else "FALSE",
            "ACTIVE_BENCHMARK_INPUT_CREATED": "TRUE" if gate_ready else "FALSE",
            "CERTIFICATION_BLOCKER_COUNT": "0" if gate_ready else "2",
            "READY_FOR_V20_28_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_NEXT": "TRUE" if gate_ready else "FALSE",
            "READY_FOR_BACKTEST_EXECUTION_NEXT": "FALSE",
            "READY_FOR_DYNAMIC_WEIGHTING_NEXT": "FALSE",
        }],
        ["STATUS", "YAHOO_CACHE_CERTIFICATION_EXECUTED", "YAHOO_TICKER_CACHE_CERTIFIED", "YAHOO_BENCHMARK_CACHE_CERTIFIED", "OUTCOME_STAGED_CANDIDATE_CERTIFIED", "BENCHMARK_STAGED_CANDIDATE_CERTIFIED", "ACTIVE_OUTCOME_INPUT_CREATED", "ACTIVE_BENCHMARK_INPUT_CREATED", "CERTIFICATION_BLOCKER_COUNT", "READY_FOR_V20_28_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_NEXT", "READY_FOR_BACKTEST_EXECUTION_NEXT", "READY_FOR_DYNAMIC_WEIGHTING_NEXT"],
    )
    write_csv(module.IN_REGISTER, [{"input_type": "outcome"}, {"input_type": "benchmark"}], ["input_type"])
    write_csv(module.IN_ACTIVE_AUDIT, [{"input_type": "outcome"}, {"input_type": "benchmark"}], ["input_type"])
    write_csv(module.IN_NEXT, [{"ready_for_value_attachment_retry": "TRUE" if gate_ready else "FALSE"}], ["ready_for_value_attachment_retry"])
    write_csv(module.IN_BLOCKERS, [] if gate_ready else [{"blocker_id": "B1"}], ["blocker_id"])
    write_csv(
        module.IN_CANDIDATES,
        [{"backtest_input_candidate_id": "C1", "ticker": "AAA", "effective_price_date": "2026-06-12", "effective_observation_date": "2026-06-12"}],
        ["backtest_input_candidate_id", "ticker", "effective_price_date", "effective_observation_date"],
    )


def seed_active_inputs(module) -> None:
    write_csv(
        module.OUTCOME_INPUT,
        [{
            "ticker": "AAA", "signal_date": "2026-06-12", "outcome_window": "forward_1d",
            "outcome_price_date": "2026-06-13", "outcome_close": "10", "adjusted_outcome_close": "10",
            "source_hash": "oh", "run_id": "RUN1", "active_runtime_flag": "TRUE",
            "historical_reference_flag": "FALSE", "availability_date": "2026-06-13",
            "created_at_utc": "2026-06-13T00:00:00+00:00", "notes": "test",
        }],
        ["ticker", "signal_date", "outcome_window", "outcome_price_date", "outcome_close", "adjusted_outcome_close", "source_hash", "run_id", "active_runtime_flag", "historical_reference_flag", "availability_date", "created_at_utc", "notes"],
    )
    rows = []
    for symbol in ["SPY", "QQQ"]:
        rows.append({
            "benchmark_symbol": symbol, "signal_date": "2026-06-12", "benchmark_window": "benchmark_forward_1d",
            "benchmark_price_date": "2026-06-13", "benchmark_close": "10", "adjusted_benchmark_close": "10",
            "source_hash": f"bh-{symbol}", "run_id": "RUN1", "active_runtime_flag": "TRUE",
            "historical_reference_flag": "FALSE", "availability_date": "2026-06-13",
            "created_at_utc": "2026-06-13T00:00:00+00:00", "notes": "test",
        })
    write_csv(
        module.BENCHMARK_INPUT,
        rows,
        ["benchmark_symbol", "signal_date", "benchmark_window", "benchmark_price_date", "benchmark_close", "adjusted_benchmark_close", "source_hash", "run_id", "active_runtime_flag", "historical_reference_flag", "availability_date", "created_at_utc", "notes"],
    )


def test_v20_28_blocks_without_v20_27_certified_active_inputs() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as td:
        configure(module, Path(td))
        seed_common(module, gate_ready=False)
        assert module.main() == 0
        gate = first_row(module.OUT_GATE)
        assert gate["STATUS"].startswith("BLOCKED_V20_28")
        assert gate["VALUE_ATTACHMENT_EXECUTED"] == "FALSE"
        assert gate["CANDIDATE_ROWS_REVIEWED"] == "0"


def test_v20_28_passes_with_certified_active_inputs() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as td:
        configure(module, Path(td))
        seed_common(module, gate_ready=True)
        seed_active_inputs(module)
        assert module.main() == 0
        gate = first_row(module.OUT_GATE)
        assert gate["STATUS"] == "PASS_V20_28_OUTCOME_BENCHMARK_VALUE_ATTACHMENT_RETRY_FROM_CERTIFIED_YAHOO_INPUTS"
        assert gate["READY_FOR_V20_29_FIRST_LIMITED_BACKTEST_READINESS_GATE_NEXT"] == "TRUE"
        assert gate["FORWARD_RETURNS_CREATED"] == "FALSE"
        assert gate["BACKTEST_EXECUTED"] == "FALSE"


if __name__ == "__main__":
    test_v20_28_blocks_without_v20_27_certified_active_inputs()
    test_v20_28_passes_with_certified_active_inputs()
    print("PASS test_v20_28_outcome_benchmark_value_attachment_retry_from_certified_yahoo_inputs")
