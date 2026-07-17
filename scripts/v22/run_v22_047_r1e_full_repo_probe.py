#!/usr/bin/env python
"""Run a bounded full-repository pytest probe and classify every observed failure."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STAGE = "V22.047_R1E_WINDOWS_AUTOSTART_SERVICE_HARDENING_AND_DASHBOARD_V2_SHADOW_ONLY"
PROTECTED = ["scripts/v22/test_v22_040*", "scripts/v22/test_v22_044*", "scripts/v22/v22_040*", "scripts/v22/v22_044*"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read(path: Path, default: Any) -> Any:
    try: return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception: return default


def write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def classify(item: dict[str, Any]) -> str:
    node = str(item.get("nodeid", "")).replace("\\", "/").lower()
    error = str(item.get("error", "")).lower()
    if "v22_047_r1d" in node or "v22_047_r1e" in node:
        return "R1D_OR_R1E_REGRESSION"
    if "v22_040" in node or "v22_044" in node:
        return "PROTECTED_LEGACY_FAILURE"
    if any(token in error for token in ("permissionerror", "access is denied", "拒绝访问", "modulenotfounderror", "connectionerror")):
        return "ENVIRONMENT_DEPENDENT_FAILURE"
    if node.startswith("scripts/v"):
        return "PRE_EXISTING_BASELINE_FAILURE"
    return "UNKNOWN_REQUIRES_REVIEW"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--repo-root", default=r"D:\us-tech-quant")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--finalize-existing", action="store_true")
    args = parser.parse_args(argv)
    repo = Path(args.repo_root).resolve(); out = repo / "outputs" / "v22" / STAGE
    progress_path = out / "full_repo_test_progress.json"; log_path = out / "full_repo_pytest_output.log"
    out.mkdir(parents=True, exist_ok=True)
    if args.finalize_existing:
        progress = read(progress_path, {"collected": 0, "completed": 0, "failures": [], "collection_errors": []})
        observed = list(progress.get("failures", [])) + list(progress.get("collection_errors", []))
        classified = [{**item, "classification": classify(item)} for item in observed]
        counts: dict[str, int] = {}
        for item in classified: counts[item["classification"]] = counts.get(item["classification"], 0) + 1
        progress.update({"probe_finished_at_utc": now(), "timeout_seconds": args.timeout_seconds,
                         "timed_out": True, "pytest_return_code": -9, "full_repo_pass_claimed": False})
        write(progress_path, progress)
        write(out / "full_repo_known_failures.json", {"schema_version": 1, "timestamp_utc": now(),
              "failure_list_complete": False, "timed_out": True, "classifications": counts, "failures": classified})
        write(out / "protected_legacy_test_allowlist.json", {"schema_version": 1, "timestamp_utc": now(),
              "protected_patterns": PROTECTED, "policy": "Report but do not modify V22.040 or V22.044 failures during R1E."})
        print("timed_out=True"); print(f"progress_ratio={progress.get('progress_ratio', 0)}")
        print(f"observed_failures={len(classified)}"); print("full_repo_pass_claimed=False")
        return 1
    for path in (progress_path, log_path):
        try: path.unlink()
        except FileNotFoundError: pass
    env = os.environ.copy(); env["R1E_PYTEST_PROGRESS_PATH"] = str(progress_path)
    env["PYTHONPATH"] = os.pathsep.join([str(repo / "scripts" / "v21"), str(repo / "scripts" / "v22"), env.get("PYTHONPATH", "")])
    command = [sys.executable, "-m", "pytest", "-q", "-p", "v22_047_r1e_pytest_progress_plugin"]
    started = now(); timed_out = False; return_code = None
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        process = subprocess.Popen(command, cwd=str(repo), env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            return_code = process.wait(timeout=args.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            else:
                process.kill()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = -9
    progress = read(progress_path, {"collected": 0, "completed": 0, "failures": [], "collection_errors": []})
    observed = list(progress.get("failures", [])) + list(progress.get("collection_errors", []))
    classified = [{**item, "classification": classify(item)} for item in observed]
    counts: dict[str, int] = {}
    for item in classified: counts[item["classification"]] = counts.get(item["classification"], 0) + 1
    progress.update({"probe_started_at_utc": started, "probe_finished_at_utc": now(), "timeout_seconds": args.timeout_seconds,
                     "timed_out": timed_out, "pytest_return_code": return_code,
                     "full_repo_pass_claimed": return_code == 0 and not timed_out})
    write(progress_path, progress)
    write(out / "full_repo_known_failures.json", {
        "schema_version": 1, "timestamp_utc": now(), "failure_list_complete": not timed_out,
        "timed_out": timed_out, "classifications": counts, "failures": classified,
    })
    write(out / "protected_legacy_test_allowlist.json", {
        "schema_version": 1, "timestamp_utc": now(), "protected_patterns": PROTECTED,
        "policy": "Report but do not modify V22.040 or V22.044 failures during R1E.",
    })
    print(f"timed_out={timed_out}"); print(f"progress_ratio={progress.get('progress_ratio', 0)}")
    print(f"observed_failures={len(classified)}"); print(f"full_repo_pass_claimed={progress['full_repo_pass_claimed']}")
    return 0 if progress["full_repo_pass_claimed"] else 1


if __name__ == "__main__": raise SystemExit(main())
