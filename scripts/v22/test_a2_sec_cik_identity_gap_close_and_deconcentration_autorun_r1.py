from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


SOURCE = Path(__file__).with_name("a2_sec_cik_identity_gap_close_and_deconcentration_autorun_r1.py")
SPEC = importlib.util.spec_from_file_location("a2_sec_cik_identity_gap_close_under_test", SOURCE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_identity_normalization_is_exact_deterministic_and_preserves_structure() -> None:
    assert MODULE.identity_name_key("AMERIPRISE FINL INC") == MODULE.identity_name_key("Ameriprise Financial, Inc.")
    assert MODULE.identity_name_key("DISNEY WALT CO") == MODULE.identity_name_key("The Walt Disney Company")
    assert MODULE.identity_name_key("O REILLY AUTOMOTIVE INC") == MODULE.identity_name_key("O'Reilly Automotive, Inc.")
    assert MODULE.identity_name_key("MARVELL TECHNOLOGY INC") != MODULE.identity_name_key("MARVELL TECHNOLOGY GROUP LTD")


def test_bare_cusip_is_recognized_without_prefix() -> None:
    assert MODULE.security_key("369604301") == "369604301"
    assert MODULE.security_key("CUSIP_369604301") == "369604301"
    assert MODULE.security_key("A2_TICKER_GE") is None


def test_initial_accounting_is_mutually_exclusive() -> None:
    top = pd.DataFrame({
        "signal_date": pd.to_datetime(["2023-01-03", "2023-01-04", "2023-01-03", "2023-01-04"]),
        "ticker": ["A", "A", "B", "B"],
    })
    bridge = pd.DataFrame({"ticker": ["A", "B"], "cik": pd.Series([1, pd.NA], dtype="Int64")})
    old_sec, old_dates = MODULE.EXPECTED_SECURITIES, MODULE.EXPECTED_SECURITY_DATES
    MODULE.EXPECTED_SECURITIES, MODULE.EXPECTED_SECURITY_DATES = 2, 4
    try:
        result = MODULE.initial_accounting(top, bridge)
    finally:
        MODULE.EXPECTED_SECURITIES, MODULE.EXPECTED_SECURITY_DATES = old_sec, old_dates
    assert result["fully_resolved_securities"] == 1
    assert result["partially_resolved_securities"] == 0
    assert result["zero_resolved_securities"] == 1
    assert result["resolved_security_dates"] + result["unresolved_security_dates"] == 4


def test_contract_contains_no_bulk_sec_download_path_and_seals_2026() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "stage_sec_data(" not in source
    assert 'prices.trade_date < pd.Timestamp("2026-01-01")' in source
    assert '"2026_outcome_used": False' in source
    assert "FUZZY" not in "|".join(MODULE.TOKEN_EXPANSIONS)
    assert "FINAL_ARTIFACT_BUDGET" in source
