"""Synthetic acceptance for the finite, zero-fit fixed MAIN extension gate."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import pandas as pd
import pytest
from scripts.common.storage_paths import StoragePaths
from scripts.research.a2.evaluation import consensus_paper_performance as paper

SID = paper.IDS[0]


def fixtures(tmp_path):
    frames = {
        "daily": pd.DataFrame([dict(path_id=SID, date=pd.Timestamp(day), cash=3000., nav=3000., certified_nav=3000., gross_exposure=0., transaction_cost_amount=0., buy_notional=0., sell_notional=0., turnover=0., accounting_qualified=True, receivable_value_usd=0., entitlement_cash_flow_usd=0.) for day in (paper.START, paper.FIRST_EXECUTION, paper.PREFIX_END, "2026-10-09", paper.MAX_END)]),
        "positions": pd.DataFrame([dict(path_id=SID, date=pd.Timestamp(day), ticker="SYNTHETIC", index_units=1., mark=1., market_value=1., weight=.01, holding_age=1, entry_date=pd.Timestamp(paper.START), entry_price=1., entry_execution_open=1., quantity_coordinate_factor=1., stale=False, unknown=False, accounting_qualified=True) for day in (paper.PREFIX_END, paper.MAX_END)]),
        "fills": pd.DataFrame([dict(path_id=SID, signal_date=pd.Timestamp(paper.START), execution_date=pd.Timestamp(day), order_id="synthetic-"+day, ticker="SYNTHETIC", side="BUY", action="BUY", price=1., notional=1., index_units=1., index_units_before=0., index_units_after=1., transaction_cost=0., quantity_coordinate_factor=1.) for day in (paper.PREFIX_END, paper.MAX_END)]),
        "entitlements": pd.DataFrame([dict(path_id=SID, session=pd.Timestamp(day), event_id="synthetic-"+day, event_fingerprint="f"*64, old_security_id="SID", ticker="SYNTHETIC", phase="EX", ex_date=pd.Timestamp(day), record_date=pd.Timestamp(day), pay_date=pd.Timestamp(day), entitled_raw_shares=1., amount_usd=0., spendable_cash_delta=0., source_fingerprint="f"*64, reason="synthetic") for day in (paper.PREFIX_END, paper.MAX_END)]),
    }
    frames["actions"] = pd.DataFrame([dict(path_id=SID, signal_date=pd.Timestamp(paper.PREFIX_END), ticker="SYNTHETIC",
        planned_execution_date=pd.Timestamp("2026-10-09"), target_weight=.01, decision="TARGET")])
    frames["orders"] = pd.DataFrame([dict(path_id=SID, signal_date=pd.Timestamp(paper.PREFIX_END), ticker="SYNTHETIC",
        order_id="synthetic-pending", execution_date=pd.Timestamp("2026-10-09"), status="submitted", target_weight=.01)])
    paths = StoragePaths(**{name:tmp_path/name for name in ("repo_root","data_root","cache_root","daily_root","backtest_root","results_root","envs_root")})
    refs = {}
    for name, frame in frames.items():
        path = paths.backtest_root/"baseline"/(name+".parquet"); path.parent.mkdir(parents=True, exist_ok=True)
        clock, _ = paper.LEDGER_TABLES[name]
        old = frame.loc[frame[clock].le(pd.Timestamp(paper.PREFIX_END))].copy()
        if name == "actions": old.loc[:, "planned_execution_date"] = pd.NaT
        if name == "orders":
            old.loc[:, "execution_date"] = pd.NaT
            old.loc[:, "status"] = "no_next_session"
        old.to_parquet(path, index=False)
        refs[name] = paper.reference(path)
    calendar_file = tmp_path / "calendar-source.json"; calendar_file.write_text('{"synthetic":true}', encoding="utf8")
    calendar_ref = paper.reference(calendar_file)
    proof = dict(helper=paper.CALENDAR_HELPER, calendar_ref=calendar_ref, helper_ref=calendar_ref, provider_ref=calendar_ref,
        production_binding_ref=calendar_ref, target_session=paper.MAX_END, latest_completed_us_session=paper.MAX_END,
        target_session_completed=True, session_close_utc="2026-10-12T20:00:00Z",
        main_sessions=[paper.START, paper.FIRST_EXECUTION, paper.PREFIX_END, "2026-10-09", paper.MAX_END],
        tail_sessions=["2026-10-09", paper.MAX_END])
    authority = paper.PaperAuthority(pd.Timestamp(paper.START),pd.Timestamp(paper.MAX_END),pd.Timestamp("2026-10-13T01:00:00Z"),(SID,),"[]","{}","{}",json.dumps({"source_refs":{},"calendar_qualification":proof}),None,seal=paper._SEAL)
    return paths, frames, refs, authority


def test_prefix_gate_uses_all_four_accepted_tables(tmp_path):
    _, frames, refs, _ = fixtures(tmp_path)
    receipt = paper.compare_prefix(frames, refs, SID)
    assert receipt["status"] == "EXACT_MATCH"
    assert set(receipt["table_comparisons"]) == set(paper.TABLES)
    assert receipt["account_prefix_identity"]["end_session"] == paper.PREFIX_END
    assert receipt["account_prefix_identity"]["row_counts"] == dict(daily=3, positions=1, fills=1, entitlements=1)


@pytest.mark.parametrize("table", list(paper.TABLES))
def test_one_changed_prefix_cell_blocks_publication(tmp_path, table):
    paths, frames, refs, authority = fixtures(tmp_path)
    column = dict(daily="cash", positions="index_units", fills="notional", entitlements="amount_usd")[table]
    frames[table].loc[0,column] += 1e-12
    with patch.object(paper, "accepted_baseline_refs", return_value=refs), pytest.raises(ValueError,match="ACCEPTED_PREFIX_CHANGED:"+table):
        paper.publish_verified(paths,candidate_id=SID,frames=frames,baseline_refs=refs,authority=authority,source_refs={},projection_receipts=[])
    assert not (paths.backtest_root/paper.TASK).exists()
    assert not paths.results_root.exists()


def test_publication_preserves_old_bytes_and_reuses_identical_extension(tmp_path):
    paths, frames, refs, authority = fixtures(tmp_path)
    before = {name:Path(ref["path"]).read_bytes() for name,ref in refs.items()}
    with patch.object(paper, "accepted_baseline_refs", return_value=refs):
        receipt, ref = paper.publish_verified(paths,candidate_id=SID,frames=frames,baseline_refs=refs,authority=authority,source_refs={},projection_receipts=[])
        repeated, same = paper.publish_verified(paths,candidate_id=SID,frames=frames,baseline_refs=refs,authority=authority,source_refs={},projection_receipts=[])
    assert repeated == receipt and same == ref
    assert Path(ref["path"]).is_relative_to(paths.backtest_root)
    assert receipt["end"] == paper.MAX_END and receipt["model_fit_calls"] == 0
    assert receipt["independent_holdout_claim"] is False and receipt["broker_action_allowed"] is False
    assert all(Path(refs[name]["path"]).read_bytes()==data for name,data in before.items())
    assert set(receipt["artifacts"]) == set(paper.LEDGER_TABLES)
    stock = receipt["stock_prefix_comparison"]
    assert stock["status"] == "EXACT_CLOSED_PREFIX_WITH_PENDING_MATURITY"
    assert stock["historical_cutoff_at_or_before_prefix_uses_original_baseline"] is True
    for name in paper.STOCK_TABLES:
        proof = stock["table_comparisons"][name]["pending_maturity"]
        assert proof["changed_rows"] == 1
        assert proof["old_fields_sha256"] != proof["new_fields_sha256"]


@pytest.mark.parametrize("table", list(paper.STOCK_TABLES))
def test_stock_maturity_cannot_change_target_or_skip_the_original_next_open(tmp_path, table):
    _, frames, refs, _ = fixtures(tmp_path)
    frames[table].loc[0, "target_weight"] += 1e-12
    with pytest.raises(ValueError, match="STOCK_ACCEPTED_PREFIX_CHANGED:" + table):
        paper.compare_stock_prefix(frames, refs, SID)
    _, frames, refs, _ = fixtures(tmp_path)
    column = "planned_execution_date" if table == "actions" else "execution_date"
    frames[table].loc[0, column] = pd.Timestamp("2026-10-12")
    with pytest.raises(ValueError, match="PENDING_OPEN_CLOCK_CHANGED"):
        paper.compare_stock_prefix(frames, refs, SID)


def guarded_function(authority, date):
    from scripts.research.a2.evaluation.frozen_test_authority import require_descriptive_decision
    require_descriptive_decision(authority, date, path_id=SID)
    return 2 + 3


def test_projection_preserves_algorithm_and_rejects_outside_new_scope(tmp_path):
    _, _, _, authority = fixtures(tmp_path)
    projected, receipt = paper.guard_projection(guarded_function)
    assert receipt["algorithm_ast_unchanged"] is True and receipt["guard_imports_rebound"] == 1
    assert projected(authority, paper.MAX_END) == 5
    with pytest.raises(ValueError,match="INPUT_OUTSIDE_BOUND"):
        projected(authority,"2027-01-01")
    with pytest.raises(ValueError,match="FINITE_AUTHORITY_REQUIRED"):
        projected(deepcopy(authority),paper.MAX_END)


def test_new_gate_never_accepts_old_or_dictionary_authority():
    with pytest.raises(ValueError,match="FINITE_AUTHORITY_REQUIRED"):
        paper.require_descriptive_decision({"status":"READY","end":paper.MAX_END},paper.MAX_END,path_id=SID)


def input_fixture():
    from scripts.research.a2.training.stateful_inputs import FEATURES
    days = pd.bdate_range("2023-01-03",periods=25).append(pd.DatetimeIndex(["2026-01-02","2026-01-05","2026-01-06"]))
    records=[]
    for date in days:
        for index in range(24):
            row={name:.01 for name in FEATURES}
            row.update(signal_date=date,ticker="T"+str(index),security_id="S"+str(index),feature_available=True,
                is_raw_top20=index<20,new_buy_eligible=index<20,raw_top20_set_complete=True,
                raw_a2_rank=index+1,raw_a2_prediction=.1-index*.001)
            records.append(row)
    return pd.DataFrame(records),days


def test_batched_r10_roles_equal_the_original_per_decision_math():
    from scripts.research.a2.inference.consensus_paper import original_frames
    prefix,calendar=input_fixture()
    roles=paper.full_r10_roles(prefix,calendar,calendar[-1])
    for date in calendar[calendar>=pd.Timestamp(paper.START)]:
        old=original_frames(prefix.loc[prefix.signal_date.le(date)],calendar[calendar<=date],date)
        for name,frame in old.items():
            actual=roles[name].loc[roles[name].signal_date.eq(date)].reset_index(drop=True)
            pd.testing.assert_frame_equal(actual,frame.reset_index(drop=True),check_dtype=True,check_exact=True)


def test_r7_forward_preserves_full_grid_and_releases_one_frozen_model(tmp_path,monkeypatch):
    from scripts.research.a2.inference import consensus_paper as consumer
    from scripts.research.a2.inference.frozen_a94_state import _clone,_DateInputs
    from scripts.research.a2.training import stateful_decision as decision,stateful_decision_models as owner
    import joblib
    flags,calendar=input_fixture();dates=calendar[calendar>=pd.Timestamp(paper.START)]
    builder=_clone(decision.build_samples,inputs=_DateInputs(dates[-1]+pd.Timedelta(days=1)))
    samples,_=builder(flags.loc[flags.signal_date.isin(dates)],pd.DataFrame(columns=decision.LABEL_COLS),dates)
    frame=samples["gross"];_,names=decision.encode_features(frame,decision.GROSS)
    class Model:
        objective="gross";learner="linear";features=names
    states={paper.IDS[2]:{"model_ref":{"path":"synthetic","sha256":"f"*64}}}
    monkeypatch.setattr(consumer,"resource_check",lambda:None)
    monkeypatch.setattr(consumer,"frozen_states",lambda *args:states)
    monkeypatch.setattr(consumer,"verify",lambda ref:Path("synthetic"))
    monkeypatch.setattr(joblib,"load",lambda ref:Model())
    monkeypatch.setattr(owner,"predict",lambda model,x:{"gross":frame.gross_previous_proxy.to_numpy()})
    authority=paper.PaperAuthority(dates[0],dates[-1],pd.Timestamp("2026-10-13T01:00:00Z"),(paper.IDS[2],),"[]","{}","{}","{}",None,seal=paper._SEAL)
    grid,refs=paper.forward_r7(SimpleNamespace(),flags,dates,authority)
    assert set(grid[paper.IDS[2]])==set(dates)
    assert all(day=={g:g for g in decision.G} for day in grid[paper.IDS[2]].values())
    assert refs=={paper.IDS[2]:states[paper.IDS[2]]["model_ref"]}


def test_calendar_proof_rejects_future_close_and_noncompleted_target(tmp_path):
    _, _, _, authority = fixtures(tmp_path)
    proof = json.loads(authority.provenance_json)["calendar_qualification"]
    paper.validate_calendar_proof(proof, authority.as_of, paper.MAX_END)
    with pytest.raises(ValueError, match="CALENDAR_CLOCK_INVALID"):
        paper.validate_calendar_proof(proof, "2026-10-12T19:59:59Z", paper.MAX_END)
    proof["target_session_completed"] = False
    with pytest.raises(ValueError, match="CALENDAR_PROOF_REQUIRED"):
        paper.validate_calendar_proof(proof, authority.as_of, paper.MAX_END)


def test_accepted_baseline_receipt_cannot_be_replaced_with_caller_refs(tmp_path):
    paths, frames, refs, authority = fixtures(tmp_path)
    changed = dict(refs, daily=dict(refs["daily"], sha256="0" * 64))
    with patch.object(paper, "accepted_baseline_refs", return_value=changed), pytest.raises(ValueError, match="BASELINE_PINS_REQUIRED"):
        paper.publish_verified(paths,candidate_id=SID,frames=frames,baseline_refs=refs,authority=authority,source_refs={},projection_receipts=[])


def test_auto_idempotency_returns_before_capture_model_or_replay(tmp_path):
    paths, _, _, _ = fixtures(tmp_path)
    expected = dict(status="ALREADY_CURRENT_PREFIX_VERIFIED", end=paper.MAX_END, models_loaded=0, account_replays=0)
    with patch.object(paper,"completed_calendar",return_value={"target_session":paper.MAX_END}), \
         patch.object(paper,"already_current",return_value=expected), \
         patch.object(paper,"metadata_preflight",side_effect=AssertionError("must not prepare inputs")), \
         patch.object(paper,"resolve_current_capture",side_effect=AssertionError("must not inspect capture")), \
         patch.object(paper,"qualified_inputs",side_effect=AssertionError("must not start source work")):
        assert paper.run_qualified_main(paths,as_of="2026-10-13T01:00:00Z",execute=True,auto=True)==expected


def test_candidate_projection_never_decodes_other_specification(tmp_path):
    path=tmp_path/"candidate-metadata.json"
    path.write_text(json.dumps(dict(candidates=[dict(candidate_id="OTHER",specification={"restricted_result_marker":"SKIP_THIS"}),
        dict(candidate_id=SID,specification={"candidate_id":SID,"action":"raw"},scientific_tuple_sha256="a"*64)])),encoding="utf8")
    import scripts.common.json_projection as projection
    original_loads=projection.json.loads
    def guarded(value,*args,**kwargs):
        raw=value.decode() if isinstance(value,bytes) else value
        assert "SKIP_THIS" not in raw
        return original_loads(value,*args,**kwargs)
    with patch.object(projection.json,"loads",side_effect=guarded):
        assert paper.selected_rows(paper.reference(path),"candidates",SID)["specification"]=={"candidate_id":SID,"action":"raw"}


def test_real_release_shape_projection_preserves_absolute_offset_across_buffers(tmp_path):
    path = tmp_path / "root-release.json"
    body = dict(schema="REMAINING10_ROOT_ACCOUNT_RELEASE_R1", skipped_padding="p" * 66000,
        candidate_bindings=[dict(candidate_id="OTHER", specification={"restriction_marker":"SKIP_OTHER"}),
            dict(candidate_id=SID, scientific_tuple_sha256="f"*64, specification={"candidate_id":SID,
                "action":"raw", "frozen_bundle":{"family":"elasticnet","capacity":"MID"}}, ignored={"x":123})])
    path.write_text(json.dumps(body, indent=2), encoding="utf8")
    selected = paper.selected_rows(paper.reference(path), "candidate_bindings", SID)
    assert selected == {"candidate_id":SID, "scientific_tuple_sha256":"f"*64,
        "specification":{"candidate_id":SID,"action":"raw","frozen_bundle":{"family":"elasticnet","capacity":"MID"}}}


def test_metadata_only_entry_never_qualifies_source_or_loads_models(tmp_path):
    paths, _, _, _ = fixtures(tmp_path)
    metadata = dict(status="METADATA_PREFLIGHT_READY_NOT_SOURCE_OR_REPLAY_QUALIFICATION",end=paper.MAX_END,
        originals={"private":"source"},document={"private":"source"},baselines={"private":"source"},model_fit_calls=0)
    with patch.object(paper,"metadata_preflight",return_value=metadata), \
         patch.object(paper,"qualified_inputs",side_effect=AssertionError("metadata must not begin raw-price qualification")), \
         patch.object(paper,"forward_r10",side_effect=AssertionError("metadata must not load models")), \
         patch.object(paper,"execute_prepared",side_effect=AssertionError("metadata must not replay")):
        result = paper.run_qualified_main(paths,capture_ref={},as_of="2026-10-13T01:00:00Z",execute=False)
    assert result == {key:value for key,value in metadata.items() if key not in ("originals","document","baselines")}


def test_ridge_reader_view_resolves_its_own_scientific_history_not_shared_defaults():
    refs = {key:{"path":key,"sha256":key} for key in ("bridge","view","science","flags","values","inventory","schedule","admission","catalog","prehistory","precalendar")}
    source = dict(stage="ORIGINAL_RAW_COLUMN_READER_VIEW",start=paper.START,end=paper.PREFIX_END,
        original_consensus_source_bundle_ref=refs["science"],bars_ref={"path":"native-original-bars","sha256":"a057"},bars_read_columns=["ticker","trade_date","open","close","quality"])
    def project(ref, fields, path=()):
        if ref == paper.R7_RELEASE: return {}
        if ref == paper.RIDGE_CONFIG: return dict(admission_ref=refs["admission"],inventory_ref=refs["inventory"],bridge_bundle_ref=refs["bridge"],schedule_ref=refs["schedule"])
        if ref == refs["bridge"]: return dict(source_bundle_ref=refs["view"],flags_output_ref=refs["flags"],account_catalog_ref=refs["catalog"],value_outputs_ref=refs["values"])
        if ref == refs["view"]: return source
        if ref == refs["science"]: return dict(universe_variant="CONSENSUS100",prehistory_ref=refs["prehistory"],prehistory_calendar_ref=refs["precalendar"])
        if ref == refs["flags"]: return dict(flags_ref=refs["flags"],flags_read_columns=["ticker"])
        if ref == refs["values"]: return dict(frame_ref=refs["values"],sigma=1.,lineage="original-frozen-pre2026")
        raise AssertionError("unexpected shared-source fallback: " + str(ref))
    with patch.object(paper,"projected_metadata",side_effect=project), \
         patch.object(paper,"selected_rows",return_value={"specification":{"candidate_id":paper.IDS[1]}}):
        meta=paper.original_metadata(paper.IDS[1])
    assert meta["inference"]["original_quote_reader_ref"]==refs["view"]
    assert meta["inference"]["source_bundle_ref"]==refs["science"]
    assert meta["inference"]["prehistory_ref"]==refs["prehistory"]
    assert meta["inference"]["prehistory_calendar_ref"]==refs["precalendar"]


def test_real_daily_os_lock_blocks_source_work_and_releases_for_next_call(tmp_path):
    from scripts.daily_recommendation import single_update as original_daily_lock
    from scripts.common.daily_support import single_update as shared_daily_lock
    from scripts.research.a2.inference import consensus_paper as consumer
    assert callable(original_daily_lock) and callable(shared_daily_lock)
    paths, _, _, _ = fixtures(tmp_path)
    root = paths.daily_root / "A2_today_recommendation"
    from contextlib import nullcontext
    preflight = {"originals":{paper.IDS[2]:{}}}
    with patch.object(paper, "metadata_preflight", return_value=preflight), \
         patch.object(paper, "original_runtime_custody", side_effect=lambda meta:nullcontext(None)), \
         patch.object(consumer, "resource_check", return_value=None), \
         patch.object(paper, "qualified_inputs", side_effect=ValueError("SYNTHETIC_SOURCE_PREFLIGHT_STOP")) as qualify:
        with original_daily_lock(root), pytest.raises(RuntimeError):
            paper.run_qualified_main(paths, capture_ref={}, as_of="2026-10-13T01:00:00Z", execute=True)
        qualify.assert_not_called()
        with pytest.raises(ValueError, match="SYNTHETIC_SOURCE_PREFLIGHT_STOP"):
            paper.run_qualified_main(paths, capture_ref={}, as_of="2026-10-13T01:00:00Z", execute=True)
        qualify.assert_called_once_with(paths, preflight, ca_receipt_refs=())
    assert (root / "update.lock").is_file()



def runtime_fixture(tmp_path, monkeypatch, sid=SID):
    profile_source = tmp_path / "original_profile.py.source"
    remaining_source = tmp_path / "original_remaining.py.source"
    profile_source.write_text('def declared_path():\n    return __file__\ndef check_source(ref):\n    from scripts.research.a2.evaluation import frozen_test_authority as f\n    return f._physical(ref)\n',encoding="utf8")
    remaining_source.write_text('def _owners():\n    from scripts.research.a2.evaluation import frozen_a94_profile as p, frozen_test_authority as f\n    return p, f\ndef declared_paths():\n    p, f = _owners()\n    return p.__file__, __file__\n',encoding="utf8")
    custody={"profile":paper.reference(profile_source),"remaining10_profile":paper.reference(remaining_source)}
    pinned={key:dict(path=str(Path(paper.__file__).with_name(name.rsplit(".",1)[1]+".py").resolve()),sha256=custody[key]["sha256"]) for key,name in paper._RUNTIME_NAMES.items()}
    monkeypatch.setattr(paper,"_RUNTIME_CUSTODY",{sid:custody})
    monkeypatch.setattr(paper,"projected_metadata",lambda ref,fields:{"runtime_source_refs":pinned})
    return {"candidate":{"candidate_id":sid},"release_ref":paper.ROOT_RELEASES[sid]},pinned,custody


def test_candidate_runtime_executes_exact_bytes_and_restores_after_exception(tmp_path,monkeypatch):
    import importlib,sys
    from scripts.research.a2.evaluation import frozen_test_authority as f
    parent=importlib.import_module("scripts.research.a2.evaluation")
    before={name:importlib.import_module(name) for name in paper._RUNTIME_NAMES.values()}
    parents={name:getattr(parent,name.rsplit(".",1)[1]) for name in before}
    physical=f._physical
    meta,pinned,custody=runtime_fixture(tmp_path,monkeypatch)
    unrelated=tmp_path/"unrelated-source.json";unrelated.write_text('{}',encoding="utf8")
    wrong_ref=dict(paper.reference(unrelated),sha256="f"*64)
    with pytest.raises(RuntimeError,match="SYNTHETIC_SCOPE_EXCEPTION"):
        with paper.original_runtime_custody(meta) as proof:
            p=importlib.import_module(paper._RUNTIME_NAMES["profile"])
            r=importlib.import_module(paper._RUNTIME_NAMES["remaining10_profile"])
            assert p is not before[p.__name__] and r is not before[r.__name__]
            assert p.__file__==custody["profile"]["path"] and p.__spec__.origin==p.__file__
            assert r.__file__==custody["remaining10_profile"]["path"] and r.__spec__.origin==r.__file__
            assert p.declared_path()==pinned["profile"]["path"]
            assert r.declared_paths()==(pinned["profile"]["path"],pinned["remaining10_profile"]["path"])
            assert p.check_source(pinned["profile"])==Path(custody["profile"]["path"])
            assert all(row["original_algorithm_ast_unchanged"] for row in proof["source_mappings"])
            assert proof["execution_admission_inherited"] is False
            paths=StoragePaths(**{name:tmp_path/name for name in ("repo_root","data_root","cache_root","daily_root","backtest_root","results_root","envs_root")})
            proof_ref=paper.runtime_custody_receipt(paths,proof)
            assert json.loads(Path(proof_ref["path"]).read_text(encoding="utf8"))==proof
            with pytest.raises(ValueError,match="DESCRIPTIVE_SOURCE_SHA_CHANGED"):
                p.check_source(wrong_ref)
            raise RuntimeError("SYNTHETIC_SCOPE_EXCEPTION")
    assert f._physical is physical
    assert all(sys.modules[name] is module for name,module in before.items())
    assert all(getattr(parent,name.rsplit(".",1)[1]) is module for name,module in parents.items())


def test_candidate_runtime_rejects_other_version_for_same_original_path(tmp_path,monkeypatch):
    from scripts.research.a2.evaluation import frozen_test_authority as f
    meta,pinned,custody=runtime_fixture(tmp_path,monkeypatch)
    with paper.original_runtime_custody(meta):
        mixed=dict(pinned["profile"],sha256="e"*64)
        with pytest.raises(ValueError,match="RUNTIME_VERSION_SPLICE"):
            f._physical(mixed)
    pinned["profile"]["sha256"]="d"*64
    with pytest.raises(ValueError,match="RUNTIME_VERSION_SPLICE"):
        with paper.original_runtime_custody(meta):
            raise AssertionError("mixed release must not enter")


def test_candidate_runtime_rejects_modified_custody_before_binding_globals(tmp_path,monkeypatch):
    import importlib,sys
    from scripts.research.a2.evaluation import frozen_test_authority as f
    meta,_,custody=runtime_fixture(tmp_path,monkeypatch)
    before={name:importlib.import_module(name) for name in paper._RUNTIME_NAMES.values()}
    physical=f._physical
    Path(custody["profile"]["path"]).write_text("raise AssertionError('tampered must never execute')",encoding="utf8")
    with pytest.raises(ValueError,match="REFERENCE_CHANGED"):
        with paper.original_runtime_custody(meta):
            raise AssertionError("tampered source must not enter")
    assert f._physical is physical and all(sys.modules[name] is module for name,module in before.items())



@pytest.mark.parametrize("drive", ["E:","F:"])
def test_unmapped_forbidden_drive_rejects_before_any_resolve(tmp_path,monkeypatch,drive):
    from scripts.research.a2.evaluation import frozen_test_authority as f
    meta,_,_=runtime_fixture(tmp_path,monkeypatch)
    original_resolve=Path.resolve
    def guard_resolve(path,*args,**kwargs):
        assert path.drive.upper() not in ("E:","F:"), "forbidden drive must reject lexically before resolve"
        return original_resolve(path,*args,**kwargs)
    with paper.original_runtime_custody(meta), patch.object(Path,"resolve",new=guard_resolve):
        with pytest.raises(ValueError,match="DESCRIPTIVE_FORBIDDEN_DRIVE"):
            f._physical(dict(path=drive+"/forbidden-source.json",sha256="a"*64))


def write_source_json(tmp_path, name, body):
    path = tmp_path / name; path.write_text(json.dumps(body, indent=2), encoding="utf8")
    return paper.reference(path)


def test_native_source_array_projection_preserves_absolute_offsets(tmp_path):
    ref = write_source_json(tmp_path, "lineage.json", [dict(ticker="IGNORED", forbidden="no decode"),
        dict(ticker="SYNTHETIC", code="US.SYNTHETIC", raw_sources=[dict(path="synthetic", sha256="a"*64)])])
    result = paper.selected_source_rows(ref, {"SYNTHETIC"}, {"code", "raw_sources"})
    assert set(result) == {"SYNTHETIC"} and result["SYNTHETIC"]["code"] == "US.SYNTHETIC"
    assert "forbidden" not in result["SYNTHETIC"]


def test_required_tail_scope_includes_old_carry_and_next_open_targets_without_inactive(tmp_path):
    paths, _, refs, _ = fixtures(tmp_path)
    baselines = {}
    for sid in paper.IDS:
        path = tmp_path/(sid+"_positions.parquet")
        pd.DataFrame([dict(path_id=sid, date=pd.Timestamp(paper.PREFIX_END), ticker="CARRY", weight=.01)]).to_parquet(path,index=False)
        baselines[sid] = {"positions":paper.reference(path)}
    days=["2026-10-09",paper.MAX_END]; rows=[]
    for day in days:
        tickers = ["T"+str(i) for i in range(20)]
        if day==paper.MAX_END: tickers[-1]="NEW"
        rows += [dict(ticker=t, signal_date=pd.Timestamp(day),raw_a2_rank=i+1,is_raw_top20=True) for i,t in enumerate(tickers)]
    path=tmp_path/"flags.parquet";pd.DataFrame(rows).to_parquet(path,index=False)
    domain={r["ticker"] for r in rows}|{"CARRY","INACTIVE"}
    required,scope=paper.tail_required_scope(paper.reference(path),baselines,days,domain)
    assert all(len(v)==22 and "CARRY" in v and "T19" in v and "NEW" in v and "INACTIVE" not in v for v in required.values())
    assert scope["carry_tickers"]==["CARRY"]


def native_catalog_fixture(tmp_path, *, mismatch=False, future=False):
    import sqlite3
    dates=["2026-10-09",paper.MAX_END]
    row=dict(ticker="SYNTHETIC",moomoo_symbol="US.SYNTHETIC",open=2.,high=3.,low=1.,close=2.5,volume=10.,source="MOOMOO_OPEND",
        adjustment="raw",source_policy="MOOMOO_ONLY",fetched_at_utc="2026-10-14T01:00:00Z" if future else "2026-10-13T01:00:00Z")
    leaf=tmp_path/"native.csv";pd.DataFrame([{**row,"date":day} for day in dates+['2027-01-05']]).to_csv(leaf,index=False)
    leaf_ref=paper.reference(leaf)
    records=[dict(date=day,ticker="SYNTHETIC",provider_code="US.SYNTHETIC",open=2.,high=3.,low=1.,close=2.6 if mismatch else 2.5,volume=10.,
        source="MOOMOO_OPEND",adjustment="raw",source_id=leaf_ref["sha256"]) for day in dates+['2027-01-05']]
    normalized=tmp_path/"raw.parquet";pd.DataFrame(records).to_parquet(normalized,index=False);ref=paper.reference(normalized)
    catalog=tmp_path/"catalog.sqlite3"
    with sqlite3.connect(catalog) as connection:
        connection.execute("CREATE TABLE data_files(dataset TEXT,ticker TEXT,adjustment TEXT,source TEXT,format TEXT,path TEXT,source_sha256 TEXT,lineage_json TEXT)")
        connection.execute("INSERT INTO data_files VALUES(?,?,?,?,?,?,?,?)",("prices_daily","SYNTHETIC","raw","MOOMOO_OPEND","parquet",ref["path"],ref["sha256"],"{}"))
    store=SimpleNamespace(catalog_path=catalog,resolve_price_inputs=lambda *a,**k:[leaf_ref])
    return store,ref,dates


def test_existing_native_qualifier_checks_exact_leaf_without_future_numeric_decode(tmp_path):
    store,ref,dates=native_catalog_fixture(tmp_path)
    original=paper.source_date_projection
    seen=[]
    def watch(ref,dates,fields):
        frame=original(ref,dates,fields);seen.extend(frame.get("date",[]));return frame
    with patch.object(paper,"source_date_projection",side_effect=watch):
        result,proof=paper._catalog_raw_tail(store,"SYNTHETIC","US.SYNTHETIC",ref,dates,"2026-10-13T02:00:00Z")
    assert len(result)==2 and "2027-01-05" not in seen and proof["normalized_leaf_exact"] is True
    assert proof["qualifier"].endswith("._native_raw")


@pytest.mark.parametrize("mismatch,future,reason",[(True,False,"NATIVE_RAW_NORMALIZED_LEAF_MISMATCH"),(False,True,"PAPER_EXTENSION_CURRENT_RAW_QUOTES_OR_CLOCK")])
def test_native_tail_rejects_numeric_leaf_drift_and_future_capture(tmp_path,mismatch,future,reason):
    store,ref,dates=native_catalog_fixture(tmp_path,mismatch=mismatch,future=future)
    with pytest.raises(ValueError,match=reason):
        paper._catalog_raw_tail(store,"SYNTHETIC","US.SYNTHETIC",ref,dates,"2026-10-13T02:00:00Z")


def ca_fixture(tmp_path,*,event=None,fetched="2026-10-13T01:00:00Z"):
    # Use the fixture's reviewed completed-session proof rather than recomputing a business day.
    calendar=dict(helper=paper.CALENDAR_HELPER,target_session=paper.MAX_END,session_close_utc="2026-10-12T20:00:00Z")
    rows=[] if event is None else [dict(code="US.SYNTHETIC",ex_div_date=event,forward_adj_factorA=1.,forward_adj_factorB=0.)]
    frame=pd.DataFrame(rows,columns=["code","ex_div_date","forward_adj_factorA","forward_adj_factorB"])
    leaf=tmp_path/"ca.parquet";frame.to_parquet(leaf,index=False);ref=paper.reference(leaf)
    receipt=write_source_json(tmp_path,"rehab_receipt.json",dict(status="READY",source="MOOMOO_OPEND_GET_REHAB",target_date=paper.MAX_END,
        completed_at=fetched,history_requests=0,trade_requests=0,results=[dict(code="US.SYNTHETIC",status="PASS",**ref,row_count=len(frame),fetched_at=fetched)]))
    return receipt,calendar


def test_current_ca_absence_needs_named_fresh_provider_response(tmp_path):
    receipt,calendar=ca_fixture(tmp_path)
    result=paper.tail_ca_qualification([receipt],{"US.SYNTHETIC","US.MISSING"},["2026-10-09",paper.MAX_END],"2026-10-13T02:00:00Z",calendar)
    assert result["status"]=="BLOCKED" and result["missing_codes"]==["US.MISSING"]
    assert result["response_proofs"]["US.SYNTHETIC"]["absence_proven_from_current_native_response"] is True
    assert result["historical_factor_vintage_equivalence_claimed"] is False


def test_current_tail_ca_event_requires_typed_terms(tmp_path):
    receipt,calendar=ca_fixture(tmp_path,event="2026-10-09")
    result=paper.tail_ca_qualification([receipt],{"US.SYNTHETIC"},["2026-10-09",paper.MAX_END],"2026-10-13T02:00:00Z",calendar)
    assert result["status"]=="BLOCKED" and result["typed_event_terms_required"]=={"US.SYNTHETIC":["2026-10-09"]}


def test_new_ca_receipt_cannot_be_backdated_into_previous_asof(tmp_path):
    receipt,calendar=ca_fixture(tmp_path,fetched="2026-10-13T03:00:00Z")
    with pytest.raises(ValueError,match="CA_RECEIPT_AFTER_ASOF"):
        paper.tail_ca_qualification([receipt],{"US.SYNTHETIC"},["2026-10-09",paper.MAX_END],"2026-10-13T02:00:00Z",calendar)


def test_prefix_carry_identity_survives_unbound_aux_tail_rows():
    flags=pd.DataFrame([dict(ticker="CARRY",signal_date=pd.Timestamp(paper.PREFIX_END),security_id="EXACT_CUSIP"),
        dict(ticker="CARRY",signal_date=pd.Timestamp(paper.MAX_END),security_id=None)])
    master=pd.DataFrame([dict(ticker="CARRY",cusip="EXACT_CUSIP",moomoo_transport_code="US.CARRY",
        moomoo_current_validated=True,transport_static_validated=True,mapping_status="RESOLVED")])
    assert paper.tail_security_identity(master,flags,"CARRY")==("US.CARRY","EXACT_CUSIP")
    master.loc[0,"cusip"]="WRONG_CUSIP"
    with pytest.raises(ValueError,match="CURRENT_SECURITY_IDENTITY_INVALID"):
        paper.tail_security_identity(master,flags,"CARRY")


def test_current_raw_normalized_parquet_uses_original_native_route(tmp_path):
    store,ref,dates=native_catalog_fixture(tmp_path)
    result,proof=paper.qualified_native_tail(store,"SYNTHETIC","US.SYNTHETIC",ref,dates,"2026-10-13T02:00:00Z")
    assert len(result)==2 and proof["normalized_leaf_exact"] is True
    assert proof["qualifier"].endswith("._native_raw")


def test_accepted_dated_mapping_owns_identity_ahead_of_old_transport_master():
    flags=pd.DataFrame([dict(ticker="CARRY",signal_date=pd.Timestamp(paper.PREFIX_END),security_id="CURRENT_CUSIP"),
        dict(ticker="CARRY",signal_date=pd.Timestamp(paper.MAX_END),security_id=None)])
    master=pd.DataFrame([dict(ticker="CARRY",cusip="STALE_CUSIP",moomoo_transport_code="US.CARRY",
        moomoo_current_validated=True,transport_static_validated=True,mapping_status="RESOLVED")])
    mapping=pd.DataFrame([dict(ticker="CARRY",security_id="CURRENT_CUSIP",moomoo_symbol="US.CARRY")])
    assert paper.tail_security_identity(master,flags,"CARRY",mapping)==("US.CARRY","CURRENT_CUSIP")
    mapping.loc[0,"security_id"]="OTHER_CUSIP"
    with pytest.raises(ValueError,match="CURRENT_DATED_MAPPING_INVALID"):
        paper.tail_security_identity(master,flags,"CARRY",mapping)


def test_resource_failure_logs_phase_and_preserves_original_floor_exception(capsys):
    from scripts.research.a2.inference import consensus_paper as consumer
    memory=dict(available_physical_bytes=100,available_page_bytes=200,worker=dict(working_set_bytes=50))
    original=ValueError("CONSENSUS_RESOURCE_FLOOR")
    with patch.object(consumer,"resource_check",side_effect=original) as guard, patch.object(paper,"resource_snapshot",return_value=memory):
        with pytest.raises(ValueError) as caught:
            paper.check_resources("R10_BEFORE_FROZEN_HEAD",candidate_id=SID,group="ENTRY")
    assert caught.value is original;guard.assert_called_once_with()
    event=json.loads(capsys.readouterr().out)
    assert event==dict(event="PAPER_EXTENSION_RESOURCE_GATE_REJECTED",stage="R10_BEFORE_FROZEN_HEAD",candidate_id=SID,group="ENTRY",memory=memory)


def test_resource_pass_has_no_diagnostic_or_model_side_effect(capsys):
    from scripts.research.a2.inference import consensus_paper as consumer
    with patch.object(consumer,"resource_check",return_value=None) as guard, patch.object(paper,"resource_snapshot",side_effect=AssertionError("no diagnostics on pass")):
        paper.check_resources("AFTER_METADATA_BEFORE_SOURCE_AND_LOCK")
    guard.assert_called_once_with();assert capsys.readouterr().out==""


@pytest.mark.parametrize("candidate_id",paper.IDS[:2])
def test_r10_bounded_records_match_old_decoder_with_full_prediction_batches(tmp_path,monkeypatch,candidate_id):
    import joblib,numpy as np,weakref
    from scripts.research.a2.inference import consensus_paper as consumer
    from scripts.research.a2.inference.frozen_a94_actions import role_features
    from scripts.research.a2.training import stateful_mechanism as mechanism,stateful_final_action_packets as packets
    roles={};states={};expected={};batch_sizes=[];lifetimes=[]
    for group,size in (("ENTRY",4103),("INCUMBENT",4105)):
        names=role_features("R10:"+group)
        frame=pd.DataFrame({name:np.linspace(-.1,.2,size) for name in names})
        frame["signal_date"]=[pd.Timestamp("2026-01-02") if i%3==0 else pd.Timestamp("2026-01-05") for i in range(size)]
        frame["sample_id"]=[group+"_"+str(i) for i in range(size)]
        frame["ticker"]=["T"+str(i%23) for i in range(size)]
        frame["security_id"]=["S"+str(i%23) for i in range(size)]
        frame["action_type"]=np.arange(size)%2
        frame["entrant_ticker"]=["E"+str(i%17) if i%2 else None for i in range(size)]
        frame["entrant_sid"]=["9"+str(i%17).zfill(8) if i%2 else None for i in range(size)]
        # Wide records include object/missing fields, without changing encoded inputs.
        for i in range(8):frame["unused_"+str(i)]=np.arange(size,dtype=float)
        frame["optional_metadata"]=[None if i%2 else "EXACT" for i in range(size)]
        roles[group]=frame
        _,features=mechanism.encode(frame,names)
        key="ACTION_VALUE_"+group+"_H5_RIDGE" if candidate_id==paper.IDS[1] else "MODEL_"+group
        states[key]=dict(state_type="new_model",model_ref=dict(path=group+"_MODEL",sha256="a"*64),
            metadata_row=dict(group=group,family="ridge" if candidate_id==paper.IDS[1] else "elasticnet",feature_order=features))
        states["ACTION_VALUE_"+group+"_SCALER"]=dict(state_type="scaler",model_ref=dict(path=group+"_SCALER",sha256="b"*64))
        means=np.arange(size,dtype=float)*.0031-2.
        for index,row in enumerate(frame.to_dict("records")):
            day=expected.setdefault(pd.Timestamp(row["signal_date"]),[])
            first={**row,"mean":float(means[index])}
            if first.get("action_type")==1: first["entrant_security_id"]=first.get("entrant_sid")
            day.append(packets.decode_r10_row(first,len(day),group=group))
    class Model:
        def __init__(self,group):self.group=group
    class Scaler:
        def transform(self,x):return x
    def load(path):
        name=str(path);obj=Scaler() if name.endswith("_SCALER") else Model(name.rsplit("_",1)[0]);lifetimes.append(weakref.ref(obj));return obj
    def predict(model,x):
        batch_sizes.append((model.group,len(x)))
        return dict(mean=np.arange(len(x),dtype=float)*.0031-2.,ignored_scalar=3.,ignored_wrong_shape=np.ones((1,)))
    monkeypatch.setattr(consumer,"resource_check",lambda:None)
    monkeypatch.setattr(consumer,"frozen_states",lambda *a:states)
    monkeypatch.setattr(consumer,"verify",lambda ref:Path(ref["path"]))
    monkeypatch.setattr(joblib,"load",load)
    monkeypatch.setattr(consumer,"predict_r10",predict)
    sizes=[];original=pd.DataFrame.to_dict
    def records(frame,*args,**kwargs):
        if (args and args[0]=="records") or kwargs.get("orient")=="records":sizes.append(len(frame))
        return original(frame,*args,**kwargs)
    authority=paper.PaperAuthority(pd.Timestamp(paper.START),pd.Timestamp("2026-01-05"),pd.Timestamp("2026-10-13T01:00:00Z"),
        (candidate_id,),"[]","{}","{}","{}",None,seal=paper._SEAL)
    with patch.object(pd.DataFrame,"to_dict",new=records):
        result,refs=paper.forward_r10(SimpleNamespace(),candidate_id,roles,authority)
    assert result=={candidate_id:expected}
    assert batch_sizes==[("ENTRY",4103),("INCUMBENT",4105)]
    assert sizes==[4096,7,4096,9] and max(sizes)<=4096
    assert len(refs)==4 and all(reference() is None for reference in lifetimes)


_ACCOUNT_FIELDS = ("share_events", "cash_events", "terminal_events", "strict_terminal_events", "known_at",
    "unsupported_events", "engine_scheduled_unsupported_record_indices", "security_tickers",
    "entitlement_source_binding", "source_completeness_unknown")


def account_catalog_fixture(tmp_path, events, **extra):
    catalog = dict(share_events=[], cash_events=events, terminal_events=[], strict_terminal_events=[],
        known_at={"SYNTHETIC": "2026-01-02"}, unsupported_events=[], engine_scheduled_unsupported_record_indices=[],
        security_tickers={"synthetic-id": "SYNTHETIC"}, entitlement_source_binding={"schema": "SYNTHETIC_ONLY"},
        source_completeness_unknown=True, **extra)
    path = tmp_path / "synthetic_account_catalog.json"
    path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    return paper.reference(path), {key: catalog[key] for key in _ACCOUNT_FIELDS}


@pytest.mark.parametrize("empty", [False, True])
def test_account_catalog_streamed_cash_matches_original_small_projection(tmp_path, empty):
    events = [] if empty else [dict(event_id="z", amount=-0.0, quantity=9007199254740993, note="合成"),
        dict(event_id="a", amount=.1, quantity=1e-9), dict(event_id="m", amount=1.2345678901234567)]
    ref, expected = account_catalog_fixture(tmp_path, events)
    original = paper.projected_metadata(ref, _ACCOUNT_FIELDS)
    actual = paper.projected_account_catalog(ref)
    assert actual == expected == original
    assert paper.canonical(actual) == paper.canonical(original)
    assert actual["cash_events"] == events


def test_account_catalog_streamed_cash_large_array(tmp_path, monkeypatch):
    from scripts.common import json_projection
    events = [dict(event_id=f"synthetic-{500-index:04d}", amount=index / 17, note="x" * 480) for index in range(500)]
    forbidden = "NEVER_DECODE_UNRELATED_VALUE_" + "u" * 150000
    ref, expected = account_catalog_fixture(tmp_path, events, unrelated_derived_results={"forbidden": forbidden})
    assert len(json.dumps(events).encode("utf-8")) > 65536
    with pytest.raises(ValueError, match="SOURCE_JSON_METADATA_VALUE_TOO_LARGE"):
        paper.projected_metadata(ref, _ACCOUNT_FIELDS)
    loads = json_projection.json.loads; decoded_events = []
    def bounded_loads(raw, *args, **kwargs):
        assert len(raw) <= paper._ACCOUNT_CASH_ITEM_BYTES
        assert b"NEVER_DECODE_UNRELATED_VALUE_" not in (raw.encode("utf8") if isinstance(raw, str) else raw)
        value = loads(raw, *args, **kwargs)
        if isinstance(value, dict) and "event_id" in value: decoded_events.append(value)
        return value
    monkeypatch.setattr(json_projection.json, "loads", bounded_loads)
    actual = paper.projected_account_catalog(ref)
    assert actual == expected and actual["cash_events"] == events
    assert decoded_events == events  # exact input order, one decoded cash object per item.


@pytest.mark.parametrize("extra", [0, 1])
def test_account_catalog_streamed_cash_item_limit_rejects_before_decode(tmp_path, monkeypatch, extra):
    from scripts.common import json_projection
    event = dict(event_id="synthetic-item-bound", note="")
    event["note"] = "x" * (paper._ACCOUNT_CASH_ITEM_BYTES - len(json.dumps(event).encode("utf8")) + extra)
    assert len(json.dumps(event).encode("utf8")) == paper._ACCOUNT_CASH_ITEM_BYTES + extra
    ref, expected = account_catalog_fixture(tmp_path, [event])
    loads = json_projection.json.loads
    def bounded_loads(raw, *args, **kwargs):
        assert len(raw) <= paper._ACCOUNT_CASH_ITEM_BYTES
        return loads(raw, *args, **kwargs)
    monkeypatch.setattr(json_projection.json, "loads", bounded_loads)
    if extra:
        with pytest.raises(ValueError, match="SOURCE_JSON_METADATA_VALUE_TOO_LARGE"):
            paper.projected_account_catalog(ref)
    else:
        assert paper.projected_account_catalog(ref) == expected


@pytest.mark.parametrize("extra", [0, 1])
def test_account_catalog_streamed_cash_event_count_bound(tmp_path, extra):
    events = [dict(event_id=f"synthetic-{index}") for index in range(paper._ACCOUNT_CASH_MAX_ITEMS + extra)]
    ref, expected = account_catalog_fixture(tmp_path, events)
    if extra:
        with pytest.raises(ValueError, match="ACCOUNT_CASH_EVENT_COUNT_LIMIT"):
            paper.projected_account_catalog(ref)
    else:
        assert paper.projected_account_catalog(ref) == expected


def test_account_catalog_streamed_cash_file_limit_rejects_before_projection(tmp_path, monkeypatch):
    path = tmp_path / "oversized_synthetic_catalog.json"
    with path.open("wb") as stream: stream.truncate(paper._ACCOUNT_CATALOG_FILE_BYTES + 1)
    ref = paper.reference(path)
    from scripts.common import json_projection
    def forbidden(*args, **kwargs): raise AssertionError("oversized file was projected")
    monkeypatch.setattr(json_projection, "_parser_type", forbidden)
    with pytest.raises(ValueError, match="ACCOUNT_CATALOG_FILE_LIMIT"):
        paper.projected_account_catalog(ref)


@pytest.mark.parametrize("phase", ["before", "during"])
def test_account_catalog_streamed_cash_changed_reference_rejected(tmp_path, monkeypatch, phase):
    from scripts.common import json_projection
    ref, _ = account_catalog_fixture(tmp_path, [dict(event_id="synthetic-change", amount=.125)])
    path = Path(ref["path"])
    if phase == "before":
        with path.open("ab") as stream: stream.write(b" ")
    else:
        parser = json_projection._parser_type(); scalar = parser.scalar; changed = []
        def mutate(reader, *args, **kwargs):
            value = scalar(reader, *args, **kwargs)
            if isinstance(value, dict) and value.get("event_id") == "synthetic-change":
                with path.open("ab") as stream: stream.write(b" ")
                changed.append(True)
            return value
        monkeypatch.setattr(parser, "scalar", mutate)
    with pytest.raises(ValueError, match="PAPER_EXTENSION_REFERENCE_CHANGED"):
        paper.projected_account_catalog(ref)
    if phase == "during": assert changed == [True]


@pytest.mark.parametrize("field,value", [("cash_events", "[]"), ("known_at", "{}")])
def test_account_catalog_streamed_cash_duplicate_named_fields_remain_rejected(tmp_path, field, value):
    path = tmp_path / "duplicate_synthetic_catalog.json"
    path.write_text('{"' + field + '":' + value + ',"' + field + '":' + value + '}', encoding="utf-8")
    ref = paper.reference(path)
    for project in (lambda: paper.projected_metadata(ref, _ACCOUNT_FIELDS), lambda: paper.projected_account_catalog(ref)):
        with pytest.raises(ValueError, match="SOURCE_JSON_DUPLICATE_METADATA_KEY"): project()


def test_account_catalog_streamed_cash_trailing_comma_remains_rejected(tmp_path):
    path = tmp_path / "malformed_synthetic_catalog.json"
    path.write_text('{"cash_events":[{"event_id":"synthetic"},]}', encoding="utf-8")
    ref = paper.reference(path)
    for project in (lambda: paper.projected_metadata(ref, _ACCOUNT_FIELDS), lambda: paper.projected_account_catalog(ref)):
        with pytest.raises(ValueError, match="SOURCE_JSON_EMPTY_VALUE"): project()


@pytest.fixture
def market_flag_projection_case(tmp_path, monkeypatch):
    """Synthetic Parquet only; reuse the actual bounded reader and market projection."""
    import numpy as np
    from scripts.research.a2.inference import consensus_paper as consumer, frozen_a94_state as state, stateful_test_inputs as inputs
    from scripts.research.a2.training import stateful_replay as replay
    days = pd.DatetimeIndex([paper.START, paper.FIRST_EXECUTION, paper.PREFIX_END, "2026-10-09", paper.MAX_END])
    names = [f"SYN{index:02d}" for index in range(24)]
    bits = ("is_max_group", "decision_information_present_union", "stock_forecast_input_present", "raw_selector_input_present")
    columns = list(dict.fromkeys((*state._PRED, *bits)))
    all_days = pd.DatetimeIndex(["2025-12-31", *days, "2027-01-01"])
    rows = []
    for day in all_days:
        for index, ticker in enumerate(names):
            top = index < 20; qualified = index % 3 != 0
            stock = index % 2 == 0 if top else (index - 20) in (1, 3)
            raw = True if top else (index - 20) in (2, 3)
            row = {key: .125 for key in state.original_inputs.FEATURES}
            row.update(signal_date=day, ticker=ticker, security_id="synthetic-" + ticker,
                feature_available=stock, is_raw_top20=top, new_buy_eligible=top and qualified,
                raw_top20_set_complete=True, raw_a2_rank=index + 1 if top else np.nan,
                raw_a2_prediction=.01 if raw else np.nan, is_max_group=qualified,
                decision_information_present_union=stock or raw, stock_forecast_input_present=stock,
                raw_selector_input_present=raw, label_value="NEVER_PROJECT_SYNTHETIC_LABEL",
                label_mature_date=pd.Timestamp("2027-01-01"))
            rows.append(row)
    flags = pd.DataFrame(rows)
    refs = {}; files = {}
    for role in ("original", "current"):
        files[role] = tmp_path / (role + "_synthetic_flags.parquet")
        flags.to_parquet(files[role], index=False); refs[role] = paper.reference(files[role])
    authority = paper.PaperAuthority(days[0], days[-1], pd.Timestamp("2026-10-13T16:20:23Z"), (SID,),
        "[]", "{}", "{}", "{}", None, seal=paper._SEAL)
    calls = []; original_reader = consumer.bounded_frame
    packet_ref = dict(path="synthetic-unused-packet", sha256="0" * 64)
    def bounded(ref, requested, clock, first, last):
        assert not set(requested) & state._OUTCOMES
        calls.append((ref, tuple(requested), clock, pd.Timestamp(first), pd.Timestamp(last)))
        if ref == packet_ref: return pd.DataFrame(columns=requested)
        return original_reader(ref, requested, clock, first, last)
    monkeypatch.setattr(consumer, "bounded_frame", bounded)
    helper = SimpleNamespace(account_inputs=lambda catalog, admitted: ({}, {}), values_for=lambda *args: {})
    monkeypatch.setattr(paper, "_original_authority", lambda meta: SimpleNamespace())
    monkeypatch.setattr(paper, "load_original_owner", lambda *args: helper)
    monkeypatch.setattr(paper, "projected_account_catalog", lambda ref: {})
    monkeypatch.setattr(paper, "projected_metadata", lambda ref, requested: {"common_sessions": [str(day.date()) for day in days if day <= pd.Timestamp(paper.PREFIX_END)]})
    monkeypatch.setattr(paper, "bind_authority", lambda *args, **kwargs: authority)
    inference = dict(flags_ref=refs["original"], flags_read_columns=columns, account_catalog_ref={},
        value_outputs={"ridge": dict(frame_ref=packet_ref, sigma=.1, lineage="SYNTHETIC")})
    meta = dict(candidate=dict(action="raw", gross="fixed", forecast="none", execution_friction={}),
        inference=inference, r7_release={"original_account_helpers_ref": {}}, release={"schedule_ref": {}},
        release_ref={}, inference_ref={})
    preflight = dict(originals={SID: meta}, calendar_qualification={"main_sessions": [str(day.date()) for day in days], "calendar_ref": {}},
        publication_ref={}, as_of="2026-10-13T16:20:23Z", end=str(days[-1].date()))
    bars = flags.loc[flags.signal_date.isin(days), ["signal_date", "ticker"]].assign(open=10., close=11.)
    qualified = dict(document={"flags_ref": refs["current"], "source_extension_ref": {}}, quote_receipt_ref={},
        quote_proof={"quotes_ref": {}, "original_market_tickers": names}, bars=bars)
    def rewrite(role, **changes):
        frame = flags.copy()
        if "drop" in changes: frame = frame.drop(columns=changes["drop"])
        if "fault" in changes:
            mask = frame.signal_date.eq(days[-1]) & frame.ticker.eq(names[0])
            field = changes["fault"]; frame.loc[mask, field] = ~frame.loc[mask, field]
        frame.to_parquet(files[role], index=False); refs[role] = paper.reference(files[role])
        if role == "original": inference["flags_ref"] = refs[role]
        else: qualified["document"]["flags_ref"] = refs[role]
    return SimpleNamespace(preflight=preflight, qualified=qualified, authority=authority, calls=calls,
        days=days, names=names, columns=columns, bits=bits, flags=flags, rewrite=rewrite, inference=inference,
        inputs=inputs, values=replay._old().values)


def test_market_flag_projection_original_guard_and_full_boolean_schema(market_flag_projection_case):
    import numpy as np
    e = market_flag_projection_case
    prepared, flags = paper._prepare_candidate(None, SID, e.preflight, e.qualified)
    assert list(flags.columns) == e.columns and not set(flags) & {"label_value", "label_mature_date"}
    assert pd.DatetimeIndex(flags.signal_date.unique()).equals(e.days)
    assert [(call[2], call[3], call[4]) for call in e.calls[:2]] == [
        ("signal_date", pd.Timestamp(paper.START), pd.Timestamp(paper.PREFIX_END)),
        ("signal_date", e.days[-2], e.days[-1])]
    assert all(call[1] == tuple(e.columns) for call in e.calls[:2])
    assert prepared["projection_receipts"][0]["function"] == "project_window"
    assert prepared["projection_receipts"][0]["algorithm_ast_unchanged"] is True
    assert prepared["projection_receipts"][0]["namespace_guard_dependency_bindings"] == ["authority"]
    expected = e.flags.loc[e.flags.signal_date.isin(e.days)]
    for name, field in (("top", "is_raw_top20"), ("qualified", "is_max_group"),
            ("stock_present", "stock_forecast_input_present"), ("raw_selector_present", "raw_selector_input_present")):
        assert np.array_equal(prepared[name], e.values(expected, e.days, e.names, field, False, bool))
    assert np.all(prepared["top"].sum(axis=1) == 20)
    assert np.array_equal(prepared["market"].input_present, prepared["stock_present"] | prepared["raw_selector_present"])
    assert np.array_equal(prepared["market"].new_buy_eligible, prepared["top"] & prepared["qualified"])
    original_vol = e.values(expected, e.days, e.names, "realized_vol_20d") * np.sqrt(5.)
    assert np.array_equal(prepared["vol"], np.where(prepared["stock_present"], original_vol, np.nan), equal_nan=True)
    assert np.isnan(prepared["vol"][~prepared["stock_present"]]).all()


@pytest.mark.parametrize("field,role", [("is_max_group", "original"), ("decision_information_present_union", "current"),
    ("stock_forecast_input_present", "original"), ("raw_selector_input_present", "current")])
def test_market_flag_projection_missing_columns_fail_closed(market_flag_projection_case, field, role):
    e = market_flag_projection_case; e.rewrite(role, drop=field)
    with pytest.raises(ValueError, match="CONSENSUS_PROJECTED_INPUT_FIELDS_REQUIRED"):
        paper._prepare_candidate(None, SID, e.preflight, e.qualified)


@pytest.mark.parametrize("field", ["decision_information_present_union", "new_buy_eligible"])
def test_market_flag_projection_unknown_information_bits_not_repaired(market_flag_projection_case, field):
    e = market_flag_projection_case; e.rewrite("current", fault=field)
    with pytest.raises(ValueError, match="WINDOW_FROZEN_INFORMATION_BITS_CHANGED"):
        paper._prepare_candidate(None, SID, e.preflight, e.qualified)


def test_market_flag_projection_undeclared_fields_fail_before_decode(market_flag_projection_case):
    e = market_flag_projection_case; e.inference["flags_read_columns"].remove("is_max_group")
    with pytest.raises(ValueError, match="PAPER_EXTENSION_ORIGINAL_MARKET_FLAG_FIELDS_UNDECLARED"):
        paper._prepare_candidate(None, SID, e.preflight, e.qualified)
    assert e.calls == []


@pytest.mark.parametrize("day", ["2025-12-31", "2027-01-01"])
def test_market_flag_projection_original_date_guard_rejects_outside_scope(market_flag_projection_case, day):
    e = market_flag_projection_case
    projected, receipt = paper.guard_projection(e.inputs.project_window,
        authority=SimpleNamespace(validate_descriptive_input_dates=paper.validate_descriptive_input_dates))
    with pytest.raises(ValueError, match="PAPER_EXTENSION_INPUT_OUTSIDE_BOUND"):
        projected(e.flags[e.columns], e.qualified["bars"], pd.DatetimeIndex([day]), e.authority, values_function=e.values)
    assert receipt["algorithm_ast_unchanged"] is True


@pytest.fixture
def supplemental_ca_locator(tmp_path, monkeypatch):
    """Synthetic identity-only source graph; no price/CA leaf or ledger decode."""
    paths = StoragePaths(**{name:tmp_path/name for name in ("repo_root", "data_root", "cache_root", "daily_root", "backtest_root", "results_root", "envs_root")})
    run = paths.daily_root / "A2_today_recommendation/runs/synthetic_current"
    run.mkdir(parents=True)
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf8")
        return paper.reference(path)
    mapping = run / "universe_refresh/mapped_members.parquet"
    mapping.parent.mkdir(parents=True); mapping.write_bytes(b"SYNTHETIC_MAPPING_METADATA_ONLY")
    mapping_ref = paper.reference(mapping)
    identity = write(run / "identity.json", {"synthetic":True})
    source = write(run / "recommendation_source.json", dict(status="READY", data_date="2026-10-13", generated_at="2026-10-13T21:01:00Z",
        universe=dict(report_path=str(mapping.parent / "report.json"), universe_members_sha256=mapping_ref["sha256"], identity_source=identity)))
    lineage = write(run / "input_lineage.json", {"synthetic":True})
    rehab = write(run / "rehab_receipt.json", {"synthetic":True})
    report = write(run / "report.json", dict(status="READY", data_date="2026-10-13", generated_at="2026-10-13T21:02:00Z", accepted_source=source, accepted_inputs=[lineage, rehab]))
    proof = write(paths.daily_root / "proof.json", dict(current_day_proofs=[dict(signal_date="2026-10-13", mapping_ref=mapping_ref)]))
    flags = write(paths.daily_root / "flags.json", {"synthetic":True})
    bundle = write(paths.daily_root / "bundle.json", {"synthetic":True})
    publication = write(paths.daily_root / "publication.json", dict(schema="CONSENSUS_PAPER_SOURCE_V1", signal_date="2026-10-13",
        decision_as_of="2026-10-13T21:03:00Z", source_bundle_ref=bundle, flags_ref=flags, source_extension_ref=proof,
        strategy_status={sid:dict(status="READY") for sid in paper.IDS}, model_fit_calls=0))
    write(paths.daily_root / "A2_consensus_paper/latest.json", publication)
    prices = write(paths.daily_root / "prices.json", {"synthetic":True})
    events = write(paths.daily_root / "events.json", {"synthetic":True})
    capture = write(paths.daily_root / "capture.json", dict(end_date="2026-10-13", captured_prices=prices, events=events))
    receipt = write(paths.daily_root / "A2_consensus_paper/current_tail_ca/synthetic/rehab_receipt.json",
        dict(status="READY", source="MOOMOO_OPEND_GET_REHAB", target_date="2026-10-13", history_requests=0, trade_requests=0,
            completed_at="2026-10-13T23:36:47Z", results=[dict(code="US.SYNTHETIC", status="PASS", fetched_at="2026-10-13T23:36:46Z",
                event_values=[123.456] * 15000)]))
    calendar = dict(target_session="2026-10-13", session_close_utc="2026-10-13T20:00:00Z")
    monkeypatch.setattr(paper, "completed_calendar", lambda *_:calendar)
    monkeypatch.setattr(paper, "accepted_baseline_refs", lambda *_:{})
    monkeypatch.setattr(paper, "original_metadata", lambda *_:{})
    def forbidden(*_, **__): raise AssertionError("NO_CA_TERMS_PRICE_MODEL_OR_REPLAY_CALL")
    monkeypatch.setattr(paper, "tail_ca_qualification", forbidden)
    monkeypatch.setattr(paper, "qualified_inputs", forbidden)
    monkeypatch.setattr(paper, "execute_prepared", forbidden)
    kwargs=dict(target_session="2026-10-13", publication_ref=publication, capture_ref=capture, daily_report_ref=report, as_of="2026-10-13T23:40:00Z")
    return paths, kwargs, receipt, write


def test_supplemental_ca_locator_exact_metadata_roundtrip_and_atomic_idempotency(supplemental_ca_locator, monkeypatch):
    paths, kwargs, receipt, _ = supplemental_ca_locator
    before = Path(receipt["path"]).read_bytes()
    original_loads = json.loads
    def narrow_loads(value, *args, **kw):
        if isinstance(value, (bytes, str)):
            assert len(value) < 65536, "UNRELATED_EVENT_ARRAY_WAS_DECODED"
        return original_loads(value, *args, **kw)
    monkeypatch.setattr(json, "loads", narrow_loads)
    registered = paper.register_supplemental_ca_receipts(paths, **kwargs, ca_receipt_refs=[receipt])
    resolved = paper.resolve_supplemental_ca_receipts(paths, **kwargs)
    assert registered == resolved and resolved["ca_receipt_refs"] == [receipt]
    locator = Path(resolved["locator_ref"]["path"])
    assert locator == paths.daily_root / "A2_consensus_paper/current_tail_ca/2026-10-13/supplemental_refs.json"
    assert locator.stat().st_size <= 4096
    body = json.loads(locator.read_bytes())
    assert body["status"] == "LOCATOR_ONLY_NOT_QUALIFIED"
    assert "sha256" not in body["binding"]["daily_report_binding"]
    later = {**kwargs, "as_of":"2026-10-13T23:41:00Z"}
    assert paper.register_supplemental_ca_receipts(paths, **later, ca_receipt_refs=[receipt]) == registered
    assert Path(receipt["path"]).read_bytes() == before
    assert not paths.backtest_root.exists() and not paths.results_root.exists()


def test_supplemental_ca_locator_absent_future_date_never_inherits_old_refs(supplemental_ca_locator):
    paths, kwargs, receipt, _ = supplemental_ca_locator
    paper.register_supplemental_ca_receipts(paths, **kwargs, ca_receipt_refs=[receipt])
    assert paper.resolve_supplemental_ca_receipts(paths, **{**kwargs, "target_session":"2026-10-14"}) == dict(locator_ref=None, ca_receipt_refs=[])


def test_supplemental_ca_locator_report_branch_rewrite_preserves_exact_accepted_inputs(supplemental_ca_locator):
    paths, kwargs, receipt, write = supplemental_ca_locator
    result = paper.register_supplemental_ca_receipts(paths, **kwargs, ca_receipt_refs=[receipt])
    report_path = Path(kwargs["daily_report_ref"]["path"])
    report = json.loads(report_path.read_text()); report["benchmark_update"] = dict(status="BLOCKED", reason="SYNTHETIC")
    changed = write(report_path, report)
    assert changed != kwargs["daily_report_ref"]
    assert paper.resolve_supplemental_ca_receipts(paths, **{**kwargs, "daily_report_ref":changed}) == result
    report["accepted_inputs"] = list(reversed(report["accepted_inputs"]))
    changed = write(report_path, report)
    with pytest.raises(ValueError, match="CA_LOCATOR_BINDING_CHANGED"):
        paper.resolve_supplemental_ca_receipts(paths, **{**kwargs, "daily_report_ref":changed})


@pytest.mark.parametrize("field", ["publication_ref", "capture_ref", "daily_report_ref"])
def test_supplemental_ca_locator_rejects_wrong_original_binding(supplemental_ca_locator, field):
    paths, kwargs, receipt, write = supplemental_ca_locator
    paper.register_supplemental_ca_receipts(paths, **kwargs, ca_receipt_refs=[receipt])
    replacement = write(paths.daily_root / "wrong_binding.json", dict(synthetic=True, end_date="2026-10-13"))
    with pytest.raises((ValueError, KeyError)):
        paper.resolve_supplemental_ca_receipts(paths, **{**kwargs, field:replacement})


@pytest.mark.parametrize("change,expected", [
    (dict(target_date="2026-10-12"), "RECEIPT_INVALID"),
    (dict(history_requests=1), "RECEIPT_INVALID"),
    (dict(trade_requests=1), "RECEIPT_INVALID"),
    (dict(status="PARTIAL"), "RECEIPT_INVALID"),
    (dict(completed_at="2026-10-13T19:59:59Z"), "RECEIPT_CLOCK"),
    (dict(completed_at="2026-10-13T23:41:00Z"), "RECEIPT_CLOCK"),
    (dict(completed_at="2026-10-13T23:36:47"), "CLOCK_REQUIRED"),
    (dict(results=[dict(code="US.SYNTHETIC", status="PASS", fetched_at="2026-10-13T23:36:48Z")]), "RESPONSE_CLOCK"),
    (dict(results=[]), "RESPONSE_METADATA"),
])
def test_supplemental_ca_locator_rejects_invalid_receipt_metadata(supplemental_ca_locator, change, expected):
    paths, kwargs, receipt, write = supplemental_ca_locator
    body=json.loads(Path(receipt["path"]).read_text()); body.update(change); changed=write(Path(receipt["path"]), body)
    with pytest.raises(ValueError, match=expected):
        paper.register_supplemental_ca_receipts(paths, **kwargs, ca_receipt_refs=[changed])
    assert not paper._ca_locator_path(paths, kwargs["target_session"]).exists()


def test_supplemental_ca_locator_changed_receipt_sha_and_naive_asof_fail_closed(supplemental_ca_locator):
    paths, kwargs, receipt, _ = supplemental_ca_locator
    paper.register_supplemental_ca_receipts(paths, **kwargs, ca_receipt_refs=[receipt])
    with pytest.raises(ValueError, match="CA_LOCATOR_CLOCK_REQUIRED"):
        paper.resolve_supplemental_ca_receipts(paths, **{**kwargs, "as_of":"2026-10-13T23:40:00"})
    Path(receipt["path"]).write_text('{}')
    with pytest.raises(ValueError, match="REFERENCE_CHANGED"):
        paper.resolve_supplemental_ca_receipts(paths, **kwargs)


@pytest.mark.parametrize("case", ["duplicate", "oversized", "wrong_target", "unknown_key", "nonfinite", "after_asof", "ref_count"])
def test_supplemental_ca_locator_rejects_bad_persisted_locator(supplemental_ca_locator, case):
    paths, kwargs, receipt, _ = supplemental_ca_locator
    result = paper.register_supplemental_ca_receipts(paths, **kwargs, ca_receipt_refs=[receipt])
    locator=Path(result["locator_ref"]["path"]); body=json.loads(locator.read_text())
    if case == "duplicate": text='{"schema":"one","schema":"two"}'
    elif case == "oversized": text=' ' * 4097
    elif case == "wrong_target": body["binding"]["target_session"]="2026-10-12"; text=json.dumps(body)
    elif case == "unknown_key": body["allow_broker"]=True; text=json.dumps(body)
    elif case == "nonfinite": body["registered_as_of"]=float("nan"); text=json.dumps(body)
    elif case == "after_asof": body["registered_as_of"]="2026-10-13T23:41:00Z"; text=json.dumps(body)
    else: body["ca_receipt_refs"]=[receipt]*17; text=json.dumps(body, separators=(",", ":"))
    locator.write_text(text)
    with pytest.raises(ValueError): paper.resolve_supplemental_ca_receipts(paths, **kwargs)


def test_supplemental_ca_locator_ref_schema_and_forbidden_drive_precede_resolution(monkeypatch):
    with patch.object(paper, "verified", side_effect=AssertionError("UNSAFE_IO")):
        for ref in (dict(path="E:/forbidden.json", sha256="a"*64), dict(path="F:/forbidden.json", sha256="a"*64),
                    dict(path="relative.json", sha256="a"*64), dict(path="D:/unused.json", sha256="not-a-hash")):
            with pytest.raises(ValueError, match="CA_LOCATOR_REF_"): paper._ca_locator_ref(ref)


def test_supplemental_ca_locator_registration_ref_bound(supplemental_ca_locator):
    paths, kwargs, receipt, _ = supplemental_ca_locator
    for refs in ([], [receipt]*17, [receipt, receipt]):
        with pytest.raises(ValueError, match="RECEIPT_BOUND|DUPLICATE_RECEIPT"):
            paper.register_supplemental_ca_receipts(paths, **kwargs, ca_receipt_refs=refs)



def test_supplemental_ca_locator_bounded_read_rejects_growth_after_stat(tmp_path, monkeypatch):
    locator=tmp_path / "racing_locator.json"
    locator.write_bytes(b" " * 4097)
    original_stat=Path.stat
    def earlier_size(path, *args, **kwargs):
        value=original_stat(path, *args, **kwargs)
        return SimpleNamespace(st_size=4096) if path == locator else value
    monkeypatch.setattr(Path, "stat", earlier_size)
    with patch.object(paper.json, "loads", side_effect=AssertionError("OVERSIZED_LOCATOR_DECODED")) as decode:
        with pytest.raises(ValueError, match="CA_LOCATOR_FILE_BOUND"):
            paper._ca_locator_read(locator)
    decode.assert_not_called()


_QUALITY_GROUPS = ("accounting_qualified", "quote_qualified", "certified_NAV_all_window_finite", "cash_identity_correct", "entitlement_identity_correct",
    "complete_dates", "fresh_initial_nav", "no_initial_fills", "no_initial_positions")


def quality_diagnostic_fixture(failed="quote_qualified"):
    groups={name:name != failed for name in _QUALITY_GROUPS}
    return dict(groups=groups, all_passed=failed is None, owner_checks=dict(full_window_sessions=196,
        stale_holding_rows=0, stale_holding_days=0, unknown_holding_rows=1, open_stale_sessions=0,
        open_unknown_sessions=1, actual_CA_exception_rows=0, unknown_keys=[dict(date="2026-10-13", ticker="SYNTHETIC")],
        confidential_NAV=123456.789, return_amount=98765.4321, cash=45678.9012, notional=34567.8901, model_value=[23456.789]))


def test_quality_failure_diagnostic_original_quality_accepts_dynamic_dates_and_pending_orders():
    """Compile only the exact original quality function, never its research imports."""
    import ast, hashlib
    source=Path("D:/us-tech-quant-cache/_maintenance/A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1/a_all_random_accounts.py")
    assert hashlib.sha256(source.read_bytes()).hexdigest()=="de6d73ffbf4ecaf7e0995cd89d6d55322597c625e8534327606ec0cb392e0fba"
    node=next(n for n in ast.parse(source.read_text(encoding="utf8")).body if isinstance(n,ast.FunctionDef) and n.name=="quality")
    owner_checks={name:True for name in _QUALITY_GROUPS[:5]}
    owner_checks.update(full_window_752_sessions=False, eligible_for_selection=False)
    scope=dict(pd=pd,replay=SimpleNamespace(qualification_checks=lambda *_:owner_checks))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(source),"exec"),scope)
    dates=pd.bdate_range(paper.START,periods=193).append(pd.DatetimeIndex(["2026-10-09","2026-10-12","2026-10-13"]))
    frames=dict(daily=pd.DataFrame(dict(path_id=[SID]*len(dates),date=dates,TOTAL_ECONOMIC_NAV=3000.,cash=3000.)),
        positions=pd.DataFrame(columns=["path_id","date"]), fills=pd.DataFrame(columns=["path_id","execution_date"]),
        orders=pd.DataFrame([dict(path_id=SID,signal_date="2026-10-13",execution_date="2026-10-14",status="no_next_session")]))
    q=scope["quality"](object(),frames,SID,dates)
    assert len(dates)==196 and q["all_passed"] is True and set(q["groups"])==set(_QUALITY_GROUPS)
    assert q["owner_checks"]["full_window_752_sessions"] is False and q["owner_checks"]["eligible_for_selection"] is False


@pytest.mark.parametrize("failed", _QUALITY_GROUPS)
def test_quality_failure_diagnostic_reports_only_original_failed_boolean_and_counts(failed):
    q=quality_diagnostic_fixture(failed); before=deepcopy(q)
    encoded=paper._account_quality_failure_diagnostic(q,candidate_id=SID,end="2026-10-13",as_of="2026-10-14T01:00:00Z",
        owner_ref=dict(path="D:/synthetic/quality.py",sha256="a"*64))
    value=json.loads(encoded)
    assert value["groups"]==q["groups"] and value["failed_groups"]==[failed]
    assert value["owner_counts"]["full_window_sessions"]==196
    assert len(encoded.encode("utf8")) + 2 <=16384 and value["model_fit_calls"]==0 and value["broker_action_allowed"] is False
    assert q==before
    for forbidden in ("confidential_NAV","return_amount","notional","model_value","123456.789","98765.4321","45678.9012","34567.8901","23456.789"):
        assert forbidden not in encoded


def test_quality_failure_diagnostic_caps_twenty_original_order_keys_and_utf8_bytes():
    q=quality_diagnostic_fixture(); checks=q["owner_checks"]
    checks["stale_keys"]=[dict(date="2026-10-13",ticker=f"SYNTHETIC{i:02d}",NAV=123456.789) for i in range(30)]
    checks["unknown_keys"]=[dict(date="2026-10-13",ticker="UNKNOWN_SYNTHETIC") for _ in range(30)]
    checks["accounting_exception_keys"]=[dict(date=pd.Timestamp("2026-10-13"),ticker="CA_SYNTHETIC",reason="UNSUPPORTED_SYNTHETIC",cash=45678.9012) for _ in range(30)]
    kwargs=dict(candidate_id=SID,end="2026-10-13",as_of="2026-10-14T01:00:00Z",owner_ref=dict(path="D:/synthetic/quality.py",sha256="a"*64))
    encoded=paper._account_quality_failure_diagnostic(q,**kwargs); value=json.loads(encoded)
    assert sum(len(v["keys"]) for v in value["owner_keys"].values())==20
    assert [v["ticker"] for v in value["owner_keys"]["stale_keys"]["keys"]]==[f"SYNTHETIC{i:02d}" for i in range(20)]
    assert all(v["truncated"] and v["total"]==30 for v in value["owner_keys"].values())
    assert "123456.789" not in encoded and "45678.9012" not in encoded
    checks["stale_keys"]=[]; checks["unknown_keys"]=[]
    checks["accounting_exception_keys"]=[dict(date=pd.Timestamp("2026-10-13"),ticker="CA_SYNTHETIC",reason="😀"*300) for _ in range(20)]
    encoded=paper._account_quality_failure_diagnostic(q,**kwargs); value=json.loads(encoded)
    assert len(encoded.encode("utf8")) + 2 <=16384 and value["key_details_omitted_for_output_bound"] is True
    assert value["owner_keys"]["accounting_exception_keys"]["total"]==20 and value["owner_keys"]["accounting_exception_keys"]["keys"]==[]


@pytest.mark.parametrize("passed", [False, True])
def test_quality_failure_diagnostic_driver_preserves_failure_and_success_publication(tmp_path, monkeypatch, capsys, passed):
    from contextlib import nullcontext
    from unittest.mock import Mock
    from scripts.research.a2.inference import consensus_paper as consumer
    paths=SimpleNamespace(daily_root=tmp_path / "daily")
    owner=tmp_path / "synthetic_quality_owner.py"; owner.write_text("# synthetic owner identity only\n")
    owner_ref=paper.reference(owner)
    dates=pd.DatetimeIndex([paper.START,paper.FIRST_EXECUTION,"2026-10-13"])
    q=quality_diagnostic_fixture(None if passed else "quote_qualified")
    quality=Mock(return_value=q)
    prepared=dict(authority=SimpleNamespace(end=pd.Timestamp("2026-10-13")),market=SimpleNamespace(dates=dates),
        helper=SimpleNamespace(quality=quality,__file__=str(owner)),projection_receipts=[],source_refs={})
    preflight=dict(originals={sid:dict(r7_release=dict(original_account_helpers_ref=owner_ref)) for sid in paper.IDS},
        end="2026-10-13",as_of="2026-10-14T01:00:00Z",baselines={sid:{} for sid in paper.IDS})
    monkeypatch.setattr(paper,"metadata_preflight",lambda *_a,**_k:preflight)
    monkeypatch.setattr(paper,"check_resources",lambda *_a,**_k:None)
    monkeypatch.setattr(paper,"original_runtime_custody",lambda *_a,**_k:nullcontext(None))
    monkeypatch.setattr(paper,"runtime_custody_receipt",lambda *_a,**_k:{})
    monkeypatch.setattr(paper,"qualified_inputs",lambda *_a,**_k:dict(document=dict(source_bundle_ref={})))
    # Retain one spy across prepared dictionaries; never copy its Mock.
    def prepare(*_a,**_k): return {**prepared,"projection_receipts":[]},pd.DataFrame([dict(signal_date=pd.Timestamp(paper.START),ticker="SYNTHETIC")])
    monkeypatch.setattr(paper,"_prepare_candidate",prepare)
    monkeypatch.setattr(consumer,"metadata",lambda *_a,**_k:dict(prehistory_ref={},prehistory_calendar_ref={}))
    def bounded(_ref,_columns,date_column,*_a):
        return pd.DataFrame({"trade_date":[pd.Timestamp("2025-12-31")]}) if date_column=="trade_date" else pd.DataFrame([dict(signal_date=pd.Timestamp("2025-12-31"),ticker="SYNTHETIC")])
    monkeypatch.setattr(consumer,"bounded_frame",bounded)
    monkeypatch.setattr(paper,"original_metadata",lambda *_a,**_k:dict(inference=dict(prehistory_ref={},prehistory_calendar_ref={})))
    monkeypatch.setattr(paper,"full_r10_roles",lambda *_a,**_k:object())
    monkeypatch.setattr(paper,"forward_r10",lambda *_a,**_k:({},{}))
    monkeypatch.setattr(paper,"forward_r7",lambda *_a,**_k:({},{},{}))
    monkeypatch.setattr(paper,"execute_prepared",lambda *_a,**_k:(object(),{},[]))
    publish=Mock(side_effect=lambda *_a,**k:({},dict(path=k["candidate_id"],sha256="a"*64)))
    manifest=Mock(return_value=(dict(status="PREFIX_VERIFIED_DESCRIPTIVE_EXTENSION",end="2026-10-13"),dict(path="synthetic_manifest",sha256="a"*64)))
    monkeypatch.setattr(paper,"publish_verified",publish); monkeypatch.setattr(paper,"publish_manifest",manifest)
    if passed:
        result=paper.run_qualified_main(paths,capture_ref={},as_of=preflight["as_of"],execute=True)
        assert result["status"]=="PREFIX_VERIFIED_DESCRIPTIVE_EXTENSION" and result["candidate_ids"]==list(paper.IDS)
        assert publish.call_count==quality.call_count==3 and manifest.call_count==1 and capsys.readouterr().out==""
    else:
        with pytest.raises(ValueError) as raised:
            paper.run_qualified_main(paths,capture_ref={},as_of=preflight["as_of"],execute=True)
        assert str(raised.value)=="PAPER_EXTENSION_ORIGINAL_ACCOUNT_QUALIFICATION_FAILED:"+SID
        assert quality.call_count==1
        publish.assert_not_called(); manifest.assert_not_called()
        output=capsys.readouterr().out.splitlines(); assert len(output)==1
        assert json.loads(output[0])["failed_groups"]==["quote_qualified"]
        assert json.loads(output[0])["original_quality_owner_ref"]==owner_ref and len(output[0].encode("utf8")) + 2 <=16384


def test_quality_failure_diagnostic_removal_restores_original_driver_ast():
    import ast, hashlib
    before=Path("D:/us-tech-quant-cache/_maintenance/DEMO_FIVE_STRATEGY_PAPER_20261013_R1/account_quality_diagnostic_preimage/consensus_paper_performance.py.3df92ab054ffa6a91037b56fe22251cd835e3ad2dd190f1e6482f49606f77dfa.before")
    assert hashlib.sha256(before.read_bytes()).hexdigest()=="3df92ab054ffa6a91037b56fe22251cd835e3ad2dd190f1e6482f49606f77dfa"
    old={n.name:n for n in ast.parse(before.read_text(encoding="utf8")).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    new={n.name:n for n in ast.parse(Path(paper.__file__).read_text(encoding="utf8")).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    run=deepcopy(new["run_qualified_main"])
    class RemoveDiagnostic(ast.NodeTransformer):
        removed=0
        def visit_If(self,node):
            if any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=="_account_quality_failure_diagnostic" for n in ast.walk(node)) and len(node.body)==1:
                self.removed+=1; return None
            return self.generic_visit(node)
    inverse=RemoveDiagnostic(); inverse.visit(run)
    assert inverse.removed==1 and ast.dump(run,include_attributes=False)==ast.dump(old["run_qualified_main"],include_attributes=False)
    for name,node in old.items():
        if name!="run_qualified_main": assert ast.dump(new[name],include_attributes=False)==ast.dump(node,include_attributes=False)



def test_quality_failure_diagnostic_windows_crlf_exact_byte_boundary():
    q=quality_diagnostic_fixture(); checks=q["owner_checks"]
    checks["unknown_keys"]=[]
    checks["accounting_exception_keys"]=[dict(date="2026-10-13",effective_date="2026-10-13",ticker="S"*128,
        path_id="P"*128,reason="R"*256) for _ in range(20)]
    kwargs=dict(candidate_id=SID,end="2026-10-13",as_of="2026-10-14T01:00:00Z",owner_ref=dict(path="D:/",sha256="a"*64))
    baseline=paper._account_quality_failure_diagnostic(q,**kwargs)
    payload=json.loads(baseline)
    assert len(payload["owner_keys"]["accounting_exception_keys"]["keys"])==20
    for target in (16382,16383):
        delta=target-len(baseline.encode("utf8")); assert 0 < delta <= 4093
        multi,single=divmod(delta,4)
        owner={"path":"D:/"+"😀"*multi+"x"*single,"sha256":"a"*64}
        assert len(owner["path"])<=1024
        expected=deepcopy(payload); expected["original_quality_owner_ref"]=owner
        detailed=paper.canonical(expected); assert len(detailed.encode("utf8"))==target
        encoded=paper._account_quality_failure_diagnostic(q,**{**kwargs,"owner_ref":owner})
        assert len((encoded+"\r\n").encode("utf8"))<=16384
        if target==16382:
            assert encoded==detailed and json.loads(encoded)["owner_keys"]["accounting_exception_keys"]["keys"]
        else:
            value=json.loads(encoded)
            assert value["key_details_omitted_for_output_bound"] is True
            assert value["owner_keys"]["accounting_exception_keys"]["keys"]==[] and value["owner_keys"]["accounting_exception_keys"]["total"]==20


def _r10_protocol_fixture():
    import numpy as np
    from scripts.research.a2.inference.frozen_a94_actions import role_features
    frames={}; predictions={}
    for group,n in (("ENTRY",2),("INCUMBENT",4)):
        frame=pd.DataFrame({name:np.full(n,.01) for name in role_features("R10:"+group)})
        frame["signal_date"]=pd.Timestamp("2026-01-05")
        frame["sample_id"]=[group+str(i) for i in range(n)]
        frame["ticker"]=["I"+str(i) for i in range(n)]
        frame["security_id"]=["1"+str(i).zfill(8) for i in range(n)]
        frame["action_type"]=[0,1,1,0][:n]
        frame["entrant_ticker"]=[None,"ENTRY", "ENTRY",None][:n]
        frame["entrant_sid"]=[None,"200000001","200000001",None][:n]
        if group=="INCUMBENT":
            frame.loc[2,"e_friction"]=np.nan
            frame.loc[3,"i_friction"]=np.nan
        frames[group]=frame
        predictions[group]=dict(mean=np.full(n,.03),sigma=np.full(n,.02))
    return frames,predictions


def _original_r10_protocol(frames,predictions):
    """Execute the real original bind/predict/decode over synthetic custody only."""
    import numpy as np
    from scripts.research.a2.inference import frozen_a94_actions as owner
    from scripts.research.a2.training import stateful_mechanism as mechanism
    source={"path":"synthetic-no-read","sha256":"a"*64}
    auth=SimpleNamespace(provenance_json=json.dumps({"source_refs":{"action_inputs":source}}))
    candidate="R10_SYNTHETIC_PROTOCOL"
    rows={};handles={};qualification={"action_feature_inputs":{}}
    for group,frame in frames.items():
        slot="SYNTHETIC_"+group
        rows["new_model:"+slot]=dict(slot_id=slot,group=group,family="hgb",seed=20260928)
        _,features=mechanism.encode(frame,owner.role_features("R10:"+group))
        handles[group]=SimpleNamespace(kind="r10",authority=auth,row=rows["new_model:"+slot],features=tuple(features),model=SimpleNamespace(group=group))
        supported=(frame.e_friction.notna() & frame.i_friction.notna()).to_numpy() if group=="INCUMBENT" else np.ones(len(frame),bool)
        qualification["action_feature_inputs"]["R10:"+group]=dict(status="SOURCE_BOUND_COMPLETE_ORIGINAL_COMPUTED_STATE",source_ref=source,
            new_fit_count=0,outcome_columns_in_model_features=0,computed_signal_dates=["2026-01-05"],
            commitment=owner.input_commitment(frame,owner.role_features("R10:"+group),None,supported))
    auth.provenance_json=json.dumps({"source_refs":{"action_inputs":source},"source_qualification_ref":source})
    loader=SimpleNamespace(authority=auth,_check=lambda:None,_rows=rows,
        _candidates={candidate:{"model_ids":[h.row["slot_id"] for h in handles.values()]}})
    outputs={}
    with patch.object(owner.base.admission,"validate_descriptive_input_dates",return_value=None), \
         patch.object(owner.base.profile,"_document",return_value=qualification), \
         patch.object(owner.base.profile,"require_runtime_policy",return_value=None), \
         patch.object(owner,"_state",side_effect=lambda handle:handle.row), \
         patch.object(owner.r10,"predict",side_effect=lambda model,x:predictions[model.group]):
        for group,frame in frames.items():
            bound=owner.bind_action_input(loader,"R10:"+group,frame)
            output=owner.predict_r10(handles[group],bound)
            outputs[handles[group].row["slot_id"]]=output
        return owner.decode_candidate(loader,candidate,outputs)


@pytest.mark.parametrize("candidate_id",paper.IDS[:2])
def test_runtime_and_main_r10_match_original_support_and_entrant_identity(tmp_path,monkeypatch,candidate_id):
    import joblib,numpy as np,weakref
    from scripts.research.a2.inference import consensus_paper as consumer
    from scripts.research.a2.inference.frozen_a94_actions import role_features
    from scripts.research.a2.training import stateful_mechanism as mechanism
    roles,native=_r10_protocol_fixture()
    expected=_original_r10_protocol(roles,native)
    states={};lifetimes=[];batches=[];matrix_lifetimes=[]
    for group,frame in roles.items():
        _,names=mechanism.encode(frame,role_features("R10:"+group))
        key="ACTION_VALUE_"+group+"_H5_RIDGE" if candidate_id==paper.IDS[1] else "MODEL_"+group
        states[key]=dict(state_type="new_model",model_ref=dict(path=group+"_MODEL",sha256="a"*64),
            metadata_row=dict(group=group,family="ridge" if candidate_id==paper.IDS[1] else "elasticnet",feature_order=names))
        states["ACTION_VALUE_"+group+"_SCALER"]=dict(state_type="scaler",model_ref=dict(path=group+"_SCALER",sha256="b"*64))
    class Model:
        def __init__(self,group):self.group=group
        def fit(self,*args,**kwargs):raise AssertionError("NO_FIT")
    class Scaler:
        def transform(self,x):return x
        def fit(self,*args,**kwargs):raise AssertionError("NO_FIT")
    def load(path):
        name=str(path);obj=Scaler() if name.endswith("_SCALER") else Model(name.rsplit("_",1)[0])
        lifetimes.append(weakref.ref(obj));return obj
    def predict(model,x):
        batches.append((model.group,len(x)));matrix_lifetimes.append(weakref.ref(x));return native[model.group]
    from scripts.research.a2.training import stateful_final_action_packets as packets
    original_decode=packets.decode_r10_row
    def decode(*args,**kwargs):
        assert all(lifetime() is None for lifetime in lifetimes[-2:])
        assert matrix_lifetimes[-1]() is None
        return original_decode(*args,**kwargs)
    monkeypatch.setattr(packets,"decode_r10_row",decode)
    monkeypatch.setattr(consumer,"resource_check",lambda:None)
    monkeypatch.setattr(paper,"check_resources",lambda *args,**kwargs:None)
    monkeypatch.setattr(consumer,"frozen_states",lambda *args:states)
    monkeypatch.setattr(consumer,"verify",lambda ref:Path(ref["path"]))
    monkeypatch.setattr(joblib,"load",load)
    monkeypatch.setattr(consumer,"predict_r10",predict)
    monkeypatch.setattr(pd,"read_parquet",lambda path:roles[str(path).removesuffix("_ROWS")].copy())
    doc=dict(signal_date="2026-01-05",input_refs={group:dict(path=group+"_ROWS",sha256="c"*64) for group in roles})
    runtime,refs=consumer.decoded_actions(SimpleNamespace(),candidate_id,doc)
    authority=paper.PaperAuthority(pd.Timestamp(paper.START),pd.Timestamp("2026-01-05"),pd.Timestamp("2026-01-06T01:00:00Z"),
        (candidate_id,),"[]","{}","{}","{}",None,seal=paper._SEAL)
    main,main_refs=paper.forward_r10(SimpleNamespace(),candidate_id,roles,authority)
    assert runtime==expected[pd.Timestamp("2026-01-05")]
    assert main=={candidate_id:expected} and main_refs==refs
    assert [row["decision"] for row in runtime]==["BUY","BUY","SELL","REPLACE","REFERENCE","REFERENCE"]
    assert runtime[3]["entrant_security_id"]=="200000001"
    assert all(row["source_score"] is None for row in runtime[-2:])
    assert batches==[("ENTRY",2),("INCUMBENT",4)]*2
    assert all(lifetime() is None for lifetime in lifetimes)
    assert list(roles["INCUMBENT"].e_friction.isna())==[False,False,True,False]


@pytest.mark.parametrize("field",["e_friction","i_friction","action_type","entrant_sid"])
def test_r10_decoder_missing_original_interface_field_fails_closed(field):
    from scripts.research.a2.inference import consensus_paper as consumer
    row=dict(ticker="SYNTHETIC",security_id="100000001",sample_id="one",action_type=1,
        e_friction=.001,i_friction=.001,entrant_ticker="ENTRY",entrant_sid="200000001")
    row.pop(field)
    with pytest.raises(ValueError,match="ORIGINAL_SUPPORT_AND_SID_FIELDS_REQUIRED"):
        consumer.r10_decoder_input(row,{"mean":.03},group="INCUMBENT")


def test_original_overlay_accepts_restored_replacement_sid_and_rejects_mismatch():
    import numpy as np
    from scripts.research.a2.inference import consensus_paper as consumer
    from scripts.research.a2.training import stateful_final_action as owner,stateful_final_action_packets as packets
    from scripts.research.a2.retained.a2_pto_full_compat_20260928_r2.fast_account import TargetDecision
    row=dict(ticker="INC",security_id="100000001",sample_id="replace",action_type=1,
        e_friction=.001,i_friction=.001,entrant_ticker="ENTRY",entrant_sid="200000001")
    ctx=SimpleNamespace(signal_date=pd.Timestamp("2025-01-02"),tickers=np.array(["INC","ENTRY"]),
        decision_mask=np.ones((1,2),bool),current_units=np.array([[1.,0.]]),buy_allowed=np.ones((1,2),bool))
    class Raw:
        def __init__(self,*args,**kwargs):self.audit=[]
        def __call__(self,di,context):return TargetDecision(np.array([[.25,.05]]),explicit_mask=np.ones((1,2),bool))
    def evaluate(record):
        prepared=consumer.r10_decoder_input(record,{"mean":.03},group="INCUMBENT")
        proposal=packets.decode_r10_row(prepared,0,group="INCUMBENT")
        with patch.object(owner,"StatefulOverlay",Raw):
            overlay=owner.FinalActionOverlay([dict(candidate_id=SID)],{},np.array([[False,True]]),np.ones((1,2),bool),np.ones((1,2)),
                action_packets={SID:{ctx.signal_date:[proposal]}},resource_decoder=packets.decode_resource_proposals,
                sid_by_key={(ctx.signal_date,"INC"):"100000001",(ctx.signal_date,"ENTRY"):"200000001"})
        return overlay(0,ctx),overlay.action_audit
    target,audit=evaluate(row)
    assert target.weights[0,0]==0 and target.explicit_mask[0,0]
    assert target.weights[0,1]==.05 and any(item["consumer_status"]=="APPLIED" for item in audit)
    for invalid in ({**row,"entrant_sid":"900000009"},{**row,"security_id":"900000009"},{**row,"e_friction":np.nan}):
        target,audit=evaluate(invalid)
        assert target.weights[0,0]==.25 and not any(item["consumer_status"]=="APPLIED" for item in audit)


@pytest.mark.parametrize("dtype",["float32","float64"])
@pytest.mark.parametrize("mode",["standard","standard_readonly_input","standard_copy_false","alias","view","readonly","owned_custom","standard_override_owned"])
def test_r10_scaled_input_is_bit_exact_and_only_reuses_owned_standard_buffer(monkeypatch,dtype,mode):
    import numpy as np
    from sklearn.preprocessing import StandardScaler
    from scripts.research.a2.inference import consensus_paper as consumer
    dtype=np.dtype(dtype)
    initial=np.array([[np.nan,-0.],[np.finfo(dtype).max,-np.finfo(dtype).max],[1.25,-2.5]],dtype=dtype)
    def scaler():
        if mode.startswith("standard"):
            value=StandardScaler(copy=mode!="standard_copy_false")
            value.mean_=np.zeros(2);value.scale_=np.full(2,.5);value.var_=np.full(2,.25)
            value.n_features_in_=2;value.n_samples_seen_=10
            if mode=="standard_override_owned":value.transform=lambda x:x.copy()
            return value
        class Custom:
            def transform(self,x):
                if mode=="alias":return x
                if mode=="view":return x.view()
                output=x.copy();output[1]=[np.inf,-np.inf]
                if mode=="readonly":output.setflags(write=False)
                self.returned=output;return output
        return Custom()
    original=scaler();candidate=scaler();before=initial.copy();incoming=initial.copy()
    if mode=="standard_readonly_input":before.setflags(write=False);incoming.setflags(write=False)
    fill=np.nan_to_num
    with np.errstate(over="ignore",invalid="ignore"):
        transformed=original.transform(before)
        expected=fill(transformed,nan=0.)
    received=[]
    def observed(array,**kwargs):
        result=fill(array,**kwargs)
        received.append(dict(copy=kwargs["copy"],same=result is array,bytes=array.nbytes))
        return result
    monkeypatch.setattr(np,"nan_to_num",observed)
    with np.errstate(over="ignore",invalid="ignore"):
        actual=consumer.r10_scaled_input(candidate,incoming)
    assert actual.dtype==expected.dtype and actual.shape==expected.shape and actual.strides==expected.strides
    assert actual.tobytes(order="A")==expected.tobytes(order="A")
    np.testing.assert_array_equal(incoming,before)
    fast=mode in ("standard","standard_readonly_input")
    assert received==[dict(copy=not fast,same=fast,bytes=actual.nbytes)]
    assert not np.shares_memory(actual,incoming) and actual.flags.writeable
    if hasattr(candidate,"returned"):
        np.testing.assert_array_equal(candidate.returned,transformed)
        assert not np.shares_memory(actual,candidate.returned)


def test_r10_scaled_input_readonly_alias_preserves_original_transform_behavior():
    import numpy as np
    from sklearn.preprocessing import StandardScaler
    from scripts.research.a2.inference import consensus_paper as consumer
    scaler=StandardScaler(copy=False)
    scaler.mean_=np.zeros(2);scaler.scale_=np.ones(2);scaler.var_=np.ones(2)
    scaler.n_features_in_=2;scaler.n_samples_seen_=10
    values=np.array([[np.nan,1.]])
    values.setflags(write=False)
    try:
        original=np.nan_to_num(scaler.transform(values),nan=0.)
    except ValueError as error:
        with pytest.raises(type(error)) as candidate:
            consumer.r10_scaled_input(scaler,values)
        assert str(candidate.value)==str(error)
    else:
        candidate=consumer.r10_scaled_input(scaler,values)
        assert candidate.dtype==original.dtype and candidate.shape==original.shape
        assert candidate.tobytes()==original.tobytes()
    assert not values.flags.writeable


def test_r10_runtime_records_remain_bounded_after_complete_prediction_and_release(monkeypatch):
    import joblib,numpy as np,weakref
    from scripts.research.a2.inference import consensus_paper as consumer
    from scripts.research.a2.inference.frozen_a94_actions import role_features
    from scripts.research.a2.training import stateful_mechanism as mechanism,stateful_final_action_packets as packets
    frames={};states={};expected=[];batch_sizes=[];lifetimes=[];matrix_lifetimes=[];record_sizes=[]
    for group,size in (("ENTRY",4103),("INCUMBENT",4105)):
        frame=pd.DataFrame({name:np.full(size,.01) for name in role_features("R10:"+group)})
        frame["signal_date"]=pd.Timestamp("2026-01-05")
        frame["sample_id"]=[group+str(i) for i in range(size)]
        frame["ticker"]=["T"+str(i) for i in range(size)]
        frame["security_id"]=[str(i+100000000) for i in range(size)]
        frame["action_type"]=np.arange(size)%2
        frame["entrant_ticker"]=[None if i%2==0 else "ENTRY" for i in range(size)]
        frame["entrant_sid"]=[None if i%2==0 else "200000001" for i in range(size)]
        frames[group]=frame
        _,names=mechanism.encode(frame,role_features("R10:"+group))
        states["MODEL_"+group]=dict(state_type="new_model",model_ref=dict(path=group+"_MODEL",sha256="a"*64),metadata_row=dict(group=group,feature_order=names))
        states["ACTION_VALUE_"+group+"_SCALER"]=dict(state_type="scaler",model_ref=dict(path=group+"_SCALER",sha256="b"*64))
        for row in frame.to_dict("records"):
            expected.append(packets.decode_r10_row(consumer.r10_decoder_input(row,{"mean":.03},group=group),len(expected),group=group))
    class Model:
        def __init__(self,group):self.group=group
    class Scaler:
        def transform(self,x):return x
    def load(path):
        name=str(path);obj=Scaler() if name.endswith("_SCALER") else Model(name.rsplit("_",1)[0])
        lifetimes.append(weakref.ref(obj));return obj
    def predict(model,x):
        batch_sizes.append((model.group,len(x)));matrix_lifetimes.append(weakref.ref(x))
        return {"mean":np.full(len(x),.03)}
    original_decode=packets.decode_r10_row
    def decode(*args,**kwargs):
        assert all(lifetime() is None for lifetime in lifetimes[-2:]) and matrix_lifetimes[-1]() is None
        return original_decode(*args,**kwargs)
    original_records=pd.DataFrame.to_dict
    def records(frame,*args,**kwargs):
        if (args and args[0]=="records") or kwargs.get("orient")=="records":record_sizes.append(len(frame))
        return original_records(frame,*args,**kwargs)
    monkeypatch.setattr(consumer,"resource_check",lambda:None)
    monkeypatch.setattr(consumer,"frozen_states",lambda *args:states)
    monkeypatch.setattr(consumer,"verify",lambda ref:Path(ref["path"]))
    monkeypatch.setattr(joblib,"load",load)
    monkeypatch.setattr(consumer,"predict_r10",predict)
    monkeypatch.setattr(pd,"read_parquet",lambda path:frames[str(path).removesuffix("_ROWS")].copy())
    monkeypatch.setattr(pd.DataFrame,"to_dict",records)
    monkeypatch.setattr(packets,"decode_r10_row",decode)
    doc=dict(signal_date="2026-01-05",input_refs={group:dict(path=group+"_ROWS",sha256="c"*64) for group in frames})
    actual,refs=consumer.decoded_actions(SimpleNamespace(),paper.IDS[0],doc)
    assert actual==expected and len(refs)==4
    assert batch_sizes==[("ENTRY",4103),("INCUMBENT",4105)]
    assert record_sizes==[4096,7,4096,9]


def test_r10_role_temporaries_release_before_pair_and_clean_projection(monkeypatch):
    import weakref
    from scripts.research.a2.inference import frozen_a94_state as state,frozen_a94_actions as actions,consensus_paper as consumer
    from scripts.research.a2.training import stateful_mechanism_inputs as inputs
    from scripts.research.a2.data import state_label_foundation as foundation
    prefix,calendar=input_fixture();before=prefix.copy(deep=True)
    expected=consumer.original_frames(prefix,calendar,calendar[-1])
    refs=dict(proxy=[],heads=[],pairs=[],current=[])
    scoped_proxy=consumer.scoped_proxy_frame
    def tracked_proxy(*args,**kwargs):
        result=scoped_proxy(*args,**kwargs);refs["proxy"].append(weakref.ref(result));return result
    original_pairs=foundation.all_incumbent_pairs
    def pairs(*args,**kwargs):
        assert refs["proxy"] and all(ref() is None for ref in refs["proxy"])
        result=original_pairs(*args,**kwargs);refs["pairs"].append(weakref.ref(result));return result
    original_single=inputs.attach_single_labels
    def single(frame,*args,**kwargs):
        if not refs["current"]:refs["current"].append(weakref.ref(frame))
        result=original_single(frame,*args,**kwargs);refs["heads"].append(weakref.ref(result));return result
    original_pair_head=inputs.attach_pair_labels
    def pair_head(*args,**kwargs):
        result=original_pair_head(*args,**kwargs);refs["heads"].append(weakref.ref(result));return result
    original_features=actions.role_features
    def features(*args,**kwargs):
        assert all(ref() is None for values in refs.values() for ref in values)
        return original_features(*args,**kwargs)
    monkeypatch.setattr(consumer,"scoped_proxy_frame",tracked_proxy)
    monkeypatch.setattr(foundation,"all_incumbent_pairs",pairs)
    monkeypatch.setattr(inputs,"attach_single_labels",single)
    monkeypatch.setattr(inputs,"attach_pair_labels",pair_head)
    monkeypatch.setattr(actions,"role_features",features)
    actual=paper.full_r10_roles(prefix,calendar,calendar[-1])
    pd.testing.assert_frame_equal(prefix,before,check_exact=True,check_dtype=True)
    for name,frame in expected.items():
        latest=actual[name].loc[actual[name].signal_date.eq(calendar[-1])].reset_index(drop=True)
        pd.testing.assert_frame_equal(latest,frame.reset_index(drop=True),check_exact=True,check_dtype=True)


# New independent source capability: temporary metadata and byte fixtures only.
@pytest.fixture
def ridge_scope_case(tmp_path,monkeypatch):
    from scripts.research.a2.evaluation import frozen_a94_profile as profile, frozen_test_authority as common
    import hashlib
    sid=paper.IDS[1]
    def write(name,value):
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(paper.canonical(value),encoding="utf-8");return paper.reference(path)
    def blob(name):
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(('synthetic:'+name).encode());return paper.reference(path)
    policy=dict(candidate_id=sid,scientific_tuple_sha256=paper._RIDGE_TUPLE,action="raw",gross="fixed",forecast="none",execution_friction={"one_way_bps":10})
    sha={};rows=[];scales=[];state_refs={}
    for role in ("ENTRY","INCUMBENT"):
        features=[role+"_x",role+"_z"];feature_sha=hashlib.sha256(paper.canonical(features).encode()).hexdigest()
        for family in ("ridge","SCALER"):
            key=f"ACTION_VALUE_{role}_H5_2025_"+("ridge_MID_20260928" if family=="ridge" else "SCALER")
            mr=blob(key+"/model.joblib");sha[key]=mr["sha256"];rr=write(key+"/fit_receipt.json",{"scientific_tuple_identity_only":True})
            tup=dict(slot_id=key,year=2025,family=family,capacity="MID" if family=="ridge" else "SHARED",
                dates_sha256=("e" if role=="ENTRY" else "i")*64,design_sha256="d"*64,features=features,x_shape=[3,2],weights_sha256="w"*64,x_sha256=("a" if family=="ridge" else "b")*64)
            if family=="ridge":tup.update(group=role,horizon=5,cutoff_exclusive="2025-01-01")
            tuple_sha=hashlib.sha256(paper.canonical(tup).encode()).hexdigest();projected={k:v for k,v in tup.items() if k!="features"};projected["features_ref"]=feature_sha
            row=dict(slot_id=key,year=2025,family=family,capacity=tup["capacity"],model_path=mr["path"],model_sha256=mr["sha256"],receipt_ref=rr,
                status="TRAINED",scientific_tuple=projected,scientific_tuple_sha256=tuple_sha,feature_order=features,feature_count=len(features),feature_schema_sha256=feature_sha,
                model_binary_hash_verified=True,receipt_hash_matches_census=True,identity_matches_census=True)
            if family=="ridge":row.update(group=role,horizon=5,cutoff_exclusive="2025-01-01")
            (rows if family=="ridge" else scales).append(row);state_refs[("new_model:" if family=="ridge" else "new_scaler:")+key]=dict(model_ref=mr,receipt_ref=rr)
    # Preserve exact original registry closure order, independent of physical existence.
    keys=[r["slot_id"] for r in rows]+[r["slot_id"] for r in scales];sha={key:sha[key] for key in keys}
    binding=dict(candidate_id=sid,scientific_tuple_sha256=paper._RIDGE_TUPLE,specification=policy,source_group="R10",runtime_owner="FINAL_ACTION_OVERLAY",
        required_action_roles=["R10:ENTRY","R10:INCUMBENT"],dependency_closure=dict(status="COMPLETE",state_ids=list(state_refs),reason=None),lookback=None)
    # Arrange state refs in the original declaration order.
    binding["dependency_closure"]["state_ids"]=["new_model:"+key for key in keys if "SCALER" not in key]+["new_scaler:"+key for key in keys if "SCALER" in key]
    registry=write('registry.json',dict(task_id=profile.ALL_TASK,candidates=[binding]));census=write('census.json',dict(model_states=rows,external_scaler_states=scales))
    release=write('config.json',{});plan=write('plan.json',{});schedule=write('schedule.json',{})
    src=blob('source_identity.bin');asof="2026-10-09T01:00:00+00:00"
    window=dict(window_id="MAIN",start=paper.START,end=paper.PREFIX_END)
    contract=dict(task_id=profile.ALL_TASK,metadata_refs=dict(plan=plan,inventory=registry,schedule=schedule),plan={},candidate_bindings=[binding],
        state_refs=dict(state_refs),schedule=dict(windows=[window]),raw_selector_binding=dict(model_ref=src))
    # Unrelated missing legacy state must never enter the single-candidate physical request set.
    contract['state_refs']['new_model:UNUSED_HGB']=dict(model_ref=dict(path=str(tmp_path/'absent_hgb.joblib'),sha256='0'*64),receipt_ref=dict(path=str(tmp_path/'absent_hgb_receipt.json'),sha256='1'*64))
    sources={name:src for name in common.SOURCE_GROUPS}
    qual=dict(schema="A_2026_DESCRIPTIVE_SOURCE_QUALIFICATION_R1",task_id=profile.ALL_TASK,status="QUALIFIED_FOR_DECLARED_RESEARCH_SCOPE",source_refs=sources,
        as_of=asof,common_calendar_start=paper.START,common_calendar_end=paper.PREFIX_END,common_calendar_selection="SOURCE_AVAILABILITY_AND_ORIGINAL_CALENDAR_ONLY",
        raw_selector_binding=contract['raw_selector_binding'],groups={key:True for key in common.SOURCE_GROUPS},source_slices={key:dict(source_ref=src,no_2027_content=True,view_only=True,
        content_start="2023-01-03",content_end=paper.PREFIX_END,available_at=asof) for key in common.SOURCE_GROUPS})
    qual['candidate_source_qualification']={sid:dict(status='QUALIFIED',required_action_roles=['R10:ENTRY','R10:INCUMBENT'],source_ref=src)}
    qualification=write('qualification.json',qual)
    bound=dict(schema="A_2026_DESCRIPTIVE_ACCOUNT_ADMISSION_R1",task_id=profile.ALL_TASK,status="SOURCE_AND_POLICY_BOUND_FOR_DESCRIPTIVE_EVALUATION",
        strict_PIT_promotion_eligible=False,production_qualified=False,finalist_selected=False,new_fit=0,plan_ref=plan,candidate_manifest_ref=registry,
        allowed_path_ids=[sid],candidate_bindings=[binding],state_refs=contract['state_refs'],initial_cash_usd=3000,initial_holdings=[],initial_receivables=[],fresh_account=True,
        as_of=asof,windows=[window],schedule_ref=schedule,feature_history_start="2023-01-03",source_refs=sources,source_qualification_ref=qualification)
    admission=write('admission.json',bound)
    release=write('config.json',dict(admission_ref=admission,inventory_ref=registry,schedule_ref=schedule))
    meta=dict(candidate=policy,release_ref=release,request=dict(schema="A_2026_DESCRIPTIVE_AUTHORITY_REF_R1",task_id=profile.ALL_TASK,admission_ref=admission,window_id="MAIN"),release=dict(schedule_ref=schedule))
    monkeypatch.setattr(paper,'_RIDGE_REGISTRY',registry);monkeypatch.setattr(paper,'_RIDGE_CENSUS',census);monkeypatch.setattr(paper,'RIDGE_CONFIG',release);monkeypatch.setattr(paper,'_RIDGE_MODEL_SHA',sha)
    monkeypatch.setattr(profile,'profile_contract',lambda *args,**kwargs:deepcopy(contract))
    monkeypatch.setattr(profile,'_contract_as_of',lambda value:asof);monkeypatch.setattr(profile,'_accounting_decision',lambda *args:None)
    monkeypatch.setattr(profile,'_safe_path',lambda ref:Path(ref['path']))
    monkeypatch.setattr(profile,'_physical',lambda ref:paper.verified(ref))
    monkeypatch.setattr(profile,'_document',lambda ref:json.loads(paper.verified(ref).read_text(encoding='utf-8')))
    monkeypatch.setattr(common,'_load_post_verified_binding',lambda *args:'{}')
    return dict(meta=meta,contract=contract,rows=rows,scales=scales,registry=registry,census=census,write=write,profile=profile,common=common,bound=bound,qual=qual)


def test_ridge_finite_scope_qualifies_required4_without_inheriting_old_all(ridge_scope_case):
    case=ridge_scope_case;old=case['profile'];before=old._document
    with pytest.raises(FileNotFoundError):old.load_authority(case['meta']['request'])
    value=paper._ridge_source_authority(case['meta'])
    assert type(value) is paper.RidgeOriginalSourceScope and value.allowed_path_ids==(paper.IDS[1],)
    assert value.seal is paper._RIDGE_SCOPE_SEAL and value.seal is not case['common']._SEAL
    assert old._document is before
    provenance=json.loads(value.provenance_json);assert provenance['legacy_all_admission']=='BLOCKED_NOT_INHERITED'
    assert len(provenance['required_frozen_source_evidence']['states'])==4
    with pytest.raises(FileNotFoundError):old.load_authority(case['meta']['request'])


@pytest.mark.parametrize('change',['model_bytes','model_missing','fit_status','cutoff','feature_order','tuple_hash','scaler_dates','scaler_weights','registry_scope','policy','candidate'])
def test_ridge_finite_scope_rejects_changed_required_science_or_missing_leaf(ridge_scope_case,monkeypatch,change):
    case=ridge_scope_case
    if change=='model_bytes':Path(case['rows'][0]['model_path']).write_bytes(b'changed actual model bytes')
    elif change=='model_missing':Path(case['rows'][0]['model_path']).unlink()
    elif change=='candidate':case['meta']['candidate']['candidate_id']=paper.IDS[0]
    elif change=='policy':case['meta']['candidate']['gross']='other'
    elif change=='registry_scope':
        data=json.loads(Path(case['registry']['path']).read_text());data['candidates'][0]['dependency_closure']['state_ids'].pop();monkeypatch.setattr(paper,'_RIDGE_REGISTRY',case['write']('registry_changed.json',data))
    else:
        rows=deepcopy(case['rows']);scales=deepcopy(case['scales'])
        if change=='fit_status':rows[0]['status']='UNTRAINED'
        if change=='cutoff':rows[0]['cutoff_exclusive']='2026-01-01'
        if change=='feature_order':rows[0]['feature_order'].reverse()
        if change=='tuple_hash':rows[0]['scientific_tuple_sha256']='f'*64
        if change=='scaler_dates':scales[0]['scientific_tuple']['dates_sha256']='f'*64
        if change=='scaler_weights':scales[0]['scientific_tuple']['weights_sha256']='f'*64
        monkeypatch.setattr(paper,'_RIDGE_CENSUS',case['write']('census_changed.json',dict(model_states=rows,external_scaler_states=scales)))
    with pytest.raises((ValueError,FileNotFoundError)):paper._ridge_source_authority(case['meta'])


def test_ridge_new_source_scope_requires_original_tuple_policy_fees_and_pre2026_dates(ridge_scope_case):
    value=paper._ridge_source_authority(ridge_scope_case['meta']);candidate=ridge_scope_case['meta']['candidate'];policy=paper._ridge_policy(value,[candidate])
    assert policy.runtime_policy_ids==(paper.IDS[1],)
    dates=pd.DatetimeIndex([paper.START,paper.FIRST_EXECUTION,paper.PREFIX_END]);account=dict(initial_nav=3000,initial_cash=3000,initial_holdings=[],initial_receivables=[])
    paper._ridge_original_account(policy,dates,[paper.IDS[1]],account,candidate['execution_friction'])
    paper._ridge_original_accounting(policy,[],require_exact=True)
    for modified in ({**account,'initial_nav':10000},{**account,'initial_holdings':['X']}):
        with pytest.raises(ValueError):paper._ridge_original_account(policy,dates,[paper.IDS[1]],modified,candidate['execution_friction'])
    with pytest.raises(ValueError):paper._ridge_original_account(policy,dates,[paper.IDS[1]],account,{'one_way_bps':5})
    with pytest.raises(ValueError):paper._ridge_original_dates(policy,['2027-01-01'])
    with pytest.raises(ValueError):paper._ridge_policy(value,[{**candidate,'gross':'other'}])
    with pytest.raises(ValueError):paper._ridge_scope(deepcopy({'seal':paper._RIDGE_SCOPE_SEAL}))


def test_ridge_qualification_projection_exception_restores_all_original_namespaces(ridge_scope_case,monkeypatch):
    case=ridge_scope_case;profile=case['profile'];original={key:getattr(profile,key) for key in ('load_authority','_physical','_document','profile_contract')}
    monkeypatch.setattr(profile,'_physical',lambda ref:(_ for _ in ()).throw(ValueError('synthetic physical error')))
    snapshot={key:getattr(profile,key) for key in original}
    with pytest.raises(ValueError):paper._ridge_source_authority(case['meta'])
    assert all(getattr(profile,key) is value for key,value in snapshot.items())


def test_required_census_projection_never_decodes_unselected_fit_stats(tmp_path,monkeypatch):
    ref_path=tmp_path/'metadata.json';ref_path.write_text(json.dumps({'model_states':[{'slot_id':'KEEP','model_path':'synthetic','fit_stats':list(range(9000))},{'slot_id':'DROP','fit_stats':list(range(9000))}]}))
    assert paper._project_rows(paper.reference(ref_path),'model_states',{'slot_id','model_path'},selected={'KEEP'})==[{'slot_id':'KEEP','model_path':'synthetic'}]


def test_ridge_candidate_dispatch_keeps_other_two_original_authority_paths(monkeypatch):
    from scripts.research.a2.evaluation import frozen_test_authority as common
    old=SimpleNamespace();calls=[];monkeypatch.setattr(common,'load_descriptive_authority',lambda request:(calls.append(request),old)[1])
    monkeypatch.setattr(paper,'_ridge_source_authority',lambda meta:(_ for _ in ()).throw(AssertionError('only Ridge scope')))
    for sid in (paper.IDS[0],paper.IDS[2]):
        assert paper._original_authority({'candidate':{'candidate_id':sid},'release':{},'request':{'synthetic_sid':sid}}) is old
    assert len(calls)==2


def test_ridge_finite_scope_requires_accepted_census_in_place_of_four_absent_receipts(ridge_scope_case,monkeypatch):
    case=ridge_scope_case
    for row in [*case['rows'],*case['scales']]:Path(row['receipt_ref']['path']).unlink()
    with pytest.raises(FileNotFoundError):case['profile'].load_authority(case['meta']['request'])
    scoped=paper._ridge_source_authority(case['meta'])
    evidence=json.loads(scoped.provenance_json)['required_frozen_source_evidence']
    assert len(evidence['receipt_evidence'])==4
    assert all(not r['original_receipt_bytes_present'] and not r['original_receipt_bytes_verified'] for r in evidence['receipt_evidence'])
    assert evidence['census_ref']==case['census'] and evidence['legacy_all_status']=='BLOCKED_NOT_INHERITED'
    changed=deepcopy(case['rows']);changed[0]['model_binary_hash_verified']=False
    monkeypatch.setattr(paper,'_RIDGE_CENSUS',case['write']('bad_census.json',dict(model_states=changed,external_scaler_states=case['scales'])))
    with pytest.raises(ValueError,match='ORIGINAL_FIT_CENSUS_REQUIRED'):paper._ridge_source_authority(case['meta'])


@pytest.mark.parametrize('change',['source_scope','source_qualified','source_clock','origin_ref','window','initial_cash'])
def test_ridge_finite_scope_retains_original_source_clock_window_and_account_guards(ridge_scope_case,change):
    case=ridge_scope_case
    if change=='origin_ref':case['meta']['request']['admission_ref']=case['write']('other_admission.json',case['bound'])
    elif change=='window':case['meta']['request']['window_id']='OTHER'
    else:
        bound=deepcopy(case['bound']);qual=deepcopy(case['qual'])
        if change=='source_scope':qual['source_slices']['action_inputs']['content_end']='2027-01-01'
        if change=='source_qualified':qual['candidate_source_qualification'][paper.IDS[1]]['status']='BLOCKED';qual['candidate_source_qualification'][paper.IDS[1]]['reason']='SYNTHETIC';qual['groups']['action_inputs']=False
        if change=='source_clock':qual['source_slices']['action_inputs']['available_at']='2027-01-01T00:00:00Z'
        if change=='initial_cash':bound['initial_cash_usd']=10000
        # Preserve every ref/hash binding; these fail original qualification, not arbitrary SHA failures.
        bound['source_qualification_ref']=case['write']('qualification.json',qual)
        admission=case['write']('admission.json',bound)
        config=case['write']('config.json',dict(admission_ref=admission,inventory_ref=case['registry'],schedule_ref=case['bound']['schedule_ref']))
        case['meta']['release_ref'].update(config)
        case['meta']['request']['admission_ref']=admission
    with pytest.raises(ValueError):paper._ridge_source_authority(case['meta'])


def test_ridge_finite_scope_seal_extra_policy_and_old_all_capability_are_rejected(ridge_scope_case):
    from dataclasses import replace
    case=ridge_scope_case;value=paper._ridge_source_authority(case['meta'])
    for forged in (replace(value,seal=case['common']._SEAL),replace(value,allowed_path_ids=paper.IDS),replace(value,source_ready_policy_ids=paper.IDS),replace(value,capability='INFERENCE_ONLY'),replace(value,task_id='OTHER'),replace(value,end=pd.Timestamp('2026-10-09'))):
        with pytest.raises(ValueError):paper._ridge_scope(forged)
    with pytest.raises(ValueError):case['common'].load_descriptive_authority(value)
    with pytest.raises(ValueError):paper._ridge_policy(value,[case['meta']['candidate'],{'candidate_id':paper.IDS[0]}])


def test_ridge_finite_scope_binds_completed_main_and_preserves_original_accounting_rules(ridge_scope_case,tmp_path):
    case=ridge_scope_case;original=paper._ridge_source_authority(case['meta']);candidate=case['meta']['candidate']
    _,_,_,old=fixtures(tmp_path);calendar=json.loads(old.provenance_json)['calendar_qualification']
    dates=pd.DatetimeIndex(calendar['main_sessions']);clock='2026-10-13T01:00:00+00:00'
    proof=dict(seal=paper._SEAL,dates=[str(d.date()) for d in dates],as_of=clock,refs={},calendar_qualification=calendar)
    account=dict(initial_nav=3000,initial_cash=3000,initial_holdings=[],initial_receivables=[])
    authority=paper.bind_authority(original,candidates=[candidate],dates=dates,as_of=clock,source_refs={},qualification_receipt=proof,account=account,friction=candidate['execution_friction'])
    assert authority.allowed_path_ids==(paper.IDS[1],) and type(authority.original_authority) is paper.RidgeOriginalSourceScope
    paper.validate_descriptive_account(authority,dates,[paper.IDS[1]],account,candidate['execution_friction'])
    paper.validate_reconstructed_accounting_events(authority,[],require_exact=True)
    with pytest.raises(ValueError):paper.bind_authority(original,candidates=[candidate],dates=dates,as_of='2026-10-12T19:59:59Z',source_refs={},qualification_receipt=proof,account=account,friction=candidate['execution_friction'])
    with pytest.raises(ValueError):paper.bind_authority(original,candidates=[candidate],dates=dates,as_of=clock,source_refs={},qualification_receipt={**proof,'seal':None},account=account,friction=candidate['execution_friction'])


def test_ridge_finite_scope_projection_changes_only_declared_qualification_seams(ridge_scope_case):
    case=ridge_scope_case;evidence=paper.ridge_source_evidence(case['meta'])
    _,receipt=paper._ridge_qualification_projection(case['profile'],evidence)
    assert receipt['other_qualification_ast_unchanged'] and receipt['legacy_all_guard_unchanged']
    assert receipt['qualification_seams']==['EXACT_REQUIRED4_CENSUS_CUSTODY','NEW_SINGLE_RIDGE_SOURCE_TYPE_AND_SEAL']


def test_ridge_finite_scope_keeps_original_postverified_event_header_and_exact_catalogue(ridge_scope_case):
    from dataclasses import replace
    case=ridge_scope_case;value=paper._ridge_source_authority(case['meta'])
    binding=dict(task_id=value.task_id,clock_role='POST_VERIFIED_ACCOUNTING_ONLY',strict_PIT_promotion_eligible=False,production_qualified=False,
        authorization_ref=case['profile']._post_verified_decision_ref(value.task_id),events=[dict(event_fingerprint='synthetic-only')])
    bound=replace(value,research_cash_reconstruction_json=paper.canonical(binding))
    paper._ridge_original_accounting(bound,[],require_exact=False)
    with pytest.raises(ValueError,match='CATALOGUE_CHANGED'):paper._ridge_original_accounting(bound,[],require_exact=True)
    binding['authorization_ref']={'path':'synthetic-wrong','sha256':'0'*64}
    with pytest.raises(ValueError,match='HUMAN_DECISION_REQUIRED'):paper._ridge_original_accounting(replace(value,research_cash_reconstruction_json=paper.canonical(binding)),[],require_exact=True)


# Allocation-only proxy/encoder compatibility: synthetic state history, no fitted objects.
def _bounded_proxy_history():
    import numpy as np
    from scripts.research.a2.training.stateful_inputs import FEATURES
    dates=pd.bdate_range("2023-01-03","2026-01-28")
    n=len(dates);count=24;ix=np.tile(np.arange(count),n);sessions=np.repeat(np.arange(n),count)
    frame=pd.DataFrame({name:np.full(n*count,.01) for name in FEATURES})
    rank=(ix-sessions)%count+1;raw=rank<=20
    frame['signal_date']=np.repeat(dates,count);frame['ticker']=['S'+str(i) for i in ix]
    frame['security_id']=[str(100000000+i+(100 if session>=n-18 and i==3 else 0)) for session,i in zip(sessions,ix)]
    frame['feature_available']=True;frame['is_raw_top20']=raw;frame['new_buy_eligible']=raw;frame['raw_top20_set_complete']=True
    frame['raw_a2_rank']=np.where(raw,rank,np.nan);frame['raw_a2_prediction']=np.where(raw,.1-rank*.001,np.nan)
    # Sparse coverage and missing feature values must not change cohort transitions.
    frame.loc[(sessions%7==0)&(ix==5),'feature_available']=False
    frame.loc[(sessions%11==0)&(ix==2),FEATURES[0]]=np.nan
    frame=frame.loc[~((sessions%9==0)&(ix==7))].reset_index(drop=True)
    frame['mixed_note']=pd.Series([None if d.year<2025 else 'current' for d in frame.signal_date],dtype=object)
    frame['object_uint']=pd.Series([2**63+3 if d.year==2025 else 1 for d in frame.signal_date],dtype=object)
    frame['nullable_note']=pd.Series([pd.NA if i%13==0 else 1 for i in range(len(frame))],dtype='Int64')
    return frame,dates


def _bounded_proxy_owner(calendar):
    from scripts.research.a2.inference.frozen_a94_state import _clone
    from scripts.research.a2.training import stateful_mechanism_inputs as owner
    def dates(value,nullable=False):
        result=pd.to_datetime(value)
        if (not nullable and pd.isna(result).any()) or (len(result) and pd.DatetimeIndex(result).dropna().max()>calendar[-1]):raise ValueError('SYNTHETIC_DATE_GUARD')
        return result
    return _clone(owner.proxy_state,_pre2026=dates,_calendar=lambda value:pd.DatetimeIndex(dates(value)))


@pytest.mark.parametrize('scope',['day','main','empty'])
def test_bounded_proxy_multiyear_state_dtype_index_and_readonly_exact(scope):
    from scripts.research.a2.inference import consensus_paper as consumer
    frame,calendar=_bounded_proxy_history();before=frame.copy(deep=True);fn=_bounded_proxy_owner(calendar)
    first,last=(calendar[-1],calendar[-1]) if scope=='day' else (pd.Timestamp(paper.START),calendar[-1]) if scope=='main' else (calendar[-1]+pd.Timedelta(days=1),calendar[-1]+pd.Timedelta(days=2))
    old=fn(frame,calendar,10);new=consumer.scoped_proxy_frame(fn,frame,calendar,first,last)
    mask=lambda value:value.signal_date.between(first,last)
    pd.testing.assert_frame_equal(new.loc[mask(new)],old.loc[mask(old)],check_exact=True,check_dtype=True,check_index_type=True)
    assert new.empty or new.signal_date.between(first,last).all()
    pd.testing.assert_frame_equal(frame,before,check_exact=True,check_dtype=True)
    assert len(new)<len(old)/5 and old.cohort_age_sessions.max()==20
    # Historic unsigned/object and nullable witnesses survive without publishing extra targets.
    assert new.object_uint.dtype==old.object_uint.dtype and new.nullable_note.dtype==old.nullable_note.dtype


@pytest.mark.parametrize('failure',['future','duplicate','friction'])
def test_bounded_proxy_preserves_original_error_and_namespace(failure):
    from scripts.research.a2.inference import consensus_paper as consumer
    frame,calendar=input_fixture();fn=_bounded_proxy_owner(calendar);original=dict(fn.__globals__)
    if failure=='future':frame.loc[0,'signal_date']=pd.Timestamp('2027-01-01')
    if failure=='duplicate':frame=pd.concat([frame,frame.iloc[:1]],ignore_index=True)
    friction=99 if failure=='friction' else 10
    errors=[]
    for call in (lambda:fn(frame,calendar,friction),lambda:consumer.scoped_proxy_frame(fn,frame,calendar,calendar[-1],calendar[-1],friction)):
        with pytest.raises(ValueError) as error:call()
        errors.append(str(error.value))
    assert errors[0]==errors[1] and all(fn.__globals__[key] is value for key,value in original.items())


def test_bounded_proxy_unknown_scalar_falls_back_to_original_without_source_mutation():
    from scripts.research.a2.inference import consensus_paper as consumer
    frame,calendar=input_fixture();frame['unknown_scalar']=[('opaque',i) for i in range(len(frame))]
    fn=_bounded_proxy_owner(calendar);old=fn(frame,calendar,10)
    new=consumer.scoped_proxy_frame(fn,frame,calendar,calendar[-1],calendar[-1])
    pd.testing.assert_frame_equal(new,old,check_exact=True,check_dtype=True)


def test_bounded_proxy_original_current_and_main_roles_are_exact(monkeypatch):
    from scripts.research.a2.inference import consensus_paper as consumer
    # Existing role owner must produce identical full sample order/columns, including REPLACE SID.
    frame,calendar=input_fixture();scoped=consumer.scoped_proxy_frame
    monkeypatch.setattr(consumer,'scoped_proxy_frame',lambda fn,pred,cal,first,last,friction=10:fn(pred,cal,friction))
    old_current=consumer.original_frames(frame,calendar,calendar[-1]);old_main=paper.full_r10_roles(frame,calendar,calendar[-1])
    monkeypatch.setattr(consumer,'scoped_proxy_frame',scoped)
    new_current=consumer.original_frames(frame,calendar,calendar[-1]);new_main=paper.full_r10_roles(frame,calendar,calendar[-1])
    for role in ('ENTRY','INCUMBENT'):
        pd.testing.assert_frame_equal(new_current[role],old_current[role],check_exact=True,check_dtype=True)
        pd.testing.assert_frame_equal(new_main[role],old_main[role],check_exact=True,check_dtype=True)


@pytest.mark.parametrize('layout',['C','F','strided','readonly'])
@pytest.mark.parametrize('rows',[0,1,19])
def test_r10_boolean_mask_promotion_keeps_original_bits_dtype_strides_and_names(layout,rows):
    import numpy as np
    from scripts.research.a2.inference import consensus_paper as consumer
    from scripts.research.a2.training import stateful_mechanism as owner
    raw=np.arange(rows*40,dtype=float).reshape(rows,40)
    if rows:raw[0,0]=-0.;raw[-1,-1]=np.nan
    if layout=='F':raw=np.asfortranarray(raw)
    if layout=='strided':raw=raw[:,::-1]
    if layout=='readonly':raw.flags.writeable=False
    frame=pd.DataFrame(raw,columns=['x'+str(i) for i in range(40)]);before=frame.copy(deep=True)
    original,names=owner.encode(frame,frame.columns);candidate,new_names=consumer.r10_encoded_input(frame,frame.columns)
    assert names==new_names and original.dtype==candidate.dtype and original.shape==candidate.shape and original.strides==candidate.strides
    assert np.array_equal(original.view('u8'),candidate.view('u8'))
    pd.testing.assert_frame_equal(frame,before,check_exact=True,check_dtype=True)


def test_r10_boolean_mask_promotion_preserves_infinite_guard_and_original_globals():
    from scripts.research.a2.inference import consensus_paper as consumer
    from scripts.research.a2.training import stateful_mechanism as owner
    before=dict(owner.encode.__globals__);frame=pd.DataFrame({'x':[float('inf')]})
    for call in (owner.encode,consumer.r10_encoded_input):
        with pytest.raises(ValueError,match='INFINITE_FEATURE'):call(frame,['x'])
    assert all(owner.encode.__globals__[key] is value for key,value in before.items())


def test_bounded_proxy_private_row_storage_releases_before_return_without_gc(monkeypatch):
    import weakref
    from scripts.research.a2.inference import consensus_paper as consumer
    frame,calendar=input_fixture();fn=_bounded_proxy_owner(calendar);owner=consumer._ScopedProxyRows;refs=[]
    def rows(*args,**kwargs):
        result=owner(*args,**kwargs);refs.append(weakref.ref(result));return result
    monkeypatch.setattr(consumer,'_ScopedProxyRows',rows)
    result=consumer.scoped_proxy_frame(fn,frame,calendar,calendar[-1],calendar[-1])
    assert not result.empty and refs and all(ref() is None for ref in refs)


@pytest.fixture
def entitlement_format_case(monkeypatch):
    """Compile the original pure projection only; no research owner imports or model/data load."""
    import ast,hashlib,sys
    from types import ModuleType
    owner=Path("D:/us-tech-quant/scripts/research/a2/evaluation/stateful_frozen_six_path.py")
    assert hashlib.sha256(owner.read_bytes()).hexdigest()=="c315aadb1e67cbf74fadfcc5acd9233e6fbea2b77492b8db8f2f6f3b96d0564e"
    tree=ast.parse(owner.read_text(encoding="utf8"))
    nodes=[next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name==name)
           for name in ("_require","_dual_nav_frames")]
    namespace={"pd":pd}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),str(owner),"exec"),namespace)
    module=ModuleType("scripts.research.a2.evaluation.stateful_frozen_six_path")
    module._dual_nav_frames=namespace["_dual_nav_frames"]
    monkeypatch.setitem(sys.modules,module.__name__,module)
    def make(sid):
        day=pd.Timestamp("2025-10-08")
        ent=pd.DataFrame(dict(path_id=[sid,sid],session=[day,day],event_id=["first","second"],
            amount_usd=pd.Series([123456789.125,2.5],dtype="float64"),phase=["EX","PAY"]))
        raw=ent.copy();raw["scenario"]=pd.Series(["ORIGINAL_SYNTHETIC_LABEL","ORIGINAL_SYNTHETIC_LABEL"],dtype="string")
        result=SimpleNamespace(daily=pd.DataFrame([dict(path_id=sid,date=day,cash=10.,receivable_value_usd=2.,scenario="SYNTHETIC")]),
            positions=pd.DataFrame([dict(path_id=sid,date=day,market_value=3.)]),entitlements=ent,
            fills=pd.DataFrame(),orders=pd.DataFrame(),execution_results=pd.DataFrame())
        frames=dict(daily=result.daily.copy(),positions=result.positions.copy(),entitlements=raw,fills=result.fills.copy())
        return result,frames
    return make


@pytest.mark.parametrize("sid",paper.IDS)
def test_entitlement_format_restores_only_ridge_raw_label_and_never_mutates_inputs(entitlement_format_case,sid):
    result,frames=entitlement_format_case(sid)
    oldframes={name:frame.copy(deep=True) for name,frame in frames.items()};oldent=result.entitlements.copy(deep=True)
    out=paper._original_nav_output_frames(result,frames,(sid,))
    for name,frame in frames.items():pd.testing.assert_frame_equal(frame,oldframes[name],check_exact=True)
    pd.testing.assert_frame_equal(result.entitlements,oldent,check_exact=True)
    if sid==paper.IDS[1]:
        pd.testing.assert_frame_equal(out["entitlements"],frames["entitlements"],check_exact=True,check_dtype=True)
        assert out["entitlements"] is not frames["entitlements"]
        out["entitlements"].loc[0,"scenario"]="CHANGED_OUTPUT_ONLY"
        pd.testing.assert_frame_equal(frames["entitlements"],oldframes["entitlements"],check_exact=True)
    else:
        assert "scenario" not in out["entitlements"] and out["entitlements"] is result.entitlements
    assert out["daily"].LIQUID_NAV.tolist()==[13.]
    assert out["daily"].TOTAL_ECONOMIC_NAV.tolist()==[15.]


@pytest.mark.parametrize("mutation",["value","dtype","index","row_order","extra_column","missing_scenario","projected_scenario"])
def test_entitlement_format_rejects_any_payload_or_schema_change(entitlement_format_case,mutation):
    result,frames=entitlement_format_case(paper.IDS[1]);raw=frames["entitlements"]
    if mutation=="value":raw.loc[0,"amount_usd"]+=1e-7
    elif mutation=="dtype":raw["amount_usd"]=raw.amount_usd.astype("object")
    elif mutation=="index":raw.index=pd.Index([7,8],name="changed")
    elif mutation=="row_order":frames["entitlements"]=raw.iloc[::-1].copy()
    elif mutation=="extra_column":raw["unexpected"]=0
    elif mutation=="missing_scenario":raw.drop(columns=["scenario"],inplace=True)
    else:result.entitlements["scenario"]="FORBIDDEN_PROJECTED_LABEL"
    with pytest.raises((AssertionError,ValueError)):
        paper._original_nav_output_frames(result,frames,(paper.IDS[1],))


def test_entitlement_format_execute_prepared_uses_original_projection_seam(entitlement_format_case,monkeypatch):
    import sys
    from types import ModuleType
    result,frames=entitlement_format_case(paper.IDS[1]);ids=(paper.IDS[1],)
    candidates=[{"id":"SYNTHETIC"}];account={};friction={}
    value=SimpleNamespace(candidate_json=paper.canonical(candidates),account_json=paper.canonical(account),
        friction_json=paper.canonical(friction),allowed_path_ids=ids)
    prepared=dict(candidates=candidates,account=account,execution_friction=friction,market=SimpleNamespace(dates=[]),
        account_source_kwargs=dict(entitlement_enabled=True,entitlement_source_binding={}),
        packets={},top={},qualified={},vol={},stock_present={},raw_selector_present={},sid_by_key={})
    packets=ModuleType("scripts.research.a2.training.stateful_final_action_packets")
    packets.decode_resource_proposals=lambda *args,**kwargs:None
    monkeypatch.setitem(sys.modules,packets.__name__,packets)
    monkeypatch.setattr(paper,"_authority",lambda supplied:value)
    monkeypatch.setattr(paper,"validate_descriptive_account",lambda *args:None)
    calls=[]
    def execute(*args,**kwargs):calls.append(kwargs);return result,frames
    monkeypatch.setattr(paper,"replay_projection",lambda:({"execute_market":execute},["ORIGINAL_GUARDS"]))
    returned,out,receipts=paper.execute_prepared(prepared,object(),action_packets={ids[0]:{}})
    assert returned is result and receipts==["ORIGINAL_GUARDS"] and len(calls)==1
    pd.testing.assert_frame_equal(out["entitlements"],frames["entitlements"],check_exact=True)


def test_prefix_failure_diagnostic_has_only_schema_not_cell_values(tmp_path,capsys):
    _,frames,refs,_=fixtures(tmp_path)
    frames["entitlements"].loc[0,"amount_usd"]=76543210.987654
    with pytest.raises(ValueError,match="PAPER_EXTENSION_ACCEPTED_PREFIX_CHANGED:entitlements"):
        paper.compare_prefix(frames,refs,SID)
    encoded=capsys.readouterr().out.strip();value=json.loads(encoded)
    assert value["event"]=="PAPER_EXTENSION_ACCEPTED_PREFIX_CHANGED" and value["table"]=="entitlements"
    assert value["different_columns"]==["amount_usd"] and value["cell_values_included"] is False
    assert value["actual"]["shape"]==[1,len(frames["entitlements"].columns)]
    assert "76543210.987654" not in encoded and "DataFrame.iloc" not in encoded
    assert len(encoded.encode("utf8"))+2<=16384


def test_prefix_failure_diagnostic_unicode_schema_is_bounded_and_nonmutating():
    columns=[f"{i:03d}"+"😀"*100 for i in range(96)]
    actual=pd.DataFrame([[987654321.125]*len(columns)],columns=columns)
    expected=actual.copy();expected.iloc[0,:]=123456789.125
    old=actual.copy()
    encoded=paper._prefix_failure_diagnostic(actual,expected,candidate_id="😀"*300,table="😀"*300)
    value=json.loads(encoded)
    assert len(encoded.encode("utf8"))+2<=16384 and value["schema_details_truncated"] is True
    assert len(value["different_columns"])<=16 and all(len(item["name"])<=64 for item in value["actual"]["columns"])
    assert "987654321.125" not in encoded and "123456789.125" not in encoded
    pd.testing.assert_frame_equal(actual,old,check_exact=True)


def test_prefix_failure_diagnostic_failure_preserves_original_strict_error(tmp_path,monkeypatch,capsys):
    _,frames,refs,_=fixtures(tmp_path);frames["entitlements"].loc[0,"amount_usd"]+=1e-12
    def fail(*args,**kwargs):raise RuntimeError("DIAGNOSTIC_FAILURE_SECRET_987654321")
    monkeypatch.setattr(paper,"_prefix_failure_diagnostic",fail)
    with pytest.raises(ValueError,match="PAPER_EXTENSION_ACCEPTED_PREFIX_CHANGED:entitlements") as error:
        paper.compare_prefix(frames,refs,SID)
    assert isinstance(error.value.__cause__,AssertionError) and capsys.readouterr().out==""


@pytest.fixture
def r7_action_format_case():
    import numpy as np
    sid=paper.IDS[2];dates=pd.DatetimeIndex(["2025-10-07","2025-10-08"])
    sample=pd.DataFrame([(date,g) for date in dates for g in (0.,.25,.5,.75,1.)],columns=["signal_date","gross_previous_proxy"])
    action=np.asarray([0,1,2,3,3,0,1,2,1,4],dtype=np.int64)
    probability=np.eye(5,dtype=np.float64)[action];output=dict(action=action,probabilities=probability,gross=action/4.)
    trace=paper._r7_native_prediction_trace(sample,output,{"path":"SYNTHETIC_ONLY","sha256":"f"*64})
    frames=dict(
        daily=pd.DataFrame(dict(path_id=[sid]*2,date=dates,cash=[10.,20.])),
        positions=pd.DataFrame(dict(path_id=[sid],date=[dates[0]],ticker=["SYNTHETIC"],index_units=[1.])),
        fills=pd.DataFrame(dict(path_id=[sid],execution_date=[dates[1]],ticker=["SYNTHETIC"],side=["BUY"],index_units=[1.])),
        entitlements=pd.DataFrame(dict(path_id=[sid],session=[dates[1]],event_id=["SYNTHETIC"],phase=["EX"],amount_usd=[0.])),
        actions=pd.DataFrame(dict(path_id=[sid]*3,signal_date=[dates[0],dates[0],dates[1]],ticker=["AAA","BBB","AAA"],
            planned_execution_date=[dates[1],dates[1],pd.NaT],target_weight=[.5,.25,.25],scenario=["ORIGINAL_SYNTHETIC"]*3)),
        orders=pd.DataFrame(dict(path_id=[sid],signal_date=[dates[0]],ticker=["AAA"],order_id=["SYNTHETIC"],execution_date=[dates[1]],status=["submitted"])),
        gross=pd.DataFrame(dict(candidate_id=[sid]*2,signal_date=[str(x.date()) for x in dates],
            previous_requested_grid=[1.,.75],requested_grid=[.75,.25],input_supported=[True,True],status=["SYNTHETIC"]*2)))
    return dict(sid=sid,dates=dates,sample=sample,output=output,trace={sid:dict(frame=trace,model_ref={"path":"SYNTHETIC_ONLY","sha256":"f"*64})},model_refs={sid:{"path":"SYNTHETIC_ONLY","sha256":"f"*64}},frames=frames)


def test_r7_action_format_complete_six_tables_and_input_isolation(r7_action_format_case):
    import numpy as np
    c=r7_action_format_case;original={name:frame.copy(deep=True) for name,frame in c["frames"].items()};trace=c["trace"][c["sid"]]["frame"].copy(deep=True)
    out,receipt=paper._r7_original_action_frames(c["frames"],c["trace"],(c["sid"],),c["model_refs"])
    for name,(_,keys) in paper.LEDGER_TABLES.items():
        assert set(keys)<=set(out[name])
        if name!="actions":pd.testing.assert_frame_equal(out[name],original[name],check_exact=True)
    assert set(out["actions"])-set(original["actions"])=={"gross_previous_proxy","requested_grid","r7_model_action"}
    pd.testing.assert_frame_equal(out["actions"].drop(columns=["gross_previous_proxy","requested_grid","r7_model_action"]),original["actions"],check_exact=True)
    assert out["actions"].gross_previous_proxy.tolist()==[1.,1.,.75]
    assert out["actions"].requested_grid.tolist()==[.75,.75,.25] and out["actions"].r7_model_action.tolist()==[3,3,1]
    assert out["actions"].r7_model_action.dtype==np.dtype("int64")
    assert out["actions"].gross_previous_proxy.dtype==out["actions"].requested_grid.dtype==np.dtype("float64")
    for name,frame in original.items():pd.testing.assert_frame_equal(c["frames"][name],frame,check_exact=True)
    pd.testing.assert_frame_equal(c["trace"][c["sid"]]["frame"],trace,check_exact=True)
    assert receipt["model_prediction_calls_added"]==0 and receipt["account_math_changed"] is False


@pytest.mark.parametrize("mutation",["duplicate","missing_state","missing_date","missing_trace","missing_action","model_ref_path","model_ref_sha","expected_model_ref","decoder","gross","probability","action_dtype","audit_request","duplicate_audit","missing_action_date"])
def test_r7_action_format_missing_duplicate_or_inconsistent_data_refused(r7_action_format_case,mutation):
    import numpy as np
    c=r7_action_format_case;trace=c["trace"][c["sid"]]["frame"]
    if mutation=="duplicate":c["trace"][c["sid"]]["frame"]=pd.concat([trace,trace.iloc[:1]],ignore_index=True)
    elif mutation=="missing_state":c["trace"][c["sid"]]["frame"]=trace.iloc[1:].copy()
    elif mutation=="missing_date":c["trace"][c["sid"]]["frame"]=trace.loc[trace.signal_date.eq(c["dates"][0])].copy()
    elif mutation=="missing_trace":c["trace"]={}
    elif mutation=="missing_action":c["trace"][c["sid"]]["frame"]=trace.drop(columns=["action"])
    elif mutation=="model_ref_path":c["trace"][c["sid"]]["model_ref"]["path"]="CHANGED"
    elif mutation=="model_ref_sha":trace["model_sha256"]="a"*64
    elif mutation=="expected_model_ref":c["model_refs"][c["sid"]]["sha256"]="a"*64
    elif mutation=="decoder":trace.loc[0,"decoder"]="CHANGED"
    elif mutation=="gross":trace.loc[0,"requested_gross"]+=.25
    elif mutation=="probability":trace.loc[0,"probability_4"]=2.
    elif mutation=="action_dtype":trace["action"]=trace.action.astype("float64")
    elif mutation=="audit_request":c["frames"]["gross"].loc[0,"requested_grid"]=.5
    elif mutation=="duplicate_audit":c["frames"]["gross"]=pd.concat([c["frames"]["gross"]]*2,ignore_index=True)
    else:c["frames"]["actions"].loc[0,"signal_date"]=pd.Timestamp("2025-10-09")
    with pytest.raises((ValueError,pd.errors.MergeError)):
        paper._r7_original_action_frames(c["frames"],c["trace"],(c["sid"],),c["model_refs"])


@pytest.mark.parametrize("sid",paper.IDS[:2])
def test_r7_action_format_never_applies_to_other_candidates(r7_action_format_case,sid):
    c=r7_action_format_case;before={name:frame.copy(deep=True) for name,frame in c["frames"].items()}
    with pytest.raises(ValueError,match="SINGLE_NATIVE_ACTION_TRACE"):
        paper._r7_original_action_frames(c["frames"],c["trace"],(sid,),c["model_refs"])
    for name,frame in before.items():pd.testing.assert_frame_equal(c["frames"][name],frame,check_exact=True)


def test_r7_action_format_original_pure_blocks_are_AST_exact():
    import ast,inspect
    native=paper.verified(paper._R7_NATIVE_TRACE_OWNER);formatted=paper.verified(paper._R7_ACTION_FORMAT_OWNER)
    source=native.read_text(encoding="utf8");tree=ast.parse(source)
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="native_grid")
    loop=next(n for n in function.body if isinstance(n,ast.For) and any(isinstance(x,ast.Name) and x.id=="predicted_frames" for x in ast.walk(n)))
    start=next(i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="table" for t in n.targets));original=loop.body[start:-1]
    copied=ast.parse(inspect.getsource(paper._r7_native_prediction_trace)).body[0]
    start=next(i for i,n in enumerate(copied.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="table" for t in n.targets))
    assert ast.dump(ast.Module(body=original,type_ignores=[]))==ast.dump(ast.Module(body=copied.body[start:-1],type_ignores=[]))
    function=next(n for n in ast.parse(formatted.read_text(encoding="utf8")).body if isinstance(n,ast.FunctionDef) and n.name=="persist_r7_window")
    start=next(i for i,n in enumerate(function.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="audit" for t in n.targets));end=next(i for i,n in enumerate(function.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="arts" for t in n.targets))
    copied=ast.parse(inspect.getsource(paper._r7_original_action_frames)).body[0]
    nested=next(n for n in copied.body if isinstance(n,ast.FunctionDef) and n.name=="project")
    assert ast.dump(ast.Module(body=function.body[start:end],type_ignores=[]))==ast.dump(ast.Module(body=nested.body[:-1],type_ignores=[]))


def test_r7_action_format_one_native_prediction_through_original_audit_join_and_six_prefixes(tmp_path,entitlement_format_case,monkeypatch):
    """One fake native prediction, original R7 overlay/audit, original format joins and six prefix guards."""
    import numpy as np,joblib
    from scripts.research.a2.inference import consensus_paper as consumer,frozen_a94_state as frozen
    from scripts.research.a2.training import stateful_decision as decision,stateful_decision_models as models
    _,original,_,_=fixtures(tmp_path);sid=paper.IDS[2]
    frames={name:frame.copy(deep=True) for name,frame in original.items()}
    for frame in frames.values():frame["path_id"]=sid
    second=frames["actions"].copy();second["ticker"]="SYNTHETIC_SECOND"
    frames["actions"]=pd.concat([frames["actions"],second],ignore_index=True)
    frames["actions"]["target_weight"]=.375;frames["orders"]["target_weight"]=.375
    result=SimpleNamespace(**{name:frames[name] for name in ("daily","positions","fills","orders","entitlements")},execution_results=pd.DataFrame())
    expected=paper._original_nav_output_frames(result,frames,(sid,))
    refs={}
    for name,(clock,_) in paper.LEDGER_TABLES.items():
        baseline=expected[name].loc[pd.to_datetime(expected[name][clock]).le(pd.Timestamp(paper.PREFIX_END))].copy()
        if name=="actions":
            baseline["planned_execution_date"]=pd.Series(pd.NaT,index=baseline.index,dtype=baseline["planned_execution_date"].dtype);baseline["gross_previous_proxy"]=.75;baseline["requested_grid"]=.75;baseline["r7_model_action"]=np.int64(3)
        if name=="orders":baseline["execution_date"]=pd.Series(pd.NaT,index=baseline.index,dtype=baseline["execution_date"].dtype);baseline["status"]="no_next_session"
        path=tmp_path/("native-chain-baseline-"+name+".parquet");baseline.to_parquet(path,index=False);refs[name]=paper.reference(path)
    dates=pd.DatetimeIndex(frames["daily"].date)
    sample=pd.DataFrame([(date,g) for date in dates for g in (0.,.25,.5,.75,1.)],columns=["signal_date","gross_previous_proxy"])
    actions=np.full(len(sample),3,dtype=np.int64);output=dict(action=actions,gross=actions/4.,probabilities=np.eye(5)[actions])
    specs=[dict(candidate_id=sid,action="raw",gross="fixed",control="none")]
    value=paper.PaperAuthority(dates[0],dates[-1],pd.Timestamp("2026-10-13T01:00:00Z"),(sid,),paper.canonical(specs),"{}","{}","{}",None,seal=paper._SEAL)
    class Model:objective="gross";learner="linear";features=("ONE",)
    monkeypatch.setattr(paper,"check_resources",lambda *args,**kwargs:None)
    monkeypatch.setattr(frozen,"_clone",lambda *args,**kwargs:lambda *_a,**_k:({"gross":sample.copy()},{}))
    monkeypatch.setattr(decision,"encode_features",lambda frame,group:(np.zeros((len(frame),1)),["ONE"]))
    monkeypatch.setattr(consumer,"frozen_states",lambda *args:{"state":{"model_ref":{"path":"SYNTHETIC_ONLY","sha256":"f"*64}}})
    monkeypatch.setattr(consumer,"verify",lambda _:Path("SYNTHETIC_ONLY"));monkeypatch.setattr(joblib,"load",lambda _:Model())
    calls=[]
    def predict(model,x):calls.append(x.shape);return {name:value.copy() for name,value in output.items()}
    monkeypatch.setattr(models,"predict",predict)
    grid,model_refs,trace=paper.forward_r7(SimpleNamespace(),pd.DataFrame(dict(signal_date=dates)),dates,value,include_native_trace=True)
    assert len(calls)==1 and len(trace[sid]["frame"])==len(dates)*5
    class Reference:
        def __init__(self,*args,**kwargs):pass
        def __call__(self,*args,**kwargs):return SimpleNamespace(weights=np.full((1,2),.5),explicit_mask=np.ones((1,2),dtype=bool))
    audits=[]
    def account_kernel(market,candidates,packets,top,qualified,vol,account,**kwargs):
        overlay=kwargs["policy_factory"](candidates,packets,top,qualified,vol,descriptive_evaluation_authority=value)
        for i,date in enumerate(dates):
            context=SimpleNamespace(signal_date=date,path_ids=(sid,),reserved_mask=np.zeros((1,2),dtype=bool),decision_mask=np.ones((1,2),dtype=bool),
                sell_restricted=np.zeros((1,2),dtype=bool),current_units=np.zeros((1,2)))
            target=overlay(i,context);assert np.array_equal(target.weights,np.full((1,2),.375))
        audits.extend(overlay.audit)
        return result,{**frames,"gross":pd.DataFrame(overlay.audit)}
    monkeypatch.setattr(paper,"replay_projection",lambda:({"execute_market":account_kernel,"StatefulOverlay":Reference},[]))
    prepared=dict(candidates=specs,account={},execution_friction={},market=SimpleNamespace(dates=dates),packets={},top={},qualified={},vol={},stock_present={},raw_selector_present={},sid_by_key={},account_source_kwargs=dict(entitlement_enabled=True,entitlement_source_binding={}))
    _,out,receipts=paper.execute_prepared(prepared,value,gross_calendar=grid,native_trace=trace,native_model_refs=model_refs)
    assert len(calls)==1 and len(audits)==len(dates) and audits[0]["previous_requested_grid"]==1.
    assert all(row["previous_requested_grid"]==.75 for row in audits[1:])
    assert out["actions"].r7_model_action.tolist()==[3,3] and out["actions"].gross_previous_proxy.tolist()==[.75,.75]
    assert out["actions"].r7_model_action.dtype==np.dtype("int64") and receipts[-1]["model_refs"]==model_refs
    for name in paper.LEDGER_TABLES:
        if name!="actions":pd.testing.assert_frame_equal(out[name],expected[name],check_exact=True)
    assert paper.compare_prefix(out,refs,sid)["status"]=="EXACT_MATCH"
    assert paper.compare_stock_prefix(out,refs,sid)["status"]=="EXACT_CLOSED_PREFIX_WITH_PENDING_MATURITY"
    assert all("requested_grid" not in out[name] for name in paper.LEDGER_TABLES if name!="actions")
    out["actions"].loc[0,"planned_execution_date"]=pd.Timestamp(paper.MAX_END)
    with pytest.raises(ValueError,match="PENDING_OPEN_CLOCK_CHANGED"):
        paper.compare_stock_prefix(out,refs,sid)
    assert len(calls)==1


@pytest.mark.parametrize("field",["gross_previous_proxy","requested_grid","r7_model_action"])
def test_r7_action_format_all_six_prefixes_stay_strict(tmp_path,field,capsys):
    import numpy as np
    _,frames,refs,_=fixtures(tmp_path);sid=paper.IDS[2]
    for frame in frames.values():frame["path_id"]=sid
    frames["actions"]["gross_previous_proxy"]=1.;frames["actions"]["requested_grid"]=.75;frames["actions"]["r7_model_action"]=np.int64(3)
    for name,ref in list(refs.items()):
        baseline=pd.read_parquet(ref["path"]);baseline["path_id"]=sid
        if name=="actions":
            baseline["gross_previous_proxy"]=1.;baseline["requested_grid"]=.75;baseline["r7_model_action"]=np.int64(3)
        path=tmp_path/("r7-baseline-"+name+".parquet");baseline.to_parquet(path,index=False);refs[name]=paper.reference(path)
    assert paper.compare_prefix(frames,refs,sid)["status"]=="EXACT_MATCH"
    assert paper.compare_stock_prefix(frames,refs,sid)["status"]=="EXACT_CLOSED_PREFIX_WITH_PENDING_MATURITY"
    frames["actions"].loc[0,field]+=1 if field=="r7_model_action" else 1e-12
    with pytest.raises(ValueError,match="STOCK_ACCEPTED_PREFIX_CHANGED:actions"):
        paper.compare_stock_prefix(frames,refs,sid)
    encoded=capsys.readouterr().out.strip();assert json.loads(encoded)["event"]=="PAPER_EXTENSION_STOCK_ACCEPTED_PREFIX_CHANGED"
    assert len(encoded.encode("utf8"))+2<=16384


@pytest.mark.parametrize("table",["actions","orders"])
def test_r7_action_format_stock_schema_diagnostic_keeps_original_rejection(tmp_path,table,capsys):
    _,frames,refs,_=fixtures(tmp_path);frames[table]["EXTRA_SCHEMA"]=987654321.125
    with pytest.raises(ValueError,match="STOCK_PREFIX_SCHEMA_CHANGED:"+table):paper.compare_stock_prefix(frames,refs,SID)
    encoded=capsys.readouterr().out.strip();payload=json.loads(encoded)
    assert payload["event"]=="PAPER_EXTENSION_STOCK_PREFIX_SCHEMA_CHANGED" and payload["table"]==table
    assert payload["actual_only_columns"]==["EXTRA_SCHEMA"] and "987654321.125" not in encoded
    assert len(encoded.encode("utf8"))+2<=16384
