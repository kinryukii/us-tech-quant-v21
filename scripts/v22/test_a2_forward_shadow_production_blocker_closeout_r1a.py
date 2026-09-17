"""Tiny structural closeout tests; no real-universe inference or history append."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from forward_shadow.exact_date_components import (
    ExactDateComponentError,
    file_sha256,
    load_frozen_module,
    run_alpha_single_date,
    run_execution_single_date,
    run_risk_single_date,
    write_staging_only,
)
from forward_shadow.production_binding import component_composite_sha256
from forward_shadow.trading_calendar import ForwardShadowTradingCalendarProvider


CALENDAR = REPO / "config" / "research_governance" / "a2_forward_shadow_trading_calendar_r1.json"
BINDING = REPO / "config" / "research_governance" / "a2_forward_shadow_production_binding_r1.json"
_CASE = 0


@pytest.fixture
def tmp_path() -> Path:
    global _CASE
    root_value = os.environ.get("A2_FORWARD_CLOSEOUT_SYNTHETIC_TEST_ROOT")
    if not root_value:
        pytest.fail("A2_FORWARD_CLOSEOUT_SYNTHETIC_TEST_ROOT is required")
    root = Path(root_value).resolve()
    if "forward_closeout_synthetic" not in root.name:
        pytest.fail("refusing non-synthetic test root")
    _CASE += 1
    case = root / f"case_{_CASE:03d}"
    case.mkdir(parents=True, exist_ok=False)
    return case


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def component(model_id: str, artifacts: list[dict], composite: str | None = None) -> dict:
    return {
        "model_id": model_id, "artifacts": artifacts,
        "composite_sha256": composite or component_composite_sha256(artifacts),
    }


def artifact(path: Path, artifact_id: str) -> dict:
    return {"artifact_id": artifact_id, "path": str(path), "sha256": file_sha256(path)}


class AlphaApi:
    FEATURE_COLUMNS = ("F1", "F2")

    @staticmethod
    def _prediction_rank(frame: pd.DataFrame, score_column: str) -> pd.Series:
        ranked = frame.sort_values([score_column, "ticker"], ascending=[False, True], kind="mergesort")
        result = pd.Series(index=frame.index, dtype="int32")
        result.loc[ranked.index] = np.arange(1, len(ranked) + 1)
        return result.astype("int32")


class AlphaModel:
    fit_calls = 0

    def fit(self, *_args, **_kwargs):
        type(self).fit_calls += 1
        raise AssertionError("fit forbidden")

    def predict(self, values):
        return np.asarray(values)[:, 0]


class RiskModel:
    fit_calls = 0
    threshold_search_calls = 0

    def predict_proba(self, frame):
        score = np.clip(np.asarray(frame)[:, 0], 0.0, 1.0)
        return np.column_stack([1.0 - score, score])


def alpha_case(tmp_path: Path) -> tuple[dict, dict]:
    model, source, contract = tmp_path / "model.bin", tmp_path / "alpha.py", tmp_path / "contract.json"
    model.write_bytes(b"frozen-alpha")
    source.write_text("# frozen synthetic alpha\n", encoding="utf-8")
    write_json(contract, {"TOP_N": 20})
    artifacts = [artifact(model, "model"), artifact(source, "source"), artifact(contract, "frozen_contracts")]
    binding = component("A2_HGB", artifacts)
    payload = {
        "target_date": "2026-08-21", "universe_id": "U", "vintage_id": "V",
        "feature_rows": [
            {"security_id": f"S{i:03d}", "ticker": f"T{i:03d}", "F1": float(i), "F2": 1.0}
            for i in range(1, 26)
        ],
    }
    return binding, payload


def alpha_records(tmp_path: Path) -> tuple[dict, ...]:
    binding, payload = alpha_case(tmp_path)
    return run_alpha_single_date(
        "2026-08-21", payload, binding, model_loader=lambda _path: AlphaModel(),
        module_loader=lambda _path, _name: AlphaApi,
    )


def risk_case(tmp_path: Path, alpha: tuple[dict, ...], run_id: str = "RUN") -> tuple[dict, dict, dict]:
    model, prereg = tmp_path / "risk.bin", tmp_path / "prereg.json"
    model.write_bytes(b"frozen-risk")
    write_json(prereg, {"preregistered_payload": {"economic_shadow": {"rule": {
        "risk_percentile_at_least_90": 0.5, "risk_percentile_below_90": 1.0,
        "removed_weight_destination": "CASH",
    }}}})
    artifacts = [artifact(model, "model"), artifact(prereg, "r11_preregistration")]
    selected = [row for row in alpha if row["raw_target_weight"] > 0]
    payload = {
        "target_date": "2026-08-21", "input_alpha_run_id": run_id,
        "feature_rows": [
            {"security_id": row["security_id"], "ticker": row["ticker"], "F1": index / 20, "F2": 1.0}
            for index, row in enumerate(selected, 1)
        ],
    }
    deploy = {"model": RiskModel(), "features": ["F1", "F2"], "reference_scores_sorted": np.linspace(0, 1, 101)}
    return component("R6_BAD_ASYMMETRY", artifacts), payload, deploy


def e5_case() -> tuple[dict, tuple[dict, ...], dict]:
    binding = json.loads(BINDING.read_text(encoding="utf-8"))["components"]["EXECUTION"]
    tickers = [f"T{i:03d}" for i in range(1, 126)]
    wanted = set(tickers[1:21])
    rank_map = {ticker: index for index, ticker in enumerate(tickers[1:21], 1)}
    rank_map["T022"], rank_map["T001"] = 21, 22
    for index, ticker in enumerate(tickers[22:], 23):
        rank_map[ticker] = index
    alpha = tuple({
        "target_date": "2026-08-21", "security_id": ticker, "ticker": ticker,
        "rank": rank_map[ticker], "score": float(126 - rank_map[ticker]),
        "raw_target_weight": 0.05 if ticker in wanted else 0.0,
        "model_id": "A2_HGB", "universe_id": "U", "vintage_id": "V",
    } for ticker in tickers)
    payload = {
        "target_date": "2026-08-21", "previous_date": "2026-08-20",
        "input_alpha_run_id": "RUN", "input_risk_run_id": "RUN",
        "previous_executed_holdings": tickers[:20],
        "previous_alpha_rows": [{"ticker": ticker, "rank": index} for index, ticker in enumerate(tickers, 1)],
    }
    return binding, alpha, payload


def test_01_normal_weekday_is_session():
    assert ForwardShadowTradingCalendarProvider(CALENDAR).is_session("2026-08-21")


def test_02_weekend_is_non_session():
    assert not ForwardShadowTradingCalendarProvider(CALENDAR).is_session("2026-08-22")


@pytest.mark.parametrize("holiday", [
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
])
def test_03_us_holidays_are_non_sessions(holiday):
    assert not ForwardShadowTradingCalendarProvider(CALENDAR).is_session(holiday)


def test_04_calendar_includes_2026_08_21():
    assert "2026-08-21" in ForwardShadowTradingCalendarProvider(CALENDAR).sessions


def test_05_calendar_horizon_through_2027():
    provider = ForwardShadowTradingCalendarProvider(CALENDAR)
    assert (str(provider.start), str(provider.end)) == ("2026-01-01", "2027-12-31")


def test_06_calendar_hash_is_deterministic():
    first, second = ForwardShadowTradingCalendarProvider(CALENDAR), ForwardShadowTradingCalendarProvider(CALENDAR)
    assert first.contract["sessions_sha256"] == second.contract["sessions_sha256"] == "07be0ad0b9e1330ca027872cbe6259bb8a5f1035ea6ef0b71cf41a62963d5516"


def test_07_alpha_exact_date_only(tmp_path):
    binding, payload = alpha_case(tmp_path)
    with pytest.raises(ExactDateComponentError, match="ALPHA_EXACT_DATE_REQUIRED"):
        run_alpha_single_date("2026-08-20", payload, binding, model_loader=lambda _: AlphaModel(), module_loader=lambda *_: AlphaApi)


def test_08_alpha_never_calls_fit(tmp_path):
    AlphaModel.fit_calls = 0
    result = alpha_records(tmp_path)
    assert len(result) == 25 and AlphaModel.fit_calls == 0


def test_09_alpha_staging_only(tmp_path):
    records = alpha_records(tmp_path)
    authority = tmp_path / "authority"
    authority.mkdir()
    history = authority / "history.json"
    write_json(history, {"immutable": True})
    before = file_sha256(history)
    output = write_staging_only(tmp_path / "stage", "alpha.json", {"records": records}, authoritative_roots=[authority])
    assert output.is_file() and file_sha256(history) == before


def test_10_alpha_wrong_frozen_hash_fails(tmp_path):
    binding, payload = alpha_case(tmp_path)
    binding["artifacts"][0]["sha256"] = "0" * 64
    with pytest.raises(ExactDateComponentError):
        run_alpha_single_date("2026-08-21", payload, binding, model_loader=lambda _: AlphaModel(), module_loader=lambda *_: AlphaApi)


def test_11_risk_exact_upstream_lineage(tmp_path):
    alpha = alpha_records(tmp_path)
    binding, payload, deploy = risk_case(tmp_path, alpha)
    result = run_risk_single_date("2026-08-21", payload, binding, alpha, "RUN", artifact_loader=lambda _: deploy)
    assert len(result) == 20


def test_12_risk_wrong_alpha_lineage_fails(tmp_path):
    alpha = alpha_records(tmp_path)
    binding, payload, deploy = risk_case(tmp_path, alpha, run_id="WRONG")
    with pytest.raises(ExactDateComponentError, match="RISK_ALPHA_LINEAGE_MISMATCH"):
        run_risk_single_date("2026-08-21", payload, binding, alpha, "RUN", artifact_loader=lambda _: deploy)


def test_13_risk_no_fit_or_threshold_search(tmp_path):
    RiskModel.fit_calls = RiskModel.threshold_search_calls = 0
    alpha = alpha_records(tmp_path)
    binding, payload, deploy = risk_case(tmp_path, alpha)
    run_risk_single_date("2026-08-21", payload, binding, alpha, "RUN", artifact_loader=lambda _: deploy)
    assert RiskModel.fit_calls == RiskModel.threshold_search_calls == 0


def test_14_risk_staging_only(tmp_path):
    alpha = alpha_records(tmp_path)
    binding, payload, deploy = risk_case(tmp_path, alpha)
    records = run_risk_single_date("2026-08-21", payload, binding, alpha, "RUN", artifact_loader=lambda _: deploy)
    assert write_staging_only(tmp_path / "stage", "risk.json", {"records": records}).is_file()


def test_15_e5_exact_date_execution():
    binding, alpha, payload = e5_case()
    result = run_execution_single_date("2026-08-21", payload, binding, alpha, "RUN")
    assert len(result) == 20 and {row["target_date"] for row in result} == {"2026-08-21"}


def test_16_e5_frozen_rule_numeric_identity():
    binding, alpha, payload = e5_case()
    result = run_execution_single_date("2026-08-21", payload, binding, alpha, "RUN")
    source = next(Path(row["path"]) for row in binding["artifacts"] if row["artifact_id"] == "source")
    frozen = load_frozen_module(source, "e5_identity_reference")
    previous = pd.DataFrame(payload["previous_alpha_rows"])
    current = pd.DataFrame(alpha)
    panel = pd.concat([
        pd.DataFrame({"signal_date": pd.Timestamp("2026-08-20"), "ticker": previous.ticker, "a2_rank": previous["rank"], "universe_size": 125.0}),
        pd.DataFrame({"signal_date": pd.Timestamp("2026-08-21"), "ticker": current.ticker, "a2_rank": current["rank"], "universe_size": 125.0}),
    ])
    intended = {
        pd.Timestamp("2026-08-20"): set(payload["previous_executed_holdings"]),
        pd.Timestamp("2026-08-21"): set(current.loc[current.raw_target_weight.gt(0), "ticker"]),
    }
    targets, _ = frozen.build_executed_targets("E5_COMBINED_CONSERVATIVE", panel, intended)
    observed = {row["ticker"]: row["post_execution_weight"] for row in result}
    assert set(observed) == set(targets[pd.Timestamp("2026-08-21")])
    assert max(abs(observed[key] - targets[pd.Timestamp("2026-08-21")][key]) for key in observed) <= 1e-12


def test_17_e5_wrong_frozen_composite_fails():
    binding, alpha, payload = e5_case()
    binding["composite_sha256"] = "0" * 64
    with pytest.raises(ExactDateComponentError, match="COMPOSITE"):
        run_execution_single_date("2026-08-21", payload, binding, alpha, "RUN")


def test_18_e5_has_no_broker_surface():
    binding, alpha, payload = e5_case()
    result = run_execution_single_date("2026-08-21", payload, binding, alpha, "RUN")
    assert all("broker" not in key.lower() for row in result for key in row)


def test_19_e5_no_authoritative_append(tmp_path):
    binding, alpha, payload = e5_case()
    authority = tmp_path / "authority.json"
    write_json(authority, {"rows": ["immutable"]})
    before = file_sha256(authority)
    run_execution_single_date("2026-08-21", payload, binding, alpha, "RUN")
    assert file_sha256(authority) == before


def test_20_execution_downstream_lineage_required():
    binding, alpha, payload = e5_case()
    payload["input_risk_run_id"] = "WRONG"
    with pytest.raises(ExactDateComponentError, match="LINEAGE"):
        run_execution_single_date("2026-08-21", payload, binding, alpha, "RUN")


def test_21_latest_completed_session_is_informational():
    metadata = ForwardShadowTradingCalendarProvider(CALENDAR).completed_session_metadata(
        "2026-08-21", "2026-08-21T18:00:00+09:00", "Asia/Tokyo",
    )
    assert metadata["latest_completed_us_session"] == "2026-08-20"


def test_22_target_date_never_auto_mutated():
    metadata = ForwardShadowTradingCalendarProvider(CALENDAR).completed_session_metadata(
        "2026-08-21", "2026-08-21T18:00:00+09:00", "Asia/Tokyo",
    )
    assert metadata["latest_completed_us_session"] != "2026-08-21"


def test_23_incomplete_current_us_session_reported():
    metadata = ForwardShadowTradingCalendarProvider(CALENDAR).completed_session_metadata(
        "2026-08-21", "2026-08-21T10:00:00-04:00", "America/New_York",
    )
    assert metadata["target_session_completed"] is False


def test_24_previous_date_fallback_remains_forbidden():
    metadata = ForwardShadowTradingCalendarProvider(CALENDAR).completed_session_metadata(
        "2026-08-21", "2026-08-21T10:00:00-04:00", "America/New_York",
    )
    assert metadata["latest_completed_us_session"] == "2026-08-20"
    assert metadata["target_session_completed"] is False
