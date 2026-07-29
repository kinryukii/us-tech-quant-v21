from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

import v22_062pr_fast3_premarket_forward_replication_r1 as mod


def valid_pb_summary():
    return {
        "final_status": "PASS",
        "final_decision": (
            "PREMARKET_CORPORATE_ACTION_SAFE_CANDIDATE_"
            "REQUIRES_INDEPENDENT_REPLICATION"
        ),
        "v22_062p_validated": True,
        "v22_062pa_validated": True,
        "quarantined_trade_count": 0,
        "supported_exit_variants_for_replication": [
            "PREMARKET_0925"
        ],
        "full_582_partition_reread": False,
        "strategy_signal_regeneration_executed": False,
        "parameter_sweep_executed": False,
        "threshold_optimization_executed": False,
        "official_corporate_action_data_downloaded": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "next_stage": (
            "V22.062PR_FAST3_PREMARKET_INDEPENDENT_REPLICATION_R1"
        ),
    }


def synthetic_premarket(
    session_date: str = "2026-07-27",
    base: float = 100.0,
    drift: float = 0.001,
    jump_minute: int | None = None,
    jump: float = 0.0,
) -> pd.DataFrame:
    timestamp_et = pd.date_range(
        f"{session_date} 04:00",
        periods=330,
        freq="min",
        tz="America/New_York",
    )
    close = base + np.arange(330) * drift
    if jump_minute is not None:
        close[jump_minute:] += jump

    open_price = close - drift / 2.0
    high = np.maximum(
        open_price,
        close,
    ) + 0.02
    low = np.minimum(
        open_price,
        close,
    ) - 0.02

    return pd.DataFrame(
        {
            "timestamp_utc": (
                timestamp_et.tz_convert("UTC")
            ),
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(
                330,
                100.0,
            ),
        }
    )


def normalized_premarket(
    session_date: str = "2026-07-27",
    base: float = 100.0,
    drift: float = 0.001,
    jump_minute: int | None = None,
    jump: float = 0.0,
) -> pd.DataFrame:
    frame = synthetic_premarket(
        session_date,
        base,
        drift,
        jump_minute,
        jump,
    )
    normalized, _, _ = (
        mod.normalize_scale_series(frame)
    )
    return normalized


def prior(
    close: float,
) -> dict:
    return {
        "prior_close_date": "2026-07-24",
        "prior_close_timestamp_utc": pd.Timestamp(
            "2026-07-24 19:59:00+00:00"
        ),
        "prior_rth_close": close,
    }


def long_grids():
    qqq = normalized_premarket(
        base=100.0,
        drift=0.0005,
        jump_minute=130,
        jump=1.0,
    )
    soxx = normalized_premarket(
        base=200.0,
        drift=0.0008,
        jump_minute=130,
        jump=2.0,
    )
    qqq_pre, _ = mod.extract_premarket_table(
        qqq
    )
    soxx_pre, _ = mod.extract_premarket_table(
        soxx
    )
    return (
        mod.session_grid(qqq_pre),
        mod.session_grid(soxx_pre),
    )


def test_validate_pb():
    mod.validate_v22_062pb(
        valid_pb_summary()
    )


def test_validate_pb_rejects_variant():
    summary = valid_pb_summary()
    summary[
        "supported_exit_variants_for_replication"
    ] = ["FIXED_60M"]
    with pytest.raises(
        mod.ReplicationError
    ):
        mod.validate_v22_062pb(summary)


def test_spec_hash_stable():
    assert mod.spec_hash(
        mod.frozen_spec()
    ) == mod.spec_hash(
        mod.frozen_spec()
    )


def test_spec_has_cutoff():
    assert (
        mod.frozen_spec()[
            "research_cutoff_date"
        ]
        == "2026-07-24"
    )


def test_manifest_create_and_validate(
    tmp_path,
):
    summary = tmp_path / "summary.json"
    summary.write_text(
        "{}",
        encoding="utf-8",
    )
    path = tmp_path / "freeze.json"
    first = (
        mod.validate_or_create_freeze_manifest(
            path,
            summary,
        )
    )
    second = (
        mod.validate_or_create_freeze_manifest(
            path,
            summary,
        )
    )
    assert (
        first["frozen_spec_sha256"]
        == second["frozen_spec_sha256"]
    )


def test_manifest_rejects_change(
    tmp_path,
):
    summary = tmp_path / "summary.json"
    summary.write_text(
        "{}",
        encoding="utf-8",
    )
    path = tmp_path / "freeze.json"
    mod.validate_or_create_freeze_manifest(
        path,
        summary,
    )
    payload = json.loads(
        path.read_text(encoding="utf-8")
    )
    payload["frozen_spec_sha256"] = "BAD"
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    with pytest.raises(
        mod.ReplicationError
    ):
        mod.validate_or_create_freeze_manifest(
            path,
            summary,
        )


def test_symbol_month_path():
    path = (
        mod.Path("x")
        / "symbol=US.SOXL"
        / "year=2026"
        / "month=7"
        / "data.parquet"
    )
    assert mod.symbol_month_from_path(
        path
    ) == ("SOXL", "2026", "07")


def test_snap_forward_split():
    factor, error = (
        mod.snap_split_factor(10.0)
    )
    assert factor == pytest.approx(10.0)
    assert error == pytest.approx(0.0)


def test_snap_reverse_split():
    factor, _ = (
        mod.snap_split_factor(0.1)
    )
    assert factor == pytest.approx(0.1)


def test_snap_rejects_non_split():
    assert (
        mod.snap_split_factor(1.35)
        is None
    )


def test_normalize_split():
    frame = synthetic_premarket(
        base=100.0,
        drift=0.01,
    ).head(10)
    frame.loc[
        5:,
        ["open", "high", "low", "close"],
    ] /= 10.0

    normalized, recognized, unresolved = (
        mod.normalize_scale_series(frame)
    )
    assert len(recognized) == 1
    assert unresolved.empty
    assert (
        normalized.loc[
            5,
            "normalized_open",
        ]
        == pytest.approx(
            normalized.loc[4, "close"],
            rel=0.03,
        )
    )


def test_extract_premarket():
    frame = normalized_premarket()
    premarket, closes = (
        mod.extract_premarket_table(frame)
    )
    assert len(premarket) == 330
    assert closes.empty


def test_session_grid_complete():
    frame = normalized_premarket()
    premarket, _ = (
        mod.extract_premarket_table(frame)
    )
    grid = mod.session_grid(premarket)
    assert bool(
        grid["complete_session"].iloc[0]
    )
    assert bool(
        grid[
            "initial_range_complete"
        ].iloc[0]
    )


def test_prior_close():
    closes = pd.DataFrame(
        {
            "local_date": [
                "2026-07-24",
                "2026-07-27",
            ],
            "timestamp_utc": pd.to_datetime(
                [
                    "2026-07-24 19:59:00+00:00",
                    "2026-07-27 19:59:00+00:00",
                ]
            ),
            "normalized_close": [
                100.0,
                101.0,
            ],
        }
    )
    result = mod.prior_close(
        closes,
        "2026-07-27",
    )
    assert result is not None
    assert (
        result["prior_close_date"]
        == "2026-07-24"
    )


def test_long_candidate():
    qqq, soxx = long_grids()
    result, reasons = (
        mod.build_candidate(
            "2026-07-27",
            qqq,
            soxx,
            prior(99.0),
            prior(198.0),
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
        )
    )
    assert not reasons
    assert result is not None
    assert result["direction"] == "LONG"


def test_candidate_blocked_by_event():
    qqq, soxx = long_grids()
    recognized = pd.DataFrame(
        {
            "timestamp_utc": [
                pd.Timestamp(
                    "2026-07-27 11:00:00+00:00"
                )
            ]
        }
    )
    result, reasons = (
        mod.build_candidate(
            "2026-07-27",
            qqq,
            soxx,
            prior(99.0),
            prior(198.0),
            recognized,
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
        )
    )
    assert result is None
    assert any(
        "SCALE_EVENT" in reason
        for reason in reasons
    )


def test_return_from_grid():
    qqq, _ = long_grids()
    result = mod.return_from_grid(
        qqq,
        150,
    )
    assert result is not None
    assert (
        result[1]["holding_minutes"]
        == mod.EXIT_MINUTE - 150
    )


def test_profit_factor():
    assert mod.profit_factor(
        pd.Series(
            [0.02, 0.01, -0.01]
        )
    ) == pytest.approx(3.0)


def test_positive_profit_share():
    assert mod.positive_profit_share(
        pd.Series(
            [0.8, 0.1, 0.1, -0.1]
        ),
        1,
    ) == pytest.approx(0.8)


def test_maximum_drawdown():
    assert mod.maximum_drawdown(
        pd.Series(
            [0.10, -0.20, 0.10]
        )
    ) == pytest.approx(-0.20)


def test_cumulative_return():
    assert mod.cumulative_return(
        pd.Series(
            [0.10, -0.10]
        )
    ) == pytest.approx(-0.01)


def sessions(
    count: int,
    quarantined: int = 0,
) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "session_date": pd.date_range(
                "2026-07-27",
                periods=count,
                freq="B",
            ).strftime("%Y-%m-%d"),
            "session_quarantined": False,
        }
    )
    if quarantined:
        frame.loc[
            :quarantined - 1,
            "session_quarantined",
        ] = True
    return frame


def trades(
    count: int,
    value: float = 0.01,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "instrument_net_return": (
                np.full(count, value)
            ),
            "account_trade_return": (
                np.full(
                    count,
                    value * 0.20,
                )
            ),
            "selection_excess_return": (
                np.full(
                    count,
                    value / 10.0,
                )
            ),
        }
    )


def test_evaluate_insufficient():
    result = mod.evaluate_forward(
        sessions(10),
        trades(2),
    )
    assert not result[
        "interim_evaluable"
    ]
    assert "IN_PROGRESS" in result[
        "final_decision"
    ]


def test_evaluate_interim():
    result = mod.evaluate_forward(
        sessions(70),
        trades(25),
    )
    assert result[
        "interim_evaluable"
    ]
    assert not result[
        "final_evaluable"
    ]
    assert "INTERIM_ONLY" in result[
        "final_decision"
    ]


def test_evaluate_final_pass():
    alternating = np.array(
        [0.01, 0.008, -0.002]
        * 20
    )
    trade_frame = pd.DataFrame(
        {
            "instrument_net_return": (
                alternating
            ),
            "account_trade_return": (
                alternating * 0.20
            ),
            "selection_excess_return": (
                np.full(
                    len(alternating),
                    0.0005,
                )
            ),
        }
    )
    result = mod.evaluate_forward(
        sessions(130),
        trade_frame,
    )
    assert result["final_evaluable"]
    assert result[
        "forward_replication_pass"
    ]


def test_evaluate_final_fail():
    result = mod.evaluate_forward(
        sessions(130),
        trades(
            40,
            value=-0.01,
        ),
    )
    assert result["final_evaluable"]
    assert not result[
        "forward_replication_pass"
    ]
    assert result["final_decision"] == (
        "PREMARKET_0925_FORWARD_REPLICATION_FAILED"
    )


def test_default_paths():
    args = mod.parse_args(
        ["--execute"]
    )
    assert (
        "V22.062PB_FAST3"
        in args.v22_062pb_root
    )
    assert (
        "moomoo_24h_1m"
        in args.canonical_root
    )
    assert (
        "V22.062PR_FAST3"
        in args.result_dir
    )


def test_policy_constants():
    assert (
        mod.RESEARCH_CUTOFF_DATE
        == "2026-07-24"
    )
    assert (
        mod.INTERIM_MIN_COMPLETED_SESSIONS
        == 60
    )
    assert (
        mod.FINAL_MIN_COMPLETED_SESSIONS
        == 120
    )
    assert mod.FINAL_MIN_TRADES == 30
    assert mod.FIXED_ACCOUNT_WEIGHT == 0.20
