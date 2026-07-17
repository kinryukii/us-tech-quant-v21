#!/usr/bin/env python
"""V22.044 daily single entrypoint freeze and guard R1."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REVISION = "V22.044_R1"
STAGE = "V22.044_DAILY_SINGLE_ENTRYPOINT_FREEZE_AND_GUARD_R1"
OUT_REL = Path("outputs/v22") / STAGE
V22_040_SUMMARY_REL = Path("outputs/v22/V22.040_DAILY_MOOMOO_ONECLICK_REFRESH_ORCHESTRATOR_R1/v22_040_summary.json")
POINTER_JSON_REL = Path("outputs/v22/current_daily_research_entrypoint.json")
POINTER_MD_REL = Path("outputs/v22/CURRENT_DAILY_RESEARCH_ENTRYPOINT.md")

PASS_STATUS = "PASS_V22_044_DAILY_SINGLE_ENTRYPOINT_FROZEN"
FAIL_STATUS = "FAIL_V22_044_DAILY_SINGLE_ENTRYPOINT_GUARD_BLOCKED"
WARN_STATUS = "WARN_V22_044_DAILY_SINGLE_ENTRYPOINT_DRY_RUN_ONLY"
PASS_DECISION = "V22_040_ACCEPTED_AS_ONLY_CURRENT_DAILY_RESEARCH_ENTRYPOINT"
BLOCKED_DECISION = "V22_040_NOT_ACCEPTED_AS_CURRENT_DAILY_RESEARCH_ENTRYPOINT"
DRY_RUN_DECISION = "V22_040_WRAPPER_VALIDATED_EXECUTE_REQUIRED_FOR_ACCEPTANCE"

ACCEPTED_ENTRYPOINT_NAME = "V22.040_DAILY_MOOMOO_ONECLICK_REFRESH_ORCHESTRATOR_R1A"
ACCEPTED_ENTRYPOINT_WRAPPER = "scripts/v22/run_v22_040_daily_moomoo_oneclick_refresh_orchestrator_r1.ps1"
V22_044_WRAPPER = "scripts/v22/run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1"
RECOMMENDED_COMMAND = r".\scripts\v22\run_v22_044_daily_single_entrypoint_freeze_and_guard_r1.ps1 -Execute"
CHILD_COMMAND_TEXT = r".\scripts\v22\run_v22_040_daily_moomoo_oneclick_refresh_orchestrator_r1.ps1 -Execute"


EXPECTED_V22_040_STATUS = "PASS_V22_040_DAILY_MOOMOO_ONECLICK_REFRESH_COMPLETE"
EXPECTED_V22_040_DECISION = "DAILY_MOOMOO_REFRESH_COMPLETE_RESEARCH_ONLY"

ChildRunner = Callable[[list[str], Path, Path, Path], int]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def powershell_exe() -> str:
    return "powershell"


def default_child_runner(cmd: list[str], cwd: Path, stdout_path: Path, stderr_path: Path) -> int:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)
    stdout_path.write_text(proc.stdout or "", encoding="utf-8")
    stderr_path.write_text(proc.stderr or "", encoding="utf-8")
    return proc.returncode


def child_command(repo_root: Path) -> list[str]:
    return [
        powershell_exe(),
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(repo_root / ACCEPTED_ENTRYPOINT_WRAPPER),
        "-Execute",
    ]


def base_payload(repo_root: Path, output_dir: Path, execute: bool) -> dict[str, Any]:
    return {
        "revision": REVISION,
        "stage": STAGE,
        "summary_path": str(output_dir / "v22_044_summary.json"),
        "run_mode": "EXECUTE" if execute else "DRY_RUN",
        "repo_root": str(repo_root),
        "output_dir": str(output_dir),
        "accepted_entrypoint_name": ACCEPTED_ENTRYPOINT_NAME,
        "accepted_entrypoint_wrapper": ACCEPTED_ENTRYPOINT_WRAPPER,
        "recommended_command": RECOMMENDED_COMMAND,
        "child_v22_040_command": CHILD_COMMAND_TEXT,
        "research_only": True,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "factor_promotion_allowed": False,
        "direct_market_data_fetch_allowed": False,
        "direct_child_strategy_invocation_allowed": False,
        "hard_gate_passed": False,
        "failed_gate_names": [],
        "current_entrypoint_pointer_written": False,
        "current_entrypoint_markdown_written": False,
        "v22_040_wrapper_path": str(repo_root / ACCEPTED_ENTRYPOINT_WRAPPER),
        "v22_040_wrapper_exists": (repo_root / ACCEPTED_ENTRYPOINT_WRAPPER).exists(),
        "v22_040_child_exit_code": None,
        "v22_040_summary_path": str(external_v22_040_summary() if production_repo(repo_root) else (repo_root / V22_040_SUMMARY_REL)),
        "v22_040_child_stdout_log_path": str(output_dir / "v22_040_child_stdout.log"),
        "v22_040_child_stderr_log_path": str(output_dir / "v22_040_child_stderr.log"),
        "v22_040_child_start_utc": "",
        "v22_040_child_end_utc": "",
        "canonical_latest_date": "",
        "abcde_latest_date": "",
        "dram_latest_price_date": "",
        "same_date_comparable_all_strategies": False,
        "data_gap_days": None,
    }


def daily_root() -> Path:
    # Keep this module independently executable without a repo-local output.
    from sys import path as sys_path
    common = Path(__file__).resolve().parents[1]
    if str(common) not in sys_path: sys_path.insert(0, str(common))
    from common.storage_paths import get_daily_root
    return get_daily_root()


def external_v22_040_summary() -> Path:
    return daily_root() / "current" / "V22.040_DAILY_MOOMOO_ONECLICK_REFRESH_ORCHESTRATOR_R1" / "v22_040_summary.json"


def production_repo(repo_root: Path) -> bool:
    return repo_root.resolve() == Path(__file__).resolve().parents[2]


def date_text(value: Any) -> str:
    return str(value or "").strip()[:10]


def validate_hard_gates(payload: dict[str, Any], child_summary: dict[str, Any]) -> list[str]:
    failed: list[str] = []
    if not payload["v22_040_wrapper_exists"]:
        failed.append("v22_040_wrapper_exists")
    if payload["v22_040_child_exit_code"] not in (0, None):
        failed.append("v22_040_child_exit_code_zero")
    if not Path(payload["v22_040_summary_path"]).exists():
        failed.append("v22_040_summary_exists")

    canonical = date_text(child_summary.get("canonical_latest_date"))
    abcde = date_text(child_summary.get("abcde_latest_date"))
    dram = date_text(child_summary.get("dram_latest_price_date"))
    payload["canonical_latest_date"] = canonical
    payload["abcde_latest_date"] = abcde
    payload["dram_latest_price_date"] = dram
    payload["same_date_comparable_all_strategies"] = child_summary.get("same_date_comparable_all_strategies") is True
    payload["data_gap_days"] = child_summary.get("data_gap_days")

    if child_summary.get("final_status") != EXPECTED_V22_040_STATUS:
        failed.append("final_status")
    if child_summary.get("final_decision") != EXPECTED_V22_040_DECISION:
        failed.append("final_decision")
    if child_summary.get("same_date_comparable_all_strategies") is not True:
        failed.append("same_date_comparable_all_strategies")
    if child_summary.get("data_gap_days") != 0:
        failed.append("data_gap_days")
    if child_summary.get("broker_action_allowed") is not False:
        failed.append("broker_action_allowed_false")
    if child_summary.get("official_adoption_allowed") is not False:
        failed.append("official_adoption_allowed_false")
    if not canonical:
        failed.append("canonical_latest_date_exists")
    if not abcde:
        failed.append("abcde_latest_date_exists")
    if not dram:
        failed.append("dram_latest_price_date_exists")
    if not (canonical and abcde and dram and canonical == abcde == dram):
        failed.append("strategy_dates_equal")
    return failed


def pointer_payload(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "revision": REVISION,
        "accepted_current_entrypoint_name": STAGE,
        "accepted_current_entrypoint_wrapper": V22_044_WRAPPER,
        "recommended_command": RECOMMENDED_COMMAND,
        "accepted_child_orchestrator_name": ACCEPTED_ENTRYPOINT_NAME,
        "accepted_child_orchestrator_wrapper": ACCEPTED_ENTRYPOINT_WRAPPER,
        "accepted_child_orchestrator_command": CHILD_COMMAND_TEXT,
        "old_v21_daily_wrappers": "historical_only",
        "direct_child_strategy_wrappers": "not_current_daily_entrypoints",
        "research_only_gates_remain_enforced": True,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "factor_promotion_allowed": False,
        "direct_market_data_fetch_allowed": False,
        "direct_child_strategy_invocation_allowed": False,
        "latest_validated_summary_path": summary["summary_path"],
        "v22_040_summary_path": summary["v22_040_summary_path"],
        "canonical_latest_date": summary["canonical_latest_date"],
        "abcde_latest_date": summary["abcde_latest_date"],
        "dram_latest_price_date": summary["dram_latest_price_date"],
        "same_date_comparable_all_strategies": summary["same_date_comparable_all_strategies"],
        "data_gap_days": summary["data_gap_days"],
        "updated_utc": utc_now(),
    }


def pointer_markdown(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Current Daily Research Entrypoint",
            "",
            f"Run this exact command: `{RECOMMENDED_COMMAND}`",
            "",
            f"Accepted child V22.040 command: `{CHILD_COMMAND_TEXT}`",
            "",
            "What it does:",
            "- Freezes V22.044 as the current daily research wrapper.",
            "- Invokes only the accepted V22.040 daily Moomoo one-click refresh orchestrator in Execute mode.",
            "- Validates V22.040 hard gates before updating current entrypoint pointers.",
            "",
            "What it does not do:",
            "- It does not call old V21 daily wrappers directly.",
            "- It does not call ABCDE, DRAM, option, or forward scripts directly.",
            "- It does not fetch market data directly or mutate factor weights.",
            "- It does not place orders, unlock trade, approve broker action, or approve official adoption.",
            "",
            "Research-only warnings:",
            "- `research_only = true`",
            "- `broker_action_allowed = false`",
            "- `official_adoption_allowed = false`",
            "",
            f"Latest validated summary path: `{summary['summary_path']}`",
            f"Latest V22.040 child summary path: `{summary['v22_040_summary_path']}`",
            f"Latest canonical date: `{summary['canonical_latest_date'] or 'UNAVAILABLE'}`",
            f"Latest ABCDE date: `{summary['abcde_latest_date'] or 'UNAVAILABLE'}`",
            f"Latest DRAM date: `{summary['dram_latest_price_date'] or 'UNAVAILABLE'}`",
            "",
        ]
    )


def write_pointers(repo_root: Path, summary: dict[str, Any]) -> tuple[bool, bool]:
    if not production_repo(repo_root):
        write_json_atomic(repo_root / POINTER_JSON_REL, pointer_payload(summary))
        (repo_root / POINTER_MD_REL).write_text(pointer_markdown(summary), encoding="utf-8")
        return True, True
    pointer_dir = daily_root() / "current" / STAGE
    write_json_atomic(pointer_dir / "current_daily_research_entrypoint.json", pointer_payload(summary))
    tmp = pointer_dir / "CURRENT_DAILY_RESEARCH_ENTRYPOINT.md.tmp"
    tmp.write_text(pointer_markdown(summary), encoding="utf-8")
    os.replace(tmp, pointer_dir / "CURRENT_DAILY_RESEARCH_ENTRYPOINT.md")
    return True, True


def persist_summary(output_dir: Path, payload: dict[str, Any]) -> None:
    write_json_atomic(output_dir / "v22_044_summary.json", payload)


def run(repo_root: Path, execute: bool = False, child_runner: ChildRunner | None = None) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    output_dir = (daily_root() / "current" / STAGE) if production_repo(repo_root) else (repo_root / OUT_REL)
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = base_payload(repo_root, output_dir, execute)
    payload["run_id"] = uuid.uuid4().hex
    payload["run_start_utc"] = utc_now()

    if not payload["v22_040_wrapper_exists"]:
        payload["failed_gate_names"] = ["v22_040_wrapper_exists"]
        payload["final_status"] = FAIL_STATUS
        payload["final_decision"] = BLOCKED_DECISION
        payload["run_end_utc"] = utc_now()
        persist_summary(output_dir, payload)
        return payload

    child_summary_path = external_v22_040_summary() if production_repo(repo_root) else (repo_root / V22_040_SUMMARY_REL)
    if not execute:
        payload["final_status"] = WARN_STATUS
        payload["final_decision"] = DRY_RUN_DECISION
        payload["run_end_utc"] = utc_now()
        persist_summary(output_dir, payload)
        return payload

    runner = child_runner or default_child_runner
    stdout_path = output_dir / "v22_040_child_stdout.log"
    stderr_path = output_dir / "v22_040_child_stderr.log"
    payload["v22_040_child_start_utc"] = utc_now()
    old_run_id = os.environ.get("USTQ_DAILY_RUN_ID")
    os.environ["USTQ_DAILY_RUN_ID"] = payload["run_id"]
    try:
        payload["v22_040_child_exit_code"] = runner(child_command(repo_root), repo_root, stdout_path, stderr_path)
    finally:
        if old_run_id is None: os.environ.pop("USTQ_DAILY_RUN_ID", None)
        else: os.environ["USTQ_DAILY_RUN_ID"] = old_run_id
    payload["v22_040_child_end_utc"] = utc_now()

    child_summary = read_json(child_summary_path) if child_summary_path.exists() else {}
    if production_repo(repo_root) and child_summary.get("run_id") != payload["run_id"]:
        payload["run_id_match"] = False
    else:
        payload["run_id_match"] = True
    failed = validate_hard_gates(payload, child_summary)
    if not payload["run_id_match"]: failed.append("run_id_match")
    payload["failed_gate_names"] = failed
    payload["hard_gate_passed"] = not failed

    if failed:
        payload["final_status"] = FAIL_STATUS
        payload["final_decision"] = BLOCKED_DECISION
    else:
        payload["final_status"] = PASS_STATUS
        payload["final_decision"] = PASS_DECISION
        payload["current_entrypoint_pointer_written"], payload["current_entrypoint_markdown_written"] = write_pointers(repo_root, payload)

    payload["run_end_utc"] = utc_now()
    persist_summary(output_dir, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)

    payload = run(args.repo_root, execute=args.execute)
    print(f"final_status={payload['final_status']}")
    print(f"final_decision={payload['final_decision']}")
    print(f"recommended_command={payload['recommended_command']}")
    print(f"child_v22_040_command={payload['child_v22_040_command']}")
    print(f"v22_040_child_exit_code={payload['v22_040_child_exit_code']}")
    print(f"v22_040_summary_path={payload['v22_040_summary_path']}")
    print(f"canonical_latest_date={payload['canonical_latest_date']}")
    print(f"abcde_latest_date={payload['abcde_latest_date']}")
    print(f"dram_latest_price_date={payload['dram_latest_price_date']}")
    print(f"same_date_comparable_all_strategies={payload['same_date_comparable_all_strategies']}")
    print(f"data_gap_days={payload['data_gap_days']}")
    print(f"broker_action_allowed={payload['broker_action_allowed']}")
    print(f"official_adoption_allowed={payload['official_adoption_allowed']}")
    print(f"hard_gate_passed={payload['hard_gate_passed']}")
    print(f"failed_gate_names={','.join(payload['failed_gate_names'])}")
    print(f"summary_path={payload['summary_path']}")
    return 0 if payload["hard_gate_passed"] or not args.execute else 1


if __name__ == "__main__":
    raise SystemExit(main())
