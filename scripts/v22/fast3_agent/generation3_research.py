#!/usr/bin/env python
"""FAST3 Generation 3 split freeze and research entry point.

The audit phase is deliberately metadata-only.  It records every earlier
Generation 1/2 exposure and writes an immutable chronological split before any
Generation 3 OHLC or target value is opened.  Research phases are added only
after this contract has been produced and hash-checked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


NAME = "FAST3_GENERATION3_NONLINEAR_OPPORTUNITY_DIRECTION_R1"
CANONICAL = Path(r"D:\us-tech-quant-data\fast3\moomoo_24h_1m\canonical")
PRIOR_LEDGER = Path(r"D:\us-tech-quant-results\fast3_autoresearch_generation2\repaired_timestamp_unit_20260801\generation2_data_usage_ledger.csv")
PRIOR_CONTRACT = Path(r"D:\us-tech-quant-results\fast3_autoresearch_generation2\repaired_timestamp_unit_20260801\generation2_split_contract.json")
DEFAULT_OUT = Path(r"D:\us-tech-quant-results\fast3_autoresearch_generation3\current")
SYMBOLS = ("QQQ", "SOXX", "TQQQ", "SQQQ", "SOXL", "SOXS")
REQUIRED = ("timestamp_et", "timestamp_utc", "broker_trade_date", "session", "open", "high", "low", "close", "volume")
SAFETY = {
    "broker_action_allowed": False,
    "paper_broker_order_allowed": False,
    "live_trading_allowed": False,
    "official_adoption_allowed": False,
    "order_generation_allowed": False,
    "research_only": True,
    "canonical_data_writable": False,
}


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (pd.Timestamp, pd.Period)):
        return str(value)
    return str(value)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")


def sha256_json(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default).encode("utf-8")).hexdigest()


def partition_paths(canonical: Path, symbol: str) -> list[Path]:
    paths = sorted(canonical.glob(f"symbol={symbol}/year=*/month=*/data.parquet"))
    if not paths:
        raise RuntimeError(f"SOURCE_DATA_MISSING:{symbol}")
    return paths


def canonical_date_metadata(canonical: Path) -> tuple[dict[str, pd.DatetimeIndex], list[dict]]:
    """Read only timestamp/date metadata required to freeze the split."""
    dates: dict[str, pd.DatetimeIndex] = {}
    audit: list[dict] = []
    for symbol in SYMBOLS:
        parts = []
        paths = partition_paths(canonical, symbol)
        for path in paths:
            frame = pd.read_parquet(path, columns=["timestamp_et", "broker_trade_date"])
            timestamp = pd.to_datetime(frame["timestamp_et"], errors="raise")
            parts.append(pd.DatetimeIndex(timestamp.dt.normalize().unique()))
        days = pd.DatetimeIndex(np.unique(np.concatenate([x.to_numpy() for x in parts]))).sort_values()
        dates[symbol] = days
        audit.append({"symbol": symbol, "partition_count": len(paths), "date_start": days.min(), "date_end": days.max(), "date_count": len(days), "columns_read": ["timestamp_et", "broker_trade_date"], "ohlc_or_economic_values_read": False})
    return dates, audit


def _prior_exposure(day: pd.Timestamp, row: pd.Series | None) -> str:
    if row is None:
        return "FUTURE_ONLY"
    frozen_role = str(row.get("generation2_frozen_role", ""))
    prior_use = str(row.get("generation2_data_usage", ""))
    if frozen_role == "DEVELOPMENT":
        return "PREVIOUSLY_EXPOSED_DEVELOPMENT"
    if frozen_role == "VALIDATION":
        return "PREVIOUSLY_EXPOSED_VALIDATION"
    if frozen_role == "EMBARGO" or prior_use == "INELIGIBLE_OR_AMBIGUOUS":
        return "EMBARGO"
    if prior_use == "PREVIOUSLY_USED_DEVELOPMENT":
        return "PREVIOUSLY_EXPOSED_DEVELOPMENT"
    if prior_use == "PREVIOUSLY_USED_VALIDATION":
        return "PREVIOUSLY_EXPOSED_VALIDATION"
    if prior_use == "PREVIOUSLY_USED_RANDOMIZED_SELECTION":
        return "PREVIOUSLY_EXPOSED_RANDOMIZED_SELECTION"
    return "PREVIOUSLY_UNREAD_ELIGIBLE"


def freeze_contract(common_dates: pd.DatetimeIndex, prior_contract: dict) -> dict:
    """Apply the authorization's deterministic monthly rule without targets."""
    prior_validation_end = pd.Timestamp(prior_contract["validation_end"])
    eligible = common_dates[common_dates > prior_validation_end]
    periods = pd.PeriodIndex(eligible, freq="M")
    complete = [month for month in periods.unique().sort_values() if (periods == month).sum() >= 10]
    if len(complete) < 5:
        raise RuntimeError("FAIL_INSUFFICIENT_INDEPENDENT_DATA")
    first_embargo, validation_a, validation_b, second_embargo = complete[:4]
    confirmation = complete[4:]
    if not confirmation:
        raise RuntimeError("FAIL_INSUFFICIENT_INDEPENDENT_DATA")
    confirmation_dates = eligible[pd.PeriodIndex(eligible, freq="M").isin(confirmation)]
    independent_weekdays = int((confirmation_dates.dayofweek < 5).sum())
    contract = {
        "research_id": NAME,
        "contract_status": "FROZEN_BEFORE_GENERATION3_ECONOMIC_RESULTS",
        "method": "Generation 1/2 exposure audit; all dates through Generation 2 Validation are Development-only; one complete-month embargo; first two complete eligible months Validation; one complete-month embargo; remaining complete eligible months one-time Confirmation.",
        "prior_generation2_contract_sha256": prior_contract["contract_sha256"],
        "prior_generation2_validation_end": prior_validation_end,
        "development_start": common_dates.min(),
        "development_end": prior_validation_end,
        "first_embargo_start": first_embargo.start_time.tz_localize("America/New_York"),
        "first_embargo_end": first_embargo.end_time.tz_localize("America/New_York"),
        "validation_start": validation_a.start_time.tz_localize("America/New_York"),
        "validation_end": validation_b.end_time.tz_localize("America/New_York"),
        "second_embargo_start": second_embargo.start_time.tz_localize("America/New_York"),
        "second_embargo_end": second_embargo.end_time.tz_localize("America/New_York"),
        "confirmation_start": confirmation[0].start_time.tz_localize("America/New_York"),
        "confirmation_end": confirmation[-1].end_time.tz_localize("America/New_York"),
        "confirmation_complete_months": [str(x) for x in confirmation],
        "confirmation_independent_weekday_count_metadata_only": independent_weekdays,
        "confirmation_minimum_independent_trading_days": 20,
        "confirmation_minimum_nonoverlapping_executed_trades": 75,
        "confirmation_independent_day_requirement_satisfied": independent_weekdays >= 20,
        "terminal_split_feasibility_status": "SPLIT_FEASIBLE" if independent_weekdays >= 20 else "FAIL_INSUFFICIENT_INDEPENDENT_DATA",
        "candidate_families_predeclared": ["unconditional_and_regime_baselines", "linear_logistic_ridge", "two_stage_hist_gradient_boosting", "compact_regime_mixture_of_experts"],
        "candidate_family_limit": 6,
        "randomized_development_windows": {"seed": 20260801, "minimum_iterations": 100, "window_trading_days": 10, "sampling": "continuous chronological as-of windows; no shuffled rows"},
        "validation_opening_rule": "Open exactly once only after all four candidate families, feature groups, hyperparameters, thresholds, scoring rule, and tie-break are frozen.",
        "confirmation_read_count": 0,
        **SAFETY,
    }
    contract["contract_sha256"] = sha256_json(contract)
    return contract


def _write_insufficient_data_terminal(output: Path, contract: dict, source_audit: list[dict]) -> None:
    """Finish before economic reads when the frozen Confirmation cannot qualify."""
    reason = ("The deterministic Generation 3 Confirmation period has only "
              f"{contract['confirmation_independent_weekday_count_metadata_only']} metadata-only weekdays, below the frozen minimum of "
              f"{contract['confirmation_minimum_independent_trading_days']}; no boundary was moved and no economic data were read.")
    empty_files = {
        "generation3_candidate_registry.csv": "candidate_id,decision\n",
        "generation3_development_walkforward_metrics.csv": "iteration_id\n",
        "generation3_validation_metrics.csv": "candidate_id\n",
        "generation3_random_window_metrics.csv": "iteration_id\n",
        "generation3_ablation_metrics.csv": "factor_group\n",
    }
    for name, header in empty_files.items():
        (output / name).write_text(header, encoding="utf-8")
    write_json(output / "generation3_feature_contract.json", {"status": "NOT_RUN", "reason": reason, "feature_information_cutoff_guard": "NOT_APPLICABLE_NO_ECONOMIC_READ", **SAFETY})
    write_json(output / "generation3_label_contract.json", {"status": "NOT_RUN", "reason": reason, "confirmation_read_count": 0, **SAFETY})
    write_json(output / "generation3_leakage_audit.json", {"leakage_audit_pass": True, "confirmation_read_count": 0, "economic_ohlc_values_read": False, "confirmation_rows_read": 0, "conclusion": "PASS_SPLIT_FEASIBILITY_FAILED_CLOSED_BEFORE_ECONOMIC_RESEARCH", **SAFETY})
    write_json(output / "generation3_champion_record.json", {"current_champion": None, "status": "NO_CHAMPION", "reason": reason, "confirmation_read_count": 0, **SAFETY})
    summary = {"research_id": NAME, "final_status": "FAIL_INSUFFICIENT_INDEPENDENT_DATA", "final_decision": "GENERATION3_DETERMINISTIC_CONFIRMATION_PERIOD_HAS_FEWER_THAN_20_INDEPENDENT_TRADING_DAYS", "stop_reason": reason, "contract_sha256": contract["contract_sha256"], "confirmation_read_count": 0, "economic_research_executed": False, "source_audit_symbols": len(source_audit), "prospective_shadow_allowed": False, "exact_resume_command": "NONE_FAST3_GENERATION3_RESEARCH_STOPPED", **SAFETY}
    write_json(output / "generation3_final_summary.json", summary)
    (output / "generation3_final_report.md").write_text("# FAST3 Generation 3 final research report\n\nFINAL_STATUS=FAIL_INSUFFICIENT_INDEPENDENT_DATA\n\n" + reason + "\n\nConfirmation was not read. No OHLC or target economics were opened, no candidate was trained, and no orders were generated.\n", encoding="utf-8")
    checkpoint = {"current_status": summary["final_status"], "current_champion": None, "last_completed_iteration": 0, "confirmation_read_count": 0, "completed_backtests": [], "known_failures": [reason], "next_exact_action": "No permitted Generation 3 continuation until genuinely new canonical dates make the frozen deterministic split feasible.", "exact_resume_command": "NONE_FAST3_GENERATION3_RESEARCH_STOPPED", "contract_sha256": contract["contract_sha256"], **SAFETY}
    write_json(output / "generation3_checkpoint.json", checkpoint)
    write_json(output / "generation3_final_checkpoint.json", checkpoint)


def audit_phase(output: Path, canonical: Path, prior_ledger_path: Path, prior_contract_path: Path) -> dict:
    if not prior_ledger_path.is_file() or not prior_contract_path.is_file():
        raise RuntimeError("PRIOR_GENERATION_EVIDENCE_MISSING")
    prior = pd.read_csv(prior_ledger_path)
    prior["calendar_date_et"] = pd.to_datetime(prior["calendar_date_et"], errors="raise", utc=True).dt.tz_convert("America/New_York").dt.normalize()
    prior_by_date = {day: row for day, row in prior.set_index("calendar_date_et").iterrows()}
    prior_contract = json.loads(prior_contract_path.read_text(encoding="utf-8"))
    if int(prior_contract.get("confirmation_read_count", -1)) != 0:
        raise RuntimeError("PRIOR_CONFIRMATION_ISOLATION_VIOLATION")
    dates, source_audit = canonical_date_metadata(canonical)
    common = pd.DatetimeIndex(sorted(set(dates["SOXX"]).intersection(*[set(dates[symbol]) for symbol in SYMBOLS if symbol != "SOXX"])))
    contract = freeze_contract(common, prior_contract)
    ledger = pd.DataFrame({"calendar_date_et": common})
    ledger["prior_exposure"] = [_prior_exposure(day, prior_by_date.get(day)) for day in common]
    ledger["generation3_frozen_role"] = "FUTURE_ONLY"
    for role, start, end in (("GENERATION3_DEVELOPMENT", "development_start", "development_end"), ("EMBARGO", "first_embargo_start", "first_embargo_end"), ("GENERATION3_VALIDATION", "validation_start", "validation_end"), ("EMBARGO", "second_embargo_start", "second_embargo_end"), ("GENERATION3_CONFIRMATION_UNREAD", "confirmation_start", "confirmation_end")):
        ledger.loc[ledger.calendar_date_et.between(pd.Timestamp(contract[start]), pd.Timestamp(contract[end])), "generation3_frozen_role"] = role
    output.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(output / "generation3_data_usage_ledger.csv", index=False)
    write_json(output / "generation3_split_contract.json", contract)
    (output / "generation3_split_contract_sha256.txt").write_text(contract["contract_sha256"] + "\n", encoding="utf-8")
    write_json(output / "generation3_source_metadata_audit.json", {"source_audit": source_audit, "common_date_start": common.min(), "common_date_end": common.max(), "common_date_count": len(common), "prior_ledger": str(prior_ledger_path), "prior_contract": str(prior_contract_path), "prior_confirmation_read_count": 0, "ohlc_or_economic_values_read": False})
    if not contract["confirmation_independent_day_requirement_satisfied"]:
        _write_insufficient_data_terminal(output, contract, source_audit)
    else:
        write_json(output / "generation3_checkpoint.json", {"current_status": "SPLIT_FROZEN_AWAITING_PIT_LABEL_IMPLEMENTATION", "current_champion": None, "last_completed_iteration": 0, "confirmation_read_count": 0, "completed_backtests": [], "known_failures": [], "next_exact_action": "Implement and test Generation 3 three-layer PIT labels using Development only.", "exact_resume_command": f"python scripts/v22/fast3_agent/generation3_research.py --phase audit --output-dir {output}", "contract_sha256": contract["contract_sha256"], **SAFETY})
    return contract


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("audit",), required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--canonical-root", default=str(CANONICAL))
    parser.add_argument("--prior-ledger", default=str(PRIOR_LEDGER))
    parser.add_argument("--prior-contract", default=str(PRIOR_CONTRACT))
    args = parser.parse_args()
    result = audit_phase(Path(args.output_dir), Path(args.canonical_root), Path(args.prior_ledger), Path(args.prior_contract))
    print("FINAL_STATUS=" + result["terminal_split_feasibility_status"])
    print("CONFIRMATION_READ_COUNT=0")
    print("OUTPUT_DIRECTORY=" + str(Path(args.output_dir)))


if __name__ == "__main__":
    main()
