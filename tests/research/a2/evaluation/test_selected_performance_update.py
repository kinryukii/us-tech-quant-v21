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
    # This fixture is a current build awaiting its first PIT merge, not an accepted prior.
    package.pop("performance_extension", None)
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
    monkeypatch.setattr(selected, "active_policy", lambda paths: (selected.LEGACY_POLICY, paths.daily_root / "A2_selected_hgb/latest.json"))
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
    current.pop("performance_extension", None)  # New current build has no accepted PIT prior yet.
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


def accepted_repair(tmp_path, monkeypatch):
    from scripts.research.a2.portfolio import selected_hgb as selected
    spec = importlib.util.spec_from_file_location("owner_history_fixture",
        BASE / "tests/research/a2/portfolio/test_selected_hgb_history.py")
    history = importlib.util.module_from_spec(spec); spec.loader.exec_module(history)
    old, new, repair = history.repair_package(tmp_path, monkeypatch)
    output = tmp_path / "daily/A2_selected_hgb/latest.json"
    selected.publish(old, output)
    selected.publish(new, output, snapshot_repair=repair)
    return selected, old, new, output


def replay_tail_fixture(tmp_path, monkeypatch):
    selected, old, accepted, output = accepted_repair(tmp_path, monkeypatch)
    _, manifest, manifest_path, source = fixture(tmp_path)
    day = old["shared_scores"]["current"]["signal_date"]
    manifest["performance_period"].update(start="2026-09-23", end=day, days=2)
    for strategy in manifest["strategies"].values():
        strategy["daily"] = [{**strategy["daily"][0], "date": "2026-09-23"},
            {**strategy["daily"][-1], "date": day}]
        strategy["targets"] = [{"signal_date": "2026-09-22", "rows": []},
            {"signal_date": "2026-09-23", "rows": []}]
    manifest["shared_scores_historical"] = [{**row, "signal_date": day}
        for row in old["shared_scores"]["current"]["rows"]]
    manifest_path.write_text(json.dumps(manifest))
    return selected, old, accepted, output, manifest, manifest_path, source


def test_old_replay_unused_tail_uses_only_accepted_repair_and_keeps_every_execution(tmp_path, monkeypatch):
    selected, old, package, output, manifest, path, source = replay_tail_fixture(tmp_path, monkeypatch)
    before_package, before_manifest, before_bytes = deepcopy(package), deepcopy(manifest), path.read_bytes()
    evidence = {ref["path"]: Path(ref["path"]).read_bytes() for key, ref in package["source_refs"].items()
        if key.startswith(("history/", "history_revision/"))}
    merged = update.merge_extension(package, manifest, path, history_root=output.parent / "history")
    expected = [{**row, "signal_date": "2026-09-24"}
        for row in package["shared_scores"]["current"]["rows"]]
    assert merged["shared_scores"]["historical"] == expected
    assert merged["performance_extension"]["manifest"] == producer.reference(path)
    for sid in producer.IDS:
        actual = merged["raw_reference"] if sid == "RAW_A2" else merged["strategies"][sid]
        for key in ("daily", "targets", "summary"):
            assert actual[key] == manifest["strategies"][sid][key]
    assert package == before_package and manifest == before_manifest and path.read_bytes() == before_bytes
    assert all(Path(path).read_bytes() == data for path, data in evidence.items())
    selected.publish(merged, output)
    assert all(Path(path).read_bytes() == data for path, data in evidence.items())


@pytest.mark.parametrize("change", ["used_target", "before_end", "ordinary_base", "bad_receipt", "unbound_receipt", "base_with_fake_receipt"])
def test_old_replay_cannot_rewrite_used_scores_or_invent_repair_permission(tmp_path, monkeypatch, change):
    selected, old, package, output, manifest, path, _ = replay_tail_fixture(tmp_path, monkeypatch)
    if change == "used_target":
        manifest["strategies"]["RAW_A2"]["targets"].append({"signal_date": "2026-09-24", "rows": []})
    elif change == "before_end":
        manifest["performance_period"]["end"] = "2026-09-25"
        for item in manifest["strategies"].values(): item["daily"][-1]["date"] = "2026-09-25"
    elif change == "ordinary_base":
        selected._bind_archive(package, {"path": str(output.parent / "history/2026-09-24.json"),
            "sha256": selected.digest(output.parent / "history/2026-09-24.json"), "signal_date": "2026-09-24"})
        manifest["shared_scores_historical"][0]["raw_score"] += .01
    elif change == "base_with_fake_receipt":
        selected._bind_archive(package, {"path": str(output.parent / "history/2026-09-24.json"),
            "sha256": selected.digest(output.parent / "history/2026-09-24.json"), "signal_date": "2026-09-24"})
        package["source_refs"]["history_revision/2026-09-24.json"] = {"path": str(tmp_path / "unverified_receipt.json"), "sha256": "0"*64}
        package["source_hashes"]["history_revision/2026-09-24.json"] = "0"*64
        manifest["shared_scores_historical"][0]["raw_score"] += .01
    elif change == "bad_receipt":
        Path(package["source_refs"]["history_revision/2026-09-24.json"]["path"]).write_text("{}")
    else:
        package["source_hashes"]["history_revision/2026-09-24.json"] = "0" * 64
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        update.merge_extension(package, manifest, path, history_root=output.parent / "history")


def test_preserving_replay_reuses_identical_merge_gate_for_accepted_tail(tmp_path, monkeypatch):
    selected, old, package, output, manifest, path, _ = replay_tail_fixture(tmp_path, monkeypatch)
    prior = deepcopy(package)
    prior["shared_scores"]["historical"] = []
    # Keep the accepted owner refs while retaining the exact completed replay manifest.
    prior["performance_extension"] = {"source_id": "NEW_PIT_COMPARISON", "manifest": producer.reference(path)}
    output.write_text(json.dumps(prior))
    publisher = Mock(); monkeypatch.setattr(selected, "publish", publisher)
    merged = update.publish_current_preserving_replay(package, output)
    assert merged["shared_scores"]["historical"][0]["raw_score"] == package["shared_scores"]["current"]["rows"][0]["raw_score"]
    assert merged["performance_extension"]["manifest"] == producer.reference(path)
    publisher.assert_called_once_with(merged, output)


def test_merge_manifest_cannot_change_between_parse_and_binding(tmp_path, monkeypatch):
    package, manifest, path, _ = fixture(tmp_path)
    capture = producer._capture_json
    def interleave(target, expected=None):
        value, ref = capture(target,expected)
        if Path(target) == path: path.write_text("{}")
        return value, ref
    monkeypatch.setattr(producer,"_capture_json",interleave)
    with pytest.raises(ValueError,match="SOURCE_HASH_MISMATCH"):
        update.merge_extension(package,manifest,path)


def test_direct_daily_retains_policy_and_saved_receipts_across_held_recovery(tmp_path, monkeypatch):
    from scripts.research.a2.portfolio import selected_hgb as selected
    replay = Mock(side_effect=[gap("HOOD"), {"status": "READY", "blocked_next": None}])
    supplement = Mock(return_value=("verified", "inputs"))
    monkeypatch.setattr(producer, "run_extension", replay)
    monkeypatch.setattr(producer, "supplement_held_prices", supplement)
    receipts = {"acquisition": {"path": "saved", "sha256": "bound"}}
    result, _ = update.replay_with_held_updates(SimpleNamespace(repo_root="repo"), tmp_path,
        "prices", "inputs", "2026-10-02", held_price_reuse=receipts, policy=selected.DIRECT_POLICY)
    assert result["status"] == "READY"
    assert all(call.kwargs["policy"] == selected.DIRECT_POLICY for call in replay.call_args_list)
    assert supplement.call_args.kwargs["reuse_sources"] is receipts
    assert all(call.kwargs["target_date"] == "2026-10-02" for call in replay.call_args_list)


def test_direct_refresh_uses_existing_daily_recovery_owner(tmp_path, monkeypatch):
    import sys
    from scripts.research.a2.evaluation import hgb_policy_alignment as owner
    from scripts.research.a2.portfolio import selected_hgb as selected
    root = tmp_path / "managed_run"
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"data_date": "2026-10-02"}))
    paths = SimpleNamespace(repo_root=tmp_path / "repo")
    monkeypatch.setattr(owner, "frozen_contract", lambda *a: ({}, {}))
    monkeypatch.setattr(owner.subprocess, "check_output", lambda *a, **kw: "f"*40)
    monkeypatch.setitem(sys.modules, "backtest_run_manager", SimpleNamespace(create_backtest_run=lambda *a: root))
    monkeypatch.setattr(owner.extension, "capture_full_prices", Mock(return_value=("prices", "inputs")))
    recovery = Mock(return_value=({"status": "PARTIAL"}, root / "derived/replay_1/manifest.json"))
    canonical_update = __import__("scripts.research.a2.evaluation.selected_performance_update", fromlist=["unused"])
    monkeypatch.setattr(canonical_update, "replay_with_held_updates", recovery)
    package = {"policy_id": selected.DIRECT_POLICY}
    builder = Mock(return_value=package); publisher = Mock()
    monkeypatch.setattr(owner, "direct_package", builder)
    monkeypatch.setattr(selected, "publish", publisher)
    receipts = {"acquisition": {"path": "saved", "sha256": "bound"}}
    output = tmp_path / "daily/latest.json"
    result = owner.refresh_direct(paths, report, output, held_price_reuse=receipts)
    assert result is package
    assert recovery.call_args.kwargs == {"policy": selected.DIRECT_POLICY, "held_price_reuse": receipts}
    assert recovery.call_args.args[1:5] == (root / "derived", "prices", "inputs", "2026-10-02")
    builder.assert_called_once_with(paths, root / "derived/replay_1/manifest.json", report)
    publisher.assert_called_once_with(package, output)


def direct_fixture(tmp_path):
    import pandas as pd
    from scripts.research.a2.portfolio import selected_hgb
    package, manifest, path, _ = fixture(tmp_path)
    package['policy_id'] = manifest['policy_id'] = selected_hgb.DIRECT_POLICY
    package.setdefault('shared_scores', {})['current'] = {'rows': [{'ticker': 'AA', 'pred_hgb': .1}]}
    for sid, strategy in manifest['strategies'].items():
        for kind in ('daily', 'targets'):
            frame = pd.DataFrame({'signal_date': ['2026-01-05'], 'value': [1.]})
            artifact = tmp_path / (sid + '_' + kind + '.parquet'); frame.to_parquet(artifact, index=False)
            strategy['outputs'][kind] = producer.reference(artifact)
    manifest['shared_scores_historical'] = [{'signal_date': '2026-01-05', 'ticker': 'AA', 'pred_hgb': .1}]
    path.write_text(json.dumps(manifest))
    package['performance_extension'] = {'manifest': producer.reference(path)}
    base = tmp_path / 'latest.json'; base.write_text(json.dumps(package))
    return package, manifest, path, base


def test_direct_display_keeps_actual_input_vintages_and_all_target_bytes(tmp_path):
    package, manifest, path, base = direct_fixture(tmp_path)
    original = base.read_bytes()
    paths = SimpleNamespace(backtest_root=tmp_path, daily_root=tmp_path)
    from scripts.common import storage_paths
    from unittest.mock import patch
    with patch.object(storage_paths, 'assert_safe_output_path', return_value=None):
        ref = update.publish_display_performance(paths, base, path)
    assert base.read_bytes() == original
    assert ref['base_package_sha256'] == hashlib.sha256(original).hexdigest()
    assert set(ref) == {'schema', 'policy_id', 'base_package_sha256', 'performance_manifest'}


@pytest.mark.parametrize('changed', ['daily', 'targets', 'scores'])
def test_direct_merge_rejects_changed_already_executed_research_prefix(tmp_path, changed):
    import pandas as pd
    package, manifest, prior, base = direct_fixture(tmp_path)
    package['source_refs']['history/synthetic'] = producer.reference(prior)
    newer = deepcopy(manifest)
    if changed == 'scores':
        newer['shared_scores_historical'][0]['pred_hgb'] = .2
    else:
        sid = next(iter(newer['strategies']))
        artifact = tmp_path / 'changed.parquet'
        pd.DataFrame({'signal_date': ['2026-01-05'], 'value': [2.]}).to_parquet(artifact, index=False)
        newer['strategies'][sid]['outputs'][changed] = producer.reference(artifact)
    with pytest.raises(ValueError, match='DIRECT_EXECUTED_RESEARCH'):
        update._accepted_replay_scores(package, newer)


def repaired_direct_fixture(tmp_path, monkeypatch):
    spec=importlib.util.spec_from_file_location('direct_vintage_fixture',
        BASE/'tests/research/a2/portfolio/test_selected_hgb_history.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module, module.direct_repaired_research_fixture(tmp_path,monkeypatch)


def direct_refresh_fixture(tmp_path, monkeypatch, target='2026-09-25'):
    from scripts.research.a2.evaluation import hgb_policy_alignment as owner
    from scripts.research.a2.portfolio import selected_hgb as selected
    history, (_,prior,manifest,path,output,contract)=repaired_direct_fixture(tmp_path,monkeypatch)
    report=tmp_path/'new_source.json';report.write_text(json.dumps({'data_date':target}))
    monkeypatch.setattr(owner,'frozen_contract',lambda *a: ({'frozen_contract':contract},{}))
    monkeypatch.setattr(owner.extension,'bound_direct_research',lambda *a,**kw:(prior,manifest,producer.reference(path),producer.reference(output)))
    from scripts import daily_recommendation_inputs as calendar
    monkeypatch.setattr(calendar,'load_frozen_binding',lambda *a: {})
    monkeypatch.setattr(calendar,'latest_completed_session',lambda *a: {'target_date':target,
        'sessions':['2026-09-25','2026-09-28']})
    current=history.block_for(prior,target)
    selected._merge_archived_snapshots(current,output.parent/'history',previous=prior)
    builder=Mock(return_value=current);publisher=Mock()
    monkeypatch.setattr(owner,'direct_package',builder);monkeypatch.setattr(selected,'publish',publisher)
    capture=Mock(return_value=('qualified_prices','qualified_inputs'))
    monkeypatch.setattr(owner.extension,'capture_full_prices',capture)
    canonical=__import__('scripts.research.a2.evaluation.selected_performance_update',fromlist=['unused'])
    recovery=Mock(side_effect=ValueError('synthetic replay must be explicitly configured'))
    monkeypatch.setattr(canonical,'replay_with_held_updates',recovery)
    monkeypatch.setattr(owner.subprocess,'check_output',lambda *a,**kw:'e'*40)
    root=tmp_path/'new_run'
    monkeypatch.setitem(sys.modules,'backtest_run_manager',SimpleNamespace(create_backtest_run=lambda *a:root))
    paths=SimpleNamespace(repo_root=tmp_path/'repo')
    return owner, paths, report, output, prior,manifest,path,current,builder,publisher,capture,recovery,root


def test_direct_same_execution_end_reuses_verified_ledger_without_capture_or_replay(tmp_path,monkeypatch):
    owner,paths,report,output,prior,manifest,path,current,builder,publisher,capture,recovery,root=direct_refresh_fixture(tmp_path,monkeypatch)
    original=path.read_bytes()
    result=owner.refresh_direct(paths,report,output)
    assert result is current
    builder.assert_called_once_with(paths,str(path),report)
    publisher.assert_called_once_with(current,output)
    capture.assert_not_called();recovery.assert_not_called()
    assert path.read_bytes()==original and not root.exists()
    assert result['performance_period']==prior['performance_period']


@pytest.mark.parametrize('change',['manifest_bytes','output_hash','unbound_contract','model_fit','incomplete_session'])
def test_direct_same_end_does_not_reuse_unverified_or_future_checkpoint(tmp_path,monkeypatch,change):
    args=direct_refresh_fixture(tmp_path,monkeypatch)
    owner,paths,report,output,prior,manifest,path,current,builder,publisher,capture,recovery,root=args
    if change=='manifest_bytes':path.write_text('{}')
    elif change=='output_hash':Path(manifest['strategies']['HGB_DIAG_5']['outputs']['daily']['path']).write_bytes(b'changed')
    elif change=='unbound_contract':
        prior['source_hashes']['policy/frozen_contract']='0'*64;output.write_text(json.dumps(prior))
    elif change=='model_fit':
        manifest['model_fit_calls']=1;path.write_text(json.dumps(manifest))
        ref=producer.reference(path);prior['performance_extension']['manifest']=ref
        prior['source_refs']['performance_extension/manifest']=ref;prior['source_hashes']['performance_extension/manifest']=ref['sha256']
        output.write_text(json.dumps(prior))
    else:
        from scripts import daily_recommendation_inputs as calendar
        monkeypatch.setattr(calendar,'latest_completed_session',lambda *a: {'target_date':'2026-09-24','sessions':['2026-09-25']})
    with pytest.raises(ValueError):owner.refresh_direct(paths,report,output)
    builder.assert_not_called();capture.assert_not_called();recovery.assert_not_called();publisher.assert_not_called()


@pytest.mark.parametrize('failure',['date_regression','content_prefix','acquisition'])
def test_direct_new_day_attempt_preserves_verified_charts_and_current_when_extension_fails(tmp_path,monkeypatch,failure):
    import pandas as pd
    args=direct_refresh_fixture(tmp_path,monkeypatch,'2026-09-28')
    owner,paths,report,output,prior,manifest,path,current,builder,publisher,capture,recovery,root=args
    newer=deepcopy(manifest)
    if failure=='date_regression':newer['performance_period']['end']='2026-09-24'
    elif failure=='content_prefix':
        artifact=tmp_path/'different_daily.parquet'
        pd.DataFrame({'changed':[123]}).to_parquet(artifact,index=False)
        newer['strategies']['HGB_DIAG_5']['outputs']['daily']=producer.reference(artifact)
    else:capture.side_effect=ValueError('synthetic input denial')
    candidate=root/'derived/replay/manifest.json';candidate.parent.mkdir(parents=True)
    candidate.write_text(json.dumps(newer));recovery.side_effect=None;recovery.return_value=(newer,candidate)
    original=path.read_bytes()
    result=owner.refresh_direct(paths,report,output)
    assert capture.call_count==1
    assert recovery.call_count==(0 if failure=='acquisition' else 1)
    assert result['performance_extension']['status']=='PARTIAL'
    assert result['performance_extension']['requested_end_date']=='2026-09-28'
    assert result['performance_extension']['manifest']==prior['performance_extension']['manifest']
    assert result['performance_period']==prior['performance_period']
    assert result['shared_scores']['current']==current['shared_scores']['current']
    assert 'DIRECT_DAILY_REPLAY_UNVERIFIED' in result['performance_extension']['blocked_next']['reason']
    for sid in prior['strategies']:
        for key in ('daily','targets'):assert result['strategies'][sid][key]==prior['strategies'][sid][key]
    assert path.read_bytes()==original
    publisher.assert_called_once_with(current,output)


def test_future_display_overlay_preserves_research_prefix_with_repaired_cash_vintage(tmp_path,monkeypatch):
    import pandas as pd
    history,(_,package,old,path,base,_)=repaired_direct_fixture(tmp_path,monkeypatch)
    original=base.read_bytes();newer=deepcopy(old)
    newer['performance_period'].update(end='2026-09-28',days=4)
    newer['requested_end_date']='2026-09-28'
    for sid,strategy in newer['strategies'].items():
        strategy['daily'].append({**strategy['daily'][-1],'date':'2026-09-28'})
        strategy['summary'].update(days=4)
        strategy['targets'].append({'signal_date':'2026-09-25','rows':[]})
        for kind in ('daily','targets'):
            output=tmp_path/(sid+'_extended_'+kind+'.parquet')
            pd.DataFrame(strategy[kind]).to_parquet(output,index=False)
            strategy['outputs'][kind]=producer.reference(output)
    candidate=tmp_path/'extended_manifest.json';candidate.write_text(json.dumps(newer))
    from scripts.common import storage_paths
    monkeypatch.setattr(storage_paths,'assert_safe_output_path',lambda *a,**kw:None)
    ref=update.publish_display_performance(SimpleNamespace(backtest_root=tmp_path,daily_root=tmp_path),base,candidate)
    assert ref['performance_manifest']==producer.reference(candidate)
    assert base.read_bytes()==original
    merged=update.merge_extension(package,newer,candidate,history_root=base.parent/'history')
    expected=[{**r,'signal_date':'2026-09-24'} for r in package['shared_scores']['current']['rows']]
    assert [r for r in merged['shared_scores']['historical'] if r['signal_date']=='2026-09-24']==expected
    assert newer['shared_scores_historical']==old['shared_scores_historical']
    assert path.read_bytes()==json.dumps(old).encode()


def test_cross_session_replay_wrapper_passes_exact_immutable_prior_to_original_owner(tmp_path,monkeypatch):
    from scripts.research.a2.portfolio import selected_hgb as selected
    prior={'path':str(tmp_path/'accepted_manifest.json'),'sha256':'a'*64}
    replay=Mock(return_value={'status':'READY','blocked_next':None})
    monkeypatch.setattr(producer,'run_extension',replay)
    result,_=update.replay_with_held_updates(SimpleNamespace(repo_root='repo'),tmp_path,
        'prices','inputs','2026-10-05',policy=selected.DIRECT_POLICY,
        execution_open_manifest='open6',execution_end='2026-10-06',prior_research_manifest=prior)
    assert result['status']=='READY'
    assert replay.call_args.kwargs['prior_research_manifest'] is prior
    assert replay.call_args.kwargs['execution_open_manifest']=='open6'
    assert replay.call_args.kwargs['execution_end']=='2026-10-06'
    assert replay.call_args.kwargs['target_date']=='2026-10-05'



def strict_legacy_refresh_fixture(tmp_path, monkeypatch, target='2026-09-28'):
    spec = importlib.util.spec_from_file_location('legacy_research_tests', BASE/'tests/research/a2/evaluation/test_three_strategy_extension.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    paths, prior, manifest, prior_path, output, displayed, loader = module.legacy_bound_research_fixture(tmp_path, monkeypatch)
    paths.daily_root = tmp_path/'daily'
    report = tmp_path/'source.json'; report.write_text(json.dumps({'status':'READY','data_date':target}))
    from scripts import daily_recommendation_inputs as calendar
    monkeypatch.setattr(calendar,'load_frozen_binding',lambda *a: {})
    monkeypatch.setattr(calendar,'latest_completed_session',lambda *a: {'target_date':target,'sessions':['2026-09-25','2026-09-28']})
    current = deepcopy(prior); current.pop('performance_extension')
    for key in ('performance_extension/manifest',):
        current['source_refs'].pop(key); current['source_hashes'].pop(key)
    capture = Mock(return_value=('qualified_prices','qualified_inputs'))
    canonical_extension = __import__('scripts.research.a2.evaluation.three_strategy_extension',fromlist=['unused'])
    monkeypatch.setattr(canonical_extension,'capture_full_prices',capture)
    monkeypatch.setattr(canonical_extension,'bound_selected_research',lambda *a:(prior,manifest,producer.reference(prior_path),producer.reference(output)))
    replay = Mock(side_effect=ValueError('No producer configured by fixture'))
    monkeypatch.setattr(update,'replay_with_held_updates',replay)
    from scripts.research.a2.portfolio import selected_hgb as selected
    publisher = Mock(); monkeypatch.setattr(selected,'publish',publisher)
    return paths,current,prior,manifest,prior_path,output,report,capture,replay,publisher


@pytest.mark.parametrize('target',['2026-09-25'])
def test_legacy_completed_same_execution_or_newer_opening_keeps_accepted_replay_without_acquisition(tmp_path,monkeypatch,target):
    args = strict_legacy_refresh_fixture(tmp_path,monkeypatch,target)
    paths,current,prior,manifest,prior_path,output,report,capture,replay,publisher = args
    from scripts import daily_recommendation_inputs as calendar
    monkeypatch.setattr(calendar,'latest_completed_session',lambda *a:{'target_date':target,'sessions':[target]})
    evidence = {p:p.read_bytes() for p in (prior_path,output)}
    result = update.refresh_selected_performance(paths,current,report,output)
    assert result['performance_period'] == prior['performance_period']
    assert result['performance_extension']['manifest'] == producer.reference(prior_path)
    assert result['shared_scores']['current'] == current['shared_scores']['current']
    capture.assert_not_called(); replay.assert_not_called(); publisher.assert_called_once_with(result,output)
    assert all(p.read_bytes() == data for p,data in evidence.items())


def test_legacy_new_completed_day_passes_exact_prior_to_original_capture_and_replay(tmp_path,monkeypatch):
    import pandas as pd
    paths,current,prior,manifest,prior_path,output,report,capture,replay,publisher = strict_legacy_refresh_fixture(tmp_path,monkeypatch)
    newer = deepcopy(manifest)
    newer['performance_period'].update(end='2026-09-28',days=4); newer['requested_end_date']='2026-09-28'
    for sid,strategy in newer['strategies'].items():
        strategy['daily'].append({**strategy['daily'][-1],'date':'2026-09-28'})
        strategy['targets'].append({'signal_date':'2026-09-25','rows':[]})
        for kind in ('daily','targets'):
            artifact=tmp_path/(sid+'_continued_'+kind+'.parquet')
            # Preserve every original parquet column and dtype in the executed prefix.
            before = producer._capture_parquet(strategy['outputs'][kind])
            extra = before.iloc[[-1]].copy()
            pd.concat([before,extra],ignore_index=True).to_parquet(artifact,index=False)
            strategy['outputs'][kind]=producer.reference(artifact)
    candidate = tmp_path/'continued_manifest.json'; candidate.write_text(json.dumps(newer))
    replay.side_effect=None; replay.return_value=(newer,candidate)
    result=update.refresh_selected_performance(paths,current,report,output)
    assert capture.call_args.kwargs['prior_research_manifest']==producer.reference(prior_path)
    assert replay.call_args.kwargs['prior_research_manifest']==producer.reference(prior_path)
    assert replay.call_args.kwargs['policy']=='RAW_TOP20_FROZEN_LEGACY'
    assert result['performance_period']['end']=='2026-09-28'
    assert result['strategies']['HGB_DIAG_5']['application']==current['strategies']['HGB_DIAG_5']['application']
    publisher.assert_called_once_with(result,output)


@pytest.mark.parametrize('fault',['daily','targets','scores','output_path','policy','future_session'])
def test_legacy_refresh_cannot_replace_executed_prefix_or_unqualified_authority(tmp_path,monkeypatch,fault):
    import pandas as pd
    from scripts.research.a2.portfolio import selected_hgb as selected
    args = strict_legacy_refresh_fixture(tmp_path,monkeypatch)
    paths,current,prior,manifest,prior_path,output,report,capture,replay,publisher=args
    newer=deepcopy(manifest)
    if fault in {'daily','targets'}:
        before=producer._capture_parquet(newer['strategies']['HGB_DIAG_5']['outputs'][fault])
        before.iloc[0,0]='changed'
        artifact=tmp_path/'changed_prefix.parquet'; before.to_parquet(artifact,index=False)
        newer['strategies']['HGB_DIAG_5']['outputs'][fault]=producer.reference(artifact)
    elif fault=='scores': newer['shared_scores_historical'][0]['pred_hgb']+=.01
    elif fault=='output_path': output=tmp_path/'not_active.json'
    elif fault=='policy': current['policy_id']=selected.DIRECT_POLICY
    else:
        from scripts import daily_recommendation_inputs as calendar
        monkeypatch.setattr(calendar,'latest_completed_session',lambda *a:{'target_date':'2026-09-25','sessions':['2026-09-25','2026-09-28']})
    candidate=tmp_path/'attempted_manifest.json';candidate.write_text(json.dumps(newer))
    replay.side_effect=None;replay.return_value=(newer,candidate)
    original=prior_path.read_bytes()
    with pytest.raises(ValueError):update.refresh_selected_performance(paths,current,report,output)
    publisher.assert_not_called()
    assert prior_path.read_bytes()==original
    if fault in {'output_path','policy','future_session'}:capture.assert_not_called();replay.assert_not_called()


def test_verified_direct_interface_still_refuses_legacy_even_when_research_is_qualified(tmp_path,monkeypatch):
    paths,current,prior,manifest,path,output,report,capture,replay,publisher = strict_legacy_refresh_fixture(tmp_path,monkeypatch)
    assert update.verified_selected_research(prior)[0]==manifest
    with pytest.raises(ValueError,match='DIRECT_RESEARCH_POLICY_REQUIRED'):update.verified_direct_research(prior)



def test_legacy_cannot_reuse_ahead_research_without_original_open_only_authority(tmp_path,monkeypatch):
    args=strict_legacy_refresh_fixture(tmp_path,monkeypatch,'2026-09-24')
    paths,current,prior,manifest,prior_path,output,report,capture,replay,publisher=args
    from scripts import daily_recommendation_inputs as calendar
    monkeypatch.setattr(calendar,'latest_completed_session',lambda *a:{'target_date':'2026-09-24','sessions':['2026-09-24','2026-09-25']})
    with pytest.raises(ValueError,match='FUTURE_EXECUTION_UNBOUND'):
        update.refresh_selected_performance(paths,current,report,output)
    capture.assert_not_called();replay.assert_not_called();publisher.assert_not_called()



@pytest.mark.parametrize('fault',[None,'unbound_manifest','cash_field','future_asof','before_open'])
def test_legacy_ahead_overlay_reuse_requires_the_original_available_next_open_phase(tmp_path,monkeypatch,fault):
    args=strict_legacy_refresh_fixture(tmp_path,monkeypatch,'2026-09-24')
    paths,current,prior,manifest,prior_path,output,report,capture,replay,publisher=args
    from scripts import daily_recommendation_inputs as calendar
    monkeypatch.setattr(calendar,'latest_completed_session',lambda *a:{'target_date':'2026-09-24','sessions':['2026-09-24','2026-09-25']})
    open_path=tmp_path/'open_phase.json';open_path.write_text('synthetic immutable available opening evidence')
    ref=producer.reference(open_path);manifest['source_refs'].append(ref)
    phase={'manifest':ref,'signal_end_date':'2026-09-24','execution_end_date':'2026-09-25',
        'consumer_fields':['open'],'terminal_close_available':False,
        'model_feature_eligibility_granted':False,'as_of_utc':'2026-09-25T14:00:00+00:00'}
    if fault=='unbound_manifest':phase['manifest']={**ref,'sha256':'0'*64}
    elif fault=='cash_field':phase['terminal_close_available']=True
    elif fault=='future_asof':phase['as_of_utc']='2027-01-01T14:00:00+00:00'
    elif fault=='before_open':phase['as_of_utc']='2026-09-25T12:00:00+00:00'
    manifest['execution_open']=phase;manifest['signal_end_date']='2026-09-24'
    prior_path.write_text(json.dumps(manifest));changed=producer.reference(prior_path)
    prior['performance_extension']['manifest']=changed
    prior['source_refs']['performance_extension/manifest']=changed
    prior['source_hashes']['performance_extension/manifest']=changed['sha256']
    original=prior_path.read_bytes()
    if fault:
        with pytest.raises(ValueError):update.refresh_selected_performance(paths,current,report,output)
        publisher.assert_not_called()
    else:
        result=update.refresh_selected_performance(paths,current,report,output)
        assert result['performance_extension']['execution_open']==phase
        assert result['performance_period']==prior['performance_period']
        publisher.assert_called_once_with(result,output)
    capture.assert_not_called();replay.assert_not_called()
    assert prior_path.read_bytes()==original



LEGACY_CAPTURED_PRODUCER = '''
def replay_common(replay, name, spec, panel, prices, runtime, pairs):
    def target(signal, shares, values, nav):
        group = days[signal]
        if spec is None:
            wanted = {str(ticker): .05 for ticker in group.loc[group.raw_rank.le(20), "ticker"]}
            diagnostic = {"raw_targets": wanted.copy(), "solver_failed": False}
        else:
            wanted, diagnostic = runtime["optimizer"].solve(group, shares, values, nav, runtime["risk"], spec, signal)
        return wanted
    return target

def run_extension(prices_path, price_inputs_path, output_dir, *, repo_root="synthetic", feature_paths=(), target_date=None, sessions=None):
    selected.verify_frozen(root)
    runtime = selected._runtime(root)
    for signal, execution in pairs:
        names = panel.loc[panel.signal_date.eq(signal) & panel.raw_rank.le(20), "ticker"]
    for sid in IDS:
        name = "RAW" if sid == "RAW_A2" else sid
        spec = None if sid == "RAW_A2" else runtime["optimizer"].SPECS[sid]
        completed[sid] = replay_common(replay, name, spec, panel, prices, runtime, pairs)
'''


def original_legacy_manifest_schema_fixture(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('original_manifest_schema_tests',BASE/'tests/research/a2/evaluation/test_three_strategy_extension.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    paths,package,manifest,path,output,displayed,loader=module.legacy_bound_research_fixture(tmp_path,monkeypatch)
    canonical_extension=__import__('scripts.research.a2.evaluation.three_strategy_extension',fromlist=['unused'])
    manifest.pop('policy_id');manifest['schema_version']=1;package.pop('policy_id')
    producer_path=path.parent/'producer_source.py';producer_path.write_text(LEGACY_CAPTURED_PRODUCER)
    produced=producer.reference(producer_path)
    manifest['producer_ref']=produced
    manifest['canonical_producer_observation']={'path':str(Path(canonical_extension.__file__).resolve()),'sha256':produced['sha256']}
    manifest['source_refs'].append(produced)
    path.write_text(json.dumps(manifest));ref=producer.reference(path)
    package['performance_extension']['manifest']=ref
    package['source_refs']['performance_extension/manifest']=ref
    package['source_hashes']['performance_extension/manifest']=ref['sha256']
    output.write_text(json.dumps(package));displayed.clear();displayed.update(package)
    displayed.update(package_path=str(output),package_sha256=producer.reference(output)['sha256'])
    return paths,package,manifest,path,output,displayed,loader,canonical_extension


def test_original_pre_policy_manifest_is_qualified_by_immutable_native_raw20_producer_without_mutating_bytes(tmp_path,monkeypatch):
    paths,package,manifest,path,output,displayed,loader,extension=original_legacy_manifest_schema_fixture(tmp_path,monkeypatch)
    originals={p:p.read_bytes() for p in (path,output,Path(manifest['producer_ref']['path']))}
    assert update.research_policy(manifest,producer.reference(path))=='RAW_TOP20_FROZEN_LEGACY'
    assert update.verified_selected_research(package)[0]==manifest
    bound=extension.bound_selected_research(paths,producer.reference(path))
    assert bound[0]==package and bound[1]==manifest and 'policy_id' not in bound[1]
    observed=extension.bound_selected_research(paths)
    assert observed[0] is displayed and observed[1]==manifest
    merged=update.merge_extension(package,manifest,path)
    assert merged['performance_extension']['manifest']==producer.reference(path)
    assert all(p.read_bytes()==data for p,data in originals.items())
    with pytest.raises(ValueError,match='DIRECT_RESEARCH_POLICY_REQUIRED'):update.verified_direct_research(package)


@pytest.mark.parametrize('fault',['producer_bytes','producer_location','canonical_path','canonical_sha','unbound_producer','missing_frozen','solve_seam','price_eligibility','policy_freedom','explicit_none','explicit_unknown','direct_masquerade'])
def test_original_manifest_schema_never_guesses_policy_for_changed_or_unbound_provenance(tmp_path,monkeypatch,fault):
    paths,package,manifest,path,output,displayed,loader,extension=original_legacy_manifest_schema_fixture(tmp_path,monkeypatch)
    captured=Path(manifest['producer_ref']['path'])
    if fault=='producer_bytes':captured.write_text(LEGACY_CAPTURED_PRODUCER+'# changed bytes')
    elif fault=='producer_location':manifest['producer_ref']={**manifest['producer_ref'],'path':str(tmp_path/'outside'/'producer_source.py')}
    elif fault=='canonical_path':manifest['canonical_producer_observation']['path']=str(tmp_path/'other_owner.py')
    elif fault=='canonical_sha':manifest['canonical_producer_observation']['sha256']='0'*64
    elif fault=='unbound_producer':manifest['source_refs'].remove(manifest['producer_ref'])
    elif fault=='missing_frozen':
        from scripts.research.a2.portfolio import selected_hgb as selected
        digest=next(iter(selected.FROZEN_HASHES.values()))
        manifest['source_refs']=[ref for ref in manifest['source_refs'] if ref['sha256']!=digest]
    elif fault in {'solve_seam','price_eligibility','policy_freedom'}:
        code=LEGACY_CAPTURED_PRODUCER
        if fault=='solve_seam':code=code.replace('runtime["optimizer"].solve','selected.solve_targets')
        elif fault=='price_eligibility':code=code.replace('raw_rank.le(20)','raw_rank.le(40)')
        else:code=code.replace('sessions=None):','sessions=None, policy=None):')
        captured.write_text(code);ref=producer.reference(captured)
        manifest['source_refs']=[ref if x==manifest['producer_ref'] else x for x in manifest['source_refs']]
        manifest['producer_ref']=ref;manifest['canonical_producer_observation']['sha256']=ref['sha256']
    elif fault=='explicit_none':manifest['policy_id']=None
    elif fault=='explicit_unknown':manifest['policy_id']='UNRECOGNIZED'
    else:package['policy_id']='HGB_TOP20_RISK_R1'
    path.write_text(json.dumps(manifest));ref=producer.reference(path)
    package['performance_extension']['manifest']=ref;package['source_refs']['performance_extension/manifest']=ref
    package['source_hashes']['performance_extension/manifest']=ref['sha256']
    with pytest.raises(ValueError):update.verified_selected_research(package)


def test_original_manifest_without_bound_manifest_reference_is_not_a_legacy_default(tmp_path,monkeypatch):
    paths,package,manifest,path,output,displayed,loader,extension=original_legacy_manifest_schema_fixture(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='ORIGINAL_SCHEMA_BINDING_REQUIRED'):update.research_policy(manifest)


def test_original_manifest_policy_shape_is_checked_by_the_explicit_prior_replay_seam(tmp_path,monkeypatch):
    from scripts.common import storage_paths
    from scripts.research.a2.portfolio import selected_hgb as selected
    extension=__import__('scripts.research.a2.evaluation.three_strategy_extension',fromlist=['unused'])
    canonical_update=__import__('scripts.research.a2.evaluation.selected_performance_update',fromlist=['unused'])
    path=tmp_path/'original_prior.json';path.write_text('{"schema_version":1}')
    ref=producer.reference(path);prior={'schema_version':1}
    inputs=tmp_path/'inputs.json';inputs.write_text(json.dumps({'price_basis':producer.BASIS,'research_input_owner':ref}))
    monkeypatch.setattr(storage_paths,'resolve',lambda *a:SimpleNamespace())
    monkeypatch.setattr(selected,'verify_frozen',lambda *a:tmp_path)
    monkeypatch.setattr(selected,'_runtime',lambda *a:{})
    monkeypatch.setattr(extension,'bound_selected_research',lambda *a:({},prior,ref,ref))
    class ReachedSharedPolicyQualification(Exception):pass
    reached=Mock(side_effect=ReachedSharedPolicyQualification)
    monkeypatch.setattr(canonical_update,'research_policy',reached)
    with pytest.raises(ReachedSharedPolicyQualification):
        extension.run_extension('unread_prices',inputs,tmp_path/'unpublished',target_date='2026-10-05',policy=selected.LEGACY_POLICY,prior_research_manifest=ref)
    reached.assert_called_once_with(prior,ref)
    assert not (tmp_path/'unpublished').exists()


# The original fallback must preserve a qualified display overlay and live source identity.
def legacy_display_fallback_fixture(tmp_path, monkeypatch):
    import pandas as pd
    from scripts.research.a2.portfolio import selected_hgb as selected
    from apps.demo_console.adapters import selected_strategies_reader as reader
    spec = importlib.util.spec_from_file_location('fallback_bound_research_tests',
        BASE/'tests/research/a2/evaluation/test_three_strategy_extension.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    paths, prior, manifest, manifest_path, output, _, loader = module.legacy_bound_research_fixture(tmp_path, monkeypatch)
    newer = deepcopy(manifest)
    newer['performance_period'].update(end='2026-09-28', days=4)
    newer['requested_end_date'] = '2026-09-28'
    for sid, strategy in newer['strategies'].items():
        strategy['daily'].append({**strategy['daily'][-1], 'date':'2026-09-28'})
        strategy['targets'].append({'signal_date':'2026-09-25','rows':[]})
        for kind in ('daily','targets'):
            artifact = tmp_path/(sid+'_display_'+kind+'.parquet')
            pd.DataFrame(strategy[kind]).to_parquet(artifact,index=False)
            strategy['outputs'][kind] = producer.reference(artifact)
    display_path = tmp_path/'display_manifest.json'
    display_path.write_text(json.dumps(newer),encoding='utf-8')
    displayed = update.merge_extension(prior,newer,display_path,history_root=output.parent/'history')
    displayed.update(package_path=str(output),package_sha256=producer.reference(output)['sha256'])
    loader.return_value = displayed
    overlay = output.parent/'performance_reference.json'
    overlay.write_text(json.dumps({'schema':'HGB_DISPLAY_PERFORMANCE_REFERENCE_V1',
        'policy_id':selected.LEGACY_POLICY,'base_package_sha256':producer.reference(output)['sha256'],
        'performance_manifest':producer.reference(display_path)}),encoding='utf-8')
    spec = importlib.util.spec_from_file_location('fallback_snapshot_tests',
        BASE/'tests/research/a2/portfolio/test_selected_hgb_history.py')
    history = importlib.util.module_from_spec(spec); spec.loader.exec_module(history)
    publisher = Mock(); monkeypatch.setattr(selected,'publish',publisher)
    # Bind through the actual existing qualification seam; only filesystem/producer fixtures are synthetic.
    assert producer.bound_selected_research(paths)[2] == producer.reference(display_path)
    return selected,history,paths,prior,displayed,newer,display_path,output,overlay,loader,publisher


def test_failure_fallback_next_day_reuses_strict_display_instead_of_older_canonical(tmp_path,monkeypatch):
    selected,history,paths,prior,displayed,manifest,path,output,overlay,loader,publisher = legacy_display_fallback_fixture(tmp_path,monkeypatch)
    _,current = history.bound_package(tmp_path,monkeypatch,'2026-09-29')
    current['policy_id'] = selected.LEGACY_POLICY
    original = {p:p.read_bytes() for p in (output,overlay,path)}
    result = update.publish_current_preserving_replay(current,output,paths=paths)
    assert prior['performance_period']['end'] == '2026-09-25'
    assert result['performance_period']['end'] == '2026-09-28'
    assert result['performance_extension']['manifest'] == producer.reference(path)
    assert result['performance_extension']['status'] == 'READY'
    assert result['performance_extension']['requested_end_date'] == '2026-09-28'
    assert result['shared_scores']['current'] == current['shared_scores']['current']
    for sid in selected.STRATEGY_IDS:
        assert result['strategies'][sid]['application'] == current['strategies'][sid]['application']
        assert result['strategies'][sid]['daily'] == displayed['strategies'][sid]['daily']
    publisher.assert_called_once_with(result,output)
    assert all(p.read_bytes() == b for p,b in original.items())
    assert loader.call_count >= 2


def test_failure_fallback_same_day_complete_decision_preserves_canonical_and_overlay_raw_bytes(tmp_path,monkeypatch):
    selected,history,paths,prior,displayed,manifest,path,output,overlay,loader,publisher = legacy_display_fallback_fixture(tmp_path,monkeypatch)
    current = deepcopy(prior)
    current['generated_at'] = '2026-09-29T01:00:00+00:00'
    current.pop('performance_extension')
    original = {p:p.read_bytes() for p in (output,overlay,path)}
    result = update.publish_current_preserving_replay(current,output,paths=paths)
    assert result['performance_period']['end'] == '2026-09-28'
    assert result['shared_scores']['current'] == prior['shared_scores']['current']
    publisher.assert_not_called()
    assert all(p.read_bytes() == b for p,b in original.items())


@pytest.mark.parametrize('fault',['score','application','report_observation','feature_path','rollback'])
def test_failure_fallback_rejects_same_day_decision_or_execution_input_drift_and_rollback(tmp_path,monkeypatch,fault):
    selected,history,paths,prior,displayed,manifest,path,output,overlay,loader,publisher = legacy_display_fallback_fixture(tmp_path,monkeypatch)
    current = deepcopy(prior)
    if fault == 'score': current['shared_scores']['current']['rows'][0]['pred_hgb'] += .000001
    elif fault == 'application':
        app=current['strategies']['HGB_DIAG_5']['application']
        app['rows'][0]['target_weight'] -= .001; app['target_cash_weight'] += .001
    elif fault == 'report_observation':
        current = history.rerun_same_decision(tmp_path,current)
        # The original archive comparison permits this observation, but active execution fallback cannot.
        a=selected._capture_snapshot(current,'a'*64); b=selected._capture_snapshot(prior,'b'*64)
        assert selected._same_snapshot_decision(a,b)
    elif fault == 'feature_path':
        current = history.rerun_same_decision(tmp_path,current)
    else:
        _,current = history.bound_package(tmp_path,monkeypatch,'2026-09-23')
        current['policy_id'] = selected.LEGACY_POLICY
    original = {p:p.read_bytes() for p in (output,overlay,path)}
    with pytest.raises(ValueError,match='LEGACY_FALLBACK_(SAME_SIGNAL|SIGNAL_REGRESSED)'):
        update.publish_current_preserving_replay(current,output,paths=paths)
    publisher.assert_not_called()
    assert all(p.read_bytes() == b for p,b in original.items())


@pytest.mark.parametrize('fault',['active_policy','output_path','incoming_policy','display_policy','display_base_sha','canonical_changed'])
def test_failure_fallback_keeps_original_policy_path_and_canonical_observation_guards(tmp_path,monkeypatch,fault):
    selected,history,paths,prior,displayed,manifest,path,output,overlay,loader,publisher = legacy_display_fallback_fixture(tmp_path,monkeypatch)
    current=deepcopy(prior)
    target=output
    if fault == 'active_policy': monkeypatch.setattr(selected,'active_policy',lambda *a:(selected.DIRECT_POLICY,output))
    elif fault == 'output_path': target=tmp_path/'wrong_output.json'
    elif fault == 'incoming_policy': current['policy_id']=selected.DIRECT_POLICY
    elif fault == 'display_policy': displayed['policy_id']=selected.DIRECT_POLICY
    elif fault == 'display_base_sha': displayed['package_sha256']='0'*64
    else:
        actual=producer.bound_selected_research
        def changed_after_binding(*args,**kwargs):
            result=actual(*args,**kwargs)
            output.write_bytes(output.read_bytes()+b' ')
            return result
        monkeypatch.setattr(producer,'bound_selected_research',changed_after_binding)
    original_overlay=overlay.read_bytes()
    with pytest.raises(ValueError): update.publish_current_preserving_replay(current,target,paths=paths)
    publisher.assert_not_called()
    assert overlay.read_bytes()==original_overlay


def test_daily_failure_routes_original_paths_to_bound_preservation_owner(tmp_path,monkeypatch):
    tree=ast.parse((BASE/'scripts/daily_recommendation.py').read_text(encoding='utf-8'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='update_selected_strategies')
    scope={'emit':lambda x:None,'Path':Path,'os':__import__('os'),'save':lambda p,v:p.write_text(json.dumps(v))}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'daily_fallback_hook','exec'),scope)
    from scripts.research.a2.portfolio import selected_hgb as selected
    paths=SimpleNamespace(daily_root=tmp_path)
    output=tmp_path/'A2_selected_hgb/latest.json';package=reader_tests.pit_package()
    monkeypatch.setattr(selected,'active_policy',lambda p:(selected.LEGACY_POLICY,output))
    monkeypatch.setattr(selected,'build_package',Mock(return_value=package))
    preserve=Mock()
    staged=SimpleNamespace(refresh_selected_performance=Mock(side_effect=ValueError('SYNTHETIC_CHART_FAILURE')),
                           publish_current_preserving_replay=preserve)
    monkeypatch.setitem(sys.modules,'scripts.research.a2.evaluation.selected_performance_update',staged)
    result=scope['update_selected_strategies'](paths,{'status':'READY','data_date':'2026-09-29'},tmp_path)
    assert result == {'status':'BLOCKED','error':'SYNTHETIC_CHART_FAILURE'}
    preserve.assert_called_once_with(package,output,paths=paths)



def test_explicit_offline_repair_fallback_retains_verified_display_and_forwards_original_revision(tmp_path, monkeypatch):
    selected, history, paths, prior, displayed, manifest, path, output, overlay, loader, publisher = legacy_display_fallback_fixture(tmp_path, monkeypatch)
    old, current, repair = history.repair_package(tmp_path, monkeypatch)
    old['policy_id'] = current['policy_id'] = selected.LEGACY_POLICY
    canonical = deepcopy(prior)
    canonical['source_refs'] = deepcopy(old['source_refs'])
    canonical['source_hashes'] = deepcopy(old['source_hashes'])
    canonical['shared_scores']['current'] = deepcopy(old['shared_scores']['current'])
    for sid in selected.STRATEGY_IDS: canonical['strategies'][sid]['application'] = deepcopy(old['strategies'][sid]['application'])
    canonical['performance_extension'] = deepcopy(prior['performance_extension'])
    canonical['source_refs']['performance_extension/manifest'] = deepcopy(prior['performance_extension']['manifest'])
    canonical['source_hashes']['performance_extension/manifest'] = prior['performance_extension']['manifest']['sha256']
    output.write_text(json.dumps(canonical), encoding='utf-8')
    displayed = update.merge_extension(canonical, manifest, path, history_root=output.parent / 'history')
    displayed.update(package_path=str(output), package_sha256=producer.reference(output)['sha256'])
    loader.return_value = displayed
    original = {p: p.read_bytes() for p in (output, overlay, path)}
    result = update.publish_current_preserving_replay(current, output, paths=paths, snapshot_repair=repair)
    assert result['performance_period'] == displayed['performance_period']
    assert result['shared_scores']['current'] == current['shared_scores']['current']
    assert all(result['strategies'][sid]['daily'] == displayed['strategies'][sid]['daily'] for sid in selected.STRATEGY_IDS)
    publisher.assert_called_once_with(result, output, snapshot_repair=repair)
    assert all(p.read_bytes() == content for p, content in original.items())


@pytest.mark.parametrize('fault', ['parent', 'network', 'fit', 'hash'])
def test_explicit_offline_repair_fallback_rejects_forged_receipt_before_publication(tmp_path, monkeypatch, fault):
    selected, history, paths, prior, displayed, manifest, path, output, overlay, loader, publisher = legacy_display_fallback_fixture(tmp_path, monkeypatch)
    old, current, repair = history.repair_package(tmp_path, monkeypatch)
    old['policy_id'] = current['policy_id'] = selected.LEGACY_POLICY
    canonical = deepcopy(prior)
    canonical['source_refs'] = deepcopy(old['source_refs'])
    canonical['source_hashes'] = deepcopy(old['source_hashes'])
    canonical['shared_scores']['current'] = deepcopy(old['shared_scores']['current'])
    for sid in selected.STRATEGY_IDS: canonical['strategies'][sid]['application'] = deepcopy(old['strategies'][sid]['application'])
    canonical['performance_extension'] = deepcopy(prior['performance_extension'])
    canonical['source_refs']['performance_extension/manifest'] = deepcopy(prior['performance_extension']['manifest'])
    canonical['source_hashes']['performance_extension/manifest'] = prior['performance_extension']['manifest']['sha256']
    output.write_text(json.dumps(canonical), encoding='utf-8')
    displayed = update.merge_extension(canonical, manifest, path, history_root=output.parent / 'history')
    displayed.update(package_path=str(output), package_sha256=producer.reference(output)['sha256'])
    loader.return_value = displayed
    if fault == 'hash': repair['sha256'] = '0' * 64
    else:
        audit_path = Path(repair['path']); audit = json.loads(audit_path.read_text())
        if fault == 'parent': audit['parent_inputs'] = []
        elif fault == 'network': audit['network_requests_this_run'] = 1
        else: audit['model_fit_count'] = 1
        audit_path.write_text(json.dumps(audit), encoding='utf-8'); repair.update(producer.reference(audit_path))
        report_path = Path(current['source_refs']['current/report.json']['path'])
        report = json.loads(report_path.read_text()); report['repair_lineage'] = repair
        report_path.write_text(json.dumps(report), encoding='utf-8')
        current['source_refs']['current/report.json'] = producer.reference(report_path)
        current['source_hashes']['current/report.json'] = producer.reference(report_path)['sha256']
    before = output.read_bytes()
    with pytest.raises((ValueError, selected.SelectedStrategyError)):
        update.publish_current_preserving_replay(current, output, paths=paths, snapshot_repair=repair)
    publisher.assert_not_called()
    assert output.read_bytes() == before


def test_offline_repair_requires_bound_paths_even_for_legacy_two_argument_publisher(tmp_path):
    with pytest.raises(ValueError, match='REPAIR_REQUIRES_BOUND_PATHS'):
        update.publish_current_preserving_replay({}, tmp_path / 'unpublished.json', snapshot_repair={'path': 'fake', 'sha256': '0' * 64})


def test_original_legacy_refresh_forwards_offline_repair_to_original_publisher_without_new_rule(tmp_path, monkeypatch):
    paths, current, prior, manifest, prior_path, output, report, capture, replay, publisher = strict_legacy_refresh_fixture(tmp_path, monkeypatch, '2026-09-25')
    repair = {'path': str(tmp_path / 'bound-repair.json'), 'sha256': 'a' * 64}
    result = update.refresh_selected_performance(paths, current, report, output, snapshot_repair=repair)
    capture.assert_not_called(); replay.assert_not_called()
    publisher.assert_called_once_with(result, output, snapshot_repair=repair)
