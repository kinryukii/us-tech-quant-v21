from __future__ import annotations

import ast
import inspect
from pathlib import Path

import numpy as np
import pandas as pd

import scripts.v22.fast_a2_r0f_corporate_action_and_nav_forensic_audit as audit


def test_two_for_one_split_adjusted_price_and_unchanged_synthetic_shares_has_no_false_pnl():
    result = audit.audit_split_relationship(
        split_ratio=2.0, pre_raw_price=100.0, post_raw_price=50.0,
        pre_adjusted_price=50.0, post_adjusted_price=50.0,
        pre_shares=10.0, post_shares=10.0, price_basis="QFQ",
    )
    assert result["status"] == "PASS"
    assert result["position_value_return"] == 0.0


def test_one_for_ten_reverse_split_adjusted_price_does_not_create_900pct_gain():
    result = audit.audit_split_relationship(
        split_ratio=0.1, pre_raw_price=1.0, post_raw_price=10.0,
        pre_adjusted_price=10.0, post_adjusted_price=10.0,
        pre_shares=10.0, post_shares=10.0, price_basis="QFQ",
    )
    assert result["status"] == "PASS"
    assert result["adjusted_price_return"] == 0.0


def test_raw_price_with_unchanged_shares_is_detected():
    result = audit.audit_split_relationship(
        split_ratio=2.0, pre_raw_price=100.0, post_raw_price=50.0,
        pre_adjusted_price=100.0, post_adjusted_price=50.0,
        pre_shares=10.0, post_shares=10.0, price_basis="RAW",
    )
    assert result["status"] == "FAIL"
    assert "B_RAW_OR_CONVERSION_PRICE_WITH_SHARES_NOT_ADJUSTED" in result["failure_codes"]


def test_adjusted_price_and_split_adjusted_shares_double_adjustment_is_detected():
    result = audit.audit_split_relationship(
        split_ratio=2.0, pre_raw_price=100.0, post_raw_price=50.0,
        pre_adjusted_price=50.0, post_adjusted_price=50.0,
        pre_shares=10.0, post_shares=20.0, price_basis="QFQ",
    )
    assert result["status"] == "FAIL"
    assert "A_PRICE_ADJUSTED_AND_SHARES_ADJUSTED_TWICE" in result["failure_codes"]


def test_security_migration_quantity_continuity_is_detected():
    result = audit.audit_split_relationship(
        split_ratio=0.008352, pre_raw_price=1.54, post_raw_price=18.0,
        pre_adjusted_price=1.54, post_adjusted_price=18.0,
        pre_shares=10.0, post_shares=10.0, price_basis="SECURITY_CONVERSION",
        security_continuity=False,
    )
    assert result["status"] == "FAIL"
    assert "J_SECURITY_IDENTIFIER_CHANGED_BUT_TICKER_JOIN_CONTINUED_POSITION" in result["failure_codes"]


def test_independent_nav_reconstruction_cash_positions_trades_and_costs():
    dates = pd.to_datetime(["2023-01-03", "2023-01-04", "2023-01-05", "2023-01-06"])
    qfq = pd.DataFrame([
        {"ticker": ticker, "trade_date": date, "open": price, "close": price, "autype": "qfq", "source": "MOOMOO_OPEND"}
        for ticker, prices in {"QQQ": [100, 101, 102, 103], "AAA": [10, 11, 12, 13]}.items()
        for date, price in zip(dates, prices)
    ])
    targets = {dates[0]: {"AAA": 1.0}, dates[1]: {"AAA": 1.0}}
    result = audit.reconstruct_path(
        model="A1", target_map=targets, qfq=qfq,
        signal_dates=[dates[0], dates[1]], cost_bps=10,
    )
    assert result.daily.reconstruction_mode.eq("POSITION_LEDGER").all()
    assert result.daily.NAV_ACCOUNTING_IDENTITY_ERROR.abs().max() <= 1e-12
    assert result.daily.CASH_IDENTITY_ERROR.abs().max() <= 1e-12
    assert result.daily.iloc[-1].actual_risky_name_count == 0


def test_extreme_return_fingerprint_detector():
    assert audit.fingerprint_match(9.02) == "+900%"
    assert audit.fingerprint_match(-0.899) == "-90%"
    assert audit.fingerprint_match(0.17) is None
    assert audit.infer_simple_split_ratio(0.1) == (0.1, "REVERSE_SPLIT")


def test_missing_price_basis_fails_closed():
    result = audit.audit_split_relationship(
        split_ratio=2.0, pre_raw_price=100.0, post_raw_price=50.0,
        pre_adjusted_price=50.0, post_adjusted_price=50.0,
        pre_shares=10.0, post_shares=10.0, price_basis="UNKNOWN",
    )
    assert result["status"] == "FAIL_CLOSED_UNKNOWN_PRICE_BASIS"


def test_audit_source_contains_no_model_fit_call():
    source = inspect.getsource(audit)
    tree = ast.parse(source)
    calls = [
        node for node in ast.walk(tree) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == "fit"
    ]
    assert calls == []


def test_audit_reads_no_post2025_target_or_outcome_columns():
    source = inspect.getsource(audit.load_inputs)
    assert 'signal_columns = ["signal_date", "ticker", "a1_rank", "a2_rank"]' in source
    assert "target" not in source.split("signal_columns =", 1)[1].split("signals =", 1)[0]
    assert "outcome" not in source.split("signal_columns =", 1)[1].split("signals =", 1)[0]
    assert audit.END_EXCLUSIVE == pd.Timestamp("2026-01-01")


def test_required_output_contract_is_complete():
    assert len(audit.ARTIFACT_NAMES) == 12
    assert "provenance_manifest.json" in audit.ARTIFACT_NAMES
    assert "nav_reconstruction_daily.parquet" in audit.ARTIFACT_NAMES
