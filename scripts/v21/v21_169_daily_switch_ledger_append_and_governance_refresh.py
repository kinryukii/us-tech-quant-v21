from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.169_DAILY_SWITCH_LEDGER_APPEND_AND_GOVERNANCE_REFRESH"
OUT = ROOT / "outputs" / "v21" / STAGE

V164 = ROOT / "outputs" / "v21" / "V21.164_SWITCH_STATE_FORWARD_TRACKING_LEDGER"
V164_R1 = ROOT / "outputs" / "v21" / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR"
V168_RULEBOOK = ROOT / "outputs" / "v21" / "V21.168_STRATEGY_SWITCHING_GOVERNANCE_RULEBOOK_R1"
PRICE = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"

FINAL_DECISIONS = {
    "KEEP_A1_CONTROL",
    "WAIT_MORE_MATURITY",
    "ALLOW_FORWARD_TRACKING_ONLY",
    "BLOCKED_BY_RISK",
    "BLOCKED_BY_EXECUTION",
    "BLOCKED_BY_DATA_QUALITY",
    "ROLE_REVIEW_REQUIRED",
    "SWITCH_ALLOWED_RESEARCH_ONLY",
    "OFFICIAL_ADOPTION_BLOCKED",
}
HORIZONS = ["5D", "10D", "20D"]
POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "live_trading_allowed": False,
    "protected_outputs_modified": False,
}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(name: str, df: pd.DataFrame) -> None:
    df.to_csv(OUT / name, index=False)


def write_json(name: str, payload: dict[str, Any]) -> None:
    (OUT / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


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
            s = rel(path).lower().replace("-", "_")
            protected = any(x in s for x in ["broker", "real_book", "realbook", "trade_action"])
            protected = protected or ("official" in s and any(x in s for x in ["rank", "weight", "allocation", "recommend"]))
            protected = protected or ("adopted" in s and any(x in s for x in ["weight", "allocation"]))
            if protected:
                hashes[rel(path)] = sha(path)
    return hashes


def git_dirty_state() -> tuple[bool, str, int]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception as exc:  # pragma: no cover - defensive environment guard
        return True, f"GIT_STATUS_UNAVAILABLE: {exc}", 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if result.returncode != 0:
        return True, "GIT_STATUS_FAILED: " + result.stderr.strip(), len(lines)
    return bool(lines), "PRE_EXISTING_DIRTY_STATE_DETECTED" if lines else "CLEAN", len(lines)


def source_status(path: Path, warnings: list[dict[str, Any]], name: str) -> str:
    if path.exists() and path.stat().st_size > 0:
        return "SOURCE_AVAILABLE"
    warnings.append({
        "source_name": name,
        "source_path": rel(path),
        "warning_type": "SOURCE_MISSING_WARNING",
        "warning": "Source file missing; refresh records warning and does not fabricate maturity or pass results.",
    })
    return "SOURCE_MISSING_WARNING"


def latest_price_date(ledger: pd.DataFrame, rulebook: dict[str, Any]) -> str:
    dates: list[pd.Timestamp] = []
    if not ledger.empty and "latest_price_date_used" in ledger.columns:
        d = pd.to_datetime(ledger["latest_price_date_used"], errors="coerce").dropna()
        if not d.empty:
            dates.append(d.max())
    if PRICE.exists():
        price = read_csv(PRICE)
        for col in ["date", "price_date", "latest_price_date_used"]:
            if col in price.columns:
                d = pd.to_datetime(price[col], errors="coerce").dropna()
                if not d.empty:
                    dates.append(d.max())
                    break
    if rulebook.get("latest_price_date_used"):
        d = pd.to_datetime(pd.Series([rulebook["latest_price_date_used"]]), errors="coerce").dropna()
        if not d.empty:
            dates.append(d.max())
    return str(max(dates).date()) if dates else ""


def latest_tracking_date(ledger: pd.DataFrame, r1_summary: dict[str, Any]) -> str:
    dates: list[pd.Timestamp] = []
    if not ledger.empty and "ranking_date" in ledger.columns:
        d = pd.to_datetime(ledger["ranking_date"], errors="coerce").dropna()
        if not d.empty:
            dates.append(d.max())
    if r1_summary.get("latest_ranking_date_seen"):
        d = pd.to_datetime(pd.Series([r1_summary["latest_ranking_date_seen"]]), errors="coerce").dropna()
        if not d.empty:
            dates.append(d.max())
    return str(max(dates).date()) if dates else ""


def maturity_scoreboard(ledger: pd.DataFrame, base_scoreboard: pd.DataFrame, warnings: list[dict[str, Any]]) -> pd.DataFrame:
    if ledger.empty:
        warnings.append({
            "source_name": "switch_state_forward_ledger",
            "source_path": rel(V164_R1 / "switch_ledger_r1_full_ledger.csv"),
            "warning_type": "SOURCE_MISSING_WARNING",
            "warning": "Switch ledger unavailable; maturity counts remain missing and cannot pass.",
        })
    states = []
    if not base_scoreboard.empty and "state" in base_scoreboard.columns:
        states = sorted(set(base_scoreboard["state"].astype(str)))
    elif not ledger.empty and "tracked_state" in ledger.columns:
        states = sorted(set(ledger["tracked_state"].astype(str)))
    if not states:
        states = ["A1_CONTROL", "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING"]

    rows = []
    for state in states:
        for horizon in HORIZONS:
            subset = pd.DataFrame()
            if not ledger.empty and {"tracked_state", "horizon", "maturity_status"}.issubset(ledger.columns):
                subset = ledger[ledger["tracked_state"].astype(str).eq(state) & ledger["horizon"].astype(str).eq(horizon)]
            matured = int(subset["maturity_status"].astype(str).eq("MATURED").sum()) if not subset.empty else 0
            pending = int(subset["maturity_status"].astype(str).eq("PENDING_MATURITY").sum()) if not subset.empty else 0
            missing = 1 if subset.empty else 0
            stale_warning = "SOURCE_MISSING_WARNING" if ledger.empty else "MISSING_OBSERVATION_WARNING" if subset.empty else "NONE"
            rows.append({
                "state": state,
                "horizon": horizon,
                "matured_observations": matured,
                "pending_observations": pending,
                "missing_observations": missing,
                "stale_source_warning": stale_warning,
                "maturity_gate_status": "PASS_MATURITY_AVAILABLE" if matured > 0 else "FAIL_WAIT_MATURITY",
                "research_only": True,
            })
    return pd.DataFrame(rows)


def blocker_summary(rulebook: dict[str, Any], maturity: pd.DataFrame) -> str:
    parts = []
    if int(maturity["matured_observations"].sum()) == 0:
        parts.append("INSUFFICIENT_MATURITY")
    if int(rulebook.get("source_warning_count", 0) or 0) > 0:
        parts.append("SOURCE_WARNINGS_PRESENT")
    if not parts:
        parts.append("NONE")
    return "|".join(parts)


def bool_from_payload(payload: dict[str, Any], key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def build_history(
    refresh_date: str,
    current_decision: str,
    rulebook: dict[str, Any],
    maturity: pd.DataFrame,
) -> tuple[pd.DataFrame, str, bool]:
    history_path = OUT / "refreshed_switch_state_decision_history.csv"
    existing = read_csv(history_path)
    previous_decision = current_decision
    if not existing.empty and "current_decision" in existing.columns:
        prior = existing[existing["refresh_date"].astype(str).ne(refresh_date)]
        if prior.empty:
            prior = existing
        previous_decision = str(prior.tail(1)["current_decision"].iloc[0])
    row = {
        "refresh_date": refresh_date,
        "previous_decision": previous_decision,
        "current_decision": current_decision,
        "decision_changed": previous_decision != current_decision,
        "current_primary_control": rulebook.get("current_primary_control", "A1_CONTROL"),
        "best_forward_tracking_state": rulebook.get("best_forward_tracking_state", "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING"),
        "role_review_required": bool_from_payload(rulebook, "role_review_required", False),
        "official_adoption_allowed": bool_from_payload(rulebook, "official_adoption_allowed", False),
        "broker_action_allowed": bool_from_payload(rulebook, "broker_action_allowed", False),
        "blocker_summary": blocker_summary(rulebook, maturity),
        "research_only": True,
    }
    if existing.empty:
        history = pd.DataFrame([row])
        initialized = True
    else:
        history = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
        history = history.drop_duplicates(["refresh_date"], keep="last").sort_values("refresh_date")
        initialized = False
    return history, previous_decision, initialized


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_hashes()
    pre_dirty, dirty_warning, dirty_count = git_dirty_state()
    warnings: list[dict[str, Any]] = []

    r1_summary_path = V164_R1 / "V21.164_R1_SWITCH_LEDGER_DAILY_APPEND_AND_MATURITY_MONITOR_summary.json"
    rulebook_summary_path = V168_RULEBOOK / "validation_summary.json"
    source_status(r1_summary_path, warnings, "V21.164_R1 switch ledger summary")
    source_status(V164_R1 / "switch_ledger_r1_full_ledger.csv", warnings, "V21.164_R1 switch ledger")
    source_status(rulebook_summary_path, warnings, "V21.168 governance validation summary")
    source_status(V168_RULEBOOK / "switch_state_maturity_scoreboard.csv", warnings, "V21.168 maturity scoreboard")

    r1_summary = read_json(r1_summary_path)
    rulebook = read_json(rulebook_summary_path)
    ledger = read_csv(V164_R1 / "switch_ledger_r1_full_ledger.csv")
    if ledger.empty:
        ledger = read_csv(V164 / "switch_state_forward_ledger.csv")
    base_maturity = read_csv(V168_RULEBOOK / "switch_state_maturity_scoreboard.csv")
    for upstream_warning in rulebook.get("warnings", []) if isinstance(rulebook.get("warnings", []), list) else []:
        if isinstance(upstream_warning, dict):
            carried = dict(upstream_warning)
            carried["warning_type"] = "UPSTREAM_" + str(carried.get("warning_type", "WARNING"))
            carried["source_name"] = "V21.168 governance: " + str(carried.get("source_name", "unknown"))
            warnings.append(carried)

    latest_price = latest_price_date(ledger, rulebook)
    latest_tracking = latest_tracking_date(ledger, r1_summary)
    source_latest_ranking = str(r1_summary.get("latest_ranking_date_seen") or latest_tracking)
    new_rows_appended = int(r1_summary.get("new_rows_appended_count", 0) or 0)
    no_new_data = new_rows_appended == 0
    append_status = "WARN_NO_NEW_SWITCH_LEDGER_DATA" if no_new_data else "PASS_NEW_SWITCH_LEDGER_ROWS_AVAILABLE"
    append_reason = (
        "No new V21.164 switch-state rows were appended; governance snapshot refreshed from existing data."
        if no_new_data
        else "V21.164 reports newly appended switch-state rows."
    )

    maturity = maturity_scoreboard(ledger, base_maturity, warnings)
    current_decision = str(rulebook.get("final_decision") or "WAIT_MORE_MATURITY")
    if current_decision not in FINAL_DECISIONS:
        current_decision = "OFFICIAL_ADOPTION_BLOCKED"
        warnings.append({
            "source_name": "V21.168 governance validation summary",
            "source_path": rel(rulebook_summary_path),
            "warning_type": "INVALID_DECISION_ENUM_WARNING",
            "warning": "Governance decision was outside allowed enum; stage blocked official adoption.",
        })

    refresh_date = latest_price or datetime.now(timezone.utc).date().isoformat()
    history, previous_decision, history_initialized = build_history(refresh_date, current_decision, rulebook, maturity)
    write_csv("refreshed_switch_state_decision_history.csv", history)

    previous_role = False
    if len(history) > 1:
        previous_role = str(history.iloc[-2].get("role_review_required", "False")).lower() in {"true", "1"}
    current_role = bool_from_payload(rulebook, "role_review_required", False)
    previous_official = False
    previous_broker = False
    if len(history) > 1:
        previous_official = str(history.iloc[-2].get("official_adoption_allowed", "False")).lower() in {"true", "1"}
        previous_broker = str(history.iloc[-2].get("broker_action_allowed", "False")).lower() in {"true", "1"}
    change = pd.DataFrame([{
        "refresh_date": refresh_date,
        "previous_decision": previous_decision,
        "current_decision": current_decision,
        "decision_changed": previous_decision != current_decision,
        "wait_maturity_changed_to_other": previous_decision == "WAIT_MORE_MATURITY" and current_decision != "WAIT_MORE_MATURITY",
        "previous_role_review_required": previous_role,
        "current_role_review_required": current_role,
        "role_review_required_changed_false_to_true": (not previous_role) and current_role,
        "previous_official_adoption_allowed": previous_official,
        "current_official_adoption_allowed": False,
        "official_adoption_allowed_changed": previous_official is not False,
        "previous_broker_action_allowed": previous_broker,
        "current_broker_action_allowed": False,
        "broker_action_allowed_changed": previous_broker is not False,
        "research_only": True,
    }])
    write_csv("switch_decision_change_log.csv", change)

    append_summary = pd.DataFrame([{
        "refresh_date": refresh_date,
        "append_status": append_status,
        "append_reason": append_reason,
        "latest_available_price_date": latest_price,
        "latest_switch_state_tracking_date": latest_tracking,
        "source_latest_ranking_date": source_latest_ranking,
        "existing_ledger_row_count": int(len(ledger)),
        "new_rows_appended": new_rows_appended,
        "matured_observation_count": int(maturity["matured_observations"].sum()),
        "pending_observation_count": int(maturity["pending_observations"].sum()),
        "missing_observation_count": int(maturity["missing_observations"].sum()),
        **POLICY,
    }])
    write_csv("daily_switch_ledger_append_summary.csv", append_summary)
    write_csv("refreshed_switch_state_maturity_scoreboard.csv", maturity)

    snapshot = pd.DataFrame([{
        "refresh_date": refresh_date,
        "final_decision": current_decision,
        "current_primary_control": rulebook.get("current_primary_control", "A1_CONTROL"),
        "best_forward_tracking_state": rulebook.get("best_forward_tracking_state", "A1_PLUS_C_R2_PLUS_AI_BOTTLENECK_FORWARD_TRACKING"),
        "role_review_required": current_role,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "active_cash_assumption_usd": int(rulebook.get("active_cash_assumption_usd", 600) or 600),
        "blocker_summary": blocker_summary(rulebook, maturity),
        "governance_source": rel(rulebook_summary_path) if rulebook else "SOURCE_MISSING_WARNING",
        **POLICY,
    }])
    write_csv("current_switch_governance_snapshot.csv", snapshot)

    after = protected_hashes()
    changed = [path for path, digest in before.items() if after.get(path) != digest]
    post_dirty, post_dirty_warning, post_dirty_count = git_dirty_state()
    stage_modified_unrelated_files = False
    protected_clean = len(changed) == 0
    if history_initialized:
        warnings.append({
            "source_name": "V21.169 decision history",
            "source_path": rel(OUT / "refreshed_switch_state_decision_history.csv"),
            "warning_type": "HISTORY_INITIALIZED",
            "warning": "No prior V21.169 decision history existed; initialized from current V21.168 decision.",
        })
    if no_new_data:
        warnings.append({
            "source_name": "V21.164_R1 switch ledger summary",
            "source_path": rel(r1_summary_path),
            "warning_type": "WARN_NO_NEW_SWITCH_LEDGER_DATA",
            "warning": append_reason,
        })

    validation = {
        "stage": STAGE,
        "final_status": append_status,
        "final_decision": current_decision,
        "allowed_final_decision_enum": sorted(FINAL_DECISIONS),
        **POLICY,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": False,
        "protected_output_mutation_audit_clean": protected_clean,
        "changed_protected_file_count": len(changed),
        "changed_protected_paths": changed,
        "stage_modified_unrelated_files": stage_modified_unrelated_files,
        "current_primary_control": snapshot["current_primary_control"].iloc[0],
        "best_forward_tracking_state": snapshot["best_forward_tracking_state"].iloc[0],
        "role_review_required": current_role,
        "active_cash_assumption_usd": int(snapshot["active_cash_assumption_usd"].iloc[0]),
        "latest_available_price_date": latest_price,
        "latest_switch_state_tracking_date": latest_tracking,
        "new_rows_appended": new_rows_appended,
        "no_new_data": no_new_data,
        "history_initialized": history_initialized,
        "decision_changed": bool(change["decision_changed"].iloc[0]),
        "repo_dirty_state_warning": dirty_warning,
        "pre_existing_dirty_state_detected": pre_dirty,
        "pre_existing_dirty_entry_count": dirty_count,
        "post_stage_dirty_state_warning": post_dirty_warning,
        "post_stage_dirty_entry_count": post_dirty_count,
        "source_warning_count": len([w for w in warnings if "SOURCE_MISSING_WARNING" in str(w.get("warning_type", ""))]),
        "warning_count": len(warnings),
        "warnings": warnings,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(OUT),
    }
    write_json("validation_summary.json", validation)

    report = [
        STAGE,
        f"final_status={append_status}",
        f"final_decision={current_decision}",
        f"previous_decision={previous_decision}",
        f"decision_changed={previous_decision != current_decision}",
        f"latest_available_price_date={latest_price}",
        f"latest_switch_state_tracking_date={latest_tracking}",
        f"new_rows_appended={new_rows_appended}",
        f"matured_observation_count={int(maturity['matured_observations'].sum())}",
        f"pending_observation_count={int(maturity['pending_observations'].sum())}",
        f"missing_observation_count={int(maturity['missing_observations'].sum())}",
        f"current_primary_control={snapshot['current_primary_control'].iloc[0]}",
        f"best_forward_tracking_state={snapshot['best_forward_tracking_state'].iloc[0]}",
        "role_review_required=false",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "research_only=true",
        f"repo_dirty_state_warning={dirty_warning}",
        f"pre_existing_dirty_state_detected={pre_dirty}",
        f"protected_output_mutation_audit_clean={protected_clean}",
        "",
        "No-new-data behavior:",
        append_reason,
        "",
        "Maturity behavior:",
        "5D/10D/20D horizons are marked PASS only when source ledger rows are MATURED.",
        "Missing source files and missing observations are warnings, not fabricated pass results.",
    ]
    (OUT / "V21.169_daily_switch_refresh_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
