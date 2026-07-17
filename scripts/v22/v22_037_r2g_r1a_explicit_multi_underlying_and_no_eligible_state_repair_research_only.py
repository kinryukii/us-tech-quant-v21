#!/usr/bin/env python
"""V22.037_R2G_R1A explicit multi-underlying and no-eligible-state repair.

Research-only orchestration:
  market-session preflight
  -> explicit five-underlying R2D capture
  -> R2E panel
  -> V22.042_R2 direction
  -> V22.037_R2F ranking
  -> timestamp alignment audit

Design rules:
- R2D is explicit and required; no wildcard/auto child discovery.
- Outside the US regular session, do not overwrite live research outputs.
- R2E NO_BASE_RESEARCH_ELIGIBLE_ROWS is a soft data-state block, not an
  infrastructure failure.
- Every non-ready state remains NO_TRADE.
- No broker/trade mutation exists or is allowed.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

REVISION = "V22.037_R2G_R1A"
STAGE = "V22.037_R2G_R1A_EXPLICIT_MULTI_UNDERLYING_AND_NO_ELIGIBLE_STATE_REPAIR_RESEARCH_ONLY"
OUT_REL = Path("outputs") / "v22" / STAGE

PASS_STATUS = "PASS_V22_037_R2G_R1A_SAME_SESSION_CHAIN_READY_RESEARCH_ONLY"
WARN_OUTSIDE_STATUS = "WARN_V22_037_R2G_R1A_OUTSIDE_REGULAR_SESSION_NO_TRADE_RESEARCH_ONLY"
WARN_NO_ELIGIBLE_STATUS = "WARN_V22_037_R2G_R1A_NO_BASE_ELIGIBLE_ROWS_NO_TRADE_RESEARCH_ONLY"
WARN_ALIGNMENT_STATUS = "WARN_V22_037_R2G_R1A_ALIGNMENT_NOT_FRESH_NO_TRADE_RESEARCH_ONLY"
FAIL_STATUS = "FAIL_V22_037_R2G_R1A_REQUIRED_CHILD_OR_INPUT_FAILED"

PASS_DECISION = "SAME_SESSION_DIRECTION_AWARE_OPTION_RANKING_READY_RESEARCH_ONLY"
WARN_OUTSIDE_DECISION = "NO_TRADE_OUTSIDE_US_REGULAR_SESSION_RESEARCH_ONLY"
WARN_NO_ELIGIBLE_DECISION = "NO_TRADE_NO_BASE_ELIGIBLE_OPTION_ROWS_RESEARCH_ONLY"
WARN_ALIGNMENT_DECISION = "NO_TRADE_ALIGNMENT_GUARD_ACTIVE_RESEARCH_ONLY"
FAIL_DECISION = "BLOCKED_REQUIRED_CHILD_OR_INPUT_FAILURE_RESEARCH_ONLY"

R2D_WRAPPER_REL = Path("scripts/v22/run_v22_037_r2d_multi_underlying_rate_limited_same_snapshot_capture_and_iv_greeks_validation_research_only.ps1")
R2E_WRAPPER_REL = Path("scripts/v22/run_v22_037_r2e_iv_greeks_eligibility_attribution_and_liquid_contract_panel_research_only.ps1")
DIRECTION_SCRIPT_REL = Path("scripts/v22/v22_042_r2_direction_gate_reason_and_shadow_mode_audit.py")
R2F_SCRIPT_REL = Path("scripts/v22/v22_037_r2f_direction_aware_liquid_option_contract_ranking_and_no_trade_gate_research_only.py")

R2D_ROOT_REL = Path("outputs/v22/V22.037_R2D_MULTI_UNDERLYING_RATE_LIMITED_SAME_SNAPSHOT_CAPTURE_AND_IV_GREEKS_VALIDATION_RESEARCH_ONLY")
R2E_ROOT_REL = Path("outputs/v22/V22.037_R2E_IV_GREEKS_ELIGIBILITY_ATTRIBUTION_AND_LIQUID_CONTRACT_PANEL_RESEARCH_ONLY")
DIRECTION_ROOT_REL = Path("outputs/v22/V22.042_R2_DIRECTION_GATE_REASON_AND_SHADOW_MODE_AUDIT")
R2F_ROOT_REL = Path("outputs/v22/V22.037_R2F_DIRECTION_AWARE_LIQUID_OPTION_CONTRACT_RANKING_AND_NO_TRADE_GATE_RESEARCH_ONLY")

EXPECTED_UNDERLYINGS = ("QQQ", "SOXX", "SPY", "SMH", "DIA")
SOFT_R2E_STATUSES = {"FAIL_V22_037_R2E_NO_BASE_RESEARCH_ELIGIBLE_ROWS"}

LEDGER_FIELDS = [
    "stage_order", "stage_name", "required", "attempted", "return_code",
    "process_succeeded", "outcome_class", "child_final_status",
    "child_final_decision", "summary_path", "resolved_path",
    "started_utc", "ended_utc", "duration_seconds",
    "stdout_log", "stderr_log", "blocking_reason_code", "error_message",
]
AUDIT_FIELDS = [
    "check_name", "expected", "actual", "passed", "severity",
    "source_path", "notes",
]
PREFLIGHT_FIELDS = [
    "check_name", "expected", "actual", "passed", "severity", "notes",
]


@dataclass(frozen=True)
class Config:
    underlyings: tuple[str, ...] = EXPECTED_UNDERLYINGS
    max_direction_panel_gap_minutes: float = 30.0
    max_panel_age_minutes: float = 90.0
    max_direction_age_minutes: float = 90.0
    child_timeout_seconds: int = 1800


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(timezone.utc).isoformat()


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def write_csv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fields),
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text_value = str(value).strip().replace("Z", "+00:00")
    if not text_value:
        return None
    for candidate in (text_value, text_value.replace(" ", "T", 1)):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _fallback_new_york_offset(now_utc: datetime) -> timezone:
    # US DST approximation: second Sunday in March to first Sunday in November.
    year = now_utc.year

    march_first = datetime(year, 3, 1, tzinfo=timezone.utc)
    march_first_sunday = 1 + ((6 - march_first.weekday()) % 7)
    second_sunday_march = march_first_sunday + 7

    november_first = datetime(year, 11, 1, tzinfo=timezone.utc)
    first_sunday_november = 1 + ((6 - november_first.weekday()) % 7)

    dst_start_utc = datetime(year, 3, second_sunday_march, 7, 0, tzinfo=timezone.utc)
    dst_end_utc = datetime(year, 11, first_sunday_november, 6, 0, tzinfo=timezone.utc)
    offset_hours = -4 if dst_start_utc <= now_utc < dst_end_utc else -5
    return timezone(timedelta(hours=offset_hours))


def to_new_york(now_utc: datetime) -> datetime:
    normalized = now_utc.astimezone(timezone.utc)
    if ZoneInfo is not None:
        try:
            return normalized.astimezone(ZoneInfo("America/New_York"))
        except Exception:
            pass
    return normalized.astimezone(_fallback_new_york_offset(normalized))


def market_session_state(now_utc: datetime) -> dict[str, Any]:
    et = to_new_york(now_utc)
    weekday = et.weekday()
    local_clock = et.timetz().replace(tzinfo=None)
    if weekday >= 5:
        reason = "WEEKEND"
        passed = False
    elif local_clock < time(9, 30):
        reason = "BEFORE_REGULAR_SESSION"
        passed = False
    elif local_clock >= time(16, 0):
        reason = "AFTER_REGULAR_SESSION"
        passed = False
    else:
        reason = "REGULAR_SESSION_CLOCK_PASS"
        passed = True
    return {
        "market_time_et": et.isoformat(),
        "market_weekday": weekday,
        "regular_session_clock_pass": passed,
        "market_session_reason_code": reason,
        "holiday_calendar_checked": False,
    }


def parse_underlyings(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        parts = value
    else:
        parts = str(value or "").replace(";", ",").split(",")
    return tuple(
        dict.fromkeys(str(part).strip().upper() for part in parts if str(part).strip())
    )


def minutes_between(left: datetime | None, right: datetime | None) -> float | None:
    if left is None or right is None:
        return None
    return abs((left - right).total_seconds()) / 60.0


def age_minutes(value: datetime | None, now: datetime) -> float | None:
    if value is None:
        return None
    return max(0.0, (now - value).total_seconds() / 60.0)


def latest_summary(root: Path, pattern: str, preferred: str | None = None) -> Path:
    if preferred:
        preferred_path = root / preferred
        if preferred_path.exists():
            return preferred_path
    candidates = list(root.glob(pattern)) if root.exists() else []
    if not candidates:
        return root / (preferred or pattern.replace("**/", "").replace("*", ""))
    return max(candidates, key=lambda path: (path.stat().st_mtime, str(path).lower()))


def state_paths(repo_root: Path) -> dict[str, Path]:
    return {
        "r2d_summary": latest_summary(
            repo_root / R2D_ROOT_REL,
            "runs/*/v22_037_r2d_summary.json",
        ),
        "r2e_summary": latest_summary(
            repo_root / R2E_ROOT_REL,
            "*summary*.json",
            "v22_037_r2e_summary.json",
        ),
        "direction_summary": latest_summary(
            repo_root / DIRECTION_ROOT_REL,
            "*summary*.json",
            "v22_042_r2_summary.json",
        ),
        "r2f_summary": latest_summary(
            repo_root / R2F_ROOT_REL,
            "*summary*.json",
            "v22_037_r2f_summary.json",
        ),
    }


def load_state(repo_root: Path) -> dict[str, Any]:
    paths = state_paths(repo_root)
    r2d = read_json(paths["r2d_summary"])
    r2e = read_json(paths["r2e_summary"])
    direction = read_json(paths["direction_summary"])
    r2f = read_json(paths["r2f_summary"])

    panel_time = parse_datetime(
        r2f.get("panel_reference_time_utc")
        or r2e.get("panel_reference_time_utc")
        or r2e.get("valuation_timestamp_utc")
        or r2d.get("run_end_utc")
    )
    direction_time = parse_datetime(
        r2f.get("direction_source_time_utc")
        or direction.get("direction_source_time_utc")
        or direction.get("run_end_utc")
    )
    return {
        **paths,
        "r2d": r2d,
        "r2e": r2e,
        "direction": direction,
        "r2f": r2f,
        "panel_time": panel_time,
        "direction_time": direction_time,
    }


def build_commands(repo_root: Path, python_exe: Path, config: Config) -> list[dict[str, Any]]:
    underlyings_csv = ",".join(config.underlyings)
    r2f_dir = repo_root / R2F_ROOT_REL
    r2e_dir = repo_root / R2E_ROOT_REL
    direction_summary = repo_root / DIRECTION_ROOT_REL / "v22_042_r2_summary.json"
    return [
        {
            "stage_name": "R2D_OPTION_SNAPSHOT_REFRESH",
            "required": True,
            "path": repo_root / R2D_WRAPPER_REL,
            "command": [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(repo_root / R2D_WRAPPER_REL),
                "-RepoRoot", str(repo_root),
                "-Underlyings", underlyings_csv,
                "-Execute",
            ],
        },
        {
            "stage_name": "R2E_LIQUID_CONTRACT_PANEL_BUILD",
            "required": True,
            "path": repo_root / R2E_WRAPPER_REL,
            "command": [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(repo_root / R2E_WRAPPER_REL),
                "-RepoRoot", str(repo_root),
                "-Execute",
            ],
        },
        {
            "stage_name": "V22_042_R2_DIRECTION_REFRESH",
            "required": True,
            "path": repo_root / DIRECTION_SCRIPT_REL,
            "command": [
                str(python_exe), str(repo_root / DIRECTION_SCRIPT_REL),
                "--repo-root", str(repo_root),
                "--execute",
            ],
        },
        {
            "stage_name": "V22_037_R2F_DIRECTION_AWARE_RANKING",
            "required": True,
            "path": repo_root / R2F_SCRIPT_REL,
            "command": [
                str(python_exe), str(repo_root / R2F_SCRIPT_REL),
                "--repo-root", str(repo_root),
                "--output-dir", str(r2f_dir),
                "--r2e-output-dir", str(r2e_dir),
                "--direction-summary-path", str(direction_summary),
                "--max-direction-panel-gap-minutes", str(config.max_direction_panel_gap_minutes),
                "--max-panel-age-minutes", str(config.max_panel_age_minutes),
                "--execute",
            ],
        },
    ]


def classify_child(
    stage_name: str,
    return_code: int,
    summary: Mapping[str, Any],
) -> tuple[str, str]:
    status = str(summary.get("final_status") or "")
    if return_code == 0 and not status.startswith("FAIL_"):
        return "SUCCESS", ""
    if stage_name == "R2E_LIQUID_CONTRACT_PANEL_BUILD" and status in SOFT_R2E_STATUSES:
        return "SOFT_DATA_BLOCK", "NO_BASE_RESEARCH_ELIGIBLE_ROWS"
    return "HARD_FAILURE", (
        f"CHILD_STATUS_{status}" if status else f"CHILD_NONZERO_EXIT_{return_code}"
    )


def run_child(
    order: int,
    stage: Mapping[str, Any],
    repo_root: Path,
    log_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    name = str(stage["stage_name"])
    path = Path(stage["path"])
    row: dict[str, Any] = {
        "stage_order": order,
        "stage_name": name,
        "required": bool(stage.get("required", True)),
        "attempted": False,
        "return_code": "",
        "process_succeeded": False,
        "outcome_class": "HARD_FAILURE",
        "child_final_status": "",
        "child_final_decision": "",
        "summary_path": "",
        "resolved_path": str(path),
        "started_utc": "",
        "ended_utc": "",
        "duration_seconds": "",
        "stdout_log": "",
        "stderr_log": "",
        "blocking_reason_code": "",
        "error_message": "",
    }
    if not path.exists():
        row["blocking_reason_code"] = "CHILD_PATH_MISSING"
        row["error_message"] = "CHILD_PATH_MISSING"
        return row

    before_paths = state_paths(repo_root)
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{order:02d}_{name}_stdout.log"
    stderr_path = log_dir / f"{order:02d}_{name}_stderr.log"
    row["stdout_log"] = str(stdout_path)
    row["stderr_log"] = str(stderr_path)
    row["attempted"] = True
    started = utc_now()
    row["started_utc"] = utc_text(started)

    safe_tmp = log_dir / "tmp"
    safe_tmp.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"TMP": str(safe_tmp), "TEMP": str(safe_tmp), "PYTHONDONTWRITEBYTECODE": "1"})

    return_code = 1
    try:
        completed = subprocess.run(
            list(stage["command"]),
            cwd=str(repo_root),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        return_code = completed.returncode
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(exc.stdout if isinstance(exc.stdout, str) else "", encoding="utf-8")
        stderr_path.write_text(exc.stderr if isinstance(exc.stderr, str) else "", encoding="utf-8")
        row["error_message"] = "CHILD_TIMEOUT"
        row["blocking_reason_code"] = "CHILD_TIMEOUT"
    except Exception as exc:
        row["error_message"] = f"{type(exc).__name__}:{exc}"
        row["blocking_reason_code"] = "CHILD_EXECUTION_EXCEPTION"

    ended = utc_now()
    row["ended_utc"] = utc_text(ended)
    row["duration_seconds"] = round((ended - started).total_seconds(), 3)
    row["return_code"] = return_code
    row["process_succeeded"] = return_code == 0

    after_paths = state_paths(repo_root)
    summary_key = {
        "R2D_OPTION_SNAPSHOT_REFRESH": "r2d_summary",
        "R2E_LIQUID_CONTRACT_PANEL_BUILD": "r2e_summary",
        "V22_042_R2_DIRECTION_REFRESH": "direction_summary",
        "V22_037_R2F_DIRECTION_AWARE_RANKING": "r2f_summary",
    }[name]
    summary_path = after_paths[summary_key]
    child_summary = read_json(summary_path)
    row["summary_path"] = str(summary_path)
    row["child_final_status"] = child_summary.get("final_status", "")
    row["child_final_decision"] = child_summary.get("final_decision", "")

    outcome, reason = classify_child(name, return_code, child_summary)
    row["outcome_class"] = outcome
    if reason:
        row["blocking_reason_code"] = reason
    if outcome == "HARD_FAILURE" and not row["error_message"]:
        row["error_message"] = reason
    return row


def alignment_audit(
    state: Mapping[str, Any],
    config: Config,
    now_utc: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    panel_time: datetime | None = state["panel_time"]
    direction_time: datetime | None = state["direction_time"]
    gap = minutes_between(panel_time, direction_time)
    panel_age = age_minutes(panel_time, now_utc)
    direction_age = age_minutes(direction_time, now_utc)
    rows: list[dict[str, Any]] = []

    def add(
        name: str,
        expected: Any,
        actual: Any,
        passed: bool,
        severity: str,
        source: Path,
        notes: str = "",
    ) -> None:
        rows.append({
            "check_name": name,
            "expected": expected,
            "actual": actual,
            "passed": passed,
            "severity": severity,
            "source_path": str(source),
            "notes": notes,
        })

    r2d = state["r2d"]
    r2e = state["r2e"]
    direction = state["direction"]
    r2f = state["r2f"]

    requested = parse_underlyings(r2d.get("underlyings_requested"))
    expected_set = set(config.underlyings)
    requested_set = set(requested)

    add(
        "r2d_requested_underlying_scope_exact",
        ",".join(config.underlyings),
        ",".join(requested),
        requested_set == expected_set,
        "ERROR",
        state["r2d_summary"],
        "Explicit five-underlying scope is mandatory.",
    )
    add(
        "r2d_regular_session_clock_pass",
        True,
        r2d.get("regular_session_clock_pass"),
        r2d.get("regular_session_clock_pass") is True,
        "WARN",
        state["r2d_summary"],
    )
    add(
        "r2e_summary_available",
        True,
        bool(r2e),
        bool(r2e),
        "ERROR",
        state["r2e_summary"],
    )
    add(
        "direction_summary_available",
        True,
        bool(direction),
        bool(direction),
        "ERROR",
        state["direction_summary"],
    )
    add(
        "r2f_summary_available",
        True,
        bool(r2f),
        bool(r2f),
        "ERROR",
        state["r2f_summary"],
    )
    add(
        "r2f_research_only",
        True,
        r2f.get("research_only"),
        r2f.get("research_only") is True,
        "ERROR",
        state["r2f_summary"],
    )
    add(
        "r2f_broker_action_blocked",
        False,
        r2f.get("broker_action_allowed"),
        r2f.get("broker_action_allowed") is False,
        "ERROR",
        state["r2f_summary"],
    )
    add(
        "r2f_official_adoption_blocked",
        False,
        r2f.get("official_adoption_allowed"),
        r2f.get("official_adoption_allowed") is False,
        "ERROR",
        state["r2f_summary"],
    )
    add(
        "panel_reference_time_available",
        True,
        utc_text(panel_time) if panel_time else "",
        panel_time is not None,
        "ERROR",
        state["r2f_summary"],
    )
    add(
        "direction_source_time_available",
        True,
        utc_text(direction_time) if direction_time else "",
        direction_time is not None,
        "ERROR",
        state["direction_summary"],
    )
    add(
        "direction_panel_gap_within_limit",
        f"<= {config.max_direction_panel_gap_minutes}",
        "" if gap is None else round(gap, 6),
        gap is not None and gap <= config.max_direction_panel_gap_minutes,
        "WARN",
        state["r2f_summary"],
    )
    add(
        "panel_age_within_limit",
        f"<= {config.max_panel_age_minutes}",
        "" if panel_age is None else round(panel_age, 6),
        panel_age is not None and panel_age <= config.max_panel_age_minutes,
        "WARN",
        state["r2f_summary"],
    )
    add(
        "direction_age_within_limit",
        f"<= {config.max_direction_age_minutes}",
        "" if direction_age is None else round(direction_age, 6),
        direction_age is not None and direction_age <= config.max_direction_age_minutes,
        "WARN",
        state["direction_summary"],
    )

    integrity_pass = all(bool(row["passed"]) for row in rows if row["severity"] == "ERROR")
    freshness_pass = all(bool(row["passed"]) for row in rows if row["severity"] == "WARN")
    context = {
        "integrity_checks_passed": integrity_pass,
        "freshness_checks_passed": freshness_pass,
        "panel_reference_time_utc": utc_text(panel_time) if panel_time else "",
        "direction_source_time_utc": utc_text(direction_time) if direction_time else "",
        "direction_panel_gap_minutes": gap,
        "panel_age_minutes": panel_age,
        "direction_age_minutes": direction_age,
        "r2d_underlyings_requested": ",".join(requested),
        "r2d_underlying_count": r2d.get("underlying_count", 0),
        "r2d_timestamp_alignment_pass_count": r2d.get("timestamp_alignment_pass_count", 0),
        "r2d_research_ranking_eligible_count": r2d.get("research_ranking_eligible_count", 0),
        "r2e_base_research_eligible_count": r2e.get("base_research_eligible_count", 0),
        "r2e_liquid_panel_count": r2e.get("liquid_panel_count", 0),
        "r2f_final_status": r2f.get("final_status", ""),
        "r2f_final_decision": r2f.get("final_decision", ""),
        "r2f_selected_contract_count": r2f.get("selected_contract_count", 0),
        "r2f_shadow_selected_contract_count": r2f.get("shadow_selected_contract_count", 0),
        "r2f_primary_wait_reason_code": r2f.get("primary_wait_reason_code", ""),
    }
    return rows, context


def report_text(summary: Mapping[str, Any]) -> str:
    keys = [
        "final_status", "final_decision", "execution_mode",
        "market_time_et", "market_session_reason_code",
        "blocking_stage_name", "blocking_child_status", "blocking_reason_code",
        "r2d_underlyings_requested", "r2d_underlying_count",
        "r2d_timestamp_alignment_pass_count", "r2d_research_ranking_eligible_count",
        "r2e_base_research_eligible_count", "r2e_liquid_panel_count",
        "integrity_checks_passed", "freshness_checks_passed",
        "panel_reference_time_utc", "direction_source_time_utc",
        "direction_panel_gap_minutes", "panel_age_minutes", "direction_age_minutes",
        "r2f_final_status", "r2f_final_decision",
        "r2f_selected_contract_count", "r2f_shadow_selected_contract_count",
        "research_only", "broker_action_allowed", "official_adoption_allowed",
    ]
    return "\n".join([STAGE, *[f"{key}={summary.get(key)}" for key in keys]]) + "\n"


def execute(
    repo_root: Path,
    output_dir: Path,
    execute_children: bool,
    config: Config,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    now_value = (now_utc or utc_now()).astimezone(timezone.utc)

    summary_path = output_dir / "v22_037_r2g_r1a_summary.json"
    ledger_path = output_dir / "stage_ledger.csv"
    audit_path = output_dir / "timestamp_alignment_audit.csv"
    preflight_path = output_dir / "market_session_preflight.csv"
    report_path = output_dir / "V22.037_R2G_R1A_explicit_multi_underlying_no_eligible_repair_report.txt"
    log_dir = output_dir / "logs"

    session = market_session_state(now_value)
    base: dict[str, Any] = {
        "revision": REVISION,
        "stage": STAGE,
        "run_start_utc": utc_text(now_value),
        "execution_mode": "EXECUTE_CHILDREN" if execute_children else "AUDIT_ONLY",
        **session,
        "expected_underlyings": ",".join(config.underlyings),
        "final_status": "RUNNING",
        "final_decision": "NO_TRADE_WHILE_RUNNING_RESEARCH_ONLY",
        "blocking_stage_name": "",
        "blocking_child_status": "",
        "blocking_reason_code": "",
        "research_only": True,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "trade_context_used": False,
        "unlock_trade_called": False,
        "place_order_called": False,
    }
    write_json(summary_path, base)

    preflight_rows = [
        {
            "check_name": "us_regular_session_clock",
            "expected": "Mon-Fri 09:30<=ET<16:00",
            "actual": session["market_time_et"],
            "passed": session["regular_session_clock_pass"],
            "severity": "WARN",
            "notes": session["market_session_reason_code"],
        },
        {
            "check_name": "holiday_calendar",
            "expected": "Handled downstream by R2D regular_session_clock_pass",
            "actual": "NOT_CHECKED_BY_R1A_STATIC_PREFLIGHT",
            "passed": True,
            "severity": "INFO",
            "notes": "Weekday holidays remain fail-closed through R2D.",
        },
    ]
    write_csv(preflight_path, PREFLIGHT_FIELDS, preflight_rows)

    if execute_children and not session["regular_session_clock_pass"]:
        ledger_rows = []
        for order, stage in enumerate(build_commands(repo_root, Path(sys.executable), config), 1):
            ledger_rows.append({
                "stage_order": order,
                "stage_name": stage["stage_name"],
                "required": stage["required"],
                "attempted": False,
                "return_code": "",
                "process_succeeded": "",
                "outcome_class": "NOT_ATTEMPTED",
                "child_final_status": "",
                "child_final_decision": "",
                "summary_path": "",
                "resolved_path": str(stage["path"]),
                "started_utc": "",
                "ended_utc": "",
                "duration_seconds": "",
                "stdout_log": "",
                "stderr_log": "",
                "blocking_reason_code": session["market_session_reason_code"],
                "error_message": "MARKET_SESSION_PREFLIGHT_BLOCK",
            })
        write_csv(ledger_path, LEDGER_FIELDS, ledger_rows)
        summary = {
            **base,
            "run_end_utc": utc_text(now_value),
            "final_status": WARN_OUTSIDE_STATUS,
            "final_decision": WARN_OUTSIDE_DECISION,
            "blocking_stage_name": "MARKET_SESSION_PREFLIGHT",
            "blocking_reason_code": session["market_session_reason_code"],
            "integrity_checks_passed": True,
            "freshness_checks_passed": False,
            "stage_ledger_path": str(ledger_path),
            "market_session_preflight_path": str(preflight_path),
            "timestamp_alignment_audit_path": str(audit_path),
            "report_path": str(report_path),
        }
        write_csv(audit_path, AUDIT_FIELDS, [])
        write_json(summary_path, summary)
        report_path.write_text(report_text(summary), encoding="utf-8")
        return summary

    python_exe = repo_root / ".venv" / "Scripts" / "python.exe"
    if not python_exe.exists():
        python_exe = Path(sys.executable)

    ledger_rows: list[dict[str, Any]] = []
    blocking_row: dict[str, Any] | None = None

    if execute_children:
        commands = build_commands(repo_root, python_exe, config)
        for order, stage in enumerate(commands, 1):
            row = run_child(
                order=order,
                stage=stage,
                repo_root=repo_root,
                log_dir=log_dir,
                timeout_seconds=config.child_timeout_seconds,
            )
            ledger_rows.append(row)
            if row["outcome_class"] in {"SOFT_DATA_BLOCK", "HARD_FAILURE"}:
                blocking_row = row
                break
    else:
        for order, stage in enumerate(build_commands(repo_root, python_exe, config), 1):
            ledger_rows.append({
                "stage_order": order,
                "stage_name": stage["stage_name"],
                "required": stage["required"],
                "attempted": False,
                "return_code": "",
                "process_succeeded": "",
                "outcome_class": "AUDIT_ONLY",
                "child_final_status": "",
                "child_final_decision": "",
                "summary_path": "",
                "resolved_path": str(stage["path"]),
                "started_utc": "",
                "ended_utc": "",
                "duration_seconds": "",
                "stdout_log": "",
                "stderr_log": "",
                "blocking_reason_code": "",
                "error_message": "",
            })
    write_csv(ledger_path, LEDGER_FIELDS, ledger_rows)

    state = load_state(repo_root)
    audit_rows, context = alignment_audit(state, config, now_value)
    write_csv(audit_path, AUDIT_FIELDS, audit_rows)

    if blocking_row and blocking_row["outcome_class"] == "HARD_FAILURE":
        final_status = FAIL_STATUS
        final_decision = FAIL_DECISION
    elif blocking_row and blocking_row["outcome_class"] == "SOFT_DATA_BLOCK":
        final_status = WARN_NO_ELIGIBLE_STATUS
        final_decision = WARN_NO_ELIGIBLE_DECISION
    elif not context["integrity_checks_passed"]:
        # In audit-only mode, a known R2E no-eligible status remains a soft data state.
        if str(state["r2e"].get("final_status")) in SOFT_R2E_STATUSES:
            final_status = WARN_NO_ELIGIBLE_STATUS
            final_decision = WARN_NO_ELIGIBLE_DECISION
        else:
            final_status = FAIL_STATUS
            final_decision = FAIL_DECISION
    elif not context["freshness_checks_passed"]:
        final_status = WARN_ALIGNMENT_STATUS
        final_decision = WARN_ALIGNMENT_DECISION
    else:
        final_status = PASS_STATUS
        final_decision = PASS_DECISION

    summary = {
        **base,
        **context,
        "run_end_utc": utc_text(now_value),
        "final_status": final_status,
        "final_decision": final_decision,
        "blocking_stage_name": blocking_row["stage_name"] if blocking_row else "",
        "blocking_child_status": blocking_row["child_final_status"] if blocking_row else "",
        "blocking_reason_code": blocking_row["blocking_reason_code"] if blocking_row else "",
        "child_stage_attempted_count": sum(bool(row["attempted"]) for row in ledger_rows),
        "child_stage_success_count": sum(row["outcome_class"] == "SUCCESS" for row in ledger_rows),
        "child_stage_soft_block_count": sum(row["outcome_class"] == "SOFT_DATA_BLOCK" for row in ledger_rows),
        "child_stage_hard_failure_count": sum(row["outcome_class"] == "HARD_FAILURE" for row in ledger_rows),
        "stage_ledger_path": str(ledger_path),
        "market_session_preflight_path": str(preflight_path),
        "timestamp_alignment_audit_path": str(audit_path),
        "report_path": str(report_path),
    }
    write_json(summary_path, summary)
    report_path.write_text(report_text(summary), encoding="utf-8")
    return summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument(
        "--underlyings",
        default=",".join(EXPECTED_UNDERLYINGS),
        help="Comma-separated canonical underlying scope.",
    )
    parser.add_argument("--max-direction-panel-gap-minutes", type=float, default=30.0)
    parser.add_argument("--max-panel-age-minutes", type=float, default=90.0)
    parser.add_argument("--max-direction-age-minutes", type=float, default=90.0)
    parser.add_argument("--child-timeout-seconds", type=int, default=1800)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    output_dir = (args.output_dir or (repo_root / OUT_REL)).resolve()
    underlyings = parse_underlyings(args.underlyings)
    config = Config(
        underlyings=underlyings,
        max_direction_panel_gap_minutes=args.max_direction_panel_gap_minutes,
        max_panel_age_minutes=args.max_panel_age_minutes,
        max_direction_age_minutes=args.max_direction_age_minutes,
        child_timeout_seconds=args.child_timeout_seconds,
    )
    summary = execute(
        repo_root=repo_root,
        output_dir=output_dir,
        execute_children=bool(args.execute and not args.audit_only),
        config=config,
    )
    for key in [
        "final_status", "final_decision", "execution_mode",
        "market_time_et", "market_session_reason_code",
        "blocking_stage_name", "blocking_child_status", "blocking_reason_code",
        "expected_underlyings", "r2d_underlyings_requested",
        "r2d_underlying_count", "r2d_timestamp_alignment_pass_count",
        "r2d_research_ranking_eligible_count",
        "r2e_base_research_eligible_count", "r2e_liquid_panel_count",
        "integrity_checks_passed", "freshness_checks_passed",
        "panel_reference_time_utc", "direction_source_time_utc",
        "direction_panel_gap_minutes", "panel_age_minutes", "direction_age_minutes",
        "r2f_final_status", "r2f_final_decision",
        "r2f_selected_contract_count", "r2f_shadow_selected_contract_count",
        "broker_action_allowed", "official_adoption_allowed", "research_only",
    ]:
        print(f"{key}={summary.get(key)}")
    print(f"summary_path={output_dir / 'v22_037_r2g_r1a_summary.json'}")
    return 1 if str(summary.get("final_status", "")).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
