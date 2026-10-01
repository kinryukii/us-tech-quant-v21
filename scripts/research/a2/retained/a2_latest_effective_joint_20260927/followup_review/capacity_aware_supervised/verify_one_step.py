"""Trade-for-trade check of the supervised label settlement against engine."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from engine import run_replay  # noqa: E402
from one_step_label import CloseState, settle  # noqa: E402


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def close_enough(a: float, b: float) -> bool:
    return bool(np.isclose(a, b, rtol=1e-10, atol=1e-7))


def check_case(case: dict) -> dict:
    dates = pd.to_datetime(["2024-06-03", "2024-06-04", "2024-06-05"])
    price_rows = []
    for ticker, (c0, o1, c1, o2) in case["prices"].items():
        price_rows.extend([
            dict(ticker=ticker, trade_date=dates[0], open=c0, close=c0),
            dict(ticker=ticker, trade_date=dates[1], open=o1, close=c1),
            dict(ticker=ticker, trade_date=dates[2], open=o2, close=o2),
        ])
    prices = pd.DataFrame(price_rows)
    features = pd.DataFrame([
        dict(ticker=t, signal_date=dates[0], avg_dollar_volume_20d=v,
             new_buy_eligible=case["eligible"].get(t, True))
        for t, v in case["adv"].items()
    ])
    targets = case["targets"]
    state = CloseState(cash=float(case["cash"]),
                       nav=float(case["cash"] + sum(case["units"][t] * case["prices"][t][0]
                                                  for t in case["units"])),
                       units=case["units"])
    next_open = {t: p[1] for t, p in case["prices"].items()}
    following_open = {t: p[3] for t, p in case["prices"].items()}
    direct = settle(state, targets, next_open, following_open, case["adv"], case["eligible"])
    replay = run_replay(
        prices, pd.DatetimeIndex(dates), features, lambda *_: targets,
        candidate="label_engine_check", initial_cash=state.cash,
        initial_positions=state.units, cost_bps=10., capacity_fraction=.01,
        max_weight=.1, max_positions=20, max_invested=.95,
        missing_signal_policy="hold", signal_start=dates[0], signal_end=dates[0],
    )
    first, second, last = [replay.daily.iloc[i] for i in range(3)]
    assert close_enough(first.nav, state.nav), "SIGNAL_CLOSE_NAV_MISMATCH"
    for label, a, b in [
        ("pretrade_nav", direct.pretrade_nav, second.open_pretrade_nav),
        ("posttrade_nav", direct.posttrade_nav, second.open_posttrade_nav),
        ("cash", direct.cash, second.cash),
        ("following_open_nav", direct.following_open_nav, last.open_pretrade_nav),
    ]:
        assert close_enough(a, b), f"{case['name']}:{label}:{a}:{b}"
    actual = replay.trades.loc[replay.trades.execution_date.eq(dates[1])].reset_index(drop=True)
    assert len(actual) == len(direct.trades), f"{case['name']}:TRADE_COUNT"
    for expected, observed in zip(direct.trades, actual.to_dict("records")):
        for text_col in ("ticker", "side"):
            assert expected[text_col] == observed[text_col], f"{case['name']}:{text_col}"
        for col in ("notional", "index_units", "transaction_cost",
                    "index_units_before", "index_units_after"):
            assert close_enough(expected[col], observed[col]), f"{case['name']}:{col}"
    observed_units = replay.positions.loc[replay.positions.date.eq(dates[1])].set_index("ticker").index_units.to_dict()
    assert set(observed_units) == set(direct.units), f"{case['name']}:POSITION_KEYS"
    for ticker, quantity in direct.units.items():
        assert close_enough(quantity, observed_units[ticker]), f"{case['name']}:POSITION:{ticker}"
    cap_events = replay.diagnostics.loc[replay.diagnostics.code.eq("capacity_limited")]
    assert len(cap_events) == direct.capacity_limited_buys, f"{case['name']}:CAP_EVENT_COUNT"
    return dict(case=case["name"], trades=len(actual), capacity_limited_buys=len(cap_events),
                pretrade_nav=direct.pretrade_nav, after_cash=direct.cash,
                following_open_nav=direct.following_open_nav,
                max_cash_identity_error=float(replay.daily.cash_flow_identity_error.abs().max()),
                max_fee_identity_error=float(replay.daily.cost_identity_error.abs().max()))


def main() -> None:
    cases = [
        dict(name="partial_capacity_sells_before_buys", cash=50_000.,
             units={"A": 3_000., "B": 1_000.},
             prices={"A": (100., 103., 102., 107.),
                     "B": (60., 61., 62., 63.),
                     "C": (30., 31., 31.5, 32.),
                     "D": (20., 21., 20., 22.)},
             adv={"A": 500_000., "B": 10_000_000., "C": 200_000., "D": 5_000_000.},
             eligible={"A": True, "B": True, "C": True, "D": True},
             targets={"A": .05, "B": .10, "C": .10, "D": .075}),
        dict(name="blocked_ineligible_buy_and_partial_exit", cash=100_000.,
             units={"A": 2_000., "B": 500.},
             prices={"A": (100., 96., 98., 95.),
                     "B": (50., 55., 54., 53.),
                     "C": (40., 41., 42., 43.)},
             adv={"A": 1_000_000., "B": 1_000_000., "C": 1_000_000.},
             eligible={"A": True, "B": True, "C": False},
             targets={"A": .075, "B": .025, "C": .10}),
    ]
    results = [check_case(case) for case in cases]
    assert results[0]["capacity_limited_buys"] > 0, "NO_CAPACITY_BINDING_EXERCISED"
    output = dict(status="LABEL_SETTLEMENT_ENGINE_EXACT_SYNTHETIC_PASS",
                  cases=results, engine_sha256=sha(ROOT / "engine.py"),
                  one_step_sha256=sha(HERE / "one_step_label.py"),
                  fit_calls=0, test_2026_reads=0)
    path = Path("/out/TECHNICAL_CHECK.json") if Path("/out").is_dir() else HERE / "TECHNICAL_CHECK.local.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"status": output["status"], "cases": len(results),
                      "cap_events": results[0]["capacity_limited_buys"]}), flush=True)


if __name__ == "__main__":
    main()
