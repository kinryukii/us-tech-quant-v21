"""Synthetic checks for history availability and chart continuity; no result access."""
import json
import unittest
from dataclasses import replace

from apps.demo_console.components.history_charts import (
    portfolio_chart, security_chart, security_records,
)
from apps.demo_console.models import DecisionOverview, HoldingRow, PipelineStage, Provenance


def snapshot(day, *, ticker="ABC", rank=1, score=0.02, available=True,
             entered=None, retained=None, exited=None, turnover=0.10):
    return DecisionOverview(
        decision_date=day, ranking=(HoldingRow(rank, ticker, score=score),),
        holdings=(HoldingRow(None, ticker),) if available else (),
        entered=entered, retained=retained, exited=exited, turnover=turnover,
        pipeline=(PipelineStage("Portfolio", "AVAILABLE" if available else "UNAVAILABLE", "Synthetic"),),
        provenance=Provenance(execution_date=f"{day} execution"),
    )


class HistoryChartTests(unittest.TestCase):
    def test_absence_and_unavailable_are_distinct_and_rank_lines_break(self):
        history = (
            snapshot("2025-01-02", entered=("ABC",)),
            snapshot("2025-01-03", ticker="OTHER", exited=("ABC",)),
            snapshot("2025-01-06", rank=4, retained=("ABC",)),
            replace(snapshot("2025-01-07"), error="Unavailable", ranking=()),
            snapshot("2025-01-08", rank=3, available=False),
        )
        records = security_records(history, "ABC")
        self.assertEqual([row["rank"] for row in records], [1, None, 4, None, 3])
        self.assertEqual([row["ranking_status"] for row in records],
                         ["Recorded", "Outside Top20", "Recorded", "Unavailable", "Recorded"])
        self.assertEqual([row["status"] for row in records],
                         ["Entered", "Exited", "Retained", "Unavailable", "Unavailable"])
        self.assertEqual([row["held"] for row in records], [True, False, True, None, None])
        self.assertEqual([row["rank_segment"] for row in records], [1, 1, 2, 2, 3])
        spec = security_chart(history, "ABC").to_dict()
        rank_spec = spec["vconcat"][0]
        self.assertEqual(rank_spec["encoding"]["detail"]["field"], "rank_segment")
        self.assertEqual(rank_spec["encoding"]["y"]["scale"]["domain"], [20, 1])
        self.assertEqual(rank_spec["transform"], [{"filter": {"field": "rank", "valid": True}}])

    def test_score_gaps_are_independent_of_rank_and_keep_small_precision(self):
        history = (snapshot("2025-01-02", score=0.0000001789),
                   snapshot("2025-01-03", score=float("nan")),
                   snapshot("2025-01-06", score=-0.0000000037),
                   snapshot("2025-01-07", score=0.0))
        records = security_records(history, "ABC")
        self.assertEqual([row["score"] for row in records], [0.0000001789, None, -0.0000000037, 0.0])
        self.assertEqual([row["rank_segment"] for row in records], [1, 1, 1, 1])
        self.assertEqual([row["score_segment"] for row in records], [1, 1, 2, 2])
        spec = security_chart(history, "ABC", "score").to_dict()
        self.assertFalse(spec["encoding"]["y"]["scale"]["zero"])
        self.assertEqual(spec["encoding"]["detail"]["field"], "score_segment")
        json.dumps(spec, allow_nan=False)

    def test_dates_are_sorted_full_keys_across_years_and_models_stay_immutable(self):
        later = snapshot("2025-01-02", retained=("ABC",))
        earlier = snapshot("2024-12-31", entered=("ABC",))
        history = (later, earlier)
        before = repr(history)
        records = security_records(history, "ABC")
        self.assertEqual([row["decision_date"] for row in records], ["2024-12-31", "2025-01-02"])
        self.assertEqual(records[0]["execution_date"], "2024-12-31 execution")
        spec = security_chart(history, "ABC").to_dict()
        self.assertEqual(spec["vconcat"][0]["encoding"]["x"]["sort"], ["2024-12-31", "2025-01-02"])
        self.assertEqual(spec["vconcat"][0]["encoding"]["x"]["type"], "ordinal")
        self.assertEqual(repr(history), before)

    def test_axis_labels_show_year_only_when_history_crosses_years(self):
        same_year = (snapshot("2025-01-02"), snapshot("2025-12-31"))
        cross_year = (snapshot("2024-12-31"), snapshot("2025-01-02"))
        same = portfolio_chart(same_year).to_dict()["encoding"]["x"]
        cross = security_chart(cross_year, "ABC").to_dict()["vconcat"][1]["encoding"]["x"]
        self.assertEqual(same["axis"]["labelExpr"], "substring(datum.label, 5)")
        self.assertEqual(cross["axis"]["labelExpr"], "substring(datum.label, 0, 7)")
        self.assertEqual(cross["scale"]["domain"], ["2024-12-31", "2025-01-02"])
        self.assertEqual(cross["axis"]["values"], ["2024-12-31", "2025-01-02"])

    def test_portfolio_unknown_changes_stay_missing_and_true_zero_stays_zero(self):
        history = (snapshot("2025-01-02"),
                   snapshot("2025-01-03", entered=(), exited=()),
                   snapshot("2025-01-06", entered=("A", "B"), exited=("C",)),
                   snapshot("2025-01-07", entered=("A",), exited=("B",), available=False))
        spec = portfolio_chart(history).to_dict()
        values = spec["data"]["values"]
        self.assertEqual([row["signed_count"] for row in values], [None, None, 0, 0, 2, -1, None, None])
        self.assertEqual([row["count"] for row in values], [None, None, 0, 0, 2, 1, None, None])
        self.assertEqual({item["field"] for item in spec["encoding"]["tooltip"]},
                         {"decision_date", "execution_date", "change", "count"})

    def test_turnover_missing_observations_break_lines_without_zero_filling(self):
        history = (snapshot("2025-01-02", turnover=0.10),
                   snapshot("2025-01-03", turnover=None),
                   snapshot("2025-01-06", turnover=0.0),
                   snapshot("2025-01-07", turnover=float("inf")),
                   snapshot("2025-01-08", turnover=0.21))
        spec = portfolio_chart(history, "turnover").to_dict()
        values = spec["data"]["values"]
        self.assertEqual([row["turnover"] for row in values], [0.10, None, 0.0, None, 0.21])
        self.assertEqual([row["turnover_segment"] for row in values], [1, 1, 2, 2, 3])
        self.assertEqual(spec["encoding"]["detail"]["field"], "turnover_segment")
        self.assertEqual(spec["encoding"]["y"]["axis"]["format"], ".0%")
        json.dumps(spec, allow_nan=False)

    def test_empty_single_point_unknown_membership_and_literal_ticker_are_safe(self):
        self.assertEqual(security_records((), "ABC"), [])
        self.assertEqual(security_chart((), "ABC").to_dict()["data"]["values"], [])
        self.assertEqual(portfolio_chart(()).to_dict()["data"]["values"], [])
        literal = "</script><script>alert(1)</script>"
        history = (snapshot("2025-01-02", ticker=literal),)
        records = security_records(history, literal)
        self.assertEqual(records[0]["status"], "Held")
        self.assertEqual(security_records(history, "OTHER")[0]["status"], "Not held")
        spec = security_chart(history, literal).to_dict()
        self.assertEqual(spec["vconcat"][1]["encoding"]["x"]["axis"]["values"], ["2025-01-02"])
        self.assertNotIn(literal, json.dumps(spec))
        self.assertEqual(spec["data"]["values"][0]["rank"], 1)

    def test_holdings_band_is_independent_of_rank_and_missing_scores_are_literal(self):
        history = (
            snapshot("2025-01-02", score=None),
            snapshot("2025-01-03", ticker="OTHER"),
            replace(snapshot("2025-01-06"), ranking=()),
            replace(snapshot("2025-01-07"),
                    pipeline=(PipelineStage("Portfolio", "UNAVAILABLE", "Unverified"),)),
        )
        spec = security_chart(history, "ABC").to_dict()
        self.assertEqual(spec["resolve"]["scale"]["x"], "shared")
        self.assertNotIn("height", spec)
        self.assertEqual([row["holdings_state"] for row in spec["data"]["values"]],
                         ["Held", "Not held", "Held", "Unavailable"])
        self.assertEqual(spec["data"]["values"][0]["score_label"], "Not recorded")
        rank, band = spec["vconcat"]
        self.assertIsNone(rank["encoding"]["x"]["axis"])
        self.assertEqual(band["encoding"]["color"]["scale"]["domain"],
                         ["Held", "Not held", "Unavailable"])
        self.assertEqual(band["encoding"]["color"]["legend"]["orient"], "bottom")
        self.assertEqual(rank["encoding"]["x"]["scale"]["domain"], band["encoding"]["x"]["scale"]["domain"])
        self.assertEqual({item["field"] for item in band["encoding"]["tooltip"]},
                         {"decision_date", "execution_date", "holdings_state", "status"})
        score_tooltip = next(item for item in rank["encoding"]["tooltip"]
                             if item["title"] == "Recorded score")
        self.assertEqual(score_tooltip["field"], "score_label")
        self.assertEqual(score_tooltip["type"], "nominal")


if __name__ == "__main__":
    unittest.main()
