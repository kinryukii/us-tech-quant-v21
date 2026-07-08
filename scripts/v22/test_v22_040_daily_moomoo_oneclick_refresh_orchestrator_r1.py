from __future__ import annotations

import csv
import importlib.util
import json
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
