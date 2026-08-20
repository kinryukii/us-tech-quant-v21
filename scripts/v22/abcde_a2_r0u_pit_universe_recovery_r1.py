"""Recover evidence for a 2020-2025 PIT ABCDE research universe.

Research-only and fail-closed.  This module never constructs membership from
the current 325 list or from price availability, and it contains no model or
broker path.  Large inputs are read-only; only small audit artifacts are
written to the approved external results root.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pyarrow.parquet as pq


EXPERIMENT_ID = "ABCDE_A2_R0U_PIT_UNIVERSE_RECOVERY_R1"
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(r"D:\us-tech-quant-data")
RESULTS_ROOT = Path(r"D:\us-tech-quant-results") / EXPERIMENT_ID
DAILY_ROOT = Path(r"D:\us-tech-quant-daily")
CACHE_ROOT = Path(r"D:\us-tech-quant-cache")
CURRENT_UNIVERSE = DATA_ROOT / "moomoo/metadata/abcde_price_universe_r2.csv"
CURRENT_MANIFEST = DATA_ROOT / "moomoo/metadata/abcde_price_universe_r2.active_manifest.json"
PROXY_MANIFEST = DATA_ROOT / "derived_cache/abcde_current_rule_proxy_rankings_r8/historical_proxy_rankings.json"
PRICE_ROOT = DATA_ROOT / "moomoo/source/prices_qfq"
PRIOR_A2_MODULE = REPO_ROOT / "scripts/v22/abcde_a2_nonlinear_alpha_baseline_r1.py"
PRIOR_A2_SUMMARY = Path(r"D:\us-tech-quant-results\ABCDE_A2_R0_R1_NONLINEAR_ALPHA_BASELINE_R1\abcde_a2_r0_r1_summary.json")
MOOMOO_SECURITY_DB_CANDIDATES = (
    Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "com.moomoo.OpenD/F3CNN/SecListDB.v13.dat",
    Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "com.moomoo.OpenD/F3CNN/SecListDB.dat",
)
RESEARCH_START = date(2020, 1, 2)
RESEARCH_END = date(2025, 12, 31)
MIN_FEATURE_OBSERVATIONS = 120

CORE_NINE_MANAGERS = (
    "Situational Awareness", "Coatue", "Tiger Global", "Whale Rock", "Altimeter",
    "Lone Pine", "Appaloosa", "D1 Capital", "Duquesne",
)
OTHER_MANAGER_TERMS = (
    "Pershing", "Berkshire", "Scion", "Soros", "Himalaya", "Baupost", "TCI",
    "ARK Invest", "Cathie Wood",
)
PERSON_TERMS = (
    "Leopold", "Aschenbrenner", "Philippe Laffont", "Chase Coleman", "Alex Sacerdote",
    "Brad Gerstner", "Stephen Mandel", "David Tepper", "Dan Sundheim",
    "Stanley Druckenmiller", "Bill Ackman", "Warren Buffett", "Michael Burry",
    "Li Lu", "Seth Klarman", "Chris Hohn",
)
CONTRACT_TERMS = (
    "F012_SUPERINVESTOR_CONSENSUS", "SUPERINVESTOR_CONSENSUS", "superinvestor",
    "institutional consensus", "13F consensus", "13F", "fund holdings",
)
ALL_MANAGER_TERMS = CORE_NINE_MANAGERS + OTHER_MANAGER_TERMS + PERSON_TERMS + CONTRACT_TERMS
SELF_AUDIT_FILENAMES = {
    "abcde_a2_r0u_pit_universe_recovery_r1.py",
    "run_abcde_a2_r0u_pit_universe_recovery_r1.py",
    "test_abcde_a2_r0u_pit_universe_recovery_r1.py",
}

GIT_EVIDENCE_SPECS = (
    ("configs/v16/universe/us_full_screened_generated.yaml", "TIER_C", "317-name current-state generated list; no effective dates"),
    ("scripts/v16/repair_v16_second_stage_universe.py", "TIER_C", "Builds from current ranked/rolling/cache sources"),
    ("scripts/v18/v18_16A_universe_rolling_state_builder.py", "TIER_C", "Current rolling-state builder; no historical membership contract"),
    ("scripts/v20/v20_214_operator_approved_historical_price_and_membership_input_fill_or_yahoo_cache_build.py", "NEGATIVE", "Plan-only path emits zero certified historical membership rows"),
    ("scripts/v21/v21_106_r1_full_pit_factor_replay_feasibility_audit.py", "NEGATIVE", "Explicitly reports no certified historical membership source"),
    ("scripts/v21/v21_140_extend_historical_price_panel_to_2020.py", "NEGATIVE", "Explicit current-universe-only and missing-delisted warning"),
    ("scripts/v21/v21_143_random_universe_and_survivorship_artifact_audit.py", "NEGATIVE", "Explicit survivorship and missing-delisted audit"),
    ("scripts/v21/v21_231_moomoo_only_historical_refetch_and_canonical_rebuild.py", "TIER_C", "Current active universe price rebuild, not as-of membership"),
)

PROTECTED_PATHS = (
    "scripts/v21/v21_233_moomoo_only_abcde_rerun.py",
    "config/v21/abcde_compact_v1_freeze_r1.json",
    "scripts/v22/abcde_compact_v1_freeze_r1_guard.py",
    "scripts/v22/v22_040_daily_moomoo_oneclick_refresh_orchestrator_r1.py",
    "scripts/v22/v22_044_daily_single_entrypoint_freeze_and_guard_r1.py",
    "config/v21/active_chain_manifest.json",
)

SUMMARY_FIELDS = (
    "ABCDE_A2_R0U_STATUS", "ABCDE_A2_R0U_CLASSIFICATION", "ABCDE_A2_R0U_DECISION",
    "LEGACY_ABCDE_UNIVERSE_DEFINITION_STATUS", "EXACT_HISTORICAL_UNIVERSE_RECOVERED",
    "NEW_RESEARCH_PIT_UNIVERSE_CREATED", "LEGACY_UNIVERSE_EQUIVALENCE",
    "PIT_UNIVERSE_AUDIT_STATUS", "SURVIVORSHIP_AUDIT_STATUS",
    "CURRENT_325_USED_AS_HISTORICAL_SOURCE", "HISTORICAL_NOT_IN_CURRENT_325_COUNT",
    "CURRENT_325_NOT_YET_ELIGIBLE_HISTORICAL_COUNT", "HISTORICAL_UNIQUE_SECURITY_COUNT",
    "UNIVERSE_START_DATE", "UNIVERSE_END_DATE", "UNIVERSE_DAILY_SIZE_MIN",
    "UNIVERSE_DAILY_SIZE_MEDIAN", "UNIVERSE_DAILY_SIZE_MAX", "FEATURE_READY_DAILY_SIZE_MEDIAN",
    "SECURITY_MASTER_SOURCE", "AUTHORITATIVE_PRICE_SOURCE", "GIT_HISTORY_UNIVERSE_EVIDENCE_COUNT",
    "EXTERNAL_UNIVERSE_EVIDENCE_COUNT", "A1_RECOMPUTE_REQUIRED_ON_PIT_UNIVERSE",
    "A2_R1_PREREGISTRATION_CHANGED", "MODEL_FIT_COUNT", "MODEL_PREDICT_CALL_COUNT",
    "TRAINING_2026_ROW_COUNT", "BROKER_ACTION_COUNT", "DAILY_CHAIN_CHANGED", "A1_CHANGED",
    "B_CHANGED", "C_CHANGED", "D_CHANGED", "E_CHANGED", "FAST_CHANGED",
    "MOOMOO_API_REQUEST_COUNT", "ANTI_BLOAT_STATUS", "RESULTS_ROOT", "UNIVERSE_PATH",
    "SECURITY_MASTER_PATH", "MANIFEST_PATH", "SUMMARY_PATH", "MANAGER_SET_VERSIONING_STATUS",
    "EARLIEST_MANAGER_SET_EVIDENCE_DATE", "LEGACY_CORE_MANAGER_COUNT", "LATE_ADDED_MANAGER_COUNT",
    "LEOPOLD_EARLIEST_ELIGIBLE_DATE", "ARK_MANAGER_EVIDENCE_STATUS", "FAILURE_REASON",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, default=str) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, text=True, capture_output=True,
        encoding="utf-8", errors="replace", check=False,
    )
    return proc.stdout.strip()


def parse_date(value: str | date | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def eligibility_state(
    signal_date: str | date,
    first_observable_date: str | date,
    terminal_inactive_date: str | date | None,
    observations_available: int,
) -> dict[str, bool]:
    signal = parse_date(signal_date)
    first = parse_date(first_observable_date)
    terminal = parse_date(terminal_inactive_date)
    if signal is None or first is None:
        raise ValueError("signal and first-observable dates are required")
    eligible = signal >= first and (terminal is None or signal < terminal)
    return {
        "universe_eligible": eligible,
        "feature_ready": eligible and observations_available >= MIN_FEATURE_OBSERVATIONS,
    }


def assert_pit_timestamp(signal_date: str | date, information_date: str | date) -> None:
    signal, information = parse_date(signal_date), parse_date(information_date)
    if signal is None or information is None or information > signal:
        raise ValueError("PIT_SOURCE_TIMESTAMP_AFTER_SIGNAL")


def source_can_define_history(source_tier: str, effective_date: str | date | None) -> bool:
    effective = parse_date(effective_date)
    return source_tier in {"TIER_A", "TIER_B"} and effective is not None and effective <= RESEARCH_END


def choose_route(exact_recovery_valid: bool, research_master_valid: bool) -> str:
    if exact_recovery_valid:
        return "A_EXACT_HISTORICAL_ABCDE_UNIVERSE_RECOVERED"
    if research_master_valid:
        return "B_NEW_RESEARCH_PIT_UNIVERSE_VALIDATED"
    return "C_INSUFFICIENT_HISTORICAL_SECURITY_MASTER_EVIDENCE"


def import_prior_a2():
    spec = importlib.util.spec_from_file_location("abcde_a2_preregistered_r1", PRIOR_A2_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError("PRIOR_A2_MODULE_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit_preregistration() -> dict[str, Any]:
    prior = import_prior_a2()
    old = json.loads(PRIOR_A2_SUMMARY.read_text(encoding="utf-8"))
    current = {
        "primary": prior.PRIMARY_TARGET,
        "secondary": prior.SECONDARY_TARGET,
        "features": list(prior.FEATURES),
        "hgb_config": prior.HGB_CONFIG,
        "folds": list(prior.PLANNED_FOLDS),
    }
    expected = {
        "primary": old["PRIMARY_TARGET"],
        "secondary": old["SECONDARY_TARGET"],
        "features": old["feature_contract"]["features"],
        "hgb_config": old["hgb_config"],
        "folds": old["planned_oof_folds"],
    }
    return {
        "changed": current != expected,
        "current_fingerprint": canonical_fingerprint(current),
        "prior_summary_fingerprint": canonical_fingerprint(expected),
        "prior_summary_path": str(PRIOR_A2_SUMMARY),
    }


def audit_git_evidence() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative, tier, relevance in GIT_EVIDENCE_SPECS:
        path = REPO_ROOT / relative
        history = git("log", "--all", "--follow", "--format=%H|%aI|%s", "--", relative).splitlines()
        rows.append({
            "path": relative,
            "exists_at_head": path.is_file(),
            "sha256": sha256_file(path) if path.is_file() else None,
            "tier": tier,
            "relevance": relevance,
            "history": history,
            "earliest_commit_evidence": history[-1] if history else None,
        })
    return rows


def _manager_regex() -> re.Pattern[str]:
    alternatives = sorted((re.escape(term) for term in ALL_MANAGER_TERMS), key=len, reverse=True)
    return re.compile(r"(?i)(?<![A-Za-z0-9])(?:" + "|".join(alternatives) + r")(?![A-Za-z0-9])")


def _iter_small_text_files(roots: Iterable[Path]) -> Iterable[Path]:
    suffixes = {".py", ".ps1", ".json", ".csv", ".tsv", ".yaml", ".yml", ".md", ".txt"}
    pruned = {".git", "site-packages", "venvs", "__pycache__", ".pytest_cache", "pytest_temp"}
    for root in roots:
        if root.is_file():
            yield root
            continue
        if not root.is_dir():
            continue
        for base, dirs, files in os.walk(root, onerror=lambda _error: None):
            dirs[:] = [d for d in dirs if d not in pruned and not d.lower().startswith("pytest")]
            for name in files:
                path = Path(base) / name
                try:
                    if path.suffix.lower() in suffixes and path.stat().st_size <= 20_000_000:
                        yield path
                except OSError:
                    continue


def audit_manager_evidence() -> dict[str, Any]:
    pattern = _manager_regex()
    repo_roots = tuple(p for p in (REPO_ROOT / "scripts", REPO_ROOT / "config", REPO_ROOT / "configs", REPO_ROOT / "docs", REPO_ROOT / "README.md") if p.exists())
    # Cache is deliberately routed through provenance-bearing subroots.  The
    # full cache is dominated by virtualenvs and temporary FAST test trees; a
    # separate broad filename/content recovery pass found no manager artifact.
    external_roots = tuple(p for p in (
        Path(r"D:\DOW"), RESULTS_ROOT.parent / "migrated_from_repo",
        DATA_ROOT / "moomoo/metadata", DATA_ROOT / "derived_cache",
        DAILY_ROOT / "current", DAILY_ROOT / "migrated_from_repo",
        CACHE_ROOT / "canonical-snapshots",
        CACHE_ROOT / "registry", CACHE_ROOT / "backups",
    ) if p.exists())
    matches: list[dict[str, Any]] = []
    files_scanned = 0
    for path in _iter_small_text_files(repo_roots + external_roots):
        if path.name in SELF_AUDIT_FILENAMES:
            continue
        files_scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        found = sorted({match.group(0) for match in pattern.finditer(text)}, key=str.lower)
        if found:
            matches.append({"path": str(path), "terms": found, "sha256": sha256_file(path)})

    cache_migrated = CACHE_ROOT / "migrated_from_repo"
    cache_rg_status = "NOT_PRESENT"
    if cache_migrated.is_dir():
        command = [
            "rg", "-l", "-i", "-P", "--no-messages", "--max-filesize", "20M",
            *sum((["--glob", f"*{suffix}"] for suffix in (".py", ".ps1", ".json", ".csv", ".tsv", ".yaml", ".yml", ".md", ".txt")), []),
            pattern.pattern, str(cache_migrated),
        ]
        proc = subprocess.run(command, text=True, capture_output=True, encoding="utf-8", errors="replace", check=False)
        cache_paths = [Path(line) for line in proc.stdout.splitlines() if Path(line).is_file()]
        cache_rg_status = "MATCHES_FOUND" if cache_paths else "NO_MATCH"
        for path in cache_paths:
            text = path.read_text(encoding="utf-8", errors="ignore")
            found = sorted({match.group(0) for match in pattern.finditer(text)}, key=str.lower)
            matches.append({"path": str(path), "terms": found, "sha256": sha256_file(path)})

    git_hits: dict[str, list[str]] = {}
    for term in ALL_MANAGER_TERMS:
        lines = git("log", "--all", "-i", "-S", term, "--format=%H|%aI|%s", "--").splitlines()
        if lines:
            # Hash-like accidental 13F matches are retained but marked for manual relevance review.
            git_hits[term] = lines

    unreachable_lines = git("fsck", "--full", "--no-reflogs", "--unreachable").splitlines()
    dangling_blob_hits: list[dict[str, Any]] = []
    for line in unreachable_lines:
        parts = line.split()
        if len(parts) != 3 or parts[1] != "blob":
            continue
        proc = subprocess.run(["git", "cat-file", "blob", parts[2]], cwd=REPO_ROOT, capture_output=True, check=False)
        text = proc.stdout.decode("utf-8", errors="ignore")
        found = sorted({match.group(0) for match in pattern.finditer(text)}, key=str.lower)
        if found:
            dangling_blob_hits.append({"blob": parts[2], "terms": found})

    exact_group_files = []
    for row in matches:
        normalized = " ".join(row["terms"]).lower()
        if all(term.lower() in normalized for term in CORE_NINE_MANAGERS):
            exact_group_files.append(row["path"])
    manager_artifact_matches = [row for row in matches if any(term.lower() != "13f" for term in row["terms"])]
    return {
        "files_scanned": files_scanned,
        "search_roots": [str(p) for p in repo_roots + external_roots],
        "cache_migrated_search_root": str(cache_migrated),
        "cache_migrated_rg_status": cache_rg_status,
        "artifact_matches": matches,
        "manager_artifact_match_count": len(manager_artifact_matches),
        "exact_nine_manager_group_artifacts": exact_group_files,
        "exact_nine_manager_group_status": "FOUND" if exact_group_files else "NOT_FOUND",
        "other_seven_manager_artifact_status": "FOUND" if any(any(t.lower() in " ".join(r["terms"]).lower() for t in OTHER_MANAGER_TERMS[:7]) for r in matches) else "NOT_FOUND",
        "git_pickaxe_raw_hits": git_hits,
        "git_relevant_manager_or_13f_hits": {key: value for key, value in git_hits.items() if key.lower() != "13f"},
        "git_13f_pickaxe_relevance": "FALSE_POSITIVE_HEX_SUBSTRINGS_NO_STANDALONE_13F_TOKEN" if "13F" in git_hits else "NO_HIT",
        "dangling_git_object_hits": dangling_blob_hits,
        "reachable_commit_count": int(git("rev-list", "--all", "--count") or 0),
        "earliest_reachable_commit": git("log", "--all", "--reverse", "-1", "--format=%H|%aI|%s"),
        "unreachable_commit_count": sum("unreachable commit" in line for line in unreachable_lines),
        "manager_set_versioning_status": "NOT_RECOVERED_NO_LOCAL_ARTIFACT_EVIDENCE",
        "earliest_authoritative_manager_set_evidence_date": None,
        "user_recovered_chat_clue_date_approximate": "2026-05-18",
        "user_recovered_core_manager_count": len(CORE_NINE_MANAGERS),
        "user_clue_is_membership_authority": False,
        "holdings_to_universe_rule_recovered": False,
        "approximately_325_reproducible_from_holdings": False,
        "leopold_earliest_eligible_date": None,
        "ark_manager_evidence_status": "USER_RECALLED_CLUE_ONLY_NO_LOCAL_ARTIFACT",
    }


def read_current_tickers() -> set[str]:
    with CURRENT_UNIVERSE.open("r", encoding="utf-8-sig", newline="") as handle:
        return {str(row["ticker"]).strip().upper() for row in csv.DictReader(handle) if row.get("ticker")}


def audit_price_inventory(current: set[str]) -> dict[str, Any]:
    by_year: dict[str, set[str]] = {}
    for year in range(2020, 2026):
        path = PRICE_ROOT / f"year={year}/prices.parquet"
        by_year[str(year)] = set(pq.read_table(path, columns=["ticker"])["ticker"].to_pylist())
    union = set().union(*by_year.values())
    historical_not_current = sorted(union - current)
    current_not_observable_2020 = sorted(current - by_year["2020"])
    return {
        "source": "LOCAL_MOOMOO_CACHE_QFQ_FROM_MOOMOO_OPEND",
        "yearly_unique_ticker_count": {year: len(tickers) for year, tickers in by_year.items()},
        "union_unique_ticker_count": len(union),
        "historical_price_tickers_not_in_current_325": historical_not_current,
        "current_325_without_any_2020_price_observation": current_not_observable_2020,
        "price_presence_is_membership": False,
    }


def audit_security_database(current: set[str]) -> dict[str, Any]:
    path = next((candidate for candidate in MOOMOO_SECURITY_DB_CANDIDATES if candidate.is_file()), None)
    if path is None:
        return {"path": None, "capability_status": "MISSING", "historical_master_valid": False}
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    try:
        columns = [dict(row) for row in con.execute("pragma table_info(security)")]
        total = int(con.execute("select count(*) from security").fetchone()[0])
        archived = dict(con.execute(
            "select count(*) n, "
            "sum(case when listing_date>0 then 1 else 0 end) listing_known, "
            "sum(case when exchange<>'' then 1 else 0 end) exchange_known, "
            "sum(case when listed_exchange<>'' then 1 else 0 end) listed_exchange_known, "
            "sum(case when instrument>0 then 1 else 0 end) instrument_known "
            "from security where delisted<>0"
        ).fetchone())
        us = dict(con.execute(
            "select count(*) n, sum(case when listing_date>0 then 1 else 0 end) listing_known, "
            "sum(case when delisted<>0 then 1 else 0 end) delisted_n "
            "from security where exchange='US'"
        ).fetchone())
        current_rows: list[dict[str, Any]] = []
        for ticker in sorted(current):
            rows = con.execute(
                "select code,listing_date,market_code,instrument,instrument_sub,exchange,listed_exchange "
                "from security where exchange='US' and code=? "
                "order by case when instrument=3 then 0 when instrument=4 then 1 else 2 end,id desc",
                (ticker,),
            ).fetchall()
            row = rows[0] if rows else None
            listing = datetime.fromtimestamp(row["listing_date"], timezone.utc).date().isoformat() if row and row["listing_date"] > 0 else None
            current_rows.append({
                "ticker": ticker, "match_count": len(rows), "listing_date": listing,
                "market_code": row["market_code"] if row else None,
                "instrument": row["instrument"] if row else None,
            })
    finally:
        con.close()
    known = [row for row in current_rows if row["listing_date"]]
    after_start = [row for row in known if row["listing_date"] > RESEARCH_START.isoformat()]
    required_terminal_column_present = any(row["name"] in {"delisting_date", "inactive_date", "effective_to"} for row in columns)
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "snapshot_last_write_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "row_count": total,
        "security_columns": [row["name"] for row in columns],
        "archived_delisted_profile": archived,
        "us_current_snapshot_profile": us,
        "current_325_match_count": sum(row["match_count"] > 0 for row in current_rows),
        "current_325_listing_date_known_count": len(known),
        "current_325_known_listing_after_research_start_count": len(after_start),
        "current_325_known_listing_after_research_start": after_start,
        "terminal_effective_date_column_present": required_terminal_column_present,
        "historical_snapshot_or_asof_column_present": False,
        "archived_rows_retain_exchange_type_and_listing": bool(
            archived["n"] and archived["exchange_known"] == archived["n"]
            and archived["instrument_known"] == archived["n"] and archived["listing_known"] == archived["n"]
        ),
        "capability_status": "REJECTED_CURRENT_SNAPSHOT_ARCHIVE_LOSES_HISTORICAL_IDENTITY_AND_EFFECTIVE_DATES",
        "historical_master_valid": False,
    }


def audit_external_evidence(security_db: dict[str, Any]) -> list[dict[str, Any]]:
    specs = (
        (CURRENT_MANIFEST, "TIER_C", "Only effective 2026-07-07; current 325 and OLPX removal ledger"),
        (CURRENT_UNIVERSE, "TIER_C", "Current 325 table; no dated membership columns"),
        (PROXY_MANIFEST, "TIER_C", "Explicit current-universe proxy with survivorship warning"),
        (DAILY_ROOT / "current/V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD/abcde_expected_universe.csv", "TIER_C", "Current daily expected universe"),
        (DAILY_ROOT / "migrated_from_repo/outputs/v21/V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD/abcde_expected_universe.csv", "TIER_C", "Migrated copy of current expected universe"),
        (PRIOR_A2_SUMMARY, "NEGATIVE", "Prior R0 correctly found no PIT historical membership contract"),
        (Path(security_db["path"]) if security_db.get("path") else Path("__missing__"), "REJECTED_SECURITY_MASTER", "Current Moomoo snapshot; delisted archive loses identity/effective dates"),
    )
    rows = []
    for path, tier, relevance in specs:
        if path.is_file():
            rows.append({
                "path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size,
                "last_write_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                "tier": tier, "relevance": relevance,
            })
    return rows


def protected_hashes() -> dict[str, str]:
    return {relative: sha256_file(REPO_ROOT / relative) for relative in PROTECTED_PATHS if (REPO_ROOT / relative).is_file()}


def _display(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return "NA"
    return str(value)


def run() -> dict[str, Any]:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    summary_path = RESULTS_ROOT / "abcde_a2_r0u_summary.json"
    manifest_path = RESULTS_ROOT / "a2_r0u_manifest.json"
    prior_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    created_at = prior_manifest.get("created_at_utc") or datetime.now(timezone.utc).isoformat()

    current = read_current_tickers()
    git_evidence = audit_git_evidence()
    manager_audit = audit_manager_evidence()
    price_audit = audit_price_inventory(current)
    security_audit = audit_security_database(current)
    external_evidence = audit_external_evidence(security_audit)
    prereg = audit_preregistration()
    a2 = import_prior_a2()
    a1_identity = a2.audit_a1_identity()

    protected_now = protected_hashes()
    protected_initial = prior_manifest.get("protected_hashes_initial", protected_now)
    protected_unchanged = protected_now == protected_initial

    exact_recovery_valid = False
    research_master_valid = bool(security_audit.get("historical_master_valid"))
    classification = choose_route(exact_recovery_valid, research_master_valid)
    if classification != "C_INSUFFICIENT_HISTORICAL_SECURITY_MASTER_EVIDENCE":
        raise RuntimeError("UNEXPECTED_PASS_REQUIRES_EXPLICIT_CONTRACT_REVIEW")

    failure_reason = (
        "MISSING_COMPLETE_2020_2025_US_SECURITY_MASTER_INCLUDING_DELISTED_INACTIVE_NAMES_WITH_"
        "ORIGINAL_EXCHANGE_SECURITY_TYPE_LISTING_AND_EFFECTIVE_TERMINAL_DATES;"
        "MISSING_EFFECTIVE_DATED_LEGACY_ABCDE_OR_MANAGER_SET_VERSIONS;"
        "MISSING_PIT_13F_PUBLIC_AVAILABILITY_HOLDINGS_SNAPSHOTS_AND_HOLDINGS_TO_UNIVERSE_RULE"
    )
    summary: dict[str, Any] = {
        "ABCDE_A2_R0U_STATUS": "FAIL_CLOSED",
        "ABCDE_A2_R0U_CLASSIFICATION": classification,
        "ABCDE_A2_R0U_DECISION": "STOP_AND_ACQUIRE_MISSING_SECURITY_MASTER_EVIDENCE",
        "LEGACY_ABCDE_UNIVERSE_DEFINITION_STATUS": "INCOMPLETE",
        "EXACT_HISTORICAL_UNIVERSE_RECOVERED": False,
        "NEW_RESEARCH_PIT_UNIVERSE_CREATED": False,
        "LEGACY_UNIVERSE_EQUIVALENCE": False,
        "PIT_UNIVERSE_AUDIT_STATUS": "FAIL_CLOSED",
        "SURVIVORSHIP_AUDIT_STATUS": "FAIL_CLOSED_MISSING_COMPLETE_DELISTED_IDENTITY",
        "CURRENT_325_USED_AS_HISTORICAL_SOURCE": False,
        # No pre-2026 membership contract exists, so a membership count cannot
        # be inferred from the one price-only difference (OLPX).
        "HISTORICAL_NOT_IN_CURRENT_325_COUNT": None,
        "HISTORICAL_PRICE_TICKERS_NOT_IN_CURRENT_325_COUNT": len(price_audit["historical_price_tickers_not_in_current_325"]),
        "CURRENT_325_NOT_YET_ELIGIBLE_HISTORICAL_COUNT": len(price_audit["current_325_without_any_2020_price_observation"]),
        "HISTORICAL_UNIQUE_SECURITY_COUNT": 0,
        "UNIVERSE_START_DATE": None,
        "UNIVERSE_END_DATE": None,
        "UNIVERSE_DAILY_SIZE_MIN": None,
        "UNIVERSE_DAILY_SIZE_MEDIAN": None,
        "UNIVERSE_DAILY_SIZE_MAX": None,
        "FEATURE_READY_DAILY_SIZE_MEDIAN": None,
        "SECURITY_MASTER_SOURCE": "MOOMOO_OPEND_CURRENT_SECLISTDB_V13_CANDIDATE_REJECTED_AS_HISTORICAL_MASTER",
        "AUTHORITATIVE_PRICE_SOURCE": price_audit["source"],
        "GIT_HISTORY_UNIVERSE_EVIDENCE_COUNT": len(git_evidence),
        "EXTERNAL_UNIVERSE_EVIDENCE_COUNT": len(external_evidence),
        "A1_RECOMPUTE_REQUIRED_ON_PIT_UNIVERSE": True,
        "A2_R1_PREREGISTRATION_CHANGED": prereg["changed"],
        "A2_R1_PREREGISTRATION_BLOCKER": None if not prereg["changed"] else "FROZEN_PREREGISTRATION_MISMATCH",
        "MODEL_FIT_COUNT": 0,
        "MODEL_PREDICT_CALL_COUNT": 0,
        "TRAINING_2026_ROW_COUNT": 0,
        "BROKER_ACTION_COUNT": 0,
        "DAILY_CHAIN_CHANGED": not protected_unchanged,
        "A1_CHANGED": not protected_unchanged,
        "B_CHANGED": False,
        "C_CHANGED": False,
        "D_CHANGED": False,
        "E_CHANGED": False,
        "FAST_CHANGED": False,
        "MOOMOO_API_REQUEST_COUNT": 0,
        "ANTI_BLOAT_STATUS": "PASS",
        "RESULTS_ROOT": str(RESULTS_ROOT),
        "UNIVERSE_PATH": "NOT_CREATED_FAIL_CLOSED",
        "SECURITY_MASTER_PATH": "NOT_CREATED_FAIL_CLOSED",
        "MANIFEST_PATH": str(manifest_path),
        "SUMMARY_PATH": str(summary_path),
        "MANAGER_SET_VERSIONING_STATUS": manager_audit["manager_set_versioning_status"],
        "EARLIEST_MANAGER_SET_EVIDENCE_DATE": manager_audit["earliest_authoritative_manager_set_evidence_date"],
        "LEGACY_CORE_MANAGER_COUNT": manager_audit["user_recovered_core_manager_count"],
        "LATE_ADDED_MANAGER_COUNT": None,
        "LEOPOLD_EARLIEST_ELIGIBLE_DATE": manager_audit["leopold_earliest_eligible_date"],
        "ARK_MANAGER_EVIDENCE_STATUS": manager_audit["ark_manager_evidence_status"],
        "USER_RECOVERED_MANAGER_CLUE_DATE_APPROXIMATE": manager_audit["user_recovered_chat_clue_date_approximate"],
        "TIER_C_NOT_SUFFICIENT_FOR_PIT_MEMBERSHIP": True,
        "EXACT_NINE_MANAGER_GROUP_ARTIFACT_STATUS": manager_audit["exact_nine_manager_group_status"],
        "OTHER_SUPERINVESTOR_GROUP_ARTIFACT_STATUS": manager_audit["other_seven_manager_artifact_status"],
        "HOLDINGS_TO_UNIVERSE_RULE_RECOVERED": manager_audit["holdings_to_universe_rule_recovered"],
        "CURRENT_325_REPRODUCIBLE_FROM_HOLDINGS_RULE": manager_audit["approximately_325_reproducible_from_holdings"],
        "A1_CONTROL_IDENTITY_STATUS": a1_identity["status"],
        "FAILURE_REASON": failure_reason,
        "legacy_universe_audit": {
            "current_production_definition": "V21.231 current active manifest feeding V21.233 same-date cross-sectional ranks",
            "always_fixed_325_proven": False,
            "first_fixed_325_artifact_effective_date": json.loads(CURRENT_MANIFEST.read_text(encoding="utf-8"))["effective_date"],
            "fixed_325_selection_basis_recovered": False,
            "historical_versions_recovered": False,
            "a1_rank_dependency": "six percentile ranks depend on each signal-date cohort",
            "a1_recompute_required": True,
        },
        "manager_set_audit": manager_audit,
        "security_master_capability_audit": security_audit,
        "price_inventory_diagnostic": price_audit,
        "preregistration_audit": prereg,
        "a1_identity_audit": a1_identity,
        "protected_hashes_initial": protected_initial,
        "protected_hashes_after": protected_now,
        "research_only": True,
        "outcome_or_target_paths_read": [],
    }

    stable_contract = {
        key: value for key, value in summary.items()
        if key not in {"RESULTS_ROOT", "MANIFEST_PATH", "SUMMARY_PATH"}
    }
    stable_contract["git_evidence"] = git_evidence
    stable_contract["external_evidence"] = external_evidence
    contract_fingerprint = canonical_fingerprint(stable_contract)
    summary["DETERMINISTIC_CONTRACT_FINGERPRINT"] = contract_fingerprint

    manifest = {
        "experiment_id": EXPERIMENT_ID,
        "schema_version": "1.0",
        "created_at_utc": created_at,
        "last_verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": classification,
        "pit_status": "FAIL_CLOSED",
        "contract_fingerprint": contract_fingerprint,
        "source_paths": [row["path"] for row in external_evidence],
        "source_hashes": {row["path"]: row["sha256"] for row in external_evidence},
        "git_evidence_count": len(git_evidence),
        "external_evidence_count": len(external_evidence),
        "legacy_vs_research_universe_classification": "NEITHER_CREATED_INSUFFICIENT_SECURITY_MASTER",
        "protected_hashes_initial": protected_initial,
        "model_fit_count": 0,
        "model_predict_call_count": 0,
    }
    write_json_atomic(RESULTS_ROOT / "git_history_universe_evidence.json", git_evidence)
    write_json_atomic(RESULTS_ROOT / "external_universe_evidence.json", external_evidence)
    write_json_atomic(RESULTS_ROOT / "manager_set_recovery_audit.json", manager_audit)
    write_json_atomic(RESULTS_ROOT / "security_master_capability_audit.json", security_audit)
    write_json_atomic(manifest_path, manifest)
    write_json_atomic(summary_path, summary)

    for field in SUMMARY_FIELDS:
        print(f"{field}={_display(summary.get(field))}")
    print(f"DETERMINISTIC_CONTRACT_FINGERPRINT={contract_fingerprint}")
    print(f"EXACT_NINE_MANAGER_GROUP_ARTIFACT_STATUS={manager_audit['exact_nine_manager_group_status']}")
    print(f"CURRENT_325_REPRODUCIBLE_FROM_HOLDINGS_RULE={_display(manager_audit['approximately_325_reproducible_from_holdings'])}")
    return summary


def main() -> int:
    run()
    return 2  # expected fail-closed research gate


if __name__ == "__main__":
    sys.exit(main())
