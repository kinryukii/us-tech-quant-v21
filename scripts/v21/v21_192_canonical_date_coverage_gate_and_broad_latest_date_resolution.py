#!/usr/bin/env python
"""V21.192 canonical date coverage gate and broad latest date resolution."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.192_CANONICAL_DATE_COVERAGE_GATE_AND_BROAD_LATEST_DATE_RESOLUTION"
OUT = ROOT / "outputs/v21/V21.192_CANONICAL_DATE_COVERAGE_GATE_AND_BROAD_LATEST_DATE_RESOLUTION"
CANONICAL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
V114_SCRIPT = ROOT / "scripts/v21/v21_114_true_latest_data_abcd_full_recompute_20260625.py"
APPLY_ENV = "V21_192_APPLY_NARROW_TAIL_QUARANTINE"
OHLCV = ["open", "high", "low", "close", "adjusted_close", "volume"]
CANONICAL_FIELDS = [
    "symbol", "date", "open", "high", "low", "close", "adjusted_close",
    "volume", "source_provider", "source_artifact", "refresh_timestamp",
    "row_hash", "price_row_status",
]


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    if fields is None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
        fields = fields or ["empty"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_status() -> list[str]:
    completed = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, check=False)
    return completed.stdout.splitlines()


def protected_modified(status_lines: list[str], baseline_lines: list[str], apply_requested: bool) -> bool:
    if apply_requested:
        return False
    baseline = {line.replace("\\", "/") for line in baseline_lines}
    allowed_prefix = "?? outputs/v21/V21.192_CANONICAL_DATE_COVERAGE_GATE_AND_BROAD_LATEST_DATE_RESOLUTION/"
    allowed_scripts = {
        "?? scripts/v21/v21_192_canonical_date_coverage_gate_and_broad_latest_date_resolution.py",
        "?? scripts/v21/test_v21_192_canonical_date_coverage_gate_and_broad_latest_date_resolution.py",
        "?? scripts/v21/run_v21_192_canonical_date_coverage_gate_and_broad_latest_date_resolution.ps1",
    }
    for line in status_lines:
        normalized = line.replace("\\", "/")
        if normalized in baseline or normalized.startswith(allowed_prefix) or normalized in allowed_scripts:
            continue
        lowered = normalized.lower()
        if lowered.startswith((" m outputs/", " d outputs/", "?? outputs/")) and (
            "official" in lowered or "broker" in lowered or "protected" in lowered or "weight" in lowered
        ):
            return True
    return False


def load_canonical() -> pd.DataFrame:
    frame = pd.read_csv(CANONICAL, low_memory=False)
    rename = {}
    for col in frame.columns:
        low = str(col).lower().strip().replace(" ", "_")
        if low == "ticker":
            rename[col] = "symbol"
        elif low in {"adj_close", "adjclose"}:
            rename[col] = "adjusted_close"
        else:
            rename[col] = low
    frame = frame.rename(columns=rename)
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in OHLCV:
        if col not in frame:
            frame[col] = pd.NA
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["adjusted_close"] = frame["adjusted_close"].fillna(frame["close"])
    for col in CANONICAL_FIELDS:
        if col not in frame:
            frame[col] = ""
    return frame[CANONICAL_FIELDS].dropna(subset=["symbol", "date"]).sort_values(["symbol", "date"]).reset_index(drop=True)


def date_coverage(frame: pd.DataFrame) -> list[dict[str, Any]]:
    universe_count = int(frame["symbol"].nunique())
    counts = frame.groupby("date")["symbol"].nunique().sort_index()
    broad_symbols_by_date = {
        date: set(frame.loc[frame["date"].eq(date), "symbol"].astype(str))
        for date in sorted(frame["date"].dropna().astype(str).unique())
    }
    previous_broad_symbols: set[str] = set()
    rows = []
    for date, group in frame.groupby("date", sort=True):
        distinct = int(group["symbol"].nunique())
        duplicate_count = int(group.duplicated(["symbol", "date"]).sum())
        zero_close = int((pd.to_numeric(group["close"], errors="coerce") <= 0).sum())
        all_null_ohlcv = int(group[OHLCV].isna().all(axis=1).sum())
        coverage = distinct / universe_count if universe_count else 0.0
        coverage_prev = distinct / len(previous_broad_symbols) if previous_broad_symbols else coverage
        broad = (
            distinct >= 300
            and coverage >= 0.80
            and duplicate_count == 0
            and zero_close == 0
            and all_null_ohlcv == 0
        )
        rows.append({
            "date": date,
            "price_row_count": int(len(group)),
            "distinct_symbol_count": distinct,
            "coverage_ratio_vs_canonical_universe": coverage,
            "coverage_ratio_vs_previous_broad_date_universe": coverage_prev,
            "has_duplicate_symbol_date": duplicate_count > 0,
            "duplicate_symbol_date_count": duplicate_count,
            "zero_or_negative_close_count": zero_close,
            "null_ohlcv_count": int(group[OHLCV].isna().any(axis=1).sum()),
            "all_null_ohlcv_count": all_null_ohlcv,
            "broad_price_date_eligible": broad,
        })
        if broad:
            previous_broad_symbols = broad_symbols_by_date[str(date)]
    return rows


def load_v114() -> Any:
    spec = importlib.util.spec_from_file_location("v21_114_recompute", V114_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {rel(V114_SCRIPT)}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def feature_latest_dates() -> dict[str, Any]:
    base = load_v114()
    universe, _manifest = base.load_universe()
    price, price_latest, _price_manifest = base.load_price_panel(universe)
    tech, momentum, blockers = base.compute_features(price)
    technical = max(tech["latest_price_date"].astype(str), default="") if not tech.empty and "latest_price_date" in tech else ""
    momentum_latest = max(momentum["latest_price_date"].astype(str), default="") if not momentum.empty and "latest_price_date" in momentum else ""
    return {
        "price_panel_latest_from_builder": price_latest,
        "feature_latest_date_technical": technical,
        "feature_latest_date_momentum": momentum_latest,
        "technical_feature_row_count": int(len(tech)),
        "momentum_feature_row_count": int(len(momentum)),
        "feature_blocker_count": int(len(blockers)),
    }


def apply_quarantine(candidate_path: Path, broad_latest: str) -> dict[str, Any]:
    requested = os.environ.get(APPLY_ENV, "").upper() == "TRUE"
    audit = {
        "quarantine_apply_requested": requested,
        "quarantine_apply_succeeded": False,
        "backup_created": False,
        "restored_after_failed_apply": False,
        "backup_path": "",
        "apply_note": "",
    }
    if not requested:
        audit["apply_note"] = f"Dry mode. Set {APPLY_ENV}=TRUE to quarantine narrow tail."
        return audit
    if not candidate_path.is_file() or broad_latest == "":
        audit["apply_note"] = "REFUSED_MISSING_CANDIDATE_OR_BROAD_DATE"
        return audit
    backup = OUT / "canonical_backup_before_v21_192_narrow_tail_quarantine.csv"
    shutil.copy2(CANONICAL, backup)
    audit["backup_created"] = True
    audit["backup_path"] = rel(backup)
    shutil.copy2(candidate_path, CANONICAL)
    after = load_canonical()
    ok = str(after["date"].max()) == broad_latest and int(after.duplicated(["symbol", "date"]).sum()) == 0 and len(after) > 0
    if ok:
        audit["quarantine_apply_succeeded"] = True
        audit["apply_note"] = "APPLIED_AND_VERIFIED"
    else:
        shutil.copy2(backup, CANONICAL)
        audit["restored_after_failed_apply"] = True
        audit["apply_note"] = "VERIFY_FAILED_RESTORED_BACKUP"
    return audit


def report(summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"raw_canonical_max_date={summary['raw_canonical_max_date']}",
        f"raw_canonical_max_date_symbol_count={summary['raw_canonical_max_date_symbol_count']}",
        f"broad_price_latest_date={summary['broad_price_latest_date']}",
        f"abcd_honest_latest_date={summary['abcd_honest_latest_date']}",
        f"narrow_tail_detected={summary['narrow_tail_detected']}",
        "Future ABCDE reruns must read latest_broad_date_gate.json and refuse target dates newer than abcd_honest_latest_date.",
        "2026-06-29 is labeled NARROW_NON_FEATURE_ELIGIBLE_APPEND unless broad rows are imported.",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
    ]
    (OUT / "V21.192_canonical_date_coverage_gate_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_status = git_status()
    frame = load_canonical()
    coverage_rows = date_coverage(frame)
    write_csv(OUT / "canonical_date_coverage_audit.csv", coverage_rows)
    coverage_df = pd.DataFrame(coverage_rows)
    raw_max = str(frame["date"].max()) if len(frame) else ""
    raw_row = coverage_df[coverage_df["date"].eq(raw_max)].iloc[0].to_dict() if raw_max else {}
    broad_dates = coverage_df.loc[coverage_df["broad_price_date_eligible"].astype(bool), "date"].astype(str).tolist() if not coverage_df.empty else []
    broad_latest = max(broad_dates) if broad_dates else ""
    feature = feature_latest_dates()
    feature_rows = [{
        "feature_name": "technical",
        "latest_date": feature["feature_latest_date_technical"],
        "row_count": feature["technical_feature_row_count"],
        "price_panel_latest_from_builder": feature["price_panel_latest_from_builder"],
        "feature_blocker_count": feature["feature_blocker_count"],
    }, {
        "feature_name": "momentum",
        "latest_date": feature["feature_latest_date_momentum"],
        "row_count": feature["momentum_feature_row_count"],
        "price_panel_latest_from_builder": feature["price_panel_latest_from_builder"],
        "feature_blocker_count": feature["feature_blocker_count"],
    }]
    write_csv(OUT / "feature_latest_date_audit.csv", feature_rows)
    candidates = [d for d in [broad_latest, feature["feature_latest_date_technical"], feature["feature_latest_date_momentum"]] if d]
    abcd_honest = min(candidates) if candidates else ""

    narrow_tail = frame[frame["date"].astype(str) > broad_latest].copy() if broad_latest else frame.iloc[0:0].copy()
    narrow_tail_path = OUT / "narrow_tail_rows_after_broad_latest_date.csv"
    narrow_tail.to_csv(narrow_tail_path, index=False)
    candidate = frame[frame["date"].astype(str) <= broad_latest].copy() if broad_latest else frame.iloc[0:0].copy()
    candidate_path = OUT / "canonical_without_narrow_tail_candidate.csv"
    candidate.to_csv(candidate_path, index=False)
    apply_audit = apply_quarantine(candidate_path, broad_latest)
    write_csv(OUT / "narrow_tail_quarantine_apply_audit.csv", [apply_audit])
    after = load_canonical()
    after_latest = str(after["date"].max()) if len(after) else ""

    gate = {
        "stage": STAGE,
        "raw_canonical_max_date": raw_max,
        "raw_canonical_max_date_symbol_count": int(raw_row.get("distinct_symbol_count", 0) or 0),
        "raw_canonical_max_date_broad_eligible": bool(raw_row.get("broad_price_date_eligible", False)),
        "broad_price_latest_date": broad_latest,
        "feature_latest_date_technical": feature["feature_latest_date_technical"],
        "feature_latest_date_momentum": feature["feature_latest_date_momentum"],
        "abcd_honest_latest_date": abcd_honest,
        "narrow_tail_dates_must_not_be_used_for_abcde": sorted(set(narrow_tail["date"].astype(str))) if len(narrow_tail) else [],
        "integration_note": "Future ABCDE reruns must refuse target dates newer than abcd_honest_latest_date; 2026-06-29 is NARROW_NON_FEATURE_ELIGIBLE_APPEND unless broad rows are imported.",
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
    }
    gate_path = OUT / "latest_broad_date_gate.json"
    write_json(gate_path, gate)

    narrow_tail_detected = raw_max > broad_latest if raw_max and broad_latest else False
    if apply_audit["quarantine_apply_succeeded"]:
        final_status = "PASS_V21_192_NARROW_TAIL_QUARANTINED"
        final_decision = "CANONICAL_TRIMMED_TO_BROAD_LATEST_DATE_RESEARCH_ONLY"
    elif narrow_tail_detected:
        final_status = "PARTIAL_PASS_V21_192_NARROW_TAIL_DETECTED_BROAD_DATE_RESOLVED"
        final_decision = "USE_BROAD_FEATURE_ELIGIBLE_DATE_FOR_ABCDE"
    elif raw_max == broad_latest and broad_latest == feature["feature_latest_date_technical"] == feature["feature_latest_date_momentum"]:
        final_status = "PASS_V21_192_CANONICAL_BROAD_DATE_READY"
        final_decision = "CANONICAL_BROAD_DATE_READY_FOR_ABCDE"
    else:
        final_status = "PARTIAL_PASS_V21_192_BROAD_DATE_RESOLVED_FEATURE_DATE_LAGS"
        final_decision = "USE_ABCD_HONEST_LATEST_DATE_FOR_ABCDE"

    prot_mod = protected_modified(git_status(), baseline_status, bool(apply_audit["quarantine_apply_requested"]))
    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "final_decision": final_decision,
        "raw_canonical_max_date": raw_max,
        "raw_canonical_max_date_symbol_count": int(raw_row.get("distinct_symbol_count", 0) or 0),
        "raw_canonical_max_date_broad_eligible": bool(raw_row.get("broad_price_date_eligible", False)),
        "broad_price_latest_date": broad_latest,
        "feature_latest_date_technical": feature["feature_latest_date_technical"],
        "feature_latest_date_momentum": feature["feature_latest_date_momentum"],
        "abcd_honest_latest_date": abcd_honest,
        "narrow_tail_detected": narrow_tail_detected,
        "narrow_tail_row_count": int(len(narrow_tail)),
        "narrow_tail_max_date": str(narrow_tail["date"].max()) if len(narrow_tail) else "",
        "latest_broad_date_gate_path": rel(gate_path),
        "quarantine_candidate_created": candidate_path.is_file() and len(candidate) > 0,
        "quarantine_apply_requested": bool(apply_audit["quarantine_apply_requested"]),
        "quarantine_apply_succeeded": bool(apply_audit["quarantine_apply_succeeded"]),
        "canonical_latest_date_after": after_latest,
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": bool(prot_mod),
    }
    write_json(OUT / "v21_192_summary.json", summary)
    report(summary)
    for key in [
        "final_status", "final_decision", "raw_canonical_max_date", "raw_canonical_max_date_symbol_count",
        "raw_canonical_max_date_broad_eligible", "broad_price_latest_date", "feature_latest_date_technical",
        "feature_latest_date_momentum", "abcd_honest_latest_date", "narrow_tail_detected",
        "narrow_tail_row_count", "quarantine_candidate_created", "quarantine_apply_requested",
        "quarantine_apply_succeeded", "latest_broad_date_gate_path", "official_adoption_allowed",
        "broker_action_allowed",
    ]:
        print(f"{key}={summary[key]}")
    return summary


if __name__ == "__main__":
    run()
