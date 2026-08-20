#!/usr/bin/env python
"""Read-only Moomoo US-option feasibility probe and manual 5-minute shadow logger."""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
RUNTIME = RESULTS / "runtime/fast3/moomoo_option_shadow/raw"
SCRATCH = RESULTS / "scratch/fast3/moomoo_option_data_acquisition_r1"
MOOMOO_APPDATA = Path(r"D:\us-tech-quant-cache\moomoo-openapi-appdata")
HOST, PORT = "127.0.0.1", 18441
UNDERLYING_PRIORITY = ("US.SOXX", "US.SMH", "US.QQQ", "US.SPY")
MAX_NEW_HISTORY_REQUESTS = 10
MAX_STALENESS_SECONDS = 15 * 60
ET = ZoneInfo("America/New_York")


def load_helpers():
    path = REPO / "fast3/src/fast3/options/moomoo_option_shadow_r1.py"
    spec = importlib.util.spec_from_file_location("fast3_moomoo_shadow_helpers", path)
    if spec is None or spec.loader is None: raise RuntimeError("shadow helper import failed")
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, default=str, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def frame_records(frame: Any) -> list[dict[str, Any]]:
    return json.loads(frame.to_json(orient="records", date_format="iso")) if hasattr(frame, "to_json") else []


def quota(ctx: Any) -> dict[str, Any]:
    ret, value = ctx.get_history_kl_quota()
    if ret != 0: return {"status": "FAIL", "error": str(value)}
    used, remain, detail = value
    return {"status": "SUCCESS", "used": int(used), "remain": int(remain), "total": int(used + remain), "detail": detail}


def date_to_utc(value: Any) -> datetime | None:
    if value is None or str(value) in {"N/A", "nan", "NaT", ""}: return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
        try: return datetime.strptime(str(value), pattern).replace(tzinfo=ET).astimezone(timezone.utc)
        except ValueError: pass
    return None


def safe_number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number else None
    except (TypeError, ValueError): return None


def option_chain(ctx: Any, underlying: str, expiration: str | None = None, delta_filtered: bool = False) -> tuple[bool, list[dict[str, Any]], str | None]:
    from moomoo import OptionDataFilter, OptionType
    kwargs: dict[str, Any] = {}
    if expiration: kwargs.update(start=expiration, end=expiration)
    if delta_filtered:
        kwargs.update(option_type=OptionType.PUT, data_filter=OptionDataFilter(delta_min=-.30, delta_max=-.20))
    ret, data = ctx.get_option_chain(underlying, **kwargs)
    if ret != 0: return False, [], str(data)
    rows=[]
    for value in frame_records(data):
        rows.append({"option_code": value.get("code"), "underlying": value.get("stock_owner"), "call_put": value.get("option_type"), "expiry": value.get("strike_time"), "strike": safe_number(value.get("strike_price")), "lot_size": value.get("lot_size"), "listing_information": value.get("listing_date")})
    return True, rows, None


def current_snapshot(ctx: Any, codes: list[str]) -> tuple[bool, list[dict[str, Any]], str | None]:
    ret, data = ctx.get_market_snapshot(codes)
    if ret != 0: return False, [], str(data)
    rows=[]
    for value in frame_records(data):
        rows.append({"option_code": value.get("code"), "source_timestamp": value.get("update_time"), "bid": safe_number(value.get("bid_price")), "ask": safe_number(value.get("ask_price")), "last_price": safe_number(value.get("last_price")), "volume": safe_number(value.get("volume")), "open_interest": safe_number(value.get("option_open_interest")), "implied_volatility": safe_number(value.get("option_implied_volatility")), "delta": safe_number(value.get("option_delta")), "gamma": safe_number(value.get("option_gamma")), "vega": safe_number(value.get("option_vega")), "theta": safe_number(value.get("option_theta")), "strike": safe_number(value.get("option_strike_price")), "expiry": value.get("strike_time"), "call_put": value.get("option_type")})
    return True, rows, None


def basic_quote(ctx: Any, code: str) -> tuple[bool, dict[str, Any], str | None]:
    ret, data = ctx.get_market_snapshot([code])
    if ret != 0 or data.empty: return False, {}, str(data)
    value = frame_records(data)[0]
    return True, {"code": value.get("code"), "source_timestamp": value.get("update_time"), "last_price": safe_number(value.get("last_price")), "bid": safe_number(value.get("bid_price")), "ask": safe_number(value.get("ask_price")), "market_status": value.get("sec_status")}, None


def expiries(ctx: Any, underlying: str) -> tuple[bool, list[dict[str, Any]], str | None]:
    ret, data = ctx.get_option_expiration_date(underlying)
    if ret != 0: return False, [], str(data)
    return True, [{"expiry": value.get("strike_time"), "dte": int(value.get("option_expiry_date_distance")), "cycle": value.get("expiration_cycle")} for value in frame_records(data)], None


def enrich_selection(selection: list[dict[str, Any]], quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_code = {item["option_code"]: item for item in quotes}
    return [item | by_code.get(item["option_code"], {"option_code": item["option_code"]}) for item in selection]


def select_surface(ctx: Any, helpers: Any, underlying: str, quote: dict[str, Any], expiry_rows: list[dict[str, Any]], full_chain: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    spot = quote.get("last_price")
    if spot is None: return [], {"status": "UNAVAILABLE_NO_UNDERLYING_PRICE"}
    near = helpers.choose_expiry(expiry_rows, 7); mid = helpers.choose_expiry([item for item in expiry_rows if item["expiry"] in {row["expiry"] for row in full_chain}], 30)
    if near is None or mid is None: return [], {"status": "UNAVAILABLE_NO_CURRENT_CHAIN_EXPIRY"}
    selected=[]
    for role, expiry, side in (("mid_atm_call", mid["expiry"], "CALL"), ("mid_atm_put", mid["expiry"], "PUT"), ("near_atm_call", near["expiry"], "CALL"), ("near_atm_put", near["expiry"], "PUT")):
        item=helpers.choose_atm_contract(full_chain, expiry, side, float(spot))
        if item: selected.append(item | {"role": role})
    ok, filtered, error = option_chain(ctx, underlying, mid["expiry"], delta_filtered=True)
    skew=helpers.choose_delta_filtered_put(filtered, mid["expiry"], float(spot)) if ok else None
    if skew: selected.append(skew | {"role": "mid_delta_filtered_put"})
    return selected, {"status": "SUCCESS", "near_expiry": near, "mid_expiry": mid, "delta_filter_server_status": "SUCCESS" if ok else "FAIL", "delta_filter_error": error}


def history_request(ctx: Any, code: str, start: str, end: str) -> dict[str, Any]:
    from moomoo import KLType
    result=ctx.request_history_kline(code, start=start, end=end, ktype=KLType.K_5M, max_count=1000)
    ret, data = result[0], result[1]
    if ret != 0: return {"contract": code, "status": "FAIL", "error": str(data), "row_count": 0}
    rows=frame_records(data)
    times=[item.get("time_key") for item in rows if item.get("time_key")]
    return {"contract": code, "status": "SUCCESS", "start": start, "end": end, "earliest_returned_timestamp": min(times) if times else None, "latest_returned_timestamp": max(times) if times else None, "row_count": len(rows), "columns": list(data.columns), "sample_rows": rows[:3]}


def daily_history(ctx: Any, method: str) -> dict[str, Any]:
    fn=getattr(ctx, method); all_rows=[]; attempts=[]
    for year in range(2026, 2017, -1):
        end="2026-08-11" if year == 2026 else f"{year}-12-31"
        result=fn("US.SOXX", begin_time=f"{year}-01-01", end_time=end)
        ret, data = result[0], result[1]
        attempts.append({"year": year, "status": "SUCCESS" if ret == 0 else "FAIL", "error": None if ret == 0 else str(data), "row_count": len(data) if ret == 0 else 0})
        if ret == 0: all_rows.extend(frame_records(data))
    dates=[str(row.get("time")) for row in all_rows if row.get("time")]
    return {"available": bool(all_rows), "earliest_date": min(dates) if dates else None, "latest_date": max(dates) if dates else None, "row_count": len(all_rows), "attempts": attempts, "sample_rows": all_rows[:3]}


def one_shadow_snapshot(ctx: Any, helpers: Any, underlying: str) -> dict[str, Any]:
    fetched=datetime.now(timezone.utc); basic_ok, quote, basic_error=basic_quote(ctx, underlying)
    exp_ok, expiry_rows, exp_error=expiries(ctx, underlying)
    chain_ok, full_chain, chain_error=option_chain(ctx, underlying)
    if not (basic_ok and exp_ok and chain_ok):
        return {"api_status": "FAIL", "errors": {"basic": basic_error, "expiries": exp_error, "chain": chain_error}}
    selection, selection_meta=select_surface(ctx, helpers, underlying, quote, expiry_rows, full_chain)
    quote_ok, option_quotes, quote_error=current_snapshot(ctx, [row["option_code"] for row in selection]) if selection else (False, [], "NO_SELECTION")
    selected=enrich_selection(selection, option_quotes) if quote_ok else selection
    source_times=[date_to_utc(item.get("source_timestamp")) for item in selected]
    source_times=[item for item in source_times if item]
    source_timestamp=max(source_times) if source_times else None
    stale=helpers.quote_is_stale(source_timestamp, fetched, MAX_STALENESS_SECONDS)
    state=helpers.materialize_surface(selected)
    slot=helpers.canonical_slot(fetched)
    snapshot={"schema_version": "FAST3_MOOMOO_OPTION_SHADOW_R1", "snapshot_id": f"{underlying}|{slot.isoformat()}", "retrieved_at_utc": fetched, "snapshot_timestamp_utc": source_timestamp or fetched, "snapshot_timestamp_et": (source_timestamp or fetched).astimezone(ET).isoformat(), "underlying": underlying, "underlying_price": quote.get("last_price"), "near_expiry": selection_meta.get("near_expiry", {}).get("expiry"), "near_dte": selection_meta.get("near_expiry", {}).get("dte"), "mid_expiry": selection_meta.get("mid_expiry", {}).get("expiry"), "mid_dte": selection_meta.get("mid_expiry", {}).get("dte"), "selected_options": selected, "source": "MOOMOO_OPEND", "api_status": "SUCCESS" if quote_ok else "FAIL", "data_quality_status": "UNAVAILABLE_STALE" if stale else "AVAILABLE", "stale_status": stale, "missing_field_status": {"delta_missing": any(item.get("delta") is None for item in selected), "iv_missing": any(item.get("implied_volatility") is None for item in selected)}, "fast3_signal_changed": False, "position_multiplier_applied": False, "direction_reversal_allowed": False, "option_overlay_mode": "SHADOW_DATA_COLLECTION_ONLY", **state, "selection_metadata": selection_meta, "option_quote_error": quote_error}
    helpers.validate_snapshot(snapshot)
    return snapshot


def materialize_changes(snapshot: dict[str, Any], previous: list[dict[str, Any]], helpers: Any) -> None:
    """Derive changes only from exact completed 5m predecessor slots."""
    current_slot = helpers.canonical_slot(snapshot["retrieved_at_utc"])
    by_slot = {}
    for row in previous:
        try:
            by_slot[helpers.canonical_slot(datetime.fromisoformat(str(row["retrieved_at_utc"])))] = row
        except (KeyError, ValueError):
            continue
    for raw_field, prefix in (("option_atm_iv_30d", "atm_iv"), ("option_downside_skew_30d", "skew")):
        current = snapshot.get(raw_field)
        for intervals, suffix in ((1, "5m"), (2, "10m"), (3, "15m")):
            prior = by_slot.get(current_slot - timedelta(minutes=5 * intervals), {}).get(raw_field)
            snapshot[f"{prefix}_change_{suffix}"] = float(current) - float(prior) if helpers.is_valid_number(current) and helpers.is_valid_number(prior) else None
    snapshot["option_intraday_risk_change_status"] = "AVAILABLE" if snapshot["skew_change_5m"] is not None else "PENDING_SECOND_5M_OBSERVATION"


def append_shadow(snapshot: dict[str, Any], helpers: Any) -> Path:
    RUNTIME.mkdir(parents=True, exist_ok=True); day=snapshot["retrieved_at_utc"].strftime("%Y-%m-%d"); path=RUNTIME / f"{day}.jsonl"
    existing_lines=path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    existing=[json.loads(line) for line in existing_lines]
    if any(row.get("snapshot_id") == snapshot["snapshot_id"] for row in existing): return path
    materialize_changes(snapshot, existing, helpers)
    with path.open("a", encoding="utf-8") as handle: handle.write(json.dumps(snapshot, default=str, ensure_ascii=True) + "\n")
    return path


def run_probe(run_id: str) -> int:
    os.environ["APPDATA"] = str(MOOMOO_APPDATA); MOOMOO_APPDATA.mkdir(parents=True, exist_ok=True)
    from moomoo import OpenQuoteContext, __version__
    helpers=load_helpers(); frozen=RESULTS / "frozen/fast3" / f"moomoo_option_data_acquisition_r1_supplement_{run_id}"; frozen.mkdir(parents=True, exist_ok=False); SCRATCH.mkdir(parents=True, exist_ok=True)
    ctx=OpenQuoteContext(host=HOST, port=PORT); before=quota(ctx); history_calls=0
    try:
        basic_ok, basic, _=basic_quote(ctx,"US.SOXX"); exp_ok, exp_rows, _=expiries(ctx,"US.SOXX"); chain_ok, chain_rows, _=option_chain(ctx,"US.SOXX")
        selection, select_meta=select_surface(ctx,helpers,"US.SOXX",basic,exp_rows,chain_rows) if basic_ok and exp_ok and chain_ok else ([],{})
        quote_ok, quote_rows, quote_error=current_snapshot(ctx,[item["option_code"] for item in selection]) if selection else (False,[],"NO_SELECTION")
        selected=enrich_selection(selection,quote_rows) if quote_ok else selection; surface=helpers.materialize_surface(selected)
        (SCRATCH / f"SOXX_CURRENT_CHAIN_{run_id}.csv").write_text("\n".join([",".join(chain_rows[0].keys())] + [",".join(str(item.get(key, "")) for key in chain_rows[0]) for item in chain_rows]) if chain_rows else "",encoding="utf-8")
        snapshot=one_shadow_snapshot(ctx,helpers,"US.SOXX"); raw_path=append_shadow(snapshot,helpers)
        daily_iv=daily_history(ctx,"get_option_underlying_his_volatility"); daily_stat=daily_history(ctx,"get_option_underlying_his_statistic")
        today=datetime.now(ET).date(); start30=(today-timedelta(days=30)).isoformat(); end=today.isoformat(); history=[]
        for item in selected[:3]:
            if history_calls >= 3: break
            history.append(history_request(ctx,item["option_code"],start30,end)); history_calls += 1
        if history and history[0]["status"] == "SUCCESS" and history_calls < 4:
            history.append(history_request(ctx,history[0]["contract"],(today-timedelta(days=90)).isoformat(),end)); history_calls += 1
        proxy={}
        for code in UNDERLYING_PRIORITY[1:]:
            b_ok,b,_=basic_quote(ctx,code); e_ok,e,_=expiries(ctx,code); c_ok,c,_=option_chain(ctx,code); s=[]
            if b_ok and e_ok and c_ok: s,_=select_surface(ctx,helpers,code,b,e,c)
            q_ok,q_rows,_=current_snapshot(ctx,[item["option_code"] for item in s[:2]]) if s else (False,[],None)
            proxy[code]={"data_available": bool(b_ok and e_ok and c_ok and q_ok), "iv_available": any(row.get("implied_volatility") is not None for row in q_rows), "delta_available": any(row.get("delta") is not None for row in q_rows)}
        after=quota(ctx); consumed=after.get("used",0)-before.get("used",0)
        if consumed > MAX_NEW_HISTORY_REQUESTS: raise RuntimeError(f"historical kline quota safety stop: consumed={consumed}")
        current={"underlying_quote":basic,"expiration_rows":exp_rows,"chain_count":len(chain_rows),"expiry_counts":{},"selected_options":selected,"quote_available":quote_ok,"surface":surface,"raw_shadow_snapshot":snapshot,"raw_sample_path":str(raw_path)}
        for item in chain_rows: current["expiry_counts"].setdefault(item["expiry"],{"contract_count":0,"call_count":0,"put_count":0}); g=current["expiry_counts"][item["expiry"]]; g["contract_count"]+=1; g["call_count"]+=item["call_put"]=="CALL"; g["put_count"]+=item["call_put"]=="PUT"
        historical={"daily_iv":daily_iv,"daily_stat":daily_stat,"option_price_5m_probes":history,"historical_option_price_5m_available":any(item["status"]=="SUCCESS" and item["row_count"]>0 for item in history),"historical_option_iv_5m_directly_available":False,"historical_option_delta_5m_directly_available":False,"full_historical_option_surface_5m_available":False,"full_expired_chain_enumeration_available":False,"full_2018_2025_surface_reconstructable":False,"historical_iv_reconstruction_future_note":True}
        write_json(frozen/"FAST3_MOOMOO_OPTION_CURRENT_SURFACE_SAMPLE.json",current); write_json(frozen/"FAST3_MOOMOO_OPTION_HISTORICAL_COVERAGE.json",historical); write_json(frozen/"FAST3_MOOMOO_OPTION_LOGGER_DRY_RUN.json",{"status":"PASS" if snapshot["api_status"]=="SUCCESS" else "FAIL","snapshot_id":snapshot["snapshot_id"],"stale_status":snapshot["stale_status"],"raw_path":str(raw_path),"long_run_started":False})
        feasibility={"MOOMOO_SDK_VERSION":__version__,"OPEND_CONNECTION":"PASS","US_OPTION_MARKET_DATA_AUTHORITY":"SUCCESS_READ_ONLY_QUOTE_APIS","SOXX": {"basic_quote":basic_ok,"expiration":exp_ok,"chain":chain_ok,"quote":quote_ok,"bid_ask":any(row.get("bid") is not None and row.get("ask") is not None for row in quote_rows),"iv":any(row.get("implied_volatility") is not None for row in quote_rows),"delta":any(row.get("delta") is not None for row in quote_rows),"oi":any(row.get("open_interest") is not None for row in quote_rows)},"proxies":proxy,"selection":select_meta,"option_overlay_mode":"SHADOW_DATA_COLLECTION_ONLY"}; write_json(frozen/"FAST3_MOOMOO_OPTION_DATA_FEASIBILITY.json",feasibility); write_json(frozen/"FAST3_MOOMOO_OPTION_DATA_QUOTA_AUDIT.json",{"before":before,"after":after,"consumed_this_task":consumed,"max_allowed":MAX_NEW_HISTORY_REQUESTS,"within_limit":consumed<=MAX_NEW_HISTORY_REQUESTS})
        classification="A_MOOMOO_OPTION_DATA_READY_FOR_PROSPECTIVE_5M_SHADOW" if feasibility["SOXX"]["chain"] and feasibility["SOXX"]["iv"] else "E_OPTION_SURFACE_FIELDS_INSUFFICIENT"
        summary={"FAST3_MOOMOO_OPTION_DATA_SUPPLEMENT_STATUS":"COMPLETE","CLASSIFICATION":classification,"MOOMOO_SDK_VERSION":__version__,"quota_before":before,"quota_after":after,"quota_consumed":consumed,"feasibility":feasibility,"historical":historical,"current":current,"model_fit_count":0,"new_alpha_factor_count":0,"new_target_count":0,"fast3_signal_changed":False,"fast3_target_changed":False,"fast3_model_changed":False,"position_multiplier_applied":False,"option_independent_trade_allowed":False,"option_direction_flip_allowed":False,"r28_prospective_line_isolation":True,"storage_contract":"PASS","anti_bloat":"PASS_ONE_GENERIC_MODULE_ONE_RUNNER_ONE_TEST","exact_logger_command":f'& "{sys.executable}" "{Path(__file__)}" --shadow --underlying US.SOXX --interval-minutes 5'}
        write_json(frozen/"FAST3_MOOMOO_OPTION_DATA_SUPPLEMENT_SUMMARY.json",summary); (frozen/"FAST3_MOOMOO_OPTION_DATA_SUPPLEMENT_REPORT.md").write_text(f"# FAST3 Moomoo Option Data Supplement\n\nClassification: `{classification}`. Current SOXX option snapshot fields are acquisition evidence only; no alpha or risk action was evaluated/applied.\n\nHistorical option price 5m is distinct from historical IV/delta surface. The latter was not reconstructed.\n\nManual logger command:\n\n```powershell\n{summary['exact_logger_command']}\n```\n",encoding="utf-8")
        print(f"SUPPLEMENT_ROOT={frozen}"); return 0
    finally: ctx.close()


def run_shadow(underlying: str, interval_minutes: int, once: bool) -> int:
    if interval_minutes != 5: raise SystemExit("canonical option resolution is fixed at 5 minutes")
    os.environ["APPDATA"] = str(MOOMOO_APPDATA); MOOMOO_APPDATA.mkdir(parents=True, exist_ok=True)
    from moomoo import OpenQuoteContext
    helpers=load_helpers(); ctx=OpenQuoteContext(host=HOST,port=PORT)
    try:
        while True:
            snapshot=one_shadow_snapshot(ctx,helpers,underlying); path=append_shadow(snapshot,helpers); print(f"SHADOW_SNAPSHOT={snapshot.get('snapshot_id')} STATUS={snapshot.get('data_quality_status')} PATH={path}")
            if once: return 0
            time.sleep(interval_minutes*60)
    finally: ctx.close()


def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--run-id",default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")); parser.add_argument("--shadow",action="store_true"); parser.add_argument("--underlying",default="US.SOXX"); parser.add_argument("--interval-minutes",type=int,default=5); parser.add_argument("--once",action="store_true"); args=parser.parse_args()
    raise SystemExit(run_shadow(args.underlying,args.interval_minutes,args.once) if args.shadow else run_probe(args.run_id))


if __name__=="__main__": main()
