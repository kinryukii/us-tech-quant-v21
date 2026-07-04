#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

STAGE = "V21.249_SHADOW_CANDIDATE_SELECTION_AND_FORWARD_TRACKING_GATE"
OUT_REL = Path("outputs/v21") / STAGE
V247_REL = Path("outputs/v21/V21.247_REWEIGHTED_STRATEGY_REPLAY_AND_FORWARD_BACKTEST")
V246_REL = Path("outputs/v21/V21.246_FACTOR_WEIGHT_RECALIBRATION_CANDIDATES")
V245_REL = Path("outputs/v21/V21.245_STRATEGY_FACTOR_ATTRIBUTION_AND_FAILURE_DECOMPOSITION")
V243R1_REL = Path("outputs/v21/V21.243_R1_RECENT_0618_STRATEGY_SUCCESS_AUDIT_WITH_REPLAY")


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def fnum(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def bval(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def first_metric(summary: list[dict[str, str]], strategy: str, window: str = "1D", top_n: str = "20") -> dict[str, str]:
    for row in summary:
        if row.get("strategy") == strategy and row.get("forward_window") == window and str(row.get("top_n")) == top_n:
            return row
    return {}


def load_required(repo: Path) -> tuple[dict[str, Path], list[str]]:
    inputs = {
        "v21_247_summary": repo / V247_REL / "v21_247_summary.json",
        "v21_247_forward_summary": repo / V247_REL / "reweighted_strategy_forward_success_summary.csv",
        "v21_247_decision_matrix": repo / V247_REL / "reweighted_strategy_candidate_decision_matrix.csv",
        "v21_247_vs_e_r1": repo / V247_REL / "reweighted_strategy_vs_e_r1_audit.csv",
        "v21_247_vs_a1": repo / V247_REL / "reweighted_strategy_vs_a1_audit.csv",
        "v21_247_vs_dram": repo / V247_REL / "reweighted_strategy_vs_dram_audit.csv",
        "v21_247_tail": repo / V247_REL / "reweighted_strategy_tail_risk_audit.csv",
        "v21_247_turnover": repo / V247_REL / "reweighted_strategy_turnover_stability_audit.csv",
        "v21_246_summary": repo / V246_REL / "v21_246_summary.json",
        "v21_245_summary": repo / V245_REL / "v21_245_summary.json",
    }
    missing = [name for name, path in inputs.items() if not path.exists()]
    return inputs, missing


def risk_score(row: dict[str, Any], live_and_replay_present: bool) -> float:
    return (
        fnum(row.get("average_return"))
        + fnum(row.get("median_return")) * 0.5
        + fnum(row.get("p10_return")) * 0.35
        + fnum(row.get("worst5_return")) * 0.25
        + fnum(row.get("positive_rate")) * 0.01
        + (0.002 if live_and_replay_present else -0.004)
    )


def build_selection(repo: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, list[dict[str, Any]]]]:
    summary = read_rows(repo / V247_REL / "reweighted_strategy_forward_success_summary.csv")
    decisions = read_rows(repo / V247_REL / "reweighted_strategy_candidate_decision_matrix.csv")
    turnover = {r.get("strategy"): bval(r.get("live_and_replay_present")) for r in read_rows(repo / V247_REL / "reweighted_strategy_turnover_stability_audit.csv")}
    candidates = sorted({r.get("strategy", "") for r in summary if r.get("strategy")})
    candidate_decision = {r.get("candidate"): r for r in decisions}

    e_r1 = first_metric(summary, "E_R1")
    a1 = first_metric(summary, "A1")
    dram = first_metric(summary, "DRAM")
    rows_out: list[dict[str, Any]] = []
    for strategy in candidates:
        row = first_metric(summary, strategy)
        if not row:
            continue
        live_replay = turnover.get(strategy, False)
        avg = fnum(row.get("average_return"))
        med = fnum(row.get("median_return"))
        p10 = fnum(row.get("p10_return"))
        worst5 = fnum(row.get("worst5_return"))
        rs = risk_score(row, live_replay)
        matrix_row = {
            "candidate": strategy,
            "is_reweighted_candidate": strategy in candidate_decision,
            "v21_247_decision": candidate_decision.get(strategy, {}).get("decision", "BASELINE_OR_BENCHMARK"),
            "average_return": avg,
            "median_return": med,
            "excess_vs_e_r1": avg - fnum(e_r1.get("average_return")),
            "excess_vs_a1": avg - fnum(a1.get("average_return")),
            "excess_vs_dram": avg - fnum(dram.get("average_return")),
            "p10_return": p10,
            "worst5_return": worst5,
            "repeated_loser_count_proxy": 1 if p10 < -0.05 else 0,
            "turnover_proxy": "SOURCE_MODE_STABILITY",
            "turnover_materially_worse": not live_replay and strategy not in {"DRAM", "QQQ", "SOXX", "SMH"},
            "concentration_score_proxy": abs(worst5 - avg),
            "source_mode_robust": live_replay,
            "risk_adjusted_score": rs,
            "beats_e_r1_after_risk_adjustment": rs > risk_score(e_r1, turnover.get("E_R1", False)),
            "beats_a1_after_risk_adjustment": rs > risk_score(a1, turnover.get("A1", False)),
            "tail_risk_preserved_vs_e_r1": p10 >= fnum(e_r1.get("p10_return")) and worst5 >= fnum(e_r1.get("worst5_return")),
            "tail_risk_repaired_vs_a1": p10 >= fnum(a1.get("p10_return")) and worst5 >= fnum(a1.get("worst5_return")),
            "notes": "research-only shadow candidate gate; no adoption",
        }
        rows_out.append(matrix_row)

    eval_candidates = [r for r in rows_out if r["is_reweighted_candidate"]]
    supportive = [r for r in rows_out if r["v21_247_decision"] == "SUPPORTIVE_SHADOW_CANDIDATE"]
    best_return = max(eval_candidates or rows_out, key=lambda r: r["average_return"], default={})
    best_risk = max(eval_candidates or rows_out, key=lambda r: r["risk_adjusted_score"], default={})
    best_left_tail = max(eval_candidates or rows_out, key=lambda r: (r["tail_risk_repaired_vs_a1"], r["p10_return"], r["worst5_return"]), default={})
    low_turnover_pool = [r for r in eval_candidates if not r["turnover_materially_worse"]] or eval_candidates
    best_low_turnover = max(low_turnover_pool, key=lambda r: r["risk_adjusted_score"], default={})
    triggered = supportive[0]["candidate"] if supportive else ""
    triggered_row = next((r for r in rows_out if r["candidate"] == triggered), {})

    beats_e = bool(triggered_row.get("beats_e_r1_after_risk_adjustment")) and bool(triggered_row.get("tail_risk_preserved_vs_e_r1")) and not bool(triggered_row.get("turnover_materially_worse"))
    beats_a1 = bool(triggered_row.get("beats_a1_after_risk_adjustment")) and bool(triggered_row.get("tail_risk_repaired_vs_a1"))
    if beats_e:
        final_status = "SHADOW_TRACKING_READY"
        final_decision = "SHADOW_CANDIDATE_FORWARD_TRACKING_READY_RESEARCH_ONLY"
        recommended = triggered
        allowed = True
    elif beats_a1:
        final_status = "A1_REPAIR_ONLY"
        final_decision = "A1_LEFT_TAIL_REPAIR_RESEARCH_ONLY_KEEP_E_R1_AS_BEST"
        recommended = ""
        allowed = False
    elif not triggered:
        final_status = "KEEP_E_R1_AS_SHADOW_BEST"
        final_decision = "NO_REWEIGHTED_CANDIDATE_BEATS_E_R1_RESEARCH_ONLY"
        recommended = ""
        allowed = False
    else:
        final_status = "REJECT_CANDIDATE_RISK_OR_TURNOVER"
        final_decision = "SUPPORTIVE_RETURN_REJECTED_BY_RISK_OR_TURNOVER_RESEARCH_ONLY"
        recommended = ""
        allowed = False

    summary_payload = {
        "final_status": final_status,
        "final_decision": final_decision,
        "candidate_count_evaluated": len(rows_out),
        "candidate_that_triggered_supportive_shadow_status": triggered,
        "best_return_candidate": best_return.get("candidate", ""),
        "best_risk_adjusted_candidate": best_risk.get("candidate", ""),
        "best_left_tail_repair_candidate": best_left_tail.get("candidate", ""),
        "best_low_turnover_candidate": best_low_turnover.get("candidate", ""),
        "beats_e_r1_after_risk_adjustment": beats_e,
        "beats_a1_after_risk_adjustment": beats_a1,
        "recommended_shadow_tracking_candidate": recommended,
        "shadow_forward_tracking_allowed": allowed,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
        "input_files_mutated": False,
        "warning_count": 0 if final_status == "SHADOW_TRACKING_READY" else 1,
        "error_count": 0,
    }
    candidate_rows = [r for r in rows_out if r["is_reweighted_candidate"]]
    audits = {
        "vs_e_r1": [dict(r, benchmark_strategy="E_R1") for r in candidate_rows],
        "vs_a1": [dict(r, benchmark_strategy="A1") for r in candidate_rows],
        "vs_dram": [dict(r, benchmark_strategy="DRAM") for r in candidate_rows],
        "tail": [r for r in rows_out if r["is_reweighted_candidate"]],
        "turnover": [r for r in rows_out if r["is_reweighted_candidate"]],
        "source": [r for r in rows_out],
    }
    return rows_out, summary_payload, audits


def run(repo: Path, output_dir: Path | None = None) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    out.mkdir(parents=True, exist_ok=True)
    _inputs, missing = load_required(repo)
    if missing:
        summary = {
            "final_status": "FAIL_V21_249_REQUIRED_INPUT_MISSING",
            "final_decision": "SHADOW_CANDIDATE_SELECTION_BLOCKED_MISSING_INPUTS",
            "candidate_count_evaluated": 0,
            "candidate_that_triggered_supportive_shadow_status": "",
            "best_return_candidate": "",
            "best_risk_adjusted_candidate": "",
            "best_left_tail_repair_candidate": "",
            "best_low_turnover_candidate": "",
            "beats_e_r1_after_risk_adjustment": False,
            "beats_a1_after_risk_adjustment": False,
            "recommended_shadow_tracking_candidate": "",
            "shadow_forward_tracking_allowed": False,
            "official_adoption_allowed": False,
            "broker_action_allowed": False,
            "protected_outputs_modified": False,
            "input_files_mutated": False,
            "warning_count": 0,
            "error_count": len(missing),
        }
        write_json(out / "v21_249_summary.json", summary)
        write_csv(out / "shadow_forward_tracking_gate.csv", [{"gate": "required_inputs", "passed": False, "notes": ";".join(missing)}], ["gate", "passed", "notes"])
        return summary

    matrix, summary, audits = build_selection(repo)
    matrix_fields = [
        "candidate", "benchmark_strategy", "is_reweighted_candidate", "v21_247_decision", "average_return", "median_return",
        "excess_vs_e_r1", "excess_vs_a1", "excess_vs_dram", "p10_return", "worst5_return",
        "repeated_loser_count_proxy", "turnover_proxy", "turnover_materially_worse", "concentration_score_proxy",
        "source_mode_robust", "risk_adjusted_score", "beats_e_r1_after_risk_adjustment",
        "beats_a1_after_risk_adjustment", "tail_risk_preserved_vs_e_r1", "tail_risk_repaired_vs_a1", "notes",
    ]
    write_csv(out / "shadow_candidate_selection_matrix.csv", matrix, matrix_fields)
    write_csv(out / "shadow_candidate_vs_e_r1_audit.csv", audits["vs_e_r1"], matrix_fields)
    write_csv(out / "shadow_candidate_vs_a1_audit.csv", audits["vs_a1"], matrix_fields)
    write_csv(out / "shadow_candidate_vs_dram_audit.csv", audits["vs_dram"], matrix_fields)
    write_csv(out / "shadow_candidate_tail_risk_audit.csv", audits["tail"], matrix_fields)
    write_csv(out / "shadow_candidate_turnover_audit.csv", audits["turnover"], matrix_fields)
    write_csv(out / "shadow_candidate_source_mode_robustness.csv", audits["source"], matrix_fields)
    write_csv(out / "shadow_forward_tracking_gate.csv", [{
        "gate": summary["final_status"],
        "candidate": summary["recommended_shadow_tracking_candidate"] or summary["candidate_that_triggered_supportive_shadow_status"],
        "shadow_forward_tracking_allowed": summary["shadow_forward_tracking_allowed"],
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "notes": summary["final_decision"],
    }], ["gate", "candidate", "shadow_forward_tracking_allowed", "official_adoption_allowed", "broker_action_allowed", "notes"])
    write_json(out / "v21_249_summary.json", summary)
    report = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"candidate_that_triggered_supportive_shadow_status={summary['candidate_that_triggered_supportive_shadow_status']}",
        f"recommended_shadow_tracking_candidate={summary['recommended_shadow_tracking_candidate']}",
        "official_adoption_allowed=False",
        "broker_action_allowed=False",
    ]
    (out / "V21.249_shadow_candidate_selection_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    args = p.parse_args(argv)
    summary = run(args.repo_root.resolve(), args.output_dir)
    print(str((args.output_dir or args.repo_root / OUT_REL) / "v21_249_summary.json"))
    return 1 if summary.get("error_count", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
