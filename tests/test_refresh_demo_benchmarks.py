"""Synthetic offline ETF updates; no network, credentials, or production writes."""
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("offline_demo_benchmarks", ROOT / "scripts/storage/refresh_demo_benchmarks.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(module._bytes(value))
    return module._ref(path)


@pytest.fixture
def setup(tmp_path):
    paths = SimpleNamespace(results_root=tmp_path / "results", cache_root=tmp_path / "cache")
    root = paths.results_root / "demo-console/benchmarks"
    run = root / "updated/synthetic_seed"
    proof = write(tmp_path / "raw_seed.json", {"fixture": "explicit synthetic source"})
    artifacts = []
    for ticker in ("QQQ", "SPY"):
        run.mkdir(parents=True, exist_ok=True)
        path = run / (ticker + ".parquet")
        pd.DataFrame([{"date": day, "ticker": ticker, "open": 100. + i,
                       "source": "MASSIVE_GROUPED", "adjustment": "raw"}
                      for i, day in enumerate(("2026-09-21", "2026-09-22"))]).to_parquet(path, index=False)
        artifacts.append({"symbol": ticker, **module._ref(path), "row_count": 2,
                          "start_date": "2026-09-21", "end_date": "2026-09-22", "source_refs": [proof]})
    manifest = {"schema_version": 1, "status": "READY", "basis": "OPEN_TO_OPEN_PRICE_RETURN",
                "adjustment": "RAW", "provider": "MOOMOO_OPEND_AND_MASSIVE", "dividends_included": False,
                "splits_adjusted": False, "fixed_source_cutover": module.CUTOVER,
                "start_date": "2026-09-21", "end_date": "2026-09-22", "artifacts": artifacts}
    pointer = root / "updated_reference.json"
    write(pointer, write(run / "manifest.json", manifest))
    frozen = root / "manifest.json"
    frozen.write_bytes(b"old frozen benchmark manifest")
    calendar = {"target_date": "2026-09-24", "sessions": ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"],
                "calendar_id": "synthetic_verified_calendar", "calendar_sha256": "c" * 64}
    return paths, pointer, calendar, frozen


def checkpoint(paths, day, *, missing=None, adjusted=False, wrong_day=False, bad_open=False):
    root = paths.cache_root / "daily_recommendation/massive_current/days" / day
    timestamp = pd.Timestamp("2026-09-22" if wrong_day else day, tz="America/New_York").value // 1_000_000
    rows = [{"T": ticker, "o": -1. if bad_open else 102., "t": timestamp} for ticker in ("QQQ", "SPY") if ticker != missing]
    raw = write(root / "response.json", {"status": "OK", "resultsCount": len(rows), "adjusted": adjusted, "results": rows})
    raw["bytes"] = Path(raw["path"]).stat().st_size
    saved = {"status": "SUCCESS", "contract": {"date": day, "url": module.ENDPOINT + day,
             "params": {"adjusted": "false", "include_otc": "false"}}, "raw": raw}
    write(root / "checkpoint.json", saved)
    return root / "checkpoint.json"


def test_two_day_offline_append_preserves_history_contract_and_is_idempotent(setup):
    paths, pointer, calendar, frozen = setup
    old = pointer.read_bytes()
    for day in calendar["sessions"][-2:]:
        checkpoint(paths, day)
    with patch("requests.get", side_effect=AssertionError("NO_NETWORK")):
        result = module.refresh_demo_benchmarks(paths, "2026-09-24", calendar)
    assert result["status"] == "READY" and result["appended_sessions"] == 2
    assert result["network_requests"] == result["moomoo_requests"] == 0
    assert pointer.read_bytes() != old and frozen.read_bytes() == b"old frozen benchmark manifest"
    manifest = json.loads(Path(result["manifest"]["path"]).read_bytes())
    assert manifest["previous_manifest"] == json.loads(old)
    assert manifest["fixed_source_cutover"] == module.CUTOVER and manifest["dividends_included"] is False
    for artifact in manifest["artifacts"]:
        frame = pd.read_parquet(artifact["path"])
        assert frame.date.tolist() == calendar["sessions"] and frame.open.tolist()[:2] == [100., 101.]
        assert artifact["row_count"] == 4 and module._hash(artifact["path"]) == artifact["sha256"]
    current = pointer.read_bytes()
    with patch.object(module, "_checkpoint", side_effect=AssertionError("NO_REPEATED_CACHE_EXTRACTION")):
        reused = module.refresh_demo_benchmarks(paths, "2026-09-24", calendar)
    assert reused["status"] == "READY" and reused["reused"] is True and pointer.read_bytes() == current


@pytest.mark.parametrize("problem", ["missing_day", "missing_spy", "duplicate_spy", "adjusted", "timestamp", "bad_open", "raw_hash", "provider_error", "result_count"])
def test_incomplete_or_unverified_cache_keeps_old_pointer_and_explicit_cutoff(setup, problem):
    paths, pointer, calendar, frozen = setup
    original = pointer.read_bytes()
    checkpoint(paths, "2026-09-23")
    if problem != "missing_day":
        file = checkpoint(paths, "2026-09-24", missing="SPY" if problem == "missing_spy" else None,
                          adjusted=problem == "adjusted", wrong_day=problem == "timestamp", bad_open=problem == "bad_open")
        data = json.loads(file.read_bytes())
        if problem == "raw_hash":
            Path(data["raw"]["path"]).write_bytes(b"changed")
        elif problem in {"duplicate_spy", "provider_error", "result_count"}:
            raw = json.loads(Path(data["raw"]["path"]).read_bytes())
            if problem == "duplicate_spy":
                raw["results"].append(raw["results"][-1])
                raw["resultsCount"] = len(raw["results"])
            elif problem == "provider_error":
                raw["status"] = "ERROR"
            else:
                raw["resultsCount"] = 999
            data["raw"] = write(Path(data["raw"]["path"]), raw)
            data["raw"]["bytes"] = Path(data["raw"]["path"]).stat().st_size
            write(file, data)
    result = module.refresh_demo_benchmarks(paths, "2026-09-24", calendar)
    assert result["status"] == "BLOCKED" and result["available_end_date"] == "2026-09-22" and result["error"]
    assert pointer.read_bytes() == original and frozen.read_bytes() == b"old frozen benchmark manifest"


@pytest.mark.parametrize("problem", ["baseline_hash", "source_hash", "calendar_anchor", "contract"])
def test_bound_source_or_calendar_failure_never_publishes(setup, problem):
    paths, pointer, calendar, _ = setup
    reference = json.loads(pointer.read_bytes())
    manifest = json.loads(Path(reference["path"]).read_bytes())
    if problem == "baseline_hash":
        Path(manifest["artifacts"][0]["path"]).write_bytes(b"changed")
    elif problem == "source_hash":
        Path(manifest["artifacts"][0]["source_refs"][0]["path"]).write_bytes(b"changed")
    elif problem == "calendar_anchor":
        calendar["sessions"].remove("2026-09-22")
    else:
        manifest["dividends_included"] = True
        write(pointer, write(Path(reference["path"]), manifest))
    original = pointer.read_bytes()
    result = module.refresh_demo_benchmarks(paths, "2026-09-24", calendar)
    assert result["status"] == "BLOCKED" and pointer.read_bytes() == original




@pytest.fixture
def native_setup(setup):
    paths, pointer, calendar, frozen = setup
    paths.repo_root = ROOT
    reference = json.loads(pointer.read_bytes())
    manifest = json.loads(Path(reference["path"]).read_bytes())
    dates = ["2026-09-16", "2026-09-17", "2026-09-18", "2026-09-21", "2026-09-22"]
    for artifact in manifest["artifacts"]:
        frame = pd.DataFrame([{ "date": day, "ticker": artifact["symbol"], "open": 100. + i,
                               "source": "MASSIVE_GROUPED", "adjustment": "raw"} for i, day in enumerate(dates)])
        frame.to_parquet(artifact["path"], index=False)
        artifact.update(module._ref(artifact["path"]), row_count=len(dates), start_date=dates[0])
    manifest["start_date"] = dates[0]
    write(pointer, write(Path(reference["path"]), manifest))
    calendar["sessions"] = dates + ["2026-09-23", "2026-09-24"]
    return paths, pointer, calendar, frozen


def failed_checkpoint(paths, day):
    path = paths.cache_root / "daily_recommendation/massive_current/days" / day / "checkpoint.json"
    return write(path, {"status": "FAILED", "error": "HTTP_403", "contract": {"date": day,
        "url": module.ENDPOINT + day, "params": {"adjusted": "false", "include_otc": "false"}}})


def native_checkpoints(paths, calendar):
    from scripts.storage import refresh_market_data as market
    root = paths.cache_root / "native_original_checkpoint"
    result = {}
    for symbol, identity in module.ETF_IDENTITIES.items():
        item = {"ticker": symbol, "security_id": identity["security_id"], "moomoo_symbol": identity["provider_code"],
            "market": "US", "frequency": "1d", "adjustment": "raw", "planned_start_date": calendar["sessions"][0],
            "planned_end_date": calendar["target_date"], "acquisition_method": "GET_CUR_KLINE", "num": 130,
            "session": "RTH", "subscribe_push": False}
        records = [{"ticker": symbol, "moomoo_symbol": identity["provider_code"], "market": "US", "date": day,
            "open": 100. + i, "high": 102. + i, "low": 99. + i, "close": 101. + i, "volume": 100.,
            "turnover": 1000., "adjustment": "raw", "source": "MOOMOO_OPEND", "source_policy": "MOOMOO_ONLY",
            "snapshot_id": "explicit_synthetic_sdk", "fetched_at_utc": "2026-09-25T12:00:00+00:00"}
            for i, day in enumerate(calendar["sessions"])]
        saved = market.save_interval(root, item, records, "a" * 64)
        sdk_path = root / "sdk_responses" / (market.interval_key(item) + ".parquet")
        sdk_path.parent.mkdir(parents=True, exist_ok=True)
        sdk = pd.DataFrame([{**{key: row[key] for key in ["open", "high", "low", "close", "volume", "turnover"]},
            "code": identity["provider_code"], "time_key": row["date"] + " 00:00:00"} for row in records])
        sdk.to_parquet(sdk_path, index=False)
        saved["current_kline_provenance"] = {"code": identity["provider_code"], "api": "get_cur_kline", "retcode": 0,
            "autype": "NONE", "ktype": "K_DAY", "session": "RTH", "observed_at_utc": "2026-09-25T12:00:00+00:00",
            "sdk_response": module._ref(sdk_path)}
        receipt = Path(saved["path"]).with_suffix(".json")
        market.write_json(receipt, saved)
        result[symbol] = {"kind": "CURRENT_KLINE", "reference": module._ref(receipt), **identity}
    return result


def test_native_fallback_preserves_exact_prefix_honest_source_and_consumer(native_setup):
    paths, pointer, calendar, frozen = native_setup
    original = pointer.read_bytes()
    prior = json.loads(Path(json.loads(original)["path"]).read_bytes())
    previous = {row["symbol"]: pd.read_parquet(row["path"]) for row in prior["artifacts"]}
    for day in calendar["sessions"][-2:]:
        failed_checkpoint(paths, day)
    inputs = native_checkpoints(paths, calendar)
    with patch("requests.get", side_effect=AssertionError("NO_NETWORK")):
        candidate = module.refresh_demo_benchmarks(paths, calendar["target_date"], calendar,
            native_inputs=inputs, publish=False)
    assert candidate["status"] == "READY" and candidate["published"] is False and pointer.read_bytes() == original
    manifest = json.loads(Path(candidate["manifest"]["path"]).read_bytes())
    assert manifest["source_fallbacks"][0]["previous_manifest"] == json.loads(original)
    for spec in manifest["artifacts"]:
        current = pd.read_parquet(spec["path"])
        pd.testing.assert_frame_equal(current.iloc[:5].reset_index(drop=True), previous[spec["symbol"]])
        assert current.source.tolist() == ["MASSIVE_GROUPED"] * 5 + ["MOOMOO_OPEND"] * 2
    from apps.demo_console.adapters import benchmarks_reader as reader
    config = reader.UpdatedBenchmarkConfig(Path(candidate["manifest"]["path"]), candidate["manifest"]["sha256"])
    history = reader.read_updated_benchmarks(tuple(calendar["sessions"]), config=config)
    assert history.error is None and all(not x.error and len(x.points) == 7 for x in history.series)
    published = module.refresh_demo_benchmarks(paths, calendar["target_date"], calendar, native_inputs=inputs)
    assert published["status"] == "READY" and published["published"] is True
    after = pointer.read_bytes()
    with patch.object(module, "_native_rows", side_effect=AssertionError("NO_NATIVE_REEXTRACTION")), \
            patch.object(module, "_checkpoint", side_effect=AssertionError("NO_CACHE_REEXTRACTION")):
        reused = module.refresh_demo_benchmarks(paths, calendar["target_date"], calendar)
        scope = module.benchmark_native_scope(paths, calendar["target_date"], calendar)
    assert reused["reused"] is True and scope["status"] == "NOOP" and pointer.read_bytes() == after
    assert frozen.read_bytes() == b"old frozen benchmark manifest"
    calendar["sessions"].append("2026-09-25"); calendar["target_date"] = "2026-09-25"
    checkpoint(paths, "2026-09-25")
    extended = module.refresh_demo_benchmarks(paths, "2026-09-25", calendar)
    assert extended["status"] == "READY" and extended["source_fallback_applied"] is False
    future = json.loads(Path(extended["manifest"]["path"]).read_bytes())
    assert future["source_fallbacks"] == manifest["source_fallbacks"]
    for spec in future["artifacts"]:
        assert pd.read_parquet(spec["path"]).source.tolist() == ["MASSIVE_GROUPED"] * 5 + ["MOOMOO_OPEND"] * 2 + ["MASSIVE_GROUPED"]


@pytest.mark.parametrize("problem", ["one_etf", "identity", "currency", "source", "adjusted", "wrong_target", "raw_hash", "sdk_hash", "sdk_value", "overlap", "missing_target", "not_failed", "naive_observation", "before_close", "future_observation"])
def test_native_fallback_rejects_unqualified_inputs_without_pointer_mutation(native_setup, problem):
    paths, pointer, calendar, _ = native_setup
    for day in calendar["sessions"][-2:]:
        failed_checkpoint(paths, day)
    inputs = native_checkpoints(paths, calendar)
    spec = inputs["SPY"]
    receipt = Path(spec["reference"]["path"])
    saved = json.loads(receipt.read_bytes())
    if problem == "one_etf":
        del inputs["SPY"]
    elif problem == "identity":
        spec["security_id"] = "000000000"
    elif problem == "currency":
        spec["currency"] = "CNY"
    elif problem == "raw_hash":
        Path(saved["path"]).write_bytes(b"tampered")
    elif problem == "sdk_hash":
        Path(saved["current_kline_provenance"]["sdk_response"]["path"]).write_bytes(b"tampered")
    elif problem == "not_failed":
        checkpoint(paths, calendar["sessions"][-1], adjusted=True)
    else:
        raw = pd.read_csv(saved["path"])
        sdk_path = Path(saved["current_kline_provenance"]["sdk_response"]["path"])
        sdk = pd.read_parquet(sdk_path)
        if problem == "source":
            raw["source"] = "MASSIVE_GROUPED"
        elif problem == "adjusted":
            saved["current_kline_provenance"]["autype"] = "QFQ"
        elif problem == "wrong_target":
            saved["item"]["planned_end_date"] = "2026-09-23"
        elif problem in {"naive_observation", "before_close", "future_observation"}:
            saved["current_kline_provenance"]["observed_at_utc"] = {"naive_observation": "2026-09-25T12:00:00",
                "before_close": "2026-09-24T19:59:59+00:00", "future_observation": "2099-01-01T00:00:00+00:00"}[problem]
        elif problem in {"sdk_value", "overlap"}:
            sdk.loc[0, "open"] = 100.01
            if problem == "overlap":
                raw.loc[0, "open"] = 100.01
        elif problem == "missing_target":
            raw = raw.iloc[:-1]; sdk = sdk.iloc[:-1]
            saved.update(row_count=len(raw), latest_date="2026-09-23")
        raw.to_csv(saved["path"], index=False)
        sdk.to_parquet(sdk_path, index=False)
        saved["sha256"] = module._hash(saved["path"])
        saved["current_kline_provenance"]["sdk_response"] = module._ref(sdk_path)
        write(receipt, saved)
        spec["reference"] = module._ref(receipt)
    before = pointer.read_bytes()
    result = module.refresh_demo_benchmarks(paths, calendar["target_date"], calendar, native_inputs=inputs)
    assert result["status"] == "BLOCKED" and result["error"] and pointer.read_bytes() == before


def test_native_scope_reuses_same_validation_and_never_acquires(native_setup):
    paths, pointer, calendar, _ = native_setup
    before = pointer.read_bytes()
    with patch.object(module, "_native_rows", side_effect=AssertionError("SCOPE_MUST_NOT_LOAD_NATIVE")):
        blocked = module.benchmark_native_scope(paths, calendar["target_date"], calendar)
        assert blocked["status"] == "BLOCKED"
        for day in calendar["sessions"][-2:]:
            failed_checkpoint(paths, day)
        scope = module.benchmark_native_scope(paths, calendar["target_date"], calendar)
        assert scope["status"] == "NEEDS_NATIVE" and scope["bridge_start"] == calendar["sessions"][0]
        assert scope["required_dates"] == calendar["sessions"] and scope["native_tickers"] == ["QQQ", "SPY"]
        for day in calendar["sessions"][-2:]:
            checkpoint(paths, day)
        assert module.benchmark_native_scope(paths, calendar["target_date"], calendar)["status"] == "MASSIVE_READY"
    assert pointer.read_bytes() == before


def test_native_bridge_requires_five_actual_prior_records(setup):
    paths, pointer, calendar, _ = setup
    paths.repo_root = ROOT
    for day in calendar["sessions"][-2:]:
        failed_checkpoint(paths, day)
    inputs = native_checkpoints(paths, calendar)
    before = pointer.read_bytes()
    result = module.refresh_demo_benchmarks(paths, calendar["target_date"], calendar, native_inputs=inputs)
    assert result["status"] == "BLOCKED" and "FIVE_ACCEPTED" in result["error"] and pointer.read_bytes() == before


def test_catalog_native_path_reuses_existing_all_leaf_qualification(native_setup, monkeypatch):
    paths, _, calendar, _ = native_setup
    from scripts.research.a2.inference import historical_top40_prices as historical, current_native_prices as native
    raw = pd.DataFrame({"trade_date": calendar["sessions"], "open": [100. + i for i in range(7)]})
    catalog = paths.cache_root / "bound_native_version.parquet"; catalog.parent.mkdir(parents=True, exist_ok=True); raw.to_parquet(catalog, index=False)
    leaf = write(paths.cache_root / "bound_native_leaf.json", {"synthetic": "all-leaf proof"})
    reference = module._ref(catalog)
    calls = []
    store = SimpleNamespace(metadata=lambda *args: {"path": reference["path"], "source_sha256": reference["sha256"]})
    monkeypatch.setattr(historical, "_store", lambda p: store)
    def qualify(actual, symbol, code, target):
        calls.append((actual, symbol, code, target))
        return raw, {"raw_inputs": [leaf]}
    monkeypatch.setattr(native, "_native_raw", qualify)
    projected, refs = module._native_rows(paths, "QQQ", calendar["target_date"],
        {"kind": "CATALOG_RAW", "reference": reference, **module.ETF_IDENTITIES["QQQ"]})
    assert projected.date.tolist() == calendar["sessions"] and refs == [reference, leaf]
    assert calls == [(store, "QQQ", "US.QQQ", calendar["target_date"])]


def test_mixed_success_failure_uses_primary_for_success_and_preserves_failure_bytes(native_setup):
    paths, pointer, calendar, _ = native_setup
    first, target = calendar["sessions"][-2:]
    original_failure = failed_checkpoint(paths, first)
    checkpoint(paths, target)
    inputs = native_checkpoints(paths, calendar)
    scope = module.benchmark_native_scope(paths, target, calendar)
    assert scope["required_dates"] == calendar["sessions"][:-1]
    assert scope["missing_dates"] == [first] and scope["target_date"] == target
    result = module.refresh_demo_benchmarks(paths, target, calendar, native_inputs=inputs)
    assert result["status"] == "READY"
    manifest = json.loads(Path(result["manifest"]["path"]).read_bytes())
    record = manifest["source_fallbacks"][0]
    assert record["dates"] == [first]
    captured = record["massive_failures"][0]
    assert captured["origin_reference"] == original_failure
    assert captured["reference"]["path"] != original_failure["path"]
    assert module._hash(captured["reference"]["path"]) == original_failure["sha256"]
    for spec in manifest["artifacts"]:
        rows = pd.read_parquet(spec["path"])
        assert rows.source.tolist()[-2:] == ["MOOMOO_OPEND", "MASSIVE_GROUPED"]
    checkpoint(paths, first)  # Legitimate provider recovery rewrites only mutable original cache.
    assert module._hash(original_failure["path"]) != original_failure["sha256"]
    same = module.refresh_demo_benchmarks(paths, target, calendar)
    assert same["status"] == "READY" and same["reused"] is True
    calendar["sessions"].append("2026-09-25"); calendar["target_date"] = "2026-09-25"
    checkpoint(paths, "2026-09-25")
    future = module.refresh_demo_benchmarks(paths, "2026-09-25", calendar)
    assert future["status"] == "READY"


@pytest.fixture
def official_open_setup(native_setup):
    paths, pointer, calendar, frozen = native_setup
    signal, execution = "2026-09-22", "2026-09-23"
    native_calendar = {**calendar, "target_date": signal, "sessions": calendar["sessions"][:5]}
    inputs = native_checkpoints(paths, native_calendar)
    for spec in inputs.values():
        reference = spec["reference"]
        saved = json.loads(Path(reference["path"]).read_bytes())
        provenance = saved["current_kline_provenance"]
        sdk_path = Path(provenance["sdk_response"]["path"])
        frame = pd.read_parquet(sdk_path)
        # Deliberately unclosed HLCV are quarantined; only official open is usable.
        frame.loc[len(frame)] = {"code": spec["provider_code"], "time_key": execution + " 00:00:00",
            "open": 106., "high": float("nan"), "low": float("nan"), "close": float("nan"),
            "volume": float("nan"), "turnover": float("nan")}
        frame.to_parquet(sdk_path,index=False)
        provenance.update(observed_at_utc="2026-09-23T14:00:00+00:00", num=130, owned_subscription=True,
            sdk_response_semantics="RETURNED_DATAFRAME_PARQUET_NOT_WIRE_RESPONSE",
            availability="CURRENT_RETRIEVAL_NOT_HISTORICAL_PIT", sdk_response=module._ref(sdk_path))
        spec["reference"] = write(Path(reference["path"]), saved)
    calendar.update(target_date=execution, sessions=calendar["sessions"][:6], as_of_utc="2026-09-23T14:01:00+00:00")
    phase={"signal_date": signal, "execution_date": execution, "as_of_utc": calendar["as_of_utc"]}
    return paths,pointer,calendar,frozen,inputs,phase


def test_official_open_both_etfs_preserve_all_old_values_and_reader_contract(official_open_setup, monkeypatch):
    paths,pointer,calendar,frozen,inputs,phase=official_open_setup
    before=pointer.read_bytes(); old=json.loads(Path(json.loads(before)["path"]).read_bytes())
    old_frames={spec["symbol"]:pd.read_parquet(spec["path"]) for spec in old["artifacts"]}
    import pyarrow.parquet as pq
    original_read=pq.read_table
    def guarded_read(*args,**kwargs):
        filters=kwargs.get("filters") or []
        if any(x[0]=="time_key" and x[1]==">=" and str(x[2]).startswith(phase["execution_date"]) for x in filters):
            assert kwargs["columns"]==["code","time_key","open"]
        return original_read(*args,**kwargs)
    with patch.object(pq,"read_table",guarded_read), patch("requests.get",side_effect=AssertionError("NO_NETWORK")):
        result=module.refresh_demo_benchmarks(paths,calendar["target_date"],calendar,native_inputs=inputs,
                                               execution_open=phase,publish=False)
    assert result["status"]=="READY" and result["official_open_only"] and not result["closed_ohlcv_observed"],result
    assert not result["published"] and pointer.read_bytes()==before
    m=json.loads(Path(result["manifest"]["path"]).read_bytes())
    fallback=m["source_fallbacks"][-1]
    assert fallback["schema"]==module.OFFICIAL_OPEN_POLICY and "massive_failures" not in fallback
    for spec in m["artifacts"]:
        frame=pd.read_parquet(spec["path"])
        pd.testing.assert_frame_equal(frame.iloc[:-1].reset_index(drop=True),old_frames[spec["symbol"]])
        assert list(frame.columns)==module.COLUMNS and frame.iloc[-1].open==106. and frame.iloc[-1].source=="MOOMOO_OPEND"
    from apps.demo_console.adapters import benchmarks_reader as reader
    import scripts.storage.refresh_demo_benchmarks as active_owner
    monkeypatch.setattr(active_owner,"source_exceptions",module.source_exceptions)
    history=reader.read_updated_benchmarks(tuple(calendar["sessions"]),
        config=reader.UpdatedBenchmarkConfig(Path(result["manifest"]["path"]),result["manifest"]["sha256"]))
    assert history.error is None and all(not x.error for x in history.series)
    published=module.refresh_demo_benchmarks(paths,calendar["target_date"],calendar,native_inputs=inputs,execution_open=phase)
    assert published["status"]=="READY" and published["published"]
    assert frozen.read_bytes()==b"old frozen benchmark manifest"
    after=pointer.read_bytes()
    with patch.object(module,"_qualified_official_open",side_effect=AssertionError("NO_REPEATED_OPEN_EXTRACTION")):
        repeat=module.refresh_demo_benchmarks(paths,calendar["target_date"],calendar,native_inputs=inputs,execution_open=phase)
    assert repeat["reused"] and pointer.read_bytes()==after


@pytest.mark.parametrize("problem",["one_etf","wrong_sid","wrong_execution","non_next_session","before_open",
    "naive_clock","future_clock","old_observation","not_owned","wrong_api","wrong_code","raw_hash",
    "sdk_hash","missing_open","duplicate_open","bad_open","historical_open_revision","catalog_only"])
def test_official_open_invalid_evidence_preserves_pointer(official_open_setup,problem):
    paths,pointer,calendar,_,inputs,phase=official_open_setup
    reference=inputs["QQQ"]["reference"]; saved=json.loads(Path(reference["path"]).read_bytes())
    prov=saved["current_kline_provenance"]; sdk=Path(prov["sdk_response"]["path"])
    if problem=="one_etf": inputs.pop("SPY")
    elif problem=="wrong_sid": inputs["QQQ"]["security_id"]="WRONG"
    elif problem=="wrong_execution": phase["execution_date"]="2026-09-24"
    elif problem=="non_next_session": calendar["sessions"].insert(-1,"2026-09-22-extra")
    elif problem=="before_open": phase["as_of_utc"]="2026-09-23T13:29:59+00:00"
    elif problem=="naive_clock": phase["as_of_utc"]="2026-09-23T14:01:00"
    elif problem=="future_clock": phase["as_of_utc"]="2099-09-23T14:01:00+00:00"
    elif problem=="old_observation": prov["observed_at_utc"]="2026-09-22T21:00:00+00:00"
    elif problem=="not_owned": prov["owned_subscription"]=False
    elif problem=="wrong_api": prov["api"]="request_history_kline"
    elif problem=="wrong_code": prov["code"]="US.SPY"
    elif problem=="raw_hash": Path(saved["path"]).write_bytes(b"bad source")
    elif problem=="sdk_hash": sdk.write_bytes(b"bad source")
    elif problem=="catalog_only": inputs["QQQ"]["kind"]="CATALOG_RAW"
    else:
        frame=pd.read_parquet(sdk)
        if problem=="missing_open":frame=frame.iloc[:-1]
        elif problem=="duplicate_open":frame=pd.concat([frame,frame.iloc[-1:]],ignore_index=True)
        elif problem=="bad_open":frame.loc[len(frame)-1,"open"]=-1.
        elif problem=="historical_open_revision":frame.loc[0,"open"]=999.
        frame.to_parquet(sdk,index=False);prov["sdk_response"]=module._ref(sdk)
    if problem not in {"raw_hash","sdk_hash"}:
        inputs["QQQ"]["reference"]=write(Path(reference["path"]),saved)
    before=pointer.read_bytes()
    result=module.refresh_demo_benchmarks(paths,calendar["target_date"],calendar,native_inputs=inputs,execution_open=phase)
    assert result["status"]=="BLOCKED" and pointer.read_bytes()==before


def test_official_open_then_closed_extension_retains_accepted_open_not_vendor_restatement(official_open_setup):
    paths,pointer,calendar,_,inputs,phase=official_open_setup
    result=module.refresh_demo_benchmarks(paths,calendar["target_date"],calendar,native_inputs=inputs,execution_open=phase)
    assert result["status"]=="READY"
    first=json.loads(Path(result["manifest"]["path"]).read_bytes())
    # Later closed same date is NOOP even when a revised grouped open is present.
    checkpoint(paths,calendar["target_date"])
    same=module.refresh_demo_benchmarks(paths,calendar["target_date"],calendar)
    assert same["reused"] and same["manifest"]==result["manifest"]
    calendar["sessions"].append("2026-09-24");calendar["target_date"]="2026-09-24"
    checkpoint(paths,"2026-09-24")
    result=module.refresh_demo_benchmarks(paths,calendar["target_date"],calendar)
    assert result["status"]=="READY"
    last=json.loads(Path(result["manifest"]["path"]).read_bytes())
    for spec,old_spec in zip(last["artifacts"],first["artifacts"]):
        pd.testing.assert_frame_equal(pd.read_parquet(spec["path"]).iloc[:-1].reset_index(drop=True),pd.read_parquet(old_spec["path"]))


def test_official_open_qualifier_rejects_arrow_boolean_price_before_float(official_open_setup,monkeypatch):
    paths,_,calendar,_,inputs,phase=official_open_setup
    ref=inputs["QQQ"]["reference"]; saved=json.loads(Path(ref["path"]).read_bytes())
    sdk=Path(saved["current_kline_provenance"]["sdk_response"]["path"])
    pd.DataFrame([{"code":"US.QQQ","time_key":phase["execution_date"]+" 00:00:00","open":True}]).to_parquet(sdk,index=False)
    saved["current_kline_provenance"]["sdk_response"]=module._ref(sdk)
    inputs["QQQ"]["reference"]=write(Path(ref["path"]),saved)
    # Isolate the terminal value type guard from already-covered closed-history checks.
    monkeypatch.setattr(module,"_qualified_native",lambda *a: ({},{symbol:{} for symbol in module.ETF_IDENTITIES},[]))
    with pytest.raises(ValueError,match="BOOLEAN_PRICE_INVALID"):
        module._qualified_official_open(paths,inputs,{},[phase["signal_date"]],calendar["target_date"],calendar,phase)
