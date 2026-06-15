from __future__ import annotations

import csv
import importlib.util
import shutil
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "v16" / "repair_v16_second_stage_universe.py"
WRAPPER = ROOT / "scripts" / "v16" / "run_v16_second_stage_universe_bootstrap_repair.ps1"
TARGET = ROOT / "configs" / "v16" / "universe" / "us_full_second_stage_generated.yaml"
STATUS = ROOT / "outputs" / "v16" / "universe" / "V16_SECOND_STAGE_UNIVERSE_REPAIR_STATUS.csv"
AUDIT = ROOT / "outputs" / "v16" / "universe" / "V16_SECOND_STAGE_UNIVERSE_REPAIR_SOURCE_AUDIT.csv"


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_module():
    spec = importlib.util.spec_from_file_location("v16_repair", SCRIPT)
    assert_true(spec is not None and spec.loader is not None, "Unable to load V16 repair module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def read_tickers(path: Path) -> list[str]:
    tickers: list[str] = []
    in_tickers = False
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line == "tickers:":
            in_tickers = True
            continue
        if in_tickers and line.startswith("- "):
            tickers.append(line[2:].strip())
    return tickers


def configure_module_for_root(module, root: Path) -> None:
    module.ROOT = root
    module.OUT_YAML = root / "configs" / "v16" / "universe" / "us_full_second_stage_generated.yaml"
    module.OUT_SCREENED_YAML = root / "configs" / "v16" / "universe" / "us_full_screened_generated.yaml"
    module.OUT_STATUS = root / "outputs" / "v16" / "universe" / "V16_SECOND_STAGE_UNIVERSE_REPAIR_STATUS.csv"
    module.OUT_AUDIT = root / "outputs" / "v16" / "universe" / "V16_SECOND_STAGE_UNIVERSE_REPAIR_SOURCE_AUDIT.csv"
    module.OUT_TOP = root / "outputs" / "v16" / "universe" / "V16_SECOND_STAGE_TOP_CANDIDATES.csv"
    module.OUT_READ_FIRST = root / "outputs" / "v16" / "read_center" / "V16_SECOND_STAGE_UNIVERSE_REPAIR_READ_FIRST.txt"
    module.SOURCE_CANDIDATES = [
        ("TEST_AUTHORITATIVE_SOURCE", root / "state" / "v18" / "universe" / "V18_UNIVERSE_ROLLING_STATE.csv", "structured_csv"),
    ]


def write_source(path: Path, tickers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker"], lineterminator="\n")
        writer.writeheader()
        for ticker in tickers:
            writer.writerow({"ticker": ticker})


def test_missing_upstream_blocks_without_fabricating_output() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        configure_module_for_root(module, tmp_root)
        rc = module.main()
        status = read_csv(module.OUT_STATUS)[0]
        assert_true(rc == 1, "Missing upstream should return non-zero")
        assert_true(status["STATUS"] == module.BLOCKED_STATUS, "Missing upstream should be BLOCKED")
        assert_true(status["ticker_count"] == "0", "Missing upstream should not fabricate tickers")
        assert_true(not module.OUT_YAML.exists(), "Missing upstream must not create target YAML")


def test_valid_upstream_generates_yaml_with_provenance_and_deduplication() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        configure_module_for_root(module, tmp_root)
        source = tmp_root / "state" / "v18" / "universe" / "V18_UNIVERSE_ROLLING_STATE.csv"
        tickers = [f"T{i:02d}" for i in range(1, 25)] + ["T01", "T02"]
        write_source(source, tickers)
        rc = module.main()
        status = read_csv(module.OUT_STATUS)[0]
        audit = read_csv(module.OUT_AUDIT)
        yaml_tickers = read_tickers(module.OUT_YAML)
        assert_true(rc == 0, "Valid upstream should pass")
        assert_true(status["STATUS"] == module.PASS_STATUS, "Valid upstream should generate PASS")
        assert_true(module.OUT_YAML.exists(), "Generated YAML missing")
        assert_true(yaml_tickers and len(yaml_tickers) == 24, "YAML ticker count should reflect deterministic de-duplication")
        assert_true(status["ticker_count"] == "24", "Status ticker_count mismatch")
        assert_true(status["duplicate_count"] == "2", "Duplicate count should be recorded")
        assert_true(status["selected_source_path"].endswith("state/v18/universe/V18_UNIVERSE_ROLLING_STATE.csv"), "Provenance source path missing")
        assert_true(audit[0]["selected"] == "TRUE", "Selected source audit missing")
        assert_true(audit[0]["duplicate_count"] == "2", "Audit duplicate count mismatch")
        assert_true(status["official_recommendation_created"] == "FALSE", "No official recommendation allowed")
        assert_true(status["trade_action_created"] == "FALSE", "No trade action allowed")
        assert_true(status["portfolio_weight_mutated"] == "FALSE", "No weight mutation allowed")


def test_workspace_outputs_exist_and_match_schema() -> None:
    assert_true(SCRIPT.exists(), "V16 repair script missing")
    assert_true(WRAPPER.exists(), "V16 bootstrap wrapper missing")
    assert_true(TARGET.exists(), "Workspace generated YAML missing")
    assert_true(STATUS.exists(), "Workspace V16 status missing")
    assert_true(AUDIT.exists(), "Workspace V16 audit missing")
    tickers = read_tickers(TARGET)
    status = read_csv(STATUS)[0]
    assert_true(tickers, "Workspace YAML must contain tickers")
    assert_true(status["STATUS"] == "PASS_V16_SECOND_STAGE_UNIVERSE_REPAIR", "Workspace V16 status must pass")
    assert_true(int(status["ticker_count"]) > 0, "Workspace ticker_count must be positive")
    assert_true("selected_source_path" in status and status["selected_source_path"], "Status provenance missing")
    assert_true(status["official_recommendation_created"] == "FALSE", "No official recommendation allowed")
    assert_true(status["portfolio_weight_mutated"] == "FALSE", "No portfolio weight mutation allowed")
    assert_true(status["trade_action_created"] == "FALSE", "No trade action allowed")


def cleanup_pycache() -> None:
    pycache = ROOT / "scripts" / "v16" / "__pycache__"
    if pycache.exists():
        shutil.rmtree(pycache)


def main() -> int:
    tests = [
        test_missing_upstream_blocks_without_fabricating_output,
        test_valid_upstream_generates_yaml_with_provenance_and_deduplication,
        test_workspace_outputs_exist_and_match_schema,
        cleanup_pycache,
    ]
    failures: list[str] = []
    for test in tests:
        try:
            test()
        except Exception as exc:
            failures.append(f"{test.__name__}: {exc}")
    if failures:
        for failure in failures:
            print(f"FAIL_DETAIL: {failure}")
        print("FAIL_V16_SECOND_STAGE_UNIVERSE_BOOTSTRAP_REPAIR_TESTS")
        return 1
    print("PASS_V16_SECOND_STAGE_UNIVERSE_BOOTSTRAP_REPAIR_TESTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
