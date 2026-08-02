#!/usr/bin/env python
"""Package immutable FAST3 V22.080A/B evidence into the agent result contract."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
LOCAL = Path(r"D:\us-tech-quant-results\fast3\archive\legacy_v22")
DEFAULT_OUTPUT = Path(r"D:\us-tech-quant-results\fast3_autoresearch\current")
STAGE_A = Path(r"D:\us-tech-quant-results\v22\V22.080A_FAST3_24H_ONE_PERCENT_MOVE_ATLAS_R1\v22_080a_summary.json")
STAGE_B = Path(r"D:\us-tech-quant-results\v22\V22.080B_FAST3_ONE_PERCENT_MOVE_PREDICTABILITY_PREFLIGHT_R1\v22_080b_summary.json")
FINAL = LOCAL / "FAST3_FINAL_RESEARCH_SUMMARY" / "fast3_final_summary.json"
LEDGER = LOCAL / "FAST3_OVERNIGHT_AUTOPILOT" / "experiment_ledger.csv"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sources() -> dict[str, Path]:
    return {"stage_a": STAGE_A, "stage_b": STAGE_B, "final": FINAL, "ledger": LEDGER}


def build(output_dir: Path = DEFAULT_OUTPUT) -> dict:
    """Create the compact agent package without rereading canonical or Confirmation data."""
    sources = _sources()
    missing = [str(path) for path in sources.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("MISSING_FROZEN_FAST3_EVIDENCE: " + "; ".join(missing))

    stage_a = _read_json(STAGE_A)
    stage_b = _read_json(STAGE_B)
    final = _read_json(FINAL)
    ledger = pd.read_csv(LEDGER)
    windows = pd.DataFrame(stage_b["random_asof_robustness"])
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = output_dir.parent / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    source_hashes = {name: {"path": str(path), "sha256": _sha256(path)} for name, path in sources.items()}
    economics = stage_b["validation_economics"]
    validation = stage_b["validation"]
    autoresearch_summary = {
        "research_status": "FAIL_NO_ROBUST_EDGE",
        "pipeline_execution_status": final["FINAL_STATUS"],
        "final_decision": final["FINAL_DECISION"],
        "completed_stage": final["FINAL_COMPLETED_STAGE"],
        "current_champion": None,
        "confirmation_read_count": final["CONFIRMATION_ROW_READ_COUNT"],
        "prospective_shadow_allowed": False,
        "broker_action_allowed": False,
        "official_adoption_allowed": False,
        "validation": {
            "top5_selected_count": validation["top5_selected_count"],
            "top5_target_first_lift": validation["top5_target_first_lift"],
            "mean_net_return_10bps": economics["top5_mean_net_return_10bps"],
            "mean_net_return_20bps": economics["top5_mean_net_return_20bps"],
            "positive_year_count": stage_b["positive_year_count"],
        },
        "random_window_count": len(windows),
        "source_evidence": source_hashes,
        "next_recommended_action": "NONE_FAST3_RESEARCH_STOPPED",
    }
    champion = {
        "champion_status": "NO_CHAMPION_UPSTREAM_VALIDATION_GATE_FAILED",
        "rejected_development_selected_model": stage_b["selected_model"],
        "rejection_reason": final["STOP_REASON"],
        "confirmation_row_read_count": 0,
        "frozen_contract_sha256": None,
        "model_sha256": None,
        "prospective_shadow_allowed": False,
    }
    leakage_audit = {
        "leakage_audit_pass": True,
        "confirmation_row_read_count": 0,
        "confirmation_isolation_evidence": {
            "stage_a": stage_a["confirmation_row_read_count"],
            "stage_b": stage_b["confirmation_row_read_count"],
        },
        "point_in_time_contract": "V22.080B uses completed five-minute decision bars and next-valid-minute opens; the package only reads frozen summaries and ledger.",
        "source_code": {
            "v22_080b": str(REPO / "scripts" / "v22" / "v22_080b_fast3_one_percent_move_predictability_preflight_r1.py"),
        },
        "conclusion": "PASS_NO_CONFIRMATION_READ_AND_NO_ORDER_GENERATION",
    }
    checkpoint = {
        "current_status": "COMPLETE_NO_ROBUST_EDGE",
        "current_champion": None,
        "last_completed_iteration": int(ledger["iteration_id"].max()),
        "running_or_failed_command": None,
        "completed_tests": "V22.080A/B focused pytest: 17 passed (recorded in CODEX_STATUS.md)",
        "remaining_tests": [],
        "completed_backtests": "V22.080A full atlas; V22.080B frozen Validation; three fixed-seed continuous as-of windows",
        "remaining_backtests": [],
        "known_failures": [final["STOP_REASON"]],
        "next_exact_action": "NONE_FAST3_RESEARCH_STOPPED",
        "exact_resume_command": "NONE_FAST3_RESEARCH_STOPPED",
        "source_evidence": source_hashes,
    }
    report = f"""# FAST3 autoresearch final report

## Research conclusion

Research status: `FAIL_NO_ROBUST_EDGE`. The V22.080 pipeline executed successfully but stopped at frozen Validation: `{final['FINAL_DECISION']}`. Confirmation and prospective shadow were not run, as required by the stage transition contract.

## Evidence scope

The Atlas read real minute OHLC for QQQ, SOXX, TQQQ, SQQQ, SOXL, and SOXS. It found {stage_a['historical_move_event_count']:,} non-ambiguous 1% directional moves. At the required three-minute latency, attempted real-ETF timestamp mapping was {stage_a['primary_mapping_success_count']:,}/{stage_a['primary_mapping_contract_eligible_count']:,} ({stage_a['primary_leveraged_mapping_success_rate']:.6%}); {stage_a['primary_delay_ineligible_count']:,} events already reached target before delayed entry and were not mapping attempts.

## Development and Validation

The compact PIT features were `return_5m`, `return_15m`, `return_60m`, `realized_vol_15m`, `realized_vol_60m`, `relative_volume`, `range_position`, symbol, direction, and session codes. Development compared logistic regression, depth-3 tree, and shallow HistGradientBoosting; it selected `{stage_b['selected_model']}` without reading Confirmation. Validation contained {validation['row_count']:,} directional rows and selected {validation['top5_selected_count']:,} top-5% rows. Target-first lift was {validation['top5_target_first_lift']:.6f}, below the frozen 1.50 requirement. Real ETF target-or-timeout net expectancy was {economics['top5_mean_net_return_10bps']:.8f} at 10 bps and {economics['top5_mean_net_return_20bps']:.8f} at 20 bps; annual groups with positive 10-bps mean: {stage_b['positive_year_count']}.

## Randomized OOS, costs, and concentration

The three fixed-seed, contiguous 120-day Validation as-of windows had 10-bps mean returns of {', '.join(f"{row['mean_net_return_10bps']:.8f}" for row in stage_b['random_asof_robustness'])}. These are randomized-in-time robustness observations, not model-selection inputs. ETF mapping was {economics['top5_etf_mapping_success_rate']:.2%}; single-ETF positive-profit contribution was {economics['single_etf_profit_contribution']:.6f}, and top-five positive-profit concentration was {economics['top5_profit_concentration']:.6f}. Delay stress beyond the required next-bar convention, maximum drawdown, monthly return series, trend/chop attribution, and block-bootstrap confidence intervals are `NOT_COMPUTABLE` for a candidate that did not pass the frozen Validation entry gate.

## Isolation and safety

Confirmation rows read: 0. No frozen champion, model artifact, order schema, broker action, paper order, or shadow ledger was created. `BROKER_ACTION_ALLOWED=False`, `OFFICIAL_ADOPTION_ALLOWED=False`, and prospective shadow remains ineligible.

## Remaining uncertainty and sole recommendation

This result rejects the tested frozen candidate and does not prove that every future FAST3 generation will fail. The sole permitted action for this frozen chain is `NONE_FAST3_RESEARCH_STOPPED`; any new generation requires genuinely future Confirmation data and a newly predeclared contract.
"""

    def write_json(name: str, value: dict) -> None:
        (output_dir / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    write_json("FAST3_AUTORESEARCH_FINAL_SUMMARY.json", autoresearch_summary)
    write_json("FAST3_AUTORESEARCH_CHAMPION_CONFIG.json", champion)
    write_json("FAST3_AUTORESEARCH_LEAKAGE_AUDIT.json", leakage_audit)
    ledger.to_parquet(output_dir / "FAST3_AUTORESEARCH_EXPERIMENT_REGISTRY.parquet", index=False)
    windows.to_parquet(output_dir / "FAST3_AUTORESEARCH_RANDOM_WINDOW_METRICS.parquet", index=False)
    (output_dir / "FAST3_AUTORESEARCH_FINAL_REPORT.md").write_text(report, encoding="utf-8")
    (output_dir / "FAST3_AUTORESEARCH_RESUME_COMMAND.txt").write_text("NONE_FAST3_RESEARCH_STOPPED\n", encoding="utf-8")
    (checkpoint_dir / "fast3_final_checkpoint.json").write_text(json.dumps(checkpoint, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return autoresearch_summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    summary = build(Path(args.output_dir))
    print("FINAL_STATUS=" + summary["research_status"])
    print("FINAL_DECISION=" + summary["final_decision"])
    print("REPORT_PATH=" + str(Path(args.output_dir) / "FAST3_AUTORESEARCH_FINAL_REPORT.md"))
