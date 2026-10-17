"""Tiny owner-ref observer and actual refresh function, with no UI/data imports."""
import ast
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from apps.demo_console.adapters import new_strategy_replay_reader as reader


def test_reference_observer_never_opens_manifest_and_has_stable_bad_identity(tmp_path):
    pointer=tmp_path/"latest.json"
    assert reader.publication_observation_sha256(pointer)=="NO_PUBLICATION"
    pointer.write_text(json.dumps({"path":str(tmp_path/"not_created_manifest.json"),"sha256":"12"*32}))
    first=reader.publication_observation_sha256(pointer)
    assert len(first)==64 and first==reader.publication_observation_sha256(pointer)
    pointer.write_text(json.dumps({"sha256":"34"*32,"path":str(tmp_path/"not_created_manifest.json")}))
    assert reader.publication_observation_sha256(pointer)!=first
    for payload in (b"bad JSON",b"[1]",b"x"*4097):
        pointer.write_bytes(payload)
        assert reader.publication_observation_sha256(pointer)=="INVALID_POINTER"


class Rerun(Exception):
    pass


def refresh(state, observations, *, clicked=True):
    app=Path(__file__).parents[1]/"app.py"
    tree=ast.parse(app.read_text(encoding="utf8"))
    function=deepcopy(next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=="_refresh_published_data"))
    function.decorator_list=[]
    function.body=[node for node in function.body if not isinstance(node,ast.ImportFrom)]
    calls=[]
    def rerun():
        calls.append("rerun")
        raise Rerun()
    def observed():
        calls.append("owner_ref")
        return next(observations)
    namespace={"st":SimpleNamespace(session_state=state,rerun=rerun,sidebar=SimpleNamespace(
        button=lambda *args,**kwargs:clicked,
        info=lambda message:calls.append(("info",message)),
        error=lambda message:calls.append(("error",message)))),"tr":lambda source:source,
        "new_strategy_replay_reader":SimpleNamespace(publication_observation_sha256=observed),
        "selected_strategies_reader":SimpleNamespace(STRATEGY_IDS=("HGB_DIAG_5","HGB_FACTOR_5"),
            package_observation_sha256=lambda:"same_old_package"),
        "workspace_reader":SimpleNamespace(LATEST="latest"),
        "updated_research_reader":SimpleNamespace(binding=lambda:pytest.fail("unneeded legacy read"))}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),str(app),"exec"),namespace)
    return namespace["_refresh_published_data"],calls


def test_new_three_pointer_changes_rerun_once_even_with_hgb_focus():
    state={"workspace_sample":"test_2026","workspace_strategy":"HGB_DIAG_5","_selected_strategy_binding_seen":"same_old_package"}
    run,calls=refresh(state,iter(["NO_PUBLICATION","new_owner_ref","new_owner_ref"]))
    run()
    assert "rerun" not in calls
    with pytest.raises(Rerun):run()
    run()
    assert calls.count("rerun")==1 and state["_new_strategy_extension_binding_seen"]=="new_owner_ref"


def test_bad_pointer_fallback_does_not_repeat_rerun_and_historical_page_does_not_observe():
    state={"workspace_sample":"test_2026","workspace_strategy":"R7_GROSS_LINEAR","_new_strategy_extension_binding_seen":"old_ref"}
    run,calls=refresh(state,iter(["INVALID_POINTER","INVALID_POINTER","INVALID_POINTER"]))
    with pytest.raises(Rerun):run()
    run();run()
    assert calls.count("rerun")==1
    state["workspace_sample"]="historical"
    run()
    assert calls.count("owner_ref")==3


def test_idle_research_refresh_has_no_timer_or_publication_reads():
    app=Path(__file__).parents[1]/"app.py"
    tree=ast.parse(app.read_text(encoding="utf8"))
    function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=="_refresh_published_data")
    assert not function.decorator_list
    state={"workspace_sample":"test_2026","_new_strategy_extension_binding_seen":"old_ref"}
    before=state.copy()
    run,calls=refresh(state,iter(()),clicked=False)
    for _ in range(5):run()
    assert calls==[] and state==before
    assert 'reload_published_cache' in ast.unparse(function)


def test_explicit_cache_check_reports_unchanged_without_data_or_model_load():
    state={"workspace_sample":"test_2026","workspace_strategy":"HGB_DIAG_5",
           "_selected_strategy_binding_seen":"same_old_package",
           "_new_strategy_extension_binding_seen":"same_owner"}
    run,calls=refresh(state,iter(["same_owner"]))
    run()
    assert ("info","Published cache checked. No changed source binding was detected.") in calls
    assert "rerun" not in calls


def test_failed_binding_read_reports_error_and_preserves_display_context():
    state={"workspace_sample":"historical","workspace_strategy":"RAW_A2",
           "decision_date":"2025-08-11","_workspace_binding_seen":("latest","old")}
    run,calls=refresh(state,iter(()))
    def failure():
        raise OSError("synthetic unavailable")
    run.__globals__["updated_research_reader"].binding=failure
    before=state.copy()
    run()
    assert ("error","Published cache could not be verified. The existing display is retained.") in calls
    assert state==before and "rerun" not in calls


def test_changed_cache_feedback_survives_the_requested_rerun_once():
    state={"workspace_sample":"test_2026","workspace_strategy":"HGB_DIAG_5",
           "_new_strategy_extension_binding_seen":"old"}
    run,calls=refresh(state,iter(["new"]))
    with pytest.raises(Rerun): run()
    idle,idle_calls=refresh(state,iter(()),clicked=False)
    idle()
    assert any(isinstance(c,tuple) and c[0]=="info" for c in idle_calls)
    assert "_published_cache_notice" not in state


def test_unavailable_selected_binding_rechecks_once_and_reports_error_after_rerun():
    state={"workspace_strategy":"HGB_DIAG_5","_selected_strategy_binding_seen":"old"}
    run,calls=refresh(state,iter(()))
    def failure():
        raise ValueError("synthetic invalid publication")
    run.__globals__["selected_strategies_reader"].package_observation_sha256=failure
    with pytest.raises(Rerun): run()
    assert state["_selected_strategy_binding_seen"]=="UNAVAILABLE"
    assert state["_published_cache_notice_level"]=="error"
    idle,idle_calls=refresh(state,iter(()),clicked=False)
    idle()
    expected="A published source is unavailable. Records must pass their original verification checks before use."
    assert ("error",expected) in idle_calls
    assert not any(isinstance(c,tuple) and c[0]=="info" for c in idle_calls)
    run,calls=refresh(state,iter(()))
    run.__globals__["selected_strategies_reader"].package_observation_sha256=failure
    run()
    assert ("error",expected) in calls and "rerun" not in calls


def test_explicit_control_container_owns_feedback_and_button_without_sidebar_escape():
    state={"_published_cache_notice":"synthetic notice"}
    run,calls=refresh(state,iter(()),clicked=False)
    target_calls=[]
    target=SimpleNamespace(
        button=lambda *args,**kwargs:target_calls.append(("button",kwargs["key"])) or False,
        info=lambda message:target_calls.append(("info",message)),
        error=lambda message:target_calls.append(("error",message)))
    run(target=target)
    assert calls == []
    assert target_calls == [("info","synthetic notice"),("button","reload_published_cache")]
    assert "_published_cache_notice" not in state
