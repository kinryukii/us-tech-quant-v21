from __future__ import annotations

import csv
import importlib.util
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

MODULE_PATH = Path(__file__).with_name(
    "v22_037_r2_synthetic_iv_greeks_recalculation_and_quality_validation_research_only.py"
)
SPEC = importlib.util.spec_from_file_location("v22_037_r2", MODULE_PATH)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)

ET = ZoneInfo("America/New_York")


def valuation() -> datetime:
    return datetime(2026, 7, 10, 10, 0, 0, tzinfo=ET)


def expiry() -> datetime:
    return datetime(2026, 8, 21, 16, 0, 0, tzinfo=ET)


def option_row(option_type: str = "CALL", strike: float = 100.0, sigma: float = 0.30) -> dict[str, str]:
    t = (expiry() - valuation()).total_seconds() / (365.0 * 86400.0)
    price = m.bs_price(option_type, 100.0, strike, t, 0.043, 0.0, sigma)
    side = "C" if option_type == "CALL" else "P"
    return {
        "contract_code": f"TEST260821{side}{int(strike * 1000):08d}",
        "underlying": "TEST",
        "option_type": option_type,
        "strike": str(strike),
        "expiry": expiry().isoformat(),
        "bid": str(price - 0.005),
        "ask": str(price + 0.005),
        "last_price": str(price),
        "underlying_price": "100",
        "quote_timestamp": valuation().isoformat(),
        "underlying_quote_timestamp": valuation().isoformat(),
        "risk_free_rate": "0.043",
        "dividend_yield": "0",
    }


def test_black_scholes_call_price_is_positive() -> None:
    price = m.bs_price("CALL", 100, 100, 30 / 365, 0.04, 0.0, 0.25)
    assert price > 0
    assert price < 100


def test_black_scholes_put_call_parity() -> None:
    t = 45 / 365
    call = m.bs_price("CALL", 100, 105, t, 0.04, 0.01, 0.28)
    put = m.bs_price("PUT", 100, 105, t, 0.04, 0.01, 0.28)
    rhs = 100 * math.exp(-0.01 * t) - 105 * math.exp(-0.04 * t)
    assert call - put == pytest.approx(rhs, abs=1e-10)


@pytest.mark.parametrize("option_type", ["CALL", "PUT"])
def test_implied_vol_recovers_known_sigma(option_type: str) -> None:
    config = m.Config()
    t = 60 / 365
    expected = 0.42
    price = m.bs_price(option_type, 100, 103, t, 0.043, 0.0, expected)
    iv, iterations, status = m.implied_vol_bisection(
        option_type, price, 100, 103, t, 0.043, 0.0, config
    )
    assert status.startswith("CONVERGED")
    assert iterations > 0
    assert iv == pytest.approx(expected, abs=1e-6)


def test_greeks_sign_invariants() -> None:
    call = m.bs_greeks("CALL", 100, 100, 30 / 365, 0.043, 0.0, 0.30)
    put = m.bs_greeks("PUT", 100, 100, 30 / 365, 0.043, 0.0, 0.30)
    assert 0 < call["delta"] < 1
    assert -1 < put["delta"] < 0
    assert call["gamma"] > 0 and put["gamma"] > 0
    assert call["vega_per_1vol_point"] > 0 and put["vega_per_1vol_point"] > 0
    assert call["rho_per_1pct"] > 0
    assert put["rho_per_1pct"] < 0


def test_option_last_price_is_never_used_as_underlying_spot(tmp_path: Path) -> None:
    row = option_row()
    row.pop("underlying_price")
    row["last_price"] = "99.99"
    result, checks = m.recalculate_row(row, 2, tmp_path / "input.csv", m.Config(), valuation())
    assert result["underlying_price"] is None
    assert result["synthetic_iv"] is None
    spot_check = next(check for check in checks if check["check_name"] == "underlying_price_positive")
    assert spot_check["passed"] == "False"


def test_midpoint_is_preferred_over_last_price(tmp_path: Path) -> None:
    row = option_row()
    expected_mid = (float(row["bid"]) + float(row["ask"])) / 2
    row["last_price"] = str(expected_mid * 1.5)
    result, _ = m.recalculate_row(row, 2, tmp_path / "input.csv", m.Config(), valuation())
    assert result["pricing_source"] == "BID_ASK_MIDPOINT"
    assert result["option_market_price"] == pytest.approx(expected_mid)


def test_arbitrage_violation_is_rejected(tmp_path: Path) -> None:
    row = option_row("CALL")
    row["bid"] = "150"
    row["ask"] = "151"
    result, _ = m.recalculate_row(row, 2, tmp_path / "input.csv", m.Config(), valuation())
    assert result["synthetic_iv"] is None
    assert result["quality_tier"] == "REJECTED"
    assert result["no_arbitrage_pass"] is False


def test_timestamp_misalignment_downgrades_quality(tmp_path: Path) -> None:
    row = option_row()
    row["underlying_quote_timestamp"] = "2026-07-10T09:00:00-04:00"
    result, _ = m.recalculate_row(row, 2, tmp_path / "input.csv", m.Config(), valuation())
    assert result["synthetic_iv"] is not None
    assert result["timestamp_alignment_pass"] is False
    assert result["eligible_for_research_ranking"] is False
    assert result["quality_tier"] in {"B", "C"}


def test_last_price_fallback_is_not_ranking_eligible(tmp_path: Path) -> None:
    row = option_row()
    row["bid"] = ""
    row["ask"] = ""
    result, _ = m.recalculate_row(row, 2, tmp_path / "input.csv", m.Config(), valuation())
    assert result["pricing_source"] == "OPTION_LAST_PRICE_FALLBACK"
    assert result["synthetic_iv"] is not None
    assert result["quote_quality_pass"] is False
    assert result["eligible_for_research_ranking"] is False



def test_missing_rate_and_dividend_are_disclosed_and_downgrade_tier(tmp_path: Path) -> None:
    row = option_row()
    row.pop("risk_free_rate")
    row.pop("dividend_yield")
    result, checks = m.recalculate_row(row, 2, tmp_path / "input.csv", m.Config(), valuation())
    assert result["synthetic_iv"] is not None
    assert "RISK_FREE_RATE_ASSUMED" in result["quality_flags"]
    assert "DIVIDEND_YIELD_ASSUMED" in result["quality_flags"]
    assert result["quality_tier"] == "B"
    assert any(c["check_name"] == "risk_free_rate_source_available" and c["passed"] == "False" for c in checks)

def test_occ_contract_parser() -> None:
    code = "SOXX260821C00150000"
    assert m.parse_underlying("", code) == "SOXX"
    assert m.parse_option_type("", code) == "CALL"
    assert m.parse_strike("", code) == pytest.approx(150.0)
    assert m.parse_expiry("", code).date().isoformat() == "2026-08-21"


def test_date_only_expiry_defaults_to_4pm_et() -> None:
    parsed = m.parse_expiry("2026-08-21")
    assert parsed.hour == 16
    assert parsed.tzinfo is not None


def test_percentage_rate_conversion() -> None:
    rate, assumed = m.convert_rate("4.3", 0.01)
    assert rate == pytest.approx(0.043)
    assert assumed is False


def test_put_call_parity_audit_creates_pair(tmp_path: Path) -> None:
    call, _ = m.recalculate_row(option_row("CALL"), 2, tmp_path / "x.csv", m.Config(), valuation())
    put, _ = m.recalculate_row(option_row("PUT"), 3, tmp_path / "x.csv", m.Config(), valuation())
    audit = m.put_call_parity_audit([call, put], m.Config())
    assert len(audit) == 1
    assert audit[0]["parity_pass"] == "True"


def test_summary_by_underlying_counts_tiers(tmp_path: Path) -> None:
    call, _ = m.recalculate_row(option_row("CALL"), 2, tmp_path / "x.csv", m.Config(), valuation())
    put, _ = m.recalculate_row(option_row("PUT"), 3, tmp_path / "x.csv", m.Config(), valuation())
    summary = m.summarize_by_underlying([call, put])
    assert len(summary) == 1
    assert summary[0]["input_row_count"] == 2
    assert summary[0]["iv_solved_count"] == 2
    assert summary[0]["ranking_eligible_count"] == 2


def test_input_discovery_prefers_r1a_exact_candidate(tmp_path: Path) -> None:
    candidate = tmp_path / "outputs/v22/V22.037_R1A_OPTION_UNDERLYING_PRICE_INJECTION_REPAIR_RESEARCH_ONLY/option_contract_rows_with_underlying_price_repaired_research_only.csv"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("contract_code,option_type,strike,expiry,last_price,underlying_price\nX,CALL,100,2026-08-21,1.0,100\n", encoding="utf-8")
    selected, audit = m.discover_input(tmp_path, None)
    assert selected == candidate
    assert audit[0]["selected"] is True


def test_end_to_end_execute_passes_and_writes_all_outputs(tmp_path: Path) -> None:
    input_path = tmp_path / "input.csv"
    rows = [option_row("CALL", 95), option_row("PUT", 95), option_row("CALL", 105), option_row("PUT", 105)]
    with input_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    output_dir = tmp_path / "out"
    summary = m.execute(tmp_path, output_dir, input_path, m.Config(), valuation())
    assert summary["final_status"] == m.PASS_STATUS
    assert summary["synthetic_iv_solved_count"] == 4
    assert summary["research_ranking_eligible_count"] == 4
    assert summary["research_only"] is True
    assert summary["official_adoption_allowed"] is False
    assert summary["broker_action_allowed"] is False
    for filename in (
        "v22_037_r2_summary.json",
        "option_iv_greeks_recalculated_research_only.csv",
        "option_iv_greeks_quality_validation.csv",
        "option_iv_greeks_quality_summary_by_underlying.csv",
        "option_put_call_parity_audit.csv",
        "option_iv_greeks_input_discovery_audit.csv",
        "option_iv_greeks_input_schema_mapping.csv",
        "V22.037_R2_synthetic_iv_greeks_recalculation_and_quality_validation_report.txt",
    ):
        assert (output_dir / filename).exists(), filename
    loaded = json.loads((output_dir / "v22_037_r2_summary.json").read_text(encoding="utf-8"))
    assert loaded["final_status"] == m.PASS_STATUS


def test_missing_input_persists_failure_summary(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    summary = m.execute(tmp_path, output_dir, None, m.Config(), valuation())
    assert summary["final_status"] == m.FAIL_INPUT
    assert (output_dir / "v22_037_r2_summary.json").exists()


def test_policy_constants_are_hard_blocked() -> None:
    assert m.RESEARCH_ONLY is True
    assert m.OFFICIAL_ADOPTION_ALLOWED is False
    assert m.BROKER_ACTION_ALLOWED is False
