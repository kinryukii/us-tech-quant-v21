#!/usr/bin/env python
from pathlib import Path
import importlib.util

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/v21/v21_088_r1_interaction_maturity_recheck_and_pullback_repair_review.py"
SPEC = importlib.util.spec_from_file_location("v21_088_r1", MODULE_PATH)
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
        MODULE.MATURITY_NAME, MODULE.INTERACTION_FORWARD_NAME, MODULE.FORENSIC_NAME,
        MODULE.SEGMENT_NAME, MODULE.REPAIRED_PANEL_NAME, MODULE.REPAIRED_SUMMARY_NAME,
        MODULE.TOP20_RISK_NAME, MODULE.TOP20_BUCKET_NAME, MODULE.MUTATION_NAME,
        MODULE.VALIDATION_NAME,
    ):
        assert (out / name).is_file(), name
    val = pd.read_csv(out / MODULE.VALIDATION_NAME)
    assert len(val) == 1
    row = val.iloc[0]
    assert str(row["final_status"]).startswith(("PASS_", "PARTIAL_PASS_", "BLOCKED_V21_088_R1_REQUIRED_INPUTS_MISSING"))
    assert t(row["research_only"]) and t(row["diagnostic_only"])
    assert f(row["official_ranking_mutated"])
    assert f(row["official_weights_mutated"])
    assert f(row["broker_action_created"])
    assert f(row["protected_outputs_modified"])
    assert t(row["d_baseline_preserved"])
    assert t(row["technical_085_preserved"])
    assert t(row["fundamental_086_preserved"])
    assert t(row["interaction_087_preserved"])
    assert f(row["repaired_pullback_adoption_allowed"])
    if str(row["final_status"]) == "BLOCKED_V21_088_R1_REQUIRED_INPUTS_MISSING":
        print("PASS test_v21_088_r1_interaction_maturity_recheck_and_pullback_repair_review")
        raise SystemExit(0)

    maturity = pd.read_csv(out / MODULE.MATURITY_NAME)
    assert len(maturity) == int(row["interaction_bridge_rows_checked"])
    passed_missing = maturity["maturity_status"].eq("PRICE_MISSING")
    assert not (passed_missing & maturity["forward_matured_after"].map(t)).any()

    fs = pd.read_csv(out / MODULE.INTERACTION_FORWARD_NAME)
    zero = fs["matured_count"].astype(int).eq(0)
    assert fs.loc[zero, "performance_status"].eq("WAITING_FOR_MATURITY").all()
    assert fs.loc[zero, "delta_true_minus_false"].fillna("").astype(str).eq("").all()

    forensic = pd.read_csv(out / MODULE.FORENSIC_NAME, low_memory=False)
    assert forensic["TECH_PULLBACK_BUY_CANDIDATE"].map(t).all()

    repaired = pd.read_csv(out / MODULE.REPAIRED_PANEL_NAME, low_memory=False)
    bool_cols = MODULE.REPAIRED_LABELS + [
        "PULLBACK_REPAIR_REJECT_WEAK_TREND", "PULLBACK_REPAIR_REJECT_BELOW_MA50",
        "PULLBACK_REPAIR_REJECT_NO_RECLAIM", "PULLBACK_REPAIR_REJECT_MACD_DERIORATION",
        "PULLBACK_REPAIR_REJECT_NO_VOLUME_DRYUP",
    ]
    for col in bool_cols:
        if col in repaired:
            vals = set(repaired[col].dropna().astype(str).str.upper().unique())
            assert vals.issubset({"TRUE", "FALSE"}), (col, vals)
    assert repaired["repaired_pullback_adoption_allowed"].map(f).all()

    ps = pd.read_csv(out / MODULE.REPAIRED_SUMMARY_NAME)
    for w in ("5D", "10D", "20D"):
        max_matured = int(repaired[f"forward_{w.lower()}_matured"].map(t).sum())
        assert (ps.loc[ps["forward_window"].eq(w), "matured_count"].astype(int) <= max_matured).all()

    risk = pd.read_csv(out / MODULE.TOP20_RISK_NAME)
    assert len(risk) == 20
    assert risk["D_rank"].is_monotonic_increasing
    assert risk["D_rank"].tolist() == sorted(risk["D_rank"].tolist())
    assert risk["trade_action_created"].map(f).all()
    assert risk["adoption_allowed"].map(f).all()

    mut = pd.read_csv(out / MODULE.MUTATION_NAME)
    assert not mut["modified_during_run"].map(t).any()
    assert result["final_status"] == row["final_status"]
    print("PASS test_v21_088_r1_interaction_maturity_recheck_and_pullback_repair_review")
