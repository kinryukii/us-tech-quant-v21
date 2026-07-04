#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

STAGE = "V21.244_FACTOR_EFFECTIVENESS_COVERAGE_AND_GRANULARITY_REPAIR_R1"
OUT_REL = Path("outputs/v21") / STAGE
V243_REL = Path("outputs/v21/V21.243_FACTOR_EFFECTIVENESS_CONTINUATION_R1")
HORIZONS = ["1D", "5D", "10D", "20D"]
TECH_TERMS = ["RSI", "KDJ", "K", "D", "J", "MACD", "DIF", "DEA", "Bollinger Bands", "BB", "MA20", "MA50", "EMA", "volume", "volume_ma", "volatility", "momentum", "relative_strength", "breakout", "pullback"]
FACTOR_ALIASES = {
    "Bollinger Bands": ["bollinger", "bb"],
    "volume trend": ["volume", "volume_ma", "vol_ma"],
    "relative strength": ["relative_strength", "rel_strength", "relative strength"],
    "Market Regime": ["market_regime", "regime"],
    "Data Trust": ["data_trust", "quality", "coverage", "stale"],
}


def read_rows(path: Path, limit: int | None = None) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for i, row in enumerate(reader):
            if limit is not None and i >= limit:
                break
            rows.append(row)
        return rows


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def count_csv_rows(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8-sig", errors="ignore") as f:
            return max(0, sum(1 for _ in f) - 1)
    except Exception:
        return 0


def header(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="", errors="ignore") as f:
            return next(csv.reader(f), [])
    except Exception:
        return []


def norm(s: Any) -> str:
    return str(s or "").strip().lower()


def rel(repo: Path, path: Path) -> str:
    try:
        return str(path.relative_to(repo)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def detect_col(cols: list[str], names: list[str]) -> str:
    lower = {norm(c): c for c in cols}
    for n in names:
        if n in lower:
            return lower[n]
    for c in cols:
        lc = norm(c)
        if any(n in lc for n in names):
            return c
    return ""


def factor_tokens(factor: str) -> list[str]:
    base = [norm(factor), norm(factor).replace(" ", "_")]
    base.extend(FACTOR_ALIASES.get(factor, []))
    if factor in {"Fundamental", "Technical", "Strategy", "Risk"}:
        base.extend([norm(factor) + "_score", norm(factor) + "_weight"])
    return [b for b in dict.fromkeys(base) if b]


def matching_value_cols(cols: list[str], factor: str) -> list[str]:
    tokens = factor_tokens(factor)
    hits = [c for c in cols if any(t in norm(c) for t in tokens)]
    if not hits and factor in {"Fundamental", "Technical", "Strategy", "Risk", "Market Regime", "Data Trust"}:
        hits = [c for c in cols if norm(c) in {"score", "rank", "factor_value", "factor_z", "beta_standardized", "weight"}]
    return hits[:12]


def sample_profile(path: Path, cols: list[str]) -> dict[str, Any]:
    date_col = detect_col(cols, ["ranking_date", "asof_date", "date", "price_date", "target_price_date"])
    ticker_col = detect_col(cols, ["ticker", "symbol", "code"])
    horizon_col = detect_col(cols, ["forward_window", "horizon", "window"])
    maturity_col = detect_col(cols, ["maturity_status"])
    pit_col = detect_col(cols, ["pit_status", "source_mode"])
    rows = read_rows(path, 20000)
    dates = {r.get(date_col, "") for r in rows if date_col and r.get(date_col)}
    tickers = {r.get(ticker_col, "") for r in rows if ticker_col and r.get(ticker_col)}
    horizons = {r.get(horizon_col, "") for r in rows if horizon_col and r.get(horizon_col)}
    statuses = {r.get(maturity_col, "") for r in rows if maturity_col and r.get(maturity_col)}
    pit_vals = {r.get(pit_col, "") for r in rows if pit_col and r.get(pit_col)}
    return {
        "date_col": date_col,
        "ticker_col": ticker_col,
        "horizon_col": horizon_col,
        "maturity_col": maturity_col,
        "pit_col": pit_col,
        "date_count": len(dates),
        "ticker_count": len(tickers),
        "horizons": sorted(h for h in horizons if h),
        "maturity_statuses": sorted(s for s in statuses if s),
        "pit_values": sorted(v for v in pit_vals if v),
        "dates": dates,
        "tickers": tickers,
        "rows": rows,
    }


def discover_artifacts(repo: Path) -> list[dict[str, Any]]:
    out = repo / "outputs/v21"
    artifacts: list[dict[str, Any]] = []
    keywords = ["factor", "subfactor", "technical", "feature", "ranking", "forward", "ledger", "score", "maturity", "snapshot", "coefficient", "attribution", "replay"]
    for path in out.rglob("*.csv") if out.exists() else []:
        if STAGE in str(path):
            continue
        try:
            cols = header(path)
        except PermissionError:
            continue
        if not cols:
            continue
        blob = " ".join([path.name, *cols]).lower()
        if not any(k in blob for k in keywords):
            continue
        row_count = count_csv_rows(path)
        prof = sample_profile(path, cols)
        artifacts.append({
            "path": path,
            "rel": rel(repo, path),
            "cols": cols,
            "row_count": row_count,
            "column_count": len(cols),
            **prof,
        })
    return artifacts


def usability_for(artifact: dict[str, Any], factor: str) -> tuple[str, list[str], bool, bool, str]:
    cols = artifact["cols"]
    value_cols = matching_value_cols(cols, factor)
    has_date = bool(artifact["date_col"])
    has_ticker = bool(artifact["ticker_col"])
    historical = has_date and artifact["date_count"] > 1
    current_only = has_date and artifact["date_count"] <= 1 and artifact["row_count"] > 0
    pit_vals = "|".join(artifact["pit_values"])
    if "RETROSPECTIVE_PIT_LITE_REPLAY" in pit_vals:
        pit = "PIT_LITE_ONLY"
    elif artifact["pit_col"] or "live" in norm(artifact["rel"]) or "pit" in norm(artifact["rel"]):
        pit = "PIT_METADATA_PRESENT"
    else:
        pit = "PIT_METADATA_MISSING"
    if not value_cols:
        usability = "NO_FACTOR_VALUE_COLUMN"
    elif not has_date:
        usability = "MISSING_DATE_COLUMN"
    elif not has_ticker:
        usability = "MISSING_TICKER_COLUMN"
    elif historical:
        usability = "HISTORICAL_PANEL_CANDIDATE"
    elif current_only:
        usability = "CURRENT_SNAPSHOT_ONLY"
    else:
        usability = "AGGREGATED_OR_UNUSABLE"
    return usability, value_cols, historical, current_only, pit


def load_v243(repo: Path) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    root = repo / V243_REL
    return (
        read_json(root / "v21_243_summary.json"),
        read_rows(root / "factor_inventory.csv"),
        read_rows(root / "factor_effectiveness_detail.csv"),
        read_rows(root / "subfactor_effectiveness_detail.csv"),
    )


def forward_sources(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for a in artifacts:
        cols = [norm(c) for c in a["cols"]]
        if "forward_return" in cols or ("forward_window" in cols and a["maturity_col"]):
            out.append(a)
    return sorted(out, key=lambda a: a["row_count"], reverse=True)[:8]


def key_rows(artifact: dict[str, Any]) -> tuple[set[str], set[str], set[tuple[str, str]], dict[str, int]]:
    dcol, tcol, hcol = artifact["date_col"], artifact["ticker_col"], artifact["horizon_col"]
    dates, tickers, keys = set(), set(), set()
    horizons = defaultdict(int)
    for r in artifact["rows"]:
        d = r.get(dcol, "") if dcol else ""
        t = r.get(tcol, "") if tcol else ""
        h = r.get(hcol, "") if hcol else ""
        if d:
            dates.add(d)
        if t:
            tickers.add(t)
        if d and t:
            keys.add((d, t))
        if h in HORIZONS:
            horizons[h] += 1
    return dates, tickers, keys, dict(horizons)


def primary_join_blocker(fa: dict[str, Any], fw: dict[str, Any], common_dates: set[str], common_tickers: set[str], joined: int) -> str:
    if not fa["date_col"]:
        return "missing_date_column"
    if not fa["ticker_col"]:
        return "missing_ticker_column"
    if not common_dates:
        return "insufficient_date_overlap"
    if not common_tickers:
        return "insufficient_ticker_overlap"
    if joined == 0:
        return "join_key_mismatch"
    if not set(fw["horizons"]) & set(HORIZONS):
        return "insufficient_horizon_availability"
    return "join_available"


def build_join_diagnostics(source_map: list[dict[str, Any]], artifacts_by_rel: dict[str, dict[str, Any]], fwd: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for m in source_map:
        fa = artifacts_by_rel.get(m["candidate_source_path"])
        if not fa:
            continue
        f_dates, f_tickers, f_keys, _ = key_rows(fa)
        for fw in fwd:
            w_dates, w_tickers, w_keys, w_horizons = key_rows(fw)
            common_dates = f_dates & w_dates
            common_tickers = f_tickers & w_tickers
            joined_keys = f_keys & w_keys
            ratio = len(joined_keys) / max(1, min(len(f_keys), len(w_keys)))
            rows.append({
                "factor_name": m["factor_name"],
                "candidate_source_path": m["candidate_source_path"],
                "forward_return_source_path": fw["rel"],
                "factor_row_count": fa["row_count"],
                "forward_return_row_count": fw["row_count"],
                "common_date_count": len(common_dates),
                "common_ticker_count": len(common_tickers),
                "joined_row_count": len(joined_keys),
                "join_success_ratio": ratio,
                "earliest_common_date": min(common_dates) if common_dates else "",
                "latest_common_date": max(common_dates) if common_dates else "",
                "available_horizons": "|".join(sorted(w_horizons)),
                "primary_join_blocker": primary_join_blocker(fa, fw, common_dates, common_tickers, len(joined_keys)),
            })
    return rows


def bool_s(v: bool) -> str:
    return "TRUE" if v else "FALSE"


def failure_rows(factors: list[dict[str, str]], source_map: list[dict[str, Any]], joins: list[dict[str, Any]], detail: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_factor_map = defaultdict(list)
    by_factor_join = defaultdict(list)
    by_factor_detail = defaultdict(list)
    for r in source_map:
        by_factor_map[r["factor_name"]].append(r)
    for r in joins:
        by_factor_join[r["factor_name"]].append(r)
    for r in detail:
        by_factor_detail[r["factor_name"]].append(r)
    rows = []
    for f in factors:
        name = f["factor_name"]
        maps = by_factor_map[name]
        js = by_factor_join[name]
        ds = by_factor_detail[name]
        best_join = max([float(j["join_success_ratio"]) for j in js] or [0.0])
        obs = max([int(float(d.get("observation_count") or 0)) for d in ds] or [0])
        cov = max([float(d.get("coverage_ratio") or 0) for d in ds] or [0.0])
        missing_source = not maps or all(not m["source_exists"] for m in maps)
        missing_date = bool(maps) and all(m["date_column_detected"] == "" for m in maps)
        missing_ticker = bool(maps) and all(m["ticker_column_detected"] == "" for m in maps)
        missing_value = bool(maps) and all(m["factor_value_columns_detected"] == "" for m in maps)
        snapshot_only = bool(maps) and all(str(m["is_current_snapshot_only"]).upper() == "TRUE" for m in maps if m["source_exists"])
        pit_blocked = f.get("pit_eligibility") == "PIT_BLOCKED"
        insufficient_horizon = not any(d.get("forward_horizon") != "1D" and int(float(d.get("observation_count") or 0)) > 0 for d in ds)
        join_mismatch = bool(js) and all(j["primary_join_blocker"] == "join_key_mismatch" for j in js)
        insufficient_forward = best_join < 0.30
        flags = {
            "missing_source": missing_source,
            "missing_date_column": missing_date,
            "missing_ticker_column": missing_ticker,
            "missing_factor_value_column": missing_value,
            "current_snapshot_only": snapshot_only,
            "insufficient_date_overlap": bool(js) and all(int(j["common_date_count"]) < 5 for j in js),
            "insufficient_ticker_overlap": bool(js) and all(int(j["common_ticker_count"]) < 20 for j in js),
            "insufficient_forward_return_overlap": insufficient_forward,
            "insufficient_horizon_availability": insufficient_horizon,
            "pit_blocked": pit_blocked,
            "join_key_mismatch": join_mismatch,
            "threshold_too_strict_possible": obs >= 50 and cov < 0.30,
        }
        primary = next((k for k, v in flags.items() if v), "unknown")
        rows.append({"factor_name": name, "factor_family": f.get("factor_family", ""), "factor_subtype": f.get("factor_subtype", ""), **{k: bool_s(v) for k, v in flags.items()}, "unknown": bool_s(primary == "unknown"), "primary_blocker": primary, "max_v21_243_observation_count": obs, "max_v21_243_coverage_ratio": cov, "best_join_success_ratio": best_join, "officially_adopted": False, "shadow_candidate": False})
    return rows


def horizon_rows(factors: list[dict[str, str]], detail: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_factor = defaultdict(dict)
    for r in detail:
        by_factor[r["factor_name"]][r["forward_horizon"]] = int(float(r.get("observation_count") or 0))
    rows = []
    for f in factors:
        vals = by_factor[f["factor_name"]]
        best = max(HORIZONS, key=lambda h: vals.get(h, 0))
        rows.append({
            "factor_name": f["factor_name"],
            "has_1d_forward": vals.get("1D", 0) > 0,
            "has_5d_forward": vals.get("5D", 0) > 0,
            "has_10d_forward": vals.get("10D", 0) > 0,
            "has_20d_forward": vals.get("20D", 0) > 0,
            "usable_1d_obs": vals.get("1D", 0),
            "usable_5d_obs": vals.get("5D", 0),
            "usable_10d_obs": vals.get("10D", 0),
            "usable_20d_obs": vals.get("20D", 0),
            "best_available_primary_horizon": best if vals.get(best, 0) else "",
            "maturity_status": "PARTIAL_1D_ONLY" if vals.get("1D", 0) and not any(vals.get(h, 0) for h in ["5D", "10D", "20D"]) else "MULTI_HORIZON_AVAILABLE" if any(vals.get(h, 0) for h in ["5D", "10D", "20D"]) else "NO_MATURED_FORWARD_ROWS",
        })
    return rows


def technical_discovery(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for term in TECH_TERMS:
        token = norm(term).replace(" ", "_")
        found = []
        for a in artifacts:
            blob = " ".join([a["rel"], *a["cols"]]).lower()
            if token in blob.replace(" ", "_") or norm(term) in blob:
                found.append(a)
        if not found:
            status = "NOT_FOUND"
            best = None
        else:
            best = max(found, key=lambda a: (a["date_count"] > 1, a["ticker_count"], a["row_count"]))
            if not best["date_col"] or not best["ticker_col"]:
                status = "FOUND_AGGREGATED_ONLY"
            elif best["date_count"] > 1:
                status = "FOUND_HISTORICAL_PANEL"
            elif best["date_count"] == 1:
                status = "FOUND_CURRENT_SNAPSHOT_ONLY"
            else:
                status = "NEEDS_COLUMN_MAPPING"
        if best and status == "FOUND_CURRENT_SNAPSHOT_ONLY":
            status = "NEEDS_BACKFILL"
        rows.append({
            "technical_term": term,
            "discovery_status": status,
            "best_source_path": best["rel"] if best else "",
            "source_row_count": best["row_count"] if best else 0,
            "date_column_detected": best["date_col"] if best else "",
            "ticker_column_detected": best["ticker_col"] if best else "",
            "detected_columns": "|".join([c for c in (best["cols"] if best else []) if norm(term).replace(" ", "_") in norm(c).replace(" ", "_") or norm(term) in norm(c)][:20]),
            "pit_status": "PIT_METADATA_PRESENT" if best and best["pit_col"] else "PIT_METADATA_MISSING" if best else "NOT_FOUND",
        })
    return rows


def pit_recheck(factors: list[dict[str, str]], source_map: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_factor = defaultdict(list)
    for r in source_map:
        by_factor[r["factor_name"]].append(r)
    out = []
    for f in factors:
        vals = by_factor[f["factor_name"]]
        pit_values = {v["pit_status"] for v in vals}
        if "PIT_METADATA_PRESENT" in pit_values:
            re = "PIT_RECHECK_PASS_METADATA_PRESENT"
            strict = True
            lite = True
            unsafe = ""
        elif "PIT_LITE_ONLY" in pit_values:
            re = "PIT_LITE_ONLY"
            strict = False
            lite = True
            unsafe = "strict PIT unavailable; keep research-only"
        else:
            re = "PIT_METADATA_REQUIRED"
            strict = False
            lite = False
            unsafe = "missing PIT metadata"
        if f.get("pit_eligibility") == "PIT_BLOCKED":
            strict = False
            unsafe = unsafe or "V21.243 marked PIT_BLOCKED"
        out.append({"factor_name": f["factor_name"], "original_v21_243_pit_status": f.get("pit_eligibility", ""), "rechecked_pit_status": re, "reason": "|".join(sorted(pit_values)) or "no candidate source", "safe_for_strict_pit_backtest": strict, "safe_for_pit_lite_research": lite, "unsafe_reason": unsafe})
    return out


def threshold_sensitivity(factors: list[dict[str, str]], detail: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_factor = defaultdict(list)
    for r in detail:
        by_factor[r["factor_name"]].append(r)
    rows = []
    for min_obs in [50, 100, 250, 500, 1000]:
        for min_date in [5, 10, 20, 60]:
            for min_ticker in [20, 50, 100, 200]:
                usable = 0
                for f in factors:
                    obs = max([int(float(r.get("observation_count") or 0)) for r in by_factor[f["factor_name"]]] or [0])
                    # V21.243 did not persist date/ticker counts; infer conservative lower bounds from obs.
                    inferred_dates = 1 if obs else 0
                    inferred_tickers = obs if obs < 500 else 200
                    if obs >= min_obs and inferred_dates >= min_date and inferred_tickers >= min_ticker and f.get("pit_eligibility") != "PIT_BLOCKED":
                        usable += 1
                rows.append({"min_obs": min_obs, "min_date_count": min_date, "min_ticker_count": min_ticker, "research_only_usable_factor_count": usable, "shadow_candidate_count": 0, "official_adoption_allowed": False})
    return rows


def reconstruction_plan(failures: list[dict[str, Any]], tech: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tech_status = {r["technical_term"].lower(): r["discovery_status"] for r in tech}
    rows = []
    for r in failures:
        name = r["factor_name"]
        if r["pit_blocked"] == "TRUE":
            typ = "PIT_METADATA_REQUIRED"
            needed = True
            blocker = "pit_blocked"
        elif r["missing_factor_value_column"] == "TRUE":
            typ = "COLUMN_MAPPING_REPAIR"
            needed = True
            blocker = "missing_factor_value_column"
        elif r["current_snapshot_only"] == "TRUE":
            typ = "CURRENT_SNAPSHOT_ONLY_NOT_REPAIRABLE"
            needed = True
            blocker = "current_snapshot_only"
        elif name.lower() in tech_status and tech_status[name.lower()] in {"NEEDS_BACKFILL", "NOT_FOUND"}:
            typ = "TECHNICAL_RAW_BACKFILL_FROM_LOCAL_CACHE"
            needed = True
            blocker = tech_status[name.lower()].lower()
        elif r["insufficient_forward_return_overlap"] == "TRUE":
            typ = "FORWARD_RETURN_JOIN_REPAIR"
            needed = True
            blocker = "insufficient_forward_return_overlap"
        elif r["insufficient_horizon_availability"] == "TRUE":
            typ = "LONG_PANEL_REBUILD"
            needed = True
            blocker = "insufficient_horizon_availability"
        elif r["primary_blocker"] == "unknown":
            typ = "NONE_ALREADY_USABLE"
            needed = False
            blocker = ""
        else:
            typ = "LONG_PANEL_REBUILD"
            needed = True
            blocker = r["primary_blocker"]
        rows.append({"factor_name": name, "reconstruction_needed": needed, "reconstruction_type": typ, "recommended_next_version": "V21.245_FACTOR_PANEL_RECONSTRUCTION_DRY_RUN_R1", "estimated_research_value": "HIGH" if name in {"RSI", "MACD", "momentum", "relative strength", "Technical"} else "MEDIUM", "blocker": blocker, "next_action": next_action(typ), "officially_adopted": False, "shadow_candidate": False})
    return rows


def next_action(typ: str) -> str:
    return {
        "NONE_ALREADY_USABLE": "Keep diagnostic-only; wait for maturity.",
        "COLUMN_MAPPING_REPAIR": "Map raw/alias columns into canonical factor panel schema.",
        "LONG_PANEL_REBUILD": "Rebuild local date-ticker-factor panel before effectiveness retest.",
        "FORWARD_RETURN_JOIN_REPAIR": "Align date/ticker keys with local matured forward-return ledgers.",
        "TECHNICAL_RAW_BACKFILL_FROM_LOCAL_CACHE": "Backfill raw technical indicators from existing local cache only.",
        "PIT_METADATA_REQUIRED": "Add strict as-of/source metadata before PIT backtest.",
        "CURRENT_SNAPSHOT_ONLY_NOT_REPAIRABLE": "Do not use for historical effectiveness; archive as snapshot evidence.",
    }.get(typ, "Manual review.")


def build(repo: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    v243_summary, inventory, detail, subdetail = load_v243(repo)
    factors = sorted({r["factor_name"]: r for r in inventory}.values(), key=lambda r: r["factor_name"])
    artifacts = discover_artifacts(repo)
    source_map = []
    for f in factors:
        hits = []
        for a in artifacts:
            usability, value_cols, historical, current_only, pit = usability_for(a, f["factor_name"])
            if value_cols or f["factor_name"].lower() in norm(a["rel"]):
                hits.append((a, usability, value_cols, historical, current_only, pit))
        if not hits:
            source_map.append({"factor_name": f["factor_name"], "factor_family": f.get("factor_family", ""), "candidate_source_path": "", "source_exists": False, "source_row_count": 0, "source_column_count": 0, "date_column_detected": "", "ticker_column_detected": "", "factor_value_columns_detected": "", "is_historical_panel": False, "is_current_snapshot_only": False, "pit_status": "NO_SOURCE", "usability_class": "MISSING_SOURCE"})
            continue
        for a, usability, value_cols, historical, current_only, pit in sorted(hits, key=lambda x: x[0]["row_count"], reverse=True)[:8]:
            source_map.append({"factor_name": f["factor_name"], "factor_family": f.get("factor_family", ""), "candidate_source_path": a["rel"], "source_exists": True, "source_row_count": a["row_count"], "source_column_count": a["column_count"], "date_column_detected": a["date_col"], "ticker_column_detected": a["ticker_col"], "factor_value_columns_detected": "|".join(value_cols), "is_historical_panel": historical, "is_current_snapshot_only": current_only, "pit_status": pit, "usability_class": usability})
    artifacts_by_rel = {a["rel"]: a for a in artifacts}
    fwd = forward_sources(artifacts)
    joins = build_join_diagnostics(source_map, artifacts_by_rel, fwd)
    failures = failure_rows(factors, source_map, joins, detail)
    horizons = horizon_rows(factors, detail)
    tech = technical_discovery(artifacts)
    pit = pit_recheck(factors, source_map)
    sens = threshold_sensitivity(factors, detail)
    plan = reconstruction_plan(failures, tech)
    missing_source_count = sum(1 for r in failures if r["missing_source"] == "TRUE")
    historical_tech = sum(1 for r in tech if r["discovery_status"] == "FOUND_HISTORICAL_PANEL")
    if not artifacts or missing_source_count >= len(factors):
        status = "WARN_V21_244_FACTOR_COVERAGE_SOURCES_TOO_SPARSE"
        decision = "FACTOR_COVERAGE_BLOCKED_BY_SOURCE_LIMITATIONS"
    elif historical_tech > 0 and any(r["reconstruction_needed"] for r in plan):
        status = "PASS_V21_244_FACTOR_COVERAGE_REPAIR_PLAN_READY"
        decision = "FACTOR_COVERAGE_REPAIR_PLAN_READY_RESEARCH_ONLY"
    else:
        status = "PARTIAL_PASS_V21_244_FACTOR_COVERAGE_DIAGNOSIS_READY"
        decision = "FACTOR_COVERAGE_DIAGNOSIS_READY_CONTINUE_RECONSTRUCTION"
    summary = {
        "version": STAGE,
        "final_status": status,
        "final_decision": decision,
        "research_only": True,
        "official_adoption_allowed": False,
        "broker_action_allowed": False,
        "market_data_fetch_attempted": False,
        "network_provider_fetch_attempted": False,
        "official_factor_marked_count": 0,
        "shadow_candidate_marked_count": 0,
        "v21_243_evaluated_factor_count": v243_summary.get("evaluated_factor_count", 0),
        "v21_243_insufficient_coverage_factor_count": v243_summary.get("insufficient_coverage_factor_count", 0),
        "diagnosed_factor_count": len(factors),
        "diagnosed_subfactor_count": len({r["factor_name"] for r in subdetail}),
        "missing_source_count": missing_source_count,
        "current_snapshot_only_count": sum(1 for r in failures if r["current_snapshot_only"] == "TRUE"),
        "join_key_mismatch_count": sum(1 for r in failures if r["join_key_mismatch"] == "TRUE"),
        "insufficient_forward_return_overlap_count": sum(1 for r in failures if r["insufficient_forward_return_overlap"] == "TRUE"),
        "technical_found_historical_panel_count": historical_tech,
        "technical_needs_backfill_count": sum(1 for r in tech if r["discovery_status"] == "NEEDS_BACKFILL"),
        "reconstruction_needed_count": sum(1 for r in plan if r["reconstruction_needed"]),
        "error_count": 0,
    }
    return summary, {"source_map": source_map, "joins": joins, "failures": failures, "horizons": horizons, "tech": tech, "pit": pit, "sens": sens, "plan": plan}


def write_outputs(out: Path, summary: dict[str, Any], tables: dict[str, list[dict[str, Any]]]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "v21_244_summary.json", summary)
    write_csv(out / "factor_coverage_failure_detail.csv", tables["failures"], ["factor_name", "factor_family", "factor_subtype", "missing_source", "missing_date_column", "missing_ticker_column", "missing_factor_value_column", "current_snapshot_only", "insufficient_date_overlap", "insufficient_ticker_overlap", "insufficient_forward_return_overlap", "insufficient_horizon_availability", "pit_blocked", "join_key_mismatch", "threshold_too_strict_possible", "unknown", "primary_blocker", "max_v21_243_observation_count", "max_v21_243_coverage_ratio", "best_join_success_ratio", "officially_adopted", "shadow_candidate"])
    write_csv(out / "factor_source_artifact_map.csv", tables["source_map"], ["factor_name", "factor_family", "candidate_source_path", "source_exists", "source_row_count", "source_column_count", "date_column_detected", "ticker_column_detected", "factor_value_columns_detected", "is_historical_panel", "is_current_snapshot_only", "pit_status", "usability_class"])
    write_csv(out / "factor_join_diagnostics.csv", tables["joins"], ["factor_name", "candidate_source_path", "forward_return_source_path", "factor_row_count", "forward_return_row_count", "common_date_count", "common_ticker_count", "joined_row_count", "join_success_ratio", "earliest_common_date", "latest_common_date", "available_horizons", "primary_join_blocker"])
    write_csv(out / "factor_horizon_availability.csv", tables["horizons"], ["factor_name", "has_1d_forward", "has_5d_forward", "has_10d_forward", "has_20d_forward", "usable_1d_obs", "usable_5d_obs", "usable_10d_obs", "usable_20d_obs", "best_available_primary_horizon", "maturity_status"])
    write_csv(out / "factor_panel_reconstruction_plan.csv", tables["plan"], ["factor_name", "reconstruction_needed", "reconstruction_type", "recommended_next_version", "estimated_research_value", "blocker", "next_action", "officially_adopted", "shadow_candidate"])
    write_csv(out / "technical_raw_subfactor_discovery.csv", tables["tech"], ["technical_term", "discovery_status", "best_source_path", "source_row_count", "date_column_detected", "ticker_column_detected", "detected_columns", "pit_status"])
    write_csv(out / "pit_eligibility_recheck.csv", tables["pit"], ["factor_name", "original_v21_243_pit_status", "rechecked_pit_status", "reason", "safe_for_strict_pit_backtest", "safe_for_pit_lite_research", "unsafe_reason"])
    write_csv(out / "coverage_threshold_sensitivity.csv", tables["sens"], ["min_obs", "min_date_count", "min_ticker_count", "research_only_usable_factor_count", "shadow_candidate_count", "official_adoption_allowed"])
    report = [
        STAGE,
        f"final_status={summary['final_status']}",
        f"final_decision={summary['final_decision']}",
        "research_only=True",
        "official_adoption_allowed=False",
        "broker_action_allowed=False",
        "No factors were promoted to official or shadow-candidate status.",
    ]
    (out / "V21.244_factor_coverage_repair_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")


def run(repo: Path, output_dir: Path | None = None) -> dict[str, Any]:
    out = output_dir or repo / OUT_REL
    try:
        summary, tables = build(repo)
        write_outputs(out, summary, tables)
        return summary
    except Exception as exc:
        out.mkdir(parents=True, exist_ok=True)
        summary = {"version": STAGE, "final_status": "FAIL_V21_244_FACTOR_COVERAGE_REPAIR_EXECUTION_ERROR", "final_decision": "FACTOR_COVERAGE_BLOCKED_BY_SOURCE_LIMITATIONS", "research_only": True, "official_adoption_allowed": False, "broker_action_allowed": False, "market_data_fetch_attempted": False, "network_provider_fetch_attempted": False, "error_count": 1, "error": repr(exc)}
        write_json(out / "v21_244_summary.json", summary)
        raise


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", type=Path, default=Path(r"D:\us-tech-quant"))
    p.add_argument("--output-dir", type=Path)
    args = p.parse_args(argv)
    try:
        s = run(args.repo_root.resolve(), args.output_dir)
    except Exception:
        return 1
    out = args.output_dir or args.repo_root / OUT_REL
    for key in ["final_status", "final_decision", "v21_243_evaluated_factor_count", "v21_243_insufficient_coverage_factor_count", "diagnosed_factor_count", "diagnosed_subfactor_count", "missing_source_count", "current_snapshot_only_count", "join_key_mismatch_count", "insufficient_forward_return_overlap_count", "technical_found_historical_panel_count", "technical_needs_backfill_count", "reconstruction_needed_count", "official_adoption_allowed", "broker_action_allowed"]:
        print(f"{key}={s.get(key)}")
    print(f"output_root={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
