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


