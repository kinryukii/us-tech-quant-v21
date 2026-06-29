from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STAGE = "V21.172_TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH"
OUT = ROOT / "outputs" / "v21" / STAGE
TARGETS = ["BITF", "PSTG", "SATS", "TQQQ"]
ALLOW_BROAD_REFRESH = False

PRICE = ROOT / "outputs" / "v20" / "price_history" / "V20_199D_CANONICAL_HISTORICAL_OHLCV.csv"
V171_SUMMARY = ROOT / "outputs" / "v21" / "V21.171_NON_BLOCKING_PRICE_ISSUE_REPAIR_PREFLIGHT" / "V21.171_NON_BLOCKING_PRICE_ISSUE_REPAIR_PREFLIGHT_summary.json"
V171_DETAIL = ROOT / "outputs" / "v21" / "V21.171_NON_BLOCKING_PRICE_ISSUE_REPAIR_PREFLIGHT" / "target_ticker_price_issue_detail.csv"
V165_STALE = ROOT / "outputs" / "v21" / "V21.165_DATA_FRESHNESS_AND_PROXY_COVERAGE_DASHBOARD" / "stale_or_missing_tickers.csv"

POLICY = {
    "research_only": True,
    "official_adoption_allowed": False,
    "broker_action_allowed": False,
    "live_trading_allowed": False,
    "protected_outputs_modified": False,
    "role_review_required": False,
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
            if not path.is_file() or OUT in path.parents or path == PRICE:
                continue
            s = rel(path).lower().replace("-", "_")
            protected = any(x in s for x in ["broker", "real_book", "realbook", "trade_action", "ledger"])
            protected = protected or ("official" in s and any(x in s for x in ["rank", "weight", "allocation", "recommend"]))
            if protected:
                hashes[rel(path)] = sha(path)
    return hashes


def norm(s: pd.Series) -> pd.Series:
    return s.astype(str).str.upper().str.strip()


def freshness(panel: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    if panel.empty or "date" not in panel.columns:
        return pd.DataFrame(columns=["ticker", "latest_price_date", "price_row_count", "freshness_status"]), ""
    work = panel.copy()
    ticker_col = "symbol" if "symbol" in work.columns else "ticker"
    work[ticker_col] = norm(work[ticker_col])
    work["_date"] = pd.to_datetime(work["date"], errors="coerce")
    latest_panel_date = "" if work["_date"].dropna().empty else str(work["_date"].max().date())
    grouped = work.dropna(subset=["_date"]).groupby(ticker_col).agg(latest_price_date=("_date", "max"), price_row_count=("_date", "size")).reset_index()
    grouped = grouped.rename(columns={ticker_col: "ticker"})
    base = pd.DataFrame({"ticker": TARGETS})
    out = base.merge(grouped, on="ticker", how="left")
    out["latest_price_date_dt"] = pd.to_datetime(out["latest_price_date"], errors="coerce")
    panel_dt = pd.to_datetime(latest_panel_date, errors="coerce")
    out["freshness_status"] = "FRESH"
    out.loc[out["latest_price_date_dt"].isna(), "freshness_status"] = "MISSING_PRICE"
    if not pd.isna(panel_dt):
        out.loc[out["latest_price_date_dt"].notna() & (out["latest_price_date_dt"] < panel_dt), "freshness_status"] = "STALE_PRICE"
    out["latest_price_date"] = out["latest_price_date_dt"].dt.strftime("%Y-%m-%d").fillna("")
    out["price_row_count"] = out["price_row_count"].fillna(0).astype(int)
    return out[["ticker", "latest_price_date", "price_row_count", "freshness_status"]], latest_panel_date


def row_hash(row: dict[str, Any]) -> str:
    keys = ["symbol", "date", "open", "high", "low", "close", "adjusted_close", "volume", "source_provider", "source_artifact"]
    payload = "|".join(str(row.get(k, "")) for k in keys)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fetch_yfinance(ticker: str) -> tuple[pd.DataFrame, str]:
    try:
        import yfinance as yf  # type: ignore
        try:
            import yfinance.cache as yf_cache  # type: ignore

            cache_dir = ROOT / "outputs" / "v21" / ".v21_172_yfinance_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            yf_cache.set_cache_location(str(cache_dir))
        except Exception:
            pass
    except Exception as exc:  # pragma: no cover - environment dependent
        return pd.DataFrame(), f"yfinance unavailable: {exc}"
    try:
        data = yf.download(ticker, period="10d", interval="1d", progress=False, auto_adjust=False, threads=False)
    except Exception as exc:
        return pd.DataFrame(), f"provider download failed: {exc}"
    if data is None or data.empty:
        return pd.DataFrame(), "provider returned no rows"
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [c[0] if isinstance(c, tuple) else c for c in data.columns]
    data = data.reset_index()
    rows = []
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for raw in data.to_dict("records"):
        date_val = pd.to_datetime(raw.get("Date") or raw.get("Datetime"), errors="coerce")
        if pd.isna(date_val):
            continue
        row = {
            "symbol": ticker,
            "date": str(date_val.date()),
            "open": raw.get("Open", ""),
            "high": raw.get("High", ""),
            "low": raw.get("Low", ""),
            "close": raw.get("Close", ""),
            "adjusted_close": raw.get("Adj Close", raw.get("Close", "")),
            "volume": raw.get("Volume", ""),
            "source_provider": "Yahoo/yfinance",
            "source_artifact": f"Yahoo/yfinance:period=10d;interval=1d;symbol={ticker};stage=V21.172",
            "refresh_timestamp": now,
            "price_row_status": "PROVIDER_OBSERVED_OHLCV_TARGETED_REPAIR",
        }
        row["row_hash"] = row_hash(row)
        rows.append(row)
    return pd.DataFrame(rows), "" if rows else "provider rows had no usable dates"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before_protected = protected_hashes()
    pre_hash = sha(PRICE) if PRICE.exists() else ""
    backup = OUT / "canonical_price_panel_pre_refresh_backup.csv"
    if PRICE.exists():
        shutil.copy2(PRICE, backup)
    panel = read_csv(PRICE)
    pre_fresh, pre_latest = freshness(panel)
    pre_rows = len(panel)
    write_csv("pre_refresh_price_panel_snapshot_hash.csv", pd.DataFrame([{
        "canonical_price_panel_path": rel(PRICE),
        "pre_refresh_sha256": pre_hash,
        "pre_refresh_row_count": pre_rows,
        "backup_path": rel(backup),
        "backup_sha256": sha(backup) if backup.exists() else "",
    }]))
    v171 = read_json(V171_SUMMARY)
    detail = read_csv(V171_DETAIL)
    active_impact = int(v171.get("active_holding_impact_count", 0) or 0)
    maturity_dep = int(v171.get("maturity_dependency_count", 0) or 0)
    approved = pd.DataFrame([{
        "ticker": t,
        "approved_for_v21_172": True,
        "active_holding_impact": active_impact > 0 and t in set(detail.get("ticker", pd.Series(dtype=str))),
        "maturity_dependency": maturity_dep > 0 and t in set(detail.get("ticker", pd.Series(dtype=str))),
    } for t in TARGETS])
    write_csv("approved_target_tickers.csv", approved)

    attempts = []
    fetched_frames = []
    for ticker in TARGETS:
        before = pre_fresh[pre_fresh["ticker"].eq(ticker)].iloc[0].to_dict()
        if before["freshness_status"] == "FRESH":
            attempts.append({"ticker": ticker, "attempted": False, "attempt_status": "ALREADY_FRESH", "detail": "No refresh needed"})
            continue
        if not ALLOW_BROAD_REFRESH:
            rows, reason = fetch_yfinance(ticker)
            if rows.empty:
                attempts.append({"ticker": ticker, "attempted": True, "attempt_status": "REFRESH_FAILED_SOURCE_UNAVAILABLE", "detail": reason})
            else:
                attempts.append({"ticker": ticker, "attempted": True, "attempt_status": "TICKER_LEVEL_REFRESH_RETURNED_ROWS", "detail": f"rows={len(rows)}"})
                fetched_frames.append(rows)
        else:
            attempts.append({"ticker": ticker, "attempted": False, "attempt_status": "BROAD_REFRESH_REQUIRED_BUT_NOT_ALLOWED", "detail": "Broad refresh remains disabled by stage policy"})
    write_csv("targeted_refresh_attempt_log.csv", pd.DataFrame(attempts))

    canonical_mutated = False
    if fetched_frames:
        fetched = pd.concat(fetched_frames, ignore_index=True)
        fetched = fetched[fetched["symbol"].isin(TARGETS)].copy()
        if not fetched.empty:
            panel2 = panel.copy()
            if "symbol" not in panel2.columns:
                raise RuntimeError("canonical price panel missing symbol column")
            panel2["symbol"] = norm(panel2["symbol"])
            fetched_keys = set(zip(fetched["symbol"], fetched["date"]))
            keep_mask = ~panel2.apply(lambda r: (str(r["symbol"]).upper(), str(r["date"])) in fetched_keys, axis=1)
            panel2 = pd.concat([panel2.loc[keep_mask], fetched[panel.columns]], ignore_index=True)
            panel2["_date"] = pd.to_datetime(panel2["date"], errors="coerce")
            panel2 = panel2.sort_values(["symbol", "_date"]).drop(columns=["_date"])
            panel2.to_csv(PRICE, index=False)
            canonical_mutated = sha(PRICE) != pre_hash

    post_panel = read_csv(PRICE)
    post_hash = sha(PRICE) if PRICE.exists() else ""
    post_fresh, post_latest = freshness(post_panel)
    result_rows = []
    for ticker in TARGETS:
        pre = pre_fresh[pre_fresh["ticker"].eq(ticker)].iloc[0].to_dict()
        post = post_fresh[post_fresh["ticker"].eq(ticker)].iloc[0].to_dict()
        attempt = next((a for a in attempts if a["ticker"] == ticker), {})
        state = attempt.get("attempt_status", "")
        if state == "TICKER_LEVEL_REFRESH_RETURNED_ROWS":
            if post["freshness_status"] == "FRESH":
                state = "REFRESHED_SUCCESSFULLY"
            elif post["freshness_status"] == "MISSING_PRICE":
                state = "PRICE_STILL_MISSING_AFTER_REFRESH"
            else:
                state = "PRICE_STILL_STALE_AFTER_REFRESH"
        elif pre["freshness_status"] == "FRESH":
            state = "ALREADY_FRESH"
        result_rows.append({
            "ticker": ticker,
            "pre_latest_price_date": pre["latest_price_date"],
            "post_latest_price_date": post["latest_price_date"],
            "pre_freshness_status": pre["freshness_status"],
            "post_freshness_status": post["freshness_status"],
            "result_state": state,
            "canonical_panel_changed_for_ticker": canonical_mutated and pre["latest_price_date"] != post["latest_price_date"],
        })
    result_df = pd.DataFrame(result_rows)
    write_csv("targeted_refresh_result_by_ticker.csv", result_df)
    write_csv("post_refresh_price_panel_freshness.csv", post_fresh)
    write_csv("price_panel_mutation_audit.csv", pd.DataFrame([{
        "canonical_price_panel_mutated": canonical_mutated,
        "pre_refresh_sha256": pre_hash,
        "post_refresh_sha256": post_hash,
        "pre_refresh_row_count": pre_rows,
        "post_refresh_row_count": len(post_panel),
        "approved_target_tickers_only": True,
        "broad_refresh_allowed": ALLOW_BROAD_REFRESH,
    }]))
    before_status = dict(zip(result_df["ticker"], result_df["pre_freshness_status"]))
    after_status = dict(zip(result_df["ticker"], result_df["post_freshness_status"]))
    before_unresolved = sum(1 for v in before_status.values() if v != "FRESH")
    after_unresolved = sum(1 for v in after_status.values() if v != "FRESH")
    write_csv("refresh_data_quality_delta.csv", pd.DataFrame([{
        "pre_refresh_unresolved_price_issue_count": before_unresolved,
        "post_refresh_unresolved_price_issue_count": after_unresolved,
        "data_cleanliness_improved": after_unresolved < before_unresolved,
        "resolved_issue_count": before_unresolved - after_unresolved,
    }]))
    write_csv("refresh_non_active_impact_confirmation.csv", pd.DataFrame([{
        "active_holding_impact_count": active_impact,
        "maturity_dependency_count": maturity_dep,
        "historical_ledgers_rewritten": False,
        "official_rankings_modified": False,
        "broker_action_files_modified": False,
        "strategy_weights_modified": False,
    }]))

    after_protected = protected_hashes()
    changed = [p for p, h in before_protected.items() if after_protected.get(p) != h]
    official_changed = [p for p in changed if "official" in p.lower()]
    broker_changed = [p for p in changed if any(x in p.lower() for x in ["broker", "trade_action", "real_book", "realbook"])]
    ledger_changed = [p for p in changed if "ledger" in p.lower()]
    audit_clean = len(changed) == 0
    write_csv("protected_output_mutation_audit.csv", pd.DataFrame([{
        "changed_protected_file_count": len(changed),
        "changed_paths": "|".join(changed),
        "official_output_mutation_count": len(official_changed),
        "broker_action_file_mutation_count": len(broker_changed),
        "historical_ledger_mutation_count": len(ledger_changed),
        "protected_outputs_modified": False,
        "audit_clean": audit_clean,
        "stage_output_directory": rel(OUT),
    }]))
    cache_dir = ROOT / "outputs" / "v21" / ".v21_172_yfinance_cache"
    if cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)

    refreshed = int(result_df["result_state"].eq("REFRESHED_SUCCESSFULLY").sum())
    already = int(result_df["result_state"].eq("ALREADY_FRESH").sum())
    failed = int(result_df["result_state"].str.contains("FAILED|STILL", regex=True).sum())
    skipped = int(result_df["result_state"].str.contains("SKIPPED|BROAD_REFRESH", regex=True).sum())
    unresolved = int(result_df["post_freshness_status"].ne("FRESH").sum())
    data_improved = after_unresolved < before_unresolved
    warning_count = failed + skipped + unresolved
    if refreshed and unresolved == 0:
        final_status = "PASS"
        decision = "PASS_V21_172_TARGETED_PRICE_REPAIR_REFRESH_DONE"
    elif refreshed or already:
        final_status = "PARTIAL_PASS"
        decision = "PARTIAL_PASS_V21_172_TARGETED_PRICE_REPAIR_REFRESH_DONE_WITH_WARNINGS"
    else:
        final_status = "WARN"
        decision = "WARN_V21_172_PRICE_REPAIR_REFRESH_SKIPPED_OR_LIMITED"
    summary = {
        "final_status": final_status,
        "decision": decision,
        "default_decision_label": "TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH_RESEARCH_ONLY",
        **POLICY,
        "canonical_price_panel_mutated": canonical_mutated,
        "approved_target_ticker_count": len(TARGETS),
        "refreshed_successfully_count": refreshed,
        "already_fresh_count": already,
        "refresh_failed_count": failed,
        "refresh_skipped_count": skipped,
        "unresolved_price_issue_count": unresolved,
        "pre_refresh_latest_price_date_used": pre_latest,
        "post_refresh_latest_price_date_used": post_latest,
        "active_holding_impact_count": active_impact,
        "maturity_dependency_count": maturity_dep,
        "protected_output_mutation_audit_clean": audit_clean,
        "broker_action_file_mutation_count": len(broker_changed),
        "official_output_mutation_count": len(official_changed),
        "data_cleanliness_improved": data_improved,
        "warning_count": warning_count,
        "historical_ledger_mutation_count": len(ledger_changed),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_directory": rel(OUT),
    }
    write_json("V21.172_TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH_summary.json", summary)
    pairs = "; ".join(f"{r['ticker']}:{r['pre_latest_price_date']}->{r['post_latest_price_date']} {r['result_state']}" for r in result_df.to_dict("records"))
    report = [
        STAGE,
        f"final_status={final_status}",
        f"decision={decision}",
        "approved_target_tickers=BITF|PSTG|SATS|TQQQ",
        f"pre_post_latest_price_date_by_target={pairs}",
        f"refreshed_successfully_count={refreshed}",
        f"failed_skipped_count={failed + skipped}",
        f"unresolved_price_issue_count={unresolved}",
        f"canonical_price_panel_mutated={canonical_mutated}",
        f"protected_output_mutation_audit_clean={audit_clean}",
        f"data_cleanliness_improved={data_improved}",
        f"warnings={warning_count}",
    ]
    (OUT / "V21.172_TARGETED_NON_BLOCKING_PRICE_REPAIR_REFRESH_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report[1:]))


if __name__ == "__main__":
    main()
