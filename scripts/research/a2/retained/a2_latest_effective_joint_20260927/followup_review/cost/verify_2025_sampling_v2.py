"""Independent, read-only checks of the versioned 2025 account replay."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "evaluation_2025_sampling_v2"
HERE = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    freeze = json.loads((OUT / "PRE_REPLAY_FREEZE.json").read_text(encoding="utf-8"))
    complete = json.loads((OUT / "COMPLETE.json").read_text(encoding="utf-8"))
    comparison = pd.read_csv(OUT / "comparison.csv")
    assert complete["evaluations"] == len(freeze["policies"]) == 8
    assert complete["fit_guard_attempts"] == 0 and complete["test_2026_predictions"] == 0
    assert comparison.policy.tolist() == freeze["policies"]
    for name, old_hash in freeze["original_2025_result_sha256"].items():
        assert sha(ROOT / "evaluation_2025" / name) == old_hash
    for record in freeze["validation_models"].values():
        frozen_path = record["path"]
        path = (ROOT / frozen_path.removeprefix("/joint/")) if frozen_path.startswith("/joint/") else Path(frozen_path)
        assert sha(path) == record["sha256"]
    summaries = []
    source_hashes = {}
    for name in freeze["policies"]:
        folder = OUT / f"{name}_10bps"
        files = {key: folder / f"{key}.parquet" for key in
                 ("daily", "trades", "positions", "target_decisions", "diagnostics")}
        for path in files.values():
            source_hashes[str(path.relative_to(ROOT))] = sha(path)
        daily = pd.read_parquet(files["daily"])
        trades = pd.read_parquet(files["trades"])
        positions = pd.read_parquet(files["positions"])
        decisions = pd.read_parquet(files["target_decisions"])
        diagnostics = pd.read_parquet(files["diagnostics"])
        assert len(daily) == 250 and daily.date.max() < pd.Timestamp("2026-01-01")
        assert not daily.nav.isna().any() and daily.valuation_status.eq("certified").all()
        assert daily.actual_name_count.max() <= 20
        assert daily.cash.min() >= -1e-7
        assert trades.empty or (trades.cost_bps.eq(10).all() and
                                trades.execution_date.max() < pd.Timestamp("2026-01-01"))
        assert not decisions.target_sum.dropna().gt(.9500001).any()
        if not trades.empty:
            assert np.allclose(trades.transaction_cost.to_numpy(float),
                               trades.notional.to_numpy(float) * .001, atol=1e-7)
        assert np.allclose(daily.transaction_cost_amount.sum(), trades.transaction_cost.sum(), atol=1e-6)
        assert daily.cash_flow_identity_error.abs().max() < 1e-6
        assert daily.cost_identity_error.abs().max() < 1e-6
        assert daily.open_self_finance_error.abs().max() < 1e-6
        buys = trades.loc[trades.side.eq("BUY")]
        enforce = buys.capacity_enforced.astype(bool)
        assert not (buys.loc[enforce, "notional"] >
                    buys.loc[enforce, "capacity_adv"] * .01 + 1e-6).any()
        stats = Counter(trades.action.astype(str))
        codes = Counter(diagnostics.code.astype(str))
        row = comparison.loc[comparison.policy.eq(name)].iloc[0]
        assert abs(row.fee_amount - trades.transaction_cost.sum()) < 1e-5
        assert int(row.trades) == len(trades)
        summaries.append(dict(
            policy=name, days=len(daily), terminal_nav=float(daily.nav.iloc[-1]),
            terminal_return=float(daily.nav.iloc[-1] / 1_000_000 - 1),
            fees=float(trades.transaction_cost.sum()), trades=len(trades),
            buy=int((trades.side == "BUY").sum()), sell=int((trades.side == "SELL").sum()),
            entry=int(stats["BUY"]), increase=int(stats["INCREASE"]),
            reduce=int(stats["REDUCE"]), exit=int(stats["EXIT"]),
            capacity_limited_events=int(codes["capacity_limited"]),
            min_cash=float(daily.cash.min()), max_holdings=int(daily.actual_name_count.max()),
            max_abs_fee_error=float(daily.cost_identity_error.abs().max()),
            max_abs_cash_error=float(daily.cash_flow_identity_error.abs().max()),
            max_abs_open_self_finance_error=float(daily.open_self_finance_error.abs().max()),
            position_rows=len(positions),
        ))
    result = dict(status="PASS", scope="joint 2025 sampling-v2 eight-policy replay only",
                  no_new_fit=True, no_2026_read_or_inference=True,
                  source_sha256=source_hashes, policies=summaries,
                  full_path_nav_valid=True,
                  metric_nan_filter_caveat_not_triggered=True)
    (HERE / "V2_2025_VERIFICATION.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print("V2_2025_VERIFICATION_PASS", len(summaries))


if __name__ == "__main__":
    main()
