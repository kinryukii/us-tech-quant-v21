"""Finite synthetic current-paper extension; no real data/model/account access."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from scripts.common.storage_paths import StoragePaths
from scripts.research.a2.inference import consensus_paper as c
from moomoo_component import applied_source as applied

SID = "R6_DURATION_TREE"
DAY = "2026-10-12"
BASE_CLOCK = "2026-10-12T21:00:00+00:00"
OBSERVED = "2026-10-13T05:00:00+00:00"  # True next NY day is deliberately retained.


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf8")
    return c.reference(path)


def publication(tmp_path):
    roots = {name: tmp_path / name for name in ("repo_root", "data_root", "cache_root", "daily_root", "backtest_root", "results_root", "envs_root")}
    paths = StoragePaths(**roots)
    flags = save(tmp_path / "flags.json", {})
    pool = save(tmp_path / "pool.json", {})
    ext = save(tmp_path / "extension.json", {})
    source = dict(schema="CURRENT_R6_PROBE_SOURCE_V1", status="BLOCKED", signal_date=DAY,
        decision_as_of=OBSERVED, flags_ref=flags, source_bundle_ref=pool, probe_ref=None,
        qualification_ref=None, reason="SYNTHETIC_SOURCE_NOT_READY")
    base = dict(schema=c.SCHEMA, signal_date=DAY, decision_as_of=BASE_CLOCK, pool_contract=c.POOL,
        flags_ref=flags, source_bundle_ref=pool, source_extension_ref=ext, model_fit_calls=0,
        label_columns_decoded=0, input_refs={"current": flags, "ENTRY": flags, "INCUMBENT": flags, "GROSS": flags},
        strategy_status={sid: {"status": "READY"} for sid in c.NEW_IDS})
    base_ref = save(paths.daily_root / "A2_consensus_paper/inputs" / DAY / "base.json", base)
    save(paths.daily_root / "A2_consensus_paper/latest.json", base_ref)
    return paths, base, base_ref, source


def test_capability_is_explicit_and_unknown_does_not_fall_into_r7():
    assert c.PAPER_CURRENT_IDS == (*c.NEW_IDS, SID)
    assert len(c.NEW_IDS) == 3 and len(applied.ACTIVE_STRATEGY_IDS) == 5
    assert SID in applied.STRATEGY_IDS and "R6_BUY_NEURAL" not in applied.STRATEGY_IDS
    assert SID not in applied.HGB_RESET_STRATEGY_IDS and SID not in applied.ACTIVE_STRATEGY_IDS
    with pytest.raises(ValueError, match="EXACT_CURRENT_CANDIDATE"):
        c.frozen_states(SimpleNamespace(), "R6_BUY_NEURAL")


def test_opt_in_blocked_sidecar_preserves_original_default_bytes(tmp_path):
    paths, base, base_ref, source = publication(tmp_path)
    pointer = paths.daily_root / "A2_consensus_paper/latest.json"
    before = (Path(base_ref["path"]).read_bytes(), pointer.read_bytes())
    with patch.object(c, "_duration_prefix", side_effect=AssertionError("no source scan")), patch.object(c, "validate_extension"):
        extension = c.publish_duration_extension(paths, base, base_ref, source)
        old, old_ref = c.load_publication(paths, DAY, OBSERVED)
        current, current_ref = c.load_publication(paths, DAY, OBSERVED, paper_current=True)
    assert (Path(base_ref["path"]).read_bytes(), pointer.read_bytes()) == before
    assert old == base and old_ref == base_ref and SID not in old["strategy_status"]
    assert current["strategy_status"][SID] == {"status": "BLOCKED", "reason": source["reason"]}
    assert current["decision_as_of"] == OBSERVED and current_ref == extension["publication_ref"]
    assert current["input_refs"] == base["input_refs"]
    with patch.object(c, "_prepare_duration_frame", side_effect=AssertionError("unchanged producer must reuse")):
        again = c.publish_duration_extension(paths, base, base_ref, source)
    assert again["reused"] is True and again["publication_ref"] == current_ref


def test_same_day_optional_publish_never_rebuilds_original_three(tmp_path):
    paths, base, base_ref, source = publication(tmp_path)
    base["source_bundle_ref"] = dict(base["source_bundle_ref"], sha256=c.BUNDLE_SHA)
    source["source_bundle_ref"] = base["source_bundle_ref"]
    bundle = dict(schema="CONSENSUS_VARIANT_INPUT_BUNDLE_R1", pool_variant_id="TOP100", selection_rule="MANAGER_COUNT_WEIGHT_SUM")
    with patch.object(c, "metadata", side_effect=lambda ref, fields: bundle if ref == base["source_bundle_ref"] else {"signal_date": DAY}),          patch.object(c, "load_publication", return_value=(base, base_ref)), patch.object(c, "validate_extension"),          patch.object(c, "resource_check", side_effect=AssertionError("no model/full-input resource phase")),          patch.object(c, "original_frames", side_effect=AssertionError("no old3 rebuild")),          patch.object(c, "bounded_frame", side_effect=AssertionError("no original-prefix scan")):
        result = c.publish_inputs(paths, flags_ref=base["flags_ref"], source_bundle_ref=base["source_bundle_ref"],
            signal_date=DAY, decision_as_of=BASE_CLOCK, source_extension_ref=base["source_extension_ref"], r6_probe_source=source)
    assert result["paper_current_extension"]["status"] == "BLOCKED"
    assert {k: v for k, v in result.items() if k != "paper_current_extension"} == base


@pytest.mark.parametrize("field", ["flags_ref", "source_bundle_ref", "signal_date", "decision_as_of"])
def test_candidate_source_drift_or_backdating_rejects(tmp_path, field):
    paths, base, ref, source = publication(tmp_path)
    source[field] = "2026-10-11T21:00:00Z" if field == "decision_as_of" else "CHANGED"
    with pytest.raises((ValueError, TypeError)):
        c.publish_duration_extension(paths, base, ref, source)
    assert not (paths.daily_root / "A2_consensus_paper/duration_latest.json").exists()


def test_sidecar_real_clock_and_base_identity_are_rechecked(tmp_path):
    paths, base, ref, source = publication(tmp_path)
    c.publish_duration_extension(paths, base, ref, source)
    with pytest.raises(ValueError, match="OBSERVATION_CLOCK"):
        c._load_duration_publication(paths, base, ref, BASE_CLOCK)
    with pytest.raises(ValueError, match="IDENTITY_CHANGED"):
        c._load_duration_publication(paths, dict(base, flags_ref={}), ref, OBSERVED)


def test_ready_reuse_revalidates_qualified_frame_before_accepting(tmp_path):
    paths, base, ref, source = publication(tmp_path)
    source.update(status="READY", probe_ref=base["flags_ref"], qualification_ref=base["flags_ref"])
    frame = pd.DataFrame({"signal_date": [pd.Timestamp(DAY)], "sample_id": ["synthetic"]})
    qualification = dict(input_commitment={"synthetic": "frame"}, source_refs={"flags": base["flags_ref"], "pool": base["source_bundle_ref"]})
    c.publish_duration_extension(paths, base, ref, source,
        prepared=dict(status="READY", decision_as_of=OBSERVED, frame=frame, qualification=qualification))
    with patch.object(c, "_qualified_duration_frame", side_effect=ValueError("SYNTHETIC_FRAME_CHANGED")) as checked:
        with pytest.raises(ValueError, match="FRAME_CHANGED"):
            c.publish_duration_extension(paths, base, ref, source)
    checked.assert_called_once()


def duration_model_fixture(tmp_path):
    from scripts.research.a2.training import stateful_decision as decision, stateful_decision_models as owner
    model_path = tmp_path / "a/b/c/model.joblib"; model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"synthetic-placeholder-never-deserialized")
    manifest = save(tmp_path / "input_manifest.json", {"synthetic": True})
    features = tuple(decision.SINGLE) + tuple(col + "__missing" for col in decision.SINGLE)
    tup = dict(slot=dict(stage="R6", objective="duration", learner="tree", year=2025, slot_id="duration_tree_2025"),
        seed=owner.SEED, calibration_start="2024-01-01", training_signal_max="2023-12-01", training_maturity_max="2023-12-08",
        contract_sha256="c" * 64, input_manifest_sha256=manifest["sha256"], feature_order=list(features))
    receipt = dict(status="TRAINED", year=2025, objective="duration", learner="tree", seed=owner.SEED,
        model_path=str(model_path), model_sha256=c.reference(model_path)["sha256"], scientific_tuple=tup,
        scientific_tuple_sha256=hashlib.sha256(json.dumps(tup, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest())
    receipt_ref = save(model_path.with_name("receipt.json"), receipt)
    contract_ref = save(tmp_path / "contract.json", dict(specification_sha256="c" * 64, input_manifest_sha256=manifest["sha256"]))
    states = {"duration_tree_2025": dict(model_ref=c.reference(model_path), receipt_ref=receipt_ref,
        r6_contract_ref=contract_ref, metadata_row=dict(slot_id="duration_tree_2025"))}
    frame = pd.DataFrame([{**{col: .01 for col in decision.SINGLE}, "signal_date": pd.Timestamp(DAY),
        "ticker": "T" + str(i), "security_id": "S" + str(i), "sample_id": "s" + str(i), "cohort_age_sessions": age}
        for i, age in enumerate((0, 7, 14, 1))])
    return owner, features, states, frame, receipt


def test_duration_uses_original_native_probability_decoder_and_releases_model(tmp_path):
    import joblib
    from scripts.research.a2.training import stateful_final_action_packets as packets
    owner, features, states, frame, _ = duration_model_fixture(tmp_path)
    probabilities = np.array([.5, .50001, .8, .9])
    predicted_shapes = []
    def native_predict(model, x):
        predicted_shapes.append(x.shape)  # Do not retain the model in mock call history.
        return {"p_failure": probabilities}
    with patch.object(c, "_qualified_duration_frame", return_value=frame), patch.object(c, "frozen_states", return_value=states),          patch.object(c, "resource_check"), patch.object(joblib, "load", side_effect=lambda path: owner.Model("duration", "tree", None, None, features, (), {})) as load,          patch.object(owner, "predict", new=native_predict):
        records, models = c.duration_actions(SimpleNamespace(), {})
    expected = [packets.decode_r6_row({**row, "p_failure": float(probabilities[i])}, "duration", i) for i, row in enumerate(frame.to_dict("records"))]
    assert records == expected and [row["kind"] for row in records] == ["REFERENCE", "SELL", "SELL", "REFERENCE"]
    assert models == {"duration_tree_2025": states["duration_tree_2025"]["model_ref"]}
    load.assert_called_once(); assert len(predicted_shapes) == 1


@pytest.mark.parametrize("fault", ["qualification", "tuple_digest", "training_boundary"])
def test_qualification_or_frozen_receipt_fault_precedes_model_load(tmp_path, fault):
    import joblib
    owner, features, states, frame, receipt = duration_model_fixture(tmp_path)
    if fault == "tuple_digest": receipt["scientific_tuple_sha256"] = "0" * 64
    if fault == "training_boundary":
        receipt["scientific_tuple"]["training_maturity_max"] = "2026-01-01"
        receipt["scientific_tuple_sha256"] = hashlib.sha256(json.dumps(receipt["scientific_tuple"], sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    states["duration_tree_2025"]["receipt_ref"] = save(Path(states["duration_tree_2025"]["receipt_ref"]["path"]), receipt)
    with patch.object(c, "_qualified_duration_frame", side_effect=ValueError("SYNTHETIC_QUALIFICATION") if fault == "qualification" else None, return_value=frame),          patch.object(c, "frozen_states", return_value=states), patch.object(joblib, "load", side_effect=AssertionError("model must not load")):
        with pytest.raises(ValueError): c.duration_actions(SimpleNamespace(), {})


def test_status_keeps_duration_blocked_and_old_three_independent():
    source = applied._CanonicalSource.__new__(applied._CanonicalSource); source.paths = SimpleNamespace()
    base, ref = {"synthetic": True}, {"path": "synthetic", "sha256": "a" * 64}
    calls = []
    def load(paths, day, asof, **options):
        calls.append(options)
        if options: raise ValueError("DURATION_MATURE_PROBE_MISSING")
        return base, ref
    result = {"signal_date": DAY, "source_refs": {}, "strategy_status": {"RAW_A2": {"status": "READY"}}}
    with patch.object(c, "load_publication", side_effect=load), patch.object(c, "candidate_source_refs", return_value={}):
        result = source._candidate_status_refs(result, OBSERVED)
    assert calls == [{}, {"paper_current": True}]
    assert result["strategy_status"][SID]["status"] == "BLOCKED"
    assert all(result["strategy_status"][sid]["status"] == "READY" for sid in c.NEW_IDS)
    assert result["strategy_status"]["RAW_A2"]["status"] == "READY"
    with patch.object(c, "load_publication", side_effect=ValueError("BASE_SOURCE_CHANGED")):
        result = source._candidate_status_refs(result, OBSERVED)
    assert all(result["strategy_status"][sid]["status"] == "BLOCKED" for sid in c.PAPER_CURRENT_IDS)


def test_duration_new_plan_failure_preserves_existing_peer_and_opt_in():
    source = applied._CanonicalSource.__new__(applied._CanonicalSource); source.paths = SimpleNamespace()
    source.close_hours = {DAY: ("2026-10-12T13:30:00Z", "2026-10-12T20:00:00Z"), "2026-10-13": ("2026-10-13T13:30:00Z", "2026-10-13T20:00:00Z")}
    source._calendar = lambda now: (DAY, list(source.close_hours), source.close_hours)
    result = dict(signal_date=DAY, plans={"RAW_A2": {"status": "READY"}}, execution_date="2026-10-13", source_refs={})
    state = dict(weights={}, cash_weight=1., signal_date=DAY, valuation_basis="SIGNAL_CLOSE")
    with patch.object(c, "load_publication", side_effect=ValueError("MATURE_PROBES_MISSING")) as load:
        result = source._new_plans(result, {SID: state, "RAW_A2": {}}, OBSERVED)
    assert result["plans"] == {"RAW_A2": {"status": "READY"}}
    assert result["strategy_status"][SID]["status"] == "BLOCKED"
    assert load.call_args.kwargs == {"paper_current": True}


def test_duration_sell_only_real_held_and_removed_pool_holds_exact_units():
    from test_consensus_paper import fixture
    from scripts.research.a2.training import stateful_final_action_packets as packets
    prefix, calendar = fixture(); current = prefix.loc[prefix.signal_date.eq(calendar[-1])].copy()
    current.loc[current.ticker.eq("T21"), ["raw_a2_rank", "security_id"]] = [np.nan, None]
    records = [packets.decode_r6_row(dict(ticker=t, security_id="S"+t[1:], sample_id=t, cohort_age_sessions=7, p_failure=.8), "duration", i)
        for i, t in enumerate(("T0", "T1"))]
    doc = dict(signal_date=str(calendar[-1].date()), strategy_status={SID: {"status": "READY"}}, input_refs={"current": {}})
    state = dict(weights={"T0": .1, "T21": .1}, cash_weight=.8, units={"T0": 5, "T21": 7}, security_ids={"T0": "S0", "T21": "S21"})
    with patch.object(c, "verify", return_value=Path("synthetic")), patch.object(pd, "read_parquet", return_value=current), \
         patch.object(c, "duration_actions", return_value=(records, {})), patch.object(c, "_duration_source_refs", return_value={}):
        plan = c.infer_application(SimpleNamespace(), SID, state, doc)
    rows = {row["ticker"]: row for row in plan["rows"]}
    assert rows["T0"]["action"] == "SELL" and rows["T0"]["target_weight"] == 0
    assert rows["T1"]["target_weight"] > 0  # A proxy SELL cannot exit an unheld symbol.
    assert rows["T21"]["action"] == "HOLD" and rows["T21"]["exact_hold_units"] == 7
    assert rows["T21"]["target_weight"] == .1 and rows["T21"]["security_id"] == "S21"
    assert plan["model_fit_calls"] == 0 and plan["policy_id"] == SID


@pytest.mark.parametrize("fault", ["missing_clock", "invalid_clock", "runtime", "memory", "sidecar_write"])
def test_first_publish_optional_failure_commits_old_three_only(tmp_path, fault):
    paths, base, _, source = publication(tmp_path)
    (paths.daily_root / "A2_consensus_paper/latest.json").unlink()
    pool = dict(base["source_bundle_ref"], sha256=c.BUNDLE_SHA); source["source_bundle_ref"] = pool
    if fault == "missing_clock": source.pop("decision_as_of")
    if fault == "invalid_clock": source["decision_as_of"] = "NOT_A_CLOCK"
    if fault in ("runtime", "memory"): source["status"] = "READY"
    rows = []
    for i in range(40):
        rows.append(dict(signal_date=pd.Timestamp(DAY), ticker="T"+str(i), security_id="S"+str(i),
            is_raw_top20=i<20, raw_top20_set_complete=True, raw_a2_rank=i+1))
    current = pd.DataFrame(rows); prior = current.assign(signal_date=pd.Timestamp("2023-01-03"))
    calendar = pd.DataFrame({"trade_date": [pd.Timestamp("2023-01-03")]})
    bundle = dict(schema="CONSENSUS_VARIANT_INPUT_BUNDLE_R1", pool_variant_id="TOP100", selection_rule="MANAGER_COUNT_WEIGHT_SUM",
        prehistory_ref={}, prehistory_calendar_ref={})
    proof = dict(parent_source_role="FROZEN_HISTORY_RESEARCH_OBSERVATIONS", parent_source_completeness_unknown=True,
        parent_historical_available_at_bound=False, current_day_proofs=[dict(ranked_pool_security_ids=current.security_id.tolist())])
    oldframe = pd.DataFrame({"synthetic_feature": [.1]})
    from scripts.research.a2.inference import current_r6_probes as probe_owner
    def build(**kwargs):
        pointer = paths.daily_root / "A2_consensus_paper/latest.json"
        assert pointer.exists(), "optional source work must follow original base commit"
        raise MemoryError("synthetic candidate memory") if fault == "memory" else RuntimeError("synthetic candidate failure")
    original_publish = c.publish_duration_extension
    def publish(*args, **kwargs):
        if fault == "sidecar_write":
            assert (paths.daily_root / "A2_consensus_paper/latest.json").exists()
            raise OSError("synthetic sidecar write")
        return original_publish(*args, **kwargs)
    with patch.object(c, "metadata", return_value=bundle), patch.object(c, "validate_extension", return_value=proof), \
         patch.object(c, "bounded_frame", side_effect=[current, prior, calendar]), patch.object(c, "resource_check"), \
         patch.object(c, "original_frames", return_value={"ENTRY": oldframe, "INCUMBENT": oldframe}), \
         patch.object(c, "gross_frame", return_value=oldframe), patch.object(probe_owner, "build_current_duration_frame", side_effect=lambda *args, **kwargs: build(**kwargs)), \
         patch.object(c, "publish_duration_extension", side_effect=publish):
        result = c.publish_inputs(paths, flags_ref=base["flags_ref"], source_bundle_ref=pool, signal_date=DAY,
            decision_as_of=BASE_CLOCK, source_extension_ref=base["source_extension_ref"], r6_probe_source=source)
    published_ref = json.loads((paths.daily_root / "A2_consensus_paper/latest.json").read_text(encoding="utf8"))
    published = json.loads(c.verify(published_ref).read_text(encoding="utf8"))
    assert published["status"] == "READY" and set(published["strategy_status"]) == set(c.NEW_IDS)
    assert all(status["status"] == "READY" for status in published["strategy_status"].values())
    assert "paper_current_extension" not in published and result["paper_current_extension"]["status"] == "BLOCKED"
    assert {k: v for k, v in result.items() if k != "paper_current_extension"} == published


def test_original_publication_error_is_not_swallowed_by_optional_boundary(tmp_path):
    paths, base, _, source = publication(tmp_path)
    with patch.object(c, "metadata", side_effect=ValueError("ORIGINAL_POOL_BAD")):
        with pytest.raises(ValueError, match="ORIGINAL_POOL_BAD"):
            c.publish_inputs(paths, flags_ref=base["flags_ref"], source_bundle_ref=dict(base["source_bundle_ref"], sha256=c.BUNDLE_SHA),
                signal_date=DAY, decision_as_of=BASE_CLOCK, source_extension_ref=base["source_extension_ref"], r6_probe_source=source)


def _old_bounded_reference(ref, columns, date_column, first, last):
    """Pre-optimization contract, retained only for finite synthetic comparison."""
    import pyarrow.dataset as ds
    path = c.verify(ref); dataset = ds.dataset(path, format="parquet")
    c.need(set(columns) <= set(dataset.schema.names), "CONSENSUS_PROJECTED_INPUT_FIELDS_REQUIRED")
    rule = (ds.field(date_column) >= pd.Timestamp(first).to_pydatetime()) & (ds.field(date_column) <= pd.Timestamp(last).to_pydatetime())
    parts = []; count = 0
    for batch in dataset.scanner(columns=list(columns), filter=rule, batch_size=4096, use_threads=False).to_batches():
        count += batch.num_rows
        c.need(count <= 600000, "CONSENSUS_PREFIX_ROW_LIMIT")
        parts.append(batch.to_pandas())
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=columns)


@pytest.mark.parametrize("kind", ["plain", "empty_filter", "empty_file", "stored_index", "dictionary_same", "dictionary_different"])
def test_bounded_projection_preserves_complete_frame_and_empty_dtypes(tmp_path, kind):
    import pyarrow as pa
    import pyarrow.parquet as pq
    size = 9001
    frame = pd.DataFrame(dict(signal_date=pd.to_datetime("2024-01-01")+pd.to_timedelta(np.arange(size)%11, unit="D"),
        float64=np.linspace(-1, 1, size), float32=np.asarray(np.arange(size)%5, dtype=np.float32),
        value=pd.array(np.arange(size), dtype="Int64"), flag=np.arange(size)%2==0,
        nullbool=pd.Series(np.arange(size)%2==0).mask(np.arange(size)%3==0),
        all_null=[None]*size, name=["S"+str(i%53) for i in range(size)],
        clock=pd.to_datetime("2024-01-01",utc=True)+pd.to_timedelta(np.arange(size),unit="s")))
    frame.loc[np.arange(size)%7==0,"value"] = pd.NA
    if kind == "empty_file": frame = frame.iloc[:0]
    if kind == "stored_index": frame.index = pd.Index(["i"+str(i) for i in range(len(frame))],name="stored_observation")
    path = tmp_path / "synthetic.parquet"
    if kind.startswith("dictionary"):
        path = tmp_path / "fragments";path.mkdir()
        for i in range(2):
            part = frame.iloc[i*4500:(i+1)*4500].copy()
            categories = ["A", "B"] if kind == "dictionary_same" else ["A" if i == 0 else "B"]
            part["category"] = pd.Categorical([categories[i%len(categories)]]*len(part),categories=categories)
            part.to_parquet(path / (str(i)+".parquet"),index=False,row_group_size=2000)
        ref = {"path": str(path), "sha256": "synthetic-directory"}
        schema = pq.read_schema(path / "0.parquet")
    else:
        frame.to_parquet(path,index=kind=="stored_index",row_group_size=2000)
        ref = c.reference(path);schema = pq.read_schema(path)
    columns = list(reversed(schema.names))
    first, last = ("2025-01-01", "2025-01-31") if kind == "empty_filter" else ("2024-01-03", "2024-01-08")
    with patch.object(c,"verify",return_value=path):
        expected = _old_bounded_reference(ref,columns,"signal_date",first,last)
        actual = c.bounded_frame(ref,columns,"signal_date",first,last)
    pd.testing.assert_frame_equal(actual,expected,check_dtype=True,check_categorical=True,check_index_type=True,check_column_type=True)
    assert actual.attrs == expected.attrs
    if kind == "dictionary_different": assert not isinstance(actual["category"].dtype,pd.CategoricalDtype)
    if kind == "dictionary_same": assert isinstance(actual["category"].dtype,pd.CategoricalDtype)


@pytest.mark.parametrize("count", [600000,600001])
def test_bounded_projection_retains_exact_row_limit_without_large_allocation(count):
    import pyarrow as pa
    import pyarrow.dataset as ds
    tiny = pa.record_batch({"signal_date": pd.to_datetime(["2024-01-02"]), "x": [1.]})
    class Batch:
        num_rows = count
        def to_pandas(self): return tiny.to_pandas()
    class Dataset:
        schema = tiny.schema
        def scanner(self,**options):
            assert options["batch_size"] == 4096 and options["use_threads"] is False
            assert options["batch_readahead"] == options["fragment_readahead"] == 1
            return SimpleNamespace(to_batches=lambda: iter([Batch()]))
    converted = pa.Table.from_batches([tiny])
    with patch.object(c,"verify",return_value=Path("synthetic")), patch.object(ds,"dataset",return_value=Dataset()), \
         patch.object(pa,"Table",SimpleNamespace(from_batches=lambda batches:converted)):
        if count > 600000:
            with pytest.raises(ValueError,match="PREFIX_ROW_LIMIT"): c.bounded_frame({},["x"],"signal_date","2024-01-01","2024-01-03")
        else:
            assert list(c.bounded_frame({},["x"],"signal_date","2024-01-01","2024-01-03").x) == [1.]


def test_bounded_projection_no_batches_keeps_original_object_columns():
    import pyarrow as pa
    import pyarrow.dataset as ds
    schema=pa.schema([("signal_date",pa.timestamp("ns")),("x",pa.float64())])
    dataset=SimpleNamespace(schema=schema,scanner=lambda **kwargs: SimpleNamespace(to_batches=lambda:iter(())))
    with patch.object(c,"verify",return_value=Path("synthetic")),patch.object(ds,"dataset",return_value=dataset):
        result=c.bounded_frame({},["x"],"signal_date","2024-01-01","2024-01-03")
    pd.testing.assert_frame_equal(result,pd.DataFrame(columns=["x"]))


def test_bounded_projection_missing_column_rejects_before_scan(tmp_path):
    path=tmp_path/"small.parquet";pd.DataFrame({"signal_date":pd.to_datetime(["2024-01-02"])}).to_parquet(path,index=False)
    with pytest.raises(ValueError,match="PROJECTED_INPUT_FIELDS_REQUIRED"):
        c.bounded_frame(c.reference(path),["NOT_A_COLUMN"],"signal_date","2024-01-01","2024-01-03")


@pytest.fixture
def bounded_arrow_scan_stub(monkeypatch):
    """Tiny scanner double: expose behavior without a large Arrow allocation."""
    import pyarrow as pa
    import pyarrow.dataset as ds
    schema = pa.schema([("signal_date", pa.timestamp("ns")), ("x", pa.float64())])
    expected = pd.DataFrame({"x": [1.]})
    def configure(*, count=1, conversion_error=None):
        class Batch:
            num_rows = count
        class Table:
            def to_pandas(self, **options):
                assert options == {"split_blocks": True, "use_threads": False}
                if conversion_error is not None:
                    raise conversion_error
                return expected.copy()
        def scanner(**options):
            assert options["batch_size"] == 4096 and options["use_threads"] is False
            assert options["batch_readahead"] == options["fragment_readahead"] == 1
            return SimpleNamespace(to_batches=lambda: iter([Batch()]))
        monkeypatch.setattr(c, "verify", lambda ref: Path("synthetic"))
        monkeypatch.setattr(ds, "dataset", lambda *args, **kwargs: SimpleNamespace(schema=schema, scanner=scanner))
        monkeypatch.setattr(pa, "Table", SimpleNamespace(from_batches=lambda batches: Table()))
        return expected
    return configure


@pytest.mark.parametrize("fault", ["row_limit", "conversion"])
def test_bounded_projection_errors_still_run_arrow_cleanup(monkeypatch, bounded_arrow_scan_stub, fault):
    marker = RuntimeError("SYNTHETIC_CONVERSION_FAILED")
    bounded_arrow_scan_stub(count=600001 if fault == "row_limit" else 1,
        conversion_error=marker if fault == "conversion" else None)
    cleaned = []
    monkeypatch.setattr(c, "_release_arrow_cache", lambda: cleaned.append(True))
    if fault == "row_limit":
        with pytest.raises(ValueError, match="CONSENSUS_PREFIX_ROW_LIMIT"):
            c.bounded_frame({}, ["x"], "signal_date", "2024-01-01", "2024-01-03")
    else:
        with pytest.raises(RuntimeError) as caught:
            c.bounded_frame({}, ["x"], "signal_date", "2024-01-01", "2024-01-03")
        assert caught.value is marker
    assert cleaned == [True]


@pytest.mark.parametrize("fault", [False, True])
def test_bounded_projection_pool_trim_failure_preserves_result_or_original_error(monkeypatch, bounded_arrow_scan_stub, fault):
    import pyarrow as pa
    marker = RuntimeError("SYNTHETIC_ORIGINAL_CONVERSION_ERROR")
    expected = bounded_arrow_scan_stub(conversion_error=marker if fault else None)
    attempts = []
    def unavailable_trim():
        attempts.append(True)
        raise OSError("SYNTHETIC_POOL_TRIM_UNAVAILABLE")
    monkeypatch.setattr(pa, "default_memory_pool", lambda: SimpleNamespace(release_unused=unavailable_trim))
    if fault:
        with pytest.raises(RuntimeError) as caught:
            c.bounded_frame({}, ["x"], "signal_date", "2024-01-01", "2024-01-03")
        assert caught.value is marker
    else:
        actual = c.bounded_frame({}, ["x"], "signal_date", "2024-01-01", "2024-01-03")
        pd.testing.assert_frame_equal(actual, expected, check_dtype=True)
    assert attempts == [True]


@pytest.mark.parametrize("fault", [None, "missing", "duplicate", "boolean_year"])
def test_duration_frozen_state_streams_large_metadata_array(tmp_path, monkeypatch, fault):
    path = tmp_path / "_maintenance/A_ALL_AND_DEMO_RANDOM_TEST2026_20261009_R1/A_ALL_FROZEN_STATE_DEPENDENCIES.json"
    row = dict(slot_id="duration_tree_2025", stage="R6", objective="duration", learner="tree",
        year=2025, status="TRAINED", model_path="synthetic_model", model_sha256="a"*64,
        receipt_ref={"path":"synthetic_receipt", "sha256":"b"*64})
    if fault == "boolean_year": row["year"] = True
    rows = [dict(slot_id="other_"+str(i), ignored="not-selected-"+"x"*1024) for i in range(90)]
    if fault != "missing": rows.append({**row, "ignored":"not-selected-"+"x"*70000})
    if fault == "duplicate": rows.append(row.copy())
    ref = save(path, dict(model_states=rows, authority_refs={"R6_contract":{"path":"contract", "sha256":"c"*64}}))
    assert path.stat().st_size > 65536
    monkeypatch.setattr(c, "OLD_STATES_SHA", ref["sha256"])
    if fault:
        code = "FROZEN_IDENTITY" if fault == "boolean_year" else "ONE_FROZEN_STATE"
        with pytest.raises(ValueError, match=code): c.frozen_states(SimpleNamespace(results_root=tmp_path), SID)
    else:
        result = c.frozen_states(SimpleNamespace(results_root=tmp_path), SID)
        assert result["duration_tree_2025"]["metadata_row"] == row
        assert result["duration_tree_2025"]["closure_ref"] == ref


@pytest.mark.parametrize("raw, code", [
    (b'{"states":[{"id":1,"id":2}]}', "DUPLICATE_METADATA_KEY"),
    (b'{"states":[{"id":1};{"id":2}]}', "METADATA_ARRAY_CHANGED"),
    (b'{"states":[{"id":"' + b'x'*65537 + b'"}]}', "VALUE_TOO_LARGE"),
], ids=["duplicate-key", "malformed-separator", "oversized-value"])
def test_streamed_metadata_keeps_original_parser_guards(raw, code):
    import io
    from scripts.common.json_projection import array_metadata_fields
    with pytest.raises(ValueError, match=code):
        list(array_metadata_fields(io.BytesIO(raw), ("states",), {"id"}))


def test_streamed_metadata_skips_unselected_values_without_json_decoding():
    import io
    from scripts.common import json_projection as projection
    raw = b'{"before":null,"states":[{"id":1,"ignored":"DO_NOT_DECODE"}],"after":123}'
    original = json.loads
    def limited(value, *a, **kw):
        assert "DO_NOT_DECODE" not in str(value)
        return original(value, *a, **kw)
    with patch.object(projection.json, "loads", side_effect=limited):
        assert list(projection.array_metadata_fields(io.BytesIO(raw), ("states",), {"id"})) == [{"id":1}]
    assert list(projection.array_metadata_fields(io.BytesIO(b'{"states":[]}'), ("states",), {"id"})) == []
