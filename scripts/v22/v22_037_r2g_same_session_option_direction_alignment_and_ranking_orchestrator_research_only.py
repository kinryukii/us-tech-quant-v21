#!/usr/bin/env python
"""V22.037_R2G same-session option/direction alignment orchestrator.

Research-only control layer:
option snapshot/panel refresh -> direction refresh -> R2F ranking -> timestamp audit.

This module never unlocks trading, creates orders, or permits official adoption.
Any required child failure or time misalignment fails closed into NO_TRADE.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REVISION = "V22.037_R2G"
STAGE = "V22.037_R2G_SAME_SESSION_OPTION_DIRECTION_ALIGNMENT_AND_RANKING_ORCHESTRATOR_RESEARCH_ONLY"
OUT_REL = Path("outputs") / "v22" / STAGE

PASS_STATUS = "PASS_V22_037_R2G_SAME_SESSION_ALIGNMENT_READY_RESEARCH_ONLY"
WARN_STATUS = "WARN_V22_037_R2G_ALIGNMENT_NOT_FRESH_NO_TRADE_RESEARCH_ONLY"
FAIL_STATUS = "FAIL_V22_037_R2G_REQUIRED_CHILD_OR_INPUT_FAILED"

PASS_DECISION = "DIRECTION_AWARE_RANKING_READY_RESEARCH_ONLY"
WARN_DECISION = "NO_TRADE_ALIGNMENT_GUARD_ACTIVE_RESEARCH_ONLY"
FAIL_DECISION = "BLOCKED_REQUIRED_CHILD_FAILURE_RESEARCH_ONLY"

R2E_REL = Path("outputs/v22/V22.037_R2E_IV_GREEKS_ELIGIBILITY_ATTRIBUTION_AND_LIQUID_CONTRACT_PANEL_RESEARCH_ONLY")
DIRECTION_REL = Path("outputs/v22/V22.042_R2_DIRECTION_GATE_REASON_AND_SHADOW_MODE_AUDIT")
R2F_REL = Path("outputs/v22/V22.037_R2F_DIRECTION_AWARE_LIQUID_OPTION_CONTRACT_RANKING_AND_NO_TRADE_GATE_RESEARCH_ONLY")

DEFAULT_MANIFEST: dict[str, Any] = {
    "manifest_version": "V22.037_R2G_CHILD_MANIFEST_R1",
    "stages": [
        {
            "stage_name": "R2D_OPTION_SNAPSHOT_REFRESH",
            "enabled": True,
            "required": False,
            "runner": "auto",
            "patterns": [
                "scripts/v22/run_v22_037_r2d*.ps1",
                "scripts/v22/v22_037_r2d*.py",
            ],
            "notes": "Optional same-snapshot multi-underlying refresh when installed.",
        },
        {
            "stage_name": "R2E_LIQUID_CONTRACT_PANEL_BUILD",
            "enabled": True,
            "required": True,
            "runner": "auto",
            "patterns": [
                "scripts/v22/run_v22_037_r2e*.ps1",
                "scripts/v22/v22_037_r2e*.py",
            ],
            "notes": "Required fresh IV/Greeks eligibility and liquid-contract panel.",
        },
        {
            "stage_name": "V22_042_R2_DIRECTION_REFRESH",
            "enabled": True,
            "required": True,
            "runner": "python",
            "path": "scripts/v22/v22_042_r2_direction_gate_reason_and_shadow_mode_audit.py",
            "args": ["--repo-root", "{repo_root}", "--execute"],
            "notes": "Uses the installed latest-window/pagination direction implementation.",
        },
        {
            "stage_name": "V22_037_R2F_DIRECTION_AWARE_RANKING",
            "enabled": True,
            "required": True,
            "runner": "python",
            "path": "scripts/v22/v22_037_r2f_direction_aware_liquid_option_contract_ranking_and_no_trade_gate_research_only.py",
            "args": [
                "--repo-root", "{repo_root}",
                "--output-dir", "{r2f_output_dir}",
                "--r2e-output-dir", "{r2e_output_dir}",
                "--direction-summary-path", "{direction_summary_path}",
                "--max-direction-panel-gap-minutes", "{max_direction_panel_gap_minutes}",
                "--max-panel-age-minutes", "{max_panel_age_minutes}",
                "--execute",
            ],
            "notes": "Explicit input paths prevent accidental stale-summary discovery.",
        },
    ],
}

LEDGER_FIELDS = [
    "stage_order", "stage_name", "enabled", "required", "resolved_path", "runner",
    "attempted", "succeeded", "return_code", "started_utc", "ended_utc",
    "duration_seconds", "stdout_log", "stderr_log", "error_message",
]
AUDIT_FIELDS = [
    "check_name", "expected", "actual", "passed", "severity", "source_path", "notes",
]


@dataclass(frozen=True)
class Config:
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
    text = str(value).strip().replace("Z", "+00:00")
    if not text:
        return None
    for candidate in (text, text.replace(" ", "T", 1)):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def minutes_between(left: datetime | None, right: datetime | None) -> float | None:
    if left is None or right is None:
        return None
    return abs((left - right).total_seconds()) / 60.0


def age_minutes(value: datetime | None, now: datetime) -> float | None:
    if value is None:
        return None
    return max(0.0, (now - value).total_seconds() / 60.0)


def is_fail_status(value: Any) -> bool:
    return str(value or "").upper().startswith("FAIL")


def discover_summary(directory: Path, preferred_name: str) -> Path:
    preferred = directory / preferred_name
    if preferred.exists():
        return preferred
    candidates = sorted(
        directory.glob("*summary*.json"),
        key=lambda p: (p.stat().st_mtime, p.name.lower()),
        reverse=True,
    ) if directory.exists() else []
    return candidates[0] if candidates else preferred


def resolve_manifest(manifest_path: Path | None) -> dict[str, Any]:
    if manifest_path is None:
        return json.loads(json.dumps(DEFAULT_MANIFEST))
    payload = read_json(manifest_path)
    if not payload or not isinstance(payload.get("stages"), list):
        raise ValueError(f"Invalid child manifest: {manifest_path}")
    return payload


def resolve_auto_path(repo_root: Path, patterns: Sequence[str]) -> Path | None:
    matches: set[Path] = set()
    for pattern in patterns:
        matches.update(path.resolve() for path in repo_root.glob(pattern) if path.is_file())
    if not matches:
        return None
    return sorted(
        matches,
        key=lambda p: (
            0 if p.suffix.lower() == ".ps1" else 1,
            -p.stat().st_mtime,
            str(p).lower(),
        ),
    )[0]


def replace_tokens(values: Sequence[Any], tokens: Mapping[str, str]) -> list[str]:
    output: list[str] = []
    for raw in values:
        text = str(raw)
        for key, replacement in tokens.items():
            text = text.replace("{" + key + "}", replacement)
        output.append(text)
    return output


def command_for_stage(
    stage: Mapping[str, Any],
    repo_root: Path,
    python_exe: Path,
    tokens: Mapping[str, str],
) -> tuple[list[str] | None, Path | None, str]:
    runner = str(stage.get("runner") or "auto").lower()
    if runner == "auto":
        resolved = resolve_auto_path(repo_root, [str(x) for x in stage.get("patterns", [])])
        if resolved is None:
            return None, None, "auto"
        if resolved.suffix.lower() == ".ps1":
            return [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(resolved), "-RepoRoot", str(repo_root), "-Execute",
            ], resolved, "powershell"
        return [
            str(python_exe), str(resolved), "--repo-root", str(repo_root), "--execute",
        ], resolved, "python"

    raw_path = str(stage.get("path") or "")
    if not raw_path:
        return None, None, runner
    resolved = (repo_root / raw_path).resolve()
    args = replace_tokens(stage.get("args", []), tokens)
    if runner == "powershell":
        return [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(resolved), *args,
        ], resolved, runner
    return [str(python_exe), str(resolved), *args], resolved, runner


def run_child_stage(
    order: int,
    stage: Mapping[str, Any],
    repo_root: Path,
    python_exe: Path,
    tokens: Mapping[str, str],
    log_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    enabled = bool(stage.get("enabled", True))
    required = bool(stage.get("required", False))
    name = str(stage.get("stage_name") or f"STAGE_{order}")
    row: dict[str, Any] = {
        "stage_order": order,
        "stage_name": name,
        "enabled": enabled,
        "required": required,
        "resolved_path": "",
        "runner": str(stage.get("runner") or "auto"),
        "attempted": False,
        "succeeded": True if not enabled else False,
        "return_code": "",
        "started_utc": "",
        "ended_utc": "",
        "duration_seconds": "",
        "stdout_log": "",
        "stderr_log": "",
        "error_message": "",
    }
    if not enabled:
        return row

    command, resolved, actual_runner = command_for_stage(stage, repo_root, python_exe, tokens)
    row["runner"] = actual_runner
    row["resolved_path"] = "" if resolved is None else str(resolved)
    if command is None or resolved is None or not resolved.exists():
        row["error_message"] = "CHILD_STAGE_NOT_FOUND"
        return row

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

    try:
        completed = subprocess.run(
            command,
            cwd=str(repo_root),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        row["return_code"] = completed.returncode
        row["succeeded"] = completed.returncode == 0
        if completed.returncode != 0:
            row["error_message"] = f"CHILD_NONZERO_EXIT_{completed.returncode}"
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(exc.stdout if isinstance(exc.stdout, str) else "", encoding="utf-8")
        stderr_path.write_text(exc.stderr if isinstance(exc.stderr, str) else "", encoding="utf-8")
        row["error_message"] = "CHILD_TIMEOUT"
    except Exception as exc:
        row["error_message"] = f"{type(exc).__name__}:{exc}"

    ended = utc_now()
    row["ended_utc"] = utc_text(ended)
    row["duration_seconds"] = round((ended - started).total_seconds(), 3)
    return row


def load_state(repo_root: Path) -> dict[str, Any]:
    r2e_dir = repo_root / R2E_REL
    direction_dir = repo_root / DIRECTION_REL
    r2f_dir = repo_root / R2F_REL

    r2e_summary_path = discover_summary(r2e_dir, "v22_037_r2e_summary.json")
    direction_summary_path = discover_summary(direction_dir, "v22_042_r2_summary.json")
    r2f_summary_path = discover_summary(r2f_dir, "v22_037_r2f_summary.json")

    r2e = read_json(r2e_summary_path)
    direction = read_json(direction_summary_path)
    r2f = read_json(r2f_summary_path)

    panel_time = parse_datetime(
        r2f.get("panel_reference_time_utc")
        or r2e.get("panel_reference_time_utc")
        or r2e.get("valuation_timestamp_utc")
        or r2e.get("run_end_utc")
    )
    direction_time = parse_datetime(
        r2f.get("direction_source_time_utc")
        or direction.get("direction_source_time_utc")
        or direction.get("run_end_utc")
    )
    return {
        "r2e_dir": r2e_dir,
        "direction_dir": direction_dir,
        "r2f_dir": r2f_dir,
        "r2e_summary_path": r2e_summary_path,
        "direction_summary_path": direction_summary_path,
        "r2f_summary_path": r2f_summary_path,
        "r2e_summary": r2e,
        "direction_summary": direction,
        "r2f_summary": r2f,
        "panel_time": panel_time,
        "direction_time": direction_time,
    }


def audit_state(
    state: Mapping[str, Any],
    config: Config,
    now: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    r2e = state["r2e_summary"]
    direction = state["direction_summary"]
    r2f = state["r2f_summary"]
    panel_time: datetime | None = state["panel_time"]
    direction_time: datetime | None = state["direction_time"]

    gap = minutes_between(panel_time, direction_time)
    panel_age = age_minutes(panel_time, now)
    direction_age = age_minutes(direction_time, now)
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

    add("r2e_summary_exists", True, bool(r2e), bool(r2e), "ERROR", state["r2e_summary_path"])
    add("direction_summary_exists", True, bool(direction), bool(direction), "ERROR", state["direction_summary_path"])
    add("r2f_summary_exists", True, bool(r2f), bool(r2f), "ERROR", state["r2f_summary_path"])
    add("r2e_not_failed", True, r2e.get("final_status", ""), bool(r2e) and not is_fail_status(r2e.get("final_status")), "ERROR", state["r2e_summary_path"])
    add("direction_not_failed", True, direction.get("final_status", ""), bool(direction) and not is_fail_status(direction.get("final_status")), "ERROR", state["direction_summary_path"])
    add("r2f_not_failed", True, r2f.get("final_status", ""), bool(r2f) and not is_fail_status(r2f.get("final_status")), "ERROR", state["r2f_summary_path"])
    add("panel_reference_time_available", True, utc_text(panel_time) if panel_time else "", panel_time is not None, "ERROR", state["r2f_summary_path"])
    add("direction_source_time_available", True, utc_text(direction_time) if direction_time else "", direction_time is not None, "ERROR", state["direction_summary_path"])

    add(
        "direction_panel_gap_within_limit",
        f"<= {config.max_direction_panel_gap_minutes}",
        "" if gap is None else round(gap, 6),
        gap is not None and gap <= config.max_direction_panel_gap_minutes,
        "WARN",
        state["r2f_summary_path"],
        "Misalignment blocks contract selection.",
    )
    add(
        "panel_age_within_limit",
        f"<= {config.max_panel_age_minutes}",
        "" if panel_age is None else round(panel_age, 6),
        panel_age is not None and panel_age <= config.max_panel_age_minutes,
        "WARN",
        state["r2f_summary_path"],
    )
    add(
        "direction_age_within_limit",
        f"<= {config.max_direction_age_minutes}",
        "" if direction_age is None else round(direction_age, 6),
        direction_age is not None and direction_age <= config.max_direction_age_minutes,
        "WARN",
        state["direction_summary_path"],
    )

    add("r2f_research_only", True, r2f.get("research_only"), r2f.get("research_only") is True, "ERROR", state["r2f_summary_path"])
    add("r2f_broker_action_blocked", False, r2f.get("broker_action_allowed"), r2f.get("broker_action_allowed") is False, "ERROR", state["r2f_summary_path"])
    add("r2f_official_adoption_blocked", False, r2f.get("official_adoption_allowed"), r2f.get("official_adoption_allowed") is False, "ERROR", state["r2f_summary_path"])

    integrity_pass = all(bool(row["passed"]) for row in rows if row["severity"] == "ERROR")
    freshness_pass = all(bool(row["passed"]) for row in rows if row["severity"] == "WARN")
    context = {
        "panel_reference_time_utc": utc_text(panel_time) if panel_time else "",
        "direction_source_time_utc": utc_text(direction_time) if direction_time else "",
        "direction_panel_gap_minutes": gap,
        "panel_age_minutes": panel_age,
        "direction_age_minutes": direction_age,
        "integrity_checks_passed": integrity_pass,
        "freshness_checks_passed": freshness_pass,
        "r2f_final_status": r2f.get("final_status", ""),
        "r2f_final_decision": r2f.get("final_decision", ""),
        "r2f_selected_contract_count": r2f.get("selected_contract_count", 0),
        "r2f_shadow_selected_contract_count": r2f.get("shadow_selected_contract_count", 0),
        "r2f_strict_selected_contract_count": r2f.get("strict_official_selected_contract_count", 0),
        "r2f_primary_wait_reason_code": r2f.get("primary_wait_reason_code", ""),
    }
    return rows, context


def report_text(summary: Mapping[str, Any]) -> str:
    keys = [
        "final_status", "final_decision", "execution_mode",
        "required_child_failure_count", "integrity_checks_passed",
        "freshness_checks_passed", "panel_reference_time_utc",
        "direction_source_time_utc", "direction_panel_gap_minutes",
        "panel_age_minutes", "direction_age_minutes",
        "r2f_final_status", "r2f_final_decision",
        "r2f_selected_contract_count", "r2f_shadow_selected_contract_count",
        "r2f_primary_wait_reason_code", "research_only",
        "broker_action_allowed", "official_adoption_allowed",
    ]
    return "\n".join([STAGE, *[f"{key}={summary.get(key)}" for key in keys]]) + "\n"


def execute(
    repo_root: Path,
    output_dir: Path,
    manifest_path: Path | None,
    execute_children: bool,
    config: Config,
    now: datetime | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_time = now or utc_now()

    summary_path = output_dir / "v22_037_r2g_summary.json"
    ledger_path = output_dir / "stage_ledger.csv"
    audit_path = output_dir / "timestamp_alignment_audit.csv"
    manifest_snapshot_path = output_dir / "child_manifest_snapshot.json"
    report_path = output_dir / "V22.037_R2G_same_session_alignment_report.txt"
    log_dir = output_dir / "logs"

    base_summary: dict[str, Any] = {
        "revision": REVISION,
        "stage": STAGE,
        "run_start_utc": utc_text(run_time),
        "execution_mode": "EXECUTE_CHILDREN" if execute_children else "AUDIT_ONLY",
        "final_status": "RUNNING",
        "final_decision": "NO_TRADE_WHILE_RUNNING_RESEARCH_ONLY",
        "research_only": True,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "trade_context_used": False,
        "unlock_trade_called": False,
        "place_order_called": False,
    }
    write_json(summary_path, base_summary)

    try:
        manifest = resolve_manifest(manifest_path)
        write_json(manifest_snapshot_path, manifest)

        state_before = load_state(repo_root)
        tokens = {
            "repo_root": str(repo_root),
            "r2e_output_dir": str(state_before["r2e_dir"]),
            "direction_summary_path": str(state_before["direction_summary_path"]),
            "r2f_output_dir": str(state_before["r2f_dir"]),
            "max_direction_panel_gap_minutes": str(config.max_direction_panel_gap_minutes),
            "max_panel_age_minutes": str(config.max_panel_age_minutes),
        }

        python_exe = repo_root / ".venv" / "Scripts" / "python.exe"
        if not python_exe.exists():
            python_exe = Path(sys.executable)

        ledger: list[dict[str, Any]] = []
        if execute_children:
            for order, stage in enumerate(manifest.get("stages", []), 1):
                row = run_child_stage(
                    order=order,
                    stage=stage,
                    repo_root=repo_root,
                    python_exe=python_exe,
                    tokens=tokens,
                    log_dir=log_dir,
                    timeout_seconds=config.child_timeout_seconds,
                )
                ledger.append(row)
                if bool(row.get("required")) and row.get("succeeded") is False:
                    break
        else:
            for order, stage in enumerate(manifest.get("stages", []), 1):
                ledger.append({
                    "stage_order": order,
                    "stage_name": stage.get("stage_name", ""),
                    "enabled": bool(stage.get("enabled", True)),
                    "required": bool(stage.get("required", False)),
                    "resolved_path": "",
                    "runner": stage.get("runner", ""),
                    "attempted": False,
                    "succeeded": "",
                    "return_code": "",
                    "started_utc": "",
                    "ended_utc": "",
                    "duration_seconds": "",
                    "stdout_log": "",
                    "stderr_log": "",
                    "error_message": "AUDIT_ONLY",
                })
        write_csv(ledger_path, LEDGER_FIELDS, ledger)

        required_failures = [
            row for row in ledger
            if bool(row.get("required")) and row.get("succeeded") is False
        ]
        state_after = load_state(repo_root)
        audit_rows, context = audit_state(state_after, config, run_time)
        write_csv(audit_path, AUDIT_FIELDS, audit_rows)

        if required_failures or not context["integrity_checks_passed"]:
            final_status = FAIL_STATUS
            final_decision = FAIL_DECISION
        elif context["freshness_checks_passed"]:
            final_status = PASS_STATUS
            final_decision = PASS_DECISION
        else:
            final_status = WARN_STATUS
            final_decision = WARN_DECISION

        summary = {
            **base_summary,
            **context,
            "run_end_utc": utc_text(run_time),
            "final_status": final_status,
            "final_decision": final_decision,
            "required_child_failure_count": len(required_failures),
            "required_child_failure_names": ",".join(str(row["stage_name"]) for row in required_failures),
            "child_stage_count": len(ledger),
            "child_stage_attempted_count": sum(bool(row.get("attempted")) for row in ledger),
            "child_stage_succeeded_count": sum(row.get("succeeded") is True for row in ledger),
            "max_direction_panel_gap_minutes": config.max_direction_panel_gap_minutes,
            "max_panel_age_minutes": config.max_panel_age_minutes,
            "max_direction_age_minutes": config.max_direction_age_minutes,
            "stage_ledger_path": str(ledger_path),
            "timestamp_alignment_audit_path": str(audit_path),
            "manifest_snapshot_path": str(manifest_snapshot_path),
            "report_path": str(report_path),
        }
        write_json(summary_path, summary)
        report_path.write_text(report_text(summary), encoding="utf-8")
        return summary
    except Exception as exc:
        summary = {
            **base_summary,
            "run_end_utc": utc_text(run_time),
            "final_status": FAIL_STATUS,
            "final_decision": FAIL_DECISION,
            "error_message": f"{type(exc).__name__}:{exc}",
        }
        write_json(summary_path, summary)
        report_path.write_text(report_text(summary), encoding="utf-8")
        return summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--manifest-path", type=Path, default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--max-direction-panel-gap-minutes", type=float, default=30.0)
    parser.add_argument("--max-panel-age-minutes", type=float, default=90.0)
    parser.add_argument("--max-direction-age-minutes", type=float, default=90.0)
    parser.add_argument("--child-timeout-seconds", type=int, default=1800)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    output_dir = (args.output_dir or (repo_root / OUT_REL)).resolve()
    config = Config(
        max_direction_panel_gap_minutes=args.max_direction_panel_gap_minutes,
        max_panel_age_minutes=args.max_panel_age_minutes,
        max_direction_age_minutes=args.max_direction_age_minutes,
        child_timeout_seconds=args.child_timeout_seconds,
    )
    summary = execute(
        repo_root=repo_root,
        output_dir=output_dir,
        manifest_path=args.manifest_path,
        execute_children=bool(args.execute and not args.audit_only),
        config=config,
    )
    for key in [
        "final_status", "final_decision", "execution_mode",
        "required_child_failure_count", "integrity_checks_passed",
        "freshness_checks_passed", "panel_reference_time_utc",
        "direction_source_time_utc", "direction_panel_gap_minutes",
        "panel_age_minutes", "direction_age_minutes",
        "r2f_final_status", "r2f_final_decision",
        "r2f_selected_contract_count", "r2f_shadow_selected_contract_count",
        "r2f_primary_wait_reason_code", "broker_action_allowed",
        "official_adoption_allowed", "research_only",
    ]:
        print(f"{key}={summary.get(key)}")
    print(f"summary_path={output_dir / 'v22_037_r2g_summary.json'}")
    return 1 if str(summary.get("final_status", "")).startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
