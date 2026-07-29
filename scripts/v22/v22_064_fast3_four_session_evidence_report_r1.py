#!/usr/bin/env python
r"""
V22.064 FAST3 four-session evidence and comparability report R1.

Purpose
-------
Consolidate the completed FAST3 session studies into one immutable evidence
ledger without running a strategy, regenerating signals, or modifying any
existing result.

Included architectures
----------------------
PREMARKET
- V22.062PB corporate-action-safe PREMARKET_0925 historical candidate.
- V22.062PR frozen independent forward replication.

RTH
- V22.061 synchronized opening-range breakout.
- V22.063R1 VWAP mean reversion.
- V22.063R2 late-day continuation.

OVERNIGHT
- V22.062N synchronized trend baseline.
- V22.063N VWAP mean reversion.

AFTER_HOURS
- V22.063A close continuation.

Decision policy
---------------
- Historical rejection is not reversed.
- Insufficient-sample architectures remain inconclusive, not failed.
- PREMARKET_0925 remains a historical candidate only while V22.062PR is
  below its frozen final forward gate.
- A multi-session state machine is blocked until at least one session
  architecture passes independent forward replication.
- The next research stage may be diagnostic only: a cross-session transition
  return atlas. It must not create an execution policy.

No market data is read by this stage.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


VERSION = (
    "V22.064_FAST3_FOUR_SESSION_EVIDENCE_AND_COMPARABILITY_REPORT_R1"
)

EXPECTED_CUTOFF = "2026-07-24"

REJECT_DECISIONS = {
    "NO_ORB_BASELINE_CANDIDATE_QUALIFIED",
    "NO_RTH_VWAP_MEAN_REVERSION_CANDIDATE_QUALIFIED",
    "NO_RTH_LATE_DAY_CONTINUATION_CANDIDATE_QUALIFIED",
    "NO_OVERNIGHT_BASELINE_CANDIDATE_QUALIFIED",
    "NO_AFTER_HOURS_CLOSE_CONTINUATION_CANDIDATE_QUALIFIED",
}
INCONCLUSIVE_DECISIONS = {
    "OVERNIGHT_VWAP_MEAN_REVERSION_INCONCLUSIVE_INSUFFICIENT_SAMPLE",
}
FORWARD_PENDING_DECISIONS = {
    "FORWARD_REPLICATION_IN_PROGRESS_INSUFFICIENT_INTERIM_SAMPLE",
    "FORWARD_REPLICATION_INTERIM_ONLY_NOT_FINAL_DECISION_READY",
}
FORWARD_PASS_DECISION = (
    "PREMARKET_0925_FORWARD_REPLICATION_PASSED_RESEARCH_CANDIDATE_ONLY"
)
FORWARD_FAIL_DECISION = "PREMARKET_0925_FORWARD_REPLICATION_FAILED"
PREMARKET_HISTORICAL_DECISION = (
    "PREMARKET_CORPORATE_ACTION_SAFE_CANDIDATE_REQUIRES_"
    "INDEPENDENT_REPLICATION"
)


class EvidenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArchitectureSpec:
    architecture_id: str
    session: str
    architecture_name: str
    summary_path: Path
    expected_decisions: tuple[str, ...]
    is_forward: bool = False


def parse_supported(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped == "[]":
            return []
        return [stripped]
    return [str(value)]


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or pd.isna(value):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any) -> float:
    try:
        if value is None or pd.isna(value):
            return math.nan
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def validate_common_guards(summary: Mapping[str, Any], name: str) -> None:
    expected_false = (
        "canonical_files_modified",
        "raw_files_modified",
        "new_market_data_cache_created",
        "broker_action_allowed",
        "paper_trading_allowed",
        "official_adoption_allowed",
    )
    failures: list[str] = []

    if summary.get("final_status") != "PASS":
        failures.append(
            f"{name}.final_status={summary.get('final_status')!r}"
        )
    for field in expected_false:
        if summary.get(field) is not False:
            failures.append(
                f"{name}.{field}: expected False, got "
                f"{summary.get(field)!r}"
            )
    if failures:
        raise EvidenceError(
            "Common guard validation failed: " + "; ".join(failures)
        )


def validate_spec(
    spec: ArchitectureSpec,
    summary: Mapping[str, Any],
) -> None:
    validate_common_guards(summary, spec.architecture_id)
    decision = str(summary.get("final_decision", ""))
    if decision not in spec.expected_decisions:
        raise EvidenceError(
            f"{spec.architecture_id} unexpected final_decision={decision!r}; "
            f"expected one of {spec.expected_decisions!r}"
        )

    if spec.architecture_id == "PREMARKET_062PB":
        if summary.get("supported_exit_variants_for_replication") != [
            "PREMARKET_0925"
        ]:
            raise EvidenceError(
                "V22.062PB did not preserve PREMARKET_0925 as sole candidate"
            )
        if safe_int(summary.get("quarantined_trade_count"), -1) != 0:
            raise EvidenceError(
                "V22.062PB has quarantined corrected trades"
            )

    if spec.architecture_id == "PREMARKET_062PR":
        expected = {
            "research_cutoff_date": EXPECTED_CUTOFF,
            "forward_holdout_only": True,
            "rule_change_requires_reset": True,
            "sole_exit_variant": "PREMARKET_0925",
            "historical_pre_cutoff_outcomes_used_for_qualification": False,
            "strategy_rule_change_executed": False,
        }
        failures = [
            f"{key}: expected {value!r}, got {summary.get(key)!r}"
            for key, value in expected.items()
            if summary.get(key) != value
        ]
        if failures:
            raise EvidenceError(
                "V22.062PR freeze validation failed: "
                + "; ".join(failures)
            )

    if spec.architecture_id not in {
        "PREMARKET_062PB",
        "PREMARKET_062PR",
    }:
        if parse_supported(
            summary.get("supported_exit_variants_for_replication")
        ):
            raise EvidenceError(
                f"{spec.architecture_id} unexpectedly supports replication"
            )


def evidence_class(
    architecture_id: str,
    decision: str,
) -> str:
    if architecture_id == "PREMARKET_062PB":
        return "HISTORICAL_CANDIDATE_FORWARD_REQUIRED"
    if decision in FORWARD_PENDING_DECISIONS:
        return "FORWARD_REPLICATION_PENDING"
    if decision == FORWARD_PASS_DECISION:
        return "FORWARD_REPLICATION_PASSED_RESEARCH_ONLY"
    if decision == FORWARD_FAIL_DECISION:
        return "FORWARD_REPLICATION_FAILED"
    if decision in REJECT_DECISIONS:
        return "HISTORICAL_REJECT"
    if decision in INCONCLUSIVE_DECISIONS:
        return "INCONCLUSIVE_INSUFFICIENT_SAMPLE"
    if decision == PREMARKET_HISTORICAL_DECISION:
        return "HISTORICAL_CANDIDATE_FORWARD_REQUIRED"
    return "UNCLASSIFIED"


def candidate_count(summary: Mapping[str, Any]) -> int:
    for field in (
        "signal_candidate_count",
        "normalized_trade_count",
        "source_trade_count",
        "completed_holdout_session_count",
    ):
        if field in summary:
            return safe_int(summary.get(field))
    return 0


def trade_count(summary: Mapping[str, Any]) -> int:
    if "forward_trade_count" in summary:
        return safe_int(summary.get("forward_trade_count"))
    if "trade_record_count" in summary:
        return safe_int(summary.get("trade_record_count"))
    counts = summary.get("trade_count_by_exit_variant")
    if isinstance(counts, Mapping) and counts:
        return max(safe_int(value) for value in counts.values())
    return 0


def find_optional_csv(
    directory: Path,
    patterns: Iterable[str],
) -> Path | None:
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(directory.glob(pattern))
    unique = sorted(set(matches))
    return unique[0] if unique else None


def standardize_period_frame(
    architecture_id: str,
    session: str,
    source_path: Path,
) -> pd.DataFrame:
    frame = pd.read_csv(source_path)
    required = {"exit_variant", "study_period", "trade_count"}
    if not required.issubset(frame.columns):
        raise EvidenceError(
            f"{source_path} missing required columns "
            f"{sorted(required - set(frame.columns))}"
        )

    output = pd.DataFrame(
        {
            "architecture_id": architecture_id,
            "session": session,
            "exit_variant": frame["exit_variant"].astype(str),
            "study_period": frame["study_period"].astype(str),
            "trade_count": pd.to_numeric(
                frame["trade_count"], errors="coerce"
            ).fillna(0).astype(int),
        }
    )

    mapping = {
        "mean_instrument_return": "mean_instrument_return",
        "median_instrument_return": "median_instrument_return",
        "positive_rate": "positive_rate",
        "profit_factor": "profit_factor",
        "cumulative_return": "cumulative_return",
        "max_drawdown": "max_drawdown",
        "mean_selection_excess_return": (
            "mean_selection_excess_return"
        ),
        "top1_positive_profit_share": (
            "top1_positive_profit_share"
        ),
        "top5_positive_profit_share": (
            "top5_positive_profit_share"
        ),
    }
    for source, target in mapping.items():
        if source in frame.columns:
            output[target] = pd.to_numeric(
                frame[source], errors="coerce"
            )
        else:
            output[target] = np.nan

    output["source_path"] = str(source_path)
    return output


def standardize_qualification_frame(
    architecture_id: str,
    session: str,
    source_path: Path,
) -> pd.DataFrame:
    frame = pd.read_csv(source_path)
    if "exit_variant" not in frame.columns:
        raise EvidenceError(
            f"{source_path} missing exit_variant"
        )

    output = pd.DataFrame(
        {
            "architecture_id": architecture_id,
            "session": session,
            "exit_variant": frame["exit_variant"].astype(str),
        }
    )
    fields = (
        "full_history_trade_count",
        "validation_trade_count",
        "confirmation_trade_count",
        "sample_pass",
        "mean_positive_both_periods",
        "median_positive_both_periods",
        "profit_factor_pass_both_periods",
        "cumulative_return_positive_both_periods",
        "selection_excess_nonnegative_both_periods",
        "trade_concentration_pass",
        "single_positive_year_profit_share",
        "year_concentration_pass",
        "research_candidate_for_replication",
        "research_candidate_for_independent_replication",
    )
    for field in fields:
        output[field] = (
            frame[field]
            if field in frame.columns
            else np.nan
        )
    output["source_path"] = str(source_path)
    return output


def best_period_rows(periods: pd.DataFrame) -> pd.DataFrame:
    if periods.empty:
        return periods.copy()

    target = periods.loc[
        periods["study_period"].isin(
            [
                "2023-2024_VALIDATION",
                "2025-2026_YTD_CONFIRMATION",
            ]
        )
    ].copy()
    if target.empty:
        return target

    target["mean_sort"] = pd.to_numeric(
        target["mean_instrument_return"], errors="coerce"
    ).fillna(-np.inf)
    best = (
        target.sort_values(
            [
                "architecture_id",
                "study_period",
                "mean_sort",
            ],
            ascending=[True, True, False],
            kind="mergesort",
        )
        .groupby(
            ["architecture_id", "study_period"],
            sort=False,
            as_index=False,
        )
        .head(1)
        .drop(columns=["mean_sort"])
        .reset_index(drop=True)
    )
    return best


def build_decision(
    inventory: pd.DataFrame,
) -> dict[str, Any]:
    forward = inventory.loc[
        inventory["architecture_id"] == "PREMARKET_062PR"
    ]
    if forward.empty:
        raise EvidenceError("Missing PREMARKET_062PR inventory row")

    forward_decision = str(forward.iloc[0]["final_decision"])
    forward_pass = forward_decision == FORWARD_PASS_DECISION
    forward_fail = forward_decision == FORWARD_FAIL_DECISION
    forward_pending = forward_decision in FORWARD_PENDING_DECISIONS

    historical_candidates = inventory.loc[
        inventory["evidence_class"]
        == "HISTORICAL_CANDIDATE_FORWARD_REQUIRED"
    ]
    rejected = inventory.loc[
        inventory["evidence_class"] == "HISTORICAL_REJECT"
    ]
    inconclusive = inventory.loc[
        inventory["evidence_class"]
        == "INCONCLUSIVE_INSUFFICIENT_SAMPLE"
    ]

    state_machine_allowed = bool(forward_pass)
    if state_machine_allowed:
        overall = (
            "AT_LEAST_ONE_SESSION_FORWARD_REPLICATED_"
            "STATE_MACHINE_DIAGNOSTIC_ALLOWED"
        )
        next_stage = (
            "V22.065_FAST3_MULTI_SESSION_STATE_MACHINE_"
            "DIAGNOSTIC_R1"
        )
    elif forward_fail:
        overall = (
            "NO_SESSION_ARCHITECTURE_FORWARD_QUALIFIED_"
            "FAST3_EXECUTION_DEVELOPMENT_BLOCKED"
        )
        next_stage = (
            "V22.064T_FAST3_CROSS_SESSION_TRANSITION_"
            "RETURN_ATLAS_R1"
        )
    else:
        overall = (
            "SOLE_HISTORICAL_CANDIDATE_FORWARD_PENDING_"
            "MULTI_SESSION_STATE_MACHINE_BLOCKED"
        )
        next_stage = (
            "V22.064T_FAST3_CROSS_SESSION_TRANSITION_"
            "RETURN_ATLAS_R1"
        )

    return {
        "overall_decision": overall,
        "historical_candidate_architecture_count": int(
            len(historical_candidates)
        ),
        "historically_rejected_architecture_count": int(len(rejected)),
        "inconclusive_architecture_count": int(len(inconclusive)),
        "forward_replication_pending": forward_pending,
        "forward_replication_passed": forward_pass,
        "forward_replication_failed": forward_fail,
        "multi_session_state_machine_allowed": state_machine_allowed,
        "broker_action_allowed": False,
        "paper_trading_allowed": False,
        "official_adoption_allowed": False,
        "next_stage": next_stage,
    }


def markdown_report(
    inventory: pd.DataFrame,
    best: pd.DataFrame,
    decision: Mapping[str, Any],
) -> str:
    lines = [
        "# V22.064 FAST3 Four-Session Evidence Report",
        "",
        f"- Overall decision: `{decision['overall_decision']}`",
        f"- Next stage: `{decision['next_stage']}`",
        "- Broker action allowed: `False`",
        "- Paper trading allowed: `False`",
        "- Official adoption allowed: `False`",
        "",
        "## Architecture inventory",
        "",
        "| Session | Architecture | Decision | Evidence class | Candidates | Trades |",
        "|---|---|---|---|---:|---:|",
    ]
    for _, row in inventory.iterrows():
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["session"]),
                    str(row["architecture_name"]),
                    f"`{row['final_decision']}`",
                    str(row["evidence_class"]),
                    str(int(row["candidate_count"])),
                    str(int(row["trade_count"])),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Best observed exit by period",
            "",
            "This section is descriptive only. It does not select or optimize an exit.",
            "",
            "| Architecture | Period | Exit | Trades | Mean bps | Median bps | PF |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
    )
    for _, row in best.iterrows():
        mean_bps = (
            safe_float(row["mean_instrument_return"]) * 10000
        )
        median_bps = (
            safe_float(row["median_instrument_return"]) * 10000
        )
        pf = safe_float(row["profit_factor"])
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["architecture_id"]),
                    str(row["study_period"]),
                    str(row["exit_variant"]),
                    str(int(row["trade_count"])),
                    (
                        ""
                        if not np.isfinite(mean_bps)
                        else f"{mean_bps:.2f}"
                    ),
                    (
                        ""
                        if not np.isfinite(median_bps)
                        else f"{median_bps:.2f}"
                    ),
                    "" if not np.isfinite(pf) else f"{pf:.3f}",
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Governing conclusion",
            "",
            "PREMARKET_0925 is the sole historical candidate and remains under "
            "the frozen V22.062PR forward protocol. RTH opening-range "
            "breakout, RTH VWAP mean reversion, RTH late-day continuation, "
            "overnight trend, and after-hours close continuation are "
            "historically rejected. Overnight VWAP mean reversion remains "
            "inconclusive because its Validation sample is insufficient.",
            "",
            "A multi-session execution state machine is blocked until at "
            "least one architecture passes independent forward replication. "
            "The next stage is therefore diagnostic only: a cross-session "
            "transition return atlas.",
            "",
        ]
    )
    return "\n".join(lines)


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        if isinstance(value, np.floating) and not np.isfinite(value):
            return None
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value)!r}")


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                default=json_default,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run_report(
    specs: list[ArchitectureSpec],
    result_dir: Path,
) -> dict[str, Any]:
    inventory_rows: list[dict[str, Any]] = []
    period_frames: list[pd.DataFrame] = []
    qualification_frames: list[pd.DataFrame] = []

    for spec in specs:
        if not spec.summary_path.exists():
            raise EvidenceError(
                f"Missing summary: {spec.summary_path}"
            )
        summary = json.loads(
            spec.summary_path.read_text(encoding="utf-8-sig")
        )
        validate_spec(spec, summary)

        decision = str(summary["final_decision"])
        inventory_rows.append(
            {
                "architecture_id": spec.architecture_id,
                "session": spec.session,
                "architecture_name": spec.architecture_name,
                "version": str(summary.get("version", "")),
                "final_decision": decision,
                "evidence_class": evidence_class(
                    spec.architecture_id,
                    decision,
                ),
                "candidate_count": candidate_count(summary),
                "trade_count": trade_count(summary),
                "long_candidate_count": safe_int(
                    summary.get("long_candidate_count")
                ),
                "short_candidate_count": safe_int(
                    summary.get("short_candidate_count")
                ),
                "supported_variants": "|".join(
                    parse_supported(
                        summary.get(
                            "supported_exit_variants_for_replication"
                        )
                    )
                ),
                "forward_interim_evaluable": summary.get(
                    "interim_evaluable",
                    np.nan,
                ),
                "forward_final_evaluable": summary.get(
                    "final_evaluable",
                    np.nan,
                ),
                "forward_replication_pass": summary.get(
                    "forward_replication_pass",
                    np.nan,
                ),
                "summary_path": str(spec.summary_path),
            }
        )

        directory = spec.summary_path.parent
        period_path = find_optional_csv(
            directory,
            (
                "*corrected_period_summary.csv",
                "*period_summary.csv",
            ),
        )
        if period_path is not None:
            period_frames.append(
                standardize_period_frame(
                    spec.architecture_id,
                    spec.session,
                    period_path,
                )
            )

        qualification_path = find_optional_csv(
            directory,
            (
                "*corrected_qualification.csv",
                "*qualification.csv",
            ),
        )
        if qualification_path is not None:
            qualification_frames.append(
                standardize_qualification_frame(
                    spec.architecture_id,
                    spec.session,
                    qualification_path,
                )
            )

    inventory = pd.DataFrame(inventory_rows)
    periods = (
        pd.concat(period_frames, ignore_index=True)
        if period_frames
        else pd.DataFrame()
    )
    qualifications = (
        pd.concat(qualification_frames, ignore_index=True)
        if qualification_frames
        else pd.DataFrame()
    )
    best = best_period_rows(periods)
    decision = build_decision(inventory)

    result_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "inventory": result_dir
        / "v22_064_architecture_inventory.csv",
        "period_metrics": result_dir
        / "v22_064_period_metric_matrix.csv",
        "qualification": result_dir
        / "v22_064_qualification_matrix.csv",
        "best_period_rows": result_dir
        / "v22_064_descriptive_best_exit_by_period.csv",
        "report": result_dir / "v22_064_evidence_report.md",
        "summary": result_dir / "v22_064_summary.json",
    }

    inventory.to_csv(
        outputs["inventory"],
        index=False,
        encoding="utf-8-sig",
    )
    periods.to_csv(
        outputs["period_metrics"],
        index=False,
        encoding="utf-8-sig",
    )
    qualifications.to_csv(
        outputs["qualification"],
        index=False,
        encoding="utf-8-sig",
    )
    best.to_csv(
        outputs["best_period_rows"],
        index=False,
        encoding="utf-8-sig",
    )

    report_text = markdown_report(inventory, best, decision)
    outputs["report"].write_text(
        report_text,
        encoding="utf-8",
    )

    summary = {
        "version": VERSION,
        "final_status": "PASS",
        "final_decision": decision["overall_decision"],
        **decision,
        "research_cutoff_date": EXPECTED_CUTOFF,
        "architecture_count": int(len(inventory)),
        "session_count": int(inventory["session"].nunique()),
        "sole_historical_candidate": "PREMARKET_0925",
        "premarket_forward_chain_modified": False,
        "market_data_read": False,
        "strategy_backtest_executed": False,
        "signal_regeneration_executed": False,
        "parameter_sweep_executed": False,
        "threshold_optimization_executed": False,
        "canonical_files_modified": False,
        "raw_files_modified": False,
        "new_market_data_cache_created": False,
        "outputs": {
            key: str(value)
            for key, value in outputs.items()
        },
    }
    atomic_json(outputs["summary"], summary)

    print("==============================================")
    print(" V22.064 four-session evidence report")
    print("==============================================")
    print()
    print(
        inventory[
            [
                "session",
                "architecture_id",
                "final_decision",
                "evidence_class",
                "candidate_count",
                "trade_count",
                "supported_variants",
            ]
        ].to_string(index=False)
    )
    print()
    print("FINAL_STATUS=PASS")
    print(f"FINAL_DECISION={decision['overall_decision']}")
    print(
        "HISTORICAL_CANDIDATE_ARCHITECTURE_COUNT="
        f"{decision['historical_candidate_architecture_count']}"
    )
    print(
        "HISTORICALLY_REJECTED_ARCHITECTURE_COUNT="
        f"{decision['historically_rejected_architecture_count']}"
    )
    print(
        "INCONCLUSIVE_ARCHITECTURE_COUNT="
        f"{decision['inconclusive_architecture_count']}"
    )
    print(
        "FORWARD_REPLICATION_PENDING="
        f"{decision['forward_replication_pending']}"
    )
    print(
        "FORWARD_REPLICATION_PASSED="
        f"{decision['forward_replication_passed']}"
    )
    print(
        "MULTI_SESSION_STATE_MACHINE_ALLOWED="
        f"{decision['multi_session_state_machine_allowed']}"
    )
    print("PREMARKET_FORWARD_CHAIN_MODIFIED=False")
    print("MARKET_DATA_READ=False")
    print("STRATEGY_BACKTEST_EXECUTED=False")
    print("SIGNAL_REGENERATION_EXECUTED=False")
    print("PARAMETER_SWEEP_EXECUTED=False")
    print("THRESHOLD_OPTIMIZATION_EXECUTED=False")
    print("CANONICAL_FILES_MODIFIED=False")
    print("RAW_FILES_MODIFIED=False")
    print("NEW_MARKET_DATA_CACHE_CREATED=False")
    print("BROKER_ACTION_ALLOWED=False")
    print("PAPER_TRADING_ALLOWED=False")
    print("OFFICIAL_ADOPTION_ALLOWED=False")
    print(f"NEXT_STAGE={decision['next_stage']}")
    print(f"SUMMARY_PATH={outputs['summary']}")
    print(f"REPORT_PATH={outputs['report']}")
    print(f"RESULT_DIRECTORY={result_dir}")

    return summary


def default_specs(results_root: Path) -> list[ArchitectureSpec]:
    return [
        ArchitectureSpec(
            "PREMARKET_062PB",
            "PREMARKET",
            "Corporate-action-safe gap and range PREMARKET_0925",
            results_root
            / "V22.062PB_FAST3_CORPORATE_ACTION_SAFE_PRICE_NORMALIZATION_R1"
            / "v22_062pb_summary.json",
            (PREMARKET_HISTORICAL_DECISION,),
        ),
        ArchitectureSpec(
            "PREMARKET_062PR",
            "PREMARKET",
            "PREMARKET_0925 independent forward replication",
            results_root
            / "V22.062PR_FAST3_PREMARKET_INDEPENDENT_FORWARD_REPLICATION_R1"
            / "v22_062pr_summary.json",
            tuple(
                sorted(
                    FORWARD_PENDING_DECISIONS
                    | {
                        FORWARD_PASS_DECISION,
                        FORWARD_FAIL_DECISION,
                    }
                )
            ),
            is_forward=True,
        ),
        ArchitectureSpec(
            "RTH_061_ORB",
            "RTH",
            "Synchronized opening-range breakout",
            results_root
            / "V22.061_FAST3_SYNCHRONIZED_OPENING_RANGE_BREAKOUT_BASELINE_R1"
            / "v22_061_summary.json",
            ("NO_ORB_BASELINE_CANDIDATE_QUALIFIED",),
        ),
        ArchitectureSpec(
            "RTH_063R1_VWAP_MR",
            "RTH",
            "VWAP mean reversion",
            results_root
            / "V22.063R1_FAST3_RTH_VWAP_MEAN_REVERSION_BASELINE_R1"
            / "v22_063r1_summary.json",
            (
                "NO_RTH_VWAP_MEAN_REVERSION_CANDIDATE_QUALIFIED",
            ),
        ),
        ArchitectureSpec(
            "RTH_063R2_LATE_CONT",
            "RTH",
            "Late-day continuation",
            results_root
            / "V22.063R2_FAST3_RTH_LATE_DAY_CONTINUATION_BASELINE_R1"
            / "v22_063r2_summary.json",
            (
                "NO_RTH_LATE_DAY_CONTINUATION_CANDIDATE_QUALIFIED",
            ),
        ),
        ArchitectureSpec(
            "OVERNIGHT_062N_TREND",
            "OVERNIGHT",
            "Synchronized overnight trend",
            results_root
            / "V22.062N_FAST3_OVERNIGHT_SYNCHRONIZED_TREND_BASELINE_R1"
            / "v22_062n_summary.json",
            ("NO_OVERNIGHT_BASELINE_CANDIDATE_QUALIFIED",),
        ),
        ArchitectureSpec(
            "OVERNIGHT_063N_VWAP_MR",
            "OVERNIGHT",
            "Overnight VWAP mean reversion",
            results_root
            / "V22.063N_FAST3_OVERNIGHT_VWAP_MEAN_REVERSION_BASELINE_R1"
            / "v22_063n_summary.json",
            (
                "OVERNIGHT_VWAP_MEAN_REVERSION_"
                "INCONCLUSIVE_INSUFFICIENT_SAMPLE",
            ),
        ),
        ArchitectureSpec(
            "AFTER_HOURS_063A_CLOSE_CONT",
            "AFTER_HOURS",
            "After-hours close continuation",
            results_root
            / "V22.063A_FAST3_AFTER_HOURS_CLOSE_CONTINUATION_BASELINE_R1"
            / "v22_063a_summary.json",
            (
                "NO_AFTER_HOURS_CLOSE_CONTINUATION_CANDIDATE_QUALIFIED",
            ),
        ),
    ]


def parse_args(
    argv: list[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--results-root",
        default=r"D:\us-tech-quant-results\v22",
    )
    parser.add_argument(
        "--result-dir",
        default=(
            r"D:\us-tech-quant-results\v22"
            r"\V22.064_FAST3_FOUR_SESSION_EVIDENCE_AND_"
            r"COMPARABILITY_REPORT_R1"
        ),
    )
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.execute:
        print("FINAL_STATUS=BLOCKED_EXECUTE_FLAG_REQUIRED")
        return 2
    try:
        results_root = Path(args.results_root)
        run_report(
            specs=default_specs(results_root),
            result_dir=Path(args.result_dir),
        )
        return 0
    except Exception as exc:
        print("FINAL_STATUS=FAIL")
        print(f"ERROR_TYPE={type(exc).__name__}")
        print(f"ERROR={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
