#!/usr/bin/env python
"""V21.233 Moomoo-only compact ABCDE research rerun."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    import pandas as pd
except Exception:
    pd = None


STAGE = "V21.233_MOOMOO_ONLY_ABCDE_RERUN"
OUT_REL = Path("outputs/v21") / STAGE
V231_REL = Path("outputs/v21/V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD")
V232_REL = Path("outputs/v21/V21.232_MOOMOO_ONLY_DRAM_DAILY_AND_INTRADAY_PLAN")
PASS_STATUS = "PASS_V21_233_MOOMOO_ONLY_ABCDE_RERUN_READY"
WARN_STATUS = "WARN_V21_233_MOOMOO_ONLY_ABCDE_RERUN_READY_WITH_COMPACT_PROXY_WARNINGS"
FAIL_POLICY = "FAIL_V21_233_SOURCE_POLICY_VIOLATION"
FAIL_MISSING = "FAIL_V21_233_CANONICAL_SNAPSHOT_MISSING"
FAIL_RERUN = "FAIL_V21_233_ABCDE_RERUN_FAILED"
FAIL_STALE = "FAIL_V21_233_TARGET_DATE_UNIVERSE_STALE"
DECISION = "MOOMOO_ONLY_ABCDE_COMPACT_RERUN_READY_RESEARCH_ONLY"
FORBIDDEN_PROVIDER = "y" + "finance"
FORBIDDEN_PROVIDER_CALL = "yf" + ".download"
STRATEGIES = {
    "A1_CONTROL": {"momentum": 0.35, "trend": 0.25, "volatility": 0.10, "drawdown": 0.10, "liquidity": 0.10, "data_trust": 0.10},
    "B_STATIC_MOMENTUM": {"momentum": 0.55, "trend": 0.20, "volatility": 0.05, "drawdown": 0.05, "liquidity": 0.05, "data_trust": 0.10},
    "C_DYNAMIC_MOMENTUM": {"momentum": 0.45, "trend": 0.25, "volatility": 0.10, "drawdown": 0.05, "liquidity": 0.05, "data_trust": 0.10},
    "D_WEIGHT_OPTIMIZED_REFERENCE": {"momentum": 0.30, "trend": 0.25, "volatility": 0.15, "drawdown": 0.15, "liquidity": 0.05, "data_trust": 0.10},
    "E_R1_DEFENSIVE_REFERENCE": {"momentum": 0.20, "trend": 0.20, "volatility": 0.25, "drawdown": 0.20, "liquidity": 0.05, "data_trust": 0.10},
}

RANK_FIELDS = ["strategy_name","rank","ticker","moomoo_symbol","latest_date","score","score_momentum","score_trend","score_volatility","score_drawdown","score_liquidity","score_data_trust","compact_proxy_used","unavailable_component_count","source_policy","source_snapshot_id","yfinance_used","external_fallback_used","research_only","official_adoption_allowed","broker_action_allowed","notes"]
TOP_FIELDS = ["strategy_name","rank","ticker","score","latest_date","compact_proxy_used","notes"]
OVERLAP_FIELDS = ["strategy_left","strategy_right","top20_overlap_count","top50_overlap_count","top20_overlap_ratio","top50_overlap_ratio","notes"]
DATE_FIELDS = ["strategy_name","latest_date","ticker_count","ranked_ticker_count","same_date_comparable","latest_date_missing_count","notes"]
COVERAGE_FIELDS = ["ticker","moomoo_symbol","has_canonical_qfq","latest_date","row_count","coverage_status","included_in_ranking","excluded_reason","notes"]
MISSING_FIELDS = ["ticker","moomoo_symbol","reason","yahoo_fallback_allowed","external_fallback_allowed","included_in_ranking","required_user_review","notes"]
QUALITY_FIELDS = ["check_name","strategy_name","passed","severity","affected_tickers","notes"]
SOURCE_FIELDS = ["artifact","path","source_policy","source","yfinance_used","yahoo_used","external_fallback_used","moomoo_used","pass","notes"]
SNAP_FIELDS = ["check_name","expected","actual","passed","severity","notes"]
CROSS_FIELDS = ["check_name","expected","actual","passed","severity","notes"]
AUDIT_FIELDS = ["check_name","passed","yfinance_import_present","yfinance_call_present","yahoo_default_allowed","external_fallback_default_allowed","notes"]
EXTERNAL_MOOMOO_ROOT = Path(r"D:\us-tech-quant-data\moomoo")


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def bool_text(v: bool) -> str:
    return "True" if v else "False"


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader(); w.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    try:
        p = json.loads(path.read_text(encoding="utf-8"))
        return p if isinstance(p, dict) else {}
    except Exception:
        return {}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as h:
            return [{k: (v or "") for k, v in r.items() if k is not None} for r in csv.DictReader(h)]
    except Exception:
        return []


def load_policy_guard(repo_root: Path):
    path = repo_root / "scripts/v21/v21_data_source_policy_guard.py"
    if not path.exists():
        raise FileNotFoundError(str(path))
    spec = importlib.util.spec_from_file_location("v21_data_source_policy_guard", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(str(path))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


def sha256(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as h:
        for b in iter(lambda: h.read(1024 * 1024), b""):
            d.update(b)
    return d.hexdigest()


def self_audit(repo_root: Path) -> tuple[list[dict[str, Any]], bool]:
    path = repo_root / "scripts/v21/v21_233_moomoo_only_abcde_rerun.py"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    imp = bool(re.search(r"(^|\n)\s*(import|from)\s+" + re.escape(FORBIDDEN_PROVIDER), text))
    call = FORBIDDEN_PROVIDER_CALL in text
    return ([{"check_name":"v21_233_script_forbidden_provider_audit","passed":bool_text(not imp and not call),"yfinance_import_present":bool_text(imp),"yfinance_call_present":bool_text(call),"yahoo_default_allowed":"False","external_fallback_default_allowed":"False","notes":"static audit"}], imp or call)


def source_gate(snapshot_id: str) -> dict[str, Any]:
    return {"policy_version":"V21.233","data_source_policy":"MOOMOO_ONLY","source_snapshot_id":snapshot_id,"yfinance_allowed":False,"yahoo_allowed":False,"external_fallback_allowed":False,"broker_action_allowed":False,"trade_unlock_allowed":False,"official_adoption_allowed":False,"research_only":True,"active_trading_focus":"DRAM","next_allowed_stage":"V21.234_MINIMAL_MOOMOO_ONLY_DAILY_RESEARCH_CHAIN"}


def to_float(v: Any) -> float | None:
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except Exception:
        return None


def pct_rank(values: dict[str, float], reverse: bool = False) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda x: x[1], reverse=not reverse)
    n = max(len(ordered) - 1, 1)
    return {ticker: 1 - i / n for i, (ticker, _) in enumerate(ordered)}


def load_canonical(path: Path) -> list[dict[str, Any]]:
    rows = read_csv_rows(path)
    return sorted(rows, key=lambda r: (r.get("ticker",""), r.get("date","")))


def load_external_qfq_current_universe(cutoff_date: str) -> list[dict[str, Any]]:
    """Read the shared Moomoo cache without copying it or looking past cutoff."""
    manifest = EXTERNAL_MOOMOO_ROOT / "metadata" / "abcde_price_universe_r2.csv"
    price_root = EXTERNAL_MOOMOO_ROOT / "source" / "prices_qfq"
    if pd is None or not manifest.exists() or not price_root.exists():
        return []
    universe = {str(row.get("ticker", "")).upper() for row in read_csv_rows(manifest)}
    if not universe:
        return []
    frames = []
    for path in sorted(price_root.glob("year=*/prices.parquet")):
        try:
            frame = pd.read_parquet(path, columns=["ticker", "trade_date", "open", "high", "low", "close", "volume"])
            frames.append(frame)
        except Exception:
            return []
    if not frames:
        return []
    data = pd.concat(frames, ignore_index=True)
    data["ticker"] = data["ticker"].astype(str).str.upper()
    data["date"] = data["trade_date"].astype(str).str[:10]
    data = data[(data["ticker"].isin(universe)) & (data["date"] <= cutoff_date)]
    data = data.drop_duplicates(["ticker", "date"], keep="last").sort_values(["ticker", "date"])
    return [
        {"ticker": str(row.ticker), "moomoo_symbol": f"US.{row.ticker}", "date": str(row.date),
         "open": row.open, "high": row.high, "low": row.low, "close": row.close, "volume": row.volume,
         "source": "LOCAL_MOOMOO_CACHE", "source_policy": "MOOMOO_ONLY"}
        for row in data.itertuples(index=False)
    ]


def grouped(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r.get("ticker",""), []).append(r)
    return {k: v for k, v in out.items() if k}


def ret(closes: list[float], n: int) -> float | None:
    if len(closes) <= n or closes[-n-1] == 0:
        return None
    return closes[-1] / closes[-n-1] - 1


def features_by_ticker(groups: dict[str, list[dict[str, Any]]], coverage_rows: list[dict[str, str]], requested_target_date: str = "") -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    feats: dict[str, dict[str, Any]] = {}
    coverage_map = {r.get("ticker",""): r for r in coverage_rows}
    coverage_audit = []
    missing = []
    failed_known = set()
    for r in coverage_rows:
        if r.get("coverage_status") != "OK" and r.get("ticker"):
            failed_known.add(r["ticker"])
    for ticker, rows in groups.items():
        closes = [to_float(r.get("close")) for r in rows]
        closes = [v for v in closes if v is not None]
        vols = [to_float(r.get("volume")) or 0.0 for r in rows]
        latest = rows[-1].get("date","") if rows else ""
        if requested_target_date and latest < requested_target_date:
            coverage_audit.append({"ticker":ticker,"moomoo_symbol":rows[-1].get("moomoo_symbol","") if rows else "","has_canonical_qfq":"True","latest_date":latest,"row_count":len(rows),"coverage_status":"STALE_TARGET_DATE","included_in_ranking":"False","excluded_reason":"latest_date before requested target date","notes":f"requested_target_date={requested_target_date}"})
            missing.append({"ticker":ticker,"moomoo_symbol":rows[-1].get("moomoo_symbol","") if rows else "","reason":"STALE_TARGET_DATE","yahoo_fallback_allowed":"False","external_fallback_allowed":"False","included_in_ranking":"False","required_user_review":"True","notes":f"latest_date={latest}; requested_target_date={requested_target_date}"})
            continue
        if len(closes) < 60:
            coverage_audit.append({"ticker":ticker,"moomoo_symbol":rows[-1].get("moomoo_symbol","") if rows else "","has_canonical_qfq":"True","latest_date":latest,"row_count":len(rows),"coverage_status":"INSUFFICIENT_ROWS","included_in_ranking":"False","excluded_reason":"less than 60 rows","notes":"Moomoo-only compact feature minimum"})
            missing.append({"ticker":ticker,"moomoo_symbol":rows[-1].get("moomoo_symbol","") if rows else "","reason":"INSUFFICIENT_CANONICAL_ROWS","yahoo_fallback_allowed":"False","external_fallback_allowed":"False","included_in_ranking":"False","required_user_review":"True","notes":"no fallback allowed"})
            continue
        r20 = ret(closes, 20) or 0.0
        r60 = ret(closes, 60) or 0.0
        r120 = ret(closes, 120) or r60
        ma20 = sum(closes[-20:]) / 20
        ma50 = sum(closes[-50:]) / 50
        peak = max(closes[-120:]) if len(closes) >= 120 else max(closes)
        drawdown = closes[-1] / peak - 1 if peak else 0.0
        returns = [(b/a - 1) for a,b in zip(closes[-61:-1], closes[-60:]) if a]
        vol = (sum((x - sum(returns)/len(returns))**2 for x in returns)/len(returns))**0.5 if returns else 0.0
        liq = sum(vols[-20:]) / min(20, len(vols))
        feats[ticker] = {"ticker":ticker,"moomoo_symbol":rows[-1].get("moomoo_symbol",""),"latest_date":latest,"momentum_raw":0.5*r20+0.3*r60+0.2*r120,"trend_raw":(closes[-1]/ma20-1)+(ma20/ma50-1),"volatility_raw":vol,"drawdown_raw":drawdown,"liquidity_raw":liq,"data_trust_raw":1.0 if coverage_map.get(ticker,{}).get("coverage_status","OK")=="OK" else 0.8,"row_count":len(rows)}
        coverage_audit.append({"ticker":ticker,"moomoo_symbol":rows[-1].get("moomoo_symbol",""),"has_canonical_qfq":"True","latest_date":latest,"row_count":len(rows),"coverage_status":"OK","included_in_ranking":"True","excluded_reason":"","notes":"included in compact ABCDE rerun"})
    for ticker in sorted(failed_known - set(groups)):
        missing.append({"ticker":ticker,"moomoo_symbol":f"US.{ticker}","reason":"MOOMOO_UNKNOWN_OR_NO_CANONICAL_DATA","yahoo_fallback_allowed":"False","external_fallback_allowed":"False","included_in_ranking":"False","required_user_review":"True","notes":"from V21.231 failed ticker ledger/coverage"})
        coverage_audit.append({"ticker":ticker,"moomoo_symbol":f"US.{ticker}","has_canonical_qfq":"False","latest_date":"","row_count":0,"coverage_status":"MISSING_CANONICAL","included_in_ranking":"False","excluded_reason":"Moomoo unknown / no canonical data","notes":"no Yahoo/yfinance fallback"})
    return feats, coverage_audit, missing


def build_rankings(feats: dict[str, dict[str, Any]], snapshot_id: str) -> list[dict[str, Any]]:
    mom = pct_rank({k:v["momentum_raw"] for k,v in feats.items()})
    trend = pct_rank({k:v["trend_raw"] for k,v in feats.items()})
    vol = pct_rank({k:v["volatility_raw"] for k,v in feats.items()}, reverse=True)
    dd = pct_rank({k:v["drawdown_raw"] for k,v in feats.items()})
    liq = pct_rank({k:v["liquidity_raw"] for k,v in feats.items()})
    dt = {k:v["data_trust_raw"] for k,v in feats.items()}
    rows=[]
    for strat, weights in STRATEGIES.items():
        scored=[]
        for t, f in feats.items():
            score = weights["momentum"]*mom[t]+weights["trend"]*trend[t]+weights["volatility"]*vol[t]+weights["drawdown"]*dd[t]+weights["liquidity"]*liq[t]+weights["data_trust"]*dt[t]
            scored.append((score,t))
        for rank, (score,t) in enumerate(sorted(scored, reverse=True), start=1):
            f=feats[t]
            rows.append({"strategy_name":strat,"rank":rank,"ticker":t,"moomoo_symbol":f["moomoo_symbol"],"latest_date":f["latest_date"],"score":f"{score:.6f}","score_momentum":f"{mom[t]:.6f}","score_trend":f"{trend[t]:.6f}","score_volatility":f"{vol[t]:.6f}","score_drawdown":f"{dd[t]:.6f}","score_liquidity":f"{liq[t]:.6f}","score_data_trust":f"{dt[t]:.6f}","compact_proxy_used":"True","unavailable_component_count":3,"source_policy":"MOOMOO_ONLY","source_snapshot_id":snapshot_id,"yfinance_used":"False","external_fallback_used":"False","research_only":"True","official_adoption_allowed":"False","broker_action_allowed":"False","notes":"UNAVAILABLE_IN_MOOMOO_ONLY_COMPACT_RERUN: fundamentals/event/factor legacy components; compact proxy weights used"})
    return rows


def overlap(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by = {s:[r for r in rows if r["strategy_name"]==s] for s in STRATEGIES}
    out=[]
    for left in STRATEGIES:
        for right in STRATEGIES:
            l20={r["ticker"] for r in by[left] if int(r["rank"])<=20}; r20={r["ticker"] for r in by[right] if int(r["rank"])<=20}
            l50={r["ticker"] for r in by[left] if int(r["rank"])<=50}; r50={r["ticker"] for r in by[right] if int(r["rank"])<=50}
            out.append({"strategy_left":left,"strategy_right":right,"top20_overlap_count":len(l20&r20),"top50_overlap_count":len(l50&r50),"top20_overlap_ratio":f"{len(l20&r20)/max(len(l20),1):.4f}","top50_overlap_ratio":f"{len(l50&r50)/max(len(l50),1):.4f}","notes":"compact rerun overlap"})
    return out


def source_audit(pointer: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"artifact":"canonical_snapshot_pointer","path":pointer.get("canonical_snapshot_dir",""),"source_policy":pointer.get("source_policy",""),"source":pointer.get("source",""),"yfinance_used":bool_text(bool(pointer.get("yfinance_used"))),"yahoo_used":bool_text(bool(pointer.get("yahoo_used"))),"external_fallback_used":bool_text(bool(pointer.get("external_fallback_used"))),"moomoo_used":bool_text(pointer.get("source")=="MOOMOO_OPEND"),"pass":bool_text(pointer.get("source_policy")=="MOOMOO_ONLY" and not pointer.get("yfinance_used") and not pointer.get("external_fallback_used")),"notes":"read-only source audit"}]


def run(repo_root: Path, output_dir: Path, v21_231_output_dir: Path | None = None, v21_232_output_dir: Path | None = None, cache_root: Path | None = None, snapshot_id: str | None = None, top_n: int = 50) -> dict[str, Any]:
    repo_root=repo_root.resolve(); output_dir.mkdir(parents=True, exist_ok=True)
    v231=(v21_231_output_dir or repo_root/V231_REL).resolve(); v232=(v21_232_output_dir or repo_root/V232_REL).resolve()
    pointer=read_json(v231/"canonical_snapshot_pointer.json"); snap=snapshot_id or pointer.get("snapshot_id",""); croot=Path(cache_root or pointer.get("cache_root") or "")
    write_json(output_dir/"source_policy_gate.json", source_gate(snap))
    guard_found=(repo_root/"scripts/v21/v21_data_source_policy_guard.py").exists(); policy_ok=False
    try:
        guard=load_policy_guard(repo_root); guard.assert_moomoo_only_policy("V21.233 ABCDE compact rerun canonical dram abcde")
        pol=guard.load_data_source_policy(repo_root/"config/v21/data_source_policy.json")
        policy_ok=pol.get("default_data_source_policy")=="MOOMOO_ONLY" and pol.get("research_only") is True
    except Exception:
        policy_ok=False
    audit, violation=self_audit(repo_root)
    required=["v21_231_summary.json","canonical_snapshot_pointer.json","canonical_snapshot_pointer.csv","canonical_rebuild_manifest.csv","canonical_quality_audit.csv","ticker_coverage_audit.csv","failed_ticker_retry_ledger.csv","source_policy_gate.json"]
    cross=[]; input_ok=True
    for name in required:
        ex=(v231/name).exists(); input_ok=input_ok and ex
        cross.append({"check_name":name,"expected":"present","actual":"present" if ex else "missing","passed":bool_text(ex),"severity":"ERROR" if not ex else "INFO","notes":str(v231/name)})
    source_ok=pointer.get("source_policy")=="MOOMOO_ONLY" and pointer.get("yfinance_used") is False and pointer.get("external_fallback_used") is False
    qfq=Path(pointer.get("canonical_qfq_path",""))
    if not input_ok:
        return write_all(output_dir, base_summary(FAIL_MISSING, repo_root, output_dir, croot, snap, pointer), [], [], [], [], [], [], [], [], source_audit(pointer), snap_audit(pointer, False, source_ok), cross, dram_cross(v232), audit)
    if not policy_ok or violation or not source_ok:
        return write_all(output_dir, base_summary(FAIL_POLICY, repo_root, output_dir, croot, snap, pointer), [], [], [], [], [], [], [], [], source_audit(pointer), snap_audit(pointer, qfq.exists(), source_ok), cross, dram_cross(v232), audit)
    if not qfq.exists():
        return write_all(output_dir, base_summary(FAIL_MISSING, repo_root, output_dir, croot, snap, pointer), [], [], [], [], [], [], [], [], source_audit(pointer), snap_audit(pointer, False, source_ok), cross, dram_cross(v232), audit)
    before=sha256(qfq)
    rows=load_canonical(qfq)
    requested_target_date=str(pointer.get("canonical_complete_universe_date") or read_json(v231/"v21_231_summary.json").get("canonical_complete_universe_date") or read_json(v231/"v21_231_summary.json").get("canonical_latest_date") or "")[:10]
    cutoff_date=requested_target_date or max([str(r.get("date", "")) for r in rows] or [""])
    # Rankings must use exactly the promoted canonical snapshot.  A separate
    # shared cache can have a different as-of date/universe and must not
    # silently replace this snapshot.
    if sha256(qfq) != before:
        raise RuntimeError("cache snapshot mutated during read")
    groups=grouped(rows); coverage_rows=read_csv_rows(v231/"ticker_coverage_audit.csv")
    expected_manifest=read_csv_rows(v231/"abcde_expected_universe.csv")
    expected_tickers={r.get("ticker", "") for r in expected_manifest if r.get("ticker")} or set(groups)
    exclusion_rows=read_csv_rows(v231/"abcde_daily_exclusion_ledger.csv") or read_csv_rows(v231/"abcde_exclusion_ledger.csv")
    exclusions={r.get("ticker", "") for r in exclusion_rows
                if r.get("ticker") and (str(r.get("allowed", "")).lower()=="true" or r.get("status", "").upper() in {"APPROVED", "VALID", "ACTIVE"})
                and (not str(r.get("effective_date") or r.get("target_date") or "")[:10] or str(r.get("effective_date") or r.get("target_date") or "")[:10] <= requested_target_date)}
    exclusions &= expected_tickers
    usable_tickers=expected_tickers-exclusions
    feats, coverage, missing=features_by_ticker(groups, coverage_rows, requested_target_date)
    # Missing planned tickers are stale for the requested target, even when a
    # partial canonical file contains no row from which to infer latest_date.
    for ticker in sorted(usable_tickers-set(groups)):
        coverage.append({"ticker":ticker,"moomoo_symbol":f"US.{ticker}","has_canonical_qfq":"False","latest_date":"","row_count":0,"coverage_status":"STALE_TARGET_DATE","included_in_ranking":"False","excluded_reason":"missing planned ticker at requested target date","notes":f"requested_target_date={requested_target_date}"})
        missing.append({"ticker":ticker,"moomoo_symbol":f"US.{ticker}","reason":"STALE_TARGET_DATE","yahoo_fallback_allowed":"False","external_fallback_allowed":"False","included_in_ranking":"False","required_user_review":"True","notes":f"missing canonical data; requested_target_date={requested_target_date}"})
    # Rankings are cross-sectional snapshots: a ticker whose latest usable
    # price is older than the common as-of date cannot be ranked alongside the
    # current universe.  Exclude it rather than mixing dates or backfilling.
    common_date=requested_target_date or max([str(f.get("latest_date", "")) for f in feats.values()] or [""])
    stale={ticker for ticker, feature in feats.items() if str(feature.get("latest_date", "")) != common_date}
    if stale:
        for ticker in sorted(stale):
            missing.append({"ticker":ticker,"moomoo_symbol":feats[ticker].get("moomoo_symbol",f"US.{ticker}"),"reason":"STALE_PRICE_DATE_EXCLUDED_FROM_SAME_DATE_RANKING","yahoo_fallback_allowed":"False","external_fallback_allowed":"False","included_in_ranking":"False","required_user_review":"True","notes":f"latest price date {feats[ticker].get('latest_date','')} differs from common as-of {common_date}"})
        for row in coverage:
            if row.get("ticker") in stale:
                row.update({"coverage_status":"STALE_DATE_EXCLUDED","included_in_ranking":"False","excluded_reason":"latest date differs from common ranking as-of date"})
        feats={ticker: feature for ticker, feature in feats.items() if ticker not in stale}
    stale_target=sorted({r["ticker"] for r in coverage if r.get("coverage_status")=="STALE_TARGET_DATE"})
    rankings=build_rankings(feats, snap) if feats and not stale_target else []
    if stale_target:
        status=FAIL_STALE
    elif not rankings:
        status=FAIL_RERUN
    else:
        status=WARN_STATUS
    top20=[trim_top(r) for r in rankings if int(r["rank"])<=20]
    top50=[trim_top(r) for r in rankings if int(r["rank"])<=top_n]
    latest_dates={s: max([r["latest_date"] for r in rankings if r["strategy_name"]==s] or [""]) for s in STRATEGIES}
    date_audit=[{"strategy_name":s,"latest_date":latest_dates[s],"ticker_count":len(feats),"ranked_ticker_count":sum(1 for r in rankings if r["strategy_name"]==s),"same_date_comparable":bool_text(len(set(latest_dates.values()))==1),"latest_date_missing_count":0 if latest_dates[s] else len(feats),"notes":"compact rankings from one canonical snapshot"} for s in STRATEGIES]
    quality=[{"check_name":"ranking_rows_present","strategy_name":s,"passed":bool_text(any(r["strategy_name"]==s for r in rankings)),"severity":"ERROR" if not any(r["strategy_name"]==s for r in rankings) else "INFO","affected_tickers":"","notes":"strategy output exists"} for s in STRATEGIES]
    quality.append({"check_name":"compact_proxy_components","strategy_name":"ALL","passed":"True","severity":"WARN","affected_tickers":len(feats),"notes":"UNAVAILABLE_IN_MOOMOO_ONLY_COMPACT_RERUN components replaced with documented compact price/volume proxies"})
    summary=base_summary(status, repo_root, output_dir, croot, snap, pointer, rankings, feats, missing, coverage, latest_dates)
    summary.update({"requested_target_date":requested_target_date,"expected_universe_count":len(expected_tickers),"legally_excluded_count":len(exclusions),"eligible_universe_count":len(usable_tickers),"usable_ticker_count":len(usable_tickers),"feature_input_ticker_count":len(usable_tickers),"feature_built_ticker_count":len(feats),"ranked_ticker_count":len(feats),"ranking_contains_olpx":"OLPX" in feats,"stale_ticker_count":len(stale_target),"missing_target_date_tickers":stale_target,"preserve_previous_top20":bool(status.startswith("FAIL_"))})
    return write_all(output_dir, summary, rankings, top20, top50, overlap(rankings), date_audit, coverage, missing, quality, source_audit(pointer), snap_audit(pointer, True, source_ok), cross, dram_cross(v232), audit)


def trim_top(r: dict[str, Any]) -> dict[str, Any]:
    return {"strategy_name":r["strategy_name"],"rank":r["rank"],"ticker":r["ticker"],"score":r["score"],"latest_date":r["latest_date"],"compact_proxy_used":r["compact_proxy_used"],"notes":r["notes"]}


def snap_audit(pointer: dict[str, Any], exists: bool, source_ok: bool) -> list[dict[str, Any]]:
    return [{"check_name":"canonical_qfq_path_exists","expected":"True","actual":bool_text(exists),"passed":bool_text(exists),"severity":"ERROR" if not exists else "INFO","notes":pointer.get("canonical_qfq_path","")},{"check_name":"source_policy","expected":"MOOMOO_ONLY","actual":pointer.get("source_policy",""),"passed":bool_text(source_ok),"severity":"ERROR" if not source_ok else "INFO","notes":"no fallback"}]


def dram_cross(v232: Path) -> list[dict[str, Any]]:
    s=read_json(v232/"v21_232_summary.json")
    return [{"check_name":"v21_232_found","expected":"optional","actual":bool_text(bool(s)),"passed":"True","severity":"INFO","notes":str(v232/"v21_232_summary.json")},{"check_name":"active_trading_focus","expected":"DRAM","actual":"DRAM","passed":"True","severity":"INFO","notes":"V21.233 does not change focus"},{"check_name":"v21_232_status","expected":"PASS_OR_MISSING","actual":s.get("final_status","MISSING"),"passed":"True","severity":"INFO","notes":"crosscheck only"}]


def base_summary(status: str, repo_root: Path, output_dir: Path, cache_root: Path, snap: str, pointer: dict[str, Any], rankings: list[dict[str, Any]] | None=None, feats: dict[str, Any] | None=None, missing: list[dict[str, Any]] | None=None, coverage: list[dict[str, Any]] | None=None, latest_dates: dict[str, str] | None=None) -> dict[str, Any]:
    rankings=rankings or []; feats=feats or {}; missing=missing or []; coverage=coverage or []; latest_dates=latest_dates or {}
    def top(strategy: str) -> str:
        return ",".join(r["ticker"] for r in rankings if r["strategy_name"]==strategy and int(r["rank"])<=20)
    unavailable=sum(int(r.get("unavailable_component_count",0)) for r in rankings)
    cov_warn=sum(1 for r in coverage if r.get("coverage_status")!="OK")
    return {"final_status":status,"final_decision":DECISION,"repo_root":str(repo_root),"output_dir":str(output_dir),"cache_root":str(cache_root),"source_snapshot_id":snap,"canonical_snapshot_dir":pointer.get("canonical_snapshot_dir",""),"canonical_latest_date":max([r.get("latest_date","") for r in rankings] or [""]),"ranked_strategy_count":len({r["strategy_name"] for r in rankings}),"ranked_ticker_count":len(feats),"excluded_ticker_count":sum(1 for r in coverage if r.get("included_in_ranking")!="True"),"missing_ticker_count":len(missing),"same_date_comparable_all_strategies":bool_text(len(set(latest_dates.values()))<=1 if latest_dates else False),"A1_top20":top("A1_CONTROL"),"B_top20":top("B_STATIC_MOMENTUM"),"C_top20":top("C_DYNAMIC_MOMENTUM"),"D_top20":top("D_WEIGHT_OPTIMIZED_REFERENCE"),"E_R1_top20":top("E_R1_DEFENSIVE_REFERENCE"),"A1_latest_date":latest_dates.get("A1_CONTROL",""),"B_latest_date":latest_dates.get("B_STATIC_MOMENTUM",""),"C_latest_date":latest_dates.get("C_DYNAMIC_MOMENTUM",""),"D_latest_date":latest_dates.get("D_WEIGHT_OPTIMIZED_REFERENCE",""),"E_R1_latest_date":latest_dates.get("E_R1_DEFENSIVE_REFERENCE",""),"compact_proxy_used":bool(rankings),"unavailable_component_warning_count":unavailable,"coverage_warning_count":cov_warn,"quality_error_count":1 if status==FAIL_RERUN else 0,"quality_warning_count":1 if rankings else 0,"yfinance_used":False,"yahoo_used":False,"external_fallback_used":False,"moomoo_used":True,"broker_action_allowed":False,"trade_unlock_used":False,"official_adoption_allowed":False,"research_only":True,"warning_count":(1 if rankings else 0)+cov_warn,"error_count":1 if status.startswith("FAIL_") else 0}


def write_all(out: Path, summary: dict[str, Any], rankings, top20, top50, overlaps, date_audit, coverage, missing, quality, source, snap, cross, dram, audit) -> dict[str, Any]:
    # A stale/failed run is audit-only: never replace the last valid ranking snapshot.
    if not (summary.get("preserve_previous_top20") and (out/"abcde_top20_summary.csv").exists()):
        write_csv(out/"abcde_strategy_ranking_master.csv", rankings, RANK_FIELDS)
        write_csv(out/"abcde_top20_summary.csv", top20, TOP_FIELDS)
        write_csv(out/"abcde_top50_summary.csv", top50, TOP_FIELDS)
    write_csv(out/"abcde_strategy_overlap_matrix.csv", overlaps, OVERLAP_FIELDS)
    write_csv(out/"abcde_strategy_latest_date_audit.csv", date_audit, DATE_FIELDS)
    write_csv(out/"abcde_coverage_audit.csv", coverage, COVERAGE_FIELDS)
    write_csv(out/"abcde_missing_ticker_audit.csv", missing, MISSING_FIELDS)
    write_csv(out/"abcde_feature_quality_audit.csv", quality, QUALITY_FIELDS)
    write_csv(out/"abcde_source_policy_audit.csv", source, SOURCE_FIELDS)
    write_csv(out/"abcde_canonical_snapshot_audit.csv", snap, SNAP_FIELDS)
    write_csv(out/"v21_231_snapshot_crosscheck.csv", cross, CROSS_FIELDS)
    write_csv(out/"v21_232_dram_crosscheck.csv", dram, CROSS_FIELDS)
    write_csv(out/"no_yfinance_enforcement_audit.csv", audit, AUDIT_FIELDS)
    write_json(out/"v21_233_summary.json", summary)
    compact=[f"{k}={summary.get(k)}" for k in ["final_status","final_decision","source_snapshot_id","canonical_latest_date","ranked_strategy_count","ranked_ticker_count","missing_ticker_count","warning_count","error_count"]]
    (out/"abcde_compact_report.txt").write_text("\n".join(compact)+"\n", encoding="utf-8")
    (out/"V21.233_moomoo_only_abcde_rerun_report.txt").write_text("\n".join([STAGE,*compact,"research_only=True","active_trading_focus=DRAM","broker_action_allowed=False","official_adoption_allowed=False"])+"\n", encoding="utf-8")
    return summary


def parse_args(argv: list[str] | None=None) -> argparse.Namespace:
    p=argparse.ArgumentParser(description=STAGE)
    p.add_argument("--repo-root",type=Path,default=default_repo_root())
    p.add_argument("--output-dir",type=Path,default=None)
    p.add_argument("--v21-231-output-dir",type=Path,default=None)
    p.add_argument("--v21-232-output-dir",type=Path,default=None)
    p.add_argument("--cache-root",type=Path,default=None)
    p.add_argument("--snapshot-id",default=None)
    p.add_argument("--top-n",type=int,default=50)
    return p.parse_args(argv)


def main(argv: list[str] | None=None) -> int:
    a=parse_args(argv); root=a.repo_root.resolve(); out=a.output_dir or root/OUT_REL
    s=run(root,out,a.v21_231_output_dir,a.v21_232_output_dir,a.cache_root,a.snapshot_id,a.top_n)
    print(str(out/"v21_233_summary.json"))
    return 1 if str(s["final_status"]).startswith("FAIL_") else 0


if __name__=="__main__":
    raise SystemExit(main())
