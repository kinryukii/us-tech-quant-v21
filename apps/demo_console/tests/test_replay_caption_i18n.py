"""Pure caption/source contracts; no Streamlit, data adapter, model or API read."""
import ast
from collections import Counter
from copy import deepcopy
from pathlib import Path
import re
from string import Formatter
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from apps.demo_console import i18n

_ROOT = Path(__file__).parents[3]


def _captions():
    source = _ROOT / "apps/demo_console/pages/selected_strategies.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names = {"replay_basis_caption", "replay_update_caption", "replay_provenance_caption",
             "replay_input_vintage_caption", "policy_caption", "strategy_label", "_source_details"}
    body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(body) == len(names)
    # The real helper definitions run without importing data/model modules.
    # Source labels in these fixtures are synthetic identities.
    namespace = {"tr": i18n.tr, "catalog": i18n.catalog,
                 "WORKSPACE_STRATEGIES": {}, "LEGACY_STRATEGIES": {}}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


def _key(prefix):
    keys = [key for key in i18n.catalog() if key.startswith(prefix)]
    assert len(keys) == 1
    return keys[0]


class ReplayCaptionTranslationTests(unittest.TestCase):
    def test_actual_pit_and_main_descriptions_translate_in_all_languages(self):
        functions = _captions()
        package = {"performance_period": {"price_basis": "PIT_FORWARD_REHAB_INDEX"}}
        note = i18n.catalog()[_key("Fixed MAIN descriptive research ledger:")]["zh"]
        before = deepcopy(package)
        for language in ("en", "zh", "ja"):
            with self.subTest(language=language), i18n.language_scope(language):
                basis = i18n.tr(functions["replay_basis_caption"](package))
                main = functions["replay_provenance_caption"](note)
                self.assertIn("PIT", basis)
                self.assertIn("QFQ", basis)
                self.assertIn("MAIN", main)
                self.assertIn("2026-01-02", main)
                self.assertIn("01-05", main)
                self.assertIn("10", main)
                if language == "en":
                    self.assertIsNone(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", basis + main))
                    self.assertIn("not simulated-account performance", basis)
                    self.assertIn("not", basis)
                    self.assertIn("new independent test", basis)
                    self.assertIn("actual simulated-account fills", main)
                else:
                    self.assertNotEqual(basis, _key("Separate PIT research replay"))
                    self.assertNotEqual(main, _key("Fixed MAIN descriptive research ledger:"))
        self.assertEqual(package, before)

    def test_ready_and_partial_use_dynamic_dates_and_preserve_raw_reason(self):
        functions = _captions()
        reason = "SYNTHETIC_REASON {original_detail}"
        for end, requested, execution in (("2026-03-06", "2026-03-10", "2026-03-09"),
                ("2026-06-04", "2026-06-08", "2026-06-05")):
            package = {"performance_period": {"end": end}, "performance_extension": {"status": "READY"}}
            for language in ("en", "zh", "ja"):
                with self.subTest(language=language, end=end), i18n.language_scope(language):
                    ready = functions["replay_update_caption"](package)
                    self.assertIn(end, ready)
                    self.assertNotIn("{end}", ready)
                    partial = deepcopy(package)
                    partial["performance_extension"].update(status="PARTIAL", requested_end_date=requested,
                        blocked_next={"execution_date": execution, "reason": reason})
                    before = deepcopy(partial)
                    caption = functions["replay_update_caption"](partial)
                    for value in (end, requested, execution, reason):
                        self.assertIn(value, caption)
                    self.assertEqual(i18n.tr(caption), caption)
                    self.assertEqual(partial, before)
        self.assertIsNone(functions["replay_update_caption"]({}))

    def test_unknown_provenance_and_changed_historical_note_stay_exact(self):
        function = _captions()["replay_provenance_caption"]
        known = i18n.catalog()[_key("Fixed MAIN descriptive research ledger:")]["zh"]
        for language in ("en", "zh", "ja"):
            with self.subTest(language=language), i18n.language_scope(language):
                for note in (None, "", "UNKNOWN SOURCE {literal}", known.replace("2026-01-02", "2026-01-06")):
                    self.assertEqual(function(note), note)

    def test_existing_legacy_qfq_translation_key_is_retained(self):
        function = _captions()["replay_basis_caption"]
        source = function({"performance_period": {"price_basis": "SYNTHETIC_LEGACY"}})
        self.assertTrue(source.startswith("HGB replay uses the corrected close-signal"))
        for language in ("en", "zh", "ja"):
            with self.subTest(language=language), i18n.language_scope(language):
                translated = i18n.tr(source)
                self.assertIn("QFQ", translated)
                self.assertIn("2026", translated)

    def test_new_templates_and_rank_fallback_keep_placeholder_contracts(self):
        keys = [_key(prefix) for prefix in ("Separate PIT research replay", "Original Raw A2 / HGB replay is synchronized",
            "Original Raw A2 / HGB replay is verified", "Fixed MAIN descriptive research ledger:")]
        keys += ["Recorded MAIN research records", "Recorded MAIN research signal. This is not a current PAPER account target.",
            "Latest PAPER target signal: {date}. The selected-date research record is shown separately.",
            "No stock ranking or model score was recorded in this research ledger.",
            "Research signal date: {date}", "Research order target weight", "Policy weight (research action)",
            "Recorded HOLD units", "Recorded order semantic",
            "Research records failed verification. Other strategy records are shown independently."]
        fields = lambda value: Counter((field, spec, conversion) for _, field, spec, conversion in Formatter().parse(value)
            if field is not None)
        for key in keys:
            for language in ("zh", "ja"):
                with self.subTest(key=key, language=language):
                    translated = i18n.catalog()[key][language]
                    self.assertTrue(translated.strip())
                    self.assertEqual(fields(key), fields(translated))
        for language in ("en", "zh", "ja"):
            with i18n.language_scope(language):
                for key in ("Research signal date: {date}",
                        "Latest PAPER target signal: {date}. The selected-date research record is shown separately."):
                    caption = i18n.tr(key, date="2026-03-05")
                    self.assertIn("2026-03-05", caption)
                    self.assertNotIn("{date}", caption)

    def test_native_stock_note_translates_only_the_recorded_literal(self):
        function = _captions()["replay_provenance_caption"]
        key = _key("Fixed MAIN research stock records;")
        note = i18n.catalog()[key]["zh"]
        for language in ("en", "zh", "ja"):
            with self.subTest(language=language), i18n.language_scope(language):
                translated = function(note)
                self.assertEqual(translated, i18n.tr(key))
                self.assertIn("CUSIP", translated)
                if language == "en":
                    self.assertIsNone(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", translated))
                    self.assertIn("remain unknown", translated)
                    self.assertIn("not simulated-account fills", translated)
                self.assertEqual(function(note + " UNKNOWN_SOURCE"), note + " UNKNOWN_SOURCE")

    def test_source_details_translate_labels_and_preserve_raw_metadata(self):
        functions = _captions()
        package = {"performance_period": {"price_basis": "PIT_FORWARD_REHAB_INDEX"},
            "generated_at": "2026-03-05T10:11:12+00:00", "package_sha256": "ab" * 32,
            "source_hashes": {"SYNTHETIC_RAW_SOURCE {literal}": "cd" * 32}}
        before = deepcopy(package)
        for language in ("en", "zh", "ja"):
            with self.subTest(language=language), i18n.language_scope(language):
                st = MagicMock()
                functions.update(st=st, pd=SimpleNamespace(DataFrame=lambda rows: rows))
                functions["_source_details"](package)
                st.expander.assert_called_once_with(i18n.tr("Data sources"), expanded=False)
                captions = [call.args[0] for call in st.caption.call_args_list]
                self.assertTrue(any(package["generated_at"] in value for value in captions))
                self.assertTrue(any(package["package_sha256"] in value for value in captions))
                self.assertTrue(any("USER_SELECTED_AFTER_EXPOSURE" in value for value in captions))
                rows = st.dataframe.call_args.args[0]
                self.assertEqual(rows, [{i18n.tr("Source artifact"): "SYNTHETIC_RAW_SOURCE {literal}", "SHA-256": "cd" * 32}])
                if language == "en":
                    visible = captions + [call.args[0] for call in st.write.call_args_list]
                    self.assertIsNone(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", " ".join(visible)))
                self.assertEqual(package, before)

    def test_actual_stock_note_call_uses_same_display_helper(self):
        tree = ast.parse((_ROOT / "apps/demo_console/components/stock_history_search.py").read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "render_applied_stock_history")
        calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name) and node.func.id == "replay_provenance_caption"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(ast.unparse(calls[0].args[0]), "result['native_stock_note']")

    def test_reachable_model_comparison_captions_translate_both_scopes(self):
        tree = ast.parse((_ROOT / "apps/demo_console/components/ml_comparison.py").read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "render_model_comparison")
        statements = [node for node in function.body if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call) and any(isinstance(part, ast.Constant) and isinstance(part.value, str)
                and (part.value.startswith("Recorded Top40 ranking history") or part.value.startswith("The selected stocks come")) for part in ast.walk(node))]
        self.assertEqual(len(statements), 2)
        code = compile(ast.Module(body=statements, type_ignores=[]), "comparison_captions", "exec")
        for language in ("en", "zh", "ja"):
            for updated in (False, True):
                with self.subTest(language=language, updated=updated), i18n.language_scope(language):
                    st = MagicMock()
                    namespace = {"st": st, "tr": i18n.tr, "model": SimpleNamespace(decision_date="2026-03-05"),
                        "workspace_reader": SimpleNamespace(is_updated=lambda model: updated)}
                    exec(code, namespace)
                    captions = [call.args[0] for call in st.caption.call_args_list]
                    self.assertEqual(len(captions), 2)
                    self.assertIn("2026-03-05", captions[0])
                    self.assertIn("Top40" if updated else "Top20", captions[0])
                    if language == "en":
                        self.assertIsNone(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", " ".join(captions)))

    def test_actual_research_caption_call_uses_display_helper(self):
        selected_tree = ast.parse((_ROOT / "apps/demo_console/pages/selected_strategies.py").read_text(encoding="utf-8"))
        research_tree = ast.parse((_ROOT / "apps/demo_console/pages/research.py").read_text(encoding="utf-8"))
        details = next(node for node in selected_tree.body if isinstance(node, ast.FunctionDef) and node.name == "_source_details")
        mapped = [node for node in ast.walk(details) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute) and node.func.attr == "caption"
            and len(node.args) == 1 and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Name) and node.args[0].func.id == "replay_provenance_caption"]
        self.assertEqual(len(mapped), 1)
        self.assertEqual(ast.unparse(mapped[0].args[0].args[0]), "note")

        # Both actual workbench entry paths forward their own verified contexts
        # into the shared source renderer; the display helper moved with it.
        for tree, entry in ((selected_tree, "render_workspace"), (research_tree, "_render_applied_research")):
            function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == entry)
            calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name) and node.func.id == "_source_details"]
            self.assertEqual(len(calls), 1, entry)
            self.assertEqual(ast.unparse(calls[0].args[0]), "package")
            self.assertEqual(ast.unparse(next(item.value for item in calls[0].keywords if item.arg == "contexts")), "contexts")

        # Execute the actual source renderer and complete helper closure, not
        # a copied caption expression. Repeated notes are displayed once.
        functions = _captions()
        display_helper = functions["replay_provenance_caption"]
        known_key = _key("Fixed MAIN descriptive research ledger:")
        known_note = i18n.catalog()[known_key]["zh"]
        unknown_note = "UNKNOWN_SOURCE {literal} SYNTHETIC_RAW_METADATA"
        package = {"performance_period": {"price_basis": "PIT_FORWARD_REHAB_INDEX"},
            "generated_at": "2026-03-05T10:11:12+00:00", "package_sha256": "ab" * 32,
            "source_hashes": {"SYNTHETIC_RAW_SOURCE {literal}": "cd" * 32}}
        contexts = {"SYNTHETIC_ONE": {"provenance": {"note": known_note}, "history": {"end": "2026-03-05"}},
                    "SYNTHETIC_TWO": {"provenance": {"note": unknown_note}, "history": {"end": None}},
                    "SYNTHETIC_THREE": {"provenance": {"note": known_note}, "history": {"end": "2026-03-04"}}}
        before = deepcopy((package, contexts))
        for language in ("en", "zh", "ja"):
            with self.subTest(language=language), i18n.language_scope(language):
                st = MagicMock()
                helper = MagicMock(wraps=display_helper)
                functions.update(st=st, pd=SimpleNamespace(DataFrame=lambda rows: rows),
                                 replay_provenance_caption=helper)
                functions["_source_details"](package, contexts=contexts, expanded=True)
                st.expander.assert_called_once_with(i18n.tr("Data sources"), expanded=True)
                self.assertEqual([item.args[0] for item in helper.call_args_list], [known_note, unknown_note])
                captions = [item.args[0] for item in st.caption.call_args_list]
                self.assertIn(i18n.tr(known_key), captions)
                self.assertIn(unknown_note, captions)
                self.assertEqual(captions.count(i18n.tr(known_key)), 1)
                self.assertTrue(any(package["package_sha256"] in value for value in captions))
                self.assertEqual(st.dataframe.call_args.args[0], [
                    {i18n.tr("Source artifact"): "SYNTHETIC_RAW_SOURCE {literal}", "SHA-256": "cd" * 32}])
                self.assertEqual((package, contexts), before)


if __name__ == "__main__":
    unittest.main()
