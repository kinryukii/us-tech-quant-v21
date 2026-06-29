#!/usr/bin/env python
from pathlib import Path
import importlib.util

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/v21/v21_089_r1_d_top20_bucket_monitor_and_low_quality_momentum_review.py"
SPEC = importlib.util.spec_from_file_location("v21_089_r1", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def t(value) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES"}


def f(value) -> bool:
    return str(value).strip().upper() in {"FALSE", "0", "NO"}


def assert_no_adoption(frame: pd.DataFrame) -> None:
    if "adoption_allowed" in frame:
        assert frame["adoption_allowed"].map(f).all()
    if "no_trade_action_created" in frame:
        assert frame["no_trade_action_created"].map(t).all()


if __name__ == "__main__":
    out = ROOT / MODULE.OUT_REL
    if not (out / MODULE.VALIDATION_NAME).is_file():
        result = MODULE.run_stage(ROOT)
    else:
        result = pd.read_csv(out / MODULE.VALIDATION_NAME).iloc[0].to_dict()
    assert out.is_dir()
    for name in MODULE.OUTPUT_NAMES:
        assert (out / name).is_file(), name

    val = pd.read_csv(out / MODULE.VALIDATION_NAME)
    assert len(val) == 1
    row = val.iloc[0]
    allowed_statuses = {
        "PASS_V21_089_R1_D_TOP20_BUCKET_MONITOR_READY",
        "PARTIAL_PASS_V21_089_R1_D_TOP20_BUCKET_MONITOR_READY_WITH_DATA_WARN",
        "BLOCKED_V21_089_R1_LEAKAGE_OR_PROTECTED_MUTATION_RISK",
        "BLOCKED_V21_089_R1_REQUIRED_INPUTS_MISSING",
    }
    assert row["final_status"] in allowed_statuses
    assert t(row["research_only"]) and t(row["diagnostic_only"])
    assert f(row["official_ranking_mutated"])
    assert f(row["official_weights_mutated"])
    assert f(row["broker_action_created"])

    if row["final_status"] == "BLOCKED_V21_089_R1_REQUIRED_INPUTS_MISSING":
        assert str(row.get("missing_inputs", "")).strip()
        print("PASS test_v21_089_r1_d_top20_bucket_monitor_and_low_quality_momentum_review")
        raise SystemExit(0)

    assert f(row["protected_outputs_modified"])
    assert t(row["d_baseline_preserved"])
    assert t(row["technical_085_preserved"])
    assert t(row["fundamental_086_preserved"])
    assert t(row["interaction_087_preserved"])
    assert t(row["review_088_preserved"])
    assert f(row["pullback_adoption_allowed"])
    assert f(row["interaction_adoption_allowed"])
    assert row["final_status"].startswith(("PASS_", "PARTIAL_PASS_"))

    monitor = pd.read_csv(out / MODULE.MONITOR_NAME, low_memory=False)
    watch = pd.read_csv(out / MODULE.WATCHLIST_NAME, low_memory=False)
    assert len(monitor) == 20
    assert len(watch) == 20
    assert monitor["D_rank"].is_monotonic_increasing
    risk = pd.read_csv(ROOT / MODULE.RISK_REL).sort_values("D_rank")
    assert monitor["D_rank"].tolist() == risk["D_rank"].tolist()
    assert monitor["ticker"].tolist() == risk["ticker"].tolist()
    assert monitor["adoption_allowed"].map(f).all()
    assert monitor["no_trade_action_created"].map(t).all()
    assert monitor["pullback_not_adoptable_flag"].map(t).all()
    assert watch["not_a_trade_signal"].map(t).all()

    frames = {}
    for name in (
        MODULE.LOW_QUALITY_NAME, MODULE.DATA_GAP_NAME, MODULE.WAIT_NAME,
        MODULE.DAY0_NAME, MODULE.OVEREXTENDED_NAME, MODULE.WATCHLIST_NAME,
    ):
        frames[name] = pd.read_csv(out / name, low_memory=False)
        assert_no_adoption(frames[name])

    pullback = pd.read_csv(out / MODULE.PULLBACK_CONFIRM_NAME)
    assert len(pullback) == 1
    assert pullback["adoption_allowed"].map(f).all()
    assert pullback["recommended_handling"].eq("KEEP_DIAGNOSTIC_ONLY_DO_NOT_PROMOTE").all()

    day0 = frames[MODULE.DAY0_NAME]
    assert day0["day0_no_chase_reason"].str.contains("NO_CHASE").all()
    assert day0["diagnostic_interpretation"].str.upper().str.contains("NOT A BUY").all()
    assert day0["diagnostic_interpretation"].str.upper().str.contains("NOT.*CHASE", regex=True).all()
    assert day0["adoption_allowed"].map(f).all()
    assert day0["no_trade_action_created"].map(t).all()

    top20 = set(monitor["ticker"])
    checks = [
        (MODULE.LOW_QUALITY_NAME, {"TWST", "WYFI"}),
        (MODULE.DATA_GAP_NAME, {"ICHR", "VECO"}),
        (MODULE.WAIT_NAME, {"FORM", "ACLS", "SITM"}),
        (MODULE.OVEREXTENDED_NAME, {"WDC", "STX", "AMKR", "ACMR", "SNDK",
                                    "ARM", "COHU", "AMAT", "TTMI", "MKSI"}),
    ]
    for name, expected in checks:
        present_expected = expected & top20
        assert present_expected.issubset(set(frames[name]["ticker"])), (name, present_expected)

    audit = pd.read_csv(out / MODULE.MUTATION_NAME, low_memory=False)
    assert not audit["modified_during_run"].map(t).any()
    assert not audit.loc[~audit["mutation_allowed"].map(t), "modified_during_run"].map(t).any()
    assert int(row["top20_monitor_rows"]) == len(monitor)
    assert int(row["no_trade_watchlist_rows"]) == len(watch)
    assert result["final_status"] == row["final_status"]
    print("PASS test_v21_089_r1_d_top20_bucket_monitor_and_low_quality_momentum_review")
