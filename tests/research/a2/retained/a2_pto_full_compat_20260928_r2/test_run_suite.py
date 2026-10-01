"""Synthetic streaming-ledger and summary integration; no evaluation data read."""
import importlib.util
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from threadpoolctl import threadpool_limits

import fast_account as common_engine
from fast_account import MarketArrays
from portfolio_policy import PortfolioPolicy
from run_suite import LedgerWriter, summarize
from shared import RISKS
from verify_ledgers import verify_folder


class RiskCache(dict):
    @property
    def files(self):
        return list(self.keys())


def synthetic_replay(folder, *, collect_ledgers, terminal_signal=False,
                     account_engine=common_engine, family="pto", last_two_signals=False):
    dates = pd.bdate_range("2025-06-02", periods=5)
    tickers = np.array(["AAA", "BBB", "CCC", "DDD"])
    opening = np.array([[100., 80., 120., 60.], [101., 80., 119., 61.],
                        [100., 82., 121., 62.], [99., 83., 120., 63.],
                        [102., 81., 123., 62.]])
    closing = opening * np.array([1.001, .999, 1.002, 1.003])[None, :]
    quality = np.zeros_like(opening, dtype=bool)
    quality[3, 3] = True
    market = MarketArrays(dates, tickers, opening, closing, quality=quality,
                          adv=np.full_like(opening, 1e8),
                          signal_mask=[True, True, True, not last_two_signals, terminal_signal])
    # Initially zero targets, then buys, mixed sales/rebalances, a stale mark,
    # and a final evaluation close. A separate test also emits terminal targets.
    mu = np.array([[-.02, -.01, -.03, -.015], [.016, .018, .020, .022],
                   [-.008, .020, .002, .018], [.016, -.006, .025, .012],
                   [.010, .016, .022, .018]])[:, None, :]
    rng = np.random.default_rng(20250928)
    correlation = np.full((4, 4), .25)
    np.fill_diagonal(correlation, 1.)
    scenarios = rng.normal(size=(32, 4)) @ np.linalg.cholesky(correlation).T
    risk = RiskCache(corr_diagonal=correlation, scenario_diagonal=scenarios,
                     corr_ledoit_wolf=correlation, scenario_ledoit_wolf=scenarios,
                     scales=np.full((5, len(RISKS), 4), .004))
    forecast = dict(stream_ids=np.array(["ridge__identity"]), mu=mu)
    methods = ["positive_equal", "mean_variance", "robust_mv", "cvar"]
    roster = pd.DataFrame([dict(path_id=method, group="ridge", fusion="identity",
                                risk="diagonal", optimizer=method, layer="pto")
                           for method in methods])
    writer = LedgerWriter(folder)
    if family == "pto":
        actor = PortfolioPolicy(roster, forecast, risk,
                                diagnostic_callback=lambda frame: writer("optimization", frame))
    else:
        from rl_control import RLRuntime
        import torch
        class SmallActor(torch.nn.Module):
            def __init__(self, logit):
                super().__init__()
                self.logit = logit
            def forward(self, observations):
                return torch.full((len(observations),), self.logit, dtype=torch.float32)
        methods = ["reinforce", "reinforce_zero", "ppo", "ppo_zero"]
        roster = pd.DataFrame([dict(path_id=method, group="rl", fusion="none",
                                   risk="implicit", optimizer=method, layer="rl_control")
                              for method in methods])
        actor = RLRuntime.__new__(RLRuntime)
        actor.stage = "validation"
        actor.feature_cube = rng.normal(size=(5, 4, 32))
        actor.models = {method: (SmallActor(logit), np.zeros(32), np.ones(32))
                        for method, logit in zip(methods, [.3, -.2, .6, -.3])}
    def policy(day, context):
        decision = actor(day, context)
        return account_engine.TargetDecision(decision.weights, decision.explicit_mask,
                                             decision.raw_evidence_id)
    try:
        with threadpool_limits(limits=1):
            replay = account_engine.run_many(market, methods, policy,
                                              collect_ledgers=collect_ledgers,
                                              ledger_callback=writer)
    finally:
        writer.close()
    return market, roster, writer, replay


def canonical_frame(frame):
    frame = frame.copy()
    for name in frame:
        if pd.api.types.is_datetime64_any_dtype(frame[name].dtype):
            frame[name] = frame[name].astype("datetime64[ns]")
    return frame


def test_mixed_real_optimizers_stream_exact_ledgers_and_account_for_all_fees(tmp_path):
    market, roster, writer, replay = synthetic_replay(tmp_path, collect_ledgers=True)
    for name in ["daily", "positions", "orders", "fills", "execution_results", "contexts"]:
        restored = pd.read_parquet(tmp_path / f"{name}.parquet")
        expected = getattr(replay, name)
        assert writer.counts[name] == len(expected)
        pd.testing.assert_frame_equal(canonical_frame(restored), canonical_frame(expected),
                                      check_exact=True)
    daily = pd.concat(writer.daily, ignore_index=True)
    assert len(daily) == 5 * len(roster)
    assert daily[daily.date.eq(market.dates[0])].transaction_cost_amount.eq(0).all()
    assert daily.transaction_cost_amount.gt(0).any()
    assert daily.certified_nav.isna().any() and daily.certified_nav.notna().any()
    assert replay.fills.side.eq("BUY").any() and replay.fills.side.eq("SELL").any()
    diagnostics = pd.read_parquet(tmp_path / "optimization.parquet")
    assert len(diagnostics) == 4 * len(roster)
    assert set(diagnostics.optimizer_component) == set(roster.optimizer)
    assert diagnostics.cvar_eta[diagnostics.optimizer_component.eq("cvar")].notna().all()
    assert diagnostics.cvar_eta[diagnostics.optimizer_component.ne("cvar")].isna().all()
    positive = diagnostics[diagnostics.optimizer_component.eq("positive_equal")]
    assert positive.gradient_evaluations.eq(0).all()
    assert positive.exact_fixed_point.eq(False).all()
    assert diagnostics.selected_tickers.map(len).eq(4).all()
    assert diagnostics.component_target_weights.map(len).eq(4).all()
    solver = writer.solver_summary()
    assert solver.decisions.sum() == len(diagnostics)
    summary = summarize(daily, roster, 2025, solver).set_index("path_id")
    fill_fees = replay.fills.groupby("path_id").transaction_cost.sum().reindex(summary.index, fill_value=0.)
    np.testing.assert_allclose(summary.total_fees, fill_fees, rtol=0, atol=1e-10)
    assert summary.total_fees.sum() == daily.transaction_cost_amount.sum()
    assert summary.days.eq(5).all()
    for method in summary.index:
        limited = int(diagnostics[diagnostics.path_id.eq(method)].status.eq("ITERATION_LIMIT").sum())
        assert summary.loc[method, "optimization_iteration_limit_decisions"] == limited
        assert summary.loc[method, "research_status"] == (
            "REPLAY_COMPLETE_WITH_APPROXIMATE_SOLVES" if limited else "REPLAY_COMPLETE")
    independent = verify_folder(tmp_path, market=market, metadata=replay.metadata)
    assert independent["status"] == "PASS", independent
    assert independent["mismatch_count"] == 0


def test_terminal_signal_streams_unexecuted_targets_with_dated_nulls(tmp_path):
    market, roster, writer, replay = synthetic_replay(tmp_path, collect_ledgers=True,
                                                     terminal_signal=True)
    final = replay.orders[replay.orders.signal_date.eq(market.dates[-1])]
    assert len(final) and final.execution_date.isna().all()
    assert final.status.eq("no_next_session").all()
    restored = pd.read_parquet(tmp_path / "orders.parquet")
    pd.testing.assert_frame_equal(canonical_frame(restored), canonical_frame(replay.orders),
                                  check_exact=True)
    diagnostics = pd.read_parquet(tmp_path / "optimization.parquet")
    assert len(diagnostics) == 5 * len(roster)
    assert writer.counts["orders"] == len(replay.orders)


def test_no_collection_streaming_has_identical_saved_state_and_summary(tmp_path):
    collected = tmp_path / "collected"
    streamed = tmp_path / "streamed"
    _, roster, writer_a, replay_a = synthetic_replay(collected, collect_ledgers=True)
    _, _, writer_b, replay_b = synthetic_replay(streamed, collect_ledgers=False)
    np.testing.assert_array_equal(replay_a.final_units, replay_b.final_units)
    np.testing.assert_array_equal(replay_a.final_cash, replay_b.final_cash)
    assert replay_a.audit == replay_b.audit
    assert replay_b.daily.empty and replay_b.fills.empty
    assert writer_a.counts == writer_b.counts
    for name in writer_a.counts:
        assert pq.read_table(collected / f"{name}.parquet").equals(
            pq.read_table(streamed / f"{name}.parquet"))
    summary_a = summarize(pd.concat(writer_a.daily), roster, 2025, writer_a.solver_summary())
    summary_b = summarize(pd.concat(writer_b.daily), roster, 2025, writer_b.solver_summary())
    pd.testing.assert_frame_equal(summary_a, summary_b, check_exact=True)


def test_writer_preserves_declared_numeric_schema_from_zero_nan_to_values(tmp_path):
    writer = LedgerWriter(tmp_path)
    first = pd.DataFrame(dict(path_id=["synthetic"], value=np.array([np.nan]),
                              fee=np.array([0.]), count=np.array([0], dtype=np.int64),
                              flag=np.array([False])))
    second = pd.DataFrame(dict(path_id=["synthetic"], value=np.array([.023]),
                               fee=np.array([3.2]), count=np.array([4], dtype=np.int64),
                               flag=np.array([True])))
    try:
        writer("numeric_probe", first)
        writer("numeric_probe", second)
    finally:
        writer.close()
    table = pq.read_table(tmp_path / "numeric_probe.parquet")
    assert table.schema.field("value").type == pa.float64()
    assert table.schema.field("fee").type == pa.float64()
    assert table.schema.field("count").type == pa.int64()
    assert table.schema.field("flag").type == pa.bool_()
    pd.testing.assert_frame_equal(table.to_pandas(), pd.concat([first, second], ignore_index=True),
                                  check_exact=True)


def time_unit_compatibility_receipt(destination=None):
    """Explicit old/new proof for the single terminal timestamp dtype fix."""
    import hashlib
    import json
    import tempfile
    from datetime import datetime, timezone
    root = Path(__file__).resolve().parent
    before_path = root / "audits/engine_before_time_unit_85abc.py"
    before_bytes = before_path.read_bytes()
    after_bytes = (root / "fast_account.py").read_bytes()
    expected = "85abc6cfb45b5a389f0e4714543e85635b154940e77d77b31ce54578e65e02b5"
    assert hashlib.sha256(before_bytes).hexdigest() == expected
    old_text = 'else np.datetime64("NaT"),len(ri))'
    new_text = 'else np.datetime64("NaT","ns"),len(ri))'
    assert before_bytes.count(old_text.encode()) == 1
    assert before_bytes.replace(old_text.encode(), new_text.encode(), 1) == after_bytes
    module_name = "engine_before_terminal_time_unit"
    spec = importlib.util.spec_from_file_location(module_name, before_path)
    original = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = original
    spec.loader.exec_module(original)
    proof = {}
    with tempfile.TemporaryDirectory(prefix="pto-time-unit-proof-") as temporary:
        for family in ["pto", "rl"]:
            folder = Path(temporary) / family
            _, _, _, older = synthetic_replay(folder / "before", collect_ledgers=True,
                                              account_engine=original, family=family,
                                              last_two_signals=True)
            _, _, _, newer = synthetic_replay(folder / "after", collect_ledgers=True,
                                              family=family, last_two_signals=True)
            tables = {}
            for name in ["daily", "positions", "orders", "fills", "execution_results",
                         "contexts", "operational_actions"]:
                before_frame, after_frame = getattr(older, name), getattr(newer, name)
                pd.testing.assert_frame_equal(canonical_frame(before_frame),
                                              canonical_frame(after_frame), check_exact=True)
                for column in before_frame.select_dtypes(include=[np.floating]).columns:
                    np.testing.assert_array_equal(before_frame[column].to_numpy().view(np.uint64),
                                                  after_frame[column].to_numpy().view(np.uint64))
                tables[name] = dict(rows=len(before_frame), all_values_exact_equal=True,
                                    float64_bits_equal=True, datetime_unit_normalization_only=True)
            np.testing.assert_array_equal(older.final_cash.view(np.uint64), newer.final_cash.view(np.uint64))
            np.testing.assert_array_equal(older.final_units.view(np.uint64), newer.final_units.view(np.uint64))
            assert older.audit == newer.audit and older.metadata == newer.metadata
            proof[family] = dict(paths=list(newer.metadata["path_ids"]), tables=tables,
                                 final_cash_and_units_bits_equal=True,
                                 audit_and_metadata_exact_equal=True,
                                 last_two_signal_sessions_disabled=True,
                                 actors="synthetic constant small actors; no real weights read" if family=="rl" else "four fixed real optimization APIs")
        try:
            synthetic_replay(Path(temporary) / "old_terminal", collect_ledgers=True,
                             account_engine=original, terminal_signal=True)
        except TypeError as error:
            assert "datetime64 values must have a unit specified" in str(error)
            old_terminal_error = str(error)
        else:
            raise AssertionError("OLD_TERMINAL_STREAMING_FAILURE_NOT_REPRODUCED")
        _, _, _, terminal = synthetic_replay(Path(temporary) / "new_terminal", collect_ledgers=True,
                                             terminal_signal=True)
        final_orders = terminal.orders[terminal.orders.signal_date.eq(pd.Timestamp("2025-06-06"))]
        assert len(final_orders) and final_orders.execution_date.isna().all()
    assert (root / "fast_account.py").read_bytes() == after_bytes
    receipt = dict(status="PASS", scope="single missing-next-session execution NaT dtype unit only",
                   checked_at_utc=datetime.now(timezone.utc).isoformat(), synthetic_only=True,
                   production_or_2026_outcomes_read=False, before_sha256=expected,
                   after_sha256=hashlib.sha256(after_bytes).hexdigest(),
                   before_source_snapshot=str(before_path.resolve()),
                   after_source_path=str((root / "fast_account.py").resolve()),
                   single_byte_replacement_confirmed=True, fixed_methods_parameters_seeds_changed=False,
                   compatibility_proof=proof,
                   terminal_branch=dict(before_status="TYPE_ERROR", before_error=old_terminal_error,
                                        after_status="PASS", saved_terminal_orders=len(final_orders),
                                        terminal_execution_date_is_missing=True),
                   branch_reachability=dict(training="rl_control.prepare_market explicitly disables last two session signals",
                                            formal_replay="market_runtime uses 2025 signal cutoff 2025-12-29 and 2026 cutoff 2026-09-22; calendars retain later sessions",
                                            training_binding="original e655f3c6 source bindings and receipts remain unchanged; this supplements the existing e655-to-85abc label-cache proof"),
                   reproduce="python -B test_run_suite.py --time-unit-compatibility")
    target = Path(destination) if destination is not None else root / "audits/ACCOUNT_TIME_UNIT_COMPATIBILITY.json"
    target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return dict(receipt_path=str(target.resolve()), **receipt)


if __name__ == "__main__":
    import json
    assert "--time-unit-compatibility" in sys.argv
    result = time_unit_compatibility_receipt()
    print(json.dumps({key: result[key] for key in ["status", "receipt_path", "before_sha256", "after_sha256"]},
                     ensure_ascii=False, indent=2), flush=True)
