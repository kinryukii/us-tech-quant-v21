from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

import pandas as pd
import pytest

from attribution.drawdown import detect_drawdown_episodes, drawdown_window_diagnostics
from attribution.engine import AttributionEngine, concentration_metrics, normalize_rows
from attribution.incremental import IncrementalAttributionEngine
from attribution.io import ImmutableInputError, verify_immutable_manifest
from attribution.schemas import AttributionConfig, schema_contract


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "scripts/v22/fixtures/attribution"
FIXTURE = FIXTURE_DIR / "tiny_portfolio_fixture.json"
CONFIG = ROOT / "config/research_governance/a2_attribution_r1.json"


def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def config() -> AttributionConfig:
    return AttributionConfig.from_dict(json.loads(CONFIG.read_text(encoding="utf-8"))["engine"])


def a2_result() -> dict:
    data = payload()
    return AttributionEngine(config()).run(data["a2_rows"], data["a2_daily"])


def incremental_result() -> dict:
    data = payload()
    return IncrementalAttributionEngine(config()).run(
        data["a_rows"], data["a2_rows"], data["a_daily"], data["a2_daily"],
    )


def synthetic_row(date: str, security_id: str, contribution: float, rank: int, sector: str = "TECH") -> dict:
    return {
        "strategy_id": "A2", "date": date, "security_id": security_id, "ticker": security_id,
        "sector": sector, "industry": "SYNTHETIC", "component_type": "SECURITY", "rank": rank,
        "portfolio_weight": 0.5, "previous_weight": 0.5, "security_return": contribution,
        "transaction_cost": 0.0, "turnover_contribution": 0.0,
        "gross_contribution": contribution, "cost_contribution": 0.0, "net_contribution": contribution,
        "universe_id": "U_SYNTHETIC", "model_id": "A2_HGB", "vintage_id": "V_SYNTHETIC",
    }


def test_1_exact_additive_identity_with_signed_cost() -> None:
    data = payload()
    first_day = [row for row in data["a2_rows"] if row["date"] == "2024-12-31"]
    daily = [data["a2_daily"][0]]
    result = AttributionEngine(config()).run(first_day, daily)
    assert sum(row["gross_contribution"] for row in first_day) == pytest.approx(0.01 - 0.004)
    assert sum(row["cost_contribution"] for row in first_day) == pytest.approx(-0.001)
    assert result["summary"]["total_net_contribution"] == pytest.approx(0.005)
    assert result["reconciliation"]["status"] == "PASS"


def test_2_identity_failure_is_reported_not_silently_accepted() -> None:
    data = payload()
    data["a2_daily"][0]["authoritative_portfolio_return"] = 0.006
    result = AttributionEngine(config()).run(data["a2_rows"], data["a2_daily"])
    assert result["reconciliation"]["status"] == "FAIL"
    assert "daily_net_identity_tolerance_exceeded" in result["reconciliation"]["reasons"]


def test_3_security_ranking_uses_contribution_not_raw_return() -> None:
    result = a2_result()
    security = result["security_attribution"]
    assert security.iloc[0].security_id == "S1"
    raw = result["normalized_rows"].groupby("security_id").security_return.max()
    assert raw.idxmax() == "S2"


def test_4_rank_bucket_attribution_is_additive() -> None:
    result = a2_result()
    buckets = result["rank_bucket_attribution"].set_index("rank_bucket")
    assert {"RANK_1_5", "RANK_6_10", "RANK_11_20"} <= set(buckets.index)
    assert buckets.net_contribution.sum() == pytest.approx(result["summary"]["total_net_contribution"])
    assert buckets.at["RANK_11_20", "net_contribution"] == pytest.approx(0.0042)


def test_5_security_top5_share_and_effective_count() -> None:
    values = pd.Series([5.0, 1.0, 1.0, 1.0, 1.0, 1.0], index=list("ABCDEF"))
    metrics = concentration_metrics(values, "security")
    assert metrics["top_5_security_positive_contribution_share"] == pytest.approx(0.9)
    assert metrics["security_effective_positive_contributor_count"] == pytest.approx(10.0 / 3.0)


def test_6_positive_and_negative_concentration_are_separate() -> None:
    metrics = concentration_metrics(pd.Series([4.0, -3.0, 1.0, -1.0]), "security")
    assert metrics["security_positive_hhi"] == pytest.approx(0.68)
    assert metrics["security_negative_hhi"] == pytest.approx(0.625)
    assert metrics["security_effective_positive_contributor_count"] == pytest.approx(1 / 0.68)
    assert metrics["security_effective_negative_contributor_count"] == pytest.approx(1 / 0.625)


def test_7_year_and_quarter_time_attribution_reconcile() -> None:
    result = a2_result()
    years = result["time_attribution"]["year"]
    quarters = result["time_attribution"]["quarter"]
    assert set(years.period) == {"2024", "2025"}
    assert years.net_contribution.sum() == pytest.approx(result["summary"]["total_net_contribution"])
    assert quarters.net_contribution.sum() == pytest.approx(result["summary"]["total_net_contribution"])


def test_8_a_vs_a2_incremental_identity() -> None:
    data, result = payload(), incremental_result()
    expected = sum(row["authoritative_portfolio_return"] for row in data["a2_daily"]) - sum(
        row["authoritative_portfolio_return"] for row in data["a_daily"]
    )
    assert result["status"] == "PASS"
    assert result["aligned"].incremental_contribution.sum() == pytest.approx(expected)
    assert result["identity"]["total_identity_error"] == pytest.approx(0.0)


def test_9_a2_only_security_taxonomy() -> None:
    aligned = incremental_result()["aligned"]
    row = aligned.loc[aligned.security_id.eq("S4")].iloc[0]
    assert row.position_class == "A2_ONLY"
    assert row.difference_taxonomy == "A2_ONLY_SELECTION"


def test_10_a_only_security_taxonomy() -> None:
    aligned = incremental_result()["aligned"]
    row = aligned.loc[aligned.security_id.eq("S3")].iloc[0]
    assert row.position_class == "A_ONLY"
    assert row.difference_taxonomy == "A_ONLY_SELECTION"


def test_11_drawdown_detector_uses_strict_recovery() -> None:
    daily = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=5),
        "nav_after": [100.0, 110.0, 88.0, 95.0, 112.0],
    })
    episodes = detect_drawdown_episodes(daily)
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode["peak_date"] == "2024-01-02"
    assert episode["trough_date"] == "2024-01-03"
    assert episode["drawdown_magnitude"] == pytest.approx(-0.20)
    assert episode["recovery_date"] == "2024-01-05"
    assert episode["recovered"] is True


def test_12_drawdown_window_security_contribution_is_additive() -> None:
    rows = normalize_rows([
        synthetic_row("2024-01-03", "X", -0.15, 1),
        synthetic_row("2024-01-03", "Y", -0.05, 6),
        synthetic_row("2024-01-04", "X", 0.03, 1),
    ], config())
    episodes = detect_drawdown_episodes(pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=5), "nav_after": [100, 110, 88, 95, 112],
    }))
    diagnostic = drawdown_window_diagnostics(rows, episodes, config())[0]
    assert diagnostic["window_total_net_contribution"] == pytest.approx(-0.20)
    assert diagnostic["security"].net_contribution.sum() == pytest.approx(-0.20)
    assert diagnostic["identity_status"] == "PASS"


def test_13_transaction_cost_and_turnover_are_independent() -> None:
    result = a2_result()
    assert result["summary"]["total_cost"] == pytest.approx(-0.0015)
    assert result["normalized_rows"].turnover_contribution.sum() == pytest.approx(0.30)
    assert result["rank_bucket_attribution"].cost_contribution.sum() == pytest.approx(-0.0015)


def test_14_missing_sector_remains_unknown() -> None:
    result = a2_result()
    row = result["normalized_rows"].loc[result["normalized_rows"].security_id.eq("S2")].iloc[0]
    assert row.sector == "UNKNOWN"
    assert "UNKNOWN" in set(result["sector_attribution"].sector)


def test_15_immutable_manifest_hash_mismatch_fails_closed() -> None:
    with pytest.raises(ImmutableInputError, match="hash mismatch"):
        verify_immutable_manifest(
            FIXTURE_DIR / "tiny_bad_immutable_manifest.json", {"fixture": FIXTURE},
        )


def test_16_default_fixture_and_source_do_not_touch_live_research() -> None:
    cli = importlib.import_module("a2_attribution_framework_r1")
    assert "A2_OVERNIGHT_OPEN_RESEARCH_20260821_R1" not in str(cli.DEFAULT_FIXTURE)
    assert cli.DEFAULT_FIXTURE == FIXTURE
    paths = [ROOT / "scripts/v22/a2_attribution_framework_r1.py", *(ROOT / "scripts/v22/attribution").glob("*.py")]
    banned_imports = {"sklearn", "xgboost", "lightgbm", "catboost", "torch", "tensorflow", "shap", "moomoo", "futu"}
    imported: set[str] = set()
    fit_calls = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "fit":
                fit_calls.append((path.name, node.lineno))
    assert imported.isdisjoint(banned_imports)
    assert fit_calls == []
    assert schema_contract()["economic_field_policy"] == "AUTHORITATIVE_REALIZED_CONTRIBUTION_FIRST"
