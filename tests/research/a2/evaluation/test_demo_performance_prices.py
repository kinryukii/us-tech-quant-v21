import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[4]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


module = load("execution_prices_under_test", ROOT / "scripts/research/a2/evaluation/demo_performance_prices.py")
FIXTURE_ROOT = ROOT if (ROOT / "tests/test_daily_recommendation_prices.py").is_file() else Path("D:/us-tech-quant")
fixtures = load("execution_shared_price_fixtures", FIXTURE_ROOT / "tests/test_daily_recommendation_prices.py")


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "original", fixtures.prices)
    kwargs, raw, _ = fixtures.fixture(tmp_path)
    coverage = tmp_path / "backtests/research/a2/demo_2026_calendar_replay/input_coverage.json"
    coverage.parent.mkdir(parents=True)
    coverage.write_bytes(Path(kwargs["coverage_reference"]["path"]).read_bytes())
    monkeypatch.setattr(fixtures.prices, "COVERAGE_SHA", fixtures.prices.digest(coverage))
    entry = {"ticker": "AAPL", "code": "US.AAPL", "anchor_date": "2026-01-02",
        "raw_end": raw.time_key.max(), "price_basis": "PIT_FORWARD_REHAB_INDEX",
        "raw_sources": [{"path": str(tmp_path / "original.parquet"),
                         "sha256": fixtures.prices.digest(tmp_path / "original.parquet"), "role": "ORIGINAL_ANCHOR"}],
        "rehab": {**kwargs["rehab_receipt"]["results"][0], "kind": "CURRENT_SNAPSHOT"}}
    source = tmp_path / "price_inputs.json"
    source.write_text(json.dumps({"lineage": [entry], "gaps": []}))
    path = tmp_path / "manifest.json"
    manifest = {"schema_version": 1, "status": "PARTIAL", "run_id": "synthetic", "report_path": str(path),
        "start_date": "2026-01-05", "end_date": kwargs["target"],
        "price_manifest": {"path": str(source), "sha256": fixtures.prices.digest(source)}}
    path.write_text(json.dumps(manifest))
    paths = SimpleNamespace(backtest_root=tmp_path / "backtests", daily_root=tmp_path / "daily")
    return paths, path, entry, kwargs


def current(case, tmp_path, *, change=None):
    _, _, entry, kwargs = case
    row = {**entry, "adapter_sha256": fixtures.prices.ADAPTER_SHA,
        "coverage_manifest_sha256": fixtures.prices.COVERAGE_SHA,
        "rehab_sha256": entry["rehab"]["sha256"], "rehab_fetched_at": entry["rehab"]["fetched_at"],
        "raw_sources": [*entry["raw_sources"], {**kwargs["acquisitions"]["moomoo"]["results"][0], "role": "CURRENT_RAW"}]}
    row.pop("rehab"); row.pop("raw_end")
    if change:
        change(row)
    directory = tmp_path / "current"
    directory.mkdir()
    (directory / "input_lineage.json").write_text(json.dumps([row]))
    (directory / "rehab_receipt.json").write_text(json.dumps(kwargs["rehab_receipt"]))
    path = directory / "report.json"
    path.write_text(json.dumps({"status": "READY", "model_id": module.MODEL_ID,
        "model_sha256": module.MODEL_SHA256, "report_path": str(path), "data_date": kwargs["target"],
        "input_manifest_sha256": hashlib.sha256(json.dumps([row], sort_keys=True).encode()).hexdigest()}))
    return path


def test_recovers_original_affine_anchor_and_leaves_missing_final_open_absent(case):
    paths, manifest, entry, kwargs = case
    result = module.load_execution_prices(paths, manifest, tickers=["AAPL", "MISSING"])
    assert result["prices"].open.eq(101).all()
    assert result["prices"].trade_date.max().date().isoformat() == entry["raw_end"]
    assert pd.Timestamp(kwargs["target"]) not in set(result["prices"].trade_date)
    assert result["gaps"] == [{"ticker": "MISSING", "reason": "EXECUTION_ACCEPTED_PRICE_LINEAGE_UNAVAILABLE"}]
    assert {row["path"] for row in result["refs"]} >= {str(manifest.resolve()), entry["rehab"]["path"]}


def test_current_native_lineage_extends_price_with_original_coordinate(case, tmp_path):
    paths, manifest, _, kwargs = case
    result = module.load_execution_prices(paths, manifest, current_report_path=current(case, tmp_path))
    assert result["prices"].trade_date.max() == pd.Timestamp(kwargs["target"])
    assert result["prices"].open.eq(101).all() and not result["gaps"]


def test_current_receipt_cannot_change_anchor(case, tmp_path):
    paths, manifest, entry, _ = case
    report = current(case, tmp_path, change=lambda row: row.update(anchor_date="2026-01-05"))
    result = module.load_execution_prices(paths, manifest, current_report_path=report)
    assert result["prices"].trade_date.max() == pd.Timestamp(entry["raw_end"])
    assert any("ANCHOR_IDENTITY_CHANGED" in row["reason"] for row in result["gaps"])


def test_current_lineage_canonical_hash_is_required(case, tmp_path):
    paths, manifest, _, _ = case
    report = current(case, tmp_path)
    (report.parent / "input_lineage.json").write_text("[]")
    with pytest.raises(ValueError, match="LINEAGE_HASH_MISMATCH"):
        module.load_execution_prices(paths, manifest, current_report_path=report)


def test_immutable_published_current_can_reference_same_historical_run(case, tmp_path):
    paths, manifest, _, kwargs = case
    directory = tmp_path / "published"; directory.mkdir()
    lineage = directory / "input_lineage.json"
    lineage.write_text(json.dumps({"historical_manifest": {"path": str(manifest), "sha256": fixtures.prices.digest(manifest)}}))
    report = directory / "report.json"
    report.write_text(json.dumps({"status": "READY", "model_id": module.MODEL_ID,
        "model_sha256": module.MODEL_SHA256, "report_path": str(report), "data_date": kwargs["target"],
        "input_manifest_sha256": fixtures.prices.digest(lineage)}))
    assert not module.load_execution_prices(paths, manifest, current_report_path=report)["gaps"]


def test_changed_source_is_a_visible_gap_never_zero_filled(case):
    paths, manifest, entry, _ = case
    Path(entry["raw_sources"][0]["path"]).write_bytes(b"changed")
    result = module.load_execution_prices(paths, manifest)
    assert result["prices"].empty
    assert any("PRICE_SOURCE_HASH_MISMATCH" in row["reason"] for row in result["gaps"])


def bridge_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "original", fixtures.prices)
    monkeypatch.setattr(module, "EXECUTION_BRIDGE_TICKERS", frozenset({"AAPL"}))
    return fixtures.massive_fixture(tmp_path, monkeypatch)


def test_volume_rejection_remains_for_feature_but_execution_prices_qualify(tmp_path, monkeypatch):
    kwargs, record, native = bridge_fixture(tmp_path, monkeypatch)
    native.loc[native.index[-1], "volume"] = 1001
    with pytest.raises(ValueError, match="MASSIVE_RAW_OVERLAP_MISMATCH:volume"):
        fixtures.prices._qualified_massive_tail(record, native, "AAPL", kwargs["target"], kwargs["store"])
    tail, proof = module.qualify_execution_massive_tail(record, native, "AAPL", kwargs["target"], kwargs["store"])
    assert len(tail) == 1 and proof["model_feature_eligibility_granted"] is False
    assert proof["overlap_differences"]["volume"]["unequal_rows"] == 1


@pytest.mark.parametrize("mutation,reason", [
    ("identity", "SOURCE_IDENTITY"), ("hash", "HASH_MISMATCH"),
    ("open", "RECENT_OHLC_MISMATCH:open"), ("low", "RECENT_OHLC_MISMATCH:low")])
def test_execution_bridge_keeps_identity_source_and_ohlc_gates(tmp_path, monkeypatch, mutation, reason):
    kwargs, record, native = bridge_fixture(tmp_path, monkeypatch)
    if mutation == "identity": record["lineage"]["currency"] = "EUR"
    elif mutation == "hash": Path(record["path"]).write_bytes(b"changed")
    else: native.loc[native.index[-1], mutation] += 1
    with pytest.raises(ValueError, match=reason):
        module.qualify_execution_massive_tail(record, native, "AAPL", kwargs["target"], kwargs["store"])


def test_unlisted_ticker_cannot_obtain_execution_exception(tmp_path, monkeypatch):
    kwargs, record, native = fixtures.massive_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="NOT_AUTHORIZED"):
        module.qualify_execution_massive_tail(record, native, "AAPL", kwargs["target"], kwargs["store"])


@pytest.mark.parametrize("field", ["open", "close", "high"])
def test_full_overlap_checks_execution_prices_and_records_older_high_difference(tmp_path, monkeypatch, field):
    kwargs, record, native = bridge_fixture(tmp_path, monkeypatch)
    path = Path(record["path"])
    normalized = pd.read_parquet(path)
    older = normalized.iloc[0].to_dict()
    older["date"] = native.trade_date.iloc[0].date().isoformat()
    older[field] = 101.0
    pd.concat([pd.DataFrame([older]), normalized], ignore_index=True).to_parquet(path, index=False)
    record["source_sha256"] = fixtures.prices.digest(path)
    if field in {"open", "close"}:
        with pytest.raises(ValueError, match="FULL_EXECUTION_PRICE_MISMATCH:" + field):
            module.qualify_execution_massive_tail(record, native, "AAPL", kwargs["target"], kwargs["store"])
    else:
        _, proof = module.qualify_execution_massive_tail(record, native, "AAPL", kwargs["target"], kwargs["store"])
        assert proof["overlap_differences"]["high"]["unequal_rows"] == 1
        assert proof["consumer_fields"] == ["open", "close"]


def test_execution_supplement_must_bind_exact_historical_manifest(case, tmp_path):
    paths, manifest, _, _ = case
    supplement = tmp_path / "supplement.json"
    supplement.write_text(json.dumps({"schema": "A2_EXECUTION_PRICE_SUPPLEMENT_V1", "gate": module.EXECUTION_GATE,
        "model_feature_eligibility_granted": False, "historical_manifest_sha256": "0" * 64, "lineage": []}))
    with pytest.raises(ValueError, match="SUPPLEMENT_CONTRACT_MISMATCH"):
        module.load_execution_prices(paths, manifest, additional_price_manifest_path=supplement)


def test_latest_alias_requires_identical_immutable_manifest_bytes(case, tmp_path):
    paths, manifest, _, _ = case
    canonical = tmp_path / "runs/synthetic/manifest.json"
    canonical.parent.mkdir(parents=True)
    value = json.loads(manifest.read_text())
    value["report_path"] = str(canonical)
    canonical.write_text(json.dumps(value))
    pointer = tmp_path / "latest.json"
    pointer.write_bytes(canonical.read_bytes())
    result = module.load_execution_prices(paths, pointer)
    assert not result["gaps"]
    assert {str(pointer), str(canonical)} <= {row["path"] for row in result["refs"]}
    canonical.write_text(canonical.read_text() + " ")
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        module.load_execution_prices(paths, pointer)


def event_review(tmp_path):
    evidence = tmp_path / "facts.json"
    evidence.write_text('{"review_type":"synthetic"}')
    record = {"ticker":"VKTX", "code":"US.VKTX", "event_date":"2024-02-27",
        "audit_kind":"LARGE_RAW_MOVE_NO_VENDOR_EVENT", "raw_jump":1.2102390852390852,
        "status":"RESOLVED_NON_CORPORATE_ACTION", "prices_or_share_quantities_changed":False}
    event = pd.DataFrame([record])
    path = tmp_path / "event_review.json"
    review = {"schema":"A2_EXECUTION_EVENT_REVIEW_V1", "policy":module.EVENT_REVIEW_POLICY,
        "review_type":"AGENT_EVIDENCE_REVIEW", "historical_manifest_sha256":"a"*64,
        "execution_price_supplement_sha256":"b"*64, "prices_or_share_quantities_changed":False,
        "records":[record], "evidence_refs":[{"path":str(evidence),"sha256":module.original.digest(evidence)}]}
    path.write_text(json.dumps(review))
    return path, review, event, evidence


def test_exact_event_review_is_bound_without_changing_original_event(tmp_path):
    path, _, events, _ = event_review(tmp_path)
    before = events.copy(deep=True)
    ref = module._validated_event_review(path,"a"*64,"b"*64,events,{"VKTX"},module.original.verify)
    assert ref["sha256"] == module.original.digest(path)
    pd.testing.assert_frame_equal(events,before)


@pytest.mark.parametrize("change", ["code","jump","status","evidence","history"])
def test_event_review_cannot_change_identity_jump_evidence_or_scope(tmp_path, change):
    path, review, events, evidence = event_review(tmp_path)
    if change == "code": review["records"][0]["code"] = "US.OTHER"
    elif change == "jump": review["records"][0]["raw_jump"] = 1.3
    elif change == "status": review["records"][0]["status"] = "IGNORE"
    elif change == "history": review["historical_manifest_sha256"] = "c"*64
    else: evidence.write_text("changed")
    path.write_text(json.dumps(review))
    with pytest.raises(ValueError):
        module._validated_event_review(path,"a"*64,"b"*64,events,{"VKTX"},module.original.verify)


def inference(case, tmp_path):
    paths, historical, entry, kwargs = case
    history = json.loads(historical.read_text())
    history["end_date"] = entry["raw_end"]
    historical.write_text(json.dumps(history))
    report_path = current(case, tmp_path)
    report = json.loads(report_path.read_text())
    rows, _ = module._current_entries(report_path, historical.resolve(), module.original.digest(historical), module.original.verify)
    price_path = tmp_path / "missed_price_inputs.json"
    price_path.write_text(json.dumps({"lineage": rows, "gaps": []}))
    path = tmp_path / "missed_manifest.json"
    value = {"schema": "A2_MISSED_SESSION_INFERENCE_V1", "status": "READY", "report_path": str(path),
        "model_sha256": module.MODEL_SHA256, "model_fit_count": 0,
        "historical_manifest": {"path": str(historical), "sha256": module.original.digest(historical)},
        "current_report": {"path": str(report_path), "sha256": module.original.digest(report_path)},
        "start_date": kwargs["target"], "end_date": kwargs["target"],
        "price_manifest": {"path": str(price_path), "sha256": module.original.digest(price_path)}}
    path.write_text(json.dumps(value))
    return path, value, report_path, price_path


def test_missing_session_lineage_uses_same_adjustment_and_is_bound_in_refs(case, tmp_path):
    path, _, current_path, price_path = inference(case, tmp_path)
    paths, historical, _, kwargs = case
    result = module.load_execution_prices(paths, historical, current_report_path=current_path, inference_manifest_path=path)
    assert not result["gaps"] and result["prices"].open.eq(101).all()
    assert result["prices"].trade_date.max() == pd.Timestamp(kwargs["target"])
    assert {str(path), str(price_path)} <= {row["path"] for row in result["refs"]}


def test_newly_selected_ticker_can_start_from_missed_session_proof(case, tmp_path):
    path, value, current_path, _ = inference(case, tmp_path)
    paths, historical, _, _ = case
    history = json.loads(historical.read_text())
    old_prices = Path(history["price_manifest"]["path"])
    old_prices.write_text(json.dumps({"lineage": [], "gaps": []}))
    history["price_manifest"]["sha256"] = module.original.digest(old_prices)
    historical.write_text(json.dumps(history))
    value["historical_manifest"]["sha256"] = module.original.digest(historical)
    path.write_text(json.dumps(value))
    result = module.load_execution_prices(paths, historical, current_report_path=current_path, inference_manifest_path=path)
    assert not result["gaps"] and set(result["prices"].ticker) == {"AAPL"}
    assert result["prices"].open.eq(101).all()


@pytest.mark.parametrize("change", ["history", "current", "end", "model", "status", "raw_hash"])
def test_missing_session_lineage_cannot_escape_recorded_contract(case, tmp_path, change):
    path, value, current_path, price_path = inference(case, tmp_path)
    if change in {"history", "current"}:
        value["historical_manifest" if change == "history" else "current_report"]["sha256"] = "0" * 64
    elif change == "end": value["end_date"] = "2027-01-01"
    elif change == "model": value["model_fit_count"] = 1
    elif change == "status": value["status"] = "BLOCKED"
    else: price_path.write_text("{}")
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        module.load_execution_prices(case[0], case[1], current_report_path=current_path, inference_manifest_path=path)


def feature_bridge_entry(tmp_path, monkeypatch, provider='MASSIVE_GROUPED'):
    monkeypatch.setattr(module, 'original', fixtures.prices)
    kwargs, record, native = fixtures.massive_fixture(tmp_path, monkeypatch, source_volume=1000.936259)
    if provider == 'MASSIVE_GROUPED':
        _, proof = fixtures.prices._qualified_massive_tail(record, native, 'AAPL', kwargs['target'], kwargs['store'])
    else:
        appended = pd.read_parquet(record['path']); appended['volume'] = 1000.
        receipt, _ = fixtures.yahoo_fixture(tmp_path, native, appended, kwargs['target'])
        _, proof = fixtures.prices._qualified_yahoo_tail(receipt, native, 'AAPL', kwargs['target'])
    entry = dict(ticker='AAPL', code='US.AAPL', anchor_date=native.trade_date.min().date().isoformat(),
                 raw_end=kwargs['target'], price_basis='PIT_FORWARD_REHAB_INDEX', alternate_bridge=proof,
                 raw_sources=[dict(path=str(tmp_path/'original.parquet'),
                     sha256=fixtures.prices.digest(tmp_path/'original.parquet'), role='ORIGINAL_ANCHOR')])
    return kwargs, entry


@pytest.mark.parametrize('provider', ['MASSIVE_GROUPED','YAHOO_CHART'])
def test_feature_bridge_replays_same_strict_proof_to_execution_end(tmp_path, monkeypatch, provider):
    kwargs, entry = feature_bridge_entry(tmp_path, monkeypatch, provider)
    seen=[]
    def verify(path, sha):
        seen.append(str(path)); return fixtures.prices.verify(path,sha)
    result = module._raw(entry,verify,kwargs['store'],{})
    assert result.trade_date.max()==pd.Timestamp(kwargs['target'])
    assert result.open.eq(100.).all() and result.volume.eq(1000.).all()
    assert len(seen)>2


def test_feature_bridge_rejects_modified_proof_and_missing_yahoo_receipt(tmp_path, monkeypatch):
    kwargs, entry=feature_bridge_entry(tmp_path,monkeypatch)
    entry['alternate_bridge']['volume_normalization']['rule']='ROUND'
    with pytest.raises(ValueError,match='QUALIFICATION_CHANGED'):
        module._raw(entry,fixtures.prices.verify,kwargs['store'],{})
    entry['alternate_bridge']={'provider':'YAHOO_CHART'}
    with pytest.raises(ValueError,match='YAHOO_ACQUISITION_RECEIPT_MISSING'):
        module._raw(entry,fixtures.prices.verify,kwargs['store'],{})


def native_entry(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'original',fixtures.prices)
    kwargs,raw,_=fixtures.fixture(tmp_path)
    leaf=raw.copy();leaf['source']='MOOMOO_OPEND';leaf['adjustment']='raw'
    leaf_path=tmp_path/'native_leaf.parquet';leaf.to_parquet(leaf_path,index=False)
    leaf_sha=fixtures.prices.digest(leaf_path)
    normalized=leaf.rename(columns={'time_key':'date','code':'provider_code'})
    normalized['ticker']='AAPL';normalized['source_id']=leaf_sha
    path=tmp_path/'native_normalized.parquet';normalized.to_parquet(path,index=False)
    proof=dict(path=str(path),sha256=fixtures.prices.digest(path),raw_inputs=[dict(path=str(leaf_path),sha256=leaf_sha)],
               provider='MOOMOO_OPEND',provider_code='US.AAPL',adjustment='RAW')
    entry=dict(ticker='AAPL',code='US.AAPL',security_id='synthetic',anchor_date=raw.time_key.min(),raw_end=raw.time_key.max(),
               price_basis='PIT_FORWARD_REHAB_INDEX',raw_sources=[{**proof,'role':'NATIVE_MOOMOO_ANCHOR'}],
               anchor_proof=dict(kind='NEW_13F_MEMBER_NATIVE_RAW_ANCHOR',scope='2026_INFERENCE_ONLY',
                                 old_frozen_equivalence_claimed=False,native_source=proof))
    return entry


def test_native_anchor_preserves_role_and_rechecks_normalized_against_original_leaf(tmp_path,monkeypatch):
    entry=native_entry(tmp_path,monkeypatch)
    frame=module._raw(entry,fixtures.prices.verify)
    assert len(frame)==122 and frame.open.eq(100).all()
    path=Path(entry['raw_sources'][0]['path']);normalized=pd.read_parquet(path);normalized.loc[0,'open']=99.;normalized.to_parquet(path,index=False)
    sha=fixtures.prices.digest(path)
    entry['raw_sources'][0]['sha256']=sha;entry['anchor_proof']['native_source']['sha256']=sha
    with pytest.raises(ValueError,match='NORMALIZED_LEAF_MISMATCH'):
        module._raw(entry,fixtures.prices.verify)


@pytest.mark.parametrize('field,value', [('scope','HISTORICAL_ALL'),('old_frozen_equivalence_claimed',True)])
def test_native_anchor_cannot_claim_frozen_or_pre2026_scope(tmp_path,monkeypatch,field,value):
    entry=native_entry(tmp_path,monkeypatch);entry['anchor_proof'][field]=value
    with pytest.raises(ValueError,match='NATIVE_ANCHOR_PROOF_INVALID'):
        module._raw(entry,fixtures.prices.verify)


def test_native_execution_projection_does_not_expose_pre2026_warmup_rows(tmp_path,monkeypatch):
    entry=native_entry(tmp_path,monkeypatch)
    factors=tmp_path/'factors.parquet';pd.DataFrame({'code':['US.AAPL']}).to_parquet(factors,index=False)
    entry['rehab']={'path':str(factors),'sha256':fixtures.prices.digest(factors),'kind':'CURRENT_SNAPSHOT'}
    def adjusted(code,ticker,raw,factor,wolf):
        frame=pd.DataFrame({'ticker':['AAPL','AAPL'],'trade_date':pd.to_datetime(['2025-12-31','2026-01-02']),
            **{field:[100.,100.] for field in fixtures.prices.PRICE_FIELDS}})
        return frame,[dict(ticker='AAPL',event_date='2025-12-31'),dict(ticker='AAPL',event_date='2026-01-02')]
    frame,events=module._adjust(entry,SimpleNamespace(adjusted_price_frame=adjusted),{},fixtures.prices.verify,{},None,{})
    assert frame.trade_date.dt.strftime('%Y-%m-%d').tolist()==['2026-01-02']
    assert [event['event_date'] for event in events]==['2026-01-02']


def test_native_dated_union_accepts_explicit_identity_set_only_for_downstream_pit_join(tmp_path,monkeypatch):
    entry=native_entry(tmp_path,monkeypatch)
    entry.update(security_id=None,security_ids=['first-cusip','second-cusip'],
                 membership_validation='REQUIRES_DOWNSTREAM_DAILY_PIT_JOIN')
    assert len(module._raw(entry,fixtures.prices.verify))==122
    entry['membership_validation']='CALLER_VERIFIED_CURRENT_PIT_UNIVERSE'
    with pytest.raises(ValueError,match='NATIVE_ANCHOR_PROOF_INVALID'):
        module._raw(entry,fixtures.prices.verify)
    entry['membership_validation']='REQUIRES_DOWNSTREAM_DAILY_PIT_JOIN'
    entry['security_ids']=['same','same']
    with pytest.raises(ValueError,match='NATIVE_ANCHOR_PROOF_INVALID'):
        module._raw(entry,fixtures.prices.verify)


SQ_ALIAS_PROOF = {'logical_ticker':'SQ','source_ticker':'XYZ','provider_code':'US.XYZ','security_id':'852234103',
    'evidence_url':'https://investors.block.xyz/investor-news/news-details/2025/Block-Announces-Ticker-Symbol-Change-to-XYZ-To-Report-Fourth-Quarter-Results/default.aspx',
    'rule':'REGISTERED_CUSIP_AND_ISSUER_TICKER_CHANGE'}


def sq_native_entry(tmp_path,monkeypatch):
    entry=native_entry(tmp_path,monkeypatch)
    entry.update(ticker='SQ',code='US.XYZ',security_id='852234103')
    proof=entry['anchor_proof']['native_source']
    leaf_ref=proof['raw_inputs'][0];leaf_path=Path(leaf_ref['path'])
    leaf=pd.read_parquet(leaf_path);leaf['code']='US.XYZ';leaf.to_parquet(leaf_path,index=False)
    leaf_ref['sha256']=fixtures.prices.digest(leaf_path)
    path=Path(proof['path']);frame=pd.read_parquet(path)
    frame['ticker']='XYZ';frame['provider_code']='US.XYZ';frame['source_id']=leaf_ref['sha256']
    frame.to_parquet(path,index=False)
    proof.update(sha256=fixtures.prices.digest(path),provider_code='US.XYZ',transport_alias_proof=dict(SQ_ALIAS_PROOF))
    entry['raw_sources']=[{**proof,'role':'NATIVE_MOOMOO_ANCHOR'}]
    return entry


def test_execution_native_sq_alias_requires_the_reviewed_same_security_contract(tmp_path,monkeypatch):
    entry=sq_native_entry(tmp_path,monkeypatch)
    assert len(module._raw(entry,fixtures.prices.verify))==122
    entry['anchor_proof']['native_source']['transport_alias_proof']['source_ticker']='OTHER'
    with pytest.raises(ValueError):
        module._raw(entry,fixtures.prices.verify)


@pytest.mark.parametrize('changed', ['security','code','logical','evidence'])
def test_execution_native_sq_alias_is_not_a_generic_ticker_override(tmp_path,monkeypatch,changed):
    entry=sq_native_entry(tmp_path,monkeypatch)
    if changed=='security':entry['security_id']='OTHER_CUSIP'
    elif changed=='code':entry['code']='US.OTHER'
    elif changed=='logical':entry['ticker']='OTHER'
    else:entry['anchor_proof']['native_source']['transport_alias_proof']['evidence_url']='https://example.com'
    with pytest.raises(ValueError):module._raw(entry,fixtures.prices.verify)


def test_execution_sq_massive_bridge_replays_source_symbol_and_same_alias_proof(tmp_path,monkeypatch):
    # Full raw/checkpoint revalidation still runs against the source XYZ symbol.
    kwargs,record,_=fixtures.massive_fixture(tmp_path,monkeypatch,source_volume=1000.9)
    normalized=pd.read_parquet(record['path'])
    for ref in record['lineage']['inputs']:
        path=Path(ref['path']);payload=json.loads(path.read_text());payload['results'][0]['T']='XYZ'
        path.write_text(json.dumps(payload));ref['sha256']=fixtures.prices.digest(path)
        checkpoint=path.parent/'checkpoint.json';cp=json.loads(checkpoint.read_text());cp['raw']['sha256']=ref['sha256'];checkpoint.write_text(json.dumps(cp))
        normalized.loc[normalized.date.eq(ref['date']),'source_id']=ref['sha256']
    normalized['ticker']='XYZ';normalized['provider_code']='XYZ';normalized.to_parquet(record['path'],index=False)
    record.update(ticker='XYZ',source_sha256=fixtures.prices.digest(record['path']))
    record['lineage'].update(provider_symbol='XYZ',provider_mapping={'provider_symbol':'XYZ'})
    entry=sq_native_entry(tmp_path,monkeypatch)
    native=module._raw(entry,fixtures.prices.verify)
    _,bridge=fixtures.prices._qualified_massive_tail(record,native,'XYZ',kwargs['target'],kwargs['store'])
    bridge['transport_alias_proof']=dict(SQ_ALIAS_PROOF)
    entry.update(alternate_bridge=bridge,raw_end=kwargs['target'])
    actual=module._raw(entry,fixtures.prices.verify,kwargs['store'],{})
    assert actual.trade_date.max()==pd.Timestamp(kwargs['target']) and actual.volume.eq(1000).all()
    entry['alternate_bridge']['transport_alias_proof']={**SQ_ALIAS_PROOF,'logical_ticker':'OTHER'}
    with pytest.raises(ValueError):module._raw(entry,fixtures.prices.verify,kwargs['store'],{})


def test_execution_internal_gap_replays_exact_recorded_missing_dates(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'original',fixtures.prices)
    kwargs,record,raw=fixtures.massive_fixture(tmp_path,monkeypatch,source_volume=1000.9,source_sessions=10)
    gap=raw.trade_date.iloc[-3]
    raw=raw.loc[raw.trade_date.ne(gap)].copy()
    _,proof=fixtures.prices._qualified_massive_tail(record,raw,'AAPL',kwargs['target'],kwargs['store'],gap_dates=[str(gap.date())])
    entry={'ticker':'AAPL','code':'US.AAPL','raw_end':kwargs['target'],'alternate_bridge':proof}
    added=module._replay_alternate(entry,raw,fixtures.prices.verify,kwargs['store'],{})
    assert gap in set(added.trade_date)
    proof['gap_fill']['added_dates']=[]
    with pytest.raises(ValueError,match='QUALIFICATION_CHANGED'):
        module._replay_alternate(entry,raw,fixtures.prices.verify,kwargs['store'],{})
