import hashlib
import json
from pathlib import Path
import pandas as pd
import pytest
from apps.demo_console.adapters import new_strategy_replay_reader as reader


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source(tmp_path):
    sid="R7_GROSS_LINEAR"
    rows=[]
    for day,nav,ret in [("2026-01-02",100000,None),("2026-01-05",101000,.01),("2026-01-06",float("nan"),.01)]:
        rows.append(dict(path_id=sid,date=day,nav=nav,net_return=ret,research_cash_weight=.2,transaction_cost_amount=0.,turnover=0.,actual_name_count=20,stale_count=0,unknown_count=0,accounting_qualified=True))
    rows.append(dict(rows[-1],path_id="OTHER_FORBIDDEN_PATH"))
    p=tmp_path/"daily.parquet";pd.DataFrame(rows).to_parquet(p,index=False)
    receipt=tmp_path/"receipt.json";receipt.write_text(json.dumps({"candidate_ids":[sid]}))
    return sid,dict(path=str(p),sha256=digest(p),receipt=str(receipt),receipt_sha256=digest(receipt),research_id="synthetic")


def test_other_paths_and_future_rows_are_not_decoded(tmp_path):
    sid,s=source(tmp_path)
    result=reader.load_views("2026-01-05",sources={sid:s})[sid]
    assert result["history"]["status"]=="AVAILABLE"
    assert [r["date"] for r in result["history"]["daily"]]==["2026-01-02","2026-01-05"]
    assert result["history"]["daily"][-1]["nav"]==1.01
    assert result["history"]["start"]=="2026-01-05"


def test_same_cache_identity_revalidates_changed_frozen_bytes(tmp_path):
    sid,s=source(tmp_path)
    assert reader.load_views("2026-01-05",sources={sid:s})[sid]["history"]["status"]=="AVAILABLE"
    Path(s["receipt"]).write_text('{"candidate_ids":[]}')
    assert reader.load_views("2026-01-05",sources={sid:s})[sid]["history"]["status"]=="UNAVAILABLE"


def test_invalid_record_is_explicitly_unavailable_not_dropped(tmp_path):
    sid,s=source(tmp_path)
    history=reader.load_views("2026-01-06",sources={sid:s})[sid]["history"]
    assert history["status"]=="UNAVAILABLE" and history["daily"]==[]
    assert "NAV_OR_CASH" in history["reason"]


def test_no_test_records_exposed_by_historical_view_or_other_year(tmp_path):
    sid,s=source(tmp_path)
    assert reader.load_views("2026-01-05",sample="historical",sources={sid:s})=={}
    assert reader.load_views("2027-01-01",sources={sid:s})=={}


@pytest.fixture
def extension_package(tmp_path, monkeypatch):
    """All artifacts are tiny synthetic files; no canonical pointer is opened."""
    from apps.demo_console.adapters import new_strategy_stock_history_reader as stocks
    import pyarrow as pa
    import pyarrow.parquet as pq
    def pin(path):
        return {"path": str(path), "sha256": digest(path)}
    base, receipts = {}, {}
    calendar_file = tmp_path / "synthetic_calendar.json"
    calendar_file.write_text('{"calendar_id":"synthetic_sessions","target":"2026-10-12"}')
    calendar = {"helper":"scripts.daily_recommendation_inputs.latest_completed_session",
        "calendar_ref":pin(calendar_file), "target_session":"2026-10-12", "target_session_completed":True,
        "session_close_utc":"2026-10-12T20:00:00+00:00"}
    stock_status = "EXACT_CLOSED_PREFIX_WITH_PENDING_MATURITY"
    common = {"status": "PREFIX_VERIFIED_DESCRIPTIVE_EXTENSION", "window_id": "MAIN",
        "start": "2026-01-02", "first_execution_date": "2026-01-05", "prefix_end": "2026-10-08",
        "end": "2026-10-12", "as_of": "2026-10-12T20:30:00+00:00", "model_fit_calls": 0,
        "selection_using_2026": False, "broker_action_allowed": False, "calendar_qualification":calendar}
    for sid in reader.SOURCES:
        folder = tmp_path / sid;folder.mkdir()
        baseline, artifacts = {}, {}
        records = []
        previous = None
        for day, nav in [("2026-01-02", 100000.), ("2026-01-05", 101000.), ("2026-10-08", 101000.),
                         ("2026-10-09", 102010.), ("2026-10-12", 103030.1)]:
            records.append(dict(path_id=sid, date=day, nav=nav, net_return=None if previous is None else nav/previous-1,
                research_cash_weight=.8, transaction_cost_amount=0., turnover=0., actual_name_count=1,
                stale_count=0, unknown_count=0, accounting_qualified=True))
            previous=nav
        pd.DataFrame(records[:3]).to_parquet(folder / "old_daily.parquet", index=False)
        pd.DataFrame(records).to_parquet(folder / "daily.parquet", index=False)
        baseline["daily"], artifacts["daily"] = pin(folder / "old_daily.parquet"), pin(folder / "daily.parquet")
        stock_rows = {
            "actions": dict(path_id=sid, ticker="ALPHA", signal_date="2026-10-09", policy_explicit=True,
                policy_weight=.2, policy_action="HOLD", actual_weight=.2, planned_execution_date="2026-10-12"),
            "orders": dict(path_id=sid, ticker="ALPHA", signal_date="2026-10-09", execution_date="2026-10-12",
                target_weight=.2, adapted_target_weight=.2, hold_units=2., decision_semantic="MODEL_TARGET_WEIGHT", status="submitted"),
            "positions": dict(path_id=sid, ticker="ALPHA", date="2026-10-12", weight=.2, fractional_shares=2.,
                mark_date="2026-10-12", stale=False, unknown=False, accounting_qualified=True),
            "fills": dict(path_id=sid, ticker="ALPHA", execution_date="2026-10-12", signal_date="2026-10-09",
                side="BUY", actual_fill_price=101., fractional_shares=2., actual_fill_notional=202., transaction_fee=.2)}
        for name, row in stock_rows.items():
            old = {key: "2026-10-08" if key.endswith("date") else value for key, value in row.items()}
            pq.write_table(pa.Table.from_pylist([old]), folder / ("old_"+name+".parquet"))
            pq.write_table(pa.Table.from_pylist([old,row]), folder / (name+".parquet"))
            baseline[name], artifacts[name] = pin(folder / ("old_"+name+".parquet")), pin(folder / (name+".parquet"))
        for prefix in ("old_", ""):
            (folder / (prefix+"entitlements.parquet")).write_bytes(b"synthetic empty entitlements")
        baseline["entitlements"], artifacts["entitlements"] = pin(folder/"old_entitlements.parquet"), pin(folder/"entitlements.parquet")
        old_receipt = folder / "old_receipt.json";old_receipt.write_text(json.dumps({"candidate_ids":[sid]}))
        base[sid] = dict(path=baseline["daily"]["path"], sha256=baseline["daily"]["sha256"],
            receipt=str(old_receipt), receipt_sha256=digest(old_receipt), research_id="synthetic")
        meta = {**common, "schema": reader._EXTENSION_SCHEMA, "candidate_id": sid, "candidate_ids": [sid],
            "artifacts": artifacts, "baseline_artifacts": baseline, "production_qualified": False,
            "independent_holdout_claim": False, "original_prefix_comparison": {"status": "EXACT_MATCH",
                "account_prefix_identity": {"sha256": "12"*32}, "table_comparisons": {
                    name: {"status":"EXACT_MATCH", "original_ref":baseline[name]} for name in reader._TABLES[:4]}},
            "stock_prefix_comparison": {"status":stock_status, "table_comparisons": {
                name: {"status":stock_status, "original_ref":baseline[name], "pending_maturity": {
                    "signal_date":"2026-10-08", "next_execution_date":"2026-10-09", "changed_rows":0,
                    "allowed_columns":["planned_execution_date"] if name == "actions" else ["execution_date","status"],
                    "old_fields_sha256":"12"*32, "new_fields_sha256":"12"*32}}
                for name in ("actions","orders")}}}
        receipt = folder / "EXTENSION_COMPLETION.json";receipt.write_text(json.dumps(meta))
        receipts[sid] = pin(receipt)
    manifest = tmp_path / "MANIFEST.json"
    manifest.write_text(json.dumps({**common,"schema":reader._MANIFEST_SCHEMA,
        "candidate_ids": list(reader.SOURCES), "extensions":receipts}))
    pointer = tmp_path / "latest.json";pointer.write_text(json.dumps(pin(manifest)))
    validate = reader.qualified_manifest
    monkeypatch.setattr(stocks, "qualified_manifest", lambda ref: validate(ref, baseline_sources=base))
    monkeypatch.setattr(reader, "qualified_sources", lambda: original_select(pointer, baseline_sources=base))
    reader._cached.cache_clear();stocks._cached.cache_clear()
    yield {"pointer":pointer,"manifest":manifest,"base":base,"receipts":receipts,
        "select":lambda:original_select(pointer,baseline_sources=base),"pin":pin}
    reader._cached.cache_clear();stocks._cached.cache_clear()


original_select = reader.qualified_sources


def test_missing_extension_pointer_preserves_accepted_oct8_sources(tmp_path):
    result = original_select(tmp_path / "not_published.json")
    assert result["status"] == "FALLBACK_ACCEPTED_PREFIX" and result["end"] == "2026-10-08"
    assert result["replay_sources"] == reader.SOURCES


def test_one_qualified_pointer_updates_three_daily_and_native_stock_views(extension_package):
    from apps.demo_console.adapters import new_strategy_stock_history_reader as stocks
    publication = extension_package["select"]()
    assert publication["status"] == "QUALIFIED_EXTENSION"
    views = reader.load_views("2026-10-12")
    assert set(views) == set(reader.SOURCES)
    assert all(view["history"]["end"] == "2026-10-12" for view in views.values())
    assert all(view["history"]["publication_ref"] == publication["publication_ref"] for view in views.values())
    assert all(view["history"]["end"] == "2026-10-08" for view in reader.load_views("2026-10-12",history_cutoff="2026-10-08").values())
    native = stocks.query("ALPHA","2026-10-09","2026-10-13",sources=stocks.source_refs(bundle=publication))
    assert set(native["strategies"]) == set(reader.SOURCES)
    assert all(leaf["status"] == "READY" for leaf in native["strategies"].values())
    assert all(set(leaf["daily"]) == {"2026-10-09","2026-10-12"} for leaf in native["strategies"].values())
    assert all(leaf["daily"]["2026-10-12"]["research_weight"] == .2 for leaf in native["strategies"].values())
    assert reader._cached.cache_info().maxsize == stocks._cached.cache_info().maxsize == 1


def test_one_changed_extension_artifact_falls_back_as_a_whole(extension_package):
    publication = extension_package["select"]()
    sid = next(iter(reader.SOURCES))
    Path(publication["stock_sources"][sid]["positions"]["path"]).write_bytes(b"changed")
    result = extension_package["select"]()
    assert result["status"] == "FALLBACK_ACCEPTED_PREFIX" and result["end"] == "2026-10-08"
    assert result["replay_sources"] == extension_package["base"]
    assert all(view["history"]["end"] == "2026-10-08" for view in reader.load_views("2026-10-12").values())


@pytest.mark.parametrize("field,value", [("candidate_ids",["R7_GROSS_LINEAR"]),("end","2026-10-13"),
    ("model_fit_calls",1),("as_of","2026-10-12T19:59:00+00:00"),("broker_action_allowed",True)])
def test_unqualified_or_future_manifest_never_advances_end(extension_package,field,value):
    path=extension_package["manifest"];payload=json.loads(path.read_text());payload[field]=value
    path.write_text(json.dumps(payload));extension_package["pointer"].write_text(json.dumps(extension_package["pin"](path)))
    result=extension_package["select"]()
    assert result["status"] == "FALLBACK_ACCEPTED_PREFIX" and result["end"] == "2026-10-08"


def test_historical_native_cutoff_uses_original_pending_fields(extension_package):
    from apps.demo_console.adapters import new_strategy_stock_history_reader as stocks
    publication = extension_package["select"]()
    assert publication["status"] == "QUALIFIED_EXTENSION"
    selected = stocks.source_refs(bundle=publication)
    result = stocks.query("ALPHA", "2026-10-08", "2026-10-08", sources=selected)
    assert all(leaf["status"] == "READY" and set(leaf["daily"]) == {"2026-10-08"}
               for leaf in result["strategies"].values())
    assert all(leaf["daily"]["2026-10-08"]["planned_execution_date"] == "2026-10-08"
               for leaf in result["strategies"].values())
    assert all(leaf["source_refs"]["actions"] == selected[sid]["baseline_refs"]["actions"]
               for sid, leaf in result["strategies"].items())


def test_missing_pending_maturity_proof_never_publishes_new_end(extension_package):
    sid = next(iter(reader.SOURCES));receipt = Path(extension_package["receipts"][sid]["path"])
    meta = json.loads(receipt.read_text())
    meta["stock_prefix_comparison"]["table_comparisons"]["orders"].pop("pending_maturity")
    receipt.write_text(json.dumps(meta))
    manifest=extension_package["manifest"];data=json.loads(manifest.read_text())
    data["extensions"][sid]=extension_package["pin"](receipt);manifest.write_text(json.dumps(data))
    extension_package["pointer"].write_text(json.dumps(extension_package["pin"](manifest)))
    result=extension_package["select"]()
    assert result["status"] == "FALLBACK_ACCEPTED_PREFIX" and "PENDING_MATURITY" in result["reason"]


def test_missing_completed_calendar_proof_keeps_old_graph_end(extension_package):
    path=extension_package["manifest"];payload=json.loads(path.read_text());payload.pop("calendar_qualification")
    path.write_text(json.dumps(payload));extension_package["pointer"].write_text(json.dumps(extension_package["pin"](path)))
    result=extension_package["select"]()
    assert result["status"] == "FALLBACK_ACCEPTED_PREFIX" and "CALENDAR_PROOF" in result["reason"]


@pytest.mark.parametrize('broken', ['none', 'missing-one', 'different-one', 'rejected-prefix'])
def test_finite_publication_reader_requires_one_admission_and_verified_accepted_prefix(extension_package, monkeypatch, broken):
    import sys
    from types import ModuleType, SimpleNamespace
    from unittest.mock import Mock
    from scripts.common import storage_paths
    from apps.demo_console.adapters import new_strategy_stock_history_reader as stocks
    package = extension_package
    admission = {'path': 'synthetic-finite-admission.json', 'sha256': 'a' * 64}
    manifest = json.loads(package['manifest'].read_text())
    for index, (sid, receipt_ref) in enumerate(package['receipts'].items()):
        path = Path(receipt_ref['path']); receipt = json.loads(path.read_text())
        receipt['source_refs'] = {'finite_ca_admission_ref': dict(admission),
            'accepted_extension_prefix_comparison_ref': {'path': 'synthetic-prefix-' + sid, 'sha256': 'b' * 64}}
        if index == 0 and broken == 'missing-one': receipt['source_refs'].pop('finite_ca_admission_ref')
        if index == 0 and broken == 'different-one': receipt['source_refs']['finite_ca_admission_ref']['sha256'] = 'c' * 64
        path.write_text(json.dumps(receipt)); manifest['extensions'][sid] = package['pin'](path)
    package['manifest'].write_text(json.dumps(manifest)); package['pointer'].write_text(json.dumps(package['pin'](package['manifest'])))
    finite = ModuleType('scripts.research.a2.evaluation.consensus_paper_ca_continuation')
    finite.validate_published_continuation = Mock(return_value={'status': 'VERIFIED_SYNTHETIC'})
    if broken == 'rejected-prefix': finite.validate_published_continuation.side_effect = ValueError('ACCEPTED_PREFIX_CHANGED')
    monkeypatch.setitem(sys.modules, finite.__name__, finite)
    monkeypatch.setattr(storage_paths, 'resolve', lambda: SimpleNamespace())
    result = package['select']()
    if broken == 'none':
        assert result['status'] == 'QUALIFIED_EXTENSION'
        proof_call = finite.validate_published_continuation.call_args.kwargs
        assert set(proof_call['completion_receipts']) == set(reader.SOURCES)
        assert all(row['source_refs']['finite_ca_admission_ref'] == admission for row in proof_call['completion_receipts'].values())
        native = stocks.query('ALPHA', '2026-10-09', '2026-10-12', sources=stocks.source_refs(bundle=result))
        assert all(row['status'] == 'READY' for row in native['strategies'].values())
    else:
        assert result['status'] == 'FALLBACK_ACCEPTED_PREFIX' and result['replay_sources'] == package['base']
    if broken in ('missing-one', 'different-one'): finite.validate_published_continuation.assert_not_called()


@pytest.fixture
def catalog_sources(tmp_path, monkeypatch):
    """One physical file, six legal paths and unreadable forbidden records."""
    rows = []
    for sid in reader.CATALOG_IDS:
        for day, nav, ret in (("2026-01-02", 100000., None),
                              ("2026-01-05", 101000., .01),
                              ("2026-10-08", 99990., -.01)):
            rows.append(dict(path_id=sid, date=day, nav=nav, net_return=ret,
                research_cash_weight=.2, transaction_cost_amount=1., turnover=0., actual_name_count=20,
                stale_count=0, unknown_count=0, accounting_qualified=True))
        rows.append(dict(rows[-1], date="2027-01-04", nav=float("nan")))
    rows.append(dict(rows[0], path_id="OTHER_FORBIDDEN_PATH", nav=float("nan")))
    daily = tmp_path / "catalog_daily.parquet"
    pd.DataFrame(rows).to_parquet(daily, index=False)
    receipt = tmp_path / "catalog_completion.json"
    receipt.write_text(json.dumps({"candidate_ids": list(reader.CATALOG_IDS)}))
    scope = tmp_path / "selector_scope.json"
    scope.write_text(json.dumps({"schema": "ALL_A_CONSENSUS100_FROZEN_RAW_SELECTOR_APPLICATION_SCOPE_R2",
        "task_id": "A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1",
        "application_pool_origin": "CONSENSUS_TOP100_FULL_PIT32_APPLICATION_POOL",
        "new_model_or_fit": False, "pre2026_training_identity_unchanged": True}))
    selector_ref = {"path": str(scope), "sha256": digest(scope)}
    monkeypatch.setattr(reader, "_RAW_SELECTOR_REF", selector_ref)
    refs = {sid: dict(path=str(daily), sha256=digest(daily), receipt=str(receipt),
        receipt_sha256=digest(receipt), research_id="synthetic") for sid in reader.CATALOG_IDS}
    refs["RAW_s10"].update(universe_variant="CONSENSUS100", pool_variant_id="TOP100",
        selector_scope_path=str(scope), selector_scope_sha256=digest(scope))
    reader._cached.cache_clear()
    yield refs, daily, scope
    reader._cached.cache_clear()


def test_catalog_common_prefix_uses_one_shared_scanner_with_predecode_predicates(catalog_sources, monkeypatch):
    import pyarrow.dataset as ds
    refs, _, _ = catalog_sources
    original = ds.dataset
    calls = []
    class ObservedDataset:
        def __init__(self, dataset): self.dataset = dataset; self.schema = dataset.schema
        def scanner(self, **kwargs):
            calls.append(kwargs)
            return self.dataset.scanner(**kwargs)
    monkeypatch.setattr(ds, "dataset", lambda *a, **kw: ObservedDataset(original(*a, **kw)))
    catalog = reader.read_catalog(sources=refs)
    assert len(calls) == 1
    assert set(catalog["views"]) == set(reader.CATALOG_IDS)
    assert len(calls[0]["columns"]) == 11 and "nav" in calls[0]["columns"]
    rule = str(calls[0]["filter"])
    assert "path_id" in rule and "2026-01-02" in rule and "2026-10-08" in rule
    assert all(sid in rule for sid in reader.CATALOG_IDS)
    for view in catalog["views"].values():
        assert view["history"]["status"] == "AVAILABLE"
        assert [r["date"] for r in view["history"]["daily"]] == ["2026-01-02", "2026-01-05", "2026-10-08"]
        assert view["summary"]["days"] == 2
        assert view["summary"]["cumulative_return"] == pytest.approx(-.0001)
        assert view["qualification"]["accounting_qualified_days"] == 2
        assert view["provenance"]["independent_holdout_claim"] is False


def test_default_three_publication_and_selected_extra_queries_remain_separate(catalog_sources, monkeypatch):
    refs, _, _ = catalog_sources
    monkeypatch.setattr(reader, "qualified_sources", lambda: {
        "status": "SYNTHETIC_PUBLICATION", "end": reader._PREFIX_END,
        "replay_sources": {sid: refs[sid] for sid in reader.SOURCES}})
    assert tuple(reader.load_views("2026-10-08")) == tuple(reader.SOURCES)
    monkeypatch.setattr(reader, "qualified_sources", lambda: pytest.fail("unselected publication read"))
    monkeypatch.setattr(reader, "CATALOG_SOURCES", refs)
    result = reader.load_views("2026-10-15", strategy_ids=("R6_BUY_NEURAL",))
    assert tuple(result) == ("R6_BUY_NEURAL",)
    assert result["R6_BUY_NEURAL"]["history"]["end"] == "2026-10-08"
    assert result["R6_BUY_NEURAL"]["provenance"]["publication_ref"] is None
    assert len(reader.SOURCES) == 3


@pytest.mark.parametrize("ids", [("NOT_A_CATALOG_STRATEGY",), ("R6_BUY_NEURAL", "R6_BUY_NEURAL"), ()])
def test_catalog_rejects_invalid_identity_before_any_source_access(monkeypatch, ids):
    monkeypatch.setattr(reader, "_observed_sources", lambda *a: pytest.fail("source access before IDs"))
    with pytest.raises(ValueError, match="QUERYABLE_STRATEGY_IDS"):
        reader.read_catalog(strategy_ids=ids)


def test_catalog_historical_scope_never_opens_2026_sources(monkeypatch):
    monkeypatch.setattr(reader, "_observed_sources", lambda *a: pytest.fail("2026 source read"))
    assert reader.read_catalog(sample="historical") == {}
    assert reader.load_views("2027-01-01", strategy_ids=("R6_BUY_NEURAL",)) == {}


@pytest.mark.parametrize("rehash", [False, True])
def test_catalog_raw_pool_scope_cannot_drift_or_be_replaced(catalog_sources, rehash):
    refs, _, scope = catalog_sources
    doc = json.loads(scope.read_text()); doc["application_pool_origin"] = "OTHER_POOL"
    scope.write_text(json.dumps(doc))
    if rehash:
        refs["RAW_s10"]["selector_scope_sha256"] = digest(scope)
    catalog = reader.read_catalog(sources=refs)
    assert catalog["views"]["RAW_s10"]["history"]["status"] == "UNAVAILABLE"
    assert catalog["views"]["RAW_s10"]["summary"] is None
    assert all(catalog["views"][sid]["history"]["status"] == "AVAILABLE"
               for sid in reader.CATALOG_IDS if sid != "RAW_s10")


def test_catalog_quality_unknowns_remain_distinct_from_real_zero(catalog_sources):
    refs, daily, _ = catalog_sources
    frame = pd.read_parquet(daily)
    selected = frame.path_id.eq("R6_BUY_NEURAL") & frame.date.eq("2026-01-05")
    for column in ("actual_name_count", "stale_count", "unknown_count", "accounting_qualified"):
        frame[column] = frame[column].astype("boolean" if column == "accounting_qualified" else "Float64")
        frame.loc[selected, column] = pd.NA
    frame.to_parquet(daily, index=False)
    for source in refs.values(): source["sha256"] = digest(daily)
    view = reader.read_catalog(sources=refs)["views"]["R6_BUY_NEURAL"]
    assert view["history"]["status"] == "AVAILABLE"
    assert view["summary"]["stale_mark_count"] is None
    assert view["summary"]["mean_holding_count"] is None
    assert view["qualification"]["stale_mark_count"] is None
    assert view["qualification"]["stale_mark_count_missing_days"] == 1
    assert view["qualification"]["accounting_unknown_days"] == 1
    assert view["history"]["daily"][-1]["stale_mark_count"] == 0


def test_catalog_model_identity_keeps_native_freezes_and_unknown_raw_chronology():
    for sid, slot in (("R6_BUY_NEURAL", "buy_neural_2025"), ("R6_DURATION_TREE", "duration_tree_2025")):
        identity = reader.model_identity(sid)
        assert identity["frozen_model_slot"] == slot
        assert identity["signal_cutoff_exclusive"] == "2024-10-07"
        assert identity["frozen_state_identity_ref"]["sha256"] == "84d2f4a644d1fdfae4f6954a3751be3bc156ec0141f537dbf64cdb55a0bf25a9"
    identity = reader.model_identity("RAW_s10")
    assert identity["distinct_from"] == "RAW_A2" and identity["universe_variant"] == "CONSENSUS100"
    assert identity["signal_cutoff_exclusive"] is None
    assert identity["chronology_status"] == "UNKNOWN_NOT_PROJECTED"



def test_catalog_frozen_main_end_is_data_free_and_only_for_query_additions(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("identity metadata must not read data")
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(reader, "_verified", forbidden)
    for sid in reader.SOURCES:
        assert "frozen_main_end" not in reader.model_identity(sid)
    for sid in reader.CATALOG_IDS:
        if sid not in reader.SOURCES:
            assert reader.model_identity(sid)["frozen_main_end"] == "2026-10-08"


def test_unknown_model_identity_has_no_frozen_range_fallback():
    with pytest.raises(KeyError):
        reader.model_identity("UNKNOWN")


def test_mixed_catalog_query_preserves_each_original_extension_end(extension_package, catalog_sources, monkeypatch):
    from apps.demo_console.adapters import new_strategy_stock_history_reader as stocks
    refs, _, _ = catalog_sources
    original = extension_package["select"]()
    assert original["status"] == "QUALIFIED_EXTENSION"
    monkeypatch.setattr(reader, "CATALOG_SOURCES", {**reader.CATALOG_SOURCES,
        **{sid: refs[sid] for sid in reader.CATALOG_IDS if sid not in reader.SOURCES}})
    mixed = reader.load_views("2026-10-12", strategy_ids=reader.CATALOG_IDS)
    assert all(mixed[sid]["history"]["end"] == "2026-10-12" for sid in reader.SOURCES)
    assert all(mixed[sid]["history"]["end"] == "2026-10-08" for sid in reader.CATALOG_IDS if sid not in reader.SOURCES)
    assert all(mixed[sid]["provenance"]["publication_ref"] is None for sid in reader.CATALOG_IDS if sid not in reader.SOURCES)
    # Physical fake native refs suffice: out-of-window additions must never scan.
    extra = {sid: {"receipt": {"path": refs[sid]["receipt"], "sha256": refs[sid]["receipt_sha256"]}}
             for sid in reader.CATALOG_IDS if sid not in reader.SOURCES}
    chosen = {**original["stock_sources"], **extra}
    query = stocks.query("ALPHA", "2026-10-09", "2026-10-12", sources=chosen)
    assert all("2026-10-12" in query["strategies"][sid]["daily"] for sid in reader.SOURCES)
    assert all(query["strategies"][sid]["status"] == "UNAVAILABLE" and not query["strategies"][sid]["daily"] for sid in extra)
    day = stocks.rankings("2026-10-09", sources=chosen)
    assert all(day["strategies"][sid]["status"] == "AVAILABLE" for sid in reader.SOURCES)
    assert all(day["strategies"][sid]["status"] == "BLOCKED" and not day["strategies"][sid]["rows"] for sid in extra)
    assert all("EXCEEDS_ACCEPTED_END" in day["strategies"][sid]["error"] for sid in extra)
