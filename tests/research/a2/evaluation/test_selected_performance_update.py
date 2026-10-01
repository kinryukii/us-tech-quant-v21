import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
BASE = Path(__file__).parents[4]
sys.path.insert(0, "D:/us-tech-quant")
def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, (BASE / "apps/demo_console/tests/test_selected_pit_extension.py" if filename == "test_pit_reader.py" else BASE / "scripts/research/a2/evaluation" / filename))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
update = load("staged_update", "selected_performance_update.py")
producer = load("scripts.research.a2.evaluation.three_strategy_extension", "three_strategy_extension.py")
sys.modules["scripts.research.a2.evaluation.three_strategy_extension"] = producer
reader_tests = load("reader_tests", "test_pit_reader.py")

def fixture(tmp_path):
    package = reader_tests.pit_package()
    package["shared_scores"] = {"historical": []}
    source = tmp_path / "price_input.json"; source.write_text("original")
    ref = producer.reference(source)
    strategies = {sid: deepcopy(package["strategies"].get(sid, package["raw_reference"]))
        for sid in producer.IDS}
    for item in strategies.values(): item["outputs"] = {"daily": deepcopy(ref), "targets": deepcopy(ref)}
    manifest = {"source_id": "NEW_PIT_COMPARISON", "status": "READY", "model_fit_calls": 0,
        "broker_action_allowed": False, "performance_period": deepcopy(package["performance_period"]),
        "requested_end_date": "2026-01-06", "blocked_next": None, "source_refs": [ref],
        "strategies": strategies, "shared_scores_historical": [], "limitations": [],
        "cost_one_way": .0005, "initial_cash_coordinate": 1.}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return package, manifest, path, source

def test_merge_preserves_current_applications_and_frozen_references(tmp_path):
    package, manifest, path, _ = fixture(tmp_path)
    before = deepcopy(package)
    merged = update.merge_extension(package, manifest, path)
    assert package == before
    for sid in package["strategies"]:
        assert merged["strategies"][sid]["application"] == package["strategies"][sid]["application"]
    assert merged["source_refs"]["history/top40.parquet"] == package["source_refs"]["history/top40.parquet"]
    assert merged["performance_extension"]["manifest"] == producer.reference(path)

@pytest.mark.parametrize("change", ["input_hash", "manifest_content", "calendar"])
def test_merge_rejects_mutated_inputs_manifest_or_common_dates(tmp_path, change):
    package, manifest, path, source = fixture(tmp_path)
    if change == "input_hash": source.write_text("mutated")
    elif change == "manifest_content": path.write_text("{}")
    else:
        manifest["strategies"]["HGB_FACTOR_5"]["daily"][0]["date"] = "2026-01-04"
        path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError): update.merge_extension(package, manifest, path)

@pytest.mark.parametrize("status,end,expected", [
    ("READY", "2026-01-06", "READY"), ("PARTIAL", "2026-01-05", "PARTIAL"),
    ("READY", "2026-01-05", "PARTIAL")])
def test_every_daily_update_runs_extension_and_requires_verified_end(tmp_path, monkeypatch, status, end, expected):
    # Exercise the actual coordinator function, with independent expensive producers mocked.
    tree = ast.parse((BASE / "scripts/daily_recommendation.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "update_selected_strategies")
    scope = {"emit": lambda x: None, "Path": Path, "os": __import__("os"),
             "save": lambda path, value: path.write_text(json.dumps(value))}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "daily_hook", "exec"), scope)
    selected = __import__("scripts.research.a2.portfolio.selected_hgb", fromlist=["unused"])
    staged = SimpleNamespace(refresh_selected_performance=Mock(), publish_current_preserving_replay=Mock())
    monkeypatch.setitem(sys.modules, "scripts.research.a2.evaluation.selected_performance_update", staged)
    package = reader_tests.pit_package()
    for item in package["strategies"].values(): item["application"]["signal_date"] = "2026-01-06"
    monkeypatch.setattr(selected, "build_package", Mock(return_value=package))
    extended = deepcopy(package); extended["performance_period"]["end"] = end
    extended["performance_extension"].update(status=status, requested_end_date="2026-01-06")
    staged.refresh_selected_performance.return_value = extended
    paths = SimpleNamespace(daily_root=tmp_path)
    function = scope["update_selected_strategies"]
    for _ in range(2):
        assert function(paths, {"status": "READY", "data_date": "2026-01-06"}, tmp_path)["status"] == expected
    assert staged.refresh_selected_performance.call_count == 2


def test_failure_fallback_keeps_verified_replay_and_new_current_application(tmp_path, monkeypatch):
    old, manifest, manifest_path, _ = fixture(tmp_path)
    old = update.merge_extension(old, manifest, manifest_path)
    output = tmp_path / "latest.json"; output.write_text(json.dumps(old))
    current = reader_tests.pit_package()
    current["shared_scores"] = {"historical": ["new_but_unpublished"]}
    for strategy in current["strategies"].values():
        strategy["application"]["signal_date"] = "2026-01-08"
        strategy["daily"][-1]["date"] = "2026-01-04"
    selected = __import__("scripts.research.a2.portfolio.selected_hgb", fromlist=["unused"])
    publisher = Mock(); monkeypatch.setattr(selected, "publish", publisher)
    merged = update.publish_current_preserving_replay(current, output)
    for sid in current["strategies"]:
        assert merged["strategies"][sid]["daily"] == old["strategies"][sid]["daily"]
        assert merged["strategies"][sid]["application"] == current["strategies"][sid]["application"]
    assert merged["performance_period"] == old["performance_period"]
    assert merged["performance_extension"] == old["performance_extension"]
    assert merged["shared_scores"]["historical"] == old["shared_scores"]["historical"]
    publisher.assert_called_once_with(merged, output)


def gap(ticker):
    return {"status": "PARTIAL", "performance_period": {"end": "2026-01-05"},
            "blocked_next": {"reason": "HELD_EXECUTION_PRICE_MISSING", "keys": [["2026-01-06", ticker]]}}

def test_held_update_dynamic_target_and_updated_inputs_used_until_ready(tmp_path, monkeypatch):
    partial = gap("RETIRED_NEW_NAME")
    ready = {"status": "READY", "blocked_next": None}
    replay = Mock(side_effect=[partial, ready])
    supplement = Mock(return_value=("verified_new_prices", "verified_new_inputs"))
    monkeypatch.setattr(producer, "run_extension", replay)
    monkeypatch.setattr(producer, "supplement_held_prices", supplement)
    paths = SimpleNamespace(repo_root="C:/synthetic_repo")
    result, output = update.replay_with_held_updates(paths, tmp_path, "old_prices", "old_inputs", "2027-02-03")
    assert result is ready and output == tmp_path / "replay_1/manifest.json"
    assert replay.call_args_list[0].kwargs["target_date"] == "2027-02-03"
    assert replay.call_args_list[1].args[:2] == ("verified_new_prices", "verified_new_inputs")
    assert replay.call_args_list[1].kwargs["target_date"] == "2027-02-03"
    assert supplement.call_args.args[3] == ["RETIRED_NEW_NAME"]
    assert supplement.call_args.kwargs == {"target": "2027-02-03", "repo_root": "C:/synthetic_repo"}

def test_failed_qualification_retains_partial_and_real_boundary(tmp_path, monkeypatch):
    partial = gap("X")
    replay = Mock(return_value=partial); supplement = Mock(side_effect=ValueError("UNQUALIFIED_CA"))
    monkeypatch.setattr(producer, "run_extension", replay)
    monkeypatch.setattr(producer, "supplement_held_prices", supplement)
    result, output = update.replay_with_held_updates(SimpleNamespace(repo_root="repo"), tmp_path,
                                                    "prices", "inputs", "2026-01-08")
    assert result is partial and result["status"] == "PARTIAL"
    assert result["performance_period"]["end"] == "2026-01-05"
    assert replay.call_count == supplement.call_count == 1
    assert output == tmp_path / "replay/manifest.json"

def test_same_held_ticker_never_infinite_retry(tmp_path, monkeypatch):
    replay = Mock(return_value=gap("SAME")); supplement = Mock(return_value=("newp", "newi"))
    monkeypatch.setattr(producer, "run_extension", replay)
    monkeypatch.setattr(producer, "supplement_held_prices", supplement)
    result, _ = update.replay_with_held_updates(SimpleNamespace(repo_root="repo"), tmp_path,
                                               "prices", "inputs", "2026-01-08")
    assert result["status"] == "PARTIAL"
    assert replay.call_count == 2 and supplement.call_count == 1

def test_distinct_held_failures_are_bounded_to_eight_replays(tmp_path, monkeypatch):
    replay = Mock(side_effect=[gap("RETIRE" + str(i)) for i in range(10)])
    supplement = Mock(return_value=("newp", "newi"))
    monkeypatch.setattr(producer, "run_extension", replay)
    monkeypatch.setattr(producer, "supplement_held_prices", supplement)
    result, _ = update.replay_with_held_updates(SimpleNamespace(repo_root="repo"), tmp_path,
                                               "prices", "inputs", "2026-01-08")
    assert result["status"] == "PARTIAL"
    assert replay.call_count == 8 and supplement.call_count == 7


def test_partial_tuple_gap_materializes_identically_before_strict_merge(tmp_path):
    package, manifest, path, _ = fixture(tmp_path)
    manifest.update(status="PARTIAL", blocked_next={"reason": "ELIGIBLE_EXECUTION_PRICES_MISSING",
        "keys": [("2026-01-06", "FICO")]})
    published = producer._write_extension_manifest(path, manifest)
    assert published["blocked_next"]["keys"] == [["2026-01-06", "FICO"]]
    assert json.loads(path.read_text()) == published
    merged = update.merge_extension(package, published, path)
    assert merged["performance_extension"]["status"] == "PARTIAL"
    changed = deepcopy(published)
    changed["blocked_next"]["keys"][0][1] = "OTHER"
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="EXTENSION_MANIFEST_CONTENT_CHANGED"):
        update.merge_extension(package, published, path)


def test_held_update_routes_reuse_receipts_without_changing_replay_gate(tmp_path, monkeypatch):
    partial, ready = gap("HOOD"), {"status": "READY", "blocked_next": None}
    replay = Mock(side_effect=[partial, ready]); supplement = Mock(return_value=("same_gate_prices", "same_gate_inputs"))
    monkeypatch.setattr(producer, "run_extension", replay)
    monkeypatch.setattr(producer, "supplement_held_prices", supplement)
    receipts = {"acquisition": {"path": "saved", "sha256": "bound"}}
    result, _ = update.replay_with_held_updates(SimpleNamespace(repo_root="repo"), tmp_path,
        "prices", "inputs", "2026-09-30", held_price_reuse=receipts)
    assert result is ready
    assert supplement.call_args.kwargs["reuse_sources"] is receipts
    assert replay.call_args_list[1].args[:2] == ("same_gate_prices", "same_gate_inputs")
