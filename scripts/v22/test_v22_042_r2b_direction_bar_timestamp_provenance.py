from __future__ import annotations

import csv
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
R1_PATH = HERE / "v22_042_option_intraday_etf_direction_gate_r1.py"
R2_PATH = HERE / "v22_042_r2_direction_gate_reason_and_shadow_mode_audit.py"
R2F_PATH = HERE / "v22_037_r2f_direction_aware_liquid_option_contract_ranking_and_no_trade_gate_research_only.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def make_bars(last_et: datetime, interval_minutes: int, step: float, count: int = 30):
    rows = []
    start_time = last_et - timedelta(minutes=interval_minutes * (count - 1))
    for i in range(count):
        value = 100.0 + step * i
        stamp = start_time + timedelta(minutes=interval_minutes * i)
        rows.append({
            "time_key": stamp.strftime("%Y-%m-%d %H:%M:%S"),
            "open": value,
            "high": value + 0.2,
            "low": value - 0.2,
            "close": value,
            "volume": 1000 + i,
        })
    return rows


def timestamped_bars():
    # Naive timestamps intentionally represent Moomoo US Eastern market time.
    end_by_tf = {
        "1m": datetime(2026, 7, 8, 15, 59),
        "15m": datetime(2026, 7, 8, 15, 45),
        "1h": datetime(2026, 7, 8, 15, 0),
    }
    interval = {"1m": 1, "15m": 15, "1h": 60}
    return {
        symbol: {
            tf: make_bars(end_by_tf[tf], interval[tf], 0.2)
            for tf in ["1m", "15m", "1h"]
        }
        for symbol in ["SOXX", "QQQ", "SPY"]
    }


def good_v41():
    return {
        "liquidity_candidate_count": 1,
        "real_readonly_quote_verified": True,
        "fallback_rows_used": False,
    }


def candidate():
    return {
        "contract_id": "SOXL_CALL",
        "underlying": "SOXL",
        "expiration": "2026-07-17",
        "dte": "9",
        "strike": "50",
        "call_put": "CALL",
        "bid": "1",
        "ask": "1.1",
        "mid": "1.05",
        "spread_pct": "0.095",
        "volume": "10",
    }


def test_r1_writes_nine_row_explicit_timestamp_provenance(tmp_path):
    r1 = load_module("v22_042_r1_r2b_test", R1_PATH)
    repo = tmp_path / "repo"
    summary = r1.run(
        repo,
        execute=True,
        bars_by_symbol=timestamped_bars(),
        v22_041_summary=good_v41(),
        v22_041_candidates=[candidate()],
        require_qqq_confirmation=True,
        require_spy_confirmation=False,
    )

    provenance_path = repo / r1.OUT_REL / "direction_bar_timestamp_provenance.csv"
    with provenance_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 9
    assert {(row["underlying"], row["timeframe"]) for row in rows} == {
        (symbol, tf)
        for symbol in ["SOXX", "QQQ", "SPY"]
        for tf in ["1m", "15m", "1h"]
    }
    assert all(row["timestamp_parse_status"] == "OK" for row in rows)
    assert summary["direction_timestamp_complete"] is True
    assert summary["direction_source_time_trust"] == "HIGH"
    assert summary["direction_required_timestamp_row_count"] == 6
    assert summary["direction_parsed_timestamp_row_count"] == 6
    # July is EDT (UTC-4); the conservative minimum required latest bar is 15:00 ET.
    assert summary["direction_source_time_utc"] == "2026-07-08T19:00:00+00:00"
    assert summary["direction_input_latest_time_max_utc"] == "2026-07-08T19:59:00+00:00"
    assert summary["direction_input_time_dispersion_seconds"] == 3540.0
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False


def test_r1_invalid_synthetic_time_keys_do_not_fabricate_timestamp(tmp_path):
    r1 = load_module("v22_042_r1_r2b_missing_test", R1_PATH)
    bars = timestamped_bars()
    for symbol in bars:
        for timeframe in bars[symbol]:
            for index, row in enumerate(bars[symbol][timeframe]):
                row["time_key"] = f"t{index}"

    summary = r1.run(
        tmp_path / "repo",
        execute=True,
        bars_by_symbol=bars,
        v22_041_summary=good_v41(),
        v22_041_candidates=[candidate()],
    )
    assert summary["direction_timestamp_complete"] is False
    assert summary["direction_source_time_utc"] == ""
    assert summary["direction_source_time_trust"] == "MISSING"


def test_r2_propagates_r1_market_timestamp_without_regeneration(tmp_path):
    r1 = load_module("v22_042_r1_for_r2b_propagation", R1_PATH)
    r2 = load_module("v22_042_r2_for_r2b_propagation", R2_PATH)
    repo = tmp_path / "repo"

    r1_summary = r1.run(
        repo,
        execute=True,
        bars_by_symbol=timestamped_bars(),
        v22_041_summary=good_v41(),
        v22_041_candidates=[candidate()],
    )
    r2_summary = r2.run(
        repo,
        execute=True,
        v22_041_summary=good_v41(),
        candidates=[candidate()],
        v22_042_summary=r1_summary,
    )

    for field in [
        "direction_timestamp_contract_version",
        "direction_source_time_utc",
        "direction_source_time_policy",
        "direction_source_time_trust",
        "direction_timestamp_complete",
        "direction_required_timestamp_row_count",
        "direction_parsed_timestamp_row_count",
        "direction_input_latest_time_min_utc",
        "direction_input_latest_time_max_utc",
        "direction_input_time_dispersion_seconds",
        "direction_bar_timestamp_provenance_path",
    ]:
        assert r2_summary[field] == r1_summary[field]


def test_r2f_uses_explicit_market_time_and_fails_closed_without_it():
    source = R2F_PATH.read_text(encoding="utf-8")
    assert "V22.042_R2B_EXPLICIT_DIRECTION_MARKET_TIME_ONLY" in source
    assert "direction_time = datetime.fromtimestamp(direction_summary_path.stat().st_mtime" not in source
    assert 'direction_summary.get("direction_source_time_utc")' in source
    assert 'direction_summary.get("direction_timestamp_complete")' in source
    assert 'direction_time_trust == "HIGH"' in source

    r2f = load_module("v22_037_r2f_r2b_test", R2F_PATH)
    panel_time = datetime(2026, 7, 8, 19, 0, tzinfo=timezone.utc)
    base_summary = {
        "strict_official_final_direction_label": "MIXED_OR_WAIT",
        "strict_official_wait_state": True,
        "primary_wait_reason_code": "WAIT_QQQ_MIXED",
        "direction_source_time_policy": "MIN_LATEST_BAR_TIME_ACROSS_REQUIRED_UNDERLYING_TIMEFRAMES",
    }

    *_, missing_context = r2f.build_outputs(
        [],
        {},
        {
            **base_summary,
            "direction_source_time_utc": "",
            "direction_source_time_trust": "MISSING",
            "direction_timestamp_complete": False,
        },
        [],
        Path("THIS_FILE_MUST_NOT_BE_STAT_ED.json"),
        panel_time,
        r2f.Config(max_panel_age_minutes=30.0, max_direction_panel_gap_minutes=180.0),
        panel_ref_override=panel_time,
    )
    assert missing_context["direction_source_fresh"] is False
    assert missing_context["direction_time_eligible"] is False
    assert missing_context["direction_source_time_utc"] == ""

    *_, explicit_context = r2f.build_outputs(
        [],
        {},
        {
            **base_summary,
            "direction_source_time_utc": panel_time.isoformat(),
            "direction_source_time_trust": "HIGH",
            "direction_timestamp_complete": True,
        },
        [],
        Path("THIS_FILE_MUST_NOT_BE_STAT_ED.json"),
        panel_time,
        r2f.Config(max_panel_age_minutes=30.0, max_direction_panel_gap_minutes=180.0),
        panel_ref_override=panel_time,
    )
    assert explicit_context["direction_source_fresh"] is True
    assert explicit_context["direction_time_eligible"] is True
    assert explicit_context["direction_panel_time_gap_minutes"] == 0.0
