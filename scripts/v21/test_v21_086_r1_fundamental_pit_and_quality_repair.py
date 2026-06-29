#!/usr/bin/env python
from pathlib import Path
import importlib.util

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/v21/v21_086_r1_fundamental_pit_and_quality_repair.py"
SPEC = importlib.util.spec_from_file_location("v21_086_r1", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def is_true(value) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES"}


def is_false(value) -> bool:
    return str(value).strip().upper() in {"FALSE", "0", "NO"}


if __name__ == "__main__":
    out = ROOT / MODULE.OUT_REL
    if not (out / MODULE.VALIDATION_NAME).is_file():
        result = MODULE.run_stage(ROOT)
    else:
        result = pd.read_csv(out / MODULE.VALIDATION_NAME).iloc[0].to_dict()
    assert out.is_dir()
    required = [
        MODULE.SOURCE_INV_NAME, MODULE.PANEL_NAME, MODULE.PIT_REPORT_NAME,
        MODULE.COVERAGE_NAME, MODULE.FORWARD_NAME, MODULE.CORR_NAME,
        MODULE.REDUNDANT_NAME, MODULE.ABLATION_NAME, MODULE.OVERLAY_NAME,
        MODULE.VALIDATION_NAME,
    ]
    if (ROOT / MODULE.TECH085_REL).exists():
        required.append(MODULE.CROSS_NAME)
    for name in required:
        assert (out / name).is_file(), name

    validation = pd.read_csv(out / MODULE.VALIDATION_NAME)
    assert len(validation) == 1
    row = validation.iloc[0]
    assert str(row["final_status"]).startswith(("PASS_", "PARTIAL_PASS_", "BLOCKED_V21_086_R1_NO_USABLE_FUNDAMENTAL_SOURCE")), row["final_status"]
    assert is_true(row["research_only"])
    assert is_true(row["diagnostic_only"])
    assert is_false(row["official_ranking_mutated"])
    assert is_false(row["official_weights_mutated"])
    assert is_false(row["broker_action_created"])
    assert is_false(row["protected_outputs_modified"])
    assert is_true(row["d_baseline_preserved"])
    assert is_true(row["technical_085_preserved"])

    panel = pd.read_csv(out / MODULE.PANEL_NAME, low_memory=False)
    inventory = pd.read_csv(out / MODULE.SOURCE_INV_NAME)
    if str(row["final_status"]) == "BLOCKED_V21_086_R1_NO_USABLE_FUNDAMENTAL_SOURCE":
        assert panel.empty
        assert int(row["pit_usable_source_count"]) == 0
        print("PASS test_v21_086_r1_fundamental_pit_and_quality_repair")
        raise SystemExit(0)

    assert not panel.empty
    assert int(row["pit_usable_source_count"]) >= 1
    assert inventory["source_path"].astype(str).str.contains("FUNDAMENTAL", case=False).any()
    assert not panel.duplicated(["ticker", "as_of_date"]).any()
    assert (pd.to_datetime(panel["fundamental_available_date_used"]) <= pd.to_datetime(panel["as_of_date"])).all()
    if "fiscal_period_end_date" in panel.columns:
        fpe = pd.to_datetime(panel["fiscal_period_end_date"], errors="coerce")
        avail = pd.to_datetime(panel["fundamental_available_date_used"], errors="coerce")
        direct = fpe.notna() & fpe.eq(avail) & ~panel["pit_certification_level"].eq("CONSERVATIVE_LAG_ONLY")
        assert not direct.any()

    forward = pd.read_csv(out / MODULE.FORWARD_NAME)
    for window in (5, 10, 20):
        max_matured = int(panel[f"forward_{window}d_matured"].map(is_true).sum())
        sub = forward[forward["forward_window"].eq(f"{window}D")]
        if not sub.empty:
            assert (sub["matured_count"] <= max_matured).all()
        assert int(row[f"pending_{window}d_count"]) + int(row[f"matured_{window}d_count"]) == len(panel)

    bool_cols = MODULE.bool_cols(panel)
    for col in bool_cols:
        values = set(panel[col].dropna().astype(str).str.upper().unique())
        assert values.issubset({"TRUE", "FALSE"}), (col, values)

    corr = pd.read_csv(out / MODULE.CORR_NAME)
    if not corr.empty:
        assert "signal_name" in corr.columns
        assert len(corr) == len(corr.columns) - 1

    overlay = pd.read_csv(out / MODULE.OVERLAY_NAME)
    assert len(overlay) == 20
    assert overlay["D rank"].is_monotonic_increasing
    assert overlay["D rank"].tolist() == sorted(overlay["D rank"].tolist())
    assert overlay["no_trade_action_created"].map(is_true).all()

    if (out / MODULE.CROSS_NAME).is_file():
        cross = pd.read_csv(out / MODULE.CROSS_NAME, nrows=100)
        assert "combined_diagnostic_label" in cross.columns

    forbidden_new_files = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        lower = path.as_posix().lower()
        if "outputs/v21/diagnostics/v21_086_r1" in lower:
            continue
        if "v21_086" in lower and ("broker" in lower or "official" in lower):
            forbidden_new_files.append(path)
    assert not forbidden_new_files, forbidden_new_files[:5]
    assert result["final_status"] == row["final_status"]
    print("PASS test_v21_086_r1_fundamental_pit_and_quality_repair")
