"""Synthetic source binding and the unchanged execution bridge stopping gates."""
import copy
import importlib.util
import json
from pathlib import Path
import socket

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[4]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


module = load("current_execution_recovery_test", ROOT / "scripts/research/a2/evaluation/demo_performance_prices.py")
shared = load("current_execution_recovery_shared", ROOT / "tests/research/a2/evaluation/test_demo_performance_prices.py")


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("No provider calls"))
    monkeypatch.setattr(module, "original", shared.fixtures.prices)
    monkeypatch.setattr(module, "EXECUTION_BRIDGE_TICKERS", frozenset({"AAPL", "SFIX"}))
    monkeypatch.setattr(module, "RECENT_EXECUTION_BRIDGE_TICKERS", frozenset({"AAPL", "SFIX"}))
    kwargs, record, native = shared.fixtures.massive_fixture(tmp_path, monkeypatch)
    coverage = tmp_path / "backtests/research/a2/demo_2026_calendar_replay/input_coverage.json"
    coverage.parent.mkdir(parents=True)
    coverage.write_bytes(Path(kwargs["coverage_reference"]["path"]).read_bytes())
    monkeypatch.setattr(module.original, "COVERAGE_SHA", module.original.digest(coverage))
    entry = {"ticker": "AAPL", "code": "US.AAPL", "anchor_date": "2026-01-02",
        "raw_end": native.trade_date.max().date().isoformat(), "price_basis": "PIT_FORWARD_REHAB_INDEX",
        "raw_sources": [{"path": str(tmp_path / "original.parquet"),
            "sha256": module.original.digest(tmp_path / "original.parquet"), "role": "ORIGINAL_ANCHOR"}],
        "rehab": {**kwargs["rehab_receipt"]["results"][0], "kind": "CURRENT_SNAPSHOT"}}
    inputs_path = tmp_path / "historical_prices.json"
    inputs_path.write_text(json.dumps({"lineage": [entry]}))
    historical_path = tmp_path / "historical.json"
    historical_path.write_text(json.dumps({"schema_version": 1, "status": "PARTIAL", "run_id": "synthetic",
        "report_path": str(historical_path), "start_date": "2026-01-02", "end_date": entry["raw_end"],
        "price_manifest": {"path": str(inputs_path), "sha256": module.original.digest(inputs_path)}}))
    current_dir = tmp_path / "current"
    current_dir.mkdir()
    (current_dir / "input_lineage.json").write_text("[]")
    (current_dir / "rehab_receipt.json").write_text(json.dumps(kwargs["rehab_receipt"]))
    current_path = current_dir / "recommendation_source.json"
    current_path.write_text(json.dumps({"status": "READY", "model_id": module.MODEL_ID,
        "model_sha256": module.MODEL_SHA256, "report_path": str(current_path), "data_date": kwargs["target"],
        "input_manifest_sha256": module.hashlib.sha256(json.dumps([], sort_keys=True).encode()).hexdigest()}))
    acquisition = tmp_path / "acquisition_manifest.json"
    acquisition.write_text('{"summary":{"status":"COMPLETE"}}')
    recovery_path = tmp_path / "recovery.json"
    value = {"schema": "A2_CURRENT_EXECUTION_PRICE_RECORDS_V1", "gate": module.EXECUTION_GATE,
        "target_date": kwargs["target"], "model_feature_eligibility_granted": False,
        "historical_manifest": {"path": str(historical_path), "sha256": module.original.digest(historical_path)},
        "current_report": {"path": str(current_path), "sha256": module.original.digest(current_path)},
        "acquisition_manifest": {"path": str(acquisition), "sha256": module.original.digest(acquisition)},
        "catalog_records": [record]}
    recovery_path.write_text(json.dumps(value))
    stale = copy.deepcopy(record)
    stale_path = tmp_path / "stale_massive.parquet"
    pd.read_parquet(record["path"]).iloc[:-1].to_parquet(stale_path, index=False)
    stale.update(path=str(stale_path), source_sha256=module.original.digest(stale_path), max_date=entry["raw_end"])
    catalog_calls = []

    class Store:
        def metadata(self, *a, **k):
            catalog_calls.append(a)
            return stale

        def resolve_price_inputs(self, row, **kwargs):
            return row["lineage"]["inputs"]

    from scripts.research.a2.inference import historical_top40_prices
    monkeypatch.setattr(historical_top40_prices, "_store", lambda _: Store())
    # Ensure an execution record creates a reader even if all historical prices
    # are native and no historical/current row already has a bridge.
    paths = shared.SimpleNamespace(backtest_root=tmp_path / "backtests", daily_root=tmp_path / "daily")
    return {"paths": paths, "historical": historical_path, "current": current_path,
        "manifest": recovery_path, "value": value, "entry": entry, "kwargs": kwargs,
        "record": record, "catalog_calls": catalog_calls, "acquisition": acquisition}


def read_recovery(value, *, use=True):
    return module.load_execution_prices(value["paths"], value["historical"], tickers=["AAPL"],
        current_report_path=value["current"],
        **({"current_execution_manifest_path": value["manifest"]} if use else {}))


def test_bound_cache_record_extends_one_real_open_and_preserves_all_prefix_fields(recovery):
    actual = read_recovery(recovery)
    assert not recovery["catalog_calls"] and not actual["gaps"]
    assert actual["prices"].trade_date.max() == pd.Timestamp(recovery["kwargs"]["target"])
    assert actual["prices"].open.iloc[0] == 100.
    assert actual["prices"].open.iloc[1:].eq(101).all()
    assert len(actual["execution_bridges"]) == 1
    assert actual["execution_bridges"][0]["model_feature_eligibility_granted"] is False
    assert str(recovery["manifest"]) in {ref["path"] for ref in actual["refs"]}
    assert actual["event_review"] is None  # The existing supplement authority is unchanged.
    old = module._adjust(recovery["entry"], module.original._adapter(recovery["kwargs"]["target"]),
        {"event_date": "2025-09-29", "quantity_multiplier": .008352}, module.original.verify, {}, None, {})[0]
    pd.testing.assert_frame_equal(actual["prices"].iloc[:-1][module.PRICE_COLUMNS].reset_index(drop=True),
                                  old[module.PRICE_COLUMNS].reset_index(drop=True))


def test_no_manifest_keeps_old_catalog_missing_target_as_visible_gap(recovery):
    actual = read_recovery(recovery, use=False)
    assert recovery["catalog_calls"]
    assert actual["prices"].trade_date.max() == pd.Timestamp(recovery["entry"]["raw_end"])
    assert any("TARGET_SESSION_UNAVAILABLE" in gap["reason"] for gap in actual["gaps"])


@pytest.mark.parametrize("change", ["history", "current", "date", "gate", "eligibility", "duplicate", "ticker", "record_type", "record_hash", "acquisition_hash"])
def test_manifest_cannot_escape_bound_day_source_or_execution_identity(recovery, change):
    value = recovery["value"]
    if change in {"history", "current"}:
        value["historical_manifest" if change == "history" else "current_report"]["sha256"] = "0" * 64
    elif change == "date": value["target_date"] = "2027-01-01"
    elif change == "gate": value["gate"] = "WEAKENED"
    elif change == "eligibility": value["model_feature_eligibility_granted"] = True
    elif change == "duplicate": value["catalog_records"].append(copy.deepcopy(value["catalog_records"][0]))
    elif change == "ticker": value["catalog_records"][0]["ticker"] = "UNKNOWN"
    elif change == "record_type": value["catalog_records"][0] = "UNTRUSTED"
    elif change == "record_hash": Path(value["catalog_records"][0]["path"]).write_bytes(b"changed")
    else: recovery["acquisition"].write_text("changed")
    recovery["manifest"].write_text(json.dumps(value))
    with pytest.raises(ValueError):
        read_recovery(recovery)


@pytest.mark.parametrize("change,reason", [("rehab_time", "PREDATES_CLOSE"),
    ("rehab_code", "CODE_MISMATCH"), ("affine_prefix", "ADJUSTED_PREFIX_CHANGED"),
    ("checkpoint", "CHECKPOINT"), ("ohlc", "RECENT_OHLC_MISMATCH")])
def test_existing_rehab_checkpoint_ohlc_and_prefix_gates_still_block(recovery, change, reason):
    receipt_path = recovery["current"].parent / "rehab_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    factor = receipt["results"][0]
    if change == "rehab_time":
        factor["fetched_at"] = recovery["kwargs"]["target"] + "T19:59:59Z"
    elif change in {"rehab_code", "affine_prefix"}:
        path = receipt_path.with_name("fresh_changed_factor.parquet")
        frame = pd.read_parquet(factor["path"])
        if change == "rehab_code": frame["code"] = "US.OTHER"
        else: frame["forward_adj_factorB"] = -2.
        frame.to_parquet(path, index=False)
        factor.update(path=str(path), sha256=module.original.digest(path))
    elif change == "checkpoint":
        cp = Path(recovery["record"]["lineage"]["inputs"][-1]["path"]).parent / "checkpoint.json"
        value = json.loads(cp.read_text()); value["contract"]["params"]["adjusted"] = "true"
        cp.write_text(json.dumps(value))
    else:
        native_path = Path(recovery["entry"]["raw_sources"][0]["path"])
        raw = pd.read_parquet(native_path); raw.loc[raw.index[-1], "open"] = 99.
        raw.to_parquet(native_path, index=False)
        recovery["entry"]["raw_sources"][0]["sha256"] = module.original.digest(native_path)
        historical = json.loads(recovery["historical"].read_text())
        inputs = Path(historical["price_manifest"]["path"])
        inputs.write_text(json.dumps({"lineage": [recovery["entry"]]}))
        historical["price_manifest"]["sha256"] = module.original.digest(inputs)
        recovery["historical"].write_text(json.dumps(historical))
        recovery["value"]["historical_manifest"]["sha256"] = module.original.digest(recovery["historical"])
        recovery["manifest"].write_text(json.dumps(recovery["value"]))
    receipt_path.write_text(json.dumps(receipt))
    actual = read_recovery(recovery)
    assert actual["prices"].trade_date.max() == pd.Timestamp(recovery["entry"]["raw_end"])
    assert not actual["execution_bridges"]
    assert any(reason in gap["reason"] for gap in actual["gaps"]), actual["gaps"]


def test_sfix_is_only_an_execution_bridge_not_an_inference_membership_change():
    assert "SFIX" in module.EXECUTION_BRIDGE_TICKERS
    assert "SFIX" in module.RECENT_EXECUTION_BRIDGE_TICKERS
    assert module.EXECUTION_GATE == "FIVE_EXACT_OHLC_AND_ALL_OVERLAP_EXACT_OPEN_CLOSE_V1"


def test_new_event_after_prefix_still_stops_execution_extension(recovery, monkeypatch):
    old_factory = module.original._adapter
    def factory(target):
        adapter = old_factory(target)
        def adjusted(code, ticker, raw, factors, wolf):
            frame, events = adapter.adjusted_price_frame(code, ticker, raw, factors, wolf)
            if raw.trade_date.max() == pd.Timestamp(target):
                events.append({"ticker": ticker, "event_date": target, "audit_kind": "SYNTHETIC_NEW_EVENT"})
            return frame, events
        return shared.SimpleNamespace(adjusted_price_frame=adjusted)
    monkeypatch.setattr(module.original, "_adapter", factory)
    result = read_recovery(recovery)
    assert result["prices"].trade_date.max() == pd.Timestamp(recovery["entry"]["raw_end"])
    assert any("NEW_CORPORATE_ACTION_REVIEW_REQUIRED" in gap["reason"] for gap in result["gaps"])


@pytest.mark.parametrize("mixed_roots", [False, True])
def test_restore_task_script_runs_only_offline_with_cache_and_daily_outputs(recovery, tmp_path, monkeypatch, capsys, mixed_roots):
    import os
    import sys
    from types import SimpleNamespace
    from scripts.common import storage_paths
    from scripts.storage import refresh_massive_market as massive
    from scripts.research.a2 import evaluation
    task_path = Path(os.environ.get("USTQ_SFIX_RECOVERY_SCRIPT", ROOT / "artifacts/restore_sfix_execution_prices.py"))
    if not task_path.is_file():
        pytest.skip("Task script stays outside the code repository; set USTQ_SFIX_RECOVERY_SCRIPT to verify it")
    task = load("restore_sfix_task_under_test", task_path)
    paths = SimpleNamespace(repo_root=tmp_path / "repo", data_root=tmp_path / "canonical_data",
        cache_root=tmp_path / "cache", daily_root=tmp_path / "daily", backtest_root=recovery["paths"].backtest_root)
    monkeypatch.setattr(storage_paths, "resolve", lambda _: paths)
    monkeypatch.setattr(evaluation, "demo_performance_prices", module, raising=False)
    monkeypatch.setitem(sys.modules, "scripts.research.a2.evaluation.demo_performance_prices", module)
    monkeypatch.setattr(massive.requests, "get", massive.requests.get)  # Restore the task's process-local network guard.
    coverage = paths.backtest_root / "research/a2/demo_2026_calendar_replay/input_coverage.json"
    monkeypatch.setattr(module.original, "COVERAGE_PATH", coverage)
    entry = recovery["entry"]
    entry.update(ticker="SFIX", code="US.SFIX")
    native_path = Path(entry["raw_sources"][0]["path"])
    native = pd.read_parquet(native_path); native["code"] = "US.SFIX"
    native.to_parquet(native_path, index=False)
    entry["raw_sources"][0]["sha256"] = module.original.digest(native_path)
    factor = recovery["kwargs"]["rehab_receipt"]["results"][0]
    factor_path = Path(factor["path"])
    factors = pd.read_parquet(factor_path); factors["code"] = "US.SFIX"
    factors.to_parquet(factor_path, index=False)
    factor.update(code="US.SFIX", sha256=module.original.digest(factor_path))
    entry["rehab"] = {**factor, "kind": "CURRENT_SNAPSHOT"}
    historical = json.loads(recovery["historical"].read_text())
    price_path = Path(historical["price_manifest"]["path"])
    price_path.write_text(json.dumps({"lineage": [entry]}))
    historical["price_manifest"]["sha256"] = module.original.digest(price_path)
    recovery["historical"].write_text(json.dumps(historical))
    root = paths.cache_root / "daily_recommendation/massive_current"
    refs = []
    for index, source in enumerate(recovery["record"]["lineage"]["inputs"]):
        actual_root = paths.cache_root / "data_acquisition/legacy" if mixed_roots and index < 3 else root
        directory = actual_root / "days" / source["date"]; directory.mkdir(parents=True)
        payload = json.loads(Path(source["path"]).read_text()); payload["results"][0]["T"] = "SFIX"
        leaf = directory / "response.json"; leaf.write_text(json.dumps(payload))
        ref = {"date": source["date"], "observed_at": source["observed_at"], "path": str(leaf),
               "sha256": module.original.digest(leaf), "bytes": leaf.stat().st_size}
        cp = {"status": "SUCCESS", "observed_at": ref["observed_at"],
            "contract": {"date": ref["date"], "url": massive.ENDPOINT + ref["date"],
                         "params": {"adjusted": "false", "include_otc": "false"}},
            "raw": {key: ref[key] for key in ("path", "sha256", "bytes")}}
        (directory / "checkpoint.json").write_text(json.dumps(cp))
        refs.append(ref)
    acquisition = {"summary": {"status": "COMPLETE"}, "catalog_records": [],
        "contract": {"provider": "MASSIVE_GROUPED", "days": [r["date"] for r in refs], "inputs": refs,
                     "mapping": {"UNRELATED": {"provider_symbol": "UNRELATED", "evidence_url": None}}}}
    acquisition_path = tmp_path / "input_sources/acquisition_manifest.json"
    acquisition_path.parent.mkdir()
    acquisition_path.write_text(json.dumps(acquisition))
    current = json.loads(recovery["current"].read_text())
    current["acquisitions"] = {"massive": {"acquisition_manifest": str(acquisition_path)}}
    recovery["current"].write_text(json.dumps(current))
    receipt_path = recovery["current"].parent / "rehab_receipt.json"
    receipt_path.write_text(json.dumps(recovery["kwargs"]["rehab_receipt"]))
    old, _ = module._adjust(entry, module.original._adapter(current["data_date"]),
        {"event_date": "2025-09-29", "quantity_multiplier": .008352}, module.original.verify, {}, None, {})
    failed_prices = tmp_path / "failed_price_paths.parquet"
    old.rename(columns={"trade_date": "date"}).to_parquet(failed_prices, index=False)
    failed_path = tmp_path / "failed_performance_manifest.json"
    failed_path.write_text(json.dumps({"ranking_manifest": task.reference(recovery["historical"]),
        "ranking_end_date": current["data_date"], "performance_start_date": "2026-01-02",
        "blocking_input": {"date": current["data_date"], "reason": "MISSING_PRICE_EVENT", "missing_open_tickers": ["SFIX"]},
        "outputs": {"price_paths": task.reference(failed_prices)}}))
    preserved = {p: p.read_bytes() for p in (recovery["historical"], recovery["current"], failed_path)}
    monkeypatch.setattr(sys, "argv", ["restore_sfix_execution_prices.py", "--repo-root", str(paths.repo_root),
        "--historical-manifest", str(recovery["historical"]), "--current-report", str(recovery["current"]),
        "--failed-performance-manifest", str(failed_path)])
    task.main()
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "PREPARED" and result["new_price_requests"] == 0 and result["catalog_written"] is False
    assert result["new_target_open"] == 101. and result["prefix_rows"] == len(old)
    manifest = Path(result["current_execution_manifest"]["path"])
    assert manifest.is_relative_to(paths.daily_root) and not manifest.with_name("current_execution_records.candidate.json").exists()
    final = json.loads(manifest.read_text())
    records = final["catalog_records"]
    assert len(final["actual_root_map"]) == (2 if mixed_roots else 1)
    assert sum(map(len, final["actual_root_map"].values())) == len(refs)
    assert Path(records[0]["path"]).is_relative_to(paths.cache_root)
    assert not paths.data_root.exists() and not paths.repo_root.exists()
    assert all(p.read_bytes() == before for p, before in preserved.items())


@pytest.mark.parametrize("change", ["raw", "checkpoint", "attempt", "outside_cache"])
def test_mixed_root_task_keeps_raw_checkpoint_attempt_and_cache_boundaries(tmp_path, change):
    import os
    from scripts.storage import refresh_massive_market as massive
    task_path = Path(os.environ.get("USTQ_SFIX_RECOVERY_SCRIPT", ROOT / "artifacts/restore_sfix_execution_prices.py"))
    if not task_path.is_file():
        pytest.skip("External task script is not installed in this code checkout")
    task = load("mixed_root_sfix_task_test", task_path)
    cache = tmp_path / "cache"
    directory = cache / "legacy/days/2026-09-25"
    if change == "outside_cache": directory = tmp_path / "foreign/days/2026-09-25"
    directory.mkdir(parents=True)
    leaf = directory / "response.json"
    leaf.write_text(json.dumps({"status": "OK", "adjusted": False, "resultsCount": 1,
        "results": [{"T": "SFIX", "o": 100., "h": 100., "l": 100., "c": 100., "v": 1000., "t": 1790366400000}]}))
    ref = {"date": "2026-09-25", "observed_at": "2026-09-28T17:00:00Z",
           "path": str(leaf), "sha256": task.digest(leaf), "bytes": leaf.stat().st_size}
    cp = {"status": "SUCCESS", "observed_at": ref["observed_at"],
        "contract": {"date": ref["date"], "url": massive.ENDPOINT + ref["date"],
                     "params": {"adjusted": "false", "include_otc": "false"}},
        "raw": {key: ref[key] for key in ("path", "sha256", "bytes")}}
    if change == "raw": leaf.write_text("changed")
    elif change == "checkpoint": cp["contract"]["params"]["adjusted"] = "true"
    elif change == "attempt":
        foreign = tmp_path / "foreign_attempt.json"; foreign.write_text("{}")
        cp["attempts"] = [{"raw": {"path": str(foreign), "sha256": task.digest(foreign)}}]
    (directory / "checkpoint.json").write_text(json.dumps(cp))
    source = tmp_path / "source/acquisition.json"; source.parent.mkdir()
    value = {"catalog_records": [], "contract": {"days": [ref["date"]], "inputs": [ref], "mapping": {}}}
    source.write_text(json.dumps(value))
    output = cache / "recovery/SFIX"
    with pytest.raises(ValueError):
        task.normalize_original_groups(source, value, cache, output, massive)
    assert not output.exists()
