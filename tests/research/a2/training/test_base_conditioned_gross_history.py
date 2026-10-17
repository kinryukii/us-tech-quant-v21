"""Synthetic historical plumbing; no real market read, fit, or account execution."""
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.research.a2.training import base_conditioned_gross_history as history


def test_wrapper_has_no_financial_top_level_imports():
    tree = ast.parse(Path(history.__file__).read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node,ast.ImportFrom):
            assert not str(node.module).startswith(("numpy","pandas","scripts.research"))


def static_source(future='"quantity_multiplier": explode(),'):
    return '''def canonical_bytes(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
def payload_sha256(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
def frozen_evidence_records():
    records = [
        {
            "ticker": "OLD", "event_date": "2024-01-03",
            "quantity_multiplier": 2.0,
        },
        {
            "ticker": "FUT", "event_date": "2024-10-07",
            ''' + future + '''
        },
    ]
    return records
'''


def test_static_clock_first_future_poison_and_append_invariant(tmp_path):
    path = tmp_path / "static.py"; path.write_text(static_source(),encoding="utf-8")
    records, supplier, audit = history.bounded_static_records(path)
    assert len(records) == 1 and records[0]["ticker"] == "OLD"
    assert audit["excluded_payloads_evaluated"] == 0
    namespace = {}; exec(supplier,namespace)
    assert namespace["frozen_evidence_records"]() == records
    path.write_text(static_source('"quantity_multiplier": another_forbidden_future(),'),encoding="utf-8")
    assert history.bounded_static_records(path)[0] == records


def test_static_numeric_before_date_refused(tmp_path):
    path = tmp_path / "bad.py"
    path.write_text(static_source().replace('"ticker": "OLD", "event_date": "2024-01-03",','"quantity_multiplier": 4,'),encoding="utf-8")
    with pytest.raises(ValueError,match="STATIC_DATE_MUST_PRECEDE_PAYLOAD"):
        history.bounded_static_records(path)


@pytest.mark.parametrize("string_clock",[False,True])
def test_bounded_scanner_filters_both_clocks_before_value_decode(tmp_path,string_clock):
    path = tmp_path / "mixed.parquet"
    data = pd.DataFrame(dict(signal_date=["2024-01-03","2024-10-07","2024-01-04"],
         mature=["2024-01-10","2024-10-14","2025-01-01"],value=["legal","forbidden","forbidden"]))
    if not string_clock:
        for col in ("signal_date","mature"): data[col] = pd.to_datetime(data[col])
    data.to_parquet(path,index=False)
    result = history.bounded(history.ref(path),list(data),"signal_date",second_clock="mature")
    assert result.value.tolist() == ["legal"]


def manifest():
    return dict(schema="BASE_CONDITIONED_GROSS_HISTORY_INPUT_R1",task_id=history.TASK,
         driver_ref=history.ref(history.__file__),cutoff_exclusive=history.CUTOFF,
         status="ROOT_SEALED_BOUNDED_HISTORY",permits={"sources":True})


def test_phase_gate_before_numerical_or_account_import(tmp_path):
    with pytest.raises(ValueError,match="ROOT_HISTORY_PHASE_RELEASE_REQUIRED"):
        history.account(manifest(),tmp_path,SimpleNamespace())
    with pytest.raises(ValueError,match="ROOT_HISTORY_PHASE_RELEASE_REQUIRED"):
        history.prepare(manifest(),tmp_path,SimpleNamespace())


def test_resource_failure_makes_no_checkpoint_or_event_read(tmp_path,monkeypatch):
    from scripts.research.a2.training import base_conditioned_gross_run as runner
    def blocked(*a): raise ValueError("ORIGINAL_RESOURCE_ADMISSION")
    monkeypatch.setattr(runner,"resource_gate",blocked)
    monkeypatch.setattr(history,"typed_events",lambda *a:pytest.fail("event read"))
    m = manifest(); m.update(source_refs=dict(account_source={},bounded_event_binding={}),resource_owner_ref={})
    with pytest.raises(ValueError,match="ORIGINAL_RESOURCE_ADMISSION"):
        history.source_prepare(m,tmp_path)
    assert not list(tmp_path.iterdir())


def test_signal_feature_provider_keeps_axis_and_no_future_data():
    from scripts.research.a2.training.stateful_inputs import FEATURES
    flags = pd.DataFrame([dict(signal_date=pd.Timestamp("2024-02-22"),ticker="A",security_id="idA",raw_a2_prediction=.1,
                              **dict.fromkeys(FEATURES,2.)),
                          dict(signal_date=pd.Timestamp("2024-02-23"),ticker="A",security_id="idA",raw_a2_prediction=99.,
                              **dict.fromkeys(FEATURES,99.))])
    provider = history.feature_provider(flags,["B","A"])
    keys,x,scores = provider(0,SimpleNamespace(tickers=["B","A"],signal_date=pd.Timestamp("2024-02-22")),0)
    assert keys == (("B","UNAVAILABLE"),("A","idA"))
    assert np.isnan(x[0]).all() and (x[1] == 2).all() and scores[1] == .1


def test_pool_snapshot_date_gate_precedes_members(tmp_path):
    schedule = pd.DataFrame(dict(snapshot_id=["old","future"],source_snapshot_id=["o","f"],quarter=["2023Q4","2024Q3"],
         effective_date=["2024-02-22","2024-10-07"],source_effective_at=["2024-02-22T00:00:00Z","2024-10-07T00:00:00Z"],
         universe_member_count=[100,100],institution_count=[25,25]))
    schedule_path=tmp_path/"schedule.parquet";schedule.to_parquet(schedule_path,index=False)
    members=pd.DataFrame([dict(snapshot_id=s,cusip=str(i),consensus_rank=i+1) for s in ("old","future") for i in range(100)])
    members_path=tmp_path/"members.parquet";members.to_parquet(members_path,index=False)
    pool=history.read_pool(dict(pool_schedule=history.ref(schedule_path),pool_members=history.ref(members_path)))
    assert len(pool)==100 and pool.signal_date.eq("2024-02-22").all()


def test_original_h5_exact_extension_block_is_reused(tmp_path):
    source=tmp_path/"owner.py"
    source.write_text('def build_real_frames():\n    for h in (5,):\n        if h == 5:\n            packet["owner_marker"] = extension["value"]\n',encoding="utf-8")
    packet=history.original_h5_extension({},dict(value=123),history.ref(source))
    assert packet == {"owner_marker":123}


def test_main_metadata_performs_no_bootstrap(tmp_path,capsys):
    m=manifest(); path=tmp_path/"manifest.json";path.write_text(json.dumps(m),encoding="utf-8")
    history.main(["--manifest",str(path),"--manifest-sha",history.ref(path)["sha256"]])
    result=json.loads(capsys.readouterr().out)
    assert result == dict(status="METADATA_ONLY",numerical_reads=0,actual_fits=0,account_paths=0)


def test_rank_keeps_calendar_denominator_and_requires_ineligibility_proof(monkeypatch):
    from scripts.research.a2.inference import historical_top40 as ranking
    from scripts.research.a2.training.stateful_inputs import FEATURES
    dates=pd.DatetimeIndex(["2023-01-03","2024-02-22","2024-02-23"])
    features=pd.DataFrame([dict(signal_date=d,ticker="T"+str(i),**dict.fromkeys(FEATURES,1.))
                          for d in dates for i in range(100) if not (d==dates[-1] and i==99)])
    identities=pd.DataFrame([dict(signal_date=d,cusip=str(i),ticker="T"+str(i),security_id="S"+str(i),
                           feature_available=not(d==dates[-1] and i==99),feature_ineligible_qualified=False)
                           for d in dates for i in range(100)])
    pool=pd.DataFrame([dict(signal_date=d,cusip=str(i),consensus_rank=i+1,quarter="2023Q4",source_snapshot_id="orig",
                     source_effective_at="2024-02-22T00:00:00Z") for d in dates[1:] for i in range(100)])
    observed=[]
    def ranked(f,schedule,members,ledger,models,columns):
        observed.append((schedule.copy(),members.copy()))
        rows=[]
        for s in schedule.itertuples():
            allowed=members.loc[members.snapshot_id.eq(s.snapshot_id)]
            valid=allowed.merge(f.loc[f.trade_date.eq(pd.Timestamp(s.effective_date))],["ticker"] if False else "inner",on="ticker")
            for number,r in enumerate(valid.itertuples(),1):
                rows.append(dict(target_date=s.effective_date,ticker=r.ticker,rank=number,score=float(number),universe_quarter="2023Q4"))
        return pd.DataFrame(rows),pd.DataFrame()
    monkeypatch.setattr(ranking,"ranked_predictions",ranked)
    flags,q,_=history.rank_history(features,identities,pool,dates,{},25)
    assert list(q.status)==["SOURCE_UNQUALIFIED_NO_HISTORICAL_POOL","QUALIFIED","SOURCE_UNQUALIFIED_IDENTITY_OR_ORIGINAL32"]
    assert set(flags.signal_date)==set(dates) and not flags.loc[flags.signal_date.eq(dates[0]),"new_buy_eligible"].any()
    identities.loc[(identities.signal_date==dates[-1]) & identities.cusip.eq("99"),"feature_ineligible_qualified"]=True
    _,q,_=history.rank_history(features,identities,pool,dates,{},25)
    assert q.iloc[-1].status=="QUALIFIED"
    assert len(observed[-1][1])==200 and observed[-1][0].universe_member_count.eq(100).all()


def test_metadata_incomplete_source_is_not_legal_feature_ineligibility():
    identity=pd.DataFrame([dict(signal_date=pd.Timestamp("2024-02-22"),cusip=str(i),ticker="T"+str(i),
        security_id="S"+str(i),feature_available=i!=99,feature_ineligible_qualified=False) for i in range(100)])
    assert history.metadata_qualified_dates(identity)==()
    identity.loc[99,"feature_ineligible_qualified"]=True
    assert history.metadata_qualified_dates(identity)==(pd.Timestamp("2024-02-22"),)


def task_source_receipt(tmp_path):
    from scripts.research.a2.training import stateful_inputs as inputs
    proof = tmp_path / "independent_review.json"
    proof.write_text(json.dumps(dict(task_id=history.TASK, status="PASS")), encoding="utf-8")
    sources = {name: dict(path=name + ".parquet", sha256="a" * 64) for name in ("features", "dated_identity")}
    receipt = dict(task_id=history.TASK, status="APPROVED_TASK_BOUNDED_ORIGINAL32_SOURCES",
                   cutoff_exclusive=history.CUTOFF, feature_columns=list(inputs.FEATURES),
                   source_refs=sources, approved_feature_sources=[history.TASK_RAW_FEATURE_TAG],
                   proof_refs=dict(independent=history.ref(proof)))
    path = tmp_path / "admission.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    m = dict(source_refs=sources, feature_source_admission_ref=history.ref(path))
    keys = pd.DataFrame(dict(feature_available=[True], feature_source=[history.TASK_RAW_FEATURE_TAG]))
    return m, receipt, path, keys


def test_task_source_admission_is_local_and_missing_receipt_rejected(tmp_path):
    from scripts.research.a2.training import stateful_inputs as inputs
    original = inputs.ALLOWED_SOURCES
    m, receipt, path, keys = task_source_receipt(tmp_path)
    allowed = history.admitted_feature_sources(m, keys)
    assert allowed == set(original) | {history.TASK_RAW_FEATURE_TAG}
    assert inputs.ALLOWED_SOURCES is original and history.TASK_RAW_FEATURE_TAG not in original
    with pytest.raises(ValueError, match="ROOT_TASK_FEATURE_SOURCE_ADMISSION_REQUIRED"):
        history.admitted_feature_sources(dict(source_refs=m["source_refs"]), keys)
    old_keys = pd.DataFrame(dict(feature_available=[True], feature_source=[original[0]]))
    assert history.admitted_feature_sources({}, old_keys) == set(original)


@pytest.mark.parametrize("fault", ["task", "status", "cutoff", "features", "feature_ref", "identity_ref", "tag", "proof", "hash"])
def test_unapproved_task_source_receipt_stops_prepare_before_model_decode(tmp_path, monkeypatch, fault):
    from copy import deepcopy
    import joblib
    from scripts.research.a2.training import base_conditioned_gross_run as runner
    m, receipt, path, keys = task_source_receipt(tmp_path)
    receipt = deepcopy(receipt)
    if fault == "task": receipt["task_id"] = "OTHER_TASK"
    elif fault == "status": receipt["status"] = "DRAFT"
    elif fault == "cutoff": receipt["cutoff_exclusive"] = "2025-01-01"
    elif fault == "features": receipt["feature_columns"] = receipt["feature_columns"][::-1]
    elif fault == "feature_ref": receipt["source_refs"]["features"]["sha256"] = "b" * 64
    elif fault == "identity_ref": receipt["source_refs"]["dated_identity"]["sha256"] = "b" * 64
    elif fault == "tag": receipt["approved_feature_sources"] = ["FAKE_OLD_GUARD_TAG"]
    elif fault == "proof": receipt["proof_refs"]["independent"]["sha256"] = "b" * 64
    path.write_text(json.dumps(receipt), encoding="utf-8")
    m["feature_source_admission_ref"] = history.ref(path)
    if fault == "hash": m["feature_source_admission_ref"]["sha256"] = "b" * 64
    m.update(manifest(), resource_owner_ref={})
    m["permits"]["prepare"] = True
    m["source_refs"]["calendar"] = dict(path="calendar")
    monkeypatch.setattr(runner, "resource_gate", lambda *args: None)
    monkeypatch.setattr(history, "bounded", lambda ref, *args, **kwargs:
                        pd.DataFrame(dict(trade_date=[pd.Timestamp(history.FIRST)])) if ref["path"] == "calendar" else keys)
    monkeypatch.setattr(joblib, "load", lambda *args: pytest.fail("model decode precedes rejected admission"))
    with pytest.raises(ValueError): history.prepare(m, tmp_path, SimpleNamespace())
    assert not (tmp_path / "derived/gross_history").exists()


def test_action_models_cache_only_one_call_preserves_day_base_head_order(monkeypatch):
    import joblib
    from scripts.research.a2.inference import consensus_paper, frozen_a94_actions
    dates = pd.DatetimeIndex(["2024-01-02", "2024-01-03"])
    flags = pd.DataFrame(dict(signal_date=dates, is_raw_top20=[True, True]))
    reads, scores = [], []
    nodes = {group: {family + "_" + kind + "_ref": dict(path=family + "-" + group + "-" + kind)
                    for family in ("elasticnet", "ridge") for kind in ("model", "scaler")}
             for group in ("ENTRY", "INCUMBENT")}
    def load(path):
        reads.append(path)
        return (SimpleNamespace(n_features_in_=2, transform=lambda x: x)
                if path.endswith("scaler") else SimpleNamespace(key=path))
    def frames(prefix, calendar, day):
        value = float(dates.get_loc(day) + 1)
        return {group: pd.DataFrame([dict(signal_date=day, ticker="SYNTH", security_id="SYNTH",
                   sample_id=str(day) + group, value=value, action_type=0.)]) for group in ("ENTRY", "INCUMBENT")}
    def predict(model, x):
        scores.append((float(x[0, 0]), model.key))
        return dict(mean=x[:, 0].copy())
    monkeypatch.setattr(history, "verify", lambda ref: ref["path"])
    monkeypatch.setattr(joblib, "load", load)
    monkeypatch.setattr(consensus_paper, "original_frames", frames)
    monkeypatch.setattr(consensus_paper, "predict_r10", predict)
    monkeypatch.setattr(frozen_a94_actions, "role_features", lambda role: ("value",))
    first = history.action_predictions(flags, dates, dict(nodes=nodes))
    expected = [(float(i + 1), family + "-" + group + "-model") for i in range(2)
                for family in ("elasticnet", "ridge") for group in ("ENTRY", "INCUMBENT")]
    assert scores == expected and len(reads) == len(set(reads)) == 8
    assert sum(path.endswith("model") for path in reads) == 4
    assert sum(path.endswith("scaler") for path in reads) == 4
    for base in history.BASES:
        assert list(first[base]) == list(dates)
        for day, rows in first[base].items():
            assert [row["source_order"] for row in rows] == [0, 1]
            assert [row["source_score"] for row in rows] == [float(dates.get_loc(day) + 1)] * 2
    second = history.action_predictions(flags, dates, dict(nodes=nodes))
    assert second == first and scores == expected * 2 and len(reads) == 16


def test_rank_preserves_exact_new_source_provenance_and_all_decision_values(monkeypatch):
    from scripts.research.a2.inference import historical_top40 as ranking
    from scripts.research.a2.training.stateful_inputs import FEATURES
    dates = pd.DatetimeIndex(["2023-01-03", "2024-02-22"])
    features = pd.DataFrame([dict(signal_date=d, ticker="T" + str(i), **dict.fromkeys(FEATURES, 1.))
                             for d in dates for i in range(100)])
    identities = pd.DataFrame([dict(signal_date=d, cusip=str(i), ticker="T" + str(i), security_id="S" + str(i),
                        feature_available=True, feature_ineligible_qualified=False) for d in dates for i in range(100)])
    pool = pd.DataFrame([dict(signal_date=dates[-1], cusip=str(i), consensus_rank=i+1, quarter="2023Q4",
                    source_snapshot_id="original", source_effective_at="2024-02-22T00:00:00Z") for i in range(100)])
    def ranked(f, schedule, members, ledger, models, columns):
        return pd.DataFrame([dict(target_date=dates[-1], ticker="T" + str(i), rank=i+1, score=float(i+1),
                                  universe_quarter="2023Q4") for i in range(100)]), pd.DataFrame()
    monkeypatch.setattr(ranking, "ranked_predictions", ranked)
    baseline, q0, c0 = history.rank_history(features, identities, pool, dates, {}, 25)
    keys = identities[["signal_date", "ticker", "security_id", "feature_available"]].copy()
    keys["feature_source"] = "FROZEN_RAW_A2_TRAINING_MATRIX_32"
    for number, tag in enumerate(history.KNOWN_TASK_RAW_FEATURE_TAGS):
        keys.loc[keys.signal_date.eq(dates[-1]) & keys.ticker.eq("T" + str(number)), "feature_source"] = tag
    tagged, q1, c1 = history.rank_history(features, identities, pool, dates, {}, 25, context_identity=keys)
    mask = tagged.signal_date.eq(dates[-1]) & tagged.ticker.isin(["T" + str(i) for i in range(len(history.KNOWN_TASK_RAW_FEATURE_TAGS))])
    assert set(tagged.loc[mask, "feature_source"]) == set(history.KNOWN_TASK_RAW_FEATURE_TAGS)
    for number, tag in enumerate(history.KNOWN_TASK_RAW_FEATURE_TAGS):
        assert tagged.loc[tagged.signal_date.eq(dates[-1]) & tagged.ticker.eq("T" + str(number)), "feature_source"].tolist() == [tag]
    assert tagged.loc[~mask, "feature_source"].equals(baseline.loc[~mask, "feature_source"])
    pd.testing.assert_frame_equal(tagged.drop(columns="feature_source"), baseline.drop(columns="feature_source"))
    pd.testing.assert_frame_equal(q1, q0)
    for empty in (False, True):
        unapproved = keys.copy()
        if empty: unapproved["feature_source"] = None
        else: unapproved.loc[unapproved.feature_source.isin(history.KNOWN_TASK_RAW_FEATURE_TAGS), "feature_available"] = False
        untouched, _, _ = history.rank_history(features, identities, pool, dates, {}, 25, context_identity=unapproved)
        pd.testing.assert_frame_equal(untouched, baseline)


def test_known_task_source_tags_require_exact_approved_coverage(tmp_path):
    from scripts.research.a2.training import stateful_inputs as inputs
    m, receipt, path, _ = task_source_receipt(tmp_path)
    tags = list(history.KNOWN_TASK_RAW_FEATURE_TAGS)
    keys = pd.DataFrame(dict(feature_available=[True] * len(tags), feature_source=tags))
    with pytest.raises(ValueError, match="ROOT_TASK_FEATURE_SOURCE_ADMISSION_REQUIRED"):
        history.admitted_feature_sources({}, keys)
    def update(approved):
        receipt["approved_feature_sources"] = approved
        path.write_text(json.dumps(receipt), encoding="utf-8")
        m["feature_source_admission_ref"] = history.ref(path)
    update(tags)
    assert history.admitted_feature_sources(m, keys) == set(inputs.ALLOWED_SOURCES) | set(tags)
    update(tags[:4])
    with pytest.raises(ValueError, match="TAGS_UNAPPROVED"):
        history.admitted_feature_sources(m, keys)
    assert history.admitted_feature_sources(m, keys.iloc[:4]) == set(inputs.ALLOWED_SOURCES) | set(tags[:4])
    update(tags[:2])
    with pytest.raises(ValueError, match="TAGS_UNAPPROVED"):
        history.admitted_feature_sources(m, keys)
    assert history.admitted_feature_sources(m, keys.iloc[:2]) == set(inputs.ALLOWED_SOURCES) | set(tags[:2])
    for bad in ([], tags + [tags[0]], [inputs.ALLOWED_SOURCES[0]], ["FAKE_OLD_GUARD_TAG"]):
        update(bad)
        with pytest.raises(ValueError, match="EXACT_TASK_FEATURE_SOURCE_TAG_REQUIRED"):
            history.admitted_feature_sources(m, keys)



def _synthetic_source_pool(dates=("2024-02-22", "2024-02-23"), count=100):
    """Metadata and fabricated vectors; the original ranking owner is reused."""
    from scripts.research.a2.training.stateful_inputs import FEATURES
    calendar = pd.DatetimeIndex(dates)
    identities = pd.DataFrame([dict(signal_date=day, cusip="C" + str(i), ticker="T" + str(i),
        security_id="S" + str(i), feature_available=True, feature_ineligible_qualified=False,
        feature_source="FROZEN_RAW_A2_TRAINING_MATRIX_32") for day in calendar for i in range(count)])
    features = pd.DataFrame([dict(signal_date=day, ticker="T" + str(i),
        **{name: float(count - i) if name == FEATURES[0] else 1. for name in FEATURES})
        for day in calendar for i in range(count)])
    pool = pd.DataFrame([dict(signal_date=day, cusip="C" + str(i), consensus_rank=i + 1,
        quarter="2023Q4", source_snapshot_id="synthetic_original",
        source_effective_at=day.strftime("%Y-%m-%dT00:00:00Z")) for day in calendar for i in range(count)])
    return calendar, identities, features, pool


def _rank_synthetic_source_pool(monkeypatch, dates, identities, features, pool, exclusions=()):
    from scripts.research.a2.inference import historical_top40 as ranking
    original = ranking.ranked_predictions
    model = SimpleNamespace(predict=lambda x: x[:, 0].copy())
    models = dict(artifacts={str(year): dict(path="synthetic-model", sha256="synthetic-hash",
        labelmax=str(year - 1) + "-12-31") for year in set(dates.year)})
    seen = []
    def original_with_fake_model(f, schedule, members, ledger, raw, columns):
        seen.append(dict(features=f.copy(), schedule=schedule.copy(), members=members.copy()))
        return original(f, schedule, members, ledger, raw, columns, model_loader=lambda _: model)
    monkeypatch.setattr(ranking, "digest", lambda _: "synthetic-hash")
    monkeypatch.setattr(ranking, "ranked_predictions", original_with_fake_model)
    result = history.rank_history(features, identities, pool, dates, models, 25,
        context_identity=identities, source_exclusion_keys=exclusions)
    return (*result, seen)


def test_pool_source_exclusion_is_date_specific_and_separate_from_warmup():
    old = pd.Timestamp("2024-02-22")
    later = pd.Timestamp("2024-02-23")
    # The future row is fabricated identity metadata; no financial values exist.
    future = pd.Timestamp("2026-01-02")
    rows = pd.DataFrame(dict(signal_date=[old, later, future, old, old],
        cusip=["C0", "C0", "C0", "WARM", "UNKNOWN"],
        feature_available=[False, True, True, False, None],
        feature_ineligible_qualified=[False, False, False, True, False]))
    keys = {(old, "C0"), (old, "WARM"), (old, "UNKNOWN")}
    eligible, warmup, excluded = history.pool_source_masks(rows, keys)
    assert eligible.tolist() == [False, True, True, False, False]
    assert warmup.tolist() == [False, False, False, True, False]
    assert excluded.tolist() == [True, False, False, False, False]
    assert not (eligible & warmup | eligible & excluded | warmup & excluded).any()
    assert history.source_exclusions_from_manifest({}, rows) == frozenset()


def test_unlisted_missing_source_keeps_date_unqualified_and_cannot_buy(monkeypatch):
    dates, identity, features, pool = _synthetic_source_pool()
    bad = identity.signal_date.eq(dates[0]) & identity.ticker.isin(["T0", "T1"])
    identity.loc[bad, "feature_available"] = False
    keys = {(dates[0], "C0")}
    assert history.metadata_qualified_dates(identity, keys) == (dates[1],)
    flags, qualifications, _, _ = _rank_synthetic_source_pool(
        monkeypatch, dates, identity, features, pool, keys)
    assert qualifications.status.tolist() == ["SOURCE_UNQUALIFIED_IDENTITY_OR_ORIGINAL32", "QUALIFIED"]
    assert qualifications.unexplained_count.tolist() == [1, 0]
    assert not flags.loc[flags.signal_date.eq(dates[0]), "new_buy_eligible"].any()


@pytest.mark.parametrize("count, eligible_count, ready", [(100, 20, True), (100, 19, False),
                                                          (99, 99, False), (101, 101, False)])
def test_source_exclusion_keeps_nominal100_and_original_minimum20(count, eligible_count, ready):
    dates, identity, _, _ = _synthetic_source_pool(("2024-02-22",), count)
    unavailable = identity.index >= eligible_count
    identity.loc[unavailable, "feature_available"] = False
    identity.loc[unavailable, "feature_ineligible_qualified"] = True
    keys = set()
    if count > eligible_count:
        identity.loc[eligible_count, "feature_ineligible_qualified"] = False
        keys.add((dates[0], "C" + str(eligible_count)))
    assert history.metadata_qualified_dates(identity, keys) == ((dates[0],) if ready else ())


def test_rank_excludes_finite_missing_cell_without_excluding_same_stock_other_day(monkeypatch):
    dates, identity, features, pool = _synthetic_source_pool()
    missing = identity.signal_date.eq(dates[0]) & identity.ticker.eq("T0")
    warm = identity.signal_date.eq(dates[0]) & identity.ticker.eq("T1")
    identity.loc[missing | warm, "feature_available"] = False
    identity.loc[warm, "feature_ineligible_qualified"] = True
    features = features.loc[~(features.signal_date.eq(dates[0]) & features.ticker.eq("T1"))].copy()
    keys = {(dates[0], "C0")}
    flags, qualifications, coverage, seen = _rank_synthetic_source_pool(
        monkeypatch, dates, identity, features, pool, keys)
    assert history.metadata_qualified_dates(identity, keys) == tuple(
        qualifications.loc[qualifications.status.eq("QUALIFIED"), "signal_date"])
    assert qualifications.nominal_count.tolist() == [100, 100]
    assert qualifications.eligible_count.tolist() == [98, 100]
    assert qualifications.warmup_count.tolist() == [1, 0]
    assert qualifications.task_excluded_count.tolist() == [1, 0]
    assert qualifications.unexplained_count.tolist() == [0, 0]
    scored_inputs = seen[0]["features"]
    assert not (scored_inputs.trade_date.eq(dates[0]) & scored_inputs.ticker.eq("T0")).any()
    assert (scored_inputs.trade_date.eq(dates[1]) & scored_inputs.ticker.eq("T0")).any()
    omitted = flags.loc[flags.signal_date.eq(dates[0]) & flags.ticker.eq("T0")]
    assert omitted.empty or not omitted[["is_raw_top20", "new_buy_eligible", "is_max_group"]].any().any()
    valid = flags.loc[flags.signal_date.eq(dates[1]) & flags.ticker.eq("T0")]
    assert valid.new_buy_eligible.tolist() == [True]
    assert flags.groupby("signal_date").is_raw_top20.sum().tolist() == [20, 20]
    assert coverage.universe_member_count.tolist() == [100, 100]
    assert coverage.eligible_count.tolist() == [98, 100]
    assert seen[0]["schedule"].mapped_count.eq(100).all()
    assert seen[0]["members"].groupby("snapshot_id").size().tolist() == [100, 100]


def test_source_exclusion_does_not_backfill_with_101st_candidate(monkeypatch):
    from scripts.research.a2.training.stateful_inputs import FEATURES
    dates, identity, features, pool = _synthetic_source_pool(("2024-02-22",))
    identity.loc[identity.ticker.eq("T0"), "feature_available"] = False
    outsider = pd.DataFrame([dict(signal_date=dates[0], ticker="OUT101", **dict.fromkeys(FEATURES, 1000.))])
    features = pd.concat([features, outsider], ignore_index=True)
    flags, qualifications, coverage, seen = _rank_synthetic_source_pool(
        monkeypatch, dates, identity, features, pool, {(dates[0], "C0")})
    assert qualifications.nominal_count.tolist() == [100]
    assert coverage.universe_member_count.tolist() == [100] and coverage.eligible_count.tolist() == [99]
    assert not flags.loc[flags.ticker.eq("OUT101"), ["is_raw_top20", "new_buy_eligible", "is_max_group"]].any().any()
    assert "OUT101" not in set(seen[0]["members"].ticker)
    assert flags.is_raw_top20.sum() == 20


def test_prepare_success_preserves_identity_keys_and_releases_wide_rank_inputs(tmp_path, monkeypatch):
    """Exercise successful serialization; weakrefs detect rank-input overlap."""
    import weakref
    import joblib
    from scripts.research.a2.training import base_conditioned_gross_run as runner, stateful_inputs
    from scripts.storage import storage_r2a
    day = pd.Timestamp("2023-01-04")
    monkeypatch.setattr(history, "START", str(day.date()))
    calendar = pd.DatetimeIndex([history.FIRST, day])
    keys = pd.DataFrame([dict(signal_date=day, ticker="TOY", security_id="SYNTHETIC",
                             feature_available=True, feature_source="SYNTHETIC")])
    identity = keys.assign(cusip="SYNTHETIC")
    features = keys[["signal_date", "ticker"]].assign(**dict.fromkeys(stateful_inputs.FEATURES, 1.))
    pool = pd.DataFrame([dict(ticker="TOY")])
    flags = keys[["signal_date", "ticker", "security_id"]].copy()
    qualification = pd.DataFrame([dict(signal_date=day, status="QUALIFIED",
                                      task_excluded_count=0, eligible_count=1)])
    refs = {}
    sources = {name:dict(synthetic=name) for name in
               ("calendar", "features", "dated_identity", "raw_quotes", "raw_equivalence",
                "account_source", "bounded_event_binding", "model_bundle")}
    def bounded(source, columns, date_column, **kwargs):
        key = source["synthetic"]
        if key == "calendar":
            return pd.DataFrame(dict(trade_date=calendar))
        if key == "features":
            result = (keys if "feature_available" in columns else features)[columns].copy()
            if "feature_available" not in columns:
                refs["features"] = weakref.ref(result)
            return result
        if key == "dated_identity":
            result = identity[columns].copy(); refs["identity"] = weakref.ref(result); return result
        assert key == "raw_quotes"
        return pd.DataFrame([dict(trade_date=day, ticker="TOY", open=1., close=1.)])[columns]
    def read_pool(_):
        result = pool.copy(); refs["pool"] = weakref.ref(result); return result
    def rank(*args, **kwargs):
        pd.testing.assert_frame_equal(kwargs["context_identity"], keys)
        return flags, qualification, {}
    def action_predictions(*args):
        assert all(ref() is None for ref in refs.values())
        return {"synthetic":True}
    documents = {
        "model_bundle":{}, "source_preparation":dict(status="BOUNDED_TYPED_SOURCES_READY",
            source_refs={k:sources[k] for k in ("account_source", "bounded_event_binding")},
            typed_event_ref=dict(synthetic="typed_event")),
        "typed_event":dict(synthetic=True), "bounded_event_binding":dict(event_records=[])}
    monkeypatch.setattr(history, "bounded", bounded)
    monkeypatch.setattr(history, "read_pool", read_pool)
    monkeypatch.setattr(history, "rank_history", rank)
    monkeypatch.setattr(history, "action_predictions", action_predictions)
    monkeypatch.setattr(history, "admitted_feature_sources", lambda *args:{"SYNTHETIC"})
    monkeypatch.setattr(history, "metadata_qualified_dates", lambda *args:[day])
    monkeypatch.setattr(history, "doc", lambda reference, **kwargs:documents[reference["synthetic"]])
    monkeypatch.setattr(runner, "resource_gate", lambda *args:dict(synthetic=True))
    monkeypatch.setattr(runner, "verify_raw_models", lambda *args:None)
    def put(path, value):
        assert path.resolve().is_relative_to(tmp_path.resolve())
        path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(storage_r2a, "write_json_atomic", put)
    (tmp_path / "derived").mkdir()
    m = manifest()
    m.update(permits=dict(prepare=True), source_refs=sources, resource_owner_ref={},
             dated_identity_columns=list(identity), raw_model_manifest_refs={}, pool_institution_count=25,
             source_preparation_ref=dict(synthetic="source_preparation"), _manifest_ref=dict(synthetic="manifest"))
    result = history.prepare(m, tmp_path, SimpleNamespace())
    assert result["status"] == "PREPARED_BOUNDED_HISTORY_PENDING_ACCOUNT_RELEASE"
    payload = joblib.load(result["prepared_ref"]["path"])
    pd.testing.assert_frame_equal(payload["identities"], keys)
    pd.testing.assert_frame_equal(payload["flags"], flags)
    assert payload["action_packets"] == {"synthetic":True}
    assert result["real_fits"] == result["account_paths"] == 0
