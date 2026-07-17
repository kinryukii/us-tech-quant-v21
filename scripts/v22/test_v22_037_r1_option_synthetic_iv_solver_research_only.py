from __future__ import annotations

import ast
import csv
import importlib.util
import json
import subprocess
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_037_r1_option_synthetic_iv_solver_research_only.py")
WRAPPER_PATH = Path(__file__).with_name("run_v22_037_r1_option_synthetic_iv_solver_research_only.ps1")
SPEC = importlib.util.spec_from_file_location("v22_037_r1", MODULE_PATH)
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


def base_row(**updates):
    row = {
        "option_code": "C1",
        "underlying": "QQQ",
        "option_type": "CALL",
        "strike": 100,
        "expiry": "2026-08-07",
        "bid": 5.9,
        "ask": 6.1,
        "underlying_price": 100,
        "quote_datetime": "2026-07-08T10:00:00-04:00",
        "volume": 10,
    }
    row.update(updates)
    return row


def test_black_scholes_call_pricing_sanity():
    price = module.black_scholes_price("CALL", 100, 100, 30 / 365, 0.045, 0, 0.3)
    assert 3.0 < price < 5.0


def test_black_scholes_put_pricing_sanity():
    price = module.black_scholes_price("PUT", 100, 100, 30 / 365, 0.045, 0, 0.3)
    assert 2.5 < price < 4.5


def test_iv_solver_recovers_known_vol_for_call():
    t = 30 / 365
    price = module.black_scholes_price("CALL", 100, 100, t, 0.045, 0, 0.25)
    iv, status, _ = module.solve_iv("CALL", price, 100, 100, t, 0.045, 0, 5, 10)
    assert status == "SOLVED"
    assert abs(iv - 0.25) < 1e-4


def test_iv_solver_recovers_known_vol_for_put():
    t = 30 / 365
    price = module.black_scholes_price("PUT", 100, 100, t, 0.045, 0, 0.25)
    iv, status, _ = module.solve_iv("PUT", price, 100, 100, t, 0.045, 0, 5, 10)
    assert status == "SOLVED"
    assert abs(iv - 0.25) < 1e-4


def test_greeks_are_finite_and_directionally_correct():
    call = module.black_scholes_greeks("CALL", 100, 100, 30 / 365, 0.045, 0, 0.25)
    put = module.black_scholes_greeks("PUT", 100, 100, 30 / 365, 0.045, 0, 0.25)
    assert 0 < call["delta"] < 1
    assert -1 < put["delta"] < 0
    assert call["gamma"] > 0
    assert call["vega_per_vol_point"] > 0


def test_invalid_below_intrinsic_price_rejected():
    row = module.clean_row(base_row(strike=90, bid=1, ask=1.2), 0.045, 0, 5, 10)
    assert row["iv_status"] == "INVALID_BELOW_INTRINSIC_BOUND"


def test_expired_contract_rejected():
    row = module.clean_row(base_row(expiry="2026-07-01"), 0.045, 0, 5, 10)
    assert row["iv_status"] == "EXPIRED_OR_ZERO_T"


def test_missing_required_fields_rejected():
    raw = base_row()
    raw.pop("underlying_price")
    row = module.clean_row(raw, 0.045, 0, 5, 10)
    assert row["iv_status"] == "MISSING_REQUIRED_FIELDS"


def test_open_interest_not_fabricated_when_missing():
    row = module.clean_row(base_row(), 0.045, 0, 5, 10)
    assert row["open_interest_available"] is False
    assert row["open_interest_proxy_used"] is False
    assert row["open_interest_source"] == "UNAVAILABLE_FROM_CURRENT_MOOMOO_QUOTE_PAYLOAD"


def test_summary_safety_gates_are_false(tmp_path):
    inp = tmp_path / "input.csv"
    write_fixture(inp, [base_row()])
    summary = module.run(tmp_path, inp, execute=True)
    assert summary["candidate_generation_allowed"] is False
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False
    assert summary["research_only"] is True


def test_output_csv_and_json_files_created(tmp_path):
    inp = tmp_path / "input.csv"
    write_fixture(inp, [base_row()])
    module.run(tmp_path, inp, execute=True)
    out = tmp_path / module.OUT_REL
    assert (out / "option_synthetic_iv_greeks_clean.csv").exists()
    assert (out / "option_synthetic_iv_greeks_audit.csv").exists()
    assert (out / "v22_037_r1_summary.json").exists()
    assert (out / "V22.037_R1_option_synthetic_iv_greeks_report.txt").exists()
    payload = json.loads((out / "v22_037_r1_summary.json").read_text(encoding="utf-8"))
    for key in module.SUMMARY_KEYS:
        assert key in payload


def test_auto_discovery_finds_mock_latest_input_file(tmp_path):
    old = tmp_path / "outputs" / "v22" / "V22.032_R1_OPTION_QUOTE_ENRICHMENT_FROM_MOOMOO_READ_ONLY" / "old_quote_clean.csv"
    new = tmp_path / "outputs" / "v22" / "V22.032_R1_OPTION_QUOTE_ENRICHMENT_FROM_MOOMOO_READ_ONLY" / "v22_option_quote_enrichment_clean.csv"
    write_fixture(old, [base_row(option_code="OLD")])
    write_fixture(new, [base_row(option_code="NEW")])
    assert module.discover_input(tmp_path) == new


def test_powershell_wrapper_can_call_python_script(tmp_path):
    assert WRAPPER_PATH.exists()
    repo = MODULE_PATH.parents[2]
    proc = subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER_PATH), "-RepoRoot", str(repo)], text=True, capture_output=True, timeout=30)
    assert proc.returncode == 0
    assert "PLAN_ONLY" in proc.stdout


def test_module_never_imports_or_uses_trade_context():
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
