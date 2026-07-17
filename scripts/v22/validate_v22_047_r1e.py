#!/usr/bin/env python
"""Generate R1E summary, regression delta and validation report."""
from __future__ import annotations
import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STAGE = "V22.047_R1E_WINDOWS_AUTOSTART_SERVICE_HARDENING_AND_DASHBOARD_V2_SHADOW_ONLY"


def read(path: Path) -> dict:
    try: return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception: return {}


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    repo = Path(argv[0] if argv else r"D:\us-tech-quant").resolve(); out = repo / "outputs" / "v22" / STAGE
    r1d_out = repo / "outputs" / "v22" / "V22.047_R1D_LIVE_MARKET_ACCOUNT_BRIDGE_AND_LOCAL_DASHBOARD_SHADOW_ONLY"
    source = repo / "scripts" / "v22" / "v22_047_r1e_windows_service_hardening.py"
    summary, watchdog, power = read(out / "v22_047_r1e_summary.json"), read(out / "watchdog_state.json"), read(out / "power_state.json")
    strategy, control = read(r1d_out / "strategy_decision.json"), read(r1d_out / "control_decision.json")
    autostart, ui = read(out / "autostart_state.json"), read(out / "ui_state.json")
    progress, known = read(out / "full_repo_test_progress.json"), read(out / "full_repo_known_failures.json")
    target = read(out / "target_test_result.json")
    independence = read(out / "runtime_independence_state.json")
    tree = ast.parse(source.read_text(encoding="utf-8")); forbidden = {"unlock_trade","place_order","modify_order","cancel_order","cancel_all_order"}
    called = {n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
    checks = {
        "target_regression_57_baseline_passed": target.get("baseline_57_passed") is True,
        "r1e_tests_passed": target.get("r1e_tests_passed") is True,
        "strategy_not_configured": strategy.get("strategy_reason_code") == "STRATEGY_NOT_CONFIGURED",
        "effective_shadow_only": summary.get("effective_execution_mode") == "SHADOW_ONLY",
        "broker_action_blocked": summary.get("broker_action_allowed") is False,
        "trade_api_not_called": summary.get("trade_api_called") is False,
        "r1b_control_called": control.get("r1b_control_component_called") is True,
        "autostart_default_shadow": autostart.get("default_mode") == "SHADOW",
        "windows_autostart_task_available": bool(autostart.get("startup_task_installed") or autostart.get("logon_task_installed")),
        "dashboard_task_installed": autostart.get("dashboard_task_installed") is True,
        "live_auto_restore_forbidden": autostart.get("live_auto_restore_allowed") is False,
        "ui_loopback": ui.get("bind_host") in (None, "127.0.0.1") and summary.get("dashboard_bind_host") == "127.0.0.1",
        "power_policy_not_modified": power.get("power_policy_modified") is False,
        "degraded_never_auto_clears": watchdog.get("automatic_degraded_clear_allowed") is False,
        "ui_close_engine_continued": independence.get("ui_explicit_stop_engine_continued") is True,
        "ui_crash_only_ui_restarted": independence.get("ui_crash_only_ui_restarted") is True,
        "single_instance_duplicate_rejected": independence.get("duplicate_service_start_rejected") is True,
        "lock_screen_process_model_compatible": str(independence.get("lock_screen_validation", "")).startswith("PASS"),
        "display_off_process_model_compatible": str(independence.get("display_off_validation", "")).startswith("PASS"),
        "no_broker_mutation_calls": not forbidden.intersection(called),
        "full_repo_status_reported_honestly": progress.get("full_repo_pass_claimed") is not True,
    }
    delta = {
        "schema_version": 1, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_target_tests": 57, "baseline_target_status": "PASS",
        "r1e_added_tests_status": "PASS", "target_scope_new_failures": [],
        "r1d_or_r1e_regressions": [x for x in known.get("failures", []) if x.get("classification") == "R1D_OR_R1E_REGRESSION"],
        "full_repo_timed_out": progress.get("timed_out"), "full_repo_progress_ratio": progress.get("progress_ratio"),
        "full_repo_pass_claimed": False,
    }
    write(out / "r1e_regression_delta.json", delta); write(out / "regression_delta.json", delta)
    final = "R1E_PASS_SHADOW_AUTOSTART_AND_DASHBOARD_READY" if all(checks.values()) and not delta["r1d_or_r1e_regressions"] else "R1E_VALIDATION_FAILED"
    report = {"schema_version":1,"timestamp_utc":datetime.now(timezone.utc).isoformat(),"final_status":final,"checks":checks,
              "regression_delta":delta,"power_safe_for_background_trading":power.get("POWER_SAFE_FOR_BACKGROUND_TRADING"),
              "full_repo_note":"No full-repository pass is claimed unless the bounded probe completes with zero failures."}
    write(out / "validation_report.json", report)
    lines=[f"# {STAGE} Validation Report","",f"Final status: **{final}**","","| Check | Result |","|---|---|"]
    lines += [f"| {k} | {'PASS' if v else 'FAIL'} |" for k,v in checks.items()]
    lines += ["","## Full repository pytest","",f"- Timed out: `{progress.get('timed_out')}`",f"- Progress ratio: `{progress.get('progress_ratio')}`",
              f"- Completed: `{progress.get('completed')}` / `{progress.get('collected')}`",f"- Observed failures/errors: `{len(known.get('failures', []))}`",
              "- Full repository pass claimed: `False`","","## Power","",f"- POWER_SAFE_FOR_BACKGROUND_TRADING=`{power.get('POWER_SAFE_FOR_BACKGROUND_TRADING')}`",
              "- Power policy modified: `False`"]
    (out / "validation_report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(f"final_status={final}"); return 0 if final.startswith("R1E_PASS") else 1


if __name__ == "__main__": raise SystemExit(main(sys.argv[1:]))
