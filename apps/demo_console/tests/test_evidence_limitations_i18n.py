"""Render the real evidence limitation closure from source, with synthetic state only."""
import ast
from copy import deepcopy
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from apps.demo_console.i18n import catalog, language_scope, tr

_ROOT = Path(__file__).parents[3]
_SOURCES = ('Descriptive research replay after the data update, using the original fixed holdings and cost rules; this is not a live account.', 'Rankings, actual simulated holdings and execution-day performance are read separately; pending signals have no executed holdings or returns.', 'Securities with insufficient coverage do not enter these rankings. Historical price-adjustment event snapshots do not represent the publication snapshot at every historical point in time.', '2023–2025 annual models are reconstructed with fixed rules; 2026 uses the original pre-2026 frozen model. This performance replay does not train or tune models.', 'Performance is the valuation of holdings after next-day open execution. The first signal day is a cash baseline; this is not same-day closing NAV.')


@pytest.mark.parametrize("language", ("en", "zh", "ja"))
def test_actual_evidence_limitations_translate_exact_fixed_notes_and_preserve_unknowns(language):
    source = _ROOT / "apps/demo_console/pages/overview.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    functions = {node.name:node for node in tree.body if isinstance(node, ast.FunctionDef)}
    evidence_calls = [node for node in ast.walk(functions["_render_evidence"])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_render_coverage"]
    assert len(evidence_calls) == 1 and ast.unparse(evidence_calls[0].args[0]) == "model"
    helper_calls = [node for node in ast.walk(functions["_render_coverage"])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_coverage_limitation_caption"]
    assert len(helper_calls) == 1 and ast.unparse(helper_calls[0].args[0]) == "limitation"

    # Constants are read as Python literals; the data adapter is never imported.
    adapter = ast.parse((_ROOT / "apps/demo_console/adapters/updated_research_reader.py").read_text(encoding="utf-8"))
    fixed = ast.literal_eval(next(node.value for node in adapter.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "LIMITATIONS" for target in node.targets)))
    assert len(fixed) == len(_SOURCES) == 5
    for raw, key in zip(fixed, _SOURCES):
        assert catalog()[key]["zh"] == raw and catalog()[key]["ja"].strip()
    unknown = ("UNREGISTERED SOURCE {literal}", fixed[3].replace("2023–2025", "2022–2025"),
               "未登记原始说明 {raw}", "/SYNTHETIC_SOURCE/ab123", "ab" * 32)
    model = SimpleNamespace(raw_proposed_changes=7, rx_accepted_changes=3, rx_prevented_changes=None,
                            limitations=fixed + unknown)
    before = deepcopy(vars(model))
    st = MagicMock()
    namespace = {"st":st, "tr":tr, "catalog":catalog, "DecisionOverview":object}
    body = [functions["_coverage_limitation_caption"], functions["_render_coverage"]]
    exec(compile(ast.Module(body=body, type_ignores=[]), str(source), "exec"), namespace)
    with language_scope(language):
        namespace["_render_coverage"](model)
        output = [call.args[0] for call in st.write.call_args_list]
        assert output[:3] == [f'{tr("Raw A2 proposed changes")}: 7',
                              f'{tr("RX accepted changes")}: 3',
                              f'{tr("RX prevented changes")}: {tr("N/A")}']
        assert output[3:8] == [tr(key) for key in _SOURCES]
        assert tuple(output[8:]) == unknown
        st.expander.assert_called_once_with(tr("Coverage & limitations"), expanded=True)
        if language == "en":
            assert not re.search(r"[\u3040-\u30ff\u3400-\u9fff]", " ".join(output[3:8]))
            assert all(fragment in " ".join(output[3:8]) for fragment in
                       ("not a live account", "pending signals", "publication snapshot", "pre-2026", "cash baseline"))
        elif language == "zh":
            assert tuple(output[3:8]) == fixed
        else:
            assert all(message != raw for message, raw in zip(output[3:8], fixed))
            assert "2023–2025" in output[6] and "pre-2026" in output[6]
    assert vars(model) == before
