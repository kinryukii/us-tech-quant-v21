from __future__ import annotations

import csv
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).with_name(
    "v22_037_r2f_direction_aware_liquid_option_contract_ranking_and_no_trade_gate_research_only.py"
)
spec = importlib.util.spec_from_file_location("r2f", MODULE_PATH)
r2f = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = r2f
spec.loader.exec_module(r2f)
UTC = timezone.utc


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row}) if rows else ["empty"]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def panel_row(
    underlying: str = "SMH",
    option_type: str = "PUT",
    code: str = "US.SMH260717P600000",
    valuation: str = "2026-07-10T10:00:00-04:00",
    expiry: str = "2026-07-17T16:00:00-04:00",
    **overrides,
):
    row = {
        "panel_rank_underlying": "1",
        "panel_rank_underlying_dte_bucket": "1",
        "liquidity_score": "85",
        "underlying": underlying,
        "contract_code": code,
        "option_type": option_type,
        "expiry_timestamp_et": expiry,
        "valuation_timestamp_et": valuation,
        "days_to_expiry": "7.25",
        "dte_bucket": "1_7DTE",
        "strike": "600",
        "underlying_price": "606.45",
        "bid": "3.90",
        "ask": "4.10",
        "option_market_price": "4.00",
        "spread_ratio_mid": "0.05",
        "quote_alignment_seconds": "2",
        "volume": "1000",
        "open_interest": "5000",
        "synthetic_iv": "0.30",
        "delta": "-0.45" if option_type == "PUT" else "0.45",
        "gamma": "0.02",
        "theta_per_day": "-0.10",
        "vega_per_1vol_point": "0.05",
        "liquid_panel_eligible": "True",
        "eligible_for_research_ranking": "True",
    }
    row.update(overrides)
    return row


def comparison_rows():
    return [
        {
            "gate_mode": "strict_official_gate",
            "direction_label": "MIXED_OR_WAIT",
            "wait_state": "True",
            "candidate_count": "0",
            "reason_code": "WAIT_BROAD_CONFIRMATION_MISSING",
            "official_gate": "True",
            "shadow_only": "False",
        },
        {
            "gate_mode": "semiconductor_only_shadow_gate",
            "direction_label": "BEAR_SEMICONDUCTOR",
            "wait_state": "False",
            "candidate_count": "1",
            "reason_code": "SHADOW_SEMICONDUCTOR_ONLY_DIRECTION_AVAILABLE",
            "official_gate": "False",
            "shadow_only": "True",
        },
    ]


def direction_summary():
    return {
        "strict_official_wait_state": True,
        "strict_official_final_direction_label": "MIXED_OR_WAIT",
        "primary_wait_reason_code": "WAIT_BROAD_CONFIRMATION_MISSING",
        "secondary_wait_reason_code": "WAIT_QQQ_MIXED",
        "semiconductor_only_shadow_direction_label": "BEAR_SEMICONDUCTOR",
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
    }


def set_mtime(path: Path, dt: datetime) -> None:
    timestamp = dt.timestamp()
    os.utime(path, (timestamp, timestamp))


def test_bool_value():
    assert r2f.bool_value("True")
    assert r2f.bool_value(1)
    assert not r2f.bool_value("False")


def test_safe_float():
    assert r2f.safe_float("1.25") == 1.25
    assert r2f.safe_float("nan") is None
    assert r2f.safe_float(None) is None


def test_parse_datetime_z():
    assert r2f.parse_datetime("2026-07-10T14:00:00Z").tzinfo is not None


def test_parse_datetime_invalid():
    assert r2f.parse_datetime("bad") is None


@pytest.mark.parametrize(
    "label,direction,scope",
    [
        ("MIXED_OR_WAIT", "WAIT", "ALL"),
        ("BEAR_SEMICONDUCTOR", "BEARISH", "SEMICONDUCTOR"),
        ("BULL_SEMICONDUCTOR", "BULLISH", "SEMICONDUCTOR"),
        ("BEARISH", "BEARISH", "BROAD"),
        ("BULLISH", "BULLISH", "BROAD"),
        ("UNKNOWN_VALUE", "WAIT", "BROAD"),
    ],
)
def test_normalize_direction(label, direction, scope):
    assert r2f.normalize_direction(label) == (direction, scope)


def test_scope_semiconductor():
    assert r2f.underlying_in_scope("SMH", "SEMICONDUCTOR")
    assert r2f.underlying_in_scope("SOXX", "SEMICONDUCTOR")
    assert not r2f.underlying_in_scope("QQQ", "SEMICONDUCTOR")


def test_required_option_type_direct():
    assert r2f.required_option_type("QQQ", "BULLISH") == "CALL"
    assert r2f.required_option_type("QQQ", "BEARISH") == "PUT"


def test_required_option_type_inverse():
    assert r2f.required_option_type("SOXS", "BULLISH") == "PUT"
    assert r2f.required_option_type("SOXS", "BEARISH") == "CALL"


def test_required_option_type_wait():
    assert r2f.required_option_type("QQQ", "WAIT") == ""


def test_target_delta():
    cfg = r2f.Config(target_abs_delta_0dte=0.4, target_abs_delta_1_7dte=0.5)
    assert r2f.target_abs_delta("0DTE", cfg) == 0.4
    assert r2f.target_abs_delta("1_7DTE", cfg) == 0.5


def test_panel_reference_time_max():
    rows = [
        panel_row(valuation="2026-07-10T10:00:00-04:00"),
        panel_row(code="B", valuation="2026-07-10T10:05:00-04:00"),
    ]
    value = r2f.panel_reference_time(rows)
    assert value == datetime(2026, 7, 10, 14, 5, tzinfo=UTC)




def test_derive_panel_reference_time_from_r2d_recalc(tmp_path):
    run = tmp_path / "run"
    recalc = run / "iv_greeks_r2b_child" / "option_iv_greeks_recalculated_research_only.csv"
    write_csv(recalc, [{"valuation_timestamp_et": "2026-07-10T10:30:00-04:00"}])
    value, source, trust = r2f.derive_panel_reference_time(
        tmp_path,
        [{"underlying": "QQQ"}],
        {"source_r2d_run_dir": str(run)},
    )
    assert value == datetime(2026, 7, 10, 14, 30, tzinfo=UTC)
    assert source == "R2D_RECALCULATED_EXPLICIT_VALUATION_TIMESTAMP"
    assert trust == "HIGH"


def test_minmax_scores():
    assert r2f.minmax_scores([1.0, 2.0, 3.0]) == [0.0, 50.0, 100.0]
    assert r2f.minmax_scores([1.0, 1.0]) == [100.0, 100.0]


def test_base_components_good():
    components = r2f.base_components(panel_row(), r2f.Config())
    assert components["liquidity_component"] == 85.0
    assert components["alignment_component"] > 80
    assert components["spread_component"] > 60


def test_gamma_theta_raw():
    assert r2f.gamma_theta_raw(panel_row(gamma="0.02", theta_per_day="-0.1")) == pytest.approx(0.2)


def test_mode_rows_from_csv():
    modes = r2f.mode_rows(direction_summary(), comparison_rows())
    assert len(modes) == 2
    assert modes[0]["official_gate"] is True
    assert modes[1]["shadow_only"] is True


def test_mode_rows_summary_fallback():
    modes = r2f.mode_rows(direction_summary(), [])
    assert len(modes) == 1
    assert modes[0]["gate_mode"] == "strict_official_gate"


def test_universe_union():
    result = r2f.universe_from_summary([panel_row("SMH")], {"underlyings": "QQQ,SOXX,SMH"})
    assert result == ["QQQ", "SMH", "SOXX"]


def test_discover_explicit_r2e(tmp_path):
    assert r2f.discover_r2e_output(tmp_path, tmp_path) == tmp_path.resolve()


def test_discover_direction_latest(tmp_path):
    root = tmp_path / "outputs" / "v22" / "V22.042_X"
    root.mkdir(parents=True)
    old = root / "old_summary.json"
    new = root / "v22_042_summary.json"
    old.write_text("{}", encoding="utf-8")
    new.write_text("{}", encoding="utf-8")
    set_mtime(old, datetime(2026, 7, 9, tzinfo=UTC))
    set_mtime(new, datetime(2026, 7, 10, tzinfo=UTC))
    assert r2f.discover_v22_042_summary(tmp_path) == new.resolve()


def test_build_outputs_strict_wait_shadow_selects_when_fresh(tmp_path):
    now = datetime(2026, 7, 10, 14, 5, tzinfo=UTC)
    summary_path = tmp_path / "v22_042_summary.json"
    summary_path.write_text("{}", encoding="utf-8")
    set_mtime(summary_path, datetime(2026, 7, 10, 14, 0, tzinfo=UTC))
    panel = [panel_row(valuation="2026-07-10T10:00:00-04:00", expiry="2026-07-17T16:00:00-04:00")]
    rankings, top, no_trade, dte, context = r2f.build_outputs(
        panel, {"underlyings": "SMH,SOXX"}, direction_summary(), comparison_rows(), summary_path, now, r2f.Config(max_panel_age_minutes=10)
    )
    assert context["panel_fresh"] is True
    assert context["direction_source_fresh"] is True
    assert len(rankings) == 1
    assert len(top) == 1
    assert top[0]["underlying"] == "SMH"
    assert top[0]["shadow_only"] is True
    strict_smh = next(row for row in no_trade if row["gate_mode"] == "strict_official_gate" and row["underlying"] == "SMH")
    assert strict_smh["primary_gate_result"] == "NO_TRADE_DIRECTION_WAIT"


def test_build_outputs_stale_direction_blocks_selection(tmp_path):
    now = datetime(2026, 7, 10, 14, 5, tzinfo=UTC)
    summary_path = tmp_path / "v22_042_summary.json"
    summary_path.write_text("{}", encoding="utf-8")
    set_mtime(summary_path, datetime(2026, 7, 9, 10, 0, tzinfo=UTC))
    panel = [panel_row(valuation="2026-07-10T10:00:00-04:00")]
    rankings, top, no_trade, _, context = r2f.build_outputs(
        panel, {"underlyings": "SMH"}, direction_summary(), comparison_rows(), summary_path, now, r2f.Config(max_panel_age_minutes=10)
    )
    assert context["direction_source_fresh"] is False
    assert len(rankings) == 1
    assert top == []
    shadow = next(row for row in no_trade if row["gate_mode"] == "semiconductor_only_shadow_gate")
    assert "NO_TRADE_DIRECTION_INPUT_STALE" in shadow["all_gate_reasons"]


def test_build_outputs_stale_panel_blocks_selection(tmp_path):
    now = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)
    summary_path = tmp_path / "v22_042_summary.json"
    summary_path.write_text("{}", encoding="utf-8")
    set_mtime(summary_path, datetime(2026, 7, 10, 14, 0, tzinfo=UTC))
    panel = [panel_row(valuation="2026-07-10T10:00:00-04:00")]
    _, top, no_trade, _, context = r2f.build_outputs(
        panel, {"underlyings": "SMH"}, direction_summary(), comparison_rows(), summary_path, now, r2f.Config(max_panel_age_minutes=30)
    )
    assert context["panel_fresh"] is False
    assert top == []
    assert any("NO_TRADE_PANEL_STALE" in row["all_gate_reasons"] for row in no_trade)


def test_build_outputs_expired_contract_blocks(tmp_path):
    now = datetime(2026, 7, 18, 14, 0, tzinfo=UTC)
    summary_path = tmp_path / "v22_042_summary.json"
    summary_path.write_text("{}", encoding="utf-8")
    set_mtime(summary_path, now)
    panel = [panel_row(valuation="2026-07-18T09:59:00-04:00", expiry="2026-07-17T16:00:00-04:00")]
    _, top, no_trade, _, _ = r2f.build_outputs(
        panel, {"underlyings": "SMH"}, direction_summary(), comparison_rows(), summary_path, now, r2f.Config(max_panel_age_minutes=10)
    )
    assert top == []
    shadow = next(row for row in no_trade if row["gate_mode"] == "semiconductor_only_shadow_gate")
    assert "NO_UNEXPIRED_MATCHING_CONTRACT" in shadow["all_gate_reasons"]


def test_build_outputs_outside_scope(tmp_path):
    now = datetime(2026, 7, 10, 14, 5, tzinfo=UTC)
    summary_path = tmp_path / "v22_042_summary.json"
    summary_path.write_text("{}", encoding="utf-8")
    set_mtime(summary_path, datetime(2026, 7, 10, 14, 0, tzinfo=UTC))
    panel = [panel_row(underlying="QQQ", option_type="PUT", code="US.QQQP", valuation="2026-07-10T10:00:00-04:00")]
    _, top, no_trade, _, _ = r2f.build_outputs(
        panel, {"underlyings": "QQQ"}, direction_summary(), comparison_rows(), summary_path, now, r2f.Config(max_panel_age_minutes=10)
    )
    assert top == []
    shadow = next(row for row in no_trade if row["gate_mode"] == "semiconductor_only_shadow_gate")
    assert "NO_TRADE_OUTSIDE_DIRECTION_SCOPE" in shadow["all_gate_reasons"]


def test_score_candidate_groups_ranks_better_row():
    rows = []
    for code, liquidity, spread in [("A", "90", "0.01"), ("B", "50", "0.10")]:
        row = panel_row(code=code, liquidity_score=liquidity, spread_ratio_mid=spread)
        row.update({"gate_mode": "x", "dte_bucket": "1_7DTE"})
        rows.append(row)
    r2f.score_candidate_groups(rows, r2f.Config())
    ranks = {row["contract_code"]: row["direction_rank_underlying_bucket"] for row in rows}
    assert ranks["A"] == 1
    assert ranks["B"] == 2


def test_execute_end_to_end(tmp_path):
    repo = tmp_path / "repo"
    r2e_dir = tmp_path / "r2e"
    output = tmp_path / "out"
    direction_dir = tmp_path / "direction"
    direction_dir.mkdir(parents=True)
    paths = r2f.required_r2e_paths(r2e_dir)
    write_csv(paths["panel"], [panel_row()])
    write_csv(paths["topn"], [panel_row()])
    paths["summary"].write_text(json.dumps({"underlyings": "SMH,SOXX"}), encoding="utf-8")
    direction_path = direction_dir / "v22_042_r2_summary.json"
    direction_path.write_text(json.dumps(direction_summary()), encoding="utf-8")
    write_csv(direction_dir / "direction_gate_mode_comparison.csv", comparison_rows())
    panel_time = datetime(2026, 7, 10, 14, 0, tzinfo=UTC)
    set_mtime(direction_path, panel_time)
    summary = r2f.execute(
        repo, output, r2e_dir, direction_path,
        r2f.Config(max_panel_age_minutes=10),
        now_override=datetime(2026, 7, 10, 14, 5, tzinfo=UTC),
    )
    assert summary["final_status"] == r2f.PASS_STATUS
    assert summary["selected_contract_count"] == 1
    assert summary["shadow_selected_contract_count"] == 1
    assert (output / "no_trade_gate_audit.csv").exists()
    assert (output / "direction_input_provenance.csv").exists()


def test_execute_missing_input(tmp_path):
    output = tmp_path / "out"
    summary = r2f.execute(tmp_path, output, tmp_path / "missing", None, r2f.Config())
    assert summary["final_status"] == r2f.FAIL_INPUT
    assert summary["broker_action_allowed"] is False
