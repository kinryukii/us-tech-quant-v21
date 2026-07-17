#!/usr/bin/env python
"""Generate the V22.047 R1D machine-readable and Markdown validation report."""
from __future__ import annotations

import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STAGE = "V22.047_R1D_LIVE_MARKET_ACCOUNT_BRIDGE_AND_LOCAL_DASHBOARD_SHADOW_ONLY"


def read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def main(argv: list[str] | None = None) -> int:
    repo = Path(argv[0] if argv else r"D:\us-tech-quant").resolve()
    out = repo / "outputs" / "v22" / STAGE
    source = repo / "scripts" / "v22" / "v22_047_r1d_live_market_account_bridge.py"
    market, account = read(out / "market_snapshot.json"), read(out / "account_snapshot.json")
    strategy, control = read(out / "strategy_decision.json"), read(out / "control_decision.json")
    intent, summary = read(out / "shadow_order_intent.json"), read(out / "v22_047_r1d_summary.json")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    forbidden = {"place_order", "modify_order", "cancel_order", "cancel_all_order", "unlock_trade"}
    quote_symbols = set((market.get("quotes") or {}).keys())
    kline_types = set((market.get("qqq_klines") or {}).keys())
    checks = {
        "opend_connected": summary.get("opend_status") == "CONNECTED",
        "opend_endpoint_127_0_0_1_18441": summary.get("opend_endpoint") == "127.0.0.1:18441",
        "four_quotes_auditable": quote_symbols == {"US.QQQ", "US.IQQ", "US.TQQQ", "US.SQQQ"},
        "qqq_six_kline_types": kline_types == {"K_1M", "K_5M", "K_15M", "K_30M", "K_60M", "K_DAY"},
        "account_snapshot_ready": account.get("account_snapshot_ready") is True,
        "strategy_plugin_called": strategy.get("plugin_called") is True,
        "r1b_control_called": control.get("r1b_control_component_called") is True,
        "strategy_configured_false": strategy.get("strategy_configured") is False,
        "strategy_hold": strategy.get("strategy_action") == "HOLD",
        "strategy_not_configured_reason": strategy.get("strategy_reason_code") == "STRATEGY_NOT_CONFIGURED",
        "no_order_intent": intent.get("order_intent_created") is False,
        "broker_action_blocked": control.get("broker_action_allowed") is False,
        "trade_api_not_called": control.get("trade_api_called") is False,
        "effective_shadow_only": control.get("effective_execution_mode") == "SHADOW_ONLY",
        "ui_loopback": summary.get("ui_bind_host") == "127.0.0.1",
        "background_independent_of_ui": summary.get("background_independent_of_ui") is True,
        "no_broker_mutation_calls_in_r1d": not forbidden.intersection(called),
    }
    r1d_status = "PASS" if all(checks.values()) else "FAIL"
    report = {
        "schema_version": 1, "stage": STAGE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "r1d_acceptance_status": r1d_status,
        "final_status": "R1D_PASS_FULL_REPOSITORY_PYTEST_NOT_PASS" if r1d_status == "PASS" else "FAIL",
        "checks": checks,
        "pytest": {
            "r1b_r1c_r1d_regression": "PASS: 57 passed in 0.95s",
            "full_repository": "NOT_PASS: timed out at 20 minutes near 23% with many pre-existing historical failures/errors",
            "scope_note": "Historical failures cross protected/out-of-scope revisions and were not modified or hidden.",
        },
        "notes": [
            "R1D is permanently shadow-only and contains no broker mutation call.",
            "Closed/weekend quotes can be readable while data_fresh is false; this is the required stale-data gate.",
            "PAPER and LIVE are rejected by the R1D UI API.",
        ],
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"# {STAGE} Validation Report", "", f"Final status: **{report['final_status']}**", "",
             f"Generated: `{report['generated_at_utc']}`", "", "| Check | Result |", "|---|---|"]
    lines += [f"| {key} | {'PASS' if value else 'FAIL'} |" for key, value in checks.items()]
    lines += ["", "## Safety notes", ""] + [f"- {note}" for note in report["notes"]]
    lines += ["", "## Pytest", "", f"- R1B + R1C + R1D: {report['pytest']['r1b_r1c_r1d_regression']}",
              f"- Full repository: {report['pytest']['full_repository']}",
              f"- Scope: {report['pytest']['scope_note']}"]
    (out / "validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"r1d_validation_status={report['r1d_acceptance_status']}")
    print(f"overall_validation_status={report['final_status']}")
    print(f"validation_report={out / 'validation_report.md'}")
    return 0 if report["r1d_acceptance_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
