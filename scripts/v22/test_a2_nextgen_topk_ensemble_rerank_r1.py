from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SOURCE = Path(__file__).with_name("a2_nextgen_topk_ensemble_rerank_r1.py")
SPEC = importlib.util.spec_from_file_location("a2_nextgen_topk_r1", SOURCE)
assert SPEC is not None and SPEC.loader is not None
R1 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = R1
SPEC.loader.exec_module(R1)


def tiny_panel() -> pd.DataFrame:
    rows = []
    for year, dates in ((2023, ("2023-01-03", "2023-02-01")), (2024, ("2024-01-02", "2024-02-01")), (2025, ("2025-01-02", "2025-02-03"))):
        for day_index, date in enumerate(dates):
            for rank in range(1, 61):
                score = 61.0 - rank
                rows.append({
                    "signal_date": pd.Timestamp(date), "target_end_date": pd.Timestamp(date) + pd.Timedelta(days=20),
                    "security_id": f"S{rank:03d}", "ticker": f"T{rank:03d}", "outer_fold": f"OUTER_{year}",
                    "a2_raw_score": score, "a2_raw_rank": rank, "ridge_oof_pred": score * 0.9 + day_index,
                    "xgb_oof_pred": np.sin(rank / 5.0) + year / 10000.0, "q90_oof_pred": score * 0.8,
                    "target": (score / 60.0) + np.cos(rank) * 0.01,
                })
    frame = pd.DataFrame(rows)
    for source, rank in (("a2_raw_score", "a2_rank_pct"), ("ridge_oof_pred", "ridge_rank_pct"), ("xgb_oof_pred", "xgb_rank_pct"), ("q90_oof_pred", "q90_rank_pct")):
        frame[rank] = R1.stable_rank_pct(frame, source)
    frame["r6_bad_rank_pct"] = 0.5
    frame["linear_score"] = R1.fixed_linear_score(frame, False)
    return R1.deterministic_rank(frame, "linear_score", "linear_rank")


def test_2026_plus_outcome_rejection() -> None:
    frame = pd.DataFrame({"signal_date": [pd.Timestamp("2025-12-15")], "target_end_date": [pd.Timestamp("2026-01-02")]})
    with pytest.raises(R1.ResearchContractError, match="POST_2025_OUTCOME_REJECTED"):
        R1.reject_post_2025_outcomes(frame)


def test_top60_candidate_immutability() -> None:
    panel = tiny_panel()
    frame = panel.loc[panel.signal_date.eq(pd.Timestamp("2023-01-03"))].copy()
    extra = frame.iloc[[0]].copy(); extra["security_id"] = "S061"; extra["ticker"] = "T061"; extra["a2_raw_rank"] = 61
    selected = R1.select_raw_top60(pd.concat([frame, extra], ignore_index=True))
    assert set(selected.security_id) == {f"S{i:03d}" for i in range(1, 61)}


def test_final_top20_count() -> None:
    panel = tiny_panel()
    R1.assert_selection_contract(panel, "linear_rank")
    assert panel.loc[panel.linear_rank <= 20].groupby("signal_date").size().eq(20).all()


def test_no_stock_outside_raw_top60() -> None:
    panel = tiny_panel()
    panel.loc[panel.index[0], "a2_raw_rank"] = 61
    with pytest.raises(R1.ResearchContractError, match="SELECTION_OUTSIDE_RAW_TOP60"):
        R1.assert_selection_contract(panel, "linear_rank")


def test_bad_direction_penalty() -> None:
    low = pd.DataFrame({column: [0.5] for column in R1.LINEAR_WEIGHTS})
    high = low.copy()
    low["r6_bad_rank_pct"] = 0.0; high["r6_bad_rank_pct"] = 1.0
    assert R1.fixed_linear_score(low, True).iloc[0] > R1.fixed_linear_score(high, True).iloc[0]


def test_same_date_rows_cannot_split_across_folds() -> None:
    panel = tiny_panel()
    same_date = panel.signal_date.iloc[0]
    panel.loc[panel.signal_date.eq(same_date).idxmax(), "outer_fold"] = "OUTER_2099"
    with pytest.raises(R1.ResearchContractError, match="SAME_DATE_ROWS_SPLIT_ACROSS_FOLDS"):
        R1.assert_date_fold_integrity(panel)


def test_control_exact_replay() -> None:
    _, audit = R1.reconcile_control()
    assert audit["status"] == "PASS_EXACT_OR_MACHINE_PRECISION"
    assert max(audit["max_abs_errors"].values()) <= np.finfo(float).eps


def test_deterministic_reranker_output() -> None:
    panel = tiny_panel()
    first, _ = R1.fit_meta_oof(panel, n_estimators=12)
    second, _ = R1.fit_meta_oof(panel, n_estimators=12)
    cols = ["signal_date", "ticker", "meta_score", "meta_rank"]
    pd.testing.assert_frame_equal(first[cols].reset_index(drop=True), second[cols].reset_index(drop=True), check_exact=True)


def test_portfolio_contract_unchanged_except_ranking() -> None:
    panel = tiny_panel()
    raw = R1.portfolio_signals(panel, "a2_raw_rank")
    challenger = R1.portfolio_signals(panel, "linear_rank")
    assert raw[["signal_date", "ticker", "universe_size"]].equals(challenger[["signal_date", "ticker", "universe_size"]])
    assert raw.a1_rank.equals(raw.a2_rank) and challenger.a1_rank.equals(challenger.a2_rank)
    assert R1.FINAL_TOP_N == 20 and R1.COST_BPS == 10
