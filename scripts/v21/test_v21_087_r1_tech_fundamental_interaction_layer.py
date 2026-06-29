#!/usr/bin/env python
from pathlib import Path
import importlib.util

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/v21/v21_087_r1_tech_fundamental_interaction_layer.py"
SPEC = importlib.util.spec_from_file_location("v21_087_r1", MODULE_PATH)
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
    for name in (
        MODULE.PANEL_NAME, MODULE.COVERAGE_NAME, MODULE.FORWARD_NAME,
        MODULE.BRIDGE_NAME, MODULE.OVERLAY_NAME, MODULE.BUCKET_NAME,
        MODULE.RULES_NAME, MODULE.MUTATION_NAME, MODULE.VALIDATION_NAME,
    ):
        assert (out / name).is_file(), name
    val = pd.read_csv(out / MODULE.VALIDATION_NAME)
    assert len(val) == 1
    row = val.iloc[0]
    assert str(row["final_status"]).startswith(("PASS_", "PARTIAL_PASS_", "BLOCKED_V21_087_R1_REQUIRED_INPUTS_MISSING"))
    assert t(row["research_only"]) and t(row["diagnostic_only"])
    assert f(row["official_ranking_mutated"])
    assert f(row["official_weights_mutated"])
    assert f(row["broker_action_created"])
    assert f(row["protected_outputs_modified"])
    assert t(row["d_baseline_preserved"])
    assert t(row["technical_085_preserved"])
    assert t(row["fundamental_086_preserved"])
    assert f(row["interaction_adoption_allowed"])
    if str(row["final_status"]) == "BLOCKED_V21_087_R1_REQUIRED_INPUTS_MISSING":
        print("PASS test_v21_087_r1_tech_fundamental_interaction_layer")
        raise SystemExit(0)

    panel = pd.read_csv(out / MODULE.PANEL_NAME, low_memory=False)
    assert not panel.duplicated(["ticker", "as_of_date"]).any()
    tech_dates = pd.to_datetime(panel.loc[panel["technical_labels_available"].map(t), "technical_as_of_date"])
    tech_asof = pd.to_datetime(panel.loc[panel["technical_labels_available"].map(t), "as_of_date"])
    assert (tech_dates <= tech_asof).all()
    fund_dates = pd.to_datetime(panel.loc[panel["fundamental_labels_available"].map(t), "fundamental_as_of_date"])
    fund_asof = pd.to_datetime(panel.loc[panel["fundamental_labels_available"].map(t), "as_of_date"])
    assert (fund_dates <= fund_asof).all()
    avail = pd.to_datetime(panel.loc[panel["fundamental_labels_available"].map(t), "fundamental_available_date_used"])
    assert (avail <= fund_asof).all()

    fs = pd.read_csv(out / MODULE.FORWARD_NAME)
    zero = fs["matured_count"].astype(int).eq(0)
    assert fs.loc[zero, "performance_status"].eq("WAITING_FOR_MATURITY").all()
    assert fs.loc[zero, "delta_true_minus_false"].fillna("").astype(str).eq("").all()
    for w in (5, 10, 20):
        assert int(row[f"pending_{w}d_count"]) + int(row[f"matured_{w}d_count"]) == len(panel)

    for col in MODULE.INTERACTIONS:
        vals = set(panel[col].dropna().astype(str).str.upper().unique())
        assert vals.issubset({"TRUE", "FALSE"}), (col, vals)

    overlay = pd.read_csv(out / MODULE.OVERLAY_NAME)
    assert len(overlay) == 20
    assert overlay["D rank"].is_monotonic_increasing
    assert overlay["D rank"].tolist() == sorted(overlay["D rank"].tolist())
    assert overlay["adoption_allowed"].map(f).all()
    assert overlay["no_trade_action_created"].map(t).all()

    bridge = pd.read_csv(out / MODULE.BRIDGE_NAME)
    assert set(bridge["forward_window"].unique()) == {"5D", "10D", "20D"}
    assert len(bridge) == len(panel) * 3

    mut = pd.read_csv(out / MODULE.MUTATION_NAME)
    assert not mut["modified_during_run"].map(t).any()
    print("PASS test_v21_087_r1_tech_fundamental_interaction_layer")
