from __future__ import annotations

import csv
import importlib.util
import json
import os
import subprocess
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v22_040_daily_moomoo_oneclick_refresh_orchestrator_r1.py")
SPEC = importlib.util.spec_from_file_location("v22_040", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["ticker", "moomoo_symbol", "market", "date", "open", "high", "low", "close", "volume", "adjustment"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def rows(latest: str, adjustment: str, tickers: list[str] | None = None) -> list[dict[str, object]]:
    tickers = tickers or ["DRAM", "AAPL"]
    out = []
    for ticker in tickers:
        for day in ["2026-07-01", latest]:
            out.append({
                "ticker": ticker,
                "moomoo_symbol": f"US.{ticker}",
                "market": "US",
                "date": day,
                "open": 10,
                "high": 12,
                "low": 9,
                "close": 11,
                "volume": 1000,
                "adjustment": adjustment,
            })
    return out


def make_snapshot(cache_root: Path, snapshot_id: str, latest: str, raw: bool = True, qfq: bool = True) -> Path:
    directory = cache_root / "canonical/moomoo_ohlcv" / f"snapshot_id={snapshot_id}"
    if raw:
        write_csv(directory / module.CANON_RAW, rows(latest, "raw"))
    if qfq:
        write_csv(directory / module.CANON_QFQ, rows(latest, "qfq"))
    return directory


def make_promoted_snapshot(cache_root: Path, suffix: str, latest: str = "2026-07-08") -> Path:
    snapshot_id = f"v22_040_promoted_{suffix}"
    directory = make_snapshot(cache_root, snapshot_id, latest)
    module.write_json_atomic(
        directory / "canonical_manifest.json",
        {
            "snapshot_id": snapshot_id,
            "canonical_raw_path": str(directory / module.CANON_RAW),
            "canonical_qfq_path": str(directory / module.CANON_QFQ),
            "latest_date": latest,
        },
    )
    return directory


def write_pointer(repo: Path, cache_root: Path, snapshot_dir: Path, snapshot_id: str) -> None:
    v231 = repo / module.V231_REL
    v231.mkdir(parents=True, exist_ok=True)
    pointer = module.pointer_payload(cache_root, snapshot_id, snapshot_dir)
    module.write_json_atomic(v231 / "canonical_snapshot_pointer.json", pointer)
    module.write_csv_atomic(v231 / "canonical_snapshot_pointer.csv", [{"key": k, "value": v} for k, v in pointer.items()], module.POINTER_FIELDS)
    module.write_json_atomic(
        v231 / "v21_231_summary.json",
        {
            "final_status": "PASS_V21_231_MOOMOO_ONLY_CANONICAL_REBUILD_READY",
            "final_decision": "MOOMOO_ONLY_CANONICAL_READY_FOR_DRAM_AND_ABCDE_RERUN",
            "cache_root": str(cache_root),
            "canonical_snapshot_dir": str(snapshot_dir),
            "canonical_latest_date": module.csv_stats(snapshot_dir / module.CANON_QFQ)["max_date"],
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "research_only": True,
        },
    )


def fetch_runner_factory(cache_root: Path, latest: str, *, snapshot_id: str = "fetch", raw: bool = True, qfq: bool = True):
    def fetch_runner(**kwargs):
        repo = kwargs["repo_root"]
        snap_dir = make_snapshot(cache_root, snapshot_id, latest, raw=raw, qfq=qfq)
        write_pointer(repo, cache_root, snap_dir, snapshot_id)
        return {
            "final_status": "PASS_V21_231_MOOMOO_ONLY_CANONICAL_REBUILD_READY",
            "cache_root": str(cache_root),
            "canonical_latest_date": latest,
            "broker_action_allowed": False,
            "official_adoption_allowed": False,
            "research_only": True,
        }
    return fetch_runner


def stage_runner_factory(*, stale_abcde: bool = False, broker_mutation: bool = False):
    def runner(stage: str, repo: Path, out: Path) -> dict:
        out.mkdir(parents=True, exist_ok=True)
        pointer = json.loads((repo / module.V231_REL / "canonical_snapshot_pointer.json").read_text(encoding="utf-8"))
        latest = module.csv_stats(Path(pointer["canonical_qfq_path"]))["max_date"]
        common = {
            "final_status": f"PASS_{stage}",
            "broker_action_allowed": broker_mutation if stage == "V21.233" else False,
            "official_adoption_allowed": False,
            "research_only": True,
        }
        if stage == "V21.232":
            payload = {**common, "latest_price_date": latest}
            module.write_json_atomic(out / "v21_232_summary.json", payload)
            return payload
        if stage == "V21.233":
            abcde_date = "2026-07-01" if stale_abcde else latest
            payload = {**common, "canonical_latest_date": abcde_date, "same_date_comparable_all_strategies": "True", "quality_error_count": 0}
            module.write_json_atomic(out / "v21_233_summary.json", payload)
            return payload
        if stage == "V21.234":
            payload = {**common, "final_decision": "MINIMAL_MOOMOO_ONLY_DAILY_RESEARCH_CHAIN_READY_RESEARCH_ONLY"}
            module.write_json_atomic(out / "v21_234_summary.json", payload)
            return payload
        if stage == "V21.256":
            payload = {**common, "final_decision": "DAILY_MASTER_WRAPPER_WITH_CONTEXT_READY_RESEARCH_ONLY"}
            module.write_json_atomic(out / "v21_256_summary.json", payload)
            return payload
        raise AssertionError(stage)
    return runner


def test_complete_same_day_refresh(tmp_path):
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"
    summary = module.run(
        repo,
        target_date="2026-07-08",
        cache_root=cache,
        fetch_runner=fetch_runner_factory(cache, "2026-07-08"),
        stage_runner=stage_runner_factory(),
    )
    assert summary["final_status"] == module.PASS_STATUS
    assert summary["latest_available_date"] == "2026-07-08"
    assert summary["canonical_pointer_updated"] is True
    assert summary["abcde_rerun_succeeded"] is True
    assert summary["dram_rerun_succeeded"] is True


def test_target_date_unavailable_fallback_warns(tmp_path):
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"
    summary = module.run(
        repo,
        target_date="2026-07-08",
        cache_root=cache,
        fetch_runner=fetch_runner_factory(cache, "2026-07-07"),
        stage_runner=stage_runner_factory(),
    )
    assert summary["final_status"] == module.WARN_TARGET
    assert summary["latest_available_date"] == "2026-07-07"
    assert summary["data_gap_days"] == 1


def test_empty_snapshot_directory_must_fail(tmp_path):
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"
    empty = cache / "canonical/moomoo_ohlcv/snapshot_id=empty"
    empty.mkdir(parents=True)
    write_pointer(repo, cache, empty, "empty")
    summary = module.run(
        repo,
        target_date="2026-07-08",
        cache_root=cache,
        fetch_runner=lambda **kwargs: {"final_status": "PASS", "broker_action_allowed": False, "official_adoption_allowed": False},
        stage_runner=stage_runner_factory(),
    )
    assert summary["final_status"] == module.FAIL_STATUS
    assert "NO_COMPLETE_CANONICAL_SNAPSHOT_CANDIDATE" in summary["error_message"]


def test_stale_pointer_is_repaired_to_latest_complete_snapshot(tmp_path):
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"
    old = make_snapshot(cache, "old", "2026-07-05")
    latest = make_snapshot(cache, "latest", "2026-07-08")
    write_pointer(repo, cache, old, "old")
    summary = module.run(
        repo,
        target_date="2026-07-08",
        cache_root=cache,
        fetch_runner=lambda **kwargs: {"final_status": "PASS", "broker_action_allowed": False, "official_adoption_allowed": False},
        stage_runner=stage_runner_factory(),
    )
    pointer = json.loads((repo / module.V231_REL / "canonical_snapshot_pointer.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == module.PASS_STATUS
    assert summary["latest_available_date"] == "2026-07-08"
    assert pointer["snapshot_id"] == summary["canonical_snapshot_id"]
    assert Path(pointer["canonical_snapshot_dir"]) != latest


def test_missing_qfq_or_raw_canonical_files_must_fail(tmp_path):
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"
    summary = module.run(
        repo,
        target_date="2026-07-08",
        cache_root=cache,
        fetch_runner=fetch_runner_factory(cache, "2026-07-08", qfq=False),
        stage_runner=stage_runner_factory(),
    )
    assert summary["final_status"] == module.FAIL_STATUS
    assert "NO_COMPLETE_CANONICAL_SNAPSHOT_CANDIDATE" in summary["error_message"]


def test_global_max_target_date_with_partial_universe_cannot_promote(tmp_path):
    repo, cache = tmp_path / "repo", tmp_path / "cache"
    snap = cache / "canonical/moomoo_ohlcv/snapshot_id=partial"
    universe = [f"T{i:03d}" for i in range(326)]
    raw_rows = rows("2026-07-14", "raw", universe)
    qfq_rows = rows("2026-07-14", "qfq", universe)
    for r in raw_rows + qfq_rows:
        if r["ticker"] in set(universe[:5]) and r["date"] == "2026-07-14":
            r["date"] = "2026-07-15"
    write_csv(snap / module.CANON_RAW, raw_rows); write_csv(snap / module.CANON_QFQ, qfq_rows)
    write_pointer(repo, cache, snap, "partial")
    summary = module.run(repo, target_date="2026-07-15", cache_root=cache,
                         fetch_runner=lambda **_: {"final_status":"PASS", "broker_action_allowed":False, "official_adoption_allowed":False})
    assert summary["final_status"] == module.FAIL_STATUS
    assert "TARGET_DATE_UNIVERSE_INCOMPLETE" in summary["error_message"]


def test_raw_qfq_ticker_set_mismatch_cannot_promote(tmp_path):
    repo, cache = tmp_path / "repo", tmp_path / "cache"
    snap = cache / "canonical/moomoo_ohlcv/snapshot_id=mismatch"
    write_csv(snap / module.CANON_RAW, rows("2026-07-15", "raw", ["A", "B"]))
    write_csv(snap / module.CANON_QFQ, rows("2026-07-15", "qfq", ["A"]))
    write_pointer(repo, cache, snap, "mismatch")
    summary = module.run(repo, target_date="2026-07-15", cache_root=cache,
                         fetch_runner=lambda **_: {"final_status":"PASS", "broker_action_allowed":False, "official_adoption_allowed":False})
    assert summary["final_status"] == module.FAIL_STATUS


def test_325_of_326_with_one_approved_exclusion_can_promote(tmp_path):
    repo, cache = tmp_path / "repo", tmp_path / "cache"
    universe = [f"T{i:03d}" for i in range(326)]
    snap = cache / "canonical/moomoo_ohlcv/snapshot_id=one-excluded"
    write_csv(snap / module.CANON_RAW, rows("2026-07-15", "raw", universe[:-1]))
    write_csv(snap / module.CANON_QFQ, rows("2026-07-15", "qfq", universe[:-1]))
    write_pointer(repo, cache, snap, "one-excluded")
    v231 = repo / module.V231_REL
    (v231 / "abcde_expected_universe.csv").write_text("ticker\n" + "\n".join(universe) + "\n", encoding="utf-8")
    (v231 / "abcde_exclusion_ledger.csv").write_text(f"ticker,status\n{universe[-1]},APPROVED\n", encoding="utf-8")
    summary = module.run(repo, target_date="2026-07-15", cache_root=cache,
                         fetch_runner=lambda **_: {"final_status":"PASS", "broker_action_allowed":False, "official_adoption_allowed":False},
                         stage_runner=stage_runner_factory())
    assert summary["final_status"] == module.PASS_STATUS
    assert summary["expected_universe_count"] == 326
    assert summary["target_date_ticker_count"] == 325
    assert summary["excluded_ticker_count"] == 1


def test_pointer_validation_uses_325_active_members_without_olpx(tmp_path):
    repo, cache = tmp_path / "repo", tmp_path / "cache"
    universe = [f"T{i:03d}" for i in range(325)]
    snap = cache / "canonical/moomoo_ohlcv/snapshot_id=active-325"
    write_csv(snap / module.CANON_RAW, rows("2026-07-15", "raw", universe))
    write_csv(snap / module.CANON_QFQ, rows("2026-07-15", "qfq", universe))
    write_pointer(repo, cache, snap, "active-325")
    v231 = repo / module.V231_REL
    (v231 / "abcde_expected_universe.csv").write_text("ticker\n" + "\n".join(universe) + "\n", encoding="utf-8")
    validation = module.validate_pointer(module.pointer_payload(cache, "active-325", snap), v231)
    assert validation["canonical_latest_date"] == "2026-07-15"
    assert validation["pointer_expected_universe_count"] == 325
    assert validation["pointer_eligible_universe_count"] == 325
    assert validation["pointer_raw_target_date_ticker_count"] == 325
    assert validation["pointer_qfq_target_date_ticker_count"] == 325
    assert validation["pointer_missing_eligible_raw_tickers"] == []
    assert validation["pointer_missing_eligible_qfq_tickers"] == []


def test_wrapper_must_not_report_pass_when_abcde_date_is_stale(tmp_path):
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"
    summary = module.run(
        repo,
        target_date="2026-07-08",
        cache_root=cache,
        fetch_runner=fetch_runner_factory(cache, "2026-07-08"),
        stage_runner=stage_runner_factory(stale_abcde=True),
    )
    assert summary["final_status"] == module.FAIL_STATUS
    assert summary["abcde_latest_date"] == "2026-07-01"
    assert summary["abcde_rerun_succeeded"] is False


def test_no_broker_or_trade_mutation_ever_allowed(tmp_path):
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"
    summary = module.run(
        repo,
        target_date="2026-07-08",
        cache_root=cache,
        fetch_runner=fetch_runner_factory(cache, "2026-07-08"),
        stage_runner=stage_runner_factory(broker_mutation=True),
    )
    assert summary["final_status"] == module.FAIL_STATUS
    assert summary["broker_action_allowed"] is False
    assert summary["official_adoption_allowed"] is False


def test_summary_exists_immediately_at_startup(tmp_path):
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"
    observed = {}

    def fetch_runner(**kwargs):
        summary_path = repo / module.OUT_REL / "v22_040_summary.json"
        observed["exists"] = summary_path.exists()
        observed["summary"] = json.loads(summary_path.read_text(encoding="utf-8"))
        raise SystemExit("stop after startup observation")

    summary = module.run(repo, target_date="2026-07-08", cache_root=cache, fetch_runner=fetch_runner)
    assert observed["exists"] is True
    assert observed["summary"]["final_status"] == module.RUNNING_STATUS
    assert observed["summary"]["run_start_utc"]
    assert summary["exception_type"] == "SystemExit"


def test_child_systemexit_still_leaves_final_summary(tmp_path):
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"

    def fetch_runner(**kwargs):
        raise SystemExit("child terminated parent if uncaught")

    summary = module.run(repo, target_date="2026-07-08", cache_root=cache, fetch_runner=fetch_runner)
    summary_path = repo / module.OUT_REL / "v22_040_summary.json"
    assert summary_path.exists()
    persisted = json.loads(summary_path.read_text(encoding="utf-8"))
    assert persisted["final_status"] == module.FAIL_STATUS
    assert persisted["exception_type"] == "SystemExit"
    assert persisted["failed_stage"] == "V21.231"
    assert persisted["run_end_utc"]
    assert persisted["elapsed_seconds"] >= 0


def test_child_nonzero_still_leaves_final_summary(tmp_path):
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"

    def fetch_runner(**kwargs):
        snap = make_snapshot(cache, "fetch", "2026-07-08")
        write_pointer(repo, cache, snap, "fetch")
        return {"final_status": "PASS_CHILD_BUT_EXIT_NONZERO", "_exit_code": 9, "broker_action_allowed": False, "official_adoption_allowed": False}

    summary = module.run(repo, target_date="2026-07-08", cache_root=cache, fetch_runner=fetch_runner)
    persisted = json.loads((repo / module.OUT_REL / "v22_040_summary.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == module.FAIL_CHILD_NONZERO
    assert persisted["final_status"] == module.FAIL_CHILD_NONZERO
    assert persisted["child_exit_codes"]["V21.231"] == 9
    assert persisted["failed_stage"] == "V21.231"


def test_child_summary_missing_fails_with_final_summary(tmp_path):
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"

    summary = module.run(
        repo,
        target_date="2026-07-08",
        cache_root=cache,
        fetch_runner=lambda **kwargs: {"final_status": "PASS_WITHOUT_DISK_SUMMARY", "broker_action_allowed": False, "official_adoption_allowed": False},
    )
    persisted = json.loads((repo / module.OUT_REL / "v22_040_summary.json").read_text(encoding="utf-8"))
    assert summary["final_status"] == module.FAIL_CHILD_SUMMARY_MISSING
    assert persisted["failed_stage"] == "V21.231"
    assert "CHILD_SUMMARY_MISSING" in persisted["exception_message"]


def test_wrapper_prints_final_summary_path_even_on_nonzero_exit(tmp_path):
    repo = tmp_path / "empty_repo"
    repo.mkdir()
    proc = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(MODULE_PATH.with_name("run_v22_040_daily_moomoo_oneclick_refresh_orchestrator_r1.ps1")),
            "-Execute",
            "-RepoRoot",
            str(repo),
        ],
        text=True,
        capture_output=True,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode != 0
    assert "final_summary_path=" in output
    assert "summary_exists=" in output


def test_running_heartbeat_fields_are_written_before_v21_231_completes(tmp_path):
    repo = tmp_path / "repo"
    cache = tmp_path / "cache"
    observed = {}

    def fetch_runner(**kwargs):
        payload = json.loads((repo / module.OUT_REL / "v22_040_summary.json").read_text(encoding="utf-8"))
        observed.update(payload)
        raise SystemExit("stop during v21.231")

    module.run(repo, target_date="2026-07-08", cache_root=cache, fetch_runner=fetch_runner)
    assert observed["current_stage"] == "V21.231"
    assert observed["last_heartbeat_utc"]
    assert observed["stage_attempted"] is True
    assert observed["broker_action_allowed"] is False
    assert observed["official_adoption_allowed"] is False


def test_post_supersession_hook_not_called_when_promotion_fails(tmp_path):
    repo, cache = tmp_path / "repo", tmp_path / "cache"
    calls = []
    summary = module.run(
        repo,
        target_date="2026-07-08",
        cache_root=cache,
        fetch_runner=fetch_runner_factory(cache, "2026-07-08", qfq=False),
        dedup_runner=lambda **kwargs: calls.append(kwargs) or {"status": "PASS"},
    )
    assert summary["final_status"] == module.FAIL_STATUS
    assert calls == []


def test_hook_receives_pre_refresh_current_only_after_valid_promotion(tmp_path):
    repo, cache = tmp_path / "repo", tmp_path / "cache"
    old_current = make_promoted_snapshot(cache, "20260701_000000_000001", "2026-07-07")
    write_pointer(repo, cache, old_current, old_current.name.removeprefix("snapshot_id="))
    observed = {}

    def dedup_runner(**kwargs):
        observed.update(kwargs)
        return {"status": "NO_EXACT_DUPLICATE", "files_hashed": 0}

    summary = module.run(
        repo,
        target_date="2026-07-08",
        cache_root=cache,
        fetch_runner=fetch_runner_factory(cache, "2026-07-08"),
        stage_runner=stage_runner_factory(),
        dedup_runner=dedup_runner,
    )
    assert summary["final_status"] == module.PASS_STATUS
    assert observed["superseded_snapshot"].resolve() == old_current.resolve()
    assert observed["current_snapshot"].resolve() != old_current.resolve()
    assert summary["post_supersession_dedup_status"] == "NO_EXACT_DUPLICATE"


def test_disabled_post_supersession_hook_preserves_existing_flow(tmp_path):
    repo, cache = tmp_path / "repo", tmp_path / "cache"
    calls = []
    summary = module.run(
        repo,
        target_date="2026-07-08",
        cache_root=cache,
        fetch_runner=fetch_runner_factory(cache, "2026-07-08"),
        stage_runner=stage_runner_factory(),
        dedup_runner=lambda **kwargs: calls.append(kwargs) or {"status": "PASS"},
        post_supersession_dedup_enabled=False,
    )
    assert summary["final_status"] == module.PASS_STATUS
    assert summary["post_supersession_dedup_status"] == "DISABLED"
    assert calls == []


def test_dedup_permission_exception_does_not_reclassify_committed_promotion(tmp_path):
    repo, cache = tmp_path / "repo", tmp_path / "cache"
    old_current = make_promoted_snapshot(cache, "20260701_000000_000001", "2026-07-07")
    write_pointer(repo, cache, old_current, old_current.name.removeprefix("snapshot_id="))

    def permission_failure(**kwargs):
        raise PermissionError("synthetic closeout denial")

    summary = module.run(
        repo,
        target_date="2026-07-08",
        cache_root=cache,
        fetch_runner=fetch_runner_factory(cache, "2026-07-08"),
        stage_runner=stage_runner_factory(),
        dedup_runner=permission_failure,
    )
    assert summary["final_status"] == module.PASS_STATUS
    assert summary["canonical_pointer_updated"] is True
    assert summary["post_supersession_dedup_status"] == "SKIPPED_OPERATIONAL_EXCEPTION"
    assert "PermissionError" in summary["post_supersession_dedup_reason"]


def test_dedup_integrity_anomaly_is_surfaced_without_touching_new_current(tmp_path):
    repo, cache = tmp_path / "repo", tmp_path / "cache"
    old_current = make_promoted_snapshot(cache, "20260701_000000_000001", "2026-07-07")
    write_pointer(repo, cache, old_current, old_current.name.removeprefix("snapshot_id="))
    summary = module.run(
        repo,
        target_date="2026-07-08",
        cache_root=cache,
        fetch_runner=fetch_runner_factory(cache, "2026-07-08"),
        stage_runner=stage_runner_factory(),
        dedup_runner=lambda **kwargs: {
            "status": "FAIL_INTEGRITY",
            "reason": "synthetic historical rollback failure",
            "integrity_anomaly": True,
        },
    )
    assert summary["final_status"] == module.PASS_STATUS
    assert summary["canonical_pointer_updated"] is True
    assert summary["post_supersession_dedup_status"] == "FAIL_INTEGRITY"
    assert summary["post_supersession_dedup_integrity_anomaly"] is True


def test_normal_changed_snapshot_fast_rejects_without_payload_hash(tmp_path):
    cache = tmp_path / "cache"
    target = make_promoted_snapshot(cache, "20260702_000000_000001")
    source = make_promoted_snapshot(cache, "20260701_000000_000001")
    current = make_promoted_snapshot(cache, "20260703_000000_000001")
    with (source / module.CANON_RAW).open("a", encoding="utf-8") as handle:
        handle.write("extra,row,makes,size,different\n")
    result = module.dedup_superseded_snapshot(
        target, target.parent, current, candidate_dirs=[source, current]
    )
    assert result["status"] == "NO_EXACT_DUPLICATE"
    assert result["files_hashed"] == 0
    assert result["duration_ms"] >= 0


def test_exact_retry_dedups_preserves_paths_manifest_and_current(tmp_path):
    cache = tmp_path / "cache"
    source = make_promoted_snapshot(cache, "20260701_000000_000001")
    target = make_promoted_snapshot(cache, "20260702_000000_000001")
    current = make_promoted_snapshot(cache, "20260703_000000_000001", "2026-07-09")
    manifest_before = module.sha256_file(target / "canonical_manifest.json")
    current_before = [_identity(current / name) for name in (module.CANON_RAW, module.CANON_QFQ)]
    result = module.dedup_superseded_snapshot(
        target, target.parent, current, candidate_dirs=[source, current]
    )
    assert result["status"] == "PASS"
    assert result["converted_file_count"] == 2
    assert all((target / name).exists() and os.path.samefile(source / name, target / name)
               for name in (module.CANON_RAW, module.CANON_QFQ))
    assert module.sha256_file(target / "canonical_manifest.json") == manifest_before
    assert [_identity(current / name) for name in (module.CANON_RAW, module.CANON_QFQ)] == current_before
    assert result["current_canonical_hardlink_participation_count"] == 0


def _identity(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino


def test_current_with_same_hash_is_excluded_and_stays_independent(tmp_path):
    cache = tmp_path / "cache"
    source = make_promoted_snapshot(cache, "20260701_000000_000001")
    target = make_promoted_snapshot(cache, "20260702_000000_000001")
    current = make_promoted_snapshot(cache, "20260703_000000_000001")
    before = [_identity(current / name) for name in (module.CANON_RAW, module.CANON_QFQ)]
    result = module.dedup_superseded_snapshot(
        target, target.parent, current, candidate_dirs=[current, source]
    )
    assert result["status"] == "PASS"
    assert result["source_snapshot"] == str(source)
    assert [_identity(current / name) for name in (module.CANON_RAW, module.CANON_QFQ)] == before
    assert not any(os.path.samefile(current / name, source / name) for name in (module.CANON_RAW, module.CANON_QFQ))


def test_metadata_mismatch_fails_closed(tmp_path):
    cache = tmp_path / "cache"
    source = make_promoted_snapshot(cache, "20260701_000000_000001")
    target = make_promoted_snapshot(cache, "20260702_000000_000001")
    current = make_promoted_snapshot(cache, "20260703_000000_000001", "2026-07-09")
    result = module.dedup_superseded_snapshot(
        target,
        target.parent,
        current,
        candidate_dirs=[source],
        metadata_check=lambda source_path, target_path: False,
    )
    assert result["status"] == "SKIPPED_METADATA_INCOMPATIBLE"
    assert result["converted_file_count"] == 0


def test_permission_failure_is_nonfatal_and_other_targets_continue(tmp_path):
    cache = tmp_path / "cache"
    source = make_promoted_snapshot(cache, "20260701_000000_000001")
    target = make_promoted_snapshot(cache, "20260702_000000_000001")
    current = make_promoted_snapshot(cache, "20260703_000000_000001", "2026-07-09")
    calls = []

    def transaction(source_path, target_path, expected_hash):
        calls.append(target_path)
        if len(calls) == 1:
            return {"status": "SKIPPED_PERMISSION", "bytes_reclaimed": 0}
        return module._transactional_hardlink_replace(source_path, target_path, expected_hash)

    result = module.dedup_superseded_snapshot(
        target, target.parent, current, candidate_dirs=[source], transaction=transaction
    )
    assert result["status"] == "PASS_WITH_OPERATIONAL_SKIPS"
    assert result["converted_file_count"] == 1
    assert result["skipped_file_count"] == 1


def test_hash_change_before_transaction_is_safely_skipped(tmp_path):
    cache = tmp_path / "cache"
    source = make_promoted_snapshot(cache, "20260701_000000_000001")
    target = make_promoted_snapshot(cache, "20260702_000000_000001")
    current = make_promoted_snapshot(cache, "20260703_000000_000001", "2026-07-09")
    calls = []

    def changed_transaction(source_path, target_path, expected_hash):
        calls.append(target_path)
        return {"status": "SKIPPED_CHANGED", "bytes_reclaimed": 0}

    result = module.dedup_superseded_snapshot(
        target, target.parent, current, candidate_dirs=[source], transaction=changed_transaction
    )
    assert len(calls) == 2
    assert result["converted_file_count"] == 0
    assert result["status"] == "SKIPPED_OPERATIONAL"


def test_transaction_rolls_back_after_post_replace_validation_failure(tmp_path):
    source, target = tmp_path / "source.bin", tmp_path / "target.bin"
    source.write_bytes(b"same bytes")
    target.write_bytes(b"same bytes")
    target_identity = _identity(target)

    def fail_validation(source_path, target_path):
        raise RuntimeError("synthetic post-replace failure")

    result = module._transactional_hardlink_replace(
        source, target, module.sha256_file(source), after_replace=fail_validation
    )
    assert result["status"] == "SKIPPED_ROLLED_BACK"
    assert _identity(target) == target_identity
    assert target.read_bytes() == b"same bytes"


def test_transaction_surfaces_rollback_failure_and_preserves_recovery_link(tmp_path):
    source, target = tmp_path / "source.bin", tmp_path / "target.bin"
    source.write_bytes(b"same bytes")
    target.write_bytes(b"same bytes")
    calls = 0

    def replace(source_path, target_path):
        nonlocal calls
        calls += 1
        if calls == 1:
            os.replace(source_path, target_path)
        else:
            raise PermissionError("synthetic rollback denial")

    result = module._transactional_hardlink_replace(
        source,
        target,
        module.sha256_file(source),
        replace=replace,
        after_replace=lambda source_path, target_path: (_ for _ in ()).throw(RuntimeError("fail")),
    )
    rollback = target.with_name(f".{target.name}.post_dedup_rollback.tmp")
    assert result["status"] == "FAIL_INTEGRITY"
    assert rollback.exists()
    os.replace(rollback, target)


def test_second_execution_is_idempotent(tmp_path):
    cache = tmp_path / "cache"
    source = make_promoted_snapshot(cache, "20260701_000000_000001")
    target = make_promoted_snapshot(cache, "20260702_000000_000001")
    current = make_promoted_snapshot(cache, "20260703_000000_000001", "2026-07-09")
    first = module.dedup_superseded_snapshot(target, target.parent, current, candidate_dirs=[source])
    second = module.dedup_superseded_snapshot(target, target.parent, current, candidate_dirs=[source])
    assert first["converted_file_count"] == 2
    assert second["status"] == "ALREADY_SHARED"
    assert second["converted_file_count"] == 0


def test_interrupted_transaction_recovers_from_filesystem_identity(tmp_path):
    source, target = tmp_path / "source.bin", tmp_path / "target.bin"
    source.write_bytes(b"same bytes")
    target.write_bytes(b"same bytes")
    temp_link = target.with_name(f".{target.name}.post_dedup_link.tmp")
    rollback_link = target.with_name(f".{target.name}.post_dedup_rollback.tmp")
    os.link(source, temp_link)
    os.link(target, rollback_link)
    os.replace(temp_link, target)  # simulated interruption before rollback cleanup
    result = module._transactional_hardlink_replace(source, target, module.sha256_file(source))
    assert result["status"] == "ALREADY_CONVERTED_RECOVERED"
    assert os.path.samefile(source, target)
    assert not rollback_link.exists()


def test_dry_run_has_zero_filesystem_mutation(tmp_path):
    cache = tmp_path / "cache"
    source = make_promoted_snapshot(cache, "20260701_000000_000001")
    target = make_promoted_snapshot(cache, "20260702_000000_000001")
    current = make_promoted_snapshot(cache, "20260703_000000_000001", "2026-07-09")
    identities = [_identity(target / name) for name in (module.CANON_RAW, module.CANON_QFQ)]
    result = module.dedup_superseded_snapshot(
        target, target.parent, current, dry_run=True, candidate_dirs=[source]
    )
    assert result["status"] == "DRY_RUN_EXACT_DUPLICATE"
    assert result["would_convert_file_count"] == 2
    assert result["converted_file_count"] == 0
    assert [_identity(target / name) for name in (module.CANON_RAW, module.CANON_QFQ)] == identities


def test_candidate_scope_is_explicit_and_never_scans_unrelated_cache(tmp_path):
    cache = tmp_path / "cache"
    source = make_promoted_snapshot(cache, "20260701_000000_000001")
    target = make_promoted_snapshot(cache, "20260702_000000_000001")
    current = make_promoted_snapshot(cache, "20260703_000000_000001", "2026-07-09")
    unrelated = cache / "large_unrelated_namespace"
    unrelated.mkdir(parents=True)
    (unrelated / "must_not_be_read.bin").write_bytes(b"unrelated")
    result = module.dedup_superseded_snapshot(
        target, target.parent, current, dry_run=True, candidate_dirs=[source]
    )
    assert result["status"] == "DRY_RUN_EXACT_DUPLICATE"
    assert unrelated.joinpath("must_not_be_read.bin").read_bytes() == b"unrelated"


def test_synthetic_promotion_keeps_new_current_physically_isolated(tmp_path):
    repo, cache = tmp_path / "repo", tmp_path / "cache"
    historical_0 = make_promoted_snapshot(cache, "20260701_000000_000001")
    current_1 = make_promoted_snapshot(cache, "20260702_000000_000001")
    write_pointer(repo, cache, current_1, current_1.name.removeprefix("snapshot_id="))
    summary = module.run(
        repo,
        target_date="2026-07-08",
        cache_root=cache,
        fetch_runner=fetch_runner_factory(cache, "2026-07-08", snapshot_id="staging_2"),
        stage_runner=stage_runner_factory(),
    )
    new_current = Path(json.loads((repo / module.V231_REL / "canonical_snapshot_pointer.json").read_text(encoding="utf-8"))["canonical_snapshot_dir"])
    assert summary["final_status"] == module.PASS_STATUS
    assert summary["post_supersession_dedup_status"] == "PASS"
    assert all(os.path.samefile(historical_0 / name, current_1 / name) for name in (module.CANON_RAW, module.CANON_QFQ))
    assert not any(os.path.samefile(new_current / name, current_1 / name) for name in (module.CANON_RAW, module.CANON_QFQ))
    assert all((current_1 / name).exists() and (new_current / name).exists() for name in (module.CANON_RAW, module.CANON_QFQ))
