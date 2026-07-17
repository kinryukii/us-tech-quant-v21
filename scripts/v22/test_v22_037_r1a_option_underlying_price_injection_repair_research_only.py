from __future__ import annotations

import ast
import csv
import importlib.util
import json
import subprocess
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_037_r1a_option_underlying_price_injection_repair_research_only.py")
WRAPPER_PATH = Path(__file__).with_name("run_v22_037_r1a_option_underlying_price_injection_repair_research_only.ps1")
SPEC = importlib.util.spec_from_file_location("v22_037_r1a", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def write_fixture(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({k for row in rows for k in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def option_row(**updates):
    row = {
        "option_code": "US.QQQ260807C00100000",
        "underlying": "QQQ",
        "option_type": "CALL",
        "strike": "100",
        "expiry": "2026-08-07",
        "bid": "5.00",
        "ask": "5.20",
        "quote_datetime": "2026-07-08T10:00:00-04:00",
    }
    row.update(updates)
    return row


def test_existing_valid_underlying_price_is_preserved(tmp_path):
    inp = tmp_path / "input.csv"
    write_fixture(inp, [option_row(underlying_price="101.5")])
    summary = module.run(tmp_path, inp, execute=True)
    out = rows(tmp_path / module.OUT_REL / "option_quote_enrichment_clean_with_underlying_price.csv")
    assert summary["underlying_price_before_valid_count"] == 1
    assert out[0]["underlying_price_after"] == "101.5"
    assert out[0]["underlying_price_status"] == "PRESERVED_EXISTING"
    assert out[0]["underlying_price_injected"] == "False"


def test_alternative_option_row_spot_column_is_copied(tmp_path):
    inp = tmp_path / "input.csv"
    write_fixture(inp, [option_row(spot_price="102.25")])
    summary = module.run(tmp_path, inp, execute=True)
    out = rows(tmp_path / module.OUT_REL / "option_quote_enrichment_clean_with_underlying_price.csv")
    assert summary["injected_underlying_price_count"] == 1
    assert out[0]["underlying_price_after"] == "102.25"
    assert out[0]["underlying_price_source"] == "OPTION_ROW_COLUMN:spot_price"


def test_snapshot_join_by_underlying_symbol_works(tmp_path):
    inp = tmp_path / "input.csv"
    snap = tmp_path / "snapshot.csv"
    write_fixture(inp, [option_row(underlying="QQQ"), option_row(option_code="SPY1", underlying="SPY")])
    write_fixture(snap, [{"symbol": "QQQ", "price": "103"}, {"symbol": "SPY", "price": "601"}])
    summary = module.run(tmp_path, inp, snap, execute=True)
    out = rows(tmp_path / module.OUT_REL / "option_quote_enrichment_clean_with_underlying_price.csv")
    by_sym = {r["underlying"]: r for r in out}
    assert summary["injected_underlying_price_count"] == 2
    assert by_sym["QQQ"]["underlying_price_after"] == "103.0"
    assert by_sym["SPY"]["underlying_price_after"] == "601.0"
    assert by_sym["QQQ"]["underlying_price_source"] == "SNAPSHOT_JOIN:price"


def test_single_underlying_safe_broadcast_injection_works(tmp_path):
    inp = tmp_path / "input.csv"
    snap = tmp_path / "snapshot.csv"
    write_fixture(inp, [option_row(underlying="QQQ"), option_row(option_code="Q2", underlying="QQQ")])
    write_fixture(snap, [{"symbol": "SOXX", "price": "244.5"}])
    summary = module.run(tmp_path, inp, snap, execute=True)
    out = rows(tmp_path / module.OUT_REL / "option_quote_enrichment_clean_with_underlying_price.csv")
    assert summary["injected_underlying_price_count"] == 2
    assert {r["underlying_price_source"] for r in out} == {"SINGLE_UNDERLYING_BROADCAST_FROM_SNAPSHOT"}


def test_multiple_underlying_ambiguous_broadcast_is_rejected(tmp_path):
    inp = tmp_path / "input.csv"
    snap = tmp_path / "snapshot.csv"
    write_fixture(inp, [option_row(underlying="QQQ"), option_row(option_code="SPY1", underlying="SPY")])
    write_fixture(snap, [{"symbol": "SOXX", "price": "244.5"}])
    summary = module.run(tmp_path, inp, snap, execute=True)
    out = rows(tmp_path / module.OUT_REL / "option_quote_enrichment_clean_with_underlying_price.csv")
    assert summary["final_status"] == module.FAIL_NO_SOURCE
    assert all(r["underlying_price_status"] == "MISSING_OR_AMBIGUOUS" for r in out)


def test_zero_negative_and_non_numeric_prices_are_rejected(tmp_path):
    inp = tmp_path / "input.csv"
    snap = tmp_path / "snapshot.csv"
    write_fixture(inp, [option_row(spot_price="0"), option_row(option_code="Q2", spot_price="-1"), option_row(option_code="Q3", spot_price="bad")])
    write_fixture(snap, [{"symbol": "QQQ", "price": "0"}])
    summary = module.run(tmp_path, inp, snap, execute=True)
    assert summary["final_status"] == module.FAIL_NO_SOURCE
    assert summary["underlying_price_after_valid_count"] == 0


def test_missing_source_produces_fail_status(tmp_path):
    inp = tmp_path / "input.csv"
    write_fixture(inp, [option_row()])
    summary = module.run(tmp_path, inp, execute=True)
    assert summary["final_status"] == module.FAIL_NO_SOURCE
    assert summary["final_decision"] == module.NO_SOURCE_DECISION


def test_output_csv_audit_summary_and_report_are_created(tmp_path):
    inp = tmp_path / "input.csv"
    write_fixture(inp, [option_row(spot="100")])
    summary = module.run(tmp_path, inp, execute=True)
    out = tmp_path / module.OUT_REL
    assert (out / "option_quote_enrichment_clean_with_underlying_price.csv").exists()
    assert (out / "underlying_price_injection_audit.csv").exists()
    assert (out / "v22_037_r1a_summary.json").exists()
    assert (out / "V22.037_R1A_underlying_price_injection_repair_report.txt").exists()
    payload = json.loads((out / "v22_037_r1a_summary.json").read_text(encoding="utf-8"))
    assert payload["final_status"] == summary["final_status"]


def test_safety_gates_are_always_false(tmp_path):
    inp = tmp_path / "input.csv"
    write_fixture(inp, [option_row(underlying_price="100")])
    summary = module.run(tmp_path, inp, execute=True)
    assert summary["candidate_generation_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["research_only"] is True


def test_no_trade_context_or_broker_api_is_imported():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert "OpenSecTradeContext" not in text
    tree = ast.parse(text)
    forbidden = {"unlock_trade", "place_order", "modify_order", "cancel_order"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                assert func.attr not in forbidden
            if isinstance(func, ast.Name):
                assert func.id not in forbidden


def test_auto_discovery_can_find_mock_latest_v22_032_r1_clean_input(tmp_path):
    path = tmp_path / module.DEFAULT_INPUT_REL
    write_fixture(path, [option_row()])
    assert module.discover_input(tmp_path) == path


def test_snapshot_staleness_diagnostics_are_computed(tmp_path):
    inp = tmp_path / "input.csv"
    snap = tmp_path / "snapshot.csv"
    write_fixture(inp, [option_row(quote_datetime="2026-07-08T10:00:00-04:00")])
    write_fixture(snap, [{"symbol": "QQQ", "price": "100", "quote_datetime": "2026-07-08T09:00:00-04:00"}])
    module.run(tmp_path, inp, snap, execute=True)
    out = rows(tmp_path / module.OUT_REL / "option_quote_enrichment_clean_with_underlying_price.csv")
    assert out[0]["underlying_snapshot_age_minutes"] == "60.0"
    assert out[0]["underlying_snapshot_stale_flag"] == "True"


def test_option_like_snapshot_does_not_use_option_last_price_as_underlying(tmp_path):
    inp = tmp_path / "input.csv"
    snap = tmp_path / "option_snapshot.csv"
    write_fixture(inp, [option_row()])
    write_fixture(snap, [{"option_code": "US.QQQ260807C00100000", "underlying": "QQQ", "strike": "100", "last_price": "5.25"}])
    summary = module.run(tmp_path, inp, snap, execute=True)
    out = rows(tmp_path / module.OUT_REL / "option_quote_enrichment_clean_with_underlying_price.csv")
    assert summary["final_status"] == module.FAIL_NO_SOURCE
    assert out[0]["underlying_price_after"] == ""


def test_powershell_wrapper_can_call_python_script(tmp_path):
    assert WRAPPER_PATH.exists()
    repo = MODULE_PATH.parents[2]
    proc = subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER_PATH), "-RepoRoot", str(repo)], text=True, capture_output=True, timeout=30)
    assert proc.returncode == 0
    assert "PLAN_ONLY" in proc.stdout
