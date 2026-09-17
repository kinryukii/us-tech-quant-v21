"""Translation contracts and synthetic display invariants; no artifact reads."""
from collections import Counter
from contextvars import Context
import json
from string import Formatter
import unittest

from apps.demo_console.components.history_charts import (
    portfolio_chart, security_chart, security_records,
)
from apps.demo_console.components.score_profile import chart_records, score_chart
from apps.demo_console.components.top20_table import table_records
from apps.demo_console.i18n import (
    catalog, get_language, language_scope, set_language, tr,
)
from apps.demo_console.models import HoldingRow
from apps.demo_console.tests.test_history_charts import snapshot


def _placeholders(message):
    return Counter((field, spec, conversion)
                   for _, field, spec, conversion in Formatter().parse(message)
                   if field is not None)


class TranslationTests(unittest.TestCase):
    def test_catalog_has_complete_translations_and_preserves_format_placeholders(self):
        messages = catalog()
        self.assertTrue(messages, "The presentation catalog must contain translated UI messages.")
        for source, translations in messages.items():
            self.assertIsInstance(source, str)
            self.assertTrue(source.strip())
            for language in ("zh", "ja"):
                with self.subTest(source=source, language=language):
                    self.assertIn(language, translations)
                    translated = translations[language]
                    self.assertIsInstance(translated, str)
                    self.assertTrue(translated.strip())
                    self.assertEqual(_placeholders(translated), _placeholders(source))

    def test_language_scope_restores_nested_context_and_restores_after_exception(self):
        initial = get_language()
        with language_scope("en"):
            self.assertEqual(get_language(), "en")
            with language_scope("zh"):
                self.assertEqual(get_language(), "zh")
                with language_scope("ja"):
                    self.assertEqual(get_language(), "ja")
                self.assertEqual(get_language(), "zh")
                with self.assertRaisesRegex(RuntimeError, "synthetic render failure"):
                    with language_scope("ja"):
                        raise RuntimeError("synthetic render failure")
                self.assertEqual(get_language(), "zh")
            self.assertEqual(get_language(), "en")
        self.assertEqual(get_language(), initial)

    def test_contexts_keep_independent_language_choices(self):
        with language_scope("ja"):
            first = Context()
            self.assertEqual(first.run(get_language), "en")
            first.run(set_language, "zh")
            second = first.copy()
            second.run(set_language, "en")
            self.assertEqual(first.run(get_language), "zh")
            self.assertEqual(second.run(get_language), "en")
            self.assertEqual(get_language(), "ja")

    def test_unknown_language_falls_back_to_english_and_unknown_message_is_retained(self):
        with language_scope("zh"):
            with language_scope("unknown-language"):
                self.assertEqual(get_language(), "en")
                self.assertEqual(tr("Recorded rank"), "Recorded rank")
            self.assertEqual(get_language(), "zh")
        source = "SYNTHETIC_UNCATALOGUED_MESSAGE {ticker}: {count:03d}"
        ticker = "SYNTH'<&>"
        for language in ("en", "zh", "ja"):
            with self.subTest(language=language), language_scope(language):
                self.assertEqual(tr("SYNTHETIC_UNCATALOGUED_LITERAL"), "SYNTHETIC_UNCATALOGUED_LITERAL")
                self.assertEqual(tr(source, ticker=ticker, count=7), f"SYNTHETIC_UNCATALOGUED_MESSAGE {ticker}: 007")

    def test_record_functions_preserve_tickers_scores_and_internal_states_in_every_language(self):
        rows = (HoldingRow(2, "QQQ", score=0.00000123456789, held_before=True),
                HoldingRow(1, "SYNTH'<&>", score=-0.0087, held_before=False))
        history = (snapshot("2025-01-02", score=None, entered=("ABC",)),
                   snapshot("2025-01-03", ticker="OTHER", exited=("ABC",)),
                   snapshot("2025-01-06", rank=5, available=False))
        with language_scope("en"):
            originals = (table_records(rows), chart_records(rows), security_records(history, "ABC"))
        before = repr((rows, history))
        for language in ("en", "zh", "ja"):
            with self.subTest(language=language), language_scope(language):
                self.assertEqual(table_records(rows), originals[0])
                self.assertEqual(chart_records(rows), originals[1])
                self.assertEqual(security_records(history, "ABC"), originals[2])
        self.assertEqual([row["status"] for row in originals[2]], ["Entered", "Exited", "Unavailable"])
        self.assertEqual(originals[0][1]["Ticker"], "QQQ")
        self.assertEqual(originals[0][1]["Score"], 0.00000123456789)
        self.assertEqual(repr((rows, history)), before)

    def test_score_chart_translates_titles_and_tooltip_labels_without_changing_raw_values(self):
        rows = (HoldingRow(1, "QQQ", score=0.00000123456789, held_before=True),)
        for language in ("zh", "ja"):
            with self.subTest(language=language), language_scope(language):
                self.assertNotEqual(tr("Recorded rank"), "Recorded rank")
                spec = score_chart(rows).to_dict()
                self.assertEqual(spec["encoding"]["x"]["title"], tr("Recorded rank"))
                self.assertEqual(spec["encoding"]["y"]["title"], tr("Model score"))
                tooltip = {item["field"]: item["title"] for item in spec["encoding"]["tooltip"]}
                self.assertEqual(tooltip["ticker"], tr("Ticker"))
                self.assertEqual(tooltip["previous_holding_label"], tr("Previous snapshot"))
                rendered = spec["data"]["values"][0]
                self.assertEqual(rendered["previous_holding_label"], tr("Previous holding"))
                for field, value in chart_records(rows)[0].items():
                    self.assertEqual(rendered[field], value)
                self.assertNotIn("transform", spec)

    def test_history_chart_translates_states_and_legends_while_retaining_numeric_domains(self):
        history = (snapshot("2025-01-02", score=None, entered=("ABC",)),
                   snapshot("2025-01-03", ticker="OTHER", exited=("ABC",)))
        originals = security_records(history, "ABC")
        for language in ("zh", "ja"):
            with self.subTest(language=language), language_scope(language):
                spec = security_chart(history, "ABC").to_dict()
                rank, holdings = spec["vconcat"]
                self.assertEqual(rank["encoding"]["y"]["title"], tr("Top20 rank · 1 is highest"))
                self.assertEqual(rank["encoding"]["y"]["scale"]["domain"], [20, 1])
                self.assertEqual(holdings["encoding"]["x"]["title"], tr("Decision date"))
                self.assertEqual(holdings["encoding"]["color"]["scale"]["domain"], ["Held", "Not held", "Unavailable"])
                expression = holdings["encoding"]["color"]["legend"]["labelExpr"]
                legend = json.loads(expression.removesuffix("[datum.label]"))
                self.assertEqual(legend, {state: tr(state) for state in ("Held", "Not held", "Unavailable")})
                self.assertEqual(spec["data"]["values"][0]["score_label"], tr("Not recorded"))
                for original, rendered in zip(originals, spec["data"]["values"]):
                    for field, value in original.items():
                        self.assertEqual(rendered[field], value)
                    self.assertEqual(rendered["status_label"], tr(original["status"]))
                    self.assertEqual(rendered["ranking_status_label"], tr(original["ranking_status"]))
                changes = portfolio_chart(history).to_dict()
                self.assertEqual(changes["encoding"]["y"]["title"], tr("Holding names"))
                self.assertEqual(changes["data"]["values"][0]["change"], "Entered")
                self.assertEqual(changes["data"]["values"][0]["change_label"], tr("Entered"))
                self.assertEqual(changes["data"]["values"][0]["signed_count"], 1)
                json.dumps([spec, changes], allow_nan=False)


if __name__ == "__main__":
    unittest.main()
