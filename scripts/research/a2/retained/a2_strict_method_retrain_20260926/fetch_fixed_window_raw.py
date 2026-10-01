"""Append-only raw K_DAY input fetch for the frozen 2026 A2 test window.

This reads the original quarterly members and never reads model scores.
It does not create adjusted prices or call any fit or backtest entry point.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "test2026_stage" / "fixed_window_raw"
OTHER = HERE.parent / "a2_13f_learned_sizing_pre2026_test2026_r1" / "continuation_2026_r1"
ORIGINAL = Path(r"D:\us-tech-quant-results\A_VS_A2_QUARTERLY_13F_R1")
LIMITER = Path(r"D:\us-tech-quant\scripts\v21\v21_231_moomoo_only_historical_refetch_and_canonical_rebuild.py")
MANIFEST = OTHER / "SUBSCRIPTION_RAW_FILES_MANIFEST.csv"
END = pd.Timestamp("2026-09-24")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def import_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    receipt_path = OUT / "FIXED_WINDOW_RAW_RECEIPT.json"
    members = pd.read_parquet(ORIGINAL / "universe/quarterly_universe_members.parquet")
    members = members.loc[members.quarter.isin(["2025Q3", "2025Q4", "2026Q1"])]
    q2 = pd.read_parquet(OTHER / "Q2_ORIGINAL24_INITIAL_CANDIDATES.parquet")
    # Version changes may alter membership. Include all transport codes recorded
    # in the versioned rows, if present, as well as the initial candidate set.
    versioned = pd.read_parquet(OTHER / "Q2_ORIGINAL24_VERSIONED_ROWS.parquet")
    codes = set(members.moomoo_transport_code.dropna().astype(str))
    codes.update(q2.moomoo_transport_code.dropna().astype(str))
    if "moomoo_transport_code" in versioned:
        codes.update(versioned.moomoo_transport_code.dropna().astype(str))
    codes = sorted(c for c in codes if c.startswith("US."))
    prior = pd.read_csv(MANIFEST).set_index("code")
    receipt = {
        "scope": "FULL_FIXED_2026_DYNAMIC_POOL_INPUT_ONLY",
        "test_asof_utc": "2026-09-25T18:10:21.6494935Z",
        "last_signal": "2026-09-22", "last_execution": "2026-09-23",
        "terminal_valuation": "2026-09-24", "target_count": len(codes),
        "target_basis": "original_2025Q3_Q4_2026Q1_members_plus_Q2_initial_and_versioned_transport_codes_no_model_scores",
        "original_members_sha256": digest(ORIGINAL / "universe/quarterly_universe_members.parquet"),
        "q2_initial_sha256": digest(OTHER / "Q2_ORIGINAL24_INITIAL_CANDIDATES.parquet"),
        "q2_versioned_rows_sha256": digest(OTHER / "Q2_ORIGINAL24_VERSIONED_ROWS.parquet"),
        "prior_manifest_sha256": digest(MANIFEST),
        "kline_type": "K_DAY", "autype": "NONE", "session": "RTH",
        "request_started_utc": datetime.now(timezone.utc).isoformat(),
        "records": [], "batches": [], "subscription_calls": 0,
        "kline_calls": 0, "unsubscribe_calls": 0,
    }
    completed = set()
    if receipt_path.exists():
        old = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert old["test_asof_utc"] == receipt["test_asof_utc"]
        assert old["original_members_sha256"] == receipt["original_members_sha256"]
        assert old["target_count"] == receipt["target_count"]
        receipt = old
        completed = {r["code"] for r in old["records"]}
    targets = [c for c in codes if c not in completed]

    def persist() -> None:
        tmp = receipt_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        for attempt in range(20):
            try:
                tmp.replace(receipt_path)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.2)

    sdk = HERE / "test2026_stage" / "sdk_appdata"
    sdk.mkdir(parents=True, exist_ok=True)
    os.environ["APPDATA"] = str(sdk.resolve())
    os.environ["appdata"] = str(sdk.resolve())
    sys.path.insert(0, str(HERE / "vendor"))
    import moomoo
    limiter_cls = import_file("a2_2026_original_limiter", LIMITER).HistoryKlineLimiter
    limiter = limiter_cls(max_calls=40, window_seconds=30.0, min_interval=0.75)
    ctx = moomoo.OpenQuoteContext(host="127.0.0.1", port=18441)
    owned = []

    def release(force=False) -> None:
        still = []
        for item in owned:
            delay = 60.0 - (time.monotonic() - item["since"])
            if force and delay > 0:
                time.sleep(delay)
            if force or delay <= 0:
                ret, msg = ctx.unsubscribe(item["codes"], [moomoo.SubType.K_DAY], unsubscribe_all=False)
                receipt["unsubscribe_calls"] += 1
                receipt.setdefault("own_unsubscriptions", []).append({"codes": item["codes"], "return_code": ret,
                    "error": None if ret == moomoo.RET_OK else str(msg)[:250]})
            else:
                still.append(item)
        owned[:] = still
        persist()

    try:
        ret, hist = ctx.get_history_kl_quota(get_detail=True)
        receipt["history_before"] = {"return_code": ret, "used": int(hist[0]), "remaining": int(hist[1])} if ret == moomoo.RET_OK else {"return_code": ret}
        persist()
        for offset in range(0, len(targets), 20):
            release()
            batch = targets[offset:offset+20]
            ret, sub = ctx.query_subscription(is_all_conn=True)
            if ret != moomoo.RET_OK:
                receipt["status"] = "SUBSCRIPTION_QUERY_FAILED_STOP"
                receipt["error"] = str(sub)[:300]
                break
            if int(sub["remain"]) < len(batch):
                release(force=True)
                ret, sub = ctx.query_subscription(is_all_conn=True)
                if ret != moomoo.RET_OK or int(sub["remain"]) < len(batch):
                    receipt["status"] = "SUBSCRIPTION_QUOTA_INSUFFICIENT_STOP"
                    break
            limiter.acquire({"ticker": "BATCH", "adjustment": "none", "frequency": "1d"})
            ret, msg = ctx.subscribe(batch, [moomoo.SubType.K_DAY], is_first_push=False,
                subscribe_push=False, extended_time=False, session=moomoo.Session.RTH)
            receipt["subscription_calls"] += 1
            entry = {"codes": batch, "return_code": ret, "quota_remaining_before": int(sub["remain"])}
            receipt["batches"].append(entry)
            if ret == moomoo.RET_OK:
                owned.append({"codes": batch, "since": time.monotonic()})
                active = batch
            else:
                entry["error"] = str(msg)[:250]
                active = []
                for code in batch:
                    limiter.acquire({"ticker": code, "adjustment": "none", "frequency": "1d"})
                    one_ret, one_msg = ctx.subscribe([code], [moomoo.SubType.K_DAY], is_first_push=False,
                        subscribe_push=False, extended_time=False, session=moomoo.Session.RTH)
                    receipt["subscription_calls"] += 1
                    if one_ret == moomoo.RET_OK:
                        owned.append({"codes": [code], "since": time.monotonic()})
                        active.append(code)
                    else:
                        receipt["records"].append({"code": code, "status": "SUBSCRIBE_REJECTED", "error": str(one_msg)[:250]})
                        persist()
            for code in active:
                record = {"code": code, "requested_at_utc": datetime.now(timezone.utc).isoformat()}
                limiter.acquire({"ticker": code, "adjustment": "none", "frequency": "1d"})
                ret, frame = ctx.get_cur_kline(code, 1000, ktype=moomoo.KLType.K_DAY, autype=moomoo.AuType.NONE)
                receipt["kline_calls"] += 1
                record["return_code"] = ret
                if ret != moomoo.RET_OK or not isinstance(frame, pd.DataFrame) or frame.empty:
                    record.update({"status": "KLINE_REJECTED_OR_EMPTY", "error": str(frame)[:250]})
                    receipt["records"].append(record); persist(); continue
                frame = frame.copy()
                frame["trade_date"] = pd.to_datetime(frame.time_key).dt.normalize()
                frame = frame.loc[frame.trade_date.le(END)].copy()
                record["rows_through_terminal"] = len(frame)
                record["first_date"] = str(frame.trade_date.min().date()) if len(frame) else None
                record["last_date"] = str(frame.trade_date.max().date()) if len(frame) else None
                record["has_09_23"] = bool(frame.trade_date.eq("2026-09-23").any())
                record["has_09_24"] = bool(frame.trade_date.eq("2026-09-24").any())
                if not len(frame) or frame.trade_date.duplicated().any() or set(frame.code.astype(str)) != {code}:
                    record["status"] = "IDENTITY_OR_DATE_CONFLICT"
                    receipt["records"].append(record); persist(); continue
                for field in ("open", "high", "low", "close", "volume"):
                    frame[field] = pd.to_numeric(frame[field], errors="raise")
                if code in prior.index:
                    row = prior.loc[code]
                    old_path = OTHER / str(row["file"])
                    if digest(old_path) != str(row["sha256"]):
                        record["status"] = "PRIOR_RAW_HASH_CONFLICT"
                        receipt["records"].append(record); persist(); continue
                    old = pd.read_parquet(old_path)
                    old["trade_date"] = pd.to_datetime(old.time_key).dt.normalize()
                    overlap = old.merge(frame, on="trade_date", suffixes=("_old", "_new"))
                    record["overlap_rows"] = len(overlap)
                    if len(overlap):
                        error = max((pd.to_numeric(overlap[f"{f}_old"]) - pd.to_numeric(overlap[f"{f}_new"])).abs().max()
                            for f in ("open", "high", "low", "close", "volume"))
                        record["overlap_max_abs_difference"] = float(error)
                        if error > 1e-9:
                            record["status"] = "OVERLAP_CONFLICT_QUARANTINED"
                    else:
                        record["status"] = "NO_PRIOR_OVERLAP_QUARANTINED"
                if "status" not in record:
                    record["status"] = "RAW_SAVED_INPUT_ONLY"
                stem = "CONFLICT" if "QUARANTINED" in record["status"] else "RAW"
                target = OUT / f"{stem}_{code.replace('.', '_')}_K_DAY_NONE_RTH.parquet"
                if not target.exists():
                    frame.to_parquet(target, index=False)
                record["file"] = target.name
                record["sha256"] = digest(target)
                receipt["records"].append(record); persist()
            entry["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
            persist()
            print(json.dumps({"completed": len(receipt["records"]), "target": len(codes), "last_batch": len(batch)}), flush=True)
        else:
            receipt["status"] = "ALL_TARGET_CODES_ATTEMPTED"
    finally:
        release(force=True)
        ctx.close()
        receipt["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        persist()
        print(json.dumps({"status": receipt.get("status"), "target_count": len(codes),
            "record_count": len(receipt["records"]), "kline_calls": receipt["kline_calls"]}), flush=True)


if __name__ == "__main__":
    main()
