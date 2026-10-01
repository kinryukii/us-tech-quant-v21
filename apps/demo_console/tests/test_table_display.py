"""Synthetic display checks; no adapter, artifact, or Streamlit server required."""

from html.parser import HTMLParser
import re
import unittest

from apps.demo_console.components.top20_table import table_html, table_records, applied_ranking_rows, _focus_applied_ranking
from apps.demo_console.models import HoldingRow


class _TableParser(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.tags = []
        self.attrs = []
        self.text = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.extend(attrs)

    def handle_data(self, data):
        self.text.append(data)


class TableDisplayTests(unittest.TestCase):
    def test_records_contract_keeps_values_and_recorded_rank_order(self):
        rows = (HoldingRow(2, "B", score=9.0), HoldingRow(1, "A", score=1.0),
                HoldingRow(None, "C"))
        self.assertEqual(table_records(rows), [
            {"Rank": 1, "Ticker": "A", "Score": 1.0},
            {"Rank": 2, "Ticker": "B", "Score": 9.0},
            {"Rank": None, "Ticker": "C", "Score": None},
        ])
        self.assertEqual(rows[0].ticker, "B")

    def test_all_twenty_rows_are_visible_and_sorted_by_rank(self):
        rows = tuple(HoldingRow(rank, f"SYNTH_{rank:02}", score=float(rank))
                     for rank in range(20, 0, -1))
        markup = table_html(rows)
        document = _TableParser(markup)
        self.assertEqual(document.tags.count("tr"), 21)
        positions = [markup.index(f"SYNTH_{rank:02}") for rank in range(1, 21)]
        self.assertEqual(positions, sorted(positions))

    def test_untrusted_text_is_escaped_in_every_text_column(self):
        payload = '<img src=x onerror="alert(1)"> & <script>bad()</script>'
        markup = table_html((HoldingRow(1, payload, raw_action=payload,
                                       rx_action=payload, final_action=payload),))
        document = _TableParser(markup)
        self.assertNotIn("img", document.tags)
        self.assertNotIn("script", document.tags)
        self.assertFalse(any(name.startswith("on") for name, _ in document.attrs))
        self.assertEqual(" ".join(document.text).count(payload), 4)

    def test_rank_changes_and_holding_badges_keep_snapshot_meaning(self):
        markup = table_html((
            HoldingRow(1, "A", rank_change=3, held_before=True),
            HoldingRow(2, "B", rank_change=-2, held_before=False),
            HoldingRow(3, "C", rank_change=0),
            HoldingRow(4, "D"),
        ))
        for expected in ("↑ +3", "↓ −2", "→ 0", "Previous holding", "Not held",
                         "No previous rank available for comparison", "—"):
            self.assertIn(expected, markup)
        self.assertNotIn("checkbox", markup)
        self.assertNotIn("Buy", markup)

    def test_nonfinite_scores_do_not_become_values_or_bar_widths(self):
        markup = table_html((HoldingRow(1, "A", score=float("nan")),
                             HoldingRow(2, "B", score=float("inf")),
                             HoldingRow(3, "C", score=0.25)))
        self.assertIn("0.2500", markup)
        self.assertEqual(markup.count('title="Recorded value unavailable"'), 2)
        self.assertNotIn("uq-score-fill", markup)
        absent = table_html((HoldingRow(None, "A", score=float("nan")),))
        self.assertNotIn(">Score</th>", absent)
        self.assertNotIn(">Rank</th>", absent)

    def test_extreme_valid_scores_have_finite_bounded_display_bars(self):
        markup = table_html((HoldingRow(1, "A", score=1e308),
                             HoldingRow(2, "B", score=-1e308),
                             HoldingRow(3, "C", score=0.0)))
        widths = [float(value) for value in re.findall(r"width:([\d.]+)%", markup)]
        self.assertEqual(widths, [100.0, 0.0, 50.0])
        self.assertIn("not probabilities", markup)
        self.assertIn("displayed score range", markup)

    def test_empty_and_equal_score_states_do_not_invent_comparisons(self):
        self.assertIn("No recorded rows", table_html(()))
        markup = table_html((HoldingRow(None, "A", score=1.0),
                             HoldingRow(None, "B", score=1.0)))
        self.assertNotIn("uq-score-fill", markup)
        self.assertNotIn(">ΔRank</th>", markup)
        self.assertIn("source order preserved", markup)


class AppliedRankingTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            dict(ticker='HIGH_WEIGHT', company='Holding', model_rank=3, target_weight=.7, selected=True),
            dict(ticker='BEST_SCORE', company='First', model_rank=1, target_weight=.1, selected=True),
            dict(ticker='NEVER', company='Outside Top40 company', model_rank=55, target_weight=0., selected=False),
            dict(ticker='UNKNOWN', company='Missing target', model_rank=2, target_weight=None, selected=None)]

    def test_search_precedes_top_n_and_includes_company_outside_top40(self):
        result = applied_ranking_rows(self.rows, query='outside top40', top_n=1)
        self.assertEqual([row['ticker'] for row in result], ['NEVER'])
        self.assertIs(result[0]['selected'], False)

    def test_model_rank_and_weight_orders_are_distinct_without_fabricated_ranks(self):
        ranked = applied_ranking_rows(self.rows, top_n=None)
        weighted = applied_ranking_rows(self.rows, order='Portfolio weight', top_n=None)
        self.assertEqual([row['ticker'] for row in ranked], ['BEST_SCORE', 'UNKNOWN', 'HIGH_WEIGHT', 'NEVER'])
        self.assertEqual([row['ticker'] for row in weighted], ['HIGH_WEIGHT', 'BEST_SCORE', 'NEVER', 'UNKNOWN'])
        self.assertIsNone(weighted[-1]['target_weight'])
        self.assertEqual(weighted[0]['model_rank'], 3)
        self.assertEqual(self.rows[0]['ticker'], 'HIGH_WEIGHT')

    def test_selected_filter_excludes_both_false_and_unknown(self):
        result = applied_ranking_rows(self.rows, selected_only=True, top_n=None)
        self.assertEqual([row['ticker'] for row in result], ['BEST_SCORE', 'HIGH_WEIGHT'])

    def test_only_valid_current_single_row_updates_inline_focus(self):
        from unittest.mock import patch
        import streamlit as st

        state = {'_applied_ranking_keys': ('live',), '_applied_ranking_date': '2026-01-07',
            'decision_date': '2026-01-07', 'workspace': 'Overview', 'applied_stock_ticker': 'KEEP'}
        with patch.object(st, 'session_state', state):
            for event in ({}, {'selection': None}, {'selection': {'rows': None}},
                          {'selection': {'rows': []}}, {'selection': {'rows': [True]}},
                          {'selection': {'rows': [2]}}, {'selection': {'rows': [-1]}},
                          {'selection': {'rows': [0, 1]}}):
                state['live'] = event
                _focus_applied_ranking('live', ('A', 'B'))
                self.assertEqual(state['applied_stock_ticker'], 'KEEP')
            state['live'] = {'selection': {'rows': [1]}}
            _focus_applied_ranking('old', ('A', 'B'))
            self.assertEqual(state['applied_stock_ticker'], 'KEEP')
            _focus_applied_ranking('live', ('A', 'B'))
            self.assertEqual(state['applied_stock_ticker'], 'B')
            self.assertEqual(state['workspace'], 'Overview')
            self.assertEqual(state['decision_date'], '2026-01-07')
            state.update(decision_date='2026-01-06', applied_stock_ticker='KEEP')
            _focus_applied_ranking('live', ('A', 'B'))
            self.assertEqual(state['applied_stock_ticker'], 'KEEP')


if __name__ == "__main__":
    unittest.main()
