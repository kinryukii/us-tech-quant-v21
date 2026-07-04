#!/usr/bin/env python
"""V21.232 Moomoo-only DRAM daily and intraday research plan."""

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


STAGE = "V21.232_MOOMOO_ONLY_DRAM_DAILY_AND_INTRADAY_PLAN"
OUT_REL = Path("outputs/v21") / STAGE
V231_REL = Path("outputs/v21/V21.231_MOOMOO_ONLY_HISTORICAL_REFETCH_AND_CANONICAL_REBUILD")
PASS_STATUS = "PASS_V21_232_MOOMOO_ONLY_DRAM_PLAN_READY"
WARN_STATUS = "WARN_V21_232_MOOMOO_ONLY_DRAM_PLAN_READY_WITH_INDICATOR_WARNINGS"
FAIL_DATA = "FAIL_V21_232_DRAM_DATA_MISSING"
FAIL_POLICY = "FAIL_V21_232_SOURCE_POLICY_VIOLATION"
DECISION = "MOOMOO_ONLY_DRAM_PLAN_READY_RESEARCH_ONLY"
FORBIDDEN_PROVIDER = "y" + "finance"
FORBIDDEN_PROVIDER_CALL = "yf" + ".download"

DAILY_FIELDS = ["ticker","source_policy","snapshot_id","latest_price_date","latest_close","daily_return_1d","ma20","ma50","ema_short","ema_medium","rsi","macd","macd_signal","macd_hist","bb_mid","bb_upper","bb_lower","daily_trend_state","daily_risk_state","notes"]
INTRA_FIELDS = ["ticker","frequency","latest_timestamp","row_count","latest_close","rsi","kdj_k","kdj_d","kdj_j","macd","macd_signal","macd_hist","bb_mid","bb_upper","bb_lower","ma20","ma50","volume_state","volatility_state","signal_state","insufficient_indicator_count","notes"]
GATE_FIELDS = ["ticker","latest_1h_timestamp","latest_15m_timestamp","latest_1m_timestamp","one_hour_gate","fifteen_min_gate","one_min_gate","multiframe_gate","entry_allowed_research_only","chase_allowed_research_only","reason","notes"]
LEVEL_FIELDS = ["ticker","snapshot_id","latest_price_date","latest_intraday_timestamp","reference_price","entry","no_chase","stop","stop_pct","risk_reward_note","level_method","notes"]
NOCHASE_FIELDS = ["ticker","reference_price","no_chase","latest_intraday_price","no_chase_triggered","chase_allowed_research_only","reason","notes"]
STOP_FIELDS = ["ticker","reference_price","stop","stop_pct","risk_level","gap_risk_note","notes"]
SOURCE_AUDIT_FIELDS = ["artifact","path","source_policy","source","yfinance_used","yahoo_used","external_fallback_used","moomoo_used","pass","notes"]
SNAP_AUDIT_FIELDS = ["check_name","expected","actual","passed","severity","notes"]
CACHE_AUDIT_FIELDS = ["frequency","path","exists","row_count","latest_timestamp","source_policy","passed","notes"]
RISK_FIELDS = ["risk_event_type","moomoo_only_available","checked_in_v21_232","status","notes"]
TRADE_FIELDS = ["gate","allowed","reason","notes"]
CROSS_FIELDS = ["check_name","expected","actual","passed","severity","notes"]
AUDIT_FIELDS = ["check_name","passed","yfinance_import_present","yfinance_call_present","yahoo_default_allowed","external_fallback_default_allowed","notes"]


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
    path = repo_root / "scripts/v21/v21_232_moomoo_only_dram_daily_and_intraday_plan.py"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    imp = bool(re.search(r"(^|\n)\s*(import|from)\s+" + re.escape(FORBIDDEN_PROVIDER), text))
    call = FORBIDDEN_PROVIDER_CALL in text
    return ([{"check_name":"v21_232_script_forbidden_provider_audit","passed":bool_text(not imp and not call),"yfinance_import_present":bool_text(imp),"yfinance_call_present":bool_text(call),"yahoo_default_allowed":"False","external_fallback_default_allowed":"False","notes":"static audit"}], imp or call)


def source_gate(snapshot_id: str) -> dict[str, Any]:
    return {"policy_version":"V21.232","data_source_policy":"MOOMOO_ONLY","source_snapshot_id":snapshot_id,"yfinance_allowed":False,"yahoo_allowed":False,"external_fallback_allowed":False,"broker_action_allowed":False,"trade_unlock_allowed":False,"official_adoption_allowed":False,"research_only":True,"next_allowed_stage":"V21.233_MOOMOO_ONLY_ABCDE_RERUN"}


def to_float(x: Any) -> float | None:
    try:
        if x == "" or x is None:
            return None
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception:
        return None


def fmt(x: Any) -> str:
    if x == "INSUFFICIENT_BARS":
        return x
    v = to_float(x)
    return "" if v is None else f"{v:.4f}"


def series(rows: list[dict[str, Any]], key: str) -> list[float]:
    return [v for v in (to_float(r.get(key)) for r in rows) if v is not None]


def sma(vals: list[float], n: int) -> float | str:
    return sum(vals[-n:]) / n if len(vals) >= n else "INSUFFICIENT_BARS"


def ema(vals: list[float], n: int) -> float | str:
    if len(vals) < n:
        return "INSUFFICIENT_BARS"
    k = 2 / (n + 1); e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1 - k)
    return e


def rsi(vals: list[float], n: int = 14) -> float | str:
    if len(vals) <= n:
        return "INSUFFICIENT_BARS"
    gains=[]; losses=[]
    for a,b in zip(vals[-n-1:-1], vals[-n:]):
        d=b-a; gains.append(max(d,0)); losses.append(max(-d,0))
    avg_loss=sum(losses)/n
    if avg_loss == 0: return 100.0
    return 100 - 100/(1+(sum(gains)/n)/avg_loss)


def macd(vals: list[float]) -> tuple[Any, Any, Any]:
    if len(vals) < 35:
        return ("INSUFFICIENT_BARS",)*3
    diffs=[]
    for i in range(26, len(vals)+1):
        subset=vals[:i]
        diffs.append(float(ema(subset,12))-float(ema(subset,26)))
    sig = ema(diffs, 9)
    if sig == "INSUFFICIENT_BARS": return ("INSUFFICIENT_BARS",)*3
    m = diffs[-1]
    return m, sig, m-float(sig)


def bb(vals: list[float], n: int = 20) -> tuple[Any, Any, Any]:
    if len(vals) < n: return ("INSUFFICIENT_BARS",)*3
    sub=vals[-n:]; mid=sum(sub)/n; sd=(sum((x-mid)**2 for x in sub)/n)**0.5
    return mid, mid+2*sd, mid-2*sd


def kdj(rows: list[dict[str, Any]], n: int = 9) -> tuple[Any, Any, Any]:
    if len(rows) < n: return ("INSUFFICIENT_BARS",)*3
    k=d=50.0
    for i in range(n-1, len(rows)):
        win=rows[i-n+1:i+1]
        highs=series(win,"high"); lows=series(win,"low"); c=to_float(rows[i].get("close"))
        if not highs or not lows or c is None or max(highs)==min(lows): continue
        rsv=(c-min(lows))/(max(highs)-min(lows))*100
        k=2/3*k+1/3*rsv; d=2/3*d+1/3*k
    return k,d,3*k-2*d


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows = read_csv_rows(path)
    return sorted(rows, key=lambda r: r.get("date") or r.get("time_key") or "")


def indicator_row(ticker: str, freq: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    closes=series(rows,"close"); vols=series(rows,"volume")
    latest=rows[-1] if rows else {}
    m,s,h=macd(closes); bmid,bup,blo=bb(closes); kk,kd,kj=kdj(rows)
    vals={"rsi":rsi(closes),"kdj_k":kk,"kdj_d":kd,"kdj_j":kj,"macd":m,"macd_signal":s,"macd_hist":h,"bb_mid":bmid,"bb_upper":bup,"bb_lower":blo,"ma20":sma(closes,20),"ma50":sma(closes,50)}
    insuff=sum(1 for v in vals.values() if v=="INSUFFICIENT_BARS")
    ma20v=to_float(vals["ma20"]); ma50v=to_float(vals["ma50"]); close=to_float(latest.get("close"))
    signal="BULLISH" if close and ma20v and ma50v and close>ma20v>ma50v else "BEARISH" if close and ma20v and close<ma20v else "MIXED_OR_INSUFFICIENT"
    vol_state="INSUFFICIENT_BARS" if len(vols)<20 else ("ABOVE_AVG" if vols[-1] > sum(vols[-20:])/20 else "NORMAL")
    volat="INSUFFICIENT_BARS" if len(closes)<20 else fmt((max(closes[-20:])-min(closes[-20:]))/closes[-1])
    return {"ticker":ticker,"frequency":freq,"latest_timestamp":latest.get("date",""),"row_count":len(rows),"latest_close":fmt(close),"rsi":fmt(vals["rsi"]),"kdj_k":fmt(kk),"kdj_d":fmt(kd),"kdj_j":fmt(kj),"macd":fmt(m),"macd_signal":fmt(s),"macd_hist":fmt(h),"bb_mid":fmt(bmid),"bb_upper":fmt(bup),"bb_lower":fmt(blo),"ma20":fmt(vals["ma20"]),"ma50":fmt(vals["ma50"]),"volume_state":vol_state,"volatility_state":volat,"signal_state":signal,"insufficient_indicator_count":insuff,"notes":"Moomoo-only cached intraday indicators"}


def run(repo_root: Path, output_dir: Path, v21_231_output_dir: Path | None = None, cache_root: Path | None = None, snapshot_id: str | None = None) -> dict[str, Any]:
    repo_root=repo_root.resolve(); output_dir.mkdir(parents=True, exist_ok=True)
    v231_dir=(v21_231_output_dir or repo_root / V231_REL).resolve()
    pointer=read_json(v231_dir/"canonical_snapshot_pointer.json"); summary231=read_json(v231_dir/"v21_231_summary.json")
    snap=snapshot_id or pointer.get("snapshot_id","")
    croot=Path(cache_root or pointer.get("cache_root") or "")
    write_json(output_dir/"source_policy_gate.json", source_gate(snap))
    guard_found=(repo_root/"scripts/v21/v21_data_source_policy_guard.py").exists(); policy_ok=False
    try:
        guard=load_policy_guard(repo_root); guard.assert_moomoo_only_policy("V21.232 DRAM research only canonical dram abcde")
        pol=guard.load_data_source_policy(repo_root/"config/v21/data_source_policy.json")
        policy_ok=pol.get("default_data_source_policy")=="MOOMOO_ONLY" and pol.get("research_only") is True
    except Exception:
        policy_ok=False
    audit, violation = self_audit(repo_root)
    required=[v231_dir/n for n in ["v21_231_summary.json","canonical_snapshot_pointer.json","canonical_snapshot_pointer.csv","canonical_rebuild_manifest.csv","canonical_quality_audit.csv","ticker_coverage_audit.csv","dram_intraday_fetch_manifest.csv","source_policy_gate.json"]]
    cross=[]; input_ok=True
    for p in required:
        ex=p.exists(); input_ok=input_ok and ex
        cross.append({"check_name":p.name,"expected":"present","actual":"present" if ex else "missing","passed":bool_text(ex),"severity":"ERROR" if not ex else "INFO","notes":str(p)})
    source_ok=pointer.get("source_policy")=="MOOMOO_ONLY" and pointer.get("yfinance_used") is False and pointer.get("external_fallback_used") is False
    cross.append({"check_name":"source_policy","expected":"MOOMOO_ONLY/no fallback","actual":str(pointer.get("source_policy")),"passed":bool_text(source_ok),"severity":"ERROR" if not source_ok else "INFO","notes":"V21.231 pointer policy"})
    if not input_ok or not policy_ok or violation or not source_ok:
        status=FAIL_DATA if not input_ok else FAIL_POLICY if (violation or not policy_ok or not source_ok) else FAIL_DATA
        return write_all(output_dir, base_summary(status, repo_root, output_dir, croot, snap, pointer, False, {}, {}, 0, 0, 1), [], [], [], [], [], [], source_audits(pointer), snapshot_audits(pointer, summary231, input_ok, source_ok), [], risk_rows(), trade_rows(), cross, audit)
    daily_path=Path(pointer.get("canonical_qfq_path") or pointer.get("canonical_raw_path",""))
    daily=[r for r in load_rows(daily_path) if r.get("ticker")=="DRAM"]
    manifest=read_csv_rows(v231_dir/"dram_intraday_fetch_manifest.csv")
    intraday: dict[str,list[dict[str,Any]]]={}
    cache_audit=[]
    for freq in ["1m","5m","15m","1h"]:
        row=next((r for r in manifest if r.get("frequency")==freq),{})
        p=Path(row.get("cache_path","")); rows=load_rows(p) if p.exists() else []
        intraday[freq]=rows
        cache_audit.append({"frequency":freq,"path":str(p),"exists":bool_text(p.exists()),"row_count":len(rows),"latest_timestamp":rows[-1].get("date","") if rows else "","source_policy":"MOOMOO_ONLY","passed":bool_text(bool(rows)),"notes":"read-only cache audit"})
    if not daily or not any(intraday.values()):
        return write_all(output_dir, base_summary(FAIL_DATA, repo_root, output_dir, croot, snap, pointer, bool(daily), intraday, {}, 0, 1, 1), [], [], [], [], [], [], source_audits(pointer), snapshot_audits(pointer, summary231, input_ok, source_ok), cache_audit, risk_rows(), trade_rows(), cross, audit)
    closes=series(daily,"close"); latest=daily[-1]
    m,ms,mh=macd(closes); bmid,bup,blo=bb(closes)
    ma20=sma(closes,20); ma50=sma(closes,50); e12=ema(closes,12); e26=ema(closes,26)
    latest_close=to_float(latest.get("close")) or 0.0
    daily_ret="" if len(closes)<2 else (closes[-1]/closes[-2]-1)
    trend="BULLISH" if to_float(ma20) and to_float(ma50) and latest_close>float(ma20)>float(ma50) else "BEARISH" if to_float(ma20) and latest_close<float(ma20) else "MIXED_OR_INSUFFICIENT"
    risk="ELEVATED" if to_float(rsi(closes)) and float(rsi(closes))>70 else "NORMAL_OR_INSUFFICIENT"
    daily_plan=[{"ticker":"DRAM","source_policy":"MOOMOO_ONLY","snapshot_id":snap,"latest_price_date":latest.get("date",""),"latest_close":fmt(latest_close),"daily_return_1d":fmt(daily_ret),"ma20":fmt(ma20),"ma50":fmt(ma50),"ema_short":fmt(e12),"ema_medium":fmt(e26),"rsi":fmt(rsi(closes)),"macd":fmt(m),"macd_signal":fmt(ms),"macd_hist":fmt(mh),"bb_mid":fmt(bmid),"bb_upper":fmt(bup),"bb_lower":fmt(blo),"daily_trend_state":trend,"daily_risk_state":risk,"notes":"research-only DRAM daily plan"}]
    intra_rows=[indicator_row("DRAM",f,intraday[f]) for f in ["1m","5m","15m","1h"]]
    indicator_warnings=sum(int(r["insufficient_indicator_count"]) for r in intra_rows) + sum(1 for v in [ma20,ma50,e12,e26,rsi(closes),m,bmid] if v=="INSUFFICIENT_BARS")
    latest_intra=max([r["latest_timestamp"] for r in intra_rows if r["latest_timestamp"]] or [""])
    sig={r["frequency"]:r["signal_state"] for r in intra_rows}
    one="PASS" if sig.get("1h")=="BULLISH" else "WARN"
    fifteen="PASS" if sig.get("15m")=="BULLISH" else "WARN"
    one_min="PASS" if sig.get("1m")=="BULLISH" else "WARN"
    multi="PASS" if one==fifteen==one_min=="PASS" else "WAIT_FOR_CONFIRMATION"
    gate=[{"ticker":"DRAM","latest_1h_timestamp":next((r["latest_timestamp"] for r in intra_rows if r["frequency"]=="1h"),""),"latest_15m_timestamp":next((r["latest_timestamp"] for r in intra_rows if r["frequency"]=="15m"),""),"latest_1m_timestamp":next((r["latest_timestamp"] for r in intra_rows if r["frequency"]=="1m"),""),"one_hour_gate":one,"fifteen_min_gate":fifteen,"one_min_gate":one_min,"multiframe_gate":multi,"entry_allowed_research_only":bool_text(multi=="PASS"),"chase_allowed_research_only":"False","reason":"1h -> 15m -> 1m confirmation required","notes":"research-only; no broker action"}]
    low20 = min(series(daily[-20:],"low")) if len(daily)>=20 else latest_close*0.94
    entry=round(latest_close*1.005,4); no_chase=round(latest_close*1.035,4); stop=round(min(low20, latest_close*0.94),4); stop_pct=round((stop/latest_close)-1,4) if latest_close else 0
    levels=[{"ticker":"DRAM","snapshot_id":snap,"latest_price_date":latest.get("date",""),"latest_intraday_timestamp":latest_intra,"reference_price":fmt(latest_close),"entry":fmt(entry),"no_chase":fmt(no_chase),"stop":fmt(stop),"stop_pct":fmt(stop_pct),"risk_reward_note":"pre-planned levels only","level_method":"latest_close_plus_no_chase_and_recent_low_stop","notes":"research-only"}]
    latest_intraday_price=to_float(next((r for r in intra_rows if r["frequency"]=="1m"),intra_rows[0])["latest_close"]) or latest_close
    nochase=[{"ticker":"DRAM","reference_price":fmt(latest_close),"no_chase":fmt(no_chase),"latest_intraday_price":fmt(latest_intraday_price),"no_chase_triggered":bool_text(latest_intraday_price>no_chase),"chase_allowed_research_only":"False","reason":"never chase above no_chase level","notes":"research-only"}]
    stops=[{"ticker":"DRAM","reference_price":fmt(latest_close),"stop":fmt(stop),"stop_pct":fmt(stop_pct),"risk_level":"ELEVATED" if stop_pct < -0.08 else "NORMAL","gap_risk_note":"review at next pre-market plan","notes":"no broker action"}]
    data_warn=sum(1 for r in cache_audit if r["passed"]!="True")
    quality=0; status=WARN_STATUS if indicator_warnings else PASS_STATUS
    summary=base_summary(status, repo_root, output_dir, croot, snap, pointer, True, intraday, levels[0], indicator_warnings, data_warn, quality, latest.get("date",""), latest_intra, trend, multi)
    summary["daily_row_count"] = len(daily)
    return write_all(output_dir, summary, daily_plan, intra_rows, gate, levels, nochase, stops, source_audits(pointer), snapshot_audits(pointer, summary231, input_ok, source_ok), cache_audit, risk_rows(), trade_rows(), cross, audit)


def source_audits(pointer: dict[str,Any]) -> list[dict[str,Any]]:
    return [{"artifact":"canonical_snapshot_pointer","path":pointer.get("canonical_snapshot_dir",""),"source_policy":pointer.get("source_policy",""),"source":pointer.get("source",""),"yfinance_used":bool_text(bool(pointer.get("yfinance_used"))),"yahoo_used":bool_text(bool(pointer.get("yahoo_used"))),"external_fallback_used":bool_text(bool(pointer.get("external_fallback_used"))),"moomoo_used":bool_text(pointer.get("source")=="MOOMOO_OPEND"),"pass":bool_text(pointer.get("source_policy")=="MOOMOO_ONLY" and not pointer.get("yfinance_used") and not pointer.get("external_fallback_used")),"notes":"read-only source audit"}]


def snapshot_audits(pointer:dict[str,Any], s231:dict[str,Any], input_ok:bool, source_ok:bool)->list[dict[str,Any]]:
    return [{"check_name":"v21_231_inputs","expected":"present","actual":bool_text(input_ok),"passed":bool_text(input_ok),"severity":"ERROR" if not input_ok else "INFO","notes":""},{"check_name":"source_policy","expected":"MOOMOO_ONLY","actual":pointer.get("source_policy",""),"passed":bool_text(source_ok),"severity":"ERROR" if not source_ok else "INFO","notes":""},{"check_name":"quality_error_count","expected":"0","actual":s231.get("quality_error_count",""),"passed":bool_text(str(s231.get("quality_error_count",""))=="0"),"severity":"ERROR","notes":"V21.231 quality gate"}]


def risk_rows()->list[dict[str,Any]]:
    return [{"risk_event_type":t,"moomoo_only_available":"False","checked_in_v21_232":"False","status":"PLACEHOLDER_ONLY","notes":"no event fetch in V21.232"} for t in ["earnings","corporate_action","risk_event"]]


def trade_rows()->list[dict[str,Any]]:
    return [{"gate":"broker_action_allowed","allowed":"False","reason":"research-only stage","notes":"no orders"},{"gate":"trade_unlock_allowed","allowed":"False","reason":"forbidden","notes":"no unlock"},{"gate":"official_adoption_allowed","allowed":"False","reason":"research-only","notes":"no adoption"}]


def base_summary(status:str, repo_root:Path, out:Path, cache:Path, snap:str, pointer:dict[str,Any], daily_found:bool, intra:dict[str,list], level:dict[str,Any], iw:int, dw:int, qe:int, latest_price:str="", latest_intra:str="", trend:str="", multi:str="")->dict[str,Any]:
    return {"final_status":status,"final_decision":DECISION,"repo_root":str(repo_root),"output_dir":str(out),"cache_root":str(cache),"source_snapshot_id":snap,"canonical_snapshot_dir":pointer.get("canonical_snapshot_dir",""),"latest_price_date":latest_price,"latest_intraday_timestamp":latest_intra,"daily_data_found":daily_found,"intraday_1m_found":bool(intra.get("1m")),"intraday_5m_found":bool(intra.get("5m")),"intraday_15m_found":bool(intra.get("15m")),"intraday_1h_found":bool(intra.get("1h")),"daily_row_count":0 if not daily_found else -1,"intraday_1m_row_count":len(intra.get("1m",[])),"intraday_5m_row_count":len(intra.get("5m",[])),"intraday_15m_row_count":len(intra.get("15m",[])),"intraday_1h_row_count":len(intra.get("1h",[])),"entry":level.get("entry",""),"no_chase":level.get("no_chase",""),"stop":level.get("stop",""),"daily_trend_state":trend,"multiframe_gate":multi,"trade_plan_currentness":"CURRENT" if latest_price else "MISSING","data_currentness":"CURRENT" if latest_intra else "MISSING","indicator_warning_count":iw,"data_warning_count":dw,"quality_error_count":qe,"yfinance_used":False,"yahoo_used":False,"external_fallback_used":False,"moomoo_used":True,"broker_action_allowed":False,"trade_unlock_used":False,"official_adoption_allowed":False,"research_only":True,"warning_count":iw+dw,"error_count":1 if status.startswith("FAIL_") else 0}


def write_all(out:Path, summary:dict[str,Any], daily,intra,gate,levels,nochase,stops,source,snap,cache,risk,trade,cross,audit)->dict[str,Any]:
    write_csv(out/"dram_daily_plan.csv", daily, DAILY_FIELDS)
    write_csv(out/"dram_intraday_signal_audit.csv", intra, INTRA_FIELDS)
    write_csv(out/"dram_intraday_multiframe_gate.csv", gate, GATE_FIELDS)
    write_csv(out/"dram_entry_exit_levels.csv", levels, LEVEL_FIELDS)
    write_csv(out/"dram_no_chase_gate.csv", nochase, NOCHASE_FIELDS)
    write_csv(out/"dram_stop_risk_plan.csv", stops, STOP_FIELDS)
    write_csv(out/"dram_data_source_audit.csv", source, SOURCE_AUDIT_FIELDS)
    write_csv(out/"dram_canonical_snapshot_audit.csv", snap, SNAP_AUDIT_FIELDS)
    write_csv(out/"dram_intraday_cache_audit.csv", cache, CACHE_AUDIT_FIELDS)
    write_csv(out/"dram_risk_event_placeholder_audit.csv", risk, RISK_FIELDS)
    write_csv(out/"dram_trade_permission_gate.csv", trade, TRADE_FIELDS)
    write_csv(out/"v21_231_snapshot_crosscheck.csv", cross, CROSS_FIELDS)
    write_csv(out/"no_yfinance_enforcement_audit.csv", audit, AUDIT_FIELDS)
    write_json(out/"v21_232_summary.json", summary)
    keys=["final_status","final_decision","source_snapshot_id","latest_price_date","latest_intraday_timestamp","entry","no_chase","stop","daily_trend_state","multiframe_gate","warning_count","error_count"]
    (out/"V21.232_moomoo_only_dram_daily_and_intraday_plan_report.txt").write_text("\n".join([STAGE,*[f"{k}={summary.get(k)}" for k in keys],"research_only=True","broker_action_allowed=False","trade_unlock_used=False"])+"\n",encoding="utf-8")
    return summary


def parse_args(argv: list[str] | None=None)->argparse.Namespace:
    p=argparse.ArgumentParser(description=STAGE)
    p.add_argument("--repo-root",type=Path,default=default_repo_root())
    p.add_argument("--output-dir",type=Path,default=None)
    p.add_argument("--v21-231-output-dir",type=Path,default=None)
    p.add_argument("--cache-root",type=Path,default=None)
    p.add_argument("--snapshot-id",default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None=None)->int:
    a=parse_args(argv); root=a.repo_root.resolve(); out=a.output_dir or root/OUT_REL
    s=run(root,out,a.v21_231_output_dir,a.cache_root,a.snapshot_id)
    print(str(out/"v21_232_summary.json"))
    return 1 if str(s["final_status"]).startswith("FAIL_") else 0


if __name__=="__main__":
    raise SystemExit(main())
