import importlib.util
from pathlib import Path
import tempfile
import unittest
import pandas as pd
import pytest
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("extension", Path(__file__).parents[4] / "scripts/research/a2/evaluation/three_strategy_extension.py")
extension = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extension)


class ClockAndEvidenceTests(unittest.TestCase):
    def test_missing_signal_stops_before_gap_not_after(self):
        pairs, gap = extension.common_clock(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"],
            ["2026-01-02", "2026-01-06"], "2026-01-07")
        self.assertEqual(pairs, [(pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-05"))])
        self.assertEqual(gap["signal_date"], "2026-01-05")

    def test_latest_close_is_not_same_day_execution(self):
        pairs, gap = extension.common_clock(["2026-01-02", "2026-01-05", "2026-01-06"],
            ["2026-01-02", "2026-01-05", "2026-01-06"], "2026-01-05")
        self.assertEqual(len(pairs), 1)
        self.assertIsNone(gap)

    def test_changed_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source"
            path.write_text("original")
            ref = extension.reference(path)
            path.write_text("revised")
            with self.assertRaisesRegex(ValueError, "SOURCE_HASH_MISMATCH"):
                extension.verify_refs([ref])

    def test_optimizer_receives_continuous_signal_close_holdings(self):
        seen = []
        def solve(group, shares, values, nav, bundle, spec, signal):
            seen.append((shares.copy(), values.copy(), nav))
            return {"AA": .1}, {"raw_targets": {"AA": .1}, "solver_failed": False}
        def replay(name, callback, prices, executions, signals):
            callback(signals[executions[0]], {}, {}, 1.)
            callback(signals[executions[1]], {"AA": 2.}, {"AA": .2}, 1.05)
            return "ledger"
        panel = pd.DataFrame({"signal_date": pd.to_datetime(["2026-01-02", "2026-01-05"]),
                              "ticker": ["AA", "AA"], "raw_rank": [1, 1]})
        pairs = [(pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-05")),
                 (pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-06"))]
        prices = pd.DataFrame({"trade_date": pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]), "ticker": ["AA"] * 3})
        result, targets = extension.replay_common(replay, "HGB", ("frozen",), panel, prices,
            {"optimizer": SimpleNamespace(solve=solve), "risk": "frozen"}, pairs)
        self.assertEqual(seen[1], ({"AA": 2.}, {"AA": .2}, 1.05))
        self.assertAlmostEqual(targets.iloc[1].signal_close_weight, .2 / 1.05)
        self.assertEqual(result, "ledger")

    def test_recorded_predictions_do_not_impute_or_refit_short_lags(self):
        frame = pd.DataFrame({"signal_date": [pd.Timestamp("2026-01-02")] * 40,
            "ticker": [f"T{i}" for i in range(40)], "raw_rank": range(1, 41),
            "raw_score": range(40), "lag": [float("nan")] * 40,
            "pred_hgb": [.1] * 40, "pred_q10": [-.1] * 40})
        selected = SimpleNamespace(FEATURES=("lag",))
        panel = extension.score_panel([frame], selected, {})
        self.assertTrue(panel.lag.isna().all())
        self.assertTrue(panel.pred_hgb.eq(.1).all())

    def test_one_reviewed_event_does_not_resolve_another(self):
        pairs = [(pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-05")),
                 (pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-06"))]
        events = pd.DataFrame({"event_date": ["2025-12-31", "2026-01-05", "2026-01-06"],
            "ticker": ["OLD", "RESOLVED", "UNKNOWN"],
            "audit_kind": ["LARGE_RAW_MOVE_NO_VENDOR_EVENT"] * 3,
            "resolution_status": ["UNREVIEWED", "RESOLVED_NON_CORPORATE_ACTION", "UNREVIEWED"]})
        kept, gap = extension.event_clock(pairs, events)
        self.assertEqual(len(kept), 1)
        self.assertEqual(gap["tickers"], ["UNKNOWN"])

    def test_unreviewed_event_blocks_only_actual_positive_holding(self):
        signal, execution = pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-05")
        panel = pd.DataFrame({"signal_date": [signal], "ticker": ["AA"], "raw_rank": [1]})
        prices = pd.DataFrame({"trade_date": [signal, execution], "ticker": ["AA", "AA"]})
        runtime = {"unresolved_events": {(execution, "AA")}}
        def held_replay(name, callback, prices, executions, signals):
            callback(signal, {"AA": 1.}, {"AA": .1}, 1.)
        with self.assertRaises(extension.HeldEventUnresolved):
            extension.replay_common(held_replay, "RAW", None, panel, prices, runtime, [(signal, execution)])
        def empty_replay(name, callback, prices, executions, signals):
            self.assertEqual(callback(signal, {}, {}, 1.), {"AA": .05})
            return "qualified"
        result, _ = extension.replay_common(empty_replay, "RAW", None, panel, prices, runtime, [(signal, execution)])
        self.assertEqual(result, "qualified")


if __name__ == "__main__":
    unittest.main()


def reused_receipts(tmp_path):
    import json
    from scripts.common.storage_paths import StoragePaths
    paths = StoragePaths(**{name: tmp_path / name for name in
        ("repo_root", "data_root", "cache_root", "daily_root", "backtest_root", "results_root", "envs_root")})
    paths.daily_root.mkdir()
    payloads = {
        "acquisition": {"status": "PARTIAL", "results": []},
        "massive": {"summary": {"status": "COMPLETE"}, "contract": {"provider": "MASSIVE_GROUPED"},
            "catalog_records": [{"ticker": "HOOD", "max_date": "2026-09-30"}]},
        "rehab": {"source": "MOOMOO_OPEND_GET_REHAB", "target_date": "2026-09-30", "results": []}}
    refs = {}
    for name, value in payloads.items():
        path = paths.daily_root / (name + ".json")
        path.write_text(json.dumps(value))
        refs[name] = extension.reference(path)
    return paths, refs


def test_saved_receipts_load_without_transport_and_preserve_binding(tmp_path, monkeypatch):
    from scripts.storage import refresh_market_data, refresh_current_massive, refresh_massive_market
    from scripts import daily_recommendation_prices
    fail = lambda *a, **k: (_ for _ in ()).throw(AssertionError("No saved-receipt transport or key read"))
    monkeypatch.setattr(refresh_market_data, "run", fail)
    monkeypatch.setattr(refresh_current_massive, "load_api_key", fail)
    monkeypatch.setattr(refresh_massive_market, "acquire", fail)
    monkeypatch.setattr(daily_recommendation_prices, "refresh_rehab", fail)
    paths, refs = reused_receipts(tmp_path)
    acquired, records, rehab, source, used = extension._load_held_reuse(paths, refs, ["HOOD"], "2026-09-30")
    assert acquired["status"] == "PARTIAL" and set(records) == {"HOOD"}
    assert source == Path(refs["rehab"]["path"]) and used == list(refs.values())
    assert rehab["target_date"] == "2026-09-30"


def test_saved_receipts_reject_changed_bytes_missing_name_and_wrong_target(tmp_path):
    import json
    import pytest
    paths, refs = reused_receipts(tmp_path)
    with pytest.raises(ValueError, match="HELD_REUSE_TICKER_UNAVAILABLE"):
        extension._load_held_reuse(paths, refs, ["TTAN"], "2026-09-30")
    with pytest.raises(ValueError, match="HELD_REUSE_SOURCE_CONTRACT_INVALID"):
        extension._load_held_reuse(paths, refs, ["HOOD"], "2026-10-01")
    path = Path(refs["rehab"]["path"])
    path.write_text(json.dumps({"changed": True}))
    with pytest.raises(ValueError, match="SOURCE_HASH_MISMATCH"):
        extension._load_held_reuse(paths, refs, ["HOOD"], "2026-09-30")


def feature_owner(tmp_path, monkeypatch, *, legacy_no_ids=False):
    from copy import deepcopy
    import json
    from scripts.research.a2.portfolio import selected_hgb as selected
    spec = importlib.util.spec_from_file_location("feature_owner_fixture",
        Path(__file__).parents[4] / "tests/research/a2/portfolio/test_selected_hgb_history.py")
    fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
    old, new, repair = fixture.repair_package(tmp_path, monkeypatch)
    for package in (old, new):
        day = package["shared_scores"]["current"]["signal_date"]
        rows = package["shared_scores"]["current"]["rows"]
        frame = pd.DataFrame([{**{key: row[key] for key in ("ticker", "security_id", "raw_rank", "raw_score")},
            "signal_date": day, **{name: .02 for name in selected.FEATURES[2:]}} for row in rows])
        if legacy_no_ids:
            frame = frame.drop(columns="security_id").rename(columns={"signal_date":"trade_date"})
        feature = Path(package["source_refs"]["current/selected_hgb_features.parquet"]["path"])
        frame.to_parquet(feature,index=False)
        feature_ref = extension.reference(feature)
        report_path = Path(package["source_refs"]["current/report.json"]["path"])
        report = json.loads(report_path.read_text())
        report["selected_hgb_features"].update(feature_ref)
        report_path.write_text(json.dumps(report))
        package["source_refs"]["current/selected_hgb_features.parquet"] = feature_ref
        package["source_refs"]["current/report.json"] = extension.reference(report_path)
        package["source_hashes"] = {key: ref["sha256"] for key, ref in package["source_refs"].items()}
    audit_path = Path(repair["path"])
    audit = json.loads(audit_path.read_text()); audit["parent_inputs"] = [old["source_refs"]["current/report.json"]]
    audit_path.write_text(json.dumps(audit)); repair = extension.reference(audit_path)
    report_path = Path(new["source_refs"]["current/report.json"]["path"])
    report = json.loads(report_path.read_text()); report["repair_lineage"] = repair
    report_path.write_text(json.dumps(report))
    new["source_refs"]["current/report.json"] = extension.reference(report_path)
    new["source_hashes"] = {key: ref["sha256"] for key, ref in new["source_refs"].items()}
    daily = tmp_path / "daily"
    output = daily / "A2_selected_hgb/latest.json"
    selected.publish(old, output); selected.publish(new, output, snapshot_repair=repair)
    root = tmp_path / "frozen_replay"
    original = root / "test2026/predictions.parquet"; original.parent.mkdir(parents=True)
    original_frame, _ = selected._normalise_day(frame, {"pd": pd, "np": __import__("numpy")})
    if "security_id" not in original_frame:
        original_frame = original_frame.merge(pd.DataFrame(rows)[["ticker","security_id"]],on="ticker",validate="one_to_one")
    original_frame.assign(signal_date="2026-09-23", pred_hgb=.01, pred_q10=-.01).to_parquet(original,index=False)
    monkeypatch.setattr(selected, "REPLAY_HASHES", {"test2026/predictions.parquet": extension.reference(original)["sha256"]})
    stale = daily / "A2_today_recommendation/runs/old/report.json"; stale.parent.mkdir(parents=True)
    stale.write_text(json.dumps(json.loads(Path(old["source_refs"]["current/report.json"]["path"]).read_text())))
    return selected, SimpleNamespace(daily_root=daily), root, output, old, new


def test_sources_select_accepted_revision_not_stale_run_and_preserve_refs(tmp_path, monkeypatch):
    selected, paths, root, output, old, new = feature_owner(tmp_path, monkeypatch)
    monkeypatch.setattr(selected, "_current_day", lambda *a, **k: (_ for _ in ()).throw(AssertionError("stale run must not load")))
    original = output.read_bytes()
    frames, refs = extension.load_sources(paths, selected, root, target_date="2026-09-24")
    assert len(frames) == 2
    expected = pd.read_parquet(new["source_refs"]["current/selected_hgb_features.parquet"]["path"])
    assert frames[1].raw_score.tolist() == expected.raw_score.tolist()
    for key in ("history/2026-09-24.json", "history_revision/2026-09-24.json", "current/report.json",
                "current/selected_hgb_features.parquet"):
        assert new["source_refs"][key] in refs
    assert extension.reference(output) not in refs and output.read_bytes() == original
    assert old["source_refs"]["current/selected_hgb_features.parquet"] not in refs


@pytest.mark.parametrize("change", ["receipt", "feature", "owner_current", "outside_ref"])
def test_source_owner_rejects_tamper_or_unaccepted_same_date_change(tmp_path, monkeypatch, change):
    import json
    import pytest
    selected, paths, root, output, old, new = feature_owner(tmp_path, monkeypatch)
    if change == "receipt":
        Path(new["source_refs"]["history_revision/2026-09-24.json"]["path"]).write_text("{}")
    elif change == "feature":
        Path(new["source_refs"]["current/selected_hgb_features.parquet"]["path"]).write_bytes(b"tamper")
    else:
        owner = json.loads(output.read_text())
        if change == "owner_current": owner["shared_scores"]["current"]["rows"][0]["pred_hgb"] += .001
        else: owner["source_refs"]["history/2026-09-24.json"]["path"] = str(tmp_path / "outside.json")
        output.write_text(json.dumps(owner))
    with pytest.raises((ValueError, AssertionError)):
        extension.load_sources(paths, selected, root, target_date="2026-09-24")


def test_explicit_feature_duplicate_keeps_exact_comparison_not_preference(tmp_path, monkeypatch):
    import pytest
    selected, paths, root, output, old, new = feature_owner(tmp_path, monkeypatch)
    frames, _ = extension.load_sources(paths, selected, root,
        [old["source_refs"]["current/selected_hgb_features.parquet"]["path"]], target_date="2026-09-24")
    runtime = {"pd":pd, "np":__import__("numpy"),
        "model":SimpleNamespace(predict=lambda frame: [0.] * len(frame)),
        "q10":SimpleNamespace(predict=lambda frame: [0.] * len(frame))}
    with pytest.raises(AssertionError): extension.score_panel(frames, selected, runtime)


@pytest.mark.parametrize("change", [None, "prediction", "identity", "raw_score"])
def test_replayed_panel_must_match_complete_accepted_scores(tmp_path, monkeypatch, change):
    import pytest
    selected, paths, root, output, old, new = feature_owner(tmp_path, monkeypatch)
    owner = __import__("json").loads(output.read_text())
    snapshots, _ = extension.accepted_snapshots(owner, output.parent / "history", selected)
    rows = snapshots["2026-09-24"]["shared_scores"]["rows"]
    frame = pd.DataFrame(rows).assign(signal_date=pd.Timestamp("2026-09-24"))
    if change == "prediction": frame.loc[0,"pred_hgb"] += .00001
    elif change == "identity": frame.loc[0,"security_id"] = "wrong"
    elif change == "raw_score": frame.loc[0,"raw_score"] += .00001
    if change is None:
        extension.verify_accepted_scores(frame,snapshots,selected)
    else:
        with pytest.raises(ValueError, match="ACCEPTED_SHARED_SCORE_MISMATCH"):
            extension.verify_accepted_scores(frame,snapshots,selected)


def test_json_owner_capture_never_binds_separate_unhashed_parse(tmp_path, monkeypatch):
    import json
    path = tmp_path / "latest.json"
    data = b'{"version":"accepted"}'
    path.write_bytes(data)
    # A separate read_text would see a different version; the hash and parse must use one byte read.
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: '{"version":"unaccepted"}')
    owner, ref = extension._capture_json(path)
    assert owner == {"version":"accepted"} and ref == extension.reference(path)


def test_feature_capture_never_reads_unhashed_path_after_verification(tmp_path, monkeypatch):
    path = tmp_path / "feature.parquet"
    pd.DataFrame({"version":["accepted"]}).to_parquet(path,index=False)
    ref = extension.reference(path)
    real_read = pd.read_parquet
    def capture_only(source, *args, **kwargs):
        assert hasattr(source,"read") and not isinstance(source,(str,Path))
        path.write_bytes(b"changed after capture")
        return real_read(source,*args,**kwargs)
    monkeypatch.setattr(pd,"read_parquet",capture_only)
    assert extension._capture_parquet(ref).version.tolist() == ["accepted"]
    with pytest.raises(ValueError,match="SOURCE_HASH_MISMATCH"):
        extension.verify_refs([ref])


def test_mutable_owner_is_runtime_guard_without_creating_manifest_self_reference(tmp_path, monkeypatch):
    selected, paths, root, output, old, new = feature_owner(tmp_path, monkeypatch)
    _, refs, owner, snapshots = extension._load_sources(paths, selected, root, target_date="2026-09-24")
    assert owner == extension.reference(output) and "2026-09-24" in snapshots
    output.write_text(output.read_text() + "\n")
    extension.verify_refs(refs)  # Immutable accepted sources survive the next package publication.
    with pytest.raises(ValueError,match="SOURCE_HASH_MISMATCH"):
        extension.verify_refs([owner])


def test_unchanged_accepted_mutable_report_uses_original_cached_binding(tmp_path, monkeypatch):
    import json
    from scripts.research.a2.portfolio import selected_hgb as selected
    spec = importlib.util.spec_from_file_location("mutable_owner_fixture",
        Path(__file__).parents[4] / "tests/research/a2/portfolio/test_selected_hgb_history.py")
    fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
    _, package = fixture.bound_package(tmp_path, monkeypatch, mutable=True)
    output = tmp_path / "published/latest.json"
    selected.publish(package, output)
    report = Path(package["source_refs"]["current/report.json"]["path"])
    report.write_text('{"status":"READY","data_date":"2026-09-25"}')
    ref, snapshots, refs = extension._accepted_owner(output, selected)
    assert snapshots["2026-09-24"]["shared_scores"]["rows"] == package["shared_scores"]["current"]["rows"]
    assert ref == extension.reference(output)
    assert package["source_refs"]["current/report.json"] not in refs
    extension.verify_refs(refs)


def test_changed_current_alias_cannot_use_old_cached_report_binding(tmp_path, monkeypatch):
    import json
    selected, paths, root, output, old, new = feature_owner(tmp_path, monkeypatch)
    owner = json.loads(output.read_text())
    alias = tmp_path / "unaccepted_alias.json"
    alias.write_text('{"status":"READY","data_date":"2026-09-25"}')
    owner["source_refs"]["current/report.json"] = extension.reference(alias)
    owner["source_hashes"]["current/report.json"] = extension.reference(alias)["sha256"]
    output.write_text(json.dumps(owner))
    with pytest.raises(ValueError): extension._accepted_owner(output, selected)


def test_producer_vintage_is_exact_original_bytes_and_survives_next_source_change(tmp_path):
    source = tmp_path / "active.py"
    data = b"# original producer\r\nvalue = 1\r\n"
    source.write_bytes(data)
    observation = extension.reference(source)
    output = tmp_path / "existing_run/replay"; output.mkdir(parents=True)
    frozen = extension._freeze_producer_vintage(output,observation,data)
    assert Path(frozen["path"]).read_bytes() == data
    assert frozen["sha256"] == observation["sha256"] and frozen["path"] != observation["path"]
    source.write_bytes(b"# maintained producer changed\n")
    extension.verify_refs([frozen])
    with pytest.raises(ValueError,match="SOURCE_HASH_MISMATCH"): extension.verify_refs([observation])


@pytest.mark.parametrize("fault", ["changed_source", "wrong_captured_bytes", "existing_destination"])
def test_producer_vintage_never_overwrites_or_accepts_unmatched_capture(tmp_path,fault):
    source = tmp_path / "active.py"; source.write_bytes(b"original")
    observation = extension.reference(source)
    output = tmp_path / "existing_run/replay"; output.mkdir(parents=True)
    data = b"original"
    target = output / "producer_source.py"
    if fault == "changed_source": source.write_bytes(b"changed")
    elif fault == "wrong_captured_bytes": data = b"unbound"
    else: target.write_bytes(b"accepted old vintage")
    with pytest.raises((ValueError,FileExistsError)):
        extension._freeze_producer_vintage(output,observation,data)
    assert not target.exists() or target.read_bytes() == b"accepted old vintage"


def test_run_binds_vintage_only_and_keeps_canonical_as_observation():
    import ast
    tree = ast.parse(Path(extension.__file__).read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name == "run_extension")
    rendered = ast.unparse(function)
    assert "producer_ref = _freeze_producer_vintage(output, producer_observation, producer_bytes)" in rendered
    assert "refs.append(producer_ref)" in rendered
    assert "'canonical_producer_observation': producer_observation" in rendered
    assert "refs.append(producer_observation)" not in rendered


def test_legacy_trade_date_features_reuse_only_hash_bound_archive_identities(tmp_path, monkeypatch):
    selected, paths, root, output, old, new = feature_owner(tmp_path,monkeypatch,legacy_no_ids=True)
    frame = pd.read_parquet(new["source_refs"]["current/selected_hgb_features.parquet"]["path"])
    assert "security_id" not in frame and "trade_date" in frame
    frames, _ = extension.load_sources(paths,selected,root,target_date="2026-09-24")
    accepted = frames[1]
    expected = pd.DataFrame(new["shared_scores"]["current"]["rows"])
    assert accepted.security_id.tolist() == expected.sort_values("raw_rank").security_id.tolist()
    assert accepted.signal_date.dt.strftime("%Y-%m-%d").eq("2026-09-24").all()
    assert accepted.raw_score.tolist() == expected.sort_values("raw_rank").raw_score.tolist()


@pytest.mark.parametrize("fault", ["wrong_id", "empty_id", "duplicate_id", "unknown_ticker", "wrong_date", "rank", "score"])
def test_legacy_identity_attachment_never_repairs_present_bad_ids_or_changed_inputs(tmp_path,monkeypatch,fault):
    import json
    from copy import deepcopy
    selected, paths, root, output, old, new = feature_owner(tmp_path,monkeypatch,legacy_no_ids=True)
    owner = json.loads(output.read_text())
    snapshots,_ = extension.accepted_snapshots(owner,output.parent/"history",selected)
    snapshot = deepcopy(snapshots["2026-09-24"])
    frame = pd.read_parquet(snapshot["source_refs"]["current/selected_hgb_features.parquet"]["path"])
    if fault in ("wrong_id","empty_id","duplicate_id"):
        frame["security_id"] = [row["security_id"] for row in snapshot["shared_scores"]["rows"]]
        if fault == "wrong_id": frame.loc[0,"security_id"] = "WRONG"
        elif fault == "empty_id": frame.loc[0,"security_id"] = ""
        else: frame.loc[0,"security_id"] = frame.loc[1,"security_id"]
    elif fault == "unknown_ticker": frame.loc[0,"ticker"] = "NOT_IN_ACCEPTED_TOP40"
    elif fault == "wrong_date": frame["trade_date"] = "2026-09-25"
    elif fault == "rank": frame.loc[0,"raw_rank"] = 2
    else: frame.loc[0,"raw_score"] += .01
    path = tmp_path/(fault+".parquet");frame.to_parquet(path,index=False)
    # The SHA is intentionally valid for the supplied feature; identity/as-of still must reject.
    snapshot["source_refs"]["current/selected_hgb_features.parquet"] = extension.reference(path)
    with pytest.raises((ValueError,AssertionError)):
        extension._accepted_feature_frame(snapshot,selected)


@pytest.mark.parametrize("date_storage", ["timestamp", "iso_string"])
def test_bounded_arrow_capture_projects_2026_rows_and_ignores_future_append(tmp_path, monkeypatch, date_storage):
    import pyarrow as pa
    import pyarrow.dataset as ds
    import pyarrow.parquet as pq
    from pandas.testing import assert_frame_equal

    path = tmp_path / "mixed_years.parquet"
    source = pd.DataFrame({
        "signal_date": pd.to_datetime(["2025-12-31", "2026-01-01", "2026-10-01", "2027-01-01"]),
        "ticker": ["PRE", "FIRST", "LATER", "FUTURE"],
        "pred_hgb": [-999., .03, .02, 999.],
        "excluded_payload": ["must not materialize"] * 4,
    })
    if date_storage == "iso_string":
        source["signal_date"] = source.signal_date.dt.strftime("%Y-%m-%d")
    pq.write_table(pa.Table.from_pandas(source, preserve_index=False), path, row_group_size=1)
    columns = ["signal_date", "ticker", "pred_hgb"]
    scans = []
    original_dataset = ds.dataset
    original_format = ds.ParquetFileFormat

    class ProjectedScanner:
        def __init__(self, dataset):
            self.dataset = dataset

        def __getattr__(self, name):
            return getattr(self.dataset, name)

        def to_table(self, **kwargs):
            assert kwargs["columns"] == columns and kwargs.get("filter") is not None
            table = self.dataset.to_table(**kwargs)
            scans.append((table.column_names, table.num_rows))
            return table

    class ProjectedFormat:
        def __init__(self, *args, **kwargs):
            self.format = original_format(*args, **kwargs)

        def make_fragment(self, source, *args, **kwargs):
            assert not isinstance(source, (str, Path)), "bounded scan must share the hashed input stream"
            return ProjectedScanner(self.format.make_fragment(source, *args, **kwargs))

    monkeypatch.setattr(ds, "dataset", lambda *args, **kwargs: ProjectedScanner(original_dataset(*args, **kwargs)))
    monkeypatch.setattr(ds, "ParquetFileFormat", ProjectedFormat)
    monkeypatch.setattr(pd, "read_parquet", lambda *args, **kwargs: pytest.fail("bounded read must filter in Arrow"))
    first = extension._capture_parquet(extension.reference(path), columns=columns,
        date_column="signal_date", start="2026-01-01", stop="2027-01-01")
    assert first.columns.tolist() == columns
    assert first.ticker.tolist() == ["FIRST", "LATER"]
    assert first.pred_hgb.tolist() == [.03, .02]
    assert scans == [(columns, 2)]

    future = pd.DataFrame({"signal_date": pd.to_datetime(["2027-06-01"]),
        "ticker": ["APPENDED"], "pred_hgb": [1e9], "excluded_payload": ["future secret"]})
    if date_storage == "iso_string":
        future["signal_date"] = future.signal_date.dt.strftime("%Y-%m-%d")
    pq.write_table(pa.Table.from_pandas(pd.concat([source, future], ignore_index=True),
        preserve_index=False), path, row_group_size=1)
    after = extension._capture_parquet(extension.reference(path), columns=columns,
        date_column="signal_date", start="2026-01-01", stop="2027-01-01")
    assert_frame_equal(first, after, check_exact=True)
    assert scans == [(columns, 2), (columns, 2)]


@pytest.mark.parametrize("policy_name", ["DIRECT_POLICY", "LEGACY_POLICY"])
def test_explicit_replay_policy_delegates_with_continuous_account_state(monkeypatch, policy_name):
    from scripts.research.a2.portfolio import selected_hgb as selected

    signal, execution = pd.Timestamp("2026-01-02"), pd.Timestamp("2026-01-05")
    panel = pd.DataFrame({"signal_date": [signal], "ticker": ["AA"], "raw_rank": [1]})
    prices = pd.DataFrame({"trade_date": [signal, execution], "ticker": ["AA", "AA"]})
    shares, values, nav = {"AA": 2.}, {"AA": .21}, 1.05
    policy, bundle, spec = getattr(selected, policy_name), object(), ("frozen_spec",)
    calls = []
    optimizer = SimpleNamespace(solve=lambda *a, **k: pytest.fail("explicit policy must use selected solve_targets"))

    def solve_targets(group, old_shares, old_values, old_nav, risk, risk_spec, day, **kwargs):
        calls.append((old_shares.copy(), old_values.copy(), old_nav, risk, risk_spec, day, kwargs))
        return {"AA": .1}, {"raw_targets": {"AA": .1}, "solver_failed": False}

    def replay(name, callback, price_frame, executions, signals):
        assert name == "HGB" and executions == [execution] and signals == {execution: signal}
        assert callback(signal, shares, values, nav) == {"AA": .1}
        return "synthetic_ledger"

    monkeypatch.setattr(selected, "solve_targets", solve_targets)
    result, targets = extension.replay_common(replay, "HGB", spec, panel, prices,
        {"optimizer": optimizer, "risk": bundle, "policy": policy}, [(signal, execution)])
    assert calls == [(shares, values, nav, bundle, spec, signal,
                      {"optimizer": optimizer, "policy": policy})]
    assert result == "synthetic_ledger"
    assert targets.iloc[0].signal_close_weight == values["AA"] / nav
    assert targets.iloc[0].target_weight == .1


@pytest.mark.parametrize("recorded_end,expected_stop", [(None, "2026-09-25"), ("2026-10-02", "2026-10-03")])
def test_saved_supplement_bounds_captured_read_by_its_own_target(tmp_path, monkeypatch, recorded_end, expected_stop):
    """Saved receipt continuation reaches its bounded reader without network calls."""
    import json
    from scripts.common import storage_paths
    from scripts.research.a2.evaluation import demo_performance
    from scripts.research.a2.inference import historical_top40
    from scripts import daily_recommendation_prices as original
    paths, sources = reused_receipts(tmp_path)
    hist = paths.daily_root / "historical.json"
    proof = paths.daily_root / "lineage.json"
    proof.write_text(json.dumps({"lineage": [{"ticker": "HIVE", "code": "US.HIVE", "raw_end": "2026-09-22"}]}))
    hist.write_text(json.dumps({"price_manifest": extension.reference(proof)}))
    prices = paths.daily_root / "prices.parquet"
    pd.DataFrame({"trade_date": ["2026-09-22"]}).to_parquet(prices, index=False)
    inputs = paths.daily_root / "price_inputs.json"
    inputs.write_text(json.dumps({"refs": [], **({"end_date": recorded_end} if recorded_end else {})}))
    coverage = paths.daily_root / "coverage.json"
    coverage.write_text(json.dumps({"adjustment": {"wolf_event_date": "2025-01-01", "wolf_new_shares_per_old_share": 1.}}))
    monkeypatch.setattr(storage_paths, "resolve", lambda *args: paths)
    monkeypatch.setattr(demo_performance, "canonical_manifest", lambda *args: (hist, None))
    monkeypatch.setattr(historical_top40, "load_sessions", lambda *args: (pd.date_range("2026-09-01", "2026-09-30", freq="B"), {}))
    monkeypatch.setattr(extension, "_load_held_reuse", lambda *args: ({"results": []}, {}, {}, coverage, []))
    monkeypatch.setattr(original, "COVERAGE_PATH", coverage)
    monkeypatch.setattr(original, "COVERAGE_SHA", extension.reference(coverage)["sha256"])
    monkeypatch.setattr(original, "_adapter", lambda *args: object())
    class ReachedBoundedRead(Exception):
        pass
    def captured(ref, **kwargs):
        assert ref == extension.reference(prices)
        assert kwargs["date_column"] == "trade_date"
        assert kwargs["start"] == "2025-11-01"
        assert kwargs["stop"] == pd.Timestamp(expected_stop)
        raise ReachedBoundedRead
    monkeypatch.setattr(extension, "_capture_parquet", captured)
    with pytest.raises(ReachedBoundedRead):
        extension.supplement_held_prices(prices, inputs, paths.backtest_root / "offline_supplement",
            ["HIVE"], target="2026-09-24", repo_root=paths.repo_root, reuse_sources=sources)


def publication_receipts(tmp_path):
    import json
    paths, refs = reused_receipts(tmp_path)
    paths.data_root.mkdir()
    raw = paths.data_root / "synthetic_raw.parquet"
    raw.write_bytes(b"synthetic hash-only fixture")
    inputs = paths.daily_root / "published_inputs.json"
    inputs.write_text(json.dumps({"raw_inputs": []}))
    binding = extension.reference(inputs)
    row = {"ticker": "HOOD", "max_date": "2026-09-30", "dataset": "prices_daily_massive", "source": "MASSIVE_GROUPED",
           "adjustment": "raw", "format": "parquet", "path": str(raw), "source_sha256": extension.reference(raw)["sha256"],
           "lineage": {"inputs_manifest": binding}}
    publication = paths.daily_root / "current_publication.json"
    publication.write_text(json.dumps({"provider": "MASSIVE_GROUPED", "catalog_records": [row], "inputs_manifest": binding, "issues": []}))
    return paths, {"publication": extension.reference(publication), "rehab": refs["rehab"]}, inputs


def test_existing_publication_reuse_keeps_real_identity_and_bound_inputs(tmp_path):
    paths, refs, inputs = publication_receipts(tmp_path)
    acquired, records, rehab, source, used = extension._load_held_reuse(paths, refs, ["HOOD"], "2026-09-30")
    assert acquired["source"] == "EXISTING_LOCAL_PUBLICATION_NO_ACQUISITION"
    assert "status" not in acquired and acquired["results"] == []
    assert set(records) == {"HOOD"}
    assert used == [*refs.values(), extension.reference(inputs)]
    assert rehab["target_date"] == "2026-09-30"


@pytest.mark.parametrize("mutation,error", [
    ("provider", "HELD_PUBLICATION_CONTRACT_INVALID"),
    ("binding", "HELD_PUBLICATION_RECORD_BINDING_INVALID"),
    ("target", "HELD_REUSE_TARGET_PRICE_MISSING"),
    ("duplicate", "HELD_REUSE_DUPLICATE_PRICE_RECORD"),
    ("inputs", "HELD_PUBLICATION_INPUT_BINDING_MISSING"),
])
def test_publication_reuse_rejects_wrong_identity_binding_and_target(tmp_path, mutation, error):
    import json
    paths, refs, _ = publication_receipts(tmp_path)
    path = Path(refs["publication"]["path"])
    value = json.loads(path.read_text())
    if mutation == "provider": value["provider"] = "OTHER"
    if mutation == "binding": value["catalog_records"][0]["lineage"]["inputs_manifest"]["sha256"] = "wrong"
    if mutation == "target": value["catalog_records"][0]["max_date"] = "2026-09-29"
    if mutation == "duplicate": value["catalog_records"] += value["catalog_records"]
    if mutation == "inputs": value["inputs_manifest"] = {}
    path.write_text(json.dumps(value));refs["publication"] = extension.reference(path)
    with pytest.raises(ValueError, match=error):
        extension._load_held_reuse(paths, refs, ["HOOD"], "2026-09-30")


def test_publication_reuse_fails_closed_on_missing_ticker_or_changed_input(tmp_path):
    paths, refs, inputs = publication_receipts(tmp_path)
    with pytest.raises(ValueError, match="HELD_REUSE_TICKER_UNAVAILABLE:DKS"):
        extension._load_held_reuse(paths, refs, ["DKS"], "2026-09-30")
    inputs.write_text("changed")
    with pytest.raises(ValueError, match="SOURCE_HASH_MISMATCH"):
        extension._load_held_reuse(paths, refs, ["HOOD"], "2026-09-30")


def test_explicit_execution_end_uses_only_previous_frozen_signal():
    sessions = ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"]
    pairs, gap = extension.common_clock(sessions, ["2026-10-01", "2026-10-02", "2026-10-05"],
                                       "2026-10-02", execution_end="2026-10-05")
    assert pairs[-1] == (pd.Timestamp("2026-10-02"), pd.Timestamp("2026-10-05"))
    assert gap is None and all(signal <= pd.Timestamp("2026-10-02") for signal, _ in pairs)


def test_frozen_open_to_open_engine_needs_no_terminal_close():
    import ast
    import inspect
    import sys
    from scripts.research.a2.portfolio import selected_hgb as selected
    close_path = selected.DEFAULT_SOURCE_ROOT / "audit_20260926/close_clock.py"
    assert extension.reference(close_path)["sha256"] == "d0662181bbda504a6bcd23c2a12f09d4cef8910627e6c2c28f0d8cda225d02a5"
    tree = ast.parse(close_path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "close_clock_replay")
    e5_path = Path("D:/us-tech-quant-results/A2_EXECUTION_EFFICIENCY_R2_PREREGISTERED_HYSTERESIS/run_a2_execution_efficiency_r2.py")
    extension.verify_refs([{"path": str(e5_path), "sha256": extension.E5_SOURCE_SHA}])
    spec = importlib.util.spec_from_file_location("synthetic_open_e5", e5_path)
    e5 = importlib.util.module_from_spec(spec); sys.modules[spec.name] = e5; spec.loader.exec_module(e5)
    namespace = {"inspect": inspect, "rl_policy": SimpleNamespace(E5=e5_path)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(close_path), "exec"), namespace)
    replay = namespace["close_clock_replay"](e5)
    prices = pd.DataFrame({"trade_date": pd.to_datetime(["2026-10-01", "2026-10-02", "2026-10-05"]),
        "ticker": ["AA"] * 3, "open": [100., 100., 120.], "close": [100., 100., float("nan")]})
    pairs = [(pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-02")),
             (pd.Timestamp("2026-10-02"), pd.Timestamp("2026-10-05"))]
    panel = pd.DataFrame({"signal_date": [pair[0] for pair in pairs], "ticker": ["AA", "AA"], "raw_rank": [1, 1]})
    prefix, _ = extension.replay_common(replay, "RAW", None, panel, prices.iloc[:2], {}, pairs[:1])
    full, _ = extension.replay_common(replay, "RAW", None, panel, prices, {}, pairs)
    pd.testing.assert_frame_equal(prefix.daily, full.daily.iloc[:1].reset_index(drop=True))
    assert full.daily.execution_date.iloc[-1] == pd.Timestamp("2026-10-05")
    assert full.daily.nav.iloc[-1] > full.daily.nav.iloc[0]
    assert pd.isna(prices.iloc[-1].close)



def capture_reuse_case(tmp_path, monkeypatch):
    import json
    from scripts.research.a2.evaluation import demo_performance, demo_performance_prices
    signal, execution = "2026-10-02", "2026-10-05"
    paths = SimpleNamespace(daily_root=tmp_path / "daily")
    historical = tmp_path / "historical.json"; historical.write_text("{}")
    report = tmp_path / "report.json"; report.write_text(json.dumps({"data_date": signal}))
    source = tmp_path / "original_source"; source.write_text("immutable accepted source")
    def document(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value))
        return extension.reference(path)
    old_rows = [{"ticker": "AA", "code": "US.AA", "security_id": "AA_ID"}]
    new_rows = [*old_rows, {"ticker": "BB", "code": "US.BB", "security_id": "BB_ID"}]
    old_acquired = [{"code": "US.AA", "actual_response": "unchanged"}]
    old_rehab = [{"code": "US.AA", "actual_factor": "unchanged"}]
    parent = {"schema": "A2_EXECUTION_OPEN_INPUTS_V1",
        "signal_end_date": signal, "execution_end_date": execution,
        "as_of_utc": execution + "T15:00:00+00:00", "current_report": extension.reference(report),
        "records": old_rows,
        "acquisition_manifest": document("old_native.json", {"results": old_acquired}),
        "rehab_receipt": document("old_rehab.json", {"results": old_rehab})}
    parent_ref = document("parent_open.json", parent)
    new = {**parent, "as_of_utc": execution + "T16:00:00+00:00",
        "parent_execution_open_manifest": parent_ref, "records": new_rows,
        "acquisition_manifest": document("union_native.json", {"results": [*old_acquired, {"code": "US.BB"}]}),
        "rehab_receipt": document("union_rehab.json", {"results": [*old_rehab, {"code": "US.BB"}]})}
    new_ref = document("new_open.json", new)
    columns = demo_performance_prices.PRICE_COLUMNS
    prices = pd.DataFrame([{"ticker": name, "trade_date": pd.Timestamp(signal),
        "open": price, "high": price, "low": price, "close": price, "volume": 1000.}
        for name, price in (("AA", 10.), ("BB", 20.))])
    opening = prices.loc[prices.ticker.eq("AA")].copy()
    opening["trade_date"] = pd.Timestamp(execution)
    opening[["high", "low", "close", "volume"]] = float("nan")
    prices = pd.concat([prices, opening], ignore_index=True)[columns]
    price_path = tmp_path / "old_prices.parquet"; prices.to_parquet(price_path, index=False)
    events = pd.DataFrame(columns=["ticker", "event_date", "audit_kind"])
    event_path = tmp_path / "old_events.parquet"; events.to_parquet(event_path, index=False)
    phase = {"manifest": parent_ref, "signal_end_date": signal, "execution_end_date": execution,
        "as_of_utc": parent["as_of_utc"], "qualified_tickers": ["AA"],
        "qualifications": [{"ticker": "AA"}], "consumer_fields": ["open"],
        "terminal_close_available": False, "model_feature_eligibility_granted": False}
    old = {"start_date": signal, "end_date": signal, "price_basis": extension.BASIS,
        "captured_prices": extension.reference(price_path), "events": extension.reference(event_path),
        "execution_open": phase, "gaps": [], "event_review": None, "event_review_resolved": False,
        "refs": [extension.reference(source), extension.reference(historical), extension.reference(report)]}
    input_ref = document("old_inputs.json", old)
    bb = prices.loc[prices.ticker.eq("BB")].copy()
    terminal = bb.copy(); terminal["trade_date"] = pd.Timestamp(execution)
    terminal[["high", "low", "close", "volume"]] = float("nan")
    delta = {"prices": pd.concat([bb, terminal], ignore_index=True), "events": events.copy(),
        "refs": [new_ref], "gaps": [], "execution_open": {
            **phase, "manifest": new_ref, "qualified_tickers": ["BB"],
            "qualifications": [{"ticker": "BB"}]}}
    calls = []
    def qualify(p, hist, **kwargs):
        calls.append((p, hist, kwargs))
        return delta
    monkeypatch.setattr(demo_performance, "canonical_manifest", lambda path: (historical, extension.reference(historical)))
    monkeypatch.setattr(demo_performance_prices, "load_execution_prices", qualify)
    reuse = {"prices_ref": extension.reference(price_path), "inputs_ref": input_ref}
    return paths, reuse, report, Path(new_ref["path"]), new, prices, delta, calls, source


def test_capture_reuse_only_qualifies_delta_and_preserves_all_old_prices(tmp_path, monkeypatch):
    paths, reuse, report, new_path, new, previous, _, calls, _ = capture_reuse_case(tmp_path, monkeypatch)
    result, metadata = extension._reuse_execution_open_capture(
        paths, reuse, report, new_path, "2026-10-05")
    assert len(calls) == 1 and calls[0][2]["tickers"] == ["BB"]
    assert calls[0][2]["start"] == "2026-10-02" and calls[0][2]["end"] == "2026-10-02"
    assert calls[0][2]["execution_open_manifest"] == new_path
    old_rows = result["prices"].loc[~(result["prices"].ticker.eq("BB")
        & result["prices"].trade_date.eq(pd.Timestamp("2026-10-05")))]
    pd.testing.assert_frame_equal(previous.sort_values(["trade_date", "ticker"]).reset_index(drop=True),
                                  old_rows.reset_index(drop=True))
    terminal = result["prices"].loc[result["prices"].trade_date.eq(pd.Timestamp("2026-10-05"))]
    assert len(terminal) == 2 and terminal[["high", "low", "close", "volume"]].isna().all().all()
    assert metadata["execution_open"]["qualified_tickers"] == ["AA", "BB"]
    assert metadata["execution_open"]["manifest"] == extension.reference(new_path)
    assert metadata["capture_reuse"]["model_feature_eligibility_granted"] is False
    assert reuse["inputs_ref"] in metadata["refs"]


@pytest.mark.parametrize("fault,reason", [
    ("source_hash", "SOURCE_HASH_MISMATCH"),
    ("parent", "PARENT_MANIFEST_MISMATCH"),
    ("identity", "SECURITY_IDENTITY_CHANGED"),
    ("clock", "SIGNAL_REPORT_OR_CLOCK_CHANGED"),
    ("provider", "ORIGINAL_PROVIDER_RECEIPT_CHANGED"),
    ("history", "DELTA_HISTORY_PREFIX_CHANGED"),
    ("event", "DELTA_EVENT_AUDIT_CHANGED"),
    ("missing_terminal", "TERMINAL_OPEN_ONLY_REQUIRED"),
    ("unqualified", "DELTA_OPEN_NOT_QUALIFIED")])
def test_capture_reuse_rejects_changed_bindings_history_events_and_missing_open(tmp_path, monkeypatch, fault, reason):
    import json
    paths, reuse, report, new_path, new, _, delta, _, source = capture_reuse_case(tmp_path, monkeypatch)
    if fault == "source_hash":
        source.write_text("changed")
    if fault == "parent":
        new["parent_execution_open_manifest"]["sha256"] = "0" * 64
    if fault == "identity":
        new["records"][0] = {**new["records"][0], "security_id": "CHANGED"}
    if fault == "clock":
        new["execution_end_date"] = "2026-10-06"
    if fault == "provider":
        ref = new["acquisition_manifest"]; doc = json.loads(Path(ref["path"]).read_text())
        doc["results"][0]["actual_response"] = "changed"
        Path(ref["path"]).write_text(json.dumps(doc))
        new["acquisition_manifest"] = extension.reference(ref["path"])
    if fault == "history":
        delta["prices"].loc[0, "volume"] += 1.
    if fault == "event":
        delta["events"] = pd.DataFrame([{"ticker": "BB", "event_date": pd.Timestamp("2026-10-02"),
                                         "audit_kind": "LARGE_RAW_MOVE_NO_VENDOR_EVENT"}])
    if fault == "missing_terminal":
        delta["prices"] = delta["prices"].iloc[:1]
    if fault == "unqualified":
        delta["execution_open"]["qualified_tickers"] = []
        delta["gaps"] = [{"ticker": "BB", "reason": "MISSING_NATIVE_OPEN"}]
    new_path.write_text(json.dumps(new))
    with pytest.raises(ValueError, match=reason):
        extension._reuse_execution_open_capture(paths, reuse, report, new_path, "2026-10-05")


def test_capture_reuse_entry_uses_common_writer_without_full_universe_loading(tmp_path, monkeypatch):
    from scripts.common import storage_paths
    paths, reuse, report, new_path, _, _, _, calls, _ = capture_reuse_case(tmp_path, monkeypatch)
    monkeypatch.setattr(storage_paths, "resolve", lambda *a: paths)
    monkeypatch.setattr(extension, "load_sources", lambda *a, **k:
        (_ for _ in ()).throw(AssertionError("No full feature-universe collection")))
    output = tmp_path / "delta_capture"
    price_path, input_path = extension.capture_full_prices(output, repo_root=tmp_path,
        current_report_path=report, execution_open_manifest=new_path,
        execution_end="2026-10-05", reuse_capture=reuse)
    import json
    metadata = json.loads(input_path.read_text())
    assert metadata["captured_prices"] == extension.reference(price_path)
    assert len(pd.read_parquet(price_path)) == 4 and calls[0][2]["tickers"] == ["BB"]
    assert metadata["execution_open"]["qualified_tickers"] == ["AA", "BB"]


def prior_session_capture_case(tmp_path,monkeypatch):
    import json
    import numpy as np
    from scripts.research.a2.evaluation import demo_performance, demo_performance_prices as prices_reader
    from scripts import daily_recommendation_inputs as calendar
    hist=tmp_path/'historical.json';hist.write_text('original historical authority')
    identity=tmp_path/'mapped_members.parquet'
    pd.DataFrame([{'ticker':name,'moomoo_symbol':'US.'+name,'security_id':'id-'+name}
        for name in ('A','B','C')]).to_parquet(identity,index=False)
    universe={'report_path':str(tmp_path/'universe_report.json'),
        'universe_members_sha256':extension.reference(identity)['sha256']}
    records=[{'ticker':name,'code':'US.'+name,'security_id':'id-'+name} for name in ('A','B')]
    old_open=tmp_path/'old_open.json';old_open.write_text(json.dumps({'schema':'A2_EXECUTION_OPEN_INPUTS_V1',
        'signal_end_date':'2026-10-02','execution_end_date':'2026-10-05','records':records}))
    report=tmp_path/'source5.json';report.write_text(json.dumps({'status':'READY','data_date':'2026-10-05',
        'universe':universe,'ranked_rows':[{'ticker':'A','rank':1},{'ticker':'B','rank':2}]}))
    new_open=tmp_path/'open6.json';new_open.write_text(json.dumps({'schema':'A2_EXECUTION_OPEN_INPUTS_V1',
        'signal_end_date':'2026-10-05','execution_end_date':'2026-10-06',
        'identity_binding':extension.reference(identity),
        'records':[*records,{'ticker':'C','code':'US.C','security_id':'id-C'}]}))
    columns=['ticker','trade_date','open','high','low','close','volume']
    old=pd.DataFrame([['A','2026-10-02',9.,10.,8.,9.,100.],['B','2026-10-02',19.,20.,18.,19.,100.],
        ['A','2026-10-05',10.,np.nan,np.nan,np.nan,np.nan],
        ['B','2026-10-05',20.,np.nan,np.nan,np.nan,np.nan]],columns=columns)
    old['trade_date']=pd.to_datetime(old.trade_date)
    price_path=tmp_path/'prices.parquet';old.to_parquet(price_path,index=False)
    events=pd.DataFrame(columns=['ticker','event_date','audit_kind','resolution_status'])
    event_path=tmp_path/'events.parquet';events.to_parquet(event_path,index=False)
    metadata={'refs':[extension.reference(hist),extension.reference(report),extension.reference(old_open)],'start_date':'2023-01-03',
        'end_date':'2026-10-02','price_basis':extension.BASIS,'event_review_resolved':True,
        'captured_prices':extension.reference(price_path),'events':extension.reference(event_path),
        'execution_open':{'manifest':extension.reference(old_open),'qualified_tickers':['A','B'],
            'signal_end_date':'2026-10-02','execution_end_date':'2026-10-05','consumer_fields':['open'],
            'terminal_close_available':False,'model_feature_eligibility_granted':False,
            'qualifications':[{'ticker':name,'all_overlap_open_exact':True,
                'preserved_original_raw_vintage':True} for name in ('A','B')]}}
    inputs=tmp_path/'three_strategy_price_inputs.json';inputs.write_text(json.dumps(metadata))
    prior={'performance_period':{'end':'2026-10-05'},
        'source_refs':[extension.reference(inputs),extension.reference(price_path),extension.reference(event_path)],
        'strategies':{'HGB':{'targets':[{'signal_date':'2026-10-02','rows':[{'ticker':'B','target_weight':.1}]}]}}}
    prior_path=tmp_path/'research_manifest.json';prior_path.write_text(json.dumps(prior));prior_ref=extension.reference(prior_path)
    package={'shared_scores':{'current':{'rows':[{'ticker':'A'}]}},
        'source_refs':{'current/report.json':extension.reference(report)}}
    def bound(paths,ref=None):
        if ref!=prior_ref:raise ValueError('PRIOR_RESEARCH_IMMUTABLE_SELECTION_CHANGED')
        return package,prior,prior_ref,extension.reference(report)
    monkeypatch.setattr(extension,'bound_direct_research',bound)
    from scripts.research.a2.portfolio import selected_hgb as selected
    monkeypatch.setattr(selected,'active_policy',lambda *a:(selected.DIRECT_POLICY,report))
    monkeypatch.setattr(demo_performance,'canonical_manifest',lambda *a:(hist,None))
    monkeypatch.setattr(demo_performance,'reviewed_events',lambda *a:(True,pd.DataFrame()))
    monkeypatch.setattr(calendar,'load_frozen_binding',lambda *a:{})
    monkeypatch.setattr(calendar,'latest_completed_session',lambda *a:{'target_date':'2026-10-05',
        'sessions':['2026-10-02','2026-10-05','2026-10-06']})
    fresh=old.copy()
    fresh.loc[fresh.trade_date.eq(pd.Timestamp('2026-10-05')),['open','high','low','close','volume']]=[
        [11.,13.,9.,12.,1000.],[22.,26.,18.,24.,2000.]]
    fresh=pd.concat([fresh,pd.DataFrame([['A',pd.Timestamp('2026-10-06'),14.,np.nan,np.nan,np.nan,np.nan],
        ['B',pd.Timestamp('2026-10-06'),28.,np.nan,np.nan,np.nan,np.nan]],columns=columns)],ignore_index=True)
    delta={'prices':fresh,'events':events.copy(),'gaps':[],'refs':[extension.reference(report),extension.reference(new_open)],
        'price_basis':extension.BASIS,'event_review':None,'execution_open':{'manifest':extension.reference(new_open),
            'signal_end_date':'2026-10-05','execution_end_date':'2026-10-06','qualified_tickers':['A','B']}}
    calls=[]
    def qualify(*a,**kw):calls.append(kw);return delta
    monkeypatch.setattr(prices_reader,'load_execution_prices',qualify)
    paths=SimpleNamespace(daily_root=tmp_path,repo_root=tmp_path)
    return paths,prior_ref,report,new_open,old,delta,calls,inputs,hist


def test_cross_session_capture_keeps_original_open5_fills_only_mature_fields_and_qualifies_open6(tmp_path,monkeypatch):
    paths,prior,report,new_open,old,delta,calls,inputs,hist=prior_session_capture_case(tmp_path,monkeypatch)
    originals={p:p.read_bytes() for p in (inputs,Path(prior['path']),hist)}
    result,metadata=extension._advance_research_capture(paths,prior,report,new_open,'2026-10-06')
    indexed=result['prices'].set_index(['ticker','trade_date'])
    assert indexed.loc[('A',pd.Timestamp('2026-10-05')),'open']==10.
    assert indexed.loc[('B',pd.Timestamp('2026-10-05')),'open']==20.
    assert indexed.loc[('A',pd.Timestamp('2026-10-05')),'close']==12.
    assert indexed.loc[('B',pd.Timestamp('2026-10-05')),'close']==24.
    terminal=result['prices'].loc[result['prices'].trade_date.eq(pd.Timestamp('2026-10-06'))]
    assert terminal[['high','low','close','volume']].isna().all().all()
    assert terminal.open.tolist()==[14.,28.]
    pd.testing.assert_frame_equal(result['prices'].loc[result['prices'].trade_date.eq(pd.Timestamp('2026-10-02'))].reset_index(drop=True),
        old.loc[old.trade_date.eq(pd.Timestamp('2026-10-02')),result['prices'].columns].reset_index(drop=True),check_exact=True)
    assert calls[0]['tickers']==['A','B'] and calls[0]['execution_end']=='2026-10-06'
    assert metadata['research_input_owner']==prior
    assert metadata['capture_reuse']['ignored_recorded_vintage_revisions']['open']==2
    assert metadata['capture_reuse']['known_price_fields_all_exact'] is True
    assert len(metadata['capture_reuse']['matured_fields'])==8
    assert all(p.read_bytes()==b for p,b in originals.items())


@pytest.mark.parametrize('fault,reason',[('bad_prior','IMMUTABLE_SELECTION'),('changed_inputs','SOURCE_HASH'),
    ('historical_authority','SOURCE_HASH'),('missing_close5','MATURE_FIELD'),('future_close6','NEW_OPEN_PHASE'),
    ('old_date_added','OLD_DATE_ADDITION'),('event_revision','PAST_EVENT_REVISION')])
def test_cross_session_capture_refuses_bad_binding_missing_maturity_future_close_or_past_event(tmp_path,monkeypatch,fault,reason):
    import numpy as np
    paths,prior,report,new_open,old,delta,calls,inputs,hist=prior_session_capture_case(tmp_path,monkeypatch)
    if fault=='bad_prior':prior={**prior,'sha256':'0'*64}
    elif fault=='changed_inputs':inputs.write_text('{}')
    elif fault=='historical_authority':hist.write_text('changed')
    elif fault=='missing_close5':delta['prices'].loc[(delta['prices'].ticker=='B') & delta['prices'].trade_date.eq(pd.Timestamp('2026-10-05')),'close']=np.nan
    elif fault=='future_close6':delta['prices'].loc[delta['prices'].trade_date.eq(pd.Timestamp('2026-10-06')),'close']=14.
    elif fault=='old_date_added':
        added=delta['prices'].iloc[[0]].copy();added['trade_date']=pd.Timestamp('2026-10-01')
        delta['prices']=pd.concat([delta['prices'],added],ignore_index=True)
    else:delta['events']=pd.DataFrame([{'ticker':'A','event_date':'2026-10-05','audit_kind':'LATE_EVENT','resolution_status':'RESOLVED'}])
    with pytest.raises(ValueError,match=reason):extension._advance_research_capture(paths,prior,report,new_open,'2026-10-06')


def test_prior_capture_leaf_is_chosen_by_bound_parent_lineage_not_filename_order(tmp_path,monkeypatch):
    import json
    paths,prior,report,new_open,old,delta,calls,inputs,hist=prior_session_capture_case(tmp_path,monkeypatch)
    manifest=json.loads(Path(prior['path']).read_text());original=json.loads(inputs.read_text())
    child=tmp_path/'child/price_inputs.json';child.parent.mkdir()
    newer={**original,'capture_reuse':{'inputs_ref':extension.reference(inputs)}}
    child.write_text(json.dumps(newer));manifest['source_refs'].append(extension.reference(child))
    selected,_=extension.prior_price_capture(manifest)
    assert selected==extension.reference(child)
    unrelated=tmp_path/'unrelated/price_inputs.json';unrelated.parent.mkdir();unrelated.write_text(json.dumps(original))
    manifest['source_refs'].append(extension.reference(unrelated))
    with pytest.raises(ValueError,match='AMBIGUOUS'):extension.prior_price_capture(manifest)


@pytest.mark.parametrize('policy',['DIRECT','LEGACY'])
def test_prior_feature_owner_ignores_repaired_used_cash_vintage_and_accepts_single_new_signal(tmp_path,monkeypatch,policy):
    import numpy as np
    from scripts.research.a2.portfolio import selected_hgb as selected
    root=tmp_path/'frozen';(root/'test2026').mkdir(parents=True)
    def rows(day):
        return pd.DataFrame({'signal_date':pd.Timestamp(day),'ticker':[f'T{i:02d}' for i in range(1,41)],
            'security_id':[f'id{i:02d}' for i in range(1,41)],'raw_rank':list(range(1,41)),
            'raw_score':[1-i/1000 for i in range(1,41)],'f1':[.01]*40,
            'pred_hgb':[i/1000 for i in range(1,41)],'pred_q10':[-.02]*40})
    recorded=rows('2026-10-02');bootstrap=root/'test2026/predictions.parquet'
    future=rows('2027-01-01');future['pred_hgb']=999.
    pd.concat([recorded,future],ignore_index=True).to_parquet(bootstrap,index=False)
    current=rows('2026-10-05').drop(columns=['pred_hgb','pred_q10']).rename(columns={'signal_date':'trade_date'})
    current['raw_score']+=.02
    feature=tmp_path/'selected_hgb_features.parquet';current.to_parquet(feature,index=False)
    source_ref=extension.reference(feature)
    snapshot={'signal_date':'2026-10-05','source_refs':{'current/selected_hgb_features.parquet':source_ref},
        'observation_only_source_refs':[],
        'report_binding':{'raw_top40':current[['ticker','security_id','raw_rank','raw_score']].to_dict('records')}}
    old_cash={'signal_date':'2026-10-02','source_refs':{},'observation_only_source_refs':[],
        'report_binding':{'raw_top40':[]}}
    owner=tmp_path/'canonical.json';owner.write_text('synthetic owner binding')
    prior={'strategies':{'HGB':{'targets':[{'signal_date':'2026-10-02'}]}},'source_refs':[extension.reference(bootstrap)],
        'shared_scores_historical':selected._score_rows(recorded,signal_date='2026-10-02')}
    normal_calls=[]
    def normalise(frame,runtime):
        day=str(pd.Timestamp(frame['signal_date' if 'signal_date' in frame else 'trade_date'].iloc[0]).date())
        normal_calls.append(day);return frame.rename(columns={'trade_date':'signal_date'}).copy(),day
    fake=SimpleNamespace(REPLAY_HASHES={'test2026/predictions.parquet':extension.reference(bootstrap)['sha256']},
        FEATURES=('f1',),_normalise_day=normalise,active_policy=lambda paths:(policy,owner),
        _score_rows=selected._score_rows)
    monkeypatch.setattr(extension,'_accepted_owner',lambda *a:(extension.reference(owner),
        {'2026-10-02':old_cash,'2026-10-05':snapshot},[]))
    frames,refs,observation,accepted=extension._load_prior_sources(SimpleNamespace(),fake,root,prior,'2026-10-05')
    assert set(accepted)=={'2026-10-05'}
    assert normal_calls==['2026-10-05']
    assert frames[0].signal_date.dt.strftime('%Y-%m-%d').unique().tolist()==['2026-10-02']
    assert len(frames)==2 and observation==extension.reference(owner)
    predicted=[]
    class FrozenModel:
        def __init__(self,q10=False):self.q10=q10
        def predict(self,inputs):
            predicted.append(len(inputs));return np.full(len(inputs),-.02) if self.q10 else np.arange(1,41)/1000
        def fit(self,*a,**kw):raise AssertionError('No fitting allowed')
    panel=extension.score_panel(frames,fake,{'model':FrozenModel(),'q10':FrozenModel(True)})
    extension._verify_prior_scores(panel,prior,fake)
    assert predicted==[40,40] # only the new signal needs frozen inference
    assert set(panel.signal_date.dt.strftime('%Y-%m-%d'))=={'2026-10-02','2026-10-05'}
    assert panel.loc[panel.signal_date.eq(pd.Timestamp('2026-10-05')),'raw_score'].iloc[0]==current.raw_score.iloc[0]
    changed=panel.copy();changed.loc[changed.signal_date.eq(pd.Timestamp('2026-10-02')),'pred_hgb']+=.001
    with pytest.raises(ValueError,match='SHARED_SCORE_CHANGED'):extension._verify_prior_scores(changed,prior,fake)


def direct_bound_research_fixture(tmp_path,monkeypatch):
    import importlib.util
    import json
    from scripts.research.a2.portfolio import selected_hgb as selected
    from scripts.research.a2.evaluation import hgb_policy_alignment as alignment
    from apps.demo_console.adapters import selected_strategies_reader as reader
    from unittest.mock import Mock
    spec=importlib.util.spec_from_file_location('strict_direct_research_fixture',
        Path(__file__).parents[4]/'tests/research/a2/portfolio/test_selected_hgb_history.py')
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    _,package,manifest,path,output,contract=fixture.direct_repaired_research_fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(selected,'active_policy',lambda *a:(selected.DIRECT_POLICY,output))
    monkeypatch.setattr(alignment,'frozen_contract',lambda *a:({'frozen_contract':contract},{}))
    displayed={**package,'package_path':str(output),'package_sha256':extension.reference(output)['sha256']}
    loader=Mock(return_value=displayed);monkeypatch.setattr(reader,'load_package',loader)
    paths=SimpleNamespace(repo_root=tmp_path,daily_root=output.parent)
    return paths,package,manifest,path,output,contract,displayed,loader


def test_bound_direct_research_keeps_canonical_manifest_and_uses_strict_display_owner(tmp_path,monkeypatch):
    paths,package,manifest,path,output,contract,displayed,loader=direct_bound_research_fixture(tmp_path,monkeypatch)
    result=extension.bound_direct_research(paths,extension.reference(path))
    assert result[1]==manifest and result[2]==extension.reference(path)
    assert result[3]==extension.reference(output);loader.assert_not_called()
    result=extension.bound_direct_research(paths)
    loader.assert_called_once_with()
    assert result[0] is displayed and result[1]==manifest
    assert result[2]==extension.reference(path) and result[3]==extension.reference(output)


@pytest.mark.parametrize('fault,reason',[('arbitrary_prior','IMMUTABLE_SELECTION_CHANGED'),
    ('wrong_base_hash','OBSERVATION_CHANGED'),('wrong_base_path','OBSERVATION_CHANGED'),
    ('contract','POLICY_CONTRACT_UNBOUND'),('tampered_output','SOURCE_HASH_MISMATCH')])
def test_bound_direct_research_refuses_unbound_prior_display_or_policy(tmp_path,monkeypatch,fault,reason):
    import json
    paths,package,manifest,path,output,contract,displayed,loader=direct_bound_research_fixture(tmp_path,monkeypatch)
    ref=None
    if fault=='arbitrary_prior':ref={**extension.reference(path),'sha256':'0'*64}
    elif fault=='wrong_base_hash':displayed['package_sha256']='0'*64
    elif fault=='wrong_base_path':displayed['package_path']=str(tmp_path/'wrong_latest.json')
    elif fault=='contract':displayed['source_hashes']['policy/frozen_contract']='0'*64
    else:Path(manifest['strategies']['HGB_DIAG_5']['outputs']['daily']['path']).write_bytes(b'tampered')
    with pytest.raises(ValueError,match=reason):extension.bound_direct_research(paths,ref)


def test_cross_session_entry_reuses_existing_writer_and_keeps_mutable_owner_as_observation(tmp_path,monkeypatch):
    import json
    from scripts.common import storage_paths
    paths,prior,report,new_open,old,delta,calls,inputs,hist=prior_session_capture_case(tmp_path,monkeypatch)
    owner=tmp_path/'latest.json';owner.write_text('canonical current source identity')
    old_bound=extension.bound_direct_research
    def bound(*a,**kw):
        package,manifest,ref,_=old_bound(*a,**kw)
        return package,manifest,ref,extension.reference(owner)
    monkeypatch.setattr(extension,'bound_direct_research',bound)
    monkeypatch.setattr(storage_paths,'resolve',lambda *a:paths)
    monkeypatch.setattr(extension,'load_sources',lambda *a,**kw:
        (_ for _ in ()).throw(AssertionError('No full historical source glob')))
    prices,metadata_path=extension.capture_full_prices(tmp_path/'capture6',repo_root=tmp_path,
        current_report_path=report,execution_open_manifest=new_open,execution_end='2026-10-06',
        prior_research_manifest=prior)
    metadata=json.loads(metadata_path.read_text())
    assert metadata['captured_prices']==extension.reference(prices)
    assert metadata['research_input_owner']==prior
    assert metadata['selected_package_observation']==extension.reference(owner)
    assert extension.reference(owner) not in metadata['refs']
    assert len(calls)==1 and calls[0]['tickers']==['A','B']
    owner.write_text('next current daily publication')
    extension.verify_refs(metadata['refs']) # a normal current publish cannot break accepted input refs
    frame=pd.read_parquet(prices)
    assert frame.loc[frame.trade_date.eq(pd.Timestamp('2026-10-05')),'open'].tolist()==[10.,20.]
    assert frame.loc[frame.trade_date.eq(pd.Timestamp('2026-10-06')),['close','high','low','volume']].isna().all().all()


@pytest.mark.parametrize('eligible',[True,False])
def test_cross_session_new_ticker_history_requires_current_qualified_raw40_membership(tmp_path,monkeypatch,eligible):
    import json
    import numpy as np
    paths,prior,report,new_open,old,delta,calls,inputs,hist=prior_session_capture_case(tmp_path,monkeypatch)
    bound=extension.bound_direct_research
    new_report=tmp_path/'source5_new_raw_candidate.json'
    new_report.write_text(json.dumps({'status':'READY','data_date':'2026-10-05',
        'universe':json.loads(report.read_text())['universe'],
        'ranked_rows':[{'ticker':'A','rank':1},{'ticker':'B','rank':2},{'ticker':'C','rank':3 if eligible else 41}]}))
    def newer_owner(*a,**kw):
        package,manifest,ref,observation=bound(*a,**kw)
        package={**package,'source_refs':{'current/report.json':extension.reference(new_report)}}
        return package,manifest,ref,observation
    monkeypatch.setattr(extension,'bound_direct_research',newer_owner)
    columns=delta['prices'].columns
    added=pd.DataFrame([['C',pd.Timestamp('2026-10-02'),29.,30.,28.,29.,100.],
        ['C',pd.Timestamp('2026-10-05'),30.,33.,29.,32.,1000.],
        ['C',pd.Timestamp('2026-10-06'),34.,np.nan,np.nan,np.nan,np.nan]],columns=columns)
    delta['prices']=pd.concat([delta['prices'],added],ignore_index=True)
    delta['refs'].append(extension.reference(new_report))
    delta['execution_open']['qualified_tickers']=['A','B','C']
    if not eligible:
        # C can be required by a positive old target or HGB display; neither grants
        # authority to backfill a ticker's never captured historical rows.
        owner=newer_owner
        def hgb_only(*a,**kw):
            package,manifest,ref,observation=owner(*a,**kw)
            package={**package,'shared_scores':{'current':{'rows':[{'ticker':'A'},{'ticker':'C'}]}}}
            return package,manifest,ref,observation
        monkeypatch.setattr(extension,'bound_direct_research',hgb_only)
        with pytest.raises(ValueError,match='UNBOUND_OLD_DATE_ADDITION'):
            extension._advance_research_capture(paths,prior,new_report,new_open,'2026-10-06')
        return
    result,metadata=extension._advance_research_capture(paths,prior,new_report,new_open,'2026-10-06')
    assert metadata['capture_reuse']['new_qualified_raw_candidate_history']==['C']
    assert calls[0]['tickers']==['A','B','C']
    before=old.set_index(['ticker','trade_date'])
    after=result['prices'].set_index(['ticker','trade_date'])
    for column in ('open','high','low','close','volume'):
        known=before[column].notna()
        pd.testing.assert_series_equal(before.loc[known,column],after.loc[before.index[known],column],check_exact=True)
    assert set(result['prices'].ticker)=={'A','B','C'}


@pytest.mark.parametrize('fault',[None,'lineage','known_open','known_volume','missing_old_key'])
def test_cross_session_private_replay_checks_bound_capture_and_actual_known_price_fields(tmp_path,monkeypatch,fault):
    import json
    paths,prior,report,new_open,old,delta,calls,inputs,hist=prior_session_capture_case(tmp_path,monkeypatch)
    result,metadata=extension._advance_research_capture(paths,prior,report,new_open,'2026-10-06')
    manifest=json.loads(Path(prior['path']).read_text())
    captured=tmp_path/'capture6.parquet';result['prices'].to_parquet(captured,index=False)
    metadata['captured_prices']=extension.reference(captured)
    if fault=='lineage':metadata['capture_reuse']['inputs_ref']={**extension.reference(inputs),'sha256':'0'*64}
    elif fault in {'known_open','known_volume'}:
        field='open' if fault=='known_open' else 'volume'
        result['prices'].loc[result['prices'].trade_date.eq(pd.Timestamp('2026-10-02')),field]+=1.
    elif fault=='missing_old_key':result['prices']=result['prices'].iloc[1:].copy()
    if fault:
        with pytest.raises(ValueError,match='PRIOR_RESEARCH_CAPTURE'):
            extension._verify_prior_price_prefix(result['prices'],metadata,manifest,extension.reference(captured))
    else:
        extension._verify_prior_price_prefix(result['prices'],metadata,manifest,extension.reference(captured))
        assert result['prices'].loc[result['prices'].trade_date.eq(pd.Timestamp('2026-10-05')),'close'].tolist()==[12.,24.]


@pytest.mark.parametrize('field',['open','close','high','low','volume'])
def test_cross_session_delta_rejects_every_changed_old_closed_known_field(tmp_path,monkeypatch,field):
    paths,prior,report,new_open,old,delta,calls,inputs,hist=prior_session_capture_case(tmp_path,monkeypatch)
    delta['prices'].loc[delta['prices'].trade_date.eq(pd.Timestamp('2026-10-02')),field]+=1.
    with pytest.raises(ValueError,match='ACCEPTED_CLOSED_FIELD_CHANGED:'+field):
        extension._advance_research_capture(paths,prior,report,new_open,'2026-10-06')


@pytest.mark.parametrize('fault',['new_sid','current_mapped_sid','old_known_terminal_field','unqualified_old_terminal'])
def test_cross_session_maturity_binds_old_open_only_phase_and_exact_security_identity(tmp_path,monkeypatch,fault):
    import json
    paths,prior,report,new_open,old,delta,calls,inputs,hist=prior_session_capture_case(tmp_path,monkeypatch)
    metadata=json.loads(inputs.read_text())
    if fault=='new_sid':
        document=json.loads(new_open.read_text());document['records'][1]['security_id']='different-SID'
        old_ref=extension.reference(new_open);new_open.write_text(json.dumps(document))
        delta['refs']=[extension.reference(new_open) if r==old_ref else r for r in delta['refs']]
        delta['execution_open']['manifest']=extension.reference(new_open)
    elif fault=='current_mapped_sid':
        universe=json.loads(report.read_text())['universe']
        members=Path(universe['report_path']).parent/'mapped_members.parquet'
        frame=pd.read_parquet(members);frame.loc[frame.ticker.eq('B'),'security_id']='different-SID'
        frame.to_parquet(members,index=False)
        payload=json.loads(report.read_text());payload['universe']['universe_members_sha256']=extension.reference(members)['sha256']
        report.write_text(json.dumps(payload))
        document=json.loads(new_open.read_text());document['identity_binding']=extension.reference(members)
        new_open.write_text(json.dumps(document));delta['execution_open']['manifest']=extension.reference(new_open)
        delta['refs']=[extension.reference(report),extension.reference(new_open)]
    elif fault=='old_known_terminal_field':
        old.loc[old.trade_date.eq(pd.Timestamp('2026-10-05')),'high']=12.
    else:metadata['execution_open']['qualified_tickers']=['A']
    with pytest.raises(ValueError,match='PRIOR_PRICE_MATURITY'):
        extension._prior_open_maturity(metadata,old,'2026-10-05',delta,json.loads(report.read_text()),hist)


def test_cross_session_closed_followup_keeps_same_sid_and_matures_only_prior_unknown_fields(tmp_path,monkeypatch):
    paths,prior,report,new_open,old,delta,calls,inputs,hist=prior_session_capture_case(tmp_path,monkeypatch)
    # A later completed-close source is still bound to current mapped identities.
    import json
    metadata=json.loads(inputs.read_text())
    fresh={k:v for k,v in delta.items() if k!='execution_open'}
    keys,refs=extension._prior_open_maturity(metadata,old,'2026-10-05',fresh,json.loads(report.read_text()),hist)
    assert keys=={('A',pd.Timestamp('2026-10-05')),('B',pd.Timestamp('2026-10-05'))}
    assert extension.reference(tmp_path/'mapped_members.parquet') in refs


@pytest.mark.parametrize('matching_sid',[True,False])
def test_cross_session_maturity_keeps_original_historical_held_identity_fallback(tmp_path,monkeypatch,matching_sid):
    import json
    paths,prior,report,new_open,old,delta,calls,inputs,hist=prior_session_capture_case(tmp_path,monkeypatch)
    metadata=json.loads(inputs.read_text())
    mapping=tmp_path/'mapped_members.parquet'
    members=pd.read_parquet(mapping);members=members.loc[~members.ticker.eq('B')]
    members.to_parquet(mapping,index=False)
    current=json.loads(report.read_text());current['universe']['universe_members_sha256']=extension.reference(mapping)['sha256']
    next_document=json.loads(new_open.read_text());next_document['identity_binding']=extension.reference(mapping)
    new_open.write_text(json.dumps(next_document));delta['execution_open']['manifest']=extension.reference(new_open)
    delta['refs']=[extension.reference(new_open)]
    historical_inputs=tmp_path/'historical_identity.json'
    historical_inputs.write_text(json.dumps({'lineage':[{'ticker':'B','code':'US.B',
        'cusips':['id-B' if matching_sid else 'different-SID']}]}))
    historical_ref=extension.reference(historical_inputs)
    historical=tmp_path/'historical_manifest.json';historical.write_text(json.dumps({'price_manifest':historical_ref}))
    parent_path=Path(metadata['execution_open']['manifest']['path'])
    document=json.loads(parent_path.read_text());document['historical_identity_binding']=historical_ref
    old_ref=extension.reference(parent_path);parent_path.write_text(json.dumps(document))
    metadata['execution_open']['manifest']=extension.reference(parent_path)
    metadata['refs']=[extension.reference(parent_path) if r==old_ref else r for r in metadata['refs']]
    if not matching_sid:
        with pytest.raises(ValueError,match='HISTORICAL_SECURITY_IDENTITY_CHANGED:B'):
            extension._prior_open_maturity(metadata,old,'2026-10-05',delta,current,historical)
        return
    keys,refs=extension._prior_open_maturity(metadata,old,'2026-10-05',delta,current,historical)
    assert ('B',pd.Timestamp('2026-10-05')) in keys
    assert historical_ref in refs # no current Raw membership gate for already held names


def test_previous_closed_capture_cannot_claim_an_open_only_maturity_exception(tmp_path,monkeypatch):
    import json
    paths,prior,report,new_open,old,delta,calls,inputs,hist=prior_session_capture_case(tmp_path,monkeypatch)
    metadata=json.loads(inputs.read_text());metadata.pop('execution_open')
    with pytest.raises(ValueError,match='UNKNOWN_FIELD_WITHOUT_OPEN_PHASE'):
        extension._prior_open_maturity(metadata,old,'2026-10-05',delta,json.loads(report.read_text()),hist)
    mature=old.copy()
    current=delta['prices'].loc[delta['prices'].trade_date.eq(pd.Timestamp('2026-10-05'))].set_index('ticker')
    for field in ('close','high','low','volume'):
        mask=mature.trade_date.eq(pd.Timestamp('2026-10-05'))
        mature.loc[mask,field]=mature.loc[mask,'ticker'].map(current[field])
    keys,_=extension._prior_open_maturity(metadata,mature,'2026-10-05',delta,json.loads(report.read_text()),hist)
    assert not keys # a closed vintage provides no terminal open exception


# Legacy restoration extends the original accepted-vintage owner, never a replay fork.
def legacy_bound_research_fixture(tmp_path, monkeypatch):
    import json
    from copy import deepcopy
    from scripts.research.a2.portfolio import selected_hgb as selected
    from scripts.research.a2.evaluation import hgb_policy_alignment as alignment
    paths, original, manifest, path, output, contract, _, loader = direct_bound_research_fixture(tmp_path, monkeypatch)
    package = deepcopy(original)
    package['policy_id'] = manifest['policy_id'] = selected.LEGACY_POLICY
    for sid, ticker in zip(selected.STRATEGY_IDS, ('T01', 'T02')):
        app = package['strategies'][sid]['application']
        app['policy_id'] = selected.LEGACY_POLICY
        app['rows'][0]['ticker'] = ticker
        package['strategies'][sid].pop('application_history', None)
    for key in list(package['source_refs']):
        if key.startswith(('history/', 'history_revision/', 'history_repair/')) or key == 'policy/frozen_contract':
            package['source_refs'].pop(key); package['source_hashes'].pop(key)
    path.write_text(json.dumps(manifest))
    ref = extension.reference(path)
    package['performance_extension']['manifest'] = ref
    package['source_refs']['performance_extension/manifest'] = ref
    package['source_hashes']['performance_extension/manifest'] = ref['sha256']
    output.write_text(json.dumps(package))
    displayed = {**package, 'package_path': str(output), 'package_sha256': extension.reference(output)['sha256']}
    loader.return_value = displayed
    monkeypatch.setattr(selected, 'active_policy', lambda *a: (selected.LEGACY_POLICY, output))
    monkeypatch.setattr(alignment, 'frozen_contract', lambda *a: pytest.fail('Legacy must not inherit the direct task contract'))
    return paths, package, manifest, path, output, displayed, loader


def test_legacy_research_binding_reuses_canonical_and_strict_display_without_direct_contract(tmp_path, monkeypatch):
    paths, package, manifest, path, output, displayed, loader = legacy_bound_research_fixture(tmp_path, monkeypatch)
    result = extension.bound_selected_research(paths, extension.reference(path))
    assert result[0] == package and result[1] == manifest and result[2] == extension.reference(path)
    assert result[3] == extension.reference(output)
    loader.assert_not_called()
    observed = extension.bound_selected_research(paths)
    loader.assert_called_once_with()
    assert observed[0] is displayed and observed[1] == manifest
    with pytest.raises(ValueError, match='PRIOR_DIRECT_POLICY_REQUIRED'):
        extension.bound_direct_research(paths, extension.reference(path))


@pytest.mark.parametrize('fault,reason', [
    ('wrong_active_policy', 'ACTIVE_POLICY_CHANGED'), ('wrong_base_path', 'OBSERVATION_CHANGED'),
    ('wrong_base_hash', 'OBSERVATION_CHANGED'), ('wrong_display_policy', 'OBSERVATION_CHANGED'),
    ('arbitrary_prior', 'IMMUTABLE_SELECTION_CHANGED'), ('manifest_policy', 'CONTRACT_INVALID'),
    ('output_bytes', 'SOURCE_HASH_MISMATCH'), ('model_fit', 'MODEL_IDENTITY_CHANGED'),
    ('model_hash', 'MODEL_IDENTITY_CHANGED'), ('future_period', '2026_BOUNDARY'),
    ('future_score', '2026_BOUNDARY'), ('cost', 'CONTRACT_INVALID')])
def test_legacy_bound_research_rejects_unbound_or_scientifically_changed_prior(tmp_path, monkeypatch, fault, reason):
    import json
    from scripts.research.a2.portfolio import selected_hgb as selected
    paths, package, manifest, path, output, displayed, loader = legacy_bound_research_fixture(tmp_path, monkeypatch)
    ref = None
    if fault == 'wrong_active_policy':
        monkeypatch.setattr(selected, 'active_policy', lambda *a: (selected.DIRECT_POLICY, output))
    elif fault == 'wrong_base_path': displayed['package_path'] = str(tmp_path / 'not_canonical.json')
    elif fault == 'wrong_base_hash': displayed['package_sha256'] = '0' * 64
    elif fault == 'wrong_display_policy': displayed['policy_id'] = selected.DIRECT_POLICY
    elif fault == 'arbitrary_prior': ref = {**extension.reference(path), 'sha256': '0' * 64}
    elif fault == 'output_bytes': Path(manifest['strategies']['HGB_DIAG_5']['outputs']['daily']['path']).write_bytes(b'tampered')
    elif fault in {'model_fit', 'model_hash'}:
        if fault == 'model_fit': displayed['model_fit_calls'] = True
        else: displayed['shared_scores']['model_sha256'] = '0' * 64
    else:
        if fault == 'manifest_policy': manifest['policy_id'] = selected.DIRECT_POLICY
        elif fault == 'future_period': manifest['performance_period']['end'] = '2027-01-01'
        elif fault == 'future_score': manifest['shared_scores_historical'][0]['signal_date'] = '2027-01-01'
        else: manifest['cost_one_way'] = .001
        path.write_text(json.dumps(manifest)); changed = extension.reference(path)
        displayed['performance_extension']['manifest'] = changed
        displayed['source_refs']['performance_extension/manifest'] = changed
        displayed['source_hashes']['performance_extension/manifest'] = changed['sha256']
    with pytest.raises(ValueError, match=reason): extension.bound_selected_research(paths, ref)


@pytest.mark.parametrize('fault,reason', [(None,None), ('old_open','ACCEPTED_CLOSED_FIELD_CHANGED'),
    ('old_volume','ACCEPTED_CLOSED_FIELD_CHANGED'), ('future_close','NEW_OPEN_PHASE'),
    ('identity','SECURITY_IDENTITY_CHANGED'), ('hash','SOURCE_HASH')])
def test_legacy_cross_session_uses_same_exact_capture_and_maturity_guards(tmp_path, monkeypatch, fault, reason):
    import json
    from scripts.research.a2.portfolio import selected_hgb as selected
    paths, prior, report, new_open, old, delta, calls, inputs, hist = prior_session_capture_case(tmp_path, monkeypatch)
    bound = extension.bound_direct_research
    monkeypatch.setattr(selected, 'active_policy', lambda *a: (selected.LEGACY_POLICY, report))
    monkeypatch.setattr(extension, '_bound_selected_research', bound)
    originals = {p:p.read_bytes() for p in (inputs, Path(prior['path']), hist)}
    if fault in {'old_open','old_volume'}:
        key = 'open' if fault == 'old_open' else 'volume'
        delta['prices'].loc[delta['prices'].trade_date.eq(pd.Timestamp('2026-10-02')), key] += 1.
    elif fault == 'future_close': delta['prices'].loc[delta['prices'].trade_date.eq(pd.Timestamp('2026-10-06')), 'close'] = 999.
    elif fault == 'identity':
        document = json.loads(new_open.read_text()); document['records'][0]['security_id'] = 'wrong-security'
        new_open.write_text(json.dumps(document)); delta['refs'][-1] = extension.reference(new_open)
        delta['execution_open']['manifest'] = extension.reference(new_open)
    elif fault == 'hash': inputs.write_text('{}')
    if fault:
        with pytest.raises(ValueError, match=reason): extension._advance_research_capture(paths, prior, report, new_open, '2026-10-06')
        return
    result, metadata = extension._advance_research_capture(paths, prior, report, new_open, '2026-10-06')
    assert metadata['research_input_owner'] == prior and metadata['capture_reuse']['known_price_fields_all_exact'] is True
    assert result['prices'].loc[result['prices'].trade_date.eq(pd.Timestamp('2026-10-06')), ['high','low','close','volume']].isna().all().all()
    assert all(p.read_bytes() == data for p,data in originals.items())
    captured = tmp_path / 'legacy_advance.parquet'; result['prices'].to_parquet(captured, index=False)
    metadata['captured_prices'] = extension.reference(captured)
    extension._verify_prior_price_prefix(result['prices'], metadata, json.loads(Path(prior['path']).read_text()), extension.reference(captured))


@pytest.mark.parametrize('same_policy', [True, False])
@pytest.mark.parametrize('implicit_package', [False,True])
def test_legacy_explicit_replay_prior_reaches_original_bounded_source_branch_only_for_same_policy(tmp_path, monkeypatch, same_policy,implicit_package):
    import json
    from scripts.common import storage_paths
    from scripts.research.a2.portfolio import selected_hgb as selected
    from scripts.research.a2.evaluation import demo_performance
    paths, prior_ref, report, new_open, old, delta, calls, inputs, hist = prior_session_capture_case(tmp_path, monkeypatch)
    bound = extension.bound_direct_research
    monkeypatch.setattr(selected, 'active_policy', lambda *a: (selected.LEGACY_POLICY, report))
    monkeypatch.setattr(extension, '_bound_selected_research', bound)
    result, metadata = extension._advance_research_capture(paths, prior_ref, report, new_open, '2026-10-06')
    prior = json.loads(Path(prior_ref['path']).read_text())
    prior['policy_id'] = selected.LEGACY_POLICY if same_policy else selected.DIRECT_POLICY
    monkeypatch.setattr(extension, 'bound_selected_research', lambda *a: ({} if implicit_package else {'policy_id': selected.LEGACY_POLICY}, prior, prior_ref, extension.reference(report)))
    monkeypatch.setattr(storage_paths, 'resolve', lambda *a: paths)
    monkeypatch.setattr(selected, 'verify_frozen', lambda *a: tmp_path)
    monkeypatch.setattr(selected, '_runtime', lambda *a: {})
    monkeypatch.setattr(demo_performance, 'reviewed_events', lambda *a: (True,pd.DataFrame()))
    metadata['execution_open'].update(terminal_close_available=False, model_feature_eligibility_granted=False)
    captured = tmp_path / 'continued.parquet'; result['prices'].to_parquet(captured,index=False)
    metadata['captured_prices'] = extension.reference(captured)
    result['events']['event_date'] = pd.Series(dtype='datetime64[ns]')
    event_path = tmp_path / 'continued_events.parquet'; result['events'].to_parquet(event_path,index=False)
    metadata['events'] = extension.reference(event_path)
    metadata['refs'].append(metadata['events'])
    input_path = tmp_path / 'continued_inputs.json'; input_path.write_text(json.dumps(metadata))
    class ReachedOriginalSources(Exception): pass
    seen = []
    def bounded(*a): seen.append(a); raise ReachedOriginalSources
    monkeypatch.setattr(extension, '_load_prior_sources', bounded)
    expected = ReachedOriginalSources if same_policy else ValueError
    with pytest.raises(expected):
        extension.run_extension(captured,input_path,tmp_path/'not_published',repo_root=tmp_path,
            target_date='2026-10-05',policy=selected.LEGACY_POLICY,execution_open_manifest=new_open,
            execution_end='2026-10-06',prior_research_manifest=prior_ref)
    assert bool(seen) == same_policy
    assert not (tmp_path/'not_published').exists()



def test_original_legacy_package_schema_without_policy_uses_only_original_legacy_default(tmp_path,monkeypatch):
    import json
    from scripts.research.a2.portfolio import selected_hgb as selected
    from scripts.research.a2.evaluation import selected_performance_update as update
    paths,package,manifest,path,output,displayed,loader=legacy_bound_research_fixture(tmp_path,monkeypatch)
    package.pop('policy_id');displayed.pop('policy_id')
    output.write_text(json.dumps(package));displayed['package_sha256']=extension.reference(output)['sha256']
    assert update.verified_selected_research(package)[0]==manifest
    bound=extension.bound_selected_research(paths,extension.reference(path))
    assert 'policy_id' not in bound[0] and bound[1]['policy_id']==selected.LEGACY_POLICY
    loaded=extension.bound_selected_research(paths)
    assert loaded[0] is displayed and loaded[1]==manifest
    with pytest.raises(ValueError,match='DIRECT_RESEARCH_POLICY_REQUIRED'):update.verified_direct_research(package)
    with pytest.raises(ValueError,match='PRIOR_DIRECT_POLICY_REQUIRED'):extension.bound_direct_research(paths)
    monkeypatch.setattr(selected,'active_policy',lambda *a:(selected.DIRECT_POLICY,output))
    with pytest.raises(ValueError,match='ACTIVE_POLICY_CHANGED'):extension.bound_selected_research(paths)


@pytest.mark.parametrize('fault',['direct_manifest','missing_manifest_policy','unknown_package_policy'])
def test_original_legacy_policy_default_does_not_relabel_direct_or_unknown_manifest(tmp_path,monkeypatch,fault):
    import json
    from scripts.research.a2.portfolio import selected_hgb as selected
    from scripts.research.a2.evaluation import selected_performance_update as update
    paths,package,manifest,path,output,displayed,loader=legacy_bound_research_fixture(tmp_path,monkeypatch)
    package.pop('policy_id')
    if fault=='direct_manifest':manifest['policy_id']=selected.DIRECT_POLICY
    elif fault=='missing_manifest_policy':manifest.pop('policy_id')
    else:package['policy_id']='UNRECOGNIZED_POLICY'
    path.write_text(json.dumps(manifest));ref=extension.reference(path)
    package['performance_extension']['manifest']=ref
    package['source_refs']['performance_extension/manifest']=ref
    package['source_hashes']['performance_extension/manifest']=ref['sha256']
    with pytest.raises(ValueError):update.verified_selected_research(package)


def test_direct_wrappers_require_explicit_direct_even_with_byte_qualified_direct_manifest(tmp_path,monkeypatch):
    import json
    from scripts.research.a2.evaluation import selected_performance_update as update
    paths,package,manifest,path,output,contract,displayed,loader=direct_bound_research_fixture(tmp_path,monkeypatch)
    package.pop('policy_id');output.write_text(json.dumps(package))
    with pytest.raises(ValueError,match='DIRECT_RESEARCH_POLICY_REQUIRED'):update.verified_direct_research(package)
    with pytest.raises(ValueError):extension.bound_direct_research(paths,extension.reference(path))



def closed_prior_delta_scope_case(tmp_path, monkeypatch, policy):
    """Synthetic accepted broad audit with a smaller current price request."""
    import json
    from scripts.research.a2.portfolio import selected_hgb as selected
    from scripts.research.a2.evaluation import demo_performance
    from scripts import daily_recommendation_inputs as calendar
    actual_review = demo_performance.reviewed_events
    paths, ref, report, new_open, original, delta, calls, inputs, hist = prior_session_capture_case(tmp_path, monkeypatch)
    bound = extension.bound_direct_research
    package, prior, _, _ = bound(paths, ref)
    monkeypatch.setattr(selected, 'active_policy', lambda *a: (policy, report))
    if policy == selected.LEGACY_POLICY:
        monkeypatch.setattr(extension, '_bound_selected_research', bound)
    monkeypatch.setattr(demo_performance, 'reviewed_events', actual_review)
    monkeypatch.setattr(calendar, 'latest_completed_session', lambda *a: {'target_date':'2026-10-05',
        'sessions':['2026-09-22','2026-09-23','2026-09-24','2026-09-25','2026-09-28','2026-09-29',
                    '2026-09-30','2026-10-01','2026-10-02','2026-10-05','2026-10-06']})
    old = original.loc[original.trade_date.eq(pd.Timestamp('2026-10-02'))].copy()
    old['trade_date'] = pd.Timestamp('2026-09-22')
    meta = json.loads(inputs.read_text()); meta.pop('execution_open')
    price_path = Path(meta['captured_prices']['path']); old.to_parquet(price_path,index=False)
    audit = pd.DataFrame([{'ticker':'REVIEW_ONLY','code':'US.REVIEW_ONLY','event_date':pd.Timestamp('2025-09-25'),
        'audit_kind':'LARGE_RAW_MOVE_NO_VENDOR_EVENT','raw_jump':1.25}])
    event_path = Path(meta['events']['path']); audit.to_parquet(event_path,index=False)
    review = tmp_path/'event_review.json'; review.write_text(json.dumps({'schema':'A2_EXECUTION_EVENT_REVIEW_V1',
        'policy':demo_performance.EVENT_REVIEW_POLICY,'records':[{'ticker':'REVIEW_ONLY','code':'US.REVIEW_ONLY',
        'event_date':'2025-09-25','audit_kind':'LARGE_RAW_MOVE_NO_VENDOR_EVENT','raw_jump':1.25,
        'status':'RESOLVED_NON_CORPORATE_ACTION'}]}))
    meta.update(captured_prices=extension.reference(price_path),events=extension.reference(event_path),
                event_review=extension.reference(review))
    meta['refs'].append(extension.reference(review))
    inputs.write_text(json.dumps(meta))
    prior['performance_period']['end']='2026-09-22'
    prior['shared_scores_historical']=[
        {'signal_date':'2026-09-24','ticker':'MID_ONLY','raw_rank':30},
        {'signal_date':'2026-09-21','ticker':'PAST_ONLY','raw_rank':1},
        {'signal_date':'2026-10-06','ticker':'FUTURE_ONLY','raw_rank':1},
        {'signal_date':'2026-09-24','ticker':'OUTSIDE_RAW40','raw_rank':41}]
    recorded_root=tmp_path/'original_recorded';(recorded_root/'test2026').mkdir(parents=True)
    recorded_path=recorded_root/'test2026/predictions.parquet'
    recorded_empty=pd.DataFrame({'signal_date':pd.Series(dtype='datetime64[ns]'),'ticker':pd.Series(dtype='str'),
        'security_id':pd.Series(dtype='str'),'raw_rank':pd.Series(dtype='int64'),'raw_score':pd.Series(dtype='float64'),
        'pred_hgb':pd.Series(dtype='float64'),'pred_q10':pd.Series(dtype='float64')})
    recorded_empty.to_parquet(recorded_path,index=False)
    monkeypatch.setattr(selected,'DEFAULT_SOURCE_ROOT',recorded_root)
    monkeypatch.setattr(selected,'REPLAY_HASHES',{**selected.REPLAY_HASHES,
        'test2026/predictions.parquet':extension.reference(recorded_path)['sha256']})
    prior['source_refs']=[extension.reference(inputs),meta['captured_prices'],meta['events'],extension.reference(recorded_path)]
    Path(ref['path']).write_text(json.dumps(prior));ref.update(extension.reference(ref['path']))
    # Complete new close marks; the original old close rows remain byte-exact.
    terminal=delta['prices'].loc[delta['prices'].trade_date.eq(pd.Timestamp('2026-10-05'))].copy()
    delta['prices']=pd.concat([old,terminal,pd.DataFrame([
        {'ticker':'MID_ONLY','trade_date':pd.Timestamp('2026-09-21'),'open':30.,'high':31.,'low':29.,'close':30.,'volume':100.},
        {'ticker':'MID_ONLY','trade_date':pd.Timestamp('2026-10-05'),'open':31.,'high':32.,'low':30.,'close':31.,'volume':100.}
    ])],ignore_index=True)
    delta.pop('execution_open');delta['events']=audit.iloc[:0].copy()
    delta['event_review']=meta['event_review'];delta['refs'].append(meta['event_review'])
    return paths,ref,report,old,delta,calls,inputs,meta,prior,audit,review


@pytest.mark.parametrize('policy',['RAW_TOP20_FROZEN_LEGACY','HGB_TOP20_RISK_R1'])
def test_prior_delta_requests_intermediate_raw40_identity_and_checks_full_preserved_event_union(tmp_path,monkeypatch,policy):
    paths,ref,report,old,delta,calls,inputs,meta,prior,audit,review=closed_prior_delta_scope_case(tmp_path,monkeypatch,policy)
    originals={path:path.read_bytes() for path in [inputs,Path(ref['path']),Path(meta['events']['path']),review]}
    result,after=extension._advance_research_capture(paths,ref,report,None,None)
    assert calls[0]['tickers']==['A','B','MID_ONLY']
    assert 'REVIEW_ONLY' not in calls[0]['tickers']
    assert after['event_review']==meta['event_review'] and after['event_review_resolved'] is True
    pd.testing.assert_frame_equal(result['events'],audit[result['events'].columns],check_exact=True)
    pd.testing.assert_frame_equal(result['prices'].loc[result['prices'].trade_date.eq(pd.Timestamp('2026-09-22'))].reset_index(drop=True),
                                  old[result['prices'].columns].reset_index(drop=True),check_exact=True)
    assert after['capture_reuse']['new_qualified_raw_candidate_history']==['MID_ONLY']
    assert after['capture_reuse']['model_feature_eligibility_granted'] is False
    assert after['capture_reuse']['known_price_fields_all_exact'] is True
    assert all(path.read_bytes()==data for path,data in originals.items())


@pytest.mark.parametrize('policy',['RAW_TOP20_FROZEN_LEGACY','HGB_TOP20_RISK_R1'])
def test_prior_delta_missing_score_day_uses_only_bound_validated_ranking_projection(tmp_path,monkeypatch,policy):
    import json
    from scripts.research.a2.evaluation.demo_performance import MODEL_2026_SHA
    paths,ref,report,old,delta,calls,inputs,meta,prior,audit,review=closed_prior_delta_scope_case(tmp_path,monkeypatch,policy)
    ranked=pd.DataFrame([{'target_date':'2026-09-23','ticker':f'R{rank:02}','security_id':f'security-{rank}',
        'rank':rank,'score':rank/10000,'model_year':2026,'model_sha256':MODEL_2026_SHA} for rank in range(1,41)])
    ranked=pd.concat([ranked,pd.DataFrame([{'target_date':'2027-01-01','ticker':'DO_NOT_READ_FUTURE',
        'security_id':'future','rank':1,'score':-99,'model_year':2027,'model_sha256':'wrong'}])],ignore_index=True)
    ranking=tmp_path/'recorded/rankings.parquet';ranking.parent.mkdir();ranked.to_parquet(ranking,index=False)
    prior['source_refs'].append(extension.reference(ranking));Path(ref['path']).write_text(json.dumps(prior));ref.update(extension.reference(ref['path']))
    result,after=extension._advance_research_capture(paths,ref,report,None,None)
    assert set(calls[0]['tickers'])=={'A','B','MID_ONLY',*[f'R{rank:02}' for rank in range(1,41)]}
    assert extension.reference(ranking) in after['refs']
    assert 'DO_NOT_READ_FUTURE' not in calls[0]['tickers']
    assert after['capture_reuse']['model_feature_eligibility_granted'] is False


@pytest.mark.parametrize('fault,reason',[
    ('old_raw_jump','EVENT_REVIEW_DETECTED_FACT_MISMATCH'),
    ('incoming_raw_jump','PAST_EVENT_FACT_CHANGED'),
    ('review_hash','SOURCE_HASH_MISMATCH'),
    ('review_identity','EVENT_REVIEW_IDENTITY_CHANGED'),
    ('past_added_event','PAST_EVENT_REVISION'),
    ('past_price','ACCEPTED_CLOSED_FIELD_CHANGED'),
    ('ranking_model','UPDATED_RANKING_MODEL_IDENTITY'),
    ('ranking_identity','UPDATED_TOP40_CARDINALITY_OR_IDENTITY')])
def test_prior_delta_full_review_and_original_facts_or_candidate_identity_remain_strict(tmp_path,monkeypatch,fault,reason):
    import json
    from scripts.research.a2.evaluation.demo_performance import MODEL_2026_SHA
    paths,ref,report,old,delta,calls,inputs,meta,prior,audit,review=closed_prior_delta_scope_case(tmp_path,monkeypatch,'RAW_TOP20_FROZEN_LEGACY')
    if fault=='old_raw_jump':
        audit['raw_jump']=1.5;event=Path(meta['events']['path']);audit.to_parquet(event,index=False)
        meta['events']=extension.reference(event);inputs.write_text(json.dumps(meta))
        prior['source_refs']=[extension.reference(inputs),meta['captured_prices'],meta['events']]
        Path(ref['path']).write_text(json.dumps(prior));ref.update(extension.reference(ref['path']))
    elif fault=='incoming_raw_jump':delta['events']=audit.copy();delta['events']['raw_jump']=1.5
    elif fault=='review_hash':review.write_text('{}')
    elif fault=='review_identity':
        changed=tmp_path/'another_review.json';changed.write_bytes(review.read_bytes());delta['event_review']=extension.reference(changed)
        delta['refs'].append(delta['event_review'])
    elif fault=='past_added_event':
        delta['events']=pd.DataFrame([{'ticker':'A','code':'US.A','event_date':pd.Timestamp('2026-09-22'),
            'audit_kind':'NEW_PAST_EVENT','raw_jump':1.1}])
    elif fault=='past_price':delta['prices'].loc[delta['prices'].trade_date.eq(pd.Timestamp('2026-09-22')),'open']+=1.
    else:
        ranked=pd.DataFrame([{'target_date':'2026-09-23','ticker':f'R{rank:02}','security_id':f'security-{rank}',
            'rank':rank,'score':rank/10000,'model_year':2026,'model_sha256':MODEL_2026_SHA} for rank in range(1,41)])
        if fault=='ranking_model':ranked['model_sha256']='0'*64
        else:ranked.loc[1,'security_id']=ranked.loc[0,'security_id']
        ranking=tmp_path/'rankings.parquet';ranked.to_parquet(ranking,index=False)
        prior['source_refs'].append(extension.reference(ranking));Path(ref['path']).write_text(json.dumps(prior));ref.update(extension.reference(ref['path']))
    with pytest.raises(ValueError,match=reason):extension._advance_research_capture(paths,ref,report,None,None)



def recorded_unexecuted_prior_fixture(tmp_path,monkeypatch,policy):
    from scripts.research.a2.portfolio import selected_hgb as selected
    root=tmp_path/'frozen';(root/'test2026').mkdir(parents=True)
    def rows(day):
        return pd.DataFrame({'signal_date':pd.Timestamp(day),'ticker':[f'T{i:02d}' for i in range(1,41)],
            'security_id':[f'id{i:02d}' for i in range(1,41)],'raw_rank':list(range(1,41)),
            'raw_score':[i/1000 for i in range(1,41)],'f1':[.1]*40,
            'pred_hgb':[i/2000 for i in range(1,41)],'pred_q10':[-.02]*40})
    consumed=rows('2026-09-21');unexecuted=rows('2026-09-22');unexecuted.loc[0,'f1']=float('nan')
    future=rows('2026-10-06');future['pred_hgb']=999.;unknown=rows('2027-01-01');unknown['pred_hgb']=9999.
    bootstrap=root/'test2026/predictions.parquet';pd.concat([consumed,unexecuted,future,unknown],ignore_index=True).to_parquet(bootstrap,index=False)
    # A later repaired daily feature vintage must remain under its canonical
    # snapshot owner rather than being read opportunistically from prior refs.
    feature=tmp_path/'selected_hgb_features.parquet';rows('2026-10-05').rename(columns={'signal_date':'trade_date'}).to_parquet(feature,index=False)
    owner=tmp_path/'canonical.json';owner.write_text('synthetic owner')
    fake=SimpleNamespace(REPLAY_HASHES={'test2026/predictions.parquet':extension.reference(bootstrap)['sha256']},
        FEATURES=('f1',),active_policy=lambda *a:(policy,owner),_score_rows=selected._score_rows,
        _normalise_day=lambda *a:pytest.fail('Recorded predictions and consumed daily cutoff require no new normalization'))
    prior={'strategies':{'HGB':{'targets':[{'signal_date':'2026-09-21'}]}},
        'source_refs':[extension.reference(bootstrap),extension.reference(feature)],
        'shared_scores_historical':selected._score_rows(consumed,signal_date='2026-09-21')}
    monkeypatch.setattr(extension,'_accepted_owner',lambda *a:(extension.reference(owner),{},[]))
    return fake,root,prior,consumed,unexecuted,bootstrap


@pytest.mark.parametrize('policy',['RAW_TOP20_FROZEN_LEGACY','HGB_TOP20_RISK_R1'])
def test_prior_owner_reuses_bound_unexecuted_recorded_signal_without_future_rows_or_feature_imputation(tmp_path,monkeypatch,policy):
    fake,root,prior,consumed,unexecuted,bootstrap=recorded_unexecuted_prior_fixture(tmp_path,monkeypatch,policy)
    frames,refs,observation,accepted=extension._load_prior_sources(SimpleNamespace(),fake,root,prior,'2026-10-05')
    assert len(frames)==1 and not accepted
    assert set(frames[0].signal_date.dt.strftime('%Y-%m-%d'))=={'2026-09-21','2026-09-22'}
    class NoInference:
        def predict(self,*a):pytest.fail('Exact prerecorded unexecuted scores require no prediction')
        def fit(self,*a):pytest.fail('No fitting')
    panel=extension.score_panel(frames,fake,{'model':NoInference(),'q10':NoInference()})
    extension._verify_prior_scores(panel,prior,fake)
    day=panel.loc[panel.signal_date.eq(pd.Timestamp('2026-09-22'))].reset_index(drop=True)
    pd.testing.assert_frame_equal(day,unexecuted[day.columns].reset_index(drop=True),check_exact=True)
    assert pd.isna(day.loc[0,'f1'])
    assert extension.reference(bootstrap) in refs
    assert all(Path(ref['path']).name!='selected_hgb_features.parquet' for ref in refs)


@pytest.mark.parametrize('fault',['missing_original_binding','wrong_original_binding','future_target','behind_executed_target'])
def test_prior_recorded_continuation_refuses_unknown_vintage_or_unbounded_target_before_read(tmp_path,monkeypatch,fault):
    fake,root,prior,consumed,unexecuted,bootstrap=recorded_unexecuted_prior_fixture(tmp_path,monkeypatch,'RAW_TOP20_FROZEN_LEGACY')
    target='2026-10-05'
    if fault=='missing_original_binding':prior['source_refs']=[]
    elif fault=='wrong_original_binding':prior['source_refs'][0]={**prior['source_refs'][0],'sha256':'0'*64}
    elif fault=='future_target':target='2027-01-01'
    else:target='2026-09-20'
    monkeypatch.setattr(extension,'_capture_parquet',lambda *a,**kw:pytest.fail('Unknown vintage/window must fail before source read'))
    reason='ORIGINAL_PREDICTION_BINDING' if 'binding' in fault else 'FEATURE_WINDOW'
    with pytest.raises(ValueError,match=reason):extension._load_prior_sources(SimpleNamespace(),fake,root,prior,target)


@pytest.mark.parametrize('policy',['RAW_TOP20_FROZEN_LEGACY','HGB_TOP20_RISK_R1'])
def test_explicit_prior_replay_passes_mature_current_prices_to_original_missing_feature_owner(tmp_path,monkeypatch,policy):
    import json
    from scripts.common import storage_paths
    from scripts.research.a2.portfolio import selected_hgb as selected
    paths,ref,report,old,delta,calls,inputs,meta,prior,audit,review=closed_prior_delta_scope_case(tmp_path,monkeypatch,policy)
    result,metadata=extension._advance_research_capture(paths,ref,report,None,None)
    prior['policy_id']=policy;Path(ref['path']).write_text(json.dumps(prior));ref.update(extension.reference(ref['path']))
    metadata['research_input_owner']=ref
    # A next execution's recorded fields must never flow into mature signal features.
    future=result['prices'].iloc[[0]].copy();future['trade_date']=pd.Timestamp('2026-10-06');future['close']=999.
    prices=tmp_path/'continuation_prices.parquet';pd.concat([result['prices'],future],ignore_index=True).to_parquet(prices,index=False)
    event=tmp_path/'continuation_events.parquet';result['events'].to_parquet(event,index=False)
    metadata['captured_prices']=extension.reference(prices);metadata['events']=extension.reference(event)
    price_inputs=tmp_path/'continuation_inputs.json';price_inputs.write_text(json.dumps(metadata))
    monkeypatch.setattr(storage_paths,'resolve',lambda *a:paths)
    monkeypatch.setattr(selected,'verify_frozen',lambda *a:None)
    monkeypatch.setattr(selected,'_runtime',lambda *a:{})
    monkeypatch.setattr(extension,'bound_selected_research',lambda *a:({'policy_id':policy},prior,ref,extension.reference(report)))
    monkeypatch.setattr(extension,'_load_prior_sources',lambda *a:([],[],None,{}))
    class ReachedOriginalRecovery(Exception):pass
    observed=[]
    def recovery(paths,frames,bounded_prices,sessions,selected,*,prior_research):
        observed.append(bounded_prices.copy())
        assert prior_research is prior
        raise ReachedOriginalRecovery
    monkeypatch.setattr(extension,'recover_missing_features',recovery)
    with pytest.raises(ReachedOriginalRecovery):
        extension.run_extension(prices,price_inputs,tmp_path/'not_created',repo_root=tmp_path,
            target_date='2026-10-05',sessions=['2026-09-22','2026-09-23','2026-10-05','2026-10-06'],
            policy=policy,prior_research_manifest=ref)
    assert observed[0].trade_date.max()==pd.Timestamp('2026-10-05')
    assert not observed[0].close.eq(999.).any()
    assert not (tmp_path/'not_created').exists()


def test_original_missing_feature_owner_recovers_bound_middle_day_and_excludes_future_rankings(tmp_path,monkeypatch):
    import numpy as np
    dates=pd.bdate_range('2026-08-01','2026-10-05')
    prices=pd.DataFrame([{'ticker':f'T{i:02d}','trade_date':day,'close':100.+slot+i/100,'volume':1000.}
        for slot,day in enumerate(dates) for i in range(1,41)])
    rankings=pd.DataFrame([{'target_date':day,'ticker':f'T{i:02d}','security_id':f'id{i:02d}',
        'rank':i,'score':i/1000} for day in ['2026-09-23','2026-10-06','2027-01-01'] for i in range(1,41)])
    ranking=tmp_path/'rankings.parquet';rankings.to_parquet(ranking,index=False)
    features=pd.DataFrame({'ticker':prices.ticker,'trade_date':prices.trade_date,'f1':.1})
    loads=[]
    fake=SimpleNamespace(BASE_FEATURES=('f1',),_load_module=lambda name,path:(loads.append((name,path)) or
        SimpleNamespace(build_stock_state_features=lambda bounded:features.copy())))
    frames=[pd.DataFrame({'signal_date':[pd.Timestamp('2026-09-22')],'ticker':['T01']})]
    captured=[];monkeypatch.setattr(extension,'verify_refs',lambda refs:captured.extend(refs))
    recovered,refs=extension.recover_missing_features(SimpleNamespace(repo_root=tmp_path),frames,prices,dates,fake,
        prior_research={'source_refs':[extension.reference(ranking)]})
    assert len(recovered)==1 and len(recovered[0])==40
    assert pd.to_datetime(recovered[0].signal_date).dt.strftime('%Y-%m-%d').unique().tolist()==['2026-09-23']
    assert np.isfinite(recovered[0][['f1',*(f'lag_ret_{i:02d}' for i in range(10))]].to_numpy(float)).all()
    assert extension.reference(ranking) in refs and len(loads)==1
    assert captured[0]['sha256']=='fd4fe78d27bfbf57c89343d60550366ccf7fcbf3d6a65e7ef66f28405d050c19'


def recorded_candidate_projection_case(tmp_path,monkeypatch,policy):
    """Unexecuted recorded signal survives a partial prior without picking rank vintages."""
    import json
    from scripts.research.a2.portfolio import selected_hgb as selected
    from scripts.research.a2.evaluation.demo_performance import MODEL_2026_SHA
    fixture=closed_prior_delta_scope_case(tmp_path,monkeypatch,policy)
    paths,ref,report,old,delta,calls,inputs,meta,prior,audit,review=fixture
    def recorded(day,prefix):
        return pd.DataFrame({'signal_date':pd.Timestamp(day),'ticker':[f'{prefix}{i:02}' for i in range(1,41)],
            'security_id':[f'{prefix}-id-{i}' for i in range(1,41)],'raw_rank':range(1,41),
            'raw_score':[i/10000 for i in range(1,41)],'pred_hgb':[i/20000 for i in range(1,41)],
            'pred_q10':[-.02]*40})
    native=recorded('2026-09-22','N')
    future=recorded('2026-10-06','FUTURE');future['pred_hgb']=float('nan')
    unknown=recorded('2027-01-01','UNKNOWN');unknown['security_id']=''
    past=recorded('2026-09-21','PAST')
    original=selected.DEFAULT_SOURCE_ROOT/'test2026/predictions.parquet'
    pd.concat([past,native,future,unknown],ignore_index=True).to_parquet(original,index=False)
    native_ref=extension.reference(original)
    monkeypatch.setattr(selected,'REPLAY_HASHES',{**selected.REPLAY_HASHES,'test2026/predictions.parquet':native_ref['sha256']})
    prior['source_refs']=[r for r in prior['source_refs'] if Path(r['path'])!=original]+[native_ref]
    def ranking(day,prefix):
        return pd.DataFrame([{'target_date':day,'ticker':f'{prefix}{rank:02}',
            'security_id':f'{prefix}-security-{rank}','rank':rank,'score':rank/10000,
            'model_year':2026,'model_sha256':MODEL_2026_SHA} for rank in range(1,41)])
    first=tmp_path/'vintage_one/rankings.parquet';first.parent.mkdir()
    second=tmp_path/'vintage_two/rankings.parquet';second.parent.mkdir()
    # These conflicting 9/22 vintages are irrelevant once the originally bound
    # recorded40 owns that date. 9/23 remains original validated rank fallback.
    ranking('2026-09-22','WRONG_ONE').to_parquet(first,index=False)
    pd.concat([ranking('2026-09-22','WRONG_TWO'),ranking('2026-09-23','R'),
               ranking('2026-10-06','R_FUTURE'),ranking('2027-01-01','R_UNKNOWN')],ignore_index=True).to_parquet(second,index=False)
    prior['source_refs'] += [extension.reference(first),extension.reference(second)]
    Path(ref['path']).write_text(json.dumps(prior));ref.update(extension.reference(ref['path']))
    return fixture,original,native,native_ref,first,second


@pytest.mark.parametrize('policy',['RAW_TOP20_FROZEN_LEGACY','HGB_TOP20_RISK_R1'])
def test_recorded_candidate_projection_owns_missing_shared_signal_and_all_raw40_without_rank_vintage_join(tmp_path,monkeypatch,policy):
    fixture,original,native,native_ref,first,second=recorded_candidate_projection_case(tmp_path,monkeypatch,policy)
    paths,ref,report,old,delta,calls,inputs,meta,prior,audit,review=fixture
    before={p:p.read_bytes() for p in [original,first,second,inputs,Path(ref['path']),review]}
    assert not any(r['signal_date']=='2026-09-22' for r in prior['shared_scores_historical'])
    result,after=extension._advance_research_capture(paths,ref,report,None,None)
    assert set(calls[0]['tickers'])=={'A','B','MID_ONLY',*native.ticker,*[f'R{i:02}' for i in range(1,41)]}
    assert native_ref in after['refs'] and extension.reference(second) in after['refs']
    assert extension.reference(first) not in after['refs']  # no read-date vintage selection
    assert after['capture_reuse']['model_feature_eligibility_granted'] is False
    pd.testing.assert_frame_equal(result['prices'].loc[result['prices'].trade_date.eq(pd.Timestamp('2026-09-22'))].reset_index(drop=True),
                                  old[result['prices'].columns].reset_index(drop=True),check_exact=True)
    assert all(p.read_bytes()==data for p,data in before.items())


@pytest.mark.parametrize('fault,reason',[
    ('missing_ref','PRIOR_RESEARCH_ORIGINAL_PREDICTION_BINDING_REQUIRED'),
    ('wrong_ref','PRIOR_RESEARCH_ORIGINAL_PREDICTION_BINDING_REQUIRED'),
    ('short40','SHARED_SCORES_REQUIRE_RAW_TOP40'),
    ('security_identity','INVALID_SHARED_SCORE_SECURITY_IDENTITY'),
    ('q10_nonfinite','RECORDED_PREDICTIONS_NONFINITE')])
def test_recorded_candidate_projection_rejects_unknown_original_binding_or_invalid_native40_before_capture(tmp_path,monkeypatch,fault,reason):
    import json
    from scripts.research.a2.portfolio import selected_hgb as selected
    fixture,original,native,native_ref,first,second=recorded_candidate_projection_case(tmp_path,monkeypatch,'RAW_TOP20_FROZEN_LEGACY')
    paths,ref,report,old,delta,calls,inputs,meta,prior,audit,review=fixture
    if fault=='missing_ref':prior['source_refs'].remove(native_ref)
    elif fault=='wrong_ref':
        prior['source_refs'].remove(native_ref);prior['source_refs'].append({**native_ref,'sha256':'0'*64})
    else:
        if fault=='short40':native=native.iloc[:-1].copy()
        elif fault=='security_identity':native.loc[1,'security_id']=native.loc[0,'security_id']
        else:native.loc[0,'pred_q10']=float('nan')
        native.to_parquet(original,index=False)
        replacement=extension.reference(original)
        prior['source_refs'].remove(native_ref);prior['source_refs'].append(replacement)
        monkeypatch.setattr(selected,'REPLAY_HASHES',{**selected.REPLAY_HASHES,'test2026/predictions.parquet':replacement['sha256']})
    Path(ref['path']).write_text(json.dumps(prior));ref.update(extension.reference(ref['path']))
    with pytest.raises(ValueError,match=reason):extension._advance_research_capture(paths,ref,report,None,None)
    assert calls==[]


def accepted_closed_capture_reuse_case(tmp_path,monkeypatch,policy):
    """Accepted full close5 capture, partial replay22, independent current6 package."""
    import json
    fixture=closed_prior_delta_scope_case(tmp_path,monkeypatch,policy)
    paths,ref,report,old,delta,calls,inputs,meta,prior,audit,review=fixture
    package=extension.bound_direct_research(paths,ref)[0]
    source6=tmp_path/'source6.json';source6.write_text(json.dumps({'status':'READY','data_date':'2026-10-06'}))
    package['shared_scores']['current']={'signal_date':'2026-10-06','rows':[{'ticker':'FUTURE_SIX_ONLY'}]}
    package['source_refs']['current/report.json']=extension.reference(source6)
    parent=tmp_path/'original_research.json';parent.write_text(json.dumps({'accepted_original':True}))
    meta.update(end_date='2026-10-05',gaps=[],research_input_owner=extension.reference(parent))
    meta['refs'].append(extension.reference(parent))
    prices=delta['prices'].copy()
    prices.to_parquet(meta['captured_prices']['path'],index=False)
    meta['captured_prices']=extension.reference(meta['captured_prices']['path'])
    prior['source_refs']+=meta['refs']
    def persist():
        meta['captured_prices']=extension.reference(meta['captured_prices']['path'])
        meta['events']=extension.reference(meta['events']['path'])
        inputs.write_text(json.dumps(meta))
        changed={str(inputs),meta['captured_prices']['path'],meta['events']['path']}
        prior['source_refs']=[r for r in prior['source_refs'] if r['path'] not in changed]
        prior['source_refs'] += [extension.reference(inputs),meta['captured_prices'],meta['events']]
        Path(ref['path']).write_text(json.dumps(prior));ref.update(extension.reference(ref['path']))
    persist()
    return fixture,package,source6,parent,prices,persist


@pytest.mark.parametrize('policy',['RAW_TOP20_FROZEN_LEGACY','HGB_TOP20_RISK_R1'])
def test_accepted_closed_capture_reuse_rebinds_exact_leaf_without_current_future_names_or_fresh_prices(tmp_path,monkeypatch,policy):
    import json
    fixture,package,source6,parent,prices,persist=accepted_closed_capture_reuse_case(tmp_path,monkeypatch,policy)
    paths,ref,report,old,delta,calls,inputs,meta,prior,audit,review=fixture
    immutable=[inputs,Path(ref['path']),Path(meta['captured_prices']['path']),Path(meta['events']['path']),report,review,parent,source6]
    before={p:p.read_bytes() for p in immutable}
    input_ref=extension.reference(inputs);old_price=meta['captured_prices'];old_event=meta['events']
    result,after=extension._advance_research_capture(paths,ref,report,None,None)
    assert calls==[]
    pd.testing.assert_frame_equal(result['prices'],prices[result['prices'].columns],check_exact=True)
    pd.testing.assert_frame_equal(result['events'],audit,check_exact=True)
    assert after['research_input_owner']==ref and after['capture_reuse']['inputs_ref']==input_ref
    assert after['capture_reuse']['prices_ref']==old_price
    assert after['capture_reuse']['reused_accepted_closed_capture'] is True
    assert after['capture_reuse']['matured_fields']==[]
    assert after['capture_reuse']['new_qualified_raw_candidate_history']==[]
    assert after['capture_reuse']['model_feature_eligibility_granted'] is False
    assert all(r in after['refs'] for r in [*prior['source_refs'],input_ref,old_price,old_event,extension.reference(parent)])
    assert json.loads(inputs.read_text())['research_input_owner']==extension.reference(parent)
    extension._verify_prior_price_prefix(result['prices'],after,prior,old_price)
    assert package['shared_scores']['current']['signal_date']=='2026-10-06'
    assert all(p.read_bytes()==data for p,data in before.items())


@pytest.mark.parametrize('fault,reason',[
    ('gaps','PRIOR_PRICE_CLOSED_CAPTURE_BINDING_INVALID'),
    ('source_path','PRIOR_PRICE_CLOSED_CAPTURE_BINDING_INVALID'),
    ('unaccepted_old_ref','PRIOR_PRICE_CLOSED_CAPTURE_BINDING_INVALID'),
    ('unbound_parent','PRIOR_PRICE_CLOSED_CAPTURE_BINDING_INVALID'),
    ('review_unresolved','PRIOR_PRICE_EVENT_BINDING_INVALID'),
    ('review_wrong_facts','EVENT_REVIEW_DETECTED_FACT_MISMATCH'),
    ('price_hash','SOURCE_HASH_MISMATCH'),
    ('event_hash','SOURCE_HASH_MISMATCH'),
    ('missing_prices_binding','PRIOR_PRICE_CAPTURE_IDENTITY_AMBIGUOUS'),
    ('missing_events_binding','PRIOR_PRICE_EVENT_BINDING_INVALID'),
    ('truncated_prices','PRIOR_PRICE_CLOSED_CAPTURE_PRICES_INVALID'),
    ('invalid_close','PRIOR_PRICE_CLOSED_CAPTURE_PRICES_INVALID'),
    ('duplicate_prices','PRIOR_PRICE_CLOSED_CAPTURE_PRICES_INVALID'),
    ('not_mature','PRIOR_PRICE_COMPLETED_SIGNAL_REQUIRED')])
def test_accepted_closed_capture_reuse_refuses_each_unqualified_binding_or_closed_fact_before_recapture(tmp_path,monkeypatch,fault,reason):
    import json
    from scripts import daily_recommendation_inputs as calendar
    fixture,package,source6,parent,prices,persist=accepted_closed_capture_reuse_case(tmp_path,monkeypatch,'RAW_TOP20_FROZEN_LEGACY')
    paths,ref,report,old,delta,calls,inputs,meta,prior,audit,review=fixture
    selected_report=report
    if fault=='gaps':meta['gaps']=[{'ticker':'A','reason':'UNQUALIFIED'}];persist()
    elif fault=='source_path':
        selected_report=tmp_path/'same_bytes_other_source5.json';selected_report.write_bytes(report.read_bytes())
    elif fault=='unaccepted_old_ref':
        prior['source_refs'].remove(meta['refs'][0]);persist()
    elif fault=='unbound_parent':
        meta['refs'].remove(extension.reference(parent));prior['source_refs'].remove(extension.reference(parent));persist()
    elif fault=='review_unresolved':meta['event_review_resolved']=False;persist()
    elif fault=='review_wrong_facts':
        audit['raw_jump']=1.5;audit.to_parquet(meta['events']['path'],index=False);persist()
    elif fault=='price_hash':Path(meta['captured_prices']['path']).write_bytes(b'changed old immutable prices')
    elif fault=='event_hash':Path(meta['events']['path']).write_bytes(b'changed old immutable events')
    elif fault=='missing_prices_binding':
        prior['source_refs'].remove(meta['captured_prices']);Path(ref['path']).write_text(json.dumps(prior));ref.update(extension.reference(ref['path']))
    elif fault=='missing_events_binding':
        prior['source_refs'].remove(meta['events']);Path(ref['path']).write_text(json.dumps(prior));ref.update(extension.reference(ref['path']))
    elif fault in {'truncated_prices','invalid_close','duplicate_prices'}:
        if fault=='truncated_prices':prices=prices.loc[prices.trade_date.lt(pd.Timestamp('2026-10-05'))]
        elif fault=='invalid_close':prices.loc[prices.trade_date.eq(pd.Timestamp('2026-10-05')),'close']=float('nan')
        else:prices=pd.concat([prices,prices.iloc[[0]]],ignore_index=True)
        prices.to_parquet(meta['captured_prices']['path'],index=False);persist()
    else:monkeypatch.setattr(calendar,'latest_completed_session',lambda *a:{'target_date':'2026-10-02','sessions':['2026-09-22','2026-10-02','2026-10-05']})
    with pytest.raises(ValueError,match=reason):extension._advance_research_capture(paths,ref,selected_report,None,None)
    assert calls==[]


def test_accepted_closed_capture_reuse_never_claims_a_new_open_phase(tmp_path,monkeypatch):
    fixture,package,source6,parent,prices,persist=accepted_closed_capture_reuse_case(tmp_path,monkeypatch,'RAW_TOP20_FROZEN_LEGACY')
    paths,ref,report,old,delta,calls,inputs,meta,prior,audit,review=fixture
    opening=tmp_path/'open6.json'
    package['source_refs']['current/report.json']=extension.reference(report)
    with pytest.raises(ValueError,match='PRIOR_PRICE_CONTINUATION_CLOCK_OR_REPORT_INVALID'):
        extension._advance_research_capture(paths,ref,report,opening,'2026-10-06')
    assert calls==[]  # Original next-open signal must equal the accepted replay end.


# Pure synthetic accepted-vintage cases: no SDK, canonical market data or model IO.
def accepted_closed_vintage_case(tmp_path,monkeypatch):
    import json,hashlib
    from scripts.research.a2.evaluation import demo_performance, demo_performance_prices as reader
    from scripts.research.a2.portfolio import selected_hgb as selected
    from scripts import daily_recommendation_inputs as calendar, daily_recommendation_prices as original
    def write_json(path, value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,sort_keys=True),encoding='utf-8')
    historical_inputs=tmp_path/'historical_price_manifest.json'
    write_json(historical_inputs,{'lineage':[{'ticker':'A','code':'US.A','cusips':['sid-A']}]})
    historical=tmp_path/'historical.json'
    write_json(historical,{'price_manifest':extension.reference(historical_inputs)})
    anchor=tmp_path/'original_raw_anchor';anchor.write_text('same original RAW anchor',encoding='utf-8')
    reports=[];entries=[];factors=[];mappings=[]
    for label,day in (('old','2026-10-02'),('new','2026-10-05')):
        root=tmp_path/label;root.mkdir()
        mapped=root/'mapped_members.parquet'
        pd.DataFrame([{'ticker':'A','moomoo_symbol':'US.A','security_id':'sid-A'}]).to_parquet(mapped,index=False)
        raw=root/'raw';raw.write_text('independent recorded RAW vintage '+label,encoding='utf-8')
        factor=root/'factors.parquet'
        pd.DataFrame([{'code':'US.A','ex_div_date':pd.Timestamp('2025-01-02'),
            'forward_adj_factorA':1.,'forward_adj_factorB':.2,'split_ratio':1.}]).to_parquet(factor,index=False)
        item={'ticker':'A','code':'US.A','source':'MOOMOO_HISTORY_KLINE_RAW_PLUS_GET_REHAB',
            'price_basis':extension.BASIS,'anchor_date':'2020-01-02',
            'adapter_sha256':original.ADAPTER_SHA,'coverage_manifest_sha256':original.COVERAGE_SHA,
            'raw_sources':[{**extension.reference(anchor),'role':'ORIGINAL_ANCHOR'},
                {**extension.reference(raw),'role':'CURRENT_RAW'}],
            'rehab_sha256':extension.reference(factor)['sha256'],'rehab_fetched_at':day+'T21:00:00+00:00'}
        report={'status':'READY','data_date':day,'model_id':calendar.MODEL_ID,
            'model_sha256':calendar.MODEL_SHA256,'report_path':str(root/'recommendation_source.json'),
            'universe':{'report_path':str(root/'universe_report.json'),
                       'universe_members_sha256':extension.reference(mapped)['sha256']},
            'ranked_rows':[{'ticker':'A','rank':1}]}
        reports.append(report);entries.append(item);factors.append(factor);mappings.append(mapped)
    cols=reader.PRICE_COLUMNS
    old_prices=pd.DataFrame([{'ticker':'A','trade_date':pd.Timestamp('2026-10-02'),
        'open':9.,'close':9.,'high':10.,'low':8.,'volume':100.}],columns=cols)
    price_path=tmp_path/'prices.parquet';old_prices.to_parquet(price_path,index=False)
    old_events=pd.DataFrame([{'ticker':'A','event_date':pd.Timestamp('2025-01-02'),
        'audit_kind':'APPLIED_CORPORATE_ACTION','factor_a':1.,'factor_b':.2}])
    event_path=tmp_path/'events.parquet';old_events.to_parquet(event_path,index=False)
    newer=old_prices.copy();newer['close']+=.03
    newer=pd.concat([newer,old_prices.assign(trade_date=pd.Timestamp('2026-10-05'))],ignore_index=True)
    delta={'prices':newer,'events':old_events.copy(),'gaps':[],'refs':[],
           'price_basis':extension.BASIS,'event_review':None}
    metadata={'refs':[],'start_date':'2023-01-03','end_date':'2026-10-02',
        'price_basis':extension.BASIS,'event_review_resolved':True,
        'captured_prices':extension.reference(price_path),'events':extension.reference(event_path)}
    input_path=tmp_path/'three_strategy_price_inputs.json';manifest_path=tmp_path/'research_manifest.json'
    package={'policy_id':selected.LEGACY_POLICY,'shared_scores':{'current':{'rows':[{'ticker':'A'}]}},'source_refs':{}}
    state={'reports':reports,'entries':entries,'factors':factors,'mappings':mappings,'delta':delta,
           'metadata':metadata,'old_prices':old_prices,'historical':historical,'package':package,
           'events':old_events,'events_path':event_path,'input_path':input_path}
    def save():
        for report,entry,factor,mapped in zip(reports,entries,factors,mappings):
            root=Path(report['report_path']).parent
            entry['rehab_sha256']=extension.reference(factor)['sha256']
            report['universe']['universe_members_sha256']=extension.reference(mapped)['sha256']
            report['input_manifest_sha256']=hashlib.sha256(json.dumps([entry],sort_keys=True).encode()).hexdigest()
            write_json(root/'input_lineage.json',[entry])
            write_json(root/'rehab_receipt.json',{'source':'MOOMOO_OPEND_GET_REHAB','target_date':report['data_date'],
                'results':[{'status':'PASS','code':entry['code'],**extension.reference(factor),'fetched_at':entry['rehab_fetched_at']}]})
            write_json(Path(report['report_path']),report)
        def source_refs(index):
            root=Path(reports[index]['report_path']).parent
            return [extension.reference(historical),extension.reference(historical_inputs),
                *[{k:r[k] for k in ('path','sha256')} for r in entries[index]['raw_sources']],
                *[extension.reference(root/name) for name in ('recommendation_source.json','input_lineage.json','rehab_receipt.json','factors.parquet','mapped_members.parquet')]]
        metadata['refs']=source_refs(0);metadata['events']=extension.reference(event_path)
        delta['refs']=source_refs(1)
        write_json(input_path,metadata)
        prior={'policy_id':selected.LEGACY_POLICY,'performance_period':{'end':'2026-10-02'},'strategies':{'HGB':{'targets':[]}},
            'source_refs':[extension.reference(input_path),metadata['captured_prices'],metadata['events']]}
        write_json(manifest_path,prior)
        state['prior_ref']=extension.reference(manifest_path);state['prior']=prior
        package['source_refs']['current/report.json']=extension.reference(reports[1]['report_path'])
    save();state['save']=save
    paths=SimpleNamespace(repo_root=tmp_path,daily_root=tmp_path)
    state['paths']=paths;state['report_path']=Path(reports[1]['report_path'])
    def bound(paths,ref=None):
        if ref!=state['prior_ref']:raise ValueError('PRIOR_RESEARCH_IMMUTABLE_SELECTION_CHANGED')
        return package,state['prior'],state['prior_ref'],extension.reference(state['report_path'])
    monkeypatch.setattr(extension,'bound_selected_research',bound)
    monkeypatch.setattr(selected,'active_policy',lambda *a:(selected.LEGACY_POLICY,state['report_path']))
    monkeypatch.setattr(demo_performance,'canonical_manifest',lambda *a:(historical,None))
    monkeypatch.setattr(demo_performance,'reviewed_events',lambda *a:(True,pd.DataFrame()))
    monkeypatch.setattr(calendar,'load_frozen_binding',lambda *a:{})
    monkeypatch.setattr(calendar,'latest_completed_session',lambda *a:{'target_date':'2026-10-05',
        'sessions':['2026-10-02','2026-10-05']})
    monkeypatch.setattr(reader,'load_execution_prices',lambda *a,**kw:delta)
    state['advance']=lambda:extension._advance_research_capture(paths,state['prior_ref'],state['report_path'],None,None)
    return state


@pytest.mark.parametrize('field',['open','close','high','low','volume'])
def test_accepted_closed_vintage_preserves_all_known_fields_and_binds_both_raw_versions(tmp_path,monkeypatch,field):
    s=accepted_closed_vintage_case(tmp_path,monkeypatch)
    s['delta']['prices'].loc[0,field]+=.1
    custody={Path(ref['path']):Path(ref['path']).read_bytes() for ref in s['metadata']['refs']}
    result,metadata=s['advance']()
    old=result['prices'].loc[result['prices'].trade_date.eq(pd.Timestamp('2026-10-02'))]
    pd.testing.assert_frame_equal(old[s['old_prices'].columns].reset_index(drop=True),s['old_prices'],check_exact=True)
    assert result['prices'].trade_date.max()==pd.Timestamp('2026-10-05')
    audit=metadata['capture_reuse']['accepted_closed_vintage_continuation']
    assert audit['historical_price_revisions_applied'] is False and audit['model_feature_eligibility_granted'] is False
    proof=audit['ticker_proofs'][0]
    assert proof['security_id']=='sid-A' and proof['past_factor_stream_exact'] is True
    assert proof['accepted_raw_sources']!=proof['incoming_raw_sources']
    assert any(row['field']==field and row['ticker']=='A' for row in audit['field_differences'])
    assert all(path.read_bytes()==data for path,data in custody.items())
    extension._verify_prior_price_prefix(result['prices'],metadata,s['prior'],s['metadata']['captured_prices'])


@pytest.mark.parametrize('fault,reason',[
    ('sid','SECURITY_IDENTITY_CHANGED'),('code','ANCHOR_OR_ADAPTER_CHANGED'),
    ('anchor_date','ANCHOR_OR_ADAPTER_CHANGED'),('anchor_file','ORIGINAL_RAW_ANCHOR_CHANGED'),
    ('adapter','ANCHOR_OR_ADAPTER_CHANGED|PRICE_PROOF_MISMATCH'),('missing_adapter','ANCHOR_OR_ADAPTER_CHANGED|PRICE_PROOF_MISMATCH'),
    ('coverage','ANCHOR_OR_ADAPTER_CHANGED|PRICE_PROOF_MISMATCH'),('basis','ANCHOR_OR_ADAPTER_CHANGED'),
    ('past_factor','PAST_REHAB_FACTS_CHANGED'),('removed_factor','PAST_REHAB_FACTS_CHANGED'),
    ('same_raw','SAME_RAW_PROOF_CHANGED_PRICE'),('unbound_raw','RAW_SOURCE_UNBOUND'),
    ('missing_history','OLD_HISTORY_KEYS_CHANGED'),('missing_event','PAST_EVENT_FACT_MISSING'),
    ('missing_event_fact','PAST_EVENT_FACT_MISSING'),('changed_event','PAST_EVENT_FACT_CHANGED'),
    ('new_old_event','PAST_EVENT_REVISION'),('wrong_model','REPORT_IDENTITY_INVALID')])
def test_accepted_closed_vintage_rejects_identity_coordinate_source_history_and_event_drift(tmp_path,monkeypatch,fault,reason):
    s=accepted_closed_vintage_case(tmp_path,monkeypatch);new=s['entries'][1]
    if fault=='sid':
        mapped=pd.read_parquet(s['mappings'][1]);mapped['security_id']='wrong-sid';mapped.to_parquet(s['mappings'][1],index=False)
    elif fault=='code':new['code']='US.OTHER'
    elif fault=='anchor_date':new['anchor_date']='2020-01-03'
    elif fault=='anchor_file':
        path=tmp_path/'different_anchor';path.write_text('different');new['raw_sources'][0]={**extension.reference(path),'role':'ORIGINAL_ANCHOR'}
    elif fault=='adapter':new['adapter_sha256']='0'*64
    elif fault=='missing_adapter':del new['adapter_sha256']
    elif fault=='coverage':new['coverage_manifest_sha256']='0'*64
    elif fault=='basis':new['price_basis']='QFQ'
    elif fault in ('past_factor','removed_factor'):
        f=pd.read_parquet(s['factors'][1])
        if fault=='past_factor':f['forward_adj_factorB']+=.01
        else:f=f.iloc[:0]
        f.to_parquet(s['factors'][1],index=False)
    elif fault=='same_raw':new['raw_sources']=s['entries'][0]['raw_sources'].copy()
    elif fault=='missing_history':
        # An actual conflict remains on 10/2, while another accepted key for
        # the same ticker is absent. The dual-vintage proof must reject it.
        path=Path(s['metadata']['captured_prices']['path'])
        extra=s['old_prices'].assign(trade_date=pd.Timestamp('2026-10-01'))
        pd.concat([extra,s['old_prices']],ignore_index=True).to_parquet(path,index=False)
        s['metadata']['captured_prices']=extension.reference(path)
    elif fault=='missing_event':s['delta']['events']=s['delta']['events'].iloc[:0]
    elif fault=='missing_event_fact':s['delta']['events']=s['delta']['events'].drop(columns=['factor_b'])
    elif fault=='changed_event':s['delta']['events']['factor_b']+=.01
    elif fault=='new_old_event':
        extra=s['events'].copy();extra['audit_kind']='NEW_PAST_CA'
        s['delta']['events']=pd.concat([s['delta']['events'],extra],ignore_index=True)
    elif fault=='wrong_model':s['reports'][1]['model_sha256']='0'*64
    s['save']()
    if fault=='unbound_raw':s['delta']['refs']=[r for r in s['delta']['refs'] if r['path']!=new['raw_sources'][-1]['path']]
    with pytest.raises(ValueError,match=reason):s['advance']()


def test_accepted_closed_vintage_allows_future_factor_addition_but_keeps_past_coordinate(tmp_path,monkeypatch):
    s=accepted_closed_vintage_case(tmp_path,monkeypatch)
    f=pd.read_parquet(s['factors'][1]);future=f.iloc[[0]].copy()
    future['ex_div_date']=pd.Timestamp('2026-10-05');future['forward_adj_factorB']=.5
    pd.concat([f,future],ignore_index=True).to_parquet(s['factors'][1],index=False);s['save']()
    result,metadata=s['advance']()
    assert metadata['capture_reuse']['accepted_closed_vintage_continuation']['ticker_proofs'][0]['past_factor_stream_exact'] is True
    assert result['prices'].loc[0,'close']==9.


def test_accepted_closed_vintage_remains_legacy_only_and_direct_no_conflict_does_not_use_proof(tmp_path,monkeypatch):
    from scripts.research.a2.portfolio import selected_hgb as selected
    s=accepted_closed_vintage_case(tmp_path,monkeypatch)
    monkeypatch.setattr(selected,'active_policy',lambda *a:(selected.DIRECT_POLICY,s['report_path']))
    s['package']['policy_id']=selected.DIRECT_POLICY
    with pytest.raises(ValueError,match='VINTAGE_LEGACY_POLICY_REQUIRED'):s['advance']()
    s['delta']['prices'].loc[0,'close']=9.
    monkeypatch.setattr(extension,'_accepted_closed_vintage_proof',lambda *a:pytest.fail('no conflict may not load dual-vintage proofs'))
    _,metadata=s['advance']()
    assert 'accepted_closed_vintage_continuation' not in metadata['capture_reuse']


@pytest.mark.parametrize('fault,reason',[('tamper_raw','SOURCE_HASH_MISMATCH'),
    ('tamper_factor','SOURCE_HASH_MISMATCH'),('ambiguous_report','PRIOR_REPORT_AMBIGUOUS'),
    ('invalid_incoming','INCOMING_VINTAGE_VALUE_INVALID')])
def test_accepted_closed_vintage_rejects_tampered_or_ambiguous_proof(tmp_path,monkeypatch,fault,reason):
    import json
    s=accepted_closed_vintage_case(tmp_path,monkeypatch)
    if fault=='tamper_raw':Path(s['entries'][0]['raw_sources'][-1]['path']).write_text('tampered')
    elif fault=='tamper_factor':s['factors'][1].write_bytes(b'tampered')
    elif fault=='invalid_incoming':s['delta']['prices'].loc[0,'close']=float('nan')
    else:
        extra=tmp_path/'duplicate/report.json';extra.parent.mkdir()
        extra.write_text(json.dumps(s['reports'][0]),encoding='utf-8')
        s['metadata']['refs'].append(extension.reference(extra))
        s['input_path'].write_text(json.dumps(s['metadata']),encoding='utf-8')
        s['prior']['source_refs'][0]=extension.reference(s['input_path'])
        path=Path(s['prior_ref']['path']);path.write_text(json.dumps(s['prior']),encoding='utf-8');s['prior_ref']=extension.reference(path)
    with pytest.raises(ValueError,match=reason):s['advance']()


@pytest.mark.parametrize('field',['open','close','high','low','volume'])
@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1.])
def test_accepted_closed_vintage_refuses_bad_incoming_known_values_before_retention(tmp_path,monkeypatch,field,value):
    s=accepted_closed_vintage_case(tmp_path,monkeypatch)
    s['delta']['prices'].loc[0,field]=value
    with pytest.raises(ValueError,match='INCOMING_VINTAGE_VALUE_INVALID:'+field):s['advance']()


def test_accepted_closed_vintage_allows_zero_volume_but_not_duplicate_keys(tmp_path,monkeypatch):
    s=accepted_closed_vintage_case(tmp_path,monkeypatch);s['delta']['prices'].loc[0,'volume']=0.
    result,_=s['advance']();assert result['prices'].loc[0,'volume']==100.
    original=s['delta']['prices'].copy()
    s['delta']['prices']=pd.concat([original,original.iloc[[0]]],ignore_index=True)
    with pytest.raises(ValueError,match='DELTA_DATE_KEYS_INVALID'):s['advance']()
    # The unchanged original no-conflict tail-only API remains legal: the
    # old capture is still its own authority, without a dual-vintage claim.
    s['delta']['prices']=original.iloc[1:]
    monkeypatch.setattr(extension,'_accepted_closed_vintage_proof',lambda *a:pytest.fail('tail-only input must not request closed-vintage permission'))
    result,metadata=s['advance']()
    assert 'accepted_closed_vintage_continuation' not in metadata['capture_reuse']
    pd.testing.assert_frame_equal(result['prices'].iloc[[0]].reset_index(drop=True),s['old_prices'],check_exact=True)


# Existing expanded lineage schema stores adapter custody in its immutable manifest.
def expanded_closed_vintage_case(tmp_path, monkeypatch):
    import json, copy
    from scripts import daily_recommendation_prices as original
    state = accepted_closed_vintage_case(tmp_path, monkeypatch)
    owned = tmp_path/'frozen_original';owned.mkdir()
    adapter=owned/'run_rebuild.py';adapter.write_text('frozen original adapter',encoding='utf-8')
    coverage=owned/'input_coverage.json';coverage.write_text('{}',encoding='utf-8')
    script=owned/'scripts/daily_recommendation_prices.py';script.parent.mkdir();script.write_text('original schema owner',encoding='utf-8')
    historical=script.parent/'research/a2/inference/historical_top40_prices.py'
    historical.parent.mkdir(parents=True);historical.write_text('original expanded schema owner',encoding='utf-8')
    monkeypatch.setattr(original,'ADAPTER_PATH',adapter)
    monkeypatch.setattr(original,'ADAPTER_SHA',extension.reference(adapter)['sha256'])
    monkeypatch.setattr(original,'COVERAGE_PATH',coverage)
    monkeypatch.setattr(original,'COVERAGE_SHA',extension.reference(coverage)['sha256'])
    monkeypatch.setattr(original,'__file__',str(script))
    manifests=[]
    for entry,report,factor in zip(state['entries'],state['reports'],state['factors']):
        entry.pop('adapter_sha256');entry.pop('coverage_manifest_sha256')
        entry['source']='MOOMOO_OPEND_RAW_PLUS_REHAB'
        entry['raw_end']=report['data_date']
        entry['vintage_semantics']='LATER_VENDOR_REHAB_SNAPSHOT_REPLAYED_BY_EX_DATE_NOT_HISTORICAL_PUBLICATION_VINTAGE'
        entry['rehab']={**extension.reference(factor),'kind':'CURRENT_SNAPSHOT','fetched_at':entry['rehab_fetched_at']}
        path=Path(report['report_path']).parent/'expanded_anchor_inputs/prices/manifest.json'
        path.parent.mkdir(parents=True)
        doc={'schema':'A2_HISTORICAL_EXPANDED_PRICE_INPUTS_V1',
            'start':report['data_date'],'end':report['data_date'],
            'vintage_semantics':entry['vintage_semantics'],
            'references':{'coverage':extension.reference(coverage)},
            'verified_sources':[extension.reference(adapter),extension.reference(coverage)],
            'implementation_refs':[extension.reference(historical),extension.reference(script)],
            'lineage':[copy.deepcopy({key:value for key,value in entry.items() if key not in {'source','expanded_anchor_manifest','calendar_lineage','price_warnings'}})]}
        path.write_text(json.dumps(doc,sort_keys=True),encoding='utf-8')
        entry['expanded_anchor_manifest']=extension.reference(path)
        manifests.append(path)
    state['manifests']=manifests
    state['save']()
    def rewrite(index, mutate):
        path=manifests[index];doc=json.loads(path.read_text(encoding='utf-8'));mutate(doc)
        path.write_text(json.dumps(doc,sort_keys=True),encoding='utf-8')
        state['entries'][index]['expanded_anchor_manifest']=extension.reference(path);state['save']()
    state['rewrite']=rewrite;return state


@pytest.mark.parametrize('field',['close','volume'])
def test_expanded_schema_keeps_original_prefix_and_binds_original_manifest_authorities(tmp_path,monkeypatch,field):
    state=expanded_closed_vintage_case(tmp_path,monkeypatch)
    state['delta']['prices'].loc[0,field]+=1.
    after,metadata=state['advance']()
    old=state['old_prices'].sort_values(['trade_date','ticker']).reset_index(drop=True)
    prefix=after['prices'].loc[after['prices'].trade_date.le(pd.Timestamp('2026-10-02'))].reset_index(drop=True)
    pd.testing.assert_frame_equal(prefix[old.columns],old,check_exact=True)
    proof=metadata['capture_reuse']['accepted_closed_vintage_continuation']['ticker_proofs'][0]
    assert proof['past_factor_stream_exact'] is True
    bindings=proof['expanded_adapter_bindings'];assert len(bindings)==2
    assert bindings[0]['implementation_refs']==bindings[1]['implementation_refs']
    assert bindings[0]['manifest']==extension.reference(state['manifests'][0])
    assert bindings[1]['manifest']==extension.reference(state['manifests'][1])
    assert all('adapter_sha256' not in entry for entry in state['entries'])
    # Old capture never needed this transitive manifest as a direct leaf.
    assert bindings[0]['manifest'] not in state['metadata']['refs']


@pytest.mark.parametrize('fault',[
    'missing_manifest','bad_manifest_hash','wrong_schema','wrong_date','lineage_drift',
    'wrong_adapter','wrong_coverage','missing_coverage','missing_implementation',
    'bad_implementation_hash','explicit_wrong_adapter','only_one_standard_field',
    'native_not_expanded','mixed_schema','outside_owner','duplicate_lineage','future_clock'])
def test_expanded_schema_missing_or_changed_original_custody_is_rejected(tmp_path,monkeypatch,fault):
    import json,copy
    from scripts import daily_recommendation_prices as original
    state=expanded_closed_vintage_case(tmp_path,monkeypatch);entry=state['entries'][1]
    if fault=='missing_manifest':entry.pop('expanded_anchor_manifest');state['save']()
    elif fault=='bad_manifest_hash':entry['expanded_anchor_manifest']['sha256']='0'*64;state['save']()
    elif fault=='wrong_schema':state['rewrite'](1,lambda doc:doc.update(schema='UNKNOWN'))
    elif fault=='wrong_date':state['rewrite'](1,lambda doc:doc.update(start='2026-10-02'))
    elif fault=='lineage_drift':state['rewrite'](1,lambda doc:doc['lineage'][0].update(code='US.OTHER'))
    elif fault=='wrong_adapter':state['rewrite'](1,lambda doc:doc['verified_sources'].pop(0))
    elif fault=='wrong_coverage':state['rewrite'](1,lambda doc:doc['references']['coverage'].update(sha256='0'*64))
    elif fault=='missing_coverage':state['rewrite'](1,lambda doc:doc['references'].pop('coverage'))
    elif fault=='missing_implementation':state['rewrite'](1,lambda doc:doc.update(implementation_refs=[]))
    elif fault=='bad_implementation_hash':state['rewrite'](1,lambda doc:doc['implementation_refs'][0].update(sha256='0'*64))
    elif fault=='explicit_wrong_adapter':entry.update(adapter_sha256='0'*64,coverage_manifest_sha256=original.COVERAGE_SHA);state['save']()
    elif fault=='only_one_standard_field':entry['adapter_sha256']=original.ADAPTER_SHA;state['save']()
    elif fault=='native_not_expanded':
        entry.pop('expanded_anchor_manifest');entry['anchor_proof']={'kind':'NEW_13F_MEMBER_NATIVE_RAW_ANCHOR'};state['save']()
    elif fault=='mixed_schema':
        prior=state['entries'][0];prior.pop('expanded_anchor_manifest');prior.update(adapter_sha256=original.ADAPTER_SHA,coverage_manifest_sha256=original.COVERAGE_SHA);state['save']()
    elif fault=='outside_owner':
        outside=tmp_path/'outside_manifest.json';outside.write_bytes(state['manifests'][1].read_bytes());entry['expanded_anchor_manifest']=extension.reference(outside);state['save']()
    elif fault=='duplicate_lineage':state['rewrite'](1,lambda doc:doc['lineage'].append(copy.deepcopy(doc['lineage'][0])))
    elif fault=='future_clock':state['rewrite'](1,lambda doc:doc.update(end='2027-01-01'))
    with pytest.raises(ValueError,match='VINTAGE_|SOURCE_HASH_MISMATCH'):
        state['advance']()


# Existing current Raw candidates may append their own qualified unconsumed tail.
def existing_candidate_tail_case(tmp_path,monkeypatch,*,indirect_old_raw=False):
    import json
    s=accepted_closed_vintage_case(tmp_path,monkeypatch)
    s['old_prices']['trade_date']=pd.Timestamp('2026-10-01')
    path=Path(s['metadata']['captured_prices']['path'])
    s['old_prices'].to_parquet(path,index=False);s['metadata']['captured_prices']=extension.reference(path)
    s['delta']['prices']=pd.concat([s['old_prices'],
        s['old_prices'].assign(trade_date=pd.Timestamp('2026-10-02')),
        s['old_prices'].assign(trade_date=pd.Timestamp('2026-10-05'))],ignore_index=True)
    base=s['save']
    def save():
        base()
        if indirect_old_raw:
            oldraw=s['entries'][0]['raw_sources'][-1]['path']
            s['metadata']['refs']=[ref for ref in s['metadata']['refs'] if ref['path']!=oldraw]
            s['input_path'].write_text(json.dumps(s['metadata']),encoding='utf-8')
            s['prior']['source_refs'][0]=extension.reference(s['input_path'])
            m=Path(s['prior_ref']['path']);m.write_text(json.dumps(s['prior']),encoding='utf-8')
            s['prior_ref']=extension.reference(m)
    s['save']=save;save();return s


@pytest.mark.parametrize('indirect_old_raw',[False,True])
def test_existing_raw_candidate_qualified_tail_preserves_known_prefix_and_hash_owned_sources(tmp_path,monkeypatch,indirect_old_raw):
    s=existing_candidate_tail_case(tmp_path,monkeypatch,indirect_old_raw=indirect_old_raw)
    custody={Path(ref['path']):Path(ref['path']).read_bytes() for ref in s['metadata']['refs']}
    result,meta=s['advance']()
    pd.testing.assert_frame_equal(result['prices'].iloc[[0]].reset_index(drop=True),s['old_prices'],check_exact=True)
    proof=meta['capture_reuse']['qualified_existing_raw_candidate_tails']
    row=proof['ticker_proofs'][0]
    assert row['security_id']=='sid-A' and row['accepted_ticker_last_date']=='2026-10-01'
    assert row['appended_past_dates']==['2026-10-02']
    assert bool(row['transitively_bound_unused_old_raw_sources'])==indirect_old_raw
    assert proof['historical_price_revisions_applied'] is False
    assert meta['capture_reuse']['model_feature_eligibility_granted'] is False
    assert all(path.read_bytes()==data for path,data in custody.items())
    assert len(result['prices'])==3
    extension._verify_prior_price_prefix(result['prices'],meta,s['prior'],s['metadata']['captured_prices'])


@pytest.mark.parametrize('fault,reason',[
    ('earlier_date','UNBOUND_OLD_DATE_ADDITION'),('internal_hole','UNBOUND_OLD_DATE_ADDITION'),
    ('not_current_raw','UNBOUND_OLD_DATE_ADDITION'),('direct_policy','UNBOUND_OLD_DATE_ADDITION'),
    ('sid','SECURITY_IDENTITY_CHANGED'),('code','ANCHOR_OR_ADAPTER_CHANGED'),
    ('anchor_file','ORIGINAL_RAW_ANCHOR_CHANGED'),('missing_old_anchor','RAW_SOURCE_UNBOUND'),
    ('missing_new_raw','RAW_SOURCE_UNBOUND'),('unrecognized_old_role','RAW_SOURCE_UNBOUND'),
    ('adapter','ANCHOR_OR_ADAPTER_CHANGED|PRICE_PROOF_MISMATCH'),
    ('coverage','ANCHOR_OR_ADAPTER_CHANGED|PRICE_PROOF_MISMATCH'),
    ('past_factor','PAST_REHAB_FACTS_CHANGED'),('missing_old_key','OLD_HISTORY_KEYS_CHANGED'),
    ('missing_event','PAST_EVENT_FACT_MISSING'),('changed_event','PAST_EVENT_FACT_CHANGED'),
    ('new_past_event','PAST_EVENT_REVISION'),('wrong_model','REPORT_IDENTITY_INVALID'),
    ('tampered_old_raw','SOURCE_HASH_MISMATCH'),('tampered_old_lineage','SOURCE_HASH_MISMATCH')])
def test_existing_raw_candidate_tail_refuses_unbound_identity_source_internal_history_and_ca(tmp_path,monkeypatch,fault,reason):
    import json
    from scripts.research.a2.portfolio import selected_hgb as selected
    s=existing_candidate_tail_case(tmp_path,monkeypatch,indirect_old_raw=True);new=s['entries'][1]
    if fault=='earlier_date':s['delta']['prices']=pd.concat([s['delta']['prices'],s['old_prices'].assign(trade_date=pd.Timestamp('2026-09-30'))],ignore_index=True)
    elif fault=='internal_hole':
        s['old_prices']=pd.concat([s['old_prices'].assign(trade_date=pd.Timestamp('2026-09-30')),s['old_prices'].assign(trade_date=pd.Timestamp('2026-10-02'))],ignore_index=True)
        path=Path(s['metadata']['captured_prices']['path']);s['old_prices'].to_parquet(path,index=False);s['metadata']['captured_prices']=extension.reference(path)
        s['delta']['prices']=pd.concat([s['old_prices'],s['old_prices'].iloc[[0]].assign(trade_date=pd.Timestamp('2026-10-01')),s['old_prices'].iloc[[0]].assign(trade_date=pd.Timestamp('2026-10-05'))],ignore_index=True)
    elif fault=='not_current_raw':s['reports'][1]['ranked_rows'][0]['rank']=41
    elif fault=='direct_policy':
        s['package']['policy_id']=selected.DIRECT_POLICY
        monkeypatch.setattr(selected,'active_policy',lambda *a:(selected.DIRECT_POLICY,s['report_path']))
    elif fault=='sid':
        frame=pd.read_parquet(s['mappings'][1]);frame['security_id']='different';frame.to_parquet(s['mappings'][1],index=False)
    elif fault=='code':new['code']='US.OTHER'
    elif fault=='anchor_file':
        path=tmp_path/'different_anchor';path.write_text('changed');new['raw_sources'][0]={**extension.reference(path),'role':'ORIGINAL_ANCHOR'}
    elif fault=='unrecognized_old_role':s['entries'][0]['raw_sources'][-1]['role']='UNKNOWN'
    elif fault=='adapter':new['adapter_sha256']='0'*64
    elif fault=='coverage':new['coverage_manifest_sha256']='0'*64
    elif fault=='past_factor':
        frame=pd.read_parquet(s['factors'][1]);frame['forward_adj_factorB']+=1.;frame.to_parquet(s['factors'][1],index=False)
    elif fault=='missing_old_key':s['delta']['prices']=s['delta']['prices'].iloc[1:].reset_index(drop=True)
    elif fault=='missing_event':s['delta']['events']=s['delta']['events'].iloc[:0]
    elif fault=='changed_event':s['delta']['events']['factor_b']+=1.
    elif fault=='new_past_event':
        s['delta']['events']=pd.concat([s['delta']['events'],s['events'].assign(audit_kind='NEW_PAST_CA')],ignore_index=True)
    elif fault=='wrong_model':s['reports'][1]['model_sha256']='0'*64
    s['save']()
    if fault=='missing_old_anchor':
        anchor=s['entries'][0]['raw_sources'][0]['path'];s['metadata']['refs']=[r for r in s['metadata']['refs'] if r['path']!=anchor]
        s['input_path'].write_text(json.dumps(s['metadata']),encoding='utf-8');s['prior']['source_refs'][0]=extension.reference(s['input_path'])
        m=Path(s['prior_ref']['path']);m.write_text(json.dumps(s['prior']),encoding='utf-8');s['prior_ref']=extension.reference(m)
    elif fault=='missing_new_raw':s['delta']['refs']=[r for r in s['delta']['refs'] if r['path']!=new['raw_sources'][-1]['path']]
    elif fault=='tampered_old_raw':Path(s['entries'][0]['raw_sources'][-1]['path']).write_text('changed after binding')
    elif fault=='tampered_old_lineage':
        path=Path(s['reports'][0]['report_path']).parent/'input_lineage.json';rows=json.loads(path.read_text(encoding='utf-8'));rows[0]['anchor_date']='2020-01-03';path.write_text(json.dumps(rows),encoding='utf-8')
    with pytest.raises(ValueError,match=reason):s['advance']()


@pytest.mark.parametrize('field,value',[('open',0.),('close',float('nan')),('high',float('inf')),('low',-1.),('volume',-1.)])
def test_existing_raw_candidate_tail_bad_new_value_is_not_hidden_by_preserved_old_marks(tmp_path,monkeypatch,field,value):
    s=existing_candidate_tail_case(tmp_path,monkeypatch);s['delta']['prices'].loc[1,field]=value
    with pytest.raises(ValueError,match='CANDIDATE_TAIL_VALUES_INVALID'):s['advance']()


def test_existing_raw_candidate_tail_same_raw_reference_can_append_without_revising_old_values(tmp_path,monkeypatch):
    s=existing_candidate_tail_case(tmp_path,monkeypatch);s['entries'][1]['raw_sources']=s['entries'][0]['raw_sources'].copy();s['save']()
    _,meta=s['advance']();assert meta['capture_reuse']['known_price_fields_all_exact'] is True


def test_existing_raw_candidate_tail_later_than_global_end_keeps_original_tail_only_behavior(tmp_path,monkeypatch):
    s=existing_candidate_tail_case(tmp_path,monkeypatch);s['delta']['prices']=s['delta']['prices'].iloc[[2]].reset_index(drop=True)
    monkeypatch.setattr(extension,'_accepted_closed_vintage_proof',lambda *a,**kw:pytest.fail('ordinary new-day tail needs no historical-extension proof'))
    result,meta=s['advance']();assert len(result['prices'])==2
    assert 'qualified_existing_raw_candidate_tails' not in meta['capture_reuse']


# The accepted research prior owns SID for original missing-column daily features.
def prior_legacy_feature_identity_case(tmp_path,monkeypatch,date_storage='timestamp'):
    from scripts.research.a2.portfolio import selected_hgb as selected
    root=tmp_path/'frozen';(root/'test2026').mkdir(parents=True)
    def rows(day):
        return pd.DataFrame({'signal_date':pd.Timestamp(day),'ticker':[f'T{i:02d}' for i in range(1,41)],
            'security_id':[f'id{i:02d}' for i in range(1,41)],'raw_rank':range(1,41),
            'raw_score':[i/1000 for i in range(1,41)],'f1':[.1]*40,
            'pred_hgb':[i/2000 for i in range(1,41)],'pred_q10':[-.02]*40})
    first=rows('2026-01-02');original=root/'test2026/predictions.parquet';first.to_parquet(original,index=False)
    expected=rows('2026-01-05');legacy=expected.drop(columns=['security_id','pred_hgb','pred_q10']).rename(columns={'signal_date':'trade_date'})
    future=legacy.assign(trade_date=pd.Timestamp('2026-01-06'));outside=legacy.assign(trade_date=pd.Timestamp('2027-01-01'))
    if date_storage=='iso_string':
        for frame in (legacy,future,outside):frame['trade_date']=frame.trade_date.dt.strftime('%Y-%m-%d')
    feature=tmp_path/'selected_hgb_features.parquet';pd.concat([legacy,future,outside],ignore_index=True).to_parquet(feature,index=False)
    owner=tmp_path/'owner';owner.write_text('synthetic canonical owner')
    prior={'strategies':{'HGB':{'targets':[{'signal_date':'2026-01-02'},{'signal_date':'2026-01-05'}]}},
        'source_refs':[extension.reference(original),extension.reference(feature)],
        'shared_scores_historical':[row for frame in (first,expected) for row in selected._score_rows(frame,signal_date=str(frame.signal_date.iloc[0].date()))]}
    fake=SimpleNamespace(REPLAY_HASHES={'test2026/predictions.parquet':extension.reference(original)['sha256']},FEATURES=('f1',),
        active_policy=lambda *a:(selected.LEGACY_POLICY,owner),_score_rows=selected._score_rows,
        _normalise_day=lambda frame,*a:(frame.rename(columns={'trade_date':'signal_date'}).assign(signal_date=pd.to_datetime(frame['signal_date' if 'signal_date' in frame else 'trade_date'])),str(pd.Timestamp(frame['signal_date' if 'signal_date' in frame else 'trade_date'].iloc[0]).date())))
    monkeypatch.setattr(extension,'_accepted_owner',lambda *a:(extension.reference(owner),{},[]))
    calls=[]
    class Frozen:
        def __init__(self,q=False):self.q=q
        def predict(self,frame):calls.append(len(frame));return [-.02]*len(frame) if self.q else [i/2000 for i in range(1,len(frame)+1)]
        def fit(self,*a):pytest.fail('No fitting')
    runtime={'model':Frozen(),'q10':Frozen(True)}
    return fake,root,prior,legacy,feature,runtime,calls


@pytest.mark.parametrize('date_storage',['timestamp','iso_string'])
def test_prior_legacy_feature_identity_uses_exact_prior_day_and_preserves_features_before_concat(tmp_path,monkeypatch,date_storage):
    fake,root,prior,legacy,feature,runtime,calls=prior_legacy_feature_identity_case(tmp_path,monkeypatch,date_storage)
    custody=feature.read_bytes()
    frames,refs,_,_=extension._load_prior_sources(SimpleNamespace(),fake,root,prior,'2026-01-06')
    assert len(frames)==2 and len(frames[1])==40
    pd.testing.assert_frame_equal(frames[1][legacy.columns],legacy,check_exact=True)
    panel=extension.score_panel(frames,fake,runtime)
    extension._verify_prior_scores(panel,prior,fake)
    assert frames[1].security_id.tolist()==[f'id{i:02d}' for i in range(1,41)]
    assert set(panel.signal_date.dt.strftime('%Y-%m-%d'))=={'2026-01-02','2026-01-05'}
    assert calls==[40,40] and feature.read_bytes()==custody
    assert extension.reference(feature) in refs


@pytest.mark.parametrize('fault',[
    'missing_expected_day','missing_expected_row','duplicate_expected_sid','blank_expected_sid',
    'changed_expected_rank','changed_expected_score','unknown_feature_ticker','duplicate_feature_ticker',
    'changed_feature_rank','changed_feature_score','missing_feature_row','bad_feature_hash',
    'present_wrong_sid','present_null_sid','present_duplicate_sid','tampered_feature_file'])
def test_prior_legacy_feature_identity_refuses_unbound_or_changed_identity_without_repairing_present_ids(tmp_path,monkeypatch,fault):
    fake,root,prior,legacy,feature,runtime,calls=prior_legacy_feature_identity_case(tmp_path,monkeypatch)
    expected=[row for row in prior['shared_scores_historical'] if row['signal_date']=='2026-01-05']
    f=pd.read_parquet(feature)
    if fault=='missing_expected_day':prior['shared_scores_historical']=[row for row in prior['shared_scores_historical'] if row['signal_date']!='2026-01-05']
    elif fault=='missing_expected_row':prior['shared_scores_historical'].remove(expected[-1])
    elif fault=='duplicate_expected_sid':expected[1]['security_id']=expected[0]['security_id']
    elif fault=='blank_expected_sid':expected[0]['security_id']=''
    elif fault=='changed_expected_rank':expected[0]['raw_rank']=2
    elif fault=='changed_expected_score':expected[0]['raw_score']+=.01
    elif fault=='unknown_feature_ticker':f.loc[0,'ticker']='UNKNOWN'
    elif fault=='duplicate_feature_ticker':f.loc[0,'ticker']=f.loc[1,'ticker']
    elif fault=='changed_feature_rank':f.loc[0,'raw_rank']=2
    elif fault=='changed_feature_score':f.loc[0,'raw_score']+=.01
    elif fault=='missing_feature_row':f=f.drop(index=0)
    elif fault.startswith('present_'):
        f['security_id']=[f'id{i:02d}' for i in range(1,41)]*3
        if fault=='present_wrong_sid':f.loc[0,'security_id']='wrong-existing-id'
        elif fault=='present_null_sid':f.loc[0,'security_id']=None
        else:f.loc[0,'security_id']=f.loc[1,'security_id']
    if fault not in ('bad_feature_hash','tampered_feature_file'):
        f.to_parquet(feature,index=False);prior['source_refs'][1]=extension.reference(feature)
    elif fault=='bad_feature_hash':prior['source_refs'][1]['sha256']='0'*64
    else:feature.write_bytes(b'changed after SHA binding')
    with pytest.raises((ValueError,AssertionError)):
        frames,_,_,_=extension._load_prior_sources(SimpleNamespace(),fake,root,prior,'2026-01-06')
        if fault.startswith('present_'):
            assert frames[1].security_id.iloc[0]==f.security_id.iloc[0] or pd.isna(frames[1].security_id.iloc[0])
        panel=extension.score_panel(frames,fake,runtime)
        extension._verify_prior_scores(panel,prior,fake)


# Capture and replay must use the same accepted, unconsumed Raw40 signals.
def pending_signal_price_scope_case(tmp_path,monkeypatch,*,prior_rows=False):
    import json
    from scripts.research.a2.evaluation import demo_performance_prices as reader
    s=existing_candidate_tail_case(tmp_path,monkeypatch,indirect_old_raw=True)
    s['reports'][1]['ranked_rows'][0]['rank']=495
    s['package']['shared_scores']['current']['rows']=[]
    s['save']()
    leaf=tmp_path/'accepted_snapshot_source.json';leaf.write_text('immutable accepted candidate',encoding='utf-8')
    ref=extension.reference(leaf)
    snapshot={'signal_date':'2026-10-02','report_binding':{'raw_top40':[
        {'ticker':'A','security_id':'sid-A','raw_rank':1,'raw_score':.1}]},
        'source_refs':{'current/report.json':ref,'current/selected_hgb_features.parquet':ref}}
    snapshots={'2026-10-02':snapshot};refs=[ref]
    if prior_rows:
        s['prior']['shared_scores_historical']=[{'signal_date':'2026-10-02','ticker':'A',
            'security_id':'sid-A','raw_rank':1,'raw_score':.1}]
        snapshots.clear()
    monkeypatch.setattr(extension,'accepted_snapshots',lambda *a:(snapshots,refs))
    requested=[]
    def load(*a,**kw):requested.append(kw['tickers']);return s['delta']
    monkeypatch.setattr(reader,'load_execution_prices',load)
    s.update(snapshot=snapshot,snapshots=snapshots,snapshot_refs=refs,snapshot_leaf=leaf,requested=requested)
    return s


@pytest.mark.parametrize('prior_rows',[False,True])
def test_pending_signal_price_scope_captures_dropped_current_candidate_and_strict_tail(tmp_path,monkeypatch,prior_rows):
    s=pending_signal_price_scope_case(tmp_path,monkeypatch,prior_rows=prior_rows)
    old=s['old_prices'].copy();before={Path(ref['path']):Path(ref['path']).read_bytes() for ref in s['metadata']['refs']}
    result,meta=s['advance']()
    assert 'A' in s['requested'][0]
    assert list(result['prices'].trade_date.dt.strftime('%Y-%m-%d'))==['2026-10-01','2026-10-02','2026-10-05']
    pd.testing.assert_frame_equal(result['prices'].iloc[[0]].reset_index(drop=True),old,check_exact=True)
    row=meta['capture_reuse']['qualified_existing_raw_candidate_tails']['ticker_proofs'][0]
    assert row['existing_current_raw_candidate_tail'] is False
    assert row['accepted_unconsumed_raw_candidate_tail'] is True
    assert row['security_id']=='sid-A' and row['appended_past_dates']==['2026-10-02']
    assert len(meta['capture_reuse']['accepted_unconsumed_raw_candidate_signals'])==(0 if prior_rows else 1)
    assert meta['capture_reuse']['model_feature_eligibility_granted'] is False
    assert all(p.read_bytes()==b for p,b in before.items())
    extension._verify_prior_price_prefix(result['prices'],meta,s['prior'],s['metadata']['captured_prices'])


@pytest.mark.parametrize('fault,reason',[
    ('consumed','UNBOUND_OLD_DATE_ADDITION'),('older','UNBOUND_OLD_DATE_ADDITION'),
    ('future','UNBOUND_OLD_DATE_ADDITION'),('not_selected','UNBOUND_OLD_DATE_ADDITION'),
    ('snapshot_sid','SECURITY_IDENTITY_CHANGED'),('missing_sid','UNBOUND_OLD_DATE_ADDITION'),('identity_conflict','UNCONSUMED_CANDIDATE_IDENTITY_CHANGED'),
    ('archive_hash','SOURCE_HASH_MISMATCH'),('missing_old_key','OLD_HISTORY_KEYS_CHANGED'),
    ('internal_hole','UNBOUND_OLD_DATE_ADDITION'),('missing_new_raw','RAW_SOURCE_UNBOUND'),
    ('source_anchor','ORIGINAL_RAW_ANCHOR_CHANGED'),('past_factor','PAST_REHAB_FACTS_CHANGED'),
    ('missing_event','PAST_EVENT_FACT_MISSING'),('new_past_event','PAST_EVENT_REVISION')])
def test_pending_signal_price_scope_refuses_unowned_or_changed_historical_inputs(tmp_path,monkeypatch,fault,reason):
    s=pending_signal_price_scope_case(tmp_path,monkeypatch)
    if fault=='consumed':s['prior']['strategies']['HGB']['targets']=[{'signal_date':'2026-10-02','rows':[]}]
    elif fault in {'older','future'}:
        day='2026-10-01' if fault=='older' else '2026-10-06';s['snapshots'].clear();s['snapshot']['signal_date']=day;s['snapshots'][day]=s['snapshot']
    elif fault=='not_selected':s['snapshots'].clear()
    elif fault=='snapshot_sid':s['snapshot']['report_binding']['raw_top40'][0]['security_id']='different'
    elif fault=='missing_sid':del s['snapshot']['report_binding']['raw_top40'][0]['security_id']
    elif fault=='identity_conflict':s['prior']['shared_scores_historical']=[{'signal_date':'2026-10-02','ticker':'A','security_id':'different','raw_rank':1}]
    elif fault=='archive_hash':s['snapshot_leaf'].write_text('changed immutable snapshot',encoding='utf-8')
    elif fault=='missing_old_key':s['delta']['prices']=s['delta']['prices'].iloc[1:].reset_index(drop=True)
    elif fault=='internal_hole':
        old=pd.concat([s['old_prices'].assign(trade_date=pd.Timestamp('2026-09-30')),s['old_prices'].assign(trade_date=pd.Timestamp('2026-10-02'))],ignore_index=True)
        p=Path(s['metadata']['captured_prices']['path']);old.to_parquet(p,index=False);s['metadata']['captured_prices']=extension.reference(p)
        s['delta']['prices']=pd.concat([old,old.iloc[[0]].assign(trade_date=pd.Timestamp('2026-10-01')),old.iloc[[0]].assign(trade_date=pd.Timestamp('2026-10-05'))],ignore_index=True);s['save']()
    elif fault=='missing_new_raw':s['delta']['refs']=[r for r in s['delta']['refs'] if r['path']!=s['entries'][1]['raw_sources'][-1]['path']]
    elif fault=='source_anchor':
        p=tmp_path/'wrong_anchor';p.write_text('wrong anchor',encoding='utf-8');s['entries'][1]['raw_sources'][0]={**extension.reference(p),'role':'ORIGINAL_ANCHOR'};s['save']()
    elif fault=='past_factor':
        f=pd.read_parquet(s['factors'][1]);f['forward_adj_factorB']+=1.;f.to_parquet(s['factors'][1],index=False);s['save']()
    elif fault=='missing_event':s['delta']['events']=s['delta']['events'].iloc[:0]
    elif fault=='new_past_event':s['delta']['events']=pd.concat([s['delta']['events'],s['events'].assign(audit_kind='UNBOUND_EVENT')],ignore_index=True)
    with pytest.raises(ValueError,match=reason):s['advance']()


def test_pending_signal_price_scope_keeps_missing_execution_price_and_all_economic_prefix_gates(tmp_path,monkeypatch):
    s=pending_signal_price_scope_case(tmp_path,monkeypatch)
    s['delta']['prices']=s['delta']['prices'].iloc[:2].copy()
    result,meta=s['advance']()
    assert pd.Timestamp('2026-10-05') not in set(result['prices'].trade_date)
    assert meta['capture_reuse']['known_price_fields_all_exact'] is True
    # Names are qualified independently; an absent execution row remains absent.
    assert 'A' in s['requested'][0]


def test_pending_signal_price_scope_name_only_prior_does_not_grant_suffix_identity(tmp_path,monkeypatch):
    s=pending_signal_price_scope_case(tmp_path,monkeypatch,prior_rows=True)
    del s['prior']['shared_scores_historical'][0]['security_id']
    with pytest.raises(ValueError,match='UNBOUND_OLD_DATE_ADDITION'):s['advance']()



def test_pending_signal_price_scope_direct_policy_does_not_adopt_legacy_suffix_permission(tmp_path,monkeypatch):
    from scripts.research.a2.portfolio import selected_hgb as selected
    s=pending_signal_price_scope_case(tmp_path,monkeypatch)
    s['package']['policy_id']=selected.DIRECT_POLICY
    monkeypatch.setattr(selected,'active_policy',lambda *a:(selected.DIRECT_POLICY,s['report_path']))
    monkeypatch.setattr(extension,'accepted_snapshots',lambda *a:pytest.fail('New pending suffix scope is LEGACY only'))
    with pytest.raises(ValueError,match='UNBOUND_OLD_DATE_ADDITION'):s['advance']()


def test_pending_signal_price_scope_accepted_day_prevents_other_ranking_vintage_join(tmp_path,monkeypatch):
    import json
    from scripts.research.a2.portfolio import selected_hgb as selected
    s=pending_signal_price_scope_case(tmp_path,monkeypatch)
    root=tmp_path/'original';(root/'test2026').mkdir(parents=True)
    original=root/'test2026/predictions.parquet'
    pd.DataFrame([{'signal_date':pd.Timestamp('2026-09-30'),'ticker':'OLD','security_id':'old-sid',
        'raw_rank':1,'raw_score':.1,'pred_hgb':.1,'pred_q10':-.1}]).to_parquet(original,index=False)
    ranking=tmp_path/'rankings.parquet'
    pd.DataFrame([{'target_date':pd.Timestamp('2026-10-02'),'ticker':'WRONG_VINTAGE','security_id':'wrong',
        'rank':1,'score':.2,'model_sha256':'invalid-later-vintage','model_year':2026}]).to_parquet(ranking,index=False)
    s['prior']['source_refs'].extend([extension.reference(original),extension.reference(ranking)])
    p=Path(s['prior_ref']['path']);p.write_text(json.dumps(s['prior']),encoding='utf-8');s['prior_ref']=extension.reference(p)
    monkeypatch.setattr(selected,'DEFAULT_SOURCE_ROOT',root)
    monkeypatch.setattr(selected,'REPLAY_HASHES',{**selected.REPLAY_HASHES,'test2026/predictions.parquet':extension.reference(original)['sha256']})
    result,meta=s['advance']()
    assert 'A' in s['requested'][0] and 'WRONG_VINTAGE' not in s['requested'][0]
    assert extension.reference(ranking) not in meta['refs']  # No other vintage selected for the accepted date.



def pending_new_ticker_scope_case(tmp_path,monkeypatch):
    s=pending_signal_price_scope_case(tmp_path,monkeypatch)
    old=s['old_prices'].assign(ticker='PRIOR_ONLY')
    p=Path(s['metadata']['captured_prices']['path']);old.to_parquet(p,index=False)
    s['metadata']['captured_prices']=extension.reference(p);s['old_prices']=old
    s['delta']['prices']=pd.concat([s['delta']['prices'],old],ignore_index=True);s['save']()
    return s


def test_pending_signal_price_scope_first_capture_requires_same_bound_security_and_preserves_old_prices(tmp_path,monkeypatch):
    s=pending_new_ticker_scope_case(tmp_path,monkeypatch)
    result,meta=s['advance']()
    assert 'A' in s['requested'][0]
    assert set(result['prices'].ticker)=={'A','PRIOR_ONLY'}
    pd.testing.assert_frame_equal(result['prices'].loc[result['prices'].ticker.eq('PRIOR_ONLY')].reset_index(drop=True),s['old_prices'],check_exact=True)
    assert meta['capture_reuse']['accepted_unconsumed_price_identity_bindings']==[{'ticker':'A','security_id':'sid-A','code':'US.A'}]
    assert 'qualified_existing_raw_candidate_tails' not in meta['capture_reuse']


@pytest.mark.parametrize('fault,reason',[
    ('different_sid','PENDING_SECURITY_IDENTITY_CHANGED'),('duplicate_member','PENDING_CURRENT_IDENTITY_DUPLICATE'),
    ('wrong_transport','PENDING_TRANSPORT_CODE_CHANGED|PRICE_PROOF_MISMATCH'),
    ('missing_member_wrong_historical_sid','PENDING_HISTORICAL_IDENTITY_UNBOUND')])
def test_pending_signal_price_scope_first_capture_cannot_use_another_security_same_ticker(tmp_path,monkeypatch,fault,reason):
    import json
    s=pending_new_ticker_scope_case(tmp_path,monkeypatch)
    f=pd.read_parquet(s['mappings'][1])
    if fault=='different_sid':f['security_id']='sid-B'
    elif fault=='duplicate_member':f=pd.concat([f,f],ignore_index=True)
    elif fault=='wrong_transport':f['moomoo_symbol']='US.OTHER'
    else:
        f=f.iloc[:0];p=tmp_path/'historical_price_manifest.json';doc=json.loads(p.read_text());doc['lineage'][0]['cusips']=['sid-B'];p.write_text(json.dumps(doc),encoding='utf-8');p=s['historical'];doc=json.loads(p.read_text());doc['price_manifest']=extension.reference(tmp_path/'historical_price_manifest.json');p.write_text(json.dumps(doc),encoding='utf-8')
    f.to_parquet(s['mappings'][1],index=False);s['save']()
    with pytest.raises(ValueError,match=reason):s['advance']()
    assert not s['requested']  # Reject before even calling the original price loader.


def test_pending_signal_price_scope_first_capture_keeps_original_same_sid_historical_fallback(tmp_path,monkeypatch):
    s=pending_new_ticker_scope_case(tmp_path,monkeypatch)
    f=pd.read_parquet(s['mappings'][1]).iloc[:0];f.to_parquet(s['mappings'][1],index=False);s['save']()
    result,meta=s['advance']()
    assert set(result['prices'].ticker)=={'A','PRIOR_ONLY'}
    assert meta['capture_reuse']['accepted_unconsumed_price_identity_bindings']==[{'ticker':'A','security_id':'sid-A','code':'US.A'}]


# A closed capture with a recorded eligible-price gap must not short-circuit
# the same accepted-candidate append path used by a fresh capture.
def pending_closed_incomplete_scope_case(tmp_path,monkeypatch):
    import json
    s=pending_signal_price_scope_case(tmp_path,monkeypatch)
    last=s['old_prices'].assign(ticker='PERSISTENT',trade_date=pd.Timestamp('2026-10-05'))
    s['old_prices']=pd.concat([s['old_prices'],last],ignore_index=True)
    p=Path(s['metadata']['captured_prices']['path']);s['old_prices'].to_parquet(p,index=False)
    s['metadata']['captured_prices']=extension.reference(p)
    s['delta']['prices']=pd.concat([s['delta']['prices'],last],ignore_index=True)
    s['metadata'].update(end_date='2026-10-05',gaps=[])
    s['metadata']['refs'].append(extension.reference(s['report_path']))
    s['input_path'].write_text(json.dumps(s['metadata']),encoding='utf-8')
    s['prior']['source_refs']=[extension.reference(s['input_path']),s['metadata']['captured_prices'],s['metadata']['events'],*s['metadata']['refs']]
    s['prior']['status']='PARTIAL'
    s['prior']['blocked_next']={'signal_date':'2026-10-02','execution_date':'2026-10-05',
        'reason':'ELIGIBLE_EXECUTION_PRICES_MISSING','keys':[['2026-10-02','A'],['2026-10-05','A']]}
    def persist():
        p=Path(s['prior_ref']['path']);p.write_text(json.dumps(s['prior']),encoding='utf-8')
        s['prior_ref']=extension.reference(p)
    persist();s['persist_closed']=persist
    return s


def test_pending_signal_price_scope_same_closed_incomplete_capture_uses_bound_append_and_preserves_prefix(tmp_path,monkeypatch):
    s=pending_closed_incomplete_scope_case(tmp_path,monkeypatch)
    old=s['old_prices'].copy()
    result,meta=s['advance']()
    assert len(s['requested'])==1 and 'A' in s['requested'][0]
    assert not meta['capture_reuse'].get('reused_accepted_closed_capture',False)
    assert meta['capture_reuse']['recaptured_blocked_eligible_execution_prices']==s['prior']['blocked_next']
    assert set(result['prices'].loc[result['prices'].ticker.eq('A'),'trade_date'])==set(pd.to_datetime(['2026-10-01','2026-10-02','2026-10-05']))
    before=old.set_index(['ticker','trade_date']);after=result['prices'].set_index(['ticker','trade_date'])
    pd.testing.assert_frame_equal(before,after.loc[before.index],check_exact=True)
    extension._verify_prior_price_prefix(result['prices'],meta,s['prior'],s['metadata']['captured_prices'])


@pytest.mark.parametrize('fault',['complete','wrong_reason','wrong_status','wrong_signal','wrong_execution','empty_keys','direct_policy'])
def test_pending_signal_price_scope_complete_or_unowned_same_closed_capture_still_reuses_without_loader(tmp_path,monkeypatch,fault):
    from scripts.research.a2.portfolio import selected_hgb as selected
    s=pending_closed_incomplete_scope_case(tmp_path,monkeypatch)
    if fault=='complete':s['prior'].pop('blocked_next')
    elif fault=='wrong_reason':s['prior']['blocked_next']['reason']='HELD_EXECUTION_PRICE_MISSING'
    elif fault=='wrong_status':s['prior']['status']='READY'
    elif fault=='wrong_signal':s['prior']['blocked_next']['signal_date']='2026-10-01'
    elif fault=='wrong_execution':s['prior']['blocked_next']['execution_date']='2026-10-06'
    elif fault=='empty_keys':s['prior']['blocked_next']['keys']=[]
    else:s['package']['policy_id']=selected.DIRECT_POLICY
    s['persist_closed']()
    result,meta=s['advance']()
    assert s['requested']==[]
    assert meta['capture_reuse']['reused_accepted_closed_capture'] is True
    assert 'recaptured_blocked_eligible_execution_prices' not in meta['capture_reuse']
    pd.testing.assert_frame_equal(result['prices'],s['old_prices'][result['prices'].columns],check_exact=True)


# Synthetic immutable per-field origin continuation: no real price/model input.
def field_origin_continuation_case(tmp_path,monkeypatch,*,same_raw=False,first_field=None):
    import json,copy
    from scripts.daily_recommendation_inputs import latest_completed_session
    from scripts import daily_recommendation_inputs as calendar
    s=accepted_closed_vintage_case(tmp_path,monkeypatch)
    if first_field is not None:s['delta']['prices'].loc[0,first_field]+=.1
    first,meta=s['advance']()
    def persist(result,metadata,label,end):
        root=tmp_path/label;root.mkdir()
        prices=root/'prices.parquet';result['prices'].to_parquet(prices,index=False)
        events=root/'events.parquet';result['events'].to_parquet(events,index=False)
        doc=copy.deepcopy(metadata);doc['captured_prices']=extension.reference(prices);doc['events']=extension.reference(events)
        path=root/'three_strategy_price_inputs.json';path.write_text(json.dumps(doc,sort_keys=True),encoding='utf-8')
        oldrefs=s['prior']['source_refs']
        s['prior']={'policy_id':s['package']['policy_id'],'performance_period':{'end':end},'strategies':{'HGB':{'targets':[]}},
            'source_refs':[*oldrefs,*doc['refs'],extension.reference(path),doc['captured_prices'],doc['events']]}
        manifest=root/'manifest.json';manifest.write_text(json.dumps(s['prior'],sort_keys=True),encoding='utf-8')
        s['prior_ref']=extension.reference(manifest)
        return path,doc
    s['persist']=persist;s['first_prices']=first['prices'].copy()
    s['first_capture'],s['first_metadata']=persist(first,meta,'level1','2026-10-05')
    def current(day,label,raw_new=True):
        root=tmp_path/label;root.mkdir()
        report=copy.deepcopy(s['reports'][1]);entry=copy.deepcopy(s['entries'][1]);report['data_date']=day;report['report_path']=str(root/'recommendation_source.json')
        if raw_new:
            raw=root/'raw';raw.write_text('recorded additional RAW vintage '+label,encoding='utf-8')
            entry['raw_sources'][1]={**extension.reference(raw),'role':'CURRENT_RAW'}
        entry['rehab_fetched_at']=day+'T21:00:00+00:00'
        lineage=root/'input_lineage.json';lineage.write_text(json.dumps([entry],sort_keys=True),encoding='utf-8')
        import hashlib
        report['input_manifest_sha256']=hashlib.sha256(json.dumps([entry],sort_keys=True).encode()).hexdigest()
        factor=s['factors'][1]
        receipt=root/'rehab_receipt.json';receipt.write_text(json.dumps({'source':'MOOMOO_OPEND_GET_REHAB','target_date':day,'results':[{'status':'PASS','code':'US.A',**extension.reference(factor),'fetched_at':entry['rehab_fetched_at']}]}),encoding='utf-8')
        Path(report['report_path']).write_text(json.dumps(report,sort_keys=True),encoding='utf-8')
        oldrefs=s['delta']['refs'];s['delta']['refs']=[*oldrefs,extension.reference(report['report_path']),extension.reference(lineage),extension.reference(receipt),*[{k:x[k] for k in ('path','sha256')} for x in entry['raw_sources']]]
        s['report_path']=Path(report['report_path'])
        monkeypatch.setattr(calendar,'latest_completed_session',lambda *a:{'target_date':day,'sessions':['2026-10-02','2026-10-05','2026-10-06','2026-10-07']})
        return report,entry
    s['current']=current;s['current']('2026-10-06','third',not same_raw)
    added=s['old_prices'].assign(trade_date=pd.Timestamp('2026-10-06'),close=9.8)
    s['delta']['prices']=pd.concat([s['delta']['prices'],added],ignore_index=True)
    return s


def test_field_origin_repeated_advances_keep_original_all_known_values(tmp_path,monkeypatch):
    s=field_origin_continuation_case(tmp_path,monkeypatch,same_raw=True)
    second,meta=s['advance']()
    pd.testing.assert_frame_equal(second['prices'].iloc[:2].reset_index(drop=True),s['first_prices'],check_exact=True)
    assert meta['capture_reuse']['accepted_closed_vintage_continuation']['accepted_field_origins'][0]['capture_ref']==extension.reference(s['input_path'])
    s['persist'](second,meta,'level2','2026-10-06')
    s['current']('2026-10-07','fourth')
    s['delta']['prices']=pd.concat([s['delta']['prices'],s['old_prices'].assign(trade_date=pd.Timestamp('2026-10-07'))],ignore_index=True)
    third,metadata=s['advance']()
    pd.testing.assert_frame_equal(third['prices'].iloc[:len(second['prices'])].reset_index(drop=True),second['prices'],check_exact=True)
    assert metadata['capture_reuse']['accepted_closed_vintage_continuation']['accepted_field_origins'][0]['accepted_report']==extension.reference(s['reports'][0]['report_path'])


def test_field_origin_mixed_fields_use_two_original_reports_and_project_keys(tmp_path,monkeypatch):
    s=field_origin_continuation_case(tmp_path,monkeypatch)
    s['delta']['prices'].loc[s['delta']['prices'].trade_date.eq(pd.Timestamp('2026-10-05')),'volume']+=1.
    calls=[];original=extension._capture_parquet
    def read(ref,**kw):
        if kw.get('price_keys') is not None:calls.append(kw.copy())
        return original(ref,**kw)
    monkeypatch.setattr(extension,'_capture_parquet',read)
    result,meta=s['advance']();audit=meta['capture_reuse']['accepted_closed_vintage_continuation']
    assert len(audit['accepted_field_origins'])==2
    assert audit['through']=='2026-10-05'
    assert {(row['origin_end'],row['prior_consumed_end'],row['rehab_facts_through'])
            for row in audit['ticker_proofs']}=={
        ('2026-10-02','2026-10-05','2026-10-02'),
        ('2026-10-05','2026-10-05','2026-10-05')}
    byfield={(x['trade_date'],x['field']):origin['accepted_report'] for origin in audit['accepted_field_origins'] for x in origin['fields']}
    assert byfield['2026-10-02','close']==extension.reference(s['reports'][0]['report_path'])
    assert byfield['2026-10-05','volume']==extension.reference(s['reports'][1]['report_path'])
    assert calls and all(x['columns']==list(s['old_prices'].columns) for x in calls)
    assert all({day for ticker,day in x['price_keys']}<={pd.Timestamp('2026-10-02'),pd.Timestamp('2026-10-05')} for x in calls)
    pd.testing.assert_frame_equal(result['prices'].iloc[:2].reset_index(drop=True),s['first_prices'],check_exact=True)


@pytest.mark.parametrize('fault,reason',[
    ('parent_sha','SOURCE_HASH_MISMATCH'),('missing_parent','ORIGIN_PARENT_MISSING'),
    ('parent_price','ORIGIN_PARENT_BINDING_CHANGED|ORIGIN_OWNER_BINDING_CHANGED'),('known_field','ORIGIN_KNOWN_FIELD_CHANGED'),
    ('audit','ORIGIN_AUDIT_CHANGED'),('missing_origin','PRIOR_REPORT_AMBIGUOUS')])
def test_field_origin_broken_or_contradictory_custody_rejects(tmp_path,monkeypatch,fault,reason):
    import json,copy
    s=field_origin_continuation_case(tmp_path,monkeypatch)
    doc=s['first_metadata'];base_read=extension._capture_json
    if fault=='parent_sha':s['input_path'].write_text('changed parent bytes',encoding='utf-8')
    else:
        virtual=copy.deepcopy(doc)
        if fault=='missing_parent':virtual['capture_reuse'].pop('inputs_ref')
        elif fault=='parent_price':virtual['capture_reuse']['prices_ref']={**virtual['capture_reuse']['prices_ref'],'sha256':'0'*64}
        elif fault=='audit':virtual['capture_reuse']['accepted_closed_vintage_continuation']['field_differences'][0]['accepted_value']=123.
        if fault=='known_field':
            import json
            changed=s['old_prices'].copy();changed['close']+=1.
            bad_price_path=tmp_path/'bad_parent_prices.parquet';changed.to_parquet(bad_price_path,index=False)
            bad_price_ref=extension.reference(bad_price_path)
            virtual['capture_reuse']['prices_ref']=bad_price_ref;virtual['refs'].append(bad_price_ref)
            owner=json.loads(Path(virtual['research_input_owner']['path']).read_text(encoding='utf-8'))
            owner['source_refs'].append(bad_price_ref)
            owner_path=tmp_path/'bad_parent_owner.json';owner_path.write_text(json.dumps(owner,sort_keys=True),encoding='utf-8')
            virtual['research_input_owner']=extension.reference(owner_path);virtual['refs'].append(extension.reference(owner_path))
        def read(path,expected=None):
            value,ref=base_read(path,expected)
            if Path(path)==s['first_capture']:return virtual,ref
            if Path(path)==s['input_path']:
                if fault=='known_field':value['captured_prices']=bad_price_ref
                if fault=='missing_origin':value['refs']=[r for r in value['refs'] if Path(r['path']).name not in {'recommendation_source.json','report.json'}]
            return value,ref
        monkeypatch.setattr(extension,'_capture_json',read)
    old=doc if fault=='parent_sha' else virtual
    before=s['first_prices']
    keys=[('A',pd.Timestamp('2026-10-02'),'close')]
    with pytest.raises((ValueError,KeyError),match=reason):
        extension._accepted_closed_vintage_proof(old,s['delta'],s['report_path'],s['historical'],
            '2026-10-05',before,s['delta']['prices'],{'A'},_field_keys=keys)


def test_field_origin_same_raw_true_new_field_change_still_rejects(tmp_path,monkeypatch):
    s=field_origin_continuation_case(tmp_path,monkeypatch,same_raw=True)
    s['delta']['prices'].loc[s['delta']['prices'].trade_date.eq(pd.Timestamp('2026-10-05')),'close']+=.04
    with pytest.raises(ValueError,match='SAME_RAW_PROOF_CHANGED_PRICE'):s['advance']()


def test_field_origin_cycle_rejects_without_full_price_read(tmp_path,monkeypatch):
    import copy
    s=field_origin_continuation_case(tmp_path,monkeypatch)
    doc=copy.deepcopy(s['first_metadata']);ref=extension.reference(s['first_capture'])
    doc['capture_reuse']['inputs_ref']=ref;doc['capture_reuse']['prices_ref']=doc['captured_prices']
    doc['refs'].extend([ref,doc['captured_prices']])
    doc['capture_reuse']['reused_accepted_closed_capture']=True
    base=extension._capture_json
    def read(path,expected=None):
        value,checked=base(path,expected)
        return (doc,checked) if Path(path)==s['first_capture'] else (value,checked)
    monkeypatch.setattr(extension,'_capture_json',read)
    with pytest.raises(ValueError,match='ORIGIN_CYCLE'):
        extension._accepted_closed_vintage_proof(doc,s['delta'],s['report_path'],s['historical'],
            '2026-10-05',s['first_prices'],s['delta']['prices'],{'A'},
            _field_keys=[('A',pd.Timestamp('2026-10-02'),'close')])


def test_vintage_error_does_not_attribute_global_first_field_to_first_ticker(tmp_path,monkeypatch):
    s=accepted_closed_vintage_case(tmp_path,monkeypatch)
    s['entries'][1]['raw_sources']=s['entries'][0]['raw_sources'];s['save']()
    with pytest.raises(ValueError,match='CLOSED_FIELD_CHANGED:VINTAGE_PROOF:VINTAGE_SAME_RAW_PROOF_CHANGED_PRICE:A'):
        s['advance']()


@pytest.mark.parametrize('complete',[True,False])
def test_field_origin_existing_open_reuse_marker_only_preserves_closed_fields(tmp_path,monkeypatch,complete):
    import copy
    s=field_origin_continuation_case(tmp_path,monkeypatch)
    doc=copy.deepcopy(s['first_metadata']);reuse=doc['capture_reuse']
    reuse.pop('known_price_fields_all_exact');reuse['existing_prices_all_fields_exact']=True
    reuse['existing_event_audit_exact']=complete
    path=tmp_path/'parent_open_manifest.json';path.write_text('{}',encoding='utf-8')
    reuse['parent_execution_open_manifest']=extension.reference(path);doc['refs'].append(extension.reference(path))
    def call():
        return extension._accepted_closed_vintage_proof(doc,s['delta'],s['report_path'],s['historical'],
            '2026-10-05',s['first_prices'],s['delta']['prices'],{'A'},
            _field_keys=[('A',pd.Timestamp('2026-10-02'),'close')])
    if complete:assert call()['accepted_field_origins'][0]['accepted_report']==extension.reference(s['reports'][0]['report_path'])
    else:
        with pytest.raises(ValueError,match='ORIGIN_PARENT_MISSING'):call()


@pytest.mark.parametrize('field',['open','close','high','low','volume'])
def test_field_origin_same_source_recapture_preserves_each_inherited_field(tmp_path,monkeypatch,field):
    s=field_origin_continuation_case(tmp_path,monkeypatch,same_raw=True,first_field=field)
    result,meta=s['advance']()
    pd.testing.assert_frame_equal(result['prices'].iloc[:2].reset_index(drop=True),s['first_prices'],check_exact=True)
    origins=meta['capture_reuse']['accepted_closed_vintage_continuation']['accepted_field_origins']
    assert any(x['field']==field for origin in origins for x in origin['fields'])



def partial_ancestor_origin_case(tmp_path,monkeypatch,gaps,*,future_tail=False,missing_parent_field=False):
    import copy,json
    s=field_origin_continuation_case(tmp_path,monkeypatch)
    original_ref=extension.reference(s['input_path'])
    parent=json.loads(s['input_path'].read_text(encoding='utf-8'))
    old_price_ref=parent['captured_prices']
    frame=s['old_prices'].copy()
    if missing_parent_field:frame.loc[0,'close']=float('nan')
    if future_tail:
        frame=pd.concat([frame,s['old_prices'].assign(trade_date=pd.Timestamp('2026-10-05'))],ignore_index=True)
    root=tmp_path/'partial_ancestor';root.mkdir()
    path=root/'prices.parquet';frame.to_parquet(path,index=False)
    parent['captured_prices']=extension.reference(path);parent['gaps']=gaps
    parent['capture_reuse']={'inputs_ref':original_ref,'prices_ref':old_price_ref,'known_price_fields_all_exact':True}
    parent['research_input_owner']=s['first_metadata']['research_input_owner']
    parent['refs'].append(parent['research_input_owner'])
    parent['refs'].extend([original_ref,old_price_ref])
    input_path=root/'three_strategy_price_inputs.json';input_path.write_text(json.dumps(parent,sort_keys=True),encoding='utf-8')
    doc=copy.deepcopy(s['first_metadata']);reuse=doc['capture_reuse']
    reuse['inputs_ref']=extension.reference(input_path);reuse['prices_ref']=parent['captured_prices']
    doc['refs'].extend([reuse['inputs_ref'],parent['captured_prices'],*parent['refs']])
    owner=json.loads(Path(doc['research_input_owner']['path']).read_text(encoding='utf-8'))
    owner['performance_period']['end']=parent['end_date']
    owner['source_refs'].extend([reuse['inputs_ref'],parent['captured_prices']])
    owner_path=root/'consuming_manifest.json';owner_path.write_text(json.dumps(owner,sort_keys=True),encoding='utf-8')
    doc['research_input_owner']=extension.reference(owner_path);doc['refs'].append(extension.reference(owner_path))
    original_first=extension.reference(s['first_capture'])
    s['prior']['source_refs']=[ref for ref in s['prior']['source_refs'] if ref!=original_first]
    s['first_capture'],s['first_metadata']=s['persist']({'prices':s['first_prices'],'events':s['events']},doc,'partial_parent_link','2026-10-05')
    s['partial_parent']=parent;s['partial_input_path']=input_path
    return s


def test_field_origin_partial_ancestor_unrelated_gap_preserves_exact_known_fields(tmp_path,monkeypatch):
    s=partial_ancestor_origin_case(tmp_path,monkeypatch,[{'ticker':'B','source_role':'RECENT_EXECUTION_BRIDGE','reason':'MISSING'}])
    result,meta=s['advance']()
    pd.testing.assert_frame_equal(result['prices'].iloc[:2].reset_index(drop=True),s['first_prices'],check_exact=True)
    origin=meta['capture_reuse']['accepted_closed_vintage_continuation']['accepted_field_origins'][0]
    assert origin['accepted_report']==extension.reference(s['reports'][0]['report_path'])


@pytest.mark.parametrize('missing_parent_field',[False,True])
def test_field_origin_partial_ancestor_related_gap_remains_rejected(tmp_path,monkeypatch,missing_parent_field):
    s=partial_ancestor_origin_case(tmp_path,monkeypatch,[{'ticker':'A','reason':'MISSING'}],missing_parent_field=missing_parent_field)
    with pytest.raises(ValueError,match='ORIGIN_PARENT_BINDING_CHANGED'):s['advance']()


@pytest.mark.parametrize('gaps',[[{}],[{'ticker':None}],['B'],{'ticker':'B'},[{'ticker':''}],{},None])
def test_field_origin_partial_ancestor_unknown_gap_scope_remains_rejected(tmp_path,monkeypatch,gaps):
    s=partial_ancestor_origin_case(tmp_path,monkeypatch,gaps)
    with pytest.raises(ValueError,match='ORIGIN_PARENT_BINDING_CHANGED'):s['advance']()


def test_field_origin_unconsumed_parent_tail_does_not_claim_later_closed_origin(tmp_path,monkeypatch):
    s=partial_ancestor_origin_case(tmp_path,monkeypatch,[],future_tail=True)
    s['delta']['prices'].loc[s['delta']['prices'].trade_date.eq(pd.Timestamp('2026-10-05')),'volume']+=1.
    calls=[];read=extension._capture_parquet
    def observe(ref,**kw):
        if ref==s['partial_parent']['captured_prices'] and kw.get('price_keys') is not None:calls.append(kw.copy())
        return read(ref,**kw)
    monkeypatch.setattr(extension,'_capture_parquet',observe)
    result,meta=s['advance']()
    audit=meta['capture_reuse']['accepted_closed_vintage_continuation']
    origins={(x['trade_date'],x['field']):origin for origin in audit['accepted_field_origins'] for x in origin['fields']}
    assert origins['2026-10-02','close']['accepted_report']==extension.reference(s['reports'][0]['report_path'])
    assert origins['2026-10-05','volume']['accepted_report']==extension.reference(s['reports'][1]['report_path'])
    assert calls and all(day<=pd.Timestamp('2026-10-02') for call in calls for ticker,day in call['price_keys'])
    pd.testing.assert_frame_equal(result['prices'].iloc[:2].reset_index(drop=True),s['first_prices'],check_exact=True)


def test_field_origin_only_unconsumed_parent_tail_does_not_read_parent_prices(tmp_path,monkeypatch):
    s=partial_ancestor_origin_case(tmp_path,monkeypatch,[],future_tail=True)
    s['delta']['prices'].loc[s['delta']['prices'].trade_date.eq(pd.Timestamp('2026-10-05')),'volume']+=1.
    read=extension._capture_parquet
    def no_parent(ref,**kw):
        if ref==s['partial_parent']['captured_prices']:raise AssertionError('unconsumed parent tail must not be read')
        return read(ref,**kw)
    monkeypatch.setattr(extension,'_capture_parquet',no_parent)
    audit=extension._accepted_closed_vintage_proof(s['first_metadata'],s['delta'],s['report_path'],s['historical'],
        '2026-10-05',s['first_prices'],s['delta']['prices'],{'A'},
        _field_keys=[('A',pd.Timestamp('2026-10-05'),'volume')],_capture_ref=extension.reference(s['first_capture']))
    assert audit['accepted_field_origins'][0]['accepted_report']==extension.reference(s['reports'][1]['report_path'])


@pytest.mark.parametrize('end',[None,'not-a-date','2026-10-02T00:00:00','2026-1-2'])
def test_field_origin_partial_ancestor_unknown_cutoff_rejected(tmp_path,monkeypatch,end):
    import copy,json
    s=partial_ancestor_origin_case(tmp_path,monkeypatch,[])
    parent=copy.deepcopy(s['partial_parent']);oldref=extension.reference(s['partial_input_path'])
    root=tmp_path/'unknown_parent';root.mkdir();bad_path=root/'three_strategy_price_inputs.json'
    parent['end_date']=end;bad_path.write_text(json.dumps(parent,sort_keys=True),encoding='utf-8')
    doc=copy.deepcopy(s['first_metadata']);doc['capture_reuse']['inputs_ref']=extension.reference(bad_path)
    doc['refs']=[extension.reference(bad_path) if x==oldref else x for x in doc['refs']]
    original_first=extension.reference(s['first_capture'])
    s['prior']['source_refs']=[ref for ref in s['prior']['source_refs'] if ref not in (oldref,original_first)]
    s['persist']({'prices':s['first_prices'],'events':s['events']},doc,'unknown_cutoff','2026-10-05')
    with pytest.raises(ValueError,match='ORIGIN_PARENT_BINDING_CHANGED'):s['advance']()


def test_field_origin_normal_reuse_stops_at_consumed_owner_not_capture_end(tmp_path,monkeypatch):
    import json,copy
    s=partial_ancestor_origin_case(tmp_path,monkeypatch,[],future_tail=True)
    owner_ref=s['first_metadata']['research_input_owner'];owner=json.loads(Path(owner_ref['path']).read_text(encoding='utf-8'))
    owner['performance_period']['end']='2026-10-01'
    path=tmp_path/'short_owner.json';path.write_text(json.dumps(owner,sort_keys=True),encoding='utf-8')
    doc=copy.deepcopy(s['first_metadata']);doc['research_input_owner']=extension.reference(path);doc['refs'].append(extension.reference(path))
    doc['capture_reuse']['accepted_closed_vintage_continuation']['field_differences']=[]
    s['delta']['prices'].loc[s['delta']['prices'].trade_date.eq(pd.Timestamp('2026-10-02')),'close']=9.04
    proof=extension._accepted_closed_vintage_proof(doc,s['delta'],s['report_path'],s['historical'],'2026-10-05',
        s['first_prices'],s['delta']['prices'],{'A'},_field_keys=[('A',pd.Timestamp('2026-10-02'),'close')],_capture_ref=extension.reference(s['first_capture']))
    assert proof['accepted_field_origins'][0]['capture_ref']==extension.reference(s['first_capture'])
    assert proof['accepted_field_origins'][0]['accepted_report']==extension.reference(s['reports'][1]['report_path'])


@pytest.mark.parametrize('fault',['missing','hash','parent','price','policy','cutoff'])
def test_field_origin_normal_reuse_owner_custody_remains_strict(tmp_path,monkeypatch,fault):
    import json,copy
    s=field_origin_continuation_case(tmp_path,monkeypatch);doc=copy.deepcopy(s['first_metadata'])
    owner_ref=doc['research_input_owner'];owner=json.loads(Path(owner_ref['path']).read_text(encoding='utf-8'))
    if fault=='missing':doc.pop('research_input_owner')
    elif fault=='hash':doc['research_input_owner']={**owner_ref,'sha256':'0'*64}
    else:
        if fault=='parent':owner['source_refs']=[x for x in owner['source_refs'] if x!=doc['capture_reuse']['inputs_ref']]
        if fault=='price':owner['source_refs']=[x for x in owner['source_refs'] if x!=doc['capture_reuse']['prices_ref']]
        if fault=='policy':owner['policy_id']='HGB_TOP20_RISK_R1'
        if fault=='cutoff':owner['performance_period']['end']=None
        path=tmp_path/'altered_owner.json';path.write_text(json.dumps(owner,sort_keys=True),encoding='utf-8')
        doc['research_input_owner']=extension.reference(path);doc['refs'].append(extension.reference(path))
    with pytest.raises(ValueError,match='ORIGIN_OWNER|SOURCE_HASH'):
        extension._accepted_closed_vintage_proof(doc,s['delta'],s['report_path'],s['historical'],'2026-10-05',
            s['first_prices'],s['delta']['prices'],{'A'},_field_keys=[('A',pd.Timestamp('2026-10-02'),'close')])


@pytest.mark.parametrize('fault',['event_audit','phase_missing','phase_unbound'])
def test_field_origin_incomplete_whole_open_flag_cannot_skip_consumed_owner(tmp_path,monkeypatch,fault):
    import copy
    s=field_origin_continuation_case(tmp_path,monkeypatch);doc=copy.deepcopy(s['first_metadata'])
    reuse=doc['capture_reuse'];reuse['existing_prices_all_fields_exact']=True
    path=tmp_path/'open_manifest.json';path.write_text('{}',encoding='utf-8')
    reuse['existing_event_audit_exact']=fault!='event_audit'
    if fault!='phase_missing':reuse['parent_execution_open_manifest']=extension.reference(path)
    if fault!='phase_unbound':doc['refs'].append(extension.reference(path))
    doc.pop('research_input_owner')
    with pytest.raises(ValueError,match='ORIGIN_OWNER_UNBOUND'):
        extension._accepted_closed_vintage_proof(doc,s['delta'],s['report_path'],s['historical'],'2026-10-05',
            s['first_prices'],s['delta']['prices'],{'A'},_field_keys=[('A',pd.Timestamp('2026-10-02'),'close')])


@pytest.mark.parametrize('changed_bytes',[False,True])
def test_field_origin_explicit_whole_closed_copy_uses_all_parent_known_fields(tmp_path,monkeypatch,changed_bytes):
    import copy
    s=field_origin_continuation_case(tmp_path,monkeypatch);doc=copy.deepcopy(s['first_metadata'])
    doc['end_date']='2026-10-02';doc['captured_prices']=doc['capture_reuse']['prices_ref']
    doc['capture_reuse']['reused_accepted_closed_capture']=True
    doc.pop('research_input_owner')
    if changed_bytes:doc['captured_prices']={**doc['captured_prices'],'sha256':'0'*64}
    def call():
        return extension._accepted_closed_vintage_proof(doc,s['delta'],s['report_path'],s['historical'],'2026-10-02',
            s['old_prices'],s['delta']['prices'],{'A'},_field_keys=[('A',pd.Timestamp('2026-10-02'),'close')])
    if changed_bytes:
        with pytest.raises(ValueError,match='WHOLE_CAPTURE_CHANGED'):call()
    else:assert call()['accepted_field_origins'][0]['accepted_report']==extension.reference(s['reports'][0]['report_path'])


# Joint old-field vintage and strict qualified candidate suffix scope.
def vintage_with_candidate_suffix_case(tmp_path,monkeypatch):
    import copy
    s=field_origin_continuation_case(tmp_path,monkeypatch)
    day1=s['old_prices'].assign(trade_date=pd.Timestamp('2026-10-01'))
    old=pd.concat([day1,s['first_prices']],ignore_index=True).sort_values('trade_date').reset_index(drop=True)
    s['delta']['prices']=pd.concat([day1,s['delta']['prices']],ignore_index=True)
    doc=copy.deepcopy(s['first_metadata']);doc['end_date']='2026-10-06';doc['refs'].extend(s['delta']['refs'])
    original=extension.reference(s['first_capture']);s['prior']['source_refs']=[r for r in s['prior']['source_refs'] if r!=original]
    s['first_capture'],s['first_metadata']=s['persist']({'prices':old,'events':s['events']},doc,'consumed_other_names_through6','2026-10-06')
    s['first_prices']=old;s['current']('2026-10-07','candidate_suffix_current')
    s['delta']['prices']=pd.concat([s['delta']['prices'],s['old_prices'].assign(trade_date=pd.Timestamp('2026-10-07'))],ignore_index=True)
    return s


def test_vintage_with_candidate_suffix_preserves_old_fields_and_qualifies_new_keys(tmp_path,monkeypatch):
    s=vintage_with_candidate_suffix_case(tmp_path,monkeypatch)
    result,meta=s['advance']();before=s['first_prices'].set_index(['ticker','trade_date']);after=result['prices'].set_index(['ticker','trade_date'])
    pd.testing.assert_frame_equal(before,after.loc[before.index],check_exact=True)
    assert set(after.index)-set(before.index)=={('A',pd.Timestamp('2026-10-06')),('A',pd.Timestamp('2026-10-07'))}
    assert 'accepted_closed_vintage_continuation' in meta['capture_reuse']
    tail=meta['capture_reuse']['qualified_existing_raw_candidate_tails']['ticker_proofs'][0]
    assert tail['existing_current_raw_candidate_tail'] is True
    assert meta['capture_reuse']['model_feature_eligibility_granted'] is False


@pytest.mark.parametrize('fault,reason',[
    ('missing_old','OLD_HISTORY_KEYS_CHANGED'),('interior_key','UNBOUND_OLD_DATE_ADDITION'),
    ('duplicate','DELTA_DATE_KEYS_INVALID'),('noncandidate','UNBOUND_OLD_DATE_ADDITION'),
    ('bad_tail','CANDIDATE_TAIL_VALUES_INVALID')])
def test_vintage_with_candidate_suffix_does_not_hide_invalid_new_or_missing_keys(tmp_path,monkeypatch,fault,reason):
    import json
    s=vintage_with_candidate_suffix_case(tmp_path,monkeypatch);incoming=s['delta']['prices']
    if fault=='missing_old':s['delta']['prices']=incoming.loc[~incoming.trade_date.eq(pd.Timestamp('2026-10-01'))].copy()
    elif fault=='interior_key':s['delta']['prices']=pd.concat([incoming,s['old_prices'].assign(trade_date=pd.Timestamp('2026-10-03'))],ignore_index=True)
    elif fault=='duplicate':s['delta']['prices']=pd.concat([incoming,incoming.loc[incoming.trade_date.eq(pd.Timestamp('2026-10-06'))]],ignore_index=True)
    elif fault=='bad_tail':s['delta']['prices'].loc[incoming.trade_date.eq(pd.Timestamp('2026-10-06')),'volume']=float('nan')
    else:
        path=s['report_path'];oldref=extension.reference(path);doc=json.loads(path.read_text(encoding='utf-8'));doc['ranked_rows']=[];path.write_text(json.dumps(doc,sort_keys=True),encoding='utf-8');newref=extension.reference(path)
        s['delta']['refs']=[newref if r==oldref else r for r in s['delta']['refs']]
    with pytest.raises(ValueError,match=reason):s['advance']()


# Synthetic original catalog-role continuation; never reads actual market inputs.
def unused_catalog_raw_tail_case(tmp_path,monkeypatch):
    s=existing_candidate_tail_case(tmp_path,monkeypatch,indirect_old_raw=True)
    for entry in s['entries']:entry['raw_sources'][-1]['role']='CURRENT_CATALOG_RAW'
    s['save']();return s


def test_unused_catalog_raw_tail_preserves_original_prefix_and_source_identity(tmp_path,monkeypatch):
    s=unused_catalog_raw_tail_case(tmp_path,monkeypatch)
    custody={Path(ref['path']):Path(ref['path']).read_bytes() for ref in s['metadata']['refs']}
    result,meta=s['advance']()
    pd.testing.assert_frame_equal(result['prices'].iloc[[0]].reset_index(drop=True),s['old_prices'],check_exact=True)
    proof=meta['capture_reuse']['qualified_existing_raw_candidate_tails']
    row=proof['ticker_proofs'][0]
    assert row['transitively_bound_unused_old_raw_sources']==[{k:s['entries'][0]['raw_sources'][-1][k] for k in ('path','sha256')}]
    assert row['security_id']=='sid-A' and row['appended_past_dates']==['2026-10-02']
    assert proof['historical_price_revisions_applied'] is False
    assert meta['capture_reuse']['model_feature_eligibility_granted'] is False
    assert all(path.read_bytes()==raw for path,raw in custody.items())
    extension._verify_prior_price_prefix(result['prices'],meta,s['prior'],s['metadata']['captured_prices'])


@pytest.mark.parametrize('fault,reason',[
    ('fresh_catalog','RAW_SOURCE_UNBOUND'),('old_anchor','RAW_SOURCE_UNBOUND'),
    ('unknown_role','RAW_SOURCE_UNBOUND'),('native_role','RAW_SOURCE_UNBOUND'),
    ('not_candidate','UNBOUND_OLD_DATE_ADDITION'),('direct','UNBOUND_OLD_DATE_ADDITION'),
    ('sid','SECURITY_IDENTITY_CHANGED'),('factor','PAST_REHAB_FACTS_CHANGED'),
    ('old_raw_hash','SOURCE_HASH_MISMATCH'),('old_lineage_hash','SOURCE_HASH_MISMATCH')])
def test_unused_catalog_raw_tail_keeps_original_closed_guards(tmp_path,monkeypatch,fault,reason):
    import json
    from scripts.research.a2.portfolio import selected_hgb as selected
    s=unused_catalog_raw_tail_case(tmp_path,monkeypatch)
    if fault=='unknown_role':s['entries'][0]['raw_sources'][-1]['role']='OTHER_RAW'
    elif fault=='native_role':s['entries'][0]['raw_sources'][-1]['role']='NATIVE_MOOMOO_ANCHOR'
    elif fault=='not_candidate':s['reports'][1]['ranked_rows'][0]['rank']=41
    elif fault=='direct':
        s['package']['policy_id']=selected.DIRECT_POLICY
        monkeypatch.setattr(selected,'active_policy',lambda *a:(selected.DIRECT_POLICY,s['report_path']))
    elif fault=='sid':
        f=pd.read_parquet(s['mappings'][1]);f['security_id']='different-SID';f.to_parquet(s['mappings'][1],index=False)
    elif fault=='factor':
        f=pd.read_parquet(s['factors'][1]);f['forward_adj_factorB']+=1.;f.to_parquet(s['factors'][1],index=False)
    s['save']()
    if fault=='fresh_catalog':s['delta']['refs']=[ref for ref in s['delta']['refs'] if ref['path']!=s['entries'][1]['raw_sources'][-1]['path']]
    elif fault=='old_anchor':
        anchor=s['entries'][0]['raw_sources'][0]['path']
        s['metadata']['refs']=[ref for ref in s['metadata']['refs'] if ref['path']!=anchor]
        s['input_path'].write_text(json.dumps(s['metadata']),encoding='utf-8')
        s['prior']['source_refs'][0]=extension.reference(s['input_path'])
        m=Path(s['prior_ref']['path']);m.write_text(json.dumps(s['prior']),encoding='utf-8');s['prior_ref']=extension.reference(m)
    elif fault=='old_raw_hash':Path(s['entries'][0]['raw_sources'][-1]['path']).write_text('altered immutable leaf')
    elif fault=='old_lineage_hash':
        path=Path(s['reports'][0]['report_path']).parent/'input_lineage.json'
        rows=json.loads(path.read_text(encoding='utf-8'));rows[0]['anchor_date']='2020-01-03';path.write_text(json.dumps(rows),encoding='utf-8')
    with pytest.raises(ValueError,match=reason):s['advance']()


# Native schema continuation is limited to already-bound, unused candidate tails.
def native_existing_candidate_tail_case(tmp_path,monkeypatch,*,indirect_old=True):
    import json,copy
    from scripts import daily_recommendation_prices as original
    s=existing_candidate_tail_case(tmp_path,monkeypatch)
    fixed=tmp_path/'native_fixed_authority';fixed.mkdir()
    adapter=fixed/'adapter.py';adapter.write_text('original affine/event adapter',encoding='utf-8')
    coverage=fixed/'coverage.json';coverage.write_text('{}',encoding='utf-8')
    feature=fixed/'feature.py';feature.write_text('original frozen thirty-two features',encoding='utf-8')
    monkeypatch.setattr(original,'ADAPTER_PATH',adapter);monkeypatch.setattr(original,'ADAPTER_SHA',extension.reference(adapter)['sha256'])
    monkeypatch.setattr(original,'COVERAGE_PATH',coverage);monkeypatch.setattr(original,'COVERAGE_SHA',extension.reference(coverage)['sha256'])
    s['native_feature']=feature;s['native_frames']=[];s['native_leafs']=[];s['native_normalized']=[]
    for index,(entry,report,factor) in enumerate(zip(s['entries'],s['reports'],s['factors'])):
        root=Path(report['report_path']).parent
        dates=['2020-01-02','2026-10-01','2026-10-02']+(['2026-10-05'] if index else [])
        frame=pd.DataFrame({'code':'US.A','time_key':dates,'ticker':'A','source':'MOOMOO_OPEND','adjustment':'raw',
                            'open':8.,'close':9.,'high':10.,'low':7.,'volume':100.})
        leaf=root/'native_leaf.parquet';normalized=root/'native_normalized.parquet'
        s['native_frames'].append(frame);s['native_leafs'].append(leaf);s['native_normalized'].append(normalized)
        for key in ('adapter_sha256','coverage_manifest_sha256'):entry.pop(key)
        entry.update(source='MOOMOO_OPEND_RAW_PLUS_REHAB',security_id='sid-A',security_ids=['sid-A'],
            raw_end=report['data_date'],universe_id='synthetic-native-universe',universe_effective_date='2026-09-01',
            membership_validation='CALLER_VERIFIED_CURRENT_PIT_UNIVERSE',observed_target=report['data_date'],
            feature_source={'artifact_id':'source',**extension.reference(feature)},
            rehab={**extension.reference(factor),'kind':'CURRENT_SNAPSHOT','fetched_at':entry['rehab_fetched_at']},
            vintage_semantics='LATER_VENDOR_RETRIEVAL_NOT_HISTORICAL_PUBLICATION_VINTAGE')
    def rewrite_raw(index):
        entry=s['entries'][index];frame=s['native_frames'][index];leaf=s['native_leafs'][index];normalized=s['native_normalized'][index]
        frame.to_parquet(leaf,index=False);leafref=extension.reference(leaf)
        nf=frame.rename(columns={'time_key':'date','code':'provider_code'}).copy();nf['source_id']=leafref['sha256'];nf.to_parquet(normalized,index=False)
        native={**extension.reference(normalized),'raw_inputs':[leafref],'provider':'MOOMOO_OPEND','provider_code':'US.A','adjustment':'RAW'}
        entry['anchor_proof']={'kind':'NEW_13F_MEMBER_NATIVE_RAW_ANCHOR','scope':'2026_INFERENCE_ONLY',
                             'old_frozen_equivalence_claimed':False,'native_source':copy.deepcopy(native)}
        entry['raw_sources']=[{**native,'role':'NATIVE_MOOMOO_ANCHOR'}]
    for index in range(2):rewrite_raw(index)
    save=s['save']
    def native_save():
        save()
        for key,index in (('metadata',0),('delta',1)):
            s[key]['refs'].extend([extension.reference(s['native_leafs'][index]),extension.reference(feature),
                                   extension.reference(adapter),extension.reference(coverage)])
        if indirect_old:s['metadata']['refs']=[r for r in s['metadata']['refs'] if r['path']!=str(s['native_normalized'][0])]
        s['input_path'].write_text(json.dumps(s['metadata']),encoding='utf-8')
        s['prior']['source_refs'][0]=extension.reference(s['input_path']);mp=Path(s['prior_ref']['path'])
        mp.write_text(json.dumps(s['prior']),encoding='utf-8');s['prior_ref']=extension.reference(mp)
    s['save']=native_save;s['rewrite_native_raw']=rewrite_raw;native_save();return s


@pytest.mark.parametrize('indirect_old',[False,True])
def test_native_candidate_tail_reuses_original_native_schema_and_preserves_all_accepted_fields(tmp_path,monkeypatch,indirect_old):
    s=native_existing_candidate_tail_case(tmp_path,monkeypatch,indirect_old=indirect_old)
    custody={Path(r['path']):Path(r['path']).read_bytes() for r in s['metadata']['refs']}
    result,meta=s['advance']()
    pd.testing.assert_frame_equal(result['prices'].iloc[[0]].reset_index(drop=True),s['old_prices'],check_exact=True)
    row=meta['capture_reuse']['qualified_existing_raw_candidate_tails']['ticker_proofs'][0]
    assert row['original_anchor_refs']==[] and row['expanded_adapter_bindings'] is None
    assert row['native_first_raw_bar_exact'] is True and row['old_frozen_equivalence_claimed'] is False
    assert len(row['native_anchor_bindings'])==2 and bool(row['transitively_bound_unused_old_raw_sources'])==indirect_old
    assert row['appended_past_dates']==['2026-10-02']
    assert all(path.read_bytes()==data for path,data in custody.items())
    extension._verify_prior_price_prefix(result['prices'],meta,s['prior'],s['metadata']['captured_prices'])


@pytest.mark.parametrize('fault,reason',[
    ('scope','NATIVE_SCHEMA'),('equivalence','NATIVE_SCHEMA'),('kind','EXPANDED_MANIFEST_UNBOUND'),
    ('missing_native_source','NATIVE_SOURCE_UNBOUND'),('role','EXECUTION_NATIVE_ANCHOR_PROOF_INVALID'),
    ('provider','EXECUTION_NATIVE_ANCHOR_PROOF_INVALID'),('basis','EXECUTION_NATIVE_ANCHOR_PROOF_INVALID'),
    ('normalized_identity','EXECUTION_NATIVE_NORMALIZED_IDENTITY_INVALID'),('leaf_mismatch','EXECUTION_NATIVE_NORMALIZED_LEAF_MISMATCH'),
    ('native_anchor_values','NATIVE_ANCHOR_VALUES_CHANGED'),('anchor_date','ANCHOR_OR_ADAPTER_CHANGED'),
    ('sid','SECURITY_IDENTITY_CHANGED'),('entry_sid','NATIVE_SCHEMA|SECURITY_IDENTITY_CHANGED'),
    ('feature','IMPLEMENTATION_CHANGED'),('feature_hash','SOURCE_HASH_MISMATCH'),
    ('explicit_standard','NATIVE_SCHEMA'),('expanded_manifest','NATIVE_SCHEMA'),
    ('past_rehab','PAST_REHAB_FACTS_CHANGED'),('missing_new_raw','RAW_SOURCE_UNBOUND'),
    ('native_old_source_hash','SOURCE_HASH_MISMATCH'),('missing_old_key','OLD_HISTORY_KEYS_CHANGED'),
    ('duplicate','DELTA_DATE_KEYS_INVALID'),('unknown_current','UNBOUND_OLD_DATE_ADDITION')])
def test_native_candidate_tail_does_not_accept_unproved_or_drifting_native_identity_coordinate_source(tmp_path,monkeypatch,fault,reason):
    import json,copy
    s=native_existing_candidate_tail_case(tmp_path,monkeypatch);entry=s['entries'][1]
    if fault=='scope':entry['anchor_proof']['scope']='HISTORICAL_FROZEN_EQUIVALENCE'
    elif fault=='equivalence':entry['anchor_proof']['old_frozen_equivalence_claimed']=True
    elif fault=='kind':entry['anchor_proof']['kind']='UNKNOWN_NATIVE'
    elif fault=='missing_native_source':entry['anchor_proof'].pop('native_source')
    elif fault=='role':entry['raw_sources'][0]['role']='CURRENT_RAW'
    elif fault in ('provider','basis'):
        key='provider' if fault=='provider' else 'adjustment';value='YAHOO_CHART' if fault=='provider' else 'QFQ'
        entry['anchor_proof']['native_source'][key]=value;entry['raw_sources'][0][key]=value
    elif fault=='normalized_identity':
        path=s['native_normalized'][1];df=pd.read_parquet(path);df['provider_code']='US.B';df.to_parquet(path,index=False)
        ref=extension.reference(path)
        for obj in (entry['anchor_proof']['native_source'],entry['raw_sources'][0]):obj.update(ref)
    elif fault=='leaf_mismatch':
        path=s['native_normalized'][1];df=pd.read_parquet(path);df.loc[0,'close']+=.1;df.to_parquet(path,index=False)
        ref=extension.reference(path)
        for obj in (entry['anchor_proof']['native_source'],entry['raw_sources'][0]):obj.update(ref)
    elif fault=='native_anchor_values':s['native_frames'][1].loc[0,'close']+=.1;s['rewrite_native_raw'](1)
    elif fault=='anchor_date':entry['anchor_date']='2020-01-03'
    elif fault=='sid':
        p=s['mappings'][1];df=pd.read_parquet(p);df['security_id']='sid-B';df.to_parquet(p,index=False)
    elif fault=='entry_sid':entry['security_id']='sid-B';entry['security_ids']=['sid-B']
    elif fault=='feature':
        p=tmp_path/'other_feature.py';p.write_text('same new artifact',encoding='utf-8');entry['feature_source']={'artifact_id':'source',**extension.reference(p)}
    elif fault=='feature_hash':entry['feature_source']['sha256']='0'*64
    elif fault=='explicit_standard':entry['adapter_sha256']='0'*64
    elif fault=='expanded_manifest':entry['expanded_anchor_manifest']={'path':'not-real','sha256':'0'*64}
    elif fault=='past_rehab':
        p=s['factors'][1];df=pd.read_parquet(p);df['forward_adj_factorB']+=.2;df.to_parquet(p,index=False);entry['rehab'].update(extension.reference(p))
    elif fault=='missing_old_key':s['delta']['prices']=s['delta']['prices'].iloc[1:].reset_index(drop=True)
    elif fault=='duplicate':s['delta']['prices']=pd.concat([s['delta']['prices'],s['delta']['prices'].iloc[[1]]],ignore_index=True)
    elif fault=='unknown_current':s['reports'][1]['ranked_rows'][0]['rank']=41
    s['save']()
    if fault=='missing_new_raw':s['delta']['refs']=[r for r in s['delta']['refs'] if r['path']!=str(s['native_normalized'][1])]
    elif fault=='native_old_source_hash':s['native_normalized'][0].write_bytes(b'changed after immutable binding')
    with pytest.raises((ValueError,AssertionError),match=reason):s['advance']()


def test_native_schema_does_not_extend_ordinary_closed_vintage_permission(tmp_path,monkeypatch):
    s=native_existing_candidate_tail_case(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='NATIVE_SCHEMA_OR_SCOPE_UNBOUND'):
        extension._accepted_closed_vintage_proof(s['metadata'],s['delta'],s['report_path'],s['historical'],
            '2026-10-02',s['old_prices'],s['delta']['prices'],{'A'})


@pytest.mark.parametrize('fault',['normalized_future','raw_leaf_future','raw_leaf_invalid_date','missing_raw_leaf_date','union_membership','missing_anchor_row'])
def test_native_candidate_tail_proves_date_and_single_day_identity_before_original_whole_reader(tmp_path,monkeypatch,fault):
    from scripts.research.a2.evaluation import demo_performance_prices as reader
    s=native_existing_candidate_tail_case(tmp_path,monkeypatch);entry=s['entries'][1]
    if fault=='normalized_future':
        s['native_frames'][1].loc[len(s['native_frames'][1])]=s['native_frames'][1].iloc[-1]
        s['native_frames'][1].loc[len(s['native_frames'][1])-1,'time_key']='2027-01-04'
        s['rewrite_native_raw'](1)
    elif fault in ('raw_leaf_future','raw_leaf_invalid_date','missing_raw_leaf_date'):
        p=s['native_leafs'][1];frame=pd.read_parquet(p)
        if fault=='raw_leaf_future':
            frame.loc[len(frame)]=frame.iloc[-1];frame.loc[len(frame)-1,'time_key']='2026-10-06'
        elif fault=='raw_leaf_invalid_date':frame.loc[0,'time_key']='not-a-date'
        else:frame=frame.drop(columns='time_key')
        frame.to_parquet(p,index=False);ref=extension.reference(p)
        nf=pd.read_parquet(s['native_normalized'][1]);nf['source_id']=ref['sha256'];nf.to_parquet(s['native_normalized'][1],index=False)
        for item in (entry['anchor_proof']['native_source'],entry['raw_sources'][0]):
            item.update(extension.reference(s['native_normalized'][1]));item['raw_inputs']=[ref]
    elif fault=='union_membership':entry['membership_validation']='REQUIRES_DOWNSTREAM_DAILY_PIT_JOIN';entry['security_id']=None
    else:
        s['native_frames'][1]=s['native_frames'][1].iloc[1:].reset_index(drop=True);s['rewrite_native_raw'](1)
    s['save']()
    if fault!='missing_anchor_row':
        original=reader._native_anchor
        def qualified(entry,verify):
            if entry['raw_end']=='2026-10-05':pytest.fail('future/unbound new source may not reach the original whole-price reader')
            return original(entry,verify)
        monkeypatch.setattr(reader,'_native_anchor',qualified)
    with pytest.raises(ValueError,match='VINTAGE_NATIVE_'):s['advance']()


@pytest.mark.parametrize('kind',['normalized','raw_parquet','raw_csv'])
def test_native_date_preflight_uses_original_date_priority_before_any_price_read(tmp_path,monkeypatch,kind):
    from scripts.research.a2.evaluation import demo_performance_prices as reader
    s=native_existing_candidate_tail_case(tmp_path,monkeypatch);entry=s['entries'][1]
    normalized=s['native_normalized'][1];nf=pd.read_parquet(normalized)
    if kind=='normalized':
        nf['trade_date']='2026-10-06'  # Lower-priority date remains within report5.
    else:
        leaf=s['native_leafs'][1];df=pd.read_parquet(leaf)
        df['date']=df['time_key'];df['trade_date']='2026-10-06'
        if kind=='raw_csv':leaf=leaf.with_suffix('.csv');df.to_csv(leaf,index=False)
        else:df.to_parquet(leaf,index=False)
        ref=extension.reference(leaf);nf['source_id']=ref['sha256']
        for source in (entry['anchor_proof']['native_source'],entry['raw_sources'][0]):source['raw_inputs']=[ref]
    nf.to_parquet(normalized,index=False);ref=extension.reference(normalized)
    for source in (entry['anchor_proof']['native_source'],entry['raw_sources'][0]):source.update(ref)
    s['save']()
    if kind=='raw_csv':s['delta']['refs'].append(extension.reference(leaf))
    original=reader._native_anchor
    def qualified(item,verify):
        if item['raw_end']=='2026-10-05':pytest.fail('higher-priority future date must reject before whole-price native reader')
        return original(item,verify)
    monkeypatch.setattr(reader,'_native_anchor',qualified)
    with pytest.raises(ValueError,match='VINTAGE_NATIVE_SOURCE_FUTURE_DATE'):s['advance']()


@pytest.mark.parametrize('kind',['normalized','raw_leaf'])
def test_native_date_preflight_does_not_treat_string_footer_bounds_as_time_bounds(tmp_path,monkeypatch,kind):
    from scripts.research.a2.evaluation import demo_performance_prices as reader
    s=native_existing_candidate_tail_case(tmp_path,monkeypatch);entry=s['entries'][1]
    report=s['reports'][1];report['data_date']='2026-12-31'
    entry['raw_end']=entry['observed_target']='2026-12-31'
    normalized=s['native_normalized'][1];nf=pd.read_parquet(normalized)
    dates=['01/02/2026','10/09/2027','12/31/2026','12/31/2026']
    if kind=='normalized':nf['date']=dates
    else:
        leaf=s['native_leafs'][1];df=pd.read_parquet(leaf);df['date']=dates;df.to_parquet(leaf,index=False)
        ref=extension.reference(leaf);nf['source_id']=ref['sha256']
        for source in (entry['anchor_proof']['native_source'],entry['raw_sources'][0]):source['raw_inputs']=[ref]
    nf.to_parquet(normalized,index=False);ref=extension.reference(normalized)
    for source in (entry['anchor_proof']['native_source'],entry['raw_sources'][0]):source.update(ref)
    s['save']()
    original=reader._native_anchor
    def qualified(item,verify):
        if item['raw_end']=='2026-12-31':pytest.fail('lexical 2026 endpoints must not hide 2027 before whole-price reader')
        return original(item,verify)
    monkeypatch.setattr(reader,'_native_anchor',qualified)
    with pytest.raises(ValueError,match='VINTAGE_NATIVE_SOURCE_FUTURE_DATE'):
        extension._accepted_closed_vintage_proof(s['metadata'],s['delta'],s['report_path'],s['historical'],
            '2026-10-02',s['old_prices'],s['delta']['prices'],{'A'},existing_candidate_tail=True)


@pytest.mark.parametrize('kind',['date','timestamp'])
def test_native_candidate_tail_typed_arrow_date_statistics_preserve_original_native_result(tmp_path,monkeypatch,kind):
    s=native_existing_candidate_tail_case(tmp_path,monkeypatch)
    for index,entry in enumerate(s['entries']):
        p=s['native_normalized'][index];df=pd.read_parquet(p);dates=pd.to_datetime(df['date'])
        df['date']=dates.dt.date if kind=='date' else dates;df.to_parquet(p,index=False)
        for source in (entry['anchor_proof']['native_source'],entry['raw_sources'][0]):source.update(extension.reference(p))
    s['save']();result,meta=s['advance']()
    pd.testing.assert_frame_equal(result['prices'].iloc[[0]].reset_index(drop=True),s['old_prices'],check_exact=True)
    assert meta['capture_reuse']['qualified_existing_raw_candidate_tails']['ticker_proofs'][0]['native_first_raw_bar_exact'] is True


# Pure synthetic new-candidate history audit admission; no real source/model IO.
def new_candidate_past_event_case(tmp_path,monkeypatch):
    import json
    from scripts.research.a2.evaluation import demo_performance
    actual_review=demo_performance.reviewed_events
    s=pending_new_ticker_scope_case(tmp_path,monkeypatch)
    old=pd.DataFrame([{'ticker':'REVIEW_ONLY','code':'US.REVIEW_ONLY','event_date':pd.Timestamp('2025-01-02'),
        'audit_kind':'LARGE_RAW_MOVE_NO_VENDOR_EVENT','raw_jump':1.25}])
    old.to_parquet(s['events_path'],index=False);s['events']=old
    event={'ticker':'A','code':'US.A','event_date':pd.Timestamp('2026-10-01'),
        'audit_kind':'LARGE_RAW_MOVE_NO_VENDOR_EVENT','raw_jump':1.5,'source_event_date':pd.NaT,
        'aligned_to_next_session':False,'factor_a':float('nan'),'factor_b':float('nan'),
        'share_event':False,'manual_wolf':False}
    s['delta']['events']=pd.concat([old,pd.DataFrame([event])],ignore_index=True)
    review=tmp_path/'candidate_event_review.json'
    review.write_text(json.dumps({'schema':'A2_EXECUTION_EVENT_REVIEW_V1',
        'policy':demo_performance.EVENT_REVIEW_POLICY,'records':[{'ticker':'REVIEW_ONLY','code':'US.REVIEW_ONLY',
        'event_date':'2025-01-02','audit_kind':'LARGE_RAW_MOVE_NO_VENDOR_EVENT','raw_jump':1.25,
        'status':'RESOLVED_NON_CORPORATE_ACTION'}]}),encoding='utf-8')
    ref=extension.reference(review);s['metadata']['event_review']=ref;s['delta']['event_review']=ref
    save=s['save']
    def persist(targets=None):
        save()
        s['metadata']['refs'].append(ref);s['delta']['refs'].append(ref)
        s['input_path'].write_text(json.dumps(s['metadata']),encoding='utf-8')
        s['prior']['source_refs']=[extension.reference(s['input_path']),s['metadata']['captured_prices'],s['metadata']['events']]
        if targets is not None:s['prior']['strategies']['HGB']['targets']=targets
        path=Path(s['prior_ref']['path']);path.write_text(json.dumps(s['prior']),encoding='utf-8')
        s['prior_ref']=extension.reference(path)
    persist();s.update(persist_event=persist,event=event,review_path=review,review_ref=ref,actual_review=actual_review)
    monkeypatch.setattr(demo_performance,'reviewed_events',actual_review)
    return s


def test_new_candidate_past_event_admits_qualified_history_preserving_review_and_old_prefix(tmp_path,monkeypatch):
    s=new_candidate_past_event_case(tmp_path,monkeypatch)
    custody={Path(ref['path']):Path(ref['path']).read_bytes() for ref in s['metadata']['refs']}
    old=s['old_prices'].copy();old_events=s['events'].copy()
    result,meta=s['advance']()
    pd.testing.assert_frame_equal(result['prices'].loc[result['prices'].ticker.eq('PRIOR_ONLY')].reset_index(drop=True),old,check_exact=True)
    pd.testing.assert_frame_equal(result['events'].loc[result['events'].ticker.eq('REVIEW_ONLY'),old_events.columns].reset_index(drop=True),old_events,check_dtype=False,check_exact=True)
    resolved,audit=s['actual_review'](result['events'],meta['event_review'],meta['refs'])
    assert resolved=={('REVIEW_ONLY',pd.Timestamp('2025-01-02'))}
    assert audit.loc[audit.ticker.eq('A'),'resolution_status'].tolist()==['UNREVIEWED']
    assert meta['capture_reuse']['new_qualified_raw_candidate_event_history']==[
        {'ticker':'A','event_date':'2026-10-01','audit_kind':'LARGE_RAW_MOVE_NO_VENDOR_EVENT','code':'US.A','resolution_status':'UNREVIEWED'}]
    assert meta['capture_reuse']['model_feature_eligibility_granted'] is False
    assert all(path.read_bytes()==before for path,before in custody.items())


@pytest.mark.parametrize('fault',[
    'old_ticker','old_event_ticker','noncandidate','consumed_positive','other_kind','missing_price_date',
    'duplicate_key','empty_code','wrong_code','nonfinite_jump','small_jump','source_date','factor','aligned','share','manual',
    'missing_schema','changed_old_fact','empty_review','review_unbound','wrong_review'])
def test_new_candidate_past_event_rejects_old_economic_facts_and_unbound_audits(tmp_path,monkeypatch,fault):
    import json
    s=new_candidate_past_event_case(tmp_path,monkeypatch)
    new=s['delta']['events'].ticker.eq('A')
    if fault=='old_ticker':s['delta']['events'].loc[new,'ticker']='PRIOR_ONLY'
    elif fault=='old_event_ticker':
        old=s['events'].copy();old['ticker']='A';old.to_parquet(s['events_path'],index=False);s['persist_event']()
    elif fault=='noncandidate':s['snapshots'].clear()
    elif fault=='consumed_positive':s['persist_event']([{'signal_date':'2026-09-30','rows':[{'ticker':'A','target_weight':.05}]}])
    elif fault=='other_kind':s['delta']['events'].loc[new,'audit_kind']='APPLIED_CORPORATE_ACTION'
    elif fault=='missing_price_date':s['delta']['events'].loc[new,'event_date']=pd.Timestamp('2026-09-30')
    elif fault=='duplicate_key':s['delta']['events']=pd.concat([s['delta']['events'],s['delta']['events'].loc[new]],ignore_index=True)
    elif fault=='empty_code':s['delta']['events'].loc[new,'code']=''
    elif fault=='wrong_code':s['delta']['events'].loc[new,'code']='US.OTHER'
    elif fault=='nonfinite_jump':s['delta']['events'].loc[new,'raw_jump']=float('inf')
    elif fault=='small_jump':s['delta']['events'].loc[new,'raw_jump']=.79
    elif fault=='source_date':s['delta']['events'].loc[new,'source_event_date']=pd.Timestamp('2026-10-01')
    elif fault=='factor':s['delta']['events'].loc[new,'factor_a']=2.
    elif fault=='aligned':s['delta']['events'].loc[new,'aligned_to_next_session']=True
    elif fault=='share':s['delta']['events'].loc[new,'share_event']=True
    elif fault=='manual':s['delta']['events'].loc[new,'manual_wolf']=True
    elif fault=='missing_schema':s['delta']['events']=s['delta']['events'].drop(columns='share_event')
    elif fault=='changed_old_fact':s['delta']['events'].loc[~new,'raw_jump']=1.3
    elif fault=='empty_review':
        doc=json.loads(s['review_path'].read_text());doc['records']=[];s['review_path'].write_text(json.dumps(doc));ref=extension.reference(s['review_path'])
        s['metadata']['event_review']=ref;s['delta']['event_review']=ref;s['review_ref'].update(ref);s['persist_event']()
    elif fault=='review_unbound':s['delta']['event_review']=None
    elif fault=='wrong_review':
        doc=json.loads(s['review_path'].read_text());doc['policy']='OTHER';s['review_path'].write_text(json.dumps(doc));ref=extension.reference(s['review_path'])
        s['metadata']['event_review']=ref;s['delta']['event_review']=ref;s['review_ref'].update(ref);s['persist_event']()
    with pytest.raises((ValueError,AssertionError),match='PAST_EVENT|NEW_EVENTS_UNREVIEWED|EVENT_BINDING_CHANGED|EVENT_REVIEW_POLICY_MISMATCH|UNBOUND_OLD_DATE_ADDITION|EVENT_REVIEW_IDENTITY_CHANGED'):
        s['advance']()


@pytest.mark.parametrize('weight',[0.,-.05])
def test_new_candidate_past_event_zero_or_negative_old_target_is_not_positive_touch(tmp_path,monkeypatch,weight):
    s=new_candidate_past_event_case(tmp_path,monkeypatch)
    s['persist_event']([{'signal_date':'2026-09-30','rows':[{'ticker':'A','target_weight':weight}]}])
    result,meta=s['advance']()
    assert len(meta['capture_reuse']['new_qualified_raw_candidate_event_history'])==1


def test_new_candidate_past_event_keeps_original_held_unresolved_gate(tmp_path,monkeypatch):
    s=new_candidate_past_event_case(tmp_path,monkeypatch);result,meta=s['advance']()
    _,audit=s['actual_review'](result['events'],meta['event_review'],meta['refs'])
    signal,execution=pd.Timestamp('2026-09-30'),pd.Timestamp('2026-10-01')
    unresolved=audit.loc[audit.resolution_status.eq('UNREVIEWED')]
    runtime={'unresolved_events':set(zip(pd.to_datetime(unresolved.event_date),unresolved.ticker))}
    panel=pd.DataFrame({'signal_date':[signal],'ticker':['A'],'raw_rank':[1]})
    prices=pd.DataFrame({'trade_date':[signal,execution],'ticker':['A','A']})
    def held(name,callback,*args):callback(signal,{'A':1.},{'A':.1},1.)
    with pytest.raises(extension.HeldEventUnresolved):extension.replay_common(held,'RAW',None,panel,prices,runtime,[(signal,execution)])
    def empty(name,callback,*args):assert callback(signal,{},{},1.)=={'A':.05};return 'qualified'
    value,_=extension.replay_common(empty,'RAW',None,panel,prices,runtime,[(signal,execution)])
    assert value=='qualified'


def vendor_candidate_past_event_case(tmp_path,monkeypatch,aligned=False):
    s=new_candidate_past_event_case(tmp_path,monkeypatch)
    mask=s['delta']['events'].ticker.eq('A')
    s['delta']['events'].loc[mask,'audit_kind']='APPLIED_CORPORATE_ACTION'
    s['delta']['events'].loc[mask,'raw_jump']=float('nan')
    s['delta']['events'].loc[mask,'factor_a']=.9647
    s['delta']['events'].loc[mask,'factor_b']=0.
    s['delta']['events'].loc[mask,'source_event_date']=pd.Timestamp('2026-09-30' if aligned else '2026-10-01')
    s['delta']['events'].loc[mask,'aligned_to_next_session']=aligned
    return s


@pytest.mark.parametrize('aligned,beta',[(False,0.),(True,0.),(False,-.35)])
def test_vendor_candidate_past_event_keeps_old_facts_and_original_review(tmp_path,monkeypatch,aligned,beta):
    s=vendor_candidate_past_event_case(tmp_path,monkeypatch,aligned)
    mask=s['delta']['events'].ticker.eq('A');s['delta']['events'].loc[mask,'factor_b']=beta
    custody={Path(ref['path']):Path(ref['path']).read_bytes() for ref in s['metadata']['refs']}
    result,meta=s['advance']()
    pd.testing.assert_frame_equal(result['prices'].loc[result['prices'].ticker.eq('PRIOR_ONLY')].reset_index(drop=True),s['old_prices'],check_exact=True)
    old=s['events']
    pd.testing.assert_frame_equal(result['events'].loc[result['events'].ticker.eq('REVIEW_ONLY'),old.columns].reset_index(drop=True),old,check_dtype=False,check_exact=True)
    event=result['events'].loc[result['events'].ticker.eq('A')].iloc[0]
    assert event.audit_kind=='APPLIED_CORPORATE_ACTION'
    assert event.factor_a==.9647 and event.factor_b==beta
    assert bool(event.aligned_to_next_session)==aligned and not event.share_event
    resolved,audit=s['actual_review'](result['events'],meta['event_review'],meta['refs'])
    assert resolved=={('REVIEW_ONLY',pd.Timestamp('2025-01-02'))}
    assert audit.loc[audit.ticker.eq('A'),'resolution_status'].tolist()==['UNREVIEWED']
    assert meta['capture_reuse']['model_feature_eligibility_granted'] is False
    assert all(path.read_bytes()==before for path,before in custody.items())


@pytest.mark.parametrize('fault',[
    'consumed_positive','old_ticker','old_event_ticker','noncandidate','no_price_key',
    'wrong_code','unbound_code','missing_factor','zero_factor','nonfinite_factor','nonfinite_beta',
    'missing_source_date','future_source_date','alignment_without_shift','shift_without_alignment',
    'raw_jump','share','manual','duplicate','wrong_review','changed_old_fact'])
def test_vendor_candidate_past_event_refuses_unsafe_or_unqualified_history(tmp_path,monkeypatch,fault):
    s=vendor_candidate_past_event_case(tmp_path,monkeypatch)
    mask=s['delta']['events'].ticker.eq('A')
    if fault=='consumed_positive':s['persist_event']([{'signal_date':'2026-09-30','rows':[{'ticker':'A','target_weight':.05}]}])
    elif fault=='old_ticker':s['delta']['events'].loc[mask,'ticker']='PRIOR_ONLY'
    elif fault=='old_event_ticker':
        old=s['events'].copy();old['ticker']='A';old.to_parquet(s['events_path'],index=False);s['persist_event']()
    elif fault=='noncandidate':s['snapshots'].clear()
    elif fault=='no_price_key':s['delta']['events'].loc[mask,'event_date']=pd.Timestamp('2026-09-30')
    elif fault=='wrong_code':s['delta']['events'].loc[mask,'code']='US.OTHER'
    elif fault=='unbound_code':
        for snapshot in s['snapshots'].values():
            for row in snapshot['report_binding']['raw_top40']:
                row.pop('security_id',None)
    elif fault=='missing_factor':s['delta']['events'].loc[mask,'factor_a']=float('nan')
    elif fault=='zero_factor':s['delta']['events'].loc[mask,'factor_a']=0.
    elif fault=='nonfinite_factor':s['delta']['events'].loc[mask,'factor_a']=float('inf')
    elif fault=='nonfinite_beta':s['delta']['events'].loc[mask,'factor_b']=float('inf')
    elif fault=='missing_source_date':s['delta']['events'].loc[mask,'source_event_date']=pd.NaT
    elif fault=='future_source_date':s['delta']['events'].loc[mask,'source_event_date']=pd.Timestamp('2026-10-02')
    elif fault=='alignment_without_shift':s['delta']['events'].loc[mask,'aligned_to_next_session']=True
    elif fault=='shift_without_alignment':s['delta']['events'].loc[mask,'source_event_date']=pd.Timestamp('2026-09-30')
    elif fault=='raw_jump':s['delta']['events'].loc[mask,'raw_jump']=1.5
    elif fault=='share':s['delta']['events'].loc[mask,'share_event']=True
    elif fault=='manual':s['delta']['events'].loc[mask,'manual_wolf']=True
    elif fault=='duplicate':s['delta']['events']=pd.concat([s['delta']['events'],s['delta']['events'].loc[mask]],ignore_index=True)
    elif fault=='wrong_review':
        import json
        doc=json.loads(s['review_path'].read_text());doc['policy']='OTHER';s['review_path'].write_text(json.dumps(doc))
        ref=extension.reference(s['review_path']);s['metadata']['event_review']=ref;s['delta']['event_review']=ref;s['review_ref'].update(ref);s['persist_event']()
    elif fault=='changed_old_fact':s['delta']['events'].loc[~mask,'raw_jump']=1.3
    with pytest.raises((ValueError,AssertionError,KeyError),match='PAST_EVENT|NEW_EVENTS_UNREVIEWED|EVENT_BINDING_CHANGED|EVENT_REVIEW_POLICY_MISMATCH|UNBOUND_OLD_DATE_ADDITION|EVENT_REVIEW_IDENTITY_CHANGED'):
        s['advance']()


_CA_ORIGIN_CLOCK_COLUMNS = (
    'ex_div_date', 'split_base', 'split_ert', 'join_base', 'join_ert',
    'split_ratio', 'per_cash_div', 'special_dividend', 'bonus_base',
    'bonus_ert', 'per_share_div_ratio', 'transfer_base', 'transfer_ert',
    'per_share_trans_ratio', 'allot_base', 'allot_ert', 'allotment_ratio',
    'allotment_price', 'add_base', 'add_ert', 'stk_spo_ratio', 'stk_spo_price',
    'spin_off_base', 'spin_off_ert', 'spin_off_ratio', 'forward_adj_factorA',
    'forward_adj_factorB', 'backward_adj_factorA', 'backward_adj_factorB', 'code',
)


def origin_clock_vintage_case(tmp_path, monkeypatch, origin='2026-10-08',
                              *, outer_end='2026-10-12'):
    state = accepted_closed_vintage_case(tmp_path, monkeypatch)
    state['metadata']['end_date'] = origin
    state['reports'][0]['data_date'] = origin
    state['reports'][1]['data_date'] = '2026-10-13'
    for report, entry in zip(state['reports'], state['entries']):
        entry['rehab_fetched_at'] = report['data_date'] + 'T21:00:00+00:00'
    past = {name: 0.0 for name in _CA_ORIGIN_CLOCK_COLUMNS
            if name not in {'code', 'ex_div_date'}}
    past.update(code='US.A', ex_div_date=pd.Timestamp('2025-01-02'),
                forward_adj_factorA=1.0, forward_adj_factorB=0.2,
                split_ratio=1.0, backward_adj_factorA=1.0)
    for factor in state['factors']:
        pd.DataFrame([past], columns=_CA_ORIGIN_CLOCK_COLUMNS).to_parquet(
            factor, index=False)
    state['save']()

    def prove():
        incoming = state['delta']['prices'].loc[
            state['delta']['prices'].trade_date.isin(state['old_prices'].trade_date)]
        return extension._accepted_closed_vintage_proof(
            state['metadata'], state['delta'], state['report_path'],
            state['historical'], outer_end, state['old_prices'], incoming, {'A'})
    state['prove'] = prove
    return state


def origin_clock_factor_event(state, *, accepted_future=False):
    for index, factor in enumerate(state['factors']):
        frame = pd.read_parquet(factor)
        if index == 0 and not accepted_future:
            continue
        future = frame.iloc[[0]].copy()
        future['ex_div_date'] = pd.Timestamp('2026-10-09')
        future['per_cash_div'] = 0.06
        future['forward_adj_factorA'] = 1.0 if index == 0 else 0.99978
        future['forward_adj_factorB'] = -0.06 if index == 0 else 0.0
        pd.concat([frame, future], ignore_index=True).to_parquet(factor, index=False)
    state['save']()


@pytest.mark.parametrize('accepted_future', [False, True])
def test_origin_clock_future_event_addition_and_maturity_preserve_prior_facts(
        tmp_path, monkeypatch, accepted_future):
    state = origin_clock_vintage_case(tmp_path, monkeypatch)
    origin_clock_factor_event(state, accepted_future=accepted_future)
    custody = {factor: factor.read_bytes() for factor in state['factors']}
    original_read = extension._capture_parquet
    stops = []

    def read(ref, **kwargs):
        if Path(ref['path']) in state['factors']:
            stops.append(kwargs['stop'])
        return original_read(ref, **kwargs)
    monkeypatch.setattr(extension, '_capture_parquet', read)
    proof = state['prove']()
    assert proof['ticker_proofs'][0]['past_factor_stream_exact'] is True
    assert proof['through'] == '2026-10-12'
    ticker = proof['ticker_proofs'][0]
    assert (ticker['origin_end'], ticker['prior_consumed_end'], ticker['rehab_facts_through']) == (
        '2026-10-08', '2026-10-12', '2026-10-08')
    assert stops == [pd.Timestamp('2026-10-09'), pd.Timestamp('2026-10-09')]
    assert all(factor.read_bytes() == data for factor, data in custody.items())


@pytest.mark.parametrize('origin', ['2026-10-09', '2026-10-12'])
@pytest.mark.parametrize('accepted_future', [False, True])
def test_origin_clock_event_at_or_before_origin_remains_rejected(
        tmp_path, monkeypatch, origin, accepted_future):
    state = origin_clock_vintage_case(tmp_path, monkeypatch, origin)
    origin_clock_factor_event(state, accepted_future=accepted_future)
    with pytest.raises(ValueError, match='VINTAGE_PAST_REHAB_FACTS_CHANGED:A'):
        state['prove']()


@pytest.mark.parametrize('field', _CA_ORIGIN_CLOCK_COLUMNS)
def test_origin_clock_any_past_company_action_field_change_remains_rejected(
        tmp_path, monkeypatch, field):
    state = origin_clock_vintage_case(tmp_path, monkeypatch)
    frame = pd.read_parquet(state['factors'][1])
    if field == 'code':
        frame[field] = 'US.OTHER'
    elif field == 'ex_div_date':
        frame[field] += pd.Timedelta(days=1)
    else:
        frame[field] += 0.01
    frame.to_parquet(state['factors'][1], index=False)
    state['save']()
    with pytest.raises(ValueError, match='VINTAGE_PAST_REHAB_FACTS_CHANGED:A|VINTAGE_REHAB_CODE_CHANGED'):
        state['prove']()


@pytest.mark.parametrize('origin', [None, '', '2026-02-30', '2026-10-08T00:00:00Z', True])
def test_origin_clock_missing_or_illegal_date_fails_closed(tmp_path, monkeypatch, origin):
    state = origin_clock_vintage_case(tmp_path, monkeypatch)
    state['metadata']['end_date'] = origin
    with pytest.raises(ValueError, match='VINTAGE_ORIGIN_CLOCK_INVALID'):
        state['prove']()


@pytest.mark.parametrize('report_date', [None, '2026-02-30', '2026-10-09'])
def test_origin_clock_verified_report_reader_date_must_match_bound_origin(
        tmp_path, monkeypatch, report_date):
    from scripts.research.a2.evaluation import demo_performance_prices as reader
    state = origin_clock_vintage_case(tmp_path, monkeypatch)
    original = reader._current_entries

    def entries(path, *args):
        rows, report = original(path, *args)
        if Path(path) == Path(state['reports'][0]['report_path']):
            report = {**report, 'data_date': report_date}
        return rows, report
    monkeypatch.setattr(reader, '_current_entries', entries)
    reason = 'VINTAGE_ORIGIN_CLOCK_UNBOUND' if report_date == '2026-10-09' else 'VINTAGE_ORIGIN_CLOCK_INVALID'
    with pytest.raises(ValueError, match=reason):
        state['prove']()


def test_origin_clock_source_date_without_unique_bound_report_rejected(tmp_path, monkeypatch):
    state = origin_clock_vintage_case(tmp_path, monkeypatch)
    state['metadata']['end_date'] = '2026-10-07'
    with pytest.raises(ValueError, match='VINTAGE_PRIOR_REPORT_AMBIGUOUS'):
        state['prove']()


def test_origin_clock_outer_consumed_end_still_limits_unconsumed_capture_tail(tmp_path, monkeypatch):
    state = origin_clock_vintage_case(tmp_path, monkeypatch, '2026-10-12',
                                     outer_end='2026-10-08')
    origin_clock_factor_event(state, accepted_future=True)
    proof = state['prove']()
    ticker = proof['ticker_proofs'][0]
    assert ticker['past_factor_stream_exact'] is True
    assert proof['through'] == '2026-10-08'
    assert (ticker['origin_end'], ticker['prior_consumed_end'], ticker['rehab_facts_through']) == (
        '2026-10-12', '2026-10-08', '2026-10-08')
