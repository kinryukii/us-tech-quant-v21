"""Frozen-method editorial semantics and actual data-free renderer translations."""
import ast
from copy import deepcopy
from html import escape, unescape
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from apps.demo_console.i18n import catalog, language_scope, tr

_ROOT = Path(__file__).parents[3]
_COMPONENT = _ROOT / "apps/demo_console/components/strategy_workbench.py"


def _source_namespace(st=None):
    tree = ast.parse(_COMPONENT.read_text(encoding="utf-8"))
    owner = ast.parse((_ROOT / "apps/moomoo_trading_component/moomoo_component/strategy.py").read_text(encoding="utf-8"))
    identities = {node.targets[0].id:ast.literal_eval(node.value) for node in owner.body
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in ("ACTIVE_PAPER_STRATEGY_IDS", "APPLIED_STRATEGY_NAMES")}
    query=next(n.value for n in owner.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="QUERYABLE_STRATEGY_IDS" for t in n.targets))
    identities["QUERYABLE_STRATEGY_IDS"]=tuple(value for node in query.elts for value in
        (identities[node.value.id] if isinstance(node,ast.Starred) else (ast.literal_eval(node),)))
    namespace = {**identities, "st":st, "tr":tr, "escape":escape, "deepcopy":deepcopy}
    visual = ast.parse((_ROOT / "apps/demo_console/components/visuals.py").read_text(encoding="utf-8"))
    text = next(node for node in visual.body if isinstance(node, ast.FunctionDef) and node.name == "text")
    names = {"strategy_label", "short_strategy_label", "_focus_method", "_open_view", "mechanism_html", "method_detail_html", "method_principle_html", "inputs_html", "render_strategy_cases", "method_story", "render_method_explanation", "_focus_catalog_method"}
    assignments = {"WORKSPACE_STRATEGIES", "LEGACY_STRATEGIES", "FLOW_STEPS", "METHOD_EXPLANATIONS", "TRAINING_BOUNDARY", "OUTPUT_LABELS", "METHOD_QUESTIONS", "METHOD_STORIES"}
    body = [text] + [node for node in tree.body if
        isinstance(node, ast.FunctionDef) and node.name in names or
        isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in assignments for target in node.targets)]
    exec(compile(ast.Module(body=body, type_ignores=[]), str(_COMPONENT), "exec"), namespace)
    return namespace, tree


def test_five_methods_keep_native_output_roles_and_original_training_boundary():
    values, _ = _source_namespace()
    methods = values["METHOD_EXPLANATIONS"]
    assert tuple(methods) == values["QUERYABLE_STRATEGY_IDS"] and len(methods) == 8
    assert all(len(row) == 5 for row in methods.values())
    raw = methods["RAW_A2"]
    assert "HGB cross-sectional" in raw[0] and "not portfolio weights" in raw[1]
    assert "loss gradients" in raw[4] and "sums their contributions" in raw[4]
    diag = methods["HGB_DIAG_5"]
    assert "diagonal risk" in diag[0] and "bound policy" in diag[3]
    assert all(term in diag[4] for term in ("variance", "turnover costs", "weights and cash"))
    elastic = methods["R10_DIRECT_MEAN4_ELASTICNET_MID"]
    ridge = methods["R10_DIRECT_H5_RIDGE_MID"]
    for row in (elastic, ridge):
        assert "action-value" in row[0] and "not stock ranks" in row[1]
        assert "HOLD units" in row[2] and "frozen scalers" in row[3]
        assert all(word not in " ".join(row).lower() for word in ("5-day", "five-day", "outperform"))
    assert "L1 and L2" in elastic[4] and "can set coefficients to zero" in elastic[4]
    assert "L2 penalty" in ridge[4] and "without the L1" in ridge[4]
    assert elastic[4] != ridge[4]
    gross = methods["R7_GROSS_LINEAR"]
    assert "linear classifier" in gross[0] and "requested" in gross[1]
    assert all(term in gross[4] for term in ("logistic", "probabilities", "five exposure classes", "does not predict stock returns"))
    boundary = values["TRAINING_BOUNDARY"]
    assert all(term in boundary for term in ("before 2026-01-01", "earlier component cutoffs", "descriptive", "not used for tuning"))
    # Code-only identity and classifier guards support the editorial distinction.
    inputs = ast.parse((_ROOT / "scripts/daily_recommendation_inputs.py").read_text(encoding="utf-8"))
    model_id = next(ast.literal_eval(node.value) for node in inputs.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "MODEL_ID" for target in node.targets))
    assert model_id == "A2_HGB"
    gross_owner = (_ROOT / "scripts/research/a2/training/stateful_decision_models.py").read_text(encoding="utf-8")
    assert 'linear="logistic"' in gross_owner and "action = probability.argmax(axis=1)" in gross_owner
    assert 'result["gross"] = action / 4.' in gross_owner


@pytest.mark.parametrize("language",("en","zh","ja"))
@pytest.mark.parametrize("presentation",(True,False))
def test_story_renderer_translates_and_preserves_original_case_routes(language,presentation):
    for focused in ("RAW_A2","HGB_DIAG_5","R10_DIRECT_MEAN4_ELASTICNET_MID","R10_DIRECT_H5_RIDGE_MID","R7_GROSS_LINEAR"):
        state={"workspace_strategy":focused,"decision_date":"2025-12-02","workspace_sample":"historical"}
        before=deepcopy(state);st=MagicMock();st.session_state=state
        st.expander.return_value.__enter__.return_value.open=False
        values,_=_source_namespace(st);render=MagicMock();values["render_method_explanation"]=render
        with language_scope(language):
            story=values["method_story"](focused)
            detail=unescape(values["method_detail_html"](focused));principle=unescape(values["method_principle_html"](focused))
            assert all(tr(story[k]) in detail for k in ("question","summary","output","portfolio"))
            assert tr(story["technical"]) in principle and principle.count(tr(story["technical"]))==1
            values["render_strategy_cases"]({},presentation)
            render.assert_called_once_with(focused,presentation=presentation,key="strategy_method_explanation")
            actions={call.kwargs["key"]:call for call in st.button.call_args_list}
            for key,view in (("workbench_open_ml","Machine learning"),("workbench_open_decisions","Portfolio")):
                assert actions[key].kwargs["on_click"] is values["_open_view"]
                assert actions[key].kwargs["args"]==(view,focused)
        assert state==before


def test_output_labels_preserve_the_five_distinct_native_roles():
    values, _ = _source_namespace()
    assert {sid: values["OUTPUT_LABELS"][sid] for sid in values["ACTIVE_PAPER_STRATEGY_IDS"]} == {
        "RAW_A2":"Stock scores", "HGB_DIAG_5":"Weights and cash",
        "R10_DIRECT_MEAN4_ELASTICNET_MID":"Action proposals",
        "R10_DIRECT_H5_RIDGE_MID":"Action proposals", "R7_GROSS_LINEAR":"Gross exposure"}


@pytest.mark.parametrize("opened",(False,True))
def test_optional_safeguards_remain_lazy_and_story_is_not_duplicated(opened):
    st=MagicMock();st.session_state={"workspace_strategy":"RAW_A2"}
    panels={"workbench_inputs":MagicMock(),"workbench_other_methods":MagicMock()}
    for key,panel in panels.items():panel.open=opened if key=="workbench_inputs" else False;panel.__enter__.return_value=panel
    st.expander.side_effect=lambda *a,**kw:panels[kw["key"]]
    values,_=_source_namespace(st);render=MagicMock();values["render_method_explanation"]=render
    inputs=MagicMock(wraps=values["inputs_html"]);values["inputs_html"]=inputs
    values["render_strategy_cases"]({});render.assert_called_once();assert inputs.call_count==int(opened)
    assert not st.dataframe.called and not st.metric.called
