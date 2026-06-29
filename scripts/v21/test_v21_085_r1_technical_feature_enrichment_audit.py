#!/usr/bin/env python
from pathlib import Path
import importlib.util

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/v21/v21_085_r1_technical_feature_enrichment_audit.py"
SPEC = importlib.util.spec_from_file_location("v21_085_r1", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def is_false(value) -> bool:
    return str(value).strip().upper() in {"FALSE", "0", "NO"}


def is_true(value) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES"}


if __name__ == "__main__":
    out = ROOT / MODULE.OUT_REL
    if not (out / MODULE.VALIDATION_NAME).is_file():
        result = MODULE.run_stage(ROOT)
    else:
        result = pd.read_csv(out / MODULE.VALIDATION_NAME).iloc[0].to_dict()
    assert out.is_dir()
    for name in (
        MODULE.PANEL_NAME,
        MODULE.COVERAGE_NAME,
        MODULE.FORWARD_NAME,
        MODULE.CORR_NAME,
        MODULE.REDUNDANT_NAME,
        MODULE.OVERLAY_NAME,
        MODULE.VALIDATION_NAME,
    ):
        assert (out / name).is_file(), name

    validation = pd.read_csv(out / MODULE.VALIDATION_NAME)
    assert len(validation) == 1
    row = validation.iloc[0]
    assert str(row["final_status"]).startswith(("PASS_", "PARTIAL_PASS_")), row["final_status"]
    assert is_true(row["research_only"])
    assert is_true(row["diagnostic_only"])
    assert is_false(row["official_ranking_mutated"])
    assert is_false(row["official_weights_mutated"])
    assert is_false(row["broker_action_created"])
    assert is_false(row["protected_outputs_modified"])
    assert is_true(row["d_baseline_preserved"])

    panel = pd.read_csv(out / MODULE.PANEL_NAME, low_memory=False)
    assert not panel.duplicated(["ticker", "as_of_date"]).any()
    required_cols = {
        "as_of_date", "ticker", "source_price_date", "close", "volume",
        "return_5d_forward", "return_10d_forward", "return_20d_forward",
        "forward_5d_matured", "forward_10d_matured", "forward_20d_matured",
        "rsi_14", "kdj_k", "macd_hist", "bb_width", "ma20", "ema20",
        "rs_vs_qqq_10d", "rs_vs_spy_10d", "rs_vs_soxx_10d",
        "TECH_STRONG_TREND_CONTINUATION", "TECH_WEAK_OR_NO_CONFIRMATION",
    }
    assert required_cols.issubset(panel.columns), sorted(required_cols - set(panel.columns))

    forward = pd.read_csv(out / MODULE.FORWARD_NAME)
    for window in (5, 10, 20):
        max_matured = int(panel[f"forward_{window}d_matured"].map(is_true).sum())
        sub = forward[forward["forward_window"].eq(f"{window}D")]
        assert (sub["matured_count"] <= max_matured).all()
    assert int(row["pending_5d_count"]) + int(row["matured_5d_count"]) == len(panel)
    assert int(row["pending_10d_count"]) + int(row["matured_10d_count"]) == len(panel)
    assert int(row["pending_20d_count"]) + int(row["matured_20d_count"]) == len(panel)

    bool_cols = MODULE.boolean_columns(panel)
    for col in bool_cols:
        values = set(panel[col].dropna().astype(str).str.upper().unique())
        assert values.issubset({"TRUE", "FALSE"}), (col, values)

    corr = pd.read_csv(out / MODULE.CORR_NAME)
    assert "signal_name" in corr.columns
    assert len(corr) == len(corr.columns) - 1

    overlay = pd.read_csv(out / MODULE.OVERLAY_NAME)
    assert len(overlay) == 20
    assert overlay["D rank"].is_monotonic_increasing
    assert overlay["D rank"].tolist() == sorted(overlay["D rank"].tolist())
    assert overlay["no_trade_action_created"].map(is_true).all()

    forbidden_new_files = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        lower = path.as_posix().lower()
        if "outputs/v21/diagnostics/v21_085_r1" in lower:
            continue
        if "broker" in lower and "v21_085" in lower:
            forbidden_new_files.append(path)
        if "official" in lower and "v21_085" in lower:
            forbidden_new_files.append(path)
    assert not forbidden_new_files, forbidden_new_files[:5]
    assert result["final_status"] == row["final_status"]
    print("PASS test_v21_085_r1_technical_feature_enrichment_audit")
