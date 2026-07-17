#!/usr/bin/env python
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path); assert spec and spec.loader
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module; spec.loader.exec_module(module); return module


def main(argv=None):
    repo = Path(argv[0] if argv else r"D:\us-tech-quant").resolve()
    module_path = repo / "scripts" / "v22" / "v22_047_r1h_paper_execution_order_lifecycle_and_reconciliation.py"
    h = load(module_path, "r1h_validator"); summary = h.write_summary(repo); paths = h.Paths(repo)
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    real_literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value == "TrdEnv.REAL"]
    checks = {
        "final_status": summary.get("final_status") == h.FINAL_STATUS,
        "strategy_enabled_configured": summary.get("strategy_enabled") is True and summary.get("strategy_configured") is True,
        "default_shadow": summary.get("default_execution_mode") == "SHADOW",
        "paper_available_disarmed": summary.get("paper_available") is True and summary.get("paper_armed") is False,
        "live_unavailable": summary.get("live_available") is False,
        "no_real_api_called": summary.get("real_trade_api_called") is False,
        "real_literal_only_guarded": len(real_literals) <= 1,
        "required_ledgers": all((paths.output / n).exists() for n in ("paper_cash_ledger.jsonl", "paper_position_ledger.jsonl", "paper_order_ledger.jsonl", "paper_deal_ledger.jsonl", "paper_nav_history.csv")),
    }
    report = {"schema_version": 1, "final_status": h.FINAL_STATUS if all(checks.values()) else "R1H_VALIDATION_FAILED", "checks": checks, "broker_action_allowed": False, "real_trade_api_called": False}
    (paths.output / "validation_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"final_status={report['final_status']}"); return 0 if all(checks.values()) else 1


if __name__ == "__main__": raise SystemExit(main(sys.argv[1:]))
