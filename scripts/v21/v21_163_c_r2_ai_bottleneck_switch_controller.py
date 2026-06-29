from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.163_C_R2_AI_BOTTLENECK_SWITCH_CONTROLLER"
OUT = ROOT / "outputs" / "v21" / STAGE

A1_PATH = ROOT / "outputs" / "v21" / "V21.113_LATEST_DATA_ABCD_RERUN_20260625_PRICE_REFRESH" / "A1_BASELINE_CONTROL_latest_ranking.csv"
C_R2_RANK = ROOT / "outputs" / "v21" / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR" / "c_r2_r1_shadow_ranking_full.csv"
C_R2_REGIME = ROOT / "outputs" / "v21" / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR" / "c_r2_r1_regime_audit.csv"
C_R2_SUMMARY = ROOT / "outputs" / "v21" / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR" / "V21.161_R1_C_R2_PROXY_AND_REGIME_REPAIR_summary.json"
AI_RANK = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_shadow_ranking_full.csv"
AI_CONC = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_subtheme_concentration.csv"
AI_EXCLUDED = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_non_eligible_c_r2_top20.csv"
AI_WARN = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "ai_bottleneck_data_quality_warnings.csv"
AI_SUMMARY = ROOT / "outputs" / "v21" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING" / "V21.162_AI_BOTTLENECK_BASKET_TAGGING_AND_RANKING_summary.json"

SOFTCAP_CANDIDATES = [
    ROOT / "outputs" / "v21" / "V21.159_SOFT_CAP_RECIPIENT_RISK_FILTER_AND_SWITCHING_ELIGIBILITY_AUDIT" / "softcap_filter_backtest_summary.csv",
    ROOT / "outputs" / "v21" / "V21.152_SOFT_CAP_FORWARD_MATURITY_MONITOR" / "soft_cap_matured_metrics_by_policy.csv",
    ROOT / "outputs" / "v21" / "V21.151_R3_SOFT_CAP_FORWARD_TRACKING_UPDATE" / "soft_cap_forward_metrics_by_policy.csv",
]
E_R1_CANDIDATES = [
    ROOT / "outputs" / "v21" / "V21.157_E_R1_SHADOW_TRIGGER_ATTRIBUTION_AND_FORWARD_MATURITY_GATE" / "e_r1_role_review_gate_decision.csv",
    ROOT / "outputs" / "v21" / "V21.149_E_R1_DEFENSIVE_OVERLAY_AND_INVALID_TRIAL_AUDIT" / "V21.149_e_r1_defensive_overlay_tests.csv",
    ROOT / "outputs" / "v21" / "V21.134_E_R1_FORWARD_TRACKING_LEDGER" / "e_r1_forward_tracking_summary.json",
]

REQUIRED_STATES = [
    "A1_ONLY_CONTROL",
    "A1_PLUS_C_R2_FORWARD_TRACKING",
    "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING",
    "A1_PLUS_E_R1_DEFENSIVE_FORWARD_TRACKING",
    "A1_PLUS_SOFTCAP_WATCH_ONLY",
    "NO_SWITCH_INSUFFICIENT_EVIDENCE",
]

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "protected_outputs_modified": False,
    "role_review_required": False,
    "switch_adoption_allowed": False,
    "live_trading_allowed": False,
}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def protected_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for base in [ROOT / "outputs", ROOT / "data"]:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or OUT in path.parents:
                continue
            rel = path.relative_to(ROOT).as_posix().lower().replace("-", "_")
            protected = any(token in rel for token in ["broker", "real_book", "realbook"])
            protected = protected or ("official" in rel and any(k in rel for k in ["rank", "weight", "allocation", "recommend"]))
            if protected:
                hashes[path.relative_to(ROOT).as_posix()] = sha(path)
    return hashes


def source_status(path: Path) -> dict[str, Any]:
    exists = path.exists()
    rows = 0
    if exists:
        try:
            rows = len(read_csv(path)) if path.suffix.lower() == ".csv" else 1
        except Exception:
            rows = 0
    return {"path": path.relative_to(ROOT).as_posix(), "exists": exists, "rows": rows}


def first_existing(paths: list[Path]) -> Path | None:
    return next((p for p in paths if p.exists()), None)


def clean_policy(summary: dict[str, Any], adoption_key: str) -> bool:
    return (
        summary.get("research_only") is True
        and summary.get("official_adoption_allowed") is False
        and summary.get("broker_action_allowed") is False
        and summary.get("protected_outputs_modified") is False
        and summary.get("role_review_required") is False
        and summary.get(adoption_key) is False
    )


def build_rules(c_r2_ok: bool, ai_ok: bool, regime: str, confidence: float, e_available: bool, soft_available: bool, ai_conc: float) -> pd.DataFrame:
    rules = [
        ("A1_PRIMARY_DEFAULT", True, "A1 remains primary control by default."),
        ("C_R2_RANKING_EXISTS", C_R2_RANK.exists(), "C-R2 repaired ranking must exist."),
        ("C_R2_ADOPTION_BLOCKED", c_r2_ok, "C-R2 adoption must remain blocked with clean policy flags."),
        ("C_R2_REGIME_CONFIDENCE_GATE", confidence >= 0.5, "C-R2 regime confidence must be >= 0.5 for challenger tracking."),
        ("C_R2_RISK_ON_FORWARD_GATE", regime == "risk_on" and confidence >= 0.75, "Risk-on and confidence >= 0.75 allows C-R2 forward tracking."),
        ("AI_RANKING_EXISTS", AI_RANK.exists(), "AI Bottleneck ranking must exist."),
        ("AI_ADOPTION_BLOCKED", ai_ok, "AI Bottleneck adoption must remain blocked with clean policy flags."),
        ("AI_TAXONOMY_RESEARCH_ONLY_ACCEPTED", True, "PIT-lite taxonomy warning accepted only for research-only tracking."),
        ("AI_CONCENTRATION_GATE", ai_conc <= 0.40, "AI Top20 max subtheme concentration should be <= 40%; warn at boundary/above."),
        ("AI_RISK_ON_FORWARD_GATE", regime == "risk_on" and confidence >= 0.75 and AI_RANK.exists(), "Risk-on C-R2 state and AI diagnostics allow AI theme forward tracking."),
        ("RISK_OFF_E_R1_DEFENSIVE_GATE", regime == "risk_off" and e_available, "Risk-off prefers E_R1 defensive forward tracking if available."),
        ("SOFTCAP_WATCH_ONLY", soft_available, "Soft-cap remains watch-only unless prior status explicitly supports promotion."),
        ("NO_ADOPTION_OR_BROKER_ACTION", True, "No state enables official adoption, role review, broker action, or live trading."),
    ]
    return pd.DataFrame([
        {"rule_id": rid, "passed": passed, "rule_description": desc, "research_only": True}
        for rid, passed, desc in rules
    ])


def run_stage() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    warnings: list[dict[str, Any]] = []

    a1 = read_csv(A1_PATH)
    c_r2 = read_csv(C_R2_RANK)
    ai = read_csv(AI_RANK)
    ai_conc_df = read_csv(AI_CONC)
    ai_excluded = read_csv(AI_EXCLUDED)
    c_r2_summary = read_json(C_R2_SUMMARY)
    ai_summary = read_json(AI_SUMMARY)
    soft_path = first_existing(SOFTCAP_CANDIDATES)
    e_path = first_existing(E_R1_CANDIDATES)

    selected_regime = str(c_r2_summary.get("selected_regime", "unknown"))
    regime_confidence = float(c_r2_summary.get("regime_confidence", 0.0) or 0.0)
    latest = str(c_r2_summary.get("latest_price_date_used") or ai_summary.get("latest_price_date_used") or "")
    c_r2_policy_clean = clean_policy(c_r2_summary, "c_r2_adoption_allowed")
    ai_policy_clean = clean_policy(ai_summary, "ai_bottleneck_adoption_allowed")
    c_r2_challenger = bool(
        not c_r2.empty
        and c_r2_policy_clean
        and selected_regime in {"risk_on", "neutral", "risk_off"}
        and regime_confidence >= 0.5
    )
    ai_top20_max_conc = float(ai_summary.get("max_single_theme_weight_top20", 0.0) or 0.0)
    taxonomy_warning_present = any(str(w.get("warning_type")) == "PIT_LITE_TAXONOMY" for w in ai_summary.get("warnings", []))
    ai_theme_tracking = bool(
        not ai.empty
        and ai_policy_clean
        and taxonomy_warning_present
        and selected_regime == "risk_on"
        and regime_confidence >= 0.75
    )
    if ai_top20_max_conc >= 0.40:
        warnings.append({
            "warning_type": "AI_TOP20_THEME_CONCENTRATION_AT_LIMIT",
            "warning": f"AI Top20 max subtheme concentration is {ai_top20_max_conc:.2f}; research-only warning retained.",
        })
    if not c_r2_policy_clean:
        warnings.append({"warning_type": "C_R2_POLICY_NOT_CLEAN", "warning": "C-R2 policy flags are not clean; challenger disabled."})
    if not ai_policy_clean:
        warnings.append({"warning_type": "AI_POLICY_NOT_CLEAN", "warning": "AI Bottleneck policy flags are not clean; theme sleeve disabled."})
    if taxonomy_warning_present:
        warnings.append({"warning_type": "AI_PIT_LITE_TAXONOMY_ACCEPTED_RESEARCH_ONLY", "warning": "AI sleeve taxonomy is PIT-lite and accepted only for forward tracking."})

    e_available = e_path is not None
    soft_available = soft_path is not None
    e_active = selected_regime == "risk_off" and e_available
    soft_watch_only = soft_available
    if selected_regime == "risk_off" and e_active:
        selected_state = "A1_PLUS_E_R1_DEFENSIVE_FORWARD_TRACKING"
    elif selected_regime == "risk_on" and c_r2_challenger and ai_theme_tracking:
        selected_state = "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING"
    elif selected_regime == "risk_on" and c_r2_challenger:
        selected_state = "A1_PLUS_C_R2_FORWARD_TRACKING"
    elif soft_watch_only:
        selected_state = "A1_PLUS_SOFTCAP_WATCH_ONLY"
    elif len(a1):
        selected_state = "A1_ONLY_CONTROL"
    else:
        selected_state = "NO_SWITCH_INSUFFICIENT_EVIDENCE"

    component_rows = [
        {"component": "A1_PRIMARY_CONTROL", "available": not a1.empty, "status": "PRIMARY_CONTROL", "adoption_allowed": False, "source_path": A1_PATH.relative_to(ROOT).as_posix(), "notes": "Primary control remains A1."},
        {"component": "C_R2_FACTOR_ROTATION", "available": not c_r2.empty, "status": "CHALLENGER_FORWARD_TRACKING" if c_r2_challenger else "DISABLED_OR_INSUFFICIENT", "adoption_allowed": False, "source_path": C_R2_RANK.relative_to(ROOT).as_posix(), "notes": c_r2_summary.get("final_status", "")},
        {"component": "AI_BOTTLENECK_THEME", "available": not ai.empty, "status": "THEME_FORWARD_TRACKING" if ai_theme_tracking else "DISABLED_OR_INSUFFICIENT", "adoption_allowed": False, "source_path": AI_RANK.relative_to(ROOT).as_posix(), "notes": ai_summary.get("final_status", "")},
        {"component": "E_R1_DEFENSIVE_OVERLAY", "available": e_available, "status": "DEFENSIVE_FORWARD_TRACKING" if e_active else "AVAILABLE_NOT_ACTIVE_IN_CURRENT_REGIME" if e_available else "MISSING", "adoption_allowed": False, "source_path": e_path.relative_to(ROOT).as_posix() if e_path else "", "notes": "Only preferred in risk_off."},
        {"component": "SOFTCAP_RETURN_OVERLAY", "available": soft_available, "status": "WATCH_ONLY" if soft_watch_only else "MISSING", "adoption_allowed": False, "source_path": soft_path.relative_to(ROOT).as_posix() if soft_path else "", "notes": "No promotion without explicit prior support."},
    ]
    component_status = pd.DataFrame(component_rows)
    component_status.to_csv(OUT / "switch_controller_component_status.csv", index=False)

    rules = build_rules(c_r2_policy_clean, ai_policy_clean, selected_regime, regime_confidence, e_available, soft_available, ai_top20_max_conc)
    rules.to_csv(OUT / "switch_controller_decision_rules.csv", index=False)

    research_alloc = pd.DataFrame([
        {"sleeve": "A1_PRIMARY_CONTROL", "research_state": "PRIMARY_CONTROL_REFERENCE", "research_tracking_weight": 1.0, "official_weight": 0.0, "broker_action_allowed": False, "notes": "Research state only; not a trade allocation."},
        {"sleeve": "C_R2_FACTOR_ROTATION", "research_state": "FORWARD_TRACKING" if c_r2_challenger else "INACTIVE", "research_tracking_weight": 0.0, "official_weight": 0.0, "broker_action_allowed": False, "notes": "Challenger only; adoption blocked."},
        {"sleeve": "AI_BOTTLENECK_THEME", "research_state": "FORWARD_TRACKING" if ai_theme_tracking else "INACTIVE", "research_tracking_weight": 0.0, "official_weight": 0.0, "broker_action_allowed": False, "notes": "Theme sleeve only; excludes non-AI C-R2 names."},
        {"sleeve": "E_R1_DEFENSIVE", "research_state": "FORWARD_TRACKING" if e_active else "STANDBY", "research_tracking_weight": 0.0, "official_weight": 0.0, "broker_action_allowed": False, "notes": "Risk-off defensive only."},
        {"sleeve": "SOFTCAP", "research_state": "WATCH_ONLY" if soft_watch_only else "MISSING", "research_tracking_weight": 0.0, "official_weight": 0.0, "broker_action_allowed": False, "notes": "Watch-only."},
    ])
    research_alloc.to_csv(OUT / "switch_controller_research_allocation_state.csv", index=False)

    excluded_cols = ["ticker", "primary_ai_bottleneck_theme", "reason", "manual_review_required", "tag_source"]
    if ai_excluded.empty:
        ai_excluded = pd.DataFrame(columns=excluded_cols)
    ai_excluded[[c for c in excluded_cols if c in ai_excluded.columns]].to_csv(OUT / "switch_controller_excluded_names.csv", index=False)

    warn_df = pd.DataFrame(warnings) if warnings else pd.DataFrame([{"warning_type": "NONE", "warning": ""}])
    warn_df.to_csv(OUT / "switch_controller_warnings.csv", index=False)

    policy_df = pd.DataFrame([{**POLICY, "protected_outputs_modified": False, "switch_adoption_allowed": False, "live_trading_allowed": False}])
    policy_df.to_csv(OUT / "switch_controller_policy_flags.csv", index=False)

    state = pd.DataFrame([{
        "selected_switch_state": selected_state,
        "a1_primary_control": True,
        "c_r2_challenger_forward_tracking": c_r2_challenger,
        "ai_bottleneck_theme_forward_tracking": ai_theme_tracking,
        "e_r1_defensive_forward_tracking": e_active,
        "softcap_watch_only": soft_watch_only,
        "selected_regime": selected_regime,
        "regime_confidence": regime_confidence,
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "live_trading_allowed": False,
    }])
    state.to_csv(OUT / "switch_controller_state.csv", index=False)

    after = protected_hashes()
    protected_modified = before != after
    final_status = (
        "FAIL_V21_163_SWITCH_SCRIPT_ERROR" if protected_modified
        else "WARN_V21_163_SWITCH_INSUFFICIENT_EVIDENCE" if selected_state == "NO_SWITCH_INSUFFICIENT_EVIDENCE"
        else "PARTIAL_PASS_V21_163_SWITCH_READY_WITH_WARNINGS" if warnings
        else "PASS_V21_163_SWITCH_CONTROLLER_READY_RESEARCH_ONLY"
    )
    excluded_names = ai_excluded["ticker"].dropna().astype(str).tolist() if "ticker" in ai_excluded.columns else []
    summary = {
        "final_status": final_status,
        "decision": "A1_PRIMARY_WITH_C_R2_AI_BOTTLENECK_FORWARD_TRACKING_ONLY",
        "selected_switch_state": selected_state,
        **{**POLICY, "protected_outputs_modified": protected_modified},
        "a1_primary_control": True,
        "c_r2_challenger_forward_tracking": c_r2_challenger,
        "ai_bottleneck_theme_forward_tracking": ai_theme_tracking,
        "e_r1_defensive_forward_tracking": e_active,
        "softcap_watch_only": soft_watch_only,
        "selected_regime": selected_regime,
        "regime_confidence": regime_confidence,
        "c_r2_status": component_rows[1]["status"],
        "ai_bottleneck_status": component_rows[2]["status"],
        "ai_bottleneck_top20_max_subtheme_concentration": ai_top20_max_conc,
        "excluded_non_ai_c_r2_names": excluded_names,
        "latest_price_date_used": latest,
        "warning_count": len(warnings),
        "warnings": warnings,
    }
    write_json(OUT / f"{STAGE}_summary.json", summary)
    report = [
        STAGE,
        f"final_status={final_status}",
        f"decision={summary['decision']}",
        f"selected_switch_state={selected_state}",
        f"selected_regime={selected_regime}",
        f"regime_confidence={regime_confidence}",
        "component_statuses=" + "; ".join(f"{r['component']}={r['status']}" for r in component_rows),
        "research_allocation_state=" + "; ".join(f"{r['sleeve']}={r['research_state']}" for _, r in research_alloc.iterrows()),
        "excluded_names=" + ", ".join(excluded_names),
        f"warnings={len(warnings)}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "live_trading_allowed=false",
    ]
    (OUT / f"{STAGE}_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    try:
        summary = run_stage()
    except Exception as exc:  # pragma: no cover
        OUT.mkdir(parents=True, exist_ok=True)
        summary = {
            "final_status": "FAIL_V21_163_SWITCH_SCRIPT_ERROR",
            "decision": "A1_PRIMARY_WITH_C_R2_AI_BOTTLENECK_FORWARD_TRACKING_ONLY",
            "selected_switch_state": "NO_SWITCH_INSUFFICIENT_EVIDENCE",
            **POLICY,
            "error": str(exc),
            "warning_count": 1,
        }
        write_json(OUT / f"{STAGE}_summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0 if not str(summary.get("final_status", "")).startswith("FAIL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
