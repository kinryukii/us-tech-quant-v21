from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


STAGE = "V21.157_E_R1_SHADOW_TRIGGER_ATTRIBUTION_AND_FORWARD_MATURITY_GATE"
OUT = Path("outputs/v21/V21.157_E_R1_SHADOW_TRIGGER_ATTRIBUTION_AND_FORWARD_MATURITY_GATE")
V156 = Path("outputs/v21/V21.156_CONDITIONAL_STRATEGY_SWITCHING_SHADOW_SIMULATION")
V154 = Path("outputs/v21/V21.154_E_R1_INVALID_TRIAL_REPAIR_AND_REPLAY_REAUDIT")
PRICE = Path("outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")

REQUIRED = {
    "shadow_candidate_state_by_date": V156 / "shadow_candidate_state_by_date.csv",
    "governed_state_by_date": V156 / "governed_state_by_date.csv",
    "signal_score_by_date": V156 / "signal_score_by_date.csv",
    "switch_trigger_ledger": V156 / "switch_trigger_ledger.csv",
    "switch_blocker_ledger": V156 / "switch_blocker_ledger.csv",
    "switching_shadow_performance_clean_only": V156 / "switching_shadow_performance_clean_only.csv",
    "e_r1_vs_a1_clean_replay_result": V154 / "e_r1_vs_a1_clean_replay_result.csv",
}

FLAGS = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "governed_state_unchanged": True,
    "current_primary_control_unchanged": True,
}


def discover(name: str, path: Path) -> dict:
    row = {"source_name": name, "path": str(path).replace("\\", "/"), "exists": path.exists(), "rows": 0, "date_min": "", "date_max": "", "usable": False, "warning": ""}
    if not path.exists():
        row["warning"] = "INPUT_MISSING"
        return row
    try:
        df = pd.read_csv(path)
        row["rows"] = len(df)
        cols = [c for c in df.columns if "date" in c.lower() or c == "as_of_date"]
        if cols and len(df):
            vals = pd.to_datetime(df[cols[0]], errors="coerce").dropna()
            if len(vals):
                row["date_min"] = str(vals.min().date())
                row["date_max"] = str(vals.max().date())
        row["usable"] = True
    except Exception as exc:
        row["warning"] = f"READ_ERROR:{exc}"
    return row


def latest_price_date() -> str:
    if not PRICE.exists():
        return ""
    return str(pd.to_datetime(pd.read_csv(PRICE, usecols=["date"])["date"]).max().date())


def trigger_category(row: pd.Series) -> tuple[str, str, str, float]:
    reasons = []
    if pd.notna(row.get("risk_off_score")) and row["risk_off_score"] >= 3:
        reasons.append("RISK_OFF_SCORE_TRIGGER")
    if pd.notna(row.get("left_tail_risk_score")) and row["left_tail_risk_score"] >= 2:
        reasons.append("LEFT_TAIL_RISK_TRIGGER")
    if pd.notna(row.get("repeated_loser_score")) and row["repeated_loser_score"] >= 2:
        reasons.append("REPEATED_LOSER_TRIGGER")
    if pd.notna(row.get("concentration_score")) and row["concentration_score"] >= 2:
        reasons.append("CONCENTRATION_RISK_TRIGGER")
    if pd.notna(row.get("data_quality_score")) and row["data_quality_score"] >= 3:
        reasons.append("DATA_QUALITY_FALLBACK_TRIGGER")
    if len(reasons) > 1:
        primary = "COMPOSITE_DEFENSIVE_TRIGGER"
        secondary = "|".join(reasons)
        confidence = 0.85
    elif reasons:
        primary = reasons[0]
        secondary = ""
        confidence = 0.70
    else:
        primary = "UNKNOWN_TRIGGER"
        secondary = ""
        confidence = 0.20
    return primary, secondary, primary, confidence


def quality_summary(triggers: pd.DataFrame, total_dates: int) -> tuple[pd.DataFrame, str, bool]:
    count = len(triggers)
    rate = count / max(total_dates, 1)
    if count == 0:
        quality = "INSUFFICIENT_SAMPLE"
        overactive = False
    elif rate > 0.5:
        quality = "WEAK"
        overactive = True
    elif count < 3:
        quality = "INSUFFICIENT_SAMPLE"
        overactive = False
    elif (triggers["trigger_reason_primary"] == "DATA_QUALITY_FALLBACK_TRIGGER").mean() > 0.5:
        quality = "WEAK"
        overactive = False
    else:
        quality = "SUPPORTIVE"
        overactive = False
    clusters = 0
    if count:
        dates = pd.to_datetime(triggers["as_of_date"]).sort_values()
        clusters = int((dates.diff().dt.days.fillna(99) > 1).sum())
    return (
        pd.DataFrame(
            [
                {
                    "e_r1_trigger_date_count": count,
                    "e_r1_trigger_rate": rate,
                    "consecutive_trigger_clusters": clusters,
                    "average_trigger_confidence": triggers["trigger_confidence"].mean() if count else None,
                    "false_or_weak_trigger_count": int((triggers["trigger_confidence"] < 0.5).sum()) if count else 0,
                    "missing_score_trigger_count": int((triggers["trigger_reason_primary"] == "DATA_QUALITY_FALLBACK_TRIGGER").sum()) if count else 0,
                    "overactive_trigger_warning": overactive,
                    "trigger_quality": quality,
                }
            ]
        ),
        quality,
        overactive,
    )


def forward_outcomes(triggers: pd.DataFrame, latest: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows = []
    latest_ts = pd.Timestamp(latest) if latest else pd.Timestamp.min
    for _, trig in triggers.iterrows():
        d = pd.Timestamp(trig["as_of_date"])
        for bucket in ["Top20", "Top50"]:
            for horizon, days in {"5D": 5, "10D": 10, "20D": 20}.items():
                required = d + pd.tseries.offsets.BDay(days)
                matured = required <= latest_ts
                rows.append(
                    {
                        "as_of_date": str(d.date()),
                        "portfolio_bucket": bucket,
                        "holding_horizon": horizon,
                        "required_maturity_date": str(required.date()),
                        "E_R1_forward_return": None,
                        "A1_forward_return": None,
                        "QQQ_forward_return": None,
                        "E_R1_minus_A1": None,
                        "E_R1_minus_QQQ": None,
                        "E_R1_win_loss_vs_A1": None,
                        "E_R1_left_tail_proxy_vs_A1": None,
                        "E_R1_drawdown_proxy_vs_A1": None,
                        "E_R1_return_sacrifice_vs_A1": None,
                        "valid_paired_observation": False,
                        "maturity_status": "matured_no_clean_trigger_ledger" if matured else "immature",
                    }
                )
    out = pd.DataFrame(rows)
    summary = out.groupby(["portfolio_bucket", "holding_horizon", "maturity_status"], dropna=False).size().reset_index(name="count") if len(out) else pd.DataFrame(columns=["portfolio_bucket", "holding_horizon", "maturity_status", "count"])
    gate = {
        "total_trigger_dates": len(triggers),
        "matured_trigger_5D_count": int(out[(out["holding_horizon"].eq("5D")) & (out["maturity_status"].str.startswith("matured"))]["as_of_date"].nunique()) if len(out) else 0,
        "matured_trigger_10D_count": int(out[(out["holding_horizon"].eq("10D")) & (out["maturity_status"].str.startswith("matured"))]["as_of_date"].nunique()) if len(out) else 0,
        "matured_trigger_20D_count": int(out[(out["holding_horizon"].eq("20D")) & (out["maturity_status"].str.startswith("matured"))]["as_of_date"].nunique()) if len(out) else 0,
        "valid_paired_trigger_5D_count": int(out[(out["holding_horizon"].eq("5D")) & (out["valid_paired_observation"])]["as_of_date"].nunique()) if len(out) else 0,
        "valid_paired_trigger_10D_count": int(out[(out["holding_horizon"].eq("10D")) & (out["valid_paired_observation"])]["as_of_date"].nunique()) if len(out) else 0,
        "valid_paired_trigger_20D_count": int(out[(out["holding_horizon"].eq("20D")) & (out["valid_paired_observation"])]["as_of_date"].nunique()) if len(out) else 0,
    }
    gate["trigger_maturity_sufficient"] = gate["valid_paired_trigger_10D_count"] >= 3 and gate["valid_paired_trigger_20D_count"] >= 3
    gate["trigger_maturity_warning"] = "WAIT_MORE_FORWARD_MATURITY" if not gate["trigger_maturity_sufficient"] else ""
    return out, summary, pd.DataFrame([gate])


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    discovery = pd.DataFrame([discover(k, p) for k, p in REQUIRED.items()])
    core_missing = discovery[discovery["source_name"].isin(["shadow_candidate_state_by_date", "governed_state_by_date", "signal_score_by_date"]) & ~discovery["usable"].astype(bool)]
    if not core_missing.empty:
        final_status = "BLOCKED_V21_157_E_R1_TRIGGER_INPUTS_MISSING"
        decision = "DO_NOT_USE_E_R1_TRIGGER_REVIEW_UNTIL_INPUTS_REPAIRED"
        empty = pd.DataFrame()
        discovery.to_csv(OUT / "input_discovery_report.csv", index=False)
        for name in ["e_r1_trigger_dates.csv", "e_r1_trigger_attribution_ledger.csv", "e_r1_trigger_score_decomposition.csv", "e_r1_trigger_quality_summary.csv", "e_r1_trigger_forward_outcomes.csv", "e_r1_trigger_forward_summary.csv", "e_r1_forward_maturity_gate.csv", "e_r1_defensive_benefit_vs_return_sacrifice.csv", "e_r1_role_review_gate_decision.csv"]:
            empty.to_csv(OUT / name, index=False)
        summary = {"FINAL_STATUS": final_status, "DECISION": decision, **FLAGS}
        (OUT / "V21.157_machine_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return 0
    shadow = pd.read_csv(REQUIRED["shadow_candidate_state_by_date"])
    governed = pd.read_csv(REQUIRED["governed_state_by_date"])
    scores = pd.read_csv(REQUIRED["signal_score_by_date"])
    blockers = pd.read_csv(REQUIRED["switch_blocker_ledger"])
    merged = shadow.merge(governed, on="as_of_date", how="left").merge(scores, on="as_of_date", how="left")
    merged = merged.merge(blockers[["as_of_date", "shadow_candidate_state", "blocker_code", "blocker_detail"]], on=["as_of_date", "shadow_candidate_state"], how="left")
    trig = merged[merged["shadow_candidate_state"].eq("STATE_DEFENSIVE_A1_E_R1")].copy()
    attrib_rows, score_rows = [], []
    for _, row in trig.iterrows():
        primary, secondary, category, confidence = trigger_category(row)
        attrib_rows.append(
            {
                "as_of_date": row["as_of_date"],
                "governed_state": row["governed_state"],
                "shadow_candidate_state": row["shadow_candidate_state"],
                "blocker_code": row.get("blocker_code", ""),
                "blocker_detail": row.get("blocker_detail", ""),
                "trigger_reason_primary": primary,
                "trigger_reason_secondary": secondary,
                "trigger_confidence": confidence,
            }
        )
        checks = [
            ("risk_off_score", row.get("risk_off_score"), 3),
            ("left_tail_risk_score", row.get("left_tail_risk_score"), 2),
            ("repeated_loser_score", row.get("repeated_loser_score"), 2),
            ("concentration_score", row.get("concentration_score"), 2),
            ("data_quality_score", row.get("data_quality_score"), 3),
        ]
        rank = 1
        for name, value, threshold in checks:
            triggered = pd.notna(value) and value >= threshold
            score_rows.append(
                {
                    "as_of_date": row["as_of_date"],
                    "score_name": name,
                    "score_value": value,
                    "threshold": threshold,
                    "triggered": triggered,
                    "contribution_rank": rank if triggered else None,
                    "attribution_comment": f"{name} {'met' if triggered else 'did not meet'} trigger threshold",
                }
            )
            if triggered:
                rank += 1
    attrib = pd.DataFrame(attrib_rows)
    trigger_dates = attrib[["as_of_date", "shadow_candidate_state", "governed_state", "blocker_code", "trigger_reason_primary", "trigger_confidence"]].copy() if len(attrib) else pd.DataFrame(columns=["as_of_date", "shadow_candidate_state", "governed_state", "blocker_code", "trigger_reason_primary", "trigger_confidence"])
    quality, trigger_quality, overactive = quality_summary(attrib, len(shadow))
    latest = latest_price_date()
    fwd, fwd_summary, maturity_gate = forward_outcomes(attrib, latest)
    benefit = pd.DataFrame(
        [
            {
                "E_R1_left_tail_improvement_rate_vs_A1": None,
                "E_R1_drawdown_proxy_improvement_rate_vs_A1": None,
                "E_R1_average_return_sacrifice_vs_A1": None,
                "E_R1_worst_case_relative_underperformance_vs_A1": None,
                "E_R1_winrate_vs_A1_after_trigger_dates": None,
                "E_R1_risk_adjusted_benefit_classification": "INSUFFICIENT_FORWARD_MATURITY",
            }
        ]
    )
    maturity_sufficient = bool(maturity_gate.iloc[0]["trigger_maturity_sufficient"]) if len(maturity_gate) else False
    if trigger_quality == "SUPPORTIVE" and maturity_sufficient:
        final_status = "PASS_V21_157_E_R1_ROLE_REVIEW_READY"
        decision = "E_R1_DEFENSIVE_OVERLAY_ROLE_REVIEW_READY_RESEARCH_ONLY"
        role_ready = True
    elif trigger_quality in {"SUPPORTIVE", "INSUFFICIENT_SAMPLE"} and not maturity_sufficient:
        final_status = "PARTIAL_PASS_V21_157_E_R1_WAIT_MORE_FORWARD_MATURITY"
        decision = "KEEP_E_R1_DEFENSIVE_CANDIDATE_WAIT_FORWARD_MATURITY"
        role_ready = False
    elif trigger_quality == "WEAK" or overactive:
        final_status = "WARN_V21_157_E_R1_TRIGGER_WEAK_OR_OVERACTIVE"
        decision = "E_R1_TRIGGER_RULES_REQUIRE_RECALIBRATION"
        role_ready = False
    else:
        final_status = "PARTIAL_PASS_V21_157_E_R1_DEFENSIVE_SIGNAL_NOT_CONFIRMED"
        decision = "E_R1_DOWNGRADED_DIAGNOSTIC_ONLY"
        role_ready = False
    role_decision = pd.DataFrame(
        [
            {
                "role_review_status": "ROLE_REVIEW_READY" if role_ready else ("WAIT_MORE_FORWARD_MATURITY" if "WAIT" in final_status else "TRIGGER_RULE_RECALIBRATION_REQUIRED"),
                "FINAL_STATUS": final_status,
                "DECISION": decision,
                "governed_state_unchanged": True,
                "broker_action_allowed": False,
            }
        ]
    )
    summary = {
        "FINAL_STATUS": final_status,
        "DECISION": decision,
        "latest_price_date_used": latest,
        "e_r1_trigger_date_count": int(quality.iloc[0]["e_r1_trigger_date_count"]),
        "e_r1_trigger_rate": float(quality.iloc[0]["e_r1_trigger_rate"]),
        "trigger_quality": trigger_quality,
        "overactive_trigger_warning": bool(overactive),
        "matured_trigger_5D_count": int(maturity_gate.iloc[0]["matured_trigger_5D_count"]),
        "matured_trigger_10D_count": int(maturity_gate.iloc[0]["matured_trigger_10D_count"]),
        "matured_trigger_20D_count": int(maturity_gate.iloc[0]["matured_trigger_20D_count"]),
        "valid_paired_trigger_5D_count": int(maturity_gate.iloc[0]["valid_paired_trigger_5D_count"]),
        "valid_paired_trigger_10D_count": int(maturity_gate.iloc[0]["valid_paired_trigger_10D_count"]),
        "valid_paired_trigger_20D_count": int(maturity_gate.iloc[0]["valid_paired_trigger_20D_count"]),
        "trigger_maturity_sufficient": bool(maturity_sufficient),
        "e_r1_left_tail_benefit_persisted_after_triggers": False,
        "e_r1_return_sacrifice_classification": "INSUFFICIENT_FORWARD_MATURITY",
        "e_r1_role_review_ready": bool(role_ready),
        **FLAGS,
    }
    discovery.to_csv(OUT / "input_discovery_report.csv", index=False)
    trigger_dates.to_csv(OUT / "e_r1_trigger_dates.csv", index=False)
    attrib.to_csv(OUT / "e_r1_trigger_attribution_ledger.csv", index=False)
    pd.DataFrame(score_rows).to_csv(OUT / "e_r1_trigger_score_decomposition.csv", index=False)
    quality.to_csv(OUT / "e_r1_trigger_quality_summary.csv", index=False)
    fwd.to_csv(OUT / "e_r1_trigger_forward_outcomes.csv", index=False)
    fwd_summary.to_csv(OUT / "e_r1_trigger_forward_summary.csv", index=False)
    maturity_gate.to_csv(OUT / "e_r1_forward_maturity_gate.csv", index=False)
    benefit.to_csv(OUT / "e_r1_defensive_benefit_vs_return_sacrifice.csv", index=False)
    role_decision.to_csv(OUT / "e_r1_role_review_gate_decision.csv", index=False)
    (OUT / "V21.157_machine_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report = [
        STAGE,
        f"FINAL_STATUS={final_status}",
        f"DECISION={decision}",
        f"latest_price_date_used={latest}",
        f"e_r1_trigger_date_count={summary['e_r1_trigger_date_count']}",
        f"trigger_quality={trigger_quality}",
        f"matured_trigger_10D_count={summary['matured_trigger_10D_count']}",
        f"valid_paired_trigger_10D_count={summary['valid_paired_trigger_10D_count']}",
        f"trigger_maturity_sufficient={str(maturity_sufficient).lower()}",
        f"e_r1_role_review_ready={str(role_ready).lower()}",
        "governed_state_unchanged=true",
        "current_primary_control_unchanged=true",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false",
    ]
    (OUT / "V21.157_readable_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
