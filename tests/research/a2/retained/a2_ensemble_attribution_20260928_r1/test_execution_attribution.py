"""Behavior checks for ledger accounting, including unknown rejected requests."""
import unittest
import json
import pandas as pd
import numpy as np

from execution_attribution import OUT, SOURCE, sha, buy_fill_attribution, constrained_events, pairwise_decomposition


class ExecutionAttributionTests(unittest.TestCase):
    def test_capacity_then_cash_scaling_and_existing_holding(self):
        date = pd.Timestamp("2025-07-02")
        trades = pd.DataFrame([dict(order_id="a", side="BUY", execution_date=date,
                                   pretrade_nav=1000., index_units_before=2., price=10., notional=40.)])
        targets = pd.DataFrame([dict(order_id="a", adapted_target_weight=.2, signal_day_adv=5000.)])
        daily = pd.DataFrame([dict(date=date, buy_cash_scale=.8, open_stale_count=0, open_unknown_count=0)])
        got = buy_fill_attribution(trades, targets, daily, .01).iloc[0]
        self.assertEqual(got.requested_buy_notional, 180.)
        self.assertEqual(got.capacity_capped_buy_notional, 50.)
        self.assertEqual(got.capacity_withheld_notional, 130.)
        self.assertAlmostEqual(got.funding_withheld_notional, 10.)
        self.assertAlmostEqual(got.actual_reconstruction_error, 0.)

    def test_inconsistent_fill_is_rejected(self):
        date = pd.Timestamp("2025-07-02")
        trades = pd.DataFrame([dict(order_id="a", side="BUY", execution_date=date,
                                   pretrade_nav=1000., index_units_before=0., price=10., notional=200.)])
        targets = pd.DataFrame([dict(order_id="a", adapted_target_weight=.2, signal_day_adv=5000.)])
        daily = pd.DataFrame([dict(date=date, buy_cash_scale=1., open_stale_count=0, open_unknown_count=0)])
        with self.assertRaises(AssertionError):
            buy_fill_attribution(trades, targets, daily, .01)

    def test_missing_open_rejection_zero_fill_does_not_mean_zero_request(self):
        date = pd.Timestamp("2026-04-01")
        execution = pd.DataFrame([
            dict(order_id="new", ticker="NEW", execution_date=date, status="REJECTED", side="BUY", notional=0.),
            dict(order_id="held", ticker="OLD", execution_date=date, status="REJECTED", side="SELL", notional=0.),
            dict(order_id="hold", ticker="HOLD", execution_date=date, status="PRESERVED_UNITS", side="NONE", notional=0.)])
        targets = pd.DataFrame([
            dict(order_id=order, adapted_target_weight=w, current_units=q, current_weight=weight,
                 signal_close_nav=1000., signal_reservation_reasons="", signal_day_adv=1e6)
            for order,w,q,weight in [("new",.1,0.,0.),("held",0.,10.,.2),("hold",np.nan,10.,.3)]])
        daily = pd.DataFrame([dict(date=date,pretrade_nav=1000.,valuation_status="stale",open_stale_count=2,open_unknown_count=0)])
        positions = pd.DataFrame([dict(date=date,ticker=t,market_value=v,stale=True,unknown=False,mark_date=date-pd.Timedelta(days=1))
                                  for t,v in [("OLD",200.),("HOLD",300.)]])
        got = constrained_events(execution,targets,daily,positions).set_index("order_id")
        self.assertEqual(got.loc["new","requested_notional_exact_from_ledger"],100.)
        self.assertTrue(pd.isna(got.loc["held","requested_notional_exact_from_ledger"]))
        self.assertEqual(got.loc["held","ledger_filled_notional"],0.)
        self.assertEqual(got.loc["hold","request_amount_status"],"PRESERVED_UNITS_HAS_NO_TRADE_REQUEST")
        self.assertEqual(len(got),3)

    def test_fee_difference_separated_from_gross_bookkeeping_pnl(self):
        base = dict(initial_cash=1000.,traded_notional=100.,half_turnover=2.,mean_cash_weight=.5)
        rows = [dict(base,policy="a",final_recorded_nav=1120.,net_pnl=120.,gross_bookkeeping_pnl=150.,cumulative_fees=30.),
                dict(base,policy="b",final_recorded_nav=1100.,net_pnl=100.,gross_bookkeeping_pnl=150.,cumulative_fees=50.)]
        got=pairwise_decomposition(rows).iloc[0]
        self.assertEqual(got.net_pnl_difference,20.)
        self.assertEqual(got.gross_bookkeeping_pnl_difference,0.)
        self.assertEqual(got.fee_saving_contribution_to_net_difference,20.)
        self.assertEqual(got.identity_error,0.)
        self.assertFalse(got.causal_diversification_or_cash_substitution_identified)

    def test_different_starting_capital_rejected(self):
        rows=[dict(policy="a",initial_cash=1000.),dict(policy="b",initial_cash=2000.)]
        with self.assertRaises(AssertionError):
            pairwise_decomposition(rows)

    @unittest.skipUnless((OUT / "execution_receipt.json").exists(), "Run attribution first for artifact audit")
    def test_saved_all_date_coverage_and_original_input_hashes(self):
        receipt=json.loads((OUT/"execution_receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["scenario_count"],14)
        for path,digest in receipt["input_sha256"].items():
            self.assertEqual(sha(path),digest,path)
        for name,digest in receipt["output_sha256"].items():
            self.assertEqual(sha(OUT/name),digest,name)
        bridge=pd.read_csv(OUT/"execution_daily_cash_bridge.csv")
        for scenario,group in bridge.groupby("scenario"):
            original=pd.read_parquet(SOURCE/scenario/"daily.parquet")
            self.assertEqual(list(pd.to_datetime(group.date)),list(original.date))
            self.assertEqual(list(group.valuation_status),list(original.valuation_status))
            self.assertEqual(list(group.stale_count),list(original.stale_count))
            self.assertEqual(list(group.unknown_count),list(original.unknown_count))


if __name__ == "__main__":
    unittest.main()
