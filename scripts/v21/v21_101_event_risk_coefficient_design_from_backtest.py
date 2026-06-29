#!/usr/bin/env python
"""V21.101 conservative research-only event-risk coefficient specification."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUT = Path("outputs/v21")
SUMMARY_100 = OUT / "v21_100_r9_event_risk_weight_grid_backtest_summary.json"
VARIANTS = OUT / "v21_100_r7_event_weight_variant_summary.csv"
ROBUSTNESS = OUT / "v21_100_r8_event_weight_robustness_checks.csv"
SUMMARY_100_R1 = OUT / "v21_100_r1_event_weight_failure_decomposition_summary.json"
SUBSETS = OUT / "v21_100_r1_narrow_subset_diagnostic.csv"
IMPACT = OUT / "v21_097_r3_event_type_impact_summary.csv"
VULNERABILITY = OUT / "v21_097_r4_ticker_event_vulnerability_summary.csv"
TOP20 = OUT / "v21_098_r6_current_d_top20_event_policy_dashboard.csv"
MONITOR = OUT / "v21_099_r1_active_event_window_monitor_summary.json"
D_BASELINE = Path(
    "outputs/v21/experiments/momentum_dynamic/d_weight_optimized/"
    "V21_060_R5_D_WEIGHT_OPTIMIZED_RANKING.csv"
)
INPUTS = (
    SUMMARY_100, VARIANTS, ROBUSTNESS, SUMMARY_100_R1, SUBSETS,
    IMPACT, VULNERABILITY, TOP20, MONITOR,
)
OUTPUTS = (
    "v21_101_r1_coefficient_design_input_validation.csv",
    "v21_101_r1_coefficient_design_input_validation.json",
    "v21_101_r2_official_event_coefficient_decision.csv",
    "v21_101_r3_research_event_risk_coefficient_spec.csv",
    "v21_101_r4_event_risk_score_formula.md",
    "v21_101_r5_event_risk_bucket_policy.csv",
    "v21_101_r6_top20_forward_event_diagnostic_coefficients.csv",
    "v21_101_r7_coefficient_safety_checks.csv",
    "v21_101_r8_event_risk_coefficient_design_report.md",
    "v21_101_r8_event_risk_coefficient_design_summary.json",
)
RESEARCH_COEFFICIENTS = (
    ("event_type_left_tail_weight", .35, "Historical occurrence left-tail context"),
    ("ticker_vulnerability_weight", .25, "Current-universe ticker vulnerability context"),
    ("event_severity_weight", .20, "Forward event severity context"),
    ("event_confidence_weight", .10, "Source confidence context"),
    ("macro_or_sector_context_weight", .10, "Macro or sector context"),
)


def truth(value: Any) -> bool:
    return str(value).strip().upper() in {"TRUE", "1", "YES", "Y"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    def default(value: Any) -> Any:
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            return None if np.isnan(value) else float(value)
        if isinstance(value, np.bool_):
            return bool(value)
        raise TypeError(type(value).__name__)
    path.write_text(json.dumps(payload, indent=2, default=default) + "\n", encoding="utf-8")


def protected_snapshot(root: Path, outputs: set[Path]) -> dict[str, str]:
    tokens = (
        "official", "broker", "protected", "forward_observation_ledger",
        "060_r5_d_", "066a_d_latest_ranking", "p03", "p04",
    )
    result: dict[str, str] = {}
    for base in (root / "outputs", root / "data"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.resolve() not in outputs:
                if any(token in path.as_posix().lower() for token in tokens):
                    result[path.relative_to(root).as_posix()] = sha256(path)
    return result


def official_coefficients() -> pd.DataFrame:
    reasons = {
        "official_d_event_risk_weight": "V21.100 failed ticker-shuffle placebo; D integration remains blocked.",
        "official_ranking_penalty_weight": "No official event-weighted ranking is authorized.",
        "official_exposure_overlay_weight": "Observed loss reduction was diagnostic and carried missed-upside risk.",
        "official_entry_throttle_weight": "Historical pre-event avoidance validity remains blocked.",
    }
    rows = []
    for name, reason in reasons.items():
        rows.append({
            "coefficient_name": name, "coefficient_value": 0.0,
            "allowed_for_d_integration": False, "allowed_for_shadow_ranking": False,
            "allowed_for_forward_observation": True, "reason": reason,
            "research_only": True, "official_adoption_allowed": False,
        })
    return pd.DataFrame(rows)


def research_coefficients() -> pd.DataFrame:
    rows = []
    for name, value, role in RESEARCH_COEFFICIENTS:
        rows.append({
            "coefficient_name": name, "coefficient_value": value,
            "coefficient_role": role,
            "derived_from": "Conservative fixed diagnostic specification informed by V21.097/V21.100; not optimized or adopted.",
            "rationale": "Forward dashboard normalization only; placebo failure and research freeze acknowledged.",
            "allowed_for_forward_observation": True, "allowed_for_dashboard": True,
            "allowed_for_d_integration": False, "official_adoption_allowed": False,
            "research_only": True,
        })
    return pd.DataFrame(rows)


def formula_markdown() -> str:
    return """# V21.101 Diagnostic Event-Risk Score Formula

```text
event_risk_score =
    0.35 * event_type_left_tail_score
  + 0.25 * ticker_vulnerability_score
  + 0.20 * event_severity_score
  + 0.10 * event_confidence_score
  + 0.10 * macro_or_sector_context_score
```

All component scores are normalized to 0–100 and the result is clipped to 0–100.

Safety caps:

- LOW source confidence: cap final score at 70.
- Expected but not company-confirmed event date: cap final score at 75.
- Manually entered event with weak source reference: cap final score at 60.

This formula is diagnostic-only for forward monitoring and dashboards. It must not
modify D final score, create an official ranking, or support historical pre-event claims.
"""


def bucket_policy() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "risk_bucket": "LOW", "score_min": 0, "score_max": 40,
            "watch_action": "WATCH_ONLY", "entry_throttle_window": "",
            "exposure_scale": 1.00,
        },
        {
            "risk_bucket": "MEDIUM", "score_min": 40, "score_max": 60,
            "watch_action": "LIGHT_OBSERVATION", "entry_throttle_window": "",
            "exposure_scale": .90,
        },
        {
            "risk_bucket": "HIGH", "score_min": 60, "score_max": 75,
            "watch_action": "ENTRY_THROTTLE_OBSERVE",
            "entry_throttle_window": "T-1_TO_T0", "exposure_scale": .75,
        },
        {
            "risk_bucket": "EXTREME", "score_min": 75, "score_max": 100,
            "watch_action": "COMBINED_POLICY_OBSERVE",
            "entry_throttle_window": "T-3_TO_T+1", "exposure_scale": .50,
        },
    ]).assign(
        official_trade_action_allowed=False,
        official_adoption_allowed=False,
        research_only=True,
    )


def normalize_event_type_scores(impact: pd.DataFrame) -> dict[str, float]:
    five = impact[impact["window"].astype(str).str.upper().eq("5D")].copy()
    five["loss"] = (-pd.to_numeric(five["cvar_5"], errors="coerce")).clip(lower=0)
    maximum = five["loss"].max()
    five["score"] = five["loss"] / maximum * 100 if maximum > 0 else 0.0
    return five.set_index("event_type")["score"].to_dict()


def severity_score(value: Any) -> float:
    return {"LOW": 35.0, "MEDIUM": 60.0, "HIGH": 85.0, "EXTREME": 100.0}.get(
        str(value).upper(), 50.0
    )


def confidence_score(value: Any) -> float:
    return {"LOW": 40.0, "MEDIUM": 65.0, "HIGH": 90.0}.get(str(value).upper(), 50.0)


def score_top20(
    top20: pd.DataFrame, impact: pd.DataFrame, vulnerability: pd.DataFrame,
    policy: pd.DataFrame,
) -> pd.DataFrame:
    event_scores = normalize_event_type_scores(impact)
    vulnerability_score = vulnerability.set_index("ticker")["event_vulnerability_score"].to_dict()
    sectors = vulnerability.set_index("ticker")["sector_or_industry"].astype(str).to_dict()
    policy_rows = policy.set_index("risk_bucket")
    rows = []
    for _, row in top20.sort_values("rank").iterrows():
        ticker = str(row["ticker"])
        event_type = str(row["event_type"])
        historical_type = (
            "ticker_earnings_occurrence" if event_type == "ticker_earnings" else event_type
        )
        type_score = float(event_scores.get(historical_type, 50.0))
        ticker_score = float(vulnerability_score.get(ticker, 50.0))
        sev_score = severity_score(row["event_severity"])
        conf_score = confidence_score(row["event_confidence"])
        sector = sectors.get(ticker, "UNMAPPED")
        context_score = 60.0 if "Semiconductor" in sector else 50.0 if sector != "UNMAPPED" else 35.0
        raw = (
            .35 * type_score + .25 * ticker_score + .20 * sev_score
            + .10 * conf_score + .10 * context_score
        )
        caps = ["EXPECTED_NOT_COMPANY_CONFIRMED_CAP_75"]
        cap = 75.0
        if str(row["event_confidence"]).upper() == "LOW":
            cap = min(cap, 70.0)
            caps.append("LOW_CONFIDENCE_CAP_70")
            # Forward dates originated from a manually maintained expected-event branch.
            cap = min(cap, 60.0)
            caps.append("MANUAL_EXPECTED_DATE_WEAK_SOURCE_CAP_60")
        final = float(np.clip(min(raw, cap), 0, 100))
        if final < 40:
            bucket = "LOW"
        elif final < 60:
            bucket = "MEDIUM"
        elif final < 75:
            bucket = "HIGH"
        else:
            bucket = "EXTREME"
        bucket_row = policy_rows.loc[bucket]
        rows.append({
            "rank": row["rank"], "ticker": ticker, "final_score": row["final_score"],
            "event_type": event_type,
            "event_name": f"{ticker} expected {event_type.replace('_', ' ')}",
            "event_date": row["nearest_future_event_date"],
            "event_severity": row["event_severity"],
            "event_confidence": row["event_confidence"],
            "event_type_left_tail_score": type_score,
            "ticker_vulnerability_score": ticker_score,
            "event_severity_score": sev_score,
            "event_confidence_score": conf_score,
            "macro_or_sector_context_score": context_score,
            "event_risk_score": final, "event_risk_bucket": bucket,
            "research_entry_throttle_window": bucket_row["entry_throttle_window"],
            "research_exposure_scale": bucket_row["exposure_scale"],
            "official_d_weight": 0.0, "official_ranking_penalty": 0.0,
            "official_trade_action_allowed": False, "research_only": True,
            "official_adoption_allowed": False,
            "coefficient_reason": (
                "Diagnostic forward observation only; " + "|".join(caps)
                + "; V21.100 ticker-placebo failure blocks D integration."
            ),
        })
    return pd.DataFrame(rows)


def report(summary: dict[str, Any]) -> str:
    lines = ["# V21.101 Event-Risk Coefficient Design", ""]
    lines.extend(f"- {key}: `{value}`" for key, value in summary.items())
    lines.extend([
        "",
        "All official event coefficients remain zero. The diagnostic coefficients are a "
        "forward-monitoring specification only and do not establish event-weight effectiveness.",
        "",
        "V21.100 ticker-placebo weakness and the V21.100-R1 research-freeze decision remain "
        "binding. No D score, ranking, trade action, or historical pre-event test is authorized.",
    ])
    return "\n".join(lines) + "\n"


def run(root: Path) -> dict[str, Any]:
    out = root / OUT
    out.mkdir(parents=True, exist_ok=True)
    output_paths = {(out / name).resolve() for name in OUTPUTS}
    missing = [path.as_posix() for path in (*INPUTS, D_BASELINE) if not (root / path).is_file()]
    if missing:
        raise FileNotFoundError("Missing inputs: " + ", ".join(missing))
    input_hashes = {path.as_posix(): sha256(root / path) for path in INPUTS}
    prior_paths = sorted({
        path
        for prefix in ("v21_096*", "v21_097*", "v21_098*", "v21_099*", "v21_100*")
        for path in out.glob(prefix)
        if path.is_file()
    })
    prior_hashes = {path.relative_to(root).as_posix(): sha256(path) for path in prior_paths}
    d_before = sha256(root / D_BASELINE)
    before = protected_snapshot(root, output_paths)

    summary_100 = json.loads((root / SUMMARY_100).read_text(encoding="utf-8"))
    variants = pd.read_csv(root / VARIANTS, low_memory=False)
    robustness = pd.read_csv(root / ROBUSTNESS, low_memory=False)
    summary_r1 = json.loads((root / SUMMARY_100_R1).read_text(encoding="utf-8"))
    subsets = pd.read_csv(root / SUBSETS, low_memory=False)
    impact = pd.read_csv(root / IMPACT, low_memory=False)
    vulnerability = pd.read_csv(root / VULNERABILITY, low_memory=False)
    top20 = pd.read_csv(root / TOP20, low_memory=False)
    monitor = json.loads((root / MONITOR).read_text(encoding="utf-8"))
    promising_count = int(summary_r1.get("PROMISING_SUBSETS_COUNT", 0))
    pit_warnings = int(summary_100.get("PIT_LEAKAGE_WARNINGS", 0)) + int(
        summary_r1.get("PIT_LEAKAGE_WARNINGS", 0)
    )
    checks = [
        ("v21_100_final_status_pass", summary_100.get("FINAL_STATUS") == "PASS", summary_100.get("FINAL_STATUS")),
        ("v21_100_no_edge_decision", summary_100.get("DECISION") == "EVENT_WEIGHT_NO_LEFT_TAIL_EDGE_RESEARCH_ONLY", summary_100.get("DECISION")),
        ("v21_100_r1_final_status_pass", summary_r1.get("FINAL_STATUS") == "PASS", summary_r1.get("FINAL_STATUS")),
        ("v21_100_r1_research_freeze_decision", summary_r1.get("DECISION") == "EVENT_WEIGHT_RESEARCH_FREEZE_RECOMMENDED", summary_r1.get("DECISION")),
        ("placebo_failure_confirmed", summary_r1.get("PLACEBO_FAILURE_CONFIRMED") is True, ""),
        ("promising_narrow_subsets_count_zero", promising_count == 0 and not subsets["subset_recommendation"].isin(["WATCH_FORWARD_ONLY", "PROMISING_BUT_NOT_ADOPTABLE"]).any(), promising_count),
        ("historical_pre_event_random_backtest_blocked", summary_100.get("HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED") is False and summary_r1.get("HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED") is False, ""),
        ("pit_leakage_warnings_zero", pit_warnings == 0, pit_warnings),
        ("supporting_inputs_loaded", len(variants) > 0 and len(robustness) > 0 and len(top20) == 20 and monitor.get("FINAL_STATUS") == "PASS", ""),
        ("d_baseline_hash_available", bool(d_before), d_before),
    ]
    validation_rows = pd.DataFrame(checks, columns=["check_name", "passed", "detail"])
    validation = {
        "stage": "V21.101-R1_COEFFICIENT_DESIGN_INPUT_VALIDATION",
        "status": "PASS" if validation_rows["passed"].all() else "FAIL",
        "input_v21_100_status": summary_100.get("FINAL_STATUS", "MISSING"),
        "input_v21_100_r1_status": summary_r1.get("FINAL_STATUS", "MISSING"),
        "placebo_failure_confirmed": bool(summary_r1.get("PLACEBO_FAILURE_CONFIRMED")),
        "promising_narrow_subsets_count": promising_count,
        "historical_pre_event_random_backtest_allowed": False,
        "pit_leakage_warnings": pit_warnings,
        "research_only": True, "official_adoption_allowed": False,
        "d_baseline_sha256_before": d_before,
    }
    validation_rows.to_csv(out / OUTPUTS[0], index=False)

    official = official_coefficients()
    official.to_csv(out / OUTPUTS[2], index=False)
    research = research_coefficients()
    research.to_csv(out / OUTPUTS[3], index=False)
    (out / OUTPUTS[4]).write_text(formula_markdown(), encoding="utf-8")
    policy = bucket_policy()
    policy.to_csv(out / OUTPUTS[5], index=False)
    scored = score_top20(top20, impact, vulnerability, policy)
    scored.to_csv(out / OUTPUTS[6], index=False)

    after = protected_snapshot(root, output_paths)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    d_after = sha256(root / D_BASELINE)
    d_preserved = d_after == d_before
    inputs_preserved = all(sha256(root / Path(path)) == digest for path, digest in input_hashes.items())
    prior_preserved = all(
        (root / relative).is_file() and sha256(root / relative) == digest
        for relative, digest in prior_hashes.items()
    )
    official_changed = [path for path in changed if "official" in path.lower() or "broker" in path.lower()]
    protected_modified = bool(changed or not d_preserved or not inputs_preserved or not prior_preserved)
    validation.update({
        "d_baseline_sha256_after": d_after, "d_baseline_preserved": d_preserved,
        "input_files_preserved": inputs_preserved,
        "v21_096_through_v21_100_r1_artifacts_preserved": prior_preserved,
    })
    if protected_modified or official_changed:
        validation["status"] = "FAIL"
    write_json(out / OUTPUTS[1], validation)

    safety = pd.DataFrame([
        ("official_coefficients_all_zero", official["coefficient_value"].eq(0).all(), ""),
        ("research_coefficients_sum_to_1", np.isclose(research["coefficient_value"].sum(), 1.0), research["coefficient_value"].sum()),
        ("no_d_ranking_mutation", d_preserved, ""),
        ("no_protected_output_mutation", not protected_modified, ",".join(changed)),
        ("no_official_output_mutation", not official_changed, ",".join(official_changed)),
        ("historical_pre_event_random_backtest_disabled", True, ""),
        ("source_confidence_caps_applied", scored.loc[scored["event_confidence"].astype(str).str.upper().eq("LOW"), "event_risk_score"].le(60).all(), ""),
        ("no_default_025_exposure_scale", not policy["exposure_scale"].eq(.25).any(), ""),
        ("placebo_failure_acknowledged", scored["coefficient_reason"].str.contains("placebo", case=False).all(), ""),
        ("d_baseline_hash_preserved", d_preserved, f"{d_before} -> {d_after}"),
    ], columns=["check_name", "passed", "detail"])
    safety["research_only"] = True
    safety.to_csv(out / OUTPUTS[7], index=False)

    official_value = float(official["coefficient_value"].max())
    if official_value != 0:
        decision = "REJECT_COEFFICIENT_DESIGN_DUE_TO_OFFICIAL_WEIGHT_LEAK"
    elif protected_modified or official_changed:
        decision = "REJECT_COEFFICIENT_DESIGN_DUE_TO_MUTATION"
    elif promising_count > 0:
        decision = "EVENT_COEFFICIENTS_FORWARD_SUBSET_MONITOR_ONLY"
    else:
        decision = "EVENT_COEFFICIENTS_DIAGNOSTIC_ONLY_D_INTEGRATION_BLOCKED"
    summary = {
        "FINAL_STATUS": "PASS" if validation["status"] == "PASS" and safety["passed"].all() and official_value == 0 else "FAIL",
        "DECISION": decision,
        "INPUT_V21_100_STATUS": summary_100.get("FINAL_STATUS", "MISSING"),
        "INPUT_V21_100_R1_STATUS": summary_r1.get("FINAL_STATUS", "MISSING"),
        "PLACEBO_FAILURE_CONFIRMED": bool(summary_r1.get("PLACEBO_FAILURE_CONFIRMED")),
        "PROMISING_NARROW_SUBSETS_FOUND": promising_count > 0,
        "OFFICIAL_EVENT_RISK_COEFFICIENT": official_value,
        "OFFICIAL_D_INTEGRATION_ALLOWED": False,
        "OFFICIAL_SHADOW_RANKING_ALLOWED": False,
        "RESEARCH_DIAGNOSTIC_COEFFICIENTS_CREATED": len(research),
        "TOP20_FORWARD_ROWS_SCORED": len(scored),
        "RISK_BUCKETS_CREATED": len(policy),
        "MAX_RESEARCH_EXPOSURE_REDUCTION": float(1 - policy["exposure_scale"].min()),
        "DEFAULT_EXTREME_EXPOSURE_SCALE": float(policy.set_index("risk_bucket").loc["EXTREME", "exposure_scale"]),
        "HISTORICAL_PRE_EVENT_RANDOM_BACKTEST_ALLOWED": False,
        "FORWARD_OBSERVATION_ALLOWED": True,
        "EVENT_WEIGHT_RESEARCH_FROZEN": True,
        "PIT_LEAKAGE_WARNINGS": pit_warnings,
        "PROTECTED_OUTPUTS_MODIFIED": protected_modified,
        "OFFICIAL_OUTPUTS_MODIFIED": bool(official_changed),
        "RESEARCH_ONLY": True, "OFFICIAL_ADOPTION_ALLOWED": False,
        "D_BASELINE_PRESERVED": d_preserved,
        "RECOMMENDED_NEXT_STAGE": "V21.102_DIAGNOSTIC_EVENT_COEFFICIENT_FORWARD_OBSERVATION_ONLY",
    }
    write_json(out / OUTPUTS[9], summary)
    (out / OUTPUTS[8]).write_text(report(summary), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    summary = run(args.root.resolve())
    for key, value in summary.items():
        print(f"{key}={value}")
    return 0 if summary["FINAL_STATUS"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
