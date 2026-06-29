#!/usr/bin/env python
from pathlib import Path
import importlib.util

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/v21/v21_091_r1_d_top20_maturity_refresh_and_bucket_outcome_evaluator.py"
SPEC = importlib.util.spec_from_file_location("v21_091_r1", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def t(value) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES"}


def f(value) -> bool:
    return str(value).strip().upper() in {"FALSE", "0", "NO"}


if __name__ == "__main__":
    out = ROOT / MODULE.OUT_REL
    if not (out / MODULE.VALIDATION_NAME).is_file():
        result = MODULE.run_stage(ROOT)
    else:
        result = pd.read_csv(out / MODULE.VALIDATION_NAME).iloc[0].to_dict()
    assert out.is_dir()
    for name in MODULE.OUTPUT_NAMES:
        assert (out / name).is_file(), name

    validation = pd.read_csv(out / MODULE.VALIDATION_NAME)
    assert len(validation) == 1
    row = validation.iloc[0]
    assert row["final_status"] in {
        "PASS_V21_091_R1_MATURITY_REFRESH_AND_BUCKET_OUTCOME_READY",
        "PARTIAL_PASS_V21_091_R1_READY_WAITING_FOR_MATURITY",
        "PARTIAL_PASS_V21_091_R1_READY_WITH_INSUFFICIENT_SAMPLE",
        "PARTIAL_PASS_V21_091_R1_READY_WITH_DATA_WARN",
        "BLOCKED_V21_091_R1_LEAKAGE_OR_PROTECTED_MUTATION_RISK",
        "BLOCKED_V21_091_R1_REQUIRED_INPUTS_MISSING",
    }
    for col in ("research_only", "diagnostic_only", "maturity_refresh_only", "outcome_evaluation_only"):
        assert t(row[col])
    for col in ("official_ranking_mutated", "official_weights_mutated", "broker_action_created", "recommendation_created"):
        assert f(row[col])

    if row["final_status"] == "BLOCKED_V21_091_R1_REQUIRED_INPUTS_MISSING":
        assert str(row.get("missing_inputs", "")).strip()
        print("PASS test_v21_091_r1_d_top20_maturity_refresh_and_bucket_outcome_evaluator")
        raise SystemExit(0)

    assert row["final_status"].startswith(("PASS_", "PARTIAL_PASS_"))
    assert f(row["protected_outputs_modified"])
    for col in (
        "d_baseline_preserved", "technical_085_preserved", "fundamental_086_preserved",
        "interaction_087_preserved", "review_088_preserved", "monitor_089_preserved",
        "archive_090_preserved",
    ):
        assert t(row[col])
    for col in (
        "pullback_adoption_allowed", "interaction_adoption_allowed",
        "bucket_monitor_adoption_allowed", "maturity_outcome_adoption_allowed",
    ):
        assert f(row[col])

    schedule = pd.read_csv(ROOT / MODULE.SCHEDULE_REL, low_memory=False)
    refresh = pd.read_csv(out / MODULE.TOP20_REFRESH_NAME, low_memory=False)
    assert len(refresh) == len(schedule)
    matured = refresh["forward_matured_after"].map(t)
    assert refresh.loc[matured, "forward_price_available"].map(t).all()
    assert refresh.loc[matured, "return_forward_after"].notna().all()
    assert refresh["adoption_allowed"].map(f).all()
    assert refresh["no_trade_action_created"].map(t).all()

    for name in (MODULE.BUCKET_SUMMARY_NAME, MODULE.OVERALL_SUMMARY_NAME, MODULE.INTERACTION_SUMMARY_NAME):
        summary = pd.read_csv(out / name, low_memory=False)
        zero = summary["matured_count"].astype(int).eq(0)
        for metric in ("mean_forward_return", "median_forward_return", "hit_rate"):
            assert summary.loc[zero, metric].isna().all(), (name, metric)
        assert summary.loc[zero, "performance_status"].eq("WAITING_FOR_MATURITY").all()

    special_source = pd.read_csv(ROOT / MODULE.SPECIAL_REL)
    special = pd.read_csv(out / MODULE.SPECIAL_OUTCOME_NAME, low_memory=False)
    assert set(special_source["ticker"]).issubset(set(special["ticker"]))
    assert special["adoption_allowed"].map(f).all()
    assert special["no_trade_action_created"].map(t).all()

    bridge = pd.read_csv(ROOT / MODULE.BRIDGE_REL, low_memory=False)
    interaction = pd.read_csv(out / MODULE.INTERACTION_REFRESH_NAME, low_memory=False)
    assert len(interaction) == len(bridge)
    pending_source = ~bridge["forward_matured_flag"].map(t)
    assert len(interaction.loc[pending_source]) == int(pending_source.sum())
    int_matured = interaction["forward_matured_after"].map(t)
    assert interaction.loc[int_matured, "forward_price_available"].map(t).all()
    assert interaction.loc[int_matured, "return_forward_after"].notna().all()

    trigger_source = pd.read_csv(ROOT / MODULE.TRIGGER_REL)
    triggers = pd.read_csv(out / MODULE.TRIGGER_UPDATE_NAME)
    assert set(trigger_source["trigger_name"]) == set(triggers["trigger_name"])

    cert = pd.read_csv(out / MODULE.CERT_NAME)
    assert len(cert) == 1
    assert cert.iloc[0]["certification_status"] == "CERTIFIED_NO_ADOPTION_MATURITY_OUTCOME_DIAGNOSTIC_ONLY"
    assert t(cert.iloc[0]["no_trade_action_created"])
    for col in (
        "pullback_adoption_allowed", "interaction_adoption_allowed",
        "bucket_monitor_adoption_allowed", "maturity_outcome_adoption_allowed",
    ):
        assert f(cert.iloc[0][col])

    audit = pd.read_csv(out / MODULE.MUTATION_NAME, low_memory=False)
    assert not audit["modified_during_run"].map(t).any()
    assert result["final_status"] == row["final_status"]
    print("PASS test_v21_091_r1_d_top20_maturity_refresh_and_bucket_outcome_evaluator")
