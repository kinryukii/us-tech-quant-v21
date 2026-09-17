from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

import a2_pit_sec_fundamental_acceleration_alpha_r1_resume as resume


ROOT = Path(r"D:\us-tech-quant-results\A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1_RESUME_R1")
R2_ROOT = Path(r"D:\us-tech-quant-results\A2_PIT_SEC_FUNDAMENTAL_ACCELERATION_ALPHA_R1_RESUME_R2")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_artifact_manifest_and_cap() -> None:
    manifest = json.loads((ROOT / "hash_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "PASS_HASH_VERIFIED_NO_ECONOMIC_VERDICT_PRICE_SCALE_LINEAGE_FAILURE"
    assert manifest["artifact_count_including_manifest"] == len(list(ROOT.iterdir())) <= 12
    assert manifest["economic_output_valid"] is False
    assert len(manifest["source_sha256"]) == 64
    for item in manifest["artifacts"]:
        assert sha256(ROOT / item["name"]) == item["sha256"]


def test_frozen_input_and_no_mutation_contract() -> None:
    contract = json.loads((ROOT / "execution_contract.json").read_text(encoding="utf-8"))
    assert contract["raw_top40_checkpoint"]["sha256"] == "1e6fa12b3f8d1144ef0337d343244424f44c27930e8e405b622885c0ae625a17"
    assert contract["raw_top40_checkpoint"]["rows"] == 50_120
    assert contract["raw_top40_checkpoint"]["dates"] == 1_253
    assert contract["raw_a2_model_fit_count"] == 0
    assert contract["cik_repair_count_this_run"] == 0
    assert contract["semantic_alias_repair_count_this_run"] == 0
    assert contract["coverage_gate_change_count"] == 0
    assert contract["2026_outcome_used"] is False
    assert contract["outer_or_2025_driven_adaptation"] is False


def test_trial_budget_and_discovery_firewall() -> None:
    ledger = pd.read_parquet(ROOT / "trial_ledger.parquet")
    model = ledger.loc[ledger.record_type.eq("MODEL_TRIAL")]
    assert model.model_id.nunique() <= 36
    assert len(model) < 200
    discovery = ledger.loc[ledger.physical_max_price_year.notna()]
    assert not discovery.empty
    assert pd.to_numeric(discovery.physical_max_price_year).eq(2022).all()
    assert not ledger.astype(str).apply(lambda column: column.str.contains("2026_OUTCOME_USED=TRUE", regex=False)).any().any()


def test_coverage_and_lineage_final_report() -> None:
    report = (ROOT / "final_report.md").read_text(encoding="utf-8")
    assert "PRIMARY_CLASSIFICATION=NO_VERDICT_DATA_OR_LINEAGE_FAILURE" in report
    assert "POST_RECOVERY_PASSING_DATE_COUNT=945" in report
    assert "POST_RECOVERY_PASSING_DATE_FRACTION=0.7541899441340782" in report
    assert "PIT_EFFECTIVE_DATE_STATUS=PASS_STRICT_NEXT_NYSE_SESSION" in report
    assert "RESTATEMENT_GUARD_STATUS=PASS_ACCESSION_ASOF_NO_BACKFILL" in report
    assert "UNIT_SCALE_STATUS=PASS_USD_ONLY" in report
    assert "2026_LEAKAGE_COUNT=0" in report


def test_price_scale_failure_is_fail_closed() -> None:
    outer = pd.read_csv(ROOT / "outer_metrics.csv")
    assert outer.economic_validity.eq("INVALID_PORTFOLIO_PRICE_SCALE_LINEAGE").all()
    robust = pd.read_csv(ROOT / "robustness_metrics.csv")
    audit = robust.loc[robust.record_type.eq("PORTFOLIO_PRICE_SCALE_LINEAGE_AUDIT")].iloc[0]
    assert robust.record_type.eq("PORTFOLIO_PRICE_SCALE_LINEAGE_AUDIT").sum() == 1
    assert audit.status == "FAIL_CLOSED"
    assert float(audit.nvda_delta_contribution_2023_2024) > 10
    assert float(audit.nvda_clean_max_20d_return) < 1
    freeze = json.loads((ROOT / "finalist_freeze.json").read_text(encoding="utf-8"))
    assert freeze["economic_evidence_valid"] is False
    assert freeze["primary_id"] is None
    assert freeze["forward_eligible"] is False
    assert not (ROOT / "forward_model_bundle.joblib").exists()


def test_anti_bloat_shape() -> None:
    assert (Path(r"D:\us-tech-quant") / "a2_pit_sec_fundamental_acceleration_alpha_r1_resume.py").is_file()
    assert not (Path(r"D:\us-tech-quant") / ".venv").exists()
    assert len(list(ROOT.iterdir())) == 10


class _Policy:
    FORBIDDEN_LABEL_SOURCE = "FROZEN_POSITION_LEDGER_EXACT_MARK"


def _price_views() -> pd.DataFrame:
    exact = pd.DataFrame({
        "ticker": ["X"], "trade_date": pd.to_datetime(["2024-01-02"]),
        "open": [1000.0], "close": [1000.0],
        "source": ["FROZEN_POSITION_LEDGER_EXACT_MARK"],
    })
    raw = exact.copy()
    raw[["open", "close"]] = 10.0
    raw["source"] = "CANONICAL_RAW"
    exact.attrs["raw_counterfactual"] = raw
    return exact


def test_counterfactual_replay_forbids_position_ledger_marks() -> None:
    prices = _price_views()
    fallback = prices.attrs["raw_counterfactual"].copy()
    fallback["source"] = "FROZEN_POSITION_LEDGER_EXACT_MARK"
    prices.attrs["raw_counterfactual"] = pd.concat([prices.attrs["raw_counterfactual"], fallback], ignore_index=True)
    selected = resume.canonical_counterfactual_prices(_Policy, prices, "TEST")
    assert selected.source.ne("FROZEN_POSITION_LEDGER_EXACT_MARK").all()


def test_counterfactual_return_uses_raw_counterfactual_only() -> None:
    prices = _price_views()
    selected = resume.canonical_counterfactual_prices(_Policy, prices, "TEST")
    assert selected.open.iloc[0] == 10.0
    assert selected.source.eq("CANONICAL_RAW").all()


def test_execution_marks_allowed_only_for_accounting() -> None:
    prices = _price_views()
    assert prices.source.eq("FROZEN_POSITION_LEDGER_EXACT_MARK").all()
    assert resume.canonical_counterfactual_prices(_Policy, prices, "TEST").source.ne("FROZEN_POSITION_LEDGER_EXACT_MARK").all()


def _r2_reconciliation() -> dict:
    assert R2_ROOT.is_dir()
    return json.loads((R2_ROOT / "portfolio_lineage_reconciliation.json").read_text(encoding="utf-8"))


def test_nvda_portfolio_scale_regression() -> None:
    assert _r2_reconciliation()["nvda_portfolio_regression_status"] == "PASS"


def test_normal_split_portfolio_replay() -> None:
    assert any(row["role"] == "FORWARD_SPLIT" for row in _r2_reconciliation()["sentinels"])


def test_reverse_split_portfolio_replay() -> None:
    assert any(row["role"] == "REVERSE_SPLIT" for row in _r2_reconciliation()["sentinels"])


def test_no_action_portfolio_replay() -> None:
    assert any(row["role"] == "NO_ACTION_CONTROL" for row in _r2_reconciliation()["sentinels"])


def test_full_portfolio_return_reconciliation_zero_mismatch() -> None:
    audit = _r2_reconciliation()
    assert audit["portfolio_return_reconciliation_count"] > 0
    assert audit["portfolio_return_mismatch_count"] == 0
    assert audit["max_abs_return_mismatch"] == 0
    assert audit["arithmetic_envelope_failure_count"] == 0


def test_divergent_holding_delta_nav_formula() -> None:
    audit = _r2_reconciliation()
    assert audit["divergent_holding_arithmetic_status"] == "PASS"
    assert audit["divergent_holding_abs_error"] <= 1e-12


def _dependency_audit() -> pd.DataFrame:
    return pd.read_csv(R2_ROOT / "price_lineage_dependency_audit.csv")


def test_membership_attribution_uses_clean_return() -> None:
    row = _dependency_audit().loc[lambda frame: frame.stage.eq("membership attribution")].iloc[0]
    assert row.contamination_status == "CLEAN_RAW_COUNTERFACTUAL"
    assert bool(row.rerun_required)


def test_winner_attribution_uses_clean_return() -> None:
    row = _dependency_audit().loc[lambda frame: frame.stage.eq("winner attribution")].iloc[0]
    assert row.contamination_status == "CLEAN_RAW_COUNTERFACTUAL"


def test_vintage_attribution_uses_clean_return() -> None:
    row = _dependency_audit().loc[lambda frame: frame.stage.eq("vintage attribution")].iloc[0]
    assert row.rerun_required


def test_impossible_cagr_is_rejected_by_arithmetic_envelope() -> None:
    source = Path(resume.__file__).read_text(encoding="utf-8")
    assert "PRICE_LINEAGE_SANITY_FAILURE" in source
    assert "CAGR >" not in source and "cagr >" not in source
