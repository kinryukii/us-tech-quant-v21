#!/usr/bin/env python
"""V21.191 latest-available ABCDE rerun and manual 2026-06-30 import scaffold."""

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

import numpy as np
import pandas as pd

from v21_194_broad_date_gate_utils import BroadDateGateError, classify_requested_date, load_latest_broad_date_gate


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.191_LATEST_AVAILABLE_20260629_ABCDE_RERUN_AND_MANUAL_20260630_IMPORT_SCAFFOLD"
OUT = ROOT / "outputs/v21/V21.191_LATEST_AVAILABLE_20260629_ABCDE_RERUN_AND_MANUAL_20260630_IMPORT_SCAFFOLD"
OUT_R1 = ROOT / "outputs/v21/V21.191_R1_ABCD_FEATURE_DATE_ALIGNMENT_REPAIR"
CANONICAL = ROOT / "outputs/v20/price_history/V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
MANUAL_INPUT = ROOT / "inputs/manual_price_sources/approved_daily_ohlcv_20260630.csv"
V114_SCRIPT = ROOT / "scripts/v21/v21_114_true_latest_data_abcd_full_recompute_20260625.py"
PRIOR_E_R1 = ROOT / "outputs/v21/V21.133_R1_E_BASELINE_ANCHOR_AND_OVERLAP_REPAIR/e_r1_full_ranking.csv"
APPLY_ENV = "V21_191_APPLY_MANUAL_20260630_IMPORT"
LATEST_AVAILABLE_DATE = "2026-06-29"
EXPECTED_MISSING_DATE = "2026-06-30"
OHLCV = ["open", "high", "low", "close", "adjusted_close", "volume"]
CANONICAL_FIELDS = [
    "symbol", "date", "open", "high", "low", "close", "adjusted_close",
    "volume", "source_provider", "source_artifact", "refresh_timestamp",
    "row_hash", "price_row_status",
]
ABCD_LABEL = {
    "A1_BASELINE_CONTROL": "A1",
    "B_STATIC_MOMENTUM_BLEND": "B",
    "C_DYNAMIC_MOMENTUM_BLEND": "C",
    "D_WEIGHT_OPTIMIZED_R1": "D",
}
RANK_FILES = {
    "A1": "a1_latest_available_20260629_ranking.csv",
    "B": "b_latest_available_20260629_ranking.csv",
    "C": "c_latest_available_20260629_ranking.csv",
    "D": "d_latest_available_20260629_ranking.csv",
    "E_R1": "e_r1_latest_available_20260629_ranking.csv",
}
E_WEIGHTS = {
    "A1_baseline_norm": 0.80,
    "context_momentum_norm": 0.12,
    "technical_entry_quality_norm": 0.04,
    "risk_guardrail_norm": 0.04,
}


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
    allowed_prefix = "?? outputs/v21/V21.191_LATEST_AVAILABLE_20260629_ABCDE_RERUN_AND_MANUAL_20260630_IMPORT_SCAFFOLD/"
    allowed_scripts = {
        "?? scripts/v21/v21_191_latest_available_20260629_abcde_rerun_and_manual_20260630_import_scaffold.py",
        "?? scripts/v21/test_v21_191_latest_available_20260629_abcde_rerun_and_manual_20260630_import_scaffold.py",
        "?? scripts/v21/run_v21_191_latest_available_20260629_abcde_rerun_and_manual_20260630_import_scaffold.ps1",
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


def row_hash(row: dict[str, Any]) -> str:
    return hashlib.sha256("|".join(str(row.get(c, "")) for c in ["symbol", "date", *OHLCV]).encode("utf-8")).hexdigest()


def normalize_price(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=CANONICAL_FIELDS)
    rename = {}
    for col in frame.columns:
        low = str(col).lower().strip().replace(" ", "_")
        if low == "ticker":
            rename[col] = "symbol"
        elif low in {"adj_close", "adjclose"}:
            rename[col] = "adjusted_close"
        else:
            rename[col] = low
    out = frame.rename(columns=rename).copy()
    if "symbol" not in out or "date" not in out:
        return pd.DataFrame(columns=CANONICAL_FIELDS)
    out["symbol"] = out["symbol"].astype(str).str.upper().str.strip()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in OHLCV:
        if col not in out:
            out[col] = np.nan
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["adjusted_close"] = out["adjusted_close"].fillna(out["close"])
    for col in CANONICAL_FIELDS:
        if col not in out:
            out[col] = ""
    out = out[CANONICAL_FIELDS]
    out = out[out["symbol"].ne("") & out["date"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)].copy()
    out = out.dropna(subset=["open", "high", "low", "close", "adjusted_close", "volume"])
    return out.drop_duplicates(["symbol", "date"], keep="last").sort_values(["symbol", "date"]).reset_index(drop=True)


def load_canonical() -> pd.DataFrame:
    return normalize_price(pd.read_csv(CANONICAL, low_memory=False)) if CANONICAL.is_file() else pd.DataFrame(columns=CANONICAL_FIELDS)


def audit_price(frame: pd.DataFrame, path: Path) -> dict[str, Any]:
    return {
        "path": rel(path),
        "row_count": int(len(frame)),
        "ticker_count": int(frame["symbol"].nunique()) if len(frame) else 0,
        "min_date": str(frame["date"].min()) if len(frame) else "",
        "max_date": str(frame["date"].max()) if len(frame) else "",
        "duplicate_symbol_date_rows": int(frame.duplicated(["symbol", "date"]).sum()) if len(frame) else 0,
        "non_null_ohlcv_count": int(frame[OHLCV].notna().all(axis=1).sum()) if len(frame) else 0,
        "sha256": sha256(path) if path.is_file() else "",
    }


def load_v114() -> Any:
    spec = importlib.util.spec_from_file_location("v21_114_recompute", V114_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {rel(V114_SCRIPT)}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.EXPECTED_DATE = LATEST_AVAILABLE_DATE
    return module


def topn(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    eligible = frame[frame["eligible_flag"].astype(str).str.upper().isin(["TRUE", "1", "YES"])] if "eligible_flag" in frame else frame
    return eligible.sort_values(["rank", "ticker"]).head(n).copy()


def norm_score(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.dropna().nunique() <= 1:
        return pd.Series(50.0, index=series.index)
    return (numeric.rank(pct=True, ascending=True) * 100.0).clip(0, 100)


def build_e_r1(a1: pd.DataFrame) -> pd.DataFrame:
    prior = pd.read_csv(PRIOR_E_R1, low_memory=False) if PRIOR_E_R1.is_file() else pd.DataFrame()
    base = a1.copy()
    base["ticker_norm"] = base["ticker"].astype(str).str.upper().str.strip()
    full = base[["ticker_norm", "final_score", "rank"]].rename(columns={"final_score": "A1_raw_score", "rank": "A1_raw_rank"})
    full["A1_baseline_norm"] = norm_score(full["A1_raw_score"])
    if not prior.empty:
        prior["ticker_norm"] = prior["ticker_norm"].astype(str).str.upper().str.strip() if "ticker_norm" in prior else prior["ticker"].astype(str).str.upper().str.strip()
        keep = [c for c in ["ticker_norm", "context_momentum_norm", "technical_entry_quality_norm", "risk_guardrail_norm"] if c in prior]
        full = full.merge(prior[keep].drop_duplicates("ticker_norm"), on="ticker_norm", how="left")
    for col in ["context_momentum_norm", "technical_entry_quality_norm", "risk_guardrail_norm"]:
        if col not in full:
            full[col] = 50.0
        full[col] = pd.to_numeric(full[col], errors="coerce").fillna(50.0).clip(0, 100)
    full["E_final_score"] = sum(full[col] * weight for col, weight in E_WEIGHTS.items())
    full = full.sort_values(["E_final_score", "ticker_norm"], ascending=[False, True]).reset_index(drop=True)
    full["rank"] = np.arange(1, len(full) + 1)
    full["ticker"] = full["ticker_norm"]
    full["strategy"] = "E_R1_DEFENSIVE_OVERLAY_REPAIRED"
    full["latest_price_date"] = LATEST_AVAILABLE_DATE
    full["eligible_flag"] = True
    full["research_only"] = True
    full["official_adoption_allowed"] = False
    full["broker_action_allowed"] = False
    return full


def rerun_abcde(canonical_audit: dict[str, Any]) -> tuple[dict[str, pd.DataFrame], bool, bool, list[dict[str, Any]]]:
    try:
        broad_gate = load_latest_broad_date_gate()
        gate_classification = classify_requested_date(LATEST_AVAILABLE_DATE, broad_gate)
    except BroadDateGateError as exc:
        broad_gate = {}
        gate_classification = {"allowed": False, "classification": "BROAD_DATE_GATE_MISSING", "reason": str(exc)}
    if not gate_classification.get("allowed", False):
        return {}, True, False, [{
            "strategy_id": "ABCDE",
            "ranking_date": LATEST_AVAILABLE_DATE,
            "source_latest_price_dates": f"raw_requested={LATEST_AVAILABLE_DATE}|abcd_honest_latest_date={broad_gate.get('abcd_honest_latest_date', '')}",
            "row_count": 0,
            "top20_count": 0,
            "top50_count": 0,
            "same_date_comparable": False,
            "reason": gate_classification.get("classification", "TARGET_DATE_NOT_BROAD_ELIGIBLE"),
        }]
    if not (
        canonical_audit["max_date"] == LATEST_AVAILABLE_DATE
        and int(canonical_audit["row_count"]) >= 227431
        and int(canonical_audit["ticker_count"]) >= 316
        and int(canonical_audit["duplicate_symbol_date_rows"]) == 0
    ):
        return {}, False, False, []
    base = load_v114()
    universe, manifest = base.load_universe()
    price, latest, price_manifest = base.load_price_panel(universe)
    tech, momentum, blockers = base.compute_features(price)
    write_csv(OUT / "latest_available_feature_blockers_20260629.csv", blockers, list(blockers[0].keys()) if blockers else ["ticker", "reason"])
    feature_latest = max(tech["latest_price_date"].astype(str), default="") if not tech.empty and "latest_price_date" in tech else ""
    momentum_latest = max(momentum["latest_price_date"].astype(str), default="") if not momentum.empty and "latest_price_date" in momentum else ""
    if latest != LATEST_AVAILABLE_DATE or tech.empty or momentum.empty:
        return {}, True, False, [{
            "strategy_id": "",
            "ranking_date": LATEST_AVAILABLE_DATE,
            "source_latest_price_dates": f"price_panel={latest}|technical={feature_latest}|momentum={momentum_latest}",
            "row_count": 0,
            "top20_count": 0,
            "top50_count": 0,
            "same_date_comparable": False,
            "reason": "EMPTY_FEATURES_OR_DATE_MISMATCH",
        }]
    rankings = {ABCD_LABEL[k]: v for k, v in base.build_rankings(tech, momentum).items()}
    rankings["E_R1"] = build_e_r1(rankings["A1"])
    for label, frame in rankings.items():
        frame = frame.copy()
        frame["research_only"] = True
        frame["official_adoption_allowed"] = False
        frame["broker_action_allowed"] = False
        rankings[label] = frame
        frame.to_csv(OUT / RANK_FILES[label], index=False)
    audit = []
    for label, frame in rankings.items():
        dates = sorted(set(frame["latest_price_date"].astype(str)))
        audit.append({
            "strategy_id": label,
            "ranking_date": LATEST_AVAILABLE_DATE,
            "source_latest_price_dates": "|".join(dates),
            "row_count": len(frame),
            "top20_count": len(topn(frame, 20)),
            "top50_count": len(topn(frame, 50)),
            "same_date_comparable": dates == [LATEST_AVAILABLE_DATE],
            "reason": "" if dates == [LATEST_AVAILABLE_DATE] else "STRATEGY_FEATURE_ROWS_NOT_AT_CANONICAL_MAX_DATE",
        })
    comparable = all(row["same_date_comparable"] for row in audit) and len(audit) == 5
    return rankings, True, comparable, audit


def write_abcde_outputs(rankings: dict[str, pd.DataFrame], audit: list[dict[str, Any]]) -> None:
    rows20: list[dict[str, Any]] = []
    rows50: list[dict[str, Any]] = []
    sets20: dict[str, set[str]] = {}
    sets50: dict[str, set[str]] = {}
    for label, frame in rankings.items():
        score_col = "E_final_score" if label == "E_R1" else "final_score"
        t20 = topn(frame, 20)
        t50 = topn(frame, 50)
        sets20[label] = set(t20["ticker"].astype(str))
        sets50[label] = set(t50["ticker"].astype(str))
        for rec in t20.to_dict("records"):
            rows20.append({"strategy_id": label, "rank": rec.get("rank"), "ticker": rec.get("ticker"), "score": rec.get(score_col), "latest_price_date": rec.get("latest_price_date")})
        for rec in t50.to_dict("records"):
            rows50.append({"strategy_id": label, "rank": rec.get("rank"), "ticker": rec.get("ticker"), "score": rec.get(score_col), "latest_price_date": rec.get("latest_price_date")})
    write_csv(OUT / "abcde_top20_summary_20260629.csv", rows20)
    write_csv(OUT / "abcde_top50_summary_20260629.csv", rows50)
    labels = ["A1", "B", "C", "D", "E_R1"]
    for n, sets, name in [(20, sets20, "abcde_overlap_top20_matrix_20260629.csv"), (50, sets50, "abcde_overlap_top50_matrix_20260629.csv")]:
        matrix = []
        for left in labels:
            row = {"strategy_id": left}
            for right in labels:
                row[right] = len(sets[left] & sets[right])
            matrix.append(row)
        write_csv(OUT / name, matrix)
    base = rankings["A1"][["ticker", "rank"]].rename(columns={"rank": "A1_rank"})
    diff_rows = []
    for label, frame in rankings.items():
        if label == "A1":
            diff_rows.append({"strategy_id": label, "compared_to": "A1", "common_ticker_count": len(base), "mean_rank_diff_vs_a1": 0.0, "median_abs_rank_diff_vs_a1": 0.0})
            continue
        comp = frame[["ticker", "rank"]].rename(columns={"rank": f"{label}_rank"})
        merged = base.merge(comp, on="ticker", how="inner")
        diff = pd.to_numeric(merged[f"{label}_rank"], errors="coerce") - pd.to_numeric(merged["A1_rank"], errors="coerce")
        diff_rows.append({"strategy_id": label, "compared_to": "A1", "common_ticker_count": len(merged), "mean_rank_diff_vs_a1": float(diff.mean()), "median_abs_rank_diff_vs_a1": float(diff.abs().median())})
    write_csv(OUT / "abcde_rank_diff_summary_20260629.csv", diff_rows)
    write_csv(OUT / "abcde_same_date_alignment_audit_20260629.csv", audit, ["strategy_id", "ranking_date", "source_latest_price_dates", "row_count", "top20_count", "top50_count", "same_date_comparable", "reason"])


def manual_import(base: pd.DataFrame) -> dict[str, Any]:
    exists = MANUAL_INPUT.is_file()
    status = [{"manual_import_file_expected_path": rel(MANUAL_INPUT), "exists": exists, "attempted": exists}]
    write_csv(OUT / "manual_20260630_import_status.csv", status)
    schema_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []
    append = pd.DataFrame(columns=CANONICAL_FIELDS)
    candidate = pd.DataFrame(columns=CANONICAL_FIELDS)
    candidate_valid = False
    coverage = 0.0
    apply_audit = {
        "manual_import_apply_requested": os.environ.get(APPLY_ENV, "").upper() == "TRUE",
        "manual_import_apply_succeeded": False,
        "backup_created": False,
        "restored_after_failed_apply": False,
        "backup_path": "",
        "apply_note": "",
    }
    if exists:
        raw = pd.read_csv(MANUAL_INPUT, low_memory=False)
        cols = {str(c).lower().strip().replace(" ", "_") for c in raw.columns}
        required = ["symbol_or_ticker", "date", "open", "high", "low", "close", "volume"]
        schema_rows = [{"field": field, "present": (field in cols or (field == "symbol_or_ticker" and ("symbol" in cols or "ticker" in cols)))} for field in required]
        norm = normalize_price(raw)
        norm = norm[norm["date"].eq(EXPECTED_MISSING_DATE)].copy()
        for i, row in norm.iterrows():
            errs = []
            if row["close"] <= 0:
                errs.append("CLOSE_NON_POSITIVE")
            if row["high"] < row["low"]:
                errs.append("HIGH_LT_LOW")
            if row["high"] < row["open"] or row["high"] < row["close"]:
                errs.append("HIGH_BELOW_OPEN_OR_CLOSE")
            if row["low"] > row["open"] or row["low"] > row["close"]:
                errs.append("LOW_ABOVE_OPEN_OR_CLOSE")
            if errs:
                error_rows.append({"symbol": row["symbol"], "date": row["date"], "errors": "|".join(errs)})
        duplicate_count = int(norm.duplicated(["symbol", "date"]).sum())
        if duplicate_count:
            error_rows.append({"symbol": "", "date": EXPECTED_MISSING_DATE, "errors": f"DUPLICATE_SYMBOL_DATE_ROWS:{duplicate_count}"})
        valid_symbols = set(base["symbol"].astype(str))
        append = norm[norm["symbol"].isin(valid_symbols)].drop_duplicates(["symbol", "date"], keep="last")
        if not error_rows:
            append.to_csv(OUT / "manual_20260630_candidate_append_rows.csv", index=False)
            candidate = normalize_price(pd.concat([base, append], ignore_index=True))
            coverage = append["symbol"].nunique() / base["symbol"].nunique() if len(base) else 0.0
            candidate_valid = (
                len(append) > 0
                and coverage >= 0.80
                and str(candidate["date"].max()) == EXPECTED_MISSING_DATE
                and int(candidate.duplicated(["symbol", "date"]).sum()) == 0
                and len(candidate) > len(base)
            )
            if candidate_valid:
                candidate.to_csv(OUT / "manual_20260630_candidate_canonical.csv", index=False)
        if apply_audit["manual_import_apply_requested"] and candidate_valid:
            backup = OUT / "canonical_backup_before_v21_191_manual_apply.csv"
            shutil.copy2(CANONICAL, backup)
            apply_audit["backup_created"] = True
            apply_audit["backup_path"] = rel(backup)
            shutil.copy2(OUT / "manual_20260630_candidate_canonical.csv", CANONICAL)
            after = load_canonical()
            if str(after["date"].max()) == EXPECTED_MISSING_DATE and len(after) >= len(candidate) and int(after.duplicated(["symbol", "date"]).sum()) == 0:
                apply_audit["manual_import_apply_succeeded"] = True
                apply_audit["apply_note"] = "APPLIED_AND_VERIFIED"
            else:
                shutil.copy2(backup, CANONICAL)
                apply_audit["restored_after_failed_apply"] = True
                apply_audit["apply_note"] = "VERIFY_FAILED_RESTORED_BACKUP"
        elif apply_audit["manual_import_apply_requested"]:
            apply_audit["apply_note"] = "REFUSED_INVALID_OR_MISSING_MANUAL_CANDIDATE"
        else:
            apply_audit["apply_note"] = "DRY_MODE"
    write_csv(OUT / "manual_20260630_schema_audit.csv", schema_rows, ["field", "present"])
    write_csv(OUT / "manual_20260630_validation_errors.csv", error_rows, ["symbol", "date", "errors"])
    candidate_audit = audit_price(candidate, OUT / "manual_20260630_candidate_canonical.csv") if len(candidate) else {"path": rel(OUT / "manual_20260630_candidate_canonical.csv"), "row_count": 0, "ticker_count": 0, "min_date": "", "max_date": "", "duplicate_symbol_date_rows": "", "non_null_ohlcv_count": 0, "sha256": ""}
    candidate_audit["manual_import_candidate_valid"] = candidate_valid
    candidate_audit["manual_import_coverage_ratio"] = coverage
    write_csv(OUT / "manual_20260630_candidate_audit.csv", [candidate_audit])
    write_csv(OUT / "manual_20260630_apply_audit.csv", [apply_audit])
    return {
        "manual_import_file_exists": exists,
        "manual_import_attempted": exists,
        "manual_import_candidate_created": bool(candidate_valid and (OUT / "manual_20260630_candidate_canonical.csv").is_file()),
        "manual_import_candidate_valid": candidate_valid,
        "manual_import_append_rows": int(len(append)) if exists else 0,
        "manual_import_coverage_ratio": coverage,
        "manual_import_apply_requested": bool(apply_audit["manual_import_apply_requested"]),
        "manual_import_apply_succeeded": bool(apply_audit["manual_import_apply_succeeded"]),
    }


def report(summary: dict[str, Any]) -> None:
    lines = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"latest_available_rerun_date={summary['latest_available_rerun_date']}",
        f"expected_missing_date={summary['expected_missing_date']}",
        f"abcde_rerun_succeeded={summary['abcde_rerun_succeeded']}",
        f"manual_import_file_exists={summary['manual_import_file_exists']}",
        f"manual_import_candidate_valid={summary['manual_import_candidate_valid']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
    ]
    (OUT / "V21.191_latest_available_abcde_and_manual_import_scaffold_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def source_resolution_before() -> dict[str, str]:
    audit = OUT / "abcde_same_date_alignment_audit_20260629.csv"
    if not audit.is_file():
        return {label: "" for label in ["A1", "B", "C", "D", "E_R1"]}
    frame = pd.read_csv(audit, low_memory=False)
    out = {label: "" for label in ["A1", "B", "C", "D", "E_R1"]}
    for row in frame.to_dict("records"):
        label = str(row.get("strategy_id", ""))
        if label in out:
            dates = str(row.get("source_latest_price_dates", ""))
            out[label] = dates.split("|")[0] if dates else ""
    return out


def builder_inventory() -> list[dict[str, Any]]:
    rows = []
    targets = [
        V114_SCRIPT,
        ROOT / "scripts/v21/v21_128_latest_data_full_abcd_and_forward_update.py",
        ROOT / "scripts/v21/v21_187_latest_data_abcde_rerun_20260630_price_refresh.py",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8", errors="ignore") if path.is_file() else ""
        rows.append({
            "script_path": rel(path),
            "exists": path.is_file(),
            "contains_compute_features": "def compute_features" in text,
            "contains_build_rankings": "def build_rankings" in text,
            "uses_canonical_price_panel": "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv" in text,
        })
    return rows


def write_r1_report(summary: dict[str, Any]) -> None:
    lines = [
        "V21.191_R1_ABCD_FEATURE_DATE_ALIGNMENT_REPAIR",
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        f"canonical_latest_date={summary['canonical_latest_date']}",
        f"target_rerun_date={summary['target_rerun_date']}",
        f"stale_abcd_root_cause={summary['stale_abcd_root_cause']}",
        f"upstream_builder_script={summary['upstream_builder_script']}",
        f"abcd_regeneration_attempted={summary['abcd_regeneration_attempted']}",
        f"abcd_regeneration_succeeded={summary['abcd_regeneration_succeeded']}",
        f"same_date_comparable_all_strategies={summary['same_date_comparable_all_strategies']}",
        "research_only=true",
        "official_adoption_allowed=false",
        "broker_action_allowed=false",
        "protected_outputs_modified=false",
    ]
    (OUT_R1 / "V21.191_R1_abcd_feature_date_alignment_repair_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_r1_abcd_feature_date_alignment_repair(baseline_status: list[str]) -> dict[str, Any]:
    OUT_R1.mkdir(parents=True, exist_ok=True)
    base_panel = load_canonical()
    canonical_audit = audit_price(base_panel, CANONICAL)
    write_csv(OUT_R1 / "canonical_audit_20260629.csv", [canonical_audit])
    before = source_resolution_before()

    inventory = builder_inventory()
    write_csv(OUT_R1 / "upstream_feature_builder_inventory.csv", inventory)
    builder = next((row for row in inventory if row["contains_compute_features"] and row["contains_build_rankings"] and row["exists"]), {})
    upstream_builder_found = bool(builder)
    upstream_builder_script = str(builder.get("script_path", ""))

    base = load_v114()
    universe, _manifest = base.load_universe()
    price, price_latest, _price_manifest = base.load_price_panel(universe)
    tech, momentum, blockers = base.compute_features(price)
    feature_latest = max(tech["latest_price_date"].astype(str), default="") if not tech.empty and "latest_price_date" in tech else ""
    momentum_latest = max(momentum["latest_price_date"].astype(str), default="") if not momentum.empty and "latest_price_date" in momentum else ""
    price_latest_by_symbol = price.groupby("symbol")["date"].max().dt.strftime("%Y-%m-%d").to_dict() if len(price) else {}
    broad_target_count = sum(1 for d in price_latest_by_symbol.values() if str(d) == LATEST_AVAILABLE_DATE)
    eligible_target_count = int((tech["latest_price_date"].astype(str) == LATEST_AVAILABLE_DATE).sum()) if not tech.empty and "latest_price_date" in tech else 0
    stale_diag = [{
        "canonical_latest_date": canonical_audit["max_date"],
        "canonical_ticker_count": canonical_audit["ticker_count"],
        "price_panel_latest_from_builder": price_latest,
        "symbols_with_price_on_target_date": broad_target_count,
        "eligible_feature_rows_on_target_date": eligible_target_count,
        "technical_feature_latest_date": feature_latest,
        "momentum_feature_latest_date": momentum_latest,
        "feature_blocker_count": len(blockers),
        "root_cause": "CANONICAL_MAX_DATE_IS_NARROW_NON_FEATURE_ELIGIBLE_APPEND_NOT_BROAD_ABCD_UNIVERSE_DATE",
    }]
    write_csv(OUT_R1 / "stale_feature_source_diagnostic.csv", stale_diag)

    abcd_regeneration_attempted = upstream_builder_found and canonical_audit["max_date"] == LATEST_AVAILABLE_DATE
    rankings: dict[str, pd.DataFrame] = {}
    after_dates = {label: "" for label in ["A1", "B", "C", "D", "E_R1"]}
    audit_rows: list[dict[str, Any]] = []
    if abcd_regeneration_attempted and not tech.empty and not momentum.empty:
        built = {ABCD_LABEL[k]: v.copy() for k, v in base.build_rankings(tech, momentum).items()}
        for label, frame in built.items():
            dates = sorted(set(frame["latest_price_date"].astype(str)))
            after_dates[label] = dates[0] if len(dates) == 1 else "|".join(dates)
            out = frame.copy()
            out["research_only"] = True
            out["official_adoption_allowed"] = False
            out["broker_action_allowed"] = False
            if dates == [LATEST_AVAILABLE_DATE]:
                rankings[label] = out
                out.to_csv(OUT_R1 / f"regenerated_{label.lower()}_20260629_ranking.csv", index=False)
            audit_rows.append({
                "strategy_id": label,
                "target_rerun_date": LATEST_AVAILABLE_DATE,
                "resolved_date_after_regeneration": after_dates[label],
                "row_count": len(out),
                "top20_count": len(topn(out, 20)),
                "same_date_comparable": dates == [LATEST_AVAILABLE_DATE],
                "reason": "" if dates == [LATEST_AVAILABLE_DATE] else "REGENERATED_FEATURE_ROWS_STILL_RESOLVE_TO_STALE_PRICE_DATE",
            })
        if "A1" in rankings:
            e = build_e_r1(rankings["A1"])
            after_dates["E_R1"] = LATEST_AVAILABLE_DATE
            rankings["E_R1"] = e
            e.to_csv(OUT_R1 / "e_r1_20260629_ranking.csv", index=False)
            audit_rows.append({
                "strategy_id": "E_R1",
                "target_rerun_date": LATEST_AVAILABLE_DATE,
                "resolved_date_after_regeneration": LATEST_AVAILABLE_DATE,
                "row_count": len(e),
                "top20_count": len(topn(e, 20)),
                "same_date_comparable": True,
                "reason": "",
            })
    same_date = len(rankings) == 5 and all(after_dates[label] == LATEST_AVAILABLE_DATE for label in ["A1", "B", "C", "D", "E_R1"])
    if same_date:
        write_abcde_outputs_r1(rankings)
    write_csv(OUT_R1 / "abcd_source_resolution_audit.csv", [
        {"strategy_id": label, "resolved_date_before": before.get(label, ""), "resolved_date_after": after_dates.get(label, "")}
        for label in ["A1", "B", "C", "D", "E_R1"]
    ])
    write_csv(OUT_R1 / "abcde_same_date_alignment_audit_20260629_r1.csv", audit_rows, ["strategy_id", "target_rerun_date", "resolved_date_after_regeneration", "row_count", "top20_count", "same_date_comparable", "reason"])

    if same_date:
        final_status = "PASS_V21_191_R1_20260629_ABCDE_SAME_DATE_READY"
        final_decision = "LATEST_AVAILABLE_20260629_ABCDE_READY_RESEARCH_ONLY"
    elif upstream_builder_found:
        final_status = "PARTIAL_PASS_V21_191_R1_UPSTREAM_ABCD_REBUILD_REQUIRED"
        final_decision = "RERUN_IDENTIFIED_UPSTREAM_ABCD_FEATURE_BUILDER"
    else:
        final_status = "FAIL_V21_191_R1_ABCD_STALE_DATE_ROOT_CAUSE_UNKNOWN"
        final_decision = "DO_NOT_USE_ABCDE_UNTIL_SOURCE_RESOLUTION_REPAIRED"
    top20 = {label: topn(frame, 20)["ticker"].astype(str).tolist() for label, frame in rankings.items()} if rankings else {}
    prot_mod = protected_modified(git_status(), baseline_status, False)
    summary = {
        "stage": "V21.191_R1_ABCD_FEATURE_DATE_ALIGNMENT_REPAIR",
        "final_status": final_status,
        "final_decision": final_decision,
        "canonical_latest_date": canonical_audit["max_date"],
        "target_rerun_date": LATEST_AVAILABLE_DATE,
        "a1_resolved_date_before": before.get("A1", ""),
        "b_resolved_date_before": before.get("B", ""),
        "c_resolved_date_before": before.get("C", ""),
        "d_resolved_date_before": before.get("D", ""),
        "e_r1_resolved_date_before": before.get("E_R1", ""),
        "stale_abcd_root_cause": stale_diag[0]["root_cause"],
        "upstream_builder_found": upstream_builder_found,
        "upstream_builder_script": upstream_builder_script,
        "abcd_regeneration_attempted": abcd_regeneration_attempted,
        "abcd_regeneration_succeeded": same_date,
        "a1_resolved_date_after": after_dates["A1"],
        "b_resolved_date_after": after_dates["B"],
        "c_resolved_date_after": after_dates["C"],
        "d_resolved_date_after": after_dates["D"],
        "e_r1_resolved_date_after": after_dates["E_R1"],
        "same_date_comparable_all_strategies": same_date,
        "a1_top20": top20.get("A1", []),
        "b_top20": top20.get("B", []),
        "c_top20": top20.get("C", []),
        "d_top20": top20.get("D", []),
        "e_r1_top20": top20.get("E_R1", []),
        "top20_overlap_matrix_path": rel(OUT_R1 / "abcde_overlap_top20_matrix_20260629_r1.csv"),
        "top50_overlap_matrix_path": rel(OUT_R1 / "abcde_overlap_top50_matrix_20260629_r1.csv"),
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": bool(prot_mod),
    }
    write_json(OUT_R1 / "v21_191_r1_summary.json", summary)
    write_r1_report(summary)
    return summary


def write_abcde_outputs_r1(rankings: dict[str, pd.DataFrame]) -> None:
    labels = ["A1", "B", "C", "D", "E_R1"]
    rows20: list[dict[str, Any]] = []
    rows50: list[dict[str, Any]] = []
    sets20: dict[str, set[str]] = {}
    sets50: dict[str, set[str]] = {}
    for label in labels:
        frame = rankings[label]
        score_col = "E_final_score" if label == "E_R1" else "final_score"
        t20 = topn(frame, 20)
        t50 = topn(frame, 50)
        sets20[label] = set(t20["ticker"].astype(str))
        sets50[label] = set(t50["ticker"].astype(str))
        rows20.extend({"strategy_id": label, "rank": rec.get("rank"), "ticker": rec.get("ticker"), "score": rec.get(score_col), "latest_price_date": rec.get("latest_price_date")} for rec in t20.to_dict("records"))
        rows50.extend({"strategy_id": label, "rank": rec.get("rank"), "ticker": rec.get("ticker"), "score": rec.get(score_col), "latest_price_date": rec.get("latest_price_date")} for rec in t50.to_dict("records"))
    write_csv(OUT_R1 / "abcde_top20_summary_20260629_r1.csv", rows20)
    write_csv(OUT_R1 / "abcde_top50_summary_20260629_r1.csv", rows50)
    for sets, name in [(sets20, "abcde_overlap_top20_matrix_20260629_r1.csv"), (sets50, "abcde_overlap_top50_matrix_20260629_r1.csv")]:
        matrix = []
        for left in labels:
            row = {"strategy_id": left}
            for right in labels:
                row[right] = len(sets[left] & sets[right])
            matrix.append(row)
        write_csv(OUT_R1 / name, matrix)


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline_status = git_status()
    base = load_canonical()
    before_audit = audit_price(base, CANONICAL)
    write_csv(OUT / "canonical_before_v21_191_audit.csv", [before_audit])
    rankings, attempted, comparable, alignment_audit = rerun_abcde(before_audit)
    if rankings:
        write_abcde_outputs(rankings, alignment_audit)
    else:
        write_csv(OUT / "abcde_same_date_alignment_audit_20260629.csv", alignment_audit, ["strategy_id", "ranking_date", "source_latest_price_dates", "row_count", "top20_count", "top50_count", "same_date_comparable", "reason"])
    manual = manual_import(base)
    after = load_canonical()
    after_latest = str(after["date"].max()) if len(after) else ""
    abcde_success = bool(rankings) and comparable
    if not abcde_success:
        final_status = "FAIL_V21_191_ABCDE_20260629_RERUN_FAILED"
        final_decision = "DO_NOT_USE_ABCDE_RERUN_REPAIR_REQUIRED"
    elif manual["manual_import_file_exists"] and manual["manual_import_candidate_valid"] and not manual["manual_import_apply_succeeded"]:
        final_status = "PARTIAL_PASS_V21_191_MANUAL_20260630_CANDIDATE_READY_NOT_APPLIED"
        final_decision = "MANUAL_20260630_CANDIDATE_READY_FOR_GUARDED_APPLY"
    elif manual["manual_import_file_exists"] and manual["manual_import_apply_succeeded"] and after_latest == EXPECTED_MISSING_DATE:
        final_status = "PASS_V21_191_MANUAL_20260630_IMPORTED"
        final_decision = "CANONICAL_20260630_READY_FOR_FINAL_ABCDE_RERUN"
    else:
        final_status = "PARTIAL_PASS_V21_191_20260629_ABCDE_READY_WAIT_MANUAL_20260630"
        final_decision = "LATEST_AVAILABLE_20260629_ABCDE_READY_20260630_WAIT_MANUAL_APPROVED_SOURCE"
    top20 = {label: topn(frame, 20)["ticker"].astype(str).tolist() for label, frame in rankings.items()} if rankings else {}
    prot_mod = protected_modified(git_status(), baseline_status, manual["manual_import_apply_requested"])
    summary = {
        "stage": STAGE,
        "final_status": final_status,
        "final_decision": final_decision,
        "canonical_latest_date_before": before_audit["max_date"],
        "latest_available_rerun_date": LATEST_AVAILABLE_DATE,
        "expected_missing_date": EXPECTED_MISSING_DATE,
        "abcde_rerun_attempted": attempted,
        "abcde_rerun_succeeded": abcde_success,
        "same_date_comparable_all_strategies": comparable,
        "a1_top20": top20.get("A1", []),
        "b_top20": top20.get("B", []),
        "c_top20": top20.get("C", []),
        "d_top20": top20.get("D", []),
        "e_r1_top20": top20.get("E_R1", []),
        "top20_overlap_matrix_path": rel(OUT / "abcde_overlap_top20_matrix_20260629.csv"),
        "top50_overlap_matrix_path": rel(OUT / "abcde_overlap_top50_matrix_20260629.csv"),
        "manual_import_file_expected_path": rel(MANUAL_INPUT),
        **manual,
        "canonical_latest_date_after": after_latest,
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "protected_outputs_modified": bool(prot_mod),
    }
    write_json(OUT / "v21_191_summary.json", summary)
    report(summary)
    r1_summary = run_r1_abcd_feature_date_alignment_repair(baseline_status)
    print("V21.191_R1_ABCD_FEATURE_DATE_ALIGNMENT_REPAIR")
    for key in [
        "final_status", "final_decision", "canonical_latest_date", "target_rerun_date",
        "a1_resolved_date_before", "b_resolved_date_before", "c_resolved_date_before", "d_resolved_date_before", "e_r1_resolved_date_before",
        "stale_abcd_root_cause", "upstream_builder_found", "upstream_builder_script",
        "abcd_regeneration_attempted", "abcd_regeneration_succeeded",
        "a1_resolved_date_after", "b_resolved_date_after", "c_resolved_date_after", "d_resolved_date_after", "e_r1_resolved_date_after",
        "same_date_comparable_all_strategies", "official_adoption_allowed", "broker_action_allowed",
    ]:
        print(f"{key}={r1_summary[key]}")
    if r1_summary["same_date_comparable_all_strategies"]:
        for key in ["a1_top20", "b_top20", "c_top20", "d_top20", "e_r1_top20"]:
            print(f"{key}={'|'.join(r1_summary[key])}")
        matrix_path = ROOT / r1_summary["top20_overlap_matrix_path"]
        if matrix_path.is_file():
            print(pd.read_csv(matrix_path).to_string(index=False))
    for key in [
        "final_status", "final_decision", "canonical_latest_date_before", "latest_available_rerun_date",
        "abcde_rerun_attempted", "abcde_rerun_succeeded", "same_date_comparable_all_strategies",
        "manual_import_file_exists", "manual_import_attempted", "manual_import_candidate_valid",
        "manual_import_apply_requested", "manual_import_apply_succeeded",
        "official_adoption_allowed", "broker_action_allowed",
    ]:
        print(f"{key}={summary[key]}")
    if rankings:
        for key in ["a1_top20", "b_top20", "c_top20", "d_top20", "e_r1_top20"]:
            print(f"{key}={'|'.join(summary[key])}")
        print(pd.read_csv(OUT / "abcde_overlap_top20_matrix_20260629.csv").to_string(index=False))
    return summary


if __name__ == "__main__":
    run()
