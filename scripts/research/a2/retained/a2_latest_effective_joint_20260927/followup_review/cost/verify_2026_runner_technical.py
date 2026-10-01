"""Synthetic/pre-2026 mapping checks; never opens a 2026 market or result file."""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import tempfile

import numpy as np
import pandas as pd

import replay_2026_sampling_v2 as runner
from engine import run_replay
from v2_policy import CoverageV2Policy


HERE = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    assert len(runner.ROSTER) == 14 and len(runner.AFFECTED) == 10 and len(runner.UNCHANGED) == 4
    assert set(runner.AFFECTED).isdisjoint(runner.UNCHANGED)
    assert set(runner.ROSTER) == set(runner.AFFECTED) | set(runner.UNCHANGED)
    assert [(key, value["cost"], value["gate"], value["version"]) for key, value in runner.SCENARIOS.items()] == [
        ("r6_v2_10", 10, "r6", "v2"), ("r6_v2_5", 5, "r6", "v2"),
        ("r6_v2_25", 25, "r6", "v2"), ("r7_original_10", 10, "r7", "original"),
        ("r7_v2_10", 10, "r7", "v2"),
    ]
    names = [f"SYN{i:03d}" for i in range(40)]
    signal = pd.Timestamp("2025-01-02")
    calendar = pd.DatetimeIndex([signal, pd.Timestamp("2025-01-03"), pd.Timestamp("2025-01-06")])
    feature = pd.DataFrame({"signal_date": signal, "ticker": names,
                            "new_buy_eligible": True,
                            "baseline_hgb": np.linspace(.08, -.08, 40)})
    for col in runner.FEATURES:
        feature[col] = .03 if "vol" in col else 30_000_000.0 if col == "avg_dollar_volume_20d" else .01
    price_rows = []
    for date_index, date in enumerate(calendar):
        for ticker_index, ticker in enumerate(names):
            px = 100.0 + ticker_index / 10 + date_index / 5
            price_rows.append(dict(ticker=ticker, trade_date=date, open=px, close=px + .1))
    prices = pd.DataFrame(price_rows)
    fit_guard = runner.forbid_fitting()
    rows = []
    for version in ("original", "v2"):
        for name in runner.ROSTER:
            actor = runner.VersionedStateful(name, version)
            if name in ("joint_hgb_lw", "joint_hgb_pca"):
                assert isinstance(actor.policy.base, CoverageV2Policy) == (version == "v2")
            result = run_replay(
                prices, calendar, feature, actor, candidate=name,
                initial_cash=1_000_000.0, cost_bps=10.0,
                max_weight=.1, max_positions=20, max_invested=.95,
                capacity_fraction=.01, missing_signal_policy="hold",
            )
            assert result.daily.date.max() < pd.Timestamp("2026-01-01")
            assert len(result.daily) == 3
            assert result.daily.cash.min() >= -1e-7
            assert result.daily.actual_name_count.max() <= 20
            assert not result.target_decisions.target_sum.dropna().gt(.9500001).any()
            assert result.daily.cost_identity_error.abs().max() < 1e-6
            assert result.daily.cash_flow_identity_error.abs().max() < 1e-6
            assert result.trades.empty or result.trades.cost_bps.eq(10).all()
            rows.append(dict(version=version, policy=name, synthetic_days=len(result.daily),
                             trades=len(result.trades), fees=float(result.trades.transaction_cost.sum()),
                             max_names=int(result.daily.actual_name_count.max())))
    assert fit_guard["attempts"] == 0

    # The price gate can block a synthetic next-open fill. The R7 adapter's
    # exact-key proof is separately verified by its own technical receipt;
    # we do not use or imitate those 2026 prices in this test.
    gated = prices.copy()
    flagged = gated.ticker.eq("SYN000") & gated.trade_date.eq(calendar[1])
    gated.loc[flagged, ["open", "close"]] = np.nan
    fixed = lambda day, weights, cash: {"SYN000": .1}
    blocked = run_replay(gated, calendar, feature, fixed, candidate="R6_SYNTHETIC_GATE",
                         cost_bps=10, capacity_fraction=.01)
    assert blocked.trades.empty
    assert blocked.diagnostics.code.eq("missing_open_buy").any()

    with tempfile.TemporaryDirectory() as temp:
        original_root, original_out = runner.ROOT, runner.OUT
        try:
            runner.ROOT = Path(temp)
            runner.OUT = Path(temp) / "evaluation_2026_sampling_v2"
            source = runner.ROOT / "evaluation_2026" / "cost_10" / "joint_mlp_10bps"
            source.mkdir(parents=True)
            pd.DataFrame({"nav": [1_000_000.0]}).to_parquet(source / "daily.parquet", index=False)
            pd.DataFrame({"ticker": ["SYN000"]}).to_parquet(source / "positions.parquet", index=False)
            link = runner.link_records("r6_v2_10", dict(cost=10, links=["joint_mlp"]))[0]
            assert link["source_directory"] == "evaluation_2026/cost_10/joint_mlp_10bps"
            assert link["source_sha256"]["daily.parquet"] == sha(source / "daily.parquet")
            assert link["source_sha256"]["positions.parquet"] == sha(source / "positions.parquet")
        finally:
            runner.ROOT, runner.OUT = original_root, original_out
    result = dict(status="PASS", synthetic_only=True, max_market_date="2025-01-06",
                  policies_tested=rows, fit_attempts=fit_guard["attempts"],
                  r6_synthetic_missing_open_gate="PASS",
                  r7_exact_gate="covered_by_separately_frozen_valuation_adapter_technical_check",
                  link_schema="PASS", no_2026_market_or_result_read=True,
                  code_sha256={str(path.relative_to(runner.ROOT)).replace("\\", "/"): sha(path)
                               for path in (runner.ROOT / "followup_review" / "cost" / "replay_2026_sampling_v2.py",
                                            runner.ROOT / "followup_review" / "cost" / "run_2026_sampling_v2_container.ps1",
                                            Path(__file__).resolve())})
    output_root = Path(os.environ.get("TECH_OUTPUT_ROOT", str(HERE)))
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "V2_2026_RUNNER_TECHNICAL_CHECK.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print("V2_2026_RUNNER_SYNTHETIC_TECHNICAL_PASS", len(rows))


if __name__ == "__main__":
    main()
