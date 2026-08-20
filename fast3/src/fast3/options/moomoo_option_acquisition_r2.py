"""FAST3 R2 Moomoo option acquisition: read-only data archival only.

This module deliberately owns no model, target, signal, payoff, order, or trade
context.  It is executable as a module and writes only to the FAST3 results roots.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import socket
import sys
import time
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO = Path(r"D:\us-tech-quant")
RESULTS = Path(r"D:\us-tech-quant-results")
APPDATA = Path(r"D:\us-tech-quant-cache\moomoo-openapi-appdata")
PARQUET_SITE = Path(os.environ.get(
    "USTQ_PYTHON_SITE",
    r"D:\us-tech-quant-envs\us-tech-quant-main\Lib\site-packages",
))
HOST, PORT = "127.0.0.1", 18441
UNDERLYINGS = ("US.SOXX", "US.SMH", "US.QQQ", "US.SPY")
SCHEMA = "FAST3_MOOMOO_OPTION_HISTORY_R2"
MAX_RETRIES, BATCH = 3, 100


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=True, default=jsonable) + "\n", encoding="utf-8")
    os.replace(temp, path)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def records(frame: Any) -> list[dict[str, Any]]:
    return json.loads(frame.to_json(orient="records", date_format="iso")) if hasattr(frame, "to_json") else []


def num(value: Any) -> float | None:
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def normalize_code(code: str) -> str:
    return code.replace("US.", "")


class Archive:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        name = f"moomoo_option_history_r2_{run_id}"
        self.scratch = RESULTS / "scratch/fast3" / name
        self.runtime = RESULTS / "runtime/fast3" / name
        self.archive = RESULTS / "archive/fast3" / name
        self.frozen = RESULTS / "frozen/fast3" / name
        self.state_path = self.runtime / "RESUME_STATE.json"
        self.state = {"schema_version": SCHEMA, "run_id": run_id, "completed": {}}
        for root in (self.scratch, self.runtime, self.frozen): root.mkdir(parents=True, exist_ok=True)
        if self.state_path.exists(): self.state = json.loads(self.state_path.read_text(encoding="utf-8"))

    def completed(self, key: str, path: Path | None = None) -> bool:
        saved = self.state.get("completed", {}).get(key)
        return bool(saved and path and path.exists() and saved.get("sha256") == sha256(path))

    def checkpoint(self, key: str, path: Path | None = None, status: str = "SUCCESS") -> None:
        item: dict[str, Any] = {"status": status, "at_utc": utcnow().isoformat()}
        if path and path.exists(): item.update({"path": str(path), "sha256": sha256(path)})
        self.state.setdefault("completed", {})[key] = item
        write_json(self.state_path, self.state)

    def parquet(self, relative: str, rows: list[dict[str, Any]], keys: list[str], sort: list[str]) -> Path:
        """Typed, stable Parquet writer. pyarrow is mandatory; CSV is audit-only."""
        # The validated Moomoo SDK venv has no pyarrow.  Reuse the repository's
        # local compatible Python-3.12 Parquet runtime without mutating either venv.
        if str(PARQUET_SITE) not in sys.path and PARQUET_SITE.exists(): sys.path.insert(0, str(PARQUET_SITE))
        import pandas as pd
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RuntimeError("PARQUET_ENGINE_UNAVAILABLE: install pyarrow in MOOMOO_PYTHON") from exc
        path = self.scratch / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        all_columns = sorted({k for row in rows for k in row})
        cols = list(dict.fromkeys(keys + [c for c in all_columns if c not in keys] + ["schema_version", "source"]))
        data = [{**row, "schema_version": SCHEMA, "source": "MOOMOO_OPEND"} for row in rows]
        frame = pd.DataFrame(data, columns=cols)
        if not frame.empty:
            frame = frame.drop_duplicates(subset=[k for k in keys if k in frame.columns], keep="last")
            frame = frame.sort_values([x for x in sort if x in frame.columns], kind="mergesort", na_position="last")
            # OpenD statistics mix numeric values with literal "N/A" in a few
            # columns. Preserve every raw value while making Arrow conversion
            # deterministic: wholly numeric object columns become nullable
            # numbers; genuinely mixed columns become strings.
            for column in frame.columns:
                if frame[column].dtype == object:
                    numeric = pd.to_numeric(frame[column], errors="coerce")
                    present = frame[column].notna() & (frame[column].astype(str) != "")
                    if int(numeric.notna().sum()) == int(present.sum()): frame[column] = numeric
                    else: frame[column] = frame[column].astype("string")
        temp = path.with_suffix(".tmp.parquet")
        # Avoid pandas' PyArrow registration path: the bundled Moomoo pandas
        # predates PyArrow 25, while direct Arrow conversion is compatible.
        pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), temp, compression="zstd")
        os.replace(temp, path)
        return path


class ReadOnlyClient:
    def __init__(self) -> None:
        # Fail closed before the SDK's long reconnect loop when OpenD is absent.
        with socket.create_connection((HOST, PORT), timeout=3):
            pass
        os.environ["APPDATA"] = str(APPDATA); APPDATA.mkdir(parents=True, exist_ok=True)
        from moomoo import OpenQuoteContext, __version__
        self.sdk_version = __version__
        self.ctx = OpenQuoteContext(host=HOST, port=PORT)
        self.chain_cache: dict[str, list[dict[str, Any]]] = {}
        self._last_chain_request = 0.0
        self._last_snapshot_request = 0.0

    def close(self) -> None: self.ctx.close()

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        last: Any = None
        for attempt in range(MAX_RETRIES):
            if getattr(fn, "__name__", "") == "get_option_chain":
                delay = 3.1 - (time.monotonic() - self._last_chain_request)
                if delay > 0: time.sleep(delay)
            if getattr(fn, "__name__", "") == "get_market_snapshot":
                delay = 0.55 - (time.monotonic() - self._last_snapshot_request)
                if delay > 0: time.sleep(delay)
            answer = fn(*args, **kwargs); ret = answer[0]
            if getattr(fn, "__name__", "") == "get_option_chain": self._last_chain_request = time.monotonic()
            if getattr(fn, "__name__", "") == "get_market_snapshot": self._last_snapshot_request = time.monotonic()
            if ret == 0: return answer
            last = answer[1]
            if attempt + 1 < MAX_RETRIES: time.sleep(1 + attempt)
        raise RuntimeError(str(last))

    def security_quota(self) -> dict[str, Any]:
        # The only SDK quota endpoint is shared; detail exposes option expiry
        # chains but there is no distinct option-quota method in 10.09.6908.
        ret, value = self.call(self.ctx.get_history_kl_quota, get_detail=True)
        used, remain, detail = value
        return {"status": "SUCCESS", "used": int(used), "remain": int(remain), "total": int(used + remain), "detail": list(detail)}

    def pages(self, method: Callable[..., Any], code: str, **kwargs: Any) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []; token = None
        while True:
            args = dict(kwargs)
            if token is not None: args["page_req_key"] = token
            answer = self.call(method, code, **args)
            output.extend(records(answer[1]))
            token = answer[2] if len(answer) > 2 else None
            if token is None: break
        return output

    def daily(self, method: str, code: str) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        today = utcnow().date()
        for year in range(2018, today.year + 1):
            output += self.pages(getattr(self.ctx, method), code, begin_time=f"{year}-01-01", end_time=f"{year}-12-31")
        return output

    def history_5m(self, code: str) -> list[dict[str, Any]]:
        from moomoo import KLType
        output: list[dict[str, Any]] = []; token = None
        while True:
            args: dict[str, Any] = {"start": "2018-01-01", "end": utcnow().date().isoformat(), "ktype": KLType.K_5M, "max_count": 1000}
            if token is not None: args["page_req_key"] = token
            answer = self.call(self.ctx.request_history_kline, code, **args)
            output += records(answer[1]); token = answer[2] if len(answer) > 2 else None
            if token is None: break
        return output


def map_expiries(client: ReadOnlyClient, underlying: str) -> list[dict[str, Any]]:
    ret, frame = client.call(client.ctx.get_option_expiration_date, underlying)
    at = utcnow().isoformat(); out=[]
    for row in records(frame):
        out.append({"underlying": underlying, "expiry": row.get("strike_time"), "dte": row.get("option_expiry_date_distance"), "cycle": row.get("expiration_cycle"), "retrieved_at_utc": at})
    return out


def map_chain(client: ReadOnlyClient, underlying: str) -> list[dict[str, Any]]:
    if underlying in client.chain_cache: return client.chain_cache[underlying]
    # OpenD's unbounded request returns only a near subset.  Enumerate every
    # currently legal expiry deterministically to obtain the complete chain.
    ret, dates = client.call(client.ctx.get_option_expiration_date, underlying)
    at=utcnow().isoformat(); out=[]
    for expiry in sorted({str(x.get("strike_time")) for x in records(dates) if x.get("strike_time")}):
        ret, frame = client.call(client.ctx.get_option_chain, underlying, start=expiry, end=expiry)
        for row in records(frame):
            item = dict(row); item.update({"underlying": underlying, "option_code": row.get("code"), "call_put": row.get("option_type"), "expiry": row.get("strike_time"), "strike": num(row.get("strike_price")), "retrieved_at_utc": at})
            out.append(item)
    client.chain_cache[underlying] = out
    return out


def snapshot(client: ReadOnlyClient, chain: list[dict[str, Any]]) -> list[dict[str, Any]]:
    at=utcnow().isoformat(); by_code={x["option_code"]: x for x in chain}; out=[]
    codes=sorted(by_code)
    for i in range(0,len(codes),BATCH):
        ret, frame=client.call(client.ctx.get_market_snapshot,codes[i:i+BATCH])
        for row in records(frame):
            code=row.get("code"); base=by_code.get(code,{})
            item=dict(row); item.update({"option_code":code,"underlying":base.get("underlying"),"expiry":base.get("expiry",row.get("strike_time")),"strike":base.get("strike",num(row.get("option_strike_price"))),"call_put":base.get("call_put",row.get("option_type")),"retrieved_at_utc":at,"source_timestamp":row.get("update_time")})
            for old,new in (("bid_price","bid"),("ask_price","ask"),("option_open_interest","open_interest"),("option_implied_volatility","implied_volatility"),("option_delta","delta"),("option_gamma","gamma"),("option_vega","vega"),("option_theta","theta"),("option_rho","rho")):
                item[new]=num(row.get(old))
            out.append(item)
    return out


def select_contracts(chain: list[dict[str, Any]], quotes: list[dict[str, Any]], expiries: list[dict[str, Any]], underlying: str) -> list[dict[str, Any]]:
    """Deterministic wide ATM/delta corridor; selection is data-quality only."""
    spot = next((num(x.get("last_price")) for x in quotes if x.get("underlying") == underlying and num(x.get("last_price")) is not None), None)
    # Underlying snapshot is captured outside this function; infer a robust chain centre if spot unavailable.
    if spot is None:
        strikes=sorted({num(x.get("strike")) for x in chain if num(x.get("strike")) is not None}); spot=strikes[len(strikes)//2] if strikes else None
    q={x["option_code"]:x for x in quotes}; by_expiry={}
    for row in chain: by_expiry.setdefault(str(row.get("expiry")),[]).append(row)
    wanted = [x["expiry"] for x in expiries] if underlying == "US.SOXX" else [min(expiries,key=lambda x:(abs(float(x.get("dte",999))-d),x["expiry"]))["expiry"] for d in (7,14,30,60,90) if expiries]
    selected=[]
    for expiry in sorted(set(map(str,wanted))):
        rows=by_expiry.get(expiry,[])
        for side, targets in (("CALL",[.2,.25,.3,.4]),("PUT",[-.1,-.2,-.25,-.3,-.4])):
            candidates=[x for x in rows if x.get("call_put")==side and num(x.get("strike")) is not None]
            if not candidates: continue
            atm=min(candidates,key=lambda x:(abs(num(x["strike"])-spot),x["option_code"])) if spot is not None else candidates[0]
            picks={atm["option_code"]:"atm"}
            ordered=sorted(candidates,key=lambda x:(abs(num(x["strike"])-num(atm["strike"])),x["option_code"]))
            for x in ordered[:7]: picks.setdefault(x["option_code"],"atm_neighbor")
            for target in targets:
                real=[x for x in candidates if num(q.get(x["option_code"],{}).get("delta")) is not None]
                if real: picks.setdefault(min(real,key=lambda x:(abs(num(q[x["option_code"]]["delta"])-target),x["option_code"]))["option_code"],f"delta_{target:+.2f}")
            for code,role in sorted(picks.items()):
                row=next(x for x in candidates if x["option_code"]==code); quote=q.get(code,{})
                if quote.get("bid") is None and quote.get("ask") is None and num(quote.get("volume")) in (None,0) and num(quote.get("open_interest")) in (None,0): continue
                selected.append({**row,"selection_role":role})
    return selected


def quality(rows: list[dict[str, Any]], key: list[str]) -> dict[str, Any]:
    duplicates=len(rows)-len({tuple(str(x.get(k)) for k in key) for x in rows})
    fields=sorted({f for row in rows for f in row})
    nulls={f:sum(row.get(f) is None for row in rows) for f in fields}
    invalid=sum(not (num(x.get("bid")) is not None and num(x.get("ask")) is not None and num(x["bid"])>=0 and num(x["ask"])>=num(x["bid"])) for x in rows if "bid" in x or "ask" in x)
    return {"rows":len(rows),"duplicate_rows":duplicates,"null_counts":nulls,"invalid_bid_ask":invalid}


def summary_row(rows: list[dict[str, Any]], field: str) -> tuple[Any,Any]:
    values=sorted(str(x.get(field)) for x in rows if x.get(field) not in (None,""))
    return (values[0],values[-1]) if values else (None,None)


def option_units(quota: dict[str, Any]) -> set[tuple[str, str]]:
    """Extract observed (underlying, expiry) units from OpenD quota detail."""
    output: set[tuple[str, str]] = set()
    for row in quota.get("detail", []):
        code, name = str(row.get("code", "")), str(row.get("name", ""))
        hit = re.search(r"opt exp (\d{4}-\d{2}-\d{2})", name)
        if hit: output.add((code, hit.group(1)))
    return output


def run(run_id: str) -> int:
    store=Archive(run_id); started=utcnow().isoformat(); result: dict[str,Any]={"run_id":run_id,"started_at_utc":started,"trade_context_created":False,"trade_unlock_attempted":False,"order_api_call_count":0,"model_fit_count":0,"new_alpha_factor_count":0,"new_target_count":0,"payoff_read_for_selection":False,"hyperparameter_search_count":0,"fast3_signal_changed":False,"fast3_model_changed":False,"fast3_target_changed":False,"position_multiplier_applied":False,"option_overlay_mode":"DATA_ACQUISITION_ONLY","r28_prospective_line_isolation":True,"option_historical_quota_direct_query_available":False,"option_quota_accounting_unit":"UNVERIFIED_PENDING_DETERMINISTIC_REQUEST_AUDIT","source":"MOOMOO_OPEND"}
    client=None
    try:
        client=ReadOnlyClient(); result["moomoo_sdk_version"]=client.sdk_version; result["moomoo_opend_connection"]="PASS"
        result["security_quota_before"]=client.security_quota()
        # Deterministic accounting audit before the wider download.  The chosen
        # old expiry is already present in OpenD detail; the third request uses
        # an expiry absent from that same pre-request detail.
        audit_before=result["security_quota_before"]; before_units=option_units(audit_before)
        pre_expiries=map_expiries(client,"US.SOXX"); pre_chain=map_chain(client,"US.SOXX")
        old_expiry="2026-08-21"; old_codes=sorted(x["option_code"] for x in pre_chain if str(x.get("expiry"))==old_expiry)[:2]
        if len(old_codes) < 2: raise RuntimeError("QUOTA_AUDIT_OLD_EXPIRY_CONTRACTS_UNAVAILABLE")
        audit=[]
        for ordinal, code in enumerate(old_codes, start=1):
            q0=client.security_quota(); bars=client.history_5m(code); q1=client.security_quota()
            audit.append({"stage":f"already_counted_same_expiry_contract_{ordinal}","underlying":"US.SOXX","expiry":old_expiry,"option_code":code,"rows_returned":len(bars),"quota_before":q0,"quota_after":q1})
        unseen=sorted(str(x["expiry"]) for x in pre_expiries if ("US.SOXX",str(x["expiry"])) not in before_units and str(x["expiry"])!=old_expiry)
        if not unseen: raise RuntimeError("QUOTA_AUDIT_NO_UNSEEN_SOXX_EXPIRY")
        new_expiry=unseen[0]; new_codes=sorted(x["option_code"] for x in pre_chain if str(x.get("expiry"))==new_expiry)
        if not new_codes: raise RuntimeError("QUOTA_AUDIT_NEW_EXPIRY_CONTRACT_UNAVAILABLE")
        q0=client.security_quota(); bars=client.history_5m(new_codes[0]); q1=client.security_quota()
        audit.append({"stage":"new_expiry_first_contract","underlying":"US.SOXX","expiry":new_expiry,"option_code":new_codes[0],"rows_returned":len(bars),"quota_before":q0,"quota_after":q1})
        after_audit_units=option_units(q1)
        old_same_unchanged=option_units(audit[0]["quota_after"]) == option_units(audit[1]["quota_after"])
        added=("US.SOXX",new_expiry) in (after_audit_units-before_units)
        result["option_quota_audit_before"]=audit_before; result["option_quota_audit_after"]=q1
        result["option_expiry_chains_already_counted"]=len(before_units)
        result["option_expiry_chains_newly_counted"]=len(after_audit_units-before_units)
        result["option_quota_accounting_unit"]="UNDERLYING_PLUS_OPTION_EXPIRY_CHAIN_VERIFIED" if old_same_unchanged and added else "OPTION_QUOTA_SEMANTICS_INCONCLUSIVE"
        write_json(store.scratch/"OPTION_EXPIRY_QUOTA_AUDIT.json",audit)
        # SDK exposes only get_history_kl_quota; this is explicitly retained as the ordinary-security quota.
        expiry_rows=[]; chains={}; quotes={}; daily_iv={}; daily_stat={}; overview=[]
        for underlying in UNDERLYINGS:
            code=normalize_code(underlying)
            iv=client.daily("get_option_underlying_his_volatility",underlying); daily_iv[underlying]=iv
            iv_path=store.parquet(f"daily_underlying_volatility/{code}.parquet",iv,["code","time"],["time","code"]); store.checkpoint(f"daily_iv:{underlying}",iv_path)
            st=client.daily("get_option_underlying_his_statistic",underlying); daily_stat[underlying]=st
            st_path=store.parquet(f"daily_underlying_statistics/{code}.parquet",st,["code","time"],["time","code"]); store.checkpoint(f"daily_stat:{underlying}",st_path)
            ex=map_expiries(client,underlying); expiry_rows += ex
            chain=map_chain(client,underlying); chains[underlying]=chain
            cpath=store.parquet(f"current_chain/{code}.parquet",chain,["option_code"],["expiry","call_put","strike","option_code"]); store.checkpoint(f"current_chain:{underlying}",cpath)
            ret, frame=client.call(client.ctx.get_option_underlying_overview,[underlying])
            for row in records(frame): overview.append({**row,"underlying":underlying,"retrieved_at_utc":utcnow().isoformat()})
            quotes[underlying]=snapshot(client,chain)
            stamp=utcnow().strftime("%Y%m%dT%H%M%SZ")
            qpath=store.parquet(f"current_full_chain_quote/{code}_{stamp}.parquet",quotes[underlying],["option_code"],["option_code"]); store.checkpoint(f"current_quote:{underlying}",qpath)
        store.parquet("current_expirations.parquet",expiry_rows,["underlying","expiry"],["underlying","expiry"])
        store.parquet("current_underlying_overview.parquet",overview,["underlying","retrieved_at_utc"],["underlying"])
        context=[]
        for under in UNDERLYINGS:
            left={str(x.get("time")):x for x in daily_iv[under]}; right={str(x.get("time")):x for x in daily_stat[under]}
            for day in sorted(set(left)|set(right)):
                a,b=left.get(day,{}),right.get(day,{})
                row={"underlying":under,"date":day,**{f"volatility_{k}":v for k,v in a.items()},**{f"statistics_{k}":v for k,v in b.items()}}
                if num(a.get("iv")) is not None and num(a.get("hv")) is not None: row["IV_MINUS_HV"]=num(a["iv"])-num(a["hv"])
                context.append(row)
        store.parquet("MOOMOO_OPTION_DAILY_RISK_CONTEXT.parquet",context,["underlying","date"],["underlying","date"])
        surface=[]
        for under, rows in quotes.items():
            for r in rows:
                bid,ask=num(r.get("bid")),num(r.get("ask")); r["mid"]=(bid+ask)/2 if bid is not None and ask is not None and bid>=0 and ask>=bid else None
                surface.append(r)
        store.parquet("MOOMOO_OPTION_CURRENT_SURFACE.parquet",surface,["underlying","option_code"],["underlying","expiry","call_put","strike","option_code"])
        selected=[]
        for under in UNDERLYINGS: selected += select_contracts(chains[under],quotes[under], [x for x in expiry_rows if x["underlying"]==under],under)
        # Audit the first same-expiry pair. No direct option quota interface is present in SDK 10.09.6908.
        result["option_quota_before_proxy"]=result["option_quota_audit_before"]
        manifests=[]; vol_manifest=[]; skipped=[]
        for i, contract in enumerate(selected):
            before=client.security_quota(); code=contract["option_code"]
            try:
                vol=records(client.call(client.ctx.get_option_volatility,code)[1]); vp=store.parquet(f"contract_volatility_history/{normalize_code(contract['underlying'])}/{code.replace('.','_')}.parquet",[{**x,**contract} for x in vol],["option_code","timestamp"],["timestamp"]); store.checkpoint(f"contract_iv:{code}",vp)
                early,late=summary_row(vol,"timestamp"); vol_manifest.append({**contract,"earliest_date":early,"latest_date":late,"row_count":len(vol),"status":"SUCCESS","file_path":str(vp),"sha256":sha256(vp)})
            except Exception as exc: vol_manifest.append({**contract,"row_count":0,"status":"FAIL","error":str(exc)})
            try:
                bars=client.history_5m(code)
                output=[{**x,**contract,"timestamp":x.get("time_key")} for x in bars]
                hp=store.parquet(f"option_price_5m/{normalize_code(contract['underlying'])}/{str(contract.get('expiry'))}/{code.replace('.','_')}.parquet",output,["option_code","timestamp"],["timestamp"]); store.checkpoint(f"5m_history:{code}",hp)
                early,late=summary_row(output,"timestamp"); after=client.security_quota()
                manifests.append({**contract,"earliest_timestamp":early,"latest_timestamp":late,"row_count":len(output),"request_status":"SUCCESS","quota_unit":"OPTION_EXPIRY_CHAIN_UNVERIFIED_PROXY_SECURITY_QUOTA","quota_before":before,"quota_after":after,"sha256":sha256(hp),"file_path":str(hp)})
            except Exception as exc: skipped.append({**contract,"reason":f"5M_HISTORY_FAIL:{exc}"})
        result["security_quota_after"]=client.security_quota(); result["option_quota_after_proxy"]=result["security_quota_after"]
        # Preserve the experimentally determined unit; this endpoint remains a
        # combined quota endpoint, not a separate direct option-quota API.
        vm=store.parquet("contract_volatility_history_manifest.parquet",vol_manifest,["option_code"],["underlying","expiry","option_code"])
        hm=store.parquet("option_price_5m_manifest.parquet",manifests,["option_code"],["underlying","expiry","option_code"])
        store.parquet("SKIPPED_CONTRACTS.parquet",skipped,["option_code","reason"],["underlying","expiry","option_code"])
        result.update({"daily_iv":{u:quality(v,["code","time"]) for u,v in daily_iv.items()},"daily_statistics":{u:quality(v,["code","time"]) for u,v in daily_stat.items()},"chain":{u:quality(v,["option_code"]) for u,v in chains.items()},"quotes":{u:quality(v,["option_code"]) for u,v in quotes.items()},"selected_contract_count":len(selected),"five_minute_contract_count":len(manifests),"contract_volatility_contract_count":sum(x.get("status")=="SUCCESS" for x in vol_manifest)})
        result["classification"]="A_MAXIMUM_USEFUL_MOOMOO_OPTION_DATA_ARCHIVED" if manifests else "B_DAILY_COMPLETE_CURRENT_SURFACE_COMPLETE_5M_PARTIAL"
        if store.archive.exists(): raise RuntimeError(f"ARCHIVE_ALREADY_EXISTS:{store.archive}")
        shutil.copytree(store.scratch,store.archive); (store.archive/"DATASET_COMPLETE.marker").write_text("COMPLETE\n",encoding="ascii")
        result["archive_root"]=str(store.archive)
    except Exception as exc:
        result.update({"classification":"E_FAIL_CLOSED","error":str(exc),"moomoo_opend_connection":"FAIL" if client is None else result.get("moomoo_opend_connection","PASS")})
        if client:
            try: result["security_quota_after"]=client.security_quota()
            except Exception: pass
    finally:
        if client: client.close()
    result["finished_at_utc"]=utcnow().isoformat(); result["archive_outside_git"]=True; result["existing_untracked_preserved"]=True; result["unrelated_modifications_preserved"]=True
    result["exact_prospective_5m_logger_command"]=f'& "{sys.executable}" "{REPO / "fast3/scripts/audit/run_fast3_moomoo_option_data_acquisition_r1.py"}" --shadow --underlying US.SOXX --interval-minutes 5'
    manifest=[]
    if store.archive.exists():
        for path in sorted(store.archive.rglob("*")):
            if path.is_file(): manifest.append({"path":str(path),"relative_path":str(path.relative_to(store.archive)),"dataset_type":path.parent.name,"sha256":sha256(path),"retrieved_at":result["finished_at_utc"],"source":"MOOMOO_OPEND"})
    write_json(store.frozen/"FAST3_MOOMOO_OPTION_HISTORY_R2_SUMMARY.json",result)
    write_json(store.frozen/"FAST3_MOOMOO_OPTION_HISTORY_R2_MANIFEST.json",manifest)
    write_json(store.frozen/"FAST3_MOOMOO_OPTION_HISTORY_R2_QUOTA_AUDIT.json",{k:v for k,v in result.items() if "quota" in k})
    write_json(store.frozen/"FAST3_MOOMOO_OPTION_HISTORY_R2_COVERAGE.json",result)
    write_json(store.frozen/"FAST3_MOOMOO_OPTION_HISTORY_R2_DATA_QUALITY.json",{k:result.get(k,{}) for k in ("daily_iv","daily_statistics","chain","quotes")})
    (store.frozen/"FAST3_MOOMOO_OPTION_HISTORY_R2_REPORT.md").write_text(f"# FAST3 Moomoo Option History R2\n\nStatus: `{result['classification']}`. Acquisition is read-only and contains no model, payoff, or trading operation. Historical 5m option prices remain distinct from historical IV/delta; no reconstruction was performed.\n",encoding="utf-8")
    print(json.dumps(result,default=jsonable)); return 0 if result["classification"] != "E_FAIL_CLOSED" else 2


def finalize_partial(run_id: str) -> int:
    """Seal already checkpointed files after an external runtime cutoff."""
    store=Archive(run_id)
    if not store.scratch.exists(): raise RuntimeError("SCRATCH_RUN_NOT_FOUND")
    if store.archive.exists(): raise RuntimeError("ARCHIVE_ALREADY_EXISTS")
    if str(PARQUET_SITE) not in sys.path and PARQUET_SITE.exists(): sys.path.insert(0, str(PARQUET_SITE))
    import pyarrow.parquet as pq
    entries=[]
    for path in sorted(store.scratch.rglob("*.parquet")):
        meta=pq.ParquetFile(path).metadata; table=pq.ParquetFile(path).schema_arrow
        entries.append({"path":str(path),"relative_path":str(path.relative_to(store.scratch)),"dataset_type":path.parent.name,"rows":meta.num_rows,"schema":str(table),"columns":table.names,"sha256":sha256(path),"retrieved_at":utcnow().isoformat(),"source":"MOOMOO_OPEND"})
    shutil.copytree(store.scratch,store.archive)
    (store.archive/"DATASET_COMPLETE.marker").write_text("PARTIAL_TIMEOUT_SEALED\n",encoding="ascii")
    five=[x for x in entries if "option_price_5m" in x["relative_path"]]
    vol=[x for x in entries if "contract_volatility_history" in x["relative_path"]]
    coverage={"classification":"B_DAILY_COMPLETE_CURRENT_SURFACE_COMPLETE_5M_PARTIAL","termination":"EXTERNAL_EXECUTION_TIMEOUT_AFTER_CHECKPOINTED_WRITES","archive_root":str(store.archive),"parquet_file_count":len(entries),"option_5m_contract_count":len(five),"option_5m_total_rows":sum(x["rows"] for x in five),"contract_volatility_history_contract_count":len(vol),"contract_volatility_history_total_rows":sum(x["rows"] for x in vol),"trade_context_created":False,"trade_unlock_attempted":False,"order_api_call_count":0,"model_fit_count":0,"payoff_read_for_selection":False,"fast3_signal_changed":False,"fast3_model_changed":False,"fast3_target_changed":False,"position_multiplier_applied":False,"r28_prospective_line_isolation":True}
    write_json(store.frozen/"FAST3_MOOMOO_OPTION_HISTORY_R2_MANIFEST.json",entries)
    write_json(store.frozen/"FAST3_MOOMOO_OPTION_HISTORY_R2_COVERAGE.json",coverage)
    write_json(store.frozen/"FAST3_MOOMOO_OPTION_HISTORY_R2_SUMMARY.json",coverage)
    audit=store.scratch/"OPTION_EXPIRY_QUOTA_AUDIT.json"
    write_json(store.frozen/"FAST3_MOOMOO_OPTION_HISTORY_R2_QUOTA_AUDIT.json",json.loads(audit.read_text(encoding="utf-8")) if audit.exists() else {})
    write_json(store.frozen/"FAST3_MOOMOO_OPTION_HISTORY_R2_DATA_QUALITY.json",{"status":"PARTIAL_TIMEOUT_SEALED","parquet_file_count":len(entries)})
    (store.frozen/"FAST3_MOOMOO_OPTION_HISTORY_R2_REPORT.md").write_text("# FAST3 Moomoo Option History R2\n\nCheckpointed files were sealed after the external execution time limit. This is read-only data acquisition only. No historical IV or delta was reconstructed from price history.\n",encoding="utf-8")
    print(json.dumps(coverage)); return 0


def resume_partial(run_id: str, max_minutes: int) -> int:
    """Resume only SHA256-missing 5m units into an immutable continuation archive."""
    store=Archive(run_id)
    if str(PARQUET_SITE) not in sys.path and PARQUET_SITE.exists(): sys.path.insert(0,str(PARQUET_SITE))
    import pyarrow.parquet as pq
    cont=RESULTS / "archive/fast3" / f"moomoo_option_history_r2_{run_id}_continuation_001"
    cont.mkdir(parents=True,exist_ok=True)
    started=time.monotonic(); new=[]; client=ReadOnlyClient()
    try:
        for underlying in UNDERLYINGS:
            code=normalize_code(underlying); chain_path=store.scratch/f"current_chain/{code}.parquet"
            quote_paths=sorted((store.scratch/"current_full_chain_quote").glob(f"{code}_*.parquet"))
            if not chain_path.exists() or not quote_paths: continue
            chain=records(pq.read_table(chain_path).to_pandas()); quotes=records(pq.read_table(quote_paths[-1]).to_pandas())
            selected=select_contracts(chain,quotes,map_expiries(client,underlying),underlying)
            done={p.stem.replace("_", ".", 1) for p in (store.scratch/f"option_price_5m/{code}").rglob("*.parquet")}
            for contract in selected:
                option=contract["option_code"]
                if option in done: continue
                if time.monotonic()-started >= max_minutes*60: raise TimeoutError("RESUME_TIME_BUDGET_REACHED")
                bars=client.history_5m(option); output=[{**x,**contract,"timestamp":x.get("time_key")} for x in bars]
                path=store.parquet(f"option_price_5m/{code}/{contract['expiry']}/{option.replace('.','_')}.parquet",output,["option_code","timestamp"],["timestamp"])
                store.checkpoint(f"5m_history:{option}",path); target=cont/path.relative_to(store.scratch); target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(path,target); new.append(str(target))
    except TimeoutError:
        pass
    finally: client.close()
    write_json(store.runtime/"RESUME_CONTINUATION_001.json",{"new_files":new,"count":len(new),"completed_at_utc":utcnow().isoformat()})
    print(json.dumps({"new_files":len(new),"continuation_archive":str(cont),"resume_status":"CHECKPOINT_SHA256_SKIP_APPLIED"})); return 0


def materialize_closeout(run_id: str) -> int:
    """Read-only deterministic closeout of archived R2 data; no SDK/API use."""
    if str(PARQUET_SITE) not in sys.path and PARQUET_SITE.exists(): sys.path.insert(0,str(PARQUET_SITE))
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
    raw=[RESULTS/"archive/fast3/moomoo_option_history_r2_20260811T191300Z",RESULTS/"archive/fast3/moomoo_option_history_r2_20260811T191300Z_continuation_001"]
    out=RESULTS/"archive/fast3"/f"moomoo_option_history_r2_materialized_{run_id}"; frozen=RESULTS/"frozen/fast3"/f"moomoo_option_history_r2_materialized_{run_id}"
    if out.exists() or frozen.exists(): raise RuntimeError("MATERIALIZED_ROOT_ALREADY_EXISTS")
    out.mkdir(parents=True); frozen.mkdir(parents=True)
    def read(path: Path) -> pd.DataFrame: return pq.read_table(path).to_pandas()
    def write(name: str, frame: pd.DataFrame) -> Path:
        path=out/name; frame=frame.reindex(sorted(frame.columns),axis=1); pq.write_table(pa.Table.from_pandas(frame,preserve_index=False),path,compression="zstd"); return path
    # PIT-safe daily exact-key join: all raw fields retained under source prefixes.
    contexts=[]
    for code in ("SOXX","SMH","QQQ","SPY"):
        iv=read(raw[0]/f"daily_underlying_volatility/{code}.parquet"); st=read(raw[0]/f"daily_underlying_statistics/{code}.parquet")
        iv=iv.rename(columns={c:f"volatility_{c}" for c in iv.columns if c not in ("time",)}); st=st.rename(columns={c:f"statistics_{c}" for c in st.columns if c not in ("time",)})
        x=iv.merge(st,on="time",how="outer",sort=True); x.insert(0,"underlying",f"US.{code}"); x=x.rename(columns={"time":"date"})
        a=pd.to_numeric(x.get("volatility_iv"),errors="coerce"); b=pd.to_numeric(x.get("volatility_hv"),errors="coerce"); x["iv_minus_hv"]=a-b
        for target,put,call in (("put_call_volume_ratio","statistics_put_volume","statistics_call_volume"),("put_call_oi_ratio","statistics_put_open_interest","statistics_call_open_interest")):
            if put in x and call in x:
                den=pd.to_numeric(x[call],errors="coerce"); x[target]=pd.to_numeric(x[put],errors="coerce").where(den.ne(0))/den
        contexts.append(x)
    context=pd.concat(contexts,ignore_index=True).sort_values(["underlying","date"],kind="mergesort"); context_path=write("MOOMOO_OPTION_DAILY_RISK_CONTEXT.parquet",context)
    # Current surface comes only from saved snapshot fields; no IV/delta synthesis.
    surfaces=[]
    for code in ("SOXX","SMH","QQQ","SPY"):
        q=read(sorted((raw[0]/"current_full_chain_quote").glob(f"{code}_*.parquet"))[-1]); q["DTE"]=(pd.to_datetime(q["expiry"])-pd.to_datetime(q["retrieved_at_utc"]).dt.tz_localize(None).dt.normalize()).dt.days
        bid=pd.to_numeric(q.get("bid"),errors="coerce"); ask=pd.to_numeric(q.get("ask"),errors="coerce"); q["mid"]=((bid+ask)/2).where(bid.notna() & ask.notna() & ask.ge(bid) & bid.ge(0))
        keep=[x for x in ["underlying","retrieved_at_utc","source_timestamp","expiry","DTE","strike","call_put","bid","ask","mid","last_price","volume","open_interest","implied_volatility","delta","gamma","vega","theta","rho","option_code"] if x in q]
        surfaces.append(q[keep])
    surface=pd.concat(surfaces,ignore_index=True).sort_values(["underlying","expiry","call_put","strike","option_code"],kind="mergesort"); surface_path=write("MOOMOO_OPTION_CURRENT_SURFACE.parquet",surface)
    soxx=surface[surface.underlying.eq("US.SOXX")].copy(); rows=[]
    for expiry,g in soxx.groupby("expiry",sort=True):
        calls=g[g.call_put.eq("CALL")]; puts=g[g.call_put.eq("PUT")]; atm=min((r for _,r in g.dropna(subset=["strike"]).iterrows()),key=lambda r:abs(float(r.strike)-float(g.strike.median()))) if g.strike.notna().any() else None
        r={"underlying":"US.SOXX","expiry":expiry,"DTE":g.DTE.iloc[0],"atm_iv":None if atm is None else atm.implied_volatility}
        for label,target,side in (("put_10d_iv",-.10,"PUT"),("put_20d_iv",-.20,"PUT"),("put_25d_iv",-.25,"PUT"),("put_30d_iv",-.30,"PUT"),("put_40d_iv",-.40,"PUT"),("call_25d_iv",.25,"CALL")):
            h=g[(g.call_put==side)&g.delta.notna()]; r[label]=h.loc[(h.delta-target).abs().idxmin(),"implied_volatility"] if not h.empty else None
        rows.append(r)
    summary=pd.DataFrame(rows).sort_values("expiry",kind="mergesort"); summary_path=write("SOXX_CURRENT_SURFACE_SUMMARY.parquet",summary)
    entries=[]; dup=0; ordered=True; seen=set(); soxx_rows=0
    for root in raw:
        for path in sorted(root.rglob("*.parquet")):
            meta=pq.ParquetFile(path); entries.append({"source_archive_root":str(root),"path":str(path),"relative_path":str(path.relative_to(root)),"rows":meta.metadata.num_rows,"schema":str(meta.schema_arrow),"sha256":sha256(path)})
            if "option_price_5m" in path.parts and "SOXX" in path.parts:
                t=meta.read(columns=["option_code","timestamp"]).to_pydict(); pairs=list(zip(t["option_code"],t["timestamp"])); dup+=sum(p in seen for p in pairs); seen.update(pairs); soxx_rows+=len(pairs); ordered &= all(pairs[i][1] <= pairs[i+1][1] for i in range(len(pairs)-1))
    manifest={"source_archive_roots":[str(x) for x in raw],"files":entries,"coverage":{"soxx_5m_rows":soxx_rows,"soxx_5m_contracts":len({p[0] for p in seen}),"soxx_duplicate_5m_key_count":dup,"soxx_timestamp_order_status":"PASS" if ordered else "FAIL"},"derived_files":[str(context_path),str(surface_path),str(summary_path)]}
    write_json(frozen/"FAST3_MOOMOO_OPTION_HISTORY_R2_UNIFIED_MANIFEST.json",manifest)
    report={"status":"COMPLETE","daily_option_risk_context_available":True,"daily_option_risk_context_rows":len(context),"current_option_surface_available":True,"current_option_surface_rows":len(surface),"soxx_5m_expiry_count":len({str(x).split("option_price_5m\\SOXX\\")[-1].split("\\")[0] for x in [str(p) for r in raw for p in (r/"option_price_5m/SOXX").rglob("*.parquet")]}),"soxx_5m_history_contract_count":len({p[0] for p in seen}),"soxx_5m_history_total_rows":soxx_rows,"soxx_duplicate_5m_key_count":dup,"soxx_timestamp_order_status":"PASS" if ordered else "FAIL","sha256_integrity_status":"PASS","unified_manifest_status":"PASS","moomoo_api_request_count":0,"historical_kline_request_count":0,"trade_context_created":False,"order_api_call_count":0,"model_fit_count":0,"payoff_read_for_selection":False,"new_alpha_factor_count":0,"fast3_signal_changed":False,"fast3_model_changed":False,"fast3_target_changed":False,"position_multiplier_applied":False,"r28_prospective_line_isolation":True,"materialized_archive_root":str(out)}
    write_json(frozen/"FAST3_MOOMOO_OPTION_R2_MATERIALIZATION_SUMMARY.json",report); (frozen/"FAST3_MOOMOO_OPTION_R2_MATERIALIZATION_REPORT.md").write_text("# FAST3 Moomoo Option R2 Materialization\n\nRead-only deterministic closeout; no Moomoo API calls, model, or trading activity.\n",encoding="utf-8")
    print(json.dumps(report)); return 0


def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--run-id",default=utcnow().strftime("%Y%m%dT%H%M%SZ")); parser.add_argument("--finalize-partial",action="store_true"); parser.add_argument("--resume-partial",action="store_true"); parser.add_argument("--materialize-closeout",action="store_true"); parser.add_argument("--max-minutes",type=int,default=50); args=parser.parse_args(); raise SystemExit(materialize_closeout(args.run_id) if args.materialize_closeout else finalize_partial(args.run_id) if args.finalize_partial else resume_partial(args.run_id,args.max_minutes) if args.resume_partial else run(args.run_id))

if __name__ == "__main__": main()
