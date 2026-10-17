from pathlib import Path
import pandas as pd
import pytest
from scripts.research.a2.inference.consensus_current_inputs import bind_pool


def fixtures():
    schedule = pd.DataFrame([dict(snapshot_id="q2", quarter="2026Q2", effective_at="2026-09-10T20:00:00Z", institution_count=25), dict(snapshot_id="future", quarter="2026Q3", effective_at="2026-11-20T21:00:00Z", institution_count=25)])
    members = pd.DataFrame([dict(snapshot_id=sid, cusip=f"{i:09d}", consensus_rank=i+1) for sid in ("q2", "future") for i in range(100)])
    mapped = pd.DataFrame([dict(cusip=f"{i:09d}", security_id=f"{i:09d}", ticker=f"T{i}") for i in range(100)])
    return schedule, members, mapped


def test_current_pool_uses_exact_prior_snapshot_and_mapping():
    s,m,ids = fixtures()
    schedule, selected, ledger, identity = bind_pool(s,m,ids,"2026-10-12","2026Q2")
    assert len(selected)==100 and selected.source_snapshot_id.eq("q2").all()
    assert selected.consensus_rank.tolist()==list(range(1,101))
    assert identity.is_max_group.all() and set(identity.security_id)==set(ids.security_id)
    assert ledger.target_date.iloc[0]==pd.Timestamp("2026-10-12")
    assert schedule.source_effective_at.iloc[0]=="2026-09-10T20:00:00Z"


def test_missing_mapping_never_replaces_or_reranks_pool():
    s,m,ids=fixtures()
    with pytest.raises(ValueError,match="MAPPING_MISSING"):
        bind_pool(s,m,ids.iloc[:-1],"2026-10-12","2026Q2")


def test_future_snapshot_does_not_change_current_pool():
    s,m,ids=fixtures()
    assert bind_pool(s,m,ids,"2026-10-12","2026Q2")[1].source_snapshot_id.unique().tolist()==["q2"]
    with pytest.raises(ValueError,match="QUALIFIED_NEW_QUARTER"):
        bind_pool(s,m,ids,"2026-11-02","2026Q3")


def test_duplicate_current_security_identity_rejects():
    s,m,ids=fixtures();ids.loc[1,"security_id"]=ids.loc[0,"security_id"]
    with pytest.raises(ValueError,match="IDENTITY_DUPLICATE"):
        bind_pool(s,m,ids,"2026-10-12","2026Q2")


@pytest.mark.parametrize("day",["2025-12-31","2027-01-01"])
def test_input_calendar_is_2026_only(day):
    with pytest.raises(ValueError,match="CALENDAR_BOUNDARY"):
        bind_pool(*fixtures(),day,"2026Q2")


def synthetic_paths(tmp_path):
    from scripts.common.storage_paths import StoragePaths, validate
    names = ("repo_root", "data_root", "cache_root", "daily_root", "backtest_root", "results_root", "envs_root")
    paths = StoragePaths(**{name: tmp_path / name for name in names})
    validate(paths)
    return paths


def write_document(path, value):
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


@pytest.mark.parametrize("native_route", [False, True])
def test_raw32_recovery_creates_guarded_daily_directory_before_inference(tmp_path, monkeypatch, native_route):
    from scripts.common import storage_paths
    from scripts import daily_recommendation, daily_recommendation_inputs
    from scripts.research.a2.inference import consensus_current_inputs as source, historical_top40
    from scripts.research.a2.training.stateful_inputs import FEATURES
    from scripts.storage import storage_r2a

    paths = synthetic_paths(tmp_path)
    signal = "2026-10-09"
    report_dir = paths.daily_root / "A2_today_recommendation" / "runs" / "20261009T010000"
    write_document(report_dir / "rehab_receipt.json", {"synthetic_only": True})
    universe_dir = paths.daily_root / "universe" / "accepted"
    universe_dir.mkdir(parents=True)
    mapped_path = universe_dir / "mapped_members.parquet"
    pd.DataFrame([dict(ticker="T0", security_id="000000000")]).to_parquet(mapped_path, index=False)
    acquisitions = {"synthetic_only": True}
    report = dict(report_path=str(report_dir / "report.json"), acquisitions=acquisitions,
                  universe=dict(report_path=str(universe_dir / "receipt.json"),
                                universe_members_sha256=source.digest(mapped_path)))
    work = paths.daily_root / "A2_consensus_paper" / "work" / signal
    routed_acquisitions = {"qualified_native_inputs": True} if native_route else acquisitions
    if native_route:
        report.update(native_market_publication={"status": "PUBLISHED"}, native_current_tail={"result_count": 1})
        write_document(work / "raw32" / signal / "frozen_raw32_features_binding.json", {"status": "READY", "must_remain": "incomplete_previous_snapshot"})
    monkeypatch.setattr(daily_recommendation, "prediction_after_native_publication", lambda *args: routed_acquisitions)
    guards = []
    original_guard = storage_paths.assert_safe_output_path

    def checked_guard(path, **kwargs):
        original_guard(path, **kwargs)
        guards.append((path, kwargs["kind"]))

    monkeypatch.setattr(storage_paths, "assert_safe_output_path", checked_guard)
    monkeypatch.setattr(daily_recommendation_inputs, "load_frozen_binding", lambda repo: {"synthetic_only": True})
    monkeypatch.setattr(historical_top40, "load_sessions", lambda supplied: ([signal], {}))
    monkeypatch.setattr(storage_r2a, "DataStore", lambda supplied: object())
    calls = []

    def fake_predict(binding, universe, target, sessions, current_acquisitions, store, rehab, *, output_dir):
        assert binding == {"synthetic_only": True}
        assert universe["current"] is True and universe["members"][0]["ticker"] == "T0"
        assert target == signal and sessions == [signal]
        assert current_acquisitions is routed_acquisitions and rehab == {"synthetic_only": True}
        if native_route:
            assert output_dir.name == "native_publication_r1"
        assert output_dir.is_dir() and guards == [(output_dir, "daily")]
        calls.append(target)
        row = dict(trade_date=pd.Timestamp(signal), ticker="T0", security_id="000000000")
        row.update({name: 1.0 for name in FEATURES})
        frame = pd.DataFrame([row])
        feature_path = output_dir / "frozen_raw32_features.parquet"
        frame.to_parquet(feature_path, index=False)
        write_document(output_dir / "frozen_raw32_features_binding.json",
                       dict(status="READY", signal_date=signal, path=str(feature_path),
                            sha256=source.digest(feature_path), columns=list(frame.columns)))

    monkeypatch.setattr(daily_recommendation, "predict_current", fake_predict)
    frame, binding = source._feature_frame(paths, report, signal, work)
    assert calls == [signal] and binding["signal_date"] == signal
    assert frame.trade_date.tolist() == [pd.Timestamp(signal)]
    assert set(FEATURES) <= set(frame.columns)
    repeated, reused = source._feature_frame(paths, report, signal, work)
    pd.testing.assert_frame_equal(repeated, frame)
    assert calls == [signal] and reused == binding


def test_historical_report_projects_large_acquisitions_without_outcome_fields(tmp_path, monkeypatch):
    from scripts.research.a2.inference import consensus_current_inputs as source

    paths = synthetic_paths(tmp_path)
    signal = "2026-10-09"
    report_path = paths.daily_root / "A2_today_recommendation" / "runs" / "20261009T010000" / "report.json"
    acquisitions = {"synthetic_input_binding": "x" * 80000}
    fields = dict(status="READY", data_date=signal, generated_at="2026-10-10T01:00:00Z",
                  report_path=str(report_path), universe={"synthetic_only": True}, acquisitions=acquisitions,
                  frozen_raw32_features={"status": "READY", "signal_date": signal})
    write_document(report_path, dict(fields, performance={"synthetic_skipped": "x" * 200000},
                                    labels=[{"synthetic_skipped": 42}]))
    history = paths.daily_root / "A2_today_recommendation" / "history" / "20261009T010000.json"
    write_document(history, {key: fields[key] for key in ("status", "data_date", "report_path", "generated_at")})
    monkeypatch.setattr(source, "json_document", lambda *args, **kwargs: pytest.fail("whole report decode is forbidden"))
    result = source._historical_report(paths, signal)
    assert result == fields
    assert len(result["acquisitions"]["synthetic_input_binding"]) > 65536
    assert "performance" not in result and "labels" not in result


def test_historical_report_without_history_uses_only_immutable_accepted_source(tmp_path, monkeypatch):
    from scripts.research.a2.inference import consensus_current_inputs as source

    paths = synthetic_paths(tmp_path)
    signal = "2026-10-09"
    runs = paths.daily_root / "A2_today_recommendation" / "runs"
    accepted_dir = runs / "20261009T010000"
    immutable_path = accepted_dir / "recommendation_source.json"
    fields = dict(status="READY", data_date=signal, report_path=str(accepted_dir / "report.json"),
                  generated_at="2026-10-10T01:00:00Z", universe={"synthetic_only": True},
                  acquisitions={"binding": "original_accepted_input"})
    write_document(immutable_path, fields)
    accepted_ref = dict(path=str(immutable_path), sha256=source.digest(immutable_path))
    write_document(accepted_dir / "report.json",
                   dict(fields, accepted_source=accepted_ref, acquisitions={"binding": "mutable_report_input"},
                        performance={"synthetic_skipped": 42}))
    later = runs / "20261009T020000" / "report.json"
    write_document(later, dict(fields, generated_at="2026-10-10T02:00:00Z",
                               acquisitions={"binding": "unaccepted_input"}))
    monkeypatch.setattr(source, "json_document", lambda *args, **kwargs: pytest.fail("whole report decode is forbidden"))
    result = source._historical_report(paths, signal)
    assert result == fields and result["acquisitions"]["binding"] == "original_accepted_input"


def test_native_metadata_projection_skips_large_tail_details(tmp_path):
    from scripts.research.a2.inference import consensus_current_inputs as source
    path = write_document(tmp_path / "source.json", dict(status="READY", data_date="2026-10-09",
        acquisitions={"saved_input": True}, native_current_tail={"result_count": 4, "unknown": "x" * 100000},
        native_market_publication={"status": "PUBLISHED", "request_sha256": "a" * 64, "unknown": "x" * 100000},
        performance={"never_decode": "x" * 100000}))
    result = source.source_input_fields(path)
    assert result["native_current_tail"] == {"result_count": 4}
    assert result["native_market_publication"] == {"status": "PUBLISHED", "request_sha256": "a" * 64}
    assert "performance" not in result


def test_construction_objects_released_before_original_publication(monkeypatch):
    import weakref
    from scripts.research.a2.inference import consensus_current_inputs as current, consensus_paper
    refs = dict(flags_ref={"path":"synthetic_flags","sha256":"a"*64},
        source_bundle_ref={"path":"synthetic_bundle","sha256":"b"*64}, signal_date="2026-10-14",
        decision_as_of="2026-10-14T20:01:00+00:00", source_extension_ref={"path":"synthetic_proof","sha256":"c"*64})
    observed = []
    class ConstructionFrame:
        pass
    def build(paths, **kwargs):
        transient = ConstructionFrame()
        transient.cycle = transient
        observed.append(weakref.ref(transient))
        return refs.copy()
    def publish(paths, **kwargs):
        assert observed[0]() is None
        assert kwargs == {**refs, "r6_probe_source": {"status":"BLOCKED","reason":"synthetic"}}
        return {"status":"READY","model_fit_calls":0}
    monkeypatch.setattr(current,"_prepare_current_inputs",build)
    from scripts.research.a2.inference import current_r6_probes
    def optional(*args, **kwargs):
        assert observed[0]() is None
        return {"status":"BLOCKED","reason":"synthetic"}
    monkeypatch.setattr(current_r6_probes,"prepare_current_r6_probes",optional)
    monkeypatch.setattr(consensus_paper,"publish_inputs",publish)
    result=current.refresh_current_inputs(object(),current_report={},run_dir=None)
    assert result==dict(status="READY",signal_date=refs["signal_date"],flags_ref=refs["flags_ref"],
        source_extension_ref=refs["source_extension_ref"],publication={"status":"READY","model_fit_calls":0})


def test_accepted_same_day_keeps_base_identity_while_connecting_optional_candidate(monkeypatch):
    from scripts.research.a2.inference import consensus_current_inputs as current, consensus_paper, current_r6_probes
    accepted=dict(status="READY",signal_date="2026-10-14",publication={"path":"synthetic"},reused=True)
    base=dict(flags_ref={"path":"synthetic_flags"},source_bundle_ref={"path":"synthetic_pool"},
        source_extension_ref={"path":"synthetic_extension"},signal_date="2026-10-14",decision_as_of="2026-10-14T20:01:00Z")
    monkeypatch.setattr(current,"_prepare_current_inputs",lambda *a,**kw:accepted)
    monkeypatch.setattr(consensus_paper,"metadata",lambda ref,fields:base.copy())
    def failed_optional(*a,**kw):raise ValueError("synthetic candidate gap")
    monkeypatch.setattr(current_r6_probes,"prepare_current_r6_probes",failed_optional)
    calls=[]
    def publisher(*a,**kw):
        calls.append(kw)
        return dict(status="READY",base_publication_unchanged=True)
    monkeypatch.setattr(consensus_paper,"publish_inputs",publisher)
    result=current.refresh_current_inputs(object(),current_report={},run_dir=None)
    assert result["status"]=="READY" and result["publication"]["base_publication_unchanged"]
    assert {k:v for k,v in calls[0].items() if k!="r6_probe_source"}==base
    assert calls[0]["r6_probe_source"]["status"]=="BLOCKED"
    assert calls[0]["r6_probe_source"]["reason"]=="ValueError"


def test_same_day_cache_hit_does_not_import_feature_or_ranking_stack(tmp_path, monkeypatch):
    import builtins
    from scripts.research.a2.inference import consensus_current_inputs as current, consensus_paper
    paths = synthetic_paths(tmp_path)
    pointer = paths.daily_root / "A2_consensus_paper/latest.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text("{}", encoding="utf-8")
    day = "2026-10-14"
    declared = dict(status="READY", signal_date=day, sha256="synthetic-feature",
        frozen_model_sha256="4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b",
        feature_source_ref={"sha256":"fd4fe78d27bfbf57c89343d60550366ccf7fcbf3d6a65e7ef66f28405d050c19"})
    publication = {"path":"synthetic-publication","sha256":"a"*64}
    extension = {"current_day_proofs":[{"signal_date":day,"feature_ref":{"sha256":declared["sha256"]}}]}
    monkeypatch.setattr(current, "json_document", lambda path: {} if path == pointer else extension)
    monkeypatch.setattr(current, "read_reference", lambda ref: "synthetic-extension")
    monkeypatch.setattr(consensus_paper, "metadata", lambda *args: {"status":"READY","signal_date":day})
    monkeypatch.setattr(consensus_paper, "load_publication", lambda *args: ({"status":"READY", "source_extension_ref":{}}, publication))
    original_import = builtins.__import__
    forbidden = {"numpy", "pandas", "pyarrow.parquet",
        "scripts.research.a2.inference.historical_top40", "scripts.research.a2.inference.stateful_test_inputs"}
    def guarded_import(name, *args, **kwargs):
        if name in forbidden:
            raise AssertionError("Cache hit imported construction stack: " + name)
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    result = current._prepare_current_inputs(paths, current_report={"status":"READY","data_date":day,
        "frozen_raw32_features":declared}, run_dir=None)
    assert result == dict(status="READY", signal_date=day, publication=publication, reused=True)


def test_reuse_only_miss_cannot_fall_through_to_construction(tmp_path, monkeypatch):
    import builtins
    from scripts.research.a2.inference import consensus_current_inputs as current
    paths = synthetic_paths(tmp_path)
    report = dict(status="READY", data_date="2026-10-14", frozen_raw32_features=dict(
        status="READY", signal_date="2026-10-14", sha256="synthetic",
        frozen_model_sha256="4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b",
        feature_source_ref={"sha256":"fd4fe78d27bfbf57c89343d60550366ccf7fcbf3d6a65e7ef66f28405d050c19"}))
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name in {"numpy", "pandas", "pyarrow.parquet", "scripts.research.a2.inference.historical_top40"}:
            pytest.fail("Recovery miss imported construction stack")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    with pytest.raises(ValueError, match="ACCEPTED_SOURCE_REQUIRED_FOR_RESUME"):
        current._prepare_current_inputs(paths, current_report=report, run_dir=None, reuse_only=True)
    assert not paths.daily_root.exists()


def test_refresh_propagates_reuse_only_to_source_owner(monkeypatch):
    from scripts.research.a2.inference import consensus_current_inputs as current
    calls = []
    def prepare(*args, **kwargs):
        calls.append(kwargs.get("reuse_only"))
        raise ValueError("SYNTHETIC_SOURCE_MISS")
    monkeypatch.setattr(current, "_prepare_current_inputs", prepare)
    with pytest.raises(ValueError, match="SYNTHETIC_SOURCE_MISS"):
        current.refresh_current_inputs(object(), current_report={}, run_dir=None, reuse_only=True)
    assert calls == [True]


@pytest.mark.parametrize("location", ["declared", "recovered", "native_recovered"])
def test_strict_raw32_reuses_existing_bound_frame_without_predictor_import(tmp_path, monkeypatch, location):
    import builtins
    from scripts.research.a2.inference import consensus_current_inputs as current
    paths = synthetic_paths(tmp_path); signal = "2026-10-15"
    work = paths.daily_root / "current_source" / signal
    feature = paths.daily_root / "accepted" / "features.parquet"; feature.parent.mkdir(parents=True)
    frame = pd.DataFrame([dict(trade_date=pd.Timestamp(signal), ticker="SYNTHETIC", value=1.0)])
    frame.to_parquet(feature, index=False)
    binding = dict(status="READY", signal_date=signal, path=str(feature), sha256=current.digest(feature), columns=list(frame))
    report = {}
    if location == "declared": report["frozen_raw32_features"] = binding
    else:
        recovered = work / "raw32" / signal
        if location == "native_recovered":
            recovered /= "native_publication_r1"
            report["native_market_publication"] = {"status":"PUBLISHED"}
        write_document(recovered / "frozen_raw32_features_binding.json", binding)
    original_import = builtins.__import__
    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "scripts.daily_recommendation" and "predict_current" in fromlist:
            pytest.fail("strict recovery imported predictor")
        return original_import(name, globals, locals, fromlist, level)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    observed, ref = current._feature_frame(paths, report, signal, work, allow_raw_recovery=False)
    pd.testing.assert_frame_equal(observed, frame)
    assert ref == binding


def test_strict_current_input_chain_blocks_missing_historical_raw32_before_output(tmp_path, monkeypatch):
    """Run real update -> refresh -> prepare -> feature branches with synthetic files."""
    import builtins
    from scripts import daily_recommendation as daily, daily_recommendation_inputs as inputs
    from scripts.research.a2.inference import consensus_current_inputs as current, consensus_paper, historical_top40
    paths = synthetic_paths(tmp_path); day = "2026-10-16"; history_day = "2026-10-15"
    root = paths.daily_root / "synthetic_inputs"; root.mkdir(parents=True)
    def table(name, frame):
        path = root/name; frame.to_parquet(path, index=False)
        return {"path":str(path), "sha256":current.digest(path)}
    schedule, members, mapped = fixtures()
    mapping = table("mapped_members.parquet", mapped)
    flags = table("flags.parquet", pd.DataFrame([dict(signal_date=pd.Timestamp("2026-10-14"), ticker="T0")]))
    bundle = dict(pool_variant_id="TOP100", selection_rule="MANAGER_COUNT_WEIGHT_SUM", cohort_count=25, excluded_manager=None,
        source_schedule_ref=table("schedule.parquet", schedule), source_members_ref=table("members.parquet", members))
    bundle_path = write_document(root/"bundle.json", bundle)
    monkeypatch.setattr(current, "BUNDLE", bundle_path)
    monkeypatch.setattr(consensus_paper, "BUNDLE_SHA", current.digest(bundle_path))
    monkeypatch.setattr(current, "BASE_FLAGS_REF", flags)
    universe = {"report_path":str(root/"report.json"), "universe_members_sha256":mapping["sha256"], "quarter":"2026Q2"}
    historical = {"status":"READY", "data_date":history_day, "universe":universe}
    monkeypatch.setattr(current, "_historical_report", lambda *args: historical)
    model_sha = "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b"
    feature_sha = "fd4fe78d27bfbf57c89343d60550366ccf7fcbf3d6a65e7ef66f28405d050c19"
    monkeypatch.setattr(inputs, "load_frozen_binding", lambda *a: {"components":{"ALPHA":{"artifacts":[
        {"artifact_id":"model", "path":"synthetic_model", "sha256":model_sha},
        {"artifact_id":"source", "path":"synthetic_features", "sha256":feature_sha}]}}})
    monkeypatch.setattr(historical_top40, "load_sessions", lambda *a: (["2026-10-14",history_day,day], {}))
    monkeypatch.setattr(daily, "predict_current", lambda *a, **kw: pytest.fail("strict path ran Raw inference"))
    original_import = builtins.__import__
    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "scripts.daily_recommendation" and "predict_current" in fromlist:
            pytest.fail("strict path imported Raw inference")
        return original_import(name, globals, locals, fromlist, level)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    report = {"status":"READY", "data_date":day, "universe":universe, "frozen_raw32_features":{
        "status":"READY", "signal_date":day, "path":str(root/"declared.parquet"),
        "frozen_model_sha256":model_sha, "feature_source_ref":{"sha256":feature_sha}}}
    result = daily.update_consensus_paper_inputs(paths, report, root, allow_raw_recovery=False)
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "CURRENT_CONSENSUS_ACCEPTED_RAW32_REQUIRED_NO_RECOVERY:" + history_day
    assert result["model_fit_calls"] == 0 and result["broker_action_allowed"] is False
    assert not (paths.daily_root/"A2_consensus_paper").exists()


@pytest.fixture
def prepared_same_day_flags(tmp_path, monkeypatch):
    """Use the real consumer validator; only immutable frozen fixture pins are stubbed."""
    from copy import deepcopy
    from types import SimpleNamespace
    from scripts import daily_recommendation_inputs as inputs
    from scripts.research.a2.inference import consensus_current_inputs as current, consensus_paper as consumer
    paths = synthetic_paths(tmp_path); signal = "2026-10-16"
    root = paths.daily_root/"synthetic_prepared"; root.mkdir(parents=True)
    def table(name, frame):
        path = root/name; frame.to_parquet(path, index=False)
        return consumer.reference(path)
    fixed = {}
    for name, sha in (("model", "4f7eff07021bef084b0329dac8dabc31e9391c7c4945eb2955dc6c1339dcea0b"),
                      ("source", "fd4fe78d27bfbf57c89343d60550366ccf7fcbf3d6a65e7ef66f28405d050c19"),
                      ("parent", "8598030725df0758336ca6e2a7b559f4c203d0d106e1e79a1064437a2b1dfa06")):
        path = root/(name+".synthetic"); path.write_text("synthetic frozen "+name)
        fixed[name] = {"path":str(path), "sha256":sha}
    original_verify = consumer.verify
    def verify(ref):
        for name, expected in fixed.items():
            if ref.get("path") == expected["path"]:
                assert ref == expected and Path(ref["path"]).read_text() == "synthetic frozen "+name
                return Path(ref["path"])
        return original_verify(ref)
    monkeypatch.setattr(consumer, "verify", verify)
    schedule, members, mapped = fixtures()
    mapping = table("mapped_members.parquet", mapped)
    feature = {**table("raw32.parquet", pd.DataFrame([dict(trade_date=pd.Timestamp(signal), ticker="T0", value=1.0)])),
        "status":"READY", "signal_date":signal, "columns":["trade_date", "ticker", "value"],
        "frozen_model_sha256":fixed["model"]["sha256"], "feature_source_ref":fixed["source"]}
    flags = table("flags.parquet", pd.DataFrame([dict(signal_date=pd.Timestamp(signal), ticker="T0")]))
    bundle = {"pool_variant_id":"TOP100", "selection_rule":"MANAGER_COUNT_WEIGHT_SUM", "cohort_count":25,
        "excluded_manager":None, "source_role":"synthetic historical input", "source_completeness_unknown":True,
        "historical_available_at_bound":False, "source_schedule_ref":table("schedule.parquet", schedule),
        "source_members_ref":table("members.parquet", members)}
    bundle_path = write_document(root/"bundle.json", bundle); bundle_ref = consumer.reference(bundle_path)
    monkeypatch.setattr(current, "BUNDLE", bundle_path); monkeypatch.setattr(consumer, "BUNDLE_SHA", bundle_ref["sha256"])
    monkeypatch.setattr(inputs, "load_frozen_binding", lambda *a: {"components":{"ALPHA":{"artifacts":[
        {"artifact_id":name, **fixed[name]} for name in ("model", "source")]}}})
    prior_flags = table("prior_flags.parquet", pd.DataFrame([dict(signal_date=pd.Timestamp("2026-10-15"), ticker="T0")]))
    prior = dict(schema="CURRENT_CONSENSUS_PAPER_SOURCE_EXTENSION_R1", status="READY", signal_date="2026-10-15",
        flags_ref=prior_flags, source_bundle_ref=bundle_ref, cohort_count=25, pool_variant_id="TOP100",
        selection_rule="MANAGER_COUNT_WEIGHT_SUM", raw_model_ref=fixed["model"], feature_source_ref=fixed["source"], new_fit=0)
    previous_ref = consumer.reference(write_document(root/"previous.json", prior))
    ids = mapped.security_id.tolist()
    proof = dict(schema=prior["schema"], task_id="DEMO_FIVE_STRATEGY_PAPER_20261013_R1", status="READY",
        signal_date=signal, observed_at_utc="2026-10-16T20:01:00+00:00", decision_as_of="2026-10-16T20:01:00+00:00",
        source_bundle_ref=bundle_ref, parent_flags_ref=fixed["parent"], flags_ref=flags, raw_model_ref=fixed["model"],
        feature_source_ref=fixed["source"], new_fit=0, selection_rule="MANAGER_COUNT_WEIGHT_SUM", pool_variant_id="TOP100",
        cohort_count=25, execution_admission_inherited=False, continued_flags_ref=prior_flags, prior_source_extension_ref=previous_ref,
        parent_source_role=bundle["source_role"], parent_source_completeness_unknown=True, parent_historical_available_at_bound=False,
        current_day_proofs=[dict(signal_date=signal, source_snapshot_id="q2", mapping_ref=mapping, feature_ref=feature,
            ordered_pool_security_ids=ids, ranked_pool_security_ids=ids[:40], unranked_pool_security_ids=ids[40:],
            rows=40, ranked_rows=40, input_coverage_status="PARTIAL")])
    extension_path = root/"extension.json"; pointer = paths.daily_root/"A2_consensus_paper/latest_flags.json"
    def seal():
        write_document(extension_path, proof)
        saved = {**deepcopy(proof), "source_extension_ref":consumer.reference(extension_path)}
        write_document(pointer, saved)
        return saved
    saved = seal()
    # A prior-day publication is valid for the old date, not today's completion.
    old = consumer.reference(write_document(root/"old_publication.json", {"status":"READY", "signal_date":"2026-10-15"}))
    write_document(pointer.parent/"latest.json", old)
    report = dict(status="READY", data_date=signal, frozen_raw32_features=deepcopy(feature),
        universe={"report_path":str(root/"universe.json"), "universe_members_sha256":mapping["sha256"]})
    return SimpleNamespace(paths=paths, signal=signal, report=report, proof=proof, saved=saved, seal=seal,
        flags=flags, bundle_ref=bundle_ref, pointer=pointer, previous_ref=previous_ref, extension_path=extension_path)


def test_same_day_prepared_flags_resume_original_publication_without_reconstruction(prepared_same_day_flags, monkeypatch):
    import builtins
    from scripts.research.a2.inference import consensus_current_inputs as current, consensus_paper, current_r6_probes
    state = prepared_same_day_flags
    before = {p:p.read_bytes() for p in (state.pointer, state.extension_path, Path(state.flags["path"]))}
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name in {"scripts.research.a2.inference.historical_top40", "scripts.research.a2.inference.stateful_test_inputs"}:
            pytest.fail("prepared source rebuilt feature/ranking stack")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(current_r6_probes, "prepare_current_r6_probes", lambda *a, **kw: {"status":"READY", "synthetic":True})
    calls = []
    def publish(*a, **kwargs):
        calls.append(kwargs)
        return {"status":"READY", "paper_current_extension":{"status":"READY"}}
    monkeypatch.setattr(consensus_paper, "publish_inputs", publish)
    result = current.refresh_current_inputs(state.paths, current_report=state.report, run_dir=None, allow_raw_recovery=False)
    assert result["status"] == "READY" and len(calls) == 1
    assert calls[0] == {"flags_ref":state.flags, "source_bundle_ref":state.bundle_ref, "signal_date":state.signal,
        "decision_as_of":state.proof["decision_as_of"], "source_extension_ref":state.saved["source_extension_ref"],
        "r6_probe_source":{"status":"READY", "synthetic":True}}
    assert all(p.read_bytes() == value for p, value in before.items())


@pytest.mark.parametrize("damage", ["flags_bytes", "extension_bytes", "prior_bytes", "bundle", "feature", "mapping", "clock", "future_clock", "model"])
def test_same_day_prepared_flags_tamper_or_source_change_fails_closed(prepared_same_day_flags, damage):
    from scripts.research.a2.inference import consensus_current_inputs as current
    state = prepared_same_day_flags
    if damage in {"flags_bytes", "extension_bytes", "prior_bytes"}:
        path = Path(state.flags["path"] if damage == "flags_bytes" else state.previous_ref["path"] if damage == "prior_bytes" else state.extension_path)
        path.write_bytes(path.read_bytes()+b" ")
    elif damage == "bundle":
        saved = dict(state.saved); saved["source_bundle_ref"] = {"path":"foreign", "sha256":"0"*64}; write_document(state.pointer, saved)
    elif damage == "feature": state.report["frozen_raw32_features"]["columns"] = ["different"]
    elif damage == "mapping": state.report["universe"]["universe_members_sha256"] = "0"*64
    elif damage == "clock":
        saved = dict(state.saved); saved["decision_as_of"] = "2026-10-16T20:02:00+00:00"; write_document(state.pointer, saved)
    elif damage == "future_clock":
        state.proof["observed_at_utc"] = state.proof["decision_as_of"] = "2027-01-01T00:00:00+00:00"; state.seal()
    else:
        state.proof["raw_model_ref"] = {"path":"foreign", "sha256":"0"*64}; state.seal()
    with pytest.raises(ValueError):
        current._prepare_current_inputs(state.paths, current_report=state.report, run_dir=None, allow_raw_recovery=False)


def test_same_day_prepared_flags_do_not_authorize_reuse_only_first_publication(prepared_same_day_flags):
    from scripts.research.a2.inference import consensus_current_inputs as current
    state = prepared_same_day_flags
    with pytest.raises(ValueError, match="ACCEPTED_SOURCE_REQUIRED_FOR_RESUME"):
        current._prepare_current_inputs(state.paths, current_report=state.report, run_dir=None, reuse_only=True)


def test_prior_day_flags_keep_original_construction_route(prepared_same_day_flags, monkeypatch):
    import pyarrow.parquet as pq
    from scripts.research.a2.inference import consensus_current_inputs as current
    state = prepared_same_day_flags
    saved = dict(state.saved); saved["signal_date"] = "2026-10-15"; write_document(state.pointer, saved)
    paths = []
    def footer(path):
        paths.append(path)
        raise ValueError("SYNTHETIC_ORIGINAL_CONSTRUCTION_REACHED")
    monkeypatch.setattr(pq, "ParquetFile", footer)
    with pytest.raises(ValueError, match="SYNTHETIC_ORIGINAL_CONSTRUCTION_REACHED"):
        current._prepare_current_inputs(state.paths, current_report=state.report, run_dir=None)
    assert paths == [Path(state.flags["path"])]


@pytest.fixture
def accepted_duration_cache(prepared_same_day_flags, monkeypatch):
    """Real publication, duration and frame readers; frozen final math check is synthetic."""
    from scripts.research.a2.inference import consensus_paper as consumer, current_r6_probes
    state = prepared_same_day_flags; root = state.extension_path.parent
    base = dict(schema=consumer.SCHEMA, status="READY", signal_date=state.signal,
        decision_as_of=state.proof["decision_as_of"], pool_contract=consumer.POOL, model_fit_calls=0,
        label_columns_decoded=0, source_extension_ref=state.saved["source_extension_ref"],
        flags_ref=state.flags, source_bundle_ref=state.bundle_ref,
        input_refs={"current":state.flags, "R10":state.flags, "GROSS":state.flags},
        strategy_status={sid:{"status":"READY"} for sid in consumer.NEW_IDS})
    base_path = write_document(root/"accepted_base.json", base); base_ref = consumer.reference(base_path)
    write_document(state.pointer.parent/"latest.json", base_ref)
    frame_path = root/"duration_frame.parquet"
    expected_frame = pd.DataFrame([dict(signal_date=pd.Timestamp(state.signal), ticker="T0", value=2.0)])
    expected_frame.to_parquet(frame_path, index=False); frame_ref = consumer.reference(frame_path)
    r6_source = dict(schema="CURRENT_R6_PROBE_SOURCE_V1", status="READY", signal_date=state.signal,
        decision_as_of="2026-10-16T20:02:00+00:00", flags_ref=state.flags, source_bundle_ref=state.bundle_ref)
    qualification = dict(source_refs={"flags":state.flags, "pool":state.bundle_ref}, synthetic_only=True)
    proof = dict(schema="CURRENT_CONSENSUS_DURATION_INPUT_R1", signal_date=state.signal,
        decision_as_of=r6_source["decision_as_of"], input_ref=frame_ref, r6_probe_source=r6_source, qualification=qualification)
    qualification_path = write_document(root/"duration_qualification.json", proof)
    duration = dict(schema="CURRENT_CONSENSUS_DURATION_SOURCE_V1", candidate_id="R6_DURATION_TREE", status="READY",
        signal_date=state.signal, decision_as_of=r6_source["decision_as_of"], pool_contract=consumer.POOL,
        base_publication_ref=base_ref, flags_ref=state.flags, source_bundle_ref=state.bundle_ref,
        source_extension_ref=state.saved["source_extension_ref"], r6_probe_source=r6_source,
        model_fit_calls=0, execution_admission_inherited=False, historical_strict_pit_claim=False,
        qualification_ref=consumer.reference(qualification_path), input_ref=frame_ref)
    duration_path = root/"accepted_duration.json"; pointer = state.pointer.parent/"duration_latest.json"
    def seal():
        write_document(duration_path, duration)
        ref = consumer.reference(duration_path); write_document(pointer, ref)
        return ref
    duration_ref = seal(); qualified = []
    def validate(paths, *, frame, **kwargs):
        assert paths is state.paths and kwargs == dict(qualification=qualification, r6_probe_source=r6_source,
            signal_date=state.signal, decision_as_of=r6_source["decision_as_of"])
        pd.testing.assert_frame_equal(frame, expected_frame); qualified.append(True)
    monkeypatch.setattr(current_r6_probes, "validate_current_duration_frame", validate)
    monkeypatch.setattr(current_r6_probes, "prepare_current_r6_probes", lambda *a,**kw: pytest.fail("reuse_only rebuilt probe"))
    monkeypatch.setattr(consumer, "publish_inputs", lambda *a,**kw: pytest.fail("reuse_only published or changed pointer"))
    state.base=base; state.base_ref=base_ref; state.duration=duration; state.duration_ref=duration_ref
    state.duration_path=duration_path; state.duration_pointer=pointer; state.qualification_path=qualification_path
    state.frame_path=frame_path; state.seal_duration=seal; state.qualified=qualified
    return state


def test_reuse_only_duration_ready_uses_original_readers_and_keeps_all_bytes(accepted_duration_cache):
    from scripts.research.a2.inference import consensus_current_inputs as current
    state=accepted_duration_cache
    files = [path for path in state.paths.daily_root.rglob("*") if path.is_file()]
    before={path:path.read_bytes() for path in files}
    result=current.refresh_current_inputs(state.paths,current_report=state.report,run_dir=None,reuse_only=True)
    assert result["status"] == "READY" and state.qualified == [True]
    extension=result["publication"].pop("paper_current_extension")
    assert result["publication"] == state.base
    assert extension == dict(status="READY",publication_ref=state.duration_ref,
        decision_as_of=state.duration["decision_as_of"],reused=True,reason=None)
    assert all(path.read_bytes()==value for path,value in before.items())
    assert set(files)=={path for path in state.paths.daily_root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("failure",["missing", "blocked", "frame_hash", "qualification_hash", "future_clock", "base_binding"])
def test_reuse_only_optional_failure_preserves_base_and_all_cache_bytes(accepted_duration_cache,failure):
    from scripts.research.a2.inference import consensus_current_inputs as current
    state=accepted_duration_cache
    if failure=="missing": state.duration_pointer.unlink()
    elif failure=="blocked":
        state.duration.update(status="BLOCKED",reason="CONSENSUS_RESOURCE_FLOOR",input_ref=None,qualification_ref=None)
        state.duration_ref=state.seal_duration()
    elif failure in {"frame_hash","qualification_hash"}:
        path=state.frame_path if failure=="frame_hash" else state.qualification_path
        path.write_bytes(path.read_bytes()+b" ")
    elif failure=="future_clock":
        state.duration["decision_as_of"]=state.duration["r6_probe_source"]["decision_as_of"]="2027-01-01T00:00:00+00:00"
        state.seal_duration()
    else:
        state.duration["base_publication_ref"]={"path":"foreign","sha256":"0"*64};state.seal_duration()
    before={path:path.read_bytes() for path in state.paths.daily_root.rglob("*") if path.is_file()}
    result=current.refresh_current_inputs(state.paths,current_report=state.report,run_dir=None,reuse_only=True)
    extension=result["publication"].pop("paper_current_extension")
    assert result["status"]=="READY" and result["publication"]==state.base
    assert extension["status"]=="BLOCKED" and extension["reason"] and not state.qualified
    if failure=="blocked":
        assert extension["publication_ref"]==state.duration_ref and extension["decision_as_of"]==state.duration["decision_as_of"]
    else: assert extension["publication_ref"] is None and extension["decision_as_of"] is None
    assert all(path.read_bytes()==value for path,value in before.items())
    assert set(before)=={path for path in state.paths.daily_root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("failure",["publication_ref", "base_input"])
def test_reuse_only_base_drift_is_hard_failure(accepted_duration_cache,monkeypatch,failure):
    from scripts.research.a2.inference import consensus_current_inputs as current,consensus_paper as consumer
    state=accepted_duration_cache
    if failure=="publication_ref":
        owner=current._prepare_current_inputs
        def changed(*args,**kwargs):
            result=owner(*args,**kwargs)
            result["publication"]={"path":"foreign","sha256":"0"*64}
            return result
        monkeypatch.setattr(current,"_prepare_current_inputs",changed)
    else:
        # Corrupt an input only after source qualification, to reach base byte checking.
        owner=current._prepare_current_inputs
        def changed(*args,**kwargs):
            result=owner(*args,**kwargs)
            path=Path(state.flags["path"]);path.write_bytes(path.read_bytes()+b" ")
            return result
        monkeypatch.setattr(current,"_prepare_current_inputs",changed)
    with pytest.raises(ValueError,match="ACCEPTED_BASE_CHANGED|SOURCE_HASH_CHANGED"):
        current.refresh_current_inputs(state.paths,current_report=state.report,run_dir=None,reuse_only=True)
    assert not state.qualified
