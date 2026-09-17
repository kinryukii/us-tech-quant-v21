"""Synthetic chart semantics; no artifact or research-result reads."""

import json
import unittest

from apps.demo_console.components.score_profile import chart_records, score_chart
from apps.demo_console.models import HoldingRow


class ScoreProfileTests(unittest.TestCase):
    def test_actual_scores_keep_recorded_order_including_negative_and_zero(self):
        rows = (
            HoldingRow(3, "ZERO", score=0.0),
            HoldingRow(1, "NEGATIVE", score=-0.125, rank_change=2, held_before=True),
            HoldingRow(2, "POSITIVE", score=0.75, rank_change=-1, held_before=False),
        )
        records = chart_records(rows)
        self.assertEqual([record["rank"] for record in records], [1, 2, 3])
        self.assertEqual([record["score"] for record in records], [-0.125, 0.75, 0.0])
        self.assertEqual([record["rank_change"] for record in records], [2, -1, None])
        self.assertEqual([record["previous_holding"] for record in records],
                         ["Previous holding", "Not held", "Not recorded"])
        self.assertEqual(rows[0].ticker, "ZERO")

    def test_missing_or_nonfinite_coordinates_are_not_filled_or_reranked(self):
        rows = (
            HoldingRow(None, "NO_RANK", score=0.99),
            HoldingRow(1, "NO_SCORE"),
            HoldingRow(2, "NAN", score=float("nan")),
            HoldingRow(3, "INF", score=float("inf")),
            HoldingRow(4, "NEG_INF", score=-float("inf")),
            HoldingRow(5, "VALID", score=0.25),
        )
        records = chart_records(rows)
        self.assertEqual(len(records), 1)
        self.assertEqual((records[0]["rank"], records[0]["score"]), (5, 0.25))
        json.dumps(score_chart(rows).to_dict(), allow_nan=False)

    def test_chart_uses_score_bars_zero_baseline_and_recorded_rank_axis(self):
        chart = score_chart((HoldingRow(1, "SYNTH", score=0.0398, rank_change=3),))
        spec = chart.to_dict()
        self.assertEqual(spec["mark"]["type"], "bar")
        self.assertEqual(spec["encoding"]["x"]["field"], "rank")
        self.assertEqual(spec["encoding"]["x"]["type"], "ordinal")
        self.assertEqual(spec["encoding"]["y"]["field"], "score")
        self.assertTrue(spec["encoding"]["y"]["scale"]["zero"])
        self.assertNotIn("transform", spec)
        tooltip = {item["field"] for item in spec["encoding"]["tooltip"]}
        self.assertEqual(tooltip, {"ticker", "rank", "score", "rank_change", "previous_holding"})

    def test_empty_and_unavailable_rank_changes_do_not_invent_series_or_tooltip(self):
        self.assertEqual(chart_records(()), [])
        empty_spec = score_chart(()).to_dict()
        self.assertEqual(empty_spec["data"]["values"], [])
        spec = score_chart((HoldingRow(7, "ONLY", score=0.0031),)).to_dict()
        self.assertNotIn("rank_change", [item["field"] for item in spec["encoding"]["tooltip"]])
        self.assertEqual(spec["encoding"]["x"]["axis"]["values"], [7])


if __name__ == "__main__":
    unittest.main()
