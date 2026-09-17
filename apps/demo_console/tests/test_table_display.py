"""Synthetic display checks; no adapter, artifact, or Streamlit server required."""

from html.parser import HTMLParser
import re
import unittest

from apps.demo_console.components.top20_table import table_html, table_records
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


if __name__ == "__main__":
    unittest.main()
